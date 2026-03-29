PR-CORE-009 – Scheduler & Sampler UI Options

Status: Specification
Priority: MEDIUM
Effort: SMALL
Phase: Post‑Unification Core Refinement
Date: 2026-03-29

Context & Motivation

StableDiffusion‑based generation relies on samplers (Euler, DDIM, DPM++, etc.) and scheduler settings (number of inference steps) to control image quality and style. Different samplers yield distinct textures and motion patterns, especially for video models. In the current StableNew GUI, these parameters are hidden or hard‑coded; users cannot choose their preferred sampler or adjust step counts directly. Test code references different schedulers
newtab
, but no UI allows selection. To empower artists and improve reproducibility, we should expose these settings in the user interface and propagate them through the pipeline.

Goals & Non‑Goals
Goal: Add UI controls (drop‑downs or input fields) in the SVD and WebUI tabs allowing users to select a sampler algorithm (e.g. Euler, DDIM, DPM++ 2M) and specify the number of inference steps (e.g. 20–50).
Goal: Modify the PromptPack builder and pipeline configuration so that scheduler and step settings from the UI are passed to the underlying model call. Ensure these values round‑trip through the NJR intent config and into the backend (Comfy or Diffusers).
Goal: Provide sensible defaults (e.g. Euler with 30 steps) and persist the last used settings in user preferences.
Goal: Validate user input (e.g. step count within a safe range) and gracefully handle unsupported sampler names (fall back to default). Provide a list of known samplers based on available diffusers pipelines.
Non‑Goal: Do not implement custom sampling algorithms; we leverage those already provided by Diffusers or ComfyUI. This PR focuses solely on exposing existing options to the user and wiring them through the pipeline.
Guardrails
Input validation must ensure that step counts stay within reasonable limits (e.g. 1–100) to avoid extremely long runtimes or negligible quality gain.
The UI should reflect only the samplers supported by the currently selected backend (e.g. Comfy’s SVD node supports a subset of samplers). Query the pipeline or maintain a static list per backend.
Default settings should be stored in the config manager and not cause regressions for existing PromptPack jobs that omit scheduler options (backwards compatibility).
When unspecified, the pipeline should use the same default sampler and step count as prior releases to preserve current behaviour.
Allowed Files
Files to Modify
src/gui/views/svd_tab_frame_v2.py and src/gui/views/webui_tab_frame.py (or equivalent) – add drop‑down components for sampler selection and numeric input or slider for step count. Update form data collection to include sampler and num_steps fields.
src/services/prompt_pack.py – accept sampler and step parameters in prompt pack metadata. When building the stage config, set the sampler and num_inference_steps fields accordingly.
src/pipeline/job_builder_v2.py – propagate scheduler settings into the NormalizedJobRecord so that the runner calls pipe(...) with these values. Provide fallback to defaults if not present.
src/pipeline/config_contract_v26.py – extend the schema to include optional sampler and num_steps fields with valid enumerations/ranges.
src/utils/preferences.py – persist the last used sampler and step count in user preferences, and load them as defaults.
tests/gui/test_scheduler_ui.py – (new test) verify that the sampler drop‑down appears in the UI and that selecting a value updates the form data.
tests/pipeline/test_scheduler_propagation.py – (new test) construct a PromptPack with custom sampler and step count and assert that the job record includes the correct values.
Files to Create
tests/gui/test_scheduler_ui.py – as above, a GUI contract test to ensure new UI fields exist and are wired correctly.
tests/pipeline/test_scheduler_propagation.py – as above.
Forbidden Files
Do not modify the low‑level diffusers pipeline classes; sampling is configured via parameters, not code changes.
Do not hardcode sampler names in multiple places; maintain a single list of available samplers and reuse it in UI and config validation.
Implementation Plan
Expose sampler list: Identify the set of supported sampler algorithms from the diffusers library (e.g. “Euler a”, “Euler”, “DDIM”, “DPM++ 2M Karras”). Hard‑code this list in a shared module or load it dynamically if possible. Provide human‑readable names for UI display.
UI updates: In the SVD and WebUI tabs, insert a drop‑down labelled “Sampler” and a numeric input or slider labelled “Steps”. Populate the drop‑down with the sampler list. On form submission, include sampler and num_steps in the form data dictionary.
PromptPack modifications: Modify the PromptPack metadata schema to include sampler and num_steps. When constructing each stage config, set the sampler and num_inference_steps accordingly. Provide defaults if the fields are absent.
Job builder propagation: In job_builder_v2.py, read the scheduler settings from the intent config and set them on the appropriate pipeline call. For example, when using diffusers, call pipe(prompt, num_inference_steps=num_steps, scheduler=sampler). For Comfy, map the sampler name to Comfy node settings.
Validation: Implement validation functions to ensure the chosen sampler exists in the supported list and the step count is within range. If invalid, log an error and revert to default values.
Persistence: Use preferences.py to load and save the last selected sampler and step count. Pre‑populate the UI fields with these values on start.
Testing: Write GUI tests verifying the presence and behaviour of the new controls. Write pipeline tests verifying the propagation of scheduler settings. Optionally, run a quick integration test with a dummy sampler to confirm that different samplers produce different outputs (mocking heavy computations).
Testing Plan
Unit tests: Validate that the sampler list is loaded correctly and that invalid names raise errors. Test that PromptPack includes scheduler settings when provided.
GUI tests: Use the existing test framework to check that sampler and step controls appear in the UI and can be set. Inspect the resulting form data and ensure values are passed to the pipeline.
Pipeline tests: Simulate a generation request with a non‑default sampler and verify that the job record’s config contains the correct sampler and num_steps. Use mocks to avoid heavy computation.
Verification Criteria
The user can choose a sampler and number of steps in the SVD and WebUI tabs. The UI displays available samplers and persists selections across sessions.
The scheduler and steps options are present in the PromptPack metadata and are included in the NormalizedJobRecord when jobs are queued.
The pipeline uses the selected sampler and step count when running diffusion. A basic smoke test confirms that different sampler selections produce different image outputs.
Default behaviour remains unchanged when the user leaves these fields unset.
All new tests pass.
Risk Assessment
Low risk: Exposing existing parameters introduces minimal complexity. The main risk is user confusion if unsupported samplers are presented; mitigate by limiting the list to known good options.
Compatibility: Ensure sampler names map correctly between diffusers and Comfy; mismatches could produce errors or silent fallbacks.
Tech Debt Analysis

Exposing sampler options addresses a common user request and improves reproducibility. The design should centralize the list of supported samplers to avoid duplication across UI and pipeline code. Deferred work includes dynamic detection of sampler options based on installed diffusers version and supporting custom scheduler definitions.

Documentation Updates

Update the user manual and help tooltips to describe the purpose of each sampler and recommended step counts. Add a FAQ entry explaining why certain samplers may produce smoother or sharper results and how to adjust steps for quality vs. speed.

Dependencies
No new external dependencies are required. Rely on diffusers and ComfyUI for sampler implementations.
Approval & Execution

Planner: agent
Executor: TBD
Reviewer: @ui‑team
Approval Status: Pending

Next Steps

After completing scheduler exposure, monitor user feedback to refine the list of available samplers and default values. Consider adding advanced settings such as eta or guidance_scale in a future PR if users request finer control.

