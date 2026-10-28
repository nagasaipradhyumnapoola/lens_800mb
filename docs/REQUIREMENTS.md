# Lens V1 — requirements register

Formal register of the detailed product requirements for Lens V1. Each entry is one atomic, testable statement
with a stable identifier. "Shall" is mandatory, "Should" is recommended, "May" is optional.

Precedence: docs/LENS_V1_SPEC.md and the dated founder decisions recorded there take precedence over this
register where they conflict, in particular the 800,000,000-byte RAM ceiling (§15) and the language priority
(§1a). Entries affected by a later decision are marked "superseded" and kept for traceability.

Status of every entry is unverified until evidence in docs/VERIFICATION.md demonstrates it; this register
is not a completion measure. Machine-readable copy: docs/requirements.json.

Entries: 949 (Shall 712, Should 206, May 31).

## 0. Project identity and platforms

| ID | Level | Requirement |
|---|---|---|
| LM-004 | Shall | Do not interpret Lens as just the small model currently being benchmarked. |
| LM-005 | Shall | Do not interpret Lens as just OCR + Whisper + SQLite. |
| LM-006 | Shall | One distributed personal-memory system |
| LM-007 | Shall | Local-first personal-memory storage |
| LM-008 | Shall | Device-intelligence system |
| LM-014 | Shall | Target platform: Windows EXE |
| LM-015 | Shall | Target platform: Android APK |
| LM-016 | Shall | Target platform: Wear OS APK |
| LM-017 | May | Future platform: macOS |
| LM-018 | May | Future platform: iOS |
| LM-019 | May | Future platform: Tablets |
| LM-020 | May | Future platform: Smart glasses |
| LM-021 | May | Future platform: Earbuds |
| LM-022 | May | Future platform: Additional wearable and embedded devices |
| LM-028 | Shall | Inspect actual development hardware |
| LM-029 | Shall | Do not assume CUDA availability |
| LM-031 | Shall | Use the Wear OS emulator for development |
| LM-032 | Shall | Identify tests requiring physical wearable hardware |
| LM-1157 | Shall | Model weights are not personal memory. |
| LM-1158 | Shall | Encrypted memory |
| LM-1159 | Shall | Local-first memory |
| LM-1160 | Shall | Capture requires authorization. |
| LM-1161 | Shall | Source records must remain retrievable. |
| LM-1162 | Shall | Models must be replaceable. |
| LM-1163 | Shall | Cross-device commands require authenticated executors. |
| LM-1164 | Shall | The watch is a first-class target. |
| LM-1165 | Shall | The product is global. |
| LM-1166 | Shall | Retain 500 MB as an optimization goal |
| LM-1167 | Shall | Do not remove necessary features to reach 500 MB |
| LM-1168 | Should | Prefer reused open-source implementations |
| LM-1169 | Should | Verify reused implementations |
| LM-1173 | Shall | Lens shall be a working product, not a mockup. |
| LM-1175 | Shall | Open the existing Lens repository |
| LM-1176 | Shall | Restore actual implementation state |
| LM-1177 | Shall | Continue existing development |

## 1. Product definition

| ID | Level | Requirement |
|---|---|---|
| LM-060 | Should | Lens should retrieve the actual supporting historical information when it was captured. |
| LM-061 | Should | Relate events |
| LM-062 | Should | Relate people |
| LM-063 | Should | Relate projects |
| LM-064 | Should | Relate preferences |
| LM-065 | Should | Relate devices |
| LM-067 | Shall | Lens is not another large language model. |
| LM-068 | Shall | Lens is not an alternative to ChatGPT. |
| LM-069 | Shall | Lens is not a traditional voice assistant. |
| LM-070 | Shall | Lens is not merely a screenshot recorder. |
| LM-071 | Shall | Lens is not merely a searchable audio transcription tool. |
| LM-072 | Shall | Lens is not just a personal knowledge database. |
| LM-073 | Shall | Lens is not a project that trains a new foundation model from scratch. |
| LM-074 | Shall | Lens is not a clone of Screenpipe, OpenRecall, Pensieve, Hermes, or another AI product. |
| LM-075 | Shall | Lens is not three separate consumer products. |
| LM-076 | Shall | Lens is ONE distributed system with device-specific clients. |
| LM-092 | Shall | Do not start building the entire Recursion application inside the Lens repository. |
| LM-093 | Shall | Build a reusable Lens component |
| LM-094 | Shall | Expose well-defined boundaries for later Recursion integration |

## 2. Separation of models and personal memory

| ID | Level | Requirement |
|---|---|---|
| LM-095 | Shall | The AI models do not remember the user's life. |
| LM-096 | Shall | The encrypted memory system remembers the user's life. |
| LM-097 | Shall | Models observe information |
| LM-098 | Shall | Models extract information |
| LM-099 | Shall | Models classify information |
| LM-100 | Shall | Models route requests |
| LM-101 | Shall | Models assist information retrieval |
| LM-102 | Shall | Never confuse model weights with personal memory. |
| LM-108 | Shall | Preserve transcript memory field: The original transcript. |
| LM-109 | Shall | Preserve transcript memory field: Its timestamp. |
| LM-110 | Shall | Preserve transcript memory field: Its source device. |
| LM-111 | Shall | Preserve transcript memory field: Its capture metadata. |
| LM-112 | Shall | Preserve transcript memory field: Its language. |
| LM-113 | Shall | Preserve transcript memory field: The extracted meeting. |
| LM-114 | Shall | Preserve transcript memory field: The relationship between the meeting and transcript. |
| LM-119 | Shall | Device-observation pipeline stage |
| LM-120 | Shall | Perception using OCR, speech and device events |
| LM-121 | Shall | Structured extraction using Needle or specialized models |
| LM-122 | Shall | Encrypted local memory pipeline stage |
| LM-123 | Shall | Indexing and temporal organization pipeline stage |
| LM-124 | Shall | Source-grounded retrieval pipeline stage |
| LM-125 | Shall | Contextual-understanding pipeline stage |
| LM-126 | Shall | Authorized action or response pipeline stage |
| LM-127 | Shall | Verification and memory-update pipeline stage |
| LM-128 | Shall | This is one integrated engine. |
| LM-129 | Shall | Do not build unnecessary microservices for every box. |

## 3. Open-source foundations

| ID | Level | Requirement |
|---|---|---|
| LM-130 | Shall | Lens shall reuse existing open-source technology. |
| LM-132 | Shall | Use maintained upstream components and adapt them. |
| LM-133 | Should | Study Screenpipe: Screen observation. |
| LM-134 | Should | Study Screenpipe: Audio/screen capture pipelines. |
| LM-135 | Should | Study Screenpipe: Timestamped event organization. |
| LM-136 | Should | Study Screenpipe: Change detection. |
| LM-137 | Should | Study Screenpipe: Desktop integration. |
| LM-138 | Should | Study Screenpipe: Searchable activity history. |
| LM-139 | Shall | Check its current commercial licensing before reusing code. |
| LM-140 | Shall | Do not assume it is freely reusable in the commercial product. |
| LM-141 | Shall | Do not copy its UI. |
| LM-142 | Should | Study Pensieve: Local-first observation. |
| LM-143 | Should | Study Pensieve: Screenshot indexing. |
| LM-144 | Should | Study Pensieve: OCR processing. |
| LM-145 | Should | Study Pensieve: Searchable historical activity. |
| LM-146 | Should | Study Pensieve: Local memory organization. |
| LM-147 | Should | Study OpenRecall: Historical screen recall. |
| LM-148 | Should | Study OpenRecall: Search experiences. |
| LM-149 | Should | Study OpenRecall: Timestamped personal history. |
| LM-150 | Shall | Review AGPL obligations before considering code reuse. |
| LM-151 | Shall | Study ideas without violating licensing requirements. |
| LM-152 | Should | Study ActivityWatch: Window/activity watchers. |
| LM-153 | Should | Study ActivityWatch: Application activity events. |
| LM-154 | Should | Study ActivityWatch: AFK detection. |
| LM-155 | Should | Study ActivityWatch: Local-first event collection. |
| LM-156 | Should | Study ActivityWatch: Privacy-conscious activity tracking. |
| LM-157 | Shall | Study and integrate Needle capability: Tiny decision models. |
| LM-158 | Shall | Study and integrate Needle capability: Tool calling. |
| LM-159 | Shall | Study and integrate Needle capability: Structured extraction. |
| LM-160 | Shall | Study and integrate Needle capability: Classification. |
| LM-161 | Shall | Study and integrate Needle capability: Device-intent routing. |
| LM-162 | Shall | Study and integrate Needle capability: Efficient local inference. |
| LM-163 | Shall | Reuse for multilingual speech recognition. |
| LM-164 | Shall | Evaluate alternative speech models and runtimes. |
| LM-165 | Shall | Reuse OCR inference and appropriate language packs. |
| LM-166 | Shall | Reuse mature encrypted SQLite functionality. |
| LM-167 | May | Optional vector retrieval, only if benchmarking justifies it. |
| LM-168 | Should | Study hierarchical compression |
| LM-169 | Should | Study incremental context management |
| LM-170 | Should | Study original-source recovery |
| LM-171 | Should | Study long-running context organization |
| LM-172 | Shall | Do not transplant its complete runtime onto a smartwatch. |
| LM-173 | Shall | Do not turn it into a separate product. |
| LM-174 | Shall | Upstream reuse rule: Check current licenses. |
| LM-175 | Shall | Upstream reuse rule: Record exact upstream commits. |
| LM-176 | Shall | Upstream reuse rule: Verify binaries. |
| LM-177 | Shall | Upstream reuse rule: Pin dependencies. |
| LM-178 | Shall | Upstream reuse rule: Preserve required attribution. |
| LM-179 | Shall | Upstream reuse rule: Reuse appropriate components rather than whole applications. |
| LM-180 | Shall | Upstream reuse rule: Never copy another project's consumer interface. |
| LM-181 | Shall | Upstream reuse rule: Never execute unreviewed downloaded scripts blindly. |

