# PR-GUI-V2-DROPDOWN-PAYLOAD-LASTRUN-V2_5-001  
V2 Dropdown Wiring, Payload Correctness, and Last-Run Restore

## Intent

Make the **V2 pipeline actually “real”**:

- Pipeline tab dropdowns (model, VAE, sampler, scheduler, upscaler) are populated from the **WebUIResourceService** / controller, not hardcoded.
- When you select a model/vae/sampler/scheduler/upscaler in the GUI, that value flows:
  **GUI → controller → pipeline config → executor → WebUI JSON payload**.
- After a successful txt2img pipeline run, the current config is saved as a **Last-Run Config**.
- On startup, the **last-run config** is loaded and used to:
  - Preselect dropdowns (model, vae, sampler, scheduler, upscaler).
  - Pre-fill core numeric controls (steps, cfg, resolution, clip_skip, etc.) where fields exist.

This PR should **not** introduce new visual design or new features; it’s strictly wiring + correctness.

---

## Scope

### In Scope

1. **Controller → Resource Service Pass-Throughs (Production-Ready)**

   In `src/controller/app_controller.py`:

   - Finalize and harden the resource-list methods so they are safe to call from the GUI:

     ```python
     def list_models(self) -> list[WebUIResource]: ...
     def list_vaes(self) -> list[WebUIResource]: ...
     def list_upscalers(self) -> list[WebUIResource]: ...
     def list_hypernetworks(self) -> list[WebUIResource]: ...
     def list_embeddings(self) -> list[WebUIResource]: ...
     def get_last_run_config(self) -> LastRunConfigV2_5 | None: ...
     ```

   - Ensure `_resource_service` and `_last_run_store` are initialized in `__init__` (or via a small factory method) and **never** left as `None` during normal app startup.

   - If earlier test expectations look for methods like:

     ```python
     get_available_models()
     get_available_samplers()
     ```

     then:

     - Implement these as thin wrappers delegating to the canonical list methods.
     - Keep them for backward/test compatibility but **do not** build new code on top of them.

2. **AdvancedTxt2ImgStageCardV2 Dropdown Population**

   In `src/gui/advanced_txt2img_stage_card_v2.py`:

   - Model dropdown:

     - Populate using `controller.list_models()`.
     - Use a **display string** for the UI (e.g., `resource.display_name` if present, otherwise `resource.name`).
     - Internally, when the user selects an item, update the txt2img config’s `model` field with the correct name that WebUI expects (e.g., the checkpoint name).

   - VAE dropdown:

     - Populate using `controller.list_vaes()` in the same pattern.

   - Sampler & scheduler dropdowns:

     - If discovery-based lists exist:
       - Populate from controller methods or a canonical list of supported sampler/scheduler names.
     - If not, keep a well-defined, static list in one place (not duplicated in multiple files), and ensure the chosen value flows into the config keys used by the executor.

   - Upscaler dropdown:

     - If WebUIResourceService / API exposes upscalers, use `controller.list_upscalers()`.
     - Otherwise, use the existing supported upscaler names required by WebUI and ensure they map correctly into the payload.

   **Key contract:**
   - Every dropdown selection must update the **underlying config object/dict** the executor uses.

3. **Config Flow: GUI → Controller → Pipeline Config**

   In `app_controller.py` + the relevant config abstractions:

   - Implement (or fix) controller methods that the GUI can call to update config in a single, consistent place, e.g.:

     ```python
     def set_txt2img_model(self, model_name: str) -> None: ...
     def set_txt2img_vae(self, vae_name: str) -> None: ...
     def set_txt2img_sampler(self, sampler_name: str) -> None: ...
     def set_txt2img_scheduler(self, scheduler_name: str) -> None: ...
     def set_txt2img_upscaler(self, upscaler_name: str) -> None: ...
     # and, if needed:
     def update_txt2img_core_params(self, *, steps: int, cfg_scale: float, width: int, height: int, clip_skip: int, seed: int | None) -> None: ...
     ```

   - Under the hood, these methods should update the same config structure that the pipeline/executor already uses (e.g., `self.state.current_config` or equivalent).

   - The GUI **must not** directly mutate executor payloads; it should always go through the controller.

