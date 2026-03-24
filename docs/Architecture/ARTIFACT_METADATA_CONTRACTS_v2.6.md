# Artifact Metadata Contracts v2.6

Status: Canonical
Updated: 2026-03-23

## 1. Purpose

This document is the authoritative contract for artifact-centered metadata in
StableNew v2.6.

It defines the stable semantics for:

- embedded generation metadata written into image artifacts
- portable review metadata written into image artifacts or review sidecars
- normalized review-summary payloads used by controllers, UI, and imports
- artifact metadata inspection payloads used by debug and operator surfaces

This document is the contract layer for the metadata work landed in:

- PR-LEARN-261 write path
- PR-LEARN-262 rehydration path
- PR-LEARN-263 inspector and debug path

Low-level image-container encoding details remain in
`docs/Image_Metadata_Contract_v2.6.md`, but field naming, precedence, and
cross-surface semantics are defined here.

## 2. Contract Families

StableNew currently uses four metadata families.

### 2.1 Embedded generation metadata

Purpose:

- carry a portable, deterministic generation capsule with the artifact
- preserve stage-manifest and prompt/config evidence for later inspection
- provide a best-effort recovery path when full history is unavailable

Canonical schema identifier:

- `stablenew.image-metadata.v2.6`

Carrier:

- embedded image metadata keys in PNG or JPG

Companion public projection:

- `stablenew.public-image-metadata.v2.6`

Authoritative implementation:

- `src/utils/image_metadata.py`

### 2.2 Portable review metadata

Purpose:

- carry review outcomes with the artifact itself
- preserve operator notes, ratings, and prompt-change evidence across exports
- provide a re-importable review signal when internal learning records are not
  available

Canonical schema identifier:

- `stablenew.review.v2.6`

Carrier:

- embedded metadata key `stablenew_review`
- sidecar fallback `<artifact-name>.review.json`

Authoritative implementation:

- `src/review/review_metadata_service.py`
- `src/utils/image_metadata.py`

### 2.3 Normalized review summary

Purpose:

- expose one stable controller/UI payload regardless of whether review context
  came from internal records, embedded review metadata, or a sidecar
- preserve source provenance and underlying schema identity without making GUI
  surfaces parse raw carriers directly

Canonical normalized type:

- `PortableReviewSummary`

Internal normalized schema identifier:

- `stablenew.internal-review-summary.v2.6`

Authoritative implementation:

- `src/review/review_metadata_service.py`
- `src/gui/controllers/learning_controller.py`

### 2.4 Artifact metadata inspection payload

Purpose:

- provide one read-only, debuggable payload that explains what metadata is
  present, which review source won precedence, and which raw blocks were read
- keep debug logic out of GUI widgets by centralizing inspection semantics

Canonical normalized type:

- `ArtifactMetadataInspection`

Authoritative implementation:

- `src/review/artifact_metadata_inspector.py`

## 3. Namespaces and Versioning Rules

StableNew uses explicit schema identifiers rather than implicit shape matching.

Current active identifiers:

- `stablenew.image-metadata.v2.6`
- `stablenew.public-image-metadata.v2.6`
- `stablenew.review.v2.6`
- `stablenew.internal-review-summary.v2.6`

Versioning rules:

1. Schema identifiers are stable once published in active docs.
2. A version bump is required for breaking field-name or semantic changes.
3. Additive optional fields may be introduced without changing the schema id if:
   - existing required/always-emitted semantics stay intact
   - readers continue to tolerate missing optional fields
4. External consumers must treat undocumented fields as unstable.
5. GUI and controller surfaces must read normalized payloads rather than invent
   alternate local interpretations of raw metadata.

Backward-compatibility rules:

- read paths are best-effort and tolerant of missing optional fields
- write paths should preserve existing unrelated artifact metadata when adding
  StableNew-owned keys
- sidecar portable review payloads should preserve schema parity with embedded
  review payloads whenever possible

## 4. Write-Path Rules

### 4.1 Generation metadata write rules

StableNew writes one embedded generation capsule for still-image artifacts.

Required carrier keys:

- `stablenew:schema`
- `stablenew:job_id`
- `stablenew:run_id`
- `stablenew:stage`
- `stablenew:created_utc`
- `stablenew:payload_sha256`

Exactly one payload carrier must be present:

- `stablenew:payload`
- `stablenew:payload_gz_b64`
- or omission markers when the payload exceeds size limits

Write semantics:

- generation metadata is additive and must preserve unrelated existing metadata
- canonical payload bytes use stable JSON serialization and SHA-256 hashing
- public projection keys may be emitted alongside the canonical capsule for
  interoperability and human inspection

### 4.2 Portable review metadata write rules

StableNew writes portable review metadata only after canonical internal review
feedback has already been recorded.

Write order:

1. append canonical internal learning record
2. attempt embedded review metadata write using `stablenew_review`
3. if embedded write fails, attempt sidecar fallback using
   `<artifact-name>.review.json`
4. never fail the canonical internal save only because portable stamping failed

Write semantics:

