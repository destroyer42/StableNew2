from __future__ import annotations

import io
from collections.abc import Iterable
from typing import Any


class DummyProcess:
    """Simple subprocess-like stub used by WebUI process-manager tests."""

    def __init__(self, pid: int = 12345):
        self.pid = pid
        self._returncode: int | None = None
        self.stdout = io.BytesIO(b"")
        self.stderr = io.BytesIO(b"")

    def poll(self) -> int | None:
        return self._returncode

    def terminate(self) -> None:
        self._returncode = 0

    def wait(self, timeout: float | None = None) -> int | None:
        return self._returncode


class DummyWebUIClient:
    """Minimal WebUI client stub to satisfy resource & API tests."""

    def __init__(
        self,
        *,
        models: Iterable[dict[str, Any]] | None = None,
        vaes: Iterable[dict[str, Any]] | None = None,
        hypernetworks: Iterable[dict[str, Any]] | None = None,
        upscalers: Iterable[dict[str, Any]] | None = None,
    ):
        self._models: list[dict[str, Any]] = list(models or [])
        self._vaes: list[dict[str, Any]] = list(vaes or [])
        self._hypernetworks: list[dict[str, Any]] = list(hypernetworks or [])
        self._upscalers: list[dict[str, Any]] = list(upscalers or [])

    def get_models(self) -> list[dict[str, Any]]:
        return list(self._models)

    def get_vae_models(self) -> list[dict[str, Any]]:
        return list(self._vaes)

    def get_hypernetworks(self) -> list[dict[str, Any]]:
        return list(self._hypernetworks)

    def get_upscalers(self) -> list[dict[str, Any]]:
        return list(self._upscalers)

    def generate_images(
        self, *, stage: str = "txt2img", payload: dict[str, Any] | None = None, **_kwargs: Any
    ) -> dict[str, Any]:
        payload = payload or {}
        return {
            "stage": stage,
            "payload": payload,
            "images": [f"{stage}_image.png"],
            "info": {"stage": stage},
        }
