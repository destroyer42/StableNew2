# PR-LEARN-260D - Review Derived Config Inspector and Effective Settings Summary

Status: Completed 2026-03-23

## Summary

Added an Effective Reprocess Settings inspector to the canonical Review workspace
so operators can see the merged queue-bound config before submitting a reprocess
job.

## Delivered

- extended [reprocess_builder.py](/c:/Users/rob/projects/StableNew/src/pipeline/reprocess_builder.py)
  with typed preview contracts and a deterministic helper that mirrors the
  effective config merge used by the reprocess builder
- extended [app_controller.py](/c:/Users/rob/projects/StableNew/src/controller/app_controller.py)
  with `get_review_reprocess_effective_settings_preview(...)` so Review can ask
  the controller for the exact submit-time preview
- extended [review_workflow_adapter.py](/c:/Users/rob/projects/StableNew/src/gui/controllers/review_workflow_adapter.py)
  with formatter logic for the new inspector and optional staged-curation direct
  queue baseline display
- extended [review_tab_frame_v2.py](/c:/Users/rob/projects/StableNew/src/gui/views/review_tab_frame_v2.py)
  with an `Effective Reprocess Settings` surface that refreshes from:
  - selected image
  - target-stage toggles
  - prompt mode changes
  - prompt delta edits
  - staged-curation handoff preload
- added focused coverage in:
  - [test_reprocess_builder_defaults.py](/c:/Users/rob/projects/StableNew/tests/pipeline/test_reprocess_builder_defaults.py)
  - [test_reprocess_panel_v2.py](/c:/Users/rob/projects/StableNew/tests/gui_v2/test_reprocess_panel_v2.py)
  - [test_review_tab_prompt_modes.py](/c:/Users/rob/projects/StableNew/tests/gui_v2/test_review_tab_prompt_modes.py)

## Outcomes

- Review now shows the source stage/model/vae, effective target stages, prompt
  inheritance mode, and stage-specific sampler/scheduler/steps/cfg/denoise
  before queue submission
- when Review is opened from staged curation, the inspector also shows the
  direct `Queue Now` baseline so operators can compare the bulk path against the
  editable Review path
- the preview uses the same merge logic as the queue-bound reprocess builder,
  rather than duplicating config resolution in the GUI

## Guardrails Preserved

- no new execution path was introduced
- Review remains the canonical advanced manual-edit workspace
- queue submission still goes through the existing NJR-backed reprocess path
- GUI code remains event-driven and delegates effective-config resolution to the
  controller/pipeline layers

## Verification

- `python -m pytest tests/pipeline/test_reprocess_builder_defaults.py tests/gui_v2/test_reprocess_panel_v2.py tests/gui_v2/test_review_tab_prompt_modes.py -q`
