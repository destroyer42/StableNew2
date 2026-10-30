# GUI-PORT-740: isolated Qt compatibility proof

This is an opt-in qualification harness, not an application host. It creates only
synthetic queue/history projections. It never builds the production app, submits
a job, opens a job database, starts a backend or reads generated artifacts.

## Reproduce on Windows x64 / CPython 3.14 standard GIL

Use a new disposable environment **outside** the checkout and production `.venv`:

```powershell
C:/Users/rob/Python314/python.exe -m venv C:/Users/rob/qual/gui-port740-env-new
C:/Users/rob/qual/gui-port740-env-new/Scripts/python.exe -m pip install --index-url https://pypi.org/simple --only-binary=:all: --require-hashes -r tools/qualification/gui_port_740/requirements-win-py314.lock
C:/Users/rob/qual/gui-port740-env-new/Scripts/python.exe -m pip check
C:/Users/rob/qual/gui-port740-env-new/Scripts/python.exe -m tools.qualification.gui_port_740.run --allow-gui --output C:/Users/rob/qual/gui-port740-new-evidence --samples 5 --rows 500 --burst 2000
```

Run from this checkout. The output directory must be new and absolute. The
defaults produce 16 sequential children: Qt contracts; three additional close
variants; then one separately labeled warm-up and five measured samples for each
toolkit. Each child has a 25-second parent timeout and a 15-second event-loop
deadline. Windows launch reuses the existing anonymous job container and suspended
launch primitive. Cancellation/cleanup applies only to that owned launch. No
production process manager or shutdown implementation changes.

The lock contains the exact official PyPI wheels selected on the measured host,
including the current AppState import dependencies. PySide6 6.12's metapackage
requires separate WebEngine/PDF distributions. They are installed as dependencies
but never imported or exercised. Only QtCore, QtGui and QtWidgets are used. Do not
substitute this proof lock for production requirements or infer redistribution
approval. `artifacts.json` records versions, wheel URLs, SHA-256 and metadata.

No flag defaults to NOT RUN (exit 2); no Qt module is imported. Ordinary CI uses:

```powershell
python -m pytest tests/tools/test_gui_port_740.py
```

These tests require no PySide6 and no display. Optional Qt execution must remain
separate from canonical CI dependencies. On the measured host native GUI tests
needed the normal desktop context outside the execution sandbox; do not switch to
offscreen and describe that as desktop evidence.

## Evidence and interpretation

`metrics.json` records child stdout events, stderr, exit/timeout, source hashes,
environment, native working set and owned-tree sampling, backlog, delivery
latency, rendering preconditions and descendant quiescence. `qt-proof.png` is a
capture of the synthetic Qt widget itself, not a desktop capture. Child audit
hooks reject accidental Python network/database/subprocess operations; they are
**not** a native-code security sandbox.

First-visible timing includes a fresh Python process and verified mapped/rendered
window. Tk flushes idle drawing after mapping; Qt observes first paint/exposure.
These are event-loop render proxies, not instrumented monitor-photon timings.
OS file caches are uncontrolled. Warm means a second comparable shell in the same
interpreter, not a warm production application. Do not call this an OS-cold-cache
benchmark. Native row-header/selection/rendering features differ; neither shell
implements the real workspaces.

Qt uses this proof's bounded queued-signal dispatcher (4096 requests, 128 delayed
reservations, at most 64 requests/5 ms per activation); Tk uses the production
15 ms pump with its existing callback/time budget. Their backlog results measure
these policies, not an intrinsic toolkit speedup. Dispatcher capacity errors are
explicit. Callback exceptions are recorded and later callbacks continue.
Disposal cancels pending work and linearizes against an already-running callback;
callbacks must remain short and must not join a worker that waits on disposal.

See the single durable assessment at
[`2026-10-28_gui_port_740_qt_compatibility.md`](../../../docs/assessments/2026-10-28_gui_port_740_qt_compatibility.md).

## Retention and teardown

Retain the harness only to reproduce this compatibility verdict or adjudicate a
separately authorized Qt proposal. Retire it when that proposal is accepted with
replacement contract tests, or the owner closes the Qt option; preserve the dated
assessment and accepted evidence. It must never become `src/gui_qt` by accretion.

The measured environment is `C:/Users/rob/qual/gui-port740-env`; it is retained for
review and can be deleted after all proof children exit. Before recursive removal,
resolve and check the **exact** dedicated environment directory and inspect its
`pyvenv.cfg`. For the reproduction example only:

```powershell
$proofEnv = (Resolve-Path -LiteralPath C:/Users/rob/qual/gui-port740-env-new).Path
if ($proofEnv -ne 'C:\Users\rob\qual\gui-port740-env-new') { throw 'Unexpected path' }
Get-Content -LiteralPath "$proofEnv\pyvenv.cfg"
Remove-Item -LiteralPath $proofEnv -Recurse
```

Never point teardown at system Python, the application's `.venv`, a checkout or
managed WebUI environments. Evidence directories are independent; preserve them
for review. No running StableNew/WebUI process may be stopped for cleanup.
