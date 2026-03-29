# PR-CONTRACT-254 - Intent Artifact Versioning and Hash Closure

Status: Completed 2026-03-29

## Purpose

Version and hash-close persisted intent surfaces so manifests, snapshots, and
replay payloads can prove what execution intent they represent.

## Delivered

- canonical intent artifact contract now lives in
  `src/pipeline/intent_artifact_contract.py`
- config layers now carry `intent_artifact_schema`,
  `intent_artifact_version`, and `intent_hash`
- job snapshots now emit a top-level `intent_contract` payload alongside the
  layered config contract

## Validation

- `tests/pipeline/test_intent_artifact_contract.py`
- `tests/utils/test_snapshot_builder_v2.py`
- `tests/pipeline/test_config_contract_v26.py`