## 4. Model stack

| ID | Level | Requirement |
|---|---|---|
| LM-184 | Shall | The models must present one coherent native engine API. |
| LM-185 | Should | Suggested logical engine API: transcribe(audio) |
| LM-186 | Should | Suggested logical engine API: observe_screen(frame) |
| LM-187 | Should | Suggested logical engine API: extract_event(text) |
| LM-188 | Should | Suggested logical engine API: classify_event(event) |
| LM-189 | Should | Suggested logical engine API: embed_text(text) |
| LM-190 | Should | Suggested logical engine API: search_memory(query) |
| LM-191 | Should | Suggested logical engine API: retrieve_context(query) |
| LM-192 | Should | Suggested logical engine API: select_tool(command) |
| LM-193 | Should | Suggested logical engine API: execute_authorized_action(action) |
| LM-194 | Should | Suggested logical engine API: verify_action(result) |
| LM-195 | Should | Suggested logical engine API: sync_memory(device) |
| LM-196 | Should | Suggested logical engine API: forget_memory(record) |
| LM-197 | Shall | Efficient native interfaces |
| LM-198 | Shall | Replaceable native adapters |
| LM-199 | Should | Whisper Tiny Multilingual Q5_1 |
| LM-200 | Shall | Use the multilingual weights, not tiny.en. |
| LM-201 | Shall | ASR benchmark candidate: Whisper Tiny. |
| LM-202 | Shall | ASR benchmark candidate: Whisper Base. |
| LM-203 | Shall | ASR benchmark candidate: Whisper Small. |
| LM-204 | Shall | ASR benchmark candidate: Quantized variants. |
| LM-205 | Shall | ASR benchmark candidate: Sherpa-ONNX candidates. |
| LM-206 | Shall | ASR benchmark candidate: Language-specialized models. |
| LM-207 | Should | ASR benchmark candidate: Project Vaani candidates where useful. |
| LM-208 | Shall | Use actual benchmarks to choose models. |
| LM-209 | Shall | Do not optimize solely for parameter count. |
| LM-210 | Should | Cactus Needle. |
| LM-211 | Shall | Evaluate official Needle variants in the 8–29 MB range |
| LM-212 | Shall | Evaluate other relevant official Needle configurations |
| LM-213 | Shall | Needle responsibility: Identify structured events. |
| LM-214 | Shall | Extract names |
| LM-215 | Shall | Extract dates |
| LM-216 | Shall | Extract times |
| LM-217 | Shall | Extract locations |
| LM-218 | Shall | Extract tasks |
| LM-219 | Shall | Needle responsibility: Detect important preferences. |
| LM-220 | Shall | Needle responsibility: Classify observations. |
| LM-221 | Shall | Needle responsibility: Select tools. |
| LM-222 | Shall | Needle responsibility: Route commands to appropriate devices. |
| LM-223 | Shall | Needle responsibility: Determine whether a request needs memory retrieval. |
| LM-224 | Shall | Identify uncertainty |
| LM-225 | Shall | Identify missing information |
| LM-226 | Shall | Needle must not be given unrestricted execution authority. |
| LM-227 | Shall | Deterministically validate tool-call requests |
| LM-228 | Shall | Check permissions for tool-call requests |
| LM-229 | Should | PaddleOCR. |
| LM-230 | Shall | OCR script support: Latin scripts. |
| LM-231 | Shall | OCR script support: Chinese. |
| LM-232 | Shall | OCR script support: Devanagari. |
| LM-233 | Shall | OCR script support: Tamil. |
| LM-234 | Shall | OCR script support: Telugu. |
| LM-235 | Shall | OCR script support: Other supported scripts. |
| LM-236 | Shall | Do not assume the same OCR checkpoint is optimal for every language. |
| LM-237 | Should | Prefer native accessibility text when supported and authorized because it can be more efficient than OCR. |
| LM-238 | Shall | Start with reliable SQLite-based indexing. |
| LM-239 | Shall | Benchmark lexical retrieval against semantic retrieval. |
| LM-240 | May | Consider small multilingual embedding models when the additional runtime and memory cost is justified. |
| LM-241 | Shall | Do not add embeddings merely because they sound advanced. |
| LM-242 | May | Evaluate lightweight speech detection such as Silero VAD where useful. |
| LM-244 | Shall | Do not use VAD as justification for covert recording. |
| LM-245 | May | Different devices may use different model variants. |
| LM-246 | Shall | Keep shared interfaces compatible across device model variants |
| LM-247 | Should | Heavy models should not remain in memory unnecessarily. |
| LM-248 | Shall | The smallest model must still meet its declared functional acceptance criteria. |

## 5. Multilingual understanding

| ID | Level | Requirement |
|---|---|---|
| LM-249 | Shall | Lens is a global product. |
| LM-250 | Shall | It is not India-only. |
| LM-251 | Shall | Prioritized language: English *(superseded: priority order is English, Hindi, Mandarin Chinese, Spanish (docs/LENS_V1_SPEC.md §1a))* |
| LM-252 | Shall | Prioritized language: Mandarin Chinese *(superseded: priority order is English, Hindi, Mandarin Chinese, Spanish (docs/LENS_V1_SPEC.md §1a))* |
| LM-253 | Shall | Prioritized language: Spanish *(superseded: priority order is English, Hindi, Mandarin Chinese, Spanish (docs/LENS_V1_SPEC.md §1a))* |
| LM-254 | Shall | Prioritized language: Hindi *(superseded: priority order is English, Hindi, Mandarin Chinese, Spanish (docs/LENS_V1_SPEC.md §1a))* |
| LM-255 | Should | Then expand broadly. |
| LM-256 | Should | Additional important language: Tamil |
| LM-257 | Should | Additional important language: Telugu |
| LM-258 | Should | Additional important language: Malayalam |
| LM-259 | Should | Additional important language: Kannada |
| LM-260 | Should | Additional important language: Bengali |
| LM-261 | Should | Additional important language: Marathi |
| LM-262 | Should | Additional important language: French |
| LM-263 | Should | Additional important language: German |
| LM-264 | Should | Additional important language: Portuguese |
| LM-265 | Should | Additional important language: Arabic |
| LM-266 | Should | Additional important language: Japanese |
| LM-267 | Should | Additional important language: Korean |
| LM-268 | Should | Additional important language: Other supported world languages |
| LM-269 | Should | Target the widest practical coverage. |
| LM-270 | Shall | Support code-switching. |
| LM-271 | Should | Code-switching example to validate: English + Tamil |
| LM-272 | Should | Code-switching example to validate: English + Telugu |
| LM-273 | Should | Code-switching example to validate: English + Hindi |
| LM-274 | Should | Code-switching example to validate: English + Spanish |
| LM-275 | Should | Code-switching example to validate: English + Chinese |
| LM-276 | Shall | Preserve the original script. |
| LM-277 | Shall | Preserve original transcripts. |
| LM-278 | Shall | Do not automatically translate all content into English and discard the source. |
| LM-279 | Shall | Translations are derived records. |
| LM-284 | Shall | These must be tested using real reference audio. |
| LM-285 | Shall | Do not claim the model understands them because they look understandable in written form. |
| LM-286 | Shall | Measure ASR accuracy independently |
| LM-287 | Shall | Measure event-extraction accuracy independently |
| LM-289 | Shall | Both components must be evaluated. |
| LM-291 | Shall | Maintain language-level quality tiers. |

