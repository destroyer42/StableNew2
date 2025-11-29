---
name: "S2-D ADetailer stage"
about: "ADetailer as optional stage (alt to img2img) with full parameters"
title: "S2-D ADetailer stage: "
labels: [sprint-2, feature, stage, tdd]
assignees: ""
---


## Goal
Implement ADetailer as a selectable stage with: Model, Confidence, Mask/Feather, Sampler/Steps, Denoise, CFG, Pos/Neg prompts.

## DoD
- UI config present and serialized.
- Executor sends `alwayson_scripts` payload correctly.
- Cancel supported mid-stage.
- Tests: config validation + mocked API integration.

## Test commands
```
pytest -k "adetailer" -q
```
