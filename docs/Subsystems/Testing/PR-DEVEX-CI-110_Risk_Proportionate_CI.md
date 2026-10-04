# PR-DEVEX-CI-110 - risk-proportionate CI, contract gate and test census

Result class: **VALIDATION ROUTING + CROSS-BOUNDARY CONTRACT GATE + MEASUREMENT.** No product/runtime behavior changed, no test was
deleted, skipped or weakened. Execution profile: Standard (Claude Code, Sonnet 5.5 High).

## Why

GitHub CI ran the whole ~4,800-test Linux/Xvfb census on essentially every PR: about 11-12 minutes per head, roughly 14 billed
Actions minutes (the required job is billed 2 minutes, the census job 12), and about 672 of a 2,000-minute allowance in the first four
days of a billing cycle. PR-IMG-116 also showed that important regressions are *boundary* failures (artifact metadata -> Review
source -> reprocess builder -> immutable NJR -> backend identity; runtime ownership -> serving process -> loaded model files),
so a pure changed-path classifier is not enough: cheap classification must be followed by a small always-run contract gate.

## Previous policy

`required` (completeness, controller ratchet, Ruff, mypy smoke, collection, 184-test smoke list, clean-tree check) plus an
informational `full-suite` (all ~4,800 tests) on every PR head, in parallel.

## New model

```
base-to-head change set
  -> tools/ci/validation_plan.py (stdlib, repository-owned; the workflow only consumes its plan)
  -> required        repository quality + cross-boundary contract gate (always; cheap for docs-only)
  -> affected        only the affected lanes of a bounded executable PR       (informational)
  -> full-suite      ONE full census for broad/unbounded changes              (informational; replaces `affected`)
```

* **Docs-only** (prose/media only): `required` runs `git diff --check`, repository completeness and the controller ratchet with
  the runner's system Python. No Python 3.14 setup, no pip install, no tests, no census.
* **Executable PR**: `required` (installs the environment once) then `affected` (only after `required` succeeds).
* **Broad / unbounded**: `required`, then one `full-suite`; `affected` is skipped because the census subsumes it (no double payment).
* **Docs-only follow-up over green evidence**: a docs-only delta (`before..after`) takes the cheap path only when the repository-owned
  helper `tools/ci/previous_evidence.py` (a pure, tested policy, not jq in YAML) finds the previous head's evidence green: the latest
  GitHub-Actions `required` check run concluded `success`; the latest `affected` and `full-suite` runs concluded `success` or `skipped`
  (a check that merely has `status: completed` is never enough: failure, cancelled, timed_out, action_required, neutral, in-progress
  or missing all block reuse); and the current PR base is already an ancestor of the previous head (if `main` advanced, normal
  validation runs). The base-to-head classification is *not* downgraded; only what this run re-executes changes. An explicit
  full-census request always wins.
* **Docs-only keeps CI/document truth**: the cheap path runs `tools/ci/ci_truth.py` (stdlib; the same authority the pytest truth tests
  call), so a docs edit that violates current CI/testing canonical truth (Level 1-3 testing authority, the PR-gate pointer in `AGENTS.md`,
  stale "always a full-suite job" statements in `STATUS.md`/`CODEX_MAP.md`) fails the cheap job without installing the application
  environment. Ordinary docs edits do not become full-census changes.
* Preserved: one PR-head workflow (no push trigger), `cancel-in-progress` per PR head, `workflow_dispatch`, and the `required` check
  name (branch-protection identity).

## Lanes (coarse, additive; not a dependency graph)

`docs_only`, `core`, `image`, `video`, `gui`, `runtime`, `qualification_tools`, `ci_test_authority`, `full_census_required`.
A change may activate several lanes and every activated lane runs. Ownership is by path (`LANE_RULES`) and test membership is by
explicit target lists (`LANE_TARGETS`, `DOMAIN_TARGETS`) - a cross-boundary test belongs to every lane that owns one side of the
boundary, not only to its directory (for example `tests/integration/test_pr_img*` and `tests/safety/test_forge*` are image-lane
targets that live under other directories). Image and runtime sources deliberately do **not** activate `core`: the always-run contract gate
protects the boundary, and `core` runs when core source (queue, NJR, compiler, runner, controller, services, utils) changes. Domain families whose
source is rarely touched (`learning`, `promptpacks`, `randomizer`, ...) run when their source or tests change.

