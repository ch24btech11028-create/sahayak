# Sahayak — pitch and explanation

---

## 1. The 60-second pitch (say this out loud)

> Think of the last time someone in your family had to fill a government form: an income
> certificate, a scholarship, a ration card. The form is in English. The person filling it often
> isn't comfortable in English. So they stand in a queue, or pay an agent, or ask someone to fill it
> for them, and hope it's right.
>
> **Sahayak fixes that with one photo and a conversation.**
>
> *(hold the form up to the camera)*
>
> I scan the form. Sarvam Vision reads every blank on it: the name, the date of birth, even
> these tick boxes. Now Sahayak asks me each question, out loud, in Telugu.
>
> *(answer two questions, one mixing Telugu and English)*
>
> I answer the way people actually talk, mixing in English. It writes the form in proper English,
> checks the mobile number, turns "ఒకటిన్నర లక్ష" into 150000, ticks the right box, and reads
> everything back before stamping it complete.
>
> Nothing in it is written for this one form: it reads the blanks from the photo. It speaks 11
> Indian languages and never asks for Aadhaar or bank details out loud. And it runs on Sarvam
> end to end: Vision reads, Saaras listens, Sarvam-105B thinks, Bulbul speaks.
>
> Sahayak means "helper". That's what it is: a helper for every form, in every language.

**Timing:** about 30 seconds of talking and 30 seconds of demo. Practise until the demo part
needs no thought.

---

## 2. Demo plan for the showcase

**Before you go up**
- Open http://localhost:8000 once while online, so the fonts are cached.
- Have a printed form ready (the sample in `static/sample-income-form.png`, or a real one).
- Test the mic and camera once at the venue, with the laptop volume up.
- Keep a second tab already on the scan screen as a backup.

