# PR-LEARN-263 - Artifact Metadata Inspector and Debug UI v2.6

Status: Proposed  
Date: 2026-03-22  
Branch baseline: `feature/video-secondary-motion-pr-236`  
Depends on: `PR-LEARN-261-Portable-Review-Metadata-Stamping`, `PR-LEARN-262-Portable-Review-Metadata-Rehydration-and-UI-Surfacing`  
Applies to: Review, Learning, Staged Curation, metadata debugging, artifact inspection

## 1. Purpose

StableNew already relies heavily on artifact metadata for:

- generation prompt recovery
- model / VAE recovery
- stage/config recovery
- staged-curation source reconstruction
- portable review metadata stamping and rehydration

But there is currently no first-class UI to directly inspect what metadata is actually
present on an image artifact.

This PR adds a dedicated metadata inspector/debug surface so operators can quickly see
what generation metadata and review metadata exist on an image, where that metadata
came from, and what StableNew believes the normalized interpretation is.

## 2. Problem Statement

Today, when metadata-related workflows go wrong, the operator cannot easily answer:

- does this image still have its original embedded generation metadata?
- did review metadata get stamped onto the image or only into a sidecar?
- is StableNew reading embedded metadata, sidecar metadata, or internal records?
- which prompt/config fields were actually recovered from the artifact?
- why did staged curation inherit a particular prompt or config?

That makes debugging harder than it should be and weakens user trust in the
artifact-driven workflow.

## 3. Goal

Add a first-class metadata inspection experience that shows:

- raw metadata presence
- normalized metadata interpretation
- metadata source precedence
- embedded vs sidecar vs internal-review source
- generation metadata and portable review metadata together

## 4. Guardrails

- inspector must be read-only in this PR
- do not create another editing surface for prompts/config here
- do not replace Review / Learning / Staged Curation as workflow surfaces
- focus on inspectability, traceability, and debugging
- avoid exposing low-value raw blobs without a normalized summary

## 5. Product Behavior

When the operator selects an image and opens metadata inspection, StableNew should be
able to show:

### 5.1 Generation metadata summary

- prompt
- negative prompt
- model
- vae
- sampler
- scheduler
- steps
- cfg
- width / height
- seed
- stage / stage manifest presence

### 5.2 Portable review metadata summary

- prior review present: yes/no
- source type: internal / embedded / sidecar
- user rating
- quality label
- subscores
- weighted score
- review timestamp
- notes excerpt
- prompt_before / prompt_after summary
- stages

### 5.3 Source/precedence diagnostics

- embedded generation metadata found: yes/no
- embedded portable review metadata found: yes/no
- sidecar portable review metadata found: yes/no
- internal learning record found: yes/no
- active precedence path selected by StableNew

## 6. Recommended UI Shape

Implement a reusable inspector surface that can be launched from multiple places.

### Option A - modal inspector window

Recommended initial implementation:

- `Open Metadata Inspector` button from Review preview area
- optional access from Learning / Staged Curation candidate preview
- opens read-only modal with tabs or sections

### Recommended sections

- `Normalized Summary`
- `Generation Metadata`
- `Portable Review Metadata`
- `Source Diagnostics`
- `Raw Payload` (collapsible / advanced)

## 7. Scope

### 7.1 Add artifact metadata inspector service / adapter

Create a service that collects all relevant metadata signals for one artifact and
returns a normalized inspection payload.

Suggested file target:

- `src/review/artifact_metadata_inspector.py`

Recommended responsibilities:

- read embedded generation metadata
- read embedded portable review metadata
- read sidecar portable review metadata
- optionally query internal review summary when available
- normalize into one inspection payload
- annotate source precedence and missing fields

### 7.2 Add Review-tab launch point

Add an `Inspect Metadata` button in Review near the preview / metadata area.

Suggested file target:

- `src/gui/views/review_tab_frame_v2.py`

### 7.3 Add Learning / Staged Curation launch point

Add a lightweight `Inspect Metadata` button for the selected candidate in staged
curation.

Suggested file target:

- `src/gui/views/learning_tab_frame_v2.py`

### 7.4 Add reusable inspector dialog/view

Create a read-only modal/dialog for viewing the inspection payload.

Suggested file targets:

- `src/gui/artifact_metadata_inspector_dialog.py`
- or another appropriately placed GUI module

## 8. Recommended Inspection Payload

Suggested top-level structure:

- `artifact_path`
- `normalized_generation_summary`
- `normalized_review_summary`
- `source_diagnostics`
- `raw_embedded_payload`
- `raw_sidecar_review_payload`
- `raw_internal_review_summary`

### Example normalized generation summary fields

- `prompt`
- `negative_prompt`
- `model`
- `vae`
- `sampler`
- `scheduler`
- `steps`
- `cfg_scale`
- `width`
- `height`
- `seed`
- `stage`
- `manifest_present`

### Example normalized review summary fields

- `prior_review_present`
- `source_type`
- `user_rating`
- `quality_label`
- `subscores`
- `weighted_score`
- `review_timestamp`
- `user_notes`
- `prompt_before`
- `prompt_after`
- `stages`

### Example source diagnostics fields

- `embedded_generation_present`
- `embedded_review_present`
- `sidecar_review_present`
- `internal_review_present`
- `active_review_precedence`
- `warnings`

## 9. UX Recommendations

### Minimal UX for first version

- one button to open inspector
- clear read-only sections
- copy-to-clipboard support for normalized summary and raw payloads
- collapsible raw JSON area for advanced debugging

### Helpful extras

- `Copy Normalized Summary`
- `Copy Raw Metadata JSON`
- `Open Sidecar Location` if sidecar exists
- `Refresh` button in inspector dialog

## 10. Suggested File Targets

Primary:

- `src/review/artifact_metadata_inspector.py`
- `src/gui/artifact_metadata_inspector_dialog.py`
- `src/gui/views/review_tab_frame_v2.py`
- `src/gui/views/learning_tab_frame_v2.py`
- `src/utils/image_metadata.py`
- `src/review/review_metadata_service.py`

Possible additional:

- `src/gui/controllers/learning_controller.py`
- `src/gui/controllers/review_workflow_adapter.py`

Tests:

- `tests/review/test_artifact_metadata_inspector.py`
- `tests/gui_v2/test_artifact_metadata_inspector_dialog.py`
- targeted Review/Learning launch-point tests

## 11. Execution Gates

This PR is complete only if:

1. the operator can open a metadata inspector for a selected image in Review
2. the operator can inspect metadata for a selected staged-curation candidate
3. the inspector clearly shows normalized generation metadata
4. the inspector clearly shows normalized portable review metadata when present
5. the inspector shows source diagnostics and precedence decisions
6. raw payload access exists for debugging without overwhelming the default view

## 12. Non-Goals

- do not add metadata editing in this PR
- do not redesign the full Review or Learning layouts
- do not attempt full metadata repair/fixup workflows here
- do not replace logging or test diagnostics; this complements them

## 13. Recommended PR Title

`PR-LEARN-263-Artifact-Metadata-Inspector-and-Debug-UI`

## 14. Recommended Commit Message

`Add artifact metadata inspector and debug UI`

## 15. Recommendation

Adopt this PR as the operator-trust and debugging layer for the artifact-driven
metadata architecture.

It will make the preceding portability work much easier to validate in real use:

- PR-261 writes portable review metadata
- PR-262 rehydrates and surfaces it
- PR-263 lets the operator directly verify what is actually on the artifact and what
  StableNew is interpreting from it
