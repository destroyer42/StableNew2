from pathlib import Path

base = Path("/mnt/data")

overall_md = base / "StableNew_GUI_V2_Program_Plan.md"
phase1_md = base / "StableNew_Phase1_Repo_Cleanup_and_App_Spine.md"
phase2_md = base / "StableNew_Phase2_GUI_Layout_Theming_and_Wiring.md"
phase3_md = base / "StableNew_Phase3_Roadmap_Features_and_Learning_System.md"
phase4_md = base / "StableNew_Phase4_Testing_Docs_and_Packaging.md"

pr1_md = base / "PR-01_Repo_Inventory_and_Source_of_Truth.md"
pr2_md = base / "PR-02_Move_Legacy_V1_to_Archive.md"
pr3_md = base / "PR-03_Create_V2_App_Spine.md"

overall_content = """# StableNew GUI / Pipeline Program Plan (V2)

This document is the **top-level execution plan** for getting the `newComp` branch of StableNew into a clean, stable, V2-ready state.

It is meant to sit in the repo root (for example under `docs/PLAN/StableNew_GUI_V2_Program_Plan.md`) and act as the reference point for CODEX, human contributors, and other agents.

---

## 1. Objectives

1. **Stabilize and modernize the GUI (V2)**  
   - Restore the dark, modern ASWF-inspired theme.  
   - Fix the current “squished” layout and make it responsive to different window sizes.  
   - Consolidate all GUI logic into a clean V2 file set with clear ownership and boundaries.

2. **Clean and simplify the repository**  
   - Identify the active/working files that actually participate in the V2 app.  
   - Move V1 and obsolete files into an archive/legacy space.  
   - Reduce cognitive load for future contributors and for CODEX.

3. **Deliver the Roadmap v2.0 feature set**  
   - Implement the Learning System (passive + active).  
   - Implement improved job queue behaviour and robust pipeline wiring.  
   - Start laying the groundwork for distributed compute and agent-based automation.

4. **Improve reliability and maintainability**  
   - Add GUI smoke tests, pipeline tests, and IO safety checks.  
   - Add documentation so new devs (or agents) can come up to speed quickly.  
   - Ship a slimmer, more coherent codebase with clear extension points.

---

## 2. Phase Overview

The work is divided into **four phases**, each with its own goals and PRs.

### Phase 1 — Repo Cleanup & V2 App Spine

**Goal:** Identify the true V2 code paths, cleanly separate legacy/V1 material, and build a minimal but well-structured “app spine” for the GUI to hang on.

Key PRs:
- **PR-01:** Repo Inventory & Source of Truth Declaration  
- **PR-02:** Move Legacy/V1 Files to Archive  
- **PR-03:** Create the V2 App Spine (window bootstrap, package layout, imports)

### Phase 2 — GUI Layout, Theming, and Wiring

**Goal:** Fix the broken/squished GUI, restore theming, and standardize widget components so that new features do not regress layout or styling.

Key PRs:
- **PR-04:** Theme Engine V2 (ASWF black/gold, modern flat style)  
- **PR-05:** Layout Grid & Panel Structure (fix squishing, paddings, weights)  
- **PR-06:** Widget Componentization (Prompt, ModelSelector, QueueTable, etc.)  
- **PR-07:** Application State Layer (single AppState + event bus)  
- **PR-08:** Core Pipeline Wiring (txt2img/img2img/upscale in a unified path)

### Phase 3 — Roadmap Feature Implementation

**Goal:** Implement the feature work described in `StableNew_Roadmap_v2.0.md` and ContextDocs: pack config V2, improved PromptPack integration, Learning System, distributed compute, and agents.

Key PRs (high-level):
- **PR-09:** Pack Config System V2  
- **PR-10:** PromptPackPanel V2 Integration  
- **PR-11:** Job Queue V2 (no orphan jobs, predictable concurrency)  
- **PR-12:** Learning System — Passive logging and rating  
- **PR-13:** Learning System — Active learning planner  
- **PR-14:** Distributed Compute Foundations  
- **PR-15:** Agent/Automation Hooks  
- **PR-16:** File IO Safety & Upscale Tile Failsafes

### Phase 4 — Testing, Documentation, and Packaging

**Goal:** Wrap the program with tests, docs, and a slimmer package so StableNew V2 is maintainable and minimally confusing.

Key PRs:
- **PR-17:** GUI & Pipeline Smoke Tests  
- **PR-18:** Documentation Pass & Final Repo Slimdown

---

## 3. Execution Order & Dependencies

1. **Phase 1 must complete first.**  
   - PR-01 and PR-02 can be done in parallel, but PR-03 should wait until PR-01’s inventory is generated.  
   - The V2 app spine defined in PR-03 is the foundation for Phase 2’s theme/layout work.

2. **Phase 2 depends on the new app spine.**  
   - PR-04 (theme) and PR-05 (layout) operate on the new V2 GUI module structure.  
   - PR-06 (widgets) and PR-07 (state) assume that V1/V2 duplication is already removed.  
   - PR-08 relies on the cleaned-up pipeline entry points from PR-01/PR-03.

3. **Phase 3 consumes the cleaned pipeline and state model.**  
   - Pack config V2 and PromptPackPanel V2 plug into the V2 AppState and pipeline builder.  
   - Learning System and distributed compute use the standardized job model defined in PR-08/PR-11.

4. **Phase 4 can begin after Phase 2 is stable, and in parallel with late Phase 3 work.**  
   - Tests will evolve as features land, but the formal GUI smoke test suite should be stabilized after layout/theming are no longer volatile.  
   - Documentation updates can trail by one PR batch so they reflect actual behaviour.

---

## 4. Coding & PR Handling Pattern

Each PR in this plan is written to be executed by an automated agent (e.g., CODEX) or a human dev with the same expectations:

- **Single-responsibility:** Each PR focuses on one concept (inventory, archive, theme, layout, etc.).  
- **Explicit file lists:** PR specs identify which files are allowed to change and which must remain untouched.  
- **Structured tests:** Each PR includes concrete tests and manual verification steps.  
- **No silent breaking changes:** If a PR needs to change a public API or a behaviour that downstream features depend on, it must be called out explicitly in the PR description.

---

## 5. Naming & Directory Conventions

- All new GUI work should live under `src/gui/v2/` (lowercase `v2`) or similar, and be wired from `src/main.py`.  
- Legacy GUI work should move under `archive/gui_v1/` or similar.  
- Shared utilities remain under `src/utils/` but should be trimmed once unused functions are identified.  
- Documents like this plan live under `docs/`:
  - `docs/PLAN/StableNew_GUI_V2_Program_Plan.md`
  - `docs/PLAN/StableNew_Phase1_Repo_Cleanup_and_App_Spine.md`
  - etc.

---

## 6. Phase Summaries

Each phase has its own planning document with a more detailed breakdown of tasks, risks, and acceptance criteria:

- **Phase 1:** Repo Cleanup & V2 App Spine  
- **Phase 2:** GUI Layout, Theming, and Wiring  
- **Phase 3:** Roadmap Feature Implementation  
- **Phase 4:** Testing, Documentation, and Packaging  

See the corresponding phase documents for deeper detail.

---

## 7. Success Criteria

StableNew V2 is considered “Phase 4 complete” when:

1. The main entrypoint starts a visually coherent, non-squished dark-mode GUI using only V2 files.  
2. Legacy/V1 files are quarantined in clearly marked archive directories and are not imported by the running app.  
3. The core workflows (txt2img → optional img2img → upscale) work reliably on at least one machine.  
4. Learning logs and pack configurations can be written and re-used.  
5. GUI and pipeline smoke tests pass in CI, and the documentation in `docs/` reflects the current architecture and user flows.
"""

