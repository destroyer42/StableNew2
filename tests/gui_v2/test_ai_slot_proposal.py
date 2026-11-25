"""AI-213 new-slot proposals: insertion points, the deterministic judge and the review model. Pure; no Tk."""

from __future__ import annotations

import ast
import dataclasses
from pathlib import Path
from types import SimpleNamespace

import pytest

from src.ai_assist.contracts import (
    MAX_PROPOSAL_POINTS,
    SUGGESTION_SCHEMA_ID,
    AssistSuggestion,
    SlotProposal,
    SuggestionKind,
)
from src.ai_assist.preview import PREVIEW_LABEL
from src.gui_v2 import ai_slot_proposal
from src.gui_v2.ai_slot_proposal import (
    HERE,
    PROPOSAL_NOTICE,
    PROPOSAL_REVERT_TEXT,
    PROPOSAL_REVIEW_ACTIONS,
    ProposalContext,
    build_context,
    build_proposal_request,
    compute_insertion_points,
    inside_protected_token,
    judge_proposals,
    marker_insertion,
    matrix_growth,
    place_marker,
    proposal_review,
    proposal_text,
    unavailable_proposal_review,
)
from src.gui_v2.ai_slot_variety import HIDDEN_TEXT, matrix_state
from src.prompting.prompt_compatibility import NON_PROSE_PATTERN

SENTENCE = "a knight in a forest, wearing armor, at dusk"
VALUES = ("golden hour", "neon glow", "soft window light")


def slot(name, *values):
    return SimpleNamespace(name=name, values=list(values))


def visible(_text: str) -> bool:
    return True


def setup(sentence: str = SENTENCE, slots=None, mapping=None):
    slots = slots if slots is not None else [slot("location", "forest", "harbor")]
    state = matrix_state(slots)
    request, points = build_proposal_request(
        "p1", "better lighting", sentence, state, content_class="standard"
    )
    context = build_context(1, 2, 0, sentence, slots, points, "nsfw")
    config = (
        mapping
        if mapping is not None
        else {
            "enabled": False,
            "limit": 8,
            "slots": [{"name": s.name, "values": list(s.values)} for s in slots],
        }
    )
    return request, context, config


def suggestion(*entries: tuple[str, tuple[str, ...], int]) -> AssistSuggestion:
    return AssistSuggestion(
        SUGGESTION_SCHEMA_ID,
        SuggestionKind.SLOT_PROPOSAL,
        "p1",
        slot_proposals=tuple(
            SlotProposal(name, values, point, f"why {name}") for name, values, point in entries
        ),
    )


def reasons(*entries, sentence=SENTENCE, slots=None, mapping=None, is_visible=visible):
    request, context, config = setup(sentence, slots, mapping)
    rows = judge_proposals(
        suggestion(*entries), request, context, matrix_mapping=config, is_visible=is_visible
    )
    return [row.reason for row in rows]


# -- insertion points -----------------------------------------------------------------------------------------------------


def test_points_sit_before_each_clause_delimiter_and_at_the_end() -> None:
    points = compute_insertion_points(SENTENCE)
    assert [p.offset for p in points] == [
        SENTENCE.index(","),
        SENTENCE.rindex(","),
        len(SENTENCE),
    ]
    assert all(HERE in p.snippet and "\n" not in p.snippet for p in points)


def test_a_final_period_is_a_delimiter_not_an_extra_end_point() -> None:
    points = compute_insertion_points("a knight, wearing armor.")
    assert [p.offset for p in points] == [8, len("a knight, wearing armor")]


def test_no_point_falls_inside_a_protected_token() -> None:
    text = (
        "a knight <lora:style,v2:0.8>, in [[location,x]], under __light,set__, <embedding:bad,hand>"
    )
    points = compute_insertion_points(text)
    assert points
    for point in points:
        assert not inside_protected_token(text, point.offset), point
    protected = [m.span() for pattern in (NON_PROSE_PATTERN,) for m in pattern.finditer(text)]
    for point in points:
        assert not any(start < point.offset < end for start, end in protected)
    # The comma inside <lora:style,v2:0.8> is not offered.
    assert text.index(",v2") not in [p.offset for p in points]


def test_a_wildcard_is_protected_too() -> None:
    text = "under __light,set__ glow"
    assert inside_protected_token(text, text.index(",set"))
    assert text.index(",set") not in [p.offset for p in compute_insertion_points(text)]


def test_points_are_capped_and_sampled_deterministically() -> None:
    text = ", ".join(f"clause {i}" for i in range(40))
    points = compute_insertion_points(text)
    assert len(points) <= MAX_PROPOSAL_POINTS
    assert points == compute_insertion_points(text)
    assert [p.offset for p in points] == sorted({p.offset for p in points})


