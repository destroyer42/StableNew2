PR-CORE-007 - Video Composition and Stitching

Status: Specification
Priority: MEDIUM
Effort: SMALL
Phase: Post-Unification Core Refinement
Date: 2026-03-29

Context & Motivation

Currently, StableNew can generate isolated clips (e.g. via SVD or AnimateDiff), but there is no built‑in mechanism to combine multiple clips into a continuous sequence with transitions. The existing video_export.py writes frames to a single MP4 but lacks concatenation or fade logic. To produce longer scenes or entire chapters, we need a video composition tool that stitches clips end‑to‑end, optionally adding crossfades or other transitions. The research proposals call for a simple ffmpeg wrapper for this purpose. This PR introduces such a tool and integrates it into the workflow compiler.

Goals & Non‑Goals
Goal: Provide a function (and CLI) to concatenate multiple video files into a single MP4, with optional transitions (hard cut, crossfade).
Goal: Integrate this tool into the pipeline runner so that after all PromptPacks for a chapter are complete, the videos are automatically stitched in order.
Goal: Expose basic stitching options (transition type and duration) in the CLI or GUI.
Non‑Goal: Do not implement complex video editing features (e.g. audio mixing, color grading). The focus is on simple concatenation with optional fades.
Guardrails
Use imageio-ffmpeg or direct ffmpeg command invocation; do not implement video encoding manually.
Ensure that input clips have the same resolution and framerate; if they differ, either resample them or raise a descriptive error.
Stitching should be an optional final step; users should be able to download individual clips separately if desired.
Allowed Files
Files to Create
src/video/video_stitcher.py – implements stitch_videos(video_paths: list[str], output_path: str, transition: str = "cut", transition_duration: float = 1.0). Uses ffmpeg to perform the concatenation and crossfade when requested.
tests/video/test_video_stitcher.py – tests for correct concatenation order and transition insertion using short dummy videos.
Files to Modify
src/pipeline/pipeline_runner.py – after executing a list of PromptPacks for a chapter, call video_stitcher.stitch_videos on their outputs if the user selects “compose sequence”.
src/gui/views/sequence_export_frame.py (new or existing) – UI for selecting which clips to stitch and setting transition options.
Possibly src/controller/app_controller.py to orchestrate the stitching step.
Forbidden Files
Do not modify core video generation logic or Comfy pipelines. Stitching is a postprocessing step.
Implementation Plan
Implement video_stitcher: Use imageio_ffmpeg or call ffmpeg directly via subprocess. For hard cuts, create a simple concat file (ffmpeg concat demuxer). For crossfades, construct an ffmpeg filter chain such as xfade=transition=fade:duration=1.0:offset=<time>.
Handle mismatched properties: Before stitching, inspect each input file’s resolution and framerate using ffprobe. If they differ, resample them to match the first clip using ffmpeg scaling and frame rate filters.
Update pipeline runner: Modify the workflow compiler or pipeline runner to collect the list of generated video files per chapter. When the user has indicated they want a composed sequence (e.g. via CLI flag or GUI option), call the stitcher with the list of files in order.
Add UI controls: In the GUI, provide a simple form where the user can select which clips to stitch (checkbox list) and choose the transition type (cut or fade) and duration. Pass these options to the pipeline runner.
Tests: Write tests generating a couple of dummy videos (e.g. colored bars) with imageio, then stitch them and verify the duration and number of frames. Use a temporary directory to avoid polluting the repo.
Manual verification: Compose a couple of real generated clips with a crossfade and verify that the resulting output looks correct.
Testing Plan
Unit tests: Test that video_stitcher.stitch_videos can concatenate two simple videos and that the resulting file plays with the combined duration. Test crossfade transitions by checking that the first and last frames of the fade region blend the inputs.
Integration tests: Test that the pipeline runner collects output clips and calls the stitcher when composition is enabled. Use mocks for ffmpeg invocation to avoid long runtime.
Manual tests: Compose a sequence of story clips and visually inspect the final video. Test both cut and crossfade.
Verification Criteria
The video_stitcher successfully concatenates multiple videos into one file, with optional crossfade transitions at the boundaries.
The pipeline runner or CLI can invoke stitching after generating all clips for a chapter, producing a single output video file.
The GUI allows the user to select clips and transition options, and the resulting video matches those choices.
All new tests pass.
Risk Assessment
Low Risk: ffmpeg concatenation is well‑understood; errors are typically due to mismatched input properties. Mitigate by resampling or clearly erroring when unsupported.
Medium Risk: Building filter chains for crossfades can be error‑prone; mitigate by testing with different durations and verifying with ffprobe.
Tech Debt Analysis

This PR removes the manual burden of stitching clips externally and introduces a simple yet extensible composition tool. Future enhancements could support audio and more complex transitions.

Documentation Updates

Add a section describing the new “Compose Sequence” feature, with instructions for selecting clips and transitions. Update the CLI usage documentation to include a --stitch option.

Dependencies

Requires ffmpeg (already used by existing export code) and imageio_ffmpeg (already a dependency). No new external dependencies.

Approval & Execution

Planner: agent
Executor: TBD
Reviewer: @video-team
Approval Status: Pending

Next Steps

Integrate composition with the interpolation and style LoRA features (PR‑CORE‑006 and PR‑CORE‑008) to ensure stitched videos maintain style and smooth motion across cuts.

