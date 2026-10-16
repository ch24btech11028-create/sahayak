"""Forms and their fields: reading a scanned form, and cleaning/validating answers for it."""

import re
from dataclasses import asdict, dataclass, field

from . import sarvam

MAX_FIELDS = 20

# What Sarvam Vision is asked to return for a photo of a form: one call gives the title,
# every blank in printed order, and the options of tick-box fields.
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

HINTS = {
    "name": "Full name, written in English letters",
    "date": "Format DD/MM/YYYY",
    "phone": "10-digit Indian mobile number, digits only",
    "number": "Digits only",
    "choice": "Pick one of the options",
    "text": "Short answer in English",
    "sensitive": "Sensitive: the applicant writes this by hand",
}

# Sensitive fields are never asked out loud; the applicant writes them on paper.
_SENSITIVE = re.compile(r"aadha?ar|bank|account|ifsc|\bpan\b|password|otp|card number", re.I)
_KIND_PATTERNS = [
    ("date", re.compile(r"\b(date|dob|d\.o\.b)\b|birth", re.I)),
    ("phone", re.compile(r"mobile|phone|contact no|whatsapp", re.I)),
    ("number", re.compile(r"income|amount|salary|\brs\b|₹|rupees|\bage\b|pin ?code", re.I)),
    ("name", re.compile(r"\bname\b", re.I)),
]


@dataclass
class Field:
    key: str
    label: str
    kind: str                      # one of HINTS
    options: list[str] = field(default_factory=list)

    @property
    def hint(self) -> str:
        return HINTS[self.kind]

    @property
    def askable(self) -> bool:
        return self.kind != "sensitive"


@dataclass
class Form:
    title: str
    fields: list[Field]

    def get(self, key: str) -> Field | None:
        return next((f for f in self.fields if f.key == key), None)

    @property
    def askable(self) -> list[Field]:
        return [f for f in self.fields if f.askable]


def _kind(label: str, options: list[str]) -> str:
    if options:
        return "choice"
    if _SENSITIVE.search(label):
        return "sensitive"
    return next((kind for kind, pattern in _KIND_PATTERNS if pattern.search(label)), "text")


def _unique_key(label: str, used: set[str]) -> str:
    base = re.sub(r"[^a-z0-9]+", "_", label.lower()).strip("_")[:40] or "field"
    key, n = base, 2
    while key in used:
        key, n = f"{base}_{n}", n + 1
    used.add(key)
    return key


def from_scan(result: dict) -> tuple[Form, dict[str, str]]:
    """Build a Form from Sarvam Vision's result, plus any values already written on the paper."""
    used: set[str] = set()
    fields, prefilled = [], {}
    for raw in (result.get("fields") or [])[:MAX_FIELDS]:
        label = re.sub(r"^\s*\d+[.)]\s*", "", str(raw.get("label") or "")).strip().rstrip(":").strip()
        if not label:
            continue
        options = [o.strip() for o in str(raw.get("options") or "").split("|") if o.strip()]
        f = Field(_unique_key(label, used), label, _kind(label, options), options)
        fields.append(f)
        if raw.get("filled_value") and f.askable:
            prefilled[f.key] = str(raw["filled_value"])
    title = str(result.get("form_title") or "").strip() or "Scanned form"
    return Form(title, fields), prefilled


def id_document_schema(form: Form) -> dict:
    """Schema for reading this form's answers off an ID card, marksheet or certificate."""
    return {"type": "object", "properties": {
        f.key: {"type": "string", "description": f"{f.label}. {f.hint}"} for f in form.askable}}


def normalize(f: Field, value: str, lang: str) -> str:
    """Put an answer in the shape the form needs (digits, an exact option, English letters)."""
    value = str(value).strip()
    if f.kind in ("phone", "number"):
        return re.sub(r"\D", "", value)
    if f.kind == "choice":
        low = value.lower()
        exact = next((o for o in f.options if o.lower() == low), None)
        if exact:
            return exact
        # Whole words, longest option first, so "Female" never matches "Male".
        for option in sorted(f.options, key=len, reverse=True):
            if re.search(rf"\b{re.escape(option.lower())}\b", low):
                return option
        return value
    if f.kind in ("name", "text"):
        try:
            return sarvam.romanise(value, lang)
        except Exception:
            return value
    return value


def problem(f: Field, value: str) -> str | None:
    """Why a normalised answer can't go on the form, or None if it can."""
    if not f.askable:
        return "this field is for the applicant to write by hand"
    if not value:
        return "empty"
    checks = {
        "phone": (re.fullmatch(r"[6-9]\d{9}", value), "must be a 10-digit Indian mobile number"),
        "date": (re.fullmatch(r"\d{2}/\d{2}/\d{4}", value), "must be a date as DD/MM/YYYY"),
        "number": (value.isdigit(), "must be digits only"),
        "name": (len(value) >= 2 and not re.search(r"\d", value), "must be a person's name, not numbers"),
        "choice": (value in f.options, f"must be one of: {', '.join(f.options)}"),
    }
    ok, reason = checks.get(f.kind, (True, ""))
    return None if ok else reason


def to_dict(f: Field) -> dict:
    return {**asdict(f), "hint": f.hint}
