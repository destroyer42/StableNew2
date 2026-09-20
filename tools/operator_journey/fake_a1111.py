"""Deterministic loopback A1111 stand-in for operator-journey development.

This is an HTTP seam only.  StableNew's real client, compiler, queue, runner and
executor still run against it; the server merely answers the WebUI endpoints the
production stack calls and records the txt2img payloads it received.
"""

from __future__ import annotations

import base64
import hashlib
import io
import json
import random
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

DEFAULT_MODEL = "operator-journey-model"
DEFAULT_LORAS = ("add-detail-xl",)


def _png_bytes(seed: int, prompt: str) -> bytes:
    from PIL import Image

    digest = hashlib.sha256(f"{seed}|{prompt}".encode()).digest()
    color = (digest[0], digest[1], digest[2])
    buffer = io.BytesIO()
    Image.new("RGB", (64, 64), color).save(buffer, format="PNG")
    return buffer.getvalue()


class FakeA1111:
    """Loopback WebUI double; use as a context manager."""

    def __init__(
        self,
        *,
        model: str = DEFAULT_MODEL,
        loras: tuple[str, ...] = DEFAULT_LORAS,
        drop_seed_readback: bool = False,
        startup_delay: float = 0.0,
    ) -> None:
        self.model = model
        self.loras = tuple(loras)
        self.drop_seed_readback = drop_seed_readback
        self.startup_delay = float(startup_delay)
        self._started_at = 0.0
        self.rejected_while_starting = 0
        self.txt2img_payloads: list[dict[str, Any]] = []
        self.unhandled: list[str] = []
        self.options: dict[str, Any] = {"sd_model_checkpoint": model, "sd_vae": "Automatic"}
        self._server: ThreadingHTTPServer | None = None
        self._thread: threading.Thread | None = None
        self._lock = threading.Lock()

    @property
    def base_url(self) -> str:
        assert self._server is not None, "FakeA1111 is not running"
        host, port = self._server.server_address[:2]
        return f"http://{host}:{port}"

    def __enter__(self) -> FakeA1111:
        self.start()
        return self

    def __exit__(self, *_: object) -> None:
        self.stop()

    def start(self) -> None:
        owner = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *_args: object) -> None:  # silence stderr noise
                return

            def _send(self, payload: Any, status: int = 200) -> None:
                body = json.dumps(payload).encode()
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def do_GET(self) -> None:  # noqa: N802
                if owner.starting_up():
                    self._send({"detail": "starting"}, 503)
                    return
                self._send(*owner._get(self.path.split("?")[0]))

            def do_POST(self) -> None:  # noqa: N802
                length = int(self.headers.get("Content-Length") or 0)
                raw = self.rfile.read(length) if length else b"{}"
                try:
                    body = json.loads(raw or b"{}")
                except json.JSONDecodeError:
                    body = {}
                if owner.starting_up():
                    self._send({"detail": "starting"}, 503)
                    return
                self._send(*owner._post(self.path.split("?")[0], body))

        self._server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self._thread = threading.Thread(
            target=self._server.serve_forever, name="fake-a1111", daemon=True
        )
        self._thread.start()

    def starting_up(self) -> bool:
        """True while emulating WebUI's slow start (endpoints answer 503).

        The clock starts at the first request, so the emulated warm-up is
        independent of how long StableNew itself takes to build its GUI.
        """

        if self._started_at == 0.0:
            self._started_at = time.monotonic()
        warming = time.monotonic() - self._started_at < self.startup_delay
        if warming:
            self.rejected_while_starting += 1
        return warming

    def stop(self) -> None:
        if self._server is not None:
            self._server.shutdown()
            self._server.server_close()
        if self._thread is not None:
            self._thread.join(timeout=5)
        self._server = None
        self._thread = None

    def _get(self, path: str) -> tuple[Any, int]:
        if path == "/sdapi/v1/sd-models":
            return [
                {
                    "title": f"{self.model}.safetensors [deadbeef]",
                    "model_name": self.model,
                    "hash": "deadbeef",
                    "filename": f"{self.model}.safetensors",
                }
            ], 200
        if path == "/sdapi/v1/samplers":
            return [{"name": "Euler a", "aliases": [], "options": {}}], 200
        if path == "/sdapi/v1/schedulers":
            return [{"name": "normal", "label": "Normal"}], 200
        if path in {"/sdapi/v1/sd-vae", "/sdapi/v1/upscalers", "/sdapi/v1/hypernetworks"}:
            return [], 200
        if path == "/sdapi/v1/scripts":
            return {"txt2img": [], "img2img": []}, 200
        if path == "/sdapi/v1/loras":
            return [
                {"name": name, "alias": name, "path": f"{name}.safetensors"} for name in self.loras
            ], 200
        if path == "/sdapi/v1/options":
            return dict(self.options), 200
        if path == "/sdapi/v1/progress":
            return {"progress": 0.0, "eta_relative": 0.0, "state": {}, "current_image": None}, 200
        if path in {"/internal/ping", "/config"}:
            return {"ok": True, "version": "operator-journey-fake"}, 200
        self.unhandled.append(f"GET {path}")
        return {"detail": "not found"}, 404

    def _post(self, path: str, body: dict[str, Any]) -> tuple[Any, int]:
        if path == "/sdapi/v1/options":
            self.options.update(body)
            return {}, 200
        if path in {"/sdapi/v1/interrupt", "/sdapi/v1/refresh-checkpoints"}:
            return {}, 200
        if path == "/sdapi/v1/txt2img":
            return self._txt2img(body), 200
        self.unhandled.append(f"POST {path}")
        return {"detail": "not found"}, 404

    def _txt2img(self, payload: dict[str, Any]) -> dict[str, Any]:
        with self._lock:
            self.txt2img_payloads.append(json.loads(json.dumps(payload)))
        count = max(1, int(payload.get("batch_size") or 1)) * max(
            1, int(payload.get("n_iter") or 1)
        )
        requested = int(payload.get("seed", -1))
        base = requested if requested >= 0 else random.randint(0, 2**31 - 1)
        seeds = [base + index for index in range(count)]
        prompt = str(payload.get("prompt") or "")
        info: dict[str, Any] = {
            "prompt": prompt,
            "negative_prompt": str(payload.get("negative_prompt") or ""),
            "seed": seeds[0],
            "subseed": int(payload.get("subseed", -1)),
            "all_seeds": seeds,
            "all_subseeds": [int(payload.get("subseed", -1))] * count,
            "width": payload.get("width"),
            "height": payload.get("height"),
            "steps": payload.get("steps"),
            "cfg_scale": payload.get("cfg_scale"),
            "infotexts": [prompt] * count,
        }
        if self.drop_seed_readback:
            for key in ("seed", "all_seeds", "all_subseeds"):
                info.pop(key, None)
        return {
            "images": [base64.b64encode(_png_bytes(seed, prompt)).decode() for seed in seeds],
            "parameters": {},
            "info": json.dumps(info),
        }
