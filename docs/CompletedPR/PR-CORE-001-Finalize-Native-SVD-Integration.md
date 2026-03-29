# PR-CORE-001 - Finalize Native SVD Integration

Status: Completed 2026-03-29

## Summary

The native SVD runtime, controller, GUI tab, and NJR-only submission path were
already shipped. This PR closed the remaining integration-hardening gaps by
adding explicit `svd_native` config validation in the canonical config
contract, dedicated controller-to-runner integration coverage, and canonical
docs/backlog closure for the active SVD path.

## Delivered

- validated `svd_native` execution payloads through
  `src/pipeline/config_contract_v26.py`
- enforced SVD payload validation in `AppController` before queue submission
  and capability probing
- added dedicated controller-to-runner SVD integration coverage in
  `tests/video/test_svd_integration.py`
- extended focused config-contract and controller tests for the SVD path
- updated canonical video docs, backlog ordering, and roadmap bookkeeping so
  the SVD integration work is treated as completed rather than still pending

## Key Files

- `src/pipeline/config_contract_v26.py`
- `src/controller/app_controller.py`
- `tests/pipeline/test_config_contract_v26.py`
- `tests/controller/test_app_controller_svd.py`
- `tests/controller/test_svd_controller.py`
- `tests/gui_v2/test_svd_tab_frame_v2.py`
- `tests/video/test_svd_integration.py`
- `docs/Subsystems/Video/Movie_Clips_Workflow_v2.6.md`
- `docs/PR_Backlog/CORE_TOP_20_EXECUTABLE_MINI_ROADMAP_v2.6.md`
- `docs/StableNew Roadmap v2.6.md`
- `docs/DOCS_INDEX_v2.6.md`

## Validation

- `c:/Users/rob/projects/StableNew/.venv/Scripts/python.exe -m pytest tests/pipeline/test_config_contract_v26.py tests/controller/test_app_controller_svd.py tests/controller/test_svd_controller.py tests/gui_v2/test_svd_tab_frame_v2.py tests/video/test_svd_integration.py -q`
- result: `40 passed, 2 skipped in 1.44s`

## Notes

- no low-level SVD runtime changes were required; the existing shipped path was
  already aligned with the NJR-only execution contract
- the next active CORE item is `PR-CORE-011 - End-to-End Pipeline Tests`