"""The in-app model selector (owner decision D20): list the models that are ready to use and switch between them.

A model is listed only when it is imported and verified in the AI root *and* at least one runtime build the registry
lists for it is imported and verified too. Selecting one activates it through :func:`src.ai_assist.activation.activate`
(the same function the admin tool uses), refuses while a request is in flight, and refuses unless the operator's egress
attestation already covers the build it would run on. It never records an attestation, never enables Preview, never loads
or runs anything and starts no thread: the whole switch is one synchronous call the operator asked for.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from src.ai_assist.activation import (
    Activation,
    ActivationRefused,
    activate,
    is_compatible,
    model_import_problem,
    runtime_import_problem,
)
from src.ai_assist.attestation import attestation_covers, read_attestation
from src.ai_assist.manifests import (
    ModelEntry,
    ModelRegistry,
    RuntimeBuild,
    RuntimeManifest,
    read_pointer,
)
from src.ai_assist.preview import (
    TRUST_CANDIDATE,
    TRUST_PREVIEW,
    TRUST_QUALIFIED,
    preview_enabled_for,
    trust_tier,
)

REFUSED_IN_FLIGHT = "request_in_flight"
REFUSED_UNKNOWN_MODEL = "unknown_model"
REFUSED_NOT_READY = "model_not_ready"
REFUSED_NOT_ATTESTED = "egress_not_attested"
REFUSED_NOT_COVERED = "egress_not_covered"


class SelectionRefused(Exception):
    """Nothing was switched. ``code`` is stable; ``build_id`` names the build an attestation refusal is about."""

    def __init__(self, code: str, build_id: str = "") -> None:
        super().__init__(code)
        self.code = code
        self.build_id = build_id


@dataclass(frozen=True, slots=True)
class ModelChoice:
    """One selectable model, with the build it would run on. Content-free."""

    model_id: str
    display_name: str
    sha256: str
    build_id: str
    active: bool
    #: ``qualified``, ``preview`` (the operator enabled this exact model and build) or ``candidate`` (not enabled yet).
    trust: str
    #: Whether the egress attestation already covers ``build_id`` and its executable.
    attested: bool


@dataclass(frozen=True, slots=True)
class Selection:
    choice: ModelChoice
    #: ``False`` when the model and build were already active and nothing was written.
    changed: bool
    activation: Activation | None = None


def _active_identity(root: Path) -> tuple[str, str]:
    try:
        pointer = read_pointer(root)
    except (OSError, ValueError):
        return "", ""
    if pointer is None:
        return "", ""
    return str(pointer.get("model_sha256", "")), str(pointer.get("runtime_build_id", ""))


class _BuildCheck:
    """Verifies each build at most once per call (a build is hashed, so a listing must not repeat it)."""

    def __init__(self, root: Path, runtime: RuntimeManifest) -> None:
        self._root = root
        self._runtime = runtime
        self._cache: dict[str, RuntimeBuild | None] = {}

    def verified(self, build_id: str) -> RuntimeBuild | None:
        if build_id not in self._cache:
            build = self._runtime.find(build_id)
            ok = build is not None and not runtime_import_problem(self._root, build)
            self._cache[build_id] = build if ok else None
        return self._cache[build_id]


def _pick_build(
    entry: ModelEntry, checks: _BuildCheck, active_build_id: str
) -> RuntimeBuild | None:
    """The currently active build when it is compatible, imported and verified; otherwise the first such build in the
    registry's order of preference."""

    ordered = sorted(entry.compatible_builds, key=lambda b: b != active_build_id)
    for build_id in ordered:
        build = checks.verified(build_id)
        if build is not None and is_compatible(entry, build):
            return build
    return None


def _choice(
    root: Path, entry: ModelEntry, build: RuntimeBuild, active_sha: str, active_build: str
) -> ModelChoice:
    if trust_tier(entry, build) == TRUST_QUALIFIED:
        trust = TRUST_QUALIFIED
    elif preview_enabled_for(root, entry, build):
        trust = TRUST_PREVIEW
    else:
        trust = TRUST_CANDIDATE
    return ModelChoice(
        model_id=entry.model_id,
        display_name=entry.display_name,
        sha256=entry.sha256,
        build_id=build.build_id,
        active=entry.sha256 == active_sha and build.build_id == active_build,
        trust=trust,
        attested=attestation_covers(root, build.build_id, build.executable),
    )


def list_model_choices(
    root: Path, runtime: RuntimeManifest, registry: ModelRegistry
) -> tuple[ModelChoice, ...]:
    """Only models that are imported and verified here, in registry order. Read-only: no write, no process."""

    active_sha, active_build = _active_identity(root)
    checks = _BuildCheck(root, runtime)
    choices: list[ModelChoice] = []
    for entry in registry.entries:
        if model_import_problem(root, entry):
            continue
        build = _pick_build(entry, checks, active_build)
        if build is not None:
            choices.append(_choice(root, entry, build, active_sha, active_build))
    return tuple(choices)


def select_model(
    root: Path,
    runtime: RuntimeManifest,
    registry: ModelRegistry,
    model_id: str,
    *,
    request_in_flight: bool,
) -> Selection:
    """Switch to ``model_id``. Raises :class:`SelectionRefused` (nothing changed) or :class:`ActivationRefused`."""

    if request_in_flight:
        raise SelectionRefused(REFUSED_IN_FLIGHT)
    entry = next((e for e in registry.entries if e.model_id == model_id), None)
    if entry is None:
        raise SelectionRefused(REFUSED_UNKNOWN_MODEL)
    active_sha, active_build = _active_identity(root)
    if model_import_problem(root, entry):
        raise SelectionRefused(REFUSED_NOT_READY)
    build = _pick_build(entry, _BuildCheck(root, runtime), active_build)
    if build is None:
        raise SelectionRefused(REFUSED_NOT_READY)
    if not attestation_covers(root, build.build_id, build.executable):
        raise SelectionRefused(
            REFUSED_NOT_COVERED if read_attestation(root) is not None else REFUSED_NOT_ATTESTED,
            build.build_id,
        )
    if entry.sha256 == active_sha and build.build_id == active_build:
        return Selection(_choice(root, entry, build, active_sha, active_build), changed=False)
    activation = activate(root, runtime, registry, build_id=build.build_id, model_id=model_id)
    if not activation.verification.ok:
        raise ActivationRefused(f"verification_failed:{activation.verification.reason}")
    return Selection(
        _choice(root, entry, build, entry.sha256, build.build_id),
        changed=True,
        activation=activation,
    )


__all__ = [
    "REFUSED_IN_FLIGHT",
    "REFUSED_NOT_ATTESTED",
    "REFUSED_NOT_COVERED",
    "REFUSED_NOT_READY",
    "REFUSED_UNKNOWN_MODEL",
    "ModelChoice",
    "Selection",
    "SelectionRefused",
    "list_model_choices",
    "select_model",
]
