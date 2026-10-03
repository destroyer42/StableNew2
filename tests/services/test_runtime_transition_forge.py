"""PR-IMG-FORGE-100: A1111/Forge occupy one WebUI-family slot; transition policy (fakes only).

One ``WebUIProcessManager`` owns the slot and declares which identity it launched. StableNew only
ever releases a process it owns, through that manager's own ``stop_webui``; external A1111, Forge
and Comfy are immutable; unknown ownership causes no mutation.
"""

from __future__ import annotations

from src.services.runtime_transition_service import (
    KNOWN_TRANSITION_TARGETS,
    RUNTIME_A1111_WEBUI,
    RUNTIME_COMFY,
    RUNTIME_FORGE_WEBUI,
    RUNTIME_SVD_NATIVE,
    RuntimeOwnershipState,
    RuntimeTransitionCoordinator,
    RuntimeTransitionStatus,
)


class _WebUIManager:
    """Stands in for the single WebUIProcessManager (ownership + declared identity)."""

    def __init__(
        self, *, identity: str, running: bool = True, owned: bool = True, stops: bool = True
    ) -> None:
        self.runtime_identity = identity
        self._running = running
        self.owns_process = owned
        self._stops = stops
        self.stop_calls = 0

    def is_running(self) -> bool:
        return self._running

    def stop_webui(self) -> bool:
        self.stop_calls += 1
        if self._stops:
            self._running = False
            self.owns_process = False
        return self._stops


class _ComfyManager:
    def __init__(self, *, running: bool = True, owned: bool = True) -> None:
        self._running = running
        self.owns_process = owned
        self.stop_calls = 0

    def is_running(self) -> bool:
        return self._running

    def stop(self) -> bool:
        self.stop_calls += 1
        self._running = False
        self.owns_process = False
        return True


class _SVD:
    def __init__(self) -> None:
        self.clear_calls = 0

    def clear_model_cache(self) -> None:
        self.clear_calls += 1


class _Probe:
    """Counts identity probes so tests can prove it is consulted only for an occupied endpoint."""

    def __init__(self, identity: str = "unknown") -> None:
        self.identity = identity
        self.calls = 0

    def __call__(self) -> str:
        self.calls += 1
        return self.identity


def _coordinator(
    *,
    webui: object | None = None,
    comfy: object | None = None,
    svd: object | None = None,
    webui_present: bool = False,
    webui_identity: str = "unknown",
    comfy_present: bool = False,
    probe: _Probe | None = None,
) -> tuple[RuntimeTransitionCoordinator, _Probe]:
    probe = probe or _Probe(webui_identity)
    return (
        RuntimeTransitionCoordinator(
            webui_manager_getter=lambda: webui,
            comfy_manager_getter=lambda: comfy,
            svd_service_factory=lambda: svd or _SVD(),
            webui_endpoint_present=lambda: webui_present,
            webui_endpoint_identity=probe,
            comfy_endpoint_present=lambda: comfy_present,
        ),
        probe,
    )


def test_forge_is_a_known_distinct_transition_target() -> None:
    assert RUNTIME_FORGE_WEBUI == "forge_webui" != RUNTIME_A1111_WEBUI
    assert RUNTIME_FORGE_WEBUI in KNOWN_TRANSITION_TARGETS


# --------------------------------------------------------------------------------------------
# Owned runtimes: the other identity in the shared slot is released through its own manager
# --------------------------------------------------------------------------------------------


def test_target_forge_releases_owned_a1111_owned_comfy_and_clears_svd() -> None:
    a1111 = _WebUIManager(identity=RUNTIME_A1111_WEBUI)
    comfy = _ComfyManager()
    svd = _SVD()
    coordinator, probe = _coordinator(webui=a1111, comfy=comfy, svd=svd)

    result = coordinator.prepare_for(RUNTIME_FORGE_WEBUI)

    assert result.ready
    assert a1111.stop_calls == 1 and comfy.stop_calls == 1 and svd.clear_calls == 1
    assert result.ownership_state[RUNTIME_A1111_WEBUI] is RuntimeOwnershipState.OWNED
    assert RUNTIME_FORGE_WEBUI not in result.ownership_state  # the target is never "released"
    assert set(result.releases_completed) >= {RUNTIME_A1111_WEBUI, RUNTIME_COMFY}
    assert probe.calls == 0  # an owned slot is classified by the manager, never by probing


