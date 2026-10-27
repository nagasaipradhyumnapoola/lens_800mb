"""Use the pinned upstream Python binding to its native DLL, avoiding Windows ANSI argv.

Development-only. Calls complete(), which returns data and never executes a function.
"""
import json
import os
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
os.environ.update(NEEDLE_TELEMETRY="0", DO_NOT_TRACK="1", HF_HUB_OFFLINE="1",
                  NEEDLE3_LIB_PATH=str(ROOT / "models/Cactus-Compute--needle3/windows-x86_64/libneedle3.dll"))
sys.path.insert(0, str(ROOT / "third_party/needle"))
import needle


def main():
    fixtures = json.loads((ROOT / "data/fixtures/extraction-smoke.json").read_text(encoding="utf-8"))
    tools = json.loads((ROOT / "data/fixtures/extraction-tools.json").read_text(encoding="utf-8"))
    start = time.perf_counter()
    agent = needle.Needle(tools=tools, weights=ROOT / "models/Cactus-Compute--needle3/needle3.cact",
                          auto_date=False, stateless=True)
    load_ms = (time.perf_counter() - start) * 1000
    rows = []
    try:
        for sample in fixtures["samples"]:
            start = time.perf_counter()
            try:
                response = agent.complete(sample["text"], max_new_tokens=512)
                rows.append({"fixture": sample["id"], "language": sample["language"], "response": response,
                             "malformed_json": False,
                             "wall_ms": (time.perf_counter() - start) * 1000})
            except Exception as exc:
                rows.append({"fixture": sample["id"], "language": sample["language"], "failure": str(exc),
                             "malformed_json": isinstance(exc,json.JSONDecodeError),
                             "wall_ms": (time.perf_counter() - start) * 1000})
    finally:
        agent.close()
    print(json.dumps({"transport": "upstream binding -> UTF-8 C API -> native DLL", "load_ms": load_ms, "runs": rows}, ensure_ascii=True))


if __name__ == "__main__":
    main()
