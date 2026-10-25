# Testing and CI

Status: living document, edit in place
Owner area: how a change is validated (`.github/workflows/`, `tools/ci/`, `tests/`, `pyproject.toml`, `requirements-dev.txt`, the root `conftest`)

How to keep this true:
- Change this file in the same PR that changes a workflow, a gate script, a ratchet, a baseline policy, a marker, a root-conftest guard or the quarantine rule. Edit the existing row or sentence.
- Do not append per-PR sections, dates, test counts or baseline totals (baseline numbers live in `tools/ci/*.json`; `STATUS.md` quotes them). History lives in `git log` and the per-PR records listed at the end.
- Labels: **[V]** read in the code or workflow when this was written; **[A]** taken from `docs/audits/2026-10-16_repo_audit_and_roadmap.md` or `STATUS.md`, not re-checked (GitHub-side settings such as branch protection cannot be read from the repository).

## 1. Scope

This document covers validation: what the hosted CI runs and requires, how to run the same thing locally, how the test tree is laid out, what keeps tests hermetic, and how the ratchets and the flake policy work. It does not describe product behavior; the canonical execution path (`Intent -> Compiler -> NJR -> JobService -> Queue/Repository -> PipelineRunner.run_njr -> Handler -> Artifacts/History`, authority `AGENTS.md`) is what tests drive, not something this file defines. Operating rules (when to run what, never weaken tests, protected actions) live only in `AGENTS.md` sections 5 and 6; the three validation levels are in `docs/StableNew_Coding_and_Testing_v2.6.md` ("Validation levels").

Hosted CI proves deterministic behavior on Linux plus an OS-dependent slice on Windows. It never proves GPU, Forge, A1111, Comfy or SVD behavior; that stays opt-in, local and owner-authorized (`STATUS.md` Holds).

## 2. What CI enforces today

One workflow, `.github/workflows/ci.yml`, named "StableNew CI" [V]. Triggers: `pull_request` (every base, so stacked PRs are covered), `push` to `main`, `workflow_dispatch`, and a cron on Monday/Wednesday/Friday 07:00 UTC. Concurrency is per PR number (or ref); a newer PR head cancels the run in flight, runs for `main` are never cancelled. The token is `contents: read, checks: read`. Every action is pinned to a commit SHA. Python is 3.14 everywhere; the only matrix is the census shard index.

| Job | Runner / limit | Runs when | Role |
|---|---|---|---|
| `required` | ubuntu, 20 min | always | Plans the change set, then either the cheap docs path or the full quality gate (section 4). Its name is the branch-protection identity. |
| `full-suite-shard` (matrix 0, 1, 2) | ubuntu + Xvfb, 30 min each | executable change, after `required` succeeds | One third of the census (section 5). `fail-fast: false`. |
| `full-suite` | ubuntu, 10 min | executable change, `always()` once `required` succeeded | Aggregate census verdict (completeness and exit codes of all shards). Branch-protection identity. |
| `windows` | windows-latest, 30 min | executable change, after `required` succeeds | OS-dependent platform contract (section 6). |

Required status checks on `main`: `required`, `full-suite`, `windows`; PR required, force-push and deletion blocked, owner may bypass [A: `STATUS.md`]. A docs-only run skips the shard, `full-suite` and `windows` jobs; a skipped job is treated as satisfied by GitHub [A].

The same workflow set contains two other files that are not gates [V]:

- `.github/workflows/shutdown_leak_manual.yml`: `workflow_dispatch` only, `runs-on: self-hosted`, sets `STABLENEW_RUN_SHUTDOWN_LEAK_TEST=1` and runs `tests/system/test_shutdown_no_leaks.py` (launches the real app). Opt-in; no runner is registered [A].
- `.github/workflows/copilot-setup-steps.yml`: environment bootstrap for the Copilot agent (`requirements.txt` only, `python -m compileall src`). It runs on PRs that touch that file and is not a quality gate.

`continue-on-error` appears nowhere in `ci.yml`; no job masks its failure (asserted by `tests/system/test_ci_truth_sync_v2.py`). There is no "affected"/per-lane routing any more: every active test file runs for every executable change [V].

## 3. The validation plan: docs-only cheap path and evidence reuse

`tools/ci/validation_plan.py` (standard library only) is the one routing policy; the workflow only consumes its outputs `docs_only`, `cheap_path`, `reuse_previous_evidence`, `full_census`.

