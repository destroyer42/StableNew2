# PR-TEST-TRUTH-230 - `tests/gui/` surface disposition audit

Result class: **READ-ONLY AUDIT.** This package changed no test, source, pytest/collection configuration, CI routing, workflow or
marker. It adds only this report. Measurements are from one clean local Windows run (CPython 3.14.8) on the unchanged source.

## 1. Executive conclusion

`tests/gui/` is a six-file, **33-case** directory that has been excluded from default collection (and therefore from every
`full-suite` census) since before the harness-recovery package. The reason recorded for the exclusion ("requires a live Tk display" /
"Tkinter issues") is **no longer true**: only 8 of the 33 cases (two files) construct a Tk root, 25 are display-free, CI runs under
Xvfb, and `tests/gui_v2/` (631 Tk-heavy cases) is collected by default. The directory is not legacy GUI v1 either: it tests current
v2 surfaces (`QueuePanelV2`, `PreviewPanelV2`, `LearningPlanTable`, `AppController`, `LearningController`).

It costs almost nothing (0.8 s wall, 0.5 s summed) yet is silently outside the periodic census and the required gate; it only runs
when a PR routes to the GUI `affected` lane. Its contents are a mix of misplaced current coverage, duplicated coverage and three
tests of dead architecture:

| Disposition | Cases | Share |
|---|---:|---:|
| MIGRATE_GUI_V2 | 18 | 54.5% |
| MIGRATE_DOMAIN | 4 | 12.1% |
| CONSOLIDATE | 6 | 18.2% |
| RETIRE_DUPLICATE | 2 | 6.1% |
| RETIRE_OBSOLETE | 3 | 9.1% |
| KEEP_TEMPORARILY | 0 | 0% |

**Recommendation: Strategy 2 - drain and retire `tests/gui/`** (confirmed by the evidence, ranking in section 9): relocate 22 cases to
their canonical owners, fold the unique remainder of 6 into existing tests, retire 5, delete the empty directory and remove the
now-meaningless exclusion. Reincorporating the directory wholesale (Strategy 1) would freeze 5 obsolete/duplicate cases and keep a
wrong taxonomy; preserving it (Strategy 3) has no remaining justification.

## 2. Why the directory is excluded (history)

* The exclusion first appeared in `pytest.ini` on 2026-01-02 as `--ignore=tests/gui/` under the comment "Ignore GUI tests with Tkinter
  issues (can be run separately if environment configured)", inside a bundled functional commit (`6e2a23c`). The rationale was an
  environment problem, not a verdict on the tests.
* The harness-recovery package PR-MVP-010 (2026-09-06, `047ae08`) moved the rule into `pyproject.toml` (`--ignore=tests/gui`) and the
  collection gate, and labelled the directory "Optional legacy GUI - requires a live display and does not define GUI v2" in its surface
  manifest, while keeping `tests/gui_v2/` collectable and headless-safe. It warned that exclusions can hide useful tests, that excluded
  surfaces must stay explicitly runnable, and that later packages would decide promotion, quarantine or removal. At that commit the
  directory already held exactly today's six filenames.
* The six files were added between 2025-12 and 2026-03 (bindings and state-manager 2025-12-10, learning wiring 2025-12-31, thumbnail
  2026-01-01, debounce 2026-01-08, plan table 2026-03-08), i.e. they track the v2 architecture, not a superseded GUI.
* That follow-up decision never happened: PR-TEST-TRUTH-210 repaired one file and recorded debt, PR-TEST-TRUTH-220 retired two stale
  tests, and both noted the exclusion. This audit is the promotion/removal decision input.

Is the reason still valid? **No.** (a) Display need: bindings (6 cases) and plan table (2) need Tk; the other four files (25 cases) use
`__new__` + mocks or plain controllers. (b) CI installs `python3-tk xvfb` and `pytest-xvfb`; the hosted `affected` lane already runs this
directory green. (c) `tests/gui_v2/` has the same Tk dependency and is collected by default, with a `TclError` skip. (d) The two
Tk-needing files already skip safely when Tk is absent (bindings) or pass vacuously (plan table, see section 5).

