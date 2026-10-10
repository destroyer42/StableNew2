# PR-IMG-MODELS-154B — Controlled one-case physical qualification harness: Z-Image-Turbo FP8-scaled

Disposition: **`HARNESS_VALIDATED_NO_PHYSICAL_RUN`** (local branch; independent review and hosted CI pending). The executable
capability exists, is disabled by default and has **never been run against a real runtime**. No Forge was started, no model
was selected or loaded and no image was generated. The first physical execution needs its own explicit owner authorization.

Execution profile: Standard, high-risk qualification-specific lifecycle work (`tools/qualification/img154b/`, small edits to
`tools/qualification/img154/`, no production `src/` change). Claude Code Sonnet 5.5 XHigh / Codex GPT-6.1 Sol XHigh, Windows
Local/Desktop, one top-level session. Controller Surface Assessment: no controller touched; no production controller or process
manager was changed (the existing `WebUIProcessManager` is reached only through PR-IMG-115's `OwnedForge`).

Canonical production execution is unchanged:
`Intent -> Compiler -> NJR -> JobService -> Queue/Repository -> PipelineRunner.run_njr -> Handler -> Artifacts/History`.
This harness is a deliberately isolated hardware-qualification tool and is **not** an alternative production execution path:
no queue, runner, history, compiler, PromptPack, profile or GUI authority is added.

## Execution boundary

| Capability | State |
| --- | --- |
| Import of any module | Pure. An audit-hooked subprocess test proves no process start, no network, no native-library load (beyond `import ctypes`'s own kernel32) and no write at import. |
| `python -m tools.qualification.img154b.cli` (default CLI) | `request`, `layout-plan`, `challenge`, `dry-run`. Offline or read-only. It cannot import the live module. |
| `physical preflight` | Read-only live preflight. Starts, selects and sends nothing; consumes no case. |
| `physical materialize --confirm-copy` | Copies the three verified files (about 14.5 GB) into the isolated layout. Filesystem only. **Not run.** |
| `physical execute` | The single physical case. Refuses unless: Windows, not under a test runner, `STABLENEW_IMG154B_PHYSICAL=ONE-CASE`, `--attempt-identity` equals the computed identity, an interactive TTY, an owner authorization record at the stable location, then a typed exact-case phrase. **Not run.** |
| `TECHNICAL_PASS_CONSTRAINED` | Reachable only with a `physical` execution authority that only the `execute` path can mint, plus complete evidence. A synthetic authority tops out at `INSTRUMENTATION_GAP`. |

Git authorization honoured: local branch, implementation, synthetic validation and local commits only; nothing pushed, no PR,
merge, release or worktree deletion.

## Request semantics: reconciled against the pinned source (`d70373eb`)

The 154A manifest froze Euler / Beta / 9 steps / CFG 1.0 / shift 9.0 / seed 424254 from the UI preset and flagged the model
card's `guidance_scale 0.0` as unreconciled. Reading the pinned source (every point is a textual anchor in
`request.PINNED_ANCHORS`, re-verified against the managed source at preflight; 23 anchors and 14 payload keys verified against
the installed tree, zero findings):

| Question | Pinned-source fact | Consequence |
| --- | --- | --- |
| Is there a `guidance_scale`? | No API key. `cfg_scale` is the sampler's `cond_scale` in `uncond + (cond - uncond) * cfg`. | The card's "guidance 0.0 / no CFG" is **`cfg_scale 1.0`** here: `setup_conds` sets `uc = None` and `sampling_function_inner` skips the unconditional pass (`math.isclose(cond_scale, 1.0)`). **Sending 0.0 would return the unconditional prediction and ignore the prompt.** The frozen 1.0 is correct and unchanged. |
| Where does shift go? | There is no `shift` key. `processing.sample` calls `sd_model.set_shift(shift=self.distilled_cfg_scale)`; Z-Image sets `use_shift`, not distilled guidance. | The payload carries **`distilled_cfg_scale: 9.0`**. The request model's pydantic default ignores unknown keys, so a `"shift": 9.0` key (what the 154A request fields named) would be silently dropped and the run would use the default **3.5** (neither the config's 3.0 nor the preset's 9.0). |
| Does shift reach the Beta schedule? | `create_sampler` -> `set_shift` -> `sampler.sample` -> `get_sigmas`; Beta reads `inner_model.sigmas`, a live property of the predictor that `set_parameters(shift=...)` rebuilds. | Yes, in that order (an ordered anchor proves the sequence). |
| Beta's parameters, sigma bounds, early-cond skips | Server options (`beta_dist_alpha/beta` 0.6/0.6, `sigma_min/max`, `rho`, `skip_early_cond`, `s_min_uncond*`, `always_discard_next_to_last_sigma`, `sgm_noise_multiplier`, `eta_noise_seed_delta`, `randn_source` CPU, `use_dynamic_shifting`, `face_restoration`, `tiling`, `forge_unet_storage_dtype` Automatic). | Not payload keys. Their pinned defaults are verified from `GET /sdapi/v1/options` before the selection and again after it. |
| Checkpoint and modules | `POST /sdapi/v1/options` routes `sd_model_checkpoint` and `forge_additional_modules` through `checkpoint_change` / `modules_change`; **an unknown module name is dropped silently**; weights load inside the generation request (`forge_model_reload`). | The selection is confirmed from the options read-back (exact served paths, exactly two modules) before any generation; selection does not load weights. |
| What proves the effective run? | The returned infotext states `Steps`, `Sampler`, `Schedule type`, `CFG scale`, `Shift`, `Seed`, `Size`, `Model hash` and `Module N`. | The adjudication compares every one to the frozen value. A dropped shift appears as `Shift: 3.5`. |

The sampling **values are unchanged**; only their API encoding was wrong in the 154A intent field list, so no new owner
decision or new intent version is required. The manifest's `semantics_status` is now `reconciled_pinned_forge_source` and
`UNRECONCILED_INTENT_FIELDS` is empty (the intent digest `03edcf1c...` is byte-identical to 154A's). Not reconciled and not a
payload key: the card's "9 steps = 8 DiT forwards" against this sampler's nine model evaluations is a step-accounting
difference that the frozen preset step count does not settle; it is an unknown, not a claim.

`build_txt2img_payload` is pure and refuses any intent other than the frozen one. The one request is:
`prompt, negative_prompt, seed, steps, sampler_name, scheduler, cfg_scale, distilled_cfg_scale, width, height, batch_size,
n_iter, send_images, save_images` (`save_images: false`; no `enable_hr`, `override_settings`, scripts, LoRA, reference or
upscale key).

## What was built

| Module (`tools/qualification/img154b/`) | Role |
| --- | --- |
| `request.py` | Pinned-semantics anchors and their re-verification, the immutable payload, the selection payload, option-default and selection read-back checks, infotext verification. |
| `fence.py` | Stable per-case record location, atomic `O_EXCL` claim, ordered stage records, ownership token. An extension of the 154A ledger, not a new authority. |
| `runtime.py` | Isolated layout, copy-based materialization, complete served-file proof, launch-profile validation, `OwnedRuntime` (manager-owned lifecycle adapter) and ownership facts. |
| `sampler.py` | Native providers (`GetPerformanceInfo`, NVML, one PDH query, DXGI adapter map, process-tree memory) and the bounded ~1 Hz sampler feeding `SafetyMonitor`. |
| `collector.py` | Assembly of the live preflight from injected readers; the 25-second quiescent-baseline window. |
| `authorization.py` | The exact-case owner authorization record (read, bound, expiring) and the confirmation phrase. |
| `case.py` | The one-case coordinator against ports; physical-authority gate; no real I/O of its own. |
| `adjudication.py` | Response validation, telemetry coverage, and the eight-class result classification. |
| `bundle.py` | Raw and redacted evidence bundle, exclusive-create, hashed index. |
| `cli.py`, `physical.py` | The default non-live CLI and the single, gated live module (HTTP client, real wiring). |

Edits to 154A modules (all re-tested; the 154A suites are unchanged and green): `evidence.py` (`append_exclusive`, ordered
`LEDGER_STAGES`, `record_stage`, `stage_history`, an existing-but-empty ledger file is `unknown`), `preflight.py`
(`validate_quiescent_baseline` and the baseline-relative rule becoming assessable), `manifest.py` (semantics status, revision
labels), `report.py` (one residual-risk text and one checklist line).

## Preflight and authorization boundary

`evaluate_preflight` (154A) is consumed unchanged for the thresholds and is **not** permission to run. The live path also needs:

* **Exact-case owner authorization** recorded outside the package (`<attempt identity>.owner-authorization.json` in the stable
  record directory), bound to the case identity, manifest digest, payload digest, request-semantics revision, policy and
  evidence revisions, git SHA and the executed-source hash, naming `DIAG-GPU-130` among the accepted risks, scope one case and
  no retry, the exact statement and the exact challenge digest, valid for at most 24 hours. Nothing in this package writes one
  (an AST test enforces it) and the record cannot be cryptographically attributed to the owner; the controls are the exact
  binding, the expiry, the interactive typed phrase and the refusal under a test runner.
* **Trusted code revision**: a clean checkout with an identified SHA; the source hash covers `img154` and `img154b`.
* **Fresh, independently validated baselines**: a window of at least 20 samples over at least 20 s, ending within 60 s, taken
  by the harness's own sampler, bound to the NVML device digest and the boot identity of the launch reading, dedicated VRAM
  spread at most 128 MiB, shared memory spread at most 128 MiB, GPU utilization at most 15%, no model runtime present at the
  start and the end of the window. **These validation criteria are provisional harness judgments**, not measured limits.
  The 154A launch thresholds are unchanged and unrelaxed: commit headroom >= 37 GiB, available RAM >= 20 GiB, pagefile-volume
  free >= 30 GiB, dedicated VRAM <= baseline + 512 MiB.
* Exact served-file proof, resolved request semantics, verified managed-runtime marker (revision, status, Python minor),
  validated launch profile, complete required telemetry coverage, no competing or foreign runtime, no prior attempt (stable
  record **and** workspace ledger), the operator's typed phrase, then a **fresh re-measurement** (and device re-check) before
  the claim. A drop between assessment and claim refuses with nothing consumed.

## Atomic no-retry dispatch fence

* Identity: the owner `case_id` digest only. It is independent of policy revisions, request wording, repository SHA and
  workspace. The record lives under the per-user `StableNew\Qualification\IMG154_CASE_RECORDS`; a record location inside the
  workspace is refused.
* Claim: the attempt record is the first write of a per-case ledger file created with `O_EXCL`; exactly one process can ever
  create it (six real processes with different workspaces: one claim, five refusals). A stale pre-check cannot defeat it.
* Stages, each durable (fsync) before its action: `claimed -> managed_start_attempted -> startup_observed ->
  selection_attempted -> selection_confirmed -> generation_dispatched -> terminal_evidence` (`terminal_evidence` may end any
  open stage), then the outcome record. Skipped, repeated or reordered stages are refused; a failed record prevents the action.
* An interruption at any stage, a torn tail, a corrupt line, a missing claim record, a replaced record (lost ownership), an
  inaccessible location or an empty file is **ambiguous** and consumed; none is repaired or retried. A refused preflight or a
  lost claim race is not an attempt. PR-115's discretionary repair exception is not inherited.

## Lifecycle ownership

`OwnedRuntime` wraps PR-IMG-115's `OwnedForge` (`WebUIProcessManager`). Strict loopback port 7886 probe (occupied, timed-out
and unverifiable all refuse), an exact launch command (`--uv --api --port --data-dir --skip-install`, interpreter and working
directory pinned, inherited `COMMANDLINE_ARGS` neutralized because Forge appends it to its argv, caches redirected into the
isolated root, no model-reference flag), and an ownership check immediately before every runtime-changing step: manager
ownership, exact PID and unchanged start time, the process tree, and that every listener on the port is inside the owned tree.
There is no signal, kill, taskkill or other PID authority in the package (AST-enforced). If the manager-owned stop does not
return in time or leaves a survivor, the automation ends and prints operator recovery instructions.

## Telemetry: available and limited

Observed on this workstation by a 12.5 s read-only run of the real providers (no workload): 13 samples, cadence 0.988-1.014 s,
no overruns, median acquisition latency 0.45 ms (maximum 95 ms on the first read), every field `ok` including shared GPU memory
mapped through DXGI/PDH LUID to the NVML-identified GPU, hard-page rate from `\Memory\Pages Input/sec`, commit as exact
integer bytes. Per sample: monotonic and UTC time, sequence, latency, per-field status and provenance, stage and stage source,
endpoint state and ownership, owned-tree working set and private commit.

Limits: GPU identity assumes exactly one GPU whose name contains `RTX 4070 Ti` (zero or several is refused); sampling stops
being meaningful if the driver hangs; fault-event observation is a slow-cadence PowerShell diff (about 15 s), not a per-second
signal; only `denoise` is ever attributed (`state.sampling_step` demonstrably running with at least one further callback);
encoder load, transformer load and VAE decode have no verified signal and stay `unknown`. Stage-stall thresholds stay
inactive. The 80 C, 95% VRAM, low-memory and shared-memory stop thresholds remain provisional and are not validated
protection; a monitor stop is a request routed through the owned shutdown, and no software can recover a hung GPU driver.

## Stop, fault and result behavior

A latched `REQUEST_OWNER_STOP`, `CANNOT_VERIFY_SAFE_STATE` or `HARNESS_FAULT` persists its trigger, source, time and last
readings, halts progression, requests only the manager-owned shutdown, sends no second request and keeps an ambiguous
dispatch ambiguous. Two fresh clean samples are required after the selection and before the dispatch record. The single POST
runs in a worker thread supervised by the 1 Hz watchdog, so a blocking request cannot blind the monitor.

Classes: `PREFLIGHT_REFUSED`, `LOADER_FAILED`, `RESOURCE_ABORT_REQUESTED`, `AMBIGUOUS_DISPATCH`, `SYSTEM_OR_GPU_FAULT`,
`INSTRUMENTATION_GAP`, `OUTPUT_VALIDATION_FAIL`, `TECHNICAL_PASS_CONSTRAINED`. A pass needs the physical authority, a claim,
an observed startup, a confirmed selection, one decodable 1024x1024 non-constant image, the requested seed and effective
parameters (including the model hash and both modules), a verified clean owned shutdown with no unexplained survivor, a
recorded terminal ledger entry, complete telemetry (95% of samples per required field, no gaps, no sequence loss), a complete
evidence bundle and `NO_NEW_EVENTS_COMPLETE_COVERAGE` after the 120 s settle interval. It establishes one constrained
technical result, never stability, repeatability or production support.

## Validation

| Evidence | Result |
| --- | --- |
| New focused suites (`tests/tools/test_img154b_*.py`: request, fence, adjudication, preflight, runtime, sampler, case, collector, boundary) | all pass (see the counts in the completion report) |
| Unchanged 154A suites and PR-115/151/152/153 plus the WebUI process-manager ownership suites | pass |
| Mutation probes (15 high-risk rules: non-exclusive claim, skipped ownership, post-then-record, ignored confirmation, shift key, CFG 0, no-shutdown pass, ignored device mismatch, hard-link alias, authorization removed, unconditional shutdown verification, second POST budget, torn ledger as clean, unverified selection, no fresh-sample wait) | all killed (two survived the first run; the cross-process test was not sensitive to a stale pre-check and the shutdown test did not cover an unobserved tree, so two regressions were added) |
| Anchors against the installed pinned tree (read-only text) | 23 anchors, 14 payload keys, no findings |
| Real native providers, read-only, 12.5 s | all fields ok, cadence and latency as above |
| Live read-only preflight (below) | refused, as expected |

Opt-in checks (not run by default): `STABLENEW_IMG154B_FORGE_SOURCE=<managed source>` re-verifies the anchors;
`STABLENEW_IMG154B_NATIVE_SMOKE=1` reads the native providers.

## Workstation preflight disposition (read-only observation)

`physical preflight` on this host, code state dirty (uncommitted work), no isolated layout: **`REFUSED_ASSET_IDENTITY`**
(served files absent, config marker absent), with commit headroom 26.6 GiB (< 37 GiB), available RAM 16.1 GiB (< 20 GiB),
pagefile-volume free 285 GiB, dedicated VRAM 1,854 MiB of 12,282 MiB against a harness-acquired quiescent baseline of
1,854 MiB (delta 0), no competing runtime, port free, anchors verified. The thresholds were not relaxed. This refusal is an
acceptable package result; the host has not demonstrated the conditions, and the 154A observation that 37 GiB of headroom
needs a near-idle desktop (commit total at most about 12.8 GiB) still holds.

## Residual risks and what remains unproven

* `DIAG-GPU-130` black-screen / live-kernel recurrences are unresolved and unattributed; no monitor can recover them.
* Every numeric threshold and the baseline-validation criteria are provisional; the RAM stop rule is uncalibrated.
* The semantics are a source reading, never exercised; image quality, load time and peak memory are unknown.
* File provenance is exact bytes only; official provenance is unverified.
* The owner-authorization record's authorship cannot be proven in software.
* The dispatch is an hour-scale, single blocking request; the real HTTP path and the OwnedForge start have only been tested
  against fakes and a loopback test server.

## Readiness for a separate, owner-approved physical run

The harness is ready for review and, **if the owner then separately authorizes it**, a first run. Sequence: independent review
and hosted CI; owner decision on the residual risk; `physical materialize --confirm-copy` into an isolated root; a quiet
desktop meeting the unchanged thresholds; `cli challenge`; the owner records the authorization; `physical execute` in an
interactive terminal with the environment opt-in. A refusal at any gate consumes nothing.
