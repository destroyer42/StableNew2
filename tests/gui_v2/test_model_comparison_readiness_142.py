"""Cold operator resource selection -> real Learning Preview, without policy injection."""

from __future__ import annotations

import json
import time
from types import SimpleNamespace

import pytest

from src.api.webui_resources import WebUIResourceService
from src.assets import AssetRegistry
from src.gui.app_state_v2 import AppStateV2
from src.gui.controllers.learning_controller import LearningController
from src.gui.learning_state import LearningState
from src.gui.views.experiment_design_panel import ExperimentDesignPanel
from tests.assets.checkpoint_fixtures import checkpoint
from tests.gui_v2.tk_test_utils import get_shared_tk_root


@pytest.fixture
def operator(tmp_path, monkeypatch):
    root = get_shared_tk_root()
    if root is None:
        pytest.skip("Tk display unavailable")
    webui = tmp_path / "webui"
    cache = tmp_path / "cache.json"
    monkeypatch.setenv("STABLENEW_WEBUI_ROOT", str(webui))
    monkeypatch.setattr("src.assets.registry.workspace_paths.asset_registry_cache", lambda: cache)
    # Actual API/resource projection, with only the external discovery transport replaced.
    catalog = []
    service = WebUIResourceService(
        client=SimpleNamespace(get_models=lambda: list(catalog)), webui_root=str(webui)
    )
    state = AppStateV2()
    controller = LearningController(
        LearningState(), app_controller=SimpleNamespace(app_state=state, resource_service=service)
    )
    controller._get_baseline_config = lambda: {
        "txt2img": {
            "model": "first",
            "width": 768,
            "height": 1024,
            "seed": 42,
            "steps": 30,
            "cfg_scale": 7,
            "sampler_name": "Euler",
            "scheduler": "Normal",
        },
        "pipeline": {"txt2img_enabled": True},
        "backend_options": {"image": {"backend_id": "forge_webui"}},
    }
    pack = tmp_path / "packs" / "study.json"
    pack.parent.mkdir()
    pack.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "pack_data": {
                    "name": "study",
                    "slots": [{"index": 0, "text": "cat", "negative": "bad"}],
                },
                "preset_data": {},
            }
        ),
        encoding="utf-8",
    )
    view = ExperimentDesignPanel(root, learning_controller=controller, packs_dir=pack.parent)
    view.name_var.set("readiness")

    def select(names=("first", "second"), *, paths=None):
        catalog.clear()
        for index, name in enumerate(names):
            path = (
                paths[index]
                if paths
                else checkpoint(
                    webui / "models" / "Stable-diffusion" / f"{name}.safetensors",
                    metadata={"modelspec.architecture": "stable-diffusion-xl-v1-base"},
                    payload=str(index).encode(),
                )
            )
            catalog.append(
                {
                    "model_name": name,
                    "title": f"{name}.safetensors [1234567890]",
                    "filename": str(path),
                }
            )
        state.set_resources({"models": service.list_models()})
        view.study_type_var.set("Model Comparison")
        view._on_study_type_changed()
        for value in view.choice_vars.values():
            value.set(True)

    yield SimpleNamespace(
        view=view,
        controller=controller,
        select=select,
        root=root,
        webui=webui,
        cache=cache,
        catalog=catalog,
        state=state,
    )
    if view.winfo_exists():
        view.destroy()


def complete(operator):
    deadline = time.monotonic() + 8
    while time.monotonic() < deadline:
        operator.root.update()
        if not getattr(operator.view, "_comparison_readiness_busy", False):
            return
        time.sleep(0.01)
    pytest.fail("evidence readiness did not finish")


@pytest.mark.parametrize("names", [("first", "second"), ("first", "flux-2-klein-4b-fp8")])
def test_cold_real_operator_preview_becomes_ready(operator, names):
    operator.select(names)
    assert AssetRegistry().cached_snapshot().records == ()
    operator.view._on_build_preview()
    complete(operator)
    assert operator.view.feedback_var.get() == "Model Comparison preview ready"
    snapshot = json.loads(
        operator.controller.learning_state.current_experiment.execution_snapshot_json
    )
    assert len(snapshot["model_comparison"]["arms"]) == 2
    assert len({arm["source_intent_sha256"] for arm in snapshot["model_comparison"]["arms"]}) == 1


