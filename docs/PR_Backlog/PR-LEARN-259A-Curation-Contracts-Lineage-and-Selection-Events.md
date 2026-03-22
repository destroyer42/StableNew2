# PR-LEARN-259A - Curation Contracts, Lineage, and Selection Events

Status: Proposed

## Summary

Establish the canonical staged-curation contract before adding new UI behavior.

## Goals

- define the StableNew-owned curation objects
- persist candidate lineage in manifests/history
- persist user advancement behavior as first-class events
- preserve replay safety

## Scope

Add:

- `src/curation/models.py`
- `src/curation/curation_manifest.py`

Implement:

- `CurationWorkflow`
- `CurationCandidate`
- `SelectionEvent`
- `CurationOutcome`
- canonical manifest/history blocks for lineage and advancement

## Guardrails

- no runtime behavior changes yet
- no new outer job model
- no GUI-owned truth

## Success Criteria

- canonical staged-curation contract exists
- lineage schema exists
- selection events are replay-safe
