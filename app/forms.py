"""Turn a scanned form into a form definition the agent can fill.

Sarvam Vision (Doc AI Extract) lists the form's blanks; this module gives each one a key,
a kind (name/date/phone/number/choice/text) for validation, and a spoken-friendly hint.
"""

import re

from . import config

MAX_FIELDS = 20

# What we ask Sarvam Vision for. One call returns the title, every blank, and tick-box options.
SCAN_SCHEMA = {
    "type": "object",
    "properties": {
        "form_title": {"type": "string",
                       "description": "Title of the form translated to English, e.g. 'Application for Income Certificate'"},
        "fields": {
            "type": "array",
            "description": "Every blank the applicant must fill, in printed order. Skip signature, photo, "
                           "thumb impression and 'for office use only' boxes.",
            "items": {"type": "object", "properties": {
                "label": {"type": "string", "description": "The field's label translated to English"},
                "options": {"type": "string",
                            "description": "If the field is a tick-box or multiple choice, the options separated by '|', else empty"},
                "filled_value": {"type": "string", "description": "Value already written in the blank, empty if blank"},
            }},
        },
    },
}

# Never asked out loud; the user writes these by hand.
_SENSITIVE = re.compile(r"aadha?ar|bank|account|ifsc|\bpan\b|password|otp|pin code of atm|card number", re.I)


def _kind(label: str, options: list) -> str:
    l = label.lower()
    if options:
        return "choice"
    if _SENSITIVE.search(l):
        return "sensitive"
    if re.search(r"\b(date|dob|d\.o\.b)\b|birth", l):
        return "date"
    if re.search(r"mobile|phone|contact no|whatsapp", l):
        return "phone"
    if re.search(r"income|amount|salary|\brs\b|₹|rupees|\bage\b|pin ?code|pincode", l):
        return "number"
    if re.search(r"\bname\b", l):
        return "name"
    return "text"


_HINTS = {
    "name": "Full name, written in English letters",
    "date": "Format DD/MM/YYYY",
    "phone": "10-digit Indian mobile number, digits only",
    "number": "Digits only",
    "choice": "Pick one of the options",
    "text": "Short answer in English",
    "sensitive": "Sensitive: the applicant writes this by hand",
}


def _key(label: str, used: set) -> str:
    base = re.sub(r"[^a-z0-9]+", "_", label.lower()).strip("_")[:40] or "field"
    key, n = base, 2
    while key in used:
        key, n = f"{base}_{n}", n + 1
    used.add(key)
    return key


def from_scan(result: dict) -> tuple[dict, dict]:
    """Build (form, prefilled_values) from Sarvam Vision's extract result."""
    used, fields, prefilled = set(), [], {}
    for raw in (result.get("fields") or [])[:MAX_FIELDS]:
        label = re.sub(r"^\s*\d+[.)]\s*", "", str(raw.get("label") or "")).strip().rstrip(":").strip()
        if not label:
            continue
        options = [o.strip() for o in str(raw.get("options") or "").split("|") if o.strip()]
        kind = _kind(label, options)
        key = _key(label, used)
        fields.append({"key": key, "label": label, "kind": kind, "options": options, "hint": _HINTS[kind]})
        if raw.get("filled_value") and kind != "sensitive":
            prefilled[key] = str(raw["filled_value"]).strip()
    title = str(result.get("form_title") or "").strip() or "Scanned form"
    return {"id": "scanned", "title": title, "fields": fields}, prefilled


def sample_form() -> dict:
    """The built-in scholarship form, in the same shape as a scanned one."""
    kinds = {"student_name": "name", "father_name": "name", "date_of_birth": "date",
             "mobile_number": "phone", "institution_name": "text", "annual_family_income": "number"}
    return {"id": config.FORM["id"], "title": config.FORM["title"],
            "fields": [{"key": f["key"], "label": f["label"], "kind": kinds[f["key"]], "options": [],
                        "hint": f["hint"]} for f in config.FORM["fields"]]}


# Shown in mock mode instead of calling Sarvam Vision.
MOCK_SCAN = {
    "form_title": "Application for Income Certificate",
    "fields": [
        {"label": "Name of the Applicant"}, {"label": "Father's / Husband's Name"},
        {"label": "Date of Birth (DD/MM/YYYY)"}, {"label": "Mobile Number"},
        {"label": "Address (Village / Mandal / District)"}, {"label": "Occupation"},
        {"label": "Annual Income from all sources (Rs.)"}, {"label": "Purpose of Certificate"},
        {"label": "Gender", "options": "Male|Female|Other"},
    ],
}
