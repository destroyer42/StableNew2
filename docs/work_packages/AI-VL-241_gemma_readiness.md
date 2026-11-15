# AI-VL-241: independent review of the visual driver, and Gemma 4 12B readiness (CPU, synthetic wiring run)

Status: **review and fixes delivered; the Gemma wiring run is prepared and awaits the owner's approval by digest (section 6).**
Nothing here qualifies a model. `qualified`, `production_eligible` and `text_registry_eligible` stay false for both
candidates, and a synthetic run is a wiring check, not quality evidence.

Execution class: Standard. Touches `tools/qualification/vl220/` (`driver.py`, `__main__.py`), tests and docs only.
`src/` (including `src/ai_assist/argv.py`), `contract.py`, `scoring.py`, `plan.py`, `config/` and every frozen identity (Qwen plans
`17814e40...` and `3017c427...`, corpus `a89297be...`, LFM3 contract `41e65d67...`, the LFM plan digest `15d7ab2e...`) are untouched.

**Model recommendation.** Claude Code Sonnet 5.5, high effort (code review against a written contract, bounded repairs, a
numeric envelope); no second host is needed. A lower tier would not reliably cross-read the contract, the runtime launcher and
the llama.cpp sources; a higher one adds nothing to a package this size.

**Controller Surface Assessment.** Not applicable: no `src/controller/`, `src/gui*`, queue, history, runner or compiler file is
touched. The canonical path (`Intent -> Compiler -> NJR -> JobService -> Queue/Repository -> PipelineRunner.run_njr -> Handler ->
Artifacts/History`) is not involved; the harness is an offline operator tool and stays outside it.

**Token-efficient validation plan.** Focused: `tests/tools/test_ai_vl241_review.py` plus the four existing VL driver files; then the
whole `tests/tools` folder and the canonical PR gate in an isolated worktree; CI is the integration verdict.

## 1. Scope and method

Reviewed on `main` at `bbc63978`: `driver.py`, `visual_argv.py`, `staging.py`, `candidates.py`, `diagnostics.py`, `__main__.py`
against `PR-AI-VL-220_Image_Invocation_Contract.md` (sections 2, 3, 7), the evaluation contract, the runbook, and the
launcher they call (`src/utils/managed_process.py`, `src/ai_assist/observe.py`, `host.py`, `attestation.py`, `argv.py`
`build_environment`). The Gemma pair's headers were read with a bounded, read-only GGUF key reader (no model was loaded and no
runtime started). llama.cpp facts come from the b11960 sources read as text.

## 2. Part 1: review findings (both candidates)

Severity is for this harness (an offline, operator-run, contained evaluation tool), not for the application. Lines are in the
post-fix `driver.py` / `__main__.py` unless marked "main".

