"""Sahayak backend. Run with:  uvicorn app.main:app --reload --port 8000"""

import time
from pathlib import Path

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from . import agent, config, sarvam

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
            "languages": [{"code": c, "name": l["name"], "english": l["english"]}
                          for c, l in config.LANGUAGES.items()]}


class StartBody(BaseModel):
    lang: str = "hi-IN"


@app.post("/api/session")
def start_session(body: StartBody):
    if body.lang not in config.LANGUAGES:
        raise HTTPException(400, f"Unsupported language {body.lang}")
    s = agent.create_session(body.lang)
    return _respond(s, agent.run_turn(s, "(start)"), {})


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
    t = time.time()
    try:
        found = sarvam.extract_fields(file.file.read(), file.filename or "document.pdf",
                                      file.content_type or "application/pdf", config.FORM["fields"])
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
    if body.field not in config.FIELD_KEYS:
        raise HTTPException(400, "Unknown field")
    s["values"][body.field] = body.value.strip()
    s["history"].append({"role": "user", "content": f"(I edited {body.field} to {body.value.strip()} myself.)"})
    return agent.public_state(s)


@app.get("/")
def index():
    return FileResponse(STATIC / "index.html")


app.mount("/static", StaticFiles(directory=STATIC), name="static")
