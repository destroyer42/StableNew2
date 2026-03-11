from __future__ import annotations

from typing import Any


def collect_available_loras(
    *,
    prompt_workspace_state: Any = None,
    app_state: Any = None,
    baseline_config: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    merged: dict[str, dict[str, Any]] = {}

    def _add(name: str, *, strength: float | None = None, enabled: bool = True) -> None:
        key = str(name or "").strip()
        if not key:
            return
        current = merged.setdefault(
            key,
            {"name": key, "strength": float(strength if strength is not None else 1.0), "enabled": bool(enabled)},
        )
        if strength is not None:
            current["strength"] = float(strength)
        current["enabled"] = bool(current.get("enabled", True) or enabled)

    if app_state is not None:
        for config in list(getattr(app_state, "lora_strengths", []) or []):
            name = getattr(config, "name", "") or ""
            strength = getattr(config, "strength", None)
            enabled = bool(getattr(config, "enabled", True))
            _add(name, strength=strength, enabled=enabled)

    if prompt_workspace_state is not None:
        try:
            metadata = prompt_workspace_state.get_current_prompt_metadata()
            for ref in list(getattr(metadata, "loras", []) or []):
                _add(getattr(ref, "name", ""), strength=getattr(ref, "weight", None), enabled=True)
        except Exception:
            pass

    txt2img = dict((baseline_config or {}).get("txt2img") or {})
    for entry in list(txt2img.get("lora_strengths") or []):
        if not isinstance(entry, dict):
            continue
        _add(
            str(entry.get("name", "") or ""),
            strength=entry.get("strength"),
            enabled=bool(entry.get("enabled", True)),
        )
    for entry in list(txt2img.get("loras") or []):
        if isinstance(entry, dict):
            _add(
                str(entry.get("name", "") or ""),
                strength=entry.get("weight", entry.get("strength")),
                enabled=bool(entry.get("enabled", True)),
            )
        elif isinstance(entry, (list, tuple)) and entry:
            name = str(entry[0] or "")
            weight = entry[1] if len(entry) > 1 else None
            _add(name, strength=weight, enabled=True)

    return list(merged.values())
