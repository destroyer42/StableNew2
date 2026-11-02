# Runbook: converting mocap files to driving videos (PR-VID-MOTION-354)

Operator procedure for **Convert Motion** in the Video Workflow tab's Motion Library. Nothing here queues a job, starts Comfy,
loads a model or uses the GPU. StableNew never downloads or installs Blender.

## Before you start

1. Install Blender 4.2 or newer yourself (any location). StableNew only runs a `blender.exe` you choose.
2. Choose a Motion Library folder (Motion Library panel). Converted clips are kept beside it in `conversions/`.
3. Optional read-only survey of a mocap download folder (writes only the JSON you name, outside that folder):

```bash
python -m tools.motion_asset_inventory --root "<your motion asset folder>" --out "<somewhere outside it>/inventory.json"
```

It reports counts by type and source family, duplicates, conversion-ready, missing-dependency (animation without skeleton or
mesh) and unsupported items, and archives awaiting an explicit extraction. It never opens an FBX in Blender.

## Converting one clip

1. Motion Library -> **Convert Motion...**. **Choose Blender...** verifies the executable with `--version` (the dialog runs only the file you pick and does not search your machine). A previously chosen Blender is re-verified the same way when the dialog opens.
2. **Choose animation file...** (.fbx or .bvh). The header scan says what it is and whether it can be converted.
3. **Inspect** (one bounded Blender child) reads the animation's rate, range and bones.
4. Pick profile, camera, camera mode, root motion, start and length. The length list is the selected workflow's own legal lengths
   (Fun Control: 17-49, step 4, offset 1). The plan summary shows the exact frames used; a segment longer than the animation is
   refused (nothing is trimmed, padded or slowed).
5. An animation-only skeleton FBX renders as a skeleton unless you also pick **Use reference character...**; StableNew then needs
   every needed bone name to match exactly and otherwise refuses with the missing names. It never renames or guesses.
6. **Preview (short)** renders a few frames; **Convert** renders the full clip. Previews cannot be added to the library.
7. **Preview Conditioning** shows an approximate Canny view of the result (advisory; see the warnings it lists).
8. Name and tag it, then **Add to Motion Library**. The library keeps the original file's identity (SHA-256, name) apart from the
   derivative's. **Use as Driving Video** works as for any other clip; nothing is queued by selecting it.

## What is verified before publication

Source and character SHA-256 match the plan; Blender reports Cycles on the CPU; the number and size of rendered frames match; the
encoded MP4 decodes to exactly the planned frame count at 24 FPS with no audio. The result folder (video + `provenance.json`) is
published with one rename. Work folders are removed only when they carry StableNew's ownership marker.

## When something is refused

| Message | Meaning / what to do |
|---|---|
| Choose an existing .fbx or .bvh | Wrong type. ASF/AMC are unsupported. |
| Animation curves without a skeleton / mesh | Missing dependency; nothing to render. Use a file with a rig. |
| Bone names ... missing | The reference character does not share the animation's rig; choose another or render the skeleton. |
| The segment is longer than the animation | Pick a shorter length or earlier start. |
| Render was not confirmed CPU-only | Nothing is published. Report it; do not retry on a GPU build. |
| Archive refused | Unsafe or oversized zip (traversal, links, encrypted, ratio, limits). Extract it yourself if you trust it. |

## Known limitation

The Blender script (`src/video/motion_conversion/blender_scripts/motion_render.bpy`) was developed against Blender's documented
Python API and tested through a fake Blender that obeys the same command-line contract; it has **not** been run against a real
Blender or a real FBX in this change. Run one quick preview on a known Mixamo FBX first and inspect the frames before relying on
it.
