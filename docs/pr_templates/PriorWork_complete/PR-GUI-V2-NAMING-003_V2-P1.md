
# PR-GUI-V2-NAMING-003_V2-P1 — Normalize Canonical V2 View Filenames with `_v2` Suffix

**Snapshot Baseline:** `StableNew-snapshot-20251128-111334.zip`  
**Inventory Baseline:** `repo_inventory_classified_v2_phase1.json`  

> Goal: For GUI **V2 view modules** that are already canonical and live in the `src/gui/views` package, normalize filenames so they clearly indicate V2 by appending `_v2` to the module name.  
> Behavior must remain unchanged; this is a **mechanical rename + import update** PR.

---

## 1. Goal & Scope

### High-Level Goal

Make it obvious at a glance which view modules belong to GUI V2 by appending `_v2` to their filenames, while:

- Keeping **class names the same** (`PromptTabFrame`, `PipelineTabFrame`, etc.).
- Updating all imports so nothing breaks.
- Not touching shared-core or non-GUI modules.

This aligns with your Phase-1 rule:

> “V2 files should be clearly identifiable (`_v2`, V2 in class names, or living in clearly V2-only modules).”

We constrain this PR to the **views layer** (`src/gui/views`) and the imports that reference those modules.

---

## 2. Files to Rename

All of these live under `src/gui/views/` and are already conceptually V2 (the package docstring literally says “Views package for GUI v2.”).

Use `git mv` for each:

1. `src/gui/views/prompt_tab_frame.py`  
   → `src/gui/views/prompt_tab_frame_v2.py`

2. `src/gui/views/pipeline_tab_frame.py`  
   → `src/gui/views/pipeline_tab_frame_v2.py`

3. `src/gui/views/learning_tab_frame.py`  
   → `src/gui/views/learning_tab_frame_v2.py`

4. `src/gui/views/stage_cards_panel.py`  
   → `src/gui/views/stage_cards_panel_v2.py`

5. `src/gui/views/run_control_bar.py`  
   → `src/gui/views/run_control_bar_v2.py`

6. `src/gui/views/experiment_design_panel.py`  
   → `src/gui/views/experiment_design_panel_v2.py`

7. `src/gui/views/learning_plan_table.py`  
   → `src/gui/views/learning_plan_table_v2.py`

8. `src/gui/views/learning_review_panel.py`  
   → `src/gui/views/learning_review_panel_v2.py`

9. `src/gui/views/pipeline_config_panel.py`  
   → `src/gui/views/pipeline_config_panel_v2.py`

> **Important:**  
> - **Do not** change the class names inside these modules (keep `PromptTabFrame`, `PipelineTabFrame`, etc.).  
> - This keeps the diff smaller and avoids touching type hints or string references.

---

## 3. Imports to Update

After renaming, update all imports that reference these modules or classes.

### 3.1 `src/gui/main_window_v2.py`

Currently imports:

```python
from src.gui.views.prompt_tab_frame import PromptTabFrame
from src.gui.views.pipeline_tab_frame import PipelineTabFrame
from src.gui.views.learning_tab_frame import LearningTabFrame
```

Change to:

```python
from src.gui.views.prompt_tab_frame_v2 import PromptTabFrame
from src.gui.views.pipeline_tab_frame_v2 import PipelineTabFrame
from src.gui.views.learning_tab_frame_v2 import LearningTabFrame
```

No other changes in this file.

### 3.2 `src/gui/views/__init__.py`

Currently:

```python
"""Views package for GUI v2."""

from .pipeline_tab_frame import PipelineTabFrame  # noqa: F401
from .prompt_tab_frame import PromptTabFrame  # noqa: F401
from .pipeline_config_panel import PipelineConfigPanel  # noqa: F401
from .stage_cards_panel import StageCardsPanel  # noqa: F401
```

Update to:

```python
"""Views package for GUI v2."""

from .pipeline_tab_frame_v2 import PipelineTabFrame  # noqa: F401
from .prompt_tab_frame_v2 import PromptTabFrame  # noqa: F401
from .pipeline_config_panel_v2 import PipelineConfigPanel  # noqa: F401
from .stage_cards_panel_v2 import StageCardsPanel  # noqa: F401
```

No changes needed to docstring or exported class names.

### 3.3 Learning Workflow Test

`tests/learning_v2/smoke_test_learning_workflow.py` currently does:

```python
import src.gui.views.learning_tab_frame
import src.gui.controllers.learning_controller
import src.gui.views.learning_plan_table
import src.gui.views.learning_review_panel
```

Update to:

```python
import src.gui.views.learning_tab_frame_v2
import src.gui.controllers.learning_controller
import src.gui.views.learning_plan_table_v2
import src.gui.views.learning_review_panel_v2
```

The rest of the test can remain unchanged, since it only checks importability.

### 3.4 Pipeline Tab Tests

These tests reference `PipelineTabFrame` and/or the pipeline view modules:

- `tests/gui_v2/test_pipeline_tab_layout_v2.py`
- `tests/gui_v2/test_pipeline_tab_stage_cards.py`
- `tests/gui_v2/test_scrollable_pipeline_panel_v2.py`

In each, update imports like:

```python
from src.gui.views.pipeline_tab_frame import PipelineTabFrame
```

to:

```python
from src.gui.views.pipeline_tab_frame_v2 import PipelineTabFrame
```

If they import via `src.gui.views` (e.g., `from src.gui.views import PipelineTabFrame`), no change is required because we’ve updated `__init__.py` to re-export the same class names.

### 3.5 Internal View Imports

Some views import each other by class name:

- `src/gui/views/pipeline_tab_frame.py` imports `StageCardsPanel`.
- `src/gui/views/run_control_bar.py` imports `StageCardsPanel` (or references it indirectly).
- `src/gui/views/learning_tab_frame.py` references `ExperimentDesignPanel`, `LearningPlanTable`, `LearningReviewPanel`.

After renaming:

- Update internal imports to point at the `_v2` modules:

Example patterns:

```python
from .stage_cards_panel import StageCardsPanel
```

→

```python
from .stage_cards_panel_v2 import StageCardsPanel
```

and similarly for:

```python
from .experiment_design_panel import ExperimentDesignPanel
from .learning_plan_table import LearningPlanTable
from .learning_review_panel import LearningReviewPanel
```

→

```python
from .experiment_design_panel_v2 import ExperimentDesignPanel
from .learning_plan_table_v2 import LearningPlanTable
from .learning_review_panel_v2 import LearningReviewPanel
```

---

## 4. Files **Not** to Touch in This PR

To keep this change purely about naming and imports:

- Do **not** modify:
  - `src/main.py`
  - `src/app_factory.py`
  - `src/pipeline/executor.py`
  - `src/controller/app_controller.py`
  - `src/gui/theme_v2.py`
  - `src/gui/sidebar_panel_v2.py`
  - `src/gui/pipeline_panel_v2.py`
  - `src/gui/prompt_pack_panel_v2.py`
  - `src/gui/status_bar_v2.py`
  - `src/gui/preview_panel_v2.py`
  - `src/gui/randomizer_panel_v2.py`
  - `src/gui/app_state_v2.py`
  - `src/gui/adetailer_config_panel.py` (still a **“maybe”**, no renaming or edits here)
- Do **not** rename or touch:
  - `src/gui/widgets/scrollable_frame_v2.py` (already V2-labelled)
  - `src/gui/controller.py` (GUI controller; version-agnostic name is fine)
  - Any non-GUI or shared-core modules.

---

## 5. Tests & Validation

### 5.1 Tests to Run

- `pytest tests/gui_v2/test_pipeline_tab_layout_v2.py -q`
- `pytest tests/gui_v2/test_pipeline_tab_stage_cards.py -q`
- `pytest tests/gui_v2/test_scrollable_pipeline_panel_v2.py -q`
- `pytest tests/learning_v2/smoke_test_learning_workflow.py -q`
- Optionally, full GUI/learning suites:
  - `pytest tests/gui_v2 -q`
  - `pytest tests/learning_v2 -q`

All of these should behave identically to before, since this is a file/module rename only.

### 5.2 Manual Check

- Confirm `python -m src.main` still launches `MainWindowV2` successfully.
- Confirm all tabs:
  - Prompt tab
  - Pipeline tab
  - Learning tab
  still load without errors (V2 views import paths are correct).

---

## 6. Definition of Done

This PR is complete when:

1. All nine view modules under `src/gui/views/` listed above have been renamed with a `_v2` suffix.
2. Class names inside those modules remain unchanged.
3. All imports across:
   - `src/gui/main_window_v2.py`
   - `src/gui/views/__init__.py`
   - `tests/gui_v2/*` (pipeline tab tests)
   - `tests/learning_v2/smoke_test_learning_workflow.py`
   - Any other view-to-view imports
   have been updated accordingly.
4. All targeted tests pass, and running the app still brings up the full V2 GUI without import errors.
5. No non-GUI/shared-core files were modified, and `adetailer_config_panel.py` remains untouched.

