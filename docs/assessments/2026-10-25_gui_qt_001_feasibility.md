# StableNew Focused Assessment — PR-GUI-QT-001: PySide6 feasibility, architecture boundaries and migration decision — 2026-10-25

Framework: v1.2. Status: draft for owner review. Completeness: COMPLETE for source and documentary evidence; **PARTIAL for runtime evidence** (no Qt code was executed on this machine; see §7.8 and §7.2 E-tier labels). Assessor: one top-level Claude Code session plus one read-only method-diverse critique subagent. Intent/outcome: decide whether to migrate the production GUI from Tkinter/ttk to PySide6 (Qt 6). Decision required: authorize, defer or reject the next migration phase. The assessor recommends; the product owner selects.

## 1. Executive decision

**Recommendation: NO-GO / DEFER the production migration now. Confidence: medium-high that deferral is right; medium that the Qt path would be technically achievable later.**

| Question | Answer |
|---|---|
| Is PySide6 technically suitable for a Windows-only CPython 3.14 app? | Probably yes. PySide6 6.12.0 ships a `cp310-abi3` Windows x64 wheel; `pip index versions` run under this machine's CPython 3.14.8 (AMD64, standard GIL) offers 6.12.0 as installable. **Not experimentally verified:** import, `QApplication`, rendering, startup and shutdown were never executed (E-tier "external-source" and "index-metadata" only). |
| Can presentation be migrated while retaining services and the canonical execution path? | Yes in principle: `tkinter` is imported only by `src/gui/**` (121 files containing the string, 120 importing it; 53,768 non-blank lines, 60,297 physical), `src/main.py` and `src/app_factory.py`. But the controller layer is not yet toolkit-free (§5, §7.5). |
| What must be extracted first? | Controller-to-widget reads and writes, `AppStateV2`'s import of the Tk-based `GuiInvoker`, `graceful_exit`'s Tk-root contract, GUI-owned Learning/Review controllers, and a single composition root (an open owner decision). |
| Licensing, packaging, resources? | LGPL-3.0 dynamic-wheel use is a plausible path; unresolved items need counsel and an owner decision on the open LICENSE question (§7.7). Wheel payload is ~124 MB compressed (Essentials + Addons + Shiboken + meta). |
| Qt vs continued Tk improvement? | The two prior repository assessments of this exact question (2026-10-16 audit D11 and the 2026-10-22 GUI tranche) already conclude "structure, not Tk, is the bottleneck" and "do not rebuild the entire GUI". This assessment found nothing that overturns that. |
| Smallest coherent M1? | If the owner wants to keep the Qt option alive: the toolkit-neutral seam in §7.11. Every element of that seam is also a Tk-quality improvement and is already on the audited roadmap, so it can proceed without committing to Qt. |

**Why deferral:** (1) No cited, measured operator problem requires Qt: the tranche's defects are workflow, truthfulness and Tk-thread I/O problems. (2) The migration surface is ~54k Tk lines plus ~160 Tk-dependent test files while the roadmap, the video work and the GUI tranche are all active in the same files. (3) Qt does not remove the hardest parts: the lifecycle, queue and shutdown chains are controller-level and would need the same extraction first. (4) The one item that could change the answer (frame-accurate video scrubbing, large virtualized galleries) has not been shown to fail in Tk. (5) Distribution/licence decisions that Qt forces are unmade (STATUS open owner decision 1).

**Next owner decision:** choose (A) continue the Tk tranche and fold in the no-regret seam (recommended), or (B) authorize a separately scoped, isolated Qt compatibility proof (§7.11, requires explicit authorization to install PySide6 in a throwaway environment).

## 2. Source lock and scope

- Remote: `https://github.com/destroyer42/StableNew2.git`. Local checkout used: `C:\Users\rob\projects\StableNew-agent` (clean, `main` was 821 commits behind). Other local checkouts (`StableNew` on `feature/pr-vid-192-animate2-control-truth` with an uncommitted `presets/settings.json` edit, `StableNew-main`, `StableNew-vid193-recovered`, 18 `StableNew.worktrees`) were **not touched**.
- Branch `research/gui-qt-001-feasibility` created from `origin/main` = `40946733afbd3d4a6f0158d7e51777261e166a36` (matches the previously observed baseline). Note: git set the new branch's upstream to `origin/main`; nothing was pushed.
- Task start: 2026-10-25T13:42:07-04:00 (Eastern). Main session ID: `claude:a5bab7f0-0206-406d-8b97-914c35857fbc`. Critique subagent session ID is recorded in the PR completion report.
- Baseline CI on this exact SHA (run 40203933054, `StableNew CI`): `required` success, `windows` success, `full-suite` and all three `full-suite-shard` jobs success. Open PR at snapshot: #212 (`learning/learn-stage-650-independent-baselines`, Learning stage baselines), a GUI-adjacent change that this assessment does not depend on.
- Did physical tests run? **No.** No generation, GPU, backend, model, runtime start, or Qt code ran. One metadata-only `pip index versions` query was made with the system CPython 3.14.8 (`C:\Users\rob\Python314`); nothing was installed or downloaded, and no StableNew `.venv` was used.
- Evidence unavailable: PySide6 is not installed anywhere on this machine (searched system Python 3.10/3.11/3.13/3.14 site-packages roots and the StableNew checkouts). Per the work package, installing it, even in a throwaway venv, needs separate authorization. **The optional technical proof was therefore not run** (single blocker; stop condition 2 acknowledged; the report is completed as a source-and-documentation assessment).
- Model note: the session ran on Sonnet 5.5; the package recommended Opus 5.5 High. Judgments here are therefore additionally covered by the independent critique (§7.9).

## 3. Historical PySide6 investigation (PR #2 and PS6-001..010)

PR #2 `Feature/pyside6 migration ps6 001` (created and merged 2026-03-10, 58 files, +3,687/−184) was merged to `main` with an unfilled template body. It carried planning docs for PS6-001..010 and two code outcomes: UI-dispatcher abstraction (PS6-003) and view-contract extraction (PS6-002). The planning docs were later moved to `docs/NeedsReview/PR_MAR26/` and are absent from the current tree; they survive only in Git history. Current tree mentions Qt once, in `docs/Subsystems/GUI/GUI_Ownership_Map_v2.6.md:133` ("`src/gui_v2/` exists as scaffolding for a potential future toolkit migration").

