PR-081B – Pipeline Tab Controls for Refiner & Hires Fix
Intent

Expose refiner and hires fix as first-class controls in the V2 Pipeline tab so a user can configure them on the txt2img (and, where applicable, img2img) stage cards.

This PR only wires UI → AppStateV2 → RunConfig using the config surface from PR-081A. It does not yet change the underlying WebUI behavior beyond passing the config values along.

Files

GUI / Pipeline

src/gui/pipeline_tab_v2.py (Pipeline tab container)

src/gui/components/pipeline/txt2img_stage_card.py

src/gui/components/pipeline/img2img_stage_card.py (if img2img should expose hires)

Styling / Theme

src/gui/theme_v2.py (labels, spacing, sections, icons if any)

State Binding

src/gui/app_state_v2.py (ensure bindings between UI and config fields)

Tests

tests/gui/test_pipeline_tab_v2.py (or equivalent GUI test module)

Possibly new component-level tests for txt2img/img2img cards

Detailed Changes
1) Refiner controls on txt2img card

File: src/gui/components/pipeline/txt2img_stage_card.py

Add a small “Refiner” section to the txt2img card UI. Suggested layout:

Checkbox: “Enable refiner”

Dropdown: “Refiner model”

Slider / spinbox: “Refiner start”

Example (pseudo-code; adapt to actual widget framework):

class Txt2ImgStageCard(ttk.Frame):
    def __init__(self, parent, app_state: AppStateV2, *args, **kwargs):
        super().__init__(parent, *args, **kwargs)
        self.app_state = app_state
        cfg = self.app_state.current_config

        # existing UI...

        # Refiner section
        self.refiner_enabled_var = tk.BooleanVar(value=cfg.refiner_enabled)
        self.refiner_model_var = tk.StringVar(value=cfg.refiner_model_name or "")
        self.refiner_switch_var = tk.DoubleVar(value=cfg.refiner_switch_at)

        self.refiner_enable_check = ttk.Checkbutton(
            self,
            text="Enable refiner",
            variable=self.refiner_enabled_var,
            command=self._on_refiner_toggle,
        )

        self.refiner_model_combo = ttk.Combobox(
            self,
            textvariable=self.refiner_model_var,
            state="readonly",
            # values will be populated from app_state / model registry
        )

        self.refiner_switch_scale = ttk.Scale(
            self,
            from_=0.0,
            to=1.0,
            variable=self.refiner_switch_var,
            command=self._on_refiner_switch_changed,
        )


Model list:

First pass: filter the available models to “refiner” candidates using whatever naming/tag convention you’re already using for SDXL (e.g., *_refiner, “XL Refiner”). If that registry doesn’t exist yet, this PR can temporarily surface all models with a TODO.

Bind callbacks:

def _on_refiner_toggle(self):
    cfg = self.app_state.current_config
    cfg.refiner_enabled = self.refiner_enabled_var.get()

def _on_refiner_model_changed(self, *_):
    cfg = self.app_state.current_config
    cfg.refiner_model_name = self.refiner_model_var.get() or None

def _on_refiner_switch_changed(self, *_):
    cfg = self.app_state.current_config
    cfg.refiner_switch_at = float(self.refiner_switch_var.get())


If you prefer a 0–100 slider: store 0–100 in the widget; map to 0–1 in cfg.refiner_switch_at.

2) Hires fix controls on txt2img card

Add a collapsible “Hires fix” section in the same card. Suggested controls:

Checkbox: “Enable Hires fix”

Dropdown: “Hires upscaler”

Numeric: “Upscale factor”

Numeric: “Hires steps” (optional; can be None)

Slider / numeric: “Hires denoise strength”

Example wiring:

self.hires_enabled_var = tk.BooleanVar(value=cfg.hires_enabled)
self.hires_upscaler_var = tk.StringVar(value=cfg.hires_upscaler_name)
self.hires_factor_var = tk.DoubleVar(value=cfg.hires_upscale_factor)
self.hires_steps_var = tk.IntVar(value=cfg.hires_steps or 0)
self.hires_denoise_var = tk.DoubleVar(value=cfg.hires_denoise)

# Checkbox
self.hires_enable_check = ttk.Checkbutton(
    self,
    text="Enable Hires fix",
    variable=self.hires_enabled_var,
    command=self._on_hires_toggle,
)

