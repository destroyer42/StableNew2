"""PR-VID-184S: direction-sign helper regression test for ``output_scoring.py``.

The frozen scoring contract (``ROOT_TRANSLATION_DIRECTION_MUST_MATCH``) requires the output's
root-translation direction to match the driving clip's, not just its magnitude. Only
``_direction_sign`` is exercised here: the rest of ``output_scoring.py`` needs cv2/onnxruntime,
which is only available in the disposable CPU venv (see the module docstring), not this suite.
"""

from __future__ import annotations

from tools.qualification.vid184s import output_scoring


def test_direction_sign_left_to_right_is_positive() -> None:
    assert output_scoring._direction_sign(10.0, 20.0) == 1


def test_direction_sign_right_to_left_is_negative() -> None:
    assert output_scoring._direction_sign(20.0, 10.0) == -1


def test_direction_sign_no_net_movement_is_zero() -> None:
    assert output_scoring._direction_sign(15.0, 15.0) == 0


def test_direction_sign_missing_centroid_is_zero() -> None:
    assert output_scoring._direction_sign(None, 20.0) == 0
    assert output_scoring._direction_sign(10.0, None) == 0
    assert output_scoring._direction_sign(None, None) == 0


def test_short_clip_error_is_a_value_error() -> None:
    # trim_to_mp4 itself needs ffmpeg/ffprobe (not exercised here); this only pins the raised
    # type so a caller can catch ShortClipError specifically or ValueError generically.
    assert issubclass(output_scoring.ShortClipError, ValueError)
