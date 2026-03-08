# PR-VIDEO-003: AnimateDiff Learning Integration

**Related Discovery**: D-VIDEO-001  
**Architecture Version**: v2.6  
**PR Date**: 2026-01-11  
**Dependencies**: PR-VIDEO-001 (Core), PR-VIDEO-002 (GUI), PR-LEARN-020/021/022 (Variable Metadata)  
**Sequence**: Phase 3 of 3 (PR-VIDEO-001 → PR-VIDEO-002 → PR-VIDEO-003)

---

# EXECUTOR ACKNOWLEDGEMENT & COMPLIANCE BLOCK (MANDATORY)

## READ FIRST — EXECUTION CONTRACT ACKNOWLEDGEMENT

You are acting as an **Executor** for the StableNew v2.6 codebase.

By proceeding, you **explicitly acknowledge** that:

1. You have read and understand the attached document  
   **`StableNew_v2.6_Canonical_Execution_Contract.md`** *(via .github/copilot-instructions.md)*

2. You agree that this document is the **single authoritative source of truth** for:
   - Architecture
   - Variable metadata system (PR-LEARN-020)
   - Learning pipeline (PR-LEARN-010)
   - Video output tracking

3. This PR **MUST**:
   - Extend variable metadata for video parameters
   - Support video variable experiments in learning pipeline
   - Display video thumbnails in results panel
   - Track video outputs in learning history
   - Enable video rating/comparison

---

## ABSOLUTE EXECUTION RULES (NON‑NEGOTIABLE)

### 1. Scope Completion
- You MUST implement **100% of the PR scope**
- You MUST create **every file listed**
- You MUST modify **every file listed**
- Partial implementation is **explicitly forbidden**

### 2. Variable Metadata Extension
You MUST:
- Add motion_module, video_length, fps to variable metadata registry
- Support resource type for motion modules
- Implement video variable value generation
- Apply video overrides to NJR stage chain

### 3. Video Output Tracking
You MUST:
- Extend LearningRecord to store video paths
- Update experiment results to display video thumbnails
- Implement video player widget for in-app playback
- Track video metadata (frame count, duration, fps)

### 4. Proof Is Mandatory
For **every MUST**, you MUST provide:
- Full `git diff`
- pytest commands **with captured output**
- Grep output for video variable usage
- Exact file + line references

### 5. Tests Are Not Optional
You MUST:
- Run all tests specified in TEST PLAN
- Show command + full output
- Fix failures before proceeding

---

## ACKNOWLEDGEMENT STATEMENT (REQUIRED)

By continuing execution, you acknowledge:

> "I will extend variable metadata for video parameters (motion_module, video_length, fps),  
> implement video experiment support in learning pipeline, add video thumbnail display to  
> results panel, and track video outputs in learning history. I will provide verifiable proof  
> of all changes."

---

# PR METADATA

## PR ID
`PR-VIDEO-003-AnimateDiff-Learning-Integration`

## Related Canonical Sections
- **D-VIDEO-001 §7 Phase 3**: Learning Implementation Roadmap
- **D-VIDEO-001 §10 Q3**: Video comparison in learning experiments
- **D-LEARN-002 §4.C**: Hybrid Metadata approach
- **PR-LEARN-020**: Discrete variable support (dependency)
- **PR-VIDEO-001**: Core AnimateDiff stage (dependency)
- **PR-VIDEO-002**: GUI integration (dependency)

---

# INTENT (MANDATORY)

## What This PR Does

This PR implements **Phase 3** of AnimateDiff integration, adding learning system support for video experiments. Users can now test motion parameters (motion modules, frame counts, FPS) and compare video outputs side-by-side.

**Key Capabilities Added**:
1. Video variable metadata (motion_module, video_length, fps)
2. Video experiment design UI (checklist for motion modules)
3. Video output tracking in learning history
4. Video thumbnail display in results panel
5. Video player widget for in-app playback
6. Video rating and comparison

**User Value**:
- Test different motion modules with same prompt
- Compare frame counts (8, 12, 16, 24 frames)
- Evaluate FPS impact on motion quality
- Rate videos for motion smoothness
- Discover optimal motion settings

**Example Experiments**:
- "Test 3 motion modules for character animation"
- "Compare 12 vs 16 vs 20 frames for landscape motion"
- "Evaluate FPS impact: 12fps vs 24fps"

---

# SCOPE

## What This PR Changes

### 1. Variable Metadata Extension
- Add motion_module to LEARNING_VARIABLES (resource type)
- Add video_length to LEARNING_VARIABLES (numeric type)
- Add fps to LEARNING_VARIABLES (numeric type)
- Update resource discovery to include motion modules

### 2. Learning Controller Extension
- Support animatediff stage in NJR construction
- Apply motion module overrides to stage chain
- Generate video experiment variants
- Validate video variable selections

