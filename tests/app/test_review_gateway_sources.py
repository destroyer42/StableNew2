"""PHONE-FAST (a): only authoritative outputs are published to the phone (hermetic: temp roots, fake gateway)."""

from __future__ import annotations

import json
from pathlib import Path
from threading import Event

import pytest
from PIL import Image

from src.app.review_gateway_client import GatewayClient
from src.app.site_output_library import LibraryItem, Preview, key_for
from tests.app.test_review_gateway_sync import Env
from tests.helpers.review_gateway_fakes import SECRET

FRAMES_RUN = "Reprocess/20261126_090000_clips"


@pytest.fixture
def env(tmp_path):
    environment = Env(tmp_path)
    environment.large.unlink()
    environment.small.unlink()
    yield environment
    environment.close()


def make_item(env, relative: str, *, mime: str = "image/png", provenance: str = "embedded"):
    path = env.root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    if mime == "image/png":
        Image.new("RGB", (64, 48), "#224466").save(path)
    else:
        path.write_bytes(b"\x00\x00\x00\x18ftypmp42" + path.name.encode() * 200)
    stat = path.stat()
    return LibraryItem(
        path=relative,
        mime=mime,
        version=(stat.st_dev, stat.st_ino, stat.st_size, stat.st_mtime_ns, stat.st_ctime_ns),
        provenance=provenance,
    )


def write_manifest(env, run: str, **payload) -> None:
    folder = env.root / run / "manifests"
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "clip.json").write_text(json.dumps(payload), encoding="utf-8")


def absolute(env, run: str, name: str) -> str:
    return str(env.root / run / name)


def publish(env, monkeypatch, *items, **options):
    monkeypatch.setattr(
        env.publisher, "candidates", lambda _limit: [(key_for(i.path), i) for i in items]
    )
    # A video's poster needs FFmpeg and a real clip; the poster is not what these tests are about.
    monkeypatch.setattr(
        env.library, "grid_preview", lambda *_a, **_k: Preview("image/jpeg", b"thumb")
    )
    return env.publisher.publish(
        GatewayClient(env.gateway, SECRET), limit=8, cancel=Event(), **options
    )


def state(env, item) -> str | None:
    row = env.ledger.published(key_for(item.path))
    return None if row is None else row["state"]


def test_a_movie_clips_image_is_never_published_but_its_movie_is(env, monkeypatch):
    frame = make_item(env, "movie_clips/run/frame_00001_.png")
    movie = make_item(env, "movie_clips/run/movie.mp4", mime="video/mp4")
    publish(env, monkeypatch, frame, movie)
    assert state(env, frame) == "frame"
    assert state(env, movie) == "published"


def test_a_frame_listed_by_a_video_manifest_is_never_published(env, monkeypatch):
    frame = make_item(env, f"{FRAMES_RUN}/wan_00001_.png", provenance="unknown")
    still = make_item(env, f"{FRAMES_RUN}/portrait.png")
    write_manifest(
        env,
        FRAMES_RUN,
        video_path=absolute(env, FRAMES_RUN, "wan.mp4"),
        video_paths=[absolute(env, FRAMES_RUN, "wan.mp4")],
        frame_paths=[absolute(env, FRAMES_RUN, "wan_00001_.png")],
    )
    publish(env, monkeypatch, frame, still)
    assert state(env, frame) == "frame"
    assert state(env, still) == "published"


def test_images_a_manifest_without_a_video_lists_are_ordinary_outputs(env, monkeypatch):
    still = make_item(env, f"{FRAMES_RUN}/grid_00001_.png")
    write_manifest(env, FRAMES_RUN, frame_paths=[absolute(env, FRAMES_RUN, "grid_00001_.png")])
    publish(env, monkeypatch, still)
    assert state(env, still) == "published"


@pytest.mark.parametrize(
    "recorded",
    [
        {"artifact": {"retained_paths": ["{source}"]}},
        {"interpolation": {"engine": "rife"}},  # a manifest written before retained_paths existed
    ],
)
def test_an_unsmoothed_clip_is_never_published(env, monkeypatch, recorded):
    source = make_item(env, f"{FRAMES_RUN}/wan.mp4", mime="video/mp4")
    smooth = make_item(env, f"{FRAMES_RUN}/wan_rife.mp4", mime="video/mp4")
    source_path = absolute(env, FRAMES_RUN, "wan.mp4")
    smooth_path = absolute(env, FRAMES_RUN, "wan_rife.mp4")
    payload = json.loads(json.dumps(recorded).replace("{source}", json.dumps(source_path)[1:-1]))
    write_manifest(
        env, FRAMES_RUN, video_path=smooth_path, video_paths=[smooth_path, source_path], **payload
    )
    publish(env, monkeypatch, source, smooth)
    assert state(env, source) == "retained"
    assert state(env, smooth) == "published"


def test_a_two_clip_manifest_without_interpolation_publishes_both(env, monkeypatch):
    first = make_item(env, f"{FRAMES_RUN}/a.mp4", mime="video/mp4")
    second = make_item(env, f"{FRAMES_RUN}/b.mp4", mime="video/mp4")
    paths = [absolute(env, FRAMES_RUN, name) for name in ("a.mp4", "b.mp4")]
    write_manifest(env, FRAMES_RUN, video_path=paths[0], video_paths=paths)
    publish(env, monkeypatch, first, second)
    assert state(env, first) == state(env, second) == "published"


