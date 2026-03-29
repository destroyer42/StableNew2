# PR-CORE-004 - Cinematic Prompt Template Library

Status: Completed 2026-03-29

## Summary

PromptPack authoring had no curated cinematic template surface. This PR added a
repo-owned prompt-template catalog, strict template loading and interpolation
helpers, template-aware PromptPack JSON/TXT rendering, and a thin Prompt tab
selector/preview surface that preserves the existing NJR-only execution path.

## Delivered

- added the curated template catalog in `data/prompt_templates.json`
- added `src/utils/prompt_templates.py` for template loading, validation,
  placeholder extraction, and interpolation
- extended PromptPack slot persistence to carry `template_id` and
  `template_variables`
- rendered template-backed prompts through PromptPack JSON reads and TXT export
  so existing pack execution paths consume resolved prompt text without runtime
  changes
- added Prompt tab template selection, variable entry, and rendered preview
  while keeping the editor surface freeform and GUI-thin
- updated the canonical PromptPack lifecycle docs to describe template-backed
  authoring and template expansion before NJR construction

## Key Files

- `data/prompt_templates.json`
- `src/utils/prompt_templates.py`
- `src/gui/models/prompt_pack_model.py`
- `src/gui/prompt_workspace_state.py`
- `src/utils/file_io.py`
- `src/gui/views/prompt_tab_frame_v2.py`
- `tests/utils/test_prompt_templates.py`
- `tests/utils/test_prompt_packs.py`
- `tests/gui_v2/test_prompt_pack_model_matrix.py`
- `tests/gui_v2/test_prompt_tab_layout_v2.py`
- `docs/PROMPT_PACK_LIFECYCLE_v2.6.md`

## Validation

- `c:/Users/rob/projects/StableNew/.venv/Scripts/python.exe -m pytest tests/utils/test_prompt_templates.py tests/gui_v2/test_prompt_pack_model_matrix.py tests/utils/test_prompt_packs.py tests/gui_v2/test_prompt_tab_layout_v2.py -q`
- result: `35 passed in 0.93s`
- `c:/Users/rob/projects/StableNew/.venv/Scripts/python.exe -m pytest tests/gui_v2/test_prompt_optimizer_prompt_tab_v2.py tests/test_pr_gui_matrix_integration.py tests/journeys/test_jt01_prompt_pack_authoring.py -q`
- result: `18 passed, 1 skipped in 5.89s`

## Notes

- the repo-truth implementation uses `src/utils/prompt_templates.py` rather
  than the stale backlog spec's `src/services/prompt_templates.py`, because the
  feature belongs to the prompt-authoring and PromptPack serialization layer
- the next active CORE item is `PR-CORE-002 - Character Embedding Pipeline`