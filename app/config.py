"""Static configuration: the form Sahayak fills, supported languages, and voices."""

import os

from dotenv import load_dotenv

load_dotenv()

SARVAM_API_KEY = os.getenv("SARVAM_API_KEY", "").strip()
# Mock mode lets the whole app run without a key (canned STT/LLM/TTS responses).
MOCK = os.getenv("SAHAYAK_MOCK", "").lower() in ("1", "true", "yes") or not SARVAM_API_KEY

LLM_MODEL = os.getenv("SAHAYAK_LLM_MODEL", "sarvam-105b")
STT_MODEL = "saaras:v4"

# One form type, six fields. `latin` fields are stored in English/Roman script on the form.
FORM = {
    "id": "scholarship",
    "title": "Post-Matric Scholarship Application",
    "fields": [
        {"key": "student_name", "label": "Student's full name", "latin": True,
         "hint": "Full name as on school certificate"},
        {"key": "father_name", "label": "Father's / guardian's name", "latin": True,
         "hint": "Full name of father or guardian"},
        {"key": "date_of_birth", "label": "Date of birth", "latin": True,
         "hint": "Format DD/MM/YYYY"},
        {"key": "mobile_number", "label": "Mobile number", "latin": True,
         "hint": "10-digit Indian mobile number, digits only"},
        {"key": "institution_name", "label": "College / institution", "latin": True,
         "hint": "Name of the college or school currently studying in"},
        {"key": "annual_family_income", "label": "Annual family income (₹)", "latin": True,
         "hint": "Total yearly family income in rupees, digits only"},
    ],
}
FIELD_KEYS = [f["key"] for f in FORM["fields"]]

# Languages offered in the UI. Bulbul v4 Flash has no Malayalam/Odia personas yet,
# so those fall back to Bulbul v3 with a v3 speaker name.
LANGUAGES = {
    "hi-IN": {"name": "हिन्दी", "english": "Hindi", "tts_model": "bulbul:v4-flash", "speaker": "aarti_hi_customer"},
    "en-IN": {"name": "English", "english": "English", "tts_model": "bulbul:v4-flash", "speaker": "ishita_en_customer"},
    "te-IN": {"name": "తెలుగు", "english": "Telugu", "tts_model": "bulbul:v4-flash", "speaker": "kavitha_te_conversation"},
    "ta-IN": {"name": "தமிழ்", "english": "Tamil", "tts_model": "bulbul:v4-flash", "speaker": "gokul_ta_narration"},
    "kn-IN": {"name": "ಕನ್ನಡ", "english": "Kannada", "tts_model": "bulbul:v4-flash", "speaker": "chaitra_kn_conversation"},
    "bn-IN": {"name": "বাংলা", "english": "Bengali", "tts_model": "bulbul:v4-flash", "speaker": "roopa_bn_conversational"},
    "mr-IN": {"name": "मराठी", "english": "Marathi", "tts_model": "bulbul:v4-flash", "speaker": "ishita_mr_conversational"},
    "gu-IN": {"name": "ગુજરાતી", "english": "Gujarati", "tts_model": "bulbul:v4-flash", "speaker": "pooja_gu_customer"},
    "pa-IN": {"name": "ਪੰਜਾਬੀ", "english": "Punjabi", "tts_model": "bulbul:v4-flash", "speaker": "anand_pa_customer"},
    "ml-IN": {"name": "മലയാളം", "english": "Malayalam", "tts_model": "bulbul:v3", "speaker": "priya"},
    "od-IN": {"name": "ଓଡ଼ିଆ", "english": "Odia", "tts_model": "bulbul:v3", "speaker": "priya"},
}

# "Speak" in each language, shown on the welcome screen so people can find theirs without English.
SPEAK_WORD = {
    "hi-IN": "बोलिए", "en-IN": "Speak", "te-IN": "మాట్లాడండి", "ta-IN": "பேசுங்கள்",
    "kn-IN": "ಮಾತನಾಡಿ", "bn-IN": "বলুন", "mr-IN": "बोला", "gu-IN": "બોલો",
    "pa-IN": "ਬੋਲੋ", "ml-IN": "സംസാരിക്കൂ", "od-IN": "କୁହନ୍ତୁ",
}
