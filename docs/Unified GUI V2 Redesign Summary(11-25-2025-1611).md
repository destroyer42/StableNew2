StableNewV2 – Unified GUI V2 Redesign Summary
Overview

The V2 GUI is now organized into three dedicated workspaces, each with clearly partitioned responsibilities and a single source of truth for its domain:

Prompt Tab – Authoring & structure

Pipeline Tab – Execution & runtime behavior

Learning Tab – Experiments, sweeps, and rating

This replaces the loosely connected prior V2 approach and establishes a professional-grade UX that’s consistent, predictable, and extensible.

1. Prompt Tab – “Authoring Workspace”
Purpose

Create, edit, organize, and preview prompt packs with clean structure, matrix syntax, and prompt-embedded model references.

Primary Responsibilities

Prompt pack management (load/save/delete).

Multi-line prompt editor grid (10×5 default model).

Matrix syntax insertion + preview (authoring only, not execution).

LoRA & embedding insertion:

Controls where LoRAs/embeddings appear in text.

Ensures correct syntax & ordering.

Not responsible for runtime strength or activation.

Real-time parsed metadata:

Detected LoRAs/embeddings.

Matrix sections.

Prompt structure validation.

Read-only “prompt → pipeline” preview.

Source of Truth

✔ Text contents
✖ Runtime weights
✖ Execution behavior

This formalizes the Prompt tab as the authoring domain, not the execution domain.

2. Pipeline Tab – “Execution Workspace”
Purpose

Configure and run multi-stage pipelines, including batching, randomization, queueing, stage toggling, and runtime LoRA behavior.

Primary Responsibilities

Top-bar stage toggles (expand/collapse + activate/deactivate).

Run Control Bar:

Run single stage / sub-pipeline / full pipeline.

Run Now vs Add to Queue.

Central Stage Cards:

txt2img

img2img/adetailer

upscale

PipelineConfig Panel:

Direct vs Queue mode

Looping / batch runs

Randomizer execution settings

Randomizer execution engine:

Converts matrix syntax + settings into job count and run plan.

LoRA/Embedding runtime controls:

Strength sliders (the authoritative source).

On/off toggles (runtime activation).

Right-side preview panel showing results and metadata.

Global Status Bar remains visible.

Source of Truth

✔ Runtime LoRA strength
✔ Runtime activation
✔ Queue configuration
✔ Number of jobs/variants
✔ Execution flow

The Pipeline tab is the single source of truth for what actually runs.

3. Learning Tab – “Experiment Workspace”
Purpose

Design and run controlled parameter sweeps, perform ratings, and generate structured learning records for recommendation systems.

Primary Responsibilities

Experiment Designer:

Baseline config selection (pull from Pipeline tab).

Prompt selection (pull from Prompt tab).

Stage selection.

Variable-under-test:

CFG, steps, sampler, scheduler, LoRA strength, denoise, upscale factor, etc.

Value sets or ranges.

Images per value.

“Build Plan” → produces a structured Learning Plan.

“Run Plan” → executes via the Pipeline executor with a learning context.

Plan Table:

Variants

Values

Status

Completed image counts

Review/Rating Panel:

Image viewer

Metadata snapshot

Rating controls

Notes

Writes Learning Records through the existing JSONL writer.

Source of Truth

✔ Parameters under test
✔ Ratings & metadata
✔ Variant definitions
✔ Learning plan execution state

4. Key Architectural Principles
Hybrid LoRA/Embedding Model

Prompt tab controls placement & syntax.

Pipeline tab controls strength & activation.

Learning tab varies the runtime numerical parameter during sweeps.

This resolves the long-standing ambiguity about “where LoRA truth lives.”

Single Source of Truth per Domain

Prompt = text & structure

Pipeline = runtime & execution

Learning = experiment logic & ratings

Full Reuse of Existing Backend

No new execution engines—learning mode is an annotated pipeline run.