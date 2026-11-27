"""ASSIST-FIX: the Motion field's Suggest and Undo. Real Tk widgets; the AI service is a stand-in, no network."""

from __future__ import annotations

import time
from types import SimpleNamespace

import pytest

from src.ai_assist.contracts import (
    SUGGESTION_SCHEMA_ID,
    AssistOutcome,
    AssistSuggestion,
    OutcomeCode,
    SuggestionKind,
)
from src.ai_assist.remote_preview import DEFAULT_MODEL, ENDPOINT, RUNTIME_VERSION, RemoteApproval
from src.ai_assist.service import Submission
from src.gui.views.video_workflow_tab_frame_v2 import VideoWorkflowTabFrameV2
from src.video.motion_presets import FIELD_MOTION_PHRASE
from tests.helpers.make_video_313 import make_app, make_image, make_window

pytestmark = pytest.mark.gui

APPROVAL = RemoteApproval(ENDPOINT, DEFAULT_MODEL, "a" * 64, RUNTIME_VERSION)
PHRASE = "the camera pushes in slowly"


class FakeAi:
    def __init__(self) -> None:
        self.requests = []
        self.done = None
        self.approval = APPROVAL
        self.blocked = None

    def remote_preview(self):
        return SimpleNamespace(approval=self.approval), ""

    def availability(self):
        return (self.blocked, "blocked here") if self.blocked else (None, "ready")

    def submit(self, request, on_done):
        self.requests.append(request)
        self.done = on_done
        return Submission(True)

    def answer(self, code=OutcomeCode.SUGGESTION):
        request = self.requests[-1]
        suggestion = None
        if code is OutcomeCode.SUGGESTION:
            suggestion = AssistSuggestion(
                SUGGESTION_SCHEMA_ID,
                SuggestionKind.MOTION_PHRASE,
                request.request_id,
                motion_phrase=PHRASE,
            )
        self.done(AssistOutcome(code, request.request_id, suggestion=suggestion))


@pytest.fixture
def env(tk_root, tmp_path):
    app, controller, _service = make_app(tmp_path)
    controller.rife_available = lambda: False
    ai = FakeAi()
    app.ai_assist = ai
    tab = VideoWorkflowTabFrameV2(tk_root, app_controller=app, app_state=SimpleNamespace())
    app.main_window = make_window(tab)
    tab.prompt_text.insert("1.0", "a barn in a field")
    tab.source_image_var.set(make_image(tmp_path / "source.png"))
    yield SimpleNamespace(tab=tab, ai=ai, panel=tab.motion_intent_panel, root=tk_root)
    tab.destroy()


def press_suggest(env) -> None:
    before = len(env.ai.requests)
    env.panel.suggest_button.invoke()
    deadline = time.monotonic() + 10
    while len(env.ai.requests) == before and time.monotonic() < deadline:
        env.root.update()
        time.sleep(0.01)
    assert len(env.ai.requests) == before + 1, env.tab.status_var.get()


def phrase(env) -> str:
    return env.panel.phrase_var.get()


def test_suggest_sends_the_image_and_prompt_and_applies_the_phrase(env) -> None:
    assert not env.panel.undo_button.winfo_manager()
    press_suggest(env)
    request = env.ai.requests[-1]
    assert request.kind is SuggestionKind.MOTION_PHRASE
    assert request.positive_text == "a barn in a field" and request.image_jpeg[:2] == b"\xff\xd8"
    assert "disabled" in env.panel.suggest_button.state()
    env.ai.answer()
    assert phrase(env) == PHRASE and FIELD_MOTION_PHRASE in env.tab._pins.pinned
    assert env.panel.undo_button.winfo_manager()
    assert "disabled" not in env.panel.suggest_button.state()


def test_undo_restores_the_text_and_the_pin_state(env) -> None:
    env.panel.phrase_var.set("")
    env.tab._pins.pinned.discard(FIELD_MOTION_PHRASE)
    press_suggest(env)
    env.ai.answer()
    env.panel.undo_button.invoke()
    assert phrase(env) == "" and FIELD_MOTION_PHRASE not in env.tab._pins.pinned
    assert not env.panel.undo_button.winfo_manager()


def test_undo_leaves_a_phrase_edited_since_alone(env) -> None:
    press_suggest(env)
    env.ai.answer()
    env.panel.phrase_var.set("my own words")
    env.panel.undo_button.invoke()
    assert phrase(env) == "my own words"


@pytest.mark.parametrize("changed", ["phrase", "prompt", "source"])
def test_nothing_is_applied_if_the_form_changed_while_waiting(env, changed, tmp_path) -> None:
    press_suggest(env)
    if changed == "phrase":
        env.panel.phrase_var.set("typed meanwhile")
    elif changed == "prompt":
        env.tab.prompt_text.insert("end", " at night")
    else:
        env.tab.source_image_var.set(make_image(tmp_path / "other.png"))
    before = phrase(env)
    env.ai.answer()
    assert phrase(env) == before and "not applied" in env.tab.status_var.get()


def test_a_refusal_changes_nothing_and_says_so(env) -> None:
    press_suggest(env)
    env.ai.answer(OutcomeCode.REFUSED_BY_MODEL)
    assert phrase(env) == "" and "refused" in env.tab.status_var.get()
    assert "disabled" not in env.panel.suggest_button.state()


@pytest.mark.parametrize("problem", ["no_remote", "blocked", "no_source"])
def test_an_unusable_setup_sends_nothing(env, problem) -> None:
    if problem == "no_remote":
        env.ai.approval = None
    elif problem == "blocked":
        env.ai.blocked = OutcomeCode.BUSY
    else:
        env.tab.source_image_var.set("")
    env.panel.suggest_button.invoke()
    env.root.update()
    assert not env.ai.requests and env.tab.status_var.get()
