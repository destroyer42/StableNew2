"""Operator-approved, per-user Remote Preview settings. No discovery or inference."""

from __future__ import annotations

import json
import re
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, replace
from pathlib import Path

from src.ai_assist.remote_transport import HOST, PORT
from src.utils.atomic_io import atomic_write_json
from src.utils.file_writer_lock import file_writer_lock

SETTINGS_NAME = "remote_preview.json"
ENDPOINT = f"http://{HOST}:{PORT}"
RUNTIME_VERSION = "0.40.16"
DEFAULT_MODEL = "qwen3.5:4b-q4_K_M"
#: A third-party build of the default model with its refusal behaviour removed. Never active unless the operator
#: approves it and picks it; not in VISION_MODELS because it has not been tried with a picture.
UNCENSORED_MODEL = "huihui_ai/qwen3.5-abliterated:4B"
MODEL_LABELS = {
    DEFAULT_MODEL: "Qwen3.5-4B (default)",
    "lfm3:1.7b": "LFM3-1.7B",
    UNCENSORED_MODEL: "Qwen3.5-4B uncensored",
}
MODELS = tuple(MODEL_LABELS)
#: Approved models that accept a picture (ASSIST-FIX motion phrase). Any other model is never sent one.
VISION_MODELS = frozenset({DEFAULT_MODEL})
_DEFAULT_SELECTION = "default"
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
    approvals: tuple[RemoteApproval, ...] = ()
    selection: str | None = None
    damaged: bool = False

    @property
    def active_model(self) -> str | None:
        if self.selection == _DEFAULT_SELECTION:
            # Approvals are read in MODELS order, with Qwen first.
            return self.approvals[0].model if self.approvals else None
        return self.selection

    @property
    def approval(self) -> RemoteApproval | None:
        if not self.preferred:
            return None
        return next((item for item in self.approvals if item.model == self.active_model), None)


class DuplicateRemoteKeyError(ValueError):
    """A remote approval or response contains an ambiguous JSON object."""


def reject_duplicate_json_keys(pairs: list[tuple[str, object]]) -> dict[str, object]:
    data: dict[str, object] = {}
    for key, value in pairs:
        if key in data:
            raise DuplicateRemoteKeyError("duplicate remote JSON key")
        data[key] = value
    return data


def _parse_settings(raw: bytes) -> RemoteSettings:
    data = json.loads(raw, object_pairs_hook=reject_duplicate_json_keys)
    if type(data) is not dict or type(data.get("schema")) is not int:
        raise ValueError("invalid remote settings")
    if data["schema"] == 1:
        if set(data) == {"schema", "preferred"} and data["preferred"] is False:
            return RemoteSettings()
        if set(data) == {"schema", "preferred", "approval"} and data["preferred"] is True:
            approval = RemoteApproval(**data["approval"])
            return RemoteSettings(True, (approval,), approval.model)
    if data["schema"] == 2 and set(data) == {
        "schema",
        "preferred",
        "endpoint",
        "version",
        "approvals",
        "active_model",
    }:
        preferred, approvals, active = data["preferred"], data["approvals"], data["active_model"]
        if (
            type(preferred) is bool
            and data["endpoint"] == ENDPOINT
            and data["version"] == RUNTIME_VERSION
            and type(approvals) is dict
            and approvals.keys() <= set(MODELS)
            and (
                active is None
                or (active == _DEFAULT_SELECTION and bool(approvals))
                or (isinstance(active, str) and active in approvals)
            )
        ):
            identities = tuple(
                RemoteApproval(ENDPOINT, name, approvals[name], RUNTIME_VERSION)
                for name in MODELS
                if name in approvals
            )
            if len({item.digest for item in identities}) != len(identities):
                raise ValueError("conflicting remote model digests")
            return RemoteSettings(preferred, identities, active)
    raise ValueError("invalid remote settings")


def read_remote_settings(root: Path) -> RemoteSettings:
    """An absent or explicitly disabled record selects local mode. Damaged approvals fail closed."""
    try:
        with (root / SETTINGS_NAME).open("rb") as handle:
            raw = handle.read(_MAX_SETTINGS_BYTES + 1)
    except FileNotFoundError:
        return RemoteSettings()
    except OSError:
        return RemoteSettings(preferred=True, damaged=True)
    if len(raw) <= _MAX_SETTINGS_BYTES:
        try:
            return _parse_settings(raw)
        except (RecursionError, TypeError, ValueError):
            pass
    return RemoteSettings(preferred=True, damaged=True)


@contextmanager
def _edit_settings(root: Path, *, timeout: float = 2.0) -> Iterator[RemoteSettings]:
    with file_writer_lock(root / SETTINGS_NAME, timeout=timeout):
        yield read_remote_settings(root)


def _save(root: Path, settings: RemoteSettings) -> None:
    atomic_write_json(
        root / SETTINGS_NAME,
        {
            "schema": 2,
            "preferred": settings.preferred,
            "endpoint": ENDPOINT,
            "version": RUNTIME_VERSION,
            "approvals": {item.model: item.digest for item in settings.approvals},
            "active_model": settings.selection,
        },
    )


def write_remote_approval(root: Path, approval: RemoteApproval) -> None:
    with _edit_settings(root) as settings:
        if settings.damaged:
            raise ValueError("remote settings are damaged")
        if any(
            item.model != approval.model and item.digest == approval.digest
            for item in settings.approvals
        ):
            raise ValueError("conflicting remote model digests")
        approvals = tuple(item for item in settings.approvals if item.model != approval.model)
        active = settings.selection if settings.approvals else _DEFAULT_SELECTION
        _save(root, RemoteSettings(True, (*approvals, approval), active))


def select_remote_model(root: Path, approval: RemoteApproval) -> None:
    # Compare the exact identity shown in the picker, under the same lock as admin writes.
    with _edit_settings(root, timeout=0) as settings:
        if not settings.preferred or approval not in settings.approvals:
            raise ValueError("remote model is no longer selectable")
        if settings.selection != approval.model:
            _save(root, replace(settings, selection=approval.model))


def revoke_remote_approval(root: Path, model: str) -> None:
    with _edit_settings(root) as settings:
        if settings.damaged:
            raise ValueError("remote settings are damaged")
        approvals = tuple(item for item in settings.approvals if item.model != model)
        active = None if settings.active_model == model else settings.selection
        _save(root, replace(settings, approvals=approvals, selection=active))


def enable_remote_preview(root: Path) -> None:
    with _edit_settings(root) as settings:
        if not settings.approvals:
            raise ValueError("remote model approval required")
        _save(root, replace(settings, preferred=True))


def disable_remote_preview(root: Path) -> None:
    with _edit_settings(root) as settings:
        # Explicit operator recovery from a damaged document cannot preserve unverifiable approvals.
        _save(root, RemoteSettings() if settings.damaged else replace(settings, preferred=False))
