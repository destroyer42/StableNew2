# PR-VIDEO-002: AnimateDiff GUI Integration

**Related Discovery**: D-VIDEO-001  
**Architecture Version**: v2.6  
**PR Date**: 2026-01-11  
**Dependencies**: PR-VIDEO-001 (Core AnimateDiff Stage)  
**Sequence**: Phase 2 of 3 (PR-VIDEO-001 → PR-VIDEO-002 → PR-VIDEO-003)

---

# EXECUTOR ACKNOWLEDGEMENT & COMPLIANCE BLOCK (MANDATORY)

## READ FIRST — EXECUTION CONTRACT ACKNOWLEDGEMENT

You are acting as an **Executor** for the StableNew v2.6 codebase.

By proceeding, you **explicitly acknowledge** that:

1. You have read and understand the attached document  
   **`StableNew_v2.6_Canonical_Execution_Contract.md`** *(via .github/copilot-instructions.md)*

2. You agree that this document is the **single authoritative source of truth** for:
   - Architecture
   - GUI v2 stage card patterns
   - Dark mode theming
   - Preset serialization

3. This PR **MUST**:
   - Create AnimateDiffStageCardV2 following v2 patterns
   - Integrate stage card into Pipeline panel
   - Support motion module dropdown (WebUI cache)
   - Implement preset save/load for AnimateDiff config
   - Apply dark mode theming consistently

---

## ABSOLUTE EXECUTION RULES (NON‑NEGOTIABLE)

### 1. Scope Completion
- You MUST implement **100% of the PR scope**
- You MUST create **every file listed**
- You MUST modify **every file listed**
- Partial implementation is **explicitly forbidden**

### 2. GUI v2 Pattern Enforcement
You MUST:
- Follow BaseStageCardV2 patterns
- Use ttk widgets with "Dark.T*" styles
- Implement load_from_section() and to_config_dict()
- Support enable/disable toggle
- Add validation in _validate_stage_config()

### 3. Motion Module Discovery
You MUST:
- Query WebUI for available motion modules
- Cache motion module list in app_state
- Populate dropdown from cache
- Handle missing extension gracefully

### 4. Proof Is Mandatory
For **every MUST**, you MUST provide:
- Full `git diff`
- GUI screenshot showing stage card (if possible)
- Grep output for stage card usage
- Exact file + line references

### 5. Tests Are Not Optional
You MUST:
- Run all tests specified in TEST PLAN
- Show command + full output
- Fix failures before proceeding

---

## ACKNOWLEDGEMENT STATEMENT (REQUIRED)

By continuing execution, you acknowledge:

> "I will create AnimateDiffStageCardV2 following v2 patterns, integrate into Pipeline panel,  
> implement motion module discovery from WebUI cache, support preset serialization, and apply  
> dark mode theming. I will provide verifiable proof of all changes."

---

# PR METADATA

## PR ID
`PR-VIDEO-002-AnimateDiff-GUI-Integration`

## Related Canonical Sections
- **D-VIDEO-001 §6.4**: GUI Integration
- **D-VIDEO-001 §7 Phase 2**: GUI Implementation Roadmap
- **Architecture v2.6 §7**: GUI Layer (Stage Cards)
- **PR-VIDEO-001**: Core AnimateDiff Stage (dependency)

---

# INTENT (MANDATORY)

## What This PR Does

This PR implements **Phase 2** of AnimateDiff integration, adding GUI support for configuring AnimateDiff video generation. It creates a stage card for the Pipeline tab following v2 patterns and integrates with the preset system.

**Key Capabilities Added**:
1. AnimateDiffStageCardV2 widget (follows BaseStageCardV2 pattern)
2. Motion module dropdown (populated from WebUI cache)
3. Video parameters UI (frame count, FPS, loop mode)
4. Advanced controls (context batch, stride, overlap)
5. Preset save/load for AnimateDiff config
6. Pipeline panel integration with stage card
7. Dark mode theming

**User Value**:
- Configure AnimateDiff parameters visually
- Select motion modules from dropdown
- Save/load AnimateDiff presets
- Enable/disable video generation per run

---

# SCOPE

## What This PR Changes

