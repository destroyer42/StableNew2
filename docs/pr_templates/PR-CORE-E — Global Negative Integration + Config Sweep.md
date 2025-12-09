PR-CORE-E — Global Negative Integration + Config Sweep.md

Version: v2.6-CORE
Tier: Tier 2 (controller + builder integration + resolver changes + GUI wiring)
Author: ChatGPT (Planner), approved by Rob
Date: 2025-12-08
Discovery Reference: D-24
Depends on:

PR-CORE-A — UnifiedJobSummary + PromptPack-only invariant + NormalizedJobRecord schema

PR-CORE-B — Deterministic builder pipeline

PR-CORE-C — Queue/Runner lifecycle (job records must remain immutable)

PR-CORE-D — GUI alignment & PromptPack-only preview/running/queue/history panels

PROMPT_PACK_LIFECYCLE_v2.6.md – Defines global negatives, matrix slots, and override ownership

ARCHITECTURE_v2.6.md – Defines single-source-of-truth rules & builder pipeline boundaries

1. Summary (Executive Abstract)

PR-CORE-E introduces two foundational capabilities that extend the PromptPack-only architecture without violating subsystem boundaries:

A. Global Negative Prompt Integration

A unified mechanism to apply the global negative prompt—defined in app settings and optionally mirrored by pack-level per-stage flags—to all jobs during prompt resolution, not at the GUI level, not in the Pipeline tab, and not by modifying any PromptPack files.

This ensures:

Predictable, consistent application of a global negative layer

Clean separation between prompt authoring (PromptPack) and global configuration

Deterministic prompt resolution inside the builder pipeline (UnifiedPromptResolver)

B. Config Sweep Support (“same prompt, many configs”)

A formal, canonical mechanism for running multiple config variants for the same PromptPack in a single run, enabling:

Hyperparameter sweeps

Learning-driven optimization

Batch comparisons (e.g., CFG sweep, sampler sweep, step sweep)

Multi-axis testing, while keeping prompt text fixed

This introduces the new ConfigVariantPlanV2 that works analogously to RandomizationPlanV2 but applies strictly to config-level parameters, not prompt text.

Config sweeps are expanded via:

PromptPack Rows × Config Variants × Batch Size → list[NormalizedJobRecord]


All builder logic remains deterministic, pure, and compliant with architecture constraints.

2. Problem Statement

The PromptPack-only architecture stabilizes prompting, but two remaining capabilities are required for real-world usage, testing, and model tuning:

1. No unified global negative integration path

Global negative must be part of prompt resolution, not accidental GUI text.

Pack JSON already contains per-stage apply_global_negative_* flags, but no pipeline-level enforcement.

2. No first-class support for config sweeps

Users need to test 5–10 configs with the same prompt, without rewriting the pack or creating multiple pack JSON files.
Current architecture mentions sweeps conceptually but lacks:

A syntax/API

Builder integration

Controller integration

Preview & History visibility

3. Goals
A. Global Negative

Implement global negative application in UnifiedPromptResolver

Respect pack JSON per-stage toggles

Ensure global negative is recorded in final job record

Never mutate PromptPack content

B. Config Sweeps

Implement ConfigVariantPlanV2

Enable Pipeline Tab to define sweeps (simple: cfg/steps/sampler toggles)

Builder pipeline expands sweeps into distinct NormalizedJobRecord objects

Store config-signature metadata for History + Learning

C. Preserve PromptPack-only Invariant

No new prompt editing UI

No mutation of PromptPack JSON driven by Pipeline Tab

All sweep behavior originates from configs, not user-entered text

4. Success Criteria

PR-CORE-E is successful when:

Global negative is consistently applied across txt2img/img2img/upscale/adetailer according to JSON flags.

UnifiedPromptResolver outputs fully layered negatives.

Config sweeps produce multiple fully normalized jobs with differing config signatures.

History entries contain config variant metadata.

Learning receives identical prompts but differing configs—ideal for ranking and optimization workflows.

Builder pipeline remains deterministic, pure, and testable.

5. Non-Goals