### 3. Experiment Design UI Extension
- Add video variables to variable dropdown
- Show motion module checklist (resource type)
- Display video parameter ranges
- Validate video experiments

### 4. Results Panel Extension
- Display video thumbnails (first frame or GIF)
- Add video player widget (click to play)
- Show video metadata (duration, frame count, fps)
- Support video rating

### 5. Learning History Extension
- Store video paths in LearningRecord
- Track motion module in metadata
- Link video outputs to experiment variants
- Support video file replay

---

# WHAT THIS PR DOES NOT CHANGE

## Out of Scope

### Advanced Features (Future)
- ❌ ControlNet + AnimateDiff experiments
- ❌ Img2Vid mode in learning
- ❌ Video editing/trimming in GUI
- ❌ Audio track overlay

### Existing Learning Features
- ❌ No changes to numeric/discrete variable logic
- ❌ No changes to prompt testing
- ❌ No changes to hero's journey

### Core Pipeline
- ❌ No changes to executor, runner, or sequencer
- ❌ No changes to AnimateDiff stage (already in PR-VIDEO-001)

---

# ALLOWED FILES

## Files to Create

### Video Player Widget
```
src/gui/widgets/video_player_widget.py          # Video playback widget
```

### Tests
```
tests/learning/test_video_variables.py           # Video variable metadata tests
tests/gui_v2/test_video_results_display.py       # Video results panel tests
```

## Files to Modify

### Variable Metadata
```
src/learning/variable_metadata.py               # Add motion_module, video_length, fps
```

### Learning Controller
```
src/gui/controllers/learning_controller.py      # Support video experiments
```

### Experiment Design UI
```
src/gui/views/experiment_design_panel.py         # Add video variables to UI
```

### Results Panel
```
src/gui/views/learning_results_panel.py          # Display video thumbnails
```

### Learning State
```
src/gui/learning_state.py                       # Add video metadata fields
```

### Learning History
```
src/learning/learning_history.py                # Store video paths
```

---

# FORBIDDEN FILES

## Files You MUST NOT Touch

### Core Pipeline (Protected)
```
src/pipeline/executor.py                         # Already modified in PR-VIDEO-001
src/pipeline/pipeline_runner.py                  # Already modified in PR-VIDEO-001
src/pipeline/stage_sequencer.py                  # Already modified in PR-VIDEO-001
```

### GUI Stage Cards (PR-VIDEO-002 Scope)
```
src/gui/stage_cards_v2/animatediff_stage_card_v2.py  # Already in PR-VIDEO-002
```

### Other GUI Tabs
```
src/gui/views/history_tab.py                     # History tab
src/gui/views/archive_tab.py                     # Archive tab
```

---

# IMPLEMENTATION STEPS

## Step 1: Extend Variable Metadata Registry

### File: `src/learning/variable_metadata.py`

**Add video variables:**

Locate LEARNING_VARIABLES dict (after existing variables):

```python
LEARNING_VARIABLES: dict[str, VariableMetadata] = {
    # ... existing variables (cfg_scale, steps, sampler, etc.) ...
    
    # Video variables (AnimateDiff)
    "motion_module": VariableMetadata(
        name="motion_module",
        display_name="Motion Module",
        value_type="resource",
        config_path="animatediff.motion_module",
        ui_component="checklist",
        resource_key="motion_modules",
        constraints=None,
    ),
    "video_length": VariableMetadata(
        name="video_length",
        display_name="Video Length (frames)",
        value_type="numeric",
        config_path="animatediff.video_length",
        ui_component="range",
        resource_key=None,
        constraints={"min": 8, "max": 24, "step": 2},
    ),
    "fps": VariableMetadata(
        name="fps",
        display_name="Framerate (FPS)",
        value_type="numeric",
        config_path="animatediff.fps",
        ui_component="range",
        resource_key=None,
        constraints={"min": 8, "max": 30, "step": 2},
    ),
}
```

**Expected Diff:**
- Add 3 new variables: motion_module, video_length, fps
- motion_module is resource type (uses checklist)
- video_length and fps are numeric types (use range)

---

## Step 2: Extend Learning Controller for Video

### File: `src/gui/controllers/learning_controller.py`

**Update _generate_variant_values() for video:**

Locate the resource validation section (around line 273-320):

```python
    def _validate_selected_resources(
        self, selected: list[str], meta: VariableMetadata, resource_key: str
    ) -> list[str]:
        """Validate selected resources against app_state.
        
        Args:
            selected: User-selected resource names
            meta: Variable metadata
            resource_key: Key in app_state.resources (models, vaes, motion_modules, etc.)
        
        Returns:
            List of valid resource names
        """
        if not self.app_state or not hasattr(self.app_state, "resources"):
            logger.warning(f"⚠️  No app_state.resources, cannot validate {resource_key}")
            return selected
        
        available = getattr(self.app_state.resources, resource_key, [])
        if not available:
            logger.warning(f"⚠️  No {resource_key} in resources cache")
            return selected
        
        # Filter to only valid resources
        valid = [s for s in selected if s in available]
        
        if len(valid) < len(selected):
            invalid = set(selected) - set(valid)
            logger.warning(
                f"⚠️  {len(invalid)} invalid {meta.display_name} selections: {invalid}"
            )
        
        return valid
```

