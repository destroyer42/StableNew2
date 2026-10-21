"""PR-VID-LOOP-303: loop and ping-pong export, and "extend by looping to N seconds".

The frame arithmetic is pure and tested on plain lists; the runner test uses a fake generator and a capturing
encoder so no model, FFmpeg or GPU is involved.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from PIL import Image

from src.video.loop_export import (
    MAX_EXTEND_SECONDS,
    MAX_LOOP_FRAMES,
    build_loop_frames,
    loop_export_validation_error,
    ping_pong_cycle,
)
from src.video.svd_config import SVDConfig, SVDOutputConfig
from src.video.svd_errors import SVDConfigError
from src.video.svd_models import SVDPreprocessResult
from src.video.svd_postprocess import validate_svd_postprocess_config
from src.video.svd_registry import build_svd_history_record
from src.video.svd_runner import SVDRunner

# ---------------------------------------------------------------------------
# frame arithmetic
# ---------------------------------------------------------------------------


def test_default_export_is_the_clip_unchanged_and_the_record_says_so() -> None:
    frames = list(range(5))

    exported, record = build_loop_frames(frames, mode="none", extend_to_seconds=0, fps=7)

    assert exported == frames
    assert record == {
        "mode": "none",
        "extend_to_seconds": 0.0,
        "fps": 7,
        "base_frame_count": 5,
        "cycle_frame_count": 5,
        "cycles": 1,
        "output_frame_count": 5,
        "output_seconds": round(5 / 7, 3),
    }


def test_ping_pong_is_forward_then_back_without_repeating_the_end_frames() -> None:
    assert ping_pong_cycle([0, 1, 2, 3, 4]) == [0, 1, 2, 3, 4, 3, 2, 1]
    exported, record = build_loop_frames(
        [0, 1, 2, 3, 4], mode="ping_pong", extend_to_seconds=0, fps=4
    )
    assert exported == [0, 1, 2, 3, 4, 3, 2, 1]
    assert (record["cycle_frame_count"], record["cycles"]) == (8, 1)
    # The cycle joins onto its own first frame: the last frame is a neighbour of frame 0, not a repeat of it.
    assert abs(exported[-1] - exported[0]) == 1


@pytest.mark.parametrize("count", [0, 1, 2])
def test_a_clip_with_no_interior_has_no_ping_pong_turn(count: int) -> None:
    frames = list(range(count))
    assert ping_pong_cycle(frames) == frames


def test_extend_repeats_whole_cycles_until_the_duration_is_filled() -> None:
    frames = list(range(25))

    exported, record = build_loop_frames(frames, mode="none", extend_to_seconds=4, fps=28)

    # 4 s at 28 fps is 112 frames; five whole 25-frame cycles is the first count that is long enough.
    assert (record["cycles"], record["output_frame_count"]) == (5, 125)
    assert exported == frames * 5
    assert record["output_seconds"] >= 4


def test_extend_with_ping_pong_repeats_whole_ping_pong_cycles() -> None:
    frames = list(range(25))

    exported, record = build_loop_frames(frames, mode="ping_pong", extend_to_seconds=10, fps=28)

    cycle = ping_pong_cycle(frames)
    assert len(cycle) == 48
    assert record["cycles"] == 6  # ceil(280 / 48)
    assert exported == cycle * 6
    assert record["output_seconds"] >= 10


def test_a_clip_already_long_enough_is_not_repeated() -> None:
    exported, record = build_loop_frames(list(range(100)), mode="none", extend_to_seconds=2, fps=28)

    assert record["cycles"] == 1 and len(exported) == 100


def test_the_sequence_references_the_same_frames_instead_of_copying_them() -> None:
    frames = [object(), object(), object()]

    exported, _ = build_loop_frames(frames, mode="none", extend_to_seconds=2, fps=4)

    assert all(item is frames[index % 3] for index, item in enumerate(exported))


@pytest.mark.parametrize(
    ("mode", "seconds", "message"),
    [
        ("spiral", 0, "Invalid loop mode"),
        ("none", -1, "extend_to_seconds"),
        ("none", float("nan"), "extend_to_seconds"),
        ("none", MAX_EXTEND_SECONDS + 1, "at most"),
    ],
)
def test_invalid_requests_are_refused(mode: str, seconds: float, message: str) -> None:
    assert message in (loop_export_validation_error(mode=mode, extend_to_seconds=seconds) or "")
    with pytest.raises(ValueError, match=message):
        build_loop_frames([0, 1, 2], mode=mode, extend_to_seconds=seconds, fps=7)


def test_the_whole_sequence_is_bounded_not_only_the_duration() -> None:
    with pytest.raises(ValueError, match=str(MAX_LOOP_FRAMES)):
        build_loop_frames(list(range(25)), mode="none", extend_to_seconds=60, fps=200)


# ---------------------------------------------------------------------------
# configuration
# ---------------------------------------------------------------------------


def test_config_round_trips_and_an_old_dict_without_the_keys_still_loads() -> None:
    config = SVDConfig.from_dict(
        {"output": {"output_format": "mp4", "loop_mode": "ping_pong", "extend_to_seconds": 8}}
    )
    assert config.output.loop_mode == "ping_pong"
    assert config.output.extend_to_seconds == 8.0
    assert SVDConfig.from_dict(config.to_dict()).output == config.output

    old = SVDConfig.from_dict({"output": {"output_format": "gif", "save_frames": True}})
    assert (old.output.loop_mode, old.output.extend_to_seconds) == ("none", 0.0)
    assert SVDOutputConfig() == SVDOutputConfig(loop_mode="none", extend_to_seconds=0.0)


@pytest.mark.parametrize(
    "output", [{"loop_mode": "spiral"}, {"extend_to_seconds": -2}, {"extend_to_seconds": 61}]
)
def test_config_refuses_an_invalid_request(output: dict) -> None:
    with pytest.raises(SVDConfigError):
        SVDConfig.from_dict({"output": output})


def test_an_impossible_loop_is_refused_before_any_generation() -> None:
    # 40 fps x4 interpolation is 160 fps; 60 s of that is far past the frame limit.
    config = SVDConfig.from_dict(
        {
            "inference": {"fps": 40, "num_frames": 25},
            "postprocess": {
                "interpolation": {
                    "enabled": True,
                    "multiplier": 4,
                    "executable_path": __file__,
                }
            },
            "output": {"extend_to_seconds": 60},
        }
    )

    valid, reason = validate_svd_postprocess_config(config)

    assert valid is False
    assert reason is not None and str(MAX_LOOP_FRAMES) in reason


def test_a_sensible_loop_passes_the_gate() -> None:
    config = SVDConfig.from_dict(
        {"output": {"loop_mode": "ping_pong", "extend_to_seconds": 10}, "inference": {"fps": 7}}
    )

    assert validate_svd_postprocess_config(config) == (True, None)


# ---------------------------------------------------------------------------
# the run
# ---------------------------------------------------------------------------


def _run(tmp_path: Path, monkeypatch, output: dict) -> tuple[list, object, dict]:
    source = tmp_path / "source.png"
    Image.new("RGB", (16, 16), "white").save(source)
    prepared = SVDPreprocessResult(
        source_path=source,
        prepared_path=tmp_path / "prepared.png",
        original_width=16,
        original_height=16,
        target_width=16,
        target_height=16,
        resize_mode="letterbox",
        was_resized=False,
        was_padded=False,
        was_cropped=False,
    )
    monkeypatch.setattr("src.video.svd_runner.prepare_svd_input", lambda **_kw: prepared)
    monkeypatch.setattr(
        SVDRunner, "_embed_portable_svd_provenance", lambda _self, **_kw: {"schema": "stub"}
    )
    exported: list[tuple[int, int]] = []

    def _encode(*, frames, output_path, fps, cancel_token=None, settings=None):
        exported.append((len(frames), fps))
        Path(output_path).write_bytes(b"mp4")
        return Path(output_path)

    monkeypatch.setattr("src.video.svd_runner.export_video_mp4", _encode)

    class _Service:
        def generate_frames(self, **_kwargs):
            return [Image.new("RGB", (16, 16), (index * 20, 0, 0)) for index in range(5)]

        def _release_runtime_memory(self) -> None:
            return None

    config = SVDConfig.from_dict({"inference": {"fps": 7}, "output": output})
    result = SVDRunner(service=_Service(), output_root=tmp_path / "out").run(
        source_image_path=source, config=config, job_id="loop-1"
    )
    manifest = json.loads(Path(result.metadata_path).read_text(encoding="utf-8"))
    return exported, result, manifest


def test_the_run_exports_the_looped_sequence_and_records_the_mode(
    tmp_path: Path, monkeypatch
) -> None:
    exported, result, manifest = _run(
        tmp_path, monkeypatch, {"loop_mode": "ping_pong", "extend_to_seconds": 4}
    )

    # 5 frames at 7 fps: a ping-pong cycle is 8 frames; 4 s needs 28 frames, so 4 whole cycles = 32.
    assert exported == [(32, 7)]
    assert result.frame_count == 32
    assert result.export is not None and result.export["mode"] == "ping_pong"
    assert manifest["frame_count"] == 32
    assert manifest["export"]["mode"] == "ping_pong"
    assert manifest["export"]["cycles"] == 4
    assert manifest["export"]["output_frame_count"] == 32
    assert manifest["config"]["output"]["loop_mode"] == "ping_pong"
    assert build_svd_history_record(config=SVDConfig(), result=result)["export"]["cycles"] == 4


def test_the_default_run_is_unchanged_and_still_records_the_export(
    tmp_path: Path, monkeypatch
) -> None:
    exported, result, manifest = _run(tmp_path, monkeypatch, {})

    assert exported == [(5, 7)]
    assert result.frame_count == 5
    assert manifest["export"]["mode"] == "none" and manifest["export"]["cycles"] == 1
