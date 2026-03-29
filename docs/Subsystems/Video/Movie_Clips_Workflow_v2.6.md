# Movie Clips Workflow v2.6

Status: Active subsystem reference
Updated: 2026-03-29

## 1. Purpose

This document describes the current Movie Clips surface in StableNew and its
place in the post-unification architecture.

Movie Clips is a StableNew-owned post-processing and export surface for turning
existing still-image or video-derived frame sources into exportable clip
artifacts.

## 2. Architectural Boundary

Movie Clips is not a fresh-generation execution path and not a queue
submission replacement.

Canonical relationship:

Intent -> NJR -> Queue -> Runner -> Canonical artifacts/history
                                            |
                                            v
                                      Movie Clips
                                 (post-artifact assembly/export)

Movie Clips may consume:

- run folders
- manually selected images
- history-handoff image sources
- canonical workflow-video, sequence, or assembled-video source bundles

Movie Clips may not:

- create alternate job models
- replace queue submission
- bypass canonical artifact/history ownership

## 3. Current User Workflows

Current supported source modes:

- load images from a run folder
- add images manually

Current core controls:

- FPS
- codec
- quality
- sequence vs slideshow mode

Current output behavior:

- writes clip artifacts under `output/movie_clips/`
- writes a stable manifest alongside each built clip
- surfaces success or failure without crashing the app

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
| View contract | `src/gui/view_contracts/movie_clips_contract.py` | UI-facing labels, defaults, formatting |
| Tab frame | `src/gui/views/movie_clips_tab_frame_v2.py` | source selection, image list, clip settings, status |
| Data models | `src/video/movie_clip_models.py` | typed request/result/manifest objects |
| Service | `src/video/movie_clip_service.py` | ordering, validation, manifest writing, export orchestration |
| Low-level export | `src/pipeline/video.py`, `src/video/video_export.py` | FFmpeg-facing helpers |

## 5. Current Product Direction

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

Those were delivered in:

- `docs/CompletedPR/PR-VIDEO-215-Workflow-Video-Output-Routing-and-History-Convergence.md`
- `docs/CompletedPR/PR-VIDEO-217-Stitching-Interpolation-and-Clip-Assembly-Unification.md`
- `docs/CompletedPR/PR-GUI-220-UX-First-Workspace-Polish-on-Tkinter.md`
- `docs/CompletedPR/PR-CORE-001-Finalize-Native-SVD-Integration.md`

## 6. Testing Surface

Relevant tests include:

- `tests/video/test_movie_clip_service.py`
- `tests/gui_v2/test_movie_clips_tab_v2.py`
- `tests/journeys/test_movie_clips_mvp.py`

## 7. Non-Goals

Movie Clips is still not:

- a second orchestration system
- a replacement for workflow-video generation
- a timeline editor
- a backend-owned export path