phase1_content = """# Phase 1 — Repo Cleanup & V2 App Spine

**Goal:** Identify the true V2 code paths, separate legacy/V1 content into an archive, and construct a clean “app spine” for the V2 GUI and pipelines.

This phase lays the groundwork for all subsequent work. The aim is to reduce noise, establish clear boundaries between V1 and V2, and define the structural layout of the application that other phases will build on.

---

## 1. Scope

Phase 1 covers:

- Automated and manual inventory of the repository.  
- Classification of files into: **active V2**, **legacy/V1**, and **utility/shared**.  
- Moving legacy/V1 code into `archive/` directories.  
- Defining and implementing the V2 app structure (packages, main window, imports).  
- Ensuring the app still runs after the initial structural reorg.

It does **not** yet fix GUI layout, theming, or new features. Those belong to later phases.

---

## 2. PRs in Phase 1

1. **PR-01 — Repo Inventory & Source of Truth Declaration**  
2. **PR-02 — Move Legacy/V1 Files to Archive**  
3. **PR-03 — Create V2 App Spine**  

These PRs should be executed in order, with limited overlap:

- PR-01 can run immediately.  
- PR-02 depends on the inventory produced by PR-01.  
- PR-03 should be applied after PR-02 has moved the legacy code aside (or at least after the inventory is available).

---

## 3. PR-01 — Repo Inventory & Source of Truth Declaration (Overview)

**Purpose:** Give us an objective map of the codebase: what is used, what is unused, and what currently boots the app.

### High-level Tasks

- Write a small Python script that walks `src/` and related directories and records:
  - All `.py` files and whether they are imported (static import analysis).  
  - All files that import `tkinter` / `ttk` or custom GUI modules.  
  - All files containing “V1” or “v1” in the name or top-level comments.  
  - All files under `tests/`, `docs/`, `tools/` (if present).  
- Attempt to resolve the import graph from `src/main.py` to identify “active” modules.  
- Output results into structured files:
  - `repo_inventory.json` — full file list and categories.  
  - `ACTIVE_MODULES.md` — narrative summary of what is “live”.  
  - `LEGACY_CANDIDATES.md` — list of likely V1/legacy files.

### Acceptance Criteria

- `python tools/inventory_repo.py` (or similar) runs without error and produces the three outputs.  
- `ACTIVE_MODULES.md` gives a clear, human-readable summary of the main packages and files that are used by the running app.  
- `LEGACY_CANDIDATES.md` enumerates GUI and pipeline files that look V1-ish, to be moved in PR-02.

---

## 4. PR-02 — Move Legacy/V1 Files to Archive (Overview)

**Purpose:** Physically separate legacy and V1 code from the active V2 code paths, reducing clutter and eliminating accidental imports.

### High-level Tasks

- Create archive directories, for example:
  - `archive/gui_v1/`  
  - `archive/pipeline_v1/`  
  - `archive/tools_legacy/`  
- Using `LEGACY_CANDIDATES.md` (from PR-01) as the starting point, move:
  - V1 GUI modules.  
  - Old pipeline modules that are no longer wired.  
  - Deprecated tools or scripts that are not used by `src/main.py`.  
- Replace direct imports of any moved modules with either:
  - V2 equivalents (if they already exist), or  
  - temporary shims and TODO markers.

### Acceptance Criteria

- App can still start and execute a minimal pipeline.  
- No archive modules are imported when running the app in its default mode.  
- `ACTIVE_MODULES.md` is updated to reflect that archived files are no longer part of the main path.  
- There is a clear directory boundary: **active code vs. archive**.

---

## 5. PR-03 — Create V2 App Spine (Overview)

**Purpose:** Define the structural backbone (packages, imports, and main window bootstrap) of the V2 GUI, separate from archived V1 code.

### High-level Tasks

- Create a dedicated package for V2 GUI code, e.g. `src/gui/v2/`.  
- Define the main window module (e.g. `main_window_v2.py`) that:
  - Owns the root `Tk` instance.  
  - Sets up the main frames/containers (left sidebar, center pipeline controls, right preview/queue).  
  - Delegates to future modules for widgets and theming.  
- Update `src/main.py` so it clearly calls into V2:
  - `from gui.v2.main_window_v2 import run_app` or similar.  
- Add placeholder modules for later phases:
  - `theme_v2.py`  
  - `layout_v2.py` or `containers.py`  
  - `state.py` (for AppState)  
  - `widgets/` subpackage for modular components.

### Acceptance Criteria

- Running the app starts the V2 main window module.  
- All imports point at `gui.v2` for GUI concerns (no V1 GUI imports remain in the main path).  
- Placeholder modules exist with simple, documented stubs so Phase 2 can fill them in.

---

## 6. Risks & Mitigations

- **Risk:** Moving files (PR-02) could break imports in hidden corners.  
  - *Mitigation:* After PR-02, run a simple import sanity script that attempts to import every module under `src/` and fails loudly if imports are broken.

- **Risk:** Building the V2 app spine too early could cause thrash when Phase 2 changes layout.  
  - *Mitigation:* Keep app spine lean; it only wires containers and defers styling/sizing to later PRs.

- **Risk:** Inventory script might miss dynamic imports.  
  - *Mitigation:* Use `ACTIVE_MODULES.md` as a living document and allow manual curation to fix mistakes as we go.

---

## 7. Success Criteria for Phase 1

Phase 1 is complete when:

1. `repo_inventory.json`, `ACTIVE_MODULES.md`, and `LEGACY_CANDIDATES.md` exist and are reasonably accurate.  
2. A significant portion of obviously-obsolete V1 files are moved into `archive/` directories.  
3. The application boots using the V2 main window entrypoint.  
4. The directory structure makes it obvious where new GUI work should happen (under `src/gui/v2/`) and where old work lives (`archive/`).

"""

