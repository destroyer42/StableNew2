# PR-APP-251 - Shared Application Bootstrap and Kernel Composition

Status: Completed 2026-03-29

## Purpose

Make GUI and CLI compose their runtime stack through one explicit application
kernel rather than ad hoc per-entrypoint construction.

## Delivered

- shared `ApplicationKernel` now lives in `src/app/bootstrap.py`
- GUI bootstrap (`src/app_factory.py`) and CLI bootstrap (`src/cli.py`) now
  consume that shared kernel
- the kernel owns config-manager, runtime ports, API client, pipeline runner,
  structured logger, and optional-dependency snapshot wiring

## Validation

- `tests/app/test_application_kernel.py`
- `tests/cli/test_cli_njr_execution.py`
