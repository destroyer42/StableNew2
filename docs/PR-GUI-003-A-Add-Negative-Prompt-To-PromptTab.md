# PR-GUI-003-A: Add Negative Prompt to Prompt Tab

**Status:** Ready for Implementation  
**Date:** December 19, 2025  
**Version:** v2.6  
**Priority:** P1 (Foundation for matrix integration)  
**Estimated Effort:** 1 week  
**Dependencies:** None

---

## 1. Executive Summary

**Goal:** Add negative prompt editing capability to the main Prompt Tab UI.

**Current State:**
- PromptTabFrame only shows positive prompt editor
- Negative prompt can be edited in Advanced Editor modal (AdvancedPromptEditorV2)
- PromptPackModel does not store negative prompts
- No persistence for negative prompts in JSON format

**Desired State:**
- Negative prompt editor visible in main Prompt Tab (below positive editor)
- PromptSlot extended with `negative` field
- Save/load preserves negative prompts
- Metadata panel shows negative prompt stats

**Why This Matters:**
- Negative prompts are critical for quality control
- Currently hidden behind modal (poor UX)
- Required foundation for matrix system (PR-GUI-003-B needs negative handling)
- Enables full pack authoring without modal dialogs

---

## 2. Technical Specification

### 2.1 Data Model Changes

**File:** `src/gui/models/prompt_pack_model.py`

**Extend PromptSlot dataclass:**
```python
@dataclass
class PromptSlot:
    index: int
    text: str = ""
    negative: str = ""  # NEW FIELD
```

**Extend JSON format:**
```json
{
  "name": "MyPack",
  "slots": [
    {
      "index": 0,
      "text": "a wizard casting spells, masterpiece",
      "negative": "ugly, blurry, low quality"
    },
    {
      "index": 1,
      "text": "a knight in armor",
      "negative": ""
    }
  ]
}
```

**Backward Compatibility:**
- Old JSON files without `negative` field → default to `""`
- Loading code must handle missing field gracefully
- Saving always includes `negative` field (even if empty)

---

### 2.2 UI Changes

**File:** `src/gui/views/prompt_tab_frame_v2.py`

**Current Layout (Center Panel):**
```
┌──────────────────────────────────────┐
│ Editor - PackName                    │
│ [Advanced Editor] [Insert Matrix...] │
├──────────────────────────────────────┤
│                                      │
│ [Positive Prompt Text Editor]        │
│ (height=12, expands)                 │
│                                      │
│                                      │
└──────────────────────────────────────┘
```

**New Layout (Center Panel):**
```
┌──────────────────────────────────────┐
│ Editor - PackName                    │
│ [Advanced Editor] [Insert Matrix...] │
├──────────────────────────────────────┤
│ Positive Prompt                      │
│ [Positive Prompt Text Editor]        │
│ (height=8, expands with weight=3)    │
│                                      │
├──────────────────────────────────────┤
│ Negative Prompt                      │
│ [Negative Prompt Text Editor]        │
│ (height=4, expands with weight=1)    │
└──────────────────────────────────────┘
```

**Implementation Details:**
1. Change center_frame layout to use grid with rowconfigure weights
2. Add label: `ttk.Label(self.center_frame, text="Positive Prompt")`
3. Reduce positive editor height from 12 to 8
4. Add label: `ttk.Label(self.center_frame, text="Negative Prompt")`
5. Add negative editor: `self.negative_editor = tk.Text(height=4)`
6. Bind `<<Modified>>` event to `_on_negative_modified`
7. Set row weights: positive=3, negative=1 (75%/25% split)

---

### 2.3 State Management Changes

**File:** `src/gui/prompt_workspace_state.py`

**New Methods:**
```python
def get_current_negative_text(self) -> str:
    """Get negative prompt text for current slot."""
    if not self.current_pack:
        return ""
    slot = self.current_pack.get_slot(self._current_slot_index)
    return getattr(slot, "negative", "")

def set_slot_negative(self, index: int, negative: str) -> None:
    """Set negative prompt text for slot at index."""
    if not self.current_pack:
        raise RuntimeError("No prompt pack loaded")
    slot = self.current_pack.get_slot(index)
    slot.negative = negative or ""
    self.dirty = True
```

