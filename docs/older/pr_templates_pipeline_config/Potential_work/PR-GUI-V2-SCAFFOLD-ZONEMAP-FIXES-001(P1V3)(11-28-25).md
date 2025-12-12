# PR-GUI-V2-SCAFFOLD-ZONEMAP-FIXES-001(P1V3)(11-28-25) — V2 GUI Scaffold, Zone Map, and Tkinter Fixes (Phase 1)

## Intent

Stabilize the **V2 GUI foundation** so that:

- `MainWindowV2` always exposes the expected **zones** (header, left, bottom, main content, etc.)
- `AppController` can reliably attach to those zones without crashing
- Tkinter/Ttk widget construction no longer throws errors like  
  `_tkinter.TclError: unknown option "-config_manager"`

This PR is about **structure and wiring**, not visual redesign and not dropdown payload correctness.

**Outcomes:**

- `python -m src.main` should launch `MainWindowV2` without:
  - `AttributeError: 'MainWindowV2' object has no attribute 'header_zone'`
  - `AttributeError: 'MainWindowV2' object has no attribute 'bottom_zone'`
  - `_tkinter.TclError` from bad widget kwargs
- Controller ↔ zones wiring clearly defined via a **declarative zone map**
- No duplicate/competing V2 GUI scaffolds

---

## Scope

### In Scope

1. **Declarative Zone Map for V2 GUI**

   - Introduce a small, explicit “zone map” that defines the key layout zones used by the controller, e.g.:

     - `HEADER_ZONE`
     - `LEFT_ZONE`
     - `BOTTOM_ZONE`
     - `MAIN_ZONE` / `CONTENT_ZONE`

   - Represented as:
     - A tiny module (e.g. `src/gui/layout/zone_map_v2.py`) OR
     - A simple `Enum` / constants within an existing V2 GUI module (if that’s cleaner).

   - Zone map should define:
     - Zone names
     - Expected widget type (e.g., `ttk.Frame`)
     - Optional purpose/description (for doc clarity)

2. **Fix `MainWindowV2` Scaffold to Own Its Zones**

   - In `src/gui/main_window_v2.py` (or equivalent):

     - Ensure `MainWindowV2.__init__`:

       - Creates the key zone containers **immediately** (before external wiring):

         ```python
         self.header_zone = ttk.Frame(self, ...)
         self.left_zone = ttk.Frame(self, ...)
         self.bottom_zone = ttk.Frame(self, ...)
         self.main_zone = ttk.Frame(self, ...)
         ```

       - Packs/grids them in a stable layout.

     - Guarantee that by the time `build_v2_app` returns, these attributes exist and are not `None`.

   - The goal: `AppController` can assume these zone attributes exist and are frames it can populate.

3. **Align `AppController` Wiring with the Zone Map**

   - In `src/controller/app_controller.py`:

     - Update `_attach_to_gui` to:

       - Use the zone attributes **defined by the zone map**, e.g.:

         ```python
         header = getattr(self.main_window, "header_zone", None)
         left = getattr(self.main_window, "left_zone", None)
         bottom = getattr(self.main_window, "bottom_zone", None)
         ```

       - If any required zone is missing:
         - Log a clear error/warning **once** with the missing zone names.
         - Do **not** crash the app; fail gracefully.

       - Attach panels/widgets to the proper zones, not to `self.main_window` root directly.

     - Fix `__init__` to avoid using zones before wiring is confirmed:

       - If `_attach_to_gui()` defers wiring (zones not present), don’t immediately call `_update_status` with `bottom_zone.status_label`.
       - Prefer:

         - Call `_attach_to_gui()` **after** `MainWindowV2` zones exist (see next bullet), or
         - Guard `_update_status` so it doesn’t assume `bottom_zone` is wired yet.

4. **Ensure `build_v2_app` Orders Things Correctly**

   - In `src/app_factory.py` (or equivalent that builds the V2 app):

     - Ensure order resembles:

       ```python
       root = tk.Tk()
       window = MainWindowV2(root, ...)  # zones created here
       pipeline_runner = ...
       app_controller = AppController(window, pipeline_runner=pipeline_runner, threaded=threaded)
       # Optionally, explicit call to app_controller.attach_to_gui() if we decouple it from __init__
       ```

     - The key point:
       - `MainWindowV2` zones must exist **before** `AppController` tries to wire into them.
       - Do **not** create `AppController` before the V2 main window construction is complete.

5. **Fix Tkinter/Ttk Widget Kwargs (e.g., `config_manager` misuse)**

   - In `src/gui/base_stage_card_v2.py` and any other V2 GUI base classes:

     - Stop passing non-Tk keywords (e.g., `config_manager`) into `ttk.Frame.__init__` / `super().__init__`.

     - Pattern should be:

       ```python
       class BaseStageCardV2(ttk.Frame):
           def __init__(self, parent, config_manager: ConfigManagerV2 | None = None, **kwargs):
               self.config_manager = config_manager
               frame_kwargs = {k: v for k, v in kwargs.items() if k not in ("config_manager", ...)}
               super().__init__(parent, **frame_kwargs)
       ```

   - In `advanced_txt2img_stage_card_v2.py` (and other V2 stage cards):

     - Ensure they pass `config_manager` as a Python argument only, not as a Tk option.

   - Net result:
     - No `_tkinter.TclError: unknown option "-config_manager"`.

6. **Minimal Layout Fixes Only Where Needed**

   - It is okay to:

     - Adjust packing/grid calls in `MainWindowV2` to logically group header/left/bottom/main.
     - Ensure there is exactly one place the controller is supposed to attach status labels / header controls.

   - It is **not** okay in this PR to:

     - Redesign the UI.
     - Remove or add major widgets beyond what’s needed for stable wiring.

