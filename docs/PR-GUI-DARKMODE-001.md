# PR-GUI-DARKMODE-001: Pipeline Tab Dark Mode Theme Completion

**Status**: 🟡 Specification  
**Priority**: HIGH  
**Effort**: SMALL (2-3 days)  
**Phase**: GUI Polish Phase  
**Date**: 2025-12-26

---

## Context & Motivation

### Problem Statement

Multiple widgets in the Pipeline Tab are not using the dark mode theme, creating visual inconsistency and poor UX:
- ❌ Buttons appear in default (light) theme against dark background
- ❌ Spinboxes have white backgrounds
- ❌ Checkboxes and labels use default styling
- ❌ Frames don't use consistent dark surface colors

This creates a jarring, unprofessional appearance and makes the app harder to use.

### Why This Matters

1. **User Experience**: Consistent dark mode reduces eye strain and looks professional
2. **Brand Identity**: Dark mode is StableNew's visual identity
3. **Quick Win**: Pure styling changes with zero logic impact
4. **Foundation**: Must be fixed before other GUI improvements

### Current Architecture

Dark mode theme system exists in `src/gui/theme_v2.py`:
- ✅ Styles defined: `Dark.TButton`, `Dark.TSpinbox`, `Dark.TCombobox`, `Dark.TCheckbutton`
- ✅ Color constants: `BACKGROUND_ELEVATED`, `ASWF_DARK_GREY`, `TEXT_PRIMARY`
- ✅ Style constants exported: `DARK_BUTTON_STYLE`, `CARD_FRAME_STYLE`

**Issue**: Styles not consistently applied when widgets are created

### Reference

Based on discovery in [D-GUI-004](D-GUI-004-Pipeline-Tab-Dark-Mode-UX.md) and user-reported issues in [Outstanding Issues-26DEC2025-1649.md](Oustanding%20Issues-26DEC2025-1649.md)

---

## Goals & Non-Goals

### ✅ Goals

1. **Apply Dark Mode to All Unstyle Widgets**
   - Buttons: Actions, Refresh, Load Config, Apply Config, Add to Job, Show Preview, Browse
   - Spinboxes: Batch Size
   - Checkboxes: Show preview thumbnails, Global Prompts enable, Reprocess filters
   - Text fields: Running Job panel fields
   - Labels: SDXL Refiner, Hires Fix, Global Prompts
   - Frames: Global Prompts, Filter Results, Stages to Apply, Reprocess Images

2. **Maintain Visual Consistency**
   - All buttons use `Dark.TButton` style
   - All spinboxes use `Dark.TSpinbox` style
   - All checkboxes use `Dark.TCheckbutton` style
   - All frames use `CARD_FRAME_STYLE`

3. **Zero Logic Changes**
   - Only styling modifications
   - No behavior changes
   - No layout changes

### ❌ Non-Goals

1. **Layout Improvements**: Separate PR (PR-GUI-LAYOUT-001)
2. **Functional Fixes**: Separate PR (PR-GUI-FUNC-001)
3. **New Features**: Out of scope
4. **Theme System Refactoring**: Theme architecture stays as-is

---

## Allowed Files

### ✅ Files to Modify

| File | Reason | Lines Changed (Est.) |
|------|--------|----------------------|
| `src/gui/sidebar_panel_v2.py` | Apply dark styles to buttons, spinboxes, frames | 30 |
| `src/gui/output_settings_panel_v2.py` | Apply dark style to Browse button, Batch Size spinbox | 5 |
| `src/gui/panels_v2/running_job_panel_v2.py` | Apply dark style to text fields | 5 |
| `src/gui/panels_v2/preview_panel_v2.py` | Apply dark style to checkbox | 3 |
| `src/gui/reprocess_panel_v2.py` | Apply dark styles throughout (if exists) | 20 |

**Total**: 5 files, ~63 lines

### ❌ Forbidden Files (DO NOT TOUCH)

| File/Directory | Reason |
|----------------|--------|
| `src/controller/**` | No logic changes |
| `src/pipeline/**` | No pipeline changes |
| `src/gui/theme_v2.py` | Theme definitions already correct |
| `src/gui/main_window_v2.py` | No main window changes |

