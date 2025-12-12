PR-GUI-V2-PIPELINE-CONFIG-WIRING-002-(2025-11-26).md

Author: StableNew Assistant (with Rob)
Status: Draft (ready for Copilot/Codex)
Area: GUI V2 – Pipeline Tab / StateManager / PipelineConfigAssembler / PipelineController
Depends on:

PR-GUI-V2-PIPELINE-RUNTAB-MERGE-001 (stage cards already live on Pipeline tab center pane)
Key backend refs:

src/pipeline/pipeline_config_assembler.py

src/controller/pipeline_controller.py

src/pipeline/pipeline_runner.py

src/controller/app_controller.py (legacy skeleton, for context only)

src/pipeline/executor.py (real executor / WebUI integration)

1. Summary

The Pipeline tab stage cards are currently inert: users see txt2img / img2img / upscale cards, but changes made in the UI don’t flow into the pipeline configuration, and there’s no robust validation before Run.

This PR wires the Pipeline tab GUI into the real configuration pathway:

Stage card inputs update a canonical PipelineState / StateManager view of GUI overrides.

PipelineController._build_pipeline_config_from_state() uses that state to call
PipelineConfigAssembler.build_from_gui_input(...) to produce a PipelineConfig.

That PipelineConfig is passed to PipelineRunner.run(...), which already drives the real multi-stage executor.

Basic GUI-level validation & guardrails ensure required fields are set and obviously-invalid values (e.g., width <= 0) are blocked before a run.

After this PR, a user can:

Configure txt2img/img2img/upscale fully from the Pipeline tab.

Hit Run in the header.

Have a real, validated PipelineConfig drive the executor end-to-end.

2. Problem Statement

Currently:

Pipeline tab cards look right but don’t own the actual config.

The real configuration is assembled through PipelineConfigAssembler + PipelineController, but the GUI state feeding into them is either stubbed or coming from legacy Run tab state.

There is little/no validation at GUI level: you can hit Run even if samplers or models aren’t selected, or dimensions are nonsense.

We need to:

Treat Pipeline tab stage controls as the single source of truth for GUI overrides used by PipelineConfigAssembler.

Encode a minimal set of guardrails so “obviously broken” configs don’t reach the runner.

3. Goals and Non-Goals
3.1 Goals

Connect Pipeline tab UI to PipelineState / StateManager:

Changes in txt2img/img2img/upscale controls update a shared overrides structure (dict or GuiOverrides) on the StateManager (get_pipeline_overrides / pipeline_overrides).

Ensure PipelineController._build_pipeline_config_from_state() produces a fully populated PipelineConfig by calling:
self._config_assembler.build_from_gui_input(...).

Populate dropdowns (sampler, scheduler, checkpoint, upscaler, format, etc.) with valid choices from ConfigManager / WebUI config where possible.

Add basic validation:

Required fields: model / sampler / width / height / steps / batch size / image format.

Range checks: width/height > 0, steps >= 1, cfg_scale in a sane range, denoise ∈ (0,1], etc.

If invalid, prevent run and show a clear error in the status/log area.

Ensure wiring is consistent across stages:

txt2img feeds base generation config.

img2img / ADetailer consumes upstream image / settings.

Upscale consumes upstream image + its own upscaler config.

3.2 Non-Goals

Deep Learning tab integration (that’s later, using the same config but different runners).

X/Y or matrix randomization wiring (beyond what PromptRandomizer already supports).

Any major redesign of the Pipeline tab visual layout (only minor adjustments if needed to host widgets).

4. Architectural Context
4.1 PipelineConfigAssembler

PipelineConfigAssembler is designed to take GUI-level overrides and produce a validated PipelineConfig. Key features:

Accepts GuiOverrides (prompt, model, model_name, vae_name, sampler, width, height, steps, cfg_scale, resolution_preset, negative_prompt, output_dir, filename_pattern, image_format, batch_size, seed_mode, metadata, etc.).

Knows about:

ConfigManager defaults & config profiles.

PromptRandomizer metadata.

PromptWorkspaceState & PipelineState (for prompt packs, stage enable flags, etc.).

Can be reused for:

normal pipeline runs,

randomizer jobs,

learning jobs (with extra learning metadata).

4.2 PipelineController

PipelineController is already wired to:

Hold a StateManager (src.gui.state.StateManager) that exposes GUI state.

Assemble a config via:

def _build_pipeline_config_from_state(self) -> PipelineConfig:
    overrides = self._extract_state_overrides()
    learning_metadata = self._extract_metadata("learning_metadata")
    randomizer_metadata = self._extract_metadata("randomizer_metadata")
    ...
    return self._config_assembler.build_from_gui_input(
        overrides=overrides,
        learning_metadata=learning_metadata,
        randomizer_metadata=randomizer_metadata,
    )


