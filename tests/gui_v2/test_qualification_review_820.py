"""Real Tk guided pairing with synthetic images, existing writer and temporary state."""

import copy
from types import SimpleNamespace

import pytest
from PIL import Image

from src.controller.app_controller_services.background_task_coordinator import (
    BackgroundTaskCoordinator,
)
from src.gui.controllers.learning_controller import LearningController
from src.gui.learning_state import LearningState
from src.gui.views.qualification_review_window import QualificationReviewWindow
from src.learning.learning_record import LearningRecordWriter
from tests.gui_v2.tk_test_utils import get_shared_tk_root
from tests.learning_v2.test_qualification_review_820 import study as study_fixture


@pytest.fixture
def view(tmp_path, monkeypatch):
    root = get_shared_tk_root()
    if root is None:
        pytest.skip("Tk display unavailable")
    monkeypatch.setattr(
        "src.gui.view_contracts.edit_work_runner.coordinator_factory",
        lambda _widget: BackgroundTaskCoordinator(run_inline=True),
    )
    e, plan, _ratings = study_fixture.__wrapped__(tmp_path)
    e.metadata["evidence_proposal"] = {"proposal_id": "proposal"}
    for variant in plan:
        for ref in variant.image_refs:
            Image.new("RGB", (16, 16), "blue").save(ref)
    state = LearningState()
    state.current_experiment, state.plan = e, plan
    controller = LearningController(
        state, learning_record_writer=LearningRecordWriter(tmp_path / "ratings.jsonl")
    )
    controller.refresh_recommendations = lambda: None
    import tkinter.ttk as ttk

    panel = ttk.Frame(root)
    panel._get_learning_controller = lambda: controller
    window = QualificationReviewWindow(panel)
    root.update()
    yield SimpleNamespace(window=window, controller=controller, state=state, root=root, panel=panel)
    if window.winfo_exists():
        window.destroy()
    panel.destroy()
    root.update()


def test_each_card_is_own_draft_and_saved_rating_and_save_advances(view):
    window, controller = view.window, view.controller
    assert len(window.findings.pairs) == 6
    assert window.details.is_expanded() is False
    a, b = window.cards
    assert a.sample.seed == b.sample.seed == 42
    a.rating.set(3)
    a.stage()
    assert controller.get_review_draft(a.sample.image_ref)["overall_rating"] == 3
    assert controller.get_review_draft(b.sample.image_ref) is None
    b.rating.set(5)
    refs = [c.sample.image_ref for c in window.cards]
    window._save_next()
    assert [controller.get_rating_for_image(ref) for ref in refs] == [3, 5]
    assert window.index == 1
    assert window.cards[0].rating.get() == window.cards[1].rating.get() == 0


def test_partial_writer_failure_keeps_separate_truth_and_position(view, monkeypatch):
    window, controller = view.window, view.controller
    a, b = window.cards
    a.rating.set(3)
    b.rating.set(4)
    writer = controller._learning_record_writer
    original = writer.append_record
    calls = []

    def write(record):
        calls.append(record)
        return original(record) if len(calls) == 1 else False

    monkeypatch.setattr(writer, "append_record", write)
    window._save_next()
    assert controller.is_image_rated(a.sample.image_ref)
    assert not controller.is_image_rated(b.sample.image_ref)
    assert controller.get_review_draft(b.sample.image_ref)["overall_rating"] == 4
    assert "Saved successfully" in a.status.get()
    assert "Not saved" in b.status.get()
    assert window.index == 0


def test_restart_restores_pair_navigation_and_draft_without_new_rating(view):
    window = view.window
    window._move(2)
    window.cards[0].rating.set(2)
    window.cards[0].stage()
    payload = view.state.to_dict()
    selected = window.cards[0].sample.image_ref
    window.destroy()
    restored = LearningState.from_dict(payload)
    view.controller.learning_state = restored
    reopened = QualificationReviewWindow(view.panel)
    assert reopened.index == 2
    assert reopened.cards[0].sample.image_ref == selected
    assert reopened.cards[0].rating.get() == 2
    assert "Unsaved draft" in reopened.cards[0].status.get()
    assert not view.controller.is_image_rated(selected)
    reopened.destroy()


def test_switched_or_destroyed_window_cannot_write_or_present(view):
    window = view.window
    old = copy.deepcopy(view.state.to_dict())
    view.state.current_experiment = copy.deepcopy(view.state.current_experiment)
    window.cards[0].rating.set(5)
    window._save_next()
    assert view.state.review_drafts == old["review_drafts"]
    window.destroy()
    assert window.runner.closed and not window.session.live


def test_small_viewport_remains_scrollable_and_controls_keyboard_reachable(view):
    window = view.window
    window.geometry("600x400")
    view.root.update()
    assert window.scroll.inner.winfo_reqheight() > window.winfo_height()
    assert window.cards[0].media.winfo_exists()
    assert window.cards[1].media.winfo_exists()
    assert str(window.alternatives.cget("state")) == "readonly"


def test_pair_and_individual_view_switches_preserve_their_own_identity(view):
    window = view.window
    window._move(3)
    pair = window.entries[window.index].identity
    window.individual.set(True)
    window._select_entries()
    window._move(5)
    image = window.cards[0].sample.image_ref
    window.individual.set(False)
    window._select_entries()
    assert window.entries[window.index].identity == pair
    window.individual.set(True)
    window._select_entries()
    assert window.cards[0].sample.image_ref == image


def test_sfw_previews_and_prompt_privacy_use_existing_visibility_policy(view):
    window = view.window
    from src.gui.app_state_v2 import AppStateV2

    state = AppStateV2()
    state.content_visibility_mode = "sfw"
    view.state.current_experiment.prompt_text = "explicit nsfw nude"
    # MediaInspector consumes the explicit frozen subject, never a displayed prompt.
    for card in window.cards:
        card.media._app_state = state
        card.media.set_image_reference(
            card.sample.image_ref, subject={"prompt": "explicit nsfw nude"}
        )
        card.media._apply_policy()
        assert not card.media.model.eligible
    assert "explicit nsfw nude" not in window.heading.get()
    assert "explicit nsfw nude" not in window.evidence.get("1.0", "end")


def test_pending_findings_callback_is_discarded_after_destroy(view):
    window = view.window
    pending = []
    window.runner._coordinator._dispatcher = lambda callback: pending.append(callback)
    window.refresh()
    window.destroy()
    for callback in pending:
        callback()
    assert window.runner.closed


def test_saved_details_survive_view_switch_without_duplicate_rating(view):
    window, controller = view.window, view.controller
    ref = window.cards[0].sample.image_ref
    controller.record_rating(
        ref, 3, "saved note", {"subscores": {"legacy_detail": 4}, "context_flags": {}}
    )
    window.refresh()
    card = window.cards[0]
    assert card.subscores["legacy_detail"].get() == 4
    lines = controller._learning_record_writer.records_path.read_text().splitlines()
    window._move(1)
    window._move(-1)
    assert card.subscores["legacy_detail"].get() == 4
    assert controller.get_review_draft(ref) is None
    assert controller._learning_record_writer.records_path.read_text().splitlines() == lines
