# Build Sahayak with Indus

Instructions for an AI coding agent (Indus / Sarvam Code) to rebuild Sahayak from scratch.
Every API detail below was verified against the live Sarvam API with `sarvamai` 0.1.37.

## How to use this file

1. Paste **Part 1 (the master prompt)** into Indus first. It sets the product, stack and rules.
2. Then paste **one phase at a time** from Part 2. Don't move on until that phase's
   **Check** passes.
3. Finish with the **acceptance test** in Part 3.
4. If the agent goes wrong, point it back to **Part 1, "Facts about the Sarvam SDK"**. Those facts
   are where coding agents usually make mistakes.

Total: 6 phases. Phases 1–4 are the backend, phase 5 is the UI, phase 6 is the test script.

**Bring two files from this repo** (the agent can't draw them): `static/sample-income-form.png`
(a blank income-certificate form, used by "Scan a sample photo" and the smoke test) and
`samples/sample_marksheet.png` (a marksheet, for testing the ID pre-fill).

---

# Part 1 — Master prompt (paste this first)

~~~text
You are building "Sahayak", a web app that lets someone fill a printed paper government form by talking
in their own Indian language.

USER FLOW
1. The user picks one of 11 languages. Each is shown by its own word for "speak".
2. The app speaks an instruction in that language, then the user photographs a paper form
   (camera, photo upload, or PDF).
3. Sarvam Vision reads the form: its title, every blank in order, and tick-box options.
4. An agent (Sarvam-105B) asks for each blank, one at a time, out loud in the user's language.
   The user answers by push-to-talk, in speech mixed with English.
5. Answers are written on the form in English, validated in code, read back, and the form is
   marked complete only after the user confirms. It can then be printed or saved as a PDF.
6. Optional: a photo of an ID card or marksheet pre-fills matching fields.
7. Sensitive fields (Aadhaar, bank account, PAN, OTP) are never asked; the UI says "write this yourself".

STACK
- Python 3.11+, FastAPI, uvicorn, python-multipart, python-dotenv, sarvamai==0.1.37.
- Frontend: one static page (index.html, style.css, app.js), no framework, served by FastAPI.
- Key in .env as SARVAM_API_KEY. Fail fast at startup if it is missing.
- Sessions in memory (a dict). No database.

MODULES (keep these boundaries)
- app/config.py  : settings and the 11 languages (code, native name, English name, "speak" word,
                   "complete" word, TTS model, speaker).
- app/sarvam.py  : one function per Sarvam API call. The ONLY module that imports the SDK.
- app/forms.py   : Field/Form dataclasses, the scan schema, building a Form from a scan,
                   normalising and validating answers.
- app/agent.py   : Session dataclass, the system prompt, one agent step per user turn.
- app/main.py    : thin HTTP routes.

FACTS ABOUT THE SARVAM SDK (sarvamai 0.1.37) — follow exactly
- Client: SarvamAI(api_subscription_key=KEY, timeout=60.0). Auth failures are HTTP 403, not 401.
- Speech to text:
    client.speech_to_text.transcribe(file=(filename, audio_bytes), model="saaras:v4",
                                     mode="codemix", language_code=lang)  -> .transcript
  Chrome's webm/opus recordings are accepted as-is (no conversion). REST audio limit is 30 seconds.
- Text to speech:
    client.text_to_speech.convert(text=text[:2500], language_code=lang, model=..., speaker=...)
  The response .audios is a LIST of base64 strings: base64-decode "".join(r.audios) to get one WAV.
  Pass pace=0.95, and before speaking rewrite 10-digit mobile numbers as two digit-by-digit groups
  ("9 8 7 6 5, 4 3 2 1 0") so they are easy to check by ear.
  bulbul:v4-flash speakers are persona IDs (e.g. "aarti_hi_customer"); v3 names like "shubh" are
  invalid on v4-flash. Malayalam and Odia have no v4-flash voices: use bulbul:v3 with speaker "priya".
- Translate: client.text.translate(input=..., source_language_code="en-IN",
  target_language_code=lang, model="mayura:v1") -> .translated_text (max 1000 chars).
- Transliterate: client.text.transliterate(input=..., source_language_code=lang,
  target_language_code="en-IN") -> .transliterated_text
- Chat: client.chat.completions(...)  — NOT client.chat.completions.create(...).
  Always pass reasoning_effort=None (reasoning is on by default and eats max_tokens).
  For structured output use a FORCED TOOL CALL:
      tools=[{"type":"function","function":{"name":"respond","description":"...","parameters":SCHEMA}}],
      tool_choice={"type":"function","function":{"name":"respond"}}
  then json.loads(r.choices[0].message.tool_calls[0].function.arguments).
  Do NOT use response_format={"type":"json_schema",...}: on sarvam-105b it loops emitting
  whitespace until max_tokens and returns broken JSON.
- Document AI (Sarvam Vision) extract:
    job = client.doc_ai.extract(file=[(filename, bytes, content_type)],   # a LIST of tuples
                                schema=json.dumps(SCHEMA),                # a JSON STRING
                                output_format="json")                     # there is NO language param
  Poll client.doc_ai.get_status(job_id=job.job_id).status (lowercase it) every ~1.5 s until
  "completed" or "partially_completed" (fail on "failed"/"rejected", time out at 90 s), then
  client.doc_ai.get_results(job_id=job.job_id).result is a dict shaped like SCHEMA.
  Accepts PDF (max 10 pages), PNG, JPG.

RULES
- The model suggests; the server decides. Every value the model returns is normalised and
  validated in code before it is stored. Invalid values are rejected and the agent asks again.
- Never block the user with silence: if a Sarvam call fails, return a short spoken apology and an
  error message for the UI.
- Write clean, typed, small functions. No mock modes, no dead code.

I will now give you the build in phases. Do one phase at a time and stop after each so I can check it.
~~~

---

# Part 2 — Build phases

## Phase 1 — Project skeleton and Sarvam wrappers

~~~text
PHASE 1. Create:
- requirements.txt: sarvamai==0.1.37, fastapi>=0.115, uvicorn[standard]>=0.30,
  python-multipart>=0.0.9, python-dotenv>=1.0
- .env.example with SARVAM_API_KEY=   and a .gitignore (.venv, __pycache__, .env)
- app/__init__.py (empty)
- app/config.py:
  - load .env; SARVAM_API_KEY (raise RuntimeError if empty); STT_MODEL="saaras:v4";
    LLM_MODEL="sarvam-105b"; TRANSLATE_MODEL="mayura:v1".
  - frozen dataclass Language(code, name, english, speak, complete, tts_model, speaker) and
    LANGUAGES = {code: Language} with exactly these rows:
      hi-IN हिन्दी Hindi बोलिए पूर्ण bulbul:v4-flash aarti_hi_customer
      en-IN English English Speak "" bulbul:v4-flash ishita_en_customer
      te-IN తెలుగు Telugu మాట్లాడండి పూర్తి bulbul:v4-flash kavitha_te_conversation
      ta-IN தமிழ் Tamil பேசுங்கள் முடிந்தது bulbul:v4-flash gokul_ta_narration
      kn-IN ಕನ್ನಡ Kannada ಮಾತನಾಡಿ ಪೂರ್ಣ bulbul:v4-flash chaitra_kn_conversation
      bn-IN বাংলা Bengali বলুন সম্পূর্ণ bulbul:v4-flash roopa_bn_conversational
      mr-IN मराठी Marathi बोला पूर्ण bulbul:v4-flash ishita_mr_conversational
      gu-IN ગુજરાતી Gujarati બોલો પૂર્ણ bulbul:v4-flash pooja_gu_customer
      pa-IN ਪੰਜਾਬੀ Punjabi ਬੋਲੋ ਪੂਰਾ bulbul:v4-flash anand_pa_customer
      ml-IN മലയാളം Malayalam സംസാരിക്കൂ പൂർത്തിയായി bulbul:v3 priya
      od-IN ଓଡ଼ିଆ Odia କୁହନ୍ତୁ ସମ୍ପୂର୍ଣ୍ଣ bulbul:v3 priya
- app/sarvam.py with a cached client and these functions, following the SDK facts exactly:
    transcribe(audio: bytes, filename: str, lang: str) -> str
    speak(text: str, lang: str) -> str          # one base64 WAV string
    translate(text: str, lang: str) -> str      # returns text unchanged for en-IN
    romanise(text: str, lang: str) -> str       # returns text unchanged if already ASCII
    agent_step(messages: list, schema: dict) -> dict   # forced tool call named "respond",
                                                       # reasoning_effort=None, temperature=0.2, max_tokens=600
    vision_extract(document: bytes, filename: str, content_type: str, schema: dict) -> dict
Stop after this phase.
~~~

**Check:** in a Python shell, `sarvam.translate("Date of birth", "hi-IN")` returns `जन्मतिथि`,
`sarvam.romanise("रवि कुमार", "hi-IN")` returns `Ravi Kumar`, and `speak` returns a long base64 string.

## Phase 2 — Forms: reading a scan and validating answers

~~~text
PHASE 2. Create app/forms.py.

1. SCAN_SCHEMA (sent to Sarvam Vision for a photo of a form), exactly:
{"type":"object","properties":{
  "form_title":{"type":"string","description":"Title of the form translated to English, e.g. 'Application for Income Certificate'"},
  "fields":{"type":"array",
    "description":"Every blank the applicant must fill, in printed order. Skip signature, photo, thumb impression and 'for office use only' boxes.",
    "items":{"type":"object","properties":{
      "label":{"type":"string","description":"The field's label translated to English"},
      "options":{"type":"string","description":"If the field is a tick-box or multiple choice, the options separated by '|', else empty"},
      "filled_value":{"type":"string","description":"Value already written in the blank, empty if blank"}}}}}}

2. Dataclasses:
   Field(key, label, kind, options: list[str]) with properties hint (from HINTS) and askable (kind != "sensitive").
   Form(title, fields) with get(key) and an askable property.

3. Field kinds and hints:
   name "Full name, written in English letters"; date "Format DD/MM/YYYY";
   phone "10-digit Indian mobile number, digits only"; number "Digits only";
   choice "Pick one of the options"; text "Short answer in English";
   sensitive "Sensitive: the applicant writes this by hand".
   Kind detection from the label, in this order:
   options present -> choice; regex aadha?ar|bank|account|ifsc|\bpan\b|password|otp|card number -> sensitive;
   date|dob|birth -> date; mobile|phone|contact no|whatsapp -> phone;
   income|amount|salary|\brs\b|₹|rupees|\bage\b|pin ?code -> number; \bname\b -> name; else text.

4. from_scan(result) -> (Form, prefilled: dict). Strip leading numbering ("1. ", "2) ") and a trailing
   colon from labels, skip empty labels, cap at 20 fields, split options on "|", and make unique
   snake_case keys from labels (max 40 chars, add _2, _3 for duplicates). filled_value of askable
   fields goes into prefilled. Title defaults to "Scanned form".

5. id_document_schema(form): {"type":"object","properties":{key:{"type":"string",
   "description": f"{label}. {hint}"} for each askable field}} — used to read an ID card.

6. normalize(field, value, lang):
   phone/number -> digits only; choice -> exact case-insensitive match, else WHOLE-WORD match with
   the LONGEST option first (so "Female" never matches "Male"); name/text -> sarvam.romanise
   (keep the raw value if that call fails); date unchanged.

7. problem(field, value) -> reason string or None:
   not askable -> reject; empty -> reject; phone must match ^[6-9]\d{9}$; date must match
   ^\d{2}/\d{2}/\d{4}$; number must be digits; name must be 2+ chars with no digits;
   choice must be exactly one of the options.

8. to_dict(field) -> asdict plus "hint".
Stop after this phase.
~~~

**Check:** `normalize(Field("g","Gender","choice",["Male","Female","Other"]), "She is Female", "hi-IN")`
returns `Female`; `problem` rejects a phone value of `98765`.

## Phase 3 — The agent

~~~text
PHASE 3. Create app/agent.py.

1. Session dataclass: lang, form, id (12 hex chars), values: dict, history: list[dict],
   local_labels: dict, done: bool. Methods:
   - complete: every askable field has a value.
   - set(key, raw) -> (changed: bool, problem: str|None): normalize, validate, store only if valid and different.
   - to_dict(): {id, lang, done, values, form: {title, fields: [field dict + local_label]}}.
   SESSIONS: dict[str, Session].

2. start(lang, form, prefilled): create a session, translate every field label into the user's
   language in parallel (6 threads, cache by (label, lang), fall back to English on error),
   apply prefilled values through set(), store and return it.

3. Agent schema for the tool call:
   {"type":"object","required":["updates","reply","done"],"properties":{
     "updates":{"type":"array","description":"Fields to set or correct from what the user just said. Empty if none.",
       "items":{"type":"object","required":["field","value"],"properties":{
         "field":{"type":"string","enum":[askable field keys]},"value":{"type":"string"}}}},
     "reply":{"type":"string","description":"What Sahayak says next, in the user's language."},
     "done":{"type":"boolean","description":"True only after the user confirmed the full read-back."}}}

4. System prompt — use this text exactly, filling in the placeholders:
---
You are Sahayak, a warm, patient assistant helping someone fill the "{form title}" by voice.
The user may not read English. Speak ONLY in {English language name} ({native name}), using simple everyday words.
English words that people commonly mix in (form, mobile, college) are fine. Your reply is spoken aloud
to someone who may be elderly or anxious, so be clear and brief:
- Keep every reply under 20 words, and ALWAYS end with the next question (until the read-back).
- Shape: the value you just saved, then the next question, e.g. "Lakshmi Priya, noted. Your father's name?"
  Repeating the value lets the user catch a mistake. Don't say "I have written it down".
- When asking for a date or mobile number, give the format in a few words ("day, month and year").
- If the user asks what a field means, sounds unsure, or says they don't know, explain it in one simple
  sentence with an everyday example, then ask again.
- No lists, no markdown, no emojis. Write numbers and dates as digits (9840950950, 12/03/2003, 200000).

Current form:
- {key} ({label}; {hint}[; options: A / B / C]): {current value or MISSING}     <- one line per askable field
[The user writes these by hand; never ask for them: {sensitive labels}.]

You last asked about {first missing key} ({label}), so a short answer like a bare name or number is most likely
its value. After saving it, ask about the next MISSING field in order.
   <- or, when nothing is missing: "Every field is filled: read all values back and ask the user to confirm."

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
7. You only fill the form; you cannot submit it. When done, say it is ready to print or save, and to sign it.
---

5. step(session, user_text | None) -> {reply, changed, error, llm_s}:
   - messages = [system prompt, last 12 history messages, user message]. For user_text None, the
     user message is "Greet me briefly, say which form we are filling, and ask the first question."
   - Record complete_before = session.complete BEFORE applying anything.
   - Call sarvam.agent_step. On any exception, reply with a translated "Sorry, please say that again." and set error.
   - Apply each update through session.set(); collect changed keys and rejected values with reasons.
   - Append the user text (if any) to history.
   - If anything was rejected, make one more agent_step call whose user message is:
     "(System check: {key}={value!r} was NOT saved ({reason}); .... Politely say it seems wrong and ask
     for it again. Do not repeat any other question.)" and use its reply instead.
   - Append the reply to history.
   - done = model said done AND complete_before AND nothing changed AND nothing rejected.
     (Without this rule the model marks the form done while it is still reading back.)

