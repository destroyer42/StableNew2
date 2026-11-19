from __future__ import annotations

import json
from dataclasses import replace
from sqlite3 import OperationalError
from unittest.mock import Mock

from PIL import Image

from src.app.site_output_catalog import SiteOutputCatalog
from src.app.site_phone_connector import _desktop_call
from src.app.site_phone_credentials import PhoneFolder, PhoneGrant
from src.app.site_phone_queue import (
    PHONE_QUEUE_PATH,
    PHONE_SUBMISSION,
    PhoneQueueView,
    phone_job_id,
    phone_owner,
)
from src.controller.job_service import JobService
from src.pipeline.njr_compiler import NjrDerivation, derive_njr
from src.queue.job_model import JobStatus
from src.queue.job_queue import JobQueue
from src.queue.job_repository import JobRepository
from tests.helpers.job_helpers import make_test_njr


def _records(grant, receipt, count):
    owner = phone_owner(grant)
    draft = make_test_njr(prompt="private prompt")
    return tuple(
        derive_njr(
            draft,
            NjrDerivation(
                job_id=phone_job_id(owner, receipt, index),
                provenance=replace(
                    draft.provenance,
                    metadata={
                        PHONE_SUBMISSION: {
                            "owner": owner,
                            "receipt": receipt,
                            "index": index,
                            "count": count,
                            "kind": "promptpack",
                        }
                    },
                ),
            ),
        )
        for index in range(count)
    )


def test_phone_queue_receipt_survives_new_presence_and_does_not_cross_grants(tmp_path):
    output = tmp_path / "output"
    output.mkdir()
    grant = PhoneGrant(
        "1" * 32, "Fixture", "site-secret", "2" * 64, PhoneFolder.approve(output), True
    )
    stranger = replace(grant, id="3" * 32, native_review=True)
    receipt_id = "a" * 32
    records = _records(grant, receipt_id, 2)
    database = tmp_path / "jobs.sqlite3"
    repository = JobRepository(database)
    queue = JobQueue(repository=repository)
    runner = Mock(job_queue=queue, is_running=lambda: True)
    service = JobService(queue, runner=runner)
    try:
        ids = service.submit_njrs(records)
        # A replay can inherit metadata. Its distinct NJR identity must keep it out of the projection.
        replay = derive_njr(records[0], NjrDerivation(job_id="b" * 32))
        service.submit_njrs((replay, make_test_njr()))
        image = output / "final.png"
        outside = tmp_path / "unshared.png"
        for path in (image, outside):
            Image.new("RGB", (16, 16), "green").save(path)
        running = repository.transition_job(repository.get_job_model(ids[0]), JobStatus.RUNNING)
        repository.transition_job(
            running, JobStatus.COMPLETED, result={"output_paths": [str(image), str(outside)]}
        )
        runner.run_once.assert_not_called()
    finally:
        repository.close()

    repository = JobRepository(database)
    try:
        queue = JobQueue(repository=repository)
        view = PhoneQueueView(repository, JobService(queue, runner=Mock(job_queue=queue)))
        catalog = SiteOutputCatalog(output)

        def get(path, device=grant):
            reply = _desktop_call(
                catalog,
                "GET",
                PHONE_QUEUE_PATH + "/" + path,
                None,
                device.rating,
                phone_queue=view,
                grant=device,
            )
            assert b"private prompt" not in reply.data
            assert str(tmp_path).encode() not in reply.data
            return json.loads(reply.data)

        queue.pause()
        page = get("list")
        assert [(row["job_id"], row["status"], row["cause"]) for row in page["jobs"]] == [
            (ids[1], "blocked", "queue_paused"),
            (ids[0], "completed", None),
        ]
        assert get("list", stranger)["jobs"] == []
        assert get("receipt/" + receipt_id)["job_ids"] == ids
        assert get("receipt/" + receipt_id, stranger)["state"] == "unconfirmed"
        assert get("result/" + ids[0], stranger) == {"error": "unknown_job"}
        assert get("result/" + replay.job_id) == {"error": "unknown_job"}
        assets = get("result/" + ids[0])["media"]
        assert len(assets) == 1
        assert catalog.read_media(assets[0]["id"])[1] == image.read_bytes()
        assert (
            _desktop_call(
                catalog, "POST", PHONE_QUEUE_PATH + "/list", {}, True, phone_queue=view, grant=grant
            ).status
            == 403
        )
        catalog.revoke()
        assert get("list") == {"error": "output_folder_not_shared"}
    finally:
        repository.close()


def test_partial_projection_cannot_confirm_a_receipt(tmp_path):
    grant = PhoneGrant(
        "1" * 32, "Fixture", "site-secret", "2" * 64, PhoneFolder.approve(tmp_path), False
    )
    receipt_id = "a" * 32
    repository = JobRepository(tmp_path / "jobs.sqlite3")
    try:
        queue = JobQueue(repository=repository)
        service = JobService(queue, runner=Mock(job_queue=queue, is_running=lambda: True))
        service.submit_njrs(_records(grant, receipt_id, 2)[:1])
        assert PhoneQueueView(repository, service).receipt(phone_owner(grant), receipt_id) == {
            "receipt_id": receipt_id,
            "state": "unconfirmed",
            "job_ids": [],
        }
    finally:
        repository.close()


def test_queue_database_failure_returns_a_reply_and_keeps_native_details_private(tmp_path):
    grant = PhoneGrant(
        "1" * 32, "Fixture", "site-secret", "2" * 64, PhoneFolder.approve(tmp_path), False
    )
    queue_view = Mock(spec=PhoneQueueView)
    queue_view.handle.side_effect = OperationalError("database with private location locked")
    reply = _desktop_call(
        SiteOutputCatalog(tmp_path),
        "GET",
        PHONE_QUEUE_PATH + "/list",
        None,
        False,
        phone_queue=queue_view,
        grant=grant,
    )
    assert reply.status == 503
    assert json.loads(reply.data) == {"error": "queue_unavailable"}
