"""Legacy-style batch run client with explicit memory hygiene for child scripts."""

from __future__ import annotations

import gc
import logging
from io import BytesIO
from pathlib import Path
from typing import Any, Callable, Sequence

import requests
from PIL import Image

logger = logging.getLogger(__name__)
SessionFactory = Callable[[], requests.Session]


DEFAULT_GC_INTERVAL = 10


class BatchRunClient:
    """Minimal helper for feeding folders of assets through external child scripts."""

    def __init__(self, *, session_factory: SessionFactory | None = None, gc_interval: int = DEFAULT_GC_INTERVAL) -> None:
        self._session_factory = session_factory or requests.Session
        self._gc_interval = max(1, int(gc_interval or DEFAULT_GC_INTERVAL))

    def run(self, image_paths: Sequence[Path], *, api_url: str) -> list[str]:
        """Process each image path and post metadata to the provided API URL."""

        if not image_paths:
            return []

        results: list[str] = []
        with self._session_factory() as session:
            for idx, image_path in enumerate(image_paths):
                payload = self._build_payload(image_path)
                try:
                    response = session.post(api_url, json=payload, timeout=30)
                    results.append(getattr(response, "text", ""))
                except Exception as exc:  # pragma: no cover - best-effort network logging
                    logger.warning("BatchRunClient failed to POST %s: %s", image_path, exc)
                    results.append("")
                if (idx + 1) % self._gc_interval == 0:
                    gc.collect()
                del payload
        return results

    def _build_payload(self, image_path: Path) -> dict[str, Any]:
        raw_bytes = self._read_file(image_path)
        metadata = self._extract_metadata(raw_bytes)
        del raw_bytes
        return {"path": str(image_path), "metadata": metadata}

    def _read_file(self, image_path: Path) -> bytes:
        with image_path.open("rb") as handle:
            return handle.read()

    def _extract_metadata(self, raw_bytes: bytes) -> dict[str, Any]:
        buffer = BytesIO(raw_bytes)
        try:
            with Image.open(buffer) as img:
                img.load()
                return {"size": img.size, "mode": img.mode}
        finally:
            buffer.close()