### 1. AnimateDiff Stage Card
- Create `AnimateDiffStageCardV2` class
- Motion module dropdown (WebUI cache)
- Frame count slider (8-24 frames)
- FPS spinbox (8-30 fps)
- Closed loop mode dropdown
- Advanced section (collapsible)
- Enable/disable toggle

### 2. Motion Module Discovery
- Add motion module cache to app_state
- Query WebUI `/sdapi/v1/sd-models` or extension API
- Refresh button to reload available modules
- Default to "mm_sd_v15_v2.ckpt" if cache empty

### 3. Pipeline Panel Integration
- Add AnimateDiff stage card to pipeline_panel_v2.py
- Position after ADetailer card
- Wire enable toggle to pipeline config
- Update scrollable area sizing

### 4. Preset System Integration
- Extend preset serialization for animatediff section
- Load/save motion module, video_length, fps
- Support last-run persistence
- Validate AnimateDiff section in preset files

### 5. Dark Mode Theming
- Apply "Dark.T*" styles to all widgets
- Consistent spacing with other stage cards
- Hover effects on dropdowns
- Disabled state styling

---

# WHAT THIS PR DOES NOT CHANGE

## Out of Scope

### Learning Integration (Deferred to PR-VIDEO-003)
- ❌ Video variable metadata
- ❌ Learning experiment video variants
- ❌ Video thumbnail display in results
- ❌ Video rating UI

### Advanced Features (Future)
- ❌ ControlNet + AnimateDiff UI
- ❌ Img2Vid mode toggle
- ❌ Video preview/playback in GUI
- ❌ Frame-by-frame editor

### Existing Stage Cards
- ❌ No changes to txt2img, img2img, upscale, adetailer cards
- ❌ No changes to base stage card patterns

### Core Pipeline
- ❌ No changes to executor, runner, or sequencer
- ❌ No changes to NJR structure

---

# ALLOWED FILES

## Files to Create

### Stage Card
```
src/gui/stage_cards_v2/animatediff_stage_card_v2.py    # AnimateDiff stage card widget
```

### Tests
```
tests/gui_v2/test_animatediff_stage_card.py             # Stage card unit tests
```

## Files to Modify

### Pipeline Panel
```
src/gui/views/pipeline_panel_v2.py                     # Add AnimateDiff stage card
```

### Preset System
```
src/gui/controllers/preset_controller.py               # Extend preset serialization
```

### App State
```
src/utils/app_state_v2.py                              # Add motion_modules cache
```

### WebUI Cache
```
src/api/webui_cache.py                                 # Add motion module discovery
```

---

# FORBIDDEN FILES

## Files You MUST NOT Touch

### Learning Layer (PR-VIDEO-003 Scope)
```
src/learning/                                          # All learning files
src/gui/controllers/learning_controller.py             # Learning controller
src/gui/views/experiment_design_panel.py               # Experiment UI
```

### Core Pipeline (Protected)
```
src/pipeline/executor.py                               # Already modified in PR-VIDEO-001
src/pipeline/pipeline_runner.py                        # Already modified in PR-VIDEO-001
src/pipeline/stage_sequencer.py                        # Already modified in PR-VIDEO-001
```

### Other GUI Tabs
```
src/gui/views/history_tab.py                           # History tab
src/gui/views/archive_tab.py                           # Archive tab
src/gui/controllers/job_queue_controller.py            # Queue controller
```

---

# IMPLEMENTATION STEPS

## Step 1: Add Motion Module Cache to App State

### File: `src/utils/app_state_v2.py`

**Add motion_modules field:**

Locate the ResourceCache dataclass (around line 50-100):

```python
@dataclass
class ResourceCache:
    """Cached WebUI resources."""
    
    models: list[str] = field(default_factory=list)
    vaes: list[str] = field(default_factory=list)
    samplers: list[str] = field(default_factory=list)
    schedulers: list[str] = field(default_factory=list)
    loras: list[str] = field(default_factory=list)
    upscalers: list[str] = field(default_factory=list)
    motion_modules: list[str] = field(default_factory=list)  # NEW
    
    last_refresh: float = 0.0
```

**Expected Diff:**
- Add motion_modules field to ResourceCache
- Initialize as empty list

---

## Step 2: Add Motion Module Discovery to WebUI Cache

### File: `src/api/webui_cache.py`

**Add motion module discovery method:**

Add after existing cache methods:

```python
    def refresh_motion_modules(self) -> list[str]:
        """Discover available AnimateDiff motion modules.
        
        Queries the AnimateDiff extension API for available motion modules.
        Falls back to empty list if extension not installed.
        
        Returns:
            List of motion module names (e.g., ["mm_sd_v15_v2.ckpt", ...])
        """
        try:
            # Try AnimateDiff extension API endpoint
            response = self.client.get("/animatediff/model_list")
            if response and isinstance(response, dict):
                models = response.get("model_list", [])
                if models:
                    logger.info(f"✅ Discovered {len(models)} motion modules")
                    return models
        except Exception as exc:
            logger.debug(f"AnimateDiff extension API not available: {exc}")
        
        # Fallback: try filesystem scan (extension must be installed)
        try:
            # AnimateDiff extension stores models in extensions/sd-webui-animatediff/model/
            # This is not exposed via API, so we return common defaults
            defaults = [
                "mm_sd_v15_v2.ckpt",
                "mm_sd_v15_v3.ckpt",
                "mm_sdxl_v10_beta.ckpt",
                "temporaldiff-v1-animatediff.ckpt",
            ]
            logger.info(f"⚠️  Using default motion module list (extension may not be installed)")
            return defaults
        except Exception as exc:
            logger.warning(f"❌ Failed to discover motion modules: {exc}")
            return []
```

**Update refresh_all() method:**

```python
    def refresh_all(self) -> None:
        """Refresh all WebUI resource caches."""
        self.resources.models = self.refresh_models()
        self.resources.vaes = self.refresh_vaes()
        self.resources.samplers = self.refresh_samplers()
        self.resources.schedulers = self.refresh_schedulers()
        self.resources.loras = self.refresh_loras()
        self.resources.upscalers = self.refresh_upscalers()
        self.resources.motion_modules = self.refresh_motion_modules()  # NEW
        self.resources.last_refresh = time.time()
```

**Expected Diff:**
- New refresh_motion_modules() method (30+ lines)
- Add motion_modules refresh to refresh_all()

---

## Step 3: Create AnimateDiff Stage Card

### File: `src/gui/stage_cards_v2/animatediff_stage_card_v2.py` (NEW)

**Create stage card widget:**

