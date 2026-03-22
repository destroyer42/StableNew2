# PR-LEARN-262 - Portable Review Metadata Rehydration and UI Surfacing v2.6

Status: Proposed  
Date: 2026-03-22  
Branch baseline: `feature/video-secondary-motion-pr-236`  
Depends on: `PR-LEARN-261-Portable-Review-Metadata-Stamping`  
Applies to: Review, Learning, Staged Curation, discovered-review imports, metadata portability

## 1. Purpose

`PR-LEARN-261` adds a portable review metadata block stamped onto image artifacts
(or written as a sidecar when needed).

This follow-on PR makes StableNew able to **re-read** that portable review metadata
and surface it in the product so that review outcomes travel with the artifact and
become visible during later review, import, curation, and comparison workflows.

## 2. Problem Statement

Writing portable review metadata onto an artifact is only half the capability.

Without a matching read/rehydration path:

- imported images do not automatically regain their prior review state
- staged-curation candidates do not show prior review/rating context
- Review cannot display previous review history directly from the artifact
- external artifacts coming back into StableNew lose much of their portable value

## 3. Goal

Add a canonical read path that can detect and normalize portable review metadata from:

- embedded image metadata
- adjacent sidecar review metadata

Then surface that data in:

- Review tab
- Learning / Staged Curation candidate context
- import / discovered-review flows
- future lineage / compare flows

## 4. Guardrails

- preserve `LearningRecordWriter` as the canonical internal system of record
- portable review metadata is a rehydration source, not a replacement for internal records
- do not duplicate or multiply state silently without clear precedence rules
- imported review context must be clearly labeled as artifact-derived / portable metadata
- UI should distinguish between:
  - artifact-stamped review metadata
  - internal learning-record history

## 5. Product Behavior

### 5.1 Review reopen behavior

When a user opens an image in Review:

- StableNew checks for stamped portable review metadata
- if present, Review displays the latest prior rating/review summary
- the user can still add a new review, which writes both:
  - internal learning record
  - updated portable artifact metadata per PR-261

### 5.2 Staged-curation behavior

When a discovered/imported/staged-curation candidate is selected:

- StableNew checks for stamped review metadata
- if present, Learning / Staged Curation surfaces prior review summary, such as:
  - prior rating
  - quality label
  - notes
  - review timestamp
  - prompt_before / prompt_after summary where available

### 5.3 Import behavior

When images are imported from Review, history, or external folders:

- portable review metadata is read during import
- the imported item carries normalized review context with it
- this context is available for later UI display and analytics

## 6. Recommended Precedence Rules

When multiple review-data sources exist, use this precedence model:

1. latest internal learning record explicitly linked to the image
2. embedded portable review metadata on the artifact
3. sidecar portable review metadata
4. no review context

If internal history is not available, artifact-level portable review metadata should be
sufficient to restore a usable review summary.

## 7. Recommended Data Model Addition

Introduce a normalized review summary structure, for example:

- `PortableReviewSummary`

Recommended normalized fields:

- `source_type`
  - `internal_learning_record`
  - `embedded_review_metadata`
  - `sidecar_review_metadata`
- `schema`
- `review_timestamp`
- `user_rating`
- `user_rating_raw`
- `quality_label`
- `subscores`
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
- `review_record_id`

## 8. Implementation Scope

### 8.1 Extend review metadata service with read/normalize helpers

Add service methods to:

- detect embedded stamped review metadata
- detect sidecar review metadata
- normalize artifact-level review payloads into a stable summary contract
- optionally reconcile internal and portable summaries

Suggested file targets:

- `src/review/review_metadata_service.py`
- `src/utils/image_metadata.py`

### 8.2 Review tab surfacing

When an image is shown in Review, surface prior review metadata in a dedicated panel.

Recommended panel label:

- `Prior Review Summary`

Suggested content:

- prior rating
- quality label
- review timestamp
- short notes
- prior prompt delta summary
- source type (embedded / sidecar / internal)

Suggested file target:

- `src/gui/views/review_tab_frame_v2.py`

