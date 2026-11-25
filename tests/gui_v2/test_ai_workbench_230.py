"""AI-230 workbench: tabs, change cards, one Apply flow and Undo, through the real Prompt tab and a synthetic service.

No model, process or network beyond a withdrawn Tk root. Proves that every apply path is journaled and undoable only while the
workspace still equals what the apply produced, that Apply selected / Apply all work card by card, that a refused variety
request offers the new-slot bridge, and that the window carries no persisted or logged content.
"""

from __future__ import annotations

import pytest

from src.ai_assist.contracts import AssistOutcome, OutcomeCode, SuggestionKind
from src.gui_v2.ai_changes import ApplyJournal, ApplyRecord
from tests.gui_v2.test_ai_slot_proposal_journey import (
    SENTENCE as PROPOSAL_SENTENCE,
)
from tests.gui_v2.test_ai_slot_proposal_journey import (
    _ask as ask_proposal,
)
from tests.gui_v2.test_ai_slot_proposal_journey import (
    _deliver as deliver_proposal,
)
from tests.gui_v2.test_ai_slot_proposal_journey import (
    _entry,
)
from tests.gui_v2.test_ai_slot_proposal_journey import (
    _outcome as proposal_outcome,
)
from tests.gui_v2.test_ai_slot_proposal_journey import (
    _setup as setup_proposals,
)
from tests.gui_v2.test_ai_slot_proposal_journey import (
    _state as proposal_state,
)
from tests.gui_v2.test_ai_slot_variety_journey import (
    ANSWER,
    _matrix,
)
from tests.gui_v2.test_ai_slot_variety_journey import (
    _ask as ask_variety,
)
from tests.gui_v2.test_ai_slot_variety_journey import (
    _deliver as deliver_variety,
)
from tests.gui_v2.test_ai_slot_variety_journey import (
    _offered as offered_values,
)
from tests.gui_v2.test_ai_slot_variety_journey import (
    _outcome as variety_outcome,
)
from tests.gui_v2.test_ai_suggestions_112 import finish, journey, start, successful  # noqa: F401

pytestmark = pytest.mark.gui


def _slots(frame):
    return [(s.name, list(s.values)) for s in frame.workspace_state.get_matrix_config().slots]


def _entries(frame):
    return [(w[0].get(), w[1].get()) for w in frame.matrix_tab_panel.slot_widgets]


def _press(dialog, key):
    dialog.change_cards.apply_buttons[key].invoke()


# -- the window ---------------------------------------------------------------------------------------------------------------


def test_the_window_has_one_tab_per_function_and_a_header(journey):  # noqa: F811
    dialog = journey.flow.open()
    labels = [dialog.notebook.tab(t, "text") for t in dialog.notebook.tabs()]
    assert labels == ["Prompt", "Matrix slots", "Plan", "Check", "Details"]
    assert "Slot 1" in dialog.context_var.get()
    assert dialog.undo_button.instate(["disabled"])


def test_offered_cards_start_checked_and_apply_selected_is_live(journey):  # noqa: F811
    _matrix(journey.frame)
    dialog, request = ask_variety(journey)
    deliver_variety(journey, variety_outcome(request, ANSWER))
    assert dialog.notebook.select() == str(dialog.tabs["slots"])
    assert len(dialog.change_cards.selected_keys()) == 2
    assert dialog.apply_selected_button.cget("text") == "Apply selected (2)"
    assert dialog.apply_selected_button.instate(["!disabled"])
    assert dialog.apply_all_button.instate(["!disabled"])


# -- apply and undo: variety ----------------------------------------------------------------------------------------------------


def test_apply_then_undo_restores_the_matrix_exactly(journey):  # noqa: F811
    j = journey
    _matrix(j.frame)
    before = (_slots(j.frame), _entries(j.frame), j.frame.workspace_state.get_current_slot().text)
    dialog, request = ask_variety(j)
    deliver_variety(j, variety_outcome(request, ANSWER))
    _press(dialog, dialog.change_cards.offered_keys()[0])
    assert offered_values(dialog) == ["location: harbor"]
    assert _slots(j.frame)[2][1] == ["soft light", "golden hour"]
    assert (
        dialog.undo_button.instate(["!disabled"])
        and "Applied this session: 1" in dialog.applied_var.get()
    )
    assert j.flow.undo_last() is True
    assert (
        _slots(j.frame),
        _entries(j.frame),
        j.frame.workspace_state.get_current_slot().text,
    ) == before
    assert offered_values(dialog) == ["lighting: golden hour", "location: harbor"]
    assert dialog.undo_button.instate(["disabled"])
    assert j.frame.workspace_state.dirty


