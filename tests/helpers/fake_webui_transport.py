"""Deterministic WebUI-family HTTP fake for PR-IMG-FORGE-100 tests.

Replaces ``requests.Session.request`` for a client so no WebUI, GPU, model or network is involved.
It models only the contract differences the Forge qualification cares about:

* ``flavor="forge"``: ``/cmd-flags`` carries ``forge_ref_a1111_home``; the VAE/text-encoder listing
  is ``/sd-modules``; there is no ``/sd-vae``; the effective VAE is the stateful
  ``forge_additional_modules`` option, which (like Forge) silently drops unknown module names.
* ``flavor="a1111"``: no ``forge_*`` flags; ``/sd-vae`` answers; ``/sd-modules`` is a 404;
  ``sd_vae`` is an ordinary writable option.

Every request is recorded as ``(METHOD, path, json_body)`` so tests can assert exactly which
endpoints were (and were not) called, and in particular that no generation POST preceded a
rejection.
"""

from __future__ import annotations

import json
import threading
from collections import defaultdict
from collections.abc import Callable
from typing import Any

import requests

TINY_PNG_B64 = "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg=="
GENERATION_PATHS = ("/sdapi/v1/txt2img", "/sdapi/v1/img2img", "/sdapi/v1/extra-single-image")


class FakeResponse:
    def __init__(self, payload: Any, status_code: int = 200) -> None:
        self._payload = payload
        self.status_code = status_code
        self.ok = status_code < 400
        self.reason = "OK" if self.ok else "ERROR"
        self.text = json.dumps(payload) if payload is not None else ""
        self.content = self.text.encode("utf-8")
        self.headers = {"content-type": "application/json"}

    def json(self) -> Any:
        return self._payload

    def raise_for_status(self) -> None:
        if not self.ok:
            raise requests.HTTPError(f"{self.status_code} error", response=self)  # type: ignore[arg-type]

    def close(self) -> None:
        return None

    def __enter__(self) -> FakeResponse:
        return self

    def __exit__(self, *_exc: object) -> None:
        self.close()


