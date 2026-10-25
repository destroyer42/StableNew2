# GUI Ownership Map v2.6

**Status:** Canonical active reference  
**Authority:** Subsystem reference subordinate to `AGENTS.md` and architecture
**Enforced by:** `AGENTS.md` and architecture tests

---

## 1. Purpose

This document answers one question for every GUI file decision:

> _Where does this code go?_

There are two active GUI source directories:

| Directory | Role |
|---|---|
| `src/gui/` | **Active Tk runtime** — the canonical GUI host layer |
| `src/gui_v2/` | **Adapter scaffolding** — toolkit-agnostic adapters and validation helpers |

---

## 2. `src/gui/` — Active Tk Runtime

### Canonical status

`src/gui/` is the canonical GUI host layer for StableNew v2.6.  
All new Tk widgets, panels, dialogs, and views go here.

### Contents

| Sub-path | Responsibility |
|---|---|
| `main_window.py`, `main_window_v2.py` | Top-level Tk window setup; `ENTRYPOINT_GUI_CLASS` |
| `app_layout_v2.py`, `layout_v2.py` | Frame layout and zone routing |
| `app_state_v2.py` | Runtime draft state (`AppStateV2`) — owned by GUI layer |
| `controllers/` | Tk-side controller wrappers (learning, pipeline, etc.) |
| `views/` | Tab frames and panel renders; render + event wiring only |
| `view_contracts/` | Toolkit-agnostic interaction contracts (no Tk imports) |
| `view_contracts/task_navigation_contract.py`, `widgets/task_navigation_bar_v2.py` | Task-first navigation (see below) |
| `panels_v2/` | Named panel composites |
| `stage_cards_v2/` | Stage card widgets |
| `dialogs/` | Modal and non-modal dialogs |
| `widgets/` | Reusable Tk widget helpers |
| `models/` | GUI-local presentation models |
| `utils/` | GUI utility helpers (threading, event dispatching) |
| `ui_tokens.py` | Semantic style source-of-truth for all GUI hosts |
| `theme.py`, `theme_v2.py`, `design_system_v2.py` | Visual styling |

### Rules

1. **New Tk code goes in `src/gui/`** — no exceptions without a dedicated approved PR.
2. `view_contracts/` may NOT import Tk types — contracts are toolkit-agnostic by design.
3. `views/` performs render and event wiring only; non-render logic belongs in controllers or adapters.
4. `app_state_v2.py` is the one place runtime draft state lives; do not invent shadow state in sub-panels.
5. `ui_tokens.py` is the single style source-of-truth; do not hardcode colours or fonts in panels.
6. Controllers in `controllers/` orchestrate; they do not own prompt construction or job submission logic.
7. Controllers must not mutate Tk widgets directly. GUI-visible operator logs, queue/history/preview surfaces, and status indicators must flow through `AppStateV2` plus GUI-owned projection code.
8. Hot runtime surfaces in the pipeline shell are owned by `PipelineTabFrameV2`; child panels may render standalone, but when mounted in the pipeline shell they must not independently subscribe to hot runtime state.
9. Hidden or unmapped hot surfaces must defer expensive reconciliation until visible again, and filesystem/artifact lookup work must run through background query services with latest-request-wins semantics rather than on the Tk thread.

### Pipeline composer (PR-GUI-UX-530)
The Pipeline sidebar presents the four canonical stage flags as a task-oriented composer: **Generate** (txt2img), **Improve Result (optional)** (ADetailer, upscale) and a collapsed **Advanced and legacy stages** section holding the img2img flag. Normal Create no longer offers a prominent img2img switch; editing an existing image starts from **Edit or Reprocess Existing Image**, which only selects the Review tab (it changes no settings and queues nothing). A loaded configuration with img2img on stays on: the flag is the same `stage_states` variable, the collapsed header reads "img2img ON", the center column still shows its card (labelled legacy), and only the checkbox in that section turns it off. Refiner and Hires fix remain txt2img-card options inside one collapsed disclosure whose header names which are ON. `view_contracts/pipeline_composer_contract.py` owns the grouping and wording only; stage enablement, compilation, Preview and queue admission are unchanged.