phase2_content = """# Phase 2 — GUI Layout, Theming, and Wiring

**Goal:** Fix the current broken/squished GUI, restore the modern dark theme, and introduce a consistent component and state model for all GUI widgets.

Phase 2 is where the app becomes visually coherent and usable again. It assumes Phase 1 has already provided a clean V2 app spine and archived most legacy code.

---

## 1. Scope

This phase focuses on:

- Implementing a dedicated theme engine for the V2 GUI.  
- Defining a robust layout grid for the main window and its panels.  
- Refactoring monolithic GUIs into modular, reusable widget components.  
- Introducing a centralized application state layer so that widgets do not tightly couple to each other.  
- Wiring the core pipeline controls (txt2img, img2img, upscale) into the V2 GUI.

It does **not** implement new functional features like Learning System, distributed compute, or pack config V2 (those are Phase 3).

---

## 2. PRs in Phase 2

4. **PR-04 — Theme Engine V2 (ASWF Dark Theme)**  
5. **PR-05 — Layout Grid & Panel Structure**  
6. **PR-06 — Widget Componentization**  
7. **PR-07 — Application State Layer**  
8. **PR-08 — Core Pipeline Wiring**  

These PRs should generally be executed in order, but PR-06 and PR-07 can partially overlap once the basic theme and layout are in place.

---

## 3. PR-04 — Theme Engine V2 (Overview)

**Purpose:** Recreate and centralize the dark, modern, ASWF-style theme that was previously implemented and partially lost, so that the entire GUI shares consistent colors, fonts, and styling.

### High-level Tasks

- Implement `theme_v2.py` in `src/gui/v2/` which:
  - Defines the color palette: backgrounds, foregrounds, highlight, disabled, error.  
  - Defines base fonts and sizes (window title, section headings, labels, buttons, inputs).  
  - Configures `ttk.Style` with named styles like `Primary.TButton`, `Secondary.TButton`, `Panel.TFrame`, etc.  
- Provide helper functions:
  - `apply_theme(root)` to apply the styles to the root `Tk` instance.  
  - `get_colors()` / `get_fonts()` utilities for content that needs constants.  
- Update the V2 main window to call `apply_theme` at startup.

### Visual Targets

- Dark background canvas with minimal pure-white areas.  
- Gold primary buttons for “Run”/“Save”/“Apply”.  
- Muted gray controls for secondary actions.  
- Clean, modern font choices with readable sizes (especially for prompt fields and lists).

---

## 4. PR-05 — Layout Grid & Panel Structure (Overview)

**Purpose:** Fix the squished appearance and inconsistent spacing in the GUI by defining an explicit grid layout and panel structure with sensible row/column weights and padding.

### High-level Tasks

- In the main window module, define the top-level layout:
  - Left: Sidebar (model manager, core config, resolution, output settings).  
  - Center: Pipeline controls & prompt editor.  
  - Right: Preview & Jobs/Queue.  
- For each major panel:
  - Use `grid` with explicit `rowconfigure`/`columnconfigure` calls.  
  - Assign minimum sizes to key areas (prompt box, negative prompt area, job tables).  
  - Add interior padding and spacing between labeled sections.  
- Ensure that resizing the window:
  - Expands the prompt and negative prompt horizontally.  
  - Allows the job tables and preview to grow with available space.  
  - Does not cause labels or buttons to collapse.

### Acceptance Criteria

- At default window size, controls are spaced with sensible padding and no sections are visibly “crushed”.  
- When resizing the window, the UI scales gracefully: main panels expand, and clipped text is minimized.  
- No overlapping widgets or weirdly floating buttons.

---

## 5. PR-06 — Widget Componentization (Overview)

**Purpose:** Replace large, monolithic GUI files with smaller, clearly-owned widget components that can be independently updated and tested.

### High-level Tasks

- Under `src/gui/v2/widgets/`, create classes or factory functions for:
  - `PromptEditor` (prompt + char count, negative prompt).  
  - `ModelSelector` (model/VAE dropdowns and refresh).  
  - `CoreConfigPanel` (sampler, CFG, steps).  
  - `ResolutionPanel` (width, height, preset, MP estimation).  
  - `OutputSettingsPanel` (output directory and options).  
  - `JobsPanel` (active queue + recent jobs tables).  
  - `PipelineControlsPanel` (Run button, checkboxes, pipeline mode toggles).  
- Each component:
  - Owns its internal layout logic.  
  - Exposes clear methods for:
    - `bind_state(app_state)`  
    - `get_value()` / `set_value()` where appropriate.  
- The main window becomes a simple assembler wiring these widgets together.

### Acceptance Criteria

- The GUI can be started and shut down without errors.  
- The main window file shrinks meaningfully and primarily composes widgets.  
- Adding or modifying any one panel mostly touches its own widget module.

---

## 6. PR-07 — Application State Layer (Overview)

**Purpose:** Provide a single source of truth for GUI-related state so widgets do not reach into each other’s internals or rely on ad-hoc globals.

### High-level Tasks

- Implement an `AppState` class in `src/gui/v2/state.py` that manages:
  - Current model selection, sampler, CFG, steps.  
  - Resolution and output settings.  
  - Prompt and negative prompt text.  
  - Queue of pending and active jobs.  
- Implement a simple observer/event pattern:
  - Widgets can subscribe to state changes on specific keys.  
  - State updates trigger callbacks to subscribed widgets.  
- Ensure that:
  - The pipeline layer can read all necessary settings from `AppState`.  
  - Widgets communicate via state updates, not direct calls to each other.

### Acceptance Criteria

- State mutations go through `AppState` methods and are not scattered through widgets.  
- Unit tests (or simple integration tests) confirm that updating state propagates correctly to subscribed widgets.  
- Pipeline execution uses `AppState` to assemble job configurations.

---

## 7. PR-08 — Core Pipeline Wiring (Overview)

**Purpose:** Wire the V2 GUI to the existing pipeline client so that the core workflows (txt2img, optional img2img, upscale) run through a unified, well-defined process.

### High-level Tasks

- Define a `PipelineController` (or similar) module that:
  - Consumes `AppState` and creates callable payloads.  
  - Offers methods like `run_txt2img`, `run_img2img`, `run_full_pipeline`.  
  - Communicates job lifecycle to the `JobsPanel` via state updates.  
- Ensure:
  - CLI/client logic in `src/api/client` (or equivalent) is reused, not duplicated.  
  - Pipeline parameters (tile sizes, max MP, etc.) are passed correctly.  
- For now, the core pipeline should operate on the **local node only**; distributed compute comes in Phase 3.

### Acceptance Criteria

- Pressing “Run” from the V2 GUI triggers a pipeline job and updates the Jobs/Queue panel.  
- Completed jobs appear in the “Recent Jobs” table with payload information.  
- The GUI does not hang indefinitely or create duplicate jobs for a single click.  

---

## 8. Success Criteria for Phase 2

Phase 2 is complete when:

1. The GUI launches with a consistent dark ASWF-style theme and non-squished layout.  
2. Widgets are modular, owned by specific components, and wired via `AppState`.  
3. The Run button and pipeline controls reliably execute the core pipeline through a V2 controller.  
4. The UI looks and feels like a modern, cohesive app ready to host the Roadmap features from Phase 3.

"""

