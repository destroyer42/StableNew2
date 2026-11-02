# PR-VID-MOTION-354 — Motion asset conversion, conditioning quality and Fun Control qualification readiness

## Execution profile

Fresh Claude Code desktop session `local_5a980007-4435-4eea-bb35-c44683e1b226` (transcript id
`6e018bf7-21bf-451c-97fd-446e9db10f0b`), created 2026-11-01T23:15:21-05:00 (America/New_York), host `Rob-Gaming-Desk`.
Model `claude-sonnet-5-5`, effort `high`, permission mode `auto`. Isolated worktree `C:/Users/rob/qual/StableNew-motion354`,
branch `video/motion-354-asset-conditioning`, base `579019a759738ca2984351152e8bc3685d79db3a` (verified). The owner's live checkout
was not edited. Python 3.14.9 from the main checkout's virtual environment. The first segment ran offline with no Blender, GPU,
model, runtime or download. The owner then explicitly authorized (chat, 2026-11-02) installing Blender, downloading the Fun
Control weights, running real conversions and running physical qualification clips; those are reported under "Follow-up
segment" and "Physical result" below. No push, publish or merge was performed.

## What was built

| Area | Result |
|---|---|
| Inventory | `tools/motion_asset_inventory.py` + `src/video/motion_conversion/inventory.py`: read-only; header-only FBX scan (`fbx_scan.py`), zip central directory only; counts by type/source/rig, duplicates, conversion-ready, missing dependency, unsupported, archives awaiting extraction. |
| Conversion engine | `conversion_plan.py` (frozen exact-rational plan, canonical digest, legal lengths from the workflow), `rig_compat.py` (exact bone-name binding, honest refusal), `blender.py` + `blender_scripts/motion_render.bpy` (contained CPU-only child), `conversion_service.py` (private owned work dirs, FFmpeg encode, frame/duration verification, atomic publication, provenance, verified reuse), `archive_extract.py` (explicit, bounded, zip-slip-safe). |
| Library | `motion_library/derivation.py` + `models/store/importer/snapshot` hooks: a derivation record keeps the original's identity apart from the derivative's; searchable; survives restart; selecting never queues. `library_bridge.accept_conversion` refuses previews and unverifiable folders. |
| GUI | `motion_conversion_contract.py` (toolkit-neutral, per-kind stale/closed result dropping), `motion_conversion_dialog.py` (non-modal Tk), `video_motion_conversion_controller.py` mixin (thin delegation), Convert Motion... button on the Motion Library panel. Ports live in `src/video/motion_conversion/ports.py` so the controller imports nothing from `src.gui`. No ratcheted controller was touched. |
| Conditioning preview | `conditioning_preview.py`: deterministic CPU NumPy Canny (0.1 / 0.6), centre-cropped to the generation shape exactly as the pinned `Wan22FunControlToVideo` node does (`common_upscale(..., "center")`, read from the installed ComfyUI v0.38.0 source), always labeled *approximate* (`EXACT_PARITY_VERIFIED = False`), bounded advisory warnings, no Comfy, no job mutation. |
| Qualification proposal | `tools/qualification/fun354/` (below). |

The canonical execution path is unchanged: no queue, runner, NJR schema, history authority or compiler authority was added, and
no controller ceiling was raised. The immutable Fun Control 1.0.0 catalog entry is untouched (a test builds the proposal and
asserts the spec is unchanged and still `not_qualified`).

## Local acceptance on the owner's assets (read-only)

Library root `%USERPROFILE%/Videos/StableNewMotionLibrary` (path not committed). Before/after tree snapshots of all 735 files
(relative path, size, mtime) were **identical**: nothing was moved, deleted, renamed or modified.

