# pipeline_config references (excluding archive/.git/zip)

## PR-CORE1-12-STATUS.md
- PR-CORE1-12-STATUS.md:9: - ✅ Re-added `build_njr_from_legacy_pipeline_config` with deprecation comment (still used by deprecated run_pipeline method)
- PR-CORE1-12-STATUS.md:14: - ✅ Clearly states "Runtime pipeline execution via pipeline_config has been REMOVED"
- PR-CORE1-12-STATUS.md:18: - `_validate_pipeline_config()` - Legacy validation with DEPRECATED marker
- PR-CORE1-12-STATUS.md:23: - `build_pipeline_config_v2()` - Internal builder, marked as still used by NJR temporarily
- PR-CORE1-12-STATUS.md:24: - `_build_pipeline_config()` - Internal builder, marked for future refactoring
- PR-CORE1-12-STATUS.md:27: - ✅ Added PR-CORE1-12 comments to all 6 `pipeline_config_panel_v2` references
- PR-CORE1-12-STATUS.md:32: - ✅ Documented that it uses legacy adapter (build_njr_from_legacy_pipeline_config)
- PR-CORE1-12-STATUS.md:37: - `_build_pipeline_config_from_state()` - Used by NJR builder internally
- PR-CORE1-12-STATUS.md:38: - `build_pipeline_config_with_profiles()` - Model profile integration during NJR construction
- PR-CORE1-12-STATUS.md:47: 1. **src/controller/pipeline_config_assembler.py**
- PR-CORE1-12-STATUS.md:48: - ✅ Moved to `src/controller/archive/pipeline_config_assembler.py`
- PR-CORE1-12-STATUS.md:51: 2. **src/gui/panels_v2/pipeline_config_panel_v2.py**
- PR-CORE1-12-STATUS.md:52: - ✅ Moved to `src/gui/panels_v2/archive/pipeline_config_panel_v2.py`
- PR-CORE1-12-STATUS.md:55: 3. **src/gui/views/pipeline_config_panel.py**
- PR-CORE1-12-STATUS.md:56: - ✅ Moved to `src/gui/views/archive/pipeline_config_panel.py`
- PR-CORE1-12-STATUS.md:67: - ✅ Commented out `PipelineConfigPanel` import in `_build_pipeline_config_section()`
- PR-CORE1-12-STATUS.md:84: - ✅ Added deprecation docstring to `_pipeline_config_from_njr()` method
- PR-CORE1-12-STATUS.md:92: - ✅ All docstrings emphasize: "pipeline_config is DEPRECATED"
- PR-CORE1-12-STATUS.md:101: - ✅ Grep search for `pipeline_config=` in `tests/**/*.py` returned **ZERO matches**
- PR-CORE1-12-STATUS.md:102: - ✅ This means `Job(..., pipeline_config=...)` is already removed from ALL tests
- PR-CORE1-12-STATUS.md:112: 1. ✅ **Grep shows no runtime use of pipeline_config (excluding compat data)**
- PR-CORE1-12-STATUS.md:117: - No runtime execution uses pipeline_config as payload ✅
- PR-CORE1-12-STATUS.md:124: 3. ✅ **All tests run green** (already validated - no pipeline_config= in tests)
- PR-CORE1-12-STATUS.md:126: 4. ✅ **pipeline_config exists ONLY in:**
- PR-CORE1-12-STATUS.md:146: - src/controller/archive/pipeline_config_assembler.py
- PR-CORE1-12-STATUS.md:147: - src/gui/panels_v2/archive/pipeline_config_panel_v2.py
- PR-CORE1-12-STATUS.md:148: - src/gui/views/archive/pipeline_config_panel.py
- PR-CORE1-12-STATUS.md:156: - Refactor `_build_pipeline_config_from_state()` to directly build NJR fields
- PR-CORE1-12-STATUS.md:157: - Refactor `build_pipeline_config_with_profiles()` for model profiles
- PR-CORE1-12-STATUS.md:164: - **Test Coverage**: Already validated (no pipeline_config= in tests)
- PR-CORE1-12-STATUS.md:185: - `_pipeline_config_from_njr()` method (still needed internally for NJR→execution)
- PR-CORE1-12-STATUS.md:189: - Update comments about pipeline_config being legacy
- PR-CORE1-12-STATUS.md:194: - src/gui/panels_v2/pipeline_config_panel_v2.py - ARCHIVE
- PR-CORE1-12-STATUS.md:195: - src/controller/pipeline_config_assembler.py - ARCHIVE
- PR-CORE1-12-STATUS.md:198: Since Job(..., pipeline_config=...) is already removed from tests, the CRITICAL work is done.
- PR-CORE1-12-STATUS.md:204: 3. Ensuring no runtime execution uses pipeline_config

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

## pipeline_config_refs.md
- pipeline_config_refs.md:1: # pipeline_config references (excluding archive/.git/zip)
- pipeline_config_refs.md:4: - PR-CORE1-12-STATUS.md:9: - ✅ Re-added `build_njr_from_legacy_pipeline_config` with deprecation comment (still used by deprecated run_pipeline method)
- pipeline_config_refs.md:5: - PR-CORE1-12-STATUS.md:14: - ✅ Clearly states "Runtime pipeline execution via pipeline_config has been REMOVED"
- pipeline_config_refs.md:6: - PR-CORE1-12-STATUS.md:18: - `_validate_pipeline_config()` - Legacy validation with DEPRECATED marker
- pipeline_config_refs.md:7: - PR-CORE1-12-STATUS.md:23: - `build_pipeline_config_v2()` - Internal builder, marked as still used by NJR temporarily
- pipeline_config_refs.md:8: - PR-CORE1-12-STATUS.md:24: - `_build_pipeline_config()` - Internal builder, marked for future refactoring
- pipeline_config_refs.md:9: - PR-CORE1-12-STATUS.md:27: - ✅ Added PR-CORE1-12 comments to all 6 `pipeline_config_panel_v2` references
- pipeline_config_refs.md:10: - PR-CORE1-12-STATUS.md:32: - ✅ Documented that it uses legacy adapter (build_njr_from_legacy_pipeline_config)
- pipeline_config_refs.md:11: - PR-CORE1-12-STATUS.md:37: - `_build_pipeline_config_from_state()` - Used by NJR builder internally
- pipeline_config_refs.md:12: - PR-CORE1-12-STATUS.md:38: - `build_pipeline_config_with_profiles()` - Model profile integration during NJR construction
- pipeline_config_refs.md:13: - PR-CORE1-12-STATUS.md:47: 1. **src/controller/pipeline_config_assembler.py**
- pipeline_config_refs.md:14: - PR-CORE1-12-STATUS.md:48: - ✅ Moved to `src/controller/archive/pipeline_config_assembler.py`
- pipeline_config_refs.md:15: - PR-CORE1-12-STATUS.md:51: 2. **src/gui/panels_v2/pipeline_config_panel_v2.py**
- pipeline_config_refs.md:16: - PR-CORE1-12-STATUS.md:52: - ✅ Moved to `src/gui/panels_v2/archive/pipeline_config_panel_v2.py`
- pipeline_config_refs.md:17: - PR-CORE1-12-STATUS.md:55: 3. **src/gui/views/pipeline_config_panel.py**
- pipeline_config_refs.md:18: - PR-CORE1-12-STATUS.md:56: - ✅ Moved to `src/gui/views/archive/pipeline_config_panel.py`
- pipeline_config_refs.md:19: - PR-CORE1-12-STATUS.md:67: - ✅ Commented out `PipelineConfigPanel` import in `_build_pipeline_config_section()`
- pipeline_config_refs.md:20: - PR-CORE1-12-STATUS.md:84: - ✅ Added deprecation docstring to `_pipeline_config_from_njr()` method
- pipeline_config_refs.md:21: - PR-CORE1-12-STATUS.md:92: - ✅ All docstrings emphasize: "pipeline_config is DEPRECATED"
- pipeline_config_refs.md:22: - PR-CORE1-12-STATUS.md:101: - ✅ Grep search for `pipeline_config=` in `tests/**/*.py` returned **ZERO matches**
- pipeline_config_refs.md:23: - PR-CORE1-12-STATUS.md:102: - ✅ This means `Job(..., pipeline_config=...)` is already removed from ALL tests
- pipeline_config_refs.md:24: - PR-CORE1-12-STATUS.md:112: 1. ✅ **Grep shows no runtime use of pipeline_config (excluding compat data)**
- pipeline_config_refs.md:25: - PR-CORE1-12-STATUS.md:117: - No runtime execution uses pipeline_config as payload ✅
- pipeline_config_refs.md:26: - PR-CORE1-12-STATUS.md:124: 3. ✅ **All tests run green** (already validated - no pipeline_config= in tests)
- pipeline_config_refs.md:27: - PR-CORE1-12-STATUS.md:126: 4. ✅ **pipeline_config exists ONLY in:**
- pipeline_config_refs.md:28: - PR-CORE1-12-STATUS.md:146: - src/controller/archive/pipeline_config_assembler.py
- pipeline_config_refs.md:29: - PR-CORE1-12-STATUS.md:147: - src/gui/panels_v2/archive/pipeline_config_panel_v2.py
- pipeline_config_refs.md:30: - PR-CORE1-12-STATUS.md:148: - src/gui/views/archive/pipeline_config_panel.py
- pipeline_config_refs.md:31: - PR-CORE1-12-STATUS.md:156: - Refactor `_build_pipeline_config_from_state()` to directly build NJR fields
- pipeline_config_refs.md:32: - PR-CORE1-12-STATUS.md:157: - Refactor `build_pipeline_config_with_profiles()` for model profiles
- pipeline_config_refs.md:33: - PR-CORE1-12-STATUS.md:164: - **Test Coverage**: Already validated (no pipeline_config= in tests)
- pipeline_config_refs.md:34: - PR-CORE1-12-STATUS.md:185: - `_pipeline_config_from_njr()` method (still needed internally for NJR→execution)
- pipeline_config_refs.md:35: - PR-CORE1-12-STATUS.md:189: - Update comments about pipeline_config being legacy
- pipeline_config_refs.md:36: - PR-CORE1-12-STATUS.md:194: - src/gui/panels_v2/pipeline_config_panel_v2.py - ARCHIVE
- pipeline_config_refs.md:37: - PR-CORE1-12-STATUS.md:195: - src/controller/pipeline_config_assembler.py - ARCHIVE
- pipeline_config_refs.md:38: - PR-CORE1-12-STATUS.md:198: Since Job(..., pipeline_config=...) is already removed from tests, the CRITICAL work is done.
- pipeline_config_refs.md:39: - PR-CORE1-12-STATUS.md:204: 3. Ensuring no runtime execution uses pipeline_config
- pipeline_config_refs.md:42: - docs\ARCHITECTURAL_DEBT_ANALYSIS.md:33: # Legacy jobs imported from history still carry pipeline_config blobs.
- pipeline_config_refs.md:43: - docs\ARCHITECTURAL_DEBT_ANALYSIS.md:34: job = Job(job_id="legacy", pipeline_config=None)
- pipeline_config_refs.md:44: - docs\ARCHITECTURAL_DEBT_ANALYSIS.md:35: job.pipeline_config = PipelineConfig(...)
- pipeline_config_refs.md:45: - docs\ARCHITECTURAL_DEBT_ANALYSIS.md:41: > **Status:** Restricted to legacy history imports (PR-CORE1-C2). New jobs never populate `pipeline_config`; any legacy payloads are rehydrated from history via the adapter.
- pipeline_config_refs.md:46: - docs\ARCHITECTURAL_DEBT_ANALYSIS.md:200: - Status: Conflicts with pipeline_config, creates ambiguity
- pipeline_config_refs.md:47: - docs\ARCHITECTURAL_DEBT_ANALYSIS.md:217: 1. **Pick ONE job type:** NormalizedJobRecord; pipeline_config-only jobs are retired and exist solely as legacy history blobs (PR-CORE1-C2).
- pipeline_config_refs.md:48: - docs\ARCHITECTURAL_DEBT_ANALYSIS.md:348: - DTOs derive from `NormalizedJobRecord` snapshots, NOT from `pipeline_config`
- pipeline_config_refs.md:49: - docs\ARCHITECTURAL_DEBT_ANALYSIS.md:350: - Legacy `pipeline_config` fallback preserved only for old jobs without NJR snapshots
- pipeline_config_refs.md:50: - docs\ARCHITECTURAL_DEBT_ANALYSIS.md:365: - ❌ Removed: `pipeline_config` introspection for display purposes (new jobs)
- pipeline_config_refs.md:51: - docs\ARCHITECTURAL_DEBT_ANALYSIS.md:366: - ✅ Preserved: `pipeline_config` execution path (unchanged per CORE1-A3 scope)
- pipeline_config_refs.md:52: - docs\ARCHITECTURAL_DEBT_ANALYSIS.md:373: - No display logic introspects `pipeline_config`
- pipeline_config_refs.md:53: - docs\ARCHITECTURAL_DEBT_ANALYSIS.md:379: - ✅ No fallback to `pipeline_config` for NJR-backed jobs (failures return error status)
- pipeline_config_refs.md:54: - docs\ARCHITECTURAL_DEBT_ANALYSIS.md:382: - ⚠️ PR-CORE1-B3: _to_queue_job() clears pipeline_config, so NJR-only jobs never expose it
- pipeline_config_refs.md:55: - docs\ARCHITECTURAL_DEBT_ANALYSIS.md:383: - ⏳ `pipeline_config` field still exists as **legacy debug field** for inspection
- pipeline_config_refs.md:56: - docs\ARCHITECTURAL_DEBT_ANALYSIS.md:384: - ⏳ `pipeline_config` execution branch preserved for **legacy jobs only** (pre-v2.6, imported)
- pipeline_config_refs.md:57: - docs\ARCHITECTURAL_DEBT_ANALYSIS.md:385: - **Remaining work: Full pipeline_config field/method removal (CORE1-C) - after legacy job migration complete**
- pipeline_config_refs.md:58: - docs\ARCHITECTURAL_DEBT_ANALYSIS.md:405: | Execution payload | `pipeline_config` | `pipeline_config` | **Hybrid (NJR preferred)** | **NJR-only (new jobs, pipeline_config removed)** ✅ | NJR |
- pipeline_config_refs.md:59: - docs\ARCHITECTURAL_DEBT_ANALYSIS.md:412: - ✅ CORE1-D1 migrates legacy history to NJR-only snapshots; history replay no longer depends on pipeline_config payloads.
- pipeline_config_refs.md:60: - docs\ARCHITECTURAL_DEBT_ANALYSIS.md:413: - ƒo. PR-CORE1-B3 ensures _to_queue_job() clears pipeline_config, so new jobs carry only NJR snapshots
- pipeline_config_refs.md:61: - docs\ARCHITECTURAL_DEBT_ANALYSIS.md:415: **Debt Resolved (CORE1-D1/D2/D3):** Legacy history formats, pipeline_config persistence, mixed-era draft-bundle records, schema drift, and multiple replay paths are eliminated; history_schema 2.6 is enforced on load/save via HistoryMigrationEngine + schema normalization, and replay is unified through NJR → RunPlan → PipelineRunner.run_njr.
- pipeline_config_refs.md:62: - docs\ARCHITECTURAL_DEBT_ANALYSIS.md:421: 2. The GUI preview panel reads these normalized records directly, avoiding any legacy `pipeline_config` inspection whenever packs are present.
- pipeline_config_refs.md:63: - docs\ARCHITECTURAL_DEBT_ANALYSIS.md:432: 1. `state/queue_state_v2.json` now stores NJR snapshots plus strict queue metadata (`queue_id`, `status`, `priority`, `created_at`, `queue_schema == "2.6"`, optional metadata, auto-run/paused flags). `_normalized_record`, `pipeline_config`, draft/bundle blobs, and other duplicated execution data are stripped so queue snapshots never diverge from NJR semantics.
- pipeline_config_refs.md:64: - docs\ARCHITECTURAL_DEBT_ANALYSIS.md:437: - Debt removed: queue item schema drift, transitional `_normalized_record` field, pipeline_config remnants in persistence, and inconsistent queue/history summaries.
- pipeline_config_refs.md:67: - docs\ARCHITECTURE_v2.6.md:24: pipeline_config–derived jobs
- pipeline_config_refs.md:68: - docs\ARCHITECTURE_v2.6.md:368: No pipeline_config jobs
- pipeline_config_refs.md:69: - docs\ARCHITECTURE_v2.6.md:407: - All display data comes from NJR snapshots, NOT from pipeline_config
- pipeline_config_refs.md:70: - docs\ARCHITECTURE_v2.6.md:416: → on failure → return error status (NO fallback to pipeline_config)
- pipeline_config_refs.md:71: - docs\ARCHITECTURE_v2.6.md:418: This Job object no longer exposes a `pipeline_config` field; `_normalized_record` is the only execution payload carried between subsystems.
- pipeline_config_refs.md:72: - docs\ARCHITECTURE_v2.6.md:422: Job (with only pipeline_config, no normalized_record) →
- pipeline_config_refs.md:73: - docs\ARCHITECTURE_v2.6.md:424: → _run_pipeline_via_runner_only(pipeline_config) → PipelineRunner.run_njr(legacy NJR adapter)
- pipeline_config_refs.md:74: - docs\ARCHITECTURE_v2.6.md:435: - If NJR execution fails, the job is marked as failed (no pipeline_config fallback)
- pipeline_config_refs.md:75: - docs\ARCHITECTURE_v2.6.md:436: - The queue `Job` model no longer defines `pipeline_config`; new jobs never expose or persist this field (PR-CORE1-C2).
- pipeline_config_refs.md:76: - docs\ARCHITECTURE_v2.6.md:437: - Any remaining `pipeline_config` payloads live in legacy history entries and are rehydrated via `legacy_njr_adapter.build_njr_from_legacy_pipeline_config()`.
- pipeline_config_refs.md:77: - docs\ARCHITECTURE_v2.6.md:441: - The queue snapshot file (`state/queue_state_v2.json`) now records `queue_schema`, `queue_id`, `njr_snapshot`, `priority`, `status`, `created_at`, and lightweight metadata such as `source`/`prompt_source`. Every entry derives directly from the NJR snapshot and drops deprecated keys (`pipeline_config`, bundle summaries, draft blobs) before serialization so that the file always reflects canonical NJR data.
- pipeline_config_refs.md:78: - docs\ARCHITECTURE_v2.6.md:450: | V2.0 Pre‑NJR | JSONL entries containing only `pipeline_config` blobs and ad-hoc `result` dictionaries | Legacy JSON queues with `pipeline_config` per job | Written entries are normalized with `HistoryMigrationEngine`, `QueueMigrationEngine`, and `legacy_njr_adapter` before execution |
- pipeline_config_refs.md:79: - docs\ARCHITECTURE_v2.6.md:459: 3. `legacy_njr_adapter` remains the only adapter for deriving NJRs from pipeline_config-heavy records; replay requests rely entirely on the resulting NJRs plus the unified runner path.
- pipeline_config_refs.md:80: - docs\ARCHITECTURE_v2.6.md:464: - The queue `Job` model no longer exposes `pipeline_config`; `PipelineController._to_queue_job()` instantiates NJR-only jobs without storing pipeline_config.
- pipeline_config_refs.md:81: - docs\ARCHITECTURE_v2.6.md:465: - Queue/JobService/History treat `pipeline_config` as legacy metadata; only imported pre-v2.6 jobs may still store a non-null value via manual assignment.
- pipeline_config_refs.md:82: - docs\ARCHITECTURE_v2.6.md:468: - Legacy `PipelineConfig` executions pass through `legacy_njr_adapter.build_njr_from_legacy_pipeline_config()` and then run through `run_njr`, ensuring the runner core only sees NJRs.
- pipeline_config_refs.md:83: - docs\ARCHITECTURE_v2.6.md:474: - ✅ Display DTOs never introspect pipeline_config (use NJR snapshots)
- pipeline_config_refs.md:84: - docs\ARCHITECTURE_v2.6.md:478: - ??O `pipeline_config` is removed from queue `Job` instances (PR-CORE1-C2); NJR snapshots are the only executable payloads.
- pipeline_config_refs.md:85: - docs\ARCHITECTURE_v2.6.md:483: Legacy history formats are migrated in-memory to NJR snapshots via `HistoryMigrationEngine`. Replay paths no longer accept `pipeline_config` or draft-bundle structures; hydration is NJR-only.
- pipeline_config_refs.md:86: - docs\ARCHITECTURE_v2.6.md:500: History → Restore replays job by reconstructing NJR from snapshot. History load is NJR hydration only; any legacy fields (pipeline_config, draft bundles) are stripped and normalized on load.
- pipeline_config_refs.md:87: - docs\ARCHITECTURE_v2.6.md:501: **History Schema v2.6 (CORE1-D2):** History load = pure NJR hydration + schema normalization. Every persisted entry MUST contain: `id`, `timestamp`, `status`, `history_schema`, `njr_snapshot`, `ui_summary`, `metadata`, `runtime`. Deprecated fields (pipeline_config, draft/draft_bundle/job_bundle, legacy_* blobs) are forbidden and removed during migration. All entries are written in deterministic order; `history_schema` is always `2.6`.
- pipeline_config_refs.md:88: - docs\ARCHITECTURE_v2.6.md:503: **Queue Schema v2.6 (CORE1-D5):** `state/queue_state_v2.json` mirrors History Schema v2.6 by storing `njr_snapshot` plus scheduling metadata (`queue_id`, `status`, `priority`, `created_at`, `queue_schema == "2.6"`, optional `metadata`, auto-run/paused flags). Deprecated fields such as `_normalized_record`, `pipeline_config`, `draft_bundle_summary`, `legacy_config_blob`, and any other duplicated execution data are stripped on load/save so queue snapshots never duplicate NJR state. Tests (`tests/queue/test_job_history_store.py`, `tests/pipeline/test_job_queue_persistence_v2.py`) now assert queue persistence only yields NJR-backed entries and that normalization remains idempotent.
- pipeline_config_refs.md:89: - docs\ARCHITECTURE_v2.6.md:509: **Unified Replay Path (CORE1-D3):** Replay starts from a validated v2.6 HistoryRecord → hydrate NJR snapshot → build RunPlan via `build_run_plan_from_njr` → execute `PipelineRunner.run_njr(run_plan)` → return RunResult. No legacy replay branches, no pipeline_config rebuilds, no controller-local shortcuts. Fresh runs and replays share the exact NJR → RunPlan → Runner chain.
- pipeline_config_refs.md:90: - docs\ARCHITECTURE_v2.6.md:606: pipeline_config or legacy config union models
- pipeline_config_refs.md:91: - docs\ARCHITECTURE_v2.6.md:612: PromptPack-driven previews are now built via `PromptPackNormalizedJobBuilder` inside `PipelineController.get_preview_jobs()`: AppStateV2.job_draft.packs flow through the same NJR builder that execution uses, and the resulting records are stored in AppStateV2.preview_jobs so the GUI preview panel always renders prompt-pack-derived positive prompts/models without exposing pipeline_config or legacy drafts.
- pipeline_config_refs.md:92: - docs\ARCHITECTURE_v2.6.md:704: - Tests and helpers construct Jobs from NJRs only; `pipeline_config=` job construction is removed from new paths.
- pipeline_config_refs.md:95: - docs\Builder Pipeline Deep-Dive (v2.6).md:367: - NJRs are the only execution payload produced by JobBuilderV2 for v2.6 jobs; pipeline_config is left None.
- pipeline_config_refs.md:96: - docs\Builder Pipeline Deep-Dive (v2.6).md:368: - PipelineController._to_queue_job() attaches _normalized_record, sets pipeline_config = None, and builds NJR-driven queue/history snapshots.
- pipeline_config_refs.md:97: - docs\Builder Pipeline Deep-Dive (v2.6).md:369: - Queue, JobService, Runner, and History rely on NJR snapshots for display/execution. Any non-null pipeline_config values belong to legacy pre-v2.6 data.
- pipeline_config_refs.md:98: - docs\Builder Pipeline Deep-Dive (v2.6).md:371: Queue persistence output remains the JSON dump stored at `state/queue_state_v2.json`; D5 enforces that the file only ever contains NJR snapshots plus queue metadata (`queue_id`, `status`, `priority`, `created_at`, `queue_schema == "2.6"`, optional metadata, auto-run/paused flags) and no `_normalized_record`, pipeline_config, or bundle/draft keys. Queue persistence tests confirm this invariance, proving the queue file already mirrors history’s NJR schema even before D6 introduces the shared JSONL codec/format that will eventually let history and queue share the same serialization layer.
- pipeline_config_refs.md:101: - docs\CORE1-D Roadmap — History Integrity, Persistence Cleanup(v2.6).md:24: pipeline_config
- pipeline_config_refs.md:102: - docs\CORE1-D Roadmap — History Integrity, Persistence Cleanup(v2.6).md:59: No history entry anywhere in the repo contains pipeline_config.
- pipeline_config_refs.md:103: - docs\CORE1-D Roadmap — History Integrity, Persistence Cleanup(v2.6).md:367: No pipeline_config references anywhere.
- pipeline_config_refs.md:106: - docs\E2E_Golden_Path_Test_Matrix_v2.6.md:578: - End-to-end queue tests no longer construct jobs with `pipeline_config=`; they wrap NormalizedJobRecord snapshots instead.
- pipeline_config_refs.md:109: - docs\StableNew — Formal Strategy Document (v2.6).md:239: pipeline_config snapshots not aligned to NJR
- pipeline_config_refs.md:112: - docs\StableNew_Coding_and_Testing_v2.6.md:380: Tests must not assert against legacy job DTOs (`JobUiSummary`, `JobQueueItemDTO`, `JobHistoryItemDTO`); controller and history tests should derive summaries via `JobView.from_njr()` (or `JobHistoryService.summarize_history_record()`) and never reconstruct pipeline_config fragments.
- pipeline_config_refs.md:113: - docs\StableNew_Coding_and_Testing_v2.6.md:437: **FORBIDDEN:** Controllers, JobService, and Queue/Runner MUST NOT reference `pipeline_config` on `Job` instances; the field no longer exists in the queue model (PR-CORE1-C2).
- pipeline_config_refs.md:114: - docs\StableNew_Coding_and_Testing_v2.6.md:439: **FORBIDDEN:** If NJR execution fails for an NJR-backed job, the execution path MUST NOT fall back to `pipeline_config`. The job should be marked as failed.
- pipeline_config_refs.md:115: - docs\StableNew_Coding_and_Testing_v2.6.md:441: **LEGACY-ONLY:** `pipeline_config` execution branch is allowed ONLY for jobs without `_normalized_record` (imported from old history, pre-v2.6 jobs).
- pipeline_config_refs.md:116: - docs\StableNew_Coding_and_Testing_v2.6.md:449: `pipeline_config` field no longer exists on Job objects created via JobBuilderV2; new jobs rely solely on NJR snapshots (PR-CORE1-C2). Legacy pipeline_config data lives only in history entries and is rehydrated via `legacy_njr_adapter.build_njr_from_legacy_pipeline_config()`.
- pipeline_config_refs.md:117: - docs\StableNew_Coding_and_Testing_v2.6.md:451: **PR-CORE1-B4:** `PipelineRunner.run(config)` no longer exists. Tests (both unit and integration) must exercise `run_njr()` exclusively and may rely on the legacy adapter if they need to replay pipeline_config-only data.
- pipeline_config_refs.md:118: - docs\StableNew_Coding_and_Testing_v2.6.md:459: Tests MUST verify that NJR execution failures result in job error status (NO fallback to pipeline_config).
- pipeline_config_refs.md:119: - docs\StableNew_Coding_and_Testing_v2.6.md:460: Tests MUST verify that new queue jobs do not expose a `pipeline_config` field (PR-CORE1-C2); any legacy coverage should work through history data only.
- pipeline_config_refs.md:120: - docs\StableNew_Coding_and_Testing_v2.6.md:461: Tests covering queue persistence (`tests/queue/test_job_queue_persistence_v2.py`, `tests/queue/test_job_history_store.py`) must inspect `state/queue_state_v2.json` and assert every entry ships with `njr_snapshot` plus queue metadata only (`queue_id`, `priority`, `status`, `created_at`, optional auto-run/paused flags) and that forbidden keys like `pipeline_config`, `_normalized_record`, or `draft`/`bundle` blobs never survive serialization; this proves queue I/O already matches history’s NJR semantics until D6 unifies the queue file with history’s JSONL codec.
- pipeline_config_refs.md:121: - docs\StableNew_Coding_and_Testing_v2.6.md:463: Tests MUST NOT reference `pipeline_config` or legacy job dicts in persistence/replay suites; all history-oriented tests hydrate NJRs from snapshots.
- pipeline_config_refs.md:122: - docs\StableNew_Coding_and_Testing_v2.6.md:474: Tests for legacy jobs (without NJR) MUST verify `pipeline_config` branch still works.
- pipeline_config_refs.md:125: - docs\older\ARCHITECTURE_v2_COMBINED.md:319: `pipeline_runner.run_full_pipeline(pipeline_config, logger=..., callbacks=...)`
- pipeline_config_refs.md:128: - docs\older\ChatGPT-WhyNoPipeline.md:65: 'src/gui/views/pipeline_config_panel.py',
- pipeline_config_refs.md:129: - docs\older\ChatGPT-WhyNoPipeline.md:1265: 174         if hasattr(self, "pipeline_tab") and hasattr(self.pipeline_tab, "pipeline_config_panel"):
- pipeline_config_refs.md:130: - docs\older\ChatGPT-WhyNoPipeline.md:1267: 176                 self.pipeline_tab.pipeline_config_panel.controller = controller
- pipeline_config_refs.md:131: - docs\older\ChatGPT-WhyNoPipeline.md:1576: 1259         is_valid, message = self._validate_pipeline_config()
- pipeline_config_refs.md:132: - docs\older\ChatGPT-WhyNoPipeline.md:1625: 1304             pipeline_config = self.build_pipeline_config_v2()
- pipeline_config_refs.md:133: - docs\older\ChatGPT-WhyNoPipeline.md:1627: 1306             executor_config = self.pipeline_runner._build_executor_config(pipeline_config)
- pipeline_config_refs.md:134: - docs\older\ChatGPT-WhyNoPipeline.md:1628: 1307             self._cache_last_run_payload(executor_config, pipeline_config)
- pipeline_config_refs.md:135: - docs\older\ChatGPT-WhyNoPipeline.md:1629: 1308             self.pipeline_runner.run(pipeline_config, cancel_token, self._append_log_threadsafe)
- pipeline_config_refs.md:136: - docs\older\ChatGPT-WhyNoPipeline.md:1657: 1185     def _run_pipeline_via_runner_only(self, pipeline_config: PipelineConfig) -> Any:
- pipeline_config_refs.md:137: - docs\older\ChatGPT-WhyNoPipeline.md:1662: 1190         executor_config = runner._build_executor_config(pipeline_config)
- pipeline_config_refs.md:138: - docs\older\ChatGPT-WhyNoPipeline.md:1663: 1191         self._cache_last_run_payload(executor_config, pipeline_config)
- pipeline_config_refs.md:139: - docs\older\ChatGPT-WhyNoPipeline.md:1664: 1192         return runner.run(pipeline_config, None, self._append_log_threadsafe)
- pipeline_config_refs.md:140: - docs\older\ChatGPT-WhyNoPipeline.md:1860: 1051         is_valid, message = self._validate_pipeline_config()
- pipeline_config_refs.md:141: - docs\older\ChatGPT-WhyNoPipeline.md:1884: 1072         pipeline_config = self.build_pipeline_config_v2()
- pipeline_config_refs.md:142: - docs\older\ChatGPT-WhyNoPipeline.md:1888: 1076         result = self.pipeline_controller.run_pipeline(pipeline_config)
- pipeline_config_refs.md:143: - docs\older\ChatGPT-WhyNoPipeline.md:1891: 1079     def _execute_pipeline_via_runner(self, pipeline_config: PipelineConfig) -> Any:
- pipeline_config_refs.md:144: - docs\older\ChatGPT-WhyNoPipeline.md:1898: 1086         result = runner.run(pipeline_config, self.pipeline_controller.cancel_token, self._append_log_threadsafe)
- pipeline_config_refs.md:145: - docs\older\ChatGPT-WhyNoPipeline.md:1901: 1089     def _run_pipeline_from_tab(self, pipeline_tab: Any, pipeline_config: PipelineConfig) -> Any:
- pipeline_config_refs.md:146: - docs\older\ChatGPT-WhyNoPipeline.md:1928: 1116         return self._run_pipeline_via_runner_only(pipeline_config)
- pipeline_config_refs.md:147: - docs\older\ChatGPT-WhyNoPipeline.md:1977: 1304             pipeline_config = self.build_pipeline_config_v2()
- pipeline_config_refs.md:148: - docs\older\ChatGPT-WhyNoPipeline.md:1979: 1306             executor_config = self.pipeline_runner._build_executor_config(pipeline_config)
- pipeline_config_refs.md:149: - docs\older\ChatGPT-WhyNoPipeline.md:1980: 1307             self._cache_last_run_payload(executor_config, pipeline_config)
- pipeline_config_refs.md:150: - docs\older\ChatGPT-WhyNoPipeline.md:1981: 1308             self.pipeline_runner.run(pipeline_config, cancel_token, self._append_log_threadsafe)
- pipeline_config_refs.md:151: - docs\older\ChatGPT-WhyNoPipeline.md:2011: 1304             pipeline_config = self.build_pipeline_config_v2()
- pipeline_config_refs.md:152: - docs\older\ChatGPT-WhyNoPipeline.md:2013: 1306             executor_config = self.pipeline_runner._build_executor_config(pipeline_config)
- pipeline_config_refs.md:153: - docs\older\ChatGPT-WhyNoPipeline.md:2014: 1307             self._cache_last_run_payload(executor_config, pipeline_config)
- pipeline_config_refs.md:154: - docs\older\ChatGPT-WhyNoPipeline.md:2015: 1308             self.pipeline_runner.run(pipeline_config, cancel_token, self._append_log_threadsafe)
- pipeline_config_refs.md:155: - docs\older\ChatGPT-WhyNoPipeline.md:2049: from src.controller.pipeline_config_assembler import PipelineConfigAssembler, GuiOverrides, RunPlan, PlannedJob
- pipeline_config_refs.md:156: - docs\older\ChatGPT-WhyNoPipeline.md:2497: Perhaps validation is failing, causing an early return in on_run_clicked due to _validate_pipeline_config, but the user didn’t mention seeing any error messages. Maybe the run button still points to the old start_run, not start_run_v2.
- pipeline_config_refs.md:157: - docs\older\ChatGPT-WhyNoPipeline.md:2500: The internal _start_run_v2 directly uses the pipeline_controller, while on_run_clicked calls _run_pipeline_thread, which uses pipeline_runner.run without relying on a job queue. However, _run_pipeline_thread still constructs pipeline_config via build_pipeline_config_v2, so that should be fine.
- pipeline_config_refs.md:158: - docs\older\ChatGPT-WhyNoPipeline.md:3229: 385             config = self._build_pipeline_config_from_state()
- pipeline_config_refs.md:159: - docs\older\ChatGPT-WhyNoPipeline.md:3268: 385             config = self._build_pipeline_config_from_state()
- pipeline_config_refs.md:160: - docs\older\ChatGPT-WhyNoPipeline.md:3340: I ran into an index issue again, but I've already seen run_pipeline. Now I’m wondering how PipelineController is used by AppController._run_via_pipeline_controller. This method seems to build the pipeline_config using self.build_pipeline_config_v2() and likely decides between direct and queue run-modes. I’ll check lines 1075-1116 to be sure.
- pipeline_config_refs.md:161: - docs\older\ChatGPT-WhyNoPipeline.md:3350: 1072         pipeline_config = self.build_pipeline_config_v2()
- pipeline_config_refs.md:162: - docs\older\ChatGPT-WhyNoPipeline.md:3354: 1076         result = self.pipeline_controller.run_pipeline(pipeline_config)
- pipeline_config_refs.md:163: - docs\older\ChatGPT-WhyNoPipeline.md:3357: 1079     def _execute_pipeline_via_runner(self, pipeline_config: PipelineConfig) -> Any:
- pipeline_config_refs.md:164: - docs\older\ChatGPT-WhyNoPipeline.md:3364: 1086         result = runner.run(pipeline_config, self.pipeline_controller.cancel_token, self._append_log_threadsafe)
- pipeline_config_refs.md:165: - docs\older\ChatGPT-WhyNoPipeline.md:3367: 1089     def _run_pipeline_from_tab(self, pipeline_tab: Any, pipeline_config: PipelineConfig) -> Any:
- pipeline_config_refs.md:166: - docs\older\ChatGPT-WhyNoPipeline.md:3394: 1116         return self._run_pipeline_via_runner_only(pipeline_config)
- pipeline_config_refs.md:167: - docs\older\ChatGPT-WhyNoPipeline.md:5082: 174         if hasattr(self, "pipeline_tab") and hasattr(self.pipeline_tab, "pipeline_config_panel"):
- pipeline_config_refs.md:168: - docs\older\ChatGPT-WhyNoPipeline.md:5084: 176                 self.pipeline_tab.pipeline_config_panel.controller = controller
- pipeline_config_refs.md:169: - docs\older\ChatGPT-WhyNoPipeline.md:5175: mw.pipeline_config_panel_v2 = getattr(getattr(mw.pipeline_tab, "sidebar", None), "pipeline_config_panel", None)
- pipeline_config_refs.md:170: - docs\older\ChatGPT-WhyNoPipeline.md:5246: mw.pipeline_config_panel_v2 = getattr(getattr(mw.pipeline_tab, "sidebar", None), "pipeline_config_panel", None)
- pipeline_config_refs.md:171: - docs\older\ChatGPT-WhyNoPipeline.md:5506: 22 from src.controller.pipeline_config_assembler import PipelineConfigAssembler, GuiOverrides, RunPlan, PlannedJob
- pipeline_config_refs.md:172: - docs\older\ChatGPT-WhyNoPipeline.md:5552: 68             pipeline_config=config,
- pipeline_config_refs.md:173: - docs\older\ChatGPT-WhyNoPipeline.md:5696: job = Job(job_id=job_id, pipeline_config=None, priority=priority, payload=pipeline_callable, worker_id=worker_id)
- pipeline_config_refs.md:174: - docs\older\ChatGPT-WhyNoPipeline.md:5800: job = Job(job_id=job_id, pipeline_config=None, priority=priority, payload=pipeline_callable, worker_id=worker_id)
- pipeline_config_refs.md:177: - docs\older\GUI-Pipeline-Hierarchy-Diagram.txt:16: │   │           ├── pipeline_config_card (_SidebarCard)
- pipeline_config_refs.md:178: - docs\older\GUI-Pipeline-Hierarchy-Diagram.txt:17: │   │           │   └── pipeline_config_panel (PipelineConfigPanel)
- pipeline_config_refs.md:181: - docs\older\LEGACY_CANDIDATES.md:38: - `src/gui/views/pipeline_config_panel.py` (unreachable)
- pipeline_config_refs.md:182: - docs\older\LEGACY_CANDIDATES.md:64: - `tests/gui_v2/test_gui_v2_pipeline_config_roundtrip.py` (unreachable)
- pipeline_config_refs.md:183: - docs\older\LEGACY_CANDIDATES.md:152: - `src/controller/pipeline_config_assembler.py` (unreachable)
- pipeline_config_refs.md:184: - docs\older\LEGACY_CANDIDATES.md:161: - `tests/controller/test_pipeline_config_assembler.py` (unreachable)
- pipeline_config_refs.md:185: - docs\older\LEGACY_CANDIDATES.md:162: - `tests/controller/test_pipeline_config_assembler_core_fields.py` (unreachable)
- pipeline_config_refs.md:186: - docs\older\LEGACY_CANDIDATES.md:163: - `tests/controller/test_pipeline_config_assembler_model_fields.py` (unreachable)
- pipeline_config_refs.md:187: - docs\older\LEGACY_CANDIDATES.md:164: - `tests/controller/test_pipeline_config_assembler_negative_prompt.py` (unreachable)
- pipeline_config_refs.md:188: - docs\older\LEGACY_CANDIDATES.md:165: - `tests/controller/test_pipeline_config_assembler_output_settings.py` (unreachable)
- pipeline_config_refs.md:189: - docs\older\LEGACY_CANDIDATES.md:166: - `tests/controller/test_pipeline_config_assembler_resolution.py` (unreachable)
- pipeline_config_refs.md:192: - docs\older\Make the pipeline work stream of consciousness.md:1186: cfg = getattr(job, "pipeline_config", None)
- pipeline_config_refs.md:193: - docs\older\Make the pipeline work stream of consciousness.md:1410: from src.controller.pipeline_config_assembler import PipelineConfigAssembler, GuiOverrides, RunPlan, PlannedJob
- pipeline_config_refs.md:194: - docs\older\Make the pipeline work stream of consciousness.md:1459: pipeline_config=config,
- pipeline_config_refs.md:195: - docs\older\Make the pipeline work stream of consciousness.md:1546: def _build_pipeline_config_from_state(self) -> PipelineConfig:
- pipeline_config_refs.md:196: - docs\older\Make the pipeline work stream of consciousness.md:1583: base_config = self._build_pipeline_config_from_state()
- pipeline_config_refs.md:197: - docs\older\Make the pipeline work stream of consciousness.md:1786: def build_pipeline_config_with_profiles(
- pipeline_config_refs.md:198: - docs\older\Make the pipeline work stream of consciousness.md:2014: config = self._build_pipeline_config_from_state()
- pipeline_config_refs.md:199: - docs\older\Make the pipeline work stream of consciousness.md:2174: pipeline_config=config,
- pipeline_config_refs.md:200: - docs\older\Make the pipeline work stream of consciousness.md:2186: if not job.pipeline_config:
- pipeline_config_refs.md:201: - docs\older\Make the pipeline work stream of consciousness.md:2191: result = runner.run(job.pipeline_config, self.cancel_token)
- pipeline_config_refs.md:202: - docs\older\Make the pipeline work stream of consciousness.md:2389: 'pipeline_config_panel_v2.py',
- pipeline_config_refs.md:203: - docs\older\Make the pipeline work stream of consciousness.md:3273: panel = getattr(self.main_window, "pipeline_config_panel_v2", None)
- pipeline_config_refs.md:204: - docs\older\Make the pipeline work stream of consciousness.md:3312: pipeline_config=None,
- pipeline_config_refs.md:205: - docs\older\Make the pipeline work stream of consciousness.md:3389: pipeline_config_panel = getattr(self.main_window, "pipeline_config_panel_v2", None)
- pipeline_config_refs.md:206: - docs\older\Make the pipeline work stream of consciousness.md:3390: if pipeline_config_panel and hasattr(pipeline_config_panel, "apply_run_config"):
- pipeline_config_refs.md:207: - docs\older\Make the pipeline work stream of consciousness.md:3392: pipeline_config_panel.apply_run_config(pack_config)
- pipeline_config_refs.md:208: - docs\older\Make the pipeline work stream of consciousness.md:3783: panel = getattr(self.main_window, "pipeline_config_panel_v2", None)
- pipeline_config_refs.md:209: - docs\older\Make the pipeline work stream of consciousness.md:3822: pipeline_config=None,
- pipeline_config_refs.md:210: - docs\older\Make the pipeline work stream of consciousness.md:3899: pipeline_config_panel = getattr(self.main_window, "pipeline_config_panel_v2", None)
- pipeline_config_refs.md:211: - docs\older\Make the pipeline work stream of consciousness.md:3900: if pipeline_config_panel and hasattr(pipeline_config_panel, "apply_run_config"):
- pipeline_config_refs.md:212: - docs\older\Make the pipeline work stream of consciousness.md:3902: pipeline_config_panel.apply_run_config(pack_config)
- pipeline_config_refs.md:213: - docs\older\Make the pipeline work stream of consciousness.md:4432: pipeline_config=None,
- pipeline_config_refs.md:214: - docs\older\Make the pipeline work stream of consciousness.md:4530: pipeline_config_panel = getattr(self.main_window, "pipeline_config_panel_v2", None)
- pipeline_config_refs.md:215: - docs\older\Make the pipeline work stream of consciousness.md:4531: if pipeline_config_panel and hasattr(pipeline_config_panel, "apply_run_config"):
- pipeline_config_refs.md:216: - docs\older\Make the pipeline work stream of consciousness.md:4533: pipeline_config_panel.apply_run_config(pack_config)
- pipeline_config_refs.md:217: - docs\older\Make the pipeline work stream of consciousness.md:4596: pipeline_config=None,
- pipeline_config_refs.md:218: - docs\older\Make the pipeline work stream of consciousness.md:4782: result = runner.run(job.pipeline_config, self.cancel_token)
- pipeline_config_refs.md:219: - docs\older\Make the pipeline work stream of consciousness.md:4906: # Extract pipeline_config from record.config if it's the right type
- pipeline_config_refs.md:220: - docs\older\Make the pipeline work stream of consciousness.md:4907: pipeline_config = None
- pipeline_config_refs.md:221: - docs\older\Make the pipeline work stream of consciousness.md:4909: pipeline_config = record.config
- pipeline_config_refs.md:222: - docs\older\Make the pipeline work stream of consciousness.md:4913: pipeline_config = record.config
- pipeline_config_refs.md:223: - docs\older\Make the pipeline work stream of consciousness.md:4925: pipeline_config=pipeline_config,
- pipeline_config_refs.md:224: - docs\older\Make the pipeline work stream of consciousness.md:4977: if not job.pipeline_config:
- pipeline_config_refs.md:225: - docs\older\Make the pipeline work stream of consciousness.md:4982: result = runner.run(job.pipeline_config, self.cancel_token)
- pipeline_config_refs.md:226: - docs\older\Make the pipeline work stream of consciousness.md:5436: mw.pipeline_config_panel_v2 = getattr(getattr(mw.pipeline_tab, "sidebar", None), "pipeline_config_panel", None)
- pipeline_config_refs.md:227: - docs\older\Make the pipeline work stream of consciousness.md:5664: base_config = self._build_pipeline_config_from_state()
- pipeline_config_refs.md:228: - docs\older\Make the pipeline work stream of consciousness.md:6130: job = Job(job_id=job_id, pipeline_config=None, priority=priority, payload=pipeline_callable, worker_id=worker_id)
- pipeline_config_refs.md:229: - docs\older\Make the pipeline work stream of consciousness.md:7074: 301:         # Extract pipeline_config from record.config if it's the right type
- pipeline_config_refs.md:230: - docs\older\Make the pipeline work stream of consciousness.md:7075: 302:         pipeline_config = None
- pipeline_config_refs.md:231: - docs\older\Make the pipeline work stream of consciousness.md:7077: 304:             pipeline_config = record.config
- pipeline_config_refs.md:232: - docs\older\Make the pipeline work stream of consciousness.md:7081: 308:                 pipeline_config = record.config
- pipeline_config_refs.md:233: - docs\older\Make the pipeline work stream of consciousness.md:7090: 317:             pipeline_config=pipeline_config,
- pipeline_config_refs.md:234: - docs\older\Make the pipeline work stream of consciousness.md:7202: def build_pipeline_config_with_profiles(
- pipeline_config_refs.md:237: - docs\older\PIPELINE_CONFIG_LOGGING_PRESETS_ADetailer_DISCOVERY_V2-P1.md:19: - **File**: `src/gui/views/pipeline_config_panel_v2.py`
- pipeline_config_refs.md:240: - docs\older\Revised-PR-204-2-MasterPlan_v2.5.md:75: NormalizedJobRecord (or JobSpecV2) carries pipeline_config: PipelineConfig, plus metadata (variant/batch, output paths, etc.).
- pipeline_config_refs.md:241: - docs\older\Revised-PR-204-2-MasterPlan_v2.5.md:194: pipeline_config: PipelineConfig
- pipeline_config_refs.md:242: - docs\older\Revised-PR-204-2-MasterPlan_v2.5.md:432: pipeline_config: PipelineConfig  # fully merged & randomizer/batch aware
- pipeline_config_refs.md:243: - docs\older\Revised-PR-204-2-MasterPlan_v2.5.md:515: base_pipeline_config: PipelineConfig (from PipelineConfigAssembler.build_from_gui_input(...)).
- pipeline_config_refs.md:244: - docs\older\Revised-PR-204-2-MasterPlan_v2.5.md:573: pipeline_config=cfg,
- pipeline_config_refs.md:245: - docs\older\Revised-PR-204-2-MasterPlan_v2.5.md:646: Positive prompt / negative prompt (from pipeline_config).
- pipeline_config_refs.md:246: - docs\older\Revised-PR-204-2-MasterPlan_v2.5.md:714: Submitting JobSpecV2 through JobService leads to correct _run_pipeline_job(pipeline_config) call.
- pipeline_config_refs.md:249: - docs\older\Run Pipeline Path (V2) – Architecture Notes.md:34: pipeline_config
- pipeline_config_refs.md:250: - docs\older\Run Pipeline Path (V2) – Architecture Notes.md:263: pipeline_config
- pipeline_config_refs.md:253: - docs\older\StableNew_Coding_and_Testing_v2.5.md:144: - Functions: `snake_case`, descriptive (`merge_pipeline_config`, `build_jobs`, `to_ui_summary`).
- pipeline_config_refs.md:256: - docs\older\StableNew_V2_Inventory.md:50: - `.mypy_cache/3.11/src/gui/panels_v2/pipeline_config_panel_v2.data.json`
- pipeline_config_refs.md:257: - docs\older\StableNew_V2_Inventory.md:51: - `.mypy_cache/3.11/src/gui/panels_v2/pipeline_config_panel_v2.meta.json`
- pipeline_config_refs.md:258: - docs\older\StableNew_V2_Inventory.md:104: - `.mypy_cache/3.11/src/gui/views/pipeline_config_panel_v2.data.json`
- pipeline_config_refs.md:259: - docs\older\StableNew_V2_Inventory.md:105: - `.mypy_cache/3.11/src/gui/views/pipeline_config_panel_v2.meta.json`
- pipeline_config_refs.md:260: - docs\older\StableNew_V2_Inventory.md:170: - `.mypy_cache/3.11/tests/gui_v2/test_gui_v2_pipeline_config_roundtrip.data.json`
- pipeline_config_refs.md:261: - docs\older\StableNew_V2_Inventory.md:171: - `.mypy_cache/3.11/tests/gui_v2/test_gui_v2_pipeline_config_roundtrip.meta.json`
- pipeline_config_refs.md:262: - docs\older\StableNew_V2_Inventory.md:305: - `htmlcov/z_ac9e25382994b44b_pipeline_config_panel_v2_py.html`
- pipeline_config_refs.md:263: - docs\older\StableNew_V2_Inventory.md:328: - `src/controller/__pycache__/pipeline_config_assembler.cpython-310.pyc`
- pipeline_config_refs.md:264: - docs\older\StableNew_V2_Inventory.md:378: - `src/gui/panels_v2/__pycache__/pipeline_config_panel_v2.cpython-310.pyc`
- pipeline_config_refs.md:265: - docs\older\StableNew_V2_Inventory.md:385: - `src/gui/panels_v2/pipeline_config_panel_v2.py`
- pipeline_config_refs.md:266: - docs\older\StableNew_V2_Inventory.md:417: - `src/gui/views/.mypy_cache/3.11/src/gui/views/pipeline_config_panel_v2.data.json`
- pipeline_config_refs.md:267: - docs\older\StableNew_V2_Inventory.md:418: - `src/gui/views/.mypy_cache/3.11/src/gui/views/pipeline_config_panel_v2.meta.json`
- pipeline_config_refs.md:268: - docs\older\StableNew_V2_Inventory.md:426: - `src/gui/views/__pycache__/pipeline_config_panel_v2.cpython-310.pyc`
- pipeline_config_refs.md:269: - docs\older\StableNew_V2_Inventory.md:510: - `tests/gui_v2/__pycache__/test_gui_v2_pipeline_config_roundtrip.cpython-310-pytest-9.0.1.pyc`
- pipeline_config_refs.md:270: - docs\older\StableNew_V2_Inventory.md:537: - `tests/gui_v2/__pycache__/test_pipeline_config_panel_lora_runtime.cpython-310-pytest-9.0.1.pyc`
- pipeline_config_refs.md:271: - docs\older\StableNew_V2_Inventory.md:579: - `tests/gui_v2/test_pipeline_config_panel_lora_runtime.py`
- pipeline_config_refs.md:272: - docs\older\StableNew_V2_Inventory.md:1198: - `tests/controller/__pycache__/test_pipeline_config_assembler.cpython-310-pytest-9.0.1.pyc`
- pipeline_config_refs.md:273: - docs\older\StableNew_V2_Inventory.md:1199: - `tests/controller/__pycache__/test_pipeline_config_assembler_core_fields.cpython-310-pytest-9.0.1.pyc`
- pipeline_config_refs.md:274: - docs\older\StableNew_V2_Inventory.md:1200: - `tests/controller/__pycache__/test_pipeline_config_assembler_model_fields.cpython-310-pytest-9.0.1.pyc`
- pipeline_config_refs.md:275: - docs\older\StableNew_V2_Inventory.md:1201: - `tests/controller/__pycache__/test_pipeline_config_assembler_negative_prompt.cpython-310-pytest-9.0.1.pyc`
- pipeline_config_refs.md:276: - docs\older\StableNew_V2_Inventory.md:1202: - `tests/controller/__pycache__/test_pipeline_config_assembler_output_settings.cpython-310-pytest-9.0.1.pyc`
- pipeline_config_refs.md:277: - docs\older\StableNew_V2_Inventory.md:1203: - `tests/controller/__pycache__/test_pipeline_config_assembler_resolution.cpython-310-pytest-9.0.1.pyc`
- pipeline_config_refs.md:278: - docs\older\StableNew_V2_Inventory.md:1320: - `src/controller/pipeline_config_assembler.py`
- pipeline_config_refs.md:279: - docs\older\StableNew_V2_Inventory.md:1885: - `src/gui/views/__pycache__/pipeline_config_panel.cpython-310.pyc`
- pipeline_config_refs.md:280: - docs\older\StableNew_V2_Inventory.md:1894: - `src/gui/views/pipeline_config_panel.py`
- pipeline_config_refs.md:281: - docs\older\StableNew_V2_Inventory.md:1958: - `tests/controller/test_pipeline_config_assembler.py`
- pipeline_config_refs.md:282: - docs\older\StableNew_V2_Inventory.md:1959: - `tests/controller/test_pipeline_config_assembler_core_fields.py`
- pipeline_config_refs.md:283: - docs\older\StableNew_V2_Inventory.md:1960: - `tests/controller/test_pipeline_config_assembler_model_fields.py`
- pipeline_config_refs.md:284: - docs\older\StableNew_V2_Inventory.md:1961: - `tests/controller/test_pipeline_config_assembler_negative_prompt.py`
- pipeline_config_refs.md:285: - docs\older\StableNew_V2_Inventory.md:1962: - `tests/controller/test_pipeline_config_assembler_output_settings.py`
- pipeline_config_refs.md:286: - docs\older\StableNew_V2_Inventory.md:1963: - `tests/controller/test_pipeline_config_assembler_resolution.py`
- pipeline_config_refs.md:287: - docs\older\StableNew_V2_Inventory.md:3012: - `.mypy_cache/3.11/src/controller/pipeline_config_assembler.data.json`
- pipeline_config_refs.md:288: - docs\older\StableNew_V2_Inventory.md:3013: - `.mypy_cache/3.11/src/controller/pipeline_config_assembler.meta.json`
- pipeline_config_refs.md:289: - docs\older\StableNew_V2_Inventory.md:3244: - `.mypy_cache/3.11/tests/controller/test_pipeline_config_assembler.data.json`
- pipeline_config_refs.md:290: - docs\older\StableNew_V2_Inventory.md:3245: - `.mypy_cache/3.11/tests/controller/test_pipeline_config_assembler.meta.json`
- pipeline_config_refs.md:291: - docs\older\StableNew_V2_Inventory.md:6925: - `htmlcov/z_7da4a89bed7a4ad5_pipeline_config_panel_py.html`
- pipeline_config_refs.md:292: - docs\older\StableNew_V2_Inventory.md:6945: - `htmlcov/z_ac5b274346abdaff_pipeline_config_assembler_py.html`
- pipeline_config_refs.md:295: - docs\older\StableNew_V2_Inventory_V2-P1.md:107: - `src/controller/pipeline_config_assembler.py`
- pipeline_config_refs.md:296: - docs\older\StableNew_V2_Inventory_V2-P1.md:146: - `src/gui/views/pipeline_config_panel.py`
- pipeline_config_refs.md:297: - docs\older\StableNew_V2_Inventory_V2-P1.md:220: - `tests/gui_v2/test_gui_v2_pipeline_config_roundtrip.py`
- pipeline_config_refs.md:298: - docs\older\StableNew_V2_Inventory_V2-P1.md:341: - `tests/controller/test_pipeline_config_assembler.py`
- pipeline_config_refs.md:299: - docs\older\StableNew_V2_Inventory_V2-P1.md:342: - `tests/controller/test_pipeline_config_assembler_core_fields.py`
- pipeline_config_refs.md:300: - docs\older\StableNew_V2_Inventory_V2-P1.md:343: - `tests/controller/test_pipeline_config_assembler_model_fields.py`
- pipeline_config_refs.md:301: - docs\older\StableNew_V2_Inventory_V2-P1.md:344: - `tests/controller/test_pipeline_config_assembler_negative_prompt.py`
- pipeline_config_refs.md:302: - docs\older\StableNew_V2_Inventory_V2-P1.md:345: - `tests/controller/test_pipeline_config_assembler_output_settings.py`
- pipeline_config_refs.md:303: - docs\older\StableNew_V2_Inventory_V2-P1.md:346: - `tests/controller/test_pipeline_config_assembler_resolution.py`
- pipeline_config_refs.md:306: - docs\older\WIRING_V2_5_ReachableFromMain_2025-11-26.md:126: | `src/pipeline/pipeline_config_v2.py` |  |  |  |  |  |
- pipeline_config_refs.md:309: - docs\older\repo_inventory_classified_v2_phase1.json:25: "src/controller/pipeline_config_assembler.py": "shared_core",
- pipeline_config_refs.md:310: - docs\older\repo_inventory_classified_v2_phase1.json:98: "src/gui/views/pipeline_config_panel.py": "shared_core",
- pipeline_config_refs.md:311: - docs\older\repo_inventory_classified_v2_phase1.json:183: "tests/controller/test_pipeline_config_assembler.py": "neutral_test",
- pipeline_config_refs.md:312: - docs\older\repo_inventory_classified_v2_phase1.json:184: "tests/controller/test_pipeline_config_assembler_core_fields.py": "neutral_test",
- pipeline_config_refs.md:313: - docs\older\repo_inventory_classified_v2_phase1.json:185: "tests/controller/test_pipeline_config_assembler_model_fields.py": "neutral_test",
- pipeline_config_refs.md:314: - docs\older\repo_inventory_classified_v2_phase1.json:186: "tests/controller/test_pipeline_config_assembler_negative_prompt.py": "neutral_test",
- pipeline_config_refs.md:315: - docs\older\repo_inventory_classified_v2_phase1.json:187: "tests/controller/test_pipeline_config_assembler_output_settings.py": "neutral_test",
- pipeline_config_refs.md:316: - docs\older\repo_inventory_classified_v2_phase1.json:188: "tests/controller/test_pipeline_config_assembler_resolution.py": "neutral_test",
- pipeline_config_refs.md:317: - docs\older\repo_inventory_classified_v2_phase1.json:211: "tests/gui_v2/test_gui_v2_pipeline_config_roundtrip.py": "v2_canonical_test",
- pipeline_config_refs.md:320: - docs\pr_templates\PR Doc Resources\PR-114-StreamOfThought.md:114: from src.controller.pipeline_config_assembler import PipelineConfigAssembler, GuiOverrides, RunPlan, PlannedJob
- pipeline_config_refs.md:321: - docs\pr_templates\PR Doc Resources\PR-114-StreamOfThought.md:160: pipeline_config=config,
- pipeline_config_refs.md:322: - docs\pr_templates\PR Doc Resources\PR-114-StreamOfThought.md:241: def _build_pipeline_config_from_state(self) -> PipelineConfig:
- pipeline_config_refs.md:323: - docs\pr_templates\PR Doc Resources\PR-114-StreamOfThought.md:255: def build_pipeline_config_with_profiles(
- pipeline_config_refs.md:324: - docs\pr_templates\PR Doc Resources\PR-114-StreamOfThought.md:380: from src.controller.pipeline_config_assembler import PipelineConfigAssembler, GuiOverrides, RunPlan, PlannedJob
- pipeline_config_refs.md:325: - docs\pr_templates\PR Doc Resources\PR-114-StreamOfThought.md:426: pipeline_config=config,
- pipeline_config_refs.md:326: - docs\pr_templates\PR Doc Resources\PR-114-StreamOfThought.md:507: def _build_pipeline_config_from_state(self) -> PipelineConfig:
- pipeline_config_refs.md:327: - docs\pr_templates\PR Doc Resources\PR-114-StreamOfThought.md:521: def build_pipeline_config_with_profiles(
- pipeline_config_refs.md:328: - docs\pr_templates\PR Doc Resources\PR-114-StreamOfThought.md:743: config = self._build_pipeline_config_from_state()
- pipeline_config_refs.md:329: - docs\pr_templates\PR Doc Resources\PR-114-StreamOfThought.md:790: from src.controller.pipeline_config_assembler import PipelineConfigAssem
- pipeline_config_refs.md:330: - docs\pr_templates\PR Doc Resources\PR-114-StreamOfThought.md:835: config = self._build_pipeline_config_from_state()
- pipeline_config_refs.md:331: - docs\pr_templates\PR Doc Resources\PR-114-StreamOfThought.md:977: job = Job(job_id=job_id, pipeline_config=None, priority=priority, payload=pipeline_callable, worker_id=worker_id)
- pipeline_config_refs.md:332: - docs\pr_templates\PR Doc Resources\PR-114-StreamOfThought.md:1409: job = Job(job_id=job_id, pipeline_config=None, priority=priority, payload=pipeline_callable, worker_id=worker_id)
- pipeline_config_refs.md:333: - docs\pr_templates\PR Doc Resources\PR-114-StreamOfThought.md:1625: from src.controller.pipeline_config_assembler import PipelineConfigAssembler, GuiOverrides, RunPlan, PlannedJob
- pipeline_config_refs.md:334: - docs\pr_templates\PR Doc Resources\PR-114-StreamOfThought.md:1699: pipeline_config=config,
- pipeline_config_refs.md:335: - docs\pr_templates\PR Doc Resources\PR-114-StreamOfThought.md:1739: pipeline_config=config,
- pipeline_config_refs.md:336: - docs\pr_templates\PR Doc Resources\PR-114-StreamOfThought.md:2011: job = Job(job_id=job_id, pipeline_config=None, priority=priority, payload=pipeline_callable, worker_id=worker_id)
- pipeline_config_refs.md:337: - docs\pr_templates\PR Doc Resources\PR-114-StreamOfThought.md:2437: The PipelineRunner.run expects a PipelineConfig dataclass, which is presumably returned by pipeline_controller._build_pipeline_config_from_state—great, that part works. But _run_pipeline_job isn’t using run yet. I need to bridge that gap and integrate the learning hooks (_learning_enabled, _get_learning_runner). I'll also check tests for any existing connections.
- pipeline_config_refs.md:340: - docs\pr_templates\PriorWork_complete\CLEANUP-GUI-TEST-QUARANTINE-002_V2-P1.md:82: - `tests/gui_v2/test_gui_v2_pipeline_config_roundtrip.py`
- pipeline_config_refs.md:343: - docs\pr_templates\PriorWork_complete\Codex_Run_Sheet_PR-GUI-V2-MIGRATION-003.md:12: - tests/gui_v2/test_gui_v2_pipeline_config_roundtrip.py
- pipeline_config_refs.md:344: - docs\pr_templates\PriorWork_complete\Codex_Run_Sheet_PR-GUI-V2-MIGRATION-003.md:103: 1) tests/gui_v2/test_gui_v2_pipeline_config_roundtrip.py (new)
- pipeline_config_refs.md:347: - docs\pr_templates\PriorWork_complete\Dark-Mode-GlobalNeg-11-26-25.md:326: pipeline_config["global_negative"] = self.get_global_negative_config()
- pipeline_config_refs.md:348: - docs\pr_templates\PriorWork_complete\Dark-Mode-GlobalNeg-11-26-25.md:335: global_neg = pipeline_config.get("global_negative", {})
- pipeline_config_refs.md:351: - docs\pr_templates\PriorWork_complete\Execution Script for PR-#53 – Advanced Resolution Controls.md:40: src/controller/pipeline_config_assembler.py
- pipeline_config_refs.md:352: - docs\pr_templates\PriorWork_complete\Execution Script for PR-#53 – Advanced Resolution Controls.md:48: tests/controller/test_pipeline_config_assembler_resolution.py (new or extend)
- pipeline_config_refs.md:353: - docs\pr_templates\PriorWork_complete\Execution Script for PR-#53 – Advanced Resolution Controls.md:110: In pipeline_config_assembler.py:
- pipeline_config_refs.md:354: - docs\pr_templates\PriorWork_complete\Execution Script for PR-#53 – Advanced Resolution Controls.md:130: pytest tests/controller/test_pipeline_config_assembler_resolution.py -v
- pipeline_config_refs.md:355: - docs\pr_templates\PriorWork_complete\Execution Script for PR-#53 – Advanced Resolution Controls.md:156: pytest tests/controller/test_pipeline_config_assembler_resolution.py -v
- pipeline_config_refs.md:358: - docs\pr_templates\PriorWork_complete\PR-#38-PIPELINE-V2-GUIConfigToPipelineConfig-001.md:29: - `src/pipeline/pipeline_config.py` (or equivalent)
- pipeline_config_refs.md:359: - docs\pr_templates\PriorWork_complete\PR-#38-PIPELINE-V2-GUIConfigToPipelineConfig-001.md:43: - `src/controller/pipeline_config_assembler.py` **(new)** (name flexible, but must live in controller layer)
- pipeline_config_refs.md:360: - docs\pr_templates\PriorWork_complete\PR-#38-PIPELINE-V2-GUIConfigToPipelineConfig-001.md:45: - `build_pipeline_config(base_config, gui_overrides, randomizer_overlay, learning_enabled) -> PipelineConfig`
- pipeline_config_refs.md:361: - docs\pr_templates\PriorWork_complete\PR-#38-PIPELINE-V2-GUIConfigToPipelineConfig-001.md:65: - `config = self.config_assembler.build_pipeline_config(...)`
- pipeline_config_refs.md:362: - docs\pr_templates\PriorWork_complete\PR-#38-PIPELINE-V2-GUIConfigToPipelineConfig-001.md:85: - `tests/controller/test_pipeline_config_assembler.py` **(new)**
- pipeline_config_refs.md:363: - docs\pr_templates\PriorWork_complete\PR-#38-PIPELINE-V2-GUIConfigToPipelineConfig-001.md:105: - `tests/pipeline/test_pipeline_config_invariants.py` **(new or extended)**
- pipeline_config_refs.md:364: - docs\pr_templates\PriorWork_complete\PR-#38-PIPELINE-V2-GUIConfigToPipelineConfig-001.md:185: - `pytest tests/controller/test_pipeline_config_assembler.py -v`
- pipeline_config_refs.md:365: - docs\pr_templates\PriorWork_complete\PR-#38-PIPELINE-V2-GUIConfigToPipelineConfig-001.md:191: - `pytest tests/pipeline/test_pipeline_config_invariants.py -v`
- pipeline_config_refs.md:368: - docs\pr_templates\PriorWork_complete\PR-#46-PIPELINE-V2-PipelineConfigAssemblerEnforcement-001.md:35: - `src/pipeline/pipeline_config_assembler.py`
- pipeline_config_refs.md:369: - docs\pr_templates\PriorWork_complete\PR-#46-PIPELINE-V2-PipelineConfigAssemblerEnforcement-001.md:182: - `tests/controller/test_pipeline_config_assembler.py -v`
- pipeline_config_refs.md:370: - docs\pr_templates\PriorWork_complete\PR-#46-PIPELINE-V2-PipelineConfigAssemblerEnforcement-001.md:206: - `tests/pipeline/test_pipeline_config_invariants.py -v` (new or extended)
- pipeline_config_refs.md:373: - docs\pr_templates\PriorWork_complete\PR-#47-PIPELINE-V2-AssemblerEnforcement-Finish-001.md:78: - `test_pipeline_config_assembler.py`
- pipeline_config_refs.md:374: - docs\pr_templates\PriorWork_complete\PR-#47-PIPELINE-V2-AssemblerEnforcement-Finish-001.md:80: - `test_pipeline_config_invariants.py`
- pipeline_config_refs.md:375: - docs\pr_templates\PriorWork_complete\PR-#47-PIPELINE-V2-AssemblerEnforcement-Finish-001.md:104: - `src/controller/pipeline_config_assembler.py` (small adjustments only; no redesign)
- pipeline_config_refs.md:376: - docs\pr_templates\PriorWork_complete\PR-#47-PIPELINE-V2-AssemblerEnforcement-Finish-001.md:117: - `tests/controller/test_pipeline_config_assembler.py`
- pipeline_config_refs.md:377: - docs\pr_templates\PriorWork_complete\PR-#47-PIPELINE-V2-AssemblerEnforcement-Finish-001.md:119: - `tests/pipeline/test_pipeline_config_invariants.py`
- pipeline_config_refs.md:378: - docs\pr_templates\PriorWork_complete\PR-#47-PIPELINE-V2-AssemblerEnforcement-Finish-001.md:145: **File:** `src/controller/pipeline_config_assembler.py`
- pipeline_config_refs.md:379: - docs\pr_templates\PriorWork_complete\PR-#47-PIPELINE-V2-AssemblerEnforcement-Finish-001.md:173: - `def _build_pipeline_config_from_state(self) -> PipelineConfig:`
- pipeline_config_refs.md:380: - docs\pr_templates\PriorWork_complete\PR-#47-PIPELINE-V2-AssemblerEnforcement-Finish-001.md:180: - Build a `PipelineConfig` via `_build_pipeline_config_from_state()`.
- pipeline_config_refs.md:381: - docs\pr_templates\PriorWork_complete\PR-#47-PIPELINE-V2-AssemblerEnforcement-Finish-001.md:229: - Passes that structure to the controller via a clear call (for example, `controller.request_run_with_overrides(overrides)` or by setting state that `_build_pipeline_config_from_state()` reads).
- pipeline_config_refs.md:382: - docs\pr_templates\PriorWork_complete\PR-#47-PIPELINE-V2-AssemblerEnforcement-Finish-001.md:268: - `pytest tests/controller/test_pipeline_config_assembler.py -v`
- pipeline_config_refs.md:383: - docs\pr_templates\PriorWork_complete\PR-#47-PIPELINE-V2-AssemblerEnforcement-Finish-001.md:284: - `pytest tests/pipeline/test_pipeline_config_invariants.py -v`
- pipeline_config_refs.md:384: - docs\pr_templates\PriorWork_complete\PR-#47-PIPELINE-V2-AssemblerEnforcement-Finish-001.md:318: - `tests/pipeline/test_pipeline_config_invariants.py` is green.
- pipeline_config_refs.md:385: - docs\pr_templates\PriorWork_complete\PR-#47-PIPELINE-V2-AssemblerEnforcement-Finish-001.md:337: - `src/controller/pipeline_config_assembler.py` (only the deltas introduced by this PR)
- pipeline_config_refs.md:388: - docs\pr_templates\PriorWork_complete\PR-#47B-PIPELINE-V2-AssemblerEnforcement-Hotfix-001.md:51: - start_pipeline calls into a dedicated _build_pipeline_config_from_state (or equivalent) that wraps build_from_gui_input.
- pipeline_config_refs.md:389: - docs\pr_templates\PriorWork_complete\PR-#47B-PIPELINE-V2-AssemblerEnforcement-Hotfix-001.md:100: - src/controller/pipeline_config_assembler.py
- pipeline_config_refs.md:390: - docs\pr_templates\PriorWork_complete\PR-#47B-PIPELINE-V2-AssemblerEnforcement-Hotfix-001.md:104: - tests/controller/test_pipeline_config_assembler.py
- pipeline_config_refs.md:391: - docs\pr_templates\PriorWork_complete\PR-#47B-PIPELINE-V2-AssemblerEnforcement-Hotfix-001.md:156: - _build_pipeline_config_from_state(self) -> PipelineConfig:
- pipeline_config_refs.md:392: - docs\pr_templates\PriorWork_complete\PR-#47B-PIPELINE-V2-AssemblerEnforcement-Hotfix-001.md:177: - Build a PipelineConfig using _build_pipeline_config_from_state.
- pipeline_config_refs.md:393: - docs\pr_templates\PriorWork_complete\PR-#47B-PIPELINE-V2-AssemblerEnforcement-Hotfix-001.md:222: - pytest tests/controller/test_pipeline_config_assembler.py -v
- pipeline_config_refs.md:394: - docs\pr_templates\PriorWork_complete\PR-#47B-PIPELINE-V2-AssemblerEnforcement-Hotfix-001.md:245: If any test outside the target ones fails, analyze the failure and apply the minimal fix within src/controller/pipeline_controller.py or, if absolutely necessary, src/controller/pipeline_config_assembler.py.
- pipeline_config_refs.md:395: - docs\pr_templates\PriorWork_complete\PR-#47B-PIPELINE-V2-AssemblerEnforcement-Hotfix-001.md:280: - src/controller/pipeline_config_assembler.py (if touched)
- pipeline_config_refs.md:398: - docs\pr_templates\PriorWork_complete\PR-#50-GUI-V2-PromptPackManager-Integration-001.md:56: - `src/controller/pipeline_config_assembler.py`
- pipeline_config_refs.md:401: - docs\pr_templates\PriorWork_complete\PR-#51-GUI-V2-CoreConfigPanel-001.md:127: - `src/controller/pipeline_config_assembler.py` *(ensure assembler accepts core config overrides and maps into `PipelineConfig`)*
- pipeline_config_refs.md:402: - docs\pr_templates\PriorWork_complete\PR-#51-GUI-V2-CoreConfigPanel-001.md:133: - `tests/controller/test_pipeline_config_assembler_core_fields.py` *(new or extend existing assembler tests)*
- pipeline_config_refs.md:403: - docs\pr_templates\PriorWork_complete\PR-#51-GUI-V2-CoreConfigPanel-001.md:239: In `src/controller/pipeline_config_assembler.py`:
- pipeline_config_refs.md:404: - docs\pr_templates\PriorWork_complete\PR-#51-GUI-V2-CoreConfigPanel-001.md:269: 2. **Assembler test**: `tests/controller/test_pipeline_config_assembler_core_fields.py`
- pipeline_config_refs.md:405: - docs\pr_templates\PriorWork_complete\PR-#51-GUI-V2-CoreConfigPanel-001.md:271: - `test_assembler_maps_core_fields_to_pipeline_config`:
- pipeline_config_refs.md:406: - docs\pr_templates\PriorWork_complete\PR-#51-GUI-V2-CoreConfigPanel-001.md:296: - `pytest tests/controller/test_pipeline_config_assembler_core_fields.py -v`
- pipeline_config_refs.md:407: - docs\pr_templates\PriorWork_complete\PR-#51-GUI-V2-CoreConfigPanel-001.md:335: - `src/controller/pipeline_config_assembler.py`
- pipeline_config_refs.md:408: - docs\pr_templates\PriorWork_complete\PR-#51-GUI-V2-CoreConfigPanel-001.md:367: - `pytest tests/controller/test_pipeline_config_assembler_core_fields.py -v`
- pipeline_config_refs.md:411: - docs\pr_templates\PriorWork_complete\PR-#52-GUI-V2-NegativePromptPanel-001.md:114: - `src/controller/pipeline_config_assembler.py` *(map negative_prompt into `PipelineConfig`)*
- pipeline_config_refs.md:412: - docs\pr_templates\PriorWork_complete\PR-#52-GUI-V2-NegativePromptPanel-001.md:123: - `tests/controller/test_pipeline_config_assembler_negative_prompt.py` *(new)*
- pipeline_config_refs.md:413: - docs\pr_templates\PriorWork_complete\PR-#52-GUI-V2-NegativePromptPanel-001.md:192: In `src/controller/pipeline_config_assembler.py`:
- pipeline_config_refs.md:414: - docs\pr_templates\PriorWork_complete\PR-#52-GUI-V2-NegativePromptPanel-001.md:213: 2. `tests/controller/test_pipeline_config_assembler_negative_prompt.py`:
- pipeline_config_refs.md:415: - docs\pr_templates\PriorWork_complete\PR-#52-GUI-V2-NegativePromptPanel-001.md:229: - `pytest tests/controller/test_pipeline_config_assembler_negative_prompt.py -v`
- pipeline_config_refs.md:416: - docs\pr_templates\PriorWork_complete\PR-#52-GUI-V2-NegativePromptPanel-001.md:295: - `pytest tests/controller/test_pipeline_config_assembler_negative_prompt.py -v`
- pipeline_config_refs.md:419: - docs\pr_templates\PriorWork_complete\PR-#53-GUI-V2-ResolutionAdvancedControls-001.md:120: - `src/controller/pipeline_config_assembler.py` *(interpret overrides into width/height and apply clamps)*
- pipeline_config_refs.md:420: - docs\pr_templates\PriorWork_complete\PR-#53-GUI-V2-ResolutionAdvancedControls-001.md:129: - `tests/controller/test_pipeline_config_assembler_resolution.py` *(new or extended)*
- pipeline_config_refs.md:421: - docs\pr_templates\PriorWork_complete\PR-#53-GUI-V2-ResolutionAdvancedControls-001.md:197: In `src/controller/pipeline_config_assembler.py`:
- pipeline_config_refs.md:422: - docs\pr_templates\PriorWork_complete\PR-#53-GUI-V2-ResolutionAdvancedControls-001.md:223: 2. `tests/controller/test_pipeline_config_assembler_resolution.py`:
- pipeline_config_refs.md:423: - docs\pr_templates\PriorWork_complete\PR-#53-GUI-V2-ResolutionAdvancedControls-001.md:239: - `pytest tests/controller/test_pipeline_config_assembler_resolution.py -v`
- pipeline_config_refs.md:424: - docs\pr_templates\PriorWork_complete\PR-#53-GUI-V2-ResolutionAdvancedControls-001.md:304: - `pytest tests/controller/test_pipeline_config_assembler_resolution.py -v`
- pipeline_config_refs.md:427: - docs\pr_templates\PriorWork_complete\PR-#54-GUI-V2-OutputSettingsPanel-001.md:115: - `src/controller/pipeline_config_assembler.py` *(map output overrides into `PipelineConfig`)*
- pipeline_config_refs.md:428: - docs\pr_templates\PriorWork_complete\PR-#54-GUI-V2-OutputSettingsPanel-001.md:124: - `tests/controller/test_pipeline_config_assembler_output_settings.py` *(new)*
- pipeline_config_refs.md:429: - docs\pr_templates\PriorWork_complete\PR-#54-GUI-V2-OutputSettingsPanel-001.md:194: In `src/controller/pipeline_config_assembler.py`:
- pipeline_config_refs.md:430: - docs\pr_templates\PriorWork_complete\PR-#54-GUI-V2-OutputSettingsPanel-001.md:215: 2. `tests/controller/test_pipeline_config_assembler_output_settings.py`:
- pipeline_config_refs.md:431: - docs\pr_templates\PriorWork_complete\PR-#54-GUI-V2-OutputSettingsPanel-001.md:231: - `pytest tests/controller/test_pipeline_config_assembler_output_settings.py -v`
- pipeline_config_refs.md:432: - docs\pr_templates\PriorWork_complete\PR-#54-GUI-V2-OutputSettingsPanel-001.md:295: - `pytest tests/controller/test_pipeline_config_assembler_output_settings.py -v`
- pipeline_config_refs.md:435: - docs\pr_templates\PriorWork_complete\PR-#55-GUI-V2-ModelManagerPanel-001.md:110: - `src/controller/pipeline_config_assembler.py` *(map model/vae into `PipelineConfig`)*
- pipeline_config_refs.md:436: - docs\pr_templates\PriorWork_complete\PR-#55-GUI-V2-ModelManagerPanel-001.md:121: - `tests/controller/test_pipeline_config_assembler_model_fields.py` *(new or extended)*
- pipeline_config_refs.md:437: - docs\pr_templates\PriorWork_complete\PR-#55-GUI-V2-ModelManagerPanel-001.md:200: In `src/controller/pipeline_config_assembler.py`:
- pipeline_config_refs.md:438: - docs\pr_templates\PriorWork_complete\PR-#55-GUI-V2-ModelManagerPanel-001.md:220: 2. `tests/controller/test_pipeline_config_assembler_model_fields.py`:
- pipeline_config_refs.md:439: - docs\pr_templates\PriorWork_complete\PR-#55-GUI-V2-ModelManagerPanel-001.md:236: - `pytest tests/controller/test_pipeline_config_assembler_model_fields.py -v`
- pipeline_config_refs.md:440: - docs\pr_templates\PriorWork_complete\PR-#55-GUI-V2-ModelManagerPanel-001.md:301: - `pytest tests/controller/test_pipeline_config_assembler_model_fields.py -v`
- pipeline_config_refs.md:443: - docs\pr_templates\PriorWork_complete\PR-0114 — Pipeline Run Controls → Queue-Runner.md:100: config = job.pipeline_config
- pipeline_config_refs.md:444: - docs\pr_templates\PriorWork_complete\PR-0114 — Pipeline Run Controls → Queue-Runner.md:219: config = job.pipeline_config
- pipeline_config_refs.md:447: - docs\pr_templates\PriorWork_complete\PR-0114C – End-to-End Job Execution + Journey Tests.md:71: Invokes PipelineRunner via runner.run(job.pipeline_config, self.cancel_token) (for multi-stage path).
- pipeline_config_refs.md:450: - docs\pr_templates\PriorWork_complete\PR-016-PIPELINE-CONFIG-UX-RESTORE-V2-P1.md:24: - `src/gui/views/pipeline_config_panel_v2.py`
- pipeline_config_refs.md:451: - docs\pr_templates\PriorWork_complete\PR-016-PIPELINE-CONFIG-UX-RESTORE-V2-P1.md:51: ### 3.1 `pipeline_config_panel_v2.py` — Validation Surface
- pipeline_config_refs.md:452: - docs\pr_templates\PriorWork_complete\PR-016-PIPELINE-CONFIG-UX-RESTORE-V2-P1.md:79: def validate_pipeline_config(self) -> Tuple[bool, str]:
- pipeline_config_refs.md:453: - docs\pr_templates\PriorWork_complete\PR-016-PIPELINE-CONFIG-UX-RESTORE-V2-P1.md:92: is_valid, message = self.validate_pipeline_config()
- pipeline_config_refs.md:454: - docs\pr_templates\PriorWork_complete\PR-016-PIPELINE-CONFIG-UX-RESTORE-V2-P1.md:93: pipeline_panel = self._app_state.get("pipeline_config_panel_v2")
- pipeline_config_refs.md:455: - docs\pr_templates\PriorWork_complete\PR-016-PIPELINE-CONFIG-UX-RESTORE-V2-P1.md:107: - When `validate_pipeline_config` is called, update:
- pipeline_config_refs.md:456: - docs\pr_templates\PriorWork_complete\PR-016-PIPELINE-CONFIG-UX-RESTORE-V2-P1.md:136: panel = self._app_state.get("pipeline_config_panel_v2")
- pipeline_config_refs.md:457: - docs\pr_templates\PriorWork_complete\PR-016-PIPELINE-CONFIG-UX-RESTORE-V2-P1.md:152: - `tests/gui_v2/test_pipeline_config_validation_v2.py`:
- pipeline_config_refs.md:458: - docs\pr_templates\PriorWork_complete\PR-016-PIPELINE-CONFIG-UX-RESTORE-V2-P1.md:159: - `tests/controller/test_pipeline_config_validation_v2.py`:
- pipeline_config_refs.md:459: - docs\pr_templates\PriorWork_complete\PR-016-PIPELINE-CONFIG-UX-RESTORE-V2-P1.md:161: - Tests `validate_pipeline_config` logic independently (unit-level).
- pipeline_config_refs.md:462: - docs\pr_templates\PriorWork_complete\PR-024-MAIN-WEBUI-LAUNCH-UX-BROWSER-READY-V2-P1.md:114: src/gui/views/pipeline_config_panel_v2.py
- pipeline_config_refs.md:465: - docs\pr_templates\PriorWork_complete\PR-031-PIPELINE-CONFIG-LEFTCOLUMN-WIRING-V2-P1.md:114: src/gui/panels_v2/pipeline_config_panel_v2.py
- pipeline_config_refs.md:466: - docs\pr_templates\PriorWork_complete\PR-031-PIPELINE-CONFIG-LEFTCOLUMN-WIRING-V2-P1.md:215: Import PipelineConfigPanelV2 from src.gui.panels_v2.pipeline_config_panel_v2.
- pipeline_config_refs.md:467: - docs\pr_templates\PriorWork_complete\PR-031-PIPELINE-CONFIG-LEFTCOLUMN-WIRING-V2-P1.md:235: Ensure naming is consistent with existing patterns (e.g., self.pipeline_config_panel if that’s the convention).
- pipeline_config_refs.md:468: - docs\pr_templates\PriorWork_complete\PR-031-PIPELINE-CONFIG-LEFTCOLUMN-WIRING-V2-P1.md:239: In pipeline_config_panel_v2.py:
- pipeline_config_refs.md:469: - docs\pr_templates\PriorWork_complete\PR-031-PIPELINE-CONFIG-LEFTCOLUMN-WIRING-V2-P1.md:335: Add a small assertion that the pipeline tab exposes a handle to pipeline_config_panel or similar, if that’s how it’s exposed.
- pipeline_config_refs.md:470: - docs\pr_templates\PriorWork_complete\PR-031-PIPELINE-CONFIG-LEFTCOLUMN-WIRING-V2-P1.md:418: pipeline_config_panel_v2.py
- pipeline_config_refs.md:473: - docs\pr_templates\PriorWork_complete\PR-032-BOTTOM-LOGGING-SURFACE-V2-P1.md:189: src/gui/panels_v2/sidebar_panel_v2.py / pipeline_config_panel_v2.py (those are PR-031 domain)
- pipeline_config_refs.md:476: - docs\pr_templates\PriorWork_complete\PR-033-PIPELINE-PRESETS-HOOKUP-V2-P1.md:147: src/gui/panels_v2/pipeline_config_panel_v2.py
- pipeline_config_refs.md:477: - docs\pr_templates\PriorWork_complete\PR-033-PIPELINE-PRESETS-HOOKUP-V2-P1.md:332: File: src/gui/panels_v2/pipeline_config_panel_v2.py
- pipeline_config_refs.md:478: - docs\pr_templates\PriorWork_complete\PR-033-PIPELINE-PRESETS-HOOKUP-V2-P1.md:491: src/gui/panels_v2/pipeline_config_panel_v2.py
- pipeline_config_refs.md:481: - docs\pr_templates\PriorWork_complete\PR-033A-PIPELINE-LEFT-PANEL-UX-V2-P1.md:72: src/gui/views/pipeline_config_panel_v2.py (or current config panel implementation)
- pipeline_config_refs.md:482: - docs\pr_templates\PriorWork_complete\PR-033A-PIPELINE-LEFT-PANEL-UX-V2-P1.md:132: In pipeline_config_panel_v2.py, ensure:
- pipeline_config_refs.md:483: - docs\pr_templates\PriorWork_complete\PR-033A-PIPELINE-LEFT-PANEL-UX-V2-P1.md:206: pipeline_config_panel_v2.py
- pipeline_config_refs.md:486: - docs\pr_templates\PriorWork_complete\PR-034-PIPELINE-PRESETS-INTEGRATION-V2-P1.md:78: src/gui/views/pipeline_config_panel_v2.py (read/write config fields)
- pipeline_config_refs.md:487: - docs\pr_templates\PriorWork_complete\PR-034-PIPELINE-PRESETS-INTEGRATION-V2-P1.md:200: pipeline_config_panel_v2.py
- pipeline_config_refs.md:490: - docs\pr_templates\PriorWork_complete\PR-035-PIPELINE-PACK-CONFIG-JOB-BUILDER-V2-P1.md:176: src/gui/panels_v2/pipeline_config_panel_v2.py
- pipeline_config_refs.md:491: - docs\pr_templates\PriorWork_complete\PR-035-PIPELINE-PACK-CONFIG-JOB-BUILDER-V2-P1.md:420: pipeline_config_panel_v2.py
- pipeline_config_refs.md:494: - docs\pr_templates\PriorWork_complete\PR-036-PIPELINE-TAB-3COLUMN-LAYOUT-V2-P1.md:113: src/gui/panels_v2/pipeline_config_panel_v2.py
- pipeline_config_refs.md:495: - docs\pr_templates\PriorWork_complete\PR-036-PIPELINE-TAB-3COLUMN-LAYOUT-V2-P1.md:336: pipeline_config_panel_v2.py
- pipeline_config_refs.md:498: - docs\pr_templates\PriorWork_complete\PR-037-Pipeline-LoRA-Strengths-V2-P1.md:108: src/gui/panels_v2/pipeline_config_panel_v2.py
- pipeline_config_refs.md:499: - docs\pr_templates\PriorWork_complete\PR-037-Pipeline-LoRA-Strengths-V2-P1.md:167: In pipeline_config_panel_v2.py:
- pipeline_config_refs.md:500: - docs\pr_templates\PriorWork_complete\PR-037-Pipeline-LoRA-Strengths-V2-P1.md:199: Call pipeline_config_panel.load_lora_strengths() with these values.
- pipeline_config_refs.md:501: - docs\pr_templates\PriorWork_complete\PR-037-Pipeline-LoRA-Strengths-V2-P1.md:203: Read current LoRA strengths via pipeline_config_panel.get_lora_strengths().
- pipeline_config_refs.md:502: - docs\pr_templates\PriorWork_complete\PR-037-Pipeline-LoRA-Strengths-V2-P1.md:277: pipeline_config_panel_v2.py
- pipeline_config_refs.md:505: - docs\pr_templates\PriorWork_complete\PR-037A-Pipeline-LoRA-Strengths-V2-P1.md:110: src/gui/panels_v2/pipeline_config_panel_v2.py
- pipeline_config_refs.md:506: - docs\pr_templates\PriorWork_complete\PR-037A-Pipeline-LoRA-Strengths-V2-P1.md:169: In pipeline_config_panel_v2.py:
- pipeline_config_refs.md:507: - docs\pr_templates\PriorWork_complete\PR-037A-Pipeline-LoRA-Strengths-V2-P1.md:201: Call pipeline_config_panel.load_lora_strengths() with these values.
- pipeline_config_refs.md:508: - docs\pr_templates\PriorWork_complete\PR-037A-Pipeline-LoRA-Strengths-V2-P1.md:205: Read current LoRA strengths via pipeline_config_panel.get_lora_strengths().
- pipeline_config_refs.md:509: - docs\pr_templates\PriorWork_complete\PR-037A-Pipeline-LoRA-Strengths-V2-P1.md:279: pipeline_config_panel_v2.py
- pipeline_config_refs.md:512: - docs\pr_templates\PriorWork_complete\PR-038-Pipeline-Randomizer-Config-V2-P1.md:119: src/gui/panels_v2/pipeline_config_panel_v2.py
- pipeline_config_refs.md:513: - docs\pr_templates\PriorWork_complete\PR-038-Pipeline-Randomizer-Config-V2-P1.md:170: In pipeline_config_panel_v2.py:
- pipeline_config_refs.md:514: - docs\pr_templates\PriorWork_complete\PR-038-Pipeline-Randomizer-Config-V2-P1.md:202: Call pipeline_config_panel.load_randomizer_config(...).
- pipeline_config_refs.md:515: - docs\pr_templates\PriorWork_complete\PR-038-Pipeline-Randomizer-Config-V2-P1.md:274: pipeline_config_panel_v2.py
- pipeline_config_refs.md:518: - docs\pr_templates\PriorWork_complete\PR-038A-Pipeline-Randomizer-Config-V2-P1.md:119: src/gui/panels_v2/pipeline_config_panel_v2.py
- pipeline_config_refs.md:519: - docs\pr_templates\PriorWork_complete\PR-038A-Pipeline-Randomizer-Config-V2-P1.md:170: In pipeline_config_panel_v2.py:
- pipeline_config_refs.md:520: - docs\pr_templates\PriorWork_complete\PR-038A-Pipeline-Randomizer-Config-V2-P1.md:202: Call pipeline_config_panel.load_randomizer_config(...).
- pipeline_config_refs.md:521: - docs\pr_templates\PriorWork_complete\PR-038A-Pipeline-Randomizer-Config-V2-P1.md:274: pipeline_config_panel_v2.py
- pipeline_config_refs.md:524: - docs\pr_templates\PriorWork_complete\PR-041-DESIGN-SYSTEM-THEME-V2-P1.md:187: src/gui/panels_v2/pipeline_config_panel_v2.py
- pipeline_config_refs.md:527: - docs\pr_templates\PriorWork_complete\PR-041-THEME-V2-DESIGN-TOKENS-UNIFICATION-V2-P1.md:139: src/gui/panels_v2/pipeline_config_panel_v2.py
- pipeline_config_refs.md:530: - docs\pr_templates\PriorWork_complete\PR-049 — GUI V2 Dropdowns, Payload Builder, & Last-Run.md:100: Add method build_pipeline_config_v2():
- pipeline_config_refs.md:533: - docs\pr_templates\PriorWork_complete\PR-071-Pipeline-Execution-Wiring-V2-P1-20251201.md:120: def run_pipeline(self, pipeline_config, learning_context=None) -> PipelineResult:
- pipeline_config_refs.md:534: - docs\pr_templates\PriorWork_complete\PR-071-Pipeline-Execution-Wiring-V2-P1-20251201.md:122: - Validate pipeline_config
- pipeline_config_refs.md:535: - docs\pr_templates\PriorWork_complete\PR-071-Pipeline-Execution-Wiring-V2-P1-20251201.md:177: self.controller.run_pipeline(self.app_state.build_pipeline_config())
- pipeline_config_refs.md:538: - docs\pr_templates\PriorWork_complete\PR-072-RunPipeline-Facade-V2-P1-20251202.md:139: Use whatever existing method(s) currently builds a PipelineConfig or equivalent object (e.g., self.app_state.build_pipeline_config() or similar).
- pipeline_config_refs.md:539: - docs\pr_templates\PriorWork_complete\PR-072-RunPipeline-Facade-V2-P1-20251202.md:167: result = self.pipeline_runner.run(pipeline_config)
- pipeline_config_refs.md:540: - docs\pr_templates\PriorWork_complete\PR-072-RunPipeline-Facade-V2-P1-20251202.md:258: def run(self, pipeline_config):
- pipeline_config_refs.md:541: - docs\pr_templates\PriorWork_complete\PR-072-RunPipeline-Facade-V2-P1-20251202.md:259: self.run_calls.append(pipeline_config)
- pipeline_config_refs.md:542: - docs\pr_templates\PriorWork_complete\PR-072-RunPipeline-Facade-V2-P1-20251202.md:263: The exact shape of pipeline_config doesn’t matter for this PR; tests only care that run was called and resulted in one entry in run_calls.
- pipeline_config_refs.md:545: - docs\pr_templates\PriorWork_complete\PR-074-Upscale-Pipeline-Logic-V2-P1-20251202.md:395: pipeline_config = self.build_pipeline_config_v2()
- pipeline_config_refs.md:546: - docs\pr_templates\PriorWork_complete\PR-074-Upscale-Pipeline-Logic-V2-P1-20251202.md:399: return runner.run(pipeline_config, None, self._append_log_threadsafe)
- pipeline_config_refs.md:549: - docs\pr_templates\PriorWork_complete\PR-078-Journey-Test-API-Shims-V2-P1-20251202.md:20: Ensure JT05 and the V2 full-pipeline journey set a minimal valid RunConfig (model, sampler, steps) so AppController.run_pipeline() passes _validate_pipeline_config() and actually calls the runner/WebUI mocks.
- pipeline_config_refs.md:552: - docs\pr_templates\PriorWork_complete\PR-081D-4 — RunConfig Refiner-Hires Fields.md:44: src/gui/panels_v2/pipeline_config_panel_v2.py
- pipeline_config_refs.md:555: - docs\pr_templates\PriorWork_complete\PR-081D-7 — GUI Harness Cleanup Pytest Marker.md:34: src/gui/panels_v2/pipeline_config_panel_v2.py  (checkbox order if required)
- pipeline_config_refs.md:558: - docs\pr_templates\PriorWork_complete\PR-087 – Controller RunConfig & GUI Entrypoint Wiring (V2.5).md:88: tests/controller/test_app_controller_pipeline_integration.py::test_pipeline_config_assembled_from_controller_state
- pipeline_config_refs.md:559: - docs\pr_templates\PriorWork_complete\PR-087 – Controller RunConfig & GUI Entrypoint Wiring (V2.5).md:148: Ensure that the method assembling pipeline config (e.g. AppController._assemble_pipeline_config() or call into pipeline_config_assembler) consumes RunConfig correctly.
- pipeline_config_refs.md:560: - docs\pr_templates\PriorWork_complete\PR-087 – Controller RunConfig & GUI Entrypoint Wiring (V2.5).md:150: Fix test_pipeline_config_assembled_from_controller_state by:
- pipeline_config_refs.md:561: - docs\pr_templates\PriorWork_complete\PR-087 – Controller RunConfig & GUI Entrypoint Wiring (V2.5).md:284: test_pipeline_config_assembled_from_controller_state sees a correctly assembled pipeline config derived from run_config.
- pipeline_config_refs.md:562: - docs\pr_templates\PriorWork_complete\PR-087 – Controller RunConfig & GUI Entrypoint Wiring (V2.5).md:338: test_pipeline_config_assembled_from_controller_state
- pipeline_config_refs.md:565: - docs\pr_templates\PriorWork_complete\PR-107 – StageSequencer + StageExecutionPlan Backbone.md:23: StageSequencer.build_plan(pipeline_config) becomes the single place where we:
- pipeline_config_refs.md:566: - docs\pr_templates\PriorWork_complete\PR-107 – StageSequencer + StageExecutionPlan Backbone.md:25: Interpret the high-level pipeline_config.
- pipeline_config_refs.md:567: - docs\pr_templates\PriorWork_complete\PR-107 – StageSequencer + StageExecutionPlan Backbone.md:146: 4. StageSequencer.build_plan(pipeline_config)
- pipeline_config_refs.md:568: - docs\pr_templates\PriorWork_complete\PR-107 – StageSequencer + StageExecutionPlan Backbone.md:153: def build_plan(self, pipeline_config: Mapping[str, Any]) -> StageExecutionPlan:
- pipeline_config_refs.md:569: - docs\pr_templates\PriorWork_complete\PR-107 – StageSequencer + StageExecutionPlan Backbone.md:156: 4.1 Expected pipeline_config inputs
- pipeline_config_refs.md:570: - docs\pr_templates\PriorWork_complete\PR-107 – StageSequencer + StageExecutionPlan Backbone.md:162: pipeline_config["txt2img_enabled"]  # bool
- pipeline_config_refs.md:571: - docs\pr_templates\PriorWork_complete\PR-107 – StageSequencer + StageExecutionPlan Backbone.md:163: pipeline_config["img2img_enabled"]  # bool
- pipeline_config_refs.md:572: - docs\pr_templates\PriorWork_complete\PR-107 – StageSequencer + StageExecutionPlan Backbone.md:168: pipeline_config["upscale_enabled"]
- pipeline_config_refs.md:573: - docs\pr_templates\PriorWork_complete\PR-107 – StageSequencer + StageExecutionPlan Backbone.md:169: pipeline_config["adetailer_enabled"]
- pipeline_config_refs.md:574: - docs\pr_templates\PriorWork_complete\PR-107 – StageSequencer + StageExecutionPlan Backbone.md:174: pipeline_config["refiner_enabled"]
- pipeline_config_refs.md:575: - docs\pr_templates\PriorWork_complete\PR-107 – StageSequencer + StageExecutionPlan Backbone.md:175: pipeline_config["refiner_model_name"]
- pipeline_config_refs.md:576: - docs\pr_templates\PriorWork_complete\PR-107 – StageSequencer + StageExecutionPlan Backbone.md:176: pipeline_config["refiner_switch_step"]
- pipeline_config_refs.md:577: - docs\pr_templates\PriorWork_complete\PR-107 – StageSequencer + StageExecutionPlan Backbone.md:178: pipeline_config["hires_enabled"]
- pipeline_config_refs.md:578: - docs\pr_templates\PriorWork_complete\PR-107 – StageSequencer + StageExecutionPlan Backbone.md:179: pipeline_config["hires_upscaler_name"]
- pipeline_config_refs.md:579: - docs\pr_templates\PriorWork_complete\PR-107 – StageSequencer + StageExecutionPlan Backbone.md:180: pipeline_config["hires_denoise_strength"]
- pipeline_config_refs.md:580: - docs\pr_templates\PriorWork_complete\PR-107 – StageSequencer + StageExecutionPlan Backbone.md:181: pipeline_config["hires_scale_factor"]
- pipeline_config_refs.md:581: - docs\pr_templates\PriorWork_complete\PR-107 – StageSequencer + StageExecutionPlan Backbone.md:194: txt2img_enabled = bool(pipeline_config.get("txt2img_enabled"))
- pipeline_config_refs.md:582: - docs\pr_templates\PriorWork_complete\PR-107 – StageSequencer + StageExecutionPlan Backbone.md:195: img2img_enabled = bool(pipeline_config.get("img2img_enabled"))
- pipeline_config_refs.md:583: - docs\pr_templates\PriorWork_complete\PR-107 – StageSequencer + StageExecutionPlan Backbone.md:196: upscale_enabled = bool(pipeline_config.get("upscale_enabled"))
- pipeline_config_refs.md:584: - docs\pr_templates\PriorWork_complete\PR-107 – StageSequencer + StageExecutionPlan Backbone.md:197: adetailer_enabled = bool(pipeline_config.get("adetailer_enabled"))
- pipeline_config_refs.md:585: - docs\pr_templates\PriorWork_complete\PR-107 – StageSequencer + StageExecutionPlan Backbone.md:208: config=pipeline_config.get("txt2img_config") or {},
- pipeline_config_refs.md:586: - docs\pr_templates\PriorWork_complete\PR-107 – StageSequencer + StageExecutionPlan Backbone.md:222: config=pipeline_config.get("img2img_config") or {},
- pipeline_config_refs.md:587: - docs\pr_templates\PriorWork_complete\PR-107 – StageSequencer + StageExecutionPlan Backbone.md:231: config=pipeline_config.get("upscale_config") or {},
- pipeline_config_refs.md:588: - docs\pr_templates\PriorWork_complete\PR-107 – StageSequencer + StageExecutionPlan Backbone.md:238: config=pipeline_config.get("adetailer_config") or {},
- pipeline_config_refs.md:589: - docs\pr_templates\PriorWork_complete\PR-107 – StageSequencer + StageExecutionPlan Backbone.md:278: def run(self, pipeline_config: Mapping[str, Any]) -> RunResult:
- pipeline_config_refs.md:590: - docs\pr_templates\PriorWork_complete\PR-107 – StageSequencer + StageExecutionPlan Backbone.md:458: StageSequencer.build_plan(pipeline_config):
- pipeline_config_refs.md:591: - docs\pr_templates\PriorWork_complete\PR-107 – StageSequencer + StageExecutionPlan Backbone.md:482: Once this lands, the stage pipeline becomes deterministic and auditable: controllers and jobs feed a single pipeline_config → StageSequencer.build_plan → PipelineRunner.run(plan) chain, and every change to stage ordering or refiner/hires logic can be tested in isolation.
- pipeline_config_refs.md:594: - docs\pr_templates\PriorWork_complete\PR-B — Canonical JobPart-JobBundle + Builder (V2.5).md:344: test_pipeline_config_snapshot_basic_defaults:
- pipeline_config_refs.md:595: - docs\pr_templates\PriorWork_complete\PR-B — Canonical JobPart-JobBundle + Builder (V2.5).md:348: test_pipeline_config_snapshot_copy_with_overrides:
- pipeline_config_refs.md:596: - docs\pr_templates\PriorWork_complete\PR-B — Canonical JobPart-JobBundle + Builder (V2.5).md:477: test_pipeline_config_snapshot_basic_defaults
- pipeline_config_refs.md:597: - docs\pr_templates\PriorWork_complete\PR-B — Canonical JobPart-JobBundle + Builder (V2.5).md:479: test_pipeline_config_snapshot_copy_with_overrides
- pipeline_config_refs.md:600: - docs\pr_templates\PriorWork_complete\PR-GUI-V2-MIGRATION-003_Real_Pipeline_Config_Behavior.md:62: - tests/gui_v2/test_gui_v2_pipeline_config_roundtrip.py (new)
- pipeline_config_refs.md:601: - docs\pr_templates\PriorWork_complete\PR-GUI-V2-MIGRATION-003_Real_Pipeline_Config_Behavior.md:160: 2) tests/gui_v2/test_gui_v2_pipeline_config_roundtrip.py (new)
- pipeline_config_refs.md:602: - docs\pr_templates\PriorWork_complete\PR-GUI-V2-MIGRATION-003_Real_Pipeline_Config_Behavior.md:227: - tests/gui_v2/test_gui_v2_pipeline_config_roundtrip.py
- pipeline_config_refs.md:605: - docs\pr_templates\PriorWork_complete\PR-GUI-V2-MIGRATION-004_StatusBarV2_Progress_ETA.md:276: - Existing GUI V2 tests (`test_gui_v2_layout_skeleton.py`, `test_gui_v2_pipeline_button_wiring.py`, `test_gui_v2_pipeline_config_roundtrip.py`, `test_gui_v2_startup.py`) still pass.
- pipeline_config_refs.md:608: - docs\pr_templates\PriorWork_complete\PR-GUI-V2-NAMING-003_V2-P1.md:60: 9. `src/gui/views/pipeline_config_panel.py`
- pipeline_config_refs.md:609: - docs\pr_templates\PriorWork_complete\PR-GUI-V2-NAMING-003_V2-P1.md:61: → `src/gui/views/pipeline_config_panel_v2.py`
- pipeline_config_refs.md:610: - docs\pr_templates\PriorWork_complete\PR-GUI-V2-NAMING-003_V2-P1.md:102: from .pipeline_config_panel import PipelineConfigPanel  # noqa: F401
- pipeline_config_refs.md:611: - docs\pr_templates\PriorWork_complete\PR-GUI-V2-NAMING-003_V2-P1.md:113: from .pipeline_config_panel_v2 import PipelineConfigPanel  # noqa: F401
- pipeline_config_refs.md:614: - docs\pr_templates\PriorWork_complete\PR-GUI-V2-PIPELINE-CONFIG-WIRING-002-(2025-11-26).md:11: src/pipeline/pipeline_config_assembler.py
- pipeline_config_refs.md:615: - docs\pr_templates\PriorWork_complete\PR-GUI-V2-PIPELINE-CONFIG-WIRING-002-(2025-11-26).md:29: PipelineController._build_pipeline_config_from_state() uses that state to call
- pipeline_config_refs.md:616: - docs\pr_templates\PriorWork_complete\PR-GUI-V2-PIPELINE-CONFIG-WIRING-002-(2025-11-26).md:67: Ensure PipelineController._build_pipeline_config_from_state() produces a fully populated PipelineConfig by calling:
- pipeline_config_refs.md:617: - docs\pr_templates\PriorWork_complete\PR-GUI-V2-PIPELINE-CONFIG-WIRING-002-(2025-11-26).md:127: def _build_pipeline_config_from_state(self) -> PipelineConfig:
- pipeline_config_refs.md:618: - docs\pr_templates\PriorWork_complete\PR-GUI-V2-PIPELINE-CONFIG-WIRING-002-(2025-11-26).md:345: In PipelineController._build_pipeline_config_from_state() or before run_pipeline:
- pipeline_config_refs.md:619: - docs\pr_templates\PriorWork_complete\PR-GUI-V2-PIPELINE-CONFIG-WIRING-002-(2025-11-26).md:450: _build_pipeline_config_from_state() yields correct overrides.
- pipeline_config_refs.md:622: - docs\pr_templates\PriorWork_complete\PR-GUI-V2-PIPELINE-STAGECARDS-001-Wire Cards-11-26-2025-0816.md:368: controller.update_pipeline_config(cfg)
- pipeline_config_refs.md:625: - docs\pr_templates\PriorWork_complete\PR-GUI-V2-PIPELINE-TAB-002.md:266: - `src/gui/views/pipeline_config_panel.py` (new):
- pipeline_config_refs.md:628: - docs\pr_templates\PriorWork_complete\PR-LEARN-PROFILES-001-Model & LoRA Profile Sidecars as Priors for Learning.md:335: def build_pipeline_config_with_profiles(
- pipeline_config_refs.md:629: - docs\pr_templates\PriorWork_complete\PR-LEARN-PROFILES-001-Model & LoRA Profile Sidecars as Priors for Learning.md:411: test_build_pipeline_config_with_profiles_applies_suggested_preset
- pipeline_config_refs.md:630: - docs\pr_templates\PriorWork_complete\PR-LEARN-PROFILES-001-Model & LoRA Profile Sidecars as Priors for Learning.md:415: Call build_pipeline_config_with_profiles and assert the resulting PipelineConfig matches those values, absent user overrides.
- pipeline_config_refs.md:631: - docs\pr_templates\PriorWork_complete\PR-LEARN-PROFILES-001-Model & LoRA Profile Sidecars as Priors for Learning.md:417: test_build_pipeline_config_with_profiles_respects_user_overrides
- pipeline_config_refs.md:632: - docs\pr_templates\PriorWork_complete\PR-LEARN-PROFILES-001-Model & LoRA Profile Sidecars as Priors for Learning.md:421: test_build_pipeline_config_with_profiles_falls_back_without_profiles
- pipeline_config_refs.md:633: - docs\pr_templates\PriorWork_complete\PR-LEARN-PROFILES-001-Model & LoRA Profile Sidecars as Priors for Learning.md:441: pytest tests/learning/test_profile_integration.py::test_build_pipeline_config_with_profiles_applies_suggested_preset -v
- pipeline_config_refs.md:634: - docs\pr_templates\PriorWork_complete\PR-LEARN-PROFILES-001-Model & LoRA Profile Sidecars as Priors for Learning.md:443: pytest tests/learning/test_profile_integration.py::test_build_pipeline_config_with_profiles_respects_user_overrides -v
- pipeline_config_refs.md:635: - docs\pr_templates\PriorWork_complete\PR-LEARN-PROFILES-001-Model & LoRA Profile Sidecars as Priors for Learning.md:445: pytest tests/learning/test_profile_integration.py::test_build_pipeline_config_with_profiles_falls_back_without_profiles -v
- pipeline_config_refs.md:636: - docs\pr_templates\PriorWork_complete\PR-LEARN-PROFILES-001-Model & LoRA Profile Sidecars as Priors for Learning.md:471: build_pipeline_config_with_profiles:
- pipeline_config_refs.md:637: - docs\pr_templates\PriorWork_complete\PR-LEARN-PROFILES-001-Model & LoRA Profile Sidecars as Priors for Learning.md:579: Call build_pipeline_config_with_profiles and:
- pipeline_config_refs.md:638: - docs\pr_templates\PriorWork_complete\PR-LEARN-PROFILES-001-Model & LoRA Profile Sidecars as Priors for Learning.md:591: Call build_pipeline_config_with_profiles.
- pipeline_config_refs.md:641: - docs\pr_templates\PriorWork_complete\PR-LEARN-V2-RECORDWRITER-001_pipeline_learningrecord_integration.md:114: pipeline_config: PipelineConfig,
- pipeline_config_refs.md:644: - docs\pr_templates\PriorWork_complete\PR-PIPE-CORE-01_Addendum_Bundle\PR-PIPE-CORE-01_Addendum_PipelineRunner_Location_and_Construction.md:92: - Call `self._pipeline_runner.run(pipeline_config, self._cancel_token)` in the worker thread.
- pipeline_config_refs.md:647: - docs\pr_templates\PriorWork_complete\PR-QUEUE-V2-JOBMODEL-001_queue_model_and_single_node_runner_skeleton.md:97: pipeline_config: PipelineConfig
- pipeline_config_refs.md:650: - docs\pr_templates\PriorWork_complete\PR-WIRE-01-V2.5 – “Minimal Happy Path”-11-26-2025-1918.md:36: - Various V2 panels (e.g., `core_config_panel_v2.py`, `model_manager_panel_v2.py`, `pipeline_config_panel_v2.py`, `prompt_editor_panel_v2.py`, `status_bar_v2.py`, etc.)
- pipeline_config_refs.md:651: - docs\pr_templates\PriorWork_complete\PR-WIRE-01-V2.5 – “Minimal Happy Path”-11-26-2025-1918.md:169: - For example, something like `run_pipeline(pipeline_config)` or `execute_txt2img(config)`.
- pipeline_config_refs.md:654: - docs\pr_templates\PriorWork_complete\PR-WIRE-02-V2.5 – Entrypoint Contracts (11-26-2025-1916).md:31: - `tests/gui_v2/test_gui_v2_pipeline_config_roundtrip.py::test_pipeline_panel_loads_initial_config`
- pipeline_config_refs.md:655: - docs\pr_templates\PriorWork_complete\PR-WIRE-02-V2.5 – Entrypoint Contracts (11-26-2025-1916).md:32: - `tests/gui_v2/test_gui_v2_pipeline_config_roundtrip.py::test_pipeline_panel_run_roundtrip`
- pipeline_config_refs.md:656: - docs\pr_templates\PriorWork_complete\PR-WIRE-02-V2.5 – Entrypoint Contracts (11-26-2025-1916).md:73: - `tests/gui_v2/test_gui_v2_pipeline_config_roundtrip.py`
- pipeline_config_refs.md:657: - docs\pr_templates\PriorWork_complete\PR-WIRE-02-V2.5 – Entrypoint Contracts (11-26-2025-1916).md:238: pytest tests/gui_v2/test_gui_v2_pipeline_config_roundtrip.py -q
- pipeline_config_refs.md:660: - docs\pr_templates\PriorWork_complete\PR-WIRE-03-V2.5-11-26-2025.md:89: - `src/gui/pipeline_config_panel_v2.py` or equivalent PipelinePanelV2 implementation.
- pipeline_config_refs.md:661: - docs\pr_templates\PriorWork_complete\PR-WIRE-03-V2.5-11-26-2025.md:172: Inspect src/gui/pipeline_config_panel_v2.py (or wherever PipelinePanelV2 is implemented):
- pipeline_config_refs.md:664: - docs\pr_templates\PriorWork_complete\Script for PR-#51 – Core Config Panel V2.md:38: src/controller/pipeline_config_assembler.py
- pipeline_config_refs.md:665: - docs\pr_templates\PriorWork_complete\Script for PR-#51 – Core Config Panel V2.md:46: tests/controller/test_pipeline_config_assembler_core_fields.py (new or extend existing)
- pipeline_config_refs.md:666: - docs\pr_templates\PriorWork_complete\Script for PR-#51 – Core Config Panel V2.md:138: In pipeline_config_assembler.py:
- pipeline_config_refs.md:667: - docs\pr_templates\PriorWork_complete\Script for PR-#51 – Core Config Panel V2.md:160: pytest tests/controller/test_pipeline_config_assembler_core_fields.py -v
- pipeline_config_refs.md:668: - docs\pr_templates\PriorWork_complete\Script for PR-#51 – Core Config Panel V2.md:188: pytest tests/controller/test_pipeline_config_assembler_core_fields.py -v
- pipeline_config_refs.md:671: - docs\pr_templates\PriorWork_complete\Script for PR-#52 – Negative Prompt Panel V2.md:40: src/controller/pipeline_config_assembler.py
- pipeline_config_refs.md:672: - docs\pr_templates\PriorWork_complete\Script for PR-#52 – Negative Prompt Panel V2.md:48: tests/controller/test_pipeline_config_assembler_negative_prompt.py (new)
- pipeline_config_refs.md:673: - docs\pr_templates\PriorWork_complete\Script for PR-#52 – Negative Prompt Panel V2.md:114: In pipeline_config_assembler.py:
- pipeline_config_refs.md:674: - docs\pr_templates\PriorWork_complete\Script for PR-#52 – Negative Prompt Panel V2.md:130: pytest tests/controller/test_pipeline_config_assembler_negative_prompt.py -v
- pipeline_config_refs.md:675: - docs\pr_templates\PriorWork_complete\Script for PR-#52 – Negative Prompt Panel V2.md:156: pytest tests/controller/test_pipeline_config_assembler_negative_prompt.py -v
- pipeline_config_refs.md:678: - docs\pr_templates\PriorWork_complete\Script for PR-#54 – Output Settings Panel V2.md:38: src/controller/pipeline_config_assembler.py
- pipeline_config_refs.md:679: - docs\pr_templates\PriorWork_complete\Script for PR-#54 – Output Settings Panel V2.md:46: tests/controller/test_pipeline_config_assembler_output_settings.py (new)
- pipeline_config_refs.md:680: - docs\pr_templates\PriorWork_complete\Script for PR-#54 – Output Settings Panel V2.md:112: In pipeline_config_assembler.py:
- pipeline_config_refs.md:681: - docs\pr_templates\PriorWork_complete\Script for PR-#54 – Output Settings Panel V2.md:128: pytest tests/controller/test_pipeline_config_assembler_output_settings.py -v
- pipeline_config_refs.md:682: - docs\pr_templates\PriorWork_complete\Script for PR-#54 – Output Settings Panel V2.md:154: pytest tests/controller/test_pipeline_config_assembler_output_settings.py -v
- pipeline_config_refs.md:685: - docs\pr_templates\PriorWork_complete\Script for PR-#55 – Model Manager Panel V2.md:38: src/controller/pipeline_config_assembler.py
- pipeline_config_refs.md:686: - docs\pr_templates\PriorWork_complete\Script for PR-#55 – Model Manager Panel V2.md:48: tests/controller/test_pipeline_config_assembler_model_fields.py (new or extend)
- pipeline_config_refs.md:687: - docs\pr_templates\PriorWork_complete\Script for PR-#55 – Model Manager Panel V2.md:116: In pipeline_config_assembler.py:
- pipeline_config_refs.md:688: - docs\pr_templates\PriorWork_complete\Script for PR-#55 – Model Manager Panel V2.md:132: pytest tests/controller/test_pipeline_config_assembler_model_fields.py -v
- pipeline_config_refs.md:689: - docs\pr_templates\PriorWork_complete\Script for PR-#55 – Model Manager Panel V2.md:158: pytest tests/controller/test_pipeline_config_assembler_model_fields.py -v
- pipeline_config_refs.md:692: - docs\pr_templates\PriorWork_complete\StableNew PR-091 – AppController ↔ PipelineController Bridge.md:220: is_valid, message = self._validate_pipeline_config()
- pipeline_config_refs.md:693: - docs\pr_templates\PriorWork_complete\StableNew PR-091 – AppController ↔ PipelineController Bridge.md:230: builds pipeline_config via build_pipeline_config_v2(),
- pipeline_config_refs.md:696: - inventory\stable_v2_inventory.json:519: "tests/controller/__pycache__/test_pipeline_config_assembler.cpython-310-pytest-9.0.1.pyc",
- pipeline_config_refs.md:697: - inventory\stable_v2_inventory.json:520: "tests/controller/__pycache__/test_pipeline_config_assembler_core_fields.cpython-310-pytest-9.0.1.pyc",
- pipeline_config_refs.md:698: - inventory\stable_v2_inventory.json:521: "tests/controller/__pycache__/test_pipeline_config_assembler_model_fields.cpython-310-pytest-9.0.1.pyc",
- pipeline_config_refs.md:699: - inventory\stable_v2_inventory.json:522: "tests/controller/__pycache__/test_pipeline_config_assembler_negative_prompt.cpython-310-pytest-9.0.1.pyc",
- pipeline_config_refs.md:700: - inventory\stable_v2_inventory.json:523: "tests/controller/__pycache__/test_pipeline_config_assembler_output_settings.cpython-310-pytest-9.0.1.pyc",
- pipeline_config_refs.md:701: - inventory\stable_v2_inventory.json:524: "tests/controller/__pycache__/test_pipeline_config_assembler_resolution.cpython-310-pytest-9.0.1.pyc",
- pipeline_config_refs.md:702: - inventory\stable_v2_inventory.json:1587: ".mypy_cache/3.11/src/controller/pipeline_config_assembler.data.json",
- pipeline_config_refs.md:703: - inventory\stable_v2_inventory.json:1588: ".mypy_cache/3.11/src/controller/pipeline_config_assembler.meta.json",
- pipeline_config_refs.md:704: - inventory\stable_v2_inventory.json:1843: ".mypy_cache/3.11/tests/controller/test_pipeline_config_assembler.data.json",
- pipeline_config_refs.md:705: - inventory\stable_v2_inventory.json:1844: ".mypy_cache/3.11/tests/controller/test_pipeline_config_assembler.meta.json",
- pipeline_config_refs.md:706: - inventory\stable_v2_inventory.json:5538: "htmlcov/z_7da4a89bed7a4ad5_pipeline_config_panel_py.html",
- pipeline_config_refs.md:707: - inventory\stable_v2_inventory.json:5558: "htmlcov/z_ac5b274346abdaff_pipeline_config_assembler_py.html",
- pipeline_config_refs.md:708: - inventory\stable_v2_inventory.json:5932: "src/controller/pipeline_config_assembler.py",
- pipeline_config_refs.md:709: - inventory\stable_v2_inventory.json:6158: "src/gui/views/pipeline_config_panel.py",
- pipeline_config_refs.md:710: - inventory\stable_v2_inventory.json:6486: "src/gui/views/__pycache__/pipeline_config_panel.cpython-310.pyc",
- pipeline_config_refs.md:711: - inventory\stable_v2_inventory.json:6574: "tests/controller/test_pipeline_config_assembler.py",
- pipeline_config_refs.md:712: - inventory\stable_v2_inventory.json:6575: "tests/controller/test_pipeline_config_assembler_core_fields.py",
- pipeline_config_refs.md:713: - inventory\stable_v2_inventory.json:6576: "tests/controller/test_pipeline_config_assembler_model_fields.py",
- pipeline_config_refs.md:714: - inventory\stable_v2_inventory.json:6577: "tests/controller/test_pipeline_config_assembler_negative_prompt.py",
- pipeline_config_refs.md:715: - inventory\stable_v2_inventory.json:6578: "tests/controller/test_pipeline_config_assembler_output_settings.py",
- pipeline_config_refs.md:716: - inventory\stable_v2_inventory.json:6579: "tests/controller/test_pipeline_config_assembler_resolution.py",
- pipeline_config_refs.md:717: - inventory\stable_v2_inventory.json:6714: ".mypy_cache/3.11/src/gui/panels_v2/pipeline_config_panel_v2.data.json",
- pipeline_config_refs.md:718: - inventory\stable_v2_inventory.json:6715: ".mypy_cache/3.11/src/gui/panels_v2/pipeline_config_panel_v2.meta.json",
- pipeline_config_refs.md:719: - inventory\stable_v2_inventory.json:6748: ".mypy_cache/3.11/src/gui/views/pipeline_config_panel_v2.data.json",
- pipeline_config_refs.md:720: - inventory\stable_v2_inventory.json:6749: ".mypy_cache/3.11/src/gui/views/pipeline_config_panel_v2.meta.json",
- pipeline_config_refs.md:721: - inventory\stable_v2_inventory.json:6812: ".mypy_cache/3.11/tests/gui_v2/test_gui_v2_pipeline_config_roundtrip.data.json",
- pipeline_config_refs.md:722: - inventory\stable_v2_inventory.json:6813: ".mypy_cache/3.11/tests/gui_v2/test_gui_v2_pipeline_config_roundtrip.meta.json",
- pipeline_config_refs.md:723: - inventory\stable_v2_inventory.json:6944: "htmlcov/z_ac9e25382994b44b_pipeline_config_panel_v2_py.html",
- pipeline_config_refs.md:724: - inventory\stable_v2_inventory.json:6969: "src/controller/__pycache__/pipeline_config_assembler.cpython-310.pyc",
- pipeline_config_refs.md:725: - inventory\stable_v2_inventory.json:6999: "src/gui/panels_v2/pipeline_config_panel_v2.py",
- pipeline_config_refs.md:726: - inventory\stable_v2_inventory.json:7002: "src/gui/panels_v2/__pycache__/pipeline_config_panel_v2.cpython-310.pyc",
- pipeline_config_refs.md:727: - inventory\stable_v2_inventory.json:7042: "src/gui/views/.mypy_cache/3.11/src/gui/views/pipeline_config_panel_v2.data.json",
- pipeline_config_refs.md:728: - inventory\stable_v2_inventory.json:7043: "src/gui/views/.mypy_cache/3.11/src/gui/views/pipeline_config_panel_v2.meta.json",
- pipeline_config_refs.md:729: - inventory\stable_v2_inventory.json:7049: "src/gui/views/__pycache__/pipeline_config_panel_v2.cpython-310.pyc",
- pipeline_config_refs.md:730: - inventory\stable_v2_inventory.json:7138: "tests/gui_v2/test_pipeline_config_panel_lora_runtime.py",
- pipeline_config_refs.md:731: - inventory\stable_v2_inventory.json:7180: "tests/gui_v2/__pycache__/test_gui_v2_pipeline_config_roundtrip.cpython-310-pytest-9.0.1.pyc",
- pipeline_config_refs.md:732: - inventory\stable_v2_inventory.json:7207: "tests/gui_v2/__pycache__/test_pipeline_config_panel_lora_runtime.cpython-310-pytest-9.0.1.pyc",
- pipeline_config_refs.md:734: ## pipeline_config_refs.md
- pipeline_config_refs.md:735: - pipeline_config_refs.md:1: # pipeline_config references (excluding archive/.git/zip)
- pipeline_config_refs.md:736: - pipeline_config_refs.md:4: - docs\ARCHITECTURAL_DEBT_ANALYSIS.md:33: # Legacy jobs imported from history still carry pipeline_config blobs.
- pipeline_config_refs.md:737: - pipeline_config_refs.md:5: - docs\ARCHITECTURAL_DEBT_ANALYSIS.md:34: job = Job(job_id="legacy", pipeline_config=None)
- pipeline_config_refs.md:738: - pipeline_config_refs.md:6: - docs\ARCHITECTURAL_DEBT_ANALYSIS.md:35: job.pipeline_config = PipelineConfig(...)
- pipeline_config_refs.md:739: - pipeline_config_refs.md:7: - docs\ARCHITECTURAL_DEBT_ANALYSIS.md:41: > **Status:** Restricted to legacy history imports (PR-CORE1-C2). New jobs never populate `pipeline_config`; any legacy payloads are rehydrated from history via the adapter.
- pipeline_config_refs.md:740: - pipeline_config_refs.md:8: - docs\ARCHITECTURAL_DEBT_ANALYSIS.md:200: - Status: Conflicts with pipeline_config, creates ambiguity
- pipeline_config_refs.md:741: - pipeline_config_refs.md:9: - docs\ARCHITECTURAL_DEBT_ANALYSIS.md:217: 1. **Pick ONE job type:** NormalizedJobRecord; pipeline_config-only jobs are retired and exist solely as legacy history blobs (PR-CORE1-C2).
- pipeline_config_refs.md:742: - pipeline_config_refs.md:10: - docs\ARCHITECTURAL_DEBT_ANALYSIS.md:348: - DTOs derive from `NormalizedJobRecord` snapshots, NOT from `pipeline_config`
- pipeline_config_refs.md:743: - pipeline_config_refs.md:11: - docs\ARCHITECTURAL_DEBT_ANALYSIS.md:350: - Legacy `pipeline_config` fallback preserved only for old jobs without NJR snapshots
- pipeline_config_refs.md:744: - pipeline_config_refs.md:12: - docs\ARCHITECTURAL_DEBT_ANALYSIS.md:365: - ❌ Removed: `pipeline_config` introspection for display purposes (new jobs)
- pipeline_config_refs.md:745: - pipeline_config_refs.md:13: - docs\ARCHITECTURAL_DEBT_ANALYSIS.md:366: - ✅ Preserved: `pipeline_config` execution path (unchanged per CORE1-A3 scope)
- pipeline_config_refs.md:746: - pipeline_config_refs.md:14: - docs\ARCHITECTURAL_DEBT_ANALYSIS.md:373: - No display logic introspects `pipeline_config`
- pipeline_config_refs.md:747: - pipeline_config_refs.md:15: - docs\ARCHITECTURAL_DEBT_ANALYSIS.md:379: - ✅ No fallback to `pipeline_config` for NJR-backed jobs (failures return error status)
- pipeline_config_refs.md:748: - pipeline_config_refs.md:16: - docs\ARCHITECTURAL_DEBT_ANALYSIS.md:382: - ⚠️ PR-CORE1-B3: _to_queue_job() clears pipeline_config, so NJR-only jobs never expose it
- pipeline_config_refs.md:749: - pipeline_config_refs.md:17: - docs\ARCHITECTURAL_DEBT_ANALYSIS.md:383: - ⏳ `pipeline_config` field still exists as **legacy debug field** for inspection
- pipeline_config_refs.md:750: - pipeline_config_refs.md:18: - docs\ARCHITECTURAL_DEBT_ANALYSIS.md:384: - ⏳ `pipeline_config` execution branch preserved for **legacy jobs only** (pre-v2.6, imported)
- pipeline_config_refs.md:751: - pipeline_config_refs.md:19: - docs\ARCHITECTURAL_DEBT_ANALYSIS.md:385: - **Remaining work: Full pipeline_config field/method removal (CORE1-C) - after legacy job migration complete**
- pipeline_config_refs.md:752: - pipeline_config_refs.md:20: - docs\ARCHITECTURAL_DEBT_ANALYSIS.md:405: | Execution payload | `pipeline_config` | `pipeline_config` | **Hybrid (NJR preferred)** | **NJR-only (new jobs, pipeline_config removed)** ✅ | NJR |
- pipeline_config_refs.md:753: - pipeline_config_refs.md:21: - docs\ARCHITECTURAL_DEBT_ANALYSIS.md:412: - ✅ CORE1-D1 migrates legacy history to NJR-only snapshots; history replay no longer depends on pipeline_config payloads.
- pipeline_config_refs.md:754: - pipeline_config_refs.md:22: - docs\ARCHITECTURAL_DEBT_ANALYSIS.md:413: - ƒo. PR-CORE1-B3 ensures _to_queue_job() clears pipeline_config, so new jobs carry only NJR snapshots
- pipeline_config_refs.md:755: - pipeline_config_refs.md:23: - docs\ARCHITECTURAL_DEBT_ANALYSIS.md:415: **Debt Resolved (CORE1-D1/D2/D3):** Legacy history formats, pipeline_config persistence, mixed-era draft-bundle records, schema drift, and multiple replay paths are eliminated; history_schema 2.6 is enforced on load/save via HistoryMigrationEngine + schema normalization, and replay is unified through NJR → RunPlan → PipelineRunner.run_njr.
- pipeline_config_refs.md:756: - pipeline_config_refs.md:24: - docs\ARCHITECTURAL_DEBT_ANALYSIS.md:421: 2. The GUI preview panel reads these normalized records directly, avoiding any legacy `pipeline_config` inspection whenever packs are present.
- pipeline_config_refs.md:757: - pipeline_config_refs.md:25: - docs\ARCHITECTURAL_DEBT_ANALYSIS.md:432: 1. `state/queue_state_v2.json` now stores NJR snapshots plus strict queue metadata (`queue_id`, `status`, `priority`, `created_at`, `queue_schema == "2.6"`, optional metadata, auto-run/paused flags). `_normalized_record`, `pipeline_config`, draft/bundle blobs, and other duplicated execution data are stripped so queue snapshots never diverge from NJR semantics.
- pipeline_config_refs.md:758: - pipeline_config_refs.md:26: - docs\ARCHITECTURAL_DEBT_ANALYSIS.md:437: - Debt removed: queue item schema drift, transitional `_normalized_record` field, pipeline_config remnants in persistence, and inconsistent queue/history summaries.
- pipeline_config_refs.md:759: - pipeline_config_refs.md:29: - docs\ARCHITECTURE_v2.6.md:24: pipeline_config–derived jobs
- pipeline_config_refs.md:760: - pipeline_config_refs.md:30: - docs\ARCHITECTURE_v2.6.md:368: No pipeline_config jobs
- pipeline_config_refs.md:761: - pipeline_config_refs.md:31: - docs\ARCHITECTURE_v2.6.md:407: - All display data comes from NJR snapshots, NOT from pipeline_config
- pipeline_config_refs.md:762: - pipeline_config_refs.md:32: - docs\ARCHITECTURE_v2.6.md:416: → on failure → return error status (NO fallback to pipeline_config)
- pipeline_config_refs.md:763: - pipeline_config_refs.md:33: - docs\ARCHITECTURE_v2.6.md:418: This Job object no longer exposes a `pipeline_config` field; `_normalized_record` is the only execution payload carried between subsystems.
- pipeline_config_refs.md:764: - pipeline_config_refs.md:34: - docs\ARCHITECTURE_v2.6.md:422: Job (with only pipeline_config, no normalized_record) →
- pipeline_config_refs.md:765: - pipeline_config_refs.md:35: - docs\ARCHITECTURE_v2.6.md:424: → _run_pipeline_via_runner_only(pipeline_config) → PipelineRunner.run_njr(legacy NJR adapter)
- pipeline_config_refs.md:766: - pipeline_config_refs.md:36: - docs\ARCHITECTURE_v2.6.md:435: - If NJR execution fails, the job is marked as failed (no pipeline_config fallback)
- pipeline_config_refs.md:767: - pipeline_config_refs.md:37: - docs\ARCHITECTURE_v2.6.md:436: - The queue `Job` model no longer defines `pipeline_config`; new jobs never expose or persist this field (PR-CORE1-C2).
- pipeline_config_refs.md:768: - pipeline_config_refs.md:38: - docs\ARCHITECTURE_v2.6.md:437: - Any remaining `pipeline_config` payloads live in legacy history entries and are rehydrated via `legacy_njr_adapter.build_njr_from_legacy_pipeline_config()`.
- pipeline_config_refs.md:769: - pipeline_config_refs.md:39: - docs\ARCHITECTURE_v2.6.md:441: - The queue snapshot file (`state/queue_state_v2.json`) now records `queue_schema`, `queue_id`, `njr_snapshot`, `priority`, `status`, `created_at`, and lightweight metadata such as `source`/`prompt_source`. Every entry derives directly from the NJR snapshot and drops deprecated keys (`pipeline_config`, bundle summaries, draft blobs) before serialization so that the file always reflects canonical NJR data.
- pipeline_config_refs.md:770: - pipeline_config_refs.md:40: - docs\ARCHITECTURE_v2.6.md:450: | V2.0 Pre‑NJR | JSONL entries containing only `pipeline_config` blobs and ad-hoc `result` dictionaries | Legacy JSON queues with `pipeline_config` per job | Written entries are normalized with `HistoryMigrationEngine`, `QueueMigrationEngine`, and `legacy_njr_adapter` before execution |
- pipeline_config_refs.md:771: - pipeline_config_refs.md:41: - docs\ARCHITECTURE_v2.6.md:459: 3. `legacy_njr_adapter` remains the only adapter for deriving NJRs from pipeline_config-heavy records; replay requests rely entirely on the resulting NJRs plus the unified runner path.
- pipeline_config_refs.md:772: - pipeline_config_refs.md:42: - docs\ARCHITECTURE_v2.6.md:464: - The queue `Job` model no longer exposes `pipeline_config`; `PipelineController._to_queue_job()` instantiates NJR-only jobs without storing pipeline_config.
- pipeline_config_refs.md:773: - pipeline_config_refs.md:43: - docs\ARCHITECTURE_v2.6.md:465: - Queue/JobService/History treat `pipeline_config` as legacy metadata; only imported pre-v2.6 jobs may still store a non-null value via manual assignment.
- pipeline_config_refs.md:774: - pipeline_config_refs.md:44: - docs\ARCHITECTURE_v2.6.md:468: - Legacy `PipelineConfig` executions pass through `legacy_njr_adapter.build_njr_from_legacy_pipeline_config()` and then run through `run_njr`, ensuring the runner core only sees NJRs.
- pipeline_config_refs.md:775: - pipeline_config_refs.md:45: - docs\ARCHITECTURE_v2.6.md:474: - ✅ Display DTOs never introspect pipeline_config (use NJR snapshots)
- pipeline_config_refs.md:776: - pipeline_config_refs.md:46: - docs\ARCHITECTURE_v2.6.md:478: - ??O `pipeline_config` is removed from queue `Job` instances (PR-CORE1-C2); NJR snapshots are the only executable payloads.
- pipeline_config_refs.md:777: - pipeline_config_refs.md:47: - docs\ARCHITECTURE_v2.6.md:483: Legacy history formats are migrated in-memory to NJR snapshots via `HistoryMigrationEngine`. Replay paths no longer accept `pipeline_config` or draft-bundle structures; hydration is NJR-only.
- pipeline_config_refs.md:778: - pipeline_config_refs.md:48: - docs\ARCHITECTURE_v2.6.md:500: History → Restore replays job by reconstructing NJR from snapshot. History load is NJR hydration only; any legacy fields (pipeline_config, draft bundles) are stripped and normalized on load.
- pipeline_config_refs.md:779: - pipeline_config_refs.md:49: - docs\ARCHITECTURE_v2.6.md:501: **History Schema v2.6 (CORE1-D2):** History load = pure NJR hydration + schema normalization. Every persisted entry MUST contain: `id`, `timestamp`, `status`, `history_schema`, `njr_snapshot`, `ui_summary`, `metadata`, `runtime`. Deprecated fields (pipeline_config, draft/draft_bundle/job_bundle, legacy_* blobs) are forbidden and removed during migration. All entries are written in deterministic order; `history_schema` is always `2.6`.
- pipeline_config_refs.md:780: - pipeline_config_refs.md:50: - docs\ARCHITECTURE_v2.6.md:503: **Queue Schema v2.6 (CORE1-D5):** `state/queue_state_v2.json` mirrors History Schema v2.6 by storing `njr_snapshot` plus scheduling metadata (`queue_id`, `status`, `priority`, `created_at`, `queue_schema == "2.6"`, optional `metadata`, auto-run/paused flags). Deprecated fields such as `_normalized_record`, `pipeline_config`, `draft_bundle_summary`, `legacy_config_blob`, and any other duplicated execution data are stripped on load/save so queue snapshots never duplicate NJR state. Tests (`tests/queue/test_job_history_store.py`, `tests/pipeline/test_job_queue_persistence_v2.py`) now assert queue persistence only yields NJR-backed entries and that normalization remains idempotent.
- pipeline_config_refs.md:781: - pipeline_config_refs.md:51: - docs\ARCHITECTURE_v2.6.md:509: **Unified Replay Path (CORE1-D3):** Replay starts from a validated v2.6 HistoryRecord → hydrate NJR snapshot → build RunPlan via `build_run_plan_from_njr` → execute `PipelineRunner.run_njr(run_plan)` → return RunResult. No legacy replay branches, no pipeline_config rebuilds, no controller-local shortcuts. Fresh runs and replays share the exact NJR → RunPlan → Runner chain.
- pipeline_config_refs.md:782: - pipeline_config_refs.md:52: - docs\ARCHITECTURE_v2.6.md:606: pipeline_config or legacy config union models
- pipeline_config_refs.md:783: - pipeline_config_refs.md:53: - docs\ARCHITECTURE_v2.6.md:612: PromptPack-driven previews are now built via `PromptPackNormalizedJobBuilder` inside `PipelineController.get_preview_jobs()`: AppStateV2.job_draft.packs flow through the same NJR builder that execution uses, and the resulting records are stored in AppStateV2.preview_jobs so the GUI preview panel always renders prompt-pack-derived positive prompts/models without exposing pipeline_config or legacy drafts.
- pipeline_config_refs.md:784: - pipeline_config_refs.md:54: - docs\ARCHITECTURE_v2.6.md:704: - Tests and helpers construct Jobs from NJRs only; `pipeline_config=` job construction is removed from new paths.
- pipeline_config_refs.md:785: - pipeline_config_refs.md:57: - docs\Builder Pipeline Deep-Dive (v2.6).md:367: - NJRs are the only execution payload produced by JobBuilderV2 for v2.6 jobs; pipeline_config is left None.
- pipeline_config_refs.md:786: - pipeline_config_refs.md:58: - docs\Builder Pipeline Deep-Dive (v2.6).md:368: - PipelineController._to_queue_job() attaches _normalized_record, sets pipeline_config = None, and builds NJR-driven queue/history snapshots.
- pipeline_config_refs.md:787: - pipeline_config_refs.md:59: - docs\Builder Pipeline Deep-Dive (v2.6).md:369: - Queue, JobService, Runner, and History rely on NJR snapshots for display/execution. Any non-null pipeline_config values belong to legacy pre-v2.6 data.
- pipeline_config_refs.md:788: - pipeline_config_refs.md:60: - docs\Builder Pipeline Deep-Dive (v2.6).md:371: Queue persistence output remains the JSON dump stored at `state/queue_state_v2.json`; D5 enforces that the file only ever contains NJR snapshots plus queue metadata (`queue_id`, `status`, `priority`, `created_at`, `queue_schema == "2.6"`, optional metadata, auto-run/paused flags) and no `_normalized_record`, pipeline_config, or bundle/draft keys. Queue persistence tests confirm this invariance, proving the queue file already mirrors history’s NJR schema even before D6 introduces the shared JSONL codec/format that will eventually let history and queue share the same serialization layer.
- pipeline_config_refs.md:789: - pipeline_config_refs.md:63: - docs\CORE1-D Roadmap — History Integrity, Persistence Cleanup(v2.6).md:24: pipeline_config
- pipeline_config_refs.md:790: - pipeline_config_refs.md:64: - docs\CORE1-D Roadmap — History Integrity, Persistence Cleanup(v2.6).md:59: No history entry anywhere in the repo contains pipeline_config.
- pipeline_config_refs.md:791: - pipeline_config_refs.md:65: - docs\CORE1-D Roadmap — History Integrity, Persistence Cleanup(v2.6).md:367: No pipeline_config references anywhere.
- pipeline_config_refs.md:792: - pipeline_config_refs.md:68: - docs\E2E_Golden_Path_Test_Matrix_v2.6.md:578: - End-to-end queue tests no longer construct jobs with `pipeline_config=`; they wrap NormalizedJobRecord snapshots instead.
- pipeline_config_refs.md:793: - pipeline_config_refs.md:71: - docs\StableNew — Formal Strategy Document (v2.6).md:239: pipeline_config snapshots not aligned to NJR
- pipeline_config_refs.md:794: - pipeline_config_refs.md:74: - docs\StableNew_Coding_and_Testing_v2.6.md:380: Tests must not assert against legacy job DTOs (`JobUiSummary`, `JobQueueItemDTO`, `JobHistoryItemDTO`); controller and history tests should derive summaries via `JobView.from_njr()` (or `JobHistoryService.summarize_history_record()`) and never reconstruct pipeline_config fragments.
- pipeline_config_refs.md:795: - pipeline_config_refs.md:75: - docs\StableNew_Coding_and_Testing_v2.6.md:437: **FORBIDDEN:** Controllers, JobService, and Queue/Runner MUST NOT reference `pipeline_config` on `Job` instances; the field no longer exists in the queue model (PR-CORE1-C2).
- pipeline_config_refs.md:796: - pipeline_config_refs.md:76: - docs\StableNew_Coding_and_Testing_v2.6.md:439: **FORBIDDEN:** If NJR execution fails for an NJR-backed job, the execution path MUST NOT fall back to `pipeline_config`. The job should be marked as failed.
- pipeline_config_refs.md:797: - pipeline_config_refs.md:77: - docs\StableNew_Coding_and_Testing_v2.6.md:441: **LEGACY-ONLY:** `pipeline_config` execution branch is allowed ONLY for jobs without `_normalized_record` (imported from old history, pre-v2.6 jobs).
- pipeline_config_refs.md:798: - pipeline_config_refs.md:78: - docs\StableNew_Coding_and_Testing_v2.6.md:449: `pipeline_config` field no longer exists on Job objects created via JobBuilderV2; new jobs rely solely on NJR snapshots (PR-CORE1-C2). Legacy pipeline_config data lives only in history entries and is rehydrated via `legacy_njr_adapter.build_njr_from_legacy_pipeline_config()`.
- pipeline_config_refs.md:799: - pipeline_config_refs.md:79: - docs\StableNew_Coding_and_Testing_v2.6.md:451: **PR-CORE1-B4:** `PipelineRunner.run(config)` no longer exists. Tests (both unit and integration) must exercise `run_njr()` exclusively and may rely on the legacy adapter if they need to replay pipeline_config-only data.
- pipeline_config_refs.md:800: - pipeline_config_refs.md:80: - docs\StableNew_Coding_and_Testing_v2.6.md:459: Tests MUST verify that NJR execution failures result in job error status (NO fallback to pipeline_config).
- pipeline_config_refs.md:801: - pipeline_config_refs.md:81: - docs\StableNew_Coding_and_Testing_v2.6.md:460: Tests MUST verify that new queue jobs do not expose a `pipeline_config` field (PR-CORE1-C2); any legacy coverage should work through history data only.
- pipeline_config_refs.md:802: - pipeline_config_refs.md:82: - docs\StableNew_Coding_and_Testing_v2.6.md:461: Tests covering queue persistence (`tests/queue/test_job_queue_persistence_v2.py`, `tests/queue/test_job_history_store.py`) must inspect `state/queue_state_v2.json` and assert every entry ships with `njr_snapshot` plus queue metadata only (`queue_id`, `priority`, `status`, `created_at`, optional auto-run/paused flags) and that forbidden keys like `pipeline_config`, `_normalized_record`, or `draft`/`bundle` blobs never survive serialization; this proves queue I/O already matches history’s NJR semantics until D6 unifies the queue file with history’s JSONL codec.
- pipeline_config_refs.md:803: - pipeline_config_refs.md:83: - docs\StableNew_Coding_and_Testing_v2.6.md:463: Tests MUST NOT reference `pipeline_config` or legacy job dicts in persistence/replay suites; all history-oriented tests hydrate NJRs from snapshots.
- pipeline_config_refs.md:804: - pipeline_config_refs.md:84: - docs\StableNew_Coding_and_Testing_v2.6.md:474: Tests for legacy jobs (without NJR) MUST verify `pipeline_config` branch still works.
- pipeline_config_refs.md:805: - pipeline_config_refs.md:87: - docs\older\ARCHITECTURE_v2_COMBINED.md:319: `pipeline_runner.run_full_pipeline(pipeline_config, logger=..., callbacks=...)`
- pipeline_config_refs.md:806: - pipeline_config_refs.md:90: - docs\older\ChatGPT-WhyNoPipeline.md:65: 'src/gui/views/pipeline_config_panel.py',
- pipeline_config_refs.md:807: - pipeline_config_refs.md:91: - docs\older\ChatGPT-WhyNoPipeline.md:1265: 174         if hasattr(self, "pipeline_tab") and hasattr(self.pipeline_tab, "pipeline_config_panel"):
- pipeline_config_refs.md:808: - pipeline_config_refs.md:92: - docs\older\ChatGPT-WhyNoPipeline.md:1267: 176                 self.pipeline_tab.pipeline_config_panel.controller = controller
- pipeline_config_refs.md:809: - pipeline_config_refs.md:93: - docs\older\ChatGPT-WhyNoPipeline.md:1576: 1259         is_valid, message = self._validate_pipeline_config()
- pipeline_config_refs.md:810: - pipeline_config_refs.md:94: - docs\older\ChatGPT-WhyNoPipeline.md:1625: 1304             pipeline_config = self.build_pipeline_config_v2()
- pipeline_config_refs.md:811: - pipeline_config_refs.md:95: - docs\older\ChatGPT-WhyNoPipeline.md:1627: 1306             executor_config = self.pipeline_runner._build_executor_config(pipeline_config)
- pipeline_config_refs.md:812: - pipeline_config_refs.md:96: - docs\older\ChatGPT-WhyNoPipeline.md:1628: 1307             self._cache_last_run_payload(executor_config, pipeline_config)
- pipeline_config_refs.md:813: - pipeline_config_refs.md:97: - docs\older\ChatGPT-WhyNoPipeline.md:1629: 1308             self.pipeline_runner.run(pipeline_config, cancel_token, self._append_log_threadsafe)
- pipeline_config_refs.md:814: - pipeline_config_refs.md:98: - docs\older\ChatGPT-WhyNoPipeline.md:1657: 1185     def _run_pipeline_via_runner_only(self, pipeline_config: PipelineConfig) -> Any:
- pipeline_config_refs.md:815: - pipeline_config_refs.md:99: - docs\older\ChatGPT-WhyNoPipeline.md:1662: 1190         executor_config = runner._build_executor_config(pipeline_config)
- pipeline_config_refs.md:816: - pipeline_config_refs.md:100: - docs\older\ChatGPT-WhyNoPipeline.md:1663: 1191         self._cache_last_run_payload(executor_config, pipeline_config)
- pipeline_config_refs.md:817: - pipeline_config_refs.md:101: - docs\older\ChatGPT-WhyNoPipeline.md:1664: 1192         return runner.run(pipeline_config, None, self._append_log_threadsafe)
- pipeline_config_refs.md:818: - pipeline_config_refs.md:102: - docs\older\ChatGPT-WhyNoPipeline.md:1860: 1051         is_valid, message = self._validate_pipeline_config()
- pipeline_config_refs.md:819: - pipeline_config_refs.md:103: - docs\older\ChatGPT-WhyNoPipeline.md:1884: 1072         pipeline_config = self.build_pipeline_config_v2()
- pipeline_config_refs.md:820: - pipeline_config_refs.md:104: - docs\older\ChatGPT-WhyNoPipeline.md:1888: 1076         result = self.pipeline_controller.run_pipeline(pipeline_config)
- pipeline_config_refs.md:821: - pipeline_config_refs.md:105: - docs\older\ChatGPT-WhyNoPipeline.md:1891: 1079     def _execute_pipeline_via_runner(self, pipeline_config: PipelineConfig) -> Any:
- pipeline_config_refs.md:822: - pipeline_config_refs.md:106: - docs\older\ChatGPT-WhyNoPipeline.md:1898: 1086         result = runner.run(pipeline_config, self.pipeline_controller.cancel_token, self._append_log_threadsafe)
- pipeline_config_refs.md:823: - pipeline_config_refs.md:107: - docs\older\ChatGPT-WhyNoPipeline.md:1901: 1089     def _run_pipeline_from_tab(self, pipeline_tab: Any, pipeline_config: PipelineConfig) -> Any:
- pipeline_config_refs.md:824: - pipeline_config_refs.md:108: - docs\older\ChatGPT-WhyNoPipeline.md:1928: 1116         return self._run_pipeline_via_runner_only(pipeline_config)
- pipeline_config_refs.md:825: - pipeline_config_refs.md:109: - docs\older\ChatGPT-WhyNoPipeline.md:1977: 1304             pipeline_config = self.build_pipeline_config_v2()
- pipeline_config_refs.md:826: - pipeline_config_refs.md:110: - docs\older\ChatGPT-WhyNoPipeline.md:1979: 1306             executor_config = self.pipeline_runner._build_executor_config(pipeline_config)
- pipeline_config_refs.md:827: - pipeline_config_refs.md:111: - docs\older\ChatGPT-WhyNoPipeline.md:1980: 1307             self._cache_last_run_payload(executor_config, pipeline_config)
- pipeline_config_refs.md:828: - pipeline_config_refs.md:112: - docs\older\ChatGPT-WhyNoPipeline.md:1981: 1308             self.pipeline_runner.run(pipeline_config, cancel_token, self._append_log_threadsafe)
- pipeline_config_refs.md:829: - pipeline_config_refs.md:113: - docs\older\ChatGPT-WhyNoPipeline.md:2011: 1304             pipeline_config = self.build_pipeline_config_v2()
- pipeline_config_refs.md:830: - pipeline_config_refs.md:114: - docs\older\ChatGPT-WhyNoPipeline.md:2013: 1306             executor_config = self.pipeline_runner._build_executor_config(pipeline_config)
- pipeline_config_refs.md:831: - pipeline_config_refs.md:115: - docs\older\ChatGPT-WhyNoPipeline.md:2014: 1307             self._cache_last_run_payload(executor_config, pipeline_config)
- pipeline_config_refs.md:832: - pipeline_config_refs.md:116: - docs\older\ChatGPT-WhyNoPipeline.md:2015: 1308             self.pipeline_runner.run(pipeline_config, cancel_token, self._append_log_threadsafe)
- pipeline_config_refs.md:833: - pipeline_config_refs.md:117: - docs\older\ChatGPT-WhyNoPipeline.md:2049: from src.controller.pipeline_config_assembler import PipelineConfigAssembler, GuiOverrides, RunPlan, PlannedJob
- pipeline_config_refs.md:834: - pipeline_config_refs.md:118: - docs\older\ChatGPT-WhyNoPipeline.md:2497: Perhaps validation is failing, causing an early return in on_run_clicked due to _validate_pipeline_config, but the user didn’t mention seeing any error messages. Maybe the run button still points to the old start_run, not start_run_v2.
- pipeline_config_refs.md:835: - pipeline_config_refs.md:119: - docs\older\ChatGPT-WhyNoPipeline.md:2500: The internal _start_run_v2 directly uses the pipeline_controller, while on_run_clicked calls _run_pipeline_thread, which uses pipeline_runner.run without relying on a job queue. However, _run_pipeline_thread still constructs pipeline_config via build_pipeline_config_v2, so that should be fine.
- pipeline_config_refs.md:836: - pipeline_config_refs.md:120: - docs\older\ChatGPT-WhyNoPipeline.md:3229: 385             config = self._build_pipeline_config_from_state()
- pipeline_config_refs.md:837: - pipeline_config_refs.md:121: - docs\older\ChatGPT-WhyNoPipeline.md:3268: 385             config = self._build_pipeline_config_from_state()
- pipeline_config_refs.md:838: - pipeline_config_refs.md:122: - docs\older\ChatGPT-WhyNoPipeline.md:3340: I ran into an index issue again, but I've already seen run_pipeline. Now I’m wondering how PipelineController is used by AppController._run_via_pipeline_controller. This method seems to build the pipeline_config using self.build_pipeline_config_v2() and likely decides between direct and queue run-modes. I’ll check lines 1075-1116 to be sure.
- pipeline_config_refs.md:839: - pipeline_config_refs.md:123: - docs\older\ChatGPT-WhyNoPipeline.md:3350: 1072         pipeline_config = self.build_pipeline_config_v2()
- pipeline_config_refs.md:840: - pipeline_config_refs.md:124: - docs\older\ChatGPT-WhyNoPipeline.md:3354: 1076         result = self.pipeline_controller.run_pipeline(pipeline_config)
- pipeline_config_refs.md:841: - pipeline_config_refs.md:125: - docs\older\ChatGPT-WhyNoPipeline.md:3357: 1079     def _execute_pipeline_via_runner(self, pipeline_config: PipelineConfig) -> Any:
- pipeline_config_refs.md:842: - pipeline_config_refs.md:126: - docs\older\ChatGPT-WhyNoPipeline.md:3364: 1086         result = runner.run(pipeline_config, self.pipeline_controller.cancel_token, self._append_log_threadsafe)
- pipeline_config_refs.md:843: - pipeline_config_refs.md:127: - docs\older\ChatGPT-WhyNoPipeline.md:3367: 1089     def _run_pipeline_from_tab(self, pipeline_tab: Any, pipeline_config: PipelineConfig) -> Any:
- pipeline_config_refs.md:844: - pipeline_config_refs.md:128: - docs\older\ChatGPT-WhyNoPipeline.md:3394: 1116         return self._run_pipeline_via_runner_only(pipeline_config)
- pipeline_config_refs.md:845: - pipeline_config_refs.md:129: - docs\older\ChatGPT-WhyNoPipeline.md:5082: 174         if hasattr(self, "pipeline_tab") and hasattr(self.pipeline_tab, "pipeline_config_panel"):
- pipeline_config_refs.md:846: - pipeline_config_refs.md:130: - docs\older\ChatGPT-WhyNoPipeline.md:5084: 176                 self.pipeline_tab.pipeline_config_panel.controller = controller
- pipeline_config_refs.md:847: - pipeline_config_refs.md:131: - docs\older\ChatGPT-WhyNoPipeline.md:5175: mw.pipeline_config_panel_v2 = getattr(getattr(mw.pipeline_tab, "sidebar", None), "pipeline_config_panel", None)
- pipeline_config_refs.md:848: - pipeline_config_refs.md:132: - docs\older\ChatGPT-WhyNoPipeline.md:5246: mw.pipeline_config_panel_v2 = getattr(getattr(mw.pipeline_tab, "sidebar", None), "pipeline_config_panel", None)
- pipeline_config_refs.md:849: - pipeline_config_refs.md:133: - docs\older\ChatGPT-WhyNoPipeline.md:5506: 22 from src.controller.pipeline_config_assembler import PipelineConfigAssembler, GuiOverrides, RunPlan, PlannedJob
- pipeline_config_refs.md:850: - pipeline_config_refs.md:134: - docs\older\ChatGPT-WhyNoPipeline.md:5552: 68             pipeline_config=config,
- pipeline_config_refs.md:851: - pipeline_config_refs.md:135: - docs\older\ChatGPT-WhyNoPipeline.md:5696: job = Job(job_id=job_id, pipeline_config=None, priority=priority, payload=pipeline_callable, worker_id=worker_id)
- pipeline_config_refs.md:852: - pipeline_config_refs.md:136: - docs\older\ChatGPT-WhyNoPipeline.md:5800: job = Job(job_id=job_id, pipeline_config=None, priority=priority, payload=pipeline_callable, worker_id=worker_id)
- pipeline_config_refs.md:853: - pipeline_config_refs.md:139: - docs\older\GUI-Pipeline-Hierarchy-Diagram.txt:16: │   │           ├── pipeline_config_card (_SidebarCard)
- pipeline_config_refs.md:854: - pipeline_config_refs.md:140: - docs\older\GUI-Pipeline-Hierarchy-Diagram.txt:17: │   │           │   └── pipeline_config_panel (PipelineConfigPanel)
- pipeline_config_refs.md:855: - pipeline_config_refs.md:143: - docs\older\LEGACY_CANDIDATES.md:38: - `src/gui/views/pipeline_config_panel.py` (unreachable)
- pipeline_config_refs.md:856: - pipeline_config_refs.md:144: - docs\older\LEGACY_CANDIDATES.md:64: - `tests/gui_v2/test_gui_v2_pipeline_config_roundtrip.py` (unreachable)
- pipeline_config_refs.md:857: - pipeline_config_refs.md:145: - docs\older\LEGACY_CANDIDATES.md:152: - `src/controller/pipeline_config_assembler.py` (unreachable)
- pipeline_config_refs.md:858: - pipeline_config_refs.md:146: - docs\older\LEGACY_CANDIDATES.md:161: - `tests/controller/test_pipeline_config_assembler.py` (unreachable)
- pipeline_config_refs.md:859: - pipeline_config_refs.md:147: - docs\older\LEGACY_CANDIDATES.md:162: - `tests/controller/test_pipeline_config_assembler_core_fields.py` (unreachable)
- pipeline_config_refs.md:860: - pipeline_config_refs.md:148: - docs\older\LEGACY_CANDIDATES.md:163: - `tests/controller/test_pipeline_config_assembler_model_fields.py` (unreachable)
- pipeline_config_refs.md:861: - pipeline_config_refs.md:149: - docs\older\LEGACY_CANDIDATES.md:164: - `tests/controller/test_pipeline_config_assembler_negative_prompt.py` (unreachable)
- pipeline_config_refs.md:862: - pipeline_config_refs.md:150: - docs\older\LEGACY_CANDIDATES.md:165: - `tests/controller/test_pipeline_config_assembler_output_settings.py` (unreachable)
- pipeline_config_refs.md:863: - pipeline_config_refs.md:151: - docs\older\LEGACY_CANDIDATES.md:166: - `tests/controller/test_pipeline_config_assembler_resolution.py` (unreachable)
- pipeline_config_refs.md:864: - pipeline_config_refs.md:154: - docs\older\Make the pipeline work stream of consciousness.md:1186: cfg = getattr(job, "pipeline_config", None)
- pipeline_config_refs.md:865: - pipeline_config_refs.md:155: - docs\older\Make the pipeline work stream of consciousness.md:1410: from src.controller.pipeline_config_assembler import PipelineConfigAssembler, GuiOverrides, RunPlan, PlannedJob
- pipeline_config_refs.md:866: - pipeline_config_refs.md:156: - docs\older\Make the pipeline work stream of consciousness.md:1459: pipeline_config=config,
- pipeline_config_refs.md:867: - pipeline_config_refs.md:157: - docs\older\Make the pipeline work stream of consciousness.md:1546: def _build_pipeline_config_from_state(self) -> PipelineConfig:
- pipeline_config_refs.md:868: - pipeline_config_refs.md:158: - docs\older\Make the pipeline work stream of consciousness.md:1583: base_config = self._build_pipeline_config_from_state()
- pipeline_config_refs.md:869: - pipeline_config_refs.md:159: - docs\older\Make the pipeline work stream of consciousness.md:1786: def build_pipeline_config_with_profiles(
- pipeline_config_refs.md:870: - pipeline_config_refs.md:160: - docs\older\Make the pipeline work stream of consciousness.md:2014: config = self._build_pipeline_config_from_state()
- pipeline_config_refs.md:871: - pipeline_config_refs.md:161: - docs\older\Make the pipeline work stream of consciousness.md:2174: pipeline_config=config,
- pipeline_config_refs.md:872: - pipeline_config_refs.md:162: - docs\older\Make the pipeline work stream of consciousness.md:2186: if not job.pipeline_config:
- pipeline_config_refs.md:873: - pipeline_config_refs.md:163: - docs\older\Make the pipeline work stream of consciousness.md:2191: result = runner.run(job.pipeline_config, self.cancel_token)
- pipeline_config_refs.md:874: - pipeline_config_refs.md:164: - docs\older\Make the pipeline work stream of consciousness.md:2389: 'pipeline_config_panel_v2.py',
- pipeline_config_refs.md:875: - pipeline_config_refs.md:165: - docs\older\Make the pipeline work stream of consciousness.md:3273: panel = getattr(self.main_window, "pipeline_config_panel_v2", None)
- pipeline_config_refs.md:876: - pipeline_config_refs.md:166: - docs\older\Make the pipeline work stream of consciousness.md:3312: pipeline_config=None,
- pipeline_config_refs.md:877: - pipeline_config_refs.md:167: - docs\older\Make the pipeline work stream of consciousness.md:3389: pipeline_config_panel = getattr(self.main_window, "pipeline_config_panel_v2", None)
- pipeline_config_refs.md:878: - pipeline_config_refs.md:168: - docs\older\Make the pipeline work stream of consciousness.md:3390: if pipeline_config_panel and hasattr(pipeline_config_panel, "apply_run_config"):
- pipeline_config_refs.md:879: - pipeline_config_refs.md:169: - docs\older\Make the pipeline work stream of consciousness.md:3392: pipeline_config_panel.apply_run_config(pack_config)
- pipeline_config_refs.md:880: - pipeline_config_refs.md:170: - docs\older\Make the pipeline work stream of consciousness.md:3783: panel = getattr(self.main_window, "pipeline_config_panel_v2", None)
- pipeline_config_refs.md:881: - pipeline_config_refs.md:171: - docs\older\Make the pipeline work stream of consciousness.md:3822: pipeline_config=None,
- pipeline_config_refs.md:882: - pipeline_config_refs.md:172: - docs\older\Make the pipeline work stream of consciousness.md:3899: pipeline_config_panel = getattr(self.main_window, "pipeline_config_panel_v2", None)
- pipeline_config_refs.md:883: - pipeline_config_refs.md:173: - docs\older\Make the pipeline work stream of consciousness.md:3900: if pipeline_config_panel and hasattr(pipeline_config_panel, "apply_run_config"):
- pipeline_config_refs.md:884: - pipeline_config_refs.md:174: - docs\older\Make the pipeline work stream of consciousness.md:3902: pipeline_config_panel.apply_run_config(pack_config)
- pipeline_config_refs.md:885: - pipeline_config_refs.md:175: - docs\older\Make the pipeline work stream of consciousness.md:4432: pipeline_config=None,
- pipeline_config_refs.md:886: - pipeline_config_refs.md:176: - docs\older\Make the pipeline work stream of consciousness.md:4530: pipeline_config_panel = getattr(self.main_window, "pipeline_config_panel_v2", None)
- pipeline_config_refs.md:887: - pipeline_config_refs.md:177: - docs\older\Make the pipeline work stream of consciousness.md:4531: if pipeline_config_panel and hasattr(pipeline_config_panel, "apply_run_config"):
- pipeline_config_refs.md:888: - pipeline_config_refs.md:178: - docs\older\Make the pipeline work stream of consciousness.md:4533: pipeline_config_panel.apply_run_config(pack_config)
- pipeline_config_refs.md:889: - pipeline_config_refs.md:179: - docs\older\Make the pipeline work stream of consciousness.md:4596: pipeline_config=None,
- pipeline_config_refs.md:890: - pipeline_config_refs.md:180: - docs\older\Make the pipeline work stream of consciousness.md:4782: result = runner.run(job.pipeline_config, self.cancel_token)
- pipeline_config_refs.md:891: - pipeline_config_refs.md:181: - docs\older\Make the pipeline work stream of consciousness.md:4906: # Extract pipeline_config from record.config if it's the right type
- pipeline_config_refs.md:892: - pipeline_config_refs.md:182: - docs\older\Make the pipeline work stream of consciousness.md:4907: pipeline_config = None
- pipeline_config_refs.md:893: - pipeline_config_refs.md:183: - docs\older\Make the pipeline work stream of consciousness.md:4909: pipeline_config = record.config
- pipeline_config_refs.md:894: - pipeline_config_refs.md:184: - docs\older\Make the pipeline work stream of consciousness.md:4913: pipeline_config = record.config
- pipeline_config_refs.md:895: - pipeline_config_refs.md:185: - docs\older\Make the pipeline work stream of consciousness.md:4925: pipeline_config=pipeline_config,
- pipeline_config_refs.md:896: - pipeline_config_refs.md:186: - docs\older\Make the pipeline work stream of consciousness.md:4977: if not job.pipeline_config:
- pipeline_config_refs.md:897: - pipeline_config_refs.md:187: - docs\older\Make the pipeline work stream of consciousness.md:4982: result = runner.run(job.pipeline_config, self.cancel_token)
- pipeline_config_refs.md:898: - pipeline_config_refs.md:188: - docs\older\Make the pipeline work stream of consciousness.md:5436: mw.pipeline_config_panel_v2 = getattr(getattr(mw.pipeline_tab, "sidebar", None), "pipeline_config_panel", None)
- pipeline_config_refs.md:899: - pipeline_config_refs.md:189: - docs\older\Make the pipeline work stream of consciousness.md:5664: base_config = self._build_pipeline_config_from_state()
- pipeline_config_refs.md:900: - pipeline_config_refs.md:190: - docs\older\Make the pipeline work stream of consciousness.md:6130: job = Job(job_id=job_id, pipeline_config=None, priority=priority, payload=pipeline_callable, worker_id=worker_id)
- pipeline_config_refs.md:901: - pipeline_config_refs.md:191: - docs\older\Make the pipeline work stream of consciousness.md:7074: 301:         # Extract pipeline_config from record.config if it's the right type
- pipeline_config_refs.md:902: - pipeline_config_refs.md:192: - docs\older\Make the pipeline work stream of consciousness.md:7075: 302:         pipeline_config = None
- pipeline_config_refs.md:903: - pipeline_config_refs.md:193: - docs\older\Make the pipeline work stream of consciousness.md:7077: 304:             pipeline_config = record.config
- pipeline_config_refs.md:904: - pipeline_config_refs.md:194: - docs\older\Make the pipeline work stream of consciousness.md:7081: 308:                 pipeline_config = record.config
- pipeline_config_refs.md:905: - pipeline_config_refs.md:195: - docs\older\Make the pipeline work stream of consciousness.md:7090: 317:             pipeline_config=pipeline_config,
- pipeline_config_refs.md:906: - pipeline_config_refs.md:196: - docs\older\Make the pipeline work stream of consciousness.md:7202: def build_pipeline_config_with_profiles(
- pipeline_config_refs.md:907: - pipeline_config_refs.md:199: - docs\older\PIPELINE_CONFIG_LOGGING_PRESETS_ADetailer_DISCOVERY_V2-P1.md:19: - **File**: `src/gui/views/pipeline_config_panel_v2.py`
- pipeline_config_refs.md:908: - pipeline_config_refs.md:202: - docs\older\Revised-PR-204-2-MasterPlan_v2.5.md:75: NormalizedJobRecord (or JobSpecV2) carries pipeline_config: PipelineConfig, plus metadata (variant/batch, output paths, etc.).
- pipeline_config_refs.md:909: - pipeline_config_refs.md:203: - docs\older\Revised-PR-204-2-MasterPlan_v2.5.md:194: pipeline_config: PipelineConfig
- pipeline_config_refs.md:910: - pipeline_config_refs.md:204: - docs\older\Revised-PR-204-2-MasterPlan_v2.5.md:432: pipeline_config: PipelineConfig  # fully merged & randomizer/batch aware
- pipeline_config_refs.md:911: - pipeline_config_refs.md:205: - docs\older\Revised-PR-204-2-MasterPlan_v2.5.md:515: base_pipeline_config: PipelineConfig (from PipelineConfigAssembler.build_from_gui_input(...)).
- pipeline_config_refs.md:912: - pipeline_config_refs.md:206: - docs\older\Revised-PR-204-2-MasterPlan_v2.5.md:573: pipeline_config=cfg,
- pipeline_config_refs.md:913: - pipeline_config_refs.md:207: - docs\older\Revised-PR-204-2-MasterPlan_v2.5.md:646: Positive prompt / negative prompt (from pipeline_config).
- pipeline_config_refs.md:914: - pipeline_config_refs.md:208: - docs\older\Revised-PR-204-2-MasterPlan_v2.5.md:714: Submitting JobSpecV2 through JobService leads to correct _run_pipeline_job(pipeline_config) call.
- pipeline_config_refs.md:915: - pipeline_config_refs.md:211: - docs\older\Run Pipeline Path (V2) – Architecture Notes.md:34: pipeline_config
- pipeline_config_refs.md:916: - pipeline_config_refs.md:212: - docs\older\Run Pipeline Path (V2) – Architecture Notes.md:263: pipeline_config
- pipeline_config_refs.md:917: - pipeline_config_refs.md:215: - docs\older\StableNew_Coding_and_Testing_v2.5.md:144: - Functions: `snake_case`, descriptive (`merge_pipeline_config`, `build_jobs`, `to_ui_summary`).
- pipeline_config_refs.md:918: - pipeline_config_refs.md:218: - docs\older\StableNew_V2_Inventory.md:50: - `.mypy_cache/3.11/src/gui/panels_v2/pipeline_config_panel_v2.data.json`
- pipeline_config_refs.md:919: - pipeline_config_refs.md:219: - docs\older\StableNew_V2_Inventory.md:51: - `.mypy_cache/3.11/src/gui/panels_v2/pipeline_config_panel_v2.meta.json`
- pipeline_config_refs.md:920: - pipeline_config_refs.md:220: - docs\older\StableNew_V2_Inventory.md:104: - `.mypy_cache/3.11/src/gui/views/pipeline_config_panel_v2.data.json`
- pipeline_config_refs.md:921: - pipeline_config_refs.md:221: - docs\older\StableNew_V2_Inventory.md:105: - `.mypy_cache/3.11/src/gui/views/pipeline_config_panel_v2.meta.json`
- pipeline_config_refs.md:922: - pipeline_config_refs.md:222: - docs\older\StableNew_V2_Inventory.md:170: - `.mypy_cache/3.11/tests/gui_v2/test_gui_v2_pipeline_config_roundtrip.data.json`
- pipeline_config_refs.md:923: - pipeline_config_refs.md:223: - docs\older\StableNew_V2_Inventory.md:171: - `.mypy_cache/3.11/tests/gui_v2/test_gui_v2_pipeline_config_roundtrip.meta.json`
- pipeline_config_refs.md:924: - pipeline_config_refs.md:224: - docs\older\StableNew_V2_Inventory.md:305: - `htmlcov/z_ac9e25382994b44b_pipeline_config_panel_v2_py.html`
- pipeline_config_refs.md:925: - pipeline_config_refs.md:225: - docs\older\StableNew_V2_Inventory.md:328: - `src/controller/__pycache__/pipeline_config_assembler.cpython-310.pyc`
- pipeline_config_refs.md:926: - pipeline_config_refs.md:226: - docs\older\StableNew_V2_Inventory.md:378: - `src/gui/panels_v2/__pycache__/pipeline_config_panel_v2.cpython-310.pyc`
- pipeline_config_refs.md:927: - pipeline_config_refs.md:227: - docs\older\StableNew_V2_Inventory.md:385: - `src/gui/panels_v2/pipeline_config_panel_v2.py`
- pipeline_config_refs.md:928: - pipeline_config_refs.md:228: - docs\older\StableNew_V2_Inventory.md:417: - `src/gui/views/.mypy_cache/3.11/src/gui/views/pipeline_config_panel_v2.data.json`
- pipeline_config_refs.md:929: - pipeline_config_refs.md:229: - docs\older\StableNew_V2_Inventory.md:418: - `src/gui/views/.mypy_cache/3.11/src/gui/views/pipeline_config_panel_v2.meta.json`
- pipeline_config_refs.md:930: - pipeline_config_refs.md:230: - docs\older\StableNew_V2_Inventory.md:426: - `src/gui/views/__pycache__/pipeline_config_panel_v2.cpython-310.pyc`
- pipeline_config_refs.md:931: - pipeline_config_refs.md:231: - docs\older\StableNew_V2_Inventory.md:510: - `tests/gui_v2/__pycache__/test_gui_v2_pipeline_config_roundtrip.cpython-310-pytest-9.0.1.pyc`
- pipeline_config_refs.md:932: - pipeline_config_refs.md:232: - docs\older\StableNew_V2_Inventory.md:537: - `tests/gui_v2/__pycache__/test_pipeline_config_panel_lora_runtime.cpython-310-pytest-9.0.1.pyc`
- pipeline_config_refs.md:933: - pipeline_config_refs.md:233: - docs\older\StableNew_V2_Inventory.md:579: - `tests/gui_v2/test_pipeline_config_panel_lora_runtime.py`
- pipeline_config_refs.md:934: - pipeline_config_refs.md:234: - docs\older\StableNew_V2_Inventory.md:1198: - `tests/controller/__pycache__/test_pipeline_config_assembler.cpython-310-pytest-9.0.1.pyc`
- pipeline_config_refs.md:935: - pipeline_config_refs.md:235: - docs\older\StableNew_V2_Inventory.md:1199: - `tests/controller/__pycache__/test_pipeline_config_assembler_core_fields.cpython-310-pytest-9.0.1.pyc`
- pipeline_config_refs.md:936: - pipeline_config_refs.md:236: - docs\older\StableNew_V2_Inventory.md:1200: - `tests/controller/__pycache__/test_pipeline_config_assembler_model_fields.cpython-310-pytest-9.0.1.pyc`
- pipeline_config_refs.md:937: - pipeline_config_refs.md:237: - docs\older\StableNew_V2_Inventory.md:1201: - `tests/controller/__pycache__/test_pipeline_config_assembler_negative_prompt.cpython-310-pytest-9.0.1.pyc`
- pipeline_config_refs.md:938: - pipeline_config_refs.md:238: - docs\older\StableNew_V2_Inventory.md:1202: - `tests/controller/__pycache__/test_pipeline_config_assembler_output_settings.cpython-310-pytest-9.0.1.pyc`
- pipeline_config_refs.md:939: - pipeline_config_refs.md:239: - docs\older\StableNew_V2_Inventory.md:1203: - `tests/controller/__pycache__/test_pipeline_config_assembler_resolution.cpython-310-pytest-9.0.1.pyc`
- pipeline_config_refs.md:940: - pipeline_config_refs.md:240: - docs\older\StableNew_V2_Inventory.md:1320: - `src/controller/pipeline_config_assembler.py`
- pipeline_config_refs.md:941: - pipeline_config_refs.md:241: - docs\older\StableNew_V2_Inventory.md:1885: - `src/gui/views/__pycache__/pipeline_config_panel.cpython-310.pyc`
- pipeline_config_refs.md:942: - pipeline_config_refs.md:242: - docs\older\StableNew_V2_Inventory.md:1894: - `src/gui/views/pipeline_config_panel.py`
- pipeline_config_refs.md:943: - pipeline_config_refs.md:243: - docs\older\StableNew_V2_Inventory.md:1958: - `tests/controller/test_pipeline_config_assembler.py`
- pipeline_config_refs.md:944: - pipeline_config_refs.md:244: - docs\older\StableNew_V2_Inventory.md:1959: - `tests/controller/test_pipeline_config_assembler_core_fields.py`
- pipeline_config_refs.md:945: - pipeline_config_refs.md:245: - docs\older\StableNew_V2_Inventory.md:1960: - `tests/controller/test_pipeline_config_assembler_model_fields.py`
- pipeline_config_refs.md:946: - pipeline_config_refs.md:246: - docs\older\StableNew_V2_Inventory.md:1961: - `tests/controller/test_pipeline_config_assembler_negative_prompt.py`
- pipeline_config_refs.md:947: - pipeline_config_refs.md:247: - docs\older\StableNew_V2_Inventory.md:1962: - `tests/controller/test_pipeline_config_assembler_output_settings.py`
- pipeline_config_refs.md:948: - pipeline_config_refs.md:248: - docs\older\StableNew_V2_Inventory.md:1963: - `tests/controller/test_pipeline_config_assembler_resolution.py`
- pipeline_config_refs.md:949: - pipeline_config_refs.md:249: - docs\older\StableNew_V2_Inventory.md:3012: - `.mypy_cache/3.11/src/controller/pipeline_config_assembler.data.json`
- pipeline_config_refs.md:950: - pipeline_config_refs.md:250: - docs\older\StableNew_V2_Inventory.md:3013: - `.mypy_cache/3.11/src/controller/pipeline_config_assembler.meta.json`
- pipeline_config_refs.md:951: - pipeline_config_refs.md:251: - docs\older\StableNew_V2_Inventory.md:3244: - `.mypy_cache/3.11/tests/controller/test_pipeline_config_assembler.data.json`
- pipeline_config_refs.md:952: - pipeline_config_refs.md:252: - docs\older\StableNew_V2_Inventory.md:3245: - `.mypy_cache/3.11/tests/controller/test_pipeline_config_assembler.meta.json`
- pipeline_config_refs.md:953: - pipeline_config_refs.md:253: - docs\older\StableNew_V2_Inventory.md:6925: - `htmlcov/z_7da4a89bed7a4ad5_pipeline_config_panel_py.html`
- pipeline_config_refs.md:954: - pipeline_config_refs.md:254: - docs\older\StableNew_V2_Inventory.md:6945: - `htmlcov/z_ac5b274346abdaff_pipeline_config_assembler_py.html`
- pipeline_config_refs.md:955: - pipeline_config_refs.md:257: - docs\older\StableNew_V2_Inventory_V2-P1.md:107: - `src/controller/pipeline_config_assembler.py`
- pipeline_config_refs.md:956: - pipeline_config_refs.md:258: - docs\older\StableNew_V2_Inventory_V2-P1.md:146: - `src/gui/views/pipeline_config_panel.py`
- pipeline_config_refs.md:957: - pipeline_config_refs.md:259: - docs\older\StableNew_V2_Inventory_V2-P1.md:220: - `tests/gui_v2/test_gui_v2_pipeline_config_roundtrip.py`
- pipeline_config_refs.md:958: - pipeline_config_refs.md:260: - docs\older\StableNew_V2_Inventory_V2-P1.md:341: - `tests/controller/test_pipeline_config_assembler.py`
- pipeline_config_refs.md:959: - pipeline_config_refs.md:261: - docs\older\StableNew_V2_Inventory_V2-P1.md:342: - `tests/controller/test_pipeline_config_assembler_core_fields.py`
- pipeline_config_refs.md:960: - pipeline_config_refs.md:262: - docs\older\StableNew_V2_Inventory_V2-P1.md:343: - `tests/controller/test_pipeline_config_assembler_model_fields.py`
- pipeline_config_refs.md:961: - pipeline_config_refs.md:263: - docs\older\StableNew_V2_Inventory_V2-P1.md:344: - `tests/controller/test_pipeline_config_assembler_negative_prompt.py`
- pipeline_config_refs.md:962: - pipeline_config_refs.md:264: - docs\older\StableNew_V2_Inventory_V2-P1.md:345: - `tests/controller/test_pipeline_config_assembler_output_settings.py`
- pipeline_config_refs.md:963: - pipeline_config_refs.md:265: - docs\older\StableNew_V2_Inventory_V2-P1.md:346: - `tests/controller/test_pipeline_config_assembler_resolution.py`
- pipeline_config_refs.md:964: - pipeline_config_refs.md:268: - docs\older\WIRING_V2_5_ReachableFromMain_2025-11-26.md:126: | `src/pipeline/pipeline_config_v2.py` |  |  |  |  |  |
- pipeline_config_refs.md:965: - pipeline_config_refs.md:271: - docs\older\repo_inventory_classified_v2_phase1.json:25: "src/controller/pipeline_config_assembler.py": "shared_core",
- pipeline_config_refs.md:966: - pipeline_config_refs.md:272: - docs\older\repo_inventory_classified_v2_phase1.json:98: "src/gui/views/pipeline_config_panel.py": "shared_core",
- pipeline_config_refs.md:967: - pipeline_config_refs.md:273: - docs\older\repo_inventory_classified_v2_phase1.json:183: "tests/controller/test_pipeline_config_assembler.py": "neutral_test",
- pipeline_config_refs.md:968: - pipeline_config_refs.md:274: - docs\older\repo_inventory_classified_v2_phase1.json:184: "tests/controller/test_pipeline_config_assembler_core_fields.py": "neutral_test",
- pipeline_config_refs.md:969: - pipeline_config_refs.md:275: - docs\older\repo_inventory_classified_v2_phase1.json:185: "tests/controller/test_pipeline_config_assembler_model_fields.py": "neutral_test",
- pipeline_config_refs.md:970: - pipeline_config_refs.md:276: - docs\older\repo_inventory_classified_v2_phase1.json:186: "tests/controller/test_pipeline_config_assembler_negative_prompt.py": "neutral_test",
- pipeline_config_refs.md:971: - pipeline_config_refs.md:277: - docs\older\repo_inventory_classified_v2_phase1.json:187: "tests/controller/test_pipeline_config_assembler_output_settings.py": "neutral_test",
- pipeline_config_refs.md:972: - pipeline_config_refs.md:278: - docs\older\repo_inventory_classified_v2_phase1.json:188: "tests/controller/test_pipeline_config_assembler_resolution.py": "neutral_test",
- pipeline_config_refs.md:973: - pipeline_config_refs.md:279: - docs\older\repo_inventory_classified_v2_phase1.json:211: "tests/gui_v2/test_gui_v2_pipeline_config_roundtrip.py": "v2_canonical_test",
- pipeline_config_refs.md:974: - pipeline_config_refs.md:282: - docs\pr_templates\PR Doc Resources\PR-114-StreamOfThought.md:114: from src.controller.pipeline_config_assembler import PipelineConfigAssembler, GuiOverrides, RunPlan, PlannedJob
- pipeline_config_refs.md:975: - pipeline_config_refs.md:283: - docs\pr_templates\PR Doc Resources\PR-114-StreamOfThought.md:160: pipeline_config=config,
- pipeline_config_refs.md:976: - pipeline_config_refs.md:284: - docs\pr_templates\PR Doc Resources\PR-114-StreamOfThought.md:241: def _build_pipeline_config_from_state(self) -> PipelineConfig:
- pipeline_config_refs.md:977: - pipeline_config_refs.md:285: - docs\pr_templates\PR Doc Resources\PR-114-StreamOfThought.md:255: def build_pipeline_config_with_profiles(
- pipeline_config_refs.md:978: - pipeline_config_refs.md:286: - docs\pr_templates\PR Doc Resources\PR-114-StreamOfThought.md:380: from src.controller.pipeline_config_assembler import PipelineConfigAssembler, GuiOverrides, RunPlan, PlannedJob
- pipeline_config_refs.md:979: - pipeline_config_refs.md:287: - docs\pr_templates\PR Doc Resources\PR-114-StreamOfThought.md:426: pipeline_config=config,
- pipeline_config_refs.md:980: - pipeline_config_refs.md:288: - docs\pr_templates\PR Doc Resources\PR-114-StreamOfThought.md:507: def _build_pipeline_config_from_state(self) -> PipelineConfig:
- pipeline_config_refs.md:981: - pipeline_config_refs.md:289: - docs\pr_templates\PR Doc Resources\PR-114-StreamOfThought.md:521: def build_pipeline_config_with_profiles(
- pipeline_config_refs.md:982: - pipeline_config_refs.md:290: - docs\pr_templates\PR Doc Resources\PR-114-StreamOfThought.md:743: config = self._build_pipeline_config_from_state()
- pipeline_config_refs.md:983: - pipeline_config_refs.md:291: - docs\pr_templates\PR Doc Resources\PR-114-StreamOfThought.md:790: from src.controller.pipeline_config_assembler import PipelineConfigAssem
- pipeline_config_refs.md:984: - pipeline_config_refs.md:292: - docs\pr_templates\PR Doc Resources\PR-114-StreamOfThought.md:835: config = self._build_pipeline_config_from_state()
- pipeline_config_refs.md:985: - pipeline_config_refs.md:293: - docs\pr_templates\PR Doc Resources\PR-114-StreamOfThought.md:977: job = Job(job_id=job_id, pipeline_config=None, priority=priority, payload=pipeline_callable, worker_id=worker_id)
- pipeline_config_refs.md:986: - pipeline_config_refs.md:294: - docs\pr_templates\PR Doc Resources\PR-114-StreamOfThought.md:1409: job = Job(job_id=job_id, pipeline_config=None, priority=priority, payload=pipeline_callable, worker_id=worker_id)
- pipeline_config_refs.md:987: - pipeline_config_refs.md:295: - docs\pr_templates\PR Doc Resources\PR-114-StreamOfThought.md:1625: from src.controller.pipeline_config_assembler import PipelineConfigAssembler, GuiOverrides, RunPlan, PlannedJob
- pipeline_config_refs.md:988: - pipeline_config_refs.md:296: - docs\pr_templates\PR Doc Resources\PR-114-StreamOfThought.md:1699: pipeline_config=config,
- pipeline_config_refs.md:989: - pipeline_config_refs.md:297: - docs\pr_templates\PR Doc Resources\PR-114-StreamOfThought.md:1739: pipeline_config=config,
- pipeline_config_refs.md:990: - pipeline_config_refs.md:298: - docs\pr_templates\PR Doc Resources\PR-114-StreamOfThought.md:2011: job = Job(job_id=job_id, pipeline_config=None, priority=priority, payload=pipeline_callable, worker_id=worker_id)
- pipeline_config_refs.md:991: - pipeline_config_refs.md:299: - docs\pr_templates\PR Doc Resources\PR-114-StreamOfThought.md:2437: The PipelineRunner.run expects a PipelineConfig dataclass, which is presumably returned by pipeline_controller._build_pipeline_config_from_state—great, that part works. But _run_pipeline_job isn’t using run yet. I need to bridge that gap and integrate the learning hooks (_learning_enabled, _get_learning_runner). I'll also check tests for any existing connections.
- pipeline_config_refs.md:992: - pipeline_config_refs.md:302: - docs\pr_templates\PriorWork_complete\CLEANUP-GUI-TEST-QUARANTINE-002_V2-P1.md:82: - `tests/gui_v2/test_gui_v2_pipeline_config_roundtrip.py`
- pipeline_config_refs.md:993: - pipeline_config_refs.md:305: - docs\pr_templates\PriorWork_complete\Codex_Run_Sheet_PR-GUI-V2-MIGRATION-003.md:12: - tests/gui_v2/test_gui_v2_pipeline_config_roundtrip.py
- pipeline_config_refs.md:994: - pipeline_config_refs.md:306: - docs\pr_templates\PriorWork_complete\Codex_Run_Sheet_PR-GUI-V2-MIGRATION-003.md:103: 1) tests/gui_v2/test_gui_v2_pipeline_config_roundtrip.py (new)
- pipeline_config_refs.md:995: - pipeline_config_refs.md:309: - docs\pr_templates\PriorWork_complete\Dark-Mode-GlobalNeg-11-26-25.md:326: pipeline_config["global_negative"] = self.get_global_negative_config()
- pipeline_config_refs.md:996: - pipeline_config_refs.md:310: - docs\pr_templates\PriorWork_complete\Dark-Mode-GlobalNeg-11-26-25.md:335: global_neg = pipeline_config.get("global_negative", {})
- pipeline_config_refs.md:997: - pipeline_config_refs.md:313: - docs\pr_templates\PriorWork_complete\Execution Script for PR-#53 – Advanced Resolution Controls.md:40: src/controller/pipeline_config_assembler.py
- pipeline_config_refs.md:998: - pipeline_config_refs.md:314: - docs\pr_templates\PriorWork_complete\Execution Script for PR-#53 – Advanced Resolution Controls.md:48: tests/controller/test_pipeline_config_assembler_resolution.py (new or extend)
- pipeline_config_refs.md:999: - pipeline_config_refs.md:315: - docs\pr_templates\PriorWork_complete\Execution Script for PR-#53 – Advanced Resolution Controls.md:110: In pipeline_config_assembler.py:
- pipeline_config_refs.md:1000: - pipeline_config_refs.md:316: - docs\pr_templates\PriorWork_complete\Execution Script for PR-#53 – Advanced Resolution Controls.md:130: pytest tests/controller/test_pipeline_config_assembler_resolution.py -v
- pipeline_config_refs.md:1001: - pipeline_config_refs.md:317: - docs\pr_templates\PriorWork_complete\Execution Script for PR-#53 – Advanced Resolution Controls.md:156: pytest tests/controller/test_pipeline_config_assembler_resolution.py -v
- pipeline_config_refs.md:1002: - pipeline_config_refs.md:320: - docs\pr_templates\PriorWork_complete\PR-#38-PIPELINE-V2-GUIConfigToPipelineConfig-001.md:29: - `src/pipeline/pipeline_config.py` (or equivalent)
- pipeline_config_refs.md:1003: - pipeline_config_refs.md:321: - docs\pr_templates\PriorWork_complete\PR-#38-PIPELINE-V2-GUIConfigToPipelineConfig-001.md:43: - `src/controller/pipeline_config_assembler.py` **(new)** (name flexible, but must live in controller layer)
- pipeline_config_refs.md:1004: - pipeline_config_refs.md:322: - docs\pr_templates\PriorWork_complete\PR-#38-PIPELINE-V2-GUIConfigToPipelineConfig-001.md:45: - `build_pipeline_config(base_config, gui_overrides, randomizer_overlay, learning_enabled) -> PipelineConfig`
- pipeline_config_refs.md:1005: - pipeline_config_refs.md:323: - docs\pr_templates\PriorWork_complete\PR-#38-PIPELINE-V2-GUIConfigToPipelineConfig-001.md:65: - `config = self.config_assembler.build_pipeline_config(...)`
- pipeline_config_refs.md:1006: - pipeline_config_refs.md:324: - docs\pr_templates\PriorWork_complete\PR-#38-PIPELINE-V2-GUIConfigToPipelineConfig-001.md:85: - `tests/controller/test_pipeline_config_assembler.py` **(new)**
- pipeline_config_refs.md:1007: - pipeline_config_refs.md:325: - docs\pr_templates\PriorWork_complete\PR-#38-PIPELINE-V2-GUIConfigToPipelineConfig-001.md:105: - `tests/pipeline/test_pipeline_config_invariants.py` **(new or extended)**
- pipeline_config_refs.md:1008: - pipeline_config_refs.md:326: - docs\pr_templates\PriorWork_complete\PR-#38-PIPELINE-V2-GUIConfigToPipelineConfig-001.md:185: - `pytest tests/controller/test_pipeline_config_assembler.py -v`
- pipeline_config_refs.md:1009: - pipeline_config_refs.md:327: - docs\pr_templates\PriorWork_complete\PR-#38-PIPELINE-V2-GUIConfigToPipelineConfig-001.md:191: - `pytest tests/pipeline/test_pipeline_config_invariants.py -v`
- pipeline_config_refs.md:1010: - pipeline_config_refs.md:330: - docs\pr_templates\PriorWork_complete\PR-#46-PIPELINE-V2-PipelineConfigAssemblerEnforcement-001.md:35: - `src/pipeline/pipeline_config_assembler.py`
- pipeline_config_refs.md:1011: - pipeline_config_refs.md:331: - docs\pr_templates\PriorWork_complete\PR-#46-PIPELINE-V2-PipelineConfigAssemblerEnforcement-001.md:182: - `tests/controller/test_pipeline_config_assembler.py -v`
- pipeline_config_refs.md:1012: - pipeline_config_refs.md:332: - docs\pr_templates\PriorWork_complete\PR-#46-PIPELINE-V2-PipelineConfigAssemblerEnforcement-001.md:206: - `tests/pipeline/test_pipeline_config_invariants.py -v` (new or extended)
- pipeline_config_refs.md:1013: - pipeline_config_refs.md:335: - docs\pr_templates\PriorWork_complete\PR-#47-PIPELINE-V2-AssemblerEnforcement-Finish-001.md:78: - `test_pipeline_config_assembler.py`
- pipeline_config_refs.md:1014: - pipeline_config_refs.md:336: - docs\pr_templates\PriorWork_complete\PR-#47-PIPELINE-V2-AssemblerEnforcement-Finish-001.md:80: - `test_pipeline_config_invariants.py`
- pipeline_config_refs.md:1015: - pipeline_config_refs.md:337: - docs\pr_templates\PriorWork_complete\PR-#47-PIPELINE-V2-AssemblerEnforcement-Finish-001.md:104: - `src/controller/pipeline_config_assembler.py` (small adjustments only; no redesign)
- pipeline_config_refs.md:1016: - pipeline_config_refs.md:338: - docs\pr_templates\PriorWork_complete\PR-#47-PIPELINE-V2-AssemblerEnforcement-Finish-001.md:117: - `tests/controller/test_pipeline_config_assembler.py`
- pipeline_config_refs.md:1017: - pipeline_config_refs.md:339: - docs\pr_templates\PriorWork_complete\PR-#47-PIPELINE-V2-AssemblerEnforcement-Finish-001.md:119: - `tests/pipeline/test_pipeline_config_invariants.py`
- pipeline_config_refs.md:1018: - pipeline_config_refs.md:340: - docs\pr_templates\PriorWork_complete\PR-#47-PIPELINE-V2-AssemblerEnforcement-Finish-001.md:145: **File:** `src/controller/pipeline_config_assembler.py`
- pipeline_config_refs.md:1019: - pipeline_config_refs.md:341: - docs\pr_templates\PriorWork_complete\PR-#47-PIPELINE-V2-AssemblerEnforcement-Finish-001.md:173: - `def _build_pipeline_config_from_state(self) -> PipelineConfig:`
- pipeline_config_refs.md:1020: - pipeline_config_refs.md:342: - docs\pr_templates\PriorWork_complete\PR-#47-PIPELINE-V2-AssemblerEnforcement-Finish-001.md:180: - Build a `PipelineConfig` via `_build_pipeline_config_from_state()`.
- pipeline_config_refs.md:1021: - pipeline_config_refs.md:343: - docs\pr_templates\PriorWork_complete\PR-#47-PIPELINE-V2-AssemblerEnforcement-Finish-001.md:229: - Passes that structure to the controller via a clear call (for example, `controller.request_run_with_overrides(overrides)` or by setting state that `_build_pipeline_config_from_state()` reads).
- pipeline_config_refs.md:1022: - pipeline_config_refs.md:344: - docs\pr_templates\PriorWork_complete\PR-#47-PIPELINE-V2-AssemblerEnforcement-Finish-001.md:268: - `pytest tests/controller/test_pipeline_config_assembler.py -v`
- pipeline_config_refs.md:1023: - pipeline_config_refs.md:345: - docs\pr_templates\PriorWork_complete\PR-#47-PIPELINE-V2-AssemblerEnforcement-Finish-001.md:284: - `pytest tests/pipeline/test_pipeline_config_invariants.py -v`
- pipeline_config_refs.md:1024: - pipeline_config_refs.md:346: - docs\pr_templates\PriorWork_complete\PR-#47-PIPELINE-V2-AssemblerEnforcement-Finish-001.md:318: - `tests/pipeline/test_pipeline_config_invariants.py` is green.
- pipeline_config_refs.md:1025: - pipeline_config_refs.md:347: - docs\pr_templates\PriorWork_complete\PR-#47-PIPELINE-V2-AssemblerEnforcement-Finish-001.md:337: - `src/controller/pipeline_config_assembler.py` (only the deltas introduced by this PR)
- pipeline_config_refs.md:1026: - pipeline_config_refs.md:350: - docs\pr_templates\PriorWork_complete\PR-#47B-PIPELINE-V2-AssemblerEnforcement-Hotfix-001.md:51: - start_pipeline calls into a dedicated _build_pipeline_config_from_state (or equivalent) that wraps build_from_gui_input.
- pipeline_config_refs.md:1027: - pipeline_config_refs.md:351: - docs\pr_templates\PriorWork_complete\PR-#47B-PIPELINE-V2-AssemblerEnforcement-Hotfix-001.md:100: - src/controller/pipeline_config_assembler.py
- pipeline_config_refs.md:1028: - pipeline_config_refs.md:352: - docs\pr_templates\PriorWork_complete\PR-#47B-PIPELINE-V2-AssemblerEnforcement-Hotfix-001.md:104: - tests/controller/test_pipeline_config_assembler.py
- pipeline_config_refs.md:1029: - pipeline_config_refs.md:353: - docs\pr_templates\PriorWork_complete\PR-#47B-PIPELINE-V2-AssemblerEnforcement-Hotfix-001.md:156: - _build_pipeline_config_from_state(self) -> PipelineConfig:
- pipeline_config_refs.md:1030: - pipeline_config_refs.md:354: - docs\pr_templates\PriorWork_complete\PR-#47B-PIPELINE-V2-AssemblerEnforcement-Hotfix-001.md:177: - Build a PipelineConfig using _build_pipeline_config_from_state.
- pipeline_config_refs.md:1031: - pipeline_config_refs.md:355: - docs\pr_templates\PriorWork_complete\PR-#47B-PIPELINE-V2-AssemblerEnforcement-Hotfix-001.md:222: - pytest tests/controller/test_pipeline_config_assembler.py -v
- pipeline_config_refs.md:1032: - pipeline_config_refs.md:356: - docs\pr_templates\PriorWork_complete\PR-#47B-PIPELINE-V2-AssemblerEnforcement-Hotfix-001.md:245: If any test outside the target ones fails, analyze the failure and apply the minimal fix within src/controller/pipeline_controller.py or, if absolutely necessary, src/controller/pipeline_config_assembler.py.
- pipeline_config_refs.md:1033: - pipeline_config_refs.md:357: - docs\pr_templates\PriorWork_complete\PR-#47B-PIPELINE-V2-AssemblerEnforcement-Hotfix-001.md:280: - src/controller/pipeline_config_assembler.py (if touched)
- pipeline_config_refs.md:1034: - pipeline_config_refs.md:360: - docs\pr_templates\PriorWork_complete\PR-#50-GUI-V2-PromptPackManager-Integration-001.md:56: - `src/controller/pipeline_config_assembler.py`
- pipeline_config_refs.md:1035: - pipeline_config_refs.md:363: - docs\pr_templates\PriorWork_complete\PR-#51-GUI-V2-CoreConfigPanel-001.md:127: - `src/controller/pipeline_config_assembler.py` *(ensure assembler accepts core config overrides and maps into `PipelineConfig`)*
- pipeline_config_refs.md:1036: - pipeline_config_refs.md:364: - docs\pr_templates\PriorWork_complete\PR-#51-GUI-V2-CoreConfigPanel-001.md:133: - `tests/controller/test_pipeline_config_assembler_core_fields.py` *(new or extend existing assembler tests)*
- pipeline_config_refs.md:1037: - pipeline_config_refs.md:365: - docs\pr_templates\PriorWork_complete\PR-#51-GUI-V2-CoreConfigPanel-001.md:239: In `src/controller/pipeline_config_assembler.py`:
- pipeline_config_refs.md:1038: - pipeline_config_refs.md:366: - docs\pr_templates\PriorWork_complete\PR-#51-GUI-V2-CoreConfigPanel-001.md:269: 2. **Assembler test**: `tests/controller/test_pipeline_config_assembler_core_fields.py`
- pipeline_config_refs.md:1039: - pipeline_config_refs.md:367: - docs\pr_templates\PriorWork_complete\PR-#51-GUI-V2-CoreConfigPanel-001.md:271: - `test_assembler_maps_core_fields_to_pipeline_config`:
- pipeline_config_refs.md:1040: - pipeline_config_refs.md:368: - docs\pr_templates\PriorWork_complete\PR-#51-GUI-V2-CoreConfigPanel-001.md:296: - `pytest tests/controller/test_pipeline_config_assembler_core_fields.py -v`
- pipeline_config_refs.md:1041: - pipeline_config_refs.md:369: - docs\pr_templates\PriorWork_complete\PR-#51-GUI-V2-CoreConfigPanel-001.md:335: - `src/controller/pipeline_config_assembler.py`
- pipeline_config_refs.md:1042: - pipeline_config_refs.md:370: - docs\pr_templates\PriorWork_complete\PR-#51-GUI-V2-CoreConfigPanel-001.md:367: - `pytest tests/controller/test_pipeline_config_assembler_core_fields.py -v`
- pipeline_config_refs.md:1043: - pipeline_config_refs.md:373: - docs\pr_templates\PriorWork_complete\PR-#52-GUI-V2-NegativePromptPanel-001.md:114: - `src/controller/pipeline_config_assembler.py` *(map negative_prompt into `PipelineConfig`)*
- pipeline_config_refs.md:1044: - pipeline_config_refs.md:374: - docs\pr_templates\PriorWork_complete\PR-#52-GUI-V2-NegativePromptPanel-001.md:123: - `tests/controller/test_pipeline_config_assembler_negative_prompt.py` *(new)*
- pipeline_config_refs.md:1045: - pipeline_config_refs.md:375: - docs\pr_templates\PriorWork_complete\PR-#52-GUI-V2-NegativePromptPanel-001.md:192: In `src/controller/pipeline_config_assembler.py`:
- pipeline_config_refs.md:1046: - pipeline_config_refs.md:376: - docs\pr_templates\PriorWork_complete\PR-#52-GUI-V2-NegativePromptPanel-001.md:213: 2. `tests/controller/test_pipeline_config_assembler_negative_prompt.py`:
- pipeline_config_refs.md:1047: - pipeline_config_refs.md:377: - docs\pr_templates\PriorWork_complete\PR-#52-GUI-V2-NegativePromptPanel-001.md:229: - `pytest tests/controller/test_pipeline_config_assembler_negative_prompt.py -v`
- pipeline_config_refs.md:1048: - pipeline_config_refs.md:378: - docs\pr_templates\PriorWork_complete\PR-#52-GUI-V2-NegativePromptPanel-001.md:295: - `pytest tests/controller/test_pipeline_config_assembler_negative_prompt.py -v`
- pipeline_config_refs.md:1049: - pipeline_config_refs.md:381: - docs\pr_templates\PriorWork_complete\PR-#53-GUI-V2-ResolutionAdvancedControls-001.md:120: - `src/controller/pipeline_config_assembler.py` *(interpret overrides into width/height and apply clamps)*
- pipeline_config_refs.md:1050: - pipeline_config_refs.md:382: - docs\pr_templates\PriorWork_complete\PR-#53-GUI-V2-ResolutionAdvancedControls-001.md:129: - `tests/controller/test_pipeline_config_assembler_resolution.py` *(new or extended)*
- pipeline_config_refs.md:1051: - pipeline_config_refs.md:383: - docs\pr_templates\PriorWork_complete\PR-#53-GUI-V2-ResolutionAdvancedControls-001.md:197: In `src/controller/pipeline_config_assembler.py`:
- pipeline_config_refs.md:1052: - pipeline_config_refs.md:384: - docs\pr_templates\PriorWork_complete\PR-#53-GUI-V2-ResolutionAdvancedControls-001.md:223: 2. `tests/controller/test_pipeline_config_assembler_resolution.py`:
- pipeline_config_refs.md:1053: - pipeline_config_refs.md:385: - docs\pr_templates\PriorWork_complete\PR-#53-GUI-V2-ResolutionAdvancedControls-001.md:239: - `pytest tests/controller/test_pipeline_config_assembler_resolution.py -v`
- pipeline_config_refs.md:1054: - pipeline_config_refs.md:386: - docs\pr_templates\PriorWork_complete\PR-#53-GUI-V2-ResolutionAdvancedControls-001.md:304: - `pytest tests/controller/test_pipeline_config_assembler_resolution.py -v`
- pipeline_config_refs.md:1055: - pipeline_config_refs.md:389: - docs\pr_templates\PriorWork_complete\PR-#54-GUI-V2-OutputSettingsPanel-001.md:115: - `src/controller/pipeline_config_assembler.py` *(map output overrides into `PipelineConfig`)*
- pipeline_config_refs.md:1056: - pipeline_config_refs.md:390: - docs\pr_templates\PriorWork_complete\PR-#54-GUI-V2-OutputSettingsPanel-001.md:124: - `tests/controller/test_pipeline_config_assembler_output_settings.py` *(new)*
- pipeline_config_refs.md:1057: - pipeline_config_refs.md:391: - docs\pr_templates\PriorWork_complete\PR-#54-GUI-V2-OutputSettingsPanel-001.md:194: In `src/controller/pipeline_config_assembler.py`:
- pipeline_config_refs.md:1058: - pipeline_config_refs.md:392: - docs\pr_templates\PriorWork_complete\PR-#54-GUI-V2-OutputSettingsPanel-001.md:215: 2. `tests/controller/test_pipeline_config_assembler_output_settings.py`:
- pipeline_config_refs.md:1059: - pipeline_config_refs.md:393: - docs\pr_templates\PriorWork_complete\PR-#54-GUI-V2-OutputSettingsPanel-001.md:231: - `pytest tests/controller/test_pipeline_config_assembler_output_settings.py -v`
- pipeline_config_refs.md:1060: - pipeline_config_refs.md:394: - docs\pr_templates\PriorWork_complete\PR-#54-GUI-V2-OutputSettingsPanel-001.md:295: - `pytest tests/controller/test_pipeline_config_assembler_output_settings.py -v`
- pipeline_config_refs.md:1061: - pipeline_config_refs.md:397: - docs\pr_templates\PriorWork_complete\PR-#55-GUI-V2-ModelManagerPanel-001.md:110: - `src/controller/pipeline_config_assembler.py` *(map model/vae into `PipelineConfig`)*
- pipeline_config_refs.md:1062: - pipeline_config_refs.md:398: - docs\pr_templates\PriorWork_complete\PR-#55-GUI-V2-ModelManagerPanel-001.md:121: - `tests/controller/test_pipeline_config_assembler_model_fields.py` *(new or extended)*
- pipeline_config_refs.md:1063: - pipeline_config_refs.md:399: - docs\pr_templates\PriorWork_complete\PR-#55-GUI-V2-ModelManagerPanel-001.md:200: In `src/controller/pipeline_config_assembler.py`:
- pipeline_config_refs.md:1064: - pipeline_config_refs.md:400: - docs\pr_templates\PriorWork_complete\PR-#55-GUI-V2-ModelManagerPanel-001.md:220: 2. `tests/controller/test_pipeline_config_assembler_model_fields.py`:
- pipeline_config_refs.md:1065: - pipeline_config_refs.md:401: - docs\pr_templates\PriorWork_complete\PR-#55-GUI-V2-ModelManagerPanel-001.md:236: - `pytest tests/controller/test_pipeline_config_assembler_model_fields.py -v`
- pipeline_config_refs.md:1066: - pipeline_config_refs.md:402: - docs\pr_templates\PriorWork_complete\PR-#55-GUI-V2-ModelManagerPanel-001.md:301: - `pytest tests/controller/test_pipeline_config_assembler_model_fields.py -v`
- pipeline_config_refs.md:1067: - pipeline_config_refs.md:405: - docs\pr_templates\PriorWork_complete\PR-0114 — Pipeline Run Controls → Queue-Runner.md:100: config = job.pipeline_config
- pipeline_config_refs.md:1068: - pipeline_config_refs.md:406: - docs\pr_templates\PriorWork_complete\PR-0114 — Pipeline Run Controls → Queue-Runner.md:219: config = job.pipeline_config
- pipeline_config_refs.md:1069: - pipeline_config_refs.md:409: - docs\pr_templates\PriorWork_complete\PR-0114C – End-to-End Job Execution + Journey Tests.md:71: Invokes PipelineRunner via runner.run(job.pipeline_config, self.cancel_token) (for multi-stage path).
- pipeline_config_refs.md:1070: - pipeline_config_refs.md:412: - docs\pr_templates\PriorWork_complete\PR-016-PIPELINE-CONFIG-UX-RESTORE-V2-P1.md:24: - `src/gui/views/pipeline_config_panel_v2.py`
- pipeline_config_refs.md:1071: - pipeline_config_refs.md:413: - docs\pr_templates\PriorWork_complete\PR-016-PIPELINE-CONFIG-UX-RESTORE-V2-P1.md:51: ### 3.1 `pipeline_config_panel_v2.py` — Validation Surface
- pipeline_config_refs.md:1072: - pipeline_config_refs.md:414: - docs\pr_templates\PriorWork_complete\PR-016-PIPELINE-CONFIG-UX-RESTORE-V2-P1.md:79: def validate_pipeline_config(self) -> Tuple[bool, str]:
- pipeline_config_refs.md:1073: - pipeline_config_refs.md:415: - docs\pr_templates\PriorWork_complete\PR-016-PIPELINE-CONFIG-UX-RESTORE-V2-P1.md:92: is_valid, message = self.validate_pipeline_config()
- pipeline_config_refs.md:1074: - pipeline_config_refs.md:416: - docs\pr_templates\PriorWork_complete\PR-016-PIPELINE-CONFIG-UX-RESTORE-V2-P1.md:93: pipeline_panel = self._app_state.get("pipeline_config_panel_v2")
- pipeline_config_refs.md:1075: - pipeline_config_refs.md:417: - docs\pr_templates\PriorWork_complete\PR-016-PIPELINE-CONFIG-UX-RESTORE-V2-P1.md:107: - When `validate_pipeline_config` is called, update:
- pipeline_config_refs.md:1076: - pipeline_config_refs.md:418: - docs\pr_templates\PriorWork_complete\PR-016-PIPELINE-CONFIG-UX-RESTORE-V2-P1.md:136: panel = self._app_state.get("pipeline_config_panel_v2")
- pipeline_config_refs.md:1077: - pipeline_config_refs.md:419: - docs\pr_templates\PriorWork_complete\PR-016-PIPELINE-CONFIG-UX-RESTORE-V2-P1.md:152: - `tests/gui_v2/test_pipeline_config_validation_v2.py`:
- pipeline_config_refs.md:1078: - pipeline_config_refs.md:420: - docs\pr_templates\PriorWork_complete\PR-016-PIPELINE-CONFIG-UX-RESTORE-V2-P1.md:159: - `tests/controller/test_pipeline_config_validation_v2.py`:
- pipeline_config_refs.md:1079: - pipeline_config_refs.md:421: - docs\pr_templates\PriorWork_complete\PR-016-PIPELINE-CONFIG-UX-RESTORE-V2-P1.md:161: - Tests `validate_pipeline_config` logic independently (unit-level).
- pipeline_config_refs.md:1080: - pipeline_config_refs.md:424: - docs\pr_templates\PriorWork_complete\PR-024-MAIN-WEBUI-LAUNCH-UX-BROWSER-READY-V2-P1.md:114: src/gui/views/pipeline_config_panel_v2.py
- pipeline_config_refs.md:1081: - pipeline_config_refs.md:427: - docs\pr_templates\PriorWork_complete\PR-031-PIPELINE-CONFIG-LEFTCOLUMN-WIRING-V2-P1.md:114: src/gui/panels_v2/pipeline_config_panel_v2.py
- pipeline_config_refs.md:1082: - pipeline_config_refs.md:428: - docs\pr_templates\PriorWork_complete\PR-031-PIPELINE-CONFIG-LEFTCOLUMN-WIRING-V2-P1.md:215: Import PipelineConfigPanelV2 from src.gui.panels_v2.pipeline_config_panel_v2.
- pipeline_config_refs.md:1083: - pipeline_config_refs.md:429: - docs\pr_templates\PriorWork_complete\PR-031-PIPELINE-CONFIG-LEFTCOLUMN-WIRING-V2-P1.md:235: Ensure naming is consistent with existing patterns (e.g., self.pipeline_config_panel if that’s the convention).
- pipeline_config_refs.md:1084: - pipeline_config_refs.md:430: - docs\pr_templates\PriorWork_complete\PR-031-PIPELINE-CONFIG-LEFTCOLUMN-WIRING-V2-P1.md:239: In pipeline_config_panel_v2.py:
- pipeline_config_refs.md:1085: - pipeline_config_refs.md:431: - docs\pr_templates\PriorWork_complete\PR-031-PIPELINE-CONFIG-LEFTCOLUMN-WIRING-V2-P1.md:335: Add a small assertion that the pipeline tab exposes a handle to pipeline_config_panel or similar, if that’s how it’s exposed.
- pipeline_config_refs.md:1086: - pipeline_config_refs.md:432: - docs\pr_templates\PriorWork_complete\PR-031-PIPELINE-CONFIG-LEFTCOLUMN-WIRING-V2-P1.md:418: pipeline_config_panel_v2.py
- pipeline_config_refs.md:1087: - pipeline_config_refs.md:435: - docs\pr_templates\PriorWork_complete\PR-032-BOTTOM-LOGGING-SURFACE-V2-P1.md:189: src/gui/panels_v2/sidebar_panel_v2.py / pipeline_config_panel_v2.py (those are PR-031 domain)
- pipeline_config_refs.md:1088: - pipeline_config_refs.md:438: - docs\pr_templates\PriorWork_complete\PR-033-PIPELINE-PRESETS-HOOKUP-V2-P1.md:147: src/gui/panels_v2/pipeline_config_panel_v2.py
- pipeline_config_refs.md:1089: - pipeline_config_refs.md:439: - docs\pr_templates\PriorWork_complete\PR-033-PIPELINE-PRESETS-HOOKUP-V2-P1.md:332: File: src/gui/panels_v2/pipeline_config_panel_v2.py
- pipeline_config_refs.md:1090: - pipeline_config_refs.md:440: - docs\pr_templates\PriorWork_complete\PR-033-PIPELINE-PRESETS-HOOKUP-V2-P1.md:491: src/gui/panels_v2/pipeline_config_panel_v2.py
- pipeline_config_refs.md:1091: - pipeline_config_refs.md:443: - docs\pr_templates\PriorWork_complete\PR-033A-PIPELINE-LEFT-PANEL-UX-V2-P1.md:72: src/gui/views/pipeline_config_panel_v2.py (or current config panel implementation)
- pipeline_config_refs.md:1092: - pipeline_config_refs.md:444: - docs\pr_templates\PriorWork_complete\PR-033A-PIPELINE-LEFT-PANEL-UX-V2-P1.md:132: In pipeline_config_panel_v2.py, ensure:
- pipeline_config_refs.md:1093: - pipeline_config_refs.md:445: - docs\pr_templates\PriorWork_complete\PR-033A-PIPELINE-LEFT-PANEL-UX-V2-P1.md:206: pipeline_config_panel_v2.py
- pipeline_config_refs.md:1094: - pipeline_config_refs.md:448: - docs\pr_templates\PriorWork_complete\PR-034-PIPELINE-PRESETS-INTEGRATION-V2-P1.md:78: src/gui/views/pipeline_config_panel_v2.py (read/write config fields)
- pipeline_config_refs.md:1095: - pipeline_config_refs.md:449: - docs\pr_templates\PriorWork_complete\PR-034-PIPELINE-PRESETS-INTEGRATION-V2-P1.md:200: pipeline_config_panel_v2.py
- pipeline_config_refs.md:1096: - pipeline_config_refs.md:452: - docs\pr_templates\PriorWork_complete\PR-035-PIPELINE-PACK-CONFIG-JOB-BUILDER-V2-P1.md:176: src/gui/panels_v2/pipeline_config_panel_v2.py
- pipeline_config_refs.md:1097: - pipeline_config_refs.md:453: - docs\pr_templates\PriorWork_complete\PR-035-PIPELINE-PACK-CONFIG-JOB-BUILDER-V2-P1.md:420: pipeline_config_panel_v2.py
- pipeline_config_refs.md:1098: - pipeline_config_refs.md:456: - docs\pr_templates\PriorWork_complete\PR-036-PIPELINE-TAB-3COLUMN-LAYOUT-V2-P1.md:113: src/gui/panels_v2/pipeline_config_panel_v2.py
- pipeline_config_refs.md:1099: - pipeline_config_refs.md:457: - docs\pr_templates\PriorWork_complete\PR-036-PIPELINE-TAB-3COLUMN-LAYOUT-V2-P1.md:336: pipeline_config_panel_v2.py
- pipeline_config_refs.md:1100: - pipeline_config_refs.md:460: - docs\pr_templates\PriorWork_complete\PR-037-Pipeline-LoRA-Strengths-V2-P1.md:108: src/gui/panels_v2/pipeline_config_panel_v2.py
- pipeline_config_refs.md:1101: - pipeline_config_refs.md:461: - docs\pr_templates\PriorWork_complete\PR-037-Pipeline-LoRA-Strengths-V2-P1.md:167: In pipeline_config_panel_v2.py:
- pipeline_config_refs.md:1102: - pipeline_config_refs.md:462: - docs\pr_templates\PriorWork_complete\PR-037-Pipeline-LoRA-Strengths-V2-P1.md:199: Call pipeline_config_panel.load_lora_strengths() with these values.
- pipeline_config_refs.md:1103: - pipeline_config_refs.md:463: - docs\pr_templates\PriorWork_complete\PR-037-Pipeline-LoRA-Strengths-V2-P1.md:203: Read current LoRA strengths via pipeline_config_panel.get_lora_strengths().
- pipeline_config_refs.md:1104: - pipeline_config_refs.md:464: - docs\pr_templates\PriorWork_complete\PR-037-Pipeline-LoRA-Strengths-V2-P1.md:277: pipeline_config_panel_v2.py
- pipeline_config_refs.md:1105: - pipeline_config_refs.md:467: - docs\pr_templates\PriorWork_complete\PR-037A-Pipeline-LoRA-Strengths-V2-P1.md:110: src/gui/panels_v2/pipeline_config_panel_v2.py
- pipeline_config_refs.md:1106: - pipeline_config_refs.md:468: - docs\pr_templates\PriorWork_complete\PR-037A-Pipeline-LoRA-Strengths-V2-P1.md:169: In pipeline_config_panel_v2.py:
- pipeline_config_refs.md:1107: - pipeline_config_refs.md:469: - docs\pr_templates\PriorWork_complete\PR-037A-Pipeline-LoRA-Strengths-V2-P1.md:201: Call pipeline_config_panel.load_lora_strengths() with these values.
- pipeline_config_refs.md:1108: - pipeline_config_refs.md:470: - docs\pr_templates\PriorWork_complete\PR-037A-Pipeline-LoRA-Strengths-V2-P1.md:205: Read current LoRA strengths via pipeline_config_panel.get_lora_strengths().
- pipeline_config_refs.md:1109: - pipeline_config_refs.md:471: - docs\pr_templates\PriorWork_complete\PR-037A-Pipeline-LoRA-Strengths-V2-P1.md:279: pipeline_config_panel_v2.py
- pipeline_config_refs.md:1110: - pipeline_config_refs.md:474: - docs\pr_templates\PriorWork_complete\PR-038-Pipeline-Randomizer-Config-V2-P1.md:119: src/gui/panels_v2/pipeline_config_panel_v2.py
- pipeline_config_refs.md:1111: - pipeline_config_refs.md:475: - docs\pr_templates\PriorWork_complete\PR-038-Pipeline-Randomizer-Config-V2-P1.md:170: In pipeline_config_panel_v2.py:
- pipeline_config_refs.md:1112: - pipeline_config_refs.md:476: - docs\pr_templates\PriorWork_complete\PR-038-Pipeline-Randomizer-Config-V2-P1.md:202: Call pipeline_config_panel.load_randomizer_config(...).
- pipeline_config_refs.md:1113: - pipeline_config_refs.md:477: - docs\pr_templates\PriorWork_complete\PR-038-Pipeline-Randomizer-Config-V2-P1.md:274: pipeline_config_panel_v2.py
- pipeline_config_refs.md:1114: - pipeline_config_refs.md:480: - docs\pr_templates\PriorWork_complete\PR-038A-Pipeline-Randomizer-Config-V2-P1.md:119: src/gui/panels_v2/pipeline_config_panel_v2.py
- pipeline_config_refs.md:1115: - pipeline_config_refs.md:481: - docs\pr_templates\PriorWork_complete\PR-038A-Pipeline-Randomizer-Config-V2-P1.md:170: In pipeline_config_panel_v2.py:
- pipeline_config_refs.md:1116: - pipeline_config_refs.md:482: - docs\pr_templates\PriorWork_complete\PR-038A-Pipeline-Randomizer-Config-V2-P1.md:202: Call pipeline_config_panel.load_randomizer_config(...).
- pipeline_config_refs.md:1117: - pipeline_config_refs.md:483: - docs\pr_templates\PriorWork_complete\PR-038A-Pipeline-Randomizer-Config-V2-P1.md:274: pipeline_config_panel_v2.py
- pipeline_config_refs.md:1118: - pipeline_config_refs.md:486: - docs\pr_templates\PriorWork_complete\PR-041-DESIGN-SYSTEM-THEME-V2-P1.md:187: src/gui/panels_v2/pipeline_config_panel_v2.py
- pipeline_config_refs.md:1119: - pipeline_config_refs.md:489: - docs\pr_templates\PriorWork_complete\PR-041-THEME-V2-DESIGN-TOKENS-UNIFICATION-V2-P1.md:139: src/gui/panels_v2/pipeline_config_panel_v2.py
- pipeline_config_refs.md:1120: - pipeline_config_refs.md:492: - docs\pr_templates\PriorWork_complete\PR-049 — GUI V2 Dropdowns, Payload Builder, & Last-Run.md:100: Add method build_pipeline_config_v2():
- pipeline_config_refs.md:1121: - pipeline_config_refs.md:495: - docs\pr_templates\PriorWork_complete\PR-071-Pipeline-Execution-Wiring-V2-P1-20251201.md:120: def run_pipeline(self, pipeline_config, learning_context=None) -> PipelineResult:
- pipeline_config_refs.md:1122: - pipeline_config_refs.md:496: - docs\pr_templates\PriorWork_complete\PR-071-Pipeline-Execution-Wiring-V2-P1-20251201.md:122: - Validate pipeline_config
- pipeline_config_refs.md:1123: - pipeline_config_refs.md:497: - docs\pr_templates\PriorWork_complete\PR-071-Pipeline-Execution-Wiring-V2-P1-20251201.md:177: self.controller.run_pipeline(self.app_state.build_pipeline_config())
- pipeline_config_refs.md:1124: - pipeline_config_refs.md:500: - docs\pr_templates\PriorWork_complete\PR-072-RunPipeline-Facade-V2-P1-20251202.md:139: Use whatever existing method(s) currently builds a PipelineConfig or equivalent object (e.g., self.app_state.build_pipeline_config() or similar).
- pipeline_config_refs.md:1125: - pipeline_config_refs.md:501: - docs\pr_templates\PriorWork_complete\PR-072-RunPipeline-Facade-V2-P1-20251202.md:167: result = self.pipeline_runner.run(pipeline_config)
- pipeline_config_refs.md:1126: - pipeline_config_refs.md:502: - docs\pr_templates\PriorWork_complete\PR-072-RunPipeline-Facade-V2-P1-20251202.md:258: def run(self, pipeline_config):
- pipeline_config_refs.md:1127: - pipeline_config_refs.md:503: - docs\pr_templates\PriorWork_complete\PR-072-RunPipeline-Facade-V2-P1-20251202.md:259: self.run_calls.append(pipeline_config)
- pipeline_config_refs.md:1128: - pipeline_config_refs.md:504: - docs\pr_templates\PriorWork_complete\PR-072-RunPipeline-Facade-V2-P1-20251202.md:263: The exact shape of pipeline_config doesn’t matter for this PR; tests only care that run was called and resulted in one entry in run_calls.
- pipeline_config_refs.md:1129: - pipeline_config_refs.md:507: - docs\pr_templates\PriorWork_complete\PR-074-Upscale-Pipeline-Logic-V2-P1-20251202.md:395: pipeline_config = self.build_pipeline_config_v2()
- pipeline_config_refs.md:1130: - pipeline_config_refs.md:508: - docs\pr_templates\PriorWork_complete\PR-074-Upscale-Pipeline-Logic-V2-P1-20251202.md:399: return runner.run(pipeline_config, None, self._append_log_threadsafe)
- pipeline_config_refs.md:1131: - pipeline_config_refs.md:511: - docs\pr_templates\PriorWork_complete\PR-078-Journey-Test-API-Shims-V2-P1-20251202.md:20: Ensure JT05 and the V2 full-pipeline journey set a minimal valid RunConfig (model, sampler, steps) so AppController.run_pipeline() passes _validate_pipeline_config() and actually calls the runner/WebUI mocks.
- pipeline_config_refs.md:1132: - pipeline_config_refs.md:514: - docs\pr_templates\PriorWork_complete\PR-081D-4 — RunConfig Refiner-Hires Fields.md:44: src/gui/panels_v2/pipeline_config_panel_v2.py
- pipeline_config_refs.md:1133: - pipeline_config_refs.md:517: - docs\pr_templates\PriorWork_complete\PR-081D-7 — GUI Harness Cleanup Pytest Marker.md:34: src/gui/panels_v2/pipeline_config_panel_v2.py  (checkbox order if required)
- pipeline_config_refs.md:1134: - pipeline_config_refs.md:520: - docs\pr_templates\PriorWork_complete\PR-087 – Controller RunConfig & GUI Entrypoint Wiring (V2.5).md:88: tests/controller/test_app_controller_pipeline_integration.py::test_pipeline_config_assembled_from_controller_state
- pipeline_config_refs.md:1135: - pipeline_config_refs.md:521: - docs\pr_templates\PriorWork_complete\PR-087 – Controller RunConfig & GUI Entrypoint Wiring (V2.5).md:148: Ensure that the method assembling pipeline config (e.g. AppController._assemble_pipeline_config() or call into pipeline_config_assembler) consumes RunConfig correctly.
- pipeline_config_refs.md:1136: - pipeline_config_refs.md:522: - docs\pr_templates\PriorWork_complete\PR-087 – Controller RunConfig & GUI Entrypoint Wiring (V2.5).md:150: Fix test_pipeline_config_assembled_from_controller_state by:
- pipeline_config_refs.md:1137: - pipeline_config_refs.md:523: - docs\pr_templates\PriorWork_complete\PR-087 – Controller RunConfig & GUI Entrypoint Wiring (V2.5).md:284: test_pipeline_config_assembled_from_controller_state sees a correctly assembled pipeline config derived from run_config.
- pipeline_config_refs.md:1138: - pipeline_config_refs.md:524: - docs\pr_templates\PriorWork_complete\PR-087 – Controller RunConfig & GUI Entrypoint Wiring (V2.5).md:338: test_pipeline_config_assembled_from_controller_state
- pipeline_config_refs.md:1139: - pipeline_config_refs.md:527: - docs\pr_templates\PriorWork_complete\PR-107 – StageSequencer + StageExecutionPlan Backbone.md:23: StageSequencer.build_plan(pipeline_config) becomes the single place where we:
- pipeline_config_refs.md:1140: - pipeline_config_refs.md:528: - docs\pr_templates\PriorWork_complete\PR-107 – StageSequencer + StageExecutionPlan Backbone.md:25: Interpret the high-level pipeline_config.
- pipeline_config_refs.md:1141: - pipeline_config_refs.md:529: - docs\pr_templates\PriorWork_complete\PR-107 – StageSequencer + StageExecutionPlan Backbone.md:146: 4. StageSequencer.build_plan(pipeline_config)
- pipeline_config_refs.md:1142: - pipeline_config_refs.md:530: - docs\pr_templates\PriorWork_complete\PR-107 – StageSequencer + StageExecutionPlan Backbone.md:153: def build_plan(self, pipeline_config: Mapping[str, Any]) -> StageExecutionPlan:
- pipeline_config_refs.md:1143: - pipeline_config_refs.md:531: - docs\pr_templates\PriorWork_complete\PR-107 – StageSequencer + StageExecutionPlan Backbone.md:156: 4.1 Expected pipeline_config inputs
- pipeline_config_refs.md:1144: - pipeline_config_refs.md:532: - docs\pr_templates\PriorWork_complete\PR-107 – StageSequencer + StageExecutionPlan Backbone.md:162: pipeline_config["txt2img_enabled"]  # bool
- pipeline_config_refs.md:1145: - pipeline_config_refs.md:533: - docs\pr_templates\PriorWork_complete\PR-107 – StageSequencer + StageExecutionPlan Backbone.md:163: pipeline_config["img2img_enabled"]  # bool
- pipeline_config_refs.md:1146: - pipeline_config_refs.md:534: - docs\pr_templates\PriorWork_complete\PR-107 – StageSequencer + StageExecutionPlan Backbone.md:168: pipeline_config["upscale_enabled"]
- pipeline_config_refs.md:1147: - pipeline_config_refs.md:535: - docs\pr_templates\PriorWork_complete\PR-107 – StageSequencer + StageExecutionPlan Backbone.md:169: pipeline_config["adetailer_enabled"]
- pipeline_config_refs.md:1148: - pipeline_config_refs.md:536: - docs\pr_templates\PriorWork_complete\PR-107 – StageSequencer + StageExecutionPlan Backbone.md:174: pipeline_config["refiner_enabled"]
- pipeline_config_refs.md:1149: - pipeline_config_refs.md:537: - docs\pr_templates\PriorWork_complete\PR-107 – StageSequencer + StageExecutionPlan Backbone.md:175: pipeline_config["refiner_model_name"]
- pipeline_config_refs.md:1150: - pipeline_config_refs.md:538: - docs\pr_templates\PriorWork_complete\PR-107 – StageSequencer + StageExecutionPlan Backbone.md:176: pipeline_config["refiner_switch_step"]
- pipeline_config_refs.md:1151: - pipeline_config_refs.md:539: - docs\pr_templates\PriorWork_complete\PR-107 – StageSequencer + StageExecutionPlan Backbone.md:178: pipeline_config["hires_enabled"]
- pipeline_config_refs.md:1152: - pipeline_config_refs.md:540: - docs\pr_templates\PriorWork_complete\PR-107 – StageSequencer + StageExecutionPlan Backbone.md:179: pipeline_config["hires_upscaler_name"]
- pipeline_config_refs.md:1153: - pipeline_config_refs.md:541: - docs\pr_templates\PriorWork_complete\PR-107 – StageSequencer + StageExecutionPlan Backbone.md:180: pipeline_config["hires_denoise_strength"]
- pipeline_config_refs.md:1154: - pipeline_config_refs.md:542: - docs\pr_templates\PriorWork_complete\PR-107 – StageSequencer + StageExecutionPlan Backbone.md:181: pipeline_config["hires_scale_factor"]
- pipeline_config_refs.md:1155: - pipeline_config_refs.md:543: - docs\pr_templates\PriorWork_complete\PR-107 – StageSequencer + StageExecutionPlan Backbone.md:194: txt2img_enabled = bool(pipeline_config.get("txt2img_enabled"))
- pipeline_config_refs.md:1156: - pipeline_config_refs.md:544: - docs\pr_templates\PriorWork_complete\PR-107 – StageSequencer + StageExecutionPlan Backbone.md:195: img2img_enabled = bool(pipeline_config.get("img2img_enabled"))
- pipeline_config_refs.md:1157: - pipeline_config_refs.md:545: - docs\pr_templates\PriorWork_complete\PR-107 – StageSequencer + StageExecutionPlan Backbone.md:196: upscale_enabled = bool(pipeline_config.get("upscale_enabled"))
- pipeline_config_refs.md:1158: - pipeline_config_refs.md:546: - docs\pr_templates\PriorWork_complete\PR-107 – StageSequencer + StageExecutionPlan Backbone.md:197: adetailer_enabled = bool(pipeline_config.get("adetailer_enabled"))
- pipeline_config_refs.md:1159: - pipeline_config_refs.md:547: - docs\pr_templates\PriorWork_complete\PR-107 – StageSequencer + StageExecutionPlan Backbone.md:208: config=pipeline_config.get("txt2img_config") or {},
- pipeline_config_refs.md:1160: - pipeline_config_refs.md:548: - docs\pr_templates\PriorWork_complete\PR-107 – StageSequencer + StageExecutionPlan Backbone.md:222: config=pipeline_config.get("img2img_config") or {},
- pipeline_config_refs.md:1161: - pipeline_config_refs.md:549: - docs\pr_templates\PriorWork_complete\PR-107 – StageSequencer + StageExecutionPlan Backbone.md:231: config=pipeline_config.get("upscale_config") or {},
- pipeline_config_refs.md:1162: - pipeline_config_refs.md:550: - docs\pr_templates\PriorWork_complete\PR-107 – StageSequencer + StageExecutionPlan Backbone.md:238: config=pipeline_config.get("adetailer_config") or {},
- pipeline_config_refs.md:1163: - pipeline_config_refs.md:551: - docs\pr_templates\PriorWork_complete\PR-107 – StageSequencer + StageExecutionPlan Backbone.md:278: def run(self, pipeline_config: Mapping[str, Any]) -> RunResult:
- pipeline_config_refs.md:1164: - pipeline_config_refs.md:552: - docs\pr_templates\PriorWork_complete\PR-107 – StageSequencer + StageExecutionPlan Backbone.md:458: StageSequencer.build_plan(pipeline_config):
- pipeline_config_refs.md:1165: - pipeline_config_refs.md:553: - docs\pr_templates\PriorWork_complete\PR-107 – StageSequencer + StageExecutionPlan Backbone.md:482: Once this lands, the stage pipeline becomes deterministic and auditable: controllers and jobs feed a single pipeline_config → StageSequencer.build_plan → PipelineRunner.run(plan) chain, and every change to stage ordering or refiner/hires logic can be tested in isolation.
- pipeline_config_refs.md:1166: - pipeline_config_refs.md:556: - docs\pr_templates\PriorWork_complete\PR-B — Canonical JobPart-JobBundle + Builder (V2.5).md:344: test_pipeline_config_snapshot_basic_defaults:
- pipeline_config_refs.md:1167: - pipeline_config_refs.md:557: - docs\pr_templates\PriorWork_complete\PR-B — Canonical JobPart-JobBundle + Builder (V2.5).md:348: test_pipeline_config_snapshot_copy_with_overrides:
- pipeline_config_refs.md:1168: - pipeline_config_refs.md:558: - docs\pr_templates\PriorWork_complete\PR-B — Canonical JobPart-JobBundle + Builder (V2.5).md:477: test_pipeline_config_snapshot_basic_defaults
- pipeline_config_refs.md:1169: - pipeline_config_refs.md:559: - docs\pr_templates\PriorWork_complete\PR-B — Canonical JobPart-JobBundle + Builder (V2.5).md:479: test_pipeline_config_snapshot_copy_with_overrides
- pipeline_config_refs.md:1170: - pipeline_config_refs.md:562: - docs\pr_templates\PriorWork_complete\PR-GUI-V2-MIGRATION-003_Real_Pipeline_Config_Behavior.md:62: - tests/gui_v2/test_gui_v2_pipeline_config_roundtrip.py (new)
- pipeline_config_refs.md:1171: - pipeline_config_refs.md:563: - docs\pr_templates\PriorWork_complete\PR-GUI-V2-MIGRATION-003_Real_Pipeline_Config_Behavior.md:160: 2) tests/gui_v2/test_gui_v2_pipeline_config_roundtrip.py (new)
- pipeline_config_refs.md:1172: - pipeline_config_refs.md:564: - docs\pr_templates\PriorWork_complete\PR-GUI-V2-MIGRATION-003_Real_Pipeline_Config_Behavior.md:227: - tests/gui_v2/test_gui_v2_pipeline_config_roundtrip.py
- pipeline_config_refs.md:1173: - pipeline_config_refs.md:567: - docs\pr_templates\PriorWork_complete\PR-GUI-V2-MIGRATION-004_StatusBarV2_Progress_ETA.md:276: - Existing GUI V2 tests (`test_gui_v2_layout_skeleton.py`, `test_gui_v2_pipeline_button_wiring.py`, `test_gui_v2_pipeline_config_roundtrip.py`, `test_gui_v2_startup.py`) still pass.
- pipeline_config_refs.md:1174: - pipeline_config_refs.md:570: - docs\pr_templates\PriorWork_complete\PR-GUI-V2-NAMING-003_V2-P1.md:60: 9. `src/gui/views/pipeline_config_panel.py`
- pipeline_config_refs.md:1175: - pipeline_config_refs.md:571: - docs\pr_templates\PriorWork_complete\PR-GUI-V2-NAMING-003_V2-P1.md:61: → `src/gui/views/pipeline_config_panel_v2.py`
- pipeline_config_refs.md:1176: - pipeline_config_refs.md:572: - docs\pr_templates\PriorWork_complete\PR-GUI-V2-NAMING-003_V2-P1.md:102: from .pipeline_config_panel import PipelineConfigPanel  # noqa: F401
- pipeline_config_refs.md:1177: - pipeline_config_refs.md:573: - docs\pr_templates\PriorWork_complete\PR-GUI-V2-NAMING-003_V2-P1.md:113: from .pipeline_config_panel_v2 import PipelineConfigPanel  # noqa: F401
- pipeline_config_refs.md:1178: - pipeline_config_refs.md:576: - docs\pr_templates\PriorWork_complete\PR-GUI-V2-PIPELINE-CONFIG-WIRING-002-(2025-11-26).md:11: src/pipeline/pipeline_config_assembler.py
- pipeline_config_refs.md:1179: - pipeline_config_refs.md:577: - docs\pr_templates\PriorWork_complete\PR-GUI-V2-PIPELINE-CONFIG-WIRING-002-(2025-11-26).md:29: PipelineController._build_pipeline_config_from_state() uses that state to call
- pipeline_config_refs.md:1180: - pipeline_config_refs.md:578: - docs\pr_templates\PriorWork_complete\PR-GUI-V2-PIPELINE-CONFIG-WIRING-002-(2025-11-26).md:67: Ensure PipelineController._build_pipeline_config_from_state() produces a fully populated PipelineConfig by calling:
- pipeline_config_refs.md:1181: - pipeline_config_refs.md:579: - docs\pr_templates\PriorWork_complete\PR-GUI-V2-PIPELINE-CONFIG-WIRING-002-(2025-11-26).md:127: def _build_pipeline_config_from_state(self) -> PipelineConfig:
- pipeline_config_refs.md:1182: - pipeline_config_refs.md:580: - docs\pr_templates\PriorWork_complete\PR-GUI-V2-PIPELINE-CONFIG-WIRING-002-(2025-11-26).md:345: In PipelineController._build_pipeline_config_from_state() or before run_pipeline:
- pipeline_config_refs.md:1183: - pipeline_config_refs.md:581: - docs\pr_templates\PriorWork_complete\PR-GUI-V2-PIPELINE-CONFIG-WIRING-002-(2025-11-26).md:450: _build_pipeline_config_from_state() yields correct overrides.
- pipeline_config_refs.md:1184: - pipeline_config_refs.md:584: - docs\pr_templates\PriorWork_complete\PR-GUI-V2-PIPELINE-STAGECARDS-001-Wire Cards-11-26-2025-0816.md:368: controller.update_pipeline_config(cfg)
- pipeline_config_refs.md:1185: - pipeline_config_refs.md:587: - docs\pr_templates\PriorWork_complete\PR-GUI-V2-PIPELINE-TAB-002.md:266: - `src/gui/views/pipeline_config_panel.py` (new):
- pipeline_config_refs.md:1186: - pipeline_config_refs.md:590: - docs\pr_templates\PriorWork_complete\PR-LEARN-PROFILES-001-Model & LoRA Profile Sidecars as Priors for Learning.md:335: def build_pipeline_config_with_profiles(
- pipeline_config_refs.md:1187: - pipeline_config_refs.md:591: - docs\pr_templates\PriorWork_complete\PR-LEARN-PROFILES-001-Model & LoRA Profile Sidecars as Priors for Learning.md:411: test_build_pipeline_config_with_profiles_applies_suggested_preset
- pipeline_config_refs.md:1188: - pipeline_config_refs.md:592: - docs\pr_templates\PriorWork_complete\PR-LEARN-PROFILES-001-Model & LoRA Profile Sidecars as Priors for Learning.md:415: Call build_pipeline_config_with_profiles and assert the resulting PipelineConfig matches those values, absent user overrides.
- pipeline_config_refs.md:1189: - pipeline_config_refs.md:593: - docs\pr_templates\PriorWork_complete\PR-LEARN-PROFILES-001-Model & LoRA Profile Sidecars as Priors for Learning.md:417: test_build_pipeline_config_with_profiles_respects_user_overrides
- pipeline_config_refs.md:1190: - pipeline_config_refs.md:594: - docs\pr_templates\PriorWork_complete\PR-LEARN-PROFILES-001-Model & LoRA Profile Sidecars as Priors for Learning.md:421: test_build_pipeline_config_with_profiles_falls_back_without_profiles
- pipeline_config_refs.md:1191: - pipeline_config_refs.md:595: - docs\pr_templates\PriorWork_complete\PR-LEARN-PROFILES-001-Model & LoRA Profile Sidecars as Priors for Learning.md:441: pytest tests/learning/test_profile_integration.py::test_build_pipeline_config_with_profiles_applies_suggested_preset -v
- pipeline_config_refs.md:1192: - pipeline_config_refs.md:596: - docs\pr_templates\PriorWork_complete\PR-LEARN-PROFILES-001-Model & LoRA Profile Sidecars as Priors for Learning.md:443: pytest tests/learning/test_profile_integration.py::test_build_pipeline_config_with_profiles_respects_user_overrides -v
- pipeline_config_refs.md:1193: - pipeline_config_refs.md:597: - docs\pr_templates\PriorWork_complete\PR-LEARN-PROFILES-001-Model & LoRA Profile Sidecars as Priors for Learning.md:445: pytest tests/learning/test_profile_integration.py::test_build_pipeline_config_with_profiles_falls_back_without_profiles -v
- pipeline_config_refs.md:1194: - pipeline_config_refs.md:598: - docs\pr_templates\PriorWork_complete\PR-LEARN-PROFILES-001-Model & LoRA Profile Sidecars as Priors for Learning.md:471: build_pipeline_config_with_profiles:
- pipeline_config_refs.md:1195: - pipeline_config_refs.md:599: - docs\pr_templates\PriorWork_complete\PR-LEARN-PROFILES-001-Model & LoRA Profile Sidecars as Priors for Learning.md:579: Call build_pipeline_config_with_profiles and:
- pipeline_config_refs.md:1196: - pipeline_config_refs.md:600: - docs\pr_templates\PriorWork_complete\PR-LEARN-PROFILES-001-Model & LoRA Profile Sidecars as Priors for Learning.md:591: Call build_pipeline_config_with_profiles.
- pipeline_config_refs.md:1197: - pipeline_config_refs.md:603: - docs\pr_templates\PriorWork_complete\PR-LEARN-V2-RECORDWRITER-001_pipeline_learningrecord_integration.md:114: pipeline_config: PipelineConfig,
- pipeline_config_refs.md:1198: - pipeline_config_refs.md:606: - docs\pr_templates\PriorWork_complete\PR-PIPE-CORE-01_Addendum_Bundle\PR-PIPE-CORE-01_Addendum_PipelineRunner_Location_and_Construction.md:92: - Call `self._pipeline_runner.run(pipeline_config, self._cancel_token)` in the worker thread.
- pipeline_config_refs.md:1199: - pipeline_config_refs.md:609: - docs\pr_templates\PriorWork_complete\PR-QUEUE-V2-JOBMODEL-001_queue_model_and_single_node_runner_skeleton.md:97: pipeline_config: PipelineConfig
- pipeline_config_refs.md:1200: - pipeline_config_refs.md:612: - docs\pr_templates\PriorWork_complete\PR-WIRE-01-V2.5 – “Minimal Happy Path”-11-26-2025-1918.md:36: - Various V2 panels (e.g., `core_config_panel_v2.py`, `model_manager_panel_v2.py`, `pipeline_config_panel_v2.py`, `prompt_editor_panel_v2.py`, `status_bar_v2.py`, etc.)
- pipeline_config_refs.md:1201: - pipeline_config_refs.md:613: - docs\pr_templates\PriorWork_complete\PR-WIRE-01-V2.5 – “Minimal Happy Path”-11-26-2025-1918.md:169: - For example, something like `run_pipeline(pipeline_config)` or `execute_txt2img(config)`.
- pipeline_config_refs.md:1202: - pipeline_config_refs.md:616: - docs\pr_templates\PriorWork_complete\PR-WIRE-02-V2.5 – Entrypoint Contracts (11-26-2025-1916).md:31: - `tests/gui_v2/test_gui_v2_pipeline_config_roundtrip.py::test_pipeline_panel_loads_initial_config`
- pipeline_config_refs.md:1203: - pipeline_config_refs.md:617: - docs\pr_templates\PriorWork_complete\PR-WIRE-02-V2.5 – Entrypoint Contracts (11-26-2025-1916).md:32: - `tests/gui_v2/test_gui_v2_pipeline_config_roundtrip.py::test_pipeline_panel_run_roundtrip`
- pipeline_config_refs.md:1204: - pipeline_config_refs.md:618: - docs\pr_templates\PriorWork_complete\PR-WIRE-02-V2.5 – Entrypoint Contracts (11-26-2025-1916).md:73: - `tests/gui_v2/test_gui_v2_pipeline_config_roundtrip.py`
- pipeline_config_refs.md:1205: - pipeline_config_refs.md:619: - docs\pr_templates\PriorWork_complete\PR-WIRE-02-V2.5 – Entrypoint Contracts (11-26-2025-1916).md:238: pytest tests/gui_v2/test_gui_v2_pipeline_config_roundtrip.py -q
- pipeline_config_refs.md:1206: - pipeline_config_refs.md:622: - docs\pr_templates\PriorWork_complete\PR-WIRE-03-V2.5-11-26-2025.md:89: - `src/gui/pipeline_config_panel_v2.py` or equivalent PipelinePanelV2 implementation.
- pipeline_config_refs.md:1207: - pipeline_config_refs.md:623: - docs\pr_templates\PriorWork_complete\PR-WIRE-03-V2.5-11-26-2025.md:172: Inspect src/gui/pipeline_config_panel_v2.py (or wherever PipelinePanelV2 is implemented):
- pipeline_config_refs.md:1208: - pipeline_config_refs.md:626: - docs\pr_templates\PriorWork_complete\Script for PR-#51 – Core Config Panel V2.md:38: src/controller/pipeline_config_assembler.py
- pipeline_config_refs.md:1209: - pipeline_config_refs.md:627: - docs\pr_templates\PriorWork_complete\Script for PR-#51 – Core Config Panel V2.md:46: tests/controller/test_pipeline_config_assembler_core_fields.py (new or extend existing)
- pipeline_config_refs.md:1210: - pipeline_config_refs.md:628: - docs\pr_templates\PriorWork_complete\Script for PR-#51 – Core Config Panel V2.md:138: In pipeline_config_assembler.py:
- pipeline_config_refs.md:1211: - pipeline_config_refs.md:629: - docs\pr_templates\PriorWork_complete\Script for PR-#51 – Core Config Panel V2.md:160: pytest tests/controller/test_pipeline_config_assembler_core_fields.py -v
- pipeline_config_refs.md:1212: - pipeline_config_refs.md:630: - docs\pr_templates\PriorWork_complete\Script for PR-#51 – Core Config Panel V2.md:188: pytest tests/controller/test_pipeline_config_assembler_core_fields.py -v
- pipeline_config_refs.md:1213: - pipeline_config_refs.md:633: - docs\pr_templates\PriorWork_complete\Script for PR-#52 – Negative Prompt Panel V2.md:40: src/controller/pipeline_config_assembler.py
- pipeline_config_refs.md:1214: - pipeline_config_refs.md:634: - docs\pr_templates\PriorWork_complete\Script for PR-#52 – Negative Prompt Panel V2.md:48: tests/controller/test_pipeline_config_assembler_negative_prompt.py (new)
- pipeline_config_refs.md:1215: - pipeline_config_refs.md:635: - docs\pr_templates\PriorWork_complete\Script for PR-#52 – Negative Prompt Panel V2.md:114: In pipeline_config_assembler.py:
- pipeline_config_refs.md:1216: - pipeline_config_refs.md:636: - docs\pr_templates\PriorWork_complete\Script for PR-#52 – Negative Prompt Panel V2.md:130: pytest tests/controller/test_pipeline_config_assembler_negative_prompt.py -v
- pipeline_config_refs.md:1217: - pipeline_config_refs.md:637: - docs\pr_templates\PriorWork_complete\Script for PR-#52 – Negative Prompt Panel V2.md:156: pytest tests/controller/test_pipeline_config_assembler_negative_prompt.py -v
- pipeline_config_refs.md:1218: - pipeline_config_refs.md:640: - docs\pr_templates\PriorWork_complete\Script for PR-#54 – Output Settings Panel V2.md:38: src/controller/pipeline_config_assembler.py
- pipeline_config_refs.md:1219: - pipeline_config_refs.md:641: - docs\pr_templates\PriorWork_complete\Script for PR-#54 – Output Settings Panel V2.md:46: tests/controller/test_pipeline_config_assembler_output_settings.py (new)
- pipeline_config_refs.md:1220: - pipeline_config_refs.md:642: - docs\pr_templates\PriorWork_complete\Script for PR-#54 – Output Settings Panel V2.md:112: In pipeline_config_assembler.py:
- pipeline_config_refs.md:1221: - pipeline_config_refs.md:643: - docs\pr_templates\PriorWork_complete\Script for PR-#54 – Output Settings Panel V2.md:128: pytest tests/controller/test_pipeline_config_assembler_output_settings.py -v
- pipeline_config_refs.md:1222: - pipeline_config_refs.md:644: - docs\pr_templates\PriorWork_complete\Script for PR-#54 – Output Settings Panel V2.md:154: pytest tests/controller/test_pipeline_config_assembler_output_settings.py -v
- pipeline_config_refs.md:1223: - pipeline_config_refs.md:647: - docs\pr_templates\PriorWork_complete\Script for PR-#55 – Model Manager Panel V2.md:38: src/controller/pipeline_config_assembler.py
- pipeline_config_refs.md:1224: - pipeline_config_refs.md:648: - docs\pr_templates\PriorWork_complete\Script for PR-#55 – Model Manager Panel V2.md:48: tests/controller/test_pipeline_config_assembler_model_fields.py (new or extend)
- pipeline_config_refs.md:1225: - pipeline_config_refs.md:649: - docs\pr_templates\PriorWork_complete\Script for PR-#55 – Model Manager Panel V2.md:116: In pipeline_config_assembler.py:
- pipeline_config_refs.md:1226: - pipeline_config_refs.md:650: - docs\pr_templates\PriorWork_complete\Script for PR-#55 – Model Manager Panel V2.md:132: pytest tests/controller/test_pipeline_config_assembler_model_fields.py -v
- pipeline_config_refs.md:1227: - pipeline_config_refs.md:651: - docs\pr_templates\PriorWork_complete\Script for PR-#55 – Model Manager Panel V2.md:158: pytest tests/controller/test_pipeline_config_assembler_model_fields.py -v
- pipeline_config_refs.md:1228: - pipeline_config_refs.md:654: - docs\pr_templates\PriorWork_complete\StableNew PR-091 – AppController ↔ PipelineController Bridge.md:220: is_valid, message = self._validate_pipeline_config()
- pipeline_config_refs.md:1229: - pipeline_config_refs.md:655: - docs\pr_templates\PriorWork_complete\StableNew PR-091 – AppController ↔ PipelineController Bridge.md:230: builds pipeline_config via build_pipeline_config_v2(),
- pipeline_config_refs.md:1230: - pipeline_config_refs.md:658: - inventory\stable_v2_inventory.json:519: "tests/controller/__pycache__/test_pipeline_config_assembler.cpython-310-pytest-9.0.1.pyc",
- pipeline_config_refs.md:1231: - pipeline_config_refs.md:659: - inventory\stable_v2_inventory.json:520: "tests/controller/__pycache__/test_pipeline_config_assembler_core_fields.cpython-310-pytest-9.0.1.pyc",
- pipeline_config_refs.md:1232: - pipeline_config_refs.md:660: - inventory\stable_v2_inventory.json:521: "tests/controller/__pycache__/test_pipeline_config_assembler_model_fields.cpython-310-pytest-9.0.1.pyc",
- pipeline_config_refs.md:1233: - pipeline_config_refs.md:661: - inventory\stable_v2_inventory.json:522: "tests/controller/__pycache__/test_pipeline_config_assembler_negative_prompt.cpython-310-pytest-9.0.1.pyc",
- pipeline_config_refs.md:1234: - pipeline_config_refs.md:662: - inventory\stable_v2_inventory.json:523: "tests/controller/__pycache__/test_pipeline_config_assembler_output_settings.cpython-310-pytest-9.0.1.pyc",
- pipeline_config_refs.md:1235: - pipeline_config_refs.md:663: - inventory\stable_v2_inventory.json:524: "tests/controller/__pycache__/test_pipeline_config_assembler_resolution.cpython-310-pytest-9.0.1.pyc",
- pipeline_config_refs.md:1236: - pipeline_config_refs.md:664: - inventory\stable_v2_inventory.json:1587: ".mypy_cache/3.11/src/controller/pipeline_config_assembler.data.json",
- pipeline_config_refs.md:1237: - pipeline_config_refs.md:665: - inventory\stable_v2_inventory.json:1588: ".mypy_cache/3.11/src/controller/pipeline_config_assembler.meta.json",
- pipeline_config_refs.md:1238: - pipeline_config_refs.md:666: - inventory\stable_v2_inventory.json:1843: ".mypy_cache/3.11/tests/controller/test_pipeline_config_assembler.data.json",
- pipeline_config_refs.md:1239: - pipeline_config_refs.md:667: - inventory\stable_v2_inventory.json:1844: ".mypy_cache/3.11/tests/controller/test_pipeline_config_assembler.meta.json",
- pipeline_config_refs.md:1240: - pipeline_config_refs.md:668: - inventory\stable_v2_inventory.json:5538: "htmlcov/z_7da4a89bed7a4ad5_pipeline_config_panel_py.html",
- pipeline_config_refs.md:1241: - pipeline_config_refs.md:669: - inventory\stable_v2_inventory.json:5558: "htmlcov/z_ac5b274346abdaff_pipeline_config_assembler_py.html",
- pipeline_config_refs.md:1242: - pipeline_config_refs.md:670: - inventory\stable_v2_inventory.json:5932: "src/controller/pipeline_config_assembler.py",
- pipeline_config_refs.md:1243: - pipeline_config_refs.md:671: - inventory\stable_v2_inventory.json:6158: "src/gui/views/pipeline_config_panel.py",
- pipeline_config_refs.md:1244: - pipeline_config_refs.md:672: - inventory\stable_v2_inventory.json:6486: "src/gui/views/__pycache__/pipeline_config_panel.cpython-310.pyc",
- pipeline_config_refs.md:1245: - pipeline_config_refs.md:673: - inventory\stable_v2_inventory.json:6574: "tests/controller/test_pipeline_config_assembler.py",
- pipeline_config_refs.md:1246: - pipeline_config_refs.md:674: - inventory\stable_v2_inventory.json:6575: "tests/controller/test_pipeline_config_assembler_core_fields.py",
- pipeline_config_refs.md:1247: - pipeline_config_refs.md:675: - inventory\stable_v2_inventory.json:6576: "tests/controller/test_pipeline_config_assembler_model_fields.py",
- pipeline_config_refs.md:1248: - pipeline_config_refs.md:676: - inventory\stable_v2_inventory.json:6577: "tests/controller/test_pipeline_config_assembler_negative_prompt.py",
- pipeline_config_refs.md:1249: - pipeline_config_refs.md:677: - inventory\stable_v2_inventory.json:6578: "tests/controller/test_pipeline_config_assembler_output_settings.py",
- pipeline_config_refs.md:1250: - pipeline_config_refs.md:678: - inventory\stable_v2_inventory.json:6579: "tests/controller/test_pipeline_config_assembler_resolution.py",
- pipeline_config_refs.md:1251: - pipeline_config_refs.md:679: - inventory\stable_v2_inventory.json:6714: ".mypy_cache/3.11/src/gui/panels_v2/pipeline_config_panel_v2.data.json",
- pipeline_config_refs.md:1252: - pipeline_config_refs.md:680: - inventory\stable_v2_inventory.json:6715: ".mypy_cache/3.11/src/gui/panels_v2/pipeline_config_panel_v2.meta.json",
- pipeline_config_refs.md:1253: - pipeline_config_refs.md:681: - inventory\stable_v2_inventory.json:6748: ".mypy_cache/3.11/src/gui/views/pipeline_config_panel_v2.data.json",
- pipeline_config_refs.md:1254: - pipeline_config_refs.md:682: - inventory\stable_v2_inventory.json:6749: ".mypy_cache/3.11/src/gui/views/pipeline_config_panel_v2.meta.json",
- pipeline_config_refs.md:1255: - pipeline_config_refs.md:683: - inventory\stable_v2_inventory.json:6812: ".mypy_cache/3.11/tests/gui_v2/test_gui_v2_pipeline_config_roundtrip.data.json",
- pipeline_config_refs.md:1256: - pipeline_config_refs.md:684: - inventory\stable_v2_inventory.json:6813: ".mypy_cache/3.11/tests/gui_v2/test_gui_v2_pipeline_config_roundtrip.meta.json",
- pipeline_config_refs.md:1257: - pipeline_config_refs.md:685: - inventory\stable_v2_inventory.json:6944: "htmlcov/z_ac9e25382994b44b_pipeline_config_panel_v2_py.html",
- pipeline_config_refs.md:1258: - pipeline_config_refs.md:686: - inventory\stable_v2_inventory.json:6969: "src/controller/__pycache__/pipeline_config_assembler.cpython-310.pyc",
- pipeline_config_refs.md:1259: - pipeline_config_refs.md:687: - inventory\stable_v2_inventory.json:6999: "src/gui/panels_v2/pipeline_config_panel_v2.py",
- pipeline_config_refs.md:1260: - pipeline_config_refs.md:688: - inventory\stable_v2_inventory.json:7002: "src/gui/panels_v2/__pycache__/pipeline_config_panel_v2.cpython-310.pyc",
- pipeline_config_refs.md:1261: - pipeline_config_refs.md:689: - inventory\stable_v2_inventory.json:7042: "src/gui/views/.mypy_cache/3.11/src/gui/views/pipeline_config_panel_v2.data.json",
- pipeline_config_refs.md:1262: - pipeline_config_refs.md:690: - inventory\stable_v2_inventory.json:7043: "src/gui/views/.mypy_cache/3.11/src/gui/views/pipeline_config_panel_v2.meta.json",
- pipeline_config_refs.md:1263: - pipeline_config_refs.md:691: - inventory\stable_v2_inventory.json:7049: "src/gui/views/__pycache__/pipeline_config_panel_v2.cpython-310.pyc",
- pipeline_config_refs.md:1264: - pipeline_config_refs.md:692: - inventory\stable_v2_inventory.json:7138: "tests/gui_v2/test_pipeline_config_panel_lora_runtime.py",
- pipeline_config_refs.md:1265: - pipeline_config_refs.md:693: - inventory\stable_v2_inventory.json:7180: "tests/gui_v2/__pycache__/test_gui_v2_pipeline_config_roundtrip.cpython-310-pytest-9.0.1.pyc",
- pipeline_config_refs.md:1266: - pipeline_config_refs.md:694: - inventory\stable_v2_inventory.json:7207: "tests/gui_v2/__pycache__/test_pipeline_config_panel_lora_runtime.cpython-310-pytest-9.0.1.pyc",
- pipeline_config_refs.md:1267: - pipeline_config_refs.md:697: - repo_inventory.json:353: "path": "src/controller/pipeline_config_assembler.py",
- pipeline_config_refs.md:1268: - pipeline_config_refs.md:698: - repo_inventory.json:354: "module": "src.controller.pipeline_config_assembler",
- pipeline_config_refs.md:1269: - pipeline_config_refs.md:699: - repo_inventory.json:395: "src.controller.pipeline_config_assembler",
- pipeline_config_refs.md:1270: - pipeline_config_refs.md:700: - repo_inventory.json:1548: "src.gui.pipeline_config_panel",
- pipeline_config_refs.md:1271: - pipeline_config_refs.md:701: - repo_inventory.json:1624: "path": "src/gui/views/pipeline_config_panel.py",
- pipeline_config_refs.md:1272: - pipeline_config_refs.md:702: - repo_inventory.json:1625: "module": "src.gui.views.pipeline_config_panel",
- pipeline_config_refs.md:1273: - pipeline_config_refs.md:703: - repo_inventory.json:2890: "path": "tests/controller/test_pipeline_config_assembler.py",
- pipeline_config_refs.md:1274: - pipeline_config_refs.md:704: - repo_inventory.json:2891: "module": "tests.controller.test_pipeline_config_assembler",
- pipeline_config_refs.md:1275: - pipeline_config_refs.md:705: - repo_inventory.json:2897: "src.controller.pipeline_config_assembler"
- pipeline_config_refs.md:1276: - pipeline_config_refs.md:706: - repo_inventory.json:2902: "path": "tests/controller/test_pipeline_config_assembler_core_fields.py",
- pipeline_config_refs.md:1277: - pipeline_config_refs.md:707: - repo_inventory.json:2903: "module": "tests.controller.test_pipeline_config_assembler_core_fields",
- pipeline_config_refs.md:1278: - pipeline_config_refs.md:708: - repo_inventory.json:2910: "src.controller.pipeline_config_assembler"
- pipeline_config_refs.md:1279: - pipeline_config_refs.md:709: - repo_inventory.json:2915: "path": "tests/controller/test_pipeline_config_assembler_model_fields.py",
- pipeline_config_refs.md:1280: - pipeline_config_refs.md:710: - repo_inventory.json:2916: "module": "tests.controller.test_pipeline_config_assembler_model_fields",
- pipeline_config_refs.md:1281: - pipeline_config_refs.md:711: - repo_inventory.json:2922: "src.controller.pipeline_config_assembler"
- pipeline_config_refs.md:1282: - pipeline_config_refs.md:712: - repo_inventory.json:2927: "path": "tests/controller/test_pipeline_config_assembler_negative_prompt.py",
- pipeline_config_refs.md:1283: - pipeline_config_refs.md:713: - repo_inventory.json:2928: "module": "tests.controller.test_pipeline_config_assembler_negative_prompt",
- pipeline_config_refs.md:1284: - pipeline_config_refs.md:714: - repo_inventory.json:2934: "src.controller.pipeline_config_assembler"
- pipeline_config_refs.md:1285: - pipeline_config_refs.md:715: - repo_inventory.json:2939: "path": "tests/controller/test_pipeline_config_assembler_output_settings.py",
- pipeline_config_refs.md:1286: - pipeline_config_refs.md:716: - repo_inventory.json:2940: "module": "tests.controller.test_pipeline_config_assembler_output_settings",
- pipeline_config_refs.md:1287: - pipeline_config_refs.md:717: - repo_inventory.json:2946: "src.controller.pipeline_config_assembler"
- pipeline_config_refs.md:1288: - pipeline_config_refs.md:718: - repo_inventory.json:2951: "path": "tests/controller/test_pipeline_config_assembler_resolution.py",
- pipeline_config_refs.md:1289: - pipeline_config_refs.md:719: - repo_inventory.json:2952: "module": "tests.controller.test_pipeline_config_assembler_resolution",
- pipeline_config_refs.md:1290: - pipeline_config_refs.md:720: - repo_inventory.json:2958: "src.controller.pipeline_config_assembler"
- pipeline_config_refs.md:1291: - pipeline_config_refs.md:721: - repo_inventory.json:2973: "src.controller.pipeline_config_assembler",
- pipeline_config_refs.md:1292: - pipeline_config_refs.md:722: - repo_inventory.json:3302: "path": "tests/gui_v2/test_gui_v2_pipeline_config_roundtrip.py",
- pipeline_config_refs.md:1293: - pipeline_config_refs.md:723: - repo_inventory.json:3303: "module": "tests.gui_v2.test_gui_v2_pipeline_config_roundtrip",
- pipeline_config_refs.md:1294: - pipeline_config_refs.md:726: - reports\file_access\CLEANHOUSE_REPORT_V2_5_2025_11_26.md:30: - `src/controller/pipeline_config_assembler.py` | touched: false | reachable_from_main: true
- pipeline_config_refs.md:1295: - pipeline_config_refs.md:727: - reports\file_access\CLEANHOUSE_REPORT_V2_5_2025_11_26.md:164: - `tests/controller/test_pipeline_config_assembler.py` | touched: false | reachable_from_main: false | TEST
- pipeline_config_refs.md:1296: - pipeline_config_refs.md:728: - reports\file_access\CLEANHOUSE_REPORT_V2_5_2025_11_26.md:165: - `tests/controller/test_pipeline_config_assembler_core_fields.py` | touched: false | reachable_from_main: false | TEST
- pipeline_config_refs.md:1297: - pipeline_config_refs.md:729: - reports\file_access\CLEANHOUSE_REPORT_V2_5_2025_11_26.md:166: - `tests/controller/test_pipeline_config_assembler_model_fields.py` | touched: false | reachable_from_main: false | TEST
- pipeline_config_refs.md:1298: - pipeline_config_refs.md:730: - reports\file_access\CLEANHOUSE_REPORT_V2_5_2025_11_26.md:167: - `tests/controller/test_pipeline_config_assembler_negative_prompt.py` | touched: false | reachable_from_main: false | TEST
- pipeline_config_refs.md:1299: - pipeline_config_refs.md:731: - reports\file_access\CLEANHOUSE_REPORT_V2_5_2025_11_26.md:168: - `tests/controller/test_pipeline_config_assembler_output_settings.py` | touched: false | reachable_from_main: false | TEST
- pipeline_config_refs.md:1300: - pipeline_config_refs.md:732: - reports\file_access\CLEANHOUSE_REPORT_V2_5_2025_11_26.md:169: - `tests/controller/test_pipeline_config_assembler_resolution.py` | touched: false | reachable_from_main: false | TEST
- pipeline_config_refs.md:1301: - pipeline_config_refs.md:733: - reports\file_access\CLEANHOUSE_REPORT_V2_5_2025_11_26.md:228: - `tests/gui_v2/test_gui_v2_pipeline_config_roundtrip.py` | touched: false | reachable_from_main: false | TEST
- pipeline_config_refs.md:1302: - pipeline_config_refs.md:736: - reports\file_access\file_access_summary.csv:28: src/controller/pipeline_config_assembler.py,false,,true,true,false,false,false,A_RUNTIME_CORE,
- pipeline_config_refs.md:1303: - pipeline_config_refs.md:737: - reports\file_access\file_access_summary.csv:152: tests/controller/test_pipeline_config_assembler.py,false,,false,false,true,false,false,C_TEST,
- pipeline_config_refs.md:1304: - pipeline_config_refs.md:738: - reports\file_access\file_access_summary.csv:153: tests/controller/test_pipeline_config_assembler_core_fields.py,false,,false,false,true,false,false,C_TEST,
- pipeline_config_refs.md:1305: - pipeline_config_refs.md:739: - reports\file_access\file_access_summary.csv:154: tests/controller/test_pipeline_config_assembler_model_fields.py,false,,false,false,true,false,false,C_TEST,
- pipeline_config_refs.md:1306: - pipeline_config_refs.md:740: - reports\file_access\file_access_summary.csv:155: tests/controller/test_pipeline_config_assembler_negative_prompt.py,false,,false,false,true,false,false,C_TEST,
- pipeline_config_refs.md:1307: - pipeline_config_refs.md:741: - reports\file_access\file_access_summary.csv:156: tests/controller/test_pipeline_config_assembler_output_settings.py,false,,false,false,true,false,false,C_TEST,
- pipeline_config_refs.md:1308: - pipeline_config_refs.md:742: - reports\file_access\file_access_summary.csv:157: tests/controller/test_pipeline_config_assembler_resolution.py,false,,false,false,true,false,false,C_TEST,
- pipeline_config_refs.md:1309: - pipeline_config_refs.md:743: - reports\file_access\file_access_summary.csv:216: tests/gui_v2/test_gui_v2_pipeline_config_roundtrip.py,false,,false,false,true,false,false,C_TEST,
- pipeline_config_refs.md:1310: - pipeline_config_refs.md:745: ## scripts\list_pipeline_config_refs.py
- pipeline_config_refs.md:1311: - pipeline_config_refs.md:746: - scripts\list_pipeline_config_refs.py:3: Generate pipeline_config_refs.md listing all occurrences of "pipeline_config"
- pipeline_config_refs.md:1312: - pipeline_config_refs.md:747: - scripts\list_pipeline_config_refs.py:16: OUTPUT = ROOT / "pipeline_config_refs.md"
- pipeline_config_refs.md:1313: - pipeline_config_refs.md:748: - scripts\list_pipeline_config_refs.py:21: "pipeline_config",
- pipeline_config_refs.md:1314: - pipeline_config_refs.md:749: - scripts\list_pipeline_config_refs.py:53: f.write("# pipeline_config references (excluding archive/.git/zip)\n\n")
- pipeline_config_refs.md:1315: - pipeline_config_refs.md:752: - snapshots\repo_inventory.json:773: "path": "archive/legacy_tests/tests_gui_v2_legacy/test_gui_v2_pipeline_config_roundtrip.py",
- pipeline_config_refs.md:1316: - pipeline_config_refs.md:753: - snapshots\repo_inventory.json:5393: "path": "src/controller/pipeline_config_assembler.py",
- pipeline_config_refs.md:1317: - pipeline_config_refs.md:754: - snapshots\repo_inventory.json:5703: "path": "src/gui/panels_v2/pipeline_config_panel_v2.py",
- pipeline_config_refs.md:1318: - pipeline_config_refs.md:755: - snapshots\repo_inventory.json:5843: "path": "src/gui/views/pipeline_config_panel.py",
- pipeline_config_refs.md:1319: - pipeline_config_refs.md:756: - snapshots\repo_inventory.json:6813: "path": "tests/controller/test_pipeline_config_assembler.py",
- pipeline_config_refs.md:1320: - pipeline_config_refs.md:757: - snapshots\repo_inventory.json:6818: "path": "tests/controller/test_pipeline_config_assembler_core_fields.py",
- pipeline_config_refs.md:1321: - pipeline_config_refs.md:758: - snapshots\repo_inventory.json:6823: "path": "tests/controller/test_pipeline_config_assembler_model_fields.py",
- pipeline_config_refs.md:1322: - pipeline_config_refs.md:759: - snapshots\repo_inventory.json:6828: "path": "tests/controller/test_pipeline_config_assembler_negative_prompt.py",
- pipeline_config_refs.md:1323: - pipeline_config_refs.md:760: - snapshots\repo_inventory.json:6833: "path": "tests/controller/test_pipeline_config_assembler_output_settings.py",
- pipeline_config_refs.md:1324: - pipeline_config_refs.md:761: - snapshots\repo_inventory.json:6838: "path": "tests/controller/test_pipeline_config_assembler_resolution.py",
- pipeline_config_refs.md:1325: - pipeline_config_refs.md:762: - snapshots\repo_inventory.json:7148: "path": "tests/gui_v2/test_pipeline_config_panel_lora_runtime.py",
- pipeline_config_refs.md:1326: - pipeline_config_refs.md:765: - src\controller\app_controller.py:764: "error": "Job is missing normalized_record; legacy/pipeline_config execution is disabled.",
- pipeline_config_refs.md:1327: - pipeline_config_refs.md:766: - src\controller\app_controller.py:1247: def _validate_pipeline_config(self) -> tuple[bool, str]:
- pipeline_config_refs.md:1328: - pipeline_config_refs.md:767: - src\controller\app_controller.py:1258: panel = getattr(self.main_window, "pipeline_config_panel_v2", None)
- pipeline_config_refs.md:1329: - pipeline_config_refs.md:768: - src\controller\app_controller.py:1494: def _execute_pipeline_via_runner(self, pipeline_config: PipelineConfig) -> Any:
- pipeline_config_refs.md:1330: - pipeline_config_refs.md:769: - src\controller\app_controller.py:1498: def _run_pipeline_from_tab(self, pipeline_tab: Any, pipeline_config: PipelineConfig) -> Any:
- pipeline_config_refs.md:1331: - pipeline_config_refs.md:770: - src\controller\app_controller.py:1594: def _run_pipeline_via_runner_only(self, pipeline_config: PipelineConfig) -> Any:
- pipeline_config_refs.md:1332: - pipeline_config_refs.md:771: - src\controller\app_controller.py:1665: is_valid, message = self._validate_pipeline_config()
- pipeline_config_refs.md:1333: - pipeline_config_refs.md:772: - src\controller\app_controller.py:1710: pipeline_config = self.build_pipeline_config_v2()
- pipeline_config_refs.md:1334: - pipeline_config_refs.md:773: - src\controller\app_controller.py:1712: executor_config = self.pipeline_runner._build_executor_config(pipeline_config)
- pipeline_config_refs.md:1335: - pipeline_config_refs.md:774: - src\controller\app_controller.py:1713: self._cache_last_run_payload(executor_config, pipeline_config)
- pipeline_config_refs.md:1336: - pipeline_config_refs.md:775: - src\controller\app_controller.py:1714: self.pipeline_runner.run(pipeline_config, cancel_token, self._append_log_threadsafe)
- pipeline_config_refs.md:1337: - pipeline_config_refs.md:776: - src\controller\app_controller.py:1734: def _cache_last_run_payload(self, executor_config: dict[str, Any], pipeline_config: PipelineConfig) -> None:
- pipeline_config_refs.md:1338: - pipeline_config_refs.md:777: - src\controller\app_controller.py:1741: "prompt": pipeline_config.prompt,
- pipeline_config_refs.md:1339: - pipeline_config_refs.md:778: - src\controller\app_controller.py:1742: "pack_name": pipeline_config.pack_name,
- pipeline_config_refs.md:1340: - pipeline_config_refs.md:779: - src\controller\app_controller.py:1743: "preset_name": pipeline_config.preset_name,
- pipeline_config_refs.md:1341: - pipeline_config_refs.md:780: - src\controller\app_controller.py:1822: pipeline_panel = getattr(self.main_window, "pipeline_config_panel_v2", None)
- pipeline_config_refs.md:1342: - pipeline_config_refs.md:781: - src\controller\app_controller.py:2139: pipeline_config_panel = getattr(self.main_window, "pipeline_config_panel_v2", None)
- pipeline_config_refs.md:1343: - pipeline_config_refs.md:782: - src\controller\app_controller.py:2140: if pipeline_config_panel and hasattr(pipeline_config_panel, "apply_run_config"):
- pipeline_config_refs.md:1344: - pipeline_config_refs.md:783: - src\controller\app_controller.py:2142: pipeline_config_panel.apply_run_config(preset_config)
- pipeline_config_refs.md:1345: - pipeline_config_refs.md:784: - src\controller\app_controller.py:2413: def build_pipeline_config_v2(self) -> PipelineConfig:
- pipeline_config_refs.md:1346: - pipeline_config_refs.md:785: - src\controller\app_controller.py:2415: return self._build_pipeline_config()
- pipeline_config_refs.md:1347: - pipeline_config_refs.md:786: - src\controller\app_controller.py:2417: def _build_pipeline_config(self) -> PipelineConfig:
- pipeline_config_refs.md:1348: - pipeline_config_refs.md:787: - src\controller\app_controller.py:2695: panel = getattr(self.main_window, "pipeline_config_panel_v2", None)
- pipeline_config_refs.md:1349: - pipeline_config_refs.md:788: - src\controller\app_controller.py:2810: pipeline_config_panel = getattr(self.main_window, "pipeline_config_panel_v2", None)
- pipeline_config_refs.md:1350: - pipeline_config_refs.md:789: - src\controller\app_controller.py:2811: if pipeline_config_panel and hasattr(pipeline_config_panel, "apply_run_config"):
- pipeline_config_refs.md:1351: - pipeline_config_refs.md:790: - src\controller\app_controller.py:2813: pipeline_config_panel.apply_run_config(pack_config)
- pipeline_config_refs.md:1352: - pipeline_config_refs.md:791: - src\controller\app_controller.py:3041: pipeline_config_panel = getattr(self.main_window, "pipeline_config_panel_v2", None)
- pipeline_config_refs.md:1353: - pipeline_config_refs.md:792: - src\controller\app_controller.py:3042: if pipeline_config_panel and hasattr(pipeline_config_panel, "apply_run_config"):
- pipeline_config_refs.md:1354: - pipeline_config_refs.md:793: - src\controller\app_controller.py:3044: pipeline_config_panel.apply_run_config(preset_config)
- pipeline_config_refs.md:1355: - pipeline_config_refs.md:796: - src\controller\job_history_service.py:223: Prefers NJR snapshot data. Legacy pipeline_config-only jobs no longer
- pipeline_config_refs.md:1356: - pipeline_config_refs.md:799: - src\controller\job_service.py:305: # PR-CORE1-B3/C2: NJR-backed jobs are purely NJR-only and don't store pipeline_config.
- pipeline_config_refs.md:1357: - pipeline_config_refs.md:802: - src\controller\pipeline_controller.py:35: from src.pipeline.legacy_njr_adapter import build_njr_from_legacy_pipeline_config
- pipeline_config_refs.md:1358: - pipeline_config_refs.md:803: - src\controller\pipeline_controller.py:50: from src.controller.pipeline_config_assembler import PipelineConfigAssembler, GuiOverrides, RunPlan, PlannedJob
- pipeline_config_refs.md:1359: - pipeline_config_refs.md:804: - src\controller\pipeline_controller.py:194: def _build_pipeline_config_from_state(self) -> PipelineConfig:
- pipeline_config_refs.md:1360: - pipeline_config_refs.md:805: - src\controller\pipeline_controller.py:231: base_config = self._build_pipeline_config_from_state()
- pipeline_config_refs.md:1361: - pipeline_config_refs.md:806: - src\controller\pipeline_controller.py:380: PR-CORE1-B3: NJR-backed jobs MUST NOT carry pipeline_config. The field may
- pipeline_config_refs.md:1362: - pipeline_config_refs.md:807: - src\controller\pipeline_controller.py:530: def build_pipeline_config_with_profiles(
- pipeline_config_refs.md:1363: - pipeline_config_refs.md:808: - src\controller\pipeline_controller.py:846: config = self._build_pipeline_config_from_state()
- pipeline_config_refs.md:1364: - pipeline_config_refs.md:809: - src\controller\pipeline_controller.py:1296: Legacy pipeline_config execution is retired in CORE1-C2.
- pipeline_config_refs.md:1365: - pipeline_config_refs.md:810: - src\controller\pipeline_controller.py:1550: record = build_njr_from_legacy_pipeline_config(config)
- pipeline_config_refs.md:1366: - pipeline_config_refs.md:811: - src\controller\pipeline_controller.py:1556: record = build_njr_from_legacy_pipeline_config(config)
- pipeline_config_refs.md:1367: - pipeline_config_refs.md:814: - src\gui\dropdown_loader_v2.py:61: panel = getattr(sidebar, "pipeline_config_panel", None)
- pipeline_config_refs.md:1368: - pipeline_config_refs.md:817: - src\gui\main_window_v2.py:187: if hasattr(self, "pipeline_tab") and hasattr(self.pipeline_tab, "pipeline_config_panel"):
- pipeline_config_refs.md:1369: - pipeline_config_refs.md:818: - src\gui\main_window_v2.py:189: self.pipeline_tab.pipeline_config_panel.controller = controller
- pipeline_config_refs.md:1370: - pipeline_config_refs.md:821: - src\gui\panels_v2\__init__.py:8: from src.gui.panels_v2.pipeline_config_panel_v2 import PipelineConfigPanel
- pipeline_config_refs.md:1371: - pipeline_config_refs.md:824: - src\gui\panels_v2\layout_manager_v2.py:62: mw.pipeline_config_panel_v2 = getattr(getattr(mw.pipeline_tab, "sidebar", None), "pipeline_config_panel", None)
- pipeline_config_refs.md:1372: - pipeline_config_refs.md:827: - src\gui\pipeline_panel_v2.py:297: config = getattr(job, "config_snapshot", None) or getattr(job, "pipeline_config", None) or {}
- pipeline_config_refs.md:1373: - pipeline_config_refs.md:830: - src\gui\preview_panel_v2.py:4: All display data comes from NJR snapshots, never from pipeline_config.
- pipeline_config_refs.md:1374: - pipeline_config_refs.md:833: - src\gui\sidebar_panel_v2.py:226: self.pipeline_config_card = _SidebarCard(
- pipeline_config_refs.md:1375: - pipeline_config_refs.md:834: - src\gui\sidebar_panel_v2.py:229: build_child=lambda parent: self._build_pipeline_config_section(parent),
- pipeline_config_refs.md:1376: - pipeline_config_refs.md:835: - src\gui\sidebar_panel_v2.py:231: self.pipeline_config_card.grid(row=3, column=0, sticky="ew", padx=8, pady=(0, 4))
- pipeline_config_refs.md:1377: - pipeline_config_refs.md:836: - src\gui\sidebar_panel_v2.py:872: def _build_pipeline_config_section(self, parent: ttk.Frame) -> ttk.Frame:
- pipeline_config_refs.md:1378: - pipeline_config_refs.md:837: - src\gui\sidebar_panel_v2.py:875: from src.gui.panels_v2.pipeline_config_panel_v2 import PipelineConfigPanel
- pipeline_config_refs.md:1379: - pipeline_config_refs.md:838: - src\gui\sidebar_panel_v2.py:885: self.pipeline_config_panel = PipelineConfigPanel(
- pipeline_config_refs.md:1380: - pipeline_config_refs.md:839: - src\gui\sidebar_panel_v2.py:891: self.pipeline_config_panel.pack(fill="both", expand=True)
- pipeline_config_refs.md:1381: - pipeline_config_refs.md:842: - src\history\history_migration_engine.py:16: build_njr_from_legacy_pipeline_config,
- pipeline_config_refs.md:1382: - pipeline_config_refs.md:843: - src\history\history_migration_engine.py:22: "pipeline_config",
- pipeline_config_refs.md:1383: - pipeline_config_refs.md:844: - src\history\history_migration_engine.py:161: def _coerce_pipeline_config(self, data: Mapping[str, Any]) -> PipelineConfig:
- pipeline_config_refs.md:1384: - pipeline_config_refs.md:847: - src\history\history_record.py:11: "pipeline_config",
- pipeline_config_refs.md:1385: - pipeline_config_refs.md:850: - src\history\history_schema_v26.py:26: "pipeline_config",
- pipeline_config_refs.md:1386: - pipeline_config_refs.md:853: - src\learning\learning_record_builder.py:40: pipeline_config: PipelineConfig,
- pipeline_config_refs.md:1387: - pipeline_config_refs.md:854: - src\learning\learning_record_builder.py:48: config_dict = asdict(pipeline_config)
- pipeline_config_refs.md:1388: - pipeline_config_refs.md:857: - src\pipeline\job_models_v2.py:78: the NJR snapshot stored in Job.snapshot, not from Job.pipeline_config.
- pipeline_config_refs.md:1389: - pipeline_config_refs.md:858: - src\pipeline\job_models_v2.py:79: Legacy jobs without NJR snapshots may fall back to pipeline_config.
- pipeline_config_refs.md:1390: - pipeline_config_refs.md:859: - src\pipeline\job_models_v2.py:103: the NJR snapshot stored in history entries, not from pipeline_config.
- pipeline_config_refs.md:1391: - pipeline_config_refs.md:860: - src\pipeline\job_models_v2.py:104: Legacy history entries without NJR snapshots may fall back to pipeline_config.
- pipeline_config_refs.md:1392: - pipeline_config_refs.md:861: - src\pipeline\job_models_v2.py:439: During early CORE1-A/B hybrid state, Job.pipeline_config was the execution payload,
- pipeline_config_refs.md:1393: - pipeline_config_refs.md:862: - src\pipeline\job_models_v2.py:441: Full NJR-only execution is enforced for all new jobs; pipeline_config remains
- pipeline_config_refs.md:1394: - pipeline_config_refs.md:865: - src\pipeline\legacy_njr_adapter.py:31: def build_njr_from_legacy_pipeline_config(pipeline_config: PipelineConfig) -> NormalizedJobRecord:
- pipeline_config_refs.md:1395: - pipeline_config_refs.md:866: - src\pipeline\legacy_njr_adapter.py:40: config_snapshot = asdict(pipeline_config)
- pipeline_config_refs.md:1396: - pipeline_config_refs.md:867: - src\pipeline\legacy_njr_adapter.py:41: stage = _make_default_stage(pipeline_config)
- pipeline_config_refs.md:1397: - pipeline_config_refs.md:868: - src\pipeline\legacy_njr_adapter.py:42: metadata = dict(pipeline_config.metadata or {})
- pipeline_config_refs.md:1398: - pipeline_config_refs.md:869: - src\pipeline\legacy_njr_adapter.py:60: positive_prompt=pipeline_config.prompt or "",
- pipeline_config_refs.md:1399: - pipeline_config_refs.md:870: - src\pipeline\legacy_njr_adapter.py:61: negative_prompt=pipeline_config.negative_prompt or "",
- pipeline_config_refs.md:1400: - pipeline_config_refs.md:871: - src\pipeline\legacy_njr_adapter.py:66: steps=pipeline_config.steps or 20,
- pipeline_config_refs.md:1401: - pipeline_config_refs.md:872: - src\pipeline\legacy_njr_adapter.py:67: cfg_scale=pipeline_config.cfg_scale or 7.0,
- pipeline_config_refs.md:1402: - pipeline_config_refs.md:873: - src\pipeline\legacy_njr_adapter.py:68: width=pipeline_config.width or 512,
- pipeline_config_refs.md:1403: - pipeline_config_refs.md:874: - src\pipeline\legacy_njr_adapter.py:69: height=pipeline_config.height or 512,
- pipeline_config_refs.md:1404: - pipeline_config_refs.md:875: - src\pipeline\legacy_njr_adapter.py:70: sampler_name=pipeline_config.sampler or "Euler a",
- pipeline_config_refs.md:1405: - pipeline_config_refs.md:876: - src\pipeline\legacy_njr_adapter.py:71: scheduler=getattr(pipeline_config, "scheduler", "") or "",
- pipeline_config_refs.md:1406: - pipeline_config_refs.md:877: - src\pipeline\legacy_njr_adapter.py:72: base_model=pipeline_config.model or "unknown",
- pipeline_config_refs.md:1407: - pipeline_config_refs.md:878: - src\pipeline\legacy_njr_adapter.py:90: "legacy_source": "pipeline_config",
- pipeline_config_refs.md:1408: - pipeline_config_refs.md:879: - src\pipeline\legacy_njr_adapter.py:140: pipeline_config = data.get("pipeline_config")
- pipeline_config_refs.md:1409: - pipeline_config_refs.md:880: - src\pipeline\legacy_njr_adapter.py:141: if isinstance(pipeline_config, PipelineConfig):
- pipeline_config_refs.md:1410: - pipeline_config_refs.md:881: - src\pipeline\legacy_njr_adapter.py:142: return build_njr_from_legacy_pipeline_config(pipeline_config)
- pipeline_config_refs.md:1411: - pipeline_config_refs.md:882: - src\pipeline\legacy_njr_adapter.py:143: if isinstance(pipeline_config, Mapping):
- pipeline_config_refs.md:1412: - pipeline_config_refs.md:883: - src\pipeline\legacy_njr_adapter.py:145: prompt=str(pipeline_config.get("prompt", "") or ""),
- pipeline_config_refs.md:1413: - pipeline_config_refs.md:884: - src\pipeline\legacy_njr_adapter.py:146: model=_normalize_model_name(pipeline_config.get("model", "") or pipeline_config.get("model_name", "")),
- pipeline_config_refs.md:1414: - pipeline_config_refs.md:885: - src\pipeline\legacy_njr_adapter.py:147: sampler=str(pipeline_config.get("sampler", "") or pipeline_config.get("sampler_name", "") or "Euler a"),
- pipeline_config_refs.md:1415: - pipeline_config_refs.md:886: - src\pipeline\legacy_njr_adapter.py:148: width=_coerce_int(pipeline_config.get("width", 512), 512),
- pipeline_config_refs.md:1416: - pipeline_config_refs.md:887: - src\pipeline\legacy_njr_adapter.py:149: height=_coerce_int(pipeline_config.get("height", 512), 512),
- pipeline_config_refs.md:1417: - pipeline_config_refs.md:888: - src\pipeline\legacy_njr_adapter.py:150: steps=_coerce_int(pipeline_config.get("steps", 20), 20),
- pipeline_config_refs.md:1418: - pipeline_config_refs.md:889: - src\pipeline\legacy_njr_adapter.py:151: cfg_scale=_coerce_float(pipeline_config.get("cfg_scale", 7.0), 7.0),
- pipeline_config_refs.md:1419: - pipeline_config_refs.md:890: - src\pipeline\legacy_njr_adapter.py:152: negative_prompt=str(pipeline_config.get("negative_prompt", "") or ""),
- pipeline_config_refs.md:1420: - pipeline_config_refs.md:891: - src\pipeline\legacy_njr_adapter.py:153: metadata=dict(pipeline_config.get("metadata") or {}),
- pipeline_config_refs.md:1421: - pipeline_config_refs.md:892: - src\pipeline\legacy_njr_adapter.py:155: return build_njr_from_legacy_pipeline_config(config)
- pipeline_config_refs.md:1422: - pipeline_config_refs.md:895: - src\pipeline\pipeline_runner.py:415: config = self._pipeline_config_from_njr(record)
- pipeline_config_refs.md:1423: - pipeline_config_refs.md:896: - src\pipeline\pipeline_runner.py:418: def _pipeline_config_from_njr(self, record: NormalizedJobRecord) -> PipelineConfig:
- pipeline_config_refs.md:1424: - pipeline_config_refs.md:899: - src\pipeline\stage_sequencer.py:262: plan = sequencer.build_plan(pipeline_config)
- pipeline_config_refs.md:1425: - pipeline_config_refs.md:900: - src\pipeline\stage_sequencer.py:265: def build_plan(self, pipeline_config: dict[str, Any]) -> StageExecutionPlan:
- pipeline_config_refs.md:1426: - pipeline_config_refs.md:901: - src\pipeline\stage_sequencer.py:269: pipeline_config: Dictionary containing stage configurations and flags.
- pipeline_config_refs.md:1427: - pipeline_config_refs.md:902: - src\pipeline\stage_sequencer.py:278: return build_stage_execution_plan(pipeline_config)
- pipeline_config_refs.md:1428: - pipeline_config_refs.md:905: - src\queue\job_history_store.py:8: NormalizedJobRecord data. Legacy entries on disk may still expose pipeline_config
- pipeline_config_refs.md:1429: - pipeline_config_refs.md:906: - src\queue\job_history_store.py:9: blobs, but new entries no longer persist pipeline_config—legacy_njr_adapter
- pipeline_config_refs.md:1430: - pipeline_config_refs.md:909: - src\queue\job_queue.py:7: for execution. The pipeline_config field is legacy-only and should not be relied
- pipeline_config_refs.md:1431: - pipeline_config_refs.md:912: - src\services\queue_store_v2.py:29: "pipeline_config",
- pipeline_config_refs.md:1432: - pipeline_config_refs.md:913: - src\services\queue_store_v2.py:49: "pipeline_config",
- pipeline_config_refs.md:1433: - pipeline_config_refs.md:916: - src\utils\snapshot_builder_v2.py:35: def _serialize_pipeline_config(config: Any) -> dict[str, Any]:
- pipeline_config_refs.md:1434: - pipeline_config_refs.md:917: - src\utils\snapshot_builder_v2.py:188: "config": _serialize_pipeline_config(record.config),
- pipeline_config_refs.md:1435: - pipeline_config_refs.md:920: - test_adetailer_sync.py:10: from src.gui.panels_v2.pipeline_config_panel_v2 import PipelineConfigPanel
- pipeline_config_refs.md:1436: - pipeline_config_refs.md:923: - test_output.txt:60: tests\controller\test_pipeline_config_assembler.py ...                   [ 14%]
- pipeline_config_refs.md:1437: - pipeline_config_refs.md:924: - test_output.txt:61: tests\controller\test_pipeline_config_assembler_core_fields.py ..        [ 14%]
- pipeline_config_refs.md:1438: - pipeline_config_refs.md:925: - test_output.txt:62: tests\controller\test_pipeline_config_assembler_model_fields.py .        [ 14%]
- pipeline_config_refs.md:1439: - pipeline_config_refs.md:926: - test_output.txt:63: tests\controller\test_pipeline_config_assembler_negative_prompt.py .     [ 14%]
- pipeline_config_refs.md:1440: - pipeline_config_refs.md:927: - test_output.txt:64: tests\controller\test_pipeline_config_assembler_output_settings.py .     [ 14%]
- pipeline_config_refs.md:1441: - pipeline_config_refs.md:928: - test_output.txt:65: tests\controller\test_pipeline_config_assembler_resolution.py .          [ 14%]
- pipeline_config_refs.md:1442: - pipeline_config_refs.md:931: - tests\compat\data\history_compat_v2\history_v2_0_pre_njr.jsonl:1: {"job_id":"legacy-001","timestamp":"2023-01-01T00:00:00Z","status":"completed","pipeline_config":{"prompt":"legacy prompt 001","model":"sdxl","steps":20,"cfg_scale":7.0,"sampler":"Euler a","width":512,"height":512},"result":{"run_id":"legacy-001","success":true,"variants":[],"learning_records":[],"metadata":{"source":"legacy"}}}
- pipeline_config_refs.md:1443: - pipeline_config_refs.md:932: - tests\compat\data\history_compat_v2\history_v2_0_pre_njr.jsonl:2: {"job_id":"legacy-002","timestamp":"2023-02-02T00:00:00Z","status":"failed","pipeline_config":{"prompt":"legacy prompt 002","model":"sdxl","steps":25,"cfg_scale":6.5,"sampler":"Euler a","width":640,"height":640},"error_message":"boom","result":{"run_id":"legacy-002","success":false,"error":"boom","variants":[],"learning_records":[],"metadata":{"source":"legacy"}}}
- pipeline_config_refs.md:1444: - pipeline_config_refs.md:933: - tests\compat\data\history_compat_v2\history_v2_0_pre_njr.jsonl:3: {"job_id":"legacy-003","timestamp":"2023-03-03T00:00:00Z","status":"completed","pipeline_config":{"prompt":"legacy prompt 003","model":"sdxl","steps":15,"cfg_scale":8.0,"sampler":"Euler a","width":768,"height":768},"result":{"run_id":"legacy-003","success":true,"variants":[],"learning_records":[],"metadata":{"source":"legacy"}}}
- pipeline_config_refs.md:1445: - pipeline_config_refs.md:936: - tests\compat\data\history_compat_v2\history_v2_4_hybrid.jsonl:1: {"job_id":"hybrid-001","timestamp":"2024-04-04T04:04:04Z","status":"failed","snapshot":{"job_id":"hybrid-001","positive_prompt":"hybrid prompt","base_model":"sdxl","steps":26,"cfg_scale":7.5,"normalized_job":{"job_id":"hybrid-001","config":{"prompt":"hybrid prompt","model":"sdxl"}}},"pipeline_config":{"prompt":"hybrid prompt","model":"sdxl","steps":26,"cfg_scale":7.5,"sampler":"Euler a","width":640,"height":640},"result":{"run_id":"hybrid-001","success":false,"error":"oops","variants":[],"learning_records":[],"metadata":{"source":"hybrid"}}}
- pipeline_config_refs.md:1446: - pipeline_config_refs.md:937: - tests\compat\data\history_compat_v2\history_v2_4_hybrid.jsonl:3: {"job_id":"hybrid-003","timestamp":"2024-06-06T06:06:06Z","status":"completed","snapshot":{"normalized_job":{"job_id":"hybrid-003","config":{"prompt":"hybrid three","model":"sdxl","steps":30,"cfg_scale":7.2}}},"pipeline_config":{"prompt":"hybrid three","model":"sdxl","steps":30,"cfg_scale":7.2,"sampler":"Euler a","width":512,"height":512},"result":{"run_id":"hybrid-003","success":true,"variants":[],"learning_records":[],"metadata":{"source":"hybrid"}}}
- pipeline_config_refs.md:1447: - pipeline_config_refs.md:940: - tests\compat\data\queue_compat_v2\queue_state_v2_0.json:1: {"jobs":[{"queue_id":"legacy-queue-001","job_id":"legacy-queue-001","status":"queued","priority":1,"created_at":"2023-01-05T10:00:00Z","pipeline_config":{"prompt":"queue prompt legacy 001","model":"sdxl","steps":20,"cfg_scale":7.0,"sampler":"Euler a","width":512,"height":512}},{"queue_id":"legacy-queue-002","job_id":"legacy-queue-002","status":"running","priority":2,"created_at":"2023-01-06T11:11:00Z","pipeline_config":{"prompt":"queue prompt legacy 002","model":"sdxl","steps":24,"cfg_scale":6.5,"sampler":"Euler a","width":640,"height":640}}],"auto_run_enabled":true,"paused":false,"schema_version":"2.0"}
- pipeline_config_refs.md:1448: - pipeline_config_refs.md:943: - tests\compat\data\queue_compat_v2\queue_state_v2_4_hybrid.json:1: {"jobs":[{"queue_id":"hybrid-queue-001","job_id":"hybrid-queue-001","status":"queued","priority":1,"created_at":"2024-04-04T04:04:00Z","snapshot":{"job_id":"hybrid-queue-001","positive_prompt":"hybrid queue prompt","base_model":"sdxl","steps":30,"cfg_scale":7.25},"pipeline_config":{"prompt":"hybrid queue prompt","model":"sdxl","steps":30,"cfg_scale":7.25,"sampler":"Euler a","width":640,"height":640}},{"queue_id":"hybrid-queue-002","job_id":"hybrid-queue-002","status":"queued","priority":2,"created_at":"2024-04-05T05:05:00Z","njr_snapshot":{"job_id":"hybrid-queue-002","positive_prompt":"hybrid queue nested","base_model":"sdxl","steps":32,"cfg_scale":7.5,"normalized_job":{"job_id":"hybrid-queue-002","config":{"prompt":"hybrid queue nested","model":"sdxl","steps":32,"cfg_scale":7.5}}}}],"auto_run_enabled":false,"paused":true,"schema_version":"2.4"}
- pipeline_config_refs.md:1449: - pipeline_config_refs.md:946: - tests\compat\data\queue_compat_v2\queue_state_v2_6_core1_pre.json:1: {"jobs":[{"queue_id":"core1-queue-001","job_id":"core1-queue-001","status":"queued","priority":1,"created_at":"2025-01-10T10:10:00Z","njr_snapshot":{"job_id":"core1-queue-001","positive_prompt":"core1 queue ready","base_model":"sdxl","steps":40,"cfg_scale":7.8},"_normalized_record":{"job_id":"core1-queue-001"},"pipeline_config":{"prompt":"core1 queue ready","model":"sdxl","steps":40,"cfg_scale":7.8,"sampler":"Euler a","width":768,"height":768},"metadata":{"note":"transitioning"}},{"queue_id":"core1-queue-002","job_id":"core1-queue-002","status":"running","priority":2,"created_at":"2025-01-11T11:11:00Z","njr_snapshot":{"job_id":"core1-queue-002","positive_prompt":"core1 queue run","base_model":"sdxl","steps":42,"cfg_scale":7.9,"normalized_job":{"job_id":"core1-queue-002","config":{"prompt":"core1 queue run","model":"sdxl","steps":42,"cfg_scale":7.9}}}}],"auto_run_enabled":true,"paused":false,"schema_version":"2.6"}
- pipeline_config_refs.md:1450: - pipeline_config_refs.md:949: - tests\controller\archive\test_app_controller_pipeline_integration.py:58: def test_pipeline_config_assembled_from_controller_state(pack_file):
- pipeline_config_refs.md:1451: - pipeline_config_refs.md:950: - tests\controller\archive\test_app_controller_pipeline_integration.py:90: pipeline_config = runner.calls[0][0]
- pipeline_config_refs.md:1452: - pipeline_config_refs.md:951: - tests\controller\archive\test_app_controller_pipeline_integration.py:91: assert isinstance(pipeline_config, PipelineConfig)
- pipeline_config_refs.md:1453: - pipeline_config_refs.md:952: - tests\controller\archive\test_app_controller_pipeline_integration.py:92: assert pipeline_config.model == "SDXL-Lightning"
- pipeline_config_refs.md:1454: - pipeline_config_refs.md:953: - tests\controller\archive\test_app_controller_pipeline_integration.py:93: assert pipeline_config.sampler == "DPM++ 2M"
- pipeline_config_refs.md:1455: - pipeline_config_refs.md:954: - tests\controller\archive\test_app_controller_pipeline_integration.py:94: assert pipeline_config.width == 832
- pipeline_config_refs.md:1456: - pipeline_config_refs.md:955: - tests\controller\archive\test_app_controller_pipeline_integration.py:95: assert pipeline_config.height == 640
- pipeline_config_refs.md:1457: - pipeline_config_refs.md:956: - tests\controller\archive\test_app_controller_pipeline_integration.py:96: assert pipeline_config.steps == 42
- pipeline_config_refs.md:1458: - pipeline_config_refs.md:957: - tests\controller\archive\test_app_controller_pipeline_integration.py:97: assert pipeline_config.cfg_scale == 8.9
- pipeline_config_refs.md:1459: - pipeline_config_refs.md:958: - tests\controller\archive\test_app_controller_pipeline_integration.py:98: assert pipeline_config.pack_name == "alpha"
- pipeline_config_refs.md:1460: - pipeline_config_refs.md:959: - tests\controller\archive\test_app_controller_pipeline_integration.py:99: assert "sunset" in pipeline_config.prompt
- pipeline_config_refs.md:1461: - pipeline_config_refs.md:962: - tests\controller\test_app_controller_lora_runtime.py:88: payload = controller._build_pipeline_config()
- pipeline_config_refs.md:1462: - pipeline_config_refs.md:965: - tests\controller\test_app_controller_njr_exec.py:6: - Rejects jobs without normalized_record (no pipeline_config fallback)
- pipeline_config_refs.md:1463: - pipeline_config_refs.md:966: - tests\controller\test_app_controller_njr_exec.py:92: """Jobs without normalized_record are rejected (no pipeline_config fallback)."""
- pipeline_config_refs.md:1464: - pipeline_config_refs.md:967: - tests\controller\test_app_controller_njr_exec.py:129: def test_payload_job_without_njr_or_pipeline_config_returns_error(self, mock_app_controller):
- pipeline_config_refs.md:1465: - pipeline_config_refs.md:970: - tests\controller\test_app_controller_pipeline_integration.py:56: def test_pipeline_config_assembled_from_controller_state(pack_file):
- pipeline_config_refs.md:1466: - pipeline_config_refs.md:971: - tests\controller\test_app_controller_pipeline_integration.py:88: pipeline_config = runner.calls[0][0]
- pipeline_config_refs.md:1467: - pipeline_config_refs.md:972: - tests\controller\test_app_controller_pipeline_integration.py:89: assert isinstance(pipeline_config, PipelineConfig)
- pipeline_config_refs.md:1468: - pipeline_config_refs.md:973: - tests\controller\test_app_controller_pipeline_integration.py:90: assert pipeline_config.model == "SDXL-Lightning"
- pipeline_config_refs.md:1469: - pipeline_config_refs.md:974: - tests\controller\test_app_controller_pipeline_integration.py:91: assert pipeline_config.sampler == "DPM++ 2M"
- pipeline_config_refs.md:1470: - pipeline_config_refs.md:975: - tests\controller\test_app_controller_pipeline_integration.py:92: assert pipeline_config.width == 832
- pipeline_config_refs.md:1471: - pipeline_config_refs.md:976: - tests\controller\test_app_controller_pipeline_integration.py:93: assert pipeline_config.height == 640
- pipeline_config_refs.md:1472: - pipeline_config_refs.md:977: - tests\controller\test_app_controller_pipeline_integration.py:94: assert pipeline_config.steps == 42
- pipeline_config_refs.md:1473: - pipeline_config_refs.md:978: - tests\controller\test_app_controller_pipeline_integration.py:95: assert pipeline_config.cfg_scale == 8.9
- pipeline_config_refs.md:1474: - pipeline_config_refs.md:979: - tests\controller\test_app_controller_pipeline_integration.py:96: assert pipeline_config.pack_name == "alpha"
- pipeline_config_refs.md:1475: - pipeline_config_refs.md:980: - tests\controller\test_app_controller_pipeline_integration.py:97: assert "sunset" in pipeline_config.prompt
- pipeline_config_refs.md:1476: - pipeline_config_refs.md:983: - tests\controller\test_core_run_path_v2.py:151: """PR-CORE1-B2: Job with NJR that fails execution returns error (no pipeline_config fallback)."""
- pipeline_config_refs.md:1477: - pipeline_config_refs.md:984: - tests\controller\test_core_run_path_v2.py:172: # PR-CORE1-B2: Should return error status, not fall back to pipeline_config
- pipeline_config_refs.md:1478: - pipeline_config_refs.md:985: - tests\controller\test_core_run_path_v2.py:197: assert getattr(queue_job, "pipeline_config", None) is None
- pipeline_config_refs.md:1479: - pipeline_config_refs.md:988: - tests\controller\test_job_construction_b3.py:36: assert getattr(job, "pipeline_config", None) is None
- pipeline_config_refs.md:1480: - pipeline_config_refs.md:990: ## tests\controller\test_pipeline_config_assembler.py
- pipeline_config_refs.md:1481: - pipeline_config_refs.md:991: - tests\controller\test_pipeline_config_assembler.py:1: from src.controller.pipeline_config_assembler import PipelineConfigAssembler, GuiOverrides
- pipeline_config_refs.md:1482: - pipeline_config_refs.md:992: - tests\controller\test_pipeline_config_assembler.py:4: def test_build_pipeline_config_applies_overrides_and_limits():
- pipeline_config_refs.md:1483: - pipeline_config_refs.md:993: - tests\controller\test_pipeline_config_assembler.py:22: def test_build_pipeline_config_includes_metadata():
- pipeline_config_refs.md:1484: - pipeline_config_refs.md:995: ## tests\controller\test_pipeline_config_assembler_core_fields.py
- pipeline_config_refs.md:1485: - pipeline_config_refs.md:996: - tests\controller\test_pipeline_config_assembler_core_fields.py:3: from src.controller.pipeline_config_assembler import GuiOverrides, PipelineConfigAssembler
- pipeline_config_refs.md:1486: - pipeline_config_refs.md:998: ## tests\controller\test_pipeline_config_assembler_model_fields.py
- pipeline_config_refs.md:1487: - pipeline_config_refs.md:999: - tests\controller\test_pipeline_config_assembler_model_fields.py:1: from src.controller.pipeline_config_assembler import GuiOverrides, PipelineConfigAssembler
- pipeline_config_refs.md:1488: - pipeline_config_refs.md:1001: ## tests\controller\test_pipeline_config_assembler_negative_prompt.py
- pipeline_config_refs.md:1489: - pipeline_config_refs.md:1002: - tests\controller\test_pipeline_config_assembler_negative_prompt.py:1: from src.controller.pipeline_config_assembler import GuiOverrides, PipelineConfigAssembler
- pipeline_config_refs.md:1490: - pipeline_config_refs.md:1004: ## tests\controller\test_pipeline_config_assembler_output_settings.py
- pipeline_config_refs.md:1491: - pipeline_config_refs.md:1005: - tests\controller\test_pipeline_config_assembler_output_settings.py:1: from src.controller.pipeline_config_assembler import GuiOverrides, PipelineConfigAssembler
- pipeline_config_refs.md:1492: - pipeline_config_refs.md:1007: ## tests\controller\test_pipeline_config_assembler_resolution.py
- pipeline_config_refs.md:1493: - pipeline_config_refs.md:1008: - tests\controller\test_pipeline_config_assembler_resolution.py:1: from src.controller.pipeline_config_assembler import GuiOverrides, PipelineConfigAssembler
- pipeline_config_refs.md:1494: - pipeline_config_refs.md:1011: - tests\controller\test_pipeline_controller_config_path.py:5: from src.controller.pipeline_config_assembler import PipelineConfigAssembler, GuiOverrides
- pipeline_config_refs.md:1495: - pipeline_config_refs.md:1014: - tests\controller\test_pipeline_controller_job_specs_v2.py:10: 3. Key pipeline_config fields (model, steps, CFG, etc.) are correctly passed through.
- pipeline_config_refs.md:1496: - pipeline_config_refs.md:1015: - tests\controller\test_pipeline_controller_job_specs_v2.py:28: make_minimal_pipeline_config,
- pipeline_config_refs.md:1497: - pipeline_config_refs.md:1016: - tests\controller\test_pipeline_controller_job_specs_v2.py:68: config = make_minimal_pipeline_config(model="test-model", seed=12345)
- pipeline_config_refs.md:1498: - pipeline_config_refs.md:1017: - tests\controller\test_pipeline_controller_job_specs_v2.py:81: config = make_minimal_pipeline_config()
- pipeline_config_refs.md:1499: - pipeline_config_refs.md:1018: - tests\controller\test_pipeline_controller_job_specs_v2.py:98: config = make_minimal_pipeline_config(model="my-special-model")
- pipeline_config_refs.md:1500: - pipeline_config_refs.md:1019: - tests\controller\test_pipeline_controller_job_specs_v2.py:110: config = make_minimal_pipeline_config(steps=42)
- pipeline_config_refs.md:1501: - pipeline_config_refs.md:1020: - tests\controller\test_pipeline_controller_job_specs_v2.py:122: config = make_minimal_pipeline_config(cfg_scale=9.5)
- pipeline_config_refs.md:1502: - pipeline_config_refs.md:1021: - tests\controller\test_pipeline_controller_job_specs_v2.py:134: config = make_minimal_pipeline_config()
- pipeline_config_refs.md:1503: - pipeline_config_refs.md:1022: - tests\controller\test_pipeline_controller_job_specs_v2.py:152: config = make_minimal_pipeline_config()
- pipeline_config_refs.md:1504: - pipeline_config_refs.md:1023: - tests\controller\test_pipeline_controller_job_specs_v2.py:176: config = make_minimal_pipeline_config(model="base-model")
- pipeline_config_refs.md:1505: - pipeline_config_refs.md:1024: - tests\controller\test_pipeline_controller_job_specs_v2.py:193: config = make_minimal_pipeline_config()
- pipeline_config_refs.md:1506: - pipeline_config_refs.md:1025: - tests\controller\test_pipeline_controller_job_specs_v2.py:212: config = make_minimal_pipeline_config()
- pipeline_config_refs.md:1507: - pipeline_config_refs.md:1026: - tests\controller\test_pipeline_controller_job_specs_v2.py:233: config = make_minimal_pipeline_config()
- pipeline_config_refs.md:1508: - pipeline_config_refs.md:1027: - tests\controller\test_pipeline_controller_job_specs_v2.py:253: config = make_minimal_pipeline_config()
- pipeline_config_refs.md:1509: - pipeline_config_refs.md:1028: - tests\controller\test_pipeline_controller_job_specs_v2.py:269: config = make_minimal_pipeline_config()
- pipeline_config_refs.md:1510: - pipeline_config_refs.md:1029: - tests\controller\test_pipeline_controller_job_specs_v2.py:296: config = make_minimal_pipeline_config()
- pipeline_config_refs.md:1511: - pipeline_config_refs.md:1030: - tests\controller\test_pipeline_controller_job_specs_v2.py:309: config = make_minimal_pipeline_config()
- pipeline_config_refs.md:1512: - pipeline_config_refs.md:1031: - tests\controller\test_pipeline_controller_job_specs_v2.py:323: config = make_minimal_pipeline_config()
- pipeline_config_refs.md:1513: - pipeline_config_refs.md:1032: - tests\controller\test_pipeline_controller_job_specs_v2.py:336: config = make_minimal_pipeline_config()
- pipeline_config_refs.md:1514: - pipeline_config_refs.md:1033: - tests\controller\test_pipeline_controller_job_specs_v2.py:350: config = make_minimal_pipeline_config(model="batch-model", steps=25)
- pipeline_config_refs.md:1515: - pipeline_config_refs.md:1034: - tests\controller\test_pipeline_controller_job_specs_v2.py:374: config = make_minimal_pipeline_config()
- pipeline_config_refs.md:1516: - pipeline_config_refs.md:1035: - tests\controller\test_pipeline_controller_job_specs_v2.py:391: config = make_minimal_pipeline_config()
- pipeline_config_refs.md:1517: - pipeline_config_refs.md:1036: - tests\controller\test_pipeline_controller_job_specs_v2.py:416: config = make_minimal_pipeline_config()
- pipeline_config_refs.md:1518: - pipeline_config_refs.md:1037: - tests\controller\test_pipeline_controller_job_specs_v2.py:441: config = make_minimal_pipeline_config()
- pipeline_config_refs.md:1519: - pipeline_config_refs.md:1038: - tests\controller\test_pipeline_controller_job_specs_v2.py:468: config = make_minimal_pipeline_config(hires_enabled=True)
- pipeline_config_refs.md:1520: - pipeline_config_refs.md:1039: - tests\controller\test_pipeline_controller_job_specs_v2.py:479: config = make_minimal_pipeline_config(refiner_enabled=True)
- pipeline_config_refs.md:1521: - pipeline_config_refs.md:1040: - tests\controller\test_pipeline_controller_job_specs_v2.py:490: config = make_minimal_pipeline_config(adetailer_enabled=True)
- pipeline_config_refs.md:1522: - pipeline_config_refs.md:1041: - tests\controller\test_pipeline_controller_job_specs_v2.py:519: config = make_minimal_pipeline_config(model="test", seed=123)
- pipeline_config_refs.md:1523: - pipeline_config_refs.md:1042: - tests\controller\test_pipeline_controller_job_specs_v2.py:551: config = make_minimal_pipeline_config()
- pipeline_config_refs.md:1524: - pipeline_config_refs.md:1043: - tests\controller\test_pipeline_controller_job_specs_v2.py:582: config = make_minimal_pipeline_config()
- pipeline_config_refs.md:1525: - pipeline_config_refs.md:1044: - tests\controller\test_pipeline_controller_job_specs_v2.py:593: config = make_minimal_pipeline_config()
- pipeline_config_refs.md:1526: - pipeline_config_refs.md:1045: - tests\controller\test_pipeline_controller_job_specs_v2.py:606: config = make_minimal_pipeline_config()
- pipeline_config_refs.md:1527: - pipeline_config_refs.md:1048: - tests\controller\test_pipeline_controller_webui_gating.py:11: controller._build_pipeline_config_from_state = mock.Mock()
- pipeline_config_refs.md:1528: - pipeline_config_refs.md:1049: - tests\controller\test_pipeline_controller_webui_gating.py:16: controller._build_pipeline_config_from_state.assert_not_called()
- pipeline_config_refs.md:1529: - pipeline_config_refs.md:1050: - tests\controller\test_pipeline_controller_webui_gating.py:23: controller._build_pipeline_config_from_state = mock.Mock(return_value=mock.Mock())
- pipeline_config_refs.md:1530: - pipeline_config_refs.md:1051: - tests\controller\test_pipeline_controller_webui_gating.py:32: controller._build_pipeline_config_from_state.assert_called_once()
- pipeline_config_refs.md:1531: - pipeline_config_refs.md:1054: - tests\controller\test_pipeline_randomizer_config_v2.py:54: controller.main_window = SimpleNamespace(pipeline_config_panel_v2=panel)
- pipeline_config_refs.md:1532: - pipeline_config_refs.md:1057: - tests\controller\test_presets_integration_v2.py:48: controller.main_window = SimpleNamespace(pipeline_config_panel_v2=DummyPipelinePanel())
- pipeline_config_refs.md:1533: - pipeline_config_refs.md:1058: - tests\controller\test_presets_integration_v2.py:56: assert controller.main_window.pipeline_config_panel_v2.applied[-1]["randomization_enabled"]
- pipeline_config_refs.md:1534: - pipeline_config_refs.md:1061: - tests\controller\test_profile_integration.py:18: def test_build_pipeline_config_with_profiles_applies_suggested_preset():
- pipeline_config_refs.md:1535: - pipeline_config_refs.md:1062: - tests\controller\test_profile_integration.py:23: config = controller.build_pipeline_config_with_profiles(
- pipeline_config_refs.md:1536: - pipeline_config_refs.md:1063: - tests\controller\test_profile_integration.py:34: def test_build_pipeline_config_with_profiles_respects_user_overrides():
- pipeline_config_refs.md:1537: - pipeline_config_refs.md:1064: - tests\controller\test_profile_integration.py:39: config = controller.build_pipeline_config_with_profiles(
- pipeline_config_refs.md:1538: - pipeline_config_refs.md:1065: - tests\controller\test_profile_integration.py:48: def test_build_pipeline_config_with_profiles_falls_back_without_profiles():
- pipeline_config_refs.md:1539: - pipeline_config_refs.md:1066: - tests\controller\test_profile_integration.py:53: config = controller.build_pipeline_config_with_profiles(
- pipeline_config_refs.md:1540: - pipeline_config_refs.md:1069: - tests\gui_v2\archive\test_pipeline_randomizer_panel_v2.py:11: from src.gui.panels_v2.pipeline_config_panel_v2 import PipelineConfigPanel
- pipeline_config_refs.md:1541: - pipeline_config_refs.md:1071: ## tests\gui_v2\test_pipeline_config_panel_lora_runtime.py
- pipeline_config_refs.md:1542: - pipeline_config_refs.md:1072: - tests\gui_v2\test_pipeline_config_panel_lora_runtime.py:8: from src.gui.panels_v2.pipeline_config_panel_v2 import PipelineConfigPanel
- pipeline_config_refs.md:1543: - pipeline_config_refs.md:1073: - tests\gui_v2\test_pipeline_config_panel_lora_runtime.py:33: def test_pipeline_config_panel_lora_controls_update_controller() -> None:
- pipeline_config_refs.md:1544: - pipeline_config_refs.md:1076: - tests\gui_v2\test_pipeline_layout_scroll_v2.py:338: def test_pipeline_config_panel_no_validation_label() -> None:
- pipeline_config_refs.md:1545: - pipeline_config_refs.md:1077: - tests\gui_v2\test_pipeline_layout_scroll_v2.py:347: from src.gui.panels_v2.pipeline_config_panel_v2 import PipelineConfigPanel
- pipeline_config_refs.md:1546: - pipeline_config_refs.md:1078: - tests\gui_v2\test_pipeline_layout_scroll_v2.py:374: from src.gui.panels_v2.pipeline_config_panel_v2 import PipelineConfigPanel
- pipeline_config_refs.md:1547: - pipeline_config_refs.md:1081: - tests\gui_v2\test_pipeline_left_column_config_v2.py:28: config_panel = getattr(sidebar, "pipeline_config_panel", None)
- pipeline_config_refs.md:1548: - pipeline_config_refs.md:1084: - tests\gui_v2\test_pipeline_stage_checkbox_order_v2.py:7: from src.gui.views.pipeline_config_panel import PipelineConfigPanel
- pipeline_config_refs.md:1549: - pipeline_config_refs.md:1085: - tests\gui_v2\test_pipeline_stage_checkbox_order_v2.py:11: def test_pipeline_config_stage_checkbox_order(monkeypatch) -> None:
- pipeline_config_refs.md:1550: - pipeline_config_refs.md:1088: - tests\gui_v2\test_preview_panel_v2_normalized_jobs.py:3: Confirms preview panel uses NJR-based display, not pipeline_config.
- pipeline_config_refs.md:1551: - pipeline_config_refs.md:1091: - tests\gui_v2\test_queue_panel_v2_normalized_jobs.py:3: Confirms queue panel uses NJR-based display, not pipeline_config.
- pipeline_config_refs.md:1552: - pipeline_config_refs.md:1094: - tests\helpers\pipeline_fixtures_v2.py:147: def make_minimal_pipeline_config(
- pipeline_config_refs.md:1553: - pipeline_config_refs.md:1095: - tests\helpers\pipeline_fixtures_v2.py:216: config = make_minimal_pipeline_config(seed=seed)
- pipeline_config_refs.md:1554: - pipeline_config_refs.md:1096: - tests\helpers\pipeline_fixtures_v2.py:277: "make_minimal_pipeline_config",
- pipeline_config_refs.md:1555: - pipeline_config_refs.md:1099: - tests\history\test_history_compaction.py:18: "pipeline_config": {"prompt": "old", "model": "v1", "sampler": "Euler"},
- pipeline_config_refs.md:1556: - pipeline_config_refs.md:1102: - tests\history\test_history_migration_engine.py:12: "pipeline_config": {
- pipeline_config_refs.md:1557: - pipeline_config_refs.md:1103: - tests\history\test_history_migration_engine.py:68: assert all("pipeline_config" not in entry["njr_snapshot"] for entry in migrated)
- pipeline_config_refs.md:1558: - pipeline_config_refs.md:1106: - tests\history\test_history_roundtrip.py:18: "pipeline_config": {
- pipeline_config_refs.md:1559: - pipeline_config_refs.md:1107: - tests\history\test_history_roundtrip.py:78: assert all("pipeline_config" not in rec.njr_snapshot for rec in second)
- pipeline_config_refs.md:1560: - pipeline_config_refs.md:1110: - tests\history\test_history_schema_roundtrip.py:19: "pipeline_config": {"prompt": "ancient job", "model": "v1", "sampler": "Euler a"},
- pipeline_config_refs.md:1561: - pipeline_config_refs.md:1113: - tests\history\test_history_schema_v26.py:38: entry["pipeline_config"] = {}
- pipeline_config_refs.md:1562: - pipeline_config_refs.md:1114: - tests\history\test_history_schema_v26.py:41: assert any("deprecated field present: pipeline_config" in err for err in errors)
- pipeline_config_refs.md:1563: - pipeline_config_refs.md:1117: - tests\integration\test_end_to_end_pipeline_v2.py:21: from src.pipeline.legacy_njr_adapter import build_njr_from_legacy_pipeline_config
- pipeline_config_refs.md:1564: - pipeline_config_refs.md:1118: - tests\integration\test_end_to_end_pipeline_v2.py:60: njr = build_njr_from_legacy_pipeline_config(cfg)
- pipeline_config_refs.md:1565: - pipeline_config_refs.md:1119: - tests\integration\test_end_to_end_pipeline_v2.py:260: config = job.pipeline_config
- pipeline_config_refs.md:1566: - pipeline_config_refs.md:1120: - tests\integration\test_end_to_end_pipeline_v2.py:282: def small_pipeline_config() -> PipelineConfig:
- pipeline_config_refs.md:1567: - pipeline_config_refs.md:1121: - tests\integration\test_end_to_end_pipeline_v2.py:313: small_pipeline_config: PipelineConfig,
- pipeline_config_refs.md:1568: - pipeline_config_refs.md:1122: - tests\integration\test_end_to_end_pipeline_v2.py:318: small_pipeline_config,
- pipeline_config_refs.md:1569: - pipeline_config_refs.md:1123: - tests\integration\test_end_to_end_pipeline_v2.py:352: small_pipeline_config: PipelineConfig,
- pipeline_config_refs.md:1570: - pipeline_config_refs.md:1124: - tests\integration\test_end_to_end_pipeline_v2.py:356: small_pipeline_config,
- pipeline_config_refs.md:1571: - pipeline_config_refs.md:1125: - tests\integration\test_end_to_end_pipeline_v2.py:377: small_pipeline_config: PipelineConfig,
- pipeline_config_refs.md:1572: - pipeline_config_refs.md:1126: - tests\integration\test_end_to_end_pipeline_v2.py:381: small_pipeline_config,
- pipeline_config_refs.md:1573: - pipeline_config_refs.md:1127: - tests\integration\test_end_to_end_pipeline_v2.py:411: small_pipeline_config: PipelineConfig,
- pipeline_config_refs.md:1574: - pipeline_config_refs.md:1128: - tests\integration\test_end_to_end_pipeline_v2.py:416: small_pipeline_config,
- pipeline_config_refs.md:1575: - pipeline_config_refs.md:1129: - tests\integration\test_end_to_end_pipeline_v2.py:445: small_pipeline_config: PipelineConfig,
- pipeline_config_refs.md:1576: - pipeline_config_refs.md:1130: - tests\integration\test_end_to_end_pipeline_v2.py:449: small_pipeline_config,
- pipeline_config_refs.md:1577: - pipeline_config_refs.md:1131: - tests\integration\test_end_to_end_pipeline_v2.py:516: small_pipeline_config: PipelineConfig,
- pipeline_config_refs.md:1578: - pipeline_config_refs.md:1132: - tests\integration\test_end_to_end_pipeline_v2.py:520: small_pipeline_config,
- pipeline_config_refs.md:1579: - pipeline_config_refs.md:1133: - tests\integration\test_end_to_end_pipeline_v2.py:557: small_pipeline_config: PipelineConfig,
- pipeline_config_refs.md:1580: - pipeline_config_refs.md:1134: - tests\integration\test_end_to_end_pipeline_v2.py:562: small_pipeline_config,
- pipeline_config_refs.md:1581: - pipeline_config_refs.md:1135: - tests\integration\test_end_to_end_pipeline_v2.py:663: pipeline_config = {
- pipeline_config_refs.md:1582: - pipeline_config_refs.md:1136: - tests\integration\test_end_to_end_pipeline_v2.py:682: plan = StageSequencer().build_plan(pipeline_config)
- pipeline_config_refs.md:1583: - pipeline_config_refs.md:1139: - tests\pipeline\test_config_merger_v2.py:67: def base_pipeline_config(base_txt2img_config: dict) -> dict:
- pipeline_config_refs.md:1584: - pipeline_config_refs.md:1140: - tests\pipeline\test_config_merger_v2.py:379: self, base_pipeline_config: dict
- pipeline_config_refs.md:1585: - pipeline_config_refs.md:1141: - tests\pipeline\test_config_merger_v2.py:386: base_config=base_pipeline_config,
- pipeline_config_refs.md:1586: - pipeline_config_refs.md:1142: - tests\pipeline\test_config_merger_v2.py:392: assert result == base_pipeline_config
- pipeline_config_refs.md:1587: - pipeline_config_refs.md:1143: - tests\pipeline\test_config_merger_v2.py:393: assert result is not base_pipeline_config
- pipeline_config_refs.md:1588: - pipeline_config_refs.md:1144: - tests\pipeline\test_config_merger_v2.py:394: assert result["refiner"] is not base_pipeline_config["refiner"]
- pipeline_config_refs.md:1589: - pipeline_config_refs.md:1145: - tests\pipeline\test_config_merger_v2.py:397: self, base_pipeline_config: dict
- pipeline_config_refs.md:1590: - pipeline_config_refs.md:1146: - tests\pipeline\test_config_merger_v2.py:403: base_config=base_pipeline_config,
- pipeline_config_refs.md:1591: - pipeline_config_refs.md:1147: - tests\pipeline\test_config_merger_v2.py:408: assert result == base_pipeline_config
- pipeline_config_refs.md:1592: - pipeline_config_refs.md:1148: - tests\pipeline\test_config_merger_v2.py:409: assert result is not base_pipeline_config
- pipeline_config_refs.md:1593: - pipeline_config_refs.md:1149: - tests\pipeline\test_config_merger_v2.py:412: self, base_pipeline_config: dict
- pipeline_config_refs.md:1594: - pipeline_config_refs.md:1150: - tests\pipeline\test_config_merger_v2.py:426: base_config=base_pipeline_config,
- pipeline_config_refs.md:1595: - pipeline_config_refs.md:1151: - tests\pipeline\test_config_merger_v2.py:437: self, base_pipeline_config: dict
- pipeline_config_refs.md:1596: - pipeline_config_refs.md:1152: - tests\pipeline\test_config_merger_v2.py:450: base_config=base_pipeline_config,
- pipeline_config_refs.md:1597: - pipeline_config_refs.md:1153: - tests\pipeline\test_config_merger_v2.py:464: self, base_pipeline_config: dict
- pipeline_config_refs.md:1598: - pipeline_config_refs.md:1154: - tests\pipeline\test_config_merger_v2.py:477: base_config=base_pipeline_config,
- pipeline_config_refs.md:1599: - pipeline_config_refs.md:1155: - tests\pipeline\test_config_merger_v2.py:487: self, base_pipeline_config: dict
- pipeline_config_refs.md:1600: - pipeline_config_refs.md:1156: - tests\pipeline\test_config_merger_v2.py:500: base_config=base_pipeline_config,
- pipeline_config_refs.md:1601: - pipeline_config_refs.md:1157: - tests\pipeline\test_config_merger_v2.py:510: self, base_pipeline_config: dict
- pipeline_config_refs.md:1602: - pipeline_config_refs.md:1158: - tests\pipeline\test_config_merger_v2.py:523: base_config=base_pipeline_config,
- pipeline_config_refs.md:1603: - pipeline_config_refs.md:1159: - tests\pipeline\test_config_merger_v2.py:533: self, base_pipeline_config: dict
- pipeline_config_refs.md:1604: - pipeline_config_refs.md:1160: - tests\pipeline\test_config_merger_v2.py:546: base_config=base_pipeline_config,
- pipeline_config_refs.md:1605: - pipeline_config_refs.md:1161: - tests\pipeline\test_config_merger_v2.py:556: self, base_pipeline_config: dict
- pipeline_config_refs.md:1606: - pipeline_config_refs.md:1162: - tests\pipeline\test_config_merger_v2.py:571: base_config=base_pipeline_config,
- pipeline_config_refs.md:1607: - pipeline_config_refs.md:1163: - tests\pipeline\test_config_merger_v2.py:592: self, base_pipeline_config: dict
- pipeline_config_refs.md:1608: - pipeline_config_refs.md:1164: - tests\pipeline\test_config_merger_v2.py:597: original = copy.deepcopy(base_pipeline_config)
- pipeline_config_refs.md:1609: - pipeline_config_refs.md:1165: - tests\pipeline\test_config_merger_v2.py:605: base_config=base_pipeline_config,
- pipeline_config_refs.md:1610: - pipeline_config_refs.md:1166: - tests\pipeline\test_config_merger_v2.py:611: assert base_pipeline_config == original
- pipeline_config_refs.md:1611: - pipeline_config_refs.md:1169: - tests\pipeline\test_job_queue_persistence_v2.py:76: "pipeline_config": {"model": "old"},
- pipeline_config_refs.md:1612: - pipeline_config_refs.md:1170: - tests\pipeline\test_job_queue_persistence_v2.py:84: assert "pipeline_config" not in migrated["njr_snapshot"]
- pipeline_config_refs.md:1613: - pipeline_config_refs.md:1171: - tests\pipeline\test_job_queue_persistence_v2.py:149: assert "pipeline_config" not in job_record["njr_snapshot"]
- pipeline_config_refs.md:1614: - pipeline_config_refs.md:1172: - tests\pipeline\test_job_queue_persistence_v2.py:166: "pipeline_config": {"model": "old"},
- pipeline_config_refs.md:1615: - pipeline_config_refs.md:1173: - tests\pipeline\test_job_queue_persistence_v2.py:185: assert "pipeline_config" not in job["njr_snapshot"]
- pipeline_config_refs.md:1616: - pipeline_config_refs.md:1174: - tests\pipeline\test_job_queue_persistence_v2.py:308: assert "pipeline_config" not in queue_entry["njr_snapshot"]
- pipeline_config_refs.md:1617: - pipeline_config_refs.md:1175: - tests\pipeline\test_job_queue_persistence_v2.py:309: assert "pipeline_config" not in history_njr
- pipeline_config_refs.md:1618: - pipeline_config_refs.md:1176: - tests\pipeline\test_job_queue_persistence_v2.py:353: assert "pipeline_config" not in entry["njr_snapshot"]
- pipeline_config_refs.md:1619: - pipeline_config_refs.md:1179: - tests\pipeline\test_legacy_njr_adapter.py:1: from src.pipeline.legacy_njr_adapter import build_njr_from_legacy_pipeline_config
- pipeline_config_refs.md:1620: - pipeline_config_refs.md:1180: - tests\pipeline\test_legacy_njr_adapter.py:5: def _make_pipeline_config() -> PipelineConfig:
- pipeline_config_refs.md:1621: - pipeline_config_refs.md:1181: - tests\pipeline\test_legacy_njr_adapter.py:20: config = _make_pipeline_config()
- pipeline_config_refs.md:1622: - pipeline_config_refs.md:1182: - tests\pipeline\test_legacy_njr_adapter.py:21: record = build_njr_from_legacy_pipeline_config(config)
- pipeline_config_refs.md:1623: - pipeline_config_refs.md:1183: - tests\pipeline\test_legacy_njr_adapter.py:25: assert record.extra_metadata.get("legacy_source") == "pipeline_config"
- pipeline_config_refs.md:1624: - pipeline_config_refs.md:1184: - tests\pipeline\test_legacy_njr_adapter.py:29: def test_adapter_handles_minimal_pipeline_config() -> None:
- pipeline_config_refs.md:1625: - pipeline_config_refs.md:1185: - tests\pipeline\test_legacy_njr_adapter.py:39: record = build_njr_from_legacy_pipeline_config(config)
- pipeline_config_refs.md:1626: - pipeline_config_refs.md:1188: - tests\pipeline\test_pipeline_learning_hooks.py:52: def _pipeline_config():
- pipeline_config_refs.md:1627: - pipeline_config_refs.md:1189: - tests\pipeline\test_pipeline_learning_hooks.py:67: runner.run(_pipeline_config(), cancel_token=_cancel_token())
- pipeline_config_refs.md:1628: - pipeline_config_refs.md:1190: - tests\pipeline\test_pipeline_learning_hooks.py:74: runner.run(_pipeline_config(), cancel_token=_cancel_token())
- pipeline_config_refs.md:1629: - pipeline_config_refs.md:1193: - tests\pipeline\test_stage_plan_builder_v2_5.py:8: def _base_pipeline_config(**overrides) -> dict[str, dict]:
- pipeline_config_refs.md:1630: - pipeline_config_refs.md:1194: - tests\pipeline\test_stage_plan_builder_v2_5.py:36: config = _base_pipeline_config(
- pipeline_config_refs.md:1631: - pipeline_config_refs.md:1195: - tests\pipeline\test_stage_plan_builder_v2_5.py:56: config = _base_pipeline_config(
- pipeline_config_refs.md:1632: - pipeline_config_refs.md:1196: - tests\pipeline\test_stage_plan_builder_v2_5.py:72: config = _base_pipeline_config(
- pipeline_config_refs.md:1633: - pipeline_config_refs.md:1197: - tests\pipeline\test_stage_plan_builder_v2_5.py:86: config = _base_pipeline_config(
- pipeline_config_refs.md:1634: - pipeline_config_refs.md:1200: - tests\queue\test_job_history_store.py:90: assert "pipeline_config" not in njr_snapshot
- pipeline_config_refs.md:1635: - pipeline_config_refs.md:1203: - tests\queue\test_job_model.py:13: def test_job_dict_does_not_include_pipeline_config():
- pipeline_config_refs.md:1636: - pipeline_config_refs.md:1204: - tests\queue\test_job_model.py:16: assert "pipeline_config" not in as_dict
- pipeline_config_refs.md:1637: - pipeline_config_refs.md:1207: - tests\queue\test_job_service_pipeline_integration_v2.py:234: """submit_direct() passes job with correct pipeline_config."""
- pipeline_config_refs.md:1638: - pipeline_config_refs.md:1208: - tests\queue\test_job_service_pipeline_integration_v2.py:336: """submit_queued() passes job with correct pipeline_config."""
- pipeline_config_refs.md:1639: - pipeline_config_refs.md:1211: - tests\queue\test_job_variant_metadata_v2.py:9: def _make_pipeline_config() -> PipelineConfig:
- pipeline_config_refs.md:1640: - pipeline_config_refs.md:1212: - tests\queue\test_job_variant_metadata_v2.py:27: "pipeline_config": _make_pipeline_config(),
- pipeline_config_refs.md:1641: - pipeline_config_refs.md:1215: - tests\queue\test_queue_njr_path.py:5: - Execution uses NJR-only path for new jobs (pipeline_config is None)
- pipeline_config_refs.md:1642: - pipeline_config_refs.md:1216: - tests\queue\test_queue_njr_path.py:6: - Legacy pipeline_config-only jobs still work but are marked as legacy
- pipeline_config_refs.md:1643: - pipeline_config_refs.md:1217: - tests\queue\test_queue_njr_path.py:60: assert getattr(retrieved, "pipeline_config", None) is None
- pipeline_config_refs.md:1644: - pipeline_config_refs.md:1218: - tests\queue\test_queue_njr_path.py:63: """Job with NJR should execute via NJR path only (no pipeline_config fallback)."""
- pipeline_config_refs.md:1645: - pipeline_config_refs.md:1219: - tests\queue\test_queue_njr_path.py:81: # 3. NOT fall back to pipeline_config even if _run_job fails
- pipeline_config_refs.md:1646: - pipeline_config_refs.md:1220: - tests\queue\test_queue_njr_path.py:85: # pipeline_config should remain None for NJR-only jobs
- pipeline_config_refs.md:1647: - pipeline_config_refs.md:1221: - tests\queue\test_queue_njr_path.py:86: assert getattr(retrieved, "pipeline_config", None) is None
- pipeline_config_refs.md:1648: - pipeline_config_refs.md:1222: - tests\queue\test_queue_njr_path.py:88: def test_legacy_pipeline_config_only_job(self, tmp_path: Path):
- pipeline_config_refs.md:1649: - pipeline_config_refs.md:1223: - tests\queue\test_queue_njr_path.py:89: """Legacy job with only pipeline_config (no NJR) should still work."""
- pipeline_config_refs.md:1650: - pipeline_config_refs.md:1224: - tests\queue\test_queue_njr_path.py:99: job.pipeline_config = PipelineConfig(
- pipeline_config_refs.md:1651: - pipeline_config_refs.md:1225: - tests\queue\test_queue_njr_path.py:115: assert getattr(retrieved, "pipeline_config", None) is not None
- pipeline_config_refs.md:1652: - pipeline_config_refs.md:1226: - tests\queue\test_queue_njr_path.py:152: def test_new_jobs_dont_rely_on_pipeline_config_for_execution(self, tmp_path: Path):
- pipeline_config_refs.md:1653: - pipeline_config_refs.md:1227: - tests\queue\test_queue_njr_path.py:153: """PR-CORE1-B2: New queue jobs should not rely on pipeline_config for execution."""
- pipeline_config_refs.md:1654: - pipeline_config_refs.md:1228: - tests\queue\test_queue_njr_path.py:167: # pipeline_config is intentionally absent for new NJR-only jobs
- pipeline_config_refs.md:1655: - pipeline_config_refs.md:1229: - tests\queue\test_queue_njr_path.py:175: assert getattr(retrieved, "pipeline_config", None) is None
- pipeline_config_refs.md:1656: - pipeline_config_refs.md:1230: - tests\queue\test_queue_njr_path.py:176: # PR-CORE1-B2 contract: Execution MUST use _normalized_record, not pipeline_config
- pipeline_config_refs.md:1659: - repo_inventory.json:353: "path": "src/controller/pipeline_config_assembler.py",
- pipeline_config_refs.md:1660: - repo_inventory.json:354: "module": "src.controller.pipeline_config_assembler",
- pipeline_config_refs.md:1661: - repo_inventory.json:395: "src.controller.pipeline_config_assembler",
- pipeline_config_refs.md:1662: - repo_inventory.json:1548: "src.gui.pipeline_config_panel",
- pipeline_config_refs.md:1663: - repo_inventory.json:1624: "path": "src/gui/views/pipeline_config_panel.py",
- pipeline_config_refs.md:1664: - repo_inventory.json:1625: "module": "src.gui.views.pipeline_config_panel",
- pipeline_config_refs.md:1665: - repo_inventory.json:2890: "path": "tests/controller/test_pipeline_config_assembler.py",
- pipeline_config_refs.md:1666: - repo_inventory.json:2891: "module": "tests.controller.test_pipeline_config_assembler",
- pipeline_config_refs.md:1667: - repo_inventory.json:2897: "src.controller.pipeline_config_assembler"
- pipeline_config_refs.md:1668: - repo_inventory.json:2902: "path": "tests/controller/test_pipeline_config_assembler_core_fields.py",
- pipeline_config_refs.md:1669: - repo_inventory.json:2903: "module": "tests.controller.test_pipeline_config_assembler_core_fields",
- pipeline_config_refs.md:1670: - repo_inventory.json:2910: "src.controller.pipeline_config_assembler"
- pipeline_config_refs.md:1671: - repo_inventory.json:2915: "path": "tests/controller/test_pipeline_config_assembler_model_fields.py",
- pipeline_config_refs.md:1672: - repo_inventory.json:2916: "module": "tests.controller.test_pipeline_config_assembler_model_fields",
- pipeline_config_refs.md:1673: - repo_inventory.json:2922: "src.controller.pipeline_config_assembler"
- pipeline_config_refs.md:1674: - repo_inventory.json:2927: "path": "tests/controller/test_pipeline_config_assembler_negative_prompt.py",
- pipeline_config_refs.md:1675: - repo_inventory.json:2928: "module": "tests.controller.test_pipeline_config_assembler_negative_prompt",
- pipeline_config_refs.md:1676: - repo_inventory.json:2934: "src.controller.pipeline_config_assembler"
- pipeline_config_refs.md:1677: - repo_inventory.json:2939: "path": "tests/controller/test_pipeline_config_assembler_output_settings.py",
- pipeline_config_refs.md:1678: - repo_inventory.json:2940: "module": "tests.controller.test_pipeline_config_assembler_output_settings",
- pipeline_config_refs.md:1679: - repo_inventory.json:2946: "src.controller.pipeline_config_assembler"
- pipeline_config_refs.md:1680: - repo_inventory.json:2951: "path": "tests/controller/test_pipeline_config_assembler_resolution.py",
- pipeline_config_refs.md:1681: - repo_inventory.json:2952: "module": "tests.controller.test_pipeline_config_assembler_resolution",
- pipeline_config_refs.md:1682: - repo_inventory.json:2958: "src.controller.pipeline_config_assembler"
- pipeline_config_refs.md:1683: - repo_inventory.json:2973: "src.controller.pipeline_config_assembler",
- pipeline_config_refs.md:1684: - repo_inventory.json:3302: "path": "tests/gui_v2/test_gui_v2_pipeline_config_roundtrip.py",
- pipeline_config_refs.md:1685: - repo_inventory.json:3303: "module": "tests.gui_v2.test_gui_v2_pipeline_config_roundtrip",
- pipeline_config_refs.md:1688: - reports\file_access\CLEANHOUSE_REPORT_V2_5_2025_11_26.md:30: - `src/controller/pipeline_config_assembler.py` | touched: false | reachable_from_main: true
- pipeline_config_refs.md:1689: - reports\file_access\CLEANHOUSE_REPORT_V2_5_2025_11_26.md:164: - `tests/controller/test_pipeline_config_assembler.py` | touched: false | reachable_from_main: false | TEST
- pipeline_config_refs.md:1690: - reports\file_access\CLEANHOUSE_REPORT_V2_5_2025_11_26.md:165: - `tests/controller/test_pipeline_config_assembler_core_fields.py` | touched: false | reachable_from_main: false | TEST
- pipeline_config_refs.md:1691: - reports\file_access\CLEANHOUSE_REPORT_V2_5_2025_11_26.md:166: - `tests/controller/test_pipeline_config_assembler_model_fields.py` | touched: false | reachable_from_main: false | TEST
- pipeline_config_refs.md:1692: - reports\file_access\CLEANHOUSE_REPORT_V2_5_2025_11_26.md:167: - `tests/controller/test_pipeline_config_assembler_negative_prompt.py` | touched: false | reachable_from_main: false | TEST
- pipeline_config_refs.md:1693: - reports\file_access\CLEANHOUSE_REPORT_V2_5_2025_11_26.md:168: - `tests/controller/test_pipeline_config_assembler_output_settings.py` | touched: false | reachable_from_main: false | TEST
- pipeline_config_refs.md:1694: - reports\file_access\CLEANHOUSE_REPORT_V2_5_2025_11_26.md:169: - `tests/controller/test_pipeline_config_assembler_resolution.py` | touched: false | reachable_from_main: false | TEST
- pipeline_config_refs.md:1695: - reports\file_access\CLEANHOUSE_REPORT_V2_5_2025_11_26.md:228: - `tests/gui_v2/test_gui_v2_pipeline_config_roundtrip.py` | touched: false | reachable_from_main: false | TEST
- pipeline_config_refs.md:1698: - reports\file_access\file_access_summary.csv:28: src/controller/pipeline_config_assembler.py,false,,true,true,false,false,false,A_RUNTIME_CORE,
- pipeline_config_refs.md:1699: - reports\file_access\file_access_summary.csv:152: tests/controller/test_pipeline_config_assembler.py,false,,false,false,true,false,false,C_TEST,
- pipeline_config_refs.md:1700: - reports\file_access\file_access_summary.csv:153: tests/controller/test_pipeline_config_assembler_core_fields.py,false,,false,false,true,false,false,C_TEST,
- pipeline_config_refs.md:1701: - reports\file_access\file_access_summary.csv:154: tests/controller/test_pipeline_config_assembler_model_fields.py,false,,false,false,true,false,false,C_TEST,
- pipeline_config_refs.md:1702: - reports\file_access\file_access_summary.csv:155: tests/controller/test_pipeline_config_assembler_negative_prompt.py,false,,false,false,true,false,false,C_TEST,
- pipeline_config_refs.md:1703: - reports\file_access\file_access_summary.csv:156: tests/controller/test_pipeline_config_assembler_output_settings.py,false,,false,false,true,false,false,C_TEST,
- pipeline_config_refs.md:1704: - reports\file_access\file_access_summary.csv:157: tests/controller/test_pipeline_config_assembler_resolution.py,false,,false,false,true,false,false,C_TEST,
- pipeline_config_refs.md:1705: - reports\file_access\file_access_summary.csv:216: tests/gui_v2/test_gui_v2_pipeline_config_roundtrip.py,false,,false,false,true,false,false,C_TEST,
- pipeline_config_refs.md:1707: ## scripts\list_pipeline_config_refs.py
- pipeline_config_refs.md:1708: - scripts\list_pipeline_config_refs.py:3: Generate pipeline_config_refs.md listing all occurrences of "pipeline_config"
- pipeline_config_refs.md:1709: - scripts\list_pipeline_config_refs.py:16: OUTPUT = ROOT / "pipeline_config_refs.md"
- pipeline_config_refs.md:1710: - scripts\list_pipeline_config_refs.py:21: "pipeline_config",
- pipeline_config_refs.md:1711: - scripts\list_pipeline_config_refs.py:53: f.write("# pipeline_config references (excluding archive/.git/zip)\n\n")
- pipeline_config_refs.md:1714: - snapshots\repo_inventory.json:78: "path": "pipeline_config_refs.md",
- pipeline_config_refs.md:1715: - snapshots\repo_inventory.json:778: "path": "archive/legacy_tests/tests_gui_v2_legacy/test_gui_v2_pipeline_config_roundtrip.py",
- pipeline_config_refs.md:1716: - snapshots\repo_inventory.json:5248: "path": "scripts/list_pipeline_config_refs.py",
- pipeline_config_refs.md:1717: - snapshots\repo_inventory.json:5403: "path": "src/controller/pipeline_config_assembler.py",
- pipeline_config_refs.md:1718: - snapshots\repo_inventory.json:5713: "path": "src/gui/panels_v2/pipeline_config_panel_v2.py",
- pipeline_config_refs.md:1719: - snapshots\repo_inventory.json:5853: "path": "src/gui/views/pipeline_config_panel.py",
- pipeline_config_refs.md:1720: - snapshots\repo_inventory.json:6823: "path": "tests/controller/test_pipeline_config_assembler.py",
- pipeline_config_refs.md:1721: - snapshots\repo_inventory.json:6828: "path": "tests/controller/test_pipeline_config_assembler_core_fields.py",
- pipeline_config_refs.md:1722: - snapshots\repo_inventory.json:6833: "path": "tests/controller/test_pipeline_config_assembler_model_fields.py",
- pipeline_config_refs.md:1723: - snapshots\repo_inventory.json:6838: "path": "tests/controller/test_pipeline_config_assembler_negative_prompt.py",
- pipeline_config_refs.md:1724: - snapshots\repo_inventory.json:6843: "path": "tests/controller/test_pipeline_config_assembler_output_settings.py",
- pipeline_config_refs.md:1725: - snapshots\repo_inventory.json:6848: "path": "tests/controller/test_pipeline_config_assembler_resolution.py",
- pipeline_config_refs.md:1726: - snapshots\repo_inventory.json:7158: "path": "tests/gui_v2/test_pipeline_config_panel_lora_runtime.py",
- pipeline_config_refs.md:1729: - src\controller\app_controller.py:5: Runtime pipeline execution via pipeline_config has been REMOVED.
- pipeline_config_refs.md:1730: - src\controller\app_controller.py:7: Use PipelineController + NJR path for all new code. Do not add pipeline_config-based
- pipeline_config_refs.md:1731: - src\controller\app_controller.py:767: "error": "Job is missing normalized_record; legacy/pipeline_config execution is disabled.",
- pipeline_config_refs.md:1732: - src\controller\app_controller.py:1250: def _validate_pipeline_config(self) -> tuple[bool, str]:
- pipeline_config_refs.md:1733: - src\controller\app_controller.py:1251: """DEPRECATED (PR-CORE1-12): Legacy validation for pipeline_config panel.
- pipeline_config_refs.md:1734: - src\controller\app_controller.py:1266: # PR-CORE1-12: pipeline_config_panel_v2 is DEPRECATED - no longer wired in GUI V2
- pipeline_config_refs.md:1735: - src\controller\app_controller.py:1267: panel = getattr(self.main_window, "pipeline_config_panel_v2", None)
- pipeline_config_refs.md:1736: - src\controller\app_controller.py:1503: def _execute_pipeline_via_runner(self, pipeline_config: PipelineConfig) -> Any:
- pipeline_config_refs.md:1737: - src\controller\app_controller.py:1504: """DEPRECATED (PR-CORE1-12): Legacy pipeline_config execution removed.
- pipeline_config_refs.md:1738: - src\controller\app_controller.py:1512: RuntimeError: Always - pipeline_config execution is disabled.
- pipeline_config_refs.md:1739: - src\controller\app_controller.py:1516: def _run_pipeline_from_tab(self, pipeline_tab: Any, pipeline_config: PipelineConfig) -> Any:
- pipeline_config_refs.md:1740: - src\controller\app_controller.py:1517: """DEPRECATED (PR-CORE1-12): Legacy tab-based pipeline_config execution.
- pipeline_config_refs.md:1741: - src\controller\app_controller.py:1619: def _run_pipeline_via_runner_only(self, pipeline_config: PipelineConfig) -> Any:
- pipeline_config_refs.md:1742: - src\controller\app_controller.py:1629: RuntimeError: Always - pipeline_config execution is disabled.
- pipeline_config_refs.md:1743: - src\controller\app_controller.py:1701: is_valid, message = self._validate_pipeline_config()
- pipeline_config_refs.md:1744: - src\controller\app_controller.py:1746: pipeline_config = self.build_pipeline_config_v2()
- pipeline_config_refs.md:1745: - src\controller\app_controller.py:1748: executor_config = self.pipeline_runner._build_executor_config(pipeline_config)
- pipeline_config_refs.md:1746: - src\controller\app_controller.py:1749: self._cache_last_run_payload(executor_config, pipeline_config)
- pipeline_config_refs.md:1747: - src\controller\app_controller.py:1750: self.pipeline_runner.run(pipeline_config, cancel_token, self._append_log_threadsafe)
- pipeline_config_refs.md:1748: - src\controller\app_controller.py:1770: def _cache_last_run_payload(self, executor_config: dict[str, Any], pipeline_config: PipelineConfig) -> None:
- pipeline_config_refs.md:1749: - src\controller\app_controller.py:1771: """DEPRECATED (PR-CORE1-12): Legacy payload caching for pipeline_config.
- pipeline_config_refs.md:1750: - src\controller\app_controller.py:1773: This cached pipeline_config for debugging/replay. No longer used since
- pipeline_config_refs.md:1751: - src\controller\app_controller.py:1782: "prompt": pipeline_config.prompt,
- pipeline_config_refs.md:1752: - src\controller\app_controller.py:1783: "pack_name": pipeline_config.pack_name,
- pipeline_config_refs.md:1753: - src\controller\app_controller.py:1784: "preset_name": pipeline_config.preset_name,
- pipeline_config_refs.md:1754: - src\controller\app_controller.py:1863: # PR-CORE1-12: pipeline_config_panel_v2 is DEPRECATED - no longer wired in GUI V2
- pipeline_config_refs.md:1755: - src\controller\app_controller.py:1864: pipeline_panel = getattr(self.main_window, "pipeline_config_panel_v2", None)
- pipeline_config_refs.md:1756: - src\controller\app_controller.py:2181: # PR-CORE1-12: pipeline_config_panel_v2 is DEPRECATED - no longer wired in GUI V2
- pipeline_config_refs.md:1757: - src\controller\app_controller.py:2182: pipeline_config_panel = getattr(self.main_window, "pipeline_config_panel_v2", None)
- pipeline_config_refs.md:1758: - src\controller\app_controller.py:2183: if pipeline_config_panel and hasattr(pipeline_config_panel, "apply_run_config"):
- pipeline_config_refs.md:1759: - src\controller\app_controller.py:2185: pipeline_config_panel.apply_run_config(preset_config)
- pipeline_config_refs.md:1760: - src\controller\app_controller.py:2456: def build_pipeline_config_v2(self) -> PipelineConfig:
- pipeline_config_refs.md:1761: - src\controller\app_controller.py:2457: """DEPRECATED (PR-CORE1-12): Legacy pipeline_config builder.
- pipeline_config_refs.md:1762: - src\controller\app_controller.py:2465: return self._build_pipeline_config()
- pipeline_config_refs.md:1763: - src\controller\app_controller.py:2467: def _build_pipeline_config(self) -> PipelineConfig:
- pipeline_config_refs.md:1764: - src\controller\app_controller.py:2468: """DEPRECATED (PR-CORE1-12): Internal pipeline_config builder.
- pipeline_config_refs.md:1765: - src\controller\app_controller.py:2470: NOTE: Still used by PipelineController._build_pipeline_config_from_state()
- pipeline_config_refs.md:1766: - src\controller\app_controller.py:2753: # PR-CORE1-12: pipeline_config_panel_v2 is DEPRECATED - no longer wired in GUI V2
- pipeline_config_refs.md:1767: - src\controller\app_controller.py:2754: panel = getattr(self.main_window, "pipeline_config_panel_v2", None)
- pipeline_config_refs.md:1768: - src\controller\app_controller.py:2869: # PR-CORE1-12: pipeline_config_panel_v2 is DEPRECATED - no longer wired in GUI V2
- pipeline_config_refs.md:1769: - src\controller\app_controller.py:2870: pipeline_config_panel = getattr(self.main_window, "pipeline_config_panel_v2", None)
- pipeline_config_refs.md:1770: - src\controller\app_controller.py:2871: if pipeline_config_panel and hasattr(pipeline_config_panel, "apply_run_config"):
- pipeline_config_refs.md:1771: - src\controller\app_controller.py:2873: pipeline_config_panel.apply_run_config(pack_config)
- pipeline_config_refs.md:1772: - src\controller\app_controller.py:3101: # PR-CORE1-12: pipeline_config_panel_v2 is DEPRECATED - no longer wired in GUI V2
- pipeline_config_refs.md:1773: - src\controller\app_controller.py:3102: pipeline_config_panel = getattr(self.main_window, "pipeline_config_panel_v2", None)
- pipeline_config_refs.md:1774: - src\controller\app_controller.py:3103: if pipeline_config_panel and hasattr(pipeline_config_panel, "apply_run_config"):
- pipeline_config_refs.md:1775: - src\controller\app_controller.py:3105: pipeline_config_panel.apply_run_config(preset_config)
- pipeline_config_refs.md:1778: - src\controller\archive\README.md:12: #### `pipeline_config_assembler.py`
- pipeline_config_refs.md:1781: - src\controller\job_history_service.py:223: Prefers NJR snapshot data. Legacy pipeline_config-only jobs no longer
- pipeline_config_refs.md:1784: - src\controller\job_service.py:305: # PR-CORE1-B3/C2: NJR-backed jobs are purely NJR-only and don't store pipeline_config.
- pipeline_config_refs.md:1787: - src\controller\pipeline_controller.py:37: from src.pipeline.legacy_njr_adapter import build_njr_from_legacy_pipeline_config
- pipeline_config_refs.md:1788: - src\controller\pipeline_controller.py:40: from src.controller.archive.pipeline_config_assembler import PipelineConfigAssembler, GuiOverrides
- pipeline_config_refs.md:1789: - src\controller\pipeline_controller.py:199: def _build_pipeline_config_from_state(self) -> PipelineConfig:
- pipeline_config_refs.md:1790: - src\controller\pipeline_controller.py:236: base_config = self._build_pipeline_config_from_state()
- pipeline_config_refs.md:1791: - src\controller\pipeline_controller.py:385: PR-CORE1-B3: NJR-backed jobs MUST NOT carry pipeline_config. The field may
- pipeline_config_refs.md:1792: - src\controller\pipeline_controller.py:535: def build_pipeline_config_with_profiles(
- pipeline_config_refs.md:1793: - src\controller\pipeline_controller.py:851: config = self._build_pipeline_config_from_state()
- pipeline_config_refs.md:1794: - src\controller\pipeline_controller.py:1301: Legacy pipeline_config execution is retired in CORE1-C2.
- pipeline_config_refs.md:1795: - src\controller\pipeline_controller.py:1555: This method converts pipeline_config to NJR using legacy adapter, then
- pipeline_config_refs.md:1796: - src\controller\pipeline_controller.py:1567: record = build_njr_from_legacy_pipeline_config(config)
- pipeline_config_refs.md:1797: - src\controller\pipeline_controller.py:1573: record = build_njr_from_legacy_pipeline_config(config)
- pipeline_config_refs.md:1800: - src\gui\dropdown_loader_v2.py:61: panel = getattr(sidebar, "pipeline_config_panel", None)
- pipeline_config_refs.md:1803: - src\gui\main_window_v2.py:187: if hasattr(self, "pipeline_tab") and hasattr(self.pipeline_tab, "pipeline_config_panel"):
- pipeline_config_refs.md:1804: - src\gui\main_window_v2.py:189: self.pipeline_tab.pipeline_config_panel.controller = controller
- pipeline_config_refs.md:1807: - src\gui\panels_v2\__init__.py:9: # from src.gui.panels_v2.pipeline_config_panel_v2 import PipelineConfigPanel
- pipeline_config_refs.md:1810: - src\gui\panels_v2\archive\README.md:12: #### `pipeline_config_panel_v2.py`
- pipeline_config_refs.md:1813: - src\gui\panels_v2\layout_manager_v2.py:62: mw.pipeline_config_panel_v2 = getattr(getattr(mw.pipeline_tab, "sidebar", None), "pipeline_config_panel", None)
- pipeline_config_refs.md:1816: - src\gui\pipeline_panel_v2.py:297: config = getattr(job, "config_snapshot", None) or getattr(job, "pipeline_config", None) or {}
- pipeline_config_refs.md:1819: - src\gui\preview_panel_v2.py:4: All display data comes from NJR snapshots, never from pipeline_config.
- pipeline_config_refs.md:1822: - src\gui\sidebar_panel_v2.py:226: self.pipeline_config_card = _SidebarCard(
- pipeline_config_refs.md:1823: - src\gui\sidebar_panel_v2.py:229: build_child=lambda parent: self._build_pipeline_config_section(parent),
- pipeline_config_refs.md:1824: - src\gui\sidebar_panel_v2.py:231: self.pipeline_config_card.grid(row=3, column=0, sticky="ew", padx=8, pady=(0, 4))
- pipeline_config_refs.md:1825: - src\gui\sidebar_panel_v2.py:872: def _build_pipeline_config_section(self, parent: ttk.Frame) -> ttk.Frame:
- pipeline_config_refs.md:1826: - src\gui\sidebar_panel_v2.py:876: was wired to pipeline_config execution, which is removed in v2.6.
- pipeline_config_refs.md:1827: - src\gui\sidebar_panel_v2.py:881: # from src.gui.panels_v2.pipeline_config_panel_v2 import PipelineConfigPanel
- pipeline_config_refs.md:1828: - src\gui\sidebar_panel_v2.py:886: # PR-CORE1-12: Stages section and pipeline_config_panel creation disabled
- pipeline_config_refs.md:1829: - src\gui\sidebar_panel_v2.py:892: # self.pipeline_config_panel = PipelineConfigPanel(
- pipeline_config_refs.md:1830: - src\gui\sidebar_panel_v2.py:898: # self.pipeline_config_panel.pack(fill="both", expand=True)
- pipeline_config_refs.md:1833: - src\gui\views\archive\README.md:12: #### `pipeline_config_panel.py`
- pipeline_config_refs.md:1836: - src\history\history_migration_engine.py:16: build_njr_from_legacy_pipeline_config,
- pipeline_config_refs.md:1837: - src\history\history_migration_engine.py:22: "pipeline_config",
- pipeline_config_refs.md:1838: - src\history\history_migration_engine.py:161: def _coerce_pipeline_config(self, data: Mapping[str, Any]) -> PipelineConfig:
- pipeline_config_refs.md:1841: - src\history\history_record.py:11: "pipeline_config",
- pipeline_config_refs.md:1844: - src\history\history_schema_v26.py:26: "pipeline_config",
- pipeline_config_refs.md:1847: - src\learning\learning_record_builder.py:40: pipeline_config: PipelineConfig,
- pipeline_config_refs.md:1848: - src\learning\learning_record_builder.py:48: config_dict = asdict(pipeline_config)
- pipeline_config_refs.md:1851: - src\pipeline\job_models_v2.py:78: the NJR snapshot stored in Job.snapshot, not from Job.pipeline_config.
- pipeline_config_refs.md:1852: - src\pipeline\job_models_v2.py:80: PR-CORE1-12: pipeline_config is DEPRECATED. Legacy jobs without NJR
- pipeline_config_refs.md:1853: - src\pipeline\job_models_v2.py:81: snapshots may fall back to pipeline_config, but all new jobs use NJR only.
- pipeline_config_refs.md:1854: - src\pipeline\job_models_v2.py:105: the NJR snapshot stored in history entries, not from pipeline_config.
- pipeline_config_refs.md:1855: - src\pipeline\job_models_v2.py:107: PR-CORE1-12: pipeline_config is DEPRECATED. Legacy history entries without
- pipeline_config_refs.md:1856: - src\pipeline\job_models_v2.py:108: NJR snapshots may fall back to pipeline_config, but all new jobs use NJR only.
- pipeline_config_refs.md:1857: - src\pipeline\job_models_v2.py:444: PR-CORE1-12: pipeline_config is DEPRECATED and removed from runtime execution.
- pipeline_config_refs.md:1858: - src\pipeline\job_models_v2.py:445: During early CORE1-A/B hybrid state, Job.pipeline_config was the execution payload,
- pipeline_config_refs.md:1859: - src\pipeline\job_models_v2.py:447: Full NJR-only execution is enforced for all new jobs; pipeline_config is
- pipeline_config_refs.md:1862: - src\pipeline\legacy_njr_adapter.py:58: def build_njr_from_legacy_pipeline_config(pipeline_config: PipelineConfig) -> NormalizedJobRecord:
- pipeline_config_refs.md:1863: - src\pipeline\legacy_njr_adapter.py:67: config_snapshot = asdict(pipeline_config)
- pipeline_config_refs.md:1864: - src\pipeline\legacy_njr_adapter.py:68: stage = _make_default_stage(pipeline_config)
- pipeline_config_refs.md:1865: - src\pipeline\legacy_njr_adapter.py:69: metadata = dict(pipeline_config.metadata or {})
- pipeline_config_refs.md:1866: - src\pipeline\legacy_njr_adapter.py:87: positive_prompt=pipeline_config.prompt or "",
- pipeline_config_refs.md:1867: - src\pipeline\legacy_njr_adapter.py:88: negative_prompt=pipeline_config.negative_prompt or "",
- pipeline_config_refs.md:1868: - src\pipeline\legacy_njr_adapter.py:93: steps=pipeline_config.steps or 20,
- pipeline_config_refs.md:1869: - src\pipeline\legacy_njr_adapter.py:94: cfg_scale=pipeline_config.cfg_scale or 7.0,
- pipeline_config_refs.md:1870: - src\pipeline\legacy_njr_adapter.py:95: width=pipeline_config.width or 512,
- pipeline_config_refs.md:1871: - src\pipeline\legacy_njr_adapter.py:96: height=pipeline_config.height or 512,
- pipeline_config_refs.md:1872: - src\pipeline\legacy_njr_adapter.py:97: sampler_name=pipeline_config.sampler or "Euler a",
- pipeline_config_refs.md:1873: - src\pipeline\legacy_njr_adapter.py:98: scheduler=getattr(pipeline_config, "scheduler", "") or "",
- pipeline_config_refs.md:1874: - src\pipeline\legacy_njr_adapter.py:99: base_model=pipeline_config.model or "unknown",
- pipeline_config_refs.md:1875: - src\pipeline\legacy_njr_adapter.py:117: "legacy_source": "pipeline_config",
- pipeline_config_refs.md:1876: - src\pipeline\legacy_njr_adapter.py:167: pipeline_config = data.get("pipeline_config")
- pipeline_config_refs.md:1877: - src\pipeline\legacy_njr_adapter.py:168: if isinstance(pipeline_config, PipelineConfig):
- pipeline_config_refs.md:1878: - src\pipeline\legacy_njr_adapter.py:169: return build_njr_from_legacy_pipeline_config(pipeline_config)
- pipeline_config_refs.md:1879: - src\pipeline\legacy_njr_adapter.py:170: if isinstance(pipeline_config, Mapping):
- pipeline_config_refs.md:1880: - src\pipeline\legacy_njr_adapter.py:172: prompt=str(pipeline_config.get("prompt", "") or ""),
- pipeline_config_refs.md:1881: - src\pipeline\legacy_njr_adapter.py:173: model=_normalize_model_name(pipeline_config.get("model", "") or pipeline_config.get("model_name", "")),
- pipeline_config_refs.md:1882: - src\pipeline\legacy_njr_adapter.py:174: sampler=str(pipeline_config.get("sampler", "") or pipeline_config.get("sampler_name", "") or "Euler a"),
- pipeline_config_refs.md:1883: - src\pipeline\legacy_njr_adapter.py:175: width=_coerce_int(pipeline_config.get("width", 512), 512),
- pipeline_config_refs.md:1884: - src\pipeline\legacy_njr_adapter.py:176: height=_coerce_int(pipeline_config.get("height", 512), 512),
- pipeline_config_refs.md:1885: - src\pipeline\legacy_njr_adapter.py:177: steps=_coerce_int(pipeline_config.get("steps", 20), 20),
- pipeline_config_refs.md:1886: - src\pipeline\legacy_njr_adapter.py:178: cfg_scale=_coerce_float(pipeline_config.get("cfg_scale", 7.0), 7.0),
- pipeline_config_refs.md:1887: - src\pipeline\legacy_njr_adapter.py:179: negative_prompt=str(pipeline_config.get("negative_prompt", "") or ""),
- pipeline_config_refs.md:1888: - src\pipeline\legacy_njr_adapter.py:180: metadata=dict(pipeline_config.get("metadata") or {}),
- pipeline_config_refs.md:1889: - src\pipeline\legacy_njr_adapter.py:182: return build_njr_from_legacy_pipeline_config(config)
- pipeline_config_refs.md:1892: - src\pipeline\pipeline_runner.py:415: config = self._pipeline_config_from_njr(record)
- pipeline_config_refs.md:1893: - src\pipeline\pipeline_runner.py:418: def _pipeline_config_from_njr(self, record: NormalizedJobRecord) -> PipelineConfig:
- pipeline_config_refs.md:1896: - src\pipeline\stage_sequencer.py:262: plan = sequencer.build_plan(pipeline_config)
- pipeline_config_refs.md:1897: - src\pipeline\stage_sequencer.py:265: def build_plan(self, pipeline_config: dict[str, Any]) -> StageExecutionPlan:
- pipeline_config_refs.md:1898: - src\pipeline\stage_sequencer.py:269: pipeline_config: Dictionary containing stage configurations and flags.
- pipeline_config_refs.md:1899: - src\pipeline\stage_sequencer.py:278: return build_stage_execution_plan(pipeline_config)
- pipeline_config_refs.md:1902: - src\queue\job_history_store.py:8: NormalizedJobRecord data. Legacy entries on disk may still expose pipeline_config
- pipeline_config_refs.md:1903: - src\queue\job_history_store.py:9: blobs, but new entries no longer persist pipeline_config—legacy_njr_adapter
- pipeline_config_refs.md:1906: - src\queue\job_queue.py:7: for execution. The pipeline_config field is legacy-only and should not be relied
- pipeline_config_refs.md:1909: - src\services\queue_store_v2.py:29: "pipeline_config",
- pipeline_config_refs.md:1910: - src\services\queue_store_v2.py:49: "pipeline_config",
- pipeline_config_refs.md:1913: - src\utils\snapshot_builder_v2.py:35: def _serialize_pipeline_config(config: Any) -> dict[str, Any]:
- pipeline_config_refs.md:1914: - src\utils\snapshot_builder_v2.py:188: "config": _serialize_pipeline_config(record.config),
- pipeline_config_refs.md:1917: - test_adetailer_sync.py:10: from src.gui.panels_v2.pipeline_config_panel_v2 import PipelineConfigPanel
- pipeline_config_refs.md:1920: - test_output.txt:60: tests\controller\test_pipeline_config_assembler.py ...                   [ 14%]
- pipeline_config_refs.md:1921: - test_output.txt:61: tests\controller\test_pipeline_config_assembler_core_fields.py ..        [ 14%]
- pipeline_config_refs.md:1922: - test_output.txt:62: tests\controller\test_pipeline_config_assembler_model_fields.py .        [ 14%]
- pipeline_config_refs.md:1923: - test_output.txt:63: tests\controller\test_pipeline_config_assembler_negative_prompt.py .     [ 14%]
- pipeline_config_refs.md:1924: - test_output.txt:64: tests\controller\test_pipeline_config_assembler_output_settings.py .     [ 14%]
- pipeline_config_refs.md:1925: - test_output.txt:65: tests\controller\test_pipeline_config_assembler_resolution.py .          [ 14%]
- pipeline_config_refs.md:1928: - tests\compat\data\history_compat_v2\history_v2_0_pre_njr.jsonl:1: {"job_id":"legacy-001","timestamp":"2023-01-01T00:00:00Z","status":"completed","pipeline_config":{"prompt":"legacy prompt 001","model":"sdxl","steps":20,"cfg_scale":7.0,"sampler":"Euler a","width":512,"height":512},"result":{"run_id":"legacy-001","success":true,"variants":[],"learning_records":[],"metadata":{"source":"legacy"}}}
- pipeline_config_refs.md:1929: - tests\compat\data\history_compat_v2\history_v2_0_pre_njr.jsonl:2: {"job_id":"legacy-002","timestamp":"2023-02-02T00:00:00Z","status":"failed","pipeline_config":{"prompt":"legacy prompt 002","model":"sdxl","steps":25,"cfg_scale":6.5,"sampler":"Euler a","width":640,"height":640},"error_message":"boom","result":{"run_id":"legacy-002","success":false,"error":"boom","variants":[],"learning_records":[],"metadata":{"source":"legacy"}}}
- pipeline_config_refs.md:1930: - tests\compat\data\history_compat_v2\history_v2_0_pre_njr.jsonl:3: {"job_id":"legacy-003","timestamp":"2023-03-03T00:00:00Z","status":"completed","pipeline_config":{"prompt":"legacy prompt 003","model":"sdxl","steps":15,"cfg_scale":8.0,"sampler":"Euler a","width":768,"height":768},"result":{"run_id":"legacy-003","success":true,"variants":[],"learning_records":[],"metadata":{"source":"legacy"}}}
- pipeline_config_refs.md:1933: - tests\compat\data\history_compat_v2\history_v2_4_hybrid.jsonl:1: {"job_id":"hybrid-001","timestamp":"2024-04-04T04:04:04Z","status":"failed","snapshot":{"job_id":"hybrid-001","positive_prompt":"hybrid prompt","base_model":"sdxl","steps":26,"cfg_scale":7.5,"normalized_job":{"job_id":"hybrid-001","config":{"prompt":"hybrid prompt","model":"sdxl"}}},"pipeline_config":{"prompt":"hybrid prompt","model":"sdxl","steps":26,"cfg_scale":7.5,"sampler":"Euler a","width":640,"height":640},"result":{"run_id":"hybrid-001","success":false,"error":"oops","variants":[],"learning_records":[],"metadata":{"source":"hybrid"}}}
- pipeline_config_refs.md:1934: - tests\compat\data\history_compat_v2\history_v2_4_hybrid.jsonl:3: {"job_id":"hybrid-003","timestamp":"2024-06-06T06:06:06Z","status":"completed","snapshot":{"normalized_job":{"job_id":"hybrid-003","config":{"prompt":"hybrid three","model":"sdxl","steps":30,"cfg_scale":7.2}}},"pipeline_config":{"prompt":"hybrid three","model":"sdxl","steps":30,"cfg_scale":7.2,"sampler":"Euler a","width":512,"height":512},"result":{"run_id":"hybrid-003","success":true,"variants":[],"learning_records":[],"metadata":{"source":"hybrid"}}}
- pipeline_config_refs.md:1937: - tests\compat\data\queue_compat_v2\queue_state_v2_0.json:1: {"jobs":[{"queue_id":"legacy-queue-001","job_id":"legacy-queue-001","status":"queued","priority":1,"created_at":"2023-01-05T10:00:00Z","pipeline_config":{"prompt":"queue prompt legacy 001","model":"sdxl","steps":20,"cfg_scale":7.0,"sampler":"Euler a","width":512,"height":512}},{"queue_id":"legacy-queue-002","job_id":"legacy-queue-002","status":"running","priority":2,"created_at":"2023-01-06T11:11:00Z","pipeline_config":{"prompt":"queue prompt legacy 002","model":"sdxl","steps":24,"cfg_scale":6.5,"sampler":"Euler a","width":640,"height":640}}],"auto_run_enabled":true,"paused":false,"schema_version":"2.0"}
- pipeline_config_refs.md:1940: - tests\compat\data\queue_compat_v2\queue_state_v2_4_hybrid.json:1: {"jobs":[{"queue_id":"hybrid-queue-001","job_id":"hybrid-queue-001","status":"queued","priority":1,"created_at":"2024-04-04T04:04:00Z","snapshot":{"job_id":"hybrid-queue-001","positive_prompt":"hybrid queue prompt","base_model":"sdxl","steps":30,"cfg_scale":7.25},"pipeline_config":{"prompt":"hybrid queue prompt","model":"sdxl","steps":30,"cfg_scale":7.25,"sampler":"Euler a","width":640,"height":640}},{"queue_id":"hybrid-queue-002","job_id":"hybrid-queue-002","status":"queued","priority":2,"created_at":"2024-04-05T05:05:00Z","njr_snapshot":{"job_id":"hybrid-queue-002","positive_prompt":"hybrid queue nested","base_model":"sdxl","steps":32,"cfg_scale":7.5,"normalized_job":{"job_id":"hybrid-queue-002","config":{"prompt":"hybrid queue nested","model":"sdxl","steps":32,"cfg_scale":7.5}}}}],"auto_run_enabled":false,"paused":true,"schema_version":"2.4"}
- pipeline_config_refs.md:1943: - tests\compat\data\queue_compat_v2\queue_state_v2_6_core1_pre.json:1: {"jobs":[{"queue_id":"core1-queue-001","job_id":"core1-queue-001","status":"queued","priority":1,"created_at":"2025-01-10T10:10:00Z","njr_snapshot":{"job_id":"core1-queue-001","positive_prompt":"core1 queue ready","base_model":"sdxl","steps":40,"cfg_scale":7.8},"_normalized_record":{"job_id":"core1-queue-001"},"pipeline_config":{"prompt":"core1 queue ready","model":"sdxl","steps":40,"cfg_scale":7.8,"sampler":"Euler a","width":768,"height":768},"metadata":{"note":"transitioning"}},{"queue_id":"core1-queue-002","job_id":"core1-queue-002","status":"running","priority":2,"created_at":"2025-01-11T11:11:00Z","njr_snapshot":{"job_id":"core1-queue-002","positive_prompt":"core1 queue run","base_model":"sdxl","steps":42,"cfg_scale":7.9,"normalized_job":{"job_id":"core1-queue-002","config":{"prompt":"core1 queue run","model":"sdxl","steps":42,"cfg_scale":7.9}}}}],"auto_run_enabled":true,"paused":false,"schema_version":"2.6"}
- pipeline_config_refs.md:1946: - tests\controller\archive\test_app_controller_pipeline_integration.py:58: def test_pipeline_config_assembled_from_controller_state(pack_file):
- pipeline_config_refs.md:1947: - tests\controller\archive\test_app_controller_pipeline_integration.py:90: pipeline_config = runner.calls[0][0]
- pipeline_config_refs.md:1948: - tests\controller\archive\test_app_controller_pipeline_integration.py:91: assert isinstance(pipeline_config, PipelineConfig)
- pipeline_config_refs.md:1949: - tests\controller\archive\test_app_controller_pipeline_integration.py:92: assert pipeline_config.model == "SDXL-Lightning"
- pipeline_config_refs.md:1950: - tests\controller\archive\test_app_controller_pipeline_integration.py:93: assert pipeline_config.sampler == "DPM++ 2M"
- pipeline_config_refs.md:1951: - tests\controller\archive\test_app_controller_pipeline_integration.py:94: assert pipeline_config.width == 832
- pipeline_config_refs.md:1952: - tests\controller\archive\test_app_controller_pipeline_integration.py:95: assert pipeline_config.height == 640
- pipeline_config_refs.md:1953: - tests\controller\archive\test_app_controller_pipeline_integration.py:96: assert pipeline_config.steps == 42
- pipeline_config_refs.md:1954: - tests\controller\archive\test_app_controller_pipeline_integration.py:97: assert pipeline_config.cfg_scale == 8.9
- pipeline_config_refs.md:1955: - tests\controller\archive\test_app_controller_pipeline_integration.py:98: assert pipeline_config.pack_name == "alpha"
- pipeline_config_refs.md:1956: - tests\controller\archive\test_app_controller_pipeline_integration.py:99: assert "sunset" in pipeline_config.prompt
- pipeline_config_refs.md:1959: - tests\controller\test_app_controller_lora_runtime.py:88: payload = controller._build_pipeline_config()
- pipeline_config_refs.md:1962: - tests\controller\test_app_controller_njr_exec.py:6: - Rejects jobs without normalized_record (no pipeline_config fallback)
- pipeline_config_refs.md:1963: - tests\controller\test_app_controller_njr_exec.py:92: """Jobs without normalized_record are rejected (no pipeline_config fallback)."""
- pipeline_config_refs.md:1964: - tests\controller\test_app_controller_njr_exec.py:129: def test_payload_job_without_njr_or_pipeline_config_returns_error(self, mock_app_controller):
- pipeline_config_refs.md:1967: - tests\controller\test_app_controller_pipeline_integration.py:56: def test_pipeline_config_assembled_from_controller_state(pack_file):
- pipeline_config_refs.md:1968: - tests\controller\test_app_controller_pipeline_integration.py:88: pipeline_config = runner.calls[0][0]
- pipeline_config_refs.md:1969: - tests\controller\test_app_controller_pipeline_integration.py:89: assert isinstance(pipeline_config, PipelineConfig)
- pipeline_config_refs.md:1970: - tests\controller\test_app_controller_pipeline_integration.py:90: assert pipeline_config.model == "SDXL-Lightning"
- pipeline_config_refs.md:1971: - tests\controller\test_app_controller_pipeline_integration.py:91: assert pipeline_config.sampler == "DPM++ 2M"
- pipeline_config_refs.md:1972: - tests\controller\test_app_controller_pipeline_integration.py:92: assert pipeline_config.width == 832
- pipeline_config_refs.md:1973: - tests\controller\test_app_controller_pipeline_integration.py:93: assert pipeline_config.height == 640
- pipeline_config_refs.md:1974: - tests\controller\test_app_controller_pipeline_integration.py:94: assert pipeline_config.steps == 42
- pipeline_config_refs.md:1975: - tests\controller\test_app_controller_pipeline_integration.py:95: assert pipeline_config.cfg_scale == 8.9
- pipeline_config_refs.md:1976: - tests\controller\test_app_controller_pipeline_integration.py:96: assert pipeline_config.pack_name == "alpha"
- pipeline_config_refs.md:1977: - tests\controller\test_app_controller_pipeline_integration.py:97: assert "sunset" in pipeline_config.prompt
- pipeline_config_refs.md:1980: - tests\controller\test_core_run_path_v2.py:151: """PR-CORE1-B2: Job with NJR that fails execution returns error (no pipeline_config fallback)."""
- pipeline_config_refs.md:1981: - tests\controller\test_core_run_path_v2.py:172: # PR-CORE1-B2: Should return error status, not fall back to pipeline_config
- pipeline_config_refs.md:1982: - tests\controller\test_core_run_path_v2.py:197: assert getattr(queue_job, "pipeline_config", None) is None
- pipeline_config_refs.md:1985: - tests\controller\test_job_construction_b3.py:36: assert getattr(job, "pipeline_config", None) is None
- pipeline_config_refs.md:1987: ## tests\controller\test_pipeline_config_assembler.py
- pipeline_config_refs.md:1988: - tests\controller\test_pipeline_config_assembler.py:1: from src.controller.pipeline_config_assembler import PipelineConfigAssembler, GuiOverrides
- pipeline_config_refs.md:1989: - tests\controller\test_pipeline_config_assembler.py:4: def test_build_pipeline_config_applies_overrides_and_limits():
- pipeline_config_refs.md:1990: - tests\controller\test_pipeline_config_assembler.py:22: def test_build_pipeline_config_includes_metadata():
- pipeline_config_refs.md:1992: ## tests\controller\test_pipeline_config_assembler_core_fields.py
- pipeline_config_refs.md:1993: - tests\controller\test_pipeline_config_assembler_core_fields.py:3: from src.controller.pipeline_config_assembler import GuiOverrides, PipelineConfigAssembler
- pipeline_config_refs.md:1995: ## tests\controller\test_pipeline_config_assembler_model_fields.py
- pipeline_config_refs.md:1996: - tests\controller\test_pipeline_config_assembler_model_fields.py:1: from src.controller.pipeline_config_assembler import GuiOverrides, PipelineConfigAssembler
- pipeline_config_refs.md:1998: ## tests\controller\test_pipeline_config_assembler_negative_prompt.py
- pipeline_config_refs.md:1999: - tests\controller\test_pipeline_config_assembler_negative_prompt.py:1: from src.controller.pipeline_config_assembler import GuiOverrides, PipelineConfigAssembler
- pipeline_config_refs.md:2001: ## tests\controller\test_pipeline_config_assembler_output_settings.py
- pipeline_config_refs.md:2002: - tests\controller\test_pipeline_config_assembler_output_settings.py:1: from src.controller.pipeline_config_assembler import GuiOverrides, PipelineConfigAssembler
- pipeline_config_refs.md:2004: ## tests\controller\test_pipeline_config_assembler_resolution.py
- pipeline_config_refs.md:2005: - tests\controller\test_pipeline_config_assembler_resolution.py:1: from src.controller.pipeline_config_assembler import GuiOverrides, PipelineConfigAssembler
- pipeline_config_refs.md:2008: - tests\controller\test_pipeline_controller_config_path.py:5: from src.controller.pipeline_config_assembler import PipelineConfigAssembler, GuiOverrides
- pipeline_config_refs.md:2011: - tests\controller\test_pipeline_controller_job_specs_v2.py:10: 3. Key pipeline_config fields (model, steps, CFG, etc.) are correctly passed through.
- pipeline_config_refs.md:2012: - tests\controller\test_pipeline_controller_job_specs_v2.py:28: make_minimal_pipeline_config,
- pipeline_config_refs.md:2013: - tests\controller\test_pipeline_controller_job_specs_v2.py:68: config = make_minimal_pipeline_config(model="test-model", seed=12345)
- pipeline_config_refs.md:2014: - tests\controller\test_pipeline_controller_job_specs_v2.py:81: config = make_minimal_pipeline_config()
- pipeline_config_refs.md:2015: - tests\controller\test_pipeline_controller_job_specs_v2.py:98: config = make_minimal_pipeline_config(model="my-special-model")
- pipeline_config_refs.md:2016: - tests\controller\test_pipeline_controller_job_specs_v2.py:110: config = make_minimal_pipeline_config(steps=42)
- pipeline_config_refs.md:2017: - tests\controller\test_pipeline_controller_job_specs_v2.py:122: config = make_minimal_pipeline_config(cfg_scale=9.5)
- pipeline_config_refs.md:2018: - tests\controller\test_pipeline_controller_job_specs_v2.py:134: config = make_minimal_pipeline_config()
- pipeline_config_refs.md:2019: - tests\controller\test_pipeline_controller_job_specs_v2.py:152: config = make_minimal_pipeline_config()
- pipeline_config_refs.md:2020: - tests\controller\test_pipeline_controller_job_specs_v2.py:176: config = make_minimal_pipeline_config(model="base-model")
- pipeline_config_refs.md:2021: - tests\controller\test_pipeline_controller_job_specs_v2.py:193: config = make_minimal_pipeline_config()
- pipeline_config_refs.md:2022: - tests\controller\test_pipeline_controller_job_specs_v2.py:212: config = make_minimal_pipeline_config()
- pipeline_config_refs.md:2023: - tests\controller\test_pipeline_controller_job_specs_v2.py:233: config = make_minimal_pipeline_config()
- pipeline_config_refs.md:2024: - tests\controller\test_pipeline_controller_job_specs_v2.py:253: config = make_minimal_pipeline_config()
- pipeline_config_refs.md:2025: - tests\controller\test_pipeline_controller_job_specs_v2.py:269: config = make_minimal_pipeline_config()
- pipeline_config_refs.md:2026: - tests\controller\test_pipeline_controller_job_specs_v2.py:296: config = make_minimal_pipeline_config()
- pipeline_config_refs.md:2027: - tests\controller\test_pipeline_controller_job_specs_v2.py:309: config = make_minimal_pipeline_config()
- pipeline_config_refs.md:2028: - tests\controller\test_pipeline_controller_job_specs_v2.py:323: config = make_minimal_pipeline_config()
- pipeline_config_refs.md:2029: - tests\controller\test_pipeline_controller_job_specs_v2.py:336: config = make_minimal_pipeline_config()
- pipeline_config_refs.md:2030: - tests\controller\test_pipeline_controller_job_specs_v2.py:350: config = make_minimal_pipeline_config(model="batch-model", steps=25)
- pipeline_config_refs.md:2031: - tests\controller\test_pipeline_controller_job_specs_v2.py:374: config = make_minimal_pipeline_config()
- pipeline_config_refs.md:2032: - tests\controller\test_pipeline_controller_job_specs_v2.py:391: config = make_minimal_pipeline_config()
- pipeline_config_refs.md:2033: - tests\controller\test_pipeline_controller_job_specs_v2.py:416: config = make_minimal_pipeline_config()
- pipeline_config_refs.md:2034: - tests\controller\test_pipeline_controller_job_specs_v2.py:441: config = make_minimal_pipeline_config()
- pipeline_config_refs.md:2035: - tests\controller\test_pipeline_controller_job_specs_v2.py:468: config = make_minimal_pipeline_config(hires_enabled=True)
- pipeline_config_refs.md:2036: - tests\controller\test_pipeline_controller_job_specs_v2.py:479: config = make_minimal_pipeline_config(refiner_enabled=True)
- pipeline_config_refs.md:2037: - tests\controller\test_pipeline_controller_job_specs_v2.py:490: config = make_minimal_pipeline_config(adetailer_enabled=True)
- pipeline_config_refs.md:2038: - tests\controller\test_pipeline_controller_job_specs_v2.py:519: config = make_minimal_pipeline_config(model="test", seed=123)
- pipeline_config_refs.md:2039: - tests\controller\test_pipeline_controller_job_specs_v2.py:551: config = make_minimal_pipeline_config()
- pipeline_config_refs.md:2040: - tests\controller\test_pipeline_controller_job_specs_v2.py:582: config = make_minimal_pipeline_config()
- pipeline_config_refs.md:2041: - tests\controller\test_pipeline_controller_job_specs_v2.py:593: config = make_minimal_pipeline_config()
- pipeline_config_refs.md:2042: - tests\controller\test_pipeline_controller_job_specs_v2.py:606: config = make_minimal_pipeline_config()
- pipeline_config_refs.md:2045: - tests\controller\test_pipeline_controller_webui_gating.py:11: controller._build_pipeline_config_from_state = mock.Mock()
- pipeline_config_refs.md:2046: - tests\controller\test_pipeline_controller_webui_gating.py:16: controller._build_pipeline_config_from_state.assert_not_called()
- pipeline_config_refs.md:2047: - tests\controller\test_pipeline_controller_webui_gating.py:23: controller._build_pipeline_config_from_state = mock.Mock(return_value=mock.Mock())
- pipeline_config_refs.md:2048: - tests\controller\test_pipeline_controller_webui_gating.py:32: controller._build_pipeline_config_from_state.assert_called_once()
- pipeline_config_refs.md:2051: - tests\controller\test_pipeline_randomizer_config_v2.py:54: controller.main_window = SimpleNamespace(pipeline_config_panel_v2=panel)
- pipeline_config_refs.md:2054: - tests\controller\test_presets_integration_v2.py:48: controller.main_window = SimpleNamespace(pipeline_config_panel_v2=DummyPipelinePanel())
- pipeline_config_refs.md:2055: - tests\controller\test_presets_integration_v2.py:56: assert controller.main_window.pipeline_config_panel_v2.applied[-1]["randomization_enabled"]
- pipeline_config_refs.md:2058: - tests\controller\test_profile_integration.py:18: def test_build_pipeline_config_with_profiles_applies_suggested_preset():
- pipeline_config_refs.md:2059: - tests\controller\test_profile_integration.py:23: config = controller.build_pipeline_config_with_profiles(
- pipeline_config_refs.md:2060: - tests\controller\test_profile_integration.py:34: def test_build_pipeline_config_with_profiles_respects_user_overrides():
- pipeline_config_refs.md:2061: - tests\controller\test_profile_integration.py:39: config = controller.build_pipeline_config_with_profiles(
- pipeline_config_refs.md:2062: - tests\controller\test_profile_integration.py:48: def test_build_pipeline_config_with_profiles_falls_back_without_profiles():
- pipeline_config_refs.md:2063: - tests\controller\test_profile_integration.py:53: config = controller.build_pipeline_config_with_profiles(
- pipeline_config_refs.md:2066: - tests\gui_v2\archive\test_pipeline_randomizer_panel_v2.py:11: from src.gui.panels_v2.pipeline_config_panel_v2 import PipelineConfigPanel
- pipeline_config_refs.md:2068: ## tests\gui_v2\test_pipeline_config_panel_lora_runtime.py
- pipeline_config_refs.md:2069: - tests\gui_v2\test_pipeline_config_panel_lora_runtime.py:8: from src.gui.panels_v2.pipeline_config_panel_v2 import PipelineConfigPanel
- pipeline_config_refs.md:2070: - tests\gui_v2\test_pipeline_config_panel_lora_runtime.py:33: def test_pipeline_config_panel_lora_controls_update_controller() -> None:
- pipeline_config_refs.md:2073: - tests\gui_v2\test_pipeline_layout_scroll_v2.py:338: def test_pipeline_config_panel_no_validation_label() -> None:
- pipeline_config_refs.md:2074: - tests\gui_v2\test_pipeline_layout_scroll_v2.py:347: from src.gui.panels_v2.pipeline_config_panel_v2 import PipelineConfigPanel
- pipeline_config_refs.md:2075: - tests\gui_v2\test_pipeline_layout_scroll_v2.py:374: from src.gui.panels_v2.pipeline_config_panel_v2 import PipelineConfigPanel
- pipeline_config_refs.md:2078: - tests\gui_v2\test_pipeline_left_column_config_v2.py:28: config_panel = getattr(sidebar, "pipeline_config_panel", None)
- pipeline_config_refs.md:2081: - tests\gui_v2\test_pipeline_stage_checkbox_order_v2.py:7: from src.gui.views.pipeline_config_panel import PipelineConfigPanel
- pipeline_config_refs.md:2082: - tests\gui_v2\test_pipeline_stage_checkbox_order_v2.py:11: def test_pipeline_config_stage_checkbox_order(monkeypatch) -> None:
- pipeline_config_refs.md:2085: - tests\gui_v2\test_preview_panel_v2_normalized_jobs.py:3: Confirms preview panel uses NJR-based display, not pipeline_config.
- pipeline_config_refs.md:2088: - tests\gui_v2\test_queue_panel_v2_normalized_jobs.py:3: Confirms queue panel uses NJR-based display, not pipeline_config.
- pipeline_config_refs.md:2091: - tests\helpers\pipeline_fixtures_v2.py:147: def make_minimal_pipeline_config(
- pipeline_config_refs.md:2092: - tests\helpers\pipeline_fixtures_v2.py:216: config = make_minimal_pipeline_config(seed=seed)
- pipeline_config_refs.md:2093: - tests\helpers\pipeline_fixtures_v2.py:277: "make_minimal_pipeline_config",
- pipeline_config_refs.md:2096: - tests\history\test_history_compaction.py:18: "pipeline_config": {"prompt": "old", "model": "v1", "sampler": "Euler"},
- pipeline_config_refs.md:2099: - tests\history\test_history_migration_engine.py:12: "pipeline_config": {
- pipeline_config_refs.md:2100: - tests\history\test_history_migration_engine.py:68: assert all("pipeline_config" not in entry["njr_snapshot"] for entry in migrated)
- pipeline_config_refs.md:2103: - tests\history\test_history_roundtrip.py:18: "pipeline_config": {
- pipeline_config_refs.md:2104: - tests\history\test_history_roundtrip.py:78: assert all("pipeline_config" not in rec.njr_snapshot for rec in second)
- pipeline_config_refs.md:2107: - tests\history\test_history_schema_roundtrip.py:19: "pipeline_config": {"prompt": "ancient job", "model": "v1", "sampler": "Euler a"},
- pipeline_config_refs.md:2110: - tests\history\test_history_schema_v26.py:38: entry["pipeline_config"] = {}
- pipeline_config_refs.md:2111: - tests\history\test_history_schema_v26.py:41: assert any("deprecated field present: pipeline_config" in err for err in errors)
- pipeline_config_refs.md:2114: - tests\integration\test_end_to_end_pipeline_v2.py:21: from src.pipeline.legacy_njr_adapter import build_njr_from_legacy_pipeline_config
- pipeline_config_refs.md:2115: - tests\integration\test_end_to_end_pipeline_v2.py:60: njr = build_njr_from_legacy_pipeline_config(cfg)
- pipeline_config_refs.md:2116: - tests\integration\test_end_to_end_pipeline_v2.py:260: config = job.pipeline_config
- pipeline_config_refs.md:2117: - tests\integration\test_end_to_end_pipeline_v2.py:282: def small_pipeline_config() -> PipelineConfig:
- pipeline_config_refs.md:2118: - tests\integration\test_end_to_end_pipeline_v2.py:313: small_pipeline_config: PipelineConfig,
- pipeline_config_refs.md:2119: - tests\integration\test_end_to_end_pipeline_v2.py:318: small_pipeline_config,
- pipeline_config_refs.md:2120: - tests\integration\test_end_to_end_pipeline_v2.py:352: small_pipeline_config: PipelineConfig,
- pipeline_config_refs.md:2121: - tests\integration\test_end_to_end_pipeline_v2.py:356: small_pipeline_config,
- pipeline_config_refs.md:2122: - tests\integration\test_end_to_end_pipeline_v2.py:377: small_pipeline_config: PipelineConfig,
- pipeline_config_refs.md:2123: - tests\integration\test_end_to_end_pipeline_v2.py:381: small_pipeline_config,
- pipeline_config_refs.md:2124: - tests\integration\test_end_to_end_pipeline_v2.py:411: small_pipeline_config: PipelineConfig,
- pipeline_config_refs.md:2125: - tests\integration\test_end_to_end_pipeline_v2.py:416: small_pipeline_config,
- pipeline_config_refs.md:2126: - tests\integration\test_end_to_end_pipeline_v2.py:445: small_pipeline_config: PipelineConfig,
- pipeline_config_refs.md:2127: - tests\integration\test_end_to_end_pipeline_v2.py:449: small_pipeline_config,
- pipeline_config_refs.md:2128: - tests\integration\test_end_to_end_pipeline_v2.py:516: small_pipeline_config: PipelineConfig,
- pipeline_config_refs.md:2129: - tests\integration\test_end_to_end_pipeline_v2.py:520: small_pipeline_config,
- pipeline_config_refs.md:2130: - tests\integration\test_end_to_end_pipeline_v2.py:557: small_pipeline_config: PipelineConfig,
- pipeline_config_refs.md:2131: - tests\integration\test_end_to_end_pipeline_v2.py:562: small_pipeline_config,
- pipeline_config_refs.md:2132: - tests\integration\test_end_to_end_pipeline_v2.py:663: pipeline_config = {
- pipeline_config_refs.md:2133: - tests\integration\test_end_to_end_pipeline_v2.py:682: plan = StageSequencer().build_plan(pipeline_config)
- pipeline_config_refs.md:2136: - tests\pipeline\test_config_merger_v2.py:67: def base_pipeline_config(base_txt2img_config: dict) -> dict:
- pipeline_config_refs.md:2137: - tests\pipeline\test_config_merger_v2.py:379: self, base_pipeline_config: dict
- pipeline_config_refs.md:2138: - tests\pipeline\test_config_merger_v2.py:386: base_config=base_pipeline_config,
- pipeline_config_refs.md:2139: - tests\pipeline\test_config_merger_v2.py:392: assert result == base_pipeline_config
- pipeline_config_refs.md:2140: - tests\pipeline\test_config_merger_v2.py:393: assert result is not base_pipeline_config
- pipeline_config_refs.md:2141: - tests\pipeline\test_config_merger_v2.py:394: assert result["refiner"] is not base_pipeline_config["refiner"]
- pipeline_config_refs.md:2142: - tests\pipeline\test_config_merger_v2.py:397: self, base_pipeline_config: dict
- pipeline_config_refs.md:2143: - tests\pipeline\test_config_merger_v2.py:403: base_config=base_pipeline_config,
- pipeline_config_refs.md:2144: - tests\pipeline\test_config_merger_v2.py:408: assert result == base_pipeline_config
- pipeline_config_refs.md:2145: - tests\pipeline\test_config_merger_v2.py:409: assert result is not base_pipeline_config
- pipeline_config_refs.md:2146: - tests\pipeline\test_config_merger_v2.py:412: self, base_pipeline_config: dict
- pipeline_config_refs.md:2147: - tests\pipeline\test_config_merger_v2.py:426: base_config=base_pipeline_config,
- pipeline_config_refs.md:2148: - tests\pipeline\test_config_merger_v2.py:437: self, base_pipeline_config: dict
- pipeline_config_refs.md:2149: - tests\pipeline\test_config_merger_v2.py:450: base_config=base_pipeline_config,
- pipeline_config_refs.md:2150: - tests\pipeline\test_config_merger_v2.py:464: self, base_pipeline_config: dict
- pipeline_config_refs.md:2151: - tests\pipeline\test_config_merger_v2.py:477: base_config=base_pipeline_config,
- pipeline_config_refs.md:2152: - tests\pipeline\test_config_merger_v2.py:487: self, base_pipeline_config: dict
- pipeline_config_refs.md:2153: - tests\pipeline\test_config_merger_v2.py:500: base_config=base_pipeline_config,
- pipeline_config_refs.md:2154: - tests\pipeline\test_config_merger_v2.py:510: self, base_pipeline_config: dict
- pipeline_config_refs.md:2155: - tests\pipeline\test_config_merger_v2.py:523: base_config=base_pipeline_config,
- pipeline_config_refs.md:2156: - tests\pipeline\test_config_merger_v2.py:533: self, base_pipeline_config: dict
- pipeline_config_refs.md:2157: - tests\pipeline\test_config_merger_v2.py:546: base_config=base_pipeline_config,
- pipeline_config_refs.md:2158: - tests\pipeline\test_config_merger_v2.py:556: self, base_pipeline_config: dict
- pipeline_config_refs.md:2159: - tests\pipeline\test_config_merger_v2.py:571: base_config=base_pipeline_config,
- pipeline_config_refs.md:2160: - tests\pipeline\test_config_merger_v2.py:592: self, base_pipeline_config: dict
- pipeline_config_refs.md:2161: - tests\pipeline\test_config_merger_v2.py:597: original = copy.deepcopy(base_pipeline_config)
- pipeline_config_refs.md:2162: - tests\pipeline\test_config_merger_v2.py:605: base_config=base_pipeline_config,
- pipeline_config_refs.md:2163: - tests\pipeline\test_config_merger_v2.py:611: assert base_pipeline_config == original
- pipeline_config_refs.md:2166: - tests\pipeline\test_job_queue_persistence_v2.py:76: "pipeline_config": {"model": "old"},
- pipeline_config_refs.md:2167: - tests\pipeline\test_job_queue_persistence_v2.py:84: assert "pipeline_config" not in migrated["njr_snapshot"]
- pipeline_config_refs.md:2168: - tests\pipeline\test_job_queue_persistence_v2.py:149: assert "pipeline_config" not in job_record["njr_snapshot"]
- pipeline_config_refs.md:2169: - tests\pipeline\test_job_queue_persistence_v2.py:166: "pipeline_config": {"model": "old"},
- pipeline_config_refs.md:2170: - tests\pipeline\test_job_queue_persistence_v2.py:185: assert "pipeline_config" not in job["njr_snapshot"]
- pipeline_config_refs.md:2171: - tests\pipeline\test_job_queue_persistence_v2.py:308: assert "pipeline_config" not in queue_entry["njr_snapshot"]
- pipeline_config_refs.md:2172: - tests\pipeline\test_job_queue_persistence_v2.py:309: assert "pipeline_config" not in history_njr
- pipeline_config_refs.md:2173: - tests\pipeline\test_job_queue_persistence_v2.py:353: assert "pipeline_config" not in entry["njr_snapshot"]
- pipeline_config_refs.md:2176: - tests\pipeline\test_legacy_njr_adapter.py:1: from src.pipeline.legacy_njr_adapter import build_njr_from_legacy_pipeline_config
- pipeline_config_refs.md:2177: - tests\pipeline\test_legacy_njr_adapter.py:5: def _make_pipeline_config() -> PipelineConfig:
- pipeline_config_refs.md:2178: - tests\pipeline\test_legacy_njr_adapter.py:20: config = _make_pipeline_config()
- pipeline_config_refs.md:2179: - tests\pipeline\test_legacy_njr_adapter.py:21: record = build_njr_from_legacy_pipeline_config(config)
- pipeline_config_refs.md:2180: - tests\pipeline\test_legacy_njr_adapter.py:25: assert record.extra_metadata.get("legacy_source") == "pipeline_config"
- pipeline_config_refs.md:2181: - tests\pipeline\test_legacy_njr_adapter.py:29: def test_adapter_handles_minimal_pipeline_config() -> None:
- pipeline_config_refs.md:2182: - tests\pipeline\test_legacy_njr_adapter.py:39: record = build_njr_from_legacy_pipeline_config(config)
- pipeline_config_refs.md:2185: - tests\pipeline\test_pipeline_learning_hooks.py:52: def _pipeline_config():
- pipeline_config_refs.md:2186: - tests\pipeline\test_pipeline_learning_hooks.py:67: runner.run(_pipeline_config(), cancel_token=_cancel_token())
- pipeline_config_refs.md:2187: - tests\pipeline\test_pipeline_learning_hooks.py:74: runner.run(_pipeline_config(), cancel_token=_cancel_token())
- pipeline_config_refs.md:2190: - tests\pipeline\test_stage_plan_builder_v2_5.py:8: def _base_pipeline_config(**overrides) -> dict[str, dict]:
- pipeline_config_refs.md:2191: - tests\pipeline\test_stage_plan_builder_v2_5.py:36: config = _base_pipeline_config(
- pipeline_config_refs.md:2192: - tests\pipeline\test_stage_plan_builder_v2_5.py:56: config = _base_pipeline_config(
- pipeline_config_refs.md:2193: - tests\pipeline\test_stage_plan_builder_v2_5.py:72: config = _base_pipeline_config(
- pipeline_config_refs.md:2194: - tests\pipeline\test_stage_plan_builder_v2_5.py:86: config = _base_pipeline_config(
- pipeline_config_refs.md:2197: - tests\queue\test_job_history_store.py:90: assert "pipeline_config" not in njr_snapshot
- pipeline_config_refs.md:2200: - tests\queue\test_job_model.py:13: def test_job_dict_does_not_include_pipeline_config():
- pipeline_config_refs.md:2201: - tests\queue\test_job_model.py:16: assert "pipeline_config" not in as_dict
- pipeline_config_refs.md:2204: - tests\queue\test_job_service_pipeline_integration_v2.py:234: """submit_direct() passes job with correct pipeline_config."""
- pipeline_config_refs.md:2205: - tests\queue\test_job_service_pipeline_integration_v2.py:336: """submit_queued() passes job with correct pipeline_config."""
- pipeline_config_refs.md:2208: - tests\queue\test_job_variant_metadata_v2.py:9: def _make_pipeline_config() -> PipelineConfig:
- pipeline_config_refs.md:2209: - tests\queue\test_job_variant_metadata_v2.py:27: "pipeline_config": _make_pipeline_config(),
- pipeline_config_refs.md:2212: - tests\queue\test_queue_njr_path.py:5: - Execution uses NJR-only path for new jobs (pipeline_config is None)
- pipeline_config_refs.md:2213: - tests\queue\test_queue_njr_path.py:6: - Legacy pipeline_config-only jobs still work but are marked as legacy
- pipeline_config_refs.md:2214: - tests\queue\test_queue_njr_path.py:60: assert getattr(retrieved, "pipeline_config", None) is None
- pipeline_config_refs.md:2215: - tests\queue\test_queue_njr_path.py:63: """Job with NJR should execute via NJR path only (no pipeline_config fallback)."""
- pipeline_config_refs.md:2216: - tests\queue\test_queue_njr_path.py:81: # 3. NOT fall back to pipeline_config even if _run_job fails
- pipeline_config_refs.md:2217: - tests\queue\test_queue_njr_path.py:85: # pipeline_config should remain None for NJR-only jobs
- pipeline_config_refs.md:2218: - tests\queue\test_queue_njr_path.py:86: assert getattr(retrieved, "pipeline_config", None) is None
- pipeline_config_refs.md:2219: - tests\queue\test_queue_njr_path.py:88: def test_legacy_pipeline_config_only_job(self, tmp_path: Path):
- pipeline_config_refs.md:2220: - tests\queue\test_queue_njr_path.py:89: """Legacy job with only pipeline_config (no NJR) should still work."""
- pipeline_config_refs.md:2221: - tests\queue\test_queue_njr_path.py:99: job.pipeline_config = PipelineConfig(
- pipeline_config_refs.md:2222: - tests\queue\test_queue_njr_path.py:115: assert getattr(retrieved, "pipeline_config", None) is not None
- pipeline_config_refs.md:2223: - tests\queue\test_queue_njr_path.py:152: def test_new_jobs_dont_rely_on_pipeline_config_for_execution(self, tmp_path: Path):
- pipeline_config_refs.md:2224: - tests\queue\test_queue_njr_path.py:153: """PR-CORE1-B2: New queue jobs should not rely on pipeline_config for execution."""
- pipeline_config_refs.md:2225: - tests\queue\test_queue_njr_path.py:167: # pipeline_config is intentionally absent for new NJR-only jobs
- pipeline_config_refs.md:2226: - tests\queue\test_queue_njr_path.py:175: assert getattr(retrieved, "pipeline_config", None) is None
- pipeline_config_refs.md:2227: - tests\queue\test_queue_njr_path.py:176: # PR-CORE1-B2 contract: Execution MUST use _normalized_record, not pipeline_config

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
- snapshots\repo_inventory.json:78: "path": "pipeline_config_refs.md",
- snapshots\repo_inventory.json:778: "path": "archive/legacy_tests/tests_gui_v2_legacy/test_gui_v2_pipeline_config_roundtrip.py",
- snapshots\repo_inventory.json:5248: "path": "scripts/list_pipeline_config_refs.py",
- snapshots\repo_inventory.json:5403: "path": "src/controller/pipeline_config_assembler.py",
- snapshots\repo_inventory.json:5713: "path": "src/gui/panels_v2/pipeline_config_panel_v2.py",
- snapshots\repo_inventory.json:5853: "path": "src/gui/views/pipeline_config_panel.py",
- snapshots\repo_inventory.json:6823: "path": "tests/controller/test_pipeline_config_assembler.py",
- snapshots\repo_inventory.json:6828: "path": "tests/controller/test_pipeline_config_assembler_core_fields.py",
- snapshots\repo_inventory.json:6833: "path": "tests/controller/test_pipeline_config_assembler_model_fields.py",
- snapshots\repo_inventory.json:6838: "path": "tests/controller/test_pipeline_config_assembler_negative_prompt.py",
- snapshots\repo_inventory.json:6843: "path": "tests/controller/test_pipeline_config_assembler_output_settings.py",
- snapshots\repo_inventory.json:6848: "path": "tests/controller/test_pipeline_config_assembler_resolution.py",
- snapshots\repo_inventory.json:7158: "path": "tests/gui_v2/test_pipeline_config_panel_lora_runtime.py",

## src\controller\app_controller.py
- src\controller\app_controller.py:5: Runtime pipeline execution via pipeline_config has been REMOVED.
- src\controller\app_controller.py:7: Use PipelineController + NJR path for all new code. Do not add pipeline_config-based
- src\controller\app_controller.py:767: "error": "Job is missing normalized_record; legacy/pipeline_config execution is disabled.",
- src\controller\app_controller.py:1250: def _validate_pipeline_config(self) -> tuple[bool, str]:
- src\controller\app_controller.py:1251: """DEPRECATED (PR-CORE1-12): Legacy validation for pipeline_config panel.
- src\controller\app_controller.py:1266: # PR-CORE1-12: pipeline_config_panel_v2 is DEPRECATED - no longer wired in GUI V2
- src\controller\app_controller.py:1267: panel = getattr(self.main_window, "pipeline_config_panel_v2", None)
- src\controller\app_controller.py:1503: def _execute_pipeline_via_runner(self, pipeline_config: PipelineConfig) -> Any:
- src\controller\app_controller.py:1504: """DEPRECATED (PR-CORE1-12): Legacy pipeline_config execution removed.
- src\controller\app_controller.py:1512: RuntimeError: Always - pipeline_config execution is disabled.
- src\controller\app_controller.py:1516: def _run_pipeline_from_tab(self, pipeline_tab: Any, pipeline_config: PipelineConfig) -> Any:
- src\controller\app_controller.py:1517: """DEPRECATED (PR-CORE1-12): Legacy tab-based pipeline_config execution.
- src\controller\app_controller.py:1619: def _run_pipeline_via_runner_only(self, pipeline_config: PipelineConfig) -> Any:
- src\controller\app_controller.py:1629: RuntimeError: Always - pipeline_config execution is disabled.
- src\controller\app_controller.py:1701: is_valid, message = self._validate_pipeline_config()
- src\controller\app_controller.py:1746: pipeline_config = self.build_pipeline_config_v2()
- src\controller\app_controller.py:1748: executor_config = self.pipeline_runner._build_executor_config(pipeline_config)
- src\controller\app_controller.py:1749: self._cache_last_run_payload(executor_config, pipeline_config)
- src\controller\app_controller.py:1750: self.pipeline_runner.run(pipeline_config, cancel_token, self._append_log_threadsafe)
- src\controller\app_controller.py:1770: def _cache_last_run_payload(self, executor_config: dict[str, Any], pipeline_config: PipelineConfig) -> None:
- src\controller\app_controller.py:1771: """DEPRECATED (PR-CORE1-12): Legacy payload caching for pipeline_config.
- src\controller\app_controller.py:1773: This cached pipeline_config for debugging/replay. No longer used since
- src\controller\app_controller.py:1782: "prompt": pipeline_config.prompt,
- src\controller\app_controller.py:1783: "pack_name": pipeline_config.pack_name,
- src\controller\app_controller.py:1784: "preset_name": pipeline_config.preset_name,
- src\controller\app_controller.py:1863: # PR-CORE1-12: pipeline_config_panel_v2 is DEPRECATED - no longer wired in GUI V2
- src\controller\app_controller.py:1864: pipeline_panel = getattr(self.main_window, "pipeline_config_panel_v2", None)
- src\controller\app_controller.py:2181: # PR-CORE1-12: pipeline_config_panel_v2 is DEPRECATED - no longer wired in GUI V2
- src\controller\app_controller.py:2182: pipeline_config_panel = getattr(self.main_window, "pipeline_config_panel_v2", None)
- src\controller\app_controller.py:2183: if pipeline_config_panel and hasattr(pipeline_config_panel, "apply_run_config"):
- src\controller\app_controller.py:2185: pipeline_config_panel.apply_run_config(preset_config)
- src\controller\app_controller.py:2456: def build_pipeline_config_v2(self) -> PipelineConfig:
- src\controller\app_controller.py:2457: """DEPRECATED (PR-CORE1-12): Legacy pipeline_config builder.
- src\controller\app_controller.py:2465: return self._build_pipeline_config()
- src\controller\app_controller.py:2467: def _build_pipeline_config(self) -> PipelineConfig:
- src\controller\app_controller.py:2468: """DEPRECATED (PR-CORE1-12): Internal pipeline_config builder.
- src\controller\app_controller.py:2470: NOTE: Still used by PipelineController._build_pipeline_config_from_state()
- src\controller\app_controller.py:2753: # PR-CORE1-12: pipeline_config_panel_v2 is DEPRECATED - no longer wired in GUI V2
- src\controller\app_controller.py:2754: panel = getattr(self.main_window, "pipeline_config_panel_v2", None)
- src\controller\app_controller.py:2869: # PR-CORE1-12: pipeline_config_panel_v2 is DEPRECATED - no longer wired in GUI V2
- src\controller\app_controller.py:2870: pipeline_config_panel = getattr(self.main_window, "pipeline_config_panel_v2", None)
- src\controller\app_controller.py:2871: if pipeline_config_panel and hasattr(pipeline_config_panel, "apply_run_config"):
- src\controller\app_controller.py:2873: pipeline_config_panel.apply_run_config(pack_config)
- src\controller\app_controller.py:3101: # PR-CORE1-12: pipeline_config_panel_v2 is DEPRECATED - no longer wired in GUI V2
- src\controller\app_controller.py:3102: pipeline_config_panel = getattr(self.main_window, "pipeline_config_panel_v2", None)
- src\controller\app_controller.py:3103: if pipeline_config_panel and hasattr(pipeline_config_panel, "apply_run_config"):
- src\controller\app_controller.py:3105: pipeline_config_panel.apply_run_config(preset_config)

## src\controller\archive\README.md
- src\controller\archive\README.md:12: #### `pipeline_config_assembler.py`

## src\controller\job_history_service.py
- src\controller\job_history_service.py:223: Prefers NJR snapshot data. Legacy pipeline_config-only jobs no longer

## src\controller\job_service.py
- src\controller\job_service.py:305: # PR-CORE1-B3/C2: NJR-backed jobs are purely NJR-only and don't store pipeline_config.

## src\controller\pipeline_controller.py
- src\controller\pipeline_controller.py:37: from src.pipeline.legacy_njr_adapter import build_njr_from_legacy_pipeline_config
- src\controller\pipeline_controller.py:40: from src.controller.archive.pipeline_config_assembler import PipelineConfigAssembler, GuiOverrides
- src\controller\pipeline_controller.py:199: def _build_pipeline_config_from_state(self) -> PipelineConfig:
- src\controller\pipeline_controller.py:236: base_config = self._build_pipeline_config_from_state()
- src\controller\pipeline_controller.py:385: PR-CORE1-B3: NJR-backed jobs MUST NOT carry pipeline_config. The field may
- src\controller\pipeline_controller.py:535: def build_pipeline_config_with_profiles(
- src\controller\pipeline_controller.py:851: config = self._build_pipeline_config_from_state()
- src\controller\pipeline_controller.py:1301: Legacy pipeline_config execution is retired in CORE1-C2.
- src\controller\pipeline_controller.py:1555: This method converts pipeline_config to NJR using legacy adapter, then
- src\controller\pipeline_controller.py:1567: record = build_njr_from_legacy_pipeline_config(config)
- src\controller\pipeline_controller.py:1573: record = build_njr_from_legacy_pipeline_config(config)

## src\gui\dropdown_loader_v2.py
- src\gui\dropdown_loader_v2.py:61: panel = getattr(sidebar, "pipeline_config_panel", None)

## src\gui\main_window_v2.py
- src\gui\main_window_v2.py:187: if hasattr(self, "pipeline_tab") and hasattr(self.pipeline_tab, "pipeline_config_panel"):
- src\gui\main_window_v2.py:189: self.pipeline_tab.pipeline_config_panel.controller = controller

## src\gui\panels_v2\__init__.py
- src\gui\panels_v2\__init__.py:9: # from src.gui.panels_v2.pipeline_config_panel_v2 import PipelineConfigPanel

## src\gui\panels_v2\archive\README.md
- src\gui\panels_v2\archive\README.md:12: #### `pipeline_config_panel_v2.py`

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
- src\gui\sidebar_panel_v2.py:876: was wired to pipeline_config execution, which is removed in v2.6.
- src\gui\sidebar_panel_v2.py:881: # from src.gui.panels_v2.pipeline_config_panel_v2 import PipelineConfigPanel
- src\gui\sidebar_panel_v2.py:886: # PR-CORE1-12: Stages section and pipeline_config_panel creation disabled
- src\gui\sidebar_panel_v2.py:892: # self.pipeline_config_panel = PipelineConfigPanel(
- src\gui\sidebar_panel_v2.py:898: # self.pipeline_config_panel.pack(fill="both", expand=True)

## src\gui\views\archive\README.md
- src\gui\views\archive\README.md:12: #### `pipeline_config_panel.py`

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
- src\pipeline\job_models_v2.py:80: PR-CORE1-12: pipeline_config is DEPRECATED. Legacy jobs without NJR
- src\pipeline\job_models_v2.py:81: snapshots may fall back to pipeline_config, but all new jobs use NJR only.
- src\pipeline\job_models_v2.py:105: the NJR snapshot stored in history entries, not from pipeline_config.
- src\pipeline\job_models_v2.py:107: PR-CORE1-12: pipeline_config is DEPRECATED. Legacy history entries without
- src\pipeline\job_models_v2.py:108: NJR snapshots may fall back to pipeline_config, but all new jobs use NJR only.
- src\pipeline\job_models_v2.py:444: PR-CORE1-12: pipeline_config is DEPRECATED and removed from runtime execution.
- src\pipeline\job_models_v2.py:445: During early CORE1-A/B hybrid state, Job.pipeline_config was the execution payload,
- src\pipeline\job_models_v2.py:447: Full NJR-only execution is enforced for all new jobs; pipeline_config is

## src\pipeline\legacy_njr_adapter.py
- src\pipeline\legacy_njr_adapter.py:58: def build_njr_from_legacy_pipeline_config(pipeline_config: PipelineConfig) -> NormalizedJobRecord:
- src\pipeline\legacy_njr_adapter.py:67: config_snapshot = asdict(pipeline_config)
- src\pipeline\legacy_njr_adapter.py:68: stage = _make_default_stage(pipeline_config)
- src\pipeline\legacy_njr_adapter.py:69: metadata = dict(pipeline_config.metadata or {})
- src\pipeline\legacy_njr_adapter.py:87: positive_prompt=pipeline_config.prompt or "",
- src\pipeline\legacy_njr_adapter.py:88: negative_prompt=pipeline_config.negative_prompt or "",
- src\pipeline\legacy_njr_adapter.py:93: steps=pipeline_config.steps or 20,
- src\pipeline\legacy_njr_adapter.py:94: cfg_scale=pipeline_config.cfg_scale or 7.0,
- src\pipeline\legacy_njr_adapter.py:95: width=pipeline_config.width or 512,
- src\pipeline\legacy_njr_adapter.py:96: height=pipeline_config.height or 512,
- src\pipeline\legacy_njr_adapter.py:97: sampler_name=pipeline_config.sampler or "Euler a",
- src\pipeline\legacy_njr_adapter.py:98: scheduler=getattr(pipeline_config, "scheduler", "") or "",
- src\pipeline\legacy_njr_adapter.py:99: base_model=pipeline_config.model or "unknown",
- src\pipeline\legacy_njr_adapter.py:117: "legacy_source": "pipeline_config",
- src\pipeline\legacy_njr_adapter.py:167: pipeline_config = data.get("pipeline_config")
- src\pipeline\legacy_njr_adapter.py:168: if isinstance(pipeline_config, PipelineConfig):
- src\pipeline\legacy_njr_adapter.py:169: return build_njr_from_legacy_pipeline_config(pipeline_config)
- src\pipeline\legacy_njr_adapter.py:170: if isinstance(pipeline_config, Mapping):
- src\pipeline\legacy_njr_adapter.py:172: prompt=str(pipeline_config.get("prompt", "") or ""),
- src\pipeline\legacy_njr_adapter.py:173: model=_normalize_model_name(pipeline_config.get("model", "") or pipeline_config.get("model_name", "")),
- src\pipeline\legacy_njr_adapter.py:174: sampler=str(pipeline_config.get("sampler", "") or pipeline_config.get("sampler_name", "") or "Euler a"),
- src\pipeline\legacy_njr_adapter.py:175: width=_coerce_int(pipeline_config.get("width", 512), 512),
- src\pipeline\legacy_njr_adapter.py:176: height=_coerce_int(pipeline_config.get("height", 512), 512),
- src\pipeline\legacy_njr_adapter.py:177: steps=_coerce_int(pipeline_config.get("steps", 20), 20),
- src\pipeline\legacy_njr_adapter.py:178: cfg_scale=_coerce_float(pipeline_config.get("cfg_scale", 7.0), 7.0),
- src\pipeline\legacy_njr_adapter.py:179: negative_prompt=str(pipeline_config.get("negative_prompt", "") or ""),
- src\pipeline\legacy_njr_adapter.py:180: metadata=dict(pipeline_config.get("metadata") or {}),
- src\pipeline\legacy_njr_adapter.py:182: return build_njr_from_legacy_pipeline_config(config)

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

