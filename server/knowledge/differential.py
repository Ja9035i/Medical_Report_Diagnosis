"""
Rule-based ranked differential diagnosis.

Each knowledge-base condition lists the lab abnormalities that point towards it.
For a report's labs:
  supporting  = pattern labs measured with the expected flag (e.g. ferritin LOW)
  against     = pattern labs measured but NOT abnormal in that direction
  not_measured= pattern labs missing from the report (suggest testing them)

  score = (supporting - 0.5 * against) / number_of_pattern_labs

Deterministic and explainable: every likelihood can be traced to specific values.
"""
from ..labs.reference import REFERENCE_RANGES
from .conditions import CONDITIONS


def _describe(lab) -> str:
    return f"{lab['test']} {lab['value']:g} {lab.get('unit') or ''}".strip() + f" ({lab['flag']})"


def likelihood_label(score: float, supporting: int, total: int) -> str:
    if score >= 0.6 and (supporting >= 2 or total == 1):
        return "High"
    if score >= 0.3:
        return "Medium"
    return "Low"


def rank_differential(labs, max_results: int = 5):
    measured = {}
    for lab in labs or []:
        measured.setdefault(lab["key"], lab)  # first value per test

    ranked = []
    for condition in CONDITIONS:
        supporting, against, not_measured = [], [], []
        for key, expected in condition["patterns"]:
            lab = measured.get(key)
            if lab is None or lab["flag"] == "UNKNOWN":
                not_measured.append(REFERENCE_RANGES[key][0])
            elif lab["flag"] == expected:
                supporting.append(lab)
            else:
                against.append(lab)

        if not supporting:
            continue
        total = len(condition["patterns"])
        score = (len(supporting) - 0.5 * len(against)) / total
        ranked.append({
            "id": condition["id"],
            "name": condition["name"],
            "likelihood": likelihood_label(score, len(supporting), total),
            "score": round(score, 2),
            "supporting": [_describe(lab) for lab in supporting],
            "against": [_describe(lab) for lab in against],
            "not_measured": not_measured,
            "confirm_tests": condition["confirm_tests"],
            "source": condition["source"],
            "url": condition["url"],
        })

    ranked.sort(key=lambda d: (-d["score"], -len(d["supporting"]), d["name"]))
    return ranked[:max_results]


def format_differential(differential) -> str:
    if not differential:
        return "No condition patterns matched the abnormal lab values."
    lines = []
    for i, d in enumerate(differential, start=1):
        line = f"{i}. {d['name']} — {d['likelihood']} (supporting: {', '.join(d['supporting'])}"
        if d["against"]:
            line += f"; against: {', '.join(d['against'])}"
        if d["not_measured"]:
            line += f"; not measured: {', '.join(d['not_measured'])}"
        lines.append(line + ")")
    return "\n".join(lines)