### Task navigation (PR-GUI-410)

The nine workspaces stay nine tabs of the one `MainWindowV2.center_notebook`; `_tab_registry` and the `*_tab` attributes remain the tab-identity authority and the notebook the selection authority. `view_contracts/task_navigation_contract.py` maps the stable tab ids to presentation groups only (Create: prompt, pipeline; Edit: review, photo_optimize; Motion: video_workflow, svd, movie_clips; Learn: learning; Advanced: character_training, shown as HOLD). A group is not a tab, job or queue authority, and Job History stays inside Pipeline. `widgets/task_navigation_bar_v2.py` is the single visible navigation surface: it calls `MainWindowV2.select_tab` and mirrors the notebook through `<<NotebookTabChanged>>` without calling back, so controller handoffs that call `center_notebook.select(frame)` keep working and update the highlight.

The notebook's own tab strip is hidden only after the bar is built (`hide_notebook_tab_strip`); if the bar cannot be built, or the theme refuses the empty tab layout, the native strip stays (documented fallback), and Ctrl+Tab / Ctrl+PageUp/PageDown cycle the notebook either way. `tabs.selected_tab_id` is the persisted selection; the historic numeric `tabs.selected_index` is still written for older builds and is read only when no valid id is stored, translated through `LEGACY_TAB_ORDER` (the notebook creation order, which must not be reordered). The stored tab is restored after the panels attach, because `LayoutManagerV2.attach_panels` raises Pipeline. A tab that fails to build shows a placeholder and is listed by `MainWindowV2.tab_failures()`; a tab that cannot be added to the notebook is not registered and its navigation button is disabled.

### Pipeline settings sources (PR-GUI-UX-500, PR-GUI-UX-520)

