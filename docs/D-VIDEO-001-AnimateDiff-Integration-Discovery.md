# D-VIDEO-001 — AnimateDiff Integration Discovery

**Status:** Discovery  
**Version:** v2.6  
**Date:** 2026-01-11  
**Subsystem:** Pipeline (Video Stage)  
**Author:** StableNew Development Team

---

## 1. Executive Summary

This discovery document analyzes how to integrate **AnimateDiff** video generation into StableNew's v2.6 architecture. AnimateDiff is a Stable Diffusion extension that converts still images into short animated video clips by injecting motion modules into the diffusion process.

The goal is to enable users to:
1. Generate animated video clips from static prompts
2. Apply motion to existing image sequences
3. Configure motion parameters (motion scale, frame count, FPS)
4. Maintain v2.6 architectural integrity (NJR-only execution)

This document provides:
- Current state analysis
- AnimateDiff capabilities and requirements
- Three integration approaches with trade-offs
- Recommended implementation path
- Risk analysis and mitigations

---

## 2. Current State Analysis

### 2.1 Existing Video Infrastructure

StableNew has **partial video infrastructure** from legacy development:

**Existing Components:**
- `src/pipeline/video.py` — `VideoCreator` class with ffmpeg wrapper
- Legacy tests in `archive/legacy_tests/test_pipeline_journey.py` (video stage tests)
- Stage type infrastructure supports future video stages
- Pipeline execution comment: "Main pipeline orchestrator for txt2img → img2img → upscale → video"

**Current Limitations:**
- Video stage is **not implemented** in v2.6 pipeline
- No AnimateDiff-specific logic exists
- No motion module configuration
- No frame interpolation or motion control
- VideoCreator only handles basic ffmpeg encoding (post-generation assembly)

### 2.2 V2.6 Pipeline Architecture

**Canonical Stage Ordering:**
```
txt2img → img2img → upscale → adetailer
```

AnimateDiff must integrate as either:
1. A **generation modifier** (affects txt2img/img2img)
2. A **separate stage** (e.g., `animatediff` or `video`)
3. A **post-processing stage** (after all image stages)

**NJR Execution Model:**
- PromptPack → Builder Pipeline → NJR → Queue → Runner → History
- All stage configuration must be in `NormalizedJobRecord.stage_chain`
- Stage types: `txt2img`, `img2img`, `upscale`, `adetailer`
- No new stage types without architectural approval

### 2.3 Stable Diffusion WebUI AnimateDiff Extension

**AnimateDiff A1111 Extension:**
- Requires `sd-webui-animatediff` extension installed
- Injects motion modules into SD generation process
- Works by applying temporal convolutions across frame batches
- Generates multiple frames in a single pass
- Requires motion module files (e.g., `mm_sd_v15_v2.ckpt`)

**Configuration Parameters:**
- `enable_animatediff`: Boolean toggle
- `motion_module`: Motion model name (e.g., `mm_sd_v15_v2.ckpt`)
- `video_length`: Frame count (typically 8-24 frames)
- `fps`: Target framerate (8-30 fps)
- `loop_number`: Number of animation loops
- `closed_loop`: Whether video loops seamlessly
- `batch_size`: Must be 1 for AnimateDiff
- `context_batch_size`: Frames processed together (affects VRAM)
- `stride`: Frame sampling stride
- `overlap`: Frame overlap for smooth transitions
- `interp`: Interpolation method (film, rife, etc.)
- `interp_x`: Interpolation multiplier

**WebUI API Integration:**
- AnimateDiff params added to `/sdapi/v1/txt2img` payload
- Returns multiple frames as separate images
- Frames must be assembled into video using ffmpeg

---

## 3. AnimateDiff Capabilities & Requirements

### 3.1 What AnimateDiff Does

AnimateDiff adds **temporal coherence** to Stable Diffusion generation:

**Single Prompt → Multiple Frames:**
- Prompt: "a cat walking through a garden"
- Output: 16 frames showing the cat's motion
- Each frame is slightly different but temporally coherent

**Motion Module Types:**
- `mm_sd_v15_v2.ckpt` — SD 1.5 motion (general purpose)
- `mm_sdxl_v10_beta.ckpt` — SDXL motion (higher quality)
- Custom motion modules for specific styles (anime, realistic, etc.)

