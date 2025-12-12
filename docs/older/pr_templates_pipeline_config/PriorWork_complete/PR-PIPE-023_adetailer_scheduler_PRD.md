# PR-PIPE-023 — ADetailer scheduler dropdown & sampler/scheduler normalization

## 1. Title
PR-PIPE-023 — ADetailer scheduler dropdown & sampler/scheduler normalization

## 2. Summary
This PR gives the ADetailer stage its own scheduler selection (to match the Stable Diffusion WebUI UX) and fixes sampler/scheduler normalization so that:
- We no longer send an explicit `"None"` scheduler that gets auto-corrected to `"Automatic"` in WebUI.
- The main pipeline (txt2img/img2img) and ADetailer can either **inherit** the main sampler/scheduler or explicitly override it with a specific scheduler (e.g., `Karras`).
- Payloads sent to WebUI use a centralized helper for sampler + scheduler serialization, so future changes are safe and consistent.

## 3. Problem Statement
Current logs show the following during runs that include ADetailer:

- `Sampler Scheduler autocorrection: "DPM++ 2M" -> "DPM++ 2M", "None" -> "Automatic"`

This implies:
- We are sending `scheduler = "None"` to WebUI.
- WebUI treats `"None"` as invalid and silently replaces it with its default `"Automatic"` scheduler.
- The user’s intended scheduler (e.g., `Karras`) is not consistently honored, especially for ADetailer, which has its own scheduler control in WebUI.

This breaks the expectation that StableNew’s ADetailer stage mirrors the WebUI ADetailer behavior and that selected schedulers are faithfully applied.

## 4. Goals
1. Add an **ADetailer scheduler dropdown** in the GUI that:
   - Defaults to **Inherit main scheduler**.
   - Allows selecting explicit schedulers (e.g., Karras, Exponential, Polynomial, etc.).
2. Introduce a **centralized sampler/scheduler normalization helper** that:
   - Avoids sending `"None"` or `"Automatic"` as explicit schedulers to WebUI when we intend to use the default.
   - Encodes the chosen scheduler both as:
     - A combined sampler string (e.g., `"DPM++ 2M Karras"`) for backwards compatibility.
     - A separate `scheduler` field for newer WebUI APIs.
3. Wire the helper into:
   - The main txt2img/img2img payload builders.
   - The ADetailer payload builder, with its own scheduler option.
4. Add tests to lock the behavior for both the main pipeline and ADetailer.

## 5. Non-goals
- Do **not** change any randomizer/matrix logic.
- Do **not** change how samplers/schedulers are surfaced in prompt pack definitions.
- Do **not** add new stages or change the overall pipeline structure.
- Do **not** change GUI layout beyond the ADetailer configuration panel.
- Do **not** touch controller lifecycle, CancelToken behavior, or threading.

## 6. Allowed Files
The PR should only modify/add the following files:

- `src/utils/config.py`
  - Central sampler/scheduler helper.
  - Integration into existing payload builders.
- `src/gui/adetailer_config_panel.py`
  - New ADetailer scheduler dropdown wired to the config.
- `tests/test_config_passthrough.py`
  - New tests for sampler/scheduler normalization and payload behavior.
- `tests/gui/test_adetailer_panel.py`
  - New/updated tests verifying the ADetailer scheduler control exists and persists the correct value.

## 7. Forbidden Files
Do **not** modify:

- Any files under `src/gui/` other than `adetailer_config_panel.py`.
- Any files under `src/controller/`.
- Any files under `src/pipeline/`.
- `src/utils/randomizer.py` or any randomizer/matrix-related modules.
- `src/utils/logger.py` or manifest-writing logic.
- Any `tools/` scripts.
- Any configuration files (`pyproject.toml`, `requirements.txt`, etc.).

If a change appears necessary outside the allowed files, STOP and request a follow-on PR design.

## 8. Step-by-step Implementation

