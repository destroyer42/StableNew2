from __future__ import annotations

import io
import json
from email.message import Message
from http import HTTPStatus
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from src.app.site_queue_bridge import SITE_ORIGIN, SiteSession, make_handler
from src.controller.app_controller import AppController
from src.controller.job_service import JobService
from src.gui.site_connection_dialog import PreviewQueueConnection
from src.pipeline.job_models_v2 import WorkloadKind
from src.queue.job_queue import JobQueue
from src.queue.job_repository import JobRepository
from tests.helpers.job_helpers import make_test_njr

PORT = 49381


def request(
    session, method, path, *, origin=SITE_ORIGIN, host=f"127.0.0.1:{PORT}", token=None, body=b""
):
    handler_type = make_handler(session, PORT)
    handler = handler_type.__new__(handler_type)
    handler.command = method
    handler.path = path
    handler.request_version = "HTTP/1.1"
    handler.requestline = f"{method} {path} HTTP/1.1"
    handler.headers = Message()
    handler.headers["Origin"] = origin
    handler.headers["Host"] = host
    if token is not None:
        handler.headers["Authorization"] = f"Bearer {token}"
    if method == "OPTIONS":
        handler.headers["Access-Control-Request-Method"] = "GET"
    if body:
        handler.headers["Content-Length"] = str(len(body))
        handler.headers["Content-Type"] = "application/json"
    handler.rfile = io.BytesIO(body)
    handler.wfile = io.BytesIO()
    getattr(handler, f"do_{method}")()
    raw_headers, _, raw_body = handler.wfile.getvalue().partition(b"\r\n\r\n")
    return (
        int(raw_headers.splitlines()[0].split()[1]),
        raw_headers,
        json.loads(raw_body) if raw_body else None,
    )


def native_connection(confirm=lambda _count: True):
    jobs = tuple(
        SimpleNamespace(
            job_id=f"image-{i}", workload_kind=WorkloadKind.IMAGE, stage_chain_labels=["txt2img"]
        )
        for i in (1, 2)
    )
    native_state = SimpleNamespace(witness=(9, jobs))
    calls = []
    committed = set()
    fallback = []

    def submit(records, **_kwargs):
        calls.append(tuple(records))
        committed.update(job.job_id for job in records)
        return len(records)

    app = object.__new__(AppController)
    app.app_state = SimpleNamespace(
        snapshot_accepted_preview=lambda: native_state.witness,
        preview_jobs=list(jobs),
        clear_admitted_draft=lambda _jobs: True,
    )
    app.pipeline_controller = SimpleNamespace(
        submit_preview_jobs_to_queue=submit,
        enqueue_draft_jobs=lambda **_kwargs: fallback.append("unexpected"),
    )
    app._is_shutting_down = False
    app._queue_submit_in_progress = False
    app._append_log = lambda _message: None
    app._prepare_queue_run_config = dict
    app._ensure_run_mode_default = lambda _source: None
    app._spawn_tracked_thread = lambda *, target, args, **_kwargs: target(*args)
    app._ui_dispatch = lambda f: f()
    app.job_service = SimpleNamespace(
        history_store=SimpleNamespace(get_job=lambda job: job if job in committed else None)
    )
    session = SiteSession()
    conn = PreviewQueueConnection(app, session, confirm)
    conn.tick()
    return conn, session, native_state, jobs, calls, fallback


def test_site_receipt_is_one_existing_preview_submission():
    conn, session, _state, jobs, calls, fallback = native_connection()
    status, headers, preview = request(session, "GET", "/v1/preview", token=session.code)
    assert status == HTTPStatus.OK
    assert SITE_ORIGIN.encode() in headers
    assert list(preview["jobs"][0]) == ["job_id", "stages"]
    assert preview["jobs"][0]["job_id"] == jobs[0].job_id
    body = json.dumps({"preview_id": preview["preview_id"]}).encode()

    status, _headers, submitted = request(
        session, "POST", "/v1/submit", token=session.code, body=body
    )
    assert status == HTTPStatus.ACCEPTED
    assert submitted["state"] == "awaiting_confirmation"
    assert calls == []
    conn.tick()
    conn.tick()

    status, _headers, receipt = request(session, "GET", "/v1/receipt", token=session.code)
    assert status == HTTPStatus.OK
    assert receipt["receipt_id"] == submitted["receipt_id"]
    assert receipt["state"] == "queued"
    assert receipt["job_ids"] == [job.job_id for job in jobs]
    assert calls == [jobs]
    assert all(calls[0][i] is jobs[i] for i in range(len(jobs)))
    assert not fallback

    _status, _headers, duplicate = request(
        session, "POST", "/v1/submit", token=session.code, body=body
    )
    conn.tick()
    assert duplicate == receipt
    assert calls == [jobs]


