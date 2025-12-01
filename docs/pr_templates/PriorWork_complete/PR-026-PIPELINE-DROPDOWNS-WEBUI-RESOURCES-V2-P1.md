1. Title

PR-026-PIPELINE-DROPDOWNS-WEBUI-RESOURCES-V2-P1

2. Summary

Wire the V2 Core Config panel (model / VAE / sampler dropdowns) to WebUIResourceService so that, when the WebUI API is reachable, those dropdowns populate from the actual WebUI resources instead of static defaults.

Add a small, explicit refresh path:

CoreConfigPanelV2 exposes a “refresh from adapters/WebUI” method.

SidebarPanelV2 exposes a single entrypoint to refresh core config from WebUI.

main.py’s WebUI lifecycle hook triggers that refresh when the connection state transitions to READY.

Result: When WebUI is up and the API works, the model/VAE/sampler dropdowns in the “Core Config” card visibly update, giving you a concrete signal that the API is alive and wired correctly.

3. Problem Statement

Right now:

WebUIResourceService exists and can list models/VAEs/etc.

CoreConfigPanelV2 has dropdowns for model/VAE/sampler and even a “Refresh” button stub.

SidebarPanelV2 wires in adapters and ConfigManager, but the dropdowns don’t actually call WebUIResourceService or hit the live API.

WebUIConnectionController + status bar show connection state, but that state isn’t used to refresh the dropdowns when WebUI becomes READY.

So from the UX perspective:

Launching WebUI “works” at the process/API level, but nothing in the Core Config panel visibly updates.

You don’t yet get the “true test” that the API is healthy: seeing all model/VAE/sampler dropdowns repopulate from WebUI.

We need a deterministic, testable path:

WebUI ready → call WebUIResourceService → CoreConfigPanel dropdowns are updated.

4. Goals

Use WebUIResourceService as the primary source of truth for Core Config dropdowns (models, VAEs, and samplers where applicable).

Implement a clean refresh path inside CoreConfigPanelV2 that:

Reads from adapters/WebUI.

Updates combobox values.

Preserves user selection when possible.

Expose a single, public method on SidebarPanelV2 to trigger a Core Config refresh (no outer code spelunking inside internal widgets).

Hook the WebUI lifecycle in main.py so that:

When WebUIConnectionState transitions to READY, we trigger a Core Config refresh once (and on retries, as appropriate).

Add tests so Codex can verify:

CoreConfigPanelV2 refreshes combobox values from supplied adapters/resources.

The WebUI READY transition results in a refresh being requested from the sidebar.

5. Non-goals

No change to pipeline execution, payload format, or stage sequencing.

No change to the EngineSettingsDialog behavior or engine settings persistence.

No new GUI tabs, panels, or layout changes.

No changes to the WebUIConnectionController state machine or retry algorithm beyond what’s needed to call the new refresh hook.

No attempt to auto-detect “scheduler” lists beyond what WebUIResourceService / SDWebUIClient already provide.

6. Allowed Files

Implementation is limited to the following files:

src/gui/core_config_panel_v2.py

src/gui/sidebar_panel_v2.py

src/gui/model_list_adapter_v2.py (small internal change only if needed)

src/main.py (WebUI lifecycle hook only)

Tests:

tests/gui_v2/test_core_config_webui_resources_v2.py (new)

tests/gui_v2/test_gui_v2_workspace_tabs_v2.py (only if minor update needed, e.g., to account for new methods)

tests/api/test_webui_resources.py (optional: add coverage if necessary for new usage patterns, not behavior changes)

7. Forbidden Files

Do not modify:

src/gui/main_window_v2.py

src/gui/panels_v2/layout_manager_v2.py

src/gui/views/pipeline_tab_frame_v2.py

src/gui/views/prompt_tab_frame_v2.py

src/gui/views/learning_tab_frame_v2.py

src/controller/webui_connection_controller.py

src/controller/pipeline_controller.py

src/api/client.py

Any archived V1 files under archive/

Any CI / config (pyproject.toml, pre-commit config, GitHub workflows, etc.)

If you discover a strong reason to touch any forbidden file, stop and surface that as a follow-on PR request instead of modifying it here.

8. Step-by-step Implementation
8.1 CoreConfigPanelV2: make adapters + refresh real

File: src/gui/core_config_panel_v2.py

Capture adapters and track combobox widgets

