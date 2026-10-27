# Needle 3 integration review — 2026-10-26

The existing evidence does not justify blaming every failure on multilingual model capacity. The UTF-8 native path is real, but Lens currently measures raw tool proposals without applying the native negation/grounding flags. The pinned Python extraction API applies an additional strict validation step. That difference is concrete and matters before a proposal becomes a derived memory or an executable request. It does not explain away incorrect Chinese/Hindi entity extraction, and applying a refusal policy does not establish an extraction-quality pass.

This review initially inspected existing public/synthetic artifacts only. It did not rerun quality benchmarks, tune on holdouts, download weights, install packages, inspect personal content or execute actions. The subsequent explicitly assigned policy regression work is recorded at the end. The full distributed product is approved scope; the immediate priority for this task is native model integration and proposal correctness, followed by the approved dependency order.

## Exact identities

| Component | Identity verified from local files |
|---|---|
| Upstream source | `cactus-compute/needle`, `b4fc11b04f1852888d375c8c6dfbaca44572d014`; local HEAD matches `third_party/upstream-lock.json` |
| Model repository | `Cactus-Compute/needle3`, revision `d6c7d6a2e9655505e0f8e23339356dd1705900eb` |
| `needle3.cact` | 35,335,380 bytes; SHA256 `c9d915eca282ed42d1a09b143b592adb4cc6744ffe2d294adf5cfc5548170c38` |
| Native DLL | 1,533,952 bytes; SHA256 `1263c6003dd88b9fcb1904a55985be66858639849309280b42f7764ee5d874d0`; member of the locked 3.3.3 Windows wheel |
| Native C header | SHA256 `a27dac4b3239eead91d124b7f7dbce5495c13019903fd817b68c16d39b055a99`; six-argument text/speech `needle_complete` ABI |
| Fixture schema | SHA256 `9b058ffd4f142d39a05a76995a00ce6d5e1ff97515b54e5436068d12ce2c5e80` |
| Synthetic fixture set | SHA256 `a152326b5060b08897bbae64b92429f1bd2531804dd9023659b451613f6cfb73` |
| Existing native results | SHA256 `5c12128be838faaa41abafaac64c9814829091252a10eb8455fb7bf4350ca914` |
| Existing binding results | SHA256 `d4bc8dfce06435ceeae92618b8df4f402487c5b362a9ead5fa05f4dcbb29c25f` |

Hashes were recomputed read-only. The source package reports `__version__ = 3.2.1`; the DLL comes from a separately locked 3.3.3 wheel. Therefore the older local binding and native binary are not one identical source release. This is a provenance limitation, not evidence that their C ABI is wrong.

## Integration findings

