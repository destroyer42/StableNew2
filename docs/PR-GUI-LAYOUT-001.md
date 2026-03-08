# PR-GUI-LAYOUT-001: Pipeline Tab Layout & UX Improvements

**Status**: 🟡 Specification  
**Priority**: MEDIUM  
**Effort**: MEDIUM (1 week)  
**Phase**: GUI Layout Optimization  
**Date**: 2025-12-27

---

## Context & Motivation

### Problem Statement

Multiple layout issues reduce usability and efficient use of screen space:
- Output Settings frame has inefficient layout (Filename field unnecessary, elements cramped)
- Reprocess panel elements use multiple rows when could fit fewer
- Preview panel not optimized for thumbnail + metadata display
- Prompt fields fixed at small size instead of expandable

### Why This Matters

1. **Screen Real Estate**: Better layouts fit more useful information
2. **Workflow Efficiency**: Fewer clicks, less scrolling
3. **Visual Clarity**: Better organization improves comprehension

### Current Architecture

**Sidebar Panel**: Fixed width (300-400px), scrollable  
**Center Panel**: Expandable, contains stage configs  
**Right Panel**: Fixed width, contains queue/preview

### Reference

Based on discovery in [D-GUI-004](D-GUI-004-Pipeline-Tab-Dark-Mode-UX.md), issues 1.g-h, 1.k-m, 1.p-q, 2.k, 3.b-c

---

## Goals & Non-Goals

### ✅ Goals

1. **Optimize Output Settings Layout**
   - Remove Filename label/textbox (filenaming is hardcoded)
   - Widen Output Dir to span full frame
   - Move Format, Batch Size, Seed Mode to single row below
   
2. **Optimize Reprocess Panel Layout**
   - Make description span full width (single line)
   - Move 3 buttons (Select Images, Select Folder, Clear) to same row
   - Move max width/height spin boxes next to Filter checkbox
   - Consolidate Stages checkboxes to single row

3. **Optimize Preview Panel Layout**
   - Move thumbnail to far right
   - Move metadata to left of thumbnail
   - Expand positive/negative prompts to show full text

4. **Make Prompt Fields Expandable**
   - Change Txt2Img prompt fields to 3 lines with scrollbars
   - Auto-expand if text exceeds visible area

### ❌ Non-Goals

1. **Functionality Changes**: Only layout, no behavior changes
2. **Dark Mode**: Already handled in PR-GUI-DARKMODE-001
3. **New Features**: Not adding capabilities

---

## Allowed Files

### ✅ Files to Modify

| File | Reason | Lines Changed (Est.) |
|------|--------|----------------------|
| `src/gui/output_settings_panel_v2.py` | Remove Filename, reorganize layout | 40 |
| `src/gui/panels_v2/reprocess_panel_v2.py` | Optimize button rows, consolidate checkboxes | 60 |
| `src/gui/preview_panel_v2.py` | Reorganize thumbnail + metadata | 80 |
| `src/gui/stage_cards_v2/txt2img_stage_card_v2.py` | Make prompt fields expandable | 30 |

**Total**: 4 files, ~210 lines

### ❌ Forbidden Files

| File/Directory | Reason |
|----------------|--------|
| `src/pipeline/**` | No pipeline changes |
| `src/builders/**` | No builder changes |

---

## Implementation Plan

### Step 1: Remove Filename from Output Settings

**File**: `src/gui/output_settings_panel_v2.py`

**Remove**:
```python
self._build_row(
    parent, "Filename", ttk.Entry(parent, textvariable=self.filename_pattern_var), 2, 0
)
```

**Widen Output Dir**:
```python
# Output dir now spans columns 0-3
label_widget.grid(row=1, column=0, sticky="w", padx=(0, 8), pady=(0, 4))
container.grid(row=1, column=1, columnspan=3, sticky="ew", pady=(0, 4))
```

**Consolidate Format/Batch/Seed to row 2**:
```python
format_frame = ttk.Frame(parent)
format_frame.grid(row=2, column=0, columnspan=4, sticky="ew", pady=(0, 4))

# Format dropdown
ttk.Label(format_frame, text="Format:").pack(side="left", padx=(0, 4))
format_combo.pack(side="left", padx=(0, 16))

# Batch Size
ttk.Label(format_frame, text="Batch Size:").pack(side="left", padx=(0, 4))
batch_spin.pack(side="left", padx=(0, 16))

# Seed Mode
ttk.Label(format_frame, text="Seed Mode:").pack(side="left", padx=(0, 4))
seed_combo.pack(side="left")
```

### Step 2: Optimize Reprocess Panel Layout

**File**: `src/gui/panels_v2/reprocess_panel_v2.py`

**Make description single-line**:
```python
desc = ttk.Label(
    self,
    text="Select existing images to send through pipeline stages",
    style=BODY_LABEL_STYLE,
    wraplength=600,  # Increased from 300
)
```

**Consolidate buttons to single row**:
```python
button_row = ttk.Frame(selection_frame)
button_row.grid(row=0, column=0, sticky="ew", pady=2)

self.select_images_button.grid(row=0, column=0, sticky="ew", padx=(0, 4))
self.select_folder_button.grid(row=0, column=1, sticky="ew", padx=(0, 4))
self.clear_button.grid(row=0, column=2, sticky="ew")
```

