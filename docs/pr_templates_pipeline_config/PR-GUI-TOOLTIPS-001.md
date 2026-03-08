# PR-GUI-TOOLTIPS-001: Add Help Text & Tooltips for ADetailer Configuration

**Status**: READY FOR IMPLEMENTATION  
**Priority**: Medium  
**PR Type**: GUI Enhancement - User Experience  
**Architecture Impact**: None (GUI-only)

---

## Context & Motivation

Multiple ADetailer configuration options lack clear explanations, making it difficult for users to understand what each setting controls. This PR adds comprehensive tooltips and inline help text to guide users through ADetailer configuration.

**Related Outstanding Issues:**
- Issue 2h: Add tooltips for Confidence, Max detections, Mask blur, Mask merge mode
- Issue 2i: Add tooltips for Mask filtering section
- Issue 2j: Add tooltips for Mask Processing section

---

## Implementation Plan

### Phase 1: Create Tooltip System Component

**File**: `src/gui/widgets/tooltip_widget.py`

Create a reusable tooltip widget that can be attached to any widget:

```python
class HoverTooltip:
    """Shows a tooltip on hover with detailed information."""
    def __init__(self, widget, text: str, delay: int = 500):
        self.widget = widget
        self.text = text
        self.delay = delay
        self._tooltip_window = None
        self._after_id = None
        
        widget.bind("<Enter>", self._on_enter)
        widget.bind("<Leave>", self._on_leave)
    
    def _on_enter(self, event):
        self._after_id = self.widget.after(self.delay, self._show_tooltip)
    
    def _on_leave(self, event):
        if self._after_id:
            self.widget.after_cancel(self._after_id)
            self._after_id = None
        if self._tooltip_window:
            self._tooltip_window.destroy()
            self._tooltip_window = None
    
    def _show_tooltip(self):
        # Create tooltip window with text
        pass
```

### Phase 2: Define Help Text Content

**File**: `src/gui/help_text/adetailer_help.py`

```python
ADETAILER_HELP_TEXT = {
    "confidence": {
        "short": "Detection confidence threshold",
        "long": "Minimum confidence score (0.1-1.0) required for face/object detection. Higher values = fewer false positives but may miss some faces. Recommended: 0.3-0.4 for faces."
    },
    "max_detections": {
        "short": "Maximum number of detections per image",
        "long": "Limits how many faces/objects will be detected and processed. Useful for performance control. Set to 1-3 for portraits, higher for group photos."
    },
    "mask_blur": {
        "short": "Mask edge blur radius",
        "long": "Pixels to blur at mask edges for smoother blending (0-16). Higher values create softer transitions. Recommended: 4-8 for natural results."
    },
    "mask_merge_mode": {
        "short": "How multiple masks are combined",
        "long": "'none': Process each mask separately. 'merge': Combine all masks into one region. 'merge_and_invert': Combine masks then invert."
    },
    "filter_method": {
        "short": "Which detections to keep",
        "long": "'largest': Keep only the N largest detections. 'all': Process all detections that pass filters. Use 'largest' for primary subject focus."
    },
    "mask_k_largest": {
        "short": "Number of largest masks to keep",
        "long": "When filter_method='largest', this specifies how many of the largest detections to process (1-10)."
    },
    "mask_min_ratio": {
        "short": "Minimum mask size ratio",
        "long": "Filter out detections smaller than this fraction of image size (0.0-1.0). Use to ignore tiny faces in background."
    },
    "mask_max_ratio": {
        "short": "Maximum mask size ratio",
        "long": "Filter out detections larger than this fraction of image size (0.0-1.0). Use to ignore false detections."
    },
    "dilate_erode": {
        "short": "Mask dilation/erosion",
        "long": "Negative values shrink mask inward (erosion), positive values expand mask outward (dilation). Range: -32 to +32 pixels. Use +4 to +8 to include more surrounding detail."
    },
    "mask_feather": {
        "short": "Mask edge feathering",
        "long": "Additional gaussian blur applied to mask edges (0-64 pixels). Creates very soft transitions. Combine with mask_blur for ultra-smooth blending."
    }
}
```

### Phase 3: Update ADetailer Stage Card

**File**: `src/gui/stage_cards_v2/adetailer_stage_card_v2.py`

Modifications:
1. Import tooltip system and help text
2. Add inline help labels after each config item
3. Attach hover tooltips to help labels

Example for Confidence section:

```python
# Current code (line ~173-179):
row = self._add_spin_section(
    parent,
    row,
    "Confidence:",
    self.confidence_var,
    0.1,
    1.0,
    0.05,
    format_str="%.2f",
)

# Updated code:
conf_row_frame = ttk.Frame(parent, style=SURFACE_FRAME_STYLE)
conf_row_frame.grid(row=row, column=0, columnspan=2, sticky="ew", pady=2)
conf_row_frame.columnconfigure(2, weight=1)

ttk.Label(conf_row_frame, text="Confidence:", style=BODY_LABEL_STYLE).grid(
    row=0, column=0, sticky="w", padx=(0, 4)
)
ttk.Spinbox(
    conf_row_frame,
    from_=0.1,
    to=1.0,
    increment=0.05,
    textvariable=self.confidence_var,
    format="%.2f",
    width=8,
    style=DARK_SPINBOX_STYLE,
).grid(row=0, column=1, sticky="w", padx=(0, 8))

help_label = ttk.Label(
    conf_row_frame,
    text="Detection confidence threshold",
    style="Dark.TLabel",
    foreground="#888888",
)
help_label.grid(row=0, column=2, sticky="w")
HoverTooltip(help_label, ADETAILER_HELP_TEXT["confidence"]["long"])

row += 1
```