| # | Sev | Finding | Where | Disposition |
|---|---|---|---|---|
| M1 | Medium | The Gemma-only watch killed a child when its **working set** passed the 12 GiB ceiling. A working set is not a commit: while llama.cpp reads Q4_0 weights into its own repacked buffers the mapped pages of the pinned file are also resident, so a healthy load can read near twice the weights. LFM3 shows the pattern (1.70 GiB private, 2.29 GiB peak working set for 1.38 GiB of files). For Gemma that is about 13 GiB against a 12 GiB kill, so the first case would very likely have been cancelled for a harmless reason. The real bound (job commit limit and the private-bytes cap, both 12 GiB) already exists. | `driver.py` `_Watch`, `working_set_tripwire_bytes` (main: `working_set_limit_bytes=resource.max_peak_working_set_bytes`) | **Fixed.** The tripwire is the ceiling plus the two pinned files (18.7 GiB), the most the files can add. Commit and private caps unchanged. Test `test_the_working_set_tripwire_is_the_ceiling_plus_the_pinned_files`, `test_the_private_bytes_cap_still_stops_a_child_that_commits_past_the_ceiling`. |
| M2 | Medium | Admission headroom for every candidate was the download plus 4 GiB (10.66 GiB for Gemma) for RAM **and** commit. A child at its planned private peak (9.0 GiB, section 3) would leave 1.7 GiB of commit and, on a busy host, trip the in-run guard (1 GiB, two consecutive readings) instead of being refused up front. | `driver.py` `memory_requirements`, `_memory_refusal` (main lines 546-558) | **Fixed.** Gemma needs 11.0 GiB available and 12.0 GiB commit headroom; LFM keeps the old rule. Refusal is `available_ram_below_requirement` / `commit_headroom_below_requirement`, row `not_run`, set stops. Tests `test_memory_requirements_keep_the_old_rule_for_lfm_and_plan_for_gemma`, `test_gemma_is_refused_cleanly_when_headroom_is_short_and_records_not_run`, `test_gemma_is_admitted_at_exactly_the_required_headroom`. |
| M3 | Medium | A launch that **proved no containment** (no job object, memory limit not read back, child not observable) was recorded as `launch_failed` and the set continued, so every remaining case repeated a 7 GB re-hash, ran nothing and was then scored as a wrong answer. A set of non-answers looks like a model result. | `driver.py` `run_cases`, `run_controls` (main lines 850-860) | **Fixed.** `launch_failed` is a stable refusal (`REFUSED_LAUNCH`, sub-reason kept); the set stops after the first such case. Test `test_a_launch_that_proves_no_containment_stops_the_set_instead_of_scoring_non_answers` (five outcomes), `test_a_gemma_child_that_cannot_be_observed_is_not_trusted`. |
| M4 | Medium | The per-case work directory (prompt and image copies) was removed with `shutil.rmtree(..., ignore_errors=True)` and never checked. A handle held by a just-killed child, antivirus or a crash would leave private bytes in the evaluation root with no signal, contrary to "removed when the case ends". For a non-synthetic set that is a copy of the operator's image and prompt. | `driver.py` `_run_case`, `_remove_work` (main line 654) | **Fixed.** One retry, then `cleanup_complete: false` in the evidence document and a non-zero CLI exit; the next case is refused (`scratch_unavailable: work_directory_not_empty`) while anything remains, which also catches a crash's leftovers. Nothing is deleted on the operator's behalf. Tests `test_a_work_directory_left_behind_stops_the_next_case_and_is_never_deleted_for_the_operator`, `test_a_work_directory_that_cannot_be_removed_is_reported_not_hidden`. |
| L1 | Low | The evidence file is written only after the whole run. Its folder was not checked first, so a missing folder lost a finished run to a traceback, and the location was not held to the rules the diagnostics file has (outside Git and outside the AI Assist root). Evidence and diagnostics could also be the same path. | `__main__.py` `_evaluate` (main lines 77-79, 173-177) | **Fixed.** Pre-flight before the first launch; a write failure is reported (`evidence_write_failed`, exit 1). Tests `test_the_cli_checks_where_the_evidence_goes_before_launching_anything`, `test_a_failed_evidence_write_is_reported_after_the_run`. |
| L2 | Low | The default per-case kill for every candidate was the contract's 180 s. For a 12B model on CPU that is the lower part of the estimated range (section 3.4); a kill discards exactly the measurement the run exists for. | `driver.py` `default_limits`, `DEFAULT_TIMEOUT_SECONDS` | **Fixed within the harness, no contract change.** Gemma defaults to a 300 s kill, LFM stays at 180 s; `--timeout-seconds` overrides, and the value is part of the execution identity the owner approves by digest. The plan's own proposed limit (`ResourceLimits.max_wall_seconds`, 180 s, in `plan.py`/`contract.py`, not mine) is unchanged, so a case slower than 180 s is **reported** as a resource violation although it was allowed to finish. Test `test_gemma_runs_under_its_own_timeout_and_the_operator_can_change_it`. |
| L3 | Low, accepted | Verify-then-load window: model, projector and runtime are re-hashed for every case (`check_admission`, `runtime_import_problem(deep=True)`) and the child loads them seconds later. Someone with write access to the evaluation root or runtime folder could swap a file in between. Both are operator-owned folders and the run is supervised, so the residual risk is the operator's own account. | `driver.py` `_admitted_run` | **Reported, not changed.** Closing it needs a file-handle lock or a copy-then-verify-then-launch-the-copy design (7 GB copy per case); that is a design choice, not a defect. |
| I1 | Info | The attestation binds `(build id, executable name)`, not a path; the Windows Block rule binds the absolute path. The driver proves the runtime at `<ai root>/runtimes/b11960-cpu-vision/` re-hashes to its pins and the attestation covers the pair, but cannot see that the rule covers that path. | `candidates`/`attestation.py` | Not a defect (documented, owner-attested). Verified read-only for this run in section 5. |
| I2 | Info | `--jinja` and the template. Verified: the only template control is the single `--jinja` switch (exactly once, only when `use_jinja` is true); `--chat-template`, `--chat-template-file`, `--chat-template-kwargs`, `--reasoning`, `--reasoning-format`, `--reasoning-budget`, `-rea` are refused by name and, being outside the allow-list, would be refused anyway. `build_environment` copies only six system variables, so no `LLAMA_ARG_CHAT_TEMPLATE*`, `LLAMA_ARG_JINJA`, `LLAMA_ARG_HF_*`, `LLAMA_ARG_MMPROJ*`, `LLAMA_CACHE`, `HF_*` reaches the child. The template therefore comes only from the `tokenizer.chat_template` key of the hash-pinned GGUF (18,681 characters in the Gemma file; read from its header). If a GGUF had no template llama.cpp would silently use a built-in one; the SHA-256 pin makes that impossible for the two pinned files. | `visual_argv.py` `check_visual_argv`; `argv.py` `build_environment` | Confirmed; new tests `test_the_jinja_switch_is_the_only_template_control_and_it_names_no_template`, `test_the_child_environment_cannot_inject_a_template_or_a_model_source`. |
| I3 | Info | Identity: model and projector re-hashed per case against catalog pins and GGUF headers (architecture, file type, embedding width, projector type, vision encoder, pairing by name); the runtime's 51 loadable files re-hashed, extra files refused; one `-m`, exactly one `--mmproj`, both resolved inside the evaluation root, images and prompt only in the private work directory; one or two images, PNG/JPEG signature, at most 8 MiB and 4096 x 4096 from a header read. | `candidates.py`, `staging.py`, `visual_argv.py`, `driver.py` | Confirmed (existing tests plus the new flag tests). |
| I4 | Info | Bounds: stdout 64 KiB (the valid response is at most 16 KiB; larger output kills the child), stderr 64 KiB, `-n` 768 (256 for a free-text control), `-c` 4096, prompt text at most 1000 characters plus 12 elements of at most 40 characters, wall-clock kill, `--prio -1`, launcher polls cancel every 50 ms and kills the whole job tree. | `visual_argv.py` `VisualLimits`, `contract.py`, `run_bounded` | Confirmed. |
| I5 | Info | Persistence: evidence holds timing, memory, exit code, path-free argv hash, reason codes and the aggregate score (counts and rates; `scoring.py` stores no answer string). Raw answers stay in memory. Stderr, the answer and the images are written only by an attached `DiagnosticCapture`, which cannot be constructed unless the case and label documents are exactly a built-in synthetic set with synthetic-by-construction labels. For any other set no answer text, prompt or runtime output reaches a file; the existing scan test and the new `cleanup_complete` check cover the work directory. | `driver.py` `evidence_document`; `diagnostics.py` | Confirmed. Nothing is written under the AI Assist root. |
| I6 | Info | LFM (non-strict) runs are contained by the launcher's Windows default and killed on private bytes over 6 GiB, but have no job memory limit (peak measured 1.70 GiB private). Gemma runs with a mandatory, read-back job commit limit of 12 GiB and refuses if the OS did not confirm it. | `driver.py` `_launch`, `_judge` | Acceptable for LFM at its measured size; stricter path unchanged. |

