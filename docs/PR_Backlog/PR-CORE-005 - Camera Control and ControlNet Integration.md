PR-CORE-005 - Camera Control and ControlNet Integration

Status: Specification
Priority: HIGH
Effort: MEDIUM
Phase: Post-Unification Core Refinement
Date: 2026-03-29

Context & Motivation

StableNew can generate short video clips via the SVD pipeline, but users cannot specify camera movements or inject depth/pose information into generation. The only motion control currently supported is through the secondary‑motion post‑process (using optical flow), which does not allow user control. Recent research and the PR proposals suggest integrating ControlNet to guide frames using depth or pose maps and enabling explicit camera paths. Implementing this feature will allow cinematic camera moves such as pans and zooms and improve scene composition. The code base lacks any support for ControlNet or camera path definitions; this PR introduces optional depth/pose inputs and camera motion parameters to the video pipeline.

Goals & Non‑Goals
Goal: Allow users to specify a camera motion path (e.g. pan left, zoom in) or provide a depth/pose map to guide video generation via ControlNet or similar conditioning.
Goal: Extend the SVD preprocessing and service layers to accept optional depth maps or pose data and pass them through to the generation backend (Comfy or Diffusers) using ControlNet nodes.
Goal: Update the UI to let users upload a depth map or select a preset camera motion for each video generation job.
Goal: Write tests to ensure that optional ControlNet inputs are passed to the pipeline correctly and do not break existing workflows when unspecified.
Non‑Goal: Do not build or train new ControlNet models. The integration should rely on existing ControlNet checkpoints and API support.
Non‑Goal: Do not replace the existing secondary‑motion postprocess; this feature is additive.
Guardrails
The feature must be optional; if users do not provide camera motion or depth maps, the pipeline should behave exactly as before.
ControlNet integration must be encapsulated; do not modify core SVD model code. Use the Diffusers or Comfy API for ControlNet conditioning when available.
Do not add new mandatory dependencies for all users; ControlNet functionality should be behind a feature flag or conditional import.
Allowed Files
Files to Create
src/video/camera_motion.py – defines data classes for camera motion parameters (e.g. trajectory type, duration) and functions to generate synthetic camera path curves if needed.
src/video/controlnet_adapter.py – wraps Diffusers/Comfy ControlNet modules, providing an interface to apply depth or pose conditioning to SVD frames.
Tests: tests/video/test_camera_motion.py and test_controlnet_adapter.py for unit testing motion definitions and ControlNet integration (with mocks).
Files to Modify
src/video/svd_config.py – extend SVDConfig and SVDPreprocessConfig to include optional camera_motion and controlnet fields (e.g. depth_map_path, pose_map_path).
src/video/svd_preprocess.py – read the optional depth/pose maps from config and include them in the job payload.
src/video/svd_service.py – when ControlNet configuration is present, pass the depth/pose to the underlying pipeline (Diffusers StableVideoDiffusionPipeline or Comfy nodes). Use the controlnet_adapter to apply conditioning.
src/pipeline/job_models_v2.py – allow job definitions to include camera_motion and controlnet entries.
src/gui/views/svd_tab_frame_v2.py – add UI controls to upload a depth map image or choose a preset camera path; propagate these options into the job config.
Forbidden Files
Do not remove or alter secondary_motion post‑process code; this PR is additive.
Do not alter high‑level pipeline orchestration (runner/queue) beyond passing new fields.
Implementation Plan
Camera motion representation: Define a CameraMotion dataclass with attributes like path_type (pan, zoom, tilt), duration, and parameters (e.g. direction, magnitude). Provide helper functions in camera_motion.py to generate interpolation curves over frames if needed.
ControlNet adapter: Implement controlnet_adapter.py to abstract away model specifics. For Diffusers, call StableVideoDiffusionPipeline(controlnet=depth_model) with appropriate conditioning. For Comfy, build a node graph referencing the ControlNet nodes. If ControlNet is unavailable, raise a descriptive error.
Config & job model: Extend SVDConfig to include optional camera_motion (serialized CameraMotion or null) and controlnet (dictionary with keys like type and map_path). Update job_models_v2.py and config_contract_v26.py accordingly.
SVD service updates: In svd_preprocess.py, load depth or pose maps from disk and include them in the payload. In svd_service.py, when controlnet is present, call the adapter to set up ControlNet conditioning prior to inference. For camera motion, adjust frame times or step prompts accordingly (e.g. apply dynamic cropping or transformation if supported by backend).
UI integration: Add file picker for depth map / pose map and a dropdown for camera path in svd_tab_frame_v2.py. Persist selections in the form data and include them in the job submission.
Tests: Unit tests for camera_motion.py verify parameter validation and curve generation. Tests for controlnet_adapter.py use mocks to assert that depth maps are passed into pipeline calls. Integration tests mock the SVD pipeline to ensure that specifying a depth map results in proper call signature. GUI tests ensure new controls appear and are serialized into the config.
Manual validation: Use a known depth map with a simple prompt to verify that ControlNet produces a depth‑guided video. Test camera paths by generating a clip with a pan motion and visually confirm motion.
Testing Plan
Unit tests for new modules (camera_motion, controlnet_adapter) using dummy inputs and mocks.
Integration tests for svd_service.py to ensure depth/pose maps are forwarded to the pipeline when provided and ignored otherwise.
GUI tests to verify that the UI collects camera and depth options and serializes them into job configs.
Manual experiments to evaluate qualitative improvement in camera motion and depth‑guided outputs.
Verification Criteria
When a depth map or pose map is provided, the SVD pipeline uses ControlNet conditioning to guide video generation without errors.
When a camera motion path is specified, the resulting video exhibits the expected motion (e.g. pan left). When no motion is provided, behaviour is unchanged.
The UI shows new controls for depth/pose upload and camera path selection, and existing options remain functional.
All new tests pass.
Risk Assessment
High Risk: Integrating ControlNet introduces new dependencies and may require large models. Mitigate by making it optional and failing gracefully when not available.
Medium Risk: Incorrect parameter passing could break the SVD pipeline. Mitigate with thorough unit tests and mocks.
Low Risk: UI modifications are straightforward but must not clutter the interface. Provide sensible defaults and tooltips.
Tech Debt Analysis

This PR adds camera and ControlNet support but does not address advanced editing of motion curves or integration with multi‑scene stitching. Future PRs may refine user‑defined camera paths and unify motion handling across different backends.

Documentation Updates

Add documentation for new SVD parameters (camera_motion, controlnet) and update the video generation section to explain how to supply depth maps or choose camera motions. Document any environment setup required for ControlNet models.

Dependencies

Depends on external ControlNet model weights. These must be downloaded separately and referenced in configuration. Internally, depends on the SVD service and Diffusers/Comfy support for ControlNet.

Approval & Execution

Planner: agent
Executor: TBD
Reviewer: @ml-team, @video-team
Approval Status: Pending

Next Steps

Once camera control is available, integrate it with the scene planner so each scene can specify an appropriate camera motion. Investigate automatic depth map estimation from input images for users who do not supply depth maps (future work).