```python
"""AnimateDiff stage card for Pipeline tab."""

from __future__ import annotations

import logging
import tkinter as tk
from tkinter import ttk
from typing import Any

from src.gui.stage_cards_v2.base_stage_card_v2 import BaseStageCardV2

logger = logging.getLogger(__name__)


class AnimateDiffStageCardV2(BaseStageCardV2):
    """Stage card for AnimateDiff video generation configuration.
    
    AnimateDiff generates short video clips (8-24 frames) with temporal coherence
    by injecting motion modules into the Stable Diffusion generation process.
    
    UI Elements:
        - Enable toggle
        - Motion module dropdown
        - Video length slider (frames)
        - FPS spinbox
        - Closed loop mode dropdown
        - Advanced section (context batch, stride, overlap)
    """
    
    def __init__(self, parent: tk.Widget, app_state: Any, **kwargs):
        """Initialize AnimateDiff stage card.
        
        Args:
            parent: Parent widget
            app_state: AppStateV2 instance (for motion module cache)
            **kwargs: Additional arguments passed to BaseStageCardV2
        """
        super().__init__(
            parent=parent,
            app_state=app_state,
            title="AnimateDiff (Video Generation)",
            config_section="animatediff",
            **kwargs
        )
        self.app_state = app_state
        
        # Create UI
        self._create_widgets()
    
    def _create_widgets(self) -> None:
        """Create AnimateDiff configuration widgets."""
        # Enable toggle (inherited from base)
        self._create_enable_toggle()
        
        # Motion module section
        self._create_motion_module_section()
        
        # Video parameters section
        self._create_video_params_section()
        
        # Advanced section (collapsible)
        self._create_advanced_section()
    
    def _create_motion_module_section(self) -> None:
        """Create motion module selection dropdown."""
        frame = ttk.Frame(self.content_frame, style="Dark.TFrame")
        frame.pack(fill=tk.X, pady=(8, 4))
        
        # Label
        label = ttk.Label(
            frame,
            text="Motion Module:",
            style="Dark.TLabel",
            width=18,
        )
        label.pack(side=tk.LEFT, padx=(0, 8))
        
        # Dropdown
        self.motion_module_var = tk.StringVar(value="mm_sd_v15_v2.ckpt")
        self.motion_module_dropdown = ttk.Combobox(
            frame,
            textvariable=self.motion_module_var,
            state="readonly",
            style="Dark.TCombobox",
            width=30,
        )
        self.motion_module_dropdown.pack(side=tk.LEFT, fill=tk.X, expand=True)
        
        # Populate from cache
        self._populate_motion_modules()
        
        # Refresh button
        refresh_btn = ttk.Button(
            frame,
            text="🔄",
            width=3,
            style="Dark.TButton",
            command=self._refresh_motion_modules,
        )
        refresh_btn.pack(side=tk.LEFT, padx=(4, 0))
    
    def _create_video_params_section(self) -> None:
        """Create video parameter controls."""
        # Video length (frames)
        length_frame = ttk.Frame(self.content_frame, style="Dark.TFrame")
        length_frame.pack(fill=tk.X, pady=(4, 4))
        
        ttk.Label(
            length_frame,
            text="Video Length (frames):",
            style="Dark.TLabel",
            width=18,
        ).pack(side=tk.LEFT, padx=(0, 8))
        
        self.video_length_var = tk.IntVar(value=16)
        length_slider = ttk.Scale(
            length_frame,
            from_=8,
            to=24,
            orient=tk.HORIZONTAL,
            variable=self.video_length_var,
            style="Dark.Horizontal.TScale",
        )
        length_slider.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 8))
        
        self.video_length_label = ttk.Label(
            length_frame,
            text="16",
            style="Dark.TLabel",
            width=4,
        )
        self.video_length_label.pack(side=tk.LEFT)
        
        # Update label on change
        self.video_length_var.trace_add("write", self._update_video_length_label)
        
        # FPS
        fps_frame = ttk.Frame(self.content_frame, style="Dark.TFrame")
        fps_frame.pack(fill=tk.X, pady=(4, 4))
        
        ttk.Label(
            fps_frame,
            text="Framerate (FPS):",
            style="Dark.TLabel",
            width=18,
        ).pack(side=tk.LEFT, padx=(0, 8))
        
        self.fps_var = tk.IntVar(value=12)
        fps_spinbox = ttk.Spinbox(
            fps_frame,
            from_=8,
            to=30,
            textvariable=self.fps_var,
            width=8,
            style="Dark.TSpinbox",
        )
        fps_spinbox.pack(side=tk.LEFT)
        
        # Duration display
        self.duration_label = ttk.Label(
            fps_frame,
            text="(~1.3s)",
            style="Dark.TLabel",
            font=("Segoe UI", 9, "italic"),
        )
        self.duration_label.pack(side=tk.LEFT, padx=(8, 0))
        
        # Update duration on change
        self.fps_var.trace_add("write", self._update_duration_label)
        
        # Closed loop mode
        loop_frame = ttk.Frame(self.content_frame, style="Dark.TFrame")
        loop_frame.pack(fill=tk.X, pady=(4, 4))
        
        ttk.Label(
            loop_frame,
            text="Loop Mode:",
            style="Dark.TLabel",
            width=18,
        ).pack(side=tk.LEFT, padx=(0, 8))
        
        self.closed_loop_var = tk.StringVar(value="R+")
        closed_loop_dropdown = ttk.Combobox(
            loop_frame,
            textvariable=self.closed_loop_var,
            values=["N", "R+", "R-", "A"],
            state="readonly",
            width=15,
            style="Dark.TCombobox",
        )
        closed_loop_dropdown.pack(side=tk.LEFT)
        
        # Loop mode explanation
        loop_help = ttk.Label(
            loop_frame,
            text="(N=None, R+=Forward, R-=Reverse, A=Pingpong)",
            style="Dark.TLabel",
            font=("Segoe UI", 8, "italic"),
        )
        loop_help.pack(side=tk.LEFT, padx=(8, 0))
    
    def _create_advanced_section(self) -> None:
        """Create collapsible advanced settings section."""
        # Advanced header (collapsible)
        self.advanced_frame = ttk.LabelFrame(
            self.content_frame,
            text="Advanced Settings",
            style="Dark.TLabelframe",
            padding=8,
        )
        self.advanced_frame.pack(fill=tk.X, pady=(8, 0))
        
        # Context batch size
        context_frame = ttk.Frame(self.advanced_frame, style="Dark.TFrame")
        context_frame.pack(fill=tk.X, pady=(0, 4))
        
        ttk.Label(
            context_frame,
            text="Context Batch Size:",
            style="Dark.TLabel",
            width=18,
        ).pack(side=tk.LEFT, padx=(0, 8))
        
        self.context_batch_var = tk.IntVar(value=16)
        context_spinbox = ttk.Spinbox(
            context_frame,
            from_=8,
            to=24,
            textvariable=self.context_batch_var,
            width=8,
            style="Dark.TSpinbox",
        )
        context_spinbox.pack(side=tk.LEFT)
        
        # Stride
        stride_frame = ttk.Frame(self.advanced_frame, style="Dark.TFrame")
        stride_frame.pack(fill=tk.X, pady=(4, 4))
        
        ttk.Label(
            stride_frame,
            text="Stride:",
            style="Dark.TLabel",
            width=18,
        ).pack(side=tk.LEFT, padx=(0, 8))
        
        self.stride_var = tk.IntVar(value=1)
        stride_spinbox = ttk.Spinbox(
            stride_frame,
            from_=1,
            to=4,
            textvariable=self.stride_var,
            width=8,
            style="Dark.TSpinbox",
        )
        stride_spinbox.pack(side=tk.LEFT)
        
        # Overlap
        overlap_frame = ttk.Frame(self.advanced_frame, style="Dark.TFrame")
        overlap_frame.pack(fill=tk.X, pady=(4, 0))
        
        ttk.Label(
            overlap_frame,
            text="Overlap:",
            style="Dark.TLabel",
            width=18,
        ).pack(side=tk.LEFT, padx=(0, 8))
        
        self.overlap_var = tk.IntVar(value=8)
        overlap_spinbox = ttk.Spinbox(
            overlap_frame,
            from_=0,
            to=16,
            textvariable=self.overlap_var,
            width=8,
            style="Dark.TSpinbox",
        )
        overlap_spinbox.pack(side=tk.LEFT)
    
    def _populate_motion_modules(self) -> None:
        """Populate motion module dropdown from cache."""
        if self.app_state and hasattr(self.app_state, "resources"):
            modules = getattr(self.app_state.resources, "motion_modules", [])
            if modules:
                self.motion_module_dropdown["values"] = modules
                logger.info(f"✅ Loaded {len(modules)} motion modules")
            else:
                # Default fallback
                defaults = ["mm_sd_v15_v2.ckpt", "mm_sd_v15_v3.ckpt", "mm_sdxl_v10_beta.ckpt"]
                self.motion_module_dropdown["values"] = defaults
                logger.warning("⚠️  No motion modules in cache, using defaults")
        else:
            # Minimal fallback
            self.motion_module_dropdown["values"] = ["mm_sd_v15_v2.ckpt"]
    
    def _refresh_motion_modules(self) -> None:
        """Refresh motion module list from WebUI."""
        logger.info("🔄 Refreshing motion modules from WebUI...")
        if self.app_state and hasattr(self.app_state, "webui_cache"):
            try:
                modules = self.app_state.webui_cache.refresh_motion_modules()
                self.app_state.resources.motion_modules = modules
                self._populate_motion_modules()
                logger.info(f"✅ Refreshed {len(modules)} motion modules")
            except Exception as exc:
                logger.error(f"❌ Failed to refresh motion modules: {exc}")
    
    def _update_video_length_label(self, *args) -> None:
        """Update video length display label."""
        length = self.video_length_var.get()
        self.video_length_label.config(text=str(length))
        self._update_duration_label()
    
    def _update_duration_label(self, *args) -> None:
        """Update video duration display."""
        length = self.video_length_var.get()
        fps = self.fps_var.get()
        if fps > 0:
            duration = length / fps
            self.duration_label.config(text=f"(~{duration:.1f}s)")
    
    def load_from_section(self, config: dict[str, Any]) -> None:
        """Load AnimateDiff configuration from config dict.
        
        Args:
            config: Pipeline config dict with 'animatediff' section
        """
        animatediff_cfg = config.get("animatediff", {})
        
        # Load motion module
        motion_module = animatediff_cfg.get("motion_module", "mm_sd_v15_v2.ckpt")
        self.motion_module_var.set(motion_module)
        
        # Load video parameters
        self.video_length_var.set(int(animatediff_cfg.get("video_length", 16)))
        self.fps_var.set(int(animatediff_cfg.get("fps", 12)))
        self.closed_loop_var.set(animatediff_cfg.get("closed_loop", "R+"))
        
        # Load advanced settings
        self.context_batch_var.set(int(animatediff_cfg.get("context_batch_size", 16)))
        self.stride_var.set(int(animatediff_cfg.get("stride", 1)))
        self.overlap_var.set(int(animatediff_cfg.get("overlap", 8)))
        
        # Load enable state
        enabled = config.get("pipeline", {}).get("animatediff_enabled", False)
        self.enabled_var.set(enabled)
    
    def to_config_dict(self) -> dict[str, Any]:
        """Convert current widget values to config dict.
        
        Returns:
            Dict with 'animatediff' section
        """
        return {
            "animatediff": {
                "motion_module": self.motion_module_var.get(),
                "video_length": self.video_length_var.get(),
                "fps": self.fps_var.get(),
                "closed_loop": self.closed_loop_var.get(),
                "context_batch_size": self.context_batch_var.get(),
                "stride": self.stride_var.get(),
                "overlap": self.overlap_var.get(),
                "mode": "txt2img",  # Default mode (can be extended later)
            },
            "pipeline": {
                "animatediff_enabled": self.enabled_var.get(),
            }
        }
    
    def _validate_stage_config(self) -> list[str]:
        """Validate AnimateDiff stage configuration.
        
        Returns:
            List of validation error messages (empty if valid)
        """
        errors = []
        
        # Validate video length
        length = self.video_length_var.get()
        if length < 8 or length > 24:
            errors.append("Video length must be 8-24 frames")
        
        # Validate FPS
        fps = self.fps_var.get()
        if fps < 8 or fps > 30:
            errors.append("FPS must be 8-30")
        
        # Validate context batch
        context_batch = self.context_batch_var.get()
        if context_batch > length:
            errors.append("Context batch size cannot exceed video length")
        
        return errors
```

