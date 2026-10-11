# PR-IMG-MODELS-154B — Controlled one-case physical qualification harness: Z-Image-Turbo FP8-scaled

Disposition: **`INSTRUMENTATION_GAP`** for the second owner-authorized physical case on 2026-10-10 (America/New_York).
The corrected launch environment started Forge and generated one valid image. Shutdown was not verified clean at the
recorded check; a later observation found no recorded PID or listener, but does not establish PASS. Both cases are consumed.

Execution profile: Standard, high-risk qualification-specific lifecycle work (`tools/qualification/img154b/`, small edits to
`tools/qualification/img154/`, no production `src/` change). Claude Code Sonnet 5.5 XHigh / Codex GPT-6.1 Sol XHigh, Windows
Local/Desktop, one top-level session. Controller Surface Assessment: no controller touched; no production controller or process
manager was changed (the existing `WebUIProcessManager` is reached only through PR-IMG-115's `OwnedForge`).

Canonical production execution is unchanged:
`Intent -> Compiler -> NJR -> JobService -> Queue/Repository -> PipelineRunner.run_njr -> Handler -> Artifacts/History`.
This harness is a deliberately isolated hardware-qualification tool and is **not** an alternative production execution path:
no queue, runner, history, compiler, PromptPack, profile or GUI authority is added.

## Captured first-case physical result: `LOADER_FAILED`

The executed checkout was clean SHA `df4b518a0cacdc159272cd64afa38fe7d4cf791f`, source SHA-256
`66298a85767d86a5636933bdb7bc5572538821dffbcc5fed984309f325b9e144`. Case identity
`471c18ba071aa54a2f7cebc26c101f78c8fea1f5a3fe0acd4792ff5772827231` was claimed at
2026-10-11T01:13:56Z (2026-10-10 21:13:56 America/New_York) after the owner's interactive confirmations.
The three served copies had exact verified bytes and hashes. The fresh claim-boundary preflight was
`PREPARED_FOR_OWNER_REVIEW`: commit headroom 41.92 GiB, available RAM 21.48 GiB, pagefile-volume free 267.93 GiB,
VRAM 1,053 MiB against a 1,061 MiB quiescent baseline. Limits and the frozen request were unchanged.

Durable stages were `claimed -> managed_start_attempted -> terminal_evidence`. The console recorded
`[Error] uv is not installed...`; the pinned Forge `modules_forge/uv_hook.py` emits this on `FileNotFoundError` from
`subprocess.run(["uv", "--help"])`. This establishes that the launched environment could not find the executable,
not whether it is installed elsewhere on the workstation. Ownership verification refused because the owned root no longer
existed. There were zero selection/generation requests and no output. The result is a runtime bootstrap failure, not a
Z-Image-Turbo model or GPU qualification verdict.

Manager-owned shutdown was `verified_clean`, with no reported survivor; a subsequent read-only check found no qualification
process or port 7886 listener. Telemetry was complete (138 samples; maximum gap 1.03109 s). After the 120-second settle,
fault observation reported `NO_NEW_EVENTS_COMPLETE_COVERAGE`, with no boot change or new records. These observations
establish neither stability nor production support.

Evidence is preserved locally under
`%LOCALAPPDATA%\StableNew\Qualification\IMG154B_ZIMAGE_TURBO_FP8\evidence\case-471c18ba071a-20261011T011152Z`:
`case-report.redacted.json`, `samples.jsonl`, the hashed `index.json`, and `redacted/console_tail.txt`.
The stable no-retry ledger remains consumed. No `uv` installation or environment repair was performed in that attempt.
The owner subsequently authorized the bounded launch correction and distinct second case below; this ledger was not reset.

## Captured second-case physical result: `INSTRUMENTATION_GAP`

The executed checkout was clean SHA `a4ee0464d92cd512923530ced8181fe97fec717e`, source SHA-256
`c4ec1aa3545d864cf1de9f52cdd36de80f6c4f133bc26be5d5511d84230b0b15`. Case
`df34833e09d1fbcab744b33412affd8aa431549bf9c6ad25e100d8e5794fb9d3` passed the owner's interactive confirmation
and fresh claim-boundary preflight at 2026-10-11T01:48:00Z: commit headroom 41.87 GiB, available RAM 21.47 GiB,
pagefile-volume free 265.05 GiB, VRAM at its 1,105 MiB baseline. The assets, request and limits were unchanged.

Every durable stage was recorded through startup, confirmed selection, generation dispatch and terminal evidence.
Forge returned HTTP 200 and one decodable, nontrivial 1024x1024 image; seed 424254, effective infotext and model/module
identities all passed validation. `artifacts/output.png` is 937,523 bytes, SHA-256
`871ee082e875ed0f89c9b758f95a3510499ebab2aa653e1e89422d0cda67bd06`. Visual quality remains unreviewed.
The report's per-HTTP `requests` array is empty; the preserved ledger, console and validated output establish execution.

The monitor did not halt. Telemetry was complete (187 samples, maximum gap 1.02062 s), and the 120-second settle fault
check reported `NO_NEW_EVENTS_COMPLETE_COVERAGE`, no boot change or new records. Manager-owned stop returned, but its
shutdown snapshot reported 20 surviving PIDs: `requested_unverified`, `verified: false`. The required clean-shutdown and
no-survivor facts therefore remained false, producing `INSTRUMENTATION_GAP`; this is not qualification PASS.

At 2026-10-11T01:52:26Z, a separate read-only process/port observation found none of the recorded root/survivor PIDs and
no port 7886 listener. This later observation does not prove absence at the original verification time or change its verdict.
The supplemental observation is outside the frozen bundle, in the local temporary retry package's
`post-run-process-observation.json`; no process was stopped or restarted by that observation.

Evidence is preserved under the same qualification evidence root at `case-df34833e09d1-20261011T014521Z`.
All 45 indexed files were rehashed without mismatch. Both ledgers and original bundles remain unchanged and consumed.
The executed harness/tests are evidence-frozen. No third attempt, environment installation or further runtime repair occurred.

## Execution boundary

| Capability | State |
| --- | --- |
| Import of any module | Pure. An audit-hooked subprocess test proves no process start, no network, no native-library load (beyond `import ctypes`'s own kernel32) and no write at import. |
| `python -m tools.qualification.img154b.cli` (default CLI) | `request`, `layout-plan`, `challenge`, `dry-run`, `passphrase-verifier`. Offline or read-only. It cannot import the live module. |
| `physical preflight` | Read-only live preflight. Starts, selects and sends nothing; consumes no case. |
| `physical materialize --confirm-copy` | Copies the three verified files (about 14.5 GB) into the isolated layout. Filesystem only. **Completed with exact served-file proof.** |
| `physical execute` | One separately authorized case per identity. Refuses unless: Windows, not under a test runner, `STABLENEW_IMG154B_PHYSICAL=ONE-CASE`, `--attempt-identity` equals the computed identity, an interactive TTY, an owner authorization record at the stable location, then a typed exact-case phrase and the owner's passphrase (no echo). **Case 1 consumed as `LOADER_FAILED`; case 2 consumed as `INSTRUMENTATION_GAP` after valid generation.** |
| `TECHNICAL_PASS_CONSTRAINED` | Reachable only with a `physical` execution authority that only the `execute` path can mint, plus complete evidence. A synthetic authority tops out at `INSTRUMENTATION_GAP`. |

The original harness was integrated through PR #83 at `4d83fd8b`. The subsequent launch corrections and this physical-result
closeout remain local on `codex/img154b-challenge-binding-launch`; they have no hosted CI verdict or publication authorization.

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
  no retry, the exact statement and the exact challenge digest, valid for at most 24 hours, and carrying a **salted PBKDF2
  verifier of an owner-chosen passphrase** (`cli passphrase-verifier`). Nothing in this package writes a record (an AST test
  enforces it). The record is unsigned JSON, so the controls are: the exact binding, the expiry, the interactive typed phrase
  (composed by the operator from labelled values; the assembled phrase is not printed), **the passphrase only the owner knows,
  read without echo and never stored or logged**, and the refusal under a test runner. A script that can write the record and
  drive a console still cannot start the run without the passphrase; the owner must not share it with automation.
* **Trusted code revision**: a clean checkout with an identified SHA; the source hash covers `img154` and `img154b`.
  `cli challenge` and the physical preflight/execute path use the same read-only source-identity helper, so the owner record
  binds both packages. Generate the challenge after the final correction commit; an older SHA/source binding is refused.
* Existing isolated targets satisfy the structural validator's full-hash requirement only after a complete, successful
  served-file proof and an unchanged-file recheck. Missing, failed, incomplete or stale proof remains inconclusive; every
  other isolation refusal is retained.
* **Fresh, independently validated baselines**: a window of at least 20 samples over at least 20 s, ending within 60 s, taken
  by the harness's own sampler, bound to the NVML device digest and the boot identity of the launch reading, dedicated VRAM
  spread at most 128 MiB, shared memory spread at most 128 MiB, GPU utilization at most 15%, no model runtime present at the
  start and the end of the window. **These validation criteria are provisional harness judgments**, not measured limits.
  The 154A launch thresholds are unchanged and unrelaxed: commit headroom >= 37 GiB, available RAM >= 20 GiB, pagefile-volume
  free >= 30 GiB, dedicated VRAM <= baseline + 512 MiB.
* Exact served-file proof, resolved request semantics, verified managed-runtime marker (revision, status, Python minor),
  validated launch profile, complete required telemetry coverage, no competing or foreign runtime, no prior attempt (stable
  record **and** workspace ledger), the operator's typed phrase and the owner's passphrase, then a **fresh re-measurement**
  after that unbounded wait: a new fault snapshot, a new 25-second quiescent window, the device identity again, and the
  resource readings last. A drop (or a stale or mismatched baseline) refuses with nothing consumed.
* **The sampler is proven healthy before the case is consumed**: three consecutive samples with every essential field `ok`
  and nothing latched, otherwise the run refuses unclaimed. A claim therefore never precedes working telemetry, and no
  process starts without it.

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
The manager returns as soon as the process exists and Forge binds the port tens of seconds later, so verification has two
modes: during the boot window it requires the process identity but no listener (and fails fast if the root exits or a listener
outside the tree appears); once the endpoint answers it requires every listener to be inside the owned tree, before
`startup_observed` is recorded and again before the selection request. The selection request is itself supervised by the
monitor watchdog. There is no signal, kill, taskkill or other PID authority in the package (AST-enforced). If the manager-owned stop does not
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

Immediately before the atomic claim, after operator interaction and sampler-health proof, the harness refreshes the
process inventory and port state, re-reads the trusted Git/source identity and checks the original authorization record's
file identity and complete bytes. It revalidates exact manifest/payload/policy/risk binding with fresh UTC and rejects expired,
modified, replaced, absent or unverifiable records before consuming the case. Runtime findings and resource preflight must
remain within the existing freshness window; unknown or conflicting state refuses. Loopback reachability confers no ownership.

## Stop, fault and result behavior

A latched `REQUEST_OWNER_STOP`, `CANNOT_VERIFY_SAFE_STATE` or `HARNESS_FAULT` persists its trigger, source, time and last
readings, halts progression, requests only the manager-owned shutdown, sends no second request and keeps an ambiguous
dispatch ambiguous. Two fresh clean samples are required after the selection and before the dispatch record. The single POST
runs in a worker thread supervised by the 1 Hz watchdog, with an independent overall monotonic deadline: 600 s for
selection, 1800 s for generation. Expiration is flush/fsync recorded in `requests.jsonl` before the manager-owned stop; the
POST and progress-observation workers share the existing bounded abort-join budget. Progress GETs run on a single
non-overlapping observation worker, so trickling or stalled responses cannot blind the supervisor; late observation results
cannot mutate an aborted case. An unjoined worker is explicitly reported as possibly outstanding. No
selection or generation progresses after an abort, no request is retried, and a late response cannot restore PASS. A dispatched
POST remains ambiguous even if shutdown is verified; a timeout does not prove Forge never received or executed it.

Classes: `PREFLIGHT_REFUSED`, `LOADER_FAILED`, `RESOURCE_ABORT_REQUESTED`, `AMBIGUOUS_DISPATCH`, `SYSTEM_OR_GPU_FAULT`,
`INSTRUMENTATION_GAP`, `OUTPUT_VALIDATION_FAIL`, `TECHNICAL_PASS_CONSTRAINED`. A pass needs the physical authority, a claim,
an observed startup, a confirmed selection, one decodable 1024x1024 non-constant image, the requested seed and effective
parameters (including the model hash and both modules), a verified clean owned shutdown with no unexplained survivor, a
recorded terminal ledger entry, complete telemetry (95% of samples per required field, no gaps, no sequence loss), a complete
evidence bundle and `NO_NEW_EVENTS_COMPLETE_COVERAGE` after the 120 s settle interval. It establishes one constrained
technical result, never stability, repeatability or production support.

## Validation

The first executed launch-correction SHA passed 709 affected tests (6 platform/explicit-opt-in skips), scoped Ruff and mypy,
and the local PR gate (8,244 collected; 386 smoke passed; repository unchanged; completeness/controller/Ruff/mypy passed).
The physical-result closeout changes documentation only and reuses that source-identical evidence without another run.
The second executed SHA passed 891 affected qualification/ownership tests (6 platform/explicit-opt-in skips), Ruff,
the required mypy smoke and local PR gate (8,246 collected; 386 smoke passed; repository unchanged). Additional scoped
typing passed four files with the pre-existing missing `psutil` stubs reported separately. This second closeout also changes
documentation only, reusing the accepted exact-source validation without another test or physical run.

The following records describe the original harness validation; PR #83 subsequently passed its hosted required and affected jobs.

The R1 import audit initializes standard-library `ctypes` separately before importing any harness module: CPython 3.14.8
`Lib/ctypes/__init__.py` initializes `pythonapi = PyDLL(None)` on Linux (the known hosted T89 event), and kernel32 on Windows.
Every subsequent native-library load remains audited and rejected, including `None` and kernel32. Unexpected process,
outbound-network and filesystem-write events remain rejected. This import isolation is not a hosted corrected-SHA verdict;
Linux `affected` CI was required before PR #83 integration; the subsequent local launch corrections remain unpublished.

| Evidence | Result |
| --- | --- |
| New focused suites (`tests/tools/test_img154b_*.py`: request, fence, adjudication, authorization, preflight, runtime, sampler, case, collector, boundary) | all pass (see the counts in the completion report) |
| Independent read-only review (separate agent, base commit `e8382f46`) | Verified the request semantics, fence, no-replay HTTP and native structure layouts. Found two blockers and two HIGH issues that the fakes had hidden, all fixed with regressions: (B1) ownership demanded a listener immediately after the non-blocking start; (B2) a ctypes structure's `_fields_` was assigned per instance, so a second PDH query in a process failed; (H1) no ownership gate between readiness and the selection request; (H2) post-stop samples counted as missing process-tree coverage so a flawless run could never pass. Also fixed: sampler construction and health proof before the claim, guarded post-run path, non-echoed owner passphrase, supervised selection request, fresh baseline after the operator wait, daemon provider threads, NVML init lock, BOM-tolerant record read, Euler extra options. |
| Unchanged 154A suites and PR-115/151/152/153 plus the WebUI process-manager ownership suites | pass |
| Mutation probes (26 high-risk rules, including non-exclusive claim, skipped or stale ownership, post-then-record, ignored confirmation and passphrase, shift key, CFG 0, no-shutdown pass, ignored device mismatch, hard-link alias, authorization removed, unconditional shutdown verification, second POST budget, torn ledger as clean, unverified selection, no fresh-sample wait, boot-window listener, endpoint ownership, skipped sampler proof, stale single-pid tree, re-assigned PDH fields) | all killed (two survived the first round; the cross-process test was not sensitive to a stale pre-check and the shutdown test did not cover an unobserved tree, so two regressions were added) |
| Anchors against the installed pinned tree (read-only text) | 23 anchors, 14 payload keys, no findings |
| Real native providers, read-only, 12.5 s | all fields ok, cadence and latency as above |
| Original live read-only preflight (below) | refused, as expected; superseded for the authorized attempt by the fresh prepared preflight above |

Opt-in checks (not run by default): `STABLENEW_IMG154B_FORGE_SOURCE=<managed source>` re-verifies the anchors;
`STABLENEW_IMG154B_NATIVE_SMOKE=1` reads the native providers.

## Original workstation preflight disposition (historical read-only observation)

`physical preflight` on this host, code state dirty (uncommitted work), no isolated layout: **`REFUSED_ASSET_IDENTITY`**
(served files absent, config marker absent), with commit headroom 26.6 GiB (< 37 GiB), available RAM 16.1 GiB (< 20 GiB),
pagefile-volume free 285 GiB, dedicated VRAM 1,854 MiB of 12,282 MiB against a harness-acquired quiescent baseline of
1,854 MiB (delta 0), no competing runtime, port free, anchors verified. The thresholds were not relaxed. This refusal is an
acceptable package result; the host has not demonstrated the conditions, and the 154A observation that 37 GiB of headroom
needs a near-idle desktop (commit total at most about 12.8 GiB) still holds.

## Residual risks and what remains unproven

* `DIAG-GPU-130` black-screen / live-kernel recurrences are unresolved and unattributed; no monitor can recover them.
* Every numeric threshold and the baseline-validation criteria are provisional; the RAM stop rule is uncalibrated. PR-IMG-115
  already saw 0.01 GB of available RAM during a benign load, so the 1 GiB floor held for 10 s may stop a healthy run
  (`RESOURCE_ABORT_REQUESTED`), which consumes the case. The threshold was not relaxed; that is an owner decision.
* The second case exercised and validated the frozen effective semantics once; image quality is unreviewed and repeatability,
  stability and production support remain unestablished. The recorded resource measurements describe only this exposure.
* File provenance is exact bytes only; official provenance is unverified.
* The owner-authorization record is unsigned; its authorship rests on the passphrase only the owner holds, and an owner who
  shares the passphrase with automation defeats that control.
* The dispatch is an hour-scale, single blocking request. The second case exercised it once after the first startup failed
  at the `uv` bootstrap check. The second case's unverified shutdown prevents a constrained technical PASS.

## Boundary for any subsequent physical run

Both authorized cases are complete and consumed; no third attempt is authorized. Any subsequent package must explicitly
address the launch-environment blocker, define its acceptance contract and distinct case identity, and retain the existing
case ledger and evidence. It must pass the unchanged authorization, isolation, ownership, resource and telemetry gates
before any new managed startup. A pre-claim refusal consumes nothing; an attempt that reaches the claim cannot be retried.

### Owner-authorized loader correction and second case (completed)

The owner explicitly continued the package to correct the loader failure and launch again. Read-only inspection found
`uv.exe` already present in the managed venv; the isolated profile had omitted the production profile's `PATH`,
`VIRTUAL_ENV` and `UV_PYTHON` bindings. The correction pins these only in the launched child environment and validates them;
no install, global environment change, manager change or threshold relaxation is needed. `uv --help` succeeds in that
exact child environment without starting Forge. The import-audit subprocess now uses `-B` explicitly because `-I` ignores
the existing bytecode environment flag; the audit still rejects every unexpected native/process/network/write event.

The CLI and physical module accept an explicit `--case-id`; absent it, the original case and consumed ledger remain the
default. The authorized second case is `img154-zimage-turbo-owner-case-2`, retaining the exact assets, request, limits and
one-claim/no-replay fence. A new exact-SHA owner record and interactive private confirmation are required; case-1's record
cannot authorize it. No loop or automatic third attempt is authorized.

Execution Profile: Narrow, demonstrated launch-environment repair and explicit continuation using the existing case/fence
contract. Recommendation: Codex GPT-6.1 Sol High / Claude Code Sonnet 5.5 High, Windows Local/Desktop, one session: the
understood defect is small, while cross-command authorization and lifecycle regressions make retry cost material.
Controller Surface Assessment: no production controller/coordinator/process manager touched; the existing qualification
coordinator and submission budgets are unchanged. Token-Efficient Validation Plan: fail-before launch and case-binding
regressions; focused boundary/fence suites; affected qualification/ownership suites and scoped lint/typing; one final local
PR gate; clean committed SHA; read-only child `uv` check and preflight; one interactive execution if every existing gate passes.
