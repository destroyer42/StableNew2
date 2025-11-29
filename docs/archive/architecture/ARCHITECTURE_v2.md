## 2) `docs/ARCHITECTURE_v2.md` (draft)

```markdown
# StableNew – Architecture v2 (Draft)

_Last updated: 2025-11-15 — DRAFT.  
This document describes the **target architecture** for StableNew after the planned refactors._

This is not a perfect reflection of the current code yet; it is the design we are moving toward.

---

## 1. High-Level Overview

StableNew is a **desktop orchestrator** for Stable Diffusion WebUI:

- **GUI layer (Tk/Ttk)**  
  Presents configuration controls, prompt packs, randomization/matrix UI, pipeline controls, logs, and status.

- **Controller & State layer**  
  Coordinates GUI events with pipeline execution; maintains lifecycle state (`IDLE`, `RUNNING`, `STOPPING`, `ERROR`).

- **Pipeline layer**  
  Orchestrates per-run stages:
  `txt2img → img2img → ADetailer → Upscale → Video`.

- **Integration layer (WebUI API client)**  
  Handles HTTP requests, retry/backoff, readiness checks.

- **Configuration & Presets layer**  
  Merges presets, GUI state, prompt packs, and runtime overrides into concrete pipeline configs.

- **Randomization & Matrix layer**  
  Applies wildcard/randomization rules and prompt matrices, then sanitizes prompts before sending them to WebUI.

- **Logging & Manifests layer**  
  Creates run directories, writes manifests and CSV rollups, and supports future analytics.

- **(Planned) Job & Queue layer**  
  Models runs as jobs and supports queued and distributed execution.

---

## 2. Layers & Modules

### 2.1 GUI Layer

**Primary responsibilities:**

- Render controls and panels.
- React to user interactions (clicks, selections, text edits).
- Display progress, logs, and status.

**Key modules (target organization):**

- `src/gui/main_window.py`  
  - Mediator for the GUI; manages window shell, menu, and panel layout.
  - Wires high-level events (Run, Stop, Preview, Exit) to the controller.

- `src/gui/config_panel.py`  
  - Model/preset/VAEs/upscale-specific controls.
  - Basic SDXL/Flux/preset selection.

- `src/gui/pipeline_controls_panel.py`  
  - Controls for Run, Stop, loop counts, batch sizes, etc.

- `src/gui/prompt_pack_panel.py`  
  - Pack selection, loading/saving, pack metadata display.

- `src/gui/advanced_prompt_editor.py`  
  - Rich editor for pack contents, global negative prompt, `name:` metadata, etc.

- `src/gui/matrix_panel.py` (planned explicit module)  
  - Matrix base prompt and slots UI (purely UI, no logic about pipeline internals).

- `src/gui/adetailer_config_panel.py`  
  - Config for ADetailer stage (models, thresholds, prompts).

- `src/gui/stage_chooser.py`  
  - Non-blocking modal for per-image stage selection after `txt2img`.

- `src/gui/log_panel.py`  
  - Log text widget, filtering, and basic diagnostics.

- `src/gui/state.py`  
  - Shared GUI state representation and signals (e.g., lifecycle events).

- `src/gui/theme.py` (optional)  
  - Colors, fonts, spacing, dark mode theming.

**Threading contract:**

- Tkinter widgets are only created and updated on the **main thread**.
- Background work (API calls, IO-heavy operations) occurs in worker threads.
- Any GUI updates from worker threads are marshaled via `root.after(...)`.

---

### 2.2 Controller & State

**Responsibilities:**

- Interpret GUI events and translate them into pipeline operations.
- Own the **lifecycle state** of the application:
  - `IDLE`, `RUNNING`, `STOPPING`, `ERROR`, etc.
- Manage cancellation tokens and ensure cooperative cancellation.
- Coordinate one-or-many runs (future: jobs/queue).

**Key concepts:**

- **Controller object** (e.g., `PipelineController` or `AppController`):
  - Bound to GUI events (Run, Stop, Preview, Exit).
  - Owns a reference to the pipeline executor.
  - Handles one run at a time in v2 (future: jobs).

- **State model** (in `src/gui/state.py`):
  - Stores current status (string or enum).
  - Optionally stores current run/job ID, progress counts, or stage.

**Interactions:**

- GUI → Controller:
  - “User clicked Run” → validate inputs → start new run.
  - “User clicked Stop” → set cancel token and update state.

- Controller → GUI:
  - Progress updates (image count, stage).
  - Failure or completion events (e.g., show toast/log message, reset buttons).

---

### 2.3 Pipeline Layer

**Responsibilities:**

- Execute a single run from configuration and prompts.
- Coordinate stage-level functions:
  - `run_txt2img`, `run_img2img`, `run_adetailer`, `run_upscale`, `run_video`.

- Maintain a clear distinction between:
  - **Logical pipeline** (what stages conceptually exist and in what order).
  - **Execution pipeline** (which stages run in this run, given config).

**Key module:**

- `src/pipeline/executor.py`

**Target shape:**

- A single entrypoint per run, e.g.:

  ```python
  def run_pipeline(run_config: RunConfig, controller: PipelineController, logger: StructuredLogger, cancel_token: CancelToken) -> None:
      ...
Stage-specific helpers:

python
Copy code
def run_txt2img(...): ...
def run_img2img(...): ...
def run_adetailer(...): ...
def run_upscale(...): ...
def run_video(...): ...
Each helper:

Accepts config and input image(s).

Writes manifests via the logger.

Checks cancel token at safe points.

Returns paths or metadata to the next stage.

2.4 Integration Layer (WebUI API Client)
Responsibilities:

Encapsulate HTTP calls to Stable Diffusion WebUI.

