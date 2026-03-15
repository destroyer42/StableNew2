# D-VIDEO-005 - SVD Native Img2Vid Tab Discovery

**Status:** Discovery  
**Version:** v2.6  
**Date:** 2026-03-14  
**Subsystem:** Video / Native Python backend / GUI tab  
**Author:** Codex

---

## 1. Purpose

This discovery defines the architecture-aligned shape for adding Stable Video
Diffusion (SVD) to StableNew as a native Python feature.

It answers one narrower planning question:

1. What is the smallest clean SVD implementation that fits StableNew without
   coupling it to A1111/WebUI?

This document is discovery only. It does not authorize implementation by
itself. Its immediate purpose is to support a new OpenSpec PR for SVD Phase 1.

---

## 2. Executive Summary

### Conclusion

StableNew should implement SVD as a **separate native Python image-to-video
feature** with its own **dedicated GUI tab**, while still using the existing
queue/runner/history lifecycle instead of inventing a second unmanaged runtime.

### Phase 1 should include

1. a native SVD backend service under `src/video/`
2. explicit preprocess rules for portrait and non-landscape images
3. MP4 export plus optional frame save
4. a new `SVD Img2Vid` tab
5. a selected-image workflow that produces a history/output artifact

### Phase 1 should not include

1. any A1111/WebUI dependency
2. PromptPack authoring integration
3. Pipeline tab stage-card integration
4. interpolation, stabilization, or frame upscaling
5. long-form cinematic sequencing

---

## 3. Architecture Decision

### 3.1 Separation from AnimateDiff is correct

AnimateDiff and SVD solve different product problems:

1. AnimateDiff is a prompt-and-motion stage integrated into the main image
   pipeline through WebUI.
2. SVD is a native Python image-to-video backend that starts from an already
   chosen still image.

Because of that difference, SVD should not be forced into the same integration
shape as AnimateDiff.

### 3.2 Separation from A1111 is correct

SVD should not be routed through:

1. WebUI process management
2. A1111 payload builders
3. `alwayson_scripts`
4. A1111 checkpoint or extension discovery

Its dependency surface is native Python plus Diffusers model loading.

### 3.3 Separate tab is correct

The cleanest first user experience is a dedicated tab named `SVD Img2Vid`.

That tab should own:

1. source-image selection
2. SVD parameter editing
3. submit/generate action
4. result preview/open-output actions

It should not be embedded into Movie Clips or PromptPack stage cards in Phase 1.

### 3.4 Queue/runner reuse is still preferred

Even though SVD is a separate tab and backend, StableNew should still reuse:

1. queue lifecycle
2. background execution model
3. history recording
4. output metadata conventions

This avoids creating a second job runtime with separate cancellation, progress,
and output semantics.

---

## 4. External Contract Findings

### 4.1 SVD is image-to-video, not text-to-video

The Stable Video Diffusion family is for image-conditioned short video
generation. It should be modeled in StableNew as:

1. selected PNG in
2. short frame sequence out
3. MP4/GIF export out

This makes it a natural fit for final-image animation, not for prompt-first
generation.

### 4.2 Recommended dimensions matter

The current Diffusers guidance and model card center on `576x1024` landscape
input for `stable-video-diffusion-img2vid-xt`.

Practical implication:

1. portrait images must be processed intentionally
2. StableNew must expose resize policy explicitly
3. silent stretching is not acceptable

### 4.3 Memory pressure is real

Diffusers guidance explicitly recommends memory-reduction options such as:

1. model CPU offload
2. forward chunking
3. smaller decode chunk sizes

These must be part of StableNew's config surface from Phase 1, even if advanced
by default.

### 4.4 Initial control surface should stay small

The first meaningful controls are:

1. frames
2. fps
3. motion bucket
4. noise augmentation
5. resize mode
6. output format
7. seed

That is enough for a useful first release without overloading the tab.

### 4.5 Additional useful concepts from alternate planning

A comparison against the alternate SVD plan surfaced several ideas that are
worth preserving in the repo plan:

1. split config into preprocess / inference / output subdomains, even if
   persisted under one `svd` root
2. keep a typed supported-model registry rather than treating `model_id` as a
   loose string everywhere
