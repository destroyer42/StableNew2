CODEX-PROMPT-PR-GUI-V2-DROPDOWN-PAYLOAD-LASTRUN-V2_5-001(P1V3)(11-28-25)

You are implementing PR-GUI-V2-DROPDOWN-PAYLOAD-LASTRUN-V2_5-001(P1V3)(11-28-25) in the StableNew repo.

GOAL
Make the V2 pipeline “real”:
- Pipeline tab dropdowns (model, VAE, sampler, scheduler, upscaler) are populated from the WebUIResourceService via AppController.
- When the user selects a value, it flows GUI -> controller -> pipeline config -> executor -> WebUI payload.
- After a successful txt2img run, current settings are saved as Last-Run Config.
- On startup, last-run config is loaded and used to preselect dropdowns and pre-fill core numeric fields.

IMPORTANT
- Assume the V2 GUI scaffold / zones are already fixed by a prior PR (MainWindowV2 zones, Tk kwargs, etc.).
- Work ONLY on V2 code paths. Do NOT reintroduce or depend on V1 GUI code.

PRECONDITIONS (handled by me)
- I will run the snapshot script before changes.

SCOPE (what you MAY touch)
- src/controller/app_controller.py
- src/gui/advanced_txt2img_stage_card_v2.py
- src/gui/base_stage_card_v2.py (if needed for helper callbacks/props)
- src/api/webui_resources.py (small tweaks only, if needed)
- src/api/last_run_store_v2_5.py (small helper accessors if needed)
- src/pipeline/executor.py (MINIMAL changes only to align key names)

OUT OF SCOPE (do NOT change unless absolutely required)
- Legacy V1 GUI files.
- Fundamental executor behavior or pipeline sequencing.
- Learning, randomization, advanced prompt editor, layout/scroll fixes.

TASKS

1) Harden AppController resource and last-run methods.

In src/controller/app_controller.py:

- Ensure the controller has fully initialized members:
  - self._resource_service: WebUIResourceService
  - self._last_run_store: LastRunStoreV2_5