**Use Cases:**
1. **Animated concept exploration** — see how a scene moves
2. **Motion previews** — validate dynamic composition
3. **Video thumbnails** — animated previews for galleries
4. **Learning experiments** — test motion parameters

### 3.2 Technical Requirements

**WebUI Extension:**
- User must install `sd-webui-animatediff` extension
- Motion module files must be in `extensions/sd-webui-animatediff/model/`
- Compatible with SD 1.5 and SDXL checkpoints

**API Requirements:**
- AnimateDiff params passed in txt2img/img2img payload
- Batch size must be 1 (AnimateDiff handles frame batching internally)
- Returns N frames as separate images
- Frame filenames include index (e.g., `00000.png`, `00001.png`, ...)

**Resource Constraints:**
- VRAM: Requires ~2-4GB additional VRAM for motion modules
- Generation Time: 3-5x slower than static image generation
- Disk Space: Multiple frames per prompt (8-24 images → 1 video)

**Post-Processing:**
- Frames must be assembled into video (ffmpeg)
- Audio track optional (silent video or music overlay)
- Container format: MP4 (H.264 + AAC) for compatibility

---

## 4. Integration Approaches

### Approach A: AnimateDiff as Generation Modifier (Inline)

**Design:**
- Add `animatediff_enabled` toggle to txt2img/img2img stage config
- AnimateDiff params stored in `StageConfig.extra` dict
- PipelineRunner detects `animatediff_enabled` and modifies payload
- Returns multiple frames from single stage
- VideoCreator assembles frames into MP4

**Stage Chain Example:**
```python
stage_chain=[
    StageConfig(
        stage_type="txt2img",
        enabled=True,
        steps=20,
        cfg_scale=7.0,
        extra={
            "animatediff_enabled": True,
            "motion_module": "mm_sd_v15_v2.ckpt",
            "video_length": 16,
            "fps": 12,
            "closed_loop": True,
        }
    )
]
```

**Pros:**
- ✅ No new stage type required
- ✅ Works within existing v2.6 architecture
- ✅ AnimateDiff params colocated with generation config
- ✅ Easy to enable/disable per job
- ✅ Minimal changes to stage sequencer

**Cons:**
- ❌ Conflates generation and video assembly concerns
- ❌ Returns multiple images from "single" stage (breaks stage output model)
- ❌ Harder to apply AnimateDiff to existing images
- ❌ No clear separation between image and video outputs

**Implementation Scope:**
- Modify `StageConfig` to support `animatediff_enabled` in extra
- Update `PipelineRunner.run_njr()` to detect AnimateDiff mode
- Extend `Pipeline.run_txt2img_stage()` to apply AnimateDiff params
- Add `VideoCreator.assemble_animatediff_frames()` method
- Update GUI to show AnimateDiff toggles in txt2img/img2img cards

---

### Approach B: AnimateDiff as Separate Stage (New Stage Type)

**Design:**
- Add new stage type: `StageType.ANIMATEDIFF = "animatediff"`
- AnimateDiff stage requires input from txt2img/img2img
- Stage chain: `txt2img → animatediff` or `txt2img → upscale → animatediff`
- AnimateDiff stage configuration in `StageConfig`
- Returns video file path in stage output

**Stage Chain Example:**
```python
stage_chain=[
    StageConfig(stage_type="txt2img", enabled=True, steps=20),
    StageConfig(
        stage_type="animatediff",
        enabled=True,
        extra={
            "motion_module": "mm_sd_v15_v2.ckpt",
            "video_length": 16,
            "fps": 12,
            "mode": "txt2img",  # or "img2img" for image input
        }
    )
]
```

**Pros:**
- ✅ Clean separation of concerns (generation vs animation)
- ✅ Can apply AnimateDiff to existing images (img2img mode)
- ✅ Stage output model: one stage → one artifact (video file)
- ✅ Easy to enable/disable independently
- ✅ Supports canonical ordering: `txt2img → upscale → animatediff`

**Cons:**
- ❌ Requires architectural approval for new stage type
- ❌ More complex stage sequencer logic
- ❌ AnimateDiff stage duplicates txt2img config (model, sampler, etc.)
- ❌ Potential confusion: two ways to generate (static vs animated)

