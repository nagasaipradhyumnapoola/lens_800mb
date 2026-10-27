"""Pinned native Hindi comparison; Python is only a development controller.

Raw reference/hypothesis/output stay in ignored artifacts. Every run has a unique
name; historical measurements and model selection are never rewritten here.
"""
import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import platform
import subprocess
import sys
import threading
import time
from urllib.request import urlopen

import psutil
import soundfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from benchmarks.metrics import error_rate
from scripts.benchmark import digest, percentile, write_csv
from scripts.fetch_models import fetch

REPO = "parismitaglobalsolutions/indicconformer-sherpa-onnx"
REVISION = "9721eb71eea141fae0982cfcdb9dd2e3d4953c4a"
SOURCE_REPO = "ai4bharat/indicconformer_stt_hi_hybrid_ctc_rnnt_large"
SOURCE_REVISION = "deada84ce880997c56ee933aa21571d768264700"
LICENSE_REVISION = "3a4c52d0e9168746a2df0da841c6ca5fbb6f18d9"
LOCK = ROOT / "third_party/indic-hindi-lock.json"
RUNTIME = ROOT / ".tools/sherpa-runtime/sherpa-onnx-v2.0.0-win-x64-shared-MD-Release-no-tts"


def parse_native_result(stdout, stderr, exit_code, timed_out):
    """Fail closed on invalid bytes, surrogates, process failure or ambiguity."""
    if exit_code != 0 or timed_out:
        raise RuntimeError(f"native exit={exit_code}, timeout={timed_out}")
    streams = [raw.decode("utf-8", errors="strict") for raw in (stdout, stderr)]
    transcripts = []
    for output in streams:
        for line in output.splitlines():
            if not line.lstrip().startswith("{"):
                continue
            try:
                item = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(item, dict) and "text" in item:
                if not isinstance(item["text"], str):
                    raise ValueError("Native transcript is not a string")
                item["text"].encode("utf-8", errors="strict")
                transcripts.append(item["text"])
    if len(transcripts) != 1:
        raise ValueError(f"Expected exactly one native transcript, got {len(transcripts)}")
    return transcripts[0]


