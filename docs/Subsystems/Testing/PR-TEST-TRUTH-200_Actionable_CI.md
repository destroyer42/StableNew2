# PR-TEST-TRUTH-200 — Restore Actionable CI & Consolidate Legacy Journeys

Status: implemented on `feature/pr-test-truth-200-actionable-ci` (base `origin/main` 4acad71).
No production (`src/`) change. Required CI behavior unchanged.

## Why

The informational full suite was permanently red and the `Journey Tests` workflow
ran a lane of tests that exercised removed architecture. A per-directory census
on the base (Python 3.11, local) found about 300 failures (the first-five list
in the package brief was only the head of it). Causes were stale fixtures, not
production regressions: removed `NormalizedJobRecord(config=...)`, fakes without
`JobRepository`, `.txt` PromptPacks (native JSON only now), host-state leaks
(owner's running A1111, per-user PromptPack directory), and assertions about
removed direct-run / legacy paths.

## What changed

- **WebUI ownership/readiness:** shutdown tests model a StableNew-launched
  (owned) process and prove an unowned or PID-mismatched process is never
  terminated or killed. Readiness fixtures return `progress=0.0`; busy-progress,
  progress-HTTP-error and busy-then-idle polling are covered; the boot marker is
  tested as observability only. Production unchanged.
- **Legacy journey lane retired.** `tests/journeys`, `tests/journey`,
  `journey-tests.yml`, `journeys_shutdown.yml` and `scripts/run_journey_tests.ps1`
  are gone; their durable assertions moved to the layer that owns them
  (ledger below). `tests/helpers/njr_queue_harness.py::run_njr_via_queue` is the
  canonical-path harness (NJR -> JobService -> SQLite -> `run_njr`, HTTP mocked).
  `tests/system/test_ci_truth_sync_v2.py` pins the new workflow truth.
- **CI:** `ci.yml` required job unchanged. The informational `full-suite` lane
  no longer uses `--maxfail=5`, adds `pytest-timeout` (`--timeout=300`) and short
  failure summaries, and is documented as informational. The shutdown/no-leak
  process check is `shutdown_leak_manual.yml` (manual, self-hosted) and the test
  is opt-in (`STABLENEW_RUN_SHUTDOWN_LEAK_TEST=1`).
- **Host isolation:** `tests/gui_v2/conftest.py` and a new
  `tests/integration/conftest.py` isolate PromptPacks, UI state files, WebUI/Comfy
  autostart and endpoint probes. Video/SVD/runner tests inject fake runtime
  transition owners instead of probing the real endpoint.
- **Quarantine audited:** emptied (README states why).
- **Docs:** testing guide, `STATUS.md` (PR-RUNTIME-110 integrated; this package),
  `CODEX_MAP.md`.

## Deletion / relocation ledger

| Removed | Class | Evidence / replacement |
|---|---|---|
| JT03 txt2img, JT04 img2img/ADetailer, JT05 upscale, JT06 PromptPack queue | obsolete architecture | Drove `start_run_and_wait` through direct controller submission and asserted `run_mode == "direct"` / mocked `generate_images`; production queues only. Payload/stage coverage: `test_golden_path_suite_v2_6.py` (GP6 structured stage configs), `test_pr_mvp_045_promptpack_queue.py`, executor/stage tests. JT06 scaffold only asserted helpers were callable. |
| `journey_helpers_v2.start_run_and_wait` / `get_stage_plan_for_job` / `get_latest_job` | obsolete helpers | No retained user. `run_njr_journey` kept as `run_njr_via_queue`. |
| JT01 + JT02 (Tk app builds) | relocated | Unique parsing/save-load assertions are now Tk-free in `tests/state/test_prompt_metadata_parsing.py`. JT02 `pipeline_tab_integration` asserted `app_state is not None` (placeholder) — dropped. |
| JT07 large-batch | misnamed + timing flake | Synthetic `AppState` churn, no job executed, wall-clock jitter thresholds (observed 249 ms vs 100 ms bound under load). Not "80-job execution"; deleted. |
| `test_v2_full_pipeline_journey` (2) | duplicate/misnamed | "runner error" test never injected an error; both only called `on_run_clicked`. Covered by `test_app_controller_pipeline_integration.py` and `test_core_run_path_v2.py`. Resource-population flow retained as `tests/gui_v2/test_phase1_resource_population_and_run_enqueue.py`. |
| `test_njr_modern_pattern` | relocated | `tests/integration/test_njr_queue_runner_transport.py`. |
| `test_movie_clips_mvp` | relocated/renamed | `tests/video/test_movie_clips_tab_service_smoke.py`. |
| `test_shutdown_no_leaks` | relocated, opt-in | `tests/system/`; launches the real app, inspects host processes. |
| `tests/journey/test_content_visibility_mode_journey` | duplicate | `test_content_visibility_toggle_integration.py` (live filter) and `test_content_visibility_mode_persistence.py` (restart persistence). |
| `tests/gui_v2/test_pipeline_tab_render.py` | superseded manual script | Called `mainloop()` (hung the full suite); `tests/gui_v2/test_pipeline_tab_*` cover construction. |
| 9 `tests/quarantine` scripts | superseded manual scripts | No pytest functions, interactive `mainloop()`, one imports a nonexistent module; superseded by `tests/gui_v2/test_pipeline_stage_cards_v2.py`, `test_stage_cards_layout_v2.py`, `tests/controller/test_heartbeat_stall_fix.py`, `tests/services/test_pr_harden_008_watchdog.py`, `tests/utils/test_diagnostics_bundle_v2.py`. Two real tests graduated (`tests/learning/test_learning_baseline_config.py`, `tests/gui_v2/test_queue_panel_remove_updates_gui.py`). |
| `tests/test_pr_gui_004_phase_d.py`, `tests/test_pr_gui_004_phases_bce.py` | duplicate | Identical current copies in `tests/gui_v2/` and `tests/utils/`; the old cache test would have `unlink`ed the real workspace asset cache. |
| 4 `TestJobStatusCallbackFlow` + `test_job_has_payload` + `test_direct_mode_sets_run_mode` | vacuous/obsolete | Ran a closure on a `Mock(spec=...)`; controller no longer attaches `Job.payload`; direct-to-queue coercion already tested. |
| 2 `TestTimestamps` | removed field | NJR no longer has `created_ts` (creation time is repository-owned). |

Replaced rather than removed: all-disabled stage-chain test (now pins the NJR
"at least one enabled stage" invariant), sweep-by-randomization placeholder skip
(now a real test).

## Open findings (not fixed here; tests left red on purpose)

1. `tests/pipeline/test_pipeline_io_contracts.py::...returns_result_and_learning_record`:
   `PipelineRunner.run_njr` reads `getattr(njr, "randomizer_mode", "")` but the NJR
   has no such field, so `result.randomizer_mode` is always empty for NJR runs.
   Decision: source it from `randomizer_summary` or drop the result field.
2. `tests/controller/test_auto_run_worker_lifecycle_v2.py::test_pause_resume_preserves_manual_or_auto_dispatch_policy`:
   race — a finished manual one-shot `QueueWorkerOnce` thread is still alive, so
   `_ensure_runner_started()` skips starting the continuous worker and queued jobs
   stall with auto-run on. Fix belongs in `JobService`/`SingleNodeJobRunner`.
   The same race makes `tests/integration/test_pr_mvp_060_phase1b.py::...manual_dispatch`
   (a second `on_queue_send_job_v2()` right after a completed job) fail intermittently
   in whole-suite runs; it passes in isolation and is left unmasked.

## Process-global isolation added to `tests/conftest.py`

An autouse fixture clears `ThreadRegistry` bookkeeping, resets the `SystemWatchdogV2`
single-flight slot, and restores `sys.excepthook`/`threading.excepthook` after each
test. Without it, `AppController`s that tests never shut down stack their chained
exception hooks until one thread exception recurses to a stack overflow (observed as a
Windows fatal crash of the whole run) and leaked threads/watchdogs fail unrelated
lifecycle tests only in a whole-suite run. It forgets leaked threads; it does not stop
them, and the leaking tests themselves are unaudited debt.

## Verification

- Final single-process full suite (Python 3.11 local): 3940 passed, 64 skipped,
  18 failed = 14 `numpy`/`cv2` environment + the two open findings above + two
  1-second `post_started` waits in `test_pr_harden_009_r1a/r2` (raised to 10 s after
  the run; they pass in isolation and in the `tests/integration tests/pipeline` run) +
  the phase1b symptom of finding 2. Base census: about 300 failures plus a hang and a
  stack-overflow crash. Collected tests 4033 -> 4020.
- Required gate pieces pass locally: repository completeness, controller ratchet,
  Ruff, collection gate, required smoke (129 passed), `git diff --check`.
  `tools/ci/run_pr_gate.py` stops at the existing missing-`mypy` tooling blocker.
- Python 3.12 and GitHub required CI were not run (no 3.12 test environment locally;
  publication was not authorized).

## Known environment limits

- 14 `tests/tools` tests need `numpy`/`cv2` (declared dependencies; CI installs them).
- Optional/opt-in skips unchanged (cv2 importorskip, evidence env vars, Tk/Tcl
  intermittent init, `Implementation pending` golden-path placeholders, ~38
  PR-GUI-F1 "widget removed" skips left for one cleanup commit).
- `tests/tools/test_operator_journey_gui.py` asserts the worktree stays clean, so it
  is unreliable while other pytest processes share the same worktree.
- A real `test_pack.json` written by the old `test_json_unification` may remain in
  `%LOCALAPPDATA%\StableNew\PromptPacks`; owner may delete it.
