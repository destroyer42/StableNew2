# PR-APP-251 - Shared Application Bootstrap and Kernel Composition

Status: Completed 2026-03-29

## Delivered

- GUI and CLI now compose through the shared `ApplicationKernel`
- runtime ports, API client, runner, config manager, structured logger, and
  capability snapshot are built once via `src/app/bootstrap.py`
- `src/app_factory.py` and `src/cli.py` no longer own independent bootstrap
  graphs

## Validation

- `tests/app/test_application_kernel.py`
- `tests/cli/test_cli_njr_execution.py`
