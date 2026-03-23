# PR-LEARN-261 - Portable Review Metadata Stamping

Status: Completed 2026-03-23

## Summary

Added a portable review metadata stamping layer so reviewed artifacts can carry
review outcomes with the image itself while preserving the internal learning
record as the canonical system of record.

## Delivered

- added [src/review/review_metadata_service.py](c:/Users/rob/projects/StableNew/src/review/review_metadata_service.py)
  to:
  - build the versioned portable review payload
  - stamp review metadata onto supported images using embedded metadata
  - fall back to adjacent `.review.json` sidecars when embedded writes are not
    supported or fail
  - read portable review metadata back from embedded or sidecar storage
- added review metadata exports in [src/review/__init__.py](c:/Users/rob/projects/StableNew/src/review/__init__.py)
- extended [src/utils/image_metadata.py](c:/Users/rob/projects/StableNew/src/utils/image_metadata.py)
  with reusable helpers for:
  - embedded review metadata reads
  - sidecar path construction and reads/writes
  - embedded-first portable review metadata resolution
- extended [src/gui/controllers/learning_controller.py](c:/Users/rob/projects/StableNew/src/gui/controllers/learning_controller.py)
  so `save_review_feedback(...)` now:
  - keeps the internal learning-record append path unchanged
  - performs best-effort post-append artifact metadata stamping
  - exposes the stamp result on the returned in-memory review record without
    making portable stamping a save blocker
- added focused coverage in:
  - [tests/controller/test_learning_controller_review_feedback.py](c:/Users/rob/projects/StableNew/tests/controller/test_learning_controller_review_feedback.py)
  - [tests/review/test_review_metadata_service.py](c:/Users/rob/projects/StableNew/tests/review/test_review_metadata_service.py)

## Outcomes

- reviewed artifacts now carry a versioned `stablenew_review` payload when
  embedding is supported
- unsupported or failed embedded writes now fall back to a portable
  `<image>.review.json` sidecar
- future rehydration and metadata-inspector work can rely on a single
  embedded-first, sidecar-second review metadata read path

## Guardrails Preserved

- no alternate execution path was introduced
- internal learning records remain the canonical review feedback store
- portable stamping is additive and does not replace the main StableNew image
  metadata contract
- review save flow remains best-effort and does not fail if artifact stamping
  cannot complete

## Verification

- `c:/Users/rob/projects/StableNew/.venv/Scripts/python.exe -m pytest tests/controller/test_learning_controller_review_feedback.py tests/review/test_review_metadata_service.py -q`