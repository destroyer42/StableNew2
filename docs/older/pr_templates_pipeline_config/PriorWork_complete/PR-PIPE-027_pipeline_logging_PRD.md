# PR-PIPE-027 — Pipeline early-out consistency and cancellation logging polish

## 1. Title
PR-PIPE-027 — Pipeline early-out consistency and cancellation logging polish

## 2. Summary
After PR-PIPE-026, pipeline entry points will handle `CancellationError` by logging a simple message and returning an empty result. This PR standardizes cancellation behavior and logging across all pipeline entry points and (optionally) ensures that StructuredLogger or any manifest-writing logic records a clear “cancelled” status.

The goal is to make cancellation semantics fully predictable and observable while keeping the implementation small and focused.

## 3. Problem Statement
Even with `CancellationError` caught at pipeline boundaries, there may still be:

- Inconsistent log messages (different wording or log levels for cancellation in different methods).
- Inconsistent handling of partially produced outputs or manifests when cancellation occurs mid-run.
- Limited visibility into the difference between “hard error” and “user-initiated cancellation” in logs and (if applicable) manifests.

This PR provides a small, focused polish pass to make cancellation behavior and logging consistent.

## 4. Goals
1. Standardize cancellation logging across `run_txt2img`, `run_img2img`, `run_full_pipeline`, and any related helpers.
2. Ensure that manifest/logging layers (e.g., StructuredLogger) distinguish “cancelled” from “success” and “error”, if such a status is already modeled.
3. Add or adjust tests to verify that cancellation results in:
   - Predictable log messages.
   - Appropriate status indicators (where applicable).
   - No accidental marking of cancelled runs as “success” or generic “error”.

## 5. Non-goals
- No changes to CancelToken semantics or `_ensure_not_cancelled` behavior.
- No changes to sampler/scheduler behavior.
- No GUI or controller changes.
- No new features or additional pipeline stages.

## 6. Allowed Files
- `src/pipeline/executor.py`
- Structured logging/manifest module (e.g., `src/utils/structured_logger.py` or equivalent, if present).
- One or more focused test modules, such as:
  - `tests/test_cancel_token.py`
  - `tests/pipeline/test_pipeline_early_out.py`
  - or a new small test module for pipeline logging if that’s cleaner.

## 7. Forbidden Files
- All GUI modules (`src/gui/...`).
- All controller modules (`src/controller/...`).
- Randomizer/matrix modules under `src/utils/`.
- Configuration/build files.

## 8. Step-by-step Implementation

1. In `src/pipeline/executor.py`, pick a standard log format for cancellation, e.g.:

   - `logger.info("✋ Pipeline cancelled during %s; aborting remaining stages.", context)`

   or a close equivalent. Apply this consistently in all `except CancellationError` blocks added/modified in PR-PIPE-026.

2. If a StructuredLogger (or similar manifest writer) is used to record pipeline run metadata:
   - Introduce or reuse a status value that clearly indicates cancellation (e.g. `"cancelled"`).
   - Ensure that when a `CancellationError` is caught at the pipeline boundary, the manifest/record is written with status `"cancelled"` rather than `"success"` or generic `"error"`.
   - Keep the manifest schema unchanged if possible; if a status field already exists, reuse it rather than adding new fields.

3. Add or update tests to check cancellation logging/manifest behavior. For example:

   - A test that runs a pipeline with a pre-cancelled token and asserts:
     - No images are produced.
     - The log output (captured via `caplog`) includes the standardized “pipeline cancelled” message.
   - A test that inspects the manifest or StructuredLogger output to confirm that cancel status is used instead of success/error when cancellation occurs.

4. Ensure that successful runs and hard errors are not affected by these changes (status and logs should remain as before).

## 9. Required Tests
After implementing the changes:

- Run the new/updated logging-focused tests, e.g.:
  - `pytest tests/test_cancel_token.py -k log -v`
  - or the dedicated pipeline-logging test module.
- Run the full suite:
  - `pytest`

## 10. Acceptance Criteria
- All pipeline entry points log cancellation using a consistent format and log level.
- Any manifest/StructuredLogger output records a distinct “cancelled” status for cancelled runs.
- Cancellation does not get misreported as success or error.
- All existing tests remain green, and new logging/manifest tests pass.

## 11. Rollback Plan
- Revert changes to:
  - `src/pipeline/executor.py`
  - Any logging/manifest modules touched.
  - Related tests.
- Re-run the full test suite to confirm behavior is restored to the prior state.
