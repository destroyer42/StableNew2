# PR-VIDEO-001: Core AnimateDiff Stage Implementation

> Stale draft. Do not execute this PR spec directly.
>
> It predates the current-state discovery in
> [`docs/D-VIDEO-004-AnimateDiff-Current-State-Discovery.md`](./D-VIDEO-004-AnimateDiff-Current-State-Discovery.md)
> and is superseded for Phase 1 planning by
> [`docs/OpenSpec/PR-CORE-VIDEO-004-AnimateDiff-Phase-1-Contract-Gated.md`](./OpenSpec/PR-CORE-VIDEO-004-AnimateDiff-Phase-1-Contract-Gated.md).
> Retained only as historical planning context.

**Related Discovery**: D-VIDEO-001  
**Architecture Version**: v2.6  
**PR Date**: 2026-01-11  
**Dependencies**: None  
**Sequence**: Phase 1 of 3 (PR-VIDEO-001 → PR-VIDEO-002 → PR-VIDEO-003)

---

# EXECUTOR ACKNOWLEDGEMENT & COMPLIANCE BLOCK (MANDATORY)

## READ FIRST — EXECUTION CONTRACT ACKNOWLEDGEMENT

You are acting as an **Executor** for the StableNew v2.6 codebase.

By proceeding, you **explicitly acknowledge** that:

1. You have read and understand the attached document  
   **`StableNew_v2.6_Canonical_Execution_Contract.md`** *(via .github/copilot-instructions.md)*

2. You agree that this document is the **single authoritative source of truth** for:
   - Architecture
   - NJR-only execution
   - Stage chain extension
   - Pipeline execution flow

3. This PR **MUST**:
   - Add ANIMATEDIFF stage type to stage models
   - Implement AnimateDiff WebUI API integration
   - Extend stage sequencer for animatediff ordering
   - Implement video frame assembly
   - Maintain NJR-only execution path

---

## ABSOLUTE EXECUTION RULES (NON‑NEGOTIABLE)

### 1. Scope Completion
- You MUST implement **100% of the PR scope**
- You MUST create **every file listed**
- You MUST modify **every file listed**
- Partial implementation is **explicitly forbidden**

### 2. Stage Type Extension Enforcement
You MUST:
- Add StageType.ANIMATEDIFF to stage_models.py
- Update stage sequencer canonical ordering
- Implement run_animatediff_stage() in executor.py
- Support animatediff in pipeline_runner.py
- Validate animatediff stage placement

### 3. Video Assembly Enforcement
You MUST:
- Implement frame-to-video assembly in VideoCreator
- Support ffmpeg encoding (H.264/MP4)
- Handle frame sequence cleanup
- Store video path in stage output

### 4. Proof Is Mandatory
For **every MUST**, you MUST provide:
- Full `git diff`
- pytest commands **with captured output**
- Grep output for ANIMATEDIFF references
- Exact file + line references

### 5. Tests Are Not Optional
You MUST:
- Run all tests specified in TEST PLAN
- Show command + full output
- Fix failures before proceeding

---

## ACKNOWLEDGEMENT STATEMENT (REQUIRED)

By continuing execution, you acknowledge:

> "I will add AnimateDiff stage type to stage models, implement WebUI API integration with  
> alwayson_scripts payload structure, extend stage sequencer for canonical ordering, implement  
> frame-to-video assembly with VideoCreator, and ensure NJR-only execution path. I will provide  
> verifiable proof of all changes."

---

# PR METADATA

## PR ID
`PR-VIDEO-001-Core-AnimateDiff-Stage`

## Related Canonical Sections
- **D-VIDEO-001 §6**: Recommended Approach B (Separate AnimateDiff Stage)
- **D-VIDEO-001 §6.1**: Stage Configuration Model
- **D-VIDEO-001 §6.2**: Pipeline Execution Flow
- **D-VIDEO-001 §6.3**: WebUI API Integration
- **Architecture v2.6 §3.2**: NJR-only execution
- **Architecture v2.6 §5**: Stage chain in NormalizedJobRecord

---

# INTENT (MANDATORY)

## What This PR Does

This PR implements **Phase 1** of AnimateDiff integration, adding a new `animatediff` stage type to the StableNew v2.6 pipeline. AnimateDiff enables video generation from text prompts by injecting motion modules into the Stable Diffusion generation process.

**Key Capabilities Added**:
1. ANIMATEDIFF stage type in stage models enum
2. Stage sequencer support for animatediff ordering
3. AnimateDiff WebUI API payload construction
4. run_animatediff_stage() executor implementation
5. VideoCreator frame-to-MP4 assembly
6. NJR stage chain support for animatediff

**User Value**:
- Generate animated video clips from static prompts
- Test motion parameters (motion module, frame count, FPS)
- Create animated concept previews
- No GUI required (CLI/API usage only in Phase 1)

---

# SCOPE

## What This PR Changes

### 1. Stage Type Extension
- Add `StageType.ANIMATEDIFF = "animatediff"` to stage models
- Deprecated ordering note: this document predates the corrected canonical
  stage chain. Current order is
  `txt2img → img2img → adetailer → upscale → animatediff`.
