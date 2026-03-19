# PR-GUI-003-B: Add Matrix Tab to Prompt Tab

**Status:** APPROVED  
**Target Version:** StableNew v2.6  
**Dependencies:** PR-GUI-003-A (negative prompt support)  
**Estimated Effort:** 5 days  
**Risk Level:** MEDIUM (new subsystem, preview generation complexity)

---

## Executive Summary

Add a dedicated **Matrix Tab** to the Prompt Tab that allows users to define **slot-based matrix configurations** for Cartesian prompt expansion. This replaces the simple wildcard helper with a full matrix editor that supports:

- Named slots with multiple values
- Preview of expanded combinations
- Integration with existing PromptRandomizer
- Export to TXT format with `[[slot_name]]` tokens
- Compatibility with current TXT pack format

The Matrix Tab enables users to create sophisticated prompt variations (e.g., `[[job]]` = wizard|knight|druid) directly in the Prompt Tab UI, with immediate preview of how many combinations will be generated.

---

## Problem Statement

### Current State

**Prompt Tab (JSON-based):**
- Has MatrixHelperDialog for inserting inline `{opt1|opt2}` wildcards
- No way to define reusable named slots
- No preview of Cartesian expansion
- Matrix config not persisted in JSON

**Pipeline Tab (TXT-based):**
- Packs use `[[environment]]`, `[[job]]` tokens
- Expanded by PromptRandomizer during job building
- No GUI for editing matrix definitions
- Matrix values hardcoded in lists/ folder

**Gap:**
Users cannot define matrix slots in Prompt Tab and see preview of combinations. They must manually edit TXT files or use the limited inline wildcard helper.

### Desired State

**Prompt Tab with Matrix Tab:**
- Define named slots (e.g., "job", "environment", "lighting")
- Assign multiple values per slot (comma-separated)
- Preview shows first 10 expanded combinations + total count
- Insert button adds `[[slot_name]]` token at cursor
- Matrix config saved in JSON, exported to TXT during save
- Compatible with existing PromptRandomizer in pipeline

---

## Requirements

### Functional Requirements

1. **Matrix Configuration Editor**
   - Enable/disable matrix checkbox
   - Mode selector: "fanout" (default), "sequential" (future)
   - Limit field: max combinations to generate (default: 8)
   - Slot table: name, values (comma-separated), delete button
   - Add Slot button: creates new empty row

2. **Preview Panel**
   - Shows total combination count
   - Lists first 10 expanded prompts
   - Updates in real-time as slots change
   - Indicates if limit truncates results

3. **Slot Insertion**
   - "Insert Slot..." button in Prompt/Negative editors
   - Opens dialog showing available slots
   - Inserts `[[slot_name]]` token at cursor

4. **Persistence**
   - Save matrix config in JSON pack file
   - Load matrix config when opening pack
   - Export to TXT with `[[tokens]]` for pipeline

5. **Integration**
   - Works with positive and negative prompts
   - Uses existing PromptRandomizer for expansion
   - Maintains backward compatibility with TXT packs

### Non-Functional Requirements

1. **Performance:** Preview updates in <100ms for typical configs
2. **Validation:** Warn if duplicate slot names, empty values
3. **Usability:** Clear visual separation from prompt editing
4. **Compatibility:** Works with existing TXT pack format

---

## Technical Design

### Data Model Changes

**File:** `src/gui/models/prompt_pack_model.py`

```python
@dataclass
class MatrixSlot:
    """Single slot in the matrix configuration."""
    name: str
    values: list[str]  # Parsed from comma-separated input

@dataclass
class MatrixConfig:
    """Matrix configuration for Cartesian prompt expansion."""
    enabled: bool = False
    mode: str = "fanout"  # "fanout" or "sequential"
    limit: int = 8        # Max combinations to generate
    slots: list[MatrixSlot] = field(default_factory=list)
    
    def get_slot_names(self) -> list[str]:
        """Return list of slot names for insertion."""
        return [slot.name for slot in self.slots]
    
    def get_slot_dict(self) -> dict[str, list[str]]:
        """Return dict format for PromptRandomizer."""
        return {slot.name: slot.values for slot in self.slots}

@dataclass
class PromptPackModel:
    name: str
    path: Path | None
    slots: list[PromptSlot]  # existing
    matrix: MatrixConfig = field(default_factory=MatrixConfig)  # NEW
```

