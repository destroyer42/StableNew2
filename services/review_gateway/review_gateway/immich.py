"""The only outbound application connection: the few Immich API calls a kept item needs (D3, S5).

Standard library only. The API key travels in one header to the configured address: redirects are not followed,
and no error message, log line or ``repr`` carries the key or an Immich response body. Reply shapes follow
Immich v2 and v3.
"""

from __future__ import annotations

import http.client
import json
import os
import re
import secrets
import ssl
import stat
import uuid
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any
from urllib.parse import urlencode, urlsplit

#: Everything the uploader calls, and so everything the owner's API key needs.
PERMISSIONS = ("album.create", "album.read", "albumAsset.create", "asset.update", "asset.upload")
#: The oldest major version whose permission names these are.
MINIMUM_MAJOR = 2
DEVICE_ID = "stablenew-review-gateway"

_TIMEOUT_S = 30.0
_UPLOAD_TIMEOUT_S = 300.0
_RESPONSE_LIMIT = 32 * 1024 * 1024  # v2 lists every album
_CHUNK = 1024 * 1024
_KEY = re.compile(rb"[!-~]{16,256}")


class ImmichError(Exception):
    """One item could not be handled. ``code`` is safe to log and to put in a receipt.

    ``transient`` failures are retried quietly at first; the others are reported at once.
    """

    def __init__(self, code: str, *, transient: bool = False) -> None:
        super().__init__(code)
        self.code = code
        self.transient = transient


class ImmichUnavailable(ImmichError):
    """Immich cannot be reached: nothing about the item, so every upload waits."""

    def __init__(self, code: str = "immich_unreachable") -> None:
        super().__init__(code, transient=True)


class ImmichRefusedGateway(ImmichError):
    """Immich answered but will not serve this gateway (key, permission, address or version)."""


def read_key(path: Path) -> bytes | None:
    """The API key, or ``None`` while the file is missing or empty. Anything else odd is refused."""

    try:
        mode = path.stat().st_mode
        value = path.read_bytes().strip()
    except FileNotFoundError:
        return None
    if not value:
        return None
    # As for the sync secret: Windows has no group/other bits and the deployment target is Linux.
    if os.name == "posix" and stat.S_IMODE(mode) & 0o077:
        raise ValueError(f"{path} must be readable only by its owner (chmod 600)")
    if not _KEY.fullmatch(value):
        raise ValueError(f"{path} does not hold one API key on one line")
    return value


def check_url(url: str) -> str:
    """``url`` without a trailing ``/`` or ``/api``; refuses anything that is not a plain http(s) address."""

    parts = urlsplit(url)
    try:
        port_ok = parts.port is None or parts.port > 0
    except ValueError:
        port_ok = False
    if (
        parts.scheme not in ("http", "https")
        or not parts.hostname
        or "@" in parts.netloc
        or parts.query
        or parts.fragment
        or not port_ok
        or not url.isascii()
        or any(character.isspace() for character in url)
    ):
        raise ValueError("immich_url must be a plain http:// or https:// address")
    return url.rstrip("/").removesuffix("/api")


def _asset_id(value: object) -> str:
    """Immich ids are UUIDs; one that is not never reaches a request path or a receipt."""

    try:
        return str(uuid.UUID(str(value)))
    except ValueError:
        raise ImmichError("immich_bad_response") from None