No finding needs a contract or security-boundary change, so none was stopped. Options for L3 if the owner wants it closed: (a)
accept (supervised, operator-owned folders); (b) have the driver launch from a verified private copy of the pair (7 GB of writes
per case, minutes added); (c) hold an exclusive no-write handle on the two files for the duration of the child (a Windows-only
lock in `driver.py`, no new process). I recommend (a) for the synthetic run and (c) before real-image evaluation.

## 3. Part 2: Gemma resource envelope on this machine (before any run)

Machine: i9-13900K (8 P + 16 E cores, `-t 8`), 31.8 GiB RAM, 92 GiB commit limit, NVMe D:, CPU only.

### 3.1 Inputs

| Quantity | Value | Source |
|---|---:|---|
| Model file | 6,975,879,296 B = 6.50 GiB | catalog, hash-verified (`verify-staging`: pair verified) |
| Projector | 175,115,616 B = 0.16 GiB (52 M parameters, no ViT blocks: the `gemma4uv` projector is a patch convolution plus projection) | GGUF header |
| Layers / heads | 48 layers; 40 sliding-window layers (window 1024, 8 KV heads, head size 256) and 8 global layers (1 KV head, head size 512); width 3840, FFN 15360, vocabulary 262,144 | GGUF header |
| Context in the plan | 4096 tokens | `VisualLimits` |
| Chat template | embedded, 18,681 characters, used through `--jinja` | GGUF header |

