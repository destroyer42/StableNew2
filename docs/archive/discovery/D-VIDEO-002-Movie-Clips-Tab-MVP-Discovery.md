# D-VIDEO-002 - Movie Clips Tab MVP Discovery

**Status:** Discovery
**Version:** v2.6
**Date:** 2026-03-11
**Subsystem:** Post-Execution Media / GUI
**Author:** StableNew Development Team

---

## 1. Executive Summary

This discovery document evaluates how much work it would take to add a user-facing capability that generates movie clips from existing images in StableNew.

The core conclusion is:

1. A **Movie Clips tab MVP** is practical and relatively low risk.
2. A **true pipeline stage for clip generation** is not the right first step for the MVP.
3. The current codebase already contains enough legacy and partial infrastructure to support an MVP built as a **post-processing tab**, not as a new NJR generation stage.

Recommended path:

- Build a new top-level `Movie Clips` tab that works on existing run outputs and selected image sets.
- Reuse the existing FFmpeg wrapper in `src/pipeline/video.py`.
- Keep the MVP outside the canonical generation stage chain.
- Defer AnimateDiff and any true motion-generation stage until a separate architecture-approved phase.

---

## 2. Problem Statement

Users can already generate still images and review or reprocess them, but there is no integrated flow for turning those images into short clips.

There are two different problem classes:

1. **Clip assembly**
   - Input: existing images
   - Output: MP4/GIF/slideshow clip
   - No new diffusion generation required

2. **Motion generation**
   - Input: prompt and/or image
   - Output: multiple coherent animation frames and an encoded video
   - Requires AnimateDiff or a similar extension

These should not be conflated. The first is a post-processing feature. The second is a pipeline architecture extension.

---

## 3. Current State Analysis

### 3.1 Existing Relevant Infrastructure

The repo already contains:

- `src/pipeline/video.py`
  - `VideoCreator` wrapper around `ffmpeg`
  - image-sequence to video support
  - slideshow-like concat support

- `src/utils/config.py`
  - contains a `video` config section with `fps`, `codec`, and `quality`

- `src/utils/preferences.py`
  - contains `video_enabled` preference state

- `src/utils/logger.py`
  - creates a `video/` folder under run logging structure

- `docs/D-VIDEO-001-AnimateDiff-Integration-Discovery.md`
  - prior discovery of AnimateDiff integration options

### 3.2 Architectural Constraints

The canonical v2.6 execution flow remains:

`PromptPack -> Builder -> NJR -> Queue -> Runner -> History -> Learning`

The current stage architecture is explicitly limited to:

- `txt2img`
- `img2img`
- `upscale`
- `adetailer`

Confirmed in:

- `src/pipeline/stage_models.py`
- `src/pipeline/stage_sequencer.py`
- `src/pipeline/run_plan.py`
- `src/pipeline/pipeline_runner.py`

This means a true new pipeline stage for `video` or `animatediff` is not a local change. It requires coordinated modifications across:

- stage definitions
- stage sequencing
- job building
- runner dispatch
- history/output assumptions
- preview/history UI behavior

### 3.3 What Already Works

The easiest already-supported capability is:

- take a directory of images
- sort them
- call `ffmpeg`
- emit an output MP4

That capability already exists in `VideoCreator`.

### 3.4 What Does Not Exist

The following do not currently exist in a production-ready way:

- a top-level `Movie Clips` tab
- a controller service for selecting assets and building clip jobs
- clip manifests/metadata
- queue/history integration for clip-build tasks
- clip previews in the GUI
- any canonical `video` or `animatediff` stage in the stage chain

---

## 4. Architectural Options

### Option A: New Movie Clips Tab (Post-Processing Only)

Design:

- Add a new top-level tab.
- Let users select:
  - an output run folder
  - a set of images
  - fps/codec/quality
  - slideshow timing mode
- Call `VideoCreator`.
- Write clips into a managed clip output folder and manifest.

Pros:

- Aligns with current architecture
- Avoids modifying stage sequencing
- Reuses existing FFmpeg code
- Lower test burden
- Low risk of destabilizing generation

Cons:

- Not a true generation stage
- No automatic motion generation
- Separate from Pipeline tab mental model

Assessment:

- Best MVP choice

### Option B: Add a `video` Stage to Pipeline

Design:

- Extend `StageType`
- Extend `StageSequencer`
- Extend `PipelineRunner`
- Add a video stage card to Pipeline
- Let a run end with `video`

Pros:

- Unified stage-chain experience
- Could support image-sequence-to-video as a first-class artifact

Cons:

- Changes canonical stage model
- Forces clip building into NJR semantics
- Requires decisions about whether video is built from:
  - all output images
  - one batch
  - one variant
  - one selected sequence
- Adds complexity to History and Preview

Assessment:

- Possible, but too invasive for MVP

### Option C: AnimateDiff / Motion Generation Stage

Design:

- Integrate AnimateDiff extension parameters
- Add new stage or generation modifier
- Emit frames plus encoded clip

Pros:

- Highest end-user value for actual animation

Cons:

- High complexity
- Extension dependency
- Much larger investigation still required

Assessment:

- Defer to future phase

---

## 5. Recommended MVP

### Recommendation

Build a **new `Movie Clips` top-level tab** as a post-processing subsystem.

### Why This Is the Right First Move

1. It provides immediate user value.
2. It reuses existing infrastructure instead of forcing stage-model churn.
3. It avoids architecture risk in queue/runner/stage-sequencer internals.
4. It creates a clean place to manage future video-related features later.

### MVP Scope

The MVP should support:

1. Selecting a source set:
   - a run output folder
   - a review selection
   - a manual image list

2. Clip settings:
   - FPS
   - codec
   - quality preset
   - optional per-image duration for slideshow mode
   - output filename

3. Output:
   - write MP4 to a managed clip output folder
   - save clip manifest JSON
   - show clip build result in the tab

### Explicit Non-Goals for MVP

1. AnimateDiff
2. frame interpolation engines
3. audio tracks
4. queue-backed distributed clip jobs
5. clip-aware Learning records
6. new pipeline stage types

---

## 6. Estimated Work

### Movie Clips Tab MVP

Estimated effort:

- Small to medium
- roughly 3 PRs
- approximately 2-5 days depending on UI polish and test depth

Primary work areas:

- new tab UI
- controller/service wiring
- manifests and persistence
- focused tests

### Full AnimateDiff Pipeline

Estimated effort:

- Large
- roughly 5-8 PRs after deeper research
- approximately 2-4 weeks for a stable, architecture-aligned implementation

Primary work areas:

- stage model changes
- runner changes
- WebUI extension contract validation
- frame and clip artifact semantics
- history/preview/learning implications

---

## 7. Risks

### Low Risk

- Reusing `VideoCreator`
- adding a new standalone tab
- writing clip manifests next to outputs

### Medium Risk

- Choosing correct image ordering semantics
- handling mixed image sizes or formats
- keeping the UI intuitive for run-folder versus manual-selection workflows

### High Risk

- treating clip generation as a pipeline stage without first defining canonical stage semantics
- mixing simple clip assembly and AnimateDiff into one feature too early

---

## 8. Conclusions

### Final Conclusion

The right next step is:

1. implement a **Movie Clips tab MVP**
2. keep it **post-processing only**
3. store structured clip manifests
4. defer AnimateDiff to a separate, deeper investigation and PR series

### Decision

**Approved recommendation for planning purposes:** pursue the Movie Clips tab MVP first, and do not add a new pipeline stage in the MVP.

