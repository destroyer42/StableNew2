# PR-GUI-LAYOUT-002: Layout Optimizations (CFG Slider, ADetailer Dropdown, Prompt Fields, Preview Panel)

**Status**: READY FOR IMPLEMENTATION  
**Priority**: Medium  
**PR Type**: GUI Layout Enhancement  
**Architecture Impact**: None (GUI-only)

---

## Context & Motivation

Several layout issues impact visual consistency and space utilization:
1. **CFG slider** doesn't extend to frame edge
2. **ADetailer Mask merge mode dropdown** is too wide
3. **Prompt fields** should be 3 lines tall with scrollbars
4. **Preview panel** layout is not optimized

**Related Outstanding Issues:**
- Issue 2a: CFG slider should span full frame width
- Issue 2g: Adetailer Mask merge mode dropdown width
- Issue 2k: Prompt field sizing (3 lines with scrollbars)
- Issue 3b: Preview frame layout optimization
- Issue 3c: Preview panel prompt display

---

## Implementation Plan

### Phase 1: CFG Slider Full Width

**File**: `src/gui/stage_cards_v2/advanced_txt2img_stage_card_v2.py`

**Current code** (line ~106-116):
```python
self.cfg_slider = EnhancedSlider(
    self.sampler_section,
    from_=1.0,
    to=30.0,
    variable=self.cfg_var,
    resolution=0.1,
    width=120,  # Fixed width
    label="",
    command=self._on_cfg_changed,
)
self.cfg_slider.grid(row=1, column=1, sticky="ew", pady=(6, 0), padx=(0, 8))
```

**Issue**: The `width=120` parameter sets a fixed width, and `sticky="ew"` doesn't expand it because the EnhancedSlider might not respect grid expansion.

**Investigation needed**: Check `src/gui/enhanced_slider.py` to see if it supports dynamic width expansion.

**Potential fixes**:

**Option A**: If EnhancedSlider supports dynamic width:
```python
self.cfg_slider = EnhancedSlider(
    self.sampler_section,
    from_=1.0,
    to=30.0,
    variable=self.cfg_var,
    resolution=0.1,
    # Remove fixed width parameter
    label="",
    command=self._on_cfg_changed,
)
self.cfg_slider.grid(row=1, column=1, sticky="ew", pady=(6, 0), padx=(0, 8))
# Ensure column 1 has weight
self.sampler_section.columnconfigure(1, weight=1)
```

**Option B**: If EnhancedSlider doesn't support dynamic width, replace with standard Scale:
```python
cfg_frame = ttk.Frame(self.sampler_section, style=SURFACE_FRAME_STYLE)
cfg_frame.grid(row=1, column=1, sticky="ew", pady=(6, 0), padx=(0, 8))
cfg_frame.columnconfigure(0, weight=1)

cfg_scale = ttk.Scale(
    cfg_frame,
    from_=1.0,
    to=30.0,
    variable=self.cfg_var,
    orient="horizontal",
    command=lambda val: self._on_cfg_changed(),
)
cfg_scale.grid(row=0, column=0, sticky="ew")

cfg_value_label = ttk.Label(
    cfg_frame,
    textvariable=self.cfg_var,
    width=5,
    style=BODY_LABEL_STYLE,
)
cfg_value_label.grid(row=0, column=1, padx=(4, 0))
```

### Phase 2: ADetailer Mask Merge Mode Dropdown Width

**File**: `src/gui/stage_cards_v2/adetailer_stage_card_v2.py`

**Current code** (line ~196):
```python
self._add_labeled_combo(
    parent,
    "Mask merge mode:",
    self.merge_var,
    self.MERGE_MODES,
    row,
)
```

**Issue**: Dropdown is as wide as longest option text. Should be narrower to align with "Mask blur" spinbox.

**Fix**: Modify `_add_labeled_combo` to accept a width parameter:

