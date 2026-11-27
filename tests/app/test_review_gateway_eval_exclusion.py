"""RG-170: eval outputs never reach the Review inbox (they are rated blind in "To rate"). Hermetic temp roots."""

from __future__ import annotations

import json
from threading import Event

import pytest

from src.app.review_gateway_client import GatewayClient
from src.app.review_gateway_sources import EVAL, SourceFilter
from tests.app.test_review_gateway_sources import absolute, make_item, publish, write_manifest
from tests.app.test_review_gateway_sync import Env
from tests.helpers.review_gateway_fakes import SECRET

RUN = "Reprocess/20261127_090000_clips"


@pytest.fixture
def env(tmp_path):
    environment = Env(tmp_path)
    environment.large.unlink()
    environment.small.unlink()
    yield environment
    environment.close()


def eval_run(env, *job_ids: str, name: str = "20261127_090000_demo_0a1b2c3d") -> None:
    folder = env.root / "video_eval" / name
    folder.mkdir(parents=True, exist_ok=True)
    jobs = [{"case_id": "c", "arm_id": "a", "job_id": job_id} for job_id in job_ids]
    (folder / "run.json").write_text(json.dumps({"jobs": jobs}), encoding="utf-8")


def clip(env, name: str, job_id: str):
    item = make_item(env, f"{RUN}/{name}", mime="video/mp4")
    folder = env.root / RUN / "manifests"
    write_manifest(
        env,
        RUN,
        video_path=absolute(env, RUN, name),
        artifact={"job_id": job_id, "primary_path": absolute(env, RUN, name)},
    )
    (folder / "clip.json").rename(folder / f"{name}.json")
    return item


def test_anything_inside_an_eval_run_folder_is_excluded(env) -> None:
    item = make_item(env, "video_eval/20261127_090000_demo_0a1b2c3d/sheet.png")
    assert SourceFilter(env.root).exclusion(item) == EVAL


def test_a_clip_made_by_an_eval_job_is_excluded_wherever_it_was_written(env) -> None:
    eval_run(env, "job-eval")
    measured = clip(env, "eval.mp4", "job-eval")
    ordinary = clip(env, "keeper.mp4", "job-ordinary")

    sources = SourceFilter(env.root)

    assert sources.exclusion(measured) == EVAL
    assert sources.exclusion(ordinary) == ""


def test_an_eval_run_recorded_after_the_first_look_is_seen(env) -> None:
    item = clip(env, "later.mp4", "job-later")
    sources = SourceFilter(env.root)
    assert sources.exclusion(item) == ""

    eval_run(env, "job-later")

    assert sources.exclusion(item) == EVAL


def test_an_unreadable_run_file_excludes_nothing_else(env) -> None:
    (env.root / "video_eval" / "broken").mkdir(parents=True)
    (env.root / "video_eval" / "broken" / "run.json").write_text("{", encoding="utf-8")
    eval_run(env, "job-eval")

    sources = SourceFilter(env.root)

    assert sources.exclusion(clip(env, "eval.mp4", "job-eval")) == EVAL
    assert sources.exclusion(clip(env, "keeper.mp4", "job-ordinary")) == ""


def test_the_publisher_sends_no_eval_clip(env, monkeypatch) -> None:
    eval_run(env, "job-eval")
    measured = clip(env, "eval.mp4", "job-eval")
    ordinary = clip(env, "keeper.mp4", "job-ordinary")

    result = publish(env, monkeypatch, measured, ordinary)

    assert result.published == 1
    assert [m["media"]["original"]["bytes"] for m in env.gateway.manifests.values()] == [
        ordinary.version[2]
    ]


def test_the_job_a_comfy_clips_manifest_records_inside_its_compiled_workflow_counts(env) -> None:
    # The shape of real video-workflow manifests: artifact.job_id is empty there.
    eval_run(env, "job-eval")
    item = make_item(env, f"{RUN}/comfy.mp4", mime="video/mp4")
    write_manifest(
        env,
        RUN,
        video_path=absolute(env, RUN, "comfy.mp4"),
        artifact={"job_id": None},
        compiled_workflow={"compiler_metadata": {"job_id": "job-eval"}},
    )

    assert SourceFilter(env.root).exclusion(item) == EVAL


def test_eval_clips_published_earlier_are_withdrawn_even_after_the_frame_sweep_ran(env) -> None:
    # The PHONE-FAST sweep may already have finished on this PC, before eval outputs were excluded.
    env.gateway.features = ["item_withdraw"]
    eval_run(env, "job-eval")
    clip(env, "eval.mp4", "job-eval")
    clip(env, "keeper.mp4", "job-ordinary")
    for library_id, name in (("eval-clip", "eval.mp4"), ("keeper-clip", "keeper.mp4")):
        env.ledger.mark_published(
            library_id,
            "v1",
            f"{RUN}/{name}",
            "a" * 64,
            "video",
            "published",
            "2026-11-26T00:00:00Z",
        )
    env.ledger.set_meta({"sources_withdrawn": "done", "sources_withdraw_cursor": "999"})
    client = GatewayClient(env.gateway, SECRET)
    client.health()

    env.publisher.withdraw_unpublishable(client, Event())

    assert env.gateway.withdrawn == ["eval-clip"]
