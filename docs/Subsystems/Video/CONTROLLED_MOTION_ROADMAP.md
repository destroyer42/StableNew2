# Controlled Motion Generation roadmap

Status: **official development direction** for the controlled-motion part of StableNew's video capability. Phases 1
(PR-VID-MOTION-400), 2 (PR-VID-MOTION-410), 3 (PR-VID-MOTION-420) and 4 (PR-VID-MOTION-430, offline) are implemented; every later phase is a planning identifier only and needs
its own work package, contract check and, where it says so, an owner decision.

This document supplements `docs/audits/2026-10-20_video_experience_roadmap.md`. It does not replace broader video
priorities, the qualification authorities (`tools/qualification/system840/ledger.v1.json`,
`docs/Subsystems/Testing/QUAL-CAMPAIGN-920_Wave0_Capability_Campaign_Plan.md`), `STATUS.md` or the operating rules in
`AGENTS.md`. Where this file and those disagree, they win.

## 1. Problem statement

StableNew supports prompt-directed video generation, experimental driving-video generation, a local Motion Library,
deterministic driving-frame preparation, motion-capture conversion and video evaluation. These capabilities operate as
partially connected tools. Successful generated movement is not yet systematically harvested, prepared, evaluated and
reused as a transferable motion capability.

Operators repeatedly rediscover desired motion, manually isolate useful segments in an external editor and work out
compatible settings without enough feedback about movement fidelity, identity preservation or cross-subject
transferability.

## 2. Product vision

Make movement a reusable, searchable and progressively evidence-informed generation input.

Two complementary workflows are supported:

1. **Creative motion discovery** through prompt-directed generation.
2. **Controlled motion generation** through reusable references and evidence-informed conditioning.

Successful motion is preserved independently of the appearance of the subject it came from. Existing RGB-conditioned
workflows do **not** guarantee that appearance and movement are separated, and nothing in this roadmap claims they do.

## 3. Target operating model

`Acquire/discover -> Harvest -> Prepare -> Catalog -> Select -> Align -> Condition -> Generate -> Evaluate -> Learn -> Reuse`

Generated outputs feed back into the Motion Library only through explicit, operator-approved actions. No generation is
queued by importing, harvesting, rating, searching or previewing a motion asset.

## 4. Architecture principles

- The canonical runtime is preserved:
  `Intent -> Compiler -> NJR -> JobService -> Queue/Repository -> PipelineRunner.run_njr -> Handler -> Artifacts/History`.
- Immutable NJRs remain the executable workload authority; SQLite remains the lifecycle authority.
- The Motion Library remains the application-data catalog of reusable motion assets. Motion assets and prepared driving
  inputs have **distinct lifecycles**: a harvested asset is workflow-independent; a prepared driving source
  (PR-VID-MOTION-210) is exact to one workflow, version and length.
- Original media, derived-media identity and lineage are preserved. Originals are read-only.
- Asset preparation, model conditioning and generated-output evaluation are separate concerns.
- No parallel queue, runner, job model, history, qualification ledger or process authority. Existing video Learning and
  evaluation infrastructure is reused.
- Experimental workflow status and per-job consent stay authoritative. Successful source preparation does not prove
  successful generated motion; ratings, metrics and recommendations never authorize workflow promotion.
- Prefer evidence-based compatibility and recommendations over hardcoded assumptions.
- The operator keeps control of settings and of generation submission.

## 5. Development phases

### Phase 1 - PR-VID-MOTION-400: Motion Harvesting and Preparation (implemented)

The reusable asset lifecycle, harvesting handoffs, interactive action-window selection, deterministic derivative
publication, metadata editing and integration with the existing driving-video preparation. Operator guide:
`docs/runbooks/motion_harvesting.md`; design record: `docs/Subsystems/Video/MOTION_LIBRARY.md` section 7.

Exit criterion: a successful existing video can be harvested into multiple reusable motion assets and applied to a
compatible driving-video form without modifying the original or launching generation.

