#CANONICAL
Rewritten GUI Wishlist PR Plan (V2.5 – Updated & Integrated)

#CANONICAL-GUI-WISHLIST

Executive Summary

This roadmap defines all GUI modifications required to bring the StableNew GUI in line with:

The v2.5 architecture

The new JobBuilder / NormalizedJobRecord pipeline

Queue-first execution model

Deterministic preview and payload inspection

Clean UX separation between Preview, Queue, and Running Job areas

Dark-mode–aligned, consistent theming

Proper presentation of execution state across the three pipeline columns

It organizes the work into manageable, atomic PRs grouped by subsystem:
A – Theming, B – Field Validation Cleanup, C – Prompt Pack UX, D – Core Config Polish,
E – Refiner/Hires/ Upscale UX, F – Queue & Run Controls Overhaul, G – Preview UX,
H – Window Management & Layout Fixes, I – File Output & Naming UX, J – Override & Config Control,
K – Seed UX Improvements, and L – Scroll Behavior.

All requested new changes—particularly the removal of legacy queue status labels in Preview, migration of Pause Queue and Auto-run queue into Queue Panel, elimination of Run Controls Panel, and introduction of Send Job—are now incorporated.

PR Groups Overview
Group	Title	Type	Notes
A	Theming & Control Polish	UI only	Fix dark-mode inconsistencies, slider labels, dropdown popups
B	Remove Empty Validation Fields	UI only	Deletes dead validation UI from all panels
C	Prompt Pack Preview Persistence	UX	Make preview pane text selectable, persistent
D	Core Config polish	UI only	Spinboxes, dropdowns, naming consistency
E	Stage Panel UX polish	UI only	Refiner, Hires, Upscale sliders, model selectors
F	Queue & Run Controls Overhaul	Structural UI + minor logic	This is where most of your new requested changes live
G	Preview UX Modernization	UX	Remove leftover status fields, summarize job state clearly
H	Window sizing & layout fixes	UI only	Default width, scrollable columns, consistent card nesting
I	Output path & filename UX	UX	Allow editing, tooltips, token explanation
J	Config Override Controls	UX	Add explicit stage-override checkbox & behavior
K	Seed UX improvements	UX	Fix Randomize button, seed-mode indicators
L	Scroll behavior normalization	UI only	Fix inconsistent scrolling regions
Detailed PR Definitions (Updated with your new changes)

Below is the fully rewritten roadmap, with all changes integrated.

PR-GUI-A — Theming & Control Polish (V2.5)

(Already generated for you as full spec)
Covers:

Light-mode dropdown popups → dark mode

Core Config steps/cfg spinbox theming

Uniform label colors (incl. SDXL Refiner label)

Slider numeric value display for Refiner/Hires/Upscale

Upscale panel dark-mode fixes

Your new changes:

“Queue: (status)” dark-mode requirements → moved to PR-GUI-F1, since the label moves panels.

PR-GUI-B — Remove Empty Validation Fields (All Panels)

Removes dead fields with no logic behind them.

Panels affected:

txt2img

img2img

refiner

hires

upscale

No functional changes.

PR-GUI-C — Prompt Pack Preview Persistence & Selection

Fixes:

Switching into a prompt pack should not wipe the preview

User must be able to select and copy text

Preview area should behave like a proper scrollable text widget

No side-effects on AppState

PR-GUI-D — Core Config Polish

Addresses:

Step/cfg spinboxing

Clearer labeling

Dropdown standardization

Clarify "batch size vs batch runs" (through labels + tooltips only; logic unchanged)

PR-GUI-E — Refiner / Hires Fix / Upscale UX Fixes

Addresses longstanding usability issues:

Refiner toggle should show/hide refiner options

Hires toggle should show/hide hires options

Upscale sliders value visibility

Hires model selector (optional: choose different model)

Numeric indicators for denoise sliders

Upscale final size calculation fix

PR-GUI-F — Queue & Run Controls Overhaul (Major)

This is the category into which almost all of your new changes fall.
It is broken into three sub-PRs for safety, clarity, and atomicity.

PR-GUI-F1 — Queue/Run Controls UI Restructure (No new behavior)

Your requested changes integrated here:

Remove Queue label, Queue Status, No pending jobs from PreviewPanelV2

Remove "Running Job:" and "Status:" from PreviewPanelV2

Keep only the Pause Queue button that actually works

Move that button into Queue Panel row 2

Delete the unused Pause Queue button

Move Auto-run queue checkbox into Queue Panel

Move Queue: (status) label into Queue Panel (row 1 or 2), and apply dark-mode

