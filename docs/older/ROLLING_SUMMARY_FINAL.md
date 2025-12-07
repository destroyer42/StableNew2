# ROLLING_SUMMARY

> Short, cumulative summary of major changes.
> Keep this file brief: aim for bullet points, not essays.

---

## 2025-11-22 (v1 bootstrap)

- Established `docs/codex_context/` as the single source of truth for AI assistants.
- Defined v2 architecture: GUI  controller  pipeline  api  learning.
- Formalized pipeline rules (stages, adetailer as explicit stage, upscale invariants).
- Summarized Learning v2: builder + JSONL writer + execution runner/controller.

## 2025-11-22 (queue persistence)

- Added JobHistoryStore (JSONL) to persist queue submissions and lifecycle changes.
- Added JobHistoryService so controllers/GUI can read active + historical job view models.
- Queue now records lifecycle transitions to history without changing scheduling semantics.

## 2025-11-22 (GUI job history)

- Added a read-only GUI V2 Job History & Active Queue panel powered by JobHistoryService.
- Integrated the panel into AppLayoutV2 without altering existing prompt/pipeline flows.
- New GUI tests cover rendering, empty states, and refresh wiring via a fake service.

## 2025-11-22 (GUI job actions)

- Added Cancel/Retry controls to the Jobs/Queue panel, wired through JobHistoryService and queue controller APIs.
- Controller-side job actions validate status (cancel queued/running; retry completed/failed/cancelled) and submit via existing queue pathways.
- GUI tests verify action enablement and controller invocation; docs note controller-only job action flow.

## 2025-11-22 (Cluster worker registry)

- Defined WorkerDescriptor/WorkerStatus and an in-memory WorkerRegistry with a default local worker.
- Jobs and job history now carry an optional worker_id to prepare for worker-aware scheduling.
- Added ClusterController facade plus tests for registry/worker lifecycle; no change to single-node behavior yet.

## 2025-11-22 (Queue-backed run integration)

- Completed the **queue-backed execution path** by wiring `QueueExecutionController` into `PipelineController` with a `queue_execution_enabled` feature flag, enabling Run/Stop to operate on queued jobs when enabled.
- Added job status → controller lifecycle mapping (QUEUED/RUNNING/COMPLETED/FAILED/CANCELLED), ensuring that queued runs drive the same lifecycle states and GUI updates as direct runs.
- Expanded controller and GUI V2 tests to validate queue-mode toggling, job-id tracking, and cancellation, without regressing default direct-execution behavior.

---

## 2025-11-22 (Assembler enforcement)

- `PipelineController.start_pipeline` now builds `PipelineConfig` immediately through `PipelineConfigAssembler`, eliminating the legacy `pipeline_func` shortcut and submitting the assembled config to queue/direct runners.
- State-driven overrides plus learning/randomizer metadata are extracted (when present) before assembly so tests can monkeypatch the assembler and observe calls.
- Architecture/Rule docs highlight the assembler as the required entry point for production runs.

---

## 2025-11-22 (Pipeline command bar)

> **PR-#48-GUI-V2-CommandBar-RunStopQueue-001** – Introduced a dedicated PipelineCommandBarV2 widget to host Run, Stop, and Queue mode controls inside PipelinePanelV2. StableNewGUI still exposes `run_button` for tests, but the primary pipeline actions are now grouped into a single command bar, aligning with the GUI V2 layout plan and button-placement guidance. Queue mode toggle is surfaced via the command bar using existing app_config/controller plumbing; no pipeline or controller semantics changed. New GUI V2 tests cover command bar existence and queue toggle behavior.

---

## 2025-11-22 (Advanced prompt editor overlay)

> **PR-#49-GUI-V2-AdvancedPromptEditor-001** – Added an AdvancedPromptEditorV2 widget and integrated it with the GUI V2 pipeline panel so users can edit prompts in a larger, focused text area. Opening the editor pre-fills from the current prompt input; applying changes feeds updated text back into the main pipeline prompt field(s) without changing pipeline or controller behavior. New GUI V2 tests cover editor callback behavior and prompt roundtrip between the pipeline panel and the advanced editor.

