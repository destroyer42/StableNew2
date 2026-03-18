# PR-CORE-VIDEO-005: SVD Phase 1 Native Img2Vid Tab

**Status**: Specification  
**Priority**: HIGH  
**Effort**: MEDIUM-HIGH  
**Phase**: Video Phase 1  
**Date**: 2026-03-14

## Context & Motivation

### Problem Statement

StableNew can currently:

1. generate still images through PromptPack -> Builder -> NJR -> Queue -> Runner
2. assemble existing image sequences into clips through Movie Clips
3. generate animation through AnimateDiff in the main pipeline

It cannot yet:

1. take a finished PNG
2. animate it through a native Python SVD backend
3. export a clip through a dedicated tab without A1111/WebUI coupling

### Why This Matters

SVD is the right product seam for:

1. animating chosen final images
2. hero-frame motion generation
3. short clip generation independent of A1111 extension state

This gives StableNew a second animation path that is cleaner for selected-image
workflows than forcing everything through WebUI.

### Current Architecture

This PR intentionally keeps SVD separate from:

1. A1111 payload builders
2. WebUI process management
3. AnimateDiff stage config

But it still preserves StableNew's job lifecycle:

1. GUI tab -> controller -> NJR-backed queued background execution -> history/output

### Reference

1. [`docs/D-VIDEO-005-SVD-Native-Tab-Discovery.md`](../D-VIDEO-005-SVD-Native-Tab-Discovery.md)
2. [`docs/ARCHITECTURE_v2.6.md`](../ARCHITECTURE_v2.6.md)
3. [`docs/StableNew_v2.6_Canonical_Execution_Contract.md`](../StableNew_v2.6_Canonical_Execution_Contract.md)
4. Diffusers SVD docs:
   https://huggingface.co/docs/diffusers/main/en/using-diffusers/svd
5. SVD XT model card:
   https://huggingface.co/stabilityai/stable-video-diffusion-img2vid-xt

## Goals & Non-Goals

### Goals

1. Add a native SVD backend service under `src/video/`.
2. Add explicit preprocess handling for portrait and non-landscape inputs.
3. Add MP4 export and optional frame export.
4. Add a dedicated `SVD Img2Vid` GUI tab.
5. Generate one short clip from one chosen PNG.
6. Surface result artifacts in StableNew history/output.

### Non-Goals

1. No A1111/WebUI dependency.
2. No PromptPack builder integration.
3. No Pipeline-tab stage card integration.
4. No interpolation, stabilization, or frame upscaling.
5. No batch animate queue in Phase 1.
6. No learning-system integration.

## Allowed Files

### Files to Create

| File | Purpose | Lines (Est.) |
|------|---------|--------------|
| `src/video/svd_config.py` | Nested preprocess/inference/output config models | 140 |
| `src/video/svd_models.py` | Typed model registry and result models | 120 |
| `src/video/svd_errors.py` | Typed SVD runtime/config errors | 60 |
| `src/video/svd_preprocess.py` | Input image validation and resize policy | 180 |
| `src/video/svd_service.py` | Native Diffusers-backed SVD generation | 220 |
| `src/video/svd_runner.py` | Orchestrates preprocess -> generate -> export -> manifest | 140 |
| `src/video/video_export.py` | MP4/GIF/frame export helpers | 120 |
| `src/video/svd_registry.py` | Writes run manifests and history-friendly records | 100 |
| `src/controller/svd_controller.py` | Tab-facing controller for validation and submit | 140 |
| `src/gui/views/svd_tab_frame_v2.py` | Dedicated SVD tab UI | 260 |
| `tests/video/test_svd_config.py` | Config validation tests | 100 |
| `tests/video/test_svd_models.py` | Model validation tests | 80 |
| `tests/video/test_svd_preprocess.py` | Resize/preprocess tests | 160 |
| `tests/video/test_svd_service.py` | Service execution tests with mocked pipeline | 220 |
| `tests/video/test_svd_runner.py` | Orchestration tests | 140 |
| `tests/video/test_svd_registry.py` | Manifest and record tests | 100 |
| `tests/controller/test_svd_controller.py` | Controller submit/validation tests | 140 |
| `tests/gui_v2/test_svd_tab_frame_v2.py` | GUI contract tests | 180 |
| `tests/integration/test_svd_golden_path.py` | End-to-end mocked golden path | 180 |

### Files to Modify

