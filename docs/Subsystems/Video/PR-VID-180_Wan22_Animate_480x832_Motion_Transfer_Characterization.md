# PR-VID-180 — Wan2.2-Animate 480×832 Motion-Transfer Characterization

Status: **COMPLETE / `ANIMATE_CHARACTERIZATION_INCONCLUSIVE`**. Qualification/characterization
only. No production `src/` change, no backend, no queue/history authority, no GUI/controller/
resolver change, no Wan production graph/settings change, no workflow registration, no production
integration. Start `main @ 908c9f65a8ebe1a11f88eb822429bf9122cf774c`.

## Question asked

PR-VID-175 established `ANIMATE_480x832_INTERPRETABLE_PASS`: at 480×832, Wan2.2-Animate's real
hip-hinge (Case C) output became visually interpretable. This package asks the product-value
question that interpretability made askable: at that same resource-viable, interpretable envelope,
does Animate transfer useful **gesture** (Case A) and genuine **stepping/root translation**
(Case B) while preserving identity, anatomy and temporal coherence? It also asks whether the
background hallucination/instability PR-VID-175 observed is Case-C-specific, common across motion
inputs, or severe enough to block an experimental StableNew integration.

**Answer, stated up front:** gesture (A) and locomotion (B) both failed clearly at 480×832 using
this package's synthetic stick-figure driving-pose input — but that result is confounded by driving
-pose *representation*, not isolated to resolution or to Animate's underlying capability. See
"Confound: synthetic vs. real driving-pose format" below. Background instability is common across
all three cases (not Case-C-specific) and is independently severe.

## Reuse of PR-VID-175 Case C

Per instruction, Case C was **not rerun**. PR-VID-175's already-accepted physical evidence is
reused as this package's Case C:

- prompt `a87ebb69-b2e0-46a4-b6ea-21dd77541411`, status `completed`, re-verified directly from
  `reports/vid175/run/evidence.json` (still locally present, read-only);
- accepted classification `ANIMATE_480x832_INTERPRETABLE_PASS`;
- accepted qualitative result: identity, anatomy and the real hip-hinge motion progression clearly
  assessable; background hallucination/instability persists as a separate, already-flagged issue.
- Its output clip (`reports/vid175/run/case_c_480x832_output.mp4`) remained locally available, so
  it was analyzed **read-only** alongside A/B's new output for objective metrics and a direct
  frame re-inspection (`reports/vid175/run/frame_6.png`) — no new generation, no mutation of
  PR-VID-175's evidence or label.

No code path in `tools/qualification/vid180/run.py` can submit Case C: `CASES` contains only `"A"`
and `"B"`, and `--case` is `argparse`-constrained to `sorted(CASES)`.

## Fixed matrix

Frozen identically across A, B and reused C (`tools.qualification.vid170.graph.
CharacterizationSpec`, only `width`/`height` overridden exactly as PR-VID-175 did):

| Field | Value |
|---|---|
| Model | `Wan2.2-Animate-14B-Q3_K_M.gguf` (+ same UMT5/Wan VAE/CLIP Vision) |
| Reference image | `reports/vid110/inputs/source_fullbody.png` |
| Reference SHA-256 | `362c86cc83876e340b8927dd54a0f55af1c5fb82c1e9c98d624e67044afa71bb` (verified this session, matches exactly) |
| width × height | 480 × 832 |
| length | 13 |
| fps | 8 |
| steps | 20 |
| cfg | 1.0 |
| shift | 5.0 |
| sampler / scheduler | `uni_pc` / `simple` |
| seed | 1733123036 |
| prompt | official default (`视频中的人在做动作`) |
| negative prompt | `""` (unchanged) |
| `pose_video` | present |
| `face_video` | absent |

Verified via `test_spec_at_480x832_matches_frozen_defaults_on_every_other_field` and
`test_case_a_and_b_differ_only_by_pose_asset` (the latter diffs the full built graphs node-by-node
and confirms the only differing field across A/B is the `LoadVideo` `file` input).

