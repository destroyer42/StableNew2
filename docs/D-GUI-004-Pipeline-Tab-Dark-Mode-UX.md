# D-GUI-004: Pipeline Tab Dark Mode & UX Issues Discovery

**Date**: 2025-12-26  
**Status**: Discovery Complete  
**Priority**: HIGH  
**Related Issues**: Outstanding Issues-26DEC2025-1649.md

---

## Executive Summary

Investigation of 40+ outstanding issues in the Pipeline Tab GUI reveals systematic problems across three categories:
1. **Dark Mode Styling** (~18 issues): Buttons, spinboxes, and widgets not using dark mode theme
2. **Functionality** (~12 issues): Non-working buttons, incorrect behavior, missing features
3. **Layout/UX** (~10 issues): Poor space utilization, unclear controls, redundant elements

## Issue Categorization

### Category 1: Dark Mode Styling Issues (PR-GUI-DARKMODE-001)

**Left Panel**:
- ❌ 'Actions' button in Pipeline Presets Frame
- ❌ 'Refresh' button in Pack Selector Frame
- ❌ 'Load Config', 'Apply Config', 'Add to Job', 'Show Preview' buttons
- ❌ 'Global Prompts' Frame
- ❌ 'Browse' button for Output Dir
- ❌ Batch Size spin button
- ❌ Reprocess Images widgets (labels, textboxes, buttons, frames, checkboxes)

**Right Panel**:
- ❌ 'Show preview thumbnails' checkbox
- ❌ Running Job text fields (3 fields)

**Center Panel**:
- ❌ SDXL Refiner label
- ❌ Hires fix label

**File Locations**:
- `src/gui/sidebar_panel_v2.py` - Main left panel
- `src/gui/panels_v2/running_job_panel_v2.py` - Running job panel
- `src/gui/panels_v2/preview_panel_v2.py` - Preview panel
- `src/gui/theme_v2.py` - Theme definitions

### Category 2: Functional Issues (PR-GUI-FUNC-001, PR-GUI-FUNC-002)

**Broken Functionality**:
- ❌ 'Refresh' button doesn't refresh Prompt Pack list (1.b)
- ❌ Global Positive/Negative save functionality unclear (1.f)
- ❌ Queue reordering not visually updating (3.d)
- ❌ Pause/Cancel Job buttons always disabled (3.f)
- ❌ Variant # not incrementing (3.g)
- ❌ Open Output Folder opens wrong location (3.g)
- ❌ Job Lifecycle Log shows nothing (3.h)
- ❌ Jobs/Metadata panel non-functional (3.h)

**Missing Features**:
- ❌ Subseed randomizer button (2.b)
- ❌ Subseed strength randomizer button (2.b)
- ❌ Face restore dropdown (GFPGAN vs Codeformers) (2.m)
- ❌ Final size calculation not working (2.n)

**File Locations**:
- `src/gui/sidebar_panel_v2.py` - Refresh, Global prompts
- `src/gui/panels_v2/queue_panel_v2.py` - Queue reordering
- `src/gui/panels_v2/running_job_panel_v2.py` - Pause/Cancel, variant, output folder

### Category 3: Layout & UX Issues (PR-GUI-LAYOUT-001)

**Space Optimization**:
- Remove 'Filename' label/textbox from Output Settings (1.g)
- Reorganize Output Settings frame (1.h)
- Consolidate Reprocess Images layout (1.k-1, 1.l, 1.m)
- Move CFG slider to span full width (2.a)
- Shorten dropdown widths, add descriptions (2.g, 2.h, 2.i, 2.j, 2.l)
- Change Prompt to 3 lines with scrollbars (2.k)
- Optimize Preview frame layout (3.b, 3.c)

**Config Improvements**:
- SDXL Refiner Start default to 80% (2.d)
- Hires Fix 'Use base model' checkbox behavior (2.f)
- Move stage checkboxes to same line (1.q)

**File Locations**:
- `src/gui/sidebar_panel_v2.py`
- `src/gui/output_settings_panel_v2.py`
- `src/gui/panels_v2/preview_panel_v2.py`

## Recommended PR Sequence

### PR-GUI-DARKMODE-001: Dark Mode Theme Completion
**Priority**: HIGH  
**Effort**: SMALL (2-3 days)  
**Files**: 7 files, ~150 lines changed  
**Focus**: Apply dark mode styles systematically to all unstyle

d widgets

### PR-GUI-FUNC-001: Core Functionality Fixes
**Priority**: HIGH  
**Effort**: MEDIUM (1 week)  
**Files**: 5 files, ~300 lines  
**Focus**: Fix broken refresh, pause/cancel, queue reordering, output folder

### PR-GUI-LAYOUT-001: Layout & UX Improvements
**Priority**: MEDIUM  
**Effort**: MEDIUM (1 week)  
**Files**: 6 files, ~400 lines  
**Focus**: Reorganize frames, optimize space, improve usability

### PR-GUI-FUNC-002: Missing Features
**Priority**: LOW  
**Effort**: SMALL (2-3 days)  
**Files**: 3 files, ~100 lines  
**Focus**: Add randomizer buttons, face restore dropdown, final size calc

### PR-GUI-CLEANUP-001: Remove Non-Functional Elements
**Priority**: LOW  
**Effort**: SMALL (1 day)  
**Files**: 2 files, ~50 lines removed  
**Focus**: Remove Job Lifecycle Log, Jobs/Metadata panel

## Technical Analysis

### Dark Mode Theme Architecture

Current theme system in `src/gui/theme_v2.py`:
- `DARK_BUTTON_STYLE = "Dark.TButton"` exists
- `Dark.TSpinbox` style exists
- `Dark.TCombobox` style exists
- `Dark.TCheckbutton` style exists

**Issue**: Not consistently applied across all widgets

**Solution**: Systematic application in widget creation

### Functional Issues Root Causes

1. **Refresh Button**: Likely missing callback wiring
2. **Pause/Cancel**: Buttons configured with `state=["disabled"]` without update logic
3. **Queue Reordering**: Queue update not triggering GUI refresh
4. **Output Folder**: Using wrong path (runs/ vs actual output dir)

### Layout Complexity

Current layout uses:
- `_SidebarCard` wrapper for sections
- Mix of grid and pack geometry managers
- Inconsistent spacing (hardcoded vs theme constants)

**Recommendation**: Standardize on grid layout with theme constants

## Dependencies & Risks

### Dependencies
- ✅ Theme system already exists (`theme_v2.py`)
- ✅ Widget styles defined
- ⚠️ Controller callbacks may need enhancement

### Risks
- **Medium**: Functional fixes may require controller/state changes
- **Low**: Dark mode styling is purely cosmetic
- **Low**: Layout changes are isolated to GUI

### Rollback Plan
Each PR is independent:
- Dark mode: Revert style assignments
- Functionality: Revert callback changes
- Layout: Revert grid/pack configurations

## Next Steps

1. **Immediate**: Create PR-GUI-DARKMODE-001 spec
2. **After PR-1**: Create PR-GUI-FUNC-001 spec
3. **Parallel**: Create PR-GUI-LAYOUT-001 spec
4. **Final**: Create PR-GUI-FUNC-002, PR-GUI-CLEANUP-001 specs

---

**Document Status**: ✅ Complete  
**Recommended Action**: Proceed with PR-GUI-DARKMODE-001 first (highest ROI, lowest risk)
