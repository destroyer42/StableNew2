Below is a repo-ready StableNew implementation spec for adding Stable Video Diffusion (SVD) as an alternate end-stage animation path for a selected final PNG.

This is written to fit your normal StableNew style:

clear module boundaries

explicit signatures

config-first behavior

atomic phased PR plan

minimal disruption to the current image pipeline

StableNew Implementation Spec
Feature: SVD Img2Vid Alternate Animation Path
1. Objective

Add a new SVD-based image-to-video path to StableNew that allows the user to:

select a finished image output, typically the final upscaled PNG

configure SVD animation parameters in the UI

generate a short animated clip

export MP4, optionally GIF and frame sequence

preserve full run metadata for reproducibility

This path is separate from the existing / planned AnimateDiff end-stage flow.

2. Product Intent
Existing flow

PromptPack -> NJR -> Queue -> Runner -> image outputs -> upscale -> final PNG

New alternate flow

Final PNG / Gallery Selection -> SVD Config -> SVD Runner -> Video Export -> History / Output Registry

Design principle

Treat SVD as a native StableNew Python service using the Diffusers StableVideoDiffusionPipeline, not as an A1111 extension dependency.

Reference model/docs:

stabilityai/stable-video-diffusion-img2vid

stabilityai/stable-video-diffusion-img2vid-xt

Diffusers SVD docs using StableVideoDiffusionPipeline and parameters like motion_bucket_id, noise_aug_strength, decode_chunk_size, and num_frames:
Diffusers SVD docs

SVD-XT model

3. Scope
In scope

add SVD backend service

add image preprocessing for SVD-friendly dimensions

add UI for SVD config and execution

add export to MP4

optional GIF and frame sequence export

run metadata persistence

history integration

Out of scope for MVP

long-form video generation

multi-keyframe chaining

interpolation integration

face repair / temporal restoration

distributed video queue execution

text-guided video prompting beyond SVD’s image-conditioning controls

4. Proposed Module / File Layout

This layout assumes StableNew already has image pipeline and UI structure. Adjust package roots to your repo conventions.

StableNew/
├─ src/
│  ├─ stablenew/
│  │  ├─ video/
│  │  │  ├─ __init__.py
│  │  │  ├─ svd_config.py
│  │  │  ├─ svd_models.py
│  │  │  ├─ svd_preprocess.py
│  │  │  ├─ svd_service.py
│  │  │  ├─ svd_runner.py
│  │  │  ├─ svd_export.py
│  │  │  ├─ svd_registry.py
│  │  │  ├─ svd_errors.py
│  │  │  └─ video_types.py
│  │  │
│  │  ├─ ui/
│  │  │  ├─ video_tab.py
│  │  │  ├─ svd_panel.py
│  │  │  ├─ svd_preview_widget.py
│  │  │  └─ svd_bindings.py
│  │  │
│  │  ├─ services/
│  │  │  ├─ model_cache_service.py
│  │  │  └─ output_registry_service.py
│  │  │
│  │  ├─ config/
│  │  │  ├─ app_config.py
│  │  │  └─ video_defaults.py
│  │  │
│  │  └─ history/
│  │     ├─ output_history.py
│  │     └─ run_metadata.py
│  │
├─ tests/
│  ├─ unit/
│  │  ├─ test_svd_config.py
│  │  ├─ test_svd_preprocess.py
│  │  ├─ test_svd_export.py
│  │  ├─ test_svd_registry.py
│  │  └─ test_svd_bindings.py
│  │
│  ├─ integration/
│  │  ├─ test_svd_runner_smoke.py
│  │  ├─ test_svd_model_load_mock.py
│  │  └─ test_svd_end_to_end_mock.py
│  │
│  └─ fixtures/
│     ├─ sample_landscape.png
│     ├─ sample_portrait.png
│     └─ sample_square.png
│
├─ models/
│  └─ video/
│     └─ svd/
│
└─ outputs/
   └─ video/
5. Architecture Overview
Core components
svd_config.py

Defines the canonical config schema and validation rules.

svd_models.py

