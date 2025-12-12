# PR-1: Config Source Banner Implementation Details

**Date:** November 12, 2025
**Author:** GitHub Copilot
**Scope:** `src/gui/main_window.py`

## Overview

Implemented the foundation for explicit config management by disabling automatic config loading and adding a visual indicator of the current config source.

## What Was Changed

### 1. Disabled Auto-Config Loading

**Before:** Pack selection automatically loaded and applied pack-specific config to the editor.

**After:** Pack selection only updates the banner and tracks selection - no automatic config changes.

### 2. Config Source Banner

Added `config_source_banner` label at the top of the UI showing current config context:

- "Using: Pack Config" - when pack is selected but config not loaded
- "Using: Pack Config (view)" - when pack config is explicitly loaded
- "Using: Preset: [name]" - when preset is loaded
- "Using: Global Lock" - when config is locked

### 3. ConfigContext State Management

Introduced `ConfigContext` class to track:

- `source`: Current config source (PACK/PRESET/GLOBAL_LOCK)
- `editor_cfg`: Current editor configuration
- `locked_cfg`: Frozen config when locked
- `active_preset`: Currently loaded preset name
- `active_list`: Currently loaded list name

### 4. Banner Update Logic

Banner updates in exactly three places as specified:

1. **After loading preset** (`_ui_load_preset`): Shows "Using: Preset: [name]"
2. **After loading pack config** (`_ui_load_pack_config`): Shows "Using: Pack Config (view)"
3. **When toggling lock** (`_lock_config`/`_unlock_config`): Shows "Using: Global Lock"

## Why These Changes

### Problem Solved
The original implicit autoload behavior was confusing and error-prone. Users couldn't tell what config was active, and accidental pack selections would overwrite their carefully tuned settings.

### Design Decisions

**No Auto-Changes**: Pack selection became purely informational - no side effects.

**Visual Feedback**: Banner provides constant awareness of config state.

**State Machine**: `ConfigContext` provides clean separation of concerns.

**Explicit Actions**: All config changes now require deliberate user action.

## Testing

### Manual Test Case
1. Select different packs - banner shows "Using: Pack Config"
2. Click "Load Pack Config" - banner shows "Using: Pack Config (view)"
3. Load a preset - banner shows "Using: Preset: [name]"
4. Lock config - banner shows "Using: Global Lock"

### Integration Points
- Compatible with existing pack selection system
- No interference with pipeline execution
- Banner updates are thread-safe

## Risk Assessment

**Low Risk**: Purely additive changes with defensive fallbacks. Rollback simply re-enables autoload and removes banner.</content>
<parameter name="filePath">c:\Users\rober\projects\StableNew\docs\PR1_CONFIG_BANNER_IMPLEMENTATION.md
