"""PR-VID-POST-304 / decision D8: GFPGAN is retired from SVD; one face-fidelity default everywhere.

A stored config or NJR that still names GFPGAN must keep loading, and an *enabled* one is refused
at admission with the existing readable message before any generation starts.
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from src.controller.svd_controller import SVDController
from src.video.restoration.runtime import GFPGAN_UNSUPPORTED_ISSUE
from src.video.svd_capabilities import apply_recommended_svd_defaults
from src.video.svd_config import (
    DEFAULT_FACE_RESTORE_FIDELITY,
    OFFERED_FACE_RESTORE_METHODS,
    RETIRED_FACE_RESTORE_METHODS,
    SVDConfig,
    SVDFaceRestoreConfig,
)
from src.video.svd_errors import SVDPostprocessError
from src.video.svd_postprocess import validate_svd_postprocess_config
from src.video.svd_runner import SVDRunner


def _legacy_gfpgan_config(*, enabled: bool) -> dict:
    """The shape a pre-retirement NJR froze: GFPGAN selected, its own weight path recorded."""

    return {
        "postprocess": {
            "face_restore": {
                "enabled": enabled,
                "method": "GFPGAN",
                "fidelity_weight": 0.7,
                "gfpgan_weight_path": "C:/models/GFPGAN/GFPGANv1.4.pth",
                "facelib_model_root": "C:/models/GFPGAN",
            }
        }
    }


def test_gfpgan_is_retired_not_offered() -> None:
    assert OFFERED_FACE_RESTORE_METHODS == ("CodeFormer",)
    assert RETIRED_FACE_RESTORE_METHODS == ("GFPGAN",)


@pytest.mark.parametrize("enabled", [True, False])
def test_a_stored_config_naming_gfpgan_still_loads_and_round_trips(enabled: bool) -> None:
    config = SVDConfig.from_dict(_legacy_gfpgan_config(enabled=enabled))

    assert config.postprocess.face_restore.method == "GFPGAN"
    assert config.postprocess.face_restore.enabled is enabled
    again = SVDConfig.from_dict(config.to_dict())
    assert again.postprocess.face_restore == config.postprocess.face_restore


def test_an_enabled_gfpgan_config_is_refused_with_the_readable_message() -> None:
    config = SVDConfig.from_dict(_legacy_gfpgan_config(enabled=True))

    valid, reason = validate_svd_postprocess_config(config)

    assert valid is False
    assert reason is not None
    assert "GFPGAN is enabled" in reason and GFPGAN_UNSUPPORTED_ISSUE in reason


def test_a_disabled_gfpgan_config_is_inert_and_stays_valid() -> None:
    config = SVDConfig.from_dict(_legacy_gfpgan_config(enabled=False))

    assert validate_svd_postprocess_config(config) == (True, None)


def test_admission_refuses_an_enabled_gfpgan_job_without_submitting_anything(
    tmp_path: Path,
) -> None:
    job_service = Mock()
    controller = SVDController(
        app_controller=SimpleNamespace(output_dir=str(tmp_path), job_service=job_service),
        svd_service=Mock(),
    )
    source = tmp_path / "source.png"
    source.write_bytes(b"png")

    with pytest.raises(RuntimeError, match="GFPGAN is enabled"):
        controller.submit_svd_job(
            source_image_path=source,
            config=SVDConfig.from_dict(_legacy_gfpgan_config(enabled=True)),
        )

    job_service.submit_njrs.assert_not_called()


def test_a_frozen_njr_naming_gfpgan_loads_and_is_refused_before_any_generation(
    tmp_path: Path,
) -> None:
    controller = SVDController(
        app_controller=SimpleNamespace(output_dir=str(tmp_path), job_service=Mock()),
        svd_service=Mock(),
    )
    source = tmp_path / "source.png"
    source.write_bytes(b"png")
    frozen = SVDConfig.from_dict(_legacy_gfpgan_config(enabled=True))
    njr = controller._build_svd_njr(source_image_path=source, config=frozen, output_route=None)

    # What the executor does with the frozen stage config when the job reaches the runner.
    loaded = SVDConfig.from_dict(njr.config["svd_native"])
    service = Mock()
    runner = SVDRunner(service=service, output_root=tmp_path / "out")

    assert loaded.postprocess.face_restore.method == "GFPGAN"
    with pytest.raises(SVDPostprocessError, match="GFPGAN is enabled"):
        runner.run(source_image_path=source, config=loaded, job_id="old-job")
    service.prepare_runtime.assert_not_called()
    service.generate_frames.assert_not_called()


def test_recommended_defaults_never_pick_gfpgan() -> None:
    config = apply_recommended_svd_defaults(
        SVDConfig.from_dict(_legacy_gfpgan_config(enabled=True))
    )

    assert config.postprocess.face_restore.method == "CodeFormer"


# --- one fidelity default ------------------------------------------------------------------------


def test_every_origin_agrees_on_the_default_face_fidelity() -> None:
    controller = SVDController(app_controller=SimpleNamespace(output_dir="out"), svd_service=Mock())

    values = {
        "dataclass": SVDFaceRestoreConfig().fidelity_weight,
        "from_dict": SVDFaceRestoreConfig.from_dict({}).fidelity_weight,
        "controller": controller.build_default_config().postprocess.face_restore.fidelity_weight,
    }

    assert set(values.values()) == {DEFAULT_FACE_RESTORE_FIDELITY}
    assert DEFAULT_FACE_RESTORE_FIDELITY == 0.85


def test_a_frozen_fidelity_is_kept_when_a_config_is_reloaded() -> None:
    config = SVDConfig.from_dict({"postprocess": {"face_restore": {"fidelity_weight": 0.6}}})

    assert config.postprocess.face_restore.fidelity_weight == 0.6
    assert SVDConfig.from_dict(config.to_dict()).postprocess.face_restore.fidelity_weight == 0.6


def test_temporal_smoothing_defaults_on_and_a_stored_choice_survives() -> None:
    assert SVDFaceRestoreConfig().temporal_smoothing is True
    assert SVDFaceRestoreConfig.from_dict({}).temporal_smoothing is True
    off = SVDConfig.from_dict({"postprocess": {"face_restore": {"temporal_smoothing": False}}})
    assert SVDConfig.from_dict(off.to_dict()).postprocess.face_restore.temporal_smoothing is False


def test_the_controller_default_config_enables_temporal_smoothing() -> None:
    controller = SVDController(app_controller=SimpleNamespace(output_dir="out"), svd_service=Mock())

    assert controller.build_default_config().postprocess.face_restore.temporal_smoothing is True