| Historical element | Status against current source |
|---|---|
| `UiDispatcher` protocol with Tk and Immediate implementations | **Survives.** `src/gui/ui_dispatcher.py` (52 lines); `ui_scheduler` is injected into `AppController` (`src/app_factory.py`). Still useful as the M1 dispatch contract. Its implementation file lives in `src/gui` and imports the Tk `GuiInvoker`, so the protocol is not importable without Tk. |
| View-contract extraction (frozen dataclasses, Tk-free sessions) | **Survives and grew:** `src/gui/view_contracts/` is 33 modules, 6,702 lines, consumed by 55 files. Useful, but only one contract (`edit_work_runner.py`) imports tkinter, so contract coverage of whole tabs is partial (§7.6). |
| Gate-driven 10-PR plan, mixed Tk/Qt runtime forbidden | **Partly useful:** "no mixed host in mainline" matches this task's invariant. Its single-step cutover and per-tab parity tests are superseded by §7.10. |
| `pytest-qt`, "CI GUI environment assumptions" | Unverified here; CI is Linux Xvfb census plus a Windows lane (`tools/ci/run_windows_lane.py`). Any Qt lane is new work. |
| PS6 plan assumptions on controller state ("reuse existing controller attach points only") | **Superseded/unsafe as written:** current `AppController` still reads and writes widgets (§7.3); attaching a second window to it as-is would violate "no second owner". |
| Archived code or branches | Not restored, not cherry-picked. Historical material is background only. |

Nothing in the historical set should inform M1 except the dispatcher and contract abstractions already in the tree.

## 4. Evidence register

Tiers: **CV** code-verified at SHA `40946733`; **DOC** repository document; **EXT** external primary source (fetched 2026-10-25); **IDX** index metadata via pip on this interpreter; **INF** inference; **UNV** unverified assumption. No runtime-verified (RV) entries exist.

| ID | Claim | Source | Tier | Limitation |
|---|---|---|---|---|
| E1 | `tkinter` is imported only in `src/gui/**` (121 files, 53,768 lines), `src/main.py`, `src/app_factory.py`. 76 other `src/gui` files (13,590 non-blank lines, 15,801 physical) are Tk-free. `src/gui_v2/` is 25 modules, 4,331 lines. | `git grep` over `src/` | CV | Counts are non-blank lines unless stated. |
| E2 | `AppStateV2` imports `GuiInvoker` (module imports `tkinter`) at module level; listeners are zero-argument and keyed (`subscribe`/`unsubscribe`), batched via `invoke_later`. | `src/gui/app_state_v2.py:14,142-261`; `src/gui/gui_invoker.py` | CV | |
| E3 | `UiDispatcher` Protocol exists; `TkUiDispatcher` wraps `GuiInvoker`; `AppController` takes `ui_scheduler`. | `src/gui/ui_dispatcher.py`; `src/app_factory.py` | CV | |
| E4 | Controllers import `src.gui*`: 17 ratcheted `controller_gui_imports` (12 in `app_controller.py`). | `tools/ci/architecture_baseline.json` | CV | |
| E5 | `AppController` (6,919 lines = its ceiling) references `main_window` on 88 lines (45 lines use `getattr(... main_window`); `_build_stage_flags` reads `pipeline_tab.<stage>_enabled.get()` Tk variables. `_ui_dispatch` prefers `main_window.run_in_main_thread`. | `src/controller/app_controller.py:746,1359` | CV | Count is line matches. |
| E6 | Controller ratchet ceilings: `app_controller.py` 6919, `job_service.py` 1227, `pipeline_controller.py` 1697, `job_history_service.py` 647; new controller limit 600. | `tools/ci/controller_surface_baseline.json` | CV | `STATUS.md` quotes 7,307 for `AppController`; the file is 6,919 now. Record as documentary drift. |
| E7 | Startup: `main()` acquires `SingleInstanceLock` (socket), builds Tk root, `build_v2_app`, registers `graceful_exit`, schedules WebUI/Comfy bootstrap with `root.after`, runs `root.mainloop()`. | `src/main.py:728-833` | CV | |
| E8 | Queue submit: Add-to-Queue → `AppController.on_add_job_to_queue_v2` → tracked thread `_submit_preview_jobs_to_queue_async` → `pipeline_controller.submit_preview_jobs_to_queue` → `JobService.submit_njrs`; completion returns by UI dispatch. | `app_controller.py:1634-1760`; `job_service.py:465` | CV | Downstream compile/enqueue not re-traced past `submit_njrs`. |
| E9 | Shutdown: `WM_DELETE_WINDOW` → `MainWindowV2._on_close` → graceful-exit handler → `graceful_exit()` → `controller.shutdown_app` (admission fence, cancel jobs, stop background work, learning hooks, WebUI, JobService, queue snapshot, threads) → `window.cleanup()` → `root.quit()/destroy()` → bounded wait → lock release → `os._exit(0)`. | `src/utils/graceful_exit.py`; `app_controller.py:4522` | CV | |
| E10 | Persisted nav: nine stable tab IDs, `LEGACY_TAB_ORDER` index fallback, `selected_tab_id` in UI state store. | `src/gui/view_contracts/task_navigation_contract.py`; `main_window_v2.py:1718` | CV | Store file format not changed in M0. |
| E11 | Tk-bound facility counts in `src/gui`: Tk Variable constructions 640 in 77 files; ttk in 113 files; Canvas in 19 files; `ImageTk/PhotoImage` in 18; `filedialog/messagebox` in 32; Treeview in 20. | `git grep` | CV | Regex counts. |
| E12 | Tests: 1,118 test files; 161 reference tkinter/`build_v2_app`/`MainWindowV2`; 48 contain a literal `tk.Tk()`/`tkinter.Tk()` (method-dependent: 64 by a `build_v2_app`/`MainWindowV2(` pattern, up to 199 with broader patterns); `tests/conftest.py` disables the garbage collector session-wide to avoid Tcl_AsyncDelete aborts; root `conftest.py` imports tkinter. CI census uses Xvfb on Linux; a Windows lane runs a Tk construction smoke. | `tests/`; `.github/workflows/ci.yml:201-290` | CV | |
| E13 | Video preview decodes via contained FFmpeg into bounded frames on a `ThreadRegistry` worker, delivered through `TkUiDispatcher`, drawn on a Tk surface. | `src/gui/widgets/video_preview_widget_v2.py` | CV | |
| E14 | Prior assessments conclude: stay on Tk (D11), "Don't rewrite the GUI in Qt", "Do not rebuild the entire GUI". | `docs/audits/2026-10-16_repo_audit_and_roadmap.md:535-540,811`; `docs/audits/2026-10-22_gui_ux_audit_and_tranche.md:60` | DOC | Point-in-time; independent corroboration only partially (same repo). |
| E15 | Composition root (P3-2) and controller/widget separation are open owner decision 11 and audit D3. | `STATUS.md` decision 11; audit D3 | DOC | |
| E16 | PySide6 6.12.0 (2026-10-08): licence `LGPL-3.0-only OR GPL-2.0-only OR GPL-3.0-only`, `requires_python >=3.10,<3.16`, classifiers include 3.14; Windows x64 wheel `cp310-abi3`: PySide6 meta 578,958 B; Essentials 82,153,795 B; Addons 40,522,402 B; Shiboken6 1,265,476 B. | PyPI JSON for `PySide6`, `PySide6_Essentials`, `PySide6_Addons`, `shiboken6` | EXT | Compressed sizes; install size not measured. |
| E17 | `pip index versions PySide6` under CPython 3.14.8 AMD64 (GIL build) lists 6.12.0, 6.11.2 … as installable. | system `pip 26.2.1` | IDX | Proves a compatible file exists, not that it runs. |
| E18 | Qt for Python 6.12: Qt 6.12 LTS, free-threaded Python unsupported ("still in research"), Python 3.15 initial support, `pyside6-deploy` now standalone by default, Windows shell-injection fix. | qt.io release blog | EXT | Blog does not address 3.14 desktop explicitly. |
| E19 | Qt threading: widgets main-thread only; queued connections cross threads; `deleteLater` needs a running loop; events dropped without a loop. | doc.qt.io `threads-qobject` | EXT | |
| E20 | Qt 6 is per-monitor DPI aware V2 by default; rounding policy configurable; `QPixmap` carries a device pixel ratio. | doc.qt.io `highdpi` | EXT | |
| E21 | Qt Multimedia: FFmpeg is the Windows default; the WMF backend is deprecated since 6.10 and slated for removal; LGPLv3/GPLv2; FFmpeg LGPL-2.1+; codec patents not covered. | doc.qt.io `qtmultimedia-index` | EXT | Seek/scrub behaviour not documented on the fetched page. |
| E22 | LGPLv3: dynamic linking keeps the app separable; users must be able to replace and relink; licence text and prominent notice; complete corresponding source or written offer (link to upstream is insufficient per Qt FAQ); some Qt modules GPL-only; WebEngine embeds Chromium with LGPL-2.1 third-party terms. | qt.io LGPL obligations page; Qt FAQ; WebEngine licensing page | EXT | Not legal advice; module-by-module GPL-only list not retrieved. |
| E23 | Distribution today is a source checkout bootstrapped into a repo-local `.venv` from pinned constraints (`scripts/bootstrap_windows.ps1`, `constraints/windows-py314-cu130.txt`); no frozen binary; `pyproject.toml` declares `license = MIT` but **no `LICENSE` file exists** (STATUS open owner decision 1). | repo | CV/DOC | |
| E24 | Qt Widgets uses a raster painter by default and Qt Quick is a separate scene-graph/RHI stack. | Qt background knowledge | UNV | Not fetched this session; verify before relying. |

