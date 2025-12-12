PR-044-RANDOMIZER-GUI-INTEGRATION-V2-P1
1. Title

PR-044 – Randomizer GUI Integration with RandomizerEngineV2 & JobDraft (V2-P1)

2. Summary

This PR wires the Pipeline tab Randomizer controls into the new RandomizerEngineV2 so that:

The Randomizer card in the Pipeline left column edits a RandomizationPlanV2 stored in AppStateV2.

The JobDraft uses that plan when building jobs:

If Randomizer is disabled → single job using the base config.

If enabled → expands into multiple config variants using generate_run_config_variants.

The Job Preview panel (right side) shows a clear summary of:

How many variants will be created.

Which fields are randomized (models / samplers / CFG / steps / batch sizes, etc.).

When a job is added to the queue (or run directly), the queue receives one job per variant using the engine output.

No executor/pipeline core changes; this is purely about hooking existing UI + AppState into the engine from PR-043.

3. Problem Statement

Currently:

The Randomizer panel in the Pipeline left column exists, but:

It doesn’t produce a structured RandomizationPlan.

It doesn’t affect the JobDraft or pipeline jobs.

The RandomizerEngineV2 (PR-043) can generate multiple RunConfigV2 variants, but:

It isn’t called anywhere.

The JobQueue never sees the expanded set of variants.

The Job Preview on the right side doesn’t reflect:

How many variants will be created.

Which fields are randomized.

As a result, toggling randomization has no real effect, and users can’t see or reason about what the system will actually run.

We need to connect these pieces so the Randomizer UI → AppState → engine → JobQueue → preview path is real and deterministic.

4. Goals

Make the Randomizer panel authoritative for randomization

The controls in the Pipeline left column:

Enable/disable randomization.

Set max variants.

Configure seed mode.

Configure which fields to randomize (models, samplers, CFG, steps, batches).

Are mapped to a RandomizationPlanV2 object stored in AppStateV2.

Integrate RandomizerEngineV2 into job creation

When user clicks “Add to Job ”:

The controller gathers:

Base RunConfigV2 (from current pipeline config).

RandomizationPlanV2 (from AppStateV2).

Calls generate_run_config_variants(base_config, plan, rng_seed=...).

Creates one prompt per variant and adds them to the preview (or current job bundle).

Update Job Preview panel

Show:

Total variant count that will be created by the current draft.

A short summary of which fields are randomized:

e.g., Models: 2 choices, CFG: [4.5, 7.0], Steps: [20, 30], Seed: per-variant from 100.

Make it obvious when Randomizer is off vs on.

Stay aligned with V2 design system

Do not change theme tokens or card visuals in this PR.

Reuse existing styles; no new one-off styling or colors.

Only adjust labels/tooltips where necessary to clarify behavior.

Add targeted tests

Controller tests that confirm:

Randomizer is invoked when enabled.

Job expansion uses variants from the engine.

GUI tests that confirm:

Randomizer panel writes a correct plan into AppState.

Job preview picks up plan changes.

5. Non-goals

No changes to executor or WebUI integration.

No Learning or per-image rating integration here.

No job-history changes beyond whatever is already in place.

No new randomization features beyond config-level randomization:

No prompt-matrix/random token logic in this PR.

No visual re-design of the Randomizer panel (PR-041/041B handles design kit/theming).

6. Allowed Files

Randomizer panel & pipeline GUI

src/gui/panels_v2/randomizer_panel_v2.py (or whichever module currently implements the Randomizer controls).

src/gui/views/pipeline_tab_frame_v2.py

Only for plumbing between Randomizer panel ↔ AppState ↔ controller.

App state & controller

src/gui/app_state_v2.py

To add a randomization_plan_v2 field or extend JobDraft with randomization metadata.

src/controller/app_controller.py

To:

Receive randomizer updates from the panel.

Attach plan to JobDraft.

Invoke generate_run_config_variants when creating jobs.

Job model / queue / preview

src/pipeline/job_models_v2.py or equivalent

Only if you need to add a small field indicating that a job is “variant N of M”.

src/pipeline/job_queue_v2.py or equivalent

Only if necessary to accept a list of jobs rather than a single job; ideally it already accepts lists.

src/gui/panels_v2/preview_panel_v2.py (or equivalent job preview panel)

To display the randomization summary.

Randomizer engine (read-only imports)

src/randomizer/randomizer_engine_v2.py

Import only; no changes to engine logic in this PR.

Tests

tests/controller/test_randomizer_integration_v2.py (new)

tests/gui_v2/test_pipeline_randomizer_panel_v2.py (new)

tests/gui_v2/test_job_preview_randomizer_summary_v2.py (new, if you keep preview-specific assertions separate).

7. Forbidden Files

Do not modify:

src/main.py

src/pipeline/executor.py or src/pipeline/executor_v2.py

src/api/healthcheck.py