class FakeWebUITransport:
    """Callable stand-in for ``session.request`` with Forge or A1111 endpoint semantics."""

    def __init__(
        self,
        *,
        flavor: str = "forge",
        checkpoint: str = "sdxl.safetensors",
        modules: list[dict[str, str]] | None = None,
        seed: int = 12345,
        generation_error: Exception | None = None,
        block_generation_until_interrupt: bool = False,
        reject_generation_when: Callable[[dict[str, Any]], str | None] | None = None,
        ignore_module_writes: bool = False,
        loras: list[dict[str, str]] | None = None,
    ) -> None:
        if flavor not in {"forge", "a1111"}:
            raise ValueError(flavor)
        self.flavor = flavor
        self.modules = (
            list(modules)
            if modules is not None
            else [
                {
                    "model_name": "sdxl_vae.safetensors",
                    "filename": "/models/VAE/sdxl_vae.safetensors",
                }
            ]
        )
        self.seed = seed
        self.generation_error = generation_error
        # When set, a generation POST blocks until POST /sdapi/v1/interrupt arrives (deterministic
        # stand-in for a long generation that only operator cancellation can end).
        self.block_generation_until_interrupt = block_generation_until_interrupt
        # Forge loads the model lazily on a generation POST; this models the real failure of a
        # checkpoint meeting an incompatible persisted module set (HTTP 500, a *definite* error).
        self.reject_generation_when = reject_generation_when
        self.ignore_module_writes = ignore_module_writes  # a write that silently does not stick
        self.loras = list(loras) if loras is not None else []  # GET /sdapi/v1/loras entries (name/alias/path)
        self.generation_module_state: list[list[str]] = []
        self.rejected_generations: list[str] = []
        self.generation_started = threading.Event()
        self.interrupted = threading.Event()
        self.options: dict[str, Any] = {"sd_model_checkpoint": checkpoint, "sd_vae": "Automatic"}
        if flavor == "forge":
            self.options["forge_additional_modules"] = []
        self.calls: list[tuple[str, str, Any]] = []
        self.payloads: dict[str, list[dict[str, Any]]] = defaultdict(list)

    # -- helpers -----------------------------------------------------------------------------
    @staticmethod
    def _split(args: tuple, kwargs: dict) -> tuple[str, str]:
        method = str(args[0] if args else kwargs.get("method", "")).upper()
        url = str(args[1] if len(args) > 1 else kwargs.get("url", ""))
        path = "/" + url.split("://", 1)[-1].split("/", 1)[-1] if "://" in url else url
        return method, path

    def paths(self, method: str | None = None) -> list[str]:
        return [path for verb, path, _ in self.calls if method is None or verb == method]

    @property
    def generation_calls(self) -> list[tuple[str, str, Any]]:
        return [c for c in self.calls if c[0] == "POST" and c[1] in GENERATION_PATHS]

    # -- request routing ---------------------------------------------------------------------
    def __call__(self, *args: Any, **kwargs: Any) -> FakeResponse:
        method, path = self._split(args, kwargs)
        body = kwargs.get("json")
        self.calls.append((method, path, body))
        if method == "GET":
            return self._get(path)
        if method == "POST":
            return self._post(path, body)
        return FakeResponse({})

    def _get(self, path: str) -> FakeResponse:
        if path == "/sdapi/v1/cmd-flags":
            flags: dict[str, Any] = {"api": True, "port": 7860}
            if self.flavor == "forge":
                flags.update({"forge_ref_a1111_home": None, "forge_ref_comfy_home": None})
            return FakeResponse(flags)
        if path == "/sdapi/v1/sd-modules":
            return FakeResponse(self.modules) if self.flavor == "forge" else FakeResponse({}, 404)
        if path == "/sdapi/v1/loras":
            return FakeResponse(list(self.loras))
        if path == "/sdapi/v1/sd-vae":
            if self.flavor == "a1111":
                return FakeResponse(list(self.modules))
            return FakeResponse({}, 404)
        if path == "/sdapi/v1/options":
            return FakeResponse(dict(self.options))
        if path == "/sdapi/v1/sd-models":
            return FakeResponse(
                [{"title": self.options["sd_model_checkpoint"], "model_name": "sdxl"}]
            )
        if path == "/sdapi/v1/progress":
            return FakeResponse({"progress": 0.0, "eta_relative": 0.0, "state": {}})
        if path in {"/sdapi/v1/samplers", "/sdapi/v1/schedulers", "/sdapi/v1/upscalers"}:
            return FakeResponse([])
        if path == "/sdapi/v1/scripts":
            return FakeResponse({"txt2img": ["ADetailer"], "img2img": ["ADetailer"]})
        return FakeResponse({})

    def _post(self, path: str, body: Any) -> FakeResponse:
        if path == "/sdapi/v1/options":
            self._apply_options(dict(body or {}))
            return FakeResponse({})
        if path == "/sdapi/v1/interrupt":
            self.interrupted.set()
            return FakeResponse({})
        if path in GENERATION_PATHS:
            self.payloads[path].append(dict(body or {}))
            self.generation_module_state.append(
                [str(m).replace("\\", "/").rsplit("/", 1)[-1] for m in self.options.get("forge_additional_modules") or []]
            )
            if self.reject_generation_when is not None:
                reason = self.reject_generation_when(dict(self.options))
                if reason:
                    self.rejected_generations.append(reason)
                    return FakeResponse({"error": "RuntimeError", "detail": "", "message": reason}, 500)
            if self.block_generation_until_interrupt:
                self.generation_started.set()
                if not self.interrupted.wait(timeout=10.0):
                    raise AssertionError("generation was never interrupted")
            if self.generation_error is not None:
                raise self.generation_error
            if path == "/sdapi/v1/extra-single-image":
                return FakeResponse({"image": TINY_PNG_B64, "html_info": ""})
            info = {"seed": self.seed, "all_seeds": [self.seed], "all_subseeds": [0]}
            return FakeResponse({"images": [TINY_PNG_B64], "info": json.dumps(info)})
        return FakeResponse({})

    def _apply_options(self, body: dict[str, Any]) -> None:
        for key, value in body.items():
            if key == "forge_additional_modules" and self.flavor == "forge":
                if self.ignore_module_writes:
                    continue
                known = {m["model_name"]: m["filename"] for m in self.modules}
                # Forge silently drops module names it does not know.
                self.options[key] = sorted(
                    known[name.replace("\\", "/").rsplit("/", 1)[-1]]
                    for name in value
                    if name.replace("\\", "/").rsplit("/", 1)[-1] in known
                )
            else:
                self.options[key] = value
