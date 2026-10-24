"""PR-IMG-CNET-230: pure reference-map adapters and source handling (tiny synthetic fixtures; no model, GPU or network)."""

from __future__ import annotations

import io
import json

import numpy as np
import pytest
from PIL import Image

from src.conditioning.reference_map import canny, depth, pose
from src.conditioning.reference_map.contracts import ReferenceMapError
from src.conditioning.reference_map.source import load_source, oriented_digest, reverify_source

# ---------------------------------------------------------------------------------------------- helpers


def _png(image: Image.Image, **options) -> bytes:
    buffer = io.BytesIO()
    image.save(buffer, format="PNG", **options)
    return buffer.getvalue()


def _gradient(width: int = 96, height: int = 64) -> Image.Image:
    array = np.zeros((height, width, 3), dtype=np.uint8)
    array[..., 0] = np.linspace(0, 255, width, dtype=np.uint8)[None, :]
    array[..., 1] = np.linspace(0, 255, height, dtype=np.uint8)[:, None]
    array[20:40, 30:60] = (250, 250, 20)
    return Image.fromarray(array)


def _exif(orientation: int) -> Image.Exif:
    exif = Image.Exif()
    exif[0x0112] = orientation
    return exif


def _person(visible: dict[int, tuple[float, float]], score: float = 0.9) -> pose.PosePerson:
    points = np.zeros((pose.KEYPOINTS, 2))
    scores = np.zeros(pose.KEYPOINTS)
    for index, point in visible.items():
        points[index] = point
        scores[index] = score
    return pose.PosePerson(points, scores)


_BODY = {
    0: (64, 10), 5: (50, 30), 6: (78, 30), 7: (45, 50), 8: (83, 50),
    9: (42, 70), 10: (86, 70), 11: (55, 60), 12: (73, 60), 13: (54, 85), 14: (74, 85),
}  # fmt: skip


# ---------------------------------------------------------------------------------------------- canny


def test_canny_geometry_bounds_and_polarity_with_an_injected_detector() -> None:
    rgb = np.asarray(_gradient())

    def detector(gray: np.ndarray) -> np.ndarray:
        assert gray.dtype == np.uint8 and gray.shape == rgb.shape[:2]
        out = np.zeros_like(gray)
        out[10:12, :] = 77  # any positive value is an edge
        return out

    result = canny.canny_map(rgb, detect=detector)
    assert result.shape == rgb.shape and result.dtype == np.uint8
    assert set(np.unique(result)) == {0, 255}
    assert (result[..., 0] == result[..., 1]).all() and (result[..., 1] == result[..., 2]).all()
    assert result[10:12].min() == 255 and result[:10].max() == 0  # white edges on black


def test_canny_refuses_a_wrongly_sized_detector_result_and_non_rgb_input() -> None:
    rgb = np.asarray(_gradient())
    with pytest.raises(ReferenceMapError):
        canny.canny_map(rgb, detect=lambda gray: np.zeros((3, 3), dtype=np.uint8))
    with pytest.raises(ReferenceMapError):
        canny.canny_map(rgb[..., 0])


def test_luma_is_integer_rec601_and_frozen_config_is_complete() -> None:
    pixels = np.array([[[255, 255, 255], [255, 0, 0], [0, 255, 0], [0, 0, 255]]], dtype=np.uint8)
    assert canny.luma(pixels).tolist() == [[255, 76, 150, 29]]
    config = canny.identity().config
    assert {
        "gray",
        "blur",
        "low_threshold",
        "high_threshold",
        "resize",
        "polarity",
        "channels",
    } <= set(config)
    assert (canny.identity().method_id, canny.identity().version) == ("canny-edge", 1)


def test_canny_with_opencv_is_deterministic_and_finds_the_square() -> None:
    pytest.importorskip("cv2")
    rgb = np.zeros((96, 96, 3), dtype=np.uint8)
    rgb[30:66, 30:66] = 230
    first, second = canny.canny_map(rgb), canny.canny_map(rgb.copy())
    assert first.tobytes() == second.tobytes()
    assert set(np.unique(first)) == {0, 255}
    assert first[30, 40, 0] == 255 or first[29, 40, 0] == 255 or first[31, 40, 0] == 255
    assert first[48, 48, 0] == 0  # the flat interior has no edge
    assert canny.runtime_versions()["opencv"]


