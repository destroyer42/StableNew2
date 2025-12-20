# D-GUI-003-REVISED: Prompt Tab Integration Analysis

**Status:** Discovery Document (REVISED after finding existing Prompt tab)  
**Date:** December 19, 2025  
**Version:** v2.6  
**Author:** Analysis by Copilot

---

## Executive Summary

**CRITICAL DISCOVERY:** The V2 GUI already has a fully functional **Prompt tab** that was overlooked in the initial analysis.

**What Actually Exists:**
- ✅ **PromptTabFrame** - First tab in MainWindowV2 (before Pipeline, before Learning)
- ✅ **Prompt Slots** - 10-slot editor with New/Open/Save/Save As buttons
- ✅ **AdvancedPromptEditorV2** - Modal dialog with positive + negative prompt editors
- ✅ **MatrixHelperDialog** - Modal for inserting `{opt1|opt2|opt3}` expressions
- ✅ **PromptWorkspaceState** - State management for current pack + slots
- ✅ **PromptPackModel** - JSON-based pack save/load (slots with index + text)

**What This Changes:**
- ❌ **PR-GUI-003-A is OBSOLETE** - Advanced editor IS already integrated
- ❌ **PR-GUI-003-B is OBSOLETE** - Matrix helper already exists
- ⚠️ **PR-GUI-003-C needs revision** - Wiring exists but uses different architecture
- ⚠️ **PR-GUI-003-D needs revision** - RandomizerPanelV2 is separate from Prompt tab
- ✅ **PR-GUI-003-E remains valid** - Testing still needed
- ✅ **PR-GUI-003-F remains valid** - Docs need updating

**Key Architectural Insight:**
The current system has **TWO parallel prompt authoring paths**:
1. **Prompt Tab** → PromptPackModel (JSON with slots) → ???
2. **Pipeline Tab** → TXT-based packs → PromptPackNormalizedJobBuilder → NJR

These are NOT integrated. The Prompt tab creates JSON packs, but the Pipeline tab uses TXT packs.

---

## 1. Current Architecture (Actual Implementation)

### 1.1 Prompt Tab Components

**File:** `src/gui/views/prompt_tab_frame_v2.py`

**UI Structure:**
```
┌─────────────────────────────────────────────────────────────┐
│                        PROMPT TAB                           │
├───────────────┬──────────────────────┬──────────────────────┤
│  Left Panel   │    Center Panel      │    Right Panel       │
│               │                      │                      │
│ Prompt Slots  │  Editor              │ Current Slot Summary │
│ [Listbox]     │  - Pack Name (mod)   │ - Pack: name         │
│  Prompt 1     │  [Text Editor]       │ - Slot: 1            │
│  Prompt 2     │                      │ - Length: 123 chars  │
│  Prompt 3     │  [Advanced Editor]   │ - Matrix: 2          │
│  ...          │  [Insert Matrix...]  │ - LoRAs: 1           │
│  Prompt 10    │                      │ - Embeddings: 0      │
│               │                      │ - Pipeline Preview   │
│ [New]         │                      │                      │
│ [Open...]     │                      │                      │
│ [Save]        │                      │                      │
│ [Save As...]  │                      │                      │
└───────────────┴──────────────────────┴──────────────────────┘
```

**Key Features:**
- 10 prompt slots (hardcoded in UI, expandable in model)
- Slot selection → loads text into center editor
- Typing in editor → saves to current slot (marks dirty)
- Metadata panel shows LoRA/embedding detection, matrix count
- New/Open/Save/SaveAs → JSON file format

**Data Model:** `src/gui/models/prompt_pack_model.py`
```python
@dataclass
class PromptSlot:
    index: int
    text: str = ""

@dataclass
class PromptPackModel:
    name: str
    path: str | None = None
    slots: list[PromptSlot] = field(default_factory=list)
```

**Saved Format (JSON):**
```json
{
  "name": "MyPack",
  "slots": [
    {"index": 0, "text": "a wizard casting spells"},
    {"index": 1, "text": "a knight in armor"},
    {"index": 2, "text": ""}
  ]
}
```

