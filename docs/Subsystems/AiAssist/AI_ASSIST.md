# Offline AI Assist

Status: living document, edit in place
Owner area: advisory prompt and workflow suggestions from a locally stored open-weight model (`src/ai_assist/`, `config/managed_ai_runtime.json`, `config/ai_model_registry.json`, the `ai_assist` readiness record in `src/services/operator_readiness_service.py`)

How to keep this true:
- Change this file in the same PR that changes a contract, a gate, the pinned manifests, the process rules or the qualification criteria. Edit the existing row or sentence.
- Do not append per-PR sections, dates or test counts. History lives in `git log`.
- Labels: **[V]** read in the code when this was written; **[P]** a decision recorded by the owner (PR-AI-100, D1-D12); **[U]** unknown until PR-AI-111 measures it.

## 1. Scope and state

Offline AI Assist turns one explicit operator request into a **typed, validated suggestion**: a prompt rewrite, a target-fit choice or a workflow choice. It sits *before* Intent as an authoring aid. It is **foundation plus offline qualification machinery** today [V]: nothing is installed, no runtime build is pinned and no model is qualified (the model registry holds four unverified *candidates*, the runtime manifest is empty), there is no GUI, and nothing calls the service in production. The only production-reachable surface is the read-only `ai_assist` record in Operator Readiness, which reports "optional / not installed". No weights have been downloaded and no inference has ever been run [P: D12]. PR-AI-111 Stage 1 is recorded in `PR-AI-111_Offline_Qualification.md`.

Decisions [P]: one-shot contained subprocess (D2); CPU-only in v1 (D3); third-party GGUF files allowed with verified provenance and hash pinning (D4); sensitive prompts supported locally, refusals surfaced and never silently sanitised, provisional 5% refusal-rate qualification target (D5); unknown or mismatched hashes refused (D6); no training-data capture or fine-tuning in v1 (D7); outbound firewall restriction is operator-managed, never automatic (D8); request-scoped AI cancellation is allowed while job cancellation is unchanged (D9); AI refuses or terminates during a GPU quarantine or generation-resource conflict (D10). Package split: PR-AI-110 foundation (this), 111 physical qualification, 112 controller service and GUI, conditional 120 (D1).

## 2. Authority and the canonical path

AI Assist adds **no** queue, history, lifecycle, cancellation, process or compiler authority [V].

| Concern | Reality |
|---|---|
| Canonical path | Unchanged. A suggestion is text for an editing buffer; the operator's ordinary Preview and Add to Queue produce the NJR. |
| Compiler and policy | `adapt_prompt_for_target` and `ModelPolicy` stay authoritative. Later GUI work shows their result for a suggestion before Accept. |
| Layering | `src/ai_assist` may import only `ai_assist`, `utils` and `prompting`. The `ai_assist_forbidden_imports` architecture ratchet (baseline 0) fails on any import of the queue, repository, job service, runner, NJR core, backends or GUI. |
| Process facility | Only `src.utils.managed_process.run_bounded`. No `ManagedProcess`, no server, no listening socket. |
| Cancellation | `AiCancelToken` is request-scoped and distinct from the controller's `CancelToken`. `AiAssistService.cancel` affects that request only; the service has no method that touches a job. |
| Persistence | `src/utils/atomic_io.py` only. |

## 3. Contracts (`contracts.py`, `validators.py`, `framing.py`)

