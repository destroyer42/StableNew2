"""N5: the Packs x Models dialog captures intent, shows the exact plan and queues only what it showed."""

from __future__ import annotations

from typing import Any

import pytest

from src.controller.app_controller_services.pack_model_batch_service import (
    BatchCell,
    BatchPlan,
    BatchRequest,
)
from src.gui.batch_builder_dialog import BatchBuilderDialog

MODELS = [
    ("Juggernaut XL v9", "sdxl\\juggernautXL_v9.safetensors [a1b2]"),
    ("Pony v6", "ponyDiffusion_v6.safetensors"),
]


class Calls:
    def __init__(self) -> None:
        self.planned: list[BatchRequest] = []
        self.queued: list[BatchPlan] = []
        self.plan_reply: Any = None
        self.queue_reply: Any = None

    def plan(self, request, on_result, on_error):  # type: ignore[no-untyped-def]
        self.planned.append(request)
        self.plan_reply = (on_result, on_error)

    def queue(self, plan, on_result, on_error):  # type: ignore[no-untyped-def]
        self.queued.append(plan)
        self.queue_reply = (on_result, on_error)


def _plan(request: BatchRequest) -> BatchPlan:
    cells = tuple(
        BatchCell(pack, pack, model, records=(object(), object()))
        for pack in request.pack_ids
        for model in request.models
    )
    return BatchPlan(request=request, cells=cells, eta_seconds=600.0)


@pytest.fixture
def dialog(tk_root):  # type: ignore[no-untyped-def]
    calls = Calls()
    window = BatchBuilderDialog(
        tk_root,
        packs=["castles", "portraits", "forests"],
        models=MODELS,
        plan_batch=calls.plan,
        queue_batch=calls.queue,
        selected_packs=["castles"],
        selected_model=MODELS[0][1],
        adetailer=True,
    )
    window.calls = calls  # type: ignore[attr-defined]
    yield window
    window.destroy()


def test_it_opens_with_the_pipeline_selection_and_queue_disabled(dialog):  # type: ignore[no-untyped-def]
    assert dialog.selected_packs() == ["castles"]
    assert dialog.selected_models() == [MODELS[0][1]]
    assert dialog.adetailer_var.get() is True and dialog.upscale_var.get() is False
    assert "castles x 1 model(s)" in dialog.name_var.get()
    assert dialog.queue_button.instate(["disabled"])


def test_plan_then_queue_submits_exactly_the_plan_it_showed(dialog):  # type: ignore[no-untyped-def]
    dialog.pack_list.selection_set(1)
    dialog.model_list.selection_set(1)
    dialog._changed()
    dialog._plan()
    (request,) = dialog.calls.planned
    assert request.pack_ids == ("castles", "portraits") and request.models == tuple(
        m for _, m in MODELS
    )
    assert request.adetailer is True and request.upscale is False
    assert dialog.plan_button.instate(["disabled"])

    on_result, _on_error = dialog.calls.plan_reply
    on_result(_plan(request))
    assert "Jobs: 8    Images: 8" in dialog.summary_text()
    assert dialog.queue_button.instate(["!disabled"]) and "8 jobs" in dialog.queue_button.cget(
        "text"
    )

    dialog.name_var.set("tonight")
    dialog._queue()
    (queued,) = dialog.calls.queued
    assert queued.jobs == 8 and queued.request.name == "tonight"
    dialog.calls.queue_reply[0](8)
    assert "Queued 8 job(s) as one batch." in dialog.status_label.cget("text")
    assert dialog.queue_button.instate(["disabled"])


def test_changing_the_selection_after_planning_requires_a_new_plan(dialog):  # type: ignore[no-untyped-def]
    dialog._plan()
    dialog.calls.plan_reply[0](_plan(dialog.calls.planned[0]))
    assert dialog.queue_button.instate(["!disabled"])

    dialog.upscale_var.set(True)
    dialog._changed()
    assert dialog.plan is None and dialog.queue_button.instate(["disabled"])
    assert "Plan again" in dialog.status_label.cget("text")


