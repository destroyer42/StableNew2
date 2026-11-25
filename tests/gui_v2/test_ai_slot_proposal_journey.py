"""AI-213 new-slot proposals through the real Prompt tab, Matrix sub-tab and AI dialog, with a controllable synthetic service.

No model, process, network or display beyond a withdrawn Tk root. Proves that accepting a proposal adds exactly one slot and one
marker (all-or-nothing), that a stale context refuses, that protected tokens are never split, that nothing is saved or queued,
and that the goal, sentence and proposals stay out of logs.
"""

from __future__ import annotations

import ast
import copy
import inspect
import json
import re
import textwrap

import pytest

from src.ai_assist.contracts import (
    SUGGESTION_SCHEMA_ID,
    AssistOutcome,
    OutcomeCode,
    RuntimeDetail,
    SuggestionKind,
)
from src.ai_assist.preview import PREVIEW_LABEL
from src.ai_assist.validators import protected_tokens, validate_output
from src.gui.models.prompt_pack_model import MatrixSlot
from src.gui.prompt_ai_suggestions import PromptAiSuggestions
from src.gui_v2.ai_slot_proposal import (
    PROPOSAL_NOTICE,
    PROPOSAL_REVERT_TEXT,
    STALE_TEXT,
    marker_insertion,
)
from src.gui_v2.ai_suggestion_view import OUTCOME_TEXT
from tests.gui_v2.test_ai_suggestions_112 import journey  # noqa: F401 - shared fixture

pytestmark = pytest.mark.gui

SENTENCE = "a knight in a forest, wearing armor, at dusk"


def _setup(frame, sentence=SENTENCE, slots=None, limit=8):
    config = frame.workspace_state.get_matrix_config()
    config.limit = limit
    config.slots = [
        MatrixSlot(name=name, values=list(values))
        for name, values in (slots or (("location", ("forest", "harbor")),))
    ]
    frame.workspace_state.set_slot_text(0, sentence)
    frame._refresh_editor()
    frame.matrix_tab_panel.refresh()
    frame.workspace_state.dirty = False


@pytest.fixture
def proposals(journey):  # noqa: F811 - the imported fixture
    _setup(journey.frame)
    return journey


def _text(dialog) -> str:
    return dialog.status_var.get() + "\n" + dialog.preview.get("1.0", "end")


def _ask(j, goal="better lighting for hyperrealism"):
    dialog = j.flow.open()
    assert dialog is not None and dialog.proposal_button is not None
    dialog.proposal_goal_var.set(goal)
    dialog.proposal_button.invoke()
    return dialog, j.service.requests[-1]


def _outcome(request, proposals, **kwargs):
    doc = {
        "schema": SUGGESTION_SCHEMA_ID,
        "status": "ok",
        "kind": "slot_proposal",
        "proposals": proposals,
    }
    validated = validate_output(json.dumps(doc), request)
    assert validated.suggestion is not None, validated.reason
    return AssistOutcome(
        OutcomeCode.SUGGESTION, request.request_id, suggestion=validated.suggestion, **kwargs
    )


def _entry(name="lighting", point=0, values=("golden hour", "neon glow", "soft window light")):
    return {
        "slot_name": name,
        "values": list(values),
        "insertion_point": point,
        "rationale": "light sets the mood",
    }


def _deliver(j, outcome):
    j.service.callbacks[-1](outcome)
    assert j.scheduled, "completion must be queued to the GUI thread"
    j.scheduled.pop(0)()


def _offered(dialog) -> list[str]:
    return list(dialog.proposal_list.get(0, "end"))


def _add(dialog, position: int = 0) -> None:
    dialog.proposal_list.selection_clear(0, "end")
    dialog.proposal_list.selection_set(position)
    dialog.add_proposal_button.invoke()


def _editor(frame) -> str:
    return frame.editor.get("1.0", "end-1c")


def _state(frame):
    ws = frame.workspace_state
    return (
        [(s.name, list(s.values)) for s in ws.get_matrix_config().slots],
        ws.get_current_slot().text,
        _editor(frame),
        [(w[0].get(), w[1].get()) for w in frame.matrix_tab_panel.slot_widgets],
    )


# -- request ---------------------------------------------------------------------------------------------------------------


