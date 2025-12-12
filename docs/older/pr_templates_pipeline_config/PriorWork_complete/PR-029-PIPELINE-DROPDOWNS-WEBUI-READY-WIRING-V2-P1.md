1. Title

PR-029-PIPELINE-DROPDOWNS-WEBUI-READY-WIRING-V2-P1 – Fix READY→Refresh Ownership & Wire Resource State into Dropdowns

2. Summary

PR-028 successfully:

Starts WebUI,

Uses stricter healthcheck semantics (PR-027),

Calls WebUIResourceService and logs model/VAE/sampler/scheduler counts.

But from the GUI’s point of view:

The Pipeline tab dropdowns never change,

And the bottom bar still shows conflicting WebUI statuses (two “WebUI: Ready” labels, plus “disconnected”).

This PR:

Moves the READY→refresh wiring out of main.py into the controller/GUI layer so WebUI lifecycle stays inside the V2 architecture instead of the entrypoint.

Ensures AppStateV2.resources changes actually propagate into the Pipeline tab, so the stage cards’ model/VAE/sampler/scheduler dropdowns update when WebUI becomes READY.

Cleans up the WebUI status duplication enough that you see a single, coherent READY state.

3. Problem Statement

Current behavior (after PR-027/028):

WebUI starts and really does reach READY.

Logs show Resource update: X models, Y vaes, Z samplers, W schedulers.

Yet:

The Pipeline tab model/VAE/sampler/scheduler dropdowns never update.

Bottom status bar still shows:

a tiny black bar,

a “disconnected” label,

multiple “WebUI: Ready” labels from different panels.

Root causes:

READY→refresh wiring is in main.py

WebUIConnectionController is given a ready_callback directly from main.py, violating the “thin main, logic in controller/GUI” rule and making tests/ownership messy.

AppStateV2.resources doesn’t notify the GUI meaningfully

Resources are stored and logged, but PipelineTabFrameV2 / StageCardsPanel / stage cards aren’t reliably subscribed to changes.

Stage cards don’t have robust “set values” hooks

Combobox items are mostly set at construction time using static or legacy helper methods; they never respond to resource updates.

Legacy status widgets still coexist

StatusBarV2 and APIStatusPanel (or other V1-ish status components) both show WebUI state, leading to duplicate/contradictory visual signals.

We need a small but decisive PR to:

Put READY→refresh in the right layer, and

Finish the wiring so the dropdowns finally move.

4. Goals

READY→refresh ownership

main.py becomes dumb again (no direct READY callback).

WebUI lifecycle (including “on READY, refresh resources”) lives in AppController + WebUIConnectionController + StatusBarV2.

Functional dropdown refresh

When WebUI hits READY:

AppController.refresh_resources_from_webui() is invoked,

AppStateV2.resources is updated,

PipelineTabFrameV2 / StageCardsPanel detect the change,

All relevant dropdowns (models, VAEs, samplers, schedulers) show the correct options from WebUI.

Clear single WebUI status

Bottom bar shows a single coherent WebUI connection indicator:

Disconnected / Connecting / Ready / Error, but not multiple contradictory labels.

Minimal & V2-only

Touch only V2 files and tests clearly needed to support this behavior.

No refactors, moves, or architecture changes beyond what’s strictly required.

5. Non-goals

No changes to the actual WebUIResourceService HTTP logic (endpoints, parsing) beyond what PR-028 already did.

No changes to pipeline execution (StageSequencer, PipelineRunner, payload shape).

No redesign of the entire status bar or logging view; just enough cleanup to remove contradictory WebUI labels.

No changes to engine settings dialog, advanced prompt editor, or learning tab.

6. Allowed Files

Implementation must be strictly limited to:

Controller / State:

src/controller/app_controller.py

src/controller/webui_connection_controller.py

src/gui/app_state_v2.py

GUI – Status / Pipeline / Stage Cards:

src/gui/status_bar_v2.py

