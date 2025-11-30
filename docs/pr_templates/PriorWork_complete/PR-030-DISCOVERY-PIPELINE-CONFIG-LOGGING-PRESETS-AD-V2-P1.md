PR-030-DISCOVERY-PIPELINE-CONFIG-LOGGING-PRESETS-AD-V2-P1 (Codex-ready spec)

If your numbering is different, feel free to rename the PR ID; the rest of the content still stands.

1. Title

PR-030-DISCOVERY-PIPELINE-CONFIG-LOGGING-PRESETS-AD-V2-P1

2. Summary

Read-only discovery PR to:

Map the V2 pipeline config panel and its correct home in the Pipeline tab left column.

Confirm how the bottom logging panel (LogTracePanelV2) is supposed to be wired and which handler feeds it.

Trace the preset dropdown → ConfigManager → presets/ folder path and why the GUI is not seeing existing presets.

Locate and classify all ADetailer-related files (GUI, pipeline stages, config) and recommend a V2 placement.

Produce a single markdown doc capturing “should use” vs “legacy/no longer use” files so the follow-on implementation PRs are tight and safe.

No behavior changes, no wiring changes. One new discovery doc only.

3. Problem Statement

From the current GUI:

The pipeline left-column config panel (core model/sampler/steps, stage toggles, etc.) is not visible in the Pipeline tab, despite V2 classes existing (SidebarPanelV2, CoreConfigPanelV2, OutputSettingsPanelV2, etc.).

The bottom logging panel is not surfaced; LogTracePanelV2 is constructed conditionally in MainWindowV2 based on gui_log_handler, but behavior is inconsistent and the user can’t see WebUI logs.

The preset dropdown doesn’t show any options even though presets/ contains multiple JSON presets and SidebarPanelV2 is wired to ConfigManager.list_presets().

ADetailer behavior (and possibly its stage/config) is missing from the Pipeline stages; we don’t yet have a clear map of where its V2 stage card or pipeline stage lives, or if it’s still only present in V1/hybrid code.

We need a clear, file-level map before we start rewiring, to avoid more Frankenstein behavior.

4. Goals

Config panel mapping (left column, Pipeline tab)

Identify the canonical V2 components for:

Core config (model/vae/sampler/steps/cfg): CoreConfigPanelV2.

Sidebar container & stage toggles: SidebarPanelV2.

Output settings / global negative / prompt packs in that sidebar.

Determine which file is the active sidebar:

src/gui/sidebar_panel_v2.py vs src/gui/panels_v2/sidebar_panel_v2.py.

Confirm how PipelineTabFrame / PipelineTabFrameV2 and LayoutManagerV2 are supposed to host that sidebar as the Pipeline-tab left column, not the global LeftZone.

Bottom logging panel mapping

Trace where LogTracePanelV2 is defined and how it’s instantiated in MainWindowV2 (bottom_zone + gui_log_handler).

Identify the logging stack:

InMemoryLogHandler, GUI log sink, controller wiring, and how log records are supposed to land in the bottom panel (and in which tab(s)).

Enumerate any legacy log panels or competing status/log widgets we should not keep using in V2.

Presets dropdown & ConfigManager

Map the full path from:

SidebarPanelV2 preset dropdown → ConfigManager.list_presets() / load_preset() → presets/ directory.

Confirm:

Where ConfigManager is instantiated (currently inside SidebarPanelV2).

Which base path it uses and why it might not be resolving C:\Users\rob\projects\StableNew\presets on your machine.

Identify whether there is any older preset loader (e.g., legacy config_panel.py / other GUI) still in play that we should explicitly mark as legacy-only.

ADetailer discovery

Using the inventory, locate:

Any files with adetailer in the name or content (e.g., adetailer_stage, adetailer_config, stage card files that mention ADetailer).

Classify:

Pipeline-level ADetailer stage (if exists): stage class, config schema, StageSequencer integration.

GUI-level ADetailer controls: stage card(s) under src/gui/stage_cards_v2/ or older V1 structures.

