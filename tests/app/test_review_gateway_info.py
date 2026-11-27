"""NAME-INFO on the PC: "More info" goes with the manifest, only to a gateway that takes it, and never with a path."""

from __future__ import annotations

import json
from threading import Event

import pytest

from src.app.review_gateway_client import GatewayClient
from src.app.review_gateway_protocol import ItemRef, MediaVariant, item_manifest
from src.app.review_gateway_publish import GatewayPublisher, job_info_reader
from tests.app.test_review_gateway_backlog import indexed
from tests.app.test_review_gateway_sync import Env
from tests.helpers.review_gateway_fakes import SECRET, validate_def


@pytest.fixture
def env(tmp_path):
    environment = Env(tmp_path)
    yield environment
    environment.close()


def publish(env, features, info_of):
    env.publisher = GatewayPublisher(env.library, env.ledger, transcode=None, info_of=info_of)
    env.gateway.features = features
    client = GatewayClient(env.gateway, SECRET)
    client.health()
    indexed(env, 2)
    assert env.publisher.publish(client, limit=8, cancel=Event()).published == 2
    return list(env.gateway.manifests.values())


def test_info_goes_with_the_manifest_to_a_gateway_that_takes_it(env):
    manifests = publish(env, ["item_info"], job_info_reader(None, lambda _job: None))
    assert len(manifests) == 2
    for manifest in manifests:
        # These two files carry no StableNew record, and their names are not descriptive ones (so not sent).
        assert set(manifest["info"]) == {"made_at"}
        validate_def(manifest, "item_manifest")
        assert str(env.root) not in json.dumps(manifest)


def test_an_older_gateway_is_not_sent_info_and_nothing_is_read(env):
    manifests = publish(env, None, lambda _path, _item: pytest.fail("described for no one"))
    assert all("info" not in manifest for manifest in manifests)


def test_a_description_that_fails_never_holds_an_item_back(env):
    def broken(_path, _item):
        raise RuntimeError("the job database is locked")

    assert all("info" not in manifest for manifest in publish(env, ["item_info"], broken))


def test_the_manifest_keeps_only_bounded_known_fields_without_paths():
    media = MediaVariant("ab" * 32, 10, "image/png")
    manifest = item_manifest(
        item=ItemRef("lib-12345678", "ab" * 32),
        kind="image",
        run_id="20261127_164800_000-Style_photoMomentum",
        created_at=__import__("datetime").datetime.fromisoformat("2026-11-27T16:48:00+00:00"),
        media={"thumb_320": media, "original": media},
        info={
            "stage_path": "txt2img",
            "model": "x" * 90,
            "model_name": "C:\\models\\sdxl\\photoMomentum.safetensors",
            "pack": "  ",
            "prompt_number": 1,
            "variant": 0,
            "seed": "-1",
            "made_at": "yesterday",
            "batch": "night",
            "path": "C:\\secret",
        },
    )

    assert manifest["info"] == {
        "stage_path": "txt2img",
        "model": "x" * 39 + "…",
        "model_name": "photoMomentum.safetensors",
        "prompt_number": 1,
        "batch": "night",
    }
    validate_def(manifest, "item_manifest")
