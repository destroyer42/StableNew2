PR-CORE-004 - Cinematic Prompt Template Library

Status: Specification
Priority: MEDIUM
Effort: SMALL
Phase: Post-Unification Core Refinement
Date: 2026-03-29

Context & Motivation

StableNew uses PromptPacks to run sequences of prompts but provides no curated library of cinematic prompt phrases or camera shot descriptions. As a result, users must craft detailed prompts for every scene, which is tedious and yields inconsistent style. The PR proposals recommend creating a prompt template library of reusable phrases covering common shot types, camera angles, and environmental descriptors. This library will be stored in a data file and loaded by the PromptPack builder, allowing users to select templates and fill in placeholders. External design guides and diffusion communities supply many examples【18†L61-L63】【18†L89-L93】 which we can encode as templates.

Goals & Non‑Goals
Goal: Create a structured data file (data/prompt_templates.json or .yaml) defining categories of prompt templates (e.g. shot type, composition, lighting) with placeholders such as {scene} and {character}.
Goal: Load the template file in the PromptPack builder and allow the user (or automatic scene planner) to select a template category when constructing prompts.
Goal: Provide UI elements (drop‑down or selection list) in the prompt editor to choose templates and preview the resulting full prompt.
Goal: Write tests to ensure templates are loaded correctly and placeholder interpolation works as expected.
Non‑Goal: Do not restrict users to only templates; freeform prompt editing should remain available.
Guardrails
Do not embed raw user text in the template data; placeholders must be clearly marked and replaced only when constructing a prompt.
The template loader must validate the JSON/YAML file structure and fail fast on syntax errors. Provide a default set of templates if the file is missing.
UI additions should be optional and not disturb existing prompt entry workflows.
Allowed Files
Files to Create
data/prompt_templates.json (or .yaml) – top‑level keys are categories (e.g. wide_shot, close_up) and values are template strings with placeholders.
src/services/prompt_templates.py – utility for loading, validating, and retrieving template strings. Exposes get_template(category) and apply_template(template, **kwargs) functions.
tests/services/test_prompt_templates.py – unit tests for loading templates and applying placeholders.
tests/data/test_prompt_templates.json – sample template file for tests.
Files to Modify
src/services/prompt_pack.py – incorporate template application when building prompts. Accept a template_category parameter from config or UI; call get_template and apply_template.
src/gui/views/prompt_editor_frame.py (or similar) – add UI controls to choose a template category and update the prompt editor accordingly.
Forbidden Files
Do not modify src/video/ pipeline code; templates belong to the prompt building layer.
Do not hardcode templates in code; they must live in the data file for easy updates.
Implementation Plan

Define template schema: Decide on JSON/YAML structure. For example:

{
  "wide_shot": "A wide shot of {scene} at {time_of_day}, cinematic lighting",
  "close_up": "Close‑up of {character}, dramatic expression, {style}"
}

Ensure placeholders are enclosed in curly braces.

Implement loader: In prompt_templates.py, implement load_templates(path) that reads and parses the file at startup (with caching). Provide get_template(name) that raises a descriptive error if the template is missing.
Template application: Implement apply_template(template, **kwargs) that substitutes placeholders using Python str.format(). Validate that all placeholders are provided and raise errors otherwise.
Integrate with PromptPack builder: Modify prompt_pack.py so that each prompt entry can specify a template_category and a set of variables (scene description, character name, style). When building the prompt, call get_template and apply_template to produce the final text. If no template is specified, use the freeform prompt.
GUI integration: Add a dropdown in the prompt editor (or scene planner) for selecting a template category. When a user picks one, show the resulting prompt in the editor, allowing further edits.
Tests: Write unit tests to ensure templates load correctly, missing placeholders raise errors, and the builder uses templates when specified. Provide sample template data for tests.
Testing Plan
Unit tests verify that load_templates reads the file, returns the correct dictionary, and errors on malformed JSON. Test apply_template with various combinations of placeholders and missing values.
Integration tests ensure that when a PromptPack includes a template_category, the final prompt contains replaced values. Also test that selecting a template in the GUI updates the editor.
Manual verification: using the GUI, select a template and fill in placeholders; verify the preview matches expectations.
Verification Criteria
The template file loads at startup without errors, and categories are available through the API.
When a user chooses a template category and provides the necessary variables, the PromptPack builder constructs a prompt that matches the template with placeholders replaced.
Freeform prompts remain supported when no template category is specified.
All new tests pass.
Risk Assessment
Low risk overall; failure to load templates falls back to manual prompts. Mitigate by providing a default template file in the repo.
Minor UI risk if the dropdown is miswired; mitigate by adding basic GUI tests.
Tech Debt Analysis

This PR introduces a maintainable mechanism for prompt templates, reducing manual prompt writing. Deferred items include expanding the template library and supporting localized templates for different languages.

Documentation Updates

Update the user guide to explain how to use templates when creating prompt packs. Document the available categories and placeholders in a docs/prompt_templates.md file.

Dependencies

No new external dependencies. Uses Python’s JSON/YAML parser (PyYAML is already available).

Approval & Execution

Planner: agent
Executor: TBD
Reviewer: @ui-team
Approval Status: Pending

Next Steps

After implementing templates, integrate them with the story planner so that each scene can be assigned a default template automatically (ties into PR‑CORE‑003). Consider adding style templates linked to style LoRAs (PR‑CORE‑008).

