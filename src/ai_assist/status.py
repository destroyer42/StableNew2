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
from src.ai_assist.preview import (
    PREVIEW_LABEL,
    TRUST_CANDIDATE,
    TRUST_PREVIEW,
    TRUST_QUALIFIED,
    PreviewState,
    preview_enabled_for,
    trust_tier,
)

_CONFIG_DIR = Path(__file__).resolve().parents[2] / "config"
RUNTIME_MANIFEST_PATH = _CONFIG_DIR / "managed_ai_runtime.json"
MODEL_REGISTRY_PATH = _CONFIG_DIR / "ai_model_registry.json"

STATE_NOT_INSTALLED = "not_installed"
STATE_READY = "ready"
STATE_INTEGRITY_FAILED = "integrity_failed"
#: A candidate model and runtime are installed and verified, but the operator has not enabled AI Assist Preview.
STATE_PREVIEW_AVAILABLE = "preview_available"
#: A candidate is installed, verified and enabled by the operator (AI Assist Preview, owner decision D13).
STATE_PREVIEW = "preview"

MISSING_PINNED_BUILD = "pinned_build"
MISSING_IMPORTED_MODEL = "imported_model"
MISSING_ENABLEMENT = "enablement"
MISSING_ATTESTATION = "attestation"


@dataclass(frozen=True, slots=True)
class AiAssistStatus:
    state: str
    summary: str
    blockers: tuple[str, ...] = ()
    actions: tuple[str, ...] = ()
    last_outcome: str | None = None
    egress: str = "not_attested"
    #: ``qualified``, ``preview`` or ``""``. A preview model is unqualified and must be labelled as such everywhere.
    trust: str = ""
    #: The exact next prerequisite the operator is missing (``MISSING_*``), or ``""``.
    missing: str = ""
    model_name: str = ""
    build_id: str = ""
    model_sha256: str = ""


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
            "Offline AI Assist is not installed: nothing has been imported (a runtime build must also be pinned).",
            actions=("Follow docs/runbooks/ai_assist_preview_activation.md.",),
            missing=MISSING_IMPORTED_MODEL,
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
    if not runtime.builds:
        return AiAssistStatus(
            STATE_NOT_INSTALLED,
            "Offline AI Assist is not set up: no runtime build is pinned in config/managed_ai_runtime.json.",
            blockers=problems,
            actions=(
                "Pin a runtime build by reviewed change (tools/ai_assist_admin.py describe-runtime).",
            ),
            last_outcome=last,
            egress=egress,
            missing=MISSING_PINNED_BUILD,
        )
    verification = verify_installation(base, runtime, registry, allow_candidate=True)
    if verification.ok and verification.entry is not None and verification.build is not None:
        entry, build = verification.entry, verification.build
        if trust_tier(entry, build) == TRUST_QUALIFIED:
            return AiAssistStatus(
                STATE_READY,
                "Offline AI Assist is installed and its files match the pinned identities.",
                blockers=problems,
                last_outcome=last,
                egress=egress,
                trust=TRUST_QUALIFIED,
                model_name=entry.display_name,
                build_id=build.build_id,
                model_sha256=entry.sha256,
            )
        if preview_enabled_for(base, entry, build):
            return AiAssistStatus(
                STATE_PREVIEW,
                f"{PREVIEW_LABEL} (enabled by the operator): {entry.display_name} is installed and verified but not qualified.",
                blockers=problems,
                actions=()
                if egress == "attested"
                else ("Record the outbound firewall attestation.",),
                last_outcome=last,
                egress=egress,
                trust=TRUST_PREVIEW,
                missing="" if egress == "attested" else MISSING_ATTESTATION,
                model_name=entry.display_name,
                build_id=build.build_id,
                model_sha256=entry.sha256,
            )
        return AiAssistStatus(
            STATE_PREVIEW_AVAILABLE,
            f"{entry.display_name} is installed and verified but not qualified. AI Assist Preview is not enabled.",
            blockers=problems,
            actions=("Enable AI Assist Preview from the Prompt tab.",),
            last_outcome=last,
            egress=egress,
            missing=MISSING_ENABLEMENT,
            model_name=entry.display_name,
            build_id=build.build_id,
            model_sha256=entry.sha256,
        )
    if verification.code is OutcomeCode.NOT_INSTALLED:
        return AiAssistStatus(
            STATE_NOT_INSTALLED,
            "Offline AI Assist is not installed: no runtime and model have been imported and activated.",
            blockers=problems,
            actions=("Import the pinned AI runtime and model from local files.",),
            last_outcome=last,
            egress=egress,
            missing=MISSING_IMPORTED_MODEL,
        )
    return AiAssistStatus(
        STATE_INTEGRITY_FAILED,
        "Offline AI Assist files do not match the pinned identities, so it is disabled.",
        blockers=(verification.reason, *problems),
        actions=("Re-import the pinned runtime and model from verified local files.",),
        last_outcome=last,
        egress=egress,
    )


def preview_state(status: AiAssistStatus) -> PreviewState:
    """The operator-facing Preview view of a status (content-free)."""

    trust = {
        STATE_READY: TRUST_QUALIFIED,
        STATE_PREVIEW: TRUST_PREVIEW,
        STATE_PREVIEW_AVAILABLE: TRUST_CANDIDATE,
    }.get(status.state, "")
    missing = status.missing
    if status.state == STATE_INTEGRITY_FAILED:
        missing = "integrity"
    elif trust and not missing and status.egress != "attested":
        missing = MISSING_ATTESTATION
    return PreviewState(trust, missing, status.model_name, status.build_id, status.model_sha256)


__all__ = [
    "MODEL_REGISTRY_PATH",
    "RUNTIME_MANIFEST_PATH",
    "STATE_INTEGRITY_FAILED",
    "MISSING_ATTESTATION",
    "MISSING_ENABLEMENT",
    "MISSING_IMPORTED_MODEL",
    "MISSING_PINNED_BUILD",
    "STATE_NOT_INSTALLED",
    "STATE_PREVIEW",
    "STATE_PREVIEW_AVAILABLE",
    "STATE_READY",
    "AiAssistStatus",
    "preview_state",
    "read_status",
]
