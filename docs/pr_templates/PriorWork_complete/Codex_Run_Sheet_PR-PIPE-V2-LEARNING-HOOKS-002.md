# Codex Run Sheet – PR-PIPE-V2-LEARNING-HOOKS-002

Paste this entire block into Codex chat when you’re ready to implement this PR.

---

You are implementing PR-PIPE-V2-LEARNING-HOOKS-002.

High-level intent:
- Capture real pipeline run configurations and randomizer metadata into structured learning records.
- Keep everything GUI-free and backward compatible.
- Do not introduce any LLM calls or online learning yet.

Reference PR template:
- docs/pr_templates/PR-PIPE-V2-LEARNING-HOOKS-002.md

## Scope and File Boundaries

Allowed files:
- src/learning/learning_record.py (new)
- src/learning/learning_runner.py (minimal adjustments only)
- src/learning/__init__.py (if needed)
- src/pipeline/pipeline_runner.py
- src/controller/pipeline_controller.py
- tests/learning/test_learning_record_serialization.py (new)
- tests/learning/test_learning_hooks_pipeline_runner.py (new)
- tests/learning/test_learning_hooks_controller.py (new)

Forbidden:
- src/gui/*
- src/gui_v2/*
- src/utils/randomizer.py
- tests/gui/*
- tests/gui_v1_legacy/*
- Any networking/LLM integration modules

If you think additional files must be changed, stop and request an update to the PR template instead of guessing.

## Implementation Steps

1. LearningRecord model
   - Create src/learning/learning_record.py:
     - Define a LearningRecord dataclass capturing:
       - run_id (string or UUID)
       - timestamp (string or datetime serialized)
       - base_config (mapping of stage -> dict)
       - variant_configs (list of mappings, one per variant or at least the first variant)
       - randomizer_mode (string)
       - randomizer_plan_size (int)
       - primary_model (string)
       - primary_sampler (string)
       - primary_scheduler (string)
       - primary_steps (int)
       - primary_cfg_scale (float)
     - Implement:
       - to_json(self) -> str
       - @staticmethod from_json(text: str) -> LearningRecord
       - @staticmethod from_pipeline_context(base_config, variant_configs, randomizer_metadata, knobs_metadata) -> LearningRecord

2. LearningRecordWriter
   - In src/learning/learning_record.py (or a closely related helper):
     - Implement LearningRecordWriter:
       - __init__(self, base_dir: Path | str)
       - write(self, record: LearningRecord) -> None
         - Generates a unique filename (e.g., using run_id and timestamp).
         - Writes JSON atomically:
           - Write to a temporary file in the same directory.
           - fsync/close.
           - Rename to the final filename.
         - Wrap IO errors in try/except and log, but do not re-raise (learning failures must not break the main pipeline).

3. PipelineRunner integration
   - In src/pipeline/pipeline_runner.py:
     - Extend PipelineRunner to accept an optional LearningRecordWriter and optional on_learning_record callback:
       - e.g., __init__(..., learning_record_writer: Optional[LearningRecordWriter] = None, on_learning_record: Optional[Callable[[LearningRecord], None]] = None)
     - After a successful run (or when you have enough information to log a record):
       - Create a LearningRecord via LearningRecord.from_pipeline_context, using:
         - The base PipelineConfig or config dict used for the run.
         - The first (or each) variant config the runner actually used.
         - Randomizer metadata from RandomizerPlanResult (mode, plan size) if present.
         - Extracted knobs (model, sampler, scheduler, steps, cfg_scale) from the effective config.
       - If a LearningRecordWriter is provided, call write(record) inside a try/except.
       - If an on_learning_record callback is provided, call it with the record (do not let exceptions escape).

4. PipelineController integration
   - In src/controller/pipeline_controller.py:
     - Add an optional learning_record_writer parameter to the controller constructor (or a similar injection point).
     - When constructing PipelineRunner, pass the writer and (optionally) a controller-local callback that:
       - Stores the last LearningRecord for tests.
       - Forwards the record to any external observer via a controller-level hook (e.g., on_learning_record).
     - Do not import Tk or GUI modules.
     - Keep default behavior unchanged when no writer is provided.

5. Tests – LearningRecord and serialization
   - Add tests/learning/test_learning_record_serialization.py:
     - Build a LearningRecord with non-trivial configs and randomizer metadata.
     - Round-trip via to_json/from_json and assert field equality.
     - Instantiate a LearningRecordWriter with a temporary directory and assert:
       - write(record) produces a JSON file.
       - The JSON can be read back and deserialized into an equivalent LearningRecord.

6. Tests – PipelineRunner hooks
   - Add tests/learning/test_learning_hooks_pipeline_runner.py:
     - Use a fake LearningRecordWriter that appends incoming records to an in-memory list instead of hitting the filesystem.
     - Construct PipelineRunner with:
       - The fake writer.
       - A dummy on_learning_record callback that appends records to another list.
     - Trigger a minimal run (mock actual stable diffusion processing; you only need the control flow).
     - Assert:
       - Exactly one LearningRecord is written by the writer.
       - on_learning_record was invoked with the same record.
       - When creating a runner without a writer, no records are produced and no exceptions occur.

7. Tests – PipelineController hooks
   - Add tests/learning/test_learning_hooks_controller.py:
     - Create a fake PipelineRunner that simulates a run and calls its on_learning_record callback with a synthetic LearningRecord.
     - Construct PipelineController with:
       - The fake runner injection (or a factory override).
       - An on_learning_record callback that appends to a list.
     - Trigger a run via the controller’s public API.
     - Assert that the callback received the record and that no GUI imports are present.

8. Backward compatibility
   - Ensure all new constructor parameters are optional with sensible defaults.
   - Existing code paths that construct PipelineRunner and PipelineController without learning features must continue to work unmodified.

## Required Test Commands

Run these in order and paste outputs into the PR discussion:

1) pytest tests/learning/test_learning_record_serialization.py -v
2) pytest tests/learning/test_learning_hooks_pipeline_runner.py -v
3) pytest tests/learning/test_learning_hooks_controller.py -v
4) pytest tests/learning -v
5) pytest tests/gui_v2 -v
6) pytest -v

If any test fails, fix the issue within this PR’s scope. Do not “fix” unrelated modules in this PR.

## Guardrails / Reminders

- No GUI modules or Tk imports in learning/pipeline/controller code.
- No external service calls or LLM integration.
- Learning features must be optional and non-fatal; if something goes wrong, the main pipeline run must still succeed.
- Keep diffs focused and consistent with the Architecture_v2 learning groundwork.
