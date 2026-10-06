"""Same-session attestation of a StableNew-owned managed Forge (PR-RUNTIME-FORGE-IDENTITY-150).

``forge_webui`` work needs a *positively identified* Forge, and that guard runs before every stage's first
generation dispatch with fresh read-only GETs and no memory. One failed required GET (``/options`` or
``/sd-modules``) therefore turned a healthy managed Forge into ``unknown`` and rejected a stage.

This module adds the one narrow relaxation that is safe, and nothing else:

    The exact process StableNew launched was already positively classified as Forge from real endpoint evidence
    during this exact, still-current runtime session, and the current weak probe carries no contradictory
    positive evidence.

Authority split (unchanged): ``WebUIProcessManager`` stays the only lifecycle/ownership authority and merely
exposes immutable session facts; this module (with ``webui_runtime_identity``) stays the only endpoint-identity
authority. Ownership, a declared ``runtime_identity``, a port, a path or a healthy endpoint are never proof; only a
real positive classification creates an attestation, and only for the session it was observed in.

The attestation is one in-memory slot (the WebUI-family runtime is a single slot). It is never persisted. It is
dropped the moment the session facts stop matching or contradicting evidence appears, and an external/unowned
endpoint never has one. Diagnostics distinguish ``live_positive``, ``same_session_attestation``,
``no_valid_attestation``, ``contradictory_identity`` and ``session_changed``.
"""

from __future__ import annotations

import logging
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, replace
from typing import Any

from src.api.webui_runtime_identity import (
    FORGE_WEBUI_IDENTITY,
    UNKNOWN_WEBUI_IDENTITY,
    WebUIRuntimeIdentity,
    WebUIRuntimeIdentityMismatch,
    assert_runtime_matches_backend,
    classify_client_runtime,
)

logger = logging.getLogger(__name__)

SOURCE_LIVE_POSITIVE = "live_positive"
SOURCE_SAME_SESSION = "same_session_attestation"
SOURCE_NO_ATTESTATION = "no_valid_attestation"
SOURCE_CONTRADICTORY = "contradictory_identity"
SOURCE_SESSION_CHANGED = "session_changed"
#: A non-Forge backend's own (unchanged) policy decided; no attestation was consulted.
SOURCE_NOT_APPLICABLE = "not_applicable"

GAP_COMPLETE_LOSS = "complete_endpoint_loss"
GAP_CONFLICTING_VAE = "conflicting_sd_vae"
GAP_OPTIONS_WITHOUT_FORGE_KEYS = "options_without_forge_keys"
GAP_OPTIONS_UNAVAILABLE = "options_unavailable"
GAP_OPTIONS_MALFORMED = "options_malformed"
GAP_MODULES_UNAVAILABLE = "sd_modules_unavailable"
GAP_MODULES_MALFORMED = "sd_modules_malformed"
GAP_INDETERMINATE = "indeterminate"

#: Gaps that are positive evidence *against* Forge, not merely missing evidence. They are never transient.
CONTRADICTORY_GAPS = frozenset({GAP_CONFLICTING_VAE, GAP_OPTIONS_WITHOUT_FORGE_KEYS})

#: Missing/incomplete/malformed evidence: the only gaps the initial-establishment settle may wait through.
SETTLE_GAPS = frozenset({
    GAP_COMPLETE_LOSS, GAP_OPTIONS_UNAVAILABLE, GAP_OPTIONS_MALFORMED, GAP_MODULES_UNAVAILABLE, GAP_MODULES_MALFORMED,
})

#: Initial identity-establishment settle (finite, seconds): general readiness can be proven a moment before the
#: endpoint serves enough evidence (``/options``, ``/sd-modules``) to classify Forge. It runs only for an owned,
#: still-current session with no valid attestation, until the first real positive classification. A probe that is
#: already in flight is not interrupted, so the wall time can exceed the bound by at most one probe.
INITIAL_IDENTITY_SETTLE_SECONDS = 8.0
INITIAL_IDENTITY_POLL_SECONDS = 0.5

