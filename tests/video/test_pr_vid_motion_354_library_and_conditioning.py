"""PR-VID-MOTION-354: converted clips in the Motion Library, and the advisory Canny conditioning preview."""

from __future__ import annotations

import hashlib
import json
from fractions import Fraction
from pathlib import Path

import numpy as np
import pytest

from src.video.motion_conversion import conditioning_preview as cond
from src.video.motion_conversion import conversion_plan as cp
from src.video.motion_conversion.conversion_service import PROVENANCE_NAME, MotionConverter
from src.video.motion_conversion.library_bridge import accept_conversion, suggested_tags
from src.video.motion_library.derivation import derivation_lines
from src.video.motion_library.models import MotionAsset
from src.video.motion_library.search import SearchQuery, search_assets
from src.video.motion_library.store import MotionLibraryStore
from tests.helpers.motion_conversion_354 import (
    MIXAMO_BONES,
    fake_environ,
    fake_install,
    sha256,
    write_fbx,
)
from tests.helpers.motion_library_353 import (
    FFMPEG,
    FakeInspector,
    make_clip,
    needs_ffmpeg,
    new_store,
)

PROBE = cp.AnimationProbe(Fraction(24), Fraction(1), Fraction(121), MIXAMO_BONES, True, "4.2.3")


def _convert(tmp_path: Path, *, purpose: str = "accepted", **overrides):
    source = write_fbx(tmp_path / "src" / "Idle Walk.fbx")
    options = {
        "source_path": str(source),
        "source_sha256": sha256(source),
        "source_route": cp.SOURCE_FBX_CHARACTER,
        "probe": PROBE,
        "profile": cp.PROFILE_SILHOUETTE,
        "camera": cp.CAMERA_SIDE,
        "output_frames": 9,
        "width": 256,
        "height": 272,
    }
    options.update(overrides)
    plan = cp.build_plan(**options)
    converter = MotionConverter(
        fake_install(tmp_path / "bin"),
        tmp_path / "out",
        ffmpeg=FFMPEG or "ffmpeg",
        environ=fake_environ(),
    )
    return plan, converter.convert(plan, purpose=purpose)


# ------------------------------------------------------------------ library


@needs_ffmpeg
def test_accepting_a_conversion_uses_the_existing_catalog_and_keeps_original_and_derivative_apart(
    tmp_path: Path,
) -> None:
    plan, result = _convert(tmp_path)
    store = new_store(tmp_path)
    outcome = accept_conversion(
        store, result.directory, name="Side walk", extra_tags=("walk",), inspect=FakeInspector()
    )
    assert outcome.status == "imported", outcome.reason
    asset = store.require(outcome.asset_id)
    assert asset.sha256 == result.output_sha256 != plan.source_sha256
    assert asset.derivation is not None and asset.derivation.source_sha256 == plan.source_sha256
    assert asset.source_category == "rendered_mocap" and asset.viewpoint == "side"
    assert (
        asset.camera_movement == "static"
        and asset.framing == "full_body"
        and asset.review_status == "unreviewed"
    )
    for tag in (
        "derived",
        "source-fbx",
        "silhouette-render",
        "view-side",
        "static-camera",
        "root-motion",
        "walk",
    ):
        assert tag in asset.tags
    assert asset.locator.mode == "linked" and asset.locator.path == result.video_path
    assert plan.source_sha256 in asset.provenance_notes


@needs_ffmpeg
def test_derivation_survives_a_restart_and_is_found_by_ordinary_search(tmp_path: Path) -> None:
    _, result = _convert(tmp_path)
    store = new_store(tmp_path)
    accept_conversion(store, result.directory, inspect=FakeInspector())
    reopened = MotionLibraryStore(store.root)
    asset = reopened.assets()[0]
    assert asset.derivation is not None and asset.derivation.profile == "high_contrast_silhouette"
    assert search_assets(reopened.assets(), SearchQuery(tags=("derived",))) == [asset]
    assert search_assets(reopened.assets(), SearchQuery(text="silhouette-render")) == [asset]
    assert search_assets(reopened.assets(), SearchQuery(tags=("view-front",))) == []
    assert MotionAsset.from_dict(asset.to_dict()) == asset


