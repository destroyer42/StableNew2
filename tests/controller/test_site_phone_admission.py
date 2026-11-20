from __future__ import annotations

import json
from dataclasses import replace
from functools import partial
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from PIL import Image

from src.app.site_output_catalog import SiteOutputCatalog
from src.app.site_phone_admission import PhoneQueueAdmission
from src.app.site_phone_connector import _desktop_call
from src.app.site_phone_credentials import PhoneFolder, PhoneGrant
from src.app.site_phone_eval import PhoneEvalReports
from src.app.site_phone_preview_host import PhonePreviewHost
from src.app.site_phone_queue import PHONE_QUEUE_PATH, PhoneQueueView
from src.app.site_phone_video import PhoneVideo
from src.controller.app_controller import AppController
from src.controller.job_service import JobService
from src.controller.pipeline_controller import PipelineController
from src.gui.app_state_v2 import AppStateV2
from src.learning.learning_record import LearningRecordWriter
from src.pipeline.job_builder_v2 import JobBuilderV2
from src.pipeline.prompt_pack_job_builder import PromptPackNormalizedJobBuilder
from src.queue.job_model import JobStatus
from src.queue.job_queue import JobQueue
from src.queue.job_repository import JobRepository
from src.review.review_evidence import save_disposition
from src.review.review_lineage import verified_review_outputs
from src.utils.config import ConfigManager
from src.utils.prompt_packs import PromptPackInfo
from src.video.video_eval_metrics import ClipMeasurement
from src.video.video_eval_report import build_eval_report
from tests.controller.test_site_output_library import _library, _search
from tests.gui_v2.test_review_batch_200 import images
from tests.video.test_pr_vid_eval_320_report import _metrics


@pytest.fixture
def native(tmp_path):
    output = tmp_path / "output"
    output.mkdir()
    repository = JobRepository(tmp_path / "jobs.sqlite3")
    queue = JobQueue(repository=repository)
    runner = Mock(job_queue=queue, is_running=lambda: True)
    jobs = JobService(queue, runner=runner)
    records = tmp_path / "review.jsonl"
    catalog = SiteOutputCatalog(output, review_outputs=partial(verified_review_outputs, repository))
    grant = PhoneGrant(
        "1" * 32,
        "Synthetic phone",
        "fixture",
        "2" * 64,
        PhoneFolder.approve(output),
        False,
        queue_submit=True,
    )
    app = AppController(main_window=None, threaded=False, pipeline_runner=None)
    app.app_state = AppStateV2()
    app.app_state.set_pipeline_stage_enabled("txt2img", True)
    app._packs_dir = tmp_path
    app._config_manager = ConfigManager(presets_dir=tmp_path / "presets", packs_dir=tmp_path)
    app._build_reprocess_config = lambda _: {
        "model": "sdxl-fixture.safetensors",
        "steps": 20,
        "cfg_scale": 7,
        "img2img": {"denoising_strength": 0.3},
    }
    compiler = object.__new__(PipelineController)
    builder = PromptPackNormalizedJobBuilder(
        config_manager=app._config_manager, job_builder=JobBuilderV2(), packs_dir=tmp_path
    )
    compiler._get_prompt_pack_builder = lambda: builder
    app.pipeline_controller = compiler
    host = PhonePreviewHost(app, repository, records)
    queue_view = PhoneQueueView(repository, jobs)
    admission = PhoneQueueAdmission(
        queue_view,
        jobs,
        packs=host.packs,
        compile_pack=host.compile_pack,
        compile_rework=host.compile_rework,
        video=PhoneVideo(jobs),
    )
    reports = PhoneEvalReports(repository)

    def call(route, body=None, *, device=grant, source=catalog, prefix=PHONE_QUEUE_PATH):
        reply = _desktop_call(
            source,
            "GET" if body is None else "POST",
            prefix + "/" + route,
            body,
            device.rating,
            phone_queue=admission,
            phone_eval=reports,
            grant=device,
        )
        return reply.status, json.loads(reply.data)

    try:
        yield SimpleNamespace(
            root=output,
            repository=repository,
            jobs=jobs,
            runner=runner,
            app=app,
            host=host,
            review=records,
            catalog=catalog,
            grant=grant,
            call=call,
        )
    finally:
        runner.run_once.assert_not_called()
        catalog.revoke()
        repository.close()


