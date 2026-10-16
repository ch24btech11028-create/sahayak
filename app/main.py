"""Sahayak HTTP API. Run with:  uvicorn app.main:app --port 8000"""

import threading
import time
from concurrent.futures import ThreadPoolExecutor
from contextlib import asynccontextmanager
from functools import cache
from pathlib import Path

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from . import agent, config, forms, sarvam

STATIC = Path(__file__).resolve().parent.parent / "static"
DOCUMENT_TYPES = {"application/pdf", "image/png", "image/jpeg"}
SCAN_INSTRUCTION = "Hold your form in front of the camera so the whole page is visible, then press the button."

def _warm_instructions():
    """Pre-generate the spoken scan instruction for every language, so it plays instantly."""
    for code in config.LANGUAGES:
        try:
            _instruction(code)
        except Exception:
            pass  # generated on demand instead


@asynccontextmanager
async def lifespan(_: FastAPI):
    threading.Thread(target=_warm_instructions, daemon=True).start()
    yield


app = FastAPI(title="Sahayak", lifespan=lifespan)


class Timer:
    """Collects how long each Sarvam stage took, shown in the UI."""

    def __init__(self):
        self.timings: dict[str, float] = {}

    def __call__(self, name: str, fn, *args):
        started = time.monotonic()
        try:
            return fn(*args)
        finally:
            self.timings[name] = round(time.monotonic() - started, 2)


def _session(sid: str) -> agent.Session:
    if sid not in agent.SESSIONS:
        raise HTTPException(404, "This session has ended. Start over.")
    return agent.SESSIONS[sid]


def _language(code: str) -> str:
    if code not in config.LANGUAGES:
        raise HTTPException(400, f"Unsupported language: {code}")
    return code


def _document(file: UploadFile) -> tuple[bytes, str, str]:
    content_type = (file.content_type or "").split(";")[0]
    if content_type not in DOCUMENT_TYPES:
        raise HTTPException(400, "Use a photo (JPG or PNG) or a PDF of up to 10 pages.")
    data = file.file.read()
    if not data:
        raise HTTPException(400, "The file is empty.")
    return data, file.filename or "document", content_type


def _reply(s: agent.Session, turn: dict, timer: Timer, heard: str | None = None) -> dict:
    """Speak the agent's reply and return everything the UI needs for this turn."""
    audio, error = None, turn["error"]
    try:
        audio = timer("tts_s", sarvam.speak, turn["reply"], s.lang)
    except Exception as e:
        error = f"Could not play the reply aloud: {e}"
    return {"heard": heard, "reply": turn["reply"], "audio_b64": audio, "changed": turn["changed"],
            "error": error, "timings": {**timer.timings, "llm_s": turn["llm_s"]}, "state": s.to_dict()}


@app.get("/api/config")
def get_config():
    return {"languages": [{"code": l.code, "name": l.name, "english": l.english, "speak": l.speak,
                           "complete": l.complete} for l in config.LANGUAGES.values()]}


@cache
def _instruction(lang: str) -> dict:
    text = sarvam.translate(SCAN_INSTRUCTION, lang)
    return {"text": text, "audio_b64": sarvam.speak(text, lang)}


@app.get("/api/instruction")
def instruction(lang: str):
    """The scan instruction in the user's language, spoken, for people who can't read the English UI."""
    lang = _language(lang)
    try:
        return _instruction(lang)
    except Exception:
        return {"text": SCAN_INSTRUCTION, "audio_b64": None}


@app.post("/api/form/scan")
def scan_form(lang: str = Form(...), file: UploadFile = File(...)):
    """A photo of any paper form → Sarvam Vision lists its blanks → the agent opens the conversation."""
    lang = _language(lang)
    data, name, content_type = _document(file)
    timer = Timer()
    try:
        result = timer("scan_s", sarvam.vision_extract, data, name, content_type, forms.SCAN_SCHEMA)
    except Exception as e:
        raise HTTPException(502, f"Sarvam Vision could not read the form: {e}")
    form, prefilled = forms.from_scan(result)
    if not form.fields:
        raise HTTPException(422, "No blanks were found. Retake the photo with the whole page in view and good light.")
    s = agent.start(lang, form, prefilled)
    with ThreadPoolExecutor(max_workers=1) as pool:  # translate labels while the agent greets
        labels = pool.submit(agent.translate_labels, form, lang)
        greeting = agent.step(s, None)
        s.local_labels = labels.result()
    return _reply(s, greeting, timer)


@app.post("/api/turn")
def turn(session_id: str = Form(...), audio: UploadFile | None = File(None), text: str | None = Form(None)):
    """One answer from the user: recorded speech (push-to-talk) or typed text."""
    s = _session(session_id)
    timer = Timer()
    if audio is not None:
        data = audio.file.read()
        if not data:
            raise HTTPException(400, "The recording is empty.")
        try:
            heard = timer("stt_s", sarvam.transcribe, data, audio.filename or "speech.webm", s.lang)
        except Exception as e:
            raise HTTPException(502, f"Could not understand the recording: {e}")
    else:
        heard = (text or "").strip()
    if not heard:
        raise HTTPException(400, "Nothing was heard. Tap the mic and speak, or type your answer.")
    return _reply(s, agent.step(s, heard), timer, heard)


@app.post("/api/document")
def fill_from_document(session_id: str = Form(...), file: UploadFile = File(...)):
    """Pre-fill the open form from a photo of an ID card, marksheet or certificate."""
    s = _session(session_id)
    data, name, content_type = _document(file)
    timer = Timer()
    try:
        found = timer("doc_s", sarvam.vision_extract, data, name, content_type, forms.id_document_schema(s.form))
    except Exception as e:
        raise HTTPException(502, f"Sarvam Vision could not read the document: {e}")
    changed, note = agent.fill_from_document(s, {k: str(v) for k, v in found.items() if v})
    result = agent.step(s, note)
    result["changed"] = sorted(set(result["changed"]) | set(changed))
    return _reply(s, result, timer)


class FieldEdit(BaseModel):
    field: str
    value: str


@app.post("/api/session/{sid}/field")
def edit_field(sid: str, body: FieldEdit):
    """A correction typed directly on the form."""
    s = _session(sid)
    if not agent.edit(s, body.field, body.value):
        raise HTTPException(400, f"Unknown field: {body.field}")
    return s.to_dict()


@app.delete("/api/session/{sid}/field/{key}")
def remove_field(sid: str, key: str):
    """Remove a blank that was detected by mistake."""
    s = _session(sid)
    if not agent.remove_field(s, key):
        raise HTTPException(400, f"Unknown field: {key}")
    return s.to_dict()


@app.get("/")
def index():
    return FileResponse(STATIC / "index.html")


app.mount("/static", StaticFiles(directory=STATIC), name="static")