### 3.2 Memory

* **KV cache at 4096, f16.** Sliding layers keep about 1024 + 512 cells: 40 x 1536 x (8 x 256 x 2) x 2 B = 0.47 GiB. Global layers
  keep all 4096: 8 x 4096 x (1 x 512 x 2) x 2 B = 0.06 GiB. Total **0.53 GiB**; a full-size sliding cache would be 1.31 GiB (upper bound used).
* **Weights and compute.** Weights stay private (llama.cpp copies the Q4_0 weights into its own repacked buffers on this CPU):
  6.66 GiB with the projector. The LFM3-VL-2B runs measured the structure: 1.70 GiB private for 1.38 GiB of files (+0.32 GiB for
  compute buffers, KV and the process), 2.29 GiB peak working set (+0.59 GiB over private). Compute buffers scale with the FFN and
  vocabulary, so I allow 0.5 GiB.
* **Expected private bytes:** 6.66 + 0.53 + 0.5 + 0.2 = **7.9 GiB**; **planned upper bound 9.0 GiB** (full sliding cache, larger buffers).
* **Expected working set:** 8.5 GiB if the file's mapped pages are released after the load, up to about 13.7 GiB while the mapped
  file and the repacked copy coexist during the load (this is why M1 matters). Tripwire 18.7 GiB.
* **Uncertainty.** The repack-versus-mmap behaviour is inferred from the LFM measurement, not observed for Gemma; the first run
  settles it. A private peak above 9.0 GiB would be a surprise worth stopping on, and the 12 GiB job limit holds regardless.

### 3.3 Headroom to require at admission

| Check | Requirement | Reasoning |
|---|---:|---|
| Available physical RAM | **11.0 GiB** | planned private 9.0 + 2.0 margin; mapped file pages are reclaimable and not counted |
| Commit headroom | **12.0 GiB** | planned private 9.0 + the in-run guard's own kill threshold 1.0 + margin 2.0; equals the job limit, so the host can hold the worst case |
| In-run guard (unchanged) | available >= 0.25 GiB, commit headroom >= 1.0 GiB, two consecutive 1 s readings | stops a child that makes the host thrash |

Measured on this host while preparing (no Forge, no application running): about 11.8 GiB physical free and about 16 GiB commit
headroom (the pagefile is 60 GiB). That clears the gate narrowly; **Forge or the application running will not** (an earlier LFM
run was refused for commit headroom under that load), so they must be closed. A short reading refuses cleanly: `not_run`, the
refusal code in the evidence, the set stops, nothing is launched or scored.

### 3.4 Time per case (estimate, uncertainty stated)

The cost is the language model, not the vision encoder (52 M parameters). For `vl220-synthetic-512-2`: text prompt 700-950
characters (about 200-260 tokens) plus the turn template; images 512 x 512 become **121 tokens** each (see 3.5), the two-panel
1024 x 512 images 231 and before/after 242; so about **350-530 prompt tokens**, and an answer of about 60-150 tokens (a free-text control up to 256).

| Stage | Estimate | Basis |
|---|---:|---|
| Process start, load, Q4_0 repack, clip warm-up | 5-12 s | 6.7 GiB from page cache (just hashed) at memory speed; LFM's whole case took 4.2 s for 1.5 GB |
| Prompt processing | 6-20 s | 12B x 2 FLOP x 450 tokens = 11 TFLOP; 8 AVX2 threads, 25-60 tokens/s |
| Generation | 10-40 s | memory-bound: 6.5 GiB read per token, 35-65 GB/s achievable on 8 threads, 3.5-6 tokens/s |
| **Per scored case** | **25-75 s, median about 45 s; tail about 2 min** | factor-of-two uncertainty either way |
| Free-text control (256 tokens) | 50-100 s | |
| Re-hash of the pair per case (not in `wall_seconds`) | about 5 s | measured: `verify-staging` took 5.2 s |

Whole run (14 scored cases + 2 controls): **about 15 minutes (10-35 minutes)**; the theoretical worst case with every case at the
300 s kill is 80 minutes, and the run stops at the first refusal or cancel. Pinning of threads to P-cores is not done by the
harness, so E-core placement is a real downside risk to these numbers.

