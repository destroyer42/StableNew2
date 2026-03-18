# StableNew — Migration Closure Executable Backlog v2.6

## Why the earlier PR sequence was not sufficient

From the standpoint of an external AI implementation agent, the prior PR list still had four execution gaps:

1. It named the right themes, but not the exact repo seams that are currently broken.
2. It did not specify which files should be created versus moved versus deleted.
3. It did not distinguish between “temporary compatibility needed to unblock collection” and “final target state.”
4. It did not give a deterministic completion test for each PR.

This backlog fixes that. It is intentionally more explicit, because the current repo state is a **partial migration** rather than a clean greenfield refactor.

---

## What the current repo state actually says

These findings are from the 2026-03-17 snapshot:

- `src/controller/app_controller.py` is still very large at about **6245 LOC**.
- `src/controller/pipeline_controller.py` is still large at about **1792 LOC**.
- `src/pipeline/legacy_njr_adapter.py` still imports `src.controller.archive.pipeline_config_types`.
- `src/controller/pipeline_controller.py` still imports:
  - `src.controller.archive.pipeline_config_assembler`
  - `src.controller.archive.pipeline_config_types`
- `src/controller/app_controller.py` still type-imports and runtime-imports `src.controller.archive.pipeline_config_types`.
- `tests/system/test_architecture_enforcement_v2.py` still explicitly allowlists those legacy imports instead of driving them to zero.
- `pytest --collect-only -q` in the new snapshot still ends with **1935 collected / 100 errors**.
- The dominant structural collection failure is `ModuleNotFoundError: No module named 'src.controller.archive'`.
- There are also environment/bootstrap errors for `requests_mock`, but that dependency is already declared in `pyproject.toml` and `requirements.txt`, so that one is **not the main repo-code defect**.

### Implication

The repo does **not** yet have enough executable structure for an external agent to safely “just remove archive imports.”

A safe sequence needs two distinct moves:

1. **Recreate a controlled compatibility seam** so collection stops failing at import time.
2. **Migrate live code off that seam** and then delete it.

That is the shortest path that both preserves intent and reduces drift.

---

## Global invariants for this backlog

These are mandatory across the whole sequence.

1. `PipelineRunner.run_njr(...)` remains the only production execution entrypoint.
2. No PR may reintroduce direct production execution from raw `PipelineConfig`.
3. `PipelineConfig` is allowed only as a **compatibility DTO** during migration and tests, not as the primary execution payload.
4. The final state must be:
   - no source imports from `src.controller.archive.*`
   - no allowlist for archive imports in architecture tests
   - `pytest --collect-only` reaches zero repo-caused errors
5. Do not mix structural migration with unrelated feature work.
6. Any compatibility shim introduced in this sequence must have a deletion PR already scheduled.

---

## Naming convention

Use these PR titles exactly.

1. `PR-MIG-101-Restore-Canonical-PipelineConfig-Seam-and-Compat-Shim`
2. `PR-MIG-102-Migrate-Live-Source-Off-Archive-Imports`
3. `PR-MIG-103-Zero-Collection-Errors-and-Test-Import-Triage`
4. `PR-MIG-104-Split-PipelineController-Into-Build-Submit-Execute-Services`
5. `PR-MIG-105-Shrink-AppController-Run-and-Config-Responsibilities`
6. `PR-MIG-106-Unify-Run-Request-and-Config-DTO-Boundary`
7. `PR-MIG-107-Tighten-Architecture-Guards-to-Migration-Completion`
8. `PR-MIG-108-Harden-Journey-Queue-and-Recovery-Gates`
9. `PR-MIG-109-Delete-Compat-Shim-and-Legacy-PipelineConfig-Bridge`

---

# PR-MIG-101 — Restore Canonical PipelineConfig seam and compat shim

## BLUF

The repo currently fails collection because source and tests import `src.controller.archive.*`, but that package is missing. The first safe move is **not** to rip everything out immediately. It is to restore a **controlled compatibility seam** so the repo becomes importable again, while simultaneously defining the canonical non-archive home for these symbols.

## Why this PR exists

