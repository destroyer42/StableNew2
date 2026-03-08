"""Embedding resource scanner with caching.

Scans the embeddings directory recursively for .pt, .safetensors, and .ckpt files.
Provides search functionality and caching for performance.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path


@dataclass
class EmbeddingResource:
    """Represents a scanned embedding file."""
    name: str
    path: str
    file_size: int


class EmbeddingScanner:
    """Scans embeddings directory and provides search functionality."""
    
    def __init__(self, webui_root: str | None = None):
        """Initialize scanner.
        
        Args:
            webui_root: Path to webui root (optional, will try to detect)
        """
        self.webui_root = webui_root or self._detect_webui_root()
        self._embeddings: list[EmbeddingResource] = []
        self._cache_file = Path("data/embedding_cache.json")
        self._cache_loaded = False
    
    def _detect_webui_root(self) -> str:
        """Attempt to detect webui root from config."""
        try:
            from src.config import STABLENEW_WEBUI_ROOT
            if STABLENEW_WEBUI_ROOT:
                return STABLENEW_WEBUI_ROOT
        except Exception:
            pass
        return ""
    
    def scan_embeddings(self, force_rescan: bool = False) -> list[EmbeddingResource]:
        """Scan embeddings directory.
        
        Args:
            force_rescan: If True, bypass cache and rescan filesystem
            
        Returns:
            List of EmbeddingResource objects
        """
        if self._embeddings and not force_rescan:
            return self._embeddings
        
        # Try to load from cache first
        if not force_rescan and not self._cache_loaded:
            cached = self._load_cache()
            if cached:
                self._embeddings = cached
                self._cache_loaded = True
                return self._embeddings
        
        # Scan filesystem
        self._embeddings = self._scan_filesystem()
        self._save_cache()
        self._cache_loaded = True
        
        return self._embeddings
    
    def _scan_filesystem(self) -> list[EmbeddingResource]:
        """Scan embeddings directory for embedding files."""
        if not self.webui_root:
            return []
        
        embeddings_dir = Path(self.webui_root) / "embeddings"
        if not embeddings_dir.exists():
            return []
        
        resources = []
        extensions = {".pt", ".safetensors", ".ckpt"}
        
        for root, _dirs, files in os.walk(embeddings_dir):
            for file in files:
                if any(file.lower().endswith(ext) for ext in extensions):
                    file_path = Path(root) / file
                    
                    # Get name without extension
                    name = file_path.stem
                    
                    try:
                        file_size = file_path.stat().st_size
                    except Exception:
                        file_size = 0
                    
                    resources.append(EmbeddingResource(
                        name=name,
                        path=str(file_path),
                        file_size=file_size
                    ))
        
        # Sort by name
        resources.sort(key=lambda r: r.name.lower())
        return resources
    
    def get_embedding_names(self) -> list[str]:
        """Get sorted list of embedding names."""
        if not self._embeddings:
            self.scan_embeddings()
        return [emb.name for emb in self._embeddings]
    
    def search_embeddings(self, query: str) -> list[EmbeddingResource]:
        """Search embeddings by name (case-insensitive substring match).
        
        Args:
            query: Search query string
            
        Returns:
            List of matching EmbeddingResource objects
        """
        if not self._embeddings:
            self.scan_embeddings()
        
        query_lower = query.lower()
        return [
            emb for emb in self._embeddings
            if query_lower in emb.name.lower()
        ]
    
    def get_embedding_info(self, name: str) -> EmbeddingResource | None:
        """Get info for a specific embedding by name.
        
        Args:
            name: Embedding name (without extension)
            
        Returns:
            EmbeddingResource or None if not found
        """
        if not self._embeddings:
            self.scan_embeddings()
        
        for emb in self._embeddings:
            if emb.name == name:
                return emb
        return None
    
    def clear_cache(self) -> None:
        """Clear cached embeddings data."""
        self._embeddings.clear()
        self._cache_loaded = False
        if self._cache_file.exists():
            self._cache_file.unlink()
    
    def _load_cache(self) -> list[EmbeddingResource] | None:
        """Load embeddings from cache file."""
        if not self._cache_file.exists():
            return None
        
        try:
            with open(self._cache_file, "r", encoding="utf-8") as f:
                data = json.load(f)
            
            # Validate cache entries still exist with same size
            resources = []
            for item in data:
                path = Path(item["path"])
                if path.exists():
                    try:
                        current_size = path.stat().st_size
                        if current_size == item["file_size"]:
                            resources.append(EmbeddingResource(
                                name=item["name"],
                                path=item["path"],
                                file_size=item["file_size"]
                            ))
                    except Exception:
                        continue
            
            # If we lost more than 25% of entries, invalidate cache
            if len(resources) < len(data) * 0.75:
                return None
            
            return resources
        except Exception:
            return None
    
    def _save_cache(self) -> None:
        """Save embeddings to cache file."""
        if not self._embeddings:
            return
        
        try:
            self._cache_file.parent.mkdir(parents=True, exist_ok=True)
            
            data = [
                {
                    "name": emb.name,
                    "path": emb.path,
                    "file_size": emb.file_size
                }
                for emb in self._embeddings
            ]
            
            with open(self._cache_file, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2)
        except Exception:
            pass


# Global scanner instance
_global_embedding_scanner: EmbeddingScanner | None = None


def get_embedding_scanner(webui_root: str | None = None) -> EmbeddingScanner:
    """Get or create global embedding scanner instance.
    
    Args:
        webui_root: Optional webui root path
        
    Returns:
        Global EmbeddingScanner instance
    """
    global _global_embedding_scanner
    if _global_embedding_scanner is None:
        _global_embedding_scanner = EmbeddingScanner(webui_root)
    return _global_embedding_scanner
