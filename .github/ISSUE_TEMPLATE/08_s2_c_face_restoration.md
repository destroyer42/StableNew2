---
name: "S2-C Face restoration (GFPGAN/CodeFormer)"
about: "Optional face restoration with tunable weights"
title: "S2-C Face restoration (GFPGAN/CodeFormer): "
labels: [sprint-2, feature, postprocess, tdd]
assignees: ""
---


## Goal
Add optional face restoration stage (GFPGAN/CodeFormer) with numeric weights/strengths.

## DoD
- Checkbox reveals method + numeric controls.
- Post-process integrates cooperatively with CancelToken.
- Config persists across sessions.

## Tasks
- [ ] UI controls show/hide.
- [ ] Executor stage integration + cancel hooks.
- [ ] Config schema + defaults.
- [ ] Unit + integration tests.

## Test commands
```
pytest -k "face or postprocess" -q
```
