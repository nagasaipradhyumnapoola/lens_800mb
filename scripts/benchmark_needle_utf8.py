"""Score UTF-8-native results; retain prior CLI runs as invalid non-ASCII transport evidence."""
from collections import defaultdict
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from benchmarks.metrics import field_scores
from benchmarks.process import measure
from scripts.benchmark import write_csv, percentile, digest


def main():
    result = measure([sys.executable, ROOT / "scripts/needle_utf8_worker.py"], cwd=ROOT, timeout=180)
    (ROOT / "artifacts/needle-utf8-evidence.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
    if result["exit_code"] != 0:
        print(result["stderr"])
        raise SystemExit(1)
    native = json.loads(result["stdout"])
    fixtures = {x["id"]: x for x in json.loads((ROOT / "data/fixtures/extraction-smoke.json").read_text(encoding="utf-8"))["samples"]}
    groups, scored = defaultdict(list), []
    for row in native["runs"]:
        expected = fixtures[row["fixture"]]["expected"]
        response = row.get("response", {})
        calls = response.get("function_calls", [])
        failure = row.get("failure")
        if response.get("success") is False:
            failure = response.get("error") or response.get("reason") or "native reported failure"
        actual = {}
        if calls:
            if len(calls) != 1 or calls[0].get("name") != "save_event":
                failure = "incorrect action selection or extra action"
            actual = calls[0].get("arguments", {})
            if isinstance(actual, str):
                actual = json.loads(actual)
        record = {**row, "failure": failure, "actual": actual, "expected": expected,
                  "predicted_action": bool(calls), "expected_action": bool(expected),
                  **field_scores(expected, actual)}
        scored.append(record)
        groups[row["language"]].append(record)
        print(row["fixture"], f"F1={record['f1']:.3f}", failure or "scored", flush=True)
    summary = []
    for lang, group in sorted(groups.items()):
        tp, fp, fn = [sum(x[k] for x in group) for k in ("tp", "fp", "fn")]
        pred = sum(x["predicted_action"] for x in group)
        correct = sum(x["predicted_action"] and x["expected_action"] and not x["failure"] for x in group)
        summary.append({"variant": "needle3-full-utf8-native-api", "language": lang, "sample_count": len(group),
                        "tp": tp, "fp": fp, "fn": fn, "precision": tp/(tp+fp) if tp+fp else 0,
                        "recall": tp/(tp+fn) if tp+fn else 0, "field_f1": 2*tp/(2*tp+fp+fn) if 2*tp+fp+fn else None,
                        "safe_routing_precision": correct/pred if pred else None,
                        "malformed_json_rate": sum(x.get("malformed_json",False) for x in group)/len(group), "failure_count": sum(bool(x["failure"]) for x in group),
                        "avg_latency_ms": sum(x["wall_ms"] for x in group)/len(group),
                        "p95_latency_ms": percentile([x["wall_ms"] for x in group]),
                        "load_ms": native["load_ms"],
                        "max_observed_tree_wset_bytes": result["sum_observed_process_peak_wset_bytes"],
                        "max_observed_tree_commit_bytes": result["sum_observed_process_peak_commit_bytes"],
                        "measurement_scope": "Python binding worker tree; native-only release measurement pending",
                        "certification": "EXPERIMENTAL_SYNTHETIC_SMOKE_ONLY"})
    write_csv(ROOT / "reports/extraction-upstream-binding.csv", summary)
    (ROOT / "reports/extraction-utf8-results.json").write_text(json.dumps({
        "native": native, "runs": scored, "summary": summary,
        "measurement": {k:v for k,v in result.items() if k not in ("stdout", "stderr")},
        "dll_sha256": digest(ROOT / "models/Cactus-Compute--needle3/windows-x86_64/libneedle3.dll")}, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
