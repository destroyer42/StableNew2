"""PR-IMG-CNET-230: the "Create map from image" flow, dialog and panel attachment (fakes only; no model, GPU or network)."""

from __future__ import annotations

import io
import threading
from collections import deque
from pathlib import Path
from typing import Any

import pytest
from PIL import Image

from src.conditioning.reference_map.contracts import (
    MapRequest,
    MethodIdentity,
    PreparedMap,
    ProviderUnavailable,
    ReferenceMapError,
    SourceFacts,
)
from src.conditioning.reference_map.library import SavedMap
from src.gui.widgets.controlnet_units_panel import ControlNetUnitsPanel
from src.gui_v2.reference_map_flow import FlowState, ReferenceMapFlow
from tests.integration.test_pr_img_cnet_220 import declaration


def _png(width: int = 96, height: int = 64) -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", (width, height), (30, 60, 90)).save(buffer, format="PNG")
    return buffer.getvalue()


def _prepared(modality: str = "canny", source: Path | None = None, warnings=()) -> PreparedMap:
    png = _png()
    facts = SourceFacts("a" * 64, 10, "PNG", 96, 64, "b" * 64, False)
    return PreparedMap(
        modality=modality,
        png=png,
        sha256="c" * 64,
        width=96,
        height=64,
        source=facts,
        method=MethodIdentity("m", 1, {}),
        warnings=tuple(warnings),
        source_path=source,
    )


class FakeService:
    def __init__(self, *, reasons: tuple[str, ...] = ()) -> None:
        self.reasons = reasons
        self.prepare_calls: list[tuple[MapRequest, Any]] = []
        self.save_calls: list[PreparedMap] = []
        self.prepare_error: Exception | None = None
        self.save_error: Exception | None = None
        self.threads: list[int] = []

    def availability(self, modality: str) -> tuple[str, ...]:
        return self.reasons

    def prepare(self, request: MapRequest, cancel: Any = None) -> PreparedMap:
        self.threads.append(threading.get_ident())
        self.prepare_calls.append((request, cancel))
        if self.prepare_error is not None:
            raise self.prepare_error
        return _prepared(request.modality, request.source, ("pose_no_hands",))

    def save(self, prepared: PreparedMap) -> SavedMap:
        self.threads.append(threading.get_ident())
        self.save_calls.append(prepared)
        if self.save_error is not None:
            raise self.save_error
        return SavedMap(f"created/{prepared.modality}-x.png", prepared.sha256, 5, 96, 64, True)


class Rig:
    """Deterministic scheduling: spawned work and posted completions run only when the test says so."""

    def __init__(self, service: FakeService, **flow_options: Any) -> None:
        self.work: deque[Any] = deque()
        self.posted: deque[Any] = deque()
        self.views: list[Any] = []
        self.threads: list[int] = []
        self.attached: list[tuple[SavedMap, PreparedMap]] = []
        self.flow = ReferenceMapFlow(
            service,
            post=self.posted.append,
            on_change=self._changed,
            spawn=lambda target, name: self.work.append(target),
            **flow_options,
        )

    def _changed(self, view: Any) -> None:
        self.threads.append(threading.get_ident())
        self.views.append(view)

    def run_work(self) -> None:
        self.work.popleft()()

    def drain(self) -> None:
        while self.posted:
            self.posted.popleft()()


# ---------------------------------------------------------------------------------------------- flow


def test_prepare_then_save_and_use_happy_path(tmp_path) -> None:
    service = FakeService()
    rig = Rig(service)
    flow = rig.flow
    flow.set_modality("openpose")
    flow.set_source(tmp_path / "me.png")
    assert flow.view.can_prepare and not flow.view.can_save
    flow.prepare()
    assert (
        flow.view.state is FlowState.PREPARING and flow.view.can_cancel and not flow.view.can_choose
    )
    rig.run_work()
    assert (
        flow.view.state is FlowState.PREPARING
    )  # nothing changes until the GUI thread drains the result
    rig.drain()
    view = flow.view
    assert view.state is FlowState.READY and view.can_save and view.preview_png
    assert "Nothing is saved yet" in view.message
    assert view.warnings == ("No hands were detected; the map has no hand keypoints.",)
    assert service.save_calls == []
    flow.save(lambda saved, prepared: rig.attached.append((saved, prepared)))
    assert flow.view.state is FlowState.SAVING and not flow.view.can_save
    rig.run_work()
    rig.drain()
    assert flow.view.state is FlowState.SAVED and "No job was queued" in flow.view.message
    assert [saved.identity for saved, _ in rig.attached] == ["created/openpose-x.png"]
    assert all(
        thread == threading.get_ident() for thread in rig.threads
    )  # views only on the GUI thread