- Update `is_generation_stage()` to exclude animatediff

### 2. Stage Sequencer Extension
- Add animatediff to canonical stage ordering
- Validate: animatediff requires at least one generation stage
- Support animatediff placement after any stage
- Build animatediff stage execution config

### 3. Executor Implementation
- Implement `Pipeline.run_animatediff_stage()`
- Build AnimateDiff WebUI API payload
- Handle frame sequence from WebUI response
- Call VideoCreator for frame assembly
- Return video path in stage metadata

### 4. Video Assembly
- Extend VideoCreator with `create_from_frames()` method
- Support ffmpeg H.264/MP4 encoding
- Handle frame cleanup after assembly
- Validate ffmpeg availability

### 5. Pipeline Runner Integration
- Add animatediff stage dispatch in `run_njr()`
- Pass frames from generation stage to animatediff
- Track video output in stage results
- Update history metadata with video path

---

# WHAT THIS PR DOES NOT CHANGE

## Out of Scope

### GUI (Deferred to PR-VIDEO-002)
- ❌ AnimateDiff stage card UI
- ❌ Motion module dropdown
- ❌ Pipeline panel integration
- ❌ Preset serialization UI

### Learning Integration (Deferred to PR-VIDEO-003)
- ❌ Video variable metadata
- ❌ Learning experiment video variants
- ❌ Video thumbnail display
- ❌ Video rating UI

### Advanced Features (Future)
- ❌ ControlNet + AnimateDiff integration
- ❌ Img2Vid mode (existing image → animation)
- ❌ Deforum keyframe animation
- ❌ Audio track overlay

### Existing Stage Types
- ❌ No changes to txt2img, img2img, upscale, adetailer logic
- ❌ No changes to refiner or hires metadata
- ❌ No changes to existing stage sequencer validation

---

# ALLOWED FILES

## Files to Create

### Video Stage Models
```
src/pipeline/video_stage_config.py          # AnimateDiff stage configuration dataclass
```

### Tests
```
tests/pipeline/test_animatediff_stage.py    # AnimateDiff stage unit tests
tests/pipeline/test_video_creator_v2.py     # VideoCreator frame assembly tests
```

## Files to Modify

### Stage Models
```
src/pipeline/stage_models.py                # Add StageType.ANIMATEDIFF
src/pipeline/job_models_v2.py               # Update stage chain validation
```

### Stage Sequencer
```
src/pipeline/stage_sequencer.py             # Add animatediff to canonical ordering
```

### Executor
```
src/pipeline/executor.py                    # Implement run_animatediff_stage()
```

### Pipeline Runner
```
src/pipeline/pipeline_runner.py             # Add animatediff stage dispatch
```

### Video Assembly
```
src/pipeline/video.py                       # Extend VideoCreator with create_from_frames()
```

### __init__ Exports
```
src/pipeline/__init__.py                    # Export video stage types
```

---

# FORBIDDEN FILES

## Files You MUST NOT Touch

### GUI Layer (PR-VIDEO-002 Scope)
```
src/gui/stage_cards_v2/                     # All stage card files
src/gui/views/pipeline_panel_v2.py          # Pipeline tab
src/gui/controllers/preset_controller.py    # Preset serialization
```

### Learning Layer (PR-VIDEO-003 Scope)
```
src/learning/                               # All learning files
src/gui/controllers/learning_controller.py  # Learning controller
src/gui/views/experiment_design_panel.py    # Experiment UI
```

### Core Architecture (Protected)
```
src/controller/                             # All controller files
src/queue/                                  # Queue system
src/utils/app_state_v2.py                   # App state management
```

---

# IMPLEMENTATION STEPS

## Step 1: Add AnimateDiff Stage Type

### File: `src/pipeline/stage_models.py`

**Modify StageType enum:**
```python
class StageType(str, Enum):
    """Canonical pipeline stage types.

    Ordering: TXT2IMG → IMG2IMG → UPSCALE → ADETAILER → ANIMATEDIFF

    Note: Refiner and Hires are metadata on generation stages (TXT2IMG, IMG2IMG),
    not separate stage types.
    """

    TXT2IMG = "txt2img"
    IMG2IMG = "img2img"
    UPSCALE = "upscale"
    ADETAILER = "adetailer"
    ANIMATEDIFF = "animatediff"  # NEW: Video generation stage

    def is_generation_stage(self) -> bool:
        """Return True if this is a generation stage (txt2img or img2img)."""
        return self in (StageType.TXT2IMG, StageType.IMG2IMG)
    
    def is_video_stage(self) -> bool:
        """Return True if this is a video generation stage."""
        return self == StageType.ANIMATEDIFF
```

**Expected Diff:**
- Add ANIMATEDIFF = "animatediff" to enum
- Add is_video_stage() method
- Update docstring with new ordering

---

## Step 2: Create AnimateDiff Stage Configuration

### File: `src/pipeline/video_stage_config.py` (NEW)

