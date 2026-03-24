# PR-LEARN-264 - Canonical Metadata Schemas and Contracts

Status: Completed 2026-03-23

## Summary

Added one canonical artifact-metadata contract layer for the generation,
portable review, normalized review-summary, and artifact-inspection payloads
introduced across PR-LEARN-261 through PR-LEARN-263.

## Delivered

- added [docs/Architecture/ARTIFACT_METADATA_CONTRACTS_v2.6.md](c:/Users/rob/projects/StableNew/docs/Architecture/ARTIFACT_METADATA_CONTRACTS_v2.6.md)
  as the authoritative human-readable contract for:
  - embedded generation metadata
  - portable review metadata
  - normalized review summaries
  - artifact metadata inspection payloads
- added machine-readable companion files in [docs/schemas/stablenew.image-metadata.v2.6.json](c:/Users/rob/projects/StableNew/docs/schemas/stablenew.image-metadata.v2.6.json), [docs/schemas/stablenew.review.v2.6.json](c:/Users/rob/projects/StableNew/docs/schemas/stablenew.review.v2.6.json), [docs/schemas/portable_review_summary.v2.6.json](c:/Users/rob/projects/StableNew/docs/schemas/portable_review_summary.v2.6.json), and [docs/schemas/artifact_metadata_inspection.v2.6.json](c:/Users/rob/projects/StableNew/docs/schemas/artifact_metadata_inspection.v2.6.json)
- updated [docs/DOCS_INDEX_v2.6.md](c:/Users/rob/projects/StableNew/docs/DOCS_INDEX_v2.6.md)
  so the new canonical contract and schema companions are part of the active
  doc set
- updated [docs/Image_Metadata_Contract_v2.6.md](c:/Users/rob/projects/StableNew/docs/Image_Metadata_Contract_v2.6.md)
  to point field-level semantics at the new canonical artifact-metadata
  contract while keeping its low-level carrier/encoding role
- added focused drift protection in [tests/review/test_metadata_contract_schemas.py](c:/Users/rob/projects/StableNew/tests/review/test_metadata_contract_schemas.py)
  so the documented schema identifiers, namespace keys, sidecar suffix, and
  precedence values stay aligned with runtime constants

## Outcomes

- StableNew now has one active source of truth for metadata field names,
  precedence rules, and payload semantics
- external consumers have stable machine-readable examples for the metadata
  families currently in use
- the review portability and inspector work from PR-LEARN-261 through 263 now
  has an explicit contract layer instead of relying on implementation reading
- docs and tests now guard against immediate schema drift

## Guardrails Preserved

- no alternate runtime, queue, or execution path was introduced
- no GUI surface was given raw metadata ownership
- the new schema companions document current repo truth rather than inventing a
  new runtime format
- low-level image carrier details remain in the dedicated image metadata addendum

## Verification

- `c:/Users/rob/projects/StableNew/.venv/Scripts/python.exe -m pytest tests/review/test_metadata_contract_schemas.py tests/review/test_review_metadata_service.py tests/review/test_artifact_metadata_inspector.py -q`