src/gui/views/pipeline_tab_frame_v2.py
(and src/gui/views/pipeline_tab_frame.py only if both are active and the diff is minimal and mirrored)

src/gui/views/stage_cards_panel.py

src/gui/stage_cards_v2/advanced_txt2img_stage_card_v2.py

src/gui/stage_cards_v2/advanced_img2img_stage_card_v2.py

Entry point (cleanup only):

src/main.py
(allowed only to remove the READY callback wiring and delegate it to controller/GUI; no new complexity here)

Tests:

tests/controller/test_resource_refresh_v2.py (extend)

tests/gui_v2/test_pipeline_dropdown_refresh_v2.py (new)

7. Forbidden Files

The following files must not be modified in PR-029:

src/gui/main_window_v2.py

src/gui/theme_v2.py

src/gui/panels_v2/layout_manager_v2.py

src/gui/api_status_panel.py (unless we see a trivial, absolutely necessary diff—if so, stop and propose PR-029B)

src/pipeline/executor.py

src/pipeline/pipeline_runner.py

Any archive/ or legacy *_v1 or main_window.py files

Any config/CI files (pyproject.toml, pre-commit, GitHub workflows, etc.)

If Codex finds it must touch one of these, it should stop and report instead of editing.

8. Step-by-step Implementation
8.1 Move READY→refresh wiring out of main.py
8.1.1 AppController: define on_webui_ready

File: src/controller/app_controller.py

Add a method:

def on_webui_ready(self) -> None:
    """Handle WebUI READY lifecycle event."""
    # 1) Refresh resources from WebUI
    self.refresh_resources_from_webui()
    # 2) Future: any other READY-time actions go here


Keep refresh_resources_from_webui as implemented in PR-028, but:

Ensure it:

Calls self.webui_resource_service.refresh_all(),

Updates self.state.resources or AppStateV2.resources,

Logs counts,

Calls a helper that notifies the GUI (see 8.3).

8.1.2 WebUIConnectionController: support on-ready callbacks

File: src/controller/webui_connection_controller.py

Add a simple listener mechanism:

class WebUIConnectionController:
    def __init__(..., ready_callbacks: Optional[list[Callable[[], None]]] = None, ...):
        self._ready_callbacks: list[Callable[[], None]] = ready_callbacks or []
        ...
    
    def register_on_ready(self, callback: Callable[[], None]) -> None:
        self._ready_callbacks.append(callback)


Wherever the controller currently transitions to READY (after PR-027’s stricter healthcheck):

if state is WebUIConnectionState.READY:
    self._state = state
    for cb in self._ready_callbacks:
        try:
            cb()
        except Exception:
            logging.exception("Error in WebUI on_ready callback")


Do not change ensure_connected’s public API; just add the callback call when READY is achieved.

8.1.3 StatusBarV2: register AppController.on_webui_ready

File: src/gui/status_bar_v2.py

StatusBarV2 already has access to controller (AppController) and webui_panel (APIStatusPanel).

When constructing / wiring the WebUI connection controller (if the status bar has a reference to it directly, or via a setter):

Add something like:

def attach_webui_connection_controller(self, connection_controller: WebUIConnectionController) -> None:
    self._webui_controller = connection_controller
    self._webui_controller.register_on_ready(self.controller.on_webui_ready)


If the connection controller object is not directly passed into StatusBarV2 currently, add a small adapter method in whatever V2 panel manages the status bar to do this (within allowed files). The goal: someone in GUI (not main.py) calls register_on_ready(app_controller.on_webui_ready).

8.1.4 main.py: remove READY callback wiring

File: src/main.py

Locate where WebUIConnectionController is created with a ready_callback previously:

connection_controller = WebUIConnectionController(..., ready_callback=app_controller.refresh_resources_from_webui)


Replace with:

connection_controller = WebUIConnectionController(...)


Ensure main.py no longer passes any READY callback; the GUI/StatusBar is now responsible for registering app_controller.on_webui_ready.

8.2 Make AppStateV2.resources notify GUI

File: src/gui/app_state_v2.py

