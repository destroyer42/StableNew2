# PR-PIPE-024 — Main sampler/scheduler normalization (no ADetailer changes)

## 1. Title
PR-PIPE-024 — Main sampler/scheduler normalization (no ADetailer changes)

## 2. Summary
This PR focuses solely on normalizing how the main pipeline (txt2img/img2img) passes sampler and scheduler information to the Stable Diffusion WebUI API.

It introduces a small helper in the config layer that:
- Avoids sending an explicit scheduler value of "None" or "Automatic" when we intend to let WebUI choose its default.
- Encodes the chosen scheduler both as:
  - A combined sampler string (for example "DPM++ 2M Karras") for backward compatibility.
  - A separate "scheduler" field for newer WebUI APIs.

No GUI, controller, or ADetailer UI changes are included in this PR.

## 3. Problem Statement
Current logs show messages like:

- Sampler Scheduler autocorrection: "DPM++ 2M" -> "DPM++ 2M", "None" -> "Automatic"

This indicates that:
- The payload being sent to WebUI includes something like scheduler = "None".
- WebUI interprets that as invalid and silently changes it to its default "Automatic".
- The user’s intended scheduler (for example "Karras") is not always faithfully preserved in the payload.

This PR addresses the sampler/scheduler handling at the main payload-building layer without touching ADetailer or GUI controls.

## 4. Goals
1. Introduce a centralized helper that normalizes scheduler values and builds sampler/scheduler fields for the main WebUI payload.
2. Ensure that when a concrete scheduler is set (for example "Karras"):
   - The payload includes a combined sampler name (for backward compatibility), such as "DPM++ 2M Karras".
   - The payload includes an explicit "scheduler" field with that scheduler name.
3. Ensure that when the scheduler is effectively "unset" (None, empty string, "None", or "Automatic"):
   - The payload only includes "sampler_name" and does not include a "scheduler" field, allowing WebUI to choose its default without logging autocorrections.
4. Add focused tests to lock in this behavior.

## 5. Non-goals
- No GUI changes of any kind.
- No ADetailer-specific changes (those remain in the separate PR-PIPE-023).
- No modifications to controller, pipeline stages, randomizer/matrix logic, or logging.
- No changes to configuration file formats or schemas.

## 6. Allowed Files
The PR may modify/add only the following files:

- src/utils/config.py
  - Central sampler/scheduler helper.
  - Integration into existing txt2img/img2img payload builders.
- tests/test_config_passthrough.py
  - New tests for sampler/scheduler normalization and payload behavior.

## 7. Forbidden Files
Do not modify:

- Any files under src/gui/.
- Any files under src/controller/.
- Any files under src/pipeline/.
- Any randomizer/matrix-related modules under src/utils/.
- Any logger or manifest-writing modules under src/utils/.
- Any configuration or build files (pyproject.toml, requirements, etc.).

If a change appears necessary outside the allowed files, stop and request a new PR design.

## 8. Step-by-step Implementation

### 8.1 Add sampler/scheduler helper in src/utils/config.py
1. In src/utils/config.py, add a private helper:

   - Name: _normalize_scheduler_name(scheduler)
   - Behavior:
     - If scheduler is None, return None.
     - Trim whitespace; if the trimmed string is empty, return None.
     - If the lowercased value is "none" or "automatic", return None (meaning no explicit scheduler).
     - Otherwise, return the trimmed string as-is.

2. In the same file, add a helper:

   - Name: build_sampler_scheduler_payload(sampler_name, scheduler_name)
   - Behavior:
     - Accepts optional sampler_name and scheduler_name.
     - Creates a dict payload.
     - If sampler_name is empty or missing after stripping, return an empty dict.
     - Use _normalize_scheduler_name to normalize scheduler_name.
     - If the normalized scheduler is not None:
       - Set payload["sampler_name"] to "<sampler> <scheduler>" (sampler plus a space plus scheduler).
       - Set payload["scheduler"] to the normalized scheduler value.
     - If the normalized scheduler is None:
       - Set payload["sampler_name"] to the sampler only.
       - Do not set payload["scheduler"].

