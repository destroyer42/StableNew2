"""PR-VID-POST-304: which RealESRGAN weights serve an upscale request (path logic only)."""

from __future__ import annotations

from pathlib import Path

import pytest

from src.video.restoration.upscale_models import (
    SOURCE_BESIDE_MODEL,
    SOURCE_CONFIGURED_X2,
    SOURCE_MODEL_PATH,
    X2_WEIGHT_NAME,
    resolve_upscale_model,
)


def _weights(directory: Path, *names: str) -> dict[str, str]:
    directory.mkdir(parents=True, exist_ok=True)
    paths = {}
    for name in names:
        (directory / name).write_bytes(b"w")
        paths[name] = str(directory / name)
    return paths


def test_a_configured_native_x2_model_serves_a_2x_request(tmp_path: Path) -> None:
    x4 = _weights(tmp_path / "a", "RealESRGAN_x4plus.pth")["RealESRGAN_x4plus.pth"]
    x2 = _weights(tmp_path / "b", "custom_x2.pth")["custom_x2.pth"]

    selection = resolve_upscale_model(scale=2.0, model_path=x4, model_path_x2=x2)

    assert selection is not None
    assert selection.model_path == x2
    assert selection.source == SOURCE_CONFIGURED_X2
    assert selection.expected_native_scale == 2
    assert selection.fallback_reason == ""


def test_x2_weights_beside_the_x4_weights_are_found_without_configuration(tmp_path: Path) -> None:
    paths = _weights(tmp_path, "RealESRGAN_x4plus.pth", X2_WEIGHT_NAME)

    selection = resolve_upscale_model(
        scale=2.0, model_path=paths["RealESRGAN_x4plus.pth"], model_path_x2=None
    )

    assert selection is not None
    assert selection.model_path == paths[X2_WEIGHT_NAME]
    assert selection.source == SOURCE_BESIDE_MODEL
    assert selection.expected_native_scale == 2


def test_a_2x_request_without_x2_weights_falls_back_to_the_x4_model_and_says_so(
    tmp_path: Path,
) -> None:
    x4 = _weights(tmp_path, "RealESRGAN_x4plus.pth")["RealESRGAN_x4plus.pth"]

    selection = resolve_upscale_model(scale=2.0, model_path=x4, model_path_x2=None)

    assert selection is not None
    assert selection.model_path == x4
    assert selection.source == SOURCE_MODEL_PATH
    assert selection.expected_native_scale is None
    assert X2_WEIGHT_NAME in selection.fallback_reason


def test_a_configured_but_missing_x2_path_falls_back_and_names_the_missing_file(
    tmp_path: Path,
) -> None:
    x4 = _weights(tmp_path, "RealESRGAN_x4plus.pth")["RealESRGAN_x4plus.pth"]
    missing = str(tmp_path / "gone_x2.pth")

    selection = resolve_upscale_model(scale=2.0, model_path=x4, model_path_x2=missing)

    assert selection is not None and selection.model_path == x4
    assert missing in selection.fallback_reason


@pytest.mark.parametrize("scale", [1.0, 1.5, 3.0, 4.0])
def test_other_scales_use_the_general_model_even_when_x2_weights_exist(
    tmp_path: Path, scale: float
) -> None:
    paths = _weights(tmp_path, "RealESRGAN_x4plus.pth", X2_WEIGHT_NAME)

    selection = resolve_upscale_model(
        scale=scale, model_path=paths["RealESRGAN_x4plus.pth"], model_path_x2=paths[X2_WEIGHT_NAME]
    )

    assert selection is not None
    assert selection.model_path == paths["RealESRGAN_x4plus.pth"]
    assert selection.fallback_reason == ""  # no 2x was asked for, so nothing fell back


def test_a_2x_request_can_run_on_x2_weights_alone(tmp_path: Path) -> None:
    x2 = _weights(tmp_path, X2_WEIGHT_NAME)[X2_WEIGHT_NAME]

    selection = resolve_upscale_model(scale=2.0, model_path=None, model_path_x2=x2)

    assert selection is not None and selection.model_path == x2


def test_nothing_usable_resolves_to_none(tmp_path: Path) -> None:
    assert resolve_upscale_model(scale=2.0, model_path=None, model_path_x2=None) is None
    assert (
        resolve_upscale_model(
            scale=2.0, model_path=str(tmp_path / "missing.pth"), model_path_x2=None
        )
        is None
    )
    only_x2 = _weights(tmp_path, X2_WEIGHT_NAME)[X2_WEIGHT_NAME]
    assert resolve_upscale_model(scale=4.0, model_path=None, model_path_x2=only_x2) is None


def test_the_selection_serialises_for_the_run_manifest(tmp_path: Path) -> None:
    paths = _weights(tmp_path, "RealESRGAN_x4plus.pth", X2_WEIGHT_NAME)
    selection = resolve_upscale_model(
        scale=2.0, model_path=paths["RealESRGAN_x4plus.pth"], model_path_x2=None
    )

    assert selection is not None
    assert selection.to_dict() == {
        "model_path": paths[X2_WEIGHT_NAME],
        "model_name": X2_WEIGHT_NAME,
        "requested_scale": 2.0,
        "source": SOURCE_BESIDE_MODEL,
        "expected_native_scale": 2,
        "fallback_reason": "",
    }