| Lane | Source ownership (examples) | Affected tests |
|---|---|---|
| `core` | `src/queue`, `src/history`, `src/state`, `src/pipeline`, `src/controller`, `src/services`, `src/utils`, other `src/*` | queue, history, migrations, state, controller, pipeline, integration, services, system, safety, unit, utils, regression, compat, app, cli, top-level files |
| `image` | `src/image_backends`, `src/api` (except runtime), `src/pipeline` (with `core`) | image_backends, api, image integration/safety, Klein/reprocess pipeline tests |
| `video` | `src/video`, SVD/video pipeline modules | video, SVD/video pipeline tests |
| `gui` | `src/gui`, `src/gui_v2`, `src/controller` | gui_v2, gui, review, curation, top-level state/GUI tests, GUI controller and journey tests (+ the cross-domain rules above) |
| `runtime` | process manager, runtime identity/transition, bootstrap scripts, `tools/runtime`, managed-runtime config | process/launch/runtime API and service tests, managed runtime system tests, app, safety |
| `qualification_tools` | `tools/qualification`, `tools/acceptance`, other `tools/*` | `tests/tools` |
| `ci_test_authority` | workflows, `tools/ci`, `pyproject.toml`, conftest | (implies the full census) |

### Conservative escalation

* **Full census** (`full_census_required`): `pyproject.toml`, requirements/constraints/locks, pytest/tox/mypy/ruff configuration,
  `.python-version`, `.github/workflows`, `tools/ci` (the policy, the gate, the census tooling), any `conftest.py`, and shared test
  infrastructure (`tests/helpers`, `tests/fixtures`, `tests/mocks`, `tests/data`).
* **Unknown ownership** (no lane rule matches: a new top-level directory, an unmapped root script or config file): `full_census_required`
  and recorded as an escalation. It is never docs-only, never "no tests" and never assumed to be core-only. Known data/meta trees
  (`presets/`, `packs/`, `lists/`, `data/`, `config/`, `.gitignore`, `.editorconfig`, `.gitattributes`, `.claude/`) are explicitly owned
  by `core` so ordinary data edits do not escalate.
* **Cross-domain source -> test ownership** (`CROSS_DOMAIN_RULES`, additive on top of the lane rules; coarse, not a dependency graph):
  learning GUI surfaces (`src/gui/*learning*`, `src/gui_v2/*learning*`) also run the learning, learning_v2, learning-controller and
  golden-path tests; prompt-workspace/pack model-state surfaces (`src/gui/models/*`, `prompt_workspace_state`, `prompt_pack_adapter_v2`)
  also run state, promptpack and the top-level state tests; `app_state_v2` and its projection sink also activate `core`; GUI panels also
  run the controller preview/sidebar and integration (queue/job-timing) tests; API-status, dropdown-loader and movie/video GUI views
  also activate `runtime`, `image` and `video`. A policy test re-derives the evidence (which test files import each source directly)
  and fails if a changed source would not run the tests that import it.
* Text that is executable or configuration (`.github/workflows`, `scripts`, `config/*.json`, `presets/*.txt`, `.md` under `src/` or
  `tests/`) is never documentation.
* **Directly changed tests always run**: every modified `test_*.py` is added to the affected targets (or is covered by the census).
* A routing-rot guard test requires every lane target to match something and every collected test file to be owned by a lane, a
  domain target or the census-only set, so a new test directory cannot silently fall out of routing.

### Requesting a full census without editing YAML

Apply the `full-census` PR label (before the push that should run it), put `[full-census]` in the head commit message, or run the
workflow manually with `workflow_dispatch` on the branch. Scheduled and dispatched runs are always full. Cadence is policy:
`schedule: cron "0 7 * * 1,3,5"` (Monday/Wednesday/Friday 07:00 UTC) in `.github/workflows/ci.yml`; raise it there if routing proves
unstable. Run a census before a release with `workflow_dispatch`.

## The required contract gate

`tools/ci/run_required_smoke.py`: the existing 184-test positive smoke list plus `CONTRACT_GATE_TARGETS` (110 tests), 294 tests in
about 30 seconds locally. The contract suite protects invariants *between* subsystems; feature behavior stays in the lanes:

| Invariant | Required tests |
|---|---|
| Immutable job identity survives construction; model/profile identity is never silently lost | new `tests/system/test_construction_identity_contract.py` (every builder: backend identity explicit, profiled model keeps its versioned profile, unprofiled gets none, serialization round trip) |
| Canonical production path / queue-first | smoke list (`test_core_run_path_v2`, `TestQueuedModeExecution`, operator-journey harness) and `test_image_backend_contract.py` (NJR -> JobService -> SQLite -> `run_njr`) |
| Replay: new identity + parent lineage | `test_pipeline_replay_job_v2`, `test_replay_vs_fresh_v2`, replay case in `test_image_backend_contract.py` |
| Backend identity: no strip/substitute/switch; foreign combinations fail closed | contract test above (a profile is accepted only by its own backend), `test_identity_mismatch_fails_the_job_before_any_generation_post`, A1111-unchanged test, no-fallback tests in `test_image_backend_contract.py` |
| Runtime ownership: only owned runtimes are mutated; external never adopted/stopped | `test_runtime_transition_service`, `test_webui_process_manager_identity`, `test_forge_backend_isolation_safety` |
| Ambiguous generation POST is never replayed | `test_webui_retry_policy_v2` (read-timeout/connection-error/ADetailer cases), `test_ambiguous_dispatched_forge_generation_post_is_never_replayed`, `test_ambiguous_external_generation_fails_without_recovery_or_replay` |
| SQLite is the lifecycle authority | smoke list (`test_job_repository_sqlite`, `test_sqlite_job_importer`, queue integration) |
| The routing policy itself | `test_ci_validation_plan`, `test_ci_census_summary` |

The new construction-identity contract fails if the PR-IMG-116 reprocess regression is reintroduced (verified by reverting that fix:
the reprocess/Review-restored cases and the foreign-backend case fail). It is not Klein-specific architecture; Klein is simply the only
profile that exists today.

Finding recorded while building the gate: `test_forge_txt2img_enters_through_queue_and_records_forge_identity_everywhere` passes in
the census but fails when run in the gate's isolated working directory because it reads the legacy global negative prompt from the
ambient presets directory. It was left out of the gate rather than edited here; it is a candidate hermeticity fix.

## Test census (measured)

Complete deterministic run on a Windows workstation (Python 3.14, local, serial, JUnit with setup/teardown included): **4,830 tests
collected, 4,806 passed, 22 skipped, wall 18 min 19 s** (1,099.7 s). The hosted Linux/Xvfb census for this PR is recorded in
"GitHub evidence" below and published by the workflow as `census.xml` / `census-summary.json` plus a step summary
(`tools/ci/census_summary.py`; standard library only; slowest 200 tests, time by file and by area, skip reasons).

| Area | Tests | Seconds | Share |
|---|---:|---:|---:|
| tools | 622 | 212.3 | 19.5% |
| pipeline | 609 | 192.8 | 17.7% |
| gui_v2 | 630 | 164.0 | 15.0% |
| controller | 516 | 120.6 | 11.1% |
| integration | 146 | 103.6 | 9.5% |
| api | 277 | 81.1 | 7.4% |
| top-level files | 99 | 57.5 | 5.3% |
| video | 520 | 32.2 | 3.0% |
| system | 203 | 24.1 | 2.2% |
| learning_v2 + learning | 372 | 33.4 | 3.1% |
| queue + utils + image_backends + services + state + unit + the rest | ~1,000 | ~70 | 6% |

Pareto: the 10 slowest files are 38.5% of test time with 151 tests (3% of the count); the slowest 50 files are 70.5%; the single
slowest file (`tests/tools/test_operator_journey_gui.py`, 8 tests) is 13.1%. The slowest *tests* are real waits, not assertions: the
top three (`test_ensure_connected_timeout_sets_error` 49 s, `test_filesystem_fallback` 38 s, `test_check_api_ready_failure` 31 s) are
timeout/readiness paths that wait in real time. Skips: 22 (14 optional `cv2`/`numpy` extras, 2 collection skips, opt-in local
process/qualified-graph tests).

## Test ownership census (analysis only; nothing mutated)

