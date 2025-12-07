# StableNew V2 Rescue: Current Understanding & Safe Path Forward

_Last updated: 24 Nov 2025_

This document captures what we’ve learned about the current StableNew V2 state and defines a **safe, staged plan** to move forward **without accidentally deleting or archiving valuable V2 work**.

It is meant to prevent us from repeating the “V2 work treated as legacy” problem after OS resets, partial PRs, or tool confusion.

---

## 1. Context: How We Got Here

- Over the past weeks, we implemented **dozens of V2-oriented PRs**:
  - New V2 panels (`*_panel_v2.py`)
  - Advanced stage cards (`stage_cards_v2/advanced_*_stage_card_v2.py`)
  - V2 layout experiments (`app_layout_v2`, `layout_manager_v2`)
  - WebUI process manager and GUI wiring
  - Theme and UX groundwork
- Then:
  - The system was reset / OS was reinstalled.
  - Some PRs didn’t get merged in the originally intended order.
  - The main GUI entrypoint regressed into a hybrid or partially V1-flavored window.
  - Some V2 files ended up **not wired** into `src/main.py`, even though they were the “next step”.

Result:  
Tools looking purely at “reachability from main” or “test coverage” incorrectly marked some **V2 components** (especially stage cards) as “legacy” simply because they were not yet connected.

We want to avoid losing that work.

---

## 2. What We’ve Learned About the Codebase

### 2.1. There Is a Lot of Valid V2 Work

From the prior PR bundles (`PriorWork_complete(24NOV).zip`) and the repo inventory, we know that the following are **intended V2 core**:

- `src/gui/app_layout_v2.py`
- `src/gui/controller.py` (V2-aware GUI controller)
- `src/gui/panels_v2/*.py`
  - `sidebar_panel_v2.py`
  - `pipeline_panel_v2.py`
  - `preview_panel_v2.py`
  - `randomizer_panel_v2.py`
  - `status_bar_v2.py`
- `src/gui/pipeline_panel_v2.py`
- `src/gui/preview_panel_v2.py`
- `src/gui/prompt_pack_panel_v2.py`
- `src/gui/randomizer_panel_v2.py`
- `src/gui/resolution_panel_v2.py`
- `src/gui/state.py`
- `src/gui/status_bar_v2.py`
- `src/gui/stage_cards_v2/advanced_txt2img_stage_card_v2.py`
- `src/gui/stage_cards_v2/advanced_img2img_stage_card_v2.py`
- `src/gui/stage_cards_v2/advanced_upscale_stage_card_v2.py`
- `src/gui/stage_cards_v2/validation_result.py`
- `src/gui/theme.py`
- `src/gui/tooltip.py`
- V2-specific tests under `tests/gui_v2/`
- WebUI integration:
  - `src/api/webui_process_manager.py`
  - The new wiring in `src/main.py`
  - GUI’s usage of the WebUI manager (PR-00 + PR-00A)

These are **not legacy**. They are the backbone of StableNew V2.

### 2.2. Some “Unreachable” Files Are Actually V2 Prototypes

Parts of the GUI V2 design were created but **never fully wired up** (the “next thing” that was supposed to happen before things derailed). Examples:

- `src/gui/txt2img_stage_card.py`
- `src/gui/img2img_stage_card.py`
- `src/gui/upscale_stage_card.py`

These have:
- V2-style modular card structure.
- No current references from `src/main.py` or tests.
- Clear conceptual alignment with the card-based GUI design.

They are **V2 prototypes / experiments**, not V1 leftovers.  
They should **not** be treated as legacy or moved to archive until we have a running V2 spine and can make an explicit, deliberate decision about them.

### 2.3. True Legacy (V1) Is Mostly In the Test Surface

What we can safely classify as truly legacy right now (without risk):

- `tests/gui_v1_legacy/**`
- “Prior work” GUI-V1-style test bundles under `docs/pr_templates/PriorWork_complete/...`

These target the old main window, old layout, and old panel structure.  
They are **not used by the current V2 harness**.

We are deliberately **not** moving them yet, but they are safe candidates for archiving once the V2 path is stable.

### 2.4. There Are Gray-Area GUI Files

Some GUI modules are neither clearly V2 core nor clearly legacy:

- `src/gui/center_panel.py`
- `src/gui/adetailer_config_panel.py`
- `src/gui/panels_v2/layout_manager_v2.py`
- `src/gui/prompt_pack_list_manager.py`
- `src/gui/stage_chooser.py`

These need **manual review after V2 is running**:

- Some may be true V1 or “V1.5” layout remnants (e.g., `center_panel.py`).
- Some may be useful future helpers (`layout_manager_v2.py`, `stage_chooser.py`).

We don’t touch them until we can see the V2 app running and know exactly where they fit (if at all).

---

## 3. Core Principle Going Forward

> **We do not move or delete anything until we have a working V2 app spine + theme + layout.**

Only once the V2 GUI is:

- Fully booting,
- Using V2 panels,
- Showing stage-card flows (even minimally),
- Visually coherent (dark theme, readable text),
- And sized correctly (no more squished or invisible panes)

…do we start deciding what is truly unused.

Until then:

- **No archiving of GUI modules.**
- **No deleting “unreachable” GUI files.**
- We treat “unreachable” as “possibly not wired yet”, not “trash”.

