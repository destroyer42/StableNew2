# PR-LEARN-V2-RECORDWRITER-001
**Title:** Pipeline + LearningRecordWriter Integration (Passive Single-Run Hooks)

## 1. Intent & Scope

This PR wires the existing **Learning v2 data structures** (LearningRecord, LearningRecordWriter, LearningRunner stubs) into the **single-node pipeline path** so that **every completed pipeline run can emit a LearningRecord**, even before any GUI-facing learning UX is added.

It is a **backend-only** change:
- No new GUI elements.
- No behavior changes to randomizer, config assembly, or stage sequencing.
- Strictly focuses on:
  - Creating LearningRecords from PipelineConfig + PipelineRunResult.
  - Writing them via LearningRecordWriter as append-only JSONL.
  - Ensuring the controller can enable/disable learning at runtime.

Baseline repo snapshot: **StableNew-main-11-22-2025-0729.zip** plus completed PRs:
- PR-GUI-V2-MAINWINDOW-REDUX-001
- PR-PIPELINE-V2-EXECUTOR-STAGEEVENTS-003

---

## 2. Current Context (What You Can Rely On)

From the v2 docs and current snapshot:

- Learning v2 spec defines:
  - `LearningRecord`, `LearningPlan`, `LearningRunStep`, `LearningRunResult`.
  - `LearningRecordWriter` as the single writer for append-only JSONL.
- Pipeline V2 already provides:
  - `PipelineConfig` encapsulating all stage configs and metadata.
  - `PipelineRunner` + `PipelineRunResult`, including per-stage artifacts and StageEvents.
- Controllers and adapters:
  - `PipelineController` and `learning_execution_controller` exist but are only lightly wired.
  - Learning hooks are present as stubs but not consistently used in single-run flows.

This PR **activates** the passive learning path (L2) while leaving active Learning Runs for a later PR.

---

## 3. Goals

1. **Generate LearningRecords** for every pipeline run when learning is enabled.
2. **Write LearningRecords** to disk via LearningRecordWriter as append-only JSONL with atomic writes.
3. Allow the controller to **toggle learning on/off** via configuration, with a sane default (learning off by default).
4. Ensure LearningRecords contain enough metadata to support future Learning Runs and external LLM analysis:
   - run_id, timestamp
   - prompt pack / prompt id (if available)
   - effective PipelineConfig snapshot
   - StageEvents summary (e.g., per-stage durations and outcomes)
   - output image paths per stage
5. Add tests that validate:
   - Records are produced when learning is enabled.
   - No records are produced when learning is disabled.
   - Files are never corrupted by partial writes (basic atomic-write check).

Non-goal: any GUI-facing “rate this image” or Learning Run wizard UX (that’s handled in follow-on PRs).

---

## 4. Allowed Files to Modify

You MAY modify or create:

- `src/learning/learning_record_writer.py` (or equivalent module if already present)
- `src/learning/learning_record_builder.py` (NEW helper module for constructing LearningRecords from pipeline data)
- `src/pipeline/pipeline_runner.py`
- `src/controller/pipeline_controller.py`
- `src/controller/learning_execution_controller.py` (if required for toggling)
- `src/config/app_config.py` or equivalent location where global “learning enabled” is stored

Tests:

- `tests/learning/test_learning_record_writer_integration.py` (NEW)
- `tests/pipeline/test_pipeline_learning_hooks.py` (NEW)
- `tests/controller/test_controller_learning_toggle.py` (NEW or extend an existing file)

Docs:

- `docs/Learning_System_Spec_v2.md` (small clarifications/notes)
- `docs/CHANGELOG.md` (entry for this PR)

If actual file names differ slightly, follow existing v2 learning module layout and keep scope identical.

You MUST NOT:

- Touch GUI modules (`src/gui/*`, `tests/gui_*`).
- Touch randomizer core (`src/utils/randomizer*`).
- Touch cluster modules (`src/cluster/*`) if present.
- Change manifest schemas or StructuredLogger behavior beyond adding optional learning-related metadata in a backwards-compatible way.

---

## 5. Implementation Plan

### 5.1 Introduce a LearningRecord builder helper

Create `src/learning/learning_record_builder.py` (or equivalent) with pure functions to:

- Take as input:
  - `PipelineConfig`
  - `PipelineRunResult`
  - Optional learning context (e.g., active LearningPlan id or variant index, if present).
- Produce a `LearningRecord` dataclass instance that fills:
  - Run context (run_id, timestamp, prompt pack id/prompt id if known).
  - Configuration snapshot (effective PipelineConfig as a serializable dict).
  - Stage sequence used, including StageTypes and order.
  - Outputs: list of stage outputs with image paths and any important metadata.
  - StageEvents summary if needed (e.g., durations, per-stage image counts).