Write a recommendation (in the doc) for V2:

Treat ADetailer as a dedicated stage in the pipeline (txt2img → adetailer → upscale).

Use a toggle + confidence threshold to enable “auto when faces/hands found” as a future PR.

Note any migration tasks needed (e.g., migrating options out of generic img2img card into separate ADetailer card).

Produce a single discovery document

Create docs/discovery/PIPELINE_CONFIG_LOGGING_PRESETS_ADetailer_DISCOVERY_V2-P1.md that:

Lists canonical V2 files for:

Pipeline left-column config.

Bottom logging panel.

Presets integration.

(If present) ADetailer pipeline & GUI.

Lists legacy/no-longer-should-be-used files for the same concerns (V1/hybrid).

Outlines follow-on implementation PRs, each scoped narrowly (e.g., “PR-03x Pipeline left-column wiring”, “PR-03y Bottom logging surfacing”, “PR-03z Presets hookup”, “PR-04x ADetailer stage & GUI”).

5. Non-goals

No changes to runtime behavior, pipeline execution, or actual GUI wiring.

No new stages or rewriting of StageSequencer or pipeline_runner.

No changes to MainWindowV2 layout/grid behavior beyond what’s needed to understand it.

No refactors of ConfigManager implementation; only documentation of how it behaves today.

No addition/removal of ADetailer logic; only discovery and recommendations.

6. Allowed Files

Read-only for all code; write only to the discovery doc path.

Docs (write)

docs/discovery/PIPELINE_CONFIG_LOGGING_PRESETS_ADetailer_DISCOVERY_V2-P1.md (new)

GUI V2 (read-only)

src/gui/main_window_v2.py (zones, bottom log, status bar, tabs)

src/gui/layout_v2.py (root grid / zone layout)

src/gui/sidebar_panel_v2.py and src/gui/panels_v2/sidebar_panel_v2.py (sidebar, presets, core config)

src/gui/core_config_panel_v2.py (core config fields + adapters)

src/gui/output_settings_panel_v2.py, src/gui/prompt_pack_panel_v2.py, src/gui/prompt_pack_list_manager.py (sidebar stack)

src/gui/log_trace_panel_v2.py (bottom logging panel)

src/gui/status_bar_v2.py (status + WebUI indicators)

src/gui/views/pipeline_tab_frame_v2.py (Pipeline tab container)

