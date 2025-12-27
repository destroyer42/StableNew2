#CANONICAL
StableNew — Modern SDXL Orchestration, Pipeline Engine, and GUI (V2.5)

Version: V2.5
Status: Actively under development
Documentation Index:
➡️ See /docs/DOCS_INDEX_v2.5.md for the complete canonical documentation suite

Overview

StableNew is a ground-up reimagining of an SDXL pipeline orchestration system—designed for stability, clarity, modularity, robustness, and future extensibility.

It is a multi-layered application consisting of:

GUI V2 — A modern Tkinter-based interface focused on usability, dark-mode clarity, job previewing, queue control, and pipeline configurability.

Controller Layer — The source of truth for dropdown population, pipeline configuration, randomizer integration, last-run recovery, and job dispatching.

Pipeline Runtime (V2.5) — A normalized, deterministic job-building system powered by:

ConfigMergerV2

JobBuilderV2

NormalizedJobRecord

JobSpecV2

Queue & JobService — A structured job queue supporting reordering, pausing, send-job semantics, and future persistence.

WebUI Client — A stable interface between StableNew and external Stable Diffusion WebUI processes.

Randomizer Engine V2 — A pure, deterministic, test-driven config variant generator.

Learning System (Phase 3) — A metadata and scoring layer for continuous learning loops.

Project Vision

StableNew aims to be the best-in-class local SDXL orchestrator:

Easy enough for new users

Powerful enough for advanced workflows

Architecturally sound

Thoroughly tested

Highly modular

Ready for distributed cluster execution

With:

A clean, predictable, user-friendly GUI

A deterministic, stable pipeline core

Feature-rich queue management

A future-ready architecture supporting AI-driven configuration and analysis

Where We’ve Been (History & Motivation)

The original StableNew (pre-V2) grew organically and quickly—resulting in:

A monolithic main_window.py (~7,000 lines)

Tight coupling between GUI, pipeline, and executor

Difficulty testing and extending

Increasing user confusion around pipeline flow, run controls, and dropdowns

The V2 → V2.5 rewrite addressed these issues:

V2.x Achievements

Entire GUI restructured into modular panels

Controller formalized as single source of truth

Pipeline separated from GUI

Introduction of randomizer options

Major cleanup of legacy systems

V2.5 Achievements

ConfigMergerV2 introduced for deterministic config layering

JobBuilderV2 introduced for pipeline-once job construction

NormalizedJobRecord + JobUiSummary unify backend → GUI representation

Queue system redesigned for proper ordering, pausing, and run semantics

Canonical documentation → /docs/ with versioned governance

New PR pipeline: Discovery → Scoped PR generation

MainWindow V1 legacy retired safely

The project is now on a solid foundation for rapid, safe, feature-rich development.

Where We Are Now (Current State — V2.5)

StableNew is entering its stabilization and UX polish phase, featuring:

✔ A robust core pipeline

Deterministic job expansion

Complete randomizer V2 implementation

Per-stage configurable merging

Stage presence flags (txt2img, refiner, hires, upscale)

✔ A nearly complete GUI V2

Multi-column layout with scrollable frames

Config cards for each stage

Preview panel built on unified job summary

Queue panel supporting reorder/remove/clear

Running job card

Unified logging view with Details → Logs behavior

✔ PR Roadmap established for:

Queue persistence

Auto-run improvements

Send Job semantics

Full UX modernization

Feature parity with advanced SDXL workflows

✔ Canonical Documentation Layer

All architectural, governance, and operational knowledge is captured in:

➡ /docs/DOCS_INDEX_v2.5.md
➡ /docs/ARCHITECTURE_v2.5.md
➡ /docs/GOVERNANCE_v2.5.md
➡ /docs/ROADMAP_v2.5.md

Where We’re Going (Future Direction — Roadmap Highlights)
Phase 1 (Finishing V2.5 Core)

Complete GUI Wishlist PR series (A–L)

Finalize queue semantics (send job, auto-run, persistence)

Expand preview/queue interaction features

Logging enhancements + job-specific log filtering

Output naming tokens + file-structure improvements

Phase 2 (Advanced Features)

Integrated Learning System (L3)

Feedback-based job scoring

Embedding tagging and metadata production

Image quality analysis hook-ins

Phase 3 (Distributed / Cluster Execution)

Multi-node job dispatch

Remote node discovery and capability reporting

Parallel workload coordination

Model-sharing and file caching via NAS or shared workspace