| Finding | Evidence and consequence |
|---|---|
| **Confirmed missing strict proposal gate in the original adapter** | Original `engine/needle_main.cpp:37`–43 initializes the runtime, parses its envelope and forwards it. `artifacts/native-needle-negated-en.json` contains a nonempty `save_event` call with `validation.negation=true`, confidence `0.1801`. The binding artifact also contains a negated call with `validation.negation=true`. Pinned `third_party/needle/needle/__init__.py:610`–655 rejects this in `extract(strict=True)`. The native runtime itself did not remove every flagged call. This is a missing Lens acceptance boundary; no action execution is present. |
| **The score called safe routing is narrower than safe execution** | `scripts/benchmark_native_needle.py:44`–49 counts a predicted call as correct when the sample expects any call and `failure` is empty. It does not inspect confidence, native validation or argument correctness. Thus the Hindi row can show routing precision `1.0` while its fields are incorrect. Field F1 separately exposes those errors. Keep this metric as raw tool-selection evidence; do not interpret it as authorization, grounding or correct-argument evidence. |
| **Raw call scoring differs from official extraction semantics** | Both Lens scorers read only `function_calls`; pinned `extract()` reads `function_calls` or `suppressed_calls`, then performs strict grounding validation. The native Chinese artifact has no active call at confidence `0.0996` and a suppressed incorrect call. That is not malformed JSON. A diagnostic extraction-quality view may inspect suppressed candidates separately, but a production acceptance gate must never promote them automatically. Preserve current raw scores; do not rescore or tune an existing holdout to make it pass. |
| **Schema constraints are mostly prose** | `data/fixtures/extraction-tools.json:10`–15 declares four required strings. ISO date/time formatting and verbatim provenance live in descriptions, not `format`, `pattern` or an independent validator. The injection artifact includes a suppressed `date="today"` and an invented time: parseable strings satisfy the declared types. Requiring all four slots also supplies no representation for a genuine event with a missing person/place. This is an integration/schema limitation for missing-information behavior, not the explanation for fully populated English/Spanish/Chinese/Hindi fixtures. |
| **Flat versus OpenAI-wrapped schema is a real binding-validation mismatch, not a proven native parsing failure** | Official pinned `llms.txt:54`–69 demonstrates flat `{name,description,parameters}` tools. Lens passes OpenAI `{type,function:{...}}` entries directly. The native artifacts demonstrate that this runtime accepts the wrapper. However pinned `_annotate_ungrounded()` at `needle/__init__.py:593` indexes schemas by top-level `name`, so its additional temporal schema traversal cannot find this wrapped `save_event`. Even a flat schema would need an actual date `format` for its year checks. Do not attribute all failed calls to the wrapper without a controlled fresh-data comparison. |
| **Some additional-language references conflict with the verbatim-copy instruction** | The Tamil sample expects `சென்னை` from `சென்னையில்` and `அருண்` from an inflected token. Telugu and Bengali cases similarly expect normalized base entities. The schema asks for source spelling. This is a labeling-contract ambiguity that should be resolved in a versioned future dataset. It does not account for the Chinese/Hindi core-priority errors, where the expected person/place strings are present. |

## Correct usage and remaining constraints

The C++ function signatures match the pinned C header: `needle_load(bytes,n)`, `needle_init(system,tools,index)`, `needle_complete(text,nullptr,0,max_tokens,out,capacity)`. UTF-8 JSON enters on stdin and strings go directly to the UTF-8 C API. The earlier ANSI CLI artifacts are intentionally classified invalid non-ASCII transport evidence and should remain preserved.

The Python worker uses `stateless=True`, resets between independent samples, and sets `auto_date=False`. The native executable processes one query and then exits, so history cannot contaminate the next sample. Neither path uses `run()` or invokes a function. Local DLL/weight paths and telemetry opt-outs are present. These choices are appropriate for independent native proof samples.

An empty system string is permitted. Pinned upstream guidance treats `system` as environment facts, not instruction prompting; it licenses relative dates only with a `date:` fact. All current extraction fixtures carry explicit `2026-10-27` and `15:00`, so missing current-date/locale facts do not explain their failure. Later “tomorrow” tests must use the observation's recorded time/zone as evidence, not silently use the machine's current date. Do not prepend a generic chat-assistant prompt to this specialized runtime.

The adapter limits input bytes, but a 131,072-byte text limit is not a token/context limit. It reserves 512 generation tokens and discards `needle_init`'s returned static-prefix token count. The header exposes `needle_last_error`; original failures collapse to `needle_request_failed`. The locked CLI supports `--fail-input-overflow`, but the public C header does not expose a corresponding setting. Long-observation handling therefore needs measured, source-linked chunking or a verified overflow-refusal mechanism. The short fixtures provide no evidence of overflow, so this is not a diagnosis of their failure.

The official text-model documentation reviewed here provides no enumerated, measured Needle extraction guarantee for English, Mandarin, Spanish and Hindi. The seven-language list in the README refers to **Whistle speech recognition**, not Needle text extraction. The current smoke set has one positive example per priority language and only English negative examples; it cannot pass the repository's 100 unseen examples per tested language, field micro-F1 and routing gates.