**Expected Diff:**
- New file (400+ lines)
- AnimateDiffStageCardV2 class
- Motion module dropdown with refresh
- Video parameters section
- Advanced settings section
- load_from_section() and to_config_dict() methods

---

## Step 4: Integrate Stage Card into Pipeline Panel

### File: `src/gui/views/pipeline_panel_v2.py`

**Import AnimateDiff stage card:**

Add to imports section (around line 10-30):

```python
from src.gui.stage_cards_v2.animatediff_stage_card_v2 import AnimateDiffStageCardV2
```

**Add stage card instantiation:**

Locate the section where stage cards are created (after ADetailer card):

```python
        # ADetailer stage card
        self.adetailer_card = ADetailerStageCardV2(
            parent=self.cards_frame,
            app_state=self.app_state,
        )
        self.adetailer_card.pack(fill=tk.X, pady=(0, 8))
        
        # AnimateDiff stage card (NEW)
        self.animatediff_card = AnimateDiffStageCardV2(
            parent=self.cards_frame,
            app_state=self.app_state,
        )
        self.animatediff_card.pack(fill=tk.X, pady=(0, 8))
```

**Add to load_from_config():**

```python
    def load_from_config(self, config: dict[str, Any]) -> None:
        """Load pipeline configuration into stage cards."""
        self.txt2img_card.load_from_section(config)
        self.img2img_card.load_from_section(config)
        self.upscale_card.load_from_section(config)
        self.adetailer_card.load_from_section(config)
        self.animatediff_card.load_from_section(config)  # NEW
```

