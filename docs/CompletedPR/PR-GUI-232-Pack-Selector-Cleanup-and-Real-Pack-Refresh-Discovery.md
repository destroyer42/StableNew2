# PR-GUI-232 - Pack Selector Cleanup and Real Pack Refresh Discovery

Status: Completed 2026-03-20

## Summary

This PR removed the confusing empty PromptPack text field from the Pipeline
sidebar and made PromptPack refresh/discovery honor the current JSON-backed pack
format alongside legacy `.txt` and `.tsv` packs.

## Delivered

- removed the dead legacy prompt entry from `Pack Selector`
- kept the refresh control and replaced the empty field with clear helper text
- expanded shared PromptPack discovery to scan `.json`, `.txt`, and `.tsv`
- taught shared PromptPack reading to render JSON slot content into the same
  positive/negative shape used by existing sidebar preview and pack consumers
- added regressions for JSON pack discovery, JSON pack reading, sidebar refresh,
  and legacy prompt-entry removal

## Key Files

- `src/gui/sidebar_panel_v2.py`
- `src/utils/file_io.py`
- `tests/gui_v2/test_sidebar_pack_preview_v2.py`
- `tests/utils/test_prompt_packs.py`

## Tests

Focused verification passed:

- `pytest tests/utils/test_prompt_packs.py tests/gui_v2/test_sidebar_pack_preview_v2.py -q`
- `python -m compileall src/utils/file_io.py src/gui/sidebar_panel_v2.py tests/utils/test_prompt_packs.py tests/gui_v2/test_sidebar_pack_preview_v2.py`

## Documentation Updates

Bookkeeping closure recorded in:

- `docs/StableNew Roadmap v2.6.md`

## Deferred Debt

Intentionally deferred:

- canonical discovered-experiment scan-root cleanup
  Future owner: `PR-LEARN-233`
- Pipeline tab recipe/preset UX cleanup
  Future owner: `PR-GUI-235`
