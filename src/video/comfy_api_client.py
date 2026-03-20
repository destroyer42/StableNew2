from __future__ import annotations

from typing import Any

import requests


class ComfyApiClient:
    def __init__(
        self,
        *,
        base_url: str = "http://127.0.0.1:8188",
        session: requests.Session | None = None,
    ) -> None:
        self.base_url = str(base_url or "").rstrip("/")
        self._session = session or requests.Session()

    @property
    def session(self) -> requests.Session:
        return self._session

    def close(self) -> None:
        try:
            self._session.close()
        except Exception:
            pass

    def get_system_stats(self, *, timeout: float = 5.0) -> dict[str, Any]:
        return self._get_json("/system_stats", timeout=timeout)

    def get_object_info(self, *, timeout: float = 10.0) -> dict[str, Any]:
        return self._get_json("/object_info", timeout=timeout)

    def get_queue(self, *, timeout: float = 5.0) -> dict[str, Any]:
        return self._get_json("/queue", timeout=timeout)

    def get_history(
        self,
        prompt_id: str | None = None,
        *,
        timeout: float = 10.0,
    ) -> dict[str, Any]:
        normalized_prompt_id = str(prompt_id or "").strip()
        path = f"/history/{normalized_prompt_id}" if normalized_prompt_id else "/history"
        return self._get_json(path, timeout=timeout)

    def queue_prompt(self, payload: dict[str, Any], *, timeout: float = 30.0) -> dict[str, Any]:
        response = self._session.post(
            f"{self.base_url}/prompt",
            json=dict(payload or {}),
            timeout=timeout,
        )
        response.raise_for_status()
        data = response.json()
        if not isinstance(data, dict):
            raise RuntimeError("Comfy /prompt returned a non-dict payload")
        return data

    def _get_json(self, path: str, *, timeout: float) -> dict[str, Any]:
        response = self._session.get(f"{self.base_url}{path}", timeout=timeout)
        response.raise_for_status()
        payload = response.json()
        if not isinstance(payload, dict):
            raise RuntimeError(f"Comfy {path} returned a non-dict payload")
        return payload


__all__ = ["ComfyApiClient"]
