# PR-UX-274 - Shared Layout Minimums and Resize Discipline

Status: Completed 2026-03-26

## Summary

This PR establishes a reusable layout baseline for dense pipeline forms instead
of leaving minimum-width and column-weight behavior embedded inside individual
panels.

It promotes shared form-column sizing rules into the pipeline layout contract,
adds a Tk layout adapter for applying those rules, and rewires the highest-value
 stage-card and base-generation surfaces onto that shared path.

## Delivered

- expanded `src/gui/view_contracts/pipeline_layout_contract.py` with shared form
  minimum-width constants and reusable column-spec helpers
- expanded `src/gui/layout_v2.py` with a generic `configure_grid_columns(...)`
  adapter so Tk surfaces can consume the shared contract directly
- moved base-generation form sizing off local constants and onto the shared
  three-pair form helper
- moved stage-card sampler/meta/upscale grids onto the shared two-pair form
  helper
- added a shared stage-card minimum width and applied it to the stage-card
  container plus the txt2img/img2img body surfaces
- added focused regressions for the new layout contract and stage-card minimum
  width behavior

## Key Files

- `src/gui/view_contracts/pipeline_layout_contract.py`
- `src/gui/layout_v2.py`
- `src/gui/base_generation_panel_v2.py`
- `src/gui/stage_cards_v2/components.py`
- `src/gui/views/stage_cards_panel_v2.py`

## Validation

Focused validation run:

`c:/Users/rob/projects/StableNew/.venv/Scripts/python.exe -m pytest tests/gui_v2/test_pipeline_view_contracts.py tests/gui_v2/test_zone_map_card_order_v2.py -q`

Result:

- `6 passed in 1.14s`

## Notes

- this PR intentionally establishes the shared layout baseline without trying to
  remediate every panel-specific resize issue in one sweep
- pre-existing Tk typing noise remains in older GUI modules and is outside this
  PR scope
- the next canonical UX PR is
  `PR-UX-275-Pipeline-and-Stage-Card-Resilience-Sweep`