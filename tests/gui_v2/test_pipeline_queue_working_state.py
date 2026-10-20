"""Queue event and resource delivery interleavings, with real Tk and no runtime."""

from copy import deepcopy
from types import SimpleNamespace

import pytest

from src.api.webui_resources import WebUIResource, WebUIResourceType
from src.assets.compatibility import CompatibilityProfile, CompatibilityStatus, ModelFamily
from src.contracts import WebUIProjection
from src.controller.app_controller import AppController
from src.controller.app_controller_services.background_task_coordinator import (
    BackgroundTaskCoordinator,
)
from src.controller.app_controller_services.runtime_projection_coordinator import (
    RuntimeProjectionCoordinator,
)
from src.controller.pipeline_controller import PipelineController
from src.gui.app_state_projection_sink import AppStateProjectionSink
from src.gui.app_state_v2 import AppStateV2
from src.gui.base_generation_panel_v2 import BaseGenerationPanelV2
from src.gui.preview_panel_v2 import PreviewPanelV2
from src.gui.sidebar_panel_v2 import SidebarPanelV2
from src.gui.views.pipeline_tab_frame_v2 import PipelineTabFrame
from tests.helpers.job_helpers import make_test_njr

pytestmark = pytest.mark.gui
MODEL_A = "sdxl_a.safetensors"
MODEL_B = "sdxl_b.safetensors"
KLEIN = "flux-2-klein-4b-fp8.safetensors"


def resources(order=(MODEL_A, MODEL_B, KLEIN)):
    return {
        "models": [
            WebUIResource(WebUIResourceType.MODEL, name, f"{name} [abc123]") for name in order
        ],
        "samplers": ["Euler", "Euler a"],
        "schedulers": ["Normal", "Karras", "Beta"],
    }


@pytest.fixture
def ui(tk_root):
    state = AppStateV2()
    app = object.__new__(AppController)
    app.app_state = state
    app.state = SimpleNamespace(current_config=state.current_config, resources=resources())
    backend_resources = resources()
    app.resource_service = SimpleNamespace(
        list_models=lambda: backend_resources["models"],
        list_vaes=lambda: [],
    )
    app._append_log = lambda *_: None
    app._capture_stage_plan_for_tests = lambda *_: None
    app._spawn_tracked_thread = lambda *, target, args, **_: target(*args)
    app._ui_dispatch = lambda callback: callback()
    base = BaseGenerationPanelV2(tk_root, controller=app, samplers=["Euler", "Euler a"])
    base._model_policy_projection._backend_id_provider = lambda: "forge_webui"
    base._model_policy_projection._family_lookup = lambda name: (
        CompatibilityProfile(CompatibilityStatus.RESOLVED, ModelFamily.SDXL, ())
        if name in (MODEL_A, MODEL_B)
        else None
    )
    sidebar = SimpleNamespace(base_generation_panel=base, get_base_generation_panel=lambda: base)
    tab = SimpleNamespace(sidebar=sidebar, _measure_callback=lambda _, callback: callback())
    state.add_resource_listener(
        lambda payload: PipelineTabFrame._on_app_state_resources_changed(tab, payload)
    )
    state.set_resources(resources())
    base.apply_from_overrides(
        {
            "model": MODEL_B,
            "scheduler": "Karras",
            "sampler": "Euler a",
            "width": 832,
            "height": 1216,
        }
    )
    pipeline = object.__new__(PipelineController)
    pipeline._app_state = state
    pipeline._app_controller = None
    pipeline._last_run_config = None
    pipeline.can_enqueue_learning_jobs = lambda _: (True, "")
    pipeline._is_queue_submission_blocked = lambda: False
    pipeline.get_preview_jobs = lambda: (_ for _ in ()).throw(
        AssertionError("must use frozen preview")
    )
    admitted = []
    admission = SimpleNamespace(failure=False, partial=False, on_start=lambda: None)

    def submit(records, policy):
        if admission.failure:
            raise ValueError("fake admission refused")
        accepted = records[:1] if admission.partial else records
        admitted.extend(accepted)
        admission.on_start()
        return [record.job_id for record in accepted]

    pipeline._job_service = SimpleNamespace(submit_njrs=submit)
    app.pipeline_controller = pipeline
    preview = PreviewPanelV2(tk_root, controller=app, app_state=state)
    pending = []
    sink = AppStateProjectionSink(state, dispatcher=pending.append)
    app._runtime_projection_coordinator = RuntimeProjectionCoordinator(
        sink=sink,
        background_tasks=BackgroundTaskCoordinator(run_inline=True),
        build_queue_projection=lambda: ([], []),
        load_history_entries=lambda _: [],
        summarize_running_job=lambda _: None,
    )
    yield SimpleNamespace(
        state=state,
        app=app,
        base=base,
        sidebar=sidebar,
        preview=preview,
        admitted=admitted,
        admission=admission,
        sink=sink,
        pending=pending,
        backend_resources=backend_resources,
    )
    preview.destroy()
    base.destroy()