**Create configuration dataclass:**
```python
"""AnimateDiff stage configuration models."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

AnimateDiffMode = Literal["txt2img", "img2img"]
InterpolationMethod = Literal["Off", "FILM", "RIFE"]
ClosedLoopMode = Literal["N", "R+", "R-", "A"]


@dataclass
class AnimateDiffConfig:
    """Configuration for AnimateDiff video generation stage.
    
    This configuration is stored in StageConfig.extra dict for animatediff stages.
    
    Attributes:
        motion_module: Motion module filename (e.g., "mm_sd_v15_v2.ckpt")
        video_length: Number of frames to generate (8-24 typical)
        fps: Target framerate (8-30)
        mode: Generation mode (txt2img=new generation, img2img=animate existing)
        context_batch_size: Frames processed together (affects VRAM)
        stride: Frame sampling stride
        overlap: Frame overlap for smooth transitions
        closed_loop: Loop mode for seamless looping
        interp: Interpolation method for frame smoothing
        interp_x: Interpolation multiplier
        output_format: Video container format
        codec: Video codec (default: libx264)
    """
    
    motion_module: str = "mm_sd_v15_v2.ckpt"
    video_length: int = 16
    fps: int = 12
    mode: AnimateDiffMode = "txt2img"
    context_batch_size: int = 16
    stride: int = 1
    overlap: int = 8
    closed_loop: ClosedLoopMode = "R+"
    interp: InterpolationMethod = "Off"
    interp_x: int = 10
    output_format: str = "MP4"
    codec: str = "libx264"
    
    def to_webui_payload(self) -> dict[str, Any]:
        """Convert to AnimateDiff extension API payload structure."""
        return {
            "enable": True,
            "video_length": self.video_length,
            "fps": self.fps,
            "loop_number": 0,
            "closed_loop": self.closed_loop,
            "batch_size": 1,  # MUST be 1 for AnimateDiff
            "stride": self.stride,
            "overlap": self.overlap,
            "format": ["PNG"],  # Frame format (always PNG for assembly)
            "interp": self.interp,
            "interp_x": self.interp_x,
            "model": self.motion_module,
        }
    
    @classmethod
    def from_stage_config_extra(cls, extra: dict[str, Any]) -> AnimateDiffConfig:
        """Extract AnimateDiffConfig from StageConfig.extra dict."""
        return cls(
            motion_module=extra.get("motion_module", "mm_sd_v15_v2.ckpt"),
            video_length=int(extra.get("video_length", 16)),
            fps=int(extra.get("fps", 12)),
            mode=extra.get("mode", "txt2img"),
            context_batch_size=int(extra.get("context_batch_size", 16)),
            stride=int(extra.get("stride", 1)),
            overlap=int(extra.get("overlap", 8)),
            closed_loop=extra.get("closed_loop", "R+"),
            interp=extra.get("interp", "Off"),
            interp_x=int(extra.get("interp_x", 10)),
            output_format=extra.get("output_format", "MP4"),
            codec=extra.get("codec", "libx264"),
        )


def build_animatediff_payload(
    base_config: dict[str, Any],
    animatediff_config: AnimateDiffConfig,
    prompt: str,
    negative_prompt: str,
) -> dict[str, Any]:
    """Build complete WebUI API payload with AnimateDiff extension.
    
    Args:
        base_config: Base generation config (model, sampler, steps, etc.)
        animatediff_config: AnimateDiff-specific configuration
        prompt: Positive prompt text
        negative_prompt: Negative prompt text
    
    Returns:
        Complete txt2img/img2img payload with alwayson_scripts
    """
    payload = {
        "prompt": prompt,
        "negative_prompt": negative_prompt,
        "steps": base_config.get("steps", 20),
        "cfg_scale": base_config.get("cfg_scale", 7.0),
        "sampler_name": base_config.get("sampler_name", "Euler a"),
        "width": base_config.get("width", 512),
        "height": base_config.get("height", 512),
        "seed": base_config.get("seed", -1),
        "batch_size": 1,  # MUST be 1 for AnimateDiff
        "n_iter": 1,
        "override_settings": {
            "sd_model_checkpoint": base_config.get("model", ""),
            "sd_vae": base_config.get("vae", "Automatic"),
        },
        "alwayson_scripts": {
            "animatediff": {
                "args": [animatediff_config.to_webui_payload()]
            }
        }
    }
    
    return payload
```

**Expected Diff:**
- New file with AnimateDiffConfig dataclass
- to_webui_payload() method for API conversion
- from_stage_config_extra() factory method
- build_animatediff_payload() helper function

---

## Step 3: Extend Stage Sequencer

### File: `src/pipeline/stage_sequencer.py`

**Add animatediff to build_stage_execution_plan():**

Locate the section after adetailer stage construction (around line 180-200):