### 8.1 Config: centralized sampler/scheduler helper
1. In `src/utils/config.py`, add:
   - `_normalize_scheduler_name(scheduler: Optional[str]) -> Optional[str]`
     - Treat `None`, `""`, `"None"` (case-insensitive) as “no scheduler”.
     - Treat `"Automatic"` (case-insensitive) as “no explicit scheduler” (we let WebUI choose its default and do **not** send a `scheduler` key).
   - `build_sampler_scheduler_payload(sampler_name: Optional[str], scheduler_name: Optional[str]) -> Dict[str, str]`:
     - If `sampler_name` is empty, return `{}` and let callers decide what to do.
     - If `normalized_scheduler` is present (e.g., `"Karras"`):
       - `payload["sampler_name"] = f"{sampler} {normalized_scheduler}"`
       - `payload["scheduler"] = normalized_scheduler`
     - If `normalized_scheduler` is `None`:
       - `payload["sampler_name"] = sampler`
       - Do **not** include a `scheduler` key.

2. Update the existing txt2img/img2img payload builder(s) to use this helper instead of setting `sampler_name` and `scheduler` separately.
   - Example (names may differ; adapt to real functions):
     - Find code in `config.py` that looks like it is building the WebUI txt2img/img2img payload.
     - Replace direct assignments to `payload["sampler_name"]` / `payload["scheduler"]` with:
       - A call to `build_sampler_scheduler_payload(...)` and `payload.update(...)`.

### 8.2 Config/State: ADetailer scheduler field
3. Identify the configuration object used for ADetailer (likely something like a dict or config section for ADetailer settings).
   - Add a new key/attribute:
     - Name: `adetailer_scheduler`
     - Default: `"inherit"`
   - This value will drive the ADetailer scheduler dropdown.

### 8.3 GUI: ADetailer scheduler dropdown
4. In `src/gui/adetailer_config_panel.py`:
   - Add a new `ttk.Combobox` (or equivalent) for the ADetailer scheduler, with:
     - Label: “ADetailer scheduler” (or similar).
     - Backing variable bound to the config/state key `adetailer_scheduler`.
     - Choices (values):
       - `"inherit"` → displayed as “Inherit main scheduler”.
       - `"Automatic"`
       - `"Karras"`
       - `"Exponential"`
       - `"Polynomial"`
       - Any other schedulers already supported by StableNew in the main sampler/scheduler UI.
   - On load, initialize the combobox from the config.
   - On save/apply, persist the combobox value back into the config/state.

### 8.4 Pipeline payload: ADetailer scheduler wiring
5. Find where the ADetailer alwayson-script payload is built (likely in `src/utils/config.py` or a helper nearby dealing with `alwayson_scripts["ADetailer"]`).
   - Add logic that:
     - Reads `adetailer_scheduler` from the config/state.
     - If `adetailer_scheduler == "inherit"`:
       - Do **not** set any explicit scheduler in the ADetailer payload; let ADetailer inherit the main sampler/scheduler and avoid sending `"None"`.
     - Else:
       - Use `_normalize_scheduler_name` to normalize `adetailer_scheduler`.
       - If it yields a real scheduler (e.g., `"Karras"`):
         - Set the appropriate ADetailer scheduler field in the payload (use the same key name the WebUI uses for ADetailer’s scheduler — inspect a WebUI-generated payload for reference).
       - If normalization yields `None` (including `"Automatic"`):
         - Omit the scheduler field and allow ADetailer to use its default behavior.

### 8.5 Tests
6. In `tests/test_config_passthrough.py`:
   - Add tests verifying sampler/scheduler payload behavior for the main pipeline, including:
     - With `sampler_name="DPM++ 2M", scheduler_name="Karras"`:
       - `payload["sampler_name"] == "DPM++ 2M Karras"`
       - `payload["scheduler"] == "Karras"`
     - With `sampler_name="DPM++ 2M"` and `scheduler_name` in `{None, "", "None", "none", "Automatic", "automatic"}`:
       - `payload["sampler_name"] == "DPM++ 2M"`
       - `"scheduler" not in payload`
   - If needed, use a dummy RunConfig-like object (e.g. `DummyRunConfig`) as a test helper, mirroring the fields used by the production payload builder.

