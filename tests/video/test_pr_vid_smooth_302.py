"""PR-VID-SMOOTH-302: smooth by default.

RIFE is found automatically (explicit path, environment, PATH, the tools folder one level deep), always runs with
a modern ``rife-v4.x`` model named on the command line, uses x2 for a fast source and x4 for a slow one so the
export lands at 24 fps or more, and the choice is recorded in the run. Nothing here needs a GPU or a real RIFE.
"""

from __future__ import annotations

import subprocess
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from PIL import Image

from src.controller.svd_controller import SVDController
from src.video.rife_runtime import (
    default_rife_multiplier,
    find_rife_executable,
    find_rife_model_dir,
    get_rife_multiplier_validation_error,
)
from src.video.svd_capabilities import apply_recommended_svd_defaults
from src.video.svd_config import SVDConfig
from src.video.svd_postprocess import (
    SVDPostprocessRunner,
    get_effective_svd_export_fps,
    validate_svd_postprocess_config,
)


@pytest.fixture(autouse=True)
def _no_ambient_rife(monkeypatch):
    monkeypatch.delenv("STABLENEW_RIFE_EXE", raising=False)
    monkeypatch.setenv("PATH", "")


def _model(root: Path, name: str, *, complete: bool = True) -> Path:
    folder = root / name
    folder.mkdir(parents=True)
    if complete:
        (folder / "flownet.param").write_bytes(b"p")
        (folder / "flownet.bin").write_bytes(b"b")
    return folder


def _release(root: Path) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    executable = root / "rife-ncnn-vulkan.exe"
    executable.write_bytes(b"exe")
    return executable


# ---------------------------------------------------------------------------
# finding the executable
# ---------------------------------------------------------------------------


def test_explicit_path_wins_over_the_tools_folder(tmp_path: Path) -> None:
    explicit = _release(tmp_path / "mine")
    _release(tmp_path / "tools" / "rife")

    assert find_rife_executable(explicit, repo_root=tmp_path) == explicit


def test_the_environment_variable_is_honoured(tmp_path: Path, monkeypatch) -> None:
    executable = _release(tmp_path / "env")
    monkeypatch.setenv("STABLENEW_RIFE_EXE", str(executable))

    assert find_rife_executable(None, repo_root=tmp_path / "no-repo") == executable


def test_the_tools_folder_is_searched_directly_and_one_level_down(tmp_path: Path) -> None:
    assert find_rife_executable(None, repo_root=tmp_path) is None

    nested = _release(tmp_path / "tools" / "rife" / "rife-ncnn-vulkan-20221029-windows")
    assert find_rife_executable(None, repo_root=tmp_path) == nested

    direct = _release(tmp_path / "tools" / "rife")
    assert find_rife_executable(None, repo_root=tmp_path) == direct


# ---------------------------------------------------------------------------
# choosing the model
# ---------------------------------------------------------------------------


def test_newest_modern_model_beside_the_executable_is_chosen(tmp_path: Path) -> None:
    executable = _release(tmp_path)
    for name in ("rife-v2.3", "rife-v3.1", "rife-v4", "rife-v4.6", "rife-v4.25", "rife-anime"):
        _model(tmp_path, name)

    assert find_rife_model_dir(executable) == (tmp_path / "rife-v4.25").resolve()


def test_a_plain_model_beats_its_lite_variant_and_an_incomplete_folder_is_skipped(
    tmp_path: Path,
) -> None:
    executable = _release(tmp_path)
    _model(tmp_path, "rife-v4.25-lite")
    _model(tmp_path, "rife-v4.25")
    _model(tmp_path, "rife-v4.30", complete=False)

    assert find_rife_model_dir(executable) == (tmp_path / "rife-v4.25").resolve()


def test_only_old_models_means_no_model_flag(tmp_path: Path) -> None:
    executable = _release(tmp_path)
    _model(tmp_path, "rife-v2.3")
    _model(tmp_path, "rife-v3.1")

    assert find_rife_model_dir(executable) is None


def test_a_configured_model_wins_and_a_relative_one_is_read_beside_the_executable(
    tmp_path: Path,
) -> None:
    executable = _release(tmp_path)
    _model(tmp_path, "rife-v4.25")
    custom = _model(tmp_path, "my-model")

    assert find_rife_model_dir(executable, str(custom)) == custom.resolve()
    assert find_rife_model_dir(executable, "my-model") == custom.resolve()


# ---------------------------------------------------------------------------
# the factor
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("source_fps", "factor"), [(6, 4), (7, 4), (8, 4), (13, 4), (14, 2), (24, 2), (30, 2)]
)
def test_factor_lands_the_export_at_24_fps_or_more(source_fps: int, factor: int) -> None:
    assert default_rife_multiplier(source_fps) == factor
    assert source_fps * factor >= 24
    assert get_rife_multiplier_validation_error(factor) is None


def test_other_factors_are_still_refused() -> None:
    assert "unsupported" in (get_rife_multiplier_validation_error(3) or "")


# ---------------------------------------------------------------------------
# defaults: on when RIFE resolves, unchanged when it does not
# ---------------------------------------------------------------------------


