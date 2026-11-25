"""AI-230g phrase to slot through the real Prompt tab, Matrix sub-tab and AI Assist window, with a controllable synthetic service.

No model, process, network or display beyond a withdrawn Tk root. Proves that applying a proposal replaces exactly the selected
words with one marker and adds one slot whose first value is the operator's own phrase (all-or-nothing, byte-exact), that Undo
restores the sentence and the matrix, that a stale context or a bad selection refuses, and that nothing derived from the prompt is
logged, saved or queued.
"""

from __future__ import annotations

import copy
import json

import pytest

from src.ai_assist.contracts import (
    SUGGESTION_SCHEMA_ID,
    AssistOutcome,
    OutcomeCode,
    SuggestionKind,
)
from src.ai_assist.validators import validate_output
from src.gui.models.prompt_pack_model import MatrixSlot
from src.gui_v2.ai_slot_phrase import NO_PHRASE_TEXT, PHRASE_NOTICE, PHRASE_REVERT_TEXT, STALE_TEXT
from tests.gui_v2.test_ai_suggestions_112 import journey  # noqa: F401 - shared fixture

pytestmark = pytest.mark.gui

SENTENCE = "a knight in a forest, wearing armor, at dusk"
PHRASE = "at dusk"


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
def phrase(journey):  # noqa: F811 - the imported fixture
    _setup(journey.frame)
    return journey


def _select(j, text=PHRASE, *, nth=0):
    """Select ``text`` in the positive editor the way a drag would, and let Tk deliver the selection event."""

    editor = j.frame.editor
    content = editor.get("1.0", "end-1c")
    start = -1
    for _ in range(nth + 1):
        start = content.index(text, start + 1)
    editor.tag_remove("sel", "1.0", "end")
    editor.tag_add("sel", f"1.0 + {start} chars", f"1.0 + {start + len(text)} chars")
    j.root.update()
    return start


def _select_range(j, start, end):
    editor = j.frame.editor
    editor.tag_remove("sel", "1.0", "end")
    editor.tag_add("sel", f"1.0 + {start} chars", f"1.0 + {end} chars")
    j.root.update()


def _clear_selection(j):
    j.frame.editor.tag_remove("sel", "1.0", "end")
    j.root.update()


def _text(dialog) -> str:
    return dialog.status_var.get() + "\n" + dialog.preview.get("1.0", "end")


def _ask(j, goal=""):
    dialog = j.flow.open()
    assert dialog is not None and dialog.phrase_button is not None
    dialog.phrase_goal_var.set(goal)
    dialog.phrase_button.invoke()
    return dialog


def _outcome(request, entries):
    doc = {
        "schema": SUGGESTION_SCHEMA_ID,
        "status": "ok",
        "kind": "phrase_slot",
        "phrase_slots": entries,
    }
    validated = validate_output(json.dumps(doc), request)
    assert validated.suggestion is not None, validated.reason
    return AssistOutcome(
        OutcomeCode.SUGGESTION, request.request_id, suggestion=validated.suggestion
    )


def _entry(name="time_of_day", values=("at dawn", "at midnight", "at high noon")):
    return {"slot_name": name, "values": list(values), "rationale": "other times of day"}


def _deliver(j, outcome):
    j.service.callbacks[-1](outcome)
    assert j.scheduled, "completion must be queued to the GUI thread"
    j.scheduled.pop(0)()


def _offered(dialog) -> list[str]:
    return [card.title for card in dialog.change_cards.cards if card.offered]


def _apply(dialog, position: int = 0) -> None:
    key = dialog.change_cards.offered_keys()[position]
    dialog.change_cards.apply_buttons[key].invoke()


def _editor(frame) -> str:
    return frame.editor.get("1.0", "end-1c")


def _slots(frame):
    return [(s.name, list(s.values)) for s in frame.workspace_state.get_matrix_config().slots]


def _state(frame):
    ws = frame.workspace_state
    return (
        _slots(frame),
        ws.get_current_slot().text,
        _editor(frame),
        [(w[0].get(), w[1].get()) for w in frame.matrix_tab_panel.slot_widgets],
    )


def _walk(widget):
    for child in widget.winfo_children():
        yield child
        yield from _walk(child)


def _ready(j, goal="", entries=None):
    """Select the phrase, ask, deliver a clean answer; returns ``(dialog, request)``."""

    _select(j)
    dialog = _ask(j, goal)
    request = j.service.requests[-1]
    _deliver(j, _outcome(request, entries or [_entry()]))
    return dialog, request


# -- selection and request -------------------------------------------------------------------------------------------------


