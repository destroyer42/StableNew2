StableNew v2.6 - Copilot / Executor Instructions

Status: CANONICAL ACTIVE EXECUTOR BRIEF

Read this before making any change in this repository.

## Purpose

This file is the machine-facing execution brief for Copilot/Codex sessions in StableNew.
It does not replace the canonical docs. It operationalizes them.

Primary authorities:

1. `AGENTS.md`
2. `docs/ARCHITECTURE_v2.6.md`
3. `docs/StableNew_v2.6_Canonical_Execution_Contract.md`
4. `docs/StableNew_Coding_and_Testing_v2.6.md`
5. `docs/PR_TEMPLATE_v2.6.md`

If this file conflicts with those documents, the canonical docs win.

## Core architecture

StableNew has one valid job path:

PromptPack -> Builder Pipeline -> NormalizedJobRecord -> Queue -> Runner -> History -> Learning

Critical invariants:

- PromptPack is the only prompt source.
- `AppStateV2` owns runtime draft state.
- Controllers orchestrate; they do not invent alternate job formats.
- `NormalizedJobRecord` is the only valid execution payload for new work.
- Queue and runner are the only execution path.
- Legacy shims, duplicate job paths, and parallel flows are defects.

## Repository map

- `src/gui*/` contains UI layers and view wiring.
- `src/controller/` contains orchestration and lifecycle coordination.
- `src/pipeline/` contains builder/runtime pipeline modules.
- `src/randomizer/` contains deterministic randomizer logic.
- `src/queue/` and `src/history/` contain execution persistence/runtime state.
- `src/learning/` contains post-execution learning logic.
- `tests/` mirrors runtime domains and must stay deterministic.
- `.github/agents/` contains specialist agent profiles.
- `.github/instructions/` contains path-scoped guidance files.

## Execution rules

- Treat approved PR specs as binding.
- Modify only files inside the approved scope.
- Stop when instructions are ambiguous or contradictory.
- Do not preserve legacy code "just in case."
- Do not add new prompt sources, dict-based runtime configs, or alternate runner entrypoints.
- Do not move logic into the GUI that belongs in controller/pipeline/randomizer layers.
- Do not change architecture without an explicit approved plan.

## Build and verification defaults

Use targeted validation for the files you touch, then broader validation when appropriate.

Typical commands:

- `python -m compileall src`
- `pytest -q`
- `pytest tests/controller -q`
- `pytest tests/pipeline -q`
- `pytest tests/gui -q`
- `pytest tests/randomizer -q`
- `pytest tests/learning -q`

Rules:

- No real network calls in tests.
- No sleeps unless a test is explicitly timing-related and approved.
- GUI tests must avoid blocking the UI thread.
- Prefer deterministic mocks over live WebUI/API behavior.

## Instruction layering

When editing files in a scoped area, also follow the matching file under `.github/instructions/`.

Examples:

- GUI work -> `.github/instructions/gui.instructions.md`
- Controller work -> `.github/instructions/controller.instructions.md`
- Pipeline work -> `.github/instructions/pipeline.instructions.md`
- Randomizer work -> `.github/instructions/randomizer.instructions.md`
- Tests -> `.github/instructions/tests.instructions.md`
- Docs -> `.github/instructions/docs.instructions.md`

## Agent usage

Use the canonical agents in `.github/agents/`:

- `controller_lead_engineer.md`
- `implementer.md`
- `gui.md`
- `pipeline_runtime.md`
- `tester.md`
- `docs.md`
- `refactor.md`

Archived or duplicate agent files are reference-only and must not be used for new work.
