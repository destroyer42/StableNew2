"""Exception taxonomy for StableNew Unified Error Model."""

from __future__ import annotations


class StableNewError(Exception):
    """Base class for StableNew-specific errors."""

    suggested_fix: str | None = None


class PipelineError(StableNewError):
    suggested_fix = "Double-check pipeline configuration and stage order."


class WebUIError(StableNewError):
    suggested_fix = "Confirm the WebUI API endpoint is running and reachable."


class ExecutionError(StableNewError):
    suggested_fix = "Review execution logs for resource or OS errors."


class ConfigError(StableNewError):
    suggested_fix = "Validate the provided configuration values."


class ExternalProcessError(StableNewError):
    suggested_fix = "Inspect external helper scripts/webui logs for leaks."


class WatchdogViolationError(StableNewError):
    suggested_fix = "Reduce job size or raise resource caps in configuration."


class ResourceLimitError(StableNewError):
    suggested_fix = "Lower memory/CPU requirements or extend caps."