_extract_state_overrides() tries:

state_manager.get_pipeline_overrides()

or state_manager.pipeline_overrides

or falls back to a GUI-specific method.

Conclusion: the missing piece is getting the Pipeline tab widgets to actually update state_manager in the expected format.

5. Implementation Plan

This PR is big enough that you may want to split into sub-PRs (002A–002D). The steps are ordered so each can be a safe checkpoint.

5.1. Define / Confirm Pipeline Overrides Interface on StateManager

Files:

src/gui/state.py (or wherever StateManager, PipelineState, and GUIState live)

src/controller/pipeline_controller.py

Steps:

Add or solidify PipelineState structure:

Ensure there is a PipelineState dataclass that includes:

enabled_stages / booleans for txt2img, img2img, upscale.

txt2img fields: model_name, vae_name, sampler, scheduler, steps, cfg_scale, width, height, batch_size, seed_mode, output_dir, filename_pattern, image_format, etc.

img2img fields: denoise_strength, steps, cfg_scale, sampler, scheduler, etc.

upscale fields: upscaler_name, scale_factor, any tiling options.

If these already exist, confirm their names and types align with GuiOverrides fields in PipelineConfigAssembler.

Implement the accessor that PipelineController expects:

class StateManager:
    def get_pipeline_overrides(self) -> dict[str, Any]:
        # Serialize PipelineState into a dict keyed for GuiOverrides
        ...


Map field names to GuiOverrides exactly (width, height, steps, cfg_scale, resolution_preset, image_format, batch_size, seed_mode, etc.).

Include any metadata that should go into GuiOverrides.metadata.

Ensure PipelineController._extract_state_overrides() successfully receives a dict / GuiOverrides constructed from get_pipeline_overrides() and passes it to _coerce_overrides().

5.2. Wire txt2img Stage Card Controls → PipelineState

Files:

src/gui/tabs/pipeline_tab_v2.py

src/gui/panels/stage_panels.py (if extracted in PR-001)

src/gui/state.py (bindings / update helpers)

Steps:

For each txt2img control (combo, slider, entry, checkbox):

On change, call a helper like:

self.state_manager.update_txt2img(
    sampler=self.sampler_var.get(),
    steps=self.steps_var.get(),
    cfg_scale=self.cfg_var.get(),
    width=self.width_var.get(),
    height=self.height_var.get(),
    ...
)


Implementation can be one consolidated update_txt2img or smaller per-field setters, but the important part is: all values used by txt2img are reflected in PipelineState.

Initialize controls from defaults:

Use ConfigManager (via PipelineConfigAssembler or directly) to get default sampler, steps, width/height, etc.

On first creation of txt2img card, read defaults and populate:

Combobox values (e.g., sampler list).

Initial selection index.

Sliders and spinboxes (steps, cfg, batch size).

Make sure model / VAE / sampler selection uses the real lists from WebUI / ConfigManager if available; if not, fall back to static lists.

Verify that when user hits Run:

PipelineController asks StateManager for overrides.

GuiOverrides contains the values the user set.

5.3. Wire img2img / ADetailer Stage Card Controls → PipelineState

Files:

src/gui/panels/stage_panels.py

src/gui/tabs/pipeline_tab_v2.py

src/gui/state.py

Steps:

Identify all img2img / ADetailer controls:

Source image selector / path.

Denoise slider.

Steps, cfg scale, sampler, scheduler.

Enable/disable ADetailer; region or mask options (if present).

Implement StateManager.update_img2img(...) (or equivalent):

def update_img2img(self, *, enabled: bool | None = None, denoise: float | None = None, ...):
    ...


Connect widget callbacks:

Combobox <<ComboboxSelected>> → calls update_img2img(...).

Slider <ButtonRelease-1> or variable trace → calls update_img2img(denoise=value) with quantized float.

Checkboxes → update enabled flags.

Make sure PipelineState carries:

An img2img_enabled flag the PipelineController can read.

The denoise value, plus any required config keys for the executor.

Ensure PipelineConfigAssembler can pick up img2img overrides via gui_overrides / metadata (if needed), or note any TODOs for a follow-up assembler PR if extra fields must be added there.

5.4. Wire Upscale Stage Card Controls → PipelineState

Files:

src/gui/panels/stage_panels.py

src/gui/tabs/pipeline_tab_v2.py

src/gui/state.py

Steps:

Identify Upscale controls:

Upscaler dropdown (ESRGAN, UltraSharp, etc.).

Scale factor (2x, 4x, custom).

Optional tiling settings (tile size, overlap).

Implement StateManager.update_upscale(...):

def update_upscale(self, *, enabled: bool | None = None, upscaler: str | None = None, scale: float | None = None, ...):
    ...


Wire comboboxes and sliders to the updater.

Ensure PipelineConfigAssembler can include these fields in configuration:

Either via existing metadata structure or dedicated keys on GuiOverrides.

Confirm PipelineRunner / executor knows how to interpret these settings (should already exist; this PR just feeds them).

5.5. Front-End Validation Before Run

Files:

src/controller/pipeline_controller.py

src/gui/state.py

Optional: a small src/gui/validation.py

Steps:

Add a GUI validation helper:

def validate_pipeline_overrides(overrides: GuiOverrides) -> list[str]:
    errors = []
    if not overrides.model_name:
        errors.append("Base model must be selected.")
    if not overrides.sampler:
        errors.append("Sampler must be selected.")
    if overrides.width <= 0 or overrides.height <= 0:
        errors.append("Width and height must be positive.")
    if overrides.steps <= 0:
        errors.append("Step count must be positive.")
    ...
    return errors


In PipelineController._build_pipeline_config_from_state() or before run_pipeline:

Call validate_pipeline_overrides(overrides); if errors exist:

Don’t call PipelineConfigAssembler or PipelineRunner.

Use StructuredLogger + GUI status/log panel to display a single summary and maybe a bullet list.

Optionally, tie control-level hints:

Mark invalid fields visually (e.g., border color, tooltip).

This can be deferred to a follow-up PR; for now, a clear error message is sufficient.

5.6. Guardrails for Allowed Choices

Files:

src/utils/config.py (ConfigManager – only if needed)

src/gui/panels/stage_panels.py

Steps:

For each dropdown (sampler, scheduler, image format, upscaler):

Populate values using ConfigManager / WebUI defaults where possible.

If WebUI isn’t reachable yet, fall back to a safe static list.

Ensure the user cannot select invalid combinations:

E.g., only supported image formats from ConfigManager’s list.

Sampler list must be those the executor can handle; no free-text entry.

If the config changes at runtime (e.g., WebUI reconnect with new samplers):

Provide a simple refresh hook (can be a later PR; for now initial load is enough).

6. Testing Plan
6.1. Manual

Happy path – txt2img only

Enable txt2img, disable img2img/upscale.

Select model, sampler, reasonable steps/CFG, width/height, batch size.

Press Run.

Confirm:

No validation errors.

PipelineRunner is invoked (status changes, logs show execution).

An image is produced in the configured output directory.

Missing required field

Clear sampler or model and keep stage enabled.

Press Run.

Expect:

Validation error message in status/log region.

No call to runner (no network requests to WebUI).

img2img + upscale chain

Enable txt2img + img2img + upscale.

Configure sensible values for each.

Run full pipeline.

Confirm multi-stage pipeline runs end-to-end without hitting key errors.

Invalid numeric fields

Set steps = 0 or width = -512 and attempt a run.

Confirm validation blocks execution with clear message.

6.2. Automated (where feasible)

Add / update tests for StateManager.get_pipeline_overrides():

Given a PipelineState with certain values, confirm the dict (or GuiOverrides) matches the expected fields.

Add unit test for validate_pipeline_overrides():

Valid overrides → no errors.

Missing sampler/model → specific error messages.

If GUI harness exists:

Smoke test that:

Changing a txt2img control updates StateManager as expected.

_build_pipeline_config_from_state() yields correct overrides.

7. Risks & Mitigations

Risk: Misaligned field names between PipelineState and GuiOverrides cause missing/ignored parameters.

Mitigation: Add a focused test to assert mapping between get_pipeline_overrides() and GuiOverrides fields used by PipelineConfigAssembler.

Risk: Too-strict validation blocks legitimate advanced configs.

Mitigation: Start with conservative, obvious checks only (non-empty, >0 ranges), and soften later if needed.

Risk: WebUI/ConfigManager not ready at app startup, so dropdowns look empty.

Mitigation: Provide static fallback lists and/or lazy load when connection becomes READY.

8. Follow-On PRs

Once this wiring PR lands:

Learning Tab Integration:

Use the same overrides + metadata to build PipelineConfig variants for JT-08/JT-09.

Per-field visual validation:

Highlight invalid fields, show inline helper text.

Preset/Style save & load:

Snapshot PipelineState + prompt packs into reusable presets (JT-11).