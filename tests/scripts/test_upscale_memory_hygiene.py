"""Tests for the Phase 2 upscale-folder helper that reuses the batch runner."""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path

from PIL import Image

from scripts.a1111_upscale_folder import upscale_folder


class FakeBatchRunClient:
    def __init__(self, *, session_factory: None = None, gc_interval: int | None = None) -> None:
        self.ran: list[Path] = []
        self.api: str | None = None

    def run(self, image_paths: Sequence[Path], *, api_url: str) -> list[str]:
        self.ran = list(image_paths)
        self.api = api_url
        return ["ok"] * len(image_paths)


def test_upscale_folder_limits_images_and_passes_api(tmp_path, monkeypatch) -> None:
    stored: list[Path] = []
    for idx in range(3):
        path = tmp_path / f"sample_{idx}.png"
        Image.new("RGB", (1, 1), color="white").save(path)
        stored.append(path)

    client = FakeBatchRunClient()
    monkeypatch.setattr("scripts.a1111_upscale_folder.BatchRunClient", lambda *_: client)

    results = upscale_folder(tmp_path, "http://api.test", max_images=2)

    assert results == ["ok", "ok"]
    assert client.api == "http://api.test"
    assert client.ran == sorted(stored)[:2]