The source README advertises 8–29 MB, while its pinned `llms.txt` describes a 35 MB full archive; the measured locked file is 35,335,380 bytes. The model card identifies a 20-layer full model and deployable depths from 2 to 20, with a 121M full model; the asset identifies 29–121M variants. No measured per-depth file-size table exists in the reviewed local artifacts. Do not invent 8 MB/29 MB tested variants from the marketing range, or claim the full archive is 29 MB. The native DLL also exceeds the source guide's sub-1 MB engine description. Exact installed bytes govern Lens reporting.

## Next decision and conditional fallback

The follow-up below adds the deterministic proposal gate while retaining raw outputs. Next resolve the schema/label contract using newly authored development fixtures; then evaluate a fresh locked unseen four-language extraction set. A policy rejection improves safety but may lower recall and cannot turn current F1/sample-count evidence into a pass. Native validation can reject flags and malformed structure; it cannot prove an unflagged but incorrect person/place is correct.

If a correctly integrated Needle still cannot meet the four-language gates, the smallest **candidate justified by the primary sources in this review** is Qwen3-0.6B with a pinned native llama.cpp adapter, bounded non-thinking generation and a JSON grammar. This is a candidate to benchmark, not a proven replacement, universal smallest model or RAM/accuracy promise. Its official sources list English, Chinese, Spanish and Hindi; they do not establish Lens event-extraction accuracy. Its weights, KV/context and complete process memory must be measured serially with the other models. Keep originals and return no accepted derived fact when no candidate passes; do not translate away source evidence, add cloud inference or train on personal content.

## Primary references and access limitations