**Add to to_config_dict():**

```python
    def to_config_dict(self) -> dict[str, Any]:
        """Collect configuration from all stage cards."""
        config = {}
        
        # Merge stage card configs
        self._merge_config(config, self.txt2img_card.to_config_dict())
        self._merge_config(config, self.img2img_card.to_config_dict())
        self._merge_config(config, self.upscale_card.to_config_dict())
        self._merge_config(config, self.adetailer_card.to_config_dict())
        self._merge_config(config, self.animatediff_card.to_config_dict())  # NEW
        
        return config
```

**Expected Diff:**
- Import AnimateDiffStageCardV2
- Instantiate self.animatediff_card
- Add to load_from_config()
- Add to to_config_dict()

---

## Step 5: Extend Preset Serialization

### File: `src/gui/controllers/preset_controller.py`

**Add animatediff section to preset schema:**

Locate the preset validation or schema definition (around line 50-100):

```python
def _validate_preset_structure(preset: dict[str, Any]) -> bool:
    """Validate preset has required sections."""
    required_sections = ["txt2img", "img2img", "upscale", "adetailer", "animatediff", "pipeline"]
    return all(section in preset for section in required_sections)
```

**Add animatediff to default preset:**

```python
def _create_default_preset() -> dict[str, Any]:
    """Create default preset with all sections."""
    return {
        "txt2img": { /* ... */ },
        "img2img": { /* ... */ },
        "upscale": { /* ... */ },
        "adetailer": { /* ... */ },
        "animatediff": {  # NEW
            "motion_module": "mm_sd_v15_v2.ckpt",
            "video_length": 16,
            "fps": 12,
            "closed_loop": "R+",
            "context_batch_size": 16,
            "stride": 1,
            "overlap": 8,
        },
        "pipeline": {
            "txt2img_enabled": True,
            "img2img_enabled": False,
            "upscale_enabled": False,
            "adetailer_enabled": False,
            "animatediff_enabled": False,  # NEW
        }
    }
```

