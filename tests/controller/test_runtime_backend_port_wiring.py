from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from src.controller.app_controller import AppController
from src.controller.pipeline_controller import PipelineController
from src.controller.video_workflow_controller import VideoWorkflowController


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


class _WorkflowRegistryStub:
    def list_specs_for_backend(self, backend_id: str):
        return [
            SimpleNamespace(
                workflow_id="wf-1",
                workflow_version="1.0.0",
                backend_id=backend_id,
                display_name="Workflow One",
                description="desc",
                capability_tags=("tag-a",),
                dependency_specs=(),
            )
        ]

    def get(self, workflow_id: str, workflow_version: str | None = None):
        return SimpleNamespace(
            workflow_id=workflow_id,
            workflow_version=workflow_version or "1.0.0",
            backend_id="comfy",
            display_name="Workflow One",
            description="desc",
            capability_tags=("tag-a",),
            dependency_specs=(),
        )


def test_pipeline_controller_uses_runtime_ports_for_runner_creation() -> None:
    runtime_ports = _RuntimePortsStub()
    controller = PipelineController(runtime_ports=runtime_ports)

    runner = controller._create_runtime_pipeline_runner()

    assert runtime_ports.created_clients == ["http://127.0.0.1:7860"]
    assert runtime_ports.runner_calls
    assert runner["api_client"] == {"base_url": "http://127.0.0.1:7860"}


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

        def enqueue_njrs(self, njrs, request):
            self.calls.append((list(njrs), request))
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
