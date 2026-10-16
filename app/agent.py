"""The form-filling agent: holds session state and decides, each turn, which fields to
update and what to say next. Works for any form: the built-in sample or one scanned by
Sarvam Vision (see forms.py)."""

import re
import time
import uuid
from concurrent.futures import ThreadPoolExecutor

from . import config, sarvam

SESSIONS: dict[str, dict] = {}
_label_cache: dict[tuple, str] = {}


def _askable(s: dict) -> list:
    """Fields the agent asks for. Sensitive ones (Aadhaar, bank…) are left for the user's own hand."""
    return [f for f in s["form"]["fields"] if f["kind"] != "sensitive"]


def _field(s: dict, key: str) -> dict | None:
    return next((f for f in s["form"]["fields"] if f["key"] == key), None)


def _turn_schema(s: dict) -> dict:
    return {
        "type": "object",
        "additionalProperties": False,
        "required": ["updates", "reply", "done"],
        "properties": {
            "updates": {
                "type": "array",
                "description": "Fields to set or correct from what the user just said. Empty if none.",
                "items": {
                    "type": "object", "additionalProperties": False, "required": ["field", "value"],
                    "properties": {
                        "field": {"type": "string", "enum": [f["key"] for f in _askable(s)]},
                        "value": {"type": "string"},
                    },
                },
            },
            "reply": {"type": "string", "description": "What Sahayak says next, in the user's language."},
            "done": {"type": "boolean", "description": "True only after the user confirmed the full read-back."},
        },
    }


def _local_labels(form: dict, lang: str) -> dict:
    """Field labels in the user's language, translated in parallel and cached."""
    todo = [f for f in form["fields"] if (f["label"], lang) not in _label_cache]
    if todo:
        try:
            with ThreadPoolExecutor(max_workers=6) as pool:
                out = list(pool.map(lambda f: sarvam.translate(f["label"], lang), todo))
        except Exception:
            out = [f["label"] for f in todo]
        for f, t in zip(todo, out):
            _label_cache[(f["label"], lang)] = t
    return {f["key"]: _label_cache.get((f["label"], lang), f["label"]) for f in form["fields"]}


def _system_prompt(s: dict) -> str:
    lang = config.LANGUAGES[s["lang"]]
    lines = []
    for f in _askable(s):
        v = s["values"].get(f["key"])
        extra = f"; options: {' / '.join(f['options'])}" if f["options"] else ""
        lines.append(f'- {f["key"]} ({f["label"]}; {f["hint"]}{extra}): {v if v else "MISSING"}')
    sensitive = [f["label"] for f in s["form"]["fields"] if f["kind"] == "sensitive"]
    sens_line = (f"\nThese fields are left for the user to write by hand; never ask for them: {', '.join(sensitive)}."
                 if sensitive else "")
    return f"""You are Sahayak, a warm, patient assistant helping someone fill the "{s['form']['title']}" by voice.
The user may not read English. Speak ONLY in {lang['english']} ({lang['name']}), using simple everyday words.
English words that people commonly mix in (form, mobile, college) are fine. Your reply is spoken aloud by TTS,
so keep it to 1-2 short sentences, no lists, no markdown, no emojis.
In replies, always write numbers and dates as digits (9840950950, 12/03/2003, 200000); never spell digits out as words.

Current form state:
{chr(10).join(lines)}{sens_line}

How to work:
1. Extract any field values from the user's latest message into `updates`, including corrections to earlier values.
2. Store values in English/Latin script on the form: names romanised (e.g. "Ravi Kumar"), dates as DD/MM/YYYY,
   mobile as exactly 10 digits, amounts as digits only in rupees (e.g. "2 lakh" -> "200000"), other answers as
   short English text (e.g. "किसान" -> "Farmer"). For fields with options, the value must be exactly one option.
   Convert spoken numbers in any language to digits.
3. If a value is unclear or invalid (e.g. 9 digits for mobile), do not save it; ask again politely.
4. Ask for ONE missing field at a time, in the order listed. When asking about a field with options, say the options.
5. When nothing is MISSING, read back all values briefly and ask the user to confirm.
   Set done=true only when the user has confirmed that read-back. If they correct something, update it and read back again.
6. Never ask for Aadhaar, bank account, passwords or OTPs.
7. You only fill the form; you cannot submit it. When done, say the form is ready to print or save as PDF
   and take to the office, and remind them to sign it."""


def create_session(lang: str, form: dict, prefilled: dict | None = None) -> dict:
    sid = uuid.uuid4().hex[:12]
    s = {"id": sid, "lang": lang, "form": form, "values": {}, "history": [], "done": False,
         "labels": _local_labels(form, lang), "scan": None}
    for k, v in (prefilled or {}).items():
        value = _clean(s, k, v)
        if _field(s, k) and not _invalid(s, k, value):
            s["values"][k] = value
    SESSIONS[sid] = s
    return s


_MOCK_VALUES = {"name": "Ravi Kumar", "date": "12/03/2003", "phone": "9840950950", "number": "200000",
                "text": "Sangareddy, Telangana"}