src/gui/stage_cards_v2/* (txt2img/img2img/upscale stage cards; check for any ADetailer hooks).

Controller / pipeline (read-only)

src/controller/app_controller.py (logging, presets, WebUI client, resource refresh)

src/controller/webui_connection_controller.py (WebUI lifecycle, ready callback).

src/pipeline/stage_sequencer.py, src/pipeline/pipeline_runner.py (stages & ordering).

Config / presets (read-only)

src/utils/config.py (ConfigManager)

presets/* (already in repo_inventory).

ADetailer candidates (read-only)

Any files in the inventory whose paths or content contain adetailer/ADetailer.

7. Forbidden Files

No edits, only read:

src/gui/main_window_v2.py (layout/wiring)

src/gui/theme_v2.py

src/main.py

src/pipeline/executor.py / any central pipeline runner entrypoint

Any *_OLD.py or archived legacy files (except to classify them in the doc)

8. Step-by-step Implementation

Inventory scan (no code edits)

Use repo_inventory.json to:

List all *sidebar_panel_v2*.py, *core_config_panel_v2.py, *log_trace_panel_v2.py, *status_bar_v2.py, *pipeline_tab_frame*, *stage_cards_v2*, *adetailer*.

Confirm presence of presets/*.json so we know the data exists.

Config panel & Pipeline tab mapping (read-only)

In SidebarPanelV2:

Document how the packs section, presets section, and CoreConfigPanelV2 are built and arranged.

Note methods like get_core_config_panel, refresh_core_config_from_webui, get_core_overrides, get_resolution.

In PipelineTabFrameV2 and LayoutManagerV2:

Describe how the left/center/right columns are created and which widget is expected to occupy the Pipeline-tab left column.

Confirm how MainWindowV2 currently treats left_zone / right_zone compatibility hooks.

Bottom logging panel discovery

In main_window_v2.py:

Document how LogTracePanelV2 is created under bottom_zone when gui_log_handler is present.

List any other widgets attached to bottom_zone (status bar, etc.) to explain duplicate status displays.

In the logging stack:

Identify which logger(s) feed gui_log_handler and where they’re attached (likely via AppController / GUI bootstrap).

Presets & ConfigManager path

In SidebarPanelV2:

Trace the preset section: ConfigManager(), list_presets(), load_preset(), and _on_preset_selected.

In src/utils/config.py:

Document how ConfigManager determines the root path for presets (cwd vs repo root vs env vars).

Cross-check with presets/ contents from inventory to confirm the expected filenames and whether naming aligns.

ADetailer discovery

Search for adetailer/ADetailer in:

src/pipeline/*

src/gui/stage_cards_v2/*

Any *_config, *_stage, or integration tests.

For each hit, classify:

Active V2 candidate vs legacy/hybrid.

Whether it plugs into StageSequencer or only exists as GUI metadata.

Summarize recommended V2 placement:

New stage card: AdvancedADetailerStageCardV2 (or similar) as separate from generic img2img.

Pipeline stage: ADetailerStageV2 invoked after txt2img under control of stage toggles and the confidence threshold.

Write the discovery doc

Create docs/discovery/PIPELINE_CONFIG_LOGGING_PRESETS_ADetailer_DISCOVERY_V2-P1.md with sections:

Overview & context.

Pipeline left-column config panel mapping.

Bottom logging panel mapping.

Presets pipeline (GUI → ConfigManager → presets dir).

ADetailer: findings & recommended design.

Proposed follow-on PRs:

PR-A: Wire SidebarPanelV2 into Pipeline tab left column, remove legacy LeftZone pack loader.

PR-B: Surface LogTracePanelV2 predictably and dedupe status indicators.

PR-C: Make presets dropdown fully functional (ConfigManager path + load/apply).

PR-D: Implement ADetailer as a dedicated stage (GUI + pipeline).

9. Required Tests (Failing first)

This PR is doc-only; no new tests. But the doc should explicitly list tests that will become relevant for the follow-on implementation PRs, for example:

tests/gui_v2/test_gui_v2_workspace_tabs_v2.py (for seeing sidebar + logging attached properly).

tests/utils/test_logger_integration.py / tests/gui_v2/test_gui_logging_integration.py (for log routing).

Any future test_sidebar_presets_v2.py or test_adetailer_stage_v2.py we plan to add.

10. Acceptance Criteria

docs/discovery/PIPELINE_CONFIG_LOGGING_PRESETS_ADetailer_DISCOVERY_V2-P1.md exists and:

Clearly identifies canonical V2 vs legacy components for:

Pipeline left-column config.

Bottom logging.

Presets.

ADetailer.

Proposes at least 3–4 small follow-on PRs with tight scopes.

No code behavior changed (diff limited to the new doc).

All existing tests still pass (or skip exactly as before).

11. Rollback Plan

Delete docs/discovery/PIPELINE_CONFIG_LOGGING_PRESETS_ADetailer_DISCOVERY_V2-P1.md.

No runtime code touched, so rollback is trivial.

12. Codex Execution Constraints

Do not modify any .py files for this PR.

All analysis must be done using:

repo_inventory.json

Snapshot zip contents (read-only)

Only create/update the single markdown doc listed in Allowed Files.

Do not rename, move, or delete any existing files.

Do not reclassify modules in ACTIVE_MODULES.md / LEGACY_CANDIDATES.md in this PR; only reference them in the doc if helpful.

13. Smoke Test Checklist

Even though this PR is doc-only, Codex should still:

Run python -m pytest -q (or the standard test command) and confirm:

No new failures related to imports or path changes.

Optionally run python -m src.main locally to ensure:

GUI still boots.

No new Tk/logging exceptions appear.