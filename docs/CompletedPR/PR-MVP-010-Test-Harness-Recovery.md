# PR-MVP-010 - Test Harness Recovery

Status: Completed
Priority: HIGH
Effort: MEDIUM
Phase: Phase 1 - Make verification trustworthy
Date: 2026-09-06

## 2. Context & Motivation

`PR-MVP-000` restored repository completeness and `PR-MVP-005` classified
later-branch changes without importing them. Contract migrations cannot be
trusted until collection and the required CI gate mean what their names say.

The repository has two competing pytest configurations. Default collection
uses `pytest.ini`, warns that it ignores the settings in `pyproject.toml`, and
reports 3,092 tests. Forcing the stricter `pyproject.toml` policy reports 3,141
tests but fails with three collection errors: an archived GUI test imports a
missing module, an archived/current GUI pair has an import-name collision, and
a live-Tk/quarantine pair has another collision.

The current `tools/ci/run_required_smoke.py` starts from all of `tests/` and
removes a few directories. The audited command selected 2,413 tests, ran for
87.70 seconds, failed in legacy compatibility coverage, ran WebUI/Comfy
emergency cleanup handlers, modified tracked `data/webui_cache.json`, and
created repository-root `output/`. It is not a small or isolated smoke gate.

Collection also imports three root scripts with immediate module behavior.
`tests/test_full_flow.py` rewrites a tracked PromptPack,
`tests/test_img2img_bug.py` writes a root temporary pack, and
`tests/test_stage_chain_fix.py` asserts during import. Maintained or manual
counterparts already exist in the appropriate test directories.

Finally, 30 generated files remain tracked under five
`tmp_prompt_pack_probe*` roots. `PR-MVP-005` classified their deletion as
`ADOPT` and assigned it here. That disposition also rejected tracked runtime
cache state and assigned its pollution guard here.

This PR makes tests usable evidence; it does not make stale behavior canonical
because a historical test passes. It is governed by
`docs/ARCHITECTURE_v2.6.md`,
`docs/StableNew_Coding_and_Testing_v2.6.md`, the Finalized MVP Roadmap, and
`docs/CompletedPR/PR-MVP-005-Post-Baseline-Delta-Disposition.md`.

## 3. Goals & Non-Goals

### Goals

1. Make `pyproject.toml` the only pytest configuration authority.
2. Make strict default collection succeed without archive, quarantine,
   manual-script, legacy-GUI, or live-display-only surfaces.
3. Replace negative-selection smoke with an explicit architecture-current
   allowlist.
4. Run collection and smoke with deterministic no-WebUI/test-mode defaults and
   fail either gate on repository mutation.
5. Make fakes the journey default and require explicit real-backend opt-in.
6. Remove the three import-executed root scripts and 30 tracked probe artifacts.
7. Stop tracking the machine-local WebUI cache while preserving isolated cache
   behavior in tests.
8. Synchronize CI, the test manifest, developer commands, and canonical testing
   documentation.

### Non-goals

1. Do not change production code or NJR, compiler, queue, runner, controller,
   GUI, persistence, PromptPack, image, or video runtime contracts.
2. Do not make all historical tests required or call them architecture-current.
3. Do not repair obsolete legacy/compat assertions in this PR.
4. Do not use network, WebUI, ComfyUI, GPU, model downloads, Tk, or timing
   sleeps in a required gate.
5. Do not delete user packs, outputs, reports, or state beyond the exact
   generated paths below.
6. Do not merge or cherry-pick any comparison branch.
7. Do not pin a collection count; later contract PRs must replace tests.

## 4. Guardrails

- The production path remains typed intent -> compiler -> immutable NJR ->
  JobService -> queue/repository -> `PipelineRunner.run_njr` -> typed handler ->
  artifacts/history.
- Required smoke may prove repository, isolation, and queue-only invariants. It
  must not bless legacy `DIRECT`, universal PromptPack identity, mutable NJR
  state, or JSON/JSONL as the target persistence model.
- Compatibility, integration, journey, learning, cluster, and broad video
  suites are not required merely because pytest can collect them.
- `tests/gui_v2/` remains collectable and headless-safe. `tests/gui/`,
  `tests/gui_v1_legacy/`, `tests/quarantine/`, `tests/legacy/`,
  `tests/scripts/`, and every `archive/` tree are excluded by default.
