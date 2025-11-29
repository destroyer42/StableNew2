Architecture v2 – Translation Plan

StableNew Migration Blueprint
Version: 1.0
Last Updated: 2025-11-15

This document explains how the current StableNew implementation maps to the desired Architecture v2, and provides a step-by-step refactor sequence for migrating the system safely.

It is designed to:

Reduce brittleness

Decompose large files

Standardize boundaries

Improve testability

Align GUI → Controller → Pipeline → API layers

Support future expansions (job queue, distributed workloads, video)

1. Overview of the Translation Strategy

StableNew currently has tight coupling, especially between:

GUI MainWindow

Pipeline executor

API client

Randomization/matrix logic

Logging / file IO

Global configuration state

Architecture_v2 introduces clean layers with one-way dependencies:

GUI → Controller → Pipeline → API → Randomizer/Config → Logging


This plan translates your existing codebase into that structure with:

No behavior changes until tests pass

TDD-first approach for each refactor

Small PRs that each have isolated blast radius

Parallelizable migration steps

2. Current Code → Target Layer Mapping

Below is the exact mapping between your existing modules and the planned architecture.

2.1 GUI Layer
Current File	Issue	Target Location	Action
src/gui/main_window.py	God-object, inconsistent responsibilities, threading hazards	src/gui/main_window.py (refactored)	Break into: window shell, layout zones, widget creators, panel wiring
src/gui/pipeline_controls_panel.py	Good separation but layout-based	Same	Keep panel but remove controller logic; delegate to Controller
src/gui/config_panel.py	Mixed responsibilities	Same	Extract model/vae/sampler refresh logic into GUI→Controller ops
src/gui/prompt_pack_panel.py	UI + file IO + pack logic intertwined	Same	Move pack logic → utils/prompt_packs.py
src/gui/advanced_prompt_editor.py	Fine — mostly UI only	Same	Keep; remove randomizer behavior from here
src/gui/adetailer_config_panel.py	OK; some behavior leaks	Same	Wire via Controller only
src/gui/stage_chooser.py	Good isolation but ties to pipeline	New: gui/stage_chooser.py	Only return selection; pipeline interprets it
src/gui/log_panel.py	Fine	Same	No major changes
Missing	No explicit Matrix Panel module	src/gui/matrix_panel.py	Extract UI from main_window & prompt editor
Key GUI Refactor Goals

MainWindow becomes orchestration-only with “zones” not business logic

Panels become UI-only

All pipeline actions bubble up into a single Controller interface

Threading fixed by using root.after() consistently

2.2 Controller Layer
Current Code	Issue	Target
Implicit pipeline control inside main_window.run_pipeline()	Coupled to GUI + pipeline	New: src/controller/app_controller.py
Stop logic scattered across GUI and pipeline objects	Multiple sources of truth	Move STOP logic entirely into Controller
State transitions (IDLE/RUNNING/etc) handled inconsistently	Hard to reason about	Move to unified gui/state.py
Controller Responsibilities

(Architecture_v2 goals)

Authoritative state machine

Owns PipelineExecutor

Creates new CancelToken each run

Handles Run/Stop/Preview commands

Validates config before run

Emits signals back to GUI

2.3 Pipeline Layer
Current Code	Issue	Target
src/pipeline/executor.py	Too large, logic + IO + partial API calls	pipeline/executor.py (refactored)
variant_planner.py	Mixes matrix + variant logic	See Randomization Layer
ADetailer logic	Spread between pipeline + GUI	Stage-specific helper in pipeline
Pipeline Refactor Goals

Executor calls pure functions for each stage

Each stage returns metadata to the next

CancelToken checked frequently

Error propagation standardized

Logging calls delegated to StructuredLogger only

2.4 Integration Layer (API Client)
Current File	Issue	Target
src/api/client.py	Behavior mostly right, but returns inconsistent structures; retry logic unfinished	Same
API Changes Needed

Add retry/backoff wrapper

Make .txt2img() etc return ApiResponse(success, data, error)

Slim down client to pure network operations

Move prompt sanitization out of client → Randomization layer

2.5 Randomization & Matrix Layer
Current	Issue	Target
utils/randomizer.py	Doing too much: wildcards, matrices, preview payload, sanitization, variant behavior	utils/randomizer.py + utils/matrix.py
Matrix UI logic is scattered in GUI	GUI does behavior	Move to matrix.py + have GUI as pure views
Randomization Refactor Steps

Extract:

wildcard expansion

slot/matrix expansion

sanitize_prompt()

Tests first:

preview payload == pipeline payload

no raw tokens leak

