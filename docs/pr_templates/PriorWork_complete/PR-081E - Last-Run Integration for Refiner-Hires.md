PR-081E - Last-Run Integration for Refiner/Hires
Intent
Ensure that refiner and hires fix settings are fully integrated into:


Presets (so your “good” SDXL recipes carry refiner/hires choices), and


Last-run restore (so the Pipeline tab comes back exactly as you left it),


…without breaking any existing presets or last-run files.

Files


src/utils/config.py


Preset schema, config models, last-run store wiring.




src/utils/file_io.py


If any preset/last-run file format helpers need updating.




src/gui/app_state_v2.py


Load/restore logic: push refiner/hires fields into AppStateV2 / PipelineState.




tests/unit/test_config_presets.py (or equivalent)


Preset + last-run regression tests.





Detailed Changes
1) Extend preset schema with refiner + hires fields
File: src/utils/config.py
Goal: make presets first-class carriers of SDXL refiner/hires settings.
Assuming you already have something like:


Txt2ImgConfig


HiresFixConfig


RunPreset / PresetConfig


LastRunConfig or LastRunStoreV2_5


From 081A, we now expect:
@dataclass
class Txt2ImgConfig:
    # existing fields...
    refiner_enabled: bool = False
    refiner_model_name: str | None = None
    refiner_switch_at: float = 0.8  # 0–1

@dataclass
class HiresFixConfig:
    enabled: bool = False
    upscale_factor: float = 2.0
    upscaler_name: str = "Latent"
    hires_steps: int | None = None
    hires_denoise: float = 0.3
    use_base_model_for_hires: bool = True

Changes:


Preset DTOs / dict format
Wherever you serialize presets to/from dicts (e.g., PresetConfig.to_dict(), from_dict()):


Include the refiner fields:


refiner_enabled


refiner_model_name


refiner_switch_at




Include the hires fields under a nested object if you already group them (recommended):
"hires_fix": {
    "enabled": ...,
    "upscale_factor": ...,
    "upscaler_name": ...,
    "hires_steps": ...,
    "hires_denoise": ...,
    "use_base_model_for_hires": ...
}



If you don’t currently have a nested hires_fix block, introduce one now and keep it optional.




Backward-compatible from_dict


When loading presets that don’t have these fields:


Use the dataclass defaults above.


Do not raise errors or warnings; treat missing keys as “feature off”.




Implementation sketch:
refiner_enabled = data.get("refiner_enabled", False)
refiner_model_name = data.get("refiner_model_name")
refiner_switch_at = data.get("refiner_switch_at", 0.8)

hires_data = data.get("hires_fix", {}) or {}
hires_cfg = HiresFixConfig(
    enabled=hires_data.get("enabled", False),
    upscale_factor=hires_data.get("upscale_factor", 2.0),
    upscaler_name=hires_data.get("upscaler_name", "Latent"),
    hires_steps=hires_data.get("hires_steps"),
    hires_denoise=hires_data.get("hires_denoise", 0.3),
    use_base_model_for_hires=hires_data.get("use_base_model_for_hires", True),
)





Preset export


Ensure new presets saved from V2 write these fields out, even if they’re at default values, so future changes remain explicit and debuggable.





2) Extend last-run config/store for refiner + hires
File: src/utils/config.py (and possibly src/utils/file_io.py)
Goal: last-run storage (e.g., last_run_store_v2_5.json) should capture and restore all refiner/hires knobs.


Last-run schema
If you have something like:
@dataclass
class LastRunConfig:
    txt2img: Txt2ImgConfig
    hires_fix: HiresFixConfig
    # ...

ensure:


Txt2ImgConfig is the same refiner-extended object as above.


HiresFixConfig is included and serialized.




Serialize to disk


Wherever the last-run file is written (e.g., LastRunStoreV2_5.save()):


Include the refiner and hires blocks in the JSON output.


Keep the format as close as possible to the preset schema (for sanity).






Load from disk


Use the same defensive pattern as presets:


If last-run files from older versions don’t contain the new fields, use defaults.