phase3_content = """# Phase 3 — Roadmap Feature Implementation

**Goal:** Implement the Roadmap v2.0 feature set on top of the stabilized V2 GUI and pipeline, focusing on configuration management, PromptPack integration, Learning System capabilities, job queue reliability, and early distributed compute/agent hooks.

This phase is where the application gains most of its “intelligence” and workflow power.

---

## 1. Scope

Phase 3 includes:

- A redesigned Pack Config system that aligns GUI presets with on-disk pack definitions.  
- Deeper integration with Prompt Packs, including categorization and preview capabilities.  
- A robust job queue implementation that avoids hangs and duplicated work.  
- Both passive and active learning systems to log runs and design experiments.  
- Initial support for distributed compute and agents as described in ContextDocs.

It assumes that:

- The V2 GUI is stable (Phase 2 complete).  
- Pipelines are wired through a single controller and `AppState`.  
- There is a consistent way to construct payloads for jobs.

---

## 2. PRs in Phase 3

9. **PR-09 — Pack Config System V2**  
10. **PR-10 — PromptPackPanel V2 Integration**  
11. **PR-11 — Job Queue V2**  
12. **PR-12 — Learning System — Passive Logging & Rating**  
13. **PR-13 — Learning System — Active Learning Planner**  
14. **PR-14 — Distributed Compute Foundations**  
15. **PR-15 — Agent/Automation Hooks**  
16. **PR-16 — File IO Safety & Upscale Tile Failsafes**  

Some of these PRs can overlap (e.g., queue work and learning logs), but they share the same underlying model of jobs and pipelines.

---

## 3. PR-09 — Pack Config System V2 (Overview)

**Purpose:** Centralize configuration for models, samplers, resolutions, and output behaviour into structured pack config files that can be selected from the GUI and applied consistently.

### High-level Tasks

- Define a pack schema (YAML or JSON) that includes:
  - Model and VAE choices.  
  - Sampler, steps, CFG, resolution presets.  
  - Output directory and naming conventions.  
  - Any roadmap-specific toggles (e.g., learning flags).  
- Implement loader/saver utilities that:
  - Read packs from a `packs/config/` directory.  
  - Validate pack structure and surface errors clearly in the GUI.  
- Update the V2 GUI:
  - The “Using: Pack Config” bar shows the active pack.  
  - “Save Editor → Preset” and “Apply Editor → Pack(s)” integrate with the new schema.

### Acceptance Criteria

- Users can load and save pack configs from the GUI.  
- Packs are versioned and validated; invalid packs do not crash the app.  
- AppState reflects the selected pack and can re-construct it as a config object.

---

## 4. PR-10 — PromptPackPanel V2 Integration (Overview)

**Purpose:** Upgrade the PromptPackPanel to fully integrate with the V2 GUI and leverage roadmap ideas like categories, tags, and dry-run payload previews.

### High-level Tasks

- Standardize the on-disk structure for prompt packs:
  - grouping, tags, metadata.  
- Update the PromptPackPanel widget to:
  - Display packs with categories and tags.  
  - Provide quick actions: apply, append, replace.  
- Implement “Preview Payload (Dry Run)”:
  - Generate a payload JSON preview based on current AppState and selected pack.  
  - Pop up a read-only preview window for inspection.

### Acceptance Criteria

- Selecting a prompt pack updates the prompt editor as expected.  
- Dry-run preview shows a human-readable payload (and can be copied).  
- Pack metadata (e.g., tags like “character”, “landscape”) appears in the UI.

---

## 5. PR-11 — Job Queue V2 (Overview)

**Purpose:** Make the job queue robust so that jobs cannot become stuck in odd states, and the GUI can accurately reflect active vs. completed work.

### High-level Tasks

- Design a `Job` model (ID, status, timestamps, payload, node, etc.).  
- Implement a job manager that:
  - Tracks job lifecycle: queued → running → completed/failed/cancelled.  
  - Prevents multiple concurrent jobs for operations that must be serialized.  
  - Emits events to update `AppState` (so JobsPanel redraws).  
- Introduce a watchdog/failsafe:
  - Detect jobs that have been “running” for too long and either:
    - Mark them as stale and display a warning, or  
    - Expose a “force cancel” option.

### Acceptance Criteria

- No orphaned jobs in the queue: each job has a final state.  
- The JobsPanel accurately reflects active and recent jobs.  
- Past bugs such as four upscales running at once are no longer reproducible under normal usage.

---

## 6. PR-12 — Learning System — Passive Logging & Rating (Overview)

**Purpose:** Implement passive run logging and a basic feedback loop where the user can rate outputs, building a corpus for future optimization and model selection logic.

### High-level Tasks

- Define a logging format and location, e.g., `data/logs/learning_runs.jsonl`.  
- Log for each job:
  - Prompt, negative prompt, model, sampler, cfg, steps, resolution, and any pack IDs.  
  - Timestamps and node information.  
  - Paths to generated images.  
- Add a UI element for rating:
  - Simple 1–5 stars or thumbs up/down per job.  
  - Ratings persisted in the log.

### Acceptance Criteria

- Every completed job appends a record to the learning log.  
- Ratings can be applied and persist.  
- Logs are structured and machine-readable for downstream analysis.

---

## 7. PR-13 — Learning System — Active Learning Planner (Overview)

**Purpose:** Provide a UI to design and run experiments over combinations of parameters (e.g., CFG values, samplers, resolutions), using the pipeline and queue abstractions.

### High-level Tasks

- Implement an “Experiment Planner” UI:
  - choose variables, value ranges or sets, and number of runs.  
- Generate an experiment matrix:
  - Each row corresponds to a planned job configuration.  
- Integrate with the job queue:
  - Add jobs in batches while respecting queue depth and pipeline constraints.  
- Link results back into the learning log with experiment IDs for later analysis.

### Acceptance Criteria

- User can define an experiment and enqueue a batch of jobs.  
- Each job carries experiment metadata in the logs.  
- Experiments can be paused or cancelled as a group.

---

## 8. PR-14 — Distributed Compute Foundations (Overview)

**Purpose:** Implement the basic plumbing described in ContextDocs for discovering worker nodes and directing jobs to them, without fully optimizing for performance yet.

### High-level Tasks

- Define a simple node registry (static config file or lightweight service).  
- Extend the job model with a `node_id` field.  
- Update pipeline client to:
  - Choose the local node by default.  
  - Optionally target a specific node based on node capabilities (e.g., GPU presence).  
- Provide a UI control to select target node or “auto”.

### Acceptance Criteria

- With at least two configured nodes, the GUI can dispatch jobs to either node.  
- Logs record which node handled each job.  
- If the remote node is unreachable, the job fails gracefully and surfaces an error.

---

## 9. PR-15 — Agent/Automation Hooks (Overview)

**Purpose:** Expose controlled entry points so external agents (e.g., CODEX) can programmatically create packs, enqueue jobs, or review logs.

### High-level Tasks

- Define a small internal API surface (could be CLI, HTTP, or Python API).  
- Document how agents can:
  - Load packs.  
  - Enqueue jobs with specific configs.  
  - Read learning logs.  
- Add minimal authentication/guardrails if exposing HTTP endpoints.

### Acceptance Criteria

- It is possible to script end-to-end runs using the agent interface without clicking the GUI.  
- Automation hooks are documented and stable.

---

## 10. PR-16 — File IO Safety & Upscale Tile Failsafes (Overview)

**Purpose:** Address known issues such as excessive tile sizes and guard against runaway memory usage or IO failures.

### High-level Tasks

- Centralize defaults for:
  - Max image megapixels.  
  - Max tile size per upscale method.  
- Implement automatic fallback:
  - If a requested tile size would exceed the limit, scale it down.  
- Add validation on output directories and file naming.

### Acceptance Criteria

- Upscale flows that previously hung now complete or fail with clear errors.  
- Logs record when failsafes are triggered.  
- No silent crashes due to tile size or path issues in normal usage.

---

## 11. Success Criteria for Phase 3

Phase 3 is complete when:

1. Users can reliably configure and re-use pack configs from the GUI.  
2. Prompt packs are easy to browse and apply, with dry-run payload previews.  
3. The job queue behaves predictably under typical workloads, including batched experiments.  
4. A learning log exists and is steadily accumulating data from runs.  
5. Basic distributed compute is possible on a small LAN.  
6. Agents have a stable interface for orchestrating runs and reading logs.

"""

