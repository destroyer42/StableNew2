# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Fixed
- **Critical Threading Bug**: GUI no longer hangs on second pipeline run after changing model/refiner settings. Fixed `messagebox.showerror()` being called from worker thread - now properly marshaled to main thread using `root.after(0, ...)` to prevent Tkinter threading violations. This resolves the "GUI not responding" issue that required restart between runs. (`src/gui/main_window.py`)

### Added
- **Config Management Refactor (PRs 1-7)**: Complete overhaul of configuration handling to be explicit and user-controlled, replacing implicit autoload with deliberate actions.
  - **PR-1: Config Source Banner**: Disabled automatic config loading on pack selection, added banner showing current config source (Pack/Preset/Global Lock). (`src/gui/main_window.py`)
  - **PR-2: ConfigService**: Added centralized ConfigService for all config IO operations (packs, presets, lists). (`src/services/config_service.py`)
  - **PR-3: Explicit Load Controls**: Added "Load Pack Config" and "Load Preset" buttons to action bar for deliberate config loading. (`src/gui/main_window.py`)
  - **PR-4: Config Lock**: Added "Lock This Config" button to freeze current config globally, preventing accidental changes. (`src/gui/main_window.py`)
  - **PR-5: Apply to Packs**: Added "Apply Editor → Pack(s)" button to save current editor settings to selected packs. (`src/gui/main_window.py`)
  - **PR-6: Preset CRUD**: Added full preset management with load/save/delete operations and dropdown selection. (`src/gui/main_window.py`)
  - **PR-7: List Management**: Added pack collection management with load/save/overwrite/delete for custom lists. (`src/gui/main_window.py`)
- **Preview Payload & Validate (Dry Run)**: Added "Preview Payload (Dry Run)" button to action bar for validating prompt assembly before running. Shows 1-3 resolved prompt variants per selected pack, diagnostics for unresolved tokens ([[slot]]), empty randomizer slots, and matrix combination counts. No SD WebUI calls performed. (`src/gui/main_window.py`)
- Regression tests for upscale “single” and “img2img” modes to ensure payload steps/denoise values stay in sync with the UI (`tests/pipeline/test_upscale_stage.py`).
- README documentation covering upscale mode behavior, performance trade-offs, and the WebUI progress-bar discrepancy.
- Integration test covering consecutive pipeline runs and preset snapshots (`tests/gui/test_pipeline_runs.py`).
- Live “Next Run Summary” indicators beneath the configuration panel with automatic trace updates (`src/gui/main_window.py`).
- Hypernetwork dropdowns now mirror the WebUI inventory with on-connect refresh plus executor-level enforcement/logging so per-stage selections are honored (`src/api/client.py`, `src/gui/main_window.py`, `src/gui/config_panel.py`, `src/pipeline/executor.py`).
- Randomization tab with Prompt S/R, wildcard, and matrix editors plus parsing helpers and persistence hooks to prep Phase 3 prompt variation work (`src/gui/main_window.py`, `src/utils/config.py`, `tests/gui/test_randomization_parsing.py`).
- Aesthetic Gradient controls with script/fallback modes, embedding refresh, and executor payload injection (including tests and docs) so runs can call the WebUI “Aesthetic embeddings” extension directly (`src/gui/main_window.py`, `src/utils/config.py`, `src/pipeline/executor.py`, `tests/pipeline/test_aesthetic_integration.py`, `README.md`).
- Pipeline variant scheduler supporting fan-out or rotate-per-prompt execution of model × hypernetwork matrices, including a reusable planner module and regression tests (`src/gui/main_window.py`, `src/gui/pipeline_controls_panel.py`, `src/pipeline/variant_planner.py`, `tests/gui/test_pipeline_runs.py`, `tests/pipeline/test_variant_planner.py`).
- GUI regression tests covering Advanced Prompt Editor hot-reload behavior and summary text (`tests/gui/test_editor_and_summary.py`).
- ADetailer stage restored with a dedicated configuration panel, pipeline toggle, StructuredLogger folder, and orchestration logic (`src/gui/adetailer_config_panel.py`, `src/gui/main_window.py`, `src/gui/pipeline_controls_panel.py`, `src/pipeline/executor.py`).
- Pipeline throughput optimizations: model/VAE caching + base64 read cache, plus regression test coverage (`tests/test_pipeline_throughput.py`).
- Reorganized the central configuration UI into Pipeline/ADetailer/Randomization/General tabs with info boxes and embedded pipeline controls (`src/gui/main_window.py`).
- Stage toggles now live at the top of their respective tabs, and txt2img/img2img gained hypernetwork dropdowns with strength sliders (`src/gui/config_panel.py`).
- **Stage Chooser Modal** (`src/gui/stage_chooser.py`):
  - Non-blocking per-image modal for choosing next pipeline stage
  - Options: img2img, ADetailer, upscale, or skip
  - Live image preview of generated output
  - "Always do this for batch" toggle for applying choice to remaining images
  - "Re-tune settings" link for quick configuration adjustments
  - Queue-based communication to avoid blocking Tkinter main loop
