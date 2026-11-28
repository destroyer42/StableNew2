"""The desktop's LTX-2.5 licence confirmation: asked once per Queue, never saved, never defaulted to yes.

Real Tk widgets over the real Video Workflow controller and a recording job service; the dialog itself is replaced.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest

from src.gui import licence_attestation_dialog as dialog
from src.gui.view_contracts.video_batch_contract import BatchQueueWork, VideoBatchSession
from src.gui.views.storyboard_tab_frame_v2 import StoryboardTabFrameV2
from src.gui.views.video_eval_panel_v2 import VideoEvalPanel
from src.gui.views.video_workflow_batch_panel_v2 import WorkflowBatchPanel
from src.gui.views.video_workflow_continue_v2 import ContinueClipHost
from src.gui.views.video_workflow_sequence_panel_v2 import WorkflowSequencePanel
from src.gui.views.video_workflow_tab_frame_v2 import VideoWorkflowTabFrameV2
from src.video.licence_attestation import (
    ATTESTATION_KEY,
    LTX25_ATTESTATION_TEXT,
    LTX25_ATTESTATION_VERSION,
    recorded_attestation,
)
from src.video.workflow_catalog_ltx25 import LTX25_ID
from tests.helpers.make_video_313 import RECOMMENDED_ID, make_app, make_image, make_window

pytestmark = pytest.mark.gui


class _Ask:
    def __init__(self, answer: bool) -> None:
        self.answer = answer
        self.calls: list[tuple[str, str, dict[str, Any]]] = []

    def __call__(self, title: str, message: str, **options: Any) -> bool:
        self.calls.append((title, message, options))
        return self.answer


@pytest.fixture
def asked(monkeypatch):
    def install(answer: bool) -> _Ask:
        ask = _Ask(answer)
        monkeypatch.setattr(dialog.messagebox, "askyesno", ask)
        return ask

    return install


def test_nothing_is_asked_for_an_engine_without_a_declared_confirmation(asked) -> None:
    ask = asked(False)

    assert dialog.ask_licence_attestation(None, [RECOMMENDED_ID]) == {}
    assert ask.calls == []


def test_the_dialog_states_the_text_and_defaults_to_no(asked) -> None:
    ask = asked(True)

    record = dialog.ask_licence_attestation(None, [LTX25_ID], job_count=3)

    assert record["attested"] is True
    assert record["text_version"] == LTX25_ATTESTATION_VERSION and record["attested_at"]
    [(_title, message, options)] = ask.calls
    assert LTX25_ATTESTATION_TEXT in message and "all 3 LTX-2.5 jobs" in message
    assert options["default"] == dialog.messagebox.NO


def test_declining_records_nothing(asked) -> None:
    asked(False)

    assert dialog.ask_licence_attestation(None, [LTX25_ID]) is None


@pytest.fixture
def tab_env(tk_root, tmp_path):
    app, controller, service = make_app(tmp_path)
    controller.rife_available = lambda: False
    tab = VideoWorkflowTabFrameV2(tk_root, app_controller=app, app_state=SimpleNamespace())
    app.main_window = make_window(tab)
    tab.show_experimental_var.set(True)
    tab.workflow_var.set(LTX25_ID)
    tab.source_image_var.set(make_image(tmp_path / "source.png", (576, 1024)))
    state = tab.get_video_workflow_state()
    state.update(prompt="she waves", workflow_id=LTX25_ID, workflow_version="1.0.0")
    tab.restore_video_workflow_state(state)
    return tab, service


def test_queue_asks_each_time_and_declining_queues_nothing(tab_env, asked) -> None:
    tab, service = tab_env
    ask = asked(False)

    tab._on_submit()

    assert len(ask.calls) == 1 and service.submitted == []
    assert "Not queued" in tab.status_var.get()

    ask = asked(True)
    tab._on_submit()
    tab._on_submit()

    assert len(ask.calls) == 2, tab.status_var.get()
    assert [recorded_attestation(njr.extra_metadata) is not None for njr in service.submitted] == [
        True,
        True,
    ]
    assert ATTESTATION_KEY not in tab.get_video_workflow_state(for_submission=True)


# --- the other Queue buttons: each asks, and declining queues nothing ------------------------------


def _ltx_job() -> SimpleNamespace:
    return SimpleNamespace(config={"video_workflow": {"workflow_id": LTX25_ID}})


def _never(*_args: Any, **_kwargs: Any) -> Any:
    raise AssertionError("a declined confirmation must queue nothing")


def test_declining_on_many_images_keeps_the_preview_and_queues_nothing(asked) -> None:
    ask = asked(False)
    said: list[str] = []
    work = BatchQueueWork(plan=SimpleNamespace(njrs=[_ltx_job(), _ltx_job()]))
    panel = SimpleNamespace(
        _read_form=dict,
        _session=SimpleNamespace(begin_queue=lambda _form: work, abandon_queue=said.append),
        refresh=lambda: None,
        _work_runner=_never,
    )

    WorkflowBatchPanel._on_queue(panel)

    assert said == [dialog.NOT_CONFIRMED] and "all 2 LTX-2.5 jobs" in ask.calls[0][1]


def test_the_batch_session_hands_the_confirmation_to_its_one_submit() -> None:
    given: list[dict[str, Any]] = []
    session = object.__new__(VideoBatchSession)
    session._submit_plan = lambda plan, **kwargs: given.append(kwargs)

    session.run_queue(BatchQueueWork(plan=object()))
    session.run_queue(BatchQueueWork(plan=object(), attestation={"attested": True}))

    assert given == [{}, {"attestation": {"attested": True}}]


def test_declining_a_sequence_queues_nothing(asked) -> None:
    ask = asked(False)
    status: list[str] = []
    shots = [SimpleNamespace(prompt="a", frame_count=25, keyframe_path="")]
    panel = SimpleNamespace(
        _read_form=lambda: ("source.png", {"workflow_id": LTX25_ID}),
        shots=lambda: shots,
        _block_reason=lambda: "",
        _frame_counts=lambda: {"25 frames": 25},
        status_var=SimpleNamespace(set=status.append),
        _capture_storyboard=_never,
    )
    sequence = pytest.MonkeyPatch()
    sequence.setattr(
        "src.gui.views.video_workflow_sequence_panel_v2.sequence_block_reason", lambda **_: ""
    )
    try:
        WorkflowSequencePanel._on_queue(panel)
    finally:
        sequence.undo()

    assert len(ask.calls) == 1 and status == [dialog.NOT_CONFIRMED]


def test_declining_a_storyboard_take_queues_nothing(asked) -> None:
    ask = asked(False)
    said: list[str] = []
    tree = SimpleNamespace(
        root=SimpleNamespace(to_dict=lambda: {"settings": {"workflow_id": LTX25_ID}})
    )
    tab = SimpleNamespace(
        _busy=False,
        _build_request=lambda: SimpleNamespace(mode="parallel", rows=(1, 2, 3)),
        tree=tree,
        _say=said.append,
        _service=_never,
    )

    StoryboardTabFrameV2.queue(tab)

    assert said == [dialog.NOT_CONFIRMED] and "all 3 LTX-2.5 jobs" in ask.calls[0][1]


def test_declining_a_continuation_queues_nothing(asked) -> None:
    ask = asked(False)
    refused: list[str] = []
    host = object.__new__(ContinueClipHost)
    clip = SimpleNamespace(takes_storyboard=True, workflow_id=LTX25_ID, workflow_label="LTX")
    host.opening = SimpleNamespace(clip=clip)
    host.queueing = False
    host._widget = None
    host._service = lambda: object()
    host._on_refused = refused.append
    host._on_status = _never

    host.queue({"workflow_id": LTX25_ID}, None)

    assert len(ask.calls) == 1 and refused == [dialog.NOT_CONFIRMED] and not host.queueing


@pytest.mark.parametrize("answer", [False, True])
def test_an_eval_run_asks_once_for_its_ltx_jobs(asked, answer: bool) -> None:
    ask = asked(answer)
    status: list[str] = []
    started: list[Any] = []
    submitted: list[dict[str, Any]] = []
    plan = SimpleNamespace(
        eligible=True,
        experimental_arms=(),
        jobs=[
            SimpleNamespace(njr=_ltx_job()),
            SimpleNamespace(njr=SimpleNamespace(config={"video_workflow": {"workflow_id": "x"}})),
            SimpleNamespace(njr=_ltx_job()),
        ],
        summary=lambda: "3 jobs",
    )
    panel = SimpleNamespace(
        status_var=SimpleNamespace(set=status.append),
        _confirm=lambda *_args: True,
        _busy=False,
        _closed=False,
        _update_controls=lambda: None,
        _start=lambda _name, work, *_args: started.append(work),
        _controller=lambda: SimpleNamespace(
            submit_eval_run=lambda _plan, **kwargs: submitted.append(kwargs)
        ),
        _finish_queue=None,
    )
    preview = pytest.MonkeyPatch()
    preview.setattr("src.gui.views.video_eval_panel_v2._preview_text", lambda _plan: "preview")
    try:
        VideoEvalPanel._finish_preview(panel, SimpleNamespace(error="", value=plan))
    finally:
        preview.undo()
    for work in started:
        work()

    assert len(ask.calls) == 1 and "all 2 LTX-2.5 jobs" in ask.calls[0][1]
    if answer:
        assert submitted[0]["attestation"]["text_version"] == LTX25_ATTESTATION_VERSION
    else:
        assert started == [] and dialog.NOT_CONFIRMED in status[-1]
