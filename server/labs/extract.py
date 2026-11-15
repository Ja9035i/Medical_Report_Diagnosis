"""
Deterministic lab-value extraction.

Turns free report text such as
    "C-Reactive Protein (CRP): 12 mg/L (Reference: < 5 mg/L)"
    "Hemoglobin 9.1 g/dL 13.0 - 17.0"
into structured results, and flags each value HIGH / LOW / NORMAL with plain
Python comparisons — no LLM involved, so flags are reproducible and verifiable.
"""
import re

from .reference import REFERENCE_RANGES, normalize_unit

# 11,500  |  9.1  |  130
NUM = r"\d{1,3}(?:,\d{3})+(?:\.\d+)?|\d+(?:\.\d+)?"

# Words allowed between the test name and its value: "WBC Count: 11,500", "Glucose, Fasting: 130"
GAP = r"(?:\s*,?\s*(?:fasting|random|count|level|levels|value|result|total|serum))?\s*[:=\-–]?\s*"
VALUE = rf"(?P<value>{NUM})"
UNIT = r"(?:\s*(?P<unit>(?:x\s?)?10\^\d+/[A-Za-zµμ]+|/?[A-Za-zµμ%][A-Za-zµμ%0-9/^.]*))?"

RANGE_KEYWORD = (
    r"(?:bio\.?\s*ref(?:erence)?\.?\s*(?:interval|range)?"
    r"|ref(?:erence)?(?:\s*(?:range|interval|value)s?)?"
    r"|normal(?:\s*range)?|range)"
)
BOUND = (
    rf"(?:(?P<lt>[<≤]|less than|up\s?to)\s*(?P<lt_v>{NUM})"
    rf"|(?P<gt>[>≥]|more than|greater than)\s*(?P<gt_v>{NUM})"
    rf"|(?P<lo>{NUM})\s*(?:-|–|to)\s*(?P<hi>{NUM}))"
)
RANGE_WITH_KEYWORD = re.compile(rf"^\s*[\(\[]?\s*{RANGE_KEYWORD}\s*[:\-]?\s*{BOUND}", re.I)
RANGE_IMMEDIATE = re.compile(rf"^\s*[\(\[]?\s*(?P<lo>{NUM})\s*(?:-|–|to)\s*(?P<hi>{NUM})", re.I)

NOT_UNITS = {"reference", "ref", "range", "normal", "high", "low", "h", "l", "and", "or",
             "with", "is", "was", "in", "of", "bio", "the", "to"}

# (alias, key) pairs, longest alias first so "hdl cholesterol" wins over "cholesterol"
_ALIASES = sorted(
    ((alias, key) for key, spec in REFERENCE_RANGES.items() for alias in spec[1]),
    key=lambda pair: -len(pair[0]),
)
_PATTERNS = [
    (alias, key, re.compile(
        rf"(?<![A-Za-z0-9]){re.escape(alias)}(?![A-Za-z0-9]){GAP}{VALUE}{UNIT}", re.I))
    for alias, key in _ALIASES
]


def _to_float(text):
    return float(text.replace(",", ""))


def _clean_text(text):
    flat = re.sub(r"\s+", " ", text)
    # Drop short abbreviations in brackets: "White Blood Cell (WBC) Count" -> "White Blood Cell Count"
    return re.sub(r"\s*\((?=[^)]{1,12}\))[^\d)]*\)", "", flat)


def _clean_unit(unit):
    if not unit:
        return None
    unit = unit.strip().rstrip(".,;:")
    return None if not unit or unit.lower() in NOT_UNITS else unit


def _parse_range(rest):
    """Return (low, high) from the text right after a value, or (None, None)."""
    m = RANGE_WITH_KEYWORD.match(rest) or RANGE_IMMEDIATE.match(rest)
    if not m:
        return None, None
    groups = m.groupdict()
    if groups.get("lo") and groups.get("hi"):
        return _to_float(groups["lo"]), _to_float(groups["hi"])
    if groups.get("lt_v"):
        return None, _to_float(groups["lt_v"])
    if groups.get("gt_v"):
        return _to_float(groups["gt_v"]), None
    return None, None


def flag_value(value, low, high):
    if low is None and high is None:
        return "UNKNOWN"
    if low is not None and value < low:
        return "LOW"
    if high is not None and value > high:
        return "HIGH"
    return "NORMAL"


def extract_lab_values(text):
    """
    Find known lab tests in `text`. Returns a list (in report order) of:
    {key, test, value, unit, ref_low, ref_high, range_source, flag, raw}
      range_source: "report" (range printed in the report), "default" (built-in
      range, only when units match) or None (no usable range -> flag UNKNOWN).
    """
    flat = _clean_text(text or "")
    taken_spans = []
    found = {}

    for alias, key, pattern in _PATTERNS:
        if key in found:
            continue
        for m in pattern.finditer(flat):
            start, end = m.span()
            if any(start < t_end and t_start < end for t_start, t_end in taken_spans):
                continue

            unit = _clean_unit(m.group("unit"))
            if len(alias) <= 2 and not unit:
                continue  # very short names (K, Na, Hb) need a unit to avoid false matches

            value = _to_float(m.group("value"))
            range_text_start = m.end() if unit else m.end("value")
            ref_low, ref_high = _parse_range(flat[range_text_start:range_text_start + 80])
            range_source = "report" if (ref_low is not None or ref_high is not None) else None

            display, _, default_unit, default_low, default_high = REFERENCE_RANGES[key]
            if range_source is None and unit and normalize_unit(unit) == normalize_unit(default_unit):
                ref_low, ref_high, range_source = default_low, default_high, "default"

            found[key] = {
                "key": key,
                "test": display,
                "value": value,
                "unit": unit,
                "ref_low": ref_low,
                "ref_high": ref_high,
                "range_source": range_source,
                "flag": flag_value(value, ref_low, ref_high),
                "raw": m.group(0).strip(),
                "_pos": start,
            }
            taken_spans.append((start, end))
            break

    results = sorted(found.values(), key=lambda r: r["_pos"])
    for r in results:
        r.pop("_pos")
    return results


def abnormal(results):
    return [r for r in results if r["flag"] in ("HIGH", "LOW")]