**Implementation Scope:**
- Update `StageType` enum in `stage_models.py`
- Add `animatediff` to `build_stage_execution_plan()`
- Implement `Pipeline.run_animatediff_stage()`
- Add AnimateDiff stage card to GUI
- Update stage sequencer validation rules
- Update history/learning to track video outputs

---

### Approach C: Video Assembly as Post-Processing Stage (Hybrid)

**Design:**
- AnimateDiff is treated as a **txt2img modifier** (Approach A)
- Add separate **video assembly stage** for post-processing
- Video stage takes N frames from previous stage(s) and produces MP4
- Stage chain: `txt2img[animatediff] → video`

**Stage Chain Example:**
```python
stage_chain=[
    StageConfig(
        stage_type="txt2img",
        enabled=True,
        extra={
            "animatediff_enabled": True,
            "video_length": 16,
        }
    ),
    StageConfig(
        stage_type="video",
        enabled=True,
        extra={
            "fps": 12,
            "codec": "libx264",
            "audio_track": None,
        }
    )
]
```

**Pros:**
- ✅ Separates generation (AnimateDiff) from assembly (video encoding)
- ✅ Video stage can work with ANY frame sequence (not just AnimateDiff)
- ✅ Supports future workflows: batch images → video montage
- ✅ Clear stage output: txt2img → N frames, video → 1 MP4
- ✅ Reuses existing VideoCreator infrastructure

**Cons:**
- ❌ Requires two new features (AnimateDiff modifier + video stage)
- ❌ More configuration surface area
- ❌ Potential confusion about when to enable video stage
- ❌ Requires architectural approval for video stage type

**Implementation Scope:**
- Add `animatediff_enabled` to txt2img stage (Approach A)
- Add `StageType.VIDEO = "video"` stage type
- Implement `Pipeline.run_video_stage()`
- Add video stage card to GUI
- Update VideoCreator to support stage-based assembly

---

## 5. Recommended Approach

### Recommendation: **Approach B (Separate AnimateDiff Stage)**

**Rationale:**

1. **Architectural Clarity:**
   - AnimateDiff is fundamentally different from static generation
   - Separate stage type makes this explicit in NJR
   - Clear stage output model: one stage → one video artifact

2. **Flexibility:**
   - Can apply AnimateDiff to txt2img OR img2img
   - Can position AnimateDiff after upscale for high-res videos
   - Supports future extensions (ControlNet + AnimateDiff, etc.)

3. **V2.6 Alignment:**
   - Follows existing stage pattern (txt2img, img2img, upscale, adetailer)
   - NJR stores full stage config in `stage_chain`
   - PipelineRunner dispatches to `run_animatediff_stage()`
   - History/learning track video outputs naturally

4. **User Experience:**
   - GUI has dedicated AnimateDiff stage card
   - Users explicitly enable animation (no hidden modifiers)
   - Learning experiments can test motion parameters

5. **Future-Proofing:**
   - Video stage can be added later for non-AnimateDiff workflows
   - Supports ControlNet + AnimateDiff integration
   - Enables motion learning experiments (Approach D extension)

**Canonical Stage Ordering (Extended):**
```
txt2img → img2img → upscale → adetailer → animatediff
```

**Stage Types (Extended):**
```python
class StageType(str, Enum):
    TXT2IMG = "txt2img"
    IMG2IMG = "img2img"
    UPSCALE = "upscale"
    ADETAILER = "adetailer"
    ANIMATEDIFF = "animatediff"  # NEW
```

---

## 6. Technical Design (Approach B)

### 6.1 Stage Configuration Model

**StageConfig Extension:**
```python
# Example AnimateDiff stage config in NJR
StageConfig(
    stage_type="animatediff",
    enabled=True,
    steps=20,  # Overrides txt2img steps if needed
    cfg_scale=7.0,
    extra={
        # AnimateDiff-specific params
        "motion_module": "mm_sd_v15_v2.ckpt",
        "video_length": 16,
        "fps": 12,
        "context_batch_size": 16,
        "closed_loop": True,
        "stride": 1,
        "overlap": 8,
        
        # Generation mode
        "mode": "txt2img",  # or "img2img" for image input
        
        # Optional overrides
        "sampler_name": "Euler a",  # Override txt2img sampler
        "model": None,  # Use txt2img model by default
    }
)
```

### 6.2 Pipeline Execution Flow

