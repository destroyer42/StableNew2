# D-GUI-003: Prompt Pack Builder & Randomizer Integration Analysis

**Status:** Discovery Document  
**Date:** December 19, 2025  
**Version:** v2.6  
**Author:** Analysis by Copilot

---

## Executive Summary

This document analyzes the current state of three interrelated subsystems:
1. **Advanced Prompt Pack Builder** (GUI for creating/editing prompt packs)
2. **Randomization Matrix System** (variant generation via slot substitution)
3. **Prompt Pack → NJR Builder Pipeline** (job construction from packs)

**Key Findings:**
- ✅ **Strong Foundation**: Core randomizer engine (`PromptRandomizer`) is mature, tested, and deterministic
- ✅ **Functioning GUI**: `AdvancedPromptEditor` exists with validation, save/load, model detection
- ✅ **Pipeline Integration**: `PromptPackNormalizedJobBuilder` successfully routes packs through builder
- ⚠️ **Missing Bridge**: Advanced Prompt Builder NOT integrated into main GUI (archived in V1)
- ⚠️ **Disconnected UI**: `RandomizerPanelV2` exists but isn't wired to pack creation workflow
- ⚠️ **Unclear Matrix UX**: Pack JSON has `matrix.slots` but no GUI for editing them during pack authoring

**Recommendation:** Execute 6 focused PRs to integrate existing components rather than rebuild from scratch.

---

## 1. Current State Analysis

### 1.1 Advanced Prompt Pack Builder

**Location:** `src/gui/advanced_prompt_editor.py`

**Features Present:**
- ✅ Create/Edit/Save/Load prompt packs (TXT/TSV formats)
- ✅ Multi-line prompt editing with syntax highlighting
- ✅ Global negative prompt editor
- ✅ Validation engine (detects missing embeddings, LoRAs, syntax errors)
- ✅ Auto-fix for common issues
- ✅ Model/LoRA browser with double-click insertion
- ✅ Help documentation
- ✅ Clone/Delete pack operations

**Architecture:**
```python
class AdvancedPromptEditor:
    def __init__(self, parent_window, config_manager, on_packs_changed, on_validation)
    def open_editor(self, pack_path=None)  # Toplevel window
    def _save_pack()  # Validates before saving
    def _validate_pack()  # Returns results dict
    def _load_pack(pack_path: Path)
```

**Current State:** 
- ⚠️ **Archived in V1 GUI** (`archive/gui_v1/main_window.py` line 5115)
- ✅ Module itself is in active `src/gui/` (not archived)
- ❌ NOT wired into `MainWindowV2` or Pipeline Tab
- ❌ NOT accessible from sidebar or menu

**What's Missing:**
1. Integration point in V2 GUI (button/menu to launch editor)
2. Matrix slot editor UI within Advanced Prompt Editor
3. Base prompt field for matrix mode
4. Visual preview of matrix expansions

---

### 1.2 Randomization Matrix System

**Core Engine:** `src/utils/randomizer.py` - `PromptRandomizer` class

**Engine Capabilities:**
- ✅ Matrix slot substitution (`[[slot_name]]` tokens)
- ✅ Four modes: `fanout`, `sequential`, `rotate`, `random`
- ✅ Three prompt modes: `replace`, `append`, `prepend`
- ✅ Deterministic with seed support
- ✅ Wildcard expansion
- ✅ S/R (search/replace) rules
- ✅ Combo limit enforcement
- ✅ Tested extensively (`tests/utils/test_randomizer_matrix_base_prompt.py`)

**Config Schema:**
```json
{
  "randomization": {
    "enabled": true,
    "max_variants": 8,
    "matrix": {
      "enabled": true,
      "mode": "fanout",
      "prompt_mode": "replace",
      "limit": 8,
      "base_prompt": "a female [[job]] wearing [[clothes]]",
      "slots": [
        {"name": "job", "values": ["druid", "enchantress"]},
        {"name": "clothes", "values": ["armor", "robes"]}
      ]
    }
  }
}
```

**GUI Panel:** `src/gui/randomizer_panel_v2.py` - `RandomizerPanelV2` class

