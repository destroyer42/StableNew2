# PR-UNIFY-201A: Docs Root Hygiene and Canonical Folder Layout

## Status

Completed on 2026-03-18.

## Purpose

Clean `docs/` root so it contains only canonical active documents, while moving
non-canonical material into explicit backlog, completed-record, or archive
locations.

## What Changed

- retained only canonical active docs in `docs/` root
- moved active backlog-driving docs into `docs/PR_Backlog/`
- moved the completed docs reset record into `docs/CompletedPR/`
- moved discovery notes, superseded summaries, reference analyses, diagrams, and
  stray prompt-example artifacts into `docs/archive/`
- rewrote archived high-value-but-stale Comfy and architecture notes so they now
  point back to current canon instead of competing with it

## Canonical Layout Rule

- `docs/` root: canonical active docs only
- `docs/PR_Backlog/`: active and historical backlog / draft PR materials
- `docs/CompletedPR/`: completed PR records
- `docs/archive/`: discovery, historical, superseded, reference-only material

## Verification

- verified `docs/` root now contains only the canonical keep-list
- updated `README.md` and `docs/DOCS_INDEX_v2.6.md` to the new paths
- `pytest --collect-only -q` remains `2334 collected / 1 skipped`

## Follow-On

The next runtime migration PR remains:

1. `PR-NJR-202-Queue-Only-Submission-Contract`