**Stage Chain:**
```
txt2img → animatediff → video file
```

**Execution Steps:**

1. **txt2img stage** (if mode="txt2img"):
   - Generate single base frame
   - Store in `current_stage_paths`

2. **animatediff stage**:
   - Detect `stage_type="animatediff"`
   - Build AnimateDiff payload:
     - Copy txt2img config (model, sampler, steps, cfg)
     - Add AnimateDiff params (motion_module, video_length, fps)
     - Set batch_size=1 (required by AnimateDiff)
   - Call `/sdapi/v1/txt2img` with AnimateDiff params
   - Receive N frames (8-24 images)
   - Assemble frames into MP4 using VideoCreator
   - Return video file path

3. **History recording**:
   - Store video path in manifest
   - Link frames to video artifact
   - Track AnimateDiff params in metadata

**Alternative Flow (img2img mode):**
```
[existing image] → animatediff → video file
```

### 6.3 WebUI API Integration

**AnimateDiff Payload Structure:**
```python
payload = {
    # Standard SD params
    "prompt": "a cat walking through a garden",
    "negative_prompt": "blurry, static",
    "steps": 20,
    "cfg_scale": 7.0,
    "sampler_name": "Euler a",
    "width": 512,
    "height": 512,
    "seed": 42,
    "batch_size": 1,  # MUST be 1
    
    # AnimateDiff extension params
    "alwayson_scripts": {
        "animatediff": {
            "args": [
                {
                    "enable": True,
                    "video_length": 16,
                    "fps": 12,
                    "loop_number": 0,
                    "closed_loop": "R+",
                    "batch_size": 1,
                    "stride": 1,
                    "overlap": 8,
                    "format": ["PNG"],  # Frame format
                    "interp": "Off",
                    "interp_x": 10,
                    "model": "mm_sd_v15_v2.ckpt",
                }
            ]
        }
    }
}
```

**Response Handling:**
```python
response = webui_client.txt2img(payload)
frames = response["images"]  # List of base64-encoded frames

# Save frames to disk
frame_paths = []
for idx, frame_b64 in enumerate(frames):
    path = output_dir / f"frame_{idx:05d}.png"
    save_image(frame_b64, path)
    frame_paths.append(path)

# Assemble into video
video_path = VideoCreator.create_from_frames(
    frame_paths,
    output_path=output_dir / "animation.mp4",
    fps=12,
    codec="libx264"
)
```

### 6.4 GUI Integration

**AnimateDiff Stage Card:**

Location: `src/gui/stage_cards_v2/animatediff_stage_card_v2.py`

**UI Elements:**
- ✅ Enable AnimateDiff checkbox
- Motion Module dropdown (populated from WebUI cache)
- Video Length slider (8-24 frames)
- FPS spinner (8-30 fps)
- Context Batch Size slider (8-24)
- Closed Loop checkbox
- Advanced section: stride, overlap, interpolation

**Pipeline Tab Integration:**
- Add AnimateDiff stage card after adetailer
- Show/hide based on `animatediff_enabled` toggle
- Validate: AnimateDiff requires txt2img or img2img enabled

---

## 7. Implementation Roadmap

### Phase 1: Core AnimateDiff Stage (PR-VIDEO-001)

**Scope:**
- Add `StageType.ANIMATEDIFF` to stage models
- Implement `Pipeline.run_animatediff_stage()`
- Update `stage_sequencer.py` to include animatediff in ordering
- Basic VideoCreator frame assembly
- CLI/test validation (no GUI)

**Deliverables:**
- AnimateDiff stage executes via NJR
- Produces MP4 video file
- Frame → video assembly working

**Test Plan:**
- Unit test: AnimateDiff stage config validation
- Integration test: txt2img → animatediff → video file
- WebUI mock test: AnimateDiff payload structure

---

### Phase 2: GUI Integration (PR-VIDEO-002)

**Scope:**
- Create `AnimateDiffStageCardV2` class
- Add motion module dropdown (WebUI cache discovery)
- Wire stage card to pipeline panel
- Update preset/last-run serialization
- Dark mode theming

**Deliverables:**
- AnimateDiff stage card in Pipeline tab
- User can configure motion parameters
- Presets save/load AnimateDiff config

