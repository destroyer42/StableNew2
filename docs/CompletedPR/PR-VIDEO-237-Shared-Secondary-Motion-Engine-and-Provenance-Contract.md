# PR-VIDEO-237 - Shared Secondary Motion Engine and Provenance Contract

Status: Completed 2026-03-21

## Summary

This PR added the first StableNew-owned reusable secondary-motion runtime and
the canonical provenance helpers that later backend integrations will adopt.

## Delivered

- deterministic shared motion engine in
  `src/video/motion/secondary_motion_engine.py`
- directory-based worker contract in
  `src/video/motion/secondary_motion_worker.py`
- canonical detailed and compact provenance helpers in
  `src/video/motion/secondary_motion_provenance.py`
- compact secondary-motion summaries now flow through:
  - `src/video/container_metadata.py`
  - `src/pipeline/result_contract_v26.py`

## Tests

Focused verification passed:

- `pytest tests/video/test_secondary_motion_models.py tests/video/test_secondary_motion_policy_service.py tests/video/test_secondary_motion_engine.py tests/video/test_secondary_motion_worker.py tests/video/test_secondary_motion_provenance.py tests/video/test_container_metadata.py tests/pipeline/test_result_contract_v26.py -q`
- result: `16 passed`