## 5. Present architecture (compact dependency map)

```
main.py ──tk.Tk()── build_v2_app (app_factory.py)
  │                    ├─ TkUiDispatcher(root)  ── GuiInvoker (Tk after-pump)
  │                    ├─ AppStateV2  ◄── imports GuiInvoker (Tk)  [seam hazard]
  │                    ├─ build_gui_kernel (src/app/bootstrap.py)   [toolkit-free]
  │                    ├─ AppController(main_window=None, ui_scheduler=dispatcher.invoke)
  │                    └─ MainWindowV2(root, app_state, app_controller, …)
  │                          └─ app_controller.set_main_window(window)  [bidirectional]
  ├─ root.after(...) WebUI/Comfy async bootstrap, watchdog, emergency cleanup
  └─ root.mainloop() ... graceful_exit(controller, root, lock, window)  → os._exit(0)

AppController ──► pipeline_controller ──► JobService.submit_njrs ──► SQLite repo/queue
     ▲  reads/writes main_window, *_tab Tk vars, error modal, panels   [coupling]
```

Primary migration seams (good news): the canonical path below the controller is toolkit-free and untouched by this question; `build_gui_kernel`/`ImageRuntimePorts` are neutral; `UiDispatcher`, `AppStateV2` keyed invalidation, `view_contracts` and `gui_v2` projections exist; `SingleInstanceLock` and `JobService` are toolkit-free. (`graceful_exit.py` is *not* import-clean: it imports `AppController` at runtime, which pulls in `src.gui` and tkinter, although it only uses it as an annotation.)

Hazards: `AppController` constructs and reaches into widgets; `AppStateV2` imports a Tk module; `graceful_exit` sequences `root.quit()/destroy()` (duck-typed, `root: Any`) and imports `AppController` only for an annotation; `MainWindowV2` is 1,910 lines and owns tab construction, UI state, heartbeat and shutdown handler; `main.py` is 837 lines mixing runtime bootstrap with `root.after`; the Learning and Review controllers live in `src/gui/controllers/` and are reached through `main_window` paths.

## 6. Target architecture (candidate; not authorized)

```
              ┌───────────── Presentation hosts (one active per process) ─────────────┐
              │  Tk host (default, unchanged)        Qt host (opt-in entry, candidate) │
              │  Tk widgets, ttk, Canvas             QMainWindow, item models, QtWidgets│
              │  TkUiDispatcher                       QtUiDispatcher (queued signal)    │
              └───────▲──────────────────────────────────▲─────────────────────────────┘
                      │ binds to                         │ binds to
              ┌───────┴──────────────────────────────────┴─────────────────────────────┐
              │ Toolkit-neutral GUI API  (new package, no tkinter / no PySide6 imports) │
              │  UiDispatcher · Subscription handle · Intent commands (typed)          │
              │  Read-only projections (frozen) · Navigation (stable tab IDs)          │
              │  Lifecycle: ready / shutdown request · Background-work delivery        │
              └───────▲─────────────────────────────────────────────────────────────────┘
                      │ implemented by existing owners (no second authority)
   AppController / services → JobService.submit_njrs → SQLite queue/repository → run_njr
```

