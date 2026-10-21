# StableNew current state

Updated: 2026-10-20

This file is **current state only**: baseline, supported capabilities, what is active and next, open owner
decisions, holds and known debt. It is capped at 150 lines and checked by `tools/ci/ci_truth.py`. It does not narrate
pull requests. PR narrative lives in the PR body and `git log`; per-feature detail lives in `docs/Subsystems/`.
The previous log-style file (about 1,700 lines of PR narrative) is preserved in Git: `git show aebfdd2a:STATUS.md`.

## Baseline

- Product v2.6 MVP, release proof complete (PR-MVP-090). Remote `destroyer42/StableNew2`, default branch `main`.
- Canonical path: `Intent -> Compiler -> NJR -> JobService -> Queue/Repository -> PipelineRunner.run_njr -> Handler ->
  Artifacts/History`. Fresh work is queued, the NJR is immutable, lifecycle belongs to the SQLite repository, replay creates
  a new NJR with lineage, and the GUI/controllers create no second runner. Authority: `AGENTS.md`, `docs/ARCHITECTURE_v2.6.md`.
- Interpreter: CPython 3.14 standard-GIL only. Windows runtime pins: `constraints/windows-py314-cu130.txt`; dev/CI tools:
  `requirements-dev.txt`. Managed Forge Neo (`config/managed_forge_runtime.json`) and managed Comfy
  (`config/managed_comfy_runtime.json`) are pinned separately and never share the application environment.
- Single-node, same-process execution. Production video backends: native SVD XT and the Comfy workflows the catalog marks
  `approved` (today Wan2.2 TI2V-5B 1.2.0); every other workflow is experimental and needs the job's own opt-in.

## What `main` enforces (all PRs)

- `main` is protected: a PR is required, force pushes and deletion are blocked, the owner may bypass. Required checks:
  `required`, `full-suite` (the sharded census) and `windows`. Docs-only changes take a cheap path.
- `required` runs: repository completeness, controller-surface ratchet, `ruff check .`, mypy smoke, **ratchets** (below),
  isolated collection and the required smoke. Run locally with `python tools/ci/run_pr_gate.py` (`--full` adds the sharded census) after
  `pip install -r requirements.txt -r requirements-dev.txt`.
- Ratchets only allow recorded debt to shrink (baselines under `tools/ci/`): whole-`src` strict mypy (1,681 errors in
  194 files), unformatted files (398), blind/silent excepts in `src` (BLE001 1,405, S110 565, S112 42), thread and layering
  rules (daemon threads 18, raw threads 12, utils importing upward 19, controller importing the GUI 17), and the four
  controller line ceilings.
- Workflows are SHA-pinned, the default token is read-only, and no workflow runs fork code with secrets.
  Flaky tests are repaired or quarantined with an owner and expiry (`tests/quarantine/README.md`).

## Supported capabilities (detail in the linked docs)

**Image generation**

- Start with the living documents (one per subsystem, edited in place; see `docs/Subsystems/README.md`): `docs/Subsystems/Image/IMAGE_PIPELINE.md`
  and `docs/Subsystems/Image/MODEL_PROFILES.md`. The per-PR records linked below are historical evidence and lose to the code and the living docs.
- Forge is the default backend; A1111 is the rollback/compatibility backend (`docs/Subsystems/Image/PR-IMG-FORGE-100_Forge_Compatibility_Qualification.md`).
  Backend-neutral execution: `docs/Subsystems/Image/PR-IMG-100_Backend-Neutral_Image_Execution.md`.
- Exact model profiles: FLUX.2 Klein 4B FP8 (`docs/Subsystems/Image/PR-IMG-116_FLUX2_Klein_Forge_Production_Slice.md`) and
  Z-Image-Turbo FP8 (`docs/Subsystems/Image/PR-IMG-MODELS-155_ZImage_Turbo_FP8_Forge_Enablement.md`; physical qualification
  inconclusive, see Holds). Klein Base 9B is refused (`NO_GO_RESOURCE_RISK`).
- SDXL PromptPack OpenPose ControlNet (`docs/Subsystems/Image/PR-IMG-CNET-210_SDXL_OpenPose_ControlNet.md`); ADetailer control
  truth (`docs/Subsystems/Image/PR-REFINE-160_ADetailer_Control_Truth_and_Effectiveness_Evidence.md`); supported-option upscale defaults (`docs/Subsystems/Image/PR-IMG-FORGE-230_Supported_Option_Defaults_Integrity.md`).
- PromptPacks (versioned JSON), Review and reprocess, Photo Optimize with scope-aware editing and historical baselines
  (`docs/Subsystems/Image/PR-IMG-PHOTO-222_Scope_Aware_Editing.md`), cross-workflow model compatibility preflight.
