"""Thin wrappers over the Sarvam SDK, each with a mock fallback.

Every function here does one Sarvam call. In mock mode (no API key, or SAHAYAK_MOCK=1)
they return canned data so the UI and agent logic can be developed offline.
"""

import base64
import io
import json
import re
import time
import wave

from . import config

_client = None


def client():
    global _client
    if _client is None:
        from sarvamai import SarvamAI

        _client = SarvamAI(api_subscription_key=config.SARVAM_API_KEY, timeout=60.0)
    return _client


# ---------------------------------------------------------------- speech-to-text

_MOCK_UTTERANCES = [
    "मेरा नाम Ravi Kumar है",
    "पिताजी का नाम Suresh Kumar",
    "बारह March दो हज़ार तीन",
    "nine eight four zero nine five zero nine five zero",
    "IIT Hyderabad",
    "लगभग दो लाख रुपये साल का",
    "हाँ, सब सही है",
]
_mock_turn = 0


def transcribe(audio: bytes, filename: str, language_code: str) -> str:
    """Saaras v4 in codemix mode: Indic words in native script, English words stay English."""
    global _mock_turn
    if config.MOCK:
        text = _MOCK_UTTERANCES[_mock_turn % len(_MOCK_UTTERANCES)]
        _mock_turn += 1
        return text
    r = client().speech_to_text.transcribe(
        file=(filename, audio),
        model=config.STT_MODEL,
        mode="codemix",
        language_code=language_code,
    )
    return (r.transcript or "").strip()


# ---------------------------------------------------------------- text-to-speech

def _silent_wav(seconds: float = 0.4) -> bytes:
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(16000)
        w.writeframes(b"\x00\x00" * int(16000 * seconds))
    return buf.getvalue()


def speak(text: str, language_code: str) -> str:
    """Bulbul TTS. Returns base64 WAV so the browser can play it from a data URL."""
    if config.MOCK or not text:
        return base64.b64encode(_silent_wav()).decode()
    lang = config.LANGUAGES[language_code]
    r = client().text_to_speech.convert(
        text=text[:2500],
        language_code=language_code,
        model=lang["tts_model"],
        speaker=lang["speaker"],
    )
    # REST returns a list of base64 chunks; join, decode, re-encode as one WAV.
    return base64.b64encode(base64.b64decode("".join(r.audios))).decode()


# ---------------------------------------------------------------- text tools

def translate(text: str, target: str) -> str:
    if config.MOCK or target == "en-IN":
        return text
    r = client().text.translate(
        input=text, source_language_code="en-IN", target_language_code=target, model="mayura:v1"
    )
    return r.translated_text


def to_latin(text: str, source: str) -> str:
    """Romanise a value (e.g. a name said in Devanagari) for the English form."""
    if config.MOCK or not text or text.isascii():
        return text
    try:
        r = client().text.transliterate(input=text, source_language_code=source, target_language_code="en-IN")
        return r.transliterated_text
    except Exception:
        return text


# ---------------------------------------------------------------- chat (the agent's brain)

def _strip_fences(s: str) -> str:
    s = s.strip()
    m = re.match(r"^```(?:json)?\s*(.*?)\s*```$", s, re.S)
    return m.group(1) if m else s


def chat_json(messages: list, schema: dict) -> dict:
    """Sarvam-105B returns one structured agent step. Reasoning off: faster, cheaper, no empty replies.

    Primary path is a forced tool call. Strict `json_schema` response_format was tried first and
    degenerates into endless whitespace on sarvam-105b, so it is not used. JSON mode is the fallback.
    """
    c = client()
    tool = {"type": "function", "function": {
        "name": "respond", "description": "Update form fields and say the next thing to the user.",
        "parameters": schema}}
    try:
        r = c.chat.completions(
            model=config.LLM_MODEL, messages=messages, reasoning_effort=None, temperature=0.2,
            max_tokens=600, tools=[tool], tool_choice={"type": "function", "function": {"name": "respond"}},
        )
        calls = r.choices[0].message.tool_calls
        if calls:
            return json.loads(calls[0].function.arguments)
    except (json.JSONDecodeError, IndexError):
        pass

    shape = ('Respond with ONLY a JSON object: {"updates": [{"field": "<field key>", "value": "<string>"}], '
             '"reply": "<what you say>", "done": <true|false>}')
    msgs = [{**messages[0], "content": messages[0]["content"] + "\n\n" + shape}] + messages[1:]
    r = c.chat.completions(
        model=config.LLM_MODEL, messages=msgs, reasoning_effort=None, temperature=0.2,
        max_tokens=600, response_format={"type": "json_object"},
    )
    return json.loads(_strip_fences(r.choices[0].message.content or "{}"))


# ---------------------------------------------------------------- document AI

def extract_fields(document: bytes, filename: str, content_type: str, fields: list) -> dict:
    """Doc AI Extract: pull any form fields that appear in an uploaded ID/marksheet."""
    if config.MOCK:
        time.sleep(1.0)
        return {"student_name": "Ravi Kumar", "date_of_birth": "12/03/2003"}
    schema = {
        "type": "object",
        "properties": {
            f["key"]: {"type": "string", "description": f"{f['label']}. {f['hint']}"} for f in fields
        },
    }
    c = client()
    job = c.doc_ai.extract(
        file=[(filename, document, content_type)],  # a list, even for one file
        schema=json.dumps(schema),                   # a JSON string, not a dict
        output_format="json",
    )
    deadline = time.time() + 90
    while True:
        st = c.doc_ai.get_status(job_id=job.job_id)
        status = st.status.lower()
        if status in ("completed", "partially_completed"):
            break
        if status in ("failed", "rejected"):
            raise RuntimeError(f"Document extraction {status}")
        if time.time() > deadline:
            raise TimeoutError("Document extraction took too long")
        time.sleep(3)
    result = c.doc_ai.get_results(job_id=job.job_id).result or {}
    return {k: str(v).strip() for k, v in result.items() if v not in (None, "", [], {})}
