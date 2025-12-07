# Changelog

## [Unreleased]

### Changed
- [PR-GUI-H] Window Management & Layout Fixes (V2.5) – MainWindowV2 now enforces default/min window geometry and each Pipeline tab column wraps its cards in a single `ScrollableFrame`, improving first-launch visibility (files: `src/gui/main_window_v2.py`, `src/gui/views/pipeline_tab_frame_v2.py`, `tests/gui_v2/test_window_layout_normalization_v2.py`).
- [PR-GUI-I] GUI Validation Color Normalization (V2.5) – Added canonical validation color tokens and helper functions, recolored prompt pack and randomizer panels to use the theme palette, and documented the GUI normalization milestone (files: `src/gui/theme_v2.py`, `src/gui/prompt_pack_panel_v2.py`, `src/gui/randomizer_panel_v2.py`, `docs/Roadmap_v2.5.md`, `tests/gui_v2/test_color_validation.py`).
- [PR-0114C-Q] Queue/Runner State Transitions & Payload Enforcement (V2.5) – JobQueue now notifies JobService of every state change so `EVENT_JOB_STARTED`, `EVENT_JOB_FINISHED`, and `EVENT_JOB_FAILED` fire consistently, improving queue lifecycle determinism and supporting the new queue tests (files: `src/queue/job_queue.py`, `src/controller/job_service.py`, `tests/controller/test_job_service_unit.py`, `docs/ARCHITECTURE_v2.5.md`, `docs/StableNew_Coding_and_Testing_v2.5.md`).
- [PR-0114C-H] JobService → History Wiring & Completion Recording (V2.5) – JobService now forwards completed and failed jobs through JobHistoryService so HistoryStore captures final metadata and notifies listeners (files: `src/controller/job_service.py`, `src/controller/job_history_service.py`, `src/queue/job_history_store.py`, `tests/controller/test_job_service_history_v2.py`, `tests/history/test_history_store_recording_v2.py`, `docs/ARCHITECTURE_v2.5.md`, `docs/StableNew_Coding_and_Testing_v2.5.md`).

## [2.1.0] - 2025-11-21
### Added
- Full adoption of StableNew V2 architecture.
- Stage cards, adapters, sequencer, learning metadata stack.
- Randomizer V2 with advanced UX.
- AI Settings Generator stubs.
- Safety wrapper enforcement.
- GUI V2-only test harness.
- New roadmap and pivot explanation.

### Changed
- main_window.py partially modularized.
- Randomizer import surface isolated.
- Legacy GUI tests migrated.

### Fixed
- Theme constants restored.
- Randomizer rotate behavior corrected.

### Known Issues
- Stage-event emissions pending executor wiring.
- Some GUI tests skipped when Tk/Tcl unavailable.
