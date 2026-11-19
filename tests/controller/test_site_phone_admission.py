from __future__ import annotations

import json
from dataclasses import replace
from functools import partial
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from src.app.site_output_catalog import SiteOutputCatalog
from src.app.site_phone_admission import PhoneQueueAdmission
from src.app.site_phone_connector import _desktop_call
from src.app.site_phone_credentials import PhoneFolder, PhoneGrant
from src.app.site_phone_preview_host import PhonePreviewHost
from src.app.site_phone_queue import PHONE_QUEUE_PATH, PhoneQueueView
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
from tests.controller.test_site_output_library import _library, _search
from tests.gui_v2.test_review_batch_200 import images


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
    )

    def call(route, body=None, *, device=grant, source=catalog):
        reply = _desktop_call(
            source,
            "GET" if body is None else "POST",
            PHONE_QUEUE_PATH + "/" + route,
            body,
            device.rating,
            phone_queue=admission,
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