Remove Run Controls panel entirely (becomes empty after these moves)

This PR does NOT change queue behavior—placement only.

PR-GUI-F2 — Queue Panel Structural Redesign (Framing & Visual Hierarchy)

Adds the structural improvements from wishlist:

Queue panel gains its own frame/card

Columns normalized in width

Add-frame around draft preview & queue for consistent hierarchy

Queue list displays job IDs, variant/batch indices, order number

Jobs in queue appear in selectable list form

Buttons: Move Up, Move Down, Remove, Clear Queue

Still no job-dispatch logic changes.

PR-GUI-F3 — Queue Semantics: Pause/Resume, Auto-run, “Send Job”, Persisted Queue

Your new behavior addition belongs here:

Add “Send Job” button:

If no job running: dispatch top-of-queue job immediately

If job running: mark the next job as “pending delivery”

Ensure Pause Queue properly blocks next dispatch

Auto-run queue semantics formalized

Persist queue state between program restarts

Running-job card created (optional for Phase 1, mandatory Phase 2)

Running-job cancel/return-to-queue behavior

PR-GUI-G — Preview Panel UX Modernization

Works with F1 but focuses on Preview:

Remove all deprecated pipeline status fields

Show only:

Positive prompt

Negative prompt

Model parameters

Variant summary

Randomizer summary

Stage settings chart

Prepare slot for future “learning metadata preview”

Your removals are incorporated here but structurally implemented in F1.

PR-GUI-H — Window Layout Normalization

Fixes:

Window opens too narrow

All three columns must be visible at startup

Each main column has scrollable frame container

All columns use consistent card nesting

- MainWindowV2 now applies default geometry/minimum widths and every column wraps its cards inside a single ScrollableFrame, keeping the three-column dashboard visible and rhythmically spaced on first launch (see src/gui/main_window_v2.py, src/gui/views/pipeline_tab_frame_v2.py).

PR-GUI-I — Output File & Naming UX

Addresses:

Output directory selectable

Filename editable

Hover tooltips explaining tokens ({seed}, {model}, {timestamp}, etc.)

PR-GUI-J — Config Override Checkbox

Implements:

“Override Pipeline Config” toggle at top of middle column

Allows one-off experiments without modifying Prompt Pack configs

Integrates with ConfigMergerV2 semantics

PR-GUI-K — Seed UX Enhancements

Fixes:

Randomize button wired to seed generator

Clarify seed mode behavior

Show active seed mode indicator

Add tooltip describing seed invariants

PR-GUI-L — Scroll Behavior Normalization

Fixes:

Scrolling should activate any hovered section

Clicking inside a widget traps scroll until cursor leaves widget

Preview and Queue lists scroll independently



------------------------------------------------------------------------------------------------------------------
Previous version below (for reference)
Rewritten GUI Wishlist PR Roadmap (V2.5).md

Below is an updated roadmap that:

Keeps your original intent and coverage of all 28 items,

But restructures by risk and dependency, not just visual grouping,

And explicitly anchors anything behavioral on the 204-series architecture.

I’ll keep the names generic so you can map them to final PR numbers (e.g., PR-GUI-211, etc.).

PR-GUI-A – Theming & Control Polish (Low Risk, Visual Only)

Intent

Fix all pure dark-mode / styling / label issues without changing behavior or layout.

Includes

Dark mode gaps:

Steps / CFG spinboxes in Core config.

Dropdown lists (combobox popups) in core, refiner, hires, upscale.

SDXL Refiner label still in light mode.

Slider labels:

Refiner strength shows a numeric percentage.

Hires denoise shows its numeric value.

Upscale sliders show their numeric values.

Ensure upscale fields (steps, denoise, scale, tile size, face restore) all use dark theme.

Files (likely)

gui/theme_v2.py (widget styles only)

gui/panels_v2/core_config_panel_v2.py

gui/panels_v2/refiner_panel_v2.py

gui/panels_v2/hires_panel_v2.py

gui/panels_v2/upscale_panel_v2.py

Guardrails

No layout changes.

No logic changes beyond “display text/value”.

PR-GUI-B – Stage Card Behavior (Refiner / Hires / ADetailer / Upscale)

Intent

Make stage cards behave intuitively, but still use the existing ConfigMergerV2 + JobBuilderV2 semantics.

Includes

Enable Refiner checkbox show/hide refiner options.

Enable Hires Fix checkbox show/hide hires options.

Hires Fix model selector:

Defaults to base model.

If user chooses a different model, this populates the hires override fields (ConfigMergerV2 interprets this; no ad-hoc logic).

