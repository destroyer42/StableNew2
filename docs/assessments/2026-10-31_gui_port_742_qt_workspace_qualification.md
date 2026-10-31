# GUI-PORT-742 — representative Qt workspace, DPI and operator-benefit qualification

Evidence collected **2026-10-31** on one Windows 11 host. Focused assessment following
[GUI-PORT-740](2026-10-28_gui_port_740_qt_compatibility.md).

| Verdict | Result |
|---|---|
| **A. Qualification validity** | **PASS** for the cells that could be run; the cells listed under *UNQUALIFIED* are explicitly not covered |
| **B. Migration recommendation** | **NO-GO for a production Qt migration on current evidence**; Qt work stops here. One bounded, cheaper Tk experiment is proposed instead (see *Next step*) |

Neither verdict authorizes anything. Production migration, distribution and licensing remain unapproved.

## What was built and what it is not

An opt-in harness under [`tools/qualification/gui_port_742/`](../../tools/qualification/gui_port_742/README.md) renders one
read-only Pipeline / Job History inspection workspace in an isolated Tk child and an isolated PySide6 child. Both use the
same 500 queue + 500 history records on the real `JobHistoryEntry` / `UnifiedJobSummary` contracts, the real
`task_navigation_contract` and `history_browser_model`, the real `AppStateV2` + `AppStateProjectionSink` fed from a worker
thread, the shared design values from GUI-SEAM-741 and the same scripted 12-step journey and timing code.
It is **not** an application host: no production app, launcher, job database, backend, queue or GPU is touched, and the
canonical execution path is unchanged. Nothing under `src/` changed.

## Execution identity

| Item | Observed |
|---|---|
| Source | branch `gui/port-742-qt-workspace-qualification`, commit `a15522e0`, worktree clean at run time |
| Run window | 2026-10-31 09:18:51–09:21:21 (-04:00), parent exit 0, validity `PASS`, no failures |
| Python | CPython 3.14.9 x64, standard GIL, GIL enabled (the accepted 740 proof environment, outside every checkout) |
| Toolkits | PySide6 / Qt 6.12.0 (windows platform plugin, Fusion style); Tk 9.0.4 |
| Display | one 2560×1440 monitor (ASUS VG32VQ1B), 96 DPI, DPR 1.0 (100%), per-monitor-v2 awareness in both children |
| Fixture digest | `3f7d33fb2ac861f3aeee3212c7fc42691642798cf50c3f73541963d441f3c433`; identical in every child |
| Source fingerprints | a 28-file SHA-256 map of every shared input is in [`metrics.json`](evidence/gui_port_742/metrics.json) (`identity.fingerprint`) |
| Run shape | 10 matrix children, 2 accessibility children, 18 benchmark children (1 warm-up + 5 samples for each of three conditions) |
| Evidence | [`metrics.json`](evidence/gui_port_742/metrics.json) (278 KB) and four 1366×768 screenshots |

The operator's StableNew application and its managed Forge were running on the host the whole time and were not touched.
Host CPU sampled before each benchmark child was 0.5–8.7%. It is a confound that is recorded, not corrected.

## Matrix (actual vs SIMULATED)

| Requested DPI | Viewport | Tk | Qt | Cross-toolkit parity |
|---|---|---|---|---|
| ACTUAL 100% (window DPI 96 = monitor DPI 96) | 1366×768, 1920×1080, maximized | 12/12 steps | 12/12 steps | identical outcomes |
| SIMULATED 150% (`tk scaling` ×1.5 / `QT_SCALE_FACTOR=1.5`; window DPI stays 96) | 1366×768 logical, maximized | 12/12 steps | 12/12 steps | identical outcomes |

Per cell, in both toolkits: no control clipped or off-screen, tab order matches the expected order, a focus indicator
changes screen pixels (measured on the real desktop with the window foreground), Up/Down moves the selection and scrolls it
into view, the invalid-filter notice appears and clears, the worker stream ends on its final update and nothing is
delivered after close. "Simulated" is a per-process scale factor. It is never reported as, or compared to, a real 150%
monitor. Parity compares the semantic outcome of each step, not timings.