- Implement or confirm these methods:

  ```python
  def list_models(self) -> list[WebUIResource]: ...
  def list_vaes(self) -> list[WebUIResource]: ...
  def list_upscalers(self) -> list[WebUIResource]: ...
  def list_hypernetworks(self) -> list[WebUIResource]: ...
  def list_embeddings(self) -> list[WebUIResource]: ...
  def get_last_run_config(self) -> LastRunConfigV2_5 | None: ...
If tests or GUI code still reference legacy names like get_available_models or get_available_samplers:

Implement them as thin wrappers around the canonical methods above.

Example:

python
Copy code
def get_available_models(self) -> list[WebUIResource]:
    return self.list_models()
Wire AdvancedTxt2ImgStageCardV2 dropdowns to controller.

In src/gui/advanced_txt2img_stage_card_v2.py:

On initialization of the card:

Fetch resource lists from controller:

python
Copy code
models = self.controller.list_models()
vaes = self.controller.list_vaes()
upscalers = self.controller.list_upscalers()
# samplers/schedulers from controller or canonical lists
Build dropdown/combobox options using display strings derived from WebUIResource:

Prefer resource.display_name if present.

Fall back to resource.name (or another field that matches WebUI’s checkpoint name).

Maintain a mapping from UI selection -> underlying name that must go into the config.

On selection change callbacks:

Call controller methods like:

python
Copy code
self.controller.set_txt2img_model(model_name)
self.controller.set_txt2img_vae(vae_name)
self.controller.set_txt2img_sampler(sampler_name)
self.controller.set_txt2img_scheduler(scheduler_name)
self.controller.set_txt2img_upscaler(upscaler_name)
Do not let the GUI directly mutate the executor’s payload. Always go through the controller.

Use existing config access patterns in this file to stay consistent. Don’t invent a second config mechanism.

Implement controller setters for txt2img config.

In src/controller/app_controller.py:

Implement setter methods that the GUI can call:

python
Copy code
def set_txt2img_model(self, model_name: str) -> None: ...
def set_txt2img_vae(self, vae_name: str) -> None: ...
def set_txt2img_sampler(self, sampler_name: str) -> None: ...
def set_txt2img_scheduler(self, scheduler_name: str) -> None: ...
def set_txt2img_upscaler(self, upscaler_name: str) -> None: ...
Also, if helpful, provide:

python
Copy code
def update_txt2img_core_params(
    self,
    *,
    steps: int | None = None,
    cfg_scale: float | None = None,
    width: int | None = None,
    height: int | None = None,
    clip_skip: int | None = None,
    seed: int | None = None,
) -> None:
    ...
Under the hood, these should update the same config structure the pipeline executor uses today (e.g., state.current_config["txt2img"] or equivalent).

Do NOT introduce a second, parallel config structure.

Align config keys with executor’s payload builder.

Inspect txt2img / img2img / upscaling payload builders in src/pipeline/executor.py:

Confirm they are pulling from a consistent config dict or object.

Ensure config keys used by the controller and GUI match what executor expects:

Examples (adjust to actual code):

model -> used for /sdapi/v1/options

vae -> used for /sdapi/v1/options

sampler_name -> used in txt2img payload

scheduler -> used in txt2img payload

upscaler (or hr_upscaler) -> used in hires or upscaling calls

steps, cfg_scale, width, height, clip_skip, seed

If you find mismatches (e.g., GUI sets "sampler" but executor reads "sampler_name"):

Normalize at the config/controller level so that there is exactly one canonical key per concept.

Keep changes to executor.py minimal:

Prefer adjusting where config is written instead of rewriting the executor.

Last-Run Config: save on successful txt2img run.

Find where txt2img pipeline runs successfully (likely in controller or pipeline runner):

After a successful run (images returned, no exception), build a LastRunConfigV2_5 instance using the current effective config:

Include fields defined in LastRunConfigV2_5:

model

vae

sampler_name / scheduler

upscaler

steps, cfg_scale, width, height, clip_skip, seed

prompt, negative_prompt

any additional relevant fields defined in the dataclass.

Call:

python
Copy code
self._last_run_store.save(last_run_config)
Do not save if the run failed (HTTP 500, no images, etc.).

Last-Run Config: preload on startup.

In the place where AppController is fully initialized AND the GUI widgets are available (after MainWindowV2 zones are ready):

Call:

python
Copy code
last_run = self.get_last_run_config()
If last_run is not None:

Use it to update the internal config.

Then update GUI elements:

For each dropdown:

If last_run.model (or vae/upscaler/etc.) exists in the resource list, select it.

If not found, pick a safe default and log a warning.

For numeric controls (steps, cfg, width, height, clip_skip, seed):

Set widget values to match last_run where possible.

Make sure preloading happens once, after discovery has run and dropdowns are populated, so setting initial selections does not conflict with later initialization.

Keep everything V2-only and avoid regression.

DO NOT:

Reintroduce V1 AppState or legacy controller logic.

Copy-paste old V1 code into V2 files.

Keep changes contained to the files listed in SCOPE.

Prefer small, focused modifications over large refactors.

VERIFICATION

After implementing all changes:

Run:

python -m src.main

Expect:

App launches with V2 GUI.

Pipeline tab dropdowns (model, vae, sampler, scheduler, upscaler) are non-empty and look sane.

From the GUI:

Select a specific model/vae/sampler/etc. and run a txt2img job.

Confirm in the WebUI console logs and/or in the API logs that:

The chosen model name is used.

The sampler/scheduler matches the GUI selection.

The job succeeds and produces an image.

Restart the app:

Confirm that:

The last selected model/vae/sampler/scheduler/upscaler are selected by default.

Steps, cfg, width, height, clip_skip, seed are restored.

Run:

pytest -q

Fix or update any tests that:

Assert resource lists.

Assert last-run config behavior.

Assert controller resource accessors.

Provide me a summary:

Files modified.

Brief explanation of how dropdowns are populated and wired to config.

Confirmation that txt2img runs with the selected model and that last-run config persists across restarts