def test_undo_refuses_when_the_matrix_changed_after_the_apply(journey):  # noqa: F811
    j = journey
    _matrix(j.frame)
    dialog, request = ask_variety(j)
    deliver_variety(j, variety_outcome(request, ANSWER))
    _press(dialog, dialog.change_cards.offered_keys()[0])
    _name, values_entry, _delete = j.frame.matrix_tab_panel.slot_widgets[2]
    values_entry.delete(0, "end")
    values_entry.insert(0, "soft light,golden hour,dusk")
    j.frame.matrix_tab_panel._on_slot_changed(2)
    stored = _slots(j.frame)
    assert j.flow.undo_last() is False
    assert _slots(j.frame) == stored
    assert "cannot be undone automatically" in dialog.status_var.get()
    assert dialog.undo_button.instate(["disabled"])


def test_undo_unwinds_several_applies_in_reverse_order(journey):  # noqa: F811
    j = journey
    _matrix(j.frame)
    dialog, request = ask_variety(j)
    deliver_variety(j, variety_outcome(request, ANSWER))
    initial = _slots(j.frame)
    j.flow.apply_changes(dialog.change_cards.offered_keys())
    assert _slots(j.frame)[2][1] == ["soft light", "golden hour"]
    assert _slots(j.frame)[1][1] == ["forest", "harbor"]
    assert "Applied this session: 2" in dialog.applied_var.get()
    assert j.flow.undo_last() and _slots(j.frame)[1][1] == ["forest"]
    assert j.flow.undo_last() and _slots(j.frame) == initial
    assert j.flow.undo_last() is False
    assert dialog.status_var.get().endswith("Nothing to undo.")


def test_apply_selected_applies_only_the_checked_cards(journey):  # noqa: F811
    j = journey
    _matrix(j.frame)
    dialog, request = ask_variety(j)
    deliver_variety(j, variety_outcome(request, ANSWER))
    first, second = dialog.change_cards.offered_keys()
    dialog.change_cards.check_vars[first].set(False)
    assert dialog.apply_selected_button.cget("text") == "Apply selected (1)"
    dialog.apply_selected_button.invoke()
    assert _slots(j.frame)[1][1] == ["forest", "harbor"]
    assert _slots(j.frame)[2][1] == ["soft light"]
    assert second not in dialog.change_cards.offered_keys()


def test_apply_all_applies_every_offered_card_once(journey):  # noqa: F811
    j = journey
    _matrix(j.frame)
    dialog, request = ask_variety(j)
    deliver_variety(j, variety_outcome(request, ANSWER))
    dialog.apply_all_button.invoke()
    assert _slots(j.frame)[1][1] == ["forest", "harbor"]
    assert _slots(j.frame)[2][1] == ["soft light", "golden hour"]
    assert "Applied 2 of 2" in dialog.status_var.get()
    assert dialog.apply_all_button.instate(["disabled"])
    dialog.apply_all_button.invoke()  # inert
    assert _slots(j.frame)[2][1] == ["soft light", "golden hour"]


def test_rejected_cards_are_listed_with_their_reason_and_have_no_apply_button(journey):  # noqa: F811
    j = journey
    _matrix(j.frame)
    dialog, request = ask_variety(j)
    deliver_variety(j, variety_outcome(request, ANSWER))
    rejected = [c for c in dialog.change_cards.cards if c.rejected]
    assert len(rejected) == 2 and all(c.detail for c in rejected)
    assert not any(c.key in dialog.change_cards.apply_buttons for c in rejected)


# -- apply and undo: new slot ---------------------------------------------------------------------------------------------------


@pytest.fixture
def proposals(journey):  # noqa: F811
    setup_proposals(journey.frame)
    return journey


def test_a_new_slot_card_shows_the_marker_in_place_and_examples(proposals):
    j = proposals
    dialog, request = ask_proposal(j)
    deliver_proposal(j, proposal_outcome(request, [_entry(point=1)]))
    (card,) = dialog.change_cards.cards
    assert card.offered and "[[lighting]]" in card.after and "[[lighting]]" not in card.before
    assert card.effect.startswith("Possible combinations go from 2 to 6")
    assert len(card.examples) == 3 and "golden hour" in card.examples[0]


def test_applying_a_new_slot_then_undoing_restores_slot_sentence_and_entries(proposals):
    j = proposals
    before = proposal_state(j.frame)
    dialog, request = ask_proposal(j)
    deliver_proposal(j, proposal_outcome(request, [_entry(point=1)]))
    _press(dialog, dialog.change_cards.offered_keys()[0])
    assert [s[0] for s in _slots(j.frame)] == ["location", "lighting"]
    assert "[[lighting]]" in j.frame.editor.get("1.0", "end-1c")
    assert j.flow.undo_last() is True
    assert proposal_state(j.frame) == before
    assert [c.offered for c in dialog.change_cards.cards] == [True]
    # the same card can be applied again after the undo
    _press(dialog, dialog.change_cards.offered_keys()[0])
    assert [s[0] for s in _slots(j.frame)] == ["location", "lighting"]


