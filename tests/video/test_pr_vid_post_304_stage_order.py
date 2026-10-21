"""PR-VID-POST-304: stage order, model selection and the manifest record of the SVD post-process.

Workers and RIFE are replaced by a fake ``run_bounded`` seam, so no model, GPU or executable runs.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from PIL import Image

from src.utils.managed_process import ProcessOutcome
from src.video.restoration.runtime import WORKER_REPORT_FILENAME
from src.video.restoration.upscale_models import X2_WEIGHT_NAME
from src.video.svd_config import SVDConfig
from src.video.svd_postprocess import (
    SVDPostprocessRunner,
    get_realesrgan_runtime_issues,
    validate_svd_postprocess_config,
)

_FRAME_COUNT = 5
_MULTIPLIER = 2


@pytest.fixture(autouse=True)
def _hermetic_runtime(monkeypatch):
    """No optional package probing and no weights picked up from the developer's home folder."""

    monkeypatch.setattr("src.video.restoration.runtime._module_available", lambda _name: True)
    monkeypatch.setattr("src.video.svd_config._default_realesrgan_weight_path", lambda: None)
    monkeypatch.setattr("src.video.svd_config._default_realesrgan_x2_weight_path", lambda: None)


def _frames(count: int = _FRAME_COUNT, size: int = 16) -> list[Image.Image]:
    return [Image.new("RGB", (size, size), (index * 20, 0, 0)) for index in range(count)]


def _assets(tmp_path: Path, *, with_x2: bool) -> dict[str, str]:
    weights = tmp_path / "RealESRGAN"
    facelib = tmp_path / "facelib"
    weights.mkdir()
    facelib.mkdir()
    (weights / "RealESRGAN_x4plus.pth").write_bytes(b"x4")
    if with_x2:
        (weights / X2_WEIGHT_NAME).write_bytes(b"x2")
    (tmp_path / "codeformer.pth").write_bytes(b"cf")
    (facelib / "detection_Resnet50_Final.pth").write_bytes(b"d")
    (facelib / "parsing_parsenet.pth").write_bytes(b"p")
    return {
        "x4": str(weights / "RealESRGAN_x4plus.pth"),
        "x2": str(weights / X2_WEIGHT_NAME),
        "codeformer": str(tmp_path / "codeformer.pth"),
        "facelib": str(facelib),
        "rife": str(tmp_path / "rife-ncnn-vulkan.exe"),
    }


def _config(assets: dict[str, str], **overrides) -> SVDConfig:
    Path(assets["rife"]).write_bytes(b"exe")
    postprocess = {
        "face_restore": {
            "enabled": True,
            "codeformer_weight_path": assets["codeformer"],
            "facelib_model_root": assets["facelib"],
        },
        "upscale": {
            "enabled": True,
            "scale": 2.0,
            "model_path": assets["x4"],
            "model_path_x2": None,
        },
        "interpolation": {
            "enabled": True,
            "multiplier": _MULTIPLIER,
            "executable_path": assets["rife"],
        },
    }
    for key, value in overrides.items():
        postprocess[key].update(value)
    return SVDConfig.from_dict({"postprocess": postprocess})


class _Seam:
    """A fake ``run_bounded``: records each worker action and writes the frames/report it would."""

    def __init__(self, *, upscale_factor: int = 2, reports: dict[str, dict] | None = None) -> None:
        self.actions: list[str] = []
        self.payloads: dict[str, dict] = {}
        self.upscale_factor = upscale_factor
        self.reports = reports or {}

    def __call__(self, command, *, cwd=None, **_kwargs):
        config = json.loads(command[-1])
        action = config["action"]
        self.actions.append(action)
        self.payloads[action] = config["payload"]
        source = sorted(Path(config["input_dir"]).glob("*.png"))
        output = Path(config["output_dir"])
        output.mkdir(parents=True, exist_ok=True)
        for path in source:
            with Image.open(path) as image:
                size = (
                    (image.width * self.upscale_factor,) * 2 if action == "upscale" else image.size
                )
                image.convert("RGB").resize(size).save(output / path.name)
        if action in self.reports:
            (output / WORKER_REPORT_FILENAME).write_text(
                json.dumps(self.reports[action]), encoding="utf-8"
            )
        return ProcessOutcome(returncode=0)


def _fake_rife(received: list[tuple[int, tuple[int, int]]]):
    def _run(self, *, frames, postprocess, work_dir):
        received.append((len(frames), frames[0].size))
        return [frame.copy() for frame in frames for _ in range(_MULTIPLIER)]

    return _run


def _run(tmp_path: Path, monkeypatch, config: SVDConfig, seam: _Seam):
    received: list[tuple[int, tuple[int, int]]] = []
    monkeypatch.setattr("src.video.svd_postprocess.run_bounded", seam)
    monkeypatch.setattr(SVDPostprocessRunner, "_run_rife_stage", _fake_rife(received))
    frames, metadata = SVDPostprocessRunner(repo_root=tmp_path).process_frames(
        frames=_frames(), config=config, work_dir=tmp_path / "work"
    )
    return frames, metadata, received