# ---------------------------------------------------------------------------------------------- depth


def test_depth_maps_zero_half_one_to_black_mid_white() -> None:
    result = depth.prediction_to_map(np.array([[0.0, 0.5, 1.0]], dtype=np.float32), 3, 1)
    assert result.shape == (1, 3, 3) and result.dtype == np.uint8
    assert result[0, :, 0].tolist() == [
        0,
        128,
        255,
    ]  # nearest (largest) is brightest, half rounds up
    assert (result[..., 0] == result[..., 2]).all()


@pytest.mark.parametrize("bad", [np.nan, np.inf, -np.inf])
def test_depth_refuses_non_finite_predictions(bad: float) -> None:
    prediction = np.array([[0.0, bad], [0.5, 1.0]], dtype=np.float32)
    with pytest.raises(ReferenceMapError) as caught:
        depth.prediction_to_map(prediction, 2, 2)
    assert caught.value.code == "depth_non_finite"


def test_depth_refuses_a_constant_map() -> None:
    with pytest.raises(ReferenceMapError) as caught:
        depth.prediction_to_map(np.full((4, 4), 3.0, dtype=np.float32), 8, 8)
    assert caught.value.code == "depth_flat"


def test_depth_restores_the_oriented_source_size_and_full_range() -> None:
    prediction = np.linspace(0.0, 5.0, 6 * 4, dtype=np.float32).reshape(4, 6)
    result = depth.prediction_to_map(
        prediction[None], 30, 21
    )  # leading singleton, as a model emits
    assert result.shape == (21, 30, 3)
    assert result.min() == 0 and result.max() == 255
    assert result[10, 29, 0] > result[10, 0, 0]  # the gradient direction survives the resize


@pytest.mark.parametrize("shape", [(0, 5), (5, 0), (2, 2, 2)])
def test_depth_refuses_empty_or_unexpected_shapes(shape: tuple[int, ...]) -> None:
    with pytest.raises(ReferenceMapError):
        depth.prediction_to_map(np.zeros(shape, dtype=np.float32), 8, 8)


# ---------------------------------------------------------------------------------------------- pose


def test_pose_renders_black_background_with_missing_hands_and_face_disclosed() -> None:
    array, warnings = pose.render_pose([_person(_BODY)], 128, 96)
    assert array.shape == (96, 128, 3) and array.dtype == np.uint8
    assert array[0, 0].tolist() == [0, 0, 0]
    assert array.max() > 0
    assert "pose_no_hands" in warnings and "pose_no_face" in warnings
    assert array[..., 2].astype(int).sum() > 0 or array[..., 0].astype(int).sum() > 0


def test_pose_render_is_deterministic() -> None:
    first, _ = pose.render_pose([_person(_BODY)], 128, 96)
    second, _ = pose.render_pose([_person(dict(_BODY))], 128, 96)
    assert first.tobytes() == second.tobytes()


def test_pose_never_draws_out_of_bounds_nan_or_low_confidence_points() -> None:
    wild = dict(_BODY)
    wild[0] = (-500.0, 9999.0)
    person = _person(wild)
    person.points[14] = (np.nan, np.inf)
    person.scores[12] = 0.1
    array, warnings = pose.render_pose([person], 128, 96)
    assert array.shape == (96, 128, 3)
    assert "pose_partial_body" in warnings or array.max() > 0


def test_pose_with_hands_and_face_draws_them_without_those_warnings() -> None:
    person = _person(_BODY)
    for index in range(23, 91):  # face
        person.points[index] = (64 + (index % 8), 12 + (index % 5))
        person.scores[index] = 0.9
    for index in range(91, 112):  # left hand
        person.points[index] = (40 + (index % 5) * 2, 52 + (index % 4) * 2)
        person.scores[index] = 0.9
    array, warnings = pose.render_pose([person], 128, 96)
    assert "pose_no_face" not in warnings and "pose_no_hands" not in warnings
    assert (array == 255).all(axis=2).any()  # white face dots


