# PR-CONTRACT-254 - Intent Artifact Versioning and Hash Closure

Status: Completed 2026-03-29

## Delivered

- the repo now has a canonical intent artifact schema/version/hash contract
- config layers and job snapshots carry explicit intent version/hash metadata
- replay validation can prove intent identity before hydrating execution state

## Validation

- `tests/pipeline/test_intent_artifact_contract.py`
- `tests/pipeline/test_replay_validation_v2.py`
- `tests/utils/test_snapshot_builder_v2.py`
