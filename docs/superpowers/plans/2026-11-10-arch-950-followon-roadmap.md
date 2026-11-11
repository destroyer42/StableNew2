# ARCH-950 Follow-on Implementation Plan (ARCH-951 through ARCH-956)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Remove dormant code and move read-only or independent responsibilities out of the coordination hotspots, one reviewable package at a time, without changing product behavior.

**Architecture:** Delete what nothing references first (ARCH-951), close the one data-safety gap (ARCH-954), then extract only clusters that can take explicit dependencies instead of the owning controller (ARCH-952, 953, 955), and finish with a typed seam plus ratchets (ARCH-956). The canonical path is never touched.

**Tech Stack:** Python 3.14, pytest, ruff, mypy, repo ratchets under `tools/ci/`. Interpreter with pytest: `C:/Users/rob/projects/StableNew-main/.venv/Scripts/python.exe`.

**Spec:** `docs/assessments/2026-11-10_arch_design_950_coordination_hotspot_decomposition.md` (sections 7, 8, 10), `docs/assessments/evidence/arch_design_950/STRUCTURAL_INVENTORY.md`, `docs/work_packages/ARCH-951_unreferenced_legacy_path_removal.md`.

## Global Constraints

- Canonical path is unchanged: `Intent -> Compiler -> NJR -> JobService -> Queue/Repository -> PipelineRunner.run_njr -> Handler -> Artifacts/History`. No package adds a submission path, run callable, store or status.
- Extraction rule: explicit dependencies in, no owner instance passed, no state kept in two places, tests move with the code they assert on.
- A ratchet ceiling in `tools/ci/controller_surface_baseline.json` may only go down; lock improvements with each tool's `--update`.
- One short-lived branch and one work package at a time, from current `origin/main`, in a dedicated worktree. Packages run sequentially (954 and 951 edit the same file).
- Gate: focused tests while editing, then `python tools/ci/run_pr_gate.py` (`--full` for ARCH-951); hosted `required`, `full-suite`, `windows` green.
- One batched repair/reverification cycle per package; a remaining failure caused by the package means revert that piece and report.
- Stop on: a service that must receive its owning controller, any persisted-format change, a new authority, a rising ceiling, or an authorized product package claiming the same lines.
- Merge, push to `main` and publication need owner approval (`AGENTS.md` section 5).
- Commit trailer: `Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>`.

## Review Focus

- ARCH-951: a name used only by an operator script or plugin outside tracked `.py` files. Expected: the symbol is kept and reported, never deleted on static evidence alone.
- ARCH-954: an append arrives while undo is rewriting the file. Expected: the appended record survives and exactly one record is removed.
- ARCH-954: the records file holds blank or malformed lines. Expected: undo neither crashes nor drops malformed lines it did not select.
- ARCH-953: shutdown restores the threading exception hook captured at a different moment than the others. Expected: the restored hooks are identical to today's.
- ARCH-952: history entries with missing fields, mixed-type timestamps or no media. Expected: same dictionaries key for key, same sort order, `None` where `None` is returned today.

## File Structure

| Package | Create | Modify | Delete |
|---|---|---|---|
| 951 | none | five coordination files, `IMAGE_PIPELINE.md`, `controller_surface_baseline.json`, ratchet baselines | tier B only: `src/pipeline/payload_builder.py`, `tests/api/test_sdxl_payloads.py` |
| 954 | writer-level test | `src/learning/learning_record.py`, `src/gui/controllers/learning_controller.py` | none |
| 952 | `src/video/history_media_projection.py` | `src/controller/app_controller.py`, seven test files | none |
| 953 | `src/controller/app_controller_services/diagnostics_read_model.py` | `app_controller.py`, `diagnostics_coordinator.py` | none |
| 955 | `src/learning/learning_controller_services/curation_coordinator.py` | `learning_controller.py`, views that call curation | none |
| 956 | `src/image_backends/stage_executor.py` | `webui_family_backend.py`, `controller_surface_baseline.json` | none |

---

### Task 1: ARCH-951 Remove unreferenced legacy paths