---

## 2025-11-22 (Prompt pack manager V2)

> **PR-#50-GUI-V2-PromptPackManager-Integration-001** - Added a PromptPackPanelV2 and supporting adapter to surface existing prompt packs in the GUI V2 sidebar. Users can browse packs and apply a selected pack's base prompt directly into the V2 pipeline prompt field, without changing pack formats or pipeline behavior. New GUI V2 tests cover prompt pack listing and "apply pack to prompt" roundtrips.

---

## 2025-11-22 (Core config panel V2)

> **PR-#51-GUI-V2-CoreConfigPanel-001** - Added a CoreConfigPanelV2 in the V2 sidebar to expose model, sampler, steps, CFG, and resolution presets. GuiOverrides and the PipelineConfigAssembler now carry these fields (including resolution presets -> width/height) without altering pipeline semantics. Controller/GUI tests cover the panel roundtrip and assembler mapping.

---

## 2025-11-22 (Negative prompt panel V2)

> **PR-#52-GUI-V2-NegativePromptPanel-001** - Added a NegativePromptPanelV2 in the V2 sidebar with clear/reset controls. GuiOverrides and the PipelineConfigAssembler now carry `negative_prompt` (stored in config metadata) so the negative prompt path is explicit without touching pipeline logic.

---

## 2025-11-22 (Advanced resolution controls V2)

> **PR-#53-GUI-V2-ResolutionAdvancedControls-001** - Added a ResolutionPanelV2 with width/height inputs, presets, ratios, and MP hints, integrated into the V2 sidebar/core config. GuiOverrides and PipelineConfigAssembler accept explicit resolution values and clamp via existing megapixel rules without changing pipeline semantics.

---

## How To Update

After each major PR or refactor, add 3-6 bullets:
- What changed
- Which modules were touched
- Any new invariants or rules

Keep old snapshots in `docs/codex_context/ARCHIVE/` when this file grows too large.

## 2025-11-23 (Output settings panel V2)

> **PR-#54-GUI-V2-OutputSettingsPanel-001** - Added OutputSettingsPanelV2 to the V2 sidebar with output directory/profile, filename pattern, image format, batch size, and seed mode controls. GuiOverrides and PipelineConfigAssembler carry these fields into `metadata["output"]`, keeping GUI file IO out of scope while making output configuration explicit. New GUI/controller tests cover the panel roundtrip and assembler mapping.

## 2025-11-23 (Model manager panel V2)

> **PR-#55-GUI-V2-ModelManagerPanel-001** - Added a ModelManagerPanelV2 in the V2 sidebar with model/checkpoint and VAE selectors plus refresh via ModelListAdapterV2. GuiOverrides and the assembler now carry model_name/vae_name, mapping the model into PipelineConfig.model and storing VAE/model metadata for downstream consumers. Tests cover the panel refresh/selection and assembler mapping.

## 2025-11-23 (WebUI bootstrap & gating)

> **PR-#56-CTRL-WEBUI-BOOTSTRAP-GUIHEALTH-001** - Made WebUI bootstrap non-blocking, added WebUIConnectionController with autostart+health retries, gated pipeline runs on WebUI readiness, and exposed WebUI status/reconnect in the GUI status panel. New controller/GUI tests cover connection workflow and run gating.

## 2025-11-23 (WebUI auto-detect & GUI controls)

> **PR-#57-CTRL-API-WEBUI-AUTODETECT-AUTOLAUNCH-001** - WebUI autostart now uses detection/config (no env var dependency) with defaults for workdir/command, plus controller-driven health checks. GUI status panel gains Launch/Retry buttons and runs remain gated on WebUI READY.

## 2025-11-23 (WebUI startup alignment)

> **PR-#58-MAIN-GUI-WEBUI-BOOTSTRAP-ALIGN-001** - main.py now uses app_config-driven WebUI autostart and schedules background connection via the controller. The V2 status panel with Launch/Retry is wired into the layout, and run controls reflect WebUI readiness.

## 2025-11-23 (V2 spine hardening & journey test)

