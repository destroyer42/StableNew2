# Movie Clips Workflow v2.6

Status: Retained subsystem reference; post-MVP except native SVD XT handoff
Updated: 2026-10-20

## 1. Purpose

This document describes the current Movie Clips surface in StableNew and its
place in the post-unification architecture.

Movie Clips is a StableNew-owned post-processing and export surface for turning
existing still-image or video-derived frame sources into exportable clip
artifacts.

## 2. Architectural Boundary

Movie Clips is not a generation path: it assembles outputs that already exist.
Since PR-VID-ASM-332 (owner decision D6) it runs on the canonical path as a
queued CPU workload:

Intent (Movie Clips tab) -> Compiler (freeze + hash) -> NJR (`movie_assembly`)
-> JobService -> Queue/Repository -> PipelineRunner.run_njr
-> MovieAssemblyHandler -> movie + manifest -> History

Movie Clips may consume:

- run folders (images and videos)
- manually selected images and videos
- history-handoff image sources
- canonical workflow-video, sequence, or assembled-video source bundles

Movie Clips may not:

- create alternate job models, queues or runners
- run FFmpeg outside the queued job
- bypass canonical artifact/history ownership

## 3. Current User Workflows

Current supported source modes:

- load a run folder (images and videos, in file-name order as a starting point)
- add images and videos manually (appended in the order chosen)

The list order is the movie order. Move Up and Move Down reorder it; nothing
re-sorts it by name. A file may appear more than once.

Current core controls:

- FPS, codec and quality (encode profile or x264 speed preset; CRF 16, BT.709)
- mode: sequence (every image is one frame; images only) or slideshow (stills
  hold for their duration, videos play in full); adding a video switches to
  slideshow
- Still (s) with Set for Selected: the default and per-still hold time
- resolution: match the first clip, or a fixed size; every item is fitted
  inside the frame with black bars, never stretched
- transition: crossfade seconds between slideshow items (0 = hard cuts; at most
  half of the shortest item)
- music: an optional audio track, cut or padded to the movie and faded out
- clip name

Current output behavior:

- Queue Assembly checks every file (hash, size, duration) and queues one job;
  the tab reports the job id or the reason it was refused
- the job shows in the Queue, can be cancelled there, and the movie appears in
  History (open, reveal, send onward)
- writes the movie under `output/movie_clips/<run>/` and a manifest under its
  `manifests/` folder; a file changed or moved after queueing makes the job
  fail with a clear message instead of assembling something else

### 3.1 Native SVD Quickstart

Use `SVD Img2Vid` when you already have one strong still image and want a
short clip through the native SVD backend instead of a WebUI or workflow-video
path.

Quickstart:

- open the `SVD Img2Vid` tab
- choose a source image directly or use `Use Latest Output` from recent history
- start with `Recommended Quality / Enhanced`
- keep the `SVD` output route unless you are intentionally validating under
      `Testing`
- queue the job and review the resulting preview, manifest, and clip from
      history or the route-specific output folder

### 3.2 When To Use Each Video Surface

- use `SVD Img2Vid` to animate one still image into a short clip through the
      native SVD backend
- use `Movie Clips` to assemble or export existing still-image and video
      artifacts after they are already generated
- use `Video Workflow` when you need backend-governed multi-anchor or workflow
      execution rather than a single-image animation path

## 4. Current Code Ownership

| Layer | Location | Responsibility |
|------|----------|----------------|
| View contract | `src/gui/view_contracts/movie_clips_contract.py` | UI-facing labels, defaults, formatting, reorder helper |
| Tab frame | `src/gui/views/movie_clips_tab_frame_v2.py` | source selection, ordered clip list, settings, status |
| Admission | `src/controller/movie_clips_submission_service.py` | intent from the tab, freeze, one `JobService.submit_njrs` |
| Contract | `src/video/movie_assembly_models.py` | frozen spec, validation, frame plan |
| Compiler | `src/video/movie_assembly_compiler.py` | read, hash and measure inputs; build the NJR |
| Handler | `src/pipeline/run_stage_handlers.py` (`MovieAssemblyHandler`) | run the frozen spec inside `run_njr`; record the artifact |
| Engine | `src/video/movie_assembly_engine.py` | re-verify inputs, FFmpeg command, bounded cancellable run, manifest |
| Encoder | `src/pipeline/video.py` | shared `VideoEncodeSettings`, encode filter and arguments, `run_ffmpeg` |

Full detail: `docs/Subsystems/Video/VIDEO_PIPELINE.md` section 7.

## 5. Current Product Direction

For the active MVP, only the `SVD Img2Vid` native SVD XT handoff is a release
path. Movie Clips assembly/export, workflow-video handoff, multi-anchor flows,
stitching, and other video-workspace convergence remain post-MVP even where code
or completed PR records exist. This document does not expand the active roadmap.

Movie Clips is no longer just an isolated MVP. It is now one part of the
broader video workspace alongside:

- History
- SVD
- Video Workflow

The recent convergence work delivered:

- richer workflow-video output routing into Movie Clips
- sequence-aware and assembled-video input handling
- tighter UX convergence with the rest of the video workspace
- explicit repo-truth closure for the shipped `SVD Img2Vid` path, including
      dedicated controller-to-runner integration coverage and canonical docs
      alignment

The implementation history for those changes remains available in Git history;
completed PR narratives are not active runtime documentation.

## 6. Testing Surface

Relevant tests include:

- `tests/video/test_movie_assembly_332_contract.py` (spec, frame plan, command, admission)
- `tests/video/test_movie_assembly_332_engine.py` (real FFmpeg on KB-sized clips)
- `tests/pipeline/test_movie_assembly_332_canonical.py` (classification, replay, cancel, queue and History)
- `tests/controller/test_movie_clips_submission_332.py`
- `tests/gui_v2/test_movie_clips_tab_v2.py`

## 7. Non-Goals

Movie Clips is still not:

- a second orchestration system
- a replacement for workflow-video generation
- a timeline editor (no per-video trims, no clip audio passthrough)
- a backend-owned export path
