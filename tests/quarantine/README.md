# Quarantine

This directory holds test files that cannot be collected by the standard CI
pytest run. Files here are preserved for reference or local investigation but
must NOT be expected to pass in headless environments.

## Why a file ends up here

A test file is quarantined when it falls into one of these categories:

1. **Tk-dependent** — imports `tkinter`, creates a real Tk root window, or
   calls any function that opens a display. These fail in headless CI
   environments (no `$DISPLAY`, no Tk installation).

2. **Manual verification script** — not structured as pytest tests (no
   `def test_*` functions). These are run directly with `python <file>` and
   print pass/fail rather than using pytest assertions.

3. **Integration smoke test requiring live services** — tests that require
   a running WebUI or external endpoint. Quarantined until a proper mock
   fixture is built.

## Files in this directory

| File | Category | Notes |
|---|---|---|
| `test_all_stage_cards.py` | Tk-dependent | Stage card visual rendering |
| `test_pipeline_final.py` | Tk-dependent | Pipeline tab frame integration |
| `test_pipeline_tab.py` | Tk-dependent | Pipeline tab live render |
| `test_queue_remove_bug.py` | Tk-dependent | Queue panel remove button |
| `test_stage_cards_debug.py` | Tk-dependent | Stage card debug output |
| `test_stage_cards_panel.py` | Tk-dependent | Stage card panel smoke |
| `test_import.py` | Manual script | GUI import smoke check |
| `test_learning_fix.py` | Manual script | Learning fix verification script |
| `test_learning_stage_config.py` | Broken import | References `src.models` (non-existent); needs rewrite |
| `test_pr_hb_001_002.py` | Manual script | Heartbeat PR verification script |

## Running quarantined tests locally

When a Tk display is available (Windows desktop, or Linux with Xvfb):

```bash
python tests/quarantine/test_import.py
pytest tests/quarantine/test_queue_remove_bug.py -v
```

## Graduating a test out of quarantine

To move a test out of quarantine:

1. Rewrite it to use mocked Tk fixtures (e.g., the `tk_root` fixture in
   `tests/conftest.py`) or eliminate the display dependency entirely.
2. Add a `pytest.mark.gui` marker if Tk is still required (these are selected
   only when `$DISPLAY` is available).
3. Move the file to the appropriate canonical test directory.
4. Update `tests/TEST_SURFACE_MANIFEST.md` to reflect the move.

Quarantine is a holding state, not a permanent home.