Defines model identifiers, presets, and capability metadata.

svd_preprocess.py

Transforms source images into SVD-compatible inputs.

svd_service.py

Loads and manages the StableVideoDiffusionPipeline, model caching, device behavior, and inference.

svd_runner.py

Orchestrates:

input validation

preprocessing

inference

export

registry/history writeback

svd_export.py

Exports:

MP4

GIF

frame sequences

preview thumbnails

svd_registry.py

Writes run metadata and output descriptors for reproducibility and history browsing.

svd_panel.py / video_tab.py

UI entry points and bindings.

6. Exact Class / Function Signatures
6.1 video_types.py
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal, Optional, Sequence

ResizeMode = Literal["crop", "fit_pad", "stretch"]
OutputFormat = Literal["mp4", "gif", "frames", "mp4+gif", "mp4+frames"]
PrecisionMode = Literal["fp16", "fp32"]
DeviceMode = Literal["cuda", "cpu", "auto"]
SvdModelId = Literal[
    "stabilityai/stable-video-diffusion-img2vid",
    "stabilityai/stable-video-diffusion-img2vid-xt",
    "stabilityai/stable-video-diffusion-img2vid-xt-1-1",
]

@dataclass(slots=True)
class SvdInputImage:
    source_path: Path
    original_width: int
    original_height: int
    prepared_path: Optional[Path] = None
    prepared_width: Optional[int] = None
    prepared_height: Optional[int] = None

@dataclass(slots=True)
class SvdGeneratedFrames:
    frames: Sequence["PIL.Image.Image"]
    frame_count: int

@dataclass(slots=True)
class SvdExportArtifacts:
    mp4_path: Optional[Path] = None
    gif_path: Optional[Path] = None
    frames_dir: Optional[Path] = None
    preview_image_path: Optional[Path] = None

@dataclass(slots=True)
class SvdRunResult:
    run_id: str
    config_snapshot_path: Path
    source_image_path: Path
    prepared_image_path: Path
    artifacts: SvdExportArtifacts
    frame_count: int
    fps: int
    seed: int
    model_id: str
    elapsed_seconds: float
6.2 svd_models.py
from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping

@dataclass(frozen=True, slots=True)
class SvdModelSpec:
    model_id: str
    display_name: str
    default_num_frames: int
    gated: bool
    recommended: bool
    notes: str

def get_supported_svd_models() -> Mapping[str, SvdModelSpec]:
    ...

def get_default_svd_model_id() -> str:
    ...

def resolve_svd_model_spec(model_id: str) -> SvdModelSpec:
    ...
Initial supported models
{
  "stabilityai/stable-video-diffusion-img2vid": ...,
  "stabilityai/stable-video-diffusion-img2vid-xt": ...,
  "stabilityai/stable-video-diffusion-img2vid-xt-1-1": ...,
}

Default:

"stabilityai/stable-video-diffusion-img2vid-xt"
6.3 svd_config.py
from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Dict, Optional

from .video_types import DeviceMode, OutputFormat, PrecisionMode, ResizeMode

@dataclass(slots=True)
class SvdPreprocessConfig:
    target_width: int = 1024
    target_height: int = 576
    resize_mode: ResizeMode = "fit_pad"
    center_crop: bool = True
    pad_color: tuple[int, int, int] = (0, 0, 0)
    preserve_aspect_ratio: bool = True

@dataclass(slots=True)
class SvdInferenceConfig:
    model_id: str = "stabilityai/stable-video-diffusion-img2vid-xt"
    precision: PrecisionMode = "fp16"
    device: DeviceMode = "auto"
    seed: int = 42
    num_frames: int = 25
    fps: int = 7
    motion_bucket_id: int = 127
    noise_aug_strength: float = 0.05
    decode_chunk_size: int = 4
    enable_model_cpu_offload: bool = True
    enable_forward_chunking: bool = True
    enable_vae_slicing: bool = False
    enable_xformers: bool = False
    generator_device: Optional[str] = None

