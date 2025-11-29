📦 PR-028-DROPDOWN-REFRESH-V2-P1

Scope: Pipeline dropdown population via WebUIResourceService → update AppController → update stage cards in PipelineTabFrameV2
Summary: Wire live WebUI resource data (models/VAEs/samplers/schedulers) into GUI dropdowns after WebUI is READY.

📦 Snapshot Requirement

Baseline Snapshot:
StableNew-snapshot-20251129-075009.zip

🧠 PR Type

 Wiring

 GUI update

 Controller sync

 New feature

 Tests only

🧩 Files Allowed to Modify (ONLY these):
src/controller/app_controller.py
src/controller/webui_connection_controller.py
src/api/webui_resource_service.py
src/gui/views/pipeline_tab_frame.py
src/gui/views/stage_cards_panel.py
src/gui/pipeline_panel_v2.py
src/gui/model_list_adapter_v2.py


Notes:

All files above are V2-active modules (see ACTIVE_MODULES.md).

No core V2 scaffolding, layout manager, or main_window_v2 is touched in PR-028 (these are forbidden).

🚫 Forbidden Files (must not be edited)
src/gui/main_window_v2.py
src/gui/theme_v2.py
src/pipeline/executor.py
src/pipeline/pipeline_runner.py
src/main.py
src/gui/layout_v2.py
src/gui/panels_v2/*


These are locked per the StableNew AI Discipline Protocol.

🎯 Goals (Done Criteria)

PR-028 is considered complete when ALL of the following are true:

 When WebUI reaches READY, AppController triggers WebUIResourceService.refresh_all()

 Controller receives resource data and updates an in-memory AppStateV2.resources

 PipelineTabFrameV2 dropdowns now populate:

 model list

 VAE list

 sampler algorithms

 scheduler algorithms

 Stage cards (txt2img / img2img / upscale) read from AppStateV2.resources on initialization & on refresh

 A simple log message (level INFO) shows which parts updated, visible in bottom logging panel

 No duplicated WebUI status labels appear

 Forbidden files untouched

🔧 Implementation Plan (Step-by-Step)
1. Add AppStateV2.resources structure

Inside app_controller.py:

Add a new dict:

self.state.resources = {
    "models": [],
    "vaes": [],
    "samplers": [],
    "schedulers": []
}


Default to empty lists.

2. Add AppController.refresh_resources_from_webui()

New method:

def refresh_resources_from_webui(self):
    data = self.resource_service.refresh_all()
    self.state.resources.update(data)
    self._update_gui_dropdowns()


Where _update_gui_dropdowns() simply broadcasts the new values to the active PipelineTabFrame (already reachable via view adapters).

3. Modify WebUI lifecycle: trigger on READY

In webui_connection_controller.py, after state becomes READY:

self.app_controller.refresh_resources_from_webui()


This ensures dropdowns update only after a verified 200 OK API probe.

4. Implement WebUIResourceService.refresh_all()

Add method returning:

{
  "models": [...],
  "vaes": [...],
  "samplers": [...],
  "schedulers": [...]
}


Use the standard WebUI API endpoints:

/sdapi/v1/sd-models

/sdapi/v1/vae

/sdapi/v1/samplers

/sdapi/v1/schedulers

This already exists in code as partial helpers — PR-028 only consolidates and standardizes it.

5. Update PipelineTabFrameV2

Add method:

def apply_resource_update(self, resources):
    self.model_dropdown.update(values=resources["models"])
    self.vae_dropdown.update(values=resources["vaes"])
    self.sampler_dropdown.update(values=resources["samplers"])
    self.scheduler_dropdown.update(values=resources["schedulers"])

6. Update StageCardsPanelV2

Each stage card uses one of the dropdowns. Add an adapter-level hook:

def on_resources_changed(self, resources):
    self.model_selector.set_items(resources["models"])
    ...

7. Logging

Inside controller refresh:

self.logger.info(f"Resource update: {len(models)} models, "
                 f"{len(vaes)} vaes, {len(samplers)} samplers, "
                 f"{len(schedulers)} schedulers")


This fixes the “no feedback in bottom panel” problem.

🧪 Required Tests

Codex must ensure these tests pass and add 1 new test:

Existing tests to remain green:
pytest tests/controller/test_webui_lifecycle_ux_v2.py -q
pytest tests/api/test_webui_healthcheck.py -q
pytest tests/gui_v2/test_gui_v2_workspace_tabs_v2.py -q

New test to add:
tests/controller/test_resource_refresh_v2.py


Cover:

Mock WebUIResourceService returning known lists.

Trigger READY state on WebUI controller.

Assert controller updates AppStateV2.resources.

Assert PipelineTabFrameV2 apply_resource_update() receives correct lists.

✔️ Acceptance Criteria

Launch GUI → Launch WebUI

After 2–5s, the log shows:
Resource update: X models, Y vaes, Z samplers, W schedulers

All dropdowns in the Pipeline tab populate

No duplicate status widgets

No “Disconnected / Ready” contradictory states

WebUI is fully usable (txt2img works by clicking RUN)

Forbidden files untouched

🛑 Rollback Plan

If this PR misbehaves:

Restore snapshot StableNew-snapshot-20251129-075009.zip

Delete modified files

Remove added test

Re-run Phase-1 smoke tests

Validate GUI launch & WebUI bootstrap manually

Rollback is clean because PR-028 only adds non-invasive controller/view wiring.

📘 References

Active Modules list

V2 GUI Redesign Summary (three-tab layout, dropdowns in Pipeline tab)

PR Template / Guardrails

Self-Discipline Protocol for V2 PRs