No extension to PromptPack TXT editing capabilities

No GUI-level prompt authoring

No modification to Queue or Runner

No new executor behavior

No pack JSON mutation except via Pack Editor inside Advanced Prompt Builder

6. System Architecture Alignment
6.1 PromptPack-only

Sweep logic must not modify or derive prompt strings.

6.2 Builder purity

All sweep expansion must happen inside builder pipeline, not controllers and not GUI (per ARCHITECTURE_v2.6.md).

6.3 Learning & reproducibility

Config variant identity must be included in NormalizedJobRecord for scoring/analysis.

7. Detailed Implementation Plan
7.1 Add app_settings.global_negative_prompt to settings model
Files:

src/utils/app_settings.py

src/utils/file_io.py

Add fields:
class AppSettings(BaseModel):
    global_negative_prompt: str = ""
    apply_global_negative_txt2img: bool = True
    apply_global_negative_img2img: bool = True
    apply_global_negative_upscale: bool = True
    apply_global_negative_adetailer: bool = True


Load settings once; controllers must pass these to UnifiedPromptResolver.

7.2 UnifiedPromptResolver: Add global-negative integration
File:

src/pipeline/unified_prompt_resolver.py

Behavior:

Order of negative construction becomes canonical:

final_neg = (
    row_negatives
    + pack_json_negatives
    + (global_negative if stage_allows_it)
    + runtime_negative_override
)

Required additions:

Accept global_negative_prompt + per-stage flags in resolver input

Include "global_negative_applied": True/False in resolved metadata

Write this into final NormalizedJobRecord

Tests:

Global negative applies only if stage flag is true

Multiple layers concatenate in correct order

No mutation of row text

7.3 Implement ConfigVariantPlanV2
New file:

src/pipeline/config_variant_plan_v2.py

Structure:
class ConfigVariant(BaseModel):
    label: str
    overrides: dict[str, Any]
    index: int

class ConfigVariantPlanV2(BaseModel):
    variants: list[ConfigVariant]
    enabled: bool = False


Labels allow GUI & History to show “cfg_low”, “cfg_high”, etc.

7.4 PipelineController Integration
File:

src/controller/pipeline_controller_v2.py

Add:

Build ConfigVariantPlanV2 from GUI sweep controls or default to single variant.

Pass both:

RandomizationPlanV2
ConfigVariantPlanV2


to builder.

7.5 Update JobBuilderV2 to expand sweeps
File:

src/pipeline/job_builder_v2.py

Expand builder loop:

Current:

rows × variants(matrix) × batches


Update to:

rows × config_variants × variants(matrix) × batches


Each combination results in exactly one NormalizedJobRecord.

Add metadata fields:
config_variant_label: str
config_variant_index: int
config_variant_overrides: dict[str, Any]


Included in summary + history.

7.6 UnifiedConfigResolver integration
File:

src/pipeline/unified_config_resolver.py

Add:

Apply config overrides before stage chain assembly:

e.g., override cfg, steps, denoise, model (if allowed), sampler, width/height, pipeline toggles

Ensure overrides do NOT mutate pack JSON; they apply only to merged config copy.

7.7 GUI V2 Minimal Controls
Files:

src/gui/panels_v2/pipeline_panel_v2.py

src/gui/view_models/pipeline_vm_v2.py

Add minimal sweep UI:

Section: “Config Sweep”

Checkbox: Enable Sweep

Table/list: parameter → values list (start with CFG only for v1)

Section: “Use Global Negative?”

Read-only display of global negative text from app settings

A toggle “apply global negative” per run

These settings populate the controller → ConfigVariantPlanV2.

GUI cannot modify prompts or pack JSON.

7.8 History Panel Integration
File:

src/gui/panels_v2/history_panel_v2.py

Add:

Display fields:

Config variant label

Config variant index

Global-negative-applied flag

Overrides summary

7.9 Learning Integration
File:

src/learning/... (whichever module consumes History)

Ensure:

Config variant metadata included in incoming jobs

Learning can compare jobs differing only by config