## A/B native-resolution control provenance and normalized-motion equivalence

`tools/qualification/vid180/native_pose.py` is a clean-room reimplementation of
`tools.qualification.vid170.synthetic_pose`'s motion *semantics* at 480×832. VID-170's module and
historical fixtures (`case_a_arm_raise.mp4`, `case_b_walk_forward.mp4`) are unmodified — nothing in
VID-180 imports or mutates VID-170's render functions.

Resolution-independent quantities are preserved exactly:

- **Case A arm-angle progression**: `angle(t) = pi * sin(pi*t/12)` — identical formula, verified
  frame-by-frame (`test_native_case_a_arm_angle_matches_vid170_case_a_every_frame`) against an
  independent transcription of VID-170's formula.
- **Case B gait phase / leg swing**: `phase(t) = 2*pi*2.0*(t/12)`, `swing = radians(28)*sin(phase)`
  — identical formula, verified frame-by-frame
  (`test_native_case_b_gait_phase_and_leg_swing_match_vid170_case_b_every_frame`).
- **Case B root-translation fraction**: `hip_x_fraction(t) = 0.32 + 0.36*(t/12)` — the same
  fractions of canvas width VID-170 used (`0.32*W` to `0.68*W`), verified frame-by-frame
  (`test_native_case_b_root_translation_fraction_matches_vid170_case_b_every_frame`).
- Frame count (13) and fps (8.0) unchanged.

Absolute pixel quantities (limb lengths, joint offsets) are scaled by `SCALE = 480/256 = 1.875`
(the new/old *width*, the shared constrained dimension) so the figure stays proportioned in the
taller 480×832 portrait canvas; this affects only rendered appearance, not motion semantics.

Rendering is deterministic (`test_render_arm_raise_native_is_deterministic_and_480x832`,
`test_render_walk_forward_native_is_deterministic_and_480x832` — same-input SHA-256 equality) and
frames contain a non-trivially large nonzero-pixel skeleton in every frame (independently checked
this session, min/max nonzero pixels: A 18,605–22,123, B 16,984–26,540, over 13 frames each).

Control hashes (this session, `sha256_of`):

| Case | Control file | SHA-256 |
|---|---|---|
| A | `reports/vid180/case_a_arm_raise_480x832.mp4` | `76b59a6144cd7cf21c2cfec526323e08b38a7b8ef70f1edc83a97fd52f007471` |
| B | `reports/vid180/case_b_walk_forward_480x832.mp4` | `8700b474a4839b44e74ab3d483f9f2ca4703396606e69308bb9f05baeda20e29` |

Control frames were visually reviewed directly (`reports/vid180/case_a_control_sheet.png`,
`case_b_control_sheet.png`, not committed): Case A shows a clean overhead-and-back arm arc; Case B
shows alternating-leg swing with visible left-to-right root translation across the sequence and
opposing arm swing. Both match the intended VID-170 semantics visually, not only numerically.

## Qualification tooling

`tools/qualification/vid180/` — `native_pose.py` (above) and `run.py`. `run.py` is a direct
extension of `tools.qualification.vid170.run`: same `_Stack`/`_teardown`/`preflight` (PR-VID-160B),
same `stage_pose_video`/`CommitAwareResourceSampler` (PR-VID-160C), same `ComfyClient` (PR-VID-110),
same `build_characterization_graph`/`validate_graph` (PR-VID-170, unchanged) with `width=480,
height=832` overridden exactly as PR-VID-175 did. `CASES = {"A": ..., "B": ...}` deliberately
excludes `"C"`, so no code path can submit it. Distinct evidence directories
(`reports/vid180/run_a/`, `reports/vid180/run_b/`) prevent output mixing. No new runtime/lifecycle
authority: still direct dispatch to a manager-owned Comfy instance, never through
`VideoWorkflowController`/NJR/`VideoExecutionResolver`.