6. fill_from_document(session, found) -> (changed keys, note for the agent): apply values through set();
   note is "I uploaded a document. These fields were filled from it: k=v, ..." or
   "I uploaded a document but no form fields could be read from it."

7. edit(session, key, value): store a manual correction and add
   "(I corrected {key} to {value!r} myself.)" to history.

8. remove_field(session, key): drop a blank that Sarvam Vision detected by mistake (remove it from
   the form and its value) and add "(I removed the field {label!r}; it is not on my form.)" to history.
Stop after this phase.
~~~

**Check:** build a Form by hand with a name and a phone field, call `step(s, None)` (you get a
Hindi greeting), then `step(s, "मेरा नाम रवि कुमार है")`, and `s.values` contains `Ravi Kumar`.

## Phase 4 — HTTP API

~~~text
PHASE 4. Create app/main.py (FastAPI). Accept uploads of application/pdf, image/png, image/jpeg only
(400 "Use a photo (JPG or PNG) or a PDF of up to 10 pages." otherwise; 400 if empty). Unknown
language -> 400. Unknown session -> 404 "This session has ended. Start over.".
Time each Sarvam stage in seconds (2 decimals) under the keys scan_s, doc_s, stt_s, llm_s, tts_s.

Every turn-like response has this shape:
{"heard": str|null, "reply": str, "audio_b64": str|null, "changed": [keys],
 "error": str|null, "timings": {...}, "state": session.to_dict()}
