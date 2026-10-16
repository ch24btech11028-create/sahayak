"""The conversation: one agent step per user turn decides which fields to fill and what to say."""

import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field

from . import config, forms, sarvam
from .forms import Form

HISTORY_TURNS = 12

_label_cache: dict[tuple[str, str], str] = {}


@dataclass
class Session:
    lang: str
    form: Form
    id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    values: dict[str, str] = field(default_factory=dict)
    history: list[dict] = field(default_factory=list)
    local_labels: dict[str, str] = field(default_factory=dict)
    done: bool = False

    @property
    def complete(self) -> bool:
        return all(self.values.get(f.key) for f in self.form.askable)

    def set(self, key: str, raw: str) -> tuple[bool, str | None]:
        """Normalise and validate an answer. Returns (changed, problem)."""
        f = self.form.get(key)
        if not f:
            return False, "unknown field"
        value = forms.normalize(f, raw, self.lang)
        issue = forms.problem(f, value)
        if issue or self.values.get(key) == value:
            return False, issue
        self.values[key] = value
        return True, None

    def to_dict(self) -> dict:
        return {
            "id": self.id, "lang": self.lang, "done": self.done, "values": self.values,
            "form": {"title": self.form.title,
                     "fields": [{**forms.to_dict(f), "local_label": self.local_labels.get(f.key, f.label)}
                                for f in self.form.fields]},
        }


SESSIONS: dict[str, Session] = {}


def start(lang: str, form: Form, prefilled: dict[str, str]) -> Session:
    s = Session(lang, form, local_labels=_translate_labels(form, lang))
    for key, value in prefilled.items():
        s.set(key, value)
    SESSIONS[s.id] = s
    return s


def _translate_labels(form: Form, lang: str) -> dict[str, str]:
    """Field labels in the user's language, translated in parallel and cached across sessions."""
    todo = [f.label for f in form.fields if (f.label, lang) not in _label_cache]
    if todo:
        with ThreadPoolExecutor(max_workers=6) as pool:
            for label, local in zip(todo, pool.map(lambda t: _safe_translate(t, lang), todo)):
                _label_cache[(label, lang)] = local
    return {f.key: _label_cache[(f.label, lang)] for f in form.fields}


def _safe_translate(text: str, lang: str) -> str:
    try:
        return sarvam.translate(text, lang)
    except Exception:
        return text


def _schema(s: Session) -> dict:
    return {
        "type": "object",
        "required": ["updates", "reply", "done"],
        "properties": {
            "updates": {
                "type": "array",
                "description": "Fields to set or correct from what the user just said. Empty if none.",
                "items": {"type": "object", "required": ["field", "value"], "properties": {
                    "field": {"type": "string", "enum": [f.key for f in s.form.askable]},
                    "value": {"type": "string"},
                }},
            },
            "reply": {"type": "string", "description": "What Sahayak says next, in the user's language."},
            "done": {"type": "boolean", "description": "True only after the user confirmed the full read-back."},
        },
    }