def test_an_unavailable_provider_says_why_starts_nothing_and_substitutes_nothing(tmp_path) -> None:
    service = FakeService(reasons=("runtime_missing:onnxruntime",))
    rig = Rig(service)
    rig.flow.set_modality("openpose")
    rig.flow.set_source(tmp_path / "me.png")
    rig.flow.prepare()
    view = rig.flow.view
    assert view.state is FlowState.FAILED and view.failure_code == "provider_unavailable"
    assert view.reasons == ("runtime_missing:onnxruntime",)
    assert "no other map type is substituted" in view.message
    assert not rig.work and service.prepare_calls == []
    assert view.can_choose and not view.can_save


def test_a_newer_source_wins_and_the_older_result_is_dropped(tmp_path) -> None:
    service = FakeService()
    rig = Rig(service)
    rig.flow.set_source(tmp_path / "a.png")
    rig.flow.prepare()
    rig.flow.set_source(tmp_path / "b.png")  # the operator switched source mid-flight
    assert rig.flow.view.state is FlowState.IDLE and rig.flow.view.source_name == "b.png"
    rig.run_work()  # the stale worker finishes anyway
    request, cancel_check = service.prepare_calls[0]
    assert cancel_check() is True  # it was told to stop
    rig.drain()
    assert rig.flow.view.state is FlowState.IDLE and rig.flow.prepared is None
    assert rig.flow.view.preview_png is None
    rig.flow.prepare()
    rig.run_work()
    rig.drain()
    assert rig.flow.view.state is FlowState.READY
    assert service.prepare_calls[1][0].source.name == "b.png"


def test_cancel_discards_everything_and_a_late_result_cannot_reappear(tmp_path) -> None:
    service = FakeService()
    rig = Rig(service)
    rig.flow.set_source(tmp_path / "a.png")
    rig.flow.prepare()
    rig.flow.cancel()
    assert "Cancelled" in rig.flow.view.message and rig.flow.view.can_prepare
    rig.run_work()
    rig.drain()
    assert rig.flow.prepared is None and rig.flow.view.preview_png is None
    assert not rig.flow.view.can_save


def test_cancelled_error_from_the_worker_is_not_a_failure(tmp_path) -> None:
    service = FakeService()
    service.prepare_error = ReferenceMapError("cancelled", "Cancelled.")
    rig = Rig(service)
    rig.flow.set_source(tmp_path / "a.png")
    rig.flow.prepare()
    rig.run_work()
    rig.drain()
    assert rig.flow.view.state is FlowState.IDLE and "Cancelled" in rig.flow.view.message


def test_changing_the_map_type_after_a_preview_clears_it(tmp_path) -> None:
    rig = Rig(FakeService())
    rig.flow.set_source(tmp_path / "a.png")
    rig.flow.prepare()
    rig.run_work()
    rig.drain()
    assert rig.flow.view.can_save
    rig.flow.set_modality("depth")
    assert (
        rig.flow.prepared is None
        and not rig.flow.view.can_save
        and rig.flow.view.preview_png is None
    )
    rig.flow.save(lambda *_: rig.attached.append(None))  # no-op: nothing is prepared
    assert not rig.work and rig.attached == []


def test_closing_drops_late_results_and_attaches_nothing(tmp_path) -> None:
    service = FakeService()
    rig = Rig(service)
    rig.flow.set_source(tmp_path / "a.png")
    rig.flow.prepare()
    rig.flow.close()
    rig.run_work()
    rig.drain()
    assert rig.flow.prepared is None
    rig2 = Rig(FakeService())
    rig2.flow.set_source(tmp_path / "a.png")
    rig2.flow.prepare()
    rig2.run_work()
    rig2.drain()
    rig2.flow.save(lambda saved, prepared: rig2.attached.append((saved, prepared)))
    rig2.flow.close()
    rig2.run_work()
    rig2.drain()
    assert rig2.attached == []  # the dialog was closed while saving: nothing is attached


def test_source_drift_at_save_discards_the_preview(tmp_path) -> None:
    service = FakeService()
    service.save_error = ReferenceMapError("source_changed", "The source image changed.")
    rig = Rig(service)
    rig.flow.set_source(tmp_path / "a.png")
    rig.flow.prepare()
    rig.run_work()
    rig.drain()
    rig.flow.save(lambda *_: rig.attached.append(None))
    rig.run_work()
    rig.drain()
    view = rig.flow.view
    assert view.state is FlowState.FAILED and view.failure_code == "source_changed"
    assert rig.flow.prepared is None and not view.can_save and view.preview_png is None
    assert rig.attached == []


def test_other_save_failures_keep_the_preview_and_attach_nothing(tmp_path) -> None:
    service = FakeService()
    service.save_error = ReferenceMapError("library_write_failed", "Could not write.")
    rig = Rig(service)
    rig.flow.set_source(tmp_path / "a.png")
    rig.flow.prepare()
    rig.run_work()
    rig.drain()
    rig.flow.save(lambda *_: rig.attached.append(None))
    rig.run_work()
    rig.drain()
    assert rig.flow.view.state is FlowState.READY and rig.flow.view.can_save
    assert "nothing was attached" in rig.flow.view.message and rig.attached == []