**Is a CPU deep tier practical? Before the run: probably yes for one explicit review, no for anything bulk.** The estimate is
**tens of seconds per image (30-90 s), about 1-1.5 minutes for a two-image comparison**: not seconds (LFM3-VL-2B is 4-6 s) and not
many minutes. That is tolerable for an explicit "deep review of this image" action with progress and cancel, and unacceptable for
scanning a gallery. The measured number replaces this estimate in section 7. It decides AI-GPU-440 as follows: if the measured median
is under about 90 s per case and no case needs more than 3 minutes, **speed alone does not force the GPU question to the owner**;
the stronger reason to ask is memory exclusivity (a deep review needs about 9 GiB of commit, so Forge must be closed, and a GPU
mode would instead contend with Forge for VRAM), which AI-GPU-440 already owns. If the median is over 3 minutes the GPU question must go to the owner.

### 3.5 Image token settings for Gemma (llama.cpp b11960 sources)

* `PROJECTOR_TYPE_GEMMA4UV` uses the dynamic-size preprocessor: the image is resized, keeping its aspect ratio, to a multiple of
  `patch_size x n_merge`, then clamped between `min_pixels` and `max_pixels`. For the `uv` projector the code multiplies the
  header's patch size (16) by the merge factor (3) and sets the merge to 1, so **one token is a 48 x 48 pixel cell**.
* Gemma's built-in token range is **70-1120** per image (`set_limit_image_tokens(70, 1120)`); `--image-min-tokens` and
  `--image-max-tokens` replace the bounds when they are positive; the clip warm-up uses 256 tokens and is capped by the custom maximum.
* The harness's `64` / `256` therefore means: images are scaled to between 147,456 and 589,824 pixels (up to 768 x 768) and give
  at most 256 tokens each. For the synthetic set that is 121 tokens (512 x 512 -> 528 x 528), 231 (1024 x 512 -> 1008 x 528) and 242 for
  a before/after pair; a 4096-token context is ample (largest request about 530 + 242 + 768).
* **Recommendation:** keep `64` / `256` for the wiring run (it bounds prefill time). A real-image evaluation of hands and faces
  will probably want 560 or more tokens, at about +6-10 s per image of prefill; that is a separate, owner-approved change of the
  execution identity, not part of this package. `--image-max-tokens` is owner-tunable and bounded to 1024 in `VisualLimits`.

## 4. What changed in the code

* `driver.py`: `memory_requirements` and `PLANNED_PRIVATE_GIB` (M2), `working_set_tripwire_bytes` (M1), `REFUSED_LAUNCH` and the
  stop in `run_cases`/`run_controls` (M3), `_remove_work`, `cleanup_complete` and the work-directory check (M4), `default_limits` and
  `DEFAULT_TIMEOUT_SECONDS` (L2), `cleanup_complete` in the evidence document, and moving one `assert` so the type checker is clean.
* `__main__.py`: evidence pre-flight and write handling (L1), `--timeout-seconds` for `evaluate` and `describe-execution` (L2),
  the cleanup report.
* `visual_argv.py`, `staging.py`, `candidates.py`, `diagnostics.py`: reviewed, no defect found, unchanged.
* `tests/tools/test_ai_vl241_review.py`: 20 tests. Run against the unfixed `driver.py` and `__main__.py`, 15 fail (the fixes M1-M4,
  L1, L2: for example a 12 GiB + 100 byte working set was cancelled and 11.9 GiB of commit was admitted); the other 5 pin behaviour
  the review confirmed rather than changed (the Jinja and template flags, the scrubbed environment, the verified memory limit and
  containment arguments, an unobserved child).
* Docs: this file, the runbook (Gemma envelope and `--timeout-seconds`), the invocation contract section 7 (admission, launch
  failure stops the set, cleanup).

## 5. Part 3: what was prepared, read-only, before asking