---

### 1.2 Advanced Prompt Editor Integration

**File:** `src/gui/advanced_prompt_editor.py` (line 1553)

**Class:** `AdvancedPromptEditorV2(ttk.Frame)`

**Features:**
- Positive prompt text area (10 lines, word wrap)
- Optional negative prompt text area (6 lines)
- Apply/Cancel/Clear buttons
- Character count status (Prompt: 123 chars • Negative: 45 chars)
- Modified tracking

**Launch Points:**
1. **Prompt Tab:** "Advanced Editor" button → opens modal with current slot text
2. **Controller:** `on_open_advanced_editor()` → calls `window.open_advanced_editor()`

**Workflow:**
```
User clicks "Advanced Editor" button
    ↓
PromptTabFrame._on_open_advanced_editor()
    ↓
controller.on_open_advanced_editor() [if controller exists]
    ↓
Fallback: _open_advanced_editor_dialog() → creates Toplevel with AdvancedPromptEditorV2
    ↓
User edits, clicks Apply
    ↓
on_apply callback → PromptTabFrame.apply_prompt_text(prompt)
    ↓
workspace_state.set_slot_text(index, text) → marks dirty
    ↓
_refresh_editor() → updates UI
```

**Controller Integration:** `src/controller/app_controller.py` (line 1650)
```python
def on_open_advanced_editor(self) -> None:
    prompt = self._get_active_prompt_text()
    window.open_advanced_editor(
        initial_prompt=prompt,
        on_apply=self.on_advanced_prompt_applied,
    )

def on_advanced_prompt_applied(self, new_prompt: str, negative_prompt: str | None):
    # Updates workspace_state
    ws = self.app_state.prompt_workspace_state
    ws.set_slot_text(index, new_prompt)
    
    # Updates main window
    window.apply_prompt_text(new_prompt, negative_prompt)
    
    # Updates app_state
    self.app_state.set_prompt(new_prompt)
    self.app_state.set_negative_prompt(negative_prompt)
```

---

### 1.3 Matrix Helper Integration

**File:** `src/gui/widgets/matrix_helper_widget.py`

**Class:** `MatrixHelperDialog(tk.Toplevel)`

**Features:**
- Simple text area (8 lines, 40 width)
- Enter one option per line
- Insert button → builds `{opt1|opt2|opt3}` expression
- Cancel button → closes without inserting

**Launch Point:**
- **Prompt Tab:** "Insert Matrix..." button → opens modal

**Workflow:**
```
User clicks "Insert Matrix..." button
    ↓
PromptTabFrame._open_matrix_helper()
    ↓
MatrixHelperDialog(self, on_apply=self._insert_matrix_expression)
    ↓
User types:
    wizard
    knight
    druid
    ↓
Clicks "Insert"
    ↓
_build_matrix_expression() → "{wizard|knight|druid}"
    ↓
on_apply callback → PromptTabFrame._insert_matrix_expression(expr)
    ↓
self.editor.insert("insert", "{wizard|knight|druid}")
    ↓
_on_editor_modified() → saves to slot, marks dirty
```

**Matrix Syntax:**
- Uses `{opt1|opt2|opt3}` (curly braces + pipe separators)
- Inserted at cursor position in main editor
- Part of prompt text, not separate metadata

---

### 1.4 State Management

**File:** `src/gui/prompt_workspace_state.py`

**Class:** `PromptWorkspaceState`

**Responsibilities:**
- Holds current `PromptPackModel`
- Tracks dirty flag
- Tracks current slot index
- Provides save/load operations

**API:**
```python
class PromptWorkspaceState:
    def new_pack(name: str, slot_count: int = 10) -> PromptPackModel
    def load_pack(path: str | Path) -> PromptPackModel
    def save_current_pack(path: str | Path | None) -> Path
    def save_current_pack_as(path: str | Path) -> Path
    
    def get_slot(index: int) -> PromptSlot
    def set_slot_text(index: int, text: str) -> None
    
    def set_current_slot_index(index: int) -> None
    def get_current_slot_index() -> int
    def get_current_prompt_text() -> str
    def get_current_prompt_metadata() -> PromptMetadata
```

