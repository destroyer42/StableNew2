"""Reference-map preparation service: one blocking seam, thread-agnostic (PR-IMG-CNET-230).

``prepare`` reads the source once, runs exactly the requested modality's provider and returns an in-memory
``PreparedMap``; ``save`` publishes it to the OpenPose library after re-verifying the source. Both block, so a caller runs
them on a tracked worker; neither starts a thread, queue job, backend request or runtime. There is no fallback between
modalities: an unavailable provider raises ``ProviderUnavailable`` with its reason codes.
"""

from __future__ import annotations

import hashlib
import io
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any

import numpy as np

from src.conditioning.openpose_library import OpenPoseInputError, validate_image_bytes
from src.conditioning.reference_map import library
from src.conditioning.reference_map.contracts import (
    CODE_CANCELLED,
    CODE_INFERENCE,
    CancelCheck,
    MapRequest,
    PreparedMap,
    ReferenceMapError,
)
from src.conditioning.reference_map.providers import (
    Context,
    ProcessRunner,
    Provider,
    bounded_runner,
    default_providers,
)
from src.conditioning.reference_map.source import load_source

RegistryFactory = Callable[[], Any]


def encode_png(rgb: np.ndarray) -> bytes:
    """Metadata-free, deterministic PNG bytes for an RGB8 map."""

    from PIL import Image

    buffer = io.BytesIO()
    Image.fromarray(np.ascontiguousarray(rgb)).save(buffer, format="PNG", compress_level=6)
    return buffer.getvalue()


class ReferenceMapService:
    def __init__(
        self,
        registry_factory: RegistryFactory,
        *,
        providers: Mapping[str, Provider] | None = None,
        runner: ProcessRunner = bounded_runner,
        temp_root: str | None = None,
    ) -> None:
        self._registry_factory = registry_factory
        self._providers = dict(providers) if providers is not None else default_providers()
        self._runner = runner
        self._temp_root = temp_root

    def availability(self, modality: str) -> tuple[str, ...]:
        """Cheap runtime reason codes for ``modality`` (nothing is hashed or imported); empty when it looks usable."""

        provider = self._providers.get(modality)
        return provider.availability() if provider is not None else ("unsupported_modality",)

    def webui_root(self) -> Path | None:
        root = getattr(self._registry_factory(), "webui_root", None)
        return Path(root) if root is not None else None

    def prepare(self, request: MapRequest, cancel: CancelCheck | None = None) -> PreparedMap:
        check: CancelCheck = cancel or (lambda: False)
        provider = self._providers.get(request.modality)
        if provider is None:
            raise ReferenceMapError("invalid_request", "That map type is not supported.")
        loaded = load_source(request.source)
        if check():
            raise ReferenceMapError(CODE_CANCELLED, "Cancelled.")
        context = Context(
            registry=self._registry_factory(),
            cancel=check,
            runner=self._runner,
            temp_root=self._temp_root,
        )
        produced = provider.produce(loaded, context)
        if check():
            raise ReferenceMapError(CODE_CANCELLED, "Cancelled.")
        facts = loaded.facts
        rgb = produced.rgb
        if rgb.shape != (facts.height, facts.width, 3) or rgb.dtype != np.uint8:
            raise ReferenceMapError(
                CODE_INFERENCE, "The map does not have the source image's size."
            )
        png = encode_png(rgb)
        try:
            width, height, _ = validate_image_bytes(png)
        except OpenPoseInputError as exc:
            raise ReferenceMapError(CODE_INFERENCE, str(exc)) from exc
        return PreparedMap(
            modality=request.modality,
            png=png,
            sha256=hashlib.sha256(png).hexdigest(),
            width=width,
            height=height,
            source=facts,
            method=produced.method,
            auxiliary=produced.auxiliary,
            auxiliary_resource=produced.auxiliary_resource,
            runtime=dict(produced.runtime),
            warnings=produced.warnings,
            source_path=request.source,
        )

    def save(self, prepared: PreparedMap) -> library.SavedMap:
        return library.save_map(prepared, self.webui_root())


__all__ = ["ReferenceMapService", "encode_png"]