**On stage (about 60 seconds)**
1. Tap **తెలుగు** (or Hindi). It speaks the instruction aloud: point that out ("the user doesn't
   need to read anything").
2. **Scan with camera**, hold the form up, capture. Let the scan line run, then say "it found 9 blanks".
3. Answer the name question by voice. Then give a deliberately wrong mobile number ("98765"):
   it politely asks again. **This is the moment that shows it's an agent, not a recorder.**
4. Answer the rest in one go if time is short; the form fills in violet handwriting.
5. Say "yes" to the read-back. The stamp lands. Click **Save as PDF**.

**If something fails**
- No camera: **Upload a photo** or **Scan a sample photo**.
- Wi-Fi or mic trouble: type the answers in the box; the flow is identical.
- Say calmly: "the network is slow, so I'll type the answer", and carry on. Judges respect a
  clean recovery.

---

## 3. The explanation (for judges, Q&A and the one-on-one)

### The problem
- Forms for income, caste, scholarship, pension and ration cards are mostly printed in English.
- Many applicants are more comfortable in Telugu, Hindi, Tamil or another language, so they depend
  on agents or relatives, pay for help, make mistakes, or don't apply at all.
- Existing apps make you type into a fixed digital form. Sahayak starts from **the paper form
  people already have**, and from **speech**, which everyone can use.

### What Sahayak does
1. **Reads the form from a photo.** One Sarvam Vision call returns the form's title, every blank
   in order, and the options of tick-box fields. Nothing is hard-coded per form. Today it works best
   on clear, printed, single-page forms; a wrongly detected field can be removed and any answer
   corrected by tapping it.
2. **Understands each field.** Each blank gets a kind (name, date, mobile, number, choice, text,
   sensitive), which decides how answers are cleaned and checked.
3. **Holds a conversation.** It asks one question at a time in the user's language, accepts
   several answers in one sentence, handles corrections ("no, the income is 2 lakh"), and reads
   everything back.
4. **Writes a correct English form.** Names in English letters, dates as DD/MM/YYYY, spoken
   numbers as digits, "किसान" as "Farmer", the right box ticked.
5. **Respects privacy.** Aadhaar, bank account and PAN fields are never asked out loud; they're
   marked "write this yourself".
6. **Optional pre-fill.** A photo of an ID card or marksheet fills whatever it can, and the agent
   only asks for the rest.

### How Sarvam powers each step

| Step | Sarvam model | Why this one |
|---|---|---|
| Read the form, pre-fill from an ID | **Sarvam Vision** (Document AI Extract) | Reads Indian-script and English documents and returns structured JSON from a schema |
| Listen | **Saaras v4**, `codemix` mode | Keeps English words in English and Indic words in native script, as people actually speak |
| Think | **Sarvam-105B** | Strong in Indian languages; supports tool calling for structured decisions |
| Speak | **Bulbul v4 Flash** | Natural Indian voices; v3 covers Malayalam and Odia |
| Labels and instructions | **Mayura** | Translates field labels and the scan instruction into the user's language |
| English names | **Transliterate** | "रवि कुमार" → "Ravi Kumar" for the English form |

Each model does one job that the flow needs, and every call is tested against the live API by
`scripts/smoke_test.py`.

### Architecture (one breath)
A FastAPI backend with four small modules: `sarvam.py` makes the API calls, `forms.py` knows
about fields and validation, `agent.py` runs the conversation, and `main.py` exposes the routes.
The frontend is a single page with no framework. Each user turn is one request: speech to text,
one agent step, validation, then the spoken reply.

### Engineering decisions worth mentioning
- **The model suggests, the server decides.** Sarvam-105B returns `{updates, reply, done}`, but
  every value is normalised and validated in code before it touches the form. If a value fails
  (a 9-digit mobile, a name with numbers), the agent is told and asks again.
- **Done means confirmed.** The form is only complete on a turn where everything was already
  filled and the user confirmed with nothing to change. Testing showed the model would otherwise
  mark it done while it was still reading back.
- **Forced tool call instead of JSON schema mode.** Strict `json_schema` output looped on
  whitespace with sarvam-105b. A forced tool call gives the same structured output reliably in
  about 1 second.
- **Reasoning off for conversation.** Thinking mode is on by default and uses up the token budget;
  turning it off keeps turns at 1–2 seconds.
- **A real bug we caught:** "Female" was saved as "Male", because "male" is inside "female".
  Choices now match whole words, longest first.

### Measured speed (live API, sample form)
- Scan a form: about 5.5–7.5 s
- Each answer: about 1–2 s to think, 1–2 s to speak
- Pre-fill from an ID card: about 3.5–4 s

### Who it's for, and what's next
- **Users:** applicants at home, and CSC / Meeseva / e-Mitra operators who fill forms for others
  all day.
- **Next steps:**
  - **WhatsApp:** send a photo of the form, then answer by voice notes.
  - **Phone line:** run the same flow on a Sarvam Voice Agent for people without smartphones.
  - **Write back onto the original:** print answers in the right place on the scanned page.
  - **Explain the form:** "what is this certificate for, which documents do I need".
- **Why it can scale:** nothing is per-form, so a new form is just a new photo. Harder cases
  (multi-page forms, tables, handwriting, writing answers back onto the original page) are the
  next steps, not claims for today.

---

## 4. Likely questions and short answers

**Does it work on any form?**
Nothing in the code is written for one form; it reads the blanks from the photo. It works best on
clear, printed, single-page forms, which is what we're demoing. Multi-page forms, dense tables and
handwritten forms are next.

**Do the answers go back onto the original paper?**
Not yet. Today it produces a clean, completed copy of the form with the same fields. Printing the
answers onto the original page needs each field's position, which is the next step for common forms.

**What if Sarvam Vision misreads a field?**
Every value is visible on the form while you talk and can be tapped and corrected. The read-back
step also catches mistakes before completion.

**How do you stop the AI from writing wrong data?**
The model never writes to the form directly. Code checks every value for its field type, and the
form is only marked done after the user confirms the read-back.

**What about privacy?**
Sensitive fields such as Aadhaar and bank details are detected and never asked out loud. Sessions
are held in memory only and nothing is stored. A production version would add consent and
retention controls.

**Why not just a digital form in many languages?**
People already have the paper form, and many can't type comfortably in any script. Speaking is
the most natural input, and the photo means no one has to rebuild each form.

**How is this different from a chatbot?**
It's an agent with a goal and a state: it knows which blanks are missing, validates each answer,
re-asks on bad input, accepts corrections, and finishes with a verified document.

**What would it cost?**
At Sarvam's published rates, roughly ₹5–10 per form: ₹1 to read the page, about ₹6 for the
spoken replies (₹30 per 10,000 characters), and well under ₹1 for speech recognition and the agent.

**What was the hardest part?**
Making the model reliable: getting structured output that doesn't break, validating every value
in code, and making sure "done" really means the user confirmed.

---

## 5. One-line versions

- **Tagline:** Show it your form, then just talk.
- **For a slide:** Sahayak reads a paper form with Sarvam Vision and fills it through a voice
  conversation in 11 Indian languages.
- **If asked "why Sarvam?":** Indian languages, mixed speech and Indian documents are exactly
  what Sarvam's models are built for, and the whole flow runs on them end to end.