## 6. Screen observation

| ID | Level | Requirement |
|---|---|---|
| LM-292 | Should | Lens should remember authorized digital activity. |
| LM-293 | Shall | Eventually observe where supported and authorized: Active application. |
| LM-294 | Shall | Eventually observe where supported and authorized: Active window. |
| LM-295 | Shall | Eventually observe where supported and authorized: Accessible screen text. |
| LM-296 | Shall | Eventually observe where supported and authorized: Relevant app changes. |
| LM-297 | Shall | Eventually observe where supported and authorized: Accessible notifications. |
| LM-298 | Shall | Eventually observe where supported and authorized: Document names and metadata. |
| LM-299 | Shall | Eventually observe where supported and authorized: Permitted browsing activity. |
| LM-300 | Shall | Eventually observe where supported and authorized: Relevant user interactions. |
| LM-301 | Shall | Eventually observe where supported and authorized: Supported system events. |
| LM-302 | Shall | Do not assume every OS allows unrestricted observation. |
| LM-303 | Shall | Use native events and accessibility information where appropriate and permitted. |
| LM-304 | Shall | Use OCR for visible text that native APIs cannot provide. |
| LM-305 | Shall | Detect meaningful screen change. |
| LM-306 | Shall | Identify the active application. |
| LM-307 | Shall | Identify supported text sources. |
| LM-308 | Shall | Perform OCR only when necessary. |
| LM-309 | Shall | Normalize extracted text. |
| LM-310 | Shall | Capture observation timestamp |
| LM-311 | Shall | Capture observation source |
| LM-312 | Shall | Deduplicate unchanged content. |
| LM-313 | Shall | Store complete authorized captured text encrypted. |
| LM-314 | Shall | Run lightweight event extraction. |
| LM-315 | Shall | Update the memory index. |
| LM-316 | Shall | Create relevant long-term memories. |
| LM-317 | Shall | Do not Re-OCR identical frames continuously |
| LM-318 | Shall | Do not Keep every model loaded |
| LM-319 | Shall | Do not Record protected surfaces |
| LM-320 | Shall | Do not Capture passwords by default |
| LM-321 | Shall | Do not Bypass app isolation |
| LM-322 | Shall | Do not Collect hidden private data |
| LM-323 | Shall | Do not Claim complete visual understanding from OCR alone |
| LM-325 | Shall | Store successfully captured article text |
| LM-326 | Shall | Store article source application |
| LM-327 | Shall | Store article timestamp |
| LM-328 | Shall | Store associated article metadata |
| LM-330 | Shall | Lens retrieves the original supporting text. |

## 7. Audio observation

| ID | Level | Requirement |
|---|---|---|
| LM-331 | Shall | Lens must understand permitted spoken information. |
| LM-332 | Shall | Authorize microphone or session before audio acquisition |
| LM-333 | Shall | Acquire authorized audio |
| LM-334 | May | Optional VAD stage |
| LM-335 | Shall | Multilingual ASR stage |
| LM-336 | Shall | Preserve original transcript |
| LM-337 | Shall | Extract structured information from transcript |
| LM-338 | Shall | Store audio-derived memory encrypted |
| LM-339 | Shall | Make audio-derived memory searchable and retrievable |
| LM-340 | Shall | Manually start Wear OS microphone sessions |
| LM-341 | Shall | Manually stop Wear OS microphone sessions |
| LM-342 | Shall | Recording must be visibly indicated. |
| LM-343 | Shall | No covert wearable recording. |
| LM-344 | Shall | Require clear authorization for recording on other platforms |
| LM-345 | Shall | Provide recording indicators on other platforms |
| LM-346 | Shall | Preserve audio-derived record field: Transcript. |
| LM-347 | Shall | Preserve audio-derived record field: Timestamp. |
| LM-348 | Shall | Preserve audio-derived record field: Language. |
| LM-349 | Shall | Preserve audio-derived record field: Source. |
| LM-350 | Shall | Preserve audio-derived record field: Device. |
| LM-351 | Shall | Preserve audio-derived record field: Relevant segmentation. |
| LM-352 | Shall | Preserve audio-derived record field: Model version. |
| LM-353 | Shall | Preserve audio-derived record field: Extracted facts. |
| LM-354 | Shall | Preserve audio-derived record field: Confidence where meaningful. |
| LM-355 | Shall | Do not store unnecessary raw audio indefinitely. |
| LM-356 | Shall | Expose raw-audio retention as a separate option |
| LM-357 | Shall | Make raw-audio retention explicitly configurable |
| LM-358 | Shall | Preserve complete captured transcripts according to the user's retention settings. |

## 8. Device events

| ID | Level | Requirement |
|---|---|---|
| LM-359 | Shall | Lens memory must not depend entirely on OCR. |
| LM-360 | Shall | Use authorized structured device events where available. |
| LM-372 | Should | Device-event metadata field: Device |
| LM-373 | Should | Device-event metadata field: Timestamp |
| LM-374 | Should | Device-event metadata field: Type |
| LM-375 | Should | Device-event metadata field: Source |
| LM-376 | Should | Device-event metadata field: Relevant metadata |
| LM-377 | Should | Device-event metadata field: Permission context |
| LM-378 | Should | Device-event metadata field: Relationships to other records |
| LM-379 | Shall | Do not fabricate inaccessible events. |

## 9. Historical data import

| ID | Level | Requirement |
|---|---|---|
| LM-380 | Shall | Lens must support existing historical data. |
| LM-381 | Should | It should not only remember information created after installation. |
| LM-383 | May | Potential authorized history importer: Authorized email connections. |
| LM-384 | May | Potential authorized history importer: Exported WhatsApp chats. |
| LM-385 | May | Potential authorized history importer: Other exported conversations. |
| LM-386 | May | Potential authorized history importer: Calendar history. |
| LM-387 | May | Potential authorized history importer: Existing reminders. |
| LM-388 | May | Potential authorized history importer: Accessible alarms. |
| LM-389 | May | Potential authorized history importer: Browser history. |
| LM-390 | May | Potential authorized history importer: Notes. |
| LM-391 | May | Potential authorized history importer: Documents. |
| LM-392 | May | Potential authorized history importer: User-selected folders. |
| LM-393 | May | Potential authorized history importer: Other approved data exports. |
| LM-395 | Should | Identify supported historical import methods |
| LM-396 | Should | Authorize historical import |
| LM-397 | Should | Process imported records |
| LM-398 | Should | Preserve imported-record sources |
| LM-399 | Should | Preserve imported-record timestamps |
| LM-400 | Shall | Do not bypass WhatsApp encryption. |
| LM-401 | Shall | Do not claim unrestricted access to existing chats. |
| LM-402 | Shall | Do not require users to surrender credentials to Lens. |
| LM-403 | Shall | Use supported APIs, delegated authorization, or user-controlled exports. |
| LM-404 | Shall | All imported data enters the same encrypted memory architecture. |
| LM-405 | Shall | Version importers |
| LM-406 | Shall | Preserve importer source provenance |
| LM-407 | Shall | Deduplicate imported records |
| LM-408 | Shall | Provide user deletion controls for imported data |

## 10. Memory architecture

