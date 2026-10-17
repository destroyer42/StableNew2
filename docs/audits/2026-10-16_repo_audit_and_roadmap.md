# StableNew: repository audit, priorities and improvement roadmap

**Date:** 2026-10-16
**Status:** point-in-time audit record; the roadmap's live sequencing belongs in `STATUS.md` once adopted.
**Baseline:** `main` at `d43fdc39`. The audit began at `d025d82a`; PR #106 merged partway through. The boundary and reachability counts were re-run at `d43fdc39` and did not change.
**Scope:** `src/`, `tests/`, `tools/`, `scripts/`, `.github/`, all documentation and process files, and the git, PR and CI history.
**Mode:** read-only. No code was changed, and no app, backend or GPU work was launched. The only test run was one pass of the hermetic required gate.

**Method.** Six read-only audits ran in parallel: core execution path; GUI; backends, runtime and security; product features; tests, CI and tooling; documentation, process and git history. They used AST scans, import-graph reachability, grep counts, CI run history and artifacts (via `gh`), and git analytics. I then re-checked the highest-impact claims myself (see section 9.1).

**Evidence labels:**
- **[V]** verified directly in this session.
- **[A]** measured by an auditor with commands or CI artifacts; I did not re-run it.
- **[I]** inferred from reading the code; needs runtime confirmation before acting on it.

---

## 1. Executive summary

The core design is sound and its core is well built. The canonical path runs end to end: Intent → Compiler → NJR → JobService → SQLite repository/queue → `PipelineRunner.run_njr` → handlers → artifacts and history. The NJR is the NormalizedJobRecord, the immutable versioned job envelope. Persistence is carefully engineered, and the safety instincts are good: ambiguous generation POSTs are never replayed, StableNew controls only processes it launched, and runtimes stay on loopback. The weaknesses lie elsewhere, and they reinforce each other.

1. **The automated safety net is much thinner than the process narrative suggests.**
   - Only 4% of tests (386 of 9,704) can block a merge.
   - The lanes that actually catch regressions are non-blocking and show green even when they fail.
   - `main` has no protection, and direct pushes to it get no CI.
   - mypy checks 10 of 590 files, while a full run finds 1,701 errors, some of them real defects.
2. **Real defects sit on production paths.** Two of them can disrupt your live runtime:
   - A test run or second instance can kill your managed Forge, because every process manager opens the same named Windows job object.
   - The documented WebUI startup gate is never switched on in the production wiring.
   - Also: learning data is written non-atomically and has already been corrupted, a GUI thread-safety bug, silent fallbacks that drop settings, and Comfy and SVD subprocesses that can't be cancelled or timed out.
3. **The architecture rules are broken in practice by a few god objects, so every change is expensive.**
   - `AppController` is 7,414 lines, the executor 6,782, and `run_njr` is a single 1,042-line method.
   - NJRs are built at 8 different construction sites, each applying a different subset of policies.
   - Model-family branches sit inside generic modules, a pattern ARCHITECTURE §12 forbids. Adding a model family touches about 15-25 files.
4. **The documentation and process system now costs more than it returns.**
   - Starting a task means reading about 72k tokens. STATUS.md alone is about 59k tokens, roughly 5% current state, and partly wrong.
   - STATUS.md and CODEX_MAP.md are the two most-churned files in the repository and the main source of merge conflicts.
   - Qualification harnesses make up 74% of `tools/` and 14% of the test suite.
5. **The product's differentiators are stored but not shown, and the most-wanted generation features are missing even though Forge already provides them.**
   - History shows the latest 20 of your 22,946 jobs, with no search.
   - Learning's "Apply" path can't be reached from the UI.
   - There is no inpainting or mask editor, no ControlNet beyond a single OpenPose unit, no X/Y/Z grid, and no searchable gallery.

### The 12 actions to take first

| # | Action | Effort | Why |
|---|---|---|---|
| 1 | Protect `main` (require a PR plus CI), and add a push trigger to CI | S (owner) | Untested code reaches `main` today, and `main` stayed red for days |
| 2 | Delete the `codex-autofix.yml` workflow | S | It is a pwn-request path on a public repo: any GitHub user can run code with a PR-write token |
| 3 | Isolate the Windows job object per process manager, and stub it in tests | S | Today a test run can kill your live managed Forge |
| 4 | Turn on the startup gate and NJR strictness in the production wiring | S | The documented behavior isn't actually active |
| 5 | Make the full census (sharded at 3) the merge gate, and delete the "affected" routing | S | Coverage goes from 4% to 100%, and PR CI time halves (9.8 → 4.9 min) |
| 6 | Atomic writes for every store, with write failures shown to the user | S | Your learning data has already been corrupted by a mid-write reset |
| 7 | One pinned dev lock file; correct the declared dependencies | S | The gate fails in a fresh supported environment; `main` went red over an undeclared PyYAML |
| 8 | mypy per-file ratchet across all of `src` | S | It already exposes real silently-swallowed defects |
| 9 | Add a Windows CI lane | S-M | The product is Windows-only but CI is Linux-only; Windows defects can't be seen |
| 10 | Cut STATUS.md to 150 lines or fewer, plus a guard against stale or overlong content | S | Saves about 55k tokens per task and removes most merge conflicts |
| 11 | Fix the five verified production defects in sections 4.B5-B8 | S each | Silent setting loss, thread safety, and hung subprocesses |
| 12 | Build a history browser with "Replay with changes" | M-L | Makes your 22,946 jobs and the reproducibility promise actually usable |

### Targets for about 10 weeks

| Metric | Today | Target |
|---|---|---|
| Tests that block a merge | 4% | 100% |
| CI on Windows | none | a required Windows lane |
| Tokens to start a task | about 72k | 15k or fewer |
| Net `src` size | — | about 15k lines smaller |
| `tools/` size | 43.6k | about 30k lines smaller (harness archive) |
| Files touched by a new model family | about 15-25 | 5 or fewer |
| Executor size | 6,782 lines | under 3,000 |
| `AppController` size | 7,414 lines | under 4,000 |
| Jobs you can browse | 20 | all 22,946 |
| Applied Learning recommendations | 0 | measured above 0 |

---

## 2. The repository at a glance

| Measure | Value |
|---|---|
| History | 883 commits (2025-11-29 → 2026-10-15). PR-based work since 2026-09-26: 98 PRs in 30 days, about 4.9 per day, with 0 reviews. Median time from PR open to merge is 34 minutes [A] |
| `src` | 177.5k lines in 590 Python files [V]: gui 60.9k, pipeline 22.3k, video 18.3k, controller 17.4k, utils 10.0k, learning 8.4k, api 6.6k |
| Tests | 174.5k lines in 920 files [V]; 9,704 tests collected [A] |
| `tools` | 42.5k lines [V], of which 31.6k (74%) is qualification, acceptance and archive-reference harness code [A] |
| Documentation | STATUS.md is 150 KB in 1,638 lines [V]; `docs/Subsystems` has 116 files, about 590k tokens, 107 of them per-PR records [A] |
| Largest files | `app_controller.py` 7,414 lines (exactly its ratchet ceiling); `executor.py` 6,782; `learning_controller.py` (GUI layer) 4,022; `pipeline_runner.py` 3,007; `api/client.py` 2,443 [V] |
| Size of a typical PR | median +1,215 / −39 lines. Over the last 80 PRs: +154k / −17k, an 11% deletion ratio. From Oct 1 to 15, `src` grew by a net +39.9k lines (+29%) [A] |
| Mix of the last 98 PRs | features 22%, fixes 19%, reliability/containment 12%, qualification/harness 16% (27% of added lines), devex/CI 21%, diagnostics 4%, docs 4% [A] |
| CI | The `required` job (386 tests, about 28 s) is the only blocking check. `affected` and the 3-shard census are informational [V/A] |
| GitHub settings | Public repo. `main` has no branch protection or rulesets. The default workflow token has write access and can approve PRs. Any action is allowed, and SHA pinning is not required [V] |

## 3. Strengths to preserve

- **Persistence.** One shared SQLite connection under an RLock, `BEGIN IMMEDIATE`, WAL, `synchronous=FULL` and a 10 s busy timeout. Lifecycle transitions are guarded, and callbacks fire after commit [A].
- **Runtime safety rules, enforced by tests.** Ambiguous POSTs are never replayed, external runtimes are never adopted or killed, managed Forge is pinned to loopback, and the `listen`/`share` flags are forbidden [A].
- **Clean basics.** `src` contains no `torch.load`, pickle, `yaml.load`, `eval`/`exec` or `shell=True`. Model-file header reads are size-capped, the YuNet detector is hash-pinned, and imports have essentially no side effects [A].
- **Reproducible runtimes.** Exact pins with drift verifiers for the StableNew, managed Forge and managed Comfy environments [V].
- **Determinism.** Compilation is deterministic and NJRs are immutable, which makes golden snapshot tests cheap during later refactors.
- **Healthy hygiene numbers.** Little skip/xfail debt (0 skip, 0 xfail, 17 skipif). `ruff check` is clean. 70% of modules have a docstring [A].
- **Good instincts.** The engineering intuitions about invariants, ownership, immutability and replay lineage are good. The problem is how they are enforced, not what they are.

---

## 4. Findings

Severity runs Critical > High > Medium > Low. Effort is S (a day or less), M (2-5 days), L (1-3 weeks) or XL (more than 3 weeks), for one agent-assisted developer.

### 4.A Safety net and delivery pipeline

**A1. `main` is unprotected, and direct pushes skip CI. Severity: High.**
- **Evidence [V]:**
  - The branch-protection API returns 404 and there are no rulesets.
  - `ci.yml` triggers only on `pull_request`, `workflow_dispatch` and `schedule`; there is no `push` trigger.
  - Non-PR commits sit on `main`'s first-parent history even after the "never push to main" rule was written. Examples:
    - `d12e0545`: a qualification harness plus tests, +2,531 lines.
    - `9f00e240`: touches `prompt_pack_job_builder.py` and `model_policy.py`.
    - `8caf9462`: titled "settings.json".
- **Evidence [A]:** `d12e0545` added the test that turned the `main` census red (`ModuleNotFoundError: yaml`). It is the only failure in the latest `main` census (Oct 14: 9,444 passed, 1 failed, 66 skipped).
- **Impact:** untested code lands on `main`, and `main` stays red without anyone noticing.
- **Fix:** add a ruleset on `main` that requires a PR, the `required` check, and later the census verdict, and that blocks force-pushes and branch deletion. An owner bypass is optional. Add `push: branches: [main]` to CI.
- **Effort:** S.

