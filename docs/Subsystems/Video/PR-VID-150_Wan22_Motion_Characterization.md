# PR-VID-150 — Wan2.2 Motion Characterization & Prompt Evidence

Status: **COMPLETE / QUALIFICATION ONLY**. This package adds no backend, queue, lifecycle,
scheduler, runtime-ownership, or production-graph authority. It changes no Wan production
setting. Whether to act on its recommendation is a separate product-owner decision.

Execution class: Terra Medium, Local/Desktop. Start `main @ 43d6727d30085292c330b5837827616629a7cd6`.

## Purpose

Characterize the practical prompt-controlled human-motion envelope of the already-integrated
experimental Wan2.2 TI2V-5B workflow (`wan22_ti2v_5b_i2v_v1` v1.0.0) on the RTX 4070 Ti 12 GB
target, to answer:

1. Does structured/sequential motion prompting materially improve motion/action adherence versus
   a terse action prompt, with source/seed/settings held constant?
2. Can structured prompting produce useful whole-body locomotion/body translation while retaining
   acceptable identity, anatomy and temporal coherence?
3. Is the next highest-value product work better Wan prompting/presets, more Wan characterization,
   or qualification of another consumer-GPU motion backend?

## Experimental design

All three runs used the exact production chain proven by PR-VID-130/140 (`VideoWorkflowController
-> immutable NJR -> JobService -> SQLite -> PipelineRunner.run_njr -> VideoExecutionResolver ->
ComfyWorkflowVideoBackend -> StableNew-managed Comfy -> artifact/history`), reused via a new
qualification-only harness, `tools/qualification/vid150/run.py`, that adds an explicit frozen seed
to the same submission pattern as `tools/acceptance/vid130_wan_acceptance.py`. It selects no
backend, mutates no production Wan setting, and owns no runtime lifecycle beyond releasing a
Comfy process this run's own managed manager launched. Each case is one process invocation with
exactly one job and no retry.

**Source.** `reports/vid110/inputs/source_fullbody.png` (480x832, RGB) — the existing PR-VID-110
full-body still (one person, full body, arms and legs visible, limited occlusion, plain
background with surrounding space). No new source was captured or generated. Because the source
is already 480x832, the catalog-declared portrait preparation (EXIF transpose, RGB conversion,
cover-resize, center-crop to 480x832) reproduced it byte-for-byte as
`case_*/workspace/output/prepared_video_sources/362c86cc83876e340b89_480x832_cover_resize_center_crop.png`
for all three cases — same original, same prepared image, same target/prepared dimensions
(480x832, portrait), confirmed identical across A/B/C.

**Seed.** `1733123036` (the accepted PR-VID-140 seed), frozen and confirmed via NJR readback
(`stage["seed"] == 1733123036`) identically for all three jobs.

**Held constant across all three runs:** source image, prepared image, seed, negative prompt
(empty — the workflow's catalog default), geometry (480x832 portrait), model/files, steps (20),
CFG (5), sampler (`uni_pc`), scheduler (`simple`), frame count (49), fps (24), and
`experimental_opt_in=true`. Only the positive motion prompt changed.

**Cases (all authorized, all run, no retries):**

- **Run A — terse gesture baseline:** `"The person raises their right hand and waves."`
- **Run B — structured equivalent gesture:** `"Camera locked. The person stays in place, raises
  their right arm from their side to shoulder height, waves twice, then lowers the arm. The head
  follows the hand slightly. Natural shoulder, arm, clothing and hair movement. No zoom, pan,
  orbit or scene change."`
- **Run C — structured locomotion:** `"Camera locked. The person takes two deliberate steps
  forward with natural weight transfer and opposing arm swing, then stops. Keep the same person,
  face, clothing and scene. No zoom, pan, orbit or scene change."`

No adaptation of Run C's locomotion direction/distance was needed; the source framing (full body,
open floor space in front) was appropriate for two forward steps as written.

## Run evidence

| Field | Run A | Run B | Run C |
|---|---|---|---|
| Job ID | `0e2922df81e34bf4a444f50d11e8318b` | `6dd8b5b76c184806b1a6c1929625b187` | `0c9dd7045dc74fc9b5872d72d0b493b5` |
| Status | completed | completed | completed |
| Wall time | 107.7 s | 89.5 s | 86.5 s |
| Artifact | `wan22_..._00001_.mp4` (234,780 bytes) | `wan22_..._00001_.mp4` (259,126 bytes) | `wan22_..._00001_.mp4` (263,337 bytes) |
| Frames/fps/duration | 49 / 24.0 / 2.0417 s | 49 / 24.0 / 2.0417 s | 49 / 24.0 / 2.0417 s |
| Geometry | 480x832 | 480x832 | 480x832 |
| VRAM baseline/peak | 1,222 / 11,668 MiB | 1,210 / 11,634 MiB | 1,213 / 11,629 MiB |
| Peak temperature | 72 °C | 75 °C | 77 °C |
| Peak power | 242.6 W | 247.74 W | 248.71 W |
| Min available host RAM | 0.18 GB | 0.02 GB | 1.61 GB |
| Throttle reasons (nvidia-smi bitmask) | `0x405` | `0x405` | `0x405` |
| Queue/history/replay | COMPLETED; replay `1` created with identical `video_execution`, correct parent lineage | same | same |