| Item | State |
|---|---|
| Pair verification | `verify-staging --candidate gemma-4-12b-it-qat-q4_0-google`: `pair_verified: true` (sizes, SHA-256, headers, pairing). Only reason it is not import-ready: `license_acknowledgement_missing`. |
| Licence | Catalog: Apache-2.0, `text_sha256` `cfc7749b96f63bd31c3c42b5c471bf756814053e847c10f3eb003417bc523d30`. The staged `LICENSE-2.0.txt` hashes to exactly that. The harness needs a record `{candidate_id, license_text_sha256, owner_acknowledged: true}`; **writing it is the owner's act**, so it is part of the approval below and is not created beforehand. |
| Runtime and attestation | The previous runs used evaluation root `D:\StableNew-Assets\offline-ai\vl220-eval` and the AI root `%LOCALAPPDATA%\StableNew\ManagedAi` (read only). Its `runtimes\b11960-cpu-vision\llama-mtmd-cli.exe` re-hashes to the pinned `5073109b...30b3a`; the attestation (2026-11-14T23:30Z) covers `(b11960-cpu-vision, llama-mtmd-cli.exe)`; the Windows rule `StableNew VL220 block llama-mtmd-cli outbound` is **Outbound / Block / Enabled** for exactly `C:\Users\rob\AppData\Local\StableNew\ManagedAi\runtimes\b11960-cpu-vision\llama-mtmd-cli.exe`. Gemma uses that same executable, so no new rule is needed. (The second copy under `D:\...\visual-evaluation\runtimes` has no rule and is not used.) |
| Import | Not done. After approval: `import --staging D:\StableNew-Assets\offline-ai\downloads\gemma4-12b --evaluation-root D:\StableNew-Assets\offline-ai\vl220-eval --acknowledgement <record>`; it re-verifies while copying 7.15 GB and refuses to overwrite. |
| Assets | The built-in set `vl220-synthetic-512-2` already exists at `D:\StableNew-Assets\offline-ai\vl220-synthetic-512-2` (14 cases); each image is re-proved against its pin before it is used. |

## 6. The run awaiting approval

* **Plan digest (Gemma):** `82cd8ce7ca98376bbe5564b380df2da5f616d9b393b8d37563c171f4946d3d70`
* **Execution digest:** `e0d125f5af941925d7591ab5f5636c05755af48148f5313a1f22ce70dcb425ed` (jinja, 64/256 image tokens, 300 s kill,
  12 GiB, plan above, runtime `5073109b...`); case digest `1306b33d2f17c57e0039880e3ed273380dbac9a85f43c85c849ea24dee1fc726`;
  label digest `277773917dc8dcfeaf3e76cfdef7729cede8e91c5b223356ce0d758fb55afd30`.
* **What runs:** the 14 scored cases of `vl220-synthetic-512-2` (4 adherence, 2 consistency, 4 defect triage, 2 before/after, 2
  describe) plus the 2 unscored free-text controls, 16 one-at-a-time CPU-only children of `llama-mtmd-cli.exe` with `--jinja`,
  `-ngl 0`, `--offline`, no GPU, scrubbed environment, 12 GiB job limit, diagnostics on (the set is built in and synthetic).
* **Expected:** about 15 minutes (10-35), about 9 GiB private memory and 8-14 GiB working set per child, one child at a time.
* **Saved** under `D:\StableNew-Assets\offline-ai\vl220-evidence\`: `run4-gemma-512v.json` (timing, memory, exit codes, argv hash, scores)
  and `run4-gemma-512v.diagnostics.json` (raw answers and bounded runtime output of synthetic scenes). Nothing is written under
  `%LOCALAPPDATA%\StableNew\ManagedAi`; the work directory `vl220-eval\_work` is emptied per case.
* **Preconditions:** no generation running, Forge and the StableNew application closed (the gate needs 11.0 GiB available and 12.0
  GiB commit headroom), the owner's licence acknowledgement recorded.

## 7. Run result and comparison

Pending the owner's approval. Section to be completed after the run with the per-kind table next to LFM3-VL-2B run 3
(adherence 1.0, describe recall 1.0 and exact at 512 px, consistency 0.75, defect triage recall 0.67 / precision 0.22 with the clean
figure flagged, before/after 0.5 legacy and 0.0 jinja, 28 of 28 valid, median 4.2-4.6 s, peak working set 2.46 GB).

## 8. Acceptance and evidence boundary

* **Implementation:** review fixes M1-M4, L1-L2 and the Gemma envelope in the harness, with 20 deterministic tests.
* **Demonstration:** the new tests, the existing VL tests, the `tests/tools` folder and the PR gate; read-only verification of the pair, the
  runtime hash, the attestation and the firewall rule.
* **Qualification:** none. Both candidates stay `qualified: false`.
* **Unverified or held:** Gemma has never been run; its memory, time, template rendering, grammar behaviour and answers are
  estimates until the supervised run; synthetic scenes are a wiring check, not evidence about real generated images; real-image
  evaluation with human labels (and the Gemma image-token budget for it) is a separate package; L3 is accepted, not closed.
* **Owner decisions pending:** approval by digest (section 6) and the licence acknowledgement; the AI-GPU-440 question after the measured time.