**Integration:**
- `PromptTabFrame.__init__()` creates instance
- `app_state.prompt_workspace_state = self.workspace_state` (line 42)
- Controller accesses via `self.app_state.prompt_workspace_state`

---

## 2. Gap Analysis (What's Actually Missing)

### 2.1 Critical Gap: Prompt Tab Packs ≠ Pipeline Tab Packs

**Problem:**
- **Prompt Tab** saves JSON files with `slots[]` structure
- **Pipeline Tab** expects TXT files with line-separated prompts

**Evidence:**
```python
# Prompt Tab saves:
{
  "name": "MyPack",
  "slots": [
    {"index": 0, "text": "prompt 1"},
    {"index": 1, "text": "prompt 2"}
  ]
}

# Pipeline Tab expects (from packs/ folder):
# MyPack.txt (line-separated prompts)
# MyPack.json (optional metadata with randomization config)
```

**Impact:**
- Packs created in Prompt Tab cannot be used in Pipeline Tab
- Pipeline Tab packs (TXT) cannot be edited in Prompt Tab
- Two separate ecosystems

**Root Cause:**
- Prompt Tab uses `PromptPackModel` (slots-based JSON)
- Pipeline Tab uses `read_prompt_pack()` from `src/utils/prompt_pack_utils.py` (TXT-based)

---

### 2.2 Missing: Matrix Slot Definition UI

**Current State:**
- MatrixHelperDialog inserts `{opt1|opt2|opt3}` inline expressions
- These are wildcards, not slot-based matrix system

**What's Missing:**
- No UI for defining matrix slots like `[[job]]`, `[[style]]`
- No base prompt field
- No slot name/values table
- No preview of Cartesian expansion

**Comparison:**

| Feature | Current (MatrixHelper) | Documented (Spec) |
|---------|------------------------|-------------------|
| Syntax | `{opt1\|opt2}` | `[[slot_name]]` |
| Definition | Inline in prompt | Separate slots table |
| Expansion | Wildcard (random choice) | Cartesian product |
| Base prompt | N/A | `"[[job]] [[style]]"` |
| Slots | N/A | `job: [druid, knight]` |

**What MatrixHelper Actually Does:**
- Inserts wildcard syntax for PromptRandomizer
- Single-dimension random choice, not Cartesian matrix
- No slot-based substitution

---

### 2.3 Missing: Negative Prompt in Prompt Tab

**Current State:**
- PromptTabFrame has NO negative prompt field
- AdvancedPromptEditorV2 DOES support negative prompt (optional parameter)
- Prompt tab only shows positive editor

**What's Missing:**
- Negative prompt text area in main Prompt tab UI
- Save/load negative prompts in PromptPackModel
- Integration with global negative prompt

**Impact:**
- Users can edit negative in Advanced Editor modal
- But it's not saved to pack JSON
- Not displayed in main tab

---

### 2.4 Missing: PromptPackModel → Pipeline Integration

**Current State:**
- Prompt Tab creates JSON packs
- Pipeline Tab expects TXT packs in `packs/` folder
- No bridge between them

**What's Needed:**
1. **Export to TXT:** PromptPackModel.export_to_txt() → creates TXT file
2. **Import from TXT:** PromptPackModel.import_from_txt() → loads TXT into slots
3. **Dual format:** Save both JSON (for editing) and TXT (for pipeline)
4. **Pipeline discovery:** Add JSON packs to pack list in sidebar

---

## 3. Revised Architecture Proposal

### 3.1 Unified Pack Format

**Goal:** One pack format usable by both Prompt Tab and Pipeline Tab

**Proposed Structure:**
```
packs/
  MyPack.json     ← Primary file (editable in Prompt Tab)
  MyPack.txt      ← Generated export (used by Pipeline)
```

