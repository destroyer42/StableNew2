from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any

from src.app.optional_dependency_probes import (
    OptionalDependencySnapshot,
    build_optional_dependency_snapshot,
)
from src.controller.ports.default_runtime_ports import DefaultImageRuntimePorts
from src.controller.ports.runtime_ports import ImageRuntimePorts
from src.utils import StructuredLogger
from src.utils.config import ConfigManager


@dataclass(frozen=True, slots=True)
class ApplicationKernel:
    config_manager: ConfigManager
    runtime_ports: ImageRuntimePorts
    structured_logger: StructuredLogger
    api_client: Any
    pipeline_runner: Any
    capabilities: OptionalDependencySnapshot


def _resolve_default_webui_base_url(config_manager: ConfigManager) -> str:
    settings = config_manager.load_settings()
    return str(settings.get("webui_base_url") or "").strip() or os.getenv(
        "STABLENEW_WEBUI_BASE_URL",
        "http://127.0.0.1:7860",
    )


def build_application_kernel(
    *,
    config_manager: ConfigManager | None = None,
    runtime_ports: ImageRuntimePorts | None = None,
    structured_logger: StructuredLogger | None = None,
    api_url: str | None = None,
    capabilities: OptionalDependencySnapshot | None = None,
) -> ApplicationKernel:
    config_manager = config_manager or ConfigManager()
    runtime_ports = runtime_ports or DefaultImageRuntimePorts()
    structured_logger = structured_logger or StructuredLogger()
    base_url = str(api_url or _resolve_default_webui_base_url(config_manager))
    api_client = runtime_ports.create_client(base_url=base_url)
    pipeline_runner = runtime_ports.create_runner(
        api_client=api_client,
        structured_logger=structured_logger,
    )
    capability_snapshot = capabilities or build_optional_dependency_snapshot()
    return ApplicationKernel(
        config_manager=config_manager,
        runtime_ports=runtime_ports,
        structured_logger=structured_logger,
        api_client=api_client,
        pipeline_runner=pipeline_runner,
        capabilities=capability_snapshot,
    )


def build_gui_kernel(
    *,
    config_manager: ConfigManager | None = None,
    runtime_ports: ImageRuntimePorts | None = None,
    structured_logger: StructuredLogger | None = None,
) -> ApplicationKernel:
    return build_application_kernel(
        config_manager=config_manager,
        runtime_ports=runtime_ports,
        structured_logger=structured_logger,
    )


def build_runtime_host_kernel(
    *,
    config_manager: ConfigManager | None = None,
    runtime_ports: ImageRuntimePorts | None = None,
    structured_logger: StructuredLogger | None = None,
    api_url: str | None = None,
    capabilities: OptionalDependencySnapshot | None = None,
) -> ApplicationKernel:
    return build_application_kernel(
        config_manager=config_manager,
        runtime_ports=runtime_ports,
        structured_logger=structured_logger,
        api_url=api_url,
        capabilities=capabilities,
    )


def build_cli_kernel(
    *,
    api_url: str,
    config_manager: ConfigManager | None = None,
    runtime_ports: ImageRuntimePorts | None = None,
    structured_logger: StructuredLogger | None = None,
) -> ApplicationKernel:
    return build_application_kernel(
        config_manager=config_manager,
        runtime_ports=runtime_ports,
        structured_logger=structured_logger,
        api_url=api_url,
    )


__all__ = [
    "ApplicationKernel",
    "build_application_kernel",
    "build_cli_kernel",
    "build_gui_kernel",
    "build_runtime_host_kernel",
]
