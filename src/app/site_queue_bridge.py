"""Loopback transport for the operator Site. Commands are Preview references, never jobs."""

from __future__ import annotations

import hmac
import json
import re
import secrets
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, replace
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, HTTPServer
from socket import socket
from threading import Event, Lock
from typing import Any

SITE_ORIGIN = "https://stablenew-b11960-review.stillbeacon3.chatgpt.site"
LOOPBACK = "127.0.0.1"
SITE_PORT = 49381
PAIR_SECONDS = 15 * 60
MAX_BODY = 160
_IDENTIFIER = re.compile(r"[a-f0-9]{32}")
_PREVIEW = "/v1/preview"
_SUBMIT = "/v1/submit"
_RECEIPT = "/v1/receipt"


@dataclass(frozen=True)
class PreviewJob:
    job_id: str
    stages: tuple[str, ...]


@dataclass(frozen=True)
class PreviewView:
    preview_id: str
    jobs: tuple[PreviewJob, ...]


@dataclass(frozen=True)
class SubmissionReceipt:
    receipt_id: str
    preview_id: str
    state: str
    job_ids: tuple[str, ...] = ()


class SiteSession:
    """A UI command mailbox with one request in flight and no job lifecycle ownership."""

    def __init__(self) -> None:
        self.code = secrets.token_urlsafe(32)
        self.expires_at = time.monotonic() + PAIR_SECONDS
        self._revoked = Event()
        self._lock = Lock()
        self._preview: PreviewView | None = None
        self._reason: str = "open_an_image_preview"
        self._receipt: SubmissionReceipt | None = None
        self._claimed = False

    @property
    def expired(self) -> bool:
        return self._revoked.is_set() or time.monotonic() >= self.expires_at

    def revoke(self) -> None:
        self._revoked.set()

    def authorizes(self, value: str) -> bool:
        return not self.expired and hmac.compare_digest(
            value.encode("utf-8"), f"Bearer {self.code}".encode()
        )

    def publish(self, view: PreviewView | None, reason: str = "") -> None:
        with self._lock:
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
                "jobs": [{"job_id": job.job_id, "stages": job.stages} for job in view.jobs],
            }

    def request(self, preview_id: str) -> tuple[HTTPStatus, dict[str, Any]]:
        with self._lock:
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


def make_handler(session: SiteSession, port: int) -> type[BaseHTTPRequestHandler]:
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, format: str, *args: Any) -> None:
            # Requests carry a bearer code. Keep the transport out of application logs.
            return

        def _same_site(self) -> bool:
            return self.headers.get_all("Origin") == [SITE_ORIGIN] and self.headers.get_all(
                "Host"
            ) == [f"{LOOPBACK}:{port}"]

        def _reply(self, status: HTTPStatus, body: dict[str, Any] | None = None) -> None:
            raw = json.dumps(body, separators=(",", ":")).encode() if body is not None else b""
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
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(raw)))
            self.end_headers()
            if raw:
                self.wfile.write(raw)

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
            allowed = {("GET", _PREVIEW), ("GET", _RECEIPT), ("POST", _SUBMIT)}
            if self._same_site() and (method, self.path) in allowed:
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
            else:
                self._reply(HTTPStatus.NOT_FOUND, {"error": "unknown_route"})

        def do_POST(self) -> None:
            if not self._authorized():
                return
            if self.path != _SUBMIT:
                self._reply(HTTPStatus.NOT_FOUND, {"error": "unknown_route"})
                return
            lengths = self.headers.get_all("Content-Length") or []
            length = (
                int(lengths[0])
                if len(lengths) == 1 and re.fullmatch(r"[0-9]{1,3}", lengths[0])
                else 0
            )
            if (
                self.headers.get_all("Content-Type") != ["application/json"]
                or self.headers.get("Transfer-Encoding") is not None
                or not 0 < length <= MAX_BODY
            ):
                self._reply(HTTPStatus.BAD_REQUEST, {"error": "invalid_body"})
                return
            try:
                preview_id = parse_submission(self.rfile.read(length))
            except (ValueError, TimeoutError, RecursionError):
                self._reply(HTTPStatus.BAD_REQUEST, {"error": "invalid_submission"})
                return
            status, data = session.request(preview_id)
            self._reply(status, data)

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
