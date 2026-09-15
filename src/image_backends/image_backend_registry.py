"""Registry and capability validation for one image backend per NJR."""

from __future__ import annotations

from collections.abc import Iterable

from src.image_backends.a1111_webui_backend import A1111WebUIImageBackend
from src.image_backends.image_backend_types import ImageBackendInterface


class ImageBackendRegistry:
    def __init__(self) -> None:
        self._backends: dict[str, ImageBackendInterface] = {}

    def register(self, backend: ImageBackendInterface) -> None:
        backend_id = str(getattr(backend, "backend_id", "") or "").strip()
        if not backend_id:
            raise ValueError("Image backend registration requires a non-empty backend_id")
        if backend_id in self._backends:
            raise ValueError(f"Image backend '{backend_id}' is already registered")
        if not tuple(getattr(getattr(backend, "capabilities", None), "stage_types", ()) or ()):
            raise ValueError(f"Image backend '{backend_id}' must declare stage capabilities")
        self._backends[backend_id] = backend

    def get(self, backend_id: str) -> ImageBackendInterface:
        normalized = str(backend_id or "").strip()
        if normalized not in self._backends:
            raise KeyError(f"Image backend '{normalized}' is not registered")
        return self._backends[normalized]

    def validate_stage_chain(self, backend_id: str, stage_names: Iterable[str]) -> None:
        backend = self.get(backend_id)
        supported = set(backend.capabilities.stage_types)
        unsupported = [str(stage) for stage in stage_names if str(stage) not in supported]
        if unsupported:
            raise ValueError(
                f"Image backend '{backend_id}' does not support stage chain: {', '.join(unsupported)}"
            )

    def list_backend_ids(self) -> list[str]:
        return sorted(self._backends)


def build_default_image_backend_registry() -> ImageBackendRegistry:
    registry = ImageBackendRegistry()
    registry.register(A1111WebUIImageBackend())
    return registry