- `AssistRequest` (explicit operator request) -> `AssistOutcome`, whose `suggestion` is set exactly when `code` is `SUGGESTION` [V].
- `AssistSuggestion` kinds: `PROMPT_REWRITE`, `TARGET_FIT_ADVICE`, `WORKFLOW_CHOICE`. It has no field that can become an executable payload. Choices come from **closed lists** supplied with the request.
- Outcomes (stable codes, never converted into one another): `SUGGESTION`, `REFUSED_BY_MODEL`, `MALFORMED`, `INVALID_REQUEST`, `TIMEOUT`, `CANCELLED`, `RESOURCE_INSUFFICIENT`, `BUSY`, `UNAVAILABLE`, `NOT_INSTALLED`, `INTEGRITY_FAILED`, `EGRESS_NOT_ATTESTED`, `GENERATION_ACTIVE` (refused at admission), `YIELDED_TO_GENERATION` (terminated while running).
- Validation is pure and never repairs: exactly one JSON object of the frozen schema; closed-list membership; the multiset of protected tokens (`<extra-network>` and `[[matrix]]`, the adaptation engine's own non-prose rule) must equal the authored text's; length-growth bounds; no control characters. An instruction hidden in authored text cannot change this, because the validator is the only path to `SUGGESTION`.
- Refusal is deterministic: an explicit `status: "refused"`, or non-JSON text that opens like a refusal. Anything else that fails the schema is `MALFORMED`, not a guessed refusal. A refusal is surfaced as `REFUSED_BY_MODEL` and is never turned into a suggestion [P: D5].
- Authored text is placed between reserved delimiter lines in a fixed instruction frame and declared to be data. Text containing a delimiter is `INVALID_REQUEST`, not rewritten.

## 4. Process and resource contract (`argv.py`, `runtime.py`, `service.py`, `host.py`)

- **CPU only, offline, no endpoint.** `build_argv` emits a closed flag vocabulary: always `--offline` and `-ngl 0`, never `-hf`, `-mu`, `-dr`, `--connect`, `--ui-mcp-proxy`, `--mmproj`, `--host`, `--port` or `--lora`. The child environment is scrubbed (no proxy variables or tokens), sets `CUDA_VISIBLE_DEVICES=-1`, `HF_HUB_OFFLINE=1`, `NO_PROXY=*`, and `PATH` is the runtime directory only. Prompt text and the JSON Schema go to the child as files in a per-request scratch directory, never on the command line. The flag spellings are **provisional [U]** until PR-AI-111 validates them against the pinned build; a spelling the build rejects ends as `UNAVAILABLE` and cannot widen what is allowed.
- **Single-flight.** One request at a time (`BUSY`). Admission order: single-flight, installation integrity, strict-offline attestation, generation activity, memory.
- **AI yields to generation [P: D10].** Admission is refused while a queue job is RUNNING, a GPU quarantine is active, or generation activity cannot be read. While a request runs, `run_bounded` polls the service every 50 ms and the service samples generation activity and host memory every `watch_interval_seconds` (0.25 s); a running job, a quarantine, an unreadable provider, or two consecutive memory breaches terminate the child's whole tree (`YIELDED_TO_GENERATION` or `RESOURCE_INSUFFICIENT`). Activity comes from an injected **read-only** provider; there is no queue flag or claim hook. **Residual:** a job that claims between two samples can overlap the request by at most one watch interval plus the kill. Production wiring of the provider is PR-AI-112.
- **Memory gate (GiB, stated).** Admission needs available physical RAM and commit headroom each at least model file size + 4 GiB. The running guard mirrors the WAN-321F limits: available RAM below 0.25 GiB or commit headroom below 1 GiB for two consecutive samples. An unreadable probe is a failure, never "plenty". Units are GiB (`1024**3`); the repository also contains decimal-GB readings (`forge_klein_readiness`), so never mix them.
- **Bounds.** Wall-clock timeout, stdout cap, stderr prefix cap and a thread cap. Timeout, cancel and overflow kill the whole tree and return.
- **Child priority and tree memory (F2, `observe.py`).** `run_bounded` has no priority parameter and does not expose the child's pid, and it is a shared safety primitive that this feature does not change. The AI layer therefore finds its own child (a descendant whose command line holds the request's unique scratch directory), applies below-normal priority to the whole tree and **reads it back from the OS** (`priority_verified`), samples the tree's private memory and working set (peaks kept as evidence), and stops the request above a cap (default 1.5 x the model file + 2 GiB of *private* memory, since the weights are memory-mapped; two consecutive samples) or when the child cannot be found within 3 s (an unseen child cannot be bounded). Priority is best-effort in production (it is reported, not required); physical qualification requires `priority_verified`, `child_observed` and a verified teardown. Windows only for priority; elsewhere the evidence says not applicable. Proven against real children; proven against the real inference binary only in PR-AI-111 Stage A.
- **Fail-closed readings.** A provider reading is accepted only if it is a well-formed `GenerationActivity` / `HostMemory` (exact types, finite and non-negative numbers). `None`, a wrong type, a negative count, NaN or infinity is a conflict at admission and a stop while running; a NaN would otherwise compare false against every threshold and read as "plenty". `run_bounded` treats an exception from its cancel callable as "not cancelled", so the watch catches everything itself and any internal error stops the child (`watch_error`).
- **Prompt text on disk and in the child's output.** Each request's prompt and schema live in `<root>/work/<request_id>/` (`TEMP`/`TMP` point there) and the directory is removed when the request ends. Immediate deletion after a hard process kill, a power loss or a locked file **cannot be guaranteed** (the request's `finally` never runs, or `rmtree` fails and is only logged), so the service sweeps `work/` once before its first request, removing only direct, non-symlink directories older than one hour (no live request lasts that long). Stdout must be exactly one JSON object: a prompt echo, banner or `[end of text]` line makes the request `MALFORMED` (`not_json`), by design, because lenient extraction could pick up the example refusal JSON that the instruction frame itself contains. Whether the pinned binary stays quiet with `--no-display-prompt` is verified in PR-AI-111.
- **Strict offline [P: D8].** `ServicePolicy(strict_offline=True)` requires the operator's recorded attestation that an outbound firewall restriction exists (`attestation.py`). StableNew never creates, edits or inspects firewall rules and cannot prove egress denial from code; the readiness record says "attested by the operator, not verified by StableNew".
- **Shutdown.** `AiAssistService.shutdown` cancels an in-flight request and joins its tracked non-daemon worker. Wiring it into the shutdown coordinator is PR-AI-112.

## 5. Pinned runtime, registry, import and rollback (`manifests.py`)

- `config/managed_ai_runtime.json` pins runtime builds (archive SHA-256 and the SHA-256 of **every** loadable file); `config/ai_model_registry.json` pins model files. The runtime manifest ships empty (a build needs the SHA-256 of every loadable file, known only after an authorized import). The registry holds four **candidates** (`qualified: false`) whose sizes and SHA-256 are the Hugging Face LFS values reported on 2026-10-23, unverified locally; they are checked by `import_model` before anything is installed.
- A registry entry needs complete provenance (publisher repo and revision, packager repo and revision, converter, https source URL), SPDX licence, exact byte size and SHA-256. An incomplete entry is dropped and reported, never used [P: D4]. An unknown or mismatched hash is refused; there is **no operator override** [P: D6].
- `qualified` separates a registered candidate (usable only with `allow_candidate`, for the qualification harness) from a qualified entry (the only thing production may run).
- Import is a pure local-file operation: the file is hashed before it is read or unpacked, a runtime archive may contain nothing loadable or scriptable that the manifest does not list and hash, member paths are confined, symlinks and oversized archives are refused, and installation is a rename from a staging directory into a content-addressed directory under `%LOCALAPPDATA%/StableNew/ManagedAi` (`STABLENEW_AI_DIR` overrides). There is no download, no auto-update, no pip and no dependency resolution at inference time.
- The active pointer (`active.json`, atomic) records the runtime build, model hash and a size and mtime snapshot of every pinned file. Per-request verification compares the snapshot (fast); a deep check re-hashes everything. A same-size, same-mtime edit passes the fast check and is caught only by the deep check, so a deep verification belongs at import and before qualification runs.
- Rollback is repointing the active pointer to another installed build or model; previous directories are kept and nothing is deleted automatically.

## 6. Records and privacy (`events.py`) [P: D7]

The event record (`events.jsonl`) can hold only whitelisted short scalars: request id, kind, outcome code, reason code, elapsed time, character counts, a 12-character request digest, a 12-character model hash prefix, the runtime build id and the strict-offline flag. No prompt text, suggestion text, path or asset name can be stored, there is no consent switch, and no input/output pairs are captured. Logs carry the same restriction.

The file is a true **append-only** JSON-lines log, not a rewritten file (`src/utils/atomic_io.py` provides atomic *replacement*, which cannot express an append, so this log is the one deliberate exception to "persisted state goes through atomic_io"). Each record is one line written with a single OS-level append, so several `EventLog` objects and several processes (the application and a qualification harness) never overwrite each other. On POSIX that is `O_APPEND` plus `fsync`; on Windows the C runtime emulates `O_APPEND` by seeking then writing, which is not atomic across processes (a regression test lost 87 of 240 records with it), so the Windows path opens the file with `FILE_APPEND_DATA` only and `FILE_FLAG_WRITE_THROUGH`. A crash can leave a torn final line: readers skip any invalid line and the next append starts a fresh one. The file rotates by size (256 KiB, one `.1` generation kept). A write or locking failure is observable, never silent: `append` retries a transient `PermissionError` a few times, then returns `False` and logs a warning, and the request's outcome carries `details["event_log_failed"] = True` (the request itself is not failed). A record that `append` acknowledged with `True` is on disk in one piece; rotation (which needs the file to be free) is skipped, not forced, when another process holds it. The supported concurrency model is any number of writers in any number of processes on one local NTFS or POSIX file system; network file systems are not supported. Hidden-content redaction applies to the later GUI.

## 7. Qualification criteria for PR-AI-111 [P: D11, D5]

Not run yet [U]; the frozen plan, corpus, scorer and session driver are in `tools/qualification/ai111/` and the authorization request is in `PR-AI-111_Offline_Qualification.md`. A model is selected only from the frozen offline corpus, never from public benchmarks, and is compared pairwise against the deterministic baseline.

- **Baseline arms:** identity (authored text), the deterministic engine only, a trivial heuristic, then candidate models (initially Qwen3.5-9B and Qwen3.5-4B; GLM-4.7-Flash only with owned runtimes released because of its resident size).
- **Quality:** blind side-by-side operator preference whose lower 95% confidence bound beats the deterministic arm over at least 100 judged pairs; residual capability operations the engine would still apply; closed-list accuracy for target and workflow advice.
- **Safety (hard gates):** zero protected-token changes, zero out-of-list choices, zero accepted injected instructions, zero egress observed. **Refusal rate** = `REFUSED_BY_MODEL / (SUGGESTION + REFUSED_BY_MODEL + MALFORMED)` over in-scope lawful sensitive prompts, provisional target at most 5%; infrastructure failures are excluded from the denominator.
- **Latency and resources:** cold and warm seconds, prefill and decode rates, peak working set and commit, unchanged VRAM; median at most 20 s on CPU (proposal, owner-tunable).
- **Validity:** schema-valid rate with the grammar constraint, reported also without it.
- **Evidence limits:** a physical run needs named authorization for each download, for inference, and a quiet host; thresholds are frozen before any run.

## 8. Invariants that must not be broken

1. AI output is never an executable job; the package imports no queue, repository, job service, runner or NJR core (ratchet).
2. The deterministic engine and `ModelPolicy` remain authoritative; AI never edits authored intent without an explicit operator Accept into an editing buffer.
3. Nothing is downloaded, installed, resolved or run on import or at inference time; an unknown or mismatched hash is refused.
4. The child is CPU-only, offline by construction, contained, bounded, and spawned only after every gate passes.
5. AI yields to generation: refuse at admission, terminate while running; the service has no job-cancellation or queue authority.
6. A refusal is surfaced as a refusal and never sanitised, repaired or replaced.
7. Nothing derived from prompts is persisted beyond digests, counts and codes, and a prompt left on disk by a crash is swept before the next request.
8. A missing, malformed or non-finite provider reading is never read as idle or plenty, and nothing may escape the watch.

## 9. How to test

`tests/ai_assist/` (including `test_event_log_append.py`, which runs separate processes against one log, and Windows-only tests that prove job-object containment and fail-closed behaviour) is hermetic: a fake installation under `tmp_path` and a tiny Python script as the child, launched through the real `run_bounded` (so containment, timeout, cancellation and output caps are real); no model, GPU, network or display. Memory and activity are injected. `tests/tools/test_architecture_ratchets.py` covers the import rule and `tests/tools/test_operator_journey_ai_isolation.py` covers the journey isolation (disposable AI directory; only the two committed manifests readable; everything else under a protected directory still guarded). Process-tree termination is asserted for the direct child on every platform and for descendants only where containment is required (Windows); a Linux runner without a writable cgroup uses the explicitly reported uncontained fallback. Run `python -m pytest tests/ai_assist tests/tools/test_architecture_ratchets.py` first, then `python tools/ci/run_pr_gate.py`.

## 10. Known debt and traps

- Flag spellings, `--no-conversation`/`--reasoning off` handling and whether the pinned one-shot binary accepts `--json-schema-file` are unverified until PR-AI-111.
- Qwen3.5 thinks by default; the argv requests non-thinking and the framing asks for JSON only. Interaction with constrained decoding is unmeasured.
- Safety-tuned models may refuse or soften lawful sensitive prompts; the refusal rate is measured in PR-AI-111, not assumed.
- Priority and tree-memory handling are implemented in the AI layer (section 4, F2) but not yet proven against the real binary.
- The generation-activity provider, shutdown hook, controller service and GUI are not wired (PR-AI-112). A GPU mode or resident server would need a queue dispatch hold and a transition-coordinator lease (PR-AI-120, architectural).
- `STATUS.md` is at its line cap; keep this subsystem to one line there.