**Panel Features:**
- ✅ Enable randomization checkbox
- ✅ Max variants spinbox
- ✅ Seed mode dropdown
- ✅ Matrix dimension rows (add/delete/clone)
- ✅ Variant count display
- ✅ Risk band warnings
- ✅ `get_randomizer_config()` → dict for controller

**Current State:**
- ✅ Panel exists and is functional
- ⚠️ **Location uncertain** - appears in both `src/gui/` and `src/gui/panels_v2/` (re-export)
- ❌ Matrix rows support `model` and `hypernetwork` but NOT arbitrary custom slots
- ❌ No `base_prompt` field in GUI
- ❌ No `prompt_mode` dropdown
- ❌ No live preview of matrix expansion results

**V1 Archive Has More Features:**
- `archive/gui_v1/main_window.py` lines 2183-2290
- Matrix base prompt entry
- Slot name/values rows with scrollable canvas
- Prompt mode dropdown (replace/append/prepend)
- Legacy text editor toggle

---

### 1.3 Prompt Pack → NJR Builder Pipeline

**Pipeline Flow:**
```
PromptPack (TXT + JSON)
    ↓
PromptPackNormalizedJobBuilder
    ↓
_build_randomizer_plan()
    ↓
JobBuilderV2
    ↓
NormalizedJobRecord[]
```

**Key Files:**
- `src/pipeline/prompt_pack_job_builder.py` - `PromptPackNormalizedJobBuilder`
- `src/pipeline/job_builder_v2.py` - `JobBuilderV2`
- `src/pipeline/randomizer_v2.py` - `build_prompt_variants()` (lightweight)

**Integration Status:**
- ✅ Pack selection via `SidebarPanelV2` → pack listbox
- ✅ "Load Config" button loads pack into stage cards
- ✅ "Apply Config" button saves stage cards to pack
- ✅ "Add to Job" button creates NJR from pack via builder
- ✅ Preview panel shows NJR summaries

**What Works:**
```python
# From app_controller.py line 3800
def on_pipeline_add_packs_to_job(self, pack_ids: list[str]):
    for pack_id in pack_ids:
        pack = self._find_pack_by_id(pack_id)
        all_prompts = read_prompt_pack(pack.path)  # TXT file
        run_config = self._run_config_with_lora()
        
        for row_index, prompt_row in enumerate(all_prompts):
            entry = PackJobEntry(
                pack_id=pack_id,
                pack_name=pack.name,
                config_snapshot=run_config,
                prompt_text=prompt_row.get("positive", ""),
                negative_prompt_text=prompt_row.get("negative", ""),
                stage_flags={},
                randomizer_metadata=randomizer_metadata,
                pack_row_index=row_index,
            )
            entries.append(entry)
        
        self.app_state.add_packs_to_job_draft(entries)
```

**What's Missing:**
1. Matrix randomization NOT integrated in `_build_randomizer_plan()`
   - Current code: `RandomizationPlanV2(enabled=..., max_variants=...)` (lines 327-337)
   - Missing: Slot expansion, base_prompt handling, matrix metadata
2. Pack JSON `randomization.matrix` section NOT consumed
3. No GUI for editing matrix during pack creation
4. No preview of matrix expansion before "Add to Job"

---

## 2. Gap Analysis

### 2.1 What Makes Sense (Keep)

✅ **PromptRandomizer Engine**
- Mature, tested, deterministic
- Handles complex slot combinations
- Support for wildcards, S/R rules
- **Action**: Keep as-is, ensure it's called from builder

✅ **AdvancedPromptEditor Core**
- Validation engine is valuable
- Save/Load/Clone operations work
- Model detection prevents broken packs
- **Action**: Reintegrate into V2 GUI

✅ **Pack-Driven Architecture**
- Single source of truth (TXT + JSON)
- Clean separation: authoring → selection → execution
- **Action**: Continue this model

✅ **RandomizerPanelV2 Matrix Row System**
- Add/delete/clone rows
- Enabled checkboxes
- Value parsing (simple and hypernetwork)
- **Action**: Extend for arbitrary slots

---

### 2.2 What Doesn't Make Sense (Deprecate)

❌ **Randomizer_Spec_v2.5.md Vision**
- Proposes `RandomizerEngineV2` as new pure engine
- **Reality**: `PromptRandomizer` already IS that engine
- **Problem**: Spec treats matrix as config-level randomization (model/CFG/steps)
- **Conflict**: Matrix is actually PROMPT-level (slot substitution)
- **Action**: Reconcile spec with actual usage, clarify scope