**JSON Schema (extended PromptPackModel):**
```json
{
  "name": "MyPack",
  "version": "2.6",
  "slots": [
    {
      "index": 0,
      "text": "a [[job]] wearing [[clothes]]",
      "negative": "ugly, bad anatomy"
    }
  ],
  "matrix": {
    "enabled": true,
    "mode": "fanout",
    "base_prompt": "a [[job]] wearing [[clothes]]",
    "slots": [
      {"name": "job", "values": ["wizard", "knight"]},
      {"name": "clothes", "values": ["robes", "armor"]}
    ]
  },
  "metadata": {
    "created": "2025-12-19T10:30:00Z",
    "modified": "2025-12-19T11:45:00Z"
  }
}
```

**TXT Export (for pipeline compatibility):**
```
a wizard wearing robes
a wizard wearing armor
a knight wearing robes
a knight wearing armor
```

---

### 3.2 Integration Flow

**Pack Authoring:**
```
Prompt Tab
    ↓
Edit slots → Edit matrix (new tab) → Save JSON
    ↓
Auto-export to TXT (background)
    ↓
Pipeline Tab detects new pack
```

**Pack Selection:**
```
Pipeline Tab → Pack list (from packs/*.txt)
    ↓
Select pack → Load TXT for preview
    ↓
"Edit Pack" button → Opens Prompt Tab with JSON loaded
```

**Execution:**
```
Pipeline Tab → "Add to Job"
    ↓
read_prompt_pack(MyPack.txt) → gets expanded prompts
    ↓
PromptPackNormalizedJobBuilder → NJRs
```

---

## 4. Revised PR Series

### PR-GUI-003-A: Add Negative Prompt to Prompt Tab

**Goal:** Make Prompt Tab support negative prompts

**Scope:**
1. Extend PromptPackModel:
   ```python
   @dataclass
   class PromptSlot:
       index: int
       text: str = ""
       negative: str = ""  # NEW
   ```

2. Add negative prompt editor to PromptTabFrame center panel:
   ```python
   # Below main editor
   ttk.Label(self.center_frame, text="Negative Prompt").pack(anchor="w", pady=(6, 2))
   self.negative_editor = tk.Text(self.center_frame, height=4, wrap="word")
   self.negative_editor.pack(fill="both", expand=False, pady=(0, 6))
   self.negative_editor.bind("<<Modified>>", self._on_negative_modified)
   ```

3. Update save/load to handle negative field
4. Update metadata panel to show negative prompt length

**Files:**
- `src/gui/models/prompt_pack_model.py` - extend dataclass
- `src/gui/views/prompt_tab_frame_v2.py` - add negative editor
- `src/gui/prompt_workspace_state.py` - add get/set negative methods
- `tests/gui_v2/test_prompt_tab_negative.py` - new tests

**Acceptance:**
- ✅ Negative prompt editor appears below positive
- ✅ Typing in negative editor saves to slot
- ✅ Save/load preserves negative prompts
- ✅ Metadata panel shows negative length

---

### PR-GUI-003-B: Add Matrix Tab to Prompt Tab

**Goal:** Replace inline wildcard helper with proper slot-based matrix editor

**Scope:**
1. Add "Matrix" tab to PromptTabFrame (fourth panel option via sub-notebook or separate tab)
2. Matrix editor UI:
   ```
   ┌───────────────────────────────────────────┐
   │ Matrix Configuration                      │
   ├───────────────────────────────────────────┤
   │ [x] Enable Matrix                         │
   │ Mode: [Fanout ▼]  Limit: [8    ]          │
   │                                           │
   │ Slot Definitions:                         │
   │ ┌─────────┬──────────────────┬─────┐     │
   │ │ Name    │ Values (comma)   │ Del │     │
   │ ├─────────┼──────────────────┼─────┤     │
   │ │ job     │ wizard,knight    │ [X] │     │
   │ │ clothes │ robes,armor      │ [X] │     │
   │ │         │                  │     │     │
   │ └─────────┴──────────────────┴─────┘     │
   │ [+ Add Slot]                              │
   │                                           │
   │ Preview:                                  │
   │ Total combinations: 4                     │
   │ 1. wizard robes                           │
   │ 2. wizard armor                           │
   │ 3. knight robes                           │
   │ 4. knight armor                           │
   └───────────────────────────────────────────┘
   ```