4. **Payload Correctness: Executor Uses Selected Values**

   In `src/pipeline/executor.py` (or the relevant payload-building module):

   - Confirm the txt2img payload builder reads:

     - Model name from config (e.g., `config["model"]`).
     - VAE from config (`config["vae"]`).
     - Sampler from `config["sampler_name"]` or equivalent.
     - Scheduler from `config["scheduler"]`.
     - Upscaler from the appropriate config key for hires / upscaling.
     - Steps, CFG, width, height, clip_skip, seed, etc. from the same config updated by the controller.

   - If any names/keys drift (e.g., GUI uses `sampler` but executor expects `sampler_name`), normalize them:

     - Prefer to fix the **config layer** once so that executor only needs to look at one canonical name per setting.

   - Ensure the values put into `/sdapi/v1/options` and `/sdapi/v1/txt2img` exactly match WebUI expectations (based on the README / current API behavior).

5. **Last-Run Config: Save on Success**

   In `app_controller.py` and/or pipeline runner hooks:

   - After a **successful txt2img run** (and ideally after the full pipeline completes without error):

     - Construct a `LastRunConfigV2_5` instance from the current effective config (model, vae, sampler, scheduler, upscaler, steps, cfg, width, height, clip_skip, seed, prompt, negative, etc. as defined in that dataclass).

     - Call `_last_run_store.save(last_run_config)` (or equivalent) to persist to disk.

   - Ensure this is only done on **success**, not on failures or partial runs.

6. **Last-Run Config: Restore on Startup**

   On V2 app startup:

   - During controller setup (after pipeline state/config objects exist):

     - Call `self._last_run_store.load()` (via `get_last_run_config()` if that’s the API).
     - If a config is returned:
       - Apply its values to the current pipeline config structure.
       - Update the GUI:

         - Dropdown initial selections match the last-used model, vae, sampler, scheduler, upscaler.
         - Sliders / spinboxes (steps, cfg, width, height, clip_skip, seed) are pre-filled with last-used values.

   - If the stored config references a model/vae/etc. that no longer exists:

     - Fail gracefully:
       - Keep the rest of the config (steps, cfg, etc.).
       - For missing resources, default to the first available or a safe default (e.g., the first item in the resource list).
       - Log a warning that the previously used model/vae/etc. was not found.

---

### Out of Scope

- Layout and scrolling fixes for the left panel (that’s a separate “cleanup/layout” PR).
- Duplicate core config removal from the left panel.
- Randomization engine / advanced prompt editor.
- Learning features / rating system.
- Any legacy V1 GUI work or reactivation.

---

## Guardrails

1. **Snapshot Required**

   - Before working this PR, run the snapshot script and record:

     ```text
     Snapshot used: ______________________
     ```

2. **Do Not Touch These Files (Unless Absolutely Necessary)**

   - `src/pipeline/executor.py`:
     - Only adjust minimal field-name mapping if there is a clear mismatch.
     - Do not redesign the pipeline or introduce new behaviors here.

   - `src/main.py`, `src/app_factory.py`:
     - Only touch if necessary to hook last-run preload in a clean, minimal way.

3. **V2-Only Rule**

   - No new imports from legacy V1 files.
   - No copying V1 logic into V2 modules.
   - If you need a reference, treat V1 files as read-only docs.

4. **Single Source of Truth for Resource Lists**

   - Model/vae/upscaler lists:
     - Must come from `WebUIResourceService` via controller methods.
   - Sampler/scheduler lists:
     - Either from a single canonical list or a future discovery method.
     - No duplicated hard-coded lists across multiple GUI files.

---

## Files Likely to Be Touched

- `src/controller/app_controller.py`
- `src/gui/advanced_txt2img_stage_card_v2.py`
- `src/gui/base_stage_card_v2.py` (if needed for additional callbacks/props)
- `src/pipeline/executor.py` (minimal, only if key name alignment is required)
- `src/api/webui_resources.py` (if minor tweaks are needed for consistent resource metadata)
- `src/api/last_run_store_v2_5.py` (if small accessors/helpers are needed)

---

## Suggested Implementation Steps

