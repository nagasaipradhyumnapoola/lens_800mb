#!/usr/bin/env bash
# Full Lens-vs-world comparison (answerability judges, then retrieval embeddings), one heavy job at a time.
# Each judge's scores also feed the Lens harness metric (correct answers at 5% false answers, grouped CV).
# Usage (from D:/Lens, Git Bash): bash lens_model/eval/run_comparison.sh [judges...]
set -u
cd "$(dirname "$0")/../.."
export PYTHONIOENCODING=utf-8
TRAIN=.venv-train/Scripts/python.exe; RUN=.venv/Scripts/python.exe
HARNESS=artifacts/verifier-20261026T165918Z
JUDGES=${*:-"lens-v1-int8 lens-v0-int8 mmarco-int8 qa-xlmr-int8 bge-reranker-v2-m3 qwen3-reranker-0.6b qwen2.5-1.5b-instruct qwen3-1.7b qwen3-reranker-4b qwen3-4b"}
for j in $JUDGES; do
  case $j in *-int8) PY=$RUN;; *) PY=$TRAIN;; esac
  if [ -f "reports/lens-model/benchmark/$j.json" ] && grep -q belebele_global "reports/lens-model/benchmark/$j.json"; then echo "== $j already scored"; else
    echo "== $j $(date +%H:%M)"; $PY -B lens_model/eval/compare_answerability.py --judge "$j" || { echo "JUDGE FAILED $j"; continue; }
  fi
  $RUN -B scripts/experiment_answer_verifier.py --verifier scores --scores "artifacts/lens-model/bench/scores/$j.jsonl" --reuse "$HARNESS" \
    > "reports/lens-model/benchmark/$j.harness.log" 2>&1 || echo "HARNESS FAILED $j"
done
$TRAIN -B lens_model/eval/compare_answerability.py --summary
for m in e5-small granite-278m e5-base bge-m3 arctic-l-v2 e5-large-instruct qwen3-embedding-0.6b; do
  [ -f "reports/lens-model/benchmark/retrieval-$m.json" ] && grep -q belebele_ret "reports/lens-model/benchmark/retrieval-$m.json" && { echo "== $m already scored"; continue; }
  echo "== retrieval $m $(date +%H:%M)"; $TRAIN -B lens_model/eval/compare_retrieval.py --model "$m" || echo "RETRIEVAL FAILED $m"
done
$TRAIN -B lens_model/eval/compare_retrieval.py --summary
echo "ALL DONE $(date +%H:%M)"
