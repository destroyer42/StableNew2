# Runbook: converting mocap files to driving videos (PR-VID-MOTION-354)

Operator procedure for **Convert Motion** in the Video Workflow tab's Motion Library. Nothing here queues a job, starts Comfy,
loads a model or uses the GPU. StableNew never downloads or installs Blender.

## Before you start

1. Install Blender 4.2 or newer yourself (any location; 4.5 LTS was used to verify this procedure). StableNew only runs a `blender.exe` you choose.
2. Choose a Motion Library folder (Motion Library panel). Converted clips are kept beside it in `conversions/`.
3. Optional read-only survey of a mocap download folder (writes only the JSON you name, outside that folder):

```bash
python -m tools.motion_asset_inventory --root "<your motion asset folder>" --out "<somewhere outside it>/inventory.json"
```

It reports counts by type and source family, duplicates, conversion-ready, missing-dependency (animation without skeleton or
mesh) and unsupported items, and archives awaiting an explicit extraction. It never opens an FBX in Blender.

## Converting one clip

1. Motion Library -> **Convert Motion...**. **Find Blender** looks in the standard install locations and verifies what it finds with `--version`; **Choose Blender...** verifies the file you pick. Nothing else on the machine is run. A previously chosen Blender is re-verified the same way when the dialog opens.
2. **Choose animation file...** (.fbx or .bvh). The header scan says what it is and whether it can be converted.
3. **Inspect** (one bounded Blender child) reads the animation's rate, range and bones.
4. Pick profile, camera, camera mode, root motion, start and length. The length list is the selected workflow's own legal lengths
   (Fun Control: 17-49, step 4, offset 1). The plan summary shows the exact frames used; a segment longer than the animation is
   refused (nothing is trimmed, padded or slowed).
5. An animation-only skeleton FBX renders as a skeleton unless you also pick **Use reference character...**; StableNew then needs
   every needed bone name to match exactly and otherwise refuses with the missing names. It never renames or guesses.
6. **Preview (short)** renders a few frames; **Convert** renders the full clip. Previews cannot be added to the library.
7. **Preview Conditioning** shows an approximate Canny view of the result (advisory; see the warnings it lists). The same view is available for any usable clip in the Motion Library through **Preview Conditioning...** beside the library controls.
8. Name and tag it, then **Add to Motion Library**. The library keeps the original file's identity (SHA-256, name) apart from the
   derivative's. **Use as Driving Video** works as for any other clip; nothing is queued by selecting it.

## What is verified before publication

Source and character SHA-256 match the plan; Blender reports Cycles on the CPU; the number and size of rendered frames match;
every frame shows a visible subject (a blank render is refused); the frames are not all identical (an animation that was not
applied is refused); the encoded MP4 decodes to exactly the planned frame count at 24 FPS with no audio. The result folder (video + `provenance.json`) is
published with one rename. Work folders are removed only when they carry StableNew's ownership marker.

## When something is refused

| Message | Meaning / what to do |
|---|---|
| Choose an existing .fbx or .bvh | Wrong type. ASF/AMC are unsupported. |
| Animation curves without a skeleton / mesh | Missing dependency; nothing to render. Use a file with a rig. |
| Bone names ... missing | The reference character does not share the animation's rig; choose another or render the skeleton. |
| The animation's rest pose differs from the character's | The bone names match but the rigs are posed differently (for example a T-pose against an A-pose), so the rotations would distort the character. Retargeting is refused; render the skeleton instead. |
| ... shows no visible subject / Every rendered frame is identical | The render came out blank or static. Nothing is published; report the file. |
| The segment is longer than the animation | Pick a shorter length or earlier start. |
| Render was not confirmed CPU-only | Nothing is published. Report it; do not retry on a GPU build. |
| Archive refused | Unsafe or oversized zip (traversal, links, encrypted, ratio, limits). Extract it yourself if you trust it. |

## Known limitations

The script was exercised against Blender 4.5.9 on real Mixamo and Rokoko character FBX, Xsens skeleton-only FBX and BVH files
(front/side/three-quarter, static and tracking cameras, portrait and landscape, in-place root); the frames were inspected by
eye. Two things remain unproven on real data: putting an animation onto a *separate* reference character (only the rest-pose
refusal was exercised, because no compatible skeleton-only/character pair exists in the local library) and BVH from a real
capture system (the BVH files used were written by hand). Inspect a quick preview before relying on a new kind of file.