@needs_ffmpeg
def test_importing_the_same_bytes_again_keeps_one_identity_and_the_first_derivation(
    tmp_path: Path,
) -> None:
    _, result = _convert(tmp_path)
    store = new_store(tmp_path)
    first = accept_conversion(store, result.directory, inspect=FakeInspector())
    second = accept_conversion(store, result.directory, inspect=FakeInspector())
    assert second.status == "duplicate" and second.asset_id == first.asset_id
    assert len(store.assets()) == 1 and store.assets()[0].derivation is not None


@needs_ffmpeg
def test_a_preview_stale_or_tampered_conversion_cannot_enter_the_library(tmp_path: Path) -> None:
    store = new_store(tmp_path)
    _, preview = _convert(tmp_path / "p", purpose="preview")
    refused = accept_conversion(store, preview.directory, inspect=FakeInspector())
    assert refused.status == "failed" and "preview" in refused.reason.lower()
    _, result = _convert(tmp_path / "a")
    Path(result.video_path).write_bytes(b"tampered")
    stale = accept_conversion(store, result.directory, inspect=FakeInspector())
    assert stale.status == "failed" and "no longer matches" in stale.reason
    assert store.assets() == ()


@needs_ffmpeg
def test_importing_never_moves_or_deletes_the_original_or_the_published_files(
    tmp_path: Path,
) -> None:
    plan, result = _convert(tmp_path)
    before = (sha256(Path(plan.source_path)), sha256(Path(result.video_path)))
    accept_conversion(new_store(tmp_path), result.directory, inspect=FakeInspector())
    assert (sha256(Path(plan.source_path)), sha256(Path(result.video_path))) == before
    assert (Path(result.directory) / PROVENANCE_NAME).is_file()


def test_detail_text_is_honest_when_the_original_file_is_missing() -> None:
    from src.video.motion_library.models import DerivationRecord

    record = DerivationRecord(
        "a" * 64,
        "fbx",
        "Walk.fbx",
        "C:/gone/Walk.fbx",
        profile="skeleton_reference",
        camera="three_quarter",
        camera_mode="tracking",
        root_motion="in_place",
        blender_version="4.2.3",
        script_version="1",
    )
    missing = "\n".join(derivation_lines(record, source_present=False))
    present = "\n".join(derivation_lines(record, source_present=True))
    assert "NOT found" in missing and "unaffected" in missing and "present" in present
    assert "not an OpenPose map" in missing and "root translation removed" in missing
    assert "a" * 64 in missing


def test_suggested_tags_state_facts_only() -> None:
    record = {
        "source": {"type": "bvh"},
        "conversion": {
            "profile": "skeleton_reference",
            "camera": "three_quarter",
            "camera_mode": "tracking",
            "root_motion": "in_place",
        },
    }
    tags = suggested_tags(record, ("Arm Raise",))
    assert {
        "derived",
        "source-bvh",
        "skeleton-render",
        "view-three-quarter",
        "tracking-camera",
        "in-place",
    } <= set(tags)
    assert not {"good", "best", "high-quality"} & set(tags)


# ------------------------------------------------------------------ conditioning preview


def test_canny_finds_the_outline_of_a_shape_and_nothing_in_a_flat_image() -> None:
    flat = np.full((64, 64), 0.5, dtype=np.float32)
    assert not cond.canny_edges(flat).any()
    shape = np.zeros((64, 64), dtype=np.float32)
    shape[16:48, 20:44] = 1.0
    edges = cond.canny_edges(shape)
    assert edges.any() and not edges[28:36, 28:36].any()  # an outline, not a filled region
    ys, xs = np.nonzero(edges)
    assert (
        12 <= ys.min() <= 20
        and 44 <= ys.max() <= 52
        and 16 <= xs.min() <= 24
        and 40 <= xs.max() <= 48
    )
    assert edges.mean() < 0.12