- **ADetailer Integration** (`src/gui/adetailer_config_panel.py`):
  - Automatic face and detail enhancement using YOLOv8 detection models
  - Configuration panel with full control over detection and processing
  - Available models: face, hand, person detection, MediaPipe variants
  - Adjustable confidence threshold, mask feathering, and inpainting parameters
  - Separate sampler, steps, denoise strength, and CFG scale settings
  - Custom positive and negative prompts for detail enhancement
  - Enable/disable toggle with automatic control state management
- **Advanced Prompt Editor Enhancements**:
  - `name:` metadata prefix support for custom output filenames
  - Automatic pack name population from filename on load
  - Fixed `status_text` AttributeError with proper initialization guards
  - Global negative prompt display refresh on pack load
- **Filename Prefix System**:
  - Extract `name:` from first line of prompt
  - Use as prefix for generated image files (e.g., `HeroCharacter_20251103_1234.png`)
- Dead code archiver tool (`tools/archive_unused.py`) with:
  - AST-based import graph analysis
  - Automatic detection of unused Python files
  - Timestamped archive directories with manifest
  - Restore capability with `--undo` option
- **Optional pipeline stages**: img2img and upscale stages can now be skipped via configuration
  - Set `pipeline.img2img_enabled: false` to skip img2img stage
  - Set `pipeline.upscale_enabled: false` to skip upscale stage
- **GUI Component Architecture (Mediator Pattern)**:
  - `PromptPackPanel` - Modular prompt pack selection and list management
  - `PipelineControlsPanel` - Stage toggles, loop configuration, and batch settings
  - `ConfigPanel` - Configuration tabs with validation and enhanced features
  - `APIStatusPanel` - Color-coded API connection status display
- **Enhanced Configuration Features**:
  - **Hires Fix Steps**: New `hires_steps` parameter for controlling second-pass steps separately
  - **Expanded Dimensions**: Width/Height bounds raised to 2260px with validation warnings
  - **Face Restoration**: Optional GFPGAN/CodeFormer integration with weight control
    - Toggle-based UI with show/hide controls
    - Supports both GFPGAN and CodeFormer models
- Comprehensive test suite:
  - 148 tests passing including new features
  - StageChooser modal tests (multi-image, cancellation, batch persistence)
  - ADetailer panel tests (config validation, API payload, cancellation)
  - Prompt editor enhancement tests (filename prefix, brackets, global negative)
  - 27 tests for state management and controller
  - 14 tests for archiver tool
  - 14 tests for pipeline journey scenarios
  - 15 tests for ConfigPanel features
  - 13 tests for APIStatusPanel and LogPanel

=======
- **Test Infrastructure Improvements**:
  - Headless GUI testing support via xvfb for CI environments
  - Comprehensive panel integration tests (194 tests passing)
- Architecture documentation with pipeline diagrams and state machine
- GUI state management system with `GUIState` enum and `StateManager` class
- Thread-safe `CancelToken` for cooperative cancellation
- `PipelineController` for async pipeline execution with cancellation support
- Dead code archiver tool (`tools/archive_unused.py`) with:
  - Automatic detection of unused Python files
  - Timestamped archive directories with manifest
  - Restore capability with `--undo` option
  - `PromptPackPanel` - Modular prompt pack selection and list management
  - `PipelineControlsPanel` - Stage toggles, loop configuration, and batch settings
  - `ConfigPanel` - Configuration tabs with validation and enhanced features
  - `APIStatusPanel` - Color-coded API connection status display
  - 13 tests for APIStatusPanel and LogPanel
  - All tests passing (143 total)
- Refactored `src/gui/__init__.py` to avoid tkinter dependency in tests
- Improved test organization and coverage
  - Main window now acts as coordinator for panel components
  - Improved separation of concerns and testability

### Fixed
- **Test Environment Stability**:

### Fixed

## [1.0.0] - 2024-11-02

### Added
- Initial stable release
- Full pipeline automation: txt2img → img2img → upscale → video
- Modern dark-themed Tkinter GUI
- Configuration management with preset system
- Pack-specific configuration overrides
- Prompt pack support (.txt and .tsv formats)
- Structured logging with JSON manifests
- CSV rollup summaries
- UTF-8 support for international characters
- API readiness checking with auto-discovery
- Desktop launcher scripts
- Comprehensive test suite with pytest
- Configuration validation testing
- SDXL-optimized presets
- Global NSFW prevention system
- Smart sampler/scheduler handling
- Journey test packs for validation

### Fixed
- Configuration pass-through validation
- Sampler deprecation warnings
- Pack selection persistence
- UTF-8 handling in file I/O

### Documentation
- Complete README with usage guide
- Configuration testing guide
- Launcher documentation
- Project reorganization summary

---

## Version History Format

### Categories
- **Added** for new features
- **Changed** for changes in existing functionality
- **Deprecated** for soon-to-be removed features
- **Removed** for now removed features
- **Fixed** for any bug fixes
- **Security** for vulnerability fixes

### Version Numbers
- **MAJOR** version for incompatible API changes
- **MINOR** version for backwards-compatible functionality additions
- **PATCH** version for backwards-compatible bug fixes

[Unreleased]: https://github.com/destroyer42/StableNew/compare/v1.0.0...HEAD
[1.0.0]: https://github.com/destroyer42/StableNew/releases/tag/v1.0.0
