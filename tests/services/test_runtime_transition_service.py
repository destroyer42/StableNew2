"""PR-RUNTIME-100: runtime transition coordinator (fakes only, no real process/GPU).

The coordinator delegates every release to the runtime's existing owner and never mutates an
external/ambiguous process.
"""

from __future__ import annotations

import pytest

from src.services.runtime_transition_service import (
    RUNTIME_A1111_WEBUI,
    RUNTIME_COMFY,
    RUNTIME_SVD_NATIVE,
    RuntimeOwnershipState,
    RuntimeTransitionCoordinator,
    RuntimeTransitionError,
    RuntimeTransitionStatus,
)


class _FakeManager:
    """Stands in for WebUIProcessManager/ComfyProcessManager ownership semantics."""

    def __init__(self, *, running: bool, owned: bool, stop_name: str = "stop") -> None:
        self._running = running
        self.owns_process = owned
        self.stop_calls = 0
        self._stop_name = stop_name
        setattr(self, stop_name, self._stop)

    def is_running(self) -> bool:
        return self._running

    def _stop(self) -> bool:
        self.stop_calls += 1
        self._running = False
        self.owns_process = False
        return True


class _FailingStopManager(_FakeManager):
    def _stop(self):  # noqa: D401 - stop does not actually release the process
        self.stop_calls += 1
        # simulate a stop() that fails to actually release (still running afterward)
        return False


class _RaisingManager(_FakeManager):
    def _stop(self):
        self.stop_calls += 1
        raise OSError("process handle lost")


class _FakeSVDService:
    def __init__(self, *, raise_on_clear: bool = False) -> None:
        self.clear_calls = 0
        self._raise = raise_on_clear

    def clear_model_cache(self) -> None:
        self.clear_calls += 1
        if self._raise:
            raise RuntimeError("cache release failed")


def _coordinator(
    *,
    webui: object | None = None,
    comfy: object | None = None,
    svd: object | None = None,
    webui_endpoint_present: bool = False,
    comfy_endpoint_present: bool = False,
) -> RuntimeTransitionCoordinator:
    return RuntimeTransitionCoordinator(
        webui_manager_getter=lambda: webui,
        comfy_manager_getter=lambda: comfy,
        svd_service_factory=lambda: svd or _FakeSVDService(),
        webui_endpoint_present=lambda: webui_endpoint_present,
        comfy_endpoint_present=lambda: comfy_endpoint_present,
    )


def test_target_a1111_releases_owned_comfy_and_clears_svd_never_touches_external_comfy() -> None:
    owned_comfy = _FakeManager(running=True, owned=True)
    svd = _FakeSVDService()
    result = _coordinator(comfy=owned_comfy, svd=svd).prepare_for(RUNTIME_A1111_WEBUI)

    assert result.status is RuntimeTransitionStatus.READY and result.ready
    assert owned_comfy.stop_calls == 1 and svd.clear_calls == 1
    assert result.ownership_state[RUNTIME_COMFY] is RuntimeOwnershipState.OWNED
    assert RUNTIME_COMFY in result.releases_completed

    # An external Comfy is never asked to stop.
    external_comfy = _FakeManager(running=True, owned=False)
    result2 = _coordinator(comfy=external_comfy).prepare_for(RUNTIME_A1111_WEBUI)
    assert external_comfy.stop_calls == 0
    assert result2.status is RuntimeTransitionStatus.ACTION_REQUIRED and not result2.ready
    assert result2.ownership_state[RUNTIME_COMFY] is RuntimeOwnershipState.EXTERNAL
    assert any("will not stop it" in b for b in result2.blockers)


def test_target_comfy_releases_owned_a1111_and_clears_svd_never_touches_external_a1111() -> None:
    owned_webui = _FakeManager(running=True, owned=True, stop_name="stop_webui")
    svd = _FakeSVDService()
    result = _coordinator(webui=owned_webui, svd=svd).prepare_for(RUNTIME_COMFY)

    assert result.ready
    assert owned_webui.stop_calls == 1 and svd.clear_calls == 1
    assert result.ownership_state[RUNTIME_A1111_WEBUI] is RuntimeOwnershipState.OWNED

    external_webui = _FakeManager(running=True, owned=False, stop_name="stop_webui")
    result2 = _coordinator(webui=external_webui).prepare_for(RUNTIME_COMFY)
    assert external_webui.stop_calls == 0
    assert result2.status is RuntimeTransitionStatus.ACTION_REQUIRED


