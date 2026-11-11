# ARCH-951 — Remove unreferenced legacy execution and submission paths

Status: **Tier A IMPLEMENTED (pull request open, merge pending); tier B DEFERRED to ARCH-951B under a revised
acceptance contract (below).** Produced by the design package ARCH-DESIGN-950
([assessment](../assessments/2026-11-10_arch_design_950_coordination_hotspot_decomposition.md),
[symbol inventory](../assessments/evidence/arch_design_950/STRUCTURAL_INVENTORY.md)). Tier A authorized by the owner on
2026-11-10; the owner answered OD-1 "include tier B", which the evidence below shows cannot be done as specified.
Date: 2026-11-10.

This file is the copy-paste prompt for a fresh implementation session. It follows
`docs/CODEX_WORK_PACKAGE_TEMPLATE.md`. Do not repeat the architecture discovery; do verify the start state.

## Objective

- Outcome: `src/pipeline/executor.py`, `src/pipeline/pipeline_runner.py`, `src/controller/app_controller.py`,
  `src/controller/pipeline_controller.py` and `src/gui/controllers/learning_controller.py` contain no method that is
  unreferenced by `src/`, `tests/` and `tools/`; `src/pipeline/` contains no module reachable only through such a method.
  Product behavior is unchanged.
- In scope:
  - Tier A: delete the 58 methods listed in inventory section 1 (all 59 except `PipelineController._get_batch_runs`).
  - Tier B (only if OD-1 includes it): delete `src/pipeline/payload_builder.py` together with
    `tests/api/test_sdxl_payloads.py`, and the import at `pipeline_runner.py:35`.
  - Remove imports, module-level helpers, constants and instance attributes that only the deleted code used. Find them
    by re-running the reachability script and `ruff check`; delete an attribute only when no remaining code reads it.
  - Replace the stale comment at `executor.py:4815` and the two "Dead code" bullets in
    `docs/Subsystems/Image/IMAGE_PIPELINE.md` (lines 375-376) with the current truth.
  - Lower the `app_controller.py` and `pipeline_controller.py` ceilings in `tools/ci/controller_surface_baseline.json`;
    lock mypy, ruff and architecture ratchet improvements with each tool's `--update`.
- Explicit exclusions:
  - `PipelineController._get_batch_runs` (`STATUS.md` open owner decision 4).
  - Tier C, the 40 methods referenced only by tests (inventory section 3).
  - Any change to the body, signature or behavior of a referenced symbol. No renames, no reformatting of untouched code,
    no extraction, no new module.
  - `AppController._build_job_service`, `_single_node_runner_factory`, `_execute_job` (assessment risk R5).
  - The 64 unreachable modules recorded in `STATUS.md` Known debt, other than `payload_builder.py`.
  - Any test edit other than tier B's file and the removal of an import that only served deleted code.

## Execution class and model recommendation

- Execution class: Standard
- Execution location: Local (the gate and the reachability script need a checkout; no GPU or runtime)
- Model recommendation: Claude Code Sonnet 5.5 High; Codex GPT-6.1 Sol High. A known-architecture deletion with a
  mechanical proof per symbol; the risk is diligence, not ambiguity.
- Preferred host and why: none; stay in whichever fresh session starts the package.
- Expected usage: about 10M cache-read, 50k output.
- Separable hard part worth delegating to a stronger model: none.

## Exact start state and authorities

- Task-start timestamp with timezone, host and session IDs: record before discovery.
- Repository and branch: `destroyer42/StableNew2`; new short-lived branch from current `origin/main` in a dedicated
  worktree.
- Required start SHA: current `origin/main`. The inventory was measured at
  `fdd900a93dd966a5f26c6453aac495447c69bd81`. If any of the five files or `payload_builder.py` changed since then
  (`git diff --stat fdd900a9 origin/main -- <files>`), re-run the reachability script and use its output, not the
  recorded line numbers.
- Remote feature SHA / `origin/main`: record both.
- Worktree state: clean; preserve unrelated user changes (for example `presets/settings.json` in other checkouts).
- Canonical docs consulted: `AGENTS.md`, `STATUS.md`, the assessment and inventory above, `docs/CODEX_MAP.md` rows
  "Running a job" and "GUI to queue submission", `docs/Subsystems/Image/IMAGE_PIPELINE.md` lines 370-380.