### Phase 2 - PR-VID-MOTION-410: Motion Fidelity and Evaluation (implemented)

Extends the existing evaluation system to compare source images, driving motion and generated outputs. Captures action
achievement, subject attachment, motion fidelity, identity, anatomy and continuity, supports repeatable cross-subject
evaluations and authors a bounded 36-job campaign (staged 3 / 12 / remainder; 26 jobs run so far: the Stage A / B pilot and, after revision, Stage C0, the C1 head-turn cells and C3). Record:
`docs/Subsystems/Video/PR-VID-MOTION-410_Motion_Fidelity_and_Transfer_Evaluation.md`; operator guide:
`docs/runbooks/video_eval_kit.md` section 9.

Exit criterion: motion-transfer experiments can be authored, admitted, compared and rated with verified
case/arm/input/output identity; physical evaluation remains separately authorized. Met by deterministic tests; the owner then
ran and partially reviewed the pilot (15 jobs at 49 frames: no visible arm difference at 1.2 / 1.3) and a revised Stage C (11 jobs
at 81 frames: arms at 0.5 / 2.0 are visibly different, about 7 min and 11.6 GB of 12.3 GB VRAM per job; the start-pose contrast
did not show the matched driver winning). No motion quality, transferability or workflow qualification is claimed, the
motion-specific ratings were not filled, and the full campaign has not run (PR record sections 3.1 and 3.2).

### Phase 3 - PR-VID-MOTION-420: Subject Alignment and Compatibility (implemented; pilot and diagnostic run, unrated)

Source/driver visual comparison, initial-pose and subject-position alignment, operator-controlled spatial preparation
and evidence-informed compatibility advisories. Evaluate manual transforms before any automatic landmark-based
retargeting. Preserve movement trajectories and avoid silent transformations.

Exit criterion: the operator can identify and correct meaningful source/driver alignment differences with explicit,
reproducible transformations.

Status: implemented (deterministic CPU preparation). Compatibility advisories, the Align Motion workspace,
a verified aligned derivative bound to one source image, admission/dispatch/replay checks, and aligned-versus-unaligned
comparison inside the Phase 2 evaluation kit. A 2-job pilot, an 8-job diagnostic and a 2-job re-run have run on the owner's machine, all unrated; the 16-job full stage has not;
whether alignment improves generated motion is unverified. Record: `PR-VID-MOTION-420_Subject_Alignment_and_Compatibility.md`; guide: `docs/runbooks/motion_alignment.md`.

### Phase 4 - PR-VID-MOTION-430: Alternative Conditioning and Engine Qualification

Assess raw RGB, silhouette, Canny, pose-specific representations and other technically applicable approaches. Reuse the
existing Fun Control qualification plan and qualification authority, and compare supported candidates with the Phase 2
evaluation methods. A skeleton render is not an OpenPose map, and different conditioning representations are not assumed
interchangeable.

Exit criterion: candidate workflows have clearly characterized capability, resource and motion-fidelity evidence.
Promotion remains an explicit owner decision.

Status: implemented offline (CPU, deterministic tests; no physical run). Delivered: a conditioning contract derived from each registered graph
(`src/video/workflow_conditioning.py`), related character / silhouette / skeleton variants with verified movement identity, effective-driver
conditioning inspection with a graph-order preview whose edge detector matches the pinned Canny on recorded vectors (still labelled approximate),
engine compatibility in the readiness details, multi-engine and representation comparison kinds with engine and representation summaries, a Fun
Control 1.1.0 qualification proposal (unpinned) beside the unchanged 1.0.0 plan, four unexecuted staged campaign templates (30 jobs before reuse)
and a conditional assessment of three alternative approaches. The Phase 2 and 3 evidence it builds on is mostly unrated, and no Phase 4 physical
evidence exists, so the exit criterion (characterized motion-fidelity and resource evidence) is **not** met. Record:
`PR-VID-MOTION-430_Conditioning_and_Engine_Evaluation.md`; guide: `docs/runbooks/motion_conditioning_and_engine_evaluation.md`; assessment:
`docs/assessments/2026-11-25_vid_motion_430_alternative_conditioning_candidates.md`.

