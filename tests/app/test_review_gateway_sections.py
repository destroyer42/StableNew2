"""PHONE-FAST (g): each published item names its review section, and earlier items are named once."""

from __future__ import annotations

from threading import Event

import pytest

from src.app.review_gateway_client import GatewayClient
from src.app.review_gateway_publish import source_of
from tests.app.test_review_gateway_sync import RUN, Env
from tests.helpers.review_gateway_fakes import SECRET


@pytest.fixture
def env(tmp_path):
    environment = Env(tmp_path)
    yield environment
    environment.close()


@pytest.mark.parametrize(
    "rel_path, kind, section",
    [
        ("Pipeline/run/a.png", "image", "pipeline"),
        ("Learning/run/a.png", "image", "learning"),
        ("Learning/run/a.mp4", "video", "learning"),
        ("Reprocess/run/a.png", "image", "reprocess"),
        ("Reprocess/run/a.mp4", "video", "video"),
        ("movie_clips/run/a.mp4", "video", "video"),
        ("SVD/run/a.mp4", "video", "video"),
        ("Testing/run/a.png", "image", "testing"),
        ("Best Examples/a.png", "image", "other"),
        ("loose.png", "image", "other"),
    ],
)
def test_the_section_follows_the_folder_and_the_kind(rel_path, kind, section):
    assert source_of(rel_path, kind) == section


@pytest.mark.parametrize("features, expected", [(["item_source"], "other"), (None, None)])
def test_a_section_is_sent_only_to_a_gateway_that_takes_it(env, features, expected):
    env.gateway.features = features
    env.publish_all()
    sent = {manifest.get("source") for manifest in env.gateway.manifests.values()}
    assert sent == {expected}


def test_earlier_items_are_named_once_and_no_path_is_sent(env):
    env.gateway.features = ["item_source"]
    for library_id, rel_path, kind in [
        ("library-one", f"Learning/{RUN}/a.png", "image"),
        ("library-two", f"movie_clips/{RUN}/b.mp4", "video"),
    ]:
        env.ledger.mark_published(
            library_id, "v1", rel_path, "a" * 64, kind, "published", "2026-11-26T00:00:00Z"
        )
    client = GatewayClient(env.gateway, SECRET)
    client.health()
    env.publisher.label_published(client, Event())
    assert env.gateway.sources == {"library-one": "learning", "library-two": "video"}
    env.gateway.sources.clear()
    env.publisher.label_published(client, Event())
    assert env.gateway.sources == {}