The Pipeline sidebar keeps these things apart, and `view_contracts/config_source_contract.py` owns their wording and the small decisions behind it (no Tk, no persistence): **PromptPack Settings** (the `preset_data` saved inside a PromptPack file), a **Saved Pack List** (a named group of PromptPacks that only filters the pack list; read from `state/custom_pack_lists.json`, and no in-app action creates one), the **working stage settings** with any unsaved **Current Job Overrides** (the "Working Settings" card), the **Startup Defaults** (the operator's saved starting configuration, restored once at startup and named as the source until the settings are edited), and the **Application Defaults** in Engine Settings (the default output folder; `image_format` and `filename_pattern` are not application-wide because the image pipeline does not consume them). The legacy named Generation Presets and saved recipes are retired: there is no preset list, dropdown or recipe summary, and "Preset" no longer names any Pipeline concept (the resolution dropdown is the "Size shortcut"; the recommended values of a model are a **profile**). `settings_actions_presenter.py` owns when a load needs a confirmation (the working settings differ from the last loaded or saved state), that applying to packs always confirms, and the non-modal inline status that follows; the controller callbacks do the storage. The source label states what the working settings were last loaded from; later stage edits are tracked only as the unsaved-change check. "Save Current Settings as Startup Defaults" calls `AppController.on_save_startup_defaults` and shows the controller's own success or failure text verbatim. The sidebar's Output Settings card is saved with pack settings and does not change the jobs in the current Preview. The Preview panel's read-only Effective Settings is described in `PROMPTPACKS_AND_PROMPTING.md` section 9; it also lists the working model, the selected profile and the override rule (marked as not part of the compiled jobs) and warns "Preview may be out of date" when stage flags, the override choice, the model or the profile changed after the packs were added to the draft (`draft_staleness_notices`).

**Generation profile strip (PR-IMG-PROFILE-630).** Directly under the Model row, `GenerationProfileStrip` (`src/gui/generation_profile_strip.py`) shows a Profile combobox (No profile, Research, Learning, Custom; a favorite is starred) and one status line. A "Details" toggle reveals Restore selected profile, Save as Custom, Update Custom, Favorite for this model and the per-setting evidence. The strip renders `src/gui_v2/generation_profile_projection.py` and calls `AppController.generation_profiles` (`GenerationProfileController`, `src/controller/generation_profile_controller.py`); it holds no profile logic and no persistence. Picking a checkpoint in the Model combobox (`<<ComboboxSelected>>`, not the value trace, so restores and programmatic loads never re-apply) applies that model's preferred profile through `BaseGenerationPanelV2.apply_profile_values`, which sets only the named controls. Nothing here queues, dispatches or rewrites a PromptPack, a draft entry or a Preview record.

The Pipeline preview thumbnail shows a saved image of the previewed job (the last of the previewed jobs) or says why there is none: no job, no image saved yet, or hidden by the content-visibility setting. Ticking "Show media" never generates an image.

### Controller presentation-state seam (GUI-SEAM-700)

`AppStateV2` carries the toolkit-neutral, ephemeral projection controllers need for Pipeline stage enablement
(`get_pipeline_stage_flags`, `set_pipeline_stage_enabled`) and the retained legacy prompt/upscale readers
(`get/set_pipeline_prompt_text`, `get/set_pipeline_upscale_params`). The projection is not a dataclass field, is never
persisted and is never execution authority. `PipelineTabFrame` owns the Tk variables: it publishes them into `AppStateV2` and
projects subscribed `pipeline_stage_enabled` changes back onto them. `AppController` neither reads nor writes Pipeline Tk
variables.

UI-thread delivery is the `UiDispatcher` protocol (`src/controller/ports/ui_dispatcher.py`: `schedule`, `invoke_later`,
`run_on_ui_thread`). Tk implements it with `TkInvoker` (`src/gui/gui_invoker.py`; `GuiInvoker` is a compatibility alias) and
`TkUiDispatcher` (`src/gui/ui_dispatcher.py`, which keeps `invoke`). `AppStateV2` depends on the protocol only. Composition
ownership is unchanged: `src/app_factory.py` stays the Tk composition path and `MainWindowV2` still creates its own invoker.

### Shared media inspection

`view_contracts/media_inspector_contract.py` owns ephemeral visibility, eligibility, selection revisions, zoom and dock state.
`widgets/media_inspector.py` owns Tk renderers and non-modal detached windows. `view_contracts/media_image_decode.py` bounds
image work; the existing keyed `EditWorkRunner`, `BackgroundTaskCoordinator`, `ThreadRegistry` and `TkUiDispatcher` own work
and delivery. Video remains `VideoPreviewWidget` / `VideoPreviewSession` / `prepare_review_preview`, with one serial work key
across image and video transitions. Old renderers stop before replacement; widgets are recreated, never reparented.

Adoption: Pipeline Preview, Job History including Browse All, Review, Photo Optimize's independent Original and Candidate,
Learning result review and its still comparisons, discovered/staged selected previews, Video Workflow Recent Outputs and SVD
recent recorded media. Hosts retain selection, metadata, editing, ratings and handoffs. Refresh of the same selection preserves
local Show and zoom; a new selection resets the inspector to shown, under the host's existing outer visibility default
(Pipeline and History start hidden). Hide, content-policy denial, tab unmap and destruction cancel/release rendering; a hidden
tab also suspends its detached inspector. Application content visibility has precedence over local Show.

Retained specialized surfaces: Review's verified ADetailer comparison composite (closed when the primary media is hidden),
mask/outpaint and Smart Review canvases (editing coordinates), Learning's frozen cell/contact-sheet grid (batch evidence layout
with its existing bounded thumbnail cache; cell selection opens the shared result inspector), and the video experiment window
(`VideoReviewSession` and its synchronized `ComparisonClock`, not independent looping players). Movie Clips is a file-list and
assembly workspace with no inline viewer. Static icons and LoRA catalog illustrations are not selected job artifacts; the latter
retain their bounded paged model browser. These exceptions do not add new preview surfaces.

---

### Learning guided workflow (PR-LEARN-UX-590)