**Modified Methods:**
```python
def get_current_prompt_metadata(self) -> PromptMetadata:
    """Build metadata from positive AND negative text."""
    positive = self.get_current_prompt_text()
    negative = self.get_current_negative_text()
    
    # Combine for LoRA/embedding detection
    combined_text = f"{positive}\n{negative}"
    return build_prompt_metadata(combined_text)
```

---

### 2.4 Event Handlers

**File:** `src/gui/views/prompt_tab_frame_v2.py`

**New Handler:**
```python
def _on_negative_modified(self, _event=None) -> None:
    """Handle edits to negative prompt editor."""
    if self._suppress_editor_change:
        self.negative_editor.edit_modified(False)
        return
    
    if not self.negative_editor.edit_modified():
        return
    
    negative_text = self.negative_editor.get("1.0", "end").rstrip("\n")
    try:
        self.workspace_state.set_slot_negative(
            self.workspace_state.get_current_slot_index(),
            negative_text
        )
        # Update UI indicator
        self.pack_name_label.config(
            text=f"Editor - {self.workspace_state.current_pack.name} (modified)"
        )
    except Exception:
        pass
    
    self.negative_editor.edit_modified(False)
    self._refresh_metadata()
```

**Modified Handler:**
```python
def _refresh_editor(self) -> None:
    """Load current slot's positive AND negative text."""
    slot = self.workspace_state.get_slot(self.workspace_state.get_current_slot_index())
    
    self._suppress_editor_change = True
    try:
        # Update positive editor
        self.editor.delete("1.0", "end")
        if slot.text:
            self.editor.insert("1.0", slot.text)
        self.editor.edit_modified(False)
        
        # Update negative editor (NEW)
        self.negative_editor.delete("1.0", "end")
        negative = getattr(slot, "negative", "")
        if negative:
            self.negative_editor.insert("1.0", negative)
        self.negative_editor.edit_modified(False)
    finally:
        self._suppress_editor_change = False
```

---

### 2.5 Metadata Panel Updates

**File:** `src/gui/views/prompt_tab_frame_v2.py`

**Enhanced _refresh_metadata():**
```python
def _refresh_metadata(self) -> None:
    pack = self.workspace_state.current_pack
    slot_index = self.workspace_state.get_current_slot_index()
    meta = self.workspace_state.get_current_prompt_metadata() if pack else None
    
    # Get positive and negative lengths separately
    positive_text = self.workspace_state.get_current_prompt_text()
    negative_text = self.workspace_state.get_current_negative_text()
    positive_len = len(positive_text)
    negative_len = len(negative_text)
    
    loras = meta.loras if meta else []
    embeds = meta.embeddings if meta else []
    
    dirty = " (modified)" if self.workspace_state.dirty else ""
    self.pack_name_label.config(text=f"Editor - {pack.name if pack else 'None'}{dirty}")
    
    summary_lines = [
        f"Pack: {pack.name if pack else 'None'}{dirty}",
        f"Slot: {slot_index + 1}",
        "",
        f"Positive: {positive_len} chars across {positive_text.count(chr(10)) + 1} line(s)",
        f"Negative: {negative_len} chars across {negative_text.count(chr(10)) + 1} line(s)",  # NEW
        f"Matrix expressions: {meta.matrix_count if meta else 0}",
    ]
    
    # ... rest of metadata (LoRAs, embeddings, etc.)
```

---

### 2.6 Load/Save Integration

**File:** `src/gui/models/prompt_pack_model.py`

**Modified load_from_file():**
```python
@classmethod
def load_from_file(cls, path: str | Path, min_slots: int = 10) -> PromptPackModel:
    """Load from JSON format; handle missing 'negative' field gracefully."""
    data_path = Path(path)
    try:
        with data_path.open("r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception as exc:
        raise OSError(f"Failed to load prompt pack: {exc}") from exc
    
    name = data.get("name") or data_path.stem
    raw_slots = data.get("slots") or []
    slots: list[PromptSlot] = []
    
    for idx, slot in enumerate(raw_slots):
        slots.append(
            PromptSlot(
                index=int(slot.get("index", idx)),
                text=str(slot.get("text", "")),
                negative=str(slot.get("negative", ""))  # NEW - defaults to empty
            )
        )
    
    # Pad to minimum slots
    while len(slots) < min_slots:
        slots.append(PromptSlot(index=len(slots), text="", negative=""))
    
    return cls(name=name, path=str(data_path), slots=slots)
```