| ID | Level | Requirement |
|---|---|---|
| LM-409 | Shall | Preserve complete captured memory |
| LM-410 | Shall | Create intelligent memory |
| LM-411 | Shall | Provide both complete captured memory and intelligent memory |
| LM-412 | Shall | Preserve successfully captured authorized records. |
| LM-413 | Shall | Preserve captured source-memory type: OCR text. |
| LM-414 | Shall | Preserve captured source-memory type: Speech transcripts. |
| LM-415 | Shall | Preserve captured source-memory type: Imported messages. |
| LM-416 | Shall | Preserve captured source-memory type: Document text. |
| LM-417 | Shall | Preserve captured source-memory type: Device events. |
| LM-418 | Shall | Preserve captured source-memory type: Application activity. |
| LM-419 | Shall | Preserve captured source-memory type: Timestamps. |
| LM-420 | Shall | Preserve captured source-memory type: Metadata. |
| LM-421 | Shall | Do not let the model decide to discard all information that appears temporarily unimportant. |
| LM-423 | Shall | Extract intelligent-memory type: Facts. |
| LM-424 | Shall | Extract intelligent-memory type: Preferences. |
| LM-425 | Shall | Extract intelligent-memory type: Relationships. |
| LM-426 | Shall | Extract intelligent-memory type: People. |
| LM-427 | Shall | Extract intelligent-memory type: Organizations. |
| LM-428 | Shall | Extract intelligent-memory type: Projects. |
| LM-429 | Shall | Extract intelligent-memory type: Commitments. |
| LM-430 | Shall | Extract intelligent-memory type: Tasks. |
| LM-431 | Shall | Extract intelligent-memory type: Locations. |
| LM-432 | Shall | Extract intelligent-memory type: Routines. |
| LM-433 | Shall | Extract intelligent-memory type: Repeated behaviors. |
| LM-434 | Shall | Extract intelligent-memory type: Important events. |
| LM-435 | Shall | Extract intelligent-memory type: Summaries. |
| LM-436 | Shall | Extract intelligent-memory type: Procedural knowledge. |
| LM-437 | Shall | Each derived record must point back to evidence in source memory. |
| LM-438 | Shall | Organize context by: Personal |
| LM-439 | Shall | Organize context by: Project |
| LM-440 | Shall | Organize context by: People |
| LM-441 | Shall | Organize context by: Time |
| LM-442 | Shall | Organize context by: Topic |
| LM-443 | Shall | Organize context by: Application |
| LM-444 | Shall | Organize context by: Device |
| LM-445 | Shall | Organize context by: Event sequence |
| LM-446 | May | These can be logical indexes rather than separate heavy databases. |
| LM-447 | Shall | Retrieve relevant records for a user question. |
| LM-448 | Shall | Assemble only context needed by the requesting model or agent |
| LM-449 | Shall | Do not load the entire lifetime history into one prompt. |

## 11. Memory data model

| ID | Level | Requirement |
|---|---|---|
| LM-450 | Shall | Use encrypted SQLite/SQLCipher. |
| LM-451 | Should | Suggested logical schema entity; table not mandated: devices |
| LM-452 | Should | Suggested logical schema entity; table not mandated: sources |
| LM-453 | Should | Suggested logical schema entity; table not mandated: observations |
| LM-454 | Should | Suggested logical schema entity; table not mandated: transcripts |
| LM-455 | Should | Suggested logical schema entity; table not mandated: ocr_records |
| LM-456 | Should | Suggested logical schema entity; table not mandated: events |
| LM-457 | Should | Suggested logical schema entity; table not mandated: entities |
| LM-458 | Should | Suggested logical schema entity; table not mandated: entity_relationships |
| LM-459 | Should | Suggested logical schema entity; table not mandated: facts |
| LM-460 | Should | Suggested logical schema entity; table not mandated: preferences |
| LM-461 | Should | Suggested logical schema entity; table not mandated: episodes |
| LM-462 | Should | Suggested logical schema entity; table not mandated: procedures |
| LM-463 | Should | Suggested logical schema entity; table not mandated: projects |
| LM-464 | Should | Suggested logical schema entity; table not mandated: summaries |
| LM-465 | Should | Suggested logical schema entity; table not mandated: embeddings |
| LM-466 | Should | Suggested logical schema entity; table not mandated: memory_links |
| LM-467 | Should | Suggested logical schema entity; table not mandated: action_requests |
| LM-468 | Should | Suggested logical schema entity; table not mandated: action_results |
| LM-469 | Should | Suggested logical schema entity; table not mandated: sync_events |
| LM-470 | Should | Suggested logical schema entity; table not mandated: permissions |
| LM-471 | Should | Suggested logical schema entity; table not mandated: retention_rules |
| LM-472 | Should | Suggested logical schema entity; table not mandated: schema_migrations |
| LM-473 | Should | Do not blindly create separate tables when a simpler normalized design is better. |
| LM-474 | Should | Preserve record field where appropriate: Unique ID |
| LM-475 | Should | Preserve record field where appropriate: Device ID |
| LM-476 | Should | Preserve record field where appropriate: Source ID |
| LM-477 | Should | Preserve record field where appropriate: Original text |
| LM-478 | Should | Preserve record field where appropriate: Derived text |
| LM-479 | Should | Preserve record field where appropriate: Event type |
| LM-480 | Should | Preserve record field where appropriate: Source application |
| LM-481 | Should | Preserve record field where appropriate: Original timestamp |
| LM-482 | Should | Preserve record field where appropriate: Observation timestamp |
| LM-483 | Should | Preserve record field where appropriate: Time zone |
| LM-484 | Should | Preserve record field where appropriate: Language |
| LM-485 | Should | Preserve record field where appropriate: Content hash |
| LM-486 | Should | Preserve record field where appropriate: Model version |
| LM-487 | Should | Preserve record field where appropriate: Extraction confidence |
| LM-488 | Should | Preserve record field where appropriate: Links to source evidence |
| LM-489 | Should | Preserve record field where appropriate: Consent context |
| LM-490 | Should | Preserve record field where appropriate: Retention state |
| LM-491 | Should | Preserve record field where appropriate: Version |
| LM-492 | Shall | Source records must remain recoverable while retained. |
| LM-493 | Shall | User-authorized deletion must actually remove data according to documented retention rules. |
| LM-494 | Shall | Do not interpret "immutable evidence" as permission to make personal data impossible to delete. |
| LM-495 | Shall | Use explicit migrations. |
| LM-496 | Shall | Use transactional writes. |
| LM-497 | Shall | Test crash recovery. |
| LM-498 | Shall | Test deduplication. |
| LM-499 | Shall | Test concurrent access. |
| LM-500 | Shall | Test encrypted WAL handling. |
| LM-501 | Shall | Test database reopening. |
| LM-502 | Shall | Test wrong-key rejection. |
| LM-503 | Shall | Test long-history performance. |

## 12. Memory formation

| ID | Level | Requirement |
|---|---|---|
| LM-504 | Shall | Incrementally improve organization of existing evidence |
| LM-508 | Should | Associate related events when supported by evidence |
| LM-509 | Should | It should not create three unrelated memories and lose the connection. |
| LM-510 | Shall | Memory-formation mechanism: Entity extraction. |
| LM-511 | Shall | Memory-formation mechanism: Temporal linking. |
| LM-512 | Shall | Memory-formation mechanism: Source references. |
| LM-513 | Shall | Memory-formation mechanism: Event clustering. |
| LM-514 | Shall | Memory-formation mechanism: Incremental summarization. |
| LM-515 | Shall | Memory-formation mechanism: Preference updates. |
| LM-516 | Shall | Memory-formation mechanism: Contradiction handling. |
| LM-517 | Shall | Memory-formation mechanism: Confidence tracking. |
| LM-520 | Shall | Do not simply overwrite the first observation. |
| LM-521 | Shall | Preserve historical preference change |
| LM-522 | Shall | Preserve timestamps of historical preference changes |
| LM-523 | Should | Distinguish epistemic or temporal state: What was observed. |
| LM-524 | Should | Distinguish epistemic or temporal state: What was inferred. |
| LM-525 | Should | Distinguish epistemic or temporal state: What was explicitly stated. |
| LM-526 | Should | Distinguish epistemic or temporal state: What is currently believed. |
| LM-527 | Should | Distinguish epistemic or temporal state: What may be outdated. |

## 13. Long-horizon context organisation

| ID | Level | Requirement |
|---|---|---|
| LM-529 | Shall | Lens shall not depend on a billion-token model context window. |
| LM-530 | Shall | Long-horizon context shall not be built as a standalone billion-context component. |
| LM-531 | Shall | Integrate context-management principles into Lens |
| LM-532 | Shall | Support later integration of context principles into Recursion |
| LM-533 | Shall | Integrated long-context principle: Preserve original records. |
| LM-534 | Shall | Integrated long-context principle: Incrementally organize new information. |
| LM-535 | Shall | Integrated long-context principle: Generate hierarchical summaries. |
| LM-536 | Shall | Integrated long-context principle: Avoid repeated expensive processing. |
| LM-537 | Shall | Integrated long-context principle: Retrieve details on demand. |
| LM-538 | Shall | Integrated long-context principle: Recover original evidence when summaries are insufficient. |
| LM-539 | Shall | Integrated long-context principle: Keep context across very long periods. |
| LM-540 | Shall | Integrated long-context principle: Make memory useful with smaller models. |
| LM-541 | Shall | Integrated long-context principle: Support model changes without losing history. |
| LM-542 | Shall | Integrated long-context principle: Prevent compression from destroying important facts. |
| LM-543 | Shall | Build retrieval and context management around these ideas. |
| LM-544 | Shall | Do not make a smartwatch run a heavy Node.js context proxy simply because an existing repository uses one. |
| LM-545 | Shall | Implement the smallest practical equivalent behavior. |