❌ **Dual Randomization Systems**
- V2.5 spec: Config variant randomization (model choices, CFG ranges, batch sizes)
- Current system: Prompt matrix randomization (slot substitution)
- **Problem**: These are orthogonal! Both are called "randomization"
- **Action**: Rename clearly:
  - **Prompt Matrix** = slot-based prompt variants
  - **Config Sweep** = parameter grid search (future feature)

❌ **Legacy Text Editor Mode**
- V1 GUI had "toggle to raw text" for matrix slots
- Adds complexity, error-prone
- **Action**: Remove; GUI row editor is sufficient

❌ **Prompt Pack JSON Editing**
- Some docs suggest editing JSON by hand
- Dangerous (breaks validation, schema drift)
- **Action**: GUI-only editing, JSON is export format

---

### 2.3 What's Missing (Implement)

🔴 **Priority 1: Core Integration**

1. **Advanced Prompt Editor Launch Point**
   - Where: Menu in MainWindowV2, button in Sidebar
   - Why: No way to create/edit packs in V2

2. **Matrix Slot Editor in Advanced Prompt Editor**
   - Where: New tab in AdvancedPromptEditor notebook
   - Why: Packs have `matrix.slots` but no GUI to edit them

3. **Matrix Builder Wiring**
   - Where: `PromptPackNormalizedJobBuilder._build_randomizer_plan()`
   - Why: Matrix config exists in JSON but isn't used

🟡 **Priority 2: Usability**

4. **Matrix Preview in RandomizerPanelV2**
   - Show sample expanded prompts before "Add to Job"
   - Display combo count, risk warnings

5. **Base Prompt Field**
   - Add to RandomizerPanelV2
   - Add to Advanced Prompt Editor matrix tab
   - Explain replace/append/prepend modes

6. **Arbitrary Slot Support**
   - RandomizerPanelV2 currently hardcodes "model" and "hypernetwork"
   - Need generic slot rows that map to pack's `matrix.slots`

🟢 **Priority 3: Polish**

7. **Pack Validation on Load**
   - Check matrix slots match TXT placeholders
   - Warn about unused slots or undefined placeholders

8. **Global Negative Integration**
   - AdvancedPromptEditor has global negative tab
   - Ensure it's layered correctly in builder

9. **Preset Support for Matrix**
   - Save/load matrix configs as named presets
   - Apply preset to multiple packs

---

## 3. Architecture Reconciliation

### 3.1 Two Kinds of "Randomization"

**Current Confusion:**
- Randomizer_Spec_v2.5.md talks about model/CFG/step randomization
- Actual code does prompt matrix slot randomization
- Both called "randomizer"

**Proposed Clarity:**

```
┌─────────────────────────────────────────┐
│     PROMPT PACK AUTHORING PHASE         │
│                                         │
│  ┌───────────────────────────────┐     │
│  │  Matrix Slot Definitions      │     │
│  │  "job": [druid, knight]       │     │
│  │  "style": [fierce, serene]    │     │
│  │  base_prompt: "[[job]] [[style]]"│  │
│  └───────────────────────────────┘     │
│                                         │
│  Stored in pack JSON                   │
└─────────────────────────────────────────┘
                 ↓
┌─────────────────────────────────────────┐
│     PIPELINE EXECUTION PHASE            │
│                                         │
│  1. PROMPT MATRIX EXPANSION             │
│     PromptRandomizer.generate()         │
│     → "druid fierce"                    │
│     → "druid serene"                    │
│     → "knight fierce"                   │
│     → "knight serene"                   │
│                                         │
│  2. CONFIG SWEEP (Future)               │
│     RandomizerEngineV2 (v2.7+)          │
│     model: [A, B, C]                    │
│     CFG: [6, 8, 10]                     │
│     → 3 models × 3 CFG = 9 configs      │
│                                         │
│  3. CARTESIAN PRODUCT                   │
│     4 prompts × 9 configs = 36 NJRs     │
└─────────────────────────────────────────┘
```

**Proposed Terminology:**
- **Prompt Matrix** = slot-based prompt expansion (current)
- **Config Sweep** = parameter grid search (future v2.7)
- Both feed into JobBuilderV2 for Cartesian product