**Update _build_variant_njr() to include animatediff stage:**

Locate the stage chain construction (around line 1000):

```python
    def _build_variant_njr(
        self,
        experiment: LearningExperiment,
        variant_index: int,
        variant_values: dict[str, Any],
        baseline_config: dict[str, Any],
    ) -> NormalizedJobRecord:
        """Build NJR for a single variant.
        
        Args:
            experiment: Learning experiment
            variant_index: Variant index
            variant_values: Variable values for this variant
            baseline_config: Baseline stage card config
        
        Returns:
            NormalizedJobRecord with variant overrides applied
        """
        # ... existing code ...
        
        # Build stage chain
        stage_chain = []
        
        # txt2img stage (always present)
        txt2img_stage = self._build_txt2img_stage(merged_config)
        stage_chain.append(txt2img_stage)
        
        # img2img stage (if enabled)
        if merged_config.get("pipeline", {}).get("img2img_enabled"):
            img2img_stage = self._build_img2img_stage(merged_config)
            stage_chain.append(img2img_stage)
        
        # upscale stage (if enabled)
        if merged_config.get("pipeline", {}).get("upscale_enabled"):
            upscale_stage = self._build_upscale_stage(merged_config)
            stage_chain.append(upscale_stage)
        
        # adetailer stage (if enabled)
        if merged_config.get("pipeline", {}).get("adetailer_enabled"):
            adetailer_stage = self._build_adetailer_stage(merged_config)
            stage_chain.append(adetailer_stage)
        
        # animatediff stage (if enabled or testing video variables) (NEW)
        if merged_config.get("pipeline", {}).get("animatediff_enabled") or \
           experiment.variable_under_test in ("motion_module", "video_length", "fps"):
            animatediff_stage = self._build_animatediff_stage(merged_config)
            stage_chain.append(animatediff_stage)
        
        # ... rest of NJR construction ...
```

**Add _build_animatediff_stage() helper:**

```python
    def _build_animatediff_stage(self, config: dict[str, Any]) -> StageConfig:
        """Build AnimateDiff stage config from merged config.
        
        Args:
            config: Merged pipeline config
        
        Returns:
            StageConfig for animatediff stage
        """
        from src.pipeline.job_models_v2 import StageConfig
        
        animatediff_cfg = config.get("animatediff", {})
        
        return StageConfig(
            stage_type="animatediff",
            enabled=True,
            steps=None,  # AnimateDiff uses txt2img steps
            cfg_scale=None,
            extra={
                "motion_module": animatediff_cfg.get("motion_module", "mm_sd_v15_v2.ckpt"),
                "video_length": int(animatediff_cfg.get("video_length", 16)),
                "fps": int(animatediff_cfg.get("fps", 12)),
                "closed_loop": animatediff_cfg.get("closed_loop", "R+"),
                "context_batch_size": int(animatediff_cfg.get("context_batch_size", 16)),
                "stride": int(animatediff_cfg.get("stride", 1)),
                "overlap": int(animatediff_cfg.get("overlap", 8)),
                "mode": "txt2img",
            }
        )
```

**Expected Diff:**
- Update _validate_selected_resources() to handle motion_modules
- Add animatediff stage to stage chain construction
- Add _build_animatediff_stage() helper method (30+ lines)

---

## Step 3: Update Experiment Design UI

### File: `src/gui/views/experiment_design_panel.py`

**Add video variables to dropdown:**

Locate the variable dropdown population (around line 150):

```python
        # Variable under test dropdown
        self.variable_dropdown["values"] = [
            "cfg_scale",
            "steps",
            "sampler",
            "scheduler",
            "denoise_strength",
            "upscale_factor",
            "model",
            "vae",
            "lora_strength",
            "motion_module",      # NEW
            "video_length",       # NEW
            "fps",                # NEW
        ]
```

**Update _on_variable_changed() to handle video variables:**

The existing dynamic widget switching (from PR-LEARN-020) already handles resource types, so motion_module will automatically show checklist UI. No additional changes needed if metadata is correct.

**Expected Diff:**
- Add 3 video variables to dropdown values

---

## Step 4: Extend Learning State for Video

### File: `src/gui/learning_state.py`

**Add video metadata to LearningResult:**

Locate LearningResult dataclass (around line 50-100):

