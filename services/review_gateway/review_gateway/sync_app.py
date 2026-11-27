"""The PC-facing sync API (LAN only, S2). Every request carries the per-installation sync secret."""

from __future__ import annotations

import hmac
import logging
from collections.abc import AsyncIterator

from starlette.applications import Starlette
from starlette.concurrency import run_in_threadpool
from starlette.middleware import Middleware
from starlette.requests import ClientDisconnect, Request
from starlette.responses import JSONResponse, Response
from starlette.routing import Route
from starlette.types import ASGIApp, Receive, Scope, Send

from .contract import SCHEMA_VERSION, Contract, ContractError
from .deploy_inbox import DeployInbox
from .errors import GatewayError
from .media import is_digest
from .rating_routes import sync_rating_routes
from .rating_store import RatingStore
from .store import Store
from .web import EXCEPTION_HANDLERS, read_json, refusal

PAGE_DEFAULT = 200
PAGE_LIMIT = 500
#: Optional parts of the v1 contract this gateway accepts, listed by health so a PC sends them only here (an older
#: gateway's schema would refuse the whole payload). ``item_batch``: the manifest's ``batch`` (N5 inbox grouping).
#: ``item_parent``: the manifest's ``parent`` (PHONE-FAST rework lineage). ``item_withdraw``: the withdrawals route.
#: ``item_source``: the manifest's ``source`` and the item-sources route (PHONE-FAST review sections).
#: ``item_input``: the manifest's ``input`` and ``input_missing`` (the image a desk job started from).
#: ``rating_tasks``: the RG-170 rating routes. ``item_info``: the manifest's ``info`` (NAME-INFO "More info").
#: ``item_file_name``: ``info.file_name``, the descriptive name Immich uploads under.
FEATURES = (
    "item_batch",
    "item_parent",
    "item_withdraw",
    "item_source",
    "item_input",
    "rating_tasks",
    "item_info",
    "item_file_name",
)
_WRITE_BUFFER = 1024 * 1024
_LOG = logging.getLogger("review_gateway")


class _SyncSecret:
    """Refuse everything, including unknown paths, without ``Authorization: Bearer <secret>``."""

    def __init__(self, app: ASGIApp, secret: bytes) -> None:
        self.app = app
        self.expected = b"Bearer " + secret

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] == "lifespan":
            await self.app(scope, receive, send)
            return
        if scope["type"] != "http":
            return
        sent = dict(scope["headers"]).get(b"authorization", b"")
        if not hmac.compare_digest(sent, self.expected):
            await refusal(401, "unauthorized")(scope, receive, send)
            return
        await self.app(scope, receive, send)


async def _drain(stream: AsyncIterator[bytes]) -> None:
    """Read what is left of an authenticated upload: urllib and others only read a reply after sending."""

    async for _chunk in stream:
        pass


