
# StableNew – Current-State Architecture Brief (v2.6 Transition)

## Executive Summary

StableNew is a **PromptPack-driven orchestration platform for Stable Diffusion workflows**.  
It converts structured PromptPack configurations into reproducible generation jobs executed through a queue-based pipeline.

Core architecture principles:

1. PromptPack-first workflow design
2. Canonical job representation using **NormalizedJobRecord (NJR)**
3. Controller-mediated orchestration
4. Deterministic pipeline building
5. Queue-based asynchronous execution

The repository currently represents a **mature but evolving architecture**, with major subsystems implemented while the learning and video pipelines continue to mature.

---

# High-Level Architecture

Core execution flow:

PromptPack → AppStateV2 → Controllers → Pipeline Builder → NJR → Queue → Runner → Stable Diffusion → Outputs → History → Learning

StableNew therefore functions as a **workflow orchestration system layered on top of Stable Diffusion**, not merely a GUI frontend.

---

# Major Subsystems

## GUI Layer

Location:
src/gui/
src/gui_v2/

Responsibilities:

- PromptPack selection
- pipeline configuration
- queue monitoring
- preview and output browsing
- job history browsing
- logging / diagnostics

The GUI is **purely a control interface**. Execution logic resides in controllers and services.

---

## Application State

AppStateV2 stores runtime configuration including:

- active PromptPack
- pipeline configuration
- selected models
- queue state
- runtime parameters

Design rule:

GUI modifies state → Controllers read state → Pipeline built from state

---

## Controller Layer

Location:
src/controller/

Controllers orchestrate interactions between the GUI, pipeline, queue, and services.

Key controllers include:

- AppController
- PipelineController
- JobService
- ExecutionController
- HistoryController
- LearningController

Controllers enforce **architectural separation between UI and execution logic**.

---

## Pipeline Builder

Location:
src/pipeline/

Primary component:

JobBuilderV2

Responsibilities:

- Resolve PromptPack parameters
- Assemble pipeline configuration
- Generate deterministic execution plans
- Produce canonical **NormalizedJobRecord** objects

The builder is the **only valid job creation path**.

---

## Normalized Job Record (NJR)

The NJR is the canonical job definition used throughout the system.

It contains:

- prompts
- model selections
- sampler configuration
- seeds
- pipeline stages
- output metadata

All downstream subsystems operate exclusively on NJRs.

---

## Queue System

Location:
src/queue/

Responsibilities:

- asynchronous job scheduling
- batch execution
- job prioritization
- progress monitoring

Queue-based execution enables large PromptPack batch generation runs.

---

## Pipeline Runner

Location:
src/pipeline/runner

Runner responsibilities:

- executing NJR jobs
- invoking Stable Diffusion APIs
- running pipeline stages

Typical current generation pipeline:

txt2img → img2img (ADetailer) → final upscale

This pipeline replaced older flows that relied heavily on refiner and hires-fix stages.

---

## History & Replay System

Location:
src/history/

Capabilities:

- store generation metadata
- preserve NJR snapshots
- replay previous runs

Replay mechanism:

History Snapshot → NJR → Queue → Runner

This enables **fully reproducible generation workflows**.

---

## Learning System (Partially Implemented)

Location:
src/learning/

Goal:

Use generation outcomes and user review feedback to improve future generation quality.

Planned capabilities:

- review datasets
- experiment tracking
- scoring systems
- recommendation engine

---

## Video Generation (Under Construction)

Location:
src/video/

Target capabilities:

- AnimateDiff pipelines
- Stable Video Diffusion workflows
- clip generation pipelines

This subsystem extends the same **NJR + queue execution model** used for images.

---

## Image Editing / Reprocess (Planned)

Planned features include:

- reprocess tab for modifying previous outputs
- targeted editing workflows
- canvas-based object removal or modification

These will likely integrate into the same pipeline architecture via modified NJRs.

---

# External Integrations

Primary integration:

Stable Diffusion WebUI API

Location:
src/api/

Capabilities include:

- generation requests
- process lifecycle management
- GPU resource monitoring
- result retrieval

---

# Data Flow

## Generation

PromptPack  
→ JobBuilderV2  
→ NormalizedJobRecord  
→ Queue  
→ Runner  
→ Stable Diffusion  
→ Output Images  
→ History Storage

## Replay

History Snapshot  
→ NJR Reconstruction  
→ Queue  
→ Runner

## Learning

Output Review  
→ Dataset Capture  
→ Experiment Tracking  
→ Recommendation Updates

---

# Test Architecture

Location:
tests/

The repository includes a large automated test suite including:

- pipeline unit tests
- queue tests
- GUI smoke tests
- history/replay tests
- end-to-end journey tests

---

# Architectural Strengths

- Strong canonical job format (NJR)
- Clean separation of UI, controllers, and execution
- Deterministic pipelines via PromptPack + JobBuilder
- Reproducible experimentation via history + replay
- Extensible architecture for video and learning systems

---

# Transition Areas

Current architectural transition focus areas:

- full NJR-only execution paths
- maturation of the learning subsystem
- expansion of video generation capabilities
- future editing workflows (canvas/object editing)

---

# Overall System Definition

StableNew can be best described as:

**A PromptPack-driven Stable Diffusion workflow orchestration platform designed for reproducible generation pipelines, batch processing, and extensible AI-assisted experimentation.**
