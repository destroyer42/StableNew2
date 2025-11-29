from __future__ import annotations

from typing import Any, Iterable

from src.api.client import SDWebUIClient
from src.api.webui_resources import WebUIResourceService as BaseWebUIResourceService


class WebUIResourceService(BaseWebUIResourceService):
    """WebUI resource helper that can refresh all resource lists at once."""

    def __init__(self, client: SDWebUIClient | None = None, **kwargs: Any) -> None:
        super().__init__(client=client, **kwargs)

    def refresh_all(self) -> dict[str, list[Any]]:
        """Fetch the canonical resource sets defined by the UI dropdowns."""
        models = self.list_models() or []
        vaes = self.list_vaes() or []
        samplers = self._normalize_sampler_names(self.client.get_samplers() or [])
        schedulers = list(self.client.get_schedulers() or [])
        return {
            "models": models,
            "vaes": vaes,
            "samplers": samplers,
            "schedulers": schedulers,
        }

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