3. Extend PromptPackModel:
   ```python
   @dataclass
   class MatrixSlot:
       name: str
       values: list[str]
   
   @dataclass
   class MatrixConfig:
       enabled: bool = False
       mode: str = "fanout"
       limit: int = 8
       slots: list[MatrixSlot] = field(default_factory=list)
   
   @dataclass
   class PromptPackModel:
       # ... existing fields ...
       matrix: MatrixConfig = field(default_factory=MatrixConfig)
   ```

4. Replace MatrixHelperDialog with slot insertion:
   - "Insert Matrix..." button → shows dialog to pick from defined slots
   - Inserts `[[slot_name]]` at cursor

5. Preview generator:
   - Use PromptRandomizer to expand current prompt with matrix
   - Show first 10 combinations
   - Display total count

**Files:**
- `src/gui/models/prompt_pack_model.py` - extend with MatrixConfig
- `src/gui/views/prompt_tab_frame_v2.py` - add matrix tab UI
- `src/gui/widgets/matrix_slot_editor.py` - new reusable widget
- `tests/gui_v2/test_prompt_tab_matrix.py` - matrix tab tests

**Acceptance:**
- ✅ Matrix tab appears in Prompt tab
- ✅ Can add/edit/delete matrix slots
- ✅ Preview shows expanded combinations
- ✅ Insert button adds `[[slot_name]]` to prompt
- ✅ Save/load preserves matrix config

---

### PR-GUI-003-C: Dual Format Export (JSON + TXT)

**Goal:** Make Prompt Tab packs usable in Pipeline Tab

**Scope:**
1. Extend PromptPackModel.save_to_file():
   ```python
   def save_to_file(self, path: str | Path | None = None) -> Path:
       # Save JSON (source of truth)
       target = Path(path or self.path or f"{self.name}.json")
       self._save_json(target)
       
       # Auto-export TXT (for pipeline compatibility)
       txt_path = target.with_suffix(".txt")
       self._export_txt(txt_path)
       
       return target
   
   def _export_txt(self, path: Path) -> None:
       """Export to TXT format for pipeline consumption."""
       lines = []
       for slot in self.slots:
           if slot.text.strip():
               # If matrix enabled, expand
               if self.matrix.enabled:
                   expanded = self._expand_matrix(slot.text)
                   lines.extend(expanded)
               else:
                   lines.append(slot.text)
       
       path.write_text("\n".join(lines), encoding="utf-8")
   ```

2. Matrix expansion during export:
   - Use PromptRandomizer to expand `[[slot_name]]` tokens
   - Write all combinations to TXT
   - TXT becomes "rendered" pack

3. Update Pipeline Tab pack discovery:
   - Scan `packs/*.txt` (existing)
   - If `packs/*.json` exists, prefer JSON for metadata
   - "Edit Pack" button → checks for JSON, opens Prompt Tab

4. Add "Export to Pipeline" button in Prompt Tab:
   - Saves JSON + TXT to `packs/` folder
   - Shows success message with path

**Files:**
- `src/gui/models/prompt_pack_model.py` - add _export_txt(), _expand_matrix()
- `src/gui/views/prompt_tab_frame_v2.py` - add "Export to Pipeline" button
- `src/utils/prompt_pack_utils.py` - extend to load JSON metadata if available
- `tests/gui_v2/test_pack_export.py` - export tests

**Acceptance:**
- ✅ Saving JSON auto-creates TXT
- ✅ TXT contains expanded matrix combinations (if enabled)
- ✅ Pipeline Tab shows exported packs
- ✅ "Export to Pipeline" copies to `packs/` folder
- ✅ JSON metadata loaded alongside TXT in pipeline

---

### PR-GUI-003-D: Bidirectional Pack Editing

**Goal:** Allow editing TXT packs from Pipeline Tab