- Isolation redirects mutable cache/log/output paths; it must not globally
  suppress behavior that focused unit tests exercise.
- Gates compare repository state before and after execution and return nonzero
  on pollution. CI starts from and ends with a clean checkout.
- No production NJR, queue, runner, controller, or GUI file may change.
- The 30 probe files are generated debris and may be deleted. A developer-local
  WebUI cache may remain after it is untracked and ignored.

## 5. Allowed Files

### Files to Create

- `tools/ci/run_collection_gate.py`
- `tools/ci/run_ruff_baseline.py`
- `tools/ci/ruff_baseline.json`
- `docs/CompletedPR/PR-MVP-010-Test-Harness-Recovery.md` (closeout only)

### Files to Modify

- `.gitignore`
- `.github/workflows/ci.yml`
- `.github/copilot-instructions.md`
- `README.md`
- `pyproject.toml`
- `tools/ci/run_required_smoke.py`
- `tests/conftest.py`
- `tests/journeys/conftest.py`
- `tests/controller/test_core_run_path_v2.py`
- `tests/safety/test_runtime_state_hygiene.py`
- `tests/system/test_ci_truth_sync_v2.py`
- `tests/regression/test_snapshot_regression_v2.py`
- `tests/TEST_SURFACE_MANIFEST.md`
- `docs/StableNew_Coding_and_Testing_v2.6.md`
- `docs/StableNew Roadmap v2.6.md`
- `docs/DOCS_INDEX_v2.6.md`
- `docs/PR_Backlog/PR-MVP-010-Test-Harness-Recovery.md` (implementation notes
  and closeout move only)

### Files to Delete or Untrack

- `pytest.ini`
- `data/webui_cache.json` (remove from Git tracking; keep local cache ignored)
- `tests/test_full_flow.py`
- `tests/test_img2img_bug.py`
- `tests/test_stage_chain_fix.py`
- `tmp_prompt_pack_probe/**` (6 tracked files)
- `tmp_prompt_pack_probe2/**` (5 tracked files)
- `tmp_prompt_pack_probe3/**` (6 tracked files)
- `tmp_prompt_pack_probe4/**` (7 tracked files)
- `tmp_prompt_pack_probe5/**` (6 tracked files)
- `docs/PR_Backlog/PR-MVP-010-Test-Harness-Recovery.md` (closeout only, after
  the completed record exists)

### Forbidden Files

- `src/**`
- `packs/**`
- every other file under `data/**`, `state/**`, `output/**`, `reports/**`, or
  `runs/**`
- every other test file
- every workflow except `.github/workflows/ci.yml`
- every file not explicitly listed above

## 6. Implementation Plan

### Step 1 - Consolidate pytest configuration

Delete `pytest.ini`. In `pyproject.toml`, use `testpaths = ["tests"]`, strict
configuration and markers, `--import-mode=importlib`, and exact root-relative
default exclusions for the non-active surfaces in section 4. Do not exclude
`tests/gui_v2/`.

Register the complete custom marker vocabulary used by collected tests:
`compat`, `core_e`, `golden_path`, `gp1` through `gp15`, `gui`, `integration`,
`journey`, `legacy`, `real_backend`, `slow`, `smoke`, `snapshot_regression`,
`summary`, and `timeout`. Registration does not make a surface required.

Update `tests/system/test_ci_truth_sync_v2.py` to enforce one authority, strict
import behavior, explicit exclusions, and the named CI scripts.

### Step 2 - Remove collection-time scripts

Delete the three root files listed in section 5.
`tests/scripts/test_full_flow.py` and `tests/scripts/test_img2img_bug.py` remain
manual references excluded from collection.
`tests/pipeline/test_stage_chain_fix.py` remains the pytest-owned coverage.

Do not sweep other duplicate/stale tests. The manifest must identify that debt
for the contract PR owning each subsystem.

### Step 3 - Establish deterministic isolation

In `tests/conftest.py`:

1. set `STABLENEW_NO_WEBUI=1` and `STABLENEW_TEST_MODE=1` for every test;
2. redirect `src.api.webui_process_manager._WEBUI_CACHE_FILE` to the standard
   pytest `tmp_path` instead of suppressing cache logic;
3. retain bounded API/WebUI discovery fakes;
4. remove the custom override of pytest's built-in `tmp_path` fixture.