| Measure | Result |
|---|---|
| Items (files + zip members) | 769: .fbx 759, .mp4 7, .txt 1, .zip 2 |
| Source families | Mixamo 141, Pexels 7, Rokoko 621 |
| Rig families | mixamo 249, unknown 458 |
| Duplicate-content items | 53 |
| Conversion-ready / missing dependency / unsupported / awaiting extraction / invalid | 707 / 17 / 1 / 37 / 0 |
| Blender | Not installed at the time of this survey (installed in the follow-up segment) |

The seven MP4s are importable as they are (no re-encode). The conditioning preview ran on three real MP4s (portrait 4K
treadmill, portrait 1080p yoga, landscape 4K forest pan) in about 4 s each and produced plausible edge maps with the expected
advisories (reduced analysis size, centre crop, a dense-edge background warning). This also exposed that an earlier version of the
preview resized rather than centre-cropped; it was corrected and covered by a test.

## Fun Control 5B qualification

`python -m tools.qualification.fun354 propose --out <path outside the repo> --inputs-manifest <m.json> --reference <img>` writes a
frozen plan; `check` runs **Q0** read-only (catalog identity and `not_qualified`, the three pinned weights by size and SHA-256,
every pinned driving/reference input, the installed ComfyUI commit `6b747c0428c343e1417219641db93a4fb7cb69ae`, and host
RAM/page-file/disk, recorded only: no memory threshold is invented or borrowed from TI2V). Any change to assets, runtime,
inputs, prompt, coverage, phases or stop rules changes the digest. `python -m tools.qualification.fun354.physical` is the only
thing that can run a case and refuses unless `--authorize-plan` equals the stored plan's digest and Q0 is READY for it.

| Phase | Content |
|---|---|
| Q0 | Offline readiness above. No GPU, no runtime. |
| Q1 | One generation, 17 frames, 480x832, seed 424242, 900 s limit (Mixamo walk). |
| Q1C | Source-type coverage at 17 frames, one fresh runtime per clip: the Q1 walk plus Mixamo run and Rokoko walk (character FBX), two Xsens side-view skeleton renders (skeleton FBX), three handwritten BVH files, three Pexels MP4s (pre-scaled to 480x832). |
| Q2 | 49 frames seeds 424242 and 424243 (repeatability) plus a cancel/release case, 1800 s limit; only after a clean Q1. |

Stop conditions (frozen in the digest): device loss, allocation failure, host commit >= 0.95 for two samples, available RAM <
1 GiB for 10 s, identity mismatch, timeout, unsafe teardown (60 s), telemetry gap (5 s), operator cancel; no automatic retry, no
GPU recovery, no external-process kill. The executor starts a fresh owned `ComfyProcessManager` runtime per case (scratch
input/output/temp/user folders outside the repo, `--disable-pinned-memory --disable-auto-launch --disable-all-custom-nodes`),
re-checks the runtime commit, graph digest, input hashes and launch flags before launch and `/system_stats` after, validates the
object schema, renders the catalog template with the compiler's own renderer, dispatches once, validates exact frame count and
geometry, then verifies the owned process tree and VRAM released and reads the system event log for driver/hardware faults.
Verdicts: `NOT RUN`, `INCONCLUSIVE` (unreliable evidence), `NO-GO` (a resource stop with complete telemetry and verified
identity), `FEASIBLE` (every case clean): technical feasibility on this host only, never visual quality and never a change to the
catalog policy. Offline tests drive the executor with fake managers and clients for every outcome
(`tests/video/test_pr_vid_motion_354_fun_physical.py`).

### Physical results (2026-11-02, three owner-authorized runs on the same host)

GPU RTX 4070 Ti 12 GB, host 32 GB RAM plus a 21 GB page file (commit limit about 54 GB). The owner authorized each plan digest in
chat. Run 1 and run 2 are kept as evidence because they show what is and is not safe to feed the workflow.