### Phase 5 - PR-VID-MOTION-440: Reusable Motion Recipes

Versioned recipes associate reusable assets with workflow identities, prompts, conditioning settings, preparation
options, compatibility constraints and applicable evaluation evidence. A recipe populates operator intent; it never
bypasses normal admission or silently overrides explicitly pinned settings.

Exit criterion: a previously successful motion configuration can be applied to another compatible source image
reproducibly.

### Phase 6 - PR-VID-MOTION-450: Motion-specific Learning

Aggregate applicable transfer outcomes and derive evidence-informed recommendations for motion assets, workflows and
settings. Distinguish confirmed success, confirmed failure, insufficient evidence and untested combinations. Video
recommendations stay separate from still-image Learning, and replay duplicates or stale ratings cannot inflate
confidence.

Exit criterion: recommendations are explainable, evidence-linked and limited by sample size and compatibility.

### Phase 7 - PR-VID-MOTION-460: Controlled-motion Storyboards

Integrate reusable motion references and recipes with the existing Storyboard/take/sequence architecture. Evaluate
continuity across segment boundaries, source identity retention, action sequencing and selective regeneration through
the existing lifecycle authorities.

Exit criterion: an operator can compose and revise a longer sequence from reusable movements, within physically
demonstrated workflow limits.

### Phase 8 - PR-VID-MOTION-470: Production Readiness and Optimization

Representative target-hardware evaluation, workflow-specific qualification, resource characterization, usability
assessment and performance optimization. Workflow promotion is considered only after the owner accepts the applicable
evidence.

Exit criterion: supported controlled-motion capabilities, limitations and resource requirements are explicit and
evidenced.

The later package identifiers are planning identifiers, **not authorization** to implement those phases.

## 6. Success measures

| Measure | Notes |
|---|---|
| Action achievement rate | Requested action observed / attempts with a judgement |
| Intended-subject attachment rate | The motion attaches to the intended subject |
| Operator-rated motion fidelity | Rated apart from visual quality |
| Critical identity-break rate | Existing video eval rubric |
| Cross-subject transferability | Same asset across different source images |
| Generations required for an acceptable movement | Per asset and workflow |
| End-to-end time to an acceptable result | Operator time plus generation time |
| Motion asset reuse | Distinct jobs per asset |
| Motion harvesting and preparation time | Selection to a verified, catalogued asset |

Every measure keeps its **denominator**, distinguishes missing evidence from failure, and never combines incomparable
configurations (different workflow identity, length, conditioning or preparation). Numerical targets are set only after
representative Phase 2 baseline evidence exists.

## 7. Governance and dependencies

- Phase 1 precedes Phase 2 implementation acceptance.
- Phases 3 and 4 depend on applicable evaluation evidence.
- Phase 5 depends on a stable asset contract and supported workflow evidence.
- Phase 6 depends on trustworthy evaluation and recipe identities.
- Phase 7 depends on compatible sequence capabilities.
- Phase 8 depends on representative physical evidence and owner decisions.

Readiness tooling, deterministic tests and source-level verification do not independently establish physical
qualification. Each physical run still needs the fresh, exact owner authorization `STATUS.md` requires.

Related: `docs/Subsystems/Video/PR-VID-MOTION-410_Motion_Fidelity_and_Transfer_Evaluation.md`, `docs/Subsystems/Video/MOTION_LIBRARY.md`, `docs/Subsystems/Video/VIDEO_PIPELINE.md`,
`docs/Subsystems/Video/PR-VID-MOTION-210_Prepare_Motion_Source.md`,
`docs/Subsystems/Video/PR-VID-MOTION-212_Conditioning_Semantics_and_Fidelity.md`.
