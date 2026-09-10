from __future__ import annotations

import logging
from types import SimpleNamespace

import pytest
import requests_mock

from src.api.client import DEFAULT_SCHEDULERS, SDWebUIClient
from src.api.webui_resource_service import WebUIResourceService
from src.gui.app_state_v2 import AppStateV2
from src.gui.dropdown_loader_v2 import DropdownLoader

API_BASE_URL = "http://127.0.0.1:7860"
SCHEDULER_URL = f"{API_BASE_URL}/sdapi/v1/schedulers"


def _client() -> SDWebUIClient:
    return SDWebUIClient(base_url=API_BASE_URL)


@pytest.mark.parametrize(
    ("payload", "expected"),
    [
        (
            [{"name": " Normal "}, {"name": "Karras"}],
            ["Normal", "Karras"],
        ),
        (
            [{"label": " Exponential "}, {"name": "", "label": "Simple"}],
            ["Exponential", "Simple"],
        ),
        ([" Normal ", "Karras", "Karras"], ["Normal", "Karras"]),
        (
            [None, {}, {"name": " Normal "}, {"label": "Karras"}, 4, "", {"name": "Simple"}],
            ["Normal", "Karras", "Simple"],
        ),
    ],
)
def test_get_schedulers_normalizes_supported_response_shapes(payload, expected) -> None:
    with requests_mock.Mocker() as mocker:
        mocker.get(SCHEDULER_URL, json=payload)
        assert _client().get_schedulers() == expected


@pytest.mark.parametrize("payload", [[], {}, [None, {}, 4, "  "]])
def test_get_schedulers_uses_defaults_for_empty_or_malformed_response(payload) -> None:
    with requests_mock.Mocker() as mocker:
        mocker.get(SCHEDULER_URL, json=payload)
        assert _client().get_schedulers() == list(DEFAULT_SCHEDULERS)


class _ResourceClient:
    def get_models(self):
        return [{"model_name": "model-a", "title": "Model A"}]

    def get_vae_models(self):
        return [{"model_name": "vae-a", "title": "VAE A"}]

    def get_samplers(self):
        return [{"name": "Euler a"}]

    def get_schedulers(self):
        raise ValueError("unexpected scheduler parser payload")

    def get_upscalers(self):
        return [{"name": "upscaler-a"}]

    def get_hypernetworks(self):
        return [{"name": "hyper-a"}]

    def get_adetailer_models(self):
        return []

    def get_adetailer_detectors(self):
        return []


def test_refresh_scheduler_failure_is_diagnosable_and_keeps_other_resources(caplog) -> None:
    caplog.set_level(logging.WARNING, logger="src.api.webui_resource_service")
    resources = WebUIResourceService(client=_ResourceClient(), webui_root="/missing").refresh_all()

    assert resources["schedulers"] == list(DEFAULT_SCHEDULERS)
    assert resources["samplers"] == ["Euler a"]
    assert resources["models"][0].name == "model-a"
    assert resources["vaes"][0].name == "vae-a"
    assert "resource=schedulers" in caplog.text
    assert "failure_type=ValueError" in caplog.text
    assert "fallback_used=yes" in caplog.text


def test_resource_refresh_projects_scheduler_to_base_generation_panel(tmp_path) -> None:
    resources = {"schedulers": ["Normal", "Karras"]}
    state = AppStateV2()
    state.set_resources(resources)

    class FakeCombo:
        def __init__(self) -> None:
            self.values = ()

        def __setitem__(self, key, value) -> None:
            assert key == "values"
            self.values = tuple(value)

    class FakeVar:
        def __init__(self) -> None:
            self.value = ""

        def get(self):
            return self.value

        def set(self, value) -> None:
            self.value = value

    scheduler_combo = FakeCombo()
    scheduler_var = FakeVar()
    base_panel = SimpleNamespace(
        _scheduler_combo=scheduler_combo,
        scheduler_var=scheduler_var,
    )
    pipeline_tab = SimpleNamespace(
        sidebar=SimpleNamespace(base_generation_panel=base_panel),
    )
    loader = DropdownLoader()

    dropdowns = loader.load_dropdowns(None, state)
    loader.apply_to_gui(pipeline_tab, dropdowns)

    assert scheduler_combo.values == ("Normal", "Karras")
    assert scheduler_var.value == "Normal"
    scheduler_var.set("Karras")
    loader.apply_to_gui(pipeline_tab, dropdowns)
    assert scheduler_var.value == "Karras"