src/api/webui_process_manager.py

src/api/webui_client.py

Any V1/legacy randomizer files:

src/utils/randomizer.py

tests/utils/test_randomizer_*

Any theme system core:

src/gui/theme_v2.py (no new tokens or style changes in this PR)

src/gui/main_window_v2.py (layout / wiring)

Unless a tiny helper is absolutely required, but in principle: don’t touch.

Any need to change these should be split into another PR with explicit justification.

8. Step-by-step Implementation
A. Represent Randomization Plan in AppStateV2

In app_state_v2.py:

Add a new field, either directly on AppStateV2 or as part of JobDraft:

from src.randomizer import RandomizationPlanV2, RandomizationSeedMode

@dataclass
class JobDraft:
    ...
    randomization_plan: RandomizationPlanV2 = field(default_factory=RandomizationPlanV2)


Ensure there are helper methods to:

Get the current plan: get_randomization_plan()

Update the plan: update_randomization_plan(plan: RandomizationPlanV2)

If JobDraft already exists, extend it; if not, use the app_state field that represents the “currently assembled Job”.

Make sure any existing serialization/clone logic for JobDraft includes randomization_plan (if applicable).

B. Wire RandomizerPanelV2 to AppState/Controller

In randomizer_panel_v2.py:

Ensure the panel has a single source of truth for its UI state:

Enable checkbox

Max variants spinbox / entry

Seed mode selector (fixed / per-variant / none)

Seed entry (if in fixed/per-variant mode)

Field-level toggles or multi-selects for:

models

samplers

steps

CFG

batch sizes

(You can model these as lists of values or ranges; stick to whatever the current controls support.)

Add methods:

def load_from_plan(self, plan: RandomizationPlanV2) -> None:
    # Update all widgets from plan

def build_plan(self) -> RandomizationPlanV2:
    # Read current widget values into a RandomizationPlanV2


On any relevant widget change:

call self._on_plan_changed(plan) where _on_plan_changed will delegate to the AppController (via callback) to update AppState.

In pipeline_tab_frame_v2.py:

When constructing the Randomizer panel:

Inject a callback from controller/app_state, e.g.:

randomizer_panel = RandomizerPanelV2(
    parent=self.left_column_frame,
    on_plan_changed=self._controller.on_randomizer_plan_changed,
)


On tab init:

Load initial plan from AppState into the panel via load_from_plan(...).

C. Connect AppController to AppState and RandomizerEngine

In app_controller.py:

Import from the engine:

from src.randomizer import RandomizationPlanV2, RandomizationSeedMode, generate_run_config_variants


Implement plan update handler:

def on_randomizer_plan_changed(self, plan: RandomizationPlanV2) -> None:
    self._app_state.update_randomization_plan(plan)
    self._update_job_preview_randomizer_summary()


Integrate randomizer into job creation:

Find the method that builds jobs from the current JobDraft when user clicks:

“Add to Job”

“Add to Queue”

“Run Now” (if present)

Typically something like:

def _build_jobs_from_draft(self) -> list[Job]:
    run_config = self._app_state.get_run_config()
    draft = self._app_state.get_job_draft()

    plan = draft.randomization_plan
    variants = generate_run_config_variants(run_config, plan, rng_seed=plan.base_seed or <some default>)

    jobs = []
    for idx, cfg in enumerate(variants):
        job = self._job_factory.create_job_from_config_and_draft(cfg, draft, variant_index=idx, variant_total=len(variants))
        jobs.append(job)

    return jobs


Existing queue methods should call _build_jobs_from_draft() instead of directly using the single run config.

Make sure that when Randomizer is disabled (enabled=False), the engine returns a single variant, so behavior is backwards-compatible.

D. Update Job Preview Panel to Show Randomizer Summary

In preview_panel_v2.py (or equivalent):

Extend the panel’s public API:

Add a method like:

def update_randomizer_summary(self, plan: RandomizationPlanV2, estimated_variant_count: int) -> None:
    # Renders a concise textual summary from plan


The summary should include:

Whether randomization is enabled.

If enabled:

Max variants: N

Models: len(plan.model_choices) if > 0

Samplers: len(plan.sampler_choices)

CFG: values (maybe truncated to first few)

Steps: values

Seed mode: FIXED/PER_VARIANT/NONE and the base seed.

Back in app_controller.py:

Implement _update_job_preview_randomizer_summary():

def _update_job_preview_randomizer_summary(self) -> None:
    draft = self._app_state.get_job_draft()
    plan = draft.randomization_plan
    if not plan.enabled:
        estimated = 1
    else:
        # Estimate by looking at non-empty choice lists, bounded by max_variants.
        estimated = self._estimate_variant_count(plan)

    self._preview_panel.update_randomizer_summary(plan, estimated)


Implement _estimate_variant_count(plan) as a small helper in the controller (not in engine):

