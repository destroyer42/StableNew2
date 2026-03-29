# PR-EDIT-077: Image Edit Foundation via Reprocess and img2img

## Goal

Treat canvas/object editing as a structured extension of the canonical reprocess and
artifact contracts rather than a one-off feature path.

## Scope

- Introduce an explicit image-edit spec for reprocess source items.
- Preserve masked-edit provenance in NJR metadata.
- Make `img2img` honor mask/inpaint payload fields when those edits are submitted.
- Add a controller entrypoint for masked image edits through the queue-first NJR path.

## What This PR Does

### Reprocess Builder

- Adds `ImageEditSpec` with schema `stablenew.image_edit.v2.6`.
- Allows each `ReprocessSourceItem` to carry a masked-edit spec.
- Applies masked-edit settings into the canonical `img2img` stage config.
- Persists per-item edit provenance under `extra_metadata["reprocess"]["source_items"]`.

### Controller

- Adds `AppController.on_submit_image_edits(...)`.
- Uses the existing metadata baseline and prompt-delta logic.
- Submits masked edits through `ReprocessJobBuilder` and `JobService.enqueue_njrs()`.
- Uses `source="image_edit"` and records structured image-edit metadata.

### Executor

- `run_img2img_stage()` now supports:
  - `mask_image_path`
  - `mask_blur`
  - `inpaint_full_res`
  - `inpaint_full_res_padding`
  - `inpainting_fill`
  - `inpainting_mask_invert`
- These are passed to the WebUI img2img payload only when a mask is present.

## Deliberate Non-Goals

- No canvas widget or paint UI.
- No separate editor runner.
- No queue/history schema redesign.
- No object-selection logic.

## Why This Shape

The canonical runtime already knows how to:

1. take existing artifacts,
2. build NJRs for follow-on work,
3. run `img2img`,
4. persist artifact history.

Masked editing belongs on top of that path. Future GUI work can be a thin producer of
`ImageEditSpec` data without inventing a parallel execution architecture.

## Tests

- `tests/pipeline/test_reprocess_builder_defaults.py`
- `tests/controller/test_app_controller_reprocess_review_tab.py`
- `tests/pipeline/test_img2img_masked_edit_runtime.py`
