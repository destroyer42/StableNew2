from __future__ import annotations

from pathlib import Path

from src.video.svd_models import discover_cached_svd_models, is_svd_model_cached


def test_discover_cached_svd_models_requires_complete_snapshot(tmp_path: Path) -> None:
    cache_root = tmp_path / "cache"
    complete = (
        cache_root
        / "models--stabilityai--stable-video-diffusion-img2vid-xt"
        / "snapshots"
        / "abc123"
    )
    complete.mkdir(parents=True)
    (complete / "model_index.json").write_text("{}", encoding="utf-8")

    incomplete = (
        cache_root
        / "models--stabilityai--stable-video-diffusion-img2vid-xt-1-1"
        / "snapshots"
        / "def456"
    )
    incomplete.mkdir(parents=True)
    (incomplete / "README.md").write_text("missing model index", encoding="utf-8")

    discovered = discover_cached_svd_models(cache_dir=cache_root)

    assert discovered == ["stabilityai/stable-video-diffusion-img2vid-xt"]


def test_is_svd_model_cached_checks_snapshot_integrity(tmp_path: Path) -> None:
    cache_root = tmp_path / "cache"
    snapshot = (
        cache_root
        / "models--stabilityai--stable-video-diffusion-img2vid"
        / "snapshots"
        / "good123"
    )
    snapshot.mkdir(parents=True)
    (snapshot / "model_index.json").write_text("{}", encoding="utf-8")

    assert is_svd_model_cached(
        "stabilityai/stable-video-diffusion-img2vid",
        cache_dir=cache_root,
    ) is True
    assert is_svd_model_cached(
        "stabilityai/stable-video-diffusion-img2vid-xt-1-1",
        cache_dir=cache_root,
    ) is False
