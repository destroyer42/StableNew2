PR-Roadmap – GUI Wishlist & Docs Consolidation (V2.5).md

0. Context / Current Baseline

From the latest snapshot and docs:

The run path is now GUI → AppController → PipelineController → JobBuilderV2/ConfigMergerV2 → JobService/Queue → PipelineRunner, with JobSpecs/NormalizedJobRecord as the normalized contract.

PR-204A–D already gave us:

ConfigMergerV2 (pure pipeline merge),

JobBuilderV2 + NormalizedJobRecord,

PipelineController.start_pipeline_v2,

Preview/Queue panels that can display normalized jobs.

The roadmap below assumes that 204A–E are the canonical foundation for pipeline/queue behavior.

Part 1 – GUI Wishlist → Architecture Impacts & PR Plan
1.1 Themes from the GUI Wishlist

Your 28-item Pipeline tab list naturally clusters into:

Visual polish & theming

Dark-mode gaps (steps/CFG spinboxes, dropdown lists, refiner/hires/upscale controls).

Light-mode labels like “SDXL Refiner”.

Sliders without numeric labels (refiner %, denoise, upscale sliders).

Stage card behavior & clarity

Enable Refiner / Hires Fix should hide/show their sub-options.

Hires Fix needs its own model selector.

ADetailer should default to enabled and integrate cleanly.

Upscale final size always showing 0x0.

Prompt packs, overrides, and restore

Prompt pack preview doesn’t persist when clicked into.

Need a config override checkbox in the middle column to do one-off experiments without mutating pack configs.

“Restore last run” expected to auto-load on startup and restore previous job config when pressed.

Run controls, queue, and persistence

Run controls confusing: “Run / Run Now / Mode (Direct vs Queue)” etc.

Need queue-centric model (“Add to queue”, auto-run toggle, pause/resume, reorder queue, clear queue).

Queue & preview should be framed, more informative, and persist across exits, resuming jobs when possible.

All states (queue, last run, maybe randomizer) should persist between exits.

Misc UX & layout

Remove dead validation fields + legacy top toolbar buttons.

Window opens too narrow; scrollbars feel wrong (scroll by column, not by widget).

Output dir & filename must be editable, and filename needs token help text.

Randomize button on seed does nothing; seed mode behavior unclear.

“Batch size” vs “Batch runs” unclear.

Details button should default to log terminal view.

1.2 Architecture / Pipeline Changes Needed

Most wishlist items are GUI-only, but a few require or benefit from underlying architecture/pipeline changes:

Config Override checkbox + prompt packs (item 11)

Needs to drive ConfigMergerV2 instead of the old “pack mutates global config” pattern.

Architecture change: treat prompt pack config as the base config, and middle panel as an override bundle passed into ConfigMergerV2.

Impacted areas:

app_state_v2 – store “override enabled” flag and override struct.

ConfigMergerV2 – already supports stage overrides; we just need the GUI to populate those structures correctly.

JobBuilderV2 – should always receive base_config + override_bundle.

Restore last run + auto-populate on startup (item 10)

Requires a canonical “last run snapshot” store, likely tied to NormalizedJobRecord:

Write last-completed NormalizedJobRecord (or its pipeline config snapshot) to disk.

On startup, read that snapshot and hydrate app_state.

Architecture change:

A small persistence utility (e.g., last_run_store_v2.py) in src/utils or src/services.

AppController startup hook to load last run and push into app_state_v2.

“Restore Last Run” button to copy those values over the current job draft.

Queue-centric execution, persistence, and re-ordering (item 25)

You’ve already normalized jobs with JobBuilderV2 + NormalizedJobRecord; now the queue needs:

A persistent queue store (e.g., JSON file or sqlite) for queued jobs.

A clear separation between “current running job” vs “queued jobs”.

Methods for reordering jobs and updating queue snapshots.

Architecture change:

Extend JobService/JobQueueV2 to:

Load queue at startup → repopulate UI queue view with NormalizedJobRecords.

Save queue on changes.

Expose reordering API (move up/down, clear queue, remove one).

SingleNodeJobRunner must resume the existing queue after restart if jobs are still pending.

Seed modes and randomization UI (items 9, 13, 24)

Seed modes are already understood at the JobBuilder/Randomizer level (via RandomizationPlanV2, seed modes, etc.), but:

Seed controls in core config and randomizer must share a consistent model.

“Randomize” button should either:

Generate a new base seed (and update randomization plan / run_config accordingly), or

Switch to “per-variant” mode for the next run.

Architecture change:

No deep pipeline changes; just ensure app_state_v2 + RandomizerPlan + JobBuilderV2 interpret seed mode consistently.

Output dir / filename editing & tokens (items 6, 7)

