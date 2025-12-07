#ARCHIVED
> Superseded by docs/ARCHITECTURE_v2.5.md (canonical)

# StableNew Architecture v2  
_Layered, Testable, Cluster‑Aware Design_

This document supersedes **ARCHITECTURE_v2_Translation_Plan.md** and becomes the authoritative architecture reference for V2.

---

## 1. High‑Level Overview

StableNew v2 is organized into **strict layers**:

- **GUI Layer (V2)** – Tk/Ttk based UI (StableNewGUI, V2 panels & stage cards, status bar).
- **Controller Layer** – AppController / PipelineController: lifecycle, CancelToken, config assembly, learning hooks.
- **Pipeline Layer** – PipelineRunner, PipelineConfig, stage executor logic.
- **Randomizer & Learning Layer** – pure‑function utilities for variant planning and learning plans/records.
- **Cluster & IO Layer (future)** – job queue, worker registry, schedulers, persistence.
- **API Layer** – SD WebUI client and related HTTP/JSON integration.
- **Logging Layer** – StructuredLogger and atomic IO writers.

Data flows strictly **downward**, while events and progress propagate **upward** via callbacks/events.

---

## 2. GUI Layer (V2)

### 2.1 StableNewGUI

Responsibilities:

- Construct the **V2 layout**:
  - SidebarPanelV2
  - PipelinePanelV2 (with per‑stage cards)
  - RandomizerPanelV2
  - PreviewPanelV2
  - StatusBarV2
- Wire user interactions (Run, Stop, select packs, toggle stages).
- Display progress, ETA, and error messages via StatusBarV2.
- Surface learning and randomization options without exposing low‑level details (e.g., no raw JSON in the UI).

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
  - Defines load_from_config() / to_config_dict() helpers for each card.
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
  - Randomizer‑selected variant config (via RandomizerAdapter).
- Invoke **PipelineRunner.run(config, cancel_token, log_fn, optional_learning_hooks)**.
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
  - Within long‑running loops when possible (e.g., streaming progress from SD WebUI).

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

- **src/utils/randomizer.py**
  - Matrix parsing and expansion.
  - Modes: off, sequential, rotate, random.
  - Pure functions for planning and applying variants.

- **src/gui_v2/randomizer_adapter.py**
  - Converts GUI panel options into randomizer inputs.
  - Computes variant counts for display.
  - Builds variant plans and **per‑variant config overlays**.
  - Guarantees preview/pipeline parity.

Design Principles:

- No GUI imports from randomizer core.
- Deterministic behavior for a given seed/config.
- Extensive tests for matrix semantics and fanout.

### 5.2 Learning System

Components:

- **LearningPlan / LearningRunStep / LearningRunResult** – describe a learning run (e.g., “vary steps from 15 to 45”).
- **LearningRunner** – orchestrates planned runs, tracks progress, collects per‑variant metadata.
- **LearningFeedback** – transforms user ratings into normalized signals.
- **LearningRecord** – atomic record of a single run (config + outputs + ratings + context).
- **LearningRecordWriter** – safe writer for learning records (JSONL, atomic file updates).

Integration Points:

- PipelineRunner accepts learning hooks so that any pipeline run (interactive or batch) can yield a LearningRecord.
- Controller provides an opt‑in learning runner and will later expose user‑triggered Learning Runs via GUI V2.
- Future external LLMs can ingest LearningRecords to propose new presets.

---

## 6. Cluster & IO Layer (Vision Aligned with C3)

Although not fully implemented yet, the architecture reserves a dedicated layer for cluster features.

### 6.1 Job Model

- A **Job** is defined as:
  - A prompt pack / prompt.
  - A fully specified PipelineConfig (possibly with multiple variants from the randomizer).
  - Metadata: learning enabled? randomizer used? one‑off run vs batch.
  - Priority and deadlines (e.g., interactive vs overnight).

### 6.2 Queue Manager

- Central in‑memory (later persistent) queue.
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
  - Heavier jobs prefer higher‑VRAM / more capable nodes.
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
- All writes are **atomic** (write‑temp‑then‑rename).
- Paths and directory layouts are centrally configured (no scattering literals).

---

## 9. Testing and Safety Expectations

- Every non‑trivial module should have unit tests.
- GUI V2 tests:
  - Layout skeleton.
  - Button wiring.
  - Config roundtrips.
  - StatusBarV2 progress & ETA.
  - Randomizer interaction.
- Learning tests:
  - Plan building, runner hooks, record serialization.
- Cluster tests (when implemented):
  - Queue behavior, worker registration, basic scheduling decisions (dry‑run).

- Safety tests:
  - Ensure utils/randomizer imports never drag Tk/GUI.
  - Ensure Codex or other agents cannot silently modify forbidden modules (enforced via guard tests and scripts).

---

## 10. Migration and Extension Rules

- New work should target V2 modules only (V1 is legacy).
- When in doubt:
  - Put presentation in GUI.
  - Put lifecycle in controller.
  - Put execution in pipeline.
  - Put configuration transforms/randomization/learning in pure utils/learning modules.
- Keep changes small and well‑scoped; back them with tests before touching core behavior.