```python
def _add_labeled_combo(
    self,
    parent: ttk.Frame,
    label_text: str,
    variable: tk.StringVar,
    values: list[str],
    row: int,
    width: int | None = None,  # PR-GUI-LAYOUT-002: Optional width
) -> ttk.Combobox:
    """Add a labeled combo box at the specified row."""
    ttk.Label(parent, text=label_text, style=BODY_LABEL_STYLE).grid(
        row=row, column=0, sticky="w", pady=(4, 0)
    )
    combo = ttk.Combobox(
        parent,
        textvariable=variable,
        values=values,
        state="readonly",
        style=DARK_COMBO_STYLE,
        width=width if width else None,  # Apply width if provided
    )
    combo.grid(row=row, column=1, sticky="ew" if width is None else "w", pady=(4, 0))
    return combo
```

Then update the call:
```python
self._add_labeled_combo(
    parent,
    "Mask merge mode:",
    self.merge_var,
    self.MERGE_MODES,
    row,
    width=15,  # PR-GUI-LAYOUT-002: Limit width to align with spinboxes
)
```

### Phase 3: Prompt Fields 3 Lines with Scrollbars

**Files**:
- `src/gui/stage_cards_v2/advanced_txt2img_stage_card_v2.py`
- `src/gui/stage_cards_v2/advanced_img2img_stage_card_v2.py`
- `src/gui/stage_cards_v2/adetailer_stage_card_v2.py`
- `src/gui/stage_cards_v2/advanced_upscale_stage_card_v2.py`

**Current code** (example from txt2img, line ~260-270):
```python
ttk.Label(prompt_frame, text="Prompt:", style=BODY_LABEL_STYLE).grid(
    row=0, column=0, sticky="nw"
)
prompt_entry = ttk.Entry(
    prompt_frame,
    textvariable=self.prompt_var,
    style=DARK_ENTRY_STYLE,
)
prompt_entry.grid(row=0, column=1, sticky="ew", padx=(4, 0))
```

**Issue**: Using `ttk.Entry` for single-line input. Should use `tk.Text` with scrollbars for multi-line.

**Fix** (apply to all stage cards):

```python
# Change label text from "Prompt:" to "Positive:"
ttk.Label(prompt_frame, text="Positive:", style=BODY_LABEL_STYLE).grid(
    row=0, column=0, sticky="nw", pady=(0, 4)
)

# Create frame for Text widget + scrollbar
prompt_text_frame = ttk.Frame(prompt_frame, style=SURFACE_FRAME_STYLE)
prompt_text_frame.grid(row=0, column=1, sticky="ew", padx=(4, 0))
prompt_text_frame.columnconfigure(0, weight=1)

# Text widget (3 lines tall)
prompt_text = tk.Text(
    prompt_text_frame,
    height=3,
    wrap="word",
    bg=BACKGROUND_ELEVATED,
    fg=TEXT_PRIMARY,
    relief="solid",
    borderwidth=1,
    font=("Segoe UI", 9),
)
prompt_text.grid(row=0, column=0, sticky="ew")

# Scrollbar
prompt_scrollbar = ttk.Scrollbar(
    prompt_text_frame,
    orient="vertical",
    command=prompt_text.yview,
)
prompt_scrollbar.grid(row=0, column=1, sticky="ns")
prompt_text.configure(yscrollcommand=prompt_scrollbar.set)

# Sync Text widget with StringVar
def _sync_prompt_var_to_text(*args):
    current_text = prompt_text.get("1.0", "end-1c")
    new_text = self.prompt_var.get()
    if current_text != new_text:
        prompt_text.delete("1.0", "end")
        prompt_text.insert("1.0", new_text)

def _sync_text_to_prompt_var(event=None):
    text_content = prompt_text.get("1.0", "end-1c")
    self.prompt_var.set(text_content)

self.prompt_var.trace_add("write", _sync_prompt_var_to_text)
prompt_text.bind("<KeyRelease>", _sync_text_to_prompt_var)

# Store reference for later access
self._prompt_text_widget = prompt_text
```

Apply similar pattern for negative prompt field.

