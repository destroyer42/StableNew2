# PR-VID-175 — Wan2.2-Animate 480×832 Interpretability Gate

Status: **COMPLETE / ACCEPTED / INTEGRATED — `ANIMATE_480x832_INTERPRETABLE_PASS`**.
Qualification/characterization only. No production `src/` change, no backend, no queue/history
authority, no GUI/controller/resolver change, no Wan production graph/settings change, no workflow
registration, no production integration. Start `main @ a4272a18f1c4d3f38ebd43f401e61a5eb5313e37`.

## Question asked

Does increasing only spatial geometry from PR-VID-170's 256×256 to StableNew's existing portrait
envelope (480×832) make Wan2.2-Animate output visually interpretable enough to assess identity,
anatomy and motion transfer, while remaining physically viable on RTX 4070 Ti 12 GB / 32 GB RAM?

**Yes.** The one authorized generation completed cleanly (no safety stop, no CUDA OOM, no GPU
loss) and produced output that is, by direct visual inspection of the full 13-frame sequence, a
dramatic improvement over PR-VID-170's 256×256 results: the reference person's identity is
consistent and comparable frame-to-frame, arms/torso/hips/legs are clearly resolved throughout, the
hip-hinge/weight-shift motion progression is directly visible and matches the driving pose
sequence's timing, and the severe unrequested camera zoom/reframing seen in every PR-VID-170 case
is gone (the full body stays in frame throughout). Resource cost increased measurably but stayed
well clear of every commit-aware safety threshold. This is an **interpretability gate result
only** — it authorizes the next controlled A/B/C characterization at 480×832; it is not itself a
production-value or quality characterization.

## Experimental control

