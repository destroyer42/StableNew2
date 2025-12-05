ARCHITECTURE_v2.5.md
Canonical Architecture Specification for StableNew V2.5

This document supersedes all previous V2 architectural documents and is the authoritative source of truth.

1. Overview

StableNew V2.5 uses a strict layered architecture separating:

GUI Layer (Tk/Ttk V2 UI)

Controller Layer (AppController, PipelineController)

Pipeline Layer (PipelineRunner, stage execution plan, executor wrappers)

Learning & Randomizer Layer

Queue / Job Execution Layer (SingleNodeJobRunner, JobExecutionController, JobService)

API Layer (Stable Diffusion WebUI Client)

Utilities Layer (logging, config, IO, shared helpers)

Goals

Fully testable pipeline logic, independent of GUI

Deterministic config → plan → executor flow

Expandable to multi-node cluster execution

Clean separation of orchestration vs execution

Clear run-mode semantics (direct, queued)

First-class support for Learning Records and Randomizer Variants

2. Dependency Direction

StableNew enforces Clean Architecture rules:

utils → api → pipeline → learning → controller → gui


Allowed:

Higher layers may depend on lower layers

Lower layers must not depend on higher layers

Forbidden:

GUI importing pipeline or api

Controllers importing GUI

Direct executor calls from GUI

Circular imports between controller ↔ pipeline

3. GUI Layer (V2)

The V2 GUI is a pure presentation layer.

Responsibilities

Draws UI components (tabs, panels, stage cards)

Captures user input (pipeline options, variants, run commands)

Delegates everything operational to AppController

Displays:

Status bar

Progress / ETA

Images & output previews

Learning indicators

No pipeline execution, no HTTP calls

Notable Components

PipelineTabFrame V2
Hosts Txt2Img, Img2Img, Upscale, Refiner, Hires, ADetailer stage cards.

RandomizerPanelV2
Configures variant matrices and calculates total run count.

PreviewPanelV2
Displays images and run summaries.

StatusBarV2
Shows pipeline state transitions and job progress.

4. Controller Layer

The controller layer is the orchestration brain.
It is where GUI → pipeline wiring takes place.

4.1 AppController
Responsibilities

Primary entry point for run commands

Builds run_config metadata:

run_mode ("direct" or "queue")

source (Run / Run Now / AddToQueue)

prompt source / pack id

Calls:

PipelineController.start_pipeline(run_config)

Must NOT

Execute pipeline logic

Call API or executor functions

Interact with Tk directly

4.2 PipelineController

This is the central orchestration engine for V2.5.

Responsibilities

Validate pipeline state

Build PipelineConfig using PipelineConfigAssembler

Construct jobs with full metadata (PR-106)

Submit jobs through:

Direct mode: job_service.submit_direct(job)

Queue mode: job_service.submit_queued(job)

Track:

_active_job_id

_last_run_config

_last_run_result

Stage events, execution plans

Route job execution to PipelineRunner

Key Methods

start_pipeline(run_config=...)
→ decides direct vs queued job execution

_run_pipeline_job(config)
→ the job payload executed by the runner

run_pipeline(config)
→ calls PipelineRunner.run(...)

Hooks:

LearningRecord callbacks

Structured logging

StageExecutionPlan capture (preview, tests)

5. Run Pipeline Path (V2.5)
Canonical sequence

This reflects PR-0114 and is now the official reference.

5.1 Full Flow Diagram
GUI Run Button
     ↓
AppController._start_run_v2()
     ↓
PipelineController.start_pipeline(run_config)
     ↓
PipelineConfigAssembler.build_from_gui_input()
     ↓
PipelineController._build_job()
     ↓
┌─────────────── Run Mode ────────────────┐
│ if direct → job_service.submit_direct   │
│ if queue  → job_service.submit_queued   │
└──────────────────────────────────────────┘
     ↓
JobExecutionController / QueueExecutionController
     ↓
SingleNodeJobRunner
     ↓
PipelineController._run_pipeline_job(job)
     ↓
PipelineController.run_pipeline(config)
     ↓
PipelineRunner.run(config)
     ↓
Executor → SD WebUI HTTP API
     ↓
Results (images, metadata, events)
     ↓
PipelineController.record_run_result(...)
     ↓
GUI updates (StatusBar, Preview, Last Run)

6. Pipeline Layer
6.1 PipelineConfig

