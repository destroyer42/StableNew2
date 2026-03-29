from __future__ import annotations

from src.app.bootstrap import build_application_kernel, build_gui_kernel
from src.app.optional_dependency_probes import OptionalDependencySnapshot


class _ConfigManagerStub:
    def __init__(self, settings: dict[str, object] | None = None) -> None:
        self._settings = dict(settings or {})

    def load_settings(self) -> dict[str, object]:
        return dict(self._settings)


class _RuntimePortsStub:
    def __init__(self) -> None:
        self.created_client: tuple[str] | None = None
        self.created_runner: tuple[object, object] | None = None

    def create_client(self, *, base_url: str):
        self.created_client = (base_url,)
        return {"base_url": base_url}

    def create_runner(self, *, api_client, structured_logger, status_callback=None):
        self.created_runner = (api_client, structured_logger)
        return {"client": api_client, "logger": structured_logger, "status_callback": status_callback}


def test_build_application_kernel_uses_shared_runtime_ports_and_snapshot() -> None:
    config_manager = _ConfigManagerStub({"webui_base_url": "http://127.0.0.1:9000"})
    runtime_ports = _RuntimePortsStub()
    capabilities = OptionalDependencySnapshot()

    kernel = build_application_kernel(
        config_manager=config_manager,
        runtime_ports=runtime_ports,
        capabilities=capabilities,
    )

    assert runtime_ports.created_client == ("http://127.0.0.1:9000",)
    assert runtime_ports.created_runner is not None
    assert kernel.api_client == {"base_url": "http://127.0.0.1:9000"}
    assert kernel.pipeline_runner["client"] == kernel.api_client
    assert kernel.capabilities is capabilities


def test_build_gui_kernel_uses_persisted_base_url() -> None:
    config_manager = _ConfigManagerStub({"webui_base_url": "http://127.0.0.1:7865"})
    runtime_ports = _RuntimePortsStub()

    kernel = build_gui_kernel(
        config_manager=config_manager,
        runtime_ports=runtime_ports,
    )

    assert runtime_ports.created_client == ("http://127.0.0.1:7865",)
    assert kernel.api_client["base_url"] == "http://127.0.0.1:7865"