**A2. Only 4% of tests block a merge, and the lanes that catch real regressions are non-blocking and show green. Severity: High.**
- **Evidence [V]:** `continue-on-error: true` is set on `affected`, `full-suite-shard` and `full-suite`.
- **Evidence [A]:**
  - The required gate is 386 tests, and 47% of them test the CI tooling itself.
  - Over the last 100 CI runs, `required` failed 0 times, `affected` 10 of 58, and the census 13 of 31.
  - PRs #96, #100 and #101 merged with a red census. Seven PRs merged with neither lane run.
  - The `main` census was red on Oct 12 and Oct 14 but displayed "success".
  - The red lanes caught real regressions: `test_jobrunner_integration` (`['txt2img'] != ['final_output']`), a Z-Image canonical-path `KeyError`, Learning e2e "Nothing queued", the Photo Optimize tab, and the Forge ADetailer projection. They were fixed only because an agent happened to open the job page.
- **Fix:** make the sharded census blocking for every executable PR.
- **Effort:** S.

**A3. The "affected" routing is slower than the full census and misses tests. Severity: High.**
- **Evidence [A]:**
  - The affected lane takes a median 8.6 minutes and runs 52-62% of the suite. The census runs 100% in a median 3.4 minutes across 3 shards. End to end, a PR takes a median 9.8 minutes on the affected path and 4.9 minutes on the census path.
  - Routing gaps:
    - Changes to `src/photo_optimize/*` miss 9 of the 10 test files that import it.
    - A dead `src/ai_v2/*` pattern means `tests/ai_v2` never runs.
    - Changes to `src/utils/config.py` miss 19 of its 48 test importers; `src/learning` misses 19 of 92.
  - The routing policy is 533 lines with 75 tests of its own, and `tools/ci` has had 34 commits since Sep 15.
- **Fix:** delete the lane routing, keep only docs-only detection, and always run the census.
- **Effort:** S.

**A4. Type checking is in name only, and mypy finds real defects. Severity: Medium-High.**
- **Evidence [V]:** the CI mypy gate checks 10 files, even though `pyproject.toml` sets `strict = true`.
- **Evidence [A]:**
  - A run over all of `src` finds 1,701 errors in 202 of 592 files, so 390 files are already clean.
  - Top error codes: no-untyped-def 334, attr-defined 294, no-untyped-call 271, arg-type 200.
  - Real defects found this way are listed in B5.
- **Fix:** a per-file baseline ratchet. Gate the 390 clean files now, and burn down attr-defined, call-arg and arg-type errors first.
- **Effort:** S for the ratchet, M for the burn-down.

**A5. CI doesn't test the platform the product runs on. Severity: High.**
- **Evidence [V/A]:**
  - The product is Windows-only: a `.bat` launcher, Windows job objects, `%LOCALAPPDATA%` paths and Windows CUDA constraints.
  - All CI runs on `ubuntu-latest`.
  - Defects that only exist on Windows are therefore invisible to CI:
    - the job-object collision (B2);
    - a cp1252 crash in `scripts/check_thread_registry_usage.py`;
    - Windows path assumptions.
- **Fix:** add a `windows-latest` lane, which is free for public repos. It should cover process/job-object handling, paths, encodings, SQLite and a Tk construction smoke test. Run it informational for a week, then make it required.
- **Effort:** S-M.

**A6. The CI environment isn't the product environment, and dependencies are undeclared, dead or unpinned. Severity: Medium-High.**
- **Evidence [V]:** `requirements.txt` includes pytest, pytest-cov and requests-mock, plus `ttkbootstrap` and `tkinterdnd2`, which `pyproject.toml` omits.
- **Evidence [A]:**
  - `ttkbootstrap` and `tkinterdnd2` are imported nowhere.
  - numpy is imported in 5 `src` files but not declared.
  - PyYAML is undeclared, which is what turned `main` red.
  - `cv2` is used by refinement code but declared only in the SVD extra.
  - CI installs pytest, mypy, pytest-timeout and pytest-xvfb unpinned.
  - The Windows bootstrap installs neither ruff nor mypy, so `run_pr_gate.py` exits with TOOLING BLOCKER in a fresh supported environment.
  - The main checkout's `.venv` is Python 3.12 without mypy.
- **Fix:** one pinned dev lock file used by both CI and bootstrap, and correct dependency declarations.
- **Effort:** S.

**A7. Formatting has drifted and the local guardrails don't run. Severity: Medium.**
- **Evidence [A]:**
  - `ruff format --check` would reformat 403 of 1,714 files (23.5%).
  - pre-commit configures both black and ruff-format, and it isn't installed.
  - `check_daemon_threads.py` already fails on `main` (14 `daemon=True` uses in 8 files).
  - The thread-registry check crashes under cp1252.
- **Evidence [V]:** the pre-commit config uses the deprecated `stages: [commit]` alias.
- **Fix:**
  - Use ruff-format only and do one formatting commit.
  - Add `ruff format --check` to the required gate.
  - Turn the thread guards into tests with an allowlist.
- **Effort:** S.

**A8. A test leaks files into the repository, and `.gitignore` hides it. Severity: Medium.**
- **Evidence [V]:**
  - `tests/controller/test_learning_controller_review_feedback.py:55-76` uses a relative `img_a.png`, so a review sidecar gets written into the repo root.
  - `.gitignore:85` (`/*.review.json`, commented "generated runtime/test artifacts") hides it.
  - CI's clean-checkout check uses `--porcelain`, which skips ignored files, so the leak is invisible there too.
  - Test-run debris also appears in `output/`, `state/` and `data/learning/`.
- **Fix:**
  - Use `tmp_path` in the test and remove the ignore rule.
  - Extend the clean check to known runtime directories.
- **Effort:** S.

**A9. Flaky and environment-dependent harness tests. Severity: Medium.**
- **Evidence [A]:**
  - `test_img_116_klein_acceptance_driver` builds an ID from `int(time.time())` and is flaky against the wall clock. It failed 3 of the 7 censuses that were downloaded, including `main` on Oct 12.
  - Other tests assume `%LOCALAPPDATA%` (Windows-only) or a Tk geometry.
- **Fix:**
  - Use fixed IDs.
  - Quarantine tests with an expiry date.
  - Classify failures by rerunning once.
- **Effort:** S.

**A10. Workflow hygiene. Severity: Low-Medium.**
- **Evidence [V]:**
  - The default workflow token has write access and can approve PRs.
  - Any action is allowed, and `GabrielBB/xvfb-action@v1` is not SHA-pinned; it is also redundant with pytest-xvfb.
- **Evidence [A]:**
  - `required` has no timeout, so a hang costs 6 hours.
  - The self-hosted workflow has 0 runners registered.
  - `copilot-setup-steps` references a `requirements-dev.txt` that doesn't exist.
- **Fix:**
  - Make the default token read-only.
  - SHA-pin third-party actions.
  - Add timeouts.
  - Delete the dead workflows.
- **Effort:** S.

### 4.B Correctness and runtime-safety defects on production paths

**B1. The Codex AutoFix workflow is a pwn-request path on a public repo. Severity: High (Critical as soon as any secret is configured).**
- **Evidence [V]:**
  - It triggers on any `issue_comment` containing `/codex-autofix`, with no `author_association` check.
  - It checks out `pr.head.repo.full_name` at `pr.head.ref`, which means fork code, chosen by branch name, so there is also a time-of-check/time-of-use (TOCTOU) race.
  - It then runs that checkout's `pip install -r requirements.txt` and `tools/codex_autofix_runner.py`, with `OPENAI_API_KEY` and a `pull-requests: write` token in the environment.
  - The fork-PR approval policy (`first_time_contributors`) does not apply to `issue_comment` events.
  - The workflow is vestigial: every recent run was skipped, and it needs a `requirements-dev.txt` that doesn't exist.
- **Impact:** any GitHub user can run code holding a PR-write token that can also approve PRs. The OpenAI key would leak the moment one is added.
- **Fix:** delete the workflow.
- **Effort:** S.

**B2. Every `WebUIProcessManager` shares one named Windows job object, so a test run or second instance can kill your live managed Forge. Severity: High.**
- **How it happens [V]:**
  - `webui_process_manager.py:247-249` builds its container with the constant ID `"webui_process_manager"`.
  - `process_container_v2.py` turns that into the job name `StableNewJob-webui_process_manager`.
  - `win_jobobject.py:81` calls `CreateJobObjectW(None, name)`. When that name already exists, Windows opens the existing job instead of creating a new one, and the code never checks `ERROR_ALREADY_EXISTS`.
  - The container is created in the constructor (`:148`).
  - The stop paths call `kill_all()`, which calls `TerminateJobObject` (`:772`, `:819`).
- **Evidence [A]:**
  - 17 of the 23 test files that build a real manager don't stub the container. For example, `tests/api/test_webui_process_manager_shutdown_v2.py:48-83` marks a fake process as owned and then calls `stop_webui()`.
  - The PID is assigned to the job only after `Popen` returns, so early grandchild processes escape the job.
- **Impact:** running pytest, the CLI or a second instance on Windows while your app has managed Forge running can terminate that Forge. That breaks the "only what our manager launched" invariant.
- **Hypothesis [I]:** this may have contributed to some unexplained Forge exits, since agents often run tests in worktrees while you use the app. It is unproven.
- **Fix:**
  - Use an anonymous job object, or a pid+uuid name, and fail closed on `ERROR_ALREADY_EXISTS`.
  - Add an autouse conftest stub for the container.
  - Harden by assigning the child to the job before it runs.
  - Add a two-process reproduction test on Windows.
- **Effort:** S.

**B3. The production wiring never enables the WebUI startup gate or NJR strictness. Severity: High.**
- **Evidence [V]:**
  - Production starts at `src/main.py:781` with `build_v2_app`, which constructs `AppController(job_service=None)` without a pipeline controller.
  - `AppController` then builds `PipelineController(job_service=None)`. That creates its own repository, queue and runner, and constructs `JobService(queue, runner, history_store, history_service=...)` without `require_normalized_records=True` (`pipeline_controller.py:734-738`).
  - `AppController` adopts that service (`app_controller.py:564-571`), so `_build_job_service()` (`:2476-2490`) never runs. It holds the only `enable_startup_gate()` call in `src`.
  - `_startup_gate` defaults to `False` (`webui_outage_coordinator.py:156`).
  - The gate is tested only through services constructed directly in `tests/queue`, never through the production wiring.
  - The PR-QUEUE-WEBUI-171 doc says "In production a startup gate holds WebUI claims until a fresh proof."
  - Pause and auto-run state is held in three separate places.
- **Impact:**
  - After a restart, restored WebUI jobs can be claimed before WebUI readiness and identity are proven, so they fail instead of being held.
  - A job without an NJR is accepted rather than failed (`job_service.py:401-409`).
