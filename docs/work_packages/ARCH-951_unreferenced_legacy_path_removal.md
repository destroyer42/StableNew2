# ARCH-951 — Remove unreferenced legacy execution and submission paths

Status: **PROPOSED, not authorized.** Produced by the design package ARCH-DESIGN-950
([assessment](../assessments/2026-11-10_arch_design_950_coordination_hotspot_decomposition.md),
[symbol inventory](../assessments/evidence/arch_design_950/STRUCTURAL_INVENTORY.md)). Implementation needs the owner's
explicit authorization and decision OD-1 (whether tier B is included). Date: 2026-11-10.

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

## Completion report

- Parent/final SHA:
- Files changed:
- Validation and CI:
- Main unchanged:
- Working tree clean:
- Ready for next phase: Yes / No
- Lines removed per file, and the new ceilings:
- Symbols kept despite being listed, with the reference found:
- Model / usage (host, actual model, effort, repair passes, result, exact start/end window and the line from
  `tools/usage_report.py --since <task-start> --until <end-after-closeout> --session <claude:ID|codex:ID> --line`):
