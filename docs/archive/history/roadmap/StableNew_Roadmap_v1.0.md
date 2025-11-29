# StableNew Roadmap v1.0

_Last updated: 2025-11-15_

This roadmap focuses on:

1. **Repo cleanup & documentation consolidation**
2. **Stability, TDD, and refactors**
3. **GUI overhaul (Figma → implementation)**
4. **Job queue & refinement automation**
5. **Distributed workloads & video pipeline**

Each phase is expressed as a set of **PR-sized work items**, with an expectation of **small, focused branches** and **tests-first** behavior.

---

## Phase 1 – Repo Cleanup & Documentation Consolidation

### Goals

- Root directory stays minimal (only files the system truly needs).
- All docs live under `/docs/` with clear versioning.
- Archived or outdated docs live under `/docs/archive/`.
- AI/Codex/Copilot instructions are unified and versioned.
- Project is easy for both humans and AI agents to navigate.

### Workstreams & Suggested PRs

#### 1.1 Root Folder Simplification

**Branch:** `cleanup/root-minimal-v1`

- Move non-essential docs from root into `/docs/`.
- Keep only:
  - `README.md` (high-level project overview)
  - `pyproject.toml` / `requirements.txt` / `setup.cfg` (as needed)
  - `src/`, `tests/`, `tools/`, `presets/`, `packs/`, `docs/`, `.github/`
- Add `PROJECT_INSTRUCTIONS.md` to `/docs/` (or root) with a concise description of:
  - Purpose
  - Where docs live
  - How AI tools should be used

#### 1.2 Docs Consolidation & Versioning

**Branch:** `cleanup/docs-structure-v1`

- Create standardized hierarchy:
  - `docs/StableNew_History_Summary.md`
  - `docs/Known_Bugs_And_Issues_Summary.md`
  - `docs/StableNew_Roadmap_v1.0.md`
  - `docs/AGENTS_AND_AI_WORKFLOW.md`
  - `docs/CONFIGURATION_TESTING_GUIDE_v1.0.md`
  - `docs/GUI_REVAMP_SUMMARY_v1.0.md`
  - `docs/RANDOMIZATION_AND_MATRIX_UI_SUMMARY_v1.0.md`
  - `docs/ARCHITECTURE_ARCHIVE_2024-11-02.md` (from old `ARCHITECTURE.md`)
- Move older sprint/PR docs and experimental plans into:
  - `docs/archive/SPRINT_*.md`
  - `docs/archive/PR*_*.md`
- Update `_toc.md` to reflect the new layout.

#### 1.3 AI & Agent Instructions Unification

**Branch:** `cleanup/ai-workflow-docs-v1`

- Replace scattered Codex/Copilot docs with:
  - `docs/AGENTS_AND_AI_WORKFLOW.md`
  - `.github/copilot-instructions.md`
  - `.github/CODEX_SOP.md` (trimmed & updated to reference the unified doc)
- Mark older AI instruction files in `/docs/archive/` as superseded.
- Make `README.md` and `CONTRIBUTING.md` point to the new canonical docs.

---

## Phase 2 – Stability, TDD, and Core Refactors

### Goals

- No more hangs on second run.
- Upscale and pipeline stages are robust and predictable.
- Retry/backoff behavior is well-defined.
- Config pass-through remains rock solid.
- TDD becomes the default discipline.

### Ground Rule

> **No code change without a failing test first.**  
> Then make the test pass. Then run the suite.

### Workstreams & Suggested PRs

#### 2.1 Lifecycle & Second-Run Stability

**Branch:** `stability/gui-lifecycle-v1`

- Add/update tests for:
  - Run → Complete → Run again.
  - Run → Stop → Run again.
- Confirm state machine transitions correctly through IDLE/RUNNING/STOPPING/ERROR.
- Fix controller/Pipeline wiring so each run starts with a clean state.
- Document lifecycle behavior in `docs/StableNew_History_Summary.md` and future architecture doc.

#### 2.2 Upscale Safety & Tile Configuration

**Branch:** `stability/upscale-tiling-v1`

- Introduce a helper for safe upscale tile configuration:
  - Derive tile sizes from resolution + safe defaults.
  - Allow an advanced override in config, but default conservative.
- Add tests that:
  - Check payloads for `upscale_image` under typical resolutions.
  - Verify tile sizes never exceed configured safety thresholds.
- Ensure upscale-only flows (`upscale_only` pipeline paths) use the same helper.

#### 2.3 Retry / Backoff & Manifest Integration

**Branch:** `stability/retry-backoff-v1`

- Implement a simple retry wrapper around `txt2img` (and optionally `img2img`):
  - Max attempts (e.g., 3).
  - Exponential backoff.
  - Early exit if cancel token is set.
- Extend manifests to include retry metadata.
- Update/extend `test_pipeline_journey.py` to assert on:
  - Retry count.
  - Behavior on both success-after-retry and permanent failure.

#### 2.4 Config Integrity & TDD Guardrails

**Branch:** `stability/config-passthrough-hardening-v1`

- Make `test_config_passthrough.py` the canonical gate for any config-related change:
  - Document maintenance steps at the top.
  - Add a make/Poetry target `test-config` for quick run.
- Update `CONFIGURATION_TESTING_GUIDE` to:
  - Emphasize running this test whenever presets or config structures change.
  - Explain how to add new parameters correctly.

---

## Phase 3 – GUI Overhaul (Figma → Tk)

### Goals

- A **coherent, modern layout** without nested scrollbars.
- Clear **command bar** for primary actions.
- Panels organized by function (Config, Packs, Randomization, Pipeline, Logs).
- Visual hierarchy and spacing that doesn’t feel like Win95.

### Workstreams & Suggested PRs

#### 3.1 Figma Master Layout

**Branch:** `gui/figma-layout-v1` (planning-only branch)

- In Figma:
  - Define overall window structure:
    - Top: menu/title + primary pipeline controls.
    - Left or top-left: packs & presets.
    - Right or center: configuration + randomization.
    - Bottom: logs & status.
  - Ensure:
    - Clear resize behavior.
    - One primary scrolling region if needed.
- Export screenshots and link into:
  - `docs/GUI_REVAMP_SUMMARY_v2.0.md`

> This phase produces *design only*, no code changes.

#### 3.2 Core Layout Refactor

**Branch:** `gui/layout-refactor-v1`

- Translate Figma layout into Tkinter:
  - Introduce a small layout abstraction if needed (e.g., “zones” or panels).
  - Reduce nested frames and scrollbars.
  - Keep each panel’s responsibilities narrow.
- Break into small PRs:
  - `gui/layout-main-window-v1`
  - `gui/layout-log-panel-v1`
  - `gui/layout-randomization-panel-v1`

#### 3.3 Widget & State Wiring Cleanup

**Branch:** `gui/state-refactor-v1`

- Move ad-hoc widget access into well-defined panel classes or view objects.
- Simplify how state changes propagate:
  - Use a central state object with clear events (already partially present).
- Ensure STOP, Run, and Preview buttons are wired through a clean controller instead of scattered callbacks.

#### 3.4 Theming & Visual Polish

**Branch:** `gui/theme-and-style-v1`

- Apply consistent theming from `gui_theming.md`:
  - Dark mode defaults.
  - Consistent typography and spacing.
  - Visual grouping of related controls.
- Keep behavior changes minimal in this PR; focus on look & feel.

---

## Phase 4 – Job Queue & Refinement Automation

### Goals

- Move from “click Run once” to a **job-oriented mental model**.
- Provide a basic **queue** where multiple runs can be scheduled.
- Introduce **post-processing/refinement pipelines** that can be enabled/disabled.

### Workstreams & Suggested PRs

#### 4.1 Internal Job Model & Queue

**Branch:** `pipeline/job-model-v1`

- Introduce a lightweight job abstraction:
  - Input: prompt pack + preset + pipeline options.
  - Output: run directory + manifest summary.
- Add an in-memory queue:
  - Append jobs.
  - Process jobs in sequence via the existing pipeline executor.

#### 4.2 GUI Integration – Job List & Status

**Branch:** `gui/job-queue-v1`

- Add a simple job list panel:
  - Show queued, running, completed jobs.
- Allow:
  - Add job (current configuration).
  - Run queue.
  - Cancel current job.

#### 4.3 Refinement Pipelines & Auto-Cleanup

**Branch:** `pipeline/refinement-automation-v1`

- Define post-run hooks:
  - Auto-run face cleanup or restoration passes where appropriate.
  - Optional auto-archive or move outputs to curated directories.
- Make these controlled via config and visible in the GUI.

---

## Phase 5 – Distributed Workloads & Video Pipeline

### Goals

- Lay the foundation to use **multiple machines/GPUs on the local network**.
- Promote video generation from “nice to have” to first-class stage.

### Workstreams & Suggested PRs

#### 5.1 Distributed Architecture Planning

**Branch:** `design/distributed-architecture-v1` (planning doc)

- Decide on architecture:
  - Headless worker nodes running a small agent.
  - Front-end controller (StableNew GUI) sending jobs over HTTP or local RPC.
- Document constraints, security, and expected job protocols.

#### 5.2 Worker Prototype

**Branch:** `pipeline/worker-prototype-v1`

- Build a simple “worker” script:
  - Accepts a job description (prompt, config) over HTTP/JSON.
  - Runs the pipeline headlessly.
  - Returns manifest and paths (or writes to shared storage/NAS).

#### 5.3 Video Pipeline Integration

**Branch:** `pipeline/video-stage-v1`

- Firm up the `VideoCreator` abstraction:
  - Well-defined input (image sequence + config).
  - Clear output paths and manifest entries (`video_path`).
- Ensure:
  - Video-related tests in `test_pipeline_journey.py` assert on behavior.
  - GUI exposes video options (FPS, codec, resolution) in a sensible way.

---

This roadmap is meant to be **living**. As Phases 1–3 land, you can reprioritize Phases 4–5 or split them into smaller design docs and implementation branches.
