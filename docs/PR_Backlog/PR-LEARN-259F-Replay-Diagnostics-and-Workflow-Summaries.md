# PR-LEARN-259F - Replay, Diagnostics, and Workflow Summaries for Staged Curation

Status: Proposed

## Summary

Make staged curation auditable, replayable, and diagnosable.

## Goals

- reconstruct workflow lineage
- show stage transitions and decision summaries
- localize failures by candidate and stage

## Scope

Extend:

- replay/history surfaces
- diagnostics bundle summaries

Implement:

- workflow summary
- candidate lineage display
- selection-event summaries
- replay chain reconstruction

## Success Criteria

- staged curation can be inspected and replayed
- failures can be localized by stage and candidate