def _prompt(s: Session) -> str:
    lang = config.LANGUAGES[s.lang]
    rows = []
    for f in s.form.askable:
        options = f"; options: {' / '.join(f.options)}" if f.options else ""
        rows.append(f"- {f.key} ({f.label}; {f.hint}{options}): {s.values.get(f.key) or 'MISSING'}")
    by_hand = [f.label for f in s.form.fields if not f.askable]
    by_hand_line = f"\nThe user writes these by hand; never ask for them: {', '.join(by_hand)}." if by_hand else ""
    return f"""You are Sahayak, a warm, patient assistant helping someone fill the "{s.form.title}" by voice.
The user may not read English. Speak ONLY in {lang.english} ({lang.name}), using simple everyday words.
English words that people commonly mix in (form, mobile, college) are fine. Your reply is spoken aloud,
so keep it to 1-2 short sentences: no lists, no markdown, no emojis.
In replies, always write numbers and dates as digits (9840950950, 12/03/2003, 200000); never spell digits out.

Current form:
{chr(10).join(rows)}{by_hand_line}

How to work:
1. Put every value from the user's latest message into `updates`, including corrections to earlier values.
2. Write values in English: names in English letters ("Ravi Kumar"), dates as DD/MM/YYYY, mobile numbers as
   10 digits, amounts as rupee digits ("2 lakh" -> "200000"), other answers as short English ("किसान" -> "Farmer").
   For fields with options the value must be exactly one option. Convert spoken numbers to digits.
3. If a value is unclear or invalid (e.g. a 9-digit mobile), don't save it; ask again politely.
4. Ask for ONE missing field at a time, in order. For fields with options, say the options.
5. When nothing is MISSING, read all values back briefly and ask the user to confirm. Set done=true only after
   they confirm. If they correct something, update it and read back again.
6. Never ask for Aadhaar, bank account, passwords or OTPs.
7. You only fill the form; you cannot submit it. When done, say it is ready to print or save, and to sign it."""


def step(s: Session, user_text: str | None) -> dict:
    """Run one agent step. `user_text=None` asks the agent to open the conversation."""
    started = time.monotonic()
    said = user_text or "Greet me briefly, say which form we are filling, and ask the first question."
    messages = [{"role": "system", "content": _prompt(s)}, *s.history[-HISTORY_TURNS:],
                {"role": "user", "content": said}]
    error = None
    complete_before = s.complete
    try:
        out = sarvam.agent_step(messages, _schema(s))
    except Exception as e:  # never leave the user in silence
        out = {"updates": [], "done": False, "reply": _safe_translate("Sorry, please say that again.", s.lang)}
        error = f"Sahayak could not understand that turn: {e}"

    changed, rejected = [], []
    for update in out.get("updates", []):
        ok, issue = s.set(update.get("field", ""), str(update.get("value", "")))
        if ok:
            changed.append(update["field"])
        elif issue:
            rejected.append(f"{update.get('field')}={update.get('value')!r} was NOT saved ({issue})")

    if user_text:
        s.history.append({"role": "user", "content": user_text})
    reply = str(out.get("reply", "")).strip()
    if rejected:
        reply = _ask_again(s, rejected) or reply
    s.history.append({"role": "assistant", "content": reply})
    # Done only on a pure confirmation: the form was already complete (so the user heard the read-back)
    # and nothing changed this turn. The model alone sometimes sets done while still reading back.
    s.done = bool(out.get("done")) and complete_before and not changed and not rejected
    return {"reply": reply, "changed": changed, "error": error,
            "llm_s": round(time.monotonic() - started, 2)}


def _ask_again(s: Session, rejected: list[str]) -> str | None:
    """The model accepted a value the form can't take; have it ask again instead of saying "noted"."""
    note = (f"(System check: {'; '.join(rejected)}. Politely say it seems wrong and ask for it again. "
            f"Do not repeat any other question.)")
    messages = [{"role": "system", "content": _prompt(s)}, *s.history[-HISTORY_TURNS:],
                {"role": "user", "content": note}]
    try:
        return str(sarvam.agent_step(messages, _schema(s)).get("reply", "")).strip() or None
    except Exception:
        return None


def fill_from_document(s: Session, found: dict[str, str]) -> tuple[list[str], str]:
    """Apply values read from an ID card; returns (changed keys, a note for the agent)."""
    changed = [key for key, value in found.items() if value and s.set(key, value)[0]]
    if not changed:
        return [], "I uploaded a document but no form fields could be read from it."
    filled = ", ".join(f"{key}={s.values[key]}" for key in changed)
    return changed, f"I uploaded a document. These fields were filled from it: {filled}"


def edit(s: Session, key: str, value: str) -> bool:
    """A manual correction typed on the form itself."""
    if not s.form.get(key):
        return False
    s.values[key] = value.strip()
    s.history.append({"role": "user", "content": f"(I corrected {key} to {value.strip()!r} myself.)"})
    return True
