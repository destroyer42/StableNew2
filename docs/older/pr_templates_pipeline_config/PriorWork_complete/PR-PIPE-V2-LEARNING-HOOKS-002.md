# PR-PIPE-V2-LEARNING-HOOKS-002
## Title
Pipeline V2 Learning Hooks (Run Config & Variant Metadata Recording)

## Summary
This PR introduces learning-oriented hooks in the pipeline/controller layers that record run configurations and randomizer metadata in a structured, GUI-free way. It complements the learning scaffolding added earlier (learning_plan, learning_runner, learning_feedback, learning_adapter) by capturing the “what actually ran” facts for each pipeline execution. No online learning or LLM integration is performed yet; this PR strictly wires run-time data into durable records suitable for future learning/LLM-driven config refinement.

## Problem Statement
The learning subsystem currently knows how to:
- Define learning modes and plans.
- Run stubbed learning sequences.
- Package user feedback.

But it does not know what actually ran in the real pipeline. Without a durable record of:
- Base pipeline config.
- Per-variant config (where applicable).
- Randomizer mode and plan shape.
- Core knobs (model, sampler, scheduler, steps, CFG, etc.),

there is no reliable ground truth to feed into future “learning runs” or LLM-based config suggestion flows. We need a low-risk, GUI-free way to capture this data from the pipeline/runtime path.

## Goals
- Introduce a LearningRecord dataclass (or equivalent schema) in src/learning that can represent:
  - Run ID / timestamp.
  - Base config used for the run.
  - First (or each) variant config used.
  - Randomizer mode and summary (e.g., number of variants in plan).
  - Key knobs (model, sampler, scheduler, steps, CFG scale, denoiser, etc.).
- Add a LearningRecordWriter that can persist these records atomically to disk (or another append-only store) without any GUI references.
- Extend PipelineRunner so that, when provided with an optional LearningRecordWriter, it:
  - Emits a LearningRecord at the end of each run.
  - Does not fail the pipeline if learning recording throws (failsafe behavior).
- Extend PipelineController to:
  - Accept an optional LearningRecordWriter-like dependency.
  - Expose a small on_learning_record callback hook for tests or future GUI wiring.
- Provide tests that confirm:
  - Learning records are correctly populated from configs and variant metadata.
  - PipelineRunner and controller still behave correctly when no learning writer is provided.

## Non-goals
- No GUI changes (no UI for learning, no new buttons or menus).
- No LLM calls, no prompt/pack synthesis, no new external services.
- No changes to randomizer algorithms or matrix parsing; only reading their outputs.
- No changes to the existing learning runner behavior beyond reading the new record types, if necessary.

## Allowed Files
- src/learning/learning_record.py (new, or merged into an existing learning_* file if that is the established pattern)
- src/learning/learning_runner.py (only minor adjustments to accept/forward LearningRecord if needed)
- src/learning/__init__.py (export new types if needed)
- src/pipeline/pipeline_runner.py
- src/controller/pipeline_controller.py
- tests/learning/test_learning_record_serialization.py (new)
- tests/learning/test_learning_hooks_pipeline_runner.py (new)
- tests/learning/test_learning_hooks_controller.py (new)
- docs/pr_templates/PR-PIPE-V2-LEARNING-HOOKS-002.md (this file)

