"""LoRA resource scanner with caching for autocomplete and keyword detection.

This service scans WebUI LoRA directories and caches results for performance.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Literal

from src.utils.lora_keyword_detector import LoRAMetadata, detect_lora_keywords


@dataclass
class LoRAResource:
    """Cached LoRA resource information."""
    
    name: str
    path: Path
    file_size: int
    keywords: list[str]
    source: Literal["civitai", "txt", "readme", "none"]
    description: str = ""


class LoRAScanner:
    """Scans and caches LoRA resources from WebUI directories."""
    
    def __init__(self, webui_root: Path | str | None = None):
        self.webui_root = Path(webui_root) if webui_root else None
        self._lora_cache: dict[str, LoRAResource] = {}
        self._cache_file = Path("data/lora_cache.json")
        self._load_cache()
    
    def scan_loras(self, force_rescan: bool = False) -> dict[str, LoRAResource]:
        """Scan for all LoRA files in WebUI directories.
        
        Args:
            force_rescan: If True, ignore cache and rescan all files
        
        Returns:
            Dictionary mapping LoRA names to LoRAResource objects
        """
        if not force_rescan and self._lora_cache:
            return self._lora_cache
        
        self._lora_cache.clear()
        
        if not self.webui_root or not self.webui_root.exists():
            return self._lora_cache
        
        # Scan directories
        lora_dirs = [
            self.webui_root / "models" / "Lora",
            self.webui_root / "models" / "LyCORIS",
        ]
        
        for lora_dir in lora_dirs:
            if not lora_dir.exists():
                continue
            
            self._scan_directory(lora_dir)
        
        self._save_cache()
        return self._lora_cache
    
    def _scan_directory(self, directory: Path) -> None:
        """Recursively scan directory for LoRA files."""
        try:
            for item in directory.rglob("*"):
                if item.is_file() and item.suffix.lower() in [".safetensors", ".pt", ".ckpt"]:
                    self._add_lora(item)
        except Exception:
            pass
    
    def _add_lora(self, lora_path: Path) -> None:
        """Add LoRA to cache with keyword detection."""
        name = lora_path.stem
        
        # Skip if already cached and file size matches
        if name in self._lora_cache:
            cached = self._lora_cache[name]
            if cached.path == lora_path and cached.file_size == lora_path.stat().st_size:
                return
        
        # Detect keywords
        metadata = detect_lora_keywords(name, webui_root=self.webui_root)
        
        # Create resource
        resource = LoRAResource(
            name=name,
            path=lora_path,
            file_size=lora_path.stat().st_size,
            keywords=metadata.keywords,
            source=metadata.source,
            description=metadata.description
        )
        
        self._lora_cache[name] = resource
    
    def get_lora_names(self) -> list[str]:
        """Get list of all cached LoRA names."""
        return sorted(self._lora_cache.keys())
    
    def get_lora_info(self, name: str) -> LoRAResource | None:
        """Get cached info for a specific LoRA."""
        return self._lora_cache.get(name)
    
    def search_loras(self, query: str) -> list[str]:
        """Search LoRA names by substring match."""
        query_lower = query.lower()
        return [
            name for name in self._lora_cache.keys()
            if query_lower in name.lower()
        ]
    
    def clear_cache(self) -> None:
        """Clear cached LoRA data."""
        self._lora_cache.clear()
        if self._cache_file.exists():
            self._cache_file.unlink()
    
    def _load_cache(self) -> None:
        """Load cached LoRA data from disk."""
        if not self._cache_file.exists():
            return
        
        try:
            with open(self._cache_file, encoding="utf-8") as f:
                data = json.load(f)
            
            for name, resource_data in data.items():
                # Convert path string back to Path
                resource_data["path"] = Path(resource_data["path"])
                
                # Verify file still exists and size matches
                path = resource_data["path"]
                if path.exists() and path.stat().st_size == resource_data["file_size"]:
                    self._lora_cache[name] = LoRAResource(**resource_data)
        
        except Exception:
            pass
    
    def _save_cache(self) -> None:
        """Save cached LoRA data to disk."""
        self._cache_file.parent.mkdir(parents=True, exist_ok=True)
        
        try:
            # Convert to JSON-serializable format
            cache_data = {}
            for name, resource in self._lora_cache.items():
                resource_dict = asdict(resource)
                resource_dict["path"] = str(resource.path)
                cache_data[name] = resource_dict
            
            with open(self._cache_file, "w", encoding="utf-8") as f:
                json.dump(cache_data, f, indent=2, ensure_ascii=False)
        
        except Exception:
            pass


# Global scanner instance
_scanner: LoRAScanner | None = None


def get_lora_scanner(webui_root: Path | str | None = None) -> LoRAScanner:
    """Get or create global LoRA scanner instance."""
    global _scanner
    if _scanner is None:
        _scanner = LoRAScanner(webui_root)
    elif webui_root and _scanner.webui_root != Path(webui_root):
        # Reinitialize if webui_root changed
        _scanner = LoRAScanner(webui_root)
    return _scanner
