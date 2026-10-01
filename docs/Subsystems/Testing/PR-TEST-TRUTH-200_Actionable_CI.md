# PR-TEST-TRUTH-200 — Restore Actionable CI & Consolidate Legacy Journeys

Status: implemented on `feature/pr-test-truth-200-actionable-ci` (base `origin/main` 4acad71).
Test and CI infrastructure, plus two bounded production fixes (three files) found by the work (PR-TEST-TRUTH-200R, below):
`pipeline_runner.py` (randomizer projection), `single_node_runner.py` and `job_service.py`
(one-shot -> continuous worker handoff). Required CI behavior unchanged.

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

## Production defects found and fixed (PR-TEST-TRUTH-200R)

1. **Runner randomizer projection.** `PipelineRunner.run_njr` projected
   `getattr(njr, "randomizer_mode", "")`, a field the eight-part NJR no longer has, so
   `PipelineRunResult.randomizer_mode` was always empty for NJR runs. It now uses the
   typed authority `njr.variant_mode` (`WorkloadSpec.variant_mode`, default `"standard"`);
   the learning record already read the same property. No NJR field was added; replay
   keeps reading old results (`""` still deserializes). Regressions: non-standard mode
   (`fanout`) and default (`standard`) in `tests/pipeline/test_pipeline_io_contracts.py`.
2. **One-shot -> continuous worker race.** `QueueWorkerOnce` stayed alive after its job was
   durably terminal, so `runner.is_running()` made `JobService` skip starting the
   continuous worker when auto-run was enabled/resumed in that interval; the one-shot then
   exited and queued jobs stalled. `SingleNodeJobRunner` (thread lifecycle authority) now
   guards worker state with a lock, lets `start()` ask a live one-shot to hand off to
   continuous draining on the same thread, and reports a worker that has committed to
   retiring as not running; `JobService` (dispatch-policy authority) always requests
   continuous dispatch when auto-run is on. No sleeps, no second runner. Boundary
   regressions in `tests/controller/test_auto_run_worker_lifecycle_v2.py` hold the
   `COMPLETED` status callback open (durable completion, thread alive) and prove drain for
   auto-run enable and resume (they stall without the fix), plus exactly-once execution, a
   manual one-shot with auto-run off, and re-enable after a continuous worker commits to
   retire. `test_pr_mvp_060_phase1b` now waits for runner idle before the next manual
   Send Job (durable COMPLETED precedes worker retirement by design).

## Optional dependencies and host isolation

- The 14 `tests/tools` failures were offline qualification tools that need NumPy/OpenCV,
  declared only in the `svd` extra (`requirements-svd.txt`), not base `requirements.txt`.
  They now skip with that reason (`tests/helpers/optional_deps.py`).
- `tests/conftest.py` pins `STABLENEW_WEBUI_AUTOSTART=0`, `STABLENEW_COMFY_AUTOSTART=0` and
  resets the cached WebUI autostart answer for every test; tests of autostart behavior
  override it explicitly (`tests/system/test_test_runtime_isolation.py`). Production
  defaults are unchanged.
- Host sensitivities removed: ADetailer executor tests no longer sample live GPU pressure;
  the operator-journey subprocess hides `nvidia-smi`; one real-time grace test uses a
  generous grace (the boundary is pinned by the fake-clock test).
- `tests/helpers/njr_queue_harness.py` dumps all thread stacks when a job is not terminal.

## Process-global isolation added to `tests/conftest.py`

An autouse fixture clears `ThreadRegistry` bookkeeping, resets the `SystemWatchdogV2`
single-flight slot, and restores `sys.excepthook`/`threading.excepthook` after each
test. Without it, `AppController`s that tests never shut down stack their chained
exception hooks until one thread exception recurses to a stack overflow (observed as a
Windows fatal crash of the whole run) and leaked threads/watchdogs fail unrelated
lifecycle tests only in a whole-suite run. It forgets leaked threads; it does not stop
them, and the leaking tests themselves are unaudited debt.

## Verification

- Single-process full suite, Python 3.11 local, at the 200R head: **3951 passed, 78 skipped,
  0 failed** (collected 4027). Skips: 15 golden-path `Implementation pending`, 14 optional
  NumPy/OpenCV (+4 `cv2` importorskip), 16 PR-GUI-F1 "widget removed", 2 opt-in evidence
  env vars, 1 opt-in shutdown-leak process test, 1 stage-ordering placeholder, Tk/Tcl when
  unavailable. Base census: about 300 failures plus a hang and a stack-overflow crash.
- Required gate pieces pass locally: repository completeness, controller ratchet
  (`job_service.py` ceiling lowered 1246 -> 1245), Ruff, collection gate, required smoke
  (129 passed), `git diff --check`. `tools/ci/run_pr_gate.py` stops at the missing-`mypy`
  local tooling blocker.
- Python 3.12 and GitHub CI are the canonical cross-version verdict.

## Known environment limits

- Optional/opt-in skips unchanged (cv2 importorskip, evidence env vars, Tk/Tcl
  intermittent init, `Implementation pending` golden-path placeholders, ~38
  PR-GUI-F1 "widget removed" skips left for one cleanup commit).
- `tests/tools/test_operator_journey_gui.py` asserts the worktree stays clean, so it
  is unreliable while other pytest processes share the same worktree.
- A real `test_pack.json` written by the old `test_json_unification` may remain in
  `%LOCALAPPDATA%\StableNew\PromptPacks`; owner may delete it.