def test_the_request_carries_goal_sentence_names_and_closed_points_only(proposals):
    j = proposals
    before = copy.deepcopy(j.frame.workspace_state.current_pack)
    _dialog, request = _ask(j)
    assert request.kind is SuggestionKind.SLOT_PROPOSAL
    assert request.goal_text == "better lighting for hyperrealism"
    assert request.positive_text == SENTENCE and request.negative_text == ""
    assert request.existing_slot_names == ("location",)
    assert len(request.insertion_points) == 3 and "|HERE|" in request.insertion_points[0]
    assert (request.allowed_targets, request.allowed_workflows, request.matrix_slots) == (
        (),
        (),
        (),
    )
    assert j.frame.workspace_state.current_pack == before  # a request changes nothing


def test_the_variety_button_and_contract_are_separate_from_the_new_slot_button(proposals):
    j = proposals
    dialog = j.flow.open()
    assert dialog.variety_button is not dialog.proposal_button
    assert dialog.proposal_button.cget("text") == "Suggest new slot"
    assert dialog.add_proposal_button.cget("text") == "Add slot and place marker"
    assert not j.service.requests


def test_the_dialog_states_what_may_change_and_how_to_revert(proposals):
    dialog = proposals.flow.open()
    labels = " ".join(
        str(w.cget("text")) for w in _walk(dialog) if w.winfo_class() in {"TLabel", "TLabelframe"}
    )
    assert PROPOSAL_NOTICE in labels and PROPOSAL_REVERT_TEXT in labels


def _walk(widget):
    for child in widget.winfo_children():
        yield child
        yield from _walk(child)


def test_a_blank_goal_submits_nothing(proposals):
    j = proposals
    dialog = j.flow.open()
    dialog.proposal_goal_var.set("   ")
    dialog.proposal_button.invoke()
    assert not j.service.requests and "goal" in dialog.status_var.get().lower()


def test_an_empty_prompt_blocks_the_button_with_its_reason(journey):  # noqa: F811
    _setup(journey.frame, sentence="   ")
    dialog = journey.flow.open()
    assert dialog is None or dialog.proposal_button.instate(["disabled"])


def test_a_pending_editor_edit_blocks_the_request(proposals):
    j = proposals
    dialog = j.flow.open()
    j.frame.editor.insert("end", " pending")
    dialog.proposal_goal_var.set("goal")
    dialog.proposal_button.invoke()
    assert not j.service.requests and "pending" in _text(dialog)


# -- accept ----------------------------------------------------------------------------------------------------------------


def test_accepting_adds_one_slot_and_exactly_one_marker(proposals):
    j = proposals
    dialog, request = _ask(j)
    _deliver(j, _outcome(request, [_entry(point=1)]))
    assert _offered(dialog) == ["lighting: golden hour, neon glow, soft window light"]
    assert "go from 2 to 6; compiled per prompt row: 6 (limit 8)" in _text(dialog)
    _add(dialog)

    frame = j.frame
    slots = frame.workspace_state.get_matrix_config().slots
    assert [(s.name, s.values) for s in slots] == [
        ("location", ["forest", "harbor"]),
        ("lighting", ["golden hour", "neon glow", "soft window light"]),
    ]
    offset = SENTENCE.rindex(",")
    inserted = marker_insertion(SENTENCE, offset, "lighting")
    expected = SENTENCE[:offset] + inserted + SENTENCE[offset:]
    assert expected.count("[[lighting]]") == 1
    assert _editor(frame) == frame.workspace_state.get_current_slot().text == expected
    # Removing the one marker restores the sentence exactly: nothing else was reworded.
    assert expected.replace(inserted, "", 1) == SENTENCE
    # The Matrix tab shows the new row, with the same text a person would see after typing it.
    assert [w[0].get() for w in frame.matrix_tab_panel.slot_widgets] == ["location", "lighting"]
    assert (
        frame.matrix_tab_panel.slot_widgets[1][1].get() == "golden hour,neon glow,soft window light"
    )
    assert frame.workspace_state.dirty and "modified" in frame.pack_name_label.cget("text")
    assert "[added]" in _text(dialog) and _offered(dialog) == []
    assert "modified and unsaved" in dialog.status_var.get()
    assert len(j.service.requests) == 1


def test_the_new_slot_matches_what_the_starter_dimension_path_stores(proposals):
    j = proposals
    dialog, request = _ask(j)
    _deliver(j, _outcome(request, [_entry()]))
    _add(dialog)
    new = j.frame.workspace_state.get_matrix_config().slots[-1]
    assert new.preserved == {} and new.extra == {}
    assert j.frame.matrix_tab_panel.last_view is not None


