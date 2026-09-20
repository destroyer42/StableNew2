"""Read-only probes of the configured A1111 endpoint (never starts or stops it)."""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from typing import Any


@dataclass
class BackendInfo:
    base_url: str
    reachable: bool = False
    models: list[str] = field(default_factory=list)
    loras: list[str] = field(default_factory=list)
    active_checkpoint: str = ""
    version: str = ""
    error: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {
            "base_url": self.base_url,
            "reachable": self.reachable,
            "model_count": len(self.models),
            "lora_count": len(self.loras),
            "active_checkpoint": self.active_checkpoint,
            "version": self.version,
            "error": self.error,
        }


def _get_json(url: str, timeout: float) -> Any:
    with urllib.request.urlopen(url, timeout=timeout) as response:  # noqa: S310 - loopback A1111
        return json.loads(response.read().decode("utf-8"))


def probe_backend(base_url: str, *, timeout: float = 10.0) -> BackendInfo:
    """Query documented A1111 read endpoints; failures are reported, not raised."""

    info = BackendInfo(base_url=base_url.rstrip("/"))
    try:
        models = _get_json(f"{info.base_url}/sdapi/v1/sd-models", timeout)
        info.reachable = True
        info.models = [str(m.get("model_name") or m.get("title") or "") for m in models]
    except (urllib.error.URLError, OSError, ValueError) as exc:
        info.error = f"{type(exc).__name__}: {exc}"
        return info
    for attr, path, extract in (
        ("loras", "/sdapi/v1/loras", lambda d: [str(x.get("name") or "") for x in d]),
        (
            "active_checkpoint",
            "/sdapi/v1/options",
            lambda d: str(d.get("sd_model_checkpoint") or ""),
        ),
        ("version", "/config", lambda d: str(d.get("version") or "")),
    ):
        try:
            setattr(info, attr, extract(_get_json(f"{info.base_url}{path}", timeout)))
        except (urllib.error.URLError, OSError, ValueError, AttributeError):
            continue
    return info


def fetch_progress(base_url: str, *, timeout: float = 5.0) -> dict[str, Any] | None:
    """A1111's /progress snapshot, or None when unreachable (used as a busy probe)."""

    try:
        data = _get_json(
            f"{base_url.rstrip('/')}/sdapi/v1/progress?skip_current_image=true", timeout
        )
    except (urllib.error.URLError, OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None
