PR-105 Content Part 1 — src-learning-model.md

Below is a module-level docstring you can place at the top of src/learning/model_profiles.py (above imports), plus an optional inline schema comment block.

"""
Model Profiles & Style-Aware Defaults (V2-P1)

This module defines the data structures and helpers used to represent
**ModelProfiles** – structured sidecar "priors" that StableNewV2 uses to
bootstrap good pipeline defaults for a given base model.

ModelProfiles are consumed by:
- The controller / app state when constructing a fresh PipelineConfig.
- The Learning System as a baseline config to vary in controlled experiments.
- Future analytics and recommendation layers.
(See Learning_System_Spec_v2 for the full design.)  # external spec reference

----------------------------------------------------------------------
Core Concepts
----------------------------------------------------------------------

1. ModelProfile
   A ModelProfile describes recommended settings for a single base model
   (e.g., SDXL base, RealisticVision, WD1.5, AnythingV5).  At minimum it
   captures:

   - model_id: str
       Logical identifier for the base model (not the raw filename).

   - model_family: Literal["sdxl", "sd15", ...]
       Coarse family classification that informs which refiners, VAEs,
       and other options are relevant.

   - preset tiers / core defaults (non-exhaustive, examples only):
       • recommended_sampler
       • recommended_scheduler
       • recommended_steps
       • recommended_cfg
       • recommended_resolution

   In addition to these general defaults, V2-P1 introduces explicit
   support for refiner and hires-fix defaults:

   - default_refiner_id: Optional[str]
       Logical ID of the recommended refiner for this model, if any.
       Must be one of the canonical IDs defined in the
       model_defaults_v2 spec (e.g., "sdxl_refiner_official",
       "realvisxl_refiner", "wd15_refiner", etc.).

   - default_hires_upscaler_id: Optional[str]
       Logical ID of the recommended hires-fix upscaler (e.g.,
       "swinir_4x", "4x_ultrasharp", "4x_animesharp").

   - default_hires_denoise: Optional[float]
       Recommended denoise strength for the hires-fix pass, typically
       in the range:
         • 0.20–0.40 for realism
         • 0.20–0.35 for portrait realism
         • 0.30–0.50 for stylized / semi-real
         • 0.35–0.60 for anime

   - style_profile_id: Optional[str]
       Optional link to a StyleProfile (see docs/model_defaults_v2) that
       captures a named style such as:
         • "sdxl_realism"
         • "sdxl_portrait_realism"
         • "sdxl_stylized"
         • "sd15_realism"
         • "anime"

   These fields are **priors**, not hard constraints. They are used only
   when there is no last-run config or explicit preset override.

2. Precedence Rules

   When constructing a new PipelineConfig for a given base model:

   1. If a last-run config exists, its values win.
   2. Else, if a user preset is loaded, preset values win.
   3. Else, if a ModelProfile (optionally with style_profile_id) defines
      default_refiner_id / default_hires_upscaler_id / default_hires_denoise,
      those are used to initialize the PipelineConfig.
   4. Else, engine-level fallbacks apply (e.g., no refiner).

   ModelProfiles therefore provide a **sane starting point** but are never
   allowed to override explicit user choices or last-run state.

3. Learning & Randomizer Integration

   - Learning:
       Treats the defaults from ModelProfiles as the baseline configuration
       when designing Learning Runs (e.g., sweeping hires denoise around
       default_hires_denoise). LearningRecords capture the actual values
       used per run.

   - Randomizer:
       Does NOT randomize the refiner or hires upscaler by default.
       Those belong to the "base config" defined by ModelProfiles +
       Learning, while Randomizer explores "creative overlays" such as
       LoRAs, prompts, styles, etc.

----------------------------------------------------------------------
Implementation Guidance
----------------------------------------------------------------------

- The canonical set of refiner IDs and hires upscaler IDs is defined in:
    docs/model_defaults_v2/V2-P1.md

- ModelProfiles in this module MUST use those logical IDs when specifying
  default_refiner_id and default_hires_upscaler_id.

- It is valid for some ModelProfiles to leave these fields as None; in
  that case, StableNew falls back to its existing behavior for that model.

- This module should remain free of GUI imports and must be safe to use
  from pure backend contexts (controller, pipeline, learning, tests).
"""


(Optional inline schema comment near the ModelProfile dataclass or pydantic model):

# ModelProfile refiner/hires defaults (V2-P1):
#   default_refiner_id: Optional[str]
#       Canonical refiner ID (see docs/model_defaults_v2/V2-P1.md §2.1).
#   default_hires_upscaler_id: Optional[str]
#       Canonical hires upscaler ID (see docs/model_defaults_v2/V2-P1.md §2.2).
#   default_hires_denoise: Optional[float]
#       Recommended hires denoise strength (see §3.3 for ranges).
#   style_profile_id: Optional[str]
#       Logical style profile key linking this model to a named style
#       (e.g., "sdxl_realism", "anime").
