Timestamp: 2025-11-22 15:45 (UTC-06)
PR Id: PR-#33-LEARNING-V2-RecordWriterIntegration-001
Spec Path: docs/pr_templates/PR-#33-LEARNING-V2-RecordWriterIntegration-001.md

Title: Learning v2 – Passive LearningRecord Integration Into Single-Run Pipeline

1. Summary

This PR activates the Learning System v2 for passive (L2) learning by wiring the pipeline and controller layers into the LearningRecord stack.

It does three main things:

- Introduces a pure LearningRecord builder that assembles LearningRecord objects from PipelineConfig, PipelineRunResult, stage plans/events, and metadata.
- Refactors LearningRecord and LearningRecordWriter so that learning records are written as append-only JSONL with atomic semantics and a clear records_path.
- Adds passive-learning toggles and safety guards in PipelineRunner and PipelineController so that learning can be enabled or disabled via configuration without affecting core pipeline behavior.

Codex has implemented the changes against the StableNew v2 repo snapshot; this document records the intent, scope, and implementation details for future reference and for inclusion in the PriorWork_complete archive.

2. Problem Statement

Before this PR:

- The Learning v2 spec (Learning_System_Spec_v2.md) defined LearningRecord, LearningPlan, LearningRunStep, LearningRunResult, and LearningRecordWriter in concept, but:
  - PipelineRunner did not actually emit LearningRecords.
  - The controller layer did not expose a learning-enabled toggle or provide a writer.
  - There was no reliable, append-only storage of learning records suitable for later analysis or LLM ingestion.
- As a result, StableNew could not:
  - Persist per-run metadata (config, prompts, outputs, timings) in a structured way.
  - Support the planned L2/L3 learning workflows (passive ratings, active learning runs, preset derivation).
  - Provide a durable “memory” of previous runs for future recommendation or analytics features.

We needed to connect the architecture-level Learning System v2 design to real pipeline runs without changing user-visible behavior by default.

3. Goals

3.1 Functional Goals

- Ensure every successful pipeline run can produce a LearningRecord when learning is enabled.
- Keep learning optional and non-intrusive:
  - learning_enabled must default to False.
  - Disabling learning must make the system behave exactly as before this PR.
- Ensure LearningRecordWriter persists records as JSONL with atomic writes:
  - One JSON object per line.
  - Resistant to partial writes or concurrent opens.
- Expand LearningRecord so that it can carry:
  - Stage plan information (what stages were intended to run, in what order).
  - StageEvents / runtime metadata (durations, status, counts).
  - Output references per stage (image paths and derived metadata).
- Add controller-level toggles and pipeline-layer guards so that:
  - The controller decides whether learning is active for a run.
  - PipelineRunner only interacts with learning when explicitly instructed to.

3.2 Testing Goals

- Introduce unit tests for:
  - LearningRecord builder behavior.
  - LearningRecord serialization and JSONL writing.
- Introduce integration tests for:
  - PipelineRunner learning hooks (records are emitted when enabled).
  - PipelineController learning toggle (writer is created and invoked only when appropriate).
- Keep all existing tests green:
  - No regressions in controller, pipeline, learning, or IO-contract behavior.

3.3 Non-Goals

- No new GUI features (no learning toggle in the GUI, no “Review runs” dialog).
- No active-learning workflow (LearningPlan, LearningRunStep orchestration remains for future PRs).
- No cluster or queue integration (job models and multi-node scheduling are out of scope here).
- No manifest schema changes beyond optional learning metadata hooks.

4. Scope and Files

4.1 Files Changed (from Codex implementation)

Code-level changes:

- CHANGELOG.md
- Learning_System_Spec_v2.md
- pipeline_controller.py
- learning_record.py
- learning_record_builder.py (new)
- pipeline_runner.py

Tests:

- test_controller_learning_toggle.py
- test_learning_hooks_controller.py
- test_learning_hooks_pipeline_runner.py
- test_learning_record_builder.py
- test_learning_record_serialization.py
- test_learning_record_writer_integration.py
- test_pipeline_io_contracts.py
- test_pipeline_learning_hooks.py

4.2 Allowed Responsibilities

Learning layer:

- Define what a LearningRecord contains, in alignment with Learning_System_Spec_v2.
- Build LearningRecord instances from pipeline state (config + results).
- Persist LearningRecords safely as JSONL via LearningRecordWriter.

Pipeline layer:

- Accept an optional learning callback/writer.
- After successful execution, emit a LearningRecord when learning is enabled.
- Guard against learning-related failures causing pipeline failures.

Controller layer:

- Own the decision about whether learning is enabled.
- Construct and inject LearningRecordWriter into the pipeline path.
- Provide tests that demonstrate correct toggle behavior.

5. Design and Implementation Details

5.1 LearningRecord Expansion

LearningRecord has been expanded to carry:

- Core identifiers:
  - run_id
  - optional plan_id (for future active learning)
  - timestamp
- Context:
  - prompt_pack_id / prompt_id (if available from config metadata)
  - stage plan and stage order (e.g., txt2img, img2img, upscale)
- Configuration snapshot:
  - Effective PipelineConfig summarized or serialized into a dict-like structure.
- Runtime events:
  - StageEvents (per-stage start/end times, durations, statuses).
- Outputs:
  - Per-stage output paths (e.g., generated image files).
  - Any derived metrics needed later (image size, sampler name, steps, etc.).

The LearningRecord remains a dataclass-style object with explicit fields and explicit serialization functions. Serialization tests confirm round-trip behavior.

5.2 LearningRecordBuilder (Pure Helper)

A new module, learning_record_builder.py, provides a pure builder function that encapsulates the logic for assembling a LearningRecord:

- Inputs:
  - PipelineConfig (for configuration snapshot and metadata).
  - PipelineRunResult (for final outputs, including stage results and StageEvents).
  - Optional learning context (e.g., plan_id, variant index, future LearningRunStep references).

- Behavior:
  - Extracts stage plan and stages actually executed.
  - Maps StageEvents into a per-stage event list or summary.
  - Collects image paths and important metadata from the PipelineRunResult.
  - Constructs a LearningRecord instance that can be directly serialized.

The builder is IO-free and fully unit-tested in test_learning_record_builder.py, verifying that:

- Required fields are populated.
- Configuration and result data are correctly merged.
- The function is deterministic for a given input.

5.3 LearningRecordWriter – Atomic JSONL

LearningRecordWriter has been reworked with a clearer contract:

- It is constructed with a records_path pointing to a JSONL file.
- It exposes an append-record style API:
  - append_record(record: LearningRecord) -> None

- Implementation guarantees:
  - Records are serialized to a single-line JSON string.
  - Writes are atomic:
    - A temporary file is written and then moved into place, or
    - An equivalent robust append pattern is used consistent with project IO conventions.

Compatibility:

- A previous write-style API is maintained as a thin alias for append_record, preserving backward compatibility where necessary.

Tests in test_learning_record_writer_integration.py and test_learning_record_serialization.py confirm:

- Multiple records append correctly as separate JSON lines.
- Serialized JSON is parseable and matches expected fields.
- Partial writes are not left behind as corrupted JSON.

5.4 PipelineRunner Learning Hooks

PipelineRunner now accepts learning-related parameters and guards:

- It can be configured with:
  - A flag indicating whether learning is enabled for this run.
  - A LearningRecordWriter or equivalent callback to call upon completion.

Behavior:

- After a successful pipeline run:
  - If learning is enabled and a writer has been provided, PipelineRunner:
    - Uses LearningRecordBuilder to construct a LearningRecord.
    - Calls LearningRecordWriter.append_record() to persist the record.
