"""Host-independence fixtures for integration tests.

Integration tests drive the production queue/runner path with fake inference. They
must not observe the machine they happen to run on: the owner's real A1111/Comfy
endpoints and per-user PromptPack directory are host state, not test inputs.
"""

from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def _isolate_integration_host_state(
    monkeypatch: pytest.MonkeyPatch, tmp_path_factory: pytest.TempPathFactory
) -> None:
    """Keep integration tests off host runtimes and the owner's PromptPack storage.

    * ``RuntimeTransitionCoordinator`` defaults probe the configured WebUI/Comfy
      endpoints. An external operator-run runtime would (correctly) block dispatch
      with ``action_required``, so a test that does not inject its own coordinator
      would depend on whether the owner's A1111 happens to be running. Report both
      configured endpoints as free. Tests that exercise the external-runtime policy
      inject explicit ``*_endpoint_present`` callables and are unaffected.
    * ``resolve_prompt_pack_dir`` falls back to the per-user PromptPack directory;
      point it at an empty temporary directory. Explicit ``packs_dir`` injection and
      per-test overrides still win.
    """

    monkeypatch.setattr(
        "src.api.healthcheck.probe_webui_endpoint", lambda *_args, **_kwargs: "free"
    )
    monkeypatch.setattr(
        "src.video.comfy_healthcheck.probe_comfy_endpoint", lambda *_args, **_kwargs: "free"
    )
    monkeypatch.setenv(
        "STABLENEW_PROMPTPACK_DIR", str(tmp_path_factory.mktemp("isolated_promptpacks"))
    )
