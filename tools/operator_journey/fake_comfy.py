"""Deterministic loopback ComfyUI stand-in for the golden-path video journey.

An HTTP seam only: StableNew's real ``ComfyApiClient``, workflow compiler, backend, queue, runner and the production
frame encoder run against it.  It answers the endpoints the backend calls, derives its object info from the workflow
spec itself, and returns *synthetic frames* sized and counted from the submitted graph; StableNew then encodes the
frames into a real, decodable MP4.  Everything it produces is a simulated fixture value, never a measurement.
"""

from __future__ import annotations

import io
import json
import re
import threading
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any
from urllib.parse import parse_qs, urlparse

_LOADER_INPUT = {"UNETLoader": "unet_name", "CLIPLoader": "clip_name", "VAELoader": "vae_name"}


def object_info_for(spec: Any) -> dict[str, Any]:
    """Node registry + loader choices that satisfy exactly the dependencies the workflow spec pins."""

    info: dict[str, Any] = {}
    files: dict[str, list[str]] = {}
    for dependency in spec.dependency_specs:
        if dependency.dependency_kind == "stock_node":
            info.setdefault(dependency.locator, {"input": {"required": {}}})
        elif dependency.dependency_kind == "model_file":
            loader, _, input_name = str(dependency.version_hint or "").partition(".")
            files.setdefault(loader, []).append(dependency.locator)
            info.setdefault(loader, {"input": {"required": {}}})
            info[loader]["input"]["required"][input_name or _LOADER_INPUT.get(loader, "name")] = [
                files[loader]
            ]
    return info