SETTLE_ESTABLISHED = "initial_identity_established"
SETTLE_TIMEOUT = "initial_identity_settle_timeout"
SETTLE_CONTRADICTION = "initial_identity_settle_contradiction"
SETTLE_SESSION_CHANGED = "initial_identity_settle_session_changed"
SETTLE_STOPPED = "initial_identity_settle_ineligible_evidence"


def identity_gap(observed: WebUIRuntimeIdentity) -> str | None:
    """Why an endpoint was not positively classified; ``None`` for a positively classified endpoint.

    Pure function of the classification evidence. Distinguishes missing evidence (unavailable/malformed endpoints,
    complete loss) from contradicting evidence (an A1111-style ``/sd-vae`` list, readable options with no Forge keys).
    """

    if observed.is_known:
        return None
    evidence = observed.evidence
    if not evidence:
        return GAP_COMPLETE_LOSS
    state = evidence.get("endpoint_state") or {}
    options_ok = bool(evidence.get("options_readable"))
    any_forge_option = bool(evidence.get("any_forge_option", evidence.get("forge_option_keys")))
    if evidence.get("sd_vae_list"):
        return GAP_CONFLICTING_VAE
    if options_ok and not any_forge_option:
        return GAP_OPTIONS_WITHOUT_FORGE_KEYS
    if not options_ok:
        return GAP_OPTIONS_MALFORMED if state.get("options") == "malformed" else GAP_OPTIONS_UNAVAILABLE
    if not evidence.get("sd_modules_list"):
        return GAP_MODULES_MALFORMED if state.get("sd_modules") == "malformed" else GAP_MODULES_UNAVAILABLE
    return GAP_INDETERMINATE


def _normalized_endpoint(value: Any) -> str:
    return str(value or "").strip().rstrip("/").lower()


@dataclass(frozen=True, eq=False)
class OwnedWebUISession:
    """The exact launch of the owned WebUI-family process at one instant (facts the manager already owns).

    ``manager`` and ``process`` are held by reference and compared by identity: a replacement manager or a new
    process object is a different session even when its PID, endpoint and readiness epoch happen to match. The
    single slot is dropped on any mismatch, so the references never outlive the attestation they belong to.
    """

    manager: Any
    process: Any
    pid: int
    ready_epoch: int
    endpoint: str
    declared_identity: str

    def same_launch(self, other: OwnedWebUISession) -> bool:
        return (
            self.manager is other.manager
            and self.process is other.process
            and self.pid == other.pid
            and self.ready_epoch == other.ready_epoch
            and self.endpoint == other.endpoint
            and self.declared_identity == other.declared_identity
        )

    def describe(self) -> str:
        return f"pid={self.pid} epoch={self.ready_epoch} endpoint={self.endpoint}"


@dataclass(frozen=True)
class IdentityDecision:
    """Why a runtime-identity guard allowed or refused one stage (structured diagnostics, no payloads)."""

    source: str
    allowed: bool
    observed: WebUIRuntimeIdentity
    gap: str | None = None
    session: OwnedWebUISession | None = None
    settle: IdentitySettleReport | None = None

    def describe(self) -> str:
        parts = [f"source={self.source}", f"observed={self.observed.identity}"]
        if self.gap:
            parts.append(f"gap={self.gap}")
        if self.session is not None:
            parts.append(self.session.describe())
        if self.settle is not None:
            parts.append(self.settle.describe())
        return ", ".join(parts)


@dataclass(frozen=True)
class IdentitySettleReport:
    """What the bounded initial identity-establishment settle did (bounded facts, never payloads)."""

    outcome: str
    attempts: int
    elapsed_seconds: float
    bound_seconds: float
    gap: str | None

    def describe(self) -> str:
        return (
            f"initial_identity_settle={self.outcome} attempts={self.attempts} "
            f"elapsed={self.elapsed_seconds:.2f}s bound={self.bound_seconds:.1f}s last_gap={self.gap}"
        )