3. write a run manifest per generated clip rather than relying only on general
   history plumbing
4. include a dedicated orchestration layer so preprocessing, inference, export,
   and manifest writeback do not collapse into one oversized service

Those ideas improve maintainability and future extensibility. The repo plan
should absorb them in a way that still matches current StableNew file layout and
execution semantics.

---

## 5. Current Repo Fit

### 5.1 What already exists

The current repo already has:

1. a `src/video/` package for post-generation video work
2. FFmpeg-backed export code in `src/pipeline/video.py`
3. history and output artifact patterns
4. GUI tab patterns in `src/gui/views/`
5. queue/runner execution that can process background work and surface results

### 5.2 What does not yet exist

The repo does not yet have:

1. a native Diffusers-backed video generation service
2. an SVD-specific config model
3. portrait-aware SVD preprocessing
4. a dedicated SVD tab
5. history metadata for SVD-specific parameters

---

## 6. Recommended Phase 1 Shape

### 6.1 Product scope

Phase 1 target:

1. user selects or browses one PNG
2. user sets a few SVD parameters
3. StableNew generates one short clip
4. StableNew exports MP4
5. artifact appears in history/output

### 6.2 Runtime shape

Recommended runtime shape:

1. GUI tab gathers SVD request
2. controller validates request and builds a selected-image NJR ending in an
   `svd_native` runtime stage
3. job is submitted to existing queue/background execution path
4. executor dispatches the `svd_native` stage to a native SVD service
5. result metadata is written into history/output

### 6.3 Do not force PromptPack integration in Phase 1

PromptPack and Pipeline-tab integration should wait because:

1. SVD is not prompt-first generation
2. forcing stage-card integration now would blur two distinct workflows
3. selected-image animation is the cleaner product seam

### 6.4 Preferred internal decomposition

Within the separate SVD tab flow, the cleaner implementation split is:

1. config models
2. model registry
3. preprocess helpers
4. inference service
5. export helpers
6. manifest/registry helper
7. runtime-stage orchestration

This is superior to placing all logic into one `SVDService` because it keeps
model loading, media export, and StableNew-specific artifact recording from
becoming tightly coupled.

---

## 7. Proposed Module Layout

### 7.1 Create

1. `src/video/svd_config.py`
2. `src/video/svd_models.py`
3. `src/video/svd_errors.py`
4. `src/video/svd_preprocess.py`
5. `src/video/svd_service.py`
6. `src/video/svd_runner.py`
7. `src/video/video_export.py`
8. `src/video/svd_registry.py`
9. `src/controller/svd_controller.py`
10. `src/gui/views/svd_tab_frame_v2.py`

### 7.2 Modify

1. `src/gui/main_window_v2.py`
2. `src/controller/app_controller.py`
3. `src/gui/panels_v2/history_panel_v2.py`
4. `src/pipeline/stage_models.py`
5. `src/pipeline/job_models_v2.py`
6. `src/pipeline/reprocess_builder.py`
7. `src/pipeline/executor.py`
8. `src/pipeline/pipeline_runner.py`

### 7.3 Tests

1. `tests/video/test_svd_config.py`
2. `tests/video/test_svd_models.py`
3. `tests/video/test_svd_preprocess.py`
4. `tests/video/test_svd_service.py`
5. `tests/video/test_svd_runner.py`
6. `tests/video/test_svd_registry.py`
7. `tests/controller/test_svd_controller.py`
8. `tests/gui_v2/test_svd_tab_frame_v2.py`
9. `tests/integration/test_svd_golden_path.py`

---

## 8. Recommended Config Shape

Recommended persisted config block:

```json
{
  "svd": {
    "preprocess": {
      "target_width": 1024,
      "target_height": 576,
      "resize_mode": "letterbox",
      "preserve_aspect_ratio": true,
      "center_crop": true,
      "pad_color": [0, 0, 0]
    },
    "inference": {
      "model_id": "stabilityai/stable-video-diffusion-img2vid-xt",
      "variant": "fp16",
      "torch_dtype": "float16",
      "num_frames": 25,
      "fps": 7,
      "motion_bucket_id": 127,
      "noise_aug_strength": 0.05,
      "decode_chunk_size": 2,
      "num_inference_steps": 25,
      "min_guidance_scale": 1.0,
      "max_guidance_scale": 3.0,
      "seed": null,
      "cpu_offload": true,
      "forward_chunking": true,
      "local_files_only": false,
      "cache_dir": null
    },
    "output": {
      "output_format": "mp4",
      "save_frames": false,
      "save_preview_image": true
    }
  }
}
```

