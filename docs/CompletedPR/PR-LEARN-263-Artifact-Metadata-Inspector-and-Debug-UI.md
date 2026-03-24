# PR-LEARN-263 - Artifact Metadata Inspector and Debug UI

Status: Completed 2026-03-23

## Summary

Added a read-only artifact metadata inspector so operators can directly inspect
what generation metadata, portable review metadata, and internal-review
precedence signals StableNew is using for a selected artifact.

## Delivered

- added [src/review/artifact_metadata_inspector.py](c:/Users/rob/projects/StableNew/src/review/artifact_metadata_inspector.py)
  with a reusable inspection service that aggregates:
  - normalized generation metadata
  - normalized review metadata
  - source diagnostics and precedence
  - raw embedded, sidecar, and internal-review payloads
- added [src/gui/artifact_metadata_inspector_dialog.py](c:/Users/rob/projects/StableNew/src/gui/artifact_metadata_inspector_dialog.py)
  with a read-only modal inspector that provides:
  - normalized summary tab
  - generation metadata tab
  - portable review metadata tab
  - source diagnostics tab
  - raw payload tab
  - copy normalized summary and raw JSON actions
  - refresh action
- extended [src/gui/controllers/learning_controller.py](c:/Users/rob/projects/StableNew/src/gui/controllers/learning_controller.py)
  with `inspect_artifact_metadata(...)` as the explicit controller entrypoint
  used by GUI launch points
- extended [src/gui/views/review_tab_frame_v2.py](c:/Users/rob/projects/StableNew/src/gui/views/review_tab_frame_v2.py)
  with an `Inspect Metadata` launch action for the selected Review artifact
- extended [src/gui/views/learning_tab_frame_v2.py](c:/Users/rob/projects/StableNew/src/gui/views/learning_tab_frame_v2.py)
  with an `Inspect Metadata` launch action for the selected staged-curation
  candidate
- exported the new review inspector types from [src/review/__init__.py](c:/Users/rob/projects/StableNew/src/review/__init__.py)
- added focused coverage in:
  - [tests/review/test_artifact_metadata_inspector.py](c:/Users/rob/projects/StableNew/tests/review/test_artifact_metadata_inspector.py)
  - [tests/gui_v2/test_artifact_metadata_inspector_dialog.py](c:/Users/rob/projects/StableNew/tests/gui_v2/test_artifact_metadata_inspector_dialog.py)
  - [tests/gui_v2/test_reprocess_panel_v2.py](c:/Users/rob/projects/StableNew/tests/gui_v2/test_reprocess_panel_v2.py)
  - [tests/gui_v2/test_learning_tab_state_persistence.py](c:/Users/rob/projects/StableNew/tests/gui_v2/test_learning_tab_state_persistence.py)

## Outcomes

- operators can now directly verify whether an artifact still has embedded
  generation metadata
- operators can see whether prior review context came from internal records,
  embedded portable metadata, or a sidecar
- metadata debugging no longer requires guessing which source StableNew used or
  why a prompt/config was rehydrated a certain way
- the preceding 261 and 262 portability work is now directly inspectable in the
  product

## Guardrails Preserved

- the inspector is read-only
- no new editing or execution path was introduced
- GUI launch points delegate inspection payload construction to controller and
  review-service layers
- raw payload access exists for debugging without replacing the normalized view

## Verification

- `c:/Users/rob/projects/StableNew/.venv/Scripts/python.exe -m pytest tests/review/test_artifact_metadata_inspector.py tests/gui_v2/test_artifact_metadata_inspector_dialog.py tests/gui_v2/test_reprocess_panel_v2.py tests/gui_v2/test_learning_tab_state_persistence.py -q`