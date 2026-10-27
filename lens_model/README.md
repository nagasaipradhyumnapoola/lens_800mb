# lens_model — Lens-Core model development workstream

Design, feasibility and proof plan: docs/LENS_MODEL.md. Evidence: docs/VERIFICATION.md ("Lens-Core").
This directory trains Lens's own model weights. It never touches the working engine; a trained model reaches the
engine only after it passes its benchmarks (docs/acceptance-gates.md).

Rules
- Licensed public data, permitted teacher outputs and authored synthetic data only. Personal memories never become
  training data; they stay in the encrypted store.
- Every dataset is pinned in manifest/datasets.json (repository, revision, licence, sha256). Held-out splits and the
  sealed retrieval holdouts (data/fixtures/retrieval-nl/holdout.json, acceptance.json) are never trained or tuned on.
- Training runs in `.venv-train` (requirements-train.lock.txt; PyTorch CPU build until the RTX 5060 is enabled).
  Runtime/quantization checks run in `.venv`. Outputs go to artifacts/lens-model/ (not committed); reports that back a
  claim are copied into reports/lens-model/.
- A checkpoint is not a product: deployment needs INT8 parity, CPU latency, full-process RAM and per-language quality
  on the target hardware tiers.

Layout
- data/build_answerability.py — (question, evidence window, supported?) pairs from SQuAD 2.0, TyDi GoldP, IndicQA, XQuAD.
- train/train_answerability.py — answerability head (stage T2), CPU-capable.
- export/export_onnx.py — FP32 ONNX export and INT8 quantization with per-node sensitivity and parity report.
- manifest/datasets.json — data and initialisation provenance.

Reproduce the answerability pilot
```
.venv-train\Scripts\python.exe lens_model/data/build_answerability.py
.venv-train\Scripts\python.exe lens_model/train/train_answerability.py --epochs 1 --name answerability-v0
.venv-train\Scripts\python.exe lens_model/export/export_onnx.py --checkpoint artifacts/lens-model/checkpoints/answerability-v0
.venv\Scripts\python.exe lens_model/export/export_onnx.py --quantize artifacts/lens-model/onnx/answerability-v0
.venv\Scripts\python.exe scripts/experiment_answer_verifier.py --verifier lens --lens-model artifacts/lens-model/onnx/answerability-v0/model_int8.onnx --reuse <verifier artifacts dir> --merge-qa <qa rows.json>
```