No changes to existing Learning schema aside from consuming new fields (Learning spec already supports this extension).

8. Allowed / Forbidden Files
Allowed

Controllers (pipeline_controller_v2)

Builder pipeline files (config merger, resolvers, randomizer, job builder)

GUI panels & view models

Settings files

History & Learning integration points

Tests

Forbidden

src/main.py

src/gui/main_window_v2.py

src/gui/theme_v2.py

src/pipeline/executor.py

Runner internals (JobRunnerDriver)

Any PromptPack TXT parsing (unchanged)

9. Test Plan
Unit Tests
Global Negative Tests

test_prompt_resolver_applies_global_negative_txt2img

test_prompt_resolver_respects_per_stage_flags

test_prompt_resolver_global_negative_ordering

Config Sweep Tests

test_builder_expands_config_variants

test_config_overrides_applied_to_stage_chain

test_config_variant_label_propagation

Resolver + Builder Integration Tests

Using angelic/mystical packs:

multiple config variants

verify final prompt stays unchanged

verify config fields differ correctly

GUI Tests

Sweep UI enables/disables correctly

Preview shows correct number of variants

Running/Queue display variant metadata

10. Acceptance Criteria

A run with:

PromptPack “A”

config variants = [cfg5, cfg7, cfg9]

global negative enabled

produces 3× normalized jobs, each with:

identical prompt

differing config fields

correct variant labels

correct negative layering

correct history entries

correct Debug Hub explanation

And:

No PromptPack content is modified

No GUI prompt text fields exist

Queue receives only fully normalized records

Runner executes without additional merging

11. Documentation Updates

Update the following:

ARCHITECTURE_v2.6.md

Add ConfigVariantPlan to builder diagram

Add global-negative path to prompt resolver data flow

PROMPT_PACK_LIFECYCLE_v2.6.md

Add new section “Config Sweeps Overview”

Add note: global negative belongs to app settings, not pack JSON

Roadmap_v2.6.md

Add PR-CORE-E milestone under Phase 2.6 Stabilization

StableNew_Coding_and_Testing_v2.5.md

Add sweep tests and prompt-resolution layering tests

CHANGELOG.md

12. CHANGELOG Entry
## [PR-CORE-E] - 2025-12-08
Global Negative Integration + Config Sweep Support
- Added global-negative prompt integration in UnifiedPromptResolver, controlled via app settings and per-stage pack JSON flags.
- Introduced ConfigVariantPlanV2 for config sweeps.
- Updated JobBuilderV2 to expand rows × config_variants × matrix_variants × batches.
- Updated UnifiedConfigResolver for override application.
- Updated PipelineController to construct and pass ConfigVariantPlanV2.
- Added GUI controls for basic sweep definition and global negative application.
- Updated History and Learning metadata to reflect config variants and global-negative usage.

13. Rollback Plan

Rollback removes:

Global negative integration

ConfigVariantPlan + sweep expansion

GUI sweep controls

All resulting metadata fields in job records and summaries

This disables sweep workflows and forces users to define separate config snapshots manually.

PR-CORE-E COMPLETE.


Here’s a focused Sweep Designer UI spec you can hand to Codex / a designer. I’ll keep it scoped to config sweeps only, and strictly aligned with the PromptPack-only + PR-CORE-E model.

Sweep Designer – UI Spec (Config Sweeps)
1. Purpose & Goals

Primary goal:
Give the user a clean way to say:

“Take this Prompt Pack and run it N times with different configs (cfg, steps, sampler, resolution, stage toggles…) so I can compare which config performs best.”

while never:

editing prompts,

editing PromptPack TXT/JSON,

or violating the PromptPack-only invariant.

Outcomes:

Users can define config variants inside the Pipeline tab.

Those variants become ConfigVariantPlanV2 entries.

Builder expands:
rows × config_variants × matrix_variants × batches → NormalizedJobRecord[].

2. Placement in the UI

Sweep Designer lives in the Pipeline Tab, as a collapsible section under the config/preset selector.

Rough layout:

+-----------------------------------------------------+
| Pipeline Tab                                        |
+-----------------------------------------------------+
| [Prompt Pack Selector      v]                       |
| [Config Preset / Pack JSON v]                       |
|                                                     |
| [Preview Panel Stub / Summary]                      |
|                                                     |
|  Config Sweep  [▾]                                  |
|  ───────────────────────────────────────────        |
|  [ ] Enable Config Sweep                            |
|                                                     |
|  Variant List:                                      |
|   +------------------------------------------------+
|   | Label      | CFG   | Steps | Sampler | ...     |
|   |------------+-------+-------+---------+-------- |
|   | cfg_low    | 4.5   | 20    | DPM++   | ...     |
|   | cfg_mid    | 7.0   | 20    | DPM++   | ...     |
|   | cfg_high   | 10.0  | 20    | DPM++   | ...     |
|   +------------------------------------------------+
|    [+ Add Variant]      [Load from Presets...]      |
|                                                     |
|  Global Negative [x] Apply global negative          |
|   (Shown read-only below, from App Settings)        |
|   "blurry, bad hands, ..."                          |
+-----------------------------------------------------+
| [Run Now] [Add to Queue]                            |
+-----------------------------------------------------+

3. States & Behaviors
3.1 Collapse / Expand

Default: Collapsed section labeled “Config Sweep”.

When expanded, shows:

Enable toggle

Variant list

Controls to add/delete variants

Global Negative toggle + read-only text.

3.2 Enable/Disable Sweep

Checkbox: “Enable Config Sweep”

Unchecked:

Variant list disabled.

Controller builds ConfigVariantPlanV2(enabled=False) with a single implied variant (the base merged config).

Checked:

At least one variant row is required.

Run Preview updates to show “Config variants: N”.

4. Variant List UI
4.1 Columns (First iteration)

Keep this simple and high-impact:

Label (string)

CFG (float)

Steps (int)

Sampler (enum dropdown)

Resolution (paired dropdown or width/height alias)

Stages (optional: toggles for hires/adetailer)

You can extend later, but v1 can focus on:

cfg_scale

steps

sampler_name

width/height

enable_hires / enable_adetailer

4.2 Interactions

Add Variant:

Clicking [+ Add Variant] appends a new row with:

Label: auto-filled (cfg_variant_3 etc.) but editable.

Fields defaulted from:

current merged config OR

last variant row, to keep edits cheap.

Delete Variant:

Inline [x] icon per row.

If all rows deleted while “Enable Sweep” is still checked:

Show inline validation: “At least one variant required when sweep is enabled.”

Disable Run buttons until this is resolved.

Edit Variant:

Edits are local to the variant row; they do not touch the underlying pack config or preset.

4.3 Validation

Label: non-empty, unique within the sweep.

CFG: within allowed numeric range (e.g., 0.0–30.0).

Steps: positive integer, below max (e.g., ≤ 150).

Sampler: must be valid enum value supported by backend.

Resolution: consistent (width × height) – you can reuse existing validation rules.

On invalid fields:

Highlight the cell.

Show inline message (tooltip or small text).

Disable Run and Add to Queue until all sweeps are valid.

5. Data Binding → ConfigVariantPlanV2
5.1 ViewModel Representation

In pipeline_vm_v2 (or equivalent), maintain:

class SweepVariantVM:
    label: str
    cfg_scale: float | None
    steps: int | None
    sampler_name: str | None
    width: int | None
    height: int | None
    enable_hires: bool | None
    enable_adetailer: bool | None

class ConfigSweepState:
    enabled: bool
    variants: list[SweepVariantVM]

5.2 Conversion to ConfigVariantPlanV2

Controller call:

def _build_config_variant_plan(self, sweep_state: ConfigSweepState) -> ConfigVariantPlanV2:
    if not sweep_state.enabled or not sweep_state.variants:
        return ConfigVariantPlanV2(enabled=False, variants=[])

    variants = []
    for idx, vm in enumerate(sweep_state.variants):
        overrides = {}
        if vm.cfg_scale is not None:
            overrides["txt2img.cfg_scale"] = vm.cfg_scale
        if vm.steps is not None:
            overrides["txt2img.steps"] = vm.steps
        if vm.sampler_name:
            overrides["txt2img.sampler_name"] = vm.sampler_name
        if vm.width and vm.height:
            overrides["txt2img.width"] = vm.width
            overrides["txt2img.height"] = vm.height
        if vm.enable_hires is not None:
            overrides["upscale.enabled"] = vm.enable_hires
        if vm.enable_adetailer is not None:
            overrides["adetailer.enabled"] = vm.enable_adetailer

        variants.append(
            ConfigVariant(
                label=vm.label,
                overrides=overrides,
                index=idx,
            )
        )

    return ConfigVariantPlanV2(enabled=True, variants=variants)


These ConfigVariants are passed through to the builder and recorded into each NormalizedJobRecord.

6. Global Negative – UI & Behavior
6.1 Display

In the same “Config Sweep” section, add:

[ ] Apply global negative

Global negative (from App Settings):
"blurry, bad hands, ..."


The text box is read-only.

The string is loaded from app_settings.global_negative_prompt.

The checkbox is a per-run toggle:

When checked, controller passes a flag to builder to include global_negative_prompt.

When unchecked, builder ignores global negative for this run (even if app_settings says otherwise).

6.2 Binding

ViewModel field:

apply_global_negative: bool
global_negative_preview: str  # read-only


Controller passes both into the builder, which forwards to UnifiedPromptResolver.

UnifiedPromptResolver then:

Applies global negative according to:

app settings, pack-level per-stage flags, and

this per-run toggle.

7. Preview & UX Feedback
7.1 Preview Panel Integration

When sweeps are enabled:

Preview summary box shows:

Prompt Pack: SDXL_angelic_warriors_Realistic
Configs: 3 variants (cfg_low, cfg_mid, cfg_high)
Randomization variants: 2 (matrix)
Total jobs: 6 × batch_size
Global negative: ON


If sweeps are disabled:

Configs: 1 (base config)
Randomization variants: 2
Global negative: OFF

7.2 Hover Behavior

Hovering a variant row (cfg_low) updates the preview to show:

The specific cfg/steps/sampler that will be used.

The unchanged prompt text (just to reinforce PromptPack-only).

8. Queue / Running / History UX Hooks

You don’t need full visual design here, just rules:

8.1 Queue Panel

Each queued job row shows:

Pack name

Variant label + index (e.g., cfg_high #2)

Status

Optionally:

[RUNNING] SDXL_angelic_warriors_Realistic – cfg_high (cfg=10, steps=20)

8.2 Running Job Panel

Show:

Variant label

Config snippet (cfg/steps/sampler)

Prompt snippet (same across all variants in the sweep run)

8.3 History Panel

For each job in a sweep:

Display variant label & overrides in the details panel:

Variant: cfg_high

Overrides: cfg=10.0, steps=20, sampler=DPM++ 2M Karras

Show global negative flag (ON/OFF) if relevant.

9. Edge Cases & UX Notes

Sweep enabled but only 1 variant

It’s allowed (e.g., user just wants to turn on global negative).

Preview remains explicit: Configs: 1 variant (cfg_low).

Sweep disabled while variants exist

The variants are ignored for the run but remain in the UI.

If user re-enables, previous variants come back.

Matrix randomization + sweeps

UI messaging:

“Config variants: 3 × Matrix variants: 4 × Batch size: 2 = 24 jobs”

No extra special UX besides the summary.

Mobile / constrained layout

Variant list can become a vertically stacked card layout:

Label as header.

K/V pairs for cfg/steps/sampler.

10. Implementation Phasing (Optional)

If you want to roll this out incrementally:

Phase 1 (MVP):

Sweep Designer supports:

Label, cfg, steps only.

Global negative toggle.

History shows variant label only.

Phase 2:

Add sampler, resolution, stage toggles.

Add “Load from Presets…” button to auto-generate variants from existing config presets.

Phase 3:

Add UX sugar:

quick “Make 3-point sweep around current cfg”

or “Duplicate current variant”.