Reused PR-VID-170 Case C unchanged on every dimension except resolution, because it is the
cleanest resolution-only comparison available (real accepted PR-VID-110 human-motion source, real
hip-hinge/center-of-mass-shift content, no synthetic-pose confound, and both the reference image
and the pose source's native resolution are already 480×832 — no upscaling artifact is introduced).

| Field | Value | Changed from VID-170 Case C? |
|---|---|---|
| Model | `Wan2.2-Animate-14B-Q3_K_M.gguf` | No |
| Text encoder / VAE / CLIP Vision | UMT5 / Wan VAE / `clip_vision_h.safetensors` | No |
| Reference image | `reports/vid110/inputs/source_fullbody.png` | No |
| Seed | `1733123036` | No |
| Steps / cfg / shift | `20 / 1.0 / 5.0` (official Wan2.2-Animate-14B defaults) | No |
| Sampler / scheduler | `uni_pc` / `simple` | No |
| Positive prompt | official default `视频中的人在做动作` | No |
| Negative prompt | `""` | No |
| Frame count / fps | `13` / `8` | No |
| `pose_video` | present | No (content differs only in resolution, see below) |
| `face_video` | absent | No |
| Comfy memory policy | default/auto (`comfy_command_memory_flags: []`) | No |
| **Width × height** | **480 × 832** | **Yes — the only intended variable (was 256×256)** |

Verified by `tests/tools/test_vid175_interpretability.py`
(`test_spec_at_480x832_matches_vid170_case_c_defaults_on_every_other_field`).

## Pose asset — temporal equivalence with VID-170 Case C

`tools/qualification/vid175/pose_asset_480x832.py` reuses
`tools.qualification.vid160c.pose_asset.sample_indices`/`read_frames` **directly, unchanged** —
the same function that selected VID-170 Case C's 13 frames from the same 49-frame source — so the
selected temporal indices are identical by construction, not merely re-verified after the fact.

| Field | Value |
|---|---|
| Source | `reports/vid110/inputs/pose_user.mp4` (unchanged, real, accepted PR-VID-110 asset) |
| Source SHA-256 | `89a9570b1e9ff59c0f4dd9b5f601236373c78db2dbf00fa7cbd8d37e787cd32f` |
| Source frames/dimensions | 49, 480×832, 24 fps |
| Selected indices | `[0, 4, 8, 12, 16, 20, 24, 28, 32, 36, 40, 44, 48]` — confirmed identical to VID-170 Case C's `sample_indices(49, 13)` call (`test_pose_asset_temporal_indices_equal_vid170_case_c`) |
| Adaptation | Temporal resample only — **no crop, no resize** (source is already 480×832, matching the target geometry natively) |
| Final asset | `reports/vid175/case_c_480x832_13f.mp4` — 13 frames, 480×832, 8 fps (`ffprobe`-confirmed) |
| Final asset SHA-256 | `6c45e5ebdd98aed773ba664665ffee4e73a4480c239846766460e625eecaeba1` |
| Contact sheet | `reports/vid175/pose_contact_sheet.png` (not committed) — confirms the identical hip-hinge skeleton motion as VID-170 Case C, now at native portrait aspect instead of a square crop |

Exact temporal equivalence with Case C was achieved by construction; the "STOP if discrepancy"
condition did not trigger.

## Qualification tooling

`tools/qualification/vid175/` — a thin extension over PR-VID-170, not a new harness:

- `pose_asset_480x832.py` — the native-resolution temporal resample above.
- `run.py` — imports `tools.qualification.vid170.graph.CharacterizationSpec`/
  `build_characterization_graph`/`validate_graph` **unchanged**, overriding only `width=480,
  height=832` in the constructed spec; imports `preflight`/`_Stack`/`_teardown` from
  `tools.qualification.vid160b.run`, `stage_pose_video` from `tools.qualification.vid160c.run`,
  and `CommitAwareResourceSampler` from `tools.qualification.vid160c.telemetry` — all reused
  unchanged, no resource-monitoring code duplicated. Submits exactly one prompt; no retry loop;
  releases only the Comfy process its own manager owns.

## Deterministic validation

`tests/tools/test_vid175_interpretability.py` — **12 passed**: frozen geometry is 480×832; every
other `CharacterizationSpec` field is asserted identical to VID-170 Case C's default; the built
graph carries `width=480, height=832`, `pose_video` wired, `face_video` absent; pose-asset temporal
indices are asserted identical to VID-170 Case C's; the native-resolution adaptation preserves
480×832 with no crop; external-runtime refusal; dry-run non-submission; exactly-one-submission with
no retry; partial-evidence-preservation-and-teardown on exception; owner-only teardown; commit-aware
safety thresholds (`WARN_RAM_GB=1.0` now a warning only, `EMERGENCY_RAM_GB=0.25`,
`COMMIT_PERCENT_ABORT=97.0`, `COMMIT_HEADROOM_ABORT_GB=1.0`, `CONSECUTIVE_SAMPLES=2`) asserted
unchanged from PR-VID-160C. Combined with the reused PR-VID-160B/160C/170 suites: **84 tests
passed**. Ruff clean. `git diff --check` clean.

## Pre-run physical gate

Immediately before dispatch: GPU 949 MiB / 12,282 MiB, 0% utilization (idle); no A1111/external
Comfy/unrelated StableNew process; Comfy endpoint unreachable (never externally adopted); system
commit baseline 20.39 GB / 63.76 GB limit / 43.37 GB headroom / 31.98% (not unusually low);
physical RAM available 19.12 GB; staged model assets and both pose/reference hashes reverified
unchanged; no DIAG-GPU-120 event since PR-VID-170. All conditions met; no deferral needed.

## Physical execution

**Submitted, exactly once.** `prompt_id=a87ebb69-b2e0-46a4-b6ea-21dd77541411`.

| Field | Value |
|---|---|
| Wall time | 130.2 s (completed) |
| VRAM baseline / peak | 1,126 / **11,328 MiB** of 12,282 MiB — **954 MiB headroom** |
| Host RAM available, minimum | 2.24 GB (`warn_ram_low_seen: false` — never crossed even the original 1.0 GB warning line) |
| System commit peak / limit | **52.11 / 63.76 GB (81.72%)** |
| System commit headroom, minimum | **11.66 GB** |
| Swap peak | 1.38 GB (4.0%) |
| Comfy working-set/private-usage peak | 0.0 / 0.0 GB (same known PID-tracking instrumentation gap as PR-VID-160C/170; does not affect the decisive system-wide commit figures) |
| Temperature peak | 76 °C |
| Power peak | 236.17 W |
| Stop reason | none |
| Output validity | valid: `ffprobe` confirms H.264, 480×832, 8 fps, exactly 13 frames, matching the frozen spec; 247,354 bytes |
| Owned-runtime teardown | clean: `managed_comfy_owned: true`, `teardown_errors: []` |
| Post-run GPU/RAM recovery | GPU returned to 971 MiB / 12,282 MiB, 0–4% utilization, 48 °C (cooling from 76 °C); no lingering process; host free RAM recovered to ~19.3 GB |

No CUDA OOM, no Comfy allocation failure, no GPU-lost/black-screen/max-fan signature. No retry.

## Primary evaluation: interpretability (direct clip inspection, not contact-sheet-only)

Assessed from the full 13-frame sequence (`reports/vid175/run/case_c_sheet.png`, not committed)
plus individually extracted full-resolution frames (0, 3, 6, 9, 12).

- **Identity visibility — clearly improved, now assessable.** The same person (dark hair pulled
  back, consistent build, navy athletic top/leggings, white sneakers with colored accents) is
  visually consistent across all 13 frames. Face is visible in profile through most of the
  sequence with a soft/painterly but recognizable and stable set of features — materially better
  than PR-VID-170's indistinct color blob, though not photorealistically sharp.
- **Anatomy visibility — clearly improved, now assessable.** Arms, torso, hips, and legs are
  clearly resolved and proportionate in every sampled frame; no missing/extra limb or gross
  deformation observed across the sequence.
- **Motion visibility — clearly improved, now assessable.** The hip-hinge bend visible in the
  early/middle frames and the progressive rise/leg-lift visible in the later frames directly
  matches the driving pose sequence's own bend-then-rise timing (see the pose contact sheet) — this
  is a directly visible, comparable motion-adherence signal, which PR-VID-170 could not provide at
  all.
- **Temporal visibility — assessable, and coherent.** The pose transitions smoothly frame to frame
  with no jarring identity swap, teleport, or morph; this reads as genuine motion, not flicker,
  though the surrounding background continues to shift/hallucinate (see camera behavior below),
  which affects the objective `temporal_jitter` metric more than it affects the subject itself.
- **Camera behavior — the severe unrequested zoom/reframing from PR-VID-170 is resolved for the
  subject framing.** The full body stays in frame throughout, unlike PR-VID-170's cases which
  cropped tightly into a body region. **Background instability persists as a separate, still-present
  issue**: colorful abstract/hallucinated shapes (a blue cylindrical form, a yellow-eyed
  dragon-like shape, floating disc-like objects) appear and shift behind the subject across the
  sequence. This is not the same failure mode as PR-VID-170's camera zoom, and does not prevent the
  identity/anatomy/motion judgments above, but it is not resolved by resolution alone either.

## Controlled comparison to PR-VID-170 Case C

| Dimension | VID-170 Case C (256×256) | VID-175 (480×832) | Direction |
|---|---|---|---|
| Result | completed | completed | same |
| Visual interpretability | severely degraded — identity/anatomy/motion not confidently judgeable | clearly interpretable — identity/anatomy/motion all directly assessable | **materially better** |
| Camera zoom/reframing | severe, unrequested tight crop | resolved — full body stays in frame | **materially better** |
| Background stability | pervasive noise everywhere | subject clean; background hallucination persists | **partially better** (subject-only) |
| `local_motion_px` | 4.24 | 2.80 | lower |
| `camera_drift_px` | 1.43 | 0.25 | lower |
| `motion_area_fraction` | 0.43 | 0.63 | higher |
| `temporal_jitter` | 6.19 | 6.61 | roughly unchanged |
| `identity_hist_mean` (weak proxy) | 0.40 | 0.55 | higher |
| VRAM peak / headroom | 10,837 MiB / 1,445 MiB | 11,328 MiB / 954 MiB | **less headroom** |
| Commit peak % / headroom | 71.85% / 17.95 GB | 81.72% / 11.66 GB | **more commit used, less headroom** |
| Wall time | 63.7 s | 130.2 s | **~2× longer** |
| Temperature / power peak | 65 °C / 205.6 W | 76 °C / 236.2 W | higher |
| Stability outcome | clean | clean | same — no safety-gate trip in either |

**Do not read every difference as caused by resolution alone**: seed and configuration are
controlled, but diffusion sampling behavior is not guaranteed identical across geometry even with a
fixed seed (different latent tensor shape, different noise realization at that shape). The
qualitative interpretability improvement is large and directly visible; the objective metrics move
in mixed directions and are, per prior packages in this lineage, not treated as clean standalone
evidence. The resource-cost delta (VRAM headroom −491 MiB, commit headroom −6.29 GB, wall time
~2×) is real, consistent with the larger latent tensor at 480×832, and did not approach any
commit-aware safety threshold.

## Decision classification

**`ANIMATE_480x832_INTERPRETABLE_PASS`**

The completed output at 480×832 is visually clear enough to make meaningful identity, anatomy, and
motion-transfer judgments — a qualitative step-change from PR-VID-170's 256×256 result. This does
**not** mean Animate itself passes a product-value characterization; it authorizes the next
controlled A/B/C characterization at 480×832 with the same official settings held fixed. Resource
margin (954 MiB VRAM, 11.66 GB commit headroom) remains real but is tighter than at 256×256 and is
worth watching, not yet operationally constrained — no gate came close to tripping.

## DIAG-GPU-120

One additional clean, controlled exposure: no GPU loss, no black screen, no hard reset. Not a
DIAG-GPU-120 PASS and not a root-cause conclusion; DIAG-GPU-120 remains **observation-only, in
progress**.

## Architecture effect

None. Identical to PR-VID-160B/160C/170: direct dispatch to a manager-owned Comfy instance; no
`VideoWorkflowController`/NJR/`VideoExecutionResolver` touched; no second queue/history/runner; no
production `src/` change; Animate remains unregistered as a StableNew workflow; no GUI/controller
work; no model promotion; no sampler/CFG/steps tuning performed.

## Recommended next package

The controlled **A/B/C motion-transfer characterization at 480×832** (PR-VID-170's structure —
local gesture, locomotion, whole-body weight shift — but now at an interpretable resolution)
authorized by this `INTERPRETABLE_PASS` result, using the same fixed official settings
(`cfg=1.0, shift=5.0, steps=20, sampler=uni_pc`) held unchanged. This package does not run that
characterization or move directly to the official 720×1280 size; both remain separate, future,
explicitly authorized decisions.

## Docs/Git

New: `tools/qualification/vid175/` (`__init__.py`, `pose_asset_480x832.py`, `run.py`),
`tests/tools/test_vid175_interpretability.py`, this report. `STATUS.md` to be updated with this
package's durable classification (see closeout). `CODEX_MAP.md` to be given one new row only if the
reusable seam warrants it. No architecture-doc change. No generated video, pose asset, contact
sheet, or telemetry committed (all under `reports/`, gitignored); no model asset committed.

## Explicit confirmations

Exactly one prompt was submitted this session
(`prompt_id=a87ebb69-b2e0-46a4-b6ea-21dd77541411`); no second submission and no retry occurred. No
quant was switched (Q3_K_M unchanged), no steps/CFG/shift/sampler was changed, no frame count/fps
was changed, no `face_video` was added, no move to 720×1280 or A/B/C matrix was made in this
package. No production Animate integration, GUI/controller/resolver work, model promotion, or
GPU/BIOS/XMP/driver/machine-configuration change occurred. `src/controller/app_controller.py` and
`presets/global_positive.txt` (pre-existing unrelated local state) remained untouched and unstaged
throughout.
