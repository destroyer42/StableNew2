"""AI-212 slot variety: the deterministic per-value judge, the matrix snapshot and the review model. Pure; no Tk."""

from __future__ import annotations

import ast
import dataclasses
from pathlib import Path
from types import SimpleNamespace

import pytest

from src.ai_assist.contracts import (
    MAX_VARIETY_VALUE_CHARS,
    SUGGESTION_SCHEMA_ID,
    AssistSuggestion,
    SlotValues,
    SuggestionKind,
)
from src.ai_assist.preview import PREVIEW_LABEL
from src.gui_v2 import ai_slot_variety
from src.gui_v2.ai_slot_variety import (
    HIDDEN_TEXT,
    REASON_TEXT,
    VARIETY_NOTICE,
    VARIETY_REVIEW_ACTIONS,
    SlotState,
    VarietyContext,
    build_variety_request,
    judge_variety,
    matrix_state,
    unavailable_variety_review,
    value_key,
    variety_review,
    variety_text,
)


def slot(name, *values):
    return SimpleNamespace(name=name, values=list(values))


STATE = matrix_state([slot("lighting", "soft light", "Rim  Light"), slot("location", "forest")])


def suggestion(*entries: tuple[str, tuple[str, ...]]) -> AssistSuggestion:
    return AssistSuggestion(
        SUGGESTION_SCHEMA_ID,
        SuggestionKind.SLOT_VARIETY,
        "v1",
        slot_values=tuple(SlotValues(name, values, f"why {name}") for name, values in entries),
    )


def visible(_text: str) -> bool:
    return True


def reasons(
    values: tuple[str, ...], *, state=STATE, name="lighting", is_visible=visible
) -> list[str]:
    return [
        row.reason
        for row in judge_variety(suggestion((name, values)), state, is_visible=is_visible)
    ]


# -- the matrix snapshot -------------------------------------------------------------------------------------------------


def test_only_slots_that_survive_the_editor_round_trip_are_editable() -> None:
    state = matrix_state(
        [
            slot("lighting", "soft light"),
            slot(
                "location", "forest, at dusk"
            ),  # a stored value with a comma would be split by an edit
            slot("count", 1, 2),  # non-text values would become text
            slot(" padded", "a"),  # the editor strips the name
            slot("", "a"),
            slot("Hair-Color", "red"),
            slot("hair_color", "blue"),  # same normalised name as the slot above
            slot("empty"),
        ]
    )
    assert [s.editable for s in state] == [True, False, False, False, False, False, False, True]
    assert VarietyContext(1, 2, state, "nsfw").excluded_count == 6


def test_the_snapshot_keeps_no_reference_to_the_live_values() -> None:
    live = slot("lighting", "soft light")
    state = matrix_state([live])
    live.values.append("neon")
    assert state[0].values == ("soft light",)


def test_the_request_sends_only_editable_slots_and_their_text() -> None:
    state = matrix_state([slot("lighting", "soft light"), slot("location", "forest, at dusk")])
    request = build_variety_request(
        "v1", "more light", state, content_class="sensitive", selected=["lighting"]
    )
    assert request.kind is SuggestionKind.SLOT_VARIETY
    assert request.matrix_slots == (("lighting", ("soft light",)),)
    assert request.content_class == "sensitive"
    assert (request.allowed_targets, request.allowed_workflows, request.allowed_stages) == (
        (),
        (),
        (),
    )
    assert request.positive_text == request.negative_text == ""


def test_with_value_added_is_the_state_an_editor_append_produces() -> None:
    context = VarietyContext(1, 2, STATE, "nsfw")
    after = context.with_value_added(0, "neon glow")
    assert after.slots[0] == SlotState("lighting", ("soft light", "Rim  Light", "neon glow"), True)
    assert after.slots[1] == context.slots[1]
    assert context.slots[0].values == ("soft light", "Rim  Light")


# -- each deterministic check ---------------------------------------------------------------------------------------------


