# Motion conditioning and engine evaluation (PR-VID-MOTION-430)

How to choose a driving representation, see what an engine actually does with your clip, prepare comparable cases and read the
evidence. It builds on Harvest Motion, Convert Motion, Align Motion and the video eval kit (`docs/runbooks/motion_harvesting.md`,
`motion_conversion.md`, `motion_alignment.md`, `video_eval_kit.md` sections 9 and 10). Nothing here queues a job, starts a
runtime or qualifies anything. A physical run needs the owner's separate authorization of its exact plan.

## 1. Three things that are not the same

| Thing | Meaning | Where you see it |
|---|---|---|
| **Movement** | The animation or footage whose motion you want | Motion Library asset; a converted clip's *Related variants* |
| **Driving representation** | What the pixels of the clip depict: recorded or generated RGB footage, a rendered character, a rendered silhouette or a rendered skeleton | Library detail pane; the preview heading |
| **Conditioning mechanism** | What the workflow does to those pixels before the model sees them | Video Workflow readiness details, *How this engine uses the driving clip* |

Every representation travels as an ordinary RGB video. A silhouette render is a silhouette-derived RGB clip; it is not an
edge map. A skeleton render is not an OpenPose map. A precomputed edge video and an explicit pose map are **refused** for both
registered engines (Fun Control would run Canny a second time on the edge video; no registered graph consumes a pose map). A direct
edge or pose input would need its own versioned workflow.

## 2. The two registered engines

| | Wan-Animate-2 Driving Video 1.2.0 | Wan2.2 Fun Control 5B Canny 1.1.0 (trial) |
|---|---|---|
| Conditioning | RGB frames, resized (area, centre crop) and VAE-encoded directly; the first frame is also CLIP-vision context | Canny edges of the frames at the prepared clip's own size, **then** centre-crop, bilinear resize and VAE-encode |
| Lengths | 17-81 frames at 24 FPS | 17-49 frames at 24 FPS |
| Motion prompt | Separate Motion Prompt (`pose_prompt`) and strengths | None: movement comes from the clip and the main prompt |
| Align Motion | Available | Not available |
| Status | Experimental | Experimental trial, **not qualified**; 1.0.0 stays blocked |

The facts in this table and in the details panel come from each registered graph and from the pinned ComfyUI v0.38.0 source, not
from names. The trial's 10,000 MiB VRAM floor and 16 GB RAM advisory are provisional (borrowed from TI2V-5B); selecting it never
makes it a default or a recommendation. Choosing an engine does not change your Motion Library selection.

## 3. Choosing a representation

1. Start from the movement, not the file. In the Motion Library, a converted clip lists its **related variants** (same animation
   file, window, camera, root-motion policy and geometry, identified by a movement key). A clip converted before this feature has no
   key and is never grouped by name.
2. Create a missing variant yourself with **Convert Motion** (same plan, another profile). Nothing is converted implicitly.
3. Expect differences, and write them down: a skeleton has no body shape, clothing or face, so a head turn may be poorly
   represented; a silhouette hides facial orientation; a character render carries its own texture. These are applicability limits,
   not engine failures.
4. Recorded footage and a skeleton render of unrelated movements are **exploratory** evidence only. A controlled
   representation comparison needs drivers verified as renders of one movement.

## 4. Inspecting the effective driving input

Motion Library -> **Preview Conditioning...** on the selected clip (Follow a driving clip). The window shows:

- the **effective** input: the verified prepared or aligned derivative when one exists for the *selected engine and length*, else
  the original. A preparation made for another workflow, version, length or clip is not used and the window says why;
- first, middle and last frames and their Canny edges after the graph's own crop and resize;
- the fidelity of each picture: the file bytes are exact, the pictures are decoded at a reduced analysis size, and the edges are
  **approximate**. The edge detector matches the pinned kornia Canny on four recorded synthetic vectors, but parity on real clips
  is not verified, so the label stays *approximate*;
