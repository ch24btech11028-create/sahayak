"""Sahayak backend. Run with:  uvicorn app.main:app --reload --port 8000"""

import time
from pathlib import Path

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from . import agent, config, forms, sarvam

STATIC = Path(__file__).resolve().parent.parent / "static"
app = FastAPI(title="Sahayak")


def _get(sid: str) -> dict:
    s = agent.SESSIONS.get(sid)
    if not s:
        raise HTTPException(404, "Session not found. Start a new one.")
    return s


def _respond(s: dict, turn: dict, timings: dict, heard: str | None = None) -> dict:
    t = time.time()
    try:
        audio = sarvam.speak(turn["reply"], s["lang"])
    except Exception as e:
        audio, turn["error"] = None, f"TTS failed: {e}"
    timings["tts_s"] = round(time.time() - t, 2)
    timings["llm_s"] = turn.get("llm_s")
    return {"heard": heard, "reply": turn["reply"], "audio_b64": audio, "changed": turn["changed"],
            "error": turn.get("error"), "timings": timings, "state": agent.public_state(s)}


@app.get("/api/config")
def get_config():
    return {"mock": config.MOCK, "form_title": config.FORM["title"],
            "languages": [{"code": c, "name": l["name"], "english": l["english"],
                           "speak": config.SPEAK_WORD.get(c, l["name"])}
                          for c, l in config.LANGUAGES.items()]}


_instruction_cache: dict[str, dict] = {}
INSTRUCTION = "Hold your form in front of the camera so the whole page is visible, then press the button."


@app.get("/api/instruction")
def instruction(lang: str = "hi-IN"):
    """The scan instruction, translated and spoken, for people who can't read the English UI."""
    if lang not in config.LANGUAGES:
        raise HTTPException(400, f"Unsupported language {lang}")
    if lang not in _instruction_cache:
        try:
            text = sarvam.translate(INSTRUCTION, lang)
            _instruction_cache[lang] = {"text": text, "audio_b64": sarvam.speak(text, lang)}
        except Exception as e:
            return {"text": INSTRUCTION, "audio_b64": None, "error": str(e)}
    return _instruction_cache[lang]


class StartBody(BaseModel):
    lang: str = "hi-IN"


@app.post("/api/session")
def start_session(body: StartBody):
    if body.lang not in config.LANGUAGES:
        raise HTTPException(400, f"Unsupported language {body.lang}")
    s = agent.create_session(body.lang, forms.sample_form())
    return _respond(s, agent.run_turn(s, "(start)"), {})


ALLOWED_DOCS = {"application/pdf", "image/png", "image/jpeg"}


def _read_upload(file: UploadFile) -> tuple[bytes, str, str]:
    data = file.file.read()
    ctype = (file.content_type or "").split(";")[0]
    if ctype not in ALLOWED_DOCS:
        raise HTTPException(400, "Use a photo (JPG or PNG) or a PDF of up to 10 pages.")
    if not data:
        raise HTTPException(400, "The file is empty.")
    return data, file.filename or "document", ctype


@app.post("/api/form/scan")
def scan_form(lang: str = Form("hi-IN"), file: UploadFile = File(...)):
    """Photograph any paper form: Sarvam Vision lists its fields, then the agent asks for them."""
    if lang not in config.LANGUAGES:
        raise HTTPException(400, f"Unsupported language {lang}")
    data, name, ctype = _read_upload(file)
    t = time.time()
    try:
        result = sarvam.scan_form(data, name, ctype)
    except Exception as e:
        raise HTTPException(502, f"Sarvam Vision could not read the form: {e}")
    form, prefilled = forms.from_scan(result)
    if not form["fields"]:
        raise HTTPException(422, "No fillable fields were found. Retake the photo with the whole form "
                                 "in view and good light.")
    timings = {"scan_s": round(time.time() - t, 2)}
    s = agent.create_session(lang, form, prefilled)
    return _respond(s, agent.run_turn(s, "(start)"), timings)


@app.post("/api/turn")
def voice_turn(session_id: str = Form(...), audio: UploadFile | None = File(None),
               text: str | None = Form(None)):
    """One conversational turn. Send recorded audio (push-to-talk) or typed text."""
    s = _get(session_id)
    timings = {}
    if audio is not None:
        t = time.time()
        data = audio.file.read()
        if not data:
            raise HTTPException(400, "Empty recording")
        try:
            heard = sarvam.transcribe(data, audio.filename or "speech.webm", s["lang"])
        except Exception as e:
            raise HTTPException(502, f"Speech-to-text failed: {e}")
        timings["stt_s"] = round(time.time() - t, 2)
    elif text and text.strip():
        heard = text.strip()
    else:
        raise HTTPException(400, "Send audio or text")
    if not heard:
        heard = "(silence)"
    return _respond(s, agent.run_turn(s, heard), timings, heard)


@app.post("/api/document")
def upload_document(session_id: str = Form(...), file: UploadFile = File(...)):
    """Pre-fill the form from an ID card / marksheet photo or PDF using Doc AI Extract."""
    s = _get(session_id)
    data, name, ctype = _read_upload(file)
    t = time.time()
    try:
        found = sarvam.extract_fields(data, name, ctype, s["form"]["fields"])
    except Exception as e:
        raise HTTPException(502, f"Document reading failed: {e}")
    timings = {"doc_s": round(time.time() - t, 2)}
    changed = agent.apply_document_values(s, found)
    turn = agent.run_turn(s, agent.document_note(s, changed))
    turn["changed"] = sorted(set(turn["changed"]) | set(changed))
    return _respond(s, turn, timings)


@app.get("/api/session/{sid}")
def get_session(sid: str):
    return agent.public_state(_get(sid))


class FieldEdit(BaseModel):
    field: str
    value: str


@app.post("/api/session/{sid}/field")
def edit_field(sid: str, body: FieldEdit):
    """Manual correction from the UI (tap a field and edit it)."""
    s = _get(sid)
    if not any(f["key"] == body.field for f in s["form"]["fields"]):
        raise HTTPException(400, "Unknown field")
    s["values"][body.field] = body.value.strip()
    s["history"].append({"role": "user", "content": f"(I edited {body.field} to {body.value.strip()} myself.)"})
    return agent.public_state(s)


@app.get("/")
def index():
    return FileResponse(STATIC / "index.html")


app.mount("/static", StaticFiles(directory=STATIC), name="static")
