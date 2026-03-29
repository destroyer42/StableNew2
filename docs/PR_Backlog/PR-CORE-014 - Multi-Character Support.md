PR-CORE-014 – Multi‑Character Support

Status: Specification
Priority: MEDIUM
Effort: MEDIUM
Phase: Post‑Unification Core Refinement
Date: 2026-03-29

Context & Motivation

While PR‑CORE‑002 introduces character embeddings to ensure consistent appearance for individual characters, the current pipeline still assumes a single character per scene. However, most narratives involve multiple characters interacting. The story planner (PR‑CORE‑003) may define scenes featuring two or more actors, but StableNew lacks a mechanism to apply multiple LoRAs or embeddings simultaneously. Multi‑character support allows prompts to include multiple character tags and ensures the correct LoRA weights are applied for each actor in the scene.

Goals & Non‑Goals
Goal: Extend the data model for scenes and shots to support multiple characters, each with a name and associated LoRA or embedding identifier.
Goal: Modify the PromptPack builder and job builder to assemble prompts that contain all character tokens and to load multiple LoRA weights in the correct order.
Goal: Update the UI (scene planner and prompt editor) to allow selection of multiple characters for a scene and specify their relative prominence (optional).
Goal: Ensure that multi‑character prompts still incorporate style LoRAs and template phrases (from PR‑CORE‑008 and PR‑CORE‑004) appropriately.
Non‑Goal: Automatic detection of character interactions or dynamic weighting between characters is outside the scope of this PR. We focus on deterministic inclusion of multiple tokens based on user input or story plan.
Guardrails
When combining multiple LoRAs, order matters. Adopt a convention: apply primary character LoRA first, secondary characters next, and finally style LoRAs. Document this order and ensure consistency across runs.
Validate that all specified characters have corresponding embeddings/LoRA files. If a character is missing, provide a clear error message and skip generation.
Maintain backwards compatibility: scenes with a single character should continue to work without any changes to prompts or job builder logic.
Allowed Files
Files to Modify
src/video/story_plan_models.py – update ScenePlan and ShotPlan dataclasses to include a list of actors, each with fields such as name, lora_name, and optionally prominence or weight. Provide helper methods to summarise actors and to merge actor lists from shots and scenes.
src/services/prompt_pack.py – modify prompt construction so that it iterates over all actors in a scene, appends their trigger tokens to the positive prompt, and aggregates their LoRA file paths into the job configuration. Ensure no duplicate tokens are added.
src/pipeline/job_builder_v2.py – update logic to combine multiple LoRA tags and weights in the correct order when building the stage config. Add support for a list of actors in the intent config.
src/gui/views/scene_editor_frame.py (or similar) – allow users to select multiple characters from the character store (PR‑CORE‑002) when defining a scene. Use multi‑select widgets or checkboxes. Display the selected characters’ names and preview their tags.
src/pipeline/config_contract_v26.py – extend the schema to include actors as an array of objects with properties name, lora_name, and weight.
tests/services/test_prompt_pack_multi_character.py – new unit tests verifying that multiple character tokens are inserted and that LoRA lists include all specified files.
Files to Create
tests/services/test_prompt_pack_multi_character.py – as described.
Forbidden Files
Do not implement character interaction logic (e.g. automatically weighting LoRA contributions based on prominence); such behaviour is future research.
Do not hardcode character names or LoRA IDs in code; rely on the character store (PR‑CORE‑002) to provide this data.
Implementation Plan
Data model updates: In story_plan_models.py, change the ScenePlan and ShotPlan definitions to include an actors: List[Actor] field, where Actor is a dataclass with name, lora_name, and optional weight (default 1.0). Provide methods to parse actors from JSON and to combine actor lists when merging scenes and shots.
Prompt construction: In prompt_pack.py, iterate over actors for each scene. For each actor, retrieve the character token from the character identity store (PR‑CORE‑002) and append it to the positive prompt string (e.g. <Kaladin> <Shallan>). Also append corresponding LoRA file paths to the lora_tags list in the stage config. Avoid duplicates.
Job builder changes: Update job_builder_v2.py to expect actors in the intent config. Combine LoRA weights in order and ensure the style LoRA (PR‑CORE‑008) is added last. If actors have associated weights, include them in the LoRA injection logic.
UI enhancements: Modify the scene planner and prompt editor to allow selecting multiple characters. Provide checkboxes or multi‑select lists populated from the character store. Display selected character names and allow editing of their weight values. Persist selections in the story plan.
Schema updates: Extend the config contract to define actors as an array of objects with properties. Provide validation in the builder to ensure the array is not empty if scenes require at least one character.
Testing: Write unit tests that construct a scene with two characters (e.g. Kaladin and Shallan) and verify that the generated prompt contains both tokens and that the stage config lists both LoRA files in the correct order. Also test that single‑character scenes still work.
Testing Plan
Unit tests: In test_prompt_pack_multi_character.py, create dummy actor definitions and ensure that building a prompt pack with two actors yields a prompt string containing both tokens and a job config containing both LoRA paths.
Integration tests: Extend end‑to‑end tests (PR‑CORE‑011) to include a multi‑character scene plan and verify that the dummy backend receives the correct number of LoRA weights.
Verification Criteria
Scenes and shots in the story planner can specify multiple characters, and their names and LoRA files are persisted in the plan.
The PromptPack builder appends all character tokens and LoRA file paths in the correct order, preserving previously existing style tokens and LoRA ordering.
The job builder includes multiple LoRA tags and weights in the NormalizedJobRecord. Inference proceeds without errors when multiple LoRAs are applied.
GUI updates allow selecting multiple characters and editing their weights. The UI persists selections and reflects them in the generated prompts.
All new unit and integration tests pass.
Risk Assessment
Medium risk: Combining multiple LoRAs could lead to unpredictable results if the LoRAs are incompatible (e.g. trained on different models). Mitigate by warning users when mixing LoRAs from different base models and providing guidelines.
Complexity: The pipeline must maintain consistent ordering of LoRA applications; incorrect ordering could cause inconsistent appearance. Thorough testing mitigates this risk.
Tech Debt Analysis

This PR introduces more complexity to prompt and job construction. To manage this, centralize actor handling in helper functions and avoid duplicating logic across modules. Deferred work includes exploring dynamic weighting of characters (e.g. based on prominence) and integrating this with story planning.

Documentation Updates
Update the story planner documentation to explain how to add multiple characters to a scene, including specifying their LoRA names and weights.
Update the user guide to describe multi‑character prompts and any potential limitations when combining multiple embeddings.
Dependencies
Depends on PR‑CORE‑002 (character embedding pipeline) and PR‑CORE‑008 (style LoRA) for underlying LoRA loading infrastructure.
Approval & Execution

Planner: agent
Executor: TBD
Reviewer: @pipeline‑team
Approval Status: Pending

Next Steps

Following multi‑character support, consider adding logic in the story planner to infer which characters appear in each scene based on narrative text. Explore dynamic weighting to emphasise the dominant character in a shot. Also consider UI enhancements to preview combined character styles.