def test_target_a1111_releases_owned_forge_owned_comfy_and_clears_svd() -> None:
    forge = _WebUIManager(identity=RUNTIME_FORGE_WEBUI)
    comfy = _ComfyManager()
    svd = _SVD()
    coordinator, _ = _coordinator(webui=forge, comfy=comfy, svd=svd)

    result = coordinator.prepare_for(RUNTIME_A1111_WEBUI)

    assert result.ready
    assert forge.stop_calls == 1 and comfy.stop_calls == 1 and svd.clear_calls == 1
    assert result.ownership_state[RUNTIME_FORGE_WEBUI] is RuntimeOwnershipState.OWNED
    assert RUNTIME_FORGE_WEBUI in result.releases_completed


def test_owned_runtime_already_holding_the_target_identity_is_never_stopped() -> None:
    for identity, target in (
        (RUNTIME_FORGE_WEBUI, RUNTIME_FORGE_WEBUI),
        (RUNTIME_A1111_WEBUI, RUNTIME_A1111_WEBUI),
    ):
        manager = _WebUIManager(identity=identity)
        result = _coordinator(webui=manager)[0].prepare_for(target)
        assert result.ready
        assert manager.stop_calls == 0
        assert manager.is_running()


def test_a_manager_without_a_declared_identity_is_the_legacy_a1111() -> None:
    legacy = _WebUIManager(identity="")  # no usable declaration
    result = _coordinator(webui=legacy)[0].prepare_for(RUNTIME_FORGE_WEBUI)
    assert result.ready and legacy.stop_calls == 1  # legacy A1111 released for Forge


def test_failed_release_of_the_owned_other_identity_is_reported_not_retried() -> None:
    stuck = _WebUIManager(identity=RUNTIME_A1111_WEBUI, stops=False)
    result = _coordinator(webui=stuck)[0].prepare_for(RUNTIME_FORGE_WEBUI)
    assert result.status is RuntimeTransitionStatus.RELEASE_FAILED
    assert stuck.stop_calls == 1
    assert any("did not stop" in blocker for blocker in result.blockers)


# --------------------------------------------------------------------------------------------
# External runtimes are immutable: used when they are the target, ACTION_REQUIRED when they conflict
# --------------------------------------------------------------------------------------------


def test_external_forge_is_used_by_a_forge_job_and_blocks_an_a1111_job() -> None:
    external = _WebUIManager(identity=RUNTIME_A1111_WEBUI, running=True, owned=False)
    used, probe = _coordinator(
        webui=external, webui_present=True, webui_identity=RUNTIME_FORGE_WEBUI
    )
    assert used.prepare_for(RUNTIME_FORGE_WEBUI).ready
    assert probe.calls == 1

    blocked = _coordinator(webui=external, webui_present=True, webui_identity=RUNTIME_FORGE_WEBUI)[
        0
    ].prepare_for(RUNTIME_A1111_WEBUI)
    assert blocked.status is RuntimeTransitionStatus.ACTION_REQUIRED
    assert blocked.ownership_state[RUNTIME_FORGE_WEBUI] is RuntimeOwnershipState.EXTERNAL
    assert any("will not adopt, stop, or restart" in b for b in blocked.blockers)
    assert external.stop_calls == 0


def test_external_a1111_is_used_by_an_a1111_job_and_blocks_a_forge_job() -> None:
    used = _coordinator(webui_present=True, webui_identity=RUNTIME_A1111_WEBUI)[0]
    assert used.prepare_for(RUNTIME_A1111_WEBUI).ready

    external = _WebUIManager(identity=RUNTIME_A1111_WEBUI, running=False, owned=False)
    blocked = _coordinator(webui=external, webui_present=True, webui_identity=RUNTIME_A1111_WEBUI)[
        0
    ].prepare_for(RUNTIME_FORGE_WEBUI)
    assert blocked.status is RuntimeTransitionStatus.ACTION_REQUIRED
    assert blocked.ownership_state[RUNTIME_A1111_WEBUI] is RuntimeOwnershipState.EXTERNAL
    assert external.stop_calls == 0