7. In `tests/gui/test_adetailer_panel.py`:
   - Add/update tests to verify:
     - The ADetailer panel creates the scheduler dropdown widget.
     - The widget is initialized from `adetailer_scheduler`, defaulting to `"inherit"`.
     - Changes in the combobox value are saved back to config/state when the panel’s “apply/save” logic is invoked.

## 9. Required Tests (Failing first)
Before implementation, add/adjust tests so they initially fail:

1. `tests/test_config_passthrough.py`:
   - `test_sampler_scheduler_passthrough_with_explicit_scheduler`:
     - Assert combined sampler string + explicit scheduler when `scheduler_name="Karras"`.
   - `test_sampler_scheduler_passthrough_without_scheduler`:
     - Assert no `scheduler` key when scheduler is `None` / empty / `"None"` / `"Automatic"`.
2. `tests/gui/test_adetailer_panel.py`:
   - `test_adetailer_panel_has_scheduler_dropdown`:
     - Panel creation yields a scheduler dropdown.
   - `test_adetailer_scheduler_default_inherit`:
     - Default value is `"inherit"` when config is empty/fresh.
   - `test_adetailer_scheduler_persists_value`:
     - Changing the dropdown and saving the panel writes the value back to config.

After tests are in place and failing, implement the changes until they pass.

## 10. Acceptance Criteria
- No more WebUI warnings about `Sampler Scheduler autocorrection` due to `"None" -> "Automatic"` when StableNew is sending payloads.
- When the user selects `DPM++ 2M` + `Karras` in the main sampler/scheduler and leaves ADetailer set to “Inherit main scheduler”:
  - ADetailer actually uses `Karras` (confirmed via PNG info / API logs).
- When the user selects a specific ADetailer scheduler (e.g. `Euler a` or `Karras`):
  - ADetailer uses that scheduler even if the main pipeline uses a different one.
- All new tests in `tests/test_config_passthrough.py` and `tests/gui/test_adetailer_panel.py` pass.
- Existing tests remain green, especially:
  - `tests/test_complete_workflow.py`
  - `tests/test_api.py`
  - `tests/test_controller.py`
  - `tests/test_gui_system.py`

## 11. Rollback Plan
- Revert changes to:
  - `src/utils/config.py`
  - `src/gui/adetailer_config_panel.py`
  - `tests/test_config_passthrough.py`
  - `tests/gui/test_adetailer_panel.py`
- Run the full test suite to confirm behavior is back to the previous baseline.
- Since no schema changes or persistent data formats are modified, rollback is just a code revert.

## 12. Codex Execution Constraints
- Apply changes **only** to the allowed files listed above.
- Do **not** introduce new modules or files.
- Do **not** refactor or “clean up” unrelated code.
- If you discover that a change is required outside the allowed files, STOP and request an updated PR design rather than guessing.
- After code changes, always run:
  - `pytest tests/test_config_passthrough.py -k scheduler -v`
  - `pytest tests/gui/test_adetailer_panel.py -v`
  - `pytest tests/test_complete_workflow.py -k adetailer -v` (if such tests exist; otherwise run the closest workflow tests).

## 13. Smoke Test Checklist
After tests pass, perform these manual checks:

1. Start StableNew via `python -m src.main`.
2. In the main sampler/scheduler UI:
   - Select `DPM++ 2M` and `Karras`.
3. In the ADetailer panel:
   - Confirm the new “ADetailer scheduler” dropdown exists.
   - Leave it at “Inherit main scheduler”.
4. Run a txt2img pipeline with ADetailer enabled.
   - Verify, via the WebUI logs / PNG info, that ADetailer uses `DPM++ 2M Karras` (or equivalent).
5. Change the ADetailer scheduler explicitly (e.g., to `Automatic` or another scheduler) and re-run:
   - Confirm that ADetailer uses the new scheduler setting.
6. Ensure there are no regressions:
   - No crashes in the GUI.
   - No unexpected warnings/errors in the logs.
   - Other stages (upscale, etc.) continue to behave as before.
