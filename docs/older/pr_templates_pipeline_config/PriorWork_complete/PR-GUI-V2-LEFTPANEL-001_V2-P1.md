
# PR-GUI-V2-LEFTPANEL-001 — Port Packs/Presets into V2 Left Panel (Phase 1)

**Snapshot Baseline:** `StableNew-snapshot-20251128-111334.zip`  
**Inventory Baseline:** `repo_inventory_classified_v2_phase1.json` (Phase-1 classification)  

## 1. Goal and Scope

### High-Level Goal

Make the **V2 left panel** (Sidebar + Prompt Pack panel) the **single source of truth** for:

- Prompt pack browsing and application.
- Prompt pack *lists* (via `PromptPackListManager`).
- Preset selection and management (load/save/delete).
- Config source banner (default vs preset vs ad-hoc).

This prepares us to archive the legacy/hybrid GUI files by removing the last major feature-gap between `StableNewGUI` and the V2 GUI spine.

### Subsystems Touched

- **GUI V2**
  - `src/gui/sidebar_panel_v2.py`
  - `src/gui/prompt_pack_panel_v2.py`
  - `src/gui/prompt_pack_list_manager.py` (data helper only)
  - `src/gui/views/prompt_tab_frame.py` (apply-pack hook)
  - `src/gui/panels_v2/layout_manager_v2.py` (wiring only, if needed)

- **Tests**
  - `tests/gui_v2/test_gui_v2_layout_skeleton.py` (extend assertions)
  - `tests/gui_v2/test_packs_and_presets_left_panel_v2.py` (new)

> **Explicitly _not_ touching in this PR:**
> - `src/main.py`
> - `src/pipeline/executor.py`
> - `src/gui/main_window.py` (legacy)
> - `src/gui/app_layout_v2.py` (legacy bridge)
> - `src/gui/theme.py`
> - `src/gui/prompt_pack_panel.py`
> - `src/gui/adetailer_config_panel.py` (marked **“maybe”** to keep for now; no changes here)

---

## 2. Files to Modify (Allowed)

Implementation:

- `src/gui/sidebar_panel_v2.py`
  - Add packs/presets section(s) and config-source banner.
  - Wire callbacks to `PromptPackPanelV2` and to the Prompt tab.

- `src/gui/prompt_pack_panel_v2.py`
  - Extend to support:
    - Integration with `PromptPackListManager` (custom lists).
    - Emitting a richer “apply pack” signal.
  - Add UI elements (combobox or Listbox) for available pack lists if reasonable.

- `src/gui/prompt_pack_list_manager.py`
  - Keep as data helper.
  - Add small V2-friendly conveniences if needed (e.g., “list names” accessor).
  - No breaking changes to current JSON format.

- `src/gui/views/prompt_tab_frame.py`
  - Add a method like `apply_prompt_pack(summary: PromptPackSummary)` to receive packs from the sidebar.
  - Ensure the Prompt tab remains the single source of truth for prompt text areas.

- `src/gui/panels_v2/layout_manager_v2.py`
  - Only if required:
    - Ensure the left zone instantiates and attaches any additional packs/presets card or widgets now living in `SidebarPanelV2`.

Tests:

- `tests/gui_v2/test_gui_v2_layout_skeleton.py`
  - Extend expectations:
    - `sidebar_panel_v2` exposes attributes for:
      - Pack list UI control (e.g., `pack_list_combo`).
      - Preset UI control (e.g., `preset_combo` or `preset_dropdown`).
      - Config source banner label (e.g., `config_source_label`).
  - Ensure the test asserts these widgets exist and respond to simple operations.

- `tests/gui_v2/test_packs_and_presets_left_panel_v2.py` (new)
  - A new GUI V2 test file that verifies:
    - Packs list is populated from disk (using test dirs / fixtures).
    - Presets list is populated from disk.
    - Applying a pack updates the prompt in `PromptTabFrame`.
    - Loading a preset updates the config source banner.

---

## 3. Files as Read-Only Reference (Do **not** change)

Use these only to copy behavior/flow, not to modify:

- `src/gui/main_window.py` (StableNewGUI)
  - Reference for:
    - Preset dropdown behavior.
    - List dropdown behavior.
    - Config source banner semantics (`default` vs `preset` vs `ad-hoc`).

- `src/gui/prompt_pack_panel.py`
  - Reference for:
    - Prompt pack browsing UX.
    - Any hidden behaviors around how packs are applied.

- `src/utils/config.py` and `src/utils/preferences.py`
  - Reference for:
    - Preset storage/load/merge behavior.
    - Where lists/packs/presets live on disk.
    - Current default paths and naming patterns.

> The behavior-level source of truth is V1 for now, but the implementation source of truth after this PR must be V2 files only.

---

## 4. Behavioral Requirements (Ported from Legacy to V2)

### 4.1 Packs and Pack Lists

**From legacy behavior (StableNewGUI + PromptPackPanel):**

- List prompt packs by reading from `packs/` and/or any configured pack repository.
- Support applying a selected pack:
  - Append/merge the pack’s prompt, negative prompt, and other metadata into the current prompt workspace.
- Support **“pack lists”** managed via `PromptPackListManager`:
  - Lists represent curated sets of packs (e.g., “Grimdark Fantasy”, “Portrait Styles”).
  - The manager reads `custom_pack_lists.json` and exposes:
    - Available list names.
    - Packs in each list.

**In V2 left panel:**

- `SidebarPanelV2` hosts a “Prompt Packs” sidebar card that includes:
  - Pack list selector (if multiple lists exist).
  - Pack browser (via `PromptPackPanelV2`).
  - “Apply Pack” button.

