"""PHONE-FAST (k): the PC links an output to the input image its job started from, by SHA-256 and ids only."""

from __future__ import annotations

import hashlib
import json
from types import SimpleNamespace

import pytest

from src.app import review_gateway_origin as origin
from src.app.review_gateway_publish import GatewayPublisher
from tests.app.test_review_gateway_sync import Env, copy_strip

FEATURES = ["item_input"]


@pytest.fixture
def env(tmp_path):
    environment = Env(tmp_path)
    environment.inputs = {}
    environment.publisher = GatewayPublisher(
        environment.library,
        environment.ledger,
        transcode=None,
        strip=copy_strip,
        input_of=lambda path: environment.inputs.get(path.name),
    )
    yield environment
    environment.close()


def sent(env) -> dict[str, dict]:
    return {
        env.ledger.published(library_id)["rel_path"].rsplit("/", 1)[-1]: manifest
        for library_id, manifest in env.gateway.manifests.items()
    }


def test_a_result_names_its_input_by_id_and_digest_and_sends_no_path(env):
    env.gateway.features = FEATURES
    env.inputs["small.png"] = str(env.large)
    env.publish_all()
    manifests = sent(env)
    named = manifests["small.png"]["input"]
    assert named["library_id"] == manifests["large.png"]["item"]["library_id"]
    assert named["sha256"] == hashlib.sha256(env.large.read_bytes()).hexdigest()
    assert "input" not in manifests["large.png"] and str(env.root) not in json.dumps(manifests)


def test_an_input_outside_the_library_is_reported_missing(env, tmp_path):
    env.gateway.features = FEATURES
    outside = tmp_path / "elsewhere.png"
    outside.write_bytes(b"not a library image")
    env.inputs["small.png"] = str(outside)
    env.inputs["large.png"] = ""  # a job with several inputs that cannot be told apart
    env.publish_all()
    assert all(manifest.get("input_missing") for manifest in sent(env).values())


def test_nothing_is_said_to_a_gateway_that_does_not_take_it(env):
    env.inputs["small.png"] = str(env.large)
    env.publish_all()
    assert not any({"input", "input_missing"} & manifest.keys() for manifest in sent(env).values())


def test_items_published_earlier_are_linked_once_when_idle(env):
    env.inputs["small.png"] = str(env.large)
    env.publish_all()
    env.gateway.features = FEATURES
    for _ in range(4):
        env.sync.run_cycle()
    assert sent(env)["small.png"]["input"]["library_id"]
    assert env.ledger.without_input_check(10) == []


def job(inputs):
    return SimpleNamespace(
        get_job=lambda _id: SimpleNamespace(snapshot={"inputs": inputs}),
    )


@pytest.fixture
def snapshots(monkeypatch):
    from src.utils import snapshot_builder_v2

    monkeypatch.setattr(
        snapshot_builder_v2,
        "normalized_job_from_snapshot",
        lambda snapshot: SimpleNamespace(input_image_paths=tuple(snapshot["inputs"])),
    )


def reader(inputs):
    return origin.job_input_reader(job(inputs), job_id_of=lambda _path: "job-1")


def test_one_recorded_input_is_the_original(snapshots, tmp_path):
    assert reader(["in.png"])(tmp_path / "out.png") == "in.png"
    assert reader([])(tmp_path / "out.png") is None
    assert reader([str(tmp_path / "out.png")])(tmp_path / "out.png") is None  # passed through


def test_several_inputs_are_told_apart_through_the_stage_manifests(snapshots, tmp_path):
    first, second = str(tmp_path / "a.png"), str(tmp_path / "b.png")
    middle, final = str(tmp_path / "mid.png"), str(tmp_path / "final.png")
    (tmp_path / "manifests").mkdir()
    for name, output, source in [("one", middle, second), ("two", final, middle)]:
        (tmp_path / "manifests" / f"{name}.json").write_text(
            json.dumps({"path": output, "input_image": source}), encoding="utf-8"
        )
    read = reader([first, second])
    assert read(tmp_path / "final.png") == second
    assert read(tmp_path / "unrecorded.png") == ""


def test_an_unreadable_job_links_nothing(tmp_path):
    broken = SimpleNamespace(get_job=lambda _id: 1 / 0)
    read = origin.job_input_reader(broken, job_id_of=lambda _path: "job-1")
    assert read(tmp_path / "out.png") is None


def test_an_input_in_the_library_but_not_sent_is_still_named(env):
    env.publish_all()
    key, sha = env.item(env.large)
    env.ledger.mark_published(
        key,
        "v1",
        env.large.relative_to(env.root).as_posix(),
        sha,
        "image",
        "skipped",
        "2026-11-27T00:00:00Z",
    )
    assert env.publisher._made_from("another-key", str(env.large)) == (key, sha)
    assert env.publisher._made_from(key, str(env.large)) is None  # never its own original
