"""Outbound HTTPS client for the review gateway's LAN sync port (RG-120).

The PC opens every connection (RG-100 invariant 1); nothing here binds or listens. The gateway's TLS certificate is
pinned by its SHA-256 fingerprint: the handshake completes, the fingerprint is compared, and only then is the sync
secret sent. No redirects are followed, every call has a bounded timeout and a bounded response size, and error
messages never contain the secret, a path or response text.
"""

from __future__ import annotations

import hashlib
import hmac
import http.client
import ssl
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any, BinaryIO, Protocol
from urllib.parse import urlencode

from src.app.review_gateway_protocol import (
    LIBRARY_ID,
    MAX_PAGE_BYTES,
    MAX_PAGE_RECORDS,
    SCHEMA_VERSION,
    SHA256,
    ProtocolError,
    encode_json,
    item_withdrawal,
    parse_json,
)
from src.app.review_gateway_store import GatewaySettings

#: The sync routes (RG-110's binding, adopted by RG-120 in the shared session notes); one table so an amendment is
#: one edit.
ROUTES = {
    "health": "/sync/v1/health",
    "media": "/sync/v1/media/{sha256}",
    "items": "/sync/v1/items",
    "outbox": "/sync/v1/outbox",
    "acknowledgements": "/sync/v1/acknowledgements",
    "pairing_offers": "/sync/v1/pairing-offers",
    "device_revocations": "/sync/v1/device-revocations",
    "immich_receipts": "/sync/v1/immich-receipts",
    "deploy_requests": "/sync/v1/deploy-requests",
    "deploy_status": "/sync/v1/deploy-status",
    "pc_status": "/sync/v1/pc-status",
    "withdrawals": "/sync/v1/withdrawals",
    "choice_catalog": "/sync/v1/choice-catalog",
}
#: The gateway's refusal codes for a deploy request (DEPLOY-2) that the operator tool explains.
DEPLOY_REFUSALS = frozenset({"remote_deploy_disabled", "deploy_pending"})
CONNECT_TIMEOUT = 5.0
IO_TIMEOUT = 15.0
UPLOAD_TIMEOUT = 120.0
_SMALL_RESPONSE = 64 * 1024


class GatewayError(Exception):
    """A sanitized gateway failure; ``str(error)`` is a stable code safe for the status line."""


class GatewayUnavailable(GatewayError):
    pass


class GatewayUnauthorized(GatewayError):
    pass


class GatewayPinMismatch(GatewayError):
    pass


class GatewayConflict(GatewayError):
    pass


class GatewayRejected(GatewayError):
    """The gateway refused a body (422): for example a file that changed between hashing and upload."""


ITEM_STATES = frozenset({"ready", "incomplete", "purged"})


@dataclass(frozen=True)
class Response:
    status: int
    data: bytes


class Transport(Protocol):
    def request(
        self,
        method: str,
        path: str,
        *,
        headers: Mapping[str, str],
        body: bytes | BinaryIO | None,
        timeout: float,
        limit: int,
    ) -> Response: ...


def check_pin(der: bytes | None, fingerprint: str) -> None:
    """Refuse a peer whose certificate is not the pinned one (constant-time comparison)."""

    actual = hashlib.sha256(der).hexdigest() if der else ""
    if not actual or not hmac.compare_digest(actual, fingerprint):
        raise GatewayPinMismatch("certificate_mismatch")


class PinnedHttpsTransport:
    """``http.client`` over TLS 1.2+ with the certificate pinned; headers are sent only after the pin matches."""

    def __init__(self, settings: GatewaySettings) -> None:
        self._host = settings.host
        self._port = settings.port
        self._fingerprint = settings.fingerprint
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
        context.minimum_version = ssl.TLSVersion.TLSv1_2
        # The pin replaces CA validation and the hostname check (a LAN gateway with an install-time certificate).
        context.check_hostname = False
        context.verify_mode = ssl.CERT_NONE
        self._context = context

    def request(
        self,
        method: str,
        path: str,
        *,
        headers: Mapping[str, str],
        body: bytes | BinaryIO | None,
        timeout: float,
        limit: int,
    ) -> Response:
        connection = http.client.HTTPSConnection(
            self._host, self._port, timeout=CONNECT_TIMEOUT, context=self._context
        )
        try:
            connection.connect()
            sock = connection.sock
            if not isinstance(sock, ssl.SSLSocket):
                raise GatewayPinMismatch("certificate_mismatch")
            check_pin(sock.getpeercert(binary_form=True), self._fingerprint)
            sock.settimeout(timeout)
            connection.request(method, path, body=body, headers=dict(headers))
            response = connection.getresponse()
            data = response.read(limit + 1) if method != "HEAD" else b""
            if len(data) > limit:
                raise GatewayError("response_too_large")
            return Response(response.status, data)
        except (OSError, http.client.HTTPException) as error:
            raise GatewayUnavailable("gateway_unreachable") from error
        finally:
            connection.close()