In `tests/journeys/conftest.py`, use the mock WebUI client unless
`STABLENEW_REAL_BACKEND_TESTS=1` is explicit. `CI` must not choose a different
semantic path. Real-backend runs never enter required smoke.

In `tests/controller/test_core_run_path_v2.py`, root `StructuredLogger` under
`tmp_path` and close it deterministically without weakening queue/NJR/no-fallback
assertions.

### Step 4 - Define clean collection and positive smoke

Create `tools/ci/run_collection_gate.py` to run strict
`python -m pytest --collect-only -q` with repository imports available, a
disposable working directory, deterministic environment flags, and before/after
repository-content comparison.

Rewrite `tools/ci/run_required_smoke.py` to select only:

```text
tests/system/test_repository_completeness_v2.py
tests/system/test_architecture_enforcement_v2.py
tests/system/test_ci_truth_sync_v2.py
tests/safety/test_runtime_state_hygiene.py
tests/state/test_workspace_paths.py
tests/state/test_output_routing.py
tests/controller/test_core_run_path_v2.py
tests/queue/test_job_service_pipeline_integration_v2.py::TestQueuedModeExecution
tests/queue/test_job_service_pipeline_integration_v2.py::TestQueueErrorHandling
```

The runner uses the same disposable cwd, environment, import path, and
before/after content check. It must not select all tests and subtract paths.
`TestLegacyDirectNormalization` and `TestDirectQueueParity` are deliberately
omitted: compatibility is not the target architecture. Changes to this list
must update CI truth tests, the manifest, and canonical testing docs together.

### Step 5 - Remove tracked generated state

Delete the 30 tracked probe files. Add exact root-anchored ignores for the five
probe roots and `/data/webui_cache.json`; do not use a broad rule that could hide
source or user content.

Extend `tests/safety/test_runtime_state_hygiene.py` so tracking any probe root,
`data/webui_cache.json`, root `state/`, or
`src/state/queue_state_v2.json` fails.

### Step 6 - Ratchet existing lint debt without hiding it

Pin Ruff `0.14.9` in the development and CI environment. Record the 2,208
existing findings in `tools/ci/ruff_baseline.json` as counts keyed by
repository-relative source path and rule code. Add
`tools/ci/run_ruff_baseline.py` to run Ruff JSON output and fail when:

1. Ruff's version differs from the baseline version;
2. a new path/rule key appears;
3. any existing path/rule count increases; or
4. Ruff cannot complete or its output cannot be parsed.

Counts may decrease without regenerating the baseline. Baseline regeneration
requires an approved PR and may never raise a count. This ratchet replaces the
impossible raw `ruff check src` required command; it does not call the findings
acceptable.

Repair `tests/regression/test_snapshot_regression_v2.py` by removing its
duplicate `pytest_plugins` registration and consuming the existing root
`stubbed_job_service_with_queue` fixture. Do not change snapshot assertions or
production behavior.

### Step 7 - Make CI state the real gate

Update `.github/workflows/ci.yml` so the required Python 3.11/3.12 matrix runs:

1. repository completeness;
2. `python tools/ci/run_ruff_baseline.py` and the existing mypy smoke;
3. `python tools/ci/run_collection_gate.py`;
4. `python tools/ci/run_required_smoke.py`;
5. a final clean-tree assertion.

The broader suite may remain non-blocking during migration, but must consume
the same configuration and must not be called authoritative or real-backend.

### Step 8 - Synchronize docs and close out

Update `tests/TEST_SURFACE_MANIFEST.md` to distinguish required, collected,
optional, compatibility, real-backend, manual, quarantine, and archive
surfaces. Presence does not make cluster, learning, broad video, or compat tests
part of the conservative MVP.

Update the exact commands and isolation contract in README,
`.github/copilot-instructions.md`, and
`docs/StableNew_Coding_and_Testing_v2.6.md`. Because the last file is Tier 2,
the completed record must cite implemented scripts, CI, and actual Python
3.11/3.12 results as validation.

After all gates pass, move this spec to one completed record, update the
Finalized MVP Roadmap and docs index, and remove the backlog copy.

## 7. Testing Plan

### Unit tests

```powershell
python -m pytest -q tests/system/test_ci_truth_sync_v2.py
python -m pytest -q tests/safety/test_runtime_state_hygiene.py
python -m pytest -q tests/controller/test_core_run_path_v2.py
```