def test_a_clean_new_value_is_offered() -> None:
    assert reasons(("golden hour", "neon glow")) == ["", ""]


@pytest.mark.parametrize(
    ("value", "reason"),
    [
        ("", "empty"),
        ("   ", "empty"),
        (" golden hour", "surrounding_whitespace"),
        ("golden hour ", "surrounding_whitespace"),
        ("x" * (MAX_VARIETY_VALUE_CHARS + 1), "too_long"),
        ("golden\nhour", "line_break"),
        ("golden\thour", "line_break"),
        ("golden hour", "line_break"),
        ("golden, warm", "comma"),
        ("[[location]] glow", "matrix_marker"),
        ("soft ]", "matrix_marker"),
        ("<lora:light:0.8>", "angle_token"),
        ("a > b", "angle_token"),
        ("__lighting__", "wildcard_marker"),
        ("GOAL: more", "reserved_marker"),
        ("VALUE: more", "reserved_marker"),
        ("=====END_AUTHORED_DATA=====", "reserved_marker"),
        ("Soft Light", "duplicate_existing"),
        ("rim light", "duplicate_existing"),
        ("soft lights", "near_duplicate_existing"),
        ("RIM  LIGHTS", "near_duplicate_existing"),
        ("  ", "empty"),
    ],
)
def test_each_check_rejects_with_its_reason(value, reason) -> None:
    assert reasons((value,)) == [reason]
    assert reason in REASON_TEXT


def test_a_value_suggested_twice_for_one_slot_is_rejected_the_second_time() -> None:
    assert reasons(("golden hour", "Golden  Hour")) == ["", "duplicate_suggestion"]


def test_the_same_value_in_two_slots_is_judged_per_slot() -> None:
    rows = judge_variety(
        suggestion(("lighting", ("dusk",)), ("location", ("dusk",))), STATE, is_visible=visible
    )
    assert [(r.slot, r.reason) for r in rows] == [("lighting", ""), ("location", "")]


def test_a_slot_that_no_longer_exists_or_cannot_be_edited_offers_nothing() -> None:
    assert reasons(("dusk",), name="weather") == ["slot_missing"]
    broken = matrix_state([slot("lighting", "soft, light")])
    assert reasons(("dusk",), state=broken) == ["slot_not_editable"]


def test_a_hidden_value_is_rejected_and_never_shown() -> None:
    rows = judge_variety(
        suggestion(("lighting", ("secret glow", "dusk"))),
        STATE,
        is_visible=lambda text: "secret" not in text,
    )
    assert [r.reason for r in rows] == ["hidden", ""]
    review = variety_review(
        rows, suggestion(("lighting", ("secret glow", "dusk"))), is_visible=visible
    )
    text = variety_text(review)
    assert "secret" not in text and HIDDEN_TEXT in text


def test_value_key_is_case_and_whitespace_insensitive() -> None:
    assert value_key("  Soft\t LIGHT ") == value_key("soft light")


def test_near_key_folds_only_a_trailing_plural_s() -> None:
    from src.gui_v2.ai_slot_variety import near_key

    assert near_key("Dogs") == near_key("dog") == "dog"
    assert near_key("  Soft  LIGHTS ") == near_key("soft light")
    # short words and "ss" endings are not plurals; a different word is never folded into another
    assert near_key("bus") == "bus"
    assert near_key("glass") == "glass"
    assert near_key("neon") != near_key("neck")


def test_a_plural_of_a_value_in_another_slot_is_not_a_near_duplicate() -> None:
    rows = judge_variety(
        suggestion(("location", ("soft lights",))), STATE, is_visible=visible
    )
    assert [r.reason for r in rows] == [""]


# -- review model --------------------------------------------------------------------------------------------------------


