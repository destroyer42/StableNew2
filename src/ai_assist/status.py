"""Read-only installation status for the Operator Readiness window. Never hashes, spawns or writes."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from src.ai_assist.attestation import read_attestation
from src.ai_assist.contracts import OutcomeCode
from src.ai_assist.events import EventLog
from src.ai_assist.manifests import (
    ModelRegistry,
    RuntimeManifest,
    load_model_registry,
    load_runtime_manifest,
    verify_installation,
)
from src.ai_assist.paths import events_path, resolve_ai_root

_CONFIG_DIR = Path(__file__).resolve().parents[2] / "config"
RUNTIME_MANIFEST_PATH = _CONFIG_DIR / "managed_ai_runtime.json"
MODEL_REGISTRY_PATH = _CONFIG_DIR / "ai_model_registry.json"

STATE_NOT_INSTALLED = "not_installed"
STATE_READY = "ready"
STATE_INTEGRITY_FAILED = "integrity_failed"


@dataclass(frozen=True, slots=True)
class AiAssistStatus:
    state: str
    summary: str
    blockers: tuple[str, ...] = ()
    actions: tuple[str, ...] = ()
    last_outcome: str | None = None
    egress: str = "not_attested"


def read_status(
    root: Path | None = None,
    runtime: RuntimeManifest | None = None,
    registry: ModelRegistry | None = None,
) -> AiAssistStatus:
    """Cheap, side-effect-free status. A fast identity check only (sizes and times); no inference, no hashing."""

    base = resolve_ai_root(root)
    if runtime is None and registry is None and not base.is_dir():
        # Nothing can be installed without the per-user directory, so the shipped manifests need not be read. This keeps
        # the readiness window free of config-file reads on a machine that never set this feature up.
        return AiAssistStatus(
            STATE_NOT_INSTALLED,
            "Offline AI Assist is not installed: nothing has been imported.",
        )
    runtime = runtime if runtime is not None else load_runtime_manifest(RUNTIME_MANIFEST_PATH)
    registry = registry if registry is not None else load_model_registry(MODEL_REGISTRY_PATH)
    egress = "attested" if read_attestation(base) is not None else "not_attested"

    last: str | None = None
    try:
        tail = EventLog(events_path(base)).tail(1)
        if tail:
            value = tail[-1].get("outcome")
            last = value if isinstance(value, str) else None
    except OSError:
        last = None

    problems = (*runtime.problems, *registry.problems)
    if not any(entry.qualified for entry in registry.entries) or not any(
        build.qualified for build in runtime.builds
    ):
        return AiAssistStatus(
            STATE_NOT_INSTALLED,
            "Offline AI Assist is not set up: no qualified runtime and model are registered.",
            blockers=problems,
            last_outcome=last,
            egress=egress,
        )
    verification = verify_installation(base, runtime, registry)
    if verification.ok:
        return AiAssistStatus(
            STATE_READY,
            "Offline AI Assist is installed and its files match the pinned identities.",
            blockers=problems,
            last_outcome=last,
            egress=egress,
        )
    if verification.code is OutcomeCode.NOT_INSTALLED:
        return AiAssistStatus(
            STATE_NOT_INSTALLED,
            "Offline AI Assist is not installed.",
            blockers=problems,
            actions=("Import the pinned AI runtime and model from local files.",),
            last_outcome=last,
            egress=egress,
        )
    return AiAssistStatus(
        STATE_INTEGRITY_FAILED,
        "Offline AI Assist files do not match the pinned identities, so it is disabled.",
        blockers=(verification.reason, *problems),
        actions=("Re-import the pinned runtime and model from verified local files.",),
        last_outcome=last,
        egress=egress,
    )


__all__ = [
    "MODEL_REGISTRY_PATH",
    "RUNTIME_MANIFEST_PATH",
    "STATE_INTEGRITY_FAILED",
    "STATE_NOT_INSTALLED",
    "STATE_READY",
    "AiAssistStatus",
    "read_status",
]