| Run | Plan digest | Verdict | What happened |
|---|---|---|---|
| 1 | `58eb515e0df1...` | NO-GO | 9 of 10 clips clean at host commit 0.89-0.92 (desktop apps open); `q1c_cov_mp4_dance` reached host commit 0.995 during load and was stopped. |
| 2 | `99bea6b0f90c...` | INCONCLUSIVE | Apps closed; 9 clips clean at commit 0.65-0.69; `q1c_cov_mp4_wave` made no progress for 900 s after load and hit the timeout (one `nvlddmkm` event 153 was logged at the moment the owned process tree was stopped, teardown clean). |
| 3 | `a6080f532d00...` | **FEASIBLE** | All 14 cases clean, including Q2. |

**Finding from runs 1 and 2.** Both failing clips were the 4K landscape MP4s. Source preparation is deliberately exact and does not
rescale, so those clips reached Comfy at 3840x2160 (and the treadmill at 1440x2560) while the graph runs `LoadVideo ->
GetVideoComponents -> Canny` at the clip's own resolution and only then lets `Wan22FunControlToVideo` resize to 480x832. Every
clean clip in runs 1 and 2 was 480x832 (Blender output) except the treadmill, which was the slowest clean case (60-67 s versus 22-37 s).
Run 3 pre-scaled the three MP4 drivers to 480x832 with ffmpeg (lanczos, centre crop, CRF 12) as operator input preparation, and
every MP4 completed in 22-24 s. This is evidence about the inputs, not a change to the frozen catalog graph.

**Run 3 detail** (plan `a6080f532d0043f0cca13490149353466dab6730b76b83576d6b88298da2e720`; Q0 READY; every case passed teardown
verification with owned processes gone and VRAM back to baseline; the system event log showed no display-driver, WHEA or power fault):

| Case | Source type | Frames | Wall | Peak commit | Min free RAM | Peak VRAM |
|---|---|---|---|---|---|---|
| q1 Mixamo walk | fbx_character | 17/17 | 24 s | 0.665 | 15534 MiB | 11792 MiB |
| Mixamo running | fbx_character | 17/17 | 26 s | 0.657 | 15599 | 11792 |
| Rokoko walk cycle (T-pose skipped) | fbx_character | 17/17 | 22 s | 0.651 | 15656 | 11354 |
| Xsens run and jump, side | fbx_skeleton | 17/17 | 22 s | 0.654 | 15673 | 11376 |
| Xsens run forward, side | fbx_skeleton | 17/17 | 22 s | 0.653 | 15589 | 11408 |
| BVH both arms raised | bvh | 17/17 | 22 s | 0.655 | 15767 | 11532 |
| BVH walk in place, side | bvh | 17/17 | 22 s | 0.655 | 15644 | 11538 |
| BVH jumping jacks | bvh | 17/17 | 23 s | 0.661 | 15760 | 11784 |
| Pexels treadmill (pre-scaled) | mp4 | 17/17 | 22 s | 0.655 | 15608 | 11461 |
| Pexels waving (pre-scaled) | mp4 | 17/17 | 24 s | 0.664 | 15649 | 11813 |
| Pexels dancing (pre-scaled) | mp4 | 17/17 | 23 s | 0.664 | 15152 | 11802 |
| Q2 walk 49 frames, seed 424242 | fbx_character | 49/49 | 60 s | 0.673 | 15905 | 11799 |
| Q2 walk 49 frames, seed 424243 | fbx_character | 49/49 | 54 s | 0.663 | 16086 | 11671 |
| Q2 cancel and release | fbx_character | interrupt sent at 20 s | 21 s | 0.649 | 16338 | 11009 |

Reading it: with the desktop mostly closed, 17-frame and 49-frame Fun Control completed on this host with exact frame counts, a second
seed, a cancel that released VRAM, and clean teardown. Peak VRAM sits at 11.0-11.9 GB of 12.3 GB in every case, so there is little
headroom, and with a typical desktop open (run 1) commit climbed to 0.89-0.92 and one load reached the 0.95 stop. This is technical
feasibility on this host only. It is not a visual-quality result and does not qualify the workflow: the catalog entry is unchanged and
still `not_qualified`, and Queue/admission still refuse it.

