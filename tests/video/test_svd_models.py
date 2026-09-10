from __future__ import annotations

from pathlib import Path

from src.video.svd_models import (
    discover_cached_svd_models,
    get_default_svd_cache_dir,
    get_svd_model_options,
    is_svd_model_cached,
)


def test_default_svd_cache_prefers_huggingface_environment(monkeypatch, tmp_path: Path) -> None:
    hub_cache = tmp_path / "hub-cache"
    monkeypatch.setenv("HUGGINGFACE_HUB_CACHE", str(hub_cache))
    monkeypatch.setenv("HF_HOME", str(tmp_path / "ignored-hf-home"))

    assert get_default_svd_cache_dir() == hub_cache


def test_default_svd_cache_uses_hf_home_then_user_huggingface_cache(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.delenv("HUGGINGFACE_HUB_CACHE", raising=False)
    monkeypatch.setenv("HF_HOME", str(tmp_path / "hf-home"))
    assert get_default_svd_cache_dir() == tmp_path / "hf-home" / "hub"

    monkeypatch.delenv("HF_HOME", raising=False)
    assert get_default_svd_cache_dir() == Path.home() / ".cache" / "huggingface" / "hub"


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


def test_get_svd_model_options_falls_back_to_supported_models_when_local_only_cache_is_empty(tmp_path: Path) -> None:
    cache_root = tmp_path / "cache"

    options = get_svd_model_options(cache_dir=cache_root, local_files_only=True)

    assert "stabilityai/stable-video-diffusion-img2vid-xt" in options
    assert "stabilityai/stable-video-diffusion-img2vid" in options
