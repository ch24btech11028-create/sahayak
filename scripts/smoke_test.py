"""Check every Sarvam call Sahayak depends on. Run once your key is in .env:

    .venv/bin/python scripts/smoke_test.py            # all checks
    .venv/bin/python scripts/smoke_test.py doc samples/id.jpg   # also test Doc AI on a file

Each check prints PASS/FAIL with timing, so you know what works before the build hour.
"""

import base64
import json
import mimetypes
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import agent, config, sarvam  # noqa: E402

OUT = Path(__file__).resolve().parent.parent / "samples" / "out"
results = []


def check(name, fn):
    t = time.time()
    try:
        detail = fn()
        results.append(True)
        print(f"PASS  {name:<34} {time.time() - t:5.2f}s  {detail}")
        return detail
    except Exception as e:
        results.append(False)
        print(f"FAIL  {name:<34} {time.time() - t:5.2f}s  {type(e).__name__}: {e}")


def main():
    if config.MOCK:
        print("No SARVAM_API_KEY (or SAHAYAK_MOCK=1). Add your key to .env first.")
        sys.exit(1)
    OUT.mkdir(parents=True, exist_ok=True)

    check("translate (mayura:v1)", lambda: sarvam.translate("Date of birth", "hi-IN"))
    check("transliterate to Latin", lambda: sarvam.to_latin("रवि कुमार", "hi-IN"))

    def tts():
        wav = base64.b64decode(sarvam.speak("नमस्ते! आपका पूरा नाम क्या है?", "hi-IN"))
        (OUT / "tts_hi.wav").write_bytes(wav)
        return f"{len(wav)} bytes → samples/out/tts_hi.wav"
    check("TTS hi-IN (bulbul:v4-flash)", tts)
    check("TTS ml-IN (bulbul:v3 fallback)", lambda: f"{len(sarvam.speak('നമസ്കാരം', 'ml-IN'))} b64 chars")

    def stt():
        # Round-trip: transcribe the audio we just generated.
        return repr(sarvam.transcribe((OUT / "tts_hi.wav").read_bytes(), "tts_hi.wav", "hi-IN"))
    check("STT round-trip (saaras:v4 codemix)", stt)

    def chat():
        s = agent.create_session("hi-IN")
        first = agent.run_turn(s, "(start)")
        if first.get("error"):
            raise RuntimeError(first["error"])
        second = agent.run_turn(s, "मेरा नाम Ravi Kumar है और मेरा mobile नौ आठ चार शून्य नौ पांच शून्य नौ पांच शून्य है")
        if second.get("error"):
            raise RuntimeError(second["error"])
        return f"greeting={first['reply']!r} | values={json.dumps(s['values'], ensure_ascii=False)} | next={second['reply']!r}"
    check("agent turns (sarvam-105b JSON)", chat)

    if len(sys.argv) >= 3 and sys.argv[1] == "doc":
        path = Path(sys.argv[2])
        ctype = mimetypes.guess_type(path.name)[0] or "application/pdf"
        check("Doc AI extract", lambda: sarvam.extract_fields(path.read_bytes(), path.name, ctype,
                                                               config.FORM["fields"]))

    ok = sum(results)
    print(f"\n{ok}/{len(results)} checks passed")
    sys.exit(0 if ok == len(results) else 1)


if __name__ == "__main__":
    main()
