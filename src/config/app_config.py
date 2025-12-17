"""Application-level configuration flags for GUI toggles."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from src.utils.process_container_v2 import ProcessContainerConfig
from src.utils.watchdog_v2 import WatchdogConfig

_learning_enabled: bool | None = None
_job_history_path: str | None = None
_queue_execution_enabled: bool | None = None
_core_model_name: str | None = None
_core_sampler_name: str | None = None
_core_vae_name: str | None = None
_core_steps: int | None = None
_core_cfg_scale: float | None = None
_core_resolution_preset: str | None = None
_negative_prompt_default: str | None = None
_output_dir: str | None = None
_filename_pattern: str | None = None
_image_format: str | None = None
_batch_size: int | None = None
_seed_mode: str | None = None
_webui_workdir: str | None = None
_webui_command: list[str] | None = None
_webui_autostart_enabled: bool | None = None
_webui_health_initial_timeout: float | None = None
_webui_health_retry_count: int | None = None
_webui_health_retry_interval: float | None = None
_webui_health_total_timeout: float | None = None
STABLENEW_WEBUI_ROOT = ""
STABLENEW_WEBUI_COMMAND = ""


_watchdog_config: WatchdogConfig | None = None
_process_container_config: ProcessContainerConfig | None = None
_jsonl_log_config: JsonlFileLogConfig | None = None


def _bool_env_flag(name: str, default: bool) -> bool:
    value = os.environ.get(name)
    if value is None:
        return default
    return value.lower() in {"1", "true", "yes", "on"}


def _float_env(name: str, default: float | None) -> float | None:
    value = os.environ.get(name)
    if value is None:
        return default
    try:
        return float(value)
    except Exception:
        return default


def watchdog_config_default() -> WatchdogConfig:
    interval = _float_env("STABLENEW_WATCHDOG_INTERVAL_SEC", 5.0)
    memory_limit = _float_env("STABLENEW_WATCHDOG_MAX_PROCESS_MEMORY_MB", 4096.0)
    return WatchdogConfig(
        enabled=_bool_env_flag("STABLENEW_WATCHDOG_ENABLED", True),
        interval_sec=float(interval if interval is not None else 5.0),
        max_process_memory_mb=float(memory_limit if memory_limit is not None else 4096.0),
        max_job_runtime_sec=_float_env("STABLENEW_WATCHDOG_MAX_JOB_RUNTIME_SEC", None),
        max_process_idle_sec=_float_env("STABLENEW_WATCHDOG_MAX_PROCESS_IDLE_SEC", None),
    )


def get_watchdog_config() -> WatchdogConfig:
    global _watchdog_config
    if _watchdog_config is None:
        _watchdog_config = watchdog_config_default()
    return _watchdog_config


def set_watchdog_config(config: WatchdogConfig) -> None:
    global _watchdog_config
    _watchdog_config = config


def process_container_config_default() -> ProcessContainerConfig:
    return ProcessContainerConfig(
        enabled=_bool_env_flag("STABLENEW_PROCESS_CONTAINER_ENABLED", True),
        memory_limit_mb=_float_env("STABLENEW_PROCESS_CONTAINER_MEMORY_MB", None),
        cpu_limit_percent=_float_env("STABLENEW_PROCESS_CONTAINER_CPU_PERCENT", None),
        max_processes=_float_env("STABLENEW_PROCESS_CONTAINER_MAX_PROCESSES", None),
    )


def get_process_container_config() -> ProcessContainerConfig:
    global _process_container_config
    if _process_container_config is None:
        _process_container_config = process_container_config_default()
    return _process_container_config


def set_process_container_config(config: ProcessContainerConfig) -> None:
    global _process_container_config
    _process_container_config = config


def _int_env(name: str, default: int | None) -> int | None:
    value = os.environ.get(name)
    if value is None:
        return default
    try:
        return int(value)
    except Exception:
        return default


@dataclass(frozen=True)
class JsonlFileLogConfig:
    enabled: bool = True
    path: Path | None = None
    max_bytes: int = 10_000_000
    backup_count: int = 5


def jsonl_log_config_default() -> JsonlFileLogConfig:
    env_flag = os.environ.get("STABLENEW_JSONL_LOG_ENABLED")
    enabled = True if env_flag is None else env_flag.lower() in {"1", "true", "yes", "on"}
    path_str = os.environ.get(
        "STABLENEW_JSONL_LOG_PATH", os.path.join("logs", "stablenew.log.jsonl")
    )
    return JsonlFileLogConfig(
        enabled=enabled,
        path=Path(path_str) if path_str else Path("logs") / "stablenew.log.jsonl",
        max_bytes=_int_env("STABLENEW_JSONL_LOG_MAX_BYTES", 10_000_000) or 10_000_000,
        backup_count=_int_env("STABLENEW_JSONL_LOG_BACKUP_COUNT", 5) or 5,
    )


def get_jsonl_log_config() -> JsonlFileLogConfig:
    global _jsonl_log_config
    if _jsonl_log_config is None:
        _jsonl_log_config = jsonl_log_config_default()
    return _jsonl_log_config


def set_jsonl_log_config(config: JsonlFileLogConfig) -> None:
    global _jsonl_log_config
    _jsonl_log_config = config


def learning_enabled_default() -> bool:
    """Return default for learning toggle (opt-in by default)."""

    env_flag = os.environ.get("STABLENEW_LEARNING_ENABLED")
    if env_flag is None:
        return False
    return env_flag.lower() in {"1", "true", "yes", "on"}


def get_learning_enabled() -> bool:
    """Return current learning toggle (module-level memory)."""

    global _learning_enabled
    if _learning_enabled is None:
        _learning_enabled = learning_enabled_default()
    return bool(_learning_enabled)


def set_learning_enabled(enabled: bool) -> None:
    """Persist learning toggle in module-level memory."""

    global _learning_enabled
    _learning_enabled = bool(enabled)


def job_history_path_default() -> str:
    """Return default path for job history storage."""

    env_path = os.environ.get("STABLENEW_JOB_HISTORY_PATH")
    if env_path:
        return env_path
    return os.path.join("data", "job_history.jsonl")


def get_job_history_path() -> str:
    """Return current job history path (module-level memory)."""

    global _job_history_path
    if _job_history_path is None:
        _job_history_path = job_history_path_default()
    return _job_history_path


def set_job_history_path(path: str) -> None:
    """Override job history storage path."""

    global _job_history_path
    _job_history_path = path


def queue_execution_enabled_default() -> bool:
    """Return default for queue-backed execution (disabled by default)."""

    env_flag = os.environ.get("STABLENEW_QUEUE_EXECUTION_ENABLED")
    if env_flag is None:
        return False
    return env_flag.lower() in {"1", "true", "yes", "on"}


def is_queue_execution_enabled() -> bool:
    """Return current queue execution flag."""

    global _queue_execution_enabled
    if _queue_execution_enabled is None:
        _queue_execution_enabled = queue_execution_enabled_default()
    return bool(_queue_execution_enabled)


def set_queue_execution_enabled(enabled: bool) -> None:
    """Set queue execution flag (module-local only)."""

    global _queue_execution_enabled
    _queue_execution_enabled = bool(enabled)


def debug_shutdown_inspector_default() -> bool:
    """Return whether the shutdown inspector should run (env override)."""

    env_flag = os.environ.get("STABLENEW_DEBUG_SHUTDOWN")
    if env_flag is None:
        return False
    return env_flag.lower() in {"1", "true", "yes", "on"}


_debug_shutdown_inspector_enabled: bool | None = None


def is_debug_shutdown_inspector_enabled() -> bool:
    """Return current setting for the shutdown inspector."""

    global _debug_shutdown_inspector_enabled
    if _debug_shutdown_inspector_enabled is None:
        _debug_shutdown_inspector_enabled = debug_shutdown_inspector_default()
    return bool(_debug_shutdown_inspector_enabled)


def set_debug_shutdown_inspector_enabled(enabled: bool) -> None:
    """Override the shutdown inspector flag (module-level only)."""

    global _debug_shutdown_inspector_enabled
    _debug_shutdown_inspector_enabled = bool(enabled)


# --- Core config defaults for GUI V2 -----------------------------------------------------------


def _env_default(name: str, default: str) -> str:
    value = os.environ.get(name)
    return value if value is not None else default


def core_model_default() -> str:
    """Default model/checkpoint name for GUI V2 core config."""

    return _env_default("STABLENEW_CORE_MODEL", "")


def core_sampler_default() -> str:
    """Default sampler name for GUI V2 core config."""

    return _env_default("STABLENEW_CORE_SAMPLER", "")


def core_vae_default() -> str:
    """Default VAE name for GUI V2 model selection."""

    return _env_default("STABLENEW_CORE_VAE", "")


def core_steps_default() -> int:
    """Default steps for GUI V2 core config."""

    value = _env_default("STABLENEW_CORE_STEPS", "20")
    try:
        return int(value)
    except Exception:
        return 20


def core_cfg_scale_default() -> float:
    """Default CFG scale for GUI V2 core config."""

    value = _env_default("STABLENEW_CORE_CFG_SCALE", "7.0")
    try:
        return float(value)
    except Exception:
        return 7.0


def core_resolution_preset_default() -> str:
    """Default resolution preset for GUI V2 core config."""

    return _env_default("STABLENEW_CORE_RESOLUTION", "512x512")


def get_core_model_name() -> str:
    """Return current core model name (module-level memory)."""

    global _core_model_name
    if _core_model_name is None:
        _core_model_name = core_model_default()
    return _core_model_name


def set_core_model_name(value: str) -> None:
    global _core_model_name
    _core_model_name = value or ""


def get_core_sampler_name() -> str:
    """Return current core sampler name (module-level memory)."""

    global _core_sampler_name
    if _core_sampler_name is None:
        _core_sampler_name = core_sampler_default()
    return _core_sampler_name


def set_core_sampler_name(value: str) -> None:
    global _core_sampler_name
    _core_sampler_name = value or ""


def get_core_vae_name() -> str:
    """Return current core VAE name (module-level memory)."""

    global _core_vae_name
    if _core_vae_name is None:
        _core_vae_name = core_vae_default()
    return _core_vae_name


def set_core_vae_name(value: str) -> None:
    global _core_vae_name
    _core_vae_name = value or ""


def get_core_steps() -> int:
    """Return current core steps (module-level memory)."""

    global _core_steps
    if _core_steps is None:
        _core_steps = core_steps_default()
    return int(_core_steps)


def set_core_steps(value: int) -> None:
    global _core_steps
    _core_steps = int(value) if value is not None else core_steps_default()


def get_core_cfg_scale() -> float:
    """Return current core CFG scale (module-level memory)."""

    global _core_cfg_scale
    if _core_cfg_scale is None:
        _core_cfg_scale = core_cfg_scale_default()
    return float(_core_cfg_scale)


def set_core_cfg_scale(value: float) -> None:
    global _core_cfg_scale
    try:
        _core_cfg_scale = float(value)
    except Exception:
        _core_cfg_scale = core_cfg_scale_default()


def get_core_resolution_preset() -> str:
    """Return current resolution preset (module-level memory)."""

    global _core_resolution_preset
    if _core_resolution_preset is None:
        _core_resolution_preset = core_resolution_preset_default()
    return _core_resolution_preset


def set_core_resolution_preset(value: str) -> None:
    global _core_resolution_preset
    _core_resolution_preset = value or core_resolution_preset_default()


def negative_prompt_default() -> str:
    """Default negative prompt string for GUI V2."""

    global _negative_prompt_default
    if _negative_prompt_default is None:
        _negative_prompt_default = _env_default("STABLENEW_NEGATIVE_PROMPT", "")
    return _negative_prompt_default


def set_negative_prompt_default(value: str) -> None:
    """Override default negative prompt string."""

    global _negative_prompt_default
    _negative_prompt_default = value or ""


def output_dir_default() -> str:
    """Default output directory for rendered images."""

    global _output_dir
    if _output_dir is None:
        _output_dir = os.environ.get("STABLENEW_OUTPUT_DIR", "output")
    return _output_dir


def set_output_dir(value: str) -> None:
    global _output_dir
    _output_dir = value or "output"


def filename_pattern_default() -> str:
    """Default filename pattern for outputs."""

    global _filename_pattern
    if _filename_pattern is None:
        _filename_pattern = os.environ.get("STABLENEW_FILENAME_PATTERN", "{timestamp}_{index}")
    return _filename_pattern


def set_filename_pattern(value: str) -> None:
    global _filename_pattern
    _filename_pattern = value or "{timestamp}_{index}"


def image_format_default() -> str:
    """Default image format."""

    global _image_format
    if _image_format is None:
        _image_format = os.environ.get("STABLENEW_IMAGE_FORMAT", "png")
    return _image_format


def set_image_format(value: str) -> None:
    global _image_format
    _image_format = value or "png"


def batch_size_default() -> int:
    """Default batch size (images per prompt)."""

    global _batch_size
    if _batch_size is None:
        try:
            _batch_size = int(os.environ.get("STABLENEW_BATCH_SIZE", "1"))
        except Exception:
            _batch_size = 1
    return _batch_size


def set_batch_size(value: int) -> None:
    global _batch_size
    try:
        _batch_size = int(value)
    except Exception:
        _batch_size = batch_size_default()


def seed_mode_default() -> str:
    """Default seed strategy string."""

    global _seed_mode
    if _seed_mode is None:
        _seed_mode = os.environ.get("STABLENEW_SEED_MODE", "")
    return _seed_mode


def set_seed_mode(value: str) -> None:
    global _seed_mode
    _seed_mode = value or ""


# --- WebUI process config defaults -----------------------------------------------------------


def webui_workdir_default() -> str | None:
    """Best-effort detection of WebUI working directory (non-fatal)."""

    global _webui_workdir
    if _webui_workdir is None:
        try:
            from src.api.webui_process_manager import detect_default_webui_workdir

            _webui_workdir = detect_default_webui_workdir()
        except Exception:
            _webui_workdir = None
    return _webui_workdir


def get_webui_workdir() -> str | None:
    global _webui_workdir
    return _webui_workdir if _webui_workdir is not None else webui_workdir_default()


def set_webui_workdir(path: str | None) -> None:
    global _webui_workdir
    _webui_workdir = path


def webui_command_default() -> list[str]:
    """Default WebUI launch command based on platform."""
    if os.name == "nt":
        return ["webui-user.bat", "--api", "--xformers"]
    return ["bash", "webui.sh", "--api"]


def get_webui_command() -> list[str]:
    global _webui_command
    if _webui_command is None:
        return list(webui_command_default())
    return list(_webui_command)


def set_webui_command(cmd: list[str]) -> None:
    global _webui_command
    _webui_command = list(cmd) if cmd is not None else list(webui_command_default())


def webui_autostart_enabled_default() -> bool:
    """Default autostart: env override else enabled when detection succeeds."""
    env_flag = os.environ.get("STABLENEW_WEBUI_AUTOSTART")
    if env_flag is not None:
        return env_flag.lower() in {"1", "true", "yes", "on"}
    return webui_workdir_default() is not None


def get_webui_autostart_enabled() -> bool:
    global _webui_autostart_enabled
    if _webui_autostart_enabled is None:
        _webui_autostart_enabled = webui_autostart_enabled_default()
    return bool(_webui_autostart_enabled)


def set_webui_autostart_enabled(value: bool) -> None:
    global _webui_autostart_enabled
    _webui_autostart_enabled = bool(value)


def webui_health_initial_timeout_seconds_default() -> float:
    try:
        return float(os.environ.get("STABLENEW_WEBUI_HEALTH_INITIAL_TIMEOUT", "5.0"))
    except Exception:
        return 5.0


def webui_health_retry_count_default() -> int:
    try:
        return int(os.environ.get("STABLENEW_WEBUI_HEALTH_RETRY_COUNT", "10"))
    except Exception:
        return 10


def webui_health_retry_interval_seconds_default() -> float:
    try:
        return float(os.environ.get("STABLENEW_WEBUI_HEALTH_RETRY_INTERVAL", "1.0"))
    except Exception:
        return 1.0


def webui_health_total_timeout_seconds_default() -> float:
    try:
        return float(os.environ.get("STABLENEW_WEBUI_HEALTH_TOTAL_TIMEOUT", "60.0"))
    except Exception:
        return 60.0


def is_webui_autostart_enabled() -> bool:
    return get_webui_autostart_enabled()


def get_webui_health_initial_timeout_seconds() -> float:
    global _webui_health_initial_timeout
    if _webui_health_initial_timeout is None:
        _webui_health_initial_timeout = webui_health_initial_timeout_seconds_default()
    return float(_webui_health_initial_timeout)


def set_webui_health_initial_timeout_seconds(value: float) -> None:
    global _webui_health_initial_timeout
    try:
        _webui_health_initial_timeout = float(value)
    except Exception:
        _webui_health_initial_timeout = webui_health_initial_timeout_seconds_default()


def get_webui_health_retry_count() -> int:
    global _webui_health_retry_count
    if _webui_health_retry_count is None:
        _webui_health_retry_count = webui_health_retry_count_default()
    return int(_webui_health_retry_count)


def set_webui_health_retry_count(value: int) -> None:
    global _webui_health_retry_count
    try:
        _webui_health_retry_count = int(value)
    except Exception:
        _webui_health_retry_count = webui_health_retry_count_default()


def get_webui_health_retry_interval_seconds() -> float:
    global _webui_health_retry_interval
    if _webui_health_retry_interval is None:
        _webui_health_retry_interval = webui_health_retry_interval_seconds_default()
    return float(_webui_health_retry_interval)


def set_webui_health_retry_interval_seconds(value: float) -> None:
    global _webui_health_retry_interval
    try:
        _webui_health_retry_interval = float(value)
    except Exception:
        _webui_health_retry_interval = webui_health_retry_interval_seconds_default()


def get_webui_health_total_timeout_seconds() -> float:
    global _webui_health_total_timeout
    if _webui_health_total_timeout is None:
        _webui_health_total_timeout = webui_health_total_timeout_seconds_default()
    return float(_webui_health_total_timeout)


def set_webui_health_total_timeout_seconds(value: float) -> None:
    global _webui_health_total_timeout
    try:
        _webui_health_total_timeout = float(value)
    except Exception:
        _webui_health_total_timeout = webui_health_total_timeout_seconds_default()
