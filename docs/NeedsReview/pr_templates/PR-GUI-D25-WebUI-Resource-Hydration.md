EXECUTOR ACKNOWLEDGEMENT & COMPLIANCE BLOCK (MANDATORY)

You are acting as an Executor for the StableNew v2.6 codebase.

By proceeding, you explicitly acknowledge the attached StableNew_v2.6_Canonical_Execution_Contract.md and agree it is authoritative.

If you cannot comply with all requirements below, STOP.

PR METADATA
PR ID

PR-GUI-D25-WebUI-Resource-Hydration

Related Canonical Sections (Execution Contract)

§3.1 Proof Requirement

§4.1 NJR Is Canonical (PipelineConfig forbidden in execution)

§10 Diagnostics & Watchdog (must not regress UI stall detection)

§11.1 Required Tests (Golden Path tests must run and output shown)

INTENT (MANDATORY)
What this PR DOES

Restores a single, deterministic resource hydration chain:
WebUIConnectionController → AppController → (GUI thread) → Pipeline tab → DropdownLoaderV2 → dropdown widgets

Ensures there is exactly one authoritative pipeline tab instance accessible via main_window.pipeline_tab, so resource updates always target the correct UI.

Ensures dropdown widgets (models / VAEs / samplers / schedulers / upscalers) populate after WebUI connects and resources are fetched.

What this PR DOES NOT DO

Does NOT modify NJR, queue semantics, runner behavior, pipeline execution, or job formats.

Does NOT introduce new execution entrypoints.

Does NOT re-introduce PipelineConfig into runtime execution.

Does NOT refactor the UI layout or redesign panels.

SCOPE OF CHANGE (EXPLICIT)
Allowed Files Table (Executor may touch ONLY these files)
Allowed File	Change Type	Why
src/controller/webui_connection_controller.py	MODIFY	Emit a single “resources updated” callback when models/options are ready/refreshed
src/controller/app_controller.py	MODIFY	Subscribe to resources-updated signal and dispatch UI hydration via GUI-thread dispatcher
src/gui/main_window_v2.py	MODIFY	Guarantee single authoritative self.pipeline_tab and ensure controller targets it
src/gui/pipeline_panel_v2.py	MODIFY	Provide apply_webui_resources(resources) entrypoint for dropdown hydration
src/gui/sidebar_panel_v2.py	MODIFY	Ensure pipeline dropdown host widgets are reachable / registered; expose pipeline_config_panel if present
src/gui/dropdown_loader_v2.py	MODIFY	Implement/confirm apply(resources) populates dropdown values deterministically
src/gui/panels_v2/pipeline_config_panel_v2.py	MODIFY (ONLY IF NEEDED)	Import shim only if tests require this module path
Files TO BE DELETED (REQUIRED)

None

Files VERIFIED UNCHANGED (Executor MUST NOT TOUCH)