`LearningTabFrame` presents Designed Experiments as Design, Preview, Run, Compare, Rate. `views/learning_workflow_bar.py` (`LearningWorkflowBar`) renders the step buttons, status and the single primary action; `views/learning_preview_card.py` (`LearningPreviewCard`) renders the frozen Preview summary. Both render pure projections from `src/learning/` (`guided_workflow`, `preview_summary`, `recommendation_summary`, `design_estimate`) and hold no lifecycle, persistence or execution logic. The viewed step is tab-local UI state; the tab swaps pane visibility per step and every primary action routes to an existing, already-gated handler (`request_run`, `_on_build_preview`, `LearningReviewPanel.save_and_next`). No widget here reaches `PipelineRunner`, a backend or a second queue. `LearningController` stays the coordinator; new view logic belongs in these modules, not in the controller.

## 3. `src/gui_v2/` — Adapter Scaffolding

### Canonical status

`src/gui_v2/` contains **toolkit-agnostic adapters and validation helpers**.  
It is *not* a second GUI host. It does not render panels or widgets.

### Contents

| Sub-path | Responsibility |
|---|---|
| `adapters/` | Thin bridges: translate GUI events → controller calls, or controller results → GUI updates |
| `validation/` | Pure-Python field validators used by panels (no Tk dependency) |

### Rules

1. **No new Tk widgets belong in `src/gui_v2/`.**
2. Adapter modules in `adapters/` must not import Tk directly; they receive and return plain Python objects.
3. `validation/` modules must be side-effect free and pure-Python only.
4. New adapters written for the existing Tk runtime belong in `src/gui_v2/adapters/` only if they follow the strict no-Tk rule; otherwise they belong in `src/gui/utils/` or `src/gui/controllers/`.

---

## 4. Migration Boundary

`src/gui_v2/` exists as scaffolding for a potential future toolkit migration (PySide6 or other).  
As of v2.6, **no active migration is in progress**.

The boundary rule is:

> Everything in `src/gui_v2/` MUST remain importable without Tk.  
> Everything that requires Tk stays in `src/gui/`.

Any work that blurs this boundary (e.g., adding Tk imports to `src/gui_v2/`) requires an explicit approved PR and an architecture document update.

---

## 5. Addition Rules Summary

| I need to add... | Where it goes |
|---|---|
| New panel or tab frame | `src/gui/views/` or `src/gui/panels_v2/` |
| New widget | `src/gui/widgets/` |
| New dialog | `src/gui/dialogs/` |
| New learning or pipeline controller wrapper | `src/gui/controllers/` |
| Toolkit-agnostic validation logic | `src/gui_v2/validation/` |
| Adapter translating controller output → GUI | `src/gui_v2/adapters/` (must be Tk-free) |
| Style constant | `src/gui/ui_tokens.py` |
| Theme variable | `src/gui/theme_v2.py` |
| GUI-local presentation model | `src/gui/models/` |
| GUI utility (threading, dispatching) | `src/gui/utils/` |

---

## 6. Forbidden Patterns

The following patterns are defects regardless of which directory they appear in:

- Prompt construction in any GUI file (must happen in `src/pipeline/` via PromptPack)
- Job dict construction in any GUI file (must use `NormalizedJobRecord` from builder pipeline)
- Direct runner invocation from any GUI file (must go through `JobService`/queue)
- State mutation in a `view_contracts/` file
- Tk import in any `src/gui_v2/` file
- Shadow state for queue or history in any panel (the single truth lives in `AppStateV2` and the queue/history subsystems)
- Controller-side direct widget mutation such as `log_text.insert/delete/see` or status-label `.configure(...)` calls

---

## 7. Relationship to Other Documents

| Document | Relationship |
|---|---|
| [ARCHITECTURE_v2.6.md](../../ARCHITECTURE_v2.6.md) | Canonical GUI/application ownership rules; this doc is the file-placement companion |
| `AGENTS.md` | Repository operating contract and GUI ownership boundary |