- `is_documentation(path)` is true only for prose/media: suffixes `.md .rst .txt .png .jpg .jpeg .gif .svg .pdf`, plus `LICENSE` and `CODEOWNERS`. It is false under `src/ tests/ config/ presets/ packs/ data/ tools/ci/ .github/workflows/ .github/actions/` (a `.md` there may be data), and `.txt` counts only under `docs/` (so `requirements*.txt`, constraints and version files are executable). `.json`, `.yml`, `.ps1`, `.py` are never documentation, wherever they live.
- A PR whose changed files (merge-base diff `base...head`, deletions included) are all documentation is `docs_only`: no Python environment, no tests. The `required` job then runs only `git diff --check`, `check_repository_completeness.py`, `check_controller_surface.py` and `ci_truth.py` under the runner's system `python3` (section 8).
- Anything else is executable: the full `required` gate, then the full census and the Windows lane. There is no smaller selection.
- Pushes to `main` classify the direct `before` to `head` delta, including deletions: documentation-only updates take the cheap path. An initial push or unavailable Git history fails closed to full validation. Schedule and manual dispatch always run the census.
- Evidence reuse (`tools/ci/previous_evidence.py`, on `pull_request` `synchronize`): a docs-only follow-up over a green head runs only `git diff --check <before> <head>` plus the three cheap checks. The current base must be contained in that head or have advanced only in documentation since their common ancestor. The latest completed GitHub-Actions `required` must be `success`; latest completed `full-suite` and `windows` must each be `success` or `skipped`. Unknown refs, code/configuration/test changes in either delta, failed/in-flight/missing checks and API errors refuse reuse. This covers docs-only merge conflict resolution and repeated documentation follow-ups without weakening executable-change validation. Contract: `DOCS_ONLY_EVIDENCE_REUSE.md`.

Local classification: `python tools/ci/validation_plan.py --files a.md b.py` prints the plan JSON.

## 4. The `required` gate, step by step

`python tools/ci/run_pr_gate.py` runs these nine steps in this fail-fast order and CI runs the same scripts as separate steps (`GATE_STEPS`). It first preflights `mypy`, `pytest` (importable) and `ruff` (on `PATH`); a missing tool exits 2 with `TOOLING BLOCKER`, a failing step exits with its code and prints `SOURCE/TEST FAILURE at <step>` [V].

| # | Step | Script / command | What it enforces |
|---|---|---|---|
| 1 | Repository completeness | `tools/ci/check_repository_completeness.py` | Every `src/**/*.py` is tracked (no untracked, ignored or missing source), parses, and every statically imported `src.*` module exists. |
| 2 | Controller surface ratchet | `tools/ci/check_controller_surface.py` | Physical-line ceilings for named top-level controllers in `tools/ci/controller_surface_baseline.json`; any other top-level `src/controller/*.py` must stay under `new_controller_limit`. Growth, an unlowered ceiling and a deleted target all fail. |
| 3 | Ruff | `ruff check .` | Raw zero with the `pyproject.toml` rule set (`E W F I B C4 UP`, `E501` ignored). No baseline. |
| 4 | mypy smoke | `tools/ci/run_mypy_smoke.py` | Ten explicit typed seams in `MYPY_SMOKE_TARGETS`, strict, `--follow-imports=silent`. |
| 5 | mypy ratchet | `tools/ci/run_mypy_ratchet.py` | Per-file error count over all of `src` may not exceed `tools/ci/mypy_baseline.json`. |
| 6 | Ruff ratchets | `tools/ci/run_ruff_ratchets.py` | Formatting (files `ruff format` would change) and per-file counts of `BLE001`, `S110`, `S112` in `src`, against `tools/ci/ruff_ratchet_baseline.json`. |
| 7 | Architecture ratchets | `tools/ci/run_architecture_ratchets.py` | AST counts per `src` file for `daemon_threads`, `raw_threads`, `utils_upward_imports`, `controller_gui_imports` and `ai_assist_forbidden_imports` (`src/ai_assist` may import only `ai_assist`, `utils` and `prompting`; baseline 0), against `tools/ci/architecture_baseline.json`. |
| 8 | Isolated collection | `tools/ci/run_collection_gate.py` | `pytest --collect-only` of `tests/` (minus the four excluded trees) in a temp cwd; fails on any collection error or repository change. |
| 9 | Required smoke | `tools/ci/run_required_smoke.py` | Pytest `-x -q` over the positive lists `REQUIRED_SMOKE_TARGETS` and `CONTRACT_GATE_TARGETS` (below). |

CI then fails the job if `git diff --exit-code` or `git status --porcelain --untracked-files=all` is non-empty. Ignored files are invisible to that check, which is why steps 8, 9 and the Windows lane also fingerprint `GUARDED_RUNTIME_PATHS` (section 9).

`REQUIRED_SMOKE_TARGETS` is repository truth, current-architecture guards and the production run path: `tests/system/` (completeness, architecture enforcement, CI truth, controller-surface ratchet, `test_pr_gate`, runtime constraints), runtime-state hygiene, workspace paths and output routing, the SQLite repository and importer, `tests/controller/test_core_run_path_v2.py`, the operator-journey harness and `TestQueuedModeExecution` / `TestQueueErrorHandling` in `tests/queue/test_job_service_pipeline_integration_v2.py`. `CONTRACT_GATE_TARGETS` is the small always-run cross-boundary suite, grouped by invariant: construction identity (`tests/system/test_construction_identity_contract.py`), image-backend contract and foreign backend/profile fail-closed, replay gets a new identity with parent lineage, runtime ownership (only owned runtimes are mutated), ambiguous generation POSTs are never replayed, and the CI policy tests (`tests/tools/test_ci_validation_plan.py`, `test_ci_census_summary.py`, `test_ci_previous_evidence.py`). Entries are explicit node IDs; a new test joins the smoke only by editing the tuple. Keep it small; feature behavior belongs to the census.