## 3. Current routing behavior

| Mechanism | Treatment of `tests/gui/` |
|---|---|
| `pyproject.toml` `addopts` | `--ignore=tests/gui` (never collected by a bare `pytest`) |
| `tools/ci/run_collection_gate.py` `DEFAULT_COLLECTION_EXCLUDES` | excluded from the isolated collection gate |
| `required` job (smoke + contract list) | not run |
| `full-suite` census (periodic/broad) | not run (explicit `--ignore`; the 5,051-case default collection excludes it) |
| `tools/ci/validation_plan.py` | `tests/gui/*` -> GUI lane; `tests/gui` is a GUI domain target, so a GUI-lane PR's `affected` job runs it explicitly |
| `tests/system/test_ci_truth_sync_v2.py` | asserts that every `DEFAULT_COLLECTION_EXCLUDES` path appears as `--ignore=` in `pyproject.toml` |

Net effect: the directory is **excluded from default/full collection but actively routed into GUI affected execution**. The
Monday/Wednesday/Friday census and any release census therefore never exercise it; a regression in these surfaces is caught only by a
PR that happens to touch the GUI lane. (PR-TEST-TRUTH-210's remark that these tests "pass in the full suite through test-order state"
was inaccurate for the same reason; PR-TEST-TRUTH-220 already corrected it.)

## 4. Inventory (verified by collection)

| File | Cases | Needs Tk root | Production surface |
|---|---:|---|---|
| `test_gui_controller_bindings.py` | 6 | yes (`tk.Tk()`, skips on `TclError`) | `PreviewPanelV2`, `QueuePanelV2`, `PipelineRunControlsV2` |
| `test_image_thumbnail.py` | 13 | no | `src/gui/widgets/image_thumbnail.py` (`ImageThumbnail`, `fit_image_size`) |
| `test_learning_plan_table.py` | 2 | yes (`get_shared_tk_root`) | `LearningPlanTable` |
| `test_learning_tab_wiring.py` | 5 | no | `LearningController`, `PackJobEntry` |
| `test_state_manager_legacy.py` | 1 | no | `PipelineController._on_job_status` -> `GUIState`/`StateManager` |
| `test_ui_debounce.py` | 6 | no | `AppController._mark_ui_dirty` / `_apply_pending_ui_updates` / `_on_queue_updated` |
| **Total** | **33** | 8 of 33 | |

Default repository collection is 5,051 and does not include these 33.

## 5. Per-test disposition matrix

Columns: surface/reachability; current contract; nearest active coverage; overlap; unique signal; hermeticity and weakness;
disposition (confidence). "Display" means a real/virtual display is needed. Every case is reachable in the real application unless marked dead.

### `test_gui_controller_bindings.py` (6)