Verify / add a resources setter:

class AppStateV2:
    def __init__(...):
        self.resources: dict[str, list] = {"models": [], "vaes": [], "samplers": [], "schedulers": []}
        self._resource_listeners: list[Callable[[dict[str, list]], None]] = []
    
    def add_resource_listener(self, callback: Callable[[dict[str, list]], None]) -> None:
        self._resource_listeners.append(callback)

    def set_resources(self, resources: dict[str, list]) -> None:
        self.resources = resources
        for cb in self._resource_listeners:
            try:
                cb(resources)
            except Exception:
                logging.exception("Error in resources listener")


In AppController.refresh_resources_from_webui, make sure it calls app_state.set_resources(new_resources) rather than just mutating the dict in-place; this ensures listeners fire.

8.3 Wire Pipeline tab to AppState resource changes
8.3.1 PipelineTabFrameV2: subscribe to resources

File: src/gui/views/pipeline_tab_frame_v2.py

When constructing the Pipeline tab, you already pass app_state or controller in. Add:

def __init__(..., app_state: AppStateV2, ...):
    self.app_state = app_state
    self.stage_cards_panel = StageCardsPanel(..., app_state=app_state, ...)
    # subscribe to resource changes
    self.app_state.add_resource_listener(self._on_resources_changed)

def _on_resources_changed(self, resources: dict[str, list]) -> None:
    if hasattr(self, "stage_cards_panel"):
        self.stage_cards_panel.apply_resource_update(resources)


If StageCardsPanel already has apply_resource_update, reuse it. Otherwise, add it (next step).

8.3.2 StageCardsPanel: route updates to stage cards

File: src/gui/views/stage_cards_panel.py

Ensure StageCardsPanel has a method:

def apply_resource_update(self, resources: dict[str, list]) -> None:
    # e.g.
    if self.txt2img_card is not None:
        self.txt2img_card.apply_resource_update(resources)
    if self.img2img_card is not None:
        self.img2img_card.apply_resource_update(resources)
    if self.upscale_card is not None:
        self.upscale_card.apply_resource_update(resources)


This is the single place that knows about the list of stage cards; it shouldn’t do resource parsing, just delegation.

8.4 Stage cards: actually update comboboxes
8.4.1 AdvancedTxt2ImgStageCardV2

File: src/gui/stage_cards_v2/advanced_txt2img_stage_card_v2.py

Add:

def apply_resource_update(self, resources: dict[str, list]) -> None:
    models = resources.get("models") or []
    vaes = resources.get("vaes") or []
    samplers = resources.get("samplers") or []
    schedulers = resources.get("schedulers") or []

    self._update_combo(self.model_combo, self.model_var, models)
    self._update_combo(self.vae_combo, self.vae_var, vaes)
    self._update_combo(self.sampler_combo, self.sampler_var, samplers)
    if hasattr(self, "scheduler_combo"):
        self._update_combo(self.scheduler_combo, self.scheduler_var, schedulers)


Implement _update_combo as a small helper:

def _update_combo(self, combo, var, values: list[str]) -> None:
    if combo is None:
        return
    current = var.get()
    combo["values"] = values
    if current in values:
        combo.set(current)
    elif values:
        combo.set(values[0])
        var.set(values[0])


Keep this logic pure GUI – resource parsing/selection logic stays in controller/service.

8.4.2 AdvancedImg2ImgStageCardV2

File: src/gui/stage_cards_v2/advanced_img2img_stage_card_v2.py

Mirror the same apply_resource_update and _update_combo pattern for this card’s combos.

If upscale card needs similar wiring and uses the same resource sets, optionally add it here too (but keep scope minimal if it gets large).

8.5 WebUI status cleanup (duplicate READY labels)

File: src/gui/status_bar_v2.py (and possibly internal panel used there)

Identify the redundant label that always says "disconnected" or a second "WebUI: Ready":

Either:

Remove the extra label entirely and rely solely on APIStatusPanel’s status label, or