def test_canny_is_deterministic_and_rejects_color_arrays() -> None:
    img = (np.indices((48, 48)).sum(axis=0) % 7 / 7.0).astype(np.float32)
    assert np.array_equal(cond.canny_edges(img), cond.canny_edges(img))
    with pytest.raises(ValueError):
        cond.canny_edges(np.zeros((8, 8, 3), dtype=np.float32))


def test_the_result_is_never_labeled_exact_until_parity_is_actually_verified() -> None:
    assert cond.EXACT_PARITY_VERIFIED is False
    assert (cond.LOW_THRESHOLD, cond.HIGH_THRESHOLD) == (0.1, 0.6)
    warnings = cond.advisory_warnings(
        densities=[0.02],
        border_shares=[0.0],
        motion_diffs=[0.05],
        video_aspect=0.5,
        target_aspect=0.5,
        reference_iou=None,
        downscaled=False,
    )
    assert warnings[0] == cond.EXACTNESS_REASON and "not verified" in warnings[0]


def test_heuristic_warnings_are_truthful_and_bounded() -> None:
    quiet = cond.advisory_warnings(
        densities=[0.02],
        border_shares=[0.0],
        motion_diffs=[0.05],
        video_aspect=0.5769,
        target_aspect=0.5769,
        reference_iou=0.9,
        downscaled=False,
    )
    assert len(quiet) == 1  # only the exactness note
    noisy = cond.advisory_warnings(
        densities=[0.0005],
        border_shares=[0.6],
        motion_diffs=[0.4],
        video_aspect=1.78,
        target_aspect=0.58,
        reference_iou=0.1,
        downscaled=True,
    )
    dense = cond.advisory_warnings(
        densities=[0.3, 0.2],
        border_shares=[0.0],
        motion_diffs=[0.05],
        video_aspect=0.58,
        target_aspect=0.58,
        reference_iou=None,
        downscaled=False,
    )
    static = cond.advisory_warnings(
        densities=[0.02],
        border_shares=[0.0],
        motion_diffs=[0.0001],
        video_aspect=0.58,
        target_aspect=0.58,
        reference_iou=None,
        downscaled=False,
    )
    text = " ".join(noisy) + " " + " ".join(dense) + " " + " ".join(static)
    for phrase in (
        "reduced size",
        "Very few edges",
        "very dense",
        "cropped",
        "near static",
        "camera movement",
        "center-cropped",
        "barely overlaps",
    ):
        assert phrase in text
    assert "quality score" not in text.lower() and "identity" not in text.lower()
    assert len(noisy) <= 10


def test_sample_indices_are_ascending_distinct_and_cover_the_window() -> None:
    picks = cond.sample_indices(10, 49)
    assert picks == sorted(set(picks)) and picks[0] == 10 and picks[-1] == 58 and len(picks) <= 11
    assert cond.sample_indices(0, 1) == [0] and cond.sample_indices(0, 0) == []


def test_png_encoder_round_trips_through_pillow() -> None:
    import io

    from PIL import Image

    arr = (np.indices((6, 9)).sum(axis=0) * 10).astype(np.uint8)
    decoded = np.asarray(Image.open(io.BytesIO(cond.encode_png(arr))))
    assert np.array_equal(decoded, arr)


@needs_ffmpeg
def test_build_preview_on_a_real_tiny_clip_reports_first_middle_last_and_never_claims_exactness(
    tmp_path: Path,
) -> None:
    from src.video.driving_video_inspection import inspect_driving_video

    clip = make_clip(tmp_path, "t.mp4", frames=24, size="128x96")
    inspection = inspect_driving_video(clip, frame_count=0)
    sha = hashlib.sha256(clip.read_bytes()).hexdigest()
    preview = cond.build_preview(
        clip,
        ffmpeg=FFMPEG,
        facts=inspection.facts,
        target_size=(480, 832),
        video_sha256=sha,
        derivative_of_sha256="b" * 64,
        window_start=2,
        window_frames=17,
    )
    assert preview.ok, preview.error
    assert (
        preview.exactness == cond.EXACTNESS_APPROXIMATE
        and not preview.exactness == cond.EXACTNESS_EXACT
    )
    assert [f.label for f in preview.frames] == ["First", "Middle", "Last"]
    assert [f.frame_index for f in preview.frames] == [2, 10, 18]
    assert (
        preview.video_sha256 == sha
        and preview.derivative_of_sha256 == "b" * 64
        and preview.window_frames == 17
    )
    assert any("center-cropped" in w for w in preview.warnings)  # 4:3 clip into a portrait target
    assert all(
        f.edge_png.startswith(b"\x89PNG") and f.source_png.startswith(b"\x89PNG")
        for f in preview.frames
    )
    assert json.dumps(preview.stats)