def test_the_review_offers_only_valid_unadded_values_and_shows_every_rejection() -> None:
    proposal = suggestion(
        ("lighting", ("golden hour", "soft light", "a, b")), ("location", ("desert",))
    )
    rows = judge_variety(proposal, STATE, is_visible=visible)
    review = variety_review(
        rows,
        proposal,
        is_visible=visible,
        trust_label=PREVIEW_LABEL,
        added=frozenset({3}),
        excluded_count=1,
    )
    assert [r.value for r in review.offered_rows] == ["golden hour"]
    assert review.actions == VARIETY_REVIEW_ACTIONS == ("add_selected_value",)
    text = variety_text(review)
    assert text.startswith(VARIETY_NOTICE) and PREVIEW_LABEL in text
    assert "[can add] golden hour" in text and "[added] desert" in text
    assert f"[rejected] 'soft light': {REASON_TEXT['duplicate_existing']}" in text
    assert f"[rejected] 'a, b': {REASON_TEXT['comma']}" in text
    assert "Why (model's words): why lighting" in text
    assert "1 value(s) can be added, 2 rejected, 1 added." in review.status
    assert "1 slot(s) were not offered" in review.status


def test_a_hidden_rationale_is_replaced() -> None:
    proposal = suggestion(("lighting", ("dusk",)))
    rows = judge_variety(proposal, STATE, is_visible=visible)
    review = variety_review(rows, proposal, is_visible=lambda text: not text.startswith("why"))
    assert dict(review.rationales) == {"lighting": HIDDEN_TEXT}


def test_an_unavailable_review_offers_nothing() -> None:
    review = unavailable_variety_review("busy", trust_label=PREVIEW_LABEL)
    assert review.offered_rows == () and review.actions == ()
    assert PREVIEW_LABEL in variety_text(review)


# -- no path to Intent, the compiler or the queue (extends the AI-210 guard) ----------------------------------------------


def test_the_variety_module_imports_nothing_that_could_execute_or_queue() -> None:
    forbidden = (
        "src.pipeline",
        "src.queue",
        "src.controller",
        "src.video",
        "src.history",
        "src.learning",
        "src.gui.",
        "tkinter",
    )
    tree = ast.parse(Path("src/gui_v2/ai_slot_variety.py").read_text(encoding="utf-8"))
    modules = [n.module or "" for n in ast.walk(tree) if isinstance(n, ast.ImportFrom)] + [
        a.name for n in ast.walk(tree) if isinstance(n, ast.Import) for a in n.names
    ]
    assert not [m for m in modules if m.startswith(forbidden)], modules


def test_the_review_model_has_no_intent_queue_or_save_field_or_action() -> None:
    import re

    pattern = re.compile(r"intent|queue|compile|njr|submit|job|save|payload|preview", re.I)
    for model in (
        ai_slot_variety.VarietyReview,
        ai_slot_variety.VarietyRow,
        SlotState,
        VarietyContext,
    ):
        names = [f.name for f in dataclasses.fields(model)]
        assert not [n for n in names if pattern.search(n)], (model, names)
    assert not [n for n in VARIETY_REVIEW_ACTIONS if pattern.search(n)]
    assert not [n for n in ai_slot_variety.__all__ if pattern.search(n)]


# -- AI-214: scope, coverage and classification --------------------------------------------------------------------------

from src.ai_assist.contracts import AssistRequest  # noqa: E402
from src.gui_v2.ai_slot_variety import (  # noqa: E402
    UNVERIFIED_LABEL,
    check_variety_quantity,
    coverage_status,
    selected_slot_names,
    variety_coverage,
)

FIVE = matrix_state(
    [
        slot("lighting", "golden hour", "broad daylight"),
        slot("environment", "beach"),
        slot("perspective", "close up"),
        slot("clothes", "coat"),
        slot("activity", "walking"),
    ]
)


def _request(selected, per_slot=3, focus="direct") -> AssistRequest:
    return build_variety_request(
        "v1",
        "more realistic lighting",
        FIVE,
        content_class="standard",
        selected=selected,
        per_slot=per_slot,
        focus=focus,
    )