- [Pinned official Needle usage reference](https://raw.githubusercontent.com/cactus-compute/needle/b4fc11b04f1852888d375c8c6dfbaca44572d014/llms.txt): response/validation semantics, optional system facts and model size.
- [Official Needle model card](https://huggingface.co/Cactus-Compute/needle3): model architecture, layers and context-budget caveats. The exact pinned HF README URL could not be retrieved by the web tool; current card statements are not silently substituted for locked artifact identities.
- [Official Needle source](https://github.com/cactus-compute/needle): source/engine packaging and guides; locked local code supplied the detailed binding audit.
- [Qwen3-0.6B official card](https://huggingface.co/Qwen/Qwen3-0.6B), [Qwen language table](https://qwenlm.github.io/blog/qwen3/): conditional native fallback rationale.
- [llama.cpp grammar guide](https://raw.githubusercontent.com/ggml-org/llama.cpp/master/grammars/README.md): maintained native grammar mechanism, without a correctness guarantee.

The official Cactus blog pages for tool design, confidence, extraction, Python API and porting returned access errors. The review used the equivalent pinned official `llms.txt` and local source instead. Initial searches for nonexistent `config/`, `docs/model-lock.json` and `third_party/needle/needle.py` failed; the actual locks and module locations above were then found. No inference was performed during this read-only review.

## Policy regression follow-up

The explicitly assigned follow-up changed only `engine/needle_main.cpp`, the new `engine/tool_policy.hpp` and the new `tests/test_native_needle_policy.py`, plus this report and the requested new verification logs. It did not change CMake or the existing quality benchmark reports.

The native adapter now preserves the original envelope under `proposal`, exposes `accepted_calls` and diagnostic `blocked_calls`, and keeps compatibility `function_calls` equal to accepted calls. No function executes. The only registered name is `save_event`. Schemas are checked before the native library loads. The policy accepts both the existing OpenAI wrapper and flat official schema form, but rejects unregistered tools and unsupported schema features.

The documented strict schema subset supports one explicit type per node: object with properties/required, arrays with items, strings, integers, numbers, booleans and null. It recursively checks required fields and rejects extra properties even when `additionalProperties` was omitted. Explicit `additionalProperties=true`, formats, patterns, references, unions, enum/default constraints and unknown keywords are rejected rather than silently ignored. Limits bound nesting, property/array/call counts and strings. This is not a complete JSON Schema validator; no existing maintained native schema validator was configured in the inspected engine, so a narrow subset avoids an unreviewed new dependency.

Native negation, uncertainty/confirmation flags, ungrounded fields, malformed/unknown validation flags, inconsistent error envelopes and unknown tool calls cannot enter accepted calls. Suppressed calls remain blocked. Missing, invalid or sub-0.1 confidence is blocked; 0.1 mirrors the documented upstream refusal floor and is **not** a calibrated Lens accuracy/authorization threshold. Unflagged semantic mistakes can still pass this structural gate. Permission checks and execution verification remain separate required product boundaries.

Tests were written and run red before implementing the policy. The real negated-English fixture exposed the old behavior. A temporary test-only DLL returns controlled invalid model envelopes for required-field/type/schema/unknown-function cases that cannot be reliably induced in a real model; the real executable and production validator are exercised unchanged. There is no production test bypass. Initial test setup had a Windows compiler-command quoting error; the red log retains that error and the corrected assertion runs. After rebuilding only the assigned target, the final targeted run passed **21 tests** (20 new policy tests and the original native Needle test), and **4 input-safety tests** passed. The two real model samples are synthetic policy regressions, not a multilingual quality benchmark. Full cross-feature suite verification is handed to the coordinating task after the other active workers' binaries settle.

Exact final commands:

```powershell
$vswhere='C:\Program Files (x86)\Microsoft Visual Studio\Installer\vswhere.exe'
$needleCmake=& $vswhere -latest -products '*' -find '**\cmake.exe' | Select-Object -First 1
& $needleCmake --build build/engine --config Release --target lens-needle
.venv\Scripts\python.exe -m unittest discover -s tests -p 'test_native_needle*.py' -v
.venv\Scripts\python.exe tests/test_input_safety.py
```

All three final commands exited 0. Red commands used the existing `python` interpreter to run `tests/test_native_needle_policy.py`, then the two additional focused schema/envelope tests, then the contradictory-error regression before its fix. Their complete assertion output is retained in `reports/verification-2026-10-26/needle-policy-red.log.txt`; final output is in `needle-policy-green.log.txt`. No quality-score report was regenerated. A future benchmark rerun must version the acceptance-policy change and distinguish `proposal.function_calls` from accepted calls; blindly rerunning the old scorer would change what it measures.

```powershell
python tests/test_native_needle_policy.py
python tests/test_native_needle_policy.py NativeNeedlePolicy.test_supported_scalar_and_nested_types_are_checked NativeNeedlePolicy.test_failed_and_malformed_native_envelopes_are_blocked
python tests/test_native_needle_policy.py NativeNeedlePolicy.test_native_error_fields_cannot_be_overridden_by_success_true
```

| Follow-up artifact | SHA256 |
|---|---|
| `build/engine/Release/lens-needle.exe` (182,784 bytes) | `fe65d066834b8922cd614ac2b8de52929f9a7656f56a7d6620f48ace7b758854` |
| `engine/needle_main.cpp` | `72ab1d481fa20e718c8c6e5a8d77926b5099ada08dc295bb366e3b31b4d0f6a1` |
| `engine/tool_policy.hpp` | `8cc41b40e8519bc7cb9ebd978d5b00142ef10f41e51b362abe944aa27d302136` |
| `tests/test_native_needle_policy.py` | `5a4c593da75a7e048d5193c90f43f3d249dd7f4bf17fd2cdb43f19922540818a` |
| Red log | `577ba03f1b44755ca1939753fd6503e1c0cc45deddc2762e987c8218cada0b74` |
| Green log | `021de9f9fba3b76dadb143bb05119cac6c812ecb0744c855956f9e5ff62e9553` |

The two pre-existing quality-result hashes in the initial identity table remain unchanged after the follow-up.
