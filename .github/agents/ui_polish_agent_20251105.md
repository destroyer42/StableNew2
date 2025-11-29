---
Name: UI Polish – Tk Facelift & Theming
Description: Gui enhancements/modernization
---
Modernize the Tkinter UI (rounded, consistent spacing, dark/light themes, better resizing) using ttkbootstrap, without altering business logic or pipelines.

Scope / Files

Add:

src/gui/theme.py (design tokens + theme manager)

src/gui/dialogs.py (messagebox/file dialog wrappers; headless-safe)

src/utils/settings.py (JSON load/save for theme/density/window)

tests/gui/conftest.py (shared tk_root, tk_pump, dialog stubs)

Modify (visual only, no behavior changes):

src/gui/main_window.py (apply theme; menu: View→Theme/Density; minsize/grid weights; persist geometry)

src/gui/log_panel.py (INFO/WARN/ERROR filters; export; spacing)

src/gui/prompt_pack_list_manager.py (ttk widgets; spacing)

src/gui/enhanced_slider.py (ttk styling/padding)

requirements.txt (+ ttkbootstrap>=1.10)

Guardrails

Tk main thread non-blocking (no join() in GUI/tests).

Headless-safe tests (skip gracefully if Tcl/Tk/display missing).

Keep changes visual; no pipeline/default-params changes.

Use package imports (e.g., from src.gui.theme import theme), no sys.path hacks.

Test & Validate (must pass in CI)

Commands:

pre-commit run --all-files

pytest --cov=src --cov-report=term-missing -q

Focused:

pytest tests\gui\test_theme_applies.py -q

pytest tests\gui\test_logpanel_filters.py -q

pytest tests\gui\test_settings_persist.py -q

pytest tests\gui\test_dialog_wrappers.py -q

New tests to add:

tests/gui/test_theme_applies.py – theme loads; density toggle updates padding.

tests/gui/test_logpanel_filters.py – feed INFO/WARN/ERROR; toggle filters; assert visible text.

tests/gui/test_settings_persist.py – save/load window size/pos (use tmp_path).

tests/gui/test_dialog_wrappers.py – dialog wrappers are patchable/no-op in headless.

tests/gui/conftest.py – tk_root (yield root/destroy), tk_pump, dialog stubs.

Implementation Checklist

Theme & tokens (src/gui/theme.py):

ttkbootstrap.Style() with default dark “cyborg” + light “flatly”

Tokens: spacing (XS=4, S=8, M=12, L=16, XL=24), radius (S=6, M=10), fonts (base 11–12pt, mono for logs)

Density presets: compact / comfortable

Helper: pad(s) → {'padx': s, 'pady': s}

Resizing & layout:

Sensible minsize, grid_*configure(..., weight=1) where panels must grow

Normalize paddings to tokens

Widgets:

Prefer ttk.*; use themed ttk.Separator; rounded corners where available

Menu:

View → Theme (dark/light)

View → Density (compact|comfortable) → re-layout

LogPanel:

Level filters (INFO/WARN/ERROR) without losing raw buffer (keep raw + view)

Export current view to ./logs/session_<ts>.log (or asksaveasfilename via wrapper)

Settings:

settings.json under ./settings/ (create on first run)

Keys: theme.name, ui.density, window.size, window.position

src/utils/settings.py with load_settings()/save_settings()

Dialog helpers (src/gui/dialogs.py):

Thin wrappers around messagebox/file dialogs; no-op in headless; easily monkeypatched

PR Rules

Base: origin/postGemini → Feature: ui/ttkbootstrap-facelift → PR target: postGemini

Use repo PR template; attach dark/light screenshots

Conventional commits:

feat(gui): add ttkbootstrap theme manager and design tokens

feat(gui): resizable layouts with normalized spacing

feat(logpanel): level filters and export

feat(settings): persist theme/density/window geometry

test(gui): headless fixtures and GUI assertions

chore(deps): add ttkbootstrap

Out of Scope

Pipeline/business-logic changes

Qt/PySide migration

Deep prompt-editor behavioral changes (visual restyle only)

Default parameter changes

Definition of Done

Modern theme applied; panels resize smoothly

Theme & density switchable at runtime and persist across restarts

LogPanel filters by level; export works headless

GUI tests run headless in CI with real assertions

pre-commit + coverage gates pass

Rollback

Revert PR ui/ttkbootstrap-facelift; remove new deps/files

Keep test fixtures (safe)

(Optional) One-time dependency note

Add ttkbootstrap>=1.10 to requirements.txt

If CI needs a display for legacy tests, ensure your workflow starts Xvfb before pytest