**Status:** tier A implemented and rebased on `origin/main` `2ebf96fe` (branch `arch/arch-951-unreferenced-legacy-removal`); ratchets lowered; pull request open for hosted CI. Local full gate: not clean (4 journey failures reproduced on pristine `origin/main`; 2 timing tests passed on rerun). Tier B is ARCH-951B (below).

**Files:**
- Modify: `src/pipeline/executor.py`, `src/pipeline/pipeline_runner.py`, `src/controller/app_controller.py`, `src/controller/pipeline_controller.py`, `src/gui/controllers/learning_controller.py`, `docs/Subsystems/Image/IMAGE_PIPELINE.md`
- Modify via `--update`: `tools/ci/controller_surface_baseline.json`, `mypy_baseline.json`, `ruff_ratchet_baseline.json`, `architecture_baseline.json`
- Tier B only: delete `src/pipeline/payload_builder.py`, `tests/api/test_sdxl_payloads.py`; regenerate `docs/CODE_MAP.md`

**Interfaces:**
- Produces: smaller files and lower ceilings; no new symbols.
- Candidates for subsequent removal, NOT assumed dead: `PipelineController.start_pipeline_v2`, `_normalize_run_mode`, `_get_pipeline_state`. They became test-only because their only production caller (`AppController.run_pipeline`, whose docstring named `start_pipeline_v2`) was deleted. Checked for indirect reachability: no string literal, f-string or composed name, `getattr` site, callback registration or non-Python file reaches any of them (the `getattr` sites in `presentation_actions.py`, `job_history_panel_v2.py`, `queue_panel_v2.py` and `history_sequence_contract.py` use controller-level literal names or `f"{action}_sequence"`; `main_window_v2.py:1268` resolves `start_pipeline` or `start`). `_normalize_run_mode` and `_get_pipeline_state` are called only from inside `start_pipeline_v2`. Three test files drive `start_pipeline_v2` (`test_core_run_path_v2.py`, `test_pipeline_controller_jobbuilder_integration_v2.py`, `test_pipeline_controller_run_modes_v2.py`), so removal means migrating those tests: a tier C decision (OD-3). The evidence is static, and one runtime doc (`PR-RUNTIME-WEBUI-WATCHDOG-120...md` line 41) still mentions the method.

- [x] **Step 1: Tier A deletion** of 58 methods plus `_build_stage_payload`, orphaned imports, four write-only attributes (`_last_img2img_result`, `_last_upscale_result`, `_webui_api`, `_learning_runner`), and the stale `executor.py` comment. Reachability re-run reports only `_get_batch_runs` unreferenced.
- [x] **Step 2: Run focused tests**: `python -m pytest tests/pipeline tests/image_backends tests/controller tests/learning tests/learning_v2 tests/api -q`. Expected: all pass, same collection count.
- [ ] **Step 3: Tier B is DEFERRED to a separate package (ARCH-951B) under a revised acceptance contract.** OD-1 was answered "include", but `tests/integration/test_prompt_optimizer_payload_integration.py` (3 tests) also imports `build_sdxl_payload`; the work package listed only `tests/api/test_sdxl_payloads.py`. A test is not deleted merely because its implementation dependency is obsolete. Revised contract for ARCH-951B:
  1. Per-test mapping table: each of the 21 tests (18 in `tests/api/test_sdxl_payloads.py`, 3 in the integration file) is mapped to a test that asserts the same behavior through the executor path or a shared component, or is explicitly waived by the owner as builder-only behavior.
  2. Established now, for the 3 integration tests (all covered; nothing lost by deleting them once the builder goes): optimizer enabled -> `tests/pipeline/test_executor_prompt_optimizer.py::test_txt2img_stage_uses_prompt_optimizer_and_records_manifest` (identical prompt and negative strings through `run_txt2img_stage`); optimizer disabled -> `tests/image_backends/test_webui_family_prompt_intent.py::test_explicitly_disabled_optimizer_preserves_order_duplicates_and_unicode` (stronger: all backends and stages, byte-identical); AUTO policy values -> `test_executor_prompt_optimizer.py::test_txt2img_stage_auto_fills_missing_or_auto_policy_keys` and `tests/unit/test_stage_policy_engine.py::test_stage_policy_engine_applies_missing_txt2img_values` (DPM++ 2M, Karras, 28, 6.5). Both builder and executor delegate to `PromptOptimizerOrchestrator` and `StagePolicyEngine`, so the shared logic stays covered.
  3. NOT yet established: the 18 `tests/api/test_sdxl_payloads.py` tests (refiner/hires/upscaler field encoding, `last_image_meta` chaining, alias normalization, empty config, extra-key preservation, string and enum stage types, `StageExecution` input). They assert the builder's own wire encoding, and the executor builds its payloads differently. The mapping table must show where each behavior is asserted on the live path, or record an owner waiver. Any behavior with neither gets a new executor-path test before deletion.
  4. Deletion happens only after 1-3 are complete: delete the module and both test files together, run `python tools/generate_code_map.py`, then `python -m pytest tests/tools/test_code_map.py -q`; collection count drops by exactly 21.