def test_upscale_runs_before_interpolation_so_it_sees_n_frames_not_n_times_the_multiplier(
    tmp_path: Path, monkeypatch
) -> None:
    config = _config(_assets(tmp_path, with_x2=False))
    seam = _Seam()

    frames, metadata, rife_input = _run(tmp_path, monkeypatch, config, seam)

    assert seam.actions == ["face_restore", "upscale"]
    assert metadata["applied"] == ["face_restore", "upscale", "interpolation"]
    stages = {entry["stage"]: entry for entry in metadata["stages"]}
    assert [entry["stage"] for entry in metadata["stages"]] == [
        "face_restore",
        "upscale",
        "interpolation",
    ]
    assert stages["upscale"]["frames_in"] == _FRAME_COUNT  # not _FRAME_COUNT * _MULTIPLIER
    assert stages["upscale"]["frames_out"] == _FRAME_COUNT
    assert stages["interpolation"]["frames_in"] == _FRAME_COUNT
    assert stages["interpolation"]["frames_out"] == _FRAME_COUNT * _MULTIPLIER
    # RIFE interpolated the already-upscaled frames (16 px -> 32 px).
    assert rife_input == [(_FRAME_COUNT, (32, 32))]
    assert len(frames) == _FRAME_COUNT * _MULTIPLIER and frames[0].size == (32, 32)
    assert metadata["interpolation"]["input_frame_count"] == _FRAME_COUNT


def test_status_updates_follow_the_new_stage_order(tmp_path: Path, monkeypatch) -> None:
    config = _config(_assets(tmp_path, with_x2=False))
    updates: list[dict] = []
    monkeypatch.setattr("src.video.svd_postprocess.run_bounded", _Seam())
    monkeypatch.setattr(SVDPostprocessRunner, "_run_rife_stage", _fake_rife([]))

    SVDPostprocessRunner(repo_root=tmp_path, status_callback=updates.append).process_frames(
        frames=_frames(), config=config, work_dir=tmp_path / "work"
    )

    started = [u["stage_detail"] for u in updates if u["progress"] == 0.0 or u["current_step"] == 0]
    assert started[0] == "postprocess: face_restore"
    details = [u["stage_detail"] for u in updates]
    assert details.index("postprocess: upscale") < details.index("postprocess: interpolation")


def test_a_2x_request_uses_native_x2_weights_beside_the_x4_model_and_records_them(
    tmp_path: Path, monkeypatch
) -> None:
    assets = _assets(tmp_path, with_x2=True)
    seam = _Seam(reports={"upscale": {"native_scale": 2, "resized": False, "frames": _FRAME_COUNT}})

    _frames_out, metadata, _rife = _run(tmp_path, monkeypatch, _config(assets), seam)

    assert seam.payloads["upscale"]["selected_model_path"] == assets["x2"]
    selection = metadata["upscale"]["model_selection"]
    assert selection["model_name"] == X2_WEIGHT_NAME
    assert selection["source"] == "beside_model"
    assert selection["fallback_reason"] == ""
    assert metadata["upscale"]["worker_report"] == {
        "native_scale": 2,
        "resized": False,
        "frames": _FRAME_COUNT,
    }
    upscale_stage = next(entry for entry in metadata["stages"] if entry["stage"] == "upscale")
    assert (
        upscale_stage["model"] == X2_WEIGHT_NAME and upscale_stage["model_source"] == "beside_model"
    )


def test_a_configured_x2_path_wins_over_one_beside_the_x4_weights(
    tmp_path: Path, monkeypatch
) -> None:
    assets = _assets(tmp_path, with_x2=True)
    custom = tmp_path / "my_x2.pth"
    custom.write_bytes(b"c")
    config = _config(assets, upscale={"model_path_x2": str(custom)})
    seam = _Seam()

    _run(tmp_path, monkeypatch, config, seam)

    assert seam.payloads["upscale"]["selected_model_path"] == str(custom)


def test_without_x2_weights_the_x4_model_runs_and_the_fallback_is_recorded(
    tmp_path: Path, monkeypatch
) -> None:
    assets = _assets(tmp_path, with_x2=False)
    seam = _Seam(reports={"upscale": {"native_scale": 4, "resized": True, "frames": _FRAME_COUNT}})

    _frames_out, metadata, _rife = _run(tmp_path, monkeypatch, _config(assets), seam)

    assert seam.payloads["upscale"]["selected_model_path"] == assets["x4"]
    selection = metadata["upscale"]["model_selection"]
    assert selection["model_name"] == "RealESRGAN_x4plus.pth"
    assert selection["source"] == "model_path"
    assert X2_WEIGHT_NAME in selection["fallback_reason"]
    assert metadata["upscale"]["worker_report"]["resized"] is True


def test_a_4x_request_uses_the_x4_model_even_when_x2_weights_exist(
    tmp_path: Path, monkeypatch
) -> None:
    assets = _assets(tmp_path, with_x2=True)
    config = _config(assets, upscale={"scale": 4.0})
    seam = _Seam()

    _run(tmp_path, monkeypatch, config, seam)

    assert seam.payloads["upscale"]["selected_model_path"] == assets["x4"]


