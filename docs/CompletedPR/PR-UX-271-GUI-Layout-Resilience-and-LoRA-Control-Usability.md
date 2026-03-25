# PR-UX-271 - GUI Layout Resilience and LoRA Control Usability

Status: Completed 2026-03-25
Priority: HIGH
Effort: MEDIUM
Phase: Immediate UX Help Sweep

## Summary

Improved the most fragile GUI layout surfaces so base-generation controls keep
usable minimum widths, long LoRA names no longer crowd out adjacent controls,
and LoRA strengths support exact numeric entry alongside slider adjustment.

## Delivered

- added minimum-width layout rules for the shared base-generation grid so label,
  primary-control, and secondary-control columns resize more predictably
- reflowed shared sampler, scheduler, steps, CFG, seed, subseed, and subseed
  strength rows to reduce crowding under narrower window widths
- redesigned Prompt-tab LoRA entries into separate name and controls rows so
  long names no longer hide the slider, keywords action, or remove button
- reused the shared enhanced slider pattern to provide exact-entry LoRA weight
  editing in both Prompt-tab LoRA rows and Pipeline runtime LoRA controls
- exposed runtime LoRA controls in `PipelinePanelV2` through the existing
  controller API so enable/disable and exact-strength updates are test-covered
- aligned the runtime LoRA test with the shared `tk_root` fixture so focused GUI
  validation does not depend on direct local Tcl bootstrap behavior

## Key Files

- `src/gui/widgets/lora_picker_panel.py`
- `src/gui/base_generation_panel_v2.py`
- `src/gui/pipeline_panel_v2.py`
- `tests/gui_v2/test_lora_picker_panel_v2.py`
- `tests/gui_v2/test_pipeline_base_generation_ownership_v2.py`
- `tests/gui_v2/test_pipeline_config_panel_lora_runtime.py`

## Validation

- focused GUI slice:
  - `pytest tests/gui_v2/test_lora_picker_panel_v2.py tests/gui_v2/test_pipeline_base_generation_ownership_v2.py tests/gui_v2/test_pipeline_config_panel_lora_runtime.py tests/gui_v2/test_pipeline_layout_scroll_v2.py -q`
  - `15 passed, 2 skipped in 27.15s`

## Notes

- `src/gui/pipeline_panel_v2.py` still carries unrelated pre-existing type-check
  noise outside the new runtime LoRA surface, but the touched behavior compiles
  cleanly and the targeted GUI regression slice passes