## Quantitative comparison (median of 5 samples, [min–max], after 1 warm-up each)

Three conditions isolate the dispatcher-policy confound: **tk-native**, **qt-native** (the accepted 740 queued-signal
dispatcher) and **qt-matched** (Qt running the production Tk dispatcher's scheduling policy: 15 ms pump, 32 callbacks or 8 ms
per pump). Samples are n=5, so p95 is not reported for them (only for n≥20).

| Metric | Tk | Qt native | Qt matched |
|---|---|---|---|
| Startup to verified-visible, ms | 838 [794–842] | 928 [907–958] | 933 [917–952] |
| Window construct, ms | 8.8 | 72.2 | 75.9 |
| Show to first paint, ms | 42.7 | 91.5 | 92.8 |
| Second full workspace painted, ms | 61.0 | 34.5 | 34.2 |
| Idle working set, MiB | 87.2 | 121.6 | 121.0 |
| Peak process-tree working set, MiB | 103.3 | 182.3 | 182.9 |
| Filter applied to visible, ms | 8.9 | 6.9 | 7.0 |
| Selection to visible, ms | 4.9 | 4.0 | 4.1 |
| Worker refresh to visible (selection kept), ms | 105 | 84 | 96 |
| History table render, ms | 3.2 | 1.9 | 1.9 |
| UI heartbeat gap, idle, median, ms (5 ms timer) | 5.25 | 5.00 | 5.00 |
| UI heartbeat gap, 1.5 s worker load, median / p95-of-gaps / max, ms | 6.87 / 11.0 / 16.8 | 5.01 / 10.4 / 13.6 | 5.01 / 10.3 / 13.4 |
| 2,000-callback burst, dispatch latency median, ms | **518** | **2.1** | **514** |
| 2,000-callback burst, total, ms | 1036 | 9.7 | 1022 |
| Close to process exit, ms | 155 | 190 | 184 |

The loaded-heartbeat "p95" is a p95 over the gaps within one run (several hundred gaps), not over samples.
Tk's worst loaded gap was 34.6 ms in one of five runs (sample 4, host CPU 1.6%, so not obviously host load); the other four were 15.5–17.9 ms.

## Accessibility and discoverability evidence

