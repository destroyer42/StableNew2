"""PHONE-FAST: the PC asks once for the frames and un-smoothed clips it published earlier to be withdrawn."""

from __future__ import annotations

import json
from threading import Event

import pytest

from src.app.review_gateway_client import GatewayClient
from tests.app.test_review_gateway_sync import RUN, Env
from tests.helpers.review_gateway_fakes import SECRET


@pytest.fixture
def env(tmp_path):
    environment = Env(tmp_path)
    yield environment
    environment.close()


def record(env, library_id: str, rel_path: str, kind: str = "image", state: str = "published"):
    env.ledger.mark_published(
        library_id, "v1", rel_path, "a" * 64, kind, state, "2026-11-26T00:00:00Z"
    )


def seed(env) -> None:
    manifests = env.root / RUN / "manifests"
    manifests.mkdir(parents=True, exist_ok=True)
    (manifests / "clip.json").write_text(
        json.dumps(
            {
                "video_path": "clip_smooth.mp4",
                "video_paths": ["clip_smooth.mp4", "clip_raw.mp4"],
                "interpolation": {"factor": 2},
                "frame_paths": ["listed_00001_.png"],
            }
        ),
        encoding="utf-8",
    )
    record(env, "frame-by-route", "movie_clips/a/frame.png")
    record(env, "frame-listed", f"{RUN}/listed_00001_.png")
    record(env, "clip-retained", f"{RUN}/clip_raw.mp4", "video")
    record(env, "clip-final", f"{RUN}/clip_smooth.mp4", "video")
    record(env, "still", f"{RUN}/portrait.png")
    record(env, "never-sent", "movie_clips/a/other.png", state="frame")


def withdraw(env) -> None:
    client = GatewayClient(env.gateway, SECRET)
    client.health()
    env.publisher.withdraw_unpublishable(client, Event())


def test_published_frames_and_retained_clips_are_withdrawn_once(env):
    env.gateway.features = ["item_withdraw"]
    seed(env)
    withdraw(env)
    assert sorted(env.gateway.withdrawn) == ["clip-retained", "frame-by-route", "frame-listed"]
    record(env, "later", "movie_clips/a/later.png")
    env.gateway.withdrawn.clear()
    withdraw(env)
    assert env.gateway.withdrawn == []
    assert env.ledger.published("frame-listed")["state"] == "published"


def test_an_older_gateway_is_asked_nothing_and_asked_after_its_update(env):
    seed(env)
    withdraw(env)
    assert env.gateway.withdrawn == []
    env.gateway.features = ["item_withdraw"]
    withdraw(env)
    assert len(env.gateway.withdrawn) == 3


def test_a_refused_withdrawal_is_tried_again(env):
    env.gateway.features = ["item_withdraw"]
    env.gateway.refuse_withdrawals = True
    seed(env)
    withdraw(env)
    env.gateway.refuse_withdrawals = False
    withdraw(env)
    assert len(env.gateway.withdrawn) == 3


def test_working_files_published_earlier_are_withdrawn_after_an_earlier_sweep_finished(env):
    env.gateway.features = ["item_withdraw"]
    env.ledger.set_meta({"sources_withdrawn_v2": "done", "sources_withdraw_cursor_v2": "999"})
    record(env, "prepared-still", "prepared_video_sources/0a_480x832_cover.png")
    record(env, "prepared-driver", "prepared_driving_videos/0a.mp4", "video")
    record(env, "still", f"{RUN}/portrait.png")
    # The owner's own folder: no longer sent, but what is already on the phone stays.
    record(env, "owner-copy", "Best Examples/Motion Candidates/copy.mp4", "video")
    withdraw(env)
    assert sorted(env.gateway.withdrawn) == ["prepared-driver", "prepared-still"]