### Integration tests

```powershell
python tools/ci/check_repository_completeness.py
python tools/ci/run_ruff_baseline.py
python tools/ci/run_collection_gate.py
python tools/ci/run_required_smoke.py
python tools/ci/run_mypy_smoke.py
```

Run collection and smoke in a normal worktree and a tracked-files-only
disposable checkout after a candidate commit exists.

### Journey or smoke coverage

The positive list in step 4 is the only required pytest execution subset.
Verify separately that the journey fixture uses a fake with no special
environment and only constructs a real client with
`STABLENEW_REAL_BACKEND_TESTS=1`. Do not contact a real service.

### Manual verification

```powershell
git ls-files -- 'tmp_prompt_pack_probe*' 'data/webui_cache.json'
python -m pytest --trace-config --collect-only -q
git status --short
```

The first command prints nothing. Pytest reports only `pyproject.toml`, has no
collection/marker warning, and neither gate changes repository state. CI must
pass on Python 3.11 and 3.12; the local Python 3.10 audit is not certification.

## 8. Verification Criteria

### Success criteria

1. `pytest.ini` is absent and pytest uses only `pyproject.toml`.
2. Strict collection has no import mismatch, archived missing module, unknown
   marker, network, display, or mutation failure.
3. Required smoke contains only the positive targets in step 4.
4. Collection and smoke fail if their subprocess changes repository contents.
5. Smoke finishes without external backends, GPU, Tk, or process cleanup.
6. The three import-executed root scripts are absent.
7. Git tracks no probe artifact or `data/webui_cache.json`.
8. Hygiene tests and root-anchored ignores prevent recurrence.
9. Required CI passes from clean checkouts on Python 3.11 and 3.12.
10. CI, scripts, manifest, and active docs describe the same gates.

### Failure criteria

1. Two pytest authorities remain or the lenient configuration hides failures.
2. Required smoke is all tests minus exclusions.
3. Required tests canonize legacy `DIRECT` or universal PromptPack identity.
4. A gate passes after repository mutation.
5. Journey defaults can contact a real backend without opt-in.
6. Isolation changes production code or globally disables cache behavior.
7. Any non-allowlisted pack, state, output, report, source, or branch changes.
8. Python 3.10-only evidence is presented as release certification.

## 9. Risk Assessment

### Low-risk areas

- Removing generated probes and adding exact ignore rules.
- Removing the redundant pytest configuration after consolidation.
- Synchronizing docs and the test manifest.

### Medium-risk areas with mitigation

- Exclusions can hide useful tests. Keep `tests/gui_v2/` collectable, document
  every excluded surface, and retain explicit-path optional execution.
- Importlib mode can expose hidden name coupling. Strict full collection is an
  exit gate; do not weaken isolation to silence it.
- Global safety fixtures can mask cache tests. Redirect the cache path rather
  than replacing `_save_webui_cache`.
- Threaded queue tests can flake. Use bounded event/poll synchronization and
  deterministic teardown, never fixed sleeps as synchronization.

### High-risk areas with mitigation

- Broad green tests can freeze obsolete architecture. Use the exact positive
  list, exclude direct-compat classes, and require review for list changes.
- A dirty worktree can hide same-status mutations. Compare content/state, start
  CI clean, and prove the result again in a tracked-files-only checkout.
- Untracking the cache can be mistaken for disabling it. Preserve creation,
  ignore only its exact path, and test against a redirected temporary file.

### Rollback plan

Revert this PR as one commit if consolidated gates cannot collect on both
supported Python versions. Do not independently restore generated probes or
tracked cache state. Amend the manifest and positive list in a new approved PR
if an excluded suite is later proven MVP-critical.

## 10. Tech Debt Analysis

### Debt removed

- Competing pytest authorities and misleading smoke selection.
- Import-time pack/cache/output mutation in active collection.
- Environment-dependent real-backend defaults.
- Thirty tracked probe files and one tracked machine cache.
- The custom `tmp_path` override.
- CI/docs/manifest drift about required tests.

### Debt intentionally deferred

- NJR/serializer tests: `PR-MVP-020`.
- Direct-mode, broad-dict submission, queue/controller compat, and related
  duplicates: `PR-MVP-030`.
