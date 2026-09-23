"""Compatibility projection from AssetRegistry; it owns no scan or cache."""
from __future__ import annotations

from dataclasses import dataclass

from src.assets import AssetKind, AssetRegistry


@dataclass
class EmbeddingResource:
    name: str
    path: str
    file_size: int


class EmbeddingScanner:
    """Legacy API adapter; removal condition: callers consume AssetRegistry directly."""
    def __init__(self, webui_root: str | None = None, *, registry: AssetRegistry | None = None):
        self.webui_root = webui_root
        self.registry = registry or AssetRegistry(webui_root)
        self._embeddings: list[EmbeddingResource] = []

    def scan_embeddings(self, force_rescan: bool = False) -> list[EmbeddingResource]:
        del force_rescan
        values = []
        for record in self.registry.refresh(kinds={AssetKind.EMBEDDING}).snapshot.records_for(AssetKind.EMBEDDING):
            for location in record.locations:
                if location.kind is AssetKind.EMBEDDING: values.append(EmbeddingResource(location.display_name, str(location.path), location.byte_size))
        self._embeddings = sorted(values, key=lambda item: (item.name.lower(), item.path.lower()))
        return self._embeddings

    def get_embedding_names(self) -> list[str]:
        if not self._embeddings: self.scan_embeddings()
        return [item.name for item in self._embeddings]
    def search_embeddings(self, query: str) -> list[EmbeddingResource]:
        if not self._embeddings: self.scan_embeddings()
        return [item for item in self._embeddings if query.lower() in item.name.lower()]
    def get_embedding_info(self, name: str) -> EmbeddingResource | None:
        if not self._embeddings: self.scan_embeddings()
        return next((item for item in self._embeddings if item.name == name), None)
    def clear_cache(self) -> None: self._embeddings.clear()


_scanner: EmbeddingScanner | None = None
def get_embedding_scanner(webui_root: str | None = None) -> EmbeddingScanner:
    global _scanner
    if _scanner is None or (webui_root and _scanner.webui_root != webui_root): _scanner = EmbeddingScanner(webui_root)
    return _scanner
