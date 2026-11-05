# Qt licensing, module and packaging assessment (research, partial)

**Status: PARTIAL, desk and file-system inspection only, 2026-11-05.** This is a prerequisite for any comparative prototype (DR-A26, O15). It is **not legal advice** and **not a packaging test**: nothing was installed, built, bundled, signed or distributed, and no Qt code was run except importing `PySide6`/`QtCore` to read version strings. Every item below is labelled **Measured** (read from the existing environment this session), **Prior** (from an earlier assessment) or **Unavailable** (not measured; needs the stated work).

Environment inspected: `C:\Users\rob\qual\gui-port740-env`, Python 3.14.9, outside every checkout, created for GUI-PORT-740/742.

## 1. What is installed (Measured)

| Distribution | Version | Declared license expression (package metadata) |
|---|---|---|
| `PySide6`, `PySide6_Essentials`, `PySide6_Addons`, `shiboken6` | 6.12.0 | `LGPL-3.0-only OR GPL-2.0-only OR GPL-3.0-only` |
| `PySide6_WebEngine`, `PySide6_PDF` (the add-on wheels) | 6.12.0.140 | same expression |
| Each of the above ships `licenses\LicenseRef-Qt-Commercial.txt` | | a **commercial** license option is also referenced |
| Pillow (used here only for pixel measurement) | 12.3.0 | `MIT-CMU` |

The environment also holds `cv2` and `numpy` (≈ 163 MiB), which are unrelated to Qt and out of scope.

## 2. Which Qt modules were actually used (Measured, from the repository)

The GUI-PORT-740 hermetic test (`tests/tools/test_gui_port_740.py`, lines 86–89) restricts the proof package's Qt imports to `PySide6.QtCore` and `from PySide6 import QtCore, QtGui, QtWidgets`. So the 740/742 proof exercised **QtCore, QtGui and QtWidgets only**; WebEngine, PDF, QML/Quick and Multimedia were **never** used by any StableNew proof. (A Prior statement: 742 also used the Windows UI Automation probe from outside Qt.) `git grep -i pyside` over `requirements.txt`, `requirements-dev.txt`, `requirements-postprocess.txt`, `requirements-svd.txt` and `pyproject.toml` finds nothing, and `src/` has no PySide6 reference; the only repository mentions are the hermetic proof tests (`tests/tools/test_gui_port_740.py`, `test_gui_port_742.py`).

## 3. On-disk footprint (Measured file sizes; **not** installer size)

| Item | MiB | Note |
|---|---|---|
| Whole `PySide6` package directory | 647.1 | what a naive install brings |
| Total environment `site-packages` | 845.1 | includes cv2/numpy/Pillow/pip |
| `Qt6WebEngineCore.dll` + other WebEngine files | 196.7 | + `resources` 101.4 MiB (Chromium resources) |
| PDF module files | 5.5 | |
| `translations` | 59.3 | Qt's own translations |
| `opengl32sw.dll` (software OpenGL) | 19.7 | optional fallback |
| `avcodec-63.dll` (FFmpeg, shipped with Qt Multimedia) | 13.5 | license depends on the FFmpeg build; **not inspected** |
| **Widgets-only core** (Qt6Core/Gui/Widgets, QtCore/QtGui/QtWidgets `.pyd`, `pyside6.abi3.dll`, shiboken6, `opengl32sw.dll`, Qt6Svg) | **≈ 58.2** | plus `plugins/platforms/qwindows.dll` ≈ 1 MiB, `styles` ≈ 0.2, `imageformats` ≈ 2; the figure includes the 19.7 MiB software-OpenGL DLL, which may be omitted if never needed |
| **Tk runtime of the current Python 3.14.9** (`tcl90.dll` 3.21 + `tcl9tk90.dll` 2.04 + `_tkinter.pyd` 0.07 + `tcl` 2.81 + `Lib/tkinter` 0.69) | **≈ 8.8** | Tcl/Tk 9.0 |

Reading: a Widgets-only Qt subset is on the order of **6–7× the Tk runtime on disk** (≈ 38 MiB if software OpenGL is dropped), while the full package is ≈ 70×. Whether an application can ship the subset depends on a packaging tool's pruning (**Unavailable**: no packaging was attempted). The figures are file sizes from one pip installation, not a compressed installer.

