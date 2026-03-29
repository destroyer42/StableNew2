# PR-GUI-004: LoRA & Embedding Pickers with Keyword Detection

**Status**: 📋 PROPOSAL  
**Priority**: HIGH  
**Complexity**: MEDIUM  
**Dependencies**: PR-GUI-003-C (Matrix Runtime Integration)

## Executive Summary

Enhance Prompt Tab with dedicated LoRA and embedding management UI:
- **LoRA Picker**: Browse installed LoRAs, adjust strength, auto-detect keywords, insert with syntax
- **Embedding Picker**: Browse installed embeddings, insert into positive/negative prompts
- **Structured Editing**: Separate fields for prompt text, LoRAs, and embeddings (cleaner UX)
- **Smart Load/Save**: Parse existing prompts into fields, reassemble on save

This bridges the gap between GUI editing and pipeline syntax requirements.

## Problem Statement

### Current Pain Points

**1. Manual Syntax Management**
```
User must type: <lora:add-detail-xl:0.65>
- Error-prone (typos, wrong syntax)
- Must remember LoRA names
- No visibility into available LoRAs
```

**2. No Keyword Discovery**
Many LoRAs include trigger keywords in their metadata/files, but users must:
- Open external file browser
- Read `.txt` or `.civitai.info` files manually
- Copy keywords into prompt
- Context switch away from GUI

**3. Mixed Content in Single Field**
Current prompt field contains:
```
<embedding:positive_embed>
(masterpiece, best quality) [[job]] in [[environment]]
<lora:add-detail-xl:0.65>
neg: <embedding:negative_hands>
```
- Hard to edit individual components
- Difficult to adjust LoRA strengths
- No visual separation

**4. Non-Functional Load Button**
Current "Load" button in slots doesn't parse prompts from packs into editable components.

## Proposed Solution

### Architecture Overview

```
┌─────────────────────────────────────────────────────┐
│              Prompt Tab (Enhanced)                  │
├─────────────────────────────────────────────────────┤
│  Slot Selector: [ Slot 1 ▼] [Load] [Save] [Clear] │
├─────────────────────────────────────────────────────┤
│ ┌─ Positive Prompt ─────────────────────────────┐  │
│ │ (masterpiece, best quality) [[job]]           │  │
│ │ in [[environment]]                            │  │
│ │                                                │  │
│ └───────────────────────────────────────────────┘  │
│ ┌─ Negative Prompt ─────────────────────────────┐  │
│ │ bad quality, blurry, deformed                 │  │
│ └───────────────────────────────────────────────┘  │
│ ┌─ Embeddings ──────────────────────────────────┐  │
│ │ Positive: [positive_embed▼] [+] [-]          │  │
│ │   • positive_embed                            │  │
│ │   • realism_positives_v1                      │  │
│ │ Negative: [negative_hands▼] [+] [-]          │  │
│ │   • negative_hands                            │  │
│ │   • ac_neg1                                   │  │
│ └───────────────────────────────────────────────┘  │
│ ┌─ LoRAs ───────────────────────────────────────┐  │
│ │ [Select LoRA▼] [Add]                         │  │
│ │                                                │  │
│ │ ┌───────────────────────────────────────────┐ │  │
│ │ │ add-detail-xl                             │ │  │
│ │ │ Strength: [━━━●━━━] 0.65  [Keywords...]  │ │  │
│ │ │                                    [X]    │ │  │
│ │ ├───────────────────────────────────────────┤ │  │
│ │ │ CinematicStyle_v1                         │ │  │
│ │ │ Strength: [━━━━●━━] 0.55  [Keywords...]  │ │  │
│ │ │                                    [X]    │ │  │
│ │ └───────────────────────────────────────────┘ │  │
│ └───────────────────────────────────────────────┘  │
│ ┌─ Matrix ──────────────────────────────────────┐  │
│ │ (existing Matrix Tab content)                 │  │
│ └───────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────┘
```

### Component Breakdown

#### 1. LoRA Management Panel