def test_two_proposals_are_added_one_press_each_and_markers_stay_correct(proposals):
    j = proposals
    j.frame.workspace_state.get_matrix_config().limit = 50
    dialog, request = _ask(j)
    _deliver(
        j, _outcome(request, [_entry("lighting", 0), _entry("weather", 2, ("fog", "rain", "snow"))])
    )
    assert len(_offered(dialog)) == 2
    _add(dialog, 0)
    _add(dialog, 0)  # the remaining offered proposal
    text = _editor(j.frame)
    assert text.count("[[lighting]]") == 1 and text.count("[[weather]]") == 1
    assert text.index("[[lighting]]") < text.index("[[weather]]")
    stripped = text.replace(" [[lighting]]", "").replace(" [[weather]]", "")
    assert stripped == SENTENCE
    assert [s.name for s in j.frame.workspace_state.get_matrix_config().slots] == [
        "location",
        "lighting",
        "weather",
    ]


def test_two_proposals_for_the_same_point_only_the_first_lands(proposals):
    j = proposals
    dialog, request = _ask(j)
    _deliver(
        j, _outcome(request, [_entry("lighting", 0), _entry("weather", 0, ("fog", "rain", "snow"))])
    )
    _add(dialog, 0)
    assert _offered(dialog) == []
    assert "same position" in _text(dialog) or "already received a marker" in _text(dialog)
    assert _editor(j.frame).count("[[") == 1


def test_a_proposal_is_never_added_twice(proposals):
    j = proposals
    dialog, request = _ask(j)
    _deliver(j, _outcome(request, [_entry()]))
    _add(dialog)
    once = _state(j.frame)
    j.flow.add_slot_proposal(0)
    assert _state(j.frame) == once


def test_a_failed_marker_insert_takes_the_slot_back(proposals, monkeypatch):
    j = proposals
    dialog, request = _ask(j)
    _deliver(j, _outcome(request, [_entry()]))
    before = _state(j.frame)
    monkeypatch.setattr(j.frame, "insert_slot_marker", lambda *a, **k: False)
    _add(dialog)
    assert _state(j.frame) == before
    assert "taken back" in dialog.status_var.get()
    assert _offered(dialog) == []


def test_an_exception_while_placing_the_marker_takes_the_slot_back(proposals, monkeypatch):
    j = proposals
    dialog, request = _ask(j)
    _deliver(j, _outcome(request, [_entry()]))
    before = _state(j.frame)

    def boom(*_a, **_k):
        raise RuntimeError("editor gone")

    monkeypatch.setattr(j.frame, "insert_slot_marker", boom)
    _add(dialog)
    assert _state(j.frame) == before


def test_an_unexpected_result_after_the_marker_takes_both_edits_back(proposals, monkeypatch):
    j = proposals
    dialog, request = _ask(j)
    _deliver(j, _outcome(request, [_entry()]))
    before = _state(j.frame)
    real = j.frame.insert_slot_marker

    def wrong(offset, text):
        return real(offset, text + "!")  # the editor ends up with extra text

    monkeypatch.setattr(j.frame, "insert_slot_marker", wrong)
    _add(dialog)
    assert _state(j.frame) == before
    assert "taken back" in dialog.status_var.get()


def test_a_pending_matrix_row_edit_refuses_without_change(proposals):
    j = proposals
    dialog, request = _ask(j)
    _deliver(j, _outcome(request, [_entry()]))
    _name, values_entry, _delete = j.frame.matrix_tab_panel.slot_widgets[0]
    values_entry.insert("end", ",typed-but-not-applied")
    before = _state(j.frame)
    _add(dialog)
    assert _state(j.frame) == before
    assert "unfinished edit" in dialog.status_var.get()


# -- stale and pending refusals -------------------------------------------------------------------------------------------------


@pytest.mark.parametrize("what", ["sentence", "matrix", "pack"])
def test_a_change_after_the_review_refuses_acceptance(proposals, what):
    j = proposals
    dialog, request = _ask(j)
    _deliver(j, _outcome(request, [_entry()]))
    ws = j.frame.workspace_state
    if what == "sentence":
        ws.set_slot_text(0, SENTENCE + " extra")
        j.frame._refresh_editor()
    elif what == "matrix":
        ws.get_matrix_config().slots[0].values.append("cave")
        j.frame.matrix_tab_panel.refresh()
    else:
        ws.current_pack = copy.deepcopy(ws.current_pack)
    before = _state(j.frame)
    _add(dialog)
    assert _state(j.frame) == before
    assert _offered(dialog) == [] and dialog.status_var.get() == STALE_TEXT
    assert j.flow._proposal is None


