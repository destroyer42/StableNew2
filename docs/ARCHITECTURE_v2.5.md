# StableNew Architecture v2  
_Layered, Testable, Cluster-Aware Design_

This document supersedes **ARCHITECTURE_v2_Translation_Plan.md** and becomes the authoritative architecture reference for V2.

---

## 1. High-Level Overview

StableNew v2 is organized into **strict layers**:

- **GUI Layer (V2)** – Tk/Ttk based UI (StableNewGUI, V2 panels & stage cards, status bar).
- **Controller Layer** – AppController / PipelineController: lifecycle, CancelToken, config assembly, learning hooks.
- **Pipeline Layer** – PipelineRunner, PipelineConfig, stage executor logic.
- **Randomizer & Learning Layer** – pure-function utilities for variant planning and learning plans/records.
- **Cluster & IO Layer (future)** – job queue, worker registry, schedulers, persistence.
- **API Layer** – SD WebUI client and related HTTP/JSON integration.
- **Logging Layer** – StructuredLogger and atomic IO writers.

Data flows strictly **downward**, while events and progress propagate **upward** via callbacks/events.

### 1.1 Top-Level Package Layout

To support this layered design, the codebase is organized into these top-level packages:

- `src/gui/`  
  Tkinter GUI: windows, panels, widgets, dialogs.

- `src/controller/`  
  Application and pipeline controllers (no Tk imports).

- `src/pipeline/`  
  Core pipeline runner and building blocks (stateless, testable).

- `src/api/`  
  Stable Diffusion WebUI HTTP client and related helpers.

- `src/learning/`  
  Learning v2: plan/execution/record data models, builders, writers, runners.

- `src/utils/`  
  Logging, file I/O, config, and other shared utilities.

- `tests/`  
  Mirrors the above structure (`tests/gui/`, `tests/pipeline/`, etc.).

### 1.2 Dependency Direction (Clean Architecture)

Allowed dependency directions (lower → higher):

- `utils` → (no upward deps)
- `api` → `utils`
- `pipeline` → `api`, `utils`
- `learning` → `pipeline`, `utils`
- `controller` → `pipeline`, `learning`, `api`, `utils`
- `gui` → `controller`, `utils` (but **not** `pipeline` or `api` directly)

**Forbidden patterns:**

- GUI importing `src/pipeline/*` directly.
- GUI importing `requests` or other HTTP clients directly.
- Controllers importing `gui`.
- Circular imports (e.g., controller ↔ gui ↔ pipeline).

If existing legacy code violates these rules, new work should move it toward this model.

---

## 2. GUI Layer (V2)

### 2.1 StableNewGUI

Responsibilities:

- Construct the **V2 layout**:
  - SidebarPanelV2
  - PipelinePanelV2 (with per-stage cards)
  - RandomizerPanelV2
  - PreviewPanelV2
  - StatusBarV2
- Wire user interactions (Run, Stop, select packs, toggle stages).
- Display progress, ETA, and error messages via StatusBarV2.
- Surface learning and randomization options without exposing low-level details (e.g., no raw JSON in the UI).

Must NOT:

- Execute pipeline stages directly.
- Make direct HTTP calls to SD WebUI.
- Write files except via controlled save dialogs (and even then, using helpers).

### 2.2 Panels and Stage Cards

- **PipelinePanelV2**
  - Hosts stage cards:
    - Txt2ImgStageCard
    - Img2ImgStageCard
    - UpscaleStageCard
    - (Future: ADetailerStageCard, RefinerStageCard, VideoStageCard).
  - Defines `load_from_config()` / `to_config_dict()` helpers for each card.
  - Cooperates with StableNewGUI to produce an effective **pipeline config delta**.

- **RandomizerPanelV2**
  - Provides UX for:
    - Variant mode (off / sequential / rotate / random).
    - Matrix fields (e.g., styles, LoRAs, embeddings).
    - Fanout (images per variant).
  - Shows a live **“Total variants”** label.

- **StatusBarV2**
  - Handles:
    - Status text (Idle / Running / Error / Completed).
    - Progress bar (0–100%).
    - ETA display.
  - Responds to controller callbacks to keep UI and pipeline lifecycle aligned.

---

## 3. Controller Layer

### 3.1 AppController / PipelineController

Responsibilities:

- Own the **CancelToken**, lifecycle (IDLE, RUNNING, STOPPING, ERROR), and worker threads.
- Validate GUI and configuration inputs before launching a run.
- Compose **PipelineConfig** from:
  - Default config (ConfigManager).
  - GUI overrides (PipelinePanelV2 stage cards).
  - Randomizer-selected variant config (via RandomizerAdapter).