def _mock_turn(s: dict, user_text: str) -> dict:
    missing = [f for f in _askable(s) if not s["values"].get(f["key"])]
    if user_text == "(start)":
        return {"updates": [], "done": False,
                "reply": f"नमस्ते! मैं सहायक हूँ। चलिए आपका {s['form']['title']} भरते हैं। "
                         f"{missing[0]['label'] if missing else 'सब'} बताइए।"}
    if user_text.startswith("I uploaded a document"):
        return {"updates": [], "done": False, "reply": "Document से कुछ जानकारी भर दी है। बाकी के लिए कुछ सवाल पूछती हूँ।"}
    if not missing:
        return {"updates": [], "done": True, "reply": "धन्यवाद! आपका form तैयार है।"}
    f = missing[0]
    value = f["options"][0] if f["options"] else _MOCK_VALUES.get(f["kind"], "Sample")
    reply = f"ठीक है। अब {missing[1]['label']} बताइए।" if len(missing) > 1 else "सब जानकारी मिल गई। क्या सब सही है?"
    return {"updates": [{"field": f["key"], "value": value}], "done": False, "reply": reply}


def _clean(s: dict, key: str, value: str) -> str:
    f = _field(s, key)
    value = str(value).strip()
    if not f:
        return value
    if f["kind"] in ("phone", "number"):
        return re.sub(r"\D", "", value)
    if f["kind"] == "choice":
        low = value.lower()
        exact = [o for o in f["options"] if o.lower() == low]
        if exact:
            return exact[0]
        # Whole-word match, longest option first, so "Female" never matches "Male".
        for o in sorted(f["options"], key=len, reverse=True):
            if re.search(rf"\b{re.escape(o.lower())}\b", low):
                return o
        return value
    if f["kind"] in ("name", "text"):
        return sarvam.to_latin(value, s["lang"])
    return value


def _invalid(s: dict, key: str, value: str) -> str | None:
    """Return a reason if a cleaned value can't go on the form."""
    f = _field(s, key)
    if not f or f["kind"] == "sensitive":
        return "not a field Sahayak may fill"
    if not value:
        return "empty"
    kind = f["kind"]
    if kind == "phone" and not re.fullmatch(r"[6-9]\d{9}", value):
        return "must be a 10-digit Indian mobile number"
    if kind == "date" and not re.fullmatch(r"\d{2}/\d{2}/\d{4}", value):
        return "must be a date as DD/MM/YYYY"
    if kind == "number" and not value.isdigit():
        return "must be digits only"
    if kind == "name" and (re.search(r"\d", value) or len(value) < 2):
        return "must be a person's name, not numbers"
    if kind == "choice" and value not in f["options"]:
        return f"must be one of: {', '.join(f['options'])}"
    return None


def run_turn(s: dict, user_text: str) -> dict:
    """One agent step: read the user's words, update the form, decide what to say."""
    t0 = time.time()
    schema = _turn_schema(s)
    if config.MOCK:
        out = _mock_turn(s, user_text)
    else:
        messages = [{"role": "system", "content": _system_prompt(s)}]
        messages += s["history"][-12:]
        messages.append({"role": "user", "content": user_text if user_text != "(start)"
                         else "Greet me briefly, say which form we are filling, and ask the first question."})
        try:
            out = sarvam.chat_json(messages, schema)
        except Exception as e:  # never leave the user in silence
            out = {"updates": [], "done": False,
                   "reply": sarvam.translate("Sorry, could you please say that again?", s["lang"]),
                   "error": str(e)}

    changed, rejected = [], []
    for u in out.get("updates", []):
        key, raw = u.get("field"), str(u.get("value", "")).strip()
        if not raw or not _field(s, key):
            continue
        value = _clean(s, key, raw)
        reason = _invalid(s, key, value)
        if reason:
            rejected.append((key, raw, reason))
        elif s["values"].get(key) != value:
            s["values"][key] = value
            changed.append(key)

    complete = all(s["values"].get(f["key"]) for f in _askable(s))
    s["done"] = bool(out.get("done")) and complete and not rejected
    reply = out.get("reply", "").strip()

    if user_text != "(start)":
        s["history"].append({"role": "user", "content": user_text})
    if rejected and not config.MOCK:
        # The model accepted something the form can't take: ask again instead of saying "noted".
        note = "; ".join(f"{k}={v!r} was NOT saved ({why})" for k, v, why in rejected)
        retry = [{"role": "system", "content": _system_prompt(s)}] + s["history"][-12:] + [
            {"role": "user", "content": f"(System check: {note}. Politely tell me it seems wrong and ask "
                                        f"for it again. Do not repeat any other question.)"}]
        try:
            reply = sarvam.chat_json(retry, schema).get("reply", reply).strip()
        except Exception:
            pass
    s["history"].append({"role": "assistant", "content": reply})
    return {"reply": reply, "changed": changed, "llm_s": round(time.time() - t0, 2),
            "error": out.get("error")}


def apply_document_values(s: dict, found: dict) -> list:
    """Merge values read from an ID/marksheet into the form."""
    changed = []
    for k, v in found.items():
        value = _clean(s, k, v)
        if v and not _invalid(s, k, value):
            s["values"][k] = value
            changed.append(k)
    return changed


def document_note(s: dict, changed: list) -> str:
    """The message the agent sees after an upload, so it can acknowledge and move on."""
    if not changed:
        return "I uploaded a document but no form fields could be read from it."
    return "I uploaded a document. These fields were filled from it: " + ", ".join(
        f"{k}={s['values'][k]}" for k in changed)


def public_state(s: dict) -> dict:
    return {
        "id": s["id"], "lang": s["lang"], "done": s["done"], "values": s["values"],
        "scanned": s["form"]["id"] == "scanned",
        "form": {"title": s["form"]["title"],
                 "fields": [{**f, "local_label": s["labels"].get(f["key"], f["label"])}
                            for f in s["form"]["fields"]]},
    }