**UI Elements:**
- **Dropdown**: Lists all installed LoRAs (scanned from WebUI folders)
- **Add Button**: Adds selected LoRA to list
- **LoRA Entry Cards**:
  - LoRA name (display)
  - Strength slider (0.0 to 1.5, default 0.8)
  - "Keywords..." button → Opens keyword finder dialog
  - Delete button (X)

**Keyword Finder Dialog:**
```
┌─ LoRA Keywords: add-detail-xl ────────────────┐
│                                                │
│ Detected Keywords:                             │
│ ┌────────────────────────────────────────────┐ │
│ │ • masterpiece                              │ │
│ │ • best quality                             │ │
│ │ • highly detailed                          │ │
│ │ • photorealistic                           │ │
│ └────────────────────────────────────────────┘ │
│                                                │
│ Source: add-detail-xl.civitai.info             │
│                                                │
│ [Copy to Prompt] [Close]                       │
└────────────────────────────────────────────────┘
```

**Keyword Detection Logic:**
1. Check for `.civitai.info` file (JSON with `trainedWords`)
2. Check for `.txt` file with same name
3. Parse README or description files in LoRA folder
4. Fallback: "No keywords detected"

#### 2. Embedding Management Panel

**UI Elements:**
- **Positive Embeddings**:
  - Dropdown listing all embeddings
  - [+] button to add
  - List showing added embeddings
  - [-] button to remove
- **Negative Embeddings**:
  - Same structure as positive

**Detection Logic:**
Uses existing `WebUIResourceService.list_embeddings()` to scan:
- `embeddings/` folder
- `models/embeddings/` folder
- Filters: `.pt`, `.bin`, `.ckpt`, `.safetensors`, `.embedding`

#### 3. Smart Load/Save Integration

**Load Flow (Fix Current Button):**
```python
# Current pack TXT format:
<embedding:positive_embed>
(masterpiece, best quality) portrait
<lora:add-detail-xl:0.65>
neg: <embedding:negative_hands>
neg: bad quality

# Parse into:
positive_embeddings = ["positive_embed"]
positive_text = "(masterpiece, best quality) portrait"
loras = [("add-detail-xl", 0.65)]
negative_embeddings = ["negative_hands"]
negative_text = "bad quality"
```

**Save Flow:**
```python
# Reassemble from fields:
lines = []
if positive_embeddings:
    lines.append(" ".join(f"<embedding:{e}>" for e in positive_embeddings))
lines.append(positive_text)
if loras:
    lines.append(" ".join(f"<lora:{name}:{weight}>" for name, weight in loras))
if negative_embeddings:
    lines.append(f"neg: {' '.join(f'<embedding:{e}>' for e in negative_embeddings)}")
if negative_text:
    lines.append(f"neg: {negative_text}")

slot.text = "\n".join(lines)
```

## Technical Design

### New Files

**1. `src/utils/lora_keyword_detector.py`**
```python
@dataclass
class LoRAMetadata:
    name: str
    path: Path
    keywords: list[str]
    source: str  # "civitai", "txt", "readme", "none"

def detect_lora_keywords(lora_name: str, webui_root: Path) -> LoRAMetadata:
    """Detect keywords from LoRA metadata files."""
    # 1. Try .civitai.info (JSON)
    # 2. Try .txt file
    # 3. Try README in folder
    # 4. Return empty list
```

**2. `src/gui/widgets/lora_picker_panel.py`**
```python
class LoRAPickerPanel(ttk.Frame):
    """Panel for managing LoRAs with strength and keywords."""
    
    def __init__(self, parent, on_change_callback):
        # Dropdown for LoRA selection
        # List of LoRA entry cards
        # Add/remove buttons
    
    def get_loras(self) -> list[tuple[str, float]]:
        """Return list of (name, strength) tuples."""
    
    def set_loras(self, loras: list[tuple[str, float]]):
        """Load LoRAs into UI."""
    
    def _show_keywords_dialog(self, lora_name: str):
        """Open keyword finder dialog."""
```

