from __future__ import annotations

from typing import Any

from src.video.animatediff_backend import AnimateDiffVideoBackend
from src.video.comfy_workflow_backend import ComfyWorkflowVideoBackend
from src.video.svd_native_backend import SVDNativeVideoBackend
from src.video.video_backend_types import VideoBackendInterface


class VideoBackendRegistry:
    def __init__(self) -> None:
        self._backends: dict[str, VideoBackendInterface] = {}
        self._stage_map: dict[str, str] = {}

    def register(self, backend: VideoBackendInterface) -> None:
        backend_id = str(getattr(backend, "backend_id", "") or "").strip()
        if not backend_id:
            raise ValueError("Video backend registration requires a non-empty backend_id")
        if backend_id in self._backends:
            raise ValueError(f"Video backend '{backend_id}' is already registered")
        capabilities = getattr(backend, "capabilities", None)
        stage_types = tuple(getattr(capabilities, "stage_types", ()) or ())
        if not stage_types:
            raise ValueError(f"Video backend '{backend_id}' must declare at least one stage type")
        for stage_name in stage_types:
            normalized = str(stage_name or "").strip()
            if not normalized:
                raise ValueError(f"Video backend '{backend_id}' declared an empty stage type")
            if normalized in self._stage_map:
                existing = self._stage_map[normalized]
                raise ValueError(
                    f"Stage '{normalized}' is already claimed by video backend '{existing}'"
                )
        self._backends[backend_id] = backend
        for stage_name in stage_types:
            self._stage_map[str(stage_name).strip()] = backend_id

    def get(self, backend_id: str) -> VideoBackendInterface:
        normalized = str(backend_id or "").strip()
        if normalized not in self._backends:
            raise KeyError(f"Video backend '{normalized}' is not registered")
        return self._backends[normalized]

    def get_for_stage(self, stage_name: str) -> VideoBackendInterface:
        normalized = str(stage_name or "").strip()
        backend_id = self._stage_map.get(normalized)
        if backend_id is None:
            raise KeyError(f"No video backend is registered for stage '{normalized}'")
        return self._backends[backend_id]

    def is_registered_stage(self, stage_name: str) -> bool:
        return str(stage_name or "").strip() in self._stage_map

    def list_backend_ids(self) -> list[str]:
        return sorted(self._backends.keys())

    def list_stage_types(self) -> list[str]:
        return sorted(self._stage_map.keys())


def build_default_video_backend_registry() -> VideoBackendRegistry:
    registry = VideoBackendRegistry()
    registry.register(AnimateDiffVideoBackend())
    registry.register(SVDNativeVideoBackend())
    registry.register(ComfyWorkflowVideoBackend())
    return registry


__all__ = ["VideoBackendRegistry", "build_default_video_backend_registry"]
