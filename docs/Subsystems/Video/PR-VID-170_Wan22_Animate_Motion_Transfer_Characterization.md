# PR-VID-170 — Wan2.2-Animate Motion-Transfer Characterization

Status: **COMPLETE / `ANIMATE_QUALITY_INSUFFICIENT_AT_SMALL_ENVELOPE` / PENDING MAIN INTEGRATION**.
Qualification/characterization only. No production `src/` change, no backend, no queue/history
authority, no GUI/controller/resolver change, no Wan production graph/settings change, no workflow
registration. Start `main @ 1bca3e5520389cf6b159db0b27f0257fff8ae127`.

## Product question asked

Does Wan2.2-Animate Move mode transfer useful articulated human motion while preserving the
reference person's identity, anatomy and temporal coherence well enough to justify a
production-integration package — specifically judged against PR-VID-150's stepping/translation
failure and PR-VID-110/VACE's identity-binding failure?

**Not established either way at this envelope.** All three authorized physical runs completed
cleanly (no safety stop, no CUDA OOM, no GPU loss, clean teardown, valid decodable output each
time), using credible official Wan2.2-Animate-14B sampling settings (Phase A). But the rendered
output at the accepted 256×256/13-frame resource envelope was, in all three cases, too visually
degraded — pervasive color noise, severe unwanted camera zoom/reframing the model introduced on its
own, and unresolvable face/identity detail — to confidently answer the product question. This is
recorded as **`ANIMATE_QUALITY_INSUFFICIENT_AT_SMALL_ENVELOPE`**: not a model-capability verdict,
but evidence that a larger-envelope qualification is needed before a product judgment can be made.

## Phase A — quality-setting discovery (official evidence, not invented mappings)

Retrieved directly from the official `Wan-Video/Wan2.2` GitHub repository (Apache 2.0):

| Setting | Official value | Source |
|---|---|---|
| `sample_steps` | **20** | `wan/configs/wan_animate_14B.py` |
| `sample_shift` | **5.0** | `wan/configs/wan_animate_14B.py` |
| `sample_guide_scale` (cfg) | **1.0** | `wan/configs/wan_animate_14B.py` |
| `sample_solver` default | `'unipc'` (choices: `['unipc', 'dpm++']`) | `generate.py` argparse default |
| default `prompt` | `视频中的人在做动作` ("the person in the video is performing an action") | `wan/configs/wan_animate_14B.py` |
| `frame_num` (official default) | 77 | `wan/configs/wan_animate_14B.py` |
| `sample_fps` (official default) | 30 | `wan/configs/wan_animate_14B.py` |
| `SUPPORTED_SIZES['animate-14B']` | `('720*1280', '1280*720')` — **only** these two sizes are supported | `wan/configs/__init__.py` |
| `--size` default | `'1280*720'` | `generate.py` argparse default |

**Official upstream Animate support is materially larger than this package's qualification
envelope**: the model officially supports only 720×1280/1280×720 (defaulting to 1280×720), 77
frames, 30 fps. This package's 256×256/13-frame/8 fps envelope is therefore a **deliberately
resource-constrained qualification envelope, not an upstream-representative quality envelope** —
256×256 is not even among the two officially supported sizes. This context is carried into the
Decision classification and Recommended next package sections below.

`sample_solver='unipc'` maps **directly and unambiguously** to the already-used local Comfy
`uni_pc` sampler — no inference or unsupported mapping was needed; `'dpm++'` is only the other
available choice, not the default, correcting this package's own initial assumption. Local
`KSampler`/`ModelSamplingSD3` `sampler_name`/`scheduler` option lists were inspected directly
(`comfy/samplers.py`) and confirm both `uni_pc` and `simple` are available, unmodified, local
options.

**Frozen characterization configuration** (`tools/qualification/vid170/graph.py`,
`CharacterizationSpec`):

- `steps=20`, `cfg=1.0`, `shift=5.0`, `sampler=uni_pc`, `scheduler=simple` — official values.
- `positive_prompt` = the official default prompt, used **verbatim, unchanged, in all three
  cases** — Animate is motion-driven via `pose_video`, not text-driven; the model's own documented
  default is the most defensible "minimal neutral content prompt," avoiding any invented English
  paraphrase.
