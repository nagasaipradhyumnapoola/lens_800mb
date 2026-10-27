"""Pinned PaddleOCR reference smoke; synthetic crops never certify real UI OCR quality."""
import hashlib
import json
from pathlib import Path
import sys
import subprocess
from urllib.request import urlopen
from PIL import Image, ImageDraw, ImageFont, features

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from benchmarks.metrics import error_rate
from benchmarks.process import measure
from scripts.fetch_models import fetch
from scripts.benchmark import write_csv

CASES = [
    ("en", "Latin", "PP-OCRv6_tiny_rec", "Meet Arun tomorrow at 15:00", "C:/Windows/Fonts/arial.ttf"),
    ("es", "Latin", "PP-OCRv6_tiny_rec", "Reunión con Ana mañana a las 15:00", "C:/Windows/Fonts/arial.ttf"),
    ("zh", "Han", "PP-OCRv6_tiny_rec", "明天15:00在北京开会", "C:/Windows/Fonts/msyh.ttc"),
    ("hi", "Devanagari", "devanagari_PP-OCRv5_mobile_rec", "कल 15:00 बजे दिल्ली में बैठक है", "C:/Windows/Fonts/Nirmala.ttc"),
]


def main():
    locks = json.loads((ROOT / "third_party/model-lock.json").read_text())
    for model in sorted({x[2] for x in CASES}):
        repo = "PaddlePaddle/" + model
        with urlopen(f"https://huggingface.co/api/models/{repo}/revision/main?blobs=true", timeout=60) as src:
            meta = json.load(src)
        for item in meta["siblings"]:
            if item["rfilename"] in ("inference.json", "inference.yml", "inference.pdiparams"):
                rec = fetch(repo, meta["sha"], item)
                locks = [x for x in locks if x["path"] != rec["path"]] + [rec]
    (ROOT / "third_party/model-lock.json").write_text(json.dumps(locks, indent=2)+"\n", encoding="utf-8")
    folder = ROOT / "artifacts/ocr-smoke"
    folder.mkdir(parents=True, exist_ok=True)
    rows = []
    for lang, script, model, text, font_path in CASES:
        error, result, hypothesis, score = None, None, "", 0
        try:
            if not Path(font_path).exists():
                raise FileNotFoundError(f"Font unavailable: {font_path}")
            path = folder / (lang + ".png")
            if lang == "hi" and not features.check("raqm"):
                spec=folder/'hi-spec.json'
                spec.write_text(json.dumps({'text':text},ensure_ascii=False),encoding='utf-8')
                subprocess.run(['powershell.exe','-NoProfile','-STA','-File',str(ROOT/'scripts/render-text-fixture.ps1'),
                                '-SpecPath',str(spec),'-OutputPath',str(path)],check=True,capture_output=True)
            else:
                font = ImageFont.truetype(font_path, 36)
                bbox = font.getbbox(text)
                img = Image.new("RGB", (bbox[2]-bbox[0]+40, bbox[3]-bbox[1]+40), "white")
                ImageDraw.Draw(img).text((20-bbox[0],20-bbox[1]), text, font=font, fill="black")
                img.save(path)
            result = measure([sys.executable, ROOT / "scripts/ocr_worker.py", "--model", model, "--image", path],
                             timeout=180, cwd=ROOT)
            (folder / (lang + "-evidence.json")).write_text(json.dumps(result, indent=2), encoding="utf-8")
            if result["exit_code"] != 0:
                raise RuntimeError(f"PaddleOCR reference exit {result['exit_code']}; see raw evidence")
            line = next(x for x in result["stdout"].splitlines() if x.startswith("LENS_RESULT="))
            prediction = json.loads(line.split("=",1)[1])
            hypothesis = " ".join(x["text"] for x in prediction["results"])
            score = prediction["results"][0]["score"]
        except Exception as exc:
            error = str(exc)
        ce, cc = error_rate(text, hypothesis, chars=True)
        rows.append({"language": lang, "script": script, "model": model, "sample_count": 1,
                     "fixture_kind": "synthetic rendered crop; no real UI validation", "cer": ce/cc,
                     "exact_match": text == hypothesis, "confidence": score, "failure": error,
                     "max_observed_wset_bytes": result["sum_observed_process_peak_wset_bytes"] if result else None,
                     "max_observed_commit_bytes": result["sum_observed_process_peak_commit_bytes"] if result else None,
                     "model_bytes": sum(x["bytes"] for x in locks if x["repo"] == "PaddlePaddle/"+model),
                     "measurement_scope": "development Python/Paddle reference; not a distributable runtime",
                     "certification": "EXPERIMENTAL_SYNTHETIC_SMOKE_ONLY"})
        print(lang, "CER", ce/cc, error or "scored", flush=True)
    for lang, script in [("ta","Tamil"),("te","Telugu"),("bn","Bengali"),("kn","Kannada"),("ml","Malayalam")]:
        rows.append({k: ({"language":lang,"script":script,"sample_count":0,"failure":"NOT TESTED", "certification":"PENDING"}.get(k)) for k in rows[0]})
    write_csv(ROOT / "reports/ocr-by-script.csv", rows)
    (ROOT / "reports/ocr-results.json").write_text(json.dumps(rows, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
