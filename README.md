# Sahayak — show it any form, then just talk

Government forms in India are printed in English, but most of the people who need them don't read
English comfortably. Sahayak lets anyone fill a paper form by talking, in their own language.

1. **Scan.** Hold any paper form up to the camera. Sarvam Vision reads every blank on the page.
2. **Talk.** Sahayak asks about each blank, one at a time, out loud in 11 Indian languages, and
   understands answers mixed with English ("मेरा mobile number है…").
3. **Done.** Answers are written on the form in English, checked (dates, mobile numbers, amounts,
   tick boxes), read back for confirmation, and ready to print or save as a PDF.

An ID card or marksheet can pre-fill what it can. Sensitive fields (Aadhaar, bank details) are never
asked out loud; the form leaves them for the applicant to write by hand.

## Built on Sarvam AI

| Step | Sarvam model |
|---|---|
| Read the form's blanks, pre-fill from an ID | Sarvam Vision (Document AI Extract) |
| Understand spoken answers | Saaras v4, `codemix` mode |
| Decide what to fill and ask next | Sarvam-105B (forced tool call, reasoning off) |
| Speak questions and the read-back | Bulbul v4 Flash (v3 for Malayalam and Odia) |
| Field labels and instructions in the user's language | Mayura |
| Names in English letters | Transliterate |

## Run it

```bash
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
cp .env.example .env                                   # add SARVAM_API_KEY
.venv/bin/python scripts/smoke_test.py                 # checks every Sarvam call against the live API
.venv/bin/uvicorn app.main:app --port 8000             # open http://localhost:8000
```

The camera and microphone need `localhost` or HTTPS.

## How it works

```
photo ─► POST /api/form/scan ─► Sarvam Vision ─► Form (title, fields, kinds) ─► agent opens the conversation
speech ─► POST /api/turn ─► Saaras ─► Sarvam-105B ─► normalise + validate each value ─► Bulbul reply
```

Each turn is one Sarvam-105B call that returns `{updates, reply, done}`. The server, not the model,
decides what goes on the form: every value is normalised for its field kind and validated, and a
rejected value makes the agent ask again. The form only counts as done when the user confirms a
read-back with nothing left to change.

| Path | Responsibility |
|---|---|
| `app/config.py` | Settings and the 11 languages (voice, script, UI words) |
| `app/sarvam.py` | One function per Sarvam API call; the only module that uses the SDK |
| `app/forms.py` | Form and field model, reading a scan, normalising and validating answers |
| `app/agent.py` | Sessions and the conversation: prompt, agent step, re-ask on bad values |
| `app/main.py` | HTTP routes |
| `static/` | Single-page UI: language picker, camera scan, push-to-talk, the live form |
| `scripts/smoke_test.py` | Live check of every Sarvam call |
| `docs/PITCH.md` | The pitch and a full explanation |
| `docs/INDUS_BUILD.md` | Step-by-step instructions for Indus (Sarvam's coding agent) to rebuild Sahayak |