def test_unclassifiable_external_endpoint_is_tolerated_for_a1111_but_blocks_forge() -> None:
    a1111_job, _ = _coordinator(webui_present=True, webui_identity="unknown")
    assert a1111_job.prepare_for(RUNTIME_A1111_WEBUI).ready  # A1111-family forks keep working

    forge_job, _ = _coordinator(webui_present=True, webui_identity="unknown")
    result = forge_job.prepare_for(RUNTIME_FORGE_WEBUI)
    assert result.status is RuntimeTransitionStatus.ACTION_REQUIRED
    assert any("not positively Forge" in blocker for blocker in result.blockers)


def test_a_failing_identity_probe_is_unknown_and_never_mutates() -> None:
    def boom() -> str:
        raise OSError("probe failed")

    external = _WebUIManager(identity=RUNTIME_A1111_WEBUI, running=True, owned=False)
    coordinator = RuntimeTransitionCoordinator(
        webui_manager_getter=lambda: external,
        comfy_manager_getter=lambda: None,
        svd_service_factory=_SVD,
        webui_endpoint_present=lambda: True,
        webui_endpoint_identity=boom,
        comfy_endpoint_present=lambda: False,
    )
    assert coordinator.prepare_for(RUNTIME_FORGE_WEBUI).status is (
        RuntimeTransitionStatus.ACTION_REQUIRED
    )
    assert external.stop_calls == 0


def test_unverifiable_manager_state_blocks_without_any_mutation() -> None:
    class Broken:
        owns_process = True
        stop_calls = 0

        def is_running(self) -> bool:
            raise RuntimeError("handle lost")

        def stop_webui(self) -> bool:
            Broken.stop_calls += 1
            return True

    result = _coordinator(webui=Broken())[0].prepare_for(RUNTIME_FORGE_WEBUI)
    assert result.status is RuntimeTransitionStatus.ACTION_REQUIRED
    assert Broken.stop_calls == 0


def test_free_endpoint_means_no_conflict_and_the_identity_probe_is_never_called() -> None:
    for target in (RUNTIME_A1111_WEBUI, RUNTIME_FORGE_WEBUI):
        coordinator, probe = _coordinator(webui_present=False)
        result = coordinator.prepare_for(target)
        assert result.ready
        assert probe.calls == 0


def test_external_comfy_blocks_both_webui_targets_and_is_never_stopped() -> None:
    for target in (RUNTIME_A1111_WEBUI, RUNTIME_FORGE_WEBUI):
        comfy = _ComfyManager(running=True, owned=False)
        result = _coordinator(comfy=comfy)[0].prepare_for(target)
        assert result.status is RuntimeTransitionStatus.ACTION_REQUIRED
        assert result.ownership_state[RUNTIME_COMFY] is RuntimeOwnershipState.EXTERNAL
        assert comfy.stop_calls == 0


# --------------------------------------------------------------------------------------------
# Comfy / SVD targets release whichever WebUI-family runtime StableNew owns
# --------------------------------------------------------------------------------------------


def test_comfy_and_svd_targets_release_an_owned_slot_whichever_identity_it_holds() -> None:
    for identity in (RUNTIME_A1111_WEBUI, RUNTIME_FORGE_WEBUI):
        for target in (RUNTIME_COMFY, RUNTIME_SVD_NATIVE):
            manager = _WebUIManager(identity=identity)
            svd = _SVD()
            result = _coordinator(webui=manager, comfy=_ComfyManager(), svd=svd)[0].prepare_for(
                target
            )
            assert result.ready
            assert manager.stop_calls == 1
            assert svd.clear_calls == (0 if target == RUNTIME_SVD_NATIVE else 1)


def test_comfy_and_svd_targets_never_stop_an_external_forge_or_a1111() -> None:
    for identity in ("forge_webui", "a1111_webui"):
        for target in (RUNTIME_COMFY, RUNTIME_SVD_NATIVE):
            external = _WebUIManager(identity=identity, running=True, owned=False)
            result = _coordinator(webui=external)[0].prepare_for(target)
            assert result.status is RuntimeTransitionStatus.ACTION_REQUIRED
            assert external.stop_calls == 0

            no_manager = _coordinator(webui_present=True, webui_identity=identity)[0]
            assert no_manager.prepare_for(target).status is RuntimeTransitionStatus.ACTION_REQUIRED