Keep one “WebUI:” label and bind it to the same state variable used by the panel.

Update update_webui_state(state) so it:

Maps WebUIConnectionState to user-facing text,

Updates exactly one WebUI status label (and any icon/indicator),

Does not leave any stale static text.

This is a light-touch change; no need to redesign the layout.

9. Required Tests (Failing First)

Before implementing behavior, Codex should add/extend tests that initially fail on the current snapshot.

Extend controller resource refresh test

File: tests/controller/test_resource_refresh_v2.py

Add a test that:

Mocks WebUIConnectionController hitting READY.

Confirms AppController.on_webui_ready is invoked via the controller’s register_on_ready callback.

Asserts AppStateV2.set_resources was called with resource dict.

New GUI test for dropdown refresh

File: tests/gui_v2/test_pipeline_dropdown_refresh_v2.py

Build a minimal fake V2 GUI with:

An AppStateV2 instance.

A PipelineTabFrameV2 wired with that state.

Simulate:

app_state.set_resources({"models": ["m1", "m2"], "vaes": ["v1"], "samplers": ["s1"], "schedulers": ["sch1"]}).

Assert:

The txt2img and img2img stage card combos’ ["values"] reflect these lists.

Default selection is within those lists (e.g., "m1").

Status bar sanity (optional)

A small unit test (if existing tests for StatusBarV2 exist) to assert:

After update_webui_state(READY), there is only one visible WebUI READY indicator string.

10. Acceptance Criteria

PR-029 is done when:

READY wiring is in the right place

main.py no longer passes READY callbacks into WebUIConnectionController.

AppController.on_webui_ready is registered via WebUIConnectionController.register_on_ready from the GUI layer (e.g., StatusBarV2 or its owning panel).

When WebUI becomes READY, logs show:

healthcheck success,

resource refresh,

resource update counts.

Pipeline dropdowns actually refresh

After WebUI is READY:

Model dropdown in Pipeline tab shows the model list from WebUI.

VAE dropdown shows VAEs.

Sampler dropdown shows samplers.

Scheduler dropdown shows schedulers (if exposed).

Changing resources (e.g., restarting WebUI with a different model set) and calling refresh again updates the dropdowns without restarting StableNew.

WebUI status is not duplicated

Bottom bar shows a single, coherent WebUI state:

“Disconnected” → “Connecting…” → “Ready” (or Error),

with no stray “disconnected” text or second “WebUI: Ready” label.

Tests

The new/extended tests pass:

pytest tests/controller/test_resource_refresh_v2.py -q

pytest tests/gui_v2/test_pipeline_dropdown_refresh_v2.py -q

Previously green tests remain green.

11. Rollback Plan

To roll back PR-029:

Restore:

src/controller/app_controller.py

src/controller/webui_connection_controller.py

src/gui/app_state_v2.py

src/gui/status_bar_v2.py

src/gui/views/pipeline_tab_frame_v2.py

src/gui/views/stage_cards_panel.py

src/gui/stage_cards_v2/advanced_txt2img_stage_card_v2.py

src/gui/stage_cards_v2/advanced_img2img_stage_card_v2.py

src/main.py

tests/controller/test_resource_refresh_v2.py

tests/gui_v2/test_pipeline_dropdown_refresh_v2.py (delete if added)

Re-run:

pytest for the core suite used in Phase-1.

Behavior will revert to PR-028 state—WebUI starts and resources log, but dropdowns stay static and READY wiring is back in main.py.

12. Codex Execution Constraints

When you hand this PR spec to Codex, include:

Only modify the Allowed Files list above.

Treat Forbidden Files as read-only.

Keep diffs minimal:

No refactors or renames.

No code motion that isn’t required for READY→refresh or dropdown application.

Do not change any public function signatures unless absolutely unavoidable; add optional parameters or new methods instead.

Avoid circular imports (e.g., GUI importing controller modules at top-level; use local imports if needed).

If a required behavior seems impossible within these constraints, stop and report instead of inventing new architecture.