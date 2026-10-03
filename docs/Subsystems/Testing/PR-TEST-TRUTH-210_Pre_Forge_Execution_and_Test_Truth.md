# PR-TEST-TRUTH-210 — Pre-Forge Execution & Test Truth

Status: bounded truth package, base `origin/main` `223c4e202ae5097edecb37cb1c204633f2c42818`
(PR-COMFY-RUNTIME-100 / PR #34 merged). **No new product capability was implemented.** One
production module changed behavior (`src/pipeline/run_plan.py`, fail-closed) and one reordered
(`src/pipeline/pipeline_runner.py::run_njr`, plan validation first); everything else is tests and
documentation. `PR-TEST-TRUTH-200` counts are historical evidence and are not rewritten here.

## Why

Before `PR-IMG-FORGE-100` adds another image backend, two truth gaps remained:

1. `build_run_plan_from_njr` could authorize execution the NJR never declared.
2. The active deterministic suite still carried permanent placeholder skips for removed
   architecture and for behavior that is either covered elsewhere or never shipped.

## Package A — fail-closed RunPlan

Defects at base:

- An enabled stage without a stage identity became `txt2img`
  (`getattr(stage_config, "stage_type", "") or "txt2img"`).
- If no enabled jobs were found, a `txt2img` `PlannedJob` was synthesized.
- `PipelineRunner.run_njr` ran `_begin_run_metrics` and best-effort WebUI `free_vram` **before**
  RunPlan construction, so a malformed plan could still touch the runtime.

Final semantics (`src/pipeline/run_plan.py`):

- Only explicitly enabled (`enabled` truthy; a missing attribute is not enabled), explicitly named
  stages are planned. A blank, whitespace or missing `stage_type` on an enabled stage raises
  `ValueError("RunPlan requires an explicit stage_type for every enabled stage")`.
- An empty or all-disabled chain raises `ValueError("RunPlan requires at least one enabled stage")`.
  No new exception type was introduced.
- Canonical stage ordering, `PlannedJob` fields and `RunPlan` shape are unchanged for valid input.
- `run_plan.py` is not a legacy-repair layer: historical replay hydrates into a valid NJR
  (`ReplayEngine._hydrate_njr` / `NormalizedJobRecord`) before the plan is built, and the NJR envelope
  already rejects zero stages, zero enabled stages, blank `stage_type` and workload-incompatible
  stages.
- `PipelineRunner.run_njr` builds and validates the plan first; an invalid plan produces zero
  metrics, `free_vram`, backend or runtime calls. No current invariant required the old order. No other
  `PipelineRunner` change was made.

Regressions:

| Requirement | Test |
|---|---|
| NJR still rejects zero enabled stages | `tests/pipeline/test_stage_chain_fix.py::test_njr_rejects_stage_chain_with_no_enabled_stage` (unchanged) |
| Blank/missing enabled stage identity cannot synthesize `txt2img` | `test_build_run_plan_rejects_enabled_stage_without_identity` (`""`, whitespace, `None`), `test_build_run_plan_rejects_enabled_stage_missing_stage_type_attribute` |
| Empty/all-disabled helper input cannot synthesize `txt2img` | `test_build_run_plan_never_synthesizes_txt2img` (empty, disabled, blank-disabled, no `enabled`) |
| Disabled blank stage is ignored, not rewritten | `test_build_run_plan_ignores_blank_identity_on_disabled_stage` |
| Malformed replay input fails before the runner | `tests/pipeline/test_replay_run_plan_v2.py::test_replay_engine_rejects_malformed_plan_before_runner` |
| Fresh/replay plan equivalence | `tests/pipeline/test_replay_vs_fresh_v2.py` (unchanged, green) |
| Invalid plan → zero runtime/`free_vram`/backend calls | `tests/pipeline/test_pipeline_runner.py::test_run_njr_rejects_invalid_plan_before_any_runtime_call` |

## Package B — Golden Path disposition

`tests/integration/test_golden_path_suite_v2_6.py` had exactly 16 static `Implementation pending/deferred`
skips. After this package it has **0** skips and no `test_golden_path_coverage_summary` meta-test (it
always claimed GP1-GP15 were skipped and was not evidence). No product feature was added to satisfy any
historical placeholder. Class: A = current behavior, coverage added; B = already covered by a current
authoritative test, placeholder retired; C = obsolete; D = genuinely deferred.

| # | Skipped assertion | Class | Disposition / current authority |
|---|---|---|---|
| 1 | GP1 Debug Hub explain | B | The live explanation surface is `JobExplanationPanelV2` fed by `AppController.get_job_explanation_payload`: `tests/gui_v2/test_job_explanation_panel_v2.py` (manifest and live-payload rendering) and `tests/gui_v2/test_debug_hub_panel_v2.py::test_debug_hub_explain_combo_uses_live_labels`. The placeholder's "full builder trace" wording named no shipped contract. |
| 2 | GP2 queue FIFO | B | `tests/queue/test_job_service_pipeline_integration_v2.py::test_jobs_execute_in_fifo_order`; `tests/queue/test_job_queue_basic.py::test_job_queue_respects_priority_and_fifo` |
| 3 | GP2 runner A-before-B | A | New `TestGP2QueueOnlyRun::test_gp2_runner_completes_job_a_before_starting_b` (real `JobQueue` + `SingleNodeJobRunner`, start/end event order) in the Golden Path suite |
| 4 | GP4 randomizer variants | A+B | Variant indices / distinct slot values: `test_prompt_pack_job_builder_matrix_provenance_is_immutable`, `..._random_matrix_mode_shuffles_combinations`, `tests/randomizer/test_randomizer_engine_v2.py`. Unique "prompts contain substituted values" assertion added: `test_prompt_pack_job_builder_substitutes_matrix_slot_per_variant` |
| 5 | GP4 Debug Hub substitution trace | A | `test_job_explanation_panel_shows_matrix_substitution_for_variant` (payload `matrix_slot_values`/`variant_index` rendered by the live panel) |
| 6 | GP5 randomizer × batch | A | New `TestGP5RandomizerBatchCrossProduct` (2 variants × 2 batch runs = ordered `(v,b)` 4 jobs); sweep × batch remains in `tests/pipeline/test_config_sweeps_v2.py::test_sweep_with_batch_expansion` |
| 7 | GP7 ADetailer stage | B | `tests/pipeline/test_prompt_pack_job_builder.py::test_prompt_pack_job_builder_orders_adetailer_before_upscale`; `tests/pipeline/test_stage_chain_fix.py::test_build_run_plan_normalizes_legacy_upscale_before_adetailer` |
| 8 | GP8 disabled-stage omission | B | `tests/pipeline/test_stage_chain_fix.py::test_build_run_plan_skips_disabled_stages` and the new fail-closed regressions |
| 9 | GP9 failure → failed | B | `tests/queue/test_job_service_pipeline_integration_v2.py::test_failed_job_marked_failed`; `tests/queue/test_queue_completion_to_history.py::test_webui_down_marks_job_failed`; `tests/queue/test_single_node_runner.py::test_worker_marks_job_failed_on_explicit_false_success` |
| 10 | GP9 failure does not block queue | B | `test_other_jobs_continue_after_failure`; `tests/queue/test_single_node_runner.py::test_worker_survives_exceptions_and_processes_following_jobs` |
| 11 | GP11 mixed queue | A | New `TestGP11MixedQueue::test_gp11_randomized_and_plain_jobs_do_not_contaminate` (compile-level isolation; queue ordering is #2) |
| 12 | GP12 history restore/replay | B | `tests/pipeline/test_replay_njr_compiler.py` (new identity, parent lineage, identical workload), `tests/pipeline/test_replay_vs_fresh_v2.py`, `tests/pipeline/test_replay_validation_v2.py` |
| 13 | GP13 config sweep | B | `tests/pipeline/test_config_sweeps_v2.py::TestJobBuilderV2ConfigSweeps` (`test_single_variant_sweep`, `test_multi_parameter_sweep`, metadata, non-mutation, determinism) |
| 14 | GP14 sweep × randomizer | B | `tests/pipeline/test_config_sweeps_v2.py::test_sweep_with_randomization_plan` (ordered M×N) |
| 15 | GP15 global-negative application | B+A | Layering: `test_global_negative_applied_in_resolver` / `_disabled` / `_ordering`; builder-level toggle added in `test_prompt_pack_job_builder_global_negative_is_toggleable_and_leaves_pack_untouched` |
| 16 | GP15 PromptPack immutability | A | Same new test: pack JSON bytes unchanged after compilation with the toggle on and off |

No item was class C or D: every placeholder maps to current, shipped behavior. The Golden Path
scenarios that remain active in the suite are GP1, GP2, GP3, GP5, GP6, GP10 and GP11; the other GPn labels
are covered by the authorities above and are not preserved as placeholders.

## Package C — PR-GUI-F1 skip retirement

PR-GUI-F1 moved queue controls to `QueuePanelV2`; `PipelineRunControlsV2` is no longer instantiated in the
layout (pinned by `tests/gui_v2/test_queue_run_controls_restructure_v2.py::TestNoRunControlsPanel`). No
removed widget was recreated, and no GUI/production code changed.

| Surface (all were `pytest.mark.skip` "PR-GUI-F1") | Disposition |
|---|---|
| `test_pipeline_queue_preview_v2.py` | Deleted. Queue status/list: `QueuePanelV2` (`test_queue_panel_status_label_updates`, new `test_queue_panel_update_from_app_state_projects_queue_truth`, `test_queue_panel_remove_updates_gui.py`); pause/resume/cancel callbacks: `test_pr_mvp_080_action_state_truth.py`, `tests/gui/test_gui_controller_bindings.py::test_queue_panel_invokes_controller_actions`; add/clear: `tests/gui/test_gui_controller_bindings.py` (preview panel) and `test_preview_panel_add_to_queue_v2.py`; the `start_run`/`stop` shim is obsolete. |
| `test_pipeline_run_controls_v2_run_button.py` | Deleted — obsolete (`run_button` removed; fresh work is queue-first). |
| `test_pipeline_run_controls_v2_run_now_button.py` | Deleted — obsolete widget; Run Now has no GUI button in the current layout (`sidebar_panel_v2.py`), the controller boundary is covered by `tests/controller/test_app_controller_run_now_bridge.py`. |
| `test_pipeline_run_controls_v2_add_to_queue_button.py` | Deleted — `PreviewPanelV2` owns Add to Queue (`test_preview_panel_add_to_queue_v2.py`, `test_preview_panel_summary_v2.py` enabled only after the canonical preview projection arrives). |
| `test_pipeline_run_controls_v2_pr203.py` | Deleted. Pause/Resume label, status text, auto-run reflection and controller invocation are covered on `QueuePanelV2` (`test_queue_panel_pause_button_toggles_text`, new `..._projects_queue_truth`, `test_pr_mvp_080_action_state_truth.py`). |
| `TestPipelineRunControlsRefreshStates` in `test_run_controls_states.py` | Removed with its now-unused fixtures; the `AppStateV2` run-state tests in the file are retained. Unique "tolerates missing app state" contract migrated into `..._projects_queue_truth` (`update_from_app_state(None)` / attribute-less state). |

`PipelineRunControlsV2` itself is unreferenced production code. Deleting it is dead-code cleanup outside
this package; `tests/gui/test_gui_controller_bindings.py::test_pipeline_run_controls_forward_requests` still
exercises it and is not a skip.

## Package D — other permanent skips

- `tests/gui_v2/test_pipeline_stage_checkbox_order_v2.py` — **retired**. It looked for `tk.Checkbutton`
  direct children of the panel and skipped when none existed, which silently hid a missing surface. The
  current authoritative representation is the ordered stage cards (`StageCardsPanel`, zone-map order).
  Stage order remains a contract and is tested concretely:
  `tests/gui_v2/test_pipeline_stage_cards_v2.py::test_pipeline_panel_stage_card_order` (existing) and
  `tests/gui_v2/test_zone_map_card_order_v2.py` (now pins
  `["txt2img", "img2img", "adetailer", "upscale"]`).
- `tests/gui_v2/test_pipeline_config_panel_lora_runtime.py` — the skip escape hatch is removed. The test
  converted a missing `PipelinePanelV2._lora_controls` surface into
  `pytest.skip("... not implemented in v2 panel surface yet")`, although the surface is implemented
  (`src/gui/pipeline_panel_v2.py` populates it from `get_lora_runtime_settings()`). It now asserts the
  current contract directly (`_lora_controls` exists, is populated, contains `LoRA-Alpha`) and keeps its
  strength/enabled/controller assertions. No production GUI code changed.
- `tests/gui/test_image_thumbnail.py::test_thumbnail_loads_valid_image` — the unconditional
  `skipif(True)` is removed. The test is deterministic without a Tk root (patched `ImageTk`, mocked widget
  hooks, `tmp_path`). `test_thumbnail_open_current_path_uses_default_viewer` patched Windows-only
  `os.startfile` and failed on every non-Windows host; it now pins all three platform branches through the
  module's own `os`/`subprocess` view.

## Skip census (unconditional and silent-absence skips in `tests/`)

| | Base `223c4e2` | This package |
|---|---:|---:|
| `Implementation pending/deferred` skips (Golden Path) | 16 | 0 |
| PR-GUI-F1 "removed/moved widget" markers | 6 files / classes | 0 |
| `skipif(True)` | 1 | 0 |
| Silent "not implemented" skips (stage-checkbox order, LoRA runtime controls) | 2 | 0 |
| Total static unconditional / silent-absence skips | 25 | 0 |

## Remaining legitimate skip classes (not changed)

Tk/Tcl genuinely unavailable; Windows-only ctypes structures
(`tests/tools/test_vid160c_commit_adjudication.py`); optional NumPy/OpenCV (`tests/helpers/optional_deps.py`,
`importorskip`); explicit qualification-source environment variables; explicit real-process/real-backend
opt-ins (shutdown-leak, real WebUI). Conditional/runtime `skip` call sites (`skipif`, `pytest.skip(`, `importorskip`): 136 → 116
(the reduction is the deleted/retired files and the removed silent-absence skips).

## Remaining test debt (recorded, not absorbed)

- `PipelineRunControlsV2` is unreferenced production code with one remaining forwarding test.

## Validation

Local, CPython 3.14.0rc2 under Xvfb, at the source head of this package:

- Focused set (RunPlan/replay/runner, prompt-pack builder, config sweeps, Golden Path, queue/runner/FIFO,
  randomizer, global prompt policy, QueuePanelV2/run-control, stage-card order, explanation panel,
  Debug Hub, thumbnail, GUI bindings): 220 selected, 218 passed. The 2 failures are the pre-existing
  `tests/gui/test_gui_controller_bindings.py::test_job_status_updates_*` tests, which fail identically on the
  base commit when that file runs in isolation (see debt below) and pass in the full suite.
- `tests/pipeline/test_stage_chain_fix.py` + `test_replay_run_plan_v2.py` + `test_replay_vs_fresh_v2.py` +
  `test_pipeline_runner.py`: 46 passed. `test_golden_path_suite_v2_6.py`: 12 passed, 0 skipped.
  `test_image_thumbnail.py`: 13 passed, 0 skipped.
- Full configured suite, once: `python -m pytest -q -rfE --tb=short --timeout=300` under Xvfb —
  **4190 passed, 50 skipped, 0 failed**.
- `python tools/ci/run_pr_gate.py` (run once, near final source): **PR gate OK** — repository completeness,
  controller ratchet (4 ratcheted, no controller touched, no ceiling change), Ruff, mypy smoke, isolated
  collection (4238 tests), required smoke (184 passed).
- After the final test-only repairs (seeded GP11 randomizer assertion; LoRA runtime-control skip removed): focused
  PR-TEST-TRUTH-210 set 114 passed, 0 skipped; `run_pr_gate.py` re-run: PR gate OK (same collection/smoke counts).
- `git diff --check`: clean.
- GitHub exact-head CI (`required`, `full-suite`, "Run broader configured suite (Xvfb)"): not run by this
  package — publication requires separate owner authorization. For this test-truth PR acceptance requires all
  three to be `success` on the exact head.

No physical action was taken: no A1111, Forge, Comfy, native SVD, GPU generation, model, PromptPack,
or owner SQLite/history/settings was launched or mutated.

## Additional debt found (recorded, not absorbed)

- `tests/gui/test_gui_controller_bindings.py::test_job_status_updates_use_ui_dispatcher` and
  `..._with_root_fallback_run` build `AppController.__new__(AppController)` without
  `_runtime_projection_coordinator`, so they fail when the file runs alone (identical on the base commit) yet
  pass inside the full suite through test-order state. They are stale fixtures for a refactored controller,
  not product defects.