```python
@dataclass
class LearningResult:
    """Result from a single learning variant."""
    
    variant_index: int
    variant_label: str
    variable_value: Any
    image_paths: list[str] = field(default_factory=list)
    video_paths: list[str] = field(default_factory=list)  # NEW
    video_metadata: dict[str, Any] = field(default_factory=dict)  # NEW (frame_count, fps, duration)
    generation_time_seconds: float = 0.0
    rating: int | None = None
    notes: str = ""
```

**Expected Diff:**
- Add video_paths field (list of video file paths)
- Add video_metadata field (frame_count, fps, duration, motion_module)

---

## Step 5: Create Video Player Widget

### File: `src/gui/widgets/video_player_widget.py` (NEW)

**Create video player widget:**

```python
"""Video player widget for learning results display."""

from __future__ import annotations

import logging
import subprocess
import tkinter as tk
from pathlib import Path
from tkinter import ttk
from typing import Any

logger = logging.getLogger(__name__)


class VideoPlayerWidget(ttk.Frame):
    """Widget for displaying and playing video files.
    
    Shows video thumbnail (first frame or GIF preview) with play button.
    Clicking thumbnail opens video in system default player.
    
    UI Elements:
        - Thumbnail canvas (first frame)
        - Play button overlay
        - Video metadata label (duration, fps, frame count)
    """
    
    def __init__(
        self,
        parent: tk.Widget,
        video_path: str | Path,
        width: int = 320,
        height: int = 240,
        **kwargs
    ):
        """Initialize video player widget.
        
        Args:
            parent: Parent widget
            video_path: Path to video file
            width: Thumbnail width
            height: Thumbnail height
            **kwargs: Additional arguments passed to ttk.Frame
        """
        super().__init__(parent, **kwargs)
        
        self.video_path = Path(video_path)
        self.width = width
        self.height = height
        
        self._create_widgets()
        self._load_thumbnail()
    
    def _create_widgets(self) -> None:
        """Create video player widgets."""
        # Container frame
        self.container = ttk.Frame(self, style="Dark.TFrame")
        self.container.pack(fill=tk.BOTH, expand=True)
        
        # Thumbnail canvas
        self.canvas = tk.Canvas(
            self.container,
            width=self.width,
            height=self.height,
            bg="#1e1e1e",
            highlightthickness=1,
            highlightbackground="#3e3e3e",
        )
        self.canvas.pack(side=tk.TOP, pady=(0, 4))
        
        # Bind click to play video
        self.canvas.bind("<Button-1>", lambda e: self._play_video())
        
        # Play button overlay (▶ symbol)
        play_x = self.width // 2
        play_y = self.height // 2
        self.play_button = self.canvas.create_text(
            play_x,
            play_y,
            text="▶",
            font=("Segoe UI", 48),
            fill="#ffffff",
            state=tk.NORMAL,
        )
        
        # Video metadata label
        self.metadata_label = ttk.Label(
            self.container,
            text="Loading...",
            style="Dark.TLabel",
            font=("Segoe UI", 9),
        )
        self.metadata_label.pack(side=tk.TOP)
    
    def _load_thumbnail(self) -> None:
        """Load video thumbnail (first frame or placeholder)."""
        if not self.video_path.exists():
            self._show_error("Video not found")
            return
        
        try:
            # Use ffmpeg to extract first frame
            thumbnail_path = self.video_path.parent / f"{self.video_path.stem}_thumb.png"
            
            if not thumbnail_path.exists():
                self._extract_thumbnail(thumbnail_path)
            
            if thumbnail_path.exists():
                self._display_thumbnail(thumbnail_path)
            else:
                self._show_placeholder()
            
            # Load video metadata
            self._load_metadata()
            
        except Exception as exc:
            logger.error(f"❌ Failed to load video thumbnail: {exc}")
            self._show_error("Thumbnail error")
    
    def _extract_thumbnail(self, output_path: Path) -> None:
        """Extract first frame from video using ffmpeg.
        
        Args:
            output_path: Path for thumbnail image
        """
        try:
            cmd = [
                "ffmpeg",
                "-i", str(self.video_path),
                "-vframes", "1",
                "-vf", f"scale={self.width}:{self.height}",
                str(output_path),
            ]
            
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                check=False,
            )
            
            if result.returncode != 0:
                logger.warning(f"⚠️  ffmpeg thumbnail extraction failed: {result.stderr}")
        except Exception as exc:
            logger.error(f"❌ Thumbnail extraction error: {exc}")
    
    def _display_thumbnail(self, thumbnail_path: Path) -> None:
        """Display thumbnail image on canvas.
        
        Args:
            thumbnail_path: Path to thumbnail image
        """
        try:
            from PIL import Image, ImageTk
            
            img = Image.open(thumbnail_path)
            img = img.resize((self.width, self.height), Image.Resampling.LANCZOS)
            
            self.photo = ImageTk.PhotoImage(img)
            self.canvas.create_image(0, 0, anchor=tk.NW, image=self.photo)
            
            # Re-add play button on top
            play_x = self.width // 2
            play_y = self.height // 2
            self.canvas.tag_raise(self.play_button)
            
        except Exception as exc:
            logger.error(f"❌ Failed to display thumbnail: {exc}")
            self._show_placeholder()
    
    def _show_placeholder(self) -> None:
        """Show placeholder when thumbnail unavailable."""
        self.canvas.create_rectangle(
            0, 0, self.width, self.height,
            fill="#2e2e2e",
            outline="#3e3e3e",
        )
        self.canvas.create_text(
            self.width // 2,
            self.height // 2 - 20,
            text="🎬",
            font=("Segoe UI", 32),
            fill="#6e6e6e",
        )
        self.canvas.create_text(
            self.width // 2,
            self.height // 2 + 20,
            text="Video Preview",
            font=("Segoe UI", 12),
            fill="#6e6e6e",
        )
    
    def _show_error(self, message: str) -> None:
        """Show error message on canvas.
        
        Args:
            message: Error message to display
        """
        self.canvas.create_rectangle(
            0, 0, self.width, self.height,
            fill="#2e2e2e",
            outline="#ff4444",
        )
        self.canvas.create_text(
            self.width // 2,
            self.height // 2,
            text=f"❌ {message}",
            font=("Segoe UI", 12),
            fill="#ff4444",
        )
    
    def _load_metadata(self) -> None:
        """Load and display video metadata."""
        try:
            # Use ffprobe to get video metadata
            cmd = [
                "ffprobe",
                "-v", "error",
                "-select_streams", "v:0",
                "-show_entries", "stream=duration,r_frame_rate,nb_frames",
                "-of", "default=noprint_wrappers=1",
                str(self.video_path),
            ]
            
            result = subprocess.run(cmd, capture_output=True, text=True, check=False)
            
            if result.returncode == 0:
                output = result.stdout
                
                # Parse metadata (simple key=value format)
                metadata = {}
                for line in output.strip().split("\n"):
                    if "=" in line:
                        key, value = line.split("=", 1)
                        metadata[key] = value
                
                # Format display
                duration = float(metadata.get("duration", 0))
                fps_str = metadata.get("r_frame_rate", "12/1")
                fps = self._parse_fps(fps_str)
                frames = metadata.get("nb_frames", "?")
                
                display_text = f"{duration:.1f}s | {fps:.0f} fps | {frames} frames"
                self.metadata_label.config(text=display_text)
            else:
                self.metadata_label.config(text=f"{self.video_path.name}")
        
        except Exception as exc:
            logger.error(f"❌ Failed to load video metadata: {exc}")
            self.metadata_label.config(text=f"{self.video_path.name}")
    
    def _parse_fps(self, fps_str: str) -> float:
        """Parse FPS from ffprobe output (e.g., '24/1' → 24.0).
        
        Args:
            fps_str: FPS string from ffprobe
        
        Returns:
            FPS as float
        """
        try:
            if "/" in fps_str:
                num, den = fps_str.split("/")
                return float(num) / float(den)
            return float(fps_str)
        except Exception:
            return 12.0  # Default fallback
    
    def _play_video(self) -> None:
        """Open video in system default player."""
        if not self.video_path.exists():
            logger.error(f"❌ Video file not found: {self.video_path}")
            return
        
        try:
            # Open with system default application
            import platform
            
            if platform.system() == "Windows":
                import os
                os.startfile(str(self.video_path))
            elif platform.system() == "Darwin":  # macOS
                subprocess.run(["open", str(self.video_path)], check=False)
            else:  # Linux
                subprocess.run(["xdg-open", str(self.video_path)], check=False)
            
            logger.info(f"▶️  Playing video: {self.video_path.name}")
        
        except Exception as exc:
            logger.error(f"❌ Failed to play video: {exc}")
```