## Deterministic validation

`tests/tools/test_vid180_motion_characterization.py`, 22 tests, all green under the project venv
(`.venv`, Python 3.12.14 — the system `python` lacks `opencv-python`; this is the same interpreter
implied by `pyproject.toml`'s `opencv-python>=4.10.0` dependency):

```
22 passed in 0.55s
```

Covers: only A/B runnable, no Case C submission path, case output dirs distinct, frozen 480×832
spec matches PR-VID-170/175 defaults on every other field, graph contains `pose_video`/never
`face_video`, A/B graphs differ only by pose asset, native-resolution motion formulas equal VID-170
Case A/B frame-by-frame, deterministic rendering, external-Comfy refusal, dry-run non-submission,
`--case C` rejected by argparse, exactly-one-submission/no-retry, partial-evidence-persistence on
exception, owner-only teardown, commit-aware safety thresholds unchanged.

Reuse-check (source unchanged, prior evidence still green this session):
`test_vid175_interpretability.py` + `test_vid170_qualification.py` — 31 passed.

Ruff: `tools/qualification/vid180/` and the new test file — all checks passed. `git diff --check`:
no whitespace errors.

## Pre-run gate (confirmed before each submission)

Before Case A: GPU idle (988–1030 MiB used, ≤1–10% transient utilization, 39°C baseline), no A1111,
no external Comfy on `127.0.0.1:8000` or `:8188` (both unreachable), reference/control hashes
frozen and verified, no unresolved DIAG-GPU-120 recurrence. Preflight (`endpoint_state: "free"`)
confirmed via `--dry` before the real run.

Between A and B: full return to idle confirmed (GPU memory back to ~1,005–1,030 MiB baseline, 0–1%
utilization, no Comfy process in the task list, endpoint unreachable) before Case B was submitted.
Case B's own preflight also reported `endpoint_state: "free"`.

## Physical runs submitted

Exactly two, exactly once each, no retries:

| Case | prompt_id | status |
|---|---|---|
| A | `bc67b1d7-0e5c-4751-a9af-78b5dae4f470` | `completed` |
| B | `a49493ad-a2e1-4e97-b99d-8515dc352c8d` | `completed` |

Neither tripped the commit-aware safety gate (`stop_reason: ""` in both). No CUDA OOM, no GPU loss,
no black screen. Case C was not submitted (evidence directory `run_c/` does not exist under
`reports/vid180/`).

## Resource evidence

| Metric | Case A | Case B | Case C (reused) |
|---|---|---|---|
| `vram_peak_mib` | 11,515 | 11,522 | 11,328 |
| `vram_headroom_mib` (12,282 total) | 767 | 760 | 954 |
| `ram_available_min_gb` | 1.30 | 1.59 | 2.24 |
| `commit_percent_peak` | 81.57% | 81.41% | 81.72% |
| `commit_headroom_min_gb` | 11.75 | 11.86 | 11.66 |
| `swap_used_max_gb` | 1.20 | 1.21 | 1.38 |
| `temp_peak_c` | 79 | 81 | 76 |
| `power_peak_w` | 240.51 | 243.95 | 236.17 |
| `wall_seconds` | 127.0 | 126.4 | 130.2 |
| clean teardown | yes (`managed_comfy_owned: true`, no teardown errors) | yes | yes (PR-VID-175) |

All three cases are closely clustered and well clear of every PR-VID-160C commit-aware safety
threshold (`commit_percent_abort=97%`, `commit_headroom_abort=1.0GB`, `warn_ram=1.0GB`,
`emergency_ram=0.25GB`). Per this package's own instruction, this does not reopen PR-VID-160C's
32GB feasibility decision — resource viability at 480×832 is consistent with PR-VID-175 and is not
the limiting factor found by this package.

## Objective metrics (secondary evidence — do not override direct visual evidence)

`tools.qualification.vid110.metrics.clip_metrics` / `motion_curve` / `curve_correlation`. Case C
recomputed read-only from PR-VID-175's still-local, unmodified output file (not a rerun):

| Metric | Case A | Case B | Case C (reused, read-only) |
|---|---|---|---|
| `local_motion_px` | 0.532 | 2.152 | 2.804 |
| `camera_drift_px` | 0.016 | 0.247 | 0.251 |
| `motion_area_fraction` | 0.170 | 0.453 | 0.628 |
| `temporal_jitter` | 0.732 | 5.948 | 6.611 |
| `identity_hist_mean` | 0.248 | 0.498 | 0.549 |
| `identity_hist_min` | 0.208 | 0.305 | 0.308 |
| **motion-curve correlation vs. its own driving control** | **-0.089** | **0.005** | **0.398** |

The motion-curve correlation (pose-control optical-flow curve vs. output optical-flow curve,
resampled to a common length) is a **timing/motion-energy correlation proxy, not direct skeletal
adherence**. Only Case C shows a meaningfully positive correlation; A and B are indistinguishable
from noise (≈0). This is consistent with, not the basis for, the direct visual findings below —
background hallucination can and likely does contaminate optical flow in A and B, so these numbers
are reported as corroborating context, not as the primary evidence.

## Human visual rubric (raw scores, 1–5, not averaged)

Scored by direct inspection of the full 13-frame sequence at native 480×832 resolution
(`reports/vid180/case_a_output_sheet.png`, `case_b_output_sheet.png`, plus individually extracted
full-resolution frames `frame_a_{0,6,12}.png`, `frame_b_{0,6,12}.png` — not committed).

| Criterion | Case A (gesture) | Case B (locomotion) |
|---|---|---|
| Identity retention | 1 — no recognizable person in any of the 13 frames; the frame is abstract noise throughout | 3 — a single, consistent foreground figure with reference-matching clothing (dark top with light chest graphic, dark leggings, cyan/yellow sneakers) persists in every frame; facial identity is not confirmable |
| Face stability | 1 — no face resolvable | 1 — face present but not resolvable as stable, confirmable detail |
| Anatomy | 1 — no credible humanoid structure anywhere in the sequence | 3 — the main figure has plausible, credible single-person proportions throughout; a second, anatomically incoherent "ghost" figure is also present and is not credible |
| Driving-motion adherence | 1 — no subject exists to assess articulation on | 1 — the main figure is essentially static (arms at sides) across all 13 frames despite the supplied alternating-leg gait signal; the only visible motion is the incoherent ghost figure, which does not visibly track the gait cycle |
| Root translation / locomotion (Case B) | n/a | **1 — no visible stepping or center-of-mass translation of the main figure across the sequence; this is the critical, product-defining negative result** |
| Temporal coherence | 1 — flickering/incoherent abstract shapes throughout | 2 — the main figure itself is stable only because it is not moving; background and ghost figure are highly unstable frame to frame |
| Subject framing | 1 — no subject to frame | 4 — the main figure stays well-framed, full-body, roughly centered throughout (consistent with PR-VID-175's finding that 480×832 resolves the severe zoom problem seen at 256×256) |
| Background stability | 1 — indistinguishable from subject failure; the whole frame hallucinates | 1 — severe, pervasive background hallucination (scrambled geometric shapes, garbled pseudo-text) plus an unexplained secondary humanoid-ish artifact not present in the driving signal |
| Overall usefulness | 1 — not useful; establishes only that this driving-pose input produced no interpretable gesture output at 480×832 | 1 — not useful for the product's central locomotion question; the stepping signal was not visibly followed |

## Background behavior across A/B/C

Background instability is **common across all three motion inputs tested, not Case-C-specific**:
severe/total in A (no subject/background distinction survives), severe in B (scrambled
shapes/pseudo-text plus an unexplained ghost figure alongside an otherwise-stable foreground
subject), and present-but-secondary in C (PR-VID-175: subject clearly assessable, background
"remains" unstable). Read together with PR-VID-175, background hallucination looks like an
independent, cross-case property of this graph/settings combination at 480×832 — severe enough on
its own that it would need bounded mitigation research before any production-adjacent use, even in
a hypothetical future case where gesture/locomotion transfer is confirmed viable.

## Explicit gates

**Gesture gate (Case A): FAILED.** No arm-raise/lower sequence is visible; no subject is present to
carry it.

**Locomotion gate (Case B): FAILED.** Direct clip inspection shows no alternating steps, no
foot/leg progression, and no center-of-mass/root translation — not even a planted-feet leg
animation; the main figure does not move at all.

**Identity gate: MIXED, weak overall.** Identity did not survive in A (no person). In B, clothing/
build-level consistency is plausible but facial identity is unconfirmed. In reused C, PR-VID-175
found identity clearly assessable. Identity was only clearly retained when the driving signal was a
real photographic pose video (C), not a synthetic stick-figure one (A/B) — see next section.

**Background gate: FAILED across all three cases**, recorded separately per instruction: subject
success (C) did not come with background success, and subject failure (A/B) does not explain away
the background finding as merely downstream of subject failure, since B's foreground subject was
comparatively stable while its background was not.

## Confound: synthetic vs. real driving-pose format

This is the central interpretive finding of this package. Case A/B used the same
deterministic-but-synthetic, colored-line-on-black stick-figure pose control PR-VID-170 introduced
(no real gesture/locomotion footage was available locally, exactly as PR-VID-170 disclosed). Case C
used a real, photographic PR-VID-110 pose video. At the *same* interpretable 480×832 envelope and
*identical* official inference settings:

- Real pose video (C): identity, anatomy, and motion all clearly assessable (PR-VID-175).
- Synthetic pose video (A, B): identity/anatomy/motion transfer all failed or were materially weak.

The evidence in this package cannot separate two different explanations for A/B's failure:
**(1)** Wan2.2-Animate genuinely cannot transfer gesture/locomotion well even at an interpretable
envelope, or **(2)** Wan2.2-Animate's `pose_video` conditioning expects a driving signal closer in
representation to what it was trained on (plausibly a real-derived pose-estimator render, e.g.
DWPose-style, extracted from actual footage) and responds poorly to this package's simplified
synthetic stick-figure convention, independent of the model's true gesture/locomotion capability.
PR-VID-170's `synthetic_pose.py` docstring already flagged this class of limitation ("not
robustness to real-world motion-capture noise"); this package's result is the first direct evidence
that the gap may be larger than a robustness nuance. This is exactly why the classification below is
`ANIMATE_CHARACTERIZATION_INCONCLUSIVE` rather than a capability verdict.

## Historical comparisons

**Versus PR-VID-150 (Wan2.2 TI2V-5B, text-prompted, `local_motion_viable_locomotion_weak`):**
PR-VID-150's own text-inferred stepping attempt at least produced visible (if planted-feet) leg
motion. Case B here was given an unambiguous, externally supplied stepping/translation pose signal
— in principle an easier task than inferring motion from text — and produced *no* visible leg
articulation at all. **This does not confirm Animate solved PR-VID-150's locomotion gap; on this
evidence it does not, and the result is if anything more negative than PR-VID-150's own attempt** —
though, per the confound above, this may reflect the driving-pose format rather than a genuine
regression in underlying capability. This is a product-capability comparison, not a controlled
numerical one (different models, different envelopes, different settings).

**Versus PR-VID-110/VACE (reference-binding failure):** VACE could not reproduce the reference
person's identity while following motion. Here, Case C (real pose video) does retain identity while
following motion — a genuine, positive point of contrast with VACE, already recorded in PR-VID-175.
Cases A/B (synthetic pose video) do **not** extend that result: identity did not reliably survive
either. **The VACE-identity improvement demonstrated so far is tied to a real photographic driving
signal, not yet shown to generalize to a synthetic one.**

## Decision classification

**`ANIMATE_CHARACTERIZATION_INCONCLUSIVE`**

Gesture (A) and locomotion (B) both failed clearly and directly at 480×832 with this package's
synthetic stick-figure driving-pose input — that failure itself is a solid, reproducible, real
finding, not an artifact of missing evidence (both runs completed cleanly, graph/dependency
validation passed, resource telemetry was unremarkable, and the failure was confirmed by direct
full-resolution frame inspection, not only thumbnails). What remains open is the *cause*: this
package cannot separate "Animate cannot transfer gesture/locomotion" from "Animate's `pose_video`
conditioning needs a real/photographic-style driving signal, not a synthetic stick-figure one" —
because the one case that succeeded (C) used a real pose video and the two that failed (A, B) used
a synthetic one. Per this package's own definition, resource/stability failures would get their own
report and stop the package; that did not happen here (all three cases completed cleanly and well
within safety thresholds) — this is a characterization result, not a resource-failure report.

This does **not** mean Animate is confirmed capable or confirmed incapable of gesture/locomotion
transfer. It does **not** license moving to `ANIMATE_MOTION_TRANSFER_VIABLE_480x832` or to
`ANIMATE_NOT_VIABLE_480x832` on the current evidence. It does mean background hallucination is a
separate, common, cross-case concern that would need bounded mitigation research regardless of how
the confound resolves.

## DIAG-GPU-120

Two additional clean, controlled exposures (Case A, Case B): no GPU loss, no black screen, no hard
reset, no new unresolved recurrence, commit-aware safety gate never tripped. Not double-counted
with PR-VID-175's Case C exposure. Not a DIAG-GPU-120 PASS and not a root-cause conclusion;
DIAG-GPU-120 remains **observation-only, in progress**.

## Architecture effect

None. Identical to PR-VID-160B/160C/170/175: direct dispatch to a manager-owned Comfy instance via
`ComfyProcessManager`; no import from `src.controller`/`src.queue`/`src.history`; no second
queue/history/runner authority; Animate remains an unregistered, non-production workflow. No
production Wan/backend setting or governance changed; no sampler/CFG/steps/quant/resolution/frame
-count tuning performed; no `face_video` added; no background conditioning added; no production
Animate integration begun.

## Recommended next package

Before any gesture/locomotion product verdict: a package that isolates the synthetic-vs-real
driving-pose confound directly — e.g. sourcing or adapting real photographic gesture and locomotion
footage (mirroring how PR-VID-175 adapted `reports/vid110/inputs/pose_user.mp4` for Case C) and
rerunning the equivalent of Case A/B with a real driving signal instead of `synthetic_pose`-style
output, at the same frozen 480×832/official-settings envelope. Separately, and regardless of that
result, background-hallucination bounded mitigation research is warranted given its consistent
presence across all three cases tested so far (PR-VID-175 + this package).

## Docs / Git

- `docs/Subsystems/Video/PR-VID-180_Wan22_Animate_480x832_Motion_Transfer_Characterization.md`
  (this file).
- `tools/qualification/vid180/__init__.py`, `native_pose.py`, `run.py` (new).
- `tests/tools/test_vid180_motion_characterization.py` (new, 22 tests, green).
- No generated clips, telemetry, control videos, or model assets committed (`reports/` is
  git-ignored via `.gitignore:76 /reports/`, confirmed this session with `git check-ignore -v`).
- Branch `vid/180-animate-480x832-motion-characterization`, not integrated to `main` without
  separate product-owner review, per instruction.

## Explicit confirmations

- Exactly two new physical submissions (Case A, Case B); Case C was reused, not rerun.
- No retries: each case's evidence shows exactly one `prompt_id`.
- No quant/resolution/frame-count/cfg/steps/shift/sampler change from the frozen matrix.
- No `face_video` added; no background conditioning added.
- No production Animate integration begun; no machine configuration modified.
