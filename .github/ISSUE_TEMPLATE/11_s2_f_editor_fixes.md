---
name: "S2-F Advanced Prompt Editor fixes"
about: "status_text, name prefix, angle brackets, global negative, Save-all overwrite"
title: "S2-F Advanced Prompt Editor fixes: "
labels: [sprint-2, editor, bugfix, tdd]
assignees: ""
---


## Goal
Fix editor regressions and add filename prefixing from `name:` metadata.

## DoD
- `status_text` exists at init; single helper updates it; no crashes.
- Angle brackets in prompts tolerated (warnings not crashes).
- Pack Name field populates on load; buttons/labels fit text.
- Global negative default is visible and **saves**.
- Save-all: overwrite existing or create new via combo + overwrite checkbox.
- Filenames include `name:` prefix across save paths.

## Tasks
- [ ] Init status label; centralize updates.
- [ ] Tolerant validation for `<embedding:...>` / `<lora:...>`.
- [ ] Populate name field on load; fix sizing.
- [ ] Implement prefix helper; apply in txt2img/img2img/ADetailer/upscale.
- [ ] Tests in `tests/editor/test_advanced_prompt_editor_regressions.py`.

## Test commands
```
pytest tests/editor/test_advanced_prompt_editor_regressions.py -q
```
