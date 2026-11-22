# VID-CAND-382 — HunyuanVideo 1.5 (480p I2V, step-distilled FP8) vs Wan2.2 I2V-A14B: candidate workflow and evaluation suite

Hand-off prompt for a fresh Claude Code or Codex session. The research below is complete; do not repeat broad discovery.

## Objective

- **Outcome:** an experimental, catalog-registered HunyuanVideo 1.5 I2V workflow that StableNew can run through the normal
  Video Workflow path, plus a frozen, reproducible evaluation suite (built on the existing video eval kit) that compares it with
  the current Make Video default **Wan2.2 I2V-A14B 4-step 1.0.0** on quality, identity, motion and speed, ready for the owner to
  authorize and rate.
- **In scope:**
  1. `WorkflowSpec` for the candidate (experimental, never the default) + Comfy workflow template + tests with a fake Comfy.
  2. Eval suite JSON files (stage 0 smoke, stage 1 head-to-head, stage 2 full-body) and a frozen plan with written
     GO/NO-GO thresholds, following the CLIP-371 design.
  3. A small read-only verification/analysis script for the run (seed, SHA, workflow and runtime identity, wall time from the
     job repository) modelled on `C:\Users\rob\qual\clip371\verify_s2.py`.
  4. A record `docs/Subsystems/Video/PR-VID-CAND-382_HunyuanVideo15_Candidate_Eval.md`.
- **Explicit exclusions:** no promotion (governance stays `experimental`); no change to the A14B spec or the picker default;
  no custom ComfyUI nodes (stock nodes only, managed ComfyUI 0.38.0); no physical generation, model download or licence
  acceptance without the owner (see "Owner gates").

## Execution class and model recommendation

- Execution class: **Standard** (known architecture: one catalog spec module + eval-kit content + a tool script).
- Model recommendation: Claude Code **Sonnet 5.5 High**; Codex **GPT-6.1 Sol High**.
- Expected usage: about 10–15M cache-read, 80k output (offline part). Physical runs are owner-attended sittings.

## Exact start state