def snapshot(ui):
    panel = ui.base
    return {
        "model": panel._normalize_model_name(panel.model_var.get()),
        "model_options": tuple(panel._model_combo["values"]),
        "scheduler": panel.scheduler_var.get(),
        "scheduler_options": tuple(panel._scheduler_combo["values"]),
        "sampler": panel.sampler_var.get(),
        "width": panel.width_var.get(),
        "height": panel.height_var.get(),
        "policy": panel._model_policy_projection.last_projection,
        "resources": deepcopy(ui.state.resources),
    }


def preview_jobs(ui, cycle=0, count=2):
    ui.state.add_job_draft_part("operator prompt", "")
    cfg = {
        "model": ui.base._normalize_model_name(ui.base.model_var.get()),
        "scheduler": ui.base.scheduler_var.get(),
        "sampler_name": ui.base.sampler_var.get(),
        "width": int(ui.base.width_var.get()),
        "height": int(ui.base.height_var.get()),
    }
    records = [
        make_test_njr(
            job_id=f"frozen-{cycle}-{n}",
            prompt_source="manual",
            base_model=cfg["model"],
            config=cfg,
        )
        for n in range(count)
    ]
    ui.state.set_preview_jobs(records)
    return records, [deepcopy(record.to_queue_snapshot()) for record in records]


@pytest.mark.parametrize("auto_start", [False, True])
@pytest.mark.parametrize("order", [(MODEL_A, MODEL_B, KLEIN), (KLEIN, MODEL_A, MODEL_B)])
@pytest.mark.parametrize("model", [MODEL_B, KLEIN])
def test_queue_preserves_working_state_and_frozen_preview(ui, auto_start, order, model):
    ui.base.model_var.set(model)
    if auto_start:
        # The readiness-epoch observer in main.py invokes this existing sidebar route.
        ui.admission.on_start = lambda: SidebarPanelV2.refresh_base_generation_from_webui(
            ui.sidebar
        )
    for cycle in range(2):
        records, frozen = preview_jobs(ui, cycle)
        before = snapshot(ui)
        # A resource result can already be awaiting Tk delivery when Add to Queue is clicked.
        ui.sink.apply_webui_projection(WebUIProjection(cycle + 1, resources=resources(order)))
        ui.preview.add_to_queue_button.invoke()
        while ui.pending:
            ui.pending.pop(0)()
        after = snapshot(ui)
        for key in (
            "model",
            "scheduler",
            "scheduler_options",
            "sampler",
            "width",
            "height",
            "policy",
        ):
            assert after[key] == before[key], (key, before, after)
        assert ui.admitted[-2:] == records
        assert all(
            actual is expected for actual, expected in zip(ui.admitted[-2:], records, strict=True)
        )
        assert [record.to_queue_snapshot() for record in ui.admitted[-2:]] == frozen
        assert not ui.state.preview_jobs and not ui.state.job_draft.summary.part_count
        ui.preview.add_to_queue_button.invoke()
        assert len(ui.admitted) == 2 * (cycle + 1)


def test_published_resources_do_not_emit_new_operator_edits_or_backend_calls(ui):
    changes = []
    ui.base._on_change = lambda: changes.append(True)
    ui.app.resource_service.list_models = lambda: (_ for _ in ()).throw(
        AssertionError("published refresh must not query backend")
    )
    ui.state.set_resources(resources((KLEIN, MODEL_B, MODEL_A)))
    SidebarPanelV2.refresh_base_generation_from_webui(ui.sidebar)
    assert not changes


@pytest.mark.parametrize("result", ["failure", "partial"])
def test_failed_or_partial_admission_keeps_draft_and_preview(ui, result):
    records, frozen = preview_jobs(ui)
    before = snapshot(ui)
    setattr(ui.admission, result, True)
    ui.preview.add_to_queue_button.invoke()
    assert snapshot(ui) == before
    assert ui.state.preview_jobs == records and ui.state.job_draft.summary.part_count == 1
    assert [record.to_queue_snapshot() for record in records] == frozen