## 14. Search and recall

| ID | Level | Requirement |
|---|---|---|
| LM-546 | Shall | Search must go beyond keyword matching. |
| LM-547 | Shall | Required search capability: Exact search |
| LM-548 | Shall | Required search capability: Full-text search |
| LM-549 | Shall | Required search capability: Time-filtered retrieval |
| LM-550 | Shall | Required search capability: Application-filtered retrieval |
| LM-551 | Shall | Required search capability: Source-filtered retrieval |
| LM-552 | Shall | Required search capability: Multilingual retrieval |
| LM-553 | Shall | Required search capability: Entity lookup |
| LM-554 | Shall | Required search capability: Relationship lookup |
| LM-555 | Shall | Required search capability: Event-sequence retrieval |
| LM-556 | Shall | Required search capability: Preference lookup |
| LM-557 | Shall | Required search capability: Semantic retrieval where justified |
| LM-558 | Shall | Required search capability: Evidence-backed answer construction |
| LM-559 | Should | Search-result evidence field: Relevant answer or excerpt |
| LM-560 | Should | Search-result evidence field: Original source |
| LM-561 | Should | Search-result evidence field: Timestamp |
| LM-562 | Should | Search-result evidence field: Device |
| LM-563 | Should | Search-result evidence field: Confidence or match explanation |
| LM-564 | Should | Search-result evidence field: Source link/identifier |
| LM-566 | Should | Resolve Arun as an entity when possible. |
| LM-567 | Should | Find relevant source records. |
| LM-568 | Should | Retrieve messages or transcripts involving Arun. |
| LM-569 | Should | Identify project-related segments. |
| LM-570 | Should | Construct an evidence-grounded response. |
| LM-571 | Should | Show the original text and timestamp. |
| LM-572 | Shall | If the underlying record is missing, say so. |
| LM-573 | Shall | Do not hallucinate memories. |
| LM-574 | Shall | Do not treat a generated summary as stronger evidence than the original source. |

## 15. Recursion integration

| ID | Level | Requirement |
|---|---|---|
| LM-586 | Shall | Expose portable Lens interfaces |
| LM-587 | Shall | Avoid hardcoding Lens behavior to a single UI |
| LM-597 | Shall | Do not build separate user-facing products for these capabilities in the Lens repository. |

## 16. Cross-device memory

| ID | Level | Requirement |
|---|---|---|
| LM-598 | Shall | Keep local memory on each device |
| LM-599 | Shall | Encrypt each device local memory |
| LM-600 | Shall | The system must eventually synchronize compatible memories between trusted devices. |
| LM-605 | Shall | Cross-device security requirement: Device-specific identity. |
| LM-606 | Shall | Cross-device security requirement: Explicit device enrollment. |
| LM-607 | Shall | Cross-device security requirement: Cryptographic pairing. |
| LM-608 | Shall | Cross-device security requirement: End-to-end encryption. |
| LM-609 | Shall | Cross-device security requirement: Authentication. |
| LM-610 | Shall | Cross-device security requirement: Authorization. |
| LM-611 | Shall | Cross-device security requirement: Device revocation. |
| LM-612 | Shall | Cross-device security requirement: Offline queues. |
| LM-613 | Shall | Cross-device security requirement: Replay protection. |
| LM-614 | Shall | Cross-device security requirement: Sync acknowledgments. |
| LM-615 | Shall | Cross-device security requirement: Conflict handling. |
| LM-616 | Shall | Cross-device security requirement: Deletion propagation. |
| LM-617 | Shall | Cross-device security requirement: Source provenance preservation. |
| LM-618 | Shall | Same login does not automatically grant unrestricted execution permissions. |
| LM-619 | Shall | Cloud relays must not require personal-memory plaintext access |
| LM-620 | Shall | The system must work offline locally. |

## 17. Cross-device execution

| ID | Level | Requirement |
|---|---|---|
| LM-621 | Shall | Lens must support a unified device-execution protocol. |
| LM-623 | Shall | Cactus Needle is the decision component. |
| LM-624 | Shall | It is not the executor. |
| LM-626 | Should | Emit structured action requests |
| LM-627 | Should | Identify an appropriate target device in the action request |
| LM-628 | Should | Identify the requested capability in the action request |
| LM-629 | Should | Execution protocol step: Validate the request. |
| LM-630 | Should | Execution protocol step: Check authorization. |
| LM-631 | Should | Execution protocol step: Select a trusted device. |
| LM-632 | Should | Execution protocol step: Send an encrypted command. |
| LM-633 | Should | Execution protocol step: Validate the target-device permissions. |
| LM-634 | Should | Execution protocol step: Execute using supported native APIs. |
| LM-635 | Should | Execution protocol step: Verify the result. |
| LM-636 | Should | Execution protocol step: Return the result. |
| LM-637 | Should | Execution protocol step: Record the outcome. |
| LM-643 | Should | Grow supported actions through capability adapters |
| LM-644 | Should | Allow supported action plugins |
| LM-653 | Shall | Sensitive action requiring explicit confirmation: Send message |
| LM-654 | Shall | Sensitive action requiring explicit confirmation: Delete data |
| LM-655 | Shall | Sensitive action requiring explicit confirmation: Purchase item |
| LM-656 | Shall | Sensitive action requiring explicit confirmation: Move money |
| LM-657 | Shall | Sensitive action requiring explicit confirmation: Change security settings |
| LM-658 | Shall | Sensitive action requiring explicit confirmation: Share private information |
| LM-659 | Shall | Require explicit confirmation for sensitive actions |
| LM-660 | Shall | Never allow Needle alone to authorize sensitive actions. |
| LM-661 | Shall | Do not bypass Android background-execution restrictions. |
| LM-662 | Shall | Do not misuse accessibility capabilities. |
| LM-663 | Shall | Never promise arbitrary phone control if the OS does not permit the requested operation. |

## 18. Device capability mesh

| ID | Level | Requirement |
|---|---|---|
| LM-664 | Should | Lens should know what each device can do. |
| LM-665 | Shall | Maintain capability metadata. |
| LM-685 | Shall | Determine which device can fulfill it. |
| LM-686 | Shall | Select the correct executor. |
| LM-687 | Shall | Do not route all commands through one fixed device. |
| LM-688 | Shall | Do not require constant internet connectivity for local operations. |

## 19. Wear OS

| ID | Level | Requirement |
|---|---|---|
| LM-689 | Shall | Wear OS is a first-class Lens target. |
| LM-690 | Shall | Not just a notification companion. |
| LM-691 | Should | Support independent watch local-memory capture |
| LM-692 | Should | Support independent watch local-memory retrieval |
| LM-693 | Should | Bound watch functions by actual hardware capabilities |
| LM-695 | Shall | Use Android Studio Wear OS emulator. |
| LM-696 | Should | Wear OS design target: Small packaged models. |
| LM-697 | Should | Wear OS design target: Low CPU overhead. |
| LM-698 | Should | Wear OS design target: Minimal idle RAM. |
| LM-699 | Should | Wear OS design target: Short inference sessions. |
| LM-700 | Should | Wear OS design target: Lazy model loading. |
| LM-701 | Should | Wear OS design target: Battery-conscious behavior. |
| LM-702 | Should | Wear OS design target: Reliable local encrypted storage. |
| LM-703 | Shall | Wear microphone control: Explicit user start. |
| LM-704 | Shall | Wear microphone control: Visible recording indicator. |
| LM-705 | Shall | Wear microphone control: Explicit user stop. |
| LM-706 | Shall | Do not silently enable continuous listening. |
| LM-707 | Shall | Use prerecorded test clips where emulator audio-input limitations prevent live microphone validation. |
| LM-708 | Shall | Never claim real-world wearable battery life without physical hardware testing. |
| LM-709 | May | Optional paired-phone assistance for larger processing |
| LM-710 | Shall | Require user approval before watch offloading |
| LM-711 | Should | However, the watch should retain meaningful offline functionality. |

## 20. Resource budget