def measure_raw(command, timeout=180, cwd=None):
    """Same sampling/high-water method as benchmarks.process, retaining bytes.

    This local copy is necessary because the historical helper irreversibly
    decodes with errors='replace'. It is intentionally left unchanged.
    """
    env = os.environ.copy()
    env.update(NEEDLE_TELEMETRY="0", DO_NOT_TRACK="1", HF_HUB_OFFLINE="1",
               HF_HUB_DISABLE_TELEMETRY="1", OMP_NUM_THREADS="2")
    start = time.perf_counter()
    process = subprocess.Popen([str(x) for x in command], cwd=cwd, env=env,
                               stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    output = {}

    def collect():
        output["stdout_bytes"], output["stderr_bytes"] = process.communicate()

    collector = threading.Thread(target=collect, daemon=True)
    collector.start()
    known, peaks = {}, {}
    peak_rss = peak_private = samples = 0
    timed_out = False
    while process.poll() is None:
        try:
            root = psutil.Process(process.pid)
            for child in [root] + root.children(recursive=True):
                known[(child.pid, child.create_time())] = child
        except psutil.Error:
            pass
        rss = private = 0
        for identity, child in list(known.items()):
            try:
                if child.create_time() != identity[1]:
                    continue
                mem = child.memory_info()
                rss += mem.rss
                private += getattr(mem, "private", mem.vms)
                a, b = peaks.get(identity, (0, 0))
                peaks[identity] = (max(a, getattr(mem, "peak_wset", mem.rss)),
                                   max(b, getattr(mem, "peak_pagefile", mem.vms)))
            except psutil.Error:
                pass
        peak_rss, peak_private = max(peak_rss, rss), max(peak_private, private)
        samples += 1
        if time.perf_counter() - start > timeout:
            timed_out = True
            for child in reversed(list(known.values())):
                try:
                    child.kill()
                except psutil.Error:
                    pass
            process.kill()
            break
        time.sleep(.01)
    collector.join(timeout=10)
    if collector.is_alive():
        raise RuntimeError("Output collector did not finish")
    return {"command": [str(x) for x in command], "exit_code": process.returncode,
            "timed_out": timed_out, "wall_ms": (time.perf_counter() - start) * 1000,
            "sampled_tree_rss_peak_bytes": peak_rss,
            "sampled_tree_private_peak_bytes": peak_private,
            "sum_observed_process_peak_wset_bytes": sum(x[0] for x in peaks.values()),
            "sum_observed_process_peak_commit_bytes": sum(x[1] for x in peaks.values()),
            "observed_processes": len(known), "sample_count": samples,
            "sampling_interval_ms": 10, **output}


def prepare():
    if LOCK.exists():
        raise FileExistsError("Lock already exists; preserving it. Run without --prepare.")
    with urlopen(f"https://huggingface.co/api/models/{REPO}/revision/{REVISION}?blobs=true", timeout=60) as response:
        metadata = json.load(response)
    if metadata["sha"] != REVISION:
        raise ValueError("Unexpected upstream revision")
    records = [fetch(REPO, REVISION, item) for item in metadata["siblings"]
               if item["rfilename"] in ("hi/model.int8.onnx", "tokens.txt", "README.md")]
    if len(records) != 3:
        raise ValueError("Missing required upstream files")
    model_dir = ROOT / "models" / REPO.replace("/", "--")
    license_url = f"https://raw.githubusercontent.com/AI4Bharat/IndicConformerASR/{LICENSE_REVISION}/LICENSE"
    with urlopen(license_url, timeout=60) as response:
        license_bytes = response.read()
    (model_dir / "AI4Bharat-LICENSE-MIT.txt").write_bytes(license_bytes)
    lock = {"schema_version": 1, "model": "IndicConformer Hindi 120M CTC MatMul-int8",
            "repo": REPO, "revision": REVISION, "models": records,
            "source_model_repo": SOURCE_REPO, "source_model_revision": SOURCE_REVISION,
            "source_model_card": f"https://huggingface.co/{SOURCE_REPO}/blob/{SOURCE_REVISION}/README.md",
            "source_model_license": "MIT", "export_repo_license_tag": "Apache-2.0",
            "license_interpretation": "Exporter explicitly retains source weights license; preserve MIT notice and export attribution. Commercial use permitted by MIT.",
            "license_url": license_url, "license_sha256": hashlib.sha256(license_bytes).hexdigest(),
            "source_provenance_limit": "Exporter notebook loads an unpinned NeMo source alias; exact export bytes are pinned here, but source checkpoint revision used by exporter is not established.",
            "native_runtime_lock": "third_party/sherpa-reference-lock.json",
            "native_runtime_version": "2.0.0", "decoding": "greedy_search",
            "provider": "cpu", "num_threads": 2}
    with LOCK.open("x", encoding="utf-8") as target:
        json.dump(lock, target, indent=2)
        target.write("\n")
    print("Pinned Hindi model and source license; no inference performed", flush=True)


def run(mode):
    lock = json.loads(LOCK.read_text(encoding="utf-8"))
    runtime_lock_path = ROOT / "third_party/sherpa-reference-lock.json"
    runtime_lock = json.loads(runtime_lock_path.read_text(encoding="utf-8"))
    for record in lock["models"] + runtime_lock["runtime_artifacts"]:
        path = ROOT / record["path"]
        if path.stat().st_size != record["bytes"] or digest(path) != record["sha256"]:
            raise ValueError(f"Locked artifact differs: {record['path']}")
    weight = next(x for x in lock["models"] if x["filename"] == "hi/model.int8.onnx")
    tokens = next(x for x in lock["models"] if x["filename"] == "tokens.txt")
    smoke_path = ROOT / "data/fixtures/fleurs-smoke.json"
    holdout_path = ROOT / "data/fixtures/fleurs-priority-holdout.json"
    smoke = [x for x in json.loads(smoke_path.read_text(encoding="utf-8"))["samples"] if x["language"] == "hi"]
    holdout = [x for x in json.loads(holdout_path.read_text(encoding="utf-8"))["samples"] if x["language"] == "hi"]
    if len(smoke) != 2 or len(holdout) != 100:
        raise ValueError("Expected exactly two smoke and 100 Hindi holdout clips")
    if {x["id"] for x in smoke} & {x["id"] for x in holdout} or {x["sha256"] for x in smoke} & {x["sha256"] for x in holdout}:
        raise ValueError("Smoke and holdout overlap")
    samples = smoke if mode == "smoke" else holdout
    manifest_path = smoke_path if mode == "smoke" else holdout_path
    for sample in samples:
        if sample["license"] != "CC-BY-4.0" or sample["split"] != "test" or sample["revision"] != "70bb2e84b976b7e960aa89f1c648e09c59f894dd":
            raise ValueError("Unexpected fixture provenance")
        if digest(ROOT / sample["path"]) != sample["sha256"]:
            raise ValueError("Fixture hash mismatch")
    run_id = "indic-hindi-" + mode + "-" + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    folder = ROOT / "artifacts" / run_id
    folder.mkdir(parents=True, exist_ok=False)
    exe = RUNTIME / "bin/sherpa-onnx-offline.exe"
    os.environ["PATH"] = str(RUNTIME / "lib") + os.pathsep + os.environ["PATH"]
    commit = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()
    metadata = {"run_id": run_id, "mode": mode, "source_commit": commit,
                "source_dirty": bool(subprocess.check_output(["git", "status", "--porcelain"], cwd=ROOT)),
                "runner_sha256": digest(Path(__file__)), "model_lock_sha256": digest(LOCK),
                "runtime_lock_sha256": digest(runtime_lock_path), "runtime_sha256": digest(exe),
                "fixture_manifest_sha256": digest(manifest_path), "dataset": "google/fleurs",
                "dataset_revision": samples[0]["revision"], "dataset_license": "CC-BY-4.0", "split": "test",
                "python_controller": platform.python_version(), "os": platform.platform(),
                "launch_command": [sys.executable, *sys.argv],
                "memory_scope": "Native process tree only; development controller excluded. Sampled 10ms peaks plus observed Windows per-process high-water counters; short-lived descendants may be missed.",
                "start_mode": "Fresh process/model per clip; OS file cache uncontrolled; no loaded warm/idle/30-minute measurement."}
    rows = []
    for index, sample in enumerate(samples, 1):
        audio, sr = soundfile.read(ROOT / sample["path"], dtype="float32")
        if sr != 16000 or audio.ndim != 1:
            raise ValueError("Expected 16kHz mono fixture")
        wav = folder / (sample["id"] + ".pcm16.wav")
        soundfile.write(wav, audio, sr, subtype="PCM_16")
        command = [exe, "--tokens=" + str(ROOT / tokens["path"]),
                   "--nemo-ctc-model=" + str(ROOT / weight["path"]),
                   "--num-threads=2", "--provider=cpu", "--decoding-method=greedy_search", wav]
        result = measure_raw(command, cwd=RUNTIME / "bin")
        stdout, stderr = result.pop("stdout_bytes"), result.pop("stderr_bytes")
        stem = folder / sample["id"]
        stem.with_suffix(stem.suffix + ".stdout.bin").write_bytes(stdout)
        stem.with_suffix(stem.suffix + ".stderr.bin").write_bytes(stderr)
        hypothesis, failure = "", None
        try:
            hypothesis = parse_native_result(stdout, stderr, result["exit_code"], result["timed_out"])
        except (UnicodeError, ValueError, RuntimeError) as exc:
            failure = type(exc).__name__ + ": " + str(exc)
        we, wc = error_rate(sample["reference"], hypothesis)
        ce, cc = error_rate(sample["reference"], hypothesis, chars=True)
        row = {"model": lock["model"], "language": "hi", "fixture": sample["id"],
               "model_sha256": weight["sha256"], "fixture_sha256": sample["sha256"],
               "pcm16_fixture_sha256": digest(wav), "duration_s": sample["duration_s"],
               "word_errors": we, "reference_words": wc, "character_errors": ce,
               "reference_characters": cc, "failure": failure,
               "stdout_sha256": hashlib.sha256(stdout).hexdigest(),
               "stderr_sha256": hashlib.sha256(stderr).hexdigest(),
               "real_time_factor": result["wall_ms"] / (sample["duration_s"] * 1000),
               "measurement": result}
        rows.append(row)
        stem.with_suffix(stem.suffix + ".evidence.json").write_text(json.dumps(
            {**row, "reference": sample["reference"], "hypothesis": hypothesis}, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"{mode} {index}/{len(samples)} WER={we/wc:.4f} CER={ce/cc:.4f} wall_ms={result['wall_ms']:.0f} {failure or 'scored'}", flush=True)
        if failure and mode == "smoke":
            break
    summary = {"model": lock["model"], "language": "hi", "mode": mode,
               "sample_count": len(rows), "failure_count": sum(bool(x["failure"]) for x in rows),
               "wer": sum(x["word_errors"] for x in rows) / sum(x["reference_words"] for x in rows),
               "cer": sum(x["character_errors"] for x in rows) / sum(x["reference_characters"] for x in rows),
               "model_bytes": weight["bytes"], "tokens_bytes": tokens["bytes"],
               "p95_latency_ms": percentile([x["measurement"]["wall_ms"] for x in rows]),
               "p95_real_time_factor": percentile([x["real_time_factor"] for x in rows]),
               "total_audio_duration_s": sum(x["duration_s"] for x in rows),
               "aggregate_real_time_factor": sum(x["measurement"]["wall_ms"] for x in rows) / (sum(x["duration_s"] for x in rows) * 1000),
               "max_observed_wset_bytes": max(x["measurement"]["sum_observed_process_peak_wset_bytes"] for x in rows),
               "max_observed_commit_bytes": max(x["measurement"]["sum_observed_process_peak_commit_bytes"] for x in rows),
               "sampled_tree_rss_peak_bytes": max(x["measurement"]["sampled_tree_rss_peak_bytes"] for x in rows),
               "sampled_tree_private_peak_bytes": max(x["measurement"]["sampled_tree_private_peak_bytes"] for x in rows),
               "language_id": "not measured; Hindi-specific model", "certification": "EXPERIMENTAL; release gates remain"}
    report = ROOT / "reports" / (run_id + "-results.json")
    with report.open("x", encoding="utf-8") as target:
        json.dump({"metadata": metadata, "summary": summary, "runs": rows}, target, indent=2)
        target.write("\n")
    write_csv(ROOT / "reports" / (run_id + "-summary.csv"), [summary])
    print(json.dumps({"report": str(report), "summary": summary}), flush=True)
    if summary["failure_count"]:
        raise SystemExit(1)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--prepare", action="store_true", help="Download immutable public candidate and write new lock")
    parser.add_argument("--mode", choices=("smoke", "holdout"), default="smoke")
    args = parser.parse_args()
    prepare() if args.prepare else run(args.mode)


if __name__ == "__main__":
    main()
