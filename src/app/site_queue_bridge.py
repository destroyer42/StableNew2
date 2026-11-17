"""Loopback transport for the operator Site. Commands are Preview references, never jobs."""

from __future__ import annotations

import hmac
import json
import re
import secrets
import time
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, replace
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from socket import socket
from threading import Event, Lock
from typing import Any

from src.app.site_output_catalog import SiteOutputCatalog, SiteOutputError
from src.app.site_pack_catalog import PreparePack, SitePackCatalog
from src.pipeline.reprocess_builder import extract_reprocess_output_paths
from src.queue.job_history_store import JobHistoryEntry

SITE_ORIGIN = "https://stablenew-b11960-review.stillbeacon3.chatgpt.site"
LOOPBACK = "127.0.0.1"
SITE_PORT = 49381
PAIR_SECONDS = 15 * 60
MAX_BODY = 160
_IDENTIFIER = re.compile(r"[a-f0-9]{32}")
_PREVIEW = "/v1/preview"
_SUBMIT = "/v1/submit"
_RECEIPT = "/v1/receipt"
_OUTPUT_RUNS = "/v1/output/runs"
_OUTPUT_RUN = re.compile(r"/v1/output/runs/(\d{8}_\d{6}_[A-Za-z0-9_-]{1,150})")
_OUTPUT_MEDIA = re.compile(r"/v1/output/media/([a-f0-9]{32})")
_PACKS = "/v1/promptpacks"
_PACK = re.compile(r"/v1/promptpacks/([a-f0-9]{32})")
_PREPARE = "/v1/prepare"
_PREPARE_STATUS = "/v1/prepare-status"
_RESULT = re.compile(r"/v1/results/([a-f0-9]{32})")


@dataclass(frozen=True)
class PreviewJob:
    job_id: str
    stages: tuple[str, ...]
    settings: dict[str, object] | None = None


@dataclass(frozen=True)
class PreviewView:
    preview_id: str
    jobs: tuple[PreviewJob, ...]
    preparation_id: str | None = None


@dataclass(frozen=True)
class SubmissionReceipt:
    receipt_id: str
    preview_id: str
    state: str
    job_ids: tuple[str, ...] = ()


