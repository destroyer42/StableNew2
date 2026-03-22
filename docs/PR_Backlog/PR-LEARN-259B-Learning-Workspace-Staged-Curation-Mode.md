# PR-LEARN-259B - Learning Workspace Staged Curation Mode

Status: Completed 2026-03-21

## Summary

Add a first-class `Staged Curation` mode inside the existing Learning workspace.

## Goals

- avoid adding a separate competing workspace
- let users review and advance candidates quickly
- capture reason tags and advancement decisions inline

## Scope

Extend:

- `src/gui/views/learning_tab_frame_v2.py`
- Learning controller/state projection surfaces

Implement:

- staged curation mode in the Learning notebook
- candidate grid
- advancement controls
- reason-tag controls

## Guardrails

- `Review` remains the canonical advanced reprocess surface
- no standalone curation tab unless later proven necessary

## Success Criteria

- staged curation is reachable from Learning
- user can advance/reject candidates quickly
- selection events are routed into canonical persistence
