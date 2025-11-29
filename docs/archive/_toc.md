# StableNew Documentation

## Table of Contents

### Getting Started
- [README](../README.md) - Project overview, installation, and quick start
- [CONTRIBUTING](../CONTRIBUTING.md) - Development environment setup and contribution guidelines

### Architecture & Design
- [ARCHITECTURE](../ARCHITECTURE.md) - System architecture, pipeline flow, and GUI state machine
- [GUI Revamp Summary](GUI_REVAMP_SUMMARY.md) - GUI component architecture and refactoring details
- [Sprint Summary (PR F-H)](SPRINT_SUMMARY_PR_F-H.md) - Recent UX polish and threading work
- [PR9 — Randomization Refinement](PR9_RANDOMIZATION_REFINEMENT.md) - Sanitised prompts, dry-run parity, and matrix visibility
- [PR10 — Single Instance Lock](PR10_SINGLE_INSTANCE_AND_EXIT.md) - Startup guard and reliable shutdown

### Configuration & Testing
- [Configuration Testing Guide](CONFIGURATION_TESTING_GUIDE.md) - Testing configuration changes and presets
- [Project Reorganization Summary](PROJECT_REORGANIZATION_SUMMARY.md) - File structure and organization

### Tools & Utilities
- [Launchers](LAUNCHERS.md) - Desktop launcher scripts and setup

### CI & Automation
- [Codex AutoFix Workflow](CODEX_AUTOFIX.md) - Slash-command workflow that posts Codex patch suggestions

### Version History
- [CHANGELOG](../CHANGELOG.md) - Complete version history and changes

## Quick Links

### For Users
1. [Installation & Setup](../README.md#installation)
2. [Running the Application](../README.md#usage)
3. [Configuration Guide](CONFIGURATION_TESTING_GUIDE.md)

### For Developers
1. [Development Setup](../CONTRIBUTING.md#development-setup)
2. [Architecture Overview](../ARCHITECTURE.md#system-overview)
3. [Testing Guidelines](../CONTRIBUTING.md#testing)
4. [Code Standards](../CONTRIBUTING.md#coding-standards)

### For Contributors
1. [How to Contribute](../CONTRIBUTING.md)
2. [Pull Request Process](../CONTRIBUTING.md#pull-request-process)
3. [Component Architecture](GUI_REVAMP_SUMMARY.md)

## Documentation Structure

```
StableNew/
├── README.md                    # Project landing page
├── CHANGELOG.md                 # Version history
├── ARCHITECTURE.md              # System architecture
├── CONTRIBUTING.md              # Contribution guidelines
└── docs/
    ├── _toc.md                  # This file
    ├── GUI_REVAMP_SUMMARY.md    # GUI refactoring overview
    ├── CONFIGURATION_TESTING_GUIDE.md
    ├── PROJECT_REORGANIZATION_SUMMARY.md
    └── LAUNCHERS.md

### Archived Records
- `docs/archive/refactor_plan_main_window_gui_20251102_postAgent_OLD.md` — superseded refactor plan (kept for historical reference)
```

## Component Documentation

### GUI Components
- **PromptPackPanel**: Multi-select pack management with custom lists
- **PipelineControlsPanel**: Stage toggles, loop configuration, batch settings
- **ConfigPanel**: Configuration tabs with dimension validation and new features
  - Hires fix steps control
  - Face restoration (GFPGAN/CodeFormer)
  - Dimensions up to 2260px
- **APIStatusPanel**: Color-coded connection status
- **LogPanel**: Thread-safe live logging with Python logging integration

### Core Systems
- **StateManager**: GUI state machine (IDLE → RUNNING → STOPPING → IDLE/ERROR)
- **CancelToken**: Thread-safe cooperative cancellation
- **PipelineController**: Async pipeline execution with cancellation support

## Feature Highlights

### New in Current Release
- ✅ Component-based GUI architecture with mediator pattern
- ✅ Enhanced configuration with hires_steps and face restoration
- ✅ Dimension bounds raised to 2260px
- ✅ Thread-safe logging and status updates
- ✅ Improved test coverage (143 passing tests)

### Planned Features
- 🔄 Per-image stage chooser after txt2img
- 🔄 ADetailer integration as optional stage
- 🔄 Editor improvements (angle brackets, filename prefixes)
- 🔄 Enhanced save flow (overwrite vs. save as new)

## Support & Resources

- **Issues**: [GitHub Issues](https://github.com/destroyer42/StableNew/issues)
- **Discussions**: [GitHub Discussions](https://github.com/destroyer42/StableNew/discussions)
- **Repository**: [GitHub Repository](https://github.com/destroyer42/StableNew)
