# PR-LEARN-264 - Canonical Metadata Schemas and Contracts v2.6

Status: Proposed  
Date: 2026-03-22  
Branch baseline: `feature/video-secondary-motion-pr-236`  
Depends on: `PR-LEARN-261`, `PR-LEARN-262`, `PR-LEARN-263`  
Applies to: generation metadata, portable review metadata, rehydration summaries, inspector payloads

## 1. Purpose

StableNew is moving toward an artifact-centered metadata model:

- generation metadata embedded in image artifacts
- portable review metadata embedded in artifacts or written as sidecars
- normalized review-summary rehydration for UI and imports
- inspector/debug surfaces that interpret these payloads

This PR establishes one canonical repo-level contract so future PRs, tools, and
external consumers do not drift in field names, schema versions, precedence rules,
or payload semantics.

## 2. Goal

Create one authoritative metadata contract document and supporting schema examples for
these families:

- generation metadata contract
- portable review metadata contract
- normalized review-summary contract
- artifact metadata inspector contract

Primary outcome:

- one canonical repo-level source of truth for artifact metadata contracts

## 3. Problem Statement

Without a formal metadata contract:

- field names may drift across write/read paths
- embedded and sidecar payloads may diverge
- UI surfaces may interpret the same data differently
- external tools will not know which fields are stable
- debugging becomes harder because canonical semantics are unclear

## 4. Recommended Deliverables

### Deliverable A - canonical contract document

Add one central repo document, for example:

- `docs/Architecture/ARTIFACT_METADATA_CONTRACTS_v2.6.md`

This should be the human-readable authority.

### Deliverable B - machine-readable schema examples

Add structured example or schema files, for example:

- `docs/schemas/stablenew.review.v2.6.json`
- `docs/schemas/portable_review_summary.v2.6.json`
- `docs/schemas/artifact_metadata_inspection.v2.6.json`

These do not need to be full JSON Schema if the repo is not ready for that, but they
should be structured enough to reduce ambiguity.

### Deliverable C - precedence and lifecycle rules

Document how StableNew resolves metadata when multiple sources exist.

## 5. Required Contract Sections

The canonical doc should include at least:

### 5.1 Namespaces and schema versioning

Define:

- supported metadata namespaces
- schema naming conventions
- versioning rules
- backward-compatibility expectations

### 5.2 Write-path rules

Define how StableNew writes:

- generation metadata
- portable review metadata
- sidecar fallback metadata

### 5.3 Read-path rules

Define how StableNew reads:

- embedded generation metadata
- embedded review metadata
- sidecar review metadata
- normalized summaries

### 5.4 Precedence rules

Recommended prior-review precedence:

1. linked internal learning record
2. embedded portable review metadata
3. sidecar portable review metadata
4. none

Recommended generation precedence:

1. embedded generation metadata / stage manifest
2. structured fallback generation block
3. partial inferred fields
4. none

### 5.5 Preservation rules

Examples:

- existing generation metadata must be preserved
- adding review metadata must be additive
- sidecar fallback should preserve schema parity with embedded metadata where possible

### 5.6 Validation expectations

Define what fields must be validated and what can be tolerated as missing.

## 6. Schema Families To Define

### 6.1 Generation metadata contract

Should cover fields such as:

- prompt
- negative prompt
- model
- vae
- sampler
- scheduler
- steps
- cfg_scale
- width / height
- seed
- stage manifest / generation block structure
- lineage references where present

### 6.2 Portable review metadata contract

Suggested schema identifier:

- `stablenew.review.v2.6`

Suggested namespace:

- `stablenew_review`

Required fields should be clearly marked.

### 6.3 Normalized review-summary contract

Suggested structure:

- `PortableReviewSummary`

This should specify:

- source typing
- normalized field names
- precedence expectations
- guaranteed vs optional fields

### 6.4 Artifact metadata inspector contract

Suggested structure:

- `ArtifactMetadataInspection`

This should specify:

- normalized generation summary
- normalized review summary
- source diagnostics
- raw payload blocks
- warning/diagnostic semantics

## 7. Recommended File Targets

Primary docs:

- `docs/Architecture/ARTIFACT_METADATA_CONTRACTS_v2.6.md`
- `docs/schemas/stablenew.review.v2.6.json`
- `docs/schemas/portable_review_summary.v2.6.json`
- `docs/schemas/artifact_metadata_inspection.v2.6.json`

Possible code touchpoints if light validation helpers are introduced:

- `src/utils/image_metadata.py`
- `src/review/review_metadata_service.py`
- `src/review/artifact_metadata_inspector.py`

## 8. Recommended Document Shape

### Section 1 - Overview

- what metadata families exist
- what each is for
- where each is written/read

### Section 2 - Schema families

- generation metadata
- portable review metadata
- normalized review summary
- artifact inspection payload

### Section 3 - Precedence rules

- embedded vs sidecar
- internal vs portable
- strict vs best-effort reads

### Section 4 - Compatibility rules

- how version bumps are handled
- which fields are stable for external consumers
- which fields are internal-only / best-effort

### Section 5 - Examples

Provide concrete example payloads for each major schema.

## 9. Execution Gates

This PR is complete only if:

1. there is one authoritative contract doc for artifact metadata
2. portable review metadata fields and semantics are explicitly defined
3. normalized review-summary semantics are explicitly defined
4. inspector payload semantics are explicitly defined
5. precedence rules are clearly documented
6. example payloads or schema files exist for implementers and external tools

## 10. Non-Goals

- do not fully redesign runtime metadata services in this PR
- do not require full JSON Schema enforcement if the repo is not ready for it
- do not replace implementation-specific tests; this doc complements them
- do not collapse all metadata into one undifferentiated payload

## 11. Recommended PR Title

`PR-LEARN-264-Canonical-Metadata-Schemas-and-Contracts`

## 12. Recommended Commit Message

`Add canonical artifact metadata schemas and contracts`

## 13. Recommendation

Adopt this PR as the contract layer that stabilizes the new artifact-portability work.

This should become the authoritative metadata reference for:

- PR-261 write path
- PR-262 rehydration path
- PR-263 inspector/debug path
- future external-tool interoperability