def test_face_restore_payload_and_report_carry_the_temporal_settings(
    tmp_path: Path, monkeypatch
) -> None:
    assets = _assets(tmp_path, with_x2=False)
    report = {"temporal": {"enabled": True, "frames": _FRAME_COUNT, "tracks_started": 1}}
    seam = _Seam(reports={"face_restore": report})

    _frames_out, metadata, _rife = _run(tmp_path, monkeypatch, _config(assets), seam)

    payload = seam.payloads["face_restore"]
    assert payload["temporal_smoothing"] is True
    assert payload["fidelity_weight"] == 0.85
    assert metadata["face_restore"]["worker_report"] == report
    face_stage = next(entry for entry in metadata["stages"] if entry["stage"] == "face_restore")
    assert face_stage["temporal_smoothing"] is True


def test_temporal_smoothing_can_be_switched_off_per_job(tmp_path: Path, monkeypatch) -> None:
    config = _config(_assets(tmp_path, with_x2=False), face_restore={"temporal_smoothing": False})
    seam = _Seam()

    _frames_out, metadata, _rife = _run(tmp_path, monkeypatch, config, seam)

    assert seam.payloads["face_restore"]["temporal_smoothing"] is False
    assert metadata["face_restore"]["temporal_smoothing"] is False


def test_a_missing_or_unreadable_worker_report_never_fails_the_stage(
    tmp_path: Path, monkeypatch
) -> None:
    config = _config(_assets(tmp_path, with_x2=False))
    seam = _Seam()

    def _bad_report(command, **kwargs):
        outcome = seam(command, **kwargs)
        output = Path(json.loads(command[-1])["output_dir"])
        (output / WORKER_REPORT_FILENAME).write_text("{not json", encoding="utf-8")
        return outcome

    monkeypatch.setattr("src.video.svd_postprocess.run_bounded", _bad_report)
    monkeypatch.setattr(SVDPostprocessRunner, "_run_rife_stage", _fake_rife([]))

    _frames_out, metadata = SVDPostprocessRunner(repo_root=tmp_path).process_frames(
        frames=_frames(), config=config, work_dir=tmp_path / "work"
    )

    assert "worker_report" not in metadata["upscale"]
    assert metadata["applied"] == ["face_restore", "upscale", "interpolation"]


def test_a_worker_report_in_the_output_folder_is_not_mistaken_for_a_frame(
    tmp_path: Path, monkeypatch
) -> None:
    config = _config(_assets(tmp_path, with_x2=False))
    seam = _Seam(reports={"upscale": {"native_scale": 4}, "face_restore": {"temporal": {}}})

    frames, _metadata, _rife = _run(tmp_path, monkeypatch, config, seam)

    assert len(frames) == _FRAME_COUNT * _MULTIPLIER


# --- admission --------------------------------------------------------------------------------


def test_x2_weights_alone_satisfy_a_2x_upscale_admission(tmp_path: Path) -> None:
    only_x2 = tmp_path / X2_WEIGHT_NAME
    only_x2.write_bytes(b"x2")
    config = SVDConfig.from_dict(
        {"postprocess": {"upscale": {"enabled": True, "scale": 2.0, "model_path_x2": str(only_x2)}}}
    )

    assert get_realesrgan_runtime_issues(config.postprocess) == []
    assert validate_svd_postprocess_config(config) == (True, None)


def test_x2_weights_alone_do_not_satisfy_a_4x_request(tmp_path: Path) -> None:
    only_x2 = tmp_path / X2_WEIGHT_NAME
    only_x2.write_bytes(b"x2")
    config = SVDConfig.from_dict(
        {"postprocess": {"upscale": {"enabled": True, "scale": 4.0, "model_path_x2": str(only_x2)}}}
    )

    assert get_realesrgan_runtime_issues(config.postprocess) == ["RealESRGAN weight"]


def test_a_configured_x2_weight_that_is_missing_blocks_admission_for_a_2x_request(
    tmp_path: Path,
) -> None:
    assets = _assets(tmp_path, with_x2=False)
    config = _config(assets, upscale={"model_path_x2": str(tmp_path / "gone_x2.pth")})

    valid, reason = validate_svd_postprocess_config(config)

    assert valid is False
    assert reason is not None and "RealESRGAN x2 weight" in reason


def test_a_missing_x2_weight_does_not_matter_for_a_4x_request(tmp_path: Path) -> None:
    assets = _assets(tmp_path, with_x2=False)
    config = _config(assets, upscale={"scale": 4.0, "model_path_x2": str(tmp_path / "gone_x2.pth")})

    assert get_realesrgan_runtime_issues(config.postprocess) == []


def test_no_weights_at_all_reports_the_general_weight_as_missing(tmp_path: Path) -> None:
    config = SVDConfig.from_dict(
        {"postprocess": {"upscale": {"enabled": True, "model_path": str(tmp_path / "missing.pth")}}}
    )

    assert get_realesrgan_runtime_issues(config.postprocess) == ["RealESRGAN weight"]