This PR is a migration-enabler, not a destination. It should create the last safe bridge that lets downstream cleanup happen with signal.

Without this PR, an external agent cannot tell whether later failures are due to:

- missing package/module plumbing
- real behavioral regressions
- or test drift

## Allowed Files

- `src/controller/pipeline_config_types.py` **(new)**
- `src/controller/pipeline_config_assembler.py` **(new)**
- `src/controller/archive/__init__.py` **(new)**
- `src/controller/archive/pipeline_config_types.py` **(new shim)**
- `src/controller/archive/pipeline_config_assembler.py` **(new shim)**
- `tests/controller/test_pipeline_controller_config_path.py`
- `tests/system/test_architecture_enforcement_v2.py`
- `docs/PR_MAR26/PR-MIG-101-Restore-Canonical-PipelineConfig-Seam-and-Compat-Shim.md` **(new)**

## Forbidden Files

- `src/pipeline/pipeline_runner.py`
- `src/pipeline/executor.py`
- `src/queue/**`
- `src/gui/**` except import fallout if absolutely required
- any journey test other than a compile/import fix

## Exact implementation intent

### 1. Create a canonical non-archive home for the compatibility DTO

Create `src/controller/pipeline_config_types.py`.

This file should contain the compatibility `PipelineConfig` dataclass that currently has no live home. It should be treated as:

- a **controller-boundary compatibility object**
- still supported temporarily for tests and transitional builders
- **not** the production execution payload

Use the current construction site in `AppController._build_pipeline_config()` and the test helper `tests/helpers/pipeline_fixtures_v2.py::MinimalPipelineConfig` to derive the field set. At minimum, include fields that are already constructed or asserted in the repo, including:

- prompt / negative_prompt
- model / sampler / scheduler
- width / height / steps / cfg_scale / seed
- pack_name / preset_name
- lora_settings / metadata
- refiner fields
- hires fields
- adetailer-related fields if currently accessed via config metadata
- any stage-related or path-related fields already consumed by `legacy_njr_adapter.py` and controller tests

Do **not** over-engineer validation in this PR. This object exists to restore import stability and preserve current compat semantics.

### 2. Create a canonical non-archive home for the assembler

Create `src/controller/pipeline_config_assembler.py`.

This file must define:

- `GuiOverrides`
- `PipelineConfigAssembler`

The minimal requirement is that it can satisfy the usage pattern already present in `src/controller/pipeline_controller.py`:

- `.build_from_gui_input()` with optional:
  - `overrides`
  - `lora_settings`
  - `randomizer_metadata`

Implementation rule:

- reuse current `AppController` configuration access and normalization patterns where possible
- do **not** move execution logic into this class
- this class only builds compatibility config snapshots from GUI/controller state

### 3. Recreate the missing archive package as a thin shim only

Create these shim files:

- `src/controller/archive/__init__.py`
- `src/controller/archive/pipeline_config_types.py`
- `src/controller/archive/pipeline_config_assembler.py`

Each shim file must do **re-export only**.

Examples:

```python
from src.controller.pipeline_config_types import PipelineConfig
```

```python
from src.controller.pipeline_config_assembler import GuiOverrides, PipelineConfigAssembler
```

No logic. No duplication. No new dataclasses inside the archive package.

### 4. Tighten architecture enforcement one step

Update `tests/system/test_architecture_enforcement_v2.py` so the allowlist remains temporary but now documents the migration shape correctly.

Expected allowlist after this PR:

- `src/controller/archive/pipeline_config_types.py`
- `src/controller/archive/pipeline_config_assembler.py`
- `src/controller/app_controller.py`
- `src/controller/pipeline_controller.py`
- `src/pipeline/legacy_njr_adapter.py`

The important change is that the archive package becomes an explicit shim rather than a missing ghost dependency.

## Verification

Run exactly:

```cmd
python -m compileall src/controller/pipeline_config_types.py src/controller/pipeline_config_assembler.py src/controller/archive
pytest tests/system/test_architecture_enforcement_v2.py -q
pytest tests/controller/test_pipeline_controller_config_path.py -q
pytest --collect-only -q
```

## Success criteria

