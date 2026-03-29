PR-CORE-015 – Prompt & Output Metadata Logging

Status: Specification
Priority: MEDIUM
Effort: SMALL
Phase: Post‑Unification Core Refinement
Date: 2026-03-29

Context & Motivation

In StableNew, each stage of the pipeline produces images or video frames. However, detailed metadata about how those artifacts were created—such as the prompt text, random seed, selected LoRAs, sampler, and model version—is not consistently recorded. The exsum notes partial history tracking
newtab
 but highlights the absence of prompt/seed memoization. Capturing this metadata enables reproducibility, facilitates debugging, and allows users to trace frames back to their originating prompts. Many other diffusion tools embed metadata in output images (e.g. EXIF) or sidecar JSON files. This PR introduces systematic metadata logging for all generated outputs.

Goals & Non‑Goals
Goal: For every generated image or video frame, record a metadata entry containing: positive prompt, negative prompt, random seed, model ID, sampler, number of steps, applied LoRAs (names and weights), and style tokens.
Goal: Save metadata alongside each output (e.g. as a .json file or as part of the file metadata for formats that support it). Use a consistent schema defined in Image_Metadata_Contract_v2.6.md.
Goal: Provide utilities to read and display metadata for a given output file in the GUI (e.g. when selecting an image, show its prompt and seed).
Goal: Write tests verifying that metadata files are created and adhere to the schema.
Non‑Goal: Do not embed large amounts of metadata in image EXIF if it could bloat the file size; using sidecar JSON files is acceptable. Audio metadata is beyond scope.
Guardrails
Ensure that metadata logging does not slow down inference or export significantly. Write metadata after saving the image rather than during generation.
Use the existing Image_Metadata_Contract_v2.6.md as the canonical schema. Validate metadata against this contract before writing.
Do not record sensitive information (e.g. API keys, user names). Store only the fields necessary for reproducing the output.
Allowed Files
Files to Modify
src/video/svd_runner.py and src/video/video_export.py – after generating each frame or clip, write a metadata file (e.g. .json) containing the required fields. Use a naming convention like <output_filename>.metadata.json.
src/pipeline/job_builder_v2.py – ensure that all relevant fields (prompt, seed, LoRAs, sampler, steps) are included in the job config so that the runner has access to them for logging.
src/gui/views/gallery_frame.py (or similar) – when displaying images or video outputs, load and display metadata in a sidebar or tooltip.
tests/video/test_metadata_logging.py – new unit tests verifying metadata creation and schema adherence.
Files to Create
tests/video/test_metadata_logging.py – unit tests for metadata logging.
Forbidden Files
Do not modify the diffusers or ComfyUI backends to embed metadata; handle logging in the runner/export code.
Do not record extraneous data (e.g. entire config file) in metadata; follow the contract.
Implementation Plan
Define metadata schema: Use Image_Metadata_Contract_v2.6.md as the reference for required fields. Write a function build_metadata_dict(prompt, negative_prompt, seed, model_id, sampler, steps, loras, style_tokens) that returns a dictionary conforming to this schema.
Runner modifications: In svd_runner.py and video_export.py, after saving each frame or video file, call build_metadata_dict with the relevant values from the job config and write the resulting JSON to <filename>.metadata.json. Ensure file paths are sanitized and created in the same directory as the output.
Job builder updates: Ensure that the NormalizedJobRecord includes all necessary fields (prompt, negative_prompt, seed, sampler, steps, lora_tags, style_tokens) so the runner has them available. If fields are optional, provide defaults.
GUI enhancements: In the gallery or output viewer, detect the presence of .metadata.json files alongside images/videos. When the user selects an item, load the metadata and display the prompt, seed, and LoRA names in a panel or tooltip.
Tests: Write test_metadata_logging.py to simulate a generation run (mocking the runner) and verify that metadata files are created and contain the expected keys and values. Validate the JSON against the contract using a schema validator (e.g. jsonschema).
Testing Plan
Unit tests: Use a dummy runner that records metadata for a mock output file. After running, assert that the metadata file exists and contains the correct keys and values. Test error conditions (e.g. missing fields) to ensure the logger handles them gracefully.
Integration tests: Extend PR‑CORE‑011’s integration tests to check that metadata files are generated for each output and that they match the prompts used.
Verification Criteria
For every generated output, a corresponding metadata JSON file exists and conforms to the specified schema.
Metadata includes prompt text, negative prompt, seed, model, sampler, steps, LoRAs, and style tokens. Values match the job configuration used for generation.
GUI displays metadata when viewing outputs, aiding reproducibility and debugging.
All new tests pass.
Risk Assessment
Low risk: Writing small JSON files after generation has minimal performance impact. The main risk is storing incorrect or incomplete metadata; thorough testing mitigates this.
Storage: Metadata files increase disk usage slightly; consider compressing or cleaning up old metadata in future work.
Tech Debt Analysis

Implementing metadata logging helps traceability and debugging. Potential future work includes embedding metadata in EXIF for image formats that support it or storing metadata in a centralized database for easier search and analysis.

Documentation Updates
Document the metadata schema and explain how to access metadata for outputs. Update the user manual to describe the new files and where to find prompts and seeds.
Dependencies
Use Python’s built‑in json library for serialization. Optionally depend on jsonschema in development requirements to validate metadata during tests.
Approval & Execution

Planner: agent
Executor: TBD
Reviewer: @qa‑team
Approval Status: Pending

Next Steps

After implementing metadata logging, consider adding command‑line tools to extract and search metadata across multiple runs. Explore embedding metadata into image EXIF for portability and use in other tools (e.g. digital asset managers).