**Changes:**
1. Add MatrixSlot and MatrixConfig dataclasses
2. Add `matrix: MatrixConfig` field to PromptPackModel
3. Update `save_to_file()` to serialize matrix config
4. Update `load_from_file()` to deserialize matrix config (with backward compatibility)

---

### UI Layout

**File:** `src/gui/views/prompt_tab_frame_v2.py`

**Modified:** `_build_center_panel()`

**Change:** Add Matrix tab after negative prompt editor

```
Current Layout (after PR-GUI-003-A):
┌─────────────────────────────────────────────┐
│ Header (New/Open/Save/Advanced/Matrix Help) │
├─────────────────────────────────────────────┤
│ Positive Prompt Label                       │
│ ┌─────────────────────────────────────────┐ │
│ │ Positive editor (height=8, weight=3)    │ │
│ └─────────────────────────────────────────┘ │
│ Negative Prompt Label                       │
│ ┌─────────────────────────────────────────┐ │
│ │ Negative editor (height=4, weight=1)    │ │
│ └─────────────────────────────────────────┘ │
└─────────────────────────────────────────────┘

New Layout (PR-GUI-003-B):
┌─────────────────────────────────────────────┐
│ Header (New/Open/Save/Advanced)             │
├─────────────────────────────────────────────┤
│ Notebook with 2 tabs:                       │
│ ┌──────────┬──────────┐                     │
│ │ Prompts  │ Matrix   │                     │
│ └──────────┴──────────┘                     │
│ ┌─────────────────────────────────────────┐ │
│ │ [Prompts Tab]                           │ │
│ │ Positive Prompt Label                   │ │
│ │ ┌─────────────────────────────────────┐ │ │
│ │ │ Positive editor (height=8)          │ │ │
│ │ │ [Insert Slot...] button in corner   │ │ │
│ │ └─────────────────────────────────────┘ │ │
│ │ Negative Prompt Label                   │ │
│ │ ┌─────────────────────────────────────┐ │ │
│ │ │ Negative editor (height=4)          │ │ │
│ │ │ [Insert Slot...] button in corner   │ │ │
│ │ └─────────────────────────────────────┘ │ │
│ └─────────────────────────────────────────┘ │
│ ┌─────────────────────────────────────────┐ │
│ │ [Matrix Tab]                            │ │
│ │ [x] Enable Matrix                       │ │
│ │ Mode: [fanout ▼]  Limit: [8    ]       │ │
│ │                                         │ │
│ │ Matrix Slots:                           │ │
│ │ ┌─────┬──────────────┬──────┐          │ │
│ │ │Name │Values        │Delete│          │ │
│ │ ├─────┼──────────────┼──────┤          │ │
│ │ │job  │wizard,knight │ [X]  │          │ │
│ │ │env  │forest,castle │ [X]  │          │ │
│ │ └─────┴──────────────┴──────┘          │ │
│ │ [+ Add Slot]                            │ │
│ │                                         │ │
│ │ Preview (4 combinations):               │ │
│ │ 1. [[job]]=wizard [[env]]=forest       │ │
│ │ 2. [[job]]=wizard [[env]]=castle       │ │
│ │ 3. [[job]]=knight [[env]]=forest       │ │
│ │ 4. [[job]]=knight [[env]]=castle       │ │
│ └─────────────────────────────────────────┘ │
└─────────────────────────────────────────────┘
```

---

### Component Breakdown

