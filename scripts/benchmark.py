"""Run real native ASR; serialize raw evidence and per-language scores."""
import argparse
from collections import defaultdict
from datetime import datetime, timezone
import csv
import hashlib
import json
import math
from pathlib import Path
import platform
import statistics
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from benchmarks.metrics import error_rate
from benchmarks.process import measure


def digest(path):
    with open(path, "rb") as f:
        return hashlib.file_digest(f, "sha256").hexdigest()


def percentile(values, p=.95):
    return sorted(values)[max(0, math.ceil(len(values) * p) - 1)] if values else None


def write_csv(path, rows):
    if rows:
        with path.open("w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=list(rows[0]))
            writer.writeheader()
            writer.writerows(rows)


def parse_native_asr(stem):
    # whisper-cli appends .json even if the output prefix already has a suffix.
    native = json.loads(Path(str(stem) + ".json").read_text(encoding="utf-8"))
    return (" ".join(x["text"].strip() for x in native["transcription"]).strip(),
            native["result"]["language"])


def run_asr(args):
    fixtures = json.loads((ROOT / args.fixture_manifest).read_text(encoding="utf-8"))
    samples = fixtures["samples"]
    if args.languages:
        samples = [x for x in samples if x["language"] in args.languages]
    if not samples:
        raise ValueError("No ASR fixtures; run scripts/fetch_fleurs.py first")
    locks = json.loads((ROOT / "third_party/model-lock.json").read_text())
    exe = ROOT / "build/whisper/bin/Release/whisper-cli.exe"
    exe_sha = digest(exe)
    output = ROOT / "artifacts" / ("asr-" + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ"))
    output.mkdir(parents=True)
    commit = subprocess.check_output(["git", "-C", str(ROOT / "third_party/whisper.cpp"), "rev-parse", "HEAD"], text=True).strip()
    build_commit = subprocess.run(["git", "rev-parse", "HEAD"], cwd=ROOT, capture_output=True, text=True)
    rows = []
    for model in args.models:
        weight = next(x for x in locks if x["filename"] == model)
        model_path = ROOT / weight["path"]
        if digest(model_path) != weight["sha256"]:
            raise ValueError("Weight digest mismatch; refusing inference")
        for sample in samples:
            audio = ROOT / sample["path"]
            if digest(audio) != sample["sha256"]:
                raise ValueError("Fixture digest mismatch")
            stem = output / (model.replace(".bin", "") + "-" + sample["id"])
            input_language = sample["language"] if args.language_mode == "configured" else "auto"
            command = [exe, "-m", model_path, "-f", audio, "-l", input_language, "-t", str(args.threads),
                       "-ng", "-bs", str(args.beam_size), "-bo", str(args.best_of), "-oj", "-of", stem]
            result = measure(command, timeout=args.timeout, cwd=ROOT)
            hypothesis, detected, failure = "", "", None
            try:
                if result["exit_code"] != 0 or result["timed_out"]:
                    raise RuntimeError(f"native exit={result['exit_code']}, timeout={result['timed_out']}")
                hypothesis, detected = parse_native_asr(stem)
            except Exception as exc:
                failure = str(exc)
            we, wc = error_rate(sample["reference"], hypothesis)
            ce, cc = error_rate(sample["reference"], hypothesis, chars=True)
            row = {"model": model, "model_sha256": weight["sha256"], "model_bytes": weight["bytes"],
                   "runtime_sha256": exe_sha, "runtime_bytes": exe.stat().st_size,
                   "upstream_commit": commit, "build_commit": build_commit.stdout.strip() or "UNCOMMITTED",
                   "source_dirty": bool(subprocess.check_output(["git", "status", "--porcelain"], cwd=ROOT)),
                   "device": platform.node(), "os": platform.platform(), "processor": platform.processor(),
                   "fixture": sample["id"], "language": sample["language"], "detected_language": detected,
                   "language_mode": args.language_mode,
                   "beam_size": args.beam_size, "best_of": args.best_of,
                   "dataset": sample["dataset"], "dataset_revision": sample["revision"], "split": sample["split"],
                   "fixture_sha256": sample["sha256"], "duration_s": sample["duration_s"],
                   "word_errors": we, "reference_words": wc, "character_errors": ce, "reference_characters": cc,
                   "language_correct": detected == sample["language"], "failure": failure,
                   "real_time_factor": result["wall_ms"] / (sample["duration_s"] * 1000),
                   "start_mode": "new-process; OS file-cache state uncontrolled", "threads": args.threads,
                   "measurement": {k: v for k, v in result.items() if k not in ("stdout", "stderr")}}
            rows.append(row)
            evidence = {**row, "reference": sample["reference"], "hypothesis": hypothesis,
                        "stdout": result["stdout"], "stderr": result["stderr"]}
            stem.with_name(stem.name + "-evidence.json").write_text(
                json.dumps(evidence, ensure_ascii=False, indent=2), encoding="utf-8")
            print(model, sample["language"], f"WER={we / wc if wc else 0:.3f}",
                  f"CER={ce / cc if cc else 0:.3f}", f"wall={result['wall_ms']:.0f}ms",
                  failure or "scored", flush=True)
    grouped = defaultdict(list)
    for row in rows:
        grouped[row["model"], row["language"]].append(row)
    summary = []
    for (model, lang), group in sorted(grouped.items()):
        n = len(group)
        words = sum(x["reference_words"] for x in group)
        chars = sum(x["reference_characters"] for x in group)
        failures = sum(x["failure"] is not None for x in group)
        wer = sum(x["word_errors"] for x in group) / words if words else None
        cer = sum(x["character_errors"] for x in group) / chars if chars else None
        quality = cer <= .15 if lang in ("zh", "ja", "ko") else wer <= .20 and cer <= .15
        summary.append({"model": model, "language": lang, "sample_count": n, "wer": wer, "cer": cer,
                        "language_id_accuracy": sum(x["language_correct"] for x in group) / n if args.language_mode == "auto" else None,
                        "language_mode": args.language_mode,
                        "avg_latency_ms": statistics.mean(x["measurement"]["wall_ms"] for x in group),
                        "p95_latency_ms": percentile([x["measurement"]["wall_ms"] for x in group]),
                        "mean_rtf": statistics.mean(x["real_time_factor"] for x in group),
                        "max_observed_wset_bytes": max(x["measurement"]["sum_observed_process_peak_wset_bytes"] for x in group),
                        "max_observed_commit_bytes": max(x["measurement"]["sum_observed_process_peak_commit_bytes"] for x in group),
                        "model_bytes": group[0]["model_bytes"], "runtime_bytes": group[0]["runtime_bytes"],
                        "failure_count": failures, "sample_quality_target_met": quality,
                        "certification": "EXPERIMENTAL_INSUFFICIENT_SAMPLES" if n < 100 else "REQUIRES_REVIEW"})
    write_csv(ROOT / f"reports/{args.report_name}-by-language.csv", summary)
    report = {"schema_version": 1, "run_directory": str(output), "public_fixtures_only": True,
              "dataset_fetch_failures": fixtures.get("fetch_failures", []), "runs": rows, "summary": summary}
    (ROOT / f"reports/{args.report_name}-results.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    if any(x["failure"] for x in rows):
        return 1
    return 0


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--models", nargs="+", default=["ggml-tiny-q5_1.bin", "ggml-tiny-q8_0.bin", "ggml-base-q5_1.bin"])
    parser.add_argument("--languages", nargs="*")
    parser.add_argument("--threads", type=int, default=4)
    parser.add_argument("--timeout", type=int, default=180)
    parser.add_argument("--language-mode", choices=["auto", "configured"], default="auto")
    parser.add_argument("--report-name", default="asr")
    parser.add_argument("--beam-size", type=int, default=5)
    parser.add_argument("--best-of", type=int, default=5)
    parser.add_argument("--fixture-manifest",default="data/fixtures/fleurs-smoke.json")
    raise SystemExit(run_asr(parser.parse_args()))


if __name__ == "__main__":
    main()