**Scope:**
1. Add "Edit Pack" button in Pipeline Tab sidebar (near "Load Config")
2. Clicking "Edit Pack" with TXT-only pack:
   - Creates temporary JSON from TXT
   - Opens Prompt Tab with JSON loaded
   - Prompt Tab marks as "imported from TXT"

3. Import TXT → JSON converter:
   ```python
   @classmethod
   def import_from_txt(cls, txt_path: Path) -> PromptPackModel:
       """Import TXT pack into PromptPackModel (no matrix)."""
       lines = [line.strip() for line in txt_path.read_text().splitlines() if line.strip()]
       slots = [PromptSlot(index=i, text=line) for i, line in enumerate(lines)]
       # Pad to 10 slots
       while len(slots) < 10:
           slots.append(PromptSlot(index=len(slots), text=""))
       return cls(name=txt_path.stem, path=None, slots=slots)
   ```

4. Update Pipeline Tab controller:
   ```python
   def on_edit_pack_requested(self):
       selected_pack = self._get_selected_pack()
       json_path = Path("packs") / f"{selected_pack.name}.json"
       txt_path = Path("packs") / f"{selected_pack.name}.txt"
       
       if json_path.exists():
           # Open JSON in Prompt Tab
           self.app_state.open_prompt_tab_with_pack(json_path)
       elif txt_path.exists():
           # Import TXT, open in Prompt Tab
           pack = PromptPackModel.import_from_txt(txt_path)
           self.app_state.prompt_workspace_state.current_pack = pack
           self.app_state.switch_to_prompt_tab()
       else:
           messagebox.showerror("Edit Pack", "Pack file not found.")
   ```

**Files:**
- `src/gui/models/prompt_pack_model.py` - add import_from_txt()
- `src/gui/sidebar_panel_v2.py` - add "Edit Pack" button
- `src/controller/app_controller.py` - add on_edit_pack_requested()
- `src/gui/main_window_v2.py` - add switch_to_prompt_tab()
- `tests/gui_v2/test_bidirectional_pack_edit.py` - roundtrip tests

**Acceptance:**
- ✅ "Edit Pack" button appears in Pipeline Tab
- ✅ Clicking with JSON pack opens Prompt Tab with JSON
- ✅ Clicking with TXT-only pack imports and opens Prompt Tab
- ✅ Editing and saving updates TXT in packs/
- ✅ Changes immediately visible in Pipeline Tab

---

### PR-GUI-003-E: Matrix System Testing & Validation

**Goal:** Ensure matrix system is deterministic and robust

**(Same as original PR-GUI-003-E, no changes needed)**

**Scope:**
1. Pack-level validation
2. Runtime validation
3. Test matrix (2×2, 3×3×3, sequential, random, etc.)
4. Golden path E2E test

**Files:**
- `src/utils/validators/pack_validator.py`
- `tests/utils/test_matrix_validation.py`
- `tests/pipeline/test_matrix_determinism.py`
- `tests/e2e/test_matrix_golden_path.py`

**Acceptance:**
- ✅ All validation rules enforced
- ✅ Tests pass for all modes × limits
- ✅ Deterministic output with same seed
- ✅ Golden path: pack with matrix → 4 images

---

### PR-GUI-003-F: Documentation & Architecture Reconciliation

**Goal:** Update docs to reflect actual V2 Prompt Tab architecture

**Scope:**
1. Create `Prompt_Tab_Architecture_v2.6.md`:
   - Document PromptPackModel JSON format
   - Document matrix slot system vs wildcard system
   - Document dual-format export (JSON + TXT)
   - Document Prompt Tab ↔ Pipeline Tab integration

2. Update `PROMPT_PACK_LIFECYCLE_v2.6.md`:
   - Add Prompt Tab authoring section
   - Clarify JSON vs TXT formats
   - Document matrix expansion during export

3. Update `Randomizer_Spec_v2.5.md`:
   - Distinguish prompt matrix (slots) from config sweep (future)
   - Document `[[slot_name]]` syntax (used) vs `{wildcard}` syntax (legacy)

4. Update initial D-GUI-003 analysis:
   - Add DEPRECATED notice
   - Link to this revised document