No GPU loss, black screen, max-fan, process/device disappearance, or bugcheck occurred in any run.
`nvidia-smi` and process listing confirmed a full return to idle (≈1,220 MiB, 0% util, cooling
toward ambient, no lingering Comfy/python process) between every run. This is three additional
clean post-PR-VID-140 exposures with no DIAG-GPU-120/100 recurrence; it is not a stress campaign
and establishes no stability verdict.

### Objective metrics (relative comparison only; no validated absolute thresholds)

| Metric | Run A | Run B | Run C |
|---|---|---|---|
| `local_motion_px` | 0.2543 | 0.5279 | 0.7574 |
| `camera_drift_px` | 0.0060 | 0.0411 | 0.1884 |
| `motion_area_fraction` | 0.0901 | 0.2005 | 0.3549 |
| `temporal_jitter` | 2.0742 | 1.0823 | 0.9416 |
| `identity_hist_mean` (weak appearance proxy, not identity proof) | 0.3572 | 0.5325 | 0.4676 |
| `identity_hist_min` | -0.0127 | 0.0469 | 0.0399 |

These are same-source/same-seed relative comparisons only. `local_motion_px` and
`motion_area_fraction` rise monotonically A→B→C, but the optical-flow metric cannot distinguish
limb motion from body translation — Run C's higher numbers are shown below to come from arm
swing and torso sway, not stepping. `camera_drift_px` also rises for Run C; visual review shows
the background stays structurally static (aside from the same color-cast drift seen in all three
runs), so this is read as body-motion leaking into the global-flow estimate rather than true
camera movement.

## Qualitative rubric (1–5; contact sheets only — temporal claims beyond what 12 static frames can
show are marked uncertain)

| Criterion | Run A | Run B | Run C |
|---|---|---|---|
| Identity/appearance retention | 3 — person, hair, clothing consistent; a strong pink/magenta background-and-lighting cast appears in the second half in all three runs (unrequested, not identity loss) | 3 — same cast; slightly higher appearance-proxy score | 3 — same cast; face/build still recognizable |
| Face quality | 4 — stable, consistent expression | 4 — stable | 4 — stable |
| Limb/anatomy quality | 4 — clean raise, hand slightly soft at full extension | 3 — visible motion blur/ghosting on the hand during the wave | 2 — the swinging arm shows a blurred/malformed forearm in the later frames |
| Temporal coherence | 3 (uncertain) — highest jitter metric; visible abruptness around the color-cast transition | 4 (uncertain) — lower jitter metric, visually smoother | 3 (uncertain) — lowest jitter metric, but this does not capture the arm-motion blur artifact seen visually |
| Requested-action adherence | 4 — hand raises and waves as asked | 4 — raise/wave/lower sequence and slight head-follow are visible; "twice" not confidently countable from static frames | 1 — no forward stepping or weight transfer occurs; feet stay planted across all 12 frames while the arm swings |
| Amount of subject motion | 2 — limited to the raised hand/forearm | 4 — visibly more arm/shoulder excursion | 3 — most measured motion is arm swing and torso sway, not the requested translation |
| Camera stability | 5 — static, no zoom/pan/orbit | 5 — static | 4 — static camera; elevated flow-drift metric attributed to body sway, not camera motion |
| Overall usefulness for the intended motion | 3 — plausible minimal gesture | 4 — materially more usable directed gesture | 2 — fails the core locomotion request despite intact identity/face |

The histogram identity proxy was not used to set the identity/appearance score; it is reported
only as a weak, separate signal in the objective table.

## A vs B — prompt-structure comparison

Same source, same seed, same requested action (raise the right hand and wave). Structured
sequential prompting (Run B) produced:

- **More motion:** `local_motion_px` roughly doubled (0.25 → 0.53) and `motion_area_fraction`
  more than doubled (0.09 → 0.20); visually the arm excursion and wave are clearly larger.
- **Smoother temporal quality:** `temporal_jitter` fell by about half (2.07 → 1.08), consistent
  with a visually less abrupt clip.
- **No camera change:** both runs are static; `camera_drift_px` stays negligible in both.
- **A small anatomy cost:** Run B shows more hand/wrist motion blur during the more vigorous wave
  than Run A's single clean raise.
- **Identity/appearance:** comparable; both show the same unrequested background/lighting
  color-cast shift partway through the clip, present in both runs so not attributable to prompt
  structure.

Conclusion: for this local gesture, structured sequential prompting was **materially helpful** —
more of the requested motion, better temporal smoothness, adherence intact, with only a minor,
acceptable anatomy tradeoff during the more active wave.