- If learning is disabled or no writer is provided:
  - PipelineRunner does nothing learning-related and behaves exactly as before.
- Safety:
  - Learning-related failures (e.g., serialization error, file IO error) are caught, logged, and do not cause the pipeline run itself to fail.

Tests in test_learning_hooks_pipeline_runner.py and test_pipeline_learning_hooks.py confirm:

- LearningRecord is emitted when enabled.
- No LearningRecord is emitted when disabled.
- Learning callbacks are invoked at most once per run.
- Pipeline behavior is unchanged when learning is disabled.

5.5 PipelineController Learning Toggle and Wiring

PipelineController now owns a learning toggle:

- A controller-level flag learning_enabled (sourced from configuration, e.g., app_config or an equivalent module).
- Toggle behavior:
  - Enabled: PipelineController constructs a LearningRecordWriter (with a configured records_path) and passes it to PipelineRunner.
  - Disabled: No writer is created; learning is effectively off.

Codex added:

- test_controller_learning_toggle.py to verify that:
  - When learning is enabled, PipelineController instantiates and uses LearningRecordWriter.
  - When learning is disabled, no writer is constructed and no learning paths are invoked.
- test_learning_hooks_controller.py to ensure proper interaction between controller and pipeline learning hooks.

5.6 Documentation Updates

Learning_System_Spec_v2.md:

- Updated to note that passive learning (L2) is now wired into the single-run pipeline.
- Clarified that LearningRecords are written as JSONL via LearningRecordWriter when learning is enabled.

CHANGELOG.md:

- Updated to record:
  - Activation of passive learning hooks.
  - JSONL-based LearningRecordWriter behavior.
  - The presence of new learning-related tests and builder/writer modules.

6. Tests Executed (per Codex output)

Codex reported the following commands and outcomes:

- pytest tests/learning -v
- pytest tests/pipeline -v
- pytest tests/controller -v
- pytest -v

All suites passed with the new learning hooks and writer in place.

Files changed summary (from Codex):

- 14 files changed
- +551 insertions
- -200 deletions

7. Acceptance Criteria Mapping

The original goals for this PR are met when:

- PipelineRunner emits a LearningRecord for each successful run when learning is enabled:
  - Verified by test_pipeline_learning_hooks.py and test_learning_hooks_pipeline_runner.py.
- LearningRecordWriter writes append-only JSONL with atomic semantics:
  - Verified by test_learning_record_writer_integration.py and test_learning_record_serialization.py.
- PipelineController owns a learning toggle and correctly wires the writer:
  - Verified by test_controller_learning_toggle.py and test_learning_hooks_controller.py.
- All existing tests remain green:
  - Verified by full pytest run logged by Codex.

8. Rollback Plan

If regression in learning or pipeline behavior is detected, the rollback procedure is:

1) Revert the changes to:
   - learning_record.py
   - learning_record_builder.py
   - learning_record_writer.py
   - pipeline_runner.py
   - pipeline_controller.py
   - Any learning-related tests added by this PR.

2) Remove the corresponding bullet points from:
   - CHANGELOG.md
   - Learning_System_Spec_v2.md

3) Re-run:
   - pytest tests/learning -v
   - pytest tests/pipeline -v
   - pytest tests/controller -v
   - pytest -v

4) Confirm that the test suite matches the pre-PR baseline.

9. Relationship to Future Work

This PR establishes the baseline plumbing for passive learning:

- Future GUI PRs will:
  - Add a user-facing learning toggle (linked to the existing learning_enabled flag).
  - Add a “Review recent runs” dialog that reads LearningRecords and allows rating/tagging.

- Future Learning PRs will:
  - Implement LearningPlan and LearningRunStep orchestration for active learning runs.
  - Add more sophisticated insights and preset generation based on accumulated LearningRecords.

- Future Cluster/Queue PRs will:
  - Use LearningRecords as a data source for scheduling and throughput tuning across nodes.