def test_controller_default_turns_smoothing_on_only_when_rife_resolves(
    tmp_path: Path, monkeypatch
) -> None:
    executable = _release(tmp_path)
    controller = SVDController(
        app_controller=SimpleNamespace(output_dir="output", job_service=Mock()),
        svd_service=Mock(),
    )

    monkeypatch.setattr(
        "src.controller.svd_controller.find_rife_executable", lambda *_a: executable
    )
    smoothed = controller.build_default_config()
    assert smoothed.postprocess.interpolation.enabled is True
    assert smoothed.postprocess.interpolation.executable_path == str(executable)
    assert smoothed.postprocess.interpolation.multiplier == 4
    assert smoothed.inference.fps * smoothed.postprocess.interpolation.multiplier >= 24

    monkeypatch.setattr("src.controller.svd_controller.find_rife_executable", lambda *_a: None)
    plain = controller.build_default_config()
    assert plain.postprocess.interpolation.enabled is False
    assert plain.postprocess.interpolation.executable_path is None


def test_recommended_defaults_pick_the_factor_from_the_source_fps(
    tmp_path: Path, monkeypatch
) -> None:
    executable = _release(tmp_path)
    monkeypatch.setattr("src.video.svd_capabilities.find_rife_executable", lambda *_a: executable)

    slow = apply_recommended_svd_defaults(SVDConfig.from_dict({"inference": {"fps": 7}}))
    fast = apply_recommended_svd_defaults(SVDConfig.from_dict({"inference": {"fps": 14}}))

    assert slow.postprocess.interpolation.enabled is True
    assert slow.postprocess.interpolation.multiplier == 4
    assert fast.postprocess.interpolation.multiplier == 2


def test_without_rife_the_recommended_config_is_unchanged(monkeypatch) -> None:
    monkeypatch.setattr("src.video.svd_capabilities.find_rife_executable", lambda *_a: None)

    config = apply_recommended_svd_defaults(SVDConfig.from_dict({"inference": {"fps": 7}}))

    assert config.postprocess.interpolation.enabled is False
    assert config.postprocess.interpolation.multiplier == 2


def test_default_export_fps_is_at_least_24_with_rife_and_unchanged_without() -> None:
    config = SVDConfig.from_dict({"inference": {"fps": 7}})
    smoothed = {
        "applied": ["interpolation"],
        "interpolation": {"output_fps": 7 * default_rife_multiplier(7)},
    }

    assert (
        get_effective_svd_export_fps(
            base_fps=config.inference.fps,
            postprocess_metadata=smoothed,
            interpolation_multiplier=4,
        )
        >= 24
    )
    assert (
        get_effective_svd_export_fps(
            base_fps=config.inference.fps, postprocess_metadata=None, interpolation_multiplier=4
        )
        == 7
    )


# ---------------------------------------------------------------------------
# the command that runs
# ---------------------------------------------------------------------------


def _config(executable: Path, **interpolation: object) -> SVDConfig:
    return SVDConfig.from_dict(
        {
            "inference": {"fps": 7},
            "postprocess": {
                "interpolation": {
                    "enabled": True,
                    "executable_path": str(executable),
                    "multiplier": 4,
                    **interpolation,
                }
            },
        }
    )


def test_run_names_the_modern_model_and_records_the_command(tmp_path: Path, monkeypatch) -> None:
    executable = _release(tmp_path / "rife")
    model = _model(tmp_path / "rife", "rife-v4.6")
    _model(tmp_path / "rife", "rife-v2.3")
    commands: list[list[str]] = []

    def _fake_child(self, cmd, *, cwd, timeout_seconds, what):
        commands.append(list(cmd))
        output_dir = Path(cmd[cmd.index("-o") + 1])
        output_dir.mkdir(parents=True, exist_ok=True)
        for index in range(int(cmd[cmd.index("-n") + 1])):
            Image.new("RGB", (8, 8), "white").save(output_dir / f"{index:08d}.png")
        return subprocess.CompletedProcess(cmd, 0, "", "")

    monkeypatch.setattr(SVDPostprocessRunner, "_run_child", _fake_child)
    frames = [Image.new("RGB", (8, 8), "black") for _ in range(3)]

    processed, metadata = SVDPostprocessRunner(repo_root=tmp_path).process_frames(
        frames=frames, config=_config(executable), work_dir=tmp_path / "work"
    )

    assert len(processed) == 12
    assert len(commands) == 1
    assert commands[0][commands[0].index("-m") + 1] == str(model.resolve())
    assert commands[0][commands[0].index("-n") + 1] == "12"
    assert metadata is not None
    recorded = metadata["interpolation"]
    assert recorded["model"] == "rife-v4.6"
    assert recorded["commands"] == commands
    assert recorded["output_fps"] == 28


def test_run_without_a_modern_model_passes_no_model_flag(tmp_path: Path) -> None:
    executable = _release(tmp_path / "rife")
    _model(tmp_path / "rife", "rife-v2.3")
    runner = SVDPostprocessRunner(repo_root=tmp_path)

    command = runner._build_rife_command(
        executable=executable,
        input_dir=tmp_path / "in",
        output_dir=tmp_path / "out",
        postprocess=_config(executable).postprocess,
        target_count=8,
    )

    assert "-m" not in command
    assert command[command.index("-n") + 1] == "8"


def test_a_missing_configured_model_folder_is_refused_before_any_work(tmp_path: Path) -> None:
    executable = _release(tmp_path / "rife")
    config = _config(executable, model_dir=str(tmp_path / "nowhere"))

    valid, reason = validate_svd_postprocess_config(config)

    assert valid is False
    assert reason is not None and "model folder" in reason


def test_a_missing_executable_message_says_how_to_fix_it(monkeypatch) -> None:
    monkeypatch.setattr("src.video.svd_postprocess.find_rife_executable", lambda *_a: None)
    config = SVDConfig.from_dict({"postprocess": {"interpolation": {"enabled": True}}})

    valid, reason = validate_svd_postprocess_config(config)

    assert valid is False
    assert reason is not None and "Locate RIFE" in reason and "tools/rife" in reason