def test_save_is_gated_by_the_attachment_plan(tmp_path) -> None:
    rig = Rig(FakeService(), save_gate=lambda modality: False)
    rig.flow.set_source(tmp_path / "a.png")
    rig.flow.prepare()
    rig.run_work()
    rig.drain()
    assert rig.flow.view.state is FlowState.READY and not rig.flow.view.can_save
    rig.flow.save(lambda *_: rig.attached.append(None))
    assert rig.flow.view.state is FlowState.READY and not rig.work


def test_unexpected_worker_exceptions_become_content_free_failures(tmp_path) -> None:
    service = FakeService()
    service.prepare_error = RuntimeError(f"boom at {tmp_path}")
    rig = Rig(service)
    rig.flow.set_source(tmp_path / "a.png")
    rig.flow.prepare()
    rig.run_work()
    rig.drain()
    assert rig.flow.view.state is FlowState.FAILED
    assert str(tmp_path) not in rig.flow.view.message


def test_the_real_thread_worker_never_mutates_the_view_off_the_gui_thread(tmp_path) -> None:
    service = FakeService()
    posted: deque[Any] = deque()
    views: list[int] = []
    done = threading.Event()

    def spawn(target, name):
        thread = threading.Thread(target=lambda: (target(), done.set()))
        thread.start()
        return thread

    flow = ReferenceMapFlow(
        service,
        post=posted.append,
        on_change=lambda view: views.append(threading.get_ident()),
        spawn=spawn,
    )
    flow.set_source(tmp_path / "a.png")
    flow.prepare()
    assert done.wait(10)
    while posted:
        posted.popleft()()
    assert flow.view.state is FlowState.READY
    assert set(views) == {threading.get_ident()}
    assert service.threads and service.threads[0] != threading.get_ident()


# ---------------------------------------------------------------------------------------------- dialog and panel (Tk)


@pytest.fixture
def panel(tk_root, tmp_path):
    service = FakeService()
    changes: list[int] = []
    widget = ControlNetUnitsPanel(
        tk_root,
        on_change_callback=lambda: changes.append(1),
        registry_factory=lambda: None,
        map_service_factory=lambda: service,
        confirm=lambda _title, _message: True,
        lazy=True,
    )
    widget.pack()
    widget.fake_service, widget.changes = service, changes
    widget.refresh_library = lambda: changes.append("refresh")  # the scan has its own tests
    yield widget
    widget.destroy()


@pytest.mark.gui
def test_attach_plan_replaces_adds_or_refuses_explicitly(panel) -> None:
    panel.set_declaration(declaration("canny"))
    ok, text = panel.map_attach_plan("canny")
    assert ok and "set the map of unit 1" in text
    ok, text = panel.map_attach_plan("depth")
    assert ok and "add a new" in text
    panel.set_declaration(declaration("canny", "depth"))
    assert panel.map_attach_plan("openpose")[0] is False  # a third unit is never added
    assert (
        panel.map_attach_plan("depth")[0] is False
    )  # only the selected unit (canny) can be replaced
    panel._selected = 1
    assert panel.map_attach_plan("depth")[0] is True
    panel.set_legacy_declaration({"contract": "openpose.v1"})
    ok, text = panel.map_attach_plan("canny")
    assert not ok and "legacy OpenPose" in text


@pytest.mark.gui
def test_save_and_use_replaces_the_selected_units_map_once(panel, tmp_path) -> None:
    panel.set_declaration(declaration("canny"))
    before = panel.get_declaration()["units"][0]
    saved = SavedMap("created/canny-x.png", "c" * 64, 5, 96, 64, True)
    panel.attach_created_map(saved, _prepared("canny"))
    unit = panel.get_declaration()["units"][0]
    assert unit["asset"] == "created/canny-x.png"
    assert {k: v for k, v in unit.items() if k != "asset"} == {
        k: v for k, v in before.items() if k != "asset"
    }
    assert panel.changes.count(1) == 1  # one dirty callback: an explicit operator edit


@pytest.mark.gui
def test_save_and_use_adds_a_unit_of_the_created_type_when_there_is_room(panel) -> None:
    panel.set_declaration(declaration("canny"))
    panel.attach_created_map(
        SavedMap("created/depth-x.png", "d" * 64, 5, 96, 64, True), _prepared("depth")
    )
    units = panel.get_declaration()["units"]
    assert [u["modality"] for u in units] == ["canny", "depth"]
    assert units[1]["asset"] == "created/depth-x.png" and units[1]["model"] == ""
    # a full panel refuses a third unit instead of overwriting anything
    before = panel.get_declaration()
    panel.attach_created_map(
        SavedMap("created/openpose-x.png", "e" * 64, 5, 96, 64, True), _prepared("openpose")
    )
    assert panel.get_declaration() == before