phase4_content = """# Phase 4 — Testing, Documentation, and Packaging

**Goal:** Wrap StableNew V2 with a robust test harness, up-to-date documentation, and a slimmer package layout, ensuring that future changes are safe and comprehensible.

This phase focuses on stability, clarity, and long-term maintainability rather than new features.

---

## 1. Scope

Phase 4 covers:

- Automated GUI and pipeline smoke tests.  
- Documentation updates, including architecture and contribution guidance.  
- Final repo slimdown (removing obsolete tools and dead code).  
- Light packaging work so the app can be run easily by others.

It assumes Phases 1–3 have landed and stabilized.

---

## 2. PRs in Phase 4

17. **PR-17 — GUI & Pipeline Smoke Tests**  
18. **PR-18 — Documentation Pass & Repo Slimdown**  

---

## 3. PR-17 — GUI & Pipeline Smoke Tests (Overview)

**Purpose:** Provide automated safeguards that catch obvious regressions in GUI startups and pipeline execution.

### High-level Tasks

- Implement tests that:
  - Instantiate the V2 main window in a headless or minimal environment (no infinite mainloop).  
  - Verify that key widgets can be created and bound to `AppState`.  
  - Run short, synthetic pipelines using a lightweight model or mocked interface.  
- Integrate tests into the existing test runner/CI configuration.  
- Add a simple “diagnostic mode” CLI option that runs a subset of these checks without requiring full test invocation.

### Acceptance Criteria

- Running `pytest` (or the chosen test command) executes GUI and pipeline smoke tests.  
- The tests fail fast if a core widget cannot be created or if pipeline wiring is broken.  
- A dedicated “diagnostic” command provides a quick health check for local installs.

---

## 4. PR-18 — Documentation Pass & Repo Slimdown (Overview)

**Purpose:** Bring documentation in line with the final state of the codebase and remove lingering dead files that are no longer needed.

### High-level Tasks

- Update or create documentation under `docs/`:
  - `ARCHITECTURE_V2.md` — describe packages, data flow, and main components.  
  - `GUI_V2_OVERVIEW.md` — describe panels, state, event flow.  
  - `CONTRIBUTING.md` — how to run the app, tests, and style expectations.  
  - `StableNew_GUI_V2_Program_Plan.md` and the phase docs (this set) as historical context.  
- Clean up:
  - Old tools that are no longer referenced by active code.  
  - Obsolete configs and sample scripts.  
  - Redundant or outdated docs that conflict with V2 reality.  
- Ensure README is updated:
  - Quickstart instructions.  
  - Screenshots of the new V2 GUI.  
  - Pointers to deeper docs.

### Acceptance Criteria

- Documentation matches the current application layout and behaviours.  
- There is a clear path for new contributors to get started.  
- The repo tree has no obviously dead top-level modules or directories.  

---

## 5. Success Criteria for Phase 4

Phase 4 is complete when:

1. Core app behaviours are protected by at least a minimal automated test suite.  
2. Documentation is coherent and discoverable from the repo root.  
3. The repository no longer contains significant unreferenced or legacy code outside of clearly-marked archive directories.  
4. The app can be run and understood by someone new using only the README and the docs under `docs/`.

"""