def test_the_request_carries_the_sentence_the_phrase_the_slot_names_and_an_optional_goal(phrase):
    j = phrase
    before = copy.deepcopy(j.frame.workspace_state.current_pack)
    _select(j)
    _ask(j)
    request = j.service.requests[-1]
    assert request.kind is SuggestionKind.PHRASE_SLOT
    assert (request.positive_text, request.phrase_text) == (SENTENCE, PHRASE)
    assert request.goal_text == "" and request.existing_slot_names == ("location",)
    assert (request.allowed_targets, request.allowed_workflows, request.matrix_slots) == (
        (),
        (),
        (),
    )
    assert request.insertion_points == () and request.negative_text == ""
    assert j.frame.workspace_state.current_pack == before  # a request changes nothing


def test_a_typed_goal_travels_with_the_request(phrase):
    j = phrase
    _select(j)
    _ask(j, "  different times of day ")
    assert j.service.requests[-1].goal_text == "different times of day"


def test_the_selected_phrase_is_shown_live_in_the_window(phrase):
    j = phrase
    dialog = j.flow.open()
    assert NO_PHRASE_TEXT in dialog.phrase_var.get()
    _select(j)
    assert PHRASE in dialog.phrase_var.get()
    _select(j, "forest")
    assert "forest" in dialog.phrase_var.get() and PHRASE not in dialog.phrase_var.get()


def test_the_window_states_what_may_change_and_how_to_revert(phrase):
    dialog = phrase.flow.open()
    labels = " ".join(
        str(w.cget("text")) for w in _walk(dialog) if w.winfo_class() in {"TLabel", "TLabelframe"}
    )
    assert PHRASE_NOTICE in labels and PHRASE_REVERT_TEXT in labels
    assert dialog.phrase_button.cget("text") == "Suggest slot from phrase"
    assert not phrase.service.requests


def test_no_selection_submits_nothing_and_says_so(phrase):
    j = phrase
    dialog = _ask(j)
    assert not j.service.requests and NO_PHRASE_TEXT in _text(dialog)


@pytest.mark.parametrize(
    ("text", "needle"),
    [("knig", "inside a word"), ("forest, wearing", "comma"), ("armor, at dusk", "comma")],
)
def test_a_selection_that_cannot_be_a_slot_submits_nothing(phrase, text, needle):
    j = phrase
    _select(j, text)
    dialog = _ask(j)
    assert not j.service.requests and needle in _text(dialog)


def test_a_selection_touching_a_protected_token_is_refused(journey):  # noqa: F811
    j = journey
    sentence = "a knight [[hero]] in a forest"
    _setup(j.frame, sentence=sentence, slots=(("hero", ("knight", "ranger")),))
    _select(j, "[[hero]] in")
    dialog = _ask(j)
    assert not j.service.requests and "protected token" in _text(dialog)


def test_whitespace_around_the_selection_is_trimmed_never_widened(phrase):
    j = phrase
    start = SENTENCE.index(PHRASE)
    _select_range(j, start - 1, len(SENTENCE))  # includes the space before "at"
    _ask(j)
    assert j.service.requests[-1].phrase_text == PHRASE


def test_the_last_selection_is_remembered_when_focus_moves_and_clears_it(phrase):
    j = phrase
    dialog = j.flow.open()
    _select(j)
    _clear_selection(j)  # what clicking into the goal box can do to the editor's selection
    assert PHRASE in dialog.phrase_var.get()
    dialog.phrase_button.invoke()
    assert j.service.requests[-1].phrase_text == PHRASE


def test_a_remembered_selection_is_dropped_once_the_text_no_longer_matches(phrase):
    j = phrase
    dialog = j.flow.open()
    _select(j)
    _clear_selection(j)
    j.frame.editor.insert(
        "1.0", "XX "
    )  # shifts every offset; the remembered span now names other characters
    dialog.phrase_button.invoke()
    assert not j.service.requests  # the editor also has a pending change, which blocks first
    assert "pending" in _text(dialog) or NO_PHRASE_TEXT in _text(dialog)


def test_the_second_occurrence_of_a_repeated_phrase_is_the_one_replaced(journey):  # noqa: F811
    j = journey
    sentence = "at dusk a knight, at dusk"
    _setup(j.frame, sentence=sentence)
    _select(j, PHRASE, nth=1)
    _ask(j)
    request = j.service.requests[-1]
    _deliver(j, _outcome(request, [_entry()]))
    _apply(j.flow.dialog)
    assert _editor(j.frame) == "at dusk a knight, [[time_of_day]]"


# -- apply -----------------------------------------------------------------------------------------------------------------


