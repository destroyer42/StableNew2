# PR-GUI-V2-RANDOMIZER-UX-002 — Randomizer Experience Deepening (V2)

## Status

- **Type:** Feature / UX refinement (GUI V2)
- **Scope:** `src/gui/*`, `src/gui_v2/*`, `tests/gui_v2/*`, docs
- **Pipeline Impact:** _Read-only_ — no changes to `src/pipeline/*` behavior
- **Learning Impact:** None (randomizer output shape preserved)

---

## 1. Problem & Goals

The V2 randomizer stack (panel + adapters + utils) is now functionally wired and covered by tests, but the **user experience is still “developer-grade”**: the matrix editor is minimal, variant counts are hard to reason about at a glance, and there is little guidance on how randomization interacts with packs, stages, and learning.

This PR focuses on **deepening the Randomizer UX for V2** without changing the underlying randomizer contracts or pipeline behavior.

### Goals

1. Make the **Randomizer panel V2** feel like a first‑class citizen of the central workflow.
2. Give users **clear mental models** for:
   - how matrix rows/columns map to variants,
   - how fanout multiplies variants, and
   - how randomization interacts with txt2img / img2img / upscale stages.
3. Provide **inline guidance and guardrails** so users can:
   - avoid explosive variant counts by accident,
   - quickly reset / reuse common patterns,
   - understand when randomizer + learning should be used together vs separately.

### Non‑Goals

- No introduction of new variant planning algorithms.
- No changes to `src/utils/randomizer.py` contracts or `src/pipeline/variant_planner.py` behavior.
- No integration with AI/LLM settings suggestion yet (that is covered by PR-AI-V2-SETTINGS-GENERATOR-001).

---

## 2. High‑Level Design

### 2.1 UX Framing

The V2 GUI will treat **Randomizer** as a “mode overlay” on top of a **known baseline config**:

- Pipelines are still configured via **PipelinePanelV2** (stage cards).
- Randomizer V2:
  - reads the current baseline config,
  - overlays variant dimensions (model, hypernetwork, Lora, style tags, etc.),
  - emits a variant plan and a total variant count through the existing adapters.

We do **not** change how the randomizer is executed; we only improve:

- **how users edit matrix entries,**
- **how the variant count is explained/visualized,**
- **how we preview a subset of variants,**
- **how we warn when variant count is too big for a single run.**

### 2.2 Key UX Additions

1. **Matrix editor quality-of-life:**
   - Add **per-row enable/disable toggles** (checkboxes) to allow quickly muting rows.
   - Provide **“clone row”** and **“delete row”** affordances.
   - Add **strip/trim sanitization** for entries and prevent accidental empty variants from bloating the matrix.
   - Optional: **row labels** (e.g., “Subject”, “Style”, “Lighting”) configurable via simple text cells.

2. **Variant count explainer:**
   - The existing “Total variants” label will be upgraded to show:
     - `Matrix combos × fanout = total variants`,
     - a **color-coded risk band** for very large counts (e.g., > 128) using the ASWF theme tokens.
   - Under the label, a one‑line helper text explains what is being multiplied (e.g. “3 rows × 2 options each × fanout 4 → 24 images”).

3. **Preview-first flow:**
   - Add a **“Preview variants” button** that:
     - computes the variant plan via the existing adapter,
     - shows a **small list view** of the first _N_ variant config summaries (e.g., N = 5),
     - warns when `total_variants` exceeds a configurable safe threshold, with recommended options:
       - “Reduce fanout”, “Disable some rows”, or “Proceed anyway (advanced)”.

4. **Learning-aware hints (non-invasive):**
   - When learning hooks are available in the controller, the Randomizer panel will display a subtle note:
     - “For dialing in best settings, prefer a Learning run. Use Randomizer after your favorite configs are locked in.”
   - This is textual-only for now (no new buttons / flows).

---

## 3. Detailed Changes

> All line numbers below are indicative and may shift; Codex should locate anchors by names/classes/functions, not raw line numbers.

### 3.1 GUI: RandomizerPanelV2 UX Enhancements

**File:** `src/gui/randomizer_panel_v2.py`

1. **Matrix row metadata and controls**
   - Extend internal row model (e.g., a small `MatrixRow` dataclass or dict) to include:
     - `enabled: bool`,
     - `label: str` (optional user label),
     - the existing `tk.StringVar` for values.
   - Update UI construction to:
     - Add a checkbox per row for `enabled`.
     - Add optional label entry per row (or a static label field if cheaper).
     - Add “clone” and “delete” buttons per row.
   - Ensure keyboard navigation is sane (Tab order) and doesn’t get in the way of basic typing.

2. **Row operations API**
   - Add internal helpers such as:
     - `_add_matrix_row(label: str = "", values: str = "")`,
     - `_clone_matrix_row(index: int)`,
     - `_delete_matrix_row(index: int)`,
     - `_rebuild_matrix_ui_from_model()`.
   - Wire the existing “Add row” button to `_add_matrix_row`.
   - Ensure rows are reindexed in a stable way and tests treat indices as **implementation details**, not public API.

