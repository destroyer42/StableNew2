from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from src.api.client import SDWebUIClient
from src.api.webui_resources import WebUIResourceService as BaseWebUIResourceService


class WebUIResourceService(BaseWebUIResourceService):
    """WebUI resource helper that can refresh all resource lists at once."""

    def __init__(self, client: SDWebUIClient | None = None, **kwargs: Any) -> None:
        super().__init__(client=client, **kwargs)

    def refresh_all(self, timeout: float = 5.0) -> dict[str, list[Any]]:
        """Fetch the canonical resource sets defined by the UI dropdowns.
        
        Args:
            timeout: Maximum seconds to wait for each resource fetch. Default 5.0.
        
        Returns:
            Dictionary of resource lists. Empty lists returned on timeout/error.
        """
        import concurrent.futures
        
        # Use ThreadPoolExecutor with timeout to prevent indefinite blocking
        with concurrent.futures.ThreadPoolExecutor(max_workers=4) as executor:
            futures = {
                "models": executor.submit(self.list_models),
                "vaes": executor.submit(self.list_vaes),
                "samplers": executor.submit(lambda: self._normalize_sampler_names(self.client.get_samplers() or [])),
                "schedulers": executor.submit(lambda: list(self.client.get_schedulers() or [])),
                "upscalers": executor.submit(self.list_upscalers),
                "adetailer_models": executor.submit(self.list_adetailer_models),
                "adetailer_detectors": executor.submit(self.list_adetailer_detectors),
            }
            
            results = {}
            for key, future in futures.items():
                try:
                    results[key] = future.result(timeout=timeout) or []
                except concurrent.futures.TimeoutError:
                    results[key] = []  # Fall back to empty list on timeout
                except Exception:
                    results[key] = []  # Fall back to empty list on error
            
            return results

    @staticmethod
    def _normalize_sampler_names(data: Iterable[Any]) -> list[str]:
        """Extract sampler names from the API payload into a deduplicated list."""
        seen: set[str] = set()
        values: list[str] = []
        for entry in data:
            name = ""
            if isinstance(entry, dict):
                name = (
                    entry.get("name")
                    or entry.get("label")
                    or entry.get("sampler_name")
                    or entry.get("title")
                    or ""
                )
            else:
                name = str(entry)
            name = name.strip()
            if not name or name in seen:
                continue
            seen.add(name)
            values.append(name)
        return values

    def list_adetailer_models(self) -> list[str]:
        getter = getattr(self.client, "get_adetailer_models", None)
        if callable(getter):
            try:
                return [str(item).strip() for item in getter() or [] if str(item).strip()]
            except Exception:
                pass
        return []

    def list_adetailer_detectors(self) -> list[str]:
        getter = getattr(self.client, "get_adetailer_detectors", None)
        if callable(getter):
            try:
                return [str(item).strip() for item in getter() or [] if str(item).strip()]
            except Exception:
                pass
        return []