- [x] **Step 4: Lower ceilings**: `python tools/ci/<each ratchet tool> --update` for controller surface, mypy, ruff, architecture. Expected: `app_controller.py` and `pipeline_controller.py` ceilings decrease, nothing increases.
- [ ] **Step 5: Gate**: `python tools/ci/run_pr_gate.py --full`. Expected: pass.
- [ ] **Step 6: Commit and open PR**: `refactor(arch): ARCH-951 remove unreferenced legacy execution and submission paths`.

---

### Task 2: ARCH-954 One writer for the learning-record store (gate)

**Files:**
- Modify: `src/learning/learning_record.py` (`LearningRecordWriter`), `src/gui/controllers/learning_controller.py` (`undo_review_feedback`)
- Test: `tests/learning/test_learning_record_writer_undo.py` (new); `tests/controller/test_learning_controller_review_feedback_undo.py` stays unchanged and green

**Interfaces:**
- Produces: `LearningRecordWriter.remove_latest_review_feedback(self, *, run_id: str | None = None, image_path: str | None = None) -> bool`. Takes `evidence_file_lock(self.records_path)` for the whole read-select-replace and writes with `atomic_write_text` (`src/utils/atomic_io.py`). Matching rule is today's: latest record with `metadata.source == "review_tab"`, optional `run_id` and `metadata.image_path` filters. Returns `False` on no match, missing or empty file, or `OSError`.
- Consumes: nothing from Task 1.

- [ ] **Step 1: Write failing tests** in `test_learning_record_writer_undo.py`: `test_removes_only_latest_matching_record`, `test_no_match_returns_false_and_leaves_file_bytes_identical`, `test_empty_or_missing_file_returns_false`, `test_malformed_and_blank_lines_do_not_crash_and_unselected_malformed_lines_are_kept`, `test_append_during_undo_is_not_lost` (a thread appends 50 records while undo runs; afterwards 50 appended records are present and exactly one was removed), `test_failed_replace_leaves_original_intact` (monkeypatch `src.learning.learning_record.atomic_write_text` to raise `OSError`; result `False`, file bytes unchanged).
- [ ] **Step 2: Run** `python -m pytest tests/learning/test_learning_record_writer_undo.py -q`. Expected: FAIL, attribute missing.
- [ ] **Step 3: Implement** `remove_latest_review_feedback` in `learning_record.py`; keep today's line handling (non-blank lines retained, trailing newline). Import `atomic_write_text` at module level so the monkeypatch target exists.
- [ ] **Step 4: Delegate** `LearningController.undo_review_feedback`: return `False` without a writer; call the writer; on `True` call `self.refresh_recommendations()` and return `True`. Remove the `write_text` call.
- [ ] **Step 5: Run** the new tests and `tests/controller/test_learning_controller_review_feedback_undo.py`, `tests/learning`. Expected: PASS.
- [ ] **Step 6: Verify the metric** `git grep -n "write_text" -- src/gui/controllers` returns nothing. Also `git grep -n "records_path" -- src` to confirm no other unlocked writer; if one exists, stop (spec stop condition).
- [ ] **Step 7: Gate and commit**: `python tools/ci/run_pr_gate.py`; security-review trigger applies (filesystem write path). Commit `fix(learning): route review-feedback undo through LearningRecordWriter (ARCH-954)`.

---

### Task 3: ARCH-952 History media projection out of `AppController`