---

## 4. Safe Forward Plan (High-Level)

We will proceed in **phases**, each focused on stabilizing and improving V2 **without removing anything**.

### Phase A — Stabilize V2 Runtime (No Archiving)

1. **PR-03 — V2 App Spine**
   - Introduce/normalize:
     - `MainWindowV2`
     - `AppStateV2`
     - `layout_v2` helpers
   - Ensure `src/main.py` launches **V2-only** GUI by default.
   - Wire up:
     - Sidebar
     - Pipeline panel
     - Preview panel
     - Status bar
     - WebUI controls panel (from PR-00A)
   - Result: StableNew boots into a coherent V2 window with a clear structure.

2. **PR-00A — WebUI GUI Controls**
   - Add a small `WebUIControlsPanel` (start/stop/restart/status) wired to `WebUIProcessManager`.
   - Place it in the status bar or footer.
   - Result: Users can see/manage WebUI lifecycle directly from the GUI.

3. **PR-04 — Theme Engine V2**
   - Create `theme_v2.apply_theme(root)` for:
     - Dark ASWF-like palette
     - Named styles: `Panel.TFrame`, `Card.TFrame`, `Primary.TButton`, etc.
   - Apply the theme in `MainWindowV2`.
   - Refactor key panels to use named styles instead of ad-hoc styling.
   - Result: The app looks like a real, dark-themed application again (no huge white patches).

4. **PR-05 — Layout & Resizing Fix (V2)**
   - Fix grid configuration, weights, and min sizes:
     - Sidebar, pipeline, preview columns
     - Main row/column weights
   - Ensure panels expand correctly when resized.
   - Improve padding/margins (at least to “non-squished” baseline).
   - Set a reasonable default window size.
   - Result: The V2 GUI no longer looks broken; main content is visible and usable.

> After Phase A, we have:  
> **A running V2 app, with a clear structure, readable theme, and non-broken layout.**

Only then do we move on.

---

### Phase B — Observe What’s Actually Used

Once the V2 GUI is functioning, we:

1. Run the app and visually check:
   - Which panels appear.
   - Which flows work end-to-end.
   - Which stage cards are actually used.
2. Run a small Python script to:
   - Recompute `repo_inventory.json`-style reachability.
   - Cross-check V2 panels, stage cards, and controllers against the current entrypoint.
3. Test stage-card loading:
   - Ensure each card can be initialized in isolation (e.g., in a dummy frame).
4. Exercise the pipeline:
   - Confirm controller → runner → WebUI interactions still work.

This gives us a **ground truth usage picture** that’s based on *actual runtime behavior*, not just static reachability.

---

### Phase C — Carefully Introduce Archiving (Later)

Only after Phase A and B are complete do we consider archiving:

1. **PR-02a — Move GUI V1 Tests to Archive**
   - Move `tests/gui_v1_legacy/**` → `archive/tests_v1/gui_v1_legacy/**`.
   - Move prior-work GUI V1 tests from `docs/pr_templates/...` into `archive/tests_v1/prior_work/...`.
   - Keep V2 tests (`tests/gui_v2/**`) untouched.

2. **PR-02b+ — Gradual Archive of True GUI V1/V1.5 Code**
   - File-by-file decisions for modules like:
     - `src/gui/center_panel.py`
     - Other clearly V1-era panels not used in the V2 spine.
   - Any action is preceded by:
     - “Is this referenced in runtime?”
     - “Does it have a role in the finalized V2 UX?”

We can also mark some V2 prototypes (e.g., older stage card variants) as “deprecated in favor of advanced_…”, but only **after** we’ve confirmed the newer versions are fully wired and stable.

---

## 5. Guardrails for Future Work

To avoid losing knowledge again:

1. **Never treat “unreachable from main” as automatically “legacy”.**
   - It may simply be **V2 work waiting to be wired**.

2. **Before archiving or deleting files:**
   - Confirm they are **not referenced** by:
     - `src/main.py` / `MainWindowV2` / `app_layout_v2`
     - V2 panels or stage cards
     - V2 tests
   - Confirm they are **not mentioned** in recent PRs as future work.

3. **Document PR intent in `docs/` as we go.**
   - For major structural PRs (spine, theme, layout, archiving), drop a short `.md` into `docs/` describing:
     - What changed
     - What’s considered V2 vs legacy
     - How future work should build on it

4. **Keep “prototype but not wired yet” modules in a known category.**
   - For example, we can tag them in a doc like:
     - `docs/V2_Prototypes_Not_Yet_Wired.md`
   - So tooling or contributors don’t misclassify them as obsolete.

---

## 6. Immediate Action Items

1. **Do _not_ move or delete any GUI files yet.**
2. **Focus current tool/agent work on:**
   - PR-03 — V2 App Spine
   - PR-00A — WebUI GUI Controls
   - PR-04 — Theme Engine
   - PR-05 — Layout & Resizing Fix
3. Once those are in place and the app looks and behaves correctly:
   - Re-assess what’s truly unused.
   - Introduce PR-02a (tests-only archiving) as a safe first cleanup step.

This path keeps all the hard-earned V2 work **on the table** while we stabilize the application, and it gives us a structured way to clean up later without losing functionality or design intent.