| File | Reason | Lines Changed (Est.) |
|------|--------|----------------------|
| `src/gui/main_window_v2.py` | Register the new SVD tab | 40 |
| `src/controller/app_controller.py` | Attach SVD controller and job submit/history plumbing | 120 |
| `src/gui/panels_v2/history_panel_v2.py` | Surface video artifact actions if required | 60 |
| `src/pipeline/stage_models.py` | Add `svd_native` stage type | 20 |
| `src/pipeline/job_models_v2.py` | Allow/display SVD-native stage labels and artifacts | 40 |
| `src/pipeline/reprocess_builder.py` | Emit selected-image NJRs ending in `svd_native` | 80 |
| `src/pipeline/executor.py` | Dispatch native SVD service from runtime stage | 140 |
| `src/pipeline/pipeline_runner.py` | Preserve SVD runtime metadata in results | 80 |
| `docs/DOCS_INDEX_v2.6.md` | Register the new active docs | 10 |

### Forbidden Files (DO NOT TOUCH)

| File/Directory | Reason |
|----------------|--------|
| `src/api/` | SVD Phase 1 is native Python, not WebUI |
| `src/pipeline/prompt_pack_job_builder.py` | No PromptPack integration in Phase 1 |
| `src/learning/` | Learning is out of scope |
| `src/queue/` | Queue architecture is not being redesigned here |

## Exact Models And Signatures

### `src/video/svd_config.py`

```python
from dataclasses import dataclass
from typing import Literal

SVDResizeMode = Literal["letterbox", "center_crop", "contain_then_crop"]
SVDOutputFormat = Literal["mp4", "gif", "frames"]
SVDDType = Literal["float16", "bfloat16", "float32"]

@dataclass(frozen=True)
class SVDPreprocessConfig:
    target_width: int = 1024
    target_height: int = 576
    resize_mode: SVDResizeMode = "letterbox"
    preserve_aspect_ratio: bool = True
    center_crop: bool = True
    pad_color: tuple[int, int, int] = (0, 0, 0)

@dataclass(frozen=True)
class SVDInferenceConfig:
    model_id: str = "stabilityai/stable-video-diffusion-img2vid-xt"
    variant: str | None = "fp16"
    torch_dtype: SVDDType = "float16"
    num_frames: int = 25
    fps: int = 7
    motion_bucket_id: int = 127
    noise_aug_strength: float = 0.05
    decode_chunk_size: int = 2
    num_inference_steps: int = 25
    min_guidance_scale: float = 1.0
    max_guidance_scale: float = 3.0
    seed: int | None = None
    cpu_offload: bool = True
    forward_chunking: bool = True
    local_files_only: bool = False
    cache_dir: str | None = None

@dataclass(frozen=True)
class SVDOutputConfig:
    output_format: SVDOutputFormat = "mp4"
    save_frames: bool = False
    save_preview_image: bool = True

@dataclass(frozen=True)
class SVDConfig:
    preprocess: SVDPreprocessConfig = SVDPreprocessConfig()
    inference: SVDInferenceConfig = SVDInferenceConfig()
    output: SVDOutputConfig = SVDOutputConfig()
```

### `src/video/svd_models.py`

```python
from dataclasses import dataclass
from pathlib import Path
from typing import Literal
from typing import Mapping

@dataclass(frozen=True)
class SVDModelSpec:
    model_id: str
    display_name: str
    default_num_frames: int
    recommended: bool
    notes: str

def get_supported_svd_models() -> Mapping[str, SVDModelSpec]: ...
def get_default_svd_model_id() -> str: ...
def resolve_svd_model_spec(model_id: str) -> SVDModelSpec: ...

@dataclass(frozen=True)
class SVDPreprocessResult:
    source_path: Path
    prepared_path: Path
    original_width: int
    original_height: int
    target_width: int
    target_height: int
    resize_mode: SVDResizeMode
    was_resized: bool
    was_padded: bool
    was_cropped: bool

@dataclass(frozen=True)
class SVDResult:
    source_image_path: Path
    video_path: Path | None
    gif_path: Path | None
    frame_paths: list[Path]
    thumbnail_path: Path | None
    metadata_path: Path | None
    frame_count: int
    fps: int
    seed: int | None
    model_id: str
    preprocess: SVDPreprocessResult
```

### `src/video/svd_errors.py`

```python
class SVDError(Exception): ...
class SVDConfigError(SVDError): ...
class SVDInputError(SVDError): ...
class SVDModelLoadError(SVDError): ...
class SVDInferenceError(SVDError): ...
class SVDExportError(SVDError): ...
```

### `src/video/svd_preprocess.py`

```python
from pathlib import Path
from PIL import Image
from src.video.svd_config import SVDPreprocessConfig
from src.video.svd_models import SVDPreprocessResult

def load_svd_source_image(path: str | Path) -> Image.Image: ...
def validate_svd_source_image(path: str | Path) -> None: ...

def prepare_svd_input(
    *,
    source_path: str | Path,
    config: SVDPreprocessConfig,
    temp_dir: str | Path,
) -> SVDPreprocessResult: ...
```