Pytest configuration is `pyproject.toml` only (`tests/system/test_ci_truth_sync_v2.py` asserts there is no `pytest.ini`). `addopts`: `-ra --strict-markers --strict-config --showlocals --import-mode=importlib`, and `--ignore` for `tests/legacy`, `tests/quarantine`, `tests/scripts` (and an already-absent `gui_v1_legacy` tree). `testpaths = ["tests"]`, `python_files = test_*.py`.

## 5. The census and its sharding

The census is every active test file: `tools/ci/census_shards.py` `active_test_files` mirrors pytest selection (`testpaths`, `test_*.py`, `norecursedirs`, and `DEFAULT_COLLECTION_EXCLUDES` imported from `run_collection_gate.py`) instead of defining a second universe.

- Partition: `shard = int(sha256(repo-relative POSIX path), 16) % shard_count`. Whole files, never split; a new test file is assigned automatically; Linux and Windows agree.
- `run-shard` runs ordinary pytest on its files via an `@argsfile` with `-q -rfE --tb=short --timeout=300 -o junit_family=xunit2 -o junit_duration_report=total`, no `--maxfail`, writes `census-shard-<i>.{xml,manifest.json,result.json}`. In CI it runs under `GabrielBB/xvfb-action` (Tk needs a display); the action's first `run:` line must be the executable, not a comment.
- `verify` (job `full-suite`) fails closed if a shard artifact is missing, the executed manifest differs from the partition of the current tree, an active file is unassigned or doubly assigned, a JUnit record names a file outside its shard, or any shard's pytest exit code is non-zero. It prints one merged summary (`tools/ci/census_summary.py`) to the job summary.
- The shard count `3` must agree between the `matrix.shard` list and every `--shards` argument (a truth test enforces it). A per-test budget of 300 s plus a 30-minute job deadline bound a hang; the Tk signal-mode timeout can be swallowed inside a callback, so the job deadline is the real backstop.

