# StableNew

StableNew is a local desktop orchestrator for reproducible image and video
generation. It compiles user intent into immutable jobs, runs them through one
queue, and records artifacts, history, replay lineage, diagnostics, and
learning-ready provenance.

- Product version: v2.6
- Project state: MVP recovery
- Authoritative remote: `https://github.com/destroyer42/StableNew2.git`
- Default branch: `main`

The repository is named StableNew even though the historical GitHub remote is
named `StableNew2`.

## Start here

1. `STATUS.md` — current product/repository state and immediate priorities.
2. `docs/ARCHITECTURE_v2.6.md` — runtime contracts and open architecture gaps.
3. `docs/StableNew Roadmap v2.6.md` — the active MVP sequence.
4. `docs/StableNew_Coding_and_Testing_v2.6.md` — development and verification.
5. `AGENTS.md` — concise operating contract for Codex and contributors.

Subsystem details live under `docs/Subsystems/`. Operational recovery material
lives under `docs/runbooks/`, and stable data contracts live under
`docs/schemas/`. Old plans and completed implementation records are available
from Git history rather than duplicated in the working tree.

## Runtime

The canonical path is:

`Intent -> Compiler -> NJR -> JobService -> Queue/Repository -> PipelineRunner.run_njr -> Handler -> Artifacts/History`

Fresh work always enters the queue. NJR is immutable authorized work;
queue/history records own mutable lifecycle and result state. PromptPack is one
typed source, not a universal job identity.

## Install and run

On Windows, one command starts StableNew from a checkout:

```text
scripts\launch_stablenew.bat
```

It finds the repository from its own location, creates the repository `.venv` on first run (standard-GIL
Python 3.14 is required as the source), reuses a healthy `.venv`, and always starts
`.venv\Scripts\python.exe -m src.main`; you never need to activate a venv. A broken or drifted `.venv` is
reported, not silently rebuilt. For repair, rebuilds and advanced setup (native SVD, optional
postprocess stack), use the
[Windows runtime bootstrap runbook](docs/runbooks/windows_runtime_bootstrap.md) and its
[`scripts/bootstrap_windows.ps1`](scripts/bootstrap_windows.ps1) helper.

Image generation requires a configured Stable Diffusion WebUI. Native SVD XT
video has additional dependencies in `requirements-svd.txt`; optional local face
restoration/upscaling uses `requirements-postprocess.txt`. Missing external
dependencies should fail with an actionable message; they are not installed
or downloaded at import time.

## Verify changes

`pyproject.toml` is the only pytest configuration authority. Run:

```text
python tools/ci/check_repository_completeness.py
python tools/ci/run_ruff_baseline.py
python tools/ci/run_mypy_smoke.py
python tools/ci/run_collection_gate.py
python tools/ci/run_required_smoke.py
```

The required smoke suite is hermetic and positively selected. Real WebUI/SVD
acceptance tests are opt-in and are never collection-time side effects.

## Repository hygiene

Runtime outputs, diagnostics, inventories, snapshots, caches, and temporary
test artifacts are local/generated state and are not committed. Generate an
inventory on demand with:

```text
python -m tools.inventory_repo
```

Use Git history for superseded plans, old code, completed PR narratives, and
historical diagnostic evidence.