#### 1. MatrixTabPanel (New Widget)

**File:** `src/gui/widgets/matrix_tab_panel.py`

**Purpose:** Self-contained matrix editor widget

**Interface:**
```python
class MatrixTabPanel(ttk.Frame):
    def __init__(
        self,
        parent,
        workspace_state: PromptWorkspaceState,
        on_matrix_changed: Callable[[], None],
    ):
        """
        Args:
            parent: Parent widget
            workspace_state: Access to current pack and matrix config
            on_matrix_changed: Callback when matrix config changes (for dirty tracking)
        """
        
    def refresh(self) -> None:
        """Reload matrix config from workspace state."""
        
    def _build_ui(self) -> None:
        """Build enable checkbox, mode/limit, slot table, preview."""
        
    def _on_enable_changed(self) -> None:
        """Enable/disable matrix, update preview."""
        
    def _on_slot_added(self) -> None:
        """Add new empty slot row."""
        
    def _on_slot_deleted(self, index: int) -> None:
        """Remove slot at index."""
        
    def _on_slot_changed(self, index: int, name: str, values_text: str) -> None:
        """Update slot name/values, re-generate preview."""
        
    def _update_preview(self) -> None:
        """Generate and display expanded combinations."""
        
    def get_matrix_config(self) -> MatrixConfig:
        """Return current matrix configuration."""
```

**UI Structure:**
1. **Header Frame:**
   - Checkbox: "Enable Matrix"
   - Label + Combobox: "Mode: [fanout ▼]"
   - Label + Spinbox: "Limit: [8]"

2. **Slots Frame (with scrollbar):**
   - Treeview with columns: "Name", "Values", "Delete"
   - Each row: Entry for name, Entry for values, Button [X]
   - Add Slot button at bottom

3. **Preview Frame:**
   - Label: "Preview (N combinations):"
   - Text widget (read-only, height=10)
   - Shows first 10 expanded combinations

---

#### 2. Slot Insertion Dialog

**File:** `src/gui/widgets/matrix_slot_picker.py`

**Purpose:** Modal dialog to pick which slot to insert

**Interface:**
```python
class MatrixSlotPickerDialog(tk.Toplevel):
    def __init__(
        self,
        parent,
        available_slots: list[str],
        on_select: Callable[[str], None],
    ):
        """
        Args:
            parent: Parent window
            available_slots: List of slot names from matrix config
            on_select: Callback with selected slot name
        """
        
    def _build_ui(self) -> None:
        """Build listbox with slots, Insert/Cancel buttons."""
```

**UI:**
```
┌────────────────────────┐
│ Select Slot to Insert  │
├────────────────────────┤
│ ┌────────────────────┐ │
│ │ job                │ │
│ │ environment        │ │
│ │ lighting           │ │
│ └────────────────────┘ │
│                        │
│   [Insert]  [Cancel]   │
└────────────────────────┘
```

---

#### 3. PromptTabFrame Integration

**File:** `src/gui/views/prompt_tab_frame_v2.py`

**Changes:**

1. **Replace direct editor layout with notebook:**
   ```python
   def _build_center_panel(self) -> ttk.Frame:
       # Create notebook for Prompts vs Matrix
       self.editor_notebook = ttk.Notebook(self.center_frame)
       self.editor_notebook.pack(fill="both", expand=True)
       
       # Prompts tab (existing editors)
       self.prompts_tab = ttk.Frame(self.editor_notebook)
       self.editor_notebook.add(self.prompts_tab, text="Prompts")
       self._build_prompts_tab()
       
       # Matrix tab (new)
       self.matrix_tab_panel = MatrixTabPanel(
           self.editor_notebook,
           workspace_state=self.workspace_state,
           on_matrix_changed=self._on_matrix_changed,
       )
       self.editor_notebook.add(self.matrix_tab_panel, text="Matrix")
   ```