## Surface assessment

- Source/test/tool/config files allowed to change: the five source files; `src/pipeline/payload_builder.py` and
  `tests/api/test_sdxl_payloads.py` (tier B); `tools/ci/controller_surface_baseline.json`,
  `tools/ci/mypy_baseline.json`, `tools/ci/ruff_ratchet_baseline.json`, `tools/ci/architecture_baseline.json` (only
  through `--update`); `docs/Subsystems/Image/IMAGE_PIPELINE.md`; `docs/CODE_MAP.md`, regenerated with
  `python tools/generate_code_map.py` (tier B removes a listed module and `tests/tools/test_code_map.py` fails when the
  map is stale).
- Controller or coordinator surface touched: Yes
- Controller Surface Assessment: deletions only. `AppController` loses 23 unreferenced methods (about 235 lines) and
  `PipelineController` 12 (about 76 lines); no responsibility moves and no public method with a caller changes. Both
  ceilings go down.
- Architecture authority or invariant changed: No. The canonical path
  `Intent -> Compiler -> NJR -> JobService -> Queue/Repository -> PipelineRunner.run_njr -> Handler -> Artifacts/History`
  is untouched; the package removes dormant code beside it.

## Acceptance and evidence reuse

- Required behavior/evidence:
  1. Before deleting each symbol, `git grep -l -w "<name>" -- '*.py'` returns only the defining file (tier B: only
     `payload_builder.py`, `pipeline_runner.py` and `test_sdxl_payloads.py`). A symbol that fails this check is kept and
     reported.
  2. After the deletions, the reachability script reports no unreferenced method in the five classes except
     `_get_batch_runs`, and the test-only list is unchanged apart from methods that were only reachable through deleted
     code (report any such method; do not delete it).
  3. `git diff` for the five source files contains deletions only, plus removed imports and the one corrected comment.
  4. `python tools/ci/run_pr_gate.py --full` passes locally; hosted `required`, `full-suite` and `windows` are green.
  5. Collection count changes only by the tests in `tests/api/test_sdxl_payloads.py` (tier B) or not at all (tier A
     only).
- Completion evidence expected: evidence mode deterministic test; evidence identity the final SHA with the gate and CI
  run IDs; qualification claim N/A; not demonstrated: physical generation on any backend (not required for a deletion
  of unreferenced code).
- Existing qualification or test harness to reuse: the PR gate and the sharded census. No new tool.
- Existing exact-SHA evidence reused: none (source changes).
- New manual or runtime evidence: none.
- Known blockers or non-blocking debt: tier C remains; risk R5 remains.
- Existing non-blocking CI/review debt to ignore unless caused by this package: recorded ratchet baselines.
- Review/Repair Budget: one batched repair/reverification cycle for confirmed current in-scope findings.
- Physical/External Evidence Freeze: not applicable.
- Stop condition after the allowed repair/reverification cycle: any remaining failure caused by a deletion means that
  symbol was live; restore it, report it, and do not attempt a second repair cycle.

Focused regression tests to run while editing (existing; none are modified):

- `tests/pipeline` (runner, stage sequencing, handler and executor stage tests)
- `tests/image_backends`
- `tests/controller` (app controller, pipeline controller, job service)
- `tests/learning`, `tests/learning_v2`, and the Learning controller tests under `tests/controller` and `tests/gui_v2`
- `tests/api` (tier B removes one file here)

## Token-Efficient Validation Plan

1. Run the reachability script once per class and save the output; delete file by file, running that file's focused
   tests after each.
2. Run `ruff check` on the changed files to find orphaned imports; do not reformat.
3. Run the ratchet tools with `--update`, then `python tools/ci/run_pr_gate.py --full` once.
4. Verify the final diff (`git diff --stat`, `git diff --check`), remote state and working tree; open the PR and wait
   for required CI without polling.

## Stop conditions

- Higher execution class or architecture decision discovered: a listed symbol turns out to be referenced (dynamic
  dispatch, operator script, plugin), or a deletion requires changing a referenced symbol.
- A materially new blocking failure class remains or appears after the one allowed batched repair and independent
  reverification.