At the pipeline level, filename tokens (e.g. {prompt}, {seed}, {model}, etc.) must be:

Parsed and applied consistently in the pipeline output path builder.

Architecture change:

Clarify the output settings fields on NormalizedJobRecord / BatchSettings / OutputSettings (already in PR-204B).

Add a small OutputNamingSpec doc or constants that define token names and how they’re applied in the executor/runner.

Most other items (dark mode, scrollbars, hiding/showing options, details panel default) are GUI-only and rely on:

theme_v2.py tokens,

pipeline_tab_frame_v2.py layout,

*_panel_v2.py card and control logic.

1.3 GUI Wishlist PR Roadmap

Below is a set of Phase-1 GUI PRs covering all wishlist items. The idea is to keep each PR small enough for Codex, but coherent.

PR-GUI-201 – Pipeline Tab Dark Mode & Widget Polishing

Scope

Fix dark mode gaps:

Core config steps/CFG spinboxes (item 3).

Dropdown lists for core config + refiner/hires/upscale (items 4, 21).

SDXL Refiner label still in light mode (item 14).

Add numeric labels to sliders:

Refiner strength percent (item 16).

Hires denoise slider (item 18).

Upscale sliders’ numeric values (item 21).

Key Files

src/gui/theme_v2.py – ensure all widget types (Spinbox, Combobox, Scale) have dark variants.

src/gui/panels_v2/core_config_panel_v2.py (or equivalent) – spinbox & dropdown styling.

src/gui/panels_v2/refiner_panel_v2.py, hires_panel_v2.py, upscale_panel_v2.py – slider labels and styling.

Any shared widget helpers (e.g., “themed_spinbox factory”).

Wishlist Coverage

Items: 3, 4, 14, 16, 18, 21.

PR-GUI-202 – Stage Card Behavior (Refiner / Hires / ADetailer / Upscale)

Scope

Make “Enable Refiner” hide/show refiner options (item 15).

Make “Enable Hires Fix” hide/show hires fix options (item 17).

Add Hires Fix model selector that defaults to base model but can be overridden (item 19).

ADetailer defaults to enabled, with consistent stage card behavior (item 5).

Fix upscale final size calculation (step/scale/tile size → non-0x0) (item 22).

Key Files

src/gui/panels_v2/refiner_panel_v2.py – gating visibility of controls by enable checkbox.

src/gui/panels_v2/hires_panel_v2.py – show/hide + model combobox, “use base model” default.

src/gui/panels_v2/adetailer_panel_v2.py – default enable = True, consistent layout.

src/gui/panels_v2/upscale_panel_v2.py – final size computation and display.

ConfigMergerV2 / JobBuilderV2 – only if needed to interpret hires model overrides cleanly.

Architecture Note

For hires model selector, ensure ConfigMergerV2 and JobBuilderV2 understand when a hires model is “override” vs “use base model”, using the existing override flags.

Wishlist Coverage

Items: 5, 15, 17, 19, 22.

PR-GUI-203 – Prompt Packs, Overrides, and Restore Last Run

Scope

Make prompt pack preview persist when clicking into it:

Allow text highlight/copy without collapsing (item 2).

Add config override checkbox in middle panel:

“Use current stage config to override pack config for this run only” (item 11).

Wire this to ConfigMergerV2: pack config as base, override bundle from middle card.

Implement “Restore Last Run” behavior:

On startup, load last run snapshot and populate UI.

“Restore Last Run” button restores those configs into current draft if no new job has been run (item 10).

Key Files

src/gui/panels_v2/prompt_pack_panel_v2.py – preview persistence behavior.

src/gui/views/pipeline_tab_frame_v2.py – add override checkbox + layout.

src/gui/app_state_v2.py – store “override enabled” flag + override bundle.

src/pipeline/config_merger_v2.py – ensure it can accept override bundle produced by UI (may already be fine).

src/services/last_run_store_v2.py (new) – read/write last run snapshot.

src/controller/app_controller.py – startup hook to load last run; handler for “Restore Last Run” button.

Architecture Note

Last run snapshot should be based on NormalizedJobRecord (or at least its config snapshot) so it’s aligned with the pipeline run path.

Wishlist Coverage

Items: 2, 10, 11.

PR-GUI-204 – Layout & Scroll Normalization

Scope

When window first opens, it should be wide enough to show all three columns (item 12).

Move Run Controls below Preview section; wrap Preview + run controls in a consistent card/frame (items 23, 25 sub-points about visual grouping).

Standardize scroll behavior:

Each main column has a single scrollable frame containing its cards.

Mouse wheel scrolls the column under the cursor (item 20).

Remove empty validation fields from every card (they are dead UI) (item 1).

Key Files

src/gui/main_window_v2.py (only if allowed for geometry; otherwise via pipeline tab frame).