@pytest.mark.parametrize("what", ["sentence", "matrix"])
def test_a_change_while_the_model_runs_offers_nothing(proposals, what):
    j = proposals
    dialog, request = _ask(j)
    ws = j.frame.workspace_state
    if what == "sentence":
        ws.set_slot_text(0, "something else entirely")
        j.frame._refresh_editor()
    else:
        ws.get_matrix_config().slots.append(MatrixSlot(name="extra", values=["a"]))
    _deliver(j, _outcome(request, [_entry()]))
    assert _offered(dialog) == [] and j.flow._proposal is None
    assert "lighting" not in _text(dialog)


def test_a_late_answer_after_close_changes_nothing(proposals):
    j = proposals
    dialog, request = _ask(j, goal="private goal words")
    dialog.close()
    assert dialog.proposal_goal_var.get() == ""
    before = _state(j.frame)
    _deliver(j, _outcome(request, [_entry()]))
    assert j.flow.dialog is None and j.flow._proposal is None and _state(j.frame) == before


def test_cancel_while_running_offers_nothing(proposals):
    j = proposals
    dialog, request = _ask(j)
    j.flow.cancel()
    _deliver(j, _outcome(request, [_entry()]))
    assert _offered(dialog) == [] and "cancelled" in dialog.status_var.get().lower()


# -- protected tokens -----------------------------------------------------------------------------------------------------------


def test_no_point_is_inside_a_protected_token_and_accepting_never_splits_one(journey):  # noqa: F811
    j = journey
    sentence = (
        "a knight <lora:style,v2:0.8>, in [[location]], under __light,set__, <embedding:bad,hand>"
    )
    _setup(j.frame, sentence=sentence)
    dialog, request = _ask(j)
    spans = [
        m.span() for m in re.finditer(r"<[^<>\n]*>|\[\[[^\[\]\n]*\]\]|__[^_\s][^\n]*?__", sentence)
    ]
    assert request.insertion_points
    entries = [
        _entry(f"slot{i}", i, (f"a{i}", f"b{i}", f"c{i}"))
        for i in range(len(request.insertion_points))
    ]
    _deliver(j, _outcome(request, entries[:3]))
    original = protected_tokens(sentence)
    for _ in range(3):
        if not _offered(dialog):
            break
        _add(dialog)
    after = _editor(j.frame)
    assert protected_tokens(after) - protected_tokens(sentence) == protected_tokens(
        "".join(f"[[slot{i}]]" for i in range(after.count("[[slot")))
    )
    for token in original:
        assert token in after
    # Every original span is still contiguous in the result, i.e. no marker landed inside one.
    for start, end in spans:
        assert sentence[start:end] in after


# -- visibility ------------------------------------------------------------------------------------------------------------------


def test_a_visibility_switch_scrubs_the_dialog_and_the_review(proposals):
    j = proposals
    dialog, request = _ask(j, goal="private goal words")
    _deliver(j, _outcome(request, [_entry()]))
    assert _offered(dialog)
    j.state.set_content_visibility_mode("sfw")
    assert j.flow.dialog is None and j.flow._proposal is None
    assert not dialog.winfo_exists()
    j.flow.add_slot_proposal(0)
    assert [s.name for s in j.frame.workspace_state.get_matrix_config().slots] == ["location"]


def test_hidden_authored_content_is_never_submitted(proposals):
    j = proposals
    j.frame.workspace_state.set_slot_text(0, "a nude PRIVATE_CANARY knight, in armor")
    j.state.set_content_visibility_mode("sfw")
    j.frame._refresh_editor()
    j.flow.refresh()
    assert j.flow.open() is None and not j.service.requests


# -- matrix growth and the limit ------------------------------------------------------------------------------------------------


def test_a_proposal_past_the_matrix_limit_is_offered_and_can_be_added(journey):  # noqa: F811
    j = journey
    _setup(j.frame, limit=4)
    dialog, request = _ask(j)
    _deliver(j, _outcome(request, [_entry()]))
    assert len(_offered(dialog)) == 1
    text = _text(dialog)
    assert "go from 2 to 6; compiled per prompt row: 4 (limit 4)" in text
    _add(dialog)
    assert [s.name for s in j.frame.workspace_state.get_matrix_config().slots] == [
        "location",
        "lighting",
    ]
    assert "[[lighting]]" in _editor(j.frame)


# -- failures, labels, scrubbing ---------------------------------------------------------------------------------------------------