def test_a_manifest_written_after_the_first_look_is_honoured(env, monkeypatch):
    still = make_item(env, f"{FRAMES_RUN}/portrait.png")
    publish(env, monkeypatch, still)
    frame = make_item(env, f"{FRAMES_RUN}/wan_00001_.png")
    write_manifest(
        env,
        FRAMES_RUN,
        video_path=absolute(env, FRAMES_RUN, "wan.mp4"),
        frame_paths=[absolute(env, FRAMES_RUN, "wan_00001_.png")],
    )
    publish(env, monkeypatch, frame)
    assert state(env, frame) == "frame"


def test_an_unlabelled_numbered_png_waits_while_a_job_runs(env, monkeypatch):
    """A running video job may have saved its frames but not yet written its manifest."""

    frame = make_item(env, f"{FRAMES_RUN}/wan_00001_.png", provenance="unknown")
    upload = make_item(env, f"{FRAMES_RUN}/photo.png", provenance="unknown")
    result = publish(env, monkeypatch, frame, upload, hold_unlabelled_video=True)
    assert state(env, frame) is None and result.pending == 1
    assert state(env, upload) == "published"
    publish(env, monkeypatch, frame)
    assert state(env, frame) == "published"


def test_exclusion_reads_nothing_outside_the_output_root(env, tmp_path):
    from src.app.review_gateway_sources import SourceFilter

    outside = LibraryItem(path="../elsewhere/a.png", mime="image/png", version=(0, 0, 1, 0, 0))
    assert SourceFilter(env.root).exclusion(outside) == ""
    assert not (tmp_path / "elsewhere").exists()
    assert Path(env.root).is_dir()


# -- only authoritative outputs: working files and folders no job writes outputs to ---------------------------------

WORKING_FILES = [
    ("prepared_video_sources/0a1b2c3d_480x832_cover_resize_center_crop.png", "image/png"),
    ("prepared_driving_videos/0a1b2c3d.mp4", "video/mp4"),
    ("eval_plans/video/stage/motion/head_turn.mp4", "video/mp4"),
    ("storyboards/abc123/root/frames/0001.png", "image/png"),
    ("continue_frames/job-1/last.png", "image/png"),
    ("PhotoOptimize/workspace/assets/photo_1/original/photo.png", "image/png"),
    ("PhotoOptimize/workspace/staging_runs/s1/PhotoOptimize/run/draft.png", "image/png"),
    ("SVD/run/_svd_temp/abc/postprocess/rife_output/0001.png", "image/png"),
    ("Pipeline/run/conditioning/depth.png", "image/png"),
]
NOT_JOB_OUTPUTS = [
    ("Best Examples/Motion Candidates/copy.mp4", "video/mp4"),
    ("some_new_folder/thing.png", "image/png"),
    ("loose.png", "image/png"),
]
FINAL_OUTPUTS = [
    ("Pipeline/run/final.png", "image/png"),
    ("Pipeline/run/upscaled/final.png", "image/png"),  # where the upscale stage writes
    ("20261126_090000_before_routes/final.png", "image/png"),  # a run folder from before the routes
    ("Reprocess/run/fixed.png", "image/png"),
    ("PhotoOptimize/workspace/assets/photo_1/outputs/result.png", "image/png"),
    ("movie_clips/run/clip_smooth.mp4", "video/mp4"),
    ("SVD/run/svd_clip.mp4", "video/mp4"),
]


@pytest.mark.parametrize(("relative", "mime"), WORKING_FILES + NOT_JOB_OUTPUTS)
def test_what_is_not_a_job_output_is_never_published(env, monkeypatch, relative, mime):
    item = make_item(env, relative, mime=mime, provenance="unknown")
    result = publish(env, monkeypatch, item)
    assert result.published == 0 and not env.gateway.manifests
    assert state(env, item) in {"working_file", "not_output", "frame"}


@pytest.mark.parametrize(("relative", "mime"), FINAL_OUTPUTS)
def test_a_final_output_is_published(env, monkeypatch, relative, mime):
    item = make_item(env, relative, mime=mime)
    publish(env, monkeypatch, item)
    assert state(env, item) == "published"


def test_a_video_poster_image_is_never_published(env, monkeypatch):
    run = "SVD/20261126_090000_svd"
    poster = make_item(env, f"{run}/svd_clip_preview.png", provenance="unknown")
    clip = make_item(env, f"{run}/svd_clip.mp4", mime="video/mp4")
    write_manifest(
        env,
        run,
        video_path=absolute(env, run, "svd_clip.mp4"),
        thumbnail_path=absolute(env, run, "svd_clip_preview.png"),
    )
    publish(env, monkeypatch, poster, clip)
    assert state(env, poster) == "frame"
    assert state(env, clip) == "published"


def test_every_working_folder_stablenew_writes_is_named(env):
    """The names come from the code that writes them, so a renamed folder cannot start leaking again."""

    from src.app.review_gateway_sources import WORKING, SourceFilter
    from src.app.site_phone_continue import FRAMES_FOLDER
    from src.state.eval_plans_paths import EVAL_PLANS_FOLDER
    from src.video.motion_source_preparation import PREPARED_DIRNAME
    from src.video.storyboard_root import STORYBOARDS_FOLDER
    from src.video.workflow_source_preparation import prepared_source_destination

    prepared = prepared_source_destination(env.root, "a" * 64, {"width": 480, "height": 832})
    folders = [
        prepared.parent.name,
        PREPARED_DIRNAME,
        EVAL_PLANS_FOLDER,
        STORYBOARDS_FOLDER,
        FRAMES_FOLDER,
    ]
    found = {
        name: SourceFilter(env.root).exclusion_of(f"{name}/a.png", "image") for name in folders
    }
    assert found == dict.fromkeys(folders, WORKING)
