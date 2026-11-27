"""AI-212 slot variety through the real Prompt tab, Matrix sub-tab and AI dialog, with a controllable synthetic service.

No model, process, network or display beyond a withdrawn Tk root. Proves that adding a value is the Matrix editor's own edit
(same state diff as a person typing it), that a stale context refuses, that nothing is saved or queued, and that the goal,
values and suggestions stay out of logs.
"""

from __future__ import annotations

import ast
import copy
import dataclasses
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
from src.ai_assist.validators import validate_output
from src.gui.app_state_v2 import AppStateV2
from src.gui.models.prompt_pack_model import MatrixSlot
from src.gui.prompt_ai_suggestions import PromptAiSuggestions
from src.gui.views.prompt_tab_frame_v2 import PromptTabFrame
from src.gui_v2.ai_slot_variety import VARIETY_NOTICE, VARIETY_REFUSED_HINT
from src.gui_v2.ai_suggestion_view import OUTCOME_TEXT
from tests.gui_v2.test_ai_suggestions_112 import journey  # noqa: F401 - shared fixture
from tests.gui_v2.test_prompt_target_130b import SDXL, _projection, _resolver

pytestmark = pytest.mark.gui

SENTENCE = "a [[character]] in the [[location]] under [[lighting]]"


def _matrix(frame, slots=None):
    config = frame.workspace_state.get_matrix_config()
    config.slots = [
        MatrixSlot(name=name, values=list(values))
        for name, values in (
            slots
            or (
                ("character", ("knight", "ranger")),
                ("location", ("forest",)),
                ("lighting", ("soft light",)),
            )
        )
    ]
    frame.workspace_state.set_slot_text(0, SENTENCE)
    frame._refresh_editor()
    frame.matrix_tab_panel.refresh()
    frame.workspace_state.dirty = False


@pytest.fixture
def variety(journey):  # noqa: F811 - the imported fixture
    _matrix(journey.frame)
    return journey


def _text(dialog) -> str:
    return dialog.status_var.get() + "\n" + dialog.preview.get("1.0", "end")


def _ask(
    j,
    goal="more variety in the lighting and places",
    select=("lighting", "location"),
    count="3",
    focus="direct",
):
    dialog = j.flow.open()
    assert dialog is not None and dialog.variety_button is not None
    dialog.variety_goal_var.set(goal)
    for name in select:
        dialog.variety_slot_vars[name].set(True)
    dialog.variety_count_var.set(count)
    dialog.variety_focus_var.set(focus)
    dialog.variety_button.invoke()
    return dialog, j.service.requests[-1]


def _outcome(request, slots, **kwargs):
    doc = {"schema": SUGGESTION_SCHEMA_ID, "status": "ok", "kind": "slot_variety", "slots": slots}
    validated = validate_output(json.dumps(doc), request)
    assert validated.suggestion is not None, validated.reason
    return AssistOutcome(
        OutcomeCode.SUGGESTION, request.request_id, suggestion=validated.suggestion, **kwargs
    )


ANSWER = [
    {
        "slot": "lighting",
        "values": ["golden hour", "Soft Light", "neon, rain"],
        "rationale": "warmer and cooler",
    },
    {"slot": "location", "values": ["harbor"], "rationale": "a new place"},
]


def _deliver(j, outcome):
    j.service.callbacks[-1](outcome)
    assert j.scheduled, "completion must be queued to the GUI thread"
    j.scheduled.pop(0)()


def _offered(dialog) -> list[str]:
    return [card.title for card in dialog.change_cards.cards if card.offered]


def _add(dialog, label: str) -> None:
    position = _offered(dialog).index(label)
    key = dialog.change_cards.offered_keys()[position]
    dialog.change_cards.apply_buttons[key].invoke()


def _type_manually(frame, index: int, text: str) -> None:
    """What a person does: type into the row's Values entry; its KeyRelease binding runs the panel's edit handler."""
    _name, values_entry, _delete = frame.matrix_tab_panel.slot_widgets[index]
    values_entry.delete(0, "end")
    values_entry.insert(0, text)
    frame.matrix_tab_panel._on_slot_changed(index)


# -- request --------------------------------------------------------------------------------------------------------------


