---
name: "S2-A Hires steps"
about: "Add txt2img hires_steps and pass-through to executor"
title: "S2-A Hires steps: "
labels: [sprint-2, config, feature, tdd]
assignees: ""
---


## Goal
Add `hires_steps` to HR panel and thread through config → executor/API.

## DoD
- Spinbox present; integer validation; default sensible.
- Included in config schema and sent to API.
- Unit + integration tests pass.

## Tasks
- [ ] UI control + binding.
- [ ] Config schema update + defaults.
- [ ] Executor passthrough.
- [ ] Tests for validation and payload content.

## Test commands
```
pytest -k "config_panel or config" -q
```
