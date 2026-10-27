"""Development-only, uses upstream PaddleOCR directly on labeled synthetic crop fixtures."""
import argparse
import json
import os
from pathlib import Path
import time

ROOT = Path(__file__).resolve().parents[1]
os.environ["PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK"] = "True"
os.environ["PADDLE_PDX_MODEL_SOURCE"] = "HF"
os.environ["DO_NOT_TRACK"] = "1"


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--model", required=True)
    p.add_argument("--image", required=True)
    args = p.parse_args()
    start = time.perf_counter()
    from paddleocr import TextRecognition
    model = TextRecognition(model_name=args.model,
                            model_dir=str(ROOT / "models" / ("PaddlePaddle--" + args.model)),
                            device="cpu", enable_mkldnn=False, cpu_threads=2)
    load_ms = (time.perf_counter() - start) * 1000
    start = time.perf_counter()
    results = list(model.predict(input=args.image, batch_size=1))
    rows = [{"text": x.get("rec_text", ""), "score": float(x.get("rec_score", 0))} for x in results]
    print("LENS_RESULT=" + json.dumps({"load_ms": load_ms, "infer_ms": (time.perf_counter()-start)*1000,
                                       "results": rows}, ensure_ascii=True))


if __name__ == "__main__":
    main()