def test_promptpack_phone_preview_is_detached_frozen_and_admitted_once(
    native, tmp_path, monkeypatch
):
    pack = tmp_path / "fixture.json"
    document = {
        "schema_version": 1,
        "pack_data": {
            "name": "fixture",
            "slots": [{"text": "first saved slot"}, {"text": "second saved slot"}],
        },
        "preset_data": {},
    }
    pack.write_text(json.dumps(document), encoding="utf-8")
    native.app.packs = [PromptPackInfo("fixture", pack)]
    native.app.app_state.add_job_draft_part("unsent desktop draft", "", 1)
    draft_snapshot = native.app.app_state.snapshot_accepted_preview()
    caller = native.call
    no_submit = replace(native.grant, queue_submit=False, rating=True, native_review=True)
    assert caller("packs", device=no_submit) == (403, {"error": "phone_scope_refused"})
    pack_id = caller("packs")[1]["packs"][0]["id"]

    def prepare():
        status, details = caller("packs/" + pack_id)
        assert status == 200
        status, preview = caller(
            "preview",
            {
                "kind": "promptpack",
                "pack_id": pack_id,
                "revision": details["revision"],
                "slots": [1],
            },
        )
        assert status == 200, preview
        assert len(preview["jobs"]) == 1 and preview["jobs"][0]["slot"] == 2
        assert not native.repository.list_jobs()
        return preview, {"preview_id": preview["preview_id"], "confirmed": True}

    _, stale = prepare()
    pack.write_text(json.dumps(document) + "\n", encoding="utf-8")
    assert caller("submit", stale)[1]["cause"] == "preview_changed"
    assert caller("receipt/" + stale["preview_id"])[1]["state"] == "refused"
    preview, submit = prepare()
    assert caller("submit", {**submit, "confirmed": False})[0] == 409
    assert caller("submit", submit, device=no_submit)[0] == 403
    other = replace(native.grant, id="3" * 32)
    assert caller("submit", submit, device=other)[1]["state"] == "unconfirmed"
    real_submit = native.jobs.submit_njrs

    def lose_response(records, *_args, **_kwargs):
        real_submit(records)
        raise RuntimeError("synthetic exception after the SQLite commit")

    monkeypatch.setattr(native.jobs, "submit_njrs", Mock(side_effect=lose_response))
    (_, receipt) = caller("submit", submit)
    assert receipt["state"] == "admitted"
    assert receipt["job_ids"] == [preview["jobs"][0]["job_id"]]
    assert caller("submit", submit)[1] == receipt
    native.jobs.submit_njrs.assert_called_once()
    row = native.repository.get_job_model(receipt["job_ids"][0])
    assert row._normalized_record.positive_prompt == "second saved slot"
    assert native.app.app_state.snapshot_accepted_preview() == draft_snapshot
    assert native.app.app_state.job_draft.parts[0].positive_prompt == "unsent desktop draft"
    rebound = SiteOutputCatalog(native.root)
    assert caller("receipt/" + submit["preview_id"], source=rebound)[1] == receipt
    rebound.revoke()


def test_phone_rework_rechecks_mark_and_bytes_and_returns_native_lineage(native):
    image, child = images(native.root, 2)
    ids = {item["name"]: item["id"] for item in _search(native.catalog)["items"]}
    target = ids[image.name]
    digest = _library(native.catalog, "inspect", id=target)["digest"]
    request = {
        "kind": "rework",
        "scope": native.catalog.scope,
        "id": target,
        "digest": digest,
        "stage": "img2img",
    }
    assert native.call("preview", request) == (409, {"error": "rework_mark_required"})
    assert native.call("preview", {**request, "digest": "0" * 64}) == (
        409,
        {"error": "media_changed"},
    )
    writer = LearningRecordWriter(native.review)

    def decide(disposition):
        save_disposition(
            writer,
            image_path=image,
            artifact_sha256=digest,
            disposition=disposition,
            source_job_id="parent-0",
        )

    decide("rework")
    status, preview = native.call("preview", request)
    assert status == 200, preview
    assert not native.repository.list_jobs()
    decide("retain")
    assert (
        native.call("submit", {"preview_id": preview["preview_id"], "confirmed": True})[1]["state"]
        == "refused"
    )
    decide("rework")
    status, preview = native.call("preview", request)
    assert status == 200, preview
    (_, receipt) = native.call("submit", {"preview_id": preview["preview_id"], "confirmed": True})
    assert receipt["state"] == "admitted"
    record = native.repository.get_job_model(receipt["job_ids"][0])
    assert record._normalized_record.source.parent_job_id == "parent-0"
    assert record._normalized_record.source.parent_artifact_id == "sha256:" + digest
    assert native.call("preview", request)[1]["error"] == "rework_already_in_progress_or_returned"
    running = native.repository.transition_job(record, JobStatus.RUNNING)
    native.repository.transition_job(
        running,
        JobStatus.COMPLETED,
        result={
            "success": True,
            "artifact": {
                "stage": "img2img",
                "artifact_type": "image",
                "primary_path": str(child),
                "output_paths": [str(child)],
            },
        },
    )
    returned = _library(native.catalog, "review_results", id=target, digest=digest)["results"]
    assert [result["item"]["id"] for result in returned] == [ids[child.name]]


