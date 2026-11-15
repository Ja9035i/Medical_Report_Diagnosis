"""
Remove personal identifiers from report text before it is chunked, embedded,
stored in Pinecone or sent to an LLM.

Rule-based and conservative: labelled header fields (Name, Patient ID, DOB,
Phone, Address), plus free-standing emails, phone numbers and 12-digit
national ID numbers. Age and sex are kept because they are clinically relevant.
Lab lines are not touched.
"""
import os
import re

# Labels that can follow a value on the same line (so "Name: X  Age: 38" keeps "Age: 38")
_NEXT_LABEL = (r"(?=\s{2,}|\s+(?:age|sex|gender|date\s+of\s+birth|dob|d\.o\.b|patient\s+id|mrn|uhid|"
               r"phone|mobile|contact|address|email|date\s+of\s+report|ref(?:erred)?\s+by)\b|$)")

_LABELLED_FIELDS = [
    # (placeholder, label pattern)  -- label must start the line or follow "Patient"
    ("[NAME]", r"(?:patient(?:'s)?\s+)?(?:full\s+)?name"),
    ("[ID]", r"(?:patient\s+id|patient\s+no\.?|mrn|uhid|reg(?:istration)?\.?\s*no\.?|lab\s+no\.?|sample\s+id)"),
    ("[DOB]", r"(?:date\s+of\s+birth|d\.?o\.?b\.?)"),
    ("[PHONE]", r"(?:phone|mobile|contact(?:\s+no\.?)?|tel\.?)"),
    ("[ADDRESS]", r"(?:address)"),
]

_FIELD_PATTERNS = [
    (placeholder, placeholder.strip("[]").lower(),
     re.compile(rf"(?im)^(?P<label>[ \t]*{label}[ \t]*[:\-][ \t]*)(?P<value>[^\n]*?){_NEXT_LABEL}"))
    for placeholder, label in _LABELLED_FIELDS
]

_EMAIL = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")
_NATIONAL_ID = re.compile(r"(?<!\d)\d{4}[ -]\d{4}[ -]\d{4}(?!\d)")  # e.g. Aadhaar-style 1234 5678 9012
_PHONE = re.compile(r"(?<![\d.,])(?:\+\d{1,3}[ -]?)?(?:\d[ -]?){9,12}\d(?![\d.,])")


def redaction_enabled() -> bool:
    return os.getenv("PII_REDACTION", "true").strip().lower() in ("1", "true", "yes")


def redact_text(text: str):
    """Return (redacted_text, counts) where counts says how many of each identifier were removed."""
    counts = {"name": 0, "id": 0, "dob": 0, "phone": 0, "address": 0, "email": 0}
    if not text:
        return text, counts

    for placeholder, key, pattern in _FIELD_PATTERNS:
        def replace_field(m, placeholder=placeholder, key=key):
            if not m.group("value").strip() or m.group("value").strip() == placeholder:
                return m.group(0)
            counts[key] += 1
            return m.group("label") + placeholder
        text = pattern.sub(replace_field, text)

    def replace_with(placeholder, key):
        def _replace(m):
            counts[key] += 1
            return placeholder
        return _replace

    text = _EMAIL.sub(replace_with("[EMAIL]", "email"), text)
    text = _NATIONAL_ID.sub(replace_with("[ID]", "id"), text)

    def replace_phone(m):
        digits = re.sub(r"\D", "", m.group(0))
        if 10 <= len(digits) <= 13:
            counts["phone"] += 1
            return "[PHONE]"
        return m.group(0)

    text = _PHONE.sub(replace_phone, text)
    return text, counts
