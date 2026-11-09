# StableNew — Independent Qt Widgets Prototype Assessment (v0.3)

**Status:** Source-maintainable, isolated prototype candidate; **not** an integrated StableNew branch/PR, not production code, not a qualified Qt migration. Prepared against remote `destroyer42/StableNew2` `main` **`fc644705b0d2428d1a258bc820ae7b214ffe4469`** (2026-11-08). Independent of Figma; no license, API call, asset export or runtime service is required.

**v0.3 adds the Output Display** — a dock to the right of the workspace; see "Output Display" below.

**v0.2 changes (owner request + first Windows run):** blue theme and rounded geometry; fixes for every defect found in the first Windows run; richer Create workflow. See `docs/ASSESSMENT.md` for evidence and `docs/screenshots/` for real-platform captures.

## What is provided

- `stablenew_qt_proto/tokens.py` — blue palette, radius/spacing tokens, WCAG contrast helper with asserted pairs, and the Qt stylesheet. Plain widgets are transparent (no dark patches inside cards); every control keeps a constant 2px border so focus never shifts layout.
- `stablenew_qt_proto/assets/*.svg` — four static glyphs (spin arrows, combo chevron, checkmark) referenced by the stylesheet. No runtime file writes.
- `stablenew_qt_proto/components.py` — `SectionCard`, `NoticeBanner` (info/warning/blocked/success), `StatusChip`, `IssueList`, `Disclosure`, `ActionStrip`, `ResponsiveGrid`, `SettingField`, `stacked_label`, and a wheel guard so scrolling the form never silently changes a spin box or combo.
- `stablenew_qt_proto/gallery.py` — executable component catalog including theme swatches and computed contrast ratios.
- `stablenew_qt_proto/create_view.py` — the mock Create workflow (below).
- `stablenew_qt_proto/output_display.py` / `output_model.py` — the Output Display dock and its pure (Qt-free) zoom/size-mode/frame model.
- `stablenew_qt_proto/domain.py` — dependency-free, deterministic, in-memory draft/preview model with explicit **unqualified fixtures**.
- `stablenew_qt_proto/app.py` — isolated app with Create and Component Library routes; no StableNew imports.
- `tools/capture.py` — writes layout PNGs and measurements to a directory you name.
- `tests/` — pure domain/theme/architecture tests plus opt-in Qt tests that show real windows and measure layout.

### Create workflow (v0.2)

- **PromptPack:** `{slot}` placeholders in the prompt resolve from an editable slot table (names and values); the preview shows template and resolved prompt; unresolved placeholders, unused slots and unusable slot names warn.
- **Settings:** sampler, scheduler, steps, CFG, width, height, **seed** (-1 = Random) and **batch**. Samplers/schedulers are closed lists; numeric limits are validated from one table shared with the editors.
- **Recommendations that mean something:** each setting shows its recommendation and `· differs` in words; **↺** returns one value to the recommendation; **Reset unlocked to recommended** returns the rest. Choosing *Learning-informed (fixture)* now actually proposes different values (steps/CFG), applied through the same lock/manual-protection rules as a model switch.
- **Size presets** come from the selected fixture's characterized sizes.
- **Locks and manual edits:** a manual edit equal to the recommendation stops counting as an override.
- **Undo/Redo** of draft state (typing coalesces into one step; reset is undoable, so no modal confirmation). Alt+Z / Alt+Y; Ctrl+Enter builds the preview; Ctrl+Shift+Enter simulates admission.
- **Change log:** every change with its revision, newest first, never wiped by later edits.
- **Review panel:** status chip (NOT BUILT / STALE / BLOCKED / CURRENT · READY), per-issue banners, mock result card; the panel scrolls independently.
- **Responsive:** the settings grid reflows 1–3 columns by width and never clips; the footer actions stay visible.

### Output Display (v0.3)

A dock to the right of the Create workspace. It shows a **placeholder frame** that follows the draft (size/aspect, resolved prompt, model, settings, preview state); it never shows a real image and says "No image generated".

