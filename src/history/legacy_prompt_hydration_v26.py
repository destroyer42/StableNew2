"""
Legacy prompt hydration for v2.6 migration (PR-CORE1-D16).

Provides a single canonical function to hydrate prompt fields for legacy-to-NJR migration.
"""

from typing import Any, Mapping
from src.pipeline.job_models_v2 import NormalizedJobRecord

def _ensure_config(njr_obj):
    if isinstance(njr_obj, dict):
        cfg = njr_obj.get("config")
        if not isinstance(cfg, dict):
            cfg = {}
            njr_obj["config"] = cfg
        return cfg
    if not hasattr(njr_obj, "config") or not isinstance(njr_obj.config, dict):
        njr_obj.config = {}
    return njr_obj.config

def _set_field(njr_obj, key, value):
    if isinstance(njr_obj, dict):
        njr_obj[key] = value
    else:
        setattr(njr_obj, key, value)

def hydrate_prompt_fields(legacy_entry: Mapping[str, Any], njr: NormalizedJobRecord) -> None:
    """
    Hydrates prompt fields for migrated NJRs from legacy entries.
    Order:
    1. legacy positive_prompt
    2. legacy prompt
    3. legacy config.prompt or config["prompt"]
    4. legacy prompt_lines (joined)
    5. If still missing, set both positive_prompt and config["prompt"] to "" and add migration warning.
    """
    prompt = None
    # 1. legacy positive_prompt (not implemented, placeholder for future logic)
    # 2. legacy prompt
    if isinstance(legacy_entry.get("prompt"), str) and legacy_entry["prompt"].strip():
        prompt = legacy_entry["prompt"].strip()
    # 3. legacy config.prompt
    elif isinstance(legacy_entry.get("config"), dict):
        config_prompt = legacy_entry["config"].get("prompt")
        if isinstance(config_prompt, str) and config_prompt.strip():
            prompt = config_prompt.strip()
    # 4. legacy prompt_lines (joined)
    elif isinstance(legacy_entry.get("prompt_lines"), list):
        lines = [str(line) for line in legacy_entry["prompt_lines"] if isinstance(line, str)]
        if lines:
            prompt = "\n".join(lines)
    # 5. fallback: empty string
    if prompt is None or not prompt.strip():
        prompt = "MIGRATED_LEGACY_NO_PROMPT"
        if hasattr(njr, "metadata") and isinstance(njr.metadata, dict):
            njr.metadata["migration_warning"] = "missing_prompt"
    # Always set positive_prompt and config["prompt"] (even if empty)
    _set_field(njr, "positive_prompt", prompt)
    cfg = _ensure_config(njr)
    cfg["prompt"] = prompt