**Rationale**: This is a pure styling PR. No logic, layout, or architecture changes.

---

## Implementation Plan

### Step 1: Sidebar Panel Buttons (sidebar_panel_v2.py)

**Widgets to Update**:
- Actions button (line ~540)
- Refresh button (line ~570)
- Load Config button
- Apply Config button
- Add to Job button
- Show Preview button
- Browse button

**Pattern**:
```python
# Before
btn = ttk.Button(parent, text="Actions")

# After
btn = ttk.Button(parent, text="Actions", style="Dark.TButton")
```

**Locations**:
1. Pipeline Presets Frame: Actions button
2. Pack Selector Frame: Refresh, Load Config, Apply Config, Add to Job, Show Preview buttons
3. Output Settings Frame: Browse button

### Step 2: Spinboxes (sidebar_panel_v2.py, output_settings_panel_v2.py)

**Widgets to Update**:
- Batch Size spinbox

**Pattern**:
```python
# Before
spin = ttk.Spinbox(parent, from_=1, to=99)

# After
spin = ttk.Spinbox(parent, from_=1, to=99, style="Dark.TSpinbox")
```

### Step 3: Global Prompts Frame (sidebar_panel_v2.py)

**Widgets to Update**:
- Frame itself
- Enable checkboxes (positive and negative)
- Save buttons (positive and negative)
- Labels

**Pattern**:
```python
# Frame
frame = ttk.Frame(parent, style=CARD_FRAME_STYLE)

# Checkboxes
chk = ttk.Checkbutton(frame, text="Enable", style="Dark.TCheckbutton")

# Buttons
btn = ttk.Button(frame, text="Save", style="Dark.TButton")

# Labels
lbl = ttk.Label(frame, text="Global Positive:", style=BODY_LABEL_STYLE)
```

### Step 4: Reprocess Images Panel

**Widgets to Update**:
- Select Images button
- Select Folder(s) button
- Clear Selection button
- Refresh Filter button
- Filter Results frame
- Stages to Apply frame
- All checkboxes (img2img, Adetailer, Upscale)
- All labels

**Pattern**: Same as above, consistently apply dark styles

### Step 5: Running Job Panel (running_job_panel_v2.py)

**Widgets to Update**:
- 3 text fields (Seed, ETA, other fields)

**Pattern**:
```python
# Text fields
entry = ttk.Entry(parent, style="Dark.TEntry")
```

### Step 6: Preview Panel (preview_panel_v2.py)

**Widgets to Update**:
- "Show preview thumbnails" checkbox

**Pattern**:
```python
chk = ttk.Checkbutton(parent, text="Show preview thumbnails", style="Dark.TCheckbutton")
```

### Step 7: Center Panel Labels

**Widgets to Update**:
- SDXL Refiner label
- Hires Fix label

**Pattern**:
```python
lbl = ttk.Label(parent, text="SDXL Refiner", style=HEADING_LABEL_STYLE)
```

---

## Testing Plan

### Manual Testing

1. **Visual Inspection**:
   ```bash
   python -m src.main
   ```
   - Navigate to Pipeline Tab
   - Check each widget for dark mode styling
   - Compare before/after screenshots

2. **Widget Checklist**:
   - [ ] Actions button dark
   - [ ] Refresh button dark
   - [ ] Load/Apply/Add buttons dark
   - [ ] Browse button dark
   - [ ] Batch Size spinbox dark
   - [ ] Global Prompts frame dark
   - [ ] Reprocess buttons dark
   - [ ] Preview checkbox dark
   - [ ] Running Job fields dark
   - [ ] All labels using proper styles

3. **Interaction Testing**:
   - Click all styled buttons → verify they still work
   - Adjust spinboxes → verify functionality unchanged
   - Toggle checkboxes → verify functionality unchanged

### Automated Testing

No new tests required (zero logic changes). Existing tests should pass.

```bash
pytest tests/gui_v2/ -v
```

Expected: All existing GUI tests pass

