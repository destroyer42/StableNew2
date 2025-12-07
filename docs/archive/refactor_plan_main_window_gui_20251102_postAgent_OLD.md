#ARCHIVED
> Historical refactoring plan document.

# Refactoring Plan: `main_window.py` GUI Overhaul

**Document ID:** `refactor_plan_main_window_gui_20251102_postAgent`
**Date:** November 2, 2025
**Author:** GitHub Copilot
**Status:** Proposed
**Related Docs:** `.github/copilot-instructions.md`

---

## 1. Overview & Problem Statement

This document outlines a strategic plan to refactor the primary GUI file, `src/gui/main_window.py`.

**Current State:** The `StableNewGUI` class has become a monolithic entity, responsible for:

- Main window creation and lifecycle.
- Building all UI components (API status, prompt packs, configuration tabs, pipeline controls, logging).
- Handling all event callbacks and business logic.
- Managing application state directly.

**Problem:** This monolithic architecture has led to significant development friction. Recent attempts to add test coverage for the prompt pack list manager have failed repeatedly because the class is too large and its components are too tightly coupled. Modifying one part of the GUI has unpredictable effects on others, and the code is difficult to reason about, debug, and test. This has resulted in getting stuck in unproductive development loops.

## 2. Desired State & Target Architecture

The goal is to transition from a monolithic architecture to a **Component-Based Coordinator Architecture**.

**Target Architecture:**

- **`StableNewGUI` (Coordinator):** The main class in `main_window.py` will be drastically simplified. Its sole responsibilities will be to:
  1. Initialize the main `tk.Tk()` window.
  2. Instantiate the various UI panel components.
  3. Lay out the main panels in the window.
  4. Mediate communication *between* the panels.

- **UI Panels (Components):** The UI will be broken down into logical, self-contained classes, each in its own file within the `src/gui/` directory.
  - `src/gui/api_status_panel.py`: Manages the API connection bar.
  - `src/gui/prompt_pack_panel.py`: Manages the prompt pack list, list management buttons, and the advanced editor button.
  - `src/gui/pipeline_controls_panel.py`: Manages the stage checkboxes, loop configuration, and batch settings.
  - `src/gui/config_panel.py`: The largest component, which will manage the configuration notebook and its sub-tabs (`txt2img`, `img2img`, etc.).
  - `src/gui/log_panel.py`: Manages the live log text area.

### 2.1. Communication Pattern: Observer/Mediator

To avoid creating a tangled web of direct callbacks, we will use a simplified **Observer/Mediator pattern**.

- **The `StableNewGUI` coordinator acts as the central Mediator.** It will expose methods for components to report significant events (e.g., `report_pack_selection_changed(packs)`).
- **Components act as Observers.** They will register themselves with the coordinator to be notified of events they care about. For instance, the `ConfigPanel` will have a method like `on_pack_selection_changed(packs)` that the coordinator will call.

This decouples the components from each other. The `PromptPackPanel` doesn't need to know that the `ConfigPanel` exists; it only needs to report its selection change to the coordinator. This makes the system much easier to extend in the future.

## 3. State Management and Data Flow

Clear data flow is critical. We will follow these principles:

- **Component-Scoped UI State:** Each panel is responsible for its own internal UI state. For example, `tk.StringVar` and `tk.IntVar` instances used by a panel's widgets will be owned by that panel class. This encapsulates the UI logic.
- **Centralized Application State:** The `StableNewGUI` coordinator will be the source of truth for application-level state that is shared across components, such as the currently selected prompt packs or the global configuration object.
- **Data Flow:** Data flows "down" from the coordinator to the panels via method calls (e.g., `config_panel.load_configuration(config_obj)`). Events flow "up" from panels to the coordinator via reporting methods (e.g., `coordinator.report_pipeline_settings_changed(settings)`).

## 4. Test-Driven Development (TDD) Strategy

To ensure a robust and methodical refactoring process, a Test-Driven Development (TDD) approach will be strictly followed.

**Workflow for each component:**

1. **Red:** Create a new test file (e.g., `tests/gui/test_prompt_pack_panel.py`). Write a failing test for the first piece of functionality (e.g., "test that the panel can be instantiated").
2. **Green:** Write the *minimum* amount of code in the component file (e.g., `src/gui/prompt_pack_panel.py`) to make the test pass (e.g., create the class definition).
3. **Refactor:** Clean up the code while ensuring the test still passes.
4. **Repeat:** Add a new failing test for the next feature (e.g., "test that clicking the refresh button calls the correct method") and repeat the cycle.

This methodology forces a clear definition of requirements *before* implementation, prevents over-engineering, and results in a comprehensive test suite that documents and validates the behavior of each component.

## 5. Step-by-Step Refactoring & Implementation Plan

This plan will be executed sequentially. Each step will result in a functional, tested piece of the new architecture.

### Step 0: Preparation