Typed configuration container

Holds parameters for:

txt2img

img2img

upscalers

ADetailer

Refiners

Hires fix

Includes:

metadata (run id, prompt pack id, timestamps)

learning-specific metadata

randomizer metadata

6.2 PipelineRunner

Core responsibilities:

Compute StageExecutionPlan based on PipelineConfig

For each stage:

Build executor payload

Call executor/SD WebUI client

Aggregate outputs

Emit:

structured logs

stage events

learning events

Return a PipelineRunResult (or dict)

Guarantees

Deterministic execution for given config

Graceful cancellation

Backpressure handling when using queue mode

7. Queue / Job Execution Layer

This layer enables:

direct runs

queued runs

future cluster execution

7.1 JobExecutionController

Owns:

JobQueue

SingleNodeJobRunner

JobHistoryStore

Provides:

submit_pipeline_run(callable)

cancellation

job status callbacks (RUNNING, COMPLETED, FAILED)

7.2 SingleNodeJobRunner

Background thread loop:

Pull next job

Mark RUNNING

Call job payload (→ PipelineController._run_pipeline_job)

Mark COMPLETED / FAILED

Supports:

synchronous run_once(job)

cancellation flag

Runs only one job at a time (V2.5), but scalable to multi-worker nodes.

7.3 JobService

Unified façade used by the PipelineController.

Methods

submit_direct(job)

Synchronously executes job via run_once()

submit_queued(job)

Enqueues job

Ensures runner thread is started

Provides UI/Callback events for:

Job started

Job finished

Job failed

Queue updated

8. Randomizer Layer

Pure functions for:

matrix expansion

sequential / rotate / random modes

deterministic variant planning

Used in:

preview panel

pipeline config assembly

Learning runs (future)

Never interacts with GUI or API.
9. Learning Layer (V2)

Components:

LearningPlan

LearningRunner

LearningRecord

LearningRecordWriter

Integrated via:

PipelineRunner learning callbacks

PipelineController run lifecycle hooks

Design Requirements

Never impede interactive runs

Logging and record writing must be atomic

All record formats must remain backward compatible

10. API Layer

The Stable Diffusion WebUI Client:

Sends HTTP txt2img, img2img, upscale, refiner, hires, adetailer requests

Implements:

retries

timeouts

structured error handling

Must be fully mockable for tests

No GUI dependencies

11. Logging Layer
StructuredLogger

Writes log JSONL and manifest files atomically

Emits:

pipeline start

stage events

errors

completion metadata

LearningRecordWriter

Writes JSONL learning records atomically (temp → rename)

12. Testing Expectations

V2.5 architecture requires comprehensive tests in:

Pipeline tests

StageExecutionPlan correctness

PipelineRunner’s integration through mocked executors

run → direct mode → queue mode parity

Controller tests

start_pipeline behavior

job construction

run mode selection

last-run restore

Queue tests

Job lifecycle transitions

Runner loop correctness

Direct vs queued semantics

GUI tests

wiring only (no pipeline execution)

correct delegation to controllers

13. Migration & Extension Rules

When adding features:

Put code in correct layers:

GUI-only → /src/gui/

Orchestration → /src/controller/

Execution logic → /src/pipeline/

SD WebUI interactions → /src/api/

Learning logic → /src/learning/

Shared helpers → /src/utils/

Hard rule: GUI must never call pipeline or API directly.

14. Official Pipeline Execution Specification (V2.5)

This replaces all older run-path documentation.

1. Run event originates in GUI
2. AppController builds run_config
3. PipelineController builds PipelineConfig
4. PipelineController creates Job
5. JobService executes job (direct or queue)
6. Job payload calls _run_pipeline_job
7. _run_pipeline_job → run_pipeline
8. run_pipeline → PipelineRunner.run
9. PipelineRunner executes StageExecutionPlan
10. Executor builds payloads and calls SD WebUI
11. PipelineRunner aggregates results
12. Controller records results and updates GUI

This is the canonical flow for StableNew.

15. Notes for AI Assistants

Do not modify executor or pipeline core without test coverage.

Do not break stage sequencing or config assembly.

Do not add logic to GUI other than appearance & events.

When modifying controllers:

preserve run_mode behavior

ensure queue and direct paths remain correct

keep start_pipeline the single entry point

Avoid introducing cross-layer dependencies.

Always reference this document before implementing PRs.

End of Document