def test_a_plan_for_an_older_selection_is_not_queueable(dialog):  # type: ignore[no-untyped-def]
    dialog._plan()
    stale = dialog.calls.planned[0]
    dialog.model_list.selection_set(1)
    dialog.calls.plan_reply[0](_plan(stale))
    assert dialog.plan is None and dialog.queue_button.instate(["disabled"])


def test_an_empty_selection_is_explained_without_planning(dialog):  # type: ignore[no-untyped-def]
    dialog.pack_list.selection_clear(0, "end")
    dialog._plan()
    assert dialog.calls.planned == []
    assert "Pick at least one PromptPack." in dialog.status_label.cget("text")


def test_a_planning_error_is_shown_and_plan_can_be_retried(dialog):  # type: ignore[no-untyped-def]
    dialog._plan()
    dialog.calls.plan_reply[1](ValueError("Txt2img Seed is unavailable."))
    assert "Could not plan the batch. Txt2img Seed is unavailable." in dialog.status_label.cget(
        "text"
    )
    assert dialog.plan_button.instate(["!disabled"])


def test_the_pipeline_tab_button_opens_the_dialog_seeded_from_the_sidebar(monkeypatch, tk_root):  # type: ignore[no-untyped-def]
    from src.controller.app_controller_services import pack_model_batch_service as service
    from src.gui.app_state_v2 import AppStateV2
    from src.gui.sidebar_panel_v2 import SidebarPanelV2
    from tests.gui_v2.test_sidebar_panel_v2_add_to_job import _DummyController, _FakePackListManager

    monkeypatch.setattr("src.gui.sidebar_panel_v2.PromptPackListManager", _FakePackListManager)
    controller = _DummyController()
    controller._background_tasks = object()  # type: ignore[attr-defined]
    panel = SidebarPanelV2(tk_root, controller=controller, app_state=AppStateV2())
    panel._current_pack_names = ["pack-alpha", "pack-beta"]
    panel.pack_listbox.delete(0, "end")
    for name in panel._current_pack_names:
        panel.pack_listbox.insert("end", name)
    panel.pack_listbox.selection_set(1)
    base = panel.get_base_generation_panel()
    monkeypatch.setattr(base, "model_choices", lambda: list(MODELS))
    monkeypatch.setattr(base, "selected_model_name", lambda: MODELS[1][1])
    panel.stage_states["upscale"].set(True)
    seen: list[Any] = []
    monkeypatch.setattr(
        service, "request_batch_plan", lambda app, request, **kw: seen.append((app, request))
    )

    assert panel.batch_builder_button.cget("text") == "Packs × Models…"
    opened: list[BatchBuilderDialog] = []
    monkeypatch.setattr(
        "src.gui.batch_builder_dialog.BatchBuilderDialog.__init__",
        _record_init(opened),
    )
    panel.batch_builder_button.invoke()
    (window,) = opened
    try:
        assert window.selected_packs() == ["pack-beta"]
        assert window.selected_models() == [MODELS[1][1]]
        assert window.upscale_var.get() is True
        window._plan()
        assert seen and seen[0][0] is controller and seen[0][1].pack_ids == ("pack-beta",)
    finally:
        window.destroy()


def _record_init(opened):  # type: ignore[no-untyped-def]
    original = BatchBuilderDialog.__init__

    def init(self, *args, **kwargs):  # type: ignore[no-untyped-def]
        original(self, *args, **kwargs)
        opened.append(self)

    return init


def test_saved_recipes_are_on_by_default_and_the_owner_can_turn_them_off(dialog):  # type: ignore[no-untyped-def]
    assert dialog.use_recipes_var.get() is True
    dialog._plan()
    dialog.calls.plan_reply[0](_plan(dialog.calls.planned[-1]))
    assert dialog.queue_button.instate(["!disabled"])

    dialog.use_recipes_var.set(False)
    dialog._changed()
    assert dialog.queue_button.instate(["disabled"])
    dialog._plan()
    assert dialog.calls.planned[-1].use_recipes is False
