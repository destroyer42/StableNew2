"""The phone web app and its API (S1, S6, S7). Bound to loopback; ``tailscale serve`` publishes it (D9).

There is deliberately no sync route here: the two listeners are two applications.
"""

from __future__ import annotations

import re
from collections import deque
from datetime import timedelta
from pathlib import Path

from starlette.applications import Starlette
from starlette.concurrency import run_in_threadpool
from starlette.datastructures import MutableHeaders
from starlette.middleware import Middleware
from starlette.requests import Request
from starlette.responses import FileResponse, JSONResponse, Response
from starlette.routing import Route
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from .errors import GatewayError
from .media import is_digest
from .store import Clock, Device, Store
from .web import EXCEPTION_HANDLERS, read_json, refusal

COOKIE = "rg_session"
COOKIE_AGE_S = 365 * 24 * 3600
REQUIRED_HEADER = "x-review-gateway"
FAILED_PAIRINGS = 20
FAILED_PAIRING_WINDOW = timedelta(minutes=10)

CONTENT_SECURITY_POLICY = (
    "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self'; media-src 'self'; "
    "connect-src 'self'; object-src 'none'; base-uri 'none'; form-action 'self'; "
    "frame-ancestors 'none'; require-trusted-types-for 'script'"
)
_SECURITY_HEADERS = {
    "Content-Security-Policy": CONTENT_SECURITY_POLICY,
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "no-referrer",
    "Cross-Origin-Opener-Policy": "same-origin",
    "Cross-Origin-Resource-Policy": "same-origin",
    "Permissions-Policy": "camera=(), microphone=(), geolocation=()",
}

_STATIC = Path(__file__).resolve().parent / "static"
_PAGES = {
    "/": ("index.html", "text/html"),
    "/static/app.js": ("app.js", "text/javascript"),
    "/static/app.css": ("app.css", "text/css"),
    "/static/icon.svg": ("icon.svg", "image/svg+xml"),
}
_VARIANTS = {
    "thumb": "thumb_320",
    "preview": "preview_1080",
    "video": "mobile_video",
    "original": "original",
}
_CACHE = {
    "original": "private, no-store",
    "thumb_320": "private, max-age=604800, immutable",
    "preview_1080": "private, max-age=604800, immutable",
}
_DECISION_FIELDS = {"library_id", "sha256", "verdict", "favorite", "tags", "idempotency_key"}
_ACTION_FIELDS = {"library_id", "sha256", "action", "params", "idempotency_key"}
_UPDATE_FIELDS = {"action", "expected_sha", "idempotency_key"}
_UUID = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}")


