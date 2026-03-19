# StableNew

StableNew is a local image and video orchestration system built around a single
job contract, a queue-first runtime, canonical artifacts, history, replay, and
learning-oriented metadata.

Version: v2.6  
Status: active migration closure and platform unification  
Canonical docs entrypoint: `docs/DOCS_INDEX_v2.6.md`

## Canonical Runtime

StableNew's canonical runtime is:

`Intent Surface -> Builder/Compiler -> NormalizedJobRecord -> JobService Queue -> PipelineRunner -> Stage/Backend Execution -> Canonical Artifacts -> History/Learning/Diagnostics`

Non-negotiable runtime rules:

- Fresh execution is queue-only.
- `Run Now` means queue submit + immediate auto-start, not a second executor.
- NJR is the outer execution contract for image generation, video generation,
  replay, reprocess, learning, CLI, and image edit.
- StableNew owns orchestration, queueing, artifacts, history, replay, and
  diagnostics. Image and video backends execute only.

Preferred still-image stage chain:

`txt2img -> optional img2img -> optional adetailer -> optional final upscale`

## Intent Surfaces

StableNew currently supports or is standardizing these intent surfaces:

- PromptPack-driven image generation
- Reprocess and image-edit submissions
- History replay and restore
- Learning-generated submissions
- Video workflow submissions
- CLI-driven submissions

PromptPack remains the primary image authoring surface, but it is not the only
valid source of user intent in the modern architecture.

## Current Repo Reality

The repo already has the backbone required for the end-state:

- NJR-first queue/runner execution
- canonical artifact and manifest contracts
- replay and reprocess substrate
- a real `src/video/` backend seam for video execution

There is still migration debt to remove:

- archive `PipelineConfig` imports in live source and tests
- `legacy_njr_adapter` still present in runtime code
- `DIRECT` terminology and behavior still present in code/tests
- oversized controller ownership in `app_controller.py` and `pipeline_controller.py`

Current migration closure and PR sequencing are tracked in:

- `docs/PR_Backlog/MIGRATION_CLOSURE_EXECUTABLE_BACKLOG_v2.6-1.md`
- `docs/PR_Backlog/StableNew_ComfyAware_Backlog_v2.6.md`

## Start Here

Read these first:

1. `docs/DOCS_INDEX_v2.6.md`
2. `docs/ARCHITECTURE_v2.6.md`
3. `docs/GOVERNANCE_v2.6.md`
4. `docs/StableNew Roadmap v2.6.md`
5. `docs/StableNew_v2.6_Canonical_Execution_Contract.md`

Useful subsystem docs:

- `docs/PROMPT_PACK_LIFECYCLE_v2.6.md`
- `docs/Builder Pipeline Deep-Dive (v2.6).md`
- `docs/DEBUG HUB v2.6.md`
- `docs/StableNew_Coding_and_Testing_v2.6.md`

## Running StableNew

Prerequisites:

- Python 3.10+
- Local or reachable Stable Diffusion WebUI for image stages
- Required local models and external tools for the workflows you use

Start the app:

```bash
python -m src.main
```

## Testing

Common commands:

```bash
pytest --collect-only -q
pytest tests/pipeline -q
pytest tests/controller -q
pytest tests/gui_v2 -q
pytest tests/video -q
```

Testing policy:

- canonical runtime suites come first
- compat-migration suites are temporary and must shrink over time
- quarantine suites must be explicit and not silently define architecture

Current collection baseline used by the documentation reset:

- `pytest --collect-only -q` -> `2348 collected / 1 skipped`

## Notes

- `docs/archive/` is reference-only.
- `docs/CompletedPR/` stores completed PR records.
- `docs/PR_Backlog/` stores active and historical backlog-driving PR materials.
- `docs/archive/superseded/StableNew_Architecture_v2.6.md` is not an active
  architecture source; `docs/ARCHITECTURE_v2.6.md` is the canonical
  architecture document.
- If `README.md` and a canonical v2.6 doc disagree, the canonical doc wins.
