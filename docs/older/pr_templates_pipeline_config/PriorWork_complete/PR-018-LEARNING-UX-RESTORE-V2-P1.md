# PR-018-LEARNING-UX-RESTORE-V2-P1 — Learning UX Wiring & Review Dialog

**Intent:**  
Restore and modernize the **learning UX** that previously lived in `main_window.py`:

- A visible “learning mode” toggle (on/off).
- A way to open a **learning review dialog** for rating outputs.
- Clean wiring into `LearningExecutionController` and `LearningTabFrameV2`.

The goal is to light up the learning subsystem at the UX level while preserving V2 architecture.

---

## 1. Scope & Subsystems

**Subsystems touched:**

- GUI V2 (Learning tab, toolbar)
- Learning subsystem (controller, review dialog)
- AppController (entrypoints)
- AppState (learning mode state)

**Files to modify:**

- `src/gui/views/learning_tab_frame_v2.py`
- `src/gui/learning_review_dialog_v2.py`
- `src/controller/learning_execution_controller.py`
- `src/controller/app_controller.py`
- `src/gui/main_window_v2.py` (if toolbar toggle is used)

---

## 2. High-Level UX Behavior

- **Learning toggle**:

  - A checkbox or switch labeled “Learning mode”.
  - When enabled, the system records extra metadata and allows rating/feedback.

- **Review dialog**:

  - Accessible from Learning tab (“Review recent results…” button) or a toolbar item.
  - Shows a list of recent runs (from JobHistory / Learning dataset).
  - Allows the user to assign ratings, tags, or comments.
  - On submission, calls into `LearningExecutionController` to write learning records.

---

## 3. Detailed Changes

### 3.1 `learning_tab_frame_v2.py` — UI Shell

- Add:

  - A `ttk.Checkbutton` or toggle-bound to `learning_enabled_var` (BooleanVar).
  - A “Review recent results…” button.

- Wire callbacks:

  ```python
  def _on_learning_toggled(self) -> None:
      controller = self._app_state.get("controller")
      if controller is not None:
          controller.on_learning_toggled(self._learning_enabled_var.get())

  def _on_open_review(self) -> None:
      controller = self._app_state.get("controller")
      if controller is not None:
          controller.on_open_learning_review()
  ```

- Store `learning_enabled` state in `app_state` as well so other components can read it.

### 3.2 `learning_review_dialog_v2.py` — Dialog Behavior

Ensure `LearningReviewDialogV2`:

- Accepts:

  ```python
  class LearningReviewDialogV2(ttk.Frame):
      def __init__(self, master, learning_controller, job_history_service, on_close=None, theme=None, *args, **kwargs):
          ...
  ```

- Can list recent runs (pulling from `job_history_service` or a similar abstraction).
- Allows rating (e.g., 1–5 stars or simple “good/bad”) and optional comments.
- On submission, calls methods on `learning_controller`:

  ```python
  learning_controller.submit_feedback(run_id, rating, comment)
  ```

### 3.3 `learning_execution_controller.py` — Public API

Add or confirm methods:

```python
class LearningExecutionController:
    def set_learning_enabled(self, enabled: bool) -> None: ...
    def submit_feedback(self, run_id: str, rating: int, comment: str | None = None) -> None: ...
```

These should ultimately:

- Update internal state and config.
- Persist feedback via `learning_record` / dataset builder.

### 3.4 `app_controller.py` — Entry Points

Add:

```python
def on_learning_toggled(self, enabled: bool) -> None:
    self._append_log(f"[learning] Learning mode set to {enabled}")
    self._learning_controller.set_learning_enabled(enabled)
    self._app_state.set("learning_enabled", enabled)

def on_open_learning_review(self) -> None:
    self._append_log("[learning] Opening learning review dialog…")
    window = self._app_state.get("main_window_v2")
    if window is None:
        return
    window.open_learning_review_dialog(
        learning_controller=self._learning_controller,
        job_history_service=self._job_history_service,
    )
```

### 3.5 `main_window_v2.py` — Dialog Host

Implement:

```python
def open_learning_review_dialog(self, learning_controller, job_history_service) -> None:
    dialog_win = tk.Toplevel(self)
    dialog_win.title("Learning Review")

    dialog = LearningReviewDialogV2(
        dialog_win,
        learning_controller=learning_controller,
        job_history_service=job_history_service,
        theme=self.theme,
        on_close=dialog_win.destroy,
    )
    dialog.pack(fill=tk.BOTH, expand=True)
```

---

## 4. Validation

### 4.1 Tests

- `tests/gui_v2/test_learning_tab_v2.py`:

  - Ensure toggle and button exist.
  - Use fake controller (or mock) to verify `on_learning_toggled` and `on_open_learning_review` are called.

- `tests/controller/test_learning_execution_integration_v2.py`:

  - Verify `set_learning_enabled` and `submit_feedback` update learning records as expected.

### 4.2 Manual

- Enable learning mode, run a pipeline.
- Open review dialog; rate the run.
- Confirm logs show learning-related actions.
- Confirm learning record file(s) updated (if already implemented).

---

## 5. Definition of Done

This PR is complete when:

1. Learning toggle and review button are visible and functional in V2 GUI.
2. LearningExecutionController receives correct enable/disable signals and feedback submissions.
3. LearningReviewDialogV2 opens and closes cleanly, and writes feedback through controller methods.
4. No references to legacy main_window remain in the learning UX path.