def test_clear_and_invalidate_are_not_resource_refreshes(ui):
    preview_jobs(ui)
    before = snapshot(ui)
    ui.state.invalidate_preview()
    assert snapshot(ui) == before
    ui.preview._on_clear_draft()
    assert snapshot(ui) == before


@pytest.mark.parametrize(
    "payload", [{}, {"models": []}, {"schedulers": []}, {"upscalers": ["new"]}]
)
def test_incomplete_resource_publication_preserves_valid_generation_resources(ui, payload):
    before = snapshot(ui)
    ui.sink.apply_webui_projection(WebUIProjection(1, resources=payload))
    while ui.pending:
        ui.pending.pop(0)()
    after = snapshot(ui)
    for key in (
        "model",
        "model_options",
        "scheduler",
        "scheduler_options",
        "sampler",
        "width",
        "height",
        "policy",
    ):
        assert after[key] == before[key], key
    for key in ("models", "samplers", "schedulers"):
        assert after["resources"][key] == before["resources"][key]


def test_ready_refresh_uses_published_schedulers_and_preserves_model_alias(ui):
    before = snapshot(ui)
    SidebarPanelV2.refresh_base_generation_from_webui(ui.sidebar)
    assert snapshot(ui) == before


def test_missing_model_is_reported_without_selecting_first(ui):
    ui.state.set_resources(resources((MODEL_A, KLEIN)))
    assert ui.base._normalize_model_name(ui.base.model_var.get()) == MODEL_B
    assert "unavailable" in ui.base._helper_label.cget("text").lower()
    assert MODEL_B not in ui.base._model_combo["values"]
    ui.state.set_resources(resources())
    assert "unavailable" not in ui.base._helper_label.cget("text").lower()


def test_constrained_refresh_then_saved_configuration_restores_options_and_draft(ui):
    before = snapshot(ui)
    ui.base.model_var.set(KLEIN)
    projection = ui.base._model_policy_projection
    assert projection.active
    fixed = snapshot(ui)
    ui.state.set_resources(resources((KLEIN, MODEL_B, MODEL_A)))
    for key in ("model", "scheduler", "sampler", "width", "height", "policy"):
        assert snapshot(ui)[key] == fixed[key], key
    assert str(ui.base._scheduler_combo.cget("state")) == "disabled"
    ui.base.model_var.set(MODEL_B)
    for key in ("model", "scheduler", "sampler", "width", "height", "policy"):
        assert snapshot(ui)[key] == before[key], key
    assert tuple(ui.base._scheduler_combo["values"]) == before["scheduler_options"]
    saved = {"model": MODEL_B, "scheduler": "Karras", "width": 832, "height": 1216}
    original = deepcopy(saved)
    ui.state.set_resources({"schedulers": []})
    # A saved recipe must also repair an already-empty widget from the published catalog.
    ui.base._scheduler_combo["values"] = ()
    ui.base.apply_from_overrides(saved)
    assert saved == original
    assert ui.base.scheduler_var.get() == "Karras"
    assert "Karras" in ui.base._scheduler_combo["values"]
    assert (ui.base.width_var.get(), ui.base.height_var.get()) == ("832", "1216")


@pytest.mark.parametrize("payload", [resources(), {"schedulers": []}, None])
def test_full_partial_and_failed_webui_refresh_route(ui, payload):
    before = snapshot(ui)

    def refresh():
        if payload is None:
            raise RuntimeError("fake endpoint failure")
        return payload

    ui.app.resource_service.refresh_all = refresh
    ui.app.refresh_resources_from_webui()
    while ui.pending:
        ui.pending.pop(0)()
    after = snapshot(ui)
    for key in ("model", "scheduler", "scheduler_options", "sampler", "width", "height", "policy"):
        assert after[key] == before[key], key


def test_friendly_model_labels_resolve_internal_policy_and_unavailable_identity(ui):
    payload = resources()
    payload["models"][-1].display_name = "Klein 4B [abc123]"
    ui.state.set_resources(payload)
    ui.base.apply_from_overrides({"model": KLEIN})
    assert ui.base.model_var.get() == "Klein 4B"
    assert ui.base._model_policy_projection.active
    ui.base.apply_from_overrides({"model": KLEIN, "scheduler": "Karras", "steps": 90})
    assert ui.base.scheduler_var.get() == "Beta"
    assert ui.base.steps_var.get() == 4
    ui.state.set_resources(resources((MODEL_A, MODEL_B)))
    assert ui.base._normalize_model_name(ui.base.model_var.get()) == KLEIN
    assert ui.base._model_policy_projection.active
