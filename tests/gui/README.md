# tests/gui (drained)

This directory intentionally contains no tests. Its former cases were migrated to `tests/gui_v2/`,
`tests/controller/` or retired (see `docs/Subsystems/Testing/PR-TEST-TRUTH-240_GUI_Test_Surface_Drain.md`).

The directory still exists only because collection/routing authority (`pyproject.toml --ignore`,
`tools/ci/run_collection_gate.py`, `tools/ci/validation_plan.py`) still names it and the routing-rot guard requires every
named target to exist. The follow-on collection-authority cleanup removes those references and this placeholder together.
Do not add tests here.