**Expected Diff:**
- New file (300+ lines)
- VideoPlayerWidget class
- Thumbnail extraction using ffmpeg
- Video metadata display using ffprobe
- Click to play in system player

---

## Step 6: Update Results Panel for Video

### File: `src/gui/views/learning_results_panel.py`

**Import video player widget:**

```python
from src.gui.widgets.video_player_widget import VideoPlayerWidget
```

**Update _create_result_card() to handle video:**

Locate the result card creation method (around line 200-300):

```python
    def _create_result_card(
        self,
        parent: tk.Widget,
        result: LearningResult,
        variable_name: str,
    ) -> tk.Widget:
        """Create result card for a single variant.
        
        Args:
            parent: Parent widget
            result: Learning result data
            variable_name: Variable under test name
        
        Returns:
            Frame widget containing result card
        """
        card = ttk.Frame(parent, style="Dark.TFrame", relief=tk.RAISED, borderwidth=1)
        card.pack(side=tk.LEFT, padx=8, pady=8)
        
        # Header: variant label + value
        header = ttk.Frame(card, style="Dark.TFrame")
        header.pack(fill=tk.X, pady=(4, 8))
        
        ttk.Label(
            header,
            text=f"{variable_name} = {result.variable_value}",
            style="Dark.TLabel",
            font=("Segoe UI", 11, "bold"),
        ).pack()
        
        # Content: image or video
        if result.video_paths:
            # Show video player (NEW)
            self._add_video_display(card, result)
        elif result.image_paths:
            # Show image grid (existing)
            self._add_image_display(card, result)
        else:
            # No output
            ttk.Label(
                card,
                text="No output",
                style="Dark.TLabel",
                font=("Segoe UI", 9, "italic"),
            ).pack(pady=20)
        
        # Footer: rating + metadata
        self._add_result_footer(card, result)
        
        return card
    
    def _add_video_display(self, parent: tk.Widget, result: LearningResult) -> None:
        """Add video player widget to result card.
        
        Args:
            parent: Parent widget
            result: Learning result with video paths
        """
        video_frame = ttk.Frame(parent, style="Dark.TFrame")
        video_frame.pack(pady=(0, 8))
        
        # Show first video (most common case: 1 video per variant)
        if result.video_paths:
            video_path = result.video_paths[0]
            player = VideoPlayerWidget(
                video_frame,
                video_path=video_path,
                width=320,
                height=240,
            )
            player.pack()
        
        # Show video metadata
        if result.video_metadata:
            meta = result.video_metadata
            meta_text = f"{meta.get('frame_count', '?')} frames | {meta.get('fps', '?')} fps | {meta.get('duration_seconds', 0):.1f}s"
            ttk.Label(
                video_frame,
                text=meta_text,
                style="Dark.TLabel",
                font=("Segoe UI", 9, "italic"),
            ).pack(pady=(4, 0))
```