@needs_ffmpeg
def test_build_preview_refuses_a_window_outside_the_video(tmp_path: Path) -> None:
    from src.video.driving_video_inspection import inspect_driving_video

    clip = make_clip(tmp_path, "t.mp4", frames=12, size="64x48")
    facts_ = inspect_driving_video(clip, frame_count=0).facts
    outside = cond.build_preview(
        clip, ffmpeg=FFMPEG, facts=facts_, target_size=(480, 832), window_start=8, window_frames=17
    )
    assert not outside.ok and "outside the video" in outside.error


def test_preview_calls_no_comfy_and_changes_no_job_state() -> None:
    import inspect as py_inspect

    source = py_inspect.getsource(cond)
    for forbidden in (
        "requests",
        "urllib",
        "socket",
        "ComfyClient",
        "NormalizedJobRecord",
        "JobService",
    ):
        assert forbidden not in source


def test_the_preview_center_crops_like_the_pinned_node_instead_of_stretching() -> None:
    import numpy as np

    wide = np.zeros((100, 200, 3), dtype=np.uint8)
    wide[:, 0:50] = 10
    wide[:, 150:200] = 20
    wide[:, 50:150] = 255
    portrait = cond.center_crop_to_aspect(wide, 50, 100)  # aspect 0.5: keeps the middle 50 columns
    assert portrait.shape == (100, 50, 3) and int(portrait.min()) == 255

    tall = np.zeros((300, 100, 3), dtype=np.uint8)
    landscape = cond.center_crop_to_aspect(tall, 200, 100)  # aspect 2: keeps the middle 50 rows
    assert landscape.shape == (50, 100, 3)
    same = np.zeros((832, 480, 3), dtype=np.uint8)
    assert cond.center_crop_to_aspect(same, 480, 832).shape == same.shape
    odd = np.zeros((2560, 1440, 3), dtype=np.uint8)  # 9:16 into 480x832: crop rows, never rescale
    assert cond.center_crop_to_aspect(odd, 480, 832).shape == (2496, 1440, 3)


@needs_ffmpeg
def test_a_provenance_record_is_data_never_a_path_out_of_its_folder(tmp_path: Path) -> None:
    import json

    from src.video.motion_conversion.conversion_service import verify_published

    store = new_store(tmp_path)
    _, result = _convert(tmp_path / "a")
    outside = tmp_path / "elsewhere.mp4"
    outside.write_bytes(b"not part of the conversion")
    record_path = Path(result.provenance_path)
    original = json.loads(record_path.read_text(encoding="utf-8"))
    for bad in (str(outside), r"..\elsewhere.mp4", "../elsewhere.mp4", "", "..", 7):
        record = json.loads(json.dumps(original))
        record["output"]["file"] = bad
        record["output"]["sha256"] = sha256(outside)
        record_path.write_text(json.dumps(record), encoding="utf-8")
        assert verify_published(result.directory) in {
            "The conversion record is malformed.",
            "The converted video is missing.",
        }
        refused = accept_conversion(store, result.directory, inspect=FakeInspector())
        assert refused.status == "failed"
    record = json.loads(json.dumps(original))
    record["output"] = "not a mapping"
    record_path.write_text(json.dumps(record), encoding="utf-8")
    assert verify_published(result.directory) == "The conversion record is malformed."
    assert store.assets() == ()