- **Fix:** enable the gate and the strictness flag on the service production actually uses, without building a second repository or queue. Add a wiring test that goes through `build_v2_app`. Replace this with a single composition root in P3-2.
- **Effort:** S.

**B4. Learning, Discovered, UI-state and LoRA stores write non-atomically; real data is already corrupted, and rating-write failures are silent. Severity: Medium-High.**
- **Evidence [V]:** `experiment_store.py:155-157` writes with a plain `write_text`.
- **Evidence [A]:**
  - The same pattern is in `discovered_review_store.py:458-460`, `ui_state_store.py:55` and `lora_manager.py:144`.
  - One of your experiment `session.json` files is 100,884 NUL bytes (2026-09-18). That is the signature of a hard reset in the middle of a write.
  - `append_record` swallows exceptions and logs them at DEBUG, while the UI shows the rating as saved.
  - `photo_optimize/store.py` and `promptpacks/storage.py` already write safely.
- **Fix:** one shared atomic-write helper (temp file, fsync, `os.replace`), and surface write failures in the UI.
- **Effort:** S.

**B5. Broad `except` blocks hide functional bugs (found through mypy). Severity: Medium.**
- **Evidence [V]:**
  - `pipeline_controller.py:236` and `:246` call `_extract_state_overrides()`, a method that doesn't exist. Both calls sit inside `except Exception: _logger.debug(...)`.
  - This code is on the live state-fallback preview/run path (`get_preview_jobs_for_request` → `_build_normalized_jobs_from_state`, `:462`). On that path, batch size, batch runs, output directory and filename pattern therefore always fall back to defaults.
  - Even if the method existed, `OutputSettings(filename_template=...)` at `:249` passes a keyword the class doesn't accept.
- **Evidence [A]:**
  - `client.py:845` has a mismatch in the retry-callback keyword arguments.
  - `app_controller.py:7409` imports `StableNewApp`, which doesn't exist (in a dead `__main__` block).
- **Fix:** fix or delete the affected code; then the mypy ratchet (A4) and a blind-`except` ratchet (P1-5) catch the rest.
- **Effort:** S.

**B6. The Learning background scan updates Tk widgets from a worker thread. Severity: Medium-High.**
- **Evidence [V]:** `learning_controller.py:4012` reads `getattr(self, "_after_fn", None)`, but `_after_fn` is never assigned anywhere, so `on_complete` always runs on the worker thread.
- **Evidence [A]:** that callback calls `Var.set` and `configure` and rebuilds the inbox tree. The scan starts a raw daemon thread outside ThreadRegistry.
- **Impact:** intermittent Tcl errors or hangs, especially at shutdown.
- **Fix:** inject `TkUiDispatcher.invoke`, spawn the thread through ThreadRegistry, and add a test that checks which thread the callback runs on.
- **Effort:** S.

**B7. The managed Comfy runtime has no crash containment, no cancellation, and fragile output readers. Severity: High.**
- **Evidence [A]:**
  - `comfy_process_manager.py:97-107` starts Comfy with `Popen` and no job object or process group. `text=True` is used without an explicit encoding.
  - `stop()` only does terminate followed by kill.
  - After a hard crash, the orphaned Comfy is classified as a "healthy external ComfyUI", so StableNew refuses either to launch or to stop it.
  - The reader threads die silently, and an undrained pipe can then block Comfy.
  - The history wait ignores `cancel_token`, there is no `/interrupt` call, and waits last up to 1,200 s.
  - A read timeout on `POST /prompt` surfaces as a raw requests exception, so retrying duplicates GPU work.
- **Fix:**
  - A ManagedProcess primitive (P3-3).
  - Cancel-aware polling plus `/interrupt`.
  - A typed "dispatch outcome unknown" error that is never retried automatically.
- **Effort:** M.

**B8. SVD postprocess subprocesses have no timeout, cancellation or containment. Severity: Medium-High.**
- **Evidence [A]:**
  - `svd_postprocess.py:499-505` runs the CodeFormer/upscale worker and `:705-711` runs RIFE, both with no timeout.
  - A hang blocks the single queue runner indefinitely, and an orphaned worker keeps holding VRAM.
  - A bounded runner already exists in `driving_video_inspection.py`.
- **Fix:** extract that into a shared `run_bounded()` and use it here.
- **Effort:** S.

**B9. Provenance can be lost silently. Severity: Medium.**
- **Evidence [A]:**
  - At `executor.py:771-795` the metadata builder returns `None` on any error, so the PNG is saved without provenance and nothing is logged.
  - At `pipeline_runner.py:2135-2143`, failures in `write_run_metadata` hit a bare `pass`.
  - At `:1222-1228` the NJR SHA silently becomes `None`.
  - At `job_repository.py:87-93`, corrupt stored JSON quietly becomes defaults.
  - Exceptions in listeners are dropped without logging.
  - There are two hash identities: `ensure_ascii=True` in the repository and `False` in artifacts. So embedded provenance can't be matched to its SQLite row by hash.
- **Fix:**
  - Log every provenance failure and mark the artifact `provenance_incomplete`.
  - Use one hash identity.
  - Surface corrupt rows as integrity errors.
- **Effort:** S-M.

**B10. Discipline around the queue lock, callbacks and cancellation. Severity: Medium [I].**
- **Evidence:**
  - `JobQueue._update_status` and `claim_next_job` call `transition_job`, which runs observers synchronously while the non-reentrant queue lock is held. That is a latent self-deadlock.
  - The return-to-queue paths change the job outside the lock and without `expected_status`.
  - `cancel_current` marks a job CANCELLED before the generation has actually stopped.
  - The idle loop polls at 20 Hz.
  - The 600 s job ceiling is checked only between stages.
- **Fix:**
  - Notify observers after releasing the lock, as `submit_many` already does.
  - Use `expected_status` on every transition.
  - Add a CANCELLING state (needs your decision).
  - Use an event-driven idle wait.
- **Effort:** M.

**B11. Embedded metadata is gzip-decompressed without a size limit. Severity: Low-Medium.**
- **Evidence [A]:** `image_metadata.py:306-311` and `svd_portable_provenance.py:247-254` call `gzip.decompress` on chunks an attacker could craft. The size caps exist only on the write side.
- **Impact:** a crafted file opened in Review can spike memory or crash the GUI. There is no code-execution risk.
- **Fix:** decompress with a bounded `decompressobj`.
- **Effort:** S.

### 4.C Architecture and code structure

**C1. The executor is effectively the WebUI backend, but it lives in generic `src/pipeline` and carries model-family branches, a pattern ARCHITECTURE §12 forbids. Severity: High.**
- **Evidence [A]:**
  - `WebUIFamilyImageBackend.execute` calls back into `pipeline.run_*_stage` (`webui_family_backend.py:215-285`).
  - The generic txt2img stage contains family-specific code:
    - Z-Image wire projection (`executor.py:5139-5145`);
    - `sdxl_guarded` handling (1713-1742);
    - the SDXL refiner (4879-5081);
    - the ControlNet unit (5147-5172).
  - Family names appear 21 times in the executor, 25 in the PromptPack builder, 15 in `reprocess_builder` and 3 in `job_builder_v2`.
  - `PipelineRunner.__init__` requires an `SDWebUIClient`.
  - `controller/prompt_pack_preflight.py:98` imports a GUI dialog, a controller-to-GUI layer inversion.
  - "klein" appears in 36 `src` files (526 occurrences) and "zimage" in 15 (189). A third family would touch about 15-25 files.
- **Impact:** the backend-adapter boundary from PR-IMG-100 exists in name only, and every new model family is expensive.
- **Fix:** an exact-profile plugin protocol plus typed stage settings, then move the executor under `src/image_backends/webui/` (P4-4, P4-5).
- **Effort:** L.

**C2. NJRs are built by hand at 8 construction sites, each applying a different subset of policies. Severity: High.**
- **Evidence [A]:**
  - `NormalizedJobRecord(` is called in:
    - `job_builder_v2.py:162`
    - `prompt_pack_job_builder.py:675`
    - `reprocess_builder.py:335`
    - `cli_njr_builder.py:105`
    - `training_njr_compiler.py:59`
    - `njr_core_v26.py:1263`
    - `learning/model_comparison.py:783`
    - `gui/controllers/learning_controller.py:1276`
  - Cross-cutting policies are applied unevenly: model compile policy in 4 builders, Z-Image validation in 2, effective-config preparation in 1, intent canonicalization in 3.
  - PromptPack builds every job twice.
  - GUI runs that don't come from a pack are recorded as `SourceKind.CLI`, so their provenance is mislabeled.
  - There are two SourceKind alias tables, the config shape differs by source, and there are 7 deep-merge implementations.
- **Impact:** which guarantees a job gets depends on which builder happened to build it.
- **Fix:** a single `compile_njr(intent)` core. Write golden NJR snapshot tests first, then migrate one builder at a time (P4-2).
- **Effort:** L.

**C3. God objects and copy-pasted monoliths. Severity: High.**
- **Evidence [V/A]:**
  - `AppController`: 7,414 lines, 346 methods, and 89 attributes set in a 322-line `__init__`.
  - `run_njr` is a single 1,042-line method.
  - 24 functions are 150 lines or longer, 7,671 lines in total.
  - The img2img, adetailer and upscale branches of `run_njr` repeat the same blocks, including a `free_vram` + `sleep(1.0)` sequence swallowed by `except: pass`.
  - The executor's stage methods (789, 714, 539, 297 and 268 lines) each re-implement the same steps: admission 6×, model/VAE 6×, drift 7×, metadata 7×, manifest 6×.
- **Fix:** a stage-handler registry inside `run_njr` (P4-1), keeping `run_njr` as the only public entry point.
- **Effort:** M for the runner, L for the executor.

**C4. Stage configuration is untyped dicts with spreading key aliases. Severity: Medium-High.**
- **Evidence [A]:**
  - `.get("…")` calls by file:
    - executor: 572, over 195 keys;
    - runner: 214, over 110 keys;
    - `AppController`: 464, over 243 keys, plus 392 `getattr` and 103 `hasattr` calls.
  - `StageConfig` types only 8 fields.
  - ADetailer CFG has 3 key spellings, steps 2, denoise 3, and model 4.
  - The normalizer writes both spellings back, so the old aliases never go away.
- **Fix:**
  - Typed per-stage settings, resolved once at compile time.
  - Legacy aliases accepted only when loading historical snapshots, with a stated removal condition (P4-4).
- **Effort:** L, done incrementally.

**C5. The line-count ratchet moves code around instead of decomposing it. Severity: Medium.**
- **Evidence [A]:**
  - Since 09-07, `AppController` shrank by 398 lines while `src/controller` grew from 15,349 to 17,415 lines and from 31 to 46 files.
  - The executor, which no ratchet covers, grew by 831 lines.
  - The check only looks at top-level files in `src/controller`, so subpackages, `src/pipeline` and `src/gui/controllers` are unbounded.
  - The `job_service_*` modules are free functions that call the service's private members.
