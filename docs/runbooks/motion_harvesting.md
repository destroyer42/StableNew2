# Runbook: harvesting motion from an existing video (PR-VID-MOTION-400)

Operator procedure for **Harvest Motion**: cutting the part of a video that contains the movement you want into a reusable
Motion Library clip. Nothing here queues a job, starts Comfy, loads a model or uses the GPU, and the video you start from is
never changed. Design record and limits: `docs/Subsystems/Video/MOTION_LIBRARY.md` section 7. Direction:
`docs/Subsystems/Video/CONTROLLED_MOTION_ROADMAP.md`.

## Before you start

1. Choose a Motion Library folder once (Video Workflow tab, Motion Library, *Choose library folder...*). Harvested clips are kept
   there. Without a folder you can still open a video and choose a window; saving tells you to choose a folder first and keeps
   what you selected.
2. FFmpeg must be installed (the same one Prepare Motion Source uses). Everything is CPU-only.
3. Have a good source in mind. Harvesting can only keep frames that already exist: a clip that never performed the action
   cannot be repaired by cutting it.

## Opening the workspace

Open **Harvest Motion** from the video you want to cut. Each entry hands over exactly one file and never starts generation.

| From | How |
|---|---|
| Video Workflow, Recent outputs | Select the finished clip, **Harvest Motion...**. |
| Job History | Select a completed job that recorded a video file, **Harvest Motion** (button or right-click menu). |
| Movie Clips | Select exactly one video in the clip list, **Harvest Motion...**. |
| Motion Library | Select a clip, **Harvest Motion...**; to cut a video that is not in the library yet, import it first. |
| Storyboard | *Export cut*, **Harvest Motion...** for an encoded take. |

The window shows where the video came from:

- **verified** - History names this exact file and its recorded SHA-256 matches;
- **recorded** - History names this file but kept no SHA-256, so the bytes are not independently verified;
- **path only** - only the location is known (a Movie Clips or Storyboard file, an imported file, a file that changed after the
  job, or a job that did not complete). Nothing about the originating job is claimed.

A video hidden by the current content filter is not opened. Switch the content visibility setting, then open it again.

## Choosing the action window

1. Scrub with the slider or step with `-10 / -1 / +1 / +10`. The **Frame** panel shows the exact frame and its time. The player
   above it is the shared preview; it may not show the whole video, but the frame panel and every frame number are exact.
2. At the first frame you want, **Set Start to Current**. At the last frame you want, **Set End after Current**. The window
   is frames `start` to `end - 1`: the end number is the first frame left out, so the frame you stood on is included.
3. Or type the numbers. Switch between **Frames** and **Seconds** at any time; the same window is shown in the other unit
   (seconds are placed on the nearest frame with exact arithmetic). **Reset to full video** starts over.
4. Check the three frames under *Selected window* against the three under *Original*. The duration and frame count are listed.
5. Choose the frame rate of the saved clip:
   - **Keep the source frame rate** (default, recommended) keeps every selected frame as it is;
   - **Convert to 24 fps** resamples by time and tells you how many source frames were omitted or repeated. Motion speed does
     not change either way.
6. The *workflow timing* note (if a driving-video workflow is selected) shows what Prepare Motion Source would later do with this
   window for that workflow and length. It is only information; the clip you save is not shaped to any workflow.

Refused with a reason: a variable-frame-rate video (re-encode it at a constant rate first), a video with no frame rate (use frame
numbers), an empty or out-of-range window, a window past the bounds in `MOTION_LIBRARY.md` 7.8.

## Describing and saving

Give it a **name** and, if you like, the details: motion label, direction, subject, framing, viewpoint, camera, intensity, start
and end pose, loop, review status, visual quality, whether the requested motion was achieved, whether it is good for motion
driving, known defects, reuse conditions, tags, source, usage terms and notes. **Only what you fill in is saved**; an empty box
never overwrites what the original library clip already says (source, usage terms).

Visual quality, "motion achieved" and "good for motion driving" are three separate opinions of yours. None is evidence that the
motion will transfer to another subject.

Press **Save as Motion Asset**. You can save several windows from the same video (for example the wave, then the turn); each is
listed under the buttons. **Cancel** stops a running harvest and adds nothing. Closing the window cancels it too.

Outcomes you may see:

- *Added* - a new clip exists in the library.
- *Reused* - you already harvested exactly this window; it was verified and nothing was re-encoded.
- *Duplicate* - the same bytes already exist as another clip. The existing clip is kept; the message lists any details you
  entered that were not applied to it (change them in *Edit details*).
- *Refused* or *failed* - the message says why and what to do; nothing partial is left behind.

## Using the clip

Find it in the Motion Library (filter **Harvested clips only**, or search for the label, defects or the original's name). The detail
pane shows the original, the exact frames, the cadence and the lineage. If the original has been moved or deleted the pane says so;
the clip itself is unaffected and still verifies.

**Use as Driving Video** fills the driving-video field exactly as for any other clip and nothing else. Prepare Motion Source,
Preview and Queue are unchanged and still yours to run. Harvesting never selects a workflow, turns on an experimental opt-in or
removes a block. A changed or swapped clip fails closed at submission.

## If something looks wrong

| Symptom | Meaning / action |
|---|---|
| "variable frame rate" | The video's frame timing is not constant, so a window cannot be cut exactly. Re-encode it at a constant rate in your own tool and open that file. |
| "No Motion Library folder is configured" | Choose a library folder; the window you selected is kept. |
| "past the end of the video" | The window is outside the frames the container reports; correct the end or reset. |
| Window too long | The lossless clip would be larger than the 256 MiB limit, or the frame count exceeds a bound; choose a shorter action. |
| Previews are blank | The video is hidden by the content filter, or the frames could not be decoded (the reason is listed under the source). |
| Original NOT found | The original moved or was deleted. The clip is unaffected. |

Originals, History and generated outputs are never modified. A clip can be removed from use by simply not selecting it; removing
catalog entries is not supported yet (`MOTION_LIBRARY.md` section 2).
