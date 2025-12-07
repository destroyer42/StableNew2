#CANONICAL
# StableNew Architecture (v2.5)

---

# Executive Summary (8–10 lines)

StableNew v2.5 provides a unified, predictable, testable pipeline from GUI → Controller → Pipeline Merging → Job Normalization → Queue → Runner → WebUI.  
The architecture eliminates legacy inconsistencies (V1 MainWindow, old job model, V1 runner) and replaces them with modular, well-typed components.  
The heart of the system is the **ConfigMergerV2 → JobBuilderV2 → NormalizedJobRecord** path, enabling consistent job construction regardless of GUI state or randomization.  
All pipeline execution flows through the **Queue-first architecture**, where JobService mediates job state, ordering, execution, and lifecycle.  
This document defines: subsystem responsibilities, data model definitions, execution flow, stage ordering, error handling, and deprecated concepts.  
It also includes a TLDR section for agents/users, detailed diagrams (Mermaid + ASCII), and reconciliation notes from earlier architecture versions.  

---

# PR-Relevant Facts (Quick Reference)

- **Only this document** defines the authoritative StableNew architecture.  
- Canonical pipeline construction path:  
  **RunConfigV2 → ConfigMergerV2 → JobBuilderV2 → NormalizedJobRecord → JobService/Queue → Runner → WebUI**  
- Canonical stage order:  
  **txt2img → img2img → refiner → hires → upscale → adetailer**  
- GUI V2 is panelized; MainWindow V1 architecture is deprecated.  
- Queue-first model: *all executions* flow through JobService except explicit direct mode.  
- Randomizer operates **before job normalization**, never inside the runner.  
- All override behavior must use **StageOverridesBundle** + **ConfigMergerV2 rules**.  
- Agents should ignore any document not marked `#CANONICAL`.  

---

# ============================================================
# 0. BLUF / TLDR — Concise Architecture Summary (Option C Layer)
# ============================================================

This section serves as a *top-of-file quick scan* for humans and LLMs.  
It is intentionally concise and represents the distilled structure of StableNew.

---

## **0.1 High-Level System Overview**

StableNew consists of four major layers:

1. **GUI (V2 Panels + AppStateV2)**  
   - User manipulates pipeline configs, prompt packs, randomizer controls, output settings, and queue.

2. **Controller Layer (PipelineControllerV2 + AppController)**  
   - Central coordinator.  
   - Collects GUI state and transforms it into complete pipeline instructions.

3. **Pipeline Builder Layer**  
   - `ConfigMergerV2`: merges pack configs + stage overrides.  
   - `JobBuilderV2`: expands variants, seeds, batches, and produces *NormalizedJobRecord* objects.

4. **Execution Layer**  
   - `JobService` + `JobQueueV2` manage ordering, auto-run, state transitions.  
   - Runner executes jobs (SingleNodeJobRunner or remote/WebUI).

Everything feeds into the **NormalizedJobRecord**, the canonical representation of a job.

---

## **0.2 TLDR Pipeline Flow Diagram (Mermaid)**