| ID | Level | Requirement |
|---|---|---|
| LM-715 | Shall | Proceed despite the reported 740 MB RAM usage *(superseded: RAM ceiling is 800,000,000 bytes (docs/LENS_V1_SPEC.md §15))* |
| LM-716 | Shall | Do not skip features merely to reach 500 MB |
| LM-718 | Should | 500 MB remains the optimization goal. |
| LM-719 | Shall | Do not silently sacrifice functionality to meet budget |
| LM-720 | Shall | Do not silently sacrifice privacy to meet budget |
| LM-721 | Shall | Do not silently sacrifice accuracy to meet budget |
| LM-722 | Shall | Record actual memory consumption honestly. |
| LM-723 | Shall | Resource measurement: Installed app size. |
| LM-724 | Shall | Resource measurement: Model weights. |
| LM-725 | Shall | Resource measurement: Native runtime size. |
| LM-726 | Shall | Resource measurement: Cold-start memory. |
| LM-727 | Shall | Resource measurement: Idle memory. |
| LM-728 | Shall | Resource measurement: ASR active memory. |
| LM-729 | Shall | Resource measurement: OCR active memory. |
| LM-730 | Shall | Resource measurement: Extraction active memory. |
| LM-731 | Shall | Resource measurement: Combined workloads. |
| LM-732 | Shall | Resource measurement: Peak process-tree memory. |
| LM-733 | Shall | Resource measurement: Long-running memory behavior. |
| LM-734 | Should | Resource optimization technique: Quantization. |
| LM-735 | Should | Resource optimization technique: Lazy loading. |
| LM-736 | Should | Resource optimization technique: Unloading inactive models. |
| LM-737 | Should | Resource optimization technique: Batching. |
| LM-738 | Should | Resource optimization technique: Event-driven processing. |
| LM-739 | Should | Resource optimization technique: Duplicate suppression. |
| LM-740 | Should | Resource optimization technique: Smaller runtime choices. |
| LM-741 | Should | Resource optimization technique: Efficient native data structures. |
| LM-742 | Should | Resource optimization technique: Avoiding unnecessary model concurrency. |
| LM-743 | Should | The watch should aim for substantially lower usage than the laptop. |
| LM-744 | Shall | Do not claim the 500 MB goal has been achieved until the complete packaged system is measured. |

## 21. Product user interface

| ID | Level | Requirement |
|---|---|---|
| LM-745 | Shall | Provide a premium application design |
| LM-746 | Shall | Provide an original application design |
| LM-747 | Shall | Do not copy third-party user interfaces. |
| LM-748 | Should | Original UI style direction: Dark. |
| LM-749 | Should | Original UI style direction: Black. |
| LM-750 | Should | Original UI style direction: Graphite. |
| LM-751 | Should | Original UI style direction: Gray. |
| LM-752 | Should | Original UI style direction: Subtle gradients. |
| LM-753 | Should | Original UI style direction: Strong typography. |
| LM-754 | Should | Original UI style direction: Minimal chrome. |
| LM-755 | Should | Original UI style direction: Purposeful animation. |
| LM-756 | Should | Original UI style direction: Clean information hierarchy. |
| LM-757 | Should | Original UI style direction: Excellent usability. |
| LM-758 | Shall | Design an application, not a marketing landing page. |
| LM-759 | Shall | Desktop UI capability: Universal memory search. |
| LM-760 | Shall | Desktop UI capability: Memory timeline. |
| LM-761 | Shall | Desktop UI capability: Source inspector. |
| LM-762 | Shall | Desktop UI capability: Application history. |
| LM-763 | Shall | Desktop UI capability: Transcript explorer. |
| LM-764 | Shall | Desktop UI capability: People/project relationships. |
| LM-765 | Shall | Desktop UI capability: Devices. |
| LM-766 | Shall | Desktop UI capability: Permissions. |
| LM-767 | Shall | Desktop UI capability: Language settings. |
| LM-768 | Shall | Desktop UI capability: Storage usage. |
| LM-769 | Shall | Desktop UI capability: Model status. |
| LM-770 | Shall | Desktop UI capability: Sync state. |
| LM-771 | Shall | Desktop UI capability: Privacy controls. |
| LM-772 | Shall | Phone UI capability: Search. |
| LM-773 | Shall | Phone UI capability: Recent memories. |
| LM-774 | Shall | Phone UI capability: Capture status. |
| LM-775 | Shall | Phone UI capability: Sources. |
| LM-776 | Shall | Phone UI capability: Device management. |
| LM-777 | Shall | Phone UI capability: Settings. |
| LM-778 | Shall | Phone UI capability: Privacy controls. |
| LM-779 | Shall | Watch UI capability: Start listening. |
| LM-780 | Shall | Watch UI capability: Stop listening. |
| LM-781 | Shall | Watch UI capability: Visible recording indicator. |
| LM-782 | Shall | Watch UI capability: Transcript feedback. |
| LM-783 | Shall | Watch UI capability: Quick search. |
| LM-784 | Shall | Watch UI capability: Recent memories. |
| LM-785 | Shall | Watch UI capability: Sync status. |
| LM-786 | Should | Visually distinguish: Original source evidence. |
| LM-787 | Should | Visually distinguish: AI-generated summaries. |
| LM-788 | Should | Visually distinguish: Inferred facts. |
| LM-789 | Should | Visually distinguish: Uncertain information. |
| LM-790 | Shall | All controls must work. |
| LM-791 | Shall | No fake interaction states. |
| LM-792 | Shall | No borrowed product branding. |
| LM-793 | Shall | Use appropriate reviewed UI/UX and frontend skills. |
| LM-794 | Shall | Review the design before committing to major UI implementation. |

## 22. Privacy and security

| ID | Level | Requirement |
|---|---|---|
| LM-795 | Shall | Privacy is not optional. |
| LM-797 | Shall | Required privacy/security capability: Local-first storage. |
| LM-798 | Shall | Required privacy/security capability: Strong encryption. |
| LM-799 | Shall | Required privacy/security capability: OS-backed key protection. |
| LM-800 | Shall | Required privacy/security capability: Clear capture indicators. |
| LM-801 | Shall | Required privacy/security capability: Permission transparency. |
| LM-802 | Shall | Required privacy/security capability: App/source exclusions. |
| LM-803 | Shall | Required privacy/security capability: Sensitive-field protection. |
| LM-804 | Shall | Required privacy/security capability: Deletion. |
| LM-805 | Shall | Required privacy/security capability: Export. |
| LM-806 | Shall | Required privacy/security capability: Device revocation. |
| LM-807 | Shall | Required privacy/security capability: Access controls. |
| LM-808 | Shall | Required privacy/security capability: Auditability. |
| LM-809 | Shall | Use SQLCipher for the database. |
| LM-810 | Shall | Use Windows DPAPI or an appropriate platform key facility where applicable. |
| LM-811 | Shall | Use Android Keystore for Android/Wear OS where appropriate. |
| LM-812 | Shall | Do not persist personal plaintext in logs |
| LM-813 | Shall | Do not persist personal plaintext in temporary folders |
| LM-814 | Shall | Do not transmit private data to unknown telemetry services. |
| LM-815 | Shall | Do not expose personal memories to model vendors. |
| LM-816 | Shall | Do not bypass app security. |
| LM-817 | Shall | Do not secretly monitor other people. |
| LM-818 | Shall | Do not access protected conversations without permission. |
| LM-819 | Shall | Do not save passwords by default |
| LM-820 | Shall | Do not save OTPs by default |
| LM-821 | Shall | Do not save authentication tokens by default |
| LM-822 | Shall | Do not save payment-card secrets by default |
| LM-823 | Shall | If future payments exist, use approved tokenized integrations |
| LM-824 | Shall | Do not store raw payment-card data |
| LM-825 | Shall | Provide clear retention controls |
| LM-826 | Shall | Provide clear deletion controls |
| LM-827 | Shall | Encrypt memory before synchronization. |

## 23. Autonomous memory organisation

| ID | Level | Requirement |
|---|---|---|
| LM-828 | Should | Lens should automatically organize information after authorized capture. |
| LM-829 | Should | A user should not have to manually label every memory. |
| LM-830 | Should | Autonomous organization behavior: Recognize events. |
| LM-831 | Should | Autonomous organization behavior: Identify recurring entities. |
| LM-832 | Should | Autonomous organization behavior: Link relevant records. |
| LM-833 | Should | Autonomous organization behavior: Extract preferences. |
| LM-834 | Should | Autonomous organization behavior: Update project contexts. |
| LM-835 | Should | Autonomous organization behavior: Generate periodic summaries. |
| LM-836 | Should | Autonomous organization behavior: Find meaningful changes. |
| LM-837 | Should | Autonomous organization behavior: Preserve timelines. |
| LM-838 | Should | Autonomous organization behavior: Keep original evidence accessible. |
| LM-839 | May | Potential future memory feature: Weekly memory digest. |
| LM-840 | May | Potential future memory feature: Project activity summaries. |
| LM-841 | May | Potential future memory feature: Personal knowledge summaries. |
| LM-842 | May | Potential future memory feature: Spaced-repetition assistance. |
| LM-843 | May | Potential future memory feature: Relevant reminders. |
| LM-844 | May | Potential future memory feature: Contextual suggestions. |
| LM-845 | Shall | These must be grounded in actual stored observations. |
| LM-846 | Shall | Do not infer intimate personal facts aggressively. |
| LM-847 | Shall | User corrections must be respected. |
| LM-848 | Shall | Allow user edits to memories |
| LM-849 | Shall | Allow users to exclude memories |
| LM-850 | Shall | Allow users to delete memories |