pr1_content = """# PR-01 — Repo Inventory & Source of Truth Declaration

## Summary

Create a small, focused tooling layer that inventories the repository, identifies active modules used by the running app, and flags likely legacy/V1 files. This PR does **not** move or delete anything; it only observes and records.

This is the foundation for subsequent cleanup and refactors.

---

## Motivation

- The repository currently contains a mix of V1 and V2 GUI and pipeline files.  
- Without a clear understanding of what is actually used at runtime, refactors are risky and brittle.  
- Automated tools (e.g., CODEX) need a machine-readable view of the codebase to make safe modifications.

---

## Scope

**In scope:**

- New inventory script(s) and supporting modules.  
- New documentation files summarizing active modules and legacy candidates.  

**Out of scope:**

- Moving or deleting any code.  
- Changing `src/main.py` or the current runtime behaviour of the app.

---

## Implementation Plan

1. **Create tooling module**  
   - Add a `tools/` or `scripts/` package (e.g., `tools/inventory_repo.py`).  
   - This script must be runnable via `python -m tools.inventory_repo` from the repo root.

2. **Walk the code tree**  
   - Recursively walk key directories (at minimum `src/`, optionally `tests/`, `docs/`).  
   - For each `*.py` file record:
     - Path (relative to repo root).  
     - Whether it imports `tkinter` / `ttk`.  
     - Whether the filename or top-level comment contains `v1`/`V1`.  
     - Simple metrics (e.g., line count) to help eyeball complexity.

3. **Static import graph**  
   - Attempt to build a simple import graph starting from `src/main.py`:  
     - Use `ast` or a basic heuristic to find `import ...` and `from ... import ...` statements.  
     - Traverse reachable modules to mark them as “active”.  
   - This does not need to be perfect — a best-effort static analysis is sufficient.

4. **Outputs**  
   - `repo_inventory.json` (machine-readable):
     - per-file info, plus flags like `"is_gui": true`, `"has_v1_marker": true`, `"reachable_from_main": true`.  
   - `ACTIVE_MODULES.md` (human-readable):
     - summarise main packages and modules used by the running app.  
   - `LEGACY_CANDIDATES.md` (human-readable):
     - list of files suspected to be V1 or unused, grouped by probable category (GUI, pipeline, tools).

5. **Developer convenience**  
   - Add a short section to `README` or `docs/` explaining how to run the inventory script and what the outputs mean.

---

## Files Expected to Change / Be Added

- **New:** `tools/inventory_repo.py` (or equivalent path).  
- **New:** `repo_inventory.json` (generated, may be git-ignored depending on policy).  
- **New:** `docs/ACTIVE_MODULES.md`  
- **New:** `docs/LEGACY_CANDIDATES.md`  
- **Possible:** minor additions to `README.md` or `docs/` index.

No existing source files should be modified for this PR beyond minor documentation updates.

---

## Tests & Validation

- Run the script locally: `python -m tools.inventory_repo`  
  - Confirm that it completes without throwing exceptions.  
  - Confirm that `repo_inventory.json` is populated with all expected `.py` files.  
  - Confirm that `ACTIVE_MODULES.md` and `LEGACY_CANDIDATES.md` are generated and readable.

- Manual spot-checks:
  - Verify that known active modules (e.g., the current GUI entrypoint and pipeline client) show as reachable from `src/main.py`.  
  - Verify that obviously legacy/V1 files appear in `LEGACY_CANDIDATES.md`.

---

## Acceptance Criteria

- The repository contains a runnable inventory script.  
- After running the script, the three output artifacts (`repo_inventory.json`, `ACTIVE_MODULES.md`, `LEGACY_CANDIDATES.md`) exist and correctly list files.  
- No runtime behaviour of the StableNew app is changed by this PR.

"""