**Modified save_to_file():**
```python
def save_to_file(self, path: str | Path | None = None) -> Path:
    """Persist to JSON format; always include 'negative' field."""
    target = Path(path or self.path or f"{self.name}.json")
    payload = {
        "name": self.name,
        "slots": [
            {
                "index": slot.index,
                "text": slot.text,
                "negative": getattr(slot, "negative", "")  # Always include
            }
            for slot in self.slots
        ],
    }
    
    target.parent.mkdir(parents=True, exist_ok=True)
    try:
        with target.open("w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)
    except Exception as exc:
        raise OSError(f"Failed to save prompt pack: {exc}") from exc
    
    self.path = str(target)
    return target
```

---

### 2.7 Advanced Editor Integration

**File:** `src/gui/views/prompt_tab_frame_v2.py`

**Modified _open_advanced_editor_dialog():**
```python
def _open_advanced_editor_dialog(self) -> None:
    top = tk.Toplevel(self)
    top.title("Advanced Prompt Editor")
    top.transient(self.winfo_toplevel())
    
    def _handle_apply(prompt_value: str, negative_value: str | None = None) -> None:
        # Apply positive
        self.apply_prompt_text(prompt_value)
        
        # Apply negative (NEW)
        if negative_value is not None:
            try:
                index = self.workspace_state.get_current_slot_index()
                self.workspace_state.set_slot_negative(index, negative_value)
                self._refresh_editor()  # This now updates negative_editor too
            except Exception:
                pass
        
        try:
            top.destroy()
        except Exception:
            pass
    
    # Pass both positive AND negative to editor
    editor = AdvancedPromptEditorV2(
        top,
        initial_prompt=self.workspace_state.get_current_prompt_text(),
        initial_negative_prompt=self.workspace_state.get_current_negative_text(),  # NEW
        on_apply=_handle_apply,
        on_cancel=lambda: top.destroy(),
    )
    editor.pack(fill="both", expand=True)
    
    try:
        top.grab_set()
    except Exception:
        pass
```

---

## 3. Implementation Steps

### Step 1: Extend Data Model (30 min)

1. Open `src/gui/models/prompt_pack_model.py`
2. Add `negative: str = ""` to PromptSlot dataclass
3. Update `load_from_file()` to handle `negative` field with default
4. Update `save_to_file()` to always include `negative` field
5. Run existing tests to ensure backward compatibility

**Verification:**
```python
# Test: Load old JSON without negative field
old_json = {"name": "Test", "slots": [{"index": 0, "text": "hello"}]}
pack = PromptPackModel.load_from_file(old_json_path)
assert pack.slots[0].negative == ""  # Should default to empty

# Test: Save includes negative field
pack.slots[0].negative = "ugly"
pack.save_to_file(new_path)
# Verify JSON contains {"negative": "ugly"}
```

---

### Step 2: Add Negative Editor UI (1 hour)

1. Open `src/gui/views/prompt_tab_frame_v2.py`
2. Modify `_build_center_panel()`:
   - Change layout from pack to grid
   - Add "Positive Prompt" label
   - Reduce positive editor height to 8
   - Add "Negative Prompt" label
   - Add negative_editor (height=4)
   - Configure row weights (3:1 ratio)
3. Add `_on_negative_modified()` handler
4. Update `_refresh_editor()` to load negative text

