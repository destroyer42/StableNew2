from __future__ import annotations

from pathlib import Path

from PIL import Image

from src.video.depth_map_resolver import DepthMapResolver


class _EstimatorStub:
    def __init__(self) -> None:
        self.calls = 0

    def __call__(self, image):
        self.calls += 1
        return {"depth": Image.new("L", image.size, color=128)}


def test_depth_map_resolver_auto_reuses_cache(tmp_path: Path, monkeypatch) -> None:
    source = tmp_path / "source.png"
    Image.new("RGB", (32, 24), color=(32, 64, 96)).save(source)
    estimator = _EstimatorStub()
    resolver = DepthMapResolver(cache_dir=tmp_path / "cache")
    monkeypatch.setattr(resolver, "_load_estimator", lambda: estimator)

    first = resolver.resolve(
        source_image_path=source,
        depth_input={"mode": "auto"},
        output_dir=tmp_path / "run-1",
    )
    second = resolver.resolve(
        source_image_path=source,
        depth_input={"mode": "auto"},
        output_dir=tmp_path / "run-2",
    )

    assert estimator.calls == 1
    assert first.cache_hit is False
    assert second.cache_hit is True
    assert Path(first.resolved_path).exists()
    assert Path(second.resolved_path).exists()
    assert first.cache_path == second.cache_path


def test_depth_map_resolver_upload_validates_and_copies_depth_map(tmp_path: Path) -> None:
    source = tmp_path / "source.png"
    depth = tmp_path / "depth.png"
    Image.new("RGB", (32, 24), color=(10, 20, 30)).save(source)
    Image.new("L", (32, 24), color=200).save(depth)
    resolver = DepthMapResolver(cache_dir=tmp_path / "cache")

    result = resolver.resolve(
        source_image_path=source,
        depth_input={"mode": "upload", "path": str(depth)},
        output_dir=tmp_path / "run-upload",
    )

    assert result.mode == "upload"
    assert result.requested_path == str(depth.resolve())
    assert Path(result.resolved_path).exists()
    assert Path(result.resolved_path).parent.name == "conditioning"