def test_target_svd_releases_owned_a1111_and_owned_comfy_but_not_the_svd_cache() -> None:
    owned_webui = _FakeManager(running=True, owned=True, stop_name="stop_webui")
    owned_comfy = _FakeManager(running=True, owned=True)
    svd = _FakeSVDService()
    result = _coordinator(webui=owned_webui, comfy=owned_comfy, svd=svd).prepare_for(
        RUNTIME_SVD_NATIVE
    )

    assert result.ready
    assert owned_webui.stop_calls == 1 and owned_comfy.stop_calls == 1
    assert svd.clear_calls == 0  # the SVD cache is not released ahead of an SVD job
    assert set(result.releases_completed) == {RUNTIME_A1111_WEBUI, RUNTIME_COMFY}


def test_a_non_conflicting_absent_or_not_running_runtime_is_never_stopped() -> None:
    absent = _coordinator().prepare_for(RUNTIME_COMFY)
    assert absent.ready and absent.releases_attempted == ("svd_native_cache",)
    assert absent.ownership_state[RUNTIME_A1111_WEBUI] is RuntimeOwnershipState.ABSENT

    not_running = _FakeManager(running=False, owned=True, stop_name="stop_webui")
    result = _coordinator(webui=not_running).prepare_for(RUNTIME_COMFY)
    assert not_running.stop_calls == 0  # nothing to release; it is not merely stopped on sight
    assert result.ownership_state[RUNTIME_A1111_WEBUI] is RuntimeOwnershipState.NOT_RUNNING


def test_live_configured_endpoint_without_owned_handle_is_external_and_never_stopped() -> None:
    """The normal external-runtime case has no manager process object at all."""

    no_manager_comfy = _coordinator(comfy_endpoint_present=True).prepare_for(RUNTIME_A1111_WEBUI)
    assert no_manager_comfy.status is RuntimeTransitionStatus.ACTION_REQUIRED
    assert no_manager_comfy.ownership_state[RUNTIME_COMFY] is RuntimeOwnershipState.EXTERNAL
    assert no_manager_comfy.releases_attempted == ("svd_native_cache",)

    idle_manager_comfy = _FakeManager(running=False, owned=False)
    idle_manager_comfy_result = _coordinator(
        comfy=idle_manager_comfy, comfy_endpoint_present=True
    ).prepare_for(RUNTIME_A1111_WEBUI)
    assert idle_manager_comfy_result.status is RuntimeTransitionStatus.ACTION_REQUIRED
    assert idle_manager_comfy_result.ownership_state[RUNTIME_COMFY] is RuntimeOwnershipState.EXTERNAL
    assert idle_manager_comfy.stop_calls == 0

    no_manager_webui = _coordinator(webui_endpoint_present=True).prepare_for(RUNTIME_COMFY)
    assert no_manager_webui.status is RuntimeTransitionStatus.ACTION_REQUIRED
    assert no_manager_webui.ownership_state[RUNTIME_A1111_WEBUI] is RuntimeOwnershipState.EXTERNAL

    unmanaged_webui = _FakeManager(running=False, owned=False, stop_name="stop_webui")
    idle_manager_webui = _coordinator(
        webui=unmanaged_webui, webui_endpoint_present=True
    ).prepare_for(RUNTIME_COMFY)
    assert idle_manager_webui.status is RuntimeTransitionStatus.ACTION_REQUIRED
    assert idle_manager_webui.ownership_state[RUNTIME_A1111_WEBUI] is RuntimeOwnershipState.EXTERNAL
    assert unmanaged_webui.stop_calls == 0
    assert any("will not adopt, stop, or restart" in blocker for blocker in idle_manager_webui.blockers)