@pytest.mark.parametrize("bad", ["origin", "host", "token"])
def test_site_rejects_unauthorized_requests(bad):
    _conn, session, _state, _jobs, calls, _fallback = native_connection()
    kwargs = {"token": session.code}
    kwargs[bad] = "wrong"
    status, headers, _body = request(session, "GET", "/v1/preview", **kwargs)
    assert status in (HTTPStatus.FORBIDDEN, HTTPStatus.UNAUTHORIZED)
    if bad != "token":
        assert b"Access-Control-Allow-Origin" not in headers
    assert calls == []


def test_revoked_pairing_and_preflight():
    _conn, session, _state, _jobs, _calls, _fallback = native_connection()
    status, headers, _body = request(session, "OPTIONS", "/v1/preview")
    assert status == HTTPStatus.NO_CONTENT
    assert b"Access-Control-Allow-Headers: Authorization, Content-Type" in headers
    session.revoke()
    status, _headers, _body = request(session, "GET", "/v1/preview", token=session.code)
    assert status == HTTPStatus.UNAUTHORIZED


@pytest.mark.parametrize(
    "payload",
    [
        b'{"records":[]}',
        b'{"preview_id":"broken"}',
        b'{"preview_id":"broken","preview_id":"repeat"}',
        b"[]",
        b"0",
        b"{",
    ],
)
def test_only_closed_preview_request_is_accepted(payload):
    conn, session, _state, _jobs, calls, _fallback = native_connection()
    status, _headers, _body = request(
        session, "POST", "/v1/submit", token=session.code, body=payload
    )
    assert status == HTTPStatus.BAD_REQUEST
    conn.tick()
    assert calls == []


def test_decline_does_not_submit_or_reschedule():
    conn, session, _state, _jobs, calls, fallback = native_connection(confirm=lambda _count: False)
    preview = session.preview()["preview_id"]
    session.request(preview)
    conn.tick()
    assert session.receipt()["state"] == "declined"
    conn.tick()
    session.request(preview)
    conn.tick()
    assert calls == fallback == []
    assert session.preview()["preview_id"] != preview


def test_edit_during_confirmation_cannot_submit_or_compile_fallback():
    def change_preview(_count):
        state.witness = (10, ())
        return True

    conn, session, state, _jobs, calls, fallback = native_connection(confirm=change_preview)
    session.request(session.preview()["preview_id"])
    conn.tick()
    assert session.receipt()["state"] == "preview_changed"
    assert calls == fallback == []


def test_native_witness_check_is_fail_closed_even_after_site_precheck():
    conn, _session, state, _jobs, calls, fallback = native_connection()
    reviewed = state.witness
    state.witness = (10, ())
    assert not conn.app.submit_frozen_site_preview(reviewed)
    assert calls == fallback == []


def test_uncommitted_submission_does_not_report_queued():
    conn, session, _state, _jobs, calls, _fallback = native_connection()
    conn.app.job_service.history_store.get_job = lambda _job_id: None
    session.request(session.preview()["preview_id"])
    conn.tick()
    conn.tick()
    assert len(calls) == 1
    assert session.receipt()["state"] == "check_native_queue"
    assert session.preview()["reason"] == "check_native_queue"


def test_site_admits_frozen_batch_to_native_sqlite_queue(tmp_path):
    conn, session, state, _jobs, _calls, fallback = native_connection()
    records = (make_test_njr(job_id="site-image-1"), make_test_njr(job_id="site-image-2"))
    state.witness = (10, records)
    conn.app.app_state.preview_jobs = list(records)
    repo = JobRepository(tmp_path / "jobs.sqlite3")
    try:
        queue = JobQueue(repository=repo)
        runner = Mock(job_queue=queue, is_running=lambda: True)
        service = JobService(queue, runner=runner)
        conn.app.job_service = service
        conn.app.pipeline_controller.submit_preview_jobs_to_queue = lambda records, **_kwargs: len(
            service.submit_njrs(records)
        )
        conn.tick()
        session.request(session.preview()["preview_id"])
        conn.tick()
        conn.tick()
        assert session.receipt()["state"] == "queued"
        assert tuple(session.receipt()["job_ids"]) == tuple(r.job_id for r in records)
        assert all(repo.get_job(r.job_id) is not None for r in records)
        assert not fallback
        runner.run_once.assert_not_called()
    finally:
        repo.close()
