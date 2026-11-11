# Bounded assessment: Qt Widgets design workspace (QT-DS-01, v0.4)

## Verdict

**RUNS ON WINDOWS; TESTED; DESIGN EVIDENCE ONLY.** The imported v0.3.0 prototype now has a
validated, editable theme library with a Theme Studio, a richer mock Create workflow in two layouts,
and measured layout evidence. It does not show that Qt Widgets is better for StableNew operators and
does not reverse GUI-PORT-742's NO-GO on operator benefit. No production file, setting, dependency,
branch or queue was touched; nothing was pushed.

Repository evidence cut: branch `feature/qt-ds-01-design-foundation` from `main` `5348745f`.

## Evidence

Run on Windows 11, Python 3.14.9, PySide6 6.12.0 (existing `gui-port740-env`), ASUS VG32VQ1B
2560×1440 at 100% (96 DPI), native `windows` Qt platform.

| Evidence | Result |
|---|---|
| Independent baseline of the imported source (before any edit) | 129 tests (87 pure + 42 Qt) passed on a scratch copy; the source's own "89 tests" claim was not used |
| Full workspace suite now | **270 tests pass natively** (174 pure + 96 opt-in Qt); without Qt the 96 skip |
| Repository guard | `tests/system/test_qt_design_workspace.py` (4 tests): pure suite passes in the Qt-free production venv; `src/` and the workspace never reference each other; no production settings authority |
| Lint | repository `ruff format --check` and `ruff check` clean on `design/qt_widgets` |
| Layout audit | 64 native/simulated cases: 0 unreachable controls, 0 horizontal overflow, 0 Tab-chain gaps, 0 focus out of view (`evidence/`) |
| Screenshots | 40 native PNGs in `screenshots/qt-ds-01/` (both layouts, 1280×680 and 960×600 stress, both themes, Theme Studio edited / preview / contrast-blocked, simulated result, blocked preview); the v0.3 captures remain in `screenshots/` |

## Demonstrated (by tests and measurement on this machine)

- **Theme contract:** strict versioned JSON validation, canonical form and fingerprint, density,
  20 contrast checks; both reference presets pass; the blue preset reproduces the v0.3 palette
  byte-for-byte (hash-pinned). No hex/RGB/QColor/font literal exists in widget code (static test).
- **Theme Studio:** edits colours, typography, spacing/density, borders/radius and state roles with a
  live preview and a forced state matrix whose edge pixels are asserted; invalid values and failing
  contrast block Apply/Save/Export; revert/reset; Save As (atomic, overwrite confirmed), restore in a
  new library instance, Export/Import with errors surfaced, immutable references, plain-text rendering
  of untrusted names.
- **Applying a theme** restyles the app and rebuilds the Create view while the draft session, undo
  history and layout choice survive; no Qt stylesheet warnings in either theme.
- **Create workflow (mock):** fixture packs with slots and a resolved prompt; model/profile switching
  with lock > manual > recommendation precedence; basic vs advanced settings with a header that names
  hidden differences; stale reasons by field; refusal of stale/invalid/never-built preview; simulated
  admission with placeholder tiles equal to batch; undoable reset; Tab is not trapped; focus is
  scrolled into view.
- **Layouts:** both designs reachable and unclipped at 1280×680 and at the 960×600 stress case (display
  collapsed). See [LAYOUT_EVALUATION](LAYOUT_EVALUATION.md).
- **Independence:** the pure flow runs in an isolated interpreter with `src`, Tk, SQLite, `requests`,
  sockets and subprocesses blocked; the Qt flow runs with sockets/subprocess patched to fail.

## Simulated or reconstructed (not real)

- All models, profiles, recommendations, packs and "Learning-informed" values are invented fixtures.
- Simulated admission: a text acknowledgement and placeholder tiles; no job, NJR, queue row, artifact or image.
- **Concept A** is reconstructed from `TOKENS.md` role values. Role provenance is recorded in the
  preset. It is **not** verified against the Figma file (no Figma connector was authorized).
- The 1.5× scale audit is `QT_SCALE_FACTOR` emulation, not a Windows 150% display.

## Unverified

- Operator benefit, task time, error rate; any comparison against the Tk Create screen.
- Real per-monitor 125/150%/mixed-DPI scaling; other displays and Windows font settings.
- Screen readers (Narrator/NVDA), UI Automation, High Contrast / forced colours. Accessible names exist
  and the Tab walk is measured; announcement is not.
- Dragging the Output Display's title bar to float/dock, multi-monitor Fill, and combo popup corners
  (native popups stay square).
- Startup time, memory, PySide6 packaging and licensing; any production integration.
- Behaviour of hand-edited themes with unusual fonts that are not installed (falls back to the system
  font).

## Known limitations of this workspace

1. Spacing is read when widgets are built, so applying a spacing/density change rebuilds the Create view
   (state is preserved). A production Qt host would need an explicit reflow strategy.
2. At 1280×680 with the Output Display open, the form is ~6 screens tall, the split design's review pane
   is only ~230 px wide, and chrome is 41% of the window height. Neither layout is comfortable yet.
3. Remembering the applied theme writes `active-theme.json` into the git-ignored `user_themes/` folder;
   Save As/Export write only where the operator asks.
4. The theme system is a workspace artifact. It is **not** a second production theme and does not
   reconcile `src/gui_v2/design_values.py` or toolkit-neutral state.
5. The dock's "Fill" mode is re-applied on window resize, not continuously; Output Display state does not
   persist across launches.

## Output Display (v0.3, retained)

A `QDockWidget` right of the workspace showing a placeholder frame driven by the draft (size/aspect,
resolved prompt, model, settings, preview state; always "No image generated"). It docks left/right,
undocks, collapses to a 56 px rail (Ctrl+3), and has Free / Lock size / Fill sizing and zoom
(5%–1600%, Fit, wheel, pan). It reads no artifacts or History. Cost: expanded, it raises the minimum
window width to 1192 px (944 px collapsed). Its automated tests are unchanged apart from window disposal.

## Recommendation for QT-DS-02

Treat this as a design baseline, not an adoption step. Next, in priority order: (1) widen the review pane and
cut chrome so the split layout is usable at 1280×680 (fold the Output Display into the review pane or share the right
column), then re-run `tools/layout_audit.py`; (2) have the owner review the live app and screenshots, and verify
Concept A against Figma if its fidelity matters; (3) run real 125/150% scaling and a Narrator pass;
(4) only then consider an operator task comparison with Tk. A production Qt host still needs its own
architecture decision (owner of design values, startup, packaging).

No publication, protected action or physical runtime authorization was inferred.