def test_the_request_sends_goal_and_slots_only_from_the_workspace_matrix(variety):
    j = variety
    before = copy.deepcopy(j.frame.workspace_state.current_pack)
    dialog, request = _ask(j, select=("character", "location", "lighting"), count="2")
    assert request.kind is SuggestionKind.SLOT_VARIETY
    assert request.goal_text == "more variety in the lighting and places"
    assert request.matrix_slots == (
        ("character", ("knight", "ranger")),
        ("location", ("forest",)),
        ("lighting", ("soft light",)),
    )
    assert (request.allowed_targets, request.allowed_workflows, request.allowed_stages) == (
        (),
        (),
        (),
    )
    assert request.positive_text == "" and SENTENCE not in json.dumps(
        dataclasses.asdict(request), default=repr
    )
    assert request.content_class == "standard"
    assert "Suggest variety: request running" in dialog.status_var.get()
    assert dialog.variety_button.instate(["disabled"]) and dialog.cancel_button.instate(
        ["!disabled"]
    )
    assert j.frame.workspace_state.current_pack == before and not j.frame.workspace_state.dirty


def test_an_unofferable_slot_is_excluded_and_a_pack_without_slots_is_refused(variety):
    j = variety
    _matrix(j.frame, (("lighting", ("soft light",)), ("location", ("forest, at dusk",))))
    _dialog, request = _ask(j)
    assert request.matrix_slots == (("lighting", ("soft light",)),)
    _deliver(j, AssistOutcome(OutcomeCode.CANCELLED, request.request_id))
    j.flow.close()
    _matrix(j.frame, (("location", ("forest, at dusk",)),))
    dialog = j.flow.open()
    assert dialog.variety_button.instate(["disabled"])
    assert "No matrix slot can take a new value" in _text(dialog)


def test_a_blank_goal_or_unavailable_service_submits_nothing(variety):
    j = variety
    dialog = j.flow.open()
    dialog.variety_goal_var.set("   ")
    dialog.variety_button.invoke()
    assert not j.service.requests and "goal" in dialog.status_var.get().lower()
    j.owner.availability = lambda: (
        OutcomeCode.GENERATION_ACTIVE,
        OUTCOME_TEXT[OutcomeCode.GENERATION_ACTIVE],
    )
    dialog.variety_goal_var.set("more")
    dialog.variety_button.invoke()
    assert not j.service.requests
    assert OUTCOME_TEXT[OutcomeCode.GENERATION_ACTIVE] in dialog.status_var.get()


def test_the_dialog_names_the_slots_a_request_can_use_and_the_limit(variety):
    dialog = variety.flow.open()
    line = dialog.variety_slots_var.get()
    assert "character, location, lighting" in line
    assert "cannot take a new value" not in line
    assert "already exist in this pack's Matrix tab" in VARIETY_NOTICE


def test_a_slot_that_cannot_take_values_is_counted_not_listed(variety):
    j = variety
    _matrix(j.frame, (("lighting", ("soft light",)), ("location", ("forest, at dusk",))))
    line = j.flow.open().variety_slots_var.get()
    assert "lighting" in line and "location" not in line
    assert "1 other slot(s) cannot take a new value" in line


def test_a_refused_variety_request_points_to_the_matrix_tab_and_offers_raw_detail(variety):
    j = variety
    dialog, request = _ask(j, "lighting prompts for hyperrealism")
    raw = (
        '{"schema":"ai_assist.suggestion/1","status":"refused","refusal_reason":"no fitting slot"}'
    )
    _deliver(
        j,
        AssistOutcome(
            OutcomeCode.REFUSED_BY_MODEL,
            request.request_id,
            "status_refused",
            runtime_detail=RuntimeDetail(stdout_head=raw, reason="status_refused"),
        ),
    )
    status = dialog.status_var.get()
    assert OUTCOME_TEXT[OutcomeCode.REFUSED_BY_MODEL] in status
    assert VARIETY_REFUSED_HINT.strip() in status
    assert "no fitting slot" not in status and "no fitting slot" not in _text(dialog)
    assert dialog.detail_button.instate(["!disabled"])
    assert "no fitting slot" in dialog._detail_text
    assert not j.frame.workspace_state.dirty