| Observation | Tk | Qt |
|---|---|---|
| In-process accessibility API | none per widget | `QAccessible`: 13 of 13 interactive widgets named, with roles (Tree, EditableText, ComboBox, Button, ...) |
| External UI Automation tree of the proof window (read-only client attached to the child's own PID) | 31 elements, all `Pane`, 0 named, 0 focusable | 110 elements, 104 named, 84 focusable; Button, ComboBox, Edit, Table, DataItem, Header, Tree, TreeItem |
| Clipped history cell shows its full text on hover | no (not built; the details pane shows it) | yes (native tooltip equals the full text) |
| Full text of a clipped cell reachable | yes, via the details pane | yes, via tooltip and details pane |

This is a UI Automation inspection. **It is not a screen-reader test**: Narrator, NVDA and JAWS were not run.

## UNQUALIFIED (not tested, not inferred)

- Actual 150% or any other real scale factor (no such monitor; system scaling was not changed).
- Fractional or mixed-DPI, multi-monitor and monitor-change behavior (one 100% monitor).
- Simulated 150% at 1920×1080 (needs 2880×1620 physical pixels on a 2560×1440 panel).
- Screen-reader behavior (Narrator/NVDA/JAWS).
- Anything about the real application's other workspaces, persisted UI state, application shutdown, or real data volumes.

## Appraisal of the counterhypotheses

**H1, "Qt's responsiveness advantage is primarily dispatcher policy": CONFIRMED.** For 2,000 queued callbacks, Tk delivered
the median callback after 518 ms and Qt-native after 2.1 ms (a 242× gap, 515.9 ms). Running Qt under the Tk dispatcher's policy gives 514 ms,
so **99.2%** of that gap is scheduling policy and the residual is about 4 ms (Qt-matched is within 1.008× of Tk). Callback work
itself is microseconds in both. The converse is not demonstrated: no run executed Tk with Qt's larger budget, so how much of this
a Tk dispatcher change would recover is plausible but unmeasured. Render and layout costs do differ (history table
render 3.2 ms vs 1.9 ms), but at a scale no operator can perceive. Under sustained worker load Tk's heartbeat gaps were
longer (median 6.9 vs 5.0 ms; p95 11.0 vs 10.4; max 16.8 vs 13.6): measurable, within one 60 Hz frame at the median, and
small compared with anything the operator would notice.

**H2, "startup and memory costs outweigh the practical UX gains": SUPPORTED.** Qt costs about +90 ms startup, +34 MiB idle and
+79 MiB peak working set in this small workspace, and about +35 ms of close time. Qt is faster at filtering (−2 ms),
selection (−1 ms) and refresh (−21 ms) and at building a second window. The operator-visible gain is a few milliseconds on
interactions that already finish in well under 110 ms. No operator budget was invented. The installed PySide6 metapackage
is 650 MiB on disk (WebEngine and PDF were installed as dependencies but never imported); the size of a minimal
distribution was not measured.

**H3, "a modernized Tk can solve the same problems at lower cost": PARTLY DEMONSTRATED.** In this proof Tk matched Qt on
every reachability, tab-order, focus-indicator, keyboard-selection, notice and simulated-150% DPI check. The gaps that were
observed are: (1) no hover text on clipped cells (repairable with a Tk tooltip, **not built here**, so unproven),
(2) dispatcher policy (repairable by configuration, unmeasured as above), and (3) assistive-technology exposure, which Tk does
not provide per widget (0 named UI Automation elements). Only (3) looks like a fundamental toolkit constraint. Whether that
constraint matters is a product requirement this measurement cannot supply.

**H4, "a small Qt workspace overstates application-level reuse": SUPPORTED.** The shared toolkit-neutral layer
(`src/gui_v2`, 29 files, about 5.0k lines) imports no Tk and was fully reused. The Tk-bound surface that a migration would
replace is **134 files and about 65.8k lines** under `src/` (132 files in `src/gui`, plus `src/main.py` and `src/app_factory.py`,
including `MainWindowV2`, which is 1,949 lines and owns the `mainloop`), and 156 test files reference `tkinter`. This workspace
has one table pair, one navigation tree and a filter bar. It does not exercise the pipeline, learning, video or training
workspaces, controller presentation effects, persisted layout, theming of every widget family, or application shutdown.

**H5, "DPI and accessibility benefits are assumed, not demonstrated": PARTLY SUPPORTED.** DPI: both toolkits laid out
correctly at 100% and at a *simulated* 150%; the only evidence for Qt's real-monitor DPI behavior is the per-monitor-v2 awareness
it reports and a 100% monitor, so no DPI benefit over Tk is demonstrated. Accessibility: a benefit **is** demonstrated at the
UI Automation level (104 named elements vs 0), but no assistive technology was run and the operator's need for it is not
established.

**H6, "packaging, licensing and modules make deployment unattractive": NOT DEMONSTRATED, NOT REFUTED.** The installed wheel
metadata says PySide6 and Shiboken6 are `LGPL-3.0-only OR GPL-2.0-only OR GPL-3.0-only`, with a separate Qt commercial
license reference. Distributing under the LGPL has dynamic-linking and notice obligations, and a GPL choice could affect the
licensing of the combined work. StableNew is a local operator application today. The harness imports only QtCore/QtGui/QtWidgets
(no WebEngine, QML, Multimedia or PDF; a check enforces that). The Qt runtime is not a production dependency and requirement
files are unchanged. The exact modules, wheel size on disk and distribution model were **not** decided here, and nothing in this
report is legal advice.

**H7, "the proof introduces a second application or process authority": REFUTED.** Each child is launched by the parent through
the existing contained-process utility into an anonymous job object with a 60 s deadline, imports the other toolkit never
(`tkinter` is refused in Qt children and `PySide6`/`shiboken6` in Tk children), is blocked by an audit hook from Python-level
network, `sqlite3.connect` and subprocess calls, and must leave no descendants (none did). No production controller, queue,
runner, history, launcher or database is imported or written. The harness builds no queue, runner or controller of its own.
`qt_style.py` renders the shared design values and owns none. The audit hook is not a native-code sandbox.

## Qualification defects found and fixed during this package (disclosure)

1. **Aborted first run.** The first full run showed cross-toolkit parity failures because a timing-dependent delivery count was
   compared as part of an outcome. I stopped it, moved the count out of the compared outcome, added a regression test
   (commit `be900672`) and reran everything. The aborted evidence is not used.
2. **Stale Tk heartbeat chain (found by my own appraisal).** A pending Tk `after()` from a stopped heartbeat fired after the next
   run re-armed the shared flag, doubling the beat rate. In the first complete run, Tk's loaded-heartbeat median was reported as
   3.3 ms for a 5 ms timer, which is impossible for one chain. It is fixed (commit `ff1a9796`, regression test) and the
   evidence in this report is a full rerun on the fixed source. Only the Tk loaded-gap numbers were affected; the 2,000-callback
   burst, startup, memory, parity, DPI and accessibility results never used that heartbeat. The corrected Tk numbers are worse
   (median 6.9 ms, not 3.3), which is why this matters to H1.

## Limits of this evidence

- One host, one monitor, one run window, n=5 per condition, with the operator's live app running. Differences of a few
  milliseconds are within what this measurement can resolve only because the runs were tight (see the ranges above).
- The Tk workspace uses ttk `Treeview`; a virtualized or canvas-based Tk table was not tried. The Qt workspace uses
  `QTableView`. "Same functionality" means the same scripted outcomes, not the same code or the same rendering effort.
- `flush()` is a dirty-region flush in both toolkits and costs differ (Tk 0.004 ms, Qt 0.4 ms); neither number is a
  "frame time".
- A benchmark of a read-only inspection screen says nothing about the generation, queue-run and video workflows where the
  operator spends their time.

## Recommendation (verdict B)

**NO-GO for a production Qt migration on current evidence.** The measurable operator benefits are (a) dispatcher scheduling, which
is policy and not toolkit, (b) a few milliseconds of render and interaction time, and (c) UI Automation exposure. Against that
stand +90 ms startup, +34 MiB idle memory, a 134-file / 65.8k-line Tk-bound surface plus 156 Tk-referencing tests, an unresolved
license and distribution model, and an application lifecycle (shutdown, persisted UI state, controller presentation effects)
that this proof did not touch. The result is a NO-GO and not a strong NO-GO because the Tk-side repairs for (a) and for hover
text are plausible but not demonstrated, and because assistive-technology exposure is a real constraint of Tk.

**The question that would reopen it is a product decision, not a measurement:** does the operator, or anyone who will use
StableNew, require assistive-technology support or true per-monitor scaling on non-100% displays? If yes, a Qt option
needs a different package: an application-level shell proof including shutdown and persisted state, the licensing choice, and a
real 150% display and a screen reader. If no, the remaining differences do not justify the cost.

## Next step (proposed, not started)

**A bounded Tk experiment, GUI-SEAM-743: dispatcher budget tuning.** Run the burst and loaded-heartbeat measurements from this
harness against the production `TkUiDispatcher` with the pump budget as the only variable, in the Tk child only, and decide
whether a policy change recovers most of the 518 ms median without UI stalls. It needs no Qt and no `src/` change to measure.
No Qt implementation phase follows from this report.

## Retention

The harness and this evidence exist to reproduce the 742 verdict or to adjudicate a separately authorized Qt proposal. Retire
them with GUI-PORT-740 when the Qt option is closed or a replacement contract-test suite is accepted. They must never become
`src/gui_qt` by accretion.

## Reproduce

```powershell
C:/Users/rob/qual/gui-port740-env/Scripts/python.exe -m tools.qualification.gui_port_742.run --allow-gui --output <new absolute dir> --samples 5
```

Run from this checkout. The deterministic suite (`tests/tools/test_gui_port_742.py`, 58 tests) needs no PySide6 and no
display and is part of ordinary CI.