## Forbidden Files
- src/gui/* (no changes to GUI in this PR)
- src/gui_v2/* (no changes)
- src/utils/randomizer.py
- tests/gui/* and tests/gui_v1_legacy/*
- Any external integration modules (no network, no LLM calls)

## Step-by-step Implementation Plan

1. Define LearningRecord model
   - Under src/learning/, create a new module (e.g., learning_record.py) that:
     - Defines a LearningRecord dataclass with fields such as:
       - run_id (string or UUID)
       - timestamp (ISO 8601 string or datetime serialized to string)
       - base_config (mapping of stage -> config dict)
       - variant_configs (list of stage -> config dict snapshots, or a flattened structure)
       - randomizer_mode (string)
       - randomizer_plan_size (int)
       - primary_model (string)
       - primary_sampler (string)
       - primary_scheduler (string)
       - primary_steps (int)
       - primary_cfg_scale (float)
     - Provides helper functions:
       - from_pipeline_context(base_config, variant_config, randomizer_plan, metadata) -> LearningRecord
       - to_json(record) -> str
       - from_json(str) -> LearningRecord

2. Implement LearningRecordWriter
   - In the same module or a companion (e.g., learning_record.py):
     - Define a LearningRecordWriter class that:
       - Accepts a base directory/path for learning records.
       - Exposes write(record: LearningRecord) -> None.
       - Writes each record to a unique file (e.g., by run_id or timestamp) in JSON form.
       - Uses atomic write semantics (write to temp file then rename) to avoid partial writes.
       - Swallows IO errors after logging; learning should never break the main pipeline.

3. Wire LearningRecord into PipelineRunner
   - In src/pipeline/pipeline_runner.py:
     - Update PipelineRunner (or its run method) to accept an optional LearningRecordWriter and optional learning metadata callback.
     - After the pipeline completes successfully (or reaches a terminal state where a record makes sense):
       - Build a LearningRecord from the:
         - Final base config sent into the run.
         - Variant config(s) used (in the current code, we at least have the “first variant” config used for single-variant execution).
         - Randomizer metadata currently exposed via RandomizerPlanResult (mode, plan length, etc.), if available.
       - Call LearningRecordWriter.write(record) if provided.
       - Optionally invoke a callback (for tests) with the record.
     - Ensure that any exceptions from LearningRecordWriter are caught and do not propagate to the caller.

4. Wire LearningRecord through PipelineController
   - In src/controller/pipeline_controller.py:
     - Add constructor parameters for an optional LearningRecordWriter or learning hook (depending on how you prefer to inject).
     - When instantiating PipelineRunner (or delegating to it), pass the writer through.
     - Provide a small hook:
       - on_learning_record(record: LearningRecord) that can be set in tests to observe emitted records.
     - Ensure that the controller surface remains GUI-free and does not import Tk or GUI modules.

5. Tests – LearningRecord and serialization
   - Add tests/learning/test_learning_record_serialization.py:
     - Build a representative LearningRecord with non-trivial configs and randomizer metadata.
     - Round-trip through to_json/from_json and assert equality of key fields.
     - Verify that LearningRecordWriter.write produces a file with valid JSON and that atomic write semantics are respected (no partial writes).

6. Tests – PipelineRunner hooks
   - Add tests/learning/test_learning_hooks_pipeline_runner.py:
     - Use a fake LearningRecordWriter that records calls to write without touching the filesystem.
     - Run PipelineRunner in a minimal configuration (mock the underlying API client/pipeline work if necessary).
     - Assert that:
       - LearningRecordWriter.write was called once per run when a writer is provided.
       - No calls are made when no writer is provided.
       - The LearningRecord includes expected data (model/sampler/steps/CFG/etc. gleaned from the config).

7. Tests – PipelineController hooks
   - Add tests/learning/test_learning_hooks_controller.py:
     - Instantiate PipelineController with a fake LearningRecordWriter and a fake PipelineRunner that simulates a single run and emits a LearningRecord via callback.
     - Assert that:
       - The controller passes the writer down.
       - The controller-level hook (on_learning_record) receives the record if set.
       - No GUI imports or side-effects occur.

8. Keep behavior backward compatible
   - Existing callers of PipelineRunner and PipelineController must continue to work without providing any learning dependencies.
   - All new parameters should be optional and defaulted such that existing code paths require no changes.

## Required Tests (Failing First)
- tests/learning/test_learning_record_serialization.py
- tests/learning/test_learning_hooks_pipeline_runner.py
- tests/learning/test_learning_hooks_controller.py

These tests should be added first and allowed to fail before you implement the production code.

## Acceptance Criteria
- All new learning tests pass:
  - tests/learning/test_learning_record_serialization.py
  - tests/learning/test_learning_hooks_pipeline_runner.py
  - tests/learning/test_learning_hooks_controller.py
- Existing tests under tests/learning continue to pass.
- GUI tests (tests/gui_v2) and safety tests remain green (or keep their known, existing Tk skips only).
- Running pytest -v completes successfully in the target environment.

## Rollback Plan
- If learning hooks introduce regressions or instability:
  - Revert changes in src/learning, src/pipeline/pipeline_runner.py, and src/controller/pipeline_controller.py.
  - Remove newly added tests in tests/learning related to LearningRecord and hooks.
  - Confirm that pytest tests/learning -v, pytest tests/gui_v2 -v, and pytest -v all return to their prior state.

## Codex Execution Constraints
- Do not import GUI modules in any learning/pipeline/controller files.
- Do not introduce network calls or LLM integration.
- Keep LearningRecord as a pure data model with JSON serialization helpers.
- Keep PipelineRunner and PipelineController changes backward compatible.

## Smoke Test Checklist
- Run pytest tests/learning -v and confirm all learning-related tests are green.
- Run pytest tests/gui_v2 -v and pytest -v to confirm the overall suite remains stable.
- In a local environment, run a small pipeline via the controller/pipeline and confirm that:
  - The learning record files are emitted to the expected directory when a LearningRecordWriter is configured.
  - No errors are logged if the learning directory is missing or unwritable (learning failures are gracefully ignored).
