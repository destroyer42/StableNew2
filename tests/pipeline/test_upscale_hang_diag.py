from __future__ import annotations

from pathlib import Path

import pytest

from src.pipeline.executor import Pipeline
from src.utils.logger import StructuredLogger
from src.gui.state import CancellationError


class DummyClient:
    def set_model(self, *_args, **_kwargs):
        return None

    def set_vae(self, *_args, **_kwargs):
        return None


class ToggleToken:
    def __init__(self):
        self._cancelled = False

    def cancel(self) -> None:
        self._cancelled = True

    def is_cancelled(self) -> bool:
        return self._cancelled


def _make_pipeline(tmp_path: Path) -> Pipeline:
    return Pipeline(DummyClient(), StructuredLogger(output_dir=tmp_path / "logs"))


def _seed_images(tmp_path: Path, count: int) -> list[Path]:
    images = []
    for idx in range(count):
        path = tmp_path / f"img_{idx}.png"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("stub-image")
        images.append(path)
    return images


def test_multi_image_run_upscale_is_serial_and_honors_cancel(tmp_path, monkeypatch):
    pipeline = _make_pipeline(tmp_path)
    image_paths = _seed_images(tmp_path / "src", 3)
    stage_events: list[tuple[str, str, int, int, bool]] = []

    def fake_stage_event(self, stage, phase, image_index, total_images, cancelled):
        stage_events.append((stage, phase, image_index, total_images, cancelled))

    monkeypatch.setattr(
        Pipeline, "_record_stage_event", fake_stage_event, raising=False
    )

    def fake_run_txt2img(self, prompt, cfg, run_dir, batch_size, cancel_token):
        return [
            {
                "name": f"img-{idx}",
                "timestamp": "now",
                "path": str(image_paths[idx]),
            }
            for idx in range(len(image_paths))
        ]

    def fake_run_img2img(self, *_args, **_kwargs):
        return None

    cancel_token = ToggleToken()
    upscale_counter = {"value": 0}

    def fake_run_upscale_impl(self, input_image_path, config, run_dir, cancel_token=None):
        upscale_counter["value"] += 1
        if upscale_counter["value"] == 1:
            cancel_token.cancel()
        output_path = run_dir / f"up_{upscale_counter['value']}.png"
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text("upscaled")
        return {
            "name": f"upscaled-{upscale_counter['value']}",
            "path": str(output_path),
        }

    pipeline.run_txt2img = fake_run_txt2img.__get__(pipeline, Pipeline)
    pipeline.run_img2img = fake_run_img2img.__get__(pipeline, Pipeline)
    pipeline._run_upscale_impl = fake_run_upscale_impl.__get__(pipeline, Pipeline)  # type: ignore[attr-defined]

    cfg = {
        "pipeline": {"img2img_enabled": False, "upscale_enabled": True, "upscale_only_last": False},
        "txt2img": {},
        "upscale": {},
    }

    with pytest.raises(CancellationError):
        pipeline.run_full_pipeline("prompt", cfg, batch_size=1, cancel_token=cancel_token)

    assert ("upscale", "enter", 1, len(image_paths), False) in stage_events
    assert ("upscale", "exit", 1, len(image_paths), False) in stage_events
    cancel_events = [
        evt for evt in stage_events if evt[:2] == ("upscale", "cancelled")
    ]
    assert cancel_events, "expected a cancelled event for second image"
    assert cancel_events[-1][2] == 2


def test_upscale_stage_logs_stage_and_image_progress(tmp_path, monkeypatch):
    pipeline = _make_pipeline(tmp_path)
    image_paths = _seed_images(tmp_path / "src", 2)
    stage_events: list[tuple[str, str, int, int, bool]] = []

    def fake_stage_event(self, stage, phase, image_index, total_images, cancelled):
        stage_events.append((stage, phase, image_index, total_images, cancelled))

    monkeypatch.setattr(
        Pipeline, "_record_stage_event", fake_stage_event, raising=False
    )

    def fake_run_txt2img(self, prompt, cfg, run_dir, batch_size, cancel_token):
        return [
            {
                "name": f"img-{idx}",
                "timestamp": "now",
                "path": str(image_paths[idx]),
            }
            for idx in range(len(image_paths))
        ]

    def fake_run_img2img(self, *_args, **_kwargs):
        return None

    def fake_run_upscale_impl(self, input_image_path, config, run_dir, cancel_token=None):
        idx = len(stage_events) // 2 + 1
        output_path = run_dir / f"up_{idx}.png"
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text("upscaled")
        return {
            "name": f"upscaled-{idx}",
            "path": str(output_path),
        }

    pipeline.run_txt2img = fake_run_txt2img.__get__(pipeline, Pipeline)
    pipeline.run_img2img = fake_run_img2img.__get__(pipeline, Pipeline)
    pipeline._run_upscale_impl = fake_run_upscale_impl.__get__(pipeline, Pipeline)  # type: ignore[attr-defined]

    cfg = {
        "pipeline": {"img2img_enabled": False, "upscale_enabled": True, "upscale_only_last": False},
        "txt2img": {},
        "upscale": {},
    }

    pipeline.run_full_pipeline("prompt", cfg, batch_size=1)

    enter_events = [evt for evt in stage_events if evt[:2] == ("upscale", "enter")]
    exit_events = [evt for evt in stage_events if evt[:2] == ("upscale", "exit")]
    assert len(enter_events) == len(image_paths)
    assert len(exit_events) == len(image_paths)
    assert enter_events == [
        ("upscale", "enter", idx + 1, len(image_paths), False) for idx in range(len(image_paths))
    ]
    assert exit_events == [
        ("upscale", "exit", idx + 1, len(image_paths), False) for idx in range(len(image_paths))
    ]
