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
import socket
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

DEFAULT_MODEL = "operator-journey-model"
DEFAULT_LORAS = ("add-detail-xl",)


def _png_bytes(seed: int, prompt: str, width: int = 64, height: int = 64) -> bytes:
    from PIL import Image

    digest = hashlib.sha256(f"{seed}|{prompt}".encode()).digest()
    color = (digest[0], digest[1], digest[2])
    buffer = io.BytesIO()
    Image.new("RGB", (max(8, min(int(width), 2048)), max(8, min(int(height), 2048))), color).save(
        buffer, format="PNG"
    )
    return buffer.getvalue()


class FakeA1111:
    """Loopback WebUI double; use as a context manager."""

    def __init__(
        self,
        *,
        model: str = DEFAULT_MODEL,
        extra_models: tuple[str, ...] = (),
        active_model: str | None = None,
        loras: tuple[str, ...] = DEFAULT_LORAS,
        drop_seed_readback: bool = False,
        startup_delay: float = 0.0,
        forge: bool = False,
    ) -> None:
        # ``forge`` makes the loopback endpoint answer the runtime-identity probe like Forge (PR-IMG-FORGE-100): Forge-only
        # options and an /sd-modules list, and no /sd-vae.  It is still a fake: nothing here is a real Forge.
        self.forge = bool(forge)
        self.model = active_model or model  # the checkpoint WebUI has loaded
        self.model_names = tuple(dict.fromkeys((model, *extra_models, self.model)))
        self.checkpoint_switches = 0
        self.loras = tuple(loras)
        self.drop_seed_readback = drop_seed_readback
        self.startup_delay = float(startup_delay)
        self._started_at = 0.0
        self.rejected_while_starting = 0
        # Fault injection (PR-TEST-JOURNEYS-832): rules consumed by the HTTP handler, and a log of every request that
        # reached the loopback server so a journey can prove what was (and was not) dispatched.
        self.faults: list[dict[str, Any]] = []
        self.requests: list[tuple[str, str]] = []
        self._port = 0
        self.interrupts = 0
        self._interrupt = threading.Event()
        self.txt2img_payloads: list[dict[str, Any]] = []
        self.img2img_payloads: list[dict[str, Any]] = []
        self.unhandled: list[str] = []
        self.options: dict[str, Any] = {
            "sd_model_checkpoint": self.title(self.model),
            "sd_vae": "Automatic",
        }
        if self.forge:
            self.options.update(
                {"forge_preset": "sd", "forge_additional_modules": [], "forge_unet_storage_dtype": "Automatic"}
            )
        self._server: ThreadingHTTPServer | None = None
        self._thread: threading.Thread | None = None
        self._lock = threading.Lock()

    def inject(
        self, method: str, path: str, effect: str, *, times: int = 1, delay: float = 0.0
    ) -> None:
        """Make the next ``times`` requests for ``method path`` misbehave.

        ``effect`` is ``"drop"`` (the request is read, then the connection is closed without any response: the
        outcome is ambiguous to the caller), ``"status:NNN"`` (an HTTP error) or ``"delay"`` (answer normally after
        ``delay`` seconds, long enough for a journey to act while the request is in flight).
        """

        with self._lock:
            self.faults.append(
                {"method": method.upper(), "path": path, "effect": effect, "times": times, "delay": delay}
            )

    def clear_faults(self) -> None:
        with self._lock:
            self.faults.clear()

    def _take_fault(self, method: str, path: str) -> dict[str, Any] | None:
        with self._lock:
            self.requests.append((method, path))
            for rule in self.faults:
                if rule["method"] == method and rule["path"] == path and rule["times"] > 0:
                    rule["times"] -= 1
                    return dict(rule)
        return None

    def requests_to(self, method: str, path: str) -> int:
        with self._lock:
            return sum(1 for m, p in self.requests if (m, p) == (method.upper(), path))

    def remove_model(self, name: str) -> None:
        """The backend no longer offers ``name`` (a changed model identity after the operator chose it)."""

        self.model_names = tuple(n for n in self.model_names if n != name)

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

            def _apply_fault(self, method: str) -> bool:
                """True when the request was consumed by an injected fault (no normal answer follows)."""

                path = self.path.split("?")[0]
                fault = owner._take_fault(method, path)
                if fault is None:
                    return False
                effect = str(fault["effect"])
                if effect == "delay":
                    # Like WebUI, an in-flight generation ends early when the client posts /interrupt.
                    owner._interrupt.clear()
                    owner._interrupt.wait(float(fault["delay"]))
                    return False
                length = int(self.headers.get("Content-Length") or 0)
                if length:
                    self.rfile.read(length)
                if effect.startswith("status:"):
                    self._send({"detail": "injected fault"}, int(effect.split(":", 1)[1]))
                else:  # drop: close without answering
                    self.close_connection = True
                    try:
                        self.connection.shutdown(socket.SHUT_RDWR)
                    except OSError:
                        pass
                return True

            def do_GET(self) -> None:  # noqa: N802
                if self._apply_fault("GET"):
                    return
                if owner.starting_up():
                    self._send({"detail": "starting"}, 503)
                    return
                self._send(*owner._get(self.path.split("?")[0]))

            def do_POST(self) -> None:  # noqa: N802
                if self._apply_fault("POST"):
                    return
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

        self._server = ThreadingHTTPServer(("127.0.0.1", self._port), Handler)
        self._port = self._server.server_address[1]
        self._thread = threading.Thread(
            target=self._server.serve_forever, name="fake-a1111", daemon=True
        )
        self._thread.start()

    @staticmethod
    def _hash(name: str) -> str:
        return hashlib.sha1(name.encode()).hexdigest()[:8]

    def title(self, name: str) -> str:
        return f"{name}.safetensors [{self._hash(name)}]"

    def _apply_options(self, body: dict[str, Any]) -> None:
        """Like WebUI: a checkpoint request resolves to a known title and loads it."""

        body = dict(body)
        requested = body.pop("sd_model_checkpoint", None)
        self.options.update(body)
        if requested is None:
            return
        base = str(requested).split(" [")[0].removesuffix(".safetensors")
        if base in self.model_names and self.title(base) != self.options["sd_model_checkpoint"]:
            self.checkpoint_switches += 1
            self.options["sd_model_checkpoint"] = self.title(base)

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
                    "title": self.title(name),
                    "model_name": name,
                    "hash": self._hash(name),
                    "filename": f"{name}.safetensors",
                }
                for name in self.model_names
            ], 200
        if path == "/sdapi/v1/samplers":
            return [{"name": "Euler a", "aliases": [], "options": {}}], 200
        if path == "/sdapi/v1/schedulers":
            return [{"name": "normal", "label": "Normal"}], 200
        if path == "/sdapi/v1/sd-vae" and self.forge:
            return {"detail": "Not Found"}, 404
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
        # The runtime identity probe (PR-IMG-FORGE-100) asks like it would a real A1111: flags without any
        # forge_* key, and no /sd-modules (a Forge-only endpoint).
        if path == "/sdapi/v1/cmd-flags":
            return {"api": True, "port": 7860}, 200
        if path == "/sdapi/v1/sd-modules":
            return ([], 200) if self.forge else ({"detail": "Not Found"}, 404)
        if path == "/sdapi/v1/progress":
            return {"progress": 0.0, "eta_relative": 0.0, "state": {}, "current_image": None}, 200
        if path in {"/internal/ping", "/config"}:
            return {"ok": True, "version": "operator-journey-fake"}, 200
        self.unhandled.append(f"GET {path}")
        return {"detail": "not found"}, 404

    def _post(self, path: str, body: dict[str, Any]) -> tuple[Any, int]:
        if path == "/sdapi/v1/options":
            self._apply_options(body)
            return {}, 200
        if path == "/sdapi/v1/interrupt":
            self.interrupts += 1
            self._interrupt.set()
            return {}, 200
        if path == "/sdapi/v1/refresh-checkpoints":
            return {}, 200
        if path == "/sdapi/v1/txt2img":
            return self._txt2img(body), 200
        if path == "/sdapi/v1/img2img":
            return self._img2img(body), 200
        self.unhandled.append(f"POST {path}")
        return {"detail": "not found"}, 404

    def _img2img(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Record the edit request and answer with a synthetic image the size of the first init image."""

        from PIL import Image

        with self._lock:
            self.img2img_payloads.append(json.loads(json.dumps(payload)))
        width, height = int(payload.get("width") or 0), int(payload.get("height") or 0)
        inits = payload.get("init_images") or []
        if inits and not (width and height):
            with Image.open(io.BytesIO(base64.b64decode(inits[0]))) as init:
                width, height = init.size
        seed = int(payload.get("seed", -1))
        seed = seed if seed >= 0 else random.randint(0, 2**31 - 1)
        prompt = str(payload.get("prompt") or "")
        info = {
            "prompt": prompt,
            "negative_prompt": str(payload.get("negative_prompt") or ""),
            "seed": seed,
            "all_seeds": [seed],
            "width": width or 64,
            "height": height or 64,
            "denoising_strength": payload.get("denoising_strength"),
            "infotexts": [prompt],
        }
        return {
            "images": [base64.b64encode(_png_bytes(seed, prompt, width or 64, height or 64)).decode()],
            "parameters": {},
            "info": json.dumps(info),
        }

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
            "images": [
                base64.b64encode(
                    _png_bytes(
                        seed, prompt, payload.get("width") or 64, payload.get("height") or 64
                    )
                ).decode()
                for seed in seeds
            ],
            "parameters": {},
            "info": json.dumps(info),
        }