- advisories, each tagged *measured*, *read from the pinned source*, *heuristic* or *historical*: dense or faint edges, clipping,
  uniform padding bands, internal texture, several subjects, near-static or cut-like change, tonal contrast, upload size, the
  memory a very large clip costs before Canny, driver appearance, viewpoint mismatch, head turns on skeletons and silhouettes, and
  a window shorter or longer than the generated length (Animate-2 pads a short window by holding its last frame).

None of these is a quality score or a statement that the motion will transfer. Limb-by-limb definition is not measured; only a faint
or sparse outline is flagged. Changing the engine or length makes an existing preparation out of date and blocks submission with the
reason until you prepare again.

## 5. Preparing comparable cases

- Hold constant: source image, movement, representation, window, rate, alignment, requested action, main prompt, length, seed.
- Compare engines only inside their **shared envelope** (17-49 frames at 24 FPS). Never set an 81-frame Animate-2 clip against a
  49-frame Fun Control clip: they do not cover the same action. Do not slow, truncate or repeat the end of an action to fit.
- A same seed value does not mean equivalent noise or conditioning across architectures. A comparison across engines is a
  **multi-engine comparison**: the mechanism, controls, prepared derivative and noise semantics change together and the report says
  so. The case's motion prompt is sent only to an engine that declares that control; for Fun Control it is not sent and the report
  discloses it.
- For a representation comparison bind each driver from the Motion Library (the suite then records its representation and movement
  key from the clip's own conversion record) and keep the engine, seed, length and alignment fixed. A different alignment is
  recorded as an additional intervention, not hidden.

The staged, bounded templates are in `docs/runbooks/examples/video_eval_conditioning_stage{1..4}_*.suite.json` (2 + 12 + 12 + 4 jobs
at most, 30 before reuse). They contain no media and are unexecuted.

## 6. Reading the evidence

The report adds the groups *Engine and conditioning mechanism*, *Driving representation*, *Verified movement group*, *Alignment
intervention* and *Generation length*, each with planned, completed, failed, duplicate, comparable and rated counts and the
existing rubric (requested action, subject attachment, motion fidelity, identity break), plus *Driving-representation groups*
that say whether a group is a controlled comparison. A failed generation stays in its denominators; an unrated clip is not a
failed transfer; critical identity breaks are shown apart from visual quality.

Not in a run manifest: generation time, cold versus warm state and VRAM/RAM headroom. Read them from job History or from qualification
telemetry, and never compare timings across different lengths or hardware states. A faster engine is not thereby a better motion-transfer
engine. The report may point at promising configurations; it never creates a recipe, changes a default or promotes a workflow.

## 7. Trial status and requesting physical evaluation

Historical evidence (VID-MOTION-354 run 3: 14 of 14 cases technically feasible on one RTX 4070 Ti 12 GB host with 480x832 inputs)
is **feasibility on 1.0.0's graph**. It is not a qualification of 1.1.0, of its provisional resource policy or of the application path.
Prepare Motion Source scales a Fun Control input longer than 832 px to an 832-pixel long edge; earlier 4K drivers failed before that existed.

To ask for a physical run, send the owner the exact artifact:

1. **Pilot or stage:** the suite file digest, workflow versions (Animate-2 1.2.0, Fun Control 1.1.0), input and derivative hashes, job count,
   time and resource budget, stop conditions and the delegate who launches it.
2. **Fun Control qualification:** `python -m tools.qualification.fun354 propose --workflow-version 1.1.0 --inputs-manifest M --reference R --out <outside the
   repository>`, then `check`, then the owner's authorization of that plan digest. The trial plan pins the graph, model files, runtime commit, launch flags, the
   resource-policy identity and the prepared inputs, keeps every stop condition of the 1.0.0 plan, and records GPU temperature (decimals preserved) and the
   minimum VRAM headroom. It does not capture separate cold-start timing or allocator state.

A passing offline check, a template or a plan is never an authorization and never a ledger entry.

See `docs/Subsystems/Video/PR-VID-MOTION-430_Conditioning_and_Engine_Evaluation.md` for the record and its limits.