@dataclass(slots=True)
class SvdOutputConfig:
    output_root: Path
    output_stem: str
    output_format: OutputFormat = "mp4"
    save_frames: bool = False
    save_preview_image: bool = True
    overwrite_existing: bool = False

@dataclass(slots=True)
class SvdJobConfig:
    source_image_path: Path
    preprocess: SvdPreprocessConfig
    inference: SvdInferenceConfig
    output: SvdOutputConfig

    def validate(self) -> None:
        ...

    def to_dict(self) -> Dict[str, Any]:
        ...

    @classmethod
    def from_dict(cls, payload: Dict[str, Any]) -> "SvdJobConfig":
        ...

def build_default_svd_job_config(source_image_path: Path, output_root: Path) -> SvdJobConfig:
    ...
6.4 svd_errors.py
class SvdError(Exception):
    """Base error for SVD pipeline failures."""

class SvdConfigError(SvdError):
    """Raised for invalid config values."""

class SvdInputError(SvdError):
    """Raised for bad or missing input images."""

class SvdModelLoadError(SvdError):
    """Raised when the SVD model cannot be loaded."""

class SvdInferenceError(SvdError):
    """Raised when generation fails."""

class SvdExportError(SvdError):
    """Raised when video export fails."""
6.5 svd_preprocess.py
from __future__ import annotations

from pathlib import Path
from PIL import Image

from .svd_config import SvdPreprocessConfig
from .video_types import SvdInputImage

def load_source_image(path: Path) -> Image.Image:
    ...

def validate_source_image(path: Path) -> None:
    ...

def prepare_image_for_svd(
    source_path: Path,
    config: SvdPreprocessConfig,
    temp_dir: Path,
) -> SvdInputImage:
    ...

def resize_and_pad_image(
    image: Image.Image,
    target_width: int,
    target_height: int,
    pad_color: tuple[int, int, int],
) -> Image.Image:
    ...

def resize_and_crop_image(
    image: Image.Image,
    target_width: int,
    target_height: int,
) -> Image.Image:
    ...

def stretch_resize_image(
    image: Image.Image,
    target_width: int,
    target_height: int,
) -> Image.Image:
    ...

def save_prepared_image(image: Image.Image, output_path: Path) -> Path:
    ...
6.6 svd_service.py
from __future__ import annotations

from pathlib import Path
from typing import Optional

import torch
from diffusers import StableVideoDiffusionPipeline

from .svd_config import SvdInferenceConfig
from .video_types import SvdGeneratedFrames

class SvdPipelineHandle:
    def __init__(
        self,
        model_id: str,
        pipeline: StableVideoDiffusionPipeline,
        device: str,
        precision: str,
    ) -> None:
        self.model_id = model_id
        self.pipeline = pipeline
        self.device = device
        self.precision = precision

class SvdService:
    def __init__(
        self,
        model_cache_dir: Optional[Path] = None,
    ) -> None:
        ...

    def get_or_load_pipeline(
        self,
        config: SvdInferenceConfig,
    ) -> SvdPipelineHandle:
        ...

    def unload_pipeline(self, model_id: Optional[str] = None) -> None:
        ...

    def clear_all_pipelines(self) -> None:
        ...

    def generate_frames(
        self,
        prepared_image_path: Path,
        config: SvdInferenceConfig,
    ) -> SvdGeneratedFrames:
        ...

    def _load_pipeline(
        self,
        config: SvdInferenceConfig,
    ) -> SvdPipelineHandle:
        ...

    def _resolve_device(self, config: SvdInferenceConfig) -> str:
        ...

    def _resolve_torch_dtype(self, config: SvdInferenceConfig) -> torch.dtype:
        ...

    def _build_generator(self, seed: int, device: str) -> torch.Generator:
        ...

    def _apply_memory_optimizations(
        self,
        pipe: StableVideoDiffusionPipeline,
        config: SvdInferenceConfig,
    ) -> None:
        ...
Expected backend behavior

cache by model_id + precision + device

support local HF cache / configurable model cache dir

use StableVideoDiffusionPipeline.from_pretrained(...)