**Note**: This is a significant change that affects multiple files. Consider creating a reusable `MultiLinePromptField` component in `src/gui/widgets/` to avoid code duplication.

### Phase 4: Preview Panel Layout Optimization

**File**: `src/gui/preview_panel_v2.py`

**Current layout** (line ~75-150):
- Thumbnail centered
- Checkbox below thumbnail
- Job info below checkbox
- Prompts below job info

**Desired layout**:
- Thumbnail on the right side
- Job info/prompts on the left side
- Better use of horizontal space
- Prompts expand to show full text

**Fix**:

```python
# Replace current body layout with two-column layout
self.body = ttk.Frame(self, style=SURFACE_FRAME_STYLE)
self.body.pack(fill=tk.BOTH, expand=True)
self.body.columnconfigure(0, weight=1)  # Left column expands
self.body.columnconfigure(1, weight=0)  # Right column fixed

# Right column: Thumbnail + checkbox
right_frame = ttk.Frame(self.body, style=SURFACE_FRAME_STYLE)
right_frame.grid(row=0, column=1, sticky="ne", padx=(8, 0))

self.thumbnail = ThumbnailWidget(
    right_frame,
    width=150,
    height=150,
    placeholder_text="No Preview",
)
self.thumbnail.pack(anchor="ne")

self.preview_checkbox = ttk.Checkbutton(
    right_frame,
    text="Show preview thumbnails",
    variable=self._show_preview_var,
    command=self._on_preview_checkbox_changed,
    style="Dark.TCheckbutton",
)
self.preview_checkbox.pack(anchor="ne", pady=(4, 0))

# Left column: Job info + prompts
left_frame = ttk.Frame(self.body, style=SURFACE_FRAME_STYLE)
left_frame.grid(row=0, column=0, sticky="nsew")

self.job_count_label = ttk.Label(
    left_frame, text="No job selected", style=STATUS_LABEL_STYLE
)
self.job_count_label.pack(anchor=tk.W, pady=(0, 4))

# Prompts with full expansion
self.prompt_label = ttk.Label(left_frame, text="Positive Prompt", style=STATUS_LABEL_STYLE)
self.prompt_label.pack(anchor=tk.W)
self.prompt_text = tk.Text(
    left_frame,
    height=4,  # Increased from 3
    wrap="word",
    bg=BACKGROUND_ELEVATED,
    fg=TEXT_PRIMARY,
    relief="flat",
    state="disabled",
)
self.prompt_text.pack(fill=tk.BOTH, expand=True, pady=(0, 8))

self.negative_prompt_label = ttk.Label(
    left_frame, text="Negative Prompt", style=STATUS_LABEL_STYLE
)
self.negative_prompt_label.pack(anchor=tk.W)
self.negative_prompt_text = tk.Text(
    left_frame,
    height=3,  # Increased from 2
    wrap="word",
    bg=BACKGROUND_ELEVATED,
    fg=TEXT_PRIMARY,
    relief="flat",
    state="disabled",
)
self.negative_prompt_text.pack(fill=tk.BOTH, expand=True, pady=(0, 8))

# Settings grid below prompts
settings_frame = ttk.Frame(left_frame, style=SURFACE_FRAME_STYLE)
settings_frame.pack(fill=tk.X, pady=(0, 4))
# ... rest of settings layout ...
```

---

## Allowed Files

| File | Purpose | Modification Type |
|------|---------|-------------------|
| `src/gui/enhanced_slider.py` | **INVESTIGATE** - Check dynamic width support | Analysis |
| `src/gui/stage_cards_v2/advanced_txt2img_stage_card_v2.py` | **MODIFY** - CFG slider, prompt fields | Layout |
| `src/gui/stage_cards_v2/advanced_img2img_stage_card_v2.py` | **MODIFY** - Prompt fields | Layout |
| `src/gui/stage_cards_v2/adetailer_stage_card_v2.py` | **MODIFY** - Dropdown width, prompt fields | Layout |
| `src/gui/stage_cards_v2/advanced_upscale_stage_card_v2.py` | **MODIFY** - Prompt fields (if any) | Layout |
| `src/gui/preview_panel_v2.py` | **MODIFY** - Two-column layout | Layout |
| `src/gui/widgets/multi_line_prompt_field.py` | **CREATE** (optional) - Reusable prompt component | New widget |