class GatewayClient:
    """The sync API calls. Every payload is built and parsed by ``review_gateway_protocol``."""

    def __init__(self, transport: Transport, secret: str) -> None:
        self._transport = transport
        self._secret = secret
        #: Optional contract parts the gateway accepts, read by ``health`` (empty until then).
        self.features: frozenset[str] = frozenset()

    def _call(
        self,
        method: str,
        path: str,
        *,
        body: bytes | BinaryIO | None = None,
        content_type: str = "",
        length: int | None = None,
        timeout: float = IO_TIMEOUT,
        limit: int = _SMALL_RESPONSE,
    ) -> Response:
        headers = {"Authorization": f"Bearer {self._secret}", "Accept": "application/json"}
        if body is not None:
            headers["Content-Type"] = content_type
            headers["Content-Length"] = str(
                len(body) if isinstance(body, bytes) else int(length or 0)
            )
        response = self._transport.request(
            method, path, headers=headers, body=body, timeout=timeout, limit=limit
        )
        if response.status in (401, 403):
            raise GatewayUnauthorized("gateway_refused_secret")
        return response

    @staticmethod
    def _require(response: Response, *accepted: int) -> Response:
        if response.status == 409:
            raise GatewayConflict("gateway_conflict")
        if response.status not in accepted:
            raise GatewayError(f"gateway_status_{response.status}")
        return response

    def _json(self, response: Response) -> Any:
        try:
            return parse_json(response.data, limit=MAX_PAGE_BYTES)
        except ProtocolError as error:
            raise GatewayError("invalid_gateway_response") from error

    def health(self) -> frozenset[str]:
        """Preflight each cycle: checks the secret and the contract version before any large upload.

        Returns (and keeps in ``features``) the optional contract parts the gateway lists, such as ``item_batch``;
        a gateway from before the list has none, so nothing optional is sent to it.
        """

        reply = self._json(self._require(self._call("GET", ROUTES["health"]), 200))
        if not isinstance(reply, dict) or reply.get("schema_version") != SCHEMA_VERSION:
            raise GatewayError("schema_mismatch")
        listed = reply.get("features", [])
        self.features = frozenset(
            name for name in (listed if isinstance(listed, list) else []) if isinstance(name, str)
        )
        return self.features

    # -- publish ---------------------------------------------------------------------------------------------------

    def post_manifest(self, manifest: Mapping[str, Any]) -> tuple[str, frozenset[str]]:
        """Declare an item; returns the gateway's state and the declared digests it still needs."""

        library_id = manifest["item"]["library_id"]
        if not isinstance(library_id, str) or not LIBRARY_ID.fullmatch(library_id):
            raise GatewayError("invalid_library_id")
        response = self._call(
            "POST",
            ROUTES["items"],
            body=encode_json(manifest),
            content_type="application/json",
        )
        if response.status == 422:
            raise GatewayRejected("gateway_rejected_manifest")
        reply = self._json(self._require(response, 200))
        declared = {variant["sha256"] for variant in manifest["media"].values()}
        if (
            not isinstance(reply, dict)
            or set(reply) - {"status", "missing"}
            or reply.get("status") not in ITEM_STATES
            or not isinstance(reply.get("missing", []), list)
        ):
            raise GatewayError("invalid_gateway_response")
        missing = reply.get("missing", [])
        if not all(isinstance(digest, str) and digest in declared for digest in missing):
            raise GatewayError("invalid_gateway_response")
        return str(reply["status"]), frozenset(missing)

    def upload_media(self, sha256: str, body: bytes | BinaryIO, size: int) -> None:
        if not SHA256.fullmatch(sha256):
            raise GatewayError("invalid_digest")
        response = self._call(
            "PUT",
            ROUTES["media"].format(sha256=sha256),
            body=body,
            content_type="application/octet-stream",
            length=size,
            timeout=UPLOAD_TIMEOUT,
        )
        if response.status == 422:
            raise GatewayRejected("gateway_rejected_media")
        self._require(response, 200, 201)

    def withdraw_items(self, library_ids: Sequence[str]) -> bool:
        """PHONE-FAST: stop showing these items; ``False`` when the gateway did not accept the request."""

        response = self._post("withdrawals", item_withdrawal(library_ids))
        if response.status in (404, 422):
            return False
        self._require(response, 200, 201)
        return True

    def send_choice_catalog(self, payload: Mapping[str, Any]) -> bool:
        """RG-160: what the phone may choose; ``False`` when the gateway did not accept it."""

        response = self._call(
            "PUT",
            ROUTES["choice_catalog"],
            body=encode_json(payload),
            content_type="application/json",
        )
        if response.status in (404, 413, 422):
            return False
        self._require(response, 200, 201)
        return True

    # -- pull ------------------------------------------------------------------------------------------------------

    def outbox(self, cursor: str | None, limit: int = 100) -> Any:
        query = {"limit": str(max(1, min(MAX_PAGE_RECORDS, limit)))}
        if cursor:
            query["cursor"] = cursor
        response = self._call("GET", f"{ROUTES['outbox']}?{urlencode(query)}", limit=MAX_PAGE_BYTES)
        return self._json(self._require(response, 200))

    def immich_receipts(self, cursor: str | None) -> Any | None:
        """RG-130 route; ``None`` while the gateway does not offer it yet."""

        path = ROUTES["immich_receipts"] + (f"?{urlencode({'cursor': cursor})}" if cursor else "")
        response = self._call("GET", path, limit=MAX_PAGE_BYTES)
        if response.status == 404:
            return None
        return self._json(self._require(response, 200))

    def _post(self, route: str, payload: Mapping[str, Any]) -> Response:
        return self._call(
            "POST", ROUTES[route], body=encode_json(payload), content_type="application/json"
        )

    def acknowledge(self, payload: Mapping[str, Any]) -> None:
        """Settled on 200; a 404 means the gateway withdrew the record, which is settled too."""

        response = self._post("acknowledgements", payload)
        if response.status != 404:
            self._require(response, 200, 201)

    def send_pairing_offer(self, payload: Mapping[str, Any]) -> bool:
        """``False`` when the gateway refused the offer (expired or conflicting): the code is dead."""

        response = self._post("pairing_offers", payload)
        if response.status in (409, 422):
            return False
        self._require(response, 200, 201)
        return True

    def send_revocation(self, payload: Mapping[str, Any]) -> None:
        self._require(self._post("device_revocations", payload), 200, 201)

    # -- deploy (DEPLOY-2, operator tool only; the sync worker never calls these) ----------------------------------

    def request_deploy(self, payload: Mapping[str, Any]) -> str:
        """``accepted``, or why not: a code in ``DEPLOY_REFUSALS``, ``not_supported`` or ``invalid_request``."""

        response = self._post("deploy_requests", payload)
        if response.status == 404:
            return "not_supported"
        if response.status == 422:
            return "invalid_request"
        if response.status == 409:
            reply = self._json(response)
            code = reply.get("error") if isinstance(reply, dict) else None
            return code if code in DEPLOY_REFUSALS else "conflict"
        reply = self._json(self._require(response, 202))
        if not isinstance(reply, dict) or reply.get("status") != "accepted":
            raise GatewayError("invalid_gateway_response")
        return "accepted"

    def deploy_status(self) -> dict[str, Any] | None:
        """The gateway's ``deploy_status``; ``None`` while the gateway does not offer remote deploy."""

        response = self._call("GET", ROUTES["deploy_status"])
        if response.status == 404:
            return None
        reply = self._json(self._require(response, 200))
        if not isinstance(reply, dict) or reply.get("type") != "deploy_status":
            raise GatewayError("invalid_gateway_response")
        return reply

    def send_pc_status(self, payload: Mapping[str, Any]) -> bool:
        """LAUNCH-UPDATE-2 route; ``False`` while the gateway does not offer it (an older release) or refuses this
        status (422, a contract mismatch): the status is optional and must never stop decisions from syncing."""

        response = self._call(
            "PUT", ROUTES["pc_status"], body=encode_json(payload), content_type="application/json"
        )
        if response.status in (404, 422):
            return False
        self._require(response, 200, 201)
        return True