Provide readiness checks and exponential backoff.

Handle errors and return structured errors to the pipeline.

Key module:

src/api/client.py

Capabilities:

API readiness check:

Pings /sdapi/v1/sd-models or similar endpoints.

Handles connection failures with backoff and clear error messages.

Stage-specific calls:

txt2img, img2img, upscale, possibly extra-scripts for ADetailer.

Build payloads from sanitized prompts and config structures.

Error handling:

Distinguish between transient and fatal errors.

Surface messages and codes up to the pipeline and controller.

2.5 Configuration & Presets Layer
Responsibilities:

Merge configuration from:

Defaults (global preset for repo).

Model/preset selection.

Prompt packs (additional fields, such as name: metadata).

GUI overrides (sliders, checkboxes).

Produce:

python
Copy code
class RunConfig:
    # core run-level settings
    txt2img: Txt2ImgConfig
    img2img: Img2ImgConfig
    upscale: UpscaleConfig
    video: VideoConfig
    api: APIConfig
    randomization: RandomConfig
    matrix: MatrixConfig
Key modules:

src/utils/config.py

presets/*.json

Testing:

tests/test_config_passthrough.py asserts that:

Each field expected by the API is correctly passed through.

No unexpected “silent drops” of config.

Any newly added config is either allowed to differ or explicitly tested.

2.6 Randomization & Matrix Layer
Responsibilities:

Interpret randomization and matrix settings.

Generate concrete prompts from tokenized input (packs + base prompt + slots).

Ensure that what WebUI receives is a clean, token-free prompt.

Key modules:

src/utils/randomizer.py

Possibly src/pipeline/variant_planner.py for matrix/fanout logic.

GUI components in matrix_panel.py and randomization UI.

Design principles:

Separation of concerns:

GUI: only collects and displays settings.

Randomization/matrix layer: pure functions.

Sanitization:

A sanitize_prompt() helper ensures no [[slot]] or __wildcard__ tokens
reach client.txt2img().

Tests:

Confirm parity between:

Preview payload prompts.

Actual pipeline prompts.

Ensure randomization behaves as expected:

“Random per prompt” vs “fanout” vs “rotate” modes.

2.7 Logging & Manifests
Responsibilities:

Manage per-run directory structure:

output/run_YYYYMMDD_HHMMSS/

Write:

Image manifests (JSON) per stage.

Optional CSV rollups summarizing the run.

Key modules:

src/utils/file_io.py (atomic writes, path helpers)

Logger/structured logger module (exact path may vary, but conceptually StructuredLogger).

Design:

Pipeline calls logger with simple, structured data:

Prompts, configs, outputs, timings, retry info.

Logger writes:

One manifest per produced image/stage.

Optional index files or rollups.

2.8 Job & Queue Layer (Planned)
Responsibilities:

Represent each run as a job with:

ID, name, timestamps.

Config snapshot.

Run directory / manifest paths.

Optionally support:

Multiple jobs queued.

Distributed execution across nodes.

Key idea:

GUI will evolve from “Run one pipeline” to “Submit jobs to a queue”.

The pipeline executor will remain the engine for executing a single job.

3. Threading, Cancellation, and Lifecycle
3.1 Thread Model
Tk main loop runs on the main thread.

Pipeline runs in a worker thread per run.

Async operations (model refresh, samplers, upscalers) also use worker threads.

Rules:

No widget updates from worker threads.

All such updates must use root.after(...) to schedule on the main thread.

Long-running loops in the pipeline must periodically check the cancel token.

3.2 Cancellation
A CancelToken (or equivalent primitive) is created per run.

STOP button:

Sets the cancel flag.

GUI updates state to STOPPING.

Pipeline stages:

Honor the cancel flag between images and between stages.

Perform best-effort cleanup before returning.

3.3 Lifecycle / States
Target states:

IDLE

RUNNING

STOPPING

ERROR

COMPLETED (optional, collapsed into IDLE + success info)

Transitions should be:

Explicit and tested.

Owned by the controller, not scattered across panels.

4. Filesystem Layout
High-level directories:

src/ – Application code:

gui/ – GUI components and state.

pipeline/ – Pipeline execution logic.

api/ – WebUI API client.

utils/ – Config, randomization, logging, IO helpers.

tests/ – Unit and integration tests:

tests/gui/

tests/pipeline/

tests/config/

presets/ – JSON pipeline presets.

packs/ – Prompt packs (TXT/TSV).

output/ – Generated images, manifests, videos.

docs/ – Architecture, history, roadmap, AI workflow.

docs/archive/ – Historical or superseded docs.

5. Testing Strategy
5.1 Unit Tests
Small modules: config merging, randomizer functions, client payloads.

Run quickly and frequently.

5.2 GUI Tests
Focus on:

Lifecycle (Run/Stop/Exit).

Matrix and randomization UI wiring.

Headless where possible; no join() on worker threads from tests.

5.3 Pipeline “Journey” Tests
End-to-end tests using mocks/stubs of WebUI.

Validate:

Stage ordering.

Manifest writing.

Cancel behavior.

Retry/backoff semantics.

5.4 TDD Expectations
Failing test first for any non-trivial change.

Tests updated as behavior evolves.

Critical files (high-risk list) must always be protected by tests.

6. Evolution Notes
The original ARCHITECTURE.md is treated as historical and is moved to docs/archive/ARCHITECTURE_legacy.md.

This v2 document is a living design:

Update it as Phase 2 (stability) and Phase 3 (GUI overhaul) land.

Keep diagrams and examples in sync with code.

When in doubt, code, tests, and this document should agree. If they don’t, update this document as part of the same PR that changes behavior.