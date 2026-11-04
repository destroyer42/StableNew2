"""Simulated Comfy video runtime: fixtures injected only at external adaptor boundaries.

Replaced for the duration of a simulated run (and restored after):

* the video backend registry builder, so the *production* ``ComfyWorkflowVideoBackend`` is constructed with a real
  ``ComfyApiClient`` pointed at the loopback ``FakeComfy`` plus fixture process manager / resource probes / runtime
  transition (these are the backend's own constructor seams);
* the Video Workflow tab's preflight probe factory (its own seam), reporting a StableNew-launched runtime;
* the pinned-model SHA-256 inventory check, which cannot be satisfied without the multi-GB weights.  Physical readiness
  runs that check for real; the evidence tags it ``simulated_fixture``.

The queue, repository, JobService, compiler, NJR builder, ``PipelineRunner.run_njr`` and the frame encoder are untouched.
"""

from __future__ import annotations

import sys
from collections.abc import Iterator
from contextlib import contextmanager
from types import SimpleNamespace
from typing import Any

FIXTURE_RAM_GB = 24.0
FIXTURE_VRAM_MIB = (12282.0, 11000.0)  # total, free


class FixtureComfyManager:
    """Stands in for ``ComfyProcessManager``: an endpoint that is simply up; owns and launches nothing."""

    owns_process = False
    pid = None
    jobs_since_start = 0

    def __init__(self, base_url: str, command: list[str]) -> None:
        self._config = SimpleNamespace(base_url=base_url, command=command, working_dir=None)
        self.config = self._config
        self.stops = 0

    def is_running(self) -> bool:
        return True

    def ensure_running(self) -> bool:
        return True

    def stop(self, **_kw: Any) -> None:  # never reached for an unowned runtime; counted as evidence
        self.stops += 1


@contextmanager
def fixture_video_runtime(fake_comfy: Any, spec: Any) -> Iterator[dict[str, Any]]:
    import src.controller.video_preflight_controller as preflight_controller
    import src.pipeline.pipeline_runner as pipeline_runner
    import src.video.comfy_workflow_backend as comfy_backend
    import src.video.workflow_preflight as preflight
    from src.video.comfy_api_client import ComfyApiClient
    from src.video.comfy_runtime_setup import ComfyLaunchFacts
    from src.video.comfy_workflow_backend import ComfyWorkflowVideoBackend
    from src.video.svd_native_backend import SVDNativeVideoBackend
    from src.video.video_backend_registry import VideoBackendRegistry
    from src.video.workflow_readiness import WorkflowResourceReadiness, required_launch_flags

    required = list(required_launch_flags(spec))
    command = [sys.executable, "fixture_comfy_main.py", "--listen", "127.0.0.1", *required]
    manager = FixtureComfyManager(fake_comfy.base_url, command)
    info: dict[str, Any] = {"manager": manager, "command": command, "backends": []}

    def build_registry() -> Any:
        registry = VideoBackendRegistry()
        registry.register(SVDNativeVideoBackend())
        backend = ComfyWorkflowVideoBackend(
            client=ComfyApiClient(base_url=fake_comfy.base_url),
            process_manager=manager,
            readiness=WorkflowResourceReadiness(
                ram_probe=lambda: FIXTURE_RAM_GB, gpu_probe=lambda _i: FIXTURE_VRAM_MIB
            ),
            transition=SimpleNamespace(prepare_for=lambda _t: SimpleNamespace(ready=True)),
            base_url=fake_comfy.base_url,
            history_timeout=60.0,
            history_poll_interval=0.2,
        )
        info["backends"].append(backend)
        registry.register(backend)
        return registry

    def probes() -> Any:
        client = ComfyApiClient(base_url=fake_comfy.base_url)
        return preflight.PreflightProbes(
            command=tuple(command),
            base_url=fake_comfy.base_url,
            autostart=False,
            endpoint_state=lambda _u: preflight.ENDPOINT_HEALTHY,
            fetch_object_info=lambda _u: client.get_object_info(),
            fetch_system_stats=lambda _u: client.get_system_stats(),
            ram_probe=lambda: FIXTURE_RAM_GB,
            gpu_probe=lambda _i: FIXTURE_VRAM_MIB,
            launch=ComfyLaunchFacts(
                saved_command=tuple(command), active_command=tuple(command), owns_runtime=True
            ),
            extras={"process_config": None},
        )

    saved = (
        pipeline_runner.build_default_video_backend_registry,
        preflight_controller.default_preflight_probes,
        preflight.configured_asset_issues,
        comfy_backend.configured_asset_issues,
    )
    pipeline_runner.build_default_video_backend_registry = build_registry
    preflight_controller.default_preflight_probes = lambda **_kw: probes()
    preflight.configured_asset_issues = lambda *_a, **_k: ()
    comfy_backend.configured_asset_issues = lambda *_a, **_k: ()
    try:
        yield info
    finally:
        (
            pipeline_runner.build_default_video_backend_registry,
            preflight_controller.default_preflight_probes,
            preflight.configured_asset_issues,
            comfy_backend.configured_asset_issues,
        ) = saved