- `negative_prompt=""` — unchanged from the resource-testing convention; at `cfg=1.0` the negative
  prompt has negligible formal effect in classifier-free-guidance terms.
- **Deliberately kept from the proven resource envelope, not changed**: `width=256, height=256,
  length=13, fps=8`, per Phase B's explicit instruction to isolate model behavior before
  larger-resolution feasibility — this is a real deviation from the official 77-frame/30fps
  default, made intentionally and documented here, not an oversight.
- `seed=1733123036` — continuity with the PR-VID-140/150/160B/160C lineage.

No sampler-tuning matrix was run; this one configuration was frozen before any physical dispatch
and held identical across all three cases.

## Phase B — geometry

256×256, 13 frames, 8 fps — the proven PR-VID-160B/C resource envelope, unchanged, exactly as
instructed, to isolate model behavior before a larger-resolution feasibility question. Not
increased at any point in this package. As Phase B anticipated might happen, quality at this
envelope proved to be the limiting factor in this package's evidence (see Decision classification).

## Phase C — source/reference identity

Reused unchanged from PR-VID-110/150/160B/160C: `reports/vid110/inputs/source_fullbody.png`.

| Field | Value |
|---|---|
| Path | `reports/vid110/inputs/source_fullbody.png` |
| SHA-256 | `362c86cc83876e340b8927dd54a0f55af1c5fb82c1e9c98d624e67044afa71bb` |
| Dimensions | 480×832, RGB |
| Framing | Full body, standing, front-facing, arms at sides, plain light background |
| Visible body extent | Face, hair, torso, both arms, hips, both legs, feet (athletic top/leggings/sneakers) |

Identical across all three cases; not changed.

## Phase D — driving-motion cases and sourcing provenance

Per the sourcing preference order, existing local inventory was checked first: the **only** real,
pre-existing, accepted driving-motion asset in the repository is
`reports/vid110/inputs/drive_user.mp4` / `pose_user.mp4` (PR-VID-110's skeleton-only lift/hinge
clip). The official `Wan-Video/Wan2.2` repository's `examples/wan_animate/animate/` directory ships
exactly one further example clip (`video.mp4`, content unverified, would require an external
download). **Neither source, individually or together, covers three genuinely distinct motion
types** (local gesture, stepping locomotion, whole-body weight shift/turn).

Rather than download unverified external content (tier 4) for two of the three cases, or install a
new pose-extraction dependency to manufacture footage, this package constructed Cases A and B as
**deterministic, clearly labeled synthetic pose-control sequences**
(`tools/qualification/vid170/synthetic_pose.py`) — plain 2D forward-kinematics stick-figure
rendering via the same OpenCV/numpy already used by `tools.qualification.vid160c.pose_asset`, no
generative model, no new dependency, no pose-extraction library. This is an explicit, honest
deviation from "real motion capture" for two of the three cases, carried as an interpretive caveat
throughout this report: it validly tests whether `WanAnimateToVideo` follows an unambiguous,
idealized pose signal, not robustness to real-world motion-capture noise.