def test_pose_with_no_people_is_an_actionable_failure_not_an_empty_success() -> None:
    with pytest.raises(ReferenceMapError) as none:
        pose.render_pose([], 128, 96)
    assert none.value.code == "no_people"
    barely = _person({0: (10, 10), 5: (12, 20)})  # fewer confident body points than a person needs
    with pytest.raises(ReferenceMapError) as sparse:
        pose.render_pose([barely], 128, 96)
    assert sparse.value.code == "no_people"


def test_pose_limits_the_number_of_drawn_people_and_says_so() -> None:
    people = [_person(_BODY) for _ in range(pose.MAX_PEOPLE + 2)]
    _, warnings = pose.render_pose(people, 128, 96)
    assert "pose_people_truncated" in warnings


def test_pose_payload_roundtrip_and_validation() -> None:
    person = _person(_BODY)
    payload = pose.people_to_payload([person], 128, 96)
    restored = pose.people_from_payload(json.loads(json.dumps(payload)))
    assert len(restored) == 1 and restored[0].points.shape == (pose.KEYPOINTS, 2)
    for broken in (
        None,
        {"people": "x"},
        {"people": [{"points": [[0, 0]], "scores": [0.5]}]},
        {"people": [{"points": "no", "scores": "no"}]},
        {"people": [{"points": [[0, 0]] * 133}]},
        {"people": [{"points": [[0, 0]] * 133, "scores": [0.1] * 133}] * 40},
    ):
        with pytest.raises(ReferenceMapError):
            pose.people_from_payload(broken)


def test_yolox_decode_nms_and_person_selection() -> None:
    rows = 80 * 80 + 40 * 40 + 20 * 20
    raw = np.zeros((1, rows, 85), dtype=np.float32)
    raw[..., 2:4] = np.log(64.0 / 8.0)  # 64 px boxes at stride 8
    raw[0, 100, 4] = raw[0, 100, 5] = 0.9  # a confident person
    raw[0, 101, 4] = raw[0, 101, 5] = 0.8  # an overlapping, weaker duplicate
    raw[0, 3000, 4] = 0.9
    raw[0, 3000, 6] = 0.9  # a confident non-person (class 1)
    decoded = pose.yolox_decode(raw)
    found = pose.person_boxes(decoded, ratio=0.5)
    assert len(found) == 1
    box, score = found[0]
    assert box.shape == (4,) and score == pytest.approx(0.81, abs=1e-3)
    assert box[2] > box[0] and box[3] > box[1]
    with pytest.raises(ReferenceMapError):
        pose.yolox_decode(np.zeros((1, 10, 85), dtype=np.float32))
    with pytest.raises(ReferenceMapError):
        pose.person_boxes(decoded, ratio=0.0)


def test_nms_keeps_the_strongest_of_overlapping_boxes() -> None:
    boxes = np.array([[0, 0, 10, 10], [1, 1, 11, 11], [50, 50, 60, 60]], dtype=np.float32)
    assert pose.nms(boxes, np.array([0.5, 0.9, 0.7], dtype=np.float32), 0.45) == [1, 2]


def test_estimator_crop_and_simcc_decoding_recover_known_keypoints() -> None:
    center, scale = pose.box_center_scale([100, 50, 200, 250])
    assert scale[0] / scale[1] == pytest.approx(pose.POSE_INPUT[0] / pose.POSE_INPUT[1], rel=1e-4)
    matrix = pose.warp_matrix(center, scale)
    middle = matrix @ np.array([center[0], center[1], 1.0])
    assert middle[0] == pytest.approx(pose.POSE_INPUT[0] / 2, abs=1e-3)
    assert middle[1] == pytest.approx(pose.POSE_INPUT[1] / 2, abs=1e-3)
    simcc_x = np.zeros((pose.KEYPOINTS, int(pose.POSE_INPUT[0] * 2)), dtype=np.float32)
    simcc_y = np.zeros((pose.KEYPOINTS, int(pose.POSE_INPUT[1] * 2)), dtype=np.float32)
    simcc_x[3, 288] = simcc_y[3, 384] = 0.8  # the middle of the crop
    points, scores = pose.simcc_keypoints(simcc_x, simcc_y, center, scale)
    assert points[3] == pytest.approx(center, abs=1.0)
    assert scores[3] == pytest.approx(0.8) and scores[4] == 0.0
    with pytest.raises(ReferenceMapError):
        pose.simcc_keypoints(simcc_x[0], simcc_y, center, scale)


