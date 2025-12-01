# Pipeline Config, Logging, Presets, and ADetailer Discovery - V2-P1

## Overview

This document maps the canonical V2 GUI components for pipeline left-column config, bottom logging, presets, and ADetailer. Analysis conducted via codebase inspection without making changes.

## Pipeline Left-Column Config

### Canonical V2 Component: SidebarPanelV2
- **File**: `src/gui/sidebar_panel_v2.py`
- **Integration**: Instantiated in `PipelineTabFrameV2` left column (column 0)
- **Responsibilities**:
  - Pipeline stage toggles (txt2img, img2img/adetailer, upscale)
  - Preset selection dropdown
  - Global negative prompt controls
  - LoRA runtime controls

### Pipeline Config Panel
- **File**: `src/gui/views/pipeline_config_panel_v2.py`
- **Integration**: Referenced but not directly instantiated in current V2 layout
- **Features**: Stage enable/disable checkboxes including "Enable img2img/adetailer"

### Current Status
- SidebarPanelV2 is properly integrated in PipelineTabFrameV2 left column
- Pipeline config panel exists but may need wiring for full V2 integration

## Bottom Logging

### Canonical V2 Component: LogTracePanelV2
- **File**: `src/gui/log_trace_panel_v2.py`
- **Integration**: Instantiated in `main_window_v2.py` bottom_zone
- **Features**:
  - Collapsible panel showing recent log entries
  - Log level filtering (DEBUG, INFO, WARNING, ERROR)
  - Auto-scroll to latest entries
  - Conditional creation based on gui_log_handler presence

### Current Status
- Fully integrated in V2 main window bottom zone
- Wired to InMemoryLogHandler for GUI logging

## Presets

### Config Management: ConfigManager
- **File**: `src/utils/config.py`
- **Features**:
  - `list_presets()` method scanning `presets/*.json` files
  - `load_preset(name)` for loading preset configurations
  - Relative path resolution for presets directory

### GUI Integration: SidebarPanelV2
- **File**: `src/gui/sidebar_panel_v2.py`
- **Features**:
  - Preset dropdown populated via `ConfigManager.list_presets()`
  - Preset loading triggers config updates

### Preset Files
- **Directory**: `presets/`
- **Files Present**: Multiple JSON files including `default.json`, `Beast_Boss_Juggernaut_SDXL.json`, etc.
- **Status**: Directory exists with valid preset files

### Current Status
- ConfigManager properly resolves relative "presets" path
- SidebarPanelV2 dropdown populated and functional
- Preset loading mechanism in place

## ADetailer

### Pipeline Stage Implementation
- **Stage Type**: "adetailer" included in `StageType` literal in `src/pipeline/stage_sequencer.py`
- **Executor Method**: `run_adetailer()` in `src/pipeline/executor.py`
- **Integration**: Runs between img2img and upscale stages in pipeline
- **Config**: Uses `adetailer_*` prefixed settings from config

### GUI Config Panel
- **File**: `src/gui/adetailer_config_panel.py`
- **Features**:
  - Full configuration UI for ADetailer settings
  - Model selection (face_yolov8n.pt, hand_yolov8n.pt, etc.)
  - Detection confidence, mask feather, sampler, scheduler controls
  - Prompt and negative prompt fields
  - Enable/disable toggle with UI state management

### Current GUI Integration
- **Stage Toggle**: Combined with img2img as "Enable img2img/adetailer" in pipeline config panels
- **No Dedicated Stage Card**: No `adetailer_stage_card_v2.py` in `src/gui/stage_cards_v2/`
- **Pipeline Config**: Single checkbox controls both img2img and adetailer stages

### Current Status
- Pipeline stage fully implemented and tested
- Config panel exists but not integrated into V2 GUI
- Treated as extension of img2img stage rather than separate pipeline stage in GUI

## Implementation Status

**PR-031 (Pipeline Left-Column Config Wiring)**: ✅ **COMPLETED**

- PipelineConfigPanelV2 instantiated in PipelineTabFrameV2 left column below SidebarPanelV2
- Wired to AppController and AppStateV2 for config access and change notifications
- Test added: `test_pipeline_left_column_config_v2.py` validates structure and wiring
- No changes to presets, logging, or ADetailer functionality

**PR-032 (Bottom Logging Surface)**: ✅ **COMPLETED**

- InMemoryLogHandler created in AppController and attached to root logger
- Passed to MainWindowV2 for LogTracePanelV2 instantiation
- Bottom zone layout fixed with grid: LogTracePanelV2 above StatusBarV2
- LogTracePanelV2 refreshes automatically every second
- Tests extended to validate handler attachment and panel presence

**PR-033 (Presets Hookup)**: ⏳ PENDING  
**PR-034 (ADetailer Stage & GUI)**: ⏳ PENDING

## Migration Notes

- ADetailer currently bundled with img2img in GUI but separate in pipeline
- Pipeline config panel exists but may need V2-specific integration
- All core components identified and ready for implementation PRs</content>
<parameter name="filePath">c:\Users\rob\projects\StableNew\docs\discovery\PIPELINE_CONFIG_LOGGING_PRESETS_ADetailer_DISCOVERY_V2-P1.md
