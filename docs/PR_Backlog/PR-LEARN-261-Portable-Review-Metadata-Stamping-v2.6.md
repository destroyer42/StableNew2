# PR-LEARN-261 - Portable Review Metadata Stamping v2.6

Status: Proposed  
Date: 2026-03-22  
Branch baseline: `feature/video-secondary-motion-pr-236`  
Applies to: Review, Learning records, image metadata, portability, auditability

## 1. Purpose

StableNew currently saves review/rating feedback into the Learning records store, but
it does not stamp that review metadata back onto the reviewed image artifact itself.

This PR adds a canonical, portable review metadata block that is written back onto the
image file (and optionally a sidecar where embedding is not safe/possible), so other
programs, tools, and downstream workflows can read and utilize the review outcome
without requiring direct access to StableNew's internal learning-record storage.

## 2. Problem Statement

Current behavior:

- review-tab feedback is persisted into `LearningRecordWriter`
- learning analytics and recommendation flows can use that data internally
- the original image file typically keeps only its original generation metadata
- external tools reading the image cannot see the review/rating outcome

This creates several gaps:

- review signal is not portable with the artifact
- other tools cannot consume rating/review outcomes without custom integration
- image-level auditability is weaker than it should be
- source-vs-derived review provenance is harder to carry across systems

## 3. Goal

Introduce a canonical portable review metadata contract that can be stamped onto
reviewed artifacts and later re-read by StableNew or external tools.

Primary outcome:

- reviewed images carry both generation metadata and review metadata

## 4. Guardrails

- do not destroy or overwrite existing generation metadata
- do not mutate the source artifact in a lossy way
- preserve the current Learning-record write path as the system of record
- stamping must be additive, not a replacement for internal record storage
- support safe fallback to sidecar metadata when direct embedding is unsupported
- stamped metadata must be versioned and documented

## 5. Product Behavior

After a user saves review feedback from the Review tab:

1. StableNew still writes the canonical internal learning record
2. StableNew also writes a portable review metadata block onto the image artifact
3. if direct image embedding is not available or would be unsafe, StableNew writes a
   sidecar file adjacent to the image
4. future imports / staged-curation / review reopen flows can read that portable
   review metadata back in

## 6. Recommended Metadata Contract

Add a new portable block, for example:

- `stablenew_review`

Recommended schema version:

- `stablenew.review.v2.6`

### Minimum fields

- `schema`
- `review_timestamp`
- `source`
- `image_path` or portable artifact id where appropriate
- `user_rating`
- `user_rating_raw`
- `quality_label`
- `subscores`
  - `anatomy`
  - `composition`
  - `prompt_adherence`
- `weighted_score`
- `user_notes`
- `prompt_before`
- `prompt_after`
- `negative_prompt_before`
- `negative_prompt_after`
- `prompt_delta`
- `negative_prompt_delta`
- `prompt_mode`
- `negative_prompt_mode`
- `stages`
- `review_context`
- `review_actor`
- `review_record_id` / `run_id` link back to internal record where available

### Optional fields

- `lineage`
- `selection_event`
- `curation_decision`
- `review_tags`
- `source_candidate_id`
- `derived_candidate_id`
- `model`
- `sampler`
- `scheduler`
- `steps`
- `cfg_scale`

## 7. Storage Strategy

Implement a layered strategy.

### Primary target: embedded image metadata

For formats that support safe metadata embedding, write the review block directly into
image metadata alongside existing generation metadata.

Preferred behavior:

- preserve original embedded metadata payload
- merge in a new namespaced review block
- write without discarding existing prompt/generation fields

### Fallback target: sidecar file

When embedding is unsupported, unsafe, or would rewrite the artifact in a risky way,
write a sidecar file next to the image.

Recommended filename pattern:

- `<image_filename>.review.json`

Sidecar should contain the same schema block.

## 8. Read Path Requirements

StableNew should be able to read portable review metadata from either:

- embedded artifact metadata
- adjacent sidecar metadata

Precedence recommendation:

1. embedded review block if present
2. sidecar review block if present
3. internal learning-record fallback if explicitly requested

## 9. Implementation Scope

### 9.1 Add a portable review metadata service

Create a dedicated service responsible for:

- building stamped review payloads
- merging payloads into existing image metadata safely
- writing sidecars when needed
- reading stamped review metadata back out

Suggested file target:

- `src/review/review_metadata_service.py`

### 9.2 Add metadata writer helpers

Add or extend lower-level metadata utilities to support safe merge-write behavior.

Suggested file targets:

- `src/utils/image_metadata.py`
- or a dedicated metadata writer helper if separation is cleaner

### 9.3 Integrate with review save path

Update `LearningController.save_review_feedback(...)` so that after the internal
Learning record is written, the portable review metadata stamp is also attempted.

Suggested file targets:

- `src/gui/controllers/learning_controller.py`
- `src/gui/views/review_tab_frame_v2.py` only if UI messaging/status needs updating

### 9.4 Re-read stamped metadata during imports

When images are imported into Review / Learning / Staged Curation, read stamped review
metadata if available and surface it in UI or derived context.

Suggested file targets:

- `src/utils/image_metadata.py`
- `src/gui/controllers/learning_controller.py`
- `src/gui/views/review_tab_frame_v2.py`
- discovered-review import helpers as needed

## 10. Proposed PR Deliverables

### Deliverable A - schema contract

- define `stablenew.review.v2.6`
- document required/optional fields
- define embedded-vs-sidecar precedence rules

### Deliverable B - write path

- add service method to stamp review metadata onto image
- preserve existing generation metadata
- fallback to sidecar on unsupported formats or write failure

### Deliverable C - read path

- add helper to read review metadata from image or sidecar
- return normalized payload for UI/analytics/import flows

### Deliverable D - review integration

- call stamping service from `save_review_feedback(...)`
- keep current internal record write unchanged
- surface success/fallback/failure clearly in logs and optionally UI

### Deliverable E - tests

- unit tests for metadata payload build
- unit tests for merge-with-existing-metadata behavior
- unit tests for sidecar fallback
- regression tests ensuring existing generation metadata survives
- read/write roundtrip tests

## 11. UX Recommendations

Minimal UX for this PR:

- keep save flow unchanged for the operator
- optionally show a lightweight status note such as:
  - `Feedback saved + embedded into image metadata`
  - `Feedback saved + sidecar written`
  - `Feedback saved internally; artifact stamping failed`

Do not block the save flow if artifact stamping fails.

## 12. Failure Handling

Stamping should be best-effort, not all-or-nothing.

Recommended order:

1. write internal learning record
2. attempt embedded metadata write
3. if embedded write fails, attempt sidecar write
4. if both fail, log warning and continue

This ensures the canonical internal review signal is never lost due to an artifact
write issue.

## 13. Suggested File Targets

Primary:

- `src/gui/controllers/learning_controller.py`
- `src/utils/image_metadata.py`
- `src/review/review_metadata_service.py`

Possible additional:

- `src/gui/views/review_tab_frame_v2.py`
- `src/learning/discovered_review_models.py`
- `src/gui/controllers/review_workflow_adapter.py`

Tests:

- `tests/review/test_review_metadata_service.py`
- `tests/utils/test_image_metadata_review_merge.py`
- targeted integration tests around review save/import behavior

## 14. Execution Gates

This PR is complete only if:

1. saving review feedback still writes the internal learning record
2. reviewed images receive a portable review metadata block when supported
3. unsupported/unsafe cases write a sidecar instead
4. existing generation metadata remains intact after stamping
5. StableNew can re-read its own stamped review metadata
6. external tools can parse the portable review metadata without needing the internal
   learning-record store

## 15. Non-Goals

- do not replace Learning records as the canonical internal system of record
- do not redesign the full review UI in this PR
- do not require all image formats to support direct embedding
- do not make save-feedback fail just because stamping failed

## 16. Recommended PR Title

`PR-LEARN-261-Portable-Review-Metadata-Stamping`

## 17. Recommended Commit Message

`Add portable review metadata stamping to reviewed image artifacts`

## 18. Recommendation

Adopt this PR as the portability/auditability bridge between StableNew's internal
review-learning system and artifact-level interoperability.

This should be treated as foundational support for:

- external tool interoperability
- portable dataset curation
- source-vs-derived review traceability
- richer staged-curation imports and reimports