Multiply lengths of non-empty choice lists (model, sampler, steps, cfg, etc.).

If result is 0, treat as 1 (base variant only).

Bound by plan.max_variants.

E. Tests

tests/controller/test_randomizer_integration_v2.py:

Use fake RunConfigV2 and fake JobDraft.

Test 1: Randomizer disabled

Plan: enabled=False.

Call the controller’s “build jobs from draft” method.

Assert only one job is created.

Test 2: Simple enabled plan

Plan: enabled=True, max_variants=3, model_choices=["m1", "m2", "m3"].

Assert:

generate_run_config_variants is called with that plan.

Exactly 3 jobs are created.

Each job’s config has model in {"m1","m2","m3"}.

Test 3: Multi-field with truncation

Plan with multiple lists and large theoretical grid, max_variants=2.

Assert engine is called and exactly 2 jobs created.

tests/gui_v2/test_pipeline_randomizer_panel_v2.py:

Mark as gui, skip if Tk unavailable.

Construct RandomizerPanelV2 with a fake on_plan_changed callback.

Simulate:

Toggling enabled.

Setting max_variants=3.

Choosing seed mode and base seed.

Possibly entering a couple of CFG/steps values (depending on how the current UI encodes these).

Call build_plan() and verify:

plan.enabled matches checkbox.

plan.max_variants matches the UI.

Seed mode/values are propagated.

on_plan_changed called with the same plan.

tests/gui_v2/test_job_preview_randomizer_summary_v2.py (or fold into an existing preview panel test):

Instantiate preview panel with fake labels.

Call update_randomizer_summary with:

Plan disabled.

Plan enabled with some values.

Assert rendered text / internal label string contains expected phrases:

“Randomizer: OFF” vs “Randomizer: ON”.

“Max variants: N”.

“Models: 2 choices” etc.

9. Required Tests (Failing first)

Before implementation:

tests/controller/test_randomizer_integration_v2.py

tests/gui_v2/test_pipeline_randomizer_panel_v2.py

tests/gui_v2/test_job_preview_randomizer_summary_v2.py

will either not exist or fail.

After implementation, all three must pass:

python -m pytest tests/controller/test_randomizer_integration_v2.py -q
python -m pytest tests/gui_v2/test_pipeline_randomizer_panel_v2.py -q
python -m pytest tests/gui_v2/test_job_preview_randomizer_summary_v2.py -q


Existing tests must remain green (aside from known GUI skips).

10. Acceptance Criteria

PR-044 is complete when:

Randomizer panel → plan → AppState

Changing controls in the Randomizer panel updates a RandomizationPlanV2 in AppStateV2 / JobDraft.

build_plan() and load_from_plan() round-trip cleanly.

Plan → engine → jobs

When Randomizer is disabled:

Job creation behaves exactly as before (single config).

When Randomizer is enabled:

generate_run_config_variants is invoked.

The queue receives multiple jobs (one per variant).

Preview reflects randomization

Job Preview panel indicates:

Whether Randomizer is on.

Approximate variant count.

High-level summary of which fields are randomized.

No forbidden files changed

main.py, executor, healthcheck, WebUI process manager, legacy randomizer remain untouched.

Manual behavior

From user’s perspective:

If they enable randomization and set e.g. max_variants=3 with multiple model choices, running the pipeline produces multiple jobs/variants instead of just one.

11. Rollback Plan

If PR-044 causes regressions:

Revert changes to:

randomizer_panel_v2.py

pipeline_tab_frame_v2.py

app_state_v2.py

app_controller.py

preview_panel_v2.py

Any small modifications in job model/queue

All new tests

Verify:

python -m pytest -q
python -m src.main


Confirm behavior returns to “pre-PR-044”: Randomizer UI inert again, but no pipeline breakage.

12. Codex Execution Constraints

Use RandomizationPlanV2 + generate_run_config_variants from PR-043; do not re-implement randomization logic.

Do not import or reference legacy src/utils/randomizer.py.

Minimize changes to controller/API signatures; favor adding new small methods over modifying existing ones heavily.

No new theme constants / color values.

Preserve type hints and style consistent with surrounding code.

13. Smoke Test Checklist

After Codex implements PR-044:

Run tests:

python -m pytest tests/controller/test_randomizer_integration_v2.py -q
python -m pytest tests/gui_v2/test_pipeline_randomizer_panel_v2.py -q
python -m pytest tests/gui_v2/test_job_preview_randomizer_summary_v2.py -q


Launch GUI:

python -m src.main


Manual check:

Go to Pipeline tab.

Enable Randomizer, set:

max_variants = 3

A couple of model choices / CFG / steps values.

Add job / run pipeline.

Verify:

Preview shows multiple variants.

Queue shows multiple jobs or runs that correspond to those variants.

Disable Randomizer and confirm behavior returns to “single job per run”.