- Scope begins expanding into the next roadmap phase: any extraction, any tier C deletion, any edit to
  `_get_batch_runs`, the queue-stack wiring, or a test other than the tier B file.
- Another authorized package has changed the same regions and the reachability output differs materially from the
  inventory.

## Documentation impact

- `STATUS.md`: correct the stale `AppController` line count in Known debt in place only if the owner wants it in this
  package; otherwise none.
- Roadmap: none.
- Architecture: none.
- `CODEX_MAP.md`: none (no listed path is removed). `docs/CODE_MAP.md` is regenerated for tier B.
- Coding/testing: none.
- `AGENTS.md`: none.
- `docs/Subsystems/Image/IMAGE_PIPELINE.md`: replace the dead-code bullets at lines 375-376.

## Tier B revised acceptance contract (ARCH-951B)

The owner's OD-1 answer assumed `tests/api/test_sdxl_payloads.py` was the only test importer of `build_sdxl_payload`.
It is not: `tests/integration/test_prompt_optimizer_payload_integration.py` (3 tests) also imports it, and this package's
stop conditions forbid a second test edit. A test is not deleted merely because its implementation dependency is
obsolete; behavioral coverage must be shown first.

1. Per-test mapping table. Each of the 21 tests (18 in `tests/api/test_sdxl_payloads.py`, 3 in the integration file) maps
   to a test asserting the same behavior through the executor path or a shared component, or is explicitly waived by the
   owner as builder-only behavior.
2. Established now, for the 3 integration tests: covered through the executor path, so nothing is lost by deleting them
   once the builder goes.
   - Optimizer enabled: `tests/pipeline/test_executor_prompt_optimizer.py::test_txt2img_stage_uses_prompt_optimizer_and_records_manifest`
     asserts the same prompt and negative strings through `run_txt2img_stage`.
   - Optimizer disabled: `tests/image_backends/test_webui_family_prompt_intent.py::test_explicitly_disabled_optimizer_preserves_order_duplicates_and_unicode`
     (stronger: every backend and stage, byte-identical).
   - AUTO policy values (DPM++ 2M, Karras, 28, 6.5): `test_executor_prompt_optimizer.py::test_txt2img_stage_auto_fills_missing_or_auto_policy_keys`
     and `tests/unit/test_stage_policy_engine.py::test_stage_policy_engine_applies_missing_txt2img_values`.
   - The builder and the executor both delegate to `PromptOptimizerOrchestrator` and `StagePolicyEngine`.
3. NOT established: the 18 `tests/api/test_sdxl_payloads.py` tests (refiner, hires and upscaler field encoding,
   `last_image_meta` chaining, alias normalization, empty config, extra-key preservation, string and enum stage types,
   `StageExecution` input). They assert the builder's own wire encoding. The mapping table must show where each behavior
   is asserted on the live path or record an owner waiver; a behavior with neither gets a new executor-path test first.
4. Only then delete `src/pipeline/payload_builder.py` and both test files together, regenerate `docs/CODE_MAP.md`, and
   expect the collection count to drop by exactly 21.

## Completion report

