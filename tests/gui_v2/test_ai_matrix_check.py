"""AI-230e: deterministic Check tab findings, the exact-duplicate fix, its Undo and its stale refusal. No model."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from src.gui.models.prompt_pack_model import MatrixSlot
from src.gui_v2.ai_changes import KIND_NOTE, KIND_REMOVE_DUPLICATE
from src.gui_v2.ai_matrix_check import (
    check_summary,
    dedupe_values,
    finding_cards,
    run_checks,
    with_slot_values,
)
from src.gui_v2.ai_slot_variety import HIDDEN_TEXT, VarietyContext, matrix_state
from tests.gui_v2.test_ai_suggestions_112 import journey  # noqa: F401 - shared fixture

pytestmark = pytest.mark.gui


def _slots(*pairs):
    return matrix_state([SimpleNamespace(name=n, values=list(v)) for n, v in pairs])


def _codes(findings):
    return [f.code for f in findings]


# -- pure checks -------------------------------------------------------------------------------------------------------------


def test_a_clean_matrix_has_no_findings():
    slots = _slots(("light", ["dawn", "dusk"]), ("place", ["forest", "harbor"]))
    findings = run_checks(slots, [("a [[light]] [[place]]", "")])
    assert findings == () and check_summary(findings) == "No problems found."


def test_unused_and_undefined_markers_are_found_across_every_pack_prompt():
    slots = _slots(("light", ["dawn", "dusk"]), ("place", ["forest", "harbor"]))
    findings = run_checks(slots, [("a [[light]]", ""), ("b [[mood]]", "no [[place]]")])
    assert _codes(findings) == ["undefined_marker"]  # place is used by the negative of prompt 2
    assert "Prompt 2" in findings[0].detail
    only = run_checks(slots, [("a [[light]]", "")])
    assert _codes(only) == ["unused_slot"] and "Matrix tab row 2" in only[0].detail


def test_marker_matching_uses_the_compilers_normalized_names():
    slots = _slots(("hair_color", ["red", "blue"]))
    assert run_checks(slots, [("a [[Hair Color]]", "")]) == ()


def test_exact_duplicates_are_a_fixable_finding_that_keeps_the_first_copy():
    slots = _slots(("light", ["dawn", "dusk", "dawn", "noon", "dusk"]))
    (finding,) = run_checks(slots, [("[[light]]", "")])
    assert finding.code == "exact_duplicate" and finding.fix == "dedupe"
    assert finding.before == ("dawn", "dusk", "dawn", "noon", "dusk")
    assert finding.after == ("dawn", "dusk", "noon") == dedupe_values(finding.before)
    (card,) = finding_cards([finding])
    assert card.kind == KIND_REMOVE_DUPLICATE and card.offered and "dawn, dusk, noon" in card.after


def test_a_slot_the_editor_would_reparse_is_reported_but_not_fixable():
    slots = _slots(("light", ["dawn, early", "dawn, early"]))
    (finding, *_) = run_checks(slots, [("[[light]]", "")])
    assert finding.code == "exact_duplicate" and finding.fix == ""
    assert finding_cards([finding])[0].kind == KIND_NOTE


def test_near_duplicates_single_values_and_empty_slots_are_notes_only():
    slots = _slots(
        ("light", ["Soft Light", "soft  light", "hard"]),
        ("one", ["only"]),
        ("none", []),
    )
    findings = run_checks(slots, [("[[light]] [[one]] [[none]]", "")])
    assert sorted(_codes(findings)) == ["empty_slot", "near_duplicate", "single_value"]
    assert all(card.kind == KIND_NOTE and not card.offered for card in finding_cards(findings))


def test_plural_variants_count_as_near_duplicates():
    findings = run_checks(_slots(("pet", ["cat", "cats", "owl"])), [("[[pet]]", "")])
    assert _codes(findings) == ["near_duplicate"]


def test_a_very_unbalanced_matrix_is_noted_once():
    big = [f"v{i}" for i in range(20)]
    findings = run_checks(_slots(("a", big), ("b", ["x", "y"])), [("[[a]] [[b]]", "")])
    assert _codes(findings) == ["unbalanced"]


def test_duplicate_slot_names_and_unnamed_rows_warn():
    slots = _slots(("Light", ["a", "b"]), ("light", ["c", "d"]), ("", ["e"]))
    codes = _codes(run_checks(slots, [("[[light]]", "")]))
    assert codes.count("duplicate_slot_name") == 2 and "unnamed_slot" in codes


def test_warnings_come_before_notes_and_keys_follow_that_order():
    slots = _slots(("one", ["only"]), ("dup", ["a", "a", "b"]))
    findings = run_checks(slots, [("[[dup]] [[one]]", "")])
    assert [f.severity for f in findings] == ["warning", "info"]
    assert [f.key for f in findings] == ["check:0", "check:1"]


def test_hidden_slot_names_and_values_never_appear_in_a_finding_or_card():
    slots = _slots(("secret", ["alpha", "alpha", "beta"]))

    def visible(text: str) -> bool:
        return "secret" not in text and "alpha" not in text

    findings = run_checks(slots, [("[[secret]]", "")], is_visible=visible)
    cards = finding_cards(findings, is_visible=visible)
    blob = " ".join(f"{f.title} {f.detail}" for f in findings) + " ".join(
        f"{c.title} {c.before} {c.after} {c.effect} {c.detail}" for c in cards
    )
    assert "secret" not in blob and "alpha" not in blob and HIDDEN_TEXT in blob


def test_with_slot_values_matches_what_the_matrix_state_reads_back():
    context = VarietyContext(1, 2, _slots(("a", ["x", "x", "y"]), ("b", ["1"])), "mode")
    after = with_slot_values(context, 0, ["x", "y"])
    assert [list(s.values) for s in after.slots] == [["x", "y"], ["1"]]
    assert after.pack_identity == 1 and after.matrix_identity == 2


# -- the Check tab through the real Prompt tab ----------------------------------------------------------------------------


def _frame_matrix(frame, slots, text="a [[light]] [[place]]"):
    config = frame.workspace_state.get_matrix_config()
    config.slots = [MatrixSlot(name=n, values=list(v)) for n, v in slots]
    frame.workspace_state.set_slot_text(0, text)
    frame._refresh_editor()
    frame.matrix_tab_panel.refresh()
    frame.workspace_state.dirty = False


def _stored(frame):
    return [(s.name, list(s.values)) for s in frame.workspace_state.get_matrix_config().slots]


def test_selecting_the_check_tab_runs_the_checks_without_a_model_request(journey):  # noqa: F811
    j = journey
    _frame_matrix(j.frame, [("light", ["a", "b"]), ("place", ["x", "y"]), ("extra", ["q", "r"])])
    dialog = j.flow.open()
    dialog.select_tab("check")
    dialog.update()
    assert "1 warning(s)" in dialog.check_summary_var.get()
    assert any("not used by any prompt" in c.title for c in dialog.check_cards.cards)
    assert not j.service.requests


def test_applying_the_duplicate_fix_edits_only_that_slot_and_undo_restores_it(journey):  # noqa: F811
    j = journey
    _frame_matrix(j.frame, [("light", ["a", "b", "a"]), ("place", ["x", "y"])])
    dialog = j.flow.open()
    dialog.check_button.invoke()
    (key,) = dialog.check_cards.offered_keys()
    before = (_stored(j.frame), [(w[0].get(), w[1].get()) for w in j.frame.matrix_tab_panel.slot_widgets])
    dialog.check_cards.apply_buttons[key].invoke()
    assert _stored(j.frame) == [("light", ["a", "b"]), ("place", ["x", "y"])]
    assert j.frame.workspace_state.dirty and "No problems found." == dialog.check_summary_var.get()
    assert dialog.undo_button.instate(["!disabled"])
    assert j.flow.undo_last() is True
    assert (
        _stored(j.frame),
        [(w[0].get(), w[1].get()) for w in j.frame.matrix_tab_panel.slot_widgets],
    ) == before
    assert "1 warning(s)" in dialog.check_summary_var.get()


def test_the_fix_refuses_when_the_matrix_changed_since_the_checks_ran(journey):  # noqa: F811
    j = journey
    _frame_matrix(j.frame, [("light", ["a", "b", "a"]), ("place", ["x", "y"])])
    dialog = j.flow.open()
    dialog.check_button.invoke()
    (key,) = dialog.check_cards.offered_keys()
    _name, values_entry, _del = j.frame.matrix_tab_panel.slot_widgets[1]
    values_entry.delete(0, "end")
    values_entry.insert(0, "x,y,z")
    j.frame.matrix_tab_panel._on_slot_changed(1)
    stored = _stored(j.frame)
    dialog.check_cards.apply_buttons[key].invoke()
    assert _stored(j.frame) == stored
    assert "changed since the checks ran" in dialog.status_var.get()
    assert len(j.flow._journal) == 0


def test_the_check_tab_makes_no_ai_request_and_persists_nothing(journey):  # noqa: F811
    j = journey
    _frame_matrix(j.frame, [("light", ["a", "a"]), ("place", ["x", "y"])])
    dialog = j.flow.open()
    dialog.check_button.invoke()
    dialog.check_cards.apply_buttons[dialog.check_cards.offered_keys()[0]].invoke()
    assert not j.service.requests
    dialog.close()
    assert j.flow._check_findings == () and j.flow._check_context is None