- `PromptPackPanelV2`:
  - Integrates with `PromptPackListManager` to:
    - Show packs from the currently selected list (or a default view if no lists).
  - Emits an `on_apply` callback with a `PromptPackSummary` (existing type).

- Applying a pack:
  - Calls into `PromptTabFrame.apply_prompt_pack(summary)` (new V2 method).
  - That method updates:
    - The main positive prompt.
    - Negative prompt (if pack defines one).
    - Any other relevant fields in the Prompt tab, but does **not** directly touch pipeline sliders.

### 4.2 Presets and Config Source Banner

**From legacy behavior (StableNewGUI):**

- Presets are stored in `presets/` via `ConfigManager`.
- Preset dropdown shows available preset names.
- When a preset is loaded:
  - Config is merged with defaults.
  - A banner (e.g., “Preset: <name>”) reflects current source.
- When user deviates from preset (changes fields):
  - Banner switches to “Ad-hoc configuration” or similar.

**In V2 left panel:**

- `SidebarPanelV2` gains a “Presets” sidebar card:
  - Preset dropdown listing configs from `ConfigManager.list_presets()`.
  - Buttons for:
    - “Save as preset…” (optional in this PR, or hole-punched for later).
    - “Delete preset…” (optional in this PR).
  - A banner label (e.g., `config_source_label`) that shows:
    - `"Defaults"` if no preset is loaded.
    - `"Preset: <name>"` when a preset is in effect.
    - `"Ad-hoc configuration"` when the pipeline config has diverged.

- Config application:
  - V2 left panel uses existing config/prefs infrastructure:
    - Reads presets via `ConfigManager`.
    - Writes last-used preset name via `PreferencesManager` (if that behavior exists in legacy).
  - Pipeline config merging happens via existing V2 pipeline adapter/GUI state where possible; where not yet available, store the selected preset name and allow a follow-on PR to fully integrate with pipeline payload building.

---

## 5. Architectural Constraints

- **Do not reintroduce StableNewGUI or AppLayoutV2 into V2 imports.**
  - No imports from:
    - `src/gui/main_window.py`
    - `src/gui/app_layout_v2.py`
    - `src/gui/prompt_pack_panel.py`

- **GUI V2 remains modular:**
  - `MainWindowV2` still only owns:
    - Root window
    - Zones (header/left/center/right/bottom)
    - Wiring to `LayoutManagerV2` and high-level callbacks.
  - All pack/preset UI and behavior lives in:
    - `SidebarPanelV2`
    - `PromptPackPanelV2`
    - Prompt tab view (`PromptTabFrame`).

- **No controller or pipeline changes in this PR:**
  - Do not modify:
    - `src/controller/app_controller.py`
    - `src/pipeline/executor.py`
    - `src/api/*`
  - Any pipeline interactions should be limited to updating GUI state and calling already-exposed V2 helpers.

- **`adetailer_config_panel.py` stays untouched.**
  - It is considered a “maybe legacy / maybe future V2” file.
  - No imports from V2 GUI; no edits; leave for later investigation.

---

## 6. Tests and Validation

### 6.1 New/Updated Tests

- `tests/gui_v2/test_gui_v2_layout_skeleton.py`
  - Extend to assert:
    - `app.sidebar_panel_v2` has:
      - `pack_panel` (or similar child) for packs.
      - `preset_dropdown` (or similar) for presets.
      - `config_source_label` attribute.
  - Ensure no Tk errors are raised when creating `MainWindowV2` in test mode.

- `tests/gui_v2/test_packs_and_presets_left_panel_v2.py` (new)
  - Fixture:
    - Temporary `packs/` and `presets/` directories with minimal sample data.
    - A test preferences/config manager that points to temp dirs.
  - Assertions:
    - Packs list is populated and selecting + applying a pack calls into the Prompt tab (you can confirm via a test hook on `PromptTabFrame`).
    - Preset dropdown is populated with sample presets.
    - Loading a preset updates the config source banner text.
    - Changing a key field on the pipeline/config marks the banner as “Ad-hoc configuration”.

### 6.2 Manual Validation Checklist

For local runs (`python -m src.main` once entrypoint is fully flipped to V2):

1. App boots without Tk errors or blank screen.
2. Left panel shows:
   - Packs card.
   - Presets card.
   - Config source banner.
3. Pack selection:
   - Lists packs from `packs/`.
   - Clicking “Apply Pack” updates the Prompt tab.
4. Presets:
   - Dropdown lists presets from `presets/`.
   - Selecting a preset updates UI elements.
   - Config source banner shows “Preset: <name>”.
5. Modifying a key field in the pipeline config:
   - Config source banner tracks that the configuration is no longer a clean preset (via text change or visual hint).

---

## 7. Definition of Done (Phase-1 Left Panel Port)

This PR is **done** when:

- V2 left panel (Sidebar + PromptPackPanelV2) implements:
  - Pack browsing and apply behavior.
  - Pack lists via `PromptPackListManager`.
  - Preset dropdown and source banner logic.
- No V2 GUI code imports:
  - `src/gui/main_window.py`
  - `src/gui/app_layout_v2.py`
  - `src/gui/prompt_pack_panel.py`
- The new/updated V2 GUI tests pass:
  - `pytest tests/gui_v2/test_gui_v2_layout_skeleton.py -q`
  - `pytest tests/gui_v2/test_packs_and_presets_left_panel_v2.py -q`
- No changes were made to:
  - `src/main.py`
  - `src/pipeline/executor.py`
  - `src/controller/app_controller.py`
  - `src/gui/adetailer_config_panel.py`
- Behavior parity for packs/presets/config source banner with the legacy GUI is achieved at the UX level, using only V2 code paths.

