"""PHONE-FAST (c): every published image has a phone-sized WebP, and older publications get one while idle."""

from __future__ import annotations

import io
from threading import Event

import pytest
from PIL import Image

from src.app.review_gateway_client import GatewayClient
from src.app.review_gateway_publish import encode_preview_1080
from tests.app.test_review_gateway_sync import Env
from tests.helpers.review_gateway_fakes import SECRET


@pytest.fixture
def env(tmp_path):
    environment = Env(tmp_path)
    yield environment
    environment.close()


def publish(env, **options):
    return env.publisher.publish(
        GatewayClient(env.gateway, SECRET), limit=8, cancel=Event(), **options
    )


@pytest.mark.parametrize(
    ("size", "expected"), [((1024, 1024), (1024, 1024)), ((2160, 1440), (1080, 720))]
)
def test_the_rendition_is_a_webp_of_at_most_1080_px(size, expected):
    source = io.BytesIO()
    Image.new("RGB", size, "#336699").save(source, "PNG")
    source.seek(0)
    encoded = encode_preview_1080(source, "image/png")
    assert encoded is not None
    data, content_type, width, height = encoded
    assert content_type == "image/webp" and (width, height) == expected
    assert len(data) < len(source.getvalue())


def forget_rendition(env, library_id: str) -> None:
    """As an item published before renditions: no preview at the gateway, no mark in the ledger."""

    with env.ledger._transaction() as db:
        db.execute("DELETE FROM renditions WHERE library_id = ?", (library_id,))
    env.gateway.manifests[library_id]["media"].pop("preview_1080")


def test_a_small_image_is_published_with_a_rendition(env):
    env.publish_all()
    small_id, _sha = env.item(env.small)
    assert env.gateway.manifests[small_id]["media"]["preview_1080"]["content_type"] == "image/webp"
    assert env.ledger.without_rendition(10) == []


def test_an_item_published_without_a_rendition_gets_one_while_idle_only(env):
    env.publish_all()
    library_id, _sha = env.item(env.small)
    forget_rendition(env, library_id)

    publish(env, hold_unlabelled_video=True)  # a job is running
    assert "preview_1080" not in env.gateway.manifests[library_id]["media"]

    assert publish(env).published == 1
    assert "preview_1080" in env.gateway.manifests[library_id]["media"]
    assert env.ledger.without_rendition(10) == []
    assert publish(env).published == 0


@pytest.mark.parametrize("change", ["gone", "frame"])
def test_an_upgrade_never_overwrites_a_published_row(env, monkeypatch, change):
    env.publish_all()
    library_id, _sha = env.item(env.small)
    forget_rendition(env, library_id)
    if change == "gone":
        env.small.unlink()
    else:
        monkeypatch.setattr(env.publisher._sources, "exclusion", lambda _item: "frame")
    publish(env)
    publish(env)
    row = env.ledger.published(library_id)
    assert row["state"] == "published" and row["sha256"]
