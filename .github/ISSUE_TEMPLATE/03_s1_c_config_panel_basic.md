---
name: "S1-C ConfigPanel (basic)"
about: "Extract Notebook tabs into ConfigPanel (no new features yet)"
title: "S1-C ConfigPanel (basic): "
labels: [sprint-1, gui, refactor, tdd]
assignees: ""
---


## Goal
Extract the configuration tabs from `main_window.py` into `ConfigPanel`.

## DoD
- Panel renders existing tabs/controls exactly as before.
- Coordinator can query/set values as before.
- Unit tests pass.

## Tasks
- [ ] Create `src/gui/config_panel.py` and move tab building here.
- [ ] Public methods: `get_values()`, `set_values(dict)`.
- [ ] Tests scaffold in `tests/gui/test_config_panel.py` (basic import + placeholder assertions).

## Test commands
```
pytest tests/gui/test_config_panel.py -q
```