**Expected Diff:**
- Import VideoPlayerWidget
- Update _create_result_card() to check video_paths
- Add _add_video_display() method (30+ lines)
- Show video metadata below player

---

## Step 7: Update Learning History for Video

### File: `src/learning/learning_history.py`

**Extend LearningRecord for video:**

Locate LearningRecord dataclass or dict structure (around line 50-100):

```python
@dataclass
class LearningRecord:
    """Record of a completed learning experiment."""
    
    experiment_id: str
    experiment_name: str
    variable_under_test: str
    baseline_config: dict[str, Any]
    variants: list[dict[str, Any]]  # Each variant has image_paths and/or video_paths
    created_at: str
    completed_at: str
    
    def to_dict(self) -> dict[str, Any]:
        """Serialize to dict for JSON storage."""
        return {
            "experiment_id": self.experiment_id,
            "experiment_name": self.experiment_name,
            "variable_under_test": self.variable_under_test,
            "baseline_config": self.baseline_config,
            "variants": self.variants,  # Already includes video_paths if present
            "created_at": self.created_at,
            "completed_at": self.completed_at,
        }
```

**Update write_learning_record() to handle video:**

```python
def write_learning_record(
    experiment: LearningExperiment,
    results: list[LearningResult],
    output_file: Path,
) -> None:
    """Write learning experiment results to JSONL file.
    
    Args:
        experiment: Learning experiment metadata
        results: List of variant results (may include video_paths)
        output_file: Path to JSONL file
    """
    variants = []
    for result in results:
        variant_dict = {
            "variant_index": result.variant_index,
            "variant_label": result.variant_label,
            "variable_value": result.variable_value,
            "image_paths": result.image_paths,
            "video_paths": result.video_paths,  # NEW
            "video_metadata": result.video_metadata,  # NEW
            "rating": result.rating,
            "notes": result.notes,
        }
        variants.append(variant_dict)
    
    record = LearningRecord(
        experiment_id=experiment.experiment_id,
        experiment_name=experiment.experiment_name,
        variable_under_test=experiment.variable_under_test,
        baseline_config=experiment.baseline_config,
        variants=variants,
        created_at=experiment.created_at,
        completed_at=datetime.utcnow().isoformat(),
    )
    
    # Write to JSONL
    with open(output_file, "a") as f:
        f.write(json.dumps(record.to_dict()) + "\n")
```

**Expected Diff:**
- LearningRecord already supports arbitrary variant dicts
- Ensure video_paths and video_metadata are included in variant serialization
- No breaking changes to existing record format

---

# TEST PLAN

## Unit Tests

### Test 1: Video Variable Metadata

**File**: `tests/learning/test_video_variables.py`