**Expected Diff:**
- Add animatediff to required sections
- Add animatediff default config
- Add animatediff_enabled to pipeline flags

---

# TEST PLAN

## Unit Tests

### Test 1: AnimateDiff Stage Card Widget Creation

**File**: `tests/gui_v2/test_animatediff_stage_card.py`

```python
def test_animatediff_card_creation():
    """Verify AnimateDiff stage card creates all widgets."""
    import tkinter as tk
    from src.gui.stage_cards_v2.animatediff_stage_card_v2 import AnimateDiffStageCardV2
    
    root = tk.Tk()
    card = AnimateDiffStageCardV2(parent=root, app_state=None)
    
    # Verify variables exist
    assert hasattr(card, "motion_module_var")
    assert hasattr(card, "video_length_var")
    assert hasattr(card, "fps_var")
    assert hasattr(card, "closed_loop_var")
    
    # Verify defaults
    assert card.video_length_var.get() == 16
    assert card.fps_var.get() == 12
    assert card.motion_module_var.get() == "mm_sd_v15_v2.ckpt"
    
    root.destroy()
```

---

### Test 2: Load from Config

**File**: `tests/gui_v2/test_animatediff_stage_card.py`

```python
def test_animatediff_card_load_from_config():
    """Verify stage card loads config correctly."""
    import tkinter as tk
    from src.gui.stage_cards_v2.animatediff_stage_card_v2 import AnimateDiffStageCardV2
    
    root = tk.Tk()
    card = AnimateDiffStageCardV2(parent=root, app_state=None)
    
    config = {
        "animatediff": {
            "motion_module": "test_motion.ckpt",
            "video_length": 20,
            "fps": 24,
            "closed_loop": "A",
        },
        "pipeline": {
            "animatediff_enabled": True,
        }
    }
    
    card.load_from_section(config)
    
    assert card.motion_module_var.get() == "test_motion.ckpt"
    assert card.video_length_var.get() == 20
    assert card.fps_var.get() == 24
    assert card.closed_loop_var.get() == "A"
    assert card.enabled_var.get() is True
    
    root.destroy()
```

---

### Test 3: To Config Dict

**File**: `tests/gui_v2/test_animatediff_stage_card.py`

```python
def test_animatediff_card_to_config_dict():
    """Verify stage card exports config correctly."""
    import tkinter as tk
    from src.gui.stage_cards_v2.animatediff_stage_card_v2 import AnimateDiffStageCardV2
    
    root = tk.Tk()
    card = AnimateDiffStageCardV2(parent=root, app_state=None)
    
    # Set values
    card.motion_module_var.set("custom_motion.ckpt")
    card.video_length_var.set(18)
    card.fps_var.set(15)
    card.enabled_var.set(True)
    
    config = card.to_config_dict()
    
    assert config["animatediff"]["motion_module"] == "custom_motion.ckpt"
    assert config["animatediff"]["video_length"] == 18
    assert config["animatediff"]["fps"] == 15
    assert config["pipeline"]["animatediff_enabled"] is True
    
    root.destroy()
```

