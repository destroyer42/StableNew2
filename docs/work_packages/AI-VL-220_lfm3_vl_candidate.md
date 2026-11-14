# PR-AI-VL-220: LFM3-VL-2B visual candidate and offline evaluation

Status: **implemented on a feature branch; PR open, not merged; nothing promoted.** (The image invocation it specified was
implemented afterwards; see "Image invocation implementation" at the end.) The visual candidate is recorded, its two
files are staged and hash-verified outside the repository, and an evaluation contract plus harness scaffolding exist. **No
model, binary or projector was loaded or run.** The image invocation a real run needs is a separate proposal that needs the
owner's explicit approval (`docs/Subsystems/AiAssist/PR-AI-VL-220_Image_Invocation_Contract.md`).

## Objective

- Outcome: LFM3-VL-2B prepared as an unqualified, first-party, provenance-pinned **visual** candidate and comparator, with an
  operator staging/verification workflow and a read-only deterministic evaluation contract, while the Qwen3.5 and LFM3 text
  registrations and every runtime and security boundary stay as they are.
- In scope: `config/ai_visual_candidates.json`; `tools/qualification/vl220/` (candidate parser and fail-closed admission, bounded
  GGUF header reader, staging/verify/import, contract, synthetic assets, scoring, plan); tests; the evaluation and invocation
  contract documents; the staging runbook; this document; one line each in `STATUS.md`, `docs/CODEX_MAP.md`,
  `docs/Subsystems/AiAssist/AI_ASSIST.md` (invariant 10, section 13) and the qualification README inventory.
- Explicit exclusions: any change to `config/ai_model_registry.json`, `config/managed_ai_runtime.json`, `src/`,
  `FORBIDDEN_FLAGS`, `ALLOWED_FLAGS`, `build_argv`, the selector, Preview, activation or `import-model`; importing anything into
  `ManagedAi`; running any llama.cpp binary or model; GPU work; firewall rules; qualification; the image invocation itself.

## Execution class and model recommendation

- Execution class: **Standard** (new isolated harness and records; no architecture or production change; the one material
  decision, the image invocation, is held for the owner).
- Execution location: Local.
- Model recommendation: Claude Code Sonnet 5.5, high effort (substantial but known architecture; one coherent package);
  Codex GPT-6.1 Sol High equivalent per `docs/AI_MODEL_SELECTION.md`.