class SiteSession:
    """A UI command mailbox with one request in flight and no job lifecycle ownership."""

    def __init__(
        self,
        get_job: Callable[[str], JobHistoryEntry | None] | None = None,
        *,
        allow_promptpack_queue: bool = False,
    ) -> None:
        self.code = secrets.token_urlsafe(32)
        self.expires_at = time.monotonic() + PAIR_SECONDS
        self._revoked = Event()
        self._lock = Lock()
        self._preview: PreviewView | None = None
        self._reason: str = "open_an_image_preview"
        self._receipt: SubmissionReceipt | None = None
        self._claimed = False
        self._catalog: SiteOutputCatalog | None = None
        self._get_job = get_job
        self._admitted: set[str] = set()
        self._packs: SitePackCatalog | None = None
        self._prepare: PreparePack | None = None
        self._prepare_state = "idle"
        self.allow_promptpack_queue = allow_promptpack_queue

    @property
    def expired(self) -> bool:
        return self._revoked.is_set() or time.monotonic() >= self.expires_at

    def revoke(self) -> None:
        self._revoked.set()

    def authorizes(self, value: str) -> bool:
        return not self.expired and hmac.compare_digest(
            value.encode("utf-8"), f"Bearer {self.code}".encode()
        )

    def set_output_folder(self, folder: Path | None) -> None:
        catalog = SiteOutputCatalog(folder) if folder is not None else None
        with self._lock:
            self._catalog = catalog

    @property
    def output_catalog(self) -> SiteOutputCatalog | None:
        with self._lock:
            return self._catalog if not self.expired else None

    def share_packs(self, packs: SitePackCatalog) -> None:
        with self._lock:
            self._packs = packs

    @property
    def pack_catalog(self) -> SitePackCatalog | None:
        with self._lock:
            return self._packs if not self.expired else None

    def request_preparation(self, command: PreparePack) -> bool:
        with self._lock:
            if self.expired or self._prepare_state in {"requested", "preparing"}:
                return False
            if self._receipt and self._receipt.state in {"awaiting_confirmation", "submitting"}:
                return False
            self._prepare, self._prepare_state = command, "requested"
            self._preview, self._reason = None, "preparing_promptpack"
            return True

    def take_preparation(self) -> PreparePack | None:
        with self._lock:
            if self._prepare_state != "requested" or self.expired:
                return None
            self._prepare_state = "preparing"
            return self._prepare

    def finish_preparation(self, command: PreparePack, state: str) -> None:
        with self._lock:
            if self._prepare is command:
                self._prepare_state = state

    def preparation(self) -> dict[str, str]:
        with self._lock:
            return {
                "state": self._prepare_state,
                "request_id": self._prepare.request_id if self._prepare else "",
            }

    def result(self, job_id: str) -> dict[str, Any]:
        with self._lock:
            authorized = job_id in self._admitted and not self.expired
        if not authorized or self._get_job is None:
            raise SiteOutputError("unknown_job")
        job = self._get_job(job_id)
        if job is None:
            raise SiteOutputError("unknown_job")
        catalog = self.output_catalog
        assets = (
            catalog.results(extract_reprocess_output_paths(None, job.result))
            if catalog and job.status.value == "completed"
            else []
        )
        if self.expired or (catalog is not None and self.output_catalog is not catalog):
            raise SiteOutputError("output_folder_not_shared")
        return {"job_id": job_id, "status": job.status.value, "media": assets}

    def publish(self, view: PreviewView | None, reason: str = "") -> None:
        with self._lock:
            if self._prepare_state in {"requested", "preparing"}:
                return
            if (
                view
                and view.preparation_id
                and (
                    self._prepare_state != "draft_added"
                    or not self._prepare
                    or self._prepare.request_id != view.preparation_id
                )
            ):
                view, reason = None, "preview_changed"
            self._preview = view
            self._reason = reason

    def preview(self) -> dict[str, Any]:
        with self._lock:
            view = self._preview
            if view is None:
                return {"state": "unavailable", "reason": self._reason, "jobs": []}
            return {
                "state": "ready",
                "preview_id": view.preview_id,
                **(
                    {
                        "preparation_id": view.preparation_id,
                        "desktop_confirmation": not self.allow_promptpack_queue,
                    }
                    if view.preparation_id
                    else {}
                ),
                "jobs": [
                    {
                        "job_id": job.job_id,
                        "stages": job.stages,
                        **({"settings": job.settings} if job.settings is not None else {}),
                    }
                    for job in view.jobs
                ],
            }

    def request(self, preview_id: str) -> tuple[HTTPStatus, dict[str, Any]]:
        with self._lock:
            if self._prepare_state in {"requested", "preparing"}:
                return HTTPStatus.CONFLICT, {"error": "preparing_promptpack"}
            if self._receipt is not None:
                if preview_id == self._receipt.preview_id:
                    return HTTPStatus.ACCEPTED, receipt_payload(self._receipt)
                if self._receipt.state in {"awaiting_confirmation", "submitting"}:
                    return HTTPStatus.CONFLICT, {"error": "submission_in_progress"}
            if self._preview is None or self._preview.preview_id != preview_id:
                return HTTPStatus.CONFLICT, {"error": "preview_changed"}
            self._receipt = SubmissionReceipt(
                secrets.token_hex(16), preview_id, "awaiting_confirmation"
            )
            self._claimed = False
            return HTTPStatus.ACCEPTED, receipt_payload(self._receipt)

    def take_request(self) -> SubmissionReceipt | None:
        with self._lock:
            if (
                self._claimed
                or self._receipt is None
                or self._receipt.state != "awaiting_confirmation"
            ):
                return None
            self._claimed = True
            return self._receipt

    def finish(self, receipt: SubmissionReceipt, state: str, job_ids: tuple[str, ...] = ()) -> None:
        with self._lock:
            if self._receipt is not None and self._receipt.receipt_id == receipt.receipt_id:
                self._receipt = replace(self._receipt, state=state, job_ids=job_ids)
                if state == "queued":
                    if len(self._admitted) + len(job_ids) > 1000:
                        self._admitted.clear()
                    self._admitted.update(job_ids)

    def receipt(self) -> dict[str, Any]:
        with self._lock:
            return (
                receipt_payload(self._receipt) if self._receipt is not None else {"state": "idle"}
            )


def receipt_payload(receipt: SubmissionReceipt) -> dict[str, Any]:
    return {
        "receipt_id": receipt.receipt_id,
        "preview_id": receipt.preview_id,
        "state": receipt.state,
        "job_ids": receipt.job_ids,
    }