2. **Add "Insert Slot..." buttons:**
   ```python
   def _build_prompts_tab(self) -> None:
       # Positive editor frame
       pos_frame = ttk.Frame(self.prompts_tab)
       pos_frame.pack(fill="both", expand=True)
       
       # Label and Insert button in same row
       header_frame = ttk.Frame(pos_frame)
       header_frame.pack(fill="x", pady=(0, 2))
       ttk.Label(header_frame, text="Positive Prompt").pack(side="left")
       ttk.Button(
           header_frame,
           text="Insert Slot...",
           command=self._insert_slot_into_positive,
       ).pack(side="right")
       
       # Editor
       self.editor = tk.Text(pos_frame, height=8, wrap="word")
       self.editor.pack(fill="both", expand=True)
       
       # Same for negative editor...
   ```

3. **Add slot insertion handlers:**
   ```python
   def _insert_slot_into_positive(self) -> None:
       """Open slot picker and insert [[slot_name]] into positive editor."""
       matrix_config = self.workspace_state.get_matrix_config()
       if not matrix_config.slots:
           messagebox.showinfo("No Slots", "Define matrix slots in the Matrix tab first.")
           return
       
       def on_select(slot_name: str):
           self.editor.insert("insert", f"[[{slot_name}]]")
           self._on_editor_modified(None)  # Mark dirty
       
       MatrixSlotPickerDialog(
           self,
           available_slots=matrix_config.get_slot_names(),
           on_select=on_select,
       )
   
   def _insert_slot_into_negative(self) -> None:
       """Open slot picker and insert [[slot_name]] into negative editor."""
       # Same as above but for negative_editor
   ```

4. **Add matrix change handler:**
   ```python
   def _on_matrix_changed(self) -> None:
       """Called when matrix config changes in Matrix tab."""
       self.workspace_state.mark_dirty()
       self._update_pack_name_label()  # Show asterisk
   ```

5. **Update refresh to reload matrix tab:**
   ```python
   def _refresh_editor(self, index: int | None = None) -> None:
       # ... existing slot loading ...
       
       # Refresh matrix tab
       if hasattr(self, "matrix_tab_panel"):
           self.matrix_tab_panel.refresh()
   ```

---

#### 4. PromptWorkspaceState Integration

**File:** `src/gui/prompt_workspace_state.py`

**Changes:**

```python
class PromptWorkspaceState:
    # ... existing methods ...
    
    def get_matrix_config(self) -> MatrixConfig:
        """Get current pack's matrix configuration."""
        if self.current_pack:
            return self.current_pack.matrix
        return MatrixConfig()  # Default empty
    
    def set_matrix_config(self, matrix: MatrixConfig) -> None:
        """Update current pack's matrix configuration."""
        if self.current_pack:
            self.current_pack.matrix = matrix
            self.mark_dirty()
```

---

### Preview Generation

**File:** `src/gui/widgets/matrix_tab_panel.py`

**Method:** `_update_preview()`

**Logic:**
```python
def _update_preview(self) -> None:
    """Generate preview of expanded combinations using PromptRandomizer."""
    matrix_config = self.workspace_state.get_matrix_config()
    
    if not matrix_config.enabled or not matrix_config.slots:
        self.preview_text.delete("1.0", "end")
        self.preview_text.insert("1.0", "Matrix disabled or no slots defined.")
        return
    
    # Get current positive prompt (with [[tokens]])
    current_slot = self.workspace_state.get_current_slot()
    if not current_slot or not current_slot.text.strip():
        self.preview_text.delete("1.0", "end")
        self.preview_text.insert("1.0", "No prompt text to preview.")
        return
    
    # Build slot dict for randomizer
    slot_dict = matrix_config.get_slot_dict()
    
    # Use PromptRandomizer to expand
    try:
        from src.utils.randomizer import PromptRandomizer
        
        randomizer = PromptRandomizer(custom_lists=slot_dict)
        expanded = randomizer.expand_prompt(
            current_slot.text,
            mode=matrix_config.mode,
            limit=matrix_config.limit,
        )
        
        # Display results
        total = len(expanded)
        preview_lines = [f"Preview ({total} combinations):"]
        
        for i, prompt in enumerate(expanded[:10], start=1):
            preview_lines.append(f"{i}. {prompt[:100]}...")  # Truncate long prompts
        
        if total > 10:
            preview_lines.append(f"... and {total - 10} more")
        
        self.preview_text.delete("1.0", "end")
        self.preview_text.insert("1.0", "\n".join(preview_lines))
        
    except Exception as e:
        self.preview_text.delete("1.0", "end")
        self.preview_text.insert("1.0", f"Error generating preview: {e}")
```

