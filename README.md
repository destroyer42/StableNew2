# StableNew

StableNew is a local SDXL orchestration system with a Tkinter GUI, canonical
job-building pipeline, queue execution, history, and learning-oriented metadata.

Version: v2.6  
Status: active development  
Canonical docs entrypoint: `docs/DOCS_INDEX_v2.6.md`

## Canonical Runtime

StableNew's canonical execution path is:

`PromptPack/Run Config -> Builder Pipeline -> NormalizedJobRecord -> Queue or DIRECT run -> PipelineRunner -> History/Learning`

Fresh execution is NJR-first. New runtime code should not introduce alternate
job formats or legacy `pipeline_config` execution paths.

Preferred still-image flow:

`txt2img -> optional img2img -> optional adetailer -> optional final upscale`

Refiner and hires remain supported, but as advanced `txt2img` metadata rather
than separate preferred-flow stages.

## Current State

- Canonical txt2img execution is consolidated on the stage-based NJR path.
- Queue/history runtime paths are NJR-first.
- Controller bridge cleanup, boundary config normalization, preferred-flow stage
  contract tightening, and architecture guard tests are in place.
- Prompt auto-optimizer support exists as a deterministic backend service wired
  at final prompt submission time.
- Native SVD work is active, including runtime logging, postprocess progress,
  and capability-aware defaults.

## Repository Layout

High-level structure:

```text
StableNew/
|- docs/
|- src/
|  |- api/
|  |- controller/
|  |- gui/
|  |- learning/
|  |- pipeline/
|  |- prompting/
|  |- queue/
|  |- randomizer/
|  `- video/
|- tests/
`- README.md
```

## Start Here

Read these in order:

1. `docs/DOCS_INDEX_v2.6.md`
2. `docs/ARCHITECTURE_v2.6.md`
3. `docs/GOVERNANCE_v2.6.md`
4. `docs/StableNew_v2.6_Canonical_Execution_Contract.md`
5. `docs/StableNew_Coding_and_Testing_v2.6.md`

Useful subsystem docs:

- `docs/PROMPT_PACK_LIFECYCLE_v2.6.md`
- `docs/Builder Pipeline Deep-Dive (v2.6).md`
- `docs/DEBUG HUB v2.6.md`
- `docs/StableNew Roadmap v2.6.md`

Current PR execution records:

- `docs/PR_MAR26/`

## Development Workflow

StableNew uses a discovery -> scoped PR -> approval -> implementation workflow.

Typical sequence:

1. Discovery or subsystem review
2. PR spec with allowed/forbidden files and test plan
3. Human approval
4. Implementation
5. Verification
6. Documentation harmonization

The authoritative workflow and agent boundaries are in:

- `AGENTS.md`
- `docs/GOVERNANCE_v2.6.md`
- `docs/PR_TEMPLATE_v2.6.md`

## Running StableNew

Prerequisites:

- Python 3.10+
- Local or reachable Stable Diffusion WebUI
- Required models and external tools installed for the workflows you use

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
```

Use targeted test runs for the subsystem you change. Runtime, queue, and
controller changes should also keep collection green.

## Notes

- `docs/archive/` is reference-only.
- Legacy compatibility surfaces may still exist for archival import or test
  support, but they are not the preferred path for new runtime work.
- If README and a canonical v2.6 doc disagree, the canonical doc wins.