| # | Test | Surface and reachability | Contract / nearest active coverage | Overlap and unique signal | Hermeticity / weakness | Disposition |
|---|---|---|---|---|---|---|
| B1 | `test_preview_panel_calls_controller_methods` | `PreviewPanelV2` (live) | panel forwards add / clear-draft / details to its controller. Active: `gui_v2/test_preview_panel_add_to_queue_v2.py` (v2 add handler preferred), `gui_v2/test_logging_details_default_v2.py` (details button), `controller/test_controller_event_api_v2.py` (controller side of clear draft) | add (v2 path) and details duplicated; **unique: panel `_on_clear_draft` forwarding and the legacy `on_add_to_queue` fallback** | display; private-method calls | CONSOLIDATE into the two `gui_v2/test_preview_panel*` files (high) |
| B2 | `test_pipeline_run_controls_forward_requests` | `PipelineRunControlsV2` - **dead widget**: not imported or instantiated by the layout; `gui_v2/test_queue_run_controls_restructure_v2.py::TestNoRunControlsPanel` asserts exactly that | auto-run/pause/resume forwarding; these controls now live on `QueuePanelV2` and are covered by `gui_v2/test_pr_mvp_080_action_state_truth.py` | none (dead surface) | display | RETIRE_OBSOLETE (high). Dead-class deletion is a separate production decision |
| B3 | `test_queue_panel_invokes_controller_actions` | `QueuePanelV2` (live) | panel forwards auto-run, pause/resume, move, remove, clear, send. Active: `test_pr_mvp_080_action_state_truth.py::test_queue_actions_require_capability_and_truthful_outcomes` (auto/pause/send/remove/clear, with capability and truthful-outcome checks, stronger) | 6 of 8 forwarded actions duplicated at higher fidelity; **unique: `_on_move_up` / `_on_move_down` forwarding** | display; stubs `_get_selected_job`; expected list silently omits `move_up` (a no-op at index 0) | CONSOLIDATE: keep only move-forwarding in the canonical queue-panel test (high) |
| B4 | `test_queue_panel_disables_remove_and_clear_for_running_only_queue` | `QueuePanelV2` button states | running-only queue disables remove/clear/send. Active 080 test asserts running+queued; `phase1d` uses fake buttons | partial surface overlap; **unique: clear disabled when only a running job exists** | display | MIGRATE_GUI_V2 (high) |
| B5 | `test_queue_panel_move_buttons_use_queued_position_not_visual_index` | `QueuePanelV2` position logic | move buttons derive from queued position, not listbox index. `phase1d` stubs `_selected_queued_position`, so the logic is not exercised there | none | display | MIGRATE_GUI_V2 (high) |
| B6 | `test_queue_panel_enables_move_up_for_second_queued_job_below_running` | `QueuePanelV2` position logic | as B5 for the second queued job | none | display | MIGRATE_GUI_V2 (high) |

### `test_image_thumbnail.py` (13) - `ImageThumbnail` (live: `learning_review_panel`, `learning_tab_frame_v2`, `discovered_review_table`)

`ImageThumbnail` is a different class from `ThumbnailWidget`; `gui_v2/test_thumbnail_widget_v2.py` (one case) covers only
`ThumbnailWidget`'s open-target behavior. No active test covers `ImageThumbnail`. All 13 are display-free (`__new__` + `MagicMock`;
rendering is via a patched `ImageTk`), deterministic, and take 0.002 s each.

| # | Test | Contract | Disposition |
|---|---|---|---|
| T1-T4 | `test_fit_image_size_preserves_geometry_without_crop_or_unneeded_enlarge` x4 | pure `fit_image_size` geometry (landscape, portrait, no enlarge, shrink) | MIGRATE_GUI_V2 (high) |
| T5 | `test_fit_image_size_honors_widget_dimensions_and_caps` | `_resize_to_fit` honors widget size and caps | MIGRATE_GUI_V2 (high) |
| T6 | `test_fit_thumbnail_resize_debounces_and_discards_stale_path` | resize debounce and stale-path discard | MIGRATE_GUI_V2 (high) |
| T7 | `test_thumbnail_handles_missing_pil` | **weak**: asserts only that the module exposes `ImageThumbnail`/`PIL_AVAILABLE` (true with PIL present; it never exercises absence) | MIGRATE_GUI_V2, strengthen (patch `PIL_AVAILABLE` false and load) or drop at migration (medium) |
| T8 | `test_thumbnail_handles_missing_file` | missing file returns False and shows a placeholder | MIGRATE_GUI_V2 (high) |
| T9 | `test_thumbnail_loads_valid_image` | valid image renders centered (repaired in PR-TEST-TRUTH-210) | MIGRATE_GUI_V2 (high) |
| T10 | `test_thumbnail_clear` | clear resets state | MIGRATE_GUI_V2 (high) |
| T11-T13 | `test_thumbnail_open_current_path_uses_default_viewer` x3 (nt, darwin, linux) | per-platform default-viewer launch, patched `os`/`subprocess` | MIGRATE_GUI_V2 (high) |