def _default_manager() -> Any:
    from src.api.webui_process_manager import get_global_webui_process_manager

    return get_global_webui_process_manager()


class ManagedWebUIIdentityAttestor:
    """Holds at most one Forge attestation, bound to one owned runtime session."""

    def __init__(
        self,
        manager_getter: Callable[[], Any] | None = None,
        *,
        settle_seconds: float = INITIAL_IDENTITY_SETTLE_SECONDS,
        poll_seconds: float = INITIAL_IDENTITY_POLL_SECONDS,
        clock: Callable[[], float] = time.monotonic,
        sleeper: Callable[[float], None] = time.sleep,
    ) -> None:
        self._manager_getter = manager_getter or _default_manager
        self._settle_seconds = max(0.0, float(settle_seconds))
        self._poll_seconds = max(0.001, float(poll_seconds))
        self._clock = clock
        self._sleeper = sleeper
        self._lock = threading.Lock()
        self._attested: OwnedWebUISession | None = None
        self._reuse_logged = False

    # -- session facts ------------------------------------------------------------------------------------

    def current_session(self, client_endpoint: Any) -> OwnedWebUISession | None:
        """The authoritative owned live session serving ``client_endpoint``, or ``None`` (external/unknown/stale)."""

        try:
            manager = self._manager_getter()
            if manager is None or not manager.owns_process or not manager.is_running():
                return None
            process = manager.process
            pid = manager.pid
            epoch = manager.ready_epoch
            endpoint = _normalized_endpoint(manager.endpoint)
            declared = str(manager.runtime_identity or "")
        except Exception:  # noqa: BLE001 - facts that cannot be read are facts that cannot prove anything
            return None
        if process is None or isinstance(pid, bool) or not isinstance(pid, int) or pid <= 0:
            return None
        if getattr(process, "pid", None) != pid:
            return None
        if isinstance(epoch, bool) or not isinstance(epoch, int) or epoch < 1:
            return None
        if not endpoint or endpoint != _normalized_endpoint(client_endpoint):
            return None
        return OwnedWebUISession(manager, process, pid, epoch, endpoint, declared)

    def attested_session(self) -> OwnedWebUISession | None:
        with self._lock:
            return self._attested

    def invalidate(self, reason: str) -> None:
        with self._lock:
            self._drop_locked(reason)

    def _drop_locked(self, reason: str) -> None:
        if self._attested is not None:
            logger.info("[identity] Forge attestation (%s) invalidated: %s", self._attested.describe(), reason)
        self._attested = None
        self._reuse_logged = False

    # -- decision -----------------------------------------------------------------------------------------

    def decide(
        self,
        backend_id: str,
        observed: WebUIRuntimeIdentity,
        before: OwnedWebUISession | None,
        after: OwnedWebUISession | None,
    ) -> IdentityDecision:
        """Apply the guard to one live observation (``before``/``after`` are the session facts around the probe)."""

        gap = identity_gap(observed)
        with self._lock:
            if observed.is_forge:
                self._establish_locked(before, after)
            elif observed.is_a1111:
                self._drop_locked("a positive A1111 classification contradicts it")
            elif gap in CONTRADICTORY_GAPS:
                self._drop_locked(f"the endpoint evidence contradicts Forge ({gap})")
            if backend_id != FORGE_WEBUI_IDENTITY:
                return IdentityDecision(SOURCE_NOT_APPLICABLE, True, observed, gap)
            if observed.is_forge:
                return IdentityDecision(SOURCE_LIVE_POSITIVE, True, observed, None, after)
            if observed.is_a1111 or gap in CONTRADICTORY_GAPS:
                return IdentityDecision(SOURCE_CONTRADICTORY, False, observed, gap)
            attested = self._attested
            if attested is None:
                return IdentityDecision(SOURCE_NO_ATTESTATION, False, observed, gap)
            if after is None or not attested.same_launch(after):
                self._drop_locked("the owned runtime session changed")
                return IdentityDecision(SOURCE_SESSION_CHANGED, False, observed, gap, after)
            if not self._reuse_logged:
                self._reuse_logged = True
                # First reuse per attested session only; later stages of the same session stay quiet.
                logger.info(
                    "[identity] source=%s %s gap=%s: a transient non-positive probe reused the attested session",
                    SOURCE_SAME_SESSION, attested.describe(), gap,
                )
            return IdentityDecision(SOURCE_SAME_SESSION, True, observed, gap, attested)

    def _establish_locked(self, before: OwnedWebUISession | None, after: OwnedWebUISession | None) -> None:
        """A real positive Forge probe may attest the owned session it ran against, and only that session."""

        usable = (
            before is not None
            and after is not None
            and before.same_launch(after)  # a probe that straddled a restart proves nothing about either session
            and after.declared_identity == FORGE_WEBUI_IDENTITY
        )
        if not usable:
            if self._attested is not None and (after is None or not self._attested.same_launch(after)):
                self._drop_locked("a live Forge classification arrived for a different or unowned session")
            return
        if self._attested is not None and self._attested.same_launch(after):
            return
        self._drop_locked("a new owned session was positively classified")
        self._attested = after
        logger.info("[identity] Forge positively classified; attested owned session %s", after.describe())


