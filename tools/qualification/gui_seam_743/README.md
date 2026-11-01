# GUI-SEAM-743: Tk dispatcher budget qualification

An opt-in, read-only, **Tk-only** research harness. It asks whether tuning the three internal knobs of the production
`TkInvoker` pump (`_pump_interval_ms`, `_max_callbacks_per_pump`, `_max_pump_duration_ms`) materially improves callback
latency and operator responsiveness without starving the event loop. It changes **no production code, default or
configuration mechanism**; the verdict and numbers live in
[`2026-10-31_gui_seam_743_tk_dispatcher_budget.md`](../../../docs/assessments/2026-10-31_gui_seam_743_tk_dispatcher_budget.md)
and the raw results under `docs/assessments/evidence/gui_seam_743/`.

## What it reuses and what it adds

Reused unchanged from GUI-PORT-742: the representative Pipeline / Job History workspace (`tk_view.py`), fixture, the
filter / selection / worker-refresh / sustained-load measurements (`drive.py`), the sample validators, the owned
job-object launcher and the child isolation guard. Added here (about 1,300 lines including the parent and analysis script):

| File | Role |
|---|---|
| `config.py` | Pure: the control, the seven one-factor candidates, validation, the two-confirmation rule, counterbalanced order, run plan |
| `inject.py` | Holds back the first pump timer, sets the three attributes on **one instance**, records pump entry/exit around the **unmodified production `TkInvoker._pump`** |
| `child.py` | One process = one condition: idle cadence + CPU under a real `mainloop`, filters/selection, worker refresh, sustained load, 2,000-callback burst under a real `mainloop`, lifecycle |
| `evidence.py` | Run validators, aggregation, the predeclared screening rules and the verdict function (pure, in ordinary CI) |
| `run.py` | Parent: validates everything before any window opens, launches children sequentially, writes `metrics.json` |

## Run (Windows x64, CPython 3.14 standard GIL)

```powershell
python -m tools.qualification.gui_seam_743.run --plan-only            # validated plan, no GUI
python -m tools.qualification.gui_seam_743.run --allow-gui --output C:/path/new/primary --samples 5
python -m tools.qualification.gui_seam_743.run --allow-gui --phase confirmation --primary C:/path/new/primary/metrics.json `
    --confirm H=10,64,8 --confirm I=5,128,8 --output C:/path/new/confirmation --samples 5
```

The run takes the real desktop (a topmost window per child, sequential). Start from a clean committed tree: the parent
records the SHA and refuses to PASS from a dirty worktree. Do not use the machine for anything heavy while it runs;
host CPU is recorded before and during every child and is a confound, not a correction.

## Predeclared design (fixed before any native run)

* **Candidates** (one factor at a time): A 15/32/8 control, B 10/32/8, C 5/32/8, D 15/64/8, E 15/128/8, F 15/32/4,
  G 15/32/12 (interval ms / callbacks per pump / pump ms). Not recommended settings.
* **Confirmation**: at most two combinations, each built only from values already tested, never a fresh search.
* **Ordering**: one unmeasured warm-up per candidate, then at least five measured rounds in a seeded cyclic Latin square
  (each candidate takes a different position every round).
* **Screening** (research triggers, not production thresholds), per candidate against the control's own runs:
  burst median **and** p95 each cut by at least 50% with the candidate's worst run still beating the control's best run;
  sustained-load heartbeat p95 rise at most 2 ms and worst-gap rise at most 5 ms; worker-refresh-to-visible median cut by at
  least 10% and below the control's best run; idle process CPU rise at most 0.5 percentage points. No gate waives another.
* **Verdict**: GO needs a candidate promising in the matrix and in a predeclared confirmation; a promising but
  unconfirmed candidate is CONDITIONAL GO; otherwise NO-GO. An empty, short or unbound experiment is FAIL, never PASS.

## Measurement boundaries

* Burst latency = worker `perf_counter` at `schedule()` to callback entry on the UI thread; execution cost is the callback
  body (one label update, no table re-render); total = first submit to last callback end.
* Effective pump period is measured from the recorder around the production pump, under a real `mainloop`, and reported next
  to the requested interval. Windows timer granularity can make a shorter requested interval ineffective.
* Heartbeat gaps are the 742 drift-compensated 5 ms `after` chain, started only after the window is mapped and populated.
  Worker-refresh and sustained workloads are driven by the 742 `update()` loop; idle and burst run under `mainloop`.
* Nothing here is display-photon latency. CPU is the child's own process time over a 3 s idle window plus host-wide
  `cpu_percent` over the same window.
* Synthetic fixture and lightweight callbacks: results do not predict richer production views (assessment H5).

## Retention

Keep only until the verdict is accepted and no production-scheduling package cites it; then retire with its tests. It must not
become a production configuration surface.
