PR-081D-5 — Journey Harness Glue: start_run Compatibility + Future Refiner/Hires/ADetailer Sequencing Tests

Intent
Restore journey-level pipeline testing by reintroducing the start_run() orchestration entrypoint expected by all JT03/JT04/JT05/journey tests, and connect it to the new V2 run flow.

This PR:

Part A — Implement compatibility shim

Introduces AppController.start_run() as a thin wrapper calling the canonical V2 run path.

Reconnects GUI V2 run controls to the journey harness.

Part B — Prepare & validate journey harness

Ensures PipelineTabFrame V2 exposes required attributes used in journey tests (txt2img_width, img2img_strength, etc.).

Ensures lifecycle transitions: IDLE → RUNNING → IDLE.

Part C — (Separate) Skeleton tests for refiner/hires/ADetailer sequencing

Sequencing implementation is NOT included here.
This PR only provides the test scaffolding and expected signatures, leaving implementation to PR-081E or a follow-on.

Scope & Risk

Risk: High

Subsystems: GUI V2 run controls → AppController → PipelineRunner

Strict separation from executor/pipeline sequencing logic

Requires stability of PR-081D-1..4 first

Allowed Files
src/controller/app_controller.py
src/gui/views/pipeline_tab_frame_v2.py
src/gui/panels_v2/pipeline_run_controls_v2.py
src/gui/app_state_v2.py
tests/journeys/*.py
tests/controller/test_app_controller_pipeline_flow_pr0.py
tests/controller/test_app_controller_pipeline_integration.py

Forbidden Files

(No sequencing changes allowed here)

src/pipeline/executor.py
src/pipeline/stage_sequencer.py
src/pipeline/run_plan.py
src/pipeline/pipeline_runner.py   (except minimal lifecycle glue)

Implementation Plan
Part A — Reintroduce AppController.start_run() compatibility
1. Add method to AppController
def start_run(self):
    """Compatibility shim for journey tests."""
    config = self.get_current_config()
    return self.queue_execution_controller.run_once(config)


This forwards the run request through the V2 queue/runner system.

2. Update stop behavior

Ensure:

self.stop_run() → sets cancel token → pipeline runner stops → state returns to IDLE

3. Make GUI V2 run controls call this shim

In pipeline_run_controls_v2.py:

self.controller.start_run()


instead of legacy per-stage logic.

Part B — Journey Harness Alignment
4. Expose required stage attributes on PipelineTabFrameV2

Tests expect attributes such as:

txt2img_width

txt2img_height

img2img_strength

upscale_scale

Implement them as properties forwarding to stage cards:

@property
def txt2img_width(self):
    return self.txt2img_card.width_slider.get()

5. Ensure predictable lifecycle transitions

Tests expect:

Initial: LifecycleState.IDLE

After run start: RUNNING

After run completes: IDLE

After error: ERROR → IDLE

After cancellation: RUNNING → IDLE

Update AppController lifecycle setters if needed.

6. Update journey tests to use Pipeline tab (not Run tab)

Adjust:

gui.run_tab


→

gui.pipeline_tab

Part C — Create sequencing test stubs for refiner/hires/ADetailer

This PR creates tests but does not implement sequencing.

Add tests in:

tests/journeys/test_v2_refiner_hires_adetailer_sequence.py


That assert:

pipeline.sequence == ["txt2img", "img2img?", "adetailer?", "refiner?", "upscale"]


But mark them:

@pytest.mark.xfail(reason="Sequencing logic to be implemented in PR-081E")


This allows the journey harness to pass now while preparing for PR-081E.

Acceptance Criteria
✔ All journey tests passing for:

JT03 txt2img

JT04 img2img + ADetailer

JT05 upscale

Full pipeline V2 run

Pipeline flow PR0 tests

Controller→Pipeline integration tests

✔ GUI V2 run controls correctly invoke pipeline runs
✔ Lifecycle transitions correct
✔ start_run() restored without reintroducing V1 logic
✔ Sequencing tests added but xfail’d
Validation Checklist

No sequencing logic added

No executor changes

New start_run() function is thin wrapper only

GUI V2 entrypoint validated

All journey tests (except sequencing xfails) green

PipelineTabFrame V2 exposes attributes needed by tests

🚀 Deliverables

Working journey harness

Restored start_run() for backward compatibility

Updated GUI run controls

Updated journey tests

Skeleton sequencing tests (xfail)

100% green journey suite