- **Fix:** ratchet the designated god objects, including the executor and `learning_controller`, on both size and public-method count. Count a split as decomposition only when it deletes code.
- **Effort:** S.

**C6. Layering: 23 packages form a single import cycle, and `utils` imports upward. Severity: Medium.**
- **Evidence [A]:**
  - Counting import-time imports only, 23 packages form one strongly connected cycle.
  - `utils` imports from higher layers: pipeline 5, queue 3, promptpacks 3, config 3, api 2, controller 1 (`graceful_exit.py:12` imports `AppController`).
- **Fix:** an AST layering test, plus a ratchet on the size of the cycle so it can only shrink (P1-5).
- **Effort:** S, then M.

**C7. Infrastructure is duplicated. Severity: Medium.**
- **Evidence [A]:**
  - Two `/options` throttles: 6 s in `client.py`, 8 s in `webui_api.py`.
  - Two classes named `WebUIResourceService`.
  - Two near-identical health-check modules.
  - Ten bare `requests.get` calls with no session reuse.
  - 12 separate file-hash helpers.
  - 17 ad-hoc `ConfigManager()` constructions.
  - Two `StageConfig` classes, two `StageExecution` classes, and two `CancellationError` classes.
- **Fix:** consolidate these as part of the typed-transport and composition-root work (P3-2, P3-4).
- **Effort:** M.

### 4.D GUI

**D1. The GUI layer compiles learning NJRs and prompts itself, which §12 forbids. Severity: High.**
- **Evidence [A]:** `learning_controller.py:1018-1317`:
  - builds NJRs and rewrites prompts;
  - hard-codes defaults (Euler a, 20 steps, CFG 7, clip skip 2);
  - falls back to the literal prompt "a test prompt" when there is no frozen snapshot;
  - mutates the experiment it is compiling.
- **Fix:** move this into a `compile_variant_njr` in `src/learning` (P4-3).
- **Effort:** M.

**D2. A 4,022-line god controller sits outside the ratchet. Severity: High.**
- **Evidence [A]:** a single class with 130 methods and 40 broad `except` blocks. It grew from 479 to 4,022 lines over 52 commits and is the most-changed GUI file.
- **Fix:** add it to the ratchet now, then split it into learning services.
- **Effort:** S for the ratchet, L for the split.

**D3. Widgets act as composition roots, and controller and window depend on each other in both directions. Severity: Medium-High.**
- **Evidence [A]:**
  - The Learning tab builds stores and services using the private `pipeline_controller._job_service`.
  - Review reaches the learning controller through `app_controller.main_window.learning_tab.learning_controller`.
  - `src/controller` references `main_window` 107 times and sets Tk variables directly.
  - The Run button is wired twice, so whichever wiring runs last wins.
- **Fix:** compose everything in the bootstrap (P3-2), replace controller-to-widget writes with AppStateV2 projections, and give toolbar wiring a single owner.
- **Effort:** M-L.

**D4. Tab construction failures are swallowed, leaving blank tabs and nothing in the log. Severity: Medium.**
- **Evidence [A]:**
  - `MainWindowV2.add_tab` (L757-778) catches any exception from a tab constructor, inserts an empty frame, and logs nothing. 6 of the 9 tabs are built this way.
  - The GUI has 681 broad `except` blocks, 407 of them silent: about 6.5 silent handlers per thousand lines, versus 3.3 in the core.
- **Fix:** log the error and show an error placeholder, then add a ratchet on broad `except` blocks.
- **Effort:** S, then M.

**D5. Blocking disk and image work runs on the Tk thread. Severity: Medium.**
- **Evidence [A]:**
  - Photo Optimize saves on every KeyRelease: it reads the sidecar, makes 3 directories, re-reads, writes a temp file and replaces.
  - The Review folder scan runs `rglob` plus `resolve` on the Tk thread.
  - The compare view composites at full resolution.
  - Thumbnails are decoded with LANCZOS on the Tk thread and decoded again on every resize.
- **Fix:** debounce the saves, and move decoding to a worker with an LRU cache (P4-7).
- **Effort:** M.

**D6. Five different background-work patterns coexist, and the guardrails aren't enforced. Severity: Medium.**
- **Evidence [A]:**
  - The five patterns:
    - `BackgroundWorkRunner`;
    - a mailbox task;
    - ThreadRegistry with `after(0)`;
    - a ThreadPoolExecutor polled every 50 ms;
    - raw threads.
  - Thumbnails start one OS thread each.
  - There are four ways of marshaling work back to the Tk thread, plus 56 bare `after()` calls.
- **Fix:** one primitive with a bounded pool; thread guards as tests.
- **Effort:** M.

**D7. There is no single view-model pattern. Severity: Medium.**
- **Evidence [A]:**
  - AppStateV2 is a 591-line mutable dataclass with about 70 fields, including `controller: Any`.
  - The toolkit-neutral `gui_v2` layer is only 1.4k lines, about 11% of the GUI's Tk-free logic.
  - 38 Tk modules import 177 domain symbols.
- **Fix:** standardize on the view_contracts style (a frozen view dataclass, a Tk-free session, and injected services), applied tab by tab as each one is touched.
- **Effort:** L.

**D8. GUI tests are numerous but brittle, and run on Linux only. Severity: Medium.**
- **Evidence [A]:**
  - 1,038 GUI tests, about 450 of which build a real Tk root.
  - 1,475 accesses to private attributes, and 55 `__new__` bypasses.
  - Production code branches on `PYTEST_CURRENT_TEST`.
  - The test fixture builds a compatibility shim class rather than the production window.
- **Fix:** test presenters without Tk, inject an explicit test-mode flag, and add a Windows construction smoke test.
- **Effort:** M.

**D9. All tabs are built at startup, and much of the GUI is unverified surface. Severity: Medium.**
- **Evidence [A]:**
  - All 9 tabs are built at startup.
  - 6 of them are marked advanced/unverified, about 21.7k lines, versus 20.7k for the supported ones.
  - About half the GUI churn lands on those unverified surfaces.
- **Fix:** build tabs lazily. Whether to hide unverified tabs is your call.
- **Effort:** S-M.

**D10. Polish issues. Severity: Low-Medium.**
- **Evidence [V]:** the tab is titled "Photo Optomize" (`main_window_v2.py:346`), and the window title is "StableNew V2 (Spine)" (`:235`).
- **Evidence [A]:**
  - Review raises 52 modal dialogs, including a "Saved" dialog after every feedback save.
  - There is no thumbnail grid anywhere.
  - There are three theme-token systems and 51 hard-coded colors.
- **Effort:** S.

**D11. The toolkit: Tk is not the limiting factor.**
- **Evidence [A]:**
  - None of Tk's weak areas are in use today.
  - The defects above are structural, not caused by the toolkit.
  - A virtualized thumbnail grid and a Canvas-based mask editor are both feasible in Tk.
- **Recommendation:** stay on Tk and do D7 first. Spike Qt for a single surface only if a huge gallery or video scrubbing proves it necessary.

### 4.E Backends, runtime and video

**E1. The HTTP client is a god object with inconsistent error handling. Severity: Medium.**
- **Evidence [A]:**
  - `SDWebUIClient` has 70 methods covering transport and retry, options and throttling, default policies, generation, progress and about 15 resource getters. Its constructor reads settings from disk.
  - The Comfy client tries once and raises raw exceptions.
  - Timeouts are ad hoc: 3/60/600 s for WebUI, 5-30/300 s for Comfy, 0.5 s for probes.
  - `src/cli.py:126` scans ports 7860-7864, contradicting the "alternate ports are never probed" rule.
  - There is also a dead second launcher.
- **Fix:**
  - An `HttpTransport` with a `RequestPolicy` and typed errors: endpoint unavailable, dispatch outcome unknown, definite refusal, malformed response.
  - Split the client into Resources, Options and Generation.
  - Delete the port scan (P3-4).
- **Effort:** M.

**E2. Model-family logic is spread through if/isinstance chains (see C1). Severity: Medium.**
- **Evidence [A]:**
  - `model_policy.py:237-308` reads, in effect, "if it's a ZImageProfile, otherwise assume Klein".
  - `forge_webui_backend.py` branches on both families.
  - There are 8 dedicated family modules (1,904 lines), 10 more files mention both families, and 77 test files mention a family.
- **Fix:** an `ExactProfilePlugin` protocol with a list-based registry. First wrap the existing families with no behavior change, then remove the branch sites one at a time (P4-5).
- **Effort:** L.

**E3. Video: more options exist than can be reached, and every runtime requalification mints a new workflow version. Severity: Medium.**
- **Evidence [A]:**
  - There are 3 video backends and 11 workflow specs, and none is approved: Wan is experimental and both LTX specs are disabled.
  - Version 1.2.0 is the same graph requalified on a newer Comfy, and the graphs are inline Python dicts.
  - Unreachable or broken options:
    - AnimateDiff has no GUI control and needs the A1111 extension.
    - GFPGAN is offered in the GUI but refused by the worker.
    - The story-plan and continuity modules (677 lines) are reached only from tests.
  - Adding a Comfy-hosted model takes about 3 files, but a native backend takes about 15.
- **Fix:** a declarative workflow registry, with graph JSON, a content hash and a manifest, keeping qualification records separate from graph versions (P4-6).
- **Effort:** M.

**E4. `utils/` is a grab-bag. Severity: Medium.**
- **Evidence [A]:**
  - 7 modules are dead. One of them, `clear_standby_memory`, calls `logging.basicConfig` at import time.
  - A duplicate `CancellationError`.
  - Imports point upward into higher layers.
- **Fix:** delete the dead modules and move the rest into the layers that own them (P3-1, P1-5).
- **Effort:** S-M.

**E5. Runtime exposure and supply chain: mostly sound, with small gaps. Severity: Low.**
- **Evidence [A]:**
  - A user-configured `comfy_command` is never checked for `--listen 0.0.0.0`.
  - SVD defaults to `local_files_only=False`, which means a multi-GB Hugging Face download at job time and an automatic remote refresh after a failed local load.
  - Bootstrap installs are pinned by version but not by hash.
  - The tracked `presets/settings.json` contains personal absolute paths.
- **Evidence [V]:** there is no LICENSE file, although `pyproject.toml` says MIT.
- **Effort:** S each.

**E6. Resource hygiene. Severity: Low.**
- **Evidence [A]:**
  - Disk space isn't checked before SVD frame dumps or Comfy downloads.
  - WebUI logs get one new file per launch, written relative to the current directory, with no rotation.
  - The API-failure ring keeps the full base64 payload for each of its 20 entries.