**3. `src/gui/widgets/embedding_picker_panel.py`**
```python
class EmbeddingPickerPanel(ttk.Frame):
    """Panel for managing positive/negative embeddings."""
    
    def __init__(self, parent, on_change_callback):
        # Positive embeddings section
        # Negative embeddings section
        # Add/remove buttons
    
    def get_positive_embeddings(self) -> list[str]:
    def get_negative_embeddings(self) -> list[str]:
    def set_positive_embeddings(self, embeddings: list[str]):
    def set_negative_embeddings(self, embeddings: list[str]):
```

**4. `src/gui/dialogs/lora_keyword_dialog.py`**
```python
class LoRAKeywordDialog(tk.Toplevel):
    """Modal dialog showing LoRA keywords with copy functionality."""
    
    def __init__(self, parent, lora_metadata: LoRAMetadata):
        # Display keywords
        # Copy to prompt button
        # Source attribution
```

### Modified Files

**1. `src/gui/models/prompt_pack_model.py`**

Add structured LoRA/embedding fields to PromptSlot:

```python
@dataclass
class PromptSlot:
    index: int
    text: str = ""  # Pure prompt text (no LoRA/embedding syntax)
    negative: str = ""  # Pure negative text
    positive_embeddings: list[str] = field(default_factory=list)
    negative_embeddings: list[str] = field(default_factory=list)
    loras: list[tuple[str, float]] = field(default_factory=list)
```

**Backward Compatibility:**
- Load: Parse old format into new fields
- Save: Option to save as "structured JSON" or "legacy TXT"
- Export TXT: Always assembles into pipeline format

**2. `src/gui/views/prompt_tab_frame_v2.py`**

Refactor layout to include new panels:

```python
def _build_ui(self):
    # Existing slot selector
    
    # Replace single notebook with:
    # - Positive prompt editor
    # - Negative prompt editor
    # - EmbeddingPickerPanel (NEW)
    # - LoRAPickerPanel (NEW)
    # - MatrixTabPanel (existing)
```

**3. `src/gui/prompt_workspace_state.py`**

Add methods for structured editing:

```python
def get_current_loras(self) -> list[tuple[str, float]]:
def set_slot_loras(self, slot_index: int, loras: list[tuple[str, float]]):
def get_current_positive_embeddings(self) -> list[str]:
def set_slot_positive_embeddings(self, slot_index: int, embeddings: list[str]):
# ... similar for negative
```

**4. Fix Load Button**

Update `_on_load_click()` in `prompt_tab_frame_v2.py`:

```python
def _on_load_pack(self):
    # 1. Open file picker → select pack TXT
    # 2. Parse using prompt_pack_parser
    # 3. Extract embeddings, loras, text using regex
    # 4. Populate UI fields via workspace_state
```

**5. `src/api/webui_resources.py`**

Extend to scan LoRAs with metadata:

```python
def list_loras_with_metadata(self) -> list[LoRAMetadata]:
    """Scan LoRA folders and detect keywords."""
```

### Data Flow

```
┌─────────────┐
│  User Edits │
│  LoRA Panel │
└──────┬──────┘
       │ on_change_callback
       ▼
┌──────────────────┐
│ PromptWorkspace  │
│ State            │
└──────┬───────────┘
       │ set_slot_loras()
       ▼
┌──────────────────┐
│ PromptPackModel  │
│ .slots[i].loras  │
└──────┬───────────┘
       │ save_to_file()
       ▼
┌──────────────────┐
│ pack.json        │
│ {                │
│   "slots": [{    │
│     "text": "...",│
│     "loras": [...│
│   }]             │
│ }                │
└──────┬───────────┘
       │ _export_txt()
       ▼
┌──────────────────┐
│ pack.txt         │
│ <lora:name:0.8>  │
│ (prompt text)    │
└──────────────────┘
       │
       ▼ Pipeline Tab loads
┌──────────────────┐
│ prompt_pack_     │
│ parser.py        │
│ → PackRow        │
└──────────────────┘
```

## Implementation Plan

### Phase 1: Infrastructure (PR-GUI-004-A)

**Files:**
- `src/utils/lora_keyword_detector.py` (NEW)
- `tests/utils/test_lora_keyword_detector.py` (NEW)

**Deliverables:**
- LoRA keyword detection from `.civitai.info`, `.txt`, README
- Caching for performance
- 10+ tests covering all sources

