"""Script-level unit tests for the Phase 2 batch run helper."""

from __future__ import annotations

from io import BytesIO
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from PIL import Image

from scripts.a1111_batch_run import BatchRunClient


def test_batch_run_closes_buffers_and_runs_gc(tmp_path, monkeypatch) -> None:
    images: list[Path] = []
    for idx in range(5):
        path = tmp_path / f"test_{idx}.png"
        Image.new("RGB", (2, 2), color="white").save(path)
        images.append(path)

    closed = {"count": 0}

    class TrackingBytesIO(BytesIO):
        def close(self) -> None:
            closed["count"] += 1
            super().close()

    def make_bytesio(data: bytes) -> BytesIO:
        return TrackingBytesIO(data)

    monkeypatch.setattr("scripts.a1111_batch_run.BytesIO", make_bytesio)

    collect_calls = {"count": 0}

    def fake_collect() -> int:
        collect_calls["count"] += 1
        return collect_calls["count"]

    monkeypatch.setattr("scripts.a1111_batch_run.gc.collect", fake_collect)

    posts: list[tuple[str, dict[str, Any]]] = []

    class DummySession:
        def __enter__(self) -> "DummySession":
            return self

        def __exit__(self, exc_type: Any, exc_value: Any, traceback: Any) -> None:
            pass

        def post(self, url: str, json: dict[str, Any], timeout: float | None = None) -> Any:
            posts.append((url, json))
            return SimpleNamespace(text="ok")

    client = BatchRunClient(session_factory=lambda: DummySession(), gc_interval=2)
    results = client.run(images, api_url="http://example/api")

    assert results == ["ok"] * len(images)
    assert len(posts) == len(images)
    assert closed["count"] == len(images)
    assert collect_calls["count"] >= 2
