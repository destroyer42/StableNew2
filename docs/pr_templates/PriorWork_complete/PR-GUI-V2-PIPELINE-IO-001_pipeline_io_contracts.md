# PR-GUI-V2-PIPELINE-IO-001 – Pipeline I/O Contracts and Learning Record Integration

## 1. Title

Pipeline I/O contracts, run result modeling, and learning record integration (controller/pipeline v2)

## 2. Summary

This PR formalizes the input/output contracts for the v2 pipeline runner and its controller wrapper, including the learning‑record hooks that were recently added. It introduces a clearly documented, test‑backed model of:

- What goes into the pipeline runner (PipelineConfig + variant/learning metadata).
- What comes out of a run (PipelineRunResult‑like structure and/or explicit return value shape).
- How learning records are emitted and consumed in a deterministic way.

The goal is to reduce ambiguity and duplication in how pipeline runs are invoked and observed, and to ensure that future features (learning runs, AI‑assisted settings, distributed execution) can rely on a stable contract.

This PR is focused on **contracts and tests**, not on user‑visible behavior changes.

## 3. Problem Statement

The current refactor work has:
- A `PipelineConfig` in `src/pipeline/pipeline_runner.py` that captures run parameters.
- A `PipelineRunner` that knows how to fan out variants and emit learning records if provided a writer/callback.
- Controller‑level hooks that forward learning‑related data.
- Learning record dataclasses and JSON helpers (`src/learning/learning_record.py`).

However, the overall pipeline I/O picture still has gaps:

- There is no single “source of truth” for what the pipeline returns, and how success/error/partial‑success are represented.
- Learning record emission is present but not rigorously documented/tested as an end‑to‑end contract.
- GUI v2 and future consumers (CLI, automation) will need a stable, well‑typed view of “what happened in this run” beyond just log lines.

Without tightening these contracts now, future features (learning, one‑click actions, adaptive presets) risk re‑introducing ambiguity and ad‑hoc data structures.

## 4. Goals

1. Define and document a **stable pipeline output contract** for v2, aligned with `ARCHITECTURE_v2`.
   - Inputs: `PipelineConfig` + optional variant/learning metadata.
   - Outputs: an explicit run result structure and/or well‑defined return semantics from `PipelineRunner.run` and the controller wrapper.

2. Make **learning record emission** a first‑class, test‑backed behavior:
   - Ensure `PipelineRunner` and `pipeline_controller` consistently use `learning_record.LearningRecord` and `LearningRecordWriter` (or their wrappers).
   - Add tests that validate record creation, serialization, and hook invocation.

3. Preserve existing v2 behavior:
   - No change in how the current GUI v2 triggers runs.
   - No change in external file formats beyond learning record JSON (which is already new and under our control).

4. Keep all contracts **GUI‑free**:
   - Pipeline and controller contracts must not import Tk or GUI modules.
   - Learning integration remains fully non‑UI.

## 5. Non‑Goals

- No changes to randomizer behavior or UI.
- No learning‑mode GUI yet (learning runs remain stubbed from the GUI angle).
- No distributed execution or multi‑node scheduling.
- No major restructuring of pipeline stages; we operate within the existing stage boundaries.

## 6. Allowed Files

Pipeline/core:

- `src/pipeline/pipeline_runner.py`
- `src/pipeline/__init__.py` (only for exporting new dataclasses/types, if needed)

Controller:

- `src/controller/pipeline_controller.py`

Learning:

- `src/learning/learning_record.py`
- `src/learning/learning_runner.py`
- `src/learning/learning_plan.py`
- `src/learning/learning_adapter.py`

Tests:

- `tests/pipeline/test_pipeline_io_contracts.py` (new)
- `tests/pipeline/test_pipeline_runner_variants.py` (new)
- `tests/learning/test_learning_record_serialization.py` (extend only if necessary)
- `tests/learning/test_learning_hooks_pipeline_runner.py`
- `tests/learning/test_learning_hooks_controller.py`
- `tests/learning/test_learning_adapter_stub.py`

Config / schemas (if already present and relevant):

- `docs/schemas/*` (only if a pipeline I/O schema file already exists and needs a minor update)
- `docs/history/StableNew_History_Summary.md` (read‑only context; do not modify)

## 7. Forbidden Files