- **Effort:** S.

### 4.F Documentation, process and agent economics

**F1. Starting a task costs about 72k tokens; STATUS.md is a 59k-token PR log, about 5% current state, and partly wrong. Severity: High.**
- **Evidence [V]:** STATUS.md is 150 KB in 1,638 lines, and line 148 still says PR #104 is "open… not merged" (it merged on 10-15).
- **Evidence [A]:**
  - Startup cost:
    - Following the instructions literally means reading about 72k tokens before starting.
    - That rises to about 106k with the whole code map, and about 143k with the full authority chain.
  - Shape:
    - 78% of STATUS.md is PR narrative and 17% is superseded history; one bullet is 409 lines long.
    - 22 of its 57 PR entries describe merged PRs as local, draft, open or unmerged.
  - Contradictions:
    - "3.14 only" versus "supported Windows Python 3.11/3.12 bootstrap", which appears 15 times.
    - DIAG-GPU-130 is described as both "ACTIVE OBSERVATION" and "COMPLETE".
- **Impact:** every session pays about 59k tokens before doing anything, and agents plan from false statements.
- **Fix:** cut STATUS.md to 150 lines or fewer, plus a `ci_truth` guard on its line count and on banned stale markers (P2-1).
- **Effort:** S-M.

**F2. There are no living subsystem docs, so the truth has to be pieced together from per-PR records. Severity: High.**
- **Evidence [A]:**
  - The image subsystem has 36 docs, about 200k tokens. Understanding today's image pipeline means reading about 15 of them, roughly 120k tokens.
  - `PR-IMG-FORGE-100` alone is 51.5k tokens, and it was edited in 23 of the last 400 commits. It is effectively a living document under a PR name.
  - `GUI_Ownership_Map` was last updated 09-07.
  - Documentation doubled during Oct 1-15, from 14.0k to 27.6k lines.
- **Fix:** one living document per subsystem, 400 lines or fewer, edited in place (P2-2).
- **Effort:** L.

**F3. Shared append-only docs are the top source of churn and merge conflicts. Severity: High.**
- **Evidence [A]:**
  - In the last 400 commits, STATUS.md changed 129 times and CODEX_MAP 99 times; the busiest source file changed 17 times.
  - 10 of the 12 branch-sync merges since 9/26 resolved conflicts in these files, and 6 of those had no code conflict at all.
- **Impact:** parallel work collides on prose, which is a hidden reason for the "one active package at a time" rule.
- **Fix:** the restructure in P2-1 through P2-3.

**F4. CODEX_MAP is an index of PRs rather than a map of the code. Severity: Medium.**
- **Evidence [A]:** it is 34.8k tokens, 69 of its 87 rows are named after PRs, and 70% of modules already have docstrings.
- **Fix:** generate the map from docstrings, with a freshness check in CI, plus a short hand-written table (P2-3).
- **Effort:** M.

**F5. The Roadmap and Architecture docs are frozen but still named as authorities. Severity: Medium.**
- **Evidence [V]:**
  - The roadmap says "Updated: 2026-09-16".
  - The architecture gap register is dated 2026-09-13 and still lists "Operator readiness" and "Release proof" as Open, while the roadmap says PR-MVP-090 is COMPLETE.
- **Evidence [A]:** the roadmap never mentions Photo Optimize, Z-Image, OpenPose or batch operations, and it says the next package is still PR-IMG-FORGE-100, which is finished.
- **Fix:** close the gap-register rows, move sequencing into STATUS "Next", and check doc header dates in CI.
- **Effort:** S.

**F6. The process ceremony is duplicated, unevenly followed, and has never been calibrated. Severity: Medium.**
- **Evidence [A]:**
  - There are 23 governance files totaling 76.9 KB, and the same rule is paraphrased in up to 9 of them.
  - The PR template lacks the sections the rules require.
  - Of the last 50 PR bodies, the required sections appear this often:

    | Section | PRs that include it |
    |---|---:|
    | Execution Profile | 20 (all Codex; none of the 30 Claude Code PRs) |
    | Controller Surface Assessment | 19 |
    | Validation Plan | 22 |
    | Model / usage | 3 |

  - The model-selection calibration loop has never been run.
- **Fix:** keep AGENTS.md as the single rule source, link to it everywhere else, match the template to what is actually checked, and drop or automate the per-PR model/usage ceremony (P2-4).
- **Effort:** S-M.

**F7. Qualification code stays in the active tree. Severity: Medium.**
- **Evidence [A]:**
  - 24 per-PR harness packages, 27.9k lines.
  - Together with acceptance and archive-reference code, 31.6k lines (74% of `tools/`) and 1,384 tests (14% of the suite, 22% of census test time).
  - 2 of the 3 causes of a red census on `main` were harness tests.
  - Identical test bodies are copied across 9 groups.
- **Fix:** tag and remove each harness once it has delivered its verdict (P2-6, needs your decision).
- **Effort:** M.

**F8. A stale runbook tells you to kill processes the contract protects. Severity: Medium.**
- **Evidence [A]:**
  - `docs/runbooks/ZOMBIE_PROCESS_RECOVERY.md` was last changed 2025-12-25. It instructs force-killing python/cmd processes, including any "with working directory matching WebUI path", which contradicts AGENTS.md §5.
  - `scripts/kill_orphan_pythons.ps1` kills any python process older than 1 hour or using more than 10 GB, after a y/N prompt.
- **Fix:** delete both, or rewrite them with steps limited to processes StableNew owns.
- **Effort:** S.

**F9. Version identity and the changelog. Severity: Low.**
- **Evidence [V]:** the version is 1.0.0 in `pyproject.toml`, 1.0.4 in `.stableNew_version.txt` (which has a byte-order mark), and "v2.6" in the README.
- **Evidence [A]:**
  - The CHANGELOG's last release section is 2.1.0 from 2025-11, and none of the 98 PRs since 9/26 is recorded.
  - There are no git tags.
  - 13.5% of distinct path references in the docs no longer resolve.
- **Fix:** a single version source, tags, and a changelog generated from PRs.
- **Effort:** S.

**F10. Growth is additive with almost no deletion. Severity: Medium (systemic).**
- **Evidence [A]:** the deletion ratio is 11%, and from Oct 1 to 15 `src` grew 29% and tests 56%.
- **Impact:** the code agents must read and keep consistent grows faster than its structure improves, and context costs compound.
- **Fix:** deletion pressure (section 5.1); cohesion ratchets (C5); a rule that harness code leaves the tree after its verdict (F7).

### 4.G Product and functionality gaps

**G1. Provenance and replay can't be used at scale. Severity: High.**
- **Evidence [V]:** history loads `limit or 20` jobs (`app_controller.py:2796-2808`).
- **Evidence [A]:**
  - Those jobs appear in a 6-row tree view with no search, filter, sort or thumbnails.
  - There is no "use these settings", "edit and rerun" or compare action.
  - Your repository holds 22,946 jobs (17,598 completed).
- **Impact:** the core reproducibility value is invisible to you.
- **Fix:** a history browser (P5-1).
- **Effort:** M-L.

**G2. Learning's feedback loop works in code but can't be reached from the UI. Severity: High.**
- **Evidence [V]:** the automation-mode variable (`learning_tab_frame_v2.py:151`) defaults to `suggest_only` and is bound to no widget.
- **Evidence [A]:**
  - Apply is disabled in `suggest_only` mode, and `apply_with_confirm` appears only in an allowed-values list.
  - Your data: 77 experiments, 4 committed ratings, and 504 rated review drafts that were never saved.
  - Learning is about 18k lines, roughly 10% of `src`.
- **Impact:** no recommendation ever reaches generation. Triage and curation are what you actually use.
- **Fix:**
  - Add an automation-mode selector and commit drafts on save.
  - Show how many more ratings are needed.
  - Pause further Learning expansion until usage is measured (P5-2).
- **Effort:** S-M.

**G3. No editing or conditioning breadth. Severity: High (competitive).**
- **Evidence [A]:**
  - ControlNet is a single OpenPose unit, txt2img only, with pre-rendered maps.
  - There is no mask painting, no outpainting, no regional prompting and no IP-Adapter.
  - Forge Neo already exposes ControlNet and inpainting over the API StableNew uses.
- **Fix:** P5-3 and P5-4.
- **Effort:** M-L.

**G4. There is no X/Y/Z grid. Severity: Medium.**
- **Evidence [A]:**
  - Learning only does one-variable sweeps, and `MULTI_VARIABLE_EXPERIMENT` is declared but never used.
  - Your experiments are mostly LoRA strength (34), CFG (24) and steps (19), which is exactly the X/Y plot use case.
- **Fix:** a 2-3 axis sweep that produces a labeled contact sheet (P5-2).
- **Effort:** M.

**G5. The out-of-box experience is empty and tied to this machine. Severity: Medium.**
- **Evidence [A]:**
  - The tracked `packs/` directory holds only legacy `.txt` and `.json.bak` files, and the resolver never reads repo packs, so a new user starts with zero PromptPacks.
  - `presets/` tracks runtime state.
  - `app_config.py:35` hard-codes `C:\Users\rob\stable-diffusion-webui`, and the LoRA and embedding pickers use it directly, bypassing `STABLENEW_WEBUI_ROOT`.
  - The README still says "MVP recovery", and there is no user guide.
- **Fix:** P5-6.
- **Effort:** S-M.

**G6. LoRA and model management is minimal, and metadata interop is partial. Severity: Medium.**
- **Evidence [A]:**
  - The LoRA picker is a dropdown with a strength value; there are no previews and no downloads.
  - The PNG `parameters` text lacks the Model hash and LoRA hashes. As a result Civitai won't auto-link the resources, and Forge's PNG Info loses settings.
- **Fix:** P5-5.
- **Effort:** M.

**G7. Video has no approved workflow, and Character Training is a stub. Severity: Medium.**
- **Evidence [A]:**
  - Wan2.2 TI2V-5B has real acceptance evidence (about 83 s per 49 frames) but is still experimental.
  - Character Training passes flags that kohya, OneTrainer and ai-toolkit don't accept, and no trainer is shipped.
- **Fix:** P5-7, plus your decision on what to do with training.
- **Effort:** S-M.

**G8. Dead and confusing surfaces. Severity: Low-Medium.**
- **Evidence [A]:**
  - 64 of 592 modules (8,668 lines) can't be reached from any entry point.
  - `src/ai` is a stub that hard-codes 512x704.
  - `src/cluster` does nothing.
  - Learning saves its banner label as state, so prefixes stack up: "Workflow: Workflow: …".
  - The support surface is still labeled "A1111".
