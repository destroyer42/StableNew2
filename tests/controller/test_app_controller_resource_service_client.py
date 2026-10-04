"""AppController keeps API-first resource discovery on its own client (PR-DEVEX-TEST-SLIM-120)."""

from types import SimpleNamespace

from src.api.webui_resource_service import WebUIResourceService
from src.controller.app_controller import AppController
from tests.helpers.job_service_di_test_helpers import make_stubbed_job_service


def _build(**kwargs):
    return AppController(
        main_window=None,
        pipeline_runner=None,
        structured_logger=None,
        webui_process_manager=None,
        config_manager=None,
        job_service=make_stubbed_job_service(),
        **kwargs,
    )


def test_default_resource_service_is_api_first_on_the_controller_client():
    client = SimpleNamespace(set_options_write_enabled=lambda *_a, **_k: None)
    controller = _build(api_client=client)

    assert isinstance(controller.resource_service, WebUIResourceService)
    assert controller.resource_service.client is client


def test_injected_resource_service_is_used_unchanged():
    injected = WebUIResourceService(client=None)
    controller = _build(api_client=SimpleNamespace(), resource_service=injected)

    assert controller.resource_service is injected
    assert controller.resource_service.client is None
