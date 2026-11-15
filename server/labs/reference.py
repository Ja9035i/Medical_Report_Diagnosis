"""
Default adult reference ranges for common lab tests.

Used ONLY when a report does not state its own reference range, and ONLY when the
report's unit matches the unit below. Ranges vary between labs, ages and sexes, so
results flagged with these defaults are marked range_source="default".
Educational values — not a clinical standard.
"""

# key: (display name, aliases, unit, low, high)   low/high may be None (one-sided)
REFERENCE_RANGES = {
    "hemoglobin": ("Hemoglobin", ["hemoglobin", "haemoglobin", "hgb", "hb"], "g/dL", 12.0, 17.5),
    "hematocrit": ("Hematocrit", ["hematocrit", "haematocrit", "hct", "pcv"], "%", 36.0, 52.0),
    "rbc": ("RBC count", ["red blood cell count", "red blood cells", "red blood cell", "rbc count", "rbc"], "10^6/uL", 4.2, 5.9),
    "wbc": ("WBC count", ["white blood cell count", "white blood cells", "white blood cell", "total leucocyte count",
                          "total leukocyte count", "total wbc count", "wbc count", "tlc", "wbc"], "10^3/uL", 4.0, 11.0),
    "platelets": ("Platelet count", ["platelet count", "platelets", "plt"], "10^3/uL", 150.0, 450.0),
    "mcv": ("MCV", ["mean corpuscular volume", "mcv"], "fL", 80.0, 100.0),
    "mch": ("MCH", ["mean corpuscular hemoglobin", "mch"], "pg", 27.0, 33.0),
    "mchc": ("MCHC", ["mean corpuscular hemoglobin concentration", "mchc"], "g/dL", 32.0, 36.0),
    "esr": ("ESR", ["erythrocyte sedimentation rate", "esr"], "mm/hr", 0.0, 20.0),
    "crp": ("C-reactive protein", ["c-reactive protein", "c reactive protein", "crp"], "mg/L", None, 5.0),
    "glucose_fasting": ("Fasting glucose", ["fasting blood sugar", "fasting plasma glucose", "fasting blood glucose",
                                            "fasting glucose", "glucose fasting", "fbs", "glucose"], "mg/dL", 70.0, 99.0),
    "hba1c": ("HbA1c", ["glycated hemoglobin", "glycosylated hemoglobin", "hba1c", "a1c"], "%", 4.0, 5.6),
    "creatinine": ("Creatinine", ["serum creatinine", "creatinine"], "mg/dL", 0.6, 1.3),
    "bun": ("Blood urea nitrogen", ["blood urea nitrogen", "bun"], "mg/dL", 7.0, 20.0),
    "sodium": ("Sodium", ["serum sodium", "sodium", "na"], "mmol/L", 135.0, 145.0),
    "potassium": ("Potassium", ["serum potassium", "potassium", "k"], "mmol/L", 3.5, 5.1),
    "chloride": ("Chloride", ["chloride", "cl"], "mmol/L", 98.0, 107.0),
    "calcium": ("Calcium", ["serum calcium", "total calcium", "calcium", "ca"], "mg/dL", 8.5, 10.5),
    "alt": ("ALT (SGPT)", ["alanine aminotransferase", "alt", "sgpt"], "U/L", 7.0, 56.0),
    "ast": ("AST (SGOT)", ["aspartate aminotransferase", "ast", "sgot"], "U/L", 10.0, 40.0),
    "bilirubin_total": ("Total bilirubin", ["total bilirubin", "bilirubin total", "bilirubin"], "mg/dL", 0.1, 1.2),
    "tsh": ("TSH", ["thyroid stimulating hormone", "tsh"], "mIU/L", 0.4, 4.0),
    "ferritin": ("Ferritin", ["serum ferritin", "ferritin"], "ng/mL", 30.0, 400.0),
    "cholesterol_total": ("Total cholesterol", ["total cholesterol", "cholesterol total", "cholesterol"], "mg/dL", None, 200.0),
    "ldl": ("LDL cholesterol", ["ldl cholesterol", "ldl-c", "ldl"], "mg/dL", None, 100.0),
    "hdl": ("HDL cholesterol", ["hdl cholesterol", "hdl-c", "hdl"], "mg/dL", 40.0, None),
    "triglycerides": ("Triglycerides", ["triglycerides", "triglyceride", "tg"], "mg/dL", None, 150.0),
    "vitamin_d": ("Vitamin D (25-OH)", ["25-hydroxy vitamin d", "25-oh vitamin d", "vitamin d3", "vitamin d"], "ng/mL", 30.0, 100.0),
    "vitamin_b12": ("Vitamin B12", ["vitamin b12", "b12"], "pg/mL", 200.0, 900.0),
}

# Units that mean the same thing (all compared after normalize_unit()).
UNIT_EQUIVALENTS = {
    "uiu/ml": "miu/l",
    "x10^3/ul": "10^3/ul",
    "k/ul": "10^3/ul",
    "thou/ul": "10^3/ul",
    "10^9/l": "10^3/ul",
    "x10^9/l": "10^3/ul",
    "x10^6/ul": "10^6/ul",
    "m/ul": "10^6/ul",
    "10^12/l": "10^6/ul",
    "x10^12/l": "10^6/ul",
    "meq/l": "mmol/l",
    "gm/dl": "g/dl",
    "gm%": "g/dl",
    "iu/l": "u/l",
    "mm/h": "mm/hr",
    "mm/1sthr": "mm/hr",
}


def normalize_unit(unit):
    if not unit:
        return None
    u = unit.strip().lower().replace("µ", "u").replace("μ", "u").replace(" ", "")
    u = u.replace("cumm", "ul").replace("mcl", "ul")
    return UNIT_EQUIVALENTS.get(u, u)