@pytest.mark.gui
def test_dialog_end_to_end_with_stale_result_unavailable_reason_and_threading(
    panel, tmp_path, tk_root
) -> None:
    panel.set_declaration(declaration("canny"))
    pending: deque[Any] = deque()
    service = panel.fake_service
    panel._map_service_factory = lambda: service
    sources = iter(["a.png", "b.png"])
    from src.gui.widgets.reference_map_dialog import ReferenceMapDialog

    dialog = ReferenceMapDialog(
        panel,
        service=service,
        modality="canny",
        attach_plan=panel.map_attach_plan,
        on_attached=panel.attach_created_map,
        choose_file=lambda: str(tmp_path / next(sources)),
        spawn=lambda target, name: pending.append(target),
    )
    panel._creator = dialog
    try:
        assert str(dialog.save_button.cget("state")) == "disabled"
        assert "set the map of unit 1" in dialog.plan_var.get()
        dialog._pick()  # source a
        dialog.prepare_button.invoke()
        assert str(dialog.cancel_button.cget("state")) == "normal"
        dialog._pick()  # the operator switches to source b while a is still running
        pending.popleft()()  # a's worker finishes late
        dialog._pump()
        assert dialog.flow.view.state is FlowState.IDLE and dialog.flow.prepared is None
        dialog.prepare_button.invoke()
        pending.popleft()()
        dialog._pump()
        assert dialog.flow.view.state is FlowState.READY
        assert str(dialog.save_button.cget("state")) == "normal"
        assert dialog.facts_var.get().startswith("96×64 px")
        assert dialog._photo is not None
        dialog.save_button.invoke()
        pending.popleft()()
        dialog._pump()
        assert panel.get_declaration()["units"][0]["asset"] == "created/canny-x.png"
        assert "No job was queued" in dialog.status_var.get()
    finally:
        dialog.close()


@pytest.mark.gui
def test_dialog_shows_reason_codes_and_leaves_manual_selection_available(panel, tmp_path) -> None:
    panel.set_declaration(declaration("openpose"))
    service = FakeService(reasons=("runtime_missing:onnxruntime",))
    from src.gui.widgets.reference_map_dialog import ReferenceMapDialog

    dialog = ReferenceMapDialog(
        panel,
        service=service,
        modality="openpose",
        attach_plan=panel.map_attach_plan,
        on_attached=panel.attach_created_map,
        choose_file=lambda: str(tmp_path / "me.png"),
        spawn=lambda target, name: None,
    )
    try:
        dialog._pick()
        assert "runtime_missing:onnxruntime" in dialog.availability_var.get()
        dialog.prepare_button.invoke()
        assert "runtime_missing:onnxruntime" in dialog.reasons_var.get()
        assert service.prepare_calls == []
        assert (
            str(panel.browser.listbox.cget("state")) == "normal"
        )  # manual pre-rendered selection stays
        assert str(panel.create_map_button.cget("state")) == "normal"
    finally:
        dialog.close()


@pytest.mark.gui
def test_the_panel_hosts_one_dialog_and_closes_it_with_itself(panel, tk_root) -> None:
    panel.set_declaration(declaration("canny"))
    panel.open_map_creator()
    first = panel._creator
    assert first is not None
    panel.open_map_creator()
    assert panel._creator is first  # a second click raises the same window
    panel.destroy()
    assert panel._creator is None


@pytest.mark.gui
def test_creating_and_saving_a_map_never_submits_a_job(panel, tmp_path, monkeypatch) -> None:
    from src.controller.job_service import JobService
    from src.pipeline.pipeline_runner import PipelineRunner

    def forbidden(*args, **kwargs):
        raise AssertionError("map creation reached the queue or runner")

    monkeypatch.setattr(JobService, "submit_njrs", forbidden)
    monkeypatch.setattr(PipelineRunner, "run_njr", forbidden)
    panel.set_declaration(declaration("canny"))
    rig = Rig(panel.fake_service, save_gate=lambda modality: panel.map_attach_plan(modality)[0])
    rig.flow.set_source(tmp_path / "a.png")
    rig.flow.prepare()
    rig.run_work()
    rig.drain()
    rig.flow.save(panel.attach_created_map)
    rig.run_work()
    rig.drain()
    assert panel.get_declaration()["units"][0]["asset"] == "created/canny-x.png"


def test_unavailable_error_carries_reasons_for_the_ui() -> None:
    error = ProviderUnavailable("down", reasons=("a", "b"))
    assert error.reasons == ("a", "b") and error.code == "provider_unavailable"
