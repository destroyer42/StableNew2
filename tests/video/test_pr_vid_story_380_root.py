"""PR-VID-STORY-380: root preparation (spec 7.3), a finished clip job or a still turned into a storyboard root.

A clip root is a hash-pinned cut manifest of the job's real generated frames: a frames-out job's saved PNGs (referenced
where they are), a sequence's encoded frames, a take's cut, or an encoded-only clip decoded once. A smoothed clip enters
as its generated frames at the workflow's fps. The jobs are built with the real NJR builders and workflow catalog
(``tests/helpers/storyboard_380.py``); frames are small real PNGs, and no Comfy, FFmpeg, RIFE, GPU or network is used.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from src.controller.runtime_state import CancellationError, CancelToken
from src.video.sequence_ledger import read_ledger, sha256_of
from src.video.sequence_plan import ROOT_PARENT
from src.video.storyboard_cut import BASIS_DECODED, BASIS_NATIVE, CutRange, read_cut_manifest
from src.video.storyboard_root import (
    ROOT_CUT_FILE_NAME,
    ROOT_SETTING_KEYS,
    SmoothingNote,
    StoryboardRootError,
    prepare_clip_root,
    prepare_image_root,
)
from tests.helpers.storyboard_380 import (
    REG,
    SMALL,
    FakeDecoder,
)
from tests.helpers.storyboard_380 import a14b_settings as _a14b_settings
from tests.helpers.storyboard_380 import comfy_original as _comfy_original
from tests.helpers.storyboard_380 import encoded_only_job as _encoded_only_job
from tests.helpers.storyboard_380 import frames_out_job as _frames_out_job
from tests.helpers.storyboard_380 import overwrite_png as _overwrite_png
from tests.helpers.storyboard_380 import png as _png
from tests.helpers.storyboard_380 import refused_job as _refused_job
from tests.helpers.storyboard_380 import remove as _remove
from tests.helpers.storyboard_380 import sequence_job as _sequence_job
from tests.helpers.storyboard_380 import take_job as _take_job
from tests.helpers.storyboard_380 import unsmoothed_mp4 as _unsmoothed_mp4

SID = "s" * 32


def _root_folder(tmp_path: Path) -> Path:
    return tmp_path / "storyboards" / SID / "root"


# ----------------------------------------------------------------------------- the brief's tests


def test_frames_out_root_references_frames_without_copying(tmp_path):
    repo, job_id, frames = _frames_out_job(tmp_path, count=81, size=(832, 480))
    root = prepare_clip_root(
        repository=repo, job_id=job_id, storyboard_id="s" * 32, output_root=tmp_path, registry=REG
    )
    manifest = read_cut_manifest(root.manifest.path, expected_sha256=root.manifest.sha256)
    assert [f.path for f in manifest.frames] == [str(p) for p in frames]
    assert not (tmp_path / "storyboards").exists() or not any(
        (tmp_path / "storyboards").rglob("*.png")
    )


def test_smoothed_root_uses_generated_frames_and_notes_it(tmp_path):
    repo, job_id, _ = _frames_out_job(tmp_path, count=81, smoothed_fps=32)
    root = prepare_clip_root(
        repository=repo, job_id=job_id, storyboard_id="s" * 32, output_root=tmp_path, registry=REG
    )
    assert root.fps == 16 and root.smoothing.text() == (
        "This clip was smoothed to 32 fps. The storyboard uses its 81 generated frames at 16 fps."
    )


def test_smoothed_root_with_only_the_smoothed_file_left_is_refused(tmp_path):
    repo, job_id, frames = _frames_out_job(tmp_path, count=81, smoothed_fps=32)
    _remove(frames, _unsmoothed_mp4(repo, job_id))
    with pytest.raises(StoryboardRootError, match="Only the smoothed video is left"):
        prepare_clip_root(
            repository=repo,
            job_id=job_id,
            storyboard_id="s" * 32,
            output_root=tmp_path,
            registry=REG,
        )


def test_a_mismatched_frames_out_digest_is_refused(tmp_path):
    repo, job_id, frames = _frames_out_job(tmp_path, count=81)
    _overwrite_png(frames[10])
    with pytest.raises(StoryboardRootError, match="do not match the hashes the backend recorded"):
        prepare_clip_root(
            repository=repo,
            job_id=job_id,
            storyboard_id="s" * 32,
            output_root=tmp_path,
            registry=REG,
        )


def test_sequence_root_uses_exactly_the_encoded_frames(tmp_path):
    repo, job_id, expected = _sequence_job(tmp_path, segments=2, color_matched=True)
    root = prepare_clip_root(
        repository=repo, job_id=job_id, storyboard_id="s" * 32, output_root=tmp_path, registry=REG
    )
    assert [f.path for f in read_cut_manifest(root.manifest.path).frames] == expected


def test_encoded_only_root_decodes_the_unsmoothed_file(tmp_path):
    repo, job_id, decoder = _encoded_only_job(tmp_path, smoothed_fps=48)
    root = prepare_clip_root(
        repository=repo,
        job_id=job_id,
        storyboard_id="s" * 32,
        output_root=tmp_path,
        registry=REG,
        decode_clip=decoder,
    )
    assert decoder.decoded_path == _comfy_original(repo, job_id)
    assert (
        Path(read_cut_manifest(root.manifest.path).frames[0].path).parent
        == tmp_path / "storyboards" / ("s" * 32) / "root"
    )


@pytest.mark.parametrize(
    "kind, message",
    [
        ("svd", "native SVD"),
        ("not_completed", "has not completed"),
        ("driving_video", "driving video"),
        ("missing_frames", "frame is missing"),
    ],
)
def test_refusals(tmp_path, kind, message):
    repo, job_id = _refused_job(tmp_path, kind)
    with pytest.raises(StoryboardRootError, match=message):
        prepare_clip_root(
            repository=repo,
            job_id=job_id,
            storyboard_id="s" * 32,
            output_root=tmp_path,
            registry=REG,
        )


def test_image_root_keeps_only_root_settings(tmp_path):
    root = prepare_image_root(
        image_path=_png(tmp_path / "i.png", (832, 480)),
        settings={**_a14b_settings(), "interpolation": {"enabled": True}},
        registry=REG,
    )
    assert root.kind == "image" and root.manifest is None and "interpolation" not in root.settings


# ----------------------------------------------------------------------------- the root cut manifest


def test_the_root_manifest_is_one_root_range_written_under_the_storyboard(tmp_path: Path) -> None:
    repo, job_id, frames = _frames_out_job(tmp_path, count=17)
    root = prepare_clip_root(
        repository=repo, job_id=job_id, storyboard_id=SID, output_root=tmp_path, registry=REG
    )
    assert root.manifest is not None
    assert Path(root.manifest.path) == _root_folder(tmp_path) / ROOT_CUT_FILE_NAME
    assert root.manifest.sha256 == sha256_of(root.manifest.path)
    manifest = read_cut_manifest(root.manifest.path, expected_sha256=root.manifest.sha256)
    assert manifest.ranges == (CutRange(ROOT_PARENT, 0, 16, BASIS_NATIVE, 0),)
    assert (manifest.lead_in_frames, manifest.job_id, manifest.fps) == (0, job_id, 16)
    assert (manifest.width, manifest.height) == (root.width, root.height) == (832, 480)
    assert [f.sha256 for f in manifest.frames] == [sha256_of(p) for p in frames]
    assert (root.kind, root.job_id, root.image_path, root.smoothing) == ("clip", job_id, None, None)
    assert sorted(p.name for p in (tmp_path / "storyboards" / SID).iterdir()) == ["root"]


def test_a_clip_root_inherits_only_the_root_settings(tmp_path: Path) -> None:
    repo, job_id, _ = _frames_out_job(tmp_path, count=17, smoothed_fps=32)
    root = prepare_clip_root(
        repository=repo, job_id=job_id, storyboard_id=SID, output_root=tmp_path, registry=REG
    )
    assert set(root.settings) <= ROOT_SETTING_KEYS
    assert dict(root.settings) == {
        "workflow_id": "wan22_i2v_a14b_4step_v1",
        "workflow_version": "1.0.0",
        "frame_count": 17,
        "negative_prompt": "blurry, watermark",
        "output_route": "Reprocess",
    }
    assert root.smoothing == SmoothingNote(smoothed_fps=32, fps=16, frame_count=17)


def test_an_unsmoothed_encoded_only_root_decodes_the_primary_clip(tmp_path: Path) -> None:
    repo, job_id, decoder = _encoded_only_job(tmp_path)
    root = prepare_clip_root(
        repository=repo,
        job_id=job_id,
        storyboard_id=SID,
        output_root=tmp_path,
        registry=REG,
        decode_clip=decoder,
    )
    manifest = read_cut_manifest(root.manifest.path, expected_sha256=root.manifest.sha256)
    assert decoder.decoded_path == _comfy_original(repo, job_id)
    assert manifest.ranges == (CutRange(ROOT_PARENT, 0, 16, BASIS_DECODED, 0),)
    assert [Path(f.path).name for f in manifest.frames] == [f"d_{n:06d}.png" for n in range(1, 18)]
    assert all(Path(f.path).is_file() and sha256_of(f.path) == f.sha256 for f in manifest.frames)
    assert (root.fps, root.width, root.height, root.smoothing) == (24, *SMALL, None)
    assert not [p.name for p in (tmp_path / "storyboards" / SID).iterdir() if p.name != "root"]


def test_an_encoded_only_root_with_its_unsmoothed_file_gone_is_refused(tmp_path: Path) -> None:
    repo, job_id, decoder = _encoded_only_job(tmp_path, smoothed_fps=48)
    _comfy_original(repo, job_id).unlink()
    with pytest.raises(StoryboardRootError) as caught:
        prepare_clip_root(
            repository=repo,
            job_id=job_id,
            storyboard_id=SID,
            output_root=tmp_path,
            registry=REG,
            decode_clip=decoder,
        )
    assert str(caught.value) == (
        "Only the smoothed video is left; its in-between frames were invented, so it cannot be "
        "continued exactly"
    )
    assert decoder.calls == 0


def test_a_decode_of_the_wrong_length_publishes_nothing(tmp_path: Path) -> None:
    repo, job_id, _ = _encoded_only_job(tmp_path)
    with pytest.raises(StoryboardRootError, match="gave 9 frames but the job generated 17"):
        prepare_clip_root(
            repository=repo,
            job_id=job_id,
            storyboard_id=SID,
            output_root=tmp_path,
            registry=REG,
            decode_clip=FakeDecoder(count=9),
        )
    assert not (tmp_path / "storyboards").exists()


def test_a_cancelled_decode_publishes_nothing(tmp_path: Path) -> None:
    repo, job_id, decoder = _encoded_only_job(tmp_path)
    token = CancelToken()
    token.cancel()
    with pytest.raises(CancellationError):
        prepare_clip_root(
            repository=repo,
            job_id=job_id,
            storyboard_id=SID,
            output_root=tmp_path,
            registry=REG,
            decode_clip=decoder,
            cancel_token=token,
        )
    assert not (tmp_path / "storyboards").exists()


def test_an_existing_root_is_never_overwritten(tmp_path: Path) -> None:
    repo, job_id, _ = _frames_out_job(tmp_path, count=17)
    folder = _root_folder(tmp_path)
    folder.mkdir(parents=True)
    (folder / "keep.txt").write_text("earlier", encoding="utf-8")
    with pytest.raises(StoryboardRootError, match="already has a root"):
        prepare_clip_root(
            repository=repo, job_id=job_id, storyboard_id=SID, output_root=tmp_path, registry=REG
        )
    assert [p.name for p in folder.iterdir()] == ["keep.txt"]
    assert [p.name for p in folder.parent.iterdir()] == ["root"]


@pytest.mark.parametrize("storyboard_id", ["", "..", "a/b", "a\\b", "x" * 65, "abc\n"])
def test_a_storyboard_id_that_is_not_a_plain_name_is_refused(
    tmp_path: Path, storyboard_id: str
) -> None:
    repo, job_id, _ = _frames_out_job(tmp_path, count=17)
    with pytest.raises(StoryboardRootError, match="storyboard id"):
        prepare_clip_root(
            repository=repo,
            job_id=job_id,
            storyboard_id=storyboard_id,
            output_root=tmp_path,
            registry=REG,
        )
    assert not (tmp_path / "storyboards").exists()


# ----------------------------------------------------------------------------- sequences and takes


def test_a_take_root_is_its_cut_re_ranged_as_one_root_range(tmp_path: Path) -> None:
    repo, job_id, cut_frames = _take_job(tmp_path, segments=2)
    root = prepare_clip_root(
        repository=repo, job_id=job_id, storyboard_id=SID, output_root=tmp_path, registry=REG
    )
    manifest = read_cut_manifest(root.manifest.path, expected_sha256=root.manifest.sha256)
    assert [f.path for f in manifest.frames] == cut_frames
    assert manifest.ranges == (CutRange(ROOT_PARENT, 0, len(cut_frames) - 1, BASIS_NATIVE, 0),)
    assert (manifest.lead_in_frames, manifest.job_id, root.fps) == (0, job_id, 16)
    assert (root.width, root.height) == SMALL


def test_a_take_whose_cut_manifest_changed_is_refused(tmp_path: Path) -> None:
    repo, job_id, _ = _take_job(tmp_path, segments=1)
    ledger_path = repo.jobs[job_id].result["metadata"]["sequence_artifact"]["ledger_path"]
    cut = read_ledger(Path(ledger_path)).cut_manifest
    Path(cut["path"]).write_text("{}", encoding="utf-8")
    with pytest.raises(StoryboardRootError, match="cut manifest changed"):
        prepare_clip_root(
            repository=repo, job_id=job_id, storyboard_id=SID, output_root=tmp_path, registry=REG
        )


def test_a_sequence_without_colour_matching_uses_its_frames_after_the_overlap(
    tmp_path: Path,
) -> None:
    repo, job_id, expected = _sequence_job(tmp_path, segments=2, color_matched=False)
    root = prepare_clip_root(
        repository=repo, job_id=job_id, storyboard_id=SID, output_root=tmp_path, registry=REG
    )
    manifest = read_cut_manifest(root.manifest.path)
    assert [f.path for f in manifest.frames] == expected
    assert len(expected) == 17 + 16  # segment 1 drops the frame that re-renders segment 0's last
    assert manifest.ranges == (CutRange(ROOT_PARENT, 0, 32, BASIS_NATIVE, 0),)


def test_a_sequence_found_by_its_run_folder_when_the_result_names_no_ledger(
    tmp_path: Path,
) -> None:
    repo, job_id, expected = _sequence_job(tmp_path, segments=2)
    repo.jobs[job_id].result = {"success": True, "metadata": {}}
    root = prepare_clip_root(
        repository=repo, job_id=job_id, storyboard_id=SID, output_root=tmp_path, registry=REG
    )
    assert [f.path for f in read_cut_manifest(root.manifest.path).frames] == expected


def test_a_changed_sequence_frame_is_refused_by_name(tmp_path: Path) -> None:
    repo, job_id, expected = _sequence_job(tmp_path, segments=2, color_matched=True)
    _overwrite_png(Path(expected[20]))
    with pytest.raises(StoryboardRootError, match="changed since it was recorded") as caught:
        prepare_clip_root(
            repository=repo, job_id=job_id, storyboard_id=SID, output_root=tmp_path, registry=REG
        )
    assert expected[20] in str(caught.value)
    assert not (tmp_path / "storyboards").exists()


# ----------------------------------------------------------------------------- refusals


def test_a_missing_job_is_refused(tmp_path: Path) -> None:
    repo, _job_id, _ = _frames_out_job(tmp_path, count=17)
    with pytest.raises(StoryboardRootError, match="was not found"):
        prepare_clip_root(
            repository=repo, job_id="nope", storyboard_id=SID, output_root=tmp_path, registry=REG
        )


def test_a_missing_frame_is_named(tmp_path: Path) -> None:
    repo, job_id, frames = _frames_out_job(tmp_path, count=17)
    frames[3].unlink()
    with pytest.raises(StoryboardRootError) as caught:
        prepare_clip_root(
            repository=repo, job_id=job_id, storyboard_id=SID, output_root=tmp_path, registry=REG
        )
    assert "frame 4" in str(caught.value) and str(frames[3]) in str(caught.value)


def test_a_smoothed_frames_out_job_whose_frames_are_gone_but_unsmoothed_clip_kept_names_the_frame(
    tmp_path: Path,
) -> None:
    repo, job_id, frames = _frames_out_job(tmp_path, count=17, smoothed_fps=32)
    frames[0].unlink()
    with pytest.raises(StoryboardRootError, match="frame is missing"):
        prepare_clip_root(
            repository=repo, job_id=job_id, storyboard_id=SID, output_root=tmp_path, registry=REG
        )


def test_the_driving_video_refusal_reads_plainly(tmp_path: Path) -> None:
    repo, job_id = _refused_job(tmp_path, "driving_video")
    with pytest.raises(StoryboardRootError) as caught:
        prepare_clip_root(
            repository=repo, job_id=job_id, storyboard_id=SID, output_root=tmp_path, registry=REG
        )
    assert str(caught.value).startswith(f"Job {job_id} cannot start a storyboard: ")
    assert not (tmp_path / "storyboards").exists()


# ----------------------------------------------------------------------------- image roots


def test_an_image_root_records_the_still_and_the_workflow_fps(tmp_path: Path) -> None:
    image = _png(tmp_path / "still.png", (1000, 600))
    root = prepare_image_root(
        image_path=image,
        settings={**_a14b_settings(), "seed": "5", "experimental_opt_in": True},
        registry=REG,
    )
    assert (root.job_id, root.smoothing) == (None, None)
    assert root.image_path == str(image.resolve()) and root.image_sha256 == sha256_of(image)
    assert (root.fps, root.width, root.height) == (16, 1000, 600)
    assert dict(root.settings) == {
        "workflow_id": "wan22_i2v_a14b_4step_v1",
        "workflow_version": "1.0.0",
        "frame_count": 81,
        "negative_prompt": "blurry, watermark",
        "output_route": "Reprocess",
    }


@pytest.mark.parametrize(
    ("settings", "message"),
    [
        ({"workflow_id": "wan_animate2_drive_i2v_v1", "workflow_version": "1.0.0"}, "experimental"),
        (
            {
                "workflow_id": "wan22_i2v_a14b_4step_v1",
                "workflow_version": "1.0.0",
                "frame_count": 20,
            },
            "cannot generate 20 frames",
        ),
        ({"frame_count": 81}, "needs a workflow"),
    ],
)
def test_an_image_root_refuses_a_workflow_a_take_cannot_run(
    tmp_path: Path, settings: dict, message: str
) -> None:
    image = _png(tmp_path / "still.png", (832, 480))
    with pytest.raises(StoryboardRootError, match=message):
        prepare_image_root(image_path=image, settings=settings, registry=REG)


def test_an_image_root_refuses_a_file_that_is_not_an_image(tmp_path: Path) -> None:
    fake = tmp_path / "notes.png"
    fake.write_text("not an image", encoding="utf-8")
    with pytest.raises(StoryboardRootError, match="not a readable image"):
        prepare_image_root(image_path=fake, settings=_a14b_settings(), registry=REG)
