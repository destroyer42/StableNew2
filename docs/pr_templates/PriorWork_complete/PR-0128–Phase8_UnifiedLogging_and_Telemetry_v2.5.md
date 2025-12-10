# PR-0128 — Phase 8: Unified Logging & Telemetry Harmonization (V2.5)

## 1. Summary

- Standardizes on `log_with_ctx`/`LogContext` across API, controller, watchdog, and containment layers so every log line carries `job_id`, `stage`, and `subsystem`.
- Adds `JsonlFileHandler` + `JsonlFileLogConfig` so JSONL logs live under `logs/stablenew.log.jsonl` (and rotate safely), and crash bundles now copy that file directly.
- Teaches `LogTracePanelV2` to filter by level, subsystem, and job ID while surfacing payload summaries, giving users a consistent way to inspect structured logs from Phase 5/6/7.
- Documented the new logging workflow and added targeted tests (`tests/utils/test_logger_v2.py`, `tests/gui_v2/test_log_display_v2.py`) so the plumbing is regression-tested.

## 2. Context

- Phase 5 introduced diagnostics bundles and the in-memory log handler, Phase 6 gave us structured error envelopes, and Phase 7 added retry metadata—but logs still mix formats and omit job-level details.
- Phase 8 wires everything through `src/utils/logger.py`, persists JSONL logs, and surfaces the same structured data in the GUI so engineers stop chasing siloed hash strings when debugging D-99 issues.

## 3. Scope

### In Scope
- `src/utils/logger.py` — adds `JsonlFileLogConfig`, `JsonlFileHandler`, and `attach_jsonl_log_handler`, plus `log_with_ctx` now stores `json_payload`.
- `src/controller/app_controller.py` — attaches the JSONL handler via `get_jsonl_log_config` (Phase 8 bootstrapping).
- `src/utils/diagnostics_bundle_v2.py` — copies the JSONL logs into the diagnostics ZIP so bundles carry a single canonical log source.
- `src/gui/log_trace_panel_v2.py` — adds subsystem/job filters and payload-aware summaries.
- Tests: `tests/utils/test_logger_v2.py`, `tests/gui_v2/test_log_display_v2.py`.

### Out of Scope
- No changes to pipeline/executor semantics.
- No new telemetry pipelines, metrics exports, or UI redesigns beyond the log panel filters.

## 4. Testing

- `tests/utils/test_logger_v2.py` verifies JSON payloads and the JSONL handler.
- `tests/gui_v2/test_log_display_v2.py` ensures log filters respect level, subsystem, and job ID.
- Existing suites should still pass without modification.

## 5. Documentation

- `docs/StableNew_Coding_and_Testing_v2.5.md` now describes Phase 8 logging improvements and JSONL streams.
- `CHANGELOG.md` and this template file summarize Phase 8 for reviewers.

## 6. Rollout

- Merge once targeted tests pass (no new runtime dependencies).
- The JSONL file is enabled by default but can be toggled via `STABLENEW_JSONL_LOG_ENABLED` and `STABLENEW_JSONL_LOG_PATH`.
- Crash bundles automatically pick up logs from the JSON file, so support engineers won’t need extra steps.