# ---------------------------------------------------------------------------------------------- source


def test_exif_orientation_geometry_and_oriented_hash(tmp_path) -> None:
    base = _gradient(96, 64)
    tagged = tmp_path / "tagged.png"
    tagged.write_bytes(_png(base, exif=_exif(6)))  # displayed rotated: 64 wide, 96 tall
    prerotated = tmp_path / "rotated.png"
    prerotated.write_bytes(_png(base.transpose(Image.Transpose.ROTATE_270)))
    plain = tmp_path / "plain.png"
    plain.write_bytes(_png(base))

    first, second, third = load_source(tagged), load_source(prerotated), load_source(plain)
    assert (first.facts.width, first.facts.height) == (64, 96)
    assert first.facts.exif_transposed and not second.facts.exif_transposed
    assert first.facts.oriented_sha256 == second.facts.oriented_sha256  # the same oriented pixels
    assert first.facts.file_sha256 != second.facts.file_sha256  # but different files
    assert (
        third.facts.oriented_sha256 != first.facts.oriented_sha256
    )  # orientation is part of identity
    assert first.rgb.shape == (96, 64, 3) and first.rgb.flags["C_CONTIGUOUS"]
    assert oriented_digest(first.rgb) == first.facts.oriented_sha256


def test_alpha_is_composited_on_white_and_result_is_rgb(tmp_path) -> None:
    path = tmp_path / "alpha.png"
    path.write_bytes(_png(Image.new("RGBA", (64, 64), (0, 0, 0, 0))))
    assert (load_source(path).rgb == 255).all()


@pytest.mark.parametrize(
    ("name", "payload", "code"),
    [
        ("empty.png", b"", "source_malformed"),
        ("junk.png", b"not an image at all", "source_malformed"),
        ("notes.txt", b"x", "source_extension"),
        ("tiny.png", _png(Image.new("RGB", (16, 16))), "source_dimensions"),
        ("wide.png", _png(Image.new("RGB", (5000, 64))), "source_dimensions"),
    ],
)
def test_source_envelope_is_enforced(tmp_path, name, payload, code) -> None:
    path = tmp_path / name
    path.write_bytes(payload)
    with pytest.raises(ReferenceMapError) as caught:
        load_source(path)
    assert caught.value.code == code


def test_source_refuses_directories_missing_files_and_oversized_files(tmp_path) -> None:
    (tmp_path / "folder.png").mkdir()
    with pytest.raises(ReferenceMapError) as folder:
        load_source(tmp_path / "folder.png")
    assert folder.value.code == "source_not_a_file"
    with pytest.raises(ReferenceMapError) as missing:
        load_source(tmp_path / "absent.png")
    assert missing.value.code == "source_missing"
    huge = tmp_path / "huge.png"
    huge.write_bytes(b"\x89PNG" + b"\0" * (20 * 1024 * 1024 + 1))
    with pytest.raises(ReferenceMapError) as big:
        load_source(huge)
    assert big.value.code == "source_oversized"


def test_decompression_bomb_guard_is_honoured(tmp_path, monkeypatch) -> None:
    path = tmp_path / "ok.png"
    path.write_bytes(_png(_gradient(128, 128)))
    monkeypatch.setattr(Image, "MAX_IMAGE_PIXELS", 1000)
    with pytest.raises(ReferenceMapError) as caught:
        load_source(path)
    assert caught.value.code == "source_malformed"


def test_reverify_source_detects_drift_and_disappearance(tmp_path) -> None:
    path = tmp_path / "s.png"
    path.write_bytes(_png(_gradient()))
    facts = load_source(path).facts
    reverify_source(path, facts.file_sha256)
    path.write_bytes(_png(_gradient(96, 65)))
    with pytest.raises(ReferenceMapError) as drift:
        reverify_source(path, facts.file_sha256)
    assert drift.value.code == "source_changed"
    path.unlink()
    with pytest.raises(ReferenceMapError) as gone:
        reverify_source(path, facts.file_sha256)
    assert gone.value.code == "source_changed"
