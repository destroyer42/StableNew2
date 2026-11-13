# P3-2B — Retire the dormant run and replay paths; characterize pause/auto-run ownership

Status: **IMPLEMENTED, 2026-11-13.** Follows P3-2A ([package](P3-2A_runtime_stack_consolidation.md), PR #292).
Execution class: Standard (a deletion package with reachability proof).

## Owner decisions (2026-11-13, made by the coordinating session under owner delegation)

- **OD-2 / OD-6:** full bootstrap-level inversion (`build_v2_app` builds and injects the stack, an authoritative production
  flag) is **not** done now. One factory called from the controllers plus a verified `RuntimeStack` is the accepted
  runtime-stack composition for the Tk host; revisit only when a second production host (Qt) is authorized. No production
  flag is introduced.
- **OD-3 tier C:** retire `AppController._execute_job` and, where unreachable, `PipelineController._run_job`.
- **OD-7:** retire `run_app` and the direct-admission replay path, each only after a reachability proof.
- **OD-5:** characterization tests only; no ownership, default or restart-behaviour change.

## Reachability result

Static: no reference in `src`, `tools`, `scripts`, `pyproject.toml` entry points or runbooks beyond the definitions and
the listed dormant call chain. Dynamic: an uncommitted pytest recorder wrapped each target and logged the immediate caller
over the first 44% of the census in directory order (about 7.3k of 16,459 tests, run on the #292 merge source, then
stopped for time). Result: only tests called the targets. `AppController._execute_job` 9 calls, all from the nine tests
mapped below; `JobHistoryService.retry_job` 2 and `JobExecutionController.replay` 2, from the mapped tests (one `replay` call
came from `retry_job` itself); no call from any other `src` frame. `PipelineController._run_job` was called 191 times by
`SingleNodeJobRunner` as a test-injected run callable, which is why it is kept. The unrun remainder is covered by the static
proof and a grep of `tests/`: the mapped tests are the only ones that name these methods. The census cannot see
subprocess-run tests.

| Target | Verdict | Evidence |
| --- | --- | --- |
| `AppController._execute_job` | **Deleted** | no `src`/`tools` caller; production run callable is `JobExecutionController._run_job_callback` |
| `run_app` (`src/gui/main_window_v2.py`) | **Deleted** | no caller; `main.py` -> `build_v2_app` is the launcher (`journey_harness.run_app_once` is a different function) |
| `JobExecutionController.replay` | **Deleted** | only callers were `JobHistoryService.retry_job` and `PipelineController.on_replay_history_job_v2` |
| `JobHistoryService.retry_job` (and `NullHistoryService.retry_job`) | **Deleted** | no caller |
| `PipelineController.on_replay_history_job_v2` | **Deleted** | the History panel binds `app_controller or pipeline_controller`; production replays through `AppController.on_replay_history_job_v2` (job id) -> `PipelineController.replay_job_from_history` -> `JobService`. The deleted method took a `HistoryRecord`, so a job id handed to it could never have worked |
| `PipelineController._run_job` | **Kept** | used as the run callable by `tools/acceptance/img_forge_100`, `img_forge_120_default`, `vid130_wan`, `vid190_queue_recycling`, `tools/qualification/img_forge_100/run.py`, `tests/helpers/njr_queue_harness.py` and several integration tests. Not a production caller, but retiring it means rewriting evidence tooling: separate decision |

`PipelineController._execute_job` (a different, payload-calling method passed to `JobExecutionController(execute_job=...)`)
was not a target and is unchanged.

## Finding R3 — the `ready_gate` result

`execution_path = "ready_gate"` was produced only by the retired `_execute_job`. The live path protects against a WebUI
that is not ready earlier and more strongly: the queue's startup hold (`WebUIOutageCoordinator.enable_startup_gate`,
pinned by `tests/controller/test_production_wiring_startup_gate.py`), the outage hold, the runtime-handoff gate and the
executor's true-ready gate (`PipelineExecutor._ensure_webui_true_ready`, which yields `true_ready_timeout` evidence
classified as a not-dispatched readiness failure). So no protection is lost and none was added. The consumer branch in
`src/api/webui_failure_evidence.assess_result` and its tests (`tests/queue/test_webui_outage_containment_171.py`,
`test_gpu_loss_assessment_180.py`, `test_cancel_return_dispatch_certainty.py`) are **kept**: no producer remains, but the
consumer also reads results the application did not just produce, and removing it is a typed-contract decision.

## Per-test mapping

| Deleted or changed test | Disposition | Live coverage |
| --- | --- | --- |
| `test_app_controller_njr_exec.py::test_njr_backed_job_uses_run_job` | deleted | `test_pipeline_controller_queue_mode.py::test_queued_job_executes_njr_through_pipeline_runner_run_njr` (`_run_job_callback` -> `run_njr`) |
| `…::test_njr_failure_marks_job_as_failed` | deleted | `test_job_execution_controller_queue_v2.py::test_run_job_callback_replay_exception_logs_and_raises` (live path raises; the queue owns FAILED) |
| `…::test_job_without_njr_is_rejected`, `test_njr_with_none_record_is_rejected`, `test_payload_job_without_njr_or_pipeline_config_returns_error` | deleted | `…::test_run_job_callback_missing_normalized_record_raises` |
| `…::test_njr_without_pipeline_controller_is_rejected` | deleted | none needed: the live path has no `AppController` hop to a missing `pipeline_controller` |
| `test_core_run_path_v2.py::test_njr_backed_job_uses_njr_execution_path`, `::test_njr_job_failure_returns_error_no_fallback_b2` | deleted | same two live tests as above |
| `test_webui_readiness_gate_v2.py::test_queue_job_fails_when_webui_not_ready` | deleted | see finding R3 |
| `test_job_history_service.py::test_history_service_retry_uses_canonical_replay` | deleted | `test_pr_mvp_060_image_vertical_slice.py` (replay through `AppController.on_replay_history_job_v2`: new job id, `parent_job_id`) |
| `test_history_replay_integration.py::test_replay_invokes_njr_path` | deleted | same vertical-slice test and `HistoryHandoffService` tests |
| `test_pr_mvp_060_phase2b.py::test_retry_is_new_lineage_and_preserves_authorized_workload` | **re-pointed** to the live admission (`HistoryHandoffService.replay_job_from_history` submitting through the queue); every assertion kept |
| `test_runtime_stack_negative_p3_2.py` N1 allowlist | the `run_app` exemption removed (its stale-entry check would fail otherwise) |

## OD-5 characterization (changes nothing)

`tests/controller/test_pause_auto_run_characterization_p3_2b.py` (13 tests) pins: the differing defaults (`JobExecutionController`
auto-run on, `JobService` off); that auto-run persists only through the controller (`auto_run_enabled`) while pause persists
as `queue_paused` via `JobQueue` whichever object pauses; that `JobService.pause` leaves the controller's cached pause flag
stale; restart restoration and the deferred-autostart rule; and `sync_queue_state` copying the controller's flags onto the
service and `AppState`.

## Ratchets

Controller ceilings lowered (against `main` at `32f52620`): `app_controller.py` 5213 -> 5161, `pipeline_controller.py` 1607 -> 1599,
`job_history_service.py` 647 -> 619. mypy baseline 1412 -> 1408; ruff BLE001 1217 -> 1214, S110 480 -> 479; unformatted files unchanged (378).