```python
def test_video_variables_in_registry():
    """Verify video variables in metadata registry."""
    from src.learning.variable_metadata import LEARNING_VARIABLES
    
    assert "motion_module" in LEARNING_VARIABLES
    assert "video_length" in LEARNING_VARIABLES
    assert "fps" in LEARNING_VARIABLES
    
    # Verify types
    assert LEARNING_VARIABLES["motion_module"].value_type == "resource"
    assert LEARNING_VARIABLES["video_length"].value_type == "numeric"
    assert LEARNING_VARIABLES["fps"].value_type == "numeric"


def test_motion_module_resource_discovery():
    """Verify motion module resource discovery."""
    from src.learning.variable_metadata import get_variable_metadata
    
    meta = get_variable_metadata("motion_module")
    assert meta is not None
    assert meta.resource_key == "motion_modules"
    assert meta.ui_component == "checklist"
```

---

### Test 2: Video Experiment NJR Construction

**File**: `tests/learning/test_video_experiments.py`

```python
def test_video_experiment_includes_animatediff_stage():
    """Verify video experiments include animatediff stage."""
    from src.gui.controllers.learning_controller import LearningController
    from src.gui.learning_state import LearningExperiment
    
    controller = LearningController(app_state=None)
    
    experiment = LearningExperiment(
        experiment_id="test-video",
        experiment_name="Test Motion Modules",
        variable_under_test="motion_module",
        values=[],  # Filled by controller
        metadata={"selected_items": ["mm_sd_v15_v2.ckpt", "mm_sd_v15_v3.ckpt"]},
        baseline_config={
            "pipeline": {"txt2img_enabled": True, "animatediff_enabled": True},
            "txt2img": {},
            "animatediff": {},
        },
    )
    
    variant_values = {"motion_module": "mm_sd_v15_v2.ckpt"}
    njr = controller._build_variant_njr(experiment, 0, variant_values, experiment.baseline_config)
    
    # Verify animatediff stage in chain
    stage_types = [s.stage_type for s in njr.stage_chain]
    assert "animatediff" in stage_types
```

---

### Test 3: Video Results Display

**File**: `tests/gui_v2/test_video_results_display.py`

```python
def test_video_player_widget_creation(tmp_path):
    """Verify video player widget creates correctly."""
    import tkinter as tk
    from src.gui.widgets.video_player_widget import VideoPlayerWidget
    
    # Create dummy video file
    video_path = tmp_path / "test_video.mp4"
    video_path.write_text("dummy video")
    
    root = tk.Tk()
    player = VideoPlayerWidget(root, video_path=video_path, width=320, height=240)
    
    assert player.video_path == video_path
    assert player.width == 320
    assert player.height == 240
    
    root.destroy()


def test_result_card_shows_video(tmp_path):
    """Verify result card displays video instead of images."""
    import tkinter as tk
    from src.gui.views.learning_results_panel import LearningResultsPanel
    from src.gui.learning_state import LearningResult
    
    # Create dummy video
    video_path = tmp_path / "result.mp4"
    video_path.write_text("dummy video")
    
    result = LearningResult(
        variant_index=0,
        variant_label="Variant 1",
        variable_value="mm_sd_v15_v2.ckpt",
        video_paths=[str(video_path)],
        video_metadata={"frame_count": 16, "fps": 12, "duration_seconds": 1.3},
    )
    
    root = tk.Tk()
    panel = LearningResultsPanel(root, app_state=None)
    
    # Create result card
    card = panel._create_result_card(panel, result, "motion_module")
    
    # Verify video player widget exists (not image grid)
    # (This is a structural test, actual rendering requires GUI)
    assert card is not None
    
    root.destroy()
```

---

## Integration Tests

### Test 4: End-to-End Video Experiment

**File**: `tests/learning/test_video_experiment_integration.py`

```python
def test_motion_module_comparison_experiment(tmp_path, mock_app_state):
    """Verify motion module comparison experiment end-to-end."""
    from src.gui.controllers.learning_controller import LearningController
    from src.gui.learning_state import LearningExperiment
    
    # Setup mock app state with motion modules
    mock_app_state.resources.motion_modules = [
        "mm_sd_v15_v2.ckpt",
        "mm_sd_v15_v3.ckpt",
        "mm_sdxl_v10_beta.ckpt",
    ]
    
    controller = LearningController(app_state=mock_app_state)
    
    # Create experiment
    experiment = LearningExperiment(
        experiment_id="test-motion",
        experiment_name="Compare Motion Modules",
        variable_under_test="motion_module",
        metadata={
            "selected_items": ["mm_sd_v15_v2.ckpt", "mm_sd_v15_v3.ckpt"]
        },
        baseline_config={
            "pipeline": {"txt2img_enabled": True, "animatediff_enabled": True},
            "txt2img": {"steps": 20},
            "animatediff": {"video_length": 16, "fps": 12},
        },
    )
    
    # Build plan
    jobs = controller.build_plan(experiment)
    
    # Verify 2 jobs (one per motion module)
    assert len(jobs) == 2
    
    # Verify each job has animatediff stage
    for job in jobs:
        stage_types = [s.stage_type for s in job.stage_chain]
        assert "animatediff" in stage_types
        
        # Verify motion_module override
        animatediff_stage = [s for s in job.stage_chain if s.stage_type == "animatediff"][0]
        assert "motion_module" in animatediff_stage.extra
```