def test_a_failure_shows_fixed_copy_and_offers_nothing(proposals):
    j = proposals
    dialog, request = _ask(j, goal="private goal words")
    _deliver(
        j,
        AssistOutcome(
            OutcomeCode.MALFORMED,
            request.request_id,
            reason="insertion_point_not_in_closed_list",
            runtime_detail=RuntimeDetail(stdout_head="RAW-MODEL-TEXT"),
        ),
    )
    assert OUTCOME_TEXT[OutcomeCode.MALFORMED] in dialog.status_var.get()
    assert "private" not in _text(dialog) and _offered(dialog) == []
    assert "RAW-MODEL-TEXT" not in _text(dialog)
    assert dialog.detail_button.instate(["!disabled"])


def test_every_proposal_surface_carries_the_preview_label(proposals):
    j = proposals
    dialog, request = _ask(j)
    _deliver(j, _outcome(request, [_entry()], details={"trust_tier": "preview"}))
    assert PREVIEW_LABEL in dialog.trust_var.get()
    assert PREVIEW_LABEL in dialog.status_var.get() and PREVIEW_LABEL in dialog.preview.get(
        "1.0", "end"
    )
    _add(dialog)
    assert PREVIEW_LABEL in dialog.status_var.get() and PREVIEW_LABEL in dialog.preview.get(
        "1.0", "end"
    )


def test_goal_sentence_and_proposals_never_reach_the_log(proposals, caplog):
    j = proposals
    caplog.set_level("DEBUG")
    _setup(j.frame, sentence="CANARY-SENTENCE-77 knight, wearing armor")
    dialog, request = _ask(j, goal="CANARY-GOAL-77")
    _deliver(
        j,
        _outcome(
            request,
            [_entry("CANARYSLOT77", 0, ("CANARY-A-77", "CANARY-B-77", "CANARY-C-77"))],
        ),
    )
    _add(dialog)
    assert "CANARY" not in caplog.text


def test_nothing_is_saved_queued_or_previewed(proposals, tmp_path, monkeypatch):
    j = proposals
    saves, invalidations = [], []
    monkeypatch.setattr(
        j.frame.workspace_state, "save_current_pack", lambda *a, **k: saves.append(1), raising=False
    )
    monkeypatch.setattr(j.state, "invalidate_preview", lambda *a, **k: invalidations.append(1))
    dialog, request = _ask(j)
    _deliver(j, _outcome(request, [_entry()]))
    _add(dialog)
    assert saves == [] and invalidations == []
    packs = tmp_path / "packs"
    assert not packs.exists() or not any(packs.rglob("*"))
    assert j.frame.workspace_state.dirty


def test_the_variety_request_path_is_unchanged_by_the_new_kind(proposals):
    j = proposals
    dialog = j.flow.open()
    dialog.variety_goal_var.set("more variety in locations")
    dialog.variety_slot_vars["location"].set(True)
    dialog.variety_button.invoke()
    request = j.service.requests[-1]
    assert request.kind is SuggestionKind.SLOT_VARIETY
    assert request.matrix_slots == (("location", ("forest", "harbor")),)
    assert request.existing_slot_names == () and request.insertion_points == ()


# -- no path from this kind to Intent, the compiler or the queue ---------------------------------------------------------------

_FORBIDDEN = re.compile(r"njr|queue|compile|intent|job|save|preview_jobs|run_now|pipeline", re.I)


@pytest.mark.parametrize(
    "method",
    [
        "suggest_slot",
        "_proposal_completed",
        "add_slot_proposal",
        "_proposal_review",
        "_capture_proposal",
        "_current_proposal",
        "_roll_back_proposal",
    ],
)
def test_the_proposal_path_names_nothing_that_could_save_compile_or_queue(method):
    tree = ast.parse(textwrap.dedent(inspect.getsource(getattr(PromptAiSuggestions, method))))
    names = {n.attr for n in ast.walk(tree) if isinstance(n, ast.Attribute)} | {
        n.id for n in ast.walk(tree) if isinstance(n, ast.Name)
    }
    assert not [n for n in names if _FORBIDDEN.search(n)], (method, sorted(names))
    calls = {
        n.func.attr
        for n in ast.walk(tree)
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
    }
    assert not calls & {
        "set_matrix_config",
        "set_slot_text",
        "set_slot_negative",
        "mark_dirty",
        "append",
    }


def test_the_only_mutations_are_the_matrix_and_editor_edit_paths():
    source = inspect.getsource(PromptAiSuggestions.add_slot_proposal)
    assert "matrix_tab_panel.append_slot(" in source and "insert_slot_marker(" in source
    for name in ("workspace_state", ".slots", ".values", ".text"):
        assert name not in source.replace("context.", "").replace("row.", "")