- `src.controller.archive` becomes importable again.
- Source and test collection errors caused by the **missing package** disappear.
- No production execution path starts consuming raw `PipelineConfig` again.

## Caveat

This PR is allowed to leave active source imports pointing to the archive shim. That is intentional. The next PR removes them.

---

# PR-MIG-102 — Migrate live source off archive imports

## BLUF

Once the missing-package failure is gone, migrate the **live source files** off the archive shim and onto the new canonical non-archive modules created in PR-MIG-101.

## Why this PR exists

PR-MIG-101 restores repo importability. PR-MIG-102 restores architectural truth.

## Allowed Files

- `src/controller/app_controller.py`
- `src/controller/pipeline_controller.py`
- `src/pipeline/legacy_njr_adapter.py`
- `tests/system/test_architecture_enforcement_v2.py`
- `docs/PR_MAR26/PR-MIG-102-Migrate-Live-Source-Off-Archive-Imports.md` **(new)**

## Forbidden Files

- `src/controller/archive/**` except import-only cleanup if required
- `src/gui/**`
- `src/queue/**`
- `src/pipeline/pipeline_runner.py`

## Exact implementation intent

### 1. Change source imports

Replace in live source only:

- `from src.controller.archive.pipeline_config_types import PipelineConfig`
  -> `from src.controller.pipeline_config_types import PipelineConfig`
- `from src.controller.archive.pipeline_config_assembler import ...`
  -> `from src.controller.pipeline_config_assembler import ...`

The three primary source files are already known:

- `src/controller/app_controller.py`
- `src/controller/pipeline_controller.py`
- `src/pipeline/legacy_njr_adapter.py`

### 2. Remove runtime “best effort archive import” messaging from live code

Where comments currently say things like “archive-only legacy dataclass” or “Compat import: moved to archive types,” rewrite them so they say the real state:

- `PipelineConfig` now lives at `src.controller.pipeline_config_types`
- archive path is temporary import compatibility only
- production execution still runs through NJR

### 3. Do not yet delete shim files

The archive shim remains because tests may still import it. That deletion is later.

### 4. Tighten architecture test allowlist

After this PR, `tests/system/test_architecture_enforcement_v2.py` should allow archive imports **only inside the shim package itself**.

Expected allowlist after this PR:

- `src/controller/archive/pipeline_config_types.py`
- `src/controller/archive/pipeline_config_assembler.py`

No live source file should remain on the allowlist.

## Verification

Run:

```cmd
python -m compileall src/controller/app_controller.py src/controller/pipeline_controller.py src/pipeline/legacy_njr_adapter.py
pytest tests/system/test_architecture_enforcement_v2.py -q
pytest tests/controller/test_pipeline_controller_run_modes_v2.py tests/controller/test_controller_event_api_v2.py -q
pytest --collect-only -q
```

## Success criteria

- No live source import from `src.controller.archive.*` remains.
- Architecture guard only allowlists the shim files themselves.
- Collection count improves materially.

## Caveat

Do not spend this PR converting all tests yet. Source first, tests second.

---

# PR-MIG-103 — Zero collection errors and test import triage

## BLUF

Make `pytest --collect-only` authoritative. This PR is where test imports, test categorization, and optional-dependency treatment are cleaned up enough to reach **zero repo-caused collection errors**.

## Why this PR exists

Right now the suite cannot serve as a merge gate because collection dies too early. That has to be fixed before larger refactors.

## Allowed Files

- `tests/**`
- `pytest.ini`
- `pyproject.toml`
- `requirements.txt`
- `docs/PR_MAR26/PR-MIG-103-Zero-Collection-Errors-and-Test-Import-Triage.md` **(new)**

## Forbidden Files

- `src/pipeline/pipeline_runner.py`
- `src/pipeline/executor.py`
- `src/controller/app_controller.py`
- `src/controller/pipeline_controller.py`

Use this PR to fix **test-side collection** unless a source fix is strictly unavoidable.

## Exact implementation intent

### 1. Categorize collection failures into three buckets

Create a working checklist in the PR doc with each failing test assigned to one bucket:

- **Bucket A — archive import fallout**
- **Bucket B — optional dependency/bootstrap**
- **Bucket C — stale/legacy test still asserting removed behavior**

### 2. Update active tests to canonical imports

For active tests that should continue to live, replace:

- `src.controller.archive.pipeline_config_types`
- `src.controller.archive.pipeline_config_assembler`

with:

- `src.controller.pipeline_config_types`
- `src.controller.pipeline_config_assembler`

### 3. Quarantine true legacy-behavior tests

For tests whose purpose is only to validate old compatibility behavior, move them to one of these patterns:

- `tests/compat/**` if they still matter as migration-compat tests
- or mark them explicitly with `@pytest.mark.legacy` if the repo already has that convention
- or delete them if they validate behavior the repo no longer supports and no migration promise exists

Do not leave ambiguous “active” tests importing shim paths unless the test is explicitly about shim compatibility.

### 4. Handle `requests_mock` correctly

The package is already declared in repo dependency files. Therefore:

- if CI/bootstrap is not installing the dev/test dependency set, fix that in later CI PRs
- for this PR, do **not** paper over the missing dependency by rewriting those tests away
- only touch dependency metadata here if test installation really is inconsistent across repo files

### 5. End state of collection

By the end of this PR:

- active tests should import canonical modules
- shim imports should exist only in explicit compat tests, if any
- `pytest --collect-only -q` must finish with `0 errors`

## Verification

Run:

```cmd
pytest --collect-only -q
pytest tests/system/test_architecture_enforcement_v2.py -q
pytest tests/controller -q -k "not legacy"
pytest tests/journeys -q -k "not legacy"
```

## Success criteria

- `pytest --collect-only -q` ends with zero errors.
- Remaining failing tests, if any, are runtime/assertion failures, not import/collection failures.

## Caveat

Do not accept “zero collection errors except for local env.” If a dependency is mandatory for the declared test surface, bootstrap must eventually install it.

---

# PR-MIG-104 — Split PipelineController into build, submit, and execute services

## BLUF

`PipelineController` is too large and still mixes config assembly, preview building, queue submission, and execution glue. Split it without changing the public controller facade.

## Why this PR exists

Once collection is healthy, the next architectural risk is controller concentration. `PipelineController` is the smaller of the two large controllers, so it should be split first.

## Allowed Files

- `src/controller/pipeline_controller.py`
- `src/controller/services/pipeline_preview_service.py` **(new)**
- `src/controller/services/pipeline_submission_service.py` **(new)**
- `src/controller/services/pipeline_execution_service.py` **(new)**
- `tests/controller/test_pipeline_controller_run_modes_v2.py`
- `tests/controller/test_pipeline_controller_queue_mode.py`
- `tests/controller/test_pack_draft_to_normalized_preview_v2.py`
- `docs/PR_MAR26/PR-MIG-104-Split-PipelineController-Into-Build-Submit-Execute-Services.md` **(new)**

## Forbidden Files

- `src/controller/app_controller.py`
- `src/pipeline/pipeline_runner.py`
- `src/queue/**`

## Exact implementation intent

### 1. Keep `PipelineController` as the GUI-facing facade

Do not break GUI callers. The public methods stay on `PipelineController`.

### 2. Extract preview/build responsibilities

Move methods centered on preview job construction and state-to-job translation into `pipeline_preview_service.py`.

Expected responsibilities:

- prompt-pack bundle -> NJRs
- preview jobs from current app state
- preview summary DTO helpers if they belong to preview generation

### 3. Extract submission responsibilities

Move queue conversion/submission logic into `pipeline_submission_service.py`.

Expected responsibilities:

- `NormalizedJobRecord` -> `Job`
- queue metadata and run-mode normalization
- submission through `JobService`

### 4. Extract execution responsibilities

Move `_run_job` / execution-specific orchestration into `pipeline_execution_service.py`.

Expected responsibilities:

- execute from job containing `_normalized_record`
- call `PipelineRunner.run_njr(...)`
- capture result/error envelopes

### 5. Leave the controller thin

At the end of this PR, `PipelineController` should mostly:

- delegate
- maintain controller-local state
- wire callbacks