## 24. User experience scenarios

| ID | Level | Requirement |
|---|---|---|
| LM-853 | Shall | Lens locates the supporting observation. |
| LM-856 | Shall | Lens retrieves the original transcript and time. |
| LM-858 | Shall | Lens indexes them with their original timestamps. |
| LM-860 | Shall | Lens retrieves supporting messages. |
| LM-862 | Shall | Store authorized programming activity |
| LM-863 | Shall | Store evidence-backed project relationships |
| LM-865 | Shall | Lens retrieves relevant recorded project context. |
| LM-868 | Shall | Lens searches historical records. |
| LM-869 | Shall | If Recursion later offers ordering, that action must use approved tools and require appropriate confirmation. |
| LM-871 | Shall | They manually start the microphone. |
| LM-873 | Shall | Transcribe a user-initiated watch reminder request |
| LM-874 | Shall | Store the watch transcript locally |
| LM-875 | May | Optionally create an authorized reminder |
| LM-877 | Shall | The command is routed to the correct trusted device. |
| LM-878 | Shall | Validate the command on the target phone |
| LM-879 | Shall | Attempt authorized action on the target phone |
| LM-881 | Shall | Lens responds: "I couldn't find a supporting record." |
| LM-882 | Shall | No hallucinated memories. |

## 25. Long-term design

| ID | Level | Requirement |
|---|---|---|
| LM-884 | Shall | Do not bind memory to one neural-network architecture. |
| LM-885 | Shall | Do not bind memory to one operating system. |
| LM-886 | Shall | Do not bind memory to one embedding model. |
| LM-887 | Shall | Do not depend on a single commercial LLM vendor. |
| LM-888 | Shall | Use portable schemas. |
| LM-889 | Shall | Use migration-safe records. |
| LM-890 | Shall | Use stable APIs. |
| LM-891 | Shall | Use replaceable inference adapters. |
| LM-892 | Shall | Use capability-based device routing. |
| LM-893 | Shall | Use encrypted transport. |
| LM-894 | Shall | Use versioned memory formats. |
| LM-895 | Shall | Preserve source provenance. |
| LM-896 | Shall | Support new device categories. |
| LM-897 | Shall | Separate perception from memory |
| LM-898 | Shall | Separate retrieval from perception and memory |
| LM-899 | Shall | Separate execution from retrieval and model decisions |
| LM-900 | Should | Future models should improve Lens without requiring users to rebuild their history. |

## 26. Benchmarking

| ID | Level | Requirement |
|---|---|---|
| LM-901 | Shall | Benchmark every component honestly. |
| LM-902 | Shall | ASR benchmark dimension: WER |
| LM-903 | Shall | ASR benchmark dimension: CER |
| LM-904 | Shall | ASR benchmark dimension: Language identification |
| LM-905 | Shall | ASR benchmark dimension: Code-switching |
| LM-906 | Shall | ASR benchmark dimension: Accents |
| LM-907 | Shall | ASR benchmark dimension: Noise |
| LM-908 | Shall | ASR benchmark dimension: Named entities |
| LM-909 | Shall | ASR benchmark coverage of dates and times |
| LM-910 | Shall | ASR benchmark dimension: Latency |
| LM-911 | Shall | ASR benchmark dimension: Real-time factor |
| LM-912 | Shall | ASR benchmark dimension: RAM |
| LM-913 | Shall | ASR benchmark dimension: Model size |
| LM-914 | Shall | OCR benchmark dimension: CER |
| LM-915 | Shall | OCR benchmark dimension: Exact match |
| LM-916 | Shall | OCR benchmark dimension: Real screenshots |
| LM-917 | Shall | OCR benchmark dimension: Mixed scripts |
| LM-918 | Shall | OCR benchmark dimension: Small text |
| LM-919 | Shall | OCR benchmark dimension: Different applications |
| LM-920 | Shall | OCR benchmark dimension: Latency |
| LM-921 | Shall | OCR benchmark dimension: RAM |
| LM-922 | Shall | OCR benchmark dimension: Deduplication |
| LM-923 | Shall | Needle benchmark dimension: Event extraction precision |
| LM-924 | Shall | Needle benchmark dimension: Recall |
| LM-925 | Shall | Needle benchmark dimension: F1 |
| LM-926 | Shall | Needle benchmark dimension: Tool accuracy |
| LM-927 | Shall | Needle benchmark dimension: Negated requests |
| LM-928 | Shall | Needle benchmark dimension: Malformed JSON |
| LM-929 | Shall | Needle benchmark dimension: False actions |
| LM-930 | Shall | Needle benchmark dimension: Multilingual extraction |
| LM-931 | Shall | Needle benchmark dimension: Uncertainty |
| LM-932 | Shall | Memory benchmark dimension: Recall@5 |
| LM-933 | Shall | Memory benchmark dimension: False positives |
| LM-934 | Shall | Memory benchmark dimension: Source attribution |
| LM-935 | Shall | Memory benchmark dimension: Temporal accuracy |
| LM-936 | Shall | Memory benchmark dimension: Long-history retrieval |
| LM-937 | Shall | Memory benchmark dimension: Cross-language retrieval |
| LM-938 | Shall | Memory benchmark dimension: Crash recovery |
| LM-939 | Shall | Memory benchmark dimension: Encryption |
| LM-940 | Shall | Memory benchmark dimension: Database migration |
| LM-941 | Shall | Device execution benchmark dimension: Correct routing |
| LM-942 | Shall | Device execution benchmark dimension: Authorization |
| LM-943 | Shall | Device execution benchmark dimension: Execution success |
| LM-944 | Shall | Device execution benchmark dimension: Result verification |
| LM-945 | Shall | Device execution benchmark dimension: Failure recovery |
| LM-946 | Shall | Device execution benchmark dimension: Offline behavior |
| LM-947 | Shall | Sync benchmark dimension: Encryption |
| LM-948 | Shall | Sync benchmark dimension: Pairing |
| LM-949 | Shall | Sync benchmark dimension: Reconnection |
| LM-950 | Shall | Sync benchmark dimension: Conflict resolution |
| LM-951 | Shall | Sync benchmark dimension: Deletion propagation |
| LM-952 | Shall | Sync benchmark dimension: Revocation |
| LM-953 | Shall | Sync benchmark dimension: Replay protection |
| LM-954 | Shall | Target-device benchmark: Windows |
| LM-955 | Shall | Target-device benchmark: Android |
| LM-956 | Shall | Target-device benchmark: Wear OS emulator |
| LM-957 | Shall | Target-device benchmark: Later physical watch |
| LM-958 | Shall | Record exact benchmark datasets |
| LM-959 | Shall | Record benchmark component versions |
| LM-960 | Shall | Record hardware measurements |
| LM-961 | Shall | Retain benchmark failure reports |
| LM-962 | Shall | Do not turn unsuccessful tests green. |
| LM-963 | Shall | Do not cherry-pick investor benchmarks. |
| LM-1178 | Shall | ASR benchmark dimension: dates |
| LM-1179 | Shall | ASR benchmark dimension: times |

## 27. Verification of previously reported results

| ID | Level | Requirement |
|---|---|---|
| LM-965 | Shall | Do not delete or recreate it. |
| LM-967 | Shall | Verify everything against actual files and reports. |
| LM-1002 | Shall | Inspect the current reports and binaries. |
| LM-1003 | Shall | Do not discard the existing tested work. |

## 28. Open work items