In init, after the parameters:

Store the passed adapters on the instance:

self._model_adapter = model_adapter

self._vae_adapter = vae_adapter

self._sampler_adapter = sampler_adapter

When building the three main comboboxes:

Keep references instead of discarding:

self._model_combo = self._build_combo(self.model_var, models or computed_models)

self._vae_combo = self._build_combo(self.vae_var, vaes or computed_vaes)

self._sampler_combo = self._build_combo(self.sampler_var, samplers or computed_samplers)

Use adapters as the source of dropdown values when not explicitly provided

If models is None and a model_adapter is provided, call a method like get_model_names() on the adapter to build the options list.

If vaes is None and a vae_adapter is provided, call get_vae_names() if available (or fall back to the model adapter as currently wired in SidebarPanelV2).

If samplers is None and a sampler_adapter is provided, call get_sampler_names() if available, otherwise fall back to the existing behavior (empty list or static values).

Implement a public refresh method that calls WebUI via adapters

Add a method:

def refresh_from_adapters(self) -> None:

If adapters are present, call out to them to get current lists:

models = adapter.get_model_names() or []

vaes = adapter.get_vae_names() or []

samplers = adapter.get_sampler_names() or [] (if implemented)

For each available list, update combobox values:

self._update_combo(self._model_combo, self.model_var, models)

self._update_combo(self._vae_combo, self.vae_var, vaes)

self._update_combo(self._sampler_combo, self.sampler_var, samplers)

_update_combo helper should:

Remember current selection.

Set combo["values"] to the new list.

If the previous selection is still present, restore it.

Otherwise, if there is at least one value, select the first and update the variable.

Wire the existing Refresh button to the new method

Replace the TODO body of _on_refresh with a simple call:

def _on_refresh(self) -> None:

self.refresh_from_adapters()

(Optional, small) Use WebUIResourceService inside adapters

If you need richer behavior (filesystem fallback + API):

In src/gui/model_list_adapter_v2.py, you may import WebUIResourceService and use it inside get_model_names/get_vae_names, but:

Keep this change minimal.

Do not change the external public API of ModelListAdapterV2.

Maintain compatibility with existing tests by preserving the old client-based behavior if WebUIResourceService is unavailable or fails.

If this optional layer complicates tests or introduces circularity, skip it and let adapters continue using SDWebUIClient directly. The key requirement is: CoreConfigPanelV2 can refresh from whatever the adapter returns, and those adapters are already wired to the WebUI client path.

8.2 SidebarPanelV2: single entrypoint for core config refresh

File: src/gui/sidebar_panel_v2.py

Add a helper to locate the CoreConfigPanelV2 instance

After constructing self.core_config_card, add a method:

def get_core_config_panel(self):

Iterate over self.core_config_card.body.winfo_children()

Return the first child that is an instance of CoreConfigPanelV2 (or has the expected methods).

If not found, return None.

Add a public method to trigger refresh from WebUI

Implement:

def refresh_core_config_from_webui(self) -> None:

panel = self.get_core_config_panel()

If panel is not None and has refresh_from_adapters, call panel.refresh_from_adapters().

Wrap in try/except and log/ignore errors rather than crashing the GUI.

This provides a clean, GUI-local hook that the WebUI lifecycle code can call without reaching into private attributes.

8.3 main.py: trigger refresh on WebUI READY

File: src/main.py

In _update_window_webui_manager, once you have:

connection_controller

WebUIConnectionState

webui_panel

and you already define update_status(log_changes=True) that polls connection_controller.get_state(), extend update_status so that:

When state transitions into WebUIConnectionState.READY:

If the main window has a sidebar_panel_v2 attribute and it exposes refresh_core_config_from_webui, call it once per “READY sequence”.

Use a small guard (e.g., a boolean flag like core_config_refreshed_on_ready) to avoid spamming refreshes on every status poll.

Pseudo-behavior:

On DISCONNECTED / CONNECTING / ERROR: don’t refresh.

On READY:

Call sidebar_panel_v2.refresh_core_config_from_webui() once, then mark that done.

If state later drops back to DISCONNECTED/ERROR and comes back to READY (via reconnect), allow another refresh (reset the guard in the reconnect path).

Make sure all calls are wrapped in try/except

If anything goes wrong (e.g., early startup where sidebar isn’t yet fully attached), log at debug/warn and continue.

