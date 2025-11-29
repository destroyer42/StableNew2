# LEARNING_SYSTEM_SPEC

> Compact summary of Learning v2 for AI assistants.
> For full details, see the dedicated design doc (if present).

---

## 1. Goals

- Track **what was run** (plan, config, events, outputs).
- Track **how it behaved** (success/failure, metrics).
- Keep a JSONL history for offline analysis.

---

## 2. Key Concepts

- **LearningPlan**
  - High-level intent: what sweeps / experiments to run.
- **LearningExecutionContext / Result**
  - Execution-level data (start/end times, success flag, metrics).
- **LearningRecord**
  - Durable record containing:
    - Plan details
    - Stage events
    - Output metadata
    - Any relevant metrics

---

## 3. Builder & Writer

- **LearningRecordBuilder**
  - Pure function/module that assembles `LearningRecord` from:
    - Pipeline config
    - Pipeline results
    - Stage events

- **LearningRecordWriter**
  - Appends `LearningRecord` entries to a **JSONL (`.jsonl`) file**.
  - Atomic append semantics; safe for concurrent-ish writes.
  - Old `write(...)` retained as alias to new `append_record(...)`.

---

## 4. Integration Points

- `PipelineRunner`
  - Exposes hooks to invoke builder + writer at the end of a run (when enabled).
- `LearningExecutionRunner`
  - Executes LearningPlans via injected pipeline callables.
- `LearningExecutionController`
  - High-level API for non-GUI callers to trigger runs and retrieve last results.

---

## 5. Opt-In Behavior

- Learning system must be **disabled by default** for normal users unless configured.
- GUI and controllers must:
  - Check flags before invoking learning behavior.
  - Fail gracefully if writer paths are invalid or unwritable.

---

## 6. Notes for AI Agents

- When altering learning behavior, **do not break JSONL writer semantics**.
- Maintain backward compatibility of record schema where possible.
- Add tests when:
  - Changing record structure
  - Adjusting builder logic
  - Modifying writer’s append semantics
