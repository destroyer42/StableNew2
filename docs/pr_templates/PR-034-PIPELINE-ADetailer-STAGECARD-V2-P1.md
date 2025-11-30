PR-034-PIPELINE-ADetailer-STAGECARD-V2-P1
1. Title

PR-034 – ADetailer Stage Card & Pipeline Stage Integration (V2-P1)

2. Summary

This PR promotes ADetailer to a first-class pipeline stage in GUI V2 and the pipeline payload:

Adds a dedicated ADetailer stage card in the center column (using the V2 design system card patterns).

Adds an “Enable ADetailer” checkbox in the Pipeline left-column Stages section.

Wires ADetailer config fields into:

Stage card UI (detector, model, confidence, mask options, etc.).

RunConfigV2 / pipeline config model.

JobDraft → Job → pipeline payload.

Hooks the ADetailer card’s dropdowns into WebUIResourceService so ADetailer models and detectors populate dynamically when WebUI is READY.

Integrates the ADetailer stage into the V2 stage sequence (between txt2img and upscale) without rewriting the executor core.

Adds focused tests to ensure flipping the ADetailer stage on/off changes the payload deterministically and doesn’t break existing runs.

This makes the canonical pipeline:

txt2img → ADetailer → (optional img2img) → upscale

for V2, while keeping everything behind a single “Enable ADetailer” stage toggle and following the theme_v2 design contract for visuals.

3. Problem Statement

Right now in V2:

ADetailer is not represented as its own stage in the GUI:

No stage toggle in the Pipeline left column.

No standalone ADetailer config card in the center column.

ADetailer config UI exists in the repo (ADetailerConfigPanel, etc.) but:

It is not wired into the V2 layout.

It is lumped conceptually with img2img instead of being its own stage.

Pipeline payload & JobDraft don’t expose ADetailer as a structured stage:

No clear ADetailer config object in RunConfigV2.

No ADetailer section in job draft / job payload.

WebUI resource refresh doesn’t populate ADetailer-specific dropdowns in GUI V2.

The actual pipeline executor can run an ADetailer stage, but that stage isn’t being fed parameters from V2 GUI.

The result: you can’t explicitly configure or toggle ADetailer in the V2 GUI, and the pipeline can’t learn from or randomize ADetailer usage systematically.

4. Goals

Expose ADetailer as a first-class stage in the Pipeline tab

Left column: an “ADetailer” checkbox in the Stage toggles group.

Center column: a visual ADetailer stage card (BaseCardV2) that appears when the stage is enabled.

Right column: job preview shows whether ADetailer is active and with which key settings.

Wire ADetailer config through the full data path

GUI → AppStateV2 → RunConfigV2 → JobDraft → Job → pipeline payload.

Ensure the stage sequencer includes an ADetailerStageConfig or equivalent.

Do this without rewriting the executor core.

Integrate with WebUI resources

When WebUI resources are refreshed, the ADetailer card’s dropdowns update:

ADetailer model list

Detector list (face/hand/body, etc.), if available.

If resources are missing, ADetailer’s controls degrade gracefully (e.g., disabled or showing a warning).

Follow the V2 design system (PR-041)

ADetailer stage card:

Uses BaseCardV2 or equivalent consistent card wrapper.

Uses theme tokens and styling helpers (style_card, style_section_header, style_input, etc.).

Uses the same layout patterns as txt2img/img2img/upscale cards.

Add tests that lock in the expected behavior

Enabling ADetailer flips a stage flag and populates stage config.

WebUI READY → resource refresh updates ADetailer dropdown options.

Pipeline payload differs when ADetailer is enabled vs disabled.

5. Non-goals

No ADetailer algorithm changes (we just wire parameters through).

No attempt to bundle ADetailer logic back into img2img; it’s a distinct stage.

No randomizer integration for ADetailer fields yet (that belongs in the Randomizer PRs).

No Learning/ratings changes for ADetailer beyond what job history/logging already captures.

No Light theme implementation — everything obeys the existing dark design tokens.

6. Allowed Files

Stage config & pipeline wiring

src/pipeline/run_config_v2.py (or equivalent file that defines the V2 run/job config structures)