def test_free_configured_endpoint_does_not_block_and_external_target_is_not_a_conflict() -> None:
    absent = _coordinator(webui_endpoint_present=False).prepare_for(RUNTIME_COMFY)
    assert absent.ready
    assert absent.ownership_state[RUNTIME_A1111_WEBUI] is RuntimeOwnershipState.ABSENT

    # Comfy itself is the target here, so an external Comfy endpoint is not a conflicting runtime.
    external_target = _coordinator(comfy_endpoint_present=True).prepare_for(RUNTIME_COMFY)
    assert external_target.ready
    assert RUNTIME_COMFY not in external_target.ownership_state


def test_owned_release_failure_blocks_and_is_diagnostic_not_a_generation_fallback() -> None:
    for manager in (
        _FailingStopManager(running=True, owned=True),
        _RaisingManager(running=True, owned=True),
    ):
        result = _coordinator(comfy=manager).prepare_for(RUNTIME_A1111_WEBUI)
        assert result.status is RuntimeTransitionStatus.RELEASE_FAILED and not result.ready
        assert result.ownership_state[RUNTIME_COMFY] is RuntimeOwnershipState.OWNED
        assert RUNTIME_COMFY not in result.releases_completed
        assert manager.stop_calls == 1


def test_svd_cache_release_failure_blocks_dispatch() -> None:
    result = _coordinator(svd=_FakeSVDService(raise_on_clear=True)).prepare_for(RUNTIME_COMFY)
    assert result.status is RuntimeTransitionStatus.RELEASE_FAILED
    assert "cache release failed" in result.blockers[0]


def test_alternating_a1111_comfy_a1111_uses_the_existing_managers_not_a_new_authority() -> None:
    webui = _FakeManager(running=False, owned=False, stop_name="stop_webui")
    comfy = _FakeManager(running=False, owned=False)
    coordinator = _coordinator(webui=webui, comfy=comfy)

    # a1111 acquires (nothing to release yet) -> pretend a1111 is now owned+running
    coordinator.prepare_for(RUNTIME_A1111_WEBUI)
    webui.owns_process, webui._running = True, True

    # comfy job releases that owned a1111 via its own existing manager
    result = coordinator.prepare_for(RUNTIME_COMFY)
    assert result.ready and webui.stop_calls == 1
    comfy.owns_process, comfy._running = True, True

    # a1111 job releases that owned comfy via its own existing manager
    result2 = coordinator.prepare_for(RUNTIME_A1111_WEBUI)
    assert result2.ready and comfy.stop_calls == 1
    # no restart of the previously released runtime happened as a side effect
    assert webui.owns_process is False


def test_runtime_transition_error_carries_the_full_result_for_backends_to_raise() -> None:
    external = _FakeManager(running=True, owned=False)
    result = _coordinator(comfy=external).prepare_for(RUNTIME_A1111_WEBUI)
    error = RuntimeTransitionError(result)
    assert error.result is result
    assert "action_required" in str(error)
    with pytest.raises(RuntimeTransitionError):
        raise error


def test_unknown_target_is_rejected() -> None:
    with pytest.raises(ValueError, match="Unknown runtime transition target"):
        _coordinator().prepare_for("wan22_ti2v_5b_i2v_v1")  # a workflow id, not a runtime


def test_svd_cache_is_released_through_the_real_svdservice_and_can_repopulate_after() -> None:
    """Uses the production SVDService class itself (not a fake): the coordinator calls only the
    existing ``clear_model_cache()`` boundary, and the class-level cache is shared by any later
    ``SVDService()``/``SVDRunner`` instance, so a subsequent job can reload normally."""

    from src.video.svd_service import SVDService

    SVDService._pipeline_cache = {("model-a", "cpu", None, None): object()}
    coordinator = RuntimeTransitionCoordinator(
        webui_manager_getter=lambda: None, comfy_manager_getter=lambda: None
    )
    try:
        result = coordinator.prepare_for(RUNTIME_COMFY)
        assert result.ready
        assert SVDService._pipeline_cache == {}  # released through the real, sole SVD authority
        # A later job's cache lookup is simply a normal miss, not a corrupted/poisoned state.
        SVDService._pipeline_cache[("model-b", "cpu", None, None)] = object()
        assert len(SVDService._pipeline_cache) == 1
    finally:
        SVDService._pipeline_cache = {}
