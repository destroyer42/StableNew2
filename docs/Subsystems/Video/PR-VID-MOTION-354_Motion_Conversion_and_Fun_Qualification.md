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
| Q1C | Source-type coverage at 17 frames, one fresh runtime per clip: the Q1 walk plus Mixamo run and Rokoko walk (character FBX), two Xsens skeleton renders (skeleton FBX), two handwritten BVH files, three Pexels MP4s. |
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

### Physical result (2026-11-02, plan digest `58eb515e0df16dfc3e0bd87214d120e6cf4f518d6eb7176ba6bcfd0f83b41b33`)

Authorized by the owner in chat for exactly this digest. Q0 READY (weights, all 12 pinned inputs, runtime commit). GPU RTX 4070 Ti
12 GB, host 32 GB RAM plus a 21 GB page file (commit limit about 54 GB), baseline commit 0.59 with the desktop open.

**Harness verdict: NO-GO**, from `q1c_cov_mp4_dance: host_commit_pressure` with complete telemetry. Q2 was never started (the
harness stops at the first non-clean case).

| Case | Source type | Frames | Wall | Peak commit | Min free RAM | Peak VRAM |
|---|---|---|---|---|---|---|
| q1 Mixamo walk | fbx_character | 17/17 | 27 s | 0.894 | 9791 MiB | 11692 MiB |
| Mixamo running | fbx_character | 17/17 | 35 s | 0.897 | 10686 | 11577 |
| Rokoko walk cycle | fbx_character | 17/17 | 42 s | 0.915 | 9978 | 11630 |
| Xsens walk (skeleton) | fbx_skeleton | 17/17 | 28 s | 0.894 | 10973 | 11730 |
| Xsens run (skeleton) | fbx_skeleton | 17/17 | 30 s | 0.894 | 10661 | 11366 |
| BVH arm raise | bvh | 17/17 | 29 s | 0.892 | 10949 | 11508 |
| BVH walk in place | bvh | 17/17 | 29 s | 0.896 | 11063 | 11732 |
| Pexels treadmill | mp4 | 17/17 | 60 s | 0.921 | 9685 | 11700 |
| Pexels yoga | mp4 | 17/17 | 40 s | 0.909 | 10346 | 11700 |
| Pexels dancing | mp4 | **stopped** | 7.5 s | **0.995** | 5741 | 11896 |

Every case, including the stopped one, passed teardown verification (owned processes gone, VRAM back to its baseline) and the
system event log showed no display-driver, WHEA or power fault. Nothing was retried. In the stopped case the baseline commit
(0.59) and free RAM (14 GB) matched the passing cases, and the clip is the same 480x832 shape as the others; commit climbed from
0.65 to 0.995 in about six seconds during model load while VRAM filled to 11.9 GB (passing cases held 6-10 GB at that point).
The telemetry therefore shows load-phase variability near the commit limit, not a property of that clip; the cause of the
different load behaviour was not isolated.

How to read it: nine of ten 17-frame cases completed with exact frames and clean teardown, and two or three clips completed for
every source type (character FBX 3, skeleton FBX 2, BVH 2, MP4 2). The one stop means 17-frame Fun Control on this host with a
typical desktop open is **marginal, not established**: commit peaks sit at 0.89-0.92 of the limit and one load reached the stop.
This is not a visual-quality result and does not qualify the workflow; the catalog entry is unchanged and still `not_qualified`.
Q2 (49 frames, repeatability, cancel) is NOT RUN.

Visual review (owner-local contact sheets, not committed): character-FBX drivers transferred motion convincingly (walk, run);
the treadmill MP4 transferred the running motion strongly but also leaked its background edges (the Canny preview warns about
dense backgrounds); the Xsens skeleton and handwritten BVH drivers produced nearly static people (a thin white skeleton gives
Canny little to follow); the yoga MP4 start window is a close-up of a hand and foot, a poor driver. The Rokoko and Xsens clips
begin with a T-pose calibration frame that renders as frame 0 (the generated frame 0 is visibly degraded in those clips); choose
a later start until the converter warns about it.

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
* Q2 and the repeatability and cancel/release cases are NOT RUN. A further physical session needs a new owner decision; a retry
  of the stopped case would be a new plan and a new authorization.
* Fun Control remains hardware NOT QUALIFIED; Queue/admission still refuse it.