**Re-scope first:** ARCH-930 (PR #283, merged) already extracted the SVD history summary into `src/video/svd_history.py` and removed `_extract_history_result_metadata`, `_history_sort_key`, `_extract_video_artifact_summary` and `_build_svd_history_record` from `AppController`. Re-run the cluster inventory on current `origin/main`; keep only what is still in the controller and reuse that module. The file list and interfaces below predate that change.

**Files:**
- Create: `src/video/history_media_projection.py`
- Modify: `src/controller/app_controller.py` (about lines 6236-6560 in the current checkout: `get_recent_svd_history`, `_iter_history_image_candidates`, `_get_history_image_path`, `_get_history_video_bundle`, `_extract_history_result_metadata`, `_history_sort_key`, `_build_svd_history_record` and the other cluster members), `src/gui/views/svd_tab_frame_v2.py` only if it names a moved private method
- Test: `tests/video/test_history_media_projection.py` (new characterization test); the seven test files naming the moved methods

**Interfaces:**
- Produces (pure functions, no controller, no `app_state`): `iter_history_image_candidates(entry: Any) -> list[str]`, `history_image_path(entry: Any) -> str | None`, `history_video_bundle(entry: Any) -> dict[str, Any] | None`, `extract_history_result_metadata(entry: Any) -> dict[str, Any]`, `history_sort_key(value: Any) -> str`, `build_svd_history_record(entry: Any) -> dict[str, Any] | None`, `recent_svd_history(entries: Sequence[Any], limit: int) -> list[dict[str, Any]]`.
- Consumes: `app_state.history_items` stays in the controller, passed in as `entries`.

- [ ] **Step 1: Check reuse first**: read `src/video/recent_video_outputs.py` and `sequence_history.py`; if `recent_output_from_entry` already covers part of `build_svd_history_record`, reuse it. A second projection of the same artifact shape is a stop condition.
- [ ] **Step 2: Write the characterization test against the current controller methods** using recorded history entries (image-only, video bundle, missing fields, mixed-type timestamps, no media). Run it: PASS against `AppController`.
- [ ] **Step 3: Create the module**, copy the logic, point the test at the new functions. Run it: PASS for both old and new, key for key.
- [ ] **Step 4: Replace** the controller bodies with calls to the module (`get_recent_svd_history` and `send_history_job_*` stay as callers); delete the moved private methods and update the seven test files to assert on the functions.
- [ ] **Step 5: Lower** the `app_controller.py` ceiling (about 300 lines), run `python tools/ci/run_pr_gate.py`, commit `refactor(controller): project history media outside AppController (ARCH-952)`.

---

### Task 4: ARCH-953 Diagnostics read model with one hook owner

**Files:**
- Create: `src/controller/app_controller_services/diagnostics_read_model.py`
- Modify: `src/controller/app_controller.py` (diagnostics cluster, about 3268-4100 at the locked SHA, and the hook fields at 545-547, 2553, 3434-3454), `src/controller/app_controller_services/diagnostics_coordinator.py`
- Test: `tests/controller/test_diagnostics_hook_ownership.py` (new); the 13 existing diagnostics test files keep their assertions

**Interfaces:**
- Produces: `@dataclass(frozen=True) class DiagnosticsSources` with fields `job_service`, `pipeline_controller`, `process_manager`, `connection_controller`, `app_state`, `log_handler`; `class DiagnosticsReadModel` constructed with `DiagnosticsSources`, exposing the snapshot builders behind `get_diagnostics_snapshot`, `explain_job`, `get_job_explanation_payload`, returning the same dictionaries. `DiagnosticsCoordinator` is the only holder of the three original exception hooks.
- Consumes: none from earlier tasks.

- [ ] **Step 1: Write a failing-then-passing pin test** `test_hook_install_and_restore_sequence_matches_today` recording which `sys.excepthook`, `threading.excepthook`, `sys.unraisablehook` values are active after install and after shutdown, run against current code first (must PASS before any change).
- [ ] **Step 2: Move** the read-only builders into `DiagnosticsReadModel`; the heavy-snapshot cache moves with it and is the only state it mutates.
- [ ] **Step 3: Remove** the controller's copies of the hook originals; the shutdown path asks the coordinator to restore.
- [ ] **Step 4: Run** the pin test and the 13 diagnostics test files; confirm snapshot keys consumed by the GUI panels are unchanged.
- [ ] **Step 5: Lower** the ceiling (about 750 lines), gate, commit `refactor(controller): diagnostics read model and single hook owner (ARCH-953)`.

---

### Task 5: ARCH-955 Curation and discovered-inbox coordinator

**Schedule only when no Learning feature PR is in flight; re-plan if UX-850 Learning redesign is authorized first.**

**Files:**
- Create: `src/learning/learning_controller_services/curation_coordinator.py`
- Modify: `src/gui/controllers/learning_controller.py` (staged curation and inbox, about 3118-4123 at the locked SHA), the views that call these methods
- Test: the eleven test modules naming staged curation; new `tests/learning_v2/test_curation_coordinator_admission.py`

**Interfaces:**
- Produces: `class CurationCoordinator` constructed with keyword-only `review_store: DiscoveredReviewStore`, `workflow_builder: CurationWorkflowBuilder`, `review_adapter: ReviewWorkflowAdapter`, `record_writer: LearningRecordWriter`, `job_service_getter: Callable[[], JobService | None]`, `baseline_config_getter: Callable[[], dict[str, Any]]`, `on_refresh: Callable[[], None]`. `LearningController.curation` returns the one instance; views call it.
- Consumes: existing store and builder instances only; the coordinator never constructs a store.

- [ ] **Step 1: Write failing test** `test_advancement_admits_through_job_service_submit_njrs` using a stub job service; run it against the controller path first to capture today's behavior.
- [ ] **Step 2: Verify** each public curation method has one caller in `src/gui/views/`; list them in the commit message.
- [ ] **Step 3: Move** the 44 methods; update callers; the controller keeps no curation methods.
- [ ] **Step 4: Assert** no second store: `test_coordinator_reuses_controller_stores` (identity of the injected stores).
- [ ] **Step 5: Run** the eleven modules, `tests/learning`, `tests/learning_v2`; gate; commit `refactor(learning): curation and inbox coordinator (ARCH-955)`.

---

### Task 6: ARCH-956 Typed stage-executor seam and hotspot ratchets

**Files:**
- Create: `src/image_backends/stage_executor.py`
- Modify: `src/image_backends/webui_family_backend.py` (`execute`, line 238 at the locked SHA), `tools/ci/controller_surface_baseline.json` (ratchet half, needs OD-2)
- Test: `tests/image_backends/test_stage_executor_protocol.py` (new)

**Interfaces:**
- Produces: `class StageExecutor(Protocol)` declaring exactly `run_txt2img_stage`, `run_img2img_stage`, `run_adetailer_stage`, `run_upscale_stage`, with signatures copied from `src/pipeline/executor.py` at implementation time; `WebUIFamilyImageBackend.execute(self, pipeline: StageExecutor, ...)`.
- Consumes: Task 1 (those four methods are the only stage methods left).

- [ ] **Step 1: Write failing test** `test_pipeline_satisfies_stage_executor_protocol` (a structural check that `Pipeline` exposes the four names with matching parameters via `inspect.signature`) and `test_backend_execute_annotation_is_not_any`.
- [ ] **Step 2: Implement** the protocol; change the annotation; run `mypy` ratchet and `tests/image_backends`.
- [ ] **Step 3 (needs OD-2): add** `executor.py`, `pipeline_runner.py`, `learning_controller.py` to the size ratchet at their then-current size (hotspots 4 to 7); skip this step until the owner approves.
- [ ] **Step 4: Gate and commit** `refactor(image): type the stage-executor seam (ARCH-956)`.

---

## Self-review

- Spec coverage: every package in assessment section 7 maps to a task; OD-1 and OD-2 are gates inside Tasks 1 and 6; OD-3 to OD-6 produce no task by design.
- Interface consistency: Task 6 depends on Task 1 only; Tasks 3 to 5 share no files; Task 2 and Task 1 share `learning_controller.py`, which is why they run sequentially.
- Proportion: Tasks 3 to 5 deliberately stop at signatures and test names; line numbers there are from the locked SHA and must be re-derived with the reachability and cluster scripts before editing.
