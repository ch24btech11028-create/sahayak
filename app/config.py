"""Settings and the languages Sahayak speaks."""

import os
from dataclasses import dataclass

from dotenv import load_dotenv

load_dotenv()

SARVAM_API_KEY = os.getenv("SARVAM_API_KEY", "").strip()
if not SARVAM_API_KEY:
    raise RuntimeError("SARVAM_API_KEY is not set. Copy .env.example to .env and add your key.")

STT_MODEL = "saaras:v4"
LLM_MODEL = "sarvam-105b"
TRANSLATE_MODEL = "mayura:v1"


@dataclass(frozen=True)
class Language:
    code: str
    name: str        # in its own script
    english: str
    speak: str       # "speak" in this language, shown on the language picker
    complete: str    # "complete", stamped on the finished form
    tts_model: str
    speaker: str


# Bulbul v4 Flash has no Malayalam or Odia voices yet, so those two use Bulbul v3.
LANGUAGES = {lang.code: lang for lang in [
    Language("hi-IN", "हिन्दी", "Hindi", "बोलिए", "पूर्ण", "bulbul:v4-flash", "aarti_hi_customer"),
    Language("en-IN", "English", "English", "Speak", "", "bulbul:v4-flash", "ishita_en_customer"),
    Language("te-IN", "తెలుగు", "Telugu", "మాట్లాడండి", "పూర్తి", "bulbul:v4-flash", "kavitha_te_conversation"),
    Language("ta-IN", "தமிழ்", "Tamil", "பேசுங்கள்", "முடிந்தது", "bulbul:v4-flash", "gokul_ta_narration"),
    Language("kn-IN", "ಕನ್ನಡ", "Kannada", "ಮಾತನಾಡಿ", "ಪೂರ್ಣ", "bulbul:v4-flash", "chaitra_kn_conversation"),
    Language("bn-IN", "বাংলা", "Bengali", "বলুন", "সম্পূর্ণ", "bulbul:v4-flash", "roopa_bn_conversational"),
    Language("mr-IN", "मराठी", "Marathi", "बोला", "पूर्ण", "bulbul:v4-flash", "ishita_mr_conversational"),
    Language("gu-IN", "ગુજરાતી", "Gujarati", "બોલો", "પૂર્ણ", "bulbul:v4-flash", "pooja_gu_customer"),
    Language("pa-IN", "ਪੰਜਾਬੀ", "Punjabi", "ਬੋਲੋ", "ਪੂਰਾ", "bulbul:v4-flash", "anand_pa_customer"),
    Language("ml-IN", "മലയാളം", "Malayalam", "സംസാരിക്കൂ", "പൂർത്തിയായി", "bulbul:v3", "priya"),
    Language("od-IN", "ଓଡ଼ିଆ", "Odia", "କୁହନ୍ତୁ", "ସମ୍ପୂର୍ଣ୍ଣ", "bulbul:v3", "priya"),
]}