Visual review (owner-local contact sheets and side-by-side videos, not committed): Mixamo and Rokoko character drivers transferred
walking and running convincingly; the Xsens side-view skeleton drivers (run, run and jump) transferred strong, readable motion once
rendered from the side; the handwritten BVH drivers transferred arm raises, jacks and a side-view walk, with some artefacts on the
hands; MP4 drivers transferred motion but also leaked their own face, clothing and background (the waving clip lost the reference
identity almost entirely). Earlier front-view skeleton renders and a BVH that covered only the first fraction of its motion gave nearly
static people; those drivers were replaced with side or three-quarter views, a later start and one-second motion cycles.

## Review and repairs

One aggregate security review covered: process containment and environment, Blender discovery, archive extraction, atomic
publication and ownership-marked deletion, provenance-as-data, symlink handling, network use (none), and fail-open governance.
Required repair applied: a provenance record's `output.file` was used as a path under the result folder, so a tampered record
could name a file outside it; `published_video()` now accepts only a plain file name inside the folder and a structurally valid
record, and verification, reuse and library acceptance use it (test added). Defense-in-depth items left for the owner: the
remembered Blender is run with `--version` when the dialog opens (pin its hash if the install folder is user-writable); Blender
and FFmpeg children inherit the host environment minus Python redirection (no network is used); native FBX/BVH parsing runs in
the contained child but not in a filesystem sandbox; inventory enumerates a tree before applying its file cap.

## Follow-up segment: real Blender, GUI gaps and acceptance

Blender 4.5.9 (official Windows x64 zip, checksum matched) was installed in a tools folder outside the repository; the Fun Control weights
came from the pinned Hugging Face revision with exact size and SHA-256 matches. Running the script against a real Blender
found and fixed, each with a test or a visual check: Blender 4.4+ slotted actions need an explicit `action_slot` (without it the
animation silently did not play); a skeleton drawn as loose edges renders nothing (now closed spindle solids per joint-to-joint
segment); bone tails do not reach child joints in FBX; the in-place root re-parented imported meshes away from their armature;
the camera fit used the sensor width for portrait; and a retarget between rigs that share bone names but not rest poses distorts
the character, so it is now refused (10 degree tolerance over limb-scale segments). The host verifies rendered frames are not
blank and not all identical before publishing, and `SCRIPT_VERSION` (now 8) is part of the plan digest so a script change never
serves a stale cached clip.

GUI gaps closed: **Find Blender** (verified with `--version`) and a library-browser **Preview Conditioning...** button for any
usable clip, both covered by view-contract and Tk tests. Real conversions were inspected for Mixamo and Rokoko character FBX,
Xsens skeleton FBX and handwritten BVH, front/side/three-quarter, static and tracking cameras, portrait and landscape, in-place
root.

## Known limitations and open items

* Putting an animation onto a *separate* reference character is verified only as a refusal: no compatible skeleton-only/character
  pair exists in the local library (the Xsens files do not match any HumanIK character's rest pose; Mixamo-named skeleton exports
  were refused by the rest-pose check), so the success path is UNVERIFIED on real data and was left out of physical qualification.
* The BVH files used were written by hand; no real mocap BVH is available locally.
* The Canny preview is approximate; parity with the pinned node's kornia implementation was not verified.
* The converter does not yet warn that a clip's first frame is a T-pose calibration frame (Rokoko and Xsens files).
* MP4 driving clips are not rescaled by source preparation; a 4K MP4 stalled the graph in two physical runs (Canny runs at the
  clip's own size). The pre-scale used in run 3 was operator preparation outside the app. Whether preparation should scale to the
  workflow geometry, or the preview should refuse oversized sources, is an open product decision.
* The generated frames are single-run samples from one reference image and seed; ranking drivers by look is owner feedback, not a
  measured result.
* Fun Control remains hardware NOT QUALIFIED; Queue/admission still refuse it.