- Invoke  
  `PipelineRunner.run(config, cancel_token, log_fn, optional_learning_hooks)`.
- Bridge **Learning**:
  - Provide the LearningRunner/adapter stubs and later production integrations.
  - Ensure LearningRecords can be produced without GUI coupling.

Must NOT:

- Contain Tk/Ttk code.
- Make assumptions about specific SD models; all such details belong in config or API layers.

### 3.2 Lifecycle and Cancellation

- Controller transitions:
  - IDLE → RUNNING when a valid config is launched.
  - RUNNING → IDLE when pipeline completes successfully.
  - RUNNING → ERROR on fatal pipeline errors.
  - RUNNING → STOPPING / IDLE when CancelToken is triggered.

- CancelToken checked:
  - Between stages (txt2img, img2img, adetailer, upscale).
  - Within long-running loops when possible (e.g., streaming progress from SD WebUI).

---

## 4. Pipeline Layer

### 4.1 PipelineConfig

- Encapsulates configuration for all stages:
  - txt2img fields (model, VAE, sampler, scheduler, CFG, steps, width, height, etc.).
  - img2img fields (denoising strength, source image, etc.).
  - upscale fields (upscaler, resize factor, tiling parameters).
  - adetailer/refiner fields where applicable.
  - Learning, randomizer, and metadata (e.g., run id, prompt pack id).

### 4.2 PipelineRunner

Responsibilities:

- Execute stages in order, based on PipelineConfig and enabled flags.
- Invoke **SD WebUI client** with appropriate payloads per stage.
- Aggregate results (images, logs) and forward progress information back to controller.
- Emit **LearningRecords** if a learning writer/callback is configured.

Must:

- Respect CancelToken between and during stages where practical.
- Emit structured logs and stage boundaries.

---

## 5. Randomizer & Learning Layer

### 5.1 Randomizer

Components:

- `src/utils/randomizer.py`
  - Matrix parsing and expansion.
  - Modes: off, sequential, rotate, random.
  - Pure functions for planning and applying variants.

- `src/gui_v2/randomizer_adapter.py`
  - Converts GUI panel options into randomizer inputs.
  - Computes variant counts for display.
  - Builds variant plans and **per-variant config overlays**.
  - Guarantees preview/pipeline parity.

Design Principles:

- No GUI imports from randomizer core.
- Deterministic behavior for a given seed/config.
- Extensive tests for matrix semantics and fanout.

### 5.2 Learning System

Components:

- **LearningPlan / LearningRunStep / LearningRunResult** – describe a learning run (e.g., “vary steps from 15 to 45”).
- **LearningRunner** – orchestrates planned runs, tracks progress, collects per-variant metadata.
- **LearningFeedback** – transforms user ratings into normalized signals.
- **LearningRecord** – atomic record of a single run (config + outputs + ratings + context).
- **LearningRecordWriter** – safe writer for learning records (JSONL, atomic file updates).

Integration Points:

- PipelineRunner accepts learning hooks so that any pipeline run (interactive or batch) can yield a LearningRecord.
- Controller provides an opt-in learning runner and will later expose user-triggered Learning Runs via GUI V2.
- Future external LLMs can ingest LearningRecords to propose new presets.

---

## 6. Cluster & IO Layer (Vision Aligned with C3)

Although not fully implemented yet, the architecture reserves a dedicated layer for cluster features.

### 6.1 Job Model

- A **Job** is defined as:
  - A prompt pack / prompt.
  - A fully specified PipelineConfig (possibly with multiple variants from the randomizer).
  - Metadata: learning enabled? randomizer used? one-off run vs batch.
  - Priority and deadlines (e.g., interactive vs overnight).

### 6.2 Queue Manager

- Central in-memory (later persistent) queue.
- Responsible for:
  - Accepting jobs from GUI/CLI.
  - Assigning jobs to worker nodes based on capabilities and load.
  - Tracking job state (queued, running, completed, failed).

### 6.3 Worker Agents

- Lightweight processes running on LAN nodes:
  - Expose capabilities: GPU count, VRAM, baseline throughput.
  - Register with queue manager and request work.
  - Execute jobs using SD WebUI or equivalent backends on that node.
  - Report logs, outputs, and basic metrics back.

### 6.4 Scheduler (C3)

