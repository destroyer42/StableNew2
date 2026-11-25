# PR-VID-MOTION-410: motion fidelity, transfer evaluation and evidence

Status: implemented on a feature branch (Phase 2 of `docs/Subsystems/Video/CONTROLLED_MOTION_ROADMAP.md`). This is a per-PR record: the code and the living docs (`VIDEO_PIPELINE.md`, `docs/runbooks/video_eval_kit.md`, `docs/runbooks/eval_plans.md`) win where they differ. **No physical generation was run.** Implementation is not demonstration of motion quality, and nothing here is a qualification verdict.

## 1. Outcome and class

Operators can author, admit, review and rate evaluations that ask: *did the intended source subject perform the intended movement, acceptably, with enough fidelity to the driving reference to make the asset useful again?* It extends the existing video eval kit (suite, run manifest, report, `ratings.csv`, Evaluate workspace); it adds no catalog, rating database, queue, runner, job model or qualification ledger.

- Execution class: Standard. Model recommendation: Claude Code Sonnet 5.5 XHigh; Codex GPT-6.1 Sol XHigh. Expected usage: about 15-30M cache-read, 70-120k output.
- Controller Surface Assessment: `src/controller/video_eval_controller.py` (not a ratcheted controller; 157 to 197 lines, under the 600-line new-controller limit) gained one motion branch and a per-preview preparation cache; every other responsibility sits in `src/video/`. Ratcheted ceilings are unchanged and unmoved (`app_controller` 4775, `job_history_service` 619, `job_service` 1218, `pipeline_controller` 1599); the Tk import boundary and the other ratchets hold.
- Architecture authority or invariant changed: No. `Intent -> Compiler -> NJR -> JobService -> Queue/Repository -> PipelineRunner.run_njr` is untouched; admission is still one all-or-none `JobService.submit_njrs`.

## 2. Contract

### 2.1 Suite versions (Workstream A)

`stablenew.video-eval-suite.v2` is a strict superset of v1. A v2 case may carry a `motion` object; a v1 file keeps loading exactly as before and **may not** carry one (the loader refuses it instead of silently ignoring the driver), and a v1-only reader refuses a v2 file. The editor never rewrites a plan: Save as New Version publishes a new file, as v2 only when some case has `motion`. Old plans round-trip byte-for-byte untouched. The run manifest stays `stablenew.video-eval-run.v1` with additive keys (`suite.schema`, `cases[].motion`, `jobs[].motion`) that existing readers ignore; the report adds `motion_evaluation` and per-cell `motion_diagnostic` to `metrics.json` the same way.

A case's `motion` object (`src/video/video_eval_motion.py`):

| Field | Meaning |
|---|---|
| `driving.path`, `driving.sha256` | The bound driving file; hashed at load, a pinned digest that changed is refused. |
| `driving.library_asset` | Optional `{asset_id, sha256, derived_from?}`. Accepted only when its SHA-256 equals the bound file's. Without it the clip is a **local video with unverified provenance**; it is never described as a library asset or a generated clip. |
| `action`, `motion_prompt`, `expected_outcome` | Intended action, the prompt for the workflow's motion control (`pose_prompt`) and the explicit, observable expected outcome (all required). |
| `category` | `head_turn`, `hand_wave`, `raise_arms`, `sit_down`, `turn_around`, `walk_forward` or `other`. |
| `direction`, `phases`, `window`, `annotations` | Expected direction and phases, the frame window of the bound file, and framing, viewpoint, compatibility and source-compatibility annotations. |
| `preparation` | `as_is` (the clip is used exactly as bound) or `workflow_prepared` with `fps_conversion`: Prepare Motion Source runs at preview for each distinct workflow, version and length. |

The driver is a property of the **case**: one motion asset is reused across many source images, and arms are never duplicated per driver. An arm may not set `pose_video_path`, `motion_library_asset`, `prepared_motion_source` or `operator_controls.pose_prompt`. A motion case is a single clip (no ordered segments) and runs only under Video Workflow arms.

### 2.2 Authoring (Workstream B)