**Code Changes:**
```python
def _build_center_panel(self) -> None:
    # Configure grid
    self.center_frame.rowconfigure(1, weight=3)  # positive editor
    self.center_frame.rowconfigure(3, weight=1)  # negative editor
    self.center_frame.columnconfigure(0, weight=1)
    
    # Header (row 0)
    header_frame = ttk.Frame(self.center_frame)
    header_frame.grid(row=0, column=0, sticky="ew", pady=(0, 4))
    # ... existing header code ...
    
    # Positive label (row 1 start)
    ttk.Label(self.center_frame, text="Positive Prompt", style=BODY_LABEL_STYLE).grid(
        row=1, column=0, sticky="w", pady=(0, 2)
    )
    
    # Positive editor (row 2)
    self.editor = tk.Text(self.center_frame, height=8, wrap="word")
    self.editor.grid(row=2, column=0, sticky="nsew", pady=(0, 6))
    self.editor.bind("<<Modified>>", self._on_editor_modified)
    enable_mousewheel(self.editor)
    
    # Negative label (row 3)
    ttk.Label(self.center_frame, text="Negative Prompt", style=BODY_LABEL_STYLE).grid(
        row=3, column=0, sticky="w", pady=(0, 2)
    )
    
    # Negative editor (row 4)
    self.negative_editor = tk.Text(self.center_frame, height=4, wrap="word")
    self.negative_editor.grid(row=4, column=0, sticky="nsew")
    self.negative_editor.bind("<<Modified>>", self._on_negative_modified)
    enable_mousewheel(self.negative_editor)
    attach_tooltip(self.negative_editor, "Negative prompt to exclude unwanted elements.")
```

**Verification:**
- Launch GUI → Prompt tab
- Verify negative editor appears below positive editor
- Verify 75%/25% height split (approximately)
- Verify both editors respond to typing

---

### Step 3: Add State Management (30 min)

1. Open `src/gui/prompt_workspace_state.py`
2. Add `get_current_negative_text()` method
3. Add `set_slot_negative()` method
4. Update `get_current_prompt_metadata()` to include negative text

**Verification:**
```python
# Test: Set and get negative text
ws = PromptWorkspaceState()
ws.new_pack("Test", slot_count=3)
ws.set_slot_negative(0, "ugly, blurry")
assert ws.get_current_negative_text() == "ugly, blurry"
assert ws.dirty == True
```

---

### Step 4: Wire Event Handlers (30 min)

1. Implement `_on_negative_modified()` in PromptTabFrame
2. Update `_refresh_editor()` to load negative text
3. Update `_on_new_pack()` to clear negative editor
4. Test typing in negative editor → saves to slot

**Verification:**
- Type in negative editor
- Switch slots
- Verify negative text persists
- Verify dirty flag set

---

### Step 5: Update Metadata Panel (30 min)

1. Modify `_refresh_metadata()` to show negative stats
2. Add line: `f"Negative: {negative_len} chars across {line_count} line(s)"`
3. Ensure LoRA/embedding detection includes negative text

**Verification:**
- Type LoRA in negative prompt: `<lora:test:0.5>`
- Verify metadata panel shows LoRA detected
- Verify negative character count displays

---

### Step 6: Integrate with Advanced Editor (30 min)

1. Update `_open_advanced_editor_dialog()` to pass `initial_negative_prompt`
2. Update `_handle_apply()` to save negative from modal
3. Test roundtrip: Prompt Tab → Advanced Editor → Apply → verify negative saved

**Verification:**
- Click "Advanced Editor"
- Verify negative editor pre-filled
- Edit negative, click Apply
- Verify main tab negative editor updates

---

### Step 7: Test Save/Load (1 hour)

1. Create test pack with negative prompts
2. Save to JSON
3. Close and reopen pack
4. Verify negative prompts preserved
5. Load old pack without negative field
6. Verify defaults to empty, no errors

**Test Cases:**
```python
def test_save_load_negative_prompt():
    ws = PromptWorkspaceState()
    ws.new_pack("Test")
    ws.set_slot_text(0, "wizard")
    ws.set_slot_negative(0, "ugly")
    
    path = ws.save_current_pack("test.json")
    
    ws2 = PromptWorkspaceState()
    ws2.load_pack(path)
    assert ws2.get_current_prompt_text() == "wizard"
    assert ws2.get_current_negative_text() == "ugly"

def test_load_legacy_pack_without_negative():
    # Create legacy JSON without negative field
    legacy_json = {"name": "Legacy", "slots": [{"index": 0, "text": "test"}]}
    path = Path("legacy_test.json")
    path.write_text(json.dumps(legacy_json))
    
    ws = PromptWorkspaceState()
    ws.load_pack(path)  # Should not crash
    assert ws.get_current_negative_text() == ""
```

