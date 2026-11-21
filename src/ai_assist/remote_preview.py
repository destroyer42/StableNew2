"""Operator-approved, per-user Remote Preview settings. No discovery or inference."""

from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass
from pathlib import Path

from src.ai_assist.remote_transport import HOST, PORT
from src.utils.atomic_io import atomic_write_json

SETTINGS_NAME = "remote_preview.json"
ENDPOINT = f"http://{HOST}:{PORT}"
RUNTIME_VERSION = "0.40.16"
DEFAULT_MODEL = "qwen3.5:4b-q4_K_M"
MODELS = (DEFAULT_MODEL, "lfm3:1.7b")
REMOTE_PREVIEW_LABEL = "Remote AI Assist Preview (unqualified)"
REMOTE_DISCLOSURE = "Request content is sent through the operator-managed encrypted SSH tunnel."
_DIGEST = re.compile(r"[0-9a-f]{64}")
_MAX_SETTINGS_BYTES = 2048


@dataclass(frozen=True, slots=True)
class RemoteApproval:
    endpoint: str
    model: str
    digest: str
    version: str

    def __post_init__(self) -> None:
        if (
            self.endpoint != ENDPOINT
            or self.model not in MODELS
            or not isinstance(self.digest, str)
            or not _DIGEST.fullmatch(self.digest)
            or self.version != RUNTIME_VERSION
        ):
            raise ValueError("unsupported remote identity")

    @property
    def model_reference(self) -> str:
        return f"sha256-{self.digest}:local"


@dataclass(frozen=True, slots=True)
class RemoteSettings:
    preferred: bool = False
    approval: RemoteApproval | None = None


def read_remote_settings(root: Path) -> RemoteSettings:
    """An absent or explicitly disabled record selects local mode. Damaged approvals fail closed."""

    try:
        with (root / SETTINGS_NAME).open("rb") as handle:
            raw = handle.read(_MAX_SETTINGS_BYTES + 1)
    except FileNotFoundError:
        return RemoteSettings()
    except OSError:
        return RemoteSettings(preferred=True)
    if len(raw) <= _MAX_SETTINGS_BYTES:
        try:
            data = json.loads(raw)
            if type(data) is dict and type(data.get("schema")) is int and data["schema"] == 1:
                if set(data) == {"schema", "preferred"} and data["preferred"] is False:
                    return RemoteSettings()
                if set(data) == {"schema", "preferred", "approval"} and data["preferred"] is True:
                    return RemoteSettings(
                        preferred=True, approval=RemoteApproval(**data["approval"])
                    )
        except (RecursionError, TypeError, ValueError):
            pass
    return RemoteSettings(preferred=True)


def write_remote_approval(root: Path, approval: RemoteApproval) -> None:
    atomic_write_json(
        root / SETTINGS_NAME, {"schema": 1, "preferred": True, "approval": asdict(approval)}
    )


def disable_remote_preview(root: Path) -> None:
    atomic_write_json(root / SETTINGS_NAME, {"schema": 1, "preferred": False})
