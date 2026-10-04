"""Explicit endpoint, read-only GET evidence. No discovery, installs or generation."""

from __future__ import annotations

import json
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit
from urllib.request import urlopen

from .provenance import verify_assets

READ_PATHS = (
    "/openapi.json", "/sdapi/v1/cmd-flags", "/sdapi/v1/sd-models", "/sdapi/v1/sd-modules",
    "/sdapi/v1/sd-vae", "/sdapi/v1/options", "/sdapi/v1/scripts", "/sdapi/v1/script-info",
    "/sdapi/v1/loras", "/sdapi/v1/upscalers", "/adetailer/v1/ad_model",
    "/adetailer/v1/schema",
)
REQUIRED_ROUTES = {
    "/sdapi/v1/txt2img": "post", "/sdapi/v1/img2img": "post",
    "/sdapi/v1/extra-single-image": "post", "/sdapi/v1/progress": "get",
    "/sdapi/v1/interrupt": "post", "/sdapi/v1/options": "post",
}


def loopback_endpoint(value: str) -> str:
    parsed = urlsplit(value)
    if (parsed.scheme != "http" or parsed.hostname not in {"127.0.0.1", "localhost", "::1"}
            or parsed.username or parsed.password or parsed.query or parsed.fragment
            or parsed.path not in {"", "/"} or parsed.port is None):
        raise ValueError("Supply an explicit loopback HTTP endpoint and port")
    return value.rstrip("/")


def explicit_endpoint(value: str, backend: str) -> str:
    endpoint = loopback_endpoint(value)
    if backend not in {"a1111_webui", "forge_webui"}:
        raise ValueError("Unsupported qualification backend")
    if backend == "forge_webui" and urlsplit(endpoint).port != 7871:
        raise ValueError("The frozen Forge qualification port is 7871")
    return endpoint


def fetch_json(base_url: str, path: str) -> Any:
    if path not in READ_PATHS:
        raise ValueError("Preflight only permits the frozen read-only GET paths")
    url = base_url + path
    try:
        with urlopen(url, timeout=3) as response:
            if response.geturl() != url:
                raise ValueError("Endpoint redirected; identity evidence is not trustworthy")
            return json.load(response)
    except (OSError, ValueError):
        return None


def inspect_endpoint(
    base_url: str, backend: str, *, selected: dict[str, str],
    fetch: Callable[[str, str], Any] = fetch_json, ownership: str = "external",
    launch_command: Sequence[str] | None = None,
) -> dict[str, Any]:
    from src.api.webui_runtime_identity import probe_runtime_identity

    endpoint = explicit_endpoint(base_url, backend)
    data = {path: fetch(endpoint, path) for path in READ_PATHS}
    observed = probe_runtime_identity(lambda path: data.get(path))
    checks: dict[str, bool] = {"runtime_identity": observed.identity == backend,
                               "ownership_known": ownership in {"external", "owned"}}
    routes = (data["/openapi.json"] or {}).get("paths", {})
    for path, method in REQUIRED_ROUTES.items():
        checks[f"route:{path}"] = method in routes.get(path, {})
    for path in ("/sdapi/v1/options", "/sdapi/v1/scripts"):
        checks[f"available:{path}"] = isinstance(data[path], dict)
    for path in ("/sdapi/v1/sd-models", "/sdapi/v1/script-info", "/sdapi/v1/upscalers"):
        checks[f"available:{path}"] = isinstance(data[path], list)
    models = data["/sdapi/v1/sd-models"] or []
    checks["checkpoint_visible"] = any(selected["checkpoint"] in {
        m.get("model_name"), m.get("title"), Path(m.get("filename", "")).name,
    } for m in models)
    vaes = data["/sdapi/v1/sd-modules" if backend == "forge_webui" else "/sdapi/v1/sd-vae"]
    checks["vae_visible"] = selected["vae"] == "Automatic" or any(
        selected["vae"] == m.get("model_name") for m in (vaes or []))
    checks["lora_visible"] = any(selected["lora"] in {m.get("name"), m.get("alias")}
                                 for m in (data["/sdapi/v1/loras"] or []))
    scripts = data["/sdapi/v1/scripts"] or {}
    names = [str(s).lower() for s in scripts.get("txt2img", []) + scripts.get("img2img", [])]
    checks["adetailer_visible"] = "adetailer" in names
    detectors = data["/adetailer/v1/ad_model"] or {}
    checks["detectors_visible"] = all(name in detectors.get("ad_model", []) for name in
                                     ("face_yolov8n.pt", "hand_yolov8n.pt"))
    checks["upscaler_visible"] = any(selected["upscaler"] == m.get("name")
                                     for m in (data["/sdapi/v1/upscalers"] or []))
    if backend == "forge_webui":
        # Neo's cmd-flags endpoint can fail response validation. Only a recorded
        # qualification-owned launch may supply independent flag evidence.
        flags = data["/sdapi/v1/cmd-flags"]
        checks["downloads_disabled"] = (
            isinstance(flags, dict) and flags.get("ad_no_huggingface") is True
        ) or (ownership == "owned" and "--ad-no-huggingface" in (launch_command or ()))
    return {"endpoint": endpoint, "backend": backend, "observed_identity": observed.identity,
            "ownership": ownership, "checks": checks, "ready": all(checks.values()),
            "cmd_flags_available": isinstance(data["/sdapi/v1/cmd-flags"], dict),
            "controlnet": ("FORGE_CONTROLNET_RUNTIME_CAPABILITY_PRESENT"
                           if backend == "forge_webui" and "controlnet" in names
                           else "FORGE_CONTROLNET_RUNTIME_CAPABILITY_NOT_OBSERVED"), "responses": data}


def local_preflight(matrix: dict[str, Any]) -> dict[str, Any]:
    """Hash only the explicitly frozen files; port/process evidence is supplied separately."""
    return {"assets": verify_assets(matrix["assets"]), "no_generation": True}
