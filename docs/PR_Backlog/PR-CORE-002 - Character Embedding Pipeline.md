PR-CORE-002 - Character Embedding Pipeline

Status: Specification
Priority: HIGH
Effort: LARGE
Phase: Post-Unification Core Refinement
Date: 2026-03-29

Context & Motivation

StableNew presently lacks a way to train and apply character‑specific embeddings. There are no modules under src/training/ and no schema for a “train_lora” stage. As a result, users cannot ensure that named characters look the same across scenes, which is critical for telling a cohesive story. The research exsum flags this gap as a top priority【109†L63-L65】. This PR introduces a Character Embedding Pipeline that wraps existing LoRA/textual inversion training scripts (e.g. Automatic1111 or Diffusers) and integrates with the StableNew job system and GUI.

Goals & Non‑Goals
Goal: Provide a pipeline and API to train a LoRA or textual inversion embedding for a character from a folder of images.
Goal: Expose a train_lora stage type in the config contract and job builder, allowing training jobs to run via NJR.
Goal: Create a GUI panel where the user selects a character, image directory, and hyperparameters and launches training.
Goal: Add a LoRA manager to register and load trained weights by character name during inference.
Non‑Goal: Do not implement new ML algorithms or include large weight files in the repository.
Non‑Goal: Do not modify existing inference pipelines beyond injecting LoRA weights.
Guardrails
Do not alter core inference modules (src/video/). Only add a new stage type and wrapper classes.
Training must run in a separate process to avoid blocking the GUI or job runner. Provide cancellation and error handling.
Store weight files under data/embeddings/ and keep them out of version control.
Record training configuration and results in the NJR snapshot but do not leak internal file paths into backend configs.
Allowed Files
Files to Create
src/training/character_embedder.py – wrapper around external training scripts with methods to start, poll, and cancel a training job.
src/training/lora_manager.py – registers, lists, and loads LoRA weights; maintains a manifest mapping character names to weight paths.
src/gui/views/character_training_frame.py – Tkinter GUI for selecting images and launching training.
Tests: tests/training/test_character_embedder.py, tests/training/test_lora_manager.py, and tests/gui/test_character_training_frame.py.
Files to Modify
src/pipeline/config_contract_v26.py – add a train_lora stage type with fields like character_name, image_dir, epochs, lr, and output_dir.
src/pipeline/job_builder_v2.py – recognize train_lora stages and build an embedder job snapshot.
src/controller/app_controller.py and src/gui/main_window_v2.py – register and wire the new GUI panel and training actions.
Forbidden Files
Do not modify src/video/ inference modules.
Do not alter archived controllers or DTOs.
Implementation Plan
Config & Embedder: Define a dataclass for LoRA training parameters. Implement CharacterEmbedder to assemble and run a subprocess call to the external training script, capture logs, and support cancellation.
LoRA Manager: Implement LoRAManager that maintains a JSON manifest mapping character names to weight paths and provides registration and loading functions.
Job Builder & Contract: Extend config_contract_v26.py to include a train_lora stage. Update job_builder_v2.py to create an embedder job and record parameters in the NJR snapshot.
GUI & Controller: Add a new panel in the GUI to launch training, and corresponding methods in AppController to start and monitor jobs.
Tests: Write unit tests using mocks to simulate external training. Add integration test verifying that a PipelineRunRequest with a train_lora stage produces the correct NJR snapshot.
Manual Hardening: Run a small training job manually to verify logs and weight registration; adjust as needed before merge.
Testing Plan
Unit tests for CharacterEmbedder and LoRAManager verify command construction, error handling, and manifest operations using mocks and temporary directories.
Integration tests ensure job builder handles train_lora stages and that the NJR snapshot schema remains valid.
GUI tests verify basic validation (e.g. missing images disables “Start” button) and event wiring.
Manual verification by training a small LoRA and applying it in a generation job.
Verification Criteria
Users can launch a training job from the GUI or CLI; the job runs asynchronously and produces a weight file in the specified output directory.
The NJR snapshot includes the train_lora stage with all parameters, and normal generation stages are unaffected.
The LoRA manager registers the new weight and allows subsequent jobs to reference it by character name.
All new tests pass.
Risk Assessment
Medium Risk: External training environment may not be installed. Mitigate by documenting prerequisites and failing gracefully.
Medium Risk: Cancelling training might leave orphan processes. Mitigate by tracking PIDs and cleaning them up on cancel.
High Risk: Improper manifest handling could break inference; mitigate with schema validation.
Tech Debt Analysis

This PR addresses the debt of missing character consistency by adding a formal training pipeline. Deferred items include dataset preparation tooling and advanced hyperparameter tuning, to be handled in future PRs.

Documentation Updates

Update architecture and user guides to describe the train_lora stage and how to train and use character embeddings. Add a new doc explaining how to organise training images and recommended parameters.

Dependencies

Relies on external training scripts (Automatic1111 or Diffusers) and on PyTorch/CUDA. Internally depends on config and logging utilities.

Approval & Execution

Planner: agent
Executor: TBD
Reviewer: @ml-team
Approval Status: Pending

Next Steps

Follow up by integrating character metadata with scene plans and prompt packs (PR‑CORE‑014).

