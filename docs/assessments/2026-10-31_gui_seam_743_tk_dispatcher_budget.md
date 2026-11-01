# GUI-SEAM-743 — Tk dispatcher budget qualification

Evidence collected **2026-10-31** on one Windows 11 host. Follows [GUI-PORT-742](2026-10-31_gui_port_742_qt_workspace_qualification.md),
which attributed about 97% of Qt's synthetic burst-latency advantage to scheduling policy and proposed this experiment.

| Verdict | Result |
|---|---|
| **A. Qualification validity** | **PASS**: 35 measured + 7 warm-up primary runs and 10 measured + 2 warm-up confirmation runs, 0 invalid, 0 surviving processes |
| **B. Recommendation** | **NO-GO** on tuning the Tk pump. One tested lever (callbacks per pump) buys a large synthetic-burst gain and **no** operator-visible gain; the lever with operator relevance (worker refresh) does not move for any of the nine candidates |

Neither verdict authorizes anything. **Production dispatcher defaults and behavior are unchanged** (`15 ms / 32 callbacks / 8 ms`).

## Scope and what was built

Qualification only. Nothing under `src/` changed. A small harness under
[`tools/qualification/gui_seam_743/`](../../tools/qualification/gui_seam_743/README.md) reuses the accepted 742 Tk workspace,
fixture, measurement procedures, validators and owned launcher (about 1,300 new lines; 742 is untouched). It:

1. defers the first pump timer of a new production `TkInvoker`, sets the three tuning attributes on **that one instance**, then arms the timer;
2. records entry time and duration of every pump by shadowing `_pump` on that instance with a recorder that calls the **unmodified production `TkInvoker._pump`**;
3. reports the *effective* values read back from the instance for every child, and the *effective* idle pump period actually observed.

No second dispatcher, queue, loop or configuration mechanism exists. Ordinary CI tests (`tests/tools/test_gui_seam_743.py`, 100 cases) prove
the production defaults are exactly 15/32/8, that tuning is confined to the proof instance, and run the real `_pump` on a fake root under every
candidate for loss, duplication, FIFO order (including after a time-budget yield), GUI-thread execution, exception isolation, coalescing, delayed
work, idempotent disposal, late/worker enqueue after disposal and one pump per root.

## Execution identity

