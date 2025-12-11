# pipeline_config references (excluding archive/.git/zip)

## docs\ARCHITECTURAL_DEBT_ANALYSIS.md
- docs\ARCHITECTURAL_DEBT_ANALYSIS.md:33: # Legacy jobs imported from history still carry pipeline_config blobs.
- docs\ARCHITECTURAL_DEBT_ANALYSIS.md:34: job = Job(job_id="legacy", pipeline_config=None)
- docs\ARCHITECTURAL_DEBT_ANALYSIS.md:35: job.pipeline_config = PipelineConfig(...)
- docs\ARCHITECTURAL_DEBT_ANALYSIS.md:41: > **Status:** Restricted to legacy history imports (PR-CORE1-C2). New jobs never populate `pipeline_config`; any legacy payloads are rehydrated from history via the adapter.
- docs\ARCHITECTURAL_DEBT_ANALYSIS.md:200: - Status: Conflicts with pipeline_config, creates ambiguity
- docs\ARCHITECTURAL_DEBT_ANALYSIS.md:217: 1. **Pick ONE job type:** NormalizedJobRecord; pipeline_config-only jobs are retired and exist solely as legacy history blobs (PR-CORE1-C2).
- docs\ARCHITECTURAL_DEBT_ANALYSIS.md:348: - DTOs derive from `NormalizedJobRecord` snapshots, NOT from `pipeline_config`
- docs\ARCHITECTURAL_DEBT_ANALYSIS.md:350: - Legacy `pipeline_config` fallback preserved only for old jobs without NJR snapshots
- docs\ARCHITECTURAL_DEBT_ANALYSIS.md:365: - ❌ Removed: `pipeline_config` introspection for display purposes (new jobs)
- docs\ARCHITECTURAL_DEBT_ANALYSIS.md:366: - ✅ Preserved: `pipeline_config` execution path (unchanged per CORE1-A3 scope)
- docs\ARCHITECTURAL_DEBT_ANALYSIS.md:373: - No display logic introspects `pipeline_config`
- docs\ARCHITECTURAL_DEBT_ANALYSIS.md:379: - ✅ No fallback to `pipeline_config` for NJR-backed jobs (failures return error status)
- docs\ARCHITECTURAL_DEBT_ANALYSIS.md:382: - ⚠️ PR-CORE1-B3: _to_queue_job() clears pipeline_config, so NJR-only jobs never expose it
- docs\ARCHITECTURAL_DEBT_ANALYSIS.md:383: - ⏳ `pipeline_config` field still exists as **legacy debug field** for inspection
- docs\ARCHITECTURAL_DEBT_ANALYSIS.md:384: - ⏳ `pipeline_config` execution branch preserved for **legacy jobs only** (pre-v2.6, imported)
- docs\ARCHITECTURAL_DEBT_ANALYSIS.md:385: - **Remaining work: Full pipeline_config field/method removal (CORE1-C) - after legacy job migration complete**
- docs\ARCHITECTURAL_DEBT_ANALYSIS.md:405: | Execution payload | `pipeline_config` | `pipeline_config` | **Hybrid (NJR preferred)** | **NJR-only (new jobs, pipeline_config removed)** ✅ | NJR |
- docs\ARCHITECTURAL_DEBT_ANALYSIS.md:412: - ✅ CORE1-D1 migrates legacy history to NJR-only snapshots; history replay no longer depends on pipeline_config payloads.
- docs\ARCHITECTURAL_DEBT_ANALYSIS.md:413: - ƒo. PR-CORE1-B3 ensures _to_queue_job() clears pipeline_config, so new jobs carry only NJR snapshots
- docs\ARCHITECTURAL_DEBT_ANALYSIS.md:415: **Debt Resolved (CORE1-D1/D2/D3):** Legacy history formats, pipeline_config persistence, mixed-era draft-bundle records, schema drift, and multiple replay paths are eliminated; history_schema 2.6 is enforced on load/save via HistoryMigrationEngine + schema normalization, and replay is unified through NJR → RunPlan → PipelineRunner.run_njr.
- docs\ARCHITECTURAL_DEBT_ANALYSIS.md:421: 2. The GUI preview panel reads these normalized records directly, avoiding any legacy `pipeline_config` inspection whenever packs are present.
- docs\ARCHITECTURAL_DEBT_ANALYSIS.md:432: 1. `state/queue_state_v2.json` now stores NJR snapshots plus strict queue metadata (`queue_id`, `status`, `priority`, `created_at`, `queue_schema == "2.6"`, optional metadata, auto-run/paused flags). `_normalized_record`, `pipeline_config`, draft/bundle blobs, and other duplicated execution data are stripped so queue snapshots never diverge from NJR semantics.
- docs\ARCHITECTURAL_DEBT_ANALYSIS.md:437: - Debt removed: queue item schema drift, transitional `_normalized_record` field, pipeline_config remnants in persistence, and inconsistent queue/history summaries.

## docs\ARCHITECTURE_v2.6.md
- docs\ARCHITECTURE_v2.6.md:24: pipeline_config–derived jobs
- docs\ARCHITECTURE_v2.6.md:368: No pipeline_config jobs
- docs\ARCHITECTURE_v2.6.md:407: - All display data comes from NJR snapshots, NOT from pipeline_config
- docs\ARCHITECTURE_v2.6.md:416: → on failure → return error status (NO fallback to pipeline_config)
- docs\ARCHITECTURE_v2.6.md:418: This Job object no longer exposes a `pipeline_config` field; `_normalized_record` is the only execution payload carried between subsystems.
- docs\ARCHITECTURE_v2.6.md:422: Job (with only pipeline_config, no normalized_record) →
- docs\ARCHITECTURE_v2.6.md:424: → _run_pipeline_via_runner_only(pipeline_config) → PipelineRunner.run_njr(legacy NJR adapter)
- docs\ARCHITECTURE_v2.6.md:435: - If NJR execution fails, the job is marked as failed (no pipeline_config fallback)
- docs\ARCHITECTURE_v2.6.md:436: - The queue `Job` model no longer defines `pipeline_config`; new jobs never expose or persist this field (PR-CORE1-C2).
- docs\ARCHITECTURE_v2.6.md:437: - Any remaining `pipeline_config` payloads live in legacy history entries and are rehydrated via `legacy_njr_adapter.build_njr_from_legacy_pipeline_config()`.
- docs\ARCHITECTURE_v2.6.md:441: - The queue snapshot file (`state/queue_state_v2.json`) now records `queue_schema`, `queue_id`, `njr_snapshot`, `priority`, `status`, `created_at`, and lightweight metadata such as `source`/`prompt_source`. Every entry derives directly from the NJR snapshot and drops deprecated keys (`pipeline_config`, bundle summaries, draft blobs) before serialization so that the file always reflects canonical NJR data.
- docs\ARCHITECTURE_v2.6.md:450: | V2.0 Pre‑NJR | JSONL entries containing only `pipeline_config` blobs and ad-hoc `result` dictionaries | Legacy JSON queues with `pipeline_config` per job | Written entries are normalized with `HistoryMigrationEngine`, `QueueMigrationEngine`, and `legacy_njr_adapter` before execution |
- docs\ARCHITECTURE_v2.6.md:459: 3. `legacy_njr_adapter` remains the only adapter for deriving NJRs from pipeline_config-heavy records; replay requests rely entirely on the resulting NJRs plus the unified runner path.
- docs\ARCHITECTURE_v2.6.md:464: - The queue `Job` model no longer exposes `pipeline_config`; `PipelineController._to_queue_job()` instantiates NJR-only jobs without storing pipeline_config.
- docs\ARCHITECTURE_v2.6.md:465: - Queue/JobService/History treat `pipeline_config` as legacy metadata; only imported pre-v2.6 jobs may still store a non-null value via manual assignment.
- docs\ARCHITECTURE_v2.6.md:468: - Legacy `PipelineConfig` executions pass through `legacy_njr_adapter.build_njr_from_legacy_pipeline_config()` and then run through `run_njr`, ensuring the runner core only sees NJRs.
- docs\ARCHITECTURE_v2.6.md:474: - ✅ Display DTOs never introspect pipeline_config (use NJR snapshots)
- docs\ARCHITECTURE_v2.6.md:478: - ??O `pipeline_config` is removed from queue `Job` instances (PR-CORE1-C2); NJR snapshots are the only executable payloads.
- docs\ARCHITECTURE_v2.6.md:483: Legacy history formats are migrated in-memory to NJR snapshots via `HistoryMigrationEngine`. Replay paths no longer accept `pipeline_config` or draft-bundle structures; hydration is NJR-only.
- docs\ARCHITECTURE_v2.6.md:500: History → Restore replays job by reconstructing NJR from snapshot. History load is NJR hydration only; any legacy fields (pipeline_config, draft bundles) are stripped and normalized on load.
- docs\ARCHITECTURE_v2.6.md:501: **History Schema v2.6 (CORE1-D2):** History load = pure NJR hydration + schema normalization. Every persisted entry MUST contain: `id`, `timestamp`, `status`, `history_schema`, `njr_snapshot`, `ui_summary`, `metadata`, `runtime`. Deprecated fields (pipeline_config, draft/draft_bundle/job_bundle, legacy_* blobs) are forbidden and removed during migration. All entries are written in deterministic order; `history_schema` is always `2.6`.
- docs\ARCHITECTURE_v2.6.md:503: **Queue Schema v2.6 (CORE1-D5):** `state/queue_state_v2.json` mirrors History Schema v2.6 by storing `njr_snapshot` plus scheduling metadata (`queue_id`, `status`, `priority`, `created_at`, `queue_schema == "2.6"`, optional `metadata`, auto-run/paused flags). Deprecated fields such as `_normalized_record`, `pipeline_config`, `draft_bundle_summary`, `legacy_config_blob`, and any other duplicated execution data are stripped on load/save so queue snapshots never duplicate NJR state. Tests (`tests/queue/test_job_history_store.py`, `tests/pipeline/test_job_queue_persistence_v2.py`) now assert queue persistence only yields NJR-backed entries and that normalization remains idempotent.
- docs\ARCHITECTURE_v2.6.md:509: **Unified Replay Path (CORE1-D3):** Replay starts from a validated v2.6 HistoryRecord → hydrate NJR snapshot → build RunPlan via `build_run_plan_from_njr` → execute `PipelineRunner.run_njr(run_plan)` → return RunResult. No legacy replay branches, no pipeline_config rebuilds, no controller-local shortcuts. Fresh runs and replays share the exact NJR → RunPlan → Runner chain.
- docs\ARCHITECTURE_v2.6.md:606: pipeline_config or legacy config union models
- docs\ARCHITECTURE_v2.6.md:612: PromptPack-driven previews are now built via `PromptPackNormalizedJobBuilder` inside `PipelineController.get_preview_jobs()`: AppStateV2.job_draft.packs flow through the same NJR builder that execution uses, and the resulting records are stored in AppStateV2.preview_jobs so the GUI preview panel always renders prompt-pack-derived positive prompts/models without exposing pipeline_config or legacy drafts.
- docs\ARCHITECTURE_v2.6.md:704: - Tests and helpers construct Jobs from NJRs only; `pipeline_config=` job construction is removed from new paths.

## docs\Builder Pipeline Deep-Dive (v2.6).md
- docs\Builder Pipeline Deep-Dive (v2.6).md:367: - NJRs are the only execution payload produced by JobBuilderV2 for v2.6 jobs; pipeline_config is left None.
- docs\Builder Pipeline Deep-Dive (v2.6).md:368: - PipelineController._to_queue_job() attaches _normalized_record, sets pipeline_config = None, and builds NJR-driven queue/history snapshots.
- docs\Builder Pipeline Deep-Dive (v2.6).md:369: - Queue, JobService, Runner, and History rely on NJR snapshots for display/execution. Any non-null pipeline_config values belong to legacy pre-v2.6 data.
- docs\Builder Pipeline Deep-Dive (v2.6).md:371: Queue persistence output remains the JSON dump stored at `state/queue_state_v2.json`; D5 enforces that the file only ever contains NJR snapshots plus queue metadata (`queue_id`, `status`, `priority`, `created_at`, `queue_schema == "2.6"`, optional metadata, auto-run/paused flags) and no `_normalized_record`, pipeline_config, or bundle/draft keys. Queue persistence tests confirm this invariance, proving the queue file already mirrors history’s NJR schema even before D6 introduces the shared JSONL codec/format that will eventually let history and queue share the same serialization layer.

## docs\CORE1-D Roadmap — History Integrity, Persistence Cleanup(v2.6).md
- docs\CORE1-D Roadmap — History Integrity, Persistence Cleanup(v2.6).md:24: pipeline_config
- docs\CORE1-D Roadmap — History Integrity, Persistence Cleanup(v2.6).md:59: No history entry anywhere in the repo contains pipeline_config.
- docs\CORE1-D Roadmap — History Integrity, Persistence Cleanup(v2.6).md:367: No pipeline_config references anywhere.

## docs\E2E_Golden_Path_Test_Matrix_v2.6.md
- docs\E2E_Golden_Path_Test_Matrix_v2.6.md:578: - End-to-end queue tests no longer construct jobs with `pipeline_config=`; they wrap NormalizedJobRecord snapshots instead.

## docs\StableNew — Formal Strategy Document (v2.6).md
- docs\StableNew — Formal Strategy Document (v2.6).md:239: pipeline_config snapshots not aligned to NJR

## docs\StableNew_Coding_and_Testing_v2.6.md
- docs\StableNew_Coding_and_Testing_v2.6.md:380: Tests must not assert against legacy job DTOs (`JobUiSummary`, `JobQueueItemDTO`, `JobHistoryItemDTO`); controller and history tests should derive summaries via `JobView.from_njr()` (or `JobHistoryService.summarize_history_record()`) and never reconstruct pipeline_config fragments.
- docs\StableNew_Coding_and_Testing_v2.6.md:437: **FORBIDDEN:** Controllers, JobService, and Queue/Runner MUST NOT reference `pipeline_config` on `Job` instances; the field no longer exists in the queue model (PR-CORE1-C2).
- docs\StableNew_Coding_and_Testing_v2.6.md:439: **FORBIDDEN:** If NJR execution fails for an NJR-backed job, the execution path MUST NOT fall back to `pipeline_config`. The job should be marked as failed.
- docs\StableNew_Coding_and_Testing_v2.6.md:441: **LEGACY-ONLY:** `pipeline_config` execution branch is allowed ONLY for jobs without `_normalized_record` (imported from old history, pre-v2.6 jobs).
- docs\StableNew_Coding_and_Testing_v2.6.md:449: `pipeline_config` field no longer exists on Job objects created via JobBuilderV2; new jobs rely solely on NJR snapshots (PR-CORE1-C2). Legacy pipeline_config data lives only in history entries and is rehydrated via `legacy_njr_adapter.build_njr_from_legacy_pipeline_config()`.
- docs\StableNew_Coding_and_Testing_v2.6.md:451: **PR-CORE1-B4:** `PipelineRunner.run(config)` no longer exists. Tests (both unit and integration) must exercise `run_njr()` exclusively and may rely on the legacy adapter if they need to replay pipeline_config-only data.
- docs\StableNew_Coding_and_Testing_v2.6.md:459: Tests MUST verify that NJR execution failures result in job error status (NO fallback to pipeline_config).
- docs\StableNew_Coding_and_Testing_v2.6.md:460: Tests MUST verify that new queue jobs do not expose a `pipeline_config` field (PR-CORE1-C2); any legacy coverage should work through history data only.
- docs\StableNew_Coding_and_Testing_v2.6.md:461: Tests covering queue persistence (`tests/queue/test_job_queue_persistence_v2.py`, `tests/queue/test_job_history_store.py`) must inspect `state/queue_state_v2.json` and assert every entry ships with `njr_snapshot` plus queue metadata only (`queue_id`, `priority`, `status`, `created_at`, optional auto-run/paused flags) and that forbidden keys like `pipeline_config`, `_normalized_record`, or `draft`/`bundle` blobs never survive serialization; this proves queue I/O already matches history’s NJR semantics until D6 unifies the queue file with history’s JSONL codec.
- docs\StableNew_Coding_and_Testing_v2.6.md:463: Tests MUST NOT reference `pipeline_config` or legacy job dicts in persistence/replay suites; all history-oriented tests hydrate NJRs from snapshots.
- docs\StableNew_Coding_and_Testing_v2.6.md:474: Tests for legacy jobs (without NJR) MUST verify `pipeline_config` branch still works.

## docs\older\ARCHITECTURE_v2_COMBINED.md
- docs\older\ARCHITECTURE_v2_COMBINED.md:319: `pipeline_runner.run_full_pipeline(pipeline_config, logger=..., callbacks=...)`

