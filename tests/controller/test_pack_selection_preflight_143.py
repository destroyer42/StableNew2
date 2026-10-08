"""Both GUI submission routes consume the same completed, pre-NJR policy."""

from types import SimpleNamespace

import pytest

from src.controller.app_controller import AppController
from src.controller.pipeline_controller import PipelineController
from src.controller.pipeline_controller_services.queue_submission_service import (
    QueueSubmissionService,
)
from src.controller.prompt_pack_preflight import SelectionReviewBridge
from src.gui.app_state_v2 import AppStateV2
from src.prompting.pack_lora_selection import KleinSelectionError, SelectionChoice
from tests.pipeline.test_klein_pack_selection_143 import S, make_builder


@pytest.fixture(autouse=True)
def forge(monkeypatch):
    monkeypatch.setattr(
        "src.image_backends.image_backend_types.configured_image_backend_id", lambda: "forge_webui"
    )


@pytest.mark.parametrize("route", ["add", "run"])
@pytest.mark.parametrize("cancel", [False, True])
def test_actual_app_submission_seams_atomic(tmp_path, route, cancel):
    submissions = []
    service = SimpleNamespace(
        submit_njrs=lambda jobs, policy: submissions.append((jobs, policy))
        or [j.job_id for j in jobs]
    )

    def review(requests):
        return None if cancel else [SelectionChoice("last") for _ in requests]

    builder, entry, _ = make_builder(
        tmp_path, table={"lora_ok": S.COMPATIBLE, "lora_extra": S.COMPATIBLE}, review=review
    )
    pipeline = PipelineController.__new__(PipelineController)
    pipeline._app_state = AppStateV2()
    pipeline._app_state.job_draft.packs = [entry]
    pipeline._prompt_pack_builder = builder
    pipeline._config_manager = builder._config_manager
    pipeline._job_builder = builder._job_builder
    pipeline._job_service = service
    pipeline._app_controller = None
    pipeline._queue_submission_service = QueueSubmissionService(job_service=service)
    pipeline.ensure_run_submission_ready = lambda: True
    app = AppController.__new__(AppController)
    app.app_state = pipeline._app_state
    app._is_shutting_down = False
    app._append_log = lambda _: None
    app._ui_dispatch = lambda fn: fn()
    app._refresh_preview_from_state_async = lambda: None
    if route == "add":
        app._submit_preview_jobs_to_queue_async(pipeline, [], {}, "test")
    else:
        prepared = SimpleNamespace(source="run_now_button", prompt_source="pack", run_config={})
        app._submit_run_to_queue_async(pipeline, prepared, "test")
    if cancel:
        assert submissions == []
    else:
        assert len(submissions) == 1
        assert [t.name for t in submissions[0][0][0].lora_tags] == ["lora_extra"]
        assert submissions[0][1].start_when_idle == (route == "run")


def test_bridge_dispatches_and_rejects_stale_or_hidden(monkeypatch):
    state = SimpleNamespace(job_draft="frozen", current_config={}, content_visibility_mode="sfw")
    ui = []
    app = SimpleNamespace(
        app_state=state,
        _is_shutting_down=False,
        _append_log=lambda _: None,
        _ui_dispatch=lambda fn: fn(),
        _get_ui_root=lambda: object(),
    )
    controller = SimpleNamespace(_app_state=state, _app_controller=app)

    def dialog(_parent, requests, **kwargs):
        assert kwargs["visible"] is False and kwargs["is_current"]()
        ui.append(requests)
        return [SelectionChoice("none")]

    monkeypatch.setattr("src.gui.klein_lora_selection_dialog.review_loras", dialog)
    bridge = SelectionReviewBridge(controller)
    review = bridge.begin([])
    assert review(["request"]) == [SelectionChoice("none")]
    review = bridge.begin([])
    state.job_draft = "changed"
    with pytest.raises(KleinSelectionError, match="cancelled or source changed"):
        review(["old request"])
    assert len(ui) == 1


def test_production_builder_enables_explicit_policy(tmp_path):
    from src.controller.prompt_pack_preflight import get_prompt_pack_builder
    from src.pipeline.job_builder_v2 import JobBuilderV2
    from tests.pipeline.test_prompt_pack_adaptation_140 import KLEIN, _Config

    controller = SimpleNamespace(
        _config_manager=_Config(tmp_path, model=KLEIN), _job_builder=JobBuilderV2()
    )
    builder = get_prompt_pack_builder(controller)
    assert builder._lora_selection_policy is True
    assert isinstance(builder._selection_review, SelectionReviewBridge)
    assert get_prompt_pack_builder(controller) is builder


def test_old_request_and_tk_thread_cannot_prepare_evidence():
    import threading

    from src.contracts import PackJobEntry
    from src.controller.global_prompt_policy_service import overlay_current_policy

    old = PackJobEntry(pack_id="old", pack_name="Old", config_snapshot={})
    new = PackJobEntry(pack_id="new", pack_name="New", config_snapshot={})
    state = SimpleNamespace(job_draft=SimpleNamespace(packs=[new]))
    app = SimpleNamespace(_is_shutting_down=False, _ui_thread_id=None)
    controller = SimpleNamespace(_app_state=state, _app_controller=app)
    bridge = SelectionReviewBridge(controller)
    stale = bridge.begin(overlay_current_policy(controller, [old]))
    with pytest.raises(KleinSelectionError, match="source changed"):
        stale.validate()
    current = bridge.begin(overlay_current_policy(controller, [new]))
    current.validate()
    app._ui_thread_id = threading.get_ident()
    with pytest.raises(KleinSelectionError, match="background Preview"):
        current.validate()
    app._ui_thread_id = None
    state.job_draft.packs = [old]
    assert current.cancelled()


def test_automatic_selection_rejects_change_during_evidence(tmp_path, monkeypatch):
    from src.controller.global_prompt_policy_service import overlay_current_policy
    from src.pipeline.compile_evidence import CompileEvidence

    builder, entry, _ = make_builder(tmp_path, table={"lora_ok": S.COMPATIBLE})
    state = SimpleNamespace(job_draft=SimpleNamespace(packs=[entry]))
    app = SimpleNamespace(
        _is_shutting_down=False,
        _ui_thread_id=None,
        _ui_dispatch=lambda fn: fn(),
        _append_log=lambda _: None,
    )
    controller = SimpleNamespace(_app_state=state, _app_controller=app)
    builder._selection_review = SelectionReviewBridge(controller)

    def prepare(*_, **__):
        state.job_draft.packs = []

    monkeypatch.setattr(CompileEvidence, "prepare_lora_selection", prepare)
    monkeypatch.setattr(
        builder._job_builder, "build_jobs", lambda **_: pytest.fail("stale source admitted")
    )
    with pytest.raises(KleinSelectionError, match="source changed"):
        builder.build_jobs(overlay_current_policy(controller, [entry]))
