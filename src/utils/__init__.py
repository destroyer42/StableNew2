"""Utilities module with lazy exports to avoid heavy imports at package load."""

from __future__ import annotations

from importlib import import_module
from typing import Any

__all__ = [
    "ConfigManager",
    "build_sampler_scheduler_payload",
    "StructuredLogger",
    "setup_logging",
    "get_logger",
    "LogContext",
    "log_with_ctx",
    "InMemoryLogHandler",
    "attach_gui_log_handler",
    "JsonlFileHandler",
    "JsonlFileLogConfig",
    "attach_jsonl_log_handler",
    "close_all_structured_loggers",
    "get_structured_logger_registry_count",
    "install_async_logging",  # PR-HARDEN-002
    "get_async_queue_handler",  # PR-HARDEN-002
    "PreferencesManager",
    "save_image_from_base64",
    "load_image_to_base64",
    "read_text_file",
    "write_text_file",
    "read_prompt_pack",
    "get_prompt_packs",
    "get_safe_filename",
    "build_safe_image_stem",
    "merge_global_negative",
    "find_webui_api_port",
    "wait_for_webui_ready",
]

_LAZY_IMPORTS: dict[str, tuple[str, str]] = {
    "ConfigManager": ("src.utils.config", "ConfigManager"),
    "build_sampler_scheduler_payload": ("src.utils.config", "build_sampler_scheduler_payload"),
    "StructuredLogger": ("src.utils.logger", "StructuredLogger"),
    "setup_logging": ("src.utils.logger", "setup_logging"),
    "PreferencesManager": ("src.utils.preferences", "PreferencesManager"),
    "save_image_from_base64": ("src.utils.file_io", "save_image_from_base64"),
    "load_image_to_base64": ("src.utils.file_io", "load_image_to_base64"),
    "read_text_file": ("src.utils.file_io", "read_text_file"),
    "write_text_file": ("src.utils.file_io", "write_text_file"),
    "read_prompt_pack": ("src.utils.file_io", "read_prompt_pack"),
    "get_prompt_packs": ("src.utils.file_io", "get_prompt_packs"),
    "get_safe_filename": ("src.utils.file_io", "get_safe_filename"),
    "build_safe_image_stem": ("src.utils.file_io", "build_safe_image_stem"),
    "merge_global_negative": ("src.utils.negative_helpers_v2", "merge_global_negative"),
    "find_webui_api_port": ("src.utils.webui_discovery", "find_webui_api_port"),
    # 🔴 OLD (remove this)
    # "wait_for_webui_ready": ("src.utils.webui_discovery", "wait_for_webui_ready"),
    # 🟢 NEW – route all utils.wait_for_webui_ready calls to the V2.5 healthcheck
    "wait_for_webui_ready": ("src.api.healthcheck", "wait_for_webui_ready"),
    "get_logger": ("src.utils.logger", "get_logger"),
    "LogContext": ("src.utils.logger", "LogContext"),
    "log_with_ctx": ("src.utils.logger", "log_with_ctx"),
    "InMemoryLogHandler": ("src.utils.logger", "InMemoryLogHandler"),
    "attach_gui_log_handler": ("src.utils.logger", "attach_gui_log_handler"),
    "JsonlFileHandler": ("src.utils.logger", "JsonlFileHandler"),
    "JsonlFileLogConfig": ("src.utils.logger", "JsonlFileLogConfig"),
    "attach_jsonl_log_handler": ("src.utils.logger", "attach_jsonl_log_handler"),
    "close_all_structured_loggers": ("src.utils.logger", "close_all_structured_loggers"),
    "get_structured_logger_registry_count": (
        "src.utils.logger",
        "get_structured_logger_registry_count",
    ),
    # PR-HARDEN-002: Async logging utilities
    "install_async_logging": ("src.utils.logger", "install_async_logging"),
    "get_async_queue_handler": ("src.utils.logger", "get_async_queue_handler"),
}


def __getattr__(name: str) -> Any:
    try:
        module_name, attr_name = _LAZY_IMPORTS[name]
    except KeyError as exc:
        raise AttributeError(f"module {__name__} has no attribute {name}") from exc
    module = import_module(module_name)
    value = getattr(module, attr_name)
    globals()[name] = value
    return value


def __dir__() -> list[str]:
    base_dir = list(globals().keys())
    base_dir.extend(_LAZY_IMPORTS.keys())
    return sorted(set(base_dir))