def verify_backend_runtime_identity(
    backend_id: str,
    client: Any,
    attestor: ManagedWebUIIdentityAttestor,
    record: Callable[[IdentityDecision], None] | None = None,
) -> IdentityDecision:
    """Reject a backend/endpoint pairing before any generation dispatch; return why the stage was allowed.

    ``forge_webui``: a live positive Forge, or the exact-session attestation across a transient ``unknown``.
    Any other backend keeps :func:`assert_runtime_matches_backend` exactly (A1111 tolerates an unclassifiable
    endpoint and rejects a positively identified Forge); its observation only ever *invalidates* attestation.
    """

    endpoint = getattr(client, "base_url", None)
    before = attestor.current_session(endpoint)
    observed = classify_client_runtime(client)
    after = attestor.current_session(endpoint)
    decision = attestor.decide(backend_id, observed, before, after)
    if backend_id == FORGE_WEBUI_IDENTITY and _settle_eligible(attestor, decision, after):
        decision = _settle_initial_identity(client, attestor, decision, after)
    if record is not None:
        record(decision)  # before any raise, so a rejection is diagnosable too
    if backend_id != FORGE_WEBUI_IDENTITY:
        assert_runtime_matches_backend(backend_id, observed)
        return decision
    if not decision.allowed:
        raise WebUIRuntimeIdentityMismatch(backend_id, decision.observed, detail=decision.describe())
    return decision


def _settle_eligible(
    attestor: ManagedWebUIIdentityAttestor, decision: IdentityDecision, anchor: OwnedWebUISession | None
) -> bool:
    """Whether a refused Forge stage may wait for the first real positive proof of this exact owned session.

    Every condition is a current fact: an owned live session serving the client endpoint (``anchor`` is only ever
    produced for that), declared ``forge_webui``, no valid attestation, a non-positive probe, and missing evidence
    rather than contradiction. External/unowned endpoints have no ``anchor`` and therefore never settle.
    """

    return (
        anchor is not None
        and anchor.declared_identity == FORGE_WEBUI_IDENTITY
        and not decision.allowed
        and decision.source in (SOURCE_NO_ATTESTATION, SOURCE_SESSION_CHANGED)  # a dropped proof leaves none
        and decision.observed.identity == UNKNOWN_WEBUI_IDENTITY
        and decision.gap in SETTLE_GAPS
        and attestor.attested_session() is None
    )