---

### 3.2 Where Matrix Lives

**Canonical Answer:**

| Concern | Location | Format |
|---------|----------|--------|
| **Authoring** | Advanced Prompt Editor | GUI form → JSON |
| **Storage** | `packs/*.json` | `randomization.matrix` section |
| **Selection** | Sidebar pack list + RandomizerPanelV2 | Display/override |
| **Execution** | PromptRandomizer engine | Slot substitution |
| **Builder** | PromptPackNormalizedJobBuilder | Metadata extraction |

**Key Insight:**
Matrix is a **pack property**, not a runtime setting.
- Author defines slots once during pack creation
- Pipeline applies slots every time pack is used
- RandomizerPanelV2 can override mode/limit, but not slots themselves

---

## 4. Proposed PR Series

### PR-GUI-003-A: Reintegrate Advanced Prompt Editor

**Goal:** Make Advanced Prompt Editor accessible in V2 GUI

**Scope:**
1. Add menu item: `Tools → Advanced Prompt Editor`
2. Add button in SidebarPanelV2: "Edit Pack" (launches editor for selected pack)
3. Wire callbacks:
   - `on_packs_changed` → refresh pack list
   - `on_validation` → show validation results in status bar
4. Test: Create pack, edit pack, save, verify appears in pack list

**Files:**
- `src/gui/main_window_v2.py` - add menu item
- `src/gui/sidebar_panel_v2.py` - add "Edit Pack" button
- `src/controller/app_controller.py` - add `on_advanced_editor_requested(pack_id)`
- `tests/gui_v2/test_advanced_editor_integration.py` - new test file

**Acceptance:**
- ✅ Menu item opens editor (blank pack)
- ✅ "Edit Pack" button opens editor with selected pack loaded
- ✅ Saving pack refreshes sidebar list
- ✅ Validation errors show in status bar

---

### PR-GUI-003-B: Add Matrix Tab to Advanced Prompt Editor

**Goal:** Allow editing matrix slots during pack authoring

**Scope:**
1. Add "Matrix" tab to AdvancedPromptEditor notebook (after Prompts, Global Negative, Validation tabs)
2. UI elements:
   - Enabled checkbox
   - Base prompt entry (multiline)
   - Prompt mode dropdown (replace/append/prepend)
   - Mode dropdown (fanout/sequential/rotate/random)
   - Limit spinbox
   - Scrollable slot rows:
     - Slot name entry
     - Values entry (comma-separated)
     - Add/Delete buttons
3. Load/Save:
   - `_load_matrix_from_json()` - populate from pack JSON
   - `_save_matrix_to_json()` - write to `randomization.matrix`
4. Validation:
   - Check slot names match `[[...]]` in prompts
   - Warn about unused slots
   - Warn about undefined placeholders

**Files:**
- `src/gui/advanced_prompt_editor.py` - add `_build_matrix_tab()`
- `src/gui/advanced_prompt_editor.py` - extend load/save methods
- `tests/gui_v2/test_advanced_editor_matrix.py` - matrix tab tests

**Acceptance:**
- ✅ Matrix tab displays with controls
- ✅ Load existing pack populates matrix fields
- ✅ Save writes matrix to JSON
- ✅ Validation detects slot/placeholder mismatches
- ✅ Add/Delete slot rows works

---

### PR-GUI-003-C: Wire Matrix to NJR Builder

**Goal:** Make matrix actually generate variants during job building

**Scope:**
1. Extend `PromptPackNormalizedJobBuilder._build_randomizer_plan()`:
   ```python
   def _build_randomizer_plan(self, entry: PackJobEntry, merged_config: dict):
       matrix_config = merged_config.get("randomization", {}).get("matrix", {})
       
       # Build PromptRandomizer config
       randomizer_config = {
           "enabled": bool(matrix_config.get("enabled")),
           "matrix": {
               "enabled": bool(matrix_config.get("enabled")),
               "mode": matrix_config.get("mode", "fanout"),
               "prompt_mode": matrix_config.get("prompt_mode", "replace"),
               "limit": int(matrix_config.get("limit", 8)),
               "base_prompt": matrix_config.get("base_prompt", ""),
               "slots": matrix_config.get("slots", []),
           }
       }
       
       # Use PromptRandomizer to expand
       randomizer = PromptRandomizer(randomizer_config)
       variants = randomizer.generate(entry.prompt_text)
       
       # Convert to RandomizationPlanV2 for JobBuilderV2
       return RandomizationPlanV2(
           enabled=True,
           max_variants=len(variants),
           variant_texts=[v.text for v in variants],
           variant_labels=[v.label for v in variants],
       )
   ```

