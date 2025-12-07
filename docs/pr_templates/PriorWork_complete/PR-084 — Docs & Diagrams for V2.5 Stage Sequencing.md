PR-084 — Docs & Diagrams for V2.5 Stage Sequencing.md
Intent

Create a single, authoritative documentation package for the V2.5 stage sequencing model, covering:

Conceptual overview (what stages exist, how they relate).

Run-time behavior (txt2img/img2img/refiner/hires/upscale/ADetailer).

Key invariants (order constraints, error conditions).

How GUI V2, controller, pipeline runner, and executor cooperate.

How the tests (journey + pipeline) enforce that behavior.

This will be the go-to doc for you, future contributors, and AI agents.

Scope & Risk

Risk: Low

Subsystem: Documentation only

No code changes, except possibly very small docstring additions.

Allowed Files

New docs (proposed names):

docs/Stage_Sequencing_V2_5_V2-P1.md

docs/Stage_Sequencing_Diagrams_V2_5_V2-P1.md (or combined into one)

Optionally update cross-links in:

StableNewV2_Summary_V2-P1.md

High-Level-Reasoning-and-Plan_V2-P1.md

LearningSystem_MasterIndex_V2-P1.md

README(Stable-Diffusion WebUI)_V2-P1.md

(Use your existing naming convention with V2-P1 suffix.)

Forbidden Files

All runtime code (src/*)

Tests (tests/*)

(Unless you explicitly decide later to add docstrings or comments; this PR spec assumes docs only.)

Implementation Plan
1. Create primary stage sequencing doc

docs/Stage_Sequencing_V2_5_V2-P1.md:

Sections:

Introduction

Purpose of V2.5 sequencing.

Relation to earlier V1/V2 designs.

Stage Catalog

txt2img

img2img

refiner (hires-aware)

hires fix parameters (enable_hr, hr_scale, etc.)

upscale

ADetailer

For each stage:

Inputs

Outputs

Key config fields

Relevant tests (by filename).

Canonical Stage Order

Visual list of valid orderings.

Explanation of invariants:

At least one generation stage.

ADetailer last.

Refiner/hires before upscale/ADetailer.

Sequencing Scenarios

txt2img-only.

img2img-only.

txt2img+img2img.

Generation + refiner/hires.

Generation + upscale + ADetailer.

Full chain: txt2img → img2img → refiner/hires → upscale → ADetailer.

Error Handling & Validation

Invalid configurations:

No generation stages.

ADetailer configured without any previous stage.

Multiple generation stages with conflicting settings.

How StageSequencer/runner handle these.

Integration Points

RunConfig and AppState fields.

Controller assembly and apply-config.

PipelineRunner & StageSequencer.

Executor payload structure.

Tests as Contracts

Map each behavior to 1–2 key tests:

Journey tests.

Pipeline tests.

Config tests.

2. Create diagram doc (or section) with Mermaid

In the same doc or a sibling:

Sequence diagrams:

GUI → Controller → PipelineRunner → Executor for a typical run.

Stage transitions with annotations for refiner/hires/ADetailer.

Example snippet:

sequenceDiagram
    participant GUI
    participant Controller
    participant Runner
    participant Sequencer
    participant Executor

    GUI->>Controller: start_run()
    Controller->>Runner: run_once(run_config)
    Runner->>Sequencer: build_stage_list(run_config)
    Sequencer-->>Runner: [txt2img, img2img, refiner, upscale, adetailer]
    loop stages
        Runner->>Executor: run_<stage>(config, images)
        Executor-->>Runner: images
    end
    Runner-->>Controller: result
    Controller-->>GUI: update UI (status/logs)


State diagrams:

Lifecycle states: IDLE, RUNNING, ERROR, CANCELLED, COMPLETED.

Data-flow diagrams:

Configs and images as they progress through stages.

3. Cross-link from existing docs

Update:

StableNewV2_Summary_V2-P1.md

High-Level-Reasoning-and-Plan_V2-P1.md

Test_Coverage_Report_V2-P1.md (if helpful)

Add short “Further Reading” / “Stage Sequencing” sections that link to the new doc.

4. Add doc “anchors” for AI agents

In the new doc, include explicit headings/anchors that AI agents can latch onto, e.g.:

## For AI Agents: How to Use This Doc

Where to look for:

Stage order

RunConfig fields

Test names

This matches your pattern of making docs “LLM-friendly” and easy to reference in the future.

Acceptance Criteria

A comprehensive, single-source doc describing V2.5 stage sequencing.

At least one diagram (Mermaid or similar) that visualizes the sequence.

Cross-links from at least:

The main StableNewV2 summary doc.

The high-level reasoning doc.

Clear mapping between features and tests enforcing them.

Easy for Codex/ChatGPT to use as a reference when implementing future PRs or debugging sequencing issues.

Validation Checklist

 Docs rendered locally (Markdown preview) with no formatting errors.

 Diagrams validate (Mermaid syntax OK).

 Links between docs work.

 No runtime code changed as part of this PR.

🚀 Deliverables

docs/Stage_Sequencing_V2_5_V2-P1.md

Diagrams (in-doc Mermaid or separate file)

Updated cross-references from existing StableNewV2 docs