support variant="fp16" when precision is fp16 and model supports it

call:

enable_model_cpu_offload() when configured

unet.enable_forward_chunking() when configured

This aligns with Diffusers SVD guidance.
Docs: Diffusers SVD

6.7 svd_export.py
from __future__ import annotations

from pathlib import Path
from typing import Sequence
from PIL import Image

from .svd_config import SvdOutputConfig
from .video_types import SvdExportArtifacts

def export_video_artifacts(
    frames: Sequence[Image.Image],
    config: SvdOutputConfig,
) -> SvdExportArtifacts:
    ...

def export_frames_to_mp4(
    frames: Sequence[Image.Image],
    output_path: Path,
    fps: int,
) -> Path:
    ...

def export_frames_to_gif(
    frames: Sequence[Image.Image],
    output_path: Path,
    fps: int,
) -> Path:
    ...

def export_frames_sequence(
    frames: Sequence[Image.Image],
    frames_dir: Path,
    stem: str,
) -> Path:
    ...

def create_preview_image(
    frames: Sequence[Image.Image],
    output_path: Path,
) -> Path:
    ...

def ensure_output_paths(
    config: SvdOutputConfig,
) -> dict[str, Path]:
    ...
6.8 svd_registry.py
from __future__ import annotations

from pathlib import Path
from typing import Any, Dict

from .svd_config import SvdJobConfig
from .video_types import SvdRunResult

def write_svd_run_manifest(
    run_dir: Path,
    config: SvdJobConfig,
    result: SvdRunResult,
) -> Path:
    ...

def build_svd_run_record(
    config: SvdJobConfig,
    result: SvdRunResult,
) -> Dict[str, Any]:
    ...

def register_svd_output(
    result: SvdRunResult,
) -> None:
    ...
Manifest contents

run id

timestamp

source image path

prepared image path

model id

frames

fps

seed

motion bucket

noise aug strength

decode chunk size

output artifact paths

elapsed time

6.9 svd_runner.py
from __future__ import annotations

from pathlib import Path
from typing import Optional

from .svd_config import SvdJobConfig
from .svd_service import SvdService
from .video_types import SvdRunResult

class SvdRunner:
    def __init__(
        self,
        service: SvdService,
        temp_root: Path,
    ) -> None:
        ...

    def run_job(self, config: SvdJobConfig) -> SvdRunResult:
        ...

    def dry_validate(self, config: SvdJobConfig) -> None:
        ...
run_job() orchestration

validate config

validate source image

preprocess source image

load / reuse pipeline

generate frames

export artifacts

write manifest

register output history

return SvdRunResult

6.10 UI files
video_tab.py
class VideoTabController:
    def __init__(self, ... ) -> None:
        ...

    def build(self) -> None:
        ...

    def bind_events(self) -> None:
        ...
svd_panel.py
class SvdPanel:
    def __init__(self, ... ) -> None:
        ...

    def build_controls(self) -> None:
        ...

    def get_job_config(self) -> "SvdJobConfig":
        ...

    def load_from_job_config(self, config: "SvdJobConfig") -> None:
        ...

    def set_selected_source_image(self, image_path: str) -> None:
        ...

    def on_run_clicked(self) -> None:
        ...

    def on_preview_clicked(self) -> None:
        ...
svd_bindings.py
def bind_svd_panel_events(panel: "SvdPanel", controller: "VideoTabController") -> None:
    ...

def build_svd_job_config_from_ui(panel: "SvdPanel") -> "SvdJobConfig":
    ...

def push_svd_result_to_history_ui(result: "SvdRunResult") -> None:
    ...
7. Config Schema

Use JSON-serializable config, with dataclass backing.