2. Extend `RandomizationPlanV2` to carry prompt variants:
   ```python
   @dataclass
   class RandomizationPlanV2:
       enabled: bool = False
       max_variants: int = 1
       variant_texts: list[str] = field(default_factory=list)  # NEW
       variant_labels: list[str] = field(default_factory=list)  # NEW
       # ... existing fields
   ```

3. Update `JobBuilderV2.build_jobs()` to use variant_texts:
   ```python
   if plan.variant_texts:
       for text, label in zip(plan.variant_texts, plan.variant_labels):
           # Build NJR with this prompt variant
   ```

**Files:**
- `src/pipeline/prompt_pack_job_builder.py` - extend `_build_randomizer_plan()`
- `src/pipeline/randomization_plan_v2.py` - extend dataclass
- `src/pipeline/job_builder_v2.py` - use variant_texts
- `tests/pipeline/test_matrix_njr_integration.py` - E2E test

**Acceptance:**
- ✅ Pack with matrix generates multiple NJRs (one per combo)
- ✅ NJR prompt field contains expanded text
- ✅ NJR metadata includes slot values
- ✅ Preview panel shows all variants

---

### PR-GUI-003-D: Enhance RandomizerPanelV2

**Goal:** Make RandomizerPanelV2 display/override pack matrix settings

**Scope:**
1. Add base_prompt field to RandomizerPanelV2
2. Add prompt_mode dropdown (replace/append/prepend)
3. Make matrix rows generic (not hardcoded model/hypernetwork)
4. Load matrix slots from selected pack:
   ```python
   def load_matrix_from_pack(self, pack_config: dict):
       matrix = pack_config.get("randomization", {}).get("matrix", {})
       self.base_prompt_var.set(matrix.get("base_prompt", ""))
       self.prompt_mode_var.set(matrix.get("prompt_mode", "replace"))
       
       slots = matrix.get("slots", [])
       self._rows.clear()
       for slot in slots:
           self._add_matrix_row(
               label=slot["name"],
               values=", ".join(slot["values"]),
               enabled=True,
           )
   ```
5. Add preview button:
   - Show sample expanded prompts
   - Display total combo count
   - Risk warning if > 128 combos

**Files:**
- `src/gui/randomizer_panel_v2.py` - add fields, load method
- `src/gui/sidebar_panel_v2.py` - call `load_matrix_from_pack()` on pack selection
- `tests/gui_v2/test_randomizer_panel_matrix_load.py`

**Acceptance:**
- ✅ Selecting pack loads matrix into RandomizerPanelV2
- ✅ Base prompt displays
- ✅ Slot rows populate
- ✅ Preview button shows expanded prompts
- ✅ Risk warning appears for large combos

---

### PR-GUI-003-E: Matrix Validation & Testing

**Goal:** Ensure matrix system is robust and predictable

**Scope:**
1. Pack-level validation:
   - Slot names must be valid identifiers
   - Slot values must be non-empty
   - Placeholders in TXT must have matching slots in JSON
   - Slots in JSON must be used in TXT
2. Runtime validation:
   - Combo limit enforcement
   - Memory estimation for large matrices
   - Deterministic ordering with seed
3. Test matrix:
   ```
   | Slots | Mode | Limit | Expected Combos | Test Name |
   |-------|------|-------|-----------------|-----------|
   | 2×2   | fanout | 0 | 4 | test_matrix_2x2_fanout |
   | 3×3×3 | fanout | 8 | 8 | test_matrix_limited |
   | 2×2   | sequential | 0 | 4 (rotated) | test_matrix_sequential |
   | 2×2   | random | 0 | 4 (shuffled) | test_matrix_random |
   ```