**Estimated Effort:** 1-2 days

### Phase 2: UI Components (PR-GUI-004-B)

**Files:**
- `src/gui/widgets/lora_picker_panel.py` (NEW)
- `src/gui/widgets/embedding_picker_panel.py` (NEW)
- `src/gui/dialogs/lora_keyword_dialog.py` (NEW)
- `tests/gui_v2/test_lora_picker_panel.py` (NEW)
- `tests/gui_v2/test_embedding_picker_panel.py` (NEW)

**Deliverables:**
- LoRA picker with dropdown, strength slider, keywords button
- Embedding picker with add/remove
- Keyword dialog with copy functionality
- 15+ tests

**Estimated Effort:** 2-3 days

### Phase 3: Data Model Extension (PR-GUI-004-C)

**Files:**
- `src/gui/models/prompt_pack_model.py` (MODIFY)
- `src/gui/prompt_workspace_state.py` (MODIFY)
- `tests/gui_v2/test_prompt_pack_model_loras.py` (NEW)
- `tests/gui_v2/test_prompt_workspace_state_loras.py` (NEW)

**Deliverables:**
- Extend `PromptSlot` with structured fields
- Backward-compatible load/save
- Export to TXT with correct syntax
- 20+ tests covering roundtrip, backward compat

**Estimated Effort:** 2 days

### Phase 4: Integration (PR-GUI-004-D)

**Files:**
- `src/gui/views/prompt_tab_frame_v2.py` (MODIFY)
- `tests/gui_v2/test_prompt_tab_frame_loras.py` (NEW)

**Deliverables:**
- Integrate LoRA/embedding panels into Prompt Tab layout
- Wire callbacks to workspace state
- Fix Load button to parse prompts
- Update Save to reassemble
- End-to-end test

**Estimated Effort:** 2-3 days

### Phase 5: Resource Discovery (PR-GUI-004-E)

**Files:**
- `src/api/webui_resources.py` (MODIFY)
- `tests/api/test_webui_resources_loras.py` (NEW)

**Deliverables:**
- Scan LoRA folders with metadata
- Cache for performance
- Refresh button in UI
- 10+ tests

**Estimated Effort:** 1-2 days

## Testing Strategy

### Unit Tests

**Keyword Detection:**
```python
def test_detect_keywords_from_civitai_info()
def test_detect_keywords_from_txt_file()
def test_detect_keywords_from_readme()
def test_detect_keywords_no_source_found()
def test_keyword_caching()
```

**UI Components:**
```python
def test_lora_picker_add_remove()
def test_lora_picker_strength_adjustment()
def test_embedding_picker_positive_negative()
def test_keyword_dialog_copy_to_clipboard()
```

**Data Model:**
```python
def test_prompt_slot_with_loras()
def test_save_load_roundtrip_loras()
def test_backward_compat_load_old_format()
def test_export_txt_with_lora_syntax()
```

### Integration Tests

```python
def test_e2e_add_lora_save_load()
def test_e2e_keyword_finder_workflow()
def test_e2e_load_pack_parse_into_fields()
```

## Architectural Alignment

### v2.6 Compliance

✅ **Separation of Concerns:**
- Prompt Tab: Define LoRAs/embeddings
- Pipeline Tab: Adjust runtime strengths (existing)
- No mixing of concerns

✅ **Data Flow:**
```
GUI → PromptPackModel → JSON → TXT → Parser → PackRow → Pipeline
```

✅ **No Tech Debt:**
- Extends existing models (no replacement)
- Backward compatible
- Reuses existing parsers

### Future-Proofing

**LoRA Learning System Integration:**
Current design enables future PR:
```python
# PR-GUI-004-D sets up structure
# Future PR adds:
def sweep_lora_strength(lora_name: str, min: float, max: float, step: float):
    """Generate jobs with varying LoRA strength."""
    # Uses existing lora field structure
```

**Pipeline Tab Runtime Controls:**
Existing `lora_strengths` in PipelineConfigPanelV2 can read from:
```python
# Prompt Tab defines which LoRAs
prompt_metadata.loras → [("add-detail-xl", 0.65), ...]

# Pipeline Tab allows runtime override
pipeline_config.lora_strengths → {"add-detail-xl": 0.8}
```