Apply similar pattern for all configuration items:
- Max detections
- Mask blur
- Mask merge mode
- Filter method
- Max K
- Min Ratio
- Max Ratio
- Dilate/Erode
- Feather

### Phase 4: Update Img2Img Inpaint Settings

**File**: `src/gui/stage_cards_v2/advanced_img2img_stage_card_v2.py`

**File**: `src/gui/help_text/inpaint_help.py`

Define help text for inpaint settings:

```python
INPAINT_HELP_TEXT = {
    "mask_blur": {
        "short": "Inpaint mask blur",
        "long": "Blur radius applied to inpaint mask edges (0-64 pixels). Higher values create softer transitions between inpainted and original areas."
    },
    "inpaint_full_res": {
        "short": "Inpaint at full resolution",
        "long": "Process the entire image at full resolution rather than just the masked region. Slower but may produce better results for large masks."
    },
    "inpaint_full_res_padding": {
        "short": "Padding around mask",
        "long": "Pixels of context to include around the masked region when inpaint_full_res is disabled. More padding = better blending context."
    },
    "inpainting_mask_invert": {
        "short": "Invert mask",
        "long": "Process the area outside the mask instead of inside. Useful for 'outpainting' or protecting specific regions."
    },
    "inpainting_fill": {
        "short": "Initial fill method",
        "long": "How to fill the masked area before denoising. 'original': keep original pixels, 'fill': solid color, 'latent noise': add noise, 'latent nothing': zeros."
    }
}
```

Apply tooltips to all inpaint configuration widgets.

---

## Allowed Files

| File | Purpose | Modification Type |
|------|---------|-------------------|
| `src/gui/widgets/tooltip_widget.py` | **CREATE** - Tooltip system | New component |
| `src/gui/help_text/__init__.py` | **CREATE** - Help text package init | Package marker |
| `src/gui/help_text/adetailer_help.py` | **CREATE** - ADetailer help text | Documentation |
| `src/gui/help_text/inpaint_help.py` | **CREATE** - Inpaint help text | Documentation |
| `src/gui/stage_cards_v2/adetailer_stage_card_v2.py` | **MODIFY** - Add tooltips | Layout + tooltips |
| `src/gui/stage_cards_v2/advanced_img2img_stage_card_v2.py` | **MODIFY** - Add tooltips | Layout + tooltips |

---

## Forbidden Files

**No pipeline, builder, or execution logic may be modified.** This is GUI-only.

---

## Testing Requirements

### Unit Tests

**File**: `tests/gui_v2/test_tooltip_widget.py`

```python
def test_tooltip_creation():
    """Test tooltip widget can be created and attached."""
    root = tk.Tk()
    label = ttk.Label(root, text="Test")
    tooltip = HoverTooltip(label, "Help text")
    assert tooltip.text == "Help text"
    root.destroy()

def test_tooltip_shows_on_hover():
    """Test tooltip appears after hover delay."""
    # Simulate hover event
    # Verify tooltip window created
    pass

def test_tooltip_hides_on_leave():
    """Test tooltip disappears when mouse leaves."""
    # Simulate leave event
    # Verify tooltip window destroyed
    pass
```

### Manual Testing

1. **Tooltip Display**:
   - Hover over each help label in ADetailer stage card
   - Verify detailed tooltip appears after ~500ms
   - Verify tooltip disappears when mouse leaves
   - Check tooltip text is readable and helpful

2. **Layout Integrity**:
   - Verify help labels don't break existing layout
   - Check that spinboxes and dropdowns still function correctly
   - Verify dark mode styling is consistent

3. **Inpaint Settings**:
   - Navigate to Img2Img configuration
   - Hover over inpaint setting help labels
   - Verify tooltips appear correctly

---

## Tech Debt Addressed

- **Lack of user guidance**: Users no longer need to guess what configs do
- **Documentation centralization**: Help text stored in dedicated module
- **Reusable tooltip system**: Can be applied to other configuration sections

---

## Implementation Notes

1. **Tooltip delay**: 500ms is standard for most UIs
2. **Text wrapping**: Tooltip window should wrap long text (max width ~400px)
3. **Positioning**: Tooltip should appear near cursor but not obscure the widget
4. **Dark mode**: Tooltip background should use dark theme colors

---

## Definition of Done

- [ ] Tooltip widget component created and tested
- [ ] Help text modules created with comprehensive descriptions
- [ ] All ADetailer configs have inline help + tooltips
- [ ] All Inpaint configs have inline help + tooltips
- [ ] Manual testing confirms tooltips work correctly
- [ ] No layout regressions
- [ ] Dark mode styling consistent
- [ ] Outstanding Issues document updated

---

## Post-Implementation Tasks

1. Update Outstanding Issues document - mark items 2h, 2i, 2j, 2l as FIXED
2. Consider extending tooltips to other configuration sections
3. Add tooltips to Txt2Img and Upscale stage cards (future PR)

---

**Estimated Effort**: 4-6 hours  
**Risk Level**: Low (GUI-only, no logic changes)  
**Dependencies**: None