### `src/video/video_export.py`

```python
from pathlib import Path
from PIL import Image

def export_video_mp4(
    *,
    frames: list[Image.Image],
    output_path: str | Path,
    fps: int,
) -> Path: ...

def export_video_gif(
    *,
    frames: list[Image.Image],
    output_path: str | Path,
    fps: int,
) -> Path: ...

def save_video_frames(
    *,
    frames: list[Image.Image],
    output_dir: str | Path,
    prefix: str = "frame",
) -> list[Path]: ...
```

### `src/video/svd_service.py`

```python
from pathlib import Path
from src.video.svd_config import SVDInferenceConfig
from src.video.svd_models import SVDResult

class SVDService:
    def __init__(self, *, cache_dir: str | None = None) -> None: ...
    def is_available(self) -> tuple[bool, str | None]: ...
    def clear_model_cache(self, model_id: str | None = None) -> None: ...
    def generate_frames(
        self,
        *,
        prepared_image_path: str | Path,
        config: SVDInferenceConfig,
    ) -> list["PIL.Image.Image"]: ...
```

### `src/video/svd_runner.py`

```python
from pathlib import Path
from src.video.svd_config import SVDConfig
from src.video.svd_models import SVDResult

class SVDRunner:
    def __init__(self, *, service, output_root: str | Path) -> None: ...
    def dry_validate(self, *, source_image_path: str | Path, config: SVDConfig) -> None: ...
    def run(
        self,
        *,
        source_image_path: str | Path,
        config: SVDConfig,
        job_id: str,
    ) -> SVDResult: ...
```

### `src/controller/svd_controller.py`

```python
from pathlib import Path
from src.video.svd_config import SVDConfig

class SVDController:
    def __init__(self, *, app_controller, svd_service=None) -> None: ...
    def validate_source_image(self, path: str | Path) -> tuple[bool, str | None]: ...
    def build_svd_config(self, form_data: dict[str, object]) -> SVDConfig: ...
    def submit_svd_job(
        self,
        *,
        source_image_path: str | Path,
        config: SVDConfig,
    ) -> str: ...
```

### `src/gui/views/svd_tab_frame_v2.py`

```python
class SVDTabFrameV2(ttk.Frame):
    def __init__(self, parent, app_controller=None, app_state=None) -> None: ...
    def bind_controller(self, controller) -> None: ...
    def refresh_from_state(self) -> None: ...
```

### `src/pipeline/executor.py`

```python
def run_svd_native_stage(
    self,
    *,
    input_image_path: str | Path,
    stage_config: dict[str, object],
    output_dir: str | Path,
    job_id: str,
) -> dict[str, object]: ...
```

### `src/video/svd_registry.py`

```python
from pathlib import Path
from src.video.svd_config import SVDConfig
from src.video.svd_models import SVDResult

def write_svd_run_manifest(*, run_dir: str | Path, config: SVDConfig, result: SVDResult) -> Path: ...
def build_svd_history_record(*, config: SVDConfig, result: SVDResult) -> dict[str, object]: ...
```

## Config Schema

Persist SVD defaults under:

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

Source image path stays outside the persisted default block and remains part of
the submitted job request.

## UI Field List

### Primary Fields

1. Source image path
2. Browse image
3. Use selected output image
4. Model
5. Frames
6. FPS
7. Motion bucket
8. Noise augmentation
9. Seed
10. Target size preset
11. Resize mode
12. Output format
13. Save frames

### Advanced Fields

1. CPU offload
2. Forward chunking
3. Decode chunk size
4. Local files only
5. Cache dir

### Deferred Fields (Not Phase 1 UI)

1. precision
2. device mode
3. preview prep
4. output stem override
5. save preview image

## Implementation Plan

### Step 1: Add Typed SVD Models And Config Validation

Create `src/video/svd_models.py` and cover:

1. nested config defaults in `src/video/svd_config.py`
2. model registry in `src/video/svd_models.py`
3. typed preprocess and result models
4. explicit SVD error types

**Create**:
`src/video/svd_config.py`,
`src/video/svd_models.py`,
`src/video/svd_errors.py`  
**Create**:
`tests/video/test_svd_config.py`,
`tests/video/test_svd_models.py`

### Step 2: Add SVD Preprocess And Export Helpers

Create:

1. input-image loading
2. explicit resize-policy handling
3. MP4/GIF/frame export helpers
4. preview image support

Required behavior:

1. no silent stretching
2. deterministic target size handling
3. clear failure on bad image paths

**Create**: `src/video/svd_preprocess.py`, `src/video/video_export.py`  
**Create**: `tests/video/test_svd_preprocess.py`