- Added scrollable V2 layout with ThemeV2/LayoutV2 defaults, BaseStageCardV2 components, and migrated Txt2Img/Img2Img/Upscale V2 cards with validation helpers and smoke tests.
- AppStateV2 gained prompt/current_pack/run/status fields; StatusBarV2 syncs state text; ThemeV2/StageCard tests added.
- MainWindowV2 now wires real V2 panels, dark styles, and WebUI status; LayoutV2 sets sensible geometry. GuiInvoker ensures thread-safe Tk scheduling; cleanup hooks prevent teardown crashes; LogPanel is disposal-aware.
- Added `build_v2_app` factory to construct production V2 wiring with injectable runners, plus FakePipelineRunner and a full V2 journey test that drives AppController with a fake pipeline; main.py now boots via the factory.


## 2025-11-23 (Archive GUI-V1 Tests)
> **PR-02a-MOVE-GUI-V1-TESTS-TO-ARCHIVE** – Legacy GUI‑V1 tests migrated into `archive/tests_v1/`; V2 harness established as primary.

## 2025-11-23 (V2 App Spine)
> **PR-03-CREATE-V2-APP-SPINE** – Implemented core V2 application spine (`AppLayoutV2`, `panels_v2`, unified wiring) and main‑window integration.

## 2025-11-23 (Theme Engine V2)
> **PR-04-THEME-ENGINE-V2** – Centralized theming across V2 UI, including palette, typography, and style propagation for all V2 panels.

## 2025-11-23 (Scrollable Areas V2)
> **PR-05A-SCROLLABLE-AREAS-V2** – Added and integrated `ScrollableFrameV2` to Pipeline, Preview, and Sidebar panels for proper scroll behavior.

## 2025-11-23 (Layout & Resizing V2)
> **PR-05-LAYOUT-AND-RESIZING-V2** – Improved V2 window/panel resizing behavior; unified panel structure ensures dynamic layout adjustments.


## 2025-11-23 (BaseStageCardV2 foundation)
> **PR-06A-BASESTAGECARDV2-AND-COMPONENTS** – BaseStageCardV2 and shared stage components implemented; verified across Txt2Img, Img2Img, and Upscale panels.

## 2025-11-23 (Txt2Img migrated to StageCard V2)
> **PR-06B-MIGRATE-TXT2IMG-TO-STAGECARDV2** – Txt2Img migrated onto BaseStageCardV2 with consistent field mapping and panel/assembler alignment.

## 2025-11-23 (Img2Img & Upscale migrated to StageCard V2)
> **PR-06C-MIGRATE-IMG2IMG-AND-UPSCALE-TO-STAGECARDV2** – Img2Img and Upscale V2 cards refactored to use BaseStageCardV2; confirmed consistent metadata and UI wiring.

## 2025-11-23 (WebUI GUI Controls)
> **PR-00A-WEBUI-GUI-CONTROLS** – Implemented WebUI Launch/Retry controls surfaced directly in the GUI, consistent with WebUIConnectionController semantics.

## 2025-11-23 (Move Legacy V1 to Archive)
> **PR-02-MOVE-LEGACY-V1-TO-ARCHIVE** – Legacy V1 files and GUI modules moved to `archive/`; V2 directory structure confirmed as authoritative.


## 2025-11-23 (WebUI process manager separation)
> **PR-00-WEBUI-PROCESS-MANAGER-AND-AUTOSTART-SEPARATION** – Split WebUI process control into a dedicated `webui_process_manager` module with detection-based defaults, isolated process startup logic, and clean controller boundaries. Autostart and retry parameters moved to `app_config`, ensuring WebUIConnectionController handles only connection state and health.

## 2025-11-23 (Repo inventory & source-of-truth establishment)
> **PR-01-REPO-INVENTORY-AND-SOURCE-OF-TRUTH** – Established authoritative repo layout: V2 modules under `src/`, legacy V1 moved to `archive/`, and `docs/codex_context/` defined as the AI-assistant source of truth. Added `repo_inventory.json` and aligned directory hierarchy with the V2 architecture plan.