def test_wrong_served_path_cannot_borrow_warm_same_name_evidence(operator, tmp_path):
    first = checkpoint(
        operator.webui / "models" / "Stable-diffusion" / "first.safetensors",
        metadata={"ss_base_model_version": "sdxl"},
    )
    second = checkpoint(
        operator.webui / "models" / "Stable-diffusion" / "second.safetensors",
        metadata={"ss_base_model_version": "sdxl"},
        payload=b"other",
    )
    AssetRegistry().refresh()
    operator.select(paths=[tmp_path / "external" / first.name, second])
    operator.view._on_build_preview()
    complete(operator)
    assert "unavailable" in operator.view.feedback_var.get().lower()
    assert "Model 1" in operator.view.feedback_var.get()
    assert operator.controller.learning_state.current_experiment is None


def test_warm_operator_preview_reuses_evidence_without_refresh(operator, monkeypatch):
    operator.select()
    operator.view._on_build_preview()
    complete(operator)
    before = operator.cache.read_bytes()
    monkeypatch.setattr(AssetRegistry, "refresh", lambda *a, **k: pytest.fail("warm refresh"))
    operator.view._on_build_preview()
    complete(operator)
    assert operator.view.feedback_var.get() == "Model Comparison preview ready"
    assert operator.cache.read_bytes() == before


@pytest.mark.parametrize("cancel", ["button", "selection", "resources", "mode", "destroy"])
def test_worker_is_off_tk_single_flight_and_never_publishes_stale(operator, monkeypatch, cancel):
    import threading

    operator.select()
    entered, release = threading.Event(), threading.Event()
    main_thread = threading.get_ident()
    original = AssetRegistry.refresh
    calls = []

    def paused(registry, **kwargs):
        calls.append(threading.get_ident())
        entered.set()
        assert release.wait(3)
        return original(registry, **kwargs)

    monkeypatch.setattr(AssetRegistry, "refresh", paused)
    operator.view._on_build_preview()
    assert entered.wait(3)
    assert str(operator.view.build_button.cget("state")) == "disabled"
    assert str(operator.view.run_button.cget("state")) == "disabled"
    operator.view._on_build_preview()  # Must not start a second worker.
    task = operator.view._comparison_evidence_task
    if cancel == "button":
        operator.view._cancel_comparison_evidence()
    elif cancel == "selection":
        next(iter(operator.view.choice_vars.values())).set(False)
    elif cancel == "resources":
        operator.state.set_resources({"models": []})
    elif cancel == "mode":
        operator.view.study_type_var.set("Controlled Variable")
        operator.view._on_study_type_changed()
    else:
        operator.view.destroy()
    release.set()
    task.thread.join(3)
    assert not task.thread.is_alive()
    if cancel != "destroy":
        complete(operator)
        assert "cancelled" in operator.view.feedback_var.get()
    assert len(calls) == 1 and calls[0] != main_thread
    assert operator.controller.learning_state.current_experiment is None
    assert not operator.cache.exists()


def test_operator_preview_to_run_is_frozen_and_admits_once(operator, monkeypatch):
    from unittest.mock import Mock

    from src.learning.execution_controller import LearningExecutionController

    operator.select()
    operator.view._on_build_preview()
    complete(operator)
    assert operator.view.feedback_var.get() == "Model Comparison preview ready"
    exp = operator.controller.learning_state.current_experiment
    frozen = exp.execution_snapshot_json
    (operator.view._resolve_packs_dir() / "study.json").write_text("now invalid")
    monkeypatch.setattr(
        AssetRegistry, "cached_snapshot", lambda *_: pytest.fail("live registry at Run")
    )
    monkeypatch.setattr(AssetRegistry, "refresh", lambda *a, **k: pytest.fail("refresh at Run"))
    monkeypatch.setattr(
        "src.pipeline.resolution_layer.adapt_pack_intent",
        lambda *a, **k: pytest.fail("adapt at Run"),
    )
    operator.controller._get_baseline_config = lambda: pytest.fail("live cards at Run")
    service = SimpleNamespace(
        submit_njrs=Mock(side_effect=lambda records, policy: [r.job_id for r in records])
    )
    operator.controller.execution_controller = LearningExecutionController(
        operator.controller.learning_state, service
    )
    operator.controller.pipeline_controller = object()
    operator.controller.run_plan()
    assert service.submit_njrs.call_count == 1
    assert exp.execution_snapshot_json == frozen
    records = service.submit_njrs.call_args.args[0]
    assert len(records) == 2
    for record in records:
        evidence = record.workload.metadata["model_comparison"]["checkpoint_evidence"]
        assert evidence["authority"] == "asset_registry" and len(evidence["sha256"]) == 64
        assert "path" not in evidence