**Files:**
- `src/utils/validators/pack_validator.py` - new validator module
- `tests/utils/test_matrix_validation.py` - validation tests
- `tests/pipeline/test_matrix_determinism.py` - seed tests
- `tests/e2e/test_matrix_golden_path.py` - full pack → NJR → execution

**Acceptance:**
- ✅ All validation rules enforced
- ✅ Tests pass for all modes × limits
- ✅ Deterministic output with same seed
- ✅ Golden path test: pack with matrix → 4 images generated

---

### PR-GUI-003-F: Documentation & Cleanup

**Goal:** Update docs to reflect integrated system

**Scope:**
1. Update `PROMPT_PACK_LIFECYCLE_v2.6.md`:
   - Add "Matrix Authoring" section
   - Clarify prompt matrix vs config sweep
2. Update `Randomizer_Spec_v2.5.md`:
   - Reconcile with actual PromptRandomizer usage
   - Rename config-level features to "Config Sweep (v2.7)"
3. Create `Matrix_System_User_Guide.md`:
   - How to define slots
   - How to use replace/append/prepend modes
   - Examples with screenshots
4. Archive conflicting specs:
   - Move V1 randomizer docs to `docs/older/`
   - Add deprecation notices

**Files:**
- `docs/PROMPT_PACK_LIFECYCLE_v2.6.md` - update
- `docs/Randomizer_Spec_v2.5.md` - reconcile
- `docs/Matrix_System_User_Guide.md` - new guide
- `docs/older/` - move deprecated specs

**Acceptance:**
- ✅ User can follow guide to create matrix pack
- ✅ No conflicting specs remain
- ✅ Terminology is consistent across docs

---

## 5. Risk Assessment

### 5.1 Technical Risks

🔴 **High Risk:**
- **Cartesian explosion**: 3 slots × 10 values each = 1000 combos
  - **Mitigation**: Hard limit at 512, UI warnings at 128
- **Memory usage**: Large matrices generate many NJRs
  - **Mitigation**: Builder creates NJRs lazily, not all in memory

🟡 **Medium Risk:**
- **Pack format migration**: Existing packs may have invalid matrix sections
  - **Mitigation**: Validation on load, auto-fix when possible
- **GUI complexity**: Matrix tab adds many controls
  - **Mitigation**: Progressive disclosure (collapse advanced options)

🟢 **Low Risk:**
- **PromptRandomizer bugs**: Well-tested, mature code
- **Builder integration**: Clean insertion point already exists

---

### 5.2 UX Risks

🔴 **High Risk:**
- **User confusion**: What's the difference between matrix and config sweep?
  - **Mitigation**: Clear naming, separate tabs, help tooltips
- **Accidental large jobs**: User defines 5×5×5×5 matrix = 625 images
  - **Mitigation**: Preview shows count BEFORE "Add to Job"

🟡 **Medium Risk:**
- **Hidden complexity**: Matrix powerful but intimidating
  - **Mitigation**: Simple mode (2 slots max) vs advanced mode
- **Lost work**: Editing matrix in RandomizerPanelV2 doesn't save to pack
  - **Mitigation**: "Override" vs "Save to Pack" buttons

---

## 6. Success Metrics

### 6.1 Functional Goals

✅ **By PR-GUI-003-C:**
- Pack with matrix generates N NJRs (N = combo count)
- Preview panel shows all variant prompts

✅ **By PR-GUI-003-D:**
- User can create pack with matrix using GUI only (no JSON editing)
- RandomizerPanelV2 displays pack matrix settings

✅ **By PR-GUI-003-F:**
- Golden path test: Create pack → define 2×2 matrix → add to job → execute → 4 images
- Zero conflicting docs

---

### 6.2 Quality Gates

**Before each PR merges:**
1. ✅ All existing tests pass
2. ✅ New tests cover added functionality
3. ✅ No regression in pack selection/loading
4. ✅ No regression in NJR builder determinism
5. ✅ Docs updated to match implementation

---

## 7. Alternative Approaches Considered

### 7.1 Rebuild from Scratch

**Pros:** Clean slate, perfect architecture  
**Cons:** 
- Throws away working PromptRandomizer engine
- Duplicates AdvancedPromptEditor validation logic
- 6+ months vs 6 weeks

**Verdict:** ❌ Rejected

---

### 7.2 Embed Matrix in Pack TXT