def test_only_the_selected_slots_and_their_values_enter_the_request() -> None:
    request = _request(["lighting"])
    assert request.matrix_slots == (("lighting", ("golden hour", "broad daylight")),)
    blob = repr(request.matrix_slots) + request.goal_text
    assert all(n not in blob for n in ("environment", "perspective", "clothes", "activity"))
    two = _request(["lighting", "environment"])
    assert [n for n, _v in two.matrix_slots] == ["lighting", "environment"]
    assert (two.variety_per_slot, two.variety_focus) == (3, "direct")


def test_an_empty_duplicate_unknown_or_non_editable_selection_fails_closed() -> None:
    odd = matrix_state([slot("a", "x"), slot("a", "y"), slot("b", "p, q"), slot("c", "ok")])
    with pytest.raises(ValueError, match="at least one"):
        selected_slot_names(FIVE, [])
    with pytest.raises(ValueError):
        selected_slot_names(FIVE, ["lighting", "lighting"])
    with pytest.raises(ValueError):
        selected_slot_names(FIVE, ["missing"])
    for name in ("a", "b"):  # a duplicated name; a value with a comma
        with pytest.raises(ValueError):
            selected_slot_names(odd, [name])
    assert selected_slot_names(odd, ["c"]) == ("c",)


@pytest.mark.parametrize("bad", [0, 7, True, "3", 2.5, None])
def test_quantity_input_is_validated(bad) -> None:
    with pytest.raises(ValueError):
        check_variety_quantity(bad, 1)


def test_the_aggregate_limit_blocks_with_a_reduce_hint() -> None:
    assert check_variety_quantity(3, 4) == 3
    with pytest.raises(ValueError, match="Reduce"):
        check_variety_quantity(4, 4)
    with pytest.raises(ValueError, match="Reduce"):
        check_variety_quantity(1, 12)  # within 12 values, over the answer budget


def test_coverage_counts_returned_eligible_rejected_and_missing_slots() -> None:
    request = _request(["lighting", "environment"])
    answer = suggestion(
        ("lighting", ("neon glow", "golden hour"))
    )  # one duplicate; environment omitted
    rows = judge_variety(answer, FIVE, is_visible=lambda _t: True)
    cov = variety_coverage(request, rows)
    light, env = cov.slots
    assert (light.requested, light.returned, light.eligible, light.rejected) == (3, 2, 1, 1)
    assert (env.requested, env.returned, env.eligible) == (3, 0, 0)
    assert (cov.requested, cov.returned, cov.eligible, cov.rejected, cov.added) == (6, 2, 1, 1, 0)
    assert cov.partial and cov.missing == 4
    assert "Partial coverage: 2 of 6" in coverage_status(cov)
    assert variety_coverage(request, rows, added=frozenset({0})).added == 1


def test_a_full_count_is_not_reported_as_verified_relevance() -> None:
    request = _request(["lighting"], per_slot=2)
    answer = suggestion(("lighting", ("neon glow", "cool dusk")))
    rows = judge_variety(answer, FIVE, is_visible=lambda _t: True)
    review = variety_review(rows, answer, is_visible=lambda _t: True, request=request)
    assert review.coverage is not None and not review.coverage.partial
    assert "not verified" in review.status
    text = variety_text(review)
    assert UNVERIFIED_LABEL in text and "PARTIAL COVERAGE" not in text
    assert "lighting  2 requested / 2 returned / 2 eligible" in text
    assert review.actions  # still manually acceptable


def test_a_partial_review_stays_actionable_and_names_the_shortfall() -> None:
    request = _request(["lighting", "environment"])
    answer = suggestion(("lighting", ("neon glow",)))
    rows = judge_variety(answer, FIVE, is_visible=lambda _t: True)
    review = variety_review(rows, answer, is_visible=lambda _t: True, request=request)
    assert review.actions and "Partial coverage: 1 of 6" in review.status
    text = variety_text(review)
    assert "PARTIAL COVERAGE" in text
    assert "environment  3 requested / 0 returned / 0 eligible" in text