- **Fix:** P3-1 and P5-6.
- **Effort:** S.

### 4.H Dead code and leftovers (consolidated)

| Area | What | Size | Label |
|---|---|---|---|
| Core | Executor `run_pack_pipeline` (454 lines, no references); legacy `run_img2img`/`run_upscale` implementations (269); 102 unreachable lines after `return None` in `run_adetailer` (`executor.py:4199-4300`); the runner's legacy cluster (2443-2835); `payload_builder.py` (458 lines, kept alive only by tests); `AppController._run_pipeline_from_tab`, which calls `api.txt2img` directly (a latent GUI-to-backend path) | about 1.8k lines unreachable even from tests; about 3.4k unreachable from `src` | [A] |
| GUI | 27 unreachable modules, including dead `_v2` copies next to the live unsuffixed versions; `run_app`, which would start the WebUI from GUI code; shims with no removal condition; an `__all__` that lists 4 names that don't exist | 3.9k lines | [A] |
| utils / video / misc | 7 dead utils modules; story-plan and continuity (677 lines); `src/ai`; `src/cluster`; a duplicate `history/duration_stats` | about 1.5k lines | [A] |
| Tests | `tests/scripts` (byte-identical copies, plus scripts that rewrite a user pack); `tests/legacy`; a pytest ignore entry for a `gui_v1_legacy` directory that no longer exists | small | [A] |
| Scripts | 12 of 26 scripts are referenced nowhere, including a byte-identical copy and the kill script | about 1.5k lines | [A] |
| Workflows | `codex-autofix`; `shutdown_leak_manual` (0 runners); `copilot-setup-steps` (broken) | — | [V/A] |
| Dependencies | `ttkbootstrap`, `tkinterdnd2`, `pytest-cov` | — | [A] |
| Harnesses (archive candidates) | `tools/qualification`, `tools/acceptance`, `tools/archive_reference`, plus their tests | 31.6k lines and 1,384 tests | [A] |

**Totals:** about 10-12k lines can be deleted now with high confidence and no behavior change. About 45k more go once the harness archive is decided.

---

## 5. Critical assessment

### 5.1 Root causes

1. **Rigor lives in prose, not in automation.** Every PR carries a detailed evidence narrative, but few guarantees are enforced mechanically. The pattern in the findings is consistent:
   - **Rules enforced by code hold.** Guarded SQLite transitions, no-replay tests and pinned runtimes all behaved as documented.
   - **Rules enforced by documents broke.** The §12 forbidden patterns, "the GUI must not compile", "the startup gate is on in production", the no-daemon-threads rule, and "never push to main" were all found violated.
   - **The lesson:** turn every rule that matters into a test or a ratchet, then delete the prose that restates it.