Ownership and direction: hosts depend on the neutral API; the neutral API depends on application services via existing ports; services never import a host. One composition root builds exactly one application stack and one host; Qt never creates a queue, runner, repository, process manager or cancellation owner. Application truth stays in `AppStateV2`, repositories and projections; Qt item models are read-only views over projections. Two event loops never run in the same process.

Candidate neutral-interface classification (§4D of the package):

| Contract | Already reusable | Small extraction | Substantial refactor | Toolkit-specific | Must never be in GUI |
|---|---|---|---|---|---|
| Intent commands / authoring ops | `view_contracts` sessions, `gui_v2` models, `QueueRunSubmissionService` | Name a typed command surface over current `on_*` methods | Controller methods that read widgets (`_build_stage_flags`) | Widget event wiring | NJR compilation, `JobService` admission, runner calls |
| Read-only projections | `queue_status_contract`, `history_*_contract`, `generation_profile_projection`, `batch_projection` | Move `content_visibility`, `learning_state` out of `src/gui` | `AppStateV2` (~70 fields incl. `controller: Any`) split into frozen slices | Qt item models | Queue/history authority (SQLite repository) |
| Subscription registration/disposal | `AppStateV2.subscribe/unsubscribe` | Return disposable handle; stale-callback guard | | Qt signal/slot adapters | |
| GUI-thread dispatch | `UiDispatcher` Protocol | Move Protocol and an invoker Protocol out of `src/gui`; drop `AppStateV2`'s `GuiInvoker` import | Retire `main_window.run_in_main_thread` preference in `_ui_dispatch` | `TkUiDispatcher`, future `QtUiDispatcher` | |
| Navigation / stable IDs | `task_navigation_contract` | | | Notebook / `QTabWidget` binding | |
| Startup/readiness/shutdown | `graceful_exit` controller half, `shutdown_app` | `graceful_exit`: `TYPE_CHECKING` guard for `AppController`; split into toolkit-free shutdown + host `close()` | Single composition root (owner decision 11) | Root destroy, `QApplication.quit` | Process-ownership rules (managers launch/own only their runtimes) |
| Background work / latest-wins | `BackgroundWorkRunner`, `edit_work_runner`, `ThreadRegistry` | Standardize on one primitive (audit D6) | Five coexisting patterns | Delivery callback only | Cancellation authority (JobService/repository) |
| Error/status/content visibility | `status_banner_contract`, `feedback_panel_contract`, `ContentVisibilityResolver` | Resolver imports `src.gui.content_visibility` (move) | `ErrorModalV2` reached from controller | Dialogs | Visibility policy decisions |

## 7. Findings

### 7.1 Technology and compatibility (PySide6 / Qt Widgets)

