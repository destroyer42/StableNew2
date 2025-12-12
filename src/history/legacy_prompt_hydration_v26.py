"""
Legacy prompt hydration for v2.6 migration (PR-CORE1-D16).

Provides a single canonical function to hydrate prompt fields for legacy-to-NJR migration.
"""
from typing import Any, Mapping
from src.pipeline.job_models_v2 import NormalizedJobRecord

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
    prompt = (
        legacy_entry.get("positive_prompt")
        or legacy_entry.get("prompt")
        or (legacy_entry.get("config", {{}}).get("prompt") if isinstance(legacy_entry.get("config"), dict) else None)
        or ("\n".join(legacy_entry["prompt_lines"]) if isinstance(legacy_entry.get("prompt_lines"), list) else None)
    )
    if prompt:
        njr.positive_prompt = prompt
        if hasattr(njr, "config") and isinstance(njr.config, dict):
            njr.config.setdefault("prompt", prompt)
    else:
        njr.positive_prompt = ""
        if hasattr(njr, "config") and isinstance(njr.config, dict):
            njr.config.setdefault("prompt", "")
        if hasattr(njr, "metadata") and isinstance(njr.metadata, dict):
            njr.metadata["migration_warning"] = "missing_prompt"
