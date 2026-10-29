"""AI-LEARN-830 GUI surface: toolkit-neutral view, real Tk dialog and Model Evidence routing (acceptance 12)."""

from __future__ import annotations

import time
from tkinter import ttk
from types import SimpleNamespace

import pytest

from src.gui.views.model_evidence_window import ModelEvidenceWindow
from src.gui.views.next_test_dialog import NextTestDialog
from src.gui_v2.next_test_view import build_view, details_text, route_for
from src.learning.experiment_store import LearningExperimentStore
from src.learning.intelligence_contracts import (
    WORKFLOW_PROPOSED_EXPERIMENTS,
    StaleActionError,
)
from tests.learning_v2.intelligence_fixtures_830 import (
    NOTE,
    make_context,
    rating_rows,
    run,
    save_experiment,
    steps_proposal,
)


def wait_idle(root, window, seconds=3.0):
    deadline = time.monotonic() + seconds
    while window._busy and time.monotonic() < deadline:
        root.update()
        time.sleep(0.01)
    root.update()
    assert not window._busy


@pytest.fixture
def report(tmp_path):
    return run(tmp_path)[0]


def select_first(root, window):
    """Select the checkpoint and let its queued <<TreeviewSelect>> run before any worker starts."""
    window.tree.selection_set(next(iter(window._rows)))
    root.update()


def make_window(tk_root, owner_attrs=None):
    owner = ttk.Frame(tk_root)
    owner._on_open_experiment_library = lambda: owner.calls.append("library")
    owner.calls = []
    for key, value in (owner_attrs or {}).items():
        setattr(owner, key, value)
    window = ModelEvidenceWindow(owner)
    window.census = {
        "assets": [
            {
                "kind": "checkpoint",
                "relative": "models/Stable-diffusion/test.safetensors",
                "identity_status": "pending",
                "family": "unknown",
                "size": 10,
                "header": {},
            }
        ]
    }
    window._render_assets()
    return owner, window


def test_view_model_has_one_primary_few_alternatives_and_explicit_readiness(report):
    view = build_view(report)
    assert view.primary.ready and "Ready" in view.primary.readiness
    assert len(view.alternatives) <= 3
    assert view.primary.button == "Open Proposed Experiments"
    assert "No improvement is promised" not in view.primary.purpose
    assert view.notice == ""
    text = view.details
    assert "REVIEWED RESEARCH CLAIMS" in text and "limitation:" in text and "freshness:" in text
    assert route_for(report.actions.primary).workflow == WORKFLOW_PROPOSED_EXPERIMENTS
    assert details_text(report) == text  # pure and repeatable


def test_view_model_surfaces_degraded_evidence_and_blocked_state(tmp_path):
    degraded, _ = run(tmp_path, log_extra="{broken\n")
    assert "could not be read" in build_view(degraded).notice
    unverified, _ = run(tmp_path, context=make_context(sha=None))
    view = build_view(unverified)
    assert "Needs your step" in view.status and not view.primary.ready
    assert view.primary.button == "Show me the step"


def test_dialog_renders_and_opens_only_the_selected_ready_action(tk_root, report):
    opened, refreshed = [], []
    dialog = NextTestDialog(
        tk_root, build_view(report), on_open=opened.append, on_refresh=lambda: refreshed.append(1)
    )
    tk_root.update()
    assert dialog.choices.selection() == ("0",)
    assert str(dialog.open_button.cget("state")) == "normal"
    assert dialog.open_button.cget("text") == "Open Proposed Experiments"
    shown = dialog.card_text.get("1.0", "end")
    assert "Your next step" in shown and "No improvement is promised" in shown
    dialog._open()
    assert opened == [report.actions.primary.action_id]
    dialog._refresh()
    assert refreshed == [1]
    blocked = next(i for i, c in enumerate(dialog.cards) if not c.ready)
    dialog.choices.selection_set(str(blocked))
    tk_root.update()
    opened.clear()
    if not dialog.cards[blocked].button:
        assert str(dialog.open_button.cget("state")) == "disabled"
        dialog._open()
        assert opened == []
    dialog.close()
    dialog.close()  # idempotent


def test_dialog_details_toggle_stale_state_resize_and_keyboard(tk_root, report):
    opened = []
    dialog = NextTestDialog(
        tk_root, build_view(report), on_open=opened.append, on_refresh=lambda: None
    )
    dialog.toggle_details()
    assert "Reviewed research claims".upper() in dialog.details.get("1.0", "end")
    dialog.toggle_details()
    assert dialog.details_button.cget("text") == "Show evidence details"
    dialog.geometry("460x340")
    tk_root.update()
    narrow = int(dialog._labels[0].cget("wraplength"))
    dialog.geometry("900x500")
    tk_root.update()
    assert int(dialog._labels[0].cget("wraplength")) > narrow
    dialog.choices.focus_force()
    tk_root.update()
    dialog.choices.event_generate("<Return>")
    tk_root.update()
    assert opened == [report.actions.primary.action_id]  # keyboard reachable
    dialog.mark_stale("Evidence changed.")
    assert str(dialog.open_button.cget("state")) == "disabled"
    dialog._open()
    assert len(opened) == 1
    dialog.close()