def test_applying_adds_the_slot_with_the_phrase_first_and_replaces_exactly_those_words(phrase):
    j = phrase
    dialog, _request = _ready(j)
    assert _offered(dialog) == ["time_of_day: at dusk, at dawn, at midnight, at high noon"]
    card = dialog.change_cards.cards[0]
    assert PHRASE in card.before and "[[time_of_day]]" in card.after and card.examples
    assert "at dusk" in card.examples[0]  # the first compiled prompt is the original sentence
    _apply(dialog)

    frame = j.frame
    assert _slots(frame) == [
        ("location", ["forest", "harbor"]),
        ("time_of_day", ["at dusk", "at dawn", "at midnight", "at high noon"]),
    ]
    start = SENTENCE.index(PHRASE)
    expected = SENTENCE[:start] + "[[time_of_day]]" + SENTENCE[start + len(PHRASE) :]
    assert _editor(frame) == frame.workspace_state.get_current_slot().text == expected
    # Putting the phrase back where the marker is restores the sentence byte for byte: nothing else was reworded.
    assert expected.replace("[[time_of_day]]", PHRASE, 1) == SENTENCE
    assert [w[0].get() for w in frame.matrix_tab_panel.slot_widgets] == ["location", "time_of_day"]
    assert (
        frame.matrix_tab_panel.slot_widgets[1][1].get()
        == "at dusk,at dawn,at midnight,at high noon"
    )
    assert frame.workspace_state.dirty and "modified" in frame.pack_name_label.cget("text")
    assert "[applied]" in _text(dialog) and _offered(dialog) == []
    assert "modified and unsaved" in dialog.status_var.get()
    assert len(j.service.requests) == 1


def test_only_one_proposal_can_be_applied_for_one_selection(phrase):
    j = phrase
    dialog, _request = _ready(
        j, entries=[_entry("time_of_day"), _entry("mood", ("calm", "tense", "wistful"))]
    )
    assert len(_offered(dialog)) == 2
    _apply(dialog, 0)
    after_first = _state(j.frame)
    cards = {card.key: card for card in dialog.change_cards.cards}
    assert cards["phrase:0"].applied
    assert cards["phrase:1"].rejected and cards["phrase:1"].reason == "phrase_taken"
    assert _offered(dialog) == []
    # pressing Apply all offered now has nothing to do, and the workspace is untouched
    assert j.flow.apply_changes(["phrase:1"]) == 0
    assert _state(j.frame) == after_first


def test_apply_selected_and_apply_all_use_the_same_path(phrase):
    j = phrase
    dialog, _request = _ready(j)
    assert dialog.apply_all_button.instate(["!disabled"])
    dialog.apply_all_button.invoke()
    assert _editor(j.frame).count("[[time_of_day]]") == 1
    assert len(j.flow._journal) == 1


def test_a_proposal_with_a_taken_name_or_a_repeated_phrase_is_shown_rejected_and_never_applied(
    phrase,
):
    j = phrase
    before = _state(j.frame)
    dialog, _request = _ready(
        j,
        entries=[
            _entry("location"),
            _entry("time", ("at dusk", "at dawn", "at noon")),
            _entry("mood", ("calm", "calm", "tense")),
        ],
    )
    assert _offered(dialog) == []
    reasons = [card.reason for card in dialog.change_cards.cards]
    assert reasons == ["slot_name_exists", "value_repeats_phrase", "values_invalid"]
    assert "[rejected]" in _text(dialog)
    assert _state(j.frame) == before


# -- undo ------------------------------------------------------------------------------------------------------------------


def test_apply_then_undo_restores_the_sentence_and_the_matrix_exactly(phrase):
    j = phrase
    before = _state(j.frame)
    dialog, _request = _ready(j)
    _apply(dialog)
    assert _state(j.frame) != before and dialog.undo_button.instate(["!disabled"])
    assert j.flow.undo_last() is True
    assert _state(j.frame) == before
    assert dialog.undo_button.instate(["disabled"])
    # the same card can be applied again after the undo
    assert len(_offered(dialog)) == 1
    _apply(dialog)
    assert _editor(j.frame).count("[[time_of_day]]") == 1


def test_undo_refuses_when_the_sentence_changed_after_the_apply(phrase):
    j = phrase
    dialog, _request = _ready(j)
    _apply(dialog)
    j.frame.editor.insert("end-1c", " extra")
    j.frame._on_editor_modified(None)
    changed = _state(j.frame)
    assert j.flow.undo_last() is False
    assert _state(j.frame) == changed
    assert "cannot be undone automatically" in dialog.status_var.get()


