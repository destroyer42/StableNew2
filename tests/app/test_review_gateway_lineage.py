"""PHONE-FAST (d) on the PC: a rework result is published with the original it was made from."""

from __future__ import annotations

import json
from threading import Event

import pytest

from src.app.review_gateway_actions import REWORK_ACTIONS
from src.app.review_gateway_client import GatewayClient
from tests.app import test_review_gateway_actions as actions_tests
from tests.app.test_review_gateway_backlog import indexed
from tests.app.test_review_gateway_sync import Env
from tests.helpers.review_gateway_fakes import SECRET

ORIGINAL = ("lib-original", "ab" * 32)


@pytest.fixture
def env(tmp_path, monkeypatch):
    environment = Env(tmp_path)
    # The result's embedded job id, as the reprocess job writes it.
    monkeypatch.setattr(
        "src.app.review_gateway_publish.image_source_job",
        lambda path: "job-rework" if path.name == "small.png" else "job-other",
    )
    yield environment
    environment.close()


def publish(env, features):
    env.gateway.features = features
    client = GatewayClient(env.gateway, SECRET)
    client.health()
    indexed(env, 2)
    assert env.publisher.publish(client, limit=8, cancel=Event()).published == 2
    return {env.ledger.published(key)["rel_path"].split("/")[-1]: (key, manifest)
            for key, manifest in env.gateway.manifests.items()}


def test_rework_actions_are_the_ones_with_one_result_to_compare():
    assert REWORK_ACTIONS == {"fix_face", "fix_hands", "fix_both", "another_model", "aspect_ratio"}


def test_a_rework_result_names_its_original_and_keeps_the_lineage(env):
    env.ledger.remember_rework(["job-rework"], *ORIGINAL)
    published = publish(env, ["item_parent"])
    result_id, manifest = published["small.png"]
    assert manifest["parent"] == {"library_id": ORIGINAL[0], "sha256": ORIGINAL[1]}
    assert "parent" not in published["large.png"][1]
    assert env.ledger.rework_original_of(result_id) == ORIGINAL


def test_an_older_gateway_is_not_sent_the_field_but_the_lineage_is_kept(env):
    env.ledger.remember_rework(["job-rework"], *ORIGINAL)
    published = publish(env, None)
    result_id, manifest = published["small.png"]
    assert "parent" not in manifest
    assert env.ledger.rework_original_of(result_id) == ORIGINAL
    assert str(env.root) not in json.dumps(manifest)


def test_without_any_rework_no_image_metadata_is_read(env, monkeypatch):
    monkeypatch.setattr(
        "src.app.review_gateway_publish.image_source_job",
        lambda _path: pytest.fail("read metadata with nothing to match"),
    )
    publish(env, ["item_parent"])


@pytest.mark.parametrize(
    ("action", "params", "recorded"),
    [("fix_face", {}, True), ("more_like_this", {"count": 2}, False)],
)
def test_admitting_a_rework_records_which_jobs_rework_the_item(tmp_path, action, params, recorded):
    environment = actions_tests.Env(tmp_path)
    try:
        environment.pair()
        prepared = environment.request(action, **params)
        revision = environment.answer(prepared)["receipt"]["action_summary"]["revision"]
        ack = environment.answer(environment.confirm(prepared, revision, action))
        found = [environment.ledger.rework_original(job) for job in ack["receipt"]["job_ids"]]
        original = (environment.library_id, environment.sha)
        assert found == ([original] if recorded else [None] * len(found))
    finally:
        environment.close()