**Move dimension filters next to checkbox**:
```python
dim_row = ttk.Frame(folder_options_frame)
dim_row.pack(fill="x", pady=2)

self.dimension_filter_check.pack(side="left", padx=(0, 12))
ttk.Label(dim_row, text="Max width:").pack(side="left", padx=(0, 4))
self.max_width_spinbox.pack(side="left", padx=(0, 12))
ttk.Label(dim_row, text="Max height:").pack(side="left", padx=(0, 4))
self.max_height_spinbox.pack(side="left")
```

**Consolidate stage checkboxes**:
```python
stage_row = ttk.Frame(stages_frame)
stage_row.pack(fill="x", pady=2)

self.img2img_check.pack(side="left", padx=(0, 16))
self.adetailer_check.pack(side="left", padx=(0, 16))
self.upscale_check.pack(side="left")
```

### Step 3: Optimize Preview Panel Layout

**File**: `src/gui/preview_panel_v2.py`

**Create horizontal layout**:
```python
# Main container with thumbnail on right
content_frame = ttk.Frame(self.body, style=SURFACE_FRAME_STYLE)
content_frame.pack(fill="both", expand=True)
content_frame.columnconfigure(0, weight=1)  # metadata column
content_frame.columnconfigure(1, weight=0)  # thumbnail column

# Metadata column (left)
metadata_frame = ttk.Frame(content_frame, style=SURFACE_FRAME_STYLE)
metadata_frame.grid(row=0, column=0, sticky="nsew", padx=(0, 8))

# Thumbnail column (right)
thumbnail_frame = ttk.Frame(content_frame, style=SURFACE_FRAME_STYLE)
thumbnail_frame.grid(row=0, column=1, sticky="ne")
```

**Expand prompt fields**:
```python
self.prompt_text = tk.Text(
    metadata_frame,
    height=5,  # Increased from 3
    wrap="word",
    bg=BACKGROUND_ELEVATED,
    fg=TEXT_PRIMARY,
    relief="flat",
    state="disabled",
)
# Add scrollbar
prompt_scrollbar = ttk.Scrollbar(metadata_frame, command=self.prompt_text.yview)
self.prompt_text.configure(yscrollcommand=prompt_scrollbar.set)
```

### Step 4: Make Txt2Img Prompt Fields Expandable

**File**: `src/gui/stage_cards_v2/txt2img_stage_card_v2.py`

**Update prompt field height**:
```python
self.positive_prompt_text = tk.Text(
    prompt_frame,
    height=3,  # Default 3 lines
    wrap="word",
    # ... existing options
)

# Add scrollbar
positive_scrollbar = ttk.Scrollbar(
    prompt_frame,
    command=self.positive_prompt_text.yview
)
self.positive_prompt_text.configure(yscrollcommand=positive_scrollbar.set)
positive_scrollbar.pack(side="right", fill="y")
```

---

## Testing Plan

### Manual Testing

1. **Output Settings**:
   - Verify Filename field removed
   - Verify Output Dir spans full width
   - Verify Format/Batch/Seed fit on one row
   - Verify tooltips work

2. **Reprocess Panel**:
   - Verify description is single line
   - Verify 3 buttons on same row
   - Verify dimension filters next to checkbox
   - Verify stage checkboxes on same row

3. **Preview Panel**:
   - Verify thumbnail on right
   - Verify metadata on left
   - Verify prompts show full text
   - Verify scrollbars work

4. **Prompt Fields**:
   - Verify 3 line default height
   - Verify scrollbars appear when needed
   - Verify text fully visible

---

## Verification Criteria

### ✅ Success Criteria

1. **Output Settings**
   - [ ] Filename field gone
   - [ ] Layout more compact
   - [ ] All controls accessible

2. **Reprocess Panel**
   - [ ] Fewer rows used
   - [ ] All controls accessible
   - [ ] No horizontal scroll needed

3. **Preview Panel**
   - [ ] Thumbnail visible on right
   - [ ] Metadata readable on left
   - [ ] Full prompts visible

4. **Prompt Fields**
   - [ ] 3 lines visible by default
   - [ ] Scrollbars work
   - [ ] All text accessible

---

## Risk Assessment

### Low Risk Areas

✅ **Output Settings**: Simple field removal  
✅ **Prompt Fields**: Just height + scrollbar

### Medium Risk Areas

⚠️ **Reprocess Panel**: Multiple layout changes
- **Mitigation**: Test each change independently

⚠️ **Preview Panel**: Complex reorganization
- **Mitigation**: Maintain existing widget references

---

## Tech Debt Removed

✅ **Unnecessary Filename field**: Removed unused config  
✅ **Cramped layouts**: Better space utilization  
✅ **Hidden prompt text**: Fully visible with scrolling

**Net Tech Debt**: -3 layout issues

---

## Architecture Alignment

### ✅ Enforces Architecture v2.6

- GUI-only changes
- No pipeline modifications
- Preserves all functionality

---

## Timeline & Effort

| Task | Effort | Duration |
|------|--------|----------|
| Step 1: Output Settings | 4 hours | Day 1 |
| Step 2: Reprocess Panel | 8 hours | Day 2-3 |
| Step 3: Preview Panel | 12 hours | Day 4-5 |
| Step 4: Prompt Fields | 4 hours | Day 6 |
| Testing | 4 hours | Day 7 |

**Total**: 5-7 days

---

## Approval & Sign-Off

**Planner**: GitHub Copilot  
**Executor**: TBD  
**Reviewer**: Rob

**Approval Status**: 🟡 Awaiting approval

---

**Document Status**: ✅ Complete  
**Ready for Implementation**: ✅ Yes (pending approval)
