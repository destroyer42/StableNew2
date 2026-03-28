# PR-CONFIG-271 - Content Visibility Mode Contract and Persistence

Status: Completed 2026-03-27

## Summary

This PR established the canonical content-visibility mode contract for the v2
GUI and persisted it through normal UI state restore/save paths. It created the
shared `sfw` / `nsfw` mode model, made mode changes observable through
`AppStateV2`, and ensured older or invalid persisted payloads normalize safely.

## Delivered

- added `src/gui/content_visibility.py` with the canonical mode enum,
  normalization helpers, and serializable settings payload
- extended `src/gui/app_state_v2.py` with persisted runtime state plus
  notifier-driven `set_content_visibility_mode()` and
  `toggle_content_visibility_mode()`
- wired `src/gui/main_window_v2.py` to restore the mode at startup and save it
  through the UI-state payload on persistence
- hardened `src/services/ui_state_store.py` so missing or invalid
  `content_visibility` payloads normalize to the deterministic `nsfw` default
- added deterministic tests covering normalization, app-state notifications,
  settings round-trip behavior, and UI-state fallback handling

## Key Files

- `src/gui/content_visibility.py`
- `src/gui/app_state_v2.py`
- `src/gui/main_window_v2.py`
- `src/services/ui_state_store.py`
- `tests/gui_v2/test_content_visibility_contract.py`

## Tests

Focused verification passed:

- `pytest -q tests/gui_v2/test_content_visibility_contract.py`
- `python -m compileall src/gui/content_visibility.py src/gui/app_state_v2.py src/gui/main_window_v2.py src/services/ui_state_store.py tests/gui_v2/test_content_visibility_contract.py`

## Documentation Updates

- `docs/StableNew Roadmap v2.6.md`
- `docs/DOCS_INDEX_v2.6.md`
- `docs/PR_Backlog/PR-CONFIG-271-Content-Visibility-Mode-Contract-and-Persistence.md`

## Notes

This PR intentionally stopped at contract and persistence boundaries. Resolver
integration, shell UX wiring, and feature-series hardening were delivered by
`PR-CTRL-272`, `PR-GUI-273`, and `PR-TEST-274`.