| ID | Level | Requirement |
|---|---|---|
| LM-1004 | Shall | Complete or verify broader English benchmarks |
| LM-1005 | Shall | Complete or verify broader Mandarin Chinese benchmarks |
| LM-1006 | Shall | Complete or verify broader Spanish benchmarks |
| LM-1007 | Shall | Complete or verify broader Hindi benchmarks |
| LM-1008 | Shall | Complete or verify international model comparisons |
| LM-1009 | Shall | Complete or verify Indian-language model comparisons |
| LM-1010 | Shall | Real screenshot OCR testing. |
| LM-1011 | Shall | Automatic screen observation. |
| LM-1012 | Shall | Device-event capture. |
| LM-1013 | Shall | Existing-history imports. |
| LM-1014 | Shall | Robust multilingual event extraction. |
| LM-1015 | Shall | Intelligent memory formation. |
| LM-1016 | Shall | Natural-language source-backed retrieval. |
| LM-1017 | Shall | Long-horizon context organization. |
| LM-1018 | Shall | Complete or verify memory database migrations |
| LM-1019 | Shall | Complete or verify user memory deletion |
| LM-1020 | Shall | Resource optimization. |
| LM-1021 | Shall | Android native integration. |
| LM-1022 | Shall | Wear OS native inference. |
| LM-1023 | Shall | Wear OS microphone interface. |
| LM-1024 | Shall | Encrypted device synchronization. |
| LM-1025 | Shall | Cross-device command execution. |
| LM-1026 | Shall | Complete or verify permission systems |
| LM-1027 | Shall | Complete or verify confirmation systems |
| LM-1028 | Shall | Original desktop interface. |
| LM-1029 | Shall | Original Android interface. |
| LM-1030 | Shall | Original watch interface. |
| LM-1031 | Shall | Installable release packaging. |
| LM-1032 | Shall | Actual end-to-end integration tests. |
| LM-1033 | Shall | Investor-quality truthful demonstrations. |
| LM-1034 | Shall | Do not silently remove these requirements. |

## 29. Development strategy

| ID | Level | Requirement |
|---|---|---|
| LM-1035 | Shall | Model first. |
| LM-1036 | Shall | Memory Second. |
| LM-1037 | Shall | Device integration third. |
| LM-1038 | Shall | Product UI and verified demo after the foundation works. |
| LM-1039 | Shall | But the complete product remains the ultimate deliverable. |
| LM-1040 | Shall | Inspect existing implementation. |
| LM-1041 | Shall | Preserve working code. |
| LM-1042 | Shall | Resume unfinished benchmarks. |
| LM-1043 | Shall | Resolve Mandarin model limitations |
| LM-1044 | Shall | Resolve Hindi model limitations |
| LM-1045 | Shall | Validate native OCR. |
| LM-1046 | Shall | Finish robust extraction. |
| LM-1047 | Shall | Build full encrypted memory behavior |
| LM-1048 | Shall | Validate full encrypted memory behavior |
| LM-1049 | Shall | Add incremental context organization. |
| LM-1050 | Shall | Implement advanced search |
| LM-1051 | Shall | Implement source-backed retrieval |
| LM-1052 | Shall | Build authorized device observers. |
| LM-1053 | Shall | Build supported history importers. |
| LM-1054 | Shall | Build encrypted synchronization. |
| LM-1055 | Shall | Build device capability routing. |
| LM-1056 | Shall | Build authorized device execution. |
| LM-1057 | Shall | Complete Windows EXE. |
| LM-1058 | Shall | Complete Android APK. |
| LM-1059 | Shall | Complete Wear OS APK. |
| LM-1060 | Shall | Finish the original premium UI. |
| LM-1061 | Shall | Run end-to-end tests. |
| LM-1062 | Shall | Fix failures. |
| LM-1063 | Shall | Produce documented releases. |
| LM-1064 | Shall | Do not start the whole project again. |

## 30. Engineering standards

| ID | Level | Requirement |
|---|---|---|
| LM-1065 | Shall | Read the existing repository first. |
| LM-1066 | Shall | Preserve user work. |
| LM-1067 | Shall | Reuse upstream source code. |
| LM-1068 | Shall | Pin dependencies. |
| LM-1069 | Shall | Verify licenses. |
| LM-1070 | Shall | Read relevant installed skills. |
| LM-1071 | Shall | Avoid overlapping unnecessary skills. |
| LM-1072 | Shall | Never fake benchmarks. |
| LM-1073 | Shall | Never fabricate application capabilities. |
| LM-1074 | Shall | Measure actual memory consumption. |
| LM-1075 | Shall | Do not let a smaller model silently reduce quality. |
| LM-1076 | Shall | Keep original source records. |
| LM-1077 | Shall | Store memory encrypted. |
| LM-1078 | Shall | Validate every tool call. |
| LM-1079 | Shall | Require permission for sensitive actions. |
| LM-1080 | Shall | Keep code modular. |
| LM-1081 | Shall | Keep the engine portable. |
| LM-1082 | Shall | Use native inference for production. |
| LM-1083 | Shall | Avoid mandatory paid production LLM APIs. |
| LM-1084 | Shall | Exclude Python development tooling from the production application |
| LM-1085 | Shall | Do not package development datasets. |
| LM-1086 | Shall | Do not silently upload private data. |
| LM-1087 | Shall | Do not overwrite existing reports. |
| LM-1088 | Shall | Fix actual failures before claiming completion. |
| LM-1089 | Shall | Ask for approval before major product changes. |
| LM-1090 | Shall | Continue routine development without unnecessary     repeated questions. |
| LM-1091 | Shall | Preserve documented unsuccessful experiments. |
| LM-1092 | Shall | Keep Git history clean. |
| LM-1093 | Shall | Do not publish externally without approval. |
| LM-1094 | Shall | Verify software on the actual supported platform |
| LM-1095 | Shall | Identify unavailable-hardware validation limitations |

## 31. Definition of a working product

| ID | Level | Requirement |
|---|---|---|
| LM-1096 | Shall | A user installs Lens. |
| LM-1097 | Shall | They authorize supported capture sources. |
| LM-1098 | Shall | Lens observes permitted activity. |
| LM-1099 | Shall | It transcribes permitted conversations. |
| LM-1100 | Shall | It reads accessible screen text. |
| LM-1101 | Shall | It processes device events. |
| LM-1102 | Shall | It stores complete records encrypted. |
| LM-1103 | Shall | It creates intelligent memory. |
| LM-1104 | Shall | It indexes the information. |
| LM-1105 | Shall | It relates relevant events. |
| LM-1106 | Shall | It retrieves historical context. |
| LM-1107 | Shall | It can operate offline for supported local features. |
| LM-1108 | Shall | It can synchronize across trusted devices. |
| LM-1109 | Shall | It can receive commands from another trusted device. |
| LM-1110 | Shall | Execute allowed actions |
| LM-1111 | Shall | Verify action outcomes |
| LM-1112 | Shall | Delete user memories |
| LM-1113 | Shall | Export user memories |
| LM-1114 | Shall | It can replace models without losing personal history. |
| LM-1115 | Shall | It can explain where remembered information came from. |
| LM-1116 | Shall | It never invents a memory. |
| LM-1117 | Shall | The interface feels like one premium application. |

## 32. Progress reporting

| ID | Level | Requirement |
|---|---|---|
| LM-1122 | Shall | Do not start from zero. |
| LM-1123 | Shall | Do not build a superficial demo. |
| LM-1124 | Shall | Actually continue development. |
| LM-1125 | Shall | Inspect D:\Lens. |
| LM-1126 | Shall | Read repository AGENTS.md |
| LM-1127 | Shall | Read relevant repository skills |
| LM-1128 | Shall | Read existing code |
| LM-1129 | Shall | Read architecture documents |
| LM-1130 | Shall | Read benchmark reports |
| LM-1131 | Shall | Read test logs |
| LM-1132 | Shall | Verify the real implementation status. |
| LM-1133 | Shall | Identify the current unfinished work from the prior session. |
| LM-1134 | Shall | Resume the highest-priority incomplete engineering task. |
| LM-1135 | Shall | Build the current engineering task |
| LM-1136 | Shall | Test the current engineering task |
| LM-1137 | Shall | Fix failures in the current engineering task |
| LM-1138 | Shall | Continue through the approved development phases. |
| LM-1139 | Shall | Required milestone-report field: What works. |
| LM-1140 | Shall | Required milestone-report field: What was actually tested. |
| LM-1141 | Shall | Required milestone-report field: Measured performance. |
| LM-1142 | Shall | Required milestone-report field: Failures. |
| LM-1143 | Shall | Required milestone-report field: Known limitations. |
| LM-1144 | Shall | Required milestone-report field: Next task. |
| LM-1145 | Shall | Do not report fictional completion percentages. |
| LM-1146 | Shall | Do not stop merely because one test passed. |
| LM-1147 | Shall | Do not claim full Lens functionality when only the native model harness works. |
| LM-1148 | Shall | Continue until the implementation is genuinely functional or a specific unavoidable blocker requires the founder's decision. |