def test_a_sentence_without_delimiters_still_has_its_end() -> None:
    assert [p.offset for p in compute_insertion_points("a knight")] == [8]
    assert compute_insertion_points("   ") == ()


@pytest.mark.parametrize("sentence", [SENTENCE, "a knight", "(a knight), armor.", "a,b;c"])
def test_the_inserted_text_is_the_marker_and_removing_it_restores_the_sentence(sentence) -> None:
    for point in compute_insertion_points(sentence):
        inserted = marker_insertion(sentence, point.offset, "lighting")
        placed = place_marker(sentence, point.offset, "lighting")
        assert inserted.strip() == "[[lighting]]"
        assert placed.count("[[lighting]]") == 1
        assert placed.replace(inserted, "", 1) == sentence
        assert len(inserted) - len("[[lighting]]") <= 2
        assert placed[: point.offset] + placed[point.offset + len(inserted) :] == sentence


def test_the_marker_is_separated_from_a_neighbouring_word_only_where_needed() -> None:
    assert marker_insertion("a knight, armor", 8, "x") == " [[x]]"
    assert marker_insertion("a knight ", 9, "x") == "[[x]]"
    assert marker_insertion("a (", 3, "x") == "[[x]]"


# -- the request -----------------------------------------------------------------------------------------------------------


def test_the_request_holds_the_sentence_names_and_points_only() -> None:
    request, context, _config = setup()
    assert request.kind is SuggestionKind.SLOT_PROPOSAL
    assert request.positive_text == SENTENCE and request.existing_slot_names == ("location",)
    assert len(request.insertion_points) == len(context.offsets)
    assert not (request.allowed_targets or request.allowed_workflows or request.matrix_slots)


def test_an_empty_or_oversized_sentence_is_refused_before_a_request() -> None:
    with pytest.raises(ValueError):
        build_proposal_request("p", "g", "  ", (), content_class="standard")
    with pytest.raises(ValueError):
        build_proposal_request("p", "g", "x" * 2001, (), content_class="standard")


# -- the judge -------------------------------------------------------------------------------------------------------------


def test_a_clean_proposal_is_offered_with_its_matrix_growth() -> None:
    request, context, config = setup()
    (row,) = judge_proposals(
        suggestion(("lighting", VALUES, 1)),
        request,
        context,
        matrix_mapping=config,
        is_visible=visible,
    )
    assert row.offered and row.growth == (2, 6, 8)


@pytest.mark.parametrize(
    ("name", "reason"),
    [
        ("", "slot_name_empty"),
        ("  ", "slot_name_empty"),
        (" lighting", "slot_name_whitespace"),
        ("x" * 65, "slot_name_too_long"),
        ("a,b", "slot_name_chars"),
        ("a[b", "slot_name_chars"),
        ("a<b", "slot_name_chars"),
        ("a__b", "slot_name_chars"),
        ("a\nb", "slot_name_chars"),
        ("SLOT: x", "slot_name_chars"),
        ("---", "slot_name_chars"),
        ("Location", "slot_name_exists"),
        ("loca-tion", "slot_name_exists"),
        ("LOCATION ", "slot_name_whitespace"),
    ],
)
def test_each_slot_name_check_rejects_with_its_reason(name, reason) -> None:
    assert reasons((name, VALUES, 0)) == [reason]


def test_a_slot_name_matching_any_existing_slot_is_not_unique_even_if_that_slot_is_not_editable() -> (
    None
):
    slots = [slot("location", "forest, glade")]  # not editable: a value holds a comma
    assert reasons(("lighting", VALUES, 0), ("Location", VALUES, 1), slots=slots) == [
        "",
        "slot_name_exists",
    ]


def test_two_proposals_cannot_share_a_name_and_only_the_first_is_offered() -> None:
    assert reasons(("lighting", VALUES, 0), ("Lighting", VALUES, 1), ("light-ing", VALUES, 2)) == [
        "",
        "slot_name_collision",
        "slot_name_collision",
    ]


@pytest.mark.parametrize(
    "values",
    [
        ("golden hour", "neon glow", ""),
        ("golden hour", "neon glow", " padded"),
        ("golden hour", "neon, glow", "dusk"),
        ("golden hour", "[neon]", "dusk"),
        ("golden hour", "<lora:x>", "dusk"),
        ("golden hour", "__wild__", "dusk"),
        ("golden hour", "neon\nglow", "dusk"),
        ("golden hour", "x" * 81, "dusk"),
        ("golden hour", "Golden  Hour", "dusk"),
        ("golden hour", "GOAL: x", "dusk"),
    ],
)
def test_values_must_pass_the_variety_value_rules(values) -> None:
    assert reasons(("lighting", values, 0)) == ["values_invalid"]