### `test_learning_plan_table.py` (2) - `LearningPlanTable` (live: `learning_tab_frame_v2`)

No active test references `LearningPlanTable`. Both use the shared Tk helper, which returns `None` without Tk, and then **`return` (a
vacuous pass) instead of skipping**.

| # | Test | Contract | Disposition |
|---|---|---|---|
| P1 | `test_learning_plan_table_variant_numbering_and_stage` | row numbering ("#1", "#2") and stage column | MIGRATE_GUI_V2 (high); replace the silent return with `pytest.skip` |
| P2 | `test_learning_plan_table_selection_callback_uses_row_index` | selection callback receives the row index | MIGRATE_GUI_V2 (high) |

### `test_learning_tab_wiring.py` (5) - `LearningController`

| # | Test | Reachability / evidence | Disposition |
|---|---|---|---|
| L1 | `test_learning_tab_receives_pipeline_controller` | asserts `controller.pipeline_controller is mock` after construction (attribute assignment). Behavior is exercised by `controller/test_learning_controller_njr.py` (submit through `pipeline_controller._job_service`) and `controller/test_learning_controller_integration.py::test_learning_controller_receives_execution_controller` | RETIRE_DUPLICATE (high); the "MainWindow passes pipeline_controller" claim in its docstring is not what it tests |
| L2 | `test_learning_controller_builds_correct_overrides` | `_build_variant_overrides` has **no production caller** (`src/` references only its own definition); current variants go through `_build_variant_njr`, covered by `test_learning_controller_njr.py` | RETIRE_OBSOLETE (high). The uncalled method itself is a separate dead-code finding |
| L3 | `test_learning_metadata_added_to_pack_entry` | asserts a dataclass stores a dict. The field is real: `PackJobEntry.learning_metadata["submission_source"]` is read by `prompt_pack_job_builder` to choose the intent `source`, and **no active test covers that consumer** | CONSOLIDATE: drop the tautological storage assertion; add a builder-contract assertion (a `PackJobEntry` with `submission_source` yields that `source` in the NJR intent) to `controller/test_builder_pipeline_contract_v2_6.py` (medium-high). Not a "Learning Tab wiring" test |
| L4 | `test_submit_variant_job_delegates_to_execution_controller` | `LearningController._submit_variant_job` -> `execution_controller.submit_variant_job(record, variant, experiment_name, variable_under_test)`. Active: `test_learning_controller_njr.py::test_submit_variant_job_uses_job_service` (real submit through `JobService`, status `queued`), `test_learning_completion_resume_regressions.py` (`execution.submit_variant_job` -> `_job_to_variant`) | RETIRE_DUPLICATE (medium-high): end-to-end coverage is stronger than the mock-kwargs assertion |
| L5 | `test_learning_controller_handles_missing_queue_controller` | premise is obsolete (`queue_controller` is not part of the path). Reproduced: the variant ends `failed` only because `_build_variant_njr` raises `Object of type MagicMock is not JSON serializable`, an unrelated incidental error, not because anything is "missing". The genuine contract (submission cannot proceed -> variant `failed`) has no active test | RETIRE_OBSOLETE (high); optionally add one explicit "execution controller returns False -> variant failed" case to `test_learning_controller_njr.py` |

### `test_state_manager_legacy.py` (1)

| # | Test | Evidence | Disposition |
|---|---|---|---|
| S1 | `test_job_status_transitions_state_manager` | `PipelineController._handle_status` still drives `GUIState` through `_safe_gui_transition`; the file name is misleading. `controller/test_controller_job_lifecycle.py` covers COMPLETED->IDLE, FAILED->ERROR, CANCELLED->IDLE with a fake capture. **Unique: RUNNING->RUNNING mapping and acceptance by the real `StateManager`** | CONSOLIDATE into `controller/test_controller_job_lifecycle.py`; drop "legacy" naming (high) |

