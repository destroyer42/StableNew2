PR-CORE-012 – Enhanced Logging & Metrics

Status: Specification
Priority: MEDIUM
Effort: SMALL
Phase: Post‑Unification Core Refinement
Date: 2026-03-29

Context & Motivation

StableNew’s current pipeline uses Python’s logging but lacks structured logs and metrics. Important details like stage durations, GPU memory usage, and error counts are not captured. The research exsum notes only partial logging support
newtab
. As features expand (scene planning, style LoRAs, ControlNet), observability becomes critical. This PR introduces consistent structured logging and basic metrics to support debugging and performance tuning.

Goals & Non‑Goals
Goal: Introduce a unified logging format with fields such as timestamp, log level, module, stage, and message. Consider JSON or key‑value output for easier parsing.
Goal: Measure and record durations of key pipeline stages (prompt processing, model loading, inference, post‑processing, export) and include them in logs.
Goal: Count important events (e.g. number of frames generated, LoRA loads, errors) and log these counters.
Goal: Provide a mechanism to emit logs to both console and file, with configurable verbosity. Leave integration with external monitoring systems for future work.
Non‑Goal: Do not implement full monitoring dashboards or alerting; focus on emitting structured logs and metrics.
Guardrails
Logging must not expose sensitive information (API keys, user data). Review messages for privacy.
Logging should have minimal performance impact. Use coarse‑grained timers and avoid logging inside tight loops.
Default behaviour should remain unchanged for users who do not enable verbose logging.
Allowed Files
Files to Modify
src/common/logging_utils.py (create if missing) – encapsulate logging configuration, formatters, and timing utilities. Offer decorators like @log_duration(stage_name).
src/pipeline/job_builder_v2.py and other core modules – insert logging calls at start and end of major stages using the utilities. Include stage names and durations.
src/utils/preferences.py – add settings to control log verbosity and file path.
src/gui/views/settings_frame.py – add UI controls to choose log level and enable logging to file.
tests/common/test_logging_utils.py – tests to verify timing decorators and structured logging output.
Files to Create
src/common/logging_utils.py – defines structured logger and timing utilities.
tests/common/test_logging_utils.py – unit tests for logging utilities.
Forbidden Files
Avoid print() statements; use the logging API exclusively.
Do not log in high‑frequency inner loops; measure durations at stage boundaries instead.
Implementation Plan
Define structured format: Implement a custom Formatter in logging_utils.py that outputs JSON objects with standard fields (timestamp, level, module, stage, message, duration_ms, extra).
Setup logging: Provide a setup_logging(log_file, level) function to configure root handlers for stdout and file output. Use rotating file handlers to avoid unbounded log growth.
Timing utilities: Implement a context manager or decorator log_duration(stage_name) that records start time and logs elapsed milliseconds when exiting.
Instrument code: Apply log_duration to major functions (PromptPack build, pipeline execute, SVD inference, post‑processing, export). Within each stage, log counters (e.g. number of frames generated) using logger.info with structured extra data.
Preferences and UI: Add config options (e.g. log_level, log_file) in preferences. In the GUI settings, allow the user to set the log level and specify where to write log files.
Testing: Write tests in test_logging_utils.py that wrap dummy functions with log_duration and capture logs using pytest’s caplog. Assert that log messages include a duration_ms field and that the JSON format is parseable.
Testing Plan
Unit tests: Use the caplog fixture to capture logs from functions decorated with log_duration. Confirm that logs contain expected fields and measure approximate durations.
Integration tests: As part of PR‑CORE‑011, ensure that pipeline execution logs stage timings and counters. Optionally parse the log file and compute total runtime.
Verification Criteria
Logs include structured fields (timestamp, level, stage, duration) for each instrumented stage.
Stage durations roughly match actual execution times within a reasonable margin.
Users can set log level and file output via preferences and UI. Default behaviour is unchanged if verbose logging is disabled.
All new unit tests pass and existing functionality is unaffected.
Risk Assessment
Low risk: Logging adds minimal overhead if implemented carefully. Potential risk is cluttered logs or exposure of sensitive data; mitigate via careful message design.
Tech Debt Analysis

Improved logging reduces debugging time and surfaces performance bottlenecks. Future debt includes integrating metrics with external systems (Prometheus, StatsD) and implementing log rotation policies.

Documentation Updates
Update developer guide to describe the logging utilities and how to instrument new code.
Update user documentation on enabling verbose logging and finding log files.
Dependencies
No new dependencies; use Python’s logging and logging.handlers modules.
Approval & Execution

Planner: agent
Executor: TBD
Reviewer: @logging‑team
Approval Status: Pending

Next Steps

After implementing structured logging, consider adding metric export to a monitoring system and building simple dashboards to visualize pipeline performance trends.

