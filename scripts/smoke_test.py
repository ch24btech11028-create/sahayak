"""Check every Sarvam call Sahayak depends on, against the live API.

    .venv/bin/python scripts/smoke_test.py                                  # all checks
    .venv/bin/python scripts/smoke_test.py samples/sample_marksheet.png     # also pre-fill from an ID
"""

import base64
import json
import mimetypes
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app import agent, forms, sarvam  # noqa: E402

SAMPLE_FORM = ROOT / "static" / "sample-income-form.png"
passed: list[bool] = []


def _describe(value) -> str:
    if isinstance(value, bytes):
        return f"{len(value):,} bytes of audio"
    if isinstance(value, tuple) and isinstance(value[0], forms.Form):
        return f"{value[0].title!r}, {len(value[0].fields)} blanks"
    return str(value)[:160]


def check(name: str, fn):
    started = time.monotonic()
    try:
        detail = fn()
        print(f"PASS  {name:<30} {time.monotonic() - started:5.2f}s  {_describe(detail)}")
        passed.append(True)
        return detail
    except Exception as e:
        print(f"FAIL  {name:<30} {time.monotonic() - started:5.2f}s  {type(e).__name__}: {e}")
        passed.append(False)


def main():
    check("translate (Mayura)", lambda: sarvam.translate("Date of birth", "hi-IN"))
    check("romanise (transliterate)", lambda: sarvam.romanise("रवि कुमार", "hi-IN"))

    speech = check("speak (Bulbul)", lambda: base64.b64decode(sarvam.speak("आपका पूरा नाम क्या है?", "hi-IN")))
    if speech:
        check("transcribe (Saaras)", lambda: repr(sarvam.transcribe(speech, "speech.wav", "hi-IN")))

    scan = check("scan form (Sarvam Vision)", lambda: forms.from_scan(
        sarvam.vision_extract(SAMPLE_FORM.read_bytes(), SAMPLE_FORM.name, "image/png", forms.SCAN_SCHEMA)))
    if scan:
        form, _ = scan
        print("      " + ", ".join(f"{f.label} [{f.kind}]" for f in form.fields))

        def conversation():
            s = agent.start("hi-IN", form, {})
            for said in (None, "मेरा नाम सुनीता देवी है और मोबाइल 9123456780"):
                result = agent.step(s, said)
                if result["error"]:
                    raise RuntimeError(result["error"])
            return json.dumps(s.values, ensure_ascii=False)
        check("agent step (Sarvam-105B)", conversation)

        if len(sys.argv) > 1:
            path = Path(sys.argv[1])
            content_type = mimetypes.guess_type(path.name)[0] or "application/pdf"
            check("pre-fill from ID", lambda: sarvam.vision_extract(
                path.read_bytes(), path.name, content_type, forms.id_document_schema(form)))

    print(f"\n{sum(passed)}/{len(passed)} checks passed")
    sys.exit(0 if all(passed) else 1)


if __name__ == "__main__":
    main()