---

### Out of Scope

- Dropdown population from WebUI discovery (models/VAEs/samplers/schedulers).
- Payload correctness to `/sdapi/v1/options` and `/sdapi/v1/txt2img`.
- Left-panel duplication cleanup and scroll behavior.
- Learning features, randomization engine, advanced prompt editor.
- Any V1 code moves (that’s handled by the classification/archive PR).

---

## Guardrails

1. **Snapshot Required**

   - Before implementing this PR, run the snapshot script and note:

     ```text
     Snapshot used: ______________________
     ```

2. **Do Not Touch Core Pipeline Logic**

   - Do **not** modify:

     - `src/pipeline/executor.py`
     - WebUI API client behavior (beyond any minimal logging changes if absolutely necessary — but avoid if possible)

3. **Do Not Reanimate V1 Code**

   - No new imports from legacy V1 GUI files.
   - No copying V1 implementations into V2 files.
   - If you need to reference V1, treat it as read-only reference, not source.

4. **No Visual Redesign**

   - Any styling/theming/layout tweaks must be limited to:
     - Getting zones visible and functional.
     - Ensuring widgets don’t overlap catastrophically.
   - Do not introduce new styling systems, themes, or fonts in this PR.

---

## Files Likely to Be Touched

- `src/gui/main_window_v2.py`
- `src/controller/app_controller.py`
- `src/app_factory.py` (or `src/app_factory_v2.py`, depending on repo)
- `src/gui/base_stage_card_v2.py`
- `src/gui/advanced_txt2img_stage_card_v2.py`
- (Optionally) new helper:
  - `src/gui/layout/zone_map_v2.py`

---

## Suggested Implementation Steps

1. **Zone Map**

   - Add `src/gui/layout/zone_map_v2.py`:

     ```python
     from __future__ import annotations
     from dataclasses import dataclass
     from enum import Enum

     class ZoneName(str, Enum):
         HEADER = "header_zone"
         LEFT = "left_zone"
         BOTTOM = "bottom_zone"
         MAIN = "main_zone"

     @dataclass(frozen=True)
     class ZoneSpec:
         attr_name: str
         description: str

     ZONE_MAP_V2: dict[ZoneName, ZoneSpec] = {
         ZoneName.HEADER: ZoneSpec("header_zone", "Top header toolbar / controls"),
         ZoneName.LEFT: ZoneSpec("left_zone", "Pipeline configuration / controls"),
         ZoneName.BOTTOM: ZoneSpec("bottom_zone", "Status bar, log, progress"),
         ZoneName.MAIN: ZoneSpec("main_zone", "Main content / image panels"),
     }
     ```

   - `MainWindowV2` and `AppController` should reference these names to avoid drift.

2. **MainWindowV2 Zone Creation**

   - In `MainWindowV2.__init__`:

     - Create the frames using `ZONE_MAP_V2` constants.
     - Attach them to `self` with `self.<attr_name> = ttk.Frame(...)`.
     - Pack/grid them into a stable layout.

3. **AppController Wiring**

   - `_attach_to_gui` should:

     - Read `header_zone`, `left_zone`, `bottom_zone`, `main_zone` from `self.main_window`.
     - If any are missing, log and return early.
     - Once available, attach:
       - Status panel to `bottom_zone`.
       - Pipeline panel to `left_zone`.
       - etc., in a way consistent with existing V2 design.

   - `_update_status` should:

     - Access `self.main_window.bottom_zone.status_label` only if both `bottom_zone` and `status_label` exist.
     - Fallback gracefully if wiring is not ready yet (e.g., log and skip).

4. **App Factory Ordering**

   - Ensure `build_v2_app`:

     - Creates `MainWindowV2` first (zones created).
     - Then creates `AppController`.
     - Optionally, call a dedicated `app_controller.attach_to_gui()` instead of wiring inside `__init__` (but only if this change is minimal and consistent).

5. **Tkinter Kwarg Cleanup**

   - In `BaseStageCardV2` (and any other base classes):

     - Filter non-Tk kwargs before calling `super().__init__`.
     - Store custom arguments as attributes.

   - In `AdvancedTxt2ImgStageCardV2` and siblings:

     - Confirm they call the base class correctly:

       ```python
       super().__init__(parent, config_manager=config_manager, **frame_kwargs)
       ```

     - But only the base class should forward valid kwargs to Tk.

---

## Verification

### Required

- [ ] Run snapshot script; record snapshot name above.

- [ ] `python -m src.main`:
  - App launches with `MainWindowV2`.
  - No `AttributeError` for `header_zone`, `left_zone`, `bottom_zone`, etc.
  - No `_tkinter.TclError: unknown option "-config_manager"` (or similar).

- [ ] Basic pipeline smoke test:
  - Use the existing “StableNew GUI Run” style button or a manual txt2img run.
  - Confirm:
    - WebUI starts (or connects).
    - txt2img call is made (even if model name is still a bit off in this PR).

- [ ] `pytest -q`:
  - GUI V2 tests that previously failed due to:
    - `unknown option "-config_manager"`
    - missing `header_zone` / `bottom_zone`
  - should now pass or at least move to **different**, more meaningful failures (e.g., payload expectations).

### Optional (Nice to Have)

- [ ] Add a small test that asserts `MainWindowV2` has the zone attributes:

  ```python
  window = MainWindowV2(root, ...)
  assert hasattr(window, "header_zone")
  assert hasattr(window, "left_zone")
  assert hasattr(window, "bottom_zone")
  assert hasattr(window, "main_zone")