pr2_content = """# PR-02 — Move Legacy/V1 Files to Archive

## Summary

Using the outputs from PR-01, create a clear separation between active V2 code and legacy/V1 code by moving legacy files into dedicated `archive/` directories. Ensure that the app still runs and that no archived modules are imported in normal operation.

---

## Motivation

- The mixture of V1 and V2 files is confusing for maintainers and automated tools.  
- Removing legacy code is risky; archiving it is safer while still reducing noise.  
- Future work (V2 app spine, theme, layout, learning system) should operate on a clearly-labelled V2 codebase.

---

## Scope

**In scope:**

- Creating `archive/` directories for GUI, pipeline, and other legacy code.  
- Moving V1/legacy files into those directories.  
- Fixing imports for any modules that depended on moved files, if still needed.

**Out of scope:**

- Rewriting the logic of any module beyond minimal import adjustments.  
- Implementing the V2 app spine (that is PR-03).

---

## Implementation Plan

1. **Define archive structure**  
   - Create directories such as:
     - `archive/gui_v1/`  
     - `archive/pipeline_v1/`  
     - `archive/tools_legacy/`  
   - Add a short `README.md` in `archive/` explaining purpose and retention policy.

2. **Select files to move**  
   - Start with `docs/LEGACY_CANDIDATES.md` from PR-01.  
   - For each candidate file:
     - Confirm that it is **not** imported (or that imports are only from other legacy modules).  
     - Double-check that there is a newer V2 equivalent when applicable.  
   - Maintain a mapping file, e.g. `archive/ARCHIVE_MAP.md`, that lists:
     - Original path → archive path.  
     - Reason for archival.

3. **Move files**  
   - Physically move the selected files to the appropriate archive directory.  
   - Update any remaining imports that refer to them and are still legitimately needed (for example, a tool that still expects an old module):
     - Either change the import path to point into `archive/...`, or  
     - Mark the dependent module as legacy and move it too.

4. **Guard against accidental imports**  
   - Add a simple mechanism to detect archive imports from active code, for example:
     - A check in `src/main.py` or a small unit test that fails if `archive.` appears in the import tree.  
   - Alternatively, agree that archived modules should only be imported by scripts in `archive/` and enforce that by convention.

5. **Update documentation**  
   - Update `ACTIVE_MODULES.md` to reflect that archived code is no longer considered active.  
   - Explain archive usage briefly in `docs/` or the repo README.

---

## Files Expected to Change / Be Added

- **New:** `archive/README.md`  
- **New:** `archive/ARCHIVE_MAP.md`  
- **Moved:** Various V1/legacy modules (GUI, pipeline, tools), paths to be determined from `LEGACY_CANDIDATES.md`.  
- **Updated:** `docs/ACTIVE_MODULES.md`  
- **Updated:** Any files that require import path adjustments due to the moves.

---

## Tests & Validation

- Run the app entrypoint: `python -m src.main`  
  - App should start successfully using the current GUI (even if it is still visually rough).  
- Run a basic pipeline job to confirm there are no obvious runtime errors.  
- Optionally run a simple script that tries to import all `src.` modules and fails if any import from `archive.` is detected in the active path.

---

## Acceptance Criteria

- All clearly legacy/V1 modules are moved under `archive/` directories.  
- The StableNew app still starts and can run a simple job.  
- `ACTIVE_MODULES.md` no longer lists archived files as active.  
- There is a documented map of which files were archived and why.

"""