The reply is spoken with sarvam.speak; if speaking fails, audio_b64 is null and error explains.

Routes:
- GET  /api/config -> {"languages":[{code,name,english,speak,complete}]}
- GET  /api/instruction?lang= -> {"text","audio_b64"}: translate and speak
  "Hold your form in front of the camera so the whole page is visible, then press the button."
  Cache successful results per language; on failure return the English text with audio_b64 null.
- POST /api/form/scan (multipart: lang, file) -> vision_extract with SCAN_SCHEMA, forms.from_scan,
  422 "No blanks were found. Retake the photo with the whole page in view and good light." if no fields,
  502 if Sarvam Vision fails; then agent.start and agent.step(s, None), translating the field labels
  in a background thread at the same time (the greeting doesn't need them).
- On startup, pre-generate the spoken instruction for all 11 languages in a background thread.
- POST /api/turn (multipart: session_id, and either audio file or text) -> transcribe if audio,
  400 "Nothing was heard. Tap the mic and speak, or type your answer." if empty, then agent.step.
- POST /api/document (multipart: session_id, file) -> vision_extract with id_document_schema,
  fill_from_document, then agent.step with the note; changed = union of both.
- POST /api/session/{id}/field (JSON {field, value}) -> agent.edit, returns session.to_dict(); 400 if unknown field.
- DELETE /api/session/{id}/field/{key} -> agent.remove_field, returns session.to_dict(); 400 if unknown field.
- GET / serves static/index.html; mount /static.
Stop after this phase.
~~~

**Check:** `uvicorn app.main:app --port 8000`, then POST a photo of a form to `/api/form/scan`
(for example with curl). The response lists the form's fields and has a greeting in `reply`.

## Phase 5 — The web page

~~~text
PHASE 5. Create static/index.html, static/style.css, static/app.js. No framework.

LOOK
- Palette (Indian paperwork): security-paper mint #dfece3 background with faint diagonal hatching,
  form sheet #f6fbf6, teal ink #0e3b43 (text and the voice panel), rules #b8d0c1,
  voter-ink violet #5b2bb5 for every written answer and the stamp, marigold #f5a524 only while listening.
- Fonts from Google Fonts: the Anek family for all scripts (Anek Latin, Devanagari, Telugu, Tamil,
  Kannada, Bangla, Gujarati, Gurmukhi, Malayalam, Odia) for UI text; Kalam (handwriting) for the
  answers written on the form.
- A guilloche rosette SVG (concentric ellipses) as the form's seal and a faint welcome watermark.
- No all-caps labels, no generic rounded cards. Visible keyboard focus. Respect prefers-reduced-motion.
  Works on phones (single column under 900px).

SCREENS
1. Welcome: headline "Fill your form by speaking.", a grid of 11 language buttons, each showing the
   "speak" word large and "native name, English name" small.
2. Show your form: headline "Show Sahayak your form.", the instruction text from /api/instruction in
   violet (and play its audio), buttons "Scan with camera" and "Upload a photo or PDF",
   and "No form with you? Scan a sample photo" (uses a bundled static/sample-income-form.png).
3. Camera overlay: live <video> from getUserMedia (facingMode environment, ideal 1920x1440) with four
   corner guides, a round shutter button, Cancel, and "Upload instead". Capture draws the frame to
   a canvas and sends a JPEG (quality 0.92). Escape closes it. If the camera fails, say so and keep upload.
4. Scanning overlay: the photo with a violet scan line sweeping top to bottom, text
   "Sarvam Vision is reading the blanks on your form". On error show the message and "Try another photo".
5. Workspace, two columns:
   - Left (teal): the current question in large type ("long" smaller style if over 110 chars),
     "Hear it again", a scrolling history (previous questions, the user's answers right-aligned
     with a violet border), a 96px round mic button (ripples while recording, spinner while busy),
     a status line ("Listening… speak your answer"), "Or type your answer" input, "Fill from my ID or marksheet" (opens the camera
     overlay for an ID), and the stage timings as "Scanning 5.6s, Thinking 0.9s, Voice 1.5s".
   - Right: the form as a paper sheet: seal, "Read from your photo by Sarvam Vision" + "View photo"
     link, the form title, "{answered}/{total} answered", numbered fields with the English label and
     the translated label. Text answers are contentEditable lines in Kalam violet; editing and blurring
     POSTs a correction. Choice fields render as tick boxes (clicking one saves it). Sensitive fields
     show "Write this yourself on the paper form. Sahayak never asks for it." The next missing field
     has an "Asking now" tag. Until the form is done, each field has a small "Not on my form" link
     (shown on hover, always on touch screens) that calls the DELETE route.
   - New answers "write" in with a left-to-right clip-path animation. When done, a round violet
     "Confirmed" stamp (with the language's "complete" word) lands with a short scale-down animation,
     and a "Save as PDF" button (window.print; print CSS shows only the form) appears.

BEHAVIOUR
- Hands-free listening for the whole form: open the mic once (getUserMedia with echoCancellation,
  noiseSuppression, autoGainControl) and keep it open. After Sahayak finishes speaking, start a
  MediaRecorder on that stream (first supported of audio/webm;codecs=opus, audio/webm, audio/mp4,
  audio/ogg). Use a Web Audio AnalyserNode to measure loudness every 50 ms: calibrate the room's noise
  for the first 300 ms (threshold = clamp(noise x 2.5, 0.012, 0.05)), treat 250 ms above the threshold
  as speech, and stop and send after 1.3 s of silence (or 25 s total). If nobody speaks for 15 s,
  silently start a fresh recording. Never record while Sahayak is speaking. Pause listening while
  typing, while the camera or scan overlay is open, and after the form is done. The mic button
  pauses and resumes; its glow grows with the voice level. A "Nothing was heard" response just
  restarts listening. If the mic is blocked, say so in the status line and keep typing available.
- After every response: move the previous question into history, add the heard text, show any error,
  re-render the form, play audio_b64 as a data:audio/wav URL.
- Use textContent (never innerHTML) for any text that comes from the server.
Stop after this phase.
~~~

**Check:** open http://localhost:8000, pick Telugu, "Scan a sample photo": the form appears with
its blanks and you hear a Telugu greeting.

## Phase 6 — Live smoke test

~~~text
PHASE 6. Create scripts/smoke_test.py that runs against the live API and prints PASS/FAIL with timings for:
translate, romanise, speak, transcribe (round-trip the audio from speak), scan the bundled sample form
with SCAN_SCHEMA, and one agent conversation of two steps on that form. Optional argument: a path to an
ID photo to test id_document_schema extraction. Exit 1 if any check fails.
~~~

**Check:** `python scripts/smoke_test.py` prints all PASS.

---

# Part 3 — Acceptance test

Run this conversation on the sample income-certificate form, in Hindi. All of these must hold:

| Step | You say | Expected |
|---|---|---|
| 1 | *(scan the form)* | 9 blanks found; Gender is a tick box with Male / Female / Other |
| 2 | "मेरा नाम सुनीता देवी है, पति का नाम रमेश यादव" | Two fields filled: `Sunita Devi`, `Ramesh Yadav` |
| 3 | "मोबाइल 98765" | Not saved; Sahayak asks again politely |
| 4 | "9123456780" | Mobile saved |
| 5 | "जन्म पांच जनवरी उन्नीस सौ नब्बे" | `05/01/1990` |
| 6 | "किसान हूँ, आय डेढ़ लाख" | Occupation `Farmer`, income `150000` |
| 7 | "महिला" | **Female** ticked (not Male) |
| 8 | (remaining answers) | Sahayak reads everything back; form NOT yet complete |
| 9 | "नहीं, आय दो लाख है" | Income becomes `200000`; it reads back again; still not complete |
| 10 | "हाँ सब सही है" | Stamp lands; "Save as PDF" appears; it tells you to print and sign |

Also check: "Not on my form" removes a field and Sahayak never asks about it, uploading a `.txt` is
refused with a clear message, the ID pre-fill fills the name and
date of birth from a marksheet photo, and no field asking for Aadhaar or bank details is ever spoken.

---

# Part 4 — If something goes wrong

| Symptom | Cause | Fix to tell the agent |
|---|---|---|
| `AttributeError ... completions.create` | Wrong method name | Use `client.chat.completions(...)` |
| Agent replies are empty or cut off | Reasoning used the token budget | Pass `reasoning_effort=None` |
| Broken JSON, very slow turns (~50 s) | `response_format` json_schema loop | Use the forced tool call |
| Doc AI `TypeError` or `'dict' has no attribute 'read'` | Wrong argument shapes | `file` is a list of tuples; `schema` is `json.dumps(...)` |
| Doc AI rejects `language` | Not a parameter in this SDK | Remove it |
| Audio file won't play | Base64 not decoded | Decode `"".join(r.audios)` |
| TTS 422 invalid speaker | v3 name on v4-flash | Use the persona IDs from Phase 1 |
| "Female" saved as "Male" | Substring matching | Whole-word, longest option first |
| Stamp appears before the user says yes | Model sets done during the read-back | Done only if complete before the turn and nothing changed |
| Camera or mic blocked | Page not on a secure origin | Use `localhost` or HTTPS |
| Every call returns 403 | Bad key | Check `SARVAM_API_KEY` (403 means a bad key, not 401) |