The Create / Edit Suite dialog gains a **Driving motion** section per case: bind a local video or a verified Motion Library clip (the editor verifies the bytes and merges the library's framing, viewpoint, direction and label as suggestions that never overwrite the operator's text), set category, action, motion prompt, expected outcome, window, preparation and annotations, open or reveal the driver with the existing authorized helpers, and **Duplicate Case for Another Source** (driver and expectations kept, a fresh source binding required, no arm added). Arms keep editing the workflow, exact version, declared controls, opt-in and baseline. Validation refuses, with the reason, a motion case paired with a workflow that takes no driving video (and native SVD); the reference is never dropped to make an arm queueable. A prompt-only comparator is **not implemented**; if one is added later it must be an explicit, differently labelled conditioning mode. `MAX_EVAL_JOBS` stays 64.

### 2.3 Frozen inputs and admission (Workstream C)

Every job is built by `VideoWorkflowNjrBuilder`; the run service then reads the compiled NJR and **refuses the whole run** if a job lacks the driver, froze a different driver or motion prompt, lost or invented a library binding, differs from the requested preparation, or froze no length or rate. It freezes and re-hashes at admission: the source image, the prepared source image, the original driving video and any prepared derivative. A file changed between preview and admission is refused; nothing is queued and no manifest is left. Arms that need different preparation contracts (workflow, version or length) get different content-addressed derivatives; this is disclosed in the preview summary, never described as identical input. Per-job experimental consent is unchanged.

### 2.4 Comparison integrity (Workstream D)

`src/video/video_eval_integrity.py` classifies from the **frozen NJR settings**, not labels. Cells and pairs are `verified_comparable`, `verified_with_disclosed_differences`, `incomparable`, `missing_evidence`, `changed_input`, `changed_output` or `failed_or_incomplete`. Kinds:

- `one_variable`: exactly one declared control differs (baseline versus each candidate in the campaign).
- `multi_arm`: several controls differ (candidate against candidate in the campaign differs in two controls and is **not** called one-variable), or the workflow, version, length, rate or prepared derivative differs (disclosed as inseparable implementation differences).
- `cross_subject`: one motion (driver, window, prompt, category) across several source images under one arm, with settings fixed; one subject is repeated generation, not transfer.

A different driver, seed or motion prompt makes a pair `incomparable`.

### 2.5 Ratings and evidence applicability (Workstreams F and H)

`ratings.csv` stays the single rating artifact and its only writer (`video_eval_ratings_store.py`). A run with motion cases adds columns (non-motion runs keep their exact layout; a pre-410 file converts once with the existing recovery copy): `driving_context_sha256`, `rubric_version` (`stablenew.video-eval-motion-rubric.v1`), `subject_attachment`, `motion_fidelity_1_to_5`, `action_direction`, `action_timing`, `action_completion`, `root_displacement`, `start_end_pose`, `driver_contamination`, `motion_comments`. `requested_action` gains `incorrect_or_contradictory`; the failure taxonomy gains the controlled-motion categories (identity drift, anatomy, continuity and freeze reuse the existing keys). Blank or `not_assessed` is never zero; `not_applicable` removes a field that does not fit (a head turn has no locomotion).

Requested action, subject attachment and motion fidelity are three separate judgments, apart from visual quality and identity. A motion judgment counts only while **both** bindings hold: `artifact_sha256` equals the clip and `driving_context_sha256` equals the current context (source image, original driver, prepared derivative, workflow and length, preparation, motion prompt). A changed clip is `STALE_ARTIFACT` (as before); a changed driver, derivative or source makes the motion rating **inapplicable** (kept and identifiable, never re-assigned, shown as such); a motion judgment typed without a context is **legacy unverified**; the operator adopts the current context on purpose by typing `rebind` in `driving_context_sha256`. Legacy and unverified ratings are distinct from a confirmed failure.

### 2.6 Diagnostics, transfer and report (Workstreams G, I, K)

`video_eval_motion_metrics.py` computes a **global image-motion diagnostic** per motion cell against the *effective* driving clip: a motion-energy trace (mean luma change between consecutive preview frames), activity window and onset/offset, repeated and frozen frames, held tails, and on a common seconds basis trace similarity, timing displacement, onset/offset displacement and relative magnitude. It is labelled as such in every result; it is not pose fidelity and never evidence that the intended subject moved (a camera move gives the same trace; the tests show it). It handles static, flat, short, truncated, different-rate and unavailable inputs as `insufficient_evidence` or `unavailable` with the reason, never zero. There is no composite score and no threshold; the historical 0.30 motion-curve guardrail is not reused.