# -- review and per-value acceptance --------------------------------------------------------------------------------------


def test_only_valid_values_are_offered_and_rejections_show_their_reason(variety):
    j = variety
    dialog, request = _ask(j)
    _deliver(j, _outcome(request, ANSWER))
    assert _offered(dialog) == ["lighting: golden hour", "location: harbor"]
    text = _text(dialog)
    assert VARIETY_NOTICE in text
    assert "[rejected] 'Soft Light': Already a value of this slot." in text
    assert "[rejected] 'neon, rain': Contains a comma" in text
    assert dialog.accept_button.instate(["disabled"]) and dialog.apply_selected_button.instate(
        ["!disabled"]
    )
    assert not j.frame.workspace_state.dirty


def test_adding_a_value_is_exactly_a_manual_edit_of_the_matrix(variety, tk_root, tmp_path):
    j = variety
    dialog, request = _ask(j)
    _deliver(j, _outcome(request, ANSWER))
    _add(dialog, "lighting: golden hour")

    manual = PromptTabFrame(tk_root, app_state=AppStateV2(), packs_dir=tmp_path / "manual")
    try:
        # Replay the journey fixture's own setup, then the same matrix, so only the edit differs.
        manual.target_lora_resolver = _resolver({})
        manual.workspace_state.set_slot_text(0, "a red barn <lora:kept:0.8> [[season]]")
        manual.workspace_state.set_slot_negative(0, "blurry")
        manual._refresh_editor()
        manual.on_model_projection(_projection(SDXL))
        _matrix(manual)
        _type_manually(manual, 2, "soft light,golden hour")
        ai_pack, manual_pack = (
            j.frame.workspace_state.current_pack,
            manual.workspace_state.current_pack,
        )
        assert dataclasses.asdict(ai_pack) == dataclasses.asdict(manual_pack)
        assert j.frame.workspace_state.dirty is manual.workspace_state.dirty is True
        assert j.frame.pack_name_label.cget("text") == manual.pack_name_label.cget("text")
        ai_row = [w.get() for w in j.frame.matrix_tab_panel.slot_widgets[2][:2]]
        assert ai_row == [w.get() for w in manual.matrix_tab_panel.slot_widgets[2][:2]]
    finally:
        manual.destroy()

    slots = j.frame.workspace_state.get_matrix_config().slots
    assert [s.name for s in slots] == [
        "character",
        "location",
        "lighting",
    ]  # no slot created or renamed
    assert [s.values for s in slots] == [
        ["knight", "ranger"],
        ["forest"],
        ["soft light", "golden hour"],
    ]
    assert (
        j.frame.workspace_state.get_current_slot().text == SENTENCE
    )  # the prompt sentence is untouched
    assert _offered(dialog) == ["location: harbor"]
    assert (
        "[added] golden hour" in _text(dialog) and "modified and unsaved" in dialog.status_var.get()
    )
    assert len(j.service.requests) == 1


def test_values_are_added_one_at_a_time_and_never_twice(variety):
    j = variety
    dialog, request = _ask(j)
    _deliver(j, _outcome(request, ANSWER))
    _add(dialog, "lighting: golden hour")
    _add(dialog, "location: harbor")
    slots = j.frame.workspace_state.get_matrix_config().slots
    assert slots[1].values == ["forest", "harbor"] and slots[2].values == [
        "soft light",
        "golden hour",
    ]
    assert _offered(dialog) == [] and dialog.apply_selected_button.instate(["disabled"])
    j.flow.add_variety_value(0)  # a repeated press of an added row is inert
    assert slots[2].values == ["soft light", "golden hour"]


def test_nothing_is_saved_queued_or_previewed(variety, tmp_path, monkeypatch):
    j = variety
    saves, invalidations = [], []
    monkeypatch.setattr(
        j.frame.workspace_state, "save_current_pack", lambda *a, **k: saves.append(1), raising=False
    )
    monkeypatch.setattr(j.state, "invalidate_preview", lambda *a, **k: invalidations.append(1))
    dialog, request = _ask(j)
    _deliver(j, _outcome(request, ANSWER))
    _add(dialog, "location: harbor")
    assert saves == [] and invalidations == []
    packs = tmp_path / "packs"
    assert not packs.exists() or not any(packs.rglob("*"))
    assert j.frame.workspace_state.dirty