Design the builder as:

```python
def build_learning_record(
    pipeline_config: PipelineConfig,
    run_result: PipelineRunResult,
    learning_context: Optional[LearningContext] = None,
) -> LearningRecord:
    ...
```

This helper must be **pure** (no IO) and fully unit-testable.

### 5.2 Extend LearningRecordWriter for atomic JSONL writes

Ensure `LearningRecordWriter`:

- Accepts a target JSONL path (e.g., under `output/learning/learning_records.jsonl` or a date-sharded layout).
- Writes records atomically:
  - Serialize LearningRecord to a single-line JSON string.
  - Write to a temp file then append/rename, or use a safe append pattern consistent with existing IO helpers.
- Exposes a simple API:

```python
class LearningRecordWriter:
    def __init__(self, records_path: Path): ...
    def append_record(self, record: LearningRecord) -> None: ...
```

Add unit tests that:

- Append multiple records.
- Ensure resulting file contains one JSON object per line.
- Ensure writer can be instantiated multiple times and continues appending.

### 5.3 Integrate Learning hooks into PipelineRunner

In `src/pipeline/pipeline_runner.py`:

- Accept an optional `learning_writer` (or `learning_hook`) argument in the main `run` or `run_pipeline` method.
- After successful pipeline completion (or even partial completion, depending on future needs), build a LearningRecord by calling the builder helper.
- If learning is enabled and a writer is provided, append the record.
- Ensure that failures in learning write **do not crash the pipeline**:
  - Log a warning on LearningRecord write failure, but allow the pipeline result to be returned.

### 5.4 Controller-level toggle and wiring

In `src/controller/pipeline_controller.py` (and, if necessary, `learning_execution_controller` and config):

- Introduce a simple boolean flag (e.g., `self.learning_enabled`), initialized from app config.
- When starting a run, if learning is enabled:
  - Construct a `LearningRecordWriter` with the appropriate path for the run/session.
  - Pass this writer (or a small `LearningContext` object that wraps it) into PipelineRunner.
- If learning is disabled:
  - Pass `None` so PipelineRunner skips LearningRecord creation.

Add controller tests that:

- Verify that enabling learning results in a call to `LearningRecordWriter.append_record` for successful runs (use mocks).
- Verify that disabling learning results in no calls to the writer.

### 5.5 Config Surface (No GUI yet)

If you have an app-level config module (e.g., `src/config/app_config.py`):

- Add a `learning_enabled` setting (default: False).
- Provide a getter/setter or config object so that future GUI PRs can toggle this value.
- Tests should confirm default is False and that setting to True enables the behavior in the controller tests.

### 5.6 Docs & Changelog

- Update `docs/Learning_System_Spec_v2.md`:
  - Note that L2 passive learning is now **activated** for normal runs when enabled via config.
  - Clarify that GUI-facing rating UI is coming in a later PR.

- Update `docs/CHANGELOG.md`:
  - Add an entry describing that LearningRecords are now written for pipeline runs when learning is enabled.

---

## 6. Tests & Commands

You MUST add or update tests so that the following pass:

- `pytest tests/learning -v`
- `pytest tests/pipeline -v`
- `pytest tests/controller -v`
- `pytest -v`

New tests should include:

1. `test_learning_record_builder_basic_roundtrip`:
   - Given a dummy PipelineConfig + PipelineRunResult, asserts that LearningRecord fields are populated correctly.

2. `test_learning_record_writer_appends_jsonl_lines`:
   - Writes multiple records and validates file line count and basic parse correctness.

3. `test_pipeline_runner_emits_learning_record_when_enabled`:
   - Uses a fake LearningRecordWriter or in-memory stub to assert that `append_record` is called.

4. `test_pipeline_controller_respects_learning_toggle`:
   - Asserts writer is created only when learning is enabled.

All learning-related failures should be localized to the new tests; pre-existing tests must remain green.

---

## 7. Acceptance Criteria

This PR is complete when:

1. PipelineRunner can accept an optional learning writer/context and produces LearningRecords for successful runs when enabled.
2. LearningRecordWriter writes append-only JSONL in an atomic, non-corrupting manner.
3. Controller exposes and respects a `learning_enabled` configuration toggle.
4. All new and existing tests (learning, pipeline, controller, full suite) pass.
5. No GUI code was touched.
6. Learning is still **opt-in**; default behavior for existing users is unchanged (no records written until explicitly enabled).