- review stamping is best-effort and non-fatal
- embedded review metadata is preferred over sidecars when embedding succeeds
- portable review payloads should remain additive and must not remove existing
  generation metadata

## 5. Read-Path Rules

### 5.1 Generation metadata read rules

Read order for the embedded generation capsule:

1. verify `stablenew:schema == stablenew.image-metadata.v2.6`
2. decode `stablenew:payload` or `stablenew:payload_gz_b64`
3. validate `stablenew:payload_sha256`
4. tolerate missing or omitted payloads without raising product-blocking errors

If embedded generation metadata is missing or stripped, StableNew may fall back
to public projection fields, stage manifests, or partial inferred fields where
the specific surface already supports that behavior.

### 5.2 Portable review metadata read rules

Read order for portable review metadata:

1. inspect embedded `stablenew_review`
2. if no embedded payload is available, inspect sidecar fallback
3. if both are missing, return `missing`
4. if an embedded read is corrupt, surface the read error and still allow the
   caller to decide whether to inspect sidecar fallback

### 5.3 Normalized summary read rules

GUI and controller surfaces must prefer normalized review summaries over direct
raw-payload interpretation.

Normalization rules:

- `source_type` identifies where the summary came from
- `schema` preserves the underlying source schema identifier
- fields not available from the source are emitted as empty strings, empty lists,
  empty dicts, or `null` where the normalized type already allows that
- prompt-delta and negative-prompt-delta are best-effort, not guaranteed

## 6. Precedence Rules

### 6.1 Prior review precedence

StableNew resolves prior-review context in this order:

1. linked internal learning record
2. embedded portable review metadata
3. sidecar portable review metadata
4. none

This is the canonical precedence used by controller rehydration and inspector
surfaces.

### 6.2 Generation summary precedence

StableNew resolves generation summary fields in this order:

1. embedded generation payload plus stage-manifest config
2. structured fallback generation block where present
3. partial inferred fields already recoverable from public or legacy carriers
4. none

### 6.3 Inspector precedence semantics

`ArtifactMetadataInspection.source_diagnostics.active_review_precedence` may only
contain:

- `internal_learning_record`
- `embedded_review_metadata`
- `sidecar_review_metadata`
- `none`

## 7. Preservation Rules

StableNew must preserve existing metadata whenever possible.

Preservation requirements:

- existing generation metadata remains authoritative for generation evidence
- adding portable review metadata must be additive
- writing embedded review metadata must not strip other existing image metadata
- sidecar fallback should mirror the embedded review payload shape instead of
  inventing a separate sidecar-only schema
- normalized review summaries and inspector payloads are read models; they do
  not replace the raw artifact-owned metadata carriers

## 8. Validation Expectations

Validation must distinguish between carrier integrity and semantic completeness.

Carrier integrity that should be validated:

- embedded generation schema identifier
- canonical payload hash when embedded payload bytes are present
- portable review metadata must decode to a JSON object
- sidecar review files must decode to an object containing `stablenew_review`

Semantic fields that may be missing without making the artifact unusable:

- user rating
- weighted score
- prompt deltas
- stage lists
- model, sampler, scheduler, and other optional review echo fields
- raw embedded generation payload sub-blocks outside the normalized fields

UI and debug surfaces should expose missing data as unavailable rather than
failing closed.

## 9. Stable vs Best-Effort Fields

The following are considered stable for external consumers in v2.6:

- schema identifiers listed in this document
- portable review namespace key `stablenew_review`
- sidecar suffix `.review.json`
- normalized review precedence order
- inspection precedence values in `active_review_precedence`
- normalized generation summary field names currently exposed by the inspector:
  `prompt`, `negative_prompt`, `model`, `vae`, `sampler`, `scheduler`, `steps`,
  `cfg_scale`, `width`, `height`, `seed`, `stage`, `present`,
  `manifest_present`

The following are best-effort and may be absent or partially populated:

- prompt deltas
- public projection strings intended for human-readable interoperability
- raw payload blocks inside inspection payloads
- lineage, selection-event, and curation-decision echoes in portable review
  metadata

## 10. Machine-Readable Companions

The following files are the machine-readable companion contracts for this
document:

- `docs/schemas/stablenew.image-metadata.v2.6.json`
- `docs/schemas/stablenew.review.v2.6.json`
- `docs/schemas/portable_review_summary.v2.6.json`
- `docs/schemas/artifact_metadata_inspection.v2.6.json`

These files are intentionally example-oriented rather than full JSON Schema, but
they are structured enough to keep field names, precedence values, and schema
identifiers aligned with the implementation.

## 11. Example Resolution Flow

For a reviewed artifact inspected in StableNew:

1. read embedded generation metadata if present
2. query internal learning records for prior review summary
3. if no internal summary exists, read embedded portable review metadata
4. if no embedded review payload exists, read sidecar review metadata
5. normalize the winning review payload into `PortableReviewSummary`
6. build one `ArtifactMetadataInspection` payload for the GUI/debug surface

This preserves the architecture boundary:

- raw artifact carriers remain artifact-owned truth for portability
- internal learning records remain canonical first-party review history
- GUI surfaces stay thin and consume controller/service payloads