1. **Restore `main_window.py`:** Execute `git restore src/gui/main_window.py` to revert any failed partial edits and start from a clean, known-good state.
2. **Create Test Directory:** Create a `tests/gui/` directory to house the new GUI component tests.

### Step 1: Extract `PromptPackPanel`

1. **TDD:** Create `tests/gui/test_prompt_pack_panel.py` and `src/gui/prompt_pack_panel.py`.
2. **UI Construction:** Move the UI building code from `StableNewGUI._build_prompt_pack_panel()` into `PromptPackPanel.__init__()`. The constructor will accept `parent` and a `coordinator` instance.
3. **Logic & Callbacks:**
   - Move the list management methods (`_refresh_prompt_packs`, `_load_pack_list`, etc.) into the `PromptPackPanel`.
   - The `_on_pack_selection_changed` logic will now call `self.coordinator.report_pack_selection_changed(selected_packs)`, passing a `list[str]` of the selected file paths.
4. **Integration:** In `main_window.py`, instantiate `self.prompt_pack_panel = PromptPackPanel(parent_frame, coordinator=self)`.

### Step 2: Extract `PipelineControlsPanel`

1. **TDD:** Create `tests/gui/test_pipeline_controls_panel.py` and `src/gui/pipeline_controls_panel.py`.
2. **UI & State:** Move the relevant UI code. The panel will manage its own `tk.BooleanVar` and `tk.StringVar` instances for the checkboxes and loop settings.
3. **Interface:** The panel will expose a public method, `get_settings()`, which returns a structured dictionary that the main pipeline executor can use, e.g., `{ "run_txt2img": True, "run_img2img": False, "loop_mode": "sequential", "loop_count": 3 }`.

### Step 3: Extract `ConfigPanel` & Implement New Features

This is the most complex step and will benefit from a **sub-refactoring**.

1. **TDD:** Create `src/gui/config_panel.py` and `tests/gui/test_config_panel.py`.
2. **Sub-Refactoring:** The `ConfigPanel` itself will be a coordinator for smaller tab-specific panels (e.g., `Txt2ImgPanel`, `Img2ImgPanel`). This further breaks down complexity. For this step, we will extract the main notebook and its tabs into `ConfigPanel`, but defer extracting sub-panels.
3. **Extraction:** Move `_build_config_display_tab` and all related sub-tab build methods into the `ConfigPanel` class.
4. **Interface:** The `ConfigPanel` will have a public method `update_with_selection(selected_packs)` that the coordinator will call. This method will be responsible for recalculating and displaying the configuration based on the selected packs.
5. **Implement Feature Enhancements (TDD):**
   - **Hires Fix Steps:** Add the `hires_steps` spinbox to the `txt2img` tab. Ensure its `tk.IntVar` is correctly managed.
   - **Expanded Dimensions:** Update the `Combobox` values for width/height to include resolutions up to `2168`.
   - **Optional Face Restoration:**
     - Add a main "Enable Face Restoration" `Checkbutton`.
     - The dependent widgets (GFPGAN/CodeFormer sliders) will be created but not placed in the grid.
     - The checkbox callback will dynamically call `.grid()` or `.grid_remove()` on the dependent widgets to show/hide them, providing a clean user experience.

### Step 4: Extract `APIStatusPanel` and `LogPanel`

These are simpler components, but extracting them completes the architecture.

1. **`APIStatusPanel`:**
   - **TDD:** Create `src/gui/api_status_panel.py` and its test file.
   - **UI:** Move the status label and its update logic.
   - **Interface:** Expose a method `set_status(text, color)` that the coordinator can call during API checks.
2. **`LogPanel`:**
   - **TDD:** Create `src/gui/log_panel.py` and its test file.
   - **UI:** Move the `ScrolledText` widget for logging.
   - **Interface:** Expose a method `log(message)` that can be used by a custom `logging.Handler` to redirect logs to the GUI.

## 6. Error Handling Strategy

- **Component-Level:** Each component should be resilient. For example, if the `ConfigPanel` fails to load a pack's configuration, it should display an error message within its own frame rather than crashing the application. `try...except` blocks with logging will be used within component methods.
- **Coordinator-Level:** The main coordinator will be responsible for handling critical errors, such as the inability to connect to the SD API on startup, and displaying appropriate dialogs to the user.

## 7. Impact on Existing Tests

- **`tests/test_gui.py` (or similar):** Any existing high-level GUI tests will likely break and be removed.
- **Mitigation:** Testing responsibility will be shifted to the new, more granular component test files (`test_prompt_pack_panel.py`, etc.). This is a positive outcome, as the new tests will be more robust, targeted, and less brittle, leading to a net *increase* in test quality and coverage.

By following this detailed, test-driven plan, we can systematically and safely refactor the GUI into a clean, maintainable, and extensible architecture, resolving the current development bottleneck and paving the way for future feature additions.
