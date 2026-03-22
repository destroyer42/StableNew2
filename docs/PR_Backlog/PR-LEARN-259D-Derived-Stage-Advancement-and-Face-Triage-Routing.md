# PR-LEARN-259D - Derived Stage Advancement and Face Triage Routing

Status: Proposed

## Summary

Compile staged advancement into normal NJR-backed jobs for refine, face triage,
and upscale.

## Goals

- preserve queue-first architecture
- derive later-stage jobs only for selected candidates
- support optional face-triage tiers instead of blanket ADetailer

## Scope

Add:

- curation workflow builder/service helpers

Implement:

- scout -> refine derivation
- refine -> face-triage derivation
- finalist -> upscale derivation
- per-candidate face-triage tier selection

## Success Criteria

- all staged work remains NJR-backed
- expensive stages run only for selected candidates
