# Baseline results: B2 + B3 + B5 (executed 2026-11-05)

Executes [NEXT_SESSION_B2_B3_B5_CONTRACT.md](NEXT_SESSION_B2_B3_B5_CONTRACT.md) (DR-A33). Documentation only; nothing under `src/`, `tests/` or `tools/` was changed. **B4 was not run.** No push, PR, merge, GPU work, backend start, runtime restart or production change.

Convention: **measured** values come from the sealed archives or the probe output named beside them. **Assumptions** are listed separately in section 6. Single runs are never statistical evidence (the harness's own comparator rule).

## 1. Execution record

| Item | Value |
|---|---|
| Research branch / SHA | `research/gui-ux-850-experience-redesign` at `88314856d4b8c90471d724af7998475a0e3a4f0b` (checked first; matched the kickoff text) |
| Code under test | `ed1e989f2149b01d16aef26d5f880326aeb250e0`; `git diff --stat ed1e989f HEAD -- . ':!docs/research'` was **empty** before B2 and again after B3/B5 |
| Tracked tree | `git status --short` empty before B2, after B2, and after B3/B5 |
| Preconditions | Checked before asking: SHA, empty src diff, clean tree, no `run_pr_gate` / census / pytest / `operator_journey` / StableNew process (two VS Code mypy language-server processes were the only Python processes and are not competitors), no StableNew window, 37.3 GiB free on the evidence drive (47 GiB at the end) |
| Owner confirmation of an exclusive desktop | Requested in chat, then given in chat. Recorded at **2026-11-05 18:28:50 -05:00** (23:28:50Z). Availability ended with the run (last desktop activity about 19:59 local) |
| Interpreter | the repository's Python 3.14.9 environment (the `StableNew-main` checkout's `.venv`; the worktree has none), **not** the Qt environment; the worktree's own `src/` and `tools/` were imported (verified by `__file__`) |
| Harness | `python -m tools.operator_journey`, windows driver, `--mode simulated`, loopback fakes only |
| Display | one monitor, 2560x1440 at 100% (96 dpi), from `evidence.json` of every archive |
| Evidence root | `~\StableNewAcceptance\` (outside every checkout). Probe scripts and raw probe output are kept in `~\StableNewAcceptance\b2_b3_b5_probes_20261105\` (not sealed archives; hashes of the files at copy time are not recorded here) |
| Stop conditions fired | **None.** No exit code 4, no guard violation (`isolation_violations` empty in all 27 B2 journey records and in every B5 and B3 probe run that reported it), no harness-reported obscured control, no leaked probe process (checked after B3/B5) |

Defects in my own scratch probes, disclosed so nothing is hidden: the first B5 smoke run aborted on a probe bug (driver used before the app booted); two N=0 control runs each waited out a 170 s timeout because an empty history can never "populate" (I stopped the loop, fixed the probe, discarded those runs, and reran all N=0 repeats); the first Review probe used the wrong tab title (`Review` instead of `Review - Adv`), and the first Job History and Learning probes ran before I added the neutral-page control, so both were rerun with it (their classification did not change). None of these touched product code or data, and none is counted in the tables below.

## 2. B2: sealed baseline of the existing journeys on `main`

Six commands (`--journey all` and `--journey advanced` at `normal`, `minimum` and `maximized`), each with `--archive`. Every archive was verified with `--suite golden-paths --verify-archive` and returned **OK**. The first 16 hex characters of the `MANIFEST.json` SHA-256 equal the hash recorded in each archive's `COMPLETE` marker. Archives record `repository_sha` `88314856` (the research HEAD), which differs from `ed1e989f` by documentation only.

| Layout | Archive | Manifest SHA-256 (first 16) | Suite verdict | `--verify-archive` |
|---|---|---|---|---|
| normal, all | `20261105T233252Z_simulated_88314856_normal_acceptance_7bb5ec` | `dceaca5081a9b2c8` | PASS | OK |
| normal, advanced | `20261105T234539Z_simulated_88314856_normal_acceptance_8a13de` | `de4f031c264dc210` | FAIL | OK |
| minimum, all | `20261105T235032Z_simulated_88314856_minimum_acceptance_4585a1` | `4786fd6ad5e39055` | PASS | OK |
| minimum, advanced | `20261106T000359Z_simulated_88314856_minimum_acceptance_29d34c` | `b8aa426834fec857` | FAIL | OK |
| maximized, all | `20261106T000755Z_simulated_88314856_maximized_acceptance_688b2d` | `7419ea77686d0758` | PASS | OK |
| maximized, advanced | `20261106T002052Z_simulated_88314856_maximized_acceptance_3c760c` | `fc539a9fcf70fac6` | FAIL | OK |

Shorthand for later evidence rows: **A-B2n / A-B2m / A-B2x** = the three `all` archives; **A-B2n+ / A-B2m+ / A-B2x+** = the three `advanced` archives (suffixes `7bb5ec`, `4585a1`, `688b2d`; `8a13de`, `29d34c`, `3c760c`).

### 2.1 Per journey and layout

Metrics are computed by the harness's own `journey_metrics` (the comparator's function) over each archive's `evidence.json`. `select_tab` is the contract's count (rows with `"action": "select_tab"` in `actions.jsonl`). It is small because most navigation happens through task-bar clicks, so I also give **nav clicks** (rows labelled `nav ...`) as a supplementary figure; the contract did not ask for it. Duration is the journey's recorded duration.

| Layout | Journey | Verdict | Reach. | Actions | Extra | Lost | Retries | Forced scroll/resize | select_tab | nav clicks | Duration s |
|---|---|---|---|---|---|---|---|---|---|---|---|
| normal | IMG-01 | PASS | DIRECT | 50 | 4 | 0 | 0 | 4 | 1 | 2 | 79.0 |
| normal | LRN-01 | PASS | DIRECT | 98 | 5 | 0 | 0 | 5 | 2 | 5 | 97.0 |
| normal | VID-01 | PASS | DIRECT | 33 | 1 | 0 | 0 | 1 | 0 | 4 | 44.0 |
| normal | IMG-02 | PASS | DIRECT | 102 | 7 | 0 | 0 | 7 | 1 | 6 | 118.0 |
| normal | IMG-03 | FAIL | DIRECT | 95 | 5 | 0 | 0 | 5 | 1 | 6 | 78.0 |
| normal | LRN-02 | PASS | WITH_WORKAROUNDS | 141 | 13 | 0 | 0 | 12 | 2 | 6 | 132.0 |
| normal | OPS-01 | FAIL | DIRECT | 135 | 10 | 0 | 0 | 10 | 1 | 2 | 246.0 |
| normal | VID-02 | HOLD | DIRECT | 31 | 2 | 0 | 0 | 2 | 1 | 2 | 71.0 |
| normal | VID-03 | PASS | WITH_WORKAROUNDS | 111 | 10 | 0 | 0 | 9 | 2 | 4 | 117.0 |
| minimum | IMG-01 | PASS | DIRECT | 52 | 6 | 0 | 0 | 6 | 1 | 2 | 84.0 |
| minimum | LRN-01 | PASS | DIRECT | 102 | 9 | 0 | 0 | 9 | 2 | 5 | 105.0 |
| minimum | VID-01 | PASS | DIRECT | 36 | 4 | 0 | 0 | 4 | 0 | 4 | 96.0 |
| minimum | IMG-02 | PASS | DIRECT | 104 | 9 | 0 | 0 | 9 | 1 | 6 | 126.0 |
| minimum | IMG-03 | FAIL | DIRECT | 98 | 8 | 0 | 0 | 8 | 1 | 6 | 83.0 |
| minimum | LRN-02 | PASS | WITH_WORKAROUNDS | 146 | 18 | 0 | 0 | 17 | 2 | 6 | 145.0 |
| minimum | OPS-01 | FAIL | DIRECT | 140 | 15 | 0 | 0 | 15 | 1 | 2 | 253.0 |
| minimum | VID-02 | HOLD | DIRECT | 33 | 4 | 0 | 0 | 4 | 1 | 2 | 74.0 |
| minimum | VID-03 | PASS | DIRECT | 116 | 15 | 0 | 0 | 15 | 2 | 4 | 123.0 |
| maximized | IMG-01 | PASS | WITH_WORKAROUNDS | 50 | 4 | 0 | 0 | 4 | 1 | 2 | 83.0 |
| maximized | LRN-01 | PASS | WITH_WORKAROUNDS | 98 | 5 | 0 | 0 | 5 | 2 | 5 | 101.0 |
| maximized | VID-01 | PASS | WITH_WORKAROUNDS | 34 | 2 | 0 | 0 | 2 | 0 | 4 | 45.0 |
| maximized | IMG-02 | PASS | WITH_WORKAROUNDS | 100 | 5 | 0 | 0 | 5 | 1 | 6 | 121.0 |
| maximized | IMG-03 | FAIL | WITH_WORKAROUNDS | 95 | 5 | 0 | 0 | 5 | 1 | 6 | 82.0 |
| maximized | LRN-02 | PASS | WITH_WORKAROUNDS | 136 | 8 | 0 | 0 | 7 | 2 | 6 | 132.0 |
| maximized | OPS-01 | FAIL | WITH_WORKAROUNDS | 130 | 5 | 0 | 0 | 5 | 1 | 2 | 246.0 |
| maximized | VID-02 | HOLD | WITH_WORKAROUNDS | 33 | 4 | 0 | 0 | 4 | 1 | 2 | 73.0 |
| maximized | VID-03 | PASS | WITH_WORKAROUNDS | 111 | 10 | 0 | 0 | 10 | 2 | 4 | 119.0 |

Display for every row: 2560x1440 at 100% scaling, 96 dpi. Lost clicks and click retries are 0 in all 27 rows. `maximized` is itself recorded as a workaround (GP830-F1, forced maximize), which is why those rows read WITH_WORKAROUNDS.

### 2.2 Against the expectation in the contract

| Expectation (from the registry) | Observed | Status |
|---|---|---|
| GP832-F1: OPS-01 generic failure message | OPS-01 FAIL at all three layouts; the failed check is `failure_cause_visible_to_operator` ("No images were generated successfully"; History shows only generic labels) | **reproduces** |
| GP832-F2: running job while the banner reports jobs held | Recorded as an observation, not a failing check: in `ops_outcomes.unreachable_before_dispatch` the job status was `running` while down, the queue line read "Queue: Running job...", and the banner read "WebUI jobs are held in the queue ... 0 WebUI job(s) held" | **reproduces** (as observation, consistent with the registry) |
| GP832-F3: IMG-03 `parent_job_id` null | IMG-03 FAIL at all three layouts; failed checks `parent_job_recorded` and `compare_offered_for_the_edit`; the frozen source carried `parent_job_id: None` | **reproduces** |
| GP832-F4: VID-03 blank form-level motion prompt refusal | **Not reproduced and not exercised.** VID-03 PASS at all three layouts. The journey on this code types a non-blank form-level motion prompt (`vid03.py` line 89), so the blank-form condition never occurs; no check or observation names F4 | **deviation: new observation.** The harness at `ed1e989f` cannot show F4; the register's EV-10 "UNREPAIRED" status rests on the findings registry and a source check, not on this run |
| VID-02 HOLD at conversion (Blender absent) | HOLD at all three layouts; the hold reason says Blender is not installed or registered and that lane B used a labelled pre-rendered clip | **reproduces** |
| IMG-01, VID-01, LRN-01 and the rest pass | IMG-01, VID-01, LRN-01, IMG-02, LRN-02 PASS at all layouts | **matches** |

New observations (recorded, not repaired): LRN-02 carries a `waited_for_hidden_or_disabled_control` workaround (count 1) at every layout; VID-03 carries a `mouse_release_followed_moving_control` workaround (GP830-F2) at `normal` only. The workaround label `waited_for_hidden_or_disabled_control` has no finding id attached in the archive.

### 2.3 Comparison with the PR-831 archives

`--compare` of each `all` archive against the register's A-831 archive of the same layout (`a18c7403`, an ancestor of `origin/main`), written to `~\StableNewAcceptance\comparisons\b2_vs_a831_{normal,minimum,maximized}\`. The comparator accepted all pairs. It marked media-byte differences and "shutdown latency not recorded on one side" INCONCLUSIVE; I keep those verdicts. Environment differences it listed: repository SHA and harness-source hash.

| Layout | Improved | Unchanged | Degraded | Inconclusive | Notes |
|---|---|---|---|---|---|
| normal | 0 | 48 | 0 | 6 | all inconclusive items are media bytes or shutdown latency |
| minimum | 1 | 45 | 2 | 6 | IMG-01 duration 99 s to 84 s improved; **VID-01 duration 48 s to 96 s and waiting 3.32 s to 28.97 s degraded** (exit code 1) |
| maximized | 0 | 48 | 0 | 6 | as normal |

The VID-01 minimum figures are one run each and unrepeated; VID-01 took 44 s and 45 s in the other two layouts of this session, so the 96 s run is an outlier of unknown cause. It is not evidence of a regression.

## 3. B3: wheel-capture probe on `main`

Scratch script `b3_probe.py` (outside the repository; kept in the probe folder) reusing the harness's Windows driver (`reach`, `_center`, `_scroll_container`, `Win32.wheel`), the disposable workspace and, for Review and Learning, the unmodified journey bodies (IMG-03 and LRN-01), probing at the journey's first `shutdown_app()` while its data was on screen. Layout `minimum`, one run per target. For each target: pointer over the widget, one notch up to reach the inner top, then single wheel notches down until the inner offset stopped moving twice, then five more notches at the limit, recording the page scroll box's `yview` and the inner widget's `yview`/`xview`. A **control** then wheels over a neutral part of the page twice to show that the page can move at all.

Classification is my own definition of the contract's three labels: **inner only** = the inner widget moves and the page does not move before its limit; **chains to page at limit** = the page moves once the inner widget is at its limit; **captured at limit** = the page does not move at the limit although the control shows it can.

| Target | Data reached | Viewport | Inner offset (start to limit) | Page moved before limit | Page moved at limit (5 notches) | Control (page can move) | Result |
|---|---|---|---|---|---|---|---|
| Job History tree (Pipeline) | 20 visible rows of 200 seeded (history is bounded at 20, see B5) | 327x125 px | 0.0-0.3 to 0.7-1.0; limit reached within 8 wheel events (including the initial upward one) | no | **no** | yes, 0.7105 to 0.7321 (page had about 0.02 of headroom) | **captured at limit** |
| Motion Library tree (Video) | 14 clips imported through the panel's own Import control | 1202x253 px | 0.0-0.357 to 0.643-1.0; limit reached within 6 wheel events (including the initial upward one) | no | **no** | yes, 0.3181 to 0.3606 | **captured at limit** |
| Review preview canvas | one image handed off from History by IMG-03 | 828x620 px | none: `yview` and `xview` stayed 0-1 | no | **no** | yes, 0.1935 to 0.2422 | wheel over the canvas moves **neither the canvas nor the page**; the page can move, so the wheel is consumed without effect. Whether the canvas zooms on the wheel was **not measured** |
| Learning Images list | **1** image (LRN-01's own fixture) | 596x76 px | none: the list does not overflow | no | **no** | yes, 0.0623 to 0.1869 | wheel over a list that does not overflow still does not move the page; **inner-overflow behaviour (inner only versus chains versus captured) is unavailable** because the existing fixture produces one image, not more than the four visible rows |

What this does and does not support: on `main`, the pointer over the Job History tree or the Motion Library tree at the minimum window keeps the wheel at the inner widget's limit and the page does not follow, which is the GP833-O2 behaviour (EV-16) now measured on `main`. For the Review canvas and the Learning list the wheel over the widget does not reach the page either. The probe has one run per target, one display, and the page headroom for the Job History target was small (about 0.02), so the five-notch test at the limit there is a weak negative on its own; the control and the Motion Library result are stronger.

No change to `src/`, `tests/` or `tools/` was needed. Seeding used the repository's public `JobRepository.import_jobs` for History and the panel's own Import control for the Motion Library; the Review and Learning data came from the unmodified journeys.

## 4. B5: large-history load

Disposable data only. A scratch script built a SQLite file with `JobRepository.import_jobs` (public API, 1,000 jobs per atomic transaction, status `completed`, synthetic prompts `synthetic prompt N`, no paths or images), copied it into the harness workspace's `workspace_paths.job_repository()` location (asserted to be under the workspace root), booted the real application there with the windows driver (`normal` layout), selected the Pipeline tab, and polled the Job History tree until it held rows. Each repeat is a **fresh process**. The real queue/history database was not opened (the harness's guards reported no change).

| N (rows in DB) | DB file size | Build time | Time to populated, s (3 repeats) | Mean s | Working set at populated, MiB (3 repeats) | Peak working set, MiB |
|---|---|---|---|---|---|---|
| 0 (control, extra) | 0.04 MB | 0 | 25.25, 24.52, 25.14 | 24.97 | 825.9, 826.3, 826.8 | 826.3 to 826.9 |
| 500 | 2.2 MB | 0.5 s | 24.67, 24.68, 28.92 | 26.09 | 827.6, 828.5, 828.4 | 828.4 to 828.6 |
| 5,000 | 21.9 MB | 5.3 s | 25.40, 24.98, 24.75 | 25.04 | 827.3, 827.7, 827.4 | 828.1 to 828.4 |
| 50,000 | 219.2 MB | 143.7 s | 24.66, 25.76, 25.53 | 25.32 | 827.9, 828.6, 827.9 | 832.6 to 833.3 |

N = 50,000 was attempted because the 5,000-row load (about 25 s) did not exceed the 60 s skip threshold. The N = 0 control is an addition to the contract's list, included so the fixed application start cost can be separated.

Findings:

- **The measured time is dominated by application start.** The "time to populated" includes the harness bringing the window forward and the app booting (about 24.5 s at N = 0) and exceeds it by about 0.1 s at every N. Differences between N values (24.5 to 28.9 s) are within the spread of the repeats at a single N, so this run shows **no N-dependent load cost in the range 0 to 50,000 rows**, and cannot resolve one smaller than a few seconds.
- **The panel is bounded.** At every N the tree, the panel's entry map and `app_state.history_items` each held exactly **20** rows, so the user-visible list never grows with history. The panel's own refresh metric (`_populate_history`) recorded about 0.76 ms in the one probe that kept it (N = 500, smoke run, not counted above).
- **Working set** rose from about 826 MiB (N = 0) to about 828 MiB (500 to 50,000) at populated, and peak working set was about 6 MiB higher at 50,000 than at the control. The process total is the whole application, not only the history.
- **Not measured:** the cost of Browse All / History filters over 50,000 rows, scrolling, Learning or Review reading the same history, and cold disk cache (the files were just written). Rows were created through the import API, so their `legacy_imports` bookkeeping rows exist; rows admitted through the live queue path were not generated.

## 5. Unavailable or limited measurements

| Item | Status | Reason |
|---|---|---|
| GP832-F4 reproduction | not exercised | VID-03 on this harness supplies a form-level prompt (section 2.2) |
| Review canvas wheel zoom | not measured | the probe read scroll offsets only |
| Learning Images list overflow behaviour | **unavailable** | existing fixtures produce a single image; producing more would need a change outside the existing seams |
| N-dependent history load time below a few seconds | not resolvable | boot time dominates and varies by up to about 4 s across repeats |
| Real DPI, multi-monitor, other tabs' wheel behaviour | not run | outside this contract; B4 not approved |
| Time to populated excluding app boot | not separated | the app does not expose a per-phase timer; the control row is the proxy |

## 6. Assumptions (not measured)

- That nobody touched the mouse or keyboard during the runs: the harness does not detect human input, so this rests on the owner's confirmation and on the absence of harness-reported obscured controls and failed clicks (lost clicks and retries were 0 throughout).
- That `88314856` behaves as `ed1e989f` for these purposes: asserted by the empty non-docs diff, not by running `ed1e989f` itself.
- That one display at 100% is representative: it is not tested otherwise (EV-29).
- That the wheel results on a single fixture row set (20 History rows, 14 clips) transfer to real data volumes.

## 7. Acceptance checklist (from the contract)

- [x] SHA matched; `src/` identical to `ed1e989f`; tracked tree clean before and after
- [x] Owner confirmation of an exclusive desktop recorded with the time (18:28:50 -05:00)
- [x] B2 archives sealed and verified for three layouts (no stops)
- [x] B3 table (two targets with full classification, two limited, reasons named)
- [x] B5 table for N = 0 (extra), 500, 5,000 and 50,000
- [x] Unavailable measurements named; assumptions separated from measurements
- [x] No real data touched (guards clean); no backend, runtime or GPU activity; no display setting changed
- [x] Docs-only local commit; branch/SHA and `Model / usage` line reported in the session closeout
