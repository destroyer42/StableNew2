# StableNew – History & Context Summary (v1.0)

_Last updated: 2025-11-15_

This document gives a concise but opinionated history of StableNew so new work can start with clear context instead of re-discovering old decisions or bugs.

It’s meant to answer:

- What is StableNew trying to be?
- How did we get to the current architecture?
- Where did the brittleness come from?
- What prior work do we *keep* vs *retire*?

---

## 1. Purpose & Vision

StableNew is a local orchestration layer around **Stable Diffusion WebUI (A1111)** that aims to:

- Provide a **single, repeatable pipeline**:
  `txt2img → img2img → ADetailer → Upscale → (Video)`
- Make **prompt pack–driven workflows** first-class, especially medieval/fantasy themes.
- Capture **structured logs and manifests** for every run (JSON + CSV rollups).
- Offer a **GUI that is powerful but understandable**, hiding WebUI complexity behind presets, packs, and a stateful pipeline controller.
- Enable future **distributed / multi-node rendering**, job queues, and video output.

The repo evolved through many iterations to support new pipeline features, randomization, manifests, and better GUI controls, but accumulated technical debt and brittle behaviors.

---

## 2. Early Architecture & Core Concepts

The early StableNew architecture (captured in the archived `ARCHITECTURE.md`) followed a clean conceptual model:

- **GUI (Tkinter)** – user-facing controls, configuration panels, and logs.
- **Pipeline Executor** – Python code coordinating calls to SD WebUI:
  - `txt2img`, `img2img`, `upscale`, and optional `video` stage.
- **Config Manager** – merge defaults, presets, pack overrides, and runtime options.
- **State Manager** – track “IDLE / RUNNING / STOPPING / ERROR” and drive buttons.
- **Structured Logger** – create run directories, manifests, and CSV summaries.
- **Cancellation Token** – cooperative cancel, checked at safe points in the pipeline.

The pipeline tests (`test_pipeline_journey.py` and `test_config_passthrough.py`) document the intended behavior:

- **Full journey** across stages (including skip paths).
- **Config pass-through** from composite config → API payloads.
- **Directory layout and manifest structure**.
- **Cooperative cancel**, retry behavior, and manifest consistency.

Over time the implementation drifted from the ideal, especially in:

- Tkinter state management
- Threading and async refresh
- GUI layout sprawl
- Upscale and tiling defaults
- Randomization/matrix complexity in the GUI

---

## 3. Prompt Packs, Randomization, and Matrix Evolution

StableNew leaned heavily into structured prompt workflows:

- **Prompt packs** (TXT/TSV, medieval heroes, beasts, castles, etc.).
- **Presets** for SDXL / Juggernaut / Medieval realism vs fantasy.
- A flexible **randomization system**:
  - Search/replace rules (`person => man | woman | child | elder`).
  - Wildcards (`__mood__`, `__weather__`, etc.).
  - Prompt matrix slots (`[[time]]`, `[[location]]`).

Key iterations:

- Introduction of a **Randomization Example preset** and pack:
  - `presets/randomization_example.json`
  - `packs/randomization_test.txt`
  - `presets/RANDOMIZATION_EXAMPLE_README.md`
- A **structured Prompt Matrix UI**:
  - Base prompt field with `[[Slot]]` markers.
  - Dynamic rows per slot (name + values + add/remove).
  - Legacy raw text view for advanced users.
- Config structure evolved to include `matrix.base_prompt`, `slots`, `raw_text`.

The randomization/matrix behavior was later unified with the live pipeline via:

- **PR9 – Randomization Refinement & Prompt Sanitization**
  - Added `sanitize_prompt()` in `main_window` to remove raw `[[matrix]]` and `__wildcard__` tokens before sending to WebUI.
  - Ensured **Preview Payload** (dry-run) and actual pipeline use the same code path.
  - Logged matrix configuration (mode, slots, limits) for visibility.

These changes significantly improved consistency, but increased coupling between GUI, randomizer, and pipeline.

---

## 4. Structured Logging, Manifests, and Journey Tests

StableNew evolved a solid data trail:

- Per-run directory under `output/run_YYYYMMDD_HHMMSS/` with:
  - Stage folders: `txt2img/`, `img2img/`, `upscaled/`, `video/` (planned).
  - `manifests/` with one JSON manifest per stage/image.
  - Optional CSV rollups summarizing runs.
- The **StructuredLogger** handles directory creation, manifest writing, and rollups.

`test_pipeline_journey.py` and the **Journey Test Coverage Checklist** encode expected behavior:

- Multi-stage runs with optional stages disabled.
- Video integration via a `VideoCreator` abstraction (mocked in tests).
- Manifest shape and timestamp ordering.
- CSV header expectations.
- Retry/backoff hooks.
- Prompt pack permutations and persistent negative prompt safety.
- Cooperative cancel/resume and clean manifest behavior.

These tests represent the *intended* “high-level contract” of StableNew, even when parts of the code diverged.