| Family | Tests | What it protects | Where it runs now |
|---|---:|---|---|
| Cross-boundary contract | 294 (smoke + contract list) | identity, canonical path, queue-first, replay, ownership, ambiguity, persistence | every executable PR (`required`) |
| core | ~2,090 (pipeline 609, controller 516, integration 146, utils 239, queue 122, services 92, system 203, state 52, ...) | compiler/NJR/queue/runner/history/lifecycle | `core` lane |
| image | 388 (api 277, image_backends 111) | still-image backends, WebUI API | `image` lane |
| video | 520 | native SVD, video workflows | `video` lane |
| gui | 630 + review/curation | Tk views, controllers adapters, state projection | `gui` lane |
| runtime | subset of api/services/app/safety/system | process ownership, bootstrap, transition | `runtime` lane (also in `core`) |
| qualification | 622 | harness/driver/tooling for physical qualifications | `qualification_tools` lane |
| domain families | learning_v2 322, learning 50, assets 23, refinement 17, promptpacks 16, curation 15, ... | domain logic | when their source/tests change; census otherwise |
| census only | mocks 9, compat/legacy-adjacent, the long tail | shared infrastructure | full census (periodic / broad PRs) |

## Phase-B candidates (not authorized; no test was changed here)

Each candidate states the unique signal that would remain if consolidated; none is called redundant merely because it has long been green.

1. **Real-time waits in unit tests** (the ~14 slowest tests, about 120-250 s). Candidate: inject clocks/timeouts. Unique signal kept:
   the timeout/readiness *behavior* (state transitions and error text); only the wall-clock wait is removed.
2. **Operator-journey GUI harness tests** (3 files, 36 tests, ~155 s, mostly fake-journey process waits). Candidate: keep one end-to-end
   journey per release lane and move the rest to the periodic census. Kept: the end-to-end operator path; lost from per-PR: variations.
3. **Historical `test_pr_*` files** (45 files, 400 tests, ~147 s). Candidate: consolidate assertions that repeat the canonical-path
   contract (queue->runner->history) into the contract gate and retire exact duplicates. Kept: each PR's unique regression
   assertion; a duplicate-assertion audit per file is a prerequisite.
4. **Canonical-path integration repeated across backends** (`test_pr_img_forge_100_canonical_path`, `test_pr_img_116_*`, `test_pr_runtime_*`,
   ~68 tests, ~55 s): parametrize a single canonical harness over backends. Kept: backend-specific payload/identity assertions.
5. **GUI matrices** (`gui_v2` 630 tests, ~164 s; 138 GUI-named files): equivalent widget-state permutations. Kept: one representative
   per distinct behavior; needs per-file review.
6. **Qualification tests** (622 tests, ~212 s): already isolated to the `qualification_tools` lane; no unrelated PR pays for them now.
   Consolidation is not needed for routing.
7. **Hermeticity**: tests that depend on ambient presets or working directory (see the finding above) should be made hermetic before
   any consolidation so moves do not change outcomes.

## Risks accepted

* The affected lanes and the census are informational (as the census already was); only `required` blocks. Promotion is a later,
  evidence-based owner decision.
* Lane membership is coarse and path-based; a boundary regression whose tests live in another lane is caught only if the contract gate
  or an explicitly cross-listed target covers it. The routing-rot test and the periodic census are the backstops.
* `required` no longer runs the full census on ordinary PRs; a regression only visible in the full suite surfaces on the next
  scheduled run (Mon/Wed/Fri) or a requested census.
* Reuse of previous evidence trusts the previous head's completed check runs (read through the GitHub API).
* Hosted CI does not exercise GPU, A1111, Forge, Comfy, CUDA, SVD or filesystem/runtime behavior; those remain opt-in local acceptance.

## Rollback

Revert the PR (restores the single `required` + always-on `full-suite` workflow). A partial rollback that keeps the policy but runs the
census everywhere: make `full_census` always true in `.github/workflows/ci.yml` or add the `full-census` label to every PR.

## GitHub evidence

Hosted timing and the final census for the repaired executable SHA are recorded here after that SHA's single full census completes
(a docs-only commit then reuses the evidence through the safe path above). Earlier measurements taken on the first implementation
SHAs are not repeated here to avoid presenting superseded routing as final.