ADetailer defaults to enabled for SDXL pipelines.

Upscale final size calculation fixed (no more 0x0).

Uses known base dimensions from pipeline config (JobBuilder/NormalizedJobRecord) where possible.

Files

Relevant *_panel_v2.py files for refiner, hires, adetailer, upscale.

Possibly small, safe adjustments in ConfigMergerV2 to ensure hires model override semantics are explicit (if not already).

Guardrails

Stage “enable” flags and model/scale/denoise values must be passed through the existing pipeline merge path; no side channels.

PR-GUI-C – Prompt Packs, Overrides, and Restore Last Run (Anchored on 204A/B/C)

Intent

Solve three closely-related, config-oriented UX problems:

Prompt pack preview persistence (so you can click in and copy text).

Per-run overrides without mutating the pack.

Restoring the last run in a principled way.

Includes

Prompt pack preview:

Clicking into a pack preview doesn’t collapse it.

Text is selectable and copyable.

Config override checkbox (middle column):

“Use current stage config as overrides for this run.”

On = AppState builds a StageOverridesBundle matching the ConfigMergerV2 override schema.

JobBuilderV2 always receives: (pack_config, overrides_bundle) and does not mutate the pack.

Restore Last Run:

Add a small last_run_store_v2 utility that persists a snapshot derived from NormalizedJobRecord.to_queue_snapshot (or equivalent).

On startup: AppController loads last run and hydrates app_state.

Restore Last Run button: copies stored config into the current draft if no newer job has run.

Files

gui/panels_v2/prompt_pack_panel_v2.py

gui/views/pipeline_tab_frame_v2.py (override checkbox, restore button wiring)

gui/app_state_v2.py (override bundle + last-run state)

utils/last_run_store_v2.py (new)

Minor integration in app_controller.py

Guardrails

Overrides must be expressed only via ConfigMergerV2 types; no new merging logic in GUI.

Last-run snapshot must be derived from NormalizedJobRecord; do not invent another snapshot format.

PR-GUI-D – Layout & Column Scroll Normalization

Intent

Fix the structural layout and scrolling issues without touching queue semantics or run controls.

Includes

On first open, main window is wide enough to show all three columns (no clipped right panel).

Each main column:

Has a single scrollable frame.

Cards live inside that frame.

Mouse wheel scrolls the column under the cursor, not random controls.

Remove obsolete empty validation fields from cards (pure UI no-ops).

Files

gui/main_window_v2.py or top-level geometry helper.

gui/views/pipeline_tab_frame_v2.py