- Review mask editing for registry-resolved SDXL base / Forge: original-pixel painting, frozen input previews and canonical queue admission (`docs/Subsystems/GUI/PHOTO_REVIEW_REPROCESS.md`); outpainting and physical masked-output acceptance are deferred.
- Learning: designed experiments, ratings, Model Comparison, staged curation. Recommendations are applied from the Learning tab's
  Recommendations selector (default Apply with confirm); rated review drafts are saved on navigation or with Save All Drafts.
- History browser: the Pipeline tab's Job History opens a searchable, paged view of every job (status, date, pack, prompt/model text;
  no schema change). Text search covers only the first 64 prompt characters and the model; full-text search and "replay with changes" are not built.
- Batch operations: whole-selection Review preflight, multi-source Video Workflow batch, unified batch triage and retry
  (`docs/Subsystems/GUI/PR-BATCH-OPS-201_Unified_Batch_Operations.md`).

**Video**

- Native SVD XT queue-first path with source-aware targets, provenance and replay lineage. Comfy Video Workflow: Wan2.2 TI2V-5B
  1.2.0 is `approved` (production, no per-job opt-in; 1.0.0 and 1.1.0 stay experimental so stored jobs replay unchanged) and
  is the only conditionally qualified directed-motion candidate; Wan-Animate-2 stays experimental (Queue stays disabled until
  the job's opt-in is ticked). Motion source readiness: `docs/Subsystems/Video/PR-VID-196_Motion_Source_Readiness.md`; optional Prepare Motion Source
  (the exact driving-clip frames a verified workflow consumes, lossless and content-addressed): `docs/Subsystems/Video/PR-VID-MOTION-210_Prepare_Motion_Source.md`. One-variable experiments can be reopened from History or the tab, compared side by side and rated (action outcome kept apart from quality) as Learning evidence that never feeds image recommendations: `docs/Subsystems/Video/PR-VID-QUALITY-211_Experiment_Review.md`.

**Runtime safety** (all on the production construction path)

- Endpoint lifecycle and single-flight connection (`docs/Subsystems/Runtime/PR-RUNTIME-WEBUI-170_Managed_WebUI_Endpoint_and_Lifecycle_Consistency.md`), backend-scoped outage containment with a
  startup hold that releases only on a fresh readiness+identity proof (`docs/Subsystems/Runtime/PR-QUEUE-WEBUI-171_Backend_Scoped_Outage_Containment.md`,
  `docs/Subsystems/Runtime/PR-QUEUE-WEBUI-172_Dead_Forge_Endpoint_Cascade_Repair.md`),
  GPU device-loss dispatch quarantine (`docs/Subsystems/Runtime/PR-QUEUE-GPU-180_GPU_Loss_Dispatch_Containment.md`), shutdown
  admission fence, managed-Forge identity attestation, anonymous per-owner job objects, crash-safe state writes.
- External A1111/Comfy processes are never adopted, restarted or killed; ambiguous dispatched generation POSTs are never
  replayed. Cancel and Return requeues a job only on positive dispatch evidence; otherwise it is cancelled and flagged
  action-required (`docs/Subsystems/Runtime/QUEUE_AND_RUNTIME.md`).

## Active and next

Active: the improvement roadmap in `docs/audits/2026-10-16_repo_audit_and_roadmap.md` (read its "Critical assessment" and
the independent critique adjustments in the PR history before reordering it). Phases 0 and 1 are merged (protection and gates,
process isolation, startup wiring, crash-safe writes, pinned dev environment, Windows lane, ratchets). Phase 2 (docs and
process) is in progress: this file (P2-1) and the generated code map `docs/CODE_MAP.md` with the short task map
`docs/CODEX_MAP.md` (P2-3) and one source for the rules in `AGENTS.md` (P2-4) are done, and the eight living subsystem docs (P2-2) are written;
P2-6 wave 1 retired the leaf harnesses; the rest stay with named retirement conditions (`tools/qualification/README.md`). Phase 3 has started: P3-3 (contained, bounded child processes, `src/utils/managed_process.py`) P3-4 (typed Comfy transport and cancellation, `src/api/http_transport.py`; the port scan and dead launcher are gone) and P3-5 (provenance never lost silently; one NJR hash identity, `src/utils/njr_identity.py`) P3-6 (queue lock and idle discipline, without the CANCELLING status that needs an owner decision) and P3-1 (30 unreferenced modules deleted), and P4-1 (stage handlers: `run_njr` is orchestration only) are merged. Phases 4 and 5 are a candidate list; each package needs a contract check and an owner decision first.

Video: the owner-accepted video roadmap is `docs/audits/2026-10-20_video_experience_roadmap.md` (phases A-E, decisions D1-D8).

Assessment practice: the framework (v1.2) is in `docs/assessments/README.md`. Its dated 2026-10-15 findings predate Phases 0 and 1
of the roadmap; where they conflict with this file, this file and the repository are current.

## Open owner decisions

1. LICENSE file (copyright holder) and the single canonical version number (`pyproject.toml` 1.0.0, `.stableNew_version.txt`
   1.0.4, README v2.6).
2. Further retirement of the retained qualification harnesses, each at its stated condition in `tools/qualification/README.md`
   (the per-PR model ceremony is decided: a one-line recommendation and a one-line usage record, see `docs/AI_MODEL_SELECTION.md`).
3. Is `DIAG-GPU-130` open or closed? Records conflict; treat as open (see Holds).
4. Should the GUI "batch runs" control apply on the state-fallback job-building path? It has never applied there.
5. A physical restart check that queued WebUI jobs are held then released against a running Forge.
6. Decided: Character Training stays on hold pending a real trainer decision (see Holds). Retired: AnimateDiff execution (only an
   enabled stage is refused; disabled placeholders and history stay readable), the disabled LTX specs (future LTX support is not ruled
   out and needs bridge implementations plus accepted runtime evidence), the dormant story-plan/continuity authoring code, the AI
   settings-suggestion stub (external scripts importing `src.ai` would break, unverified) and the cluster scaffolding.
7. `PR-IMG-120` (Diffusers production slice) remains unauthorized pending a separate decision.
8. Product order after the safety work: inpainting/ControlNet, LoRA browser (the history browser and Learning payoff are in; "replay with changes" is not).
9. Learning model-comparison jobs store the whole experiment snapshot twice per job (about 750 MB across 10 experiments). Decided: store it
   once per experiment by hash, forward-only (an NJR contract change, its own PR). Open: backfilling existing rows, and whether to prune jobs
   whose images and manifests were deleted (archive then delete, or delete), both only after the owner reads the output of
   `python tools/job_repository_report.py` (read-only; see `docs/Subsystems/Learning/LEARNING.md` section 9).
10. Decided 2026-10-20 and implemented: Movie Clips assembly is a queued CPU `movie_assembly` job on the canonical path
   (`docs/Subsystems/Video/VIDEO_PIPELINE.md` section 7); approved Comfy workflows are production video backends and Wan2.2
   TI2V-5B 1.2.0 is promoted.
11. Material changes the roadmap holds for an owner decision (`docs/audits/2026-10-16_repo_audit_and_roadmap.md` section 8): a single
   composition root (P3-2, decision 11), a durable CANCELLING status (decision 12), and moving the executor into `image_backends` (decision 14).

## Holds and safety constraints

- The physical-GPU hold was lifted by the owner on 2026-10-18: the owner has been running jobs, and device loss looks
  intermittent (a loss can come early in a run, or the GPU can be stressed for hours without one). Records:
  `docs/Subsystems/Runtime/DIAG-GPU-100_Hard_Crash_Correlation_and_Survivor_Telemetry.md`,
  `docs/Subsystems/Runtime/DIAG-GPU-110_Windows_Dump_Attribution.md` and `docs/Subsystems/Runtime/DIAG-GPU-140_Forge_Job_Start_Device_Loss_Recurrence.md` (17 losses since 2026-09-07, 8 after XMP-off; the last three each 4-9 s into a Forge txt2img job; no root cause accepted). The device-loss
  quarantine stays the response to a loss. Tests, gates and CI still never touch a GPU or a real runtime; a package runs physical work only when its acceptance needs it.
- Character Training is on HOLD pending a real trainer decision (no trainer is bundled; cancellation reaches only the immediate process; weight discovery can fall back to an older file). LoRA consumption is independent and stays supported: `docs/Subsystems/Training/Character_Embedding_Workflow_v2.6.md` section 0.1.
- Forge-vs-Comfy still-image qualification is offline only (CONDITIONAL / INCONCLUSIVE); a Comfy image slice needs resource and
  fault clearance first (`docs/Subsystems/Image/PR-IMG-BACKEND-QUAL-100_Forge_vs_Comfy_Still_Image_Qualification.md`).
- Z-Image clean shutdown and repeated-run stability are unresolved; no repeat physical attempt is authorized.
- Never push to `main`, merge, publish or mutate secrets without explicit owner approval (`AGENTS.md`).

## Known debt

- The ratchet baselines above; the audit findings not yet scheduled (god objects `AppController` 7,307 lines and the executor,
  NJR construction at several sites, model-family branches in generic code, untyped stage configuration).
- 64 modules unreachable from any entry point (~8.7k lines) await a verified deletion pass; the retained qualification harnesses
  (inventory in `tools/qualification/README.md`) remain the bulk of `tools/`.
- Two Tcl callback-noise messages appear after an otherwise clean shutdown; no thread error or leak was observed.

## Keeping this file true

Update it only when direction, active work, a hold, an owner decision or a verified baseline changes, and edit the existing
line instead of adding one. Do not add per-PR bullets, unmerged/"local" status labels or test counts. `ci_truth.py` enforces the
line cap, bans stale markers and requires every referenced repository path to exist.