1. **Stabilize Controller Resource Methods**

   - Ensure `_resource_service` and `_last_run_store` are created in `AppController.__init__` (or via a helper).
   - Implement/verify:

     ```python
     def list_models(self) -> list[WebUIResource]: ...
     def list_vaes(self) -> list[WebUIResource]: ...
     def list_upscalers(self) -> list[WebUIResource]: ...
     def list_hypernetworks(self) -> list[WebUIResource]: ...
     def list_embeddings(self) -> list[WebUIResource]: ...
     def get_last_run_config(self) -> LastRunConfigV2_5 | None: ...
     ```

   - If tests reference `get_available_models` / `get_available_samplers`, add thin wrappers that call the new list methods.

2. **Wire AdvancedTxt2ImgStageCardV2 Dropdowns**

   - On card init:

     - Fetch lists from controller:

       ```python
       models = controller.list_models()
       vaes = controller.list_vaes()
       upscalers = controller.list_upscalers()
       # samplers/schedulers from controller or from a canonical list
       ```

     - Build dropdowns with human-friendly labels, but keep track of the underlying name that must flow into the config.

   - On selection change:

     - Call controller methods (e.g. `set_txt2img_model(selected_model_name)`).
     - Ensure config immediately reflects the new choice.

3. **Align Config Keys with Executor Expectations**

   - Inspect txt2img payload builder in `executor.py`:

     - Ensure:

       ```python
       payload["prompt"] = config["prompt"]
       payload["negative_prompt"] = config["negative_prompt"]
       payload["steps"] = config["steps"]
       payload["cfg_scale"] = config["cfg_scale"]
       payload["width"] = config["width"]
       payload["height"] = config["height"]
       payload["sampler_name"] = config["sampler_name"]
       payload["scheduler"] = config["scheduler"]
       # model, vae, upscaler likely applied via /sdapi/v1/options or options+extras
       ```

   - If GUI/config is using different keys (e.g. `sampler` vs `sampler_name`), normalize them so there is **one** canonical key.

4. **Hook Last-Run Save on Success**

   - In the controller or pipeline runner path that handles a **successful txt2img run**:

     - Gather the active config (model, vae, sampler, scheduler, upscaler, steps, cfg, width, height, clip_skip, seed, prompt, negative, etc.) and construct a `LastRunConfigV2_5`.

     - Call `_last_run_store.save(last_run_config)`.

   - Ensure this runs only when the pipeline completes successfully (e.g., `txt2img` returns images).

5. **Preload Last-Run Config on Startup**

   - After app construction (zones and controller set up):

     - Load last-run config:

       ```python
       last_run = self.get_last_run_config()
       ```

     - If present:

       - Apply it to the current config.
       - Update GUI controls:
         - Set dropdown selected values to match `last_run.model`, `last_run.vae`, etc. if those resources exist.
         - Update steps, cfg, width, height, clip_skip, seed fields.

       - For missing resources (model/vae/etc. not found in discovery lists):
         - Choose a safe fallback (first available).
         - Log a warning.

---

## Verification

### Required

- [ ] Run snapshot script and note snapshot name.

- [ ] `python -m src.main`:
  - App launches without Tk/Tcl errors.
  - Pipeline tab dropdowns for:
    - Model
    - VAE
    - Sampler
    - Scheduler
    - Upscaler  
    are populated with non-empty, realistic values.

- [ ] Manually run a txt2img pipeline from the GUI:
  - Confirm the chosen model/vae/etc. actually appear in WebUI console logs / API requests.
  - Confirm images are generated as expected (assuming the chosen resources exist).

- [ ] Close the app, relaunch:
  - Confirm last used model/vae/sampler/scheduler/upscaler and core integers/floats (steps, cfg, width, height, clip_skip, seed) are restored.

- [ ] `pytest -q`:
  - Tests for:
    - Last-run store
    - WebUI resource service
    - Controller resource methods
    - Any GUI tests exercising dropdowns  
    should pass or at least move to more meaningful assertions.

### Optional

- [ ] Add a small controller test that asserts:
  - `list_models` returns `WebUIResource` objects.
  - `get_last_run_config` returns `LastRunConfigV2_5 | None`.

- [ ] Add a GUI smoke test that verifies:
  - `AdvancedTxt2ImgStageCardV2` builds dropdowns with at least one model when provided a fake controller.

---