- Parent/final SHA: parent `origin/main` `2ebf96fe` (PR #283, ARCH-930, merged); the branch was first built on
  `8677ff11` and rebased once. Final SHA: the pull request head, which contains this report.
- Files changed: `executor.py`, `pipeline_runner.py`, `app_controller.py`, `pipeline_controller.py`,
  `learning_controller.py` (deletions only, plus orphaned imports and one comment line);
  `docs/Subsystems/Image/IMAGE_PIPELINE.md`; `tools/ci/controller_surface_baseline.json`, `mypy_baseline.json`,
  `ruff_ratchet_baseline.json` (all decreases); this work package; the follow-on plan
  `docs/superpowers/plans/2026-11-10-arch-950-followon-roadmap.md`. `architecture_baseline.json` unchanged.
- Validation and CI (read the distinctions; the local full gate is NOT clean):
  - Focused set (`tests/pipeline`, `image_backends`, `controller`, `learning`, `learning_v2`, `api`): 5,619 passed at the
    pre-rebase SHA `48ba453c`. Re-run on the rebased head: see the pull request.
  - `python tools/ci/run_pr_gate.py --full` at `48ba453c` (pre-rebase, so not exact-SHA evidence for the final head):
    lint, collection (16,226) and smoke (397 passed) passed; the sharded census reported 16,197 passed, 6 failed,
    23 skipped, so the gate exited 1.
  - Four of the six failures are `tests/tools/test_golden_path_journeys.py` journeys (`video` simulated and physical,
    `storyboard`, `motion-assets`), all failing with "isolation: read operator-owned file ...config/managed_comfy_runtime.json".
    **All four were reproduced on pristine `origin/main` `2ebf96fe`** with the same message, so they are not caused by
    this package.
  - The other two (`tests/tools/test_gui_seam_743.py::test_exception_isolation_and_pending_id_release`,
    `tests/utils/test_process_containment_failsafe.py::test_output_of_a_pump_abandoned_by_stop_never_leaks_into_the_restarted_process`)
    passed when re-run alone on this branch and on pristine `origin/main`. That is consistent with timing flakiness
    under the two-worker census, but it is an inference: they were not reproduced as failing anywhere else.
  - Hosted `required`, `full-suite`, `windows`: pending at the time of writing; they are the exact-SHA evidence.
- Main unchanged: yes (nothing was pushed to `main`).
- Working tree clean: yes at commit time.
- Ready for next phase: Yes for ARCH-954, which is independent of this package; this package awaits hosted CI and
  review; tier B (ARCH-951B) is not ready.
- Lines removed per file, and the new ceilings: `executor.py` -925/+2 (6,590 to 5,667), `pipeline_runner.py` -243
  (2,210 to 1,967), `app_controller.py` -262 (ceiling 6,592 to 6,330, measured after ARCH-930),
  `learning_controller.py` -110 (4,123 to 4,013), `pipeline_controller.py` -89 (ceiling 1,697 to 1,608).
  1,629 source lines deleted in total.
- Symbols kept despite being listed, with the reference found: none of the 58 tier A methods plus
  `_build_stage_payload` was kept. `_build_stage_payload` was first refused by the deletion script because the stale
  `executor.py` comment named it; it was deleted after that comment was corrected. `_get_batch_runs` is excluded by
  scope (`STATUS.md` open owner decision 4). Tier B module `payload_builder.py` is kept: a third importer exists.
- Candidates for subsequent removal, not assumed dead: `PipelineController.start_pipeline_v2`, `_normalize_run_mode`,
  `_get_pipeline_state`. They became test-only because their only production caller (the deleted
  `AppController.run_pipeline`, whose docstring named `start_pipeline_v2`) is gone; `_normalize_run_mode` and
  `_get_pipeline_state` are called only from `start_pipeline_v2`. Checked for indirect reachability: no string literal,
  f-string or composed name, `getattr` site, callback registration or non-Python file reaches them (the dynamic
  `getattr` sites in `presentation_actions.py`, `job_history_panel_v2.py`, `queue_panel_v2.py` and
  `history_sequence_contract.py` use literal controller names or `f"{action}_sequence"`; `main_window_v2.py:1268`
  resolves `start_pipeline` or `start`). Three test files drive `start_pipeline_v2`
  (`test_core_run_path_v2.py`, `test_pipeline_controller_jobbuilder_integration_v2.py`,
  `test_pipeline_controller_run_modes_v2.py`), so removal needs a tier C decision (OD-3); one runtime doc
  (`PR-RUNTIME-WEBUI-WATCHDOG-120...md` line 41) still mentions the method. The evidence is static.
- Model / usage (host, actual model, effort, repair passes, result, exact start/end window and the line from
  `tools/usage_report.py --since <task-start> --until <end-after-closeout> --session <claude:ID|codex:ID> --line`):
  Claude Code (desktop app), `claude-sonnet-5-5`, effort not recorded by the host; one batched repair cycle (the
  rebase onto ARCH-930); result PASS for the scoped deletion, local full gate FAIL as described above. Window starts
  2026-11-10T20:23:30-05:00 (first message of the session; a start time was not recorded before discovery) and is
  shared with the follow-on plan and the start of ARCH-954. Session `claude:69062684-e681-4f4e-8cf9-e13d3f669d8b`.
  Claude Code claude-sonnet-5-5: 109 responses, fresh input 226, cache read 19.1M, cache write 363.9k, output 90.9k, reasoning 0 (in output) (tokens from host session logs; cost not reported)
