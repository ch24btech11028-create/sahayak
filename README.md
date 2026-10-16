# Sahayak — show it any form, then just talk

Millions of people can't fill English government forms. Point Sahayak at any paper form: Sarvam
Vision reads every blank on the page, then Sahayak asks about each one out loud in the user's
language, understands answers spoken in mixed Hindi/Telugu/Tamil + English, and writes the form in
English. Tick-box fields are ticked, sensitive fields (Aadhaar, bank) are left for the user's own hand,
and an ID card or marksheet can pre-fill what it can.

**Sarvam stack:** Sarvam Vision / Doc AI Extract (reads the form's fields; pre-fills from IDs) ·
Saaras v4 (speech-to-text, `codemix`) · Sarvam-105B (the agent, forced tool call) · Bulbul v4 Flash
(voice) · Mayura (field labels and the scan instruction in the user's language) · Transliterate.

## Run it

```bash
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
cp .env.example .env          # paste SARVAM_API_KEY
.venv/bin/python scripts/smoke_test.py                      # every Sarvam call, PASS/FAIL
.venv/bin/python scripts/smoke_test.py doc samples/id.jpg   # also test Doc AI on a file
.venv/bin/uvicorn app.main:app --reload --port 8000         # open http://localhost:8000
```

Without a key the app runs in **mock mode** (canned speech/LLM/voice) so the UI can be worked on offline.

## How a turn works

```
camera / photo / PDF ─► POST /api/form/scan ─► Sarvam Vision: title, blanks, tick-box options
                                            └─► field kinds (name/date/phone/number/choice/sensitive)

mic (MediaRecorder webm) ─► POST /api/turn ─► Saaras v4 codemix ─► Sarvam-105B (JSON: updates, reply, done)
                                                               └─► transliterate names → form values
                         ◄── reply text + Bulbul WAV + updated form state + timings ◄──┘
```

The agent is one structured-output call per turn (reasoning off, for speed): it decides which
fields to set or correct, what to ask next (one field at a time), and when the user has confirmed
the read-back.

## Files

| Path | What |
|---|---|
| `app/config.py` | The sample form (6 fields), languages and voices |
| `app/forms.py` | Turns a Sarvam Vision scan into a fillable form: keys, kinds, validation hints |
| `app/sarvam.py` | One function per Sarvam call, each with a mock fallback |
| `app/agent.py` | Session state, system prompt, turn logic |
| `app/main.py` | FastAPI routes: `/api/form/scan`, `/api/session` (sample), `/api/turn`, `/api/document`, `/api/instruction` |
| `static/` | Single-page UI: language picker, camera scan, push-to-talk, live paper form, print to PDF |
| `samples/` | A blank income-certificate form and a marksheet to test scanning and pre-fill |
| `scripts/smoke_test.py` | Verifies the key and every API before the build hour |

## Build-hour ideas (pick 1–2)

- Tune the prompt on real voices: dates ("बारह मार्च दो हज़ार तीन"), mobile digits, "2 lakh".
- Show the extracted-vs-spoken source of each field (Doc AI returns confidences in `annotations`).
- Read back the final form in the user's language and offer a WhatsApp-shareable PDF.
- Second form type (ration card) by adding another `FORM` dict.
