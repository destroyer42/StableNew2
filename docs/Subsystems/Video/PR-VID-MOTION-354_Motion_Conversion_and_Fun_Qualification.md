# PR-VID-MOTION-354 — Motion asset conversion, conditioning quality and Fun Control qualification readiness

## Execution profile

Fresh Claude Code desktop session `local_5a980007-4435-4eea-bb35-c44683e1b226` (transcript id
`6e018bf7-21bf-451c-97fd-446e9db10f0b`), created 2026-11-01T23:15:21-05:00 (America/New_York), host `Rob-Gaming-Desk`.
Model `claude-sonnet-5-5`, effort `high`, permission mode `auto`. Isolated worktree `C:/Users/rob/qual/StableNew-motion354`,
branch `video/motion-354-asset-conditioning`, base `579019a759738ca2984351152e8bc3685d79db3a` (verified). The owner's live checkout
was not edited. Python 3.14.9 from the main checkout's virtual environment. Blender is **not installed** on this host and was not
installed by this work; no GPU, model, runtime, download, push or merge was used or performed.

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
| Blender | NOT installed or not selected |

The seven MP4s are importable as they are (no re-encode). The conditioning preview ran on three real MP4s (portrait 4K
treadmill, portrait 1080p yoga, landscape 4K forest pan) in about 4 s each and produced plausible edge maps with the expected
advisories (reduced analysis size, centre crop, a dense-edge background warning). This also exposed that an earlier version of the
preview resized rather than centre-cropped; it was corrected and covered by a test.

## Fun Control 5B qualification proposal (offline, NOT RUN)

`python -m tools.qualification.fun354 propose --out <path outside the repo>` writes a frozen plan (digest `2e0bdbd0...` for the
current catalog with unpinned inputs; any change to assets, runtime, inputs, phases or stop rules changes the digest). `check`
runs **Q0** read-only: catalog identity and `not_qualified`, the three pinned weights by size and SHA-256 (a missing Fun Control
model is a named BLOCKER; nothing is fetched), pinned driving/reference input hashes, installed ComfyUI commit
(`6b747c0428c343e1417219641db93a4fb7cb69ae`), and host RAM/page-file/disk (recorded only; no memory threshold is invented or
borrowed from TI2V). There is no `run` command and this package ships no physical executor.

| Phase | Content |
|---|---|
| Q0 | Offline readiness above. No GPU, no runtime. |
| Q1 | One generation, 17 frames, 480x832, seed 424242, 900 s limit. |
| Q2 | 49 frames seeds 424242 and 424243 (repeatability) plus a cancel/release case, 1800 s limit; only after a clean Q1. |

Stop conditions (frozen in the digest): device loss, allocation failure, host commit >= 0.95, available RAM < 1 GiB for 10 s,
identity mismatch, timeout, unsafe teardown (60 s), telemetry gap (5 s), operator cancel; no automatic retry, no GPU recovery, no
external-process kill. Verdicts: `NOT RUN` (no authorization bound to the plan digest, Q0 not READY, or no case run),
`INCONCLUSIVE` (unreliable evidence), `NO-GO` (a resource stop with complete telemetry and verified identity), `FEASIBLE` (every
case clean) which means technical feasibility on this host only, never visual quality and never a change to the catalog policy.
The runner is exercised with fake executors for each outcome (`tests/video/test_pr_vid_motion_354_fun_qualification.py`).

**Current state: NOT RUN.** Physical execution is not authorized, the Fun Control model file is absent on this host, and the
driving/reference inputs are not yet pinned. Owner steps before any physical session: choose and pin the driving clip and
reference; acquire the Fun Control weights through an owner-approved path; authorize the plan digest explicitly.

## Review and repairs

One aggregate security review covered: process containment and environment, Blender discovery, archive extraction, atomic
publication and ownership-marked deletion, provenance-as-data, symlink handling, network use (none), and fail-open governance.
Required repair applied: a provenance record's `output.file` was used as a path under the result folder, so a tampered record
could name a file outside it; `published_video()` now accepts only a plain file name inside the folder and a structurally valid
record, and verification, reuse and library acceptance use it (test added). Defense-in-depth items left for the owner: the
remembered Blender is run with `--version` when the dialog opens (pin its hash if the install folder is user-writable); Blender
and FFmpeg children inherit the host environment minus Python redirection (no network is used); native FBX/BVH parsing runs in
the contained child but not in a filesystem sandbox; inventory enumerates a tree before applying its file cap.

## Known limitations and open items

* The Blender render script and real FBX/BVH conversion are **unverified against a real Blender** (not installed; installing it
  was forbidden). The "supported animated FBX converts correctly" criterion is therefore PARTIAL: contract, plan, containment,
  verification, publication and library behaviour are tested through a fake Blender that obeys the real command-line contract.
* The Canny preview is approximate; parity with the pinned node's kornia implementation was not verified.
* The dialog does not search for Blender (the engine's `discover_blender` is not wired to a button) and has no library-browser
  button for conditioning preview of an existing MP4 (the workbench method exists).
* Fun Control remains hardware NOT QUALIFIED; Queue/admission still refuse it.