# -- stale and pending-edit refusals --------------------------------------------------------------------------------------


def test_a_matrix_change_after_the_review_refuses_acceptance(variety):
    j = variety
    dialog, request = _ask(j)
    _deliver(j, _outcome(request, ANSWER))
    _type_manually(j.frame, 1, "forest,desert")
    before = copy.deepcopy(j.frame.workspace_state.get_matrix_config().slots)
    _add(dialog, "lighting: golden hour")
    assert j.frame.workspace_state.get_matrix_config().slots == before
    assert "changed since the request" in dialog.status_var.get()
    assert _offered(dialog) == [] and dialog.preview.get("1.0", "end").strip() == ""


def test_a_matrix_change_while_the_model_runs_offers_nothing(variety):
    j = variety
    dialog, request = _ask(j)
    _type_manually(j.frame, 2, "soft light,dusk")
    _deliver(j, _outcome(request, ANSWER))
    assert _offered(dialog) == [] and "changed" in dialog.status_var.get()
    assert j.flow._variety is None


def test_switching_pack_refuses_acceptance(variety):
    j = variety
    dialog, request = _ask(j)
    _deliver(j, _outcome(request, ANSWER))
    replacement = copy.deepcopy(j.frame.workspace_state.current_pack)
    j.frame.workspace_state.current_pack = replacement
    _add(dialog, "lighting: golden hour")
    assert replacement.matrix.slots[2].values == ["soft light"]
    assert "changed since the request" in dialog.status_var.get()


def test_a_pending_manual_edit_in_the_row_refuses_without_change(variety):
    j = variety
    dialog, request = _ask(j)
    _deliver(j, _outcome(request, ANSWER))
    _name, values_entry, _delete = j.frame.matrix_tab_panel.slot_widgets[2]
    values_entry.insert("end", ",half-typed")  # typed but its handler has not run yet
    _add(dialog, "lighting: golden hour")
    assert j.frame.workspace_state.get_matrix_config().slots[2].values == ["soft light"]
    assert "unfinished edit" in dialog.status_var.get()
    assert not j.frame.workspace_state.dirty


# -- outcomes, trust and privacy ------------------------------------------------------------------------------------------


def test_a_failure_shows_fixed_copy_and_offers_nothing(variety):
    j = variety
    dialog, request = _ask(j)
    _deliver(
        j, AssistOutcome(OutcomeCode.REFUSED_BY_MODEL, request.request_id, reason="private words")
    )
    assert OUTCOME_TEXT[OutcomeCode.REFUSED_BY_MODEL] in dialog.status_var.get()
    assert "private" not in _text(dialog) and _offered(dialog) == []


def test_every_variety_surface_carries_the_preview_label(variety):
    j = variety
    dialog, request = _ask(j)
    _deliver(j, _outcome(request, ANSWER, details={"trust_tier": "preview"}))
    assert PREVIEW_LABEL in dialog.trust_var.get()
    assert PREVIEW_LABEL in dialog.status_var.get() and PREVIEW_LABEL in dialog.preview.get(
        "1.0", "end"
    )
    _add(dialog, "location: harbor")
    assert PREVIEW_LABEL in dialog.status_var.get() and PREVIEW_LABEL in dialog.preview.get(
        "1.0", "end"
    )


def test_closing_scrubs_the_goal_and_drops_a_late_answer(variety):
    j = variety
    dialog, request = _ask(j, goal="private goal words")
    dialog.close()
    assert dialog.variety_goal_var.get() == ""
    _deliver(j, _outcome(request, ANSWER))
    assert j.flow.dialog is None and j.flow._variety is None
    assert j.frame.workspace_state.get_matrix_config().slots[2].values == ["soft light"]


def test_cancel_while_running_offers_nothing(variety):
    j = variety
    dialog, request = _ask(j)
    j.flow.cancel()
    _deliver(j, _outcome(request, ANSWER))
    assert _offered(dialog) == [] and "cancelled" in dialog.status_var.get().lower()