pr3_content = """# PR-03 — Create V2 App Spine

## Summary

Define and implement the structural backbone of the V2 application: a dedicated V2 GUI package, a main window module, and a clean entrypoint from `src/main.py`. This PR does not fully fix styling or layout; it focuses on structure and wiring.

---

## Motivation

- After Phase 1 cleanup, we want a clear and explicit place where all V2 GUI work lives.  
- Legacy/V1 GUI code should not be part of the main app path.  
- Future PRs (theme engine, layout, widgets, state, learning system) all need a stable, agreed-upon app structure.

---

## Scope

**In scope:**

- Creating the `src/gui/v2/` package.  
- Implementing `main_window_v2.py` with minimal but functional GUI scaffolding.  
- Updating `src/main.py` to launch V2 instead of the old GUI.  
- Adding placeholder modules for later work (`theme_v2.py`, `state.py`, `widgets/`, etc.).

**Out of scope:**

- Full visual polish and layout refinement (Phase 2).  
- New features like Learning System or distributed compute (Phase 3).

---

## Implementation Plan

1. **Create V2 package layout**  
   - Under `src/gui/`, add:
     - `v2/__init__.py`  
     - `v2/main_window_v2.py`  
     - `v2/theme_v2.py` (stub – will be filled in by PR-04)  
     - `v2/state.py` (stub – will be filled in by PR-07)  
     - `v2/widgets/__init__.py` (empty for now)  
   - Optionally add `v2/containers.py` or `v2/layout.py` as a future home for layout logic.

2. **Implement minimal main window**  
   - `main_window_v2.py` should:
     - Create the `Tk` root.  
     - Set a basic window title and minimum size.  
     - Create placeholder frames for:
       - Sidebar  
       - Pipeline controls  
       - Preview & jobs  
     - Arrange them in a simple grid so the app is obviously running V2 (even if visually plain).  
   - For now, frames can be empty or contain simple labels (“Sidebar”, “Pipeline”, “Preview/Jobs”).

3. **Wire entrypoint to V2**  
   - In `src/main.py`, import and call a function such as:
     - `from gui.v2.main_window_v2 import run_app`  
     - `if __name__ == "__main__": run_app()`  
   - Ensure any previous GUI entrypoint (V1) is no longer invoked by default.

4. **Document and mark TODOs**  
   - In `theme_v2.py`, `state.py`, and `widgets/__init__.py`, add docstrings describing their intended purpose and which PRs will fill them in.  
   - Add comments in `main_window_v2.py` indicating where Phase 2 work (layout, themes, widgets, state binding) will plug in.

5. **Maintain compatibility for pipelines**  
   - Ensure that whatever minimal controls exist still call into the current pipeline client when the user triggers a basic run (even if via a temporary “Run demo” button).  
   - This preserves a working vertical slice.

---

## Files Expected to Change / Be Added

- **New:** `src/gui/v2/__init__.py`  
- **New:** `src/gui/v2/main_window_v2.py`  
- **New:** `src/gui/v2/theme_v2.py` (stub)  
- **New:** `src/gui/v2/state.py` (stub)  
- **New:** `src/gui/v2/widgets/__init__.py`  
- **Updated:** `src/main.py` to launch V2.

No changes should be made to archived V1 code.

---

## Tests & Validation

- Run the app: `python -m src.main`  
  - Confirm that the window clearly shows “V2” via a title or label, so there is no ambiguity.  
  - Confirm that the window has three major regions (sidebar, pipeline, preview/jobs).  
- Trigger any available run/demo action to ensure pipeline calls still function.

---

## Acceptance Criteria

- The StableNew app launches using the V2 GUI entrypoint by default.  
- There is a dedicated `src/gui/v2/` package with placeholders for theme, state, and widgets.  
- The app remains functional, even if visually barebones.  
- The structure is ready for Phase 2 PRs to build on (theme/layout/widget refactors).

"""