## docs\older\ChatGPT-WhyNoPipeline.md
- docs\older\ChatGPT-WhyNoPipeline.md:65: 'src/gui/views/pipeline_config_panel.py',
- docs\older\ChatGPT-WhyNoPipeline.md:1265: 174         if hasattr(self, "pipeline_tab") and hasattr(self.pipeline_tab, "pipeline_config_panel"):
- docs\older\ChatGPT-WhyNoPipeline.md:1267: 176                 self.pipeline_tab.pipeline_config_panel.controller = controller
- docs\older\ChatGPT-WhyNoPipeline.md:1576: 1259         is_valid, message = self._validate_pipeline_config()
- docs\older\ChatGPT-WhyNoPipeline.md:1625: 1304             pipeline_config = self.build_pipeline_config_v2()
- docs\older\ChatGPT-WhyNoPipeline.md:1627: 1306             executor_config = self.pipeline_runner._build_executor_config(pipeline_config)
- docs\older\ChatGPT-WhyNoPipeline.md:1628: 1307             self._cache_last_run_payload(executor_config, pipeline_config)
- docs\older\ChatGPT-WhyNoPipeline.md:1629: 1308             self.pipeline_runner.run(pipeline_config, cancel_token, self._append_log_threadsafe)
- docs\older\ChatGPT-WhyNoPipeline.md:1657: 1185     def _run_pipeline_via_runner_only(self, pipeline_config: PipelineConfig) -> Any:
- docs\older\ChatGPT-WhyNoPipeline.md:1662: 1190         executor_config = runner._build_executor_config(pipeline_config)
- docs\older\ChatGPT-WhyNoPipeline.md:1663: 1191         self._cache_last_run_payload(executor_config, pipeline_config)
- docs\older\ChatGPT-WhyNoPipeline.md:1664: 1192         return runner.run(pipeline_config, None, self._append_log_threadsafe)
- docs\older\ChatGPT-WhyNoPipeline.md:1860: 1051         is_valid, message = self._validate_pipeline_config()
- docs\older\ChatGPT-WhyNoPipeline.md:1884: 1072         pipeline_config = self.build_pipeline_config_v2()
- docs\older\ChatGPT-WhyNoPipeline.md:1888: 1076         result = self.pipeline_controller.run_pipeline(pipeline_config)
- docs\older\ChatGPT-WhyNoPipeline.md:1891: 1079     def _execute_pipeline_via_runner(self, pipeline_config: PipelineConfig) -> Any:
- docs\older\ChatGPT-WhyNoPipeline.md:1898: 1086         result = runner.run(pipeline_config, self.pipeline_controller.cancel_token, self._append_log_threadsafe)
- docs\older\ChatGPT-WhyNoPipeline.md:1901: 1089     def _run_pipeline_from_tab(self, pipeline_tab: Any, pipeline_config: PipelineConfig) -> Any:
- docs\older\ChatGPT-WhyNoPipeline.md:1928: 1116         return self._run_pipeline_via_runner_only(pipeline_config)
- docs\older\ChatGPT-WhyNoPipeline.md:1977: 1304             pipeline_config = self.build_pipeline_config_v2()
- docs\older\ChatGPT-WhyNoPipeline.md:1979: 1306             executor_config = self.pipeline_runner._build_executor_config(pipeline_config)
- docs\older\ChatGPT-WhyNoPipeline.md:1980: 1307             self._cache_last_run_payload(executor_config, pipeline_config)
- docs\older\ChatGPT-WhyNoPipeline.md:1981: 1308             self.pipeline_runner.run(pipeline_config, cancel_token, self._append_log_threadsafe)
- docs\older\ChatGPT-WhyNoPipeline.md:2011: 1304             pipeline_config = self.build_pipeline_config_v2()
- docs\older\ChatGPT-WhyNoPipeline.md:2013: 1306             executor_config = self.pipeline_runner._build_executor_config(pipeline_config)
- docs\older\ChatGPT-WhyNoPipeline.md:2014: 1307             self._cache_last_run_payload(executor_config, pipeline_config)
- docs\older\ChatGPT-WhyNoPipeline.md:2015: 1308             self.pipeline_runner.run(pipeline_config, cancel_token, self._append_log_threadsafe)
- docs\older\ChatGPT-WhyNoPipeline.md:2049: from src.controller.pipeline_config_assembler import PipelineConfigAssembler, GuiOverrides, RunPlan, PlannedJob
- docs\older\ChatGPT-WhyNoPipeline.md:2497: Perhaps validation is failing, causing an early return in on_run_clicked due to _validate_pipeline_config, but the user didn’t mention seeing any error messages. Maybe the run button still points to the old start_run, not start_run_v2.
- docs\older\ChatGPT-WhyNoPipeline.md:2500: The internal _start_run_v2 directly uses the pipeline_controller, while on_run_clicked calls _run_pipeline_thread, which uses pipeline_runner.run without relying on a job queue. However, _run_pipeline_thread still constructs pipeline_config via build_pipeline_config_v2, so that should be fine.
- docs\older\ChatGPT-WhyNoPipeline.md:3229: 385             config = self._build_pipeline_config_from_state()
- docs\older\ChatGPT-WhyNoPipeline.md:3268: 385             config = self._build_pipeline_config_from_state()
- docs\older\ChatGPT-WhyNoPipeline.md:3340: I ran into an index issue again, but I've already seen run_pipeline. Now I’m wondering how PipelineController is used by AppController._run_via_pipeline_controller. This method seems to build the pipeline_config using self.build_pipeline_config_v2() and likely decides between direct and queue run-modes. I’ll check lines 1075-1116 to be sure.
- docs\older\ChatGPT-WhyNoPipeline.md:3350: 1072         pipeline_config = self.build_pipeline_config_v2()
- docs\older\ChatGPT-WhyNoPipeline.md:3354: 1076         result = self.pipeline_controller.run_pipeline(pipeline_config)
- docs\older\ChatGPT-WhyNoPipeline.md:3357: 1079     def _execute_pipeline_via_runner(self, pipeline_config: PipelineConfig) -> Any:
- docs\older\ChatGPT-WhyNoPipeline.md:3364: 1086         result = runner.run(pipeline_config, self.pipeline_controller.cancel_token, self._append_log_threadsafe)
- docs\older\ChatGPT-WhyNoPipeline.md:3367: 1089     def _run_pipeline_from_tab(self, pipeline_tab: Any, pipeline_config: PipelineConfig) -> Any:
- docs\older\ChatGPT-WhyNoPipeline.md:3394: 1116         return self._run_pipeline_via_runner_only(pipeline_config)
- docs\older\ChatGPT-WhyNoPipeline.md:5082: 174         if hasattr(self, "pipeline_tab") and hasattr(self.pipeline_tab, "pipeline_config_panel"):
- docs\older\ChatGPT-WhyNoPipeline.md:5084: 176                 self.pipeline_tab.pipeline_config_panel.controller = controller
- docs\older\ChatGPT-WhyNoPipeline.md:5175: mw.pipeline_config_panel_v2 = getattr(getattr(mw.pipeline_tab, "sidebar", None), "pipeline_config_panel", None)
- docs\older\ChatGPT-WhyNoPipeline.md:5246: mw.pipeline_config_panel_v2 = getattr(getattr(mw.pipeline_tab, "sidebar", None), "pipeline_config_panel", None)
- docs\older\ChatGPT-WhyNoPipeline.md:5506: 22 from src.controller.pipeline_config_assembler import PipelineConfigAssembler, GuiOverrides, RunPlan, PlannedJob
- docs\older\ChatGPT-WhyNoPipeline.md:5552: 68             pipeline_config=config,
- docs\older\ChatGPT-WhyNoPipeline.md:5696: job = Job(job_id=job_id, pipeline_config=None, priority=priority, payload=pipeline_callable, worker_id=worker_id)
- docs\older\ChatGPT-WhyNoPipeline.md:5800: job = Job(job_id=job_id, pipeline_config=None, priority=priority, payload=pipeline_callable, worker_id=worker_id)

## docs\older\GUI-Pipeline-Hierarchy-Diagram.txt
- docs\older\GUI-Pipeline-Hierarchy-Diagram.txt:16: │   │           ├── pipeline_config_card (_SidebarCard)
- docs\older\GUI-Pipeline-Hierarchy-Diagram.txt:17: │   │           │   └── pipeline_config_panel (PipelineConfigPanel)

## docs\older\LEGACY_CANDIDATES.md
- docs\older\LEGACY_CANDIDATES.md:38: - `src/gui/views/pipeline_config_panel.py` (unreachable)
- docs\older\LEGACY_CANDIDATES.md:64: - `tests/gui_v2/test_gui_v2_pipeline_config_roundtrip.py` (unreachable)
- docs\older\LEGACY_CANDIDATES.md:152: - `src/controller/pipeline_config_assembler.py` (unreachable)
- docs\older\LEGACY_CANDIDATES.md:161: - `tests/controller/test_pipeline_config_assembler.py` (unreachable)
- docs\older\LEGACY_CANDIDATES.md:162: - `tests/controller/test_pipeline_config_assembler_core_fields.py` (unreachable)
- docs\older\LEGACY_CANDIDATES.md:163: - `tests/controller/test_pipeline_config_assembler_model_fields.py` (unreachable)
- docs\older\LEGACY_CANDIDATES.md:164: - `tests/controller/test_pipeline_config_assembler_negative_prompt.py` (unreachable)
- docs\older\LEGACY_CANDIDATES.md:165: - `tests/controller/test_pipeline_config_assembler_output_settings.py` (unreachable)
- docs\older\LEGACY_CANDIDATES.md:166: - `tests/controller/test_pipeline_config_assembler_resolution.py` (unreachable)