It should not remain the place where most run logic lives.

## Verification

Run:

```cmd
python -m compileall src/controller/pipeline_controller.py src/controller/services
pytest tests/controller/test_pipeline_controller_run_modes_v2.py tests/controller/test_pipeline_controller_queue_mode.py tests/controller/test_pack_draft_to_normalized_preview_v2.py -q
pytest --collect-only -q
```

## Success criteria

- `PipelineController` is materially smaller.
- No behavior change to the external controller surface.
- Preview, submit, and execute responsibilities are separable in code review.

## Caveat

Do not create generic “utils.” These must be named services with explicit responsibilities.

---

# PR-MIG-105 — Shrink AppController run and config responsibilities

## BLUF

`AppController` is still the largest structural risk in the repo. This PR removes run-specific and config-compat responsibilities that now belong elsewhere.

## Why this PR exists

At ~6245 LOC, `AppController` is still acting as a gravity well. The migration will keep drifting until run/config work is carved away.

## Allowed Files

- `src/controller/app_controller.py`
- `src/controller/services/app_run_bridge_service.py` **(new)**
- `src/controller/services/app_pipeline_config_service.py` **(new)**
- `tests/controller/test_app_controller_pipeline_integration.py`
- `tests/controller/test_app_controller_run_bridge_v2.py`
- `tests/controller/test_app_to_pipeline_run_bridge_v2.py`
- `docs/PR_MAR26/PR-MIG-105-Shrink-AppController-Run-and-Config-Responsibilities.md` **(new)**

## Forbidden Files

- `src/pipeline/pipeline_runner.py`
- `src/queue/**`
- `src/gui/**`

## Exact implementation intent

### 1. Extract deprecated PipelineConfig construction into a dedicated service

Take the `_build_pipeline_config()` / `build_pipeline_config_v2()` responsibility out of `AppController` and place it behind `app_pipeline_config_service.py`.

That service should:

- read current GUI/controller config
- construct compatibility `PipelineConfig`
- remain clearly labeled as deprecated migration support

This change matters because it isolates the compatibility burden.

### 2. Extract run-bridge logic out of AppController

Move methods that primarily hand off from app-level GUI actions into the pipeline layer into `app_run_bridge_service.py`.

This should include run-start bridging logic that does not need to live on the main application controller.

### 3. Preserve public behavior

The GUI should still be able to call the same high-level app actions. This is a structural split, not a UX redesign.

## Verification

Run:

```cmd
python -m compileall src/controller/app_controller.py src/controller/services
pytest tests/controller/test_app_controller_run_bridge_v2.py tests/controller/test_app_to_pipeline_run_bridge_v2.py tests/controller/test_app_controller_pipeline_integration.py -q
pytest --collect-only -q
```

## Success criteria

- `AppController` loses the deprecated config-construction bulk.
- Run bridge logic is no longer embedded directly in the main controller.
- No new execution path is introduced.

## Caveat

Do not try to fully decompose `AppController` in one PR. Only move run/config responsibilities.

---

# PR-MIG-106 — Unify run request and config DTO boundary

## BLUF

The repo needs a single explicit boundary between GUI intent and executable NJR-based work. This PR defines that boundary clearly instead of letting preview, queue, replay, and reprocess each improvise it.

## Why this PR exists

The repo already has good pieces:

- `config_normalizer.py`
- `artifact_contract.py`
- NJR

But the controller seam is still muddy. This PR makes it explicit.

## Allowed Files

- `src/pipeline/job_requests_v2.py`
- `src/controller/pipeline_config_types.py`
- `src/controller/pipeline_config_assembler.py`
- `src/pipeline/config_normalizer.py`
- `src/pipeline/legacy_njr_adapter.py`
- `tests/pipeline/test_config_normalizer.py`
- `tests/pipeline/test_run_modes.py`
- `tests/journeys/test_njr_modern_pattern.py`
- `docs/PR_MAR26/PR-MIG-106-Unify-Run-Request-and-Config-DTO-Boundary.md` **(new)**

## Forbidden Files

- `src/pipeline/pipeline_runner.py` except if a tiny type import fix is required
- `src/gui/**`