## 4. Licensing findings and obligations (desk review; counsel/owner must confirm)

- **Declared options.** The metadata offers LGPL-3.0, GPL-2.0, GPL-3.0 **or** a Qt commercial license. Which option StableNew would use is **undecided**.
- **Repository license.** The study documents record that the repository `LICENSE` and distribution form are unresolved (`STATUS.md` decision 1, as cited in GUI-QT-001 and GUI-PORT-742). Until that is decided, no Qt redistribution choice can be made.
- **What the LGPL path typically involves (general knowledge, unverified for this project):** shipping license texts and notices, allowing the end user to replace the Qt libraries (which favors dynamic linking and a layout that keeps Qt as separate, replaceable DLLs), and not imposing terms that forbid reverse engineering for debugging such replacement. A GPL path would impose copyleft on the whole application. A commercial license changes cost, not technical packaging. **These are the questions to put to counsel**, not conclusions.
- **Bundled third-party components.** The WebEngine/Chromium and FFmpeg files carry their own licenses (BSD-style and other terms; FFmpeg may be LGPL or GPL depending on build). **Not inspected here.** The owner's instruction to "avoid bundling unused heavyweight modules" removes most of this surface: the Widgets-only subset needs none of WebEngine, PDF, Multimedia/FFmpeg or QML.
- **Qt modules the Widgets path pulls in** (QtCore, QtGui, QtWidgets, optional QtSvg and image-format plugins) must still be listed individually for the notices file. **Unavailable:** an authoritative per-module license table (requires reading each shipped `licenses` file and the Qt notice for the exact version).

## 5. Packaging constraints from the owner (O15) and what is known

| Constraint | Status |
|---|---|
| Windows desktop | Met by PySide6 (Measured: runs on this Windows host) |
| Compatible with the supported Python 3.14 environment | **Measured:** PySide6/Qt 6.12.0 imports on Python 3.14.9 |
| Offline-capable | Plausible (no network service is required by QtCore/Gui/Widgets); **not tested**; WebEngine would be the network-heavy module and is excluded by the Widgets-only rule |
| No administrator-required runtime installation | **Unavailable:** the per-user pip layout in this env needed no admin (it was created by a standard user), but a distributable installer, VC++ runtime requirements and a code-signing path were not tested |
| No unnecessary network services | Meets the Widgets-only subset by construction; **not verified** by a packet or socket capture |

## 6. Measurements the owner asked for, and their availability

| Measure (against Tk) | Value today | Source / what is missing |
|---|---|---|
| Installer size | **Unavailable** | needs a packaged build of a minimal Qt app and of the Tk app; on-disk sizes above are only an upper-bound proxy |
| Cold-start latency | Prior: +87 ms (Qt vs Tk) on one read-only Job History workspace, n = 5 (GUI-PORT-742) | not measured for a real shell or for a cold file cache; not re-run |
| Memory | Prior: +34 MiB idle, +79 MiB peak (742) | same limitation |
| Rendering responsiveness | Prior: filter −2.3 ms, selection −1.0 ms, refresh −18 ms; 96.7% of the burst gap was dispatcher policy (742); **no gallery/preview rendering measured** | needs the comparative prototypes' gallery and media-inspection screens |
| Dependency complexity | Measured partially: the proof needed 3 Qt modules plus shiboken6 | a full dependency/ratchet impact (the repo has 140 Tk-importing files) was not costed |
| Licensing/redistribution obligations | Section 4 (desk review only) | counsel/owner review; per-module table |

## 7. Implications

1. A **Widgets-only** PySide6 subset is the only configuration this research should consider for COA B; WebEngine, PDF, Multimedia and QML are excluded unless a measured need appears.
2. The environment that was reused is a full wheel set; any prototype should either use only the three imported modules from it or a pruned copy, and record which files it actually loaded.
3. The licensing choice (LGPL vs commercial vs GPL) and the repository `LICENSE` decision are **owner decisions** that gate any Qt redistribution, but not a research-only measurement inside the environment.
4. Installer size, cold start and memory for a *product-like* shell remain unmeasured; the figures above must not be presented as such.