def test_values_goal_and_suggestions_never_reach_the_log(variety, caplog):
    j = variety
    caplog.set_level("DEBUG")
    _matrix(j.frame, (("lighting", ("CANARY-VALUE-91",)),))
    dialog, request = _ask(j, goal="CANARY-GOAL-91", select=("lighting",))
    _deliver(
        j,
        _outcome(
            request, [{"slot": "lighting", "values": ["CANARY-NEW-91"], "rationale": "CANARY-WHY"}]
        ),
    )
    _add(dialog, "lighting: CANARY-NEW-91")
    assert "CANARY" not in caplog.text


# -- no path from this kind to Intent, the compiler or the queue (extends the AI-210 guard) -------------------------------

_FORBIDDEN = re.compile(r"njr|queue|compile|intent|job|save|preview_jobs|run_now|pipeline", re.I)


@pytest.mark.parametrize(
    "method",
    [
        "suggest_variety",
        "_variety_completed",
        "add_variety_value",
        "_variety_review",
        "_capture_matrix",
        "_variety_context",
    ],
)
def test_the_variety_path_names_nothing_that_could_save_compile_or_queue(method):
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
    # The only workspace mutation is the Matrix editor's own edit path.
    assert not calls & {
        "set_matrix_config",
        "set_slot_text",
        "set_slot_negative",
        "mark_dirty",
        "append",
    }


def test_the_only_matrix_mutation_is_the_editor_append():
    source = inspect.getsource(PromptAiSuggestions.add_variety_value)
    assert "matrix_tab_panel.append_slot_value(" in source
    assert ".values" not in source.replace("row.value", "")


# -- AI-214: target slots, quantity, focus and coverage ------------------------------------------------------------------


def _blocked(j, **kw):
    """Ask and expect no request to be sent; returns the dialog."""
    before = len(j.service.requests)
    dialog = j.flow.open()
    dialog.variety_goal_var.set("more realistic lighting")
    for name in kw.get("select", ()):
        dialog.variety_slot_vars[name].set(True)
    dialog.variety_count_var.set(kw.get("count", "3"))
    dialog.variety_button.invoke()
    assert len(j.service.requests) == before
    return dialog


def test_a_new_dialog_starts_with_no_slot_selected_and_lists_every_slot(variety):
    dialog = variety.flow.open()
    assert set(dialog.variety_slot_vars) == {"character", "location", "lighting"}
    assert dialog.selected_variety_slots() == ()
    assert "none" in dialog.variety_scope_var.get().lower()
    assert dialog.variety_count_var.get() == "3" and dialog.variety_focus_var.get() == "direct"


def test_select_all_clear_and_the_summary_track_the_selection(variety):
    dialog = variety.flow.open()
    dialog.select_all_variety_slots()
    assert dialog.selected_variety_slots() == ("character", "location", "lighting")
    assert "Requested: 9 value(s)" in dialog.variety_scope_var.get()
    dialog.clear_variety_slots()
    assert dialog.selected_variety_slots() == ()
    dialog.variety_slot_vars["lighting"].set(True)
    dialog._variety_scope_changed()
    assert "Selected: lighting" in dialog.variety_scope_var.get()
    assert "Requested: 3 value(s)" in dialog.variety_scope_var.get()


def test_an_empty_selection_blocks_before_inference(variety):
    dialog = _blocked(variety)
    assert (
        "at least one" in dialog.preview.get("1.0", "end").lower() + dialog.status_var.get().lower()
    )


@pytest.mark.parametrize("count", ["0", "7", "x", "", "2.5", "-1"])
def test_an_invalid_count_blocks_before_inference(variety, count):
    dialog = _blocked(variety, select=("lighting",), count=count)
    assert "whole number from 1 to 6" in dialog.status_var.get()


def test_the_aggregate_limit_blocks_and_explains_how_to_reduce(variety):
    dialog = _blocked(variety, select=("character", "location", "lighting"), count="6")
    assert "Reduce" in dialog.status_var.get()


def test_only_the_selected_slot_reaches_the_model_request(variety):
    j = variety
    _dialog, request = _ask(j, select=("lighting",))
    assert request.matrix_slots == (("lighting", ("soft light",)),)
    blob = json.dumps(dataclasses.asdict(request), default=repr)
    assert "character" not in blob and "knight" not in blob and "forest" not in blob
    assert (request.variety_per_slot, request.variety_focus) == (3, "direct")


