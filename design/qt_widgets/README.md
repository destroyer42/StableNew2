# StableNew — Qt Widgets design workspace (QT-DS-01, v0.4)

A permanent, source-maintained place to prototype and compare **Qt Widgets** components, themes and
layouts for StableNew. It is a **design aid**: not production code, not an integrated StableNew
branch, not a qualified Qt migration, and not a toolkit decision.

Authority: `AGENTS.md` and `STATUS.md` win over this directory. The UX research that motivates the
prototype lives in [`docs/research/stablenew-experience/`](../../docs/research/stablenew-experience/README.md)
and is **not** duplicated here; this workspace only links to it:

- [UX-850-B J1 Create journey](../../docs/research/stablenew-experience/ux850-b/JOURNEYS.md)
- [UX-850-C component roles](../../docs/research/stablenew-experience/ux850-c/COMPONENTS.md) and
  [token roles](../../docs/research/stablenew-experience/ux850-c/TOKENS.md)
- [UX-850-D state authority](../../docs/research/stablenew-experience/ux850-d/README.md)
- [UX-850-E Learning feasibility](../../docs/research/stablenew-experience/ux850-e/README.md) and
  [UX-850-F delivery program](../../docs/research/stablenew-experience/ux850-f/README.md)
- [Owner decisions](../../docs/research/stablenew-experience/ux-850-r1/OWNER_DECISIONS.md)

## What is here

| Path | Purpose |
|---|---|
| `stablenew_qt_proto/theme.py` | Pure (no Qt) versioned theme contract: strict validation, contrast checks, density, editor, stylesheet builder |
| `stablenew_qt_proto/themes/*.theme.json` | Two immutable reference presets: `blue-modern` (the migrated v0.3 look) and `concept-a` (reconstructed, **not** Figma-verified) |
| `stablenew_qt_proto/theme_store.py` | User theme library (atomic Save As, Export, Import, remembered active theme) |
| `stablenew_qt_proto/theme_studio.py`, `gallery.py` | Component library page + **Theme Studio** (live preview, state matrix, contrast diagnostics) |
| `stablenew_qt_proto/components.py`, `create_view.py`, `output_display.py` | Reusable components, the mock Create workflow (two layouts), the Output Display dock |
| `stablenew_qt_proto/domain.py`, `output_model.py` | Pure in-memory mock domain (fixtures, recommendations, locks, preview freshness) |
| `stablenew_qt_proto/layout_probe.py`, `tools/layout_audit.py`, `tools/capture.py` | Deterministic layout measurement, evidence tables, screenshots |
| `tests/` | Pure tests plus opt-in native Qt tests |
| `docs/` | [WALKTHROUGH](docs/WALKTHROUGH.md), [LAYOUT_EVALUATION](docs/LAYOUT_EVALUATION.md), [THEME_CONTRACT](docs/THEME_CONTRACT.md), [ASSESSMENT](docs/ASSESSMENT.md) (demonstrated vs unverified), [TRACEABILITY](docs/TRACEABILITY.md), [IMPORT_RECORD](docs/IMPORT_RECORD.md), `evidence/`, `screenshots/` |

`SOURCE_IMPORT_MANIFEST.sha256` records the exact bytes of the imported v0.3.0 prototype (see
[IMPORT_RECORD](docs/IMPORT_RECORD.md)).

## Boundaries (enforced by tests)

- No import of `src/`, Tk, the compiler, `JobService`, the SQLite queue, `PipelineRunner`, History,
  network or subprocess APIs. The Create workflow is a simulation: it never dispatches a job and
  its receipt is a text acknowledgement with placeholder tiles, **not** a mock authority.
- The workspace theme is **not** a second production theme. It never reads or writes
  `presets/settings.json`, `src/gui_v2/design_values.py` or any Tk value. Production Qt adoption
  would still have to reconcile those owners.
- User themes are written only by explicit Save As / Export / Apply (remembered theme) into
  `user_themes/` (git-ignored; override with `STABLENEW_QT_PROTO_THEME_DIR`). Shipped presets are read-only.
- **Never install PySide6 into StableNew's production venv.** The repository test
  `tests/system/test_qt_design_workspace.py` runs the Qt-free part of this suite in the normal
  environment and fails if the application and the workspace reference each other.

## Run (Windows, existing Python 3.14 + PySide6 6.12 environment)

```powershell
$py = 'C:\Users\rob\qual.__moved_to_D\gui-port740-env\Scripts\python.exe'   # reuse; do not rebuild
cd design\qt_widgets
& $py -m stablenew_qt_proto.app                    # remembered theme, split Create layout
& $py -m stablenew_qt_proto.app --theme concept-a --layout scroll
```

## Test

```powershell
& $py -m unittest discover -s tests                # pure tests (Qt tests skip)
$env:STABLENEW_QT_PROTOTYPE_TEST = '1'
& $py -m unittest discover -s tests                # + native Qt tests (shows windows briefly)
```

Use the native platform for layout work; `QT_QPA_PLATFORM=offscreen` has no fonts, so widths are not
representative.

## Evidence tools

```powershell
& $py tools/layout_audit.py --out docs/evidence --sizes 1280x680 960x600 1440x900 --name my_audit
& $py tools/capture.py --out captures --sizes 1280x680 --layout split --prefix split_ --studio
```

`--scale` sets `QT_SCALE_FACTOR` and is **simulated** scaling (reported as such). Real per-monitor
125/150% scaling was not run (the development display is 100%).

## Operator guide

[docs/WALKTHROUGH.md](docs/WALKTHROUGH.md) is a step-by-step tour: component gallery, Theme Studio
(edit, preview, contrast, save, restore, export, import), the Create journey and the two layouts.

## Limits that matter

Everything the prototype shows is a fixture. It demonstrates *how components and layouts could
behave*, not that Qt Widgets is better for StableNew operators; GUI-PORT-742's NO-GO on operator
benefit is untouched. See [ASSESSMENT](docs/ASSESSMENT.md) for what is demonstrated, simulated and
unverified.
