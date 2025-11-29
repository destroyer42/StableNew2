# PR-08 — V2 Full Pipeline Journey Test (txt2img → adetailer/img2img → upscale)

## Summary

We now have:

- V2 spine + theme + layout (`MainWindowV2`, `AppStateV2`, `theme_v2`, `layout_v2`)
- V2 panels (sidebar, pipeline, preview, status)
- V2 stage cards (advanced txt2img/img2img/upscale) componentized via `BaseStageCardV2`
- Controllers and pipeline runner wired into V2 (per PR-07)
- A test-safe threading/teardown layer (PR-07A)

But there is still a disconnect between what **unit/GUI tests** see and what you see when you run:

```bash
python -m src.main
```

Tests often instantiate controllers/UI in a specific configuration which may not perfectly match the `main.py` wiring. To ensure the real app path is correct, we need a **single end-to-end “Journey Test”** that:

- Uses the *same wiring* as `main.py` (or a shared factory).
- Drives the V2 app controller through a realistic pipeline:
  - `txt2img` stage
  - `adetailer` stage via `img2img`
  - `upscale` stage
- Asserts that the composed pipeline is correct and that the lifecycle state, status, and controller interactions are what we expect.

> This PR adds a high-level integration test that exercises the full V2 pipeline path without actually calling a real WebUI. It relies on a **FakePipelineRunner** that records pipeline configs and simulates success.

---

## Goals

1. Create a **single, authoritative journey test** that exercises the same wiring used by `main.py` / V2.
2. Verify that a “standard” 3-stage pipeline is constructed and handed to the pipeline runner in the correct order:
   - `txt2img`
   - `img2img` (adetailer)
   - `upscale`
3. Validate that `AppController`/V2 lifecycle transitions are correct:
   - IDLE → RUNNING → IDLE (or SUCCESS), no lingering error state.
4. Confirm that the test uses **the same construction path as production** (via a factory shared with `main.py`) so drift is detected.

---

## Non-Goals

- No real WebUI or SD inference; all external calls are faked.  
- No UI assertions about exact widget trees or pixel-perfect layout.  
- No changes to the actual pipeline business logic (`pipeline_runner` is assumed correct and already tested elsewhere).

---

## Design Overview

We introduce:

1. A **factory function** that builds the V2 app using the same wiring as `main.py`, but with dependency injection hooks so tests can substitute a fake pipeline runner.
2. A **FakePipelineRunner** implementation that:
   - Matches the `PipelineRunner` contract used by `AppController` / `LearningExecutionController`,
   - Captures the provided pipeline config,
   - Simulates a synchronous successful run.
3. A **journey test** file under `tests/journeys/` that:
   - Builds the V2 app via the factory with the fake runner,
   - Arranges a 3-stage pipeline (txt2img → adetailer/img2img → upscale),
   - Triggers a “Run” via the controller API (as close as possible to the actual button callback),
   - Asserts on:
     - Stage ordering/types,
     - Lifecycle state transitions,
     - No error state.

This test acts as a “canary” for any future wiring regressions in `main.py` or `MainWindowV2` construction.

---

## Implementation Plan

### 1. Add a V2 App Factory for Tests

In `src/main.py` (or a new `src/app_factory.py` if you want to keep `main.py` thin), add a function that encapsulates the production wiring but allows injection of a pipeline runner for tests.

Example:

```python
# src/app_factory.py (recommended)

from __future__ import annotations

import tkinter as tk
from typing import Optional

from src.config.app_config import AppConfig, build_app_config
from src.controller.app_controller import AppController
from src.controller.pipeline_controller import PipelineController
from src.controller.learning_execution_controller import LearningExecutionController
from src.controller.webui_connection_controller import WebUIConnectionController
from src.gui.app_state_v2 import AppStateV2
from src.gui.main_window_v2 import MainWindowV2
from src.api.webui_process_manager import WebUIProcessManager
from src.pipeline.pipeline_runner import PipelineRunner


def build_v2_app(
    *,
    root: Optional[tk.Tk] = None,
    config: Optional[AppConfig] = None,
    pipeline_runner: Optional[PipelineRunner] = None,
) -> tuple[tk.Tk, AppStateV2, AppController]:
    """Create the full V2 app as wired in production, but with injectable runner.

    Returns (root, app_state, app_controller) for use in tests or main.py.
    """
    if root is None:
        root = tk.Tk()

    if config is None:
        config = build_app_config()

    app_state = AppStateV2()

    # Build WebUI process manager
    webui_manager = WebUIProcessManager.from_config(config)

    # Build pipeline runner (real or fake)
    if pipeline_runner is None:
        # Use the existing factory / default pipeline runner
        pipeline_runner = ...  # e.g., PipelineRunner.from_config(config, webui_manager)

    # Build controllers; adjust to actual controller signatures in the repo
    pipeline_controller = PipelineController(config=config, pipeline_runner=pipeline_runner)
    learning_controller = LearningExecutionController(config=config, pipeline_runner=pipeline_runner)
    webui_controller = WebUIConnectionController(webui_manager=webui_manager)

    app_controller = AppController(
        app_state=app_state,
        pipeline_controller=pipeline_controller,
        learning_controller=learning_controller,
        webui_controller=webui_controller,
        # other dependencies as required by the implementation
    )

    # Build MainWindowV2 (wires panels, state, and controllers)
    window = MainWindowV2(
        root=root,
        app_state=app_state,
        webui_manager=webui_manager,
        app_controller=app_controller,
        packs_controller=app_controller.packs_controller,
        pipeline_controller=pipeline_controller,
    )

    # AppController may need a reference back to window for callbacks / logging
    app_controller.attach_window(window)

    return root, app_state, app_controller
```

In `src/main.py`, you can then simplify:

```python
from src.app_factory import build_v2_app

def main() -> None:
    root, app_state, app_controller = build_v2_app()
    root.mainloop()
```

> CODEX must adapt the names and parameters to match the real constructors and factories in the current repo; the above is a schematic.

### 2. Add FakePipelineRunner for Journey Tests

Under `tests/journeys/fakes/` (or `tests/fakes/`), create a fake runner that implements the subset of the `PipelineRunner` API used by `AppController` / controllers.

Example:

```python
# tests/journeys/fakes/fake_pipeline_runner.py

from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Any, Optional

from src.pipeline.pipeline_runner import PipelineConfig  # adapt to real types


@dataclass
class RunCall:
    config: PipelineConfig
    options: dict


@dataclass
class FakePipelineRunner:
    should_raise: bool = False
    run_calls: List[RunCall] = field(default_factory=list)

    def run(self, config: PipelineConfig, **options: Any) -> None:
        """Synchronous fake run that records the requested config."""
        self.run_calls.append(RunCall(config=config, options=dict(options)))

        if self.should_raise:
            raise RuntimeError("Fake pipeline failure (test)")

        # Simulate success; if there are callbacks, CODEX can add hooks here.
```

If your `PipelineRunner` uses a different method name (e.g., `run_pipeline`), match that instead. The key is that the fake records the `config` so tests can inspect the assembled stages.

### 3. Add a Journey Test File

Create a new test module:

```text
tests/journeys/test_v2_full_pipeline_journey.py
```

Implementation sketch:

```python
from __future__ import annotations

import tkinter as tk
import pytest

from src.app_factory import build_v2_app  # or src.main, depending on where the factory lives
from src.controller.app_controller import AppController, LifecycleState
from tests.journeys.fakes.fake_pipeline_runner import FakePipelineRunner


@pytest.fixture
def tk_root():
    root = tk.Tk()
    yield root
    try:
        root.destroy()
    except tk.TclError:
        pass


def test_v2_full_pipeline_journey_txt2img_adetailer_upscale(tk_root):
    # Arrange: build app with a fake pipeline runner
    fake_runner = FakePipelineRunner()
    root, app_state, app_controller = build_v2_app(root=tk_root, pipeline_runner=fake_runner)

    # Option A: configure a known 3-stage pipeline via AppController API.
    # For example, you might have something like:
    # app_controller.select_prompt_pack("journey_smoke_pack")  # a small built-in pack
    # app_controller.enable_stage("txt2img", enabled=True)
    # app_controller.enable_stage("adetailer", enabled=True)
    # app_controller.enable_stage("upscale", enabled=True)

    # For now, rely on defaults that main.py would use for a full pipeline.
    assert app_controller.state.lifecycle == LifecycleState.IDLE

    # Act: simulate clicking the Run button
    app_controller.on_run_clicked()

    # In synchronous mode, this should return after fake_runner.run() completes.
    assert app_controller.state.lifecycle in {LifecycleState.IDLE, LifecycleState.SUCCESS}
    assert app_controller.state.last_error is None

    # Assert: one pipeline run was triggered
    assert len(fake_runner.run_calls) == 1
    call = fake_runner.run_calls[0]

    # The config should have 3 stages in the expected order
    stages = call.config.stages  # adapt to the actual type/field name
    assert len(stages) == 3

    stage_kinds = [s.kind for s in stages]  # or s.name / s.stage_type
    assert stage_kinds == ["txt2img", "img2img_adetailer", "upscale"]
```

CODEX will need to:

- Adapt the factory + test to the actual APIs:
  - The `LifecycleState` enum names and field access (`app_controller.state.lifecycle`).
  - The `PipelineConfig` / `StageConfig` attributes (`config.stages`, `stage.kind` or similar).
- Optionally, configure a specific “journey smoke test” prompt pack or pipeline preset that ensures all three stages are active, instead of relying solely on defaults.

### 4. Optional: Negative Journey Test

Add a second test in the same module to ensure errors propagate correctly:

```python
def test_v2_full_pipeline_journey_error_from_runner_sets_error_state(tk_root):
    fake_runner = FakePipelineRunner(should_raise=True)
    root, app_state, app_controller = build_v2_app(root=tk_root, pipeline_runner=fake_runner)

    app_controller.on_run_clicked()

    assert app_controller.state.lifecycle in {LifecycleState.ERROR, LifecycleState.IDLE}
    assert app_controller.state.last_error is not None
```

This mirrors the spirit of the older PR-0 tests but uses the new V2 wiring and factory.

---

## Files Expected to Change / Be Added

**New:**

- `src/app_factory.py` (or equivalent) — V2 app builder with injectable runner.
- `tests/journeys/fakes/fake_pipeline_runner.py` — fake pipeline runner for journey tests.
- `tests/journeys/test_v2_full_pipeline_journey.py` — main Journey test module.

**Updated:**

- `src/main.py`
  - To call `build_v2_app()` instead of re-implementing wiring inline, if applicable.

- `tests/conftest.py` or `tests/gui_v2/conftest.py`
  - May add or reuse `tk_root` fixture for Tk lifecycle, or update to use the one here.

---

## Tests & Validation

1. Run the new journey test directly:

```bash
pytest tests/journeys/test_v2_full_pipeline_journey.py -v
```

2. Run the full suite:

```bash
pytest -q
```

Expected:

- No GUI crashes or Tk thread errors (assuming PR-07A is in place).  
- Journey test passes and confirms the correct 3-stage pipeline is built and executed (via fake runner).

If the journey test fails, it should provide actionable information about:

- Incorrect wiring in `build_v2_app` vs `main.py`.
- Missing or disabled stages in the assembled pipeline.
- Lifecycle state not transitioning as expected.

This is the **“single pane of glass”** test for the V2 experience: if this breaks, something fundamental in the wiring or stage assembly has regressed.
