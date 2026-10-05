"""PR-RUNTIME-100: coordinate release of conflicting StableNew-owned GPU runtimes.

This is a narrow coordination layer, not a second lifecycle authority. It delegates every
release operation to the runtime's own existing owner and never persists state of its own:

- ``WebUIProcessManager`` (via ``get_global_webui_process_manager``) remains the sole authority
  over managed A1111 lifecycle; ``stop_webui()`` is the only release boundary used here.
- ``ComfyProcessManager`` (via ``get_global_comfy_process_manager``) remains the sole authority
  over managed Comfy lifecycle; ``stop()`` is the only release boundary used here.
- ``SVDService`` remains the sole authority over the native SVD pipeline cache;
  ``clear_model_cache()`` is the only release boundary used here.

An **external or ambiguous** runtime (one this session did not launch, including a live configured
endpoint without a manager process handle) is never adopted, stopped or restarted. When one blocks
readiness for the requested target, this service reports ``ACTION_REQUIRED`` with operator
guidance and takes no OS action; it does not wait for the external process to disappear.

Target runtime identities are StableNew execution runtimes, never model names:
``RUNTIME_A1111_WEBUI``, ``RUNTIME_FORGE_WEBUI``, ``RUNTIME_COMFY``, ``RUNTIME_SVD_NATIVE``.

A1111 and Forge are two identities occupying ONE WebUI-family runtime slot (one configured endpoint,
one ``WebUIProcessManager``); there is no second managed owner. The manager declares which identity
it launched (``runtime_identity``); an external endpoint's identity is observed read-only through
``webui_runtime_identity`` (endpoint evidence, never process or folder names).

Target-driven release policy (product decision, see the PR-RUNTIME-100 record):

============  ==========================================================
target        conflicting residencies released
============  ==========================================================
a1111_webui   owned Forge (if the slot holds one), owned Comfy, SVD cache
forge_webui   owned A1111 (if the slot holds one), owned Comfy, SVD cache
comfy         whichever owned WebUI-family runtime, SVD cache
svd_native    whichever owned WebUI-family runtime, owned Comfy
============  ==========================================================

External runtimes are immutable: a target external runtime is simply used; a *conflicting* external
runtime (including an external Forge/A1111 occupying the slot of the other identity, or an
endpoint that cannot be positively identified when the target is Forge) yields ``ACTION_REQUIRED``;
unknown ownership causes no mutation.

Nothing is restarted afterward: the target backend's own existing owner remains responsible for
starting/loading what it needs (``WebUIProcessManager.ensure_running``, the Comfy backend's own
``_ensure_runtime_ready``, ``SVDService``/``SVDRunner`` loading a pipeline). This service only
clears the way; the resource-readiness guards that already exist per workflow (for example the
Wan2.2 10,000 MiB / 16 GB floors in ``src/video/workflow_readiness.py``) remain the authoritative
check for whether the target itself may proceed, and are unchanged and uncalled by this module.

Safety: this is called once, synchronously, from inside a single admitted job's backend
``execute()``. ``PipelineRunner``/``JobService`` already serialize job execution (one job runs at
a time), so there is no separate busy/idle authority to invent here; this service never touches
the queue, SQLite, NJRs or replay, and a failed release simply raises before generation dispatch
(no retry, no replay, no fallback to another backend).

This service does not diagnose or attempt to fix the workstation's pre-existing hard GPU
resets/black-screen failures (see PR-VID-110 section 9); it only removes StableNew-owned runtime
contention that was otherwise being resolved by asking the operator to close their own tools.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

RUNTIME_A1111_WEBUI = "a1111_webui"
RUNTIME_FORGE_WEBUI = "forge_webui"
RUNTIME_COMFY = "comfy"
RUNTIME_SVD_NATIVE = "svd_native"
_SVD_CACHE_RUNTIME = "svd_native_cache"

KNOWN_TRANSITION_TARGETS = frozenset(
    {RUNTIME_A1111_WEBUI, RUNTIME_FORGE_WEBUI, RUNTIME_COMFY, RUNTIME_SVD_NATIVE}
)

# The WebUI-family slot is shared by these two identities (one managed owner, one endpoint).
_WEBUI_FAMILY = (RUNTIME_A1111_WEBUI, RUNTIME_FORGE_WEBUI)
_OTHER_WEBUI_IDENTITY = {
    RUNTIME_A1111_WEBUI: RUNTIME_FORGE_WEBUI,
    RUNTIME_FORGE_WEBUI: RUNTIME_A1111_WEBUI,
}

# target -> managed process runtimes it must release before dispatch (SVD cache release is
# separate: every non-SVD target also clears it, see prepare_for).  For the WebUI-family targets the
# listed WebUI id is the *other* identity in the shared slot; for comfy/svd_native the A1111 entry
# stands for whichever WebUI-family runtime StableNew owns.
_CONFLICTING_MANAGED_RUNTIMES: dict[str, tuple[str, ...]] = {
    RUNTIME_A1111_WEBUI: (RUNTIME_COMFY, RUNTIME_FORGE_WEBUI),
    RUNTIME_FORGE_WEBUI: (RUNTIME_COMFY, RUNTIME_A1111_WEBUI),
    RUNTIME_COMFY: (RUNTIME_A1111_WEBUI,),
    RUNTIME_SVD_NATIVE: (RUNTIME_A1111_WEBUI, RUNTIME_COMFY),
}


class RuntimeOwnershipState(str, Enum):
    ABSENT = "absent"  # no manager, or manager has never launched a process
    NOT_RUNNING = "not_running"  # manager exists but the process is not currently alive
    OWNED = "owned"  # StableNew launched and still owns this live process
    EXTERNAL = "external"  # a live process this session did not launch (immutable)


class RuntimeTransitionStatus(str, Enum):
    READY = "ready"  # no blocker; target may proceed to its own readiness/start
    ACTION_REQUIRED = "action_required"  # an external runtime blocks; operator must act
    RELEASE_FAILED = "release_failed"  # an owned runtime failed to release


@dataclass(frozen=True)
class RuntimeTransitionResult:
    target: str
    conflicts_observed: tuple[str, ...]
    ownership_state: dict[str, RuntimeOwnershipState]
    releases_attempted: tuple[str, ...]
    releases_completed: tuple[str, ...]
    status: RuntimeTransitionStatus
    blockers: tuple[str, ...] = ()

    @property
    def ready(self) -> bool:
        return self.status is RuntimeTransitionStatus.READY

    def to_dict(self) -> dict[str, Any]:
        return {
            "target": self.target,
            "conflicts_observed": list(self.conflicts_observed),
            "ownership_state": {k: v.value for k, v in self.ownership_state.items()},
            "releases_attempted": list(self.releases_attempted),
            "releases_completed": list(self.releases_completed),
            "status": self.status.value,
            "blockers": list(self.blockers),
        }


class RuntimeTransitionError(RuntimeError):
    """Raised by a backend when ``prepare_for`` did not reach READY; carries the full result."""

    def __init__(self, result: RuntimeTransitionResult) -> None:
        message = (
            f"Runtime transition to '{result.target}' is not ready "
            f"({result.status.value}): {'; '.join(result.blockers) or 'no detail available'}"
        )
        super().__init__(message)
        self.result = result


def _managed_webui_identity(manager: Any) -> str:
    """Identity the single WebUI manager launched; missing/unknown means the legacy A1111."""

    declared = str(getattr(manager, "runtime_identity", "") or "")
    return declared if declared in _WEBUI_FAMILY else RUNTIME_A1111_WEBUI


def _default_webui_manager() -> Any:
    from src.api.webui_process_manager import get_global_webui_process_manager

    return get_global_webui_process_manager()


def _default_comfy_manager() -> Any:
    from src.video.comfy_process_manager import get_global_comfy_process_manager

    return get_global_comfy_process_manager()


def _default_svd_service() -> Any:
    from src.video.svd_service import SVDService

    return SVDService()


def _load_settings_mapping() -> Any:
    """The settings backend/endpoint selection reads; unreadable settings fail closed (no endpoint is guessed)."""

    from src.api.webui_runtime_identity import load_backend_settings

    return load_backend_settings()


def _configured_endpoint(setting_name: str, environment_name: str, default: str) -> str:
    """Read one existing configured endpoint without constructing or starting a manager."""

    import os

    from src.utils.config import ConfigManager

    settings = ConfigManager().load_settings()
    return str(settings.get(setting_name) or "").strip() or os.environ.get(environment_name, default)


def _default_webui_endpoint_presence() -> bool:
    """Observe only the configured WebUI endpoint; never discover or mutate processes."""

    from src.api.healthcheck import probe_webui_endpoint
    from src.api.webui_runtime_identity import resolve_effective_webui_base_url

    base_url = resolve_effective_webui_base_url(_load_settings_mapping())
    return probe_webui_endpoint(base_url, timeout=0.5) != "free"


def _default_webui_endpoint_identity() -> str:
    """Read-only identity of the configured WebUI endpoint; called only when it is occupied."""

    from src.api.webui_runtime_identity import (
        probe_endpoint_runtime_identity,
        resolve_effective_webui_base_url,
    )

    base_url = resolve_effective_webui_base_url(_load_settings_mapping())
    return probe_endpoint_runtime_identity(base_url).identity


def _default_comfy_endpoint_presence() -> bool:
    """Observe only the configured Comfy endpoint; never discover or mutate processes."""

    from src.video.comfy_healthcheck import probe_comfy_endpoint

    base_url = _configured_endpoint(
        "comfy_base_url", "STABLENEW_COMFY_BASE_URL", "http://127.0.0.1:8188"
    )
    return probe_comfy_endpoint(base_url, timeout=0.5) != "free"


@dataclass
class RuntimeTransitionCoordinator:
    """Delegates every release to the runtime's existing owner; owns no lifecycle state itself."""

    webui_manager_getter: Callable[[], Any] = field(default=_default_webui_manager)
    comfy_manager_getter: Callable[[], Any] = field(default=_default_comfy_manager)
    svd_service_factory: Callable[[], Any] = field(default=_default_svd_service)
    webui_endpoint_present: Callable[[], bool] = field(default=_default_webui_endpoint_presence)
    webui_endpoint_identity: Callable[[], str] = field(default=_default_webui_endpoint_identity)
    comfy_endpoint_present: Callable[[], bool] = field(default=_default_comfy_endpoint_presence)

    def prepare_for(self, target: str) -> RuntimeTransitionResult:
        """Release conflicting StableNew-owned runtime residency ahead of dispatching ``target``.

        Never raises: callers (backends) decide whether a non-READY result should block
        dispatch, by raising ``RuntimeTransitionError`` themselves.
        """

        if target not in KNOWN_TRANSITION_TARGETS:
            raise ValueError(f"Unknown runtime transition target '{target}'")

        conflicts = list(_CONFLICTING_MANAGED_RUNTIMES[target])
        ownership: dict[str, RuntimeOwnershipState] = {}
        attempted: list[str] = []
        completed: list[str] = []
        blockers: list[str] = []
        failed = False

        for runtime_id in conflicts:
            if target in _WEBUI_FAMILY and runtime_id in _WEBUI_FAMILY:
                state, attempted_this, completed_this, blocker = self._release_other_webui_identity(
                    target, runtime_id
                )
            else:
                state, attempted_this, completed_this, blocker = self._release_managed_runtime(
                    runtime_id
                )
            ownership[runtime_id] = state
            attempted.extend(attempted_this)
            completed.extend(completed_this)
            if blocker:
                blockers.append(blocker)
                if state is RuntimeOwnershipState.OWNED:
                    failed = True  # an owned release did not complete

        if target != RUNTIME_SVD_NATIVE:
            ownership[_SVD_CACHE_RUNTIME], svd_blocker = self._release_svd_cache()
            attempted.append(_SVD_CACHE_RUNTIME)
            if svd_blocker:
                blockers.append(svd_blocker)
                failed = True
            else:
                completed.append(_SVD_CACHE_RUNTIME)
            conflicts.append(_SVD_CACHE_RUNTIME)

        if failed:
            status = RuntimeTransitionStatus.RELEASE_FAILED
        elif any(state is RuntimeOwnershipState.EXTERNAL for state in ownership.values()):
            status = RuntimeTransitionStatus.ACTION_REQUIRED
        else:
            status = RuntimeTransitionStatus.READY

        return RuntimeTransitionResult(
            target=target,
            conflicts_observed=tuple(conflicts),
            ownership_state=ownership,
            releases_attempted=tuple(attempted),
            releases_completed=tuple(completed),
            status=status,
            blockers=tuple(blockers),
        )

    def _release_other_webui_identity(
        self, target: str, other: str
    ) -> tuple[RuntimeOwnershipState, list[str], list[str], str | None]:
        """Clear the shared WebUI-family slot of the *other* identity ahead of ``target``.

        Only a process StableNew owns (the existing ``WebUIProcessManager`` declares which identity
        it launched) is ever released, through that manager's own ``stop_webui``. An external
        endpoint is classified read-only: the target identity is simply used, the other identity
        needs operator action, and an unclassifiable endpoint is tolerated for A1111 (existing
        A1111-family fork compatibility) but is a blocker for Forge. Never adopts or stops an
        external process.
        """

        manager = self.webui_manager_getter()
        if manager is not None:
            try:
                running = bool(manager.is_running())
                owns = bool(getattr(manager, "owns_process", False))
            except Exception as exc:  # noqa: BLE001 - a broken probe blocks, it does not mutate
                return (
                    RuntimeOwnershipState.EXTERNAL,
                    [],
                    [],
                    f"{other}: could not verify runtime state ({type(exc).__name__}: {exc})",
                )
            if running and owns:
                occupant = _managed_webui_identity(manager)
                if occupant != other:
                    # StableNew owns the slot and it already holds the target identity.
                    return RuntimeOwnershipState.ABSENT, [], [], None
                try:
                    manager.stop_webui()
                    released = not bool(manager.is_running())
                except Exception as exc:  # noqa: BLE001 - report, never mutate further
                    return (
                        RuntimeOwnershipState.OWNED,
                        [other],
                        [],
                        f"{other}: release raised {type(exc).__name__}: {exc}",
                    )
                if not released:
                    return (
                        RuntimeOwnershipState.OWNED,
                        [other],
                        [],
                        f"{other}: StableNew-owned process did not stop within its own shutdown "
                        "bound",
                    )
                return RuntimeOwnershipState.OWNED, [other], [other], None
        try:
            present = bool(self.webui_endpoint_present())
        except Exception as exc:  # noqa: BLE001 - failed observation is ambiguous, never mutable
            return (
                RuntimeOwnershipState.EXTERNAL,
                [],
                [],
                f"{other}: could not verify configured endpoint ({type(exc).__name__}: {exc}); "
                "treating it as external/ambiguous and taking no action.",
            )
        if not present:
            return (
                RuntimeOwnershipState.ABSENT
                if manager is None
                else RuntimeOwnershipState.NOT_RUNNING
            ), [], [], None
        try:
            observed = str(self.webui_endpoint_identity() or "")
        except Exception:  # noqa: BLE001 - an unreadable identity is simply unknown
            observed = ""
        if observed == target:
            return RuntimeOwnershipState.ABSENT, [], [], None
        if observed == other or target == RUNTIME_FORGE_WEBUI:
            described = other if observed == other else "an external WebUI that is not positively Forge"
            return (
                RuntimeOwnershipState.EXTERNAL,
                [],
                [],
                f"{other}: {described} occupies the configured WebUI endpoint, but this job "
                f"targets {target}. StableNew did not launch it and will not adopt, stop, or "
                "restart it; close it yourself (or point StableNew at the correct runtime) "
                "before this job can proceed.",
            )
        # target a1111_webui + an endpoint that cannot be classified as Forge: tolerated.
        return RuntimeOwnershipState.ABSENT, [], [], None

    def _release_managed_runtime(
        self, runtime_id: str
    ) -> tuple[RuntimeOwnershipState, list[str], list[str], str | None]:
        manager = self._get_manager(runtime_id)
        if manager is None:
            return self._classify_unmanaged_endpoint(runtime_id, absent=True)
        try:
            is_running = bool(manager.is_running())
        except Exception as exc:  # noqa: BLE001 - a broken probe blocks, it does not mutate
            return (
                RuntimeOwnershipState.EXTERNAL,
                [],
                [],
                f"{runtime_id}: could not verify runtime state ({type(exc).__name__}: {exc})",
            )
        if not is_running:
            return self._classify_unmanaged_endpoint(runtime_id, absent=False)
        owns_process = bool(getattr(manager, "owns_process", False))
        if not owns_process:
            return (
                RuntimeOwnershipState.EXTERNAL,
                [],
                [],
                f"{runtime_id}: an external/ambiguous process is running and holding resources. "
                f"StableNew did not launch it and will not stop it; close it yourself (or free "
                f"its resources) before this job can proceed.",
            )
        try:
            self._stop_managed_runtime(runtime_id, manager)
            released = not bool(manager.is_running())
        except Exception as exc:  # noqa: BLE001 - report, never mutate further
            return (
                RuntimeOwnershipState.OWNED,
                [runtime_id],
                [],
                f"{runtime_id}: release raised {type(exc).__name__}: {exc}",
            )
        if not released:
            return (
                RuntimeOwnershipState.OWNED,
                [runtime_id],
                [],
                f"{runtime_id}: StableNew-owned process did not stop within its own shutdown bound",
            )
        return RuntimeOwnershipState.OWNED, [runtime_id], [runtime_id], None

    def _classify_unmanaged_endpoint(
        self, runtime_id: str, *, absent: bool
    ) -> tuple[RuntimeOwnershipState, list[str], list[str], str | None]:
        """Treat a live configured endpoint without ownership as immutable external state."""

        try:
            endpoint_present = self._endpoint_present(runtime_id)
        except Exception as exc:  # noqa: BLE001 - failed observation is ambiguous, never mutable
            return (
                RuntimeOwnershipState.EXTERNAL,
                [],
                [],
                f"{runtime_id}: could not verify configured endpoint ({type(exc).__name__}: {exc}); "
                "treating it as external/ambiguous and taking no action.",
            )
        if endpoint_present:
            return (
                RuntimeOwnershipState.EXTERNAL,
                [],
                [],
                f"{runtime_id}: configured endpoint is live or occupied without StableNew ownership. "
                "StableNew will not adopt, stop, or restart it; close it yourself (or free its "
                "resources) before this job can proceed.",
            )
        return (RuntimeOwnershipState.ABSENT if absent else RuntimeOwnershipState.NOT_RUNNING), [], [], None

    def _get_manager(self, runtime_id: str) -> Any:
        if runtime_id == RUNTIME_A1111_WEBUI:
            return self.webui_manager_getter()
        if runtime_id == RUNTIME_COMFY:
            return self.comfy_manager_getter()
        raise ValueError(f"'{runtime_id}' has no managed-process owner")

    def _endpoint_present(self, runtime_id: str) -> bool:
        if runtime_id == RUNTIME_A1111_WEBUI:
            return bool(self.webui_endpoint_present())
        if runtime_id == RUNTIME_COMFY:
            return bool(self.comfy_endpoint_present())
        raise ValueError(f"'{runtime_id}' has no configured endpoint")

    @staticmethod
    def _stop_managed_runtime(runtime_id: str, manager: Any) -> None:
        # Each owner's own release boundary; no duplicated shutdown logic.
        if runtime_id == RUNTIME_A1111_WEBUI:
            manager.stop_webui()
        else:
            manager.stop()

    def _release_svd_cache(self) -> tuple[RuntimeOwnershipState, str | None]:
        try:
            service = self.svd_service_factory()
            service.clear_model_cache()
        except Exception as exc:  # noqa: BLE001 - report, do not mutate anything else
            return (
                RuntimeOwnershipState.OWNED,
                f"{_SVD_CACHE_RUNTIME}: release raised {type(exc).__name__}: {exc}",
            )
        return RuntimeOwnershipState.OWNED, None


__all__ = [
    "KNOWN_TRANSITION_TARGETS",
    "RUNTIME_A1111_WEBUI",
    "RUNTIME_COMFY",
    "RUNTIME_FORGE_WEBUI",
    "RUNTIME_SVD_NATIVE",
    "RuntimeOwnershipState",
    "RuntimeTransitionCoordinator",
    "RuntimeTransitionError",
    "RuntimeTransitionResult",
    "RuntimeTransitionStatus",
]
