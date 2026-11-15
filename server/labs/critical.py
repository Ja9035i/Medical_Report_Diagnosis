"""
Critical-value ("red flag") rules.

Hard-coded thresholds, modelled on typical hospital critical-value lists. When a
value crosses one, the app shows an URGENT banner BEFORE any AI text. This is
decided by code, never by the LLM. Illustrative values — not a clinical standard.
"""
from .reference import REFERENCE_RANGES, normalize_unit

# key: (critical low, critical high), in the default unit from REFERENCE_RANGES
CRITICAL_LIMITS = {
    "potassium": (2.5, 6.5),
    "sodium": (120.0, 160.0),
    "glucose_fasting": (50.0, 400.0),
    "hemoglobin": (7.0, 20.0),
    "hematocrit": (20.0, 60.0),
    "platelets": (20.0, 1000.0),
    "wbc": (2.0, 30.0),
    "calcium": (6.0, 13.0),
}

# Counts reported per microlitre (e.g. "11,500/uL") -> thousands per microlitre
_PER_UL_UNITS = {"/ul", "cells/ul", "/mm3", "cells/mm3"}


def value_in_default_unit(result):
    """Convert a result to its default unit, or return None if the unit is not understood."""
    default_unit = REFERENCE_RANGES[result["key"]][2]
    unit = normalize_unit(result.get("unit"))
    if unit is None:
        return None
    if unit == normalize_unit(default_unit):
        return result["value"]
    if normalize_unit(default_unit) == "10^3/ul" and unit in _PER_UL_UNITS:
        return result["value"] / 1000.0
    return None


def check_critical(results):
    """
    Mark each lab result with `critical` / `critical_reason` and return the list
    of critical alerts (human-readable strings), most important first.
    """
    alerts = []
    for result in results:
        result["critical"] = False
        result["critical_reason"] = None
        limits = CRITICAL_LIMITS.get(result["key"])
        if not limits:
            continue
        value = value_in_default_unit(result)
        if value is None:
            continue
        crit_low, crit_high = limits
        default_unit = REFERENCE_RANGES[result["key"]][2]
        if crit_low is not None and value < crit_low:
            reason = f"{result['test']} {result['value']:g} {result['unit']} is below the critical limit ({crit_low:g} {default_unit})"
        elif crit_high is not None and value > crit_high:
            reason = f"{result['test']} {result['value']:g} {result['unit']} is above the critical limit ({crit_high:g} {default_unit})"
        else:
            continue
        result["critical"] = True
        result["critical_reason"] = reason
        alerts.append(reason)
    return alerts