3. **Sanitization & trimming**
   - When exporting options via `get_randomizer_options`:
     - Split row values on commas,
     - Trim whitespace,
     - Drop empty strings,
     - Respect `enabled` flag (disabled rows contribute nothing).
   - This must **not break** existing tests that assert raw dict shape; instead, adjust tests where appropriate to expect trimmed behavior.

4. **Variant count banner**
   - Enhance the existing variant count label to show:
     - `"{matrix_combos} × fanout {fanout} = {total} variants"`,
     - an optional “High output” badge when count > threshold.
   - Use Status/Theme adapters to compute and expose a **risk level** (low/medium/high) that drives color/style, without importing Tk inside adapters.

5. **Variant preview list (simple text-based)**
   - Add a small `ttk.Treeview` or `ttk.Frame` with labels to show the first N predicted variants:
     - Columns like “Index”, “Subject/style snippet”, “Stage overrides” (optional).
   - Backed by adapter results; no pipeline execution occurs here.
   - Ensure that preview construction is **purely based on existing randomizer plan logic** to avoid new contracts.

### 3.2 GUI V2 → Adapters

**File:** `src/gui_v2/randomizer_adapter_v2.py`

- Extend the adapter interface with a helper that returns both:
  - `matrix_combos`, `fanout`, and `total_variants`,
  - a **preview slice** of the variant plan (first N items).
- Maintain existing `RandomizerPlanResult` shape and avoid new dependencies.
- Add a small `RiskBand` enum or constants to classify variant counts into **safe / caution / high** bands.

### 3.3 Tests

**Directory:** `tests/gui_v2`

Add / update tests:

1. `test_gui_v2_randomizer_matrix_ux.py`
   - Asserts that:
     - rows can be added, cloned, deleted,
     - enabled/disabled rows impact exported options,
     - trimming and removal of empty entries behaves as expected.

2. `test_gui_v2_randomizer_variant_count_banner.py`
   - Asserts that the label text reflects matrix × fanout,
   - Risk band classification is correct at boundary thresholds.

3. `test_gui_v2_randomizer_preview_list.py`
   - Uses dummy adapter results to assert that preview items show up with correct index and summary strings,
   - Ensures no Tk errors in headless mode (reuse existing GUI V2 fixtures).

4. Update `test_gui_v2_randomizer_integration.py`
   - Extend coverage to confirm that:
     - preview count matches adapter,
     - high-variant warnings appear when threshold exceeded.

### 3.4 Safety / Import Guards

- Ensure that all new logic in adapters remains **Tk-free**.
- Add/update a safety test (e.g., `tests/safety/test_gui_v2_randomizer_ux_no_tk_imports.py`) to confirm no Tk imports sneak into the adapter modules.

---

## 4. Acceptance Criteria

- [ ] RandomizerPanelV2 shows enable/disable toggles, clone/delete row actions, and optional row labels.
- [ ] Exported options trim whitespace and ignore empty entries while respecting enabled flags.
- [ ] Variant count label shows `matrix_combos × fanout = total` and signals large counts with a visual hint.
- [ ] A preview list of the first N variants is available and driven entirely by the adapter plan.
- [ ] All new logic is covered by GUI V2 tests, with no Tk imports in adapter modules.
- [ ] `pytest tests/gui_v2 -v` passes.
- [ ] `pytest tests/safety -v` passes.
- [ ] `pytest -v` passes (existing XFAILs remain only where previously agreed).

---

## 5. Test Plan

1. **Unit / integration tests**
   - Run:
     - `pytest tests/gui_v2/test_gui_v2_randomizer_matrix_ux.py -v`
     - `pytest tests/gui_v2/test_gui_v2_randomizer_variant_count_banner.py -v`
     - `pytest tests/gui_v2/test_gui_v2_randomizer_preview_list.py -v`
     - `pytest tests/gui_v2/test_gui_v2_randomizer_integration.py -v`
     - `pytest tests/gui_v2 -v`
     - `pytest tests/safety -v`
     - `pytest -v`

2. **Manual smoke (optional, once Tk/Tcl is healthy)**
   - Launch StableNew GUI V2.
   - Open Randomizer panel.
   - Add a few rows with values like:
     - `warrior, ranger`
     - `cinematic lighting, studio light`
   - Adjust fanout to 3.
   - Confirm:
     - variant count label matches 2×2×3=12,
     - preview list shows at least the first few combinations,
     - disabling a row updates count and preview.

---

## 6. Risks & Rollback

### Risks

- Misclassification of variant counts could under‑ or over‑warn users.
- If sanitization is too aggressive, some legitimate variants might be dropped.

### Rollback

- Revert changes under:
  - `src/gui/randomizer_panel_v2.py`
  - `src/gui_v2/randomizer_adapter_v2.py`
  - New/updated `tests/gui_v2/*randomizer*` files
  - Any added safety tests

No migration of persisted state is required; randomizer options remain ephemeral per session.

---

## 7. Follow‑On Work

- Deeper integration with the **learning stack** so that the Randomizer panel hints when a pack has strong learned preferences.
- Per‑stage randomization controls (e.g., img2img‑only or upscale‑only variants).
- Tighter coupling to the future **AI settings generator** once configs are learnable per pack.