`video_eval_transfer.py` summarizes this run at the levels motion asset, category, workflow id and version, source compatibility category, conditioning configuration, arm and cross-subject group: planned, completed, failed or incomplete, verified comparable, rated, action, subject-attachment and fidelity distributions, critical breaks, distinct source subjects (by source bytes) and seeds, each percentage with its numerator, denominator and basis. A missing review is not rated and never counts as a failed action; a runtime failure stays in the attempt counts; a replay or duplicate (same inputs and settings, or the same artifact bytes) counts once and is listed as excluded. Readiness reuses `INSUFFICIENT EVIDENCE`, `IDENTITY CONCERNS`, `READY FOR OWNER REVIEW` (at least two distinct rated subjects are needed); it never ranks assets, updates Motion Library flags or promotes a workflow.

The report adds, per motion run: the case's driving reference and expectation, the effective driving input, the motion rubric, diagnostics with limitations, integrity per cell and pair, baseline-relative motion differences, cross-subject groups and the transfer tables. Driving video and text follow the content-visibility flag; the driver is never auto-played.

### 2.7 Motion Review window (Workstream E)

**Review Motion…** (Evaluate, built motion runs) opens `VideoEvalMotionReviewWindow` over the toolkit-neutral `MotionReviewSession`: source image, effective driving reference and two results on the existing `ComparisonClock` (real-time steps of `1 / max(fps)`, lower-rate clips repeat frames, shorter clips are held), bounded review previews only, first/middle/last at the same *times* in every clip, playback and frame position disclosed, differences in rate or length stated, prepared-versus-original identity shown, original and reveal through `src/utils/os_shell.py`, nothing plays until Play, stale decodes are dropped by token and cancelled, closing cancels everything, and SFW mode withholds the source and driver frames. Where no effective driver is recorded, only the original binding is shown and it is labelled as not verified.

## 3. Initial campaign (Workstream J): authored, not executed

Templates in `docs/runbooks/examples/` (relative placeholder paths, no media, no machine paths, each marked "Unexecuted template"). Workflow `wan_animate2_drive_i2v_v1` **1.2.0** (confirmed against the catalog: the newest offerable version of that id, experimental, `pose_video` declared; defaults, graph and readiness floor unchanged). Arms (1.0/1.0 baseline, pose 1.2, reference 1.3; pose interval at its default; no smoothing); seed 410; each suite keeps one legal length (the suite structure cannot vary length per case, so cases are grouped):