def test_count_and_focus_reach_the_request_and_its_identity(variety):
    j = variety
    _dialog, direct = _ask(j, select=("lighting",), count="2")
    _deliver(j, _outcome(direct, [{"slot": "lighting", "values": ["dusk"], "rationale": "x"}]))
    _dialog, explore = _ask(j, select=("lighting",), count="2", focus="explore")
    assert (explore.variety_per_slot, explore.variety_focus) == (2, "explore")
    assert direct.digest() != explore.digest()


def test_a_model_answer_for_an_unselected_slot_is_never_offered(variety):
    j = variety
    _dialog, request = _ask(j, select=("lighting",))
    doc = {
        "schema": SUGGESTION_SCHEMA_ID,
        "status": "ok",
        "kind": "slot_variety",
        "slots": [{"slot": "location", "values": ["harbor"], "rationale": "x"}],
    }
    assert validate_output(json.dumps(doc), request).code is OutcomeCode.MALFORMED


def test_partial_coverage_is_shown_and_remaining_values_stay_addable(variety):
    j = variety
    dialog, request = _ask(j, select=("location", "lighting"), count="3")
    answer = [{"slot": "lighting", "values": ["golden hour", "dusk"], "rationale": "warm"}]
    _deliver(j, _outcome(request, answer))
    assert "Partial coverage: 2 of 6 requested values returned" in dialog.status_var.get()
    assert "Partial coverage" in dialog.variety_coverage_var.get()
    text = dialog.preview.get("1.0", "end")
    assert "PARTIAL COVERAGE" in text and "location  3 requested / 0 returned / 0 eligible" in text
    assert "not independently relevance-verified" in text
    assert _offered(dialog) == ["lighting: golden hour", "lighting: dusk"]
    _add(dialog, "lighting: dusk")
    assert j.frame.workspace_state.get_matrix_config().slots[2].values == ["soft light", "dusk"]
    assert "1 added" in dialog.preview.get("1.0", "end")


def test_a_genuine_refusal_stays_a_refusal_with_no_coverage(variety):
    j = variety
    dialog, request = _ask(j, select=("lighting",))
    _deliver(j, AssistOutcome(OutcomeCode.REFUSED_BY_MODEL, request.request_id))
    assert OUTCOME_TEXT[OutcomeCode.REFUSED_BY_MODEL] in dialog.status_var.get()
    assert _offered(dialog) == [] and dialog.variety_coverage_var.get() == ""


def test_a_change_to_a_nonselected_slot_still_makes_the_request_stale(variety):
    j = variety
    dialog, request = _ask(j, select=("lighting",))
    _type_manually(j.frame, 0, "knight,ranger,mage")  # 'character' was not selected
    _deliver(j, _outcome(request, [{"slot": "lighting", "values": ["dusk"], "rationale": "x"}]))
    assert _offered(dialog) == [] and j.flow._variety is None


def test_a_nonselected_change_after_review_refuses_addition(variety):
    j = variety
    dialog, request = _ask(j, select=("lighting",))
    _deliver(j, _outcome(request, [{"slot": "lighting", "values": ["dusk"], "rationale": "x"}]))
    _type_manually(j.frame, 0, "knight,ranger,mage")
    _add(dialog, "lighting: dusk")
    assert j.frame.workspace_state.get_matrix_config().slots[2].values == ["soft light"]
    assert "changed since the request" in dialog.status_var.get()


def test_a_slot_that_cannot_take_a_value_is_listed_disabled(journey):  # noqa: F811
    _matrix(journey.frame, (("good", ("a",)), ("bad", ("x, y",))))
    dialog = journey.flow.open()
    assert "disabled" in dialog.variety_slot_checks["bad"].state()
    assert "disabled" not in dialog.variety_slot_checks["good"].state()
    dialog.variety_slot_vars["bad"].set(True)
    assert dialog.selected_variety_slots() == ()


def test_closing_clears_the_selection(variety):
    dialog = variety.flow.open()
    dialog.variety_slot_vars["lighting"].set(True)
    dialog.clear_sensitive()
    assert dialog.selected_variety_slots() == ()