### Step 3: Add Native SVD Service

Create `src/video/svd_service.py` that:

1. loads Diffusers SVD pipeline
2. capability-gates missing imports cleanly
3. applies configured memory settings
4. reuses cached pipelines by model id and dtype
5. runs generation

Create `src/video/svd_runner.py` that:

1. validates inputs
2. preprocesses image
3. calls `SVDService.generate_frames(...)`
4. exports artifacts
5. writes a metadata manifest
6. returns StableNew-friendly result metadata

Tests must mock the underlying Diffusers pipeline. No live model downloads in CI.

**Create**: `src/video/svd_service.py`, `src/video/svd_runner.py`, `src/video/svd_registry.py`  
**Create**: `tests/video/test_svd_service.py`, `tests/video/test_svd_runner.py`, `tests/video/test_svd_registry.py`

### Step 4: Add SVD Controller

Create `src/controller/svd_controller.py` that:

1. validates source image
2. converts GUI form data into `SVDConfig`
3. builds a selected-image NJR ending in `svd_native`
4. submits the job through the existing queue/job service

The controller must not own preprocessing, inference, or export logic directly.

**Create**: `src/controller/svd_controller.py`  
**Create**: `tests/controller/test_svd_controller.py`

### Step 5: Add Dedicated SVD Tab

Create `src/gui/views/svd_tab_frame_v2.py` and register it in
`src/gui/main_window_v2.py`.

Required behavior:

1. source-image browse/select
2. form validation
3. generate action
4. status/progress text
5. open output action
6. prepared size preview label

Do not mix Movie Clips controls into this tab.

**Create**: `src/gui/views/svd_tab_frame_v2.py`  
**Modify**: `src/gui/main_window_v2.py`  
**Create**: `tests/gui_v2/test_svd_tab_frame_v2.py`

### Step 6: Surface Result Artifacts

Update app-level wiring so generated videos appear in StableNew's normal output
and history surfaces.

Minimum required metadata:

1. source image path
2. model id
3. frame count
4. fps
5. motion controls
6. output path(s)

**Modify**:
`src/controller/app_controller.py`,
`src/gui/panels_v2/history_panel_v2.py`,
`src/pipeline/stage_models.py`,
`src/pipeline/job_models_v2.py`,
`src/pipeline/reprocess_builder.py`,
`src/pipeline/executor.py`,
`src/pipeline/pipeline_runner.py`

### Step 7: Add Golden Path Coverage

Add one golden path that proves:

1. selected PNG
2. config submit
3. mocked SVD generation
4. MP4 artifact written
5. result visible through StableNew output/history plumbing
6. manifest written with reproducibility metadata

**Create**: `tests/integration/test_svd_golden_path.py`

## Testing Plan

### Unit Tests

1. `pytest tests/video/test_svd_models.py -q`
2. `pytest tests/video/test_svd_preprocess.py -q`
3. `pytest tests/video/test_svd_service.py -q`

### Controller / GUI Tests

1. `pytest tests/controller/test_svd_controller.py -q`
2. `pytest tests/gui_v2/test_svd_tab_frame_v2.py -q`

### Integration Tests

1. `pytest tests/integration/test_svd_golden_path.py -q`

### Manual Testing

1. Open `SVD Img2Vid` tab.
2. Select a real PNG.
3. Generate default 25-frame MP4.
4. Confirm output file exists.
5. Confirm metadata manifest exists.
6. Confirm output is reachable from StableNew history/output surfaces.

## Verification Criteria

### Success Criteria

1. StableNew can animate one selected PNG into one MP4 without A1111.
2. Portrait inputs are handled through explicit resize policy.
3. Missing SVD dependencies fail with clear install guidance.
4. The new tab is usable without touching Pipeline tab stage cards.
5. Execution still flows through StableNew's queued background runtime.
6. Each run writes a manifest with enough metadata to explain and reproduce the clip.
7. Deterministic tests pass without live model downloads.

### Failure Criteria

1. Any A1111/WebUI dependency is introduced.
2. Movie Clips and SVD become intermixed in one confusing UI surface.
3. Portrait images are stretched silently.
4. Phase 1 attempts interpolation, stabilization, or batching.
5. SVD runtime bypasses StableNew queue/history conventions entirely.
6. SVD logic collapses into one oversized service/controller without a clean orchestration split.

## Follow-On PR Plan

### PR-GUI-VIDEO-006

Usability pass:

1. presets
2. selected-history-image handoff
3. regenerate/retry
4. GIF preview
5. cache controls

### PR-VIDEO-007

Quality pass:

1. interpolation
2. frame upscale
3. stabilization
4. batch animation