---

### Export to TXT Format

**File:** `src/gui/models/prompt_pack_model.py`

**Method:** `save_to_file()`

**Logic:**
```python
def save_to_file(self, path: str | Path | None = None) -> Path:
    """Save pack as JSON (and auto-export to TXT if in packs/ folder)."""
    target = Path(path or self.path or f"{self.name}.json")
    
    # Save JSON
    data = {
        "name": self.name,
        "slots": [
            {
                "index": slot.index,
                "text": slot.text,
                "negative": getattr(slot, "negative", ""),
            }
            for slot in self.slots
        ],
        "matrix": {
            "enabled": self.matrix.enabled,
            "mode": self.matrix.mode,
            "limit": self.matrix.limit,
            "slots": [
                {"name": s.name, "values": s.values}
                for s in self.matrix.slots
            ],
        },
    }
    
    target.write_text(json.dumps(data, indent=2), encoding="utf-8")
    self.path = target
    
    # Auto-export TXT if in packs/ folder (for Pipeline Tab compatibility)
    if "packs" in target.parts:
        self._export_txt(target.with_suffix(".txt"))
    
    return target

def _export_txt(self, txt_path: Path) -> None:
    """Export to TXT format with [[tokens]] for pipeline."""
    lines = []
    
    for slot in self.slots:
        if not slot.text.strip():
            continue
        
        # Positive prompt (with [[tokens]] preserved)
        lines.append(slot.text.strip())
        
        # Negative prompt (with neg: prefix)
        negative = getattr(slot, "negative", "").strip()
        if negative:
            # Split into lines if multi-line, prefix each with neg:
            neg_lines = [f"neg: {line.strip()}" for line in negative.split("\n") if line.strip()]
            lines.extend(neg_lines)
        
        # Blank line separator
        lines.append("")
    
    txt_path.write_text("\n".join(lines), encoding="utf-8")
```

**TXT Output Example:**
```
<embedding:stable_yogis_pdxl_positives>
(masterpiece, best quality) portrait, [[job]] in [[environment]]
<lora:add-detail-xl:0.65>
neg: <embedding:negative_hands>
neg: bad quality, blurry, distorted

<embedding:stable_yogis_pdxl_positives>
(masterpiece, best quality) portrait, [[job]] casting spell
<lora:add-detail-xl:0.65>
neg: <embedding:negative_hands>
neg: bad quality, blurry, distorted
```

**Matrix Definition (in JSON only):**
```json
{
  "matrix": {
    "enabled": true,
    "mode": "fanout",
    "limit": 8,
    "slots": [
      {"name": "job", "values": ["wizard", "knight", "druid"]},
      {"name": "environment", "values": ["forest", "castle", "dungeon"]}
    ]
  }
}
```

**Note:** The TXT file contains `[[tokens]]` but NOT the slot definitions. The matrix definitions live in JSON only. The Pipeline Tab's PromptRandomizer expands `[[tokens]]` using the lists/ folder (existing behavior). Future PR-GUI-003-C will pass JSON metadata to pipeline for expansion.

---

## Implementation Plan

### Day 1: Data Model (4 hours)