---

## Manual Testing

### Test 5: Create Video Experiment

**Steps:**
1. Open Learning tab
2. Select "motion_module" from variable dropdown
3. Check 2-3 motion modules in checklist
4. Enter prompt: "a cat walking through a garden"
5. Click "Build Preview"
6. Verify 2-3 variants shown with video icon
7. Click "Run Experiment"

**Expected:**
- Experiment generates 2-3 videos
- Each video uses different motion module
- Results panel shows video players
- Click thumbnail to play video

---

### Test 6: Video Results Display

**Steps:**
1. After experiment completes (Test 5)
2. View results panel
3. Verify each variant shows:
   - Video thumbnail (first frame)
   - Play button overlay
   - Video metadata (frame count, fps, duration)
4. Click thumbnail
5. Verify video plays in system player

**Expected:**
- Video thumbnails render correctly
- Metadata displays (e.g., "16 frames | 12 fps | 1.3s")
- Click opens video in default player

---

# VALIDATION CHECKLIST

Before marking this PR complete, verify:

## Code Changes
- [ ] Video variables added to variable_metadata.py
- [ ] Learning controller supports video experiments
- [ ] VideoPlayerWidget created
- [ ] Results panel displays video thumbnails
- [ ] Learning history stores video paths
- [ ] Experiment design UI includes video variables

## Tests
- [ ] Video variable metadata tests pass
- [ ] Video experiment NJR construction tests pass
- [ ] Video player widget tests pass
- [ ] End-to-end video experiment test passes

## UI/UX
- [ ] Video variables appear in variable dropdown
- [ ] Motion module checklist functional
- [ ] Video thumbnails render in results panel
- [ ] Video playback works (system player)
- [ ] Video metadata displays correctly

## Architecture Compliance
- [ ] No pipeline logic in GUI layer
- [ ] Video outputs tracked in learning history
- [ ] NJR stage chain includes animatediff
- [ ] No breaking changes to existing learning features

---

# RISKS & MITIGATIONS

## Risk 1: Video Thumbnail Generation Slow

**Impact**: Results panel loads slowly

**Mitigation**:
- Extract thumbnails asynchronously
- Cache thumbnails after first load
- Show placeholder while loading

---

## Risk 2: Video Playback Fails

**Impact**: User cannot view video results

**Mitigation**:
- Fallback: open folder containing video
- Show video path as copyable text
- Support manual VLC/player invocation

---

## Risk 3: Large Video Files

**Impact**: Disk space issues, slow transfers

**Mitigation**:
- Compress videos with lower CRF
- Delete old experiment videos after 30 days
- Add video cleanup tool

---

# NEXT STEPS (Post-Implementation)

1. **Merge PR-VIDEO-003** → Video learning experiments functional
2. **Add video gallery view** → Browse all experiment videos
3. **Add video comparison** → Side-by-side playback
4. **Add ControlNet + AnimateDiff** → Motion-guided video experiments
5. **Add audio overlay** → Background music for videos

---

# EXAMPLE EXPERIMENTS

## Experiment 1: Motion Module Comparison

**Setup:**
- Variable: motion_module
- Values: mm_sd_v15_v2.ckpt, mm_sd_v15_v3.ckpt, temporaldiff-v1-animatediff.ckpt
- Prompt: "a butterfly flying through a flower garden"
- Fixed: 16 frames, 12 fps

**Hypothesis:** Different motion modules produce different quality motion

**Evaluation:** Rate each video for motion smoothness and temporal coherence

---

## Experiment 2: Frame Count Impact

**Setup:**
- Variable: video_length
- Values: 8, 12, 16, 20, 24 frames
- Prompt: "waves crashing on a beach at sunset"
- Fixed: mm_sd_v15_v2.ckpt, 12 fps

**Hypothesis:** More frames = smoother motion but longer generation

**Evaluation:** Balance motion quality vs. generation time

---

## Experiment 3: FPS Comparison

**Setup:**
- Variable: fps
- Values: 8, 12, 16, 24 fps
- Prompt: "a car driving down a city street"
- Fixed: mm_sd_v15_v2.ckpt, 16 frames

**Hypothesis:** Higher FPS improves perceived motion smoothness

**Evaluation:** Find optimal FPS for perceptual quality

---

**End of PR-VIDEO-003**

This PR completes AnimateDiff integration by adding learning system support for video experiments. Users can now test motion parameters and compare video outputs systematically.
