# Import record

**Imported source:** the owner's latest local prototype, Qt Widgets prototype **v0.3.0**, at
`D:\Downloads\StableNew_Qt_Prototype_Assessment\StableNew_Qt_Prototype_Assessment` (not a git
repository). The older initial archive was not used.

| | |
|---|---|
| Files | 71 (excluding `__pycache__`) |
| Aggregate identity | `sha256 84f4975b991ff017cf33b714c66f4ef5fe230d7d314e8574a7d473c70b59de81` (over the sorted `hash  path` lines) |
| Per-file record | `../SOURCE_IMPORT_MANIFEST.sha256` (hash, bytes, path) |
| Computed | 2026-11-09, before any edit |
| Verbatim commit | `9e304461` on `feature/qt-ds-01-design-foundation` |

The source package was left untouched; its files were re-hashed at the end of QT-DS-01 and compared
with the manifest (result in the completion report).

## Independent verification before changing anything

The 129 tests the source reported were **not** reused as evidence. A scratch copy was run natively on
Windows (Python 3.14.9, PySide6 6.12.0): 87 pure + 42 Qt = 129 passed. After the refactor all of
those tests still pass; the current suite is larger (see ASSESSMENT).

## Commits

1. `9e304461` verbatim import (byte-identical except the added manifest).
2. `63f6865d` theme library, Theme Studio, split Create layout, layout probe, tests.
3. `b8908c94` repository-configured `ruff format`/lint only (separate so the import stays reviewable).
4. Later commits: review repairs, repository guard test, evidence and documentation.

## Changes to imported behaviour

- `tokens.py` is now a thin live facade over the active theme; the v0.3 palette lives in
  `themes/blue-modern.theme.json` and is pinned by a hash test.
- `output_display.py` no longer contains a literal colour (theme-derived).
- One test (`test_mock_receipt_is_not_actual_queue_or_history`) was extended because receipts now
  carry placeholder tiles; it still asserts no job/queue/artifact identity.
- Qt tests dispose of their windows (live widgets made later stylesheet changes slow).