**Test Plan:**
- Stage card UI test (widget values → config dict)
- Preset round-trip test (save → load → verify)
- Dark mode visual validation

---

### Phase 3: Learning Integration (PR-VIDEO-003)

**Scope:**
- Extend variable metadata for motion parameters
- Add motion_module, video_length, fps to learning variables
- Update experiment design panel for video variables
- Learning controller generates video experiment variants

**Deliverables:**
- Learning experiments can test motion parameters
- Example: "Test 3 motion modules with same prompt"
- Video outputs stored in experiment results

**Test Plan:**
- Learning experiment: motion_module comparison
- Learning experiment: video_length sweep (8, 12, 16 frames)
- Results panel shows video thumbnails

---

## 8. Risk Analysis & Mitigations

### Risk 1: WebUI Extension Not Installed

**Impact:** AnimateDiff API calls fail, no video generation possible

**Likelihood:** HIGH (user must manually install extension)

**Mitigation:**
- Add extension detection via `/sdapi/v1/scripts` endpoint
- Show warning in GUI if AnimateDiff extension not found
- Graceful degradation: disable AnimateDiff stage card if unavailable
- Documentation: clear installation instructions

---

### Risk 2: VRAM Exhaustion

**Impact:** Generation fails mid-stage, corrupted video output

**Likelihood:** MEDIUM (AnimateDiff requires 2-4GB additional VRAM)

**Mitigation:**
- Add VRAM requirement warning in GUI
- Recommend context_batch_size < video_length for low VRAM
- Fallback: reduce resolution or frame count
- Error handling: catch OOM errors, log clear message

---

### Risk 3: Frame Assembly Failure

**Impact:** Frames generated but video file not created

**Likelihood:** LOW (ffmpeg is robust)

**Mitigation:**
- Validate ffmpeg installation on startup
- Show ffmpeg install instructions if missing
- Fallback: save frames as ZIP archive if video fails
- Test: VideoCreator error handling

---

### Risk 4: Architectural Drift (New Stage Type)

**Impact:** Breaks v2.6 stage sequencer, NJR validation, or history tracking

**Likelihood:** MEDIUM (new stage type requires careful integration)

**Mitigation:**
- Follow PR-CORE-A patterns for stage chain extension
- Update ALL stage sequencer validation rules
- Test: stage chain with animatediff in all positions
- Test: history persistence with video artifacts
- Code review: verify no PipelineConfig leaks

---

### Risk 5: Learning Subsystem Integration

**Impact:** Video outputs not tracked, ratings lost

**Likelihood:** MEDIUM (learning expects image outputs)

**Mitigation:**
- Extend LearningRecord to support video_path field
- Update results panel to display video thumbnails
- Video player widget for in-app playback
- Test: learning experiment with animatediff stage

---

## 9. Alternative Considerations

### AnimateDiff vs. Deforum

**Deforum** is another animation extension with different capabilities:

| Feature | AnimateDiff | Deforum |
|---------|-------------|---------|
| Motion Type | Temporal coherence | Keyframe-based camera motion |
| Frame Count | 8-24 frames | Unlimited |
| Complexity | Simple (one prompt) | Complex (keyframes, math expressions) |
| Use Case | Short animated loops | Long narrative videos |

**Recommendation:** Start with AnimateDiff (simpler, more stable). Deforum can be added later as separate stage type if needed.

---

### Img2Vid vs. Txt2Vid

**Current Recommendation:** Txt2Vid (txt2img → animatediff)

**Future Extension:** Img2Vid mode
- User provides static image
- AnimateDiff applies motion to image
- Stage chain: `[existing image] → img2img[animatediff]`

---

## 10. Open Questions

### Q1: Should AnimateDiff support ControlNet?

**Context:** ControlNet + AnimateDiff enables motion-guided animation

**Options:**
- A. Defer to future PR (PR-VIDEO-004)
- B. Include in Phase 1 (increases scope)

**Recommendation:** Defer to future PR. ControlNet integration is complex and should be separate work.

---

### Q2: Should video stage be separate from AnimateDiff?

**Context:** Approach C suggests separating generation and assembly

**Options:**
- A. AnimateDiff stage does generation + assembly (simpler)
- B. AnimateDiff + video stages (more flexible)

**Recommendation:** Option A for Phase 1. Video stage can be added in Phase 4 if needed for non-AnimateDiff workflows.

