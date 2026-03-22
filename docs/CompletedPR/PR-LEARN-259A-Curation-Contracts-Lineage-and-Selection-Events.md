# PR-LEARN-259A - Curation Contracts, Lineage, and Selection Events

Status: Completed 2026-03-21

## Summary

Established the canonical staged-curation contract as a StableNew-owned package
without changing runtime behavior.

## Delivered

- added [models.py](/c:/Users/rob/projects/StableNew/src/curation/models.py)
- added [curation_manifest.py](/c:/Users/rob/projects/StableNew/src/curation/curation_manifest.py)
- added [__init__.py](/c:/Users/rob/projects/StableNew/src/curation/__init__.py)
- added focused model and manifest coverage under:
  - [test_models.py](/c:/Users/rob/projects/StableNew/tests/curation/test_models.py)
  - [test_curation_manifest.py](/c:/Users/rob/projects/StableNew/tests/curation/test_curation_manifest.py)

## Outcomes

- canonical `CurationWorkflow`, `CurationCandidate`, `SelectionEvent`,
  `RefineProfile`, `FaceTriageProfile`, and `CurationOutcome` contracts exist
- canonical schema helpers now exist for:
  - `stablenew.curation.v2.6`
  - `stablenew.selection_event.v2.6`
  - `stablenew.curation_outcome.v2.6`
- replay-safe staged-curation lineage blocks now have one StableNew-owned source

## Notes

- this PR intentionally does not add runtime behavior, GUI surfaces, or queue
  derivation yet
- it establishes the contract boundary for the rest of the staged-curation
  Learning tranche

## Verification

- `pytest tests/state/test_output_routing.py tests/pipeline/test_output_folder_structure.py tests/curation/test_models.py tests/curation/test_curation_manifest.py -q`
- `python -m compileall src/state/output_routing.py src/curation tests/state/test_output_routing.py tests/pipeline/test_output_folder_structure.py tests/curation`
