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

## Outcome (builder findings, 2026-11-17)

Measured on the owner's i9-13900K (Windows 11, 32 logical CPUs) at the implementation branch, with other agent
sessions also using the machine.

- **Spike passed.** On the private desktop Tk reports `winfo_viewable() == 1`, the requested geometry, `focus_get`
  following `focus_force` (root, entry and a `Toplevel`), and `event_generate` key and click events firing, all
  identical to the interactive desktop. `GetForegroundWindow` returns no window there.
- **Screen capture does not work on the private desktop** (`ImageGrab.grab` raises `screen grab failed`). Only the
  opt-in physical lane (`STABLENEW_DESKTOP_LANE=1`, `WindowsDesktopDriver.screenshot`) captures screenshots, and it
  already stays on the real desktop; the simulated golden-path suite run by pytest takes none. So that lane keeps the
  visible path and nothing else needed to change.
- **Relaunch point.** pytest starts file-descriptor capture before importing conftests, so at conftest import time
  the standard handles point at pytest's capture files. The relaunch therefore runs from `pytest_configure`
  (`tryfirst`), where the real handles are back, still before collection and before any Tk interpreter exists
  (`tkinter` itself may already be imported by `tests/conftest.py`; importing it creates no window).
- **Efficiency-core affinity is off by default (deviation from Goal 2, accepted by the owner on 2026-11-17:
  "Accept opt-in").** With below-normal priority *and* efficiency-core affinity, `tests/gui_v2` + `tests/tools` took 95 min instead of 49 min visible, and
  two layout tests in `tests/gui_v2/test_focused_operator_workspace_110.py` (fixed 160 ms main-loop settle) failed
  that pass visibly. Controlled reruns of that file, 3 runs each: hidden desktop at normal priority on all cores 27/27;
  below-normal on all cores 27/27; normal priority on efficiency cores 27/27; below-normal on efficiency cores
  (hidden or visible) 1 failure every run. The hidden desktop is not the cause; the combination is. Goal 4 and the
  stated failure condition win, so the default is below-normal priority on all cores and
  `STABLENEW_TESTS_CORES=efficiency` restores the affinity.
- **Outcome sets.** Hidden with the default: 6382 passed, 7 failed, 13 skipped (48 min). Visible
  (`STABLENEW_TESTS_VISIBLE=1`): 6377 passed, 7 failed, 13 skipped (49 min). No test changed status. The pass-count
  difference is the new `tests/tools/test_quiet_run.py` cases added between the runs. The same 7 tests fail both ways
  for environmental reasons: worktree config isolation in five golden-path journeys, a "duplicate StableNew/WebUI
  process" admission refusal with the owner's app running, and `test_gui_seam_743` in full-suite order.
  One `ai115b` parametrized test builds its IDs from an unordered set, so its IDs differ between runs.
- **Isolation.** During hidden runs (5,640 and 2,861 one-second samples, 503 and 384 processes: python, git, ruff,
  ffmpeg, ffprobe, powershell, cmd, conhost, nvidia-smi, typeperf) `EnumWindows` on the interactive desktop found no
  window owned by the test tree, and every process ran below normal priority (CPUs 16-31 with efficiency
  affinity, all 32 by default), except the relaunching pytest parent, which only waits.
- **Responsiveness.** A withdrawn Tk probe at normal priority on the interactive desktop measured `after(10)`
  lateness: idle p50 5.5 / p99 6.6 / max 14.2 ms; 2-worker census visible 5.5 / 11.5 / 15.7; quiet with efficiency
  cores 5.5 / 6.8 / 28.1; quiet on all cores 5.4 / 12.7 / 21.2; idle again 5.5 / 11.4 / 15.4; no callback over 50 ms
  in any case. A 2-worker census does not saturate this CPU, so scheduling latency is not where the stutter comes
  from. The likely cause is test windows taking focus and appearing over the live app, which the private desktop
  removes. A withdrawn probe cannot measure that; shared files and disk I/O were not measured.
