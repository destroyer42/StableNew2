PR-CORE-017 – ControlNet and Depth‑Map Support

Status: Specification
Priority: MEDIUM
Effort: MEDIUM
Phase: Post‑Unification Core Refinement
Date: 2026‑03‑29

Context & Motivation

While PR‑CORE‑005 introduces basic camera motion via optional depth or pose inputs, the full potential of ControlNet and depth maps remains untapped. Current SVD pipelines accept only a single depth or pose map and pass it through to the backend, but StableNew does not provide tools for generating, previewing, or managing these auxiliary inputs. External research shows that conditioning generative video models on depth maps can dramatically improve scene coherence and camera control. To leverage this, we must add first‑class support for depth maps and ControlNet parameters across the pipeline.

Goals & Non‑Goals
Goal: Add built‑in support for generating depth maps from input images using existing models (e.g. MiDaS or DPT). This allows users who lack depth data to create it on‑the‑fly.
Goal: Allow specifying ControlNet models and weights in the SVD config. Expose these parameters in the UI and pass them through the pipeline to the backend.
Goal: Extend the NJR schema to include multiple auxiliary inputs (e.g. depth, pose, scribbles) for a single video generation stage.
Goal: Provide a small preview of the depth map in the UI so users understand what is being used for conditioning.
Non‑Goal: Writing a custom depth or pose estimation model. We will rely on existing open‑source models for this purpose.
Guardrails
Model Usage: Depth map generation relies on third‑party models. Use them only in pre‑processing and ensure that their outputs are saved to disk for reproducibility. Do not send depth data to remote services.
Backward Compatibility: Users should still be able to run SVD jobs without ControlNet or depth maps. Auxiliary inputs must be optional and default to None.
Security: Validate any uploaded depth or pose files to prevent arbitrary file execution. Accept only image files (PNG, JPG) or numpy arrays saved via standard libraries.
Allowed Files
Files to Create
src/video/depth_map_generator.py – a module that wraps an off‑the‑shelf depth estimation model (e.g. MiDaS). It exposes a function generate_depth_map(image: PIL.Image) -> np.ndarray that returns a normalised depth map. Use a pre‑trained model from TorchHub or diffusers and include caching.
src/video/controlnet_adapter.py – define a simple interface to pass ControlNet inputs (depth or pose arrays) into the pipeline. Provide a function to convert a numpy array into a format accepted by the backend (e.g. save to PNG and store path).
tests/video/test_depth_map_generator.py – unit tests for depth map generation on a dummy image, verifying shape and value ranges.
tests/video/test_controlnet_adapter.py – unit tests verifying that ControlNet adapter saves the auxiliary input to the correct location and returns the expected metadata.
Files to Modify
src/video/svd_preprocess.py – add optional calls to depth_map_generator.generate_depth_map if the config specifies generate_depth_from_image=True. Save the generated depth map and embed its path in the aux_inputs field of the job config.
src/video/svd_service.py – update pipeline execution to include ControlNet inputs when present. When the job config contains auxiliary maps, load them and feed them into the ControlNet model attached to the video diffusion pipeline.
src/pipeline/config_contract_v26.py – extend the schema to include fields controlnet_model (str), controlnet_weight (float), depth_map_path (str), and generate_depth_from_image (bool).
src/gui/views/svd_tab_frame_v2.py – add UI elements to select a ControlNet model (dropdown), specify a weight, upload a depth/pose file, or toggle auto‑generation of depth. Add preview functionality using a thumbnail of the depth map.
src/pipeline/job_builder_v2.py – update the builder to merge ControlNet parameters into stage configs and to ensure they are included in the NJR.
Forbidden Files
Do not modify src/video/svd_postprocess.py as ControlNet operates in the inference phase, not post‑processing.
Implementation Plan
Depth Map Generation: Implement depth_map_generator.py using a state‑of‑the‑art depth estimation model. Load the model lazily to reduce initialisation time. Provide caching to avoid regenerating depth maps for the same image.
ControlNet Adapter: Define controlnet_adapter.py to accept a numpy array or file path and return a dictionary containing the path and any required metadata (e.g. "type": "depth"). Use this to unify how auxiliary inputs are passed to the backend.
Config Schema Updates: In config_contract_v26.py, add optional fields for controlnet_model, controlnet_weight, depth_map_path, pose_map_path, and generate_depth_from_image. Provide defaults (e.g. empty strings or None) and update validation logic accordingly.
Pre‑processing Changes: In svd_preprocess.py, if generate_depth_from_image=True, call the depth map generator on the input image and store the result via the ControlNet adapter. If depth_map_path is provided, validate the file and embed it directly into the job config.
Inference Integration: In svd_service.py, when building the diffusion pipeline, load the specified ControlNet model (e.g. from diffusers). Pass the auxiliary input (depth or pose) into the pipeline’s controlnet_conditioning argument. Include controlnet_weight in the call.
UI Enhancements: Modify SVDTabFrameV2 to add controls for enabling ControlNet, selecting a model (e.g. “depth”, “pose”), specifying a weight slider (0–1), uploading an auxiliary file, and a checkbox for auto‑generate depth. When a depth file is uploaded or generated, display a thumbnail to the user.
Testing: Write unit tests covering the depth map generator and ControlNet adapter. Write integration tests that build a dummy job with a generated depth map and verify that the job config includes the correct fields. Consider mocking the ControlNet model to avoid heavy computations during testing.
Documentation: Update the user guide to explain depth map generation, ControlNet models, and how to control their influence via weights. Provide examples illustrating improved scene coherence with ControlNet.
Testing Plan
Unit Tests: test_depth_map_generator.py and test_controlnet_adapter.py ensure that depth maps are generated and saved correctly.
Schema Tests: Validate that config updates with depth and ControlNet fields pass or fail appropriately when missing or invalid.
Integration Tests: Use a dummy backend to test that the ControlNet input is read and forwarded. Verify that the weight parameter affects the call to the model (e.g. by mocking a call count or weight multiplier).
Manual Verification: Generate a short video with and without depth maps and observe improvements in camera motion and depth consistency.
Verification Criteria
Depth map generation produces normalised arrays between 0 and 1 and caches results.
ControlNet parameters in the config are correctly propagated through NJR to the inference service.
The UI displays new controls and previews depth maps. Toggling generate_depth_from_image triggers generation.
Tests pass, and documentation is updated to reflect the new features.
Risk & Mitigation
Risk: Integrating new models (depth estimation, ControlNet) increases the size of dependencies and may complicate installation. Mitigate by making them optional and documenting the additional requirements in installation guides.
Risk: Generating depth maps on the fly may slow down pre‑processing. Mitigate with caching and by performing depth estimation in a separate thread or asynchronous task.
Risk: UI complexity could overwhelm users. Mitigate by grouping ControlNet settings under an expandable “Advanced” section and providing clear tooltips.
Dependencies
PR‑CORE‑005 (basic camera motion) must be merged first as this PR extends its depth/pose capabilities. No other dependencies.
Approval & Execution
Approvers: Core ML team, UI team.
Execution: Merge onto a dedicated feature/controlnet-depth branch. Coordinate with packaging to ensure optional model files are available. After tests pass and documentation is updated, merge into development.