## Exact implementation intent

### 1. Define the boundary clearly

There should now be three distinct object roles:

- `PipelineConfig` — deprecated controller-boundary compatibility DTO
- `PipelineRunRequest` / run request types — explicit request object for queue/direct/replay/reprocess submission
- `NormalizedJobRecord` — the execution object consumed by the runner

### 2. Make the adapter path explicit and narrow

`legacy_njr_adapter.py` should become the only sanctioned place that translates compatibility `PipelineConfig` into NJR.

No other source module should recreate this translation ad hoc.

### 3. Normalize run modes through the request layer

Preview, queue, replay, and reprocess should all converge through one request model before NJR execution.

The exact field names can follow current `job_requests_v2.py`, but the architectural rule must become visible in code and tests.

## Verification

Run:

```cmd
pytest tests/pipeline/test_config_normalizer.py tests/pipeline/test_run_modes.py tests/journeys/test_njr_modern_pattern.py -q
pytest --collect-only -q
```

## Success criteria

- Repo has one documented DTO boundary instead of several implicit ones.
- `legacy_njr_adapter.py` is isolated and justified.
- Tests prove the modern pattern and the compat path separately.

## Caveat

Do not try to delete the adapter in this PR. Narrow it first; delete later.

---

# PR-MIG-107 — Tighten architecture guards to migration completion

## BLUF

The current architecture test mostly limits spread. It does not prove completion. This PR flips it into a completion-oriented guard.

## Why this PR exists

Now that source and tests should be off archive imports, the repo needs enforcement that matches the intended target state.

## Allowed Files

- `tests/system/test_architecture_enforcement_v2.py`
- `docs/PR_MAR26/PR-MIG-107-Tighten-Architecture-Guards-to-Migration-Completion.md` **(new)**

## Forbidden Files

- `src/**`
- `tests/**` outside the architecture guard file

## Exact implementation intent

### 1. Remove the archive import allowlist completely

By the end of this PR, any import of:

- `src.controller.archive.pipeline_config_types`
- `src.controller.archive.pipeline_config_assembler`

outside the shim package itself should fail the architecture test.

### 2. Add a second rule: no live source may reference `PipelineConfig` for production execution

You do **not** need to ban `PipelineConfig` everywhere. You do need to forbid patterns that indicate production execution is using it directly.

Examples of patterns worth checking:

- direct call from controller to runner with `PipelineConfig`
- new non-adapter helper that translates `PipelineConfig` to execution payload outside `legacy_njr_adapter.py`

### 3. Keep the existing GUI-to-runner direct-call guard

That part is still useful and should remain.

## Verification

Run:

```cmd
pytest tests/system/test_architecture_enforcement_v2.py -q
pytest --collect-only -q
```

## Success criteria

- No live code can quietly backslide into archive imports.
- No new direct `PipelineConfig` execution path can be added without failing the guard.

---

# PR-MIG-108 — Harden journey, queue, and recovery gates

## BLUF

Once structural migration is closed, the next priority is proving the substrate under stress: journey execution, queue lifecycle, and failure/recovery semantics.

## Why this PR exists

The repo has already invested in queue, checkpoint, recovery, and diagnostics. The next gap is confidence, not feature breadth.

## Allowed Files

- `tests/journeys/**`
- `tests/controller/test_controller_queue_execution.py`
- `tests/controller/test_job_queue_integration_v2.py`
- `tests/controller/test_heartbeat_stall_fix.py`
- `.github/workflows/ci.yml`
- `.github/workflows/journey-tests.yml`
- `docs/PR_MAR26/PR-MIG-108-Harden-Journey-Queue-and-Recovery-Gates.md` **(new)**

## Forbidden Files

- `src/controller/app_controller.py`
- `src/controller/pipeline_controller.py`
- `src/pipeline/pipeline_runner.py`

This PR is for test and gate hardening, not runtime redesign.

## Exact implementation intent

### 1. Add destructive-semantics coverage where missing

Strengthen coverage for:

- cancel current job while queued work remains
- pause/resume around active and idle runner states
- watchdog stall event propagation
- recovery attempt recorded into history/incident surfaces