```python
    if ad_enabled:
        if not generative_enabled and not up_enabled:
            raise InvalidStagePlanError(
                "ADetailer requires at least one generation stage (txt2img or img2img)."
            )
        payload = _stage_payload(config, "adetailer")
        metadata = _build_stage_metadata(config, payload, stage="adetailer")
        stage = StageExecution(
            stage_type="adetailer",
            config=StageConfig(enabled=ad_enabled, payload=payload, metadata=metadata),
            order_index=order,
            requires_input_image=True,
            produces_output_image=True,
        )
        stages.append(stage)
        order += 1

    # NEW: AnimateDiff stage (video generation)
    animatediff_enabled = pipeline_flags.get("animatediff_enabled", False) or _extract_enabled(
        config, "animatediff", False
    )
    if animatediff_enabled:
        if not generative_enabled:
            raise InvalidStagePlanError(
                "AnimateDiff requires at least one generation stage (txt2img or img2img)."
            )
        payload = _stage_payload(config, "animatediff")
        metadata = _build_stage_metadata(config, payload, stage="animatediff")
        stage = StageExecution(
            stage_type="animatediff",
            config=StageConfig(enabled=animatediff_enabled, payload=payload, metadata=metadata),
            order_index=order,
            requires_input_image=False,  # AnimateDiff generates its own frames
            produces_output_image=True,  # Produces video file (treated as "image" output)
        )
        stages.append(stage)
        order += 1

    if not stages:
        raise InvalidStagePlanError("No stages enabled in pipeline configuration.")

    return StageExecutionPlan(stages=stages)
```

**Expected Diff:**
- Add animatediff stage after adetailer
- Validate: animatediff requires generation stage
- Set requires_input_image=False (generates from scratch or uses config)
- Update order index

---

## Step 4: Implement AnimateDiff Executor

### File: `src/pipeline/executor.py`

**Add run_animatediff_stage() method:**

Add after `run_adetailer_stage()` (around line 3050):

```python
    def run_animatediff_stage(
        self,
        config: dict[str, Any],
        output_dir: Path,
        image_name: str,
        prompt: str | None = None,
        negative_prompt: str | None = None,
        cancel_token=None,
    ) -> dict[str, Any] | None:
        """Run AnimateDiff video generation stage.
        
        AnimateDiff generates multiple frames with temporal coherence and assembles
        them into a video file using ffmpeg.
        
        Args:
            config: AnimateDiff stage configuration dict
            output_dir: Directory for output video
            image_name: Base name for video file
            prompt: Positive prompt (required for txt2img mode)
            negative_prompt: Negative prompt
            cancel_token: Cancellation token
        
        Returns:
            Stage metadata dict with video path, or None on failure
        """
        from src.pipeline.video import VideoCreator
        from src.pipeline.video_stage_config import (
            AnimateDiffConfig,
            build_animatediff_payload,
        )
        
        logger.info("🎬 [ANIMATEDIFF] Starting AnimateDiff video generation stage")
        
        # Create output directory
        output_dir.mkdir(parents=True, exist_ok=True)
        frames_dir = output_dir / f"{image_name}_frames"
        frames_dir.mkdir(parents=True, exist_ok=True)
        
        # Extract AnimateDiff configuration
        animatediff_cfg = AnimateDiffConfig.from_stage_config_extra(config)
        logger.info(
            f"🎬 [ANIMATEDIFF] Config: motion_module={animatediff_cfg.motion_module}, "
            f"frames={animatediff_cfg.video_length}, fps={animatediff_cfg.fps}"
        )
        
        # Build WebUI API payload
        base_config = config.get("pipeline", {}) or {}
        payload = build_animatediff_payload(
            base_config=base_config,
            animatediff_config=animatediff_cfg,
            prompt=prompt or "",
            negative_prompt=negative_prompt or "",
        )
        
        # Call WebUI txt2img with AnimateDiff extension
        logger.info("🎬 [ANIMATEDIFF] Calling WebUI API with AnimateDiff params")
        try:
            response = self.client.txt2img(**payload)
        except Exception as exc:
            logger.error(f"❌ [ANIMATEDIFF] WebUI API call failed: {exc}")
            return None
        
        if not response or "images" not in response:
            logger.error("❌ [ANIMATEDIFF] No frames returned from WebUI")
            return None
        
        frames_b64 = response["images"]
        if len(frames_b64) < 2:
            logger.error(f"❌ [ANIMATEDIFF] Insufficient frames: got {len(frames_b64)}, expected {animatediff_cfg.video_length}")
            return None
        
        logger.info(f"🎬 [ANIMATEDIFF] Received {len(frames_b64)} frames from WebUI")
        
        # Save frames to disk
        frame_paths = []
        for idx, frame_b64 in enumerate(frames_b64):
            frame_path = frames_dir / f"frame_{idx:05d}.png"
            try:
                self._save_image_from_base64(frame_b64, frame_path)
                frame_paths.append(frame_path)
            except Exception as exc:
                logger.error(f"❌ [ANIMATEDIFF] Failed to save frame {idx}: {exc}")
                return None
        
        logger.info(f"🎬 [ANIMATEDIFF] Saved {len(frame_paths)} frames to {frames_dir}")
        
        # Assemble frames into video
        video_path = output_dir / f"{image_name}.mp4"
        video_creator = VideoCreator()
        
        if not video_creator.ffmpeg_available:
            logger.error("❌ [ANIMATEDIFF] ffmpeg not available, cannot create video")
            return None
        
        logger.info(f"🎬 [ANIMATEDIFF] Assembling {len(frame_paths)} frames into video")
        success = video_creator.create_from_frames(
            frame_paths=frame_paths,
            output_path=video_path,
            fps=animatediff_cfg.fps,
            codec=animatediff_cfg.codec,
        )
        
        if not success or not video_path.exists():
            logger.error(f"❌ [ANIMATEDIFF] Video assembly failed")
            return None
        
        logger.info(f"✅ [ANIMATEDIFF] Video created: {video_path}")
        
        # Clean up frame directory (optional, keep for debugging)
        # shutil.rmtree(frames_dir, ignore_errors=True)
        
        # Return stage metadata
        return {
            "path": str(video_path),
            "name": video_path.name,
            "stage": "animatediff",
            "frame_count": len(frame_paths),
            "fps": animatediff_cfg.fps,
            "duration_seconds": len(frame_paths) / animatediff_cfg.fps,
            "motion_module": animatediff_cfg.motion_module,
            "frames_dir": str(frames_dir),
            "final_prompt": prompt or "",
            "final_negative_prompt": negative_prompt or "",
        }
```