def test_window_assesses_on_worker_and_delivers_on_the_tk_thread(tk_root, monkeypatch, report):
    import threading

    threads = []
    monkeypatch.setattr(
        "src.gui.views.model_evidence_window.assess_model",
        lambda context, services: threads.append(threading.get_ident()) or report,
    )
    owner, window = make_window(tk_root)
    select_first(tk_root, window)
    window._capture_planning_inputs = lambda: ("inputs",)
    window._context = lambda _inputs: "context"
    window._test_next()
    wait_idle(tk_root, window)
    assert threads and threads[0] != threading.get_ident()
    assert isinstance(window._next_dialog, NextTestDialog) and window._next_report is report
    assert "Nothing was started" in window.status.get()
    window._close()


def test_selecting_another_model_makes_the_open_suggestion_inert(tk_root, monkeypatch, report):
    monkeypatch.setattr("src.gui.views.model_evidence_window.assess_model", lambda c, s: report)
    _, window = make_window(tk_root)
    select_first(tk_root, window)
    window._capture_planning_inputs = lambda: ("inputs",)
    window._context = lambda _inputs: "context"
    window._test_next()
    wait_idle(tk_root, window)
    dialog = window._next_dialog
    window.tree.selection_remove(window.tree.selection())
    window._selected_model_changed()
    assert str(window.next_button.cget("state")) == "disabled" and window._next_report is None
    assert str(dialog.open_button.cget("state")) == "disabled"
    window._close()


def test_closing_the_window_cancels_pending_work_and_destroys_the_dialog(
    tk_root, monkeypatch, report
):
    import threading

    gate = threading.Event()
    monkeypatch.setattr(
        "src.gui.views.model_evidence_window.assess_model", lambda c, s: gate.wait(2) and report
    )
    _, window = make_window(tk_root)
    select_first(tk_root, window)
    window._capture_planning_inputs = lambda: ("inputs",)
    window._context = lambda _inputs: "context"
    window._test_next()
    window.destroy()  # parent teardown path
    gate.set()
    assert window._closed and window._cancel.is_set()
    time.sleep(0.2)
    assert window._next_dialog is None  # a late result is never delivered to a dead window


def route_window(tk_root, monkeypatch, action_result, owner_attrs=None):
    monkeypatch.setattr(
        "src.gui.views.model_evidence_window.revalidate", lambda a, c, s: action_result
    )
    owner, window = make_window(tk_root, owner_attrs)
    select_first(tk_root, window)
    window._capture_planning_inputs = lambda: ("inputs",)
    window._context = lambda _inputs: "context"
    return owner, window


def test_run_action_opens_the_existing_proposed_experiments_flow_only(tk_root, monkeypatch, report):
    owner, window = route_window(tk_root, monkeypatch, (report.actions.primary, report))
    planned = []
    window._plan = lambda **kw: planned.append(kw) or None
    window._open_next_action(report.actions.primary.action_id)
    wait_idle(tk_root, window)
    assert planned == [{}] and owner.calls == []
    window._close()


def test_rating_action_opens_the_saved_experiment_in_learning_review(
    tk_root, monkeypatch, tmp_path
):
    context = make_context()
    store = LearningExperimentStore(tmp_path / "experiments")
    save_experiment(store, "exp-unrated", proposal=steps_proposal(context))
    rated_report, _ = run(tmp_path, context=context)
    action = rated_report.actions.primary
    restored = []
    owner_attrs = {
        "experiment_store": store,
        "_restore_from_store_payload": lambda payload, experiment_id=None: restored.append(
            (payload["current_experiment"]["experiment_id"], experiment_id)
        )
        or True,
    }
    owner, window = route_window(tk_root, monkeypatch, (action, rated_report), owner_attrs)
    window._open_next_action(action.action_id)
    wait_idle(tk_root, window)
    wait_idle(tk_root, window)  # revalidation, then the explicit store read
    assert restored == [("exp-unrated", "exp-unrated")]
    assert "Rate or inspect" in window.status.get()
    window._close()