| File | Cases | Frames | Jobs |
|---|---|---|---|
| `video_eval_controlled_motion_short.suite.json` | head turn, right-hand wave, raise both arms (2 subjects each) | 49 | 18 |
| `video_eval_controlled_motion_long.suite.json` | sit down, turn around, walk forward (2 subjects each) | 81 | 18 |
| `video_eval_controlled_motion_stage_a.suite.json` | head turn, one subject | 49 | 3 |
| `video_eval_controlled_motion_stage_b.suite.json` | head turn and wave, two subjects (contains Stage A's cells) | 49 | 12 |
| `video_eval_controlled_motion_stage_c_short.suite.json` | raise both arms | 49 | 6 |

Full design 36 jobs = short + long. Stage A (3) is the functional pilot. Stage B (12, of which 3 repeat Stage A) is the diagnostic transfer sample: run only the 9 cells not already accepted when the exact inputs, workflow and configuration match. Stage C is the remainder (24): `stage_c_short` plus the long suite. Each stage is its own run with its own report; staged runs are not merged (no second campaign registry). Reusing an accepted cell means pointing the owner decision at that run's report; if exact identity is not provable, rerun it.

**Runtime planning (no fresh benchmark).** Animate-2 requires managed Comfy launched with `--disable-pinned-memory`, readiness floors of 10,000 MiB available VRAM and 16 GB available RAM, a 1,200 s history timeout, and the owned runtime is released after every job, so every job is a cold start. The only recorded timing is about 164 s for 41 frames including a cold load (PR-VID-184R); lengths 49 and 81 are unmeasured and **this is not a benchmark**. Planning figures to state in the authorization request, measured freshly on the target machine: per-job time at 49 and 81 frames, VRAM and RAM headroom, and the whole-stage budget (3, then 9, then 24 jobs). The device-loss quarantine and its recovery hold stay in force.

**Stop conditions for any later run:** a GPU device loss or quarantine, a resource-guard refusal, two consecutive failed jobs, any changed-input or incomparable finding in the report, content that must not be shown, or the stage budget exhausted. **Authorization boundary:** each physical run needs the owner's fresh, exact authorization of its suite file and SHA-256, input identities, workflow and version, job count and budget (`STATUS.md` Holds; `docs/runbooks/qual_system_840.md` section 2). This package authorizes none.

**Operator steps:** copy a template into `<Output>/eval_plans/video/` or open it in the editor; bind each case's two source images and the class driver (a local clip or a Motion Library asset, using a harvested window where available); keep one frame count per suite; Validate; Save and Preview (shows the compiled jobs, the per-case driving contracts and any refusals); then, only after authorization, Queue.

### 3.1 Post-pilot revision of Stage C (2026-11-24): authored, not executed

**What the pilot showed (owner inspection, recorded as notes in the run folders, not as ratings).** Stage A (3 jobs) and Stage B (12 jobs) all completed on `wan_animate2_drive_i2v_v1` 1.2.0 at 49 frames with no stop condition. The three arms (pose 1.0 / 1.2, reference 1.0 / 1.3) were indistinguishable by eye; all results had the intended motion, no visible artifact and no driver bleed-through, and the source subject held. Two oddities: a driver that starts facing away in the opposite direction makes the result open with the subject unnaturally looking far over a shoulder before turning to a normal range, and one of the 12 clips (hand wave, subject B, reference 1.3) showed an extra, still arm at the subject's side. The clips (2 s) were too short to judge timing. "No visible difference" is a statement about arms 1.2 / 1.3 on this pair, not about the controls: the spread was too small to tell.

**Revised templates** (`docs/runbooks/examples/`, one legal length per suite, seed 410, same workflow identity, no media): the original `stage_c_short` and `long` suites stay as the unexecuted full-design record and are **superseded for the next run** by:

| File | Cases | Arms | Frames | Jobs |
|---|---|---|---|---|
| `video_eval_controlled_motion_stage_c0_canary.suite.json` | head turn, subject A | baseline | 81 | 1 |
| `video_eval_controlled_motion_stage_c1_subject_a.suite.json` | head turn (start-pose matched), hand wave, subject A | 6 | 81 | 12 |
| `video_eval_controlled_motion_stage_c2_subject_b.suite.json` | the same two cases, subject B | 6 | 81 | 12 |
| `video_eval_controlled_motion_stage_c3_start_pose_contrast.suite.json` | head turn on each subject, start-pose matched and the pilot's unmatched profile-start driver | baseline | 81 | 4 |

Arms are one-variable against the baseline (pose 1.0, reference 1.0, pose window full): `pose_low` (pose 0.5), `pose_high` (pose 2.0), `reference_low` (reference 0.5), `reference_high` (reference 2.0) and `pose_early_stop` (pose end 0.6). Values are at least a factor of two from the baseline because 1.2 / 1.3 showed nothing. All are within the declared 0-10 control bounds; the extremes may degrade identity or motion, which is the information wanted. 81 frames (3.4 s at 24 fps) is the longest legal length.

**Start-pose contrast (C3).** The same source with the matched driver and with the pilot's profile-start driver, baseline arm only, so the driver's start pose is the only variable between a subject's two cases. It is the direct evidence for what a start-pose mismatch costs and whether the matched driver removes it, and so for how much PR-VID-MOTION-420 (alignment) is worth.

**Start pose.** Match the driver's first frame to the source's pose instead of hoping the model reconciles them. Both sources face the camera, so the head-turn driver must start facing the camera. The pilot driver turned from profile to the camera; a derived clip that starts facing the camera is the first 3.4 s of it, reversed: `ffmpeg -t 3.4 -i head_turn.mp4 -vf reverse -an -c:v libx264 -crf 14 -pix_fmt yuv420p head_turn_front_to_profile.mp4` (the `-t 3.4` must come **before** `-i`: after it, ffmpeg reverses the whole clip and keeps the first 3.4 s of the reversal, which is the final hold, not the turn; check the first and last frames). That is a new local video with its own SHA-256 and unverified provenance (record its lineage in the case annotations); it is not the Pexels file. If a driver instead starts facing the other way, flip the source image (or the driver, `-vf hflip`) and bind the flipped file; say so in the case annotations. The `start_pose` annotation states what each driver starts as.

**Runtime planning (no fresh benchmark at 81 frames).** At 49 frames the pilot took 229-311 s per job (about 49 min for 12) with whole-GPU VRAM peaking at about 11.8 GB of 12.28 GB, host RAM minimum 15.3 GB and the GPU near 83 C. 81 frames is unmeasured and will take longer and may exceed the VRAM available (a clean resource refusal or an out-of-memory failure), so **Stage C0 runs one job first**; only a completed canary with its measured time and peak headroom supports authorizing C1 (12 jobs; it repeats the canary's cell, which also checks repeatability) and then C2. Stop conditions and the authorization boundary are unchanged (section 3): device loss, resource refusal, two consecutive failures, any changed or incomparable finding, content that must not be shown, or the budget. StableNew and its Forge must be closed while a harness runs (the runtime guard refuses while a Forge it did not start is live).

**Keep the inputs inside Output.** Bind images and driving videos from a folder under the Output root (for example `eval_plans/video/<suite>/images` and `/motion`). Frozen job inputs record their paths, and a viewer limited to Output (the Site) can show only files there; an input outside Output cannot be relinked afterwards without rewriting frozen records, which the report would flag as a source-image mismatch.

**Results as future drivers.** A finished clip can be added to the Motion Library from Recent outputs (it keeps the originating job and artifact), and Prepare Motion Source treats it like any other driver. A generated clip carries its source subject's appearance and any artifact it had, so it is a reference to be reviewed, not a clean motion capture; a driver from a reviewed result inherits the 81-frame length and a known start pose, which is useful when the run was good and misleading when it was not.

## 4. Future extensions (documented, not implemented)

Raw rendered character versus silhouette conditioning; source/driver alignment (Phase 3); alternative conditioning graphs and Fun Control qualification and comparison (Phase 4); multiple-seed robustness; longer controlled-motion sequences; an explicit prompt-only comparator; recipes and automatic recommendations (Phases 5 and 6).

## 5. Limits

Identity, attachment and fidelity are what the operator saw; the diagnostic is global image motion on a bounded preview (first 120 frames, 256 px). Evidence is per run: replays across runs are not deduplicated and staged runs are not aggregated. A library asset's "good for motion" flag is an operator statement; the transfer summaries record observed outcomes beside it and never change it. Motion evidence stays in the eval kit's `ratings.csv` and does not feed Learning or image recommendations. Admission verifies the bound files and the compiled NJR; it cannot prove what the model consumed beyond the frozen, content-addressed inputs.

## 6. Acceptance and tests

| ID | Covered by |
|---|---|
| AC-01, AC-02 | `PR-VID-MOTION-400` merged as `48e19879` (PR #399); `test_pr_vid_motion_410_cases.py`, `..._authoring.py` (library binding of a harvested asset) |
| AC-03, AC-04 | `..._cases.py` (shared driver, different drivers, one driver across subjects, no extra arms) |
| AC-05 | existing eval, authoring, catalog, sequence and identity suites unchanged and green; `..._authoring.py` (v1 round trip) |
| AC-06, AC-08 | `..._authoring.py`, `..._cases.py` (refusals, changed or missing files, incompatible workflow) |
| AC-07, AC-09 | `..._cases.py` (production NJRs, all-or-none admission, frozen identities, preparation reuse) |
| AC-10 | `..._evidence.py` (one-variable, multi-arm, cross-subject, incomparable) |
| AC-11 | `..._review.py`, `tests/gui_v2/test_video_eval_motion_410.py` |
| AC-12 to AC-15 | `..._evidence.py` (every state, rebuild and restart, stale output, changed driver, legacy) |
| AC-16, AC-17 | `..._metrics.py`; `..._evidence.py` (report separates human and diagnostic evidence) |
| AC-18, AC-19 | `..._evidence.py` (denominators, distinct subjects, duplicates) |
| AC-20, AC-21 | `..._campaign.py`; no physical run, no claim |
| AC-22 | focused tests, `python tools/ci/run_pr_gate.py`, aggregate review (closeout report) |
