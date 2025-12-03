PR-081A – SDXL Refiner & Hires Fix Config Model
Intent

Extend the core V2 pipeline configuration model so we can express but not yet execute:

Refiner usage for SDXL txt2img:

refiner_enabled

refiner_model_name

refiner_switch_at (fraction of steps)

Hires fix usage:

enabled

upscaler name

upscale factor

hires steps

hires denoise

whether hires pass uses base model vs refiner

No GUI widgets and no behavioral change to pipeline execution yet — this PR is purely about adding the configuration surface with safe defaults and backward-compatible load/save.

Files

Core / Pipeline

src/pipeline/run_plan.py
(or wherever RunConfig / Txt2ImgConfig / stage config dataclasses live)

src/pipeline/stage_sequencer.py

State & Config

src/gui/app_state_v2.py

src/utils/config.py (presets, last-run, and schema defaults)

API DTOs

src/api/client.py (config DTOs passed down towards WebUI)

Tests

Existing pipeline config tests (if present)

Existing config load/save tests

New unit tests for refiner/hires config defaults and schema upgrades

Detailed Changes
1) Extend core Txt2Img + Hires Fix config

File: src/pipeline/run_plan.py

Locate the canonical pipeline config dataclasses (examples below; adjust to match actual names):

@dataclass
class Txt2ImgConfig:
    # existing fields (examples only)
    prompt: str
    negative_prompt: str
    steps: int
    cfg_scale: float
    width: int
    height: int
    sampler_name: str
    scheduler_name: str
    model_name: str
    # ...


Extend this dataclass with refiner fields:

from dataclasses import dataclass
from typing import Optional

@dataclass
class Txt2ImgConfig:
    # existing fields...
    refiner_enabled: bool = False
    refiner_model_name: Optional[str] = None
    refiner_switch_at: float = 0.8  # 0–1 ratio through steps


Add a dedicated hires fix config type; either nested in RunConfig or owned separately:

@dataclass
class HiresFixConfig:
    enabled: bool = False
    upscale_factor: float = 2.0
    upscaler_name: str = "Latent"
    hires_steps: Optional[int] = None
    hires_denoise: float = 0.3
    use_base_model_for_hires: bool = True


If there is a RunConfig / PipelineRunConfig that aggregates stage configs, add the hires fix config there:

@dataclass
class RunConfig:
    txt2img: Txt2ImgConfig
    # existing stage configs...
    hires_fix: HiresFixConfig = field(default_factory=HiresFixConfig)


Key points:

Defaults are non-disruptive: refiner off, hires fix off.

No behavior changes yet — the runner and sequencer will still ignore these fields.

2) Stage sequencer awareness (no behavior yet)

File: src/pipeline/stage_sequencer.py

Goal: make the sequencer aware that these knobs exist without changing actual behavior.

Ensure the sequencer’s planning logic can see:

run_config.txt2img.refiner_enabled

run_config.txt2img.refiner_model_name

run_config.txt2img.refiner_switch_at

run_config.hires_fix.*

For this PR, you can simply:

Pass these values through to any internal “stage plan” objects, or

Attach them as metadata to the existing plan data structures.

Example (conceptual):

@dataclass
class StagePlan:
    name: str  # "txt2img", "img2img", "upscale", etc.
    payload: dict
    # new optional metadata fields
    refiner_enabled: bool = False
    refiner_model_name: Optional[str] = None
    refiner_switch_at: float = 0.8
    hires_fix: Optional[HiresFixConfig] = None


But: do not alter the actual sequence (no extra stages, no change to stage order) in this PR. Just ensure the sequencer can carry the new data forward so the next PR can implement behavior.

3) Hook into AppStateV2

File: src/gui/app_state_v2.py

Goal: AppStateV2 should own and persist these knobs so the GUI and pipeline share one source of truth.

Assuming we already have a CurrentConfig or similar (from 079B/079F), add fields or a nested structure for refiner + hires:

Option A – Extend CurrentConfig directly:

@dataclass
class CurrentConfig:
    # existing fields...
    model_name: str = ""
    sampler_name: str = ""
    scheduler_name: str = ""
    steps: int = 20
    cfg_scale: float = 7.0
    batch_size: int = 1
    seed: Optional[int] = None

    # Refiner
    refiner_enabled: bool = False
    refiner_model_name: Optional[str] = None
    refiner_switch_at: float = 0.8

    # Hires fix
    hires_enabled: bool = False
    hires_upscale_factor: float = 2.0
    hires_upscaler_name: str = "Latent"
    hires_steps: Optional[int] = None
    hires_denoise: float = 0.3
    hires_use_base_model_for_hires: bool = True


Option B – If you prefer to keep CurrentConfig smaller, embed a HiresFixConfig field instead; either way, the mapping to RunConfig must be explicit.

Ensure AppStateV2.__init__ continues to initialize self.current_config with sane defaults so all the new fields are always present.

4) Config load/save & presets (backwards-compatible)

File: src/utils/config.py

Wherever you:

Deserialize presets / last-run configs

Build RunConfig or CurrentConfig from dicts

Serialize configs back to disk

Update the schema handling to:

Accept missing new fields gracefully by applying defaults.

Include the new fields on write.

Example for a dict-to-config helper:

def build_txt2img_config(data: dict) -> Txt2ImgConfig:
    return Txt2ImgConfig(
        # existing fields...
        refiner_enabled=data.get("refiner_enabled", False),
        refiner_model_name=data.get("refiner_model_name"),
        refiner_switch_at=float(data.get("refiner_switch_at", 0.8)),
    )


Example for last-run:

def last_run_from_current(current: CurrentConfig) -> dict:
    return {
        # existing fields...
        "refiner_enabled": current.refiner_enabled,
        "refiner_model_name": current.refiner_model_name,
        "refiner_switch_at": current.refiner_switch_at,
        "hires_enabled": current.hires_enabled,
        "hires_upscale_factor": current.hires_upscale_factor,
        "hires_upscaler_name": current.hires_upscaler_name,
        "hires_steps": current.hires_steps,
        "hires_denoise": current.hires_denoise,
        "hires_use_base_model_for_hires": current.hires_use_base_model_for_hires,
    }


Key requirement: loading an older config that doesn’t know about these fields must not crash; everything should default to “off”.

5) API client config DTOs (no behavior yet)

File: src/api/client.py

Where you build the payload DTOs for WebUI (txt2img / img2img / hires calls), extend the DTO structure to accept these fields but do not change how they’re used.

Example:

@dataclass
class Txt2ImgRequest:
    # existing fields...
    steps: int
    sampler_name: str
    scheduler_name: str
    model_name: str
    # New:
    refiner_enabled: bool = False
    refiner_model_name: Optional[str] = None
    refiner_switch_at: float = 0.8

    hires_enabled: bool = False
    hires_upscale_factor: float = 2.0
    hires_upscaler_name: str = "Latent"
    hires_steps: Optional[int] = None
    hires_denoise: float = 0.3
    hires_use_base_model_for_hires: bool = True


For this PR:

You can pass these through to payload dicts under keys like refiner_switch_at, hires_fix_upsampler, etc., but you don’t have to hook them into real WebUI behavior yet.

At minimum, tests should confirm the DTO can carry these fields so the next behavioral PR can start using them.

6) Tests

Add/extend tests to verify:

Txt2ImgConfig and HiresFixConfig default values are as specified.

Old config JSON without refiner/hires keys is still loadable and produces matching defaults.

Last-run serialization includes these fields and they round-trip correctly.

AppStateV2.current_config always has the new attributes initialized.

No journey/UI tests should change in this PR.

Out of Scope (explicit)

No new GUI controls.

No actual change in pipeline behavior/sequencing.

No changes to ADetailer execution; this PR just sets up configuration.