"""Take deterministic first archive members from real FLEURS test audio, CC BY 4.0.

Streams only enough of each tar.gz for the smoke set; never extracts arbitrary paths.
This is a convenience sample, not a representative accuracy certification dataset.
"""
import argparse
import concurrent.futures
import hashlib
import io
import json
from pathlib import Path
import tarfile
from urllib.request import urlopen
import soundfile

ROOT = Path(__file__).resolve().parents[1]
REV = "70bb2e84b976b7e960aa89f1c648e09c59f894dd"
BASE = f"https://huggingface.co/datasets/google/fleurs/resolve/{REV}/data"
LANGS = {"en_us": "en", "ta_in": "ta", "te_in": "te", "hi_in": "hi", "ml_in": "ml",
         "kn_in": "kn", "bn_in": "bn", "mr_in": "mr", "es_419": "es", "cmn_hans_cn": "zh",
         "fr_fr": "fr", "de_de": "de", "pt_br": "pt", "ar_eg": "ar", "ja_jp": "ja", "ko_kr": "ko"}


def fetch_language(config, count):
    folder = ROOT / "data/external/fleurs" / config
    folder.mkdir(parents=True, exist_ok=True)
    manifest = folder / "manifest.json"
    if manifest.exists():
        cached = json.loads(manifest.read_text(encoding="utf-8"))
        if len(cached) >= count and all((ROOT / x["path"]).exists() for x in cached[:count]):
            return cached[:count]
    with urlopen(f"{BASE}/{config}/test.tsv", timeout=60) as src:
        raw_tsv = src.read()
    (folder / "test.tsv").write_bytes(raw_tsv)
    by_name = {}
    for line in raw_tsv.decode("utf-8").splitlines():
        cols = line.split("\t")
        if len(cols) >= 5:
            by_name[cols[1]] = cols
    results = []
    url = f"{BASE}/{config}/audio/test.tar.gz"
    with urlopen(url, timeout=120) as src:
        with tarfile.open(fileobj=src, mode="r|gz") as archive:
            for member in archive:
                name = Path(member.name).name
                if not member.isfile() or name not in by_name:
                    continue
                if member.size > 8_000_000:
                    raise ValueError("Unexpected oversized WAV member")
                audio = archive.extractfile(member).read()
                wav = soundfile.info(io.BytesIO(audio))
                duration = wav.duration
                if wav.samplerate != 16000 or wav.channels != 1:
                    raise ValueError("Expected original 16 kHz mono FLEURS audio")
                (folder / name).write_bytes(audio)
                cols = by_name[name]
                results.append({"id": f"fleurs-{config}-{cols[0]}-{name}", "language": LANGS[config],
                                "config": config, "dataset": "google/fleurs", "split": "test",
                                "revision": REV, "license": "CC-BY-4.0", "archive_url": url,
                                "archive_member": member.name, "path": (folder / name).relative_to(ROOT).as_posix(),
                                "sha256": hashlib.sha256(audio).hexdigest(), "duration_s": duration,
                                "reference": cols[2], "normalized_reference": cols[3],
                                "tsv_sha256": hashlib.sha256(raw_tsv).hexdigest(),
                                "sampling": "first matching WAV archive members, no quality filtering",
                                "archive_digest_verified": False})
                if len(results) >= count:
                    break
    if len(results) != count:
        raise ValueError(f"Insufficient samples in {config}: {len(results)}")
    manifest.write_text(json.dumps(results, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return results


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--per-language", type=int, default=2)
    p.add_argument("--languages", nargs="*", default=list(LANGS))
    p.add_argument("--output", default="data/fixtures/fleurs-smoke.json")
    p.add_argument("--skip-first",type=int,default=0)
    args = p.parse_args()
    results, failures = [], []
    with concurrent.futures.ThreadPoolExecutor(max_workers=3) as pool:
        futures = {pool.submit(fetch_language, lang, args.per_language+args.skip_first): lang for lang in args.languages}
        for future in concurrent.futures.as_completed(futures):
            lang = futures[future]
            try:
                rows = future.result()[args.skip_first:]
                results.extend(rows)
                print(lang, len(rows), "real clips", flush=True)
            except Exception as exc:
                failures.append({"language": lang, "error": str(exc)})
                print(lang, "FAILED", str(exc), flush=True)
    results.sort(key=lambda x: x["id"])
    (ROOT / args.output).write_text(
        json.dumps({"samples": results, "fetch_failures": failures}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    if failures:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