### 8.2 Use helper in txt2img/img2img payload builders
3. Find the functions in src/utils/config.py that build the WebUI txt2img and img2img payloads (they might be named like build_txt2img_payload, build_img2img_payload, or similar).
4. In each payload builder, replace any direct assignments of sampler_name and scheduler (for example payload["sampler_name"] = ..., payload["scheduler"] = ...) with a call to build_sampler_scheduler_payload.
   - Example pattern:
     - Remove or comment out the previous sampler_name/scheduler lines.
     - Add:

       - sampler_scheduler = build_sampler_scheduler_payload(
           sampler_name=config.sampler_name,
           scheduler_name=getattr(config, "scheduler_name", None),
         )
       - payload.update(sampler_scheduler)

   - Adjust field access (for instance config.sampler or config.sd_sampler) to match the actual RunConfig attributes in your tree.

5. Ensure that there is no remaining code in config.py that directly sets payload["scheduler"] based on sentinel values like "None" or "Automatic". All logic should go through build_sampler_scheduler_payload.

### 8.3 Tests in tests/test_config_passthrough.py
6. In tests/test_config_passthrough.py, add tests for the new helper and behavior.
   - If there already is a config passthrough test module, extend it; otherwise, add focused tests near similar behavior.

   Recommended tests:

   - test_sampler_scheduler_passthrough_with_explicit_scheduler
     - Given sampler_name "DPM++ 2M" and scheduler_name "Karras":
       - payload["sampler_name"] == "DPM++ 2M Karras"
       - payload["scheduler"] == "Karras"

   - test_sampler_scheduler_passthrough_without_scheduler
     - For each scheduler_name in (None, "", "None", "none", "Automatic", "automatic"):
       - payload["sampler_name"] == "DPM++ 2M"
       - "scheduler" not in payload

   These tests can call build_sampler_scheduler_payload directly, or they can go through a minimal dummy RunConfig if that better matches your testing conventions.

## 9. Required Tests (Failing first)
Before implementing the helper and wiring it into the payload builders, add tests in tests/test_config_passthrough.py that describe the desired behavior and verify they fail under the current implementation.

Required tests:

- test_sampler_scheduler_passthrough_with_explicit_scheduler
- test_sampler_scheduler_passthrough_without_scheduler

Then implement the helper and payload changes until these tests pass.

## 10. Acceptance Criteria
- New tests in tests/test_config_passthrough.py pass, specifically the ones covering sampler/scheduler behavior.
- No changes were made outside src/utils/config.py and tests/test_config_passthrough.py.
- When a real scheduler is set (for example "Karras"), the outgoing payload:
  - Uses a combined sampler_name that includes the scheduler name.
  - Includes an explicit "scheduler" field with that scheduler name.
- When scheduler_name is None, empty, "None", or "Automatic":
  - The payload does not contain a "scheduler" key.
  - The payload still contains a valid "sampler_name".
- Existing tests in the suite remain green.

## 11. Rollback Plan
- Revert changes to:
  - src/utils/config.py
  - tests/test_config_passthrough.py
- Run the full test suite to confirm behavior is restored to the prior baseline.
- This PR does not change persistent data formats, so rollback is code-only.

## 12. Codex Execution Constraints
- Modify only src/utils/config.py and tests/test_config_passthrough.py.
- Do not introduce new modules or alter existing public APIs beyond what is described.
- Do not refactor unrelated functions or clean up surrounding code.
- If you find that another part of the code seems to require change, stop and request a new PR design rather than making assumptions.

After implementing the changes:

- Run:
  - pytest tests/test_config_passthrough.py -k scheduler -v
  - pytest (entire suite) to ensure there are no regressions.

## 13. Smoke Test Checklist
After tests pass, perform a brief manual verification:

1. Start StableNew and trigger a txt2img run with a specific sampler and scheduler (for example DPM++ 2M + Karras).
2. Confirm, via WebUI logs or PNG metadata, that:
   - The sampler_name shows the combined form including the scheduler where appropriate.
   - The scheduler field matches the selected scheduler.
3. Trigger a txt2img run with the scheduler left at a default or "Automatic" state.
4. Confirm that:
   - No "Sampler Scheduler autocorrection" messages appear due to scheduler = "None" being sent.
   - The images generate successfully.
5. Repeat for img2img if applicable, verifying that behavior is consistent between stages.
