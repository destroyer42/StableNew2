# PR-UX-276 - Prompt and LoRA Row Usability Sweep

Status: Completed 2026-03-26

## Summary

This PR makes the Prompt tab resize behavior explicit and keeps LoRA controls
usable when prompt-side panels get narrow.

It adds a shared three-column width contract for the Prompt workspace, gives the
LoRA and embedding picker row area a minimum height and width baseline, and
reworks the LoRA picker into a deterministic grid layout so long names do not
crowd out the slider, exact-value entry, or action buttons.

## Delivered

- expanded `src/gui/view_contracts/prompt_editor_contract.py` with shared Prompt
  tab column minimums and picker row minimums
- moved `PromptTabFrame` onto the shared Prompt tab width contract instead of
  relying on bare weighted columns
- added explicit minimum widths for the prompt-side LoRA and embedding picker
  columns plus a minimum height for the picker row
- rewired `LoRAPickerPanel` header, add row, scroll container, and entry rows to
  deterministic grid layouts
- added a control-row minimum width so long LoRA names no longer crowd out the
  slider/value entry and action buttons
- added focused GUI regressions for the Prompt tab layout contract and the LoRA
  picker control-row behavior

## Key Files

- `src/gui/view_contracts/prompt_editor_contract.py`
- `src/gui/views/prompt_tab_frame_v2.py`
- `src/gui/widgets/lora_picker_panel.py`
- `tests/gui_v2/test_prompt_tab_layout_v2.py`
- `tests/gui_v2/test_lora_picker_panel_v2.py`

## Validation

Focused validation run:

`c:/Users/rob/projects/StableNew/.venv/Scripts/python.exe -m pytest tests/gui_v2/test_lora_picker_panel_v2.py tests/gui_v2/test_prompt_optimizer_prompt_tab_v2.py tests/gui_v2/test_prompt_tab_layout_v2.py -q`

Result:

- `4 passed, 1 skipped in 1.40s`

## Notes

- pre-existing Tk typing diagnostics remain in `prompt_tab_frame_v2.py` and are
  outside this PR scope
- the next canonical UX PR is
  `PR-UX-277-Review-Learning-and-Video-Panel-Consistency-Sweep`