### 8.3 Learning / Staged Curation surfacing

When a candidate is selected in Staged Curation, display whether that artifact has
already been reviewed and summarize prior portable review state.

Recommended additions:

- `Prior Review` read-only block in the staged-curation selection workspace
- compact fields such as:
  - rating
  - quality
  - note excerpt
  - review date
  - prompt delta summary if available

Suggested file targets:

- `src/gui/views/learning_tab_frame_v2.py`
- `src/gui/controllers/learning_controller.py`

### 8.4 Import/discovered-review enrichment

When discovered/imported items are built from image paths, enrich them with normalized
review metadata if present.

Suggested file targets:

- `src/gui/controllers/learning_controller.py`
- `src/learning/discovered_review_models.py`
- discovered-review helper layers as needed

### 8.5 Analytics / future-proofing hooks

Do not fully redesign analytics here, but expose normalized review metadata in a way
that later analytics can consume it.

Suggested file targets:

- `src/learning/learning_analytics.py` only if light hook support is needed

## 9. UI Recommendations

### Review tab

Add a read-only `Prior Review Summary` section near the current preview / metadata
surface.

Recommended display elements:

- `Rating: 4/5 (good)`
- `Reviewed: 2026-03-22T...`
- `Source: embedded artifact metadata`
- `Notes: ...`
- `Prompt change: append / replace / modify`

### Learning / Staged Curation

Add a compact `Prior Review` block in the right-side selection workspace.

Recommended display elements:

- `Prior review: yes/no`
- `Rating`
- `Quality`
- `Reviewed on`
- `Notes excerpt`
- `Prompt changed: yes/no`

## 10. Suggested File Targets

Primary:

- `src/review/review_metadata_service.py`
- `src/utils/image_metadata.py`
- `src/gui/views/review_tab_frame_v2.py`
- `src/gui/views/learning_tab_frame_v2.py`
- `src/gui/controllers/learning_controller.py`

Possible additional:

- `src/learning/discovered_review_models.py`
- `src/gui/controllers/review_workflow_adapter.py`

Tests:

- `tests/review/test_review_metadata_service.py`
- `tests/gui_v2/test_review_tab_prior_review_summary.py`
- `tests/gui_v2/test_learning_tab_staged_prior_review_summary.py`
- integration tests around import/rehydration

## 11. Read Path Requirements

StableNew must support these read scenarios:

### Scenario A - embedded artifact metadata only

- artifact has stamped review metadata
- no internal learning record available
- UI still shows prior review summary

### Scenario B - sidecar metadata only

- artifact lacks embedded review block
- adjacent `.review.json` exists
- UI still shows prior review summary

### Scenario C - both internal and portable metadata exist

- internal record takes precedence for latest canonical summary
- portable metadata is still available for portability / audit note

## 12. Failure Handling

Portable review rehydration should be non-blocking.

If parsing fails:

- do not fail image load/import
- simply omit prior review summary
- log diagnostic detail

## 13. Execution Gates

This PR is complete only if:

1. StableNew can detect and parse stamped review metadata from embedded artifacts
2. StableNew can detect and parse sidecar review metadata
3. Review tab surfaces prior portable review summary when available
4. Learning / Staged Curation surfaces prior portable review summary when available
5. discovered/imported items can carry normalized review context forward
6. internal learning-record precedence remains intact when both sources exist

## 14. Non-Goals

- do not replace internal learning records
- do not redesign all analytics around portable metadata in this PR
- do not attempt full bidirectional sync conflict resolution beyond basic precedence
- do not require every UI surface to expose the full review payload

## 15. Recommended PR Title

`PR-LEARN-262-Portable-Review-Metadata-Rehydration-and-UI-Surfacing`

## 16. Recommended Commit Message

`Add portable review metadata rehydration and UI surfacing`

## 17. Recommendation

Treat this PR as the natural companion to PR-261.

- PR-261 makes review metadata portable
- PR-262 makes that portability usable inside StableNew again

Together they create artifact-level interoperability without abandoning the existing
internal learning-record architecture.