def _arm(workflow, version, opt_in=False):
    return {
        "workflow_id": workflow,
        "workflow_version": version,
        "experimental_opt_in": opt_in,
    }


BASE = _arm("wan22_ti2v_5b_i2v_v1", "1.3.0")
ALTERNATE = _arm("wan22_ti2v_5b_i2v_720p_v1", "1.0.0")
CANDIDATE = _arm("wan22_i2v_a14b_4step_v1", "1.0.0")


def _video_request(native, arms, *, kind="video_eval"):
    Image.new("RGB", (96, 64), "red").save(native.root / "landscape.png")
    Image.new("RGB", (64, 96), "blue").save(native.root / "portrait.png")
    sources = [
        {"id": item["id"], "digest": _library(native.catalog, "inspect", id=item["id"])["digest"]}
        for item in _search(native.catalog)["items"]
    ]
    assert len(sources) == 2
    return {
        "kind": kind,
        "scope": native.catalog.scope,
        "sources": sources,
        "arms": arms,
        "prompt": "Pan slowly as the subject turns.",
        "negative_prompt": "flicker",
        "seed": 1234,
        "frames": 81,
    }


def test_phone_video_workflow_catalog_and_frozen_admission(native):
    not_allowed = replace(native.grant, queue_submit=False)
    assert native.call("video-options", device=not_allowed)[0] == 403
    status, options = native.call("video-options")
    assert status == 200 and options["default"] == [CANDIDATE["workflow_id"], "1.0.0"]
    assert all("drive_i2v" not in item["workflow_id"] for item in options["workflows"])
    command = _video_request(native, [BASE], kind="video")
    command["sources"] = command["sources"][:1]
    status, preview = native.call("preview", command)
    assert status == 200, preview
    assert len(preview["jobs"]) == 1 and not native.repository.list_jobs()
    assert sorted((preview["jobs"][0]["width"], preview["jobs"][0]["height"])) == [480, 832]
    assert str(native.root) not in json.dumps(preview)
    (native.root / preview["jobs"][0]["source"]).write_bytes(b"changed")
    request = {"preview_id": preview["preview_id"], "confirmed": True}
    assert native.call("submit", request)[1]["state"] == "refused"
    assert not native.repository.list_jobs()


def test_phone_eval_opt_in_is_per_arm_and_invalid_matrix_is_not_admitted(native, monkeypatch):
    experimental = _arm(BASE["workflow_id"], "1.4.0")
    command = _video_request(native, [BASE, experimental, CANDIDATE])
    assert native.call("preview", command)[1]["error"] == "experimental_opt_in_required"
    command["arms"][1] = {**experimental, "experimental_opt_in": True}
    assert (
        native.call("preview", {**command, "frames": 82})[1]["error"] == "invalid_video_frame_count"
    )
    status, preview = native.call("preview", command)
    assert status == 200, preview
    assert {row["arm"] for row in preview["jobs"] if row["experimental"]} == {"arm-2"}
    assert not native.repository.list_jobs()

    from src.video.video_workflow_njr_builder import VideoWorkflowNjrBuilder

    build = VideoWorkflowNjrBuilder.build_job

    def fail_one_case(builder, form, frozen, **kwargs):
        if form["workflow_version"] == "1.4.0" and frozen.source_image_path.endswith(
            "portrait.png"
        ):
            raise ValueError("The experimental arm cannot use this synthetic case")
        return build(builder, form, frozen, **kwargs)

    monkeypatch.setattr(VideoWorkflowNjrBuilder, "build_job", fail_one_case)
    assert native.call("preview", command)[1]["error"] == "video_preview_failed"
    submit = {"preview_id": preview["preview_id"], "confirmed": True}
    assert native.call("submit", submit)[1]["state"] == "unconfirmed"
    assert not native.repository.list_jobs()


