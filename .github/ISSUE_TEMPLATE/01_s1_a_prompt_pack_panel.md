---
name: "S1-A PromptPackPanel"
about: "Implement PromptPackPanel with mediator callbacks"
title: "S1-A PromptPackPanel: "
labels: [sprint-1, gui, refactor, tdd]
assignees: ""
---


## Goal
Extract `PromptPackPanel` from `main_window.py`, emitting mediator callback `report_pack_selection_changed(list[str])`.

## Definition of Done
- Panel renders pack list, supports refresh and selection.
- Selection changes call mediator with selected pack names/ids.
- Unit tests in `tests/gui/test_prompt_pack_panel.py` pass.

## Tasks
- [ ] Create `src/gui/prompt_pack_panel.py` (class `PromptPackPanel`).
- [ ] Wire list population, selection binding, mediator callback.
- [ ] Add type hints/docstrings.
- [ ] Tests: instantiate, refresh, selection → mediator spy.

## Test commands
```
pytest tests/gui/test_prompt_pack_panel.py -q
pre-commit run --all-files
```