- Expected usage: about 10M cache-read and 60k output tokens (the owner's estimate).

## Exact start state and authorities

- Task-start timestamp: **2026-11-14T10:54:06-05:00** (recorded before discovery). Session: this top-level Claude Code session
  (id in the PR body), started by the orchestrating session `local_ded6f184-9d33-48d3-876e-43da15db7f73`; no subagents.
- Repository and branch: `destroyer42/StableNew2`, `claude/ai-vl-220-lfm3-vl-candidate-c7104b`, worktree
  `.claude/worktrees/ai-200-preview-tier-04aca4`.
- Start SHA: the branch started at `ba108e1f` (clean) and was fast-forwarded to `origin/main` `56187fcf` (PR #307, AI-202b), which
  the brief requires; the diff against `origin/main` was empty before editing.
- Python: the repository venv `C:/Users/rob/projects/StableNew-main/.venv/Scripts/python.exe` is **Python 3.14.9**.
- Canonical docs consulted: `AGENTS.md`, `STATUS.md`, `docs/CODEX_MAP.md`, `docs/AI_MODEL_SELECTION.md`,
  `docs/CODEX_WORK_PACKAGE_TEMPLATE.md`, `docs/Subsystems/AiAssist/AI_ASSIST.md`, `AI-202_invocation_and_selector.md`,
  `PR-AI-115_LFM3_Qualification_Contract.md`, the AI-111/AI-115 contract code, `src/review/assist/` (Smart Review).

## Surface assessment

- Controller or coordinator surface touched: **No.** Controller Surface Assessment: none; no controller, coordinator, GUI or
  `src/` file changes, so no ratchet ceiling moves.
- Architecture authority or invariant changed: **No.** The canonical path (Intent -> Compiler -> NJR -> JobService -> ...) is
  not involved; AI output stays advisory and the visual candidate is unreachable from the application.

## 1. Audit (requirement 1)

* **Existing multimodal capability.** Smart Review (PR-IMG-REVIEW-320, `src/review/assist/`) runs SAM2 (segmentation) and
  Florence-2 (caption) as Python children (torch/transformers, CPU, offline) over catalog resources verified by the
  PR-ASSET-130 registry. It has nothing to do with llama.cpp. **No Qwen multimodal capability exists in StableNew:** the four
  Qwen3.5 GGUFs are registered as text models, no projector is registered, and `--mmproj` is in `FORBIDDEN_FLAGS`. A
  Qwen3.5 visual arm would need its own projector pin, license review and invocation approval.
* **Import infrastructure.** `import_model` hashes and copies a registered entry into a content-addressed directory; the
  selector (AI-202b) lists every imported and verified registry entry; Preview enablement and `activate` take registry entries.
  Each treats an entry as a text model.
* **Modality contract.** The brief states it unambiguously: a visual candidate and comparator, evaluated offline, not
  production. No owner stop was needed for requirement 1.
* **D22 confirmed.** A visual entry in the text registry would be offered by the selector for text use, so the registry
  semantics were not changed and a separate candidate file was used. A test proves nothing in `src/`, the admin tool or the
  runtime/registry configs reads it, that the selector lists nothing for it even if its bytes sat in the AI root, and that
  `import-model` and `activate` refuse its id.

## 2. Provenance (requirement 2); everything below was read anonymously from huggingface.co on 2026-11-14

| Item | Value |
|---|---|
| Publisher repository / revision | `LiquidAI/LFM3-VL-2B` @ `23387beda43c60310348e83e25f78f33c3140d3a` (public, not gated; weights unchanged since the first commit, later commits are documentation) |
| Packager repository / revision | `LiquidAI/LFM3-VL-2B-GGUF` @ `1add221a5ea6c047fcf1eaaf2d247939d7cf8849` (public, not gated, first-party Liquid AI) |
| Model file | `LFM3-VL-2B-Q4_K_M.gguf`, 1,099,627,808 bytes, SHA-256 `56dac2e192ff0d9ab8507f4f1aeb4aed0463449bbbefaac79497f041c95f21eb`; GGUF header: architecture `lfm3`, file type 15 (Q4_K_M), embedding length 2048, context 128000 |
| Projector file | `mmproj-LFM3-VL-2B-F16.gguf`, 378,996,032 bytes, SHA-256 `1d8e6e58eefc093e09d6332f081516e1ddbd5b35cfca7f35463fb270db230b1e`; GGUF header: architecture `clip`, type `mmproj`, `lfm3vl` projector, F16, projection dimension 2048 |
| Why this projector | It is "matching" in three verified senses: the same repository revision, the same declared base model and name, and a projection dimension equal to the language model's embedding length; the publisher says every `mmproj` in the repository is used unchanged across language-model quantizations and benchmarks a Q4 language model with an F16 projector. F16 keeps the vision front end from being a second quantization variable. **Choice for the owner:** llama.cpp's own `-hf` auto-pick for a Q4 tag would choose the Q8_0 projector (nearest quantization); Q8_0 (`c5c5b58d...`, 203,031,872 bytes) and BF16 (`8e75a88a...`, 378,996,032 bytes) are listed, not downloaded, not approved |
| License | LFM Open License v1.0 (`license: other`, name `lfm1.0`); text SHA-256 `30adf9d6478191fb87f2424f63ba0728598335aaf99cd2848ef17e8e545fe94b`, 10,574 bytes. **Same terms as the text acknowledged for LFM3-1.7B (`4d28ca14...`, AI-QUAL-115) but different bytes (a trailing space and a final newline), so that acknowledgement does not name it.** Section 5 conditions commercial use by an entity on staying under USD 10,000,000 annual revenue |
| Required runtime | **`b11960-cpu` only.** The publisher's card requires b11960 or newer; llama.cpp source at tag `b11960` has the `lfm3vl` projector and tag `b11840` does not (`tools/mtmd/clip-impl.h`). `llama-mtmd-cli.exe` is already hashed in the pinned `b11960-cpu` file map (`5073109b...`) |
| Converter | Liquid AI GGUF export; the converter build is not stated in the repository metadata (the same wording the LFM3 text entries use) |
| Vendor claims | Not relied on. Their benchmarks and speed tables establish nothing about StableNew quality |

**Download and verification (authorization recorded below).** Exactly the two files above were downloaded anonymously with `curl`
(no token or account; the repository is not gated and no terms were accepted) from the pinned-revision `resolve` URLs into
`D:\StableNew-Assets\offline-ai\downloads\lfm3-vl-2b\` (1,478,623,840 bytes, well under the 6 GiB ceiling; nothing else was
downloaded). Both files matched the pinned byte size and SHA-256 exactly. Their GGUF headers were read as plain bytes (no model
load, no binary). Records kept outside Git in that folder: `download_verification.json` and
`license_acknowledgement.TEMPLATE.json` (an **unsigned** template: `owner_acknowledged` is `false`).

## 3. Operator workflow (requirement 3, D15)

`docs/runbooks/ai_vl_candidate_staging.md`: print pinned `curl` commands, `verify-staging` (hashes, headers, build pin), the owner's
license acknowledgement, and an explicit `import` into an **evaluation root** the operator names (never `ManagedAi`, never a Git
working tree, never overwrites, cancel-safe). The application downloads nothing; the tool imports no network or process module.
`import` is documented as held until the driver exists (the owner approved the invocation contract on 2026-11-14, see below). Nothing was imported anywhere.

## 4. Evaluation contract (requirement 4)

`docs/Subsystems/AiAssist/PR-AI-VL-220_Visual_Evaluation_Contract.md` and `tools/qualification/vl220/`: cases without
reference data, separate labels (human-written whenever a non-synthetic asset is used), a closed two-branch response schema,
deterministic scoring for prompt adherence, anatomical defect triage, multi-subject consistency, before/after usefulness,
hallucination, structured-output validity and memory/runtime limits, an explicit comparator eligibility table (deterministic
floors; Smart Review's Florence-2 for hallucination only; the Qwen3.5 and LFM3 text models and SAM2 ineligible with reasons),
13 synthetic cases whose PNG bytes are byte-deterministic, and a plan with a digest. It runs no model.

## 5. Security and boundary findings (requirement 5)

The candidate document refuses any flag that claims qualification, production use, text-registry use or an approved invocation;
the package contains no `--mmproj`, `--image`, process, network or inference import (scanned by a test); admission is
fail-closed on any problem or exception; `FORBIDDEN_FLAGS`, `ALLOWED_FLAGS`, `build_argv`, `build_production_argv`, the process
authority, the attestation and the validators are untouched (`git diff origin/main` shows no `src/` change). The image invocation
is specified, not implemented, in `PR-AI-VL-220_Image_Invocation_Contract.md`: tool `llama-mtmd-cli.exe`, a separate hash-identical
build entry `b11960-cpu-vision` so attestation stays one executable per build, a closed visual vocabulary that is the only place
`--mmproj` could appear, the existing `run_bounded` launcher, fail-closed admission, CPU only. It also records that
`llama-cli.exe` in b11960 has client/server sources not reviewed for sockets, and that `mtmd-cli` applies a chat template, so a
visual result is not raw-prompt comparable with the text models.

## Acceptance and evidence boundary

- **Implementation (delivered):** items under "In scope".
- **Demonstration (deterministic tests, `tests/tools/test_ai_vl220_candidate.py`, `test_ai_vl220_contract.py`):** provenance and
  revision pinning; refusal of 23 malformed or over-claiming candidate documents; missing, wrong-size, wrong-hash and
  non-matching projector; wrong model header; unsupported, unknown, tool-less and qualified runtime builds; license
  acknowledgement missing/mismatched; fail-closed admission on unexpected errors; cancellation (hashing and copy) leaves nothing;
  import refuses `ManagedAi`, Git trees and overwrite; the registry is unchanged in meaning and nothing in `src/` reads the
  candidate file; selector, `import-model` and `activate` ignore it; no network or process use (AST scan and with sockets and
  `Popen` patched to fail); the frozen flag vocabulary still refuses projectors; schema invalidity (21 case, 12 label and 24 response
  refusals); scoring (oracle, floors, hallucination, invalid and missing answers, resource limits); a deterministic plan whose
  digest is in the evaluation document.
- **Qualification:** none. `qualified` is false everywhere.
- **Held / unverified:** that `llama-mtmd-cli.exe` of `b11960-cpu` loads this model and projector, its CPU memory and speed, the
  template question (`--jinja`), grammar behavior in `mtmd-cli`, the right `--image-max-tokens`, and any quality claim; the
  Florence-2 comparator's catalog resource state; the license acknowledgement (the owner's act); the real-asset case set and
  labels.

## Existing evidence reused

The frozen AI-111/AI-115 digest tests (`tests/tools/test_ai111_final.py`, `test_ai115_lfm3_contract.py`,
`test_ai115b_contract_harness.py`, `test_ai115b_repair.py`, the system840 tests) were run **unmodified** and pass; the Qwen
screening plan `17814e40...`, final plan `3017c427...`, corpus `a89297be...` and LFM3 `FROZEN_CONTRACT_SHA256` `41e65d67...` did
not move because the registry and the argument vocabulary were not touched.

## Owner decisions required

1. Approve, change or decline the image invocation contract and the `b11960-cpu-vision` build-entry approach.
2. Acknowledge the exact license text (`30adf9d6...`) in a record you write; a template is staged.
3. Confirm the projector (F16, or Q8_0 as llama.cpp would pick) and the proposed limits.
4. Choose the existing assets and the person who labels them, and whether Florence-2 is a comparator.
5. Authorize a first supervised CPU-only run by plan digest (a later package; this PR authorizes none), and create the
   `llama-mtmd-cli.exe` outbound Block rule yourself.

## Owner decision after review (2026-11-14, from the chat)

Owner statement (verbatim): "A: Approve. B: Approve. C: Authorize". Decisions 1 (invocation contract and the
`b11960-cpu-vision` build-entry approach) and 5's run authorization are now given for the first supervised CPU-only run, naming
plan digest `23df6fa4...880e`; this PR changes only documentation and one test assertion to record that. Still open and not
done by this PR: the license acknowledgement (decision 2), the projector and limits confirmation (3), the real assets and
labeler (4), the owner's `llama-mtmd-cli.exe` firewall rule and attestation, and the implementing package (manifest entry,
visual argument builder, driver reusing `run_bounded`, tests). `INVOCATION_APPROVED` stays `False` until that package lands.

## Stop conditions

Higher class or architecture decision discovered: none beyond the held image invocation. Scope expansion: running the model,
adding `b11960-cpu-vision` to the manifest, or a Qwen visual arm would each be a new package.

## Documentation impact

`STATUS.md` one clause on the existing AI Assist line; `docs/CODEX_MAP.md` the AI Assist row; `AI_ASSIST.md` invariant 10 and
section 13; `tools/qualification/README.md` inventory row; no roadmap or architecture change.


## Image invocation implementation (follow-up package, 2026-11-14)

Outcome: the owner-approved image invocation contract is implemented and has never been run. Delivered: the pinned build entry
`b11960-cpu-vision` (same archive and per-file hashes as `b11960-cpu`, `llama-mtmd-cli.exe`, unqualified, listed by no model);
the closed visual vocabulary and builder `tools/qualification/vl220/visual_argv.py` (the only place `--mmproj` or `--image` can
be emitted; `src/ai_assist/argv.py` is byte-identical); the question text `prompts.py`; the driver `driver.py` (launches only
through `run_bounded`, scrubbed `build_environment`, fail-closed admission before every launch, stdout-only strict JSON then
`validate_response`, evidence of timing, memory, a path-free argv hash, exit code and reason code, no text persisted); the
`evaluate` CLI command that needs `--i-have-the-plan-digest`; `contract.INVOCATION_APPROVED = True` with the new plan digest
`fa63304dc98e6aeb0eeb8e7d922cc61d23507ef58fb4994232bd723e9e66339a`, proved to differ from the authorized
`23df6fa436f4e4292b4421e5155ee232729ea1b4942ff8b6807b50dbc755880e` only by that flag and the comparator reason text; the
documents; `tests/tools/test_ai_vl220_invocation.py`.

Explicit exclusions kept: no llama.cpp binary or model was executed; no GPU; nothing written under
`%LOCALAPPDATA%\StableNew\ManagedAi`; no firewall rule, no attestation, no license acknowledgement (all the owner's acts); no
change to the text registry, the selector, Preview, activation, `import-model`, `FORBIDDEN_FLAGS`, `ALLOWED_FLAGS`,
`build_argv`, `build_production_argv` or any frozen AI-111/AI-115 identity (their digest tests pass unmodified).

Held, still the owner's before the first supervised CPU-only run: `license_acknowledgement.json` for text
`30adf9d6478191fb87f2424f63ba0728598335aaf99cd2848ef17e8e545fe94b`; the outbound Block rule for `llama-mtmd-cli.exe` and the
attestation for `b11960-cpu-vision`; the evaluation-root import; for existing assets, the chosen images and a human labeler; and
the owner's confirmation in chat naming the current plan digest. Unverified without that run (contract section 5): that the
tool loads this model and projector, memory and speed, the chat-template question (`--jinja`), grammar behavior in `mtmd-cli`,
whether stdout carries only the answer, and the right `--max-image-tokens`.
