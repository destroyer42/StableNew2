# Unobtrusive local test runs (design)

Date: 2026-11-16. Status: approved by Rob in conversation (approach and design). Execution class: Standard
(test/CI tooling only; no application runtime, architecture invariant or product behavior changes).

## Intent

Rob runs a live StableNew from `C:\Users\rob\projects\StableNew-main` while agents run local tests. Today those
runs open windows over his work, take focus, and make the live app's menus stutter. Local test runs must be
invisible on his desktop and must not degrade the live app. Slower tests are an accepted cost.

## Evidence (main at 19dcb479)

- About 80 files under `tests/gui_v2`, `tests/tools` and `tests/helpers` call `deiconify`, `focus_force`, `lift`
  or `-topmost` on real Tk windows; they need a viewable window, so the windows are really shown.
- `tests/tools/test_golden_path_journeys.py` starts `python -m tools.operator_journey --suite golden-paths`,
  a full app window in a child process.
- `tools/ci/run_pr_gate.py`, `tools/ci/run_sharded_census.py`, `tools/ci/census_shards.py` and
  `tests/conftest.py` set no priority, affinity or window isolation. Every process runs at normal priority on
  all 32 logical CPUs (i9-13900K: 8 P-cores / 16 threads, 16 E-cores).
- Agents mostly run `python -m pytest ...` directly, so a gate-only change would miss most runs.

## Goals

1. No test-created window (Tk, dialog, console, journey app) appears on, or takes focus from, the interactive
   desktop during any local Windows pytest run.
2. The whole test process tree (including grandchildren) runs below normal priority and off the performance
   cores on hybrid CPUs.
3. This applies to every local entry point: bare `pytest`, `python -m pytest`, the PR gate, the collection gate,
   required smoke, the sharded census.
4. Test results are unchanged: same pass/fail/skip set as a visible run.

## Non-goals and anti-goals

- No change under `src/`. No test is weakened, skipped or rewritten to avoid showing a window.
- Hosted CI (`CI` set) and non-Windows behavior are unchanged.
- The opt-in physical-input journeys (`tools/operator_journey/desktop.py`, real `SendInput`) stay on the real
  desktop; they are already refused in headless modes.
- Never stop, signal, re-prioritize or otherwise touch the owner's running app, Forge/Comfy, or another
  session's test run.
- Failure would be: tests that pass visibly now fail or silently skip when hidden; or a hung hidden run that
  nobody can see or kill.

## Approaches

1. **Hidden Windows desktop + background job (chosen).** Start the test process on a private desktop
   (`CreateDesktopW`, `STARTUPINFO.lpDesktop`) inside a job object. Windows are real and viewable there, so
   layout/focus tests keep working, but nothing can reach the interactive desktop. Children inherit the desktop
   and the job.
2. **Withdraw/minimize or move windows off-screen.** Rejected: breaks the tests that need a viewable window,
   needs edits across ~80 files, and misses child processes.
3. **Lower priority only.** Rejected: fixes none of the flicker or focus theft.

## Design

**`tools/ci/quiet_run.py`** (stdlib + `ctypes`, Windows; elsewhere it runs the command unchanged). Runs a
command and returns its exit code, relaying stdin/stdout/stderr:

- Private desktop `StableNewTests` in the current window station; child started with `lpDesktop` set,
  `CREATE_SUSPENDED`, assigned to a job object, then resumed.
- Job limits: `BELOW_NORMAL_PRIORITY_CLASS`; affinity to the lowest-efficiency-class cores reported by
  `GetLogicalProcessorInformationEx` when the CPU is hybrid; `KILL_ON_JOB_CLOSE` so a cancelled run leaves no
  hidden orphans.
- The Win32 surface is one injectable class, as `tools/operator_journey/desktop.py` does, so the logic is
  unit-testable without a desktop.

**Automatic relaunch.** A local Windows pytest session that is not already inside the quiet environment
re-runs itself through `quiet_run` with the same arguments and exits with the child's code. It must happen
before Tk is imported or collection starts. A marker environment variable prevents recursion and is inherited by
nested pytest runs. Skipped when `CI` is set, off Windows, or when `STABLENEW_TESTS_VISIBLE=1`.

**Gate and census.** `run_pr_gate.py` and `run_sharded_census.py` launch their steps/workers through
`quiet_run`, so non-pytest steps (ruff, mypy, git worktree setup) are also low priority.

**Calls made by the designer (not owner decisions):**

- If the hidden desktop cannot be created, print one warning line and run visibly but still low priority
  (fail open on visibility, never on test execution).
- Non-hybrid CPU or more than 64 logical CPUs: priority only, no affinity.
- Below-normal priority rather than idle or background mode (background mode clamps memory and can stall).

## Left to the builder

- The exact relaunch hook (root `conftest.py`, `tests/conftest.py` import time, or an early plugin) and how to
  tell a real CLI run from an in-process `pytest.main()` call.
- Whether journey screenshot evidence still captures on a non-input desktop; if not, that suite keeps the
  visible path and the reason is recorded.
- Where the testing guidance for this lives (testing authority doc and the `docs/CODEX_MAP.md` row).

## Verification

1. Spike first: Tk `deiconify`, `winfo_viewable`, `focus_force`/`focus_get`, `event_generate` and geometry on
   the hidden desktop. If focus does not work there, stop and report before building further.
2. `tests/gui_v2` and `tests/tools`: identical outcome sets hidden vs visible (`STABLENEW_TESTS_VISIBLE=1`).
3. During a hidden run, `EnumWindows` on the interactive desktop shows no window owned by the test tree, and
   every test process reports below-normal priority and the expected affinity.
4. Responsiveness: a standalone probe Tk loop at normal priority (not the owner's app) records event-loop
   latency during a 2-worker census, before and after. If stutter persists, look next at shared files and disk
   I/O between the test tree and the live checkout, and report rather than widen scope.
5. Unit tests for `quiet_run` with a fake Win32; `python tools/ci/run_pr_gate.py`; `tests/tools` (ratchets).