def test_phone_eval_480p_720p_alternate_receipt_and_report_refresh(native, monkeypatch):
    command = _video_request(native, [BASE, ALTERNATE, CANDIDATE])
    status, preview = native.call("preview", command)
    assert status == 200, preview
    assert len(preview["jobs"]) == 6 and not native.repository.list_jobs()
    assert {row["frames"] for row in preview["jobs"]} == {81}
    assert {row["seed"] for row in preview["jobs"]} == {1234}
    assert {(row["width"], row["height"], row["fps"]) for row in preview["jobs"]} == {
        (832, 480, 24),
        (480, 832, 24),
        (1280, 704, 24),
        (704, 1280, 24),
        (832, 480, 16),
        (480, 832, 16),
    }
    assert all(row["models"] and row["graph_revision"] for row in preview["jobs"])
    caller = {"preview_id": preview["preview_id"], "confirmed": True}

    def notify_failed():
        raise RuntimeError("Synthetic notification interruption after native commit")

    monkeypatch.setattr(native.jobs, "_on_queue_activity", notify_failed, raising=False)
    _, receipt = native.call("submit", caller)
    assert receipt["state"] == "admitted"
    assert native.call("submit", caller)[1] == receipt
    run_id = receipt["eval_run"]
    directory = native.root / "video_eval" / run_id
    manifest = json.loads((directory / "run.json").read_bytes())
    assert [job["job_id"] for job in manifest["jobs"]] == receipt["job_ids"]
    assert len(native.repository.list_jobs()) == 6
    assert native.call("runs", prefix="/v1/phone-eval")[1]["runs"] == [
        {"id": run_id, "built": False, "refresh": None}
    ]
    for job_id in receipt["job_ids"]:
        job = native.repository.get_job_model(job_id)
        clip = native.root / (job_id + ".mp4")
        clip.write_bytes(b"\x00\x00\x00\x16ftypmp42" + job_id.encode())
        running = native.repository.transition_job(job, JobStatus.RUNNING)
        native.repository.transition_job(
            running, JobStatus.COMPLETED, result={"video_bundle": {"primary_path": str(clip)}}
        )
    job_id = receipt["job_ids"][0]
    assert native.call("result/" + job_id)[1]["media"][0]["type"] == "video/mp4"
    monkeypatch.setattr(
        "src.app.site_phone_eval.build_eval_report",
        lambda *args, **kwargs: build_eval_report(
            *args,
            measure=lambda path, **_kwargs: ClipMeasurement(str(path), True, _metrics(3.0)),
            **kwargs,
        ),
    )
    monkeypatch.setattr(
        "src.app.site_phone_eval.get_thread_registry",
        lambda: SimpleNamespace(spawn=lambda *, target, **_kwargs: target()),
    )
    refresh = "refresh/" + run_id
    body = {"scope": native.catalog.scope}
    assert native.call(refresh, body, prefix="/v1/phone-eval")[0] == 403
    rater = replace(native.grant, rating=True, queue_submit=False)
    assert native.call(refresh, body, prefix="/v1/phone-eval", device=rater)[0] == 200
    result = native.catalog.get_run(run_id, review=True)
    assert result["report_revision"] == result["revision"] and not result["report_stale"]
    assert len(result["pairs"]) == 4
    clip = result["clips"][0]
    native.catalog.save_rating(
        run_id,
        {
            **body,
            "revision": result["revision"],
            "case_id": clip["case"],
            "arm_id": clip["arm_id"],
            "job_id": clip["job_id"],
            "artifact_sha256": clip["artifact_sha256"],
            "source_sha256": clip["source_sha256"],
            "rebind": False,
            "judgments": {"notes": "Synthetic review"},
        },
    )
    stale = native.catalog.get_run(run_id, review=True)
    assert stale["report_stale"] and stale["report_revision"] != stale["revision"]
    assert native.call(refresh, body, prefix="/v1/phone-eval", device=rater)[0] == 200
    refreshed = native.catalog.get_run(run_id, review=True)
    assert refreshed["report_revision"] == refreshed["revision"] and not refreshed["report_stale"]
    assert refreshed["clips"][0]["rating"]["notes"] == "Synthetic review"


def test_phone_report_refresh_refuses_source_outside_share(native, tmp_path):
    request = _video_request(native, [BASE, ALTERNATE])
    _, preview = native.call("preview", request)
    _, receipt = native.call("submit", {"preview_id": preview["preview_id"], "confirmed": True})
    run_id = receipt["eval_run"]
    manifest_path = native.root / "video_eval" / run_id / "run.json"
    manifest = json.loads(manifest_path.read_bytes())
    private = tmp_path / "private.png"
    Image.new("RGB", (20, 12), "green").save(private)
    manifest["cases"][0]["image"] = str(private)
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    with pytest.raises(RuntimeError, match="outside shared Output"):
        PhoneEvalReports(native.repository)._build(native.catalog, run_id)
    assert not (manifest_path.parent / "ratings.csv").exists()
    assert not (manifest_path.parent / "metrics.json").exists()
