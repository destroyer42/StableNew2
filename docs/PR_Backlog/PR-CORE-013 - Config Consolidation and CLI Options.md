PR-CORE-013 – Config Consolidation & CLI Options

Status: Specification
Priority: MEDIUM
Effort: MEDIUM
Phase: Post‑Unification Core Refinement
Date: 2026-03-29

Context & Motivation

StableNew currently maintains separate configuration sources for the WebUI backend, the ComfyUI backend, and the GUI. Environment variables and scattered ConfigManager objects lead to duplication and confusion【136†L78-L86】. There is also no unified command‑line interface for running PromptPacks or story plans headlessly. Consolidating configuration into a single YAML file and introducing a CLI will simplify maintenance and enable batch workflows.

Goals & Non‑Goals
Goal: Create a single configuration file (stablnew.yaml) storing settings for all backends and global preferences (default models, LoRA paths, performance flags).
Goal: Implement a new ConfigManager to read and write this unified file and provide typed accessors.
Goal: Refactor modules to read configuration exclusively from this manager rather than environment variables. Both GUI and headless components should use the unified config.
Goal: Introduce a CLI entry point with subcommands (run-prompt, run-plan, list-models) using argparse. This CLI should run jobs without launching the GUI.
Non‑Goal: The GUI itself will not be overhauled here; it will simply use the unified config behind the scenes. Remote job execution is out of scope.
Guardrails
Ensure backwards compatibility: existing env‑var setups must migrate gracefully. Provide an auto‑import mechanism on first run.
Validate configuration keys and types; unknown keys should raise warnings.
CLI must provide clear error messages when required options are missing.
Allowed Files
Files to Create
config/default_config.yaml – default configuration template with sections for each backend and performance settings.
src/config/config_manager.py – encapsulates loading, saving, and accessing the unified config.
src/cli/main.py – entry point for CLI with subcommands for running prompts and plans.
tests/config/test_config_manager.py – unit tests for config loading and merging.
tests/cli/test_cli.py – tests for CLI argument parsing and integration.
Files to Modify
src/utils/preferences.py – refactor to use ConfigManager for persistent settings.
src/gui/main_window_v2.py – load configuration via ConfigManager and update settings accordingly.
Modules reading environment variables directly – replace with calls to ConfigManager.
Forbidden Files
Do not embed configuration values in code. All configurable values must reside in the unified config or environment overrides.
Do not introduce new global variables for configuration.
Implementation Plan
Design config schema: Define a YAML structure with sections such as backends.webui, backends.comfy, models.default_model, paths.lora_dir, and performance.use_xformers. Provide defaults in default_config.yaml with comments.
Implement ConfigManager: In src/config/config_manager.py, implement functions to load the YAML file, overlay environment variables, and provide typed getters (e.g. get(section, key, default=None)). Include validation to ensure required keys exist. Provide a save method to persist changes.
Refactor code: Replace direct reads of environment variables in backend modules with calls to ConfigManager. For example, in svd_service.py, read config.get('performance', 'use_xformers') instead of os.getenv('STABLENEW_USE_XFORMERS'). Update the GUI to read/write settings via the manager.
Implement CLI: In src/cli/main.py, define an argparse parser with subcommands:
run-prompt – accept --prompt, --model, --steps, etc., load the config, construct a PromptPack, and run headlessly.
run-plan – accept a path to a StoryPlan JSON/YAML and run the scenes in sequence.
list-models – print available model identifiers from the model registry.
Use dependency injection or mocks to avoid heavy inference during CLI tests.
Tests: Write unit tests for loading and saving config files, including environment overrides. Write CLI tests to ensure argument parsing works and that the CLI calls the appropriate pipeline functions (mocked). Use pytest or similar frameworks.
Migration: Implement a one‑time migration routine that checks for legacy environment variables or old config files. If the unified config does not exist, create it by reading existing values and writing them to stablnew.yaml. Warn the user about the migration.
Testing Plan
Unit tests: Test ConfigManager load/save/merge behaviour, ensuring that defaults are applied and overrides work. Ensure unknown keys raise warnings. In CLI tests, run python -m src.cli.main run-prompt --prompt "hello" in a temp directory and assert that the pipeline is invoked with correct parameters (using mocks).
Integration tests: Use the integration tests from PR‑CORE‑011 to run a full pipeline via CLI with the dummy backend. Verify that the unified config is loaded and that CLI flags override config values.
Verification Criteria
Unified configuration file is created on first run and loaded by both GUI and CLI. Existing settings are migrated correctly.
CLI subcommands function as expected: run-prompt generates an output, run-plan executes all scenes in a plan, and list-models outputs a list of registered model IDs.
Config values are accessible via ConfigManager and environment overrides are honoured. Removing old env vars or config files does not break the system.
All new tests pass and existing tests unaffected by configuration refactor remain green.
Risk Assessment
Medium risk: Consolidation touches many modules. Extensive testing is required to avoid breaking existing workflows. Migration logic must handle edge cases where users have custom setups.
Tech Debt Analysis

Unifying configuration simplifies future development and enables headless operation. However, the config schema will evolve; versioning and migration scripts may become necessary. Document the schema and encourage use of defaults to minimize breakage.

Documentation Updates
Add a new document docs/configuration.md detailing the unified config format and how to edit it.
Update README to describe how to run jobs via CLI and how to migrate existing setups.
Dependencies
Use PyYAML for YAML parsing (already included). Consider using argparse for CLI; no external CLI frameworks are needed.
Approval & Execution

Planner: agent
Executor: TBD
Reviewer: @infra‑team
Approval Status: Pending

Next Steps

After implementing the unified config and CLI, gather user feedback on CLI ergonomics. Consider adding batch processing features (e.g. run all PromptPacks in a folder) and remote execution support in future iterations.