---

## Forbidden Files

**No pipeline, builder, or execution logic may be modified.** This is GUI layout only.

---

## Testing Requirements

### Unit Tests

**File**: `tests/gui_v2/test_layout_optimizations.py`

```python
def test_cfg_slider_expands():
    """Test CFG slider expands to fill available width."""
    card = AdvancedTxt2ImgStageCardV2(...)
    # Check column weight
    # Verify slider sticky="ew"
    pass

def test_prompt_field_multiline():
    """Test prompt field is Text widget with 3 lines height."""
    card = AdvancedTxt2ImgStageCardV2(...)
    assert isinstance(card._prompt_text_widget, tk.Text)
    assert card._prompt_text_widget.cget("height") == 3
    pass

def test_preview_panel_two_column():
    """Test preview panel uses two-column layout."""
    panel = PreviewPanelV2(...)
    # Verify body has 2 columns
    # Verify thumbnail is in right column
    # Verify job info is in left column
    pass
```

### Manual Testing

1. **CFG Slider**:
   - Open Txt2Img configuration
   - Resize window wider
   - Verify CFG slider expands to use available width
   - Verify slider still functions correctly

2. **ADetailer Dropdown**:
   - Open ADetailer configuration
   - Verify "Mask merge mode" dropdown is narrower
   - Verify it aligns visually with "Mask blur" spinbox above

3. **Prompt Fields**:
   - Open any stage card with prompts
   - Verify "Prompt:" is now "Positive:"
   - Verify prompt field is 3 lines tall
   - Enter long prompt text (200+ characters)
   - Verify scrollbar appears when text exceeds 3 lines
   - Verify can scroll through prompt text
   - Apply same test to negative prompt field

4. **Preview Panel**:
   - Select a job in queue or draft
   - Verify preview panel shows thumbnail on right side
   - Verify job info and prompts are on left side
   - Enter long prompts in job
   - Verify prompts display fully without truncation
   - Resize window
   - Verify layout remains balanced

---

## Tech Debt Addressed

- **Fixed-width widgets**: CFG slider now responsive
- **Inconsistent dropdown widths**: ADetailer dropdowns properly sized
- **Limited prompt visibility**: Multi-line fields show more text
- **Poor space utilization**: Preview panel uses horizontal space efficiently

---

## Implementation Notes

1. **CFG Slider**: If EnhancedSlider doesn't support dynamic width, consider deprecating it in favor of standard ttk.Scale
2. **Prompt sync**: Text widget to StringVar sync must be bidirectional and efficient
3. **Scrollbar appearance**: Consider using autohide scrollbars (appear only when needed)
4. **Preview layout**: May need to adjust column weights based on typical prompt lengths

---

## Definition of Done

- [ ] CFG slider expands to full frame width
- [ ] ADetailer Mask merge mode dropdown width reduced
- [ ] All prompt fields changed to "Positive" label
- [ ] All prompt fields are 3 lines tall with scrollbars
- [ ] Text-to-StringVar sync works bidirectionally
- [ ] Preview panel uses two-column layout
- [ ] Thumbnail positioned on right
- [ ] Job info/prompts positioned on left
- [ ] Prompts display full text without truncation
- [ ] No layout regressions
- [ ] All unit tests pass
- [ ] Manual testing confirms improvements
- [ ] Outstanding Issues document updated

---

## Post-Implementation Tasks

1. Update Outstanding Issues document - mark items 2a, 2g, 2k, 3b, 3c as FIXED
2. Consider creating reusable MultiLinePromptField component for future use
3. Evaluate other areas where multi-line text fields would improve UX

---

**Estimated Effort**: 8-10 hours  
**Risk Level**: Medium (significant layout changes)  
**Dependencies**: None