---

## 4. Testing Strategy

### 4.1 Unit Tests

**File:** `tests/gui_v2/test_prompt_pack_model_negative.py`

```python
import pytest
from src.gui.models.prompt_pack_model import PromptPackModel, PromptSlot

def test_prompt_slot_has_negative_field():
    slot = PromptSlot(index=0, text="positive", negative="negative")
    assert slot.negative == "negative"

def test_prompt_slot_negative_defaults_empty():
    slot = PromptSlot(index=0, text="positive")
    assert slot.negative == ""

def test_save_includes_negative():
    pack = PromptPackModel.new("Test", slot_count=1)
    pack.slots[0].text = "wizard"
    pack.slots[0].negative = "ugly"
    
    path = pack.save_to_file("test_negative.json")
    
    # Read JSON and verify
    import json
    with open(path, "r") as f:
        data = json.load(f)
    
    assert data["slots"][0]["negative"] == "ugly"

def test_load_without_negative_field():
    # Simulate old JSON
    import json
    from pathlib import Path
    
    old_json = {"name": "Old", "slots": [{"index": 0, "text": "hello"}]}
    path = Path("old_test.json")
    path.write_text(json.dumps(old_json))
    
    pack = PromptPackModel.load_from_file(path)
    assert pack.slots[0].negative == ""
    
    path.unlink()

def test_load_with_negative_field():
    pack = PromptPackModel.new("Test", slot_count=1)
    pack.slots[0].negative = "bad quality"
    path = pack.save_to_file("test_with_neg.json")
    
    pack2 = PromptPackModel.load_from_file(path)
    assert pack2.slots[0].negative == "bad quality"
```

---

### 4.2 Integration Tests

**File:** `tests/gui_v2/test_prompt_workspace_state_negative.py`

```python
from src.gui.prompt_workspace_state import PromptWorkspaceState

def test_get_set_negative_text():
    ws = PromptWorkspaceState()
    ws.new_pack("Test", slot_count=3)
    
    ws.set_slot_negative(0, "ugly, blurry")
    assert ws.get_current_negative_text() == "ugly, blurry"
    assert ws.dirty

def test_negative_text_persists_across_slots():
    ws = PromptWorkspaceState()
    ws.new_pack("Test", slot_count=3)
    
    ws.set_slot_text(0, "wizard")
    ws.set_slot_negative(0, "neg1")
    
    ws.set_current_slot_index(1)
    ws.set_slot_text(1, "knight")
    ws.set_slot_negative(1, "neg2")
    
    ws.set_current_slot_index(0)
    assert ws.get_current_prompt_text() == "wizard"
    assert ws.get_current_negative_text() == "neg1"
    
    ws.set_current_slot_index(1)
    assert ws.get_current_prompt_text() == "knight"
    assert ws.get_current_negative_text() == "neg2"

def test_save_load_preserves_negative():
    ws = PromptWorkspaceState()
    ws.new_pack("Test")
    ws.set_slot_text(0, "positive text")
    ws.set_slot_negative(0, "negative text")
    
    path = ws.save_current_pack("test_roundtrip.json")
    
    ws2 = PromptWorkspaceState()
    ws2.load_pack(path)
    
    assert ws2.get_current_prompt_text() == "positive text"
    assert ws2.get_current_negative_text() == "negative text"
```

---

### 4.3 GUI Tests

**File:** `tests/gui_v2/test_prompt_tab_negative_ui.py`