- `origin/main` at hand-off `d8ea1c86`; isolated worktree (the owner's live app runs from `C:\Users\rob\projects\StableNew-main`).
  Use main's `.venv` interpreter inside the worktree (memory). Branch `video/vid-cand-382-hunyuan15`.
- Record task-start timestamp and session ID first.

## Research already done

### Candidate and hardware
- Source: `C:\Users\rob\qual\bench373\wan-video-research.html`, section "4 · Other engines" (21 Nov 2026) — verdict **"Test first"**, the
  only listed engine that fits this host. Stock ComfyUI nodes, **Comfy-Org repack**; model ~8.3 GB + text encoder ~9.4 GB; fits
  12 GB VRAM / 32 GB RAM; **121 frames at 24 fps in 8–12 steps**. Licence **excludes the EU, UK and South Korea** (owner must
  accept the licence for this host; precedent: Ideogram licence acceptance recorded in STATUS open decision 7). Nothing run locally.
- History: an earlier non-distilled HunyuanVideo was NO-GO on a 14 GB VRAM gate —
  `docs/Subsystems/Video/PR-VID-160A_Consumer_GPU_Motion_Candidate_Feasibility.md` lines 163-169; deferred in
  `docs/Subsystems/Video/PR-VID-110_Directed_Motion_Qualification.md` line 163; revisit trigger in
  `docs/audits/2026-10-20_video_experience_roadmap.md` line 150 / decision D5 line 280. Cite these and say why the distilled
  FP8 build changes the verdict.
- Others in the same table, not in scope: LTX-2.5 distilled (needs ~37 GB RAM, wait for 64 GB), MiniMax-H3 (licence excludes US),
  Kandinsky 6 (MIT, not yet in stock ComfyUI — core PR #16825; good next candidate), Bernini-R (reference-to-video only),
  Wan 2.5/2.6/3.0 (API only), SkyReels/FramePack/Self-Forcing/LongCat/Ovi (skip).
- Host: RTX 4070 Ti 12 GB (12,282 MiB), 32 GB RAM, managed ComfyUI 0.38.0 rev `6b747c04`, custom nodes disabled
  (`C:\Users\rob\qual\bench373\BENCH_PLAN.md`, `HANDOFF_REPORT.md`). The GPU device-loss issue is resolved (DIAG-GPU-160
  package); per-run stop conditions still apply.

### Baseline to beat (VID-CLIP-371, `docs/Subsystems/Video/PR-VID-CLIP-371_Three_Engine_Eval.md`)
- Plan `C:\Users\rob\qual\clip371\clip371_plan.v6.json`; suites `clip371_stage1_three_engines.suite.json`,
  `clip371_stage2_two_arms.suite.json`; private cases `cases.private.json`, `fullbody_picked.private.json`; verifiers
  `verify_s1.py`, `verify_s2.py` (read `state/jobs.sqlite3?mode=ro` for wall time and `metrics.json` for readiness).
- 8 motion classes: head turn + smile, walk toward camera, wave, sway, laugh + hair toss, turn in place, single step, gaze shift.
  Seeds 371 (stage 1) and 372 (stage 2). 81 frames.
- A14B results: action achieved 8/8 in both stages, zero identity breaks, all means 5/5 (**ratings saturated** — a ceiling
  effect the new design must address), wall time 140-176 s per clip. Outputs:
  `output/video_eval/20261116_134153_clip371-stage1_c947ec0a/`, `output/video_eval/20261118_040044_clip371-stage2_b060db61/`.
- Speed reference (WAN-BENCH-373, `C:\Users\rob\qual\bench373\HANDOFF_REPORT.md`, `run-002/summary.json`): A14B 81 frames
  480x832 ComfyUI execution mean 120.2 s (warm 116.6), CK attention 90.3 s (experimental arm 1.1.0, unrated). Live app warm
  "Prompt executed" ~99-106 s, job wall median 131.3 s incl. RIFE, cold 153-193 s (`docs/Subsystems/Video/VIDEO_PIPELINE.md` ~line 172).
  Warm hold is per workflow id+version, so cross-arm timing is confounded by cold starts — time both warm and cold.

### Eval kit (reuse unchanged)
- Runbook `docs/runbooks/video_eval_kit.md`. Suite schema `stablenew.video-eval-suite.v1`, loader `src/video/video_eval_suite.py`:
  `suite_id`, one `seed`, `baseline_arm`, `cases[]` (`case_id`, `image`, `image_sha256`, `prompt`, `tags`), `arms[]`
  (`backend: video_workflow`, `form.workflow_id/workflow_version/frame_count`). Experimental arm needs `"experimental_opt_in": true`
  (that is the per-job opt-in; `src/video/video_workflow_intent.py:66`). Max 64 jobs per run (`MAX_EVAL_JOBS`).
  Examples: `docs/runbooks/examples/video_eval_three_engines.suite.json`, `video_eval_a14b_speed_arms.suite.json`.
- Queue: "Queue eval suite..." in `src/gui/views/video_eval_panel_v2.py` (~line 55) → `src/video/video_eval_run.py` (one atomic
  `JobService.submit_njrs`) → `<output>/video_eval/<run_id>/run.json`. Report: `src/video/video_eval_report.py`, metrics
  `video_eval_metrics.py` (motion, jitter_ratio, brightness_flicker, color_drift, sharpness_retention), `video_eval_assessment.py`,
  `video_eval_identity.py`. Ratings `ratings.csv` (`src/video/video_eval_rubric.py`, `video_eval_ratings_store.py`): required
  `source_fidelity_1_to_5`, `subject_stability_1_to_5`, `critical_identity_break`; plus action, continuity, anatomy, scene,
  failure categories, `first_failure_seconds`, notes, bound to `artifact_sha256`.
- Note: package EVAL-HOME-383 (canonical eval-plan folder + dropdown) may land in parallel; write suite files where it says
  (`<output>/eval_plans/video/` per that package) if it has merged, otherwise under `docs/runbooks/examples/` plus a copy in the
  private qual folder for private cases. Do not block on it.

### Adding the workflow (recipe: `docs/Subsystems/Video/VIDEO_PIPELINE.md` section 13, ~line 438)
- New module `src/video/workflow_catalog_hunyuan15.py` modelled on `src/video/workflow_catalog_wan_a14b.py`; register in
  `build_builtin_workflow_specs` (`src/video/workflow_catalog.py` lines 21-32). Update `docs/CODEX_MAP.md` Comfy row sibling list.
- Pin model files like `WAN_A14B_MODEL_FILES`: filename, loader input, SHA-256, `repo@revision` (Comfy-Org repack on Hugging Face —
  look it up with the HF tools, record the exact revision; do not download). List stock-node dependencies (the HunyuanVideo 1.5
  loader/encoder/sampler nodes shipped in ComfyUI 0.38.0 — verify the node class names exist in the managed ComfyUI tree's
  `comfy_extras`/`nodes` before templating; `ComfyDependencyProbe` `src/video/comfy_dependency_probe.py` checks them at run time).
- `governance_state=WORKFLOW_GOVERNANCE_EXPERIMENTAL`, `make_video_default: False`. `backend_defaults`: `frame_count_policy`
  (121 default at 24 fps; allowed 4n+1), `output_policy` (frames out + fps 24 — StableNew encodes, like TI2V 1.3.0),
  `runtime_policy` (`required_launch_flags` — measure; start with the A14B set incl. `--disable-pinned-memory` only if needed),
  `resource_readiness` (VRAM floor — set from the stage-0 measurement, start conservative ~9,500 MiB; RAM advisory),
  `history_timeout_seconds` (1200 like A14B), `provenance` (`comfyui_version`, `license` text + region exclusion), `prompt_template`.
- No workflow-name branches in builder/compiler/backend. Runtime check order: `_verify_required_launch_flags` → `ComfyDependencyProbe`
  → `WorkflowResourceReadiness` (`src/video/workflow_readiness.py`) (VIDEO_PIPELINE section 4.4 ~line 151).
- Tests: registry + compiler + version pin (`tests/video/test_pr_comfy_runtime_100_workflow_versions.py`) + `_FakeComfy` backend run;
  model the new test file on `tests/video/test_vid_a14b_374_speed_arms.py`.

## Evaluation design (the deliverable the owner will authorize)

Fairness rules (write them into the plan):
- **Equal clip duration, native frame rates:** A14B 81 frames @16 fps (5.06 s) vs Hunyuan 121 frames @24 fps (5.04 s). Note in the
  report that RIFE smoothing is off for both arms (or on for both).
- Same source images (hash-pinned), same prompts, same seed per stage, matched resolution class (480p; A14B 480x832 portrait —
  set Hunyuan to its nearest native 480p portrait size and record it).
- Hunyuan steps: one arm at 8 steps and (stage 1 only) one at 12 steps if the budget allows — the research gives 8–12.
- Speed: record cold (first job after ComfyUI start) and warm separately; wall time from the job repository, ComfyUI execution time
  from logs, peak VRAM, host commit and available RAM from the qualification telemetry (`tools/qualification/owned_tree.py`).

Stages (total ≤ 64 jobs per run; ≤ ~60 generations overall):
| Stage | Jobs | Design | Purpose |
|---|---|---|---|
| 0 smoke | 2 | 1 case × Hunyuan 8-step, run twice (cold then warm) | Feasibility: loads, completes, VRAM/commit inside envelope, set the readiness floor |
| 1 head-to-head | 24 | 8 CLIP-371 cases × {A14B 1.0.0 baseline, Hunyuan 8-step, Hunyuan 12-step}, seed 371 | Quality/identity/motion vs baseline on the same 8 motion classes |
| 2 hard cases | 16–24 | 8 harder cases (full-body from `fullbody_picked.private.json` + 2–3 new: hands interacting, two-step action, fast turn) × {A14B, best Hunyuan arm}, seed 372 | Break the 5/5 ceiling |

Ceiling effect fix (A14B saturated at 5/5): in stage 2, add a **blind pairwise preference** per case (owner sees two unlabeled
clips, picks better or tie, per dimension: fidelity, stability, motion). Implement as a separate `pairwise.csv` written by a small
read-only report helper that shuffles arm order with a recorded seed — do **not** change `ratings.csv` schema. If adding the helper
to `src/video/` grows beyond ~150 lines, make it a `tools/` script instead and say so.

Written thresholds (freeze in the plan, mirror CLIP-371):
- Hunyuan **NO-GO** if: any allocation failure/OOM at the frozen envelope; host commit ≥ 0.95; action achieved < 6/8 in stage 1;
  > 1 critical identity break; mean fidelity or stability < 4; or a material regression vs A14B (≥ 2 points on fidelity/stability or
  a new break) on ≥ 2 cases.
- **"As good or better"** if: no NO-GO, stage-1 means within 0.25 of A14B on fidelity/stability/action, and stage-2 blind pairwise
  preference for Hunyuan ≥ 50% (ties split).
- **Faster** if warm wall-time median ≤ 0.8 × A14B warm median on the same host session.
- Recommendation possibilities: keep A14B / add Hunyuan as approved alternate / candidate for default — the last two are owner
  decisions (promotion recipe VIDEO_PIPELINE section 13 + section 1.1); this package only reports.

Stop rules (per run): device loss, allocation failure, commit ≥ 0.97 or available RAM < 0.25 GiB or commit headroom < 1 GiB
(WAN-BENCH-373 telemetry rules), any automatic retry. No settings downgrade after a resource failure within a frozen plan.

## Owner gates (stop and ask; never self-authorize)

1. Licence acceptance for HunyuanVideo 1.5 on this host and the model download (state file names, source repo@revision and sizes).
2. Each physical stage: frozen plan digest → owner `APPROVE <arm> <digest12>` / typed `RUN <digest12>` per
   `docs/runbooks/qual_system_840.md` section 2 (lines 36-61), or the eval-kit equivalent the owner names. Agents never issue the
   authorization. Example executor pattern: `tools/qualification/fun354/physical.py` (`--authorize-plan <digest> --authorized-by`).
3. The owner rates (ratings.csv + pairwise.csv). An agent never fills ratings.

## Acceptance criteria (offline, this package)

1. The Hunyuan spec is registered as experimental, never preselected, refused without per-job opt-in, pinned by SHA/revision, and
   passes registry/compiler/version-pin/fake-Comfy tests.
2. Suite files load with `src/video/video_eval_suite.py` (≤ 64 jobs each) and the frozen plan states fairness rules, thresholds,
   stop rules and budget.
3. The verification script reproduces the CLIP-371 checks read-only and emits arm summaries (wall time cold/warm, VRAM, commit).
4. The record doc exists; `VIDEO_PIPELINE.md` section 1.1/4.2 lists the candidate as experimental; `docs/CODEX_MAP.md` updated.
5. Physical results, ratings and any promotion are reported as *not done / pending owner* (AGENTS.md section 8 categories).

## Token-efficient validation plan

1. `python -m pytest tests/video -q -k "catalog or workflow_versions or hunyuan or eval_suite"` then the new test file.
2. `ruff check` + `python tools/ci/run_pr_gate.py` from an isolated worktree (memory: a running app in the checkout trips the
   collection gate); also `python -m pytest tests/tools -q` if a new `tools/` module is added (memory: PR gate misses tools census).
3. `git diff --check`.

## Stop conditions

- The required stock nodes are absent from ComfyUI 0.38.0 → stop; report the missing node classes (needs a runtime pin change,
  owner decision).
- The model needs > 12 GB VRAM or > 32 GB RAM at 480p/121 frames by the published figures → stop with a NO-GO note.
- Anything requiring custom nodes, a second ComfyUI, or a change to A14B/approved specs → out of scope.

## Completion report

Per `AGENTS.md` section 8, separating implementation (spec, suites, scripts), demonstration (fake-Comfy tests), qualification
(none), and held items (licence, download, physical stages, ratings). `Model / usage` line. Commit on the feature branch; publish
only with owner authorization.
