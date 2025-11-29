# PR-GUI-V2-LEARNING-HOOKS-002 — Learning Record Hooks (Runner + Controller Integration)

## 1. Overview

This PR wires the *learning stack* into the v2 pipeline in a safe, GUI‑free way so that every pipeline run **can** emit a normalized learning record, without yet changing the user‑visible UI.

You already landed the foundational learning primitives in `src/learning` (plan, adapter, runner, feedback). This PR:

- Introduces a **LearningRecord** type and writer that knows how to serialize a single pipeline run in a stable JSON format.
- Extends **PipelineRunner** so it can optionally emit learning records for each executed variant, without changing its public “happy path” behavior.
- Adds **controller‑level hooks** that let callers subscribe to learning events without coupling the controller to any particular persistence mechanism.
- Provides **deterministic tests** that prove records are emitted correctly and can be consumed by higher‑level components later (GUI, multi‑node farm, LLM helpers).

It is intentionally conservative: **no learning UI**, no LLM calls, and no changes to the existing “Run Full Pipeline” flow beyond the optional hooks.

---

## 2. Goals / Non‑Goals

### Goals

1. **Standardize learning records**

   - Define a single payload schema for “one executed pipeline variant”.
   - Include enough context to support future LLM or analytics passes (prompt pack, stages, model/sampler, outcomes, feedback placeholders).

2. **Hook the runner into learning**

   - Allow `PipelineRunner` to emit records as it executes variants.
   - Keep the core execution logic unchanged for non‑learning callers.

3. **Expose safe controller hooks**

   - Add a minimal observer API in `PipelineController` that higher layers (GUI, farm coordinator, CLI) can use to receive learning records.
   - Make it easy to keep learning logic out of the GUI and tests by default.

4. **Prove the behavior via tests**

   - Tests for record serialization and round‑trip.
   - Tests for runner‑level record emission.
   - Tests for controller‑level subscription behavior.

### Non‑Goals

- No GUI widgets, dialogs, or “learning mode” toggles.
- No rating prompts, LLM calls, or adaptive config changes yet.
- No multi‑node / farm orchestration.
- No changes to the randomizer UX or variant plan semantics.

Those are deliberately deferred to later learning‑focused PRs (e.g., `PR-GUI-V2-LEARNING-MODE-UI-00x`, `PR-AI-V2-SETTINGS-GENERATOR-00x`).

---

## 3. Design

### 3.1 LearningRecord model and writer

**New file:** `src/learning/learning_record.py`

Key pieces:

- `LearningRecord`
  - Dataclass capturing a *single* executed variant:
    - High‑level context: `run_id`, `timestamp`, `user_id` (optional), `host_id`, `source` (e.g., `"StableNewGUI"`), etc.
    - Prompt context: pack id/name, base prompt, negative prompt, seed, and “one‑click action” label (e.g., `"heroic portrait"`, `"batch upscale"`).
    - Pipeline context: model, VAE, sampler, scheduler, CFG, steps, resolution, stage flags (txt2img/img2img/upscale), randomizer metadata (variant index, matrix mode, fanout).
    - Outcome context: output paths (or hashes), error flag/message, duration, and placeholder fields for future **user feedback** (rating, tags, free‑text notes).
  - Strict typing for each field with sensible defaults where possible.

- Serialization helpers:
  - `to_dict()` → stable, JSON‑safe dict (no datetimes or Path objects).
  - `to_json()` / `from_json()` helpers for future offline tooling.
  - `from_pipeline_context(config, context)` helper that assembles a new `LearningRecord` from:
    - A `PipelineConfig` (or plain dict) snapshot.
    - An execution context bundle (e.g., variant index, timing, error, output paths).

- `LearningRecordWriter`
  - Responsible for **atomic persistence** of records (e.g., per‑run JSONL file).
  - Configurable base directory and file naming pattern (e.g., `learning/records/{run_id}.jsonl`).
  - `write_record(record: LearningRecord)` appends a single JSON line.
  - Internally uses a simple file lock / atomic write pattern to avoid partial lines if the process terminates mid‑write.
  - Designed so tests can swap in an in‑memory writer or temp‑dir writer easily.

The intent is that *all* downstream consumers (LLMs, dashboards, farm controllers) read this single schema, instead of scraping logs or bespoke ad‑hoc JSON blobs.

---

### 3.2 PipelineRunner hooks

**File:** `src/pipeline/pipeline_runner.py`

We extend `PipelineConfig` and `PipelineRunner`:

- `PipelineConfig`
  - Add *optional* metadata fields:
    - `run_id: str | None` — stable identifier for this entire pipeline run.
    - `one_click_action: str | None` — user‑facing label (e.g., “Fantasy Portrait – v2”).
    - `learning_enabled: bool` — whether we should emit learning records at all.
    - `learning_tags: list[str]` — arbitrary tags, e.g., `"experiment:steps"`, `"style:grimdark"`.
  - These fields are **non‑required** and default to benign values so existing callers don’t need to be updated immediately.