Canonical JSON schema example
{
  "source_image_path": "outputs/final/my_image.png",
  "preprocess": {
    "target_width": 1024,
    "target_height": 576,
    "resize_mode": "fit_pad",
    "center_crop": true,
    "pad_color": [0, 0, 0],
    "preserve_aspect_ratio": true
  },
  "inference": {
    "model_id": "stabilityai/stable-video-diffusion-img2vid-xt",
    "precision": "fp16",
    "device": "auto",
    "seed": 42,
    "num_frames": 25,
    "fps": 7,
    "motion_bucket_id": 127,
    "noise_aug_strength": 0.05,
    "decode_chunk_size": 4,
    "enable_model_cpu_offload": true,
    "enable_forward_chunking": true,
    "enable_vae_slicing": false,
    "enable_xformers": false,
    "generator_device": null
  },
  "output": {
    "output_root": "outputs/video",
    "output_stem": "my_image_svd",
    "output_format": "mp4",
    "save_frames": false,
    "save_preview_image": true,
    "overwrite_existing": false
  }
}
Validation rules
source image

must exist

must be readable PNG/JPG/WebP-compatible PIL image

minimum size: 128 x 128

reject corrupt images

preprocess

width > 0

height > 0

resize mode in allowed set

inference

num_frames >= 1

fps >= 1

motion_bucket_id >= 0

0.0 <= noise_aug_strength <= 1.0

decode_chunk_size >= 1

model id in supported set unless “allow custom model id” is enabled in future

output

output root must be writable or creatable

stem must be sanitized for filenames

8. UI Field List
New tab / section

Video

submode: SVD Img2Vid

future submode: AnimateDiff

SVD UI fields
Input section

Source Image

file picker

“Use Current Final Image” button

“Use Selected Gallery Image” button

Image Preview

Prepared Size Preview

label only, e.g. 1024 x 576

Model section

SVD Model

dropdown:

stable-video-diffusion-img2vid

stable-video-diffusion-img2vid-xt

stable-video-diffusion-img2vid-xt-1-1

Precision

fp16 / fp32

Device

auto / cuda / cpu

Motion / Inference section

Seed

Frames

FPS

Motion Bucket ID

Noise Aug Strength

Decode Chunk Size

Memory / Performance section

Enable Model CPU Offload

Enable Forward Chunking

Enable VAE Slicing

Enable xFormers
only if already available in repo/runtime

Preprocess section

Resize Mode

crop

fit_pad

stretch

Target Width

Target Height

Preserve Aspect Ratio

Center Crop

Pad Color

Output section

Output Format

MP4

GIF

Frames

MP4 + GIF

MP4 + Frames

Output Root

Output Stem

Save Preview Image

Save Frames

Action buttons

Preview Prep

Generate Clip

Open Output Folder

Send Result to History

Read-only status / result fields

active model status

estimated mode: low VRAM, balanced, fast

last run id

elapsed time

output path

errors / warnings panel

9. Default Presets
Preset: Balanced Default
{
  "model_id": "stabilityai/stable-video-diffusion-img2vid-xt",
  "num_frames": 25,
  "fps": 7,
  "motion_bucket_id": 127,
  "noise_aug_strength": 0.05,
  "decode_chunk_size": 4,
  "enable_model_cpu_offload": true,
  "enable_forward_chunking": true
}
Preset: Low VRAM
{
  "precision": "fp16",
  "num_frames": 14,
  "decode_chunk_size": 2,
  "enable_model_cpu_offload": true,
  "enable_forward_chunking": true
}
Preset: Higher Motion
{
  "motion_bucket_id": 180,
  "noise_aug_strength": 0.10
}

These map cleanly to parameters highlighted in the Diffusers SVD docs.
Source: Diffusers SVD docs

10. Output Structure

Recommended output layout:

outputs/
└─ video/
   └─ 2026-03-14/
      └─ svd_20260314_163015_abc123/
         ├─ input_original.png
         ├─ input_prepared.png
         ├─ output.mp4
         ├─ output.gif
         ├─ frames/
         │  ├─ frame_0001.png
         │  ├─ frame_0002.png
         │  └─ ...
         ├─ preview.png
         └─ run_manifest.json
11. StableNew Integration Points
Recommended integration hooks
output gallery / final image history

Add contextual action:

Animate with SVD

final upscale completion event

Optional future hook:

“Send to SVD panel” button after upscale completes

history service