## B vs C — motion-class comparison

Same source, same seed, same structured prompting style, moving from local gesture/pose motion
(Run B) to whole-body locomotion (Run C):

- **Requested-action adherence collapses:** Run C's prompt asked for two forward steps with
  weight transfer; the contact sheet shows the person's feet in essentially the same planted
  position in the first and last frame, with no visible forward translation or weight shift. The
  observed motion is arm swinging and torso sway, not stepping.
  Do not read Run C's motion-metric rise as evidence of successful locomotion.
- **Anatomy degrades further:** the working arm shows a blurred/indistinct forearm in later
  frames, worse than Run B's milder wave-blur.
- **Objective motion/drift metrics keep rising** (0.53 → 0.76 local motion; 0.04 → 0.19 camera
  drift), which — read together with the visual evidence — indicates the optical-flow metric is
  picking up more vigorous *non-translational* body motion, not the requested locomotion.
- **Identity/face and camera stability remain acceptable** in both B and C.

Conclusion: structured prompting's benefit from Run A→B **does not extend to whole-body
locomotion**. This one case does not prove locomotion is unreachable with different prompts,
models, or seeds, but it does not deliver it here.

## Evidence classification

**`local_motion_viable_locomotion_weak`**

Structured sequential prompting produced a materially more useful local gesture/pose clip (Run B
vs Run A) with acceptable identity, anatomy and temporal quality. The same structured style failed
to produce whole-body locomotion/body translation (Run C): the person's feet never left their
planted position despite two explicit, deliberate forward-step instructions, and anatomy quality
on the moving limb degraded further under the harder motion request.

## Recommended next package

Per the evidence classification, the next highest-value investment is **consumer-GPU
motion-backend qualification** (a new candidate — likely FramePack and/or LTX-Video 2B research
lane) rather than further Wan2.2 prompt tuning for locomotion; Wan2.2 structured-prompt presets
for local gesture/pose motion remain a reasonable, separate, lower-effort follow-up for operator
presets given the clean A→B result, but should not be expected to solve locomotion.

## Architecture and lifetime review

- `VideoWorkflowController` remains admission-only; `VideoExecutionResolver` remains the sole
  backend-selection authority. No controller responsibility changed.
- No Wan production graph, resolution, frame count, sampler, scheduler, or settings were modified.
  All three jobs used the unchanged accepted PR-VID-140 defaults.
- `tools/qualification/vid150/run.py` orchestrates bounded qualification cases and metrics only;
  it builds its own isolated SQLite/output workspace per case (the same pattern PR-VID-130's
  acceptance harness uses) and owns no production runtime lifecycle beyond releasing a Comfy
  process its own managed manager launched. It introduces no second queue, second history, or
  alternate runner.
- Wan remains EXPERIMENTAL and per-job opt-in; this package does not promote it.

## Validation

- New deterministic tests: `tests/tools/test_vid150_qualification.py` — case planning (exactly
  three cases, only the prompt varies), fixed-seed/prompt form-data serialization, unknown-case
  rejection, stop-before-build on an externally served Comfy endpoint, dry-run never submits,
  exactly-one attempt with no automatic retry on a failed case, and partial-evidence
  preservation/teardown on an exception. **8 passed.**
- Ruff on touched files (`tools/qualification/vid150/`, `tests/tools/test_vid150_qualification.py`):
  clean. `git diff --check`: clean.
- Local `python tools/ci/run_pr_gate.py` was not rerun; the existing local-`mypy`-unavailable
  tooling blocker is unchanged from PR-VID-140 and is not re-litigated here. Required GitHub
  Python 3.11/3.12 CI is pending for this branch's push.
- Three real physical acceptance runs (A/B/C) through the canonical production path, detailed
  above, each with clean GPU-idle return and no DIAG-GPU-120/100 recurrence.

## Limitations

- One source image, one seed, one run per case (as authorized) — this is a bounded qualification
  sample, not a statistically powered study; it does not prove locomotion is unreachable for Wan
  under different seeds, sources, or prompt phrasings.
- `identity_hist_mean/min` is an HSV-histogram correlation proxy, explicitly not identity proof;
  it was not used to set the visual identity/appearance score.
- The unrequested pink/magenta color-cast appearing in the second half of all three clips is
  recorded as an observation, not diagnosed; it is outside this package's scope (no graph/settings
  change is authorized here) and worth a follow-up note for whoever next touches Wan prompting.
- Contact-sheet-only review cannot fully establish temporal quality between the 12 sampled frames;
  temporal-coherence scores above are marked uncertain for that reason.

## Explicit exclusions

No new video backend, no Wan production graph/settings change, no resolution/frame-count increase,
no promotion of Wan from experimental, no Video Workflow UI redesign, no Learning integration, no
autonomous prompt rewriting, no fourth generation, no automatic retry, no GPU/BIOS/driver change,
and no `main` integration of this branch (product-owner review required).