**Tasks:**
1. Add MatrixSlot, MatrixConfig dataclasses to prompt_pack_model.py
2. Add `matrix: MatrixConfig` field to PromptPackModel
3. Update `save_to_file()` to serialize matrix
4. Update `load_from_file()` to deserialize matrix (with backward compat)
5. Add `_export_txt()` method for TXT format
6. Write 8 unit tests for data model

**Files:**
- `src/gui/models/prompt_pack_model.py` (modified)
- `tests/gui_v2/test_prompt_pack_model_matrix.py` (new)

**Tests:**
- test_matrix_config_default
- test_matrix_config_serialization
- test_matrix_config_backward_compat
- test_export_txt_with_matrix_tokens
- test_export_txt_with_negative
- test_load_json_with_matrix
- test_matrix_slot_dict_generation
- test_matrix_get_slot_names

---

### Day 2: MatrixTabPanel Widget (6 hours)

**Tasks:**
1. Create MatrixTabPanel class in new file
2. Build UI: enable checkbox, mode/limit, slot table
3. Implement add/delete/edit slot handlers
4. Add validation (duplicate names, empty values)
5. Wire up on_matrix_changed callback
6. Write 6 widget tests (if possible without full Tk)

**Files:**
- `src/gui/widgets/matrix_tab_panel.py` (new)
- `tests/gui_v2/test_matrix_tab_panel.py` (new, integration-style)

**Tests:**
- test_matrix_panel_enable_disable
- test_matrix_panel_add_slot
- test_matrix_panel_delete_slot
- test_matrix_panel_slot_validation
- test_matrix_panel_mode_limit_change
- test_matrix_panel_get_config

---

### Day 3: Preview Generation (4 hours)

**Tasks:**
1. Add `_update_preview()` method to MatrixTabPanel
2. Integrate with PromptRandomizer for expansion
3. Display first 10 combinations with truncation
4. Handle edge cases (no slots, no text, errors)
5. Write 5 preview tests

**Files:**
- `src/gui/widgets/matrix_tab_panel.py` (modified)
- `tests/gui_v2/test_matrix_preview.py` (new)

**Tests:**
- test_preview_with_single_slot
- test_preview_with_multiple_slots
- test_preview_respects_limit
- test_preview_no_tokens_in_prompt
- test_preview_error_handling

---

### Day 4: Slot Insertion & Integration (5 hours)

**Tasks:**
1. Create MatrixSlotPickerDialog widget
2. Add "Insert Slot..." buttons to positive/negative editors
3. Implement `_insert_slot_into_positive/negative()` handlers
4. Update PromptWorkspaceState with matrix methods
5. Integrate MatrixTabPanel into PromptTabFrame notebook
6. Update `_refresh_editor()` to reload matrix tab
7. Write 6 integration tests

**Files:**
- `src/gui/widgets/matrix_slot_picker.py` (new)
- `src/gui/views/prompt_tab_frame_v2.py` (modified)
- `src/gui/prompt_workspace_state.py` (modified)
- `tests/gui_v2/test_matrix_integration.py` (new)

**Tests:**
- test_insert_slot_button_appears
- test_insert_slot_adds_token
- test_slot_picker_shows_available_slots
- test_matrix_tab_appears_in_notebook
- test_matrix_config_persists_across_slots
- test_dirty_flag_on_matrix_change

---

### Day 5: Testing & Documentation (5 hours)

**Tasks:**
1. Run full GUI test suite
2. Manual testing: create pack, define matrix, preview, save, reload
3. Test TXT export with [[tokens]]
4. Test backward compatibility (old JSON without matrix)
5. Update CHANGELOG
6. Update PR status document

**Files:**
- `CHANGELOG.md` (updated)
- `docs/PR-GUI-003-B-STATUS.md` (new)

**Manual Tests:**
- Create new pack, add 2 slots, see preview
- Insert [[slot]] into prompt, verify token appears
- Save pack, verify JSON has matrix field
- Reload pack, verify matrix tab loads correctly
- Check TXT export has [[tokens]] and neg: lines
- Open old pack without matrix field, verify no errors