- Versions: PySide6 = Essentials + Addons (+ Shiboken6 pinned `==6.12.0`). Windows x64 is a stable-ABI wheel, which is the right shape for CPython 3.14 (E16, E17). PySide6 6.12 does not support free-threaded CPython (E18); StableNew already forbids it (`scripts/bootstrap_windows.ps1`), so no conflict. **Official explicit 3.14 support statement: not found** (classifiers list 3.14; the 6.12 release notes only name 3.15 additions). Treat 3.14 runtime behaviour as UNV until executed.
- Qt Widgets capability fit (EXT/INF, not exercised): responsive layouts, `QDockWidget`/`QSplitter` docking, `QAbstractItemModel` tables with virtualization, `QGraphicsView`/`QPainter` custom canvases for mask/outpaint, native `QFileDialog`/clipboard, UI-Automation-based accessibility and keyboard navigation for standard widgets (E20, accessibility page; custom canvases would need explicit accessible metadata). Qt gives genuine advantages in item-model virtualization (the audit's "no thumbnail grid" gap) and high-DPI correctness (E20). Tk can reach a virtualized grid and Canvas mask editor too (audit D11).
- Threading: widgets main-thread only; queued signals marshal results; objects need a running loop for `deleteLater`/timers (E19). This fits the existing "marshal to GUI thread" rule, and a `QtUiDispatcher` is a small adapter. The bigger lifecycle danger is destruction ordering: `graceful_exit` today ends in `os._exit(0)`, which would skip Qt teardown (acceptable) but also skip any Qt-owned flush.
- Qt Quick/QML: not required. Using Qt Widgets without a Qt Quick scene is straightforward in principle; QML would add a second declarative stack, a QtDeclarative licensing review and GPU/RHI pressure. Recommendation: Widgets only; QML only for a specifically justified future surface.
- Media: Qt Multimedia (FFmpeg default, WMF deprecated; E21) would introduce a **second media decoder** inside the app process, whereas the current path decodes in a contained, bounded child and the GUI-510 acceptance contract forbids "a second decoder or background process authority" (tranche doc §GUI-UX-510). Keeping the existing preview decode and rendering frames in Qt avoids that.
- Startup/resource cost: ~124 MB compressed wheels (E16), additional DLLs and plugins; startup and idle CPU/RAM are **not measured** (§7.8).

### 7.2 Licensing and distribution (decision table; not legal advice)

| Item | Finding | Status |
|---|---|---|
| PySide6/Essentials/Addons/Shiboken | `LGPL-3.0-only OR GPL-2.0-only OR GPL-3.0-only`; commercial licence also available (EXT) | Plausible path via LGPL |
| Linking model | Dynamic wheels satisfy "work that uses the library"; static linking or compiling into one binary needs a stricter analysis | Counsel |
| Notices / source offer | LGPL text, prominent notice, complete Qt source or written offer (upstream link alone insufficient per Qt FAQ) if StableNew *redistributes* Qt | Applies only on redistribution |
| Today's distribution | Source checkout + user-run bootstrap pulls wheels from PyPI into a local `.venv` (E23). **INF:** StableNew would not itself redistribute Qt, so most obligations fall on whoever ships a bundle | Confirm with counsel |
| Replace/relink right | Frozen one-file builds (`pyside6-deploy --mode onefile`, Nuitka) make replacement harder; standalone folder is the 6.12 default | Packaging choice affects licence |
| Qt Multimedia | LGPLv3/GPLv2; FFmpeg LGPL-2.1+; H.264 patent fees not covered | Avoid, or review |
| QtWebEngine | Chromium + LGPL-2.1 third-party obligations; much heavier | **Do not use** |
| Qt Quick/QML | `qtdeclarative` licence nuance reported on Qt forums (UNV) | Review before any QML |
| GPL-only Qt modules | Qt says some modules are GPL-only; list not retrieved | Check each Addons module used; restrict to Essentials where possible |
| PyQt6 | GPL/commercial, not LGPL | Not considered |
| Project licence | `pyproject.toml` says MIT; no `LICENSE` file; owner decision 1 open | **Preserved, not resolved**: any Qt path must wait on or accompany this decision |
| Reproducibility | Windows abi3 wheels are pinned by version; hashes not yet captured; `constraints/windows-py314-cu130.txt` is the right home | Future M-phase |
| Questions for qualified review | LGPLv3 anti-lockdown clause vs. any bundled installer; MIT app + LGPL dependency presentation; whether Addons wheel inclusion triggers GPL-only modules; Multimedia/FFmpeg codec patents | Open |

### 7.3 Coupling inventory

Representative chains traced:

1. **Normal workflow (Pipeline → queue):** E8. The GUI button calls the controller; submission runs on a tracked thread, goes through `pipeline_controller.submit_preview_jobs_to_queue` and `JobService.submit_njrs`; completion returns through the UI scheduler. A shutdown guard (`_is_preview_queue_submission_blocked`) and a single-flight flag exist. Reusable unchanged.
2. **Shutdown/cancellation:** E9. Order matters: admission fence → cancel active jobs → background work → learning hooks → WebUI (owned process only) → JobService → queue snapshot → repository close only after quiescence → thread registry join; window cleanup happens after the controller, then the Tk root is destroyed. A Qt host must call the same controller sequence, then `QApplication.quit`, and must not regress the Tk path's timing. The 2.0 s `STABLENEW_SHUTDOWN_TIMEOUT` bounds only the poll *after* `shutdown_app` returns; `shutdown_app` itself runs synchronously with no outer bound.
3. **Startup:** E7. Single-instance lock, runtime kernel, controller, window, then asynchronous WebUI/Comfy bootstrap scheduled by `root.after`. A Qt host needs a `QTimer.singleShot`-style adapter and a Tk-free "already running" dialog.

Tk-specific dependencies by kind: Tk root/`mainloop`/`after` (main, invoker, 56+ bare `after()` calls reported by audit D6), Tk Variables (640), ttk (113 files), Canvas surfaces (19), `ImageTk`/`PhotoImage` (18), modal dialogs (32), Treeview (20), widget reads from controllers (E5).

### 7.4 Controller Surface Assessment (production controller changes: none)

- References that would block an independent Qt host: `AppController` imports `AppStateProjectionSink`, `AppStateV2`, `ReviewWorkflowAdapter`, `DropdownLoader` from `src.gui`, lazily imports `DebugHubPanelV2`, `JobExplanationPanelV2`, `ErrorModalV2` and the `video_workspace_handoff` routing functions; configures buttons on `header`/`left` widgets (`app_controller.py:2444-2459`); reads Tk variables at `:1359`, `:4187-4200` (upscale), `:5626` and `:5718` (config gather) and writes them at `:4384` and `:5325` (`enabled_var.set`), seven sites in all; calls `winfo_exists` (`:3442`). Other blockers: `gui_config_service`, `content_visibility_resolver`, `prompt_pack_preflight` (imports `klein_lora_selection_dialog`, a Tk dialog), `review_batch_service`, plus `src/learning/execution_controller.py`, `src/pipeline/randomizer_v2.py` and `src/learning/model_policy_service.py` (lazy) importing GUI-resident modules. `core_pipeline_controller` imports `src.gui` only under `TYPE_CHECKING`. Controller imports of `gui_v2` (`generation_profile_controller`, `learning_execution_controller`) and importers in `src/photo_optimize/` and `src/review/assist/geometry.py` are **not counted** by the `controller_gui_imports` ratchet (it counts only `src/controller` imports of `src.gui`), so lowering that number can be met by moving modules into `gui_v2`; a no-tkinter-in-import-closure check is the meaningful gate.
- Replaceable by existing ports/adapters: dispatch (`ui_scheduler`), runtime construction (`build_gui_kernel`, `ImageRuntimePorts`), submission (`QueueRunSubmissionService`), `gui_v2` projections and `view_contracts` sessions, `AppStateV2` projection sink.
- Single composition-root refactor required? **Yes for a clean Qt host** (host choice must be made once and injected), but a Tk-compatible subset (remove widget reads, relocate neutral modules, split `graceful_exit`) can precede it. The composition root is roadmap P3-2 / open owner decision 11, so this assessment does not authorize it.
- Ratchets that would need to **decrease** in M1: `controller_gui_imports` 17 → near 0 (and `utils_upward_imports` 1 for `graceful_exit`), paired with a new closure check so the count cannot be gamed, `app_controller.py` ceiling 6919 should drop as widget wiring leaves; no ceiling may rise.
- Incremental while Tk stays green? **Yes**, if each extraction is a behaviour-preserving move with the existing Tk tests as the guard (the Tk-root tests + the Windows construction smoke).

### 7.5 Coupling matrix

| Dependency | Evidence | Class | Affected tests |
|---|---|---|---|
| Canonical path below `JobService.submit_njrs` | E8, AGENTS invariants | Reusable unchanged | pipeline/queue suites |
| `build_gui_kernel`, `ImageRuntimePorts` | `src/app/bootstrap.py` | Reusable unchanged | `tests/app` |
| `UiDispatcher` Protocol | E3 | Small extraction (move out of `src/gui`) **plus** an `invoke_later` method: `AppStateV2` batching and `_ui_dispatch_later` need delayed dispatch; the controller has four dispatch paths (main_window, `ui_scheduler`, `_dispatch_via_root_after`, inline fallback); two independent `GuiInvoker` pumps exist (`app_factory.py` and `main_window_v2.py:242-243`); `TkUiDispatcher.invoke` can run inline on the caller's thread. Invoker ownership borders owner decision 11. | `tests/gui_v2/test_ui_dispatcher.py`, `tests/controller/test_ui_dispatcher_contract.py` |
| `AppStateV2` | E2 | Small extraction (invoker Protocol) then substantial slicing | `tests/gui_v2/test_app_state_subscribe_unsubscribe.py` |
| `view_contracts` / `gui_v2` | E1, §3 | Reusable unchanged (coverage incomplete) | `tests/gui_v2` |
| `ContentVisibilityMode/Resolver` | `src/gui/content_visibility.py` imported by controller | Small extraction | content-visibility tests |
| `LearningState` and Learning/Review GUI controllers | `src/gui/controllers/*`, `src/learning/execution_controller.py` imports | Large extraction | learning_v2, controller learning tests |
| `AppController` widget reads/writes | E5 | Large extraction | `tests/controller`, tab tests using `__new__` bypasses (audit D8) |
| `graceful_exit` + `MainWindowV2.cleanup` | E9 | Small-to-large extraction | shutdown tests, Windows lane |
| Single composition root | audit D3, decision 11 | **Open architectural decision** | wiring tests via `build_v2_app` |
| `main.py` bootstrap with `root.after`, error `messagebox` | E7 | Toolkit-specific replacement | startup smoke |
| 121 Tk files | E1 | Toolkit-specific replacement (full rewrite) | 161 test files reference Tk entrypoints |
| Media inspector / video preview | E13 | Toolkit-specific replacement; keep contained decode | media tests |

### 7.6 Feature and parity matrix (feature/contract level; behaviour preserved, not redesigned)

Counts are for the primary tab file at this SHA: lines / Tk Variables / imports from `view_contracts` or `gui_v2`.

| Workspace (tab id) | Presentation owner | Neutral contract coverage | Tk-specific dependencies and special handling | Risk | Rough size* | Minimum acceptance evidence | Order |
|---|---|---|---|---|---|---|---|
| Shared shell (all) | `MainWindowV2` (1,910) | `task_navigation_contract`, `window_layout_contract`, status/feedback contracts | Notebook, heartbeat, UI-state store, modal dialogs, logs, readiness strip, accessibility | High | L | Stable-ID navigation + persisted-selection round trip; shutdown parity; heartbeat/watchdog parity | 1 |
| Create — Prompt (`prompt`) | `prompt_tab_frame_v2` (2,561 / 26 / 8) | prompt editor, LoRA, optimizer views | Rich text editor, PromptPack state, model inventory, LoRA controls, optimizer, handoffs | High | XL | PromptPack edit/save round trip; effective-prompt equality vs Tk | 5 |
| Create — Pipeline (`pipeline`) | `pipeline_tab_frame_v2` (958 / 18 / 1) + sidebar, stage cards, preview | pipeline layout/composer contracts, generation-profile projection | Stage toggles read by controller, model-aware profiles, effective settings, Preview, queue admission | High | L | Preview/admission equality; queue submit via `submit_njrs` unchanged | 4 |
| Edit — Review (`review`) | `review_tab_frame_v2` (2,452 / 19 / 3) + `mask_editor_dialog`, `outpaint_dialog` | `review_selection_contract`, `edit_work_runner`, mask/outpaint state | Canvas painting, original-pixel restore, zoom/pan, async image load, content visibility, lineage | **Very high** | XL | Mask/outpaint pixel-identity at admission; async image disposal; content-visibility enforcement | 7 |
| Edit — Photo Optimize (`photo_optimize`) | `photo_optimize_tab_frame_v2` (1,299 / 42 / 2) + layout (1,089) | `photo_optimize_layout_contract`, `photo_baseline_save_contract` | Per-photo sidecars, KeyRelease saves (audit D5), compare view, responsive reflow | High | L | Independent per-photo baselines; sidecar write debounce; layout contract tests | 6 |
| Motion — Video Workflow (`video_workflow`) | `video_workflow_tab_frame_v2` (1,693 / 25 / 9) + several `video_workflow_*_panel_v2` panels | Best covered (9 contract imports in the tab; many `video_*_contract` modules) | Basic/Advanced, media player, sequence authoring, Make Video handoffs | High | L | Handoff routing; recent-outputs bounded playback; sequence admission unchanged | 8 |
| Motion — SVD (`svd`) | `svd_tab_frame_v2` (1,907 / 31 / 1) | Minimal | Many inference controls, presets | Medium | L | Preset round trip; queue submit | 9 |
| Motion — Movie Clips (`movie_clips`) | `movie_clips_tab_frame_v2` (937 / 14 / 3) | `movie_clips_contract` | Ordered media list, timeline/preview | Medium | M | Ordered-source assembly job admission | 9 |
| Learn (`learning`) | `learning_tab_frame_v2` (2,282 / 20 / 2) + `experiment_design_panel` (1,997), `learning_review_panel` (1,288), `learning_grid_view` (520) | Minimal; **63 direct controller calls** | Experiment design, preview, compare, rate, curation, grid canvas, stored drafts | **Very high** | XL | Evidence-correctness (observational vs experimental), resume/draft persistence parity | 10 |
| Advanced — Character Training (`character_training`) | HOLD | `task_navigation_contract` hold flags | HOLD messaging only | Low | S | HOLD label and no implicit enablement | with shell |

*Size is a relative engineering estimate (INF): S < 1 package, M ~1-2, L ~3-5, XL ~6-10 bounded packages.

User-state compatibility risks to name: persisted `selected_tab_id` and the `selected_index` fallback (never reorder `LEGACY_TAB_ORDER`), `state/ui_state.json`, per-tab saved UI state, PromptPack and Photo Optimize sidecars, recipes/presets, collapse state, and Learning drafts.

### 7.7 (see §7.2) Compatibility, licensing and deployment — unresolved questions

Unresolved: official Python 3.14 runtime support statement; module-level GPL-only list; legal review of LGPLv3 with an MIT-declared app and no LICENSE file; whether any future frozen distribution is intended; hash-pinned dependency strategy; whether `pyside6-deploy` (Nuitka-based, wants MSVC `dumpbin`, runs project module-level code during deploy) is compatible with the existing bootstrap-based distribution (it is not needed if distribution stays source + `.venv`).

### 7.8 Performance and reliability considerations (no measurements collected)

Nothing below was measured on this machine. Items are risk hypotheses with a proposed measurement.

- Idle CPU/RAM and startup/first render: Qt adds a larger native footprint; measure `QApplication` + empty main window + shell vs Tk shell with the same synthetic data.
- High-DPI/resize: Qt 6 per-monitor DPI V2 default (EXT) is a likely gain over Tk scaling; verify across the owner's monitors.
- Event delivery under load: the Tk pump bounds work (32 callbacks / 8 ms per 15 ms). Qt queued signals have no equivalent bound; a fake high-rate producer test is required. The M1b proof should also exercise object-destruction thread affinity, since the Tk suite already needs a session-wide GC disable for Tcl_AsyncDelete aborts.
- Media decode/render: keep contained FFmpeg frame decode (E13); Qt Multimedia would add GPU/decoder contention with generation on the single RTX 4070 Ti 12 GB (UNV) and a second decoder authority.
- GPU contention: Qt Widgets/raster is CPU-drawn by default (E24, UNV); QOpenGLWidget/RHI/QML would add GPU use, in tension with the documented intermittent CUDA device-loss history (STATUS holds). Do not accelerate the shell.
- Shutdown/process ownership: shutdown ordering must be identical (E9); Qt event-loop exit must not pre-empt `shutdown_app`.
- Testing: CI Tk lane is Xvfb on Linux; a Qt lane would need `QT_QPA_PLATFORM=offscreen` plus a Windows lane (UNV).

### 7.9 Alternatives and critical appraisal

Alternatives: (a) continue Tk/ttk modernization (existing tokens; ttk themes; no new dependency); (b) Qt Widgets full migration; (c) Qt for one surface only; (d) Qt Quick/QML shell; (e) web UI/Electron.

| Counterhypothesis | Verdict | Evidence / method |
|---|---|---|
| H1. The main usability problem is workflow design, not Tk | **Supported** | Tranche findings are mostly labels, empty states, config ownership, media identity and Matrix semantics (all toolkit-independent); D11 |
| H2. Current Qt benefits do not justify a rewrite | **Supported** | No measured Tk limit; virtualized grid and Canvas mask editor judged feasible in Tk (D11); 54k-line surface, ~160 test files |
| H3. Existing neutral contracts are insufficient | **Partly supported** | Contracts are strong for Video Workflow (9 imports) and weak for Learning (2 imports, 63 controller calls), Review (3), SVD (1). The seam exists but is incomplete — this is cost, not a showstopper |
| H4. A Qt port would increase lifecycle fragility | **Supported for the near term** | Shutdown/startup chains are controller-level and widget-entangled (E5, E7, E9); a second host before extraction duplicates them |
| H5. New visual features would raise hardware pressure | **Plausible, unmeasured** | Only if GPU-accelerated Qt is chosen; Widgets raster alone should not (UNV) |
| H6. The GUI tranche may already solve the highest-value problems | **Largely supported** | 11-PR sequence targets the audited issues inside Tk; several are merged (#209 shared inspector, #210 guided Learning workflow) |
| H7. A one-surface Qt spike is the cheap middle path | **Refuted as stated** | Hosting a Qt surface inside a live Tk process needs two cooperating event loops, forbidden by the invariant; an out-of-process Qt viewer would add a second process authority. The only safe form is a throwaway isolated proof |

**Method-diverse critique (Pass B).** Pass A used documents plus structural greps. Pass B used (i) a scripted per-tab measurement of contract coverage versus controller calls (§7.6), (ii) CI per-job conclusion inspection on the exact SHA, (iii) an import-graph check of which controller/utility modules import `src.gui*`, and (iv) an independent read-only subagent challenge of this report against source (ledger in §9). Critique ledger rows are in §9.

### 7.10 Migration dependency roadmap (candidates only; none authorized)

| Package | Operator outcome | Predecessor | Primary source boundary | Key risks | Acceptance evidence | Effort (INF) | Class |
|---|---|---|---|---|---|---|---|
| M1 Toolkit-neutral seam | No visible change; Tk faster to test | Owner choice; none technically | `ui_dispatcher`, `AppStateV2` invoker, `graceful_exit` split, `content_visibility` move, all seven controller Tk-variable sites (reads and writes) moved to `AppStateV2`, controller GUI-import ratchet down plus a no-tkinter-closure check | Broad touch of `AppController`; decision 11 overlap | Tk suite green; `controller_gui_imports` strictly lower; no ceiling raised; Windows lane green | 3–5 packages | Architectural |
| M1b Isolated Qt compatibility proof | Evidence only | Explicit install authorization | Throwaway venv outside StableNew; synthetic data | None to production | Import/`QApplication` open-close, queued-signal delivery, stale-callback rejection, model/view of fake queue, stable-ID navigation, measured startup/idle | 1 small package | Narrow |
| M2 Qt shell + dispatch + shutdown parity | Opt-in launcher shows shell and readiness | M1 **and owner decision 11 (composition root, P3-2)** | New `src/gui_qt/` (or similar) host only | Dual-host drift | Startup/shutdown parity checklist; no second authority; Tk default unchanged | 3–4 | Architectural |
| M3 Read-only projections | Queue/History/Logs in Qt | M2 | Item models over projections | Event-rate overload | Latency under synthetic load | 3–4 | Standard |
| M4 Create (Prompt/Pipeline) | Authoring parity | M3 | Prompt/Pipeline tabs | Effective-settings equality | Preview/admission equality tests | 8–12 | Architectural |
| M5 Edit (Review, Photo Optimize) | Image editing | M4 | Canvas editors | Pixel-identity, content visibility | Mask/outpaint pixel tests | 8–12 | Architectural |
| M6 Motion | Video flows | M4 | Video panels, contained decode | Playback ownership | Bounded playback tests | 6–9 | Standard |
| M7 Learn | Learning | M5 | Learning tab, controllers | Evidence correctness | Draft/resume parity | 6–8 | Architectural |
| M8 Packaging, CI lanes, cutover | Qt default | All | Bootstrap, constraints, CI | Licence, rollback | Dry-run RC, rollback trigger, Windows lane | 3–5 | Architectural |

Total ≈ 40–60 bounded packages (INF, extrapolated from the tranche's 5–12M cache-read tokens per PR; not measured). Rollback is Tk remaining the default entry until M8.

### 7.11 Decision and next bounded package

Decision gates (package §9) applied: GO requires a bounded separation strategy plus a verified compatible path and no showstopper. **Not met:** runtime compatibility is unverified, the composition-root decision is open, the licence file is unresolved, and the benefit is unmeasured. CONDITIONAL GO would require naming an exact proof; that proof exists (M1b) but would continue spending effort on a migration whose benefit is not demonstrated. NO-GO/DEFER criteria "Tk modernization provides a demonstrably better near-term path" is met by the in-flight tranche.

**Recommended next package:** the already sequenced GUI tranche (GUI-UX-500…600), plus **one** owner-authorized architectural package "GUI-SEAM-700" that does only the no-regret subset of M1 for Tk's own benefit (move the dispatcher/invoker Protocols and `content_visibility` out of `src/gui`; replace **all seven** controller Tk-variable sites, reads and writes, with `AppStateV2` fields (reads alone would leave two sources of truth); add `invoke_later` to the dispatcher Protocol and settle a single invoker owner; guard `graceful_exit`'s `AppController` import with `TYPE_CHECKING` and split the host close; replace the raw `controller_gui_imports` count with a no-tkinter-in-import-closure check for non-gui layers). Invoker ownership borders the composition root, so that part waits on owner decision 11; the rest is independent of it.

**Reopen Qt only if:** (1) a measured, reproducible Tk limit on a named surface (e.g. virtualized gallery frame time, frame-accurate scrubbing) survives a Tk prototype; (2) GUI-SEAM-700 lands with ratchets lowered; (3) owner decisions on LICENSE, distribution form and the composition root are made; (4) M1b passes on the target machine.

**Optional alternative if the owner overrides:** authorize M1b first (isolated proof), then M1.

## 8. Acceptance checklist

| Criterion | Status |
|---|---|
| A. Repository truth: branch/SHA/worktree recorded; policies read; PR #2 classified; no old plan treated as authority | Met |
| B. Python 3.14/Windows compatibility sourced | Met at metadata level (E16-E18); **runtime unverified** |
| B. Controller/Tk/dispatcher dependencies mapped; boundary proposed; no duplicate owner proposed | Met |
| B. Normal workflow traced; shutdown chain analysed | Met (E8, E9) |
| C. All workspaces inventoried; persistence risks named; image/media/Learning risks identified; future parity tests defined | Met (§7.6) |
| D. Licensing analysed with unresolved obligations; packaging assessed; hardware considered | Met; counsel review outstanding |
| D. Runtime experiments distinguished; no generation or backend restart | Met (no runtime experiments) |
| E. Tk comparison, independent challenge, explicit gates, uncertainty, bounded next package | Met |
| F. No production behaviour/dependency/user-data change, no controller ceiling raised | Met (single new doc) |
| F. Validation | Docs-only path; see completion report |
| **Not met by design / blocker:** isolated Qt proof | Not run: PySide6 absent and installation not authorized |

## 9. Critique ledger and repair record

One independent read-only critique subagent (AST import graph that skips `TYPE_CHECKING`, AST scan of non-gui layers for Tk-object use, ratchet-source reading). No showstopper and no missed reason for GO. One repair pass applied.

| Critique | Verdict | Consequence / action |
|---|---|---|
| `graceful_exit` controller half is toolkit-free | **Refuted** | Imports `AppController` at runtime (pulls tkinter); fixed in §5/§6; remedy is a `TYPE_CHECKING` guard |
| Seam package fixing Tk-var reads only is safe | Partial (blocking in scope) | Seven controller sites read/write Tk vars; package re-scoped in §7.11 |
| M2 predecessor is M1 only | Partial (blocking in scope) | Owner decision 11 added as M2 gate (§7.10) |
| `UiDispatcher` already reusable | Partial | Needs `invoke_later` and a single invoker owner; dual pumps documented (§6) |
| Ratchet gate is meaningful | Partial | Counts only controller to `src.gui`; closure check proposed (§7.4) |
| `core_pipeline_controller` is a blocker | Partial | `TYPE_CHECKING` only; corrected |
| E1 "physical lines" | Partial | Relabelled non-blank; physical counts added |
| E5 `getattr` count 40 | Partial | 45 lines; corrected |
| 2.0 s shutdown bound | Partial | Bounds only the post-`shutdown_app` poll; corrected (§7.3) |
| 64 real-Tk-root tests | Unverified | Method-dependent; restated (E12) |
| Tk suite GC disable (Tcl_AsyncDelete) | Future hardening | Added to M1b / §7.8 |
| Confirmed | n/a | Tk confined to `src/gui`/`main`/`app_factory`; `view_contracts` 33 modules/6,702 lines; `gui_v2` 25/4,331; ratchet values; file sizes; shutdown order; layers below the controller are Tk-free; LICENSE absent; decisions 1 and 11 open |

Decision effect: none; every finding enlarges the seam work rather than strengthening the case for Qt. Repair budget used: one batched pass.

## 10. Review quality

Audit method diversity: entrypoint trace (E7), submit trace (E8), shutdown trace (E9), CI per-job inspection, import-graph counts, UI-binding counts. Negative tests performed: none executable (no runtime). Exact-source evidence: SHA `40946733`. Privileged GitHub settings: not inspected. Real operator data: none. Uninspected high-risk subsystems: per-widget behaviour of Review mask editor and Learning grid, content-visibility call sites, `ErrorModalV2` lifecycle, persisted `ui_state.json` schema. Hardware/Windows gaps: no Qt execution; no startup/idle/DPI measurements. Disconfirming tests for the NO-GO: a measured Tk limit on a named surface; M1b results showing Qt shell cost and lifecycle parity are cheap; owner licence decisions. Framework amendments: none.

## 11. Evidence links

Source: `https://github.com/destroyer42/StableNew2/tree/40946733afbd3d4a6f0158d7e51777261e166a36`. PR #2 merged 2026-03-10. CI run 40203933054. PyPI: `PySide6`, `PySide6_Essentials`, `PySide6_Addons`, `shiboken6` (JSON metadata fetched 2026-10-25). Qt: Qt for Python 6.12 release blog; `doc.qt.io/qt-6/threads-qobject.html`, `highdpi.html`, `accessible.html`, `qtmultimedia-index.html`; `qt.io/development/open-source-lgpl-obligations`; Qt WebEngine licensing page; `doc.qt.io/qtforpython-6/deployment/deployment-pyside6-deploy.html`. Repository: `docs/audits/2026-10-16_repo_audit_and_roadmap.md` D3/D7/D11; `docs/audits/2026-10-22_gui_ux_audit_and_tranche.md`.
