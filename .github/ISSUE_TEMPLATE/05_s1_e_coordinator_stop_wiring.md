---
name: "S1-E Coordinator wiring + real Stop"
about: "Wire StateManager/CancelToken into coordinator; ensure true Stop"
title: "S1-E Coordinator wiring + real Stop: "
labels: [sprint-1, gui, controller, tdd]
assignees: ""
---


## Goal
Connect coordinator (StableNewGUI) to `StateManager`, `PipelineController`, and a cooperative `CancelToken`. Implement a reliable **Stop**.

## DoD
- Start/Stop works at any stage without freezing Tk.
- Run-button disables during work; returns to Idle on completion/cancel/error.
- Status/progress updated via callbacks.
- GUI smoke tests pass.

## Tasks
- [ ] Create mediator in coordinator.
- [ ] Ensure background threads only; no blocking calls in mainloop.
- [ ] Implement Stop: signal cancel, terminate→kill subprocesses, cleanup.
- [ ] Add GUI smoke tests (headless).

## Test commands
```
pytest tests/gui -q
```