- **Dock / undock:** **Undock** / **Dock** in its title bar (it may dock left or right, not bottom; dragging the title bar is Qt's native dock behaviour and is not covered by the automated tests).
- **Collapse:** title-bar arrow, the header **Output Display** button, or **Ctrl+3**. Docked it becomes a thin vertical rail and the workspace takes the space; floating it shrinks to its title bar.
- **Size modes** (segmented control in the panel):
  - **Free** – drag the edge to resize (minimum 300 px).
  - **Lock size** – freezes the docked width (or the floating window size) until you pick another mode.
  - **Fill** – docked, uses all width the workspace does not need and follows the window; floating, fills the screen.
- **Zoom:** − / + / slider (5%–1600%) / **100%** / **Fit** (re-fits on resize), Ctrl+wheel (at the pointer), drag to pan, double-click toggles Fit/100%; Ctrl+= / Ctrl+− / Ctrl+0 / Ctrl+9 while focus is inside the display.
- Trade-off: with the display open the minimum window width is 1192 px (944 px collapsed) and the Create form is narrower; collapse it while authoring.

**Not implemented:** real PromptPack grammar or Matrix expansion, production model discovery, real profiles or Learning evidence, actual NJR compilation, backend/model inspection, production submit, job lifecycle, output images, persistent save/autosave, integrated Library, or comprehensive Qt vs Tk qualification.

## Run on Windows with the existing Python 3.14 + PySide6 environment

The environment recorded by GUI-PORT-740 was **moved**: `C:\Users\rob\qual\gui-port740-env` no longer exists, but `C:\Users\rob\qual.__moved_to_D\gui-port740-env` runs (Python 3.14.9, PySide6 6.12.0, Qt 6.12.0 verified 2026-11-08). Reuse it; do not rebuild.

```powershell
$py = 'C:\Users\rob\qual.__moved_to_D\gui-port740-env\Scripts\python.exe'
& $py --version
& $py -I -c 'import PySide6; print(PySide6.__version__)'
```

From the extracted `StableNew_Qt_Prototype_Assessment` directory:

```powershell
& $py -m stablenew_qt_proto.app
```

**Do not install PySide6 into StableNew's production venv.**

## Tests

```powershell
& $py -m unittest discover -s tests -v                      # pure tests (Qt tests skip)
$env:STABLENEW_QT_PROTOTYPE_TEST = '1'
& $py -m unittest discover -s tests -v                      # + 42 Qt tests (shows windows briefly)
Remove-Item Env:STABLENEW_QT_PROTOTYPE_TEST
```

Add `$env:QT_QPA_PLATFORM='offscreen'` for headless runs. Offscreen has no fonts, so text renders as boxes and widths are not representative; use the native platform for layout evidence.

## Layout evidence

```powershell
& $py tools/capture.py --out captures --sizes 1280x680 1440x900 960x600
& $py tools/capture.py --out captures --sizes 1280x680 --scale 1.5
```

Prints form viewport/content size, settings columns and footer position, and saves top/middle/bottom/blocked/library PNGs plus `dock_*` PNGs of the Output Display (expanded, 100% zoom with a built preview, Fill, collapsed rail, floating, floating-collapsed). Windows under 1200 px wide are captured with the display collapsed. `docs/screenshots/` holds the captures from this release.

## Guided manual mock journey

1. **Create Image:** edit the Pack name, prompt and a slot value. Rename a slot and watch `{subject}` become unresolved.
2. **Build mock preview** (or Ctrl+Enter). Read the resolved prompt and the status chip.
3. Change **Steps**: the chip turns **STALE** and **Simulate admission** disables; its field shows `· differs`. Click **↺** to restore it.
4. Lock **Steps**, switch to the Flux fixture: the value is kept, the negative prompt blocks the preview (never silently dropped), and the change log explains both.
5. Clear the negative prompt, rebuild, **Simulate admission**: the result card states **No job submitted and no image generated**.
6. Try **Undo/Redo** (Alt+Z/Alt+Y), **Reset demo draft**, then Undo to restore it.
7. Open **Component Library** to inspect components, theme swatches and contrast ratios.

## Architectural limits

The future production path must remain `Intent → Compiler → immutable NJR → JobService → SQLite Queue/Repository → PipelineRunner.run_njr → Artifacts/History`. This prototype has no runtime, compiler, queue, SQLite, artifact, cancellation, process manager or History implementation. `DemoReceipt` is an ephemeral text-only UI result, **not** a mock authority. Undo history and the change log live in memory only. It does not import production `src` modules.

## Design provenance

The optional visual reference is Figma **StableNew — PySide6 UX Prototype, Concept A**, file `7WvTcu0dxFQN7ZBiZZI8us`. The blue theme is an owner request for this prototype and is **not** Concept A's palette; no pixel parity is claimed and the Figma file was not revalidated.

Merged UX-850 sources from remote `main` at the above SHA:

- [UX-850-B J1 Create journey](https://github.com/destroyer42/StableNew2/blob/fc644705b0d2428d1a258bc820ae7b214ffe4469/docs/research/stablenew-experience/ux850-b/JOURNEYS.md)
- [UX-850-C component roles](https://github.com/destroyer42/StableNew2/blob/fc644705b0d2428d1a258bc820ae7b214ffe4469/docs/research/stablenew-experience/ux850-c/COMPONENTS.md)
- [UX-850-C token roles](https://github.com/destroyer42/StableNew2/blob/fc644705b0d2428d1a258bc820ae7b214ffe4469/docs/research/stablenew-experience/ux850-c/TOKENS.md)
- [UX-850-D state authority](https://github.com/destroyer42/StableNew2/blob/fc644705b0d2428d1a258bc820ae7b214ffe4469/docs/research/stablenew-experience/ux850-d/README.md)
- [UX-850-E Learning feasibility](https://github.com/destroyer42/StableNew2/blob/fc644705b0d2428d1a258bc820ae7b214ffe4469/docs/research/stablenew-experience/ux850-e/README.md)
- [UX-850-F delivery program](https://github.com/destroyer42/StableNew2/blob/fc644705b0d2428d1a258bc820ae7b214ffe4469/docs/research/stablenew-experience/ux850-f/README.md)
- [All 73 confirmed owner decisions](https://github.com/destroyer42/StableNew2/blob/fc644705b0d2428d1a258bc820ae7b214ffe4469/docs/research/stablenew-experience/ux-850-r1/OWNER_DECISIONS.md)

## Development boundary

`AGENTS.md`, current `STATUS.md` and the merged UX-850 research have priority over this standalone artifact. The research does not authorize a full Qt migration. GUI-PORT-742's prior result was **NO-GO** on comparative operator-benefit evidence; a prototype can inform a new decision but does not retroactively overturn that verdict.

Do not copy this package into production `src` as a second runtime design system. A future Qt host package must reconcile existing `src/gui_v2/design_values.py` and toolkit-neutral state, existing Qt proof seams, Windows accessibility/DPI, startup/memory and PySide6 packaging/licensing.

No push, PR, merge, production changes, backend calls or physical execution were performed for this artifact.