Phase 1 should keep source image paths outside this config block and pass them
through the specific job request itself.

This nested shape is superior to one flat config block because:

1. it separates UI sections cleanly
2. it allows future defaults/presets per subdomain
3. it prevents output concerns from being mixed into inference validation

---

## 9. UI Field Recommendation

### 9.1 Primary controls

1. source image path
2. browse image
3. use selected output image
4. model
5. frames
6. fps
7. motion bucket
8. noise augmentation
9. seed
10. resize mode
11. target size preset
12. output format
13. save frames

### 9.2 Advanced controls

1. CPU offload
2. forward chunking
3. decode chunk size
4. local files only
5. cache dir

### 9.3 Deferred-but-planned controls

These should be called out in discovery so the module layout supports them later
without immediate UI sprawl:

1. precision
2. device mode
3. preview prep
4. output stem override
5. save preview image
6. model cache controls

---

## 10. Risks And Second-Order Effects

### 10.1 Portrait images

Without explicit preprocessing, portrait outputs will either stretch badly or
produce confusing motion composition.

StableNew must make the resize policy visible.

### 10.2 VRAM contention with WebUI

Even though SVD is separate from A1111, both can contend for GPU memory if they
run in the same session.

Phase 1 should not attempt simultaneous A1111 and SVD execution.

This is a second-order effect of choosing a native Diffusers backend. The tab is
cleaner, but GPU contention becomes StableNew's responsibility rather than
WebUI's.

### 10.3 Dependency footprint

Adding Diffusers, Transformers, Accelerate, Safetensors, and media export
dependencies is a real productization concern. Phase 1 should capability-gate
imports cleanly and fail with explicit install guidance.

This creates a third-order maintenance effect: once SVD is native, StableNew
must own dependency diagnostics, cache-path guidance, and model-download error
messaging directly.

### 10.4 History schema expansion

History/result metadata must capture enough to explain and reproduce the clip:

1. source image
2. model id
3. seed
4. frame count
5. fps
6. motion controls
7. resize mode
8. output paths

### 10.5 Over-abstraction risk

The alternate plan proposes a wide package tree including independent cache and
output-registry services. That decomposition is conceptually nice, but in the
current repo it would likely overshoot the actual integration surface and create
parallel abstractions that the rest of StableNew does not use.

Phase 1 should therefore keep:

1. a model registry helper
2. a manifest/registry helper
3. an SVD runner/orchestrator

but should not add a general-purpose video service framework or a new
cross-subsystem output registry service yet.

---

## 11. Recommended PR Series

### 11.1 PR-CORE-VIDEO-005

Native SVD runtime foundation:

1. config models
2. model registry
3. preprocess
4. service
5. runner/orchestrator
6. export
7. manifest/registry helper
8. deterministic tests

### 11.2 PR-GUI-VIDEO-006

Dedicated SVD tab:

1. new tab
2. config binding
3. submit action
4. result surfacing
5. selected-image handoff

### 11.3 PR-VIDEO-007

Usability pass:

1. presets
2. cache controls
3. metadata save/load
4. regenerate/retry
5. GIF preview

### 11.4 PR-VIDEO-008

Quality extensions:

1. interpolation
2. frame upscale
3. stabilization
4. batch animate

---

## 12. Recommendation

Approve a Phase 1 spec that:

1. treats SVD as a native StableNew feature
2. gives it a dedicated tab
3. keeps it separate from A1111 and AnimateDiff
4. still reuses queue/history lifecycle semantics

This is the cleanest product and architecture path.

---

## 13. References

1. Diffusers SVD guide:  
   https://huggingface.co/docs/diffusers/main/en/using-diffusers/svd
2. Stability AI SVD XT model card:  
   https://huggingface.co/stabilityai/stable-video-diffusion-img2vid-xt