**Files:**
- `docs/Prompt_Tab_Architecture_v2.6.md` - NEW
- `docs/PROMPT_PACK_LIFECYCLE_v2.6.md` - UPDATE
- `docs/Randomizer_Spec_v2.5.md` - RECONCILE
- `docs/D-GUI-003-PromptPackBuilder-Randomizer-Integration-Analysis.md` - DEPRECATE

**Acceptance:**
- ✅ User can follow Prompt Tab guide to create matrix pack
- ✅ JSON format fully documented
- ✅ No conflicting specs
- ✅ Clear distinction: slot matrix vs wildcards vs config sweep

---

## 5. Key Architectural Decisions

### 5.1 Keep Prompt Tab Separate from Pipeline Tab

**Rationale:**
- Prompt Tab = **authoring** environment (creative, iterative)
- Pipeline Tab = **execution** environment (batching, config)
- Clean separation of concerns

**Integration Points:**
1. Export button (Prompt → Pipeline)
2. Edit button (Pipeline → Prompt)
3. Shared pack format (JSON source, TXT runtime)

---

### 5.2 JSON as Source of Truth, TXT as Export

**Rationale:**
- JSON preserves all metadata (negative, matrix slots, timestamps)
- TXT is simple, line-separated format for pipeline
- Auto-export keeps them in sync

**Trade-off:**
- Two files per pack (MyPack.json + MyPack.txt)
- TXT is generated, should not be edited by hand
- If TXT edited externally, can be re-imported to JSON

---

### 5.3 Slot-Based Matrix vs Inline Wildcards

**Current Confusion:**
- MatrixHelper inserts `{opt1|opt2}` (wildcards)
- Documented spec uses `[[slot]]` (slots)
- PromptRandomizer supports BOTH

**Decision:**
- **Prompt Tab** uses `[[slot]]` with explicit slot definitions
- **Legacy TXT packs** can still use `{wildcard}`
- PromptRandomizer handles both during expansion