- GUI layers (`src/gui/*`, `tests/gui*`).
- API client code (`src/api/*`).
- Structured logger implementations (`src/utils/structured_logger.py`).
- Any configuration unrelated to pipeline I/O and learning (e.g., prompt packs, presets).

If a change to a forbidden file is discovered to be unavoidable, stop and request an updated PR scope.

## 8. Step‑by‑Step Implementation Plan

1. **Audit current pipeline inputs/outputs**
   - Inspect `PipelineConfig` and `PipelineRunner.run` in `src/pipeline/pipeline_runner.py`.
   - Inspect the controller–runner integration in `src/controller/pipeline_controller.py`.
   - Inspect `LearningRecord`, `LearningRecordWriter`, and any runner/controller hooks in the `src/learning` modules.

2. **Define a PipelineRunResult model (if not already present)**
   - Introduce a `PipelineRunResult` dataclass in `src/pipeline/pipeline_runner.py` or a nearby module.
   - Include at least:
     - run_id or correlation id (if available).
     - success flag and/or error information.
     - count of variants produced (even if currently just 1).
     - optional learning record references (e.g., list of record file paths or records emitted).
   - Keep this minimal and aligned with current capabilities.

3. **Align PipelineRunner.run signature & behavior**
   - Ensure `PipelineRunner.run` (or equivalent) returns either:
     - a `PipelineRunResult`, or
     - a clearly documented type (e.g., `list[PipelineRunResult]` if variant‑wise).
   - Document assumptions in docstrings:
     - How cancellation is represented.
     - How errors are reported.
   - Make sure this does not break existing callers (controller, tests) by adjusting them accordingly.

4. **Integrate LearningRecord consistently**
   - Confirm that `PipelineRunner` uses `LearningRecord` and `LearningRecordWriter` from `src/learning/learning_record.py`.
   - Ensure that, for each run (or per variant, depending on current behavior), the runner:
     - Builds a `LearningRecord` via `from_pipeline_context` or equivalent helpers.
     - Serializes it through the writer in a deterministic way.
   - Ensure the controller has a clean hook to react to the learning records if needed (even if currently unused by the GUI).

5. **Controller contract updates**
   - In `src/controller/pipeline_controller.py`, document the contract between the controller and the pipeline runner:
     - What the controller expects to receive from the runner.
     - How it exposes that result to higher layers (GUI v2, tests).
   - If needed, add a property or method (read‑only) exposing the last `PipelineRunResult` for testing & future GUI use.

6. **Update or add tests for pipeline I/O**
   - Add `tests/pipeline/test_pipeline_io_contracts.py` to validate:
     - Creating a `PipelineConfig` with representative settings.
     - Running the pipeline via `PipelineRunner` (with a stubbed API client) returns the expected result object(s).
     - `PipelineRunResult` fields are populated as expected.
   - Add `tests/pipeline/test_pipeline_runner_variants.py` to validate:
     - Behavior when multiple variants (fanout/plan) are involved, ensuring each has a corresponding result/record.

7. **Update/extend learning tests**
   - Extend `tests/learning/test_learning_record_serialization.py` only if the record shape changes (ideally it doesn’t).
   - Ensure `tests/learning/test_learning_hooks_pipeline_runner.py` and `tests/learning/test_learning_hooks_controller.py` cover:
     - Correct invocation of learning hooks when pipeline runs succeed.
     - Safe behavior when learning writer is absent or disabled.
   - Keep learning tests GUI‑free and deterministic.

8. **Documentation comments**
   - Add concise but clear docstrings around `PipelineConfig`, `PipelineRunResult`, and the main run method describing the input/output contract.
   - Document how learning records are hooked into the pipeline, including any expectations about file paths or JSON format.

## 9. Required Tests (Failing First)

Before implementing the contract tightening, add/extend tests so they fail against the current codebase:

1. `tests/pipeline/test_pipeline_io_contracts.py`
   - Expects a `PipelineRunResult` (or equivalent) with specific fields present and correctly typed.

2. `tests/pipeline/test_pipeline_runner_variants.py`
   - Expects variant runs to yield a predictable list/collection of results.

3. `tests/learning/test_learning_hooks_pipeline_runner.py`
   - Expects the learning writer to be called with the right record(s) in response to a completed run.