gui/panels_v2/* where validation fields are removed.

Guardrails

Do not modify run controls behavior here.

Testable via GUI tests that assert columns are scrollable and validation widgets are gone.

PR-GUI-E – Core Config Semantics: Batch, Seed, Output & Filename Tokens

Intent

Tighten semantics and clarity on the “Core” areas that heavily map onto JobBuilderV2 and NormalizedJobRecord.

Includes

Clear descriptions and tooltips for:

Batch Size = images per prompt.

Batch Runs = repeated runs of same config (ties directly to BatchSettings in JobBuilderV2).

Seed mode + Randomize button:

UI reflects and manipulates RandomizationPlanV2 or the seeding strategy in JobBuilder.

“Randomize” generates a new base seed for the plan, not some separate hidden seed.

Output Dir:

Editable; always shows a concrete path.

Stored in OutputSettings / NormalizedJobRecord.

Filename:

Editable template string.

Hover tooltip lists supported tokens (e.g., {prompt}, {seed}, {model}, {idx}, etc.).

Backend uses a small output_naming_v2 helper to apply tokens consistently.

Files

gui/panels_v2/core_config_panel_v2.py (UI and tooltips).

gui/app_state_v2.py (seed mode, base seed, output settings).

pipeline/job_models_v2.py (if we need to clarify/rename OutputSettings fields).

pipeline/output_naming_v2.py (new helper for token resolution).

Guardrails

All changes must be consistent with JobBuilderV2’s existing batch + seed logic.

No new “seed mode” concept in GUI that the backend doesn’t know about.

PR-GUI-F1 – Queue & Run Controls (Phase 1: UI Restructure Only)

Intent

Reorganize the run controls and queue panel visually without changing core queue behavior or persistence yet.

Includes

Move Run Controls below Preview and into the same card/frame.

Introduce the queue-first visual model:

Primary button: “Add to Queue”.

“Clear Draft” remains, but grouped under preview.

Mode toggle (Direct vs Queue) is visually de-emphasized or relabeled (e.g., “Execution Mode – advanced”), but not yet removed from the underlying state or tests.

Queue card:

clearly separated from “Running Job” area,

at minimum, shows order number, prompt summary, and key config summary (using JobUiSummary from 204D).

Files

gui/panels_v2/run_controls_panel_v2.py

gui/panels_v2/preview_panel_v2.py

gui/panels_v2/queue_panel_v2.py

gui/views/pipeline_tab_frame_v2.py for layout changes.

Guardrails

No new queue persistence, no reordering, no behavior change to JobService.

All pipeline/controller tests added in 204C–E must still pass unchanged.

PR-GUI-F2 – Queue Behavior (Phase 2: Reordering, Clear Queue, Selection)

Intent

Once the basic UI is queue-first and stable, add the interactive queue operations that users expect.

Includes

Queue list selection.

Up/down arrows to move a selected job in queue (change order).

“Clear Queue” button to remove all queued jobs.

Remove job from queue (trash icon).

“Running Job” card:

Distinct from queue,

Shows which queue entry is currently running (by order/index).

Files

gui/panels_v2/queue_panel_v2.py (selection + reordering UI).

gui/app_state_v2.py (queue ordering state, if not entirely in JobService).

controller/job_service.py or pipeline/job_queue_v2.py (small, explicit APIs: move_up, move_down, remove, clear).

Guardrails

This PR must anchor on existing JobService/queue models.

All queue operations must operate on JobSpec/NormalizedJobRecord snapshots, not partial random GUI objects.

No persistence yet; if the app restarts, the queue resets (Phase 3 solves this).

PR-GUI-F3 – Queue Persistence & Auto-Run (Phase 3, High-Risk, Depends on 204E)

Intent

Implement the “dream queue” behavior:

Persistent queue and resumption across restarts.

Auto-run queue option.

Pause/Resume toggle and cancel/return-to-queue behavior.

Includes

Queue persistence:

queue_store_v2 module that saves a serializable view of Queued JobSpecs.

On startup, JobService loads this and repopulates queue UI.

Auto-run toggle:

When enabled, queue auto-starts when jobs appear.

When disabled, queue waits for explicit “Run Queue” action.

Running job controls:

Pause/Resume (single toggle).

Cancel (drop job completely).

Cancel-and-return-to-queue (job goes back to bottom of queue).

Progress indicator and ETA (at least stubbed based on known steps).

Files

pipeline/job_queue_v2.py / controller/job_service.py (persistence + auto-run).

services/queue_store_v2.py (new).

gui/panels_v2/queue_panel_v2.py / run_controls_panel_v2.py (buttons, toggles, progress display).

Possibly minimal updates in pipeline/executor or runner for progress reporting (if not already available).

Guardrails

Must be built on top of the 204E end-to-end + queue parity tests; those tests guard that JobService/runner calls remain correct.

Persistence format must be NormalizedJobRecord / JobSpec-based; nothing ad hoc.

PR-GUI-G – Preview & Logging UX Cleanup

Intent

Final UX polish for the Pipeline tab:

Preview shows what really matters about each job.

Logging is easy to find.

Legacy top toolbar cruft is removed.

Includes

Details button:

Defaults to showing terminal/logging pane.

Remove dead top toolbar buttons (Run, Stop, Preview, Settings, Refresh, Help) that are V1 leftovers.

Preview enhancements:

Show +prompt, -prompt,

A mini “settings summary” (model, sampler, steps, CFG, refiner/hires/upscale presence),

Randomizer summary space (e.g., “2 models × 3 CFG values × per-variant seed”),

All driven from JobUiSummary derived from NormalizedJobRecord (no new summary logic).

Files

gui/main_window_v2.py (toolbar removal, details default behavior).

gui/panels_v2/preview_panel_v2.py (rendering from JobUiSummary).

gui/panels_v2/log_panel_v2.py or equivalent logging view.

Guardrails

Preview/queue summaries must use the same summary helper; no divergence between what preview shows and what queue shows.

Coverage Check vs Wishlist

The rewritten roadmap still covers all of your original 28 items, but in a more structured way:

Theming / Dark Mode / sliders → PR-GUI-A

Stage card toggles + hires model + upscale size → PR-GUI-B

Prompt preview, config override, restore last run → PR-GUI-C

Window width, column scroll, validation fields → PR-GUI-D

Batch vs batch runs, seed mode + Randomize, output dir/filename → PR-GUI-E

Run controls + queue UX (visual first, then behavior, then persistence) → PR-GUI-F1/F2/F3

Details default, preview richness, top toolbar cleanup → PR-GUI-G