class ImmichClient:
    def __init__(self, url: str, key: bytes, cancelled: Callable[[], bool] = lambda: False) -> None:
        parts = urlsplit(check_url(url))
        self._secure = parts.scheme == "https"
        self.host = parts.hostname or ""
        self.port = parts.port or (443 if self._secure else 80)
        self._base = parts.path + "/api"
        self._key = key.decode("ascii")
        self._cancelled = cancelled

    def __repr__(self) -> str:
        return f"ImmichClient({self.host!r})"

    # --- transport ------------------------------------------------------------------------------------------------

    def _send(
        self,
        method: str,
        path: str,
        body: bytes | Iterator[bytes] | None,
        headers: dict[str, str],
        timeout: float,
    ) -> tuple[int, bytes]:
        if self._secure:
            connection: http.client.HTTPConnection = http.client.HTTPSConnection(
                self.host, self.port, timeout=timeout, context=ssl.create_default_context()
            )
        else:
            connection = http.client.HTTPConnection(self.host, self.port, timeout=timeout)
        try:
            connection.request(
                method,
                self._base + path,
                body=body,
                headers={"x-api-key": self._key, "Accept": "application/json", **headers},
            )
            response = connection.getresponse()
            data = response.read(_RESPONSE_LIMIT + 1)
        finally:
            connection.close()
        if len(data) > _RESPONSE_LIMIT:
            raise ImmichError("immich_bad_response")
        return response.status, data

    def _answer(self, status: int, data: bytes) -> Any:
        if status == 401:
            raise ImmichRefusedGateway("immich_unauthorized")
        if status == 403:
            raise ImmichRefusedGateway("immich_forbidden")
        if 300 <= status < 400:
            raise ImmichRefusedGateway("immich_redirected")
        if status == 429 or status >= 500:
            raise ImmichError("immich_server_error", transient=True)
        if status >= 400:
            raise ImmichError(f"immich_rejected_{status}")
        if not data:
            return None
        try:
            return json.loads(data)
        except (ValueError, RecursionError):
            raise ImmichError("immich_bad_response") from None

    def _call(self, method: str, path: str, payload: object = None) -> Any:
        body = None if payload is None else json.dumps(payload).encode()
        headers = {} if body is None else {"Content-Type": "application/json"}
        try:
            status, data = self._send(method, path, body, headers, _TIMEOUT_S)
        except (OSError, http.client.HTTPException):
            raise ImmichUnavailable() from None
        return self._answer(status, data)

    # --- calls ----------------------------------------------------------------------------------------------------

    def version(self) -> tuple[int, int, int]:
        """Asked first for every item, so any failure here means "not now" rather than "not this item"."""

        try:
            reply = self._call("GET", "/server/version")
            return int(reply["major"]), int(reply["minor"]), int(reply["patch"])
        except ImmichRefusedGateway:
            raise
        except (ImmichError, KeyError, TypeError, ValueError):
            raise ImmichUnavailable() from None

    def key_permissions(self) -> list[str]:
        reply = self._call("GET", "/api-keys/me")
        try:
            return [str(name) for name in reply["permissions"]]
        except (KeyError, TypeError):
            raise ImmichError("immich_bad_response") from None

    def existing_asset(self, sha1: str) -> tuple[str, bool] | None:
        """``(asset id, is in the trash)`` when this user already has these bytes."""

        reply = self._call(
            "POST", "/assets/bulk-upload-check", {"assets": [{"id": "keeper", "checksum": sha1}]}
        )
        try:
            result = reply["results"][0]
            if result["action"] == "accept":
                return None
            if result.get("reason") != "duplicate":
                raise ImmichError("immich_unsupported_media")
            return _asset_id(result["assetId"]), bool(result.get("isTrashed"))
        except (KeyError, IndexError, TypeError):
            raise ImmichError("immich_bad_response") from None

    def upload(
        self,
        path: Path,
        *,
        filename: str,
        content_type: str,
        sha1: str,
        created_at: str,
        major: int,
    ) -> tuple[str, bool]:
        """Stream one file. Returns ``(asset id, whether this call created it)``."""

        fields = {"fileCreatedAt": created_at, "fileModifiedAt": created_at}
        if major < 3:  # required before v3, removed in it
            fields.update(deviceAssetId=f"{DEVICE_ID}-{sha1}", deviceId=DEVICE_ID)
        boundary = "stablenew-" + secrets.token_hex(16)
        head = "".join(
            f'--{boundary}\r\nContent-Disposition: form-data; name="{name}"\r\n\r\n{value}\r\n'
            for name, value in fields.items()
        )
        head += (
            f'--{boundary}\r\nContent-Disposition: form-data; name="assetData";'
            f' filename="{filename}"\r\nContent-Type: {content_type}\r\n\r\n'
        )
        start = head.encode("utf-8")
        end = f"\r\n--{boundary}--\r\n".encode("ascii")
        size = path.stat().st_size

        def body() -> Iterator[bytes]:
            yield start
            with path.open("rb") as stream:
                while chunk := stream.read(_CHUNK):
                    if self._cancelled():
                        raise ImmichUnavailable("stopping")
                    yield chunk
            yield end

        headers = {
            "Content-Type": f"multipart/form-data; boundary={boundary}",
            "Content-Length": str(len(start) + size + len(end)),
            "x-immich-checksum": sha1,
        }
        try:
            status, data = self._send("POST", "/assets", body(), headers, _UPLOAD_TIMEOUT_S)
        except (OSError, http.client.HTTPException):
            # Immich answered the checks a moment ago: count this against the item, not the server.
            raise ImmichError("immich_upload_interrupted", transient=True) from None
        reply = self._answer(status, data)
        try:
            return _asset_id(reply["id"]), reply["status"] == "created"
        except (KeyError, TypeError):
            raise ImmichError("immich_bad_response") from None

    def find_album(self, name: str) -> str | None:
        # v3 filters by name; v2 ignores the parameter and lists everything, so match here as well.
        reply = self._call("GET", "/albums?" + urlencode({"name": name}))
        try:
            return next((_asset_id(a["id"]) for a in reply if a["albumName"] == name), None)
        except (KeyError, TypeError):
            raise ImmichError("immich_bad_response") from None

    def create_album(self, name: str) -> str:
        reply = self._call("POST", "/albums", {"albumName": name})
        try:
            return _asset_id(reply["id"])
        except (KeyError, TypeError):
            raise ImmichError("immich_bad_response") from None

    def add_to_album(self, album_id: str, asset_id: str) -> None:
        """Adding what is already there succeeds."""

        reply = self._call("PUT", f"/albums/{album_id}/assets", {"ids": [asset_id]})
        try:
            result = reply[0]
            if result["success"] or result.get("error") == "duplicate":
                return
            error = result.get("error")
        except (KeyError, IndexError, TypeError):
            raise ImmichError("immich_bad_response") from None
        # "no_permission" here is about this asset; a key without the permission is refused with 403.
        if error == "not_found":
            raise ImmichError("immich_asset_missing", transient=True)
        raise ImmichError("immich_album_refused")

    def set_favorite(self, asset_id: str, favorite: bool) -> None:
        self._call("PUT", "/assets", {"ids": [asset_id], "isFavorite": favorite})