- **Capability + load aware**:
  - Heavier jobs prefer higher-VRAM / more capable nodes.
  - Multiple jobs can be pipelined across nodes if capacity allows.
- Interacts with Learning & Randomizer:
  - Large learning or randomization batches can be partitioned across nodes.
  - Interactive jobs can remain on the “local” machine to reduce latency.

---

## 7. API Layer

- **SD WebUI client** encapsulates:
  - Base URL, auth (if any), and endpoints for txt2img, img2img, upscale, etc.
  - Retry/backoff and error handling.
- Must be fully mockable for tests.
- GUI must not directly call this client; it always goes through controller/pipeline.

---

## 8. Logging & IO

- **StructuredLogger** is the single writer of manifests and structured logs.
- LearningRecordWriter is the single writer of learning records.
- All writes are **atomic** (write-temp-then-rename).
- Paths and directory layouts are centrally configured (no scattering literals).

---

## 9. Testing and Safety Expectations

- Every non-trivial module should have unit tests.
- GUI V2 tests:
  - Layout skeleton.
  - Button wiring.
  - Config roundtrips.
  - StatusBarV2 progress & ETA.
  - Randomizer interaction.
- Learning tests:
  - Plan building, runner hooks, record serialization.
- Cluster tests (when implemented):
  - Queue behavior, worker registration, basic scheduling decisions (dry-run).

- Safety tests:
  - Ensure `utils/randomizer` imports never drag Tk/GUI.
  - Ensure Codex or other agents cannot silently modify forbidden modules (enforced via guard tests and scripts).

---

## 10. Migration and Extension Rules

- New work should target V2 modules only (V1 is legacy).
- When in doubt:
  - Put presentation in GUI.
  - Put lifecycle in controller.
  - Put execution in pipeline.
  - Put configuration transforms/randomization/learning in pure utils/learning modules.
- Keep changes small and well-scoped; back them with tests before touching core behavior.

---

## 11. Pipeline Execution Flow (Happy Path)

1. User configures pipeline in the GUI (prompt pack, sampler, steps, upscale, adetailer, etc.).
2. GUI builds a **pipeline config object** or uses controller helpers to assemble one.
3. `PipelineController` receives that config and calls a headless runner:
   - e.g.,  
     `pipeline_runner.run_full_pipeline(pipeline_config, logger=..., callbacks=...)`
4. `pipeline_runner`:
   - Calls into `src.api.client` to hit A1111 endpoints (txt2img, img2img, upscalers).
   - Applies tiling, safety checks, max image sizes.
   - Emits structured progress / events.
5. Outputs (images, metadata, logs) are returned to the controller.
6. Controller:
   - Updates GUI progress / status via callbacks.
   - Optionally invokes the learning subsystem to record a `LearningRecord`.

---

## 12. Learning v2 Execution Flow (Headless)

1. A **LearningPlan** describes:
   - Stages, each with config variants (e.g., sampler variants, CFG sweeps).
   - Optional conditions (stop early on failure, etc.).
2. A **LearningExecutionRunner** runs those plans using injected pipeline callables.
3. For each execution:
   - A **LearningRecordBuilder** builds a `LearningRecord`.
   - A **LearningRecordWriter** appends to a JSONL file atomically.
4. Controllers can query the **last execution result** and records.

Learning is **opt-in** and must never destabilize interactive runs.

---

## 13. Where to Put New Code

- New GUI widgets → `src/gui/`
- New coordination / orchestration logic → `src/controller/`
- New pipeline “stages” (e.g., a new enhancement pass) → `src/pipeline/`
- New SD API endpoints / options → `src/api/client.py` (or submodules)
- New learning metrics / outputs → `src/learning/`
- New cross-cutting helpers → `src/utils/` (only if genuinely shared)

If you’re unsure where something belongs, fall back to:

- Data + transformation logic → `pipeline` or `learning`
- IO/HTTP → `api`
- User interaction → `gui`
- Glue/orchestration → `controller`

---

## 14. Notes For AI Assistants

When refactoring or extending the system:

- Preserve the **layer boundaries**:
  - No Tk imports outside `src/gui/`.
  - No direct HTTP calls from `src/gui/`.
- Respect the **dependency direction** in §1.2.
- Prefer **data classes / config objects** over untyped dicts.
- Avoid making **breaking changes** to public APIs without updating:
  - Tests
  - Relevant docs in `docs/`
  - Any learning or cluster integration that depends on those APIs

When in doubt, propose changes in terms of:

- Which layer you’re modifying
- Which interfaces are affected
- What tests will validate behavior