src/pipeline/stage_sequencer_v2.py (or equivalent stage orchestration module)

src/pipeline/payload_builder_v2.py (if present; otherwise the module that maps RunConfig → pipeline payload)

V2 GUI – stage cards & pipeline tab

src/gui/stage_cards_v2/base_stage_card_v2.py

src/gui/stage_cards_v2/adetailer_stage_card_v2.py (new)

src/gui/views/pipeline_tab_frame_v2.py (to register the new card with the center column/StageCardsPanel)

src/gui/panels_v2/stage_cards_panel_v2.py (or the main stage card panel that controls which cards are visible)

src/gui/panels_v2/sidebar_panel_v2.py

Specifically: stage toggles block; no unrelated logic changes.

App state & controllers

src/gui/app_state_v2.py

src/controller/app_controller.py

Only for:

Stage toggle handling

Loading/saving configs including ADetailer

Resource update → stage card update wiring

WebUI resources

src/api/webui_resource_service.py

To integrate ADetailer-related endpoints or resource names (if needed).

Design system (style-only)

src/gui/theme_v2.py

Only if new style names or tokens are needed for ADetailer card UI (no color hardcoding; use tokens).

Tests

tests/gui_v2/test_adetailer_stage_card_v2.py (new)

tests/pipeline/test_adetailer_stage_payload_v2.py (new)

tests/controller/test_adetailer_stage_integration_v2.py (new)

Minor updates to tests/controller/test_resource_refresh_v2.py or similar if the new ADetailer resource wiring needs coverage hooks.

7. Forbidden Files

Do not modify in this PR:

src/main.py

src/pipeline/executor.py / src/pipeline/executor_v2.py (core executor logic)

We assume an ADetailer stage hook exists; if not, that will be a separate, tightly scoped PR.

src/api/healthcheck.py

src/gui/main_window_v2.py (beyond style-only changes already defined in PR-041; no new wiring/layout)

src/gui/views/prompt_tab_frame_v2.py

src/gui/views/learning_tab_frame_v2.py

All legacy V1 files and shims.

If it turns out one of these must change to complete the PR, stop and split out a small “ADetailer executor hook” PR rather than folding it into PR-034.

8. Step-by-step Implementation
A. Define/extend the ADetailer stage config in pipeline models

In run_config_v2.py (or equivalent):

Introduce an ADetailerStageConfig dataclass or Pydantic model:

@dataclass
class ADetailerStageConfig:
    enabled: bool = False
    ad_model: str | None = None
    detector: str | None = None
    confidence: float = 0.35
    max_detections: int = 8
    mask_blur: int = 4
    mask_merge_mode: str = "keep"  # or enum if you already use one
    only_on_faces: bool = True
    only_on_hands: bool = False
    # extend minimally; reuse existing ADetailer config schema where possible


Add this to RunConfigV2:

class RunConfigV2:
    ...
    adetailer: ADetailerStageConfig = field(default_factory=ADetailerStageConfig)


Ensure RunConfigV2 serialization/deserialization includes the ADetailer block (for presets/last-run).

In stage_sequencer_v2.py (or equivalent):

Incorporate ADetailer into the canonical V2 stage sequence:

def build_stage_sequence(run_config: RunConfigV2) -> list[StageSpec]:
    stages = []
    stages.append(stage_for_txt2img(run_config.txt2img, ...))
    if run_config.adetailer.enabled:
        stages.append(stage_for_adetailer(run_config.adetailer, ...))
    if run_config.img2img.enabled:
        stages.append(stage_for_img2img(run_config.img2img, ...))
    if run_config.upscale.enabled:
        stages.append(stage_for_upscale(run_config.upscale, ...))
    return stages


stage_for_adetailer should reuse the existing ADetailer stage machinery (stage type, config keys) so the executor doesn’t need changes.

If there is a payload_builder_v2.py/equivalent:

Make sure the ADetailer stage config is mapped to the expected payload keys for the executor (no rewriting of executor; just structure the payload correctly).

B. Add ADetailerStageCardV2 (center column)

Create src/gui/stage_cards_v2/adetailer_stage_card_v2.py:

Base class:

Inherit from BaseStageCardV2 (which itself composes/inherits BaseCardV2 per PR-041).

Use design system helpers:

style_card(self)

style_section_header(self.title_label)

style_input(self.some_combobox)

style_toggle(self.some_checkbutton)

Layout:

Header: ADetailer title + a description label (“high-precision face/hand refinements after txt2img”).

Body sections:

Model & detector:

ttk.Combobox for ADetailer model (populated from WebUI resources).

ttk.Combobox for detector type (face, hand, body, etc.).

Threshold & limits:

ttk.Spinbox or slider for confidence.

ttk.Spinbox for max_detections.

Mask behavior:

ttk.Spinbox for mask_blur.

ttk.Combobox for mask_merge_mode.

Target filters:

Checkbutton for “only faces”.

Checkbutton for “only hands”.

API:

load_from_config(ad_cfg: ADetailerStageConfig) → populate widgets.

export_to_config() -> ADetailerStageConfig → read widgets into a config.

apply_webui_resources(resources: WebUIResources) → update model/detector dropdowns.

C. Wire ADetailer card into StageCardsPanel & Pipeline tab

In stage_cards_panel_v2.py:

Instantiate ADetailerStageCardV2 alongside txt2img/img2img/upscale.

Register it under a known key (e.g., "adetailer").

Implement show/hide logic:

def set_adetailer_enabled(self, enabled: bool) -> None:
    self._adetailer_card.set_visible(enabled)


Ensure this panel knows how to:

Load ADetailer config onto the card.

Read ADetailer config back into RunConfigV2.

In pipeline_tab_frame_v2.py:

Ensure the central “stage cards” panel exposes a method like update_from_run_config(run_config) and apply_to_run_config(run_config).

Make sure ADetailer is included in those flows.

D. Add ADetailer stage toggle to SidebarPanelV2 (left column)

In sidebar_panel_v2.py:

In the “Stages” card, add an “ADetailer” checkbox:

Use theme helpers for toggles: style_toggle(adetailer_checkbox).

Label: “ADetailer (faces/hands refinement)”.

On change:

Notify controller/app state via a standard callback:

e.g., on_stage_toggle_changed(stage_name="adetailer", enabled=value).

Ensure the Stage toggles card now controls the visibility of the ADetailer stage card (through AppController → AppStateV2 → StageCardsPanel).

E. Connect ADetailer config through AppStateV2 & AppController

In app_state_v2.py:

Extend the internal config/state object to include run_config.adetailer.

Ensure update_run_config / get_run_config includes ADetailer.

In app_controller.py:

Stage toggles:

When ADetailer checkbox changes:

Update RunConfigV2.adetailer.enabled.

Instruct StageCardsPanel to show/hide ADetailer card.

Mark job draft as dirty, so preview recomputes.

Config load/save:

When loading a config (preset/pack/default):

Apply ADetailer section to RunConfigV2.adetailer.

Call adetailer_card.load_from_config(...).

When saving a config:

Call adetailer_card.export_to_config().

Persist ADetailer section alongside txt2img/img2img/upscale.

JobDraft building:

When building a JobDraft:

Include ADetailer config from RunConfigV2.adetailer if enabled.

Ensure the payload passed to stage sequencer includes ADetailer stage.

F. Integrate ADetailer with WebUI resource refresh

In webui_resource_service.py:

If WebUI exposes ADetailer-specific resources (models/detectors):

Add aggregator logic to gather them, e.g.:

class WebUIResources:
    ...
    adetailer_models: list[str]
    adetailer_detectors: list[str]


If not explicit, derive them from existing endpoints or keep the lists empty (UI disables the dropdowns gracefully).

In app_controller.py (resource refresh path from PR-028/029):

When WebUI resources are refreshed and stored in AppStateV2:

Notify ADetailerStageCardV2 via:

stage_cards_panel.apply_resource_update(resources) or direct call.

ADetailer card should update its dropdowns.

G. Tests

tests/gui_v2/test_adetailer_stage_card_v2.py:

Mark as gui, skip if Tk is unavailable.

Validate:

Card initializes without errors.

load_from_config correctly sets widget states.

export_to_config roundtrips config values.