2.6 Logging & Manifests Layer
Current	Issue	Target
utils/file_io.py	OK but mixed with other behavior	Same
StructuredLogger not fully isolated	Too many call sites	Create src/utils/logger/structured_logger.py
Logging Goals

One logger entry point

Pipeline stages call logger methods only

Manifests + CSV under clear, consistent naming

2.7 New Job Queue Layer (Planned)

Adds:

src/jobs/job_model.py

src/jobs/job_queue.py

src/jobs/worker_client.py

But only after Phase 1–3 complete.

3. Translation Workflows

This section shows exact PR-sized steps to migrate code toward Architecture_v2 without breaking anything.

3.1 Phase A — Safety Harness & Test Expansion

Before refactoring ANY code:

Expand test_config_passthrough.py

Add failing tests for lifecycle:

Run → Stop → Run

Run → Complete → Run

Add preliminary tests for:

Prompt sanitization invariants

Matrix UI payload equivalence

Pipeline retry/backoff

Output: A safety net for refactors.

3.2 Phase B — GUI Decomposition
PR B1 — Extract Matrix Panel

Move UI-only code for prompt matrix into:

src/gui/matrix_panel.py

PR B2 — Extract Pack Logic

Move file-IO and pack processing logic out of prompt_pack_panel:

src/utils/prompt_packs.py

PR B3 — Create “zones” inside MainWindow

Replace nested frames with:

create_header_zone()

create_left_zone()

create_center_zone()

create_bottom_zone()

And move layout code out of constructor.

PR B4 — Move all pipeline actions out of GUI

“Run / Stop / Preview” delegated to Controller:

controller.run()
controller.stop()
controller.preview()

3.3 Phase C — Controller Creation
PR C1 — Create src/controller/app_controller.py

With skeleton:

class AppController:
    def __init__(self, state, logger, api_client):
        ...

PR C2 — Move state machine here

GUIs only listen/react; Controller decides transitions.

PR C3 — Integrate CancelToken into Controller

GUI Stop → Controller.stop() → token.set()

3.4 Phase D — Pipeline Simplification
PR D1 — Split stage helpers

Move to:

pipeline/stage_txt2img.py
pipeline/stage_img2img.py
pipeline/stage_adetailer.py
pipeline/stage_upscale.py
pipeline/stage_video.py


Executor becomes:

def run_pipeline(config):
    for stage in get_enabled_stages():
        result = stage.run(...)

PR D2 — Unify returned metadata

All stages return:

StageOutput(
    images=[...],
    metadata={...},
    manifest={...}
)

PR D3 — Retry/backoff wrapper

One helper used by all API calls.

3.5 Phase E — API Layer Improvements
PR E1 — Introduce API dataclasses
@dataclass
class ApiResponse:
    success: bool
    data: dict | None
    error: str | None

PR E2 — Replace raw dictionaries across executor
PR E3 — Add robust exception/timeout handling
3.6 Phase F — Randomization/Matrix Extraction

Greatly reduces coupling.

PR F1 — Move wildcard logic into randomizer.py (pure functions)
PR F2 — Move matrix expansion into matrix.py
PR F3 — Move prompt sanitization into a shared helper
PR F4 — Add tests for preview/pipeline equivalence
3.7 Phase G — Logging/Manifest Consistency
PR G1 — Create utils/logger/structured_logger.py
PR G2 — Replace all direct file IO with logger methods
PR G3 — Add manifest schema tests
3.8 Phase H — Architecture_v2 Finalization

Once major refactors land:

Fill in real code examples in ARCHITECTURE_v2.md

Add diagrams (Mermaid/draw.io)

Document threading contract

Publish final v2 architecture doc

This closes out the architecture transition.

4. Dependency Graph for Refactors

Order matters to avoid breakage.
Here is the dependency order:

Tests → GUI extraction → Controller creation → Pipeline simplification → API cleanup → Randomization extraction → Logging consolidation → Architecture v2 finalize

5. Expected End-State (Post-Refactor)
GUI Layer

Clear zones, simple panels, layout-first design.

Controller Layer

State machine + run/stop logic in one place.

Pipeline Layer

Composable stage modules, error-safe, testable.

API Layer

Small, predictable client with typed responses.

Randomization Layer

Pure functions; testable in isolation.

Manifest Layer

Consistent schemas, atomic logging, clear directory structure.

Job Layer (Future)

Worker queue + distributed architecture.

6. Notes for AI-Assisted Work

Throughout this translation:

Every refactor must have Failing Test → Fix → Verify → Commit

Use the Controller agent to generate PR plans

Use Implementer agent for diff creation

Use Tester agent to expand scenario coverage

No multi-file refactors in a single PR unless they’re mechanical