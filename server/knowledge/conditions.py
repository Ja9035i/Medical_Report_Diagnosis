"""
Curated medical knowledge base: common conditions linked to lab patterns.

Each entry has a short educational summary, the lab abnormalities that commonly
point towards it (used for the ranked differential diagnosis), the tests usually
used to confirm it, and a reference. Educational summaries only — not clinical
guidance; verify against the cited source.
"""

MEDLINEPLUS = "https://medlineplus.gov/"

CONDITIONS = [
    {
        "id": "iron_deficiency_anemia",
        "name": "Iron-deficiency anemia",
        "summary": "Anemia caused by too little iron to make hemoglobin. Typically shows low hemoglobin "
                   "with small red cells (low MCV, low MCH) and depleted iron stores (low ferritin). Common "
                   "causes include blood loss (e.g. heavy menstruation, gastrointestinal bleeding), low "
                   "dietary iron and poor absorption.",
        "patterns": [("hemoglobin", "LOW"), ("mcv", "LOW"), ("mch", "LOW"), ("ferritin", "LOW")],
        "confirm_tests": ["Serum iron, TIBC and transferrin saturation", "Evaluation for a source of blood loss"],
        "source": "MedlinePlus: Anemia",
        "url": MEDLINEPLUS + "anemia.html",
    },
    {
        "id": "b12_deficiency_anemia",
        "name": "Vitamin B12 deficiency (macrocytic) anemia",
        "summary": "Anemia with large red cells (high MCV) caused by low vitamin B12 (or folate). It can "
                   "also cause numbness, tingling and memory problems. Causes include pernicious anemia, "
                   "strict vegan diets and some medicines such as metformin.",
        "patterns": [("hemoglobin", "LOW"), ("mcv", "HIGH"), ("vitamin_b12", "LOW")],
        "confirm_tests": ["Serum folate", "Methylmalonic acid and homocysteine", "Intrinsic factor antibodies"],
        "source": "MedlinePlus: Anemia",
        "url": MEDLINEPLUS + "anemia.html",
    },
    {
        "id": "infection_inflammation",
        "name": "Acute infection or inflammation",
        "summary": "A raised white blood cell count together with raised inflammatory markers (CRP, ESR) "
                   "suggests the body is responding to an infection or another inflammatory process. "
                   "The pattern does not identify the cause; symptoms and examination guide further tests.",
        "patterns": [("wbc", "HIGH"), ("crp", "HIGH"), ("esr", "HIGH")],
        "confirm_tests": ["Clinical examination", "Cultures or imaging depending on symptoms",
                          "Repeat CRP to follow the trend"],
        "source": "MedlinePlus: Infections",
        "url": MEDLINEPLUS + "infections.html",
    },
    {
        "id": "hyperglycemia_diabetes",
        "name": "Prediabetes or diabetes (high blood sugar)",
        "summary": "Persistently high blood glucose. In common guidelines a fasting glucose of 100-125 mg/dL "
                   "or HbA1c of 5.7-6.4% suggests prediabetes, and fasting glucose of 126 mg/dL or more or "
                   "HbA1c of 6.5% or more (confirmed on repeat testing) suggests diabetes.",
        "patterns": [("glucose_fasting", "HIGH"), ("hba1c", "HIGH")],
        "confirm_tests": ["Repeat fasting glucose", "HbA1c", "Oral glucose tolerance test"],
        "source": "MedlinePlus: Diabetes",
        "url": MEDLINEPLUS + "diabetes.html",
    },
    {
        "id": "hypothyroidism",
        "name": "Hypothyroidism (underactive thyroid)",
        "summary": "The thyroid gland makes too little hormone. A high TSH is the usual first sign. Symptoms "
                   "can include tiredness, weight gain, feeling cold and constipation. Hashimoto's thyroiditis "
                   "is a common cause.",
        "patterns": [("tsh", "HIGH")],
        "confirm_tests": ["Free T4", "Thyroid peroxidase (TPO) antibodies"],
        "source": "MedlinePlus: Hypothyroidism",
        "url": MEDLINEPLUS + "hypothyroidism.html",
    },
    {
        "id": "hyperthyroidism",
        "name": "Hyperthyroidism (overactive thyroid)",
        "summary": "The thyroid gland makes too much hormone. A low TSH is the usual first sign. Symptoms "
                   "can include weight loss, fast heartbeat, anxiety and heat intolerance. Graves' disease "
                   "is a common cause.",
        "patterns": [("tsh", "LOW")],
        "confirm_tests": ["Free T4 and T3", "Thyroid antibodies", "Thyroid uptake scan if needed"],
        "source": "MedlinePlus: Hyperthyroidism",
        "url": MEDLINEPLUS + "hyperthyroidism.html",
    },
    {
        "id": "dyslipidemia",
        "name": "Dyslipidemia (abnormal cholesterol)",
        "summary": "Unhealthy blood fat levels: high total or LDL cholesterol, high triglycerides or low HDL "
                   "cholesterol. It usually causes no symptoms but raises the risk of heart disease and stroke.",
        "patterns": [("cholesterol_total", "HIGH"), ("ldl", "HIGH"), ("hdl", "LOW"), ("triglycerides", "HIGH")],
        "confirm_tests": ["Repeat fasting lipid panel", "Cardiovascular risk assessment"],
        "source": "MedlinePlus: Cholesterol",
        "url": MEDLINEPLUS + "cholesterol.html",
    },
    {
        "id": "kidney_impairment",
        "name": "Reduced kidney function",
        "summary": "Raised creatinine and urea suggest the kidneys are filtering less well. It may be "
                   "temporary (e.g. dehydration) or a sign of acute or chronic kidney disease. High potassium "
                   "can accompany reduced kidney function.",
        "patterns": [("creatinine", "HIGH"), ("bun", "HIGH"), ("potassium", "HIGH")],
        "confirm_tests": ["eGFR", "Urinalysis and urine albumin", "Kidney ultrasound if indicated"],
        "source": "MedlinePlus: Kidney Diseases",
        "url": MEDLINEPLUS + "kidneydiseases.html",
    },
    {
        "id": "liver_injury",
        "name": "Liver inflammation or injury",
        "summary": "Raised liver enzymes (ALT, AST) indicate liver cell irritation or damage; raised "
                   "bilirubin can cause jaundice. Causes include fatty liver, viral hepatitis, alcohol and "
                   "some medicines.",
        "patterns": [("alt", "HIGH"), ("ast", "HIGH"), ("bilirubin_total", "HIGH")],
        "confirm_tests": ["Hepatitis virus tests", "ALP and GGT", "Liver ultrasound"],
        "source": "MedlinePlus: Liver Diseases",
        "url": MEDLINEPLUS + "liverdiseases.html",
    },
    {
        "id": "hyperkalemia",
        "name": "Hyperkalemia (high potassium)",
        "summary": "Too much potassium in the blood, which can affect heart rhythm. Causes include kidney "
                   "problems and some medicines; a falsely high result can occur if the blood sample was "
                   "damaged (hemolysis).",
        "patterns": [("potassium", "HIGH")],
        "confirm_tests": ["Repeat potassium to exclude a sample error", "ECG", "Kidney function tests"],
        "source": "MedlinePlus: Potassium",
        "url": MEDLINEPLUS + "potassium.html",
    },
    {
        "id": "hypokalemia",
        "name": "Hypokalemia (low potassium)",
        "summary": "Too little potassium in the blood, which can cause weakness, cramps and heart rhythm "
                   "problems. Common causes are vomiting, diarrhea and diuretic medicines.",
        "patterns": [("potassium", "LOW")],
        "confirm_tests": ["Repeat potassium and magnesium", "ECG", "Review of medicines"],
        "source": "MedlinePlus: Potassium",
        "url": MEDLINEPLUS + "potassium.html",
    },
    {
        "id": "hyponatremia",
        "name": "Hyponatremia (low sodium)",
        "summary": "Low sodium in the blood, often from water imbalance. It can cause headache, confusion "
                   "and, when severe, seizures. Causes include some medicines, heart, kidney or liver disease "
                   "and drinking excessive water.",
        "patterns": [("sodium", "LOW")],
        "confirm_tests": ["Serum and urine osmolality", "Urine sodium", "Thyroid and adrenal tests if indicated"],
        "source": "MedlinePlus",
        "url": MEDLINEPLUS,
    },
    {
        "id": "thrombocytopenia",
        "name": "Thrombocytopenia (low platelets)",
        "summary": "A low platelet count, which can lead to easy bruising or bleeding. Causes include viral "
                   "infections, some medicines, immune conditions and bone marrow problems.",
        "patterns": [("platelets", "LOW")],
        "confirm_tests": ["Repeat platelet count", "Peripheral blood smear"],
        "source": "MedlinePlus",
        "url": MEDLINEPLUS,
    },
    {
        "id": "vitamin_d_deficiency",
        "name": "Vitamin D deficiency",
        "summary": "Low vitamin D, which affects calcium absorption and bone health. It is common with "
                   "limited sun exposure and can contribute to bone pain and weakness.",
        "patterns": [("vitamin_d", "LOW")],
        "confirm_tests": ["Serum calcium and phosphate", "Parathyroid hormone (PTH)"],
        "source": "MedlinePlus: Vitamin D",
        "url": MEDLINEPLUS + "vitamind.html",
    },
    {
        "id": "polycythemia",
        "name": "High red cell levels (polycythemia or dehydration)",
        "summary": "Raised hemoglobin, hematocrit and red cell count. This can reflect dehydration, smoking, "
                   "living at altitude, lung disease or, less often, a bone marrow disorder.",
        "patterns": [("hemoglobin", "HIGH"), ("hematocrit", "HIGH"), ("rbc", "HIGH")],
        "confirm_tests": ["Repeat CBC after hydration", "Erythropoietin level", "JAK2 mutation test if indicated"],
        "source": "MedlinePlus",
        "url": MEDLINEPLUS,
    },
    {
        "id": "hypercalcemia",
        "name": "Hypercalcemia (high calcium)",
        "summary": "Too much calcium in the blood, commonly caused by overactive parathyroid glands or some "
                   "cancers. It can cause thirst, constipation, kidney stones and confusion.",
        "patterns": [("calcium", "HIGH")],
        "confirm_tests": ["Parathyroid hormone (PTH)", "Vitamin D", "Repeat calcium (albumin-corrected)"],
        "source": "MedlinePlus",
        "url": MEDLINEPLUS,
    },
]

CONDITIONS_BY_ID = {c["id"]: c for c in CONDITIONS}
