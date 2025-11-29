---
name: "S1-D APIStatusPanel & LogPanel"
about: "Extract APIStatusPanel and LogPanel; attach logging handler"
title: "S1-D APIStatusPanel & LogPanel: "
labels: [sprint-1, gui, refactor, tdd]
assignees: ""
---


## Goal
Add `APIStatusPanel` (`set_status(text, color)`) and `LogPanel` (`log(msg)`), plus a logging.Handler that writes to LogPanel.

## DoD
- Panels importable and instantiated in isolation.
- Logging handler writes to widget; scroll behavior correct.
- Unit tests pass.

## Tasks
- [ ] Implement `src/gui/api_status_panel.py`.
- [ ] Implement `src/gui/log_panel.py` + handler.
- [ ] Tests: `tests/gui/test_api_status_panel.py`, `tests/gui/test_log_panel.py`.

## Test commands
```
pytest tests/gui/test_api_status_panel.py -q
pytest tests/gui/test_log_panel.py -q
```
