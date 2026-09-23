"""Compatibility projection from AssetRegistry; it owns no scan or cache."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from src.assets import AssetKind, AssetRegistry
from src.utils.lora_keyword_detector import detect_lora_keywords


@dataclass
class LoRAResource:
    name: str
    path: Path
    file_size: int
    keywords: list[str]
    source: Literal["civitai", "txt", "readme", "none"]
    description: str = ""


class LoRAScanner:
    """Legacy API adapter; removal condition: callers consume AssetRegistry directly."""
    def __init__(self, webui_root: Path | str | None = None, *, registry: AssetRegistry | None = None):
        self.webui_root = Path(webui_root) if webui_root else None
        self.registry = registry or AssetRegistry(self.webui_root)
        self._cache_file = self.registry.cache_path
        self._lora_cache: dict[str, LoRAResource] = {}

    def scan_loras(self, force_rescan: bool = False) -> dict[str, LoRAResource]:
        del force_rescan
        resources: dict[str, LoRAResource] = {}
        for record in self.registry.refresh(kinds={AssetKind.LORA}).snapshot.records_for(AssetKind.LORA):
            for location in record.locations:
                if location.kind is not AssetKind.LORA or location.display_name in resources: continue
                found = detect_lora_keywords(location.display_name, webui_root=self.webui_root)
                resources[location.display_name] = LoRAResource(location.display_name, location.path, location.byte_size, found.keywords, found.source, found.description)
        self._lora_cache = dict(sorted(resources.items(), key=lambda item: item[0].lower()))
        return self._lora_cache

    def get_lora_names(self) -> list[str]: return list(self._lora_cache)
    def get_lora_info(self, name: str) -> LoRAResource | None: return self._lora_cache.get(name)
    def search_loras(self, query: str) -> list[str]: return [name for name in self._lora_cache if query.lower() in name.lower()]
    def clear_cache(self) -> None: self._lora_cache.clear()


_scanner: LoRAScanner | None = None
def get_lora_scanner(webui_root: Path | str | None = None) -> LoRAScanner:
    global _scanner
    root = Path(webui_root) if webui_root else None
    if _scanner is None or (root and _scanner.webui_root != root): _scanner = LoRAScanner(root)
    return _scanner
