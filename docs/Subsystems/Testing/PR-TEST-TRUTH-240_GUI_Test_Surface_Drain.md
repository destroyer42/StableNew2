# PR-TEST-TRUTH-240 - drain `tests/gui/` into canonical test owners

Result class: **TEST PLACEMENT / TEST TRUTH.** Implements the 33-case disposition in
`PR-TEST-TRUTH-230_Legacy_GUI_Test_Surface_Disposition_Audit.md`. **Zero `src/` changes**; no collection, CI-routing, workflow, marker
or watchdog change. Execution profile: Standard (Claude Code, Sonnet 5.5).

## Result

`tests/gui/` no longer contains any test. It holds a single non-test placeholder, `tests/gui/README.md`, because the routing-rot guard in
`tests/tools/test_ci_validation_plan.py` requires every target named in `tools/ci/validation_plan.py` to exist and that file still names
`tests/gui`; git cannot track an empty directory. The placeholder, the `--ignore=tests/gui` entry, the collection-gate exclusion, the
truth-sync expectation and the `validation_plan.py` mapping/target are all removed together by the separate follow-on
collection-authority package (not done here).

## Disposition reconciliation (33 cases)

| Disposition | Cases | Outcome |
|---|---:|---|
| MIGRATE_GUI_V2 | 18 | moved as 18 collected tests (below) |
| MIGRATE_DOMAIN | 4 | D2, D4, D5, D6 rewritten into 4 collected controller tests |
| CONSOLIDATE | 6 | B1, B3, L3, S1, D1, D3 -> 6 new collected tests plus one assertion folded into an existing test (D3 merged into D2's test) |
| RETIRE_DUPLICATE | 2 | L1, L4 deleted |
| RETIRE_OBSOLETE | 3 | B2, L2, L5 deleted |
| KEEP_TEMPORARILY | 0 | - |

Collection truth: explicit `tests/gui` was 33 cases. Default repository collection goes **5,051 -> 5,079 (+28)**:

* +18 GUI migrations (13 thumbnail + 2 plan table + 3 queue-panel position cases);
* +4 controller migrations (D2, D4, D5, D6);
* +6 tests created by consolidation: B1 -> 2 preview-panel tests, B3 -> 1 move-forwarding test, L3 -> 1 builder consumer test, S1 -> 1
  real-`StateManager` test, D1 -> 1 deterministic coalescing test; D3 merged into D2's test (no new test); S1's RUNNING mapping is one
  assertion added to an existing test (no new test);
* +0 for the 5 retired cases (L1, L4, B2, L2, L5).

18 + 4 + 6 = 28. No placeholder tests were added to hold the count.

## Canonical destinations

| Behavior | Owner |
|---|---|
| `ImageThumbnail` geometry, sizing/caps, resize debounce, missing PIL (now actually exercises the missing-PIL branch), missing file, render, clear, per-platform default viewer (13 cases) | `tests/gui_v2/test_image_thumbnail_v2.py` |
| `LearningPlanTable` numbering/stage and selection index (2); the silent `return` without Tk is replaced by the `gui_v2` `tk_root` fixture (real skip) | `tests/gui_v2/test_learning_plan_table_v2.py` |
| Queue-panel position-driven button states (3) and move-up/move-down forwarding (unique remainder of B3; other forwarding is owned by `test_pr_mvp_080_action_state_truth.py`) | `tests/gui_v2/test_queue_panel_button_positions_v2.py` |
| Preview-panel legacy `on_add_to_queue` fallback and `on_clear_draft` forwarding (unique remainder of B1) | `tests/gui_v2/test_preview_panel_add_to_queue_v2.py` |
| `AppController` UI-update debounce (5): deterministic preview coalescing with a recording scheduler (one callback, no refresh before it runs, one refresh after, re-arm), multi-category apply and flag clearing, heartbeat advance only when scheduled UI work executes (fake clock, no sleep), exception isolation, queue-update coalescing | `tests/controller/test_app_controller_ui_debounce.py` |
| `GUIState` mapping of RUNNING (folded into the existing lifecycle test) and acceptance of the mapped transitions by the real `StateManager` | `tests/controller/test_controller_job_lifecycle.py` |
| `PackJobEntry.learning_metadata["submission_source"]` as the NJR `intent_config["source"]` (default `add_to_queue`), the real consumer in `prompt_pack_job_builder` | `tests/controller/test_builder_pipeline_contract_v2_6.py` (the builder contract test lives under `tests/controller/`) |

## Retired tests

* Duplicates: `test_learning_tab_receives_pipeline_controller` (attribute assignment; behavior covered by `test_learning_controller_njr.py` and
  `test_learning_controller_integration.py`), `test_submit_variant_job_delegates_to_execution_controller` (stronger end-to-end coverage in
  `test_learning_controller_njr.py::test_submit_variant_job_uses_job_service` and `test_learning_completion_resume_regressions.py`).
* Obsolete: `test_pipeline_run_controls_forward_requests` (`PipelineRunControlsV2` is not instantiated by the layout; asserted by
  `test_queue_run_controls_restructure_v2.py`), `test_learning_controller_builds_correct_overrides` (`_build_variant_overrides` has no production
  caller), `test_learning_controller_handles_missing_queue_controller` (passed only because a `MagicMock` was not JSON serializable during NJR build,
  not because of any missing controller).
* The vacuous `refresh_count <= 3` coalescing test was replaced by the deterministic scheduler test above; the old real `time.sleep(0.01)` is gone.

## Heartbeat note

`AppController._apply_pending_ui_updates` still updates `last_ui_heartbeat_ts` (unchanged). In production it runs through the UI dispatcher, so
it is Tk-loop evidence; the migrated test now shows the timestamp moves only when the scheduled UI work actually executes. Whether the heartbeat
model should change is a separate runtime question.

## Validation

* Focused owners: 84 passed (all changed files plus neighbouring queue/preview/thumbnail/learning/builder tests); the new files also pass in a
  different order. No new test imports `PipelineRunControlsV2`; the migrated debounce tests contain no sleep.
* `python tools/ci/run_pr_gate.py` passes (5,079 tests collected, 341-test smoke). `tools/ci/validation_plan.py` selects lanes `core` and `gui` with
  no full census.
* Timing: the migrated cases cost about 0.5 s in total; no material change.

## Remaining work (separate packages)

* **Collection-authority cleanup (follow-on C): resolved** by `PR-TEST-TRUTH-250_GUI_Collection_Authority_Closeout.md`, which removed `--ignore=tests/gui`, the collection-gate exclusion, the truth-sync expectation, the `validation_plan.py` mapping/target and the `tests/gui/README.md` placeholder.
* **Dead production code (not touched):** `PipelineRunControlsV2`, `LearningController._build_variant_overrides` and
  `src/gui/views/learning_plan_table_v2.py` have no current callers and are candidates for a separate owner-approved cleanup.
