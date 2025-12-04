### Model Defaults & Style Profiles (Refiner + Hires Fix)

StableNewV2 now has a **single, authoritative source of truth** for:

- Which **refiner models** and **hires-fix upscalers** appear in dropdowns.
- Which combinations are **recommended defaults** per model family/style
  (e.g., SDXL realism, SDXL portraits, SD1.5 realism, anime).

Key references:

- **Model Defaults Spec:** `docs/model_defaults_v2/V2-P1.md`  
  Defines canonical IDs (e.g., `sdxl_refiner_official`, `4x_ultrasharp`,
  `swinir_4x`, `wd15_refiner`) and style profiles such as
  `sdxl_realism`, `sdxl_stylized`, `sd15_realism`, `anime`.
- **ModelProfiles & Learning integration:**  
  `src/learning/model_profiles.py`  
  `docs/Learning_System_Spec_v2.md`  
  ModelProfiles encode `default_refiner_id`,
  `default_hires_upscaler_id`, `default_hires_denoise`, and an
  optional `style_profile_id`. Defaults seed new `PipelineConfig`
  instances whenever there is no last-run or preset override and
  provide the **baseline** for Learning Runs.

Precedence for refiner/hires settings:

1. Last-run config (if present)  
2. Explicit preset (if applied)  
3. ModelProfile / StyleProfile defaults  
4. Engine fallback (no refiner / basic upscaler)

The GUI Pipeline tab **never invents defaults**; it displays and edits
the `PipelineConfig` built from these sources.
