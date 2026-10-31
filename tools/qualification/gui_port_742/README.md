# GUI-PORT-742: representative Tk / PySide6 workspace qualification

An opt-in, read-only qualification harness. It is **not** an application host and not a second GUI: it renders one
Pipeline / Job History inspection surface in an isolated Tk child and an isolated PySide6 child from the same fixture,
the same scripted journey and the same measurement code. It never builds the production app, opens a job database,
starts a backend, submits a job or reads generated output. The verdict and numbers live in
[`2026-10-31_gui_port_742_qt_workspace_qualification.md`](../../../docs/assessments/2026-10-31_gui_port_742_qt_workspace_qualification.md).

## What is shared and what is toolkit-specific

| Shared (pure Python, toolkit-free, covered by ordinary CI) | Toolkit-specific (opt-in children only) |
|---|---|
| `fixture.py` deterministic 500 queue + 500 history records on the real `JobHistoryEntry` / `UnifiedJobSummary` contracts | `tk_view.py` / `tk_child.py` (production `theme_v2`, `TkUiDispatcher`) |
| `model.py` navigation (real `task_navigation_contract`), filters (real `history_browser_model`), selection, notices | `qt_view.py` / `qt_child.py` (`QTableView`, `QTreeWidget`, Fusion + `qt_style.py`) |
| `wiring.py` real `AppStateProjectionSink` + `AppStateV2` fed from a worker thread | `qt_dispatchers.py` Tk-policy control dispatcher; the 740 queued-signal dispatcher is the native one |
| `scenario.py` the 12-step journey and its independently computed expected outcomes | |
| `drive.py` identical timing boundaries and matrix procedure; `evidence.py` validators | `launch.py` / `run.py` owned launch and parent orchestration |

`qt_style.py` renders `src/gui_v2/design_values.py` and `TOKENS` as a stylesheet. It owns no value and must not be promoted
or grow a palette. It is pure text, so CI proves it imports no toolkit and uses no color outside the shared set.

## Run (Windows x64, CPython 3.14 standard GIL)

Reuse the accepted 740 proof environment or recreate it from the 740 lock (it stays outside the checkout and the
production requirements):

```powershell
C:/Users/rob/qual/gui-port740-env/Scripts/python.exe -m tools.qualification.gui_port_742.run --allow-gui --output C:/Users/rob/qual/gui-port742-evidence --samples 5
```

Run from this checkout. `--output` must be new and absolute; samples are 5 to 10; `--phases matrix,a11y,benchmark` may
narrow the run. Without `--allow-gui` it prints NOT RUN (exit 2). Each child is explicitly launched in an anonymous job
container with a 60 s deadline, returns structured JSON and must leave no descendants. Children refuse `tkinter` (Qt) or
`PySide6`/`shiboken6` (Tk) at import time and, like 740, reject Python-level network, `sqlite3.connect` and subprocess
calls. The audit hook is not a native-code sandbox.

The run is sequential and takes the real desktop: windows appear topmost for the duration. Do not use the machine for
anything heavy while it runs; host CPU use is recorded per child and is a confound, not a correction.

## Evidence rules

* A first-visible timestamp is rejected unless the window was mapped (Qt: also exposed and painted). Never emitted for an
  unmapped window.
* DPI is separate from window size. A simulated per-process scale is labeled SIMULATED and can never pass as ACTUAL;
  a claim a monitor contradicts, a non-per-monitor-v2 process or a window/monitor mismatch invalidates the record.
* Samples must be finite, non-negative and exactly the planned count; `p95` is reported only for n >= 20.
* Lossless bursts must deliver every update once and in order; coalesced hot-key streams must be strictly increasing and
  end on the final update.
* Cells that cannot be tested (actual 150%, fractional DPI, multi-monitor, screen readers, 1920x1080 at a simulated
  150% on a 2560x1440 panel) are listed as UNQUALIFIED in the report, never passed by inference.
* The UI Automation inspection is a read-only PowerShell client attached to the proof window's own process id, as
  reported by the child. It is not a screen-reader test.

## Retention

Keep only to reproduce the 742 verdict or adjudicate a separately authorized Qt proposal; retire with 740 when the Qt
option is closed or a replacement contract-test suite is accepted. It must never become `src/gui_qt` by accretion.
