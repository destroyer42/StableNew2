PR-054 — Dropdowns & Stage Config Wiring (V2-P1).md
Summary

Dropdowns are not wired to WebUI resources, ADetailer lacks resource-driven model/detector lists, width/height controls are clumsy, and seeds/randomization are not fully integrated. This PR connects GUI controls → AppState → PipelineConfig cleanly.

Goals

Populate dropdowns from WebUI resources.

Add ADetailer model/detector selectors.

Improve resolution selectors (common presets + manual entry).

Make seed/randomization work consistently across stages.

Ensure all selected values appear properly in pipeline payloads.

Allowed Files

Stage cards in src/gui/stage_cards_v2/*

src/gui/resolution_panel_v2.py

src/gui/app_state_v2.py

src/gui/controller.py

src/controller/pipeline_controller.py

Forbidden Files

src/api resource discovery logic (read-only usage only)

src/pipeline/executor.py

Implementation Plan
1. Dropdown population

Each stage card receives model/vae/sampler lists from app_state/resources.

2. ADetailer resource wiring

Add two dropdowns:

adetailer_model

adetailer_detector

3. Resolution controls

ResolutionPanelV2:

Add dropdowns: [512, 640, 768, 960, 1024]

Keep entry box editable.

4. Seed/randomization

Add “Randomize Seed” button per stage (shared method ok).

Update app_state and propagate to pipeline config.

5. Pipeline config integration

PipelineController.build_config() must include:

{
  "txt2img": {...},
  "img2img": {...},
  "upscale": {...},
  "adetailer": {
      "model": "...",
      "detector": "..."
  },
  "resolution": {...},
  "seed": <int>,
}

Validation
Tests

tests/controller/test_pipeline_controller_resource_dropdown_wiring.py

Fake resource lists → dropdown values → payload matches.

tests/gui_v2/test_stage_cards_resource_bindings.py

GUI selects values; controller sees correct state.

Definition of Done

All dropdowns populate correctly.

ADetailer has fully wired model/detector inputs.

Resolution selectors work.

Seeds/randomization integrated end-to-end.