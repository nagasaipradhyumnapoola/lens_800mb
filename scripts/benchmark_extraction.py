"""Evaluate official Needle native runners; function calls are never executed."""
from collections import defaultdict
from datetime import datetime, timezone
import json
from pathlib import Path
import statistics
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from benchmarks.metrics import field_scores
from benchmarks.process import measure
from scripts.benchmark import digest, percentile, write_csv


def main():
    data = json.loads((ROOT / "data/fixtures/extraction-smoke.json").read_text(encoding="utf-8"))
    tools = ROOT / "data/fixtures/extraction-tools.json"
    locks = json.loads((ROOT / "third_party/model-lock.json").read_text())
    output = ROOT / "artifacts" / ("extraction-" + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ"))
    output.mkdir(parents=True)
    runs = []
    for repo, depths in [("Cactus-Compute/needle3", [2, 8, 20]), ("Cactus-Compute/needle2", [None])]:
        weight = next(x for x in locks if x["repo"] == repo and x["filename"].endswith(".cact"))
        binary = next(x for x in locks if x["repo"] == repo and x["filename"].endswith("needle.exe"))
        exe, model = ROOT / binary["path"], ROOT / weight["path"]
        if digest(exe) != binary["sha256"] or digest(model) != weight["sha256"]:
            raise ValueError("Needle artifact digest mismatch")
        for depth in depths:
            variant = f"needle3-depth{depth}" if depth else "needle2-embedded"
            for sample in data["samples"]:
                command = [exe, "--tools", tools, "--prompt", sample["text"], "--max", "256"]
                if depth:
                    command += ["--model", model, "--depth", str(depth), "--threads", "2", "--fail-input-overflow"]
                result = measure(command, cwd=ROOT, timeout=60)
                actual, failure, malformed, predicted = {}, None, False, False
                try:
                    if result["exit_code"] != 0:
                        raise RuntimeError(f"native exit={result['exit_code']}")
                    parsed = json.loads(result["stdout"])
                    if parsed.get("success") is False:
                        failure = parsed.get("error") or "native reported failure"
                    calls = parsed.get("function_calls", [])
                    predicted = bool(calls)
                    if calls:
                        first = calls[0]
                        actual = first.get("arguments", first.get("parameters", {}))
                        if isinstance(actual, str):
                            actual = json.loads(actual)
                        if not isinstance(actual, dict):
                            raise ValueError("Arguments were not an object")
                        if first.get("name") != "save_event" or len(calls) != 1:
                            failure = "incorrect action selection or extra action"
                except json.JSONDecodeError as exc:
                    malformed, failure = True, str(exc)
                except Exception as exc:
                    failure = str(exc)
                score = field_scores(sample["expected"], actual)
                row = {"variant": variant, "language": sample["language"], "fixture": sample["id"],
                       "fixture_kind": "synthetic benchmark", "expected_action": bool(sample["expected"]),
                       "predicted_action": predicted, "malformed": malformed, "failure": failure, **score,
                       "weight_sha256": weight["sha256"] if depth else None,
                       "embedded_weight_identity_verified": False if not depth else None,
                       "binary_sha256": binary["sha256"],
                       "model_bytes": weight["bytes"] if depth else 0,
                       "runtime_bytes": binary["bytes"],
                       "measurement": {k: v for k, v in result.items() if k not in ("stdout", "stderr")}}
                runs.append(row)
                (output / (variant + "-" + sample["id"] + ".json")).write_text(
                    json.dumps({**row, "text": sample["text"], "expected": sample["expected"], "actual": actual,
                                "stdout": result["stdout"], "stderr": result["stderr"]}, ensure_ascii=False, indent=2), encoding="utf-8")
                print(variant, sample["id"], f"F1={score['f1']:.3f}", failure or "scored", flush=True)
    groups = defaultdict(list)
    for row in runs:
        groups[row["variant"], row["language"]].append(row)
    summary = []
    for (variant, lang), group in sorted(groups.items()):
        tp, fp, fn = [sum(x[k] for x in group) for k in ("tp", "fp", "fn")]
        predicted = sum(x["predicted_action"] for x in group)
        correct_action = sum(x["predicted_action"] and x["expected_action"] and not x["failure"] for x in group)
        summary.append({"variant": variant, "language": lang, "sample_count": len(group),
                        "tp": tp, "fp": fp, "fn": fn, "precision": tp / (tp + fp) if tp + fp else 0,
                        "recall": tp / (tp + fn) if tp + fn else 0,
                        "field_f1": 2 * tp / (2 * tp + fp + fn) if 2 * tp + fp + fn else None,
                        "safe_routing_precision": correct_action / predicted if predicted else None,
                        "malformed_json_rate": sum(x["malformed"] for x in group) / len(group),
                        "failure_count": sum(x["failure"] is not None for x in group),
                        "avg_latency_ms": statistics.mean(x["measurement"]["wall_ms"] for x in group),
                        "p95_latency_ms": percentile([x["measurement"]["wall_ms"] for x in group]),
                        "max_observed_wset_bytes": max(x["measurement"]["sum_observed_process_peak_wset_bytes"] for x in group),
                        "max_observed_commit_bytes": max(x["measurement"]["sum_observed_process_peak_commit_bytes"] for x in group),
                        "model_bytes": group[0]["model_bytes"], "runtime_bytes": group[0]["runtime_bytes"],
                        "certification": "EXPERIMENTAL_SYNTHETIC_SMOKE_ONLY"})
    write_csv(ROOT / "reports/extraction-ansi-cli-invalid.csv", summary)
    (ROOT / "reports/extraction-results.json").write_text(
        json.dumps({"provenance": data["provenance"], "runs": runs, "summary": summary}, indent=2), encoding="utf-8")
    if any(x["failure"] for x in runs):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