def synthetic_frame(index: int, total: int, width: int, height: int) -> bytes:
    """A frame whose content depends on its index (a moving block), so the clip is not a still."""

    from PIL import Image, ImageDraw

    image = Image.new("RGB", (width, height), (24, 32, 64))
    draw = ImageDraw.Draw(image)
    size = max(8, min(width, height) // 6)
    x = int((width - size) * index / max(1, total - 1))
    draw.rectangle(
        [x, height // 2 - size // 2, x + size, height // 2 + size // 2], fill=(230, 200, 60)
    )
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


class FakeComfy:
    def __init__(self, spec: Any, *, total_vram_mib: float = 12282.0) -> None:
        self.spec = spec
        self.total_vram_mib = total_vram_mib
        self.object_info = object_info_for(spec)
        self.uploads: list[dict[str, Any]] = []
        self.prompts: list[dict[str, Any]] = []
        self.interrupts = 0
        self.unhandled: list[str] = []
        self._files: dict[str, bytes] = {}
        self._history: dict[str, Any] = {}
        self._server: ThreadingHTTPServer | None = None
        self._thread: threading.Thread | None = None
        self._lock = threading.Lock()

    @property
    def base_url(self) -> str:
        assert self._server is not None
        host, port = self._server.server_address[:2]
        return f"http://{host}:{port}"

    def __enter__(self) -> FakeComfy:
        self.start()
        return self

    def __exit__(self, *_: object) -> None:
        self.stop()

    def start(self) -> None:
        owner = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *_a: object) -> None:
                return

            def _send(
                self,
                payload: Any,
                status: int = 200,
                raw: bytes | None = None,
                ctype: str = "application/json",
            ) -> None:
                body = raw if raw is not None else json.dumps(payload).encode()
                self.send_response(status)
                self.send_header("Content-Type", ctype)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def do_GET(self) -> None:  # noqa: N802
                parsed = urlparse(self.path)
                owner._get(self, parsed.path, parse_qs(parsed.query))

            def do_POST(self) -> None:  # noqa: N802
                length = int(self.headers.get("Content-Length") or 0)
                raw = self.rfile.read(length) if length else b""
                owner._post(
                    self, urlparse(self.path).path, raw, self.headers.get("Content-Type", "")
                )

        self._server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self._thread = threading.Thread(
            target=self._server.serve_forever, name="fake-comfy", daemon=True
        )
        self._thread.start()

    def stop(self) -> None:
        if self._server is not None:
            self._server.shutdown()
            self._server.server_close()
        if self._thread is not None:
            self._thread.join(timeout=5)
        self._server = self._thread = None

    # -- endpoints -------------------------------------------------------------
    def _get(self, h: Any, path: str, query: dict[str, list[str]]) -> None:
        mib = 1024 * 1024
        if path == "/system_stats":
            h._send(
                {
                    "system": {
                        "comfyui_version": "fixture",
                        "python_version": "3.12.0 fixture",
                        "pytorch_version": "fixture",
                        "required_frontend_version": "fixture",
                    },
                    "devices": [
                        {
                            "name": "fixture-gpu",
                            "type": "cuda",
                            "index": 0,
                            "vram_total": self.total_vram_mib * mib,
                            "vram_free": self.total_vram_mib * mib * 0.9,
                            "torch_vram_total": 0,
                            "torch_vram_free": 0,
                        }
                    ],
                }
            )
        elif path == "/object_info":
            h._send(self.object_info)
        elif path == "/queue":
            h._send({"queue_running": [], "queue_pending": []})
        elif path.startswith("/history"):
            prompt_id = path.rsplit("/", 1)[-1] if path != "/history" else ""
            h._send({prompt_id: self._history[prompt_id]} if prompt_id in self._history else {})
        elif path == "/view":
            key = f"{(query.get('subfolder') or [''])[0]}/{(query.get('filename') or [''])[0]}"
            data = self._files.get(key)
            if data is None:
                h._send({"detail": "not found"}, 404)
            else:
                h._send(None, raw=data, ctype="image/png")
        else:
            self.unhandled.append(f"GET {path}")
            h._send({"detail": "not found"}, 404)

    def _post(self, h: Any, path: str, raw: bytes, ctype: str) -> None:
        if path == "/upload/image":
            match = re.search(rb'filename="([^"]+)"', raw)
            name = match.group(1).decode() if match else "upload.png"
            self.uploads.append({"name": name, "bytes": len(raw)})
            h._send({"name": name, "subfolder": "", "type": "input"})
        elif path == "/prompt":
            body = json.loads(raw or b"{}")
            with self._lock:
                self.prompts.append(json.loads(json.dumps(body)))
            prompt_id = uuid.uuid4().hex
            self._history[prompt_id] = self._run(body.get("prompt") or {}, prompt_id)
            h._send({"prompt_id": prompt_id, "number": len(self.prompts), "node_errors": {}})
        elif path == "/interrupt":
            self.interrupts += 1
            h._send({})
        elif path == "/queue":
            h._send({})
        else:
            self.unhandled.append(f"POST {path}")
            h._send({"detail": "not found"}, 404)

    def _run(self, graph: dict[str, Any], prompt_id: str) -> dict[str, Any]:
        """'Generate': read length/width/height from the graph and store that many synthetic PNG frames."""

        def graph_int(name: str, default: int) -> int:
            for node in graph.values():
                value = (node.get("inputs") or {}).get(name)
                if isinstance(value, int) and not isinstance(value, bool):
                    return value
            return default

        frames = max(1, graph_int("length", 9))
        width, height = (
            max(16, min(graph_int("width", 128), 1024)),
            max(16, min(graph_int("height", 128), 1024)),
        )
        outputs: dict[str, Any] = {}
        for node_id, node in graph.items():
            if node.get("class_type") != "SaveImage":
                continue
            prefix = str((node.get("inputs") or {}).get("filename_prefix") or "frame")
            subfolder, _, stem = prefix.rpartition("/")
            descriptors = []
            for index in range(frames):
                name = f"{stem}_{index + 1:05d}_.png"
                self._files[f"{subfolder}/{name}"] = synthetic_frame(index, frames, width, height)
                descriptors.append({"filename": name, "subfolder": subfolder, "type": "output"})
            outputs[node_id] = {"images": descriptors}
        return {
            "outputs": outputs,
            "status": {"status_str": "success", "completed": True, "messages": []},
        }