src/gui/views/pipeline_tab_frame_v2.py – restructure three columns as “scrollable section” + cards.

src/gui/panels_v2/* – remove no-op validation fields; ensure they don’t rely on them.

Scroll helper utilities, if any, for column-level bind and wheel behavior.

Wishlist Coverage

Items: 1, 12, 20, 23, 28 (column/frame standardization).

PR-GUI-205 – Core Config Clarity (Batch, Seed, Output Dir, Filename)

Scope

Clarify Batch size vs Batch runs:

Add concise labels/tooltip explaining “batch size = images per prompt; batch runs = repeats of same config” (item 8).

Align with BatchSettings in JobBuilderV2 so semantics match tests.

Implement seed mode explanation and hook up Randomize button:

Tooltip and label for seed mode (e.g., fixed vs per-variant).

Randomize button generates a new base seed and updates appropriate state (item 13; ties to item 9).

Make Output Dir editable and always show a real path (item 6).

Make Filename editable and document tokens via hover text (item 7).

Key Files

src/gui/panels_v2/core_config_panel_v2.py – batch size/runs controls, seed mode, randomize button.

src/gui/app_state_v2.py – seed mode / base seed state, output settings.

src/pipeline/job_models_v2.py – ensure BatchSettings and OutputSettings fields align semantics with the labels.

src/pipeline/output_naming.py (new) – central place for token definitions and resolution; referenced by executor/pipeline.

Architecture Note

Seed mode and randomize button must stay consistent with RandomizationPlanV2 and JobBuilderV2 seed handling; GUI should not bypass that.

Wishlist Coverage

Items: 6, 7, 8, 9, 13, 24 (seed behavior clarification, partial preview info; full preview expansion comes with 204D+).

PR-GUI-206 – Queue & Run Controls Re-Design (Queue-first Model)

Scope

Simplify run controls to queue-centric behavior:

“Add to Queue” – adds current draft/variants to queue (item 25).

Remove “Mode (Direct vs Queue)” from the UI; run mode becomes implementation detail (queue only) (item 25).

Add “Auto-run Queue” checkbox: when enabled, queue auto-runs as soon as jobs appear (item 25).

Combine Pause/Resume into a single toggle button whose label reflects state (item 25).

Queue UX:

Queue list is selectable; up/down arrows to reorder (reassign order numbers) (item 25).

“Clear Queue” button removes all queued jobs (item 25).

“Running Job” card separated from queue:

shows progress bar, timer, ETA,

pause/resume, cancel, “cancel and return to queue” (item 25).

Persist queue between program exits:

Save queue snapshot and running job (if any).

On restart, rehydrate queue and mark if a job needs resume or restart (item 25; and “all states persist” line).

Key Files

src/gui/panels_v2/preview_panel_v2.py – preview addition logic, “Clear Draft”.

src/gui/panels_v2/queue_panel_v2.py – queue list, selection, reorder controls, clear queue.

src/gui/panels_v2/run_controls_panel_v2.py – buttons, auto-run toggle, pause/resume.

src/gui/app_state_v2.py – queue state + running job state.

src/pipeline/job_service_v2.py / job_queue_v2.py – persistence, reorder support, auto-runner loop.

src/services/queue_store_v2.py (new) – serializing queue and running job.

Architecture Note

This PR aligns GUI behavior with the PR-204 job model:

Queue entries should be NormalizedJobRecord / JobSpecV2, and queue operations should not bypass the normalized job path.

“Auto-run queue” should call into JobService rather than direct runner calls.

Wishlist Coverage

Most of item 25 (run controls simplification, queue behavior, pause/resume, clear queue, persistence).

Also supports item 25’s “all states should persist” as a queue-state exemplar.

PR-GUI-207 – Preview & Logging UX

Scope

Make Details default to terminal logging view (item 26).

Remove legacy top toolbar buttons that no longer do anything (Run/Stop/Preview/Settings/Refresh/Help at very top) (item 27).

Enhance preview to show:

Full positive prompt (or truncated + tooltip),

Negative prompt,

Key settings used (model, sampler, steps, CFG, refiner/hires/upscale summary),

Seed mode/seed,

Placeholder space for randomizer injection summary (item 24).

Key Files

src/gui/main_window_v2.py – remove legacy toolbar, wire Details default.

src/gui/panels_v2/preview_panel_v2.py – use JobUiSummary to present prompts and settings.

src/gui/panels_v2/log_panel_v2.py or equivalent – set default “tab” to logs.

Architecture Note

Leverage existing JobUiSummary from 204D; no new pipeline logic required, just richer UI mapping.

Wishlist Coverage

Items: 24, 26, 27; also final polish for queue/preview clarifications.