---

### Test 4: Preset Round-Trip

**File**: `tests/gui_v2/test_preset_controller_v2.py`

```python
def test_preset_includes_animatediff(tmp_path):
    """Verify preset saves/loads animatediff config."""
    from src.gui.controllers.preset_controller import PresetController
    
    controller = PresetController(presets_dir=tmp_path)
    
    config = {
        "txt2img": {},
        "animatediff": {
            "motion_module": "test_motion.ckpt",
            "video_length": 20,
            "fps": 24,
        },
        "pipeline": {
            "animatediff_enabled": True,
        }
    }
    
    # Save preset
    controller.save_preset("test_animatediff", config)
    
    # Load preset
    loaded = controller.load_preset("test_animatediff")
    
    assert loaded["animatediff"]["motion_module"] == "test_motion.ckpt"
    assert loaded["animatediff"]["video_length"] == 20
    assert loaded["pipeline"]["animatediff_enabled"] is True
```

---

## Manual GUI Testing

### Test 5: Pipeline Tab Integration

**Steps:**
1. Launch StableNew GUI
2. Navigate to Pipeline tab
3. Scroll to bottom (AnimateDiff card should appear after ADetailer)
4. Verify widgets:
   - Enable checkbox
   - Motion module dropdown
   - Video length slider
   - FPS spinbox
   - Closed loop dropdown
   - Advanced section (expandable)

**Expected:**
- AnimateDiff card renders correctly
- Dark mode theming applied
- All widgets functional

---

### Test 6: Motion Module Discovery

**Steps:**
1. Open Pipeline tab
2. Click refresh button (🔄) next to motion module dropdown
3. Verify dropdown populates with available modules

**Expected:**
- If AnimateDiff extension installed: real module list
- If extension not installed: default fallback list
- No crashes or errors

---

### Test 7: Preset Save/Load

**Steps:**
1. Configure AnimateDiff parameters (custom values)
2. Enable AnimateDiff stage
3. Save preset as "test_video_preset"
4. Change AnimateDiff values
5. Load "test_video_preset"

**Expected:**
- AnimateDiff config restored to saved values
- Enable state preserved
- No data loss

---

# VALIDATION CHECKLIST

Before marking this PR complete, verify:

## Code Changes
- [ ] AnimateDiffStageCardV2 created in stage_cards_v2/
- [ ] Motion module cache added to app_state
- [ ] Motion module discovery added to webui_cache
- [ ] Stage card integrated into pipeline_panel_v2
- [ ] Preset serialization extended for animatediff
- [ ] Dark mode theming applied consistently

## Tests
- [ ] Stage card unit tests pass
- [ ] Preset round-trip test passes
- [ ] Manual GUI testing completed

## UI/UX
- [ ] AnimateDiff card appears in Pipeline tab
- [ ] Motion module dropdown functional
- [ ] Video parameters update duration label
- [ ] Advanced section collapsible
- [ ] Dark mode styling consistent

## Architecture Compliance
- [ ] No pipeline logic in GUI layer
- [ ] Stage card follows BaseStageCardV2 pattern
- [ ] Preset system extended properly
- [ ] No breaking changes to existing stage cards

---

# RISKS & MITIGATIONS

## Risk 1: Motion Module Discovery Fails

**Impact**: Dropdown empty or shows only defaults

**Mitigation**:
- Fallback to common default modules
- Clear warning message if extension not detected
- Manual text entry support (future)

---

## Risk 2: Advanced Section Too Complex

**Impact**: User confusion about stride/overlap

**Mitigation**:
- Tooltip explanations (hover text)
- Defaults work for 95% of use cases
- Collapsible section (hidden by default)

---

# NEXT STEPS (Post-Implementation)

1. **Merge PR-VIDEO-002** → AnimateDiff GUI functional
2. **Begin PR-VIDEO-003** → Learning integration
3. **Add tooltips** → Explain motion module types
4. **Add video preview** → Show thumbnail or first frame
5. **Add ControlNet integration** → Motion-guided video (future)

---

**End of PR-VIDEO-002**

This PR adds GUI support for AnimateDiff configuration. Phase 3 (PR-VIDEO-003) will add learning integration.