- JSON/JSONL persistence tests: `PR-MVP-040`.
- Paired PromptPack tests: `PR-MVP-050`.
- Broad image GUI/integration promotion: `PR-MVP-060`.
- Non-native video quarantine and native SVD proof: `PR-MVP-070`.
- Learning/cluster/post-MVP surface quarantine: `PR-MVP-080`.
- Final release inventory and remaining harmless duplicate cleanup:
  `PR-MVP-090`.

### Ruff debt burn-down plan

1. `PR-MVP-010` freezes the 2,208-finding file/rule baseline and blocks every
   increase.
2. `PR-MVP-020` and `PR-MVP-030` remove all Ruff findings in every NJR,
   compiler, submission, and related test file they touch; their baseline
   counts must decrease.
3. `PR-MVP-040` through `PR-MVP-070` apply the same touched-file-zero rule to
   persistence, PromptPack, image, and video slices.
4. `PR-MVP-080` owns bounded mechanical cleanup of untouched source findings,
   split by subsystem if a single review would become unsafe.
5. `PR-MVP-090` may not certify release while any baseline count is nonzero.
   The baseline is deleted only with a clean raw `ruff check src` result.

## 11. Documentation Updates

- `docs/StableNew_Coding_and_Testing_v2.6.md`: implement single-config,
  collection, isolation, and positive-smoke truth; remain active.
- `tests/TEST_SURFACE_MANIFEST.md`: implement the approved taxonomy; remain
  active.
- README and `.github/copilot-instructions.md`: publish exact commands; remain
  active.
- Finalized MVP Roadmap: mark completion only after gates pass and make
  `PR-MVP-020` next; remain the only active roadmap.
- Docs index: move this reference from backlog to completed at closeout.
- This spec moves to one `docs/CompletedPR/` record at closeout.
- Tier 1 architecture does not change. Tier 2 wording must cite implemented
  scripts, workflow, tests, disposable-checkout proof, and Python 3.11/3.12 CI.

## 12. Dependencies

### Internal module dependencies

- `PR-MVP-000` completeness guard and restored state modules.
- `PR-MVP-005` probe-cleanup and generated-state dispositions.
- Existing architecture, state, queue, and controller tests in the smoke list.

### External tools or runtimes

- Git; Python 3.11 and 3.12; pytest, Ruff, and mypy.
- No WebUI, ComfyUI, GPU, model, display, or internet service.

## 13. Approval & Execution

Planner: Codex
Executor: Codex
Reviewer: Rob (Human Owner)
Approval Status: Approved

The request to generate and approve `PR-MVP-010` records owner approval. It
authorizes only this allowlist.

Completion evidence on 2026-09-06: the allowlisted configuration, isolation,
positive smoke, generated-state cleanup, CI, documentation, regression repair,
and Ruff ratchet are implemented. Repository completeness passes for 435
tracked Python source files. Ruff 0.14.9 verifies exactly 2,208 baseline
findings in 342 path/rule buckets, and a synthetic new bucket is rejected.
The repaired regression module passes all three tests.

Two newly exposed conditions required the owner-approved amendment:

1. strict importlib collection reaches the active regression surface and fails
   because `tests/regression/test_snapshot_regression_v2.py` registers
   `tests.controller.conftest` a second time through `pytest_plugins`; a
   diagnostic run excluding only that file collects the remaining configured
   surface without error;
2. the pre-existing required `ruff check src` command reports 2,208 baseline
   findings, while `src/**` is forbidden here. Silencing Ruff or editing source
   would violate the trustworthy-gate purpose.

The owner approved the narrow amendment on 2026-09-06. It admits only the
regression fixture repair plus `tools/ci/run_ruff_baseline.py` and
`tools/ci/ruff_baseline.json`; `src/**` remains forbidden.

Disposable Python 3.11.16 and 3.12.14 environments each pass repository
completeness, the Ruff ratchet, the 10-file mypy smoke, strict collection, and
all 73 required smoke tests without repository pollution. Strict collection
reports 3,083 tests in those environments with two explicit optional-OpenCV
skips; the count is evidence, not a frozen assertion.

## 14. Next Steps

1. Generate and approve `PR-MVP-020` against the trustworthy harness.
2. Keep every touched NJR source file at zero Ruff findings.
3. Do not regenerate this baseline upward.
