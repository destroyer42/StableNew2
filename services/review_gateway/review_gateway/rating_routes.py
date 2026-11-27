"""The rating routes of both listeners (RG-170). ``phone_app`` and ``sync_app`` only add these lists.

The phone routes need the same enrolled ``review`` session as the review routes (S1); the sync routes sit behind the
sync secret like every other sync route (S2).
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable

from starlette.concurrency import run_in_threadpool
from starlette.requests import ClientDisconnect, Request
from starlette.responses import FileResponse, JSONResponse, Response
from starlette.routing import Route

from .contract import ContractError
from .errors import GatewayError
from .media import is_digest
from .rating_store import RatingStore
from .store import Device
from .web import read_json

#: A task lists up to 60 items with their text, more than the shared 64 KiB bound allows.
TASK_LIMIT = 256 * 1024
_WRITE_BUFFER = 1024 * 1024
_ANSWER_FIELDS = {"item_id", "clip_id", "values", "notes"}

Session = Callable[[Request], Awaitable[Device]]


def phone_rating_routes(ratings: RatingStore, session: Session) -> list[Route]:
    async def tasks(request: Request) -> Response:
        await session(request)
        return JSONResponse(await run_in_threadpool(ratings.tasks))

    async def task(request: Request) -> Response:
        await session(request)
        return JSONResponse(await run_in_threadpool(ratings.task, request.path_params["task_id"]))

    async def answers(request: Request) -> Response:
        device = await session(request)
        body = await read_json(request)
        if body.keys() - _ANSWER_FIELDS or {"item_id", "clip_id", "values"} - body.keys():
            raise GatewayError(422, "invalid_answer")
        try:
            ratings.contract.validate("rating_answer", body)
        except ContractError as error:
            raise GatewayError(422, "invalid_answer") from error
        await run_in_threadpool(
            ratings.save_answer, device.device_id, request.path_params["task_id"], body
        )
        return JSONResponse({"state": "saved"})

    async def submit(request: Request) -> Response:
        device = await session(request)
        body = await read_json(request)
        key = body.get("idempotency_key")
        if body.keys() != {"idempotency_key"} or not isinstance(key, str):
            raise GatewayError(422, "invalid_record")
        submission_id, state = await run_in_threadpool(
            ratings.submit, device.device_id, request.path_params["task_id"], key
        )
        return JSONResponse({"submission_id": submission_id, "state": state})

    async def media(request: Request) -> Response:
        await session(request)
        digest = request.path_params["sha256"]
        if not is_digest(digest):
            raise GatewayError(404, "not_found")
        path, content_type = await run_in_threadpool(
            ratings.media_file, request.path_params["task_id"], digest
        )
        return FileResponse(
            path, media_type=content_type, headers={"Cache-Control": "private, max-age=3600"}
        )

    return [
        Route("/api/rating/tasks", tasks, methods=["GET"]),
        Route("/api/rating/tasks/{task_id}", task, methods=["GET"]),
        Route("/api/rating/tasks/{task_id}/answers", answers, methods=["POST"]),
        Route("/api/rating/tasks/{task_id}/submit", submit, methods=["POST"]),
        Route("/rating-media/{task_id}/{sha256}", media, methods=["GET"]),
    ]


def sync_rating_routes(ratings: RatingStore) -> list[Route]:
    async def payload(request: Request, name: str, **limits: int) -> dict:
        body = await read_json(request, **limits)
        ratings.contract.validate(name, body)
        return body

    async def tasks(request: Request) -> Response:
        manifest = await payload(request, "rating_task", limit=TASK_LIMIT)
        status, missing = await run_in_threadpool(ratings.publish, manifest)
        return JSONResponse({"status": status, "missing": missing})

    async def media(request: Request) -> Response:
        digest = request.path_params["digest"]
        if not is_digest(digest):
            raise GatewayError(404, "not_found")
        if request.method == "HEAD":
            return Response(status_code=200 if ratings.media.size(digest) is not None else 404)
        created = False
        stream = request.stream()
        try:
            writer = await run_in_threadpool(ratings.upload, digest)
            if writer is not None:
                try:
                    buffer = bytearray()
                    async for chunk in stream:
                        buffer += chunk
                        if len(buffer) >= _WRITE_BUFFER:
                            await run_in_threadpool(writer.write, bytes(buffer))
                            buffer.clear()
                    await run_in_threadpool(writer.write, bytes(buffer))
                    await run_in_threadpool(writer.commit)
                    created = True
                finally:
                    writer.discard()
            else:
                async for _chunk in stream:  # urllib reads a reply only after sending
                    pass
        except ClientDisconnect:
            return Response(status_code=400)
        return JSONResponse({"status": "stored"}, status_code=201 if created else 200)

    async def submissions(_request: Request) -> Response:
        return JSONResponse(await run_in_threadpool(ratings.pending_submissions))

    async def acknowledgements(request: Request) -> Response:
        body = await payload(request, "rating_acknowledgement", limit=TASK_LIMIT)
        return JSONResponse({"status": await run_in_threadpool(ratings.acknowledge, body)})

    return [
        Route("/sync/v1/rating-tasks", tasks, methods=["POST"]),
        Route("/sync/v1/rating-media/{digest}", media, methods=["PUT", "HEAD"]),
        Route("/sync/v1/rating-submissions", submissions, methods=["GET"]),
        Route("/sync/v1/rating-acknowledgements", acknowledgements, methods=["POST"]),
    ]