### `test_ui_debounce.py` (6) - `AppController` debounce (live: `_mark_ui_dirty` is called from `_on_queue_updated` and preview refresh paths)

All build a real `AppController(main_window=None, threaded=False)`, whose constructor installs root-logger handlers (process-global
state). With no main window `_ui_dispatch_later` runs the callback immediately.

| # | Test | Evidence | Disposition |
|---|---|---|---|
| D1 | `test_debounce_coalesces_multiple_calls` | **vacuous**: with no window each `_mark_ui_dirty` applies immediately, so three marks produce three refreshes (measured: count = 3) and `assert refresh_count <= 3` always holds; it proves no coalescing | CONSOLIDATE: replace with a deterministic preview-coalescing assertion (captured scheduler, as D6) in the canonical owner (high) |
| D2 | `test_dirty_flags_cleared_after_apply` | flags and pending cleared after apply; no other active coverage | MIGRATE_DOMAIN -> `tests/controller/` (high) |
| D3 | `test_multiple_dirty_types_handled` | adds only "preview refresh runs" to D2's flag clearing | CONSOLIDATE with D2 (high) |
| D4 | `test_debounce_updates_heartbeat_timestamp` | applying updates advances `last_ui_heartbeat_ts`; uses a real `time.sleep(0.01)` | MIGRATE_DOMAIN with a clock seam instead of the sleep (medium). See finding F3 |
| D5 | `test_debounce_handles_exceptions_gracefully` | a failing refresh does not wedge the debounce | MIGRATE_DOMAIN (high) |
| D6 | `test_queue_updates_are_coalesced_into_one_refresh` | strong and deterministic: three queue updates schedule one apply; the apply refreshes once and clears flags | MIGRATE_DOMAIN (high) |

## 6. Timing evidence (one clean pass, unchanged source `b7fcde0`, Windows, CPython 3.14.8)

Produced with `pytest tests/gui` + JUnit (`junit_duration_report=total`) summarised by `tools/ci/census_summary.py`.

| Measure | `tests/gui` | `tests/gui_v2` (same machine, same pass type) |
|---|---|---|
| collected / passed / skipped | 33 / 33 / 0 | 631 / 631 / 0 |
| wall (pytest) | 0.8 s (1.19 s whole process) | 95.4 s |
| summed test time | 0.5 s | 94.6 s |

| File | Cases | Seconds |
|---|---:|---:|
| `test_gui_controller_bindings.py` | 6 | 0.3 (slowest case 0.097 s, Tk root creation) |
| `test_learning_plan_table.py` | 2 | 0.1 |
| `test_state_manager_legacy.py` | 1 | 0.1 (0.083 s: constructs `PipelineController`) |
| `test_ui_debounce.py` | 6 | 0.1 (one real 10 ms sleep) |
| `test_image_thumbnail.py` | 13 | < 0.05 |
| `test_learning_tab_wiring.py` | 5 | < 0.05 |

Setup/teardown are the only visible overhead (Tk root create/destroy, about 0.02-0.08 s per Tk case). No skip occurred locally. The
directory is 33 of 664 GUI-directory cases (5.0%) and about 0.8% of GUI-directory time. Historical comparison (separate, not equated):
PR-DEVEX-CI-110 recorded roughly 630 `gui_v2` cases / 164 s on its Windows baseline; the PR #46 hosted GUI `affected` lane ran 950 tests
(947 passed, 3 skipped, 152.72 s) and covers far more than either GUI directory, so that figure is not the cost of `tests/gui`.

## 7. Overlap analysis (every count traces to section 5)

