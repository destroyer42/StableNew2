PR-03 — Create V2 App Spine

## Summary

Define and implement the structural backbone of the V2 application: a dedicated V2 GUI package, a main window module, and a clean entrypoint from `src/main.py`. This PR does not fully fix styling or layout; it focuses on structure and wiring.

---

## Motivation

- After Phase 1 cleanup, we want a clear and explicit place where all V2 GUI work lives.  
- Legacy/V1 GUI code should not be part of the main app path.  
- Future PRs (theme engine, layout, widgets, state, learning system) all need a stable, agreed-upon app structure.

---

## Scope

**In scope:**

- Creating the `src/gui/v2/` package.  
- Implementing `main_window_v2.py` with minimal but functional GUI scaffolding.  
- Updating `src/main.py` to launch V2 instead of the old GUI.  
- Adding placeholder modules for later work (`theme_v2.py`, `state.py`, `widgets/`, etc.).

**Out of scope:**

- Full visual polish and layout refinement (Phase 2).  
- New features like Learning System or distributed compute (Phase 3).

---

## Implementation Plan

1. **Create V2 package layout**  
   - Under `src/gui/`, add:
     - `v2/__init__.py`  
     - `v2/main_window_v2.py`  
     - `v2/theme_v2.py` (stub – will be filled in by PR-04)  
     - `v2/state.py` (stub – will be filled in by PR-07)  
     - `v2/widgets/__init__.py` (empty for now)  
   - Optionally add `v2/containers.py` or `v2/layout.py` as a future home for layout logic.

2. **Implement minimal main window**  
   - `main_window_v2.py` should:
     - Create the `Tk` root.  
     - Set a basic window title and minimum size.  
     - Create placeholder frames for:
       - Sidebar  
       - Pipeline controls  
       - Preview & jobs  
     - Arrange them in a simple grid so the app is obviously running V2 (even if visually plain).  
   - For now, frames can be empty or contain simple labels (“Sidebar”, “Pipeline”, “Preview/Jobs”).

3. **Wire entrypoint to V2**  
   - In `src/main.py`, import and call a function such as:
     - `from gui.v2.main_window_v2 import run_app`  
     - `if __name__ == "__main__": run_app()`  
   - Ensure any previous GUI entrypoint (V1) is no longer invoked by default.

4. **Document and mark TODOs**  
   - In `theme_v2.py`, `state.py`, and `widgets/__init__.py`, add docstrings describing their intended purpose and which PRs will fill them in.  
   - Add comments in `main_window_v2.py` indicating where Phase 2 work (layout, themes, widgets, state binding) will plug in.

5. **Maintain compatibility for pipelines**  
   - Ensure that whatever minimal controls exist still call into the current pipeline client when the user triggers a basic run (even if via a temporary “Run demo” button).  
   - This preserves a working vertical slice.

---

## Files Expected to Change / Be Added

- **New:** `src/gui/v2/__init__.py`  
- **New:** `src/gui/v2/main_window_v2.py`  
- **New:** `src/gui/v2/theme_v2.py` (stub)  
- **New:** `src/gui/v2/state.py` (stub)  
- **New:** `src/gui/v2/widgets/__init__.py`  
- **Updated:** `src/main.py` to launch V2.

No changes should be made to archived V1 code.

---

## Tests & Validation

- Run the app: `python -m src.main`  
  - Confirm that the window clearly shows “V2” via a title or label, so there is no ambiguity.  
  - Confirm that the window has three major regions (sidebar, pipeline, preview/jobs).  
- Trigger any available run/demo action to ensure pipeline calls still function.

---

## Acceptance Criteria

- The StableNew app launches using the V2 GUI entrypoint by default.  
- There is a dedicated `src/gui/v2/` package with placeholders for theme, state, and widgets.  
- The app remains functional, even if visually barebones.  
- The structure is ready for Phase 2 PRs to build on (theme/layout/widget refactors).