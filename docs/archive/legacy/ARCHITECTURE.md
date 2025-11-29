# ARCHITECTURE (Legacy / Archived)

_Last updated: 2025-11-15_

This document is the **archived, historical version** of the StableNew architecture.
It originates from earlier iterations of the codebase and **no longer reflects the current structure** of:

- The GUI system  
- The pipeline executor  
- The randomization/matrix system  
- The WebUI API client  
- Logging and manifests  
- Threading and lifecycle behavior  
- Current planned features (job queue, distributed execution, video pipeline)

It has been preserved here because:

1. Many of the ideas and abstractions influenced later designs.
2. Some naming conventions and concepts still exist in the code.
3. Older PRs and test cases may reference structures found here.

However, **no implementation work should reference this file as authoritative**.

Use the modern document instead:

➡️ `docs/ARCHITECTURE_v2.md` — **The current target architecture**

And refer to:

- `docs/StableNew_Roadmap_v1.0.md`
- `docs/Known_Bugs_And_Issues_Summary.md`
- `docs/AGENTS_AND_AI_WORKFLOW.md`

for ongoing development standards and architectural direction.

This file should not be updated further.




This document describes the architecture of StableNew, including the pipeline flow, GUI state management, and cancellation mechanisms.

## Table of Contents

- [System Overview](#system-overview)
- [Pipeline Architecture](#pipeline-architecture)
- [GUI Architecture](#gui-architecture)
- [State Management](#state-management)
- [Cancellation Flow](#cancellation-flow)
- [Data Flow](#data-flow)
- [Configuration System](#configuration-system)

## System Overview

StableNew is a Python application that orchestrates image generation through the Stable Diffusion WebUI API. It follows a modular architecture with clear separation of concerns.

```
┌─────────────────────────────────────────────────────────────┐
│                         StableNew                            │
├─────────────────────────────────────────────────────────────┤
│                                                              │
│  ┌──────────┐    ┌──────────┐    ┌──────────┐             │
│  │   GUI    │───▶│ Pipeline │───▶│ SD WebUI │             │
│  │ (Tkinter)│    │ Executor │    │   API    │             │
│  └──────────┘    └──────────┘    └──────────┘             │
│       │               │                                      │
│       │               │                                      │
│       ▼               ▼                                      │
│  ┌──────────┐    ┌──────────┐                              │
│  │  State   │    │  Config  │                              │
│  │ Manager  │    │ Manager  │                              │
│  └──────────┘    └──────────┘                              │
│                                                              │
│  ┌──────────────────────────────────────────┐              │
│  │         Structured Logger                 │              │
│  │  (JSON manifests + CSV summaries)        │              │
│  └──────────────────────────────────────────┘              │
│                                                              │
└─────────────────────────────────────────────────────────────┘
```

## Pipeline Architecture

### Pipeline Stages

The pipeline consists of five configurable stages with per-image stage selection:

```
┌─────────────────────────────────────────────────────────────────┐
│                    Enhanced Pipeline Flow                        │
└─────────────────────────────────────────────────────────────────┘

  1. txt2img
  ┌──────────┐
  │ Prompt   │
  │   +      │
  │ Config   │
  └──────────┘
       │
       ▼
  ┌──────────┐
  │  Image   │────────┐
  │   File   │        │
  └──────────┘        │
                      ▼
                ┌────────────┐
                │   Stage    │
                │  Chooser   │ ◄─── User selects next stage
                │   Modal    │      per image
                └────────────┘
                      │
         ┌────────────┼────────────┬─────────────┐
         ▼            ▼            ▼             ▼
  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌──────────┐
  │2. img2img│  │3. ADetailer│ │4. Upscale│  │5. None   │
  │ Cleanup  │  │Face/Detail│  │ Enhance  │  │  Skip    │
  │ Refine   │  │   Fix     │  │ Quality  │  │          │
  └──────────┘  └──────────┘  └──────────┘  └──────────┘
       │             │              │              │
       └─────────────┴──────────────┴──────────────┘
                      │
                      ▼
                ┌──────────┐
                │ Enhanced │
                │  Image   │
                └──────────┘
                      │
                      ▼
                ┌──────────┐
                │ 6. Video │
                │  FFmpeg  │
                │  Muxing  │
                └──────────┘
                      │
                      ▼
                ┌──────────┐
                │  MP4 File│
                └──────────┘
```

### Stage Details

#### 1. txt2img - Generate from Prompt
- **Endpoint:** `POST /sdapi/v1/txt2img`
- **Input:** Prompt text + configuration
- **Output:** Base64-encoded image with per-image metadata
- **Features:**
  - Support for `name:` prefix in prompt for custom filenames
  - Automatic global NSFW prevention
  - SDXL and legacy model support
- **Metadata:** JSON sidecar with generation parameters

#### 2. Stage Chooser - Per-Image Selection (New)
- **Type:** Non-blocking modal dialog
- **Triggers:** After each txt2img generation
- **Options:**
  - img2img (cleanup/refinement)
  - ADetailer (face/detail enhancement)
  - Upscale (quality enhancement)
  - None (skip to next image)
- **Features:**
  - Live preview of generated image
  - "Apply to batch" toggle
  - "Re-tune settings" quick access
  - Queue-based non-blocking communication
- **Implementation:** `src/gui/stage_chooser.py`

#### 3a. img2img - Cleanup Pass (Optional)
- **Endpoint:** `POST /sdapi/v1/img2img`
- **Input:** Generated image + denoising strength
- **Output:** Refined image
- **Use Case:** Fix artifacts, improve quality, adjust composition
- **Configuration:** Can be skipped via stage chooser or `pipeline.img2img_enabled: false`

#### 3b. ADetailer - Face/Detail Enhancement (New, Optional)
- **Endpoint:** `POST /sdapi/v1/img2img` with ADetailer extension
- **Input:** Generated image + detection model
- **Output:** Enhanced image with improved faces/details
- **Use Case:** Automatic face restoration, hand fixing, detail enhancement
- **Detection Models:**
  - `face_yolov8n.pt` - Fast face detection
  - `hand_yolov8n.pt` - Hand detection and fixing
  - `person_yolov8n-seg.pt` - Full person segmentation
  - MediaPipe variants for alternative detection
- **Features:**
  - Adjustable confidence threshold (0.0-1.0)
  - Mask feathering for smooth blending
  - Independent sampler/steps/CFG/denoise settings
  - Custom prompts for detail enhancement
- **Configuration:** `adetailer_enabled: true` + model/parameter selection
- **Implementation:** `src/gui/adetailer_config_panel.py`, `src/pipeline/executor.py::run_adetailer()`

#### 4. Upscale - Enhance Quality (Optional)
- **Endpoint:** `POST /sdapi/v1/extra-single-image`
- **Input:** Image + upscaler model + scale factor
- **Output:** Upscaled image
- **Options:** GFPGAN, CodeFormer for face restoration
- **Configuration:** Can be skipped via stage chooser or `pipeline.upscale_enabled: false`

### Flexible Pipeline Execution

The pipeline supports flexible stage execution through both configuration and per-image selection:

**Configuration-Based Control:**
```python
config = {
    "pipeline": {
        "img2img_enabled": True,    # Enable img2img cleanup
        "upscale_enabled": False,    # Skip upscale for faster results
        "adetailer_enabled": True    # Enable ADetailer
    },
    "adetailer": {
        "adetailer_model": "face_yolov8n.pt",
        "adetailer_confidence": 0.3,
        "adetailer_denoise": 0.4
    }
}
```

**Per-Image Stage Selection (New):**
After txt2img, the Stage Chooser modal allows dynamic selection per image:
- Choose different processing for each generated image
- Apply choice to batch for consistency
- Skip stages entirely for specific images

**Stage Flow Examples:**

1. **Full Pipeline with ADetailer**: `txt2img → ADetailer → upscale → video`
2. **Traditional Cleanup**: `txt2img → img2img → upscale → video`
3. **Fast ADetailer Only**: `txt2img → ADetailer → video`
4. **Skip All Processing**: `txt2img → video`
5. **Mixed Per Image**: Image 1 uses ADetailer, Image 2 uses img2img, Image 3 skips

When a stage is skipped, the pipeline automatically uses the output from the previous stage as input for the next stage. This allows for flexible workflows based on your quality vs. speed requirements.

#### 5. Video - Create Sequence
- **Tool:** FFmpeg command-line
- **Input:** Sequence of images
- **Output:** MP4 video file
- **Parameters:** FPS, bitrate, resolution

### Directory Structure

```
output/
├── run_YYYYMMDD_HHMMSS/
│   ├── txt2img/              # Initial generations
│   │   ├── image_001.png
│   │   └── image_002.png
│   ├── img2img/              # Refined images (optional)
│   │   ├── image_001.png
│   │   └── image_002.png
│   ├── upscaled/             # Enhanced images
│   │   ├── image_001_US2x.png
│   │   └── image_002_US2x.png
│   ├── video/                # Generated videos
│   │   └── sequence_001.mp4
│   └── manifests/            # JSON metadata
│       ├── image_001.json
│       ├── image_002.json
│       └── rollup_manifest.json
```

## GUI Architecture

### MVC Pattern

```
┌─────────────────────────────────────────────────────────────┐
│                      GUI Components                          │
├─────────────────────────────────────────────────────────────┤
│                                                              │
│  ┌──────────────────────────────────────────────────────┐  │
│  │                     View Layer                        │  │
│  │  ┌────────────┐  ┌────────────┐  ┌────────────┐     │  │
│  │  │   Main     │  │   Config   │  │   Prompt   │     │  │
│  │  │  Window    │  │   Panels   │  │   Editor   │     │  │
│  │  └────────────┘  └────────────┘  └────────────┘     │  │
│  └─────────────┬────────────────────────────────────────┘  │
│                │                                            │
│                ▼                                            │
│  ┌──────────────────────────────────────────────────────┐  │
│  │                  Controller Layer                     │  │
│  │  ┌────────────┐  ┌────────────┐  ┌────────────┐     │  │
│  │  │  Pipeline  │  │   Event    │  │   Cancel   │     │  │
│  │  │  Control   │  │  Handlers  │  │   Token    │     │  │
│  │  └────────────┘  └────────────┘  └────────────┘     │  │
│  └─────────────┬────────────────────────────────────────┘  │
│                │                                            │
│                ▼                                            │
│  ┌──────────────────────────────────────────────────────┐  │
│  │                    Model Layer                        │  │
│  │  ┌────────────┐  ┌────────────┐  ┌────────────┐     │  │
│  │  │   State    │  │   Config   │  │    Data    │     │  │
│  │  │  Machine   │  │   Store    │  │   Models   │     │  │
│  │  └────────────┘  └────────────┘  └────────────┘     │  │
│  └──────────────────────────────────────────────────────┘  │
│                                                              │
└─────────────────────────────────────────────────────────────┘
```

### Component Responsibilities

- **View:** UI widgets, layout, user interaction
- **Controller:** Event handling, pipeline coordination, threading
- **Model:** Application state, configuration, data persistence

### Advanced Prompt Editor

The Advanced Prompt Editor is a sophisticated tool for creating and validating prompt packs with real-time feedback and model discovery.

**Key Features:**
- **Format Support**: TXT (line-based with blank line separators) and TSV (tab-separated) formats
- **Live Validation**: Real-time syntax checking, embedding/LoRA discovery, and error reporting
- **Model Integration**: Auto-discovery of embeddings and LoRAs from WebUI installation
- **Template System**: Predefined templates for common prompt structures
- **Statistics**: Character counts, prompt counts, embedding/LoRA usage metrics

**Integration with Main GUI:**
```
Main Window
     │
     │ [✏️ Advanced Editor Button]
     │
     ▼
AdvancedPromptEditor.open_editor()
     │
     ├─[on_packs_changed]──▶ Refresh pack list
     │
     └─[on_validation]─────▶ Surface validation results to main log
```

**Validation Callback:**
When a pack is validated in the editor, the callback sends results to the main GUI:
- Error count and first 3 errors
- Warning count and first 2 warnings
- Statistics (prompt count, embeddings, LoRAs)

This provides visibility into pack quality without switching windows.

## State Management

### GUI State Machine

```
┌─────────────────────────────────────────────────────────────┐
│                   GUI State Machine                          │
└─────────────────────────────────────────────────────────────┘

                         ┌──────────┐
                         │   IDLE   │◀─────┐
                         └──────────┘      │
                              │            │
                     [Run]    │            │ [Complete]
                              │            │
                              ▼            │
                         ┌──────────┐      │
                    ┌───▶│ RUNNING  │──────┘
                    │    └──────────┘
                    │         │
          [Retry]   │         │ [Stop]
                    │         ▼
                    │    ┌──────────┐
                    │    │ STOPPING │
                    │    └──────────┘
                    │         │
                    │         │ [Cleanup]
                    │         ▼
                    │    ┌──────────┐
                    └────│  ERROR   │
                         └──────────┘
```

### State Transitions

1. **IDLE → RUNNING**
   - User clicks "Run Pipeline"
   - Validate configuration
   - Start worker thread
   - Enable Stop button

2. **RUNNING → STOPPING**
   - User clicks "Stop"
   - Set cancel token
   - Signal worker thread
   - Disable UI controls

3. **STOPPING → IDLE**
   - Worker thread detects cancel
   - Cleanup temporary files
   - Terminate subprocesses
   - Re-enable UI controls

4. **RUNNING → ERROR**
   - Exception in pipeline
   - Log error details
   - Show error dialog
   - Return to IDLE after acknowledgment

5. **RUNNING → IDLE**
   - Pipeline completes successfully
   - Save manifests and logs
   - Show completion dialog
   - Re-enable UI controls

## Cancellation Flow

### Cooperative Cancellation

```
┌─────────────────────────────────────────────────────────────┐
│                  Cancellation Mechanism                      │
└─────────────────────────────────────────────────────────────┘

  User Action              GUI Thread           Worker Thread
       │                        │                      │
       │ [Click Stop]           │                      │
       ├───────────────────────▶│                      │
       │                        │                      │
       │                        │ Set cancel_token     │
       │                        ├─────────────────────▶│
       │                        │                      │
       │                        │                      │ Check token
       │                        │                      ├──────────┐
       │                        │                      │          │
       │                        │                      │◀─────────┘
       │                        │                      │
       │                        │                      │ [Cancelled]
       │                        │                      │
       │                        │                      │ Cleanup:
       │                        │                      │ - Kill FFmpeg
       │                        │                      │ - Close API
       │                        │                      │ - Delete tmp
       │                        │                      │
       │                        │   Complete event     │
       │                        │◀─────────────────────┤
       │                        │                      │
       │ [Dialog: Stopped]      │                      │
       │◀───────────────────────┤                      │
       │                        │                      │
```

### Cancel Token Implementation

```python
class CancelToken:
    """Thread-safe cancellation token"""
    def __init__(self):
        self._cancelled = threading.Event()

    def cancel(self):
        """Request cancellation"""
        self._cancelled.set()

    def is_cancelled(self) -> bool:
        """Check if cancellation requested"""
        return self._cancelled.is_set()

    def check_cancelled(self):
        """Raise exception if cancelled"""
        if self._cancelled.is_set():
            raise CancellationError("Operation cancelled by user")
```

### Graceful Termination

1. **Set cancel token** - Signal to worker thread
2. **Check at safe points** - Between pipeline stages, API calls
3. **Cleanup resources** - Close connections, delete temp files
4. **Terminate subprocesses** - Kill FFmpeg, stop API requests
5. **Return to IDLE** - Re-enable UI, log cancellation

## Data Flow

### Configuration Flow

```
Preset File (JSON)
      │
      ▼
ConfigManager.load_preset()
      │
      ▼
GUI Form Population
      │
      ▼
User Edits Values
      │
      ▼
GUI Form Extraction
      │
      ▼
Pack-Specific Overrides (Optional)
      │
      ▼
Merged Configuration
      │
      ▼
Pipeline Executor
      │
      ▼
API Request Payload
```

### Image Metadata Flow

```
Pipeline Execution
      │
      ▼
Generate Image
      │
      ▼
Save Image File
      │
      ├─────────────────────────────┐
      │                             │
      ▼                             ▼
Save JSON Manifest           Update CSV Summary
(per image)                   (rollup)
      │                             │
      │                             │
      └─────────────┬───────────────┘
                    │
                    ▼
           Complete Manifest
        (rollup_manifest.json)
```

## Configuration System

### Configuration Hierarchy

```
1. Default Config (hardcoded)
      │
      ▼
2. Preset File (presets/default.json)
      │
      ▼
3. Pack Overrides (pack-specific settings)
      │
      ▼
4. Runtime Parameters (CLI/GUI overrides)
      │
      ▼
5. Final Merged Config
```

### Configuration Structure

```json
{
  "txt2img": {
    "steps": 30,
    "sampler_name": "DPM++ 2M",
    "scheduler": "Karras",
    "cfg_scale": 7.0,
    "width": 1024,
    "height": 1024,
    "enable_hr": true,
    "hr_upscaler": "R-ESRGAN 4x+",
    "hr_scale": 1.5
  },
  "img2img": {
    "denoising_strength": 0.35,
    "steps": 20
  },
  "upscale": {
    "upscaler": "R-ESRGAN 4x+",
    "upscaling_resize": 2.0
  },
  "video": {
    "fps": 30,
    "crf": 18,
    "max_width": 1920,
    "max_height": 1080
  },
  "api": {
    "base_url": "http://127.0.0.1:7860",
    "timeout": 300
  }
}
```

## Error Handling

### Layered Error Handling

1. **API Layer** - Connection errors, timeouts, malformed responses
2. **Pipeline Layer** - Stage failures, resource unavailability
3. **GUI Layer** - User input validation, display errors
4. **Logging Layer** - All errors logged with context

### Recovery Strategies

- **API Timeout** - Retry with exponential backoff
- **API Unavailable** - Prompt user to start WebUI
- **Invalid Config** - Fall back to defaults, warn user
- **Pipeline Failure** - Log error, save partial results, continue if possible
- **Out of Memory** - Reduce batch size, suggest lower resolution

---

## Future Enhancements

- **Async Pipeline** - Non-blocking execution with progress streaming
- **Job Queue** - Multiple concurrent pipelines
- **Plugin System** - Extensible stage architecture
- **Cloud Integration** - Upload results to storage services
- **Model Management** - Download and organize models from GUI

---

Last Updated: 2024-11-02
