"""PR-IMG-120: the 'diffusers' transition target is the Ideogram 4 GPU lease (fakes only, no process, no GPU)."""

from __future__ import annotations

from src.services.runtime_transition_service import (
    KNOWN_TRANSITION_TARGETS,
    RUNTIME_DIFFUSERS,
    RuntimeOwnershipState,
    RuntimeTransitionStatus,
)
from tests.services.test_runtime_transition_service import (
    _coordinator,
    _FakeManager,
    _FakeSVDService,
)


def test_diffusers_is_a_known_target_that_releases_owned_webui_comfy_and_the_svd_cache() -> None:
    assert RUNTIME_DIFFUSERS == "diffusers" and RUNTIME_DIFFUSERS in KNOWN_TRANSITION_TARGETS
    webui = _FakeManager(running=True, owned=True, stop_name="stop_webui")
    comfy = _FakeManager(running=True, owned=True)
    svd = _FakeSVDService()
    result = _coordinator(webui=webui, comfy=comfy, svd=svd).prepare_for(RUNTIME_DIFFUSERS)
    assert result.ready and result.status is RuntimeTransitionStatus.READY
    assert webui.stop_calls == 1 and comfy.stop_calls == 1 and svd.clear_calls == 1
    assert "svd_native_cache" in result.releases_completed
    assert set(result.ownership_state) >= {"a1111_webui", "comfy"}


def test_an_external_webui_or_comfy_blocks_the_lease_and_is_never_stopped() -> None:
    result = _coordinator(webui_endpoint_present=True).prepare_for(RUNTIME_DIFFUSERS)
    assert result.status is RuntimeTransitionStatus.ACTION_REQUIRED and not result.ready
    assert result.ownership_state["a1111_webui"] is RuntimeOwnershipState.EXTERNAL
    assert result.blockers
    external = _FakeManager(running=True, owned=False)
    result = _coordinator(webui=external).prepare_for(RUNTIME_DIFFUSERS)
    assert not result.ready and external.stop_calls == 0


def test_a_failed_owned_release_fails_the_lease() -> None:
    result = _coordinator(svd=_FakeSVDService(raise_on_clear=True)).prepare_for(RUNTIME_DIFFUSERS)
    assert result.status is RuntimeTransitionStatus.RELEASE_FAILED