Use fake or deterministic runners first. Do not create flaky real-process tests unless absolutely necessary.

### 2. Promote a stable required gate subset in CI

The required CI subset after this PR should include at minimum:

- architecture enforcement
- collect-only
- deterministic controller/pipeline subset
- stable journey subset

If the full journey matrix is not reliable enough to be required, keep it visible and separate. Do not hide failures with `|| true`.

## Verification

Run:

```cmd
pytest tests/system/test_architecture_enforcement_v2.py -q
pytest --collect-only -q
pytest tests/controller/test_controller_queue_execution.py tests/controller/test_job_queue_integration_v2.py tests/controller/test_heartbeat_stall_fix.py -q
pytest tests/journeys -q -k "jt01 or jt03 or modern_pattern"
```

## Success criteria

- required CI gates become credible
- queue/recovery semantics are tested beyond happy-path unit coverage

---

# PR-MIG-109 — Delete compat shim and legacy PipelineConfig bridge

## BLUF

This is the cleanup PR that makes the migration honest. Once source, tests, and architecture guards are clean, remove the shim and the transitional bridge code that no longer serves active behavior.

## Why this PR exists

A compatibility shim that survives after its callers are gone becomes permanent debt. This PR prevents that.

## Allowed Files

- `src/controller/archive/__init__.py`
- `src/controller/archive/pipeline_config_types.py`
- `src/controller/archive/pipeline_config_assembler.py`
- `src/pipeline/legacy_njr_adapter.py`
- `tests/compat/**`
- `tests/system/test_architecture_enforcement_v2.py`
- `docs/PR_MAR26/PR-MIG-109-Delete-Compat-Shim-and-Legacy-PipelineConfig-Bridge.md` **(new)**

## Forbidden Files

- `src/gui/**`
- `src/queue/**`
- `src/pipeline/pipeline_runner.py`

## Exact implementation intent

### 1. Delete the archive shim package

Remove:

- `src/controller/archive/__init__.py`
- `src/controller/archive/pipeline_config_types.py`
- `src/controller/archive/pipeline_config_assembler.py`

### 2. Reassess `legacy_njr_adapter.py`

If compatibility `PipelineConfig` is still needed for explicit compat tests, keep the adapter but have it import from the canonical non-archive module.

If no supported compat path remains, delete the adapter and its explicit compat tests in the same PR.

### 3. Finalize the architecture guard

The guard should now fail on **any** archive import because the package is gone again — this time intentionally.

## Verification

Run:

```cmd
pytest tests/system/test_architecture_enforcement_v2.py -q
pytest --collect-only -q
pytest tests/compat -q
```

## Success criteria

- `src/controller/archive` is truly gone.
- The repo stays green at collection time.
- Any remaining compatibility support is explicit, canonical, and non-archive.

---

## External-agent sufficiency check

This sequence is executable because each PR now answers the questions an external agent needs answered:

### What exactly am I changing?

Each PR lists exact files to create, modify, or delete.

### What is the intended end-state of those files?

Each PR includes a concrete target state, not just a theme.

### What am I not allowed to touch?

Each PR has forbidden files to stop drift.

### How do I know I completed the intent?

Each PR has deterministic verification commands and success criteria.

### How do temporary shims avoid becoming permanent?

The shim is introduced only in PR-MIG-101 and explicitly deleted in PR-MIG-109.

### Where are the risky boundaries?

The backlog explicitly marks these as the risky seams:

- missing archive package versus true migration
- source imports versus test imports
- compatibility DTO versus execution payload
- structural split versus runtime change

---

## Recommended execution order

This order matters.

```text
PR-MIG-101
PR-MIG-102
PR-MIG-103
PR-MIG-104
PR-MIG-105
PR-MIG-106
PR-MIG-107
PR-MIG-108
PR-MIG-109
```

Do not skip PR-MIG-103. Collection health is the hard gate before deeper refactors.

---

## Final note

This backlog is designed to minimize the two biggest failure modes in the current repo:

1. deleting legacy seams before there is a safe canonical replacement
2. claiming migration completion while architecture and tests still encode the transitional state

