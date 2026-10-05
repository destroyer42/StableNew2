# PR-DEVEX-TEST-SLIM-130 - Phase B2A semantic duplicate consolidation

Result class: **TEST CONSOLIDATION (test-only).** Zero `src/` changes; no CI routing, marker, skip or xfail change. Execution profile: Standard
(Claude Code, Sonnet 5.5 High). Principle (from B1): remove test cost only where equivalent or stronger surviving coverage is demonstrated, never for a count.

## Audit method

1. Enumerated the 46 `test_pr_*` files outside `archive/` and classified them from names and contents; filename age or PR number was never treated as evidence.
2. Inspected the canonical queue/runner/backend integration family first (`tests/integration/test_pr_img_*`, `test_njr_queue_runner_transport.py`,
   the `test_pr_mvp_045/060` journeys, `test_pr_runtime_100_transition_queue.py`). The shared harness this package was expected to extract **already exists**:
   `tests/helpers/njr_queue_harness.py::run_njr_via_queue` (NJR -> real `JobService` -> real SQLite queue/repository -> real `PipelineRunner.run_njr`, only
   `requests.Session.request` faked) and `tests/helpers/fake_webui_transport.py`. The journeys that look alike are not duplicates: `test_pr_mvp_045` (matrix
   expansion, preview config overlay, queue count, no runner), `test_pr_mvp_060_phase1b` (repeated manual dispatch, pause/resume, ordering) and
   `test_pr_mvp_060_image_vertical_slice` (full production composition, artifacts, history, replay lineage) each own different invariants; the Klein/Forge/D110
   canonical-path files are backend-specific fail-closed and identity matrices. **All of that family is KEPT.**
3. Because no semantic duplicate was found there, a repository-wide AST scan hashed every test file and every test function body. That found a coherent, exact family:
   **byte-identical test files stored at two paths** (a historical top-level copy plus the domain-directory copy).

## Candidate family and result

Eleven byte-identical pairs exist. Two pairs involve `tests/scripts/` (ignored by default collection, so never double-run) and were deliberately left. The remaining
nine pairs are both default-collected; the **top-level** copy of each was removed and the domain-directory copy (the canonical owner) survives:

| Removed (top level) | Surviving owner | Tests | Invariant (unchanged) |
|---|---|---:|---|
| `tests/test_filename_fix.py` | `tests/utils/test_filename_fix.py` | 1 | `build_safe_image_name` yields short, unique, safe names (Windows MAX_PATH regression) |
| `tests/test_matrix_filenames.py` | `tests/pipeline/test_matrix_filenames.py` | 1 | matrix-expanded jobs resolve to unique runtime filenames |
| `tests/test_multi_slot_load.py` | `tests/state/test_multi_slot_load.py` | 1 | multi-slot prompt txt loads into prompt-workspace state |
| `tests/test_override_functionality.py` | `tests/controller/test_override_functionality.py` | 1 | config snapshot honors the override checkbox |
| `tests/test_pr032.py` | `tests/utils/test_pr032.py` | 2 | `InMemoryLogHandler` capture; `attach_gui_log_handler` attaches to root |
| `tests/test_pr_gui_003c_runtime.py` | `tests/pipeline/test_pr_gui_003c_runtime.py` | 2 | matrix expansion from pack JSON; matrix tokens replaced in prompts |
| `tests/test_reprocess_batching.py` | `tests/pipeline/test_reprocess_batching.py` | 1 | `ReprocessJobBuilder` builds jobs for 1/10/100-image batches |
| `tests/test_pr_gui_004_phase_a.py` | `tests/utils/test_pr_gui_004_phase_a.py` | 3 | LoRA keyword detection (CivitAI info, txt, none) |
| `tests/test_checkbox_fix.py` | `tests/controller/test_checkbox_fix.py` | 0 | (no collected tests; byte-identical duplicate) |

Every pair has identical test-function bodies (AST-equal). The only byte difference, in the `test_pr_gui_004_phase_a` pair, is decorative text in the non-test
`if __name__ == "__main__"` print statements. Survivor execution context is equal or stronger: `tests/controller/` additionally provides the controller conftest fixtures.

## Equivalence evidence (negative probes)

A reversible temporary mutation of production code was applied for each distinct invariant; the surviving test failed under it and passed after the revert
(`git status` clean, no `src/` change in the final diff). Probe results (survivor before / under mutation / after revert):

| Probe | Mutation | Survivor result |
|---|---|---|
| P1 | `build_safe_image_name` returns the old long, unsanitised name | pass / FAIL / pass |
| P2 | `build_safe_image_name` collapses every name to one value | pass / FAIL / pass |
| P3 | `parse_multi_slot_txt` returns nothing | pass / FAIL / pass |
| P4 | `AppController._build_config_snapshot_with_override` returns `{}` | pass / FAIL / pass |
| P5a | `InMemoryLogHandler.emit` is a no-op | pass / FAIL / pass |
| P5b | `attach_gui_log_handler` does not attach to the root logger | pass / FAIL / pass |
| P6 | `PromptPackNormalizedJobBuilder._expand_entry_by_matrix` returns the entry unexpanded | pass / FAIL / pass |
| P7 | `ReprocessJobBuilder.build_reprocess_job` raises | pass / FAIL / pass |
| P8a | `detect_lora_keywords` returns nothing | pass / FAIL / pass |
| P8b | `detect_lora_keywords` invents a keyword | pass / FAIL / pass |

Sensitivity limit found while probing (shared by both identical copies, so nothing was lost by consolidating): the matrix-filename uniqueness test derives
uniqueness from the per-variant prefix, so a mutation that keeps the prefix but drops matrix/seed hashing is **not** detected. Strengthening it is separate debt.
Likewise `test_reprocess_batching` only fails if the builder raises (its counts are local loop counters).

## Collection and validation

* Default collection **5,080 -> 5,068 (-12)**: 1+1+1+1+2+2+1+3 removed tests; each survivor collects the same number as its removed twin; the routing-rot and truth-sync tests pass (81); no stale path references exist.
* `python tools/ci/run_pr_gate.py` passes (5,068 collected, 341-test required smoke). The validation plan selects lane `core` (35 affected targets); this package additionally
  requires a **hosted full census before merge** (request it with the `full-census` label).
* Local run of the 35 core targets: 2,186 passed and 40 failed; all 40 are `pipeline` runner-integration tests that fail identically on pristine `origin/main` on this workstation
  because the runtime-transition gate sees a live, unowned Comfy endpoint (`action_required`); they are environmental and are not touched by this change. Hosted CI is the authoritative run.
* Runtime reduction is not an acceptance criterion; the removed tests cost well under a second in total.

## Kept and deferred

All Klein/Forge/D110 canonical-path matrices, the mvp_045/060 journeys, the runtime-transition and SVD/Wan queue slices, the learning `test_pr_learn_300_*` files, the harden watchdog/cancellation files and
the Comfy lifecycle files were kept (unique invariants or backend-specific signal). The two `tests/scripts` duplicate pairs and the near-duplicate `tests/test_pr_005_006.py` / `test_pr_008.py` vs their
`tests/gui_v2/` versions (not byte-identical; GUI surfaces) are deferred. The identical teardown/ownership tests repeated across the `tests/tools/test_vid*` qualification files are a candidate for a later, separate review.

Hosted CI: pending.