def test_undo_refuses_when_the_matrix_changed_after_the_apply(phrase):
    j = phrase
    dialog, _request = _ready(j)
    _apply(dialog)
    j.frame.workspace_state.get_matrix_config().slots[0].values.append("castle")
    changed = _slots(j.frame)
    assert j.flow.undo_last() is False
    assert _slots(j.frame) == changed and "[[time_of_day]]" in _editor(j.frame)


# -- stale and all-or-nothing ----------------------------------------------------------------------------------------------


def test_a_sentence_edit_after_the_request_refuses_every_proposal(phrase):
    j = phrase
    _select(j)
    dialog = _ask(j)
    request = j.service.requests[-1]
    j.frame.editor.insert("1.0", "photo of ")
    j.frame._on_editor_modified(None)
    changed = _state(j.frame)
    _deliver(j, _outcome(request, [_entry()]))
    assert _offered(dialog) == []  # nothing is offered against another state
    assert _state(j.frame) == changed


def test_a_matrix_edit_between_review_and_apply_refuses_the_apply(phrase):
    j = phrase
    dialog, _request = _ready(j)
    j.frame.workspace_state.get_matrix_config().slots[0].values.append("castle")
    changed = _state(j.frame)
    key = (
        dialog.change_cards.offered_keys()[0] if dialog.change_cards.offered_keys() else "phrase:0"
    )
    assert j.flow.apply_changes([key]) == 0
    assert _state(j.frame) == changed and STALE_TEXT in dialog.status_var.get()


def test_a_failed_marker_replacement_leaves_the_pack_as_it_was(phrase, monkeypatch):
    j = phrase
    before = _state(j.frame)
    dialog, _request = _ready(j)
    monkeypatch.setattr(j.frame, "replace_text_span", lambda *a, **k: False)
    _apply(dialog)
    assert _state(j.frame) == before and j.flow._journal.last is None
    assert "taken back" in dialog.status_var.get() or "did not change" in dialog.status_var.get()


def test_a_replacement_that_did_not_produce_the_expected_text_is_taken_back(phrase, monkeypatch):
    j = phrase
    frame = j.frame
    before = _state(frame)
    dialog, _request = _ready(j)
    real = frame.replace_text_span
    calls = []

    def sabotaged(start, end, expected, new):
        done = real(start, end, expected, new)
        if not calls:  # only the apply misbehaves; the rollback that follows is the real edit path
            frame.editor.insert("end-1c", "!")  # something else changes the sentence as well
            frame._on_editor_modified(None)
        calls.append((start, end, expected, new))
        return done

    monkeypatch.setattr(frame, "replace_text_span", sabotaged)
    _apply(dialog)
    # the slot and the marker are both gone; only the foreign edit made by the sabotage remains
    assert _slots(frame) == before[0] and _editor(frame) == SENTENCE + "!"
    assert j.flow._journal.last is None
    assert "did not change as expected" in dialog.status_var.get()


def test_replace_text_span_refuses_unless_the_span_holds_the_expected_text(phrase):
    frame = phrase.frame
    before = _editor(frame)
    assert frame.replace_text_span(0, 3, "XYZ", "q") is False  # wrong expected text
    assert frame.replace_text_span(5, 99, "x", "q") is False  # past the end
    assert frame.replace_text_span(10, 5, "x", "q") is False  # reversed
    assert _editor(frame) == before
    assert frame.replace_text_span(0, 1, "a", "the") is True
    assert _editor(frame) == "the" + before[1:]
    assert frame.workspace_state.get_current_slot().text == _editor(frame)


# -- lifetime and logging --------------------------------------------------------------------------------------------------


def test_closing_the_window_forgets_the_review_the_selection_and_the_journal(phrase):
    j = phrase
    dialog, _request = _ready(j)
    _apply(dialog)
    dialog.close()
    assert j.flow.dialog is None and len(j.flow._journal) == 0
    assert j.flow._phrase is None and j.flow._phrase_suggestion is None
    assert j.flow._phrase_added == set() and j.flow._selection is None


def test_goal_sentence_phrase_and_proposals_stay_out_of_logs_and_status(phrase, caplog):
    j = phrase
    caplog.set_level("DEBUG")
    canary = "zanzibarcanary"
    _setup(j.frame, sentence=f"a {canary} harbor, at dusk")
    _select(j, f"{canary} harbor")
    dialog = _ask(j, f"{canary} goal")
    request = j.service.requests[-1]
    _deliver(j, _outcome(request, [_entry(f"{canary}slot", (f"{canary} one", f"{canary} two"))]))
    _apply(dialog)
    assert canary not in caplog.text
    assert j.flow.snapshot is None