def test_recommendation_action_shows_existing_recommendations_without_applying(
    tk_root, monkeypatch, tmp_path
):
    from src.learning.intelligence_contracts import ACTION_REVIEW_RECOMMENDATION

    context = make_context()
    save_experiment(
        LearningExperimentStore(tmp_path / "experiments"),
        "exp-pub",
        proposal=steps_proposal(context),
    )
    rec_report, _ = run(tmp_path, context=context, rows=rating_rows("exp-pub"), publication=True)
    action = next(a for a in rec_report.actions.actions if a.kind == ACTION_REVIEW_RECOMMENDATION)
    shown = []
    panel = SimpleNamespace(
        show_recommendations=lambda: shown.append(1), apply=lambda: shown.append("APPLY")
    )
    owner, window = route_window(
        tk_root, monkeypatch, (action, rec_report), {"review_panel": panel}
    )
    window._open_next_action(action.action_id)
    wait_idle(tk_root, window)
    assert shown == [1] and "still asks for your confirmation" in window.status.get()
    window._close()


def test_operator_task_only_explains_the_step(tk_root, monkeypatch, tmp_path):
    unverified, _ = run(tmp_path, context=make_context(sha=None))
    action = unverified.actions.primary
    owner, window = route_window(tk_root, monkeypatch, (action, unverified))
    window._open_next_action(action.action_id)
    wait_idle(tk_root, window)
    assert "Verify identities" in window.status.get() and owner.calls == []
    window._close()


def test_stale_action_is_refused_and_nothing_is_routed(tk_root, monkeypatch, report):
    owner, window = route_window(tk_root, monkeypatch, None)
    window._plan = lambda **kw: pytest.fail("a stale action must not open a workflow")
    window._test_next = lambda: None
    window._next_dialog = NextTestDialog(
        window, build_view(report), on_open=lambda _a: None, on_refresh=lambda: None
    )
    window._open_next_action("act-gone")
    wait_idle(tk_root, window)
    assert "Evidence changed" in window.status.get()
    assert str(window._next_dialog.open_button.cget("state")) == "disabled"
    window._close()


def test_learning_entry_selects_the_experiments_checkpoint_then_opens_the_suggestion(
    tk_root, monkeypatch, report
):
    monkeypatch.setattr("src.gui.views.model_evidence_window.assess_model", lambda c, s: report)
    _, window = make_window(tk_root, {"learning_controller": object()})
    window._capture_planning_inputs = lambda: ("inputs",)
    window._context = (
        lambda _inputs: make_context()
    )  # the real planner runs, then chains into the suggestion
    window.request_next_test("C:/models/Stable-diffusion/Test.safetensors")
    deadline = time.monotonic() + 5
    while window._next_dialog is None and time.monotonic() < deadline:
        tk_root.update()
        time.sleep(0.02)
    wait_idle(tk_root, window)
    assert window._next_dialog is not None and not window._next_when_ready
    assert window.proposal_plan is not None  # planning completed first, in the existing way
    window.request_next_test("unknown.safetensors")
    assert "not in the cached checkpoint list" in window.status.get()
    window._close()


def test_surface_leaks_no_private_rating_text(tk_root, tmp_path):
    context = make_context()
    save_experiment(
        LearningExperimentStore(tmp_path / "experiments"), "exp-p", proposal=steps_proposal(context)
    )
    private, _ = run(tmp_path, context=context, rows=rating_rows("exp-p"))
    view = build_view(private)
    rendered = view.details + "".join(
        c.purpose + " ".join(c.reasons) for c in (view.primary, *view.alternatives)
    )
    assert NOTE not in rendered and "PRIVATE-PROMPT-CANARY" not in rendered
    with pytest.raises(StaleActionError):
        private.actions.revalidate("act-unknown")


def test_learning_header_entry_passes_the_experiments_own_model(monkeypatch):
    from src.gui.views.learning_tab_frame_v2 import LearningTabFrame

    requested = []
    fake_window = SimpleNamespace(request_next_test=requested.append)
    monkeypatch.setattr(
        "src.gui.views.model_evidence_window.open_model_evidence", lambda owner: fake_window
    )
    experiment = SimpleNamespace(
        stage="txt2img", baseline_config={"txt2img": {"model": "from-baseline.safetensors"}}
    )
    controller = SimpleNamespace(
        learning_state=SimpleNamespace(current_experiment=experiment),
        authoring_baseline=lambda: {"txt2img": {"model": "authored.safetensors"}},
    )
    LearningTabFrame._on_test_next(SimpleNamespace(learning_controller=controller))
    assert requested == ["authored.safetensors"]  # the editable Learning baseline names the target
    controller.authoring_baseline = lambda: None
    LearningTabFrame._on_test_next(SimpleNamespace(learning_controller=controller))
    assert requested[-1] == "from-baseline.safetensors"