def test_the_rejection_names_the_first_failing_value_rule() -> None:
    request, context, config = setup()
    (row,) = judge_proposals(
        suggestion(("lighting", ("golden hour", "neon, glow", "dusk"), 0)),
        request,
        context,
        matrix_mapping=config,
        is_visible=visible,
    )
    assert "comma" in ai_slot_proposal.detail_text(row).lower()


def test_an_index_outside_the_list_is_rejected() -> None:
    assert reasons(("lighting", VALUES, 99)) == ["point_invalid"]
    assert reasons(("lighting", VALUES, -1)) == ["point_invalid"]


def test_a_point_that_became_protected_is_rejected() -> None:
    request, context, config = setup()
    moved = dataclasses.replace(context, sentence="<lora:abcdefghijklmnopqrstuvwxyz:0.8>" * 2)
    (row,) = judge_proposals(
        suggestion(("lighting", VALUES, 0)),
        request,
        moved,
        matrix_mapping=config,
        is_visible=visible,
    )
    assert row.reason == "point_protected"


def test_a_hidden_name_value_or_rationale_is_rejected_and_never_shown() -> None:
    request, context, config = setup()
    sug = suggestion(("secret glow", VALUES, 0), ("lighting", ("dusk", "dawn", "secret noon"), 1))
    rows = judge_proposals(
        sug, request, context, matrix_mapping=config, is_visible=lambda t: "secret" not in t
    )
    assert [r.reason for r in rows] == ["hidden", "hidden"]
    text = proposal_text(proposal_review(rows))
    assert "secret" not in text and HIDDEN_TEXT in text


# -- matrix growth and the limit ---------------------------------------------------------------------------------------------


def test_growth_counts_the_combinations_before_and_after() -> None:
    config = {"enabled": False, "limit": 50, "slots": [{"name": "a", "values": ["x", "y"]}]}
    assert matrix_growth(config, "b", ["1", "2", "3"]) == (2, 6, 50)
    assert matrix_growth({"slots": []}, "b", ["1", "2", "3"])[:2] == (1, 3)


def test_a_proposal_past_the_matrix_limit_is_offered_with_both_counts() -> None:
    # AI-230a: the limit only caps how many combinations compile per prompt row, so it is information, not a verdict.
    config = {
        "enabled": True,
        "limit": 4,
        "slots": [{"name": "location", "values": ["forest", "harbor"]}],
    }
    request, context, _ = setup(mapping=config)
    (row,) = judge_proposals(
        suggestion(("lighting", VALUES, 0)),
        request,
        context,
        matrix_mapping=config,
        is_visible=visible,
    )
    assert row.offered and row.growth == (2, 6, 4)
    shown = proposal_text(proposal_review((row,)))
    assert "go from 2 to 6; compiled per prompt row: 4 (limit 4)" in shown
    assert "[can add]" in shown


def test_a_matrix_already_past_its_limit_still_takes_a_new_slot() -> None:
    config = {
        "enabled": True,
        "limit": 8,
        "slots": [
            {"name": "a", "values": [str(i) for i in range(5)]},
            {"name": "b", "values": [str(i) for i in range(5)]},
        ],
    }
    request, context, _ = setup(mapping=config)
    (row,) = judge_proposals(
        suggestion(("lighting", VALUES, 0)),
        request,
        context,
        matrix_mapping=config,
        is_visible=visible,
    )
    assert row.offered and row.growth == (25, 75, 8)
    assert "compiled per prompt row: 8" in proposal_text(proposal_review((row,)))


def test_a_proposal_exactly_at_the_limit_is_offered() -> None:
    config = {"limit": 6, "slots": [{"name": "location", "values": ["forest", "harbor"]}]}
    request, context, _ = setup(mapping=config)
    (row,) = judge_proposals(
        suggestion(("lighting", VALUES, 0)),
        request,
        context,
        matrix_mapping=config,
        is_visible=visible,
    )
    assert row.offered


# -- the context after an addition ---------------------------------------------------------------------------------------------


def test_after_an_addition_the_marker_is_in_the_sentence_and_later_points_move() -> None:
    request, context, _config = setup()
    first = context.offsets[0]
    after = context.with_proposal_added(0, "lighting", VALUES)
    inserted = marker_insertion(context.sentence, first, "lighting")
    assert after.sentence == place_marker(context.sentence, first, "lighting")
    assert after.offsets[0] == -1
    assert after.offsets[1] == context.offsets[1] + len(inserted)
    assert [s.name for s in after.slots] == ["location", "lighting"]
    assert after.slots[-1].editable and after.slots[-1].values == VALUES
    assert after.pack_identity == context.pack_identity


