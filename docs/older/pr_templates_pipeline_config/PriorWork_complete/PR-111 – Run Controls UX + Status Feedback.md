PR-111 – Run Controls UX + Status Feedback.md

Risk Tier: Low/Medium (Tier 1–2; GUI state only)
Baseline: StableNew-snapshot-20251203-071519.zip + repo_inventory.json
Related: PR-103 (run bridge), PR-109 (job history)

1. Intent

Make the three run controls in the 3rd column:

Run

Run Now

Add to Queue

behave like a real control surface:

Buttons enable/disable appropriately (no double-fires, no invalid “queue without pack”).

Status bar gives clear feedback (“Running DIRECT job #123…”, “Queued job #124 from pack X…”).

Validation errors (e.g., invalid stage config, ADetailer-only, missing WebUI) show as user-visible messages, not just logs.

2. Scope

Files

src/gui/app_state_v2.py

src/gui/panels/pipeline_run_controls_v2.py (or equivalent run-controls panel)

src/gui/status_bar_v2.py

tests/gui_v2/test_run_controls_states.py (new)

Out-of-Scope

Pipeline execution semantics (runner, executor, queue model).

Learning, history internals.

Major layout changes (we’ll reuse existing layout, just add state wiring).

3. Design
3.1 AppState fields for run states

File: src/gui/app_state_v2.py

Extend AppStateV2 with minimal flags:

class AppStateV2:
    ...
    is_run_in_progress: bool = False          # any run in flight
    is_direct_run_in_progress: bool = False   # specifically DIRECT run
    is_queue_paused: bool = False             # if queue is paused
    last_run_job_id: str | None = None
    last_error_message: str | None = None


These are “single source of truth” for button enable/disable logic and status bar messages.

AppController (from PR-103) should set/clear:

is_run_in_progress

is_direct_run_in_progress

last_run_job_id

last_error_message (on validation/runtime errors)

We don’t implement all controller wiring here (that may already be partially done); this PR focuses on reading these fields in the GUI and updating them in simple, obvious spots.

3.2 PipelineRunControlsV2: button enable/disable rules

File: src/gui/panels/pipeline_run_controls_v2.py

Assume this panel has three buttons bound to:

app_controller.start_run_v2

app_controller.on_run_job_now_v2

app_controller.on_add_job_to_queue_v2

Add logic to compute each button’s state from app_state:

class PipelineRunControlsV2(ttk.Frame):
    def __init__(self, master, app_state: AppStateV2, controller: AppController, **kwargs):
        ...
        self.app_state = app_state
        self.controller = controller
        # Buttons: self.btn_run, self.btn_run_now, self.btn_add_to_queue

    def refresh_states(self) -> None:
        s = self.app_state

        # Run Now (DIRECT run, immediate)
        if s.is_run_in_progress and s.is_direct_run_in_progress:
            self.btn_run_now.configure(state="disabled")
        else:
            self.btn_run_now.configure(state="normal")

        # Run (queue-backed batch / scheduled run)
        if s.is_queue_paused:
            self.btn_run.configure(state="disabled")
        else:
            self.btn_run.configure(state="normal")

        # Add to Queue: requires non-paused queue and a pack if that’s your rule
        has_pack = getattr(s, "job_draft", None) is not None and getattr(s.job_draft, "pack_id", None)
        if s.is_queue_paused or not has_pack:
            self.btn_add_to_queue.configure(state="disabled")
        else:
            self.btn_add_to_queue.configure(state="normal")


Call refresh_states():

Once after construction.

After any state change notification (e.g., a simple app_state.subscribe(self.refresh_states) pattern, or invoked by controller callbacks).

3.3 Status bar messages

File: src/gui/status_bar_v2.py

Expose a simple API:

class StatusBarV2(ttk.Frame):
    def __init__(self, master, **kwargs):
        ...
        self._label = ttk.Label(self, text="")
        self._label.pack(...)

    def set_status(self, message: str) -> None:
        self._label.configure(text=message)

    def clear(self) -> None:
        self._label.configure(text="")


Wire this to AppController actions:

On run start:

# Called by AppController when a job is created
self.app_state.is_run_in_progress = True
self.app_state.is_direct_run_in_progress = (run_mode == "direct")
self.app_state.last_run_job_id = job_id
status_bar.set_status(f"Running {run_mode.upper()} job #{job_id}...")


On queued-only Add to Queue:

status_bar.set_status(f"Queued job #{job_id} from pack {pack_id}...")


On completion:

self.app_state.is_run_in_progress = False
self.app_state.is_direct_run_in_progress = False
status_bar.set_status(f"Job #{job_id} completed.")


On error:

self.app_state.is_run_in_progress = False
self.app_state.is_direct_run_in_progress = False
self.app_state.last_error_message = error_message
status_bar.set_status(f"Error in job #{job_id}: {error_message}")


(The exact location of these calls can be AppController or JobService callbacks; the key is that the pattern is defined.)

3.4 Validation error surfacing

When validators (e.g., config validation / stage plan checks) fail before a job is even created (e.g., “ADetailer requires a generation stage” from PR-107):

Set last_error_message on AppStateV2.

Call status_bar.set_status(error_message).

Do not change is_run_in_progress (run never started).

Buttons should remain enabled (user can fix config and try again).

4. Tests – Run Controls & Status

File: tests/gui_v2/test_run_controls_states.py

Use a minimal harness that:

Creates a fake AppStateV2 object.

Creates PipelineRunControlsV2 and StatusBarV2 with no real Tk mainloop.

Simulates state changes and inspects button states / status text.

4.1 Example tests

Run Now disabled during active DIRECT run

def test_run_now_disabled_while_direct_run_in_progress():
    app_state = AppStateV2()
    app_state.is_run_in_progress = True
    app_state.is_direct_run_in_progress = True

    panel = make_run_controls_panel(app_state)  # helper that builds panel/buttons
    panel.refresh_states()

    assert str(panel.btn_run_now["state"]) == "disabled"
    assert str(panel.btn_run["state"]) == "normal"


Run/Add to Queue disabled when queue paused

def test_run_and_add_to_queue_disabled_when_queue_paused():
    app_state = AppStateV2()
    app_state.is_queue_paused = True
    app_state.job_draft = type("JD", (), {"pack_id": "pack-123"})()

    panel = make_run_controls_panel(app_state)
    panel.refresh_states()

    assert str(panel.btn_run["state"]) == "disabled"
    assert str(panel.btn_add_to_queue["state"]) == "disabled"


Add to Queue disabled when no pack selected

def test_add_to_queue_disabled_without_pack():
    app_state = AppStateV2()
    app_state.is_queue_paused = False
    app_state.job_draft = type("JD", (), {"pack_id": ""})()

    panel = make_run_controls_panel(app_state)
    panel.refresh_states()

    assert str(panel.btn_add_to_queue["state"]) == "disabled"


Status bar reflects running and completion

def test_status_bar_updates_for_run_lifecycle():
    status_bar = StatusBarV2(master=None)
    app_state = AppStateV2()
    app_state.last_run_job_id = "123"

    status_bar.set_status("Running DIRECT job #123...")
    assert "Running DIRECT job #123..." in status_bar._label["text"]

    status_bar.set_status("Job #123 completed.")
    assert "Job #123 completed." in status_bar._label["text"]


Validation error surfaces

Simulate a failed run attempt by calling a controller stub that sets last_error_message and status_bar text, then assert error is visible.

5. Validation & Acceptance

Commands:

pytest tests/gui_v2/test_run_controls_states.py
pytest tests/gui_v2


Acceptance:

 AppStateV2 exposes flags for run-in-progress, queue paused, last job id, last error.

 Run controls panel uses these flags to enable/disable buttons per rules.

 Status bar shows concise messages for run start, queueing, completion, and errors.

 New tests cover:

Run Now disabled during direct run.

Run / Add to Queue disabled appropriately for queue-pause / no-pack cases.

Status text updated for run lifecycle and validation errors.