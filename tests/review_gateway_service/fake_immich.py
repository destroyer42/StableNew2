"""A small in-process Immich: the six API calls the gateway makes, over real HTTP on loopback.

Shapes follow Immich v2.0.0 and v3.4.2 server sources (RG-130): ``x-api-key``, ``x-immich-checksum``,
``POST /assets/bulk-upload-check``, ``POST /assets``, ``/albums`` and ``PUT /assets`` for the favorite flag.
"""

from __future__ import annotations

import hashlib
import json
import threading
import uuid
from email.parser import BytesParser
from email.policy import HTTP
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any
from urllib.parse import urlsplit

API_KEY = "immich-test-key-N3verLogMe0123456789abcdef"
SCOPES = ["asset.upload", "asset.update", "album.read", "album.create", "albumAsset.create"]


class FakeImmich:
    def __init__(self) -> None:
        self.api_key = API_KEY
        self.permissions = list(SCOPES)
        self.major = 3
        self.assets: dict[str, dict[str, Any]] = {}
        self.albums: dict[str, dict[str, Any]] = {}
        self.requests: list[tuple[str, str]] = []
        self.uploads: list[dict[str, str]] = []
        self.down = False
        #: ``(method, path prefix) -> status`` answered instead of the real behavior.
        self.fail: dict[tuple[str, str], int] = {}
        self.redirect_to: str | None = None
        self.unshareable: set[str] = set()  # asset ids an album add answers no_permission for
        self.lose_favorite_reply = False  # apply the flag, then drop the connection
        fake = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *_args: Any) -> None:
                pass

            def do_GET(self) -> None:
                fake.handle(self, "GET")

            def do_POST(self) -> None:
                fake.handle(self, "POST")

            def do_PUT(self) -> None:
                fake.handle(self, "PUT")

        self._server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self._server.daemon_threads = True
        self._thread = threading.Thread(
            target=self._server.serve_forever, kwargs={"poll_interval": 0.02}, daemon=True
        )
        self._thread.start()
        self.url = f"http://127.0.0.1:{self._server.server_address[1]}"

    def close(self) -> None:
        self._server.shutdown()
        self._server.server_close()
        self._thread.join(timeout=5)

    def add_asset(self, data: bytes, *, trashed: bool = False, favorite: bool = False) -> str:
        asset_id = str(uuid.uuid4())
        self.assets[asset_id] = {
            "sha1": hashlib.sha1(data).hexdigest(),
            "data": data,
            "trashed": trashed,
            "favorite": favorite,
        }
        return asset_id

    def add_album(self, name: str) -> str:
        album_id = str(uuid.uuid4())
        self.albums[album_id] = {"name": name, "assets": []}
        return album_id

    def calls(self, method: str, path: str) -> int:
        return sum(1 for sent in self.requests if sent == (method, path))

    def _find(self, sha1: str) -> str | None:
        return next((key for key, asset in self.assets.items() if asset["sha1"] == sha1), None)

    # --- request handling -------------------------------------------------------------------------------------------

    def handle(self, request: BaseHTTPRequestHandler, method: str) -> None:
        path = urlsplit(request.path).path
        self.requests.append((method, path))
        body = request.rfile.read(int(request.headers.get("Content-Length", "0")))
        if self.down:
            request.close_connection = True
            return
        if self.redirect_to:
            request.send_response(307)
            request.send_header("Location", self.redirect_to + path)
            request.send_header("Content-Length", "0")
            request.end_headers()
            return
        for (failing_method, prefix), status in self.fail.items():
            if failing_method == method and path.startswith(prefix):
                # Echo the key, as a careless proxy might: the gateway must never log reply bodies.
                self._reply(
                    request, status, {"message": f"nope {request.headers.get('x-api-key')}"}
                )
                return
        if path == "/api/server/version":
            self._reply(request, 200, {"major": self.major, "minor": 4, "patch": 2})
            return
        if request.headers.get("x-api-key") != self.api_key:
            self._reply(request, 401, {"message": "Invalid API key"})
            return
        self._route(request, method, path, body)

    def _route(self, request: Any, method: str, path: str, body: bytes) -> None:
        if (method, path) == ("GET", "/api/api-keys/me"):
            self._reply(request, 200, {"name": "gateway", "permissions": self.permissions})
        elif (method, path) == ("POST", "/api/assets/bulk-upload-check"):
            results = []
            for entry in json.loads(body)["assets"]:
                found = self._find(entry["checksum"])
                if found is None:
                    results.append({"id": entry["id"], "action": "accept"})
                else:
                    results.append(
                        {
                            "id": entry["id"],
                            "action": "reject",
                            "reason": "duplicate",
                            "assetId": found,
                            "isTrashed": self.assets[found]["trashed"],
                        }
                    )
            self._reply(request, 200, {"results": results})
        elif (method, path) == ("POST", "/api/assets"):
            self._upload(request, body)
        elif (method, path) == ("PUT", "/api/assets"):
            sent = json.loads(body)
            for asset_id in sent["ids"]:
                self.assets[asset_id]["favorite"] = sent["isFavorite"]
            if self.lose_favorite_reply:
                request.close_connection = True
                return
            self._reply(request, 204, None)
        elif (method, path) == ("GET", "/api/albums"):
            self._reply(
                request,
                200,
                [{"id": key, "albumName": album["name"]} for key, album in self.albums.items()],
            )
        elif (method, path) == ("POST", "/api/albums"):
            album_id = self.add_album(json.loads(body)["albumName"])
            self._reply(request, 201, {"id": album_id, "albumName": self.albums[album_id]["name"]})
        elif method == "PUT" and path.startswith("/api/albums/") and path.endswith("/assets"):
            album = self.albums.get(path.split("/")[3])
            if album is None:
                self._reply(request, 400, {"message": "Album not found"})
                return
            results = []
            for asset_id in json.loads(body)["ids"]:
                if asset_id in self.unshareable:
                    results.append({"id": asset_id, "success": False, "error": "no_permission"})
                elif asset_id not in self.assets:
                    results.append({"id": asset_id, "success": False, "error": "not_found"})
                elif asset_id in album["assets"]:
                    results.append({"id": asset_id, "success": False, "error": "duplicate"})
                else:
                    album["assets"].append(asset_id)
                    results.append({"id": asset_id, "success": True})
            self._reply(request, 200, results)
        else:
            self._reply(request, 404, {"message": "Not found"})

    def _upload(self, request: Any, body: bytes) -> None:
        header = f"Content-Type: {request.headers['Content-Type']}\r\n\r\n".encode()
        message = BytesParser(policy=HTTP).parsebytes(header + body)
        fields: dict[str, str] = {}
        data = b""
        for part in message.iter_parts():
            name = part.get_param("name", header="content-disposition")
            if name == "assetData":
                data = part.get_payload(decode=True)
                fields["assetData.filename"] = part.get_filename()
                fields["assetData.type"] = part.get_content_type()
            else:
                fields[name] = part.get_payload(decode=True).decode("utf-8")
        sha1 = hashlib.sha1(data).hexdigest()
        fields["x-immich-checksum"] = request.headers.get("x-immich-checksum", "")
        self.uploads.append(fields)
        if "fileCreatedAt" not in fields or "fileModifiedAt" not in fields:
            self._reply(request, 400, {"message": "missing dates"})
            return
        if self.major == 2 and not (fields.get("deviceAssetId") and fields.get("deviceId")):
            self._reply(request, 400, {"message": "deviceAssetId should not be empty"})
            return
        existing = self._find(sha1)
        if existing is not None:
            self._reply(request, 200, {"id": existing, "status": "duplicate"})
            return
        self._reply(request, 201, {"id": self.add_asset(data), "status": "created"})

    @staticmethod
    def _reply(request: Any, status: int, payload: Any) -> None:
        data = b"" if payload is None else json.dumps(payload).encode()
        request.send_response(status)
        request.send_header("Content-Type", "application/json")
        request.send_header("Content-Length", str(len(data)))
        request.end_headers()
        request.wfile.write(data)