---

## Test Strategy

### Unit Tests (20 tests total)

**test_prompt_pack_model_matrix.py** (8 tests):
- Matrix config creation and defaults
- Serialization/deserialization
- Backward compatibility with old JSON
- TXT export with [[tokens]] and neg: lines
- Slot dict generation
- get_slot_names() method

**test_matrix_tab_panel.py** (6 tests):
- Enable/disable functionality
- Add/delete/edit slots
- Validation (duplicates, empty values)
- get_matrix_config() method
- Callback invocation on changes

**test_matrix_preview.py** (5 tests):
- Preview with single/multiple slots
- Limit enforcement
- No tokens in prompt case
- Error handling

**test_matrix_integration.py** (6 tests):
- Insert Slot button functionality
- Token insertion at cursor
- Matrix tab in notebook
- Persistence across slot switches
- Dirty flag tracking
- PromptWorkspaceState matrix methods

---

### Integration Tests (Manual)

1. **Create New Pack with Matrix:**
   - Launch GUI → Prompt Tab → New
   - Switch to Matrix tab
   - Enable matrix, add slot "job" with "wizard,knight"
   - Add slot "env" with "forest,castle"
   - Check preview shows 4 combinations
   - Save pack as "test_matrix.json"
   - Verify "test_matrix.txt" created with [[tokens]]

2. **Insert Slot Token:**
   - Switch to Prompts tab
   - Click "Insert Slot..." in positive editor
   - Select "job" from picker
   - Verify [[job]] appears at cursor
   - Type more text after token
   - Save, reload, verify token preserved

3. **Preview Updates:**
   - Matrix tab, change "job" values to "wizard,knight,druid"
   - Verify preview updates to 6 combinations
   - Change limit to 4
   - Verify preview shows only 4

4. **Backward Compatibility:**
   - Open old pack (from PR-GUI-003-A, no matrix field)
   - Verify Matrix tab shows disabled state
   - Enable matrix, add slot
   - Save, verify JSON now has matrix field

5. **TXT Export Format:**
   - Create pack with embeddings and LoRAs
   - Add negative prompts
   - Add [[tokens]]
   - Save
   - Open TXT file, verify:
     - Embeddings preserved
     - LoRAs preserved
     - [[tokens]] preserved
     - neg: lines for negative prompts
     - Blank line separators between blocks

---

## Acceptance Criteria

### Must Have

- ✅ Matrix tab appears as second tab in Prompt Tab notebook
- ✅ Can enable/disable matrix
- ✅ Can add/edit/delete matrix slots
- ✅ Preview shows expanded combinations (first 10 + count)
- ✅ "Insert Slot..." button in positive and negative editors
- ✅ Slot picker dialog shows available slots
- ✅ `[[slot_name]]` token inserted at cursor
- ✅ Matrix config saved in JSON pack file
- ✅ Matrix config loaded when opening pack
- ✅ TXT export includes [[tokens]] and neg: lines
- ✅ 20+ tests pass
- ✅ No errors when opening old packs (backward compat)

### Should Have

- ✅ Preview updates in real-time (<100ms)
- ✅ Validation warnings for duplicate slot names
- ✅ Validation warnings for empty values
- ✅ Preview indicates if limit truncates
- ✅ Mode selector (fanout default, sequential grayed out)

### Nice to Have

- ⏳ Drag-and-drop reordering of slots (defer to future PR)
- ⏳ Slot value suggestions from lists/ folder (defer to future PR)
- ⏳ Preview shows full prompts in tooltip (defer to future PR)

---

## Risk Assessment

### MEDIUM Risks

1. **Preview Performance:**
   - **Risk:** Large matrix (10+ slots) could slow preview generation
   - **Mitigation:** Always limit preview to first 10, add timeout

