# PR-TEST-TRUTH-220 - retire stale GUI controller binding tests

Result class: **TEST TRUTH (bounded).** Zero production change; no runtime behavior changed. Execution profile: Narrow
(Claude Code, Sonnet 5.5). Follows the debt recorded in `PR-TEST-TRUTH-210_Pre_Forge_Execution_and_Test_Truth.md`.

## Current architecture the tests must describe

The GUI is projection-driven. A job-lifecycle callback does not write widgets:

`AppController._on_job_status_for_panels` -> `RuntimeProjectionCoordinator.publish_queue_refresh()` (every status) and
`publish_history_refresh()` (terminal statuses) -> versioned projections -> `AppStateProjectionSink` -> `AppStateV2` ->
GUI surfaces subscribed to `queue_jobs` / `history_items` (`QueuePanelV2`, `JobHistoryPanelV2` / Pipeline tab).

## Retired tests (exactly two, in `tests/gui/test_gui_controller_bindings.py`)

Both built the controller with `AppController.__new__(AppController)`, bypassing `__init__`, so `_runtime_projection_coordinator`
never existed and they fail whenever run alone. Both asserted the removed direct model in which the controller itself mutates
panels.

| Retired test | Obsolete behavior asserted | Why not repaired | Current owner of the contract |
|---|---|---|---|
| `test_job_status_updates_use_ui_dispatcher` | a QUEUED status callback marshals a `queue_panel.upsert_job(dto)` call through `main_window.run_in_main_thread` | the controller no longer calls panel methods; supplying a coordinator stub would only re-assert the controller test below | **Callback requests the projection:** `tests/controller/test_gui_thread_dispatch_contract.py::test_on_job_status_for_panels_requests_state_projection_refresh`, `tests/controller/test_job_execution_controller_ui_dispatch.py::test_on_job_status_for_panels_requests_projection_refresh` (QUEUED/RUNNING/COMPLETED/FAILED). **UI-thread marshalling:** `_run_in_gui_thread` tests in both files (main-window dispatch, `root.after` fallback, direct call). **Versioned/stale-safe projection:** `tests/controller/test_runtime_projection_coordinator_v2.py`. **Sink to AppState:** `tests/controller/test_app_state_projection_sink_v2.py`. **Queue surface from AppState:** `tests/gui_v2/test_queue_run_controls_restructure_v2.py::test_queue_panel_update_from_app_state_projects_queue_truth`, `tests/gui_v2/test_pr_mvp_060_phase3a_r1_queue.py` (repository -> queue -> AppState -> queue panel) |
| `test_job_status_updates_with_root_fallback_run` | a COMPLETED status removes the job from the queue panel and appends a history item through the `root.after` fallback | same; terminal removal/history is now a projection of repository/history state, not a widget call | **Terminal status requests the history projection:** the two controller tests above (COMPLETED/FAILED). **History from store to AppState:** `tests/controller/test_pipeline_controller_history_refresh_v2.py`. **History surface from AppState:** `tests/gui_v2/test_job_history_panel_v2.py`, hot-surface subscriptions pinned in `tests/gui_v2/test_pipeline_tab_callback_metrics_v2.py`, AppState subscription tests (`test_app_state_subscribe_unsubscribe.py`). **Terminal jobs leave the queue:** the queue projection is built from repository state and exercised through real completions in `test_pr_mvp_060_phase3a_r1_queue.py` and `test_queue_panel_remove_updates_gui.py` |

No unique current signal is lost, so the tests were deleted rather than patched with
`controller._runtime_projection_coordinator = ...`; that would duplicate the controller tests and re-introduce the dead
direct-update model. No production compatibility guard (for example `getattr(self, "_runtime_projection_coordinator", None)`)
was added for `__new__`-constructed controllers: production `AppController.__init__` owns the coordinator. The remaining six
tests in the file (preview panel forwarding, run controls, queue-panel actions and button states) are unchanged; only the
imports that became unused were removed. (`tests/controller/test_gui_thread_dispatch_contract.py` also builds a controller with
`__new__` but supplies the coordinator explicitly, so it is order-independent.)

## Results

| | Before | After |
|---|---|---|
| `tests/gui/test_gui_controller_bindings.py` alone | 2 failed, 6 passed | 6 passed |
| `tests/gui` (whole directory, explicit selection) | 35 collected | 33 collected, 33 passed |
| default repository collection | 5,051 | 5,051 (unchanged, see below) |

Focused set (bindings; the two controller dispatch/projection-contract files; coordinator; sink; queue-panel, history-panel,
callback-metrics, repository-to-panel lifecycle, AppState subscription and history-refresh tests): 63 passed. The bindings file
also passes after `test_gui_thread_dispatch_contract.py` in the same process, so nothing depends on prior test state.

## Collection-count truth

The collected-test delta is exactly -2 for an explicit `tests/gui` selection (35 -> 33) and deliberate: obsolete duplicate
tests were retired, not product coverage. The default repository collection is unchanged at 5,051 because
`pyproject.toml` has `addopts --ignore=tests/gui` (since the harness-recovery package PR-MVP-010): `tests/gui` is never collected
by a bare `pytest` run or by the full census, only when targeted explicitly (the hosted `affected` lane does target it). Consequently
the statement in the PR-TEST-TRUTH-210 report that these tests "pass in the full suite through test-order state" was not literally
accurate; they were not part of the full suite at all. Whether `tests/gui` should remain outside default collection is a separate
repository-routing decision and is not changed here.

## Validation

`tools/ci/validation_plan.py` classifies this diff as lane `gui` only (no full census; the `affected` lane runs and is expected to
be free of this failure class). `python tools/ci/run_pr_gate.py` passes. Production diff: none; `app_controller.py` and the
controller ratchet are unchanged.