Multi-executor load balancing

Long-Term Enhancements

AI-driven prompt optimization

Model performance benchmarking

Config auto-suggestion based on past runs

Knowledge-driven run planning

Repository Structure (High-Level)
StableNew/
│
├── docs/                    # Canonical v2.5 documentation
│   ├── DOCS_INDEX_v2.5.md
│   ├── ARCHITECTURE_v2.5.md
│   ├── GOVERNANCE_v2.5.md
│   ├── ROADMAP_v2.5.md
│   ├── AGENTS_v2.5.md
│   ├── CODING_TESTING_STANDARDS_v2.5.md
│   ├── RANDOMIZER_SPEC_v2.5.md
│   ├── LEARNING_SYSTEM_SPEC_v2.5.md
│   ├── CLUSTER_COMPUTE_SPEC_v2.5.md
│   ├── pr_templates/
│   │     └── *.md          # PR templates (current, pending, or historical)
│   ├── older/
│   └── archive/
│
├── src/
│   ├── gui/
│   │   ├── panels_v2/
│   │   └── views/
│   ├── controller/
│   ├── pipeline/
│   ├── randomizer/
│   └── api/
│
├── tests/
│   ├── pipeline/
│   ├── controller/
│   ├── gui_v2/
│   └── randomizer/
│
└── README.md (this file)

Development Workflow (V2.5)

StableNew uses a Discovery → PR workflow.

1. Discovery Phase

You (or an LLM) identify:

Subsystems involved

Files likely affected

Root causes

Risk tier

Produce a Discovery ID (D-XX)

No code or PR is produced at this stage.

2. PR Generation Phase

Once user says:

“Generate PR-### using D-##”

The PR is produced with:

Allowed/forbidden files

Step-by-step implementation

Tests

Acceptance criteria

Rollback plan

Risk Tiers

Tier 1: GUI / docs / tests

Tier 2: Controller, queue logic

Tier 3: Executor, runner, learning core

See /docs/GOVERNANCE_v2.5.md for full details.

Contributing

Contributions should follow:

Coding standards → /docs/CODING_TESTING_STANDARDS_v2.5.md

Architectural boundaries → /docs/ARCHITECTURE_v2.5.md

PR template → /docs/pr_templates/*

Risk tiering & safety rules → /docs/GOVERNANCE_v2.5.md

Testing is required for any PR that touches pipeline or controller logic.

CI/CD

StableNew uses GitHub Actions for continuous integration:

Unit Tests
- Runs on every push/PR to `main` and `cooking`
- Python 3.11 & 3.12 on ubuntu-latest
- Badge: ![CI](https://github.com/destroyer42/StableNew2/workflows/CI/badge.svg)

Journey Tests (Mocked)
- Runs on every push/PR to `main` and `cooking`
- Uses WebUI mocks (no real SD WebUI required)
- Validates clean shutdown, thread management, E2E workflows
- Badge: ![Journey Tests](https://github.com/destroyer42/StableNew2/workflows/Journey%20Tests%20(CI%20-%20Mocked)/badge.svg)

Journey Tests (Real WebUI)
- Runs on self-hosted Windows runner (scheduled daily)
- Requires real SD WebUI for actual image generation
- Validates full E2E with real models

Running Tests Locally

```bash
# Unit tests
pytest tests/ -v

# Journey tests with mocks (CI mode)
CI=true pytest tests/journeys/ -v

# Journey tests with real WebUI
pytest tests/journeys/ -v  # requires WebUI at localhost:7860
```

Getting Started
Prerequisites

Python 3.10+

Stable Diffusion WebUI backend running locally or on LAN

Required models stored in configured model directory

Running StableNew
python -m src.main


GUI should open and display:

Left column: configuration cards

Middle: prompt packs and stage overrides

Right: preview, running job, and queue

Contact & Support

If you need help understanding StableNew’s architecture, development workflow, or canonical document set:

Start with /docs/DOCS_INDEX_v2.5.md

Review ROADMAP_v2.5.md for project direction

Explore ARCHITECTURE_v2.5.md for system boundaries

For bugs, feature requests, or PR planning, open an issue referencing the latest snapshot and clear expected behavior.

License

(Insert license text if applicable)

Final Note

StableNew V2.5 represents the foundation of a truly modern, AI-assisted SDXL orchestration platform.

This README now provides:

Historical context

Current architecture

Clear documentation entrypoints

Contribution guidance

Developer onboarding path

Vision for where the project is headed