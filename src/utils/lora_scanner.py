"""Compatibility projection from AssetRegistry; it owns no scan or cache."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

from src.assets import AssetKind, AssetRegistry
from src.assets.lora_preview import local_preview_path
from src.assets.registry import AssetRecord
from src.utils.lora_keyword_detector import detect_lora_keywords


@dataclass
class LoRAResource:
    name: str
    path: Path
    file_size: int
    keywords: list[str]
    source: Literal["civitai", "txt", "readme", "none"]
    description: str = ""
    record: AssetRecord | None = None
    preview_path: Path | None = None
    errors: tuple[str, ...] = ()
    visibility: dict[str, Any] = field(default_factory=dict)


class LoRAScanner:
    """Legacy API adapter; removal condition: callers consume AssetRegistry directly."""

    def __init__(
        self, webui_root: Path | str | None = None, *, registry: AssetRegistry | None = None
    ) -> None:
        self.webui_root = Path(webui_root) if webui_root else None
        self.registry = registry or AssetRegistry(self.webui_root)
        self._cache_file = self.registry.cache_path
        self._lora_cache: dict[str, LoRAResource] = {}

    def scan_loras(
        self,
        force_rescan: bool = False,
        *,
        read_only: bool = False,
        cancelled: Callable[[], bool] | None = None,
    ) -> dict[str, LoRAResource]:
        del force_rescan
        resources: dict[str, LoRAResource] = {}
        if read_only and not any(
            root.is_dir()
            for kind, root in self.registry.supported_roots()
            if kind is AssetKind.LORA
        ):
            raise FileNotFoundError("Local LoRA directories unavailable")
        records = self.registry.refresh(
            kinds={AssetKind.LORA},
            persist=not read_only,
            cancelled=cancelled,
        ).snapshot.records_for(AssetKind.LORA)
        stems: dict[str, int] = {}
        for record in records:
            for location in record.locations:
                if location.kind is AssetKind.LORA:
                    key = location.display_name.casefold()
                    stems[key] = stems.get(key, 0) + 1
        for record in records:
            for location in record.locations:
                if location.kind is not AssetKind.LORA:
                    continue
                if cancelled and cancelled():
                    raise InterruptedError("LoRA discovery cancelled")
                # Relative aliases disambiguate equal stems in separate subfolders. Ambiguous aliases
                # across roots are retained as unavailable evidence, never arbitrarily bound.
                name = (
                    location.display_name
                    if stems[location.display_name.casefold()] == 1
                    else location.path.relative_to(location.root).with_suffix("").as_posix()
                )
                if name in resources:
                    resources[name].record = None
                    resources[name].errors = ("Ambiguous local adapter name",)
                    resources[name].preview_path = None
                    resources[name].visibility["nsfw"] = (
                        True  # fail closed for an ambiguous SFW projection
                    )
                    continue
                found = detect_lora_keywords(name, lora_path=location.path)
                visibility = dict(location.sidecar_metadata)
                visibility["metadata"] = dict(location.sidecar_metadata)
                visibility.update(name=name, keywords=found.keywords, description=found.description)
                resources[name] = LoRAResource(
                    name,
                    location.path,
                    location.byte_size,
                    found.keywords,
                    found.source,
                    found.description,
                    record,
                    local_preview_path(location.path, location.root),
                    found.errors
                    + tuple(
                        "Local model metadata unavailable"
                        for error in (record.embedded_metadata_error, location.sidecar_error)
                        if error
                    ),
                    visibility,
                )
        self._lora_cache = dict(sorted(resources.items(), key=lambda item: item[0].lower()))
        return self._lora_cache

    def get_lora_names(self) -> list[str]:
        return list(self._lora_cache)

    def get_lora_info(self, name: str) -> LoRAResource | None:
        return self._lora_cache.get(name)

    def search_loras(self, query: str) -> list[str]:
        return [name for name in self._lora_cache if query.lower() in name.lower()]

    def clear_cache(self) -> None:
        self._lora_cache.clear()


def get_lora_scanner(webui_root: Path | str | None = None) -> LoRAScanner:
    # A picker owns a disposable projection; AssetRegistry remains the only persisted authority.
    return LoRAScanner(webui_root)