def _settle_initial_identity(
    client: Any,
    attestor: ManagedWebUIIdentityAttestor,
    first: IdentityDecision,
    anchor: OwnedWebUISession,
) -> IdentityDecision:
    """Wait, bounded, for the first positive Forge classification of ``anchor`` (never after one exists).

    Before EVERY further probe the session facts are re-read; any change in manager, process, PID, endpoint,
    readiness epoch, ownership or liveness aborts at once. Positive contradiction ends it at once. Only a real positive
    classification can end it successfully; exhausting the bound leaves the original refusal in place. No generation
    endpoint and none of the HTTP retry machinery is involved: it re-runs the same read-only identity probe.
    """

    endpoint = getattr(client, "base_url", None)
    clock = attestor._clock
    started = clock()
    deadline = started + attestor._settle_seconds
    attempts, gap, final = 1, first.gap, first
    logger.info("[identity] initial_identity_settle begin: %s bound=%.1fs", anchor.describe(), attestor._settle_seconds)

    def finish(outcome: str, decision: IdentityDecision) -> IdentityDecision:
        report = IdentitySettleReport(outcome, attempts, max(0.0, clock() - started), attestor._settle_seconds, gap)
        logger.info("[identity] %s %s", report.describe(), anchor.describe())
        return replace(decision, settle=report)

    while True:
        now = clock()
        if now >= deadline:
            return finish(SETTLE_TIMEOUT, final)
        attestor._sleeper(min(attestor._poll_seconds, deadline - now))
        before = attestor.current_session(endpoint)
        if before is None or not anchor.same_launch(before):
            attestor.invalidate("the owned runtime session changed during the initial identity settle")
            return finish(SETTLE_SESSION_CHANGED, replace(final, source=SOURCE_SESSION_CHANGED, session=before))
        observed = classify_client_runtime(client)
        attempts += 1
        after = attestor.current_session(endpoint)
        gap = identity_gap(observed)
        if after is None or not anchor.same_launch(after):
            attestor.invalidate("the owned runtime session changed during the initial identity settle")
            return finish(
                SETTLE_SESSION_CHANGED,
                replace(final, source=SOURCE_SESSION_CHANGED, observed=observed, gap=gap, session=after),
            )
        decision = attestor.decide(FORGE_WEBUI_IDENTITY, observed, before, after)
        if decision.allowed:
            return finish(SETTLE_ESTABLISHED, decision)
        if decision.source == SOURCE_CONTRADICTORY:
            return finish(SETTLE_CONTRADICTION, decision)
        if gap not in SETTLE_GAPS:
            return finish(SETTLE_STOPPED, decision)
        final = replace(first, observed=decision.observed, gap=gap)  # the original refusal, with the latest evidence


_DEFAULT_ATTESTOR = ManagedWebUIIdentityAttestor()


def default_attestor() -> ManagedWebUIIdentityAttestor:
    """The process-local attestor bound to the global ``WebUIProcessManager`` (one WebUI-family slot)."""

    return _DEFAULT_ATTESTOR


__all__ = [
    "IdentityDecision",
    "IdentitySettleReport",
    "INITIAL_IDENTITY_POLL_SECONDS",
    "INITIAL_IDENTITY_SETTLE_SECONDS",
    "SETTLE_CONTRADICTION",
    "SETTLE_ESTABLISHED",
    "SETTLE_SESSION_CHANGED",
    "SETTLE_STOPPED",
    "SETTLE_TIMEOUT",
    "ManagedWebUIIdentityAttestor",
    "OwnedWebUISession",
    "SOURCE_CONTRADICTORY",
    "SOURCE_LIVE_POSITIVE",
    "SOURCE_NOT_APPLICABLE",
    "SOURCE_NO_ATTESTATION",
    "SOURCE_SAME_SESSION",
    "SOURCE_SESSION_CHANGED",
    "default_attestor",
    "identity_gap",
    "verify_backend_runtime_identity",
]