**Why:**
- Slots allow preview before execution
- Slots enable Cartesian product control
- Wildcards are fire-and-forget (can't preview combos)

---

## 6. Migration Path

### 6.1 Existing Prompt Tab Users

**Scenario:** User has JSON packs created in Prompt Tab

**Action:** PR-GUI-003-C auto-exports TXT on save
- Old JSON packs get retroactive TXT export on first save
- No breaking changes to JSON format
- Add matrix field (empty by default)

---

### 6.2 Existing Pipeline Tab Users

**Scenario:** User has TXT packs in `packs/` folder

**Action:** TXT packs continue working as-is
- No changes to TXT loading
- Optional: Import to JSON for matrix editing
- "Edit Pack" button offers import workflow

---

### 6.3 Mixed Users

**Scenario:** User has both JSON (Prompt Tab) and TXT (Pipeline Tab) packs

**Action:** Gradual convergence
- PR-GUI-003-C: JSON packs start exporting TXT
- PR-GUI-003-D: TXT packs can be imported to JSON
- Over time, all packs become JSON+TXT pairs

---

## 7. Comparison: Original Analysis vs Reality

| Aspect | Original Analysis | Actual Reality |
|--------|------------------|----------------|
| Advanced Editor | "Not in V2, needs integration" | ✅ Fully integrated in Prompt Tab |
| Matrix Helper | "Missing, needs implementation" | ✅ Exists as MatrixHelperDialog |
| Prompt Slots | "Not documented" | ✅ 10-slot editor in Prompt Tab |
| Pack Format | "TXT only" | ⚠️ TWO formats (JSON in Prompt, TXT in Pipeline) |
| Matrix System | "Not implemented" | ⚠️ Wildcards exist, slots missing |
| Negative Prompt | "Missing" | ⚠️ In Advanced Editor, not in Prompt Tab |

---

## 8. Risks & Mitigation

### 8.1 Format Fragmentation

**Risk:** Users create JSON packs that don't work in Pipeline Tab

**Mitigation:**
- PR-GUI-003-C auto-exports TXT on save
- "Export to Pipeline" button is prominent
- Validation warns if matrix not yet exported

---

### 8.2 Matrix Complexity

**Risk:** Cartesian explosion (10×10×10 = 1000 combos)

**Mitigation:**
- PR-GUI-003-B preview shows count BEFORE export
- Limit field enforces cap (default 8, max 512)
- UI warning at 128+ combos

---

### 8.3 User Confusion

**Risk:** Two matrix systems (wildcards vs slots)

**Mitigation:**
- PR-GUI-003-F docs clearly distinguish
- Prompt Tab tutorial uses slots only
- Deprecate wildcard syntax in new packs (support legacy)

---

## 9. Success Metrics

### 9.1 Functional Goals

✅ **By PR-GUI-003-A:**
- Prompt Tab supports negative prompts

✅ **By PR-GUI-003-B:**
- Prompt Tab has Matrix tab with slot editor

✅ **By PR-GUI-003-C:**
- JSON packs auto-export to TXT
- Pipeline Tab loads exported packs

✅ **By PR-GUI-003-D:**
- "Edit Pack" in Pipeline Tab opens Prompt Tab
- Roundtrip editing works (TXT → JSON → edit → TXT)

✅ **By PR-GUI-003-F:**
- Zero conflicting documentation
- User guide covers full workflow

---

### 9.2 Quality Gates

**Before each PR merges:**
1. ✅ All existing Prompt Tab tests pass
2. ✅ All existing Pipeline Tab tests pass
3. ✅ New tests cover added functionality
4. ✅ No regression in pack loading
5. ✅ Docs updated

---

## 10. Open Questions

### 10.1 Resolved

1. **Q:** Is Advanced Editor in V2?  
   **A:** ✅ YES - AdvancedPromptEditorV2 exists and is integrated

2. **Q:** Is Matrix Helper in V2?  
   **A:** ✅ YES - MatrixHelperDialog exists but uses wildcards, not slots

3. **Q:** How to integrate Prompt Tab with Pipeline Tab?  
   **A:** Dual-format export (JSON + TXT) + Edit button

---

### 10.2 For Resolution Before Implementation

1. **Q:** Should old MatrixHelperDialog be replaced or extended?  
   **A:** Extend - add "Insert Slot" mode alongside "Insert Wildcard" mode

2. **Q:** Should JSON packs be stored in `packs/` or separate `prompt_packs/` folder?  
   **A:** **packs/** folder (same location, different extension)

3. **Q:** Should TXT export happen automatically or manually?  
   **A:** **Automatically** on save (with "Export to Pipeline" button for explicit control)

4. **Q:** Should TXT be re-generated on every load, or only on save?  
   **A:** **Only on save** (TXT is generated artifact, not live-updated)

5. **Q:** Max slot count in Prompt Tab?  
   **A:** **10 slots UI, unlimited in model** (scroll if > 10)

---

## 11. Conclusion

**Original Analysis Status:** Partially invalid - overlooked existing Prompt Tab

**Revised Strategy:** Enhance existing Prompt Tab instead of reintegrating from archive

**Key Changes:**
- ❌ No need to reintegrate Advanced Editor (already there)
- ❌ No need to implement Matrix Helper (already there)
- ✅ Need to bridge JSON ↔ TXT formats
- ✅ Need to add slot-based matrix system
- ✅ Need to add negative prompt to main tab

**Revised Timeline:**
- PR-GUI-003-A: 1 week (negative prompt)
- PR-GUI-003-B: 2 weeks (matrix tab)
- PR-GUI-003-C: 1 week (dual export)
- PR-GUI-003-D: 1 week (bidirectional editing)
- PR-GUI-003-E: 1 week (testing)
- PR-GUI-003-F: 1 week (docs)
- **Total:** 7 weeks (vs original 6 weeks, but more realistic)

**Next Steps:**
1. Review this revised analysis
2. Approve/modify PR sequence
3. Create PR-GUI-003-A spec (negative prompt)
4. Begin implementation

---

**End of Revised Analysis Document**