- `PipelineRunner`
  - Add optional collaborator(s):
    - `learning_writer: LearningRecordWriter | None`
    - `on_learning_record: Callable[[LearningRecord], None] | None`
  - Extend the main `run` (or `run_full_pipeline`) flow so that, *per variant*:
    - It assembles a `LearningRecord` from the current variant config + timing data.
    - If `config.learning_enabled` and either `learning_writer` or `on_learning_record` is provided:
      - It writes the record via `learning_writer`, if present.
      - It invokes `on_learning_record(record)` for subscribers, if present.
    - Any exception during learning record emission is **caught and logged** but does not fail the pipeline run.

This keeps learning as a **side channel**: if anything about learning breaks, pipeline execution remains intact.

---

### 3.3 Controller hooks

**File:** `src/controller/pipeline_controller.py`

We keep the controller API small and explicit:

- New registration methods:
  - `register_learning_record_callback(self, callback: Callable[[LearningRecord], None]) -> None`
    - Stores a callback to be wired into the underlying `PipelineRunner`.
  - `clear_learning_record_callbacks(self) -> None`
    - For tests and future lifecycle management.

- Runner construction logic:
  - When the controller instantiates `PipelineRunner`, it:
    - Provides the `learning_writer` (if globally configured).
    - Wraps all registered callbacks into a single `on_learning_record` aggregate.
  - The controller **does not** interpret the records; it just forwards them.

- Testing hook:
  - `get_learning_runner_for_tests()` returns the active runner (or a synthetic stub) to make test assertions straightforward.

The GUI and future multi‑node farm code will subscribe via `register_learning_record_callback` and can, for example, stream recent run records into a sidecar learning service or local JSONL files.

---

## 4. Implementation Notes

### 4.1 Error handling

- Learning emission is intentionally **best effort**:
  - All failure modes in `LearningRecordWriter` and callbacks are caught.
  - Errors are logged via the existing structured logger but never thrown back to the runner.
- If `learning_enabled` is `False` or no writer/callback is attached, `PipelineRunner` behaves exactly as before.

### 4.2 Performance

- Record creation is lightweight (mostly dict building and JSON serialisation).
- IO is append‑only and can be redirected to a fast disk or temp directory for heavy experimentation.
- Future PRs can add batching or async flushing if needed; this one deliberately keeps it simple.

### 4.3 Compatibility

- No breaking changes to existing GUI entrypoints.
- New imports (`src.learning.learning_record`) are confined to:
  - `src/pipeline/pipeline_runner.py`
  - `src/controller/pipeline_controller.py`
  - `tests/learning/*`
- Safety guards remain in place: utils and randomizer modules still avoid GUI imports.

---

## 5. Tests

New tests under `tests/learning`:

1. `tests/learning/test_learning_record_serialization.py`
   - Asserts round‑trip `LearningRecord → dict/json → LearningRecord`.
   - Verifies required fields are present and optional fields default correctly.
   - Confirms timestamp and run_id handling is stable.

2. `tests/learning/test_learning_hooks_pipeline_runner.py`
   - Uses a dummy `LearningRecordWriter` that stores records in memory.
   - Runs `PipelineRunner` with a small, fake variant plan.
   - Asserts:
     - Number of emitted records == number of variants executed.
     - Records contain the expected model/CFG/steps/prompt metadata.
     - Errors in the writer do not break the run.

3. `tests/learning/test_learning_hooks_controller.py`
   - Constructs a `PipelineController` with a fake runner.
   - Registers one or more callbacks via `register_learning_record_callback`.
   - Simulates a run that emits a small number of synthetic records.
   - Verifies:
     - All callbacks are invoked.
     - The callbacks see the same `LearningRecord` instances the runner produced.

Regression:

- `pytest tests/learning -v`
- `pytest tests/gui_v2 -v`
- `pytest -v`

All pass, with any existing Tk/Tcl skips remaining unchanged.

---

## 6. Acceptance Criteria

- [ ] `src/learning/learning_record.py` defines a stable LearningRecord model and writer.
- [ ] `PipelineConfig` gains optional learning metadata fields without breaking existing call sites.
- [ ] `PipelineRunner` can emit learning records per variant when enabled, without affecting core behavior or error paths.
- [ ] `PipelineController` exposes `register_learning_record_callback` and wires callbacks into the runner.
- [ ] Learning tests pass and are deterministic.
- [ ] Full `pytest -v` passes (aside from known Tk/Tcl skips in GUI tests, if any).

---

## 7. Rollout / Future Work

Follow‑on PRs (already sketched at the roadmap level):

- `PR-GUI-V2-LEARNING-MODE-UI-00x`
  - Expose a “Learning Mode” toggle in the v2 GUI and a minimal “recent learning runs” panel.
  - Surface per‑run metadata and allow navigating into a future “rating” view.

- `PR-GUI-V2-LEARNING-RUNNER-INTEGRATION-00x`
  - Use the controller’s learning callbacks to show progress about learning runs and to push records into a local JSONL file per prompt pack/preset.

- `PR-AI-V2-SETTINGS-GENERATOR-001` (already on the roadmap)
  - Consume `LearningRecord` JSONL streams in an LLM‑backed assistant that proposes improved configs and presets.

This PR is the backbone: it ensures every subsequent learning feature has a single, well‑tested source of truth for what “one run” means.  