Treat video outputs as first-class artifacts alongside still images.

config service

Persist last-used SVD settings separately from image-generation settings.

12. Phased PR Plan

Below is the phased PR plan in a StableNew-friendly implementation style.

PR-VID-SVD-001
Title

Introduce SVD config/types/model registry foundation

Goal

Create the type system, config schema, model registry, and validation layer for SVD without wiring inference yet.

Why

This isolates schema and UI contract first, minimizing later churn.

Allowed Files
src/stablenew/video/video_types.py
src/stablenew/video/svd_models.py
src/stablenew/video/svd_config.py
src/stablenew/video/svd_errors.py
src/stablenew/config/video_defaults.py
tests/unit/test_svd_config.py
Deliverables

SvdJobConfig, SvdInferenceConfig, SvdPreprocessConfig, SvdOutputConfig

supported model registry

config serialization / deserialization

validation rules

default preset builders

Acceptance Criteria

configs round-trip to/from dict/json

invalid values raise SvdConfigError

default model resolves to img2vid-xt

test coverage for validation boundaries

Risks

schema drift before UI/inference implementation

Rollback

remove video/ config/types modules only

PR-VID-SVD-002
Title

Add SVD image preprocessing and output path planning

Goal

Implement source image loading, validation, resize/crop/pad logic, and output path helpers.

Allowed Files
src/stablenew/video/svd_preprocess.py
src/stablenew/video/svd_export.py
src/stablenew/video/svd_errors.py
tests/unit/test_svd_preprocess.py
tests/unit/test_svd_export.py
tests/fixtures/sample_landscape.png
tests/fixtures/sample_portrait.png
tests/fixtures/sample_square.png
Deliverables

source image validation

prepared image creation

crop / fit_pad / stretch modes

output path planning

preview image export helper

GIF export helper

frame sequence export helper

Acceptance Criteria

portrait / square / landscape inputs handled deterministically

prepared output matches target size exactly

output paths created under expected run directory

unit tests cover resize modes

Risks

aspect-ratio behavior may need tuning later

Rollback

remove preprocessing/export modules

PR-VID-SVD-003
Title

Implement SVD service and local pipeline management

Goal

Add model loading, pipeline caching, memory tuning, and frame generation via Diffusers.

Allowed Files
src/stablenew/video/svd_service.py
src/stablenew/video/svd_models.py
src/stablenew/video/svd_errors.py
tests/integration/test_svd_model_load_mock.py
tests/integration/test_svd_runner_smoke.py
Deliverables

SvdService

local pipeline cache keyed by model/precision/device

generate_frames()

offload/chunking options

robust exception wrapping into SvdModelLoadError / SvdInferenceError

Acceptance Criteria

service loads configured model

repeated requests reuse cached pipeline

mock smoke test passes without UI

failures surface cleanly to caller

Notes

Backed by Diffusers StableVideoDiffusionPipeline using model ids such as:

stabilityai/stable-video-diffusion-img2vid-xt
Docs/model refs:
Diffusers SVD docs

SVD-XT model

Risks

environment-specific CUDA / torch compatibility

xFormers availability variance

Rollback

remove service implementation, retain config layer

PR-VID-SVD-004
Title

Add SVD runner, manifest writing, and output registry integration

Goal

Implement the orchestration layer and artifact registration.

Allowed Files
src/stablenew/video/svd_runner.py
src/stablenew/video/svd_registry.py
src/stablenew/history/run_metadata.py
src/stablenew/history/output_history.py
src/stablenew/services/output_registry_service.py
tests/unit/test_svd_registry.py
tests/integration/test_svd_end_to_end_mock.py
Deliverables

SvdRunner.run_job()

run manifest JSON

output registry/history entry

run id creation

elapsed time tracking

Acceptance Criteria

one config can produce full run record

artifacts registered in history

manifest contains all expected parameters

failed runs do not corrupt history

Risks

history schema integration may require adapter layer

Rollback

disable runner registration, preserve service layer

PR-VID-SVD-005
Title

Add SVD UI panel and bindings

Goal

