# StableNew current state

Updated: 2026-10-05

## Repository

- Authoritative remote: `https://github.com/destroyer42/StableNew2.git`
- Default/release baseline: `main`
- Current release baseline: `main` (v2.6 MVP/release proof integrated)
- Supported runtime/validation (PR-DEVEX-100 and the interpreter promotion PR-PY314-100, both
  COMPLETE / ACCEPTED / INTEGRATED; PR #33): StableNew's application/native-SVD interpreter is standard-GIL CPython 3.14.x only
  (3.12, 3.13, 3.15+ and the free-threaded build are rejected by readiness/bootstrap; no JIT).
  GitHub CI runs once per PR head
  on Python 3.14 with risk-proportionate routing (PR-DEVEX-CI-110: `required`, then only the affected lanes or, for
  broad/unbounded changes, one informational full census; docs-only changes take a cheap path); the local
  `run_pr_gate.py` pytest gates are quiet on success and complete on failure. See
  `docs/StableNew_Coding_and_Testing_v2.6.md`.
- Reproducible ML runtime (PR-RUNTIME-DEPS-100): the supported Windows/CPython 3.14/CUDA 13.0
  environment is defined by `constraints/windows-py314-cu130.txt` (exact pins, including the
  resolver `pip`) applied by `scripts/bootstrap_windows.ps1`; `tools/runtime/verify_runtime_pins.py`
  detects drift in bootstrap and `-CheckOnly`. Accepted direct stack: Torch/torchvision `+cu130`
  2.14.0/0.29.0, Diffusers 0.40.0, Transformers 5.17.0, Accelerate 1.15.0.
- Restoration isolation (PR-POSTPROC-100, COMPLETE / ACCEPTED / INTEGRATED; PR #32): local face restoration/upscaling is an
  optional `-WithPostprocess` profile (`requirements-postprocess.txt`, a `# profile: postprocess`
  section of the constraints) behind StableNew-owned adapters in `src/video/restoration/`. RealESRGAN
  and the CodeFormer network load through Spandrel with bit-identical output; the legacy face helper
  (`facelib` from the `codeformer` wheel) is retained and isolated because `facexlib` changes output
  materially; GFPGAN stays a named method that fails closed. `opencv-python` stays core (Photo Optimize
  uses it; the retained helper requires it). See
  `docs/Subsystems/Video/PR-POSTPROC-100_Restoration_Isolation.md`.
- Managed ComfyUI runtime (PR-COMFY-RUNTIME-100, COMPLETE / ACCEPTED / INTEGRATED; PR #34): the
  StableNew-managed Comfy is a reproducible, independently owned runtime separate from the application
  environment: ComfyUI `v0.38.0` (`6b747c04…`) on official standard-GIL CPython 3.13.x, Torch `2.14.0+cu130`, no
  custom nodes, identity in `config/managed_comfy_runtime.json`, the complete exact package set in
  `constraints/comfy-windows-py313-cu130-v0.38.0.txt`, built by `scripts/bootstrap_managed_comfy_windows.ps1` and
  drift-checked by `tools/runtime/verify_managed_comfy.py`; `ComfyProcessManager` stays the only lifecycle
  authority and external Comfy/A1111/Forge are untouched. A two-candidate method (v0.37.0 on Python 3.13, then
  v0.38.0) and three physical runs passed the output-equivalence (not bit-identical, visually equivalent) and
  resource gates. New `@1.2.0` workflow versions (TI2V and Animate-2) carry the `@1.1.0` graph with v0.38.0
  provenance; `@1.0.0`/`@1.1.0` are byte-identical. Workflows stay experimental. See
  `docs/Subsystems/Video/PR-COMFY-RUNTIME-100_Managed_Comfy_Runtime.md` and
  `docs/runbooks/managed_comfy_runtime.md`.
- Managed Forge Neo runtime (PR-IMG-FORGE-RUNTIME-100 and PR-IMG-FORGE-110, COMPLETE / ACCEPTED / INTEGRATED; PR #36): the hand-qualified Forge environment is replaced by a
  StableNew-owned runtime rebuilt from nothing - Forge `d70373eb…` and ADetailer-Neo `af228eba…` at exact commits,
  standard-GIL CPython 3.13, Torch `2.13.0+cu130`, the complete accepted 147-distribution set
  (`constraints/forge-windows-py313-cu130-neo-d70373eb.txt`, installed `--no-deps`), identity in
  `config/managed_forge_runtime.json`, built by `scripts/bootstrap_managed_forge_windows.ps1` and drift-checked by
  `tools/runtime/verify_managed_forge.py` (accepts only the declared Gradio/Pillow `pip check` line).
  `WebUIProcessManager` stays the only lifecycle authority. One canonical Pair-A Forge job through the managed
  runtime decodes to pixels identical to the accepted hand-built image (`MANAGED_FORGE_RUNTIME_REPRODUCIBILITY_PASS`).
  Forge is a supported production still-image backend (PR-IMG-FORGE-110, `FORGE_PRODUCTION_PROMOTION_PASS`),
  selected by `webui_runtime_identity`/`forge_runtime_profile_path`; A1111 remains the default and the rollback.
  Capability
  qualification (`FORGE_TECHNICAL_QUALIFICATION_PASS`, technical gate only; Forge is not the default): Pairs B (LoRA),
  C (img2img) and D (txt2img -> ADetailer face+hand -> 1.5x upscale) pass on A1111 and managed Forge. Pair D needed
  three repairs: the launch-profile ownership repair, R3 ADetailer progress semantics (D100 A1111 arm: natural
  completion, 127.6 s ADetailer response), and PR-IMG-FORGE-D110 (Forge module-baseline normalization: an ordinary
  Forge stage reads the endpoint's persisted `forge_additional_modules` and verifiably replaces stale Klein modules
  before any model load; Klein and A1111 paths are untouched). Known and separate: generic definite-HTTP-error
  retries are unchanged. See `docs/runbooks/managed_forge_runtime.md` and sections 23-29 of
  `docs/Subsystems/Image/PR-IMG-FORGE-100_Forge_Compatibility_Qualification.md`.
- FLUX.2 Klein 4B FP8 target-hardware qualification (PR-IMG-115, local branch, owner review pending,
  `FLUX2_KLEIN_4B_FP8_PASS_CONSTRAINED`, product value pending): on the pinned managed Forge and RTX 4070 Ti 12 GB,
  portrait, 1024x1024 and single-reference edit generations pass cleanly (about 9.7 GiB VRAM peak, no spill, no GPU event);
  two-reference editing is blocked by a pinned-Forge API gap (`ImageStitch` script args rejected), not by the model.
  Model/runtime qualification only; no production integration. See
  `docs/Subsystems/Image/PR-IMG-115_FLUX2_Klein_4B_FP8_Target_Hardware_Qualification.md`.
- FLUX.2 Klein 4B FP8 production slice (PR-IMG-116, local branch, `FLUX2_KLEIN_4B_FP8_PRODUCTION_SLICE_PASS`): on the existing
  `forge_webui` backend, a versioned immutable model profile (`flux2_klein_4b_fp8` v1: exact transformer/Qwen3/VAE identities,
  Euler/Beta/4/CFG 1.0, 768x1024 and 1024x1024) supports text-to-image (Pipeline tab) and one-reference edit (explicit Review
  checkbox -> normal `img2img` reprocess NJR). Forge multi-module selection is verified and never skipped; unsupported work
  (multi-reference, ADetailer, upscale, LoRA, ...) fails before dispatch; total physical RAM must be at least 32e9 bytes
  (available RAM is evidence only). Assets install with `scripts/install_forge_klein_assets.ps1` into the managed Forge data
  tree. Two production smokes passed on the RTX 4070 Ti. A1111 stays the default and the rollback; multi-reference is
  unsupported and tracked separately. See `docs/Subsystems/Image/PR-IMG-116_FLUX2_Klein_Forge_Production_Slice.md`.
- Risk-proportionate CI (PR-DEVEX-CI-110): the repository-owned `tools/ci/validation_plan.py` classifies the base-to-head change
  set into additive coarse lanes and the single PR-head workflow consumes it. Docs-only changes take a cheap path (no Python
  environment); every executable PR runs `required` (repository quality plus a small cross-boundary contract suite, 294 tests) and
  then only its affected lanes; broad/unbounded changes (dependencies, pytest/CI configuration, shared test infrastructure, the policy
  itself, unknown impact) run one full census instead. The full census also runs on main Monday/Wednesday/Friday, on dispatch, before
  releases and on request (`full-census` label or `[full-census]` commit marker). No tests were deleted; a measured test and ownership
  census is in `docs/Subsystems/Testing/PR-DEVEX-CI-110_Risk_Proportionate_CI.md`. Codex review is on demand, not a mandatory stage
  (`docs/AGENT_OPERATING_MODEL.md`).
  Parallel/sharded full census (PR-DEVEX-CENSUS-140, COMPLETE): a full census now executes as three deterministic whole-file hosted shards
  (`sha256(repo-relative path) % 3`, each its own runner/process/Xvfb/JUnit) followed by an aggregate `full-suite` verdict that fails closed
  unless every active test file is assigned exactly once and every shard passed; `required` and affected-lane routing are unchanged and no
  test coverage was removed. Hosted evidence: 722 files, 5,093 JUnit records (5,046 passed / 47 skipped / 0 failed), parallel census wall =
  slowest shard 134.8 s versus about 565.7 s serial. The supported local census is `python tools/ci/run_sharded_census.py` (two isolated
  worker checkouts, 464 s on the owner's Windows workstation). See `docs/Subsystems/Testing/PR-DEVEX-CENSUS-140_Parallel_Sharded_Full_Census.md`.
- WebUI startup / UI watchdog lifecycle (PR-RUNTIME-WEBUI-WATCHDOG-120): slow WebUI startup stays allowed within the existing bounded readiness contracts, and the UI-heartbeat watchdog observes Tk responsiveness only. The watchdog is attached after the main window (heartbeat source) exists; "never triggered" is an explicit `-inf` in the watchdog and diagnostics-bundle guard, so the first genuine stall triggers regardless of host uptime while repeat cooldowns are unchanged; the WebUI Launch/Retry/autoreconnect controls run their bounded connection work on a tracked thread and project the result on Tk (single-flight). No ownership, retry-policy, queue or runner change. See `docs/Subsystems/Runtime/PR-RUNTIME-WEBUI-WATCHDOG-120_WebUI_Startup_and_UI_Watchdog_Lifecycle.md`.
- Deterministic test slimming (PR-DEVEX-TEST-SLIM-120 Phase B1, COMPLETE; hosted Python 3.14 CI green: `required` plus a full census of 4,993 passed / 47 skipped / 0 failed): the slowest unit/integration tests no longer wait on production backoff, loopback discovery, ambient presets or a pytest-only generation hook (the `PYTEST_CURRENT_TEST` branch in `QueueRunSubmissionService.start_run` is removed; `app_controller.py` ceiling 7782 -> 7731). `WebUIResourceService(client=None)` now explicitly means filesystem-only (omitted = API-first default client). No tests deleted; focused set 185 s -> 15 s, full-census pytest time about 643 s -> 503 s. The stale pre-HTTP-100 retry assertion in `tests/test_api_client.py` and an uptime-dependent watchdog test exposed by the speed-up were repaired test-side only. One cancellation test (`test_pr_harden_009_r1a`) was a local-only load-sensitive observation that did not reproduce in hosted CI. See `docs/Subsystems/Testing/PR-DEVEX-TEST-SLIM-120_Phase_B1_Deterministic_Test_Slimming.md`.
- Pre-Forge execution and test truth (PR-TEST-TRUTH-210, current while its PR is open; bounded truth package, not
  a product capability): `build_run_plan_from_njr` is fail-closed - only explicitly enabled, explicitly named
  stages are planned, and a missing/blank stage identity or an empty/all-disabled chain raises `ValueError`
  instead of becoming `txt2img`; `PipelineRunner.run_njr` validates the plan before any metrics/`free_vram`/backend
  side effect. The active deterministic suite no longer carries permanent "Implementation pending/deferred" or
  PR-GUI-F1 placeholder skips (Golden Path, run-control and stage-checkbox surfaces were mapped to their current
  authority or retired). See
  `docs/Subsystems/Testing/PR-TEST-TRUTH-210_Pre_Forge_Execution_and_Test_Truth.md`. After explicit owner
  acceptance/integration the next product package was `PR-IMG-FORGE-100` (now integrated).
- Active diagnostic evidence: `DIAG-GPU-130 - Post-5600 Black-Screen Recurrence` - **XMP-OFF
  RECURRENCE / ACTIVE OBSERVATION; EXIT CRITERION NOT MET**. The owner confirms the RAM XMP profile
  has now been removed. After the 2026-09-25 07:06:20 ET boot, Windows reports both DIMMs at
  DDR5-5600, configured 5600 MT/s and 1100 mV; Windows does not establish the firmware XMP toggle,
  Intel Baseline/Default, timings, or controller state. A further 2026-09-26 recurrence produced
  WER LiveKernel `141` and `1B8` artifacts followed by unexpected shutdown at 22:06:46 ET and
  reboot at 22:07:24 ET. Known immediately preceding context is the PR-VID-184 Arm A
  Wan-Animate-2 GPU-loss workload, about 20 minutes before that recovery boot; however, no
  continuous survivor telemetry ties the exact `141`/`1B8` interval to it. The interval therefore
  remains the known display/live-kernel family without causal or workload attribution and does not
  count as qualified GPU-active exposure. This temporal correlation neither causes the restart nor
  proves or falsifies failure-family equivalence. The current NVIDIA driver reports `32.0.16.1714`,
  differing from the earlier `32.0.16.1692`; this is an evidence confounder, not a driver
  attribution. This is not a PASS, fix, hardware clearance, or root-cause verdict.
  The prior recurrence under reported DDR5-5600/XMP remains captured; subsequent ordinary-use
  observation must preserve survivor telemetry and Windows evidence. The current baseline has not
  been deliberately stress-tested. The earlier 5600/XMP recurrence remains documented with its
  WER `141` and `1B8` evidence and survivor telemetry proving immediately preceding StableNew A1111
  `txt2img` work; it does not attribute a component or StableNew as the cause. DDR5-5600 was
  insufficient to eliminate the failure, but memory/platform stability remains unexcluded.
  **Amended 2026-09-24:** NVIDIA driver-package isolation is deprioritized by cross-version
  recurrence evidence (owner-supplied); the next isolation should target the platform baseline,
  one variable at a time, with all other configuration and hardware (including the driver) held
  unchanged. `DIAG-GPU-110`
  is **COMPLETE / ACCEPTED / INTEGRATED**: its read-only report establishes strong
  cross-incident convergence on the Windows black-screen/display capture domain, without
  driver- or component-level attribution. The two `0x133` minidumps remain access-restricted;
  no individual driver, StableNew, or hardware root cause is accepted. `DIAG-GPU-100` remains
  **COMPLETE / ACCEPTED / INTEGRATED**, including its observation-only survivor telemetry and
  GitHub Actions run 35681930199 required Python 3.11/3.12 evidence. `PR-LEARN-302`, `PR-TEST-OPERATOR-110`, `PR-LEARN-301`,
  `PR-TEST-OPERATOR-100` and `PR-LEARN-300` are COMPLETE / ACCEPTED / INTEGRATED.
  `PR-IMG-110` is integrated; its Ideogram 4 "hardware no-go" is superseded by
  `PR-IMG-110R` (Ideogram 4 NF4 PASS — CONSTRAINED on the 12-GB target; COMPLETE /
  ACCEPTED / INTEGRATED). `PR-IMG-120` remains unauthorized pending a separate owner decision.
  `PR-VID-110` is COMPLETE / ACCEPTED / INTEGRATED (Wan2.2 TI2V-5B CONDITIONAL and the only
  currently qualified directed-motion candidate; Wan2.1 VACE-1.3B NO-GO in reference-only,
  Canny and pose-only modes; native SVD the only accepted production video backend).
  `PR-VID-120` (capability-aware, backend-neutral video execution contract) is COMPLETE /
  ACCEPTED / INTEGRATED; it adds no Wan/VACE integration and native SVD is unchanged. Neutral
  backend selection is explicit (`video_execution.backend_id`); the historical stage-owned bridge
  remains. Details: `docs/Subsystems/Video/PR-VID-120_Neutral_Video_Execution_Contract.md`.
  `PR-VID-130 — Wan2.2 Experimental Prompt-Directed I2V Vertical Slice` is COMPLETE / ACCEPTED / INTEGRATED
  (`docs/Subsystems/Video/PR-VID-130_Wan22_Experimental_Vertical_Slice.md`). Wan2.2 `wan22_ti2v_5b_i2v_v1` v1.0.0 is an EXPERIMENTAL Comfy workflow, never generally approved: each job needs durable explicit `video_execution.experimental_opt_in=true`; disabled workflows stay non-runnable; governance, dependency checks and an observe-only resource-readiness guard (10,000 MiB GPU memory available to Comfy, 16 GB host RAM; not a scheduler/lease) fail before Comfy queue dispatch; external A1111/Comfy are never adopted, terminated or restarted. Native SVD remains the default production video backend; VACE stays NO-GO and unregistered. `VideoWorkflowController` now emits neutral `video_execution` intent; the historical stage bridge remains for the SVD producer, AnimateDiff, prompt-pack/reprocess-built `video_workflow` stages and historical replay, and is retired only once every producer is neutral and replay normalization is proven. Real Wan2.2 acceptance on the RTX 4070 Ti 12 GB produced a valid 480x832/49-frame/24 fps MP4 in ~83.4 s (peak 11,630 MiB VRAM, min 1.45 GB free RAM, no GPU fault).
  `PR-RUNTIME-110 — Comfy Video Runner Liveness / Watchdog Correctness` is **COMPLETE / ACCEPTED /
  INTEGRATED** (PR #23)
  (`docs/Subsystems/Runtime/PR-RUNTIME-110_Comfy_Video_Runner_Liveness.md`).
  Healthy long Comfy video jobs no longer trigger a false `queue_runner_stall` at ~90 s: while the
  server confirms the queued prompt is running, or history explicitly reports a nonterminal state,
  the backend reports bounded, job-scoped liveness through the existing runtime-status path (no
  invented progress; still bounded by the workflow-declared backend execution timeout). Terminal
  failed history does not prolong liveness. Genuine stalls, native SVD and WebUI watchdog semantics
  are unchanged.
  `PR-TEST-TRUTH-200 — Actionable CI & Consolidated Legacy Journeys` restores a truthful test
  signal (`docs/Subsystems/Testing/PR-TEST-TRUTH-200_Actionable_CI.md`): the legacy `tests/journeys`
  lane and its `Journey Tests` workflow are retired, stale NJR/queue/history fixtures are repaired
  to the current contract, host-state leaks (owner's A1111/PromptPacks) are isolated, and the
  informational full-suite lane now runs to completion with a per-test timeout. Required CI is
  unchanged. Two production defects it exposed were fixed in the 200R pass:
  `PipelineRunResult.randomizer_mode` now projects `njr.variant_mode`, and `SingleNodeJobRunner`
  owns a locked one-shot -> continuous worker handoff so enabling auto-run at the retirement
  boundary cannot stall queued jobs (single local Python 3.11 full suite: 0 failed).
  `PR-RUNTIME-100 — Owned GPU Runtime Transition Policy` is **COMPLETE / ACCEPTED / INTEGRATED**.
  It coordinates release of conflicting StableNew-owned A1111,
  Comfy, or cached SVD residency before the already-selected backend prepares;
  existing owners remain sole lifecycle authorities. A configured live/occupied
  A1111 or Comfy endpoint without an owned manager handle is external and
  immutable; no runtime is restored after a job. It mitigates avoidable
  owned-runtime contention only and makes no claim about the separate
  workstation black-screen/GPU-reset diagnosis.
  `PR-VID-140` Wan2.2 Operator Readiness is **COMPLETE / ACCEPTED / INTEGRATED**
  (`docs/Subsystems/Video/PR-VID-140_Wan22_Operator_Readiness.md`). LTX catalog metadata is
  retained but disabled because the required
  `StableNewLTX*Bridge` implementations and accepted real evidence do not exist. Wan remains
  experimental and per-job opt-in. Its source-aware preparation freezes portrait/square as
  480x832 and landscape as 832x480 in the submitted NJR, along with the admission-frozen seed.
  The owned Comfy manager now honors the configured 30-second readiness timeout and poll interval,
  with bounded owned-process failure evidence. One managed real landscape run completed through
  the canonical queue/resolver path (49 frames, 24 fps, 832x480) with no GPU-loss recurrence.
  Required GitHub CI run 35729678881 passed Python 3.11 and 3.12; its informational full-suite
  jobs retain unrelated `xvfb-run` failures.
  `PR-VID-150 — Wan2.2 Motion Characterization & Prompt Evidence` is **COMPLETE / ACCEPTED /
  INTEGRATED**
  (`docs/Subsystems/Video/PR-VID-150_Wan22_Motion_Characterization.md`). Three real jobs through
  the canonical production path, same source/seed/settings, only the positive motion prompt
  varied: a terse gesture baseline, a structured equivalent gesture, and a structured locomotion
  request. Structured sequential prompting materially improved the local gesture (roughly 2x the
  measured motion, smoother temporal metric, adherence intact, minor anatomy cost) versus the
  terse baseline. The same structured style did not produce whole-body locomotion: the person's
  feet stayed planted across the clip despite an explicit two-step request, with further anatomy
  degradation on the swinging arm. Evidence classification:
  `local_motion_viable_locomotion_weak`. Recommended next package: consumer-GPU motion-backend
  qualification (a candidate better suited to whole-body/directed motion) rather than further Wan
  locomotion prompt tuning; FramePack and/or an LTX-Video 2B research lane are plausible starting
  points but neither is selected or locked in, and candidate selection requires a fresh
  research/feasibility comparison against current upstream implementations and the RTX 4070 Ti
  12 GB / 32 GB RAM target before any qualification work begins. Wan structured-prompt presets for
  gesture/pose motion remain a separate, lower-effort candidate. No Wan production graph/settings
  changed; Wan remains experimental and unpromoted. Three clean post-PR-VID-140 GPU exposures with
  no DIAG-GPU-120/100 recurrence.
  `PR-VID-160A — Consumer-GPU Directed-Motion Candidate Feasibility` is **COMPLETE / ACCEPTED /
  INTEGRATED**
  (`docs/Subsystems/Video/PR-VID-160A_Consumer_GPU_Motion_Candidate_Feasibility.md`), superseding
  PR-VID-150's tentative "FramePack and/or LTX-Video 2B" framing with a researched decision.
  Evidence classification: `BOUNDED_FEASIBILITY_PROBE_REQUIRED`. Wan2.2-Animate-14B Move mode
  (motion transferred from a driving video onto a reference-image character, rather than
  text-prompted motion) is the single lead feasibility candidate: it directly targets the
  PR-VID-150 locomotion gap and structurally separates identity from motion, addressing the
  PR-VID-110 VACE reference-binding failure. LTX-2 and HunyuanVideo-1.5 fail current official
  hard hardware gates for the RTX 4070 Ti 12 GB target; FramePack's official low-VRAM claim is
  contradicted by unresolved upstream evidence and has a weaker Comfy integration fit; legacy
  LTX-Video 2B remains an unverified, vendor-deprioritized fallback. For Wan2.2-Animate-14B, Gate
  C (12 GB VRAM) remains plausible on community GGUF evidence but unproven at StableNew's exact
  settings, and Gate D (32 GB host RAM) remains the principal open resource risk: StableNew's own
  accepted Wan2.2 5B telemetry already shows near-zero available host-RAM headroom, and community
  reports in the same wrapper ecosystem describe far worse memory pressure on 14B-class models. No
  model or backend is yet accepted; no model was installed and no environment or GPU state changed
  to produce this evidence. Next objective: `PR-VID-160B — Wan2.2-Animate Target-Hardware
  Feasibility Probe`, a bounded resource-feasibility probe (not model installation or full
  qualification) requiring separate explicit authorization.
  `PR-VID-160B` (`docs/Subsystems/Video/PR-VID-160B_Wan22_Animate_Target_Hardware_Feasibility.md`)
  is **`PARTIAL EVIDENCE ACCEPTED / INTEGRATED — MOVE-MODE RESOURCE GATE STILL OPEN`**. It ran the
  one authorized qualification-only physical attempt: `Wan2.2-Animate-14B-Q3_K_M.gguf` (community GGUF quant,
  chosen over the task's Q4_K_M default for VRAM margin) via a frozen minimal graph dispatched
  directly to a manager-owned Comfy instance (Animate is not a registered StableNew workflow; no
  `VideoWorkflowController`/NJR path was used). The run omitted `pose_video` (the input that
  actually exercises Move-mode motion transfer) and `face_video` (optional expression guidance), so
  it does not answer the package's original Move-mode question. Sub-finding:
  **`ANIMATE_BACKBONE_RESOURCE_FLOOR_PASS`** (descriptive, not a production-governance
  classification) — the Animate-14B GGUF backbone alone (transformer load, text encoder, CLIP
  Vision, VAE, sampler, decode) completed cleanly at reduced geometry (256x256, 13 frames, 4 steps):
  VRAM peaked at 11,396 MiB of 12,282 MiB (~886 MiB margin), host RAM never dropped below 4.7 GB
  available, no safety-stop, no GPU loss, clean teardown, valid decodable MP4 in 30.4 s. Gate C
  (VRAM): materially de-risked but not fully closed — true Move-mode peak VRAM with the pose branch
  is unmeasured. Gate D (host RAM): strongly de-risked but not fully closed — do not extrapolate
  4.7 GB minimum to a full Move-mode workload. One additional clean high-load DIAG-GPU-120 exposure;
  not a PASS or root-cause conclusion. No production Wan/backend setting or governance changed;
  Animate remains unregistered.
  `PR-VID-160C — Wan2.2-Animate True Move-Mode Resource Closure`
  (`docs/Subsystems/Video/PR-VID-160C_Wan22_Animate_Move_Mode_Resource_Closure.md`) closes the
  Move-mode resource gate PR-VID-160B left open, with an adjudicated result:
  **`MOVE_MODE_RESOURCE_PASS_32GB`** (supersedes the interim `MOVE_MODE_RESOURCE_NO_GO_RAM`
  reading below). Run 1, reusing the identical Q3_K_M quant/assets/harness/seed/geometry (256x256,
  13 frames, 4 steps) plus a real, reused/adapted `pose_video` (deterministically resampled from the
  existing accepted PR-VID-110 skeleton-only control clip, no new dependency), was safety-stopped by
  a coarse guard: available *physical* RAM fell to 0.77 GB (below the original 1.0 GB /
  2-consecutive-sample threshold) before generation completed. That proved the guard fired as
  designed; it did not by itself prove Windows/Comfy could not complete with 32 GB RAM, since
  low available physical RAM is not the same signal as actual virtual-memory (commit) exhaustion. A
  product-owner-authorized commit-aware adjudication (Run 2) added Windows-native system-commit
  telemetry (`tools/qualification/vid160c/win_memory.py`, `ctypes` only, no new dependency) and
  replaced the physical-RAM-only abort with a commit-aware rule (commit ≥97% or headroom <1.0 GB for
  2 consecutive samples, plus a 0.25 GB physical-RAM emergency floor; the original 1.0 GB threshold
  now a warning only), then reran the byte-identical graph/assets/settings once. Run 2 **completed**:
  valid 256x256/13-frame/8fps output, physical RAM never dropped below 2.95 GB (never even crossing
  the original warning line), system commit peaked at 69.1% of a 63.76 GB commit limit with 19.71 GB
  of headroom remaining throughout, no CUDA OOM, no GPU loss, clean owned-runtime teardown. No quant,
  geometry, frame count, step count, `face_video`, Comfy memory flag, or pagefile setting was changed
  between runs. This establishes that 32 GB host RAM is sufficient for the exact tested minimal
  Move-mode configuration; it does not establish full-resolution 480x832 feasibility, 49-frame
  feasibility, production-quality-settings feasibility, general Wan2.2-Animate feasibility at all
  workloads, or production readiness. No production Wan/backend setting or governance changed;
  Animate remains unregistered. Two clean high-load DIAG-GPU-120 exposures now recorded for this
  package (Run 1's tool-initiated interruption, Run 2's normal completion); neither is a PASS or
  root-cause conclusion; DIAG-GPU-120 remains observation-only.

  `PR-VID-170 — Wan2.2-Animate Motion-Transfer Characterization`
  (`docs/Subsystems/Video/PR-VID-170_Wan22_Animate_Motion_Transfer_Characterization.md`) ran that
  characterization: three real cases (A local gesture, B locomotion, C whole-body weight shift; A/B
  synthetic deterministic pose sequences, C the real PR-VID-110 hip-hinge clip — no suitable
  existing three-way real driving-motion inventory existed, documented in the report) at official
  Wan2.2-Animate-14B sampling settings (`steps=20, cfg=1.0, shift=5.0, sampler=uni_pc`, sourced
  directly from `Wan-Video/Wan2.2`'s config, not invented) on the accepted 256x256/13-frame
  envelope. All three completed cleanly (no safety stop, no CUDA OOM, no GPU loss). Result:
  **`ANIMATE_QUALITY_INSUFFICIENT_AT_SMALL_ENVELOPE`** — pervasive visual noise, unrequested camera
  zoom/reframing, and unresolvable face/identity detail in all three cases prevented a confident
  identity/locomotion/anatomy judgment either way; this is an envelope/settings limitation, not a
  capability verdict. Comparison to PR-VID-150 (locomotion) and PR-VID-110/VACE (identity) is
  inconclusive for the same reason. Official upstream Animate support is materially larger than
  this qualification envelope: the model supports only `720x1280`/`1280x720` (default `1280x720`),
  77 frames, 30 fps — 256x256 is not even among the officially supported sizes, so the tested
  envelope is a deliberately resource-constrained qualification envelope, not an
  upstream-representative one. `cfg=1.0` is the model's own official Animate guidance baseline
  (Phase A), not an unvalidated setting, and should remain fixed, not tuned, going forward; an
  earlier draft of this record speculated `cfg=1.0` itself might be the dominant quality driver,
  which is corrected here as unsupported. Next objective: a controlled larger-envelope Wan2.2-Animate
  characterization with official inference settings held fixed (`cfg=1.0, shift=5.0, steps=20,
  sampler=uni_pc`), to determine whether increasing spatial resolution toward the officially
  supported sizes makes identity/anatomy/motion-transfer output interpretable on the current 12 GB
  VRAM / 32 GB RAM workstation, before any production-integration decision. No production Wan/backend
  setting or governance changed; Animate remains unregistered. Three additional clean DIAG-GPU-120
  exposures; not a PASS or root-cause conclusion.
  `PR-VID-175 — Wan2.2-Animate 480x832 Interpretability Gate`
  (`docs/Subsystems/Video/PR-VID-175_Wan22_Animate_480x832_Interpretability.md`) answered that
  question with one physical run: PR-VID-170 Case C's exact real hip-hinge motion/reference/seed/
  official settings, unchanged except `256x256 -> 480x832`. Completed cleanly (no safety stop, no
  CUDA OOM, no GPU loss). Result: **`ANIMATE_480x832_INTERPRETABLE_PASS`** — direct inspection of
  the full 13-frame clip shows identity, anatomy, and the hip-hinge motion progression are now all
  clearly assessable (a qualitative step-change from PR-VID-170), and the severe unrequested camera
  zoom/reframing is resolved for subject framing, though background hallucination/instability
  persists as a separate, still-present issue. Resource cost increased measurably (VRAM headroom
  954 MiB vs 1,445 MiB; commit headroom 11.66 GB vs 17.95 GB; wall time ~2x) but stayed well clear
  of every commit-aware safety threshold. This is an interpretability-gate result only, not a
  product-value characterization. No production Wan/backend setting or governance changed; Animate
  remains unregistered; no sampler/CFG/steps tuning performed; no move to 720x1280 in this package.
  Next objective: the controlled A/B/C motion-transfer characterization at 480x832 (PR-VID-170's
  case structure, now at an interpretable resolution), official settings held fixed. One additional
  clean DIAG-GPU-120 exposure; not a PASS or root-cause conclusion.
  `PR-VID-180 — Wan2.2-Animate 480x832 Motion-Transfer Characterization`
  (`docs/Subsystems/Video/PR-VID-180_Wan22_Animate_480x832_Motion_Transfer_Characterization.md`)
  answered that objective with two physical runs (Case A gesture, Case B locomotion; Case C reused
  read-only from PR-VID-175's accepted evidence, not rerun). Both completed cleanly (no safety stop,
  no CUDA OOM, no GPU loss) with resource cost closely matching PR-VID-175 Case C. Result:
  **`PR-VID-180 — COMPLETE / ACCEPTED / INTEGRATED — ANIMATE_CHARACTERIZATION_INCONCLUSIVE`**,
  secondary finding **`BACKGROUND_INSTABILITY_CROSS_CASE`** — gesture and locomotion both failed
  clearly with this package's procedural synthetic pose-control input (Case A: no recognizable
  subject at all; Case B: subject stays identifiable and well-framed but does not step or translate
  at all despite an unambiguous gait pose signal), in contrast with Case C's success. The material
  confound is not "synthetic vs. real photographic input" (every case conditions on a pose-control
  video, never on raw photography) but **procedural synthetic pose conditioning (A/B: a manually
  parameterized stick figure, no real human motion behind it) vs. detector-derived real-human pose
  conditioning (C: rendered from a real person's captured motion)**. Official Wan2.2-Animate's own
  preprocessing detects whole-body pose from real driving footage, builds retargeted `AAPoseMeta`,
  and renders its own richer `src_pose.mp4`/`src_face.mp4` — materially richer than this package's
  procedural renderer — making this the strongest current root-cause hypothesis for A/B's failure,
  not a proven cause. A/B must not be read as clean evidence Animate cannot do gesture/locomotion:
  the outputs clearly failed, but their conditioning representation was not shown to be
  upstream-equivalent. `face_video` stayed absent throughout (including Case C's success), so it
  does not explain the differential result by itself and remains untested as a separate variable.
  Background hallucination is confirmed common across all three cases (not Case-C-specific) — a
  material independent quality defect requiring separate mitigation/adjudication, not yet a
  definitive production NO-GO. No production Wan/backend setting or governance changed; Animate
  remains unregistered; no settings tuning performed. Next objective: adjudicate the
  pose-conditioning-representation confound using real human gesture/locomotion driving footage
  processed through an upstream-compatible Wan Animate whole-body pose pipeline at the
  already-proven 480x832 envelope, inference graph/settings held fixed, `face_video` still absent;
  background-hallucination mitigation is a separate future objective. Two additional clean
  DIAG-GPU-120 exposures; not a PASS or root-cause conclusion.
  `PR-VID-181 — COMPLETE / ACCEPTED / INTEGRATED — ANIMATE_REAL_POSE_LOCAL_MOTION_ONLY`
  (`docs/Subsystems/Video/PR-VID-181_Wan22_Animate_Real_Driving_Pose_Adjudication.md`), ran the
  adjudication: pinned `Wan-Video/Wan2.2 @ 1ea34ff4` whole-body pose preprocessing ran CPU-only in a
  disposable environment outside every StableNew/Comfy/A1111 runtime; two real single-person stock
  clips (Mixkit; owner confirmed the license for personal-use testing) became frozen 480x832/13f/8fps
  controls (`retarget_flag=False`); after the owner's explicit GPU go-ahead, exactly two Animate
  generations ran at the frozen 480x832 configuration (no retries, no safety stop, commit peak
  ~77%). Result: **`ANIMATE_REAL_POSE_LOCAL_MOTION_ONLY`**, secondary
  **`BACKGROUND_INSTABILITY_CROSS_CASE`**. Case A (gesture) now transfers onto a recognisable person
  (motion-curve correlation 0.42, versus -0.09 for PR-VID-180's synthetic control) with clothing
  drift from the driving footage, so the procedural-vs-upstream conditioning representation was a
  material cause of PR-VID-180's gesture failure. Case B (locomotion) repeats PR-VID-180's failure
  pattern - the reference-identity subject stays planted while a separate blurred figure performs
  the stepping and travels - so better pose conditioning alone does not deliver locomotion at this
  envelope. Caveats: one seed, one silhouetted 1.2 s control, no retargeting, no `face_video`. No
  production Wan/backend setting or governance changed; Animate remains unregistered. Next
  `PR-VID-182 — Wan2.2-Animate Case-B Basic Pose-Retargeting Adjudication`
  (`docs/Subsystems/Video/PR-VID-182_Wan22_Animate_Basic_Pose_Retargeting_Adjudication.md`) is
  **PR-VID-182 — COMPLETE / ACCEPTED / INTEGRATED — `BASIC_RETARGET_PRECONDITION_NOT_MET`**. Pinned Wan upstream basic retargeting
  requires both the reference and the first driving frame to be front-facing and stretched/standard.
  The frozen reference satisfies that condition, but the exact Case-B frame 0 is a lateral-profile,
  high-knee step/jog silhouette, so it does not. The package stopped before preprocessing, Comfy,
  or GPU work: no source/window/crop/reference change, calibration frame, Flux, `face_video`,
  retargeted control, or Animate generation occurred. A next package requires product-owner choice
  between enhanced retargeting with the exact comparator (`use_flux=True`) and a new compliant
  driving source for basic retargeting; **PR-VID-183 — COMPLETE / ACCEPTED / INTEGRATED —
  `BASIC_RETARGET_APPLIES; REFERENCE_BOUND_LOCOMOTION_NOT_DEMONSTRATED`** now closes that controlled
  A/B with a new, naturally compliant real-human source. Its fixed 8.000-9.625 s Mixkit #4856
  window produced distinct CPU-only controls for A (`retarget_flag=False`) and B
  (`retarget_flag=True`, `use_flux=False`) and exactly one frozen-graph Animate generation per arm,
  with no `face_video`, background mitigation, retries, or third generation. B called pinned
  upstream basic `get_retarget_pose` and changed the control materially, but rendered a cropped
  lower-body subject and exaggerated split-step/lunge rather than stable reference-bound walking;
  A was initially more complete but also distorted later. The product decision is not to continue
  tuning Wan2.2-Animate locomotion through basic retargeting, `face_video`, or FLUX enhanced-retargeting
  as the immediate next objective. This does not remove the qualification evidence or make Animate a
  general model NO-GO; see
  `docs/Subsystems/Video/PR-VID-183_Wan22_Animate_Basic_Retargeting_Controlled_AB.md`. VID-181's two
  clean generations occurred while DDR5-5600/XMP was still enabled and are not a DIAG-GPU stability
  PASS.
  `PR-VID-184 — Wan-Animate-2 Reference Capability, Target-Hardware & Integration Feasibility` is
  **COMPLETE / CLOSED — MODEL CAPABILITY UNKNOWN; REMOTE GATE BLOCKED_BY_SUBSCRIPTION; LOCAL
  TARGET-HARDWARE NO-GO AT THE FROZEN ENVELOPE**
  (`docs/Subsystems/Video/PR-VID-184_Wan_Animate_2_Reference_Target_Hardware_Integration_Feasibility.md`).
  Qualification/feasibility evidence only; no production `src/`, workflow, backend, queue, runner or
  GUI/controller change. Wan-Animate-2 (released 2026-08-07, Base + Distillation, Apache 2.0, raw
  driving video, two official Comfy workflows) is real, but **no Animate-2 output was ever produced,
  so its reference-bound locomotion, motion fidelity, identity, ghost-actor, anatomy and background
  behavior are UNKNOWN**. The remote official Comfy reference test could not be queued
  (`REMOTE_REFERENCE_GATE_BLOCKED_BY_SUBSCRIPTION`: *"A cloud subscription is required to queue
  workflows."*; Comfy's advertised free tier was not usable; no paid access was authorized, no cloud
  generation occurred) — an access outcome, not a capability failure. The one owner-authorized local
  attempt (isolated qualification-only ComfyUI 0.37.0 outside the untouched StableNew-managed Comfy;
  Distilled INT8 ConvRot, cache OFF, frozen reference, 39-frame/24 fps/1.625 s locomotion input with
  legal internal length 41, fixed seed, one submission) passed setup and graph validation, queued with
  zero node errors, then failed **mid-sampling, during the 10th of 10 sampler steps** (`hostbuf_file_reader_read failed`, raised from a weight-read call in the traceback, then
  CUDA unknown/sticky error) and left the GPU in a lost-device state requiring reboot, with Windows
  commit at approximately 95–98 % (previous accepted maximum in this line ~81.7 %). Classified
  `WAN_ANIMATE_2_LOCAL_TARGET_HARDWARE_NO_GO_AT_FROZEN_ENVELOPE — GPU_DEVICE_LOSS_DURING_SAMPLING`
  with secondary `WINDOWS_COMMIT_PRESSURE_EXTREME`: a hardware/resource-envelope NO-GO for that
  envelope only, **not a model NO-GO**; commit pressure and device loss co-occurred but causality is
  unproven. No output, no retry; the authorization is exhausted and no further Animate-2 GPU run is
  authorized. The ~25 GB aggregate on-disk model assets prove full simultaneous VRAM residency at
  on-disk size is impossible on 12 GB; actual runtime residency/offload behavior was not established.
  Wan-Animate-2 stays architecturally compatible with a future `backend_id=comfy` experimental
  workflow (no production contract change authorized). The next step is an owner ROI/product decision
  among remote capability adjudication (paid, separately authorized), 32→64 GB RAM, a higher-VRAM GPU,
  or deferring Animate-2; none is selected or authorized. This event was recorded as an additional
  GPU-loss observation in the DIAG-GPU-130 record without merging root-cause interpretation: no WHEA,
  Kernel-Power 41, 6008 or 4101 event was found in the inspected window, which does not prove a
  different cause and is not a stability PASS.
  `PR-VID-184R — Wan-Animate-2 Pinned-Memory / HostBuffer Re-adjudication`
  (`docs/Subsystems/Video/PR-VID-184R_Wan_Animate_2_Pinned_Memory_Readjudication.md`) is **COMPLETE**:
  one owner-authorized GPU submission of the exact PR-VID-184 frozen workload (same isolated
  ComfyUI 0.37.0 environment, same hashes, cache OFF, 39-frame/24 fps input, legal length 41) with only
  `--disable-pinned-memory` added. It **completed** (10/10 sampler steps, output produced, GPU healthy,
  no HostBuffer/CUDA error), where PR-VID-184 lost the GPU at step 10/10. Classified
  `WAN_ANIMATE_2_LOCAL_EXECUTION_PASS_WITH_PINNED_MEMORY_DISABLED` and
  `PINNED_MEMORY_PATH_MATERIALLY_IMPLICATED` — a contributor, not proven sole cause: one run against
  one run, with uncontrolled state differences (fresh boot; commit 34 → 57 % vs 58 → 98 %). This narrows
  PR-VID-184's configuration-specific local NO-GO (which stays an accurate record of its tested
  configuration) but is not a hardware clearance or a DIAG-GPU-130 result. The output (480×848, 41 frames
  trimmed to 39) passes three of four frozen gates (continuity 1.0, ghost 0, root translation 0.623) and
  misses `motion_curve_correlation` (0.151 vs 0.30); agent visual inspection shows a reference-looking
  subject carrying the motion with no ghost figure, no owner verdict yet — motion quality is PARTIAL,
  model capability PARTIAL and unadjudicated. No further GPU run or production integration is
  authorized; next steps are owner decisions.
  `PR-VID-184S — Wan-Animate-2 Matched-State Pinned-Memory B1→A→B2 Reproducibility`
  (`docs/Subsystems/Video/PR-VID-184S_Wan_Animate_2_Matched_State_Reproducibility.md`) is
  **COMPLETE**: the owner recorded `WAN_ANIMATE_2_OWNER_MOTION_VALUE_PASS` on the accepted PR-VID-184R
  output (kept separate from the automated `motion_curve_correlation` metric, which stays FAIL/PARTIAL
  at 0.151 vs 0.30). Three owner-authorized GPU submissions ran in order under a frozen matched-state
  protocol (commit ±3pp / RAM ±1.5GB / VRAM ±512MiB vs the Arm-B1 fresh-boot reference): Arm B1
  (`--disable-pinned-memory`) completed; Arm A (pinned memory enabled, matched-state gate passed)
  also **completed** this time — the original PR-VID-184 GPU loss did not reproduce; Arm B2
  (`--disable-pinned-memory` again) completed and decoded pixel-identical to B1. Classified
  `WAN_ANIMATE_2_LOCAL_EXECUTION_REPRODUCIBLE_WITH_PINNED_MEMORY_DISABLED`,
  `ORIGINAL_PINNED_MEMORY_FAILURE_NOT_REPRODUCED_UNDER_MATCHED_STATE`, and — recorded separately —
  `PINNED_MEMORY_RESOURCE_PRESSURE_EFFECT_REPRODUCED` (Arm A's commit peak 73.15% was 20.24 points
  above B1/B2's ~52-53%, past the pre-registered 10-point threshold, with RAM available falling to a
  low 1.94 GB minimum without tripping the safety stop). This weakens but does not eliminate the
  inference that disabling pinned memory is necessary for success on this workload; it is n=1 for Arm
  A and not a hardware clearance, not a DIAG-GPU-130 result, and does not rewrite PR-VID-184 or
  PR-VID-184R. No further GPU run (all three authorized submissions used) or production integration
  is authorized; next steps are owner decisions.
  `PR-VID-185 — Wan-Animate-2 Promotion Gate & Production-Readiness Adjudication` is **COMPLETE /
  TECHNICALLY NOT YET PROMOTION-READY / NO PRODUCTION INTEGRATION**
  (`docs/Subsystems/Video/PR-VID-185_Wan_Animate_2_Promotion_Readiness_Adjudication.md`). The owner
  `WAN_ANIMATE_2_OWNER_MOTION_VALUE_PASS` is preserved, as is the frozen
  `motion_curve_correlation` FAIL (0.139–0.151 vs 0.30). The metric is adjudicated as a useful
  non-blocking guardrail rather than a sufficient hard blocker because it measures global optical-flow
  motion-energy timing, not identity-bound product motion; the threshold and historical result remain
  unchanged. Pinned-OFF is the preferred tested configuration, but representative accumulated-state
  resource/usability evidence is still required before a separate owner-authorized experimental
  integration decision. No GPU/model/runtime action or production source change occurred.
  DIAG-GPU-130 remains XMP-OFF isolation in progress / observation only.
  `PR-VID-190 — Owned-Comfy Recycling After Each Job & Selectable Frame Count` is **COMPLETE /
  ACCEPTED / INTEGRATED** (`docs/Subsystems/Video/PR-VID-190_Comfy_Runtime_Recycling_and_Frame_Count.md`).
  The owner-reviewed "useful prompt-directed motion" clips were produced by Wan2.2 TI2V-5B
  (`wan22_ti2v_5b_i2v_v1@1.0.0`) on StableNew-managed ComfyUI, not by Wan-Animate-2, so that verdict
  is not an Animate-2 result. The queue failure after each success was a missing per-job release: the
  StableNew-owned Comfy stayed resident holding its models, and the unchanged 16 GB readiness floor
  correctly failed the next job. `wan22_ti2v_5b_i2v_v1@1.1.0` declares a release-after-job runtime
  policy (only an owned process, only via `ComfyProcessManager.stop()`) and a neutral, frozen-at-
  admission frame count (legal `4n+1`, 17-81, default 49, fixed 24 fps); `@1.0.0` stays byte-identical
  for replay. Real acceptance queued three jobs (49/81/49 frames) through the canonical queue and ran
  them back to back with no manual kill: three fresh owned Comfy PIDs, each released, RAM recovered
  to ~24.5 GB before the next job, all COMPLETED, 81 frames (3.375 s) at ~11.7 GB peak VRAM.
  Wan-Animate-2 experimental exposure on managed ComfyUI is the separately-sequenced next part.
  `PR-VID-191 — Managed ComfyUI v0.37.0 Runtime & Experimental Wan-Animate-2` is **COMPLETE /
  ACCEPTED / INTEGRATED** (PR #24; required Python 3.11/3.12 CI passed)
  (`docs/Subsystems/Video/PR-VID-191_Comfy_v037_Runtime_and_Wan_Animate_2.md`). The
  acceptance runs used the PR-VID-184R/S-qualified ComfyUI v0.37.0 install (the desktop app's
  v0.3.65 cannot load Animate-2) as a machine-local, uncommitted managed-Comfy configuration with
  StableNew-owned runtime folders and `--disable-pinned-memory`; tracked `presets/settings.json` is
  unchanged;
  TI2V-5B re-verified there (3 queued jobs, faster, no host-memory pressure). Two experimental
  Wan-Animate-2 workflows (prompt motion; driving-video motion) are registered from the qualified graph
  and exercised as three queued jobs (41/81/41 frames) with per-job runtime release. Prompt mode
  produced clean motion. Driving-video mode is `ANIMATE_2_DRIVING_VIDEO_EXECUTION_PASS /
  PRODUCT_QUALITY_PARTIAL — DUPLICATE_SUBJECT_ARTIFACT OBSERVED`: the control path executes, but a
  duplicate subject appeared in its one sample (likely the dropped separate motion prompt), so
  driving-motion quality is not accepted. A `LoadVideo` input-preview artifact-selection defect
  was found and fixed. Review also added a dispatch-time check that the driving-video file still
  matches its admission-frozen SHA-256, so a clip changed after queue admission is rejected before
  upload and dispatch. The final v0.37.0 job finished at about
  08:33 ET on 2026-09-29; display watchdog reports followed at about 08:42 and 15:02 with no
  evidenced active generation. They do not invalidate the completed clips or establish a Comfy
  cause. Workstation display stability remains unproven, so the desktop ComfyUI upgrade awaits the
  owner's stability decision.
  `PR-VID-192 — Animate-2 Control Truth & Motion Experimentability` is **COMPLETE / ACCEPTED /
  INTEGRATED** (PR #25; required Python 3.11/3.12 CI passed)
  (`docs/Subsystems/Video/PR-VID-192_Animate2_Control_Truth.md`). The generic Motion selector
  (`gentle`) never reached Animate-2: neither workflow
  declared `motion_profile`, so it is now hidden for workflows that do not honor it. New `@1.1.0` workflows
  bind only controls the pinned ComfyUI v0.37.0 node actually honors: a distinct Motion Prompt wired to
  `positive_pose`, pose strength, the pose window and reference-image strength (defaults equal the node's own);
  prompt mode is described honestly as exploratory (no driving video, so the pose branch is skipped). `@1.0.0`
  stays byte-identical for replay. The stock negative prompt has no effect at CFG 1.0 and is unchanged. A small
  qualification-only motion-source corpus and a one-variable experiment suite were added. The four-arm GPU experiment
  ran once the GPU was free: the separate motion prompt removed the duplicate subject (ghost persistence 28 to 0 of
  39) but the driven locomotion disappeared with it, and pose strength 1.5 / reference strength 1.3 did not restore
  it. Driving-motion quality therefore remains `EXECUTION_PASS / PRODUCT_QUALITY_PARTIAL` pending owner review.
  `PR-VID-194 — One-Variable Operator Experiments` is **IMPLEMENTED / VERIFIED / INTEGRATED** (PR #28, merge
  `9688c5a`; `docs/Subsystems/Video/PR-VID-194_Animate2_One_Variable_Operator_Experiments.md`).
  Video Workflow gains a bounded "Compare one control" section: the current resolved value of one spec-declared
  operator control (Variant A) plus 1-3 candidates, one frozen baseline (one concrete seed, source and driving-video
  hashes), every arm built through the same extracted `VideoWorkflowNjrBuilder` as a normal submission with the
  existing `LearningJobContext`, a fail-closed controlled-diff gate, and a single `JobService.submit_njrs` call.
  No new experiment store, queue or lifecycle authority, no automatic search or winner selection, and Wan-Animate-2
  stays experimental per-job opt-in. Validation is CPU/fake-runtime only; no physical generation was run and no
  promotion or readiness conclusion changed.
- `PR-GUI-100 — Responsive Workspace & Reachable Controls Foundation` is **IMPLEMENTED / VERIFIED LOCALLY / READY FOR
  OWNER REVIEW; NOT PUSHED** (`docs/Subsystems/GUI/PR-GUI-100_Responsive_Workspace_and_Reachable_Controls.md`). The main
  window no longer demands a viewport larger than the display: `src/gui/view_contracts/window_layout_contract.py` is the
  single screen-aware authority for the default size, the minimum size and saved-geometry normalization (Pipeline's
  separate 1400 px width force is retired). Review, SVD Img2Vid and Video Workflow scroll through the existing
  `ScrollableFrame`, whose mouse-wheel handling is now one pointer-routed dispatcher per Tk interpreter. No generation,
  queue, backend, NJR, runtime or persistence behavior changed. The Pipeline uses its normal three-column presentation
  when its current Tk-rendered layout fits and otherwise a reversible compact presentation (measured fit, not a fixed pixel
  breakpoint: lower form column minimums chosen by fit, capped label wraps, reflowed hint/ADetailer cells; no widget moves),
  so no actionable control is clipped at laptop widths or in other Tk/font environments. Known debt (GUI-110 visual
  density): the scroll viewports stay short at 768 px height because fixed headers and the Operator Log sit outside them.
- Exact branch/head state must be verified from GitHub before planning or executing work.

`main` is the integrated v2.6 release baseline and now contains the accepted
PR-MVP-090 line.
The canonical documentation order is `AGENTS.md`, `STATUS.md`,
`docs/CODEX_MAP.md`, the relevant architecture section, the relevant coding and
testing section, the roadmap for sequencing, and Git history only when current
evidence is insufficient or history is explicitly requested.

## Product state

StableNew has one queue-first NJR/runner spine, transactional SQLite lifecycle
state, versioned JSON PromptPack storage, and accepted image and native SVD XT
vertical slices. PR-MVP-060 is **COMPLETE / ACCEPTED**. PR-MVP-070 is
**COMPLETE / ACCEPTED**. PR-MVP-080 is **COMPLETE / ACCEPTED / INTEGRATED**.
PR-MVP-090 is **COMPLETE / ACCEPTED / INTEGRATED**.

The runtime invariant remains:

`Intent -> Compiler -> NJR -> JobService -> Queue/Repository -> PipelineRunner.run_njr -> Handler -> Artifacts/History`

Fresh work is queued, NJRs are immutable, lifecycle state belongs to queue and
history, replay creates a new NJR with lineage, and GUI/controllers do not
create an alternate runner path.

`main` now contains the accepted PR-MVP-080 operator-readiness, PR-MVP-090
release-proof, and PR-IMG-100 backend-neutral image lines. The v2.6 MVP/release
proof is complete. PR-IMG-110 is complete: generic Diffusers qualification
passed. Its Ideogram 4 NF4 no-go was corrected by PR-IMG-110R: with the official
code and Diffusers 0.40.0, Ideogram 4 NF4 runs on the RTX 4070 Ti 12-GB up to
1024x1024 `V4_QUALITY_48` (about 60 s at 768x1024 Turbo, 279-312 s at 1024x1024
Quality) but only with an explicit GPU residency policy (text encoder first, one
transformer resident at a time); the shipped all-resident and documented offload
paths spill into shared memory and are impractical. IMG-120 is not authorized; it is
eligible for a separate product-owner decision (architecture: custom residency
lifecycle and exclusive GPU lease; structured-JSON prompt mapping; Ideogram 4
non-commercial license). Details: `docs/Subsystems/Image/PR-IMG-110R_Ideogram4_Requalification.md`.

PR-SVD-100 is the complete / accepted / integrated post-v2.6 SVD
submission-convenience package on `main`. It adds non-recursive folder planning and one
normal queue batch submission while
preserving the accepted SVD runtime, backend, queue, history, replay, and
artifact authorities.

PR-RUNTIME-100 is **COMPLETE / ACCEPTED / INTEGRATED** and adds no queue, lifecycle, scheduler, lease, or backend-selection
authority. Its one coordinator delegates release only to `WebUIProcessManager`,
`ComfyProcessManager`, and `SVDService` at the A1111, Comfy, and native-SVD
backend preparation seams. A failed owned release blocks dispatch; a read-only
configured endpoint probe classifies a live/occupied unmanaged conflict as
action-required and never mutates it. Its acceptance record
is `docs/Subsystems/Runtime/PR-RUNTIME-100_Owned_Runtime_Transition_Policy.md`.

PR-LEARN-300 is **COMPLETE / ACCEPTED / INTEGRATED**. Its evidence-integrity and workflow slices give Designed
image experiments one durable experiment identity and an immutable preview
snapshot of effective prompt, model/VAE, stage configuration, tested variable,
values, sample count, and a concrete requested seed. Backend-returned seed
vectors establish then validate controlled evidence across variants; they are
not inferred from batch arithmetic. PromptPack work resolves only Matrix
variables referenced by the selected row, freezes the first canonical vector
even when the pack normally uses random mode, and records Matrix as unused when
the selected row references no tokens. All variants compile before one normal
`JobService.submit_njrs` admission; each admitted NJR retains its ordinary
independent SQLite queue lifecycle. Ratings retain exact experiment/variant,
job/artifact, and frozen executed-configuration evidence. Controlled ratings
may recommend only the deliberately tested variable; incomplete historical rows
remain readable but are excluded from recommendation inference. Learning remains image-stage-only, cannot mutate
PromptPacks/NJRs/history, and has no autonomous tuning authority. Resource-backed
Model/VAE/Sampler/Scheduler choices now use the live `AppStateV2` projection and
refresh path. Learning outputs retain full experiment identity in metadata while
using readable experiment-folder and artifact-name labels; all variants of one
experiment remain grouped. Learning filenames include frozen source/prompt row,
model, timestamp, variant, and sample identity. Editable Working Draft state
autosaves independently; only experiments that cross queue admission enter the
default Experiment Library, while old never-run entries remain non-destructive
Draft/Legacy Draft data. Discovered scanner groups have durable origin, expose
total/available/missing counts, use distinct restorable Done and Dismiss
decisions, fit their image preview to a majority-width adjustable review
workspace, and support previewed Clean Missing References and rebuild operations
that preserve controlled/imported worksets and terminal operator decisions. The
review workspace now groups completed samples by
variant/value, exposes rated state and per-variant summaries, supports deterministic
Next Unrated and side-by-side comparison, and preserves the selected target during
background completion. Experiment conclusions derive from saved sample ratings,
exclude drafts, and cannot name a causal winner when controlled seed evidence is
invalid. The ambiguous Resume Last, primary generic recent-record Tags editor,
and global header Automation selector are no longer primary Learning actions.
Staged Curation can preview learned settings and, after confirmation, apply an
allowlisted patch only to one newly built derived-job intent before its normal
NJR/JobService submission.
`PR-VID-110` directed-motion qualification evidence is recorded in
`docs/Subsystems/Video/PR-VID-110_Directed_Motion_Qualification.md` (qualification only, no
integration): on the RTX 4070 Ti 12-GB, Wan2.2 TI2V-5B (stock Comfy) is **CONDITIONAL**
(gesture-level directed motion with identity preserved, ~1 min per 2 s clip, VRAM near the
ceiling); Wan2.1 VACE-1.3B is **NO-GO** for identity preservation in reference-only,
stock-Canny and pose-skeleton-only control modes (pose control removes the scene/silhouette
leak and gives clean anatomy but the source person is still not reproduced, so the limit is
VACE's reference binding); SCAIL-2/Wan Animate 2 are deferred (14B, no credible 12-GB
path). Wan2.2 is the only currently qualified directed-motion candidate. A GPU loss during
qualification is one of 15 hard resets on the workstation since 2026-09-07. The
read-only correlation record has no SQLite job active at any exact incident
timestamp; nearby lifecycle correlation is reported separately (one incident
has eight jobs that all started after the incident). It has contemporaneous
StableNew-captured A1111 CUDA failure/progress evidence for 11 incidents and
does not attribute cause to StableNew. Exact-time absence alone does not
establish that earlier StableNew execution could not have participated in a
failure sequence. See
`docs/Subsystems/Runtime/DIAG-GPU-100_Hard_Crash_Correlation_and_Survivor_Telemetry.md`.
The read-only dump attribution follow-up is
`docs/Subsystems/Runtime/DIAG-GPU-110_Windows_Dump_Attribution.md`; it selects no
remediation. DIAG-GPU-120 records the already-performed one-variable transition from XMP
DDR5-6000 to XMP DDR5-5600; it does not disable XMP or establish a JEDEC baseline.
Whether to integrate any candidate is a product-owner decision; native SVD remains the
only accepted video backend.
Current Global Positive/Negative text and enablement are frozen into each
compiled NJR (Learning, PromptPack, and generic jobs) rather than read at
execution. A `LoRA Strength` variant rewrites the executable prompt, and
controlled evidence requires the executed-prompt readback to show the requested
weight in addition to the frozen seed vector; incomplete historical LoRA ratings
stay readable but non-evidentiary.
Final operator acceptance is **PASS**: controlled seed proof (three CFG variants,
frozen seed `12345`, each returning `all_seeds=[12345]`), the responsive
Experiment Design / Plan / Review workflow, current Global Prompt execution in
the real app, and a real LoRA Strength experiment with actual execution/readback.

`PR-LEARN-302` is **COMPLETE / ACCEPTED / INTEGRATED**. It makes Discovered Outputs scanning incremental for newly classified
artifacts (`src/learning/discovered_scan_service.py`): members of a newly created
eligible group are indexed with their deterministic group id only after the group
is saved, and invalid manifests and controlled-experiment artifacts are indexed
ineligible. Artifacts still waiting for enough siblings stay unindexed so they can
form a group later, and a grouped manifest changed later stays reconsidered (its
stored key is not advanced). Pre-existing scanner groups that lack trustworthy
scan-index entries are deliberately not backfilled, because persisted items cannot
prove they still match the manifest (VAE, denoising strength, clip skip, LoRA and
ADetailer model are not stored); they are rescanned, without duplicating or
rewriting the group, until `Rebuild Scanned Inbox` reconciles them. Artifacts
identical in generation parameters to a grouped sibling (deduplicated) are also not
indexed. This is conservative correctness, not a gap in new-group incremental scanning.

`PR-TEST-OPERATOR-110` is **COMPLETE / ACCEPTED / INTEGRATED**. It adds the `discovered-outputs-review` operator journey
(`python -m tools.operator_journey discovered-outputs-review`): synthetic outputs
in the disposable workspace, then Rescan, Review, observational rating,
Done/Restore, Dismiss/rescan/Restore, missing-artifact handling, Clean Missing
References and Rebuild Scanned Inbox through the real Tk controls. The earlier
"scanner reads production output" observation was the crash-bundle image scan
using a repo-root constant; it now uses the workspace root, and the isolation spy
fails a journey on any read or listing of the real `output/` tree (0 in the
accepted run).

`PR-LEARN-301` is **COMPLETE / ACCEPTED / INTEGRATED**: structured/composite
experiment values (e.g. LoRA Strength `{"name", "weight"}`) are supported in both
`RecommendationEngine` and `LearningAnalytics` through the shared canonical
value-identity helper `src/learning/value_identity.py`; the semantic GUI journey
opens the real View Analytics window and verifies the summary.

`PR-TEST-OPERATOR-100` is **COMPLETE / ACCEPTED / INTEGRATED**. Semantic GUI
operator journeys are now the preferred mechanical real-GUI acceptance mechanism
wherever a journey exists. It adds `python -m tools.operator_journey <journey>`: a
semantic Tk driver plus isolated workspace and evidence bundle that operates the
real V2 GUI and only observes the production queue/SQLite/runner/backend path.
The reference journey `learning-lora-strength` passes end to end against the
fake-backend seam: Build Preview Only, Run Experiment, queue/SQLite/runner
execution, seed and LoRA readback validation, Review ratings, and
recommendation/conclusion projection. Its rating step exposed that
`RecommendationEngine` could not group composite variant values; it now groups
structured values by a canonical key (`src/learning/value_identity.py`) and
returns the original structured value. An access spy proves the journey never
opens or writes production SQLite/state/presets. The real-A1111 run of
`learning-lora-strength` is **PASS**: three completed jobs at frozen seed
`12345`, executed LoRA tokens none/`1.0`/`2.0`, controlled evidence, ratings
3/4/5 persisted through the Review GUI, structured recommendation handling, no
captured Tk/thread errors, bounded graceful shutdown, and the operator's loaded
checkpoint unchanged. The harness never starts, adopts, or stops A1111.

## Approved post-v2.6 direction

The first approved post-v2.6 architecture PR, `PR-IMG-100 — Backend-Neutral
Image Execution`, is complete / accepted / integrated. The accepted course of
action is **one typed image backend per image NJR**.
A1111/WebUI remains the default/current production image backend and its accepted
behavior must be preserved behind the new boundary. Newly compiled image NJRs
will explicitly persist image backend identity through the existing immutable
`backend_options` workload layer; historical v2.6 image NJRs that lack backend
identity will resolve deterministically to A1111 through one bounded compatibility
rule.

`PR-IMG-100` does not implement Ideogram, Diffusers image inference, ComfyUI
still-image execution, or per-stage backend composition. PR-IMG-110 established
that the generic Diffusers substrate is viable, and PR-IMG-110R (correcting its
Ideogram 4 no-go) that Ideogram 4 NF4 is constrained-viable on the RTX 4070 Ti
12-GB target with an explicit residency policy; neither authorized a Diffusers backend.
Per-stage backend composition (COA C) and ComfyUI-centric image execution (COA D)
remain possible future options, but neither may replace StableNew's compiler,
NJR, queue, runner, artifact, history, replay, cancellation, or process authorities.
The full approved acceptance contract and phased Codex prompts are in
`docs/Subsystems/Image/PR-IMG-100_Backend-Neutral_Image_Execution.md`.

## Accepted PR-MVP-080 work

Accepted 080 work includes source-aware SVD target selection, readiness
projection/UI, truthful SVD preset state, explicit SVD geometry enforcement,
HARDEN-009 runtime timeout/watchdog corrections, canonical txt2img cancellation
deterministic proof, a real A1111 operator-cancellation PASS, and the
cancellation/result-publication race repair at
`d2909e752faaa34f20a49fccc9865a8412c21b15`. R1D managed / external WebUI stall
policy is integrated on the active PR-MVP-080 branch.

The cancellation repair keeps terminal result publication behind durable
`RUNNING` ownership. SQLite remains the lifecycle and result authority; a
cancellation or return-to-queue decision that wins before late backend
publication prevents successful result data, artifact references, and
`final_output` checkpoints from being promoted. Normal success, return-to-queue,
and replay lineage remain unchanged. No lifecycle, schema, architecture, or
generic image-output cleanup authority changed. Bytes already written by a
cancelled backend may remain as non-authoritative residue when safe bounded
cleanup is unavailable.

Repair-SHA validation recorded 31 focused queue/repository tests passed and 10
cancellation/replay tests passed. An additional adjacent batch had 27 passed
with 14 unrelated legacy fixture/model-constructor failures. Ruff remained at
the existing non-increasing baseline and the changed test was clean; the
controller ratchet was not applicable. One PR-gate attempt was blocked because
the gate environment could not find local `mypy`. No real A1111 cancellation
rerun was performed because the existing external API was unreachable and was
correctly not launched, adopted, or restarted. No GitHub Actions run exists for
this exact repair SHA, so no Python 3.11/3.12 CI-green claim is made for it.

R1B real-A1111 evidence used WebUI v1.10.1. Operator cancellation during active
sampling worked with one generation POST and one interrupt; SQLite recorded
`CANCELLED`, and no artifact was resurrected.

R1D contracts are ownership-sensitive. For managed A1111, StableNew may restart
only the tracked process that StableNew launched, and only after a proven
post-interrupt wedge. For external A1111, StableNew may use supported
API/progress/interrupt operations but never adopts, kills, or restarts the
process. A stalled external runtime surfaces operator action required.

The canonical `run_img2img_stage` now uses the existing shared
progress/cancellation authority. Active img2img cancellation is deterministically
proven with one generation POST, one interrupt, persisted `CANCELLED`, no
promoted artifact, no later pipeline stage, no process restart/retry, and no
resurrection when a late response succeeds.

Conservative interrupted-job recovery is **PASS / ACCEPTED**. SQLite remains the
single lifecycle/history authority. Jobs persisted as `QUEUED` before restart
remain queued/runnable in durable order. Jobs persisted as `RUNNING` at process
loss have an ambiguous execution outcome: they are never automatically
requeued or replayed, and become terminal `FAILED` records with the machine-
identifiable `INTERRUPTED_RESTART_ACTION_REQUIRED` reason. `FAILED` is the
durable lifecycle encoding, not proof that backend generation definitely
failed. The record requires operator review and preserves available NJR,
fingerprint, lineage, timestamps, execution metadata, checkpoints, results,
artifacts, and diagnostic evidence without incrementing return-to-queue count.
Only genuine queued rows enter the restored runnable projection, so auto-run
cannot dispatch the interrupted record. Pipeline history renders it as
`Interrupted`; explicit Replay remains opt-in and creates new authorized work
with a new NJR/job identity and parent lineage, while the original remains
terminal history. Operator Readiness surfaces persisted interrupted-restart
records as action-required; no acknowledgement mechanism is documented or
assumed. No new SQLite schema/version or second lifecycle authority was
introduced. The former automatic `RUNNING -> QUEUED` restart behavior is
superseded.

Queue/history action-state and no-op cleanup is **PASS / ACCEPTED**. Live Queue
controls now combine legal queue state with callable controller capability.
Manual Send Job remains available with Auto-run OFF when queued work exists, the
queue is unpaused, no job is running, and the manual dispatch boundary exists.
Auto-run and Pause/Resume are not presented as operable without their
application boundaries; reorder, remove, and clear remain restricted to legal
queued work. Direct, keyboard, and stale callback paths re-check legality, and
Remove/Clear do not report success when the underlying action reports no change
or failure.

The live Pipeline Job History surface is `src/gui/job_history_panel_v2.py`.
History actions combine callable controller capability with real persisted,
artifact, and replay evidence. Open Output Folder requires a real surviving
output location; Replay requires a reconstructable persisted NJR, while valid
interrupted-restart records remain explicitly replayable through the existing
new-NJR/lineage rules. Animate with SVD requires a real existing still-image
artifact. Video Workflow and Movie Clips require usable surviving handoff
evidence, Explain requires its callable boundary, and buttons/context-menu
actions share the same predicates. Canonical direct-image artifact discovery
was aligned in the existing AppController handoff helper without adding
controller responsibility. No SQLite, lifecycle, replay-architecture,
acknowledgement, backend, or GPU behavior changed.

## Current acceptance state

PR-MVP-090 Phase 0 runtime/bootstrap is **COMPLETE / ACCEPTED**. The supported
Windows Python 3.11/3.12 bootstrap is repository-owned, and its CUDA-enabled
Torch installation order is encoded. Disposable bootstrap validation passed on
the RTX 4070 Ti, and check-only validation passed on the established runtime.
The accepted runtime evidence includes:

- Diffusers `StableVideoDiffusionPipeline` is available.
- FFmpeg and ffprobe execute through the production resolver.
- The accepted plain XT is detected through the production cache authority.
- Phase 0 acceptance verified that the effective operator profile matched the
  `Recommended 12GB / XT 14f` baseline at acceptance time: plain XT,
  production default per-user Hugging Face cache, 14 frames, 7 fps, 25 steps,
  motion bucket 48, noise 0.01, decode 2, Match Source Aspect with
  `center_crop`, local-only true, and all postprocess stages OFF.
- Production local-only SVD preflight passes with no blockers or warnings.
- No model download or SVD inference was required for Phase 0.
- Required GitHub Python 3.11/3.12 CI, including mypy and smoke gates, passed.

Local PR-gate execution was blocked by missing local `mypy`; the required
GitHub mypy/smoke gates passed, so this is not an active blocker. Zero NJR
submissions and zero SVD inference jobs occurred during Phase 0.

The PR-MVP-090 release-harness integrity checkpoint is **COMPLETE / ACCEPTED**.
The modern NJR journey now uses the immutable NJR contract and traverses
`JobService.submit_njrs` through a temporary SQLite queue/repository and the
production controller-to-runner bridge; history is read back from that
repository rather than synthesized. Shutdown journeys disable backend
autostart, use bounded unavailable endpoints, and inspect only test-owned
processes. Process cleanup is ownership-scoped, so unrelated user A1111,
ComfyUI, and Python processes are ignored and never targeted. Bootstrap and
journey wrappers retain the approved interpreter/dependency normalization.
Focused release-harness validation passed; the disposable `.venv-release-proof`
was removed after confirming no process used it.

The PR-MVP-090 raw-Ruff hygiene checkpoint is **COMPLETE / ACCEPTED**.
Pinned Ruff 0.14.9 found 3,553 active findings on the feature tree; after
reviewed mechanical cleanup and narrow defect repairs, `ruff check .` is zero.
The legacy baseline file and baseline-comparison gate were removed. The local
PR gate and required CI now enforce raw `ruff check .` directly. Controller
ceilings were not increased; the AppController ceiling was tightened by one
physical line. StableNew CI run 328 passed both required Python 3.11 and 3.12
jobs; informational full-suite legacy failures remain non-blocking.

The managed-runtime ownership safety repair is **COMPLETE / ACCEPTED**.
WebUI launch now refuses an occupied configured endpoint without killing or
adopting its process. Stop, restart, orphan monitoring, process-container
teardown, and emergency cleanup require explicit manager ownership and may act
only on the launched root and proven descendants. ComfyUI now has ownership
parity: bootstrap uses an existing healthy external endpoint unmanaged without
launching a duplicate, rejects an occupied invalid endpoint without killing or
replacing its occupant, and launches only when the configured endpoint is free.
The same explicit ownership gate protects ComfyUI cleanup and restart. Machine-
wide port, working-directory, process-appearance, and orphan/reparented-process
kill scans are no longer automatic authorities. Focused ownership/lifecycle/
recovery validation passed using fakes and test-owned disposable processes only.
StableNew CI run 330 passed both required Python 3.11 and 3.12 jobs;
informational full-suite legacy failures remain non-blocking. The legacy test's
live `atexit` registration and global-state leak are confirmed; whether that
callback caused the previously observed external runtime disappearance remains
unresolved.

XT 1.1 remains a distinct supported model and must not be substituted for the
accepted plain-XT baseline merely because it is cached.

The earlier stopped portrait attempt is historical context only; it found local
effective-state drift and submitted no work. After normalization through the
existing UI-state authority, portrait source-aware native-SVD acceptance is now
**PASS / ACCEPTED**. A real StableNew source artifact at `832x1216` selected the
deterministic `640x960` target. The prepared image was exactly `640x960`,
resized and center-cropped without padding. The conservative plain-XT profile
was used: 14 frames, 7 fps, 25 steps, motion bucket 48, noise 0.01, decode 2,
CPU offload and forward chunking enabled, local-only enabled, canonical
production Hugging Face cache, and all postprocess stages disabled.

The fresh job was submitted through the public application/controller boundary
and canonical queue-first `JobService` / SQLite / `PipelineRunner.run_njr`
spine. SQLite job `a46863c56b9e4d8cba8925e96edcb18d` reached `completed`; its
artifact, manifest, preview, and repository result agreed. The MP4 was
non-empty and decoded at `640x960`, `7/1` fps, with exactly 14 frames. Visual
inspection confirmed portrait orientation, plausible center crop, and no
evident stretch or squash. The physical GUI button was not used because the
desktop bridge was unavailable; the approved public submission boundary was
used instead. No production or test source changes were required.

RIFE interpolation semantics are **PASS / ACCEPTED**. RIFE is an optional
native-SVD temporal-smoothing postprocess, not slow motion. MVP operators may
use only 2x or 4x: output frames equal base frames multiplied by the factor,
and output FPS is multiplied by the same factor. Thus 14 frames at 7 fps
becomes 28 at 14 fps for 2x or 56 at 28 fps for 4x; disabled RIFE remains at
the base cadence. Unsupported factors such as 3x are rejected before SVD
model preparation or inference. Effective artifact FPS propagates through
MP4/GIF export, `SVDResult`, manifest/history, and embedded container metadata;
immutable SVD configuration retains base generation FPS. Postprocess metadata
records explicit input/output counts and FPS plus the duration-preserving
semantics. Exact output counts are validated, including the bounded
compatibility path for existing non-v4 RIFE runtimes.

A bounded real RIFE-only check used the accepted 14-frame SVD artifact: 14
frames at 7 fps and 2.00 seconds became 28 frames at 14 fps and 2.00 seconds.
The installed runtime rejected custom `-n`, so the compatibility fallback was
exercised; visual smoke inspection showed no obvious corruption. No SVD
inference, model/runtime download, or queue submission occurred. No GitHub
Actions run is associated with the RIFE commit, so its Python 3.11/3.12 CI
status must not be represented as passed.

Portable native-SVD MP4 provenance and parent artifact lineage are **PASS /
ACCEPTED**. Native-SVD MP4 artifacts embed machine-readable immutable audit /
recovery evidence under `stablenew.video-provenance.v2.6`. The payload uses
canonical JSON, with raw storage for smaller payloads and gzip/base64 for
larger payloads, and verifies its payload SHA-256. It preserves the exact
source-image byte SHA-256, valid embedded StableNew image provenance when
available, current NJR SHA-256 when available, authorized parent job/artifact
IDs, complete SVD configuration, actual preprocess/postprocess results, and
effective RIFE frame/FPS values. Missing, omitted, or corrupt source
provenance is explicit rather than fabricated. The MP4 video media/elementary
stream has an independent SHA-256 that was verified unchanged across metadata
remux; this is not a whole-MP4 file hash. Existing public container metadata
remains available, and the SVD JSON sidecar carries a matching summary.
Failure to embed, read back, or verify required provenance fails SVD export and
uses the existing partial-output cleanup. SQLite remains the live queue,
repository, and history authority; embedded provenance does not authorize
replay or automatically restore history, and paths remain convenience
references rather than durable identity.

A bounded real FFmpeg-only acceptance exercised the production `SVDRunner` with
temporary frames and a fake SVD service. Payload read-back and SHA verification,
source and media hashes, sidecar coherence, isolated MP4-only lineage recovery,
and ffprobe validation of 14 frames at 7 fps all passed. No model download,
GPU/SVD inference, or queue submission was required. Focused validation was
`74 passed`; the local standard PR gate remains blocked by missing local
`mypy`. No GitHub Python 3.11/3.12 CI result is claimed for the provenance
commit `b33d028473f905747ddc19ae394526f5e6531fe8`.

## Remaining sequence

PR-MVP-080 is **COMPLETE / ACCEPTED / INTEGRATED**. The final operator journey
passed: Rob manually verified one normal queue-first run with Auto-run OFF and
a second back-to-back run; both completed successfully. Previously accepted
queue/history, replay-lineage, cancellation, shutdown-persistence, SVD, and
provenance evidence remains valid. The accepted feature line was fast-forwarded
into `main` without a merge commit, rebase, or force push. StableNew CI run 317
passed on the accepted source tree, including required Python 3.11 and 3.12.

1. Maintain the accepted v2.6 and IMG-100 baseline pending explicit product-owner direction.

## Current execution frontier

Operational posture is **one active implementation package at a time**. The
former Lane A/B/C concurrent-lane model is retired; those labels now describe
backlog/topic categories only, not staffed parallel work. A single
short-lived branch/workspace lands, validates, and merges before the next
package starts.

Recently landed under this posture:

- `PR-TEST-TRUTH-120` (test-truth repair) and its `PR-TEST-TRUTH-121`
  follow-up are **COMPLETE / ACCEPTED / INTEGRATED**.
- `DIAG-GPU-130` closeout is **COMPLETE / ACCEPTED / INTEGRATED** (current
  platform-baseline truth remains under "Active diagnostic evidence" above;
  the incident record is not restated here).
- `PR-ASSET-120 — Provenance-Rich Asset Metadata Enrichment and Compatibility
  Profiles` is **COMPLETE / ACCEPTED / INTEGRATED**: `src/assets/registry.py`
  moved to a v2 cache with per-location `.civitai.info` sidecar evidence
  (independent of model-byte freshness), and new `src/assets/compatibility.py`
  derives a conservative, observational `CompatibilityProfile` (narrow
  `sd1`/`sd2`/`sdxl`/`sd3`/`flux` family, or explicit `unknown`/`conflicting`)
  from embedded and sidecar metadata. It adds no recommendation, GUI, or
  live-A1111 behavior.
- `WP-PACK-AUDIT-100 — PromptPack & Saved-Settings Quality Census` is
  **COMPLETE**: a new offline, read-only `tools/promptpack_quality_census.py`
  examined the real per-user PromptPack directory (39 files) and the active
  presets directory (18 standalone presets) against the real configured WebUI
  root, producing 1,020 findings with zero source mutation (fingerprint-
  verified before/after across the initial run and a one-pass correctness
  repair that fixed a crash-prone scalar-container case, an overbroad
  asset-coverage criterion, missed top-level checkpoint/VAE/refiner and
  boolean-enablement aliases, a falsy-`preset_data` validation gap, and the
  standalone-preset examined undercount). Full results:
  `docs/Subsystems/PromptPacks/WP-PACK-AUDIT-100_PromptPack_Saved_Settings_Quality_Census.md`.
  Headline evidence: the large majority of asset references resolve cleanly
  (481 `resolved_unique`); a systematic `pipeline.adetailer_enabled` vs
  `adetailer.enabled` contradiction recurred identically across five real
  sources; 24 references are genuinely missing their file-backed asset
  (including one literal stringified `"None"` placeholder); and naming-hygiene
  debt (duplicate/mismatched pack names) is cosmetic, not correctness debt.
  No PromptPack, preset, or asset was modified; no recommendation or warning
  UX was added.
- `PR-PACK-110 — ADetailer Stage-Enablement Persistence Repair` is
  **COMPLETE / ACCEPTED / MERGED**: new
  `synchronize_adetailer_enablement()` in `src/utils/config.py` makes
  `pipeline.adetailer_enabled` the persisted stage-membership authority and
  keeps `adetailer.enabled`/`adetailer.adetailer_enabled` synchronized with
  it in `_merge_config_with_defaults()` and `save_pack_config()`, without
  changing stage-sequencer OR-based runtime admission. (Review caught one
  real regression before merge — synchronizing after, rather than before,
  the defaults merge could mistake a default-filled `false` for explicit
  intent on a section-only config — fixed by synchronizing the caller's raw
  input first.) Re-checking the five sources WP-PACK-AUDIT-100 flagged found
  only one (`SDXL_epic_structures_Fantasy`) is a canonical PromptPack; the
  other four (`Juggernaut_MedievalHeroes_RandomizerAligned_v1b`,
  `Photoreal_Character_Juggernaut_SDXL`, `Testing`, `default`) are standalone
  `presets/*.json` recipes carrying the identical saved-setting defect. The
  owner subsequently authorized reconciling all five within this same
  package. Each was backed up byte-exact (with manifest) and reconciled with
  a semantic-diff guard proving the only change per file was
  `adetailer.enabled: false -> true`; a full 59-file fingerprint confirmed
  every other PromptPack/preset was untouched throughout. Rerunning the
  unmodified census confirmed all ten original
  `saved_setting_stage_contradiction` findings across all five sources are
  now gone, with zero new findings (total census findings 1,020 -> 1,010).
  Details: `docs/Subsystems/PromptPacks/PR-PACK-110_ADetailer_Stage_Enablement_Persistence_Repair.md`.

- `PR-PACK-120 — Missing Asset Reference Triage & Reconciliation-Decision
  Preparation` is **COMPLETE / ACCEPTED / MERGED**: new offline, read-only
  `tools/missing_asset_reference_triage.py` re-opened all 24 real
  `missing_file_backed_asset` sources and mapped each aggregated census
  finding back to its exact raw JSON occurrence(s) -- 24 triage items across
  16 PromptPacks, 134 total occurrences, 0 unmapped/stale, 4 literal
  `"None"`-placeholder items -- with same-asset-kind-only deterministic
  candidate evidence and Asset-120 family context attached, and a
  `decisions.template.json` defaulting every item to `leave_unresolved`, but
  no reconciliation decision made. The package is deliberately scoped to
  read-only triage: an earlier draft apply/backup/rollback mutation engine
  was removed in full before merge (never invoked against real data; a
  second review pass found further edge cases in it that had no bearing on
  the accepted scan evidence). `validate_decision`/`validate_batch` remain as
  a read-only sanity-check of a draft decisions file, but nothing in this
  module writes a source. Details:
  `docs/Subsystems/PromptPacks/PR-PACK-120_Missing_Asset_Reference_Triage.md`.
  No PromptPack/preset/asset was modified; no automatic reconciliation
  occurred at merge time. The owner subsequently reviewed all 24 triage
  items and authorized `PR-PACK-130` (below) to execute the 15 unambiguous
  ones.

- `PR-PACK-130 — Approved Missing-Reference Reconciliation` is
  **COMPLETE / CLOSED**: a one-time, owner-authorized real-data
  reconciliation, not a permanent product subsystem. A temporary,
  purpose-built utility (not a rebuild of PR-PACK-120's removed generic
  apply engine) executed the owner-approved subset of PR-PACK-120's 24
  triage items against real PromptPack data -- removed 67 structured LoRA
  entries (13 `BetterThanWords-merged-SDXL-LoRA-v3` + 54
  `babesByStableYogiPony_xlV4`, both determined by the owner to be
  checkpoint/model identities mistakenly recorded as separately-applied
  LoRAs) and cleared 4 literal `"None"` refiner-checkpoint placeholders to
  `""` (each verified refiner-disabled first), across 15 PromptPack
  sources, with every write backed up byte-exact, guarded by a
  semantic-diff proof, and atomically applied. All 9 `DreamyStyle_xl`
  items (63 occurrences) were deliberately left untouched -- its
  identity/original role is unknown and no automatic action was
  authorized for it. A fresh post-write census/triage confirmed
  `missing_file_backed_asset` **24 -> 9**, census total **1,010 -> 995**,
  and the remaining missing-reference identity set is exactly
  `{DreamyStyle_xl}`. No checkpoint/model/VAE selection, standalone preset,
  legacy text pack, or asset was touched. Once the reconciliation was
  verified, the temporary mutation utility and its tests were deliberately
  removed from the repository -- no code path capable of writing a
  PromptPack/preset source remains from this package; current
  missing-reference state continues to be tracked read-only by
  PR-PACK-120's `tools/missing_asset_reference_triage.py`. Details:
  `docs/Subsystems/PromptPacks/PR-PACK-130_Approved_Missing_Reference_Reconciliation.md`.
  No further missing-reference action is authorized unless the owner later
  identifies the historical `DreamyStyle_xl` asset or decides to remove it.

Deliberate real-model inference and platform/hardware changes remain
serialized and separately owner-authorized regardless of which package is
active. FLUX/model qualification and any DIAG-GPU work beyond event-driven
observation remain queued until deliberately selected as the one active
package.

PR-MVP-090 is **COMPLETE / ACCEPTED / INTEGRATED**. The final real-backend
release proof completed without production source changes.

The accepted final image job was `mvp090-final-image-lifetime`: one durable
`COMPLETED` queue/history entry, one decoded 768x1024 PNG, checkpoint
`juggernautXL_ragnarokBy.safetensors [dd08fa32f9]`, and image SHA-256
`57a1b6f14ab483a3d981df3e35304ef9d26bbe0478b8abb7c3a12f4513eec76f`.
The repaired acceptance harness proved durable terminal state and queue-runner
idle before teardown; no duplicate or replay occurred.

The final native plain-SVD-XT job was `4df7d2a73ea04e42a09294a81dfe8897`.
It was submitted through the public SVD controller and queue-first NJR path,
reached durable `COMPLETED`, and produced one non-empty MP4. The source-aware
target was 576x1024 from the 768x1024 portrait source; preprocessing resized
and center-cropped without padding. FFprobe verified exactly 14 frames at 7
fps and 576x1024. The accepted profile was plain XT, 25 steps, motion bucket
48, noise 0.01, decode chunk 2, fp16, CPU offload ON, forward chunking ON,
local-only ON, and all optional postprocessing OFF.

The disposable Windows bootstrap/check-only evidence used Python 3.11.9,
CUDA-enabled Torch 2.14.0+cu130 (CUDA 13.0), Diffusers 0.40.0,
Transformers 5.17.0, Accelerate 1.15.0, imageio-ffmpeg 0.6.0, and an RTX
4070 Ti. The production plain-XT cache was complete and no model download
occurred. Embedded provenance read-back passed, including source image
SHA-256, source job identity, current NJR SHA-256, SVD configuration, actual
preprocess/postprocess facts, and media-content verification. The visual smoke
check showed portrait orientation with no obvious stretch, squash, or gross
corruption.

Required CI run 331 remains the source-SHA compatibility evidence; no source
validation was rerun for this docs-only closeout. The earlier 832x1216 pressure
rejection remains expected guardrail behavior, and the interpreter-shutdown
incident is closed as an acceptance-harness lifetime defect.

## Known non-blocking debt

- Informational Linux/Xvfb isolation failures remain outside the required CI verdict.
- Legacy stale tests still reflect superseded CLI, compatibility, migration, or
  stale constructor-fixture expectations.
- Two post-destroy Tcl callback-noise messages appear after an otherwise clean
  graceful shutdown; no Tk/thread error or leak was observed.
- Local PR-gate execution can be unavailable when local `mypy` is missing;
  required GitHub mypy and smoke gates are the compatibility verdict.

Current exact collection and smoke counts are taken from the latest required CI
recorded here or in the applicable acceptance report. Run focused checks, then
`python tools/ci/run_pr_gate.py` when source changes require it. Do not repeat
GPU, WebUI, or SVD acceptance for docs-only changes.

Use Git history and the roadmap for historical detail. Update this file only
when repository direction, active work, or verified state materially changes.