## docs\older\Make the pipeline work stream of consciousness.md
- docs\older\Make the pipeline work stream of consciousness.md:1186: cfg = getattr(job, "pipeline_config", None)
- docs\older\Make the pipeline work stream of consciousness.md:1410: from src.controller.pipeline_config_assembler import PipelineConfigAssembler, GuiOverrides, RunPlan, PlannedJob
- docs\older\Make the pipeline work stream of consciousness.md:1459: pipeline_config=config,
- docs\older\Make the pipeline work stream of consciousness.md:1546: def _build_pipeline_config_from_state(self) -> PipelineConfig:
- docs\older\Make the pipeline work stream of consciousness.md:1583: base_config = self._build_pipeline_config_from_state()
- docs\older\Make the pipeline work stream of consciousness.md:1786: def build_pipeline_config_with_profiles(
- docs\older\Make the pipeline work stream of consciousness.md:2014: config = self._build_pipeline_config_from_state()
- docs\older\Make the pipeline work stream of consciousness.md:2174: pipeline_config=config,
- docs\older\Make the pipeline work stream of consciousness.md:2186: if not job.pipeline_config:
- docs\older\Make the pipeline work stream of consciousness.md:2191: result = runner.run(job.pipeline_config, self.cancel_token)
- docs\older\Make the pipeline work stream of consciousness.md:2389: 'pipeline_config_panel_v2.py',
- docs\older\Make the pipeline work stream of consciousness.md:3273: panel = getattr(self.main_window, "pipeline_config_panel_v2", None)
- docs\older\Make the pipeline work stream of consciousness.md:3312: pipeline_config=None,
- docs\older\Make the pipeline work stream of consciousness.md:3389: pipeline_config_panel = getattr(self.main_window, "pipeline_config_panel_v2", None)
- docs\older\Make the pipeline work stream of consciousness.md:3390: if pipeline_config_panel and hasattr(pipeline_config_panel, "apply_run_config"):
- docs\older\Make the pipeline work stream of consciousness.md:3392: pipeline_config_panel.apply_run_config(pack_config)
- docs\older\Make the pipeline work stream of consciousness.md:3783: panel = getattr(self.main_window, "pipeline_config_panel_v2", None)
- docs\older\Make the pipeline work stream of consciousness.md:3822: pipeline_config=None,
- docs\older\Make the pipeline work stream of consciousness.md:3899: pipeline_config_panel = getattr(self.main_window, "pipeline_config_panel_v2", None)
- docs\older\Make the pipeline work stream of consciousness.md:3900: if pipeline_config_panel and hasattr(pipeline_config_panel, "apply_run_config"):
- docs\older\Make the pipeline work stream of consciousness.md:3902: pipeline_config_panel.apply_run_config(pack_config)
- docs\older\Make the pipeline work stream of consciousness.md:4432: pipeline_config=None,
- docs\older\Make the pipeline work stream of consciousness.md:4530: pipeline_config_panel = getattr(self.main_window, "pipeline_config_panel_v2", None)
- docs\older\Make the pipeline work stream of consciousness.md:4531: if pipeline_config_panel and hasattr(pipeline_config_panel, "apply_run_config"):
- docs\older\Make the pipeline work stream of consciousness.md:4533: pipeline_config_panel.apply_run_config(pack_config)
- docs\older\Make the pipeline work stream of consciousness.md:4596: pipeline_config=None,
- docs\older\Make the pipeline work stream of consciousness.md:4782: result = runner.run(job.pipeline_config, self.cancel_token)
- docs\older\Make the pipeline work stream of consciousness.md:4906: # Extract pipeline_config from record.config if it's the right type
- docs\older\Make the pipeline work stream of consciousness.md:4907: pipeline_config = None
- docs\older\Make the pipeline work stream of consciousness.md:4909: pipeline_config = record.config
- docs\older\Make the pipeline work stream of consciousness.md:4913: pipeline_config = record.config
- docs\older\Make the pipeline work stream of consciousness.md:4925: pipeline_config=pipeline_config,
- docs\older\Make the pipeline work stream of consciousness.md:4977: if not job.pipeline_config:
- docs\older\Make the pipeline work stream of consciousness.md:4982: result = runner.run(job.pipeline_config, self.cancel_token)
- docs\older\Make the pipeline work stream of consciousness.md:5436: mw.pipeline_config_panel_v2 = getattr(getattr(mw.pipeline_tab, "sidebar", None), "pipeline_config_panel", None)
- docs\older\Make the pipeline work stream of consciousness.md:5664: base_config = self._build_pipeline_config_from_state()
- docs\older\Make the pipeline work stream of consciousness.md:6130: job = Job(job_id=job_id, pipeline_config=None, priority=priority, payload=pipeline_callable, worker_id=worker_id)
- docs\older\Make the pipeline work stream of consciousness.md:7074: 301:         # Extract pipeline_config from record.config if it's the right type
- docs\older\Make the pipeline work stream of consciousness.md:7075: 302:         pipeline_config = None
- docs\older\Make the pipeline work stream of consciousness.md:7077: 304:             pipeline_config = record.config
- docs\older\Make the pipeline work stream of consciousness.md:7081: 308:                 pipeline_config = record.config
- docs\older\Make the pipeline work stream of consciousness.md:7090: 317:             pipeline_config=pipeline_config,
- docs\older\Make the pipeline work stream of consciousness.md:7202: def build_pipeline_config_with_profiles(

## docs\older\PIPELINE_CONFIG_LOGGING_PRESETS_ADetailer_DISCOVERY_V2-P1.md
- docs\older\PIPELINE_CONFIG_LOGGING_PRESETS_ADetailer_DISCOVERY_V2-P1.md:19: - **File**: `src/gui/views/pipeline_config_panel_v2.py`

## docs\older\Revised-PR-204-2-MasterPlan_v2.5.md
- docs\older\Revised-PR-204-2-MasterPlan_v2.5.md:75: NormalizedJobRecord (or JobSpecV2) carries pipeline_config: PipelineConfig, plus metadata (variant/batch, output paths, etc.).
- docs\older\Revised-PR-204-2-MasterPlan_v2.5.md:194: pipeline_config: PipelineConfig
- docs\older\Revised-PR-204-2-MasterPlan_v2.5.md:432: pipeline_config: PipelineConfig  # fully merged & randomizer/batch aware
- docs\older\Revised-PR-204-2-MasterPlan_v2.5.md:515: base_pipeline_config: PipelineConfig (from PipelineConfigAssembler.build_from_gui_input(...)).
- docs\older\Revised-PR-204-2-MasterPlan_v2.5.md:573: pipeline_config=cfg,
- docs\older\Revised-PR-204-2-MasterPlan_v2.5.md:646: Positive prompt / negative prompt (from pipeline_config).
- docs\older\Revised-PR-204-2-MasterPlan_v2.5.md:714: Submitting JobSpecV2 through JobService leads to correct _run_pipeline_job(pipeline_config) call.

## docs\older\Run Pipeline Path (V2) – Architecture Notes.md
- docs\older\Run Pipeline Path (V2) – Architecture Notes.md:34: pipeline_config
- docs\older\Run Pipeline Path (V2) – Architecture Notes.md:263: pipeline_config

## docs\older\StableNew_Coding_and_Testing_v2.5.md
- docs\older\StableNew_Coding_and_Testing_v2.5.md:144: - Functions: `snake_case`, descriptive (`merge_pipeline_config`, `build_jobs`, `to_ui_summary`).

## docs\older\StableNew_V2_Inventory.md
- docs\older\StableNew_V2_Inventory.md:50: - `.mypy_cache/3.11/src/gui/panels_v2/pipeline_config_panel_v2.data.json`
- docs\older\StableNew_V2_Inventory.md:51: - `.mypy_cache/3.11/src/gui/panels_v2/pipeline_config_panel_v2.meta.json`
- docs\older\StableNew_V2_Inventory.md:104: - `.mypy_cache/3.11/src/gui/views/pipeline_config_panel_v2.data.json`
- docs\older\StableNew_V2_Inventory.md:105: - `.mypy_cache/3.11/src/gui/views/pipeline_config_panel_v2.meta.json`
- docs\older\StableNew_V2_Inventory.md:170: - `.mypy_cache/3.11/tests/gui_v2/test_gui_v2_pipeline_config_roundtrip.data.json`
- docs\older\StableNew_V2_Inventory.md:171: - `.mypy_cache/3.11/tests/gui_v2/test_gui_v2_pipeline_config_roundtrip.meta.json`
- docs\older\StableNew_V2_Inventory.md:305: - `htmlcov/z_ac9e25382994b44b_pipeline_config_panel_v2_py.html`
- docs\older\StableNew_V2_Inventory.md:328: - `src/controller/__pycache__/pipeline_config_assembler.cpython-310.pyc`
- docs\older\StableNew_V2_Inventory.md:378: - `src/gui/panels_v2/__pycache__/pipeline_config_panel_v2.cpython-310.pyc`
- docs\older\StableNew_V2_Inventory.md:385: - `src/gui/panels_v2/pipeline_config_panel_v2.py`
- docs\older\StableNew_V2_Inventory.md:417: - `src/gui/views/.mypy_cache/3.11/src/gui/views/pipeline_config_panel_v2.data.json`
- docs\older\StableNew_V2_Inventory.md:418: - `src/gui/views/.mypy_cache/3.11/src/gui/views/pipeline_config_panel_v2.meta.json`
- docs\older\StableNew_V2_Inventory.md:426: - `src/gui/views/__pycache__/pipeline_config_panel_v2.cpython-310.pyc`
- docs\older\StableNew_V2_Inventory.md:510: - `tests/gui_v2/__pycache__/test_gui_v2_pipeline_config_roundtrip.cpython-310-pytest-9.0.1.pyc`
- docs\older\StableNew_V2_Inventory.md:537: - `tests/gui_v2/__pycache__/test_pipeline_config_panel_lora_runtime.cpython-310-pytest-9.0.1.pyc`
- docs\older\StableNew_V2_Inventory.md:579: - `tests/gui_v2/test_pipeline_config_panel_lora_runtime.py`
- docs\older\StableNew_V2_Inventory.md:1198: - `tests/controller/__pycache__/test_pipeline_config_assembler.cpython-310-pytest-9.0.1.pyc`
- docs\older\StableNew_V2_Inventory.md:1199: - `tests/controller/__pycache__/test_pipeline_config_assembler_core_fields.cpython-310-pytest-9.0.1.pyc`
- docs\older\StableNew_V2_Inventory.md:1200: - `tests/controller/__pycache__/test_pipeline_config_assembler_model_fields.cpython-310-pytest-9.0.1.pyc`
- docs\older\StableNew_V2_Inventory.md:1201: - `tests/controller/__pycache__/test_pipeline_config_assembler_negative_prompt.cpython-310-pytest-9.0.1.pyc`
- docs\older\StableNew_V2_Inventory.md:1202: - `tests/controller/__pycache__/test_pipeline_config_assembler_output_settings.cpython-310-pytest-9.0.1.pyc`
- docs\older\StableNew_V2_Inventory.md:1203: - `tests/controller/__pycache__/test_pipeline_config_assembler_resolution.cpython-310-pytest-9.0.1.pyc`
- docs\older\StableNew_V2_Inventory.md:1320: - `src/controller/pipeline_config_assembler.py`
- docs\older\StableNew_V2_Inventory.md:1885: - `src/gui/views/__pycache__/pipeline_config_panel.cpython-310.pyc`
- docs\older\StableNew_V2_Inventory.md:1894: - `src/gui/views/pipeline_config_panel.py`
- docs\older\StableNew_V2_Inventory.md:1958: - `tests/controller/test_pipeline_config_assembler.py`
- docs\older\StableNew_V2_Inventory.md:1959: - `tests/controller/test_pipeline_config_assembler_core_fields.py`
- docs\older\StableNew_V2_Inventory.md:1960: - `tests/controller/test_pipeline_config_assembler_model_fields.py`
- docs\older\StableNew_V2_Inventory.md:1961: - `tests/controller/test_pipeline_config_assembler_negative_prompt.py`
- docs\older\StableNew_V2_Inventory.md:1962: - `tests/controller/test_pipeline_config_assembler_output_settings.py`
- docs\older\StableNew_V2_Inventory.md:1963: - `tests/controller/test_pipeline_config_assembler_resolution.py`
- docs\older\StableNew_V2_Inventory.md:3012: - `.mypy_cache/3.11/src/controller/pipeline_config_assembler.data.json`
- docs\older\StableNew_V2_Inventory.md:3013: - `.mypy_cache/3.11/src/controller/pipeline_config_assembler.meta.json`
- docs\older\StableNew_V2_Inventory.md:3244: - `.mypy_cache/3.11/tests/controller/test_pipeline_config_assembler.data.json`
- docs\older\StableNew_V2_Inventory.md:3245: - `.mypy_cache/3.11/tests/controller/test_pipeline_config_assembler.meta.json`
- docs\older\StableNew_V2_Inventory.md:6925: - `htmlcov/z_7da4a89bed7a4ad5_pipeline_config_panel_py.html`
- docs\older\StableNew_V2_Inventory.md:6945: - `htmlcov/z_ac5b274346abdaff_pipeline_config_assembler_py.html`

## docs\older\StableNew_V2_Inventory_V2-P1.md
- docs\older\StableNew_V2_Inventory_V2-P1.md:107: - `src/controller/pipeline_config_assembler.py`
- docs\older\StableNew_V2_Inventory_V2-P1.md:146: - `src/gui/views/pipeline_config_panel.py`
- docs\older\StableNew_V2_Inventory_V2-P1.md:220: - `tests/gui_v2/test_gui_v2_pipeline_config_roundtrip.py`
- docs\older\StableNew_V2_Inventory_V2-P1.md:341: - `tests/controller/test_pipeline_config_assembler.py`
- docs\older\StableNew_V2_Inventory_V2-P1.md:342: - `tests/controller/test_pipeline_config_assembler_core_fields.py`
- docs\older\StableNew_V2_Inventory_V2-P1.md:343: - `tests/controller/test_pipeline_config_assembler_model_fields.py`
- docs\older\StableNew_V2_Inventory_V2-P1.md:344: - `tests/controller/test_pipeline_config_assembler_negative_prompt.py`
- docs\older\StableNew_V2_Inventory_V2-P1.md:345: - `tests/controller/test_pipeline_config_assembler_output_settings.py`
- docs\older\StableNew_V2_Inventory_V2-P1.md:346: - `tests/controller/test_pipeline_config_assembler_resolution.py`

## docs\older\WIRING_V2_5_ReachableFromMain_2025-11-26.md
- docs\older\WIRING_V2_5_ReachableFromMain_2025-11-26.md:126: | `src/pipeline/pipeline_config_v2.py` |  |  |  |  |  |

## docs\older\repo_inventory_classified_v2_phase1.json
- docs\older\repo_inventory_classified_v2_phase1.json:25: "src/controller/pipeline_config_assembler.py": "shared_core",
- docs\older\repo_inventory_classified_v2_phase1.json:98: "src/gui/views/pipeline_config_panel.py": "shared_core",
- docs\older\repo_inventory_classified_v2_phase1.json:183: "tests/controller/test_pipeline_config_assembler.py": "neutral_test",
- docs\older\repo_inventory_classified_v2_phase1.json:184: "tests/controller/test_pipeline_config_assembler_core_fields.py": "neutral_test",
- docs\older\repo_inventory_classified_v2_phase1.json:185: "tests/controller/test_pipeline_config_assembler_model_fields.py": "neutral_test",
- docs\older\repo_inventory_classified_v2_phase1.json:186: "tests/controller/test_pipeline_config_assembler_negative_prompt.py": "neutral_test",
- docs\older\repo_inventory_classified_v2_phase1.json:187: "tests/controller/test_pipeline_config_assembler_output_settings.py": "neutral_test",
- docs\older\repo_inventory_classified_v2_phase1.json:188: "tests/controller/test_pipeline_config_assembler_resolution.py": "neutral_test",
- docs\older\repo_inventory_classified_v2_phase1.json:211: "tests/gui_v2/test_gui_v2_pipeline_config_roundtrip.py": "v2_canonical_test",

## docs\pr_templates\PR Doc Resources\PR-114-StreamOfThought.md
- docs\pr_templates\PR Doc Resources\PR-114-StreamOfThought.md:114: from src.controller.pipeline_config_assembler import PipelineConfigAssembler, GuiOverrides, RunPlan, PlannedJob
- docs\pr_templates\PR Doc Resources\PR-114-StreamOfThought.md:160: pipeline_config=config,
- docs\pr_templates\PR Doc Resources\PR-114-StreamOfThought.md:241: def _build_pipeline_config_from_state(self) -> PipelineConfig:
- docs\pr_templates\PR Doc Resources\PR-114-StreamOfThought.md:255: def build_pipeline_config_with_profiles(
- docs\pr_templates\PR Doc Resources\PR-114-StreamOfThought.md:380: from src.controller.pipeline_config_assembler import PipelineConfigAssembler, GuiOverrides, RunPlan, PlannedJob
- docs\pr_templates\PR Doc Resources\PR-114-StreamOfThought.md:426: pipeline_config=config,
- docs\pr_templates\PR Doc Resources\PR-114-StreamOfThought.md:507: def _build_pipeline_config_from_state(self) -> PipelineConfig:
- docs\pr_templates\PR Doc Resources\PR-114-StreamOfThought.md:521: def build_pipeline_config_with_profiles(
- docs\pr_templates\PR Doc Resources\PR-114-StreamOfThought.md:743: config = self._build_pipeline_config_from_state()
- docs\pr_templates\PR Doc Resources\PR-114-StreamOfThought.md:790: from src.controller.pipeline_config_assembler import PipelineConfigAssem
- docs\pr_templates\PR Doc Resources\PR-114-StreamOfThought.md:835: config = self._build_pipeline_config_from_state()
- docs\pr_templates\PR Doc Resources\PR-114-StreamOfThought.md:977: job = Job(job_id=job_id, pipeline_config=None, priority=priority, payload=pipeline_callable, worker_id=worker_id)
- docs\pr_templates\PR Doc Resources\PR-114-StreamOfThought.md:1409: job = Job(job_id=job_id, pipeline_config=None, priority=priority, payload=pipeline_callable, worker_id=worker_id)
- docs\pr_templates\PR Doc Resources\PR-114-StreamOfThought.md:1625: from src.controller.pipeline_config_assembler import PipelineConfigAssembler, GuiOverrides, RunPlan, PlannedJob
- docs\pr_templates\PR Doc Resources\PR-114-StreamOfThought.md:1699: pipeline_config=config,
- docs\pr_templates\PR Doc Resources\PR-114-StreamOfThought.md:1739: pipeline_config=config,
- docs\pr_templates\PR Doc Resources\PR-114-StreamOfThought.md:2011: job = Job(job_id=job_id, pipeline_config=None, priority=priority, payload=pipeline_callable, worker_id=worker_id)
- docs\pr_templates\PR Doc Resources\PR-114-StreamOfThought.md:2437: The PipelineRunner.run expects a PipelineConfig dataclass, which is presumably returned by pipeline_controller._build_pipeline_config_from_state—great, that part works. But _run_pipeline_job isn’t using run yet. I need to bridge that gap and integrate the learning hooks (_learning_enabled, _get_learning_runner). I'll also check tests for any existing connections.

## docs\pr_templates\PriorWork_complete\CLEANUP-GUI-TEST-QUARANTINE-002_V2-P1.md
- docs\pr_templates\PriorWork_complete\CLEANUP-GUI-TEST-QUARANTINE-002_V2-P1.md:82: - `tests/gui_v2/test_gui_v2_pipeline_config_roundtrip.py`

## docs\pr_templates\PriorWork_complete\Codex_Run_Sheet_PR-GUI-V2-MIGRATION-003.md
- docs\pr_templates\PriorWork_complete\Codex_Run_Sheet_PR-GUI-V2-MIGRATION-003.md:12: - tests/gui_v2/test_gui_v2_pipeline_config_roundtrip.py
- docs\pr_templates\PriorWork_complete\Codex_Run_Sheet_PR-GUI-V2-MIGRATION-003.md:103: 1) tests/gui_v2/test_gui_v2_pipeline_config_roundtrip.py (new)

## docs\pr_templates\PriorWork_complete\Dark-Mode-GlobalNeg-11-26-25.md
- docs\pr_templates\PriorWork_complete\Dark-Mode-GlobalNeg-11-26-25.md:326: pipeline_config["global_negative"] = self.get_global_negative_config()
- docs\pr_templates\PriorWork_complete\Dark-Mode-GlobalNeg-11-26-25.md:335: global_neg = pipeline_config.get("global_negative", {})

## docs\pr_templates\PriorWork_complete\Execution Script for PR-#53 – Advanced Resolution Controls.md
- docs\pr_templates\PriorWork_complete\Execution Script for PR-#53 – Advanced Resolution Controls.md:40: src/controller/pipeline_config_assembler.py
- docs\pr_templates\PriorWork_complete\Execution Script for PR-#53 – Advanced Resolution Controls.md:48: tests/controller/test_pipeline_config_assembler_resolution.py (new or extend)
- docs\pr_templates\PriorWork_complete\Execution Script for PR-#53 – Advanced Resolution Controls.md:110: In pipeline_config_assembler.py:
- docs\pr_templates\PriorWork_complete\Execution Script for PR-#53 – Advanced Resolution Controls.md:130: pytest tests/controller/test_pipeline_config_assembler_resolution.py -v
- docs\pr_templates\PriorWork_complete\Execution Script for PR-#53 – Advanced Resolution Controls.md:156: pytest tests/controller/test_pipeline_config_assembler_resolution.py -v

## docs\pr_templates\PriorWork_complete\PR-#38-PIPELINE-V2-GUIConfigToPipelineConfig-001.md
- docs\pr_templates\PriorWork_complete\PR-#38-PIPELINE-V2-GUIConfigToPipelineConfig-001.md:29: - `src/pipeline/pipeline_config.py` (or equivalent)
- docs\pr_templates\PriorWork_complete\PR-#38-PIPELINE-V2-GUIConfigToPipelineConfig-001.md:43: - `src/controller/pipeline_config_assembler.py` **(new)** (name flexible, but must live in controller layer)
- docs\pr_templates\PriorWork_complete\PR-#38-PIPELINE-V2-GUIConfigToPipelineConfig-001.md:45: - `build_pipeline_config(base_config, gui_overrides, randomizer_overlay, learning_enabled) -> PipelineConfig`
- docs\pr_templates\PriorWork_complete\PR-#38-PIPELINE-V2-GUIConfigToPipelineConfig-001.md:65: - `config = self.config_assembler.build_pipeline_config(...)`
- docs\pr_templates\PriorWork_complete\PR-#38-PIPELINE-V2-GUIConfigToPipelineConfig-001.md:85: - `tests/controller/test_pipeline_config_assembler.py` **(new)**
- docs\pr_templates\PriorWork_complete\PR-#38-PIPELINE-V2-GUIConfigToPipelineConfig-001.md:105: - `tests/pipeline/test_pipeline_config_invariants.py` **(new or extended)**
- docs\pr_templates\PriorWork_complete\PR-#38-PIPELINE-V2-GUIConfigToPipelineConfig-001.md:185: - `pytest tests/controller/test_pipeline_config_assembler.py -v`
- docs\pr_templates\PriorWork_complete\PR-#38-PIPELINE-V2-GUIConfigToPipelineConfig-001.md:191: - `pytest tests/pipeline/test_pipeline_config_invariants.py -v`

## docs\pr_templates\PriorWork_complete\PR-#46-PIPELINE-V2-PipelineConfigAssemblerEnforcement-001.md
- docs\pr_templates\PriorWork_complete\PR-#46-PIPELINE-V2-PipelineConfigAssemblerEnforcement-001.md:35: - `src/pipeline/pipeline_config_assembler.py`
- docs\pr_templates\PriorWork_complete\PR-#46-PIPELINE-V2-PipelineConfigAssemblerEnforcement-001.md:182: - `tests/controller/test_pipeline_config_assembler.py -v`
- docs\pr_templates\PriorWork_complete\PR-#46-PIPELINE-V2-PipelineConfigAssemblerEnforcement-001.md:206: - `tests/pipeline/test_pipeline_config_invariants.py -v` (new or extended)

## docs\pr_templates\PriorWork_complete\PR-#47-PIPELINE-V2-AssemblerEnforcement-Finish-001.md
- docs\pr_templates\PriorWork_complete\PR-#47-PIPELINE-V2-AssemblerEnforcement-Finish-001.md:78: - `test_pipeline_config_assembler.py`
- docs\pr_templates\PriorWork_complete\PR-#47-PIPELINE-V2-AssemblerEnforcement-Finish-001.md:80: - `test_pipeline_config_invariants.py`
- docs\pr_templates\PriorWork_complete\PR-#47-PIPELINE-V2-AssemblerEnforcement-Finish-001.md:104: - `src/controller/pipeline_config_assembler.py` (small adjustments only; no redesign)
- docs\pr_templates\PriorWork_complete\PR-#47-PIPELINE-V2-AssemblerEnforcement-Finish-001.md:117: - `tests/controller/test_pipeline_config_assembler.py`
- docs\pr_templates\PriorWork_complete\PR-#47-PIPELINE-V2-AssemblerEnforcement-Finish-001.md:119: - `tests/pipeline/test_pipeline_config_invariants.py`
- docs\pr_templates\PriorWork_complete\PR-#47-PIPELINE-V2-AssemblerEnforcement-Finish-001.md:145: **File:** `src/controller/pipeline_config_assembler.py`
- docs\pr_templates\PriorWork_complete\PR-#47-PIPELINE-V2-AssemblerEnforcement-Finish-001.md:173: - `def _build_pipeline_config_from_state(self) -> PipelineConfig:`
- docs\pr_templates\PriorWork_complete\PR-#47-PIPELINE-V2-AssemblerEnforcement-Finish-001.md:180: - Build a `PipelineConfig` via `_build_pipeline_config_from_state()`.
- docs\pr_templates\PriorWork_complete\PR-#47-PIPELINE-V2-AssemblerEnforcement-Finish-001.md:229: - Passes that structure to the controller via a clear call (for example, `controller.request_run_with_overrides(overrides)` or by setting state that `_build_pipeline_config_from_state()` reads).
- docs\pr_templates\PriorWork_complete\PR-#47-PIPELINE-V2-AssemblerEnforcement-Finish-001.md:268: - `pytest tests/controller/test_pipeline_config_assembler.py -v`
- docs\pr_templates\PriorWork_complete\PR-#47-PIPELINE-V2-AssemblerEnforcement-Finish-001.md:284: - `pytest tests/pipeline/test_pipeline_config_invariants.py -v`
- docs\pr_templates\PriorWork_complete\PR-#47-PIPELINE-V2-AssemblerEnforcement-Finish-001.md:318: - `tests/pipeline/test_pipeline_config_invariants.py` is green.
- docs\pr_templates\PriorWork_complete\PR-#47-PIPELINE-V2-AssemblerEnforcement-Finish-001.md:337: - `src/controller/pipeline_config_assembler.py` (only the deltas introduced by this PR)

## docs\pr_templates\PriorWork_complete\PR-#47B-PIPELINE-V2-AssemblerEnforcement-Hotfix-001.md
- docs\pr_templates\PriorWork_complete\PR-#47B-PIPELINE-V2-AssemblerEnforcement-Hotfix-001.md:51: - start_pipeline calls into a dedicated _build_pipeline_config_from_state (or equivalent) that wraps build_from_gui_input.
- docs\pr_templates\PriorWork_complete\PR-#47B-PIPELINE-V2-AssemblerEnforcement-Hotfix-001.md:100: - src/controller/pipeline_config_assembler.py
- docs\pr_templates\PriorWork_complete\PR-#47B-PIPELINE-V2-AssemblerEnforcement-Hotfix-001.md:104: - tests/controller/test_pipeline_config_assembler.py
- docs\pr_templates\PriorWork_complete\PR-#47B-PIPELINE-V2-AssemblerEnforcement-Hotfix-001.md:156: - _build_pipeline_config_from_state(self) -> PipelineConfig:
- docs\pr_templates\PriorWork_complete\PR-#47B-PIPELINE-V2-AssemblerEnforcement-Hotfix-001.md:177: - Build a PipelineConfig using _build_pipeline_config_from_state.
- docs\pr_templates\PriorWork_complete\PR-#47B-PIPELINE-V2-AssemblerEnforcement-Hotfix-001.md:222: - pytest tests/controller/test_pipeline_config_assembler.py -v
- docs\pr_templates\PriorWork_complete\PR-#47B-PIPELINE-V2-AssemblerEnforcement-Hotfix-001.md:245: If any test outside the target ones fails, analyze the failure and apply the minimal fix within src/controller/pipeline_controller.py or, if absolutely necessary, src/controller/pipeline_config_assembler.py.
- docs\pr_templates\PriorWork_complete\PR-#47B-PIPELINE-V2-AssemblerEnforcement-Hotfix-001.md:280: - src/controller/pipeline_config_assembler.py (if touched)

## docs\pr_templates\PriorWork_complete\PR-#50-GUI-V2-PromptPackManager-Integration-001.md
- docs\pr_templates\PriorWork_complete\PR-#50-GUI-V2-PromptPackManager-Integration-001.md:56: - `src/controller/pipeline_config_assembler.py`

## docs\pr_templates\PriorWork_complete\PR-#51-GUI-V2-CoreConfigPanel-001.md
- docs\pr_templates\PriorWork_complete\PR-#51-GUI-V2-CoreConfigPanel-001.md:127: - `src/controller/pipeline_config_assembler.py` *(ensure assembler accepts core config overrides and maps into `PipelineConfig`)*
- docs\pr_templates\PriorWork_complete\PR-#51-GUI-V2-CoreConfigPanel-001.md:133: - `tests/controller/test_pipeline_config_assembler_core_fields.py` *(new or extend existing assembler tests)*
- docs\pr_templates\PriorWork_complete\PR-#51-GUI-V2-CoreConfigPanel-001.md:239: In `src/controller/pipeline_config_assembler.py`:
- docs\pr_templates\PriorWork_complete\PR-#51-GUI-V2-CoreConfigPanel-001.md:269: 2. **Assembler test**: `tests/controller/test_pipeline_config_assembler_core_fields.py`
- docs\pr_templates\PriorWork_complete\PR-#51-GUI-V2-CoreConfigPanel-001.md:271: - `test_assembler_maps_core_fields_to_pipeline_config`:
- docs\pr_templates\PriorWork_complete\PR-#51-GUI-V2-CoreConfigPanel-001.md:296: - `pytest tests/controller/test_pipeline_config_assembler_core_fields.py -v`
- docs\pr_templates\PriorWork_complete\PR-#51-GUI-V2-CoreConfigPanel-001.md:335: - `src/controller/pipeline_config_assembler.py`
- docs\pr_templates\PriorWork_complete\PR-#51-GUI-V2-CoreConfigPanel-001.md:367: - `pytest tests/controller/test_pipeline_config_assembler_core_fields.py -v`

## docs\pr_templates\PriorWork_complete\PR-#52-GUI-V2-NegativePromptPanel-001.md
- docs\pr_templates\PriorWork_complete\PR-#52-GUI-V2-NegativePromptPanel-001.md:114: - `src/controller/pipeline_config_assembler.py` *(map negative_prompt into `PipelineConfig`)*
- docs\pr_templates\PriorWork_complete\PR-#52-GUI-V2-NegativePromptPanel-001.md:123: - `tests/controller/test_pipeline_config_assembler_negative_prompt.py` *(new)*
- docs\pr_templates\PriorWork_complete\PR-#52-GUI-V2-NegativePromptPanel-001.md:192: In `src/controller/pipeline_config_assembler.py`:
- docs\pr_templates\PriorWork_complete\PR-#52-GUI-V2-NegativePromptPanel-001.md:213: 2. `tests/controller/test_pipeline_config_assembler_negative_prompt.py`:
- docs\pr_templates\PriorWork_complete\PR-#52-GUI-V2-NegativePromptPanel-001.md:229: - `pytest tests/controller/test_pipeline_config_assembler_negative_prompt.py -v`
- docs\pr_templates\PriorWork_complete\PR-#52-GUI-V2-NegativePromptPanel-001.md:295: - `pytest tests/controller/test_pipeline_config_assembler_negative_prompt.py -v`

## docs\pr_templates\PriorWork_complete\PR-#53-GUI-V2-ResolutionAdvancedControls-001.md
- docs\pr_templates\PriorWork_complete\PR-#53-GUI-V2-ResolutionAdvancedControls-001.md:120: - `src/controller/pipeline_config_assembler.py` *(interpret overrides into width/height and apply clamps)*
- docs\pr_templates\PriorWork_complete\PR-#53-GUI-V2-ResolutionAdvancedControls-001.md:129: - `tests/controller/test_pipeline_config_assembler_resolution.py` *(new or extended)*
- docs\pr_templates\PriorWork_complete\PR-#53-GUI-V2-ResolutionAdvancedControls-001.md:197: In `src/controller/pipeline_config_assembler.py`:
- docs\pr_templates\PriorWork_complete\PR-#53-GUI-V2-ResolutionAdvancedControls-001.md:223: 2. `tests/controller/test_pipeline_config_assembler_resolution.py`:
- docs\pr_templates\PriorWork_complete\PR-#53-GUI-V2-ResolutionAdvancedControls-001.md:239: - `pytest tests/controller/test_pipeline_config_assembler_resolution.py -v`
- docs\pr_templates\PriorWork_complete\PR-#53-GUI-V2-ResolutionAdvancedControls-001.md:304: - `pytest tests/controller/test_pipeline_config_assembler_resolution.py -v`

## docs\pr_templates\PriorWork_complete\PR-#54-GUI-V2-OutputSettingsPanel-001.md
- docs\pr_templates\PriorWork_complete\PR-#54-GUI-V2-OutputSettingsPanel-001.md:115: - `src/controller/pipeline_config_assembler.py` *(map output overrides into `PipelineConfig`)*
- docs\pr_templates\PriorWork_complete\PR-#54-GUI-V2-OutputSettingsPanel-001.md:124: - `tests/controller/test_pipeline_config_assembler_output_settings.py` *(new)*
- docs\pr_templates\PriorWork_complete\PR-#54-GUI-V2-OutputSettingsPanel-001.md:194: In `src/controller/pipeline_config_assembler.py`:
- docs\pr_templates\PriorWork_complete\PR-#54-GUI-V2-OutputSettingsPanel-001.md:215: 2. `tests/controller/test_pipeline_config_assembler_output_settings.py`:
- docs\pr_templates\PriorWork_complete\PR-#54-GUI-V2-OutputSettingsPanel-001.md:231: - `pytest tests/controller/test_pipeline_config_assembler_output_settings.py -v`
- docs\pr_templates\PriorWork_complete\PR-#54-GUI-V2-OutputSettingsPanel-001.md:295: - `pytest tests/controller/test_pipeline_config_assembler_output_settings.py -v`

## docs\pr_templates\PriorWork_complete\PR-#55-GUI-V2-ModelManagerPanel-001.md
- docs\pr_templates\PriorWork_complete\PR-#55-GUI-V2-ModelManagerPanel-001.md:110: - `src/controller/pipeline_config_assembler.py` *(map model/vae into `PipelineConfig`)*
- docs\pr_templates\PriorWork_complete\PR-#55-GUI-V2-ModelManagerPanel-001.md:121: - `tests/controller/test_pipeline_config_assembler_model_fields.py` *(new or extended)*
- docs\pr_templates\PriorWork_complete\PR-#55-GUI-V2-ModelManagerPanel-001.md:200: In `src/controller/pipeline_config_assembler.py`:
- docs\pr_templates\PriorWork_complete\PR-#55-GUI-V2-ModelManagerPanel-001.md:220: 2. `tests/controller/test_pipeline_config_assembler_model_fields.py`:
- docs\pr_templates\PriorWork_complete\PR-#55-GUI-V2-ModelManagerPanel-001.md:236: - `pytest tests/controller/test_pipeline_config_assembler_model_fields.py -v`
- docs\pr_templates\PriorWork_complete\PR-#55-GUI-V2-ModelManagerPanel-001.md:301: - `pytest tests/controller/test_pipeline_config_assembler_model_fields.py -v`

## docs\pr_templates\PriorWork_complete\PR-0114 — Pipeline Run Controls → Queue-Runner.md
- docs\pr_templates\PriorWork_complete\PR-0114 — Pipeline Run Controls → Queue-Runner.md:100: config = job.pipeline_config
- docs\pr_templates\PriorWork_complete\PR-0114 — Pipeline Run Controls → Queue-Runner.md:219: config = job.pipeline_config

## docs\pr_templates\PriorWork_complete\PR-0114C – End-to-End Job Execution + Journey Tests.md
- docs\pr_templates\PriorWork_complete\PR-0114C – End-to-End Job Execution + Journey Tests.md:71: Invokes PipelineRunner via runner.run(job.pipeline_config, self.cancel_token) (for multi-stage path).

## docs\pr_templates\PriorWork_complete\PR-016-PIPELINE-CONFIG-UX-RESTORE-V2-P1.md
- docs\pr_templates\PriorWork_complete\PR-016-PIPELINE-CONFIG-UX-RESTORE-V2-P1.md:24: - `src/gui/views/pipeline_config_panel_v2.py`
- docs\pr_templates\PriorWork_complete\PR-016-PIPELINE-CONFIG-UX-RESTORE-V2-P1.md:51: ### 3.1 `pipeline_config_panel_v2.py` — Validation Surface
- docs\pr_templates\PriorWork_complete\PR-016-PIPELINE-CONFIG-UX-RESTORE-V2-P1.md:79: def validate_pipeline_config(self) -> Tuple[bool, str]:
- docs\pr_templates\PriorWork_complete\PR-016-PIPELINE-CONFIG-UX-RESTORE-V2-P1.md:92: is_valid, message = self.validate_pipeline_config()
- docs\pr_templates\PriorWork_complete\PR-016-PIPELINE-CONFIG-UX-RESTORE-V2-P1.md:93: pipeline_panel = self._app_state.get("pipeline_config_panel_v2")
- docs\pr_templates\PriorWork_complete\PR-016-PIPELINE-CONFIG-UX-RESTORE-V2-P1.md:107: - When `validate_pipeline_config` is called, update:
- docs\pr_templates\PriorWork_complete\PR-016-PIPELINE-CONFIG-UX-RESTORE-V2-P1.md:136: panel = self._app_state.get("pipeline_config_panel_v2")
- docs\pr_templates\PriorWork_complete\PR-016-PIPELINE-CONFIG-UX-RESTORE-V2-P1.md:152: - `tests/gui_v2/test_pipeline_config_validation_v2.py`:
- docs\pr_templates\PriorWork_complete\PR-016-PIPELINE-CONFIG-UX-RESTORE-V2-P1.md:159: - `tests/controller/test_pipeline_config_validation_v2.py`:
- docs\pr_templates\PriorWork_complete\PR-016-PIPELINE-CONFIG-UX-RESTORE-V2-P1.md:161: - Tests `validate_pipeline_config` logic independently (unit-level).

## docs\pr_templates\PriorWork_complete\PR-024-MAIN-WEBUI-LAUNCH-UX-BROWSER-READY-V2-P1.md
- docs\pr_templates\PriorWork_complete\PR-024-MAIN-WEBUI-LAUNCH-UX-BROWSER-READY-V2-P1.md:114: src/gui/views/pipeline_config_panel_v2.py

## docs\pr_templates\PriorWork_complete\PR-031-PIPELINE-CONFIG-LEFTCOLUMN-WIRING-V2-P1.md
- docs\pr_templates\PriorWork_complete\PR-031-PIPELINE-CONFIG-LEFTCOLUMN-WIRING-V2-P1.md:114: src/gui/panels_v2/pipeline_config_panel_v2.py
- docs\pr_templates\PriorWork_complete\PR-031-PIPELINE-CONFIG-LEFTCOLUMN-WIRING-V2-P1.md:215: Import PipelineConfigPanelV2 from src.gui.panels_v2.pipeline_config_panel_v2.
- docs\pr_templates\PriorWork_complete\PR-031-PIPELINE-CONFIG-LEFTCOLUMN-WIRING-V2-P1.md:235: Ensure naming is consistent with existing patterns (e.g., self.pipeline_config_panel if that’s the convention).
- docs\pr_templates\PriorWork_complete\PR-031-PIPELINE-CONFIG-LEFTCOLUMN-WIRING-V2-P1.md:239: In pipeline_config_panel_v2.py:
- docs\pr_templates\PriorWork_complete\PR-031-PIPELINE-CONFIG-LEFTCOLUMN-WIRING-V2-P1.md:335: Add a small assertion that the pipeline tab exposes a handle to pipeline_config_panel or similar, if that’s how it’s exposed.
- docs\pr_templates\PriorWork_complete\PR-031-PIPELINE-CONFIG-LEFTCOLUMN-WIRING-V2-P1.md:418: pipeline_config_panel_v2.py

## docs\pr_templates\PriorWork_complete\PR-032-BOTTOM-LOGGING-SURFACE-V2-P1.md
- docs\pr_templates\PriorWork_complete\PR-032-BOTTOM-LOGGING-SURFACE-V2-P1.md:189: src/gui/panels_v2/sidebar_panel_v2.py / pipeline_config_panel_v2.py (those are PR-031 domain)

## docs\pr_templates\PriorWork_complete\PR-033-PIPELINE-PRESETS-HOOKUP-V2-P1.md
- docs\pr_templates\PriorWork_complete\PR-033-PIPELINE-PRESETS-HOOKUP-V2-P1.md:147: src/gui/panels_v2/pipeline_config_panel_v2.py
- docs\pr_templates\PriorWork_complete\PR-033-PIPELINE-PRESETS-HOOKUP-V2-P1.md:332: File: src/gui/panels_v2/pipeline_config_panel_v2.py
- docs\pr_templates\PriorWork_complete\PR-033-PIPELINE-PRESETS-HOOKUP-V2-P1.md:491: src/gui/panels_v2/pipeline_config_panel_v2.py

## docs\pr_templates\PriorWork_complete\PR-033A-PIPELINE-LEFT-PANEL-UX-V2-P1.md
- docs\pr_templates\PriorWork_complete\PR-033A-PIPELINE-LEFT-PANEL-UX-V2-P1.md:72: src/gui/views/pipeline_config_panel_v2.py (or current config panel implementation)
- docs\pr_templates\PriorWork_complete\PR-033A-PIPELINE-LEFT-PANEL-UX-V2-P1.md:132: In pipeline_config_panel_v2.py, ensure:
- docs\pr_templates\PriorWork_complete\PR-033A-PIPELINE-LEFT-PANEL-UX-V2-P1.md:206: pipeline_config_panel_v2.py

## docs\pr_templates\PriorWork_complete\PR-034-PIPELINE-PRESETS-INTEGRATION-V2-P1.md
- docs\pr_templates\PriorWork_complete\PR-034-PIPELINE-PRESETS-INTEGRATION-V2-P1.md:78: src/gui/views/pipeline_config_panel_v2.py (read/write config fields)
- docs\pr_templates\PriorWork_complete\PR-034-PIPELINE-PRESETS-INTEGRATION-V2-P1.md:200: pipeline_config_panel_v2.py

## docs\pr_templates\PriorWork_complete\PR-035-PIPELINE-PACK-CONFIG-JOB-BUILDER-V2-P1.md
- docs\pr_templates\PriorWork_complete\PR-035-PIPELINE-PACK-CONFIG-JOB-BUILDER-V2-P1.md:176: src/gui/panels_v2/pipeline_config_panel_v2.py
- docs\pr_templates\PriorWork_complete\PR-035-PIPELINE-PACK-CONFIG-JOB-BUILDER-V2-P1.md:420: pipeline_config_panel_v2.py

## docs\pr_templates\PriorWork_complete\PR-036-PIPELINE-TAB-3COLUMN-LAYOUT-V2-P1.md
- docs\pr_templates\PriorWork_complete\PR-036-PIPELINE-TAB-3COLUMN-LAYOUT-V2-P1.md:113: src/gui/panels_v2/pipeline_config_panel_v2.py
- docs\pr_templates\PriorWork_complete\PR-036-PIPELINE-TAB-3COLUMN-LAYOUT-V2-P1.md:336: pipeline_config_panel_v2.py

## docs\pr_templates\PriorWork_complete\PR-037-Pipeline-LoRA-Strengths-V2-P1.md
- docs\pr_templates\PriorWork_complete\PR-037-Pipeline-LoRA-Strengths-V2-P1.md:108: src/gui/panels_v2/pipeline_config_panel_v2.py
- docs\pr_templates\PriorWork_complete\PR-037-Pipeline-LoRA-Strengths-V2-P1.md:167: In pipeline_config_panel_v2.py:
- docs\pr_templates\PriorWork_complete\PR-037-Pipeline-LoRA-Strengths-V2-P1.md:199: Call pipeline_config_panel.load_lora_strengths() with these values.
- docs\pr_templates\PriorWork_complete\PR-037-Pipeline-LoRA-Strengths-V2-P1.md:203: Read current LoRA strengths via pipeline_config_panel.get_lora_strengths().
- docs\pr_templates\PriorWork_complete\PR-037-Pipeline-LoRA-Strengths-V2-P1.md:277: pipeline_config_panel_v2.py

## docs\pr_templates\PriorWork_complete\PR-037A-Pipeline-LoRA-Strengths-V2-P1.md
- docs\pr_templates\PriorWork_complete\PR-037A-Pipeline-LoRA-Strengths-V2-P1.md:110: src/gui/panels_v2/pipeline_config_panel_v2.py
- docs\pr_templates\PriorWork_complete\PR-037A-Pipeline-LoRA-Strengths-V2-P1.md:169: In pipeline_config_panel_v2.py:
- docs\pr_templates\PriorWork_complete\PR-037A-Pipeline-LoRA-Strengths-V2-P1.md:201: Call pipeline_config_panel.load_lora_strengths() with these values.
- docs\pr_templates\PriorWork_complete\PR-037A-Pipeline-LoRA-Strengths-V2-P1.md:205: Read current LoRA strengths via pipeline_config_panel.get_lora_strengths().
- docs\pr_templates\PriorWork_complete\PR-037A-Pipeline-LoRA-Strengths-V2-P1.md:279: pipeline_config_panel_v2.py

## docs\pr_templates\PriorWork_complete\PR-038-Pipeline-Randomizer-Config-V2-P1.md
- docs\pr_templates\PriorWork_complete\PR-038-Pipeline-Randomizer-Config-V2-P1.md:119: src/gui/panels_v2/pipeline_config_panel_v2.py
- docs\pr_templates\PriorWork_complete\PR-038-Pipeline-Randomizer-Config-V2-P1.md:170: In pipeline_config_panel_v2.py:
- docs\pr_templates\PriorWork_complete\PR-038-Pipeline-Randomizer-Config-V2-P1.md:202: Call pipeline_config_panel.load_randomizer_config(...).
- docs\pr_templates\PriorWork_complete\PR-038-Pipeline-Randomizer-Config-V2-P1.md:274: pipeline_config_panel_v2.py

## docs\pr_templates\PriorWork_complete\PR-038A-Pipeline-Randomizer-Config-V2-P1.md
- docs\pr_templates\PriorWork_complete\PR-038A-Pipeline-Randomizer-Config-V2-P1.md:119: src/gui/panels_v2/pipeline_config_panel_v2.py
- docs\pr_templates\PriorWork_complete\PR-038A-Pipeline-Randomizer-Config-V2-P1.md:170: In pipeline_config_panel_v2.py:
- docs\pr_templates\PriorWork_complete\PR-038A-Pipeline-Randomizer-Config-V2-P1.md:202: Call pipeline_config_panel.load_randomizer_config(...).
- docs\pr_templates\PriorWork_complete\PR-038A-Pipeline-Randomizer-Config-V2-P1.md:274: pipeline_config_panel_v2.py

## docs\pr_templates\PriorWork_complete\PR-041-DESIGN-SYSTEM-THEME-V2-P1.md
- docs\pr_templates\PriorWork_complete\PR-041-DESIGN-SYSTEM-THEME-V2-P1.md:187: src/gui/panels_v2/pipeline_config_panel_v2.py

## docs\pr_templates\PriorWork_complete\PR-041-THEME-V2-DESIGN-TOKENS-UNIFICATION-V2-P1.md
- docs\pr_templates\PriorWork_complete\PR-041-THEME-V2-DESIGN-TOKENS-UNIFICATION-V2-P1.md:139: src/gui/panels_v2/pipeline_config_panel_v2.py

## docs\pr_templates\PriorWork_complete\PR-049 — GUI V2 Dropdowns, Payload Builder, & Last-Run.md
- docs\pr_templates\PriorWork_complete\PR-049 — GUI V2 Dropdowns, Payload Builder, & Last-Run.md:100: Add method build_pipeline_config_v2():

## docs\pr_templates\PriorWork_complete\PR-071-Pipeline-Execution-Wiring-V2-P1-20251201.md
- docs\pr_templates\PriorWork_complete\PR-071-Pipeline-Execution-Wiring-V2-P1-20251201.md:120: def run_pipeline(self, pipeline_config, learning_context=None) -> PipelineResult:
- docs\pr_templates\PriorWork_complete\PR-071-Pipeline-Execution-Wiring-V2-P1-20251201.md:122: - Validate pipeline_config
- docs\pr_templates\PriorWork_complete\PR-071-Pipeline-Execution-Wiring-V2-P1-20251201.md:177: self.controller.run_pipeline(self.app_state.build_pipeline_config())

## docs\pr_templates\PriorWork_complete\PR-072-RunPipeline-Facade-V2-P1-20251202.md
- docs\pr_templates\PriorWork_complete\PR-072-RunPipeline-Facade-V2-P1-20251202.md:139: Use whatever existing method(s) currently builds a PipelineConfig or equivalent object (e.g., self.app_state.build_pipeline_config() or similar).
- docs\pr_templates\PriorWork_complete\PR-072-RunPipeline-Facade-V2-P1-20251202.md:167: result = self.pipeline_runner.run(pipeline_config)
- docs\pr_templates\PriorWork_complete\PR-072-RunPipeline-Facade-V2-P1-20251202.md:258: def run(self, pipeline_config):
- docs\pr_templates\PriorWork_complete\PR-072-RunPipeline-Facade-V2-P1-20251202.md:259: self.run_calls.append(pipeline_config)
- docs\pr_templates\PriorWork_complete\PR-072-RunPipeline-Facade-V2-P1-20251202.md:263: The exact shape of pipeline_config doesn’t matter for this PR; tests only care that run was called and resulted in one entry in run_calls.

## docs\pr_templates\PriorWork_complete\PR-074-Upscale-Pipeline-Logic-V2-P1-20251202.md
- docs\pr_templates\PriorWork_complete\PR-074-Upscale-Pipeline-Logic-V2-P1-20251202.md:395: pipeline_config = self.build_pipeline_config_v2()
- docs\pr_templates\PriorWork_complete\PR-074-Upscale-Pipeline-Logic-V2-P1-20251202.md:399: return runner.run(pipeline_config, None, self._append_log_threadsafe)

## docs\pr_templates\PriorWork_complete\PR-078-Journey-Test-API-Shims-V2-P1-20251202.md
- docs\pr_templates\PriorWork_complete\PR-078-Journey-Test-API-Shims-V2-P1-20251202.md:20: Ensure JT05 and the V2 full-pipeline journey set a minimal valid RunConfig (model, sampler, steps) so AppController.run_pipeline() passes _validate_pipeline_config() and actually calls the runner/WebUI mocks.

## docs\pr_templates\PriorWork_complete\PR-081D-4 — RunConfig Refiner-Hires Fields.md
- docs\pr_templates\PriorWork_complete\PR-081D-4 — RunConfig Refiner-Hires Fields.md:44: src/gui/panels_v2/pipeline_config_panel_v2.py

## docs\pr_templates\PriorWork_complete\PR-081D-7 — GUI Harness Cleanup Pytest Marker.md
- docs\pr_templates\PriorWork_complete\PR-081D-7 — GUI Harness Cleanup Pytest Marker.md:34: src/gui/panels_v2/pipeline_config_panel_v2.py  (checkbox order if required)

## docs\pr_templates\PriorWork_complete\PR-087 – Controller RunConfig & GUI Entrypoint Wiring (V2.5).md
- docs\pr_templates\PriorWork_complete\PR-087 – Controller RunConfig & GUI Entrypoint Wiring (V2.5).md:88: tests/controller/test_app_controller_pipeline_integration.py::test_pipeline_config_assembled_from_controller_state
- docs\pr_templates\PriorWork_complete\PR-087 – Controller RunConfig & GUI Entrypoint Wiring (V2.5).md:148: Ensure that the method assembling pipeline config (e.g. AppController._assemble_pipeline_config() or call into pipeline_config_assembler) consumes RunConfig correctly.
- docs\pr_templates\PriorWork_complete\PR-087 – Controller RunConfig & GUI Entrypoint Wiring (V2.5).md:150: Fix test_pipeline_config_assembled_from_controller_state by:
- docs\pr_templates\PriorWork_complete\PR-087 – Controller RunConfig & GUI Entrypoint Wiring (V2.5).md:284: test_pipeline_config_assembled_from_controller_state sees a correctly assembled pipeline config derived from run_config.
- docs\pr_templates\PriorWork_complete\PR-087 – Controller RunConfig & GUI Entrypoint Wiring (V2.5).md:338: test_pipeline_config_assembled_from_controller_state

## docs\pr_templates\PriorWork_complete\PR-107 – StageSequencer + StageExecutionPlan Backbone.md
- docs\pr_templates\PriorWork_complete\PR-107 – StageSequencer + StageExecutionPlan Backbone.md:23: StageSequencer.build_plan(pipeline_config) becomes the single place where we:
- docs\pr_templates\PriorWork_complete\PR-107 – StageSequencer + StageExecutionPlan Backbone.md:25: Interpret the high-level pipeline_config.
- docs\pr_templates\PriorWork_complete\PR-107 – StageSequencer + StageExecutionPlan Backbone.md:146: 4. StageSequencer.build_plan(pipeline_config)
- docs\pr_templates\PriorWork_complete\PR-107 – StageSequencer + StageExecutionPlan Backbone.md:153: def build_plan(self, pipeline_config: Mapping[str, Any]) -> StageExecutionPlan:
- docs\pr_templates\PriorWork_complete\PR-107 – StageSequencer + StageExecutionPlan Backbone.md:156: 4.1 Expected pipeline_config inputs
- docs\pr_templates\PriorWork_complete\PR-107 – StageSequencer + StageExecutionPlan Backbone.md:162: pipeline_config["txt2img_enabled"]  # bool
- docs\pr_templates\PriorWork_complete\PR-107 – StageSequencer + StageExecutionPlan Backbone.md:163: pipeline_config["img2img_enabled"]  # bool
- docs\pr_templates\PriorWork_complete\PR-107 – StageSequencer + StageExecutionPlan Backbone.md:168: pipeline_config["upscale_enabled"]
- docs\pr_templates\PriorWork_complete\PR-107 – StageSequencer + StageExecutionPlan Backbone.md:169: pipeline_config["adetailer_enabled"]
- docs\pr_templates\PriorWork_complete\PR-107 – StageSequencer + StageExecutionPlan Backbone.md:174: pipeline_config["refiner_enabled"]
- docs\pr_templates\PriorWork_complete\PR-107 – StageSequencer + StageExecutionPlan Backbone.md:175: pipeline_config["refiner_model_name"]
- docs\pr_templates\PriorWork_complete\PR-107 – StageSequencer + StageExecutionPlan Backbone.md:176: pipeline_config["refiner_switch_step"]
- docs\pr_templates\PriorWork_complete\PR-107 – StageSequencer + StageExecutionPlan Backbone.md:178: pipeline_config["hires_enabled"]
- docs\pr_templates\PriorWork_complete\PR-107 – StageSequencer + StageExecutionPlan Backbone.md:179: pipeline_config["hires_upscaler_name"]
- docs\pr_templates\PriorWork_complete\PR-107 – StageSequencer + StageExecutionPlan Backbone.md:180: pipeline_config["hires_denoise_strength"]
- docs\pr_templates\PriorWork_complete\PR-107 – StageSequencer + StageExecutionPlan Backbone.md:181: pipeline_config["hires_scale_factor"]
- docs\pr_templates\PriorWork_complete\PR-107 – StageSequencer + StageExecutionPlan Backbone.md:194: txt2img_enabled = bool(pipeline_config.get("txt2img_enabled"))
- docs\pr_templates\PriorWork_complete\PR-107 – StageSequencer + StageExecutionPlan Backbone.md:195: img2img_enabled = bool(pipeline_config.get("img2img_enabled"))
- docs\pr_templates\PriorWork_complete\PR-107 – StageSequencer + StageExecutionPlan Backbone.md:196: upscale_enabled = bool(pipeline_config.get("upscale_enabled"))
- docs\pr_templates\PriorWork_complete\PR-107 – StageSequencer + StageExecutionPlan Backbone.md:197: adetailer_enabled = bool(pipeline_config.get("adetailer_enabled"))
- docs\pr_templates\PriorWork_complete\PR-107 – StageSequencer + StageExecutionPlan Backbone.md:208: config=pipeline_config.get("txt2img_config") or {},
- docs\pr_templates\PriorWork_complete\PR-107 – StageSequencer + StageExecutionPlan Backbone.md:222: config=pipeline_config.get("img2img_config") or {},
- docs\pr_templates\PriorWork_complete\PR-107 – StageSequencer + StageExecutionPlan Backbone.md:231: config=pipeline_config.get("upscale_config") or {},
- docs\pr_templates\PriorWork_complete\PR-107 – StageSequencer + StageExecutionPlan Backbone.md:238: config=pipeline_config.get("adetailer_config") or {},
- docs\pr_templates\PriorWork_complete\PR-107 – StageSequencer + StageExecutionPlan Backbone.md:278: def run(self, pipeline_config: Mapping[str, Any]) -> RunResult:
- docs\pr_templates\PriorWork_complete\PR-107 – StageSequencer + StageExecutionPlan Backbone.md:458: StageSequencer.build_plan(pipeline_config):
- docs\pr_templates\PriorWork_complete\PR-107 – StageSequencer + StageExecutionPlan Backbone.md:482: Once this lands, the stage pipeline becomes deterministic and auditable: controllers and jobs feed a single pipeline_config → StageSequencer.build_plan → PipelineRunner.run(plan) chain, and every change to stage ordering or refiner/hires logic can be tested in isolation.

## docs\pr_templates\PriorWork_complete\PR-B — Canonical JobPart-JobBundle + Builder (V2.5).md
- docs\pr_templates\PriorWork_complete\PR-B — Canonical JobPart-JobBundle + Builder (V2.5).md:344: test_pipeline_config_snapshot_basic_defaults:
- docs\pr_templates\PriorWork_complete\PR-B — Canonical JobPart-JobBundle + Builder (V2.5).md:348: test_pipeline_config_snapshot_copy_with_overrides:
- docs\pr_templates\PriorWork_complete\PR-B — Canonical JobPart-JobBundle + Builder (V2.5).md:477: test_pipeline_config_snapshot_basic_defaults
- docs\pr_templates\PriorWork_complete\PR-B — Canonical JobPart-JobBundle + Builder (V2.5).md:479: test_pipeline_config_snapshot_copy_with_overrides

## docs\pr_templates\PriorWork_complete\PR-GUI-V2-MIGRATION-003_Real_Pipeline_Config_Behavior.md
- docs\pr_templates\PriorWork_complete\PR-GUI-V2-MIGRATION-003_Real_Pipeline_Config_Behavior.md:62: - tests/gui_v2/test_gui_v2_pipeline_config_roundtrip.py (new)
- docs\pr_templates\PriorWork_complete\PR-GUI-V2-MIGRATION-003_Real_Pipeline_Config_Behavior.md:160: 2) tests/gui_v2/test_gui_v2_pipeline_config_roundtrip.py (new)
- docs\pr_templates\PriorWork_complete\PR-GUI-V2-MIGRATION-003_Real_Pipeline_Config_Behavior.md:227: - tests/gui_v2/test_gui_v2_pipeline_config_roundtrip.py

## docs\pr_templates\PriorWork_complete\PR-GUI-V2-MIGRATION-004_StatusBarV2_Progress_ETA.md
- docs\pr_templates\PriorWork_complete\PR-GUI-V2-MIGRATION-004_StatusBarV2_Progress_ETA.md:276: - Existing GUI V2 tests (`test_gui_v2_layout_skeleton.py`, `test_gui_v2_pipeline_button_wiring.py`, `test_gui_v2_pipeline_config_roundtrip.py`, `test_gui_v2_startup.py`) still pass.

## docs\pr_templates\PriorWork_complete\PR-GUI-V2-NAMING-003_V2-P1.md
- docs\pr_templates\PriorWork_complete\PR-GUI-V2-NAMING-003_V2-P1.md:60: 9. `src/gui/views/pipeline_config_panel.py`
- docs\pr_templates\PriorWork_complete\PR-GUI-V2-NAMING-003_V2-P1.md:61: → `src/gui/views/pipeline_config_panel_v2.py`
- docs\pr_templates\PriorWork_complete\PR-GUI-V2-NAMING-003_V2-P1.md:102: from .pipeline_config_panel import PipelineConfigPanel  # noqa: F401
- docs\pr_templates\PriorWork_complete\PR-GUI-V2-NAMING-003_V2-P1.md:113: from .pipeline_config_panel_v2 import PipelineConfigPanel  # noqa: F401

## docs\pr_templates\PriorWork_complete\PR-GUI-V2-PIPELINE-CONFIG-WIRING-002-(2025-11-26).md
- docs\pr_templates\PriorWork_complete\PR-GUI-V2-PIPELINE-CONFIG-WIRING-002-(2025-11-26).md:11: src/pipeline/pipeline_config_assembler.py
- docs\pr_templates\PriorWork_complete\PR-GUI-V2-PIPELINE-CONFIG-WIRING-002-(2025-11-26).md:29: PipelineController._build_pipeline_config_from_state() uses that state to call
- docs\pr_templates\PriorWork_complete\PR-GUI-V2-PIPELINE-CONFIG-WIRING-002-(2025-11-26).md:67: Ensure PipelineController._build_pipeline_config_from_state() produces a fully populated PipelineConfig by calling:
- docs\pr_templates\PriorWork_complete\PR-GUI-V2-PIPELINE-CONFIG-WIRING-002-(2025-11-26).md:127: def _build_pipeline_config_from_state(self) -> PipelineConfig:
- docs\pr_templates\PriorWork_complete\PR-GUI-V2-PIPELINE-CONFIG-WIRING-002-(2025-11-26).md:345: In PipelineController._build_pipeline_config_from_state() or before run_pipeline:
- docs\pr_templates\PriorWork_complete\PR-GUI-V2-PIPELINE-CONFIG-WIRING-002-(2025-11-26).md:450: _build_pipeline_config_from_state() yields correct overrides.

## docs\pr_templates\PriorWork_complete\PR-GUI-V2-PIPELINE-STAGECARDS-001-Wire Cards-11-26-2025-0816.md
- docs\pr_templates\PriorWork_complete\PR-GUI-V2-PIPELINE-STAGECARDS-001-Wire Cards-11-26-2025-0816.md:368: controller.update_pipeline_config(cfg)

## docs\pr_templates\PriorWork_complete\PR-GUI-V2-PIPELINE-TAB-002.md
- docs\pr_templates\PriorWork_complete\PR-GUI-V2-PIPELINE-TAB-002.md:266: - `src/gui/views/pipeline_config_panel.py` (new):

## docs\pr_templates\PriorWork_complete\PR-LEARN-PROFILES-001-Model & LoRA Profile Sidecars as Priors for Learning.md
- docs\pr_templates\PriorWork_complete\PR-LEARN-PROFILES-001-Model & LoRA Profile Sidecars as Priors for Learning.md:335: def build_pipeline_config_with_profiles(
- docs\pr_templates\PriorWork_complete\PR-LEARN-PROFILES-001-Model & LoRA Profile Sidecars as Priors for Learning.md:411: test_build_pipeline_config_with_profiles_applies_suggested_preset
- docs\pr_templates\PriorWork_complete\PR-LEARN-PROFILES-001-Model & LoRA Profile Sidecars as Priors for Learning.md:415: Call build_pipeline_config_with_profiles and assert the resulting PipelineConfig matches those values, absent user overrides.
- docs\pr_templates\PriorWork_complete\PR-LEARN-PROFILES-001-Model & LoRA Profile Sidecars as Priors for Learning.md:417: test_build_pipeline_config_with_profiles_respects_user_overrides
- docs\pr_templates\PriorWork_complete\PR-LEARN-PROFILES-001-Model & LoRA Profile Sidecars as Priors for Learning.md:421: test_build_pipeline_config_with_profiles_falls_back_without_profiles
- docs\pr_templates\PriorWork_complete\PR-LEARN-PROFILES-001-Model & LoRA Profile Sidecars as Priors for Learning.md:441: pytest tests/learning/test_profile_integration.py::test_build_pipeline_config_with_profiles_applies_suggested_preset -v
- docs\pr_templates\PriorWork_complete\PR-LEARN-PROFILES-001-Model & LoRA Profile Sidecars as Priors for Learning.md:443: pytest tests/learning/test_profile_integration.py::test_build_pipeline_config_with_profiles_respects_user_overrides -v
- docs\pr_templates\PriorWork_complete\PR-LEARN-PROFILES-001-Model & LoRA Profile Sidecars as Priors for Learning.md:445: pytest tests/learning/test_profile_integration.py::test_build_pipeline_config_with_profiles_falls_back_without_profiles -v
- docs\pr_templates\PriorWork_complete\PR-LEARN-PROFILES-001-Model & LoRA Profile Sidecars as Priors for Learning.md:471: build_pipeline_config_with_profiles:
- docs\pr_templates\PriorWork_complete\PR-LEARN-PROFILES-001-Model & LoRA Profile Sidecars as Priors for Learning.md:579: Call build_pipeline_config_with_profiles and:
- docs\pr_templates\PriorWork_complete\PR-LEARN-PROFILES-001-Model & LoRA Profile Sidecars as Priors for Learning.md:591: Call build_pipeline_config_with_profiles.

## docs\pr_templates\PriorWork_complete\PR-LEARN-V2-RECORDWRITER-001_pipeline_learningrecord_integration.md
- docs\pr_templates\PriorWork_complete\PR-LEARN-V2-RECORDWRITER-001_pipeline_learningrecord_integration.md:114: pipeline_config: PipelineConfig,

## docs\pr_templates\PriorWork_complete\PR-PIPE-CORE-01_Addendum_Bundle\PR-PIPE-CORE-01_Addendum_PipelineRunner_Location_and_Construction.md
- docs\pr_templates\PriorWork_complete\PR-PIPE-CORE-01_Addendum_Bundle\PR-PIPE-CORE-01_Addendum_PipelineRunner_Location_and_Construction.md:92: - Call `self._pipeline_runner.run(pipeline_config, self._cancel_token)` in the worker thread.

## docs\pr_templates\PriorWork_complete\PR-QUEUE-V2-JOBMODEL-001_queue_model_and_single_node_runner_skeleton.md
- docs\pr_templates\PriorWork_complete\PR-QUEUE-V2-JOBMODEL-001_queue_model_and_single_node_runner_skeleton.md:97: pipeline_config: PipelineConfig

## docs\pr_templates\PriorWork_complete\PR-WIRE-01-V2.5 – “Minimal Happy Path”-11-26-2025-1918.md
- docs\pr_templates\PriorWork_complete\PR-WIRE-01-V2.5 – “Minimal Happy Path”-11-26-2025-1918.md:36: - Various V2 panels (e.g., `core_config_panel_v2.py`, `model_manager_panel_v2.py`, `pipeline_config_panel_v2.py`, `prompt_editor_panel_v2.py`, `status_bar_v2.py`, etc.)
- docs\pr_templates\PriorWork_complete\PR-WIRE-01-V2.5 – “Minimal Happy Path”-11-26-2025-1918.md:169: - For example, something like `run_pipeline(pipeline_config)` or `execute_txt2img(config)`.

## docs\pr_templates\PriorWork_complete\PR-WIRE-02-V2.5 – Entrypoint Contracts (11-26-2025-1916).md
- docs\pr_templates\PriorWork_complete\PR-WIRE-02-V2.5 – Entrypoint Contracts (11-26-2025-1916).md:31: - `tests/gui_v2/test_gui_v2_pipeline_config_roundtrip.py::test_pipeline_panel_loads_initial_config`
- docs\pr_templates\PriorWork_complete\PR-WIRE-02-V2.5 – Entrypoint Contracts (11-26-2025-1916).md:32: - `tests/gui_v2/test_gui_v2_pipeline_config_roundtrip.py::test_pipeline_panel_run_roundtrip`
- docs\pr_templates\PriorWork_complete\PR-WIRE-02-V2.5 – Entrypoint Contracts (11-26-2025-1916).md:73: - `tests/gui_v2/test_gui_v2_pipeline_config_roundtrip.py`
- docs\pr_templates\PriorWork_complete\PR-WIRE-02-V2.5 – Entrypoint Contracts (11-26-2025-1916).md:238: pytest tests/gui_v2/test_gui_v2_pipeline_config_roundtrip.py -q

## docs\pr_templates\PriorWork_complete\PR-WIRE-03-V2.5-11-26-2025.md
- docs\pr_templates\PriorWork_complete\PR-WIRE-03-V2.5-11-26-2025.md:89: - `src/gui/pipeline_config_panel_v2.py` or equivalent PipelinePanelV2 implementation.
- docs\pr_templates\PriorWork_complete\PR-WIRE-03-V2.5-11-26-2025.md:172: Inspect src/gui/pipeline_config_panel_v2.py (or wherever PipelinePanelV2 is implemented):

## docs\pr_templates\PriorWork_complete\Script for PR-#51 – Core Config Panel V2.md
- docs\pr_templates\PriorWork_complete\Script for PR-#51 – Core Config Panel V2.md:38: src/controller/pipeline_config_assembler.py
- docs\pr_templates\PriorWork_complete\Script for PR-#51 – Core Config Panel V2.md:46: tests/controller/test_pipeline_config_assembler_core_fields.py (new or extend existing)
- docs\pr_templates\PriorWork_complete\Script for PR-#51 – Core Config Panel V2.md:138: In pipeline_config_assembler.py:
- docs\pr_templates\PriorWork_complete\Script for PR-#51 – Core Config Panel V2.md:160: pytest tests/controller/test_pipeline_config_assembler_core_fields.py -v
- docs\pr_templates\PriorWork_complete\Script for PR-#51 – Core Config Panel V2.md:188: pytest tests/controller/test_pipeline_config_assembler_core_fields.py -v

## docs\pr_templates\PriorWork_complete\Script for PR-#52 – Negative Prompt Panel V2.md
- docs\pr_templates\PriorWork_complete\Script for PR-#52 – Negative Prompt Panel V2.md:40: src/controller/pipeline_config_assembler.py
- docs\pr_templates\PriorWork_complete\Script for PR-#52 – Negative Prompt Panel V2.md:48: tests/controller/test_pipeline_config_assembler_negative_prompt.py (new)
- docs\pr_templates\PriorWork_complete\Script for PR-#52 – Negative Prompt Panel V2.md:114: In pipeline_config_assembler.py:
- docs\pr_templates\PriorWork_complete\Script for PR-#52 – Negative Prompt Panel V2.md:130: pytest tests/controller/test_pipeline_config_assembler_negative_prompt.py -v
- docs\pr_templates\PriorWork_complete\Script for PR-#52 – Negative Prompt Panel V2.md:156: pytest tests/controller/test_pipeline_config_assembler_negative_prompt.py -v

## docs\pr_templates\PriorWork_complete\Script for PR-#54 – Output Settings Panel V2.md
- docs\pr_templates\PriorWork_complete\Script for PR-#54 – Output Settings Panel V2.md:38: src/controller/pipeline_config_assembler.py
- docs\pr_templates\PriorWork_complete\Script for PR-#54 – Output Settings Panel V2.md:46: tests/controller/test_pipeline_config_assembler_output_settings.py (new)
- docs\pr_templates\PriorWork_complete\Script for PR-#54 – Output Settings Panel V2.md:112: In pipeline_config_assembler.py:
- docs\pr_templates\PriorWork_complete\Script for PR-#54 – Output Settings Panel V2.md:128: pytest tests/controller/test_pipeline_config_assembler_output_settings.py -v
- docs\pr_templates\PriorWork_complete\Script for PR-#54 – Output Settings Panel V2.md:154: pytest tests/controller/test_pipeline_config_assembler_output_settings.py -v

## docs\pr_templates\PriorWork_complete\Script for PR-#55 – Model Manager Panel V2.md
- docs\pr_templates\PriorWork_complete\Script for PR-#55 – Model Manager Panel V2.md:38: src/controller/pipeline_config_assembler.py
- docs\pr_templates\PriorWork_complete\Script for PR-#55 – Model Manager Panel V2.md:48: tests/controller/test_pipeline_config_assembler_model_fields.py (new or extend)
- docs\pr_templates\PriorWork_complete\Script for PR-#55 – Model Manager Panel V2.md:116: In pipeline_config_assembler.py:
- docs\pr_templates\PriorWork_complete\Script for PR-#55 – Model Manager Panel V2.md:132: pytest tests/controller/test_pipeline_config_assembler_model_fields.py -v
- docs\pr_templates\PriorWork_complete\Script for PR-#55 – Model Manager Panel V2.md:158: pytest tests/controller/test_pipeline_config_assembler_model_fields.py -v

## docs\pr_templates\PriorWork_complete\StableNew PR-091 – AppController ↔ PipelineController Bridge.md
- docs\pr_templates\PriorWork_complete\StableNew PR-091 – AppController ↔ PipelineController Bridge.md:220: is_valid, message = self._validate_pipeline_config()
- docs\pr_templates\PriorWork_complete\StableNew PR-091 – AppController ↔ PipelineController Bridge.md:230: builds pipeline_config via build_pipeline_config_v2(),

## inventory\stable_v2_inventory.json
- inventory\stable_v2_inventory.json:519: "tests/controller/__pycache__/test_pipeline_config_assembler.cpython-310-pytest-9.0.1.pyc",
- inventory\stable_v2_inventory.json:520: "tests/controller/__pycache__/test_pipeline_config_assembler_core_fields.cpython-310-pytest-9.0.1.pyc",
- inventory\stable_v2_inventory.json:521: "tests/controller/__pycache__/test_pipeline_config_assembler_model_fields.cpython-310-pytest-9.0.1.pyc",
- inventory\stable_v2_inventory.json:522: "tests/controller/__pycache__/test_pipeline_config_assembler_negative_prompt.cpython-310-pytest-9.0.1.pyc",
- inventory\stable_v2_inventory.json:523: "tests/controller/__pycache__/test_pipeline_config_assembler_output_settings.cpython-310-pytest-9.0.1.pyc",
- inventory\stable_v2_inventory.json:524: "tests/controller/__pycache__/test_pipeline_config_assembler_resolution.cpython-310-pytest-9.0.1.pyc",
- inventory\stable_v2_inventory.json:1587: ".mypy_cache/3.11/src/controller/pipeline_config_assembler.data.json",
- inventory\stable_v2_inventory.json:1588: ".mypy_cache/3.11/src/controller/pipeline_config_assembler.meta.json",
- inventory\stable_v2_inventory.json:1843: ".mypy_cache/3.11/tests/controller/test_pipeline_config_assembler.data.json",
- inventory\stable_v2_inventory.json:1844: ".mypy_cache/3.11/tests/controller/test_pipeline_config_assembler.meta.json",
- inventory\stable_v2_inventory.json:5538: "htmlcov/z_7da4a89bed7a4ad5_pipeline_config_panel_py.html",
- inventory\stable_v2_inventory.json:5558: "htmlcov/z_ac5b274346abdaff_pipeline_config_assembler_py.html",
- inventory\stable_v2_inventory.json:5932: "src/controller/pipeline_config_assembler.py",
- inventory\stable_v2_inventory.json:6158: "src/gui/views/pipeline_config_panel.py",
- inventory\stable_v2_inventory.json:6486: "src/gui/views/__pycache__/pipeline_config_panel.cpython-310.pyc",
- inventory\stable_v2_inventory.json:6574: "tests/controller/test_pipeline_config_assembler.py",
- inventory\stable_v2_inventory.json:6575: "tests/controller/test_pipeline_config_assembler_core_fields.py",
- inventory\stable_v2_inventory.json:6576: "tests/controller/test_pipeline_config_assembler_model_fields.py",
- inventory\stable_v2_inventory.json:6577: "tests/controller/test_pipeline_config_assembler_negative_prompt.py",
- inventory\stable_v2_inventory.json:6578: "tests/controller/test_pipeline_config_assembler_output_settings.py",
- inventory\stable_v2_inventory.json:6579: "tests/controller/test_pipeline_config_assembler_resolution.py",
- inventory\stable_v2_inventory.json:6714: ".mypy_cache/3.11/src/gui/panels_v2/pipeline_config_panel_v2.data.json",
- inventory\stable_v2_inventory.json:6715: ".mypy_cache/3.11/src/gui/panels_v2/pipeline_config_panel_v2.meta.json",
- inventory\stable_v2_inventory.json:6748: ".mypy_cache/3.11/src/gui/views/pipeline_config_panel_v2.data.json",
- inventory\stable_v2_inventory.json:6749: ".mypy_cache/3.11/src/gui/views/pipeline_config_panel_v2.meta.json",
- inventory\stable_v2_inventory.json:6812: ".mypy_cache/3.11/tests/gui_v2/test_gui_v2_pipeline_config_roundtrip.data.json",
- inventory\stable_v2_inventory.json:6813: ".mypy_cache/3.11/tests/gui_v2/test_gui_v2_pipeline_config_roundtrip.meta.json",
- inventory\stable_v2_inventory.json:6944: "htmlcov/z_ac9e25382994b44b_pipeline_config_panel_v2_py.html",
- inventory\stable_v2_inventory.json:6969: "src/controller/__pycache__/pipeline_config_assembler.cpython-310.pyc",
- inventory\stable_v2_inventory.json:6999: "src/gui/panels_v2/pipeline_config_panel_v2.py",
- inventory\stable_v2_inventory.json:7002: "src/gui/panels_v2/__pycache__/pipeline_config_panel_v2.cpython-310.pyc",
- inventory\stable_v2_inventory.json:7042: "src/gui/views/.mypy_cache/3.11/src/gui/views/pipeline_config_panel_v2.data.json",
- inventory\stable_v2_inventory.json:7043: "src/gui/views/.mypy_cache/3.11/src/gui/views/pipeline_config_panel_v2.meta.json",
- inventory\stable_v2_inventory.json:7049: "src/gui/views/__pycache__/pipeline_config_panel_v2.cpython-310.pyc",
- inventory\stable_v2_inventory.json:7138: "tests/gui_v2/test_pipeline_config_panel_lora_runtime.py",
- inventory\stable_v2_inventory.json:7180: "tests/gui_v2/__pycache__/test_gui_v2_pipeline_config_roundtrip.cpython-310-pytest-9.0.1.pyc",
- inventory\stable_v2_inventory.json:7207: "tests/gui_v2/__pycache__/test_pipeline_config_panel_lora_runtime.cpython-310-pytest-9.0.1.pyc",

## repo_inventory.json
- repo_inventory.json:353: "path": "src/controller/pipeline_config_assembler.py",
- repo_inventory.json:354: "module": "src.controller.pipeline_config_assembler",
- repo_inventory.json:395: "src.controller.pipeline_config_assembler",
- repo_inventory.json:1548: "src.gui.pipeline_config_panel",
- repo_inventory.json:1624: "path": "src/gui/views/pipeline_config_panel.py",
- repo_inventory.json:1625: "module": "src.gui.views.pipeline_config_panel",
- repo_inventory.json:2890: "path": "tests/controller/test_pipeline_config_assembler.py",
- repo_inventory.json:2891: "module": "tests.controller.test_pipeline_config_assembler",
- repo_inventory.json:2897: "src.controller.pipeline_config_assembler"
- repo_inventory.json:2902: "path": "tests/controller/test_pipeline_config_assembler_core_fields.py",
- repo_inventory.json:2903: "module": "tests.controller.test_pipeline_config_assembler_core_fields",
- repo_inventory.json:2910: "src.controller.pipeline_config_assembler"
- repo_inventory.json:2915: "path": "tests/controller/test_pipeline_config_assembler_model_fields.py",
- repo_inventory.json:2916: "module": "tests.controller.test_pipeline_config_assembler_model_fields",
- repo_inventory.json:2922: "src.controller.pipeline_config_assembler"
- repo_inventory.json:2927: "path": "tests/controller/test_pipeline_config_assembler_negative_prompt.py",
- repo_inventory.json:2928: "module": "tests.controller.test_pipeline_config_assembler_negative_prompt",
- repo_inventory.json:2934: "src.controller.pipeline_config_assembler"
- repo_inventory.json:2939: "path": "tests/controller/test_pipeline_config_assembler_output_settings.py",
- repo_inventory.json:2940: "module": "tests.controller.test_pipeline_config_assembler_output_settings",
- repo_inventory.json:2946: "src.controller.pipeline_config_assembler"
- repo_inventory.json:2951: "path": "tests/controller/test_pipeline_config_assembler_resolution.py",
- repo_inventory.json:2952: "module": "tests.controller.test_pipeline_config_assembler_resolution",
- repo_inventory.json:2958: "src.controller.pipeline_config_assembler"
- repo_inventory.json:2973: "src.controller.pipeline_config_assembler",
- repo_inventory.json:3302: "path": "tests/gui_v2/test_gui_v2_pipeline_config_roundtrip.py",
- repo_inventory.json:3303: "module": "tests.gui_v2.test_gui_v2_pipeline_config_roundtrip",

## reports\file_access\CLEANHOUSE_REPORT_V2_5_2025_11_26.md
- reports\file_access\CLEANHOUSE_REPORT_V2_5_2025_11_26.md:30: - `src/controller/pipeline_config_assembler.py` | touched: false | reachable_from_main: true
- reports\file_access\CLEANHOUSE_REPORT_V2_5_2025_11_26.md:164: - `tests/controller/test_pipeline_config_assembler.py` | touched: false | reachable_from_main: false | TEST
- reports\file_access\CLEANHOUSE_REPORT_V2_5_2025_11_26.md:165: - `tests/controller/test_pipeline_config_assembler_core_fields.py` | touched: false | reachable_from_main: false | TEST
- reports\file_access\CLEANHOUSE_REPORT_V2_5_2025_11_26.md:166: - `tests/controller/test_pipeline_config_assembler_model_fields.py` | touched: false | reachable_from_main: false | TEST
- reports\file_access\CLEANHOUSE_REPORT_V2_5_2025_11_26.md:167: - `tests/controller/test_pipeline_config_assembler_negative_prompt.py` | touched: false | reachable_from_main: false | TEST
- reports\file_access\CLEANHOUSE_REPORT_V2_5_2025_11_26.md:168: - `tests/controller/test_pipeline_config_assembler_output_settings.py` | touched: false | reachable_from_main: false | TEST
- reports\file_access\CLEANHOUSE_REPORT_V2_5_2025_11_26.md:169: - `tests/controller/test_pipeline_config_assembler_resolution.py` | touched: false | reachable_from_main: false | TEST
- reports\file_access\CLEANHOUSE_REPORT_V2_5_2025_11_26.md:228: - `tests/gui_v2/test_gui_v2_pipeline_config_roundtrip.py` | touched: false | reachable_from_main: false | TEST

## reports\file_access\file_access_summary.csv
- reports\file_access\file_access_summary.csv:28: src/controller/pipeline_config_assembler.py,false,,true,true,false,false,false,A_RUNTIME_CORE,
- reports\file_access\file_access_summary.csv:152: tests/controller/test_pipeline_config_assembler.py,false,,false,false,true,false,false,C_TEST,
- reports\file_access\file_access_summary.csv:153: tests/controller/test_pipeline_config_assembler_core_fields.py,false,,false,false,true,false,false,C_TEST,
- reports\file_access\file_access_summary.csv:154: tests/controller/test_pipeline_config_assembler_model_fields.py,false,,false,false,true,false,false,C_TEST,
- reports\file_access\file_access_summary.csv:155: tests/controller/test_pipeline_config_assembler_negative_prompt.py,false,,false,false,true,false,false,C_TEST,
- reports\file_access\file_access_summary.csv:156: tests/controller/test_pipeline_config_assembler_output_settings.py,false,,false,false,true,false,false,C_TEST,
- reports\file_access\file_access_summary.csv:157: tests/controller/test_pipeline_config_assembler_resolution.py,false,,false,false,true,false,false,C_TEST,
- reports\file_access\file_access_summary.csv:216: tests/gui_v2/test_gui_v2_pipeline_config_roundtrip.py,false,,false,false,true,false,false,C_TEST,

## scripts\list_pipeline_config_refs.py
- scripts\list_pipeline_config_refs.py:3: Generate pipeline_config_refs.md listing all occurrences of "pipeline_config"
- scripts\list_pipeline_config_refs.py:16: OUTPUT = ROOT / "pipeline_config_refs.md"
- scripts\list_pipeline_config_refs.py:21: "pipeline_config",
- scripts\list_pipeline_config_refs.py:53: f.write("# pipeline_config references (excluding archive/.git/zip)\n\n")

## snapshots\repo_inventory.json
- snapshots\repo_inventory.json:773: "path": "archive/legacy_tests/tests_gui_v2_legacy/test_gui_v2_pipeline_config_roundtrip.py",
- snapshots\repo_inventory.json:5393: "path": "src/controller/pipeline_config_assembler.py",
- snapshots\repo_inventory.json:5703: "path": "src/gui/panels_v2/pipeline_config_panel_v2.py",
- snapshots\repo_inventory.json:5843: "path": "src/gui/views/pipeline_config_panel.py",
- snapshots\repo_inventory.json:6813: "path": "tests/controller/test_pipeline_config_assembler.py",
- snapshots\repo_inventory.json:6818: "path": "tests/controller/test_pipeline_config_assembler_core_fields.py",
- snapshots\repo_inventory.json:6823: "path": "tests/controller/test_pipeline_config_assembler_model_fields.py",
- snapshots\repo_inventory.json:6828: "path": "tests/controller/test_pipeline_config_assembler_negative_prompt.py",
- snapshots\repo_inventory.json:6833: "path": "tests/controller/test_pipeline_config_assembler_output_settings.py",
- snapshots\repo_inventory.json:6838: "path": "tests/controller/test_pipeline_config_assembler_resolution.py",
- snapshots\repo_inventory.json:7148: "path": "tests/gui_v2/test_pipeline_config_panel_lora_runtime.py",

## src\controller\app_controller.py
- src\controller\app_controller.py:764: "error": "Job is missing normalized_record; legacy/pipeline_config execution is disabled.",
- src\controller\app_controller.py:1247: def _validate_pipeline_config(self) -> tuple[bool, str]:
- src\controller\app_controller.py:1258: panel = getattr(self.main_window, "pipeline_config_panel_v2", None)
- src\controller\app_controller.py:1494: def _execute_pipeline_via_runner(self, pipeline_config: PipelineConfig) -> Any:
- src\controller\app_controller.py:1498: def _run_pipeline_from_tab(self, pipeline_tab: Any, pipeline_config: PipelineConfig) -> Any:
- src\controller\app_controller.py:1594: def _run_pipeline_via_runner_only(self, pipeline_config: PipelineConfig) -> Any:
- src\controller\app_controller.py:1665: is_valid, message = self._validate_pipeline_config()
- src\controller\app_controller.py:1710: pipeline_config = self.build_pipeline_config_v2()
- src\controller\app_controller.py:1712: executor_config = self.pipeline_runner._build_executor_config(pipeline_config)
- src\controller\app_controller.py:1713: self._cache_last_run_payload(executor_config, pipeline_config)
- src\controller\app_controller.py:1714: self.pipeline_runner.run(pipeline_config, cancel_token, self._append_log_threadsafe)
- src\controller\app_controller.py:1734: def _cache_last_run_payload(self, executor_config: dict[str, Any], pipeline_config: PipelineConfig) -> None:
- src\controller\app_controller.py:1741: "prompt": pipeline_config.prompt,
- src\controller\app_controller.py:1742: "pack_name": pipeline_config.pack_name,
- src\controller\app_controller.py:1743: "preset_name": pipeline_config.preset_name,
- src\controller\app_controller.py:1822: pipeline_panel = getattr(self.main_window, "pipeline_config_panel_v2", None)
- src\controller\app_controller.py:2139: pipeline_config_panel = getattr(self.main_window, "pipeline_config_panel_v2", None)
- src\controller\app_controller.py:2140: if pipeline_config_panel and hasattr(pipeline_config_panel, "apply_run_config"):
- src\controller\app_controller.py:2142: pipeline_config_panel.apply_run_config(preset_config)
- src\controller\app_controller.py:2413: def build_pipeline_config_v2(self) -> PipelineConfig:
- src\controller\app_controller.py:2415: return self._build_pipeline_config()
- src\controller\app_controller.py:2417: def _build_pipeline_config(self) -> PipelineConfig:
- src\controller\app_controller.py:2695: panel = getattr(self.main_window, "pipeline_config_panel_v2", None)
- src\controller\app_controller.py:2810: pipeline_config_panel = getattr(self.main_window, "pipeline_config_panel_v2", None)
- src\controller\app_controller.py:2811: if pipeline_config_panel and hasattr(pipeline_config_panel, "apply_run_config"):
- src\controller\app_controller.py:2813: pipeline_config_panel.apply_run_config(pack_config)
- src\controller\app_controller.py:3041: pipeline_config_panel = getattr(self.main_window, "pipeline_config_panel_v2", None)
- src\controller\app_controller.py:3042: if pipeline_config_panel and hasattr(pipeline_config_panel, "apply_run_config"):
- src\controller\app_controller.py:3044: pipeline_config_panel.apply_run_config(preset_config)

## src\controller\job_history_service.py
- src\controller\job_history_service.py:223: Prefers NJR snapshot data. Legacy pipeline_config-only jobs no longer

## src\controller\job_service.py
- src\controller\job_service.py:305: # PR-CORE1-B3/C2: NJR-backed jobs are purely NJR-only and don't store pipeline_config.

## src\controller\pipeline_controller.py
- src\controller\pipeline_controller.py:35: from src.pipeline.legacy_njr_adapter import build_njr_from_legacy_pipeline_config
- src\controller\pipeline_controller.py:50: from src.controller.pipeline_config_assembler import PipelineConfigAssembler, GuiOverrides, RunPlan, PlannedJob
- src\controller\pipeline_controller.py:194: def _build_pipeline_config_from_state(self) -> PipelineConfig:
- src\controller\pipeline_controller.py:231: base_config = self._build_pipeline_config_from_state()
- src\controller\pipeline_controller.py:380: PR-CORE1-B3: NJR-backed jobs MUST NOT carry pipeline_config. The field may
- src\controller\pipeline_controller.py:530: def build_pipeline_config_with_profiles(
- src\controller\pipeline_controller.py:846: config = self._build_pipeline_config_from_state()
- src\controller\pipeline_controller.py:1296: Legacy pipeline_config execution is retired in CORE1-C2.
- src\controller\pipeline_controller.py:1550: record = build_njr_from_legacy_pipeline_config(config)
- src\controller\pipeline_controller.py:1556: record = build_njr_from_legacy_pipeline_config(config)

## src\gui\dropdown_loader_v2.py
- src\gui\dropdown_loader_v2.py:61: panel = getattr(sidebar, "pipeline_config_panel", None)

## src\gui\main_window_v2.py
- src\gui\main_window_v2.py:187: if hasattr(self, "pipeline_tab") and hasattr(self.pipeline_tab, "pipeline_config_panel"):
- src\gui\main_window_v2.py:189: self.pipeline_tab.pipeline_config_panel.controller = controller

## src\gui\panels_v2\__init__.py
- src\gui\panels_v2\__init__.py:8: from src.gui.panels_v2.pipeline_config_panel_v2 import PipelineConfigPanel

## src\gui\panels_v2\layout_manager_v2.py
- src\gui\panels_v2\layout_manager_v2.py:62: mw.pipeline_config_panel_v2 = getattr(getattr(mw.pipeline_tab, "sidebar", None), "pipeline_config_panel", None)

## src\gui\pipeline_panel_v2.py
- src\gui\pipeline_panel_v2.py:297: config = getattr(job, "config_snapshot", None) or getattr(job, "pipeline_config", None) or {}

## src\gui\preview_panel_v2.py
- src\gui\preview_panel_v2.py:4: All display data comes from NJR snapshots, never from pipeline_config.

## src\gui\sidebar_panel_v2.py
- src\gui\sidebar_panel_v2.py:226: self.pipeline_config_card = _SidebarCard(
- src\gui\sidebar_panel_v2.py:229: build_child=lambda parent: self._build_pipeline_config_section(parent),
- src\gui\sidebar_panel_v2.py:231: self.pipeline_config_card.grid(row=3, column=0, sticky="ew", padx=8, pady=(0, 4))
- src\gui\sidebar_panel_v2.py:872: def _build_pipeline_config_section(self, parent: ttk.Frame) -> ttk.Frame:
- src\gui\sidebar_panel_v2.py:875: from src.gui.panels_v2.pipeline_config_panel_v2 import PipelineConfigPanel
- src\gui\sidebar_panel_v2.py:885: self.pipeline_config_panel = PipelineConfigPanel(
- src\gui\sidebar_panel_v2.py:891: self.pipeline_config_panel.pack(fill="both", expand=True)

## src\history\history_migration_engine.py
- src\history\history_migration_engine.py:16: build_njr_from_legacy_pipeline_config,
- src\history\history_migration_engine.py:22: "pipeline_config",
- src\history\history_migration_engine.py:161: def _coerce_pipeline_config(self, data: Mapping[str, Any]) -> PipelineConfig:

## src\history\history_record.py
- src\history\history_record.py:11: "pipeline_config",

## src\history\history_schema_v26.py
- src\history\history_schema_v26.py:26: "pipeline_config",

## src\learning\learning_record_builder.py
- src\learning\learning_record_builder.py:40: pipeline_config: PipelineConfig,
- src\learning\learning_record_builder.py:48: config_dict = asdict(pipeline_config)

## src\pipeline\job_models_v2.py
- src\pipeline\job_models_v2.py:78: the NJR snapshot stored in Job.snapshot, not from Job.pipeline_config.
- src\pipeline\job_models_v2.py:79: Legacy jobs without NJR snapshots may fall back to pipeline_config.
- src\pipeline\job_models_v2.py:103: the NJR snapshot stored in history entries, not from pipeline_config.
- src\pipeline\job_models_v2.py:104: Legacy history entries without NJR snapshots may fall back to pipeline_config.
- src\pipeline\job_models_v2.py:439: During early CORE1-A/B hybrid state, Job.pipeline_config was the execution payload,
- src\pipeline\job_models_v2.py:441: Full NJR-only execution is enforced for all new jobs; pipeline_config remains

## src\pipeline\legacy_njr_adapter.py
- src\pipeline\legacy_njr_adapter.py:31: def build_njr_from_legacy_pipeline_config(pipeline_config: PipelineConfig) -> NormalizedJobRecord:
- src\pipeline\legacy_njr_adapter.py:40: config_snapshot = asdict(pipeline_config)
- src\pipeline\legacy_njr_adapter.py:41: stage = _make_default_stage(pipeline_config)
- src\pipeline\legacy_njr_adapter.py:42: metadata = dict(pipeline_config.metadata or {})
- src\pipeline\legacy_njr_adapter.py:60: positive_prompt=pipeline_config.prompt or "",
- src\pipeline\legacy_njr_adapter.py:61: negative_prompt=pipeline_config.negative_prompt or "",
- src\pipeline\legacy_njr_adapter.py:66: steps=pipeline_config.steps or 20,
- src\pipeline\legacy_njr_adapter.py:67: cfg_scale=pipeline_config.cfg_scale or 7.0,
- src\pipeline\legacy_njr_adapter.py:68: width=pipeline_config.width or 512,
- src\pipeline\legacy_njr_adapter.py:69: height=pipeline_config.height or 512,
- src\pipeline\legacy_njr_adapter.py:70: sampler_name=pipeline_config.sampler or "Euler a",
- src\pipeline\legacy_njr_adapter.py:71: scheduler=getattr(pipeline_config, "scheduler", "") or "",
- src\pipeline\legacy_njr_adapter.py:72: base_model=pipeline_config.model or "unknown",
- src\pipeline\legacy_njr_adapter.py:90: "legacy_source": "pipeline_config",
- src\pipeline\legacy_njr_adapter.py:140: pipeline_config = data.get("pipeline_config")
- src\pipeline\legacy_njr_adapter.py:141: if isinstance(pipeline_config, PipelineConfig):
- src\pipeline\legacy_njr_adapter.py:142: return build_njr_from_legacy_pipeline_config(pipeline_config)
- src\pipeline\legacy_njr_adapter.py:143: if isinstance(pipeline_config, Mapping):
- src\pipeline\legacy_njr_adapter.py:145: prompt=str(pipeline_config.get("prompt", "") or ""),
- src\pipeline\legacy_njr_adapter.py:146: model=_normalize_model_name(pipeline_config.get("model", "") or pipeline_config.get("model_name", "")),
- src\pipeline\legacy_njr_adapter.py:147: sampler=str(pipeline_config.get("sampler", "") or pipeline_config.get("sampler_name", "") or "Euler a"),
- src\pipeline\legacy_njr_adapter.py:148: width=_coerce_int(pipeline_config.get("width", 512), 512),
- src\pipeline\legacy_njr_adapter.py:149: height=_coerce_int(pipeline_config.get("height", 512), 512),
- src\pipeline\legacy_njr_adapter.py:150: steps=_coerce_int(pipeline_config.get("steps", 20), 20),
- src\pipeline\legacy_njr_adapter.py:151: cfg_scale=_coerce_float(pipeline_config.get("cfg_scale", 7.0), 7.0),
- src\pipeline\legacy_njr_adapter.py:152: negative_prompt=str(pipeline_config.get("negative_prompt", "") or ""),
- src\pipeline\legacy_njr_adapter.py:153: metadata=dict(pipeline_config.get("metadata") or {}),
- src\pipeline\legacy_njr_adapter.py:155: return build_njr_from_legacy_pipeline_config(config)

## src\pipeline\pipeline_runner.py
- src\pipeline\pipeline_runner.py:415: config = self._pipeline_config_from_njr(record)
- src\pipeline\pipeline_runner.py:418: def _pipeline_config_from_njr(self, record: NormalizedJobRecord) -> PipelineConfig:

## src\pipeline\stage_sequencer.py
- src\pipeline\stage_sequencer.py:262: plan = sequencer.build_plan(pipeline_config)
- src\pipeline\stage_sequencer.py:265: def build_plan(self, pipeline_config: dict[str, Any]) -> StageExecutionPlan:
- src\pipeline\stage_sequencer.py:269: pipeline_config: Dictionary containing stage configurations and flags.
- src\pipeline\stage_sequencer.py:278: return build_stage_execution_plan(pipeline_config)

## src\queue\job_history_store.py
- src\queue\job_history_store.py:8: NormalizedJobRecord data. Legacy entries on disk may still expose pipeline_config
- src\queue\job_history_store.py:9: blobs, but new entries no longer persist pipeline_config—legacy_njr_adapter

## src\queue\job_queue.py
- src\queue\job_queue.py:7: for execution. The pipeline_config field is legacy-only and should not be relied

## src\services\queue_store_v2.py
- src\services\queue_store_v2.py:29: "pipeline_config",
- src\services\queue_store_v2.py:49: "pipeline_config",

## src\utils\snapshot_builder_v2.py
- src\utils\snapshot_builder_v2.py:35: def _serialize_pipeline_config(config: Any) -> dict[str, Any]:
- src\utils\snapshot_builder_v2.py:188: "config": _serialize_pipeline_config(record.config),

## test_adetailer_sync.py
- test_adetailer_sync.py:10: from src.gui.panels_v2.pipeline_config_panel_v2 import PipelineConfigPanel

## test_output.txt
- test_output.txt:60: tests\controller\test_pipeline_config_assembler.py ...                   [ 14%]
- test_output.txt:61: tests\controller\test_pipeline_config_assembler_core_fields.py ..        [ 14%]
- test_output.txt:62: tests\controller\test_pipeline_config_assembler_model_fields.py .        [ 14%]
- test_output.txt:63: tests\controller\test_pipeline_config_assembler_negative_prompt.py .     [ 14%]
- test_output.txt:64: tests\controller\test_pipeline_config_assembler_output_settings.py .     [ 14%]
- test_output.txt:65: tests\controller\test_pipeline_config_assembler_resolution.py .          [ 14%]

## tests\compat\data\history_compat_v2\history_v2_0_pre_njr.jsonl
- tests\compat\data\history_compat_v2\history_v2_0_pre_njr.jsonl:1: {"job_id":"legacy-001","timestamp":"2023-01-01T00:00:00Z","status":"completed","pipeline_config":{"prompt":"legacy prompt 001","model":"sdxl","steps":20,"cfg_scale":7.0,"sampler":"Euler a","width":512,"height":512},"result":{"run_id":"legacy-001","success":true,"variants":[],"learning_records":[],"metadata":{"source":"legacy"}}}
- tests\compat\data\history_compat_v2\history_v2_0_pre_njr.jsonl:2: {"job_id":"legacy-002","timestamp":"2023-02-02T00:00:00Z","status":"failed","pipeline_config":{"prompt":"legacy prompt 002","model":"sdxl","steps":25,"cfg_scale":6.5,"sampler":"Euler a","width":640,"height":640},"error_message":"boom","result":{"run_id":"legacy-002","success":false,"error":"boom","variants":[],"learning_records":[],"metadata":{"source":"legacy"}}}
- tests\compat\data\history_compat_v2\history_v2_0_pre_njr.jsonl:3: {"job_id":"legacy-003","timestamp":"2023-03-03T00:00:00Z","status":"completed","pipeline_config":{"prompt":"legacy prompt 003","model":"sdxl","steps":15,"cfg_scale":8.0,"sampler":"Euler a","width":768,"height":768},"result":{"run_id":"legacy-003","success":true,"variants":[],"learning_records":[],"metadata":{"source":"legacy"}}}

## tests\compat\data\history_compat_v2\history_v2_4_hybrid.jsonl
- tests\compat\data\history_compat_v2\history_v2_4_hybrid.jsonl:1: {"job_id":"hybrid-001","timestamp":"2024-04-04T04:04:04Z","status":"failed","snapshot":{"job_id":"hybrid-001","positive_prompt":"hybrid prompt","base_model":"sdxl","steps":26,"cfg_scale":7.5,"normalized_job":{"job_id":"hybrid-001","config":{"prompt":"hybrid prompt","model":"sdxl"}}},"pipeline_config":{"prompt":"hybrid prompt","model":"sdxl","steps":26,"cfg_scale":7.5,"sampler":"Euler a","width":640,"height":640},"result":{"run_id":"hybrid-001","success":false,"error":"oops","variants":[],"learning_records":[],"metadata":{"source":"hybrid"}}}
- tests\compat\data\history_compat_v2\history_v2_4_hybrid.jsonl:3: {"job_id":"hybrid-003","timestamp":"2024-06-06T06:06:06Z","status":"completed","snapshot":{"normalized_job":{"job_id":"hybrid-003","config":{"prompt":"hybrid three","model":"sdxl","steps":30,"cfg_scale":7.2}}},"pipeline_config":{"prompt":"hybrid three","model":"sdxl","steps":30,"cfg_scale":7.2,"sampler":"Euler a","width":512,"height":512},"result":{"run_id":"hybrid-003","success":true,"variants":[],"learning_records":[],"metadata":{"source":"hybrid"}}}

## tests\compat\data\queue_compat_v2\queue_state_v2_0.json
- tests\compat\data\queue_compat_v2\queue_state_v2_0.json:1: {"jobs":[{"queue_id":"legacy-queue-001","job_id":"legacy-queue-001","status":"queued","priority":1,"created_at":"2023-01-05T10:00:00Z","pipeline_config":{"prompt":"queue prompt legacy 001","model":"sdxl","steps":20,"cfg_scale":7.0,"sampler":"Euler a","width":512,"height":512}},{"queue_id":"legacy-queue-002","job_id":"legacy-queue-002","status":"running","priority":2,"created_at":"2023-01-06T11:11:00Z","pipeline_config":{"prompt":"queue prompt legacy 002","model":"sdxl","steps":24,"cfg_scale":6.5,"sampler":"Euler a","width":640,"height":640}}],"auto_run_enabled":true,"paused":false,"schema_version":"2.0"}

## tests\compat\data\queue_compat_v2\queue_state_v2_4_hybrid.json
- tests\compat\data\queue_compat_v2\queue_state_v2_4_hybrid.json:1: {"jobs":[{"queue_id":"hybrid-queue-001","job_id":"hybrid-queue-001","status":"queued","priority":1,"created_at":"2024-04-04T04:04:00Z","snapshot":{"job_id":"hybrid-queue-001","positive_prompt":"hybrid queue prompt","base_model":"sdxl","steps":30,"cfg_scale":7.25},"pipeline_config":{"prompt":"hybrid queue prompt","model":"sdxl","steps":30,"cfg_scale":7.25,"sampler":"Euler a","width":640,"height":640}},{"queue_id":"hybrid-queue-002","job_id":"hybrid-queue-002","status":"queued","priority":2,"created_at":"2024-04-05T05:05:00Z","njr_snapshot":{"job_id":"hybrid-queue-002","positive_prompt":"hybrid queue nested","base_model":"sdxl","steps":32,"cfg_scale":7.5,"normalized_job":{"job_id":"hybrid-queue-002","config":{"prompt":"hybrid queue nested","model":"sdxl","steps":32,"cfg_scale":7.5}}}}],"auto_run_enabled":false,"paused":true,"schema_version":"2.4"}

## tests\compat\data\queue_compat_v2\queue_state_v2_6_core1_pre.json
- tests\compat\data\queue_compat_v2\queue_state_v2_6_core1_pre.json:1: {"jobs":[{"queue_id":"core1-queue-001","job_id":"core1-queue-001","status":"queued","priority":1,"created_at":"2025-01-10T10:10:00Z","njr_snapshot":{"job_id":"core1-queue-001","positive_prompt":"core1 queue ready","base_model":"sdxl","steps":40,"cfg_scale":7.8},"_normalized_record":{"job_id":"core1-queue-001"},"pipeline_config":{"prompt":"core1 queue ready","model":"sdxl","steps":40,"cfg_scale":7.8,"sampler":"Euler a","width":768,"height":768},"metadata":{"note":"transitioning"}},{"queue_id":"core1-queue-002","job_id":"core1-queue-002","status":"running","priority":2,"created_at":"2025-01-11T11:11:00Z","njr_snapshot":{"job_id":"core1-queue-002","positive_prompt":"core1 queue run","base_model":"sdxl","steps":42,"cfg_scale":7.9,"normalized_job":{"job_id":"core1-queue-002","config":{"prompt":"core1 queue run","model":"sdxl","steps":42,"cfg_scale":7.9}}}}],"auto_run_enabled":true,"paused":false,"schema_version":"2.6"}

## tests\controller\archive\test_app_controller_pipeline_integration.py
- tests\controller\archive\test_app_controller_pipeline_integration.py:58: def test_pipeline_config_assembled_from_controller_state(pack_file):
- tests\controller\archive\test_app_controller_pipeline_integration.py:90: pipeline_config = runner.calls[0][0]
- tests\controller\archive\test_app_controller_pipeline_integration.py:91: assert isinstance(pipeline_config, PipelineConfig)
- tests\controller\archive\test_app_controller_pipeline_integration.py:92: assert pipeline_config.model == "SDXL-Lightning"
- tests\controller\archive\test_app_controller_pipeline_integration.py:93: assert pipeline_config.sampler == "DPM++ 2M"
- tests\controller\archive\test_app_controller_pipeline_integration.py:94: assert pipeline_config.width == 832
- tests\controller\archive\test_app_controller_pipeline_integration.py:95: assert pipeline_config.height == 640
- tests\controller\archive\test_app_controller_pipeline_integration.py:96: assert pipeline_config.steps == 42
- tests\controller\archive\test_app_controller_pipeline_integration.py:97: assert pipeline_config.cfg_scale == 8.9
- tests\controller\archive\test_app_controller_pipeline_integration.py:98: assert pipeline_config.pack_name == "alpha"
- tests\controller\archive\test_app_controller_pipeline_integration.py:99: assert "sunset" in pipeline_config.prompt

## tests\controller\test_app_controller_lora_runtime.py
- tests\controller\test_app_controller_lora_runtime.py:88: payload = controller._build_pipeline_config()

## tests\controller\test_app_controller_njr_exec.py
- tests\controller\test_app_controller_njr_exec.py:6: - Rejects jobs without normalized_record (no pipeline_config fallback)
- tests\controller\test_app_controller_njr_exec.py:92: """Jobs without normalized_record are rejected (no pipeline_config fallback)."""
- tests\controller\test_app_controller_njr_exec.py:129: def test_payload_job_without_njr_or_pipeline_config_returns_error(self, mock_app_controller):

## tests\controller\test_app_controller_pipeline_integration.py
- tests\controller\test_app_controller_pipeline_integration.py:56: def test_pipeline_config_assembled_from_controller_state(pack_file):
- tests\controller\test_app_controller_pipeline_integration.py:88: pipeline_config = runner.calls[0][0]
- tests\controller\test_app_controller_pipeline_integration.py:89: assert isinstance(pipeline_config, PipelineConfig)
- tests\controller\test_app_controller_pipeline_integration.py:90: assert pipeline_config.model == "SDXL-Lightning"
- tests\controller\test_app_controller_pipeline_integration.py:91: assert pipeline_config.sampler == "DPM++ 2M"
- tests\controller\test_app_controller_pipeline_integration.py:92: assert pipeline_config.width == 832
- tests\controller\test_app_controller_pipeline_integration.py:93: assert pipeline_config.height == 640
- tests\controller\test_app_controller_pipeline_integration.py:94: assert pipeline_config.steps == 42
- tests\controller\test_app_controller_pipeline_integration.py:95: assert pipeline_config.cfg_scale == 8.9
- tests\controller\test_app_controller_pipeline_integration.py:96: assert pipeline_config.pack_name == "alpha"
- tests\controller\test_app_controller_pipeline_integration.py:97: assert "sunset" in pipeline_config.prompt

## tests\controller\test_core_run_path_v2.py
- tests\controller\test_core_run_path_v2.py:151: """PR-CORE1-B2: Job with NJR that fails execution returns error (no pipeline_config fallback)."""
- tests\controller\test_core_run_path_v2.py:172: # PR-CORE1-B2: Should return error status, not fall back to pipeline_config
- tests\controller\test_core_run_path_v2.py:197: assert getattr(queue_job, "pipeline_config", None) is None

## tests\controller\test_job_construction_b3.py
- tests\controller\test_job_construction_b3.py:36: assert getattr(job, "pipeline_config", None) is None

## tests\controller\test_pipeline_config_assembler.py
- tests\controller\test_pipeline_config_assembler.py:1: from src.controller.pipeline_config_assembler import PipelineConfigAssembler, GuiOverrides
- tests\controller\test_pipeline_config_assembler.py:4: def test_build_pipeline_config_applies_overrides_and_limits():
- tests\controller\test_pipeline_config_assembler.py:22: def test_build_pipeline_config_includes_metadata():

## tests\controller\test_pipeline_config_assembler_core_fields.py
- tests\controller\test_pipeline_config_assembler_core_fields.py:3: from src.controller.pipeline_config_assembler import GuiOverrides, PipelineConfigAssembler

## tests\controller\test_pipeline_config_assembler_model_fields.py
- tests\controller\test_pipeline_config_assembler_model_fields.py:1: from src.controller.pipeline_config_assembler import GuiOverrides, PipelineConfigAssembler

## tests\controller\test_pipeline_config_assembler_negative_prompt.py
- tests\controller\test_pipeline_config_assembler_negative_prompt.py:1: from src.controller.pipeline_config_assembler import GuiOverrides, PipelineConfigAssembler

## tests\controller\test_pipeline_config_assembler_output_settings.py
- tests\controller\test_pipeline_config_assembler_output_settings.py:1: from src.controller.pipeline_config_assembler import GuiOverrides, PipelineConfigAssembler

## tests\controller\test_pipeline_config_assembler_resolution.py
- tests\controller\test_pipeline_config_assembler_resolution.py:1: from src.controller.pipeline_config_assembler import GuiOverrides, PipelineConfigAssembler

## tests\controller\test_pipeline_controller_config_path.py
- tests\controller\test_pipeline_controller_config_path.py:5: from src.controller.pipeline_config_assembler import PipelineConfigAssembler, GuiOverrides

## tests\controller\test_pipeline_controller_job_specs_v2.py
- tests\controller\test_pipeline_controller_job_specs_v2.py:10: 3. Key pipeline_config fields (model, steps, CFG, etc.) are correctly passed through.
- tests\controller\test_pipeline_controller_job_specs_v2.py:28: make_minimal_pipeline_config,
- tests\controller\test_pipeline_controller_job_specs_v2.py:68: config = make_minimal_pipeline_config(model="test-model", seed=12345)
- tests\controller\test_pipeline_controller_job_specs_v2.py:81: config = make_minimal_pipeline_config()
- tests\controller\test_pipeline_controller_job_specs_v2.py:98: config = make_minimal_pipeline_config(model="my-special-model")
- tests\controller\test_pipeline_controller_job_specs_v2.py:110: config = make_minimal_pipeline_config(steps=42)
- tests\controller\test_pipeline_controller_job_specs_v2.py:122: config = make_minimal_pipeline_config(cfg_scale=9.5)
- tests\controller\test_pipeline_controller_job_specs_v2.py:134: config = make_minimal_pipeline_config()
- tests\controller\test_pipeline_controller_job_specs_v2.py:152: config = make_minimal_pipeline_config()
- tests\controller\test_pipeline_controller_job_specs_v2.py:176: config = make_minimal_pipeline_config(model="base-model")
- tests\controller\test_pipeline_controller_job_specs_v2.py:193: config = make_minimal_pipeline_config()
- tests\controller\test_pipeline_controller_job_specs_v2.py:212: config = make_minimal_pipeline_config()
- tests\controller\test_pipeline_controller_job_specs_v2.py:233: config = make_minimal_pipeline_config()
- tests\controller\test_pipeline_controller_job_specs_v2.py:253: config = make_minimal_pipeline_config()
- tests\controller\test_pipeline_controller_job_specs_v2.py:269: config = make_minimal_pipeline_config()
- tests\controller\test_pipeline_controller_job_specs_v2.py:296: config = make_minimal_pipeline_config()
- tests\controller\test_pipeline_controller_job_specs_v2.py:309: config = make_minimal_pipeline_config()
- tests\controller\test_pipeline_controller_job_specs_v2.py:323: config = make_minimal_pipeline_config()
- tests\controller\test_pipeline_controller_job_specs_v2.py:336: config = make_minimal_pipeline_config()
- tests\controller\test_pipeline_controller_job_specs_v2.py:350: config = make_minimal_pipeline_config(model="batch-model", steps=25)
- tests\controller\test_pipeline_controller_job_specs_v2.py:374: config = make_minimal_pipeline_config()
- tests\controller\test_pipeline_controller_job_specs_v2.py:391: config = make_minimal_pipeline_config()
- tests\controller\test_pipeline_controller_job_specs_v2.py:416: config = make_minimal_pipeline_config()
- tests\controller\test_pipeline_controller_job_specs_v2.py:441: config = make_minimal_pipeline_config()
- tests\controller\test_pipeline_controller_job_specs_v2.py:468: config = make_minimal_pipeline_config(hires_enabled=True)
- tests\controller\test_pipeline_controller_job_specs_v2.py:479: config = make_minimal_pipeline_config(refiner_enabled=True)
- tests\controller\test_pipeline_controller_job_specs_v2.py:490: config = make_minimal_pipeline_config(adetailer_enabled=True)
- tests\controller\test_pipeline_controller_job_specs_v2.py:519: config = make_minimal_pipeline_config(model="test", seed=123)
- tests\controller\test_pipeline_controller_job_specs_v2.py:551: config = make_minimal_pipeline_config()
- tests\controller\test_pipeline_controller_job_specs_v2.py:582: config = make_minimal_pipeline_config()
- tests\controller\test_pipeline_controller_job_specs_v2.py:593: config = make_minimal_pipeline_config()
- tests\controller\test_pipeline_controller_job_specs_v2.py:606: config = make_minimal_pipeline_config()

## tests\controller\test_pipeline_controller_webui_gating.py
- tests\controller\test_pipeline_controller_webui_gating.py:11: controller._build_pipeline_config_from_state = mock.Mock()
- tests\controller\test_pipeline_controller_webui_gating.py:16: controller._build_pipeline_config_from_state.assert_not_called()
- tests\controller\test_pipeline_controller_webui_gating.py:23: controller._build_pipeline_config_from_state = mock.Mock(return_value=mock.Mock())
- tests\controller\test_pipeline_controller_webui_gating.py:32: controller._build_pipeline_config_from_state.assert_called_once()

## tests\controller\test_pipeline_randomizer_config_v2.py
- tests\controller\test_pipeline_randomizer_config_v2.py:54: controller.main_window = SimpleNamespace(pipeline_config_panel_v2=panel)

## tests\controller\test_presets_integration_v2.py
- tests\controller\test_presets_integration_v2.py:48: controller.main_window = SimpleNamespace(pipeline_config_panel_v2=DummyPipelinePanel())
- tests\controller\test_presets_integration_v2.py:56: assert controller.main_window.pipeline_config_panel_v2.applied[-1]["randomization_enabled"]

## tests\controller\test_profile_integration.py
- tests\controller\test_profile_integration.py:18: def test_build_pipeline_config_with_profiles_applies_suggested_preset():
- tests\controller\test_profile_integration.py:23: config = controller.build_pipeline_config_with_profiles(
- tests\controller\test_profile_integration.py:34: def test_build_pipeline_config_with_profiles_respects_user_overrides():
- tests\controller\test_profile_integration.py:39: config = controller.build_pipeline_config_with_profiles(
- tests\controller\test_profile_integration.py:48: def test_build_pipeline_config_with_profiles_falls_back_without_profiles():
- tests\controller\test_profile_integration.py:53: config = controller.build_pipeline_config_with_profiles(

## tests\gui_v2\archive\test_pipeline_randomizer_panel_v2.py
- tests\gui_v2\archive\test_pipeline_randomizer_panel_v2.py:11: from src.gui.panels_v2.pipeline_config_panel_v2 import PipelineConfigPanel

## tests\gui_v2\test_pipeline_config_panel_lora_runtime.py
- tests\gui_v2\test_pipeline_config_panel_lora_runtime.py:8: from src.gui.panels_v2.pipeline_config_panel_v2 import PipelineConfigPanel
- tests\gui_v2\test_pipeline_config_panel_lora_runtime.py:33: def test_pipeline_config_panel_lora_controls_update_controller() -> None:

## tests\gui_v2\test_pipeline_layout_scroll_v2.py
- tests\gui_v2\test_pipeline_layout_scroll_v2.py:338: def test_pipeline_config_panel_no_validation_label() -> None:
- tests\gui_v2\test_pipeline_layout_scroll_v2.py:347: from src.gui.panels_v2.pipeline_config_panel_v2 import PipelineConfigPanel
- tests\gui_v2\test_pipeline_layout_scroll_v2.py:374: from src.gui.panels_v2.pipeline_config_panel_v2 import PipelineConfigPanel

## tests\gui_v2\test_pipeline_left_column_config_v2.py
- tests\gui_v2\test_pipeline_left_column_config_v2.py:28: config_panel = getattr(sidebar, "pipeline_config_panel", None)

## tests\gui_v2\test_pipeline_stage_checkbox_order_v2.py
- tests\gui_v2\test_pipeline_stage_checkbox_order_v2.py:7: from src.gui.views.pipeline_config_panel import PipelineConfigPanel
- tests\gui_v2\test_pipeline_stage_checkbox_order_v2.py:11: def test_pipeline_config_stage_checkbox_order(monkeypatch) -> None:

## tests\gui_v2\test_preview_panel_v2_normalized_jobs.py
- tests\gui_v2\test_preview_panel_v2_normalized_jobs.py:3: Confirms preview panel uses NJR-based display, not pipeline_config.

## tests\gui_v2\test_queue_panel_v2_normalized_jobs.py
- tests\gui_v2\test_queue_panel_v2_normalized_jobs.py:3: Confirms queue panel uses NJR-based display, not pipeline_config.

## tests\helpers\pipeline_fixtures_v2.py
- tests\helpers\pipeline_fixtures_v2.py:147: def make_minimal_pipeline_config(
- tests\helpers\pipeline_fixtures_v2.py:216: config = make_minimal_pipeline_config(seed=seed)
- tests\helpers\pipeline_fixtures_v2.py:277: "make_minimal_pipeline_config",

## tests\history\test_history_compaction.py
- tests\history\test_history_compaction.py:18: "pipeline_config": {"prompt": "old", "model": "v1", "sampler": "Euler"},

## tests\history\test_history_migration_engine.py
- tests\history\test_history_migration_engine.py:12: "pipeline_config": {
- tests\history\test_history_migration_engine.py:68: assert all("pipeline_config" not in entry["njr_snapshot"] for entry in migrated)

## tests\history\test_history_roundtrip.py
- tests\history\test_history_roundtrip.py:18: "pipeline_config": {
- tests\history\test_history_roundtrip.py:78: assert all("pipeline_config" not in rec.njr_snapshot for rec in second)

## tests\history\test_history_schema_roundtrip.py
- tests\history\test_history_schema_roundtrip.py:19: "pipeline_config": {"prompt": "ancient job", "model": "v1", "sampler": "Euler a"},

## tests\history\test_history_schema_v26.py
- tests\history\test_history_schema_v26.py:38: entry["pipeline_config"] = {}
- tests\history\test_history_schema_v26.py:41: assert any("deprecated field present: pipeline_config" in err for err in errors)

## tests\integration\test_end_to_end_pipeline_v2.py
- tests\integration\test_end_to_end_pipeline_v2.py:21: from src.pipeline.legacy_njr_adapter import build_njr_from_legacy_pipeline_config
- tests\integration\test_end_to_end_pipeline_v2.py:60: njr = build_njr_from_legacy_pipeline_config(cfg)
- tests\integration\test_end_to_end_pipeline_v2.py:260: config = job.pipeline_config
- tests\integration\test_end_to_end_pipeline_v2.py:282: def small_pipeline_config() -> PipelineConfig:
- tests\integration\test_end_to_end_pipeline_v2.py:313: small_pipeline_config: PipelineConfig,
- tests\integration\test_end_to_end_pipeline_v2.py:318: small_pipeline_config,
- tests\integration\test_end_to_end_pipeline_v2.py:352: small_pipeline_config: PipelineConfig,
- tests\integration\test_end_to_end_pipeline_v2.py:356: small_pipeline_config,
- tests\integration\test_end_to_end_pipeline_v2.py:377: small_pipeline_config: PipelineConfig,
- tests\integration\test_end_to_end_pipeline_v2.py:381: small_pipeline_config,
- tests\integration\test_end_to_end_pipeline_v2.py:411: small_pipeline_config: PipelineConfig,
- tests\integration\test_end_to_end_pipeline_v2.py:416: small_pipeline_config,
- tests\integration\test_end_to_end_pipeline_v2.py:445: small_pipeline_config: PipelineConfig,
- tests\integration\test_end_to_end_pipeline_v2.py:449: small_pipeline_config,
- tests\integration\test_end_to_end_pipeline_v2.py:516: small_pipeline_config: PipelineConfig,
- tests\integration\test_end_to_end_pipeline_v2.py:520: small_pipeline_config,
- tests\integration\test_end_to_end_pipeline_v2.py:557: small_pipeline_config: PipelineConfig,
- tests\integration\test_end_to_end_pipeline_v2.py:562: small_pipeline_config,
- tests\integration\test_end_to_end_pipeline_v2.py:663: pipeline_config = {
- tests\integration\test_end_to_end_pipeline_v2.py:682: plan = StageSequencer().build_plan(pipeline_config)

## tests\pipeline\test_config_merger_v2.py
- tests\pipeline\test_config_merger_v2.py:67: def base_pipeline_config(base_txt2img_config: dict) -> dict:
- tests\pipeline\test_config_merger_v2.py:379: self, base_pipeline_config: dict
- tests\pipeline\test_config_merger_v2.py:386: base_config=base_pipeline_config,
- tests\pipeline\test_config_merger_v2.py:392: assert result == base_pipeline_config
- tests\pipeline\test_config_merger_v2.py:393: assert result is not base_pipeline_config
- tests\pipeline\test_config_merger_v2.py:394: assert result["refiner"] is not base_pipeline_config["refiner"]
- tests\pipeline\test_config_merger_v2.py:397: self, base_pipeline_config: dict
- tests\pipeline\test_config_merger_v2.py:403: base_config=base_pipeline_config,
- tests\pipeline\test_config_merger_v2.py:408: assert result == base_pipeline_config
- tests\pipeline\test_config_merger_v2.py:409: assert result is not base_pipeline_config
- tests\pipeline\test_config_merger_v2.py:412: self, base_pipeline_config: dict
- tests\pipeline\test_config_merger_v2.py:426: base_config=base_pipeline_config,
- tests\pipeline\test_config_merger_v2.py:437: self, base_pipeline_config: dict
- tests\pipeline\test_config_merger_v2.py:450: base_config=base_pipeline_config,
- tests\pipeline\test_config_merger_v2.py:464: self, base_pipeline_config: dict
- tests\pipeline\test_config_merger_v2.py:477: base_config=base_pipeline_config,
- tests\pipeline\test_config_merger_v2.py:487: self, base_pipeline_config: dict
- tests\pipeline\test_config_merger_v2.py:500: base_config=base_pipeline_config,
- tests\pipeline\test_config_merger_v2.py:510: self, base_pipeline_config: dict
- tests\pipeline\test_config_merger_v2.py:523: base_config=base_pipeline_config,
- tests\pipeline\test_config_merger_v2.py:533: self, base_pipeline_config: dict
- tests\pipeline\test_config_merger_v2.py:546: base_config=base_pipeline_config,
- tests\pipeline\test_config_merger_v2.py:556: self, base_pipeline_config: dict
- tests\pipeline\test_config_merger_v2.py:571: base_config=base_pipeline_config,
- tests\pipeline\test_config_merger_v2.py:592: self, base_pipeline_config: dict
- tests\pipeline\test_config_merger_v2.py:597: original = copy.deepcopy(base_pipeline_config)
- tests\pipeline\test_config_merger_v2.py:605: base_config=base_pipeline_config,
- tests\pipeline\test_config_merger_v2.py:611: assert base_pipeline_config == original

## tests\pipeline\test_job_queue_persistence_v2.py
- tests\pipeline\test_job_queue_persistence_v2.py:76: "pipeline_config": {"model": "old"},
- tests\pipeline\test_job_queue_persistence_v2.py:84: assert "pipeline_config" not in migrated["njr_snapshot"]
- tests\pipeline\test_job_queue_persistence_v2.py:149: assert "pipeline_config" not in job_record["njr_snapshot"]
- tests\pipeline\test_job_queue_persistence_v2.py:166: "pipeline_config": {"model": "old"},
- tests\pipeline\test_job_queue_persistence_v2.py:185: assert "pipeline_config" not in job["njr_snapshot"]
- tests\pipeline\test_job_queue_persistence_v2.py:308: assert "pipeline_config" not in queue_entry["njr_snapshot"]
- tests\pipeline\test_job_queue_persistence_v2.py:309: assert "pipeline_config" not in history_njr
- tests\pipeline\test_job_queue_persistence_v2.py:353: assert "pipeline_config" not in entry["njr_snapshot"]

## tests\pipeline\test_legacy_njr_adapter.py
- tests\pipeline\test_legacy_njr_adapter.py:1: from src.pipeline.legacy_njr_adapter import build_njr_from_legacy_pipeline_config
- tests\pipeline\test_legacy_njr_adapter.py:5: def _make_pipeline_config() -> PipelineConfig:
- tests\pipeline\test_legacy_njr_adapter.py:20: config = _make_pipeline_config()
- tests\pipeline\test_legacy_njr_adapter.py:21: record = build_njr_from_legacy_pipeline_config(config)
- tests\pipeline\test_legacy_njr_adapter.py:25: assert record.extra_metadata.get("legacy_source") == "pipeline_config"
- tests\pipeline\test_legacy_njr_adapter.py:29: def test_adapter_handles_minimal_pipeline_config() -> None:
- tests\pipeline\test_legacy_njr_adapter.py:39: record = build_njr_from_legacy_pipeline_config(config)

## tests\pipeline\test_pipeline_learning_hooks.py
- tests\pipeline\test_pipeline_learning_hooks.py:52: def _pipeline_config():
- tests\pipeline\test_pipeline_learning_hooks.py:67: runner.run(_pipeline_config(), cancel_token=_cancel_token())
- tests\pipeline\test_pipeline_learning_hooks.py:74: runner.run(_pipeline_config(), cancel_token=_cancel_token())

## tests\pipeline\test_stage_plan_builder_v2_5.py
- tests\pipeline\test_stage_plan_builder_v2_5.py:8: def _base_pipeline_config(**overrides) -> dict[str, dict]:
- tests\pipeline\test_stage_plan_builder_v2_5.py:36: config = _base_pipeline_config(
- tests\pipeline\test_stage_plan_builder_v2_5.py:56: config = _base_pipeline_config(
- tests\pipeline\test_stage_plan_builder_v2_5.py:72: config = _base_pipeline_config(
- tests\pipeline\test_stage_plan_builder_v2_5.py:86: config = _base_pipeline_config(

## tests\queue\test_job_history_store.py
- tests\queue\test_job_history_store.py:90: assert "pipeline_config" not in njr_snapshot

## tests\queue\test_job_model.py
- tests\queue\test_job_model.py:13: def test_job_dict_does_not_include_pipeline_config():
- tests\queue\test_job_model.py:16: assert "pipeline_config" not in as_dict

## tests\queue\test_job_service_pipeline_integration_v2.py
- tests\queue\test_job_service_pipeline_integration_v2.py:234: """submit_direct() passes job with correct pipeline_config."""
- tests\queue\test_job_service_pipeline_integration_v2.py:336: """submit_queued() passes job with correct pipeline_config."""

## tests\queue\test_job_variant_metadata_v2.py
- tests\queue\test_job_variant_metadata_v2.py:9: def _make_pipeline_config() -> PipelineConfig:
- tests\queue\test_job_variant_metadata_v2.py:27: "pipeline_config": _make_pipeline_config(),

## tests\queue\test_queue_njr_path.py
- tests\queue\test_queue_njr_path.py:5: - Execution uses NJR-only path for new jobs (pipeline_config is None)
- tests\queue\test_queue_njr_path.py:6: - Legacy pipeline_config-only jobs still work but are marked as legacy
- tests\queue\test_queue_njr_path.py:60: assert getattr(retrieved, "pipeline_config", None) is None
- tests\queue\test_queue_njr_path.py:63: """Job with NJR should execute via NJR path only (no pipeline_config fallback)."""
- tests\queue\test_queue_njr_path.py:81: # 3. NOT fall back to pipeline_config even if _run_job fails
- tests\queue\test_queue_njr_path.py:85: # pipeline_config should remain None for NJR-only jobs
- tests\queue\test_queue_njr_path.py:86: assert getattr(retrieved, "pipeline_config", None) is None
- tests\queue\test_queue_njr_path.py:88: def test_legacy_pipeline_config_only_job(self, tmp_path: Path):
- tests\queue\test_queue_njr_path.py:89: """Legacy job with only pipeline_config (no NJR) should still work."""
- tests\queue\test_queue_njr_path.py:99: job.pipeline_config = PipelineConfig(
- tests\queue\test_queue_njr_path.py:115: assert getattr(retrieved, "pipeline_config", None) is not None
- tests\queue\test_queue_njr_path.py:152: def test_new_jobs_dont_rely_on_pipeline_config_for_execution(self, tmp_path: Path):
- tests\queue\test_queue_njr_path.py:153: """PR-CORE1-B2: New queue jobs should not rely on pipeline_config for execution."""
- tests\queue\test_queue_njr_path.py:167: # pipeline_config is intentionally absent for new NJR-only jobs
- tests\queue\test_queue_njr_path.py:175: assert getattr(retrieved, "pipeline_config", None) is None
- tests\queue\test_queue_njr_path.py:176: # PR-CORE1-B2 contract: Execution MUST use _normalized_record, not pipeline_config