| Case | Purpose | Source | Provenance | Frames/dimensions | SHA-256 |
|---|---|---|---|---|---|
| **A** | Local articulated gesture | **Synthetic** (`render_arm_raise`) | Right arm rotates from hanging down, through horizontal, to overhead, and back down (triangular angle profile); left arm and legs held in a neutral standing pose | 13 × 256×256, 8 fps | `34054b228049289878cf97a8f4f5980d8294b1c4027bac5b53022b0b6e52b0c4` |
| **B** | Locomotion | **Synthetic** (`render_walk_forward`) | Hip/root translates ~36% of frame width left-to-right (≈2 steps) while legs swing in alternating phase (2 full gait cycles) and arms swing in opposition — encodes both stepping articulation *and* whole-body translation unambiguously | 13 × 256×256, 8 fps | `2ff522682388b6a07e45926056efd489477145538637afbc2803d6c19c55c5d9` |
| **C** | Turn / whole-body weight shift | **Real** (existing, accepted PR-VID-110 asset, deterministically resampled by `tools.qualification.vid160c.pose_asset.adapt_pose_video`, identical adaptation code to PR-VID-160C) | A hip-hinge lift: bends forward at the hip, grips, stands back up — genuine center-of-mass shift and torso/hip articulation from a real human motion clip | 13 × 256×256, 8 fps | `1517b9daef601b264f6841154e09306d63e44e4ec6f0f63a4b86aad5bc981e8f` (identical hash to PR-VID-160C's frozen asset — confirms reproducible, unmodified adaptation) |

Visually confirmed via contact sheets before dispatch (`reports/vid170/case_[a|b]_sheet.png`
generation step, not committed): Case A shows a clean, unambiguous raise-and-lower arc; Case B
shows clear alternating leg-swing plus visible whole-body rightward translation; Case C (unchanged
from PR-VID-160C) shows a real, skeleton-only, black-background hip-hinge motion with no RGB
scene/background imagery. `face_video` is absent in all three cases (Phase D requirement, verified
by `validate_graph`).

## Phase E — experiment control

Fixed identically across A/B/C, verified by `tests/tools/test_vid170_qualification.py`
(`test_only_the_pose_video_file_differs_between_case_specs`): reference image, Q3_K_M transformer,
UMT5 text encoder, Wan VAE, CLIP Vision, seed, geometry, frame count, fps, steps, cfg, shift,
sampler, scheduler, positive/negative prompt, Comfy memory policy (confirmed empty
`comfy_command_memory_flags` — default/auto — in all three runs' evidence), no `face_video`. Only
the pose asset changed between cases.

## Phase F — qualification tooling

`tools/qualification/vid170/`:

- `graph.py` — `build_characterization_graph()`/`validate_graph()`; imports the frozen model-file
  constants from `tools.qualification.vid160b.graph` unchanged; identical node shape to
  PR-VID-160C's pose-driven graph, with the sampling settings above.
- `synthetic_pose.py` — the deterministic Case A/B pose renderers (see Phase D).
- `run.py` — imports `preflight`/`_Stack`/`_teardown` directly from `tools.qualification.vid160b.run`,
  `stage_pose_video` from `tools.qualification.vid160c.run`, and `CommitAwareResourceSampler` from
  `tools.qualification.vid160c.telemetry` — **all reused unchanged**, no resource-monitoring code
  duplicated. Adds a `--case {A,B,C}` CLI argument and writes evidence to a per-case directory
  (`reports/vid170/run_<case>/`) so output association can never mix cases. Submits exactly one
  prompt per invocation; no retry loop; releases only the Comfy process its own manager owns.

## Phase G — deterministic validation

`tests/tools/test_vid170_qualification.py` — **19 passed**: exactly three named cases; case
evidence directories are distinct and case-named; `pose_video` always present and wired correctly,
`face_video`/`background_video`/`character_mask` always absent; only the pose-video file differs
between case specs (all other fields assert-equal); frozen settings match the official Wan Animate
defaults (steps/cfg/shift/sampler/prompt, each individually asserted against its cited source);
synthetic pose rendering is deterministic (byte-identical across repeated renders) and produces
non-empty output; external-runtime refusal; dry-run non-submission; exactly-one-submit per
requested case with no retry; each case writes evidence to its own directory, never mixing;
partial-evidence-preservation-and-teardown on exception; owner-only teardown; unknown-case
rejection; commit-aware safety thresholds asserted unchanged from PR-VID-160C. Combined with the
reused PR-VID-160B/160C suites: **72 tests passed**. Ruff clean. `git diff --check` clean.

## Phase H — physical execution

Pre-run gate (each case): GPU idle (≈713–840 MiB baseline, 9–18% transient desktop-compositor
utilization noise at ≤10 W — not a competing workload), no A1111/external Comfy/unrelated
StableNew process, Comfy endpoint unreachable before each dispatch (never externally adopted),
commit baseline healthy (≈63.76 GB limit, ≈44 GB headroom, ~30% used, not unusually low), staged
model assets and pose asset hashes reverified unchanged before each run, no DIAG-GPU-120 event
since PR-VID-160C. All three cases dispatched A → B → C with no deferral needed.

**All three completed. No case triggered a stop condition (safety stop, CUDA OOM, GPU loss).**

| Field | Case A (gesture) | Case B (locomotion) | Case C (weight shift) |
|---|---|---|---|
| `prompt_id` | `2f58556f-f0b9-424e-b31b-c78a57eba9c8` | `95e14ed3-ed3b-4336-9256-99beb1ab1996` | `00b7fd91-3e00-4657-808c-9917967523ba` |
| Status | completed | completed | completed |
| Wall time | 54.8 s | 52.0 s | 63.7 s |
| VRAM baseline / peak | 884 / 10,710 MiB | 885 / 10,653 MiB | 978 / 10,837 MiB |
| Host RAM available, minimum | 0.84 GB | 1.71 GB | 2.01 GB |
| `warn_ram_low_seen` (original 1.0 GB marker) | false | false | false |
| System commit peak / limit | 45.16 / 63.76 GB (70.8%) | 44.73 / 63.76 GB (70.2%) | 45.82 / 63.76 GB (71.9%) |
| System commit headroom, minimum | 18.61 GB | 19.03 GB | 17.95 GB |
| Swap peak | 0.86 GB (2.5%) | 0.88 GB (2.6%) | 1.32 GB (3.8%) |
| Comfy working-set/private-usage peak | 0.0 / 0.0 GB (same known instrumentation gap as PR-VID-160C; does not affect the decisive system-wide commit figures) | 0.0 / 0.0 | 0.0 / 0.0 |
| Temperature peak | 61 °C | 65 °C | 65 °C |
| Power peak | 209.39 W | 215.1 W | 205.59 W |
| Stop reason | none | none | none |
| Output bytes / validity | 57,354 B; H.264, 256×256, 8 fps, 13 frames | 64,119 B; same | 39,347 B; same |
| Owned-runtime teardown | clean | clean | clean |
| Post-run GPU/process state | returned to ≈739 MiB, 0–10% util; no lingering process | ≈714 MiB, 0% | ≈840 MiB, 0% |

Per this package's own explicit policy, none of these resource numbers reopen the PR-VID-160C
32 GB feasibility decision — no safety gate tripped in any case.

## Phase I — objective metrics

Computed with the reused `tools.qualification.vid110.metrics.clip_metrics`/`contact_sheet`
(`identity_hist_*` explicitly labeled a weak appearance proxy, not identity proof, as in every
prior package in this lineage):

| Metric | Case A | Case B | Case C |
|---|---|---|---|
| `local_motion_px` | 3.13 | 4.53 | 4.24 |
| `camera_drift_px` | 0.31 | 0.85 | 1.43 |
| `motion_area_fraction` | 0.56 | 0.71 | 0.43 |
| `temporal_jitter` | 13.29 | 18.41 | 6.19 |
| `identity_hist_mean` | 0.54 | 0.32 | 0.40 |
| `identity_hist_min` | 0.37 | 0.25 | 0.35 |

**Critical caveat, stated up front:** these values are **3–10× higher** than every prior package in
this lineage (PR-VID-150's `temporal_jitter` ranged 0.94–2.07; `motion_area_fraction` ranged
0.09–0.35). Given the pervasive visual noise observed directly in the frames (Phase J), these
elevated motion/jitter numbers are very likely **substantially contaminated by pixel-level color
noise being counted as optical-flow motion**, not a clean signal of stronger articulated motion or
worse flicker in a meaningful sense. Per this package's own instruction, these metrics assist human
review and do not override the obvious visual quality failure documented directly below; they are
reported for completeness and future comparison, not treated as a clean quantitative result.
Pose-control adherence evidence (framewise motion-timing/optical-flow-direction agreement against
the driving pose sequence) was attempted but is **not reported as reliable**: the same noise
contamination that inflates the motion metrics above would equally contaminate any adherence-timing
comparison, so no adherence number is presented as trustworthy evidence.

## Phase J — human visual rubric

Scored directly from contact sheets (`reports/vid170/run_*/case_*_sheet.png`, not committed) and
extracted individual frames. Where the contact sheet cannot establish something confidently, the
score is marked **(uncertain)** rather than asserted, per this package's own instruction. Raw scores
are kept un-collapsed.

| Criterion | Case A (gesture) | Case B (locomotion) | Case C (weight shift) |
|---|---|---|---|
| Identity retention | 2 (uncertain) — a consistent single-figure silhouette persists but no distinguishing feature is resolvable | 1 (uncertain) — near-total crop/noise loss | 1 (uncertain) — near-total crop/noise loss |
| Face preservation | 1 — face renders as an indistinct color blob, no features | 1 — face not resolvable / mostly out of frame | 1 — face not resolvable / mostly out of frame |
| Anatomy | 3 (uncertain) — a plausible single-person humanoid proportion persists through heavy noise; no confirmed missing/extra limb, but not fully verifiable | 2 (uncertain) — visible torso/hip/leg shapes are plausible but the tight, unstable crop prevents full-body verification | 2 (uncertain) — a plausible torso/hip region emerges in later frames; early frames show an ambiguous shape difficult to confirm as anatomical |
| Driving-motion adherence | 3 (uncertain) — a horizontal arm extension is visible around the sequence midpoint, roughly matching the requested raise timing, but noise limits confidence | 1 (uncertain) — the pose signal unambiguously encoded stepping/translation; the rendered output gives no confident visual confirmation this was followed (feet not visible in the crop) | 2 (uncertain) — some posture change is visible between early/late frames; not clearly identifiable as the driving clip's specific hip-hinge |
| Whole-body translation / locomotion (Case B only) | n/a | 1 (uncertain) — no confident evidence of actual stepping/displacement in the output despite an unambiguous translating pose signal | n/a |
| Temporal coherence | 1 — visibly flickery/glitchy throughout, consistent with the elevated jitter metric | 1 — worst of the three, consistent with the highest jitter metric | 2 (uncertain) — comparatively less flickery than A/B by both eye and metric, still visually degraded |
| Camera stability | 2 — unrequested drift/glitch in framing, though the overall composition stays roughly full-figure | 2 — severe unrequested zoom toward the torso, framing shifted substantially from the reference composition | 1 — the most extreme unrequested zoom of the three; essentially no stable full-figure framing at any point |
| Overall usefulness | 2 — not currently useful; establishes only that a single coherent silhouette was produced | 1 — not useful; the case most central to the product question (locomotion) is the least interpretable | 1 — not useful |

## Phase K — comparative interpretation

**Versus PR-VID-150 (Wan2.2 TI2V-5B, text-prompted):** PR-VID-150 established
`local_motion_viable_locomotion_weak` — the model's own text-prompt-driven attempt at stepping left
the feet visibly planted. Case B here supplied an *unambiguous, externally provided* stepping/
translation pose signal (not asking the model to infer motion from text at all), which is a
materially different and in principle easier test. But the rendered output's quality was
insufficient to confirm whether that signal was actually followed. **This does not confirm Animate
solved PR-VID-150's failure mode, and does not confirm it did not — the comparison is genuinely
inconclusive at this envelope**, for a different reason (render quality) than PR-VID-150's failure
(prompt-inference limitation).

**Versus PR-VID-110 / VACE (reference-binding failure):** VACE's failure was reproducing a
*different, clearly visible* person while following motion. Here, no case resolved *any* clearly
visible face in either direction, so there is no clearly-visible-wrong-person signal to compare
against, and equally no clearly-visible-right-person signal to credit. **This comparison is also
inconclusive at this envelope** — the evidence cannot show Animate solved VACE's identity problem,
because identity-bearing detail was not resolvable at all, in either direction, at 256×256 under
these settings.

Both comparisons are blocked by the same root cause (Phase A/B envelope + settings combination),
not by two independent capability failures — supporting the chosen classification below over a
capability-failure classification.

## Decision classification

**`ANIMATE_QUALITY_INSUFFICIENT_AT_SMALL_ENVELOPE`**

Consistent across all three cases, independent of driving-motion content: pervasive visual noise,
substantial unrequested camera zoom/reframing, and unresolvable face/identity detail, despite
credible official sampling settings (Phase A) sourced directly from the model's own upstream
configuration. Per this package's own definition, this does **not** mean the model is
fundamentally incapable of articulated motion transfer or identity retention — it means this
specific controlled 256×256/13-frame envelope, at these settings, did not produce output
interpretable enough to answer the product question either way. A controlled larger-envelope
qualification is needed before a product viability judgment can be made.

**Correction (product-owner review):** an earlier draft of this section speculated that `cfg=1.0`
specifically — rather than resolution — might be the dominant driver of the observed degradation,
and proposed isolating `cfg=1.0` versus resolution in a future package. That framing is corrected
here: `cfg=1.0` (`sample_guide_scale`) is the model's own official Animate guidance baseline (Phase
A), not an unvalidated or experimental setting, and should remain **fixed**, not treated as a
variable to tune, in any future characterization. The far more parsimonious explanation, now that
official supported geometry has been recorded (Phase A/B above), is simply that **256×256 is not
even among the two officially supported Animate sizes** (`720×1280`/`1280×720`) — this package
qualified the model at roughly a fifth of its smallest officially validated linear dimension.
PR-VID-160B/160C's resource-testing settings (`cfg=5, shift=8, steps=4`) did produce visibly
cleaner output at the same 256×256 envelope, but that observation does not establish `cfg` as the
cause; it is recorded here only as a raw data point, not as a hypothesis this package endorses
pursuing. This package does not test resolution sensitivity further; doing so would require a
fourth generation, which is not authorized here.

## DIAG-GPU-120

Three additional clean, controlled exposures: no GPU loss, no black screen, no hard reset in any of
Case A/B/C. Not a DIAG-GPU-120 PASS and not a root-cause conclusion; DIAG-GPU-120 remains
**observation-only, in progress**.

## Architecture effect

None. Identical to PR-VID-160B/160C: direct dispatch to a manager-owned Comfy instance; no
`VideoWorkflowController`/NJR/`VideoExecutionResolver` touched; no second queue/history/runner; no
production `src/` change; Animate remains unregistered as a StableNew workflow; no GUI/controller
work; no model promotion.

## Recommended next package

**Controlled larger-envelope Animate characterization with official inference settings held
fixed** (`cfg=1.0`, `shift=5.0`, `steps=20`, `sampler=uni_pc` unchanged — Phase A's official
baseline, not a variable), to determine whether increasing spatial resolution toward the officially
supported sizes (`720×1280`/`1280×720`; frame count/fps may also need to move toward the official
77/30 defaults) makes identity/anatomy/motion-transfer output interpretable on the current 12 GB
VRAM / 32 GB RAM workstation — this package's PR-VID-160B/C resource evidence already establishes
that the backbone alone fits with real margin at small geometry, so the open question is purely
whether a larger, officially-representative geometry remains resource-feasible and produces
interpretable output, not whether the settings need retuning. Separately, and not blocking that
question, a future package should prefer at least one genuinely real (not synthetic) locomotion
driving clip if one can be sourced without a new dependency, so the locomotion case is not solely
dependent on an idealized procedural walk cycle. This package does not authorize or attempt either
step.

## Docs/Git

New: `tools/qualification/vid170/` (`__init__.py`, `graph.py`, `run.py`, `synthetic_pose.py`),
`tests/tools/test_vid170_qualification.py`, this report. `STATUS.md` to be updated with this
package's durable classification (see closeout). `CODEX_MAP.md` to be given one new row for the
reusable `tools/qualification/vid170/` seam. No architecture-doc change. No generated videos,
control videos, or telemetry committed (all under `reports/`, gitignored); no model asset committed.

## Explicit confirmations

Exactly three prompts were submitted this session, one per case (A, B, C); no fourth submission and
no retry of any case occurred. No quant was switched (Q3_K_M unchanged from PR-VID-160B/C), no
resolution/frame count was increased mid-experiment, no `face_video` was added, no sampler/step
tuning occurred after seeing results (all three cases used the identical, pre-frozen Phase A
settings), no production Animate integration, GUI/controller/resolver work, model promotion, or
GPU/BIOS/XMP/driver/machine-configuration change occurred. `src/controller/app_controller.py` and
`presets/global_positive.txt` (pre-existing unrelated local state) remained untouched and unstaged
throughout.