def test_a_point_that_already_took_a_marker_cannot_take_another() -> None:
    request, context, config = setup()
    after = context.with_proposal_added(0, "lighting", VALUES)
    (row,) = judge_proposals(
        suggestion(("weather", ("fog", "rain", "snow"), 0)),
        request,
        after,
        matrix_mapping={"limit": 99, "slots": []},
        is_visible=visible,
    )
    assert row.reason == "point_taken"


def test_a_later_proposal_lands_at_the_right_place_after_an_earlier_one() -> None:
    request, context, _config = setup()
    after = context.with_proposal_added(0, "lighting", VALUES)
    second_offset = after.offsets[2]
    final = place_marker(after.sentence, second_offset, "weather")
    assert final.index("[[lighting]]") < final.index("[[weather]]")
    assert final.endswith("[[weather]]")
    assert (
        final.replace("[[weather]]", "")
        .replace(" [[lighting]]", "")
        .replace("[[lighting]]", "")
        .replace("  ", " ")
        .strip()
        != ""
    )


# -- review model --------------------------------------------------------------------------------------------------------------


def test_the_review_offers_only_valid_unadded_proposals_and_shows_every_rejection() -> None:
    request, context, config = setup()
    rows = judge_proposals(
        suggestion(("lighting", VALUES, 0), ("Location", VALUES, 1), ("weather", VALUES, 99)),
        request,
        context,
        matrix_mapping=config,
        is_visible=visible,
    )
    review = proposal_review(rows, trust_label=PREVIEW_LABEL)
    assert [r.index for r in review.offered_rows] == [0]
    assert review.actions == PROPOSAL_REVIEW_ACTIONS == ("add_slot_and_place_marker",)
    text = proposal_text(review)
    assert "[can add]" in text and text.count("[rejected]") == 2
    assert PREVIEW_LABEL in text and PROPOSAL_NOTICE in text and PROPOSAL_REVERT_TEXT in text
    done = proposal_review(rows, added=frozenset({0}))
    assert done.offered_rows == () and done.actions == () and "[added]" in proposal_text(done)


def test_an_unavailable_review_offers_nothing() -> None:
    review = unavailable_proposal_review("not now", trust_label="t")
    assert review.rows == () and review.actions == () and review.offered_rows == ()


def test_the_notice_states_exactly_what_may_change_and_how_to_revert() -> None:
    assert "new slot with its values is added to the Matrix tab" in PROPOSAL_NOTICE
    assert "[[slot_name]] is inserted" in PROPOSAL_NOTICE
    assert "nothing else in the sentence is reworded" in PROPOSAL_NOTICE
    assert "Nothing is saved, previewed, compiled, queued or generated" in PROPOSAL_NOTICE
    assert "delete the slot's row" in PROPOSAL_REVERT_TEXT and "marker" in PROPOSAL_REVERT_TEXT


def test_the_review_model_has_no_intent_queue_or_save_field_or_action() -> None:
    fields = {f.name for f in dataclasses.fields(ai_slot_proposal.ProposalReview)}
    assert fields == {"status", "trust_label", "rows", "added", "notice", "revert", "actions"}
    assert not any(
        word in name for name in fields for word in ("queue", "save", "intent", "compile", "job")
    )


def test_the_proposal_module_imports_nothing_that_could_execute_or_queue() -> None:
    tree = ast.parse(Path(ai_slot_proposal.__file__).read_text(encoding="utf-8"))
    modules = {
        node.module for node in ast.walk(tree) if isinstance(node, ast.ImportFrom) and node.module
    } | {
        alias.name
        for node in ast.walk(tree)
        if isinstance(node, ast.Import)
        for alias in node.names
    }
    forbidden = (
        "tkinter",
        "subprocess",
        "src.queue",
        "src.controller",
        "src.gui.",
        "src.pipeline.job",
    )
    assert not [m for m in modules if m.startswith(forbidden)], sorted(modules)
    assert (
        "src.pipeline.matrix_expansion_plan" in modules
    )  # the planner only: a pure counting function


def test_context_is_comparable_and_holds_no_live_references() -> None:
    _request, context, _config = setup()
    twin = build_context(1, 2, 0, SENTENCE, [slot("location", "forest", "harbor")], [], "nsfw")
    assert isinstance(context, ProposalContext)
    assert dataclasses.replace(twin, offsets=context.offsets) == context