2. **Nothing pushes for deletion.** The deletion ratio is 11%. The ratchet moves code into new files instead of shrinking it, harnesses never leave the tree, and dead `_v2` copies sit beside the live code. Agents pay for every dead line they read, and the dead copies are a trap for editing the wrong file.
3. **The work mix leans toward defense and qualification rather than visible value.**
   - About 28% of PRs, and more than a third of added lines, went to qualification and containment.
   - Meanwhile the features that would make the differentiators visible don't exist: history search, replay with changes, grids, inpainting.
   - Much of the defensive work responds to platform instability: GPU device loss, hard resets, dead Forge processes.
   - Two findings suggest part of that instability is self-inflicted or made worse: B2 (tests can kill Forge) and B3 (the startup gate isn't wired). Fixing those costs far less than adding more containment layers.
4. **Features are built without usage feedback.** Learning is about 18k lines and has 4 committed ratings; its recommendations can't even be applied. No feature has a usage-based acceptance step.
5. **Docs are used as a database.** STATUS.md and CODEX_MAP serve as an append-only log and index. They grow without bound, conflict on every merge, go stale, and then mislead the next agent.

### 5.2 Where the audit's own claims need care

- **Inferences need a reproduction step.** The items marked [I] are the queue races (B10), the claim that B2 explains past Forge deaths, packaging behavior, and how much UI lag D5 actually causes. Each needs runtime confirmation, so every roadmap package that depends on one starts with a reproduction.
- **Dead-code totals are approximate.** They come from heuristics: token-based reference scans and AST reachability. The listed items were spot-checked. Dynamic imports could make a few modules live, so delete only in PRs that run the full census.
- **Your data counts may not cover your live data.** The 22,946 jobs, 4 ratings and the NUL-filled session file were read, read-only, from your local data roots. Your live data root may be different.
- **Efforts are planning estimates,** assuming one agent-assisted developer at your current throughput.

### 5.3 What not to do

- **Don't rewrite the GUI in Qt or anything else.** Structure is the bottleneck, not Tk.
- **Don't start new model-family qualifications or production slices until the plugin protocol (P4-5) exists.** That includes Comfy image, Qwen-Image-Edit and Kontext. Each one currently costs 15-25 files and deepens the §12 violations.
- **Don't keep investing in the affected-lane routing.** The full census is faster and complete.
- **Don't add new tabs or expand Learning** until the history browser and the Learning apply path ship and are actually used.
- **Don't rewrite the compile core or the executor in one go.** Extract behind golden tests, one builder or stage at a time.
- **Don't add more prose rules to AGENTS.md.** Convert the existing ones into checks.

---

## 6. Prioritization

### 6.1 Engineering priority (tech-debt scoring)

Each item is scored as Priority = (Impact + Risk) × (6 − Effort). Each factor runs from 1 to 5; effort maps S=1, S-M=2, M=3, L=4, XL=5.

| Rank | Item | Ref | Impact | Risk | Effort | Score |
|---:|---|---|---:|---:|---:|---:|
| 1 | Protect `main` and add the push trigger | A1 | 4 | 5 | 1 | 45 |
| 1 | Census as the merge gate; delete the affected routing | A2, A3 | 5 | 4 | 1 | 45 |
| 1 | Job-object isolation and the conftest stub | B2 | 4 | 5 | 1 | 45 |
| 4 | Startup gate and NJR strictness in production | B3 | 4 | 4 | 1 | 40 |
| 4 | mypy per-file ratchet | A4 | 4 | 4 | 1 | 40 |
| 4 | STATUS.md cut to 150 lines, plus the truth guard | F1 | 5 | 3 | 1 | 40 |
| 7 | Delete codex-autofix; harden token and action settings | B1, A10 | 2 | 5 | 1 | 35 |
| 7 | Atomic stores and surfaced write failures | B4 | 3 | 4 | 1 | 35 |
| 7 | Pinned dev lock; correct dependencies | A6 | 4 | 3 | 1 | 35 |
| 10 | Windows CI lane | A5 | 4 | 4 | 2 | 32 |
| 11 | Fix the silent-fallback defects | B5 | 3 | 3 | 1 | 30 |
| 11 | Bounded SVD postprocess subprocesses | B8 | 3 | 3 | 1 | 30 |
| 13 | Never-silent provenance; one hash identity | B9 | 3 | 4 | 2 | 28 |
| 14 | Learning scan thread fix | B6 | 2 | 3 | 1 | 25 |
| 14 | `add_tab` fails loudly | D4 | 2 | 3 | 1 | 25 |
| 14 | Fix the flaky and environment-dependent tests | A9 | 2 | 3 | 1 | 25 |
| 17 | Single composition root | P3-2 | 4 | 4 | 3 | 24 |
| 17 | ManagedProcess primitive and Comfy cancellation | B7 | 4 | 4 | 3 | 24 |
| 19 | Delete the dead code | 4.H | 3 | 2 | 2 | 20 |
| 19 | Layering guard and cycle ratchet | C6 | 2 | 2 | 1 | 20 |
| 19 | Formatting and guardrails | A7 | 2 | 2 | 1 | 20 |
| 19 | Fix the hermetic-test leak | A8 | 2 | 2 | 1 | 20 |
| 19 | Consolidate governance | F6 | 3 | 2 | 2 | 20 |
| 19 | Stale runbook and scripts | F8 | 1 | 3 | 1 | 20 |
| 25 | Stage-handler registry | C3 | 4 | 2 | 3 | 18 |
| 25 | Typed HTTP transport | E1 | 3 | 3 | 3 | 18 |
| 25 | Move learning out of the GUI; extend the ratchet | D1, D2 | 3 | 3 | 3 | 18 |
| 28 | Single compile core | C2 | 5 | 3 | 4 | 16 |
| 29 | Generated code map | F4 | 3 | 2 | 3 | 15 |
| 29 | Archive the harnesses | F7 | 3 | 2 | 3 | 15 |
| 29 | Queue lock discipline | B10 | 2 | 3 | 3 | 15 |
| 29 | Declarative video workflows | E3 | 3 | 2 | 3 | 15 |
| 29 | Bounded gzip decompression | B11 | 1 | 2 | 1 | 15 |
| 34 | Living subsystem docs | F2 | 4 | 3 | 4 | 14 |
| 34 | Typed stage settings | C4 | 4 | 3 | 4 | 14 |
| 36 | Exact-profile plugins | C1, E2 | 4 | 2 | 4 | 12 |

The long-horizon items (C1, C2, C4) score lower only because they are expensive. They are what makes the product cheap to extend, so the roadmap starts them as soon as the safety net exists to protect them.

### 6.2 Product value ranking

The debt formula undervalues features, so features are ranked separately here by value to you relative to effort.

| Rank | Capability | Value | Effort | Why now |
|---:|---|---|---|---|
| 1 | History browser, "Replay with changes" and compare | Very high | M-L | Unlocks 22,946 jobs and the reproducibility promise, using the existing NJR and replay path |
| 2 | Learning payoff: apply-with-confirm, draft commit, X/Y/Z grid | High | S-M plus M | The code mostly exists, and your experiments are X/Y shaped |
| 3 | Inpainting and outpainting with a mask editor | High | M-L | Forge supports it; it's the main reason to leave the app today |
| 4 | Multi-unit ControlNet (depth, canny, lineart, tile; IP-Adapter if Forge Neo has it) | High | M | Generalizes the existing OpenPose path |
| 5 | LoRA/model browser with A1111/Civitai-compatible metadata | Medium-High | M | Daily friction; the hashes are already computed |
| 6 | Out-of-box experience and polish | Medium | S-M | Cheap, and removes the dependence on this machine |
| 7 | Approve Wan2.2 TI2V-5B for video (after the Comfy fixes) | Medium | S-M | The acceptance evidence already exists |
| 8 | Editing models (Qwen-Image-Edit, Flux Kontext) as exact profiles | Medium | M each | Only after P4-5 |

---

## 7. Roadmap

**Principles.**
1. Build the safety net first; it multiplies the value of everything after it.
2. Every rule that matters becomes a check, and the prose restating it is deleted.
3. Phases 0-4 should each delete more code than they add.
4. From week 3, alternate one product package with one engineering package.
5. Stay on the canonical path, and create no new authorities. Items marked ⚑ are material changes that need your approval under AGENTS.md.

**Capacity assumption.** At your current throughput of about 5 PRs a day, work runs one package at a time through Phase 2. Two packages can run in parallel once prose merge conflicts are gone (the Phase 2 exit). The calendar weeks below are planning estimates.

### Phase 0: stop the damage (days 1-3)

| WP | Outcome | Scope | Acceptance | Effort | Refs |
|---|---|---|---|---|---|
| P0-1 ⚑ (you) | `main` is protected | A ruleset on `main` that requires a PR and the `required` check (add `full-suite` after P1-1) and blocks force-pushes and deletion, with an optional owner bypass. Make the default workflow token read-only, and stop Actions from approving PRs | Direct pushes are rejected (confirm via API) | S | A1, A10 |
| P0-2 | No workflow runs fork code with secrets | Delete `codex-autofix.yml` and `tools/codex_autofix_runner.py`. Delete or fix `shutdown_leak_manual.yml` and `copilot-setup-steps.yml`. Add a `push: main` trigger and job timeouts. SHA-pin third-party actions | The workflow list and settings check out | S | B1, A1, A10 |
| P0-3 | Tests can't touch your live runtime | An anonymous or pid+uuid job object that fails closed on `ERROR_ALREADY_EXISTS`. An autouse conftest stub for `build_process_container`. An opt-in Windows two-process reproduction test | Stopping one manager leaves another manager's child alive | S | B2 |
| P0-4 | The startup gate is really on in production | Enable the gate and `require_normalized_records=True` on the service production actually uses, without a second repository or queue. A wiring test through `build_v2_app` that checks the gate and that only one JobRepository exists | The wiring test passes and the queue tests stay green | S | B3 |
| P0-5 | Learning data can't be torn by a crash | A shared atomic write (temp file, fsync, `os.replace`) in `experiment_store`, `discovered_review_store`, `ui_state_store` and `lora_manager`. Record failures surface in the status banner | Fault-injection tests pass | S | B4 |
| P0-6 | `main` is green and honest | Declare PyYAML and numpy. Give the img_116 test a fixed ID. Fix the sidecar leak and drop the `/*.review.json` ignore. Fix or delete the state-override path and the `filename_template` keyword. Marshal the Learning scan back to the Tk thread. Make `add_tab` log and show an error placeholder | The scheduled census is green, with regression tests for each fix | S | A8, A9, B5, B6, D4 |

**Phase 0 exit:** `main` is protected, no workflow runs fork code with secrets, the census is green, and the six production defects above are fixed with regression tests.

### Phase 1: make the safety net real (weeks 1-2)

| WP | Outcome | Scope | Acceptance | Effort | Refs |
|---|---|---|---|---|---|
| P1-1 | The census is the merge gate | Remove `continue-on-error` from the census jobs, route every executable PR to the census, and make `full-suite` required. Delete the affected lane and its routing, keeping docs-only detection | 100% of active tests block; PR wall time is about 5 min | S | A2, A3 |
| P1-2 | A reproducible dev environment | A `requirements-dev` lock with exact versions of pytest, pytest-timeout, pytest-xvfb, pytest-xdist, ruff, mypy, types-requests and PyYAML, used by both CI and `bootstrap_windows.ps1`. Drop the dead dependencies. A single version source. Fix the packaging config. Add a LICENSE file | After a fresh bootstrap, `run_pr_gate.py` passes | S | A6, F9, E5 |
| P1-3 | A Windows CI lane | A `windows-latest` job covering process/job-object handling, paths, encodings, SQLite and a Tk construction smoke test. Informational for a week, then required | 5 green runs in a row, then required | S-M | A5, D8 |
| P1-4 | Type checking ratchet | mypy over all of `src` with a per-file baseline: no new errors anywhere, and clean files stay clean. Burn down attr-defined, call-arg and arg-type errors first | The gate takes 30 s or less, and the error count is published per PR | S, plus M for the burn-down | A4 |
| P1-5 | Formatting and guardrails as tests | One `ruff format` commit, and drop black. A `ruff format --check` gate. A baseline ratchet on ruff BLE001/S110 (broad and silent excepts). The no-daemon-thread and ThreadRegistry rules, and the layering rules (`utils` may not import upward; the cycle size may only shrink), become AST tests | All of these are in the required gate | S | A7, C6, D6 |
| P1-6 | A fast local gate | `run_pr_gate --full` mirrors CI, using pytest-xdist (`-n auto --dist loadfile`) with `xdist_group` for files that use Tk or global state | The full suite runs in minutes on Windows (measured) | M | A |

**Phase 1 exit:** 100% of tests can block a merge, Windows is covered, and the type, format, `except` and layering ratchets are active.

### Phase 2: lean, reliable docs and process (weeks 2-3)

These packages are docs-only, so they take CI's cheap path and can run alongside Phase 1.

| WP | Outcome | Scope | Acceptance | Effort | Refs |
|---|---|---|---|---|---|
| P2-1 ⚑ | STATUS.md at 150 lines or fewer | Sections: baseline and runtime; supported capabilities (one line each, linking to the living doc); the active package and "Next"; open owner decisions; holds; known debt. Record the old SHA as a pointer to the history. `ci_truth` adds a line cap and banned markers ("not merged", "local implementation", "3.11/3.12"), in warn mode first, then fail | Starting a task costs 15k tokens or less | S | F1, F5 |
| P2-2 | Living subsystem docs | 8 docs of 400 lines or fewer, edited in place: Image, Model profiles, Photo/Review/Reprocess, Video, Queue/Runtime/WebUI, Learning, PromptPacks/Prompting, Testing/CI. Image comes first. The per-PR docs leave the agents' read path, since git keeps them | The image pipeline can be understood from 15k tokens or less | L (incremental) | F2 |
| P2-3 | A generated code map | Generate the module map from docstrings and the package tree, with a freshness check in CI. A hand-written task-to-doc table of 60 lines or fewer | CODEX_MAP is no longer edited by hand in every PR | M | F4 |
| P2-4 ⚑ | One source for the rules | AGENTS.md holds the only rule text. CLAUDE.md, the Copilot instructions, the skills and the agent definitions link to it. The PR template matches what is actually checked. The model/usage ceremony is dropped or automated. The §13 gap rows are closed, and sequencing moves into STATUS "Next" | The governance files shrink by at least half | S-M | F5, F6 |
| P2-5 | No misleading operational material | Delete or rewrite the zombie-process runbook. Delete `kill_orphan_pythons.ps1` and the 11 other unreferenced scripts | — | S | F8, 4.H |
| P2-6 ⚑ | Finished harnesses are archived | The rule: a harness stays in the tree only while its package is active, and is tagged and removed once it has delivered its verdict. Shared primitives are extracted only when at least two harnesses need them | `tools/` loses about 30k lines; tests drop by about 1,400 | M | F7 |

**Phase 2 exit:** starting a task costs 15k tokens or less, two weeks pass without a prose merge conflict, and two packages can run in parallel.

### Phase 3: delete, consolidate and harden the runtime (weeks 3-5)

| WP | Outcome | Scope | Acceptance | Effort | Refs |
|---|---|---|---|---|---|
| P3-1 | Dead code is gone | Everything listed in 4.H outside the harnesses. Ratchet ceilings are lowered | The census is green; the reachability script shows 0 unreachable modules outside allowlisted entry points | S-M | 4.H |
| P3-2 ⚑ | One composition root | `build_runtime_stack()` in `src/app/bootstrap.py` builds the repository, queue, runner, JobService, coordinators and learning services exactly once, and injects them. One owner for pause and auto-run. No more widget composition roots or `PYTEST_CURRENT_TEST` branches (test mode is injected) | A wiring test passes; `JobRepository(` appears only in bootstrap and tests | M | B3, D3, C7 |
| P3-3 | Managed processes | A `ManagedProcess` primitive: an anonymous job object assigned before the child runs, UTF-8 readers with `errors=replace`, bounded output tails and log rotation, kill-on-close, and an ownership token. Plus `run_bounded()`. Adopted in order: the Comfy manager, then the SVD worker and RIFE, then the WebUI manager | A Comfy orphaned by a crash is reclaimed as owned; a postprocess timeout test passes | M | B2, B7, B8, E6 |
| P3-4 | A typed transport, and cancellation | `HttpTransport`, `RequestPolicy` and typed errors. Comfy gets `/interrupt`, cancel-aware polling, and a "dispatch outcome unknown" error that is never retried automatically. A single `/options` throttle. The port scan and the dead launcher are deleted | A cancelled Comfy job stops within a bounded time (fake-backend test) | M | E1, B7 |
| P3-5 | Provenance is never lost silently | Metadata failures are logged and mark the artifact `provenance_incomplete`. One hash identity. Listener exceptions are logged. Corrupt rows are surfaced as integrity errors | A test for each path | S-M | B9 |
| P3-6 | Queue discipline | Observers are notified after the lock is released. Every transition uses `expected_status`. A ⚑ CANCELLING state. An event-driven idle wait | Concurrency tests pass | M | B10 |

**Phase 3 exit:** `src` is at least 8k lines smaller, no subprocess runs without a timeout and containment, and there is one composition root.

### Phase 4: architecture for extensibility (weeks 5-10)

| WP | Outcome | Scope | Acceptance | Effort | Refs |
|---|---|---|---|---|---|
| P4-1 | A stage-handler registry | `run_njr` stays the only public entry point and becomes pure orchestration. A StageHandler protocol, with one per-image handler (img2img, adetailer and upscale, plus a refinement hook) and handlers for txt2img, video and train_lora | `run_njr` is under 200 lines, with parity proven by the existing runner tests and the fake-backend SQLite proof | M | C3 |
| P4-2 | A single compile core | `compile_njr(intent)` owns the envelope, all cross-cutting policies, backend validation through the registry, and one config shape. Golden NJR snapshot tests come first. Builders migrate one at a time: PromptPack, generic, reprocess, replay, CLI, training, model comparison, learning. A ⚑ GUI/manual SourceKind | There is one `NormalizedJobRecord(` construction site | L | C2, D1 |
| P4-3 | Learning moves out of the GUI | `compile_variant_njr` in `src/learning`, built on P4-2. The learning controller is split into compiler, rating/review, inbox and curation services. The ratchet is extended to `src/gui/controllers` and to GUI files over 1,500 lines | The learning controller is under 1,000 lines | L | D1, D2 |
| P4-4 | Typed stage settings | Frozen per-stage settings, resolved at compile time. One alias table, used only to load historical snapshots, with a removal condition. Wire names appear only in the adapters | The executor's `.get(` count halves | L | C4 |
| P4-5 ⚑ | Exact-profile plugins; the executor moves into the backend | An `ExactProfilePlugin` protocol with a registry. Klein and Z-Image are wrapped first with no behavior change. Family branches are then removed one call site at a time, and the executor moves to `src/image_backends/webui/` | No family names remain in generic `src/pipeline`; a new family takes 5 files or fewer | L | C1, E2 |
| P4-6 | Declarative video workflows | Each graph is JSON with a content hash and a manifest. Qualification records are kept separate from graph versions. Replay pins the graph hash and the qualification ID | A requalification adds a record instead of a version | M | E3 |
| P4-7 | One GUI pattern | The view_contracts style everywhere, and one BackgroundWorkRunner with a bounded pool. Migrate Photo Optimize saving (debounced), the Review scan and thumbnail decoding (with an LRU cache). Build tabs lazily | A test shows no widget work happens off the Tk thread; startup gets measurably faster | M-L | D5-D9 |

**Phase 4 exit:**
- The executor is under 3k lines and `AppController` under 4k.
- A new model family takes 5 files or fewer.
- Tests detect any §12 violation.

### Phase 5: product value (interleaved with Phases 3-4 from week 3)

| WP | Outcome | Scope | Acceptance | Effort | Refs |
|---|---|---|---|---|---|
| P5-1 | A history browser | A read-only JobRepository query service: paged, filterable by prompt text, model, seed, pack, date and status. A ⚑ index or FTS5 migration (backup first, with a dry run, idempotent). A Tk browser with virtualized thumbnails. "Replay with changes" loads the frozen intent into a Pipeline draft, compiles it normally into a new NJR with parent lineage, and submits it through `submit_njrs`. NJR diff compare. Favorites and tags | Any of the 22,946 jobs can be found in under a second; edit-and-rerun creates lineage | M-L | G1 |
| P5-2 | Learning pays off; grids | An automation-mode selector (⚑ the default mode). Drafts commit on Next and Save-all. "N more ratings needed". A 2-3 axis X/Y/Z sweep through frozen preview and a single `submit_njrs` batch. A labeled contact sheet as a derived output | The first recommendation is applied; a grid comes from one action | S-M plus M | G2, G4 |
| P5-3 | Inpainting and outpainting | A Tk Canvas brush/eraser mask editor. A job-owned mask snapshot with a SHA, following the OpenPose snapshot pattern. Flow: InpaintIntent → compiler → img2img NJR with mask fields. The Forge adapter adds `mask`, `inpainting_fill`, `inpaint_full_res` and `mask_blur`. Outpainting is pad plus mask | One physical acceptance image (owner-authorized) | M-L | G3 |
| P5-4 | Multi-unit ControlNet | Generalize to N typed units using Forge preprocessors: depth, canny, lineart, tile, and IP-Adapter if Forge Neo exposes it. Admission per unit, with SDXL evidence | Each unit type has a fake-backend test; one physical run | M | G3 |
| P5-5 | LoRA/model browser and interop | A grid backed by the AssetRegistry, with previews, trigger words and compatibility badges. Model and LoRA hashes (AutoV2) in `parameters`. A ⚑ optional download-by-URL with hash verification | Civitai auto-links resources; Forge PNG Info round-trips | M | G6 |
| P5-6 | Out-of-box experience and polish | 2-3 starter packs seeded when the pack directory is empty. Presets move to user data. One asset-root resolver, replacing the hard-coded path. A user guide. The typo and window title fixed. Review dialogs replaced by the status banner. ⚑ Hide or label unverified tabs | A fresh-user journey test passes | S-M | G5, D10 |
| P5-7 ⚑ | Video | Promote Wan2.2 TI2V-5B (after P3-3 and P3-4). Retire the disabled LTX specs, AnimateDiff and story-plan. Fix the GFPGAN option. Decide the SVD offline default | One approved workflow appears in the GUI | S-M | G7, E3 |
| P5-8 ⚑ | Editing models | Qwen-Image-Edit and Flux Kontext as exact profiles, after P4-5 | 5 files or fewer per family | M each | G3 |

### Sequencing

| Weeks | Engineering | Product |
|---|---|---|
| 1 | P0-1 to P0-6; P1-1; P1-2; P2-1 | — |
| 2 | P1-3; P1-4; P1-5; P2-3; P2-4; P2-5 | — |
| 3 | P1-6; P2-2 (Image doc); P2-6; P3-1 | P5-2: the apply and draft-commit part |
| 4 | P3-2; P3-3 | P5-1: query service and browser |
| 5 | P3-4; P3-5; P3-6 | P5-1: replay with changes, compare |
| 6-7 | P4-1; P4-2 (golden tests and the first 2 builders) | P5-2 (grids); P5-6 |
| 8-9 | P4-2 (remaining builders); P4-3 | P5-3 (inpainting) |
| 10+ | P4-4; P4-5; P4-6; P4-7 | P5-4; P5-5; P5-7; then P5-8 after P4-5 |

### Metrics dashboard

| Metric | Baseline | End of Phase 2 | End of Phase 4 |
|---|---|---|---|
| Tests that block a merge | 386 (4.0%) | 100% of active tests | 100% |
| `main` protected / CI on push | no / no | yes / yes | yes / yes |
| Windows CI | none | required lane | required lane |
| Files gated by mypy | 10 | 390, with no new errors anywhere | fewer than 500 errors in total |
| Broad `except` blocks | 518 (core path), 681 (GUI) | ratchet; can't increase | −50% |
| Tokens to start a task | about 72k | 15k or fewer | 15k or fewer |
| STATUS.md lines | 1,638 | 150 or fewer | 150 or fewer |
| Prose merge conflicts | 10 of 12 sync merges | 0 | 0 |
| `src` lines | 177.9k | about −8k after P3 | −15k or more |
| `tools` lines | 43.6k | about 12k after the archive | about 12k |
| Executor / `AppController` / `run_njr` lines | 6,782 / 7,414 / 1,042 | — | under 3,000 / under 4,000 / under 200 |
| Files touched by a new model family | 15-25 | — | 5 or fewer |
| Jobs you can browse | 20 of 22,946 | — | all (Phase 5) |
| Applied Learning recommendations | 0 | — | above 0 (measured) |

---

## 8. Decisions you need to make

**Now (Phases 0-1)**
1. Enable branch protection and a ruleset on `main`. Should you have an owner bypass?
2. Delete codex-autofix (recommended), or harden it?
3. Make the census the merge gate? This removes the affected lane.
4. Is numpy a core dependency? Should PyYAML stay?
5. Pick the canonical version number and start tagging. Add a LICENSE file, since `pyproject.toml` says MIT.
6. Should the repo stay public? Tracked files contain personal paths.

**Phase 2**
7. Approve the restructure into STATUS, living docs and a generated map. It changes the AGENTS.md authority chain.
8. Keep or drop the per-PR model/usage and Execution Profile ceremony.
9. Which qualification harnesses are still in use, and do you approve the archive rule?
10. Is DIAG-GPU-130 open or closed?

**Phases 3-4**
11. A single composition root (a material wiring change).
12. Add a CANCELLING state?
13. Add a GUI/manual SourceKind (an NJR schema change)?
14. Move the executor into `image_backends` (changes PR-IMG-100 ownership)?
15. Extend the ratchet to `src/gui` and the pipeline god objects?
16. Retire AnimateDiff, the LTX specs, story-plan/continuity, `src/ai`, `src/cluster` and Character Training, or adapt training to a real trainer?
17. Make SVD default to `local_files_only`? Enforce loopback for user-configured runtimes?

**Phase 5**
18. The history index/FTS migration (backup first).
19. Which automation mode Learning defaults to.
20. Allow network downloads from Civitai or Hugging Face?
21. Hide unverified tabs?
22. Promote Wan2.2 TI2V-5B?
23. The priority order of the P5 items.

---

## 9. Appendix

### 9.1 Verification log (checked directly in this session)

- **GitHub settings.** The repo is public. `main` has no branch protection (404) and no rulesets. Default workflow permissions are write, the token can approve PRs, any action is allowed, and SHA pinning is not required. The fork-PR approval policy is `first_time_contributors`. There are 0 self-hosted runners.
- **The codex-autofix workflow.** Its trigger, permissions, missing author check, fork checkout and nonexistent requirements file; all recent runs were skipped.
- **`ci.yml`.** No push trigger; `continue-on-error` on the affected and census jobs; mypy smoke covers 10 files; the composition of the required gate; the controller ceiling equals the file size (7,414).
- **B2.** The constant job-object name, `CreateJobObjectW` opening an existing job, creation in the constructor (`:148`), and `kill_all` on stop (`:772`, `:819`).
- **B3.** The production construction chain (`main.py:781` → `app_factory.py:61-73` → `app_controller.py:547-573` → `pipeline_controller.py:734-738`); the only `enable_startup_gate` call (`app_controller.py:2489`); `_startup_gate = False` by default; `require_normalized_records` defaults to `False` (`job_service.py:222`, `:407`).
- **B5.** `_extract_state_overrides` has no definition; it is on the state-fallback path (`pipeline_controller.py:462`) inside broad excepts; the `filename_template` keyword.
- **B6.** `_after_fn` is never assigned (`learning_controller.py:4012` is the only reference).
- **G2.** `_automation_mode_var` is never bound to a widget.
- **B4.** The non-atomic `write_text` in `experiment_store.py`.
- **G1.** The `limit or 20` history load.
- **D10.** The "Photo Optomize" and "StableNew V2 (Spine)" titles.
- **A8.** The test that leaks a review sidecar, and the `.gitignore:85` rule that hides it.
- **A1.** Direct non-PR commits on `main`'s first-parent history (`d12e0545`, `9f00e240`, `8caf9462`, and others).
- **F1.** STATUS.md line 148 is stale.
- **F5.** The roadmap and architecture doc dates, and the Open gap rows.
- **F9.** The three version strings.
- **E5.** No LICENSE file.
- **2.** Repository size counts per directory.

### 9.2 Auditor scratch scripts

The audit's analysis scripts (AST audits, dead-code and reachability scans, import graphs, CI-history pulls) were temporary and are not part of this repository. Re-create them as needed when a roadmap package starts with a reproduction step.

### 9.3 Glossary

- **NJR** (NormalizedJobRecord): the immutable, versioned executable job envelope.
- **Census:** the full informational test suite, run as 3 shards.
- **Required gate:** the only blocking CI job today.
- **Affected lane:** the routing-selected subset of tests.
- **Ratchet:** a CI-checked ceiling that may only decrease.
- **Exact profile:** a pinned, qualified model configuration, such as FLUX.2 Klein 4B or Z-Image Turbo.