4. `tests/learning/test_learning_hooks_controller.py`
   - Expects controller‑level learning hooks to behave consistently in response to runner outputs.

Run:
- `pytest tests/pipeline -v`
- `pytest tests/learning -v`

Expect RED until the pipeline I/O and learning integrations are fully aligned.

## 10. Acceptance Criteria

- All pipeline and learning tests pass:
  - `pytest tests/pipeline -v`
  - `pytest tests/learning -v`
- `pytest -v` passes (GUI v2 tests remain green; known Tk skip is acceptable).
- `PipelineRunner` and `pipeline_controller` have clear, documented input/output contracts.
- Learning records are emitted deterministically and covered by tests.
- No GUI files import pipeline or learning modules directly (contracts remain controller/pipeline/learning only).

## 11. Rollback Plan

- Revert changes in `src/pipeline/pipeline_runner.py`, `src/controller/pipeline_controller.py`, and `src/learning/*` to the previous commit.
- Revert any new/updated tests if they no longer match the contract.
- Because this PR is primarily about internal contracts and tests, rollback should have no user‑visible impact.

## 12. Codex Execution Constraints

- Do NOT modify GUI code or tests in this PR.
- Do NOT introduce new external dependencies.
- Keep the I/O contracts small, focused, and well‑documented.
- Follow TDD: add tests first, then update implementation until tests pass.
- Keep changes backward compatible with the current v2 behavior.

## 13. Smoke Test Checklist (Post‑Merge)

1. Run `pytest -v` and confirm all tests (including learning and pipeline) pass.
2. Launch StableNew GUI v2 (manual) and:
   - Trigger a simple run and confirm there are no pipeline‑level errors.
   - Confirm learning record files (if enabled) are written where expected and are valid JSON.

---

## Codex Chat Instructions for PR-GUI-V2-PIPELINE-IO-001

Paste the following text into Codex Chat for this PR:

PR NAME: PR-GUI-V2-PIPELINE-IO-001 – Pipeline I/O Contracts and Learning Record Integration

ROLE: You are acting as the Implementer (Codex) for the StableNew project. Your job is to tighten and document the pipeline input/output contracts and learning record integration, without changing user‑visible behavior.

CURRENT REPO STATE: Use the current StableNew repo on my machine as truth, including the recent learning stack additions:
- `src/learning/learning_record.py` with LearningRecord, JSON helpers, and LearningRecordWriter.
- `src/pipeline/pipeline_runner.py` with PipelineConfig and learning hooks.
- `src/controller/pipeline_controller.py` with learning hook plumbing.
Do not assume older branches; work from HEAD of my current MoreSafe branch.

OBJECTIVE:
- Define and validate a clear input/output contract for the v2 pipeline runner.
- Ensure learning records are emitted and consumed deterministically.
- Add tests that lock this behavior in place.

HARD CONSTRAINTS:
- Do NOT modify any GUI files or tests in this PR.
- Do NOT change user‑visible behavior.
- Do NOT introduce new dependencies.
- Keep learning and pipeline modules GUI‑free.
- Follow TDD: add/extend tests first, then update the implementation.

IMPLEMENTATION STEPS (HIGH LEVEL):
1) Audit `PipelineConfig`, `PipelineRunner.run`, and controller integration to understand current behavior.
2) Introduce or refine a `PipelineRunResult` (or equivalent) dataclass that captures the essential outcome of a run.
3) Align `PipelineRunner.run` and the controller wrapper so they consistently return or expose this result.
4) Ensure learning record emission is wired through `LearningRecord` and `LearningRecordWriter` with deterministic behavior.
5) Add/extend tests:
   - `tests/pipeline/test_pipeline_io_contracts.py`
   - `tests/pipeline/test_pipeline_runner_variants.py`
   - `tests/learning/test_learning_hooks_pipeline_runner.py`
   - `tests/learning/test_learning_hooks_controller.py`
6) Update docstrings/comments to clearly describe the new/clarified contracts.

TEST COMMANDS TO RUN AND REPORT:
- pytest tests/pipeline -v
- pytest tests/learning -v
- pytest -v

When you’re done, summarize:
- Files touched (with +/- line counts).
- The final shape of the pipeline input/output contract.
- How learning records are emitted and validated.
- Full pytest outputs for the commands above.