Run it locally: `python tools/ci/run_sharded_census.py [--workers 2]`. By default each worker gets its own detached `git worktree` of `HEAD` plus a copy of the uncommitted changes (shared-tree workers trip each other's writes to `state/`, `data/`, `output/`); `--shared-tree` skips that. Inspect one shard: `python tools/ci/census_shards.py plan --shards 3 --index 0`. Two workers is the supported default (a Windows/Tk suite shares ports, files and process-global state).

## 6. The Windows lane

Desktop pixel/DPI containment is a Windows support contract. The lane also runs
`tests/gui_v2/test_workspace_layout_resilience_v2.py`, including the Video Workflow laptop and
100%/150% Recent Outputs inspection cases. Those three cases run only on Windows; their assertions
remain intact. The module's other tests and media lifecycle/functional coverage continue in the Linux census.

`python tools/ci/run_windows_lane.py` (job `windows`, bash shell, `pip install -r requirements.txt -r requirements-dev.txt`). It runs `WINDOWS_LANE_TARGETS`, an explicit positive list: process ownership/containment (`tests/utils/test_job_object_isolation.py`, `test_process_container_v2.py`, `test_process_containment_failsafe.py`, `test_managed_process.py`), all of `tests/api` and `tests/safety`, atomic replace and sharing violations (`tests/utils/test_atomic_io.py`), `tests/state`, `tests/assets`, `tests/photo_optimize`, the SQLite repository and `tests/migrations` on NTFS, the production startup gate, `tests/app`, and one Tk construction smoke (`tests/gui_v2/test_p0_6_silent_failure_regressions.py`). It uses the same isolated, pollution-detecting runner as the required smoke, with `--timeout=300`. A new test never joins by accident; `tests/tools/test_ci_windows_lane.py` checks every entry still exists. It is a platform contract, not hardware qualification.

## 7. Ratchets and how baselines change

A ratchet lets recorded debt shrink and never grow. For the mypy, ruff and architecture ratchets all three outcomes fail the gate: a regression (more than baseline; a file absent from the baseline must have zero), and an improvement that is not recorded (the message says to run `--update`). So a PR that fixes debt must lock it in in the same PR.

| Ratchet | Baseline file | Measured | Update |
|---|---|---|---|
| mypy | `tools/ci/mypy_baseline.json` | strict errors per `src` file, with `--no-site-packages --platform linux --python-version 3.14`, import errors ignored (counts must not depend on what is installed) | `python tools/ci/run_mypy_ratchet.py --update` |
| format | `tools/ci/ruff_ratchet_baseline.json` (`format.files`) | files `ruff format --check .` would change; a file outside the list must be formatted | `ruff format <file>` for a new file; `python tools/ci/run_ruff_ratchets.py --update` after formatting a baselined one |
| blind/silent excepts | same file (`rules.counts`) | per `src` file `BLE001`, `S110`, `S112` (selected only by this script, not by `ruff check .`) | `python tools/ci/run_ruff_ratchets.py --update` |
| architecture | `tools/ci/architecture_baseline.json` | `daemon=True` threads, `threading.Thread(` outside `src/utils/thread_registry.py`, `src/utils` importing a higher layer, `src/controller` importing `src.gui` | `python tools/ci/run_architecture_ratchets.py --update` |
| controller surface | `tools/ci/controller_surface_baseline.json` | physical lines of named top-level controllers; `new_controller_limit` for the rest | edit the JSON by hand (no `--update`); lower a ceiling when a controller shrinks |

Policy [V: script messages, `AGENTS.md` section 4]: `--update` is for deliberate improvements. When a count regresses, fix the code ("do not raise the baseline"). Raising a controller ceiling needs explicit architecture approval. A split that only moves lines into a new file is not decomposition (audit C5) [A].

Pinned-tool traps: the mypy and ruff numbers are only reproducible with the pinned versions (`requirements-dev.txt`); a different mypy or ruff changes counts and makes a clean tree look regressed or improved. Run the ratchets from the repository root with the project interpreter. `run_pr_gate.py` looks for `ruff` on `PATH` for step 3 but the ruff ratchets call `python -m ruff`, so the active environment must provide both.

## 8. The `ci_truth` guard and documentation checks

`python tools/ci/ci_truth.py` (no flags, standard library only) exits 1 and prints each problem. It runs on the docs-only cheap path and, through `tests/system/test_ci_truth_sync_v2.py` and `tests/system/test_status_contract.py`, inside the required smoke or the census. It enforces [V]:

- `docs/StableNew_Coding_and_Testing_v2.6.md` still defines Level 1/2/3, names Python 3.14 (not 3.11/3.12), points to `python tools/ci/run_pr_gate.py`, "GitHub required CI" and `tools/ci/validation_plan.py`; `AGENTS.md` points to the gate.
- `STATUS.md`: at most 150 lines, none of the banned narrative markers (`STATUS_BANNED_MARKERS`: "not merged", "locally validated", "draft pr", "python 3.11" ...), and every backticked token that starts with `docs/ src/ tools/ tests/ scripts/ config/ constraints/` must exist (globs allowed).
- `docs/CODEX_MAP.md`: at most 60 lines, same dead-reference rule.
- Rule-bridge files are capped (`CLAUDE.md` 40, `.github/copilot-instructions.md` 12, `docs/AGENT_OPERATING_MODEL.md` 160, `docs/AI_MODEL_SELECTION.md` 90) and name `AGENTS.md`; rule text that belongs only in `AGENTS.md` may not be restated in them, in agent/skill files.

Trap: the dead-reference scan treats every whitespace-free backticked token with a repo prefix as a file path, so a pytest node ID of the form path-colon-colon-class in `STATUS.md` or `docs/CODEX_MAP.md` fails it. It also does not scan the living subsystem documents; check paths in those as described in section 17. `tests/tools/test_code_map.py` fails when `docs/CODE_MAP.md` differs from `python tools/generate_code_map.py` output, so regenerate it after adding, moving or re-documenting a module.

## 9. Environment and pins

- Interpreter: CPython 3.14 standard-GIL only (`requires-python >=3.14,<3.15`). A machine whose default `python` is older cannot run the gates meaningfully; use the project interpreter explicitly.
- Install: `pip install -r requirements.txt -r requirements-dev.txt`. `requirements-dev.txt` is the one authority for gate tools (exact pins: pytest, pytest-timeout, `pytest-xvfb` on Linux only, ruff, mypy, types-requests). The Windows runtime's pins are `constraints/windows-py314-cu130.txt`; Forge and Comfy have their own constraints files and never share the application environment.
- `tests/system/test_dev_environment_pins.py` keeps `requirements-dev.txt`, the `pyproject.toml` dev extra, `.pre-commit-config.yaml`, the Windows constraints (pytest pin) and the workflows from drifting, forbids unpinned `pip install` lines in workflows, and checks that every third-party module the code imports is declared. An upgrade of any pin is its own reviewed change.
- `requirements.txt` still lists unpinned `pytest`/`pytest-cov`/`requests-mock`; the dev file's exact pins win when both are installed together [V]. Optional extras (`requirements-svd.txt`, `requirements-postprocess.txt`) are not installed in CI; tests that need them use `tests/helpers/optional_deps.py` (`requires_numpy`, `requires_cv2`, `requires_windows`) and skip with a stated reason.
- The gate runner `run_collection_gate.py` `run_pytest_gate` runs pytest with `-c pyproject.toml --rootdir <repo> -p no:cacheprovider`, `--basetemp` in a temp directory outside the repo, cwd in that temp directory, `PYTHONHASHSEED=0`, `STABLENEW_NO_WEBUI=1`, `STABLENEW_TEST_MODE=1`, `MPLBACKEND=Agg`. It hashes every Git-visible file plus `GUARDED_RUNTIME_PATHS` (`output`, `runs`, `temp`, `tmp`, `manifests`, `logs`, `test_output`, `data/webui_cache.json`, `tmp_prompt_pack_probe*`, root `*.log`) before and after, and fails with the changed paths if a test polluted the repository. Output is one compact line on success and the full pytest output on failure.

## 10. Running validation locally

| Goal | Command |
|---|---|
| Focused (Level 1) | `python -m pytest -q <files or node ids>` from the repo root; start here, do not run the whole tree because source changed |
| Final local gate (Level 2) | `python tools/ci/run_pr_gate.py` once, near the end; reuse exact-source green evidence, do not rerun after docs-only edits |
| One gate step | the script in the section 4 table, directly |
| Full census | `python tools/ci/run_sharded_census.py` (section 5) |
| Windows lane | `python tools/ci/run_windows_lane.py` on Windows |
| Docs-only checks | `git diff --check`, `python tools/ci/check_repository_completeness.py`, `python tools/ci/check_controller_surface.py`, `python tools/ci/ci_truth.py` |
| Hosted verdict (Level 3) | the PR's `required`, `full-suite`, `windows` checks; the gate script is not a substitute for the census |

`run_pr_gate.py` on its own does not run the census, the Windows lane or `ci_truth.py` directly; the last runs only through its pytest tests in the required smoke. A green default local gate therefore does not predict a green `full-suite`. `python tools/ci/run_pr_gate.py --full [--workers N]` appends `tools/ci/run_sharded_census.py` (default 2 workers): the same path-hash shard partition and completeness verdict as the hosted `full-suite`, one isolated checkout per worker. It is deliberately not pytest-xdist: this Windows/Tk suite shares ports, files and process-global state, so workers must not share a tree. Use it before a PR that changes executable code; hosted CI stays the authority, and the Windows lane is still hosted-only. Run it with StableNew and its managed Forge/Comfy closed: a live runtime on the host occupies the WebUI endpoint and makes the runtime-transition tests (about 35 pipeline-runner tests) refuse, which looks like a regression and is not. Measured once on the owner's machine: about 13 minutes wall with 2 workers while other sessions were also busy.

## 11. Test layout (`tests/`)

Top-level directories follow the source packages; the ones that need explanation:

| Directory | Contents / role |
|---|---|
| `tests/system/` | Repository-truth and policy tests: completeness, architecture enforcement (AST rules on `src`), CI truth, pins, quarantine policy, status/rules contracts, construction identity contract, runtime isolation, managed runtime pins. Mostly in the required smoke. |
| `tests/tools/` | Tests of `tools/` including all `tools/ci` policy (validation plan, shards, ratchets, previous evidence, windows lane, code map) and the qualification/acceptance harnesses (offline, fakes only). |
| `tests/safety/` | Import-isolation and process-safety guards (no Tk in controllers/adapters/utils, backend isolation, runtime-state hygiene). |
| `tests/integration/` | Canonical-path tests with fake inference: `tests/helpers/njr_queue_harness.py` `run_njr_via_queue` (NJR -> `JobService` -> SQLite -> `PipelineRunner.run_njr`, HTTP mocked). There is no separate journeys lane. |
| `tests/gui_v2/`, `tests/controller/`, `tests/app/` | Headless-safe view/controller wiring, thread boundaries, bootstrap. Tk needed; CI uses Xvfb. |
| `tests/pipeline/`, `tests/image_backends/`, `tests/api/`, `tests/assets/`, `tests/conditioning/`, `tests/refinement/`, `tests/queue/`, `tests/video/`, `tests/learning*/`, `tests/review/`, `tests/photo_optimize/`, `tests/promptpacks/`, `tests/services/`, `tests/ai_assist/`, `tests/state/`, `tests/utils/`, `tests/history/`, `tests/migrations/` | Subsystem tests; the per-subsystem living documents say which fake each one uses. |
| `tests/golden/` | Golden NJR snapshots (`njr/*.json`), one per builder (CLI, `JobBuilderV2`, PromptPack, reprocess, training, replay). The diff of a golden file is the review artifact when a builder changes (audit P4-2); regenerate deliberately with `STABLENEW_UPDATE_GOLDEN=1 pytest tests/golden`. Temp paths and path separators are normalized so the files are OS-independent. |
| `tests/compat/`, `tests/data/`, `tests/fixtures/` | Data only (legacy history/queue fixtures, snapshots, contracts, sample packs); `tests/regression/` holds snapshot regression tests. |
| `tests/helpers/`, `tests/mocks/` | Shared test code (section 12). Not collected as tests. |
| `tests/legacy/`, `tests/scripts/`, `tests/quarantine/` | Excluded from pytest by `--ignore`, from the collection gate and from the census. `tests/scripts/` holds manual scripts that are not part of any gate. |

Operator-only code is not under `tests/`: `tools/qualification/`, `tools/acceptance/` and `tools/operator_journey/` (semantic GUI journeys; `--real-backend` is an explicit flag) are never part of the production path or CI. `tests/system/test_shutdown_no_leaks.py` launches the real app and is skipped unless `STABLENEW_RUN_SHUTDOWN_LEAK_TEST=1`.

## 12. Hermetic seams: fakes, helpers and autouse guards

Root `tests/conftest.py` [V] applies to every test:

- GC: automatic garbage collection is disabled for the session and `gc.collect` is a no-op off the main thread, with a main-thread collection when the test module changes. This prevents a Tcl "async handler deleted by the wrong thread" abort when a Tk object is finalized on a worker thread.
- `_isolate_process_global_runtime_state` (autouse): clears the `ThreadRegistry` and the `SystemWatchdogV2` single-flight slot and restores `sys.excepthook` / `threading.excepthook` after every test (leaked `AppController` instances otherwise stack hooks and recurse).
- `_pin_host_runtime_autostart_off` (autouse): `STABLENEW_WEBUI_AUTOSTART=0`, `STABLENEW_COMFY_AUTOSTART=0`, `STABLENEW_GPU_HOST_PROBE=0`, and resets the cached autostart answer in `src.config.app_config`. A test that exercises autostart overrides with its own `monkeypatch.setenv`.
- `_never_create_real_process_containers_for_webui_managers` (autouse): replaces `webui_process_manager.build_process_container` with `NullProcessContainer`, so a test-built `WebUIProcessManager` never owns a real job object/cgroup whose `stop_webui()` would kill a live managed Forge. Container behavior itself is tested by calling the factory directly in `tests/utils/test_job_object_isolation.py` and `tests/utils/test_process_container_v2.py`.
- `_isolate_global_prompt_user_state` (autouse): `STABLENEW_GLOBAL_PROMPT_DIR` points into `tmp_path`.
- `_mock_webui_discovery` (autouse): sets `STABLENEW_NO_WEBUI=1` and `STABLENEW_TEST_MODE=1`, redirects the WebUI cache file into `tmp_path`, makes `SDWebUIClient.check_api_ready` return `False` (except when the running test id contains `tests/test_api_client.py`, or the vestigial `test_api.py` name) and stubs the main window's WebUI hooks.
- Fixtures: `tk_root` (skips when Tk or a display is missing), `tk_pump`, `stubbed_job_service`, `stubbed_job_service_with_queue`, `build_v2_app_with_stubs`.

Directory conftests: `tests/api/conftest.py` (autouse `SingleInstanceLock.is_gui_running` -> True so the process manager may start in tests), `tests/controller/conftest.py` (`StubRunner` + `NullHistoryService` fixtures), `tests/gui_v2/conftest.py` (autouse isolation of the PromptPack dir via `STABLENEW_PROMPTPACK_DIR`, of UI/sidebar/preview state files, and `WebUIConnectionController.ensure_connected` forced to READY; its own `tk_root` makes the test root Tk's default root), `tests/integration/conftest.py` (autouse: WebUI and Comfy endpoint probes report `free`, PromptPack dir isolated).

There is no root-level autouse guard that blocks network access or forces `tmp_path` for all writes, and none that patches `src.utils.atomic_io` [V]. Hermeticity of state roots is per-area (above) plus the pollution fingerprint in section 9; a test that writes a bare relative path still writes into its cwd. Production code branches on test mode in several places (`PYTEST_CURRENT_TEST` / `STABLENEW_TEST_MODE`, e.g. `src/state/output_routing.py`, `src/utils/watchdog_v2.py`, `src/controller/app_controller.py`) [V], so a test can pass for a reason that does not hold in production (audit D8) [A].

Shared test code (`tests/helpers/`, `tests/mocks/`):

| Seam | Use |
|---|---|
| `tests/helpers/fake_webui_transport.py` `FakeWebUITransport` | Replaces `requests.Session.request` for a client; `flavor` `forge` or `a1111`. Records every request; `.generation_calls` (generation POSTs only) and `.paths(method)` let a test prove an endpoint was or was not called. |
| `tests/helpers/njr_queue_harness.py` `run_njr_via_queue` | Real `JobService` + SQLite + `run_njr` with only the HTTP transport mocked. |
| `tests/helpers/njr_factory.py` (`make_pipeline_njr`, `make_stage_config`, `make_queue_job`) | Build NJRs/jobs without a compiler. |
| `tests/helpers/pipeline_fakes.py` `FakePipeline`, `tests/helpers/fake_pipeline_runner.py` `FakePipelineRunner` | Stage-level stand-ins. |
| `tests/helpers/job_service_di_test_helpers.py` (`make_stubbed_job_service`, `make_app_controller_with_stubs`) and `src/queue/stub_runner.py` `StubRunner` | `JobService` without a real runner or history. |
| `tests/helpers/gui_harness_v2.py`, `tk_root_factory.py` | Tk/GUI construction helpers. |
| `tests/mocks/webui_mock_client.py`, `webui_mock_server.py` | Journey-style WebUI mocks. |
| `tests/helpers/optional_deps.py` | `requires_numpy`, `requires_cv2`, `requires_windows` skip markers. |

## 13. Markers, skips and writing a test

Declared markers (`--strict-markers`, so an unknown marker is an error): `compat`, `core_e`, `golden_path`, `gp1`..`gp15`, `gui`, `integration`, `journey`, `legacy`, `real_backend`, `slow`, `smoke`, `snapshot_regression`, `summary`, `timeout`. No workflow or gate script passes `-m`, so markers select nothing in CI [V]. Of the declared names only `gui`, `golden_path`, `gp*`, `integration`, `journey`, `slow` and `snapshot_regression` are applied anywhere; `real_backend` is declared but no test carries it [V], so "real backend" safety rests on tests not contacting one at all and on explicit opt-in drivers (`tools/operator_journey/cli.py --real-backend`, the env-gated shutdown leak test).

Skips must be explicit predicates (Tk or display unavailable, Windows-only, missing optional capability, an opt-in environment variable). A missing current surface fails the test; it is never skipped, and a permanent unconditional skip for removed architecture is retired instead (`docs/StableNew_Coding_and_Testing_v2.6.md` "Skips and retired tests").

Rules for a new test: deterministic for fixed inputs; temporary state, artifact, cache and output roots (`tmp_path`); no real network, WebUI, model, GPU, display or persistent user data; poll terminal state rather than `sleep`; drive queue behavior through `JobService` and assert the stored record, never a stale object (`docs/Subsystems/Testing/KNOWN_PITFALLS_QUEUE_TESTING.md`); close threads, clients and temporary servers; use fixed IDs, not `time.time()`.

### Adding a test for a new refusal

A refusal is code that raises before any dispatch. Prove both halves:

1. Build the offending intent through the real compiler or `njr_factory`, and run it through `run_njr_via_queue` (or the backend `validate_njr_intent` / `_validate_request` directly for a pure refusal).
2. Assert the failure (`entry.status is JobStatus.FAILED` and a fragment of `entry.error_message`, or `pytest.raises(<specific error>)`), then assert nothing was sent: `transport.generation_calls == []`, and for runtime-mutating refusals that no option or module write occurred. The pattern is in `tests/integration/test_pr_img_116_klein_canonical_path.py` (`test_conflicting_klein_work_fails_before_any_runtime_call_or_generation`).
3. Parametrize over the sibling construction paths when the rule lives in the compiler (see `tests/system/test_construction_identity_contract.py`); a refusal enforced in one builder is usually missing from another.
4. If the invariant is cross-subsystem, add the node ID to `CONTRACT_GATE_TARGETS` in `tools/ci/run_required_smoke.py`; otherwise it is covered by the census.

## 14. Flaky and environment-dependent tests: quarantine policy

The census blocks, so a test that fails and later passes without a code change is repaired, not retried; there is no rerun plugin or retry in CI [V]. If it cannot be fixed in the same PR, move the file into `tests/quarantine/` (ignored by pytest) with this exact first line:

`# quarantined: YYYY-MM-DD; owner: <name>; expires: YYYY-MM-DD; reason: <why>`

A quarantine lasts at most 30 days; `tests/system/test_quarantine_policy.py` fails once it expires or the header is malformed, forcing the decision: fix, extend deliberately, or delete. A file with no behavioral protection is deleted, not quarantined; the directory is empty today. Never weaken an assertion, widen a tolerance or add a skip to turn a flaky test green (`AGENTS.md` section 6).

Environment-dependent patterns to avoid: assuming `%LOCALAPPDATA%`, a Tk geometry, a wall-clock-derived ID, the host's A1111/Comfy being absent, or a relative output path (audit A8/A9) [A]. The sidecar leak in `tests/controller/test_learning_controller_review_feedback.py` is fixed by using `tmp_path` [V].

## 15. Invariants

1. Tests, gates and CI never start, adopt, restart or kill an external A1111/Forge/Comfy process or touch a GPU. Physical work belongs to a package's own acceptance run, never to tests (`STATUS.md` Holds).
2. Tests must not make the repository dirty; `git status` clean is checked in CI, and the pollution fingerprint covers ignored runtime paths in the pytest gates.
3. One routing policy: `tools/ci/validation_plan.py`. Do not add path-based test selection to the workflow; the census runs everything.
4. One pytest configuration authority: `pyproject.toml`.
5. Ratchets never go up silently: fix the code; a lowered baseline is committed with the improvement; a raised controller ceiling needs architecture approval.
6. Positive lists (`REQUIRED_SMOKE_TARGETS`, `CONTRACT_GATE_TARGETS`, `WINDOWS_LANE_TARGETS`) are edited deliberately and every entry must exist.
7. Workflows stay SHA-pinned with a read-only token; no workflow runs fork code with secrets [A: `STATUS.md`].
8. Rules live in `AGENTS.md`; this file adds procedure only.

## 16. Known debt and traps

- Stale comment [V]: `tools/ci/run_required_smoke.py` still says feature behavior "belongs to the affected lanes"; the lane routing was removed. Several `PR-DEVEX-*` records describe that removed design and the earlier "informational full-suite"; the workflow and this file win. A test name `test_ci_is_python_312_only_with_no_version_matrix` actually asserts Python 3.14 only.
- The census does not use the pollution-detecting runner; only collection, the required smoke and the Windows lane fingerprint the tree [V]. A leak in a census-only test shows up, if at all, in the post-job clean check, which ignores ignored files.
- `previous_evidence.py` reuses evidence without checking `windows`; a red Windows lane on the previous head does not block a docs-only follow-up from passing [V].
- `required` (smoke) runs pytest with `-x`; the census does not. A smoke failure hides later failures; fix and rerun, and run the census to see the whole picture.
- `--showlocals` from `addopts` plus `--tb=short` makes failure output long; read the `-rfE` short summary and the JUnit summary first.
- GUI tests are numerous, brittle and Linux/Xvfb only apart from one Windows Tk smoke; many use private attributes and compatibility shims (audit D8) [A]. Prefer testing presenters/view contracts without Tk.
- The required smoke includes tests of the CI tooling itself (audit A2) [A]. Do not grow it with feature tests; those belong to the census.
- `tests/tmp_executor/` is an empty, untracked directory and `tests/scripts/` is excluded; neither is part of any gate.
- Windows-only defects (job objects, `os.replace` sharing violations, NTFS paths, long paths) are visible only in the `windows` job; a Linux-green run says nothing about them.
- Quarantine, windows-lane and smoke lists are code, not config: they are read by `tests/system` and `tests/tools` policy tests, so changing them may require updating those tests.

## 17. Changing CI or the gates today

- New test: put it next to its subsystem; it joins the census automatically. Only add it to a positive list for the reasons in section 4 and 6.
- New workflow step or job: keep SHA-pinned actions, an explicit `timeout-minutes`, read-only permissions, and update `tests/system/test_ci_truth_sync_v2.py` (it pins job names, shard consistency, the single matrix, the Xvfb command shape) and `docs/StableNew_Coding_and_Testing_v2.6.md`. Changing a required check name changes branch protection (owner decision).
- New ratchet: follow `run_architecture_ratchets.py` (pure `ast`, schema-versioned baseline, `--update`, regression and unrecorded-improvement both fail), add a step to `GATE_STEPS` in `tools/ci/run_pr_gate.py` and to `ci.yml`, and a test in `tests/tools/`.
- Dev tool pin change: edit `requirements-dev.txt`, the `pyproject.toml` dev extra and `.pre-commit-config.yaml` (ruff) together, then recompute every baseline the tool affects.
- Docs-only changes need no local gate beyond `python tools/ci/ci_truth.py` and the path check; any `.json`, `.yml`, `.py`, `config/` or `tests/` file in the diff makes the PR executable.
- Path check for living documents: extract backticked tokens that start with a repo prefix and assert each exists (ignore `::` node suffixes and `*` globs).

## 18. Evidence records

Per-PR records stay in `docs/Subsystems/Testing/` as historical evidence. Several describe superseded designs (per-lane routing, informational census); the code and this file win.

| Record | Why it matters |
|---|---|
| `docs/StableNew_Coding_and_Testing_v2.6.md` | The validation levels and coding/testing rules referenced by `ci_truth.py` |
| `docs/Subsystems/Testing/PR-DEVEX-CENSUS-140_Parallel_Sharded_Full_Census.md` | Origin of the path-hash sharding and the aggregate verdict |
| `docs/Subsystems/Testing/PR-DEVEX-CI-110_Risk_Proportionate_CI.md` | Origin of the contract gate and census measurement; its routing design is removed |
| `docs/Subsystems/Testing/PR-TEST-TRUTH-200_Actionable_CI.md` | Actionable CI output and the quarantine directory audit |
| `docs/Subsystems/Testing/PR-TEST-TRUTH-210_Pre_Forge_Execution_and_Test_Truth.md` | Skip policy and deterministic-execution rules |
| `docs/Subsystems/Testing/PR-TEST-TRUTH-250_GUI_Collection_Authority_Closeout.md` | Why the old GUI collection exceptions were retired |
| `docs/Subsystems/Testing/KNOWN_PITFALLS_QUEUE_TESTING.md` | Queue-test patterns and races |
| `docs/Subsystems/Testing/Optional_Capability_Contract_v2.6.md` | Optional-capability profiles and what a skip may mean |
| `docs/Subsystems/Testing/E2E_Golden_Path_Test_Matrix_v2.6.md` | Golden-path coverage matrix |
| `docs/runbooks/sqlite_job_migration.md` | Operator migration steps behind the SQLite persistence tests |
| `docs/audits/2026-10-16_repo_audit_and_roadmap.md` | Audit A1-A10 (CI gaps), D8 (GUI tests), B2 (job object) behind today's gates |