## User Stories

### Story 1: LoRA Discovery

**As a** prompt engineer  
**I want to** browse available LoRAs in a dropdown  
**So that** I don't have to remember names or check file browser

**Acceptance:**
- Dropdown lists all LoRAs from WebUI folders
- Clicking "Add" inserts LoRA into list with default strength
- LoRA appears in saved pack TXT with correct syntax

### Story 2: Keyword Finding

**As a** prompt engineer  
**I want to** discover LoRA trigger keywords automatically  
**So that** I can use LoRAs effectively without reading external files

**Acceptance:**
- "Keywords..." button opens dialog
- Dialog shows keywords from `.civitai.info` or `.txt`
- "Copy to Prompt" button adds keywords to prompt text
- Dialog shows source attribution

### Story 3: Structured Editing

**As a** prompt engineer  
**I want** LoRAs and embeddings in separate UI sections  
**So that** editing is cleaner and less error-prone

**Acceptance:**
- Prompt text field contains ONLY text (no LoRA/embedding syntax)
- LoRA panel shows all LoRAs with sliders
- Embedding panel shows positive/negative lists
- Save assembles everything into correct TXT format

### Story 4: Load Existing Packs

**As a** user  
**I want** to load existing packs and see LoRAs/embeddings parsed into fields  
**So that** I can edit old packs with new UI

**Acceptance:**
- Load button opens file picker
- Old TXT format is parsed into new fields
- LoRAs appear in LoRA panel with correct strengths
- Embeddings appear in embedding panel
- Roundtrip (load → save) produces identical output

## Known Limitations

**1. LoRA Keyword Coverage**

Not all LoRAs have metadata files. Fallbacks:
- User can manually add keywords to prompt
- Future: Community database integration

**2. Strength Range**

Default range: 0.0 to 1.5  
Some LoRAs work outside this range → allow manual override in text

**3. Multi-File LoRAs**

Some LoRAs are folders with multiple files → need folder detection

## Success Metrics

- **Adoption:** 80% of users use LoRA picker instead of typing syntax
- **Errors:** 90% reduction in LoRA syntax errors
- **Efficiency:** 50% faster LoRA addition workflow
- **Satisfaction:** User feedback: "Much easier to manage LoRAs"

## Rollout Plan

1. **Phase 1-2:** Core infrastructure + UI components (no user-facing changes)
2. **Phase 3-4:** Enable in Prompt Tab behind feature flag
3. **Phase 5:** Public release with documentation
4. **Post-Release:** Monitor feedback, iterate on UX

## Risks & Mitigations

| Risk | Impact | Mitigation |
|------|--------|------------|
| WebUI folder structure varies | HIGH | Support multiple folder layouts, env config |
| Keyword detection unreliable | MEDIUM | Clear "No keywords" message, manual entry option |
| Backward compat breaks | HIGH | Extensive tests, gradual rollout |
| Performance (scanning folders) | MEDIUM | Caching, async scan on startup |

## Documentation Updates

- `docs/USER_GUIDE_v2.6.md` - LoRA/embedding picker tutorial
- `docs/PROMPT_PACK_FORMAT_v2.6.md` - Structured vs legacy format
- `docs/ARCHITECTURE_v2.6.md` - New UI components
- `CHANGELOG.md` - Feature announcement

## Conclusion

PR-GUI-004 represents a significant UX improvement for prompt management:

✅ **Reduces Friction:** No more manual LoRA syntax typing  
✅ **Improves Discoverability:** Keywords auto-detected  
✅ **Enhances Clarity:** Structured editing with separate fields  
✅ **Maintains Compatibility:** Works with existing packs and pipeline  
✅ **Enables Future Work:** Sets up LoRA learning system

**Total Estimated Effort:** 8-12 days  
**Recommended Approach:** Implement in phases (PR-GUI-004-A through PR-GUI-004-E)  
**Next Step:** Review proposal, approve phase order, begin PR-GUI-004-A
