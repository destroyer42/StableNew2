from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from src.controller.app_controller import AppController
from src.controller.pipeline_controller import PipelineController
from src.controller.video_workflow_controller import VideoWorkflowController
from src.video.workflow_contracts import (
    WORKFLOW_CAP_MULTI_FRAME_ANCHOR_VIDEO,
    WorkflowDependencySpec,
    WorkflowInputBinding,
    WorkflowOutputBinding,
    WorkflowSpec,
)


class _RuntimePortsStub:
    def __init__(self) -> None:
        self.created_clients: list[str] = []
        self.runner_calls: list[dict[str, object]] = []

    def create_client(self, *, base_url: str):
        self.created_clients.append(base_url)
        return {"base_url": base_url}

    def create_runner(self, *, api_client, structured_logger, status_callback=None):
        payload = {
            "api_client": api_client,
            "structured_logger": structured_logger,
            "status_callback": status_callback,
        }
        self.runner_calls.append(payload)
        return payload


def _stub_spec(backend_id: str = "comfy", workflow_version: str = "1.0.0") -> WorkflowSpec:
    """A real (minimal) spec: producers now derive requirements from declared bindings."""

    return WorkflowSpec(
        workflow_id="wf-1",
        workflow_version=workflow_version,
        backend_id=backend_id,
        display_name="Workflow One",
        description="desc",
        capability_tags=(WORKFLOW_CAP_MULTI_FRAME_ANCHOR_VIDEO,),
        input_bindings=(
            WorkflowInputBinding(binding_name="start_anchor", source_field="input_image_path"),
            WorkflowInputBinding(binding_name="end_anchor", source_field="end_anchor_path"),
            WorkflowInputBinding(binding_name="prompt", source_field="prompt", required=False),
        ),
        output_bindings=(
            WorkflowOutputBinding(binding_name="output_dir", source_field="output_dir"),
        ),
        dependency_specs=(
            WorkflowDependencySpec(dependency_id="d", dependency_kind="custom_node", locator="x"),
        ),
    )


class _WorkflowRegistryStub:
    def list_specs_for_backend(self, backend_id: str):
        return [_stub_spec(backend_id)]

    def get(self, workflow_id: str, workflow_version: str | None = None):
        return _stub_spec(workflow_version=workflow_version or "1.0.0")


@pytest.mark.parametrize(
    ("settings", "expected_endpoint"),
    [
        ({}, "http://127.0.0.1:7871"),  # nothing configured: the managed Forge default endpoint
        ({"webui_runtime_identity": "a1111_webui"}, "http://127.0.0.1:7860"),  # explicit A1111 rollback
        ({"webui_runtime_identity": "a1111_webui", "webui_base_url": "http://127.0.0.1:7861"}, "http://127.0.0.1:7861"),
    ],
)
def test_pipeline_controller_uses_runtime_ports_for_runner_creation(monkeypatch, settings, expected_endpoint) -> None:
    import src.utils.config as config_module

    class _Settings:
        def load_settings(self):
            return dict(settings)

    monkeypatch.setattr(config_module, "ConfigManager", lambda *a, **k: _Settings())
    monkeypatch.delenv("STABLENEW_WEBUI_RUNTIME_IDENTITY", raising=False)
    monkeypatch.delenv("STABLENEW_WEBUI_BASE_URL", raising=False)
    runtime_ports = _RuntimePortsStub()
    controller = PipelineController(runtime_ports=runtime_ports)

    runner = controller._create_runtime_pipeline_runner()

    assert runtime_ports.created_clients == [expected_endpoint]
    assert runtime_ports.runner_calls
    assert runner["api_client"] == {"base_url": expected_endpoint}


def test_app_controller_uses_runtime_ports_for_client_and_runner(monkeypatch) -> None:
    runtime_ports = _RuntimePortsStub()
    monkeypatch.setattr(
        "src.controller.app_controller.get_jsonl_log_config",
        lambda: {"enabled": False},
    )
    monkeypatch.setattr(
        "src.controller.app_controller.attach_jsonl_log_handler",
        lambda *_args, **_kwargs: None,
    )
    controller = AppController(
        main_window=None,
        threaded=False,
        runtime_ports=runtime_ports,
        ui_scheduler=lambda fn: fn(),
    )

    assert runtime_ports.created_clients
    assert runtime_ports.runner_calls
    assert controller.pipeline_runner == runtime_ports.runner_calls[0]


def test_app_controller_discovery_uses_runtime_ports(monkeypatch) -> None:
    runtime_ports = _RuntimePortsStub()
    controller = AppController.__new__(AppController)
    controller._runtime_ports = runtime_ports
    monkeypatch.setattr(
        "src.utils.webui_discovery.find_webui_api_port",
        lambda **_kwargs: "http://127.0.0.1:7862",
    )

    client = AppController._create_api_client_with_discovery(controller)

    assert client == {"base_url": "http://127.0.0.1:7862"}


def test_video_workflow_controller_accepts_registry_port(tmp_path: Path) -> None:
    source = tmp_path / "source.png"
    end = tmp_path / "end.png"
    source.write_bytes(b"png")
    end.write_bytes(b"png")

    class _JobServiceStub:
        def __init__(self) -> None:
            self.calls = []

        def submit_njrs(self, njrs, policy):
            self.calls.append((list(njrs), policy))
            return ["job-video-queued"]

    job_service = _JobServiceStub()
    app_controller = SimpleNamespace(job_service=job_service, output_dir=str(tmp_path / "output"))
    controller = VideoWorkflowController(
        app_controller=app_controller,
        workflow_registry=_WorkflowRegistryStub(),
    )

    job_id = controller.submit_video_workflow_job(
        source_image_path=source,
        form_data={
            "workflow_id": "wf-1",
            "workflow_version": "1.0.0",
            "end_anchor_path": str(end),
            "mid_anchor_paths": [],
            "prompt": "prompt text",
            "negative_prompt": "",
            "motion_profile": "balanced",
            "output_route": "Testing",
        },
    )

    assert job_id == "job-video-queued"
    assert len(job_service.calls) == 1