**Expected Diff:**
- New run_animatediff_stage() method (100+ lines)
- AnimateDiff config extraction
- WebUI API call with alwayson_scripts
- Frame saving loop
- VideoCreator.create_from_frames() call
- Return video metadata dict

---

## Step 5: Extend VideoCreator

### File: `src/pipeline/video.py`

**Add create_from_frames() method:**

Locate the VideoCreator class and add method after existing methods:

```python
    def create_from_frames(
        self,
        frame_paths: list[Path],
        output_path: Path,
        fps: int = 12,
        codec: str = "libx264",
        crf: int = 23,
    ) -> bool:
        """Create video from sequence of frame images.
        
        Args:
            frame_paths: List of paths to frame images (in order)
            output_path: Path for output video file
            fps: Target framerate
            codec: Video codec (libx264, libx265, etc.)
            crf: Constant Rate Factor (quality, 0-51, lower=better)
        
        Returns:
            True if video created successfully, False otherwise
        """
        if not self.ffmpeg_available:
            logger.error("❌ [VIDEO] ffmpeg not available")
            return False
        
        if not frame_paths:
            logger.error("❌ [VIDEO] No frames provided")
            return False
        
        # Validate all frames exist
        missing = [p for p in frame_paths if not p.exists()]
        if missing:
            logger.error(f"❌ [VIDEO] Missing {len(missing)} frame files")
            return False
        
        # Create temporary file listing all frames (for ffmpeg concat)
        frames_dir = frame_paths[0].parent
        concat_file = frames_dir / "frames_list.txt"
        
        try:
            with open(concat_file, "w") as f:
                for frame_path in frame_paths:
                    # Write relative path for portability
                    f.write(f"file '{frame_path.name}'\n")
                    f.write(f"duration {1.0/fps}\n")
                # Last frame needs no duration (ffmpeg quirk)
                f.write(f"file '{frame_paths[-1].name}'\n")
            
            # Build ffmpeg command
            # -f concat: concatenate input files
            # -safe 0: allow absolute paths
            # -i: input concat file
            # -c:v: video codec
            # -crf: quality (23 = good balance)
            # -pix_fmt yuv420p: compatibility with media players
            # -movflags +faststart: web streaming optimization
            cmd = [
                "ffmpeg",
                "-y",  # Overwrite output
                "-f", "concat",
                "-safe", "0",
                "-i", str(concat_file),
                "-c:v", codec,
                "-crf", str(crf),
                "-pix_fmt", "yuv420p",
                "-movflags", "+faststart",
                str(output_path),
            ]
            
            logger.info(f"🎬 [VIDEO] Running ffmpeg: {' '.join(cmd)}")
            
            result = subprocess.run(
                cmd,
                cwd=frames_dir,
                capture_output=True,
                text=True,
                check=False,
            )
            
            if result.returncode != 0:
                logger.error(f"❌ [VIDEO] ffmpeg failed: {result.stderr}")
                return False
            
            if not output_path.exists():
                logger.error(f"❌ [VIDEO] Output file not created: {output_path}")
                return False
            
            file_size_mb = output_path.stat().st_size / (1024 * 1024)
            logger.info(f"✅ [VIDEO] Created video: {output_path.name} ({file_size_mb:.2f} MB)")
            return True
            
        except Exception as exc:
            logger.error(f"❌ [VIDEO] Frame assembly failed: {exc}")
            return False
        finally:
            # Clean up concat file
            if concat_file.exists():
                concat_file.unlink()
```

**Expected Diff:**
- New create_from_frames() method (80+ lines)
- ffmpeg concat demuxer usage
- Frame list file creation
- Video codec and quality settings
- Error handling and validation

---

## Step 6: Update Pipeline Runner

### File: `src/pipeline/pipeline_runner.py`

**Add animatediff stage dispatch in run_njr():**

Locate the stage dispatch section (around line 240-300) and add after adetailer:

```python
                elif stage.stage_name == "animatediff":
                    logger.info("🎬 [BATCH_PIPELINE] Starting animatediff stage")
                    
                    # AnimateDiff generates from scratch (doesn't use previous stage images)
                    # Build payload from stage config
                    stage_payload = getattr(stage, "payload", {}) or {}
                    
                    # Merge with NJR config
                    animatediff_config = {**njr.config, **stage_payload}
                    
                    # Call executor
                    result = self.executor.run_animatediff_stage(
                        config=animatediff_config,
                        output_dir=output_dir,
                        image_name=f"{stage.stage_name}_p{prompt_row:02d}_{stage.variant_id:02d}",
                        prompt=prompt,
                        negative_prompt=negative_prompt,
                        cancel_token=cancel_token,
                    )
                    
                    if result and "path" in result:
                        # Video output (no multi-image batch)
                        current_stage_paths = [result["path"]]
                        logger.info(f"🎬 [BATCH_PIPELINE] animatediff produced video: {result['name']}")
                    else:
                        current_stage_paths = []
                        logger.warning("⚠️  [BATCH_PIPELINE] animatediff failed")
                    
                    variants.append(result)
                    last_result = result
```

**Expected Diff:**
- Add animatediff branch in stage dispatch
- Merge stage payload with NJR config
- Call run_animatediff_stage()
- Handle video output (single file)
- Update current_stage_paths

---

## Step 7: Update Job Models Validation

### File: `src/pipeline/job_models_v2.py`

**Update stage chain validation:**

Locate the `_STAGE_DISPLAY_MAP` dict (around line 18):

```python
_STAGE_DISPLAY_MAP: dict[str, str] = {
    "txt2img": "txt2img",
    "img2img": "img2img",
    "upscale": "upscale",
    "adetailer": "ADetailer",
    "animatediff": "AnimateDiff",  # NEW
}
```

**Expected Diff:**
- Add "animatediff": "AnimateDiff" to display map

---

## Step 8: Update Pipeline __init__ Exports

### File: `src/pipeline/__init__.py`

**Add video stage imports:**

```python
"""Pipeline module"""

from .executor import Pipeline
from .pipeline_runner import PipelineRunner, PipelineRunResult
from .stage_sequencer import (
    StageConfig,
    StageExecution,
    StageExecutionPlan,
    StageTypeEnum,
    build_stage_execution_plan,
)
from .video import VideoCreator
from .video_stage_config import AnimateDiffConfig, build_animatediff_payload

__all__ = [
    "Pipeline",
    "VideoCreator",
    "PipelineRunner",
    "PipelineRunResult",
    "StageConfig",
    "StageExecution",
    "StageExecutionPlan",
    "StageTypeEnum",
    "build_stage_execution_plan",
    "AnimateDiffConfig",
    "build_animatediff_payload",
]
```

**Expected Diff:**
- Add video_stage_config imports
- Add to __all__ exports

---

# TEST PLAN

## Unit Tests

### Test 1: StageType.ANIMATEDIFF Enum

**File**: `tests/pipeline/test_animatediff_stage.py`

```python
def test_animatediff_stage_type_exists():
    """Verify ANIMATEDIFF stage type is defined."""
    from src.pipeline.stage_models import StageType
    
    assert hasattr(StageType, "ANIMATEDIFF")
    assert StageType.ANIMATEDIFF == "animatediff"
    assert not StageType.ANIMATEDIFF.is_generation_stage()
    assert StageType.ANIMATEDIFF.is_video_stage()
```

---

### Test 2: AnimateDiff Configuration

**File**: `tests/pipeline/test_animatediff_stage.py`

```python
def test_animatediff_config_defaults():
    """Verify AnimateDiffConfig defaults."""
    from src.pipeline.video_stage_config import AnimateDiffConfig
    
    cfg = AnimateDiffConfig()
    assert cfg.motion_module == "mm_sd_v15_v2.ckpt"
    assert cfg.video_length == 16
    assert cfg.fps == 12
    assert cfg.mode == "txt2img"


def test_animatediff_config_to_webui_payload():
    """Verify WebUI payload conversion."""
    from src.pipeline.video_stage_config import AnimateDiffConfig
    
    cfg = AnimateDiffConfig(
        motion_module="test_motion.ckpt",
        video_length=20,
        fps=24,
    )
    payload = cfg.to_webui_payload()
    
    assert payload["enable"] is True
    assert payload["video_length"] == 20
    assert payload["fps"] == 24
    assert payload["model"] == "test_motion.ckpt"
    assert payload["batch_size"] == 1  # MUST be 1
```

---

### Test 3: Stage Sequencer with AnimateDiff

**File**: `tests/pipeline/test_stage_sequencer_v2.py`

