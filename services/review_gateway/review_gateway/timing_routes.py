"""The image open-time routes of both listeners (PHONE-FAST gate). ``phone_app`` and ``sync_app`` add these lists.

The phone sends with the same enrolled ``review`` session as the review routes (S1); the PC reads behind the sync
secret like every other sync route (S2). Neither shape is part of the sync contract file: a batch is checked here, field
by field, and anything else in it refuses the whole batch.
"""

from __future__ import annotations

import re
from collections.abc import Awaitable, Callable
from typing import Any

from starlette.concurrency import run_in_threadpool
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.routing import Route

from .errors import GatewayError
from .store import Device
from .timing_store import TimingStore
from .web import read_json

#: Far above a full batch (about 5 KB).
BODY_LIMIT = 16 * 1024
MAXIMUM_SAMPLES = 100
MAXIMUM_MS = 10 * 60 * 1000
MAXIMUM_BYTES = 100 * 1024 * 1024
#: Where the image's bytes came from: asked for now, the browser's cache, fetched ahead, or not known.
SOURCES = ("network", "cache", "prefetch", "unknown")
_KEY = re.compile(r"[A-Za-z0-9_-]{16,128}")
_BATCH_FIELDS = {"idempotency_key", "samples"}
_SAMPLE_FIELDS = {"ms", "source", "bytes"}

Session = Callable[[Request], Awaitable[Device]]


def _whole(value: Any, maximum: int) -> bool:
    return type(value) is int and 0 <= value <= maximum  # ``True`` is not a number here


def _valid_sample(sample: Any) -> bool:
    return (
        isinstance(sample, dict)
        and sample.keys() == _SAMPLE_FIELDS
        and _whole(sample["ms"], MAXIMUM_MS)
        and sample["source"] in SOURCES
        and (sample["bytes"] is None or _whole(sample["bytes"], MAXIMUM_BYTES))
    )


def _valid_batch(body: dict[str, Any]) -> bool:
    if body.keys() != _BATCH_FIELDS:
        return False
    key, samples = body["idempotency_key"], body["samples"]
    return (
        isinstance(key, str)
        and _KEY.fullmatch(key) is not None
        and isinstance(samples, list)
        and 0 < len(samples) <= MAXIMUM_SAMPLES
        and all(_valid_sample(sample) for sample in samples)
    )


def phone_timing_routes(timings: TimingStore, session: Session) -> list[Route]:
    async def send(request: Request) -> Response:
        device = await session(request)
        body = await read_json(request, limit=BODY_LIMIT)
        if not _valid_batch(body):
            raise GatewayError(422, "invalid_record")
        state = await run_in_threadpool(
            timings.add, device.device_id, body["idempotency_key"], body["samples"]
        )
        return JSONResponse({"state": state})

    return [Route("/api/timings", send, methods=["POST"])]


def sync_timing_routes(timings: TimingStore) -> list[Route]:
    async def read(request: Request) -> Response:
        try:
            after = int(request.query_params.get("cursor", "0"))
        except ValueError:
            raise GatewayError(400, "invalid_cursor") from None
        if not 0 <= after < 2**62:
            raise GatewayError(400, "invalid_cursor")
        return JSONResponse(await run_in_threadpool(timings.page, after))

    return [Route("/sync/v1/open-timings", read, methods=["GET"])]