```python
import tkinter as tk
from src.gui.views.prompt_tab_frame_v2 import PromptTabFrame
from src.gui.app_state_v2 import AppStateV2

def test_negative_editor_exists():
    root = tk.Tk()
    app_state = AppStateV2()
    frame = PromptTabFrame(root, app_state=app_state)
    
    assert hasattr(frame, "negative_editor")
    assert isinstance(frame.negative_editor, tk.Text)
    
    root.destroy()

def test_typing_in_negative_editor_saves_to_slot():
    root = tk.Tk()
    app_state = AppStateV2()
    frame = PromptTabFrame(root, app_state=app_state)
    
    # Type in negative editor
    frame.negative_editor.insert("1.0", "ugly, blurry")
    frame.negative_editor.event_generate("<<Modified>>")
    
    # Trigger handler
    frame._on_negative_modified()
    
    # Verify saved to workspace
    negative = frame.workspace_state.get_current_negative_text()
    assert "ugly, blurry" in negative
    
    root.destroy()

def test_switching_slots_loads_negative():
    root = tk.Tk()
    app_state = AppStateV2()
    frame = PromptTabFrame(root, app_state=app_state)
    
    # Set negative for slot 0
    frame.workspace_state.set_slot_negative(0, "neg1")
    
    # Set negative for slot 1
    frame.workspace_state.set_current_slot_index(1)
    frame.workspace_state.set_slot_negative(1, "neg2")
    
    # Switch back to slot 0
    frame.workspace_state.set_current_slot_index(0)
    frame._refresh_editor()
    
    # Verify negative editor shows neg1
    negative_text = frame.negative_editor.get("1.0", "end").strip()
    assert negative_text == "neg1"
    
    root.destroy()
```

---

### 4.4 Manual Test Plan

**Test Case 1: Create New Pack with Negative**
1. Launch StableNew → Prompt tab
2. Click "New"
3. Type positive prompt: "wizard casting spells"
4. Type negative prompt: "ugly, blurry"
5. Click "Save As..." → save to "test_negative.json"
6. Close and reopen StableNew
7. Open saved pack
8. **Expected:** Both positive and negative prompts restored

**Test Case 2: Edit Multiple Slots**
1. Prompt tab → New pack
2. Slot 1: Positive "wizard", Negative "ugly"
3. Slot 2: Positive "knight", Negative "blurry"
4. Slot 3: Positive "druid", Negative "lowres"
5. Click slot 1 → verify "ugly" shows
6. Click slot 2 → verify "blurry" shows
7. Click slot 3 → verify "lowres" shows
8. **Expected:** Each slot preserves its negative

**Test Case 3: Advanced Editor Roundtrip**
1. Prompt tab → type positive "test"
2. Type negative "bad"
3. Click "Advanced Editor"
4. **Expected:** Modal shows positive "test" and negative "bad"
5. Edit both, click Apply
6. **Expected:** Main tab updates both editors

**Test Case 4: Legacy Pack Compatibility**
1. Create old-format JSON manually:
   ```json
   {"name": "Old", "slots": [{"index": 0, "text": "hello"}]}
   ```
2. Prompt tab → Open this file
3. **Expected:** No crash, negative editor empty
4. Type negative "new"
5. Save
6. **Expected:** JSON now includes `"negative": "new"`

**Test Case 5: Metadata Detection**
1. Prompt tab → positive "masterpiece"
2. Negative "`<lora:test:0.5>`, ugly"
3. **Expected:** Metadata panel shows LoRA detected
4. **Expected:** Negative line count shows in metadata

---

## 5. Files Modified

### Core Files (Modify)

| File | Changes | Lines | Complexity |
|------|---------|-------|------------|
| `src/gui/models/prompt_pack_model.py` | Add `negative` field to PromptSlot, update save/load | ~20 | Low |
| `src/gui/prompt_workspace_state.py` | Add `get_current_negative_text()`, `set_slot_negative()` | ~15 | Low |
| `src/gui/views/prompt_tab_frame_v2.py` | Add negative editor UI, handlers, metadata | ~80 | Medium |

### Test Files (New)

| File | Purpose | Lines | Coverage |
|------|---------|-------|----------|
| `tests/gui_v2/test_prompt_pack_model_negative.py` | Unit tests for data model | ~60 | PromptSlot.negative |
| `tests/gui_v2/test_prompt_workspace_state_negative.py` | Integration tests for state | ~50 | State methods |
| `tests/gui_v2/test_prompt_tab_negative_ui.py` | GUI tests for editor | ~70 | UI behavior |

**Total New Lines:** ~295  
**Total Modified Lines:** ~115  
**Test Coverage Target:** >90% for new code

---

## 6. Acceptance Criteria

### Must Have (Blocking)

