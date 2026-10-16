"""The form-filling agent: holds session state and decides, each turn, which fields to
update and what to say next."""

import re
import time
import uuid
from concurrent.futures import ThreadPoolExecutor

from . import config, sarvam

SESSIONS: dict[str, dict] = {}
_label_cache: dict[str, dict] = {}

TURN_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["updates", "reply", "done"],
    "properties": {
        "updates": {
            "type": "array",
            "description": "Fields to set or correct from what the user just said. Empty if none.",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["field", "value"],
                "properties": {
                    "field": {"type": "string", "enum": config.FIELD_KEYS},
                    "value": {"type": "string"},
                },
            },
        },
        "reply": {"type": "string", "description": "What Sahayak says next, in the user's language."},
        "done": {"type": "boolean", "description": "True only after the user confirmed the full read-back."},
    },
}


def _labels(lang: str) -> dict:
    """Field labels in the user's language (translated once per language, then cached)."""
    if lang not in _label_cache:
        fields = config.FORM["fields"]
        try:
            with ThreadPoolExecutor(max_workers=6) as pool:
                out = list(pool.map(lambda f: sarvam.translate(f["label"], lang), fields))
        except Exception:
            out = [f["label"] for f in fields]
        _label_cache[lang] = {f["key"]: t for f, t in zip(fields, out)}
    return _label_cache[lang]


def _system_prompt(s: dict) -> str:
    lang = config.LANGUAGES[s["lang"]]
    lines = []
    for f in config.FORM["fields"]:
        v = s["values"].get(f["key"])
        lines.append(f'- {f["key"]} ({f["label"]}; {f["hint"]}): {v if v else "MISSING"}')
    return f"""You are Sahayak, a warm, patient assistant helping someone fill the "{config.FORM['title']}" by voice.
The user may not read English. Speak ONLY in {lang['english']} ({lang['name']}), using simple everyday words.
English words that people commonly mix in (form, mobile, college) are fine. Your reply is spoken aloud by TTS,
so keep it to 1-2 short sentences, no lists, no markdown, no emojis.
In replies, always write numbers and dates as digits (9840950950, 12/03/2003, 200000); never spell digits out as words.

Current form state:
{chr(10).join(lines)}

How to work:
1. Extract any field values from the user's latest message into `updates`, including corrections to earlier values.
2. Store values in English/Latin script on the form: names romanised (e.g. "Ravi Kumar"), dates as DD/MM/YYYY,
   mobile as exactly 10 digits, income as digits only in rupees (e.g. "2 lakh" -> "200000").
   Convert spoken numbers in any language to digits.
3. If a value is unclear or invalid (e.g. 9 digits for mobile), do not save it; ask again politely.
4. Ask for ONE missing field at a time, in the order listed.
5. When nothing is MISSING, read back all values briefly and ask the user to confirm.
   Set done=true only when the user has confirmed that read-back. If they correct something, update it and read back again.
6. Never ask for Aadhaar, bank account, passwords or OTPs."""


def create_session(lang: str) -> dict:
    sid = uuid.uuid4().hex[:12]
    SESSIONS[sid] = {"id": sid, "lang": lang, "values": {}, "history": [], "done": False,
                     "labels": _labels(lang)}
    return SESSIONS[sid]


def _mock_turn(s: dict, user_text: str) -> dict:
    missing = [k for k in config.FIELD_KEYS if not s["values"].get(k)]
    samples = {"student_name": "Ravi Kumar", "father_name": "Suresh Kumar", "date_of_birth": "12/03/2003",
               "mobile_number": "9840950950", "institution_name": "IIT Hyderabad",
               "annual_family_income": "200000"}
    if user_text == "(start)":
        return {"updates": [], "done": False,
                "reply": "नमस्ते! मैं सहायक हूँ। चलिए आपका scholarship form भरते हैं। आपका पूरा नाम क्या है?"}
    if user_text.startswith("I uploaded a document"):
        return {"updates": [], "done": False,
                "reply": "Document से कुछ जानकारी भर दी है। बाकी के लिए कुछ सवाल पूछती हूँ।"}
    if not missing:
        return {"updates": [], "done": True, "reply": "धन्यवाद! आपका form तैयार है।"}
    key = missing[0]
    nxt = missing[1] if len(missing) > 1 else None
    reply = (f"ठीक है। अब {config.FORM['fields'][config.FIELD_KEYS.index(nxt)]['label']} बताइए।" if nxt
             else "सब जानकारी मिल गई। क्या सब सही है?")
    return {"updates": [{"field": key, "value": samples[key]}], "done": False, "reply": reply}


def _clean(key: str, value: str, lang: str) -> str:
    value = value.strip()
    if key in ("mobile_number", "annual_family_income"):
        value = re.sub(r"\D", "", value)
    elif config.FORM["fields"][config.FIELD_KEYS.index(key)]["latin"]:
        value = sarvam.to_latin(value, lang)
    return value


def _invalid(key: str, value: str) -> str | None:
    """Return a reason if a cleaned value can't go on the form."""
    if not value:
        return "empty"
    if key == "mobile_number" and not re.fullmatch(r"[6-9]\d{9}", value):
        return "must be a 10-digit Indian mobile number"
    if key == "date_of_birth" and not re.fullmatch(r"\d{2}/\d{2}/\d{4}", value):
        return "must be a date as DD/MM/YYYY"
    if key == "annual_family_income" and not value.isdigit():
        return "must be digits in rupees"
    if key in ("student_name", "father_name") and (re.search(r"\d", value) or len(value) < 2):
        return "must be a person's name, not numbers"
    return None


def run_turn(s: dict, user_text: str) -> dict:
    """One agent step: read the user's words, update the form, decide what to say."""
    t0 = time.time()
    if config.MOCK:
        out = _mock_turn(s, user_text)
    else:
        messages = [{"role": "system", "content": _system_prompt(s)}]
        messages += s["history"][-12:]
        messages.append({"role": "user", "content": user_text if user_text != "(start)"
                         else "Greet me briefly and start the form."})
        try:
            out = sarvam.chat_json(messages, TURN_SCHEMA)
        except Exception as e:  # never leave the user in silence
            out = {"updates": [], "done": False,
                   "reply": sarvam.translate("Sorry, could you please say that again?", s["lang"]),
                   "error": str(e)}

    changed, rejected = [], []
    for u in out.get("updates", []):
        key, raw = u.get("field"), str(u.get("value", "")).strip()
        if key not in config.FIELD_KEYS or not raw:
            continue
        value = _clean(key, raw, s["lang"])
        reason = _invalid(key, value)
        if reason:
            rejected.append((key, raw, reason))
        elif s["values"].get(key) != value:
            s["values"][key] = value
            changed.append(key)

    complete = all(s["values"].get(k) for k in config.FIELD_KEYS)
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
            reply = sarvam.chat_json(retry, TURN_SCHEMA).get("reply", reply).strip()
        except Exception:
            pass
    s["history"].append({"role": "assistant", "content": reply})
    return {"reply": reply, "changed": changed, "llm_s": round(time.time() - t0, 2),
            "error": out.get("error")}


def apply_document_values(s: dict, found: dict) -> list:
    """Merge Doc AI results into the form, then tell the agent what was pre-filled."""
    changed = []
    for k, v in found.items():
        if k in config.FIELD_KEYS and v:
            s["values"][k] = _clean(k, v, s["lang"])
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
        "form": {"title": config.FORM["title"],
                 "fields": [{**f, "local_label": s["labels"].get(f["key"], f["label"])}
                            for f in config.FORM["fields"]]},
    }
