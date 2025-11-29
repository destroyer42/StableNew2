# StableNew

StableNew is a **local orchestration layer** around Stable Diffusion WebUI (A1111) that provides a structured, repeatable workflow for:

- `txt2img → img2img → ADetailer → Upscale → (Video)`
- Prompt-pack–driven medieval/fantasy image generation
- Configurable presets, randomization, and prompt matrices
- Structured logging and manifests for every run

This repository is being actively refactored to improve **stability**, **test coverage**, and **GUI usability** while preparing for **distributed workloads** and a stronger **video pipeline**.

---

## Key Features

- **Multi-stage pipeline**  
  Run `txt2img`, optional `img2img`, ADetailer, upscale, and (soon) video in a single orchestrated flow.

- **Prompt packs & presets**  
  Curated packs (especially medieval/fantasy) and presets for SDXL / Juggernaut with randomization tokens and matrices.

- **Randomization & Matrix UI**  
  Token-based randomization, prompt matrices, and “preview payload” to see exactly what will be sent to WebUI.

- **Structured manifests & logs**  
  Each run writes JSON manifests and optional CSV rollups into timestamped output folders.

- **AI-assisted development**  
  Tight integration with GitHub Copilot/Codex and ChatGPT, with clear roles and rules to avoid dangerous refactors.

---

## Getting Started

### Prerequisites

- Python 3.11+
- A running **Stable Diffusion WebUI (A1111)** instance with:
  - API enabled
  - (Optional) ADetailer extension installed
- FFmpeg (for planned video features)
- Windows is the primary target environment; other platforms may work but are not the focus.

### Installation

From the project root:

```bash
pip install -e ".[dev]"
If you use pre-commit:

bash
Copy code
pre-commit install
Running StableNew
From the project root:

bash
Copy code
python -m src.main
Make sure WebUI is running and reachable on the configured host/port (usually http://127.0.0.1:7860).

Development Workflow
StableNew uses a tests-first, small-PR development style and a defined AI workflow.

Tests & Linting
Common commands:

bash
Copy code
# Linting / formatting
pre-commit run --all-files

# Unit tests
pytest -q

# With coverage
pytest --cov=src --cov-report=term-missing

# Key guards
pytest tests/test_config_passthrough.py -v
pytest tests/test_pipeline_journey.py -v
AI-Assisted Development (ChatGPT + Copilot)
We treat ChatGPT as the architect and Copilot/Codex as the executor:

ChatGPT:

Diagnoses issues with logs/snippets.

Designs changes and produces minimal diffs.

Writes/updates tests and docs.

Copilot/Codex:

Applies diffs exactly.

Runs tests and returns full output.

Does not freestyle large refactors.

For details, see:

docs/AGENTS_AND_AI_WORKFLOW.md

.github/CODEX_SOP.md

.github/copilot-instructions.md

Documentation
Core docs live under /docs:

docs/StableNew_History_Summary.md
Project history, key architectural shifts, and why it’s being refactored.

docs/Known_Bugs_And_Issues_Summary.md
Current stability issues, their causes, and how we plan to address them.

docs/StableNew_Roadmap_v1.0.md
Phase-based roadmap:

Repo cleanup & docs consolidation

Stability & TDD

GUI overhaul

Job queue & refinement

Distributed workloads & video

docs/AGENTS_AND_AI_WORKFLOW.md
Roles (Controller / Implementer / Tester / GUI / Refactor / Docs) and AI workflow.

docs/ARCHITECTURE_v2.md
Draft of the target architecture, to be finalized as refactors land.

Older or superseded docs are under docs/archive/ and should be treated as historical context only.

Contributing
High-level rules:

Small PRs: one main behavior change per PR.

TDD: write or update a failing test first, then make it pass.

Respect high-risk files (main_window, executor, client, randomizer, etc.).

Keep behavior and refactors separate:

Don’t mix big refactors and bug fixes in the same PR.

Update docs when behavior or architecture changes.

See:

CONTRIBUTING.md

docs/AGENTS_AND_AI_WORKFLOW.md

.github/CODEX_SOP.md

for more detail.

Roadmap Highlights
Short version of the roadmap:

Repo cleanup & docs consolidation
Make the repo easy to navigate; unify AI instructions.

Stability & TDD
Fix hangs, upscale issues, and lifecycle bugs; harden tests.

GUI overhaul
Figma-first layout, then translate to Tk with a modern, uncluttered structure.

Job queue & refinement
Jobs as first-class objects, optional refinement pipelines.

Distributed & video
Multi-machine rendering and a robust video pipeline.

See docs/StableNew_Roadmap_v1.0.md for details.

Status
This repo is mid-refactor. If something feels brittle, check:

docs/Known_Bugs_And_Issues_Summary.md

Open issues / PRs

…and treat the current architecture as evolving toward what is described in docs/ARCHITECTURE_v2.md.