- [x] PromptSlot has `negative` field
- [x] Negative editor visible in Prompt Tab (below positive)
- [x] Typing in negative editor saves to current slot
- [x] Switching slots loads correct negative text
- [x] Save/Load preserves negative prompts in JSON
- [x] Old JSON files without negative field load without errors
- [x] Metadata panel shows negative prompt stats
- [x] Advanced Editor receives and returns negative text
- [x] All unit tests pass
- [x] All integration tests pass
- [x] Manual test plan completed

### Should Have (Important)

- [x] Negative editor has 25% height (positive has 75%)
- [x] Mousewheel scrolling works in negative editor
- [x] Tooltip on negative editor
- [x] Character count in metadata panel
- [x] LoRA detection includes negative text

### Nice to Have (Optional)

- [ ] Syntax highlighting in negative editor
- [ ] Auto-complete for negative tags
- [ ] Global negative prompt button (preset injection)
- [ ] Warning if negative too long (>500 chars)

---

## 7. Risks & Mitigation

### Risk 1: Breaking Existing Packs

**Risk:** Old JSON files crash when loading

**Likelihood:** Medium  
**Impact:** High  
**Mitigation:**
- Load code uses `slot.get("negative", "")` with default
- Unit test specifically tests legacy JSON
- Manual test with real old pack from archive

---

### Risk 2: Layout Issues

**Risk:** Negative editor takes too much space or doesn't resize

**Likelihood:** Low  
**Impact:** Medium  
**Mitigation:**
- Use grid with rowconfigure weights (3:1 ratio)
- Test on different window sizes
- Ensure both editors expand on resize

---

### Risk 3: Advanced Editor Confusion

**Risk:** Users don't realize negative in modal syncs with main tab

**Likelihood:** Medium  
**Impact:** Low  
**Mitigation:**
- Add tooltip explaining sync
- Update docs to clarify
- Consider removing negative from Advanced Editor in future (make main tab the source)

---

## 8. Future Enhancements (Post-PR)

**PR-GUI-003-B Dependencies:**
- Matrix system will need negative prompt handling (base negative + slot negatives)
- Matrix preview should show negative prompts

**PR-GUI-003-C Dependencies:**
- TXT export format doesn't support negative natively
- May need dual TXT files (positive.txt + negative.txt) or embedded format

**PR-GUI-003-F Documentation:**
- User guide section on negative prompts
- JSON format specification
- Best practices for negative prompt authoring

---

## 9. Definition of Done

- [ ] All code changes implemented
- [ ] All unit tests written and passing
- [ ] All integration tests written and passing
- [ ] Manual test plan executed and documented
- [ ] No regressions in existing Prompt Tab functionality
- [ ] No regressions in existing Pipeline Tab functionality
- [ ] Code reviewed by team
- [ ] Documentation updated (inline comments)
- [ ] CHANGELOG.md updated with feature description
- [ ] PR merged to StableBranch

---

## 10. Implementation Checklist

**Day 1: Data Model**
- [ ] Add `negative` field to PromptSlot
- [ ] Update `load_from_file()` with default handling
- [ ] Update `save_to_file()` to always include negative
- [ ] Write unit tests for data model
- [ ] Run tests, ensure backward compatibility

**Day 2: UI Implementation**
- [ ] Add negative editor to PromptTabFrame
- [ ] Implement grid layout with weight ratio
- [ ] Add labels and tooltips
- [ ] Write GUI unit tests

**Day 3: State Management**
- [ ] Add `get_current_negative_text()`
- [ ] Add `set_slot_negative()`
- [ ] Update `get_current_prompt_metadata()`
- [ ] Write state integration tests

**Day 4: Event Handlers**
- [ ] Implement `_on_negative_modified()`
- [ ] Update `_refresh_editor()` to load negative
- [ ] Update `_on_new_pack()` to clear negative
- [ ] Test event flow

**Day 5: Metadata & Advanced Editor**
- [ ] Update `_refresh_metadata()` with negative stats
- [ ] Update Advanced Editor integration
- [ ] Test roundtrip editing
- [ ] Execute manual test plan

---

**End of PR-GUI-003-A Specification**

**Ready for Implementation:** ✅  
**Estimated Completion:** 1 week  
**Next PR:** PR-GUI-003-B (Matrix Tab with Slots)
