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

### Pipeline settings sources (PR-GUI-UX-500)

The Pipeline sidebar keeps four things apart, and `view_contracts/config_source_contract.py` owns their wording and the small decisions behind it (no Tk, no persistence): a **PromptPack** (authored prompt file that also stores its own saved settings), a **saved recipe** (a named copy of stage settings in the `presets` folder, no prompts), a **saved pack list** (a named group of PromptPacks that only filters the pack list; read from `state/custom_pack_lists.json`, and no in-app action creates one) and the **working stage settings**. The recipe list hides the application's own files in `presets` (`settings`, `last_settings`, `pack_overrides`); that is display only and no file is moved or deleted. The sidebar's source label states what the working settings were last loaded from (an Apply to Working State / Load to Pipeline of a recipe, or Load Pack Config of a PromptPack) and says a merely selected recipe is "selected, not applied"; later stage edits are not tracked. Load Pack Config copies a pack's saved settings into the stage cards; Save Config to Pack overwrites the settings stored in the selected packs (prompts are untouched). An empty recipe list, pack list or saved-pack-list dropdown states why it is empty and which supported action fills it.

The Pipeline preview thumbnail shows a saved image of the previewed job (the last of the previewed jobs) or says why there is none: no job, no image saved yet, or hidden by the content-visibility setting. Ticking "Show output thumbnail" never generates an image.

---

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