```python
def test_build_plan_with_animatediff():
    """Verify animatediff stage in execution plan."""
    from src.pipeline.stage_sequencer import build_stage_execution_plan
    
    config = {
        "pipeline": {
            "txt2img_enabled": True,
            "animatediff_enabled": True,
        },
        "txt2img": {"steps": 20, "model": "test.safetensors"},
        "animatediff": {"motion_module": "mm_sd_v15_v2.ckpt"},
    }
    
    plan = build_stage_execution_plan(config)
    assert len(plan.stages) == 2
    assert plan.stages[0].stage_type == "txt2img"
    assert plan.stages[1].stage_type == "animatediff"


def test_animatediff_requires_generation_stage():
    """Verify animatediff validation."""
    from src.pipeline.stage_sequencer import build_stage_execution_plan
    from src.pipeline.stage_models import InvalidStagePlanError
    import pytest
    
    config = {
        "pipeline": {
            "txt2img_enabled": False,
            "img2img_enabled": False,
            "animatediff_enabled": True,
        },
        "animatediff": {},
    }
    
    with pytest.raises(InvalidStagePlanError, match="requires at least one generation stage"):
        build_stage_execution_plan(config)
```

---

### Test 4: VideoCreator Frame Assembly

**File**: `tests/pipeline/test_video_creator_v2.py`

```python
def test_create_from_frames_success(tmp_path):
    """Verify video creation from frames."""
    from src.pipeline.video import VideoCreator
    from PIL import Image
    
    # Create test frames
    frames_dir = tmp_path / "frames"
    frames_dir.mkdir()
    
    frame_paths = []
    for i in range(8):
        frame_path = frames_dir / f"frame_{i:05d}.png"
        img = Image.new("RGB", (512, 512), color=(i * 30, 100, 200))
        img.save(frame_path)
        frame_paths.append(frame_path)
    
    # Create video
    output_path = tmp_path / "test_video.mp4"
    creator = VideoCreator()
    
    if not creator.ffmpeg_available:
        pytest.skip("ffmpeg not available")
    
    success = creator.create_from_frames(
        frame_paths=frame_paths,
        output_path=output_path,
        fps=12,
    )
    
    assert success is True
    assert output_path.exists()
    assert output_path.stat().st_size > 0


def test_create_from_frames_missing_frames(tmp_path):
    """Verify error handling for missing frames."""
    from src.pipeline.video import VideoCreator
    
    creator = VideoCreator()
    frame_paths = [tmp_path / "nonexistent.png"]
    output_path = tmp_path / "video.mp4"
    
    success = creator.create_from_frames(
        frame_paths=frame_paths,
        output_path=output_path,
        fps=12,
    )
    
    assert success is False
```

---

## Integration Tests

### Test 5: End-to-End AnimateDiff Stage

**File**: `tests/pipeline/test_animatediff_integration.py`

```python
def test_animatediff_stage_execution(tmp_path, mock_webui_client):
    """Verify full animatediff stage execution."""
    from src.pipeline.executor import Pipeline
    from pathlib import Path
    
    # Mock WebUI to return 16 frames
    mock_response = {
        "images": ["base64_frame_data"] * 16,
    }
    mock_webui_client.txt2img.return_value = mock_response
    
    executor = Pipeline(client=mock_webui_client)
    
    config = {
        "motion_module": "mm_sd_v15_v2.ckpt",
        "video_length": 16,
        "fps": 12,
        "pipeline": {
            "model": "test_model.safetensors",
            "steps": 20,
            "cfg_scale": 7.0,
        }
    }
    
    result = executor.run_animatediff_stage(
        config=config,
        output_dir=tmp_path,
        image_name="test_animation",
        prompt="a cat walking",
        negative_prompt="static",
    )
    
    # Verify result structure
    assert result is not None
    assert "path" in result
    assert "frame_count" in result
    assert result["frame_count"] == 16
    assert result["fps"] == 12
    assert result["motion_module"] == "mm_sd_v15_v2.ckpt"
    
    # Verify video file created (mocked in this test)
    # In real execution, check Path(result["path"]).exists()
```

---

## Manual Testing (No GUI)

### Test 6: CLI Video Generation

**Create test script**: `scripts/test_animatediff_cli.py`

```python
"""CLI test for AnimateDiff stage."""

from pathlib import Path
from src.pipeline.job_models_v2 import NormalizedJobRecord, StageConfig
from src.pipeline.pipeline_runner import PipelineRunner
from src.pipeline.executor import Pipeline
from src.api.webui_client import WebUIClient

def test_animatediff_cli():
    """Generate video using AnimateDiff stage."""
    
    # Create NJR with animatediff stage
    njr = NormalizedJobRecord(
        job_id="test-animatediff",
        prompt_pack_id="cli-test",
        positive_prompt="a cat walking through a garden, high quality",
        negative_prompt="blurry, static, low quality",
        stage_chain=[
            StageConfig(
                stage_type="txt2img",
                enabled=True,
                steps=20,
                cfg_scale=7.0,
                sampler_name="Euler a",
                model="realisticVisionV60B1_v51VAE.safetensors",
            ),
            StageConfig(
                stage_type="animatediff",
                enabled=True,
                extra={
                    "motion_module": "mm_sd_v15_v2.ckpt",
                    "video_length": 16,
                    "fps": 12,
                    "mode": "txt2img",
                }
            )
        ],
        config={
            "pipeline": {
                "txt2img_enabled": True,
                "animatediff_enabled": True,
            },
            "txt2img": {
                "width": 512,
                "height": 512,
            },
        },
    )
    
    # Execute
    client = WebUIClient(base_url="http://127.0.0.1:7860")
    executor = Pipeline(client=client)
    runner = PipelineRunner(executor=executor, runs_base_dir=Path("output/test_runs"))
    
    result = runner.run_njr(njr)
    
    print(f"Success: {result.success}")
    print(f"Final paths: {result.final_image_paths}")
    print(f"Video path: {result.final_image_paths[0] if result.final_image_paths else 'NONE'}")

if __name__ == "__main__":
    test_animatediff_cli()
```

