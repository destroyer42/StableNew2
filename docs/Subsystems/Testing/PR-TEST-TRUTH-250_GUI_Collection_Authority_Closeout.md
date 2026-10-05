# PR-TEST-TRUTH-250 - retire the drained `tests/gui` collection exception

Result class: **CI/TEST AUTHORITY CLEANUP.** No production change (no `src/` files). Closes the sequence begun by
`PR-TEST-TRUTH-230_Legacy_GUI_Test_Surface_Disposition_Audit.md` (audit and rationale) and
`PR-TEST-TRUTH-240_GUI_Test_Surface_Drain.md` (migration).

## Result

`tests/gui/` no longer exists as a test surface or as a directory. Canonical GUI tests live under `tests/gui_v2/` plus their domain owners
(`tests/controller/`, `tests/learning_v2/`, ...). The historical exception ("optional legacy GUI / requires a live display") was obsolete
(see the audit) and has been removed from every place that named it.

Removed authority (nothing else was changed; `tests/gui_v1_legacy`, `tests/legacy`, `tests/quarantine`, `tests/scripts` and all other exclusions stay):

* `pyproject.toml`: `--ignore=tests/gui`;
* `tools/ci/run_collection_gate.py`: `tests/gui` in `DEFAULT_COLLECTION_EXCLUDES`;
* `tests/system/test_ci_truth_sync_v2.py`: `tests/gui` in the expected exclusion tuple (the test still proves that the gate exclusions and the
  `pyproject.toml` ignores agree);
* `tools/ci/validation_plan.py`: the `tests/gui/*` path rule and the `tests/gui` target of the GUI lane (`tests/gui_v2/*` and `tests/gui_v2` remain);
* `tests/gui/README.md`, the temporary placeholder that existed only because the routing-rot guard required the configured target to exist.

## Collection truth

Default collection is **5,079 before and after**: the 33 formerly excluded cases had already moved into default collection in PR-TEST-TRUTH-240, so
removing the ignore exposes nothing new.

## Validation

The change touches `pyproject.toml`, `run_collection_gate.py` and `validation_plan.py`, so the repository's own plan classifies it as CI/test
authority with a full census (`affected` is subsumed, not run in addition). The CI-truth-sync and validation-plan/routing-rot tests pass (81), the PR gate passes
(5,079 collected, 341-test required smoke) and the controller ratchet is unchanged. Local census on the implementation tree: 5,081 JUnit cases: 5,058 passed, 22 skipped, 1 failed, in 985 s. The repository collection gate
remains 5,079 runnable tests; the +2 in the JUnit census are the two previously documented collection-time skips (the same distinction as
5,038 gate-collected vs 5,040 JUnit cases in the Phase B1 report), so 5,081 - 2 = 5,079 and collection authority stayed exactly stable. The one local
failure was the known load-sensitive `test_pr_harden_009_r1a_txt2img_cancellation`, unrelated to this change. The hosted full census is the canonical verdict.

## Not changed

Dead production code identified by the audit (`PipelineRunControlsV2`, `LearningController._build_variant_overrides`,
`src/gui/views/learning_plan_table_v2.py`) remains for a separate owner-approved cleanup.