---

## 5. GUI Evolution, Threading Fixes, and Hangs

The GUI is powerful but became increasingly complex:

- **Main window** grew into a god-object:
  - Configuration panel, pipeline controls, prompt pack list, advanced prompt editor, randomization/matrix UI, log panel, and API status hooks.
- Nested frames and scrollbars made layout brittle and hard to resize.
- ADetailer, StageChooser, and Randomization further increased coupling.

Several stabilizing efforts:

- **Threading Fix for Model/Sampler Refresh**:
  - Moved widget updates out of background threads into main thread using `root.after(...)`.
  - Introduced async `*_async()` variants for models, VAE, upscalers, schedulers.
- **BUG_FIX_GUI_HANG_SECOND_RUN** and related docs:
  - Investigated hangs/freeze when running a second pipeline in the same session.
  - Documented lifecycle and state-machine failures.
- **PR10 – Single Instance & Reliable Exit**:
  - Single-instance lock via port binding (47631) in `main.py`.
  - `_graceful_exit()` persists preferences, stops the controller, tears down Tk, and calls `os._exit(0)` if necessary.
  - Eliminated zombie `python.exe` processes after closing the GUI.

Despite these, the GUI still suffers:

- Scrollbars inside scrollbars.
- Panels that don’t resize well.
- Controls and buttons scattered without a coherent layout system.
- Coupling between GUI, state, pipeline, and controller that makes refactors risky.

---

## 6. Testing & Configuration Integrity

StableNew invested in testing to keep behavior consistent:

- **Config Pass-Through Validation** (`test_config_passthrough.py`):
  - Validates that configuration parameters make it all the way to API payloads.
  - Warns on missing parameters or unexpected changes (except allowed fields like `prompt` / `negative_prompt`).
  - Describes maintenance rules: update expected lists whenever new config fields are added.
- **GUI tests** (API status, matrix UI, threading, etc.) exercise:
  - Thread-safe async refresh.
  - Matrix UI add/remove/load/save workflows.
  - Prompt sanitization.

However:

- Not all newly added behaviors have corresponding tests.
- Some tests encode expectations the code doesn’t fully meet yet (e.g., retry/backoff).
- TDD discipline has been inconsistent: changes sometimes shipped before tests were updated.

---

## 7. AI-Assisted Workflows (GPT, Codex, Copilot)

StableNew embraced AI as part of its development workflow:

- **CODEX_SOP** and **Codex Autopilot Workflow**:
  - GPT (ChatGPT) is the architect: designs, diffs, and explanations.
  - Codex/Copilot Chat is the executor: applies diffs exactly, runs tests, posts outputs.
  - Strict rules: no freestyling refactors; small, single-purpose PRs; GUI/pipeline treated as high-risk files.
- **Codex AutoFix GitHub Action**:
  - On `/codex-autofix`, CI failure output is sent to a Codex model.
  - Codex returns a candidate diff and fix explanation as a PR comment.
- **Custom agents** (Controller, Refactor, etc.) encoded as GitHub custom agents:
  - Controller: plans PRs, defines file boundaries, and delegates.
  - Refactor agent: non-behavior-changing cleanup and best practices.

These tools are powerful but contributed to:

- Multiple overlapping instruction docs.
- Different agent flavors and slightly divergent rules.
- Confusion about which document is “source of truth” for AI behavior.

The new project will consolidate these into a **single, versioned AI Workflow** with clear roles.

---

## 8. Repo Reorganization & Documentation Clutter

Over time, the repo grew:

- Multiple READMEs and instruction files.
- Docs scattered under root, `/docs/`, `/archive/`, and sprint-specific files.
- Some docs partially superseded others, but older versions stayed in place.
- `ARCHITECTURE.md` now lives under an archive path and is **no longer authoritative**.

A recent **Project Reorganization Summary** and `_toc.md` attempted to bring order, but the next step is more aggressive:

- Root should contain **only absolutely necessary files**.
- All docs consolidated into `/docs/` with versioned filenames.
- Archived docs clearly moved under `/docs/archive/`.
- AI/agent instructions unified and versioned.

This history sets up the first roadmap phase: a *repo hygiene and docs consolidation sprint*.

---

## 9. Why Start a New Project Context

Given:

- Accumulated technical debt in GUI and pipeline coordination.
- Brittleness (hangs, thread issues, second-run problems).
- Documentation sprawl and conflicting agent instructions.
- The desire to introduce **distributed workloads**, **video**, and a **modern GUI**.

It makes sense to:

- Start a **fresh project context** (new ChatGPT “Project” workspace).
- Keep the code repo, but treat this new project as a **clean mental model**.
- Use this summary + the roadmap + known issues as the anchor.
- Enforce TDD and AI workflow discipline from the start.

The rest of the docs (Known Bugs, Roadmap, Agents, and Next Features) build on this history and define how you’ll move StableNew from “powerful but brittle” to “stable, test-driven, and ready to scale.”