Do not allow a sidebar refresh failure to crash the app or the WebUI lifecycle.

8.4 Tests

New GUI-level test for CoreConfigPanelV2 + adapters

File: tests/gui_v2/test_core_config_webui_resources_v2.py

Add tests like:

test_core_config_refresh_from_adapters_updates_model_dropdown

Build a dummy adapter with methods get_model_names/get_vae_names/get_sampler_names that return known lists.

Instantiate CoreConfigPanelV2 with those adapters and no explicit models/vaes/samplers.

Verify that before refresh, combo values are empty or default.

Call refresh_from_adapters().

Assert that the combobox values now match the adapter outputs and that selections are set sensibly.

test_core_config_refresh_preserves_selection_if_present

Pre-select e.g. “JuggernautXL” as model.

Adapter returns a list containing “JuggernautXL” + others.

After refresh_from_adapters(), verify the selected value is retained.

WebUI READY hook test (logic-level, without real Tk)

You can test the main.py hook with a minimal fake window:

FakeWindow with:

status_bar_v2.webui_panel that has set_webui_state, set_launch_callback, set_retry_callback.

sidebar_panel_v2.refresh_core_config_from_webui that increments a counter.

Patch WebUIConnectionController to a fake that:

get_state() returns READY on first call.

Call _update_window_webui_manager(fake_window, fake_webui_manager).

Assert that refresh_core_config_from_webui was called exactly once during the initial READY transition.

WebUIResourceService tests (optional)

If you changed WebUIResourceService or how adapters use it, add or adjust tests in tests/api/test_webui_resources.py to cover your new usage path (e.g., ensuring list_models() and list_vaes() return WebUIResource objects with display_name used by dropdowns).

9. Required Tests (Failing first)

Before implementation, expect these to fail (or be missing):

tests/gui_v2/test_core_config_webui_resources_v2.py::test_core_config_refresh_from_adapters_updates_model_dropdown

tests/gui_v2/test_core_config_webui_resources_v2.py::test_core_config_refresh_preserves_selection_if_present

tests/gui_v2/test_gui_v2_workspace_tabs_v2.py (if it asserts anything about sidebar behavior that needs adjusting for the new refresh method)

main-hook test for WebUI READY (new test as described above).

After implementation, all of these (plus existing suite) must pass.

10. Acceptance Criteria

Done when:

With WebUI running and reachable, launching StableNew V2 and waiting for WebUI status to reach READY visibly updates the “Core Config” dropdowns (models/VAEs/samplers):

Model dropdown shows the actual WebUI model list (e.g., juggernautXL_ragnarokBy, etc.).

VAE dropdown shows available VAEs when configured.

Sampler dropdown shows the sampler names from WebUI, or a documented subset if samplers are not yet fully integrated.

Clicking the Core Config “Refresh” button triggers the same WebUI-driven resource refresh, even if no state transition happens on the status bar (e.g., WebUI already READY).

If WebUI is not reachable:

The refresh path fails gracefully (no crash).

Combos either remain at defaults or fall back to filesystem-based lists (if available), with clear logging.

CoreConfigPanelV2 and SidebarPanelV2 remain compatible with existing tests and layout wiring; the app still boots cleanly and the V2 layout loads.

No new Tk errors appear during startup or when refreshing Core Config.

11. Rollback Plan

The change is localized to CoreConfigPanelV2, SidebarPanelV2, ModelListAdapterV2 (optional), and main.py.

To roll back:

Revert those files to their previous versions from the last known-good snapshot.

Remove the new tests under tests/gui_v2/test_core_config_webui_resources_v2.py if necessary.

Rolling back leaves the existing WebUI lifecycle and GUI behavior unchanged (status bar still works; dropdowns simply don’t auto-refresh from WebUI).

12. Codex Execution Constraints

Do not touch any files outside the Allowed Files list without explicit instruction.

Keep diffs minimal and focused:

No refactors, renames, or relocations beyond what is strictly required to wire the refresh behavior.

Preserve all existing public APIs for CoreConfigPanelV2, SidebarPanelV2, and ModelListAdapterV2.

Avoid introducing new circular imports (e.g., be cautious if importing WebUIResourceService into GUI modules; prefer local imports inside methods if needed).

If any existing test breaks unexpectedly, adjust the implementation first; only update tests when the behavior change is intentional and documented.