Expose SVD to the user through a dedicated UI pane.

Allowed Files
src/stablenew/ui/video_tab.py
src/stablenew/ui/svd_panel.py
src/stablenew/ui/svd_bindings.py
tests/unit/test_svd_bindings.py
Deliverables

Video tab

SVD panel

control bindings -> SvdJobConfig

“Use Current Final Image”

“Generate Clip”

status and output path display

Acceptance Criteria

user can build config entirely from UI

selected gallery/final image path is injected correctly

generation invokes runner

success/failure surfaces visibly

Risks

UI framework specifics may require event adaptation

Rollback

hide SVD panel behind feature flag

PR-VID-SVD-006
Title

Add gallery/history integration and contextual SVD actions

Goal

Make SVD accessible from existing StableNew output browsing UX.

Allowed Files
src/stablenew/ui/video_tab.py
src/stablenew/ui/svd_panel.py
src/stablenew/history/output_history.py
src/stablenew/services/output_registry_service.py
tests/integration/test_svd_end_to_end_mock.py
Deliverables

right-click / action menu: Animate with SVD

open image into SVD panel

returned result visible in history/output viewer

Acceptance Criteria

user can select prior final PNG and route it into SVD

generated MP4 is visible in history

manifest link is accessible

Risks

output browser may need video MIME support

Rollback

keep standalone SVD tab, remove contextual entrypoints

PR-VID-SVD-007
Title

Add presets, quality-of-life defaults, and low-VRAM safeguards

Goal

Harden the feature for real use.

Allowed Files
src/stablenew/config/video_defaults.py
src/stablenew/video/svd_config.py
src/stablenew/ui/svd_panel.py
src/stablenew/video/svd_service.py
tests/unit/test_svd_config.py
tests/integration/test_svd_runner_smoke.py
Deliverables

default presets

low VRAM safety preset

input sanity warnings

decode chunk recommendations

optional fp32 fallback

preflight environment checks

Acceptance Criteria

first-time user can run Balanced preset successfully

low-VRAM mode sets safe defaults

warning shown for portrait/stretch mismatch or high-memory settings

Risks

too many controls may clutter the panel

Rollback

preserve presets in config only; reduce UI exposure

13. Recommended Implementation Order

PR-VID-SVD-001

PR-VID-SVD-002

PR-VID-SVD-003

PR-VID-SVD-004

PR-VID-SVD-005

PR-VID-SVD-006

PR-VID-SVD-007

This order keeps the architecture clean:

schema first

deterministic preprocessing next

then inference

then orchestration/history

then UI

then integration polish

14. Suggested Defaults for First Working Release
Initial defaults

model: stabilityai/stable-video-diffusion-img2vid-xt

target size: 1024 x 576

resize mode: fit_pad

frames: 25

fps: 7

motion bucket: 127

noise aug strength: 0.05

decode chunk size: 4

CPU offload: true

forward chunking: true

These are conservative and aligned with the documented SVD usage and memory recommendations in Diffusers.
Source: Diffusers SVD docs

15. Top 3 Critical Design Issues to Watch
1. Portrait-image handling

Your StableNew outputs may often be portrait SDXL images. SVD examples are commonly landscape-oriented.
Mitigation:

default to fit_pad

show prepared preview before run

expose crop mode as optional

2. VRAM spikes

SVD is materially heavier than single-image generation.
Mitigation:

enable CPU offload and forward chunking by default

surface decode_chunk_size

provide Low VRAM preset

3. Model/runtime coupling

Torch, CUDA, diffusers, and xFormers can drift.
Mitigation:

isolate SVD runtime into dedicated service layer

wrap failures with StableNew-specific errors

avoid making SVD dependent on A1111 extension plumbing

16. Final Recommendation

For StableNew, this should be implemented as:

a native Python Diffusers-based SVD service
with
a dedicated UI panel and output-history integration

—not as an A1111 extension wrapper.

That gives you the cleanest long-term architecture:

better control

fewer moving pieces

easier debugging

easier future expansion to interpolation, batching, or alternate video backends