**Example:**
```
# Matrix: job=druid,knight style=fierce,serene
# Base: [[job]] [[style]] portrait
masterpiece, detailed artwork
```

**Pros:** Single file, no JSON  
**Cons:**
- Fragile parsing
- No validation
- Hard to edit programmatically
- Breaks existing pack format

**Verdict:** ❌ Rejected

---

### 7.3 Runtime-Only Matrix

**Idea:** Define matrix in RandomizerPanelV2, not in pack

**Pros:** Simpler authoring  
**Cons:**
- Matrix not reusable
- Can't share pack with its matrix
- Violates "pack = complete prompt definition" principle

**Verdict:** ❌ Rejected

---

## 8. Dependencies & Sequencing

### 8.1 PR Dependencies

```
PR-GUI-003-A (Editor Integration)
    ↓
PR-GUI-003-B (Matrix Tab) ← Can start in parallel
    ↓
PR-GUI-003-C (Builder Wiring) ← BLOCKS execution
    ↓
PR-GUI-003-D (Panel Enhancement) ← Can start after A
    ↓
PR-GUI-003-E (Validation) ← Needs B and C
    ↓
PR-GUI-003-F (Docs) ← Needs all others
```

**Critical Path:** A → B → C → E → F  
**Parallelizable:** A → D (can develop simultaneously)

---

### 8.2 External Dependencies

**None.** All required components exist:
- ✅ PromptRandomizer engine
- ✅ AdvancedPromptEditor GUI
- ✅ PromptPackNormalizedJobBuilder
- ✅ RandomizerPanelV2

**Only missing:** Wiring between components.

---

## 9. Migration Path

### 9.1 Existing Packs

**Scenario 1:** Pack has no matrix section  
→ No change, works as before

**Scenario 2:** Pack has invalid matrix section  
→ Validation on load, show errors, offer auto-fix

**Scenario 3:** Pack has V1-style matrix (raw_text)  
→ Parse into slots, save as V2 format

---

### 9.2 User Education

**Required Materials:**
1. **Quick Start Guide**: "Adding Matrix to Your Pack"
2. **Video Tutorial**: Screen recording of matrix creation
3. **Example Packs**: Ship 2-3 packs with matrix pre-configured

**Launch Strategy:**
1. PR-GUI-003-A/B: Soft launch (editor accessible but matrix hidden)
2. PR-GUI-003-C/D: Beta release (matrix functional, announce in changelog)
3. PR-GUI-003-F: Full release (docs complete, announce in README)

---

## 10. Open Questions

### 10.1 For Resolution Before Implementation

1. **Q:** Should RandomizerPanelV2 override pack matrix, or just display it?  
   **A:** Display + allow mode/limit override, but not slot editing (slots are pack property)

2. **Q:** How to handle global negative with matrix?  
   **A:** Global negative appends AFTER matrix expansion (separate layer)

3. **Q:** Should matrix support wildcards in slot values?  
   **A:** No (v2.6). Wildcards are separate feature. Maybe v2.7.

4. **Q:** Max combo limit: 128? 512? 1024?  
   **A:** 512 hard limit, 128 warning threshold, configurable in settings

5. **Q:** Should base_prompt support `[[slot]]` syntax in AdvancedPromptEditor?  
   **A:** Yes, that's the point. Preview shows expansion.

---

### 10.2 Deferred to Future PRs

1. **Weighted slot values**: `{"name": "job", "values": ["druid:2", "knight:1"]}`
2. **Slot dependencies**: If job=druid → clothes=robes (conditional combos)
3. **Config sweep integration**: Combine matrix with model/CFG grid
4. **Pack inheritance**: Base pack + override matrix
5. **Batch matrix application**: Apply same matrix to multiple packs

---

## 11. Conclusion

**Current State:** Strong foundation, missing integration

**Proposed Solution:** 6 focused PRs over 6 weeks

**Expected Outcome:**
- Users can create matrix-enabled packs without JSON editing
- Pack matrix automatically generates variant NJRs
- Preview shows all combos before execution
- Zero breaking changes to existing workflow

**Next Steps:**
1. Review this document with team
2. Approve/modify PR sequence
3. Create PR-GUI-003-A spec
4. Begin implementation

---

**End of Analysis Document**