class _Guard:
    """Security headers on every response, and the custom header on every JSON API call."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] == "lifespan":
            await self.app(scope, receive, send)
            return
        if scope["type"] != "http":
            return

        async def guarded(message: Message) -> None:
            if message["type"] == "http.response.start":
                headers = MutableHeaders(scope=message)
                for name, value in _SECURITY_HEADERS.items():
                    headers[name] = value
                headers.setdefault("Cache-Control", "no-store")
            await send(message)

        names = {name for name, _value in scope["headers"]}
        if scope["path"].startswith("/api/") and REQUIRED_HEADER.encode() not in names:
            await refusal(403, "missing_header")(scope, receive, guarded)
            return
        await self.app(scope, receive, guarded)


def build_phone_app(store: Store, clock: Clock) -> Starlette:
    failures: deque = deque()

    async def session(request: Request, *, review: bool = True) -> Device:
        token = request.cookies.get(COOKIE, "")
        device = await run_in_threadpool(store.authenticate, token) if token else None
        if device is None:
            raise GatewayError(401, "not_enrolled")
        if review and "review" not in device.scopes:
            raise GatewayError(403, "not_granted")
        return device

    async def page(request: Request) -> Response:
        name, media_type = _PAGES[request.url.path]
        return FileResponse(
            _STATIC / name, media_type=media_type, headers={"Cache-Control": "no-cache"}
        )

    async def pair(request: Request) -> Response:
        now = clock()
        while failures and now - failures[0] > FAILED_PAIRING_WINDOW:
            failures.popleft()
        if len(failures) >= FAILED_PAIRINGS:
            raise GatewayError(429, "too_many_attempts")
        body = await read_json(request)
        code, label = body.get("code"), body.get("label", "")
        if not (isinstance(code, str) and 0 < len(code) <= 64):
            raise GatewayError(400, "invalid_request")
        if not (isinstance(label, str) and len(label) <= 64):
            raise GatewayError(400, "invalid_request")
        enrolled = await run_in_threadpool(store.redeem, code, label.strip() or None)
        if enrolled is None:
            failures.append(now)
            raise GatewayError(403, "invalid_code")
        device, token = enrolled
        response = JSONResponse({"device_id": device.device_id, "scopes": list(device.scopes)})
        response.set_cookie(
            COOKIE,
            token,
            max_age=COOKIE_AGE_S,
            path="/",
            secure=True,
            httponly=True,
            samesite="strict",
        )
        return response

    async def whoami(request: Request) -> Response:
        device = await session(request, review=False)
        return JSONResponse(
            {"device_id": device.device_id, "label": device.label, "scopes": list(device.scopes)}
        )

    async def runs(request: Request) -> Response:
        await session(request)
        return JSONResponse({"runs": await run_in_threadpool(store.runs)})

    async def run(request: Request) -> Response:
        await session(request)
        run_id = request.path_params["run_id"]
        return JSONResponse(
            {
                "run_id": run_id,
                "name": await run_in_threadpool(store.group_name, run_id),
                "items": await run_in_threadpool(store.run_items, run_id),
            }
        )

    async def status(request: Request) -> Response:
        await session(request)
        return JSONResponse(await run_in_threadpool(store.phone_status))

    async def decisions(request: Request) -> Response:
        device = await session(request)
        body = await read_json(request)
        if body.get("kind") == "action_request" or {"action", "action_request"} & body.keys():
            raise GatewayError(403, "not_granted")  # D6: actions arrive with RG-140
        if body.keys() - _DECISION_FIELDS or _DECISION_FIELDS - {"tags"} - body.keys():
            raise GatewayError(422, "invalid_record")
        record_id, state = await run_in_threadpool(
            store.decide,
            device.device_id,
            {"library_id": body["library_id"], "sha256": body["sha256"]},
            {
                "verdict": body["verdict"],
                "favorite": body["favorite"],
                "tags": body.get("tags", []),
            },
            body["idempotency_key"],
        )
        return JSONResponse({"record_id": record_id, "state": state})

    async def queue_session(request: Request) -> Device:
        device = await session(request)
        if "queue" not in device.scopes:
            raise GatewayError(403, "not_granted")  # D6, S4: queueing is its own grant
        return device

    async def actions(request: Request) -> Response:
        device = await queue_session(request)
        body = await read_json(request)
        if body.keys() != _ACTION_FIELDS:
            raise GatewayError(422, "invalid_record")
        record_id, state = await run_in_threadpool(
            store.request_action,
            device.device_id,
            {"library_id": body["library_id"], "sha256": body["sha256"]},
            {"action": body["action"], "params": body["params"]},
            body["idempotency_key"],
        )
        return JSONResponse({"record_id": record_id, "state": state})

    async def item_actions(request: Request) -> Response:
        device = await queue_session(request)
        library_id = request.query_params.get("library_id", "")
        sha256 = request.query_params.get("sha256", "")
        if not (0 < len(library_id) <= 64 and is_digest(sha256)):
            raise GatewayError(422, "invalid_request")
        target = {"library_id": library_id, "sha256": sha256}
        listed = await run_in_threadpool(store.item_actions, device.device_id, target)
        return JSONResponse({"actions": listed})

    async def action(request: Request) -> Response:
        device = await queue_session(request)
        record_id = request.path_params["record_id"]
        if not _UUID.fullmatch(record_id):
            raise GatewayError(404, "not_found")
        found = await run_in_threadpool(store.action_record, device.device_id, record_id)
        if found is None:
            raise GatewayError(404, "not_found")
        return JSONResponse(found)

    # LAUNCH-UPDATE-2: remote update, only for a phone paired from the desktop's dedicated offer (D2).
    async def admin_session(request: Request) -> Device:
        device = await session(request, review=False)
        if "admin" not in device.scopes:
            raise GatewayError(403, "not_granted")
        return device

    async def admin(request: Request) -> Response:
        device = await admin_session(request)
        return JSONResponse(await run_in_threadpool(store.admin_view, device.device_id))

    async def update_requests(request: Request) -> Response:
        device = await admin_session(request)
        body = await read_json(request)
        if body.keys() != _UPDATE_FIELDS:
            raise GatewayError(422, "invalid_record")
        record_id, state = await run_in_threadpool(
            store.request_update,
            device.device_id,
            {"action": body["action"], "expected_sha": body["expected_sha"]},
            body["idempotency_key"],
        )
        return JSONResponse({"record_id": record_id, "state": state})

    async def update_request(request: Request) -> Response:
        device = await admin_session(request)
        record_id = request.path_params["record_id"]
        if not _UUID.fullmatch(record_id):
            raise GatewayError(404, "not_found")
        found = await run_in_threadpool(store.admin_record, device.device_id, record_id)
        if found is None:
            raise GatewayError(404, "not_found")
        return JSONResponse(found)

    async def media(request: Request) -> Response:
        await session(request)
        params = request.path_params
        variant = _VARIANTS.get(params["variant"])
        if variant is None or not is_digest(params["sha256"]):
            raise GatewayError(404, "not_found")
        path, content_type = await run_in_threadpool(
            store.media_file, params["library_id"], params["sha256"], variant
        )
        # S6: originals are never cached; the small derivatives may stay on this phone for a while. A thumbnail or
        # rendition is of the bytes the URL names, so the phone need not ask for it again (PHONE-FAST).
        cache = _CACHE.get(variant, "private, max-age=3600")
        return FileResponse(path, media_type=content_type, headers={"Cache-Control": cache})

    return Starlette(
        routes=[
            *(Route(path, page, methods=["GET"]) for path in _PAGES),
            Route("/api/pair", pair, methods=["POST"]),
            Route("/api/session", whoami, methods=["GET"]),
            Route("/api/runs", runs, methods=["GET"]),
            Route("/api/runs/{run_id}", run, methods=["GET"]),
            Route("/api/status", status, methods=["GET"]),
            Route("/api/decisions", decisions, methods=["POST"]),
            Route("/api/actions", actions, methods=["POST"]),
            Route("/api/actions", item_actions, methods=["GET"]),
            Route("/api/actions/{record_id}", action, methods=["GET"]),
            Route("/api/admin", admin, methods=["GET"]),
            Route("/api/admin/updates", update_requests, methods=["POST"]),
            Route("/api/admin/updates/{record_id}", update_request, methods=["GET"]),
            Route("/media/{library_id}/{sha256}/{variant}", media, methods=["GET"]),
        ],
        middleware=[Middleware(_Guard)],
        exception_handlers=EXCEPTION_HANDLERS,
    )