| Measure | Result | Cases |
|---|---|---|
| Direct duplicate overlap (same behavior at equal or stronger fidelity) | 2 / 33 | L1, L4 |
| Partial duplicate inside a consolidation (some assertions duplicated, a unique remainder kept) | 3 | B1, B3 (6 of 8 forwarded actions), S1 (3 of 4 mapped statuses) |
| Obsolete (dead or incidental architecture) | 3 / 33 | B2, L2, L5 |
| Unique current GUI signal | 18 / 33 (+ the unique remainders of B1 and B3) | B4-B6, T1-T13, P1-P2 |
| Unique current non-GUI / domain signal | 4 / 33 (+ the unique remainders of S1 and D1/D3, and L3's builder gap) | D2, D4, D5, D6 |
| Mixed / consolidation candidates | 6 / 33 | B1, B3, L3, S1, D1, D3 |
| Misplaced (current signal in the wrong directory) | 22 / 33 whole cases (+ remainders above) | MIGRATE_GUI_V2 + MIGRATE_DOMAIN |
| Surface overlap only (same widget, different behavior; not duplication) | B4-B6 vs the 080/`phase1d` queue-panel tests; T11-T13 vs `ThumbnailWidget`; D-series vs controller projection tests | not counted as duplicates |

Weak assertions found: D1 (vacuous bound), T7 (existence check), L3 (tautological storage), L5 (passes for an unrelated reason), P1/P2
(vacuous pass without Tk), D4 (real sleep).

## 8. Current-vs-legacy architecture findings

* `tests/gui/` is **not** a legacy-GUI-v1 surface; every production target is current v2 code. The "legacy" label and the "optional"
  category no longer describe it.
* The projection-driven GUI (coordinator -> sink -> AppStateV2 -> subscribers) is already owned by `controller/` and `gui_v2/` tests; the
  directory's only projection-model tests were retired in PR-TEST-TRUTH-220.
* Dead production surfaces found while auditing (documented, **not** acted on): `PipelineRunControlsV2` (unreferenced widget; B2 tests
  it), `LearningController._build_variant_overrides` (no caller; L2 tests it) and `src/gui/views/learning_plan_table_v2.py` (a second
  `LearningPlanTable` class that nothing imports; the live one is `learning_plan_table.py`).
* F3 (needs owner/product-semantics review, not a test decision): `AppController._apply_pending_ui_updates` sets
  `last_ui_heartbeat_ts`, and D4 pins that. The watchdog documents that the UI heartbeat must come from the Tk main loop only. The debounced
  apply is dispatched through `_ui_dispatch_later` (the Tk thread in the real app), so it may be legitimate, but the contract should be
  stated deliberately before D4 is relocated.

## 9. Strategy comparison

Scores: 3 = best, 1 = worst.

| Criterion | 1. Reincorporate wholesale | **2. Drain and retire** | 3. Keep as optional surface |
|---|:-:|:-:|:-:|
| Architecture / test truth | 1 (freezes B2, L2, L5 and the vacuous/duplicate cases; keeps a misleading "gui" vs "gui_v2" split) | **3** | 1 (no remaining test is "optional legacy") |
| Regression signal | 2 (all 33 run, including dead-code tests) | **3** (all unique signal runs, at the right owners) | 1 (unique signal stays outside the periodic census) |
| Hermeticity | 1 (silent-pass plan table, root-logger mutation stays in a mixed directory) | **3** (fixes P1/P2/D4 on the way) | 2 |
| Runtime cost | 3 (+~0.5 s) | 3 (+~0.4 s; 5 fewer cases) | 3 (0) |
| Maintainability | 1 | **3** (one GUI directory, one domain home) | 1 (permanent exception) |
| Implementation risk | 3 (one-line config change) | 2 (relocation/consolidation of 28 cases, test-only) | 3 |
| CI clarity | 2 | **3** (no exclusion special-case, census = truth) | 1 (the exception persists) |
| **Total** | 13 | **20** | 12 |

Strategy 2 is confirmed. Strategy 1 is the cheapest change but institutionalises the 5 obsolete/duplicate cases and the
taxonomy confusion; Strategy 3 has no justification because no remaining case is display-bound legacy coverage.

## 10. Recommended final state

`tests/gui/` is drained and deleted; its exclusion is removed from `pyproject.toml`, `run_collection_gate.py`
(`DEFAULT_COLLECTION_EXCLUDES`) and the truth-sync test; the default collection grows by the relocated cases (about 5,051 -> about
5,073, plus a few folded assertions) and the periodic census begins to cover these surfaces.

Destinations: GUI-widget cases (B4-B6, T1-T13, P1-P2, and the unique halves of B1/B3) -> `tests/gui_v2/`; `AppController` debounce (D2,
D4, D5, D6, plus a strengthened D1/D3) -> `tests/controller/`; S1's unique remainder -> `tests/controller/test_controller_job_lifecycle.py`; L3's
real consumer gap -> `tests/controller/test_builder_pipeline_contract_v2_6.py`; L5's genuine contract (optional) ->
`tests/controller/test_learning_controller_njr.py`. Retired: B2, L1, L2, L4, L5.

## 11. Sequenced implementation packages

* **A + B (one test-only package)**: relocate the 22 whole cases unchanged where possible (fixing P1/P2 skip semantics and the D4 clock
  seam), fold the unique remainders of the six consolidation cases into their owners, retire B2/L1/L2/L4/L5, leave `tests/gui/` empty. One failure
  class (test placement), no CI authority touched, so it takes the bounded `gui`/`core` routing. Preserve unique assertions exactly; do not
  modernise beyond the weaknesses listed above.
* **C (separate, small CI-authority package)**: remove `--ignore=tests/gui` (and the matching `DEFAULT_COLLECTION_EXCLUDES` entry), update
  `tests/system/test_ci_truth_sync_v2.py`, drop the `tests/gui/*` mapping and the `tests/gui` domain target from `validation_plan.py` (a stale
  target would trip the routing-rot guard once the directory is gone), and update the canonical testing documentation. This touches
  `tools/ci` and `pyproject.toml`, so the validation plan will (correctly) select a full census; keep it separate so that census
  evidence is not mixed with relocation changes. Run C only after `tests/gui/` is empty.
* **Optional separate production/product packages** (not part of the above): delete `PipelineRunControlsV2`, `_build_variant_overrides`
  and `learning_plan_table_v2.py` if the owner confirms they are dead; decide F3.

## 12. Risks

* Relocated tests newly enter the default census, so any latent order-sensitivity they carry becomes visible (the PR #44/#45 history
  shows this pattern); run the relocated files alone and in neighbouring selections before proposing C.
* `test_ui_debounce.py` constructs real `AppController` instances that attach root-logger handlers; relocation should keep them isolated
  (existing controller tests already do this) and must not worsen cross-test handler accumulation.
* Consolidating B1/B3/S1/D1/D3 into existing tests risks losing the unique assertion if done mechanically; the matrix names the exact remainder for each.
* Removing the exclusion changes census time slightly (+~0.4 s locally) and test counts; the PR-DEVEX-CI-110/B1 census figures are historical and must not be rewritten.

## 13. Evidence gaps

* The audit did not execute hosted CI, so Xvfb behavior of the two Tk files is inferred from the green PR #46 `affected` lane (950 tests, 0 failed), not remeasured.
* The JSONL log handler that `AppController.__init__` configures was not inspected for filesystem side effects beyond the clean working tree after the run.
* Replacement-coverage claims were established by reading the named tests and searching for the production symbols; a mutation-style check of each "duplicate" was not performed.
* Whether `learning_plan_table_v2.py`, `PipelineRunControlsV2` and `_build_variant_overrides` are intentionally retained is an owner question; the audit found no references.
* F3 (heartbeat from the debounced apply) is flagged, not resolved.

## 14. Scope statement

This package changed **no CI, test or production behavior**: no test was moved, edited, added or deleted; `pyproject.toml`,
`run_collection_gate.py`, `validation_plan.py`, workflows, markers and default collection are untouched, and no ignore rule was removed. The only
file added is this report. The unrelated local edits to `presets/global_negative.txt` and `presets/global_positive.txt` were not touched.
