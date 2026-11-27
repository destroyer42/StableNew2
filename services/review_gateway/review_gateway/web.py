"""HTTP pieces both listeners share: bounded JSON bodies and refusals that leak nothing."""

from __future__ import annotations

from typing import Any

from starlette.requests import Request
from starlette.responses import JSONResponse

from .contract import Contract, ContractError
from .errors import GatewayError

JSON_LIMIT = 64 * 1024


def refusal(status: int, code: str) -> JSONResponse:
    return JSONResponse({"error": code}, status_code=status)


async def read_json(request: Request, *, limit: int = JSON_LIMIT) -> dict[str, Any]:
    body = bytearray()
    async for chunk in request.stream():
        body += chunk
        if len(body) > limit:
            raise GatewayError(413, "too_large")
    return Contract.parse(bytes(body))


async def _on_gateway_error(_request: Request, error: GatewayError) -> JSONResponse:
    return refusal(error.status, error.code)


async def _on_contract_error(_request: Request, error: ContractError) -> JSONResponse:
    return refusal(400 if error.code == "invalid_json" else 422, error.code)


async def _on_disk_error(_request: Request, _error: OSError) -> JSONResponse:
    return refusal(507, "storage_unavailable")


EXCEPTION_HANDLERS: dict = {
    GatewayError: _on_gateway_error,
    ContractError: _on_contract_error,
    OSError: _on_disk_error,
}