| Item | Observed |
|---|---|
| Source | branch `gui/seam-743-tk-dispatcher-budget` from `origin/main` `d83adeda` (PR #239 merged); measured at commit `8f000f10`, worktree clean for both phases |
| Primary run | 2026-10-31 22:02:37–22:08:39 (-04:00), seed 743, 5 measured rounds, validity `PASS` |
| Confirmation run | 2026-10-31 22:09:07–22:10:43, same SHA and fingerprint as the primary (checked), validity `PASS` |
| Platform | Windows 11 10.0.26100, CPython 3.14.9 x64 standard GIL, Tk 9.0.4, one 2560×1440 monitor at 100% |
| Fixture | 742 fixture digest `3f7d33fb…c433`, identical in every child; workload constants (500 rows, 2,000-callback burst, 12 refresh revisions, 1.5 s sustained at 20 ms, 3 s idle) are part of the validated record |
| Evidence | [`primary/metrics.json`](evidence/gui_seam_743/primary/metrics.json) (428 KB), [`confirmation/metrics.json`](evidence/gui_seam_743/confirmation/metrics.json) (127 KB), [`attempt1-aborted/`](evidence/gui_seam_743/attempt1-aborted/) |
| Attempt 1 | Stopped after two warm-ups (kept, unused): my validator demanded a p95 on the 16-sample refresh heartbeat, which the 742 rule leaves undefined for n < 20. Fixed to median/max; no condition, workload or threshold changed; no valid measurement was discarded |

The operator's running application was not launched or touched. **The host was not quiet**: the 500 ms CPU sample before each child was 57–67% for most
children and 4–9% for the rest (742's run saw 5–13%), from other work on the machine. It is recorded per run and is a confound, not a correction.

## Predeclared design

Candidates changed one dimension at a time (interval ms / callbacks per pump / pump ms). A is the immutable production control.

| Cond | A | B | C | D | E | F | G |
|---|---|---|---|---|---|---|---|
| Setting | 15/32/8 | 10/32/8 | 5/32/8 | 15/64/8 | 15/128/8 | 15/32/4 | 15/32/12 |

Order: one unmeasured warm-up per candidate, then five rounds in a seeded cyclic Latin square (each candidate in a different position each round).
Order effect check: mean position-normalized burst median varied 0.96–1.05 across positions and 0.99–1.03 across rounds, against effects of 0.34–0.54.

Screening (a candidate must clear **all**; no gate waives another): burst median **and** p95 cut ≥ 50% with the candidate's worst run beating the control's best;
sustained-load heartbeat p95 rise ≤ 2 ms and worst-gap rise ≤ 5 ms (and no refresh-window stall above 5 ms); worker-refresh-to-visible cut ≥ 10% and below the
control's best run; idle process CPU rise ≤ 0.5 percentage points. Confirmation: at most two combinations of already-tested values, declared before running:
**H = 10/128/8** and **I = 5/128/8** ("E plus a shorter interval").

## Results

Between-run median (min–max) of per-run values; five runs per condition. Burst and heartbeat percentiles are within-run statistics, reported per run and then spread across runs.

### Primary matrix

| Cond | Burst median ms | Burst p95 ms | Drain 2,000 ms | Pumps | Loaded hb p95 ms | Loaded hb max ms | Refresh ms | Idle pump period ms | Idle pump Hz |
|---|---|---|---|---|---|---|---|---|---|
| A 15/32/8 | **580** (560–630) | 1101 (1051–1133) | 1151 | 63 | 11.6 (8.7–18.5) | 25.5 (20.7–47.2) | **116** (101–131) | 15.9 | 58.6 |
| B 10/32/8 | 505 (483–513) | 946 (930–967) | 998 | 63 | 10.8 | 18.1 | 118 (103–131) | 15.8 | 63.3 |
| C 5/32/8 | 487 (484–501) | 908 (906–922) | 958 | 63 | 9.9 | 24.9 | 106 (100–121) | 15.7 | 65.3 |
| D 15/64/8 | 315 (263–360) | 623 (522–672) | 670 | 32 | 16.5 (8.8–17.6) | 26.5 | 118 (103–129) | 15.8 | 59.3 |
| E 15/128/8 | **195** (168–234) | 380 (330–445) | 410 | 16 | 13.2 | 23.3 | 108 (103–127) | 15.9 | 58.4 |
| F 15/32/4 | 553 (546–609) | 1078 (1015–1152) | 1127 | 63 | 11.1 | 26.1 | 116 (98–118) | 15.8 | 59.4 |
| G 15/32/12 | 565 (533–584) | 1081 (1020–1090) | 1144 | 63 | 16.0 | 26.8 | 118 (106–119) | 15.8 | 59.7 |

### Confirmation (screened against the primary control runs)

| Cond | Burst median ms | Burst p95 ms | Refresh ms | Idle pump period ms | Idle pump Hz | Loaded hb p95 / max ms |
|---|---|---|---|---|---|---|
| H 10/128/8 | 119 (89–144) | 221 | 111 (95–135) | 12.6 | 70.4 | 11.3 / 27.3 |
| I 5/128/8 | 88 (82–104) | 179 | 108 (99–116) | 6.2 | 115.7 | 13.3 / 29.2 |

### Screening outcome

| Cond | Burst med / p95 cut | Burst | Responsiveness | Refresh benefit | Resource | Result |
|---|---|---|---|---|---|---|
| B | +13% / +14% | FAIL | FAIL† | FAIL (−2%) | FAIL | reject |
| C | +16% / +18% | FAIL | FAIL† | FAIL (+8%) | pass | reject |
| D | +46% / +43% | FAIL | FAIL† (hb p95 +4.9 ms) | FAIL (−2%) | FAIL | reject |
| **E** | **+66% / +66%** | **pass** | pass | **FAIL (+7%)** | FAIL* | reject (burst only) |
| F | +5% / +2% | FAIL | FAIL† | FAIL (0%) | pass | reject |
| G | +3% / +2% | FAIL | FAIL† | FAIL (−2%) | FAIL | reject |
| H | +79% / +80% | pass | FAIL† | FAIL (+4%) | FAIL* | reject (burst only) |
| I | +85% / +84% | pass | FAIL† | FAIL (+7%) | FAIL | reject (burst only) |

† The responsiveness trigger is noise-dominated (limitation 7): conditions that change nothing relevant to the loaded path (F, G) "fail" it. **E is the only candidate that clears burst and responsiveness; it is rejected on the representative-refresh gate alone** (and H, I likewise once the noise is discounted).

\* See limitation 3: the resource gate's 0.5 pp threshold equals one CPU-time tick over the 3 s window, so E's and H's failures there are not credible on their own.
**The verdict does not rely on them**: every candidate, including E, H and I, independently fails the representative-refresh gate.

### Findings by workload

* **Burst (synthetic worst case).** Callbacks per pump is the lever: the drain takes `ceil(2000 / batch)` pumps, one pump per timer tick, so latency is set by the number of pumps × the tick. E drains in 16 pumps instead of 63 and cuts median latency 66%. A callback costs about 9 µs, so a 128-callback pump takes 1.2–4 ms and the **time budget never binds** (F and G are indistinguishable from A, +5% and +3%).
* **Interval.** Under the primary's timer regime the requested interval is ineffective: the observed idle pump period is 15.7–15.9 ms for 15, 10 and 5 ms (see limitation 2). B and C's 13–16% burst gains are not faster idle polling: the drain averaged 18.3 ms per pump for A against 15.8 (B) and 15.2 ms (C), so under load the control's re-armed timer often landed one tick later. This explanation is inferred from the drain data, not separately measured. Under the finer regime in the confirmation phase the interval is honoured (6.2 ms for a 5 ms request) and **doubles idle wakeups (116 Hz vs 59 Hz)** for a burst that batch size has already cut.
* **Sustained operator workload (50 updates/s, 1.5 s).** Heartbeat median is 5.0–5.1 ms for every condition. p95 and worst gaps are noisy and not ordered by the tuning (G, which only changes the time budget, has p95 16.0 ms; E, with 4× the batch, 13.2 ms). The worst pump in this load is 11–23 ms for every condition including the control, because a pump checks its budget only *between* callbacks and a single projection render (3.5–11 ms) overshoots it; no candidate changes that.
* **Worker refresh to visible.** 106–118 ms for all primary candidates, 108–111 ms for H and I. The best candidate (C) cut the median 8%, inside the control's own 101–131 ms run range. The path is a handful of callbacks plus the 75 ms notification-coalescing window and one table render; it never reaches a batch limit, so pump parameters have nothing to act on.
* **Interaction** (12 filter ops, 20 selections, direct Tk calls): 9–14 ms and 5–8 ms respectively with no ordering by tuning (G, which changes nothing relevant, is the slowest filter at 14.2 ms). Treated as host noise.

### Correctness, lifecycle and containment

All 54 native children (42 primary + 12 confirmation, every one valid) delivered exactly 2,000/2,000 callbacks with 0 missing, 0 duplicate, 0 out-of-order and 0 off-UI-thread executions; kept the selection through the worker refresh; showed a mapped, viewable window before any claim; reported effective parameters equal to requested and production defaults equal to 15/32/8 (cross-checked against the parent's read of the class); dropped delayed, queued, worker-originated and post-close work at close without a late view mutation; ended with a disposed dispatcher, empty queue and no timers, no Python worker thread and no PySide6 import; and left no owned descendant process. The same dispatcher object was returned for the root throughout (one pump chain). Deterministic cases that are unsafe to induce natively (slow callbacks consuming the budget, a backlog that never empties, callback exceptions, FIFO after a yield, duplicate coalescing, disposal races) are covered by the fake-root tests above, which ran the real `_pump`.

## Counter-hypotheses

| | Verdict | Evidence |
|---|---|---|
| **H1** burst is an artificial worst case | **Supported** | All 2,000 callbacks were enqueued before the first pump drained any (peak backlog 2,000 in every run); real worker traffic was not measured here but the sustained workload is ~50 updates/s. The operator-relevant measurement (refresh) is flat across all 9 candidates. |
| **H2** faster polling costs idle CPU | **Supported (weakly measured)** | Under finer timers 5 ms doubles the idle pump rate (1.97×) for no refresh gain. Idle process CPU is too coarsely sampled (limitation 3) to quantify the cost; the wakeup rate is the defensible number. |
| **H3** larger batches starve other UI events | **Not shown, not excluded** | E/H/I show no consistent loaded-heartbeat change with 9 µs callbacks (max burst pump 3–4.5 ms). The fixture cannot show it; a 128-batch of 100 µs–3 ms callbacks could. D's p95 flag (+4.9 ms) is matched by G (+4.4 ms, which changes nothing relevant) and is read as noise. |
| **H4** a longer time budget is not automatically fair | **Supported** | The budget is checked only between callbacks; the 11–23 ms pumps in the sustained load exceed the 8 ms budget in the *control*. Budget size cannot bound blocking; callback size does. |
| **H5** fixture simplicity | **Supported (open)** | One label update per callback and one 500-row table. Results do not predict richer production views. |
| **H6** coalescing is the better target | **Plausible, not tested** | 2,000 callbacks were a single label update; refresh is bound by a coalescing window, not by dispatch. Whether production emits duplicate/obsolete UI callbacks was not measured here. |
| **H7** harness changed dispatch semantics | **Rejected** | The production `_pump` ran in every child and in every CI case; the recorder only calls it. The deferred first timer is the one deliberate difference and is verified (first `after` uses the requested interval; no startup tick at 15 ms). |
| **H8** machine load / measurement bias | **Partly confirmed** | See limitations. Order bias ≤ 4.5%; host load high and uneven; timer regime changed between phases. |

## Limitations (bounded, unresolved)

1. **Synthetic findings vs production.** Everything above is a Tk research fixture on one host; it says nothing about the production Pipeline/Learning/History views, real callback rates or a quiet machine.
2. **Windows timer resolution was not recorded per run.** The primary phase's idle pump period (15.8 ms for every interval, including the 15 ms control) shows it ran under the coarse 15.6 ms regime; after the run `NtQueryTimerResolution` read 1.0 ms and the confirmation phase honoured 10 and 5 ms. The state is system-wide and set by other processes. Consequences: the interval effect (B, C) is measured only under the coarse regime and cannot be extrapolated; H and I are compared with a control measured under a different regime, so their 79–85% cuts are **not** a clean estimate of "E plus interval". The clean batch-size result (D, E vs A) is within one regime. This does not change the verdict (the refresh gate fails under both regimes), but any future package must record and control it. The harness was not changed after the fact, so the evidence matches its code fingerprint.
3. **Idle CPU resolution.** Windows `cpu_times` advances in 15.6 ms ticks; over 3 s that is 0.52 pp, equal to the 0.5 pp gate. Reported idle-CPU deltas of 0, 0.5, 1.0 pp are one to two ticks. The gate is therefore a coarse tripwire; the idle wakeup rate is the usable resource figure.
4. **Host load** 57–67% before most children, bimodal. Absolute latencies are higher than 742's (control burst median 580 ms vs 521 ms); only within-experiment comparisons are used.
5. **Confirmation has no concurrent control.** Its baseline is the primary's control runs (the contract caps the confirmation at 10 measured runs); see limitation 2 for why that matters.
6. Heartbeat gaps come from the 742 `update()` loop used for refresh and sustained loads; burst and idle run under `mainloop`. This is stated, not corrected; it is identical for every condition.
7. **The responsiveness gate is weak.** Its refresh-window max-gap component compares medians of per-run maxima over a 16-gap window; the control's own five runs span 22–38 ms and F (time budget only) reads 36 ms. A 5 ms trigger is below that noise, so FAIL here is a review flag, not evidence of a regression; likewise D's +4.9 ms p95 is matched by G's +4.4 ms. Consequently the *absence* of harm for E/H/I is also only weakly established (see H3).

## Independent appraisal

*(recorded below after the read-only review)*

## Recommendation

**NO-GO.** No candidate meets the combined conditions; the nearest (E, then H and I) win only on the synthetic worst case. Production defaults stay at 15/32/8.

Two things this experiment settles for the program, beyond the pump:

* The 742 finding that Qt's synthetic burst advantage is 97% scheduling policy was right, and it also shows that advantage **does not translate into operator-visible latency**: worker-refresh-to-visible is insensitive to every scheduling parameter tested. The remaining Qt/Tk refresh difference (84 vs 102 ms in 742) is therefore not a dispatcher-policy effect and is not a reason to tune Tk.
* If large callback floods are ever a real problem, the cost is in how many callbacks are produced, not how fast each pump drains them (H6).

**One next action (not implemented here):** stop tuning the pump. If the owner wants the burst ceiling pursued, open a separate bounded package that first *measures* real production callback arrival rates and duplicate/obsolete UI work (instrumentation on the GUI thread), and only then decides between source-side coalescing and any pump change. Any pump experiment after that must record the system timer resolution per run and run a concurrent control.

## Gates

Focused tests, the canonical PR gate and hosted CI status are recorded in the PR; see the completion report.
