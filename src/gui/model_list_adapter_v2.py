# Subsystem: Adapters
# Role: Provides model/VAE lists to GUI widgets without Tkinter coupling.

"""Thin adapter to fetch available models/VAEs for GUI V2 without GUI/toolkit deps."""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any, Protocol


class _ClientProtocol(Protocol):
    def get_models(self) -> Iterable[Any]:  # pragma: no cover - exercised through adapter logic
        ...

    def get_vae_models(self) -> Iterable[Any]:  # pragma: no cover - exercised through adapter logic
        ...


class ModelListAdapterV2:
    """Fetch model and VAE names using an injected client provider."""

    def __init__(self, client_provider=None) -> None:
        """
        Args:
            client_provider: Callable returning an object with `get_models` / `get_vae_models`
                (e.g., SDWebUIClient). If None, adapter returns empty lists.
        """

        self._client_provider = client_provider

    def _get_client(self) -> _ClientProtocol | None:
        if callable(self._client_provider):
            try:
                return self._client_provider()
            except Exception:
                return None
        return None

    def get_model_names(self) -> list[str]:
        client = self._get_client()
        if not client:
            return []
        try:
            models = client.get_models() or []
        except Exception:
            return []
        names: list[str] = []
        for entry in models:
            name = ""
            if isinstance(entry, dict):
                name = entry.get("title") or entry.get("model_name") or entry.get("name") or ""
            else:
                name = str(entry)
            if name and name not in names:
                names.append(name)
        return names

    def get_vae_names(self) -> list[str]:
        client = self._get_client()
        if not client:
            return []
        try:
            vaes = client.get_vae_models() or []
        except Exception:
            return []
        names: list[str] = []
        for entry in vaes:
            name = ""
            if isinstance(entry, dict):
                name = entry.get("model_name") or entry.get("title") or entry.get("name") or ""
            else:
                name = str(entry)
            if name and name not in names:
                names.append(name)
        return names


__all__ = ["ModelListAdapterV2"]