apply_webui_resources updates model/detector combobox values.

tests/pipeline/test_adetailer_stage_payload_v2.py:

Use a synthetic RunConfigV2:

Case 1: adetailer.enabled = False → stage sequence has no ADetailer stage.

Case 2: adetailer.enabled = True → stage sequence includes exactly one ADetailer stage with correct config fields.

Assert payload structure matches the expected schema used by the executor.

tests/controller/test_adetailer_stage_integration_v2.py:

Mock AppStateV2 & StageCardsPanel.

Simulate:

Stage toggle on/off events.

Config load (including ADetailer section).

Resource refresh with ADetailer models/detectors.

Assert:

AppStateV2.run_config.adetailer.enabled is updated correctly.

StageCardsPanel.set_adetailer_enabled called with correct value.

ADetailer card receives updated resources.

9. Required Tests (Failing first)

Before implementation:

New tests will fail or not exist:

test_adetailer_stage_card_v2.py → card class missing / not wired.

test_adetailer_stage_payload_v2.py → no ADetailer config or stage sequence logic.

test_adetailer_stage_integration_v2.py → controller hooks absent.

After implementation:

All three new tests must pass:

python -m pytest tests/gui_v2/test_adetailer_stage_card_v2.py -q
python -m pytest tests/pipeline/test_adetailer_stage_payload_v2.py -q
python -m pytest tests/controller/test_adetailer_stage_integration_v2.py -q


Existing GUI/pipeline tests must still pass (or be updated only for expected additions like an extra stage in a stage list).

10. Acceptance Criteria

This PR is considered done when:

GUI behavior

Pipeline tab shows:

A stage checkbox labeled “ADetailer” in the left column.

A central ADetailer stage card that appears when the checkbox is enabled.

ADetailer card:

Lets you choose model/detector.

Adjusts thresholds/limits/mask behavior.

Stores those values in the run config.

Payload & stages

When ADetailer is enabled:

Stage sequence includes an ADetailer stage with the correct config.

When disabled:

No ADetailer stage appears in the sequence.

Executor runs without modification (using existing ADetailer stage type).

WebUI resources

When WebUI resources load:

ADetailer model/detector dropdowns populate (or gracefully stay disabled if nothing is returned).

No Tk errors, no crashes if resources are empty.

Design system

ADetailer card visually matches other center cards:

Same background.

Same text color.

Same padding.

Uses BaseCardV2 + theme_v2 helpers.

No hardcoded colors in the ADetailer card file.

Tests

All required tests pass.

11. Rollback Plan

If this PR causes regressions:

Revert changes to:

run_config_v2.py (or equivalent)

stage_sequencer_v2.py / payload builder

app_state_v2.py

app_controller.py

webui_resource_service.py

adetailer_stage_card_v2.py

stage_cards_panel_v2.py

sidebar_panel_v2.py

All new test files.

Confirm that:

App boots.

Pipeline tab still works with txt2img/img2img/upscale.

No ADetailer stage is present.

12. Codex Execution Constraints

Do not modify the executor core; rely on existing ADetailer stage handling.

Keep GUI changes within V2 and behind the design system:

Use BaseCardV2 and theme_v2 style helpers.

No new raw hex colors.

Keep config/model changes minimal and focused:

Only add ADetailer-related fields to run config and stage sequencing.

Maintain typing and existing coding style; no new dependencies.

13. Smoke Test Checklist

After Codex implements this PR:

Run python -m src.main.

Go to the Pipeline tab.

Verify left-column Stages card now has an “ADetailer” checkbox.

Check/Uncheck “ADetailer”:

ADetailer stage card appears/disappears in the center.

With WebUI running and READY:

Confirm ADetailer dropdowns populate with at least one model/detector (or stay disabled with a clear state if none).

Configure:

ADetailer enabled.

Reasonable confidence/max detections/mask blur.

Run a simple job (one pack, small batch) and watch logs:

Verify the ADetailer stage is invoked (existing logs or pipeline debug output should show it).

Disable ADetailer and rerun:

Confirm the ADetailer stage is no longer in the sequence.

If all of the above pass and tests are green, PR-034 is ready to merge.