If hires_fix is missing, create HiresFixConfig() with defaults.






File I/O helpers


If src/utils/file_io.py has thin helpers like read_json_config, write_json_config, you may not need changes beyond ensuring:


They can handle the updated nested structures.


They don’t assume a fixed set of keys.







3) AppStateV2 / PipelineState restore logic
File: src/gui/app_state_v2.py
Goal: restoring last-run should actually set:


The in-memory refiner/hires fields.


The Pipeline tab widgets.


This is the “no re-toggling every time” part.


Apply last-run config into state
Find the code path that handles:


App startup / app reload.


“Restore last run” behavior.


For example, something like:
def restore_last_run(self, last_run: LastRunConfig):
    # existing bindings...

Extend it to:


Assign refiner fields:
self.current_config.refiner_enabled = last_run.txt2img.refiner_enabled
self.current_config.refiner_model_name = last_run.txt2img.refiner_model_name
self.current_config.refiner_switch_at = last_run.txt2img.refiner_switch_at



Assign hires fix fields:
self.current_config.hires_enabled = last_run.hires_fix.enabled
self.current_config.hires_upscale_factor = last_run.hires_fix.upscale_factor
self.current_config.hires_upscaler_name = last_run.hires_fix.upscaler_name
self.current_config.hires_steps = last_run.hires_fix.hires_steps
self.current_config.hires_denoise = last_run.hires_fix.hires_denoise



(Adapt field names to whatever 081A/079F actually used; the core idea is explicit 1:1 mapping.)


Pipeline tab widget sync
If AppStateV2 uses binding helpers like bind_refiner_state_to_widgets(...) / bind_hires_fix_to_widgets(...) or PipelineState objects:


Ensure restoring config updates both:


The underlying state.


Any Tk variable / control associated with refiner/hires fields (checkboxes, sliders, dropdowns from 081B).




You may need a helper method on the pipeline tab or stage cards, e.g.:
def apply_config_to_widgets(self, config: Txt2ImgConfig, hires: HiresFixConfig):
    # set checkbox states, slider values, dropdown selections



Call this from the restore path after AppStateV2 has been updated.




Saving last-run from GUI
Wherever last-run is updated (e.g., after a run or on config change):


Ensure you copy current refiner/hires values out of:


self.current_config


or PipelineState / RunConfig




into the LastRunConfig object that’s going to disk.





Tests
File: tests/unit/test_config_presets.py (and possibly new ones for last-run)
Add/extend tests to cover:


Preset round-trip with refiner + hires


Create a PresetConfig with:


refiner_enabled=True


refiner_model_name="sdxl_refiner_foo"


refiner_switch_at=0.75


hires_fix.enabled=True


hires_fix.upscale_factor=1.5


hires_fix.upscaler_name="Latent"


hires_fix.hires_steps=20


hires_fix.hires_denoise=0.4




Serialize to dict, then back via from_dict.


Assert that all fields survive intact.




Loading an old preset (missing fields)


Use a dict representing an “old world” preset with no refiner/hires keys.


Call from_dict.


Assert:


refiner_enabled is False


refiner_model_name is None


refiner_switch_at == 0.8 (default)


hires_fix.enabled is False


Other hires defaults match 081A’s defaults.






Last-run round-trip


Build a LastRunConfig containing non-default refiner + hires values.


Serialize to JSON (using the actual write function).


Parse back using the actual read/load function.


Assert that all refiner/hires fields survive with identical values.




AppStateV2 restore wiring


Use a lightweight test that:


Creates a fake LastRunConfig with refiner/hires enabled and non-default values.


Calls AppStateV2.restore_last_run(...) or equivalent.


Asserts:


app_state.current_config.refiner_enabled etc. match the last-run config.


If practical in unit context, also that corresponding Tk variables or pipeline state fields were updated (e.g., by querying the bound state objects, not the live GUI).









Out of Scope


Any major preset system redesign or version migration logic.


UI/UX changes beyond syncing widget values with restored config.


Changes to how refiner/hires run in the pipeline (that’s handled by 081C); this PR is strictly about state persistence (presets + last-run).