def test_undo_of_a_new_slot_refuses_after_the_sentence_was_edited(proposals):
    j = proposals
    dialog, request = ask_proposal(j)
    deliver_proposal(j, proposal_outcome(request, [_entry(point=1)]))
    _press(dialog, dialog.change_cards.offered_keys()[0])
    j.frame.editor.insert("end", " extra")
    j.frame._on_editor_modified(None)
    state = proposal_state(j.frame)
    assert j.flow.undo_last() is False
    assert proposal_state(j.frame) == state
    assert "cannot be undone automatically" in dialog.status_var.get()


# -- apply and undo: rewrite ---------------------------------------------------------------------------------------------------


def test_accepting_a_rewrite_is_journaled_and_undoable(journey):  # noqa: F811
    j = journey
    original = (
        j.frame.workspace_state.get_current_slot().text,
        j.frame.workspace_state.get_current_slot().negative,
    )
    dialog = start(j)
    finish(j)
    dialog.accept_button.invoke()
    slot = j.frame.workspace_state.get_current_slot()
    assert (slot.text, slot.negative) != original
    assert dialog.undo_button.instate(["!disabled"])
    assert j.flow.undo_last() is True
    slot = j.frame.workspace_state.get_current_slot()
    assert (slot.text, slot.negative) == original
    assert j.frame.editor.get("1.0", "end-1c") == original[0]


def test_undo_of_a_rewrite_refuses_after_a_manual_edit(journey):  # noqa: F811
    j = journey
    dialog = start(j)
    finish(j)
    dialog.accept_button.invoke()
    j.frame.editor.insert("end", " more")
    j.frame._on_editor_modified(None)
    typed = j.frame.workspace_state.get_current_slot().text
    assert j.flow.undo_last() is False
    assert j.frame.workspace_state.get_current_slot().text == typed


# -- journal lifetime -----------------------------------------------------------------------------------------------------------


def test_closing_the_window_clears_the_journal(journey):  # noqa: F811
    j = journey
    _matrix(j.frame)
    dialog, request = ask_variety(j)
    deliver_variety(j, variety_outcome(request, ANSWER))
    j.flow.apply_changes(dialog.change_cards.offered_keys()[:1])
    assert len(j.flow._journal) == 1
    dialog.close()
    assert len(j.flow._journal) == 0 and j.flow.dialog is None


def test_a_record_for_another_pack_is_dropped_not_undone(journey):  # noqa: F811
    j = journey
    _matrix(j.frame)
    dialog, request = ask_variety(j)
    deliver_variety(j, variety_outcome(request, ANSWER))
    j.flow.apply_changes(dialog.change_cards.offered_keys()[:1])
    j.frame.workspace_state.new_pack("other")
    j.frame._refresh_slot_list()
    j.frame._refresh_editor()
    j.flow.refresh()
    assert len(j.flow._journal) == 0 and dialog.undo_button.instate(["disabled"])


def test_the_journal_is_bounded_and_holds_no_content():
    journal = ApplyJournal()
    for n in range(30):
        journal.push(ApplyRecord("k", f"label {n}", 1, 0, lambda: ""))
    assert len(journal) == 20 and journal.last is not None and journal.last.label == "label 29"
    assert set(ApplyRecord.__slots__) == {"kind", "label", "pack_identity", "slot_index", "undo"}


# -- the new-slot bridge --------------------------------------------------------------------------------------------------------


def test_a_refused_variety_request_offers_the_new_slot_bridge_with_the_same_goal(journey):  # noqa: F811
    j = journey
    _matrix(j.frame)
    j.frame.workspace_state.set_slot_text(0, PROPOSAL_SENTENCE)
    j.frame._refresh_editor()
    dialog, request = ask_variety(j, goal="better lighting for hyperrealism", select=("lighting",))
    deliver_variety(j, AssistOutcome(OutcomeCode.REFUSED_BY_MODEL, request.request_id))
    assert dialog.bridge_button.winfo_manager() == "pack"
    dialog.bridge_button.invoke()
    last = j.service.requests[-1]
    assert last.kind is SuggestionKind.SLOT_PROPOSAL
    assert last.goal_text == "better lighting for hyperrealism"
    assert dialog.slots_mode_var.get() == "slot"


def test_ask_for_more_repeats_the_last_request(journey):  # noqa: F811
    j = journey
    _matrix(j.frame)
    dialog, request = ask_variety(j)
    deliver_variety(j, variety_outcome(request, ANSWER))
    assert dialog.more_button.instate(["!disabled"])
    count = len(j.service.requests)
    dialog.more_button.invoke()
    assert len(j.service.requests) == count + 1
    assert j.service.requests[-1].kind is SuggestionKind.SLOT_VARIETY
    assert j.service.requests[-1].goal_text == request.goal_text


def test_the_mode_switch_shows_one_function_at_a_time(journey):  # noqa: F811
    dialog = journey.flow.open()
    assert dialog.variety_button.winfo_manager() == "pack"
    assert dialog.proposal_button.winfo_manager() == ""
    dialog.set_slots_mode("slot")
    assert dialog.proposal_button.winfo_manager() == "pack"
    assert dialog.variety_button.winfo_manager() == ""
