"""One function per Sarvam API call. Nothing else in the app imports the SDK."""

import base64
import json
import time
from functools import cache

from sarvamai import SarvamAI

from . import config

VISION_TIMEOUT_S = 90
VISION_POLL_S = 1.5
TTS_MAX_CHARS = 2500


@cache
def _client() -> SarvamAI:
    return SarvamAI(api_subscription_key=config.SARVAM_API_KEY, timeout=60.0)


def transcribe(audio: bytes, filename: str, lang: str) -> str:
    """Saaras v4 in codemix mode: Indic words stay in native script, English words stay English."""
    r = _client().speech_to_text.transcribe(
        file=(filename, audio), model=config.STT_MODEL, mode="codemix", language_code=lang)
    return (r.transcript or "").strip()


def speak(text: str, lang: str) -> str:
    """Bulbul text-to-speech. Returns one base64 WAV for the browser to play."""
    voice = config.LANGUAGES[lang]
    r = _client().text_to_speech.convert(
        text=text[:TTS_MAX_CHARS], language_code=lang, model=voice.tts_model, speaker=voice.speaker)
    # The REST response is a list of base64 chunks; decode and re-encode them as one file.
    return base64.b64encode(base64.b64decode("".join(r.audios))).decode()


def translate(text: str, lang: str) -> str:
    """English → the user's language (Mayura)."""
    if lang == "en-IN":
        return text
    r = _client().text.translate(
        input=text, source_language_code="en-IN", target_language_code=lang, model=config.TRANSLATE_MODEL)
    return r.translated_text


def romanise(text: str, lang: str) -> str:
    """Write a value in English letters for the form, e.g. "रवि कुमार" → "Ravi Kumar"."""
    if text.isascii():
        return text
    r = _client().text.transliterate(input=text, source_language_code=lang, target_language_code="en-IN")
    return r.transliterated_text


def agent_step(messages: list, schema: dict) -> dict:
    """Sarvam-105B returns one structured agent step as a forced tool call.

    Reasoning is off for speed. A forced tool call is used instead of `response_format=json_schema`,
    which loops on whitespace on sarvam-105b.
    """
    tool = {"type": "function", "function": {
        "name": "respond", "description": "Update form fields and say the next thing to the user.",
        "parameters": schema}}
    r = _client().chat.completions(
        model=config.LLM_MODEL, messages=messages, tools=[tool],
        tool_choice={"type": "function", "function": {"name": "respond"}},
        reasoning_effort=None, temperature=0.2, max_tokens=600)
    call = r.choices[0].message.tool_calls[0]
    return json.loads(call.function.arguments)


def vision_extract(document: bytes, filename: str, content_type: str, schema: dict) -> dict:
    """Run a Sarvam Vision (Document AI Extract) job and wait for its structured result."""
    c = _client()
    job = c.doc_ai.extract(
        file=[(filename, document, content_type)],  # the SDK wants a list, even for one file
        schema=json.dumps(schema),                   # sent as a form field, so a JSON string
        output_format="json")
    deadline = time.monotonic() + VISION_TIMEOUT_S
    while True:
        status = c.doc_ai.get_status(job_id=job.job_id).status.lower()
        if status in ("completed", "partially_completed"):
            return c.doc_ai.get_results(job_id=job.job_id).result or {}
        if status in ("failed", "rejected"):
            raise RuntimeError(f"Sarvam Vision could not read this document ({status}).")
        if time.monotonic() > deadline:
            raise TimeoutError("Reading the document took too long.")
        time.sleep(VISION_POLL_S)