---

### Q3: How should learning experiments compare videos?

**Context:** Learning subsystem expects static images for rating

**Options:**
- A. Extract first frame as thumbnail (quick but lossy)
- B. Show video player in results panel (better UX)
- C. Extract GIF preview (middle ground)

**Recommendation:** Option B (video player widget). First frame thumbnail as fallback.

---

## 11. Success Criteria

**Phase 1 (Core) Success:**
- ✅ AnimateDiff stage executes via NJR
- ✅ MP4 video file generated
- ✅ Stage sequencer validates animatediff placement
- ✅ History stores video path

**Phase 2 (GUI) Success:**
- ✅ AnimateDiff stage card in Pipeline tab
- ✅ Motion parameters configurable
- ✅ Presets save/load AnimateDiff config
- ✅ Dark mode theming consistent

**Phase 3 (Learning) Success:**
- ✅ Learning experiments test motion parameters
- ✅ Video outputs stored in experiment results
- ✅ Results panel displays video thumbnails

**Architectural Success:**
- ✅ No PipelineConfig in execution path
- ✅ NJR remains single source of truth
- ✅ Stage chain integrity maintained
- ✅ No breaking changes to existing stages

---

## 12. Next Steps

1. **Human Approval:** Review discovery document, approve Approach B
2. **PR Planning:** Generate PR-VIDEO-001 spec (Core AnimateDiff Stage)
3. **Extension Check:** Verify AnimateDiff extension installed in WebUI
4. **Motion Module Discovery:** Implement motion module cache retrieval
5. **Phase 1 Implementation:** Core AnimateDiff stage (no GUI)
6. **Phase 2 Implementation:** GUI integration
7. **Phase 3 Implementation:** Learning integration

---

## 13. Appendix

### A. AnimateDiff Extension API Reference

**GitHub:** https://github.com/continue-revolution/sd-webui-animatediff

**API Params:**
```python
{
    "enable": bool,              # Enable AnimateDiff
    "video_length": int,         # Frame count (8-24)
    "fps": int,                  # Framerate (8-30)
    "loop_number": int,          # Loop count (0=no loop)
    "closed_loop": str,          # "N", "R+", "R-", "A" (loop modes)
    "batch_size": int,           # Must be 1
    "stride": int,               # Frame sampling stride
    "overlap": int,              # Frame overlap
    "format": list[str],         # ["PNG", "GIF", "MP4", "WEBM"]
    "interp": str,               # Interpolation method
    "interp_x": int,             # Interpolation multiplier
    "model": str,                # Motion module name
}
```

### B. Motion Module Library

**SD 1.5 Motion Modules:**
- `mm_sd_v15_v2.ckpt` — General purpose
- `mm_sd_v15_v3.ckpt` — Improved motion
- `temporaldiff-v1-animatediff.ckpt` — Temporal awareness

**SDXL Motion Modules:**
- `mm_sdxl_v10_beta.ckpt` — SDXL beta
- `animatediff_xl_beta.ckpt` — Community alternative

### C. Example Workflows

**Workflow 1: Simple Animation**
```
Prompt: "a cat walking through a garden, high quality"
Stage Chain: txt2img → animatediff
Config:
  - txt2img: 20 steps, 512x512, Euler a
  - animatediff: mm_sd_v15_v2, 16 frames, 12 fps
Output: animation_cat.mp4 (1.3s video)
```

**Workflow 2: Upscaled Animation**
```
Prompt: "cyberpunk cityscape, neon lights"
Stage Chain: txt2img → upscale → animatediff
Config:
  - txt2img: 30 steps, 512x512
  - upscale: R-ESRGAN 4x+, 1024x1024
  - animatediff: mm_sd_v15_v2, 20 frames, 24 fps
Output: animation_city_hd.mp4 (0.8s video, 1024x1024)
```

**Workflow 3: Learning Experiment**
```
Experiment: Test motion modules for same prompt
Variable: motion_module
Values: [mm_sd_v15_v2, mm_sd_v15_v3, temporaldiff-v1]
Stage Chain: txt2img → animatediff
Result: 3 videos, compare motion quality
```

---

**End of Discovery Document**

This discovery provides a comprehensive foundation for AnimateDiff integration. Approval of Approach B enables PR-VIDEO-001 planning to begin.