2. **PromptRandomizer Integration:**
   - **Risk:** PromptRandomizer may not handle [[tokens]] exactly as expected
   - **Mitigation:** Test thoroughly with real packs, add unit tests

3. **UI Complexity:**
   - **Risk:** Notebook + nested frames may cause layout issues
   - **Mitigation:** Test on different window sizes, use pack/grid carefully

### LOW Risks

4. **Backward Compatibility:**
   - **Risk:** Old JSON without matrix field may crash
   - **Mitigation:** Use `field(default_factory=MatrixConfig)` for safe defaults

5. **TXT Export Format:**
   - **Risk:** Pipeline Tab may not recognize new TXT format
   - **Mitigation:** TXT format unchanged, just adds [[tokens]] (already supported)

---

## Documentation Updates

### Files to Update

1. **CHANGELOG.md:**
   ```markdown
   - [PR-GUI-003-B] Matrix Tab in Prompt Tab (v2.6) - **COMPLETE**
     - Added dedicated Matrix tab for defining slot-based matrix configurations
     - Slot table editor with name, values, and delete button
     - Real-time preview of Cartesian expansion (first 10 + total count)
     - "Insert Slot..." buttons in positive/negative editors
     - Matrix config persisted in JSON pack files
     - TXT export includes [[tokens]] for pipeline compatibility
     - 20+ tests covering data model, preview, integration
   ```

2. **docs/PROMPT_PACK_LIFECYCLE_v2.6.md:**
   - Add section on Matrix Tab usage
   - Document JSON schema with matrix field
   - Explain [[token]] expansion workflow

3. **docs/D-GUI-003-REVISED-PromptTab-Integration-Analysis.md:**
   - Mark PR-GUI-003-B as COMPLETE
   - Update status table

---

## Follow-Up Work (Future PRs)

**PR-GUI-003-C: Dual Format Export**
- Enhance TXT export to include slot definitions as comments
- Pass JSON metadata to pipeline for expansion

**PR-GUI-003-D: Bidirectional Pack Editing**
- "Edit Pack" button in Pipeline Tab
- Import TXT → JSON converter

**PR-GUI-003-E: Matrix System Testing**
- End-to-end tests with real pipeline execution
- Verify [[tokens]] expand correctly in job building

**PR-GUI-003-F: Documentation Updates**
- User guide for Matrix Tab
- Video tutorial or GIFs
- Reconcile all v2.6 docs

---

## Appendix: File Changes Summary

| File | Type | LOC | Description |
|------|------|-----|-------------|
| `src/gui/models/prompt_pack_model.py` | Modified | +80 | Add MatrixConfig, update save/load, add _export_txt() |
| `src/gui/views/prompt_tab_frame_v2.py` | Modified | +150 | Add notebook, matrix tab, insert slot buttons |
| `src/gui/prompt_workspace_state.py` | Modified | +15 | Add get/set_matrix_config() methods |
| `src/gui/widgets/matrix_tab_panel.py` | New | +300 | Matrix editor widget with preview |
| `src/gui/widgets/matrix_slot_picker.py` | New | +80 | Slot picker dialog for insertion |
| `tests/gui_v2/test_prompt_pack_model_matrix.py` | New | +250 | Data model tests |
| `tests/gui_v2/test_matrix_tab_panel.py` | New | +200 | Widget tests |
| `tests/gui_v2/test_matrix_preview.py` | New | +150 | Preview generation tests |
| `tests/gui_v2/test_matrix_integration.py` | New | +200 | Integration tests |
| `CHANGELOG.md` | Modified | +10 | Document changes |

**Total:** ~1,435 lines (code + tests + docs)

---

## Sign-Off

**Author:** ChatGPT (Planner)  
**Approver:** Human (Rob)  
**Date:** 2025-12-19  
**Status:** Ready for implementation by Codex

---

**END OF PR-GUI-003-B SPECIFICATION**
