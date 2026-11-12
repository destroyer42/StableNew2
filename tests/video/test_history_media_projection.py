"""Characterization of the read-only History media-selection decisions (ARCH-952).

The expectations were pinned against the former ``AppController`` private methods before they were
extracted, so they describe behavior that must not change.  The handoff tests drive the real
``AppController`` entry points with constructed History entries and temporary artifacts.
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import Mock

import pytest

from src.controller.app_controller import AppController
from src.controller.ports.presentation_actions import PresentationActions
from src.video.history_media_projection import (
    history_image_candidates,
    history_image_path,
    history_video_bundle,
    latest_history_image_path,
    latest_history_video_bundle,
)
from src.video.recent_video_outputs import video_bundle_from_result


def _entry(result: Any = None, snapshot: Any = None, job_id: str = "job") -> SimpleNamespace:
    return SimpleNamespace(job_id=job_id, result=result, snapshot=snapshot)


def _touch(tmp_path: Path, name: str) -> str:
    path = tmp_path / name
    path.write_bytes(b"x")
    return str(path)


# ---------------------------------------------------------------------------------------------
# Image candidates
# ---------------------------------------------------------------------------------------------


def test_candidates_follow_the_documented_precedence_and_deduplicate() -> None:
    entry = _entry(
        result={
            "artifact": {"output_paths": ["a.png", "b.png"], "primary_path": "ignored.png"},
            "output_paths": ["c.png", "a.png"],
            "frame_paths": ["d.png"],
            "video_paths": ["e.mp4"],
            "gif_paths": ["f.gif"],
            "path": "g.png",
            "thumbnail_path": "h.png",
        },
        snapshot={
            "normalized_job": {"output_paths": ["i.png", "b.png"], "thumbnail_path": "j.png"}
        },
    )

    assert history_image_candidates(entry) == [
        "a.png",
        "b.png",
        "c.png",
        "d.png",
        "e.mp4",
        "f.gif",
        "g.png",
        "h.png",
        "i.png",
        "j.png",
    ]


def test_artifact_primary_path_is_used_only_without_artifact_output_paths() -> None:
    assert history_image_candidates(_entry({"artifact": {"primary_path": "p.png"}})) == ["p.png"]
    assert history_image_candidates(
        _entry({"artifact": {"output_paths": [], "primary_path": "p.png"}})
    ) == ["p.png"]
    assert history_image_candidates(_entry({"artifact": {"primary_path": None}})) == []


def test_candidates_stringify_truthy_values_and_skip_falsy_ones() -> None:
    entry = _entry(
        result={
            "output_paths": [Path("a.png"), "", None, 0, "b.png"],
            "path": Path("c.png"),
            "frame_paths": ("tuple.png",),  # only lists are read for the list keys
            "video_paths": "string.mp4",
        }
    )

    assert history_image_candidates(entry) == ["a.png", "b.png", "c.png"]


def test_snapshot_only_paths_are_candidates() -> None:
    entry = _entry(
        result=None,
        snapshot={"normalized_job": {"output_paths": ["s.png"], "thumbnail_path": "t.png"}},
    )

    assert history_image_candidates(entry) == ["s.png", "t.png"]


@pytest.mark.parametrize(
    "entry",
    [
        _entry(),
        _entry(result="text", snapshot="text"),
        _entry(result={}, snapshot={"normalized_job": "not-a-dict"}),
        _entry(result={"artifact": "not-a-mapping"}, snapshot={}),
        SimpleNamespace(),
    ],
)
def test_no_candidates_for_missing_or_malformed_entries(entry: Any) -> None:
    assert history_image_candidates(entry) == []
    assert history_image_path(entry) is None


# ---------------------------------------------------------------------------------------------
# Image selection
# ---------------------------------------------------------------------------------------------


def test_image_path_picks_first_existing_allowed_suffix_case_insensitively(tmp_path: Path) -> None:
    movie = _touch(tmp_path, "clip.mp4")
    upper = _touch(tmp_path, "FRAME.PNG")
    later = _touch(tmp_path, "later.webp")
    entry = _entry(
        {
            "output_paths": [str(tmp_path / "missing.png"), movie, upper],
            "frame_paths": [later],
        }
    )

    assert history_image_path(entry) == upper


@pytest.mark.parametrize("suffix", [".png", ".jpg", ".jpeg", ".webp", ".bmp", ".tiff", ".tif"])
def test_every_allowed_suffix_is_accepted(tmp_path: Path, suffix: str) -> None:
    assert history_image_path(_entry({"path": _touch(tmp_path, f"f{suffix}")})) == str(
        tmp_path / f"f{suffix}"
    )


@pytest.mark.parametrize("name", ["anim.gif", "clip.mp4", "noext", "image.png.txt"])
def test_other_suffixes_are_not_images(tmp_path: Path, name: str) -> None:
    assert history_image_path(_entry({"path": _touch(tmp_path, name)})) is None


def test_missing_file_is_not_selected_and_a_directory_with_image_suffix_is(tmp_path: Path) -> None:
    (tmp_path / "dir.png").mkdir()  # exists() semantics are preserved: not is_file()

    assert history_image_path(_entry({"path": str(tmp_path / "absent.png")})) is None
    assert history_image_path(_entry({"path": str(tmp_path / "dir.png")})) == str(
        tmp_path / "dir.png"
    )


def test_snapshot_image_is_used_when_the_result_has_none(tmp_path: Path) -> None:
    thumb = _touch(tmp_path, "thumb.jpg")
    entry = _entry(
        {"output_paths": [str(tmp_path / "gone.png")]},
        {"normalized_job": {"thumbnail_path": thumb}},
    )

    assert history_image_path(entry) == thumb


# ---------------------------------------------------------------------------------------------
# Video bundle
# ---------------------------------------------------------------------------------------------


def test_direct_video_bundle_is_a_shallow_copy() -> None:
    inner = ["a.mp4"]
    direct = {"primary_path": "a.mp4", "video_paths": inner, "extra": 1}
    result = {"video_bundle": direct}

    bundle = history_video_bundle(_entry(result))

    assert bundle == direct
    assert bundle is not direct
    assert bundle["video_paths"] is inner


def test_direct_empty_video_bundle_is_returned_as_an_empty_dict() -> None:
    bundle = history_video_bundle(_entry({"video_bundle": {}}))

    assert bundle == {}
    # ``video_bundle_from_result`` treats the same result differently: it falls through.
    assert video_bundle_from_result({"video_bundle": {}}) is None


def test_non_dict_video_bundle_value_falls_back_to_the_metadata_summary() -> None:
    result = {
        "video_bundle": ["not", "a", "dict"],
        "metadata": {"video_primary_artifact": {"primary_path": "m.mp4"}},
    }

    assert history_video_bundle(_entry(result))["primary_path"] == "m.mp4"


def test_metadata_aggregate_is_projected_into_the_exact_bundle_shape() -> None:
    manifests = ["m.json"]
    result = {
        "metadata": {
            "video_artifacts": {
                "animatediff": {
                    "primary_path": "clip.mp4",
                    "stage": "animatediff",
                    "backend_id": "comfy",
                    "artifact_type": "ignored",
                    "thumbnail_path": "thumb.png",
                    "manifest_paths": manifests,
                    "output_paths": ["clip.mp4"],
                    "video_paths": ["clip.mp4"],
                    "gif_paths": ["clip.gif"],
                    "frame_paths": ["f1.png", "f0.png"],
                    "source_image_path": "src.png",
                    "count": 3,
                    "artifacts": [{"dropped": True}],
                    "manifest_path": "dropped.json",
                }
            }
        }
    }

    bundle = history_video_bundle(_entry(result))

    assert bundle == {
        "primary_path": "clip.mp4",
        "stage": "animatediff",
        "backend_id": "comfy",
        "artifact_type": "video",
        "thumbnail_path": "thumb.png",
        "manifest_paths": ["m.json"],
        "output_paths": ["clip.mp4"],
        "video_paths": ["clip.mp4"],
        "gif_paths": ["clip.gif"],
        "frame_paths": ["f1.png", "f0.png"],
        "source_image_path": "src.png",
        "count": 3,
    }
    assert list(bundle) == [
        "primary_path",
        "stage",
        "backend_id",
        "artifact_type",
        "thumbnail_path",
        "manifest_paths",
        "output_paths",
        "video_paths",
        "gif_paths",
        "frame_paths",
        "source_image_path",
        "count",
    ]
    assert bundle["manifest_paths"] is not manifests  # lists are copied


def test_legacy_stage_artifact_fallback_defaults_missing_fields() -> None:
    bundle = history_video_bundle(_entry({"svd_native_artifact": {"primary_path": "legacy.mp4"}}))

    assert bundle == {
        "primary_path": "legacy.mp4",
        "stage": None,
        "backend_id": None,
        "artifact_type": "video",
        "thumbnail_path": None,
        "manifest_paths": [],
        "output_paths": [],
        "video_paths": [],
        "gif_paths": [],
        "frame_paths": [],
        "source_image_path": None,
        "count": None,
    }


@pytest.mark.parametrize("result", [None, "text", ["list"], 3])
def test_non_dict_result_has_no_video_bundle(result: Any) -> None:
    assert history_video_bundle(_entry(result)) is None


def test_dict_result_without_any_artifact_has_no_video_bundle() -> None:
    assert history_video_bundle(_entry({"output_paths": ["a.png"]})) is None
    assert history_video_bundle(SimpleNamespace()) is None


# ---------------------------------------------------------------------------------------------
# Latest image / video
# ---------------------------------------------------------------------------------------------


def test_latest_image_is_the_first_match_in_given_order_regardless_of_status(
    tmp_path: Path,
) -> None:
    first = _touch(tmp_path, "first.png")
    second = _touch(tmp_path, "second.png")
    entries = [
        _entry({"output_paths": [str(tmp_path / "gone.png")]}),
        SimpleNamespace(
            result={"output_paths": [first]}, snapshot=None, status="FAILED", error="x"
        ),
        _entry({"output_paths": [second]}),
    ]

    assert latest_history_image_path(entries) == first
    assert latest_history_image_path(iter(entries)) == first
    assert latest_history_image_path([]) is None
    assert latest_history_image_path([_entry({"output_paths": ["gone.png"]})]) is None


def test_latest_video_is_the_first_eligible_bundle_without_checking_the_disk() -> None:
    entries = [
        _entry(None),
        _entry({"video_bundle": {}}),  # an empty direct bundle is not eligible
        _entry(
            {"video_bundle": {"video_paths": ["only.mp4"]}}
        ),  # video_paths alone is not eligible
        _entry({"video_bundle": {"frame_paths": ["f.png"], "marker": "frames"}}),
        _entry({"video_bundle": {"primary_path": "never-created.mp4"}}),
    ]

    assert latest_history_video_bundle(entries) == {"frame_paths": ["f.png"], "marker": "frames"}


@pytest.mark.parametrize("key", ["primary_path", "output_paths", "frame_paths"])
def test_each_eligibility_field_qualifies(key: str) -> None:
    value: Any = "x.mp4" if key == "primary_path" else ["x.mp4"]

    assert latest_history_video_bundle([_entry({"video_bundle": {key: value}})]) == {key: value}


def test_latest_video_has_no_match_for_video_paths_only_or_empty_input() -> None:
    assert (
        latest_history_video_bundle([_entry({"video_bundle": {"video_paths": ["a.mp4"]}})]) is None
    )
    assert latest_history_video_bundle([]) is None


# ---------------------------------------------------------------------------------------------
# The AppController entry points that consume the projections
# ---------------------------------------------------------------------------------------------


def _controller(*entries: Any) -> tuple[AppController, Mock]:
    controller = AppController.__new__(AppController)
    controller.main_window = object()
    controller.presentation_actions = Mock(spec=PresentationActions)
    controller._append_log = Mock()
    controller.app_state = SimpleNamespace(history_items=list(entries))
    return controller, controller.presentation_actions


def test_controller_latest_getters_read_the_history_snapshot(tmp_path: Path) -> None:
    image = _touch(tmp_path, "latest.png")
    controller, _ = _controller(
        _entry({"video_bundle": {"primary_path": "a.mp4"}, "output_paths": [image]})
    )

    assert controller.get_latest_output_image_path() == image
    assert controller.get_latest_video_output_bundle() == {"primary_path": "a.mp4"}
    controller.app_state = None
    assert controller.get_latest_output_image_path() is None
    assert controller.get_latest_video_output_bundle() is None


def test_missing_job_and_no_output_errors_are_unchanged() -> None:
    controller, _ = _controller(_entry({"output_paths": ["gone.png"]}, job_id="known"))

    for method in (
        controller.send_history_job_image_to_svd,
        controller.send_history_job_image_to_video_workflow,
        controller.send_history_job_to_movie_clips,
    ):
        with pytest.raises(ValueError, match="History job not found: nope"):
            method("nope")
    with pytest.raises(ValueError, match="History job known has no image output available for SVD"):
        controller.send_history_job_image_to_svd("known")
    with pytest.raises(
        ValueError,
        match="History job known has no usable image or video output available for Video Workflow",
    ):
        controller.send_history_job_image_to_video_workflow("known")
    with pytest.raises(
        ValueError, match="History job known has no usable output available for Movie Clips"
    ):
        controller.send_history_job_to_movie_clips("known")


def test_svd_handoff_is_image_only(tmp_path: Path) -> None:
    image = _touch(tmp_path, "src.png")
    controller, _ = _controller(
        _entry({"video_bundle": {"primary_path": "clip.mp4"}, "output_paths": [image]}, job_id="j")
    )
    controller.send_image_to_svd = Mock(return_value="routed")

    assert controller.send_history_job_image_to_svd("j") == "routed"
    controller.send_image_to_svd.assert_called_once_with(image)


def test_video_workflow_prefers_the_bundle_then_falls_back_to_the_image_with_lineage(
    tmp_path: Path,
) -> None:
    image = _touch(tmp_path, "src.png")
    entry = _entry(
        {"video_bundle": {"primary_path": "clip.mp4"}, "output_paths": [image]}, job_id="j"
    )
    controller, actions = _controller(entry)
    actions.bundle_to_video_workflow.return_value = "best.mp4"

    assert controller.send_history_job_image_to_video_workflow("j") == "best.mp4"
    actions.bundle_to_video_workflow.assert_called_once_with(
        bundle={"primary_path": "clip.mp4"},
        status_message="Loaded video output into Video Workflow tab.",
    )
    actions.image_to_video_workflow.assert_not_called()

    actions.bundle_to_video_workflow.return_value = None
    assert controller.send_history_job_image_to_video_workflow("j") == image
    actions.image_to_video_workflow.assert_called_once_with(
        image_path=image,
        status_message="Loaded into Video Workflow tab: src.png",
        lineage={"source_job_id": "j"},
    )

    # An empty direct bundle is falsy, so the image is used and the bundle action is not called.
    actions.bundle_to_video_workflow.reset_mock()
    controller.app_state.history_items = [
        _entry({"video_bundle": {}, "output_paths": [image]}, job_id="j")
    ]
    assert controller.send_history_job_image_to_video_workflow("j") == image
    actions.bundle_to_video_workflow.assert_not_called()


def test_movie_clips_prefers_the_bundle_then_the_image(tmp_path: Path) -> None:
    image = _touch(tmp_path, "src.png")
    controller, actions = _controller(
        _entry(
            {"video_bundle": {"primary_path": "dir/clip.mp4"}, "output_paths": [image]}, job_id="j"
        )
    )

    assert controller.send_history_job_to_movie_clips("j") == "dir/clip.mp4"
    actions.bundle_to_movie_clips.assert_called_once_with(
        bundle={"primary_path": "dir/clip.mp4"},
        status_message="Loaded history output into Movie Clips.",
    )
    controller._append_log.assert_called_with(
        "[movie_clips] Routed history output to Movie Clips: clip.mp4"
    )

    controller.app_state.history_items = [_entry({"output_paths": [image]}, job_id="j")]
    assert controller.send_history_job_to_movie_clips("j") == image
    actions.image_to_movie_clips.assert_called_once_with(
        image_path=image, status_message="Loaded src.png into Movie Clips."
    )
    actions.image_to_video_workflow.assert_not_called()