# Upscaler dropdown
self.hires_upscaler_combo = ttk.Combobox(
    self,
    textvariable=self.hires_upscaler_var,
    state="readonly",
    # values from app_state / WebUI upscaler list
)

# Factor / steps / denoise inputs...


Callbacks:

def _on_hires_toggle(self):
    cfg = self.app_state.current_config
    cfg.hires_enabled = self.hires_enabled_var.get()

def _on_hires_upscaler_changed(self, *_):
    cfg = self.app_state.current_config
    cfg.hires_upscaler_name = self.hires_upscaler_var.get()

def _on_hires_factor_changed(self, *_):
    cfg = self.app_state.current_config
    cfg.hires_upscale_factor = float(self.hires_factor_var.get())

def _on_hires_steps_changed(self, *_):
    cfg = self.app_state.current_config
    value = int(self.hires_steps_var.get())
    cfg.hires_steps = value if value > 0 else None

def _on_hires_denoise_changed(self, *_):
    cfg = self.app_state.current_config
    cfg.hires_denoise = float(self.hires_denoise_var.get())


Defaults:

Keep UI defaults aligned with PR-081A: off, 2.0x, “Latent” upscaler, 0.3 denoise.

3) Optional: hires subset on img2img card

File: src/gui/components/pipeline/img2img_stage_card.py

If your V2 design calls for hires fix on img2img as well:

Mirror a subset of controls:

Enable Hires fix

Upscaler

Upscale factor

Denoise

Bind to the same CurrentConfig fields or to a dedicated Img2ImgConfig if one exists. For this PR, keep it simple:

If CurrentConfig is global, txt2img and img2img can share hires settings.

A later PR can split per-stage hires configs if needed.

4) Pipeline tab wiring

File: src/gui/pipeline_tab_v2.py

Where the Pipeline tab constructs stage cards and maps AppState → RunConfig:

Ensure the run-config builder pulls the new fields from app_state.current_config into:

RunConfig.txt2img.refiner_*

RunConfig.hires_fix.*

Example (conceptual):

def _build_run_config_from_state(self) -> RunConfig:
    cfg = self.app_state.current_config

    txt2img_cfg = Txt2ImgConfig(
        # existing fields...
        refiner_enabled=cfg.refiner_enabled,
        refiner_model_name=cfg.refiner_model_name,
        refiner_switch_at=cfg.refiner_switch_at,
    )

    hires_cfg = HiresFixConfig(
        enabled=cfg.hires_enabled,
        upscale_factor=cfg.hires_upscale_factor,
        upscaler_name=cfg.hires_upscaler_name,
        hires_steps=cfg.hires_steps,
        hires_denoise=cfg.hires_denoise,
        use_base_model_for_hires=cfg.hires_use_base_model_for_hires,
    )

    return RunConfig(
        txt2img=txt2img_cfg,
        # other stages...
        hires_fix=hires_cfg,
    )


This leverages the PR-081A model without changing runner behavior (runner can continue to ignore those fields until the next behavioral PR).

5) Theme updates

File: src/gui/theme_v2.py

Add any necessary constants, labels, or styles:

Section titles: "Refiner", "Hires fix".

Optional icons or spacing constants for collapsible sections.

Typography spacing for nested groups.

Keep styling consistent with existing StageCard UI conventions.

6) GUI Tests

File: tests/gui/test_pipeline_tab_v2.py (or new equivalent)

Add tests to verify:

Toggling the “Enable refiner” checkbox updates app_state.current_config.refiner_enabled.

Selecting a refiner model updates refiner_model_name.

Adjusting the “Refiner start” control updates refiner_switch_at (or correct 0–1 mapping if using percentages).

Toggling “Enable Hires fix” updates hires_enabled.

Changing upscaler / factor / steps / denoise propagates to CurrentConfig.

Building a RunConfig from the Pipeline tab includes the same values in Txt2ImgConfig and HiresFixConfig as in CurrentConfig.

These can be light-weight widget tests that instantiate the pipeline tab and stage cards with a dummy AppStateV2.

Out of Scope (explicit)

No new calls to WebUI or changes in actual generation order (that will be a follow-on “behavioral” PR).

No ADetailer logic changes — it remains the final stage, but we’re not modifying its configuration here.

No special error handling changes; existing error pathways for pipeline runs stay as-is.