**Run command:**
```bash
python scripts/test_animatediff_cli.py
```

**Expected output:**
```
🎬 [ANIMATEDIFF] Starting AnimateDiff video generation stage
🎬 [ANIMATEDIFF] Config: motion_module=mm_sd_v15_v2.ckpt, frames=16, fps=12
🎬 [ANIMATEDIFF] Calling WebUI API with AnimateDiff params
🎬 [ANIMATEDIFF] Received 16 frames from WebUI
🎬 [ANIMATEDIFF] Saved 16 frames to output/.../frames
🎬 [ANIMATEDIFF] Assembling 16 frames into video
✅ [ANIMATEDIFF] Video created: test_animation.mp4
Success: True
Video path: output/test_runs/.../test_animation.mp4
```

---

# VALIDATION CHECKLIST

Before marking this PR complete, verify:

## Code Changes
- [ ] StageType.ANIMATEDIFF added to stage_models.py
- [ ] AnimateDiffConfig created in video_stage_config.py
- [ ] Stage sequencer updated with animatediff ordering
- [ ] run_animatediff_stage() implemented in executor.py
- [ ] VideoCreator.create_from_frames() implemented
- [ ] Pipeline runner dispatch updated for animatediff
- [ ] Job models display map includes animatediff
- [ ] Pipeline __init__ exports video stage types

## Tests
- [ ] All unit tests pass (pytest tests/pipeline/test_animatediff_stage.py)
- [ ] VideoCreator tests pass (pytest tests/pipeline/test_video_creator_v2.py)
- [ ] Stage sequencer tests pass with animatediff
- [ ] CLI test script generates video successfully

## Architecture Compliance
- [ ] No PipelineConfig in execution path
- [ ] NJR stage_chain is single source of truth
- [ ] Stage sequencer validates animatediff placement
- [ ] Video output tracked in stage metadata
- [ ] No GUI files modified (deferred to PR-VIDEO-002)

## Documentation
- [ ] D-VIDEO-001 updated with implementation notes
- [ ] CHANGELOG.md entry added for PR-VIDEO-001
- [ ] Code comments explain AnimateDiff payload structure

---

# RISKS & MITIGATIONS

## Risk 1: WebUI AnimateDiff Extension Not Installed

**Impact**: API calls fail, no video generation possible

**Mitigation**:
- Document extension requirement in README
- Add error message with installation instructions
- Graceful failure in run_animatediff_stage()

---

## Risk 2: ffmpeg Not Available

**Impact**: Frames generated but video not created

**Mitigation**:
- VideoCreator checks ffmpeg_available
- Clear error message with install instructions
- Fallback: keep frames directory for manual assembly

---

## Risk 3: VRAM Exhaustion

**Impact**: Generation fails mid-process

**Mitigation**:
- Log AnimateDiff VRAM requirements (+2-4GB)
- Recommend context_batch_size < video_length for low VRAM
- Catch OOM errors and log clear message

---

# NEXT STEPS (Post-Implementation)

1. **Merge PR-VIDEO-001** → AnimateDiff stage functional via CLI/API
2. **Begin PR-VIDEO-002** → GUI integration (stage card, pipeline panel)
3. **Test with real WebUI** → Validate against actual AnimateDiff extension
4. **Optimize frame cleanup** → Delete frames after video creation (configurable)
5. **Add motion module cache** → Discover available motion modules from WebUI

---

# APPENDIX

## AnimateDiff WebUI API Example

**Request:**
```json
{
  "prompt": "a cat walking through a garden",
  "negative_prompt": "blurry, static",
  "steps": 20,
  "cfg_scale": 7.0,
  "sampler_name": "Euler a",
  "width": 512,
  "height": 512,
  "seed": 42,
  "batch_size": 1,
  "alwayson_scripts": {
    "animatediff": {
      "args": [{
        "enable": true,
        "video_length": 16,
        "fps": 12,
        "model": "mm_sd_v15_v2.ckpt",
        "batch_size": 1,
        "stride": 1,
        "overlap": 8
      }]
    }
  }
}
```

**Response:**
```json
{
  "images": [
    "base64_frame_0...",
    "base64_frame_1...",
    // ... 14 more frames
  ],
  "parameters": { /* generation params */ },
  "info": "{\"seed\": 42, ...}"
}
```

---

**End of PR-VIDEO-001**

This PR implements the core AnimateDiff stage without GUI. Phase 2 (PR-VIDEO-002) will add GUI integration.
