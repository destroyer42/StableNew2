---
name: "S1-B PipelineControlsPanel"
about: "Implement PipelineControlsPanel with get_settings()"
title: "S1-B PipelineControlsPanel: "
labels: [sprint-1, gui, refactor, tdd]
assignees: ""
---


## Goal
Extract `PipelineControlsPanel` exposing `get_settings()` for controller.

## Definition of Done
- Panel encapsulates toggles/loop/batch fields.
- `get_settings()` returns a typed dict used by executor.
- Unit tests pass.

## Tasks
- [ ] Create `src/gui/pipeline_controls_panel.py`.
- [ ] Implement state via `BooleanVar`/`StringVar`.
- [ ] Provide `get_settings()`; no magic strings.
- [ ] Tests in `tests/gui/test_pipeline_controls_panel.py`.

## Test commands
```
pytest tests/gui/test_pipeline_controls_panel.py -q
```