src/pipeline/**

src/queue/**

src/controller/job_service.py

Any runner/executor files

Any tests outside the list in “Test Plan” unless required to fix failures caused by this PR

ARCHITECTURAL COMPLIANCE

 NJR-only execution path untouched (§4.1)

 No PipelineConfig added to execution paths (§4.1)

 GUI updates marshaled to GUI thread (must not increase UI stall events) (§10)

 Proof + tests required (§3.1, §11.1)

IMPLEMENTATION STEPS (ORDERED, NON-OPTIONAL)
Step 0 — Preflight discovery (MANDATORY; no code changes yet)

Run these commands and keep outputs for proof:

git status --short
git grep -n "WebUIConnectionController" -n src/controller
git grep -n "apply_webui_resources" -n src/gui || true
git grep -n "DropdownLoaderV2" -n src/gui
git grep -n "pipeline_tab" -n src/gui/main_window_v2.py


If any of these grep results show existing implementations, you must reuse them and only fix wiring gaps (no refactor).

Step 1 — webui_connection_controller.py: emit “resources updated” once resources exist

File: src/controller/webui_connection_controller.py

Add a single registration method (if not already present):

set_on_resources_updated(self, cb)

Identify the exact location where resources are considered ready:

Search within the file for one of these strings (use what exists):

"models/options are ready"

"Retrieved"

"Resource update"

calls to the API client such as get_models, get_vaes, get_samplers, get_schedulers, get_upscalers

or a method that clearly refreshes resources

At the end of the “resources refreshed / fetched” block, call:

self._on_resources_updated(resources) only if callback is set.

Hard requirements

Do NOT change resource structures.

Do NOT add threads here.

Do NOT touch Tk/GUI.

Proof requirement

Provide the file+line range where callback is invoked.

Step 2 — app_controller.py: subscribe and dispatch to GUI thread

File: src/controller/app_controller.py

Locate where WebUIConnectionController is constructed or stored on the controller.

Register the callback from Step 1:

webui_connection_controller.set_on_resources_updated(self._on_webui_resources_updated)

Implement _on_webui_resources_updated(self, resources) that MUST:

call self._run_in_gui_thread(lambda: self._apply_webui_resources(resources))

Implement _apply_webui_resources(self, resources) that MUST:

find the authoritative pipeline tab via: self.main_window.pipeline_tab

call: pipeline_tab.apply_webui_resources(resources) if method exists

do nothing otherwise (but log a warning once)

Hard requirements

Do NOT touch Tk widgets directly here.

Do NOT call DropdownLoaderV2 here.

Must route through _run_in_gui_thread (compat dispatcher).

Proof requirement

Provide the exact function names and show the dispatch call.

Step 3 — main_window_v2.py: enforce single authoritative pipeline_tab

File: src/gui/main_window_v2.py

Locate where tabs are built and assigned (Prompt/Pipeline/Learning).

Ensure:

pipeline tab is created exactly once

stored as: self.pipeline_tab

no second pipeline panel object exists that the controller could accidentally reference

Allowed mechanism (deterministic, minimal)

If duplicates are possible in current code, add a simple guard:

If self.pipeline_tab already exists, do not create another.

Hard requirements

Do NOT delete other tabs.

Do NOT restructure notebooks.

Do NOT “prefer the last one”; keep first authoritative and consistently referenced by self.pipeline_tab.

Proof requirement

Provide file+line range showing self.pipeline_tab = ... and the guard.

Step 4 — pipeline_panel_v2.py: add apply_webui_resources(resources)

File: src/gui/pipeline_panel_v2.py

Add method:

apply_webui_resources(self, resources)

Implementation MUST:

create/use DropdownLoaderV2

apply values to dropdown widgets owned by the pipeline UI

preserve selection if still valid

otherwise select a safe default (first item) only if current value is invalid/empty

Hard requirements

No controller logic in this method.

No network/API calls.

No threads.

Proof requirement

Provide function definition line range.

Step 5 — sidebar_panel_v2.py: ensure the dropdown host is reachable

File: src/gui/sidebar_panel_v2.py

Ensure the pipeline config section (where dropdown widgets live) is not hidden behind an unreferenced local variable.

If a config panel object exists, expose it as:

self.pipeline_config_panel = <instance>

Ensure pipeline panel’s apply_webui_resources() can reach the correct widgets:

Either by direct references or by an internal registration function used by DropdownLoaderV2.

Hard requirements

Do NOT instantiate dummy panels solely for tests.

Do NOT wrap this in try/except that hides failures.

Proof requirement

Show self.pipeline_config_panel = ... assignment if applicable.

Step 6 — dropdown_loader_v2.py: implement deterministic apply(resources)

File: src/gui/dropdown_loader_v2.py

Ensure DropdownLoaderV2 has apply(resources) (create it if missing).

It MUST set dropdown values for at least:

models

VAEs

samplers

schedulers

upscalers

It MUST:

preserve current selection if present in new list

otherwise pick first entry (only when required)

be safe to call repeatedly

Hard requirements

Must not depend on controller.

Must not call WebUI APIs.

Must not cache in a way that prevents refresh.

Step 7 — Optional import shim for legacy test import path (ONLY if tests fail)

File: src/gui/panels_v2/pipeline_config_panel_v2.py (ONLY if needed)

If tests/gui_v2/test_pipeline_layout_scroll_v2.py imports this module path and fails:

Create/revise module to re-export the canonical panel class

No behavior changes, no widget creation tricks

If tests already pass without this, DO NOT touch it.

TEST PLAN (MANDATORY)
Required Local Tests for This PR (run exactly)
python -m pytest -q tests/gui_v2/test_pipeline_left_column_config_v2.py
python -m pytest -q tests/gui_v2/test_pipeline_layout_scroll_v2.py
python -m pytest -q tests/gui_v2/test_pipeline_config_panel_lora_runtime.py
python -m pytest -q tests/gui_v2/test_pipeline_stage_checkbox_order_v2.py
python -m pytest -q tests/gui_v2
python -m pytest -q tests/controller tests/queue tests/gui_v2

Golden Path Tests REQUIRED by Canonical Execution Contract §11.1 (MUST RUN + SHOW OUTPUT)
python -m pytest -q tests/journeys/test_jt01_prompt_pack_authoring.py
python -m pytest -q tests/journeys/test_jt03_txt2img_pipeline_run.py
python -m pytest -q tests/journeys/test_jt06_prompt_pack_queue_run.py
python -m pytest -q tests/gui_v2/test_main_window_smoke_v2.py
python -m pytest -q tests/system/test_watchdog_ui_stall.py

VERIFICATION & PROOF (MANDATORY)
git diff
git diff

git status
git status --short

Forbidden Symbol Check (Contract §4.1)
git grep -n "PipelineConfig" src/ || true


(Allowed: type hints in legacy/view-only areas ONLY. Not allowed: any new execution usage.)

Wiring Proof

Executor must include grep outputs showing the chain exists:

git grep -n "set_on_resources_updated" -n src/controller/webui_connection_controller.py
git grep -n "_on_webui_resources_updated" -n src/controller/app_controller.py
git grep -n "apply_webui_resources" -n src/gui/pipeline_panel_v2.py
git grep -n "pipeline_tab" -n src/gui/main_window_v2.py

GOLDEN PATH CONFIRMATION (MANDATORY)

Executor must confirm (with either test evidence or manual run notes):

Launch app: python -m src.main

WebUI connects and resource fetch happens

Dropdowns populate after connect

Add-to-Job does not freeze UI (no repeated UI stall bundles)

FINAL DECLARATION (REQUIRED)

This PR:

 Fully implements declared scope (all required files modified as specified)

 Touches only Allowed Files

 Passes all required tests (including §11.1) with output shown

 Includes verifiable proof (diff/status/grep/tests)

If any box cannot be checked, STOP and report the precise blocker.