```mermaid
flowchart TD
    GUI[GUI Panels (Pipeline Tab)]
    AS[AppStateV2]
    PC[PipelineControllerV2]
    CM[ConfigMergerV2]
    JB[JobBuilderV2]
    NJR[NormalizedJobRecord]
    JS[JobService / Queue]
    RN[Runner]
    WU[WebUI]

    GUI --> AS --> PC
    PC --> CM --> JB --> NJR --> JS --> RN --> WU
ASCII fallback:
markdown
Copy code
GUI → AppState → PipelineController
      ↓
  ConfigMergerV2 → JobBuilderV2 → NormalizedJobRecord → JobService/Queue → Runner → WebUI
0.3 TLDR Stage Ordering
StableNew guarantees the following pipeline ordering:

txt2img

img2img (optional)

refiner (optional)

hires fix (optional)

upscale (optional)

adetailer (optional)

No PRs, GUI features, or randomization behaviors may alter this ordering.

0.4 TLDR Job Normalization
A job is only valid after it is normalized:
nginx
Copy code
Raw GUI State → Merged Config → Expanded Variants → NormalizedJobRecord
NormalizedJobRecord includes:

Final merged and expanded pipeline config

Fully resolved seed

Batch index and variant index

Output settings

Timestamps

PR-ready config_snapshot

This ensures consistency between GUI preview, queue view, and executed pipeline.

0.5 TLDR Queue Model
All pipeline execution passes through:

nginx
Copy code
JobService → JobQueueV2 → Runner
Queue is responsible for:

Ordering

Adding/removing jobs

(Planned) persistence

Auto-start

Pause/resume

The GUI simply visualizes queue state; it does not implement queue behavior.

0.6 TLDR Randomizer Placement
RandomizerEngineV2 executes before normalization:

nginx
Copy code
MergedConfig → RandomizationPlanV2 → VariantConfigs → JobBuilderV2 normalization
Randomizer never operates inside:

Runner

JobService

WebUI

0.7 TLDR Glossary (Short)
Concept	Meaning
RunConfigV2	Base pipeline config before merging or expansion
StageOverridesBundle	Set of user-chosen override flags + override values
ConfigMergerV2	Merges pack config + overrides into merged pipeline config
JobBuilderV2	Performs variant expansion, batch expansion, seed handling
NormalizedJobRecord	Final job definition used by queue & execution
JobService	Manager of job lifecycle, queue state, execution triggers
RandomizationPlanV2	Structured plan controlling config-level randomization

=================================================================
1. Full Canonical Architecture (Option A — Detailed Specification)
=================================================================
This is the authoritative section for PRs, designs, and agent reasoning.

1. High-Level System Overview
StableNew v2.5 is designed around modular, isolated subsystems:

GUI Layer controls UI and state presentation.

Controller Layer mediates between GUI and pipeline.

Pipeline Builder Layer ensures deterministic job construction.

Execution Layer handles queuing and running jobs.

External Systems (WebUI, model servers, storage) perform the underlying image generation.

Primary design principles:

Determinism

Immutability of normalized jobs

Testability

Strict subsystem boundaries

Canonical flow enforced by architecture

2. GUI Architecture (V2 Panels + AppState)
StableNew V2 GUI is panel-based, contrasting sharply with V1’s monolithic MainWindow.

Components:
Pipeline Tab Panels

CoreConfigPanel

Stage-specific panels (Refiner, Hires, Upscale, ADetailer)

RandomizerPanel

Output/Filename configuration

Prompt Pack selection + preview

PreviewPanelV2

QueuePanelV2

RunControlsPanelV2

AppStateV2
Stores:

Current selections

Override bundles

RandomizationPlanV2

Output settings

Draft job list

Queue view models

GUI must not perform pipeline, merging, or job construction logic.

The Pipeline tab arranges the three primary columns (pack/config sidebar, stage cards, preview/queue + running job) so that each column is rooted inside a single `ScrollableFrame`, keeping column-level scrollbars and consistent card stacking. `MainWindowV2` applies default geometry/minimum-width constants so that all three columns are visible on launch without horizontal clipping.

3. Controller Architecture
3.1 PipelineControllerV2
Central responsibilities:

Read all relevant GUI state

Construct merged configs via ConfigMergerV2

Build job lists via JobBuilderV2

Submit jobs to JobService in the correct mode (queue/direct)

Forward normalized jobs to PreviewPanelV2

Enforce stage ordering rules

Coordinate Restore Last Run behavior

Dispatch UI updates on state changes

PipelineController is stateless except for the connection to AppStateV2.

4. Pipeline Construction Layer
The pipeline builder layer ensures that job construction is:

Deterministic

Testable

Independent of GUI

Fully normalized

It includes two components: ConfigMergerV2 and JobBuilderV2.

5. ConfigMergerV2 — Override & Merge Logic
Inputs:
Prompt Pack config

StageOverridesBundle (GUI-derived)

Outputs:
A MergedRunConfig representing the final configuration for a single variant before randomization/seeding.

Rules:
Overrides apply only when override flag is TRUE.

Disabled stages remain disabled, even if pack config enables them.

Nested configs (refiner, hires, adetailer) merge field-by-field.

No mutation of pack config or overrides.

Returns deep copies for safety.

Mermaid Diagram
mermaid
Copy code
flowchart LR
    PackCfg[Pack Config]
    Overrides[StageOverridesBundle]
    Merger[ConfigMergerV2]
    MergedCfg[MergedRunConfig]

    PackCfg --> Merger
    Overrides --> Merger
    Merger --> MergedCfg
ASCII:

vbnet
Copy code
PackConfig + Overrides → ConfigMergerV2 → MergedRunConfig
6. JobBuilderV2 — Variant, Batch, and Seed Expansion
JobBuilderV2 translates merged configs into a set of normalized jobs.

Responsibilities:
Apply RandomizationPlanV2 → produce variant configs

Expand batch runs

Calculate deterministic seeds (none / fixed / per-variant)

Assign variant_index, batch_index

Attach OutputSettings

Produce NormalizedJobRecord objects

Mermaid Diagram
mermaid
Copy code
flowchart TD
    MR[ MergedRunConfig ]
    RP[ RandomizationPlanV2 ]
    JB[ JobBuilderV2 ]
    VCFG[ Variant Configs ]
    NJR[ NormalizedJobRecord List ]

    MR --> JB
    RP --> JB
    JB --> VCFG --> NJR
ASCII:

css
Copy code
MergedConfig + RandomizationPlan → JobBuilderV2 → [NormalizedJobRecord...]
7. NormalizedJobRecord (Canonical Job Model)
Represents exactly what will run.
No GUI artifacts. No optional fields missing.

Fields include:
job_id

full pipeline config

seed

variant index / total

batch index / total

output directory

filename template

config_snapshot

timestamp

human-readable summary (JobUiSummary)

Why normalization is essential:
Eliminates GUI ambiguity

Ensures queue and preview are identical

Enables persistence

Prevents inconsistent executions

Guarantees reproducibility for Learning/Cluster phases

 8. Queue & Execution Layer
  Queue Model (JobService + JobQueueV2)
    - JobService now forwards completed and failed job signals to JobHistoryService so the history store consistently records metadata and emits completion events.
 - JobService now subscribes to queue status transitions and re-emits `job_started`, `job_finished`, and `job_failed` events so GUI panels and the history subsystem can react to deterministic lifecycle updates.
Add jobs

Remove jobs

Reorder jobs

Auto-run

Pause/resume

Track running job

(Planned) persist queue across restarts

Runner
Default runner: SingleNodeJobRunner

Responsibilities:

Execute pipeline stages in canonical order

Report progress & errors

Save images to output dir

Handle cancellation

Execution Mermaid Diagram
mermaid
Copy code
flowchart LR
    NJR[NormalizedJobRecord]
    JS[JobService]
    Q[JobQueueV2]
    RN[Runner]
    IMG[Generated Images]

    NJR --> JS --> Q --> RN --> IMG
ASCII:

nginx
Copy code
NormalizedJobRecord → JobService → Queue → Runner → Output Images
9. Stage Ordering Rules
Canonical order (mandatory):

txt2img

img2img

refiner

hires

upscale

adetailer

The runner must:

Skip disabled stages

Pass outputs sequentially

Preserve metadata between stages

10. Randomizer Integration Point
Randomizer runs before JobBuilderV2:

nginx
Copy code
MergedConfig → RandomizationPlanV2 → VariantConfigs → Normalization
Randomizer modifies the configuration, not:

seeds (except seed mode)

prompts

files

queue order

11. Output Model
StableNew uses:

OutputSettings

Filename templates with tokens

Output directories per job

JobBuilderV2 attaches OutputSettings to NormalizedJobRecord.

Runner writes results accordingly.

12. Error Handling & Cancellation
Jobs may fail at:

Merge stage

JobBuilder

Queue entry

Runner execution

Failures must:

Mark job as failed

Never crash GUI

Be visible in queue view

Produce a log entry visible in the Details panel

============================================================
13. Deprecated Concepts and Why They Changed
============================================================
#ARCHIVED
(This section is for historical context only. Agents must ignore.)

13.1 V1 Job Model
Unstructured

Not normalized

GUI-modified configs mid-run

No reproducibility

Replaced entirely by NormalizedJobRecord

13.2 MainWindow V1 Architecture
~7,380 lines, monolithic

Not testable

UI tightly coupled to pipeline logic

Replaced by modular panel-based GUI V2

13.3 Legacy Runner / Execution Path
Old flow:

nginx
Copy code
GUI → Executor → Direct WebUI Calls
Issues:

No queue

No job metadata

Hard to cancel jobs

No variant/batch tracking

No randomizer support

Replaced by:

nginx
Copy code
NormalizedJobRecord → JobService → Queue → Runner → WebUI
End of ARCHITECTURE_v2.5.md
