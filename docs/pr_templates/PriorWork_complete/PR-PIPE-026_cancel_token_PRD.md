# PR-PIPE-026 — CancelToken integration: clean early-out at pipeline boundaries

## 1. Title
PR-PIPE-026 — CancelToken integration: clean early-out at pipeline boundaries

## 2. Summary
Several tests around cancellation and pipeline early-out are failing because `CancellationError` raised by `_ensure_not_cancelled` bubbles up past the pipeline entry points, instead of being caught and converted into a clean early return.

This PR updates the pipeline executor so that:

- `CancellationError` continues to be raised at stage boundaries (txt2img/img2img/upscale) via `_ensure_not_cancelled`.
- Public pipeline methods (`run_txt2img`, `run_img2img`, `run_full_pipeline`, etc.) catch `CancellationError`, log a “pipeline cancelled” message, and return an appropriate empty result (usually an empty list), rather than propagating the exception to callers.
- CancelToken-focused tests are updated (if needed) to assert the new, consistent behavior.

## 3. Problem Statement
Architecture_v2 requires that:

- CancelToken is honored between every stage.
- Pipeline runs can be cancelled cleanly without crashing the GUI or controller.

Currently, `_ensure_not_cancelled` correctly raises `CancellationError` in the pipeline, but the exception is not consistently caught at the pipeline boundaries. As a result:

- Tests that expect `run_txt2img` / `run_full_pipeline` to return an empty result when cancellation occurs see an uncaught `CancellationError` instead.
- GUI/controller may receive unexpected exceptions rather than a well-defined “cancelled” outcome.

## 4. Goals
1. Make `run_txt2img`, `run_img2img`, `run_full_pipeline`, and any similar entry points catch `CancellationError` and return a clean early-out result instead of propagating the exception.
2. Preserve the fine-grained cancellation checks inside the pipeline using `_ensure_not_cancelled`.
3. Align CancelToken integration tests with the intended behavior (no crashes, early-out with empty results, logging a clear cancellation message).

## 5. Non-goals
- No changes to GUI or controller modules.
- No changes to randomizer/matrix logic.
- No changes to logging/manifests beyond a minimal “pipeline cancelled” info-level log where the exception is caught.
- No changes to sampler/scheduler logic (that was PR-PIPE-024).
- No ADetailer-specific changes.

## 6. Allowed Files
- `src/pipeline/executor.py` (or whichever module owns `Pipeline.run_*` methods).
- `tests/test_cancel_token.py` (and/or the closest existing CancelToken-focused test module).

## 7. Forbidden Files
- Any files under `src/gui/`.
- Any files under `src/controller/`.
- Any files under `src/utils/` other than the pipeline executor module (no randomizer/logger changes).
- Any configuration or build files.

## 8. Step-by-step Implementation

### 8.1 Catch `CancellationError` in pipeline entry points
1. Open `src/pipeline/executor.py` and locate public-facing pipeline methods, e.g.:
   - `Pipeline.run_txt2img(...)`
   - `Pipeline.run_img2img(...)`
   - `Pipeline.run_full_pipeline(...)`

2. For each of these methods, wrap the existing internal-stage calls in a `try/except CancellationError` block. Example pattern:

   - Before (conceptual):

     - `images = self._run_txt2img_internal(config, cancel_token)`
     - `return images`

   - After (conceptual):

     - `try:`
         - `images = self._run_txt2img_internal(config, cancel_token)`
         - `return images`
       - `except CancellationError as exc:`
         - `logger.info("Pipeline cancelled (%s); returning early.", exc)`
         - `return []`

3. Apply equivalent handling to `run_full_pipeline` so that any `CancellationError` from txt2img/img2img/upscale results in a logged “cancelled” message and an empty result (or other appropriate sentinel defined by your existing tests).

### 8.2 Keep `_ensure_not_cancelled` behavior unchanged
4. Confirm that `_ensure_not_cancelled(cancel_token, context)` continues to check `cancel_token.is_cancelled()` and raise `CancellationError` with a context-specific message. Do not weaken this function; it is still responsible for triggering cancellation at key checkpoints.

### 8.3 Align CancelToken tests
5. Open `tests/test_cancel_token.py` (or equivalent). For each test that checks cancellation behavior at the pipeline level:
   - Ensure that when cancellation is triggered mid-run, the test asserts:
     - The pipeline method returns an empty result (e.g., `[]`) rather than raising.
     - If the test currently expects an exception from `run_*`, update it to expect a clean early-out instead.
   - Preserve any lower-level unit tests that directly exercise `_ensure_not_cancelled` and *do* expect a `CancellationError` to be raised; those tests should not change.

6. If there are tests verifying that no further stages run after cancellation (e.g., no upscale after txt2img cancellation), keep those assertions and ensure the revised implementation honors them.

## 9. Required Tests
After implementing the changes:

- Run the CancelToken-focused tests:

  - `pytest tests/test_cancel_token.py -v`

- Then run relevant pipeline tests (if present), e.g.:

  - `pytest tests/pipeline -v`

- Finally, run the full test suite:

  - `pytest`

## 10. Acceptance Criteria
- Pipeline entry points (`run_txt2img`, `run_img2img`, `run_full_pipeline`) return cleanly when cancellation occurs, rather than propagating `CancellationError` to callers.
- CancelToken tests that exercise pipeline-level behavior pass and assert early-out semantics (empty results, no crashes).
- Unit tests for `_ensure_not_cancelled` still verify that it raises `CancellationError` when appropriate.
- No GUI or controller code is modified.
- Full test suite passes.

## 11. Rollback Plan
- Revert changes to:
  - `src/pipeline/executor.py`
  - `tests/test_cancel_token.py`
- Re-run the full test suite to confirm behavior returns to the prior state.
