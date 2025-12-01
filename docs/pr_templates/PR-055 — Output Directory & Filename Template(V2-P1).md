PR-055 — Output Directory & Filename Template(V2-P1).md
Summary

Users need explicit control over output destination and filename format. The current controls are placeholders and do not influence pipeline outputs. This PR wires these fields into AppState and ultimately into the pipeline config/payload.

Goals

Editable output directory with folder chooser.

Editable filename template with token support.

Tokens: {date}, {time}, {seed}, {prompt_index}, {pack_name}, {stage_name}

Values must reach the pipeline runner config.

Allowed Files

src/gui/views/pipeline_tab_frame_v2.py

src/gui/app_state_v2.py

src/config/app_config.py

src/controller/pipeline_controller.py

src/utils/path_utils.py (optional helper)

Forbidden Files

Executor or runner internals

Main entrypoint

Implementation Plan
1. Output directory field

Add text entry + “Browse” button.

Store result in app_state.output_dir.

2. Filename template

Entry field allowing tokens:

image-{date}-{time}-{seed}.png


Validate tokens but allow unknown tokens (pass through).

3. Pipeline config wiring

Add fields:

config["output_dir"]
config["filename_template"]


Pipeline runner will use these as-is (no executor changes).

4. Utilities

Optional helper for token expansion (e.g., in preview mode only).

Validation
Tests

tests/controller/test_pipeline_output_controls_v2.py

Assert config includes correct dir + template.

tests/gui_v2/test_pipeline_output_controls_gui.py

File chooser updates app_state.

Definition of Done

Output directory works.

Filename template works.

Pipeline config carries both fields.

