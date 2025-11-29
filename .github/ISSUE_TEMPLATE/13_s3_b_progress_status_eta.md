---
name: "S3-B Progress/status/ETA polish"
about: "Visible status bar + per-stage progress + ETA"
title: "S3-B Progress/status/ETA polish: "
labels: [sprint-3, ux, polish]
assignees: ""
---


## Goal
Add top status bar, per-stage progress, elapsed and ETA using controller callbacks.

## DoD
- Progress/ETA visible during all stages; updates smoothly.
- Cancel transitions status to Idle with clean message.
- Tests updated for progress callbacks (mocked time).

## Tasks
- [ ] Status bar view-model binding.
- [ ] Progress callback wiring in controller → GUI.
- [ ] Tests: simulate multi-stage run; assert progress updates.

## Test commands
```
pytest -k "progress or eta" -q
```