def parse_submission(raw: bytes) -> str:
    """Accept the single closed request shape, refusing duplicates and arbitrary NJRs."""

    def fields(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        if len(pairs) != 1 or pairs[0][0] != "preview_id":
            raise ValueError("invalid_submission")
        return dict(pairs)

    payload = json.loads(raw.decode("utf-8"), object_pairs_hook=fields)
    if not isinstance(payload, dict):
        raise ValueError("invalid_submission")
    preview_id = payload["preview_id"]
    if not isinstance(preview_id, str) or _IDENTIFIER.fullmatch(preview_id) is None:
        raise ValueError("invalid_submission")
    return preview_id


def parse_preparation(raw: bytes) -> tuple[str, str, tuple[int, ...], dict[str, Any]]:
    def fields(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        values = dict(pairs)
        if len(values) != len(pairs):
            raise ValueError("invalid_preparation")
        return values

    body = json.loads(raw, object_pairs_hook=fields)
    if (
        not isinstance(body, dict)
        or body.keys() - {"pack_id", "revision", "slots", "settings"}
        or not {"pack_id", "revision", "slots"} <= body.keys()
    ):
        raise ValueError("invalid_preparation")
    pack, revision, slots = body["pack_id"], body["revision"], body["slots"]
    if (
        not isinstance(pack, str)
        or not _IDENTIFIER.fullmatch(pack)
        or not isinstance(revision, str)
        or not re.fullmatch(r"[a-f0-9]{64}", revision)
        or not isinstance(slots, list)
        or not 1 <= len(slots) <= 16
        or not all(type(slot) is int and 0 <= slot < 500 for slot in slots)
        or len(set(slots)) != len(slots)
    ):
        raise ValueError("invalid_preparation")
    settings = body.get("settings", {})
    if not isinstance(settings, dict):
        raise ValueError("invalid_txt2img_settings")
    return pack, revision, tuple(sorted(slots)), settings


def make_handler(session: SiteSession, port: int) -> type[BaseHTTPRequestHandler]:
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, format: str, *args: Any) -> None:
            # Requests carry a bearer code. Keep the transport out of application logs.
            return

        def _same_site(self) -> bool:
            return self.headers.get_all("Origin") == [SITE_ORIGIN] and self.headers.get_all(
                "Host"
            ) == [f"{LOOPBACK}:{port}"]

        def _send(self, status: HTTPStatus, raw: bytes, content_type: str) -> None:
            self.send_response(status)
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Connection", "close")
            if self._same_site():
                self.send_header("Access-Control-Allow-Origin", SITE_ORIGIN)
                self.send_header("Vary", "Origin")
            if self.command == "OPTIONS" and status == HTTPStatus.NO_CONTENT:
                self.send_header("Access-Control-Allow-Methods", "GET, POST")
                self.send_header("Access-Control-Allow-Headers", "Authorization, Content-Type")
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(raw)))
            self.end_headers()
            if raw:
                self.wfile.write(raw)

        def _reply(self, status: HTTPStatus, body: dict[str, Any] | None = None) -> None:
            raw = json.dumps(body, separators=(",", ":")).encode() if body is not None else b""
            self._send(status, raw, "application/json")

        def _authorized(self) -> bool:
            if not self._same_site():
                self._reply(HTTPStatus.FORBIDDEN, {"error": "site_origin_refused"})
                return False
            headers = self.headers.get_all("Authorization") or []
            if len(headers) != 1 or not session.authorizes(headers[0]):
                self._reply(HTTPStatus.UNAUTHORIZED, {"error": "pairing_required"})
                return False
            return True

        def do_OPTIONS(self) -> None:
            method = self.headers.get("Access-Control-Request-Method")
            allowed = {
                ("GET", _PREVIEW),
                ("GET", _RECEIPT),
                ("POST", _SUBMIT),
                ("GET", _PACKS),
                ("GET", _PREPARE_STATUS),
                ("POST", _PREPARE),
            }
            output_read = method == "GET" and (
                self.path == _OUTPUT_RUNS
                or _OUTPUT_RUN.fullmatch(self.path)
                or _OUTPUT_MEDIA.fullmatch(self.path)
                or _PACK.fullmatch(self.path)
                or _RESULT.fullmatch(self.path)
            )
            if self._same_site() and ((method, self.path) in allowed or output_read):
                self._reply(HTTPStatus.NO_CONTENT)
            else:
                self._reply(HTTPStatus.FORBIDDEN, {"error": "site_origin_or_route_refused"})

        def do_GET(self) -> None:
            if not self._authorized():
                return
            if self.path == _PREVIEW:
                self._reply(HTTPStatus.OK, session.preview())
            elif self.path == _RECEIPT:
                self._reply(HTTPStatus.OK, session.receipt())
            elif self.path == _OUTPUT_RUNS or self.path.startswith(_OUTPUT_RUNS + "/"):
                self._output()
            elif _OUTPUT_MEDIA.fullmatch(self.path):
                self._output()
            elif self.path == _PREPARE_STATUS:
                self._reply(HTTPStatus.OK, session.preparation())
            elif self.path == _PACKS or _PACK.fullmatch(self.path):
                self._promptpacks()
            elif result := _RESULT.fullmatch(self.path):
                try:
                    self._reply(HTTPStatus.OK, session.result(result[1]))
                except (SiteOutputError, OSError):
                    self._reply(HTTPStatus.NOT_FOUND, {"error": "unknown_job"})
            else:
                self._reply(HTTPStatus.NOT_FOUND, {"error": "unknown_route"})

        def _promptpacks(self) -> None:
            packs = session.pack_catalog
            if packs is None:
                self._reply(HTTPStatus.FORBIDDEN, {"error": "promptpacks_not_shared"})
                return
            try:
                match = _PACK.fullmatch(self.path)
                data = packs.describe(match[1]) if match else {"packs": packs.list_packs()}
            except (ValueError, OSError):
                self._reply(HTTPStatus.CONFLICT, {"error": "promptpack_changed"})
                return
            if session.pack_catalog is not packs:
                self._reply(HTTPStatus.FORBIDDEN, {"error": "promptpacks_not_shared"})
            else:
                self._reply(HTTPStatus.OK, data)

        def _output(self) -> None:
            catalog = session.output_catalog
            if catalog is None:
                self._reply(HTTPStatus.FORBIDDEN, {"error": "output_folder_not_shared"})
                return
            try:
                run = _OUTPUT_RUN.fullmatch(self.path)
                media = _OUTPUT_MEDIA.fullmatch(self.path)
                if media:
                    mime, data = catalog.read_media(media[1])
                elif run:
                    result = catalog.get_run(run[1])
                elif self.path == _OUTPUT_RUNS:
                    result = {"runs": catalog.list_runs()}
                else:
                    raise SiteOutputError("unknown_route")
            except SiteOutputError as exc:
                self._reply(HTTPStatus.NOT_FOUND, {"error": str(exc)})
                return
            if session.output_catalog is not catalog:
                self._reply(HTTPStatus.FORBIDDEN, {"error": "output_folder_not_shared"})
            elif media:
                self._send(HTTPStatus.OK, data, mime)
            else:
                self._reply(HTTPStatus.OK, result)

        def do_POST(self) -> None:
            if not self._authorized():
                return
            if self.path not in {_SUBMIT, _PREPARE}:
                self._reply(HTTPStatus.NOT_FOUND, {"error": "unknown_route"})
                return
            lengths = self.headers.get_all("Content-Length") or []
            length = (
                int(lengths[0])
                if len(lengths) == 1 and re.fullmatch(r"[0-9]{1,4}", lengths[0])
                else 0
            )
            if (
                self.headers.get_all("Content-Type") != ["application/json"]
                or self.headers.get("Transfer-Encoding") is not None
                or not 0 < length <= (4096 if self.path == _PREPARE else MAX_BODY)
            ):
                self._reply(HTTPStatus.BAD_REQUEST, {"error": "invalid_body"})
                return
            try:
                raw = self.rfile.read(length)
                if self.path == _PREPARE:
                    self._prepare_promptpack(raw)
                    return
                preview_id = parse_submission(raw)
            except (ValueError, TimeoutError, RecursionError):
                self._reply(HTTPStatus.BAD_REQUEST, {"error": "invalid_submission"})
                return
            status, data = session.request(preview_id)
            self._reply(status, data)

        def _prepare_promptpack(self, raw: bytes) -> None:
            packs = session.pack_catalog
            if packs is None:
                self._reply(HTTPStatus.FORBIDDEN, {"error": "promptpacks_not_shared"})
                return
            try:
                command = packs.prepare(*parse_preparation(raw))
            except (ValueError, OSError, RecursionError) as exc:
                reason = (
                    str(exc)
                    if str(exc) in {"invalid_txt2img_settings", "invalid_preparation"}
                    else "promptpack_changed"
                )
                self._reply(HTTPStatus.CONFLICT, {"error": reason})
                return
            if session.pack_catalog is not packs or not session.request_preparation(command):
                self._reply(HTTPStatus.CONFLICT, {"error": "submission_in_progress"})
            else:
                self._reply(
                    HTTPStatus.ACCEPTED, {"request_id": command.request_id, "state": "requested"}
                )

    return Handler


class _LoopbackServer(HTTPServer):
    def get_request(self) -> tuple[socket, tuple[str, int]]:
        connection, address = super().get_request()
        connection.settimeout(1.0)
        return connection, address


class SiteListener:
    """One bounded listener owned by the explicitly opened operator dialog."""

    def __init__(self, session: SiteSession, *, port: int = SITE_PORT) -> None:
        self._session = session
        self._server = _LoopbackServer((LOOPBACK, port), make_handler(session, port))
        self._server.timeout = 0.25
        self._stop = Event()
        self._worker = ThreadPoolExecutor(max_workers=1, thread_name_prefix="StableNewSite")
        self._worker.submit(self._serve, session)

    def _serve(self, session: SiteSession) -> None:
        try:
            while not self._stop.is_set() and not session.expired:
                self._server.handle_request()
        finally:
            self._server.server_close()

    def close(self) -> None:
        self._session.revoke()
        self._stop.set()
        self._worker.shutdown(wait=False)