---

## Verification Criteria

### ✅ Success Criteria

1. **Visual Consistency**
   - [ ] All buttons in Pipeline Tab use dark theme
   - [ ] All spinboxes use dark theme
   - [ ] All checkboxes use dark theme
   - [ ] All frames use consistent dark surface
   - [ ] All labels use appropriate dark label styles

2. **No Regressions**
   - [ ] All existing functionality works
   - [ ] No layout changes
   - [ ] No controller/logic changes

3. **Code Quality**
   - [ ] Consistent style attribute usage
   - [ ] No hardcoded colors
   - [ ] Uses theme constants (DARK_BUTTON_STYLE, etc.)

### ❌ Failure Criteria

Any of:
- Widget functionality broken
- Layout changed
- Light mode elements still visible
- Inconsistent styling

---

## Risk Assessment

### Low Risk Areas

✅ **Pure Styling**: Only `style=` attribute changes  
✅ **No Logic**: Zero behavior modifications  
✅ **Reversible**: Easy to revert style attributes

### Medium Risk Areas

⚠️ **Widget Discovery**: May miss some widgets without thorough review
- **Mitigation**: Systematic file-by-file review

⚠️ **Theme Compatibility**: Some widgets may not support dark styles
- **Mitigation**: Test each widget type, fallback to manual styling if needed

### High Risk Areas

❌ **None**: This is a low-risk cosmetic PR

### Rollback Plan

If issues found:
1. Revert style attribute changes (git revert)
2. No controller/state rollback needed (none modified)
3. Test suite should catch any breakage

---

## Tech Debt Removed

✅ **Visual Inconsistency**: Removes light mode artifacts  
✅ **Theme Adherence**: Makes all widgets follow dark mode standard  
✅ **User Complaints**: Addresses 18+ styling issues

**Net Tech Debt**: -18 issues

---

## Architecture Alignment

### ✅ Enforces Architecture v2.6

- No changes to pipeline (PromptPack → NJR → Queue → Runner)
- No changes to controller logic
- Only GUI presentation layer affected

### ✅ Follows Testing Standards

- Zero logic changes = no new tests required
- Existing tests validate no regressions

### ✅ Maintains Separation of Concerns

- Theme system in `theme_v2.py` (unchanged)
- Widget styling in GUI files (changed)
- Logic in controllers (unchanged)

---

## Dependencies

### External

- ✅ Tkinter/ttk - already used
- ✅ Theme system - already exists

### Internal

- ✅ `theme_v2.py` - already defines all needed styles
- ✅ Widget files - already using ttk widgets

**No new dependencies required.**

---

## Timeline & Effort

### Breakdown

| Task | Effort | Duration |
|------|--------|----------|
| Step 1: Sidebar buttons | 2 hours | Day 1 AM |
| Step 2: Spinboxes | 1 hour | Day 1 PM |
| Step 3: Global Prompts frame | 2 hours | Day 1 PM |
| Step 4: Reprocess panel | 3 hours | Day 2 AM |
| Step 5: Running Job panel | 1 hour | Day 2 PM |
| Step 6: Preview panel | 1 hour | Day 2 PM |
| Step 7: Center panel labels | 1 hour | Day 2 PM |
| Testing & validation | 4 hours | Day 3 |
| Buffer | 2 hours | Day 3 |

**Total**: 2-3 days

---

## Approval & Sign-Off

**Planner**: GitHub Copilot (Multi-agent)  
**Executor**: TBD (Codex or Rob)  
**Reviewer**: Rob (Product Owner)

**Approval Status**: 🟡 Awaiting Rob's approval

---

## Next Steps

1. **Rob reviews this PR spec**
2. **Rob approves or requests changes**
3. **Executor implements Steps 1-7**
4. **Rob validates visual consistency**
5. **Merge to `testingBranchFromWorking`**
6. **Test for 1-2 days**
7. **Merge to `main`**

---

**Document Status**: ✅ Complete  
**Ready for Implementation**: ✅ Yes (pending approval)  
**Estimated Completion**: 2025-12-29 (3 days from approval)
