# PR-014-GUI-ADVANCED-EDITOR-V2-P1 — Advanced Prompt Editor (V2 Integration)

**Intent:**  
Reattach the existing **Advanced Prompt Editor** into the V2 GUI as a first-class citizen, aligned with the Prompt Tab structure and V2 architecture:

- Provide a visible, intuitive way to open the advanced editor from the Prompt tab.
- Ensure the editor uses V2 theming and app_state.
- Allow simple round‑trip editing: seed from current prompt → edit → apply back.

This PR does **not** radically redesign the editor. It focuses on wiring and compatibility.

---

## 1. Scope & Subsystems

**Subsystems touched:**

- GUI V2 (Prompt Tab / Left Zone)
- AppController (prompt flow)
- AppState / prompt source of truth

**Files to modify:**

- `src/gui/advanced_prompt_editor.py` (V2-safe initialization & theming)
- `src/gui/views/prompt_tab_frame_v2.py`
- `src/gui/main_window_v2.py`
- `src/controller/app_controller.py`

> NOTE: Keep changes additive and minimal. Do not reintroduce any V1-style imports or archived components.

---

## 2. High-Level Design

### 2.1 UX Behavior

- Add a **“Advanced Editor…”** button in the Prompt tab (top-right of prompt area or near the primary prompt input).
- Clicking the button:

  1. Reads the current active prompt from app_state (`prompt_text` / `negative_prompt_text`).
  2. Opens `AdvancedPromptEditor` in a modal window or child frame.
  3. Seeds the editor with current prompt(s).
  4. On “Apply & Close”, writes the final edited prompt back into app_state and refreshes the prompt input UI.

### 2.2 Architectural Rules

- The **Prompt Tab** remains the **source of truth** for prompt contents.
- The **Advanced Editor** is a **tool** that temporarily edits and returns updated text.
- AppController handles any additional plumbing (e.g., logging, analytics, learning hooks).

---

## 3. Detailed Changes

### 3.1 `src/gui/advanced_prompt_editor.py` — V2 Adaptation

Goals:

- Remove any direct assumptions about the legacy `StableNewGUI`.
- Accept theme/app_state/controller as parameters, but degrade gracefully if some are `None`.
- Ensure it can be used both in tests and from V2 main window.

**Key changes (sketch):**

- At top of file, ensure imports reference **V2 theme** and **tkinter/ttk** only (no legacy main_window imports).
- Adapt `AdvancedPromptEditor` to a simple, self-contained widget with:

  ```python
  class AdvancedPromptEditor(ttk.Frame):
      def __init__(self, master, theme=None, initial_prompt: str = "", on_apply=None, *args, **kwargs):
          ...
  ```

- Add an optional `on_apply(edited_prompt: str)` callback, invoked when user clicks “Apply & Close”.

### 3.2 `src/gui/views/prompt_tab_frame_v2.py` — Entry Point Button

- Add a button to open the advanced editor:

  - Placed near the main prompt entry area.
  - Labeled “Advanced Editor…” (short and discoverable).

- Wiring:

  - The Prompt Tab should not construct the editor directly; instead it calls an AppController method or uses app_state and a small callback adapter.
  - Example:

    ```python
    def _on_open_advanced_editor(self) -> None:
        controller = self._app_state.get("controller")
        if controller is not None:
            controller.on_open_advanced_editor()
    ```

### 3.3 `src/controller/app_controller.py` — Coordination

Add a method:

```python
def on_open_advanced_editor(self) -> None:
    self._append_log("[controller] Opening advanced editor…")

    window = self._app_state.get("main_window_v2")
    if window is None:
        return

    current_prompt = self._prompt_state.get_current_prompt()  # or equivalent helper

    window.open_advanced_editor(initial_prompt=current_prompt)
```

> Use whatever prompt-state helper currently exists; do **not** introduce a competing prompt source of truth.

### 3.4 `src/gui/main_window_v2.py` — Host Modal

Add a method on `MainWindowV2` to open the editor:

```python
def open_advanced_editor(self, initial_prompt: str) -> None:
    dialog = tk.Toplevel(self)
    dialog.title("Advanced Prompt Editor")

    editor = AdvancedPromptEditor(
        dialog,
        theme=self.theme,
        initial_prompt=initial_prompt,
        on_apply=self._on_advanced_prompt_applied,
    )
    editor.pack(fill=tk.BOTH, expand=True)
```

Handle apply callback:

```python
def _on_advanced_prompt_applied(self, new_prompt: str) -> None:
    controller = self.app_state.get("controller")
    if controller is not None:
        controller.on_advanced_prompt_applied(new_prompt)
```

Add `on_advanced_prompt_applied` in `AppController`:

```python
def on_advanced_prompt_applied(self, new_prompt: str) -> None:
    self._prompt_state.set_current_prompt(new_prompt)
    self._append_log("[controller] Advanced editor applied new prompt.")
```

> Exact names can be aligned with existing prompt-state utilities.

---

## 4. Validation

### 4.1 Tests

Add or extend:

- `tests/gui_v2/test_prompt_tab_advanced_editor_v2.py`:

  - Asserts that the “Advanced Editor…” button exists.
  - Uses a test double for controller so we can assert `on_open_advanced_editor` is called.

- `tests/gui_v2/test_advanced_prompt_editor_v2.py`:

  - Instantiates `AdvancedPromptEditor` with a dummy `on_apply` and ensures it invokes the callback with edited text.

### 4.2 Manual

- Launch GUI, go to Prompt tab, click “Advanced Editor…”.
- Edit the prompt and click “Apply & Close”.
- Confirm:

  - Advanced editor closes.
  - Prompt text in main prompt box updates.
  - Pipeline runs with the new prompt.

---

## 5. Definition of Done

This PR is complete when:

1. `AdvancedPromptEditor` is a V2-compatible widget with no legacy `StableNewGUI` assumptions.
2. Prompt tab shows an “Advanced Editor…” button that opens the editor.
3. Edits in the editor are correctly written back into the Prompt tab/app_state.
4. No legacy V1 GUI imports remain in these modules.