def build_sync_app(
    store: Store,
    contract: Contract,
    secret: bytes,
    deploys: DeployInbox | None,
    ratings: RatingStore,
) -> Starlette:
    async def payload(request: Request, name: str) -> dict:
        body = await read_json(request)
        try:
            contract.validate(name, body)
        except ContractError as error:
            _LOG.warning("refused sync payload: %s", error)  # field path only, never values
            raise
        return body

    async def health(_request: Request) -> Response:
        return JSONResponse(
            {"status": "ok", "schema_version": SCHEMA_VERSION, "features": list(FEATURES)}
        )

    async def items(request: Request) -> Response:
        manifest = await payload(request, "item_manifest")
        status, missing = await run_in_threadpool(store.publish, manifest)
        return JSONResponse({"status": status, "missing": missing})

    async def receive_media(digest: str, stream: AsyncIterator[bytes]) -> bool:
        """Stream one declared upload to disk. Returns False when it was already stored."""

        writer = await run_in_threadpool(store.upload, digest)
        if writer is None:
            # A stop between storing a file and marking its items ready is repaired by sending it again.
            await run_in_threadpool(store.stored, digest)
            return False
        try:
            buffer = bytearray()
            async for chunk in stream:
                buffer += chunk
                if len(buffer) >= _WRITE_BUFFER:
                    await run_in_threadpool(writer.write, bytes(buffer))
                    buffer.clear()
            await run_in_threadpool(writer.write, bytes(buffer))
            await run_in_threadpool(writer.commit)
        finally:
            writer.discard()
        await run_in_threadpool(store.stored, digest)
        return True

    async def media(request: Request) -> Response:
        digest = request.path_params["digest"]
        if not is_digest(digest):
            raise GatewayError(404, "not_found")
        if request.method == "HEAD":
            return Response(status_code=200 if store.media.size(digest) is not None else 404)
        stream = request.stream()
        try:
            try:
                created = await receive_media(digest, stream)
            except GatewayError:
                await _drain(stream)
                raise
            await _drain(stream)
        except ClientDisconnect:
            return Response(status_code=400)
        return JSONResponse({"status": "stored"}, status_code=201 if created else 200)

    async def outbox(request: Request) -> Response:
        try:
            after = int(request.query_params.get("cursor", "0"))
            limit = int(request.query_params.get("limit", str(PAGE_DEFAULT)))
        except ValueError:
            raise GatewayError(400, "invalid_cursor") from None
        if not (0 <= after < 2**62 and 1 <= limit <= PAGE_LIMIT):
            raise GatewayError(400, "invalid_cursor")
        return JSONResponse(await run_in_threadpool(store.outbox_page, after, limit))

    async def acknowledgements(request: Request) -> Response:
        body = await payload(request, "acknowledgement")
        return JSONResponse({"status": await run_in_threadpool(store.acknowledge, body)})

    async def pairing_offers(request: Request) -> Response:
        await run_in_threadpool(store.add_offer, await payload(request, "pairing_offer"))
        return JSONResponse({"status": "accepted"})

    async def device_revocations(request: Request) -> Response:
        body = await payload(request, "device_revocation")
        known = await run_in_threadpool(store.revoke_device, body["device_id"])
        return JSONResponse({"status": "revoked" if known else "unknown_device"})

    async def pc_status(request: Request) -> Response:
        await run_in_threadpool(store.set_pc_status, await payload(request, "pc_status"))
        return JSONResponse({"status": "stored"})

    async def withdrawals(request: Request) -> Response:
        body = await payload(request, "item_withdrawal")
        count = await run_in_threadpool(store.withdraw, body["library_ids"])
        return JSONResponse({"withdrawn": count})

    async def item_sources(request: Request) -> Response:
        body = await payload(request, "item_sources")
        pairs = [(entry["library_id"], entry["source"]) for entry in body["items"]]
        return JSONResponse({"labelled": await run_in_threadpool(store.label_sources, pairs)})

    async def immich_receipts(request: Request) -> Response:
        cursor = request.query_params.get("cursor", "")
        return JSONResponse(await run_in_threadpool(store.immich_receipts, cursor))

    def deploy_inbox() -> DeployInbox:
        if deploys is None:
            raise GatewayError(404, "not_found")
        return deploys

    async def deploy_requests(request: Request) -> Response:
        inbox = deploy_inbox()
        body = await payload(request, "deploy_request")
        status = await run_in_threadpool(inbox.submit, body)
        _LOG.info(
            "deploy request accepted"
        )  # never the commit or request id: the deployer's history has them
        return JSONResponse({"status": status, "request_id": body["request_id"]}, status_code=202)

    async def deploy_status(_request: Request) -> Response:
        return JSONResponse(await run_in_threadpool(deploy_inbox().status))

    return Starlette(
        routes=[
            Route("/sync/v1/health", health, methods=["GET"]),
            Route("/sync/v1/items", items, methods=["POST"]),
            Route("/sync/v1/media/{digest}", media, methods=["PUT", "HEAD"]),
            Route("/sync/v1/outbox", outbox, methods=["GET"]),
            Route("/sync/v1/acknowledgements", acknowledgements, methods=["POST"]),
            Route("/sync/v1/pairing-offers", pairing_offers, methods=["POST"]),
            Route("/sync/v1/device-revocations", device_revocations, methods=["POST"]),
            Route("/sync/v1/immich-receipts", immich_receipts, methods=["GET"]),
            Route("/sync/v1/deploy-requests", deploy_requests, methods=["POST"]),
            Route("/sync/v1/deploy-status", deploy_status, methods=["GET"]),
            Route("/sync/v1/pc-status", pc_status, methods=["PUT"]),
            *sync_rating_routes(ratings),
            Route("/sync/v1/withdrawals", withdrawals, methods=["POST"]),
            Route("/sync/v1/item-sources", item_sources, methods=["POST"]),
        ],
        middleware=[Middleware(_SyncSecret, secret=secret)],
        exception_handlers=EXCEPTION_HANDLERS,
    )
