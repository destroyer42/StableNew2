# PR-PIPE-025 — Align config passthrough tests with sampler/scheduler normalization

## 1. Title
PR-PIPE-025 — Align config passthrough tests with sampler/scheduler normalization

## 2. Summary
PR-PIPE-024 updated `src/utils/config.py` to normalize sampler and scheduler values and, when a real scheduler is selected (e.g. `Karras`), serialize them as:

- `sampler_name = "<sampler> <scheduler>"` (e.g. `DPM++ 2M Karras`)
- `scheduler    = "<scheduler>"` (e.g. `Karras`)

Some existing config passthrough tests still assert the old behavior (sampler name only and/or no explicit scheduler). This PR updates those tests so that:

- Their expectations match the new sampler/scheduler contract.
- They remain the single source of truth for payload serialization behavior.

No runtime behavior changes are allowed in this PR.

## 3. Problem Statement
After PR-PIPE-024, helper tests for sampler/scheduler behavior pass, but at least one existing passthrough test still expects:

- `payload["sampler_name"] == "DPM++ 2M"`

while the actual payload now (correctly) uses:

- `payload["sampler_name"] == "DPM++ 2M Karras"`
- `payload["scheduler"] == "Karras"`

This mismatch causes false negatives in the test suite. We need to align the tests with the new behavior without touching production code.

## 4. Goals
1. Update config passthrough tests to assert the new sampler/scheduler contract:
   - Combined sampler + scheduler in `sampler_name` when a real scheduler is specified.
   - Explicit `scheduler` field when a real scheduler is specified.
   - Scheduler field absent when the scheduler is logically “unset”.
2. Keep tests the authoritative specification for the sampler/scheduler payload behavior.
3. Make no changes to `src/utils/config.py` or other runtime code.

## 5. Non-goals
- No modifications to `src/utils/config.py` logic.
- No changes to GUI, controller, pipeline, randomizer, or logging.
- No ADetailer changes (those remain for a separate PR).

## 6. Allowed Files
- `tests/test_config_passthrough.py`

## 7. Forbidden Files
- All files under `src/` (including `src/utils/config.py`).
- All other `tests/` modules.
- Any configuration files (pyproject, requirements, etc.).

If you believe a production change is required, stop and request a new PR design.

## 8. Step-by-step Implementation

1. Open `tests/test_config_passthrough.py` and locate the tests that assert sampler/scheduler behavior for txt2img and img2img payloads (e.g., `test_config_passthrough_txt2img`, `test_config_passthrough_img2img`, or similar).

2. For cases where the test config includes both a sampler and a non-empty scheduler (e.g., sampler `DPM++ 2M` and scheduler `Karras`), update expectations so that they assert:

   - `payload["sampler_name"] == "<sampler> <scheduler>"` (e.g. `DPM++ 2M Karras`)
   - `payload["scheduler"] == "<scheduler>"` (e.g. `Karras`)

   instead of asserting just the sampler name.

3. For cases where the tests expect no scheduler (None, empty, `"None"`, or `"Automatic"` in the config), ensure they assert:

   - `payload["sampler_name"]` is the bare sampler (e.g. `DPM++ 2M`).
   - `"scheduler" not in payload`.

4. Where appropriate, consider re-using the helper `build_sampler_scheduler_payload` inside the tests to compute the “expected” values, rather than hardcoding strings. This keeps tests resilient to small formatting tweaks.

5. Do not change how other config fields (steps, cfg_scale, width, height, etc.) are asserted.

## 9. Required Tests
After updating the tests, run:

- `pytest tests/test_config_passthrough.py -v`

Then, as a sanity check, run:

- `pytest` (full suite) to ensure no unintended side effects.

## 10. Acceptance Criteria
- All tests in `tests/test_config_passthrough.py` pass.
- The expectations in those tests clearly match the sampler/scheduler contract introduced by PR-PIPE-024.
- No production code changes are made.
- Full test suite remains green.

## 11. Rollback Plan
- Revert changes to `tests/test_config_passthrough.py`.
- Re-run the full test suite to confirm behavior is back to the prior state.
