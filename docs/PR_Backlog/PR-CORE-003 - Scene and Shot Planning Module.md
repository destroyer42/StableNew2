PR-CORE-003 - Scene/Shot Planning Module

Status: Specification
Priority: HIGH
Effort: MEDIUM
Phase: Post-Unification Core Refinement
Date: 2026-03-29

Context & Motivation

The repository contains dataclasses for StoryPlan, ScenePlan, and ShotPlan under src/video/story_plan_models.py【2†L123-L130】, but there is no mechanism to populate these structures from narrative text or to drive video generation. Currently, users must manually craft prompts for each clip, and the “story planner” backlog item remains unimplemented【109†L63-L65】. To adapt a novel like The Way of Kings into a coherent sequence of shots, we need a module that can break text into scenes and shots, store them in a structured plan, and feed them into the PromptPack system. This PR will add a Scene/Shot Planning Module that can parse a book chapter into a StoryPlan, allow user edits, and integrate with the PromptPack builder.

Goals & Non‑Goals
Goal: Implement a function or CLI that takes a block of text (e.g. a chapter) and segments it into ordered scene descriptions and optional shot breakdowns, producing a StoryPlan object.
Goal: Persist plans via a story_plan_store.py that can save and load plans in JSON or YAML format, keyed by project or book chapter.
Goal: Provide a GUI or CLI to import text, view/edit scenes, and assign them to PromptPack creation. Each scene will ultimately correspond to a PromptPack.
Goal: Modify the PromptPack builder so that given a StoryPlan, it automatically generates a PromptPack per scene with placeholders for characters and templates (linking to PR‑CORE‑004).
Non‑Goal: Do not implement complex NLP algorithms in this PR; for initial implementation, splitting by paragraph or simple heuristics is acceptable. Advanced LLM‑based segmentation may be added later.
Non‑Goal: Do not ingest entire book files; that belongs to PR‑CORE‑019. This module operates on text provided by the user or another tool.
Guardrails
The PR must not alter the existing video execution pipeline (src/video/), except to read a StoryPlan when building PromptPacks.
StoryPlan data must remain in the intent/config layer and must not be serialized into backend workflow JSON. Plans should be saved in a dedicated directory (e.g. data/story_plans/).
Avoid hidden side effects: generating a plan should not enqueue jobs until the user explicitly triggers generation via the PromptPack builder.
Allowed Files
Files to Create
src/video/story_plan_store.py – module to save and load StoryPlan objects to/from disk (JSON/YAML) and to summarize plans.
src/cli/story_planner.py – simple command‑line interface that accepts a text file and outputs a plan file. Provides options for splitting strategy (paragraph, blank line, etc.).
src/gui/views/story_planner_frame.py – optional Tkinter view to import text, display scenes in a list, allow reordering/editing, and save the plan.
Tests: tests/video/test_story_plan_store.py, tests/cli/test_story_planner.py, and tests/gui/test_story_planner_frame.py.
Files to Modify
src/services/prompt_pack.py (or equivalent) – accept a StoryPlan and generate a PromptPack per scene. Support placeholder substitution for characters and templates.
src/pipeline/job_builder_v2.py – if necessary, adjust builder to iterate over scenes when assembling a job request.
src/gui/main_window_v2.py – add menu or button linking to the story planner view.
Forbidden Files
Do not modify src/video/story_plan_models.py dataclasses; the models are canonical and already used elsewhere.
Do not change backend video nodes or SVD services.
Implementation Plan
Plan Store: Implement StoryPlanStore with methods save(plan, path) and load(path). Use dataclasses’ asdict() for serialization. Provide a summary(plan) method that counts scenes and shots.
Basic Segmentation: Write a CLI in story_planner.py that reads a text file, splits it on blank lines or user‑defined separators into scenes, and constructs a StoryPlan. Each scene’s description is the trimmed text; shots can be left empty or filled with a single shot placeholder.
GUI Planner: Implement a Tkinter frame to show a text box for input and a listbox for resulting scenes. Allow users to merge/split scenes, reorder them, and edit descriptions. Persist the final plan via StoryPlanStore.
Integration with PromptPack: Extend the PromptPack builder to accept a loaded StoryPlan and generate one PromptPack per scene. Scenes are processed in order; each PromptPack will later be enriched with prompt templates and character info (PR‑CORE‑004 and PR‑CORE‑014).
Tests: Write unit tests for saving/loading plans, for CLI segmentation (ensuring number of scenes matches input), and for GUI validation. Add integration test verifying that the PromptPack builder iterates over scenes correctly.
Manual Validation: Run the CLI on a chapter excerpt and verify that the number of scenes makes sense. Load the plan in the GUI and reorder/edit scenes, then generate PromptPacks to ensure they align with the plan.
Testing Plan
Unit tests: Test StoryPlanStore round‑trip serialization; test CLI segmentation heuristics; test GUI functions (e.g. merging scenes) using mocks.
Integration tests: Use a sample plan to generate PromptPacks and assert that a pack exists per scene and references the correct scene description.
Manual: Test the GUI planner by importing a chapter and editing scenes. Save the plan and confirm it loads back identically.
Verification Criteria
Running python story_planner.py input.txt --split blankline produces a plan file with scenes corresponding to blank‑line separated blocks.
Loading a plan via GUI shows the same list of scenes and allows reordering and editing; saving persists edits.
The PromptPack builder generates one pack per scene when given a plan, and each pack contains the correct scene description.
All new tests pass.
Risk Assessment
Medium Risk: Poor segmentation heuristics may create too many or too few scenes. Mitigate by exposing segmentation parameters and allowing manual editing. Future PRs can integrate an LLM for improved segmentation.
Low Risk: Integration with PromptPack builder is straightforward but must ensure backward compatibility with existing workflows (e.g. explicit prompt lists still work).
Tech Debt Analysis

This PR closes the gap in story planning by turning dataclasses into usable artifacts. Deferred items include advanced LLM‑based segmentation and integration with continuity or character metadata. Those will be tackled in subsequent PRs.

Documentation Updates

Add a section to the user guide describing how to create story plans using the CLI or GUI. Update the prompt pack lifecycle document to mention that scene plans can be sources for PromptPacks.

Dependencies

No external dependencies beyond Python standard library. Optionally depends on yaml for YAML serialization (already present in the repo).

Approval & Execution

Planner: agent
Executor: TBD
Reviewer: @nlp-team
Approval Status: Pending

Next Steps

After this PR, integrate prompt templates (PR‑CORE‑004) and character metadata (PR‑CORE‑014) into the planner so that scenes automatically reference consistent prompts and LoRA tags.

