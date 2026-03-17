from __future__ import annotations

from types import SimpleNamespace

from PIL import Image

from src.video.svd_config import SVDInferenceConfig
from src.video.svd_service import SVDService


def test_is_available_returns_actionable_message_for_missing_torch(monkeypatch) -> None:
    def _import_module(name: str):
        if name == "torch":
            raise ModuleNotFoundError("No module named 'torch'", name="torch")
        raise AssertionError(f"unexpected import: {name}")

    monkeypatch.setattr("src.video.svd_service.importlib.import_module", _import_module)

    available, reason = SVDService().is_available()

    assert available is False
    assert reason is not None
    assert "requirements-svd.txt" in reason
    assert "torch" in reason


def test_clear_model_cache_releases_pipeline_hooks_and_cuda_cache(monkeypatch) -> None:
    calls: list[tuple[str, str | None]] = []

    class _FakePipeline:
        def maybe_free_model_hooks(self) -> None:
            calls.append(("maybe_free_model_hooks", None))

        def remove_all_hooks(self) -> None:
            calls.append(("remove_all_hooks", None))

        def to(self, device: str) -> None:
            calls.append(("to", device))

    fake_torch = SimpleNamespace(
        cuda=SimpleNamespace(
            is_available=lambda: True,
            empty_cache=lambda: calls.append(("empty_cache", None)),
            ipc_collect=lambda: calls.append(("ipc_collect", None)),
        )
    )
    monkeypatch.setattr(
        "src.video.svd_service.importlib.import_module",
        lambda name: fake_torch if name == "torch" else (_ for _ in ()).throw(AssertionError(name)),
    )
    SVDService._pipeline_cache = {
        ("model-a", "float16", "fp16", None): _FakePipeline(),
    }

    SVDService().clear_model_cache("model-a")

    assert SVDService._pipeline_cache == {}
    assert ("maybe_free_model_hooks", None) in calls
    assert ("remove_all_hooks", None) in calls
    assert ("to", "cpu") in calls
    assert ("empty_cache", None) in calls
    assert ("ipc_collect", None) in calls


def test_generate_frames_releases_inference_images_and_cuda_cache(monkeypatch, tmp_path) -> None:
    prepared_path = tmp_path / "prepared.png"
    Image.new("RGB", (32, 32), "white").save(prepared_path)

    calls: list[str] = []

    class _Frame:
        def __init__(self, color: str) -> None:
            self._image = Image.new("RGB", (8, 8), color)

        def convert(self, mode: str):
            return self._image.convert(mode)

        def close(self) -> None:
            calls.append("frame.close")
            self._image.close()

    class _FakePipeline:
        def __call__(self, *_args, **_kwargs):
            calls.append("pipeline")
            return SimpleNamespace(frames=[_Frame("red"), _Frame("blue")])

    service = SVDService()
    monkeypatch.setattr(service, "is_available", lambda: (True, None))
    monkeypatch.setattr(service, "_get_pipeline", lambda _config: _FakePipeline())
    monkeypatch.setattr(service, "_release_runtime_memory", lambda: calls.append("release"))
    monkeypatch.setattr(
        "src.video.svd_service.importlib.import_module",
        lambda name: SimpleNamespace(Generator=lambda device: None) if name == "torch" else None,
    )

    frames = service.generate_frames(
        prepared_image_path=prepared_path,
        config=SVDInferenceConfig(),
    )

    assert len(frames) == 2
    assert calls.count("frame.close") == 2
    assert calls[-1] == "release"
