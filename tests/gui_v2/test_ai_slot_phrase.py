"""AI-230g phrase to slot: the selected span, the deterministic judge and the review text, with no Tk, model or I/O."""

from __future__ import annotations

import ast
import dataclasses
from pathlib import Path
from types import SimpleNamespace

import pytest

from src.ai_assist.contracts import (
    MAX_PHRASE_CHARS,
    SUGGESTION_SCHEMA_ID,
    AssistSuggestion,
    PhraseSlot,
    SuggestionKind,
)
from src.gui_v2 import ai_slot_phrase
from src.gui_v2.ai_changes import KIND_PHRASE_SLOT, phrase_changes
from src.gui_v2.ai_slot_phrase import (
    NO_PHRASE_TEXT,
    PhraseSpan,
    build_phrase_request,
    detail_text,
    judge_phrase_slots,
    phrase_blocker,
    phrase_review,
    phrase_text,
    replace_span,
    restore_span,
    span_problem,
    trim_selection,
    unavailable_phrase_review,
    with_phrase_applied,
)
from src.gui_v2.ai_slot_proposal import build_context
from src.gui_v2.ai_slot_variety import matrix_state

SENTENCE = "a knight in a forest, wearing armor, at dusk"
PHRASE = "at dusk"
START = SENTENCE.index(PHRASE)
SPAN = PhraseSpan(START, START + len(PHRASE), PHRASE)
SLOTS = [SimpleNamespace(name="location", values=["forest", "harbor"])]
STATE = matrix_state(SLOTS)
MAPPING = {"enabled": True, "slots": [{"name": "location", "values": ["forest", "harbor"]}]}


def visible(_text: str) -> bool:
    return True


def suggestion(*entries: tuple[str, tuple[str, ...]]) -> AssistSuggestion:
    return AssistSuggestion(
        SUGGESTION_SCHEMA_ID,
        SuggestionKind.PHRASE_SLOT,
        "p1",
        phrase_slots=tuple(PhraseSlot(name, values, f"why {name}") for name, values in entries),
    )


def judged(*entries, span=SPAN, is_visible=visible, phrase_taken=False, sentence=SENTENCE):
    context = build_context(1, 2, 0, sentence, SLOTS, (), "nsfw")
    return judge_phrase_slots(
        suggestion(*entries),
        context,
        span,
        matrix_mapping=MAPPING,
        is_visible=is_visible,
        phrase_taken=phrase_taken,
    )


# -- the selection ---------------------------------------------------------------------------------------------------------


def test_trim_selection_drops_only_surrounding_whitespace() -> None:
    sentence = "a  knight , at dusk "
    start = sentence.index("at dusk")
    assert trim_selection(sentence, start - 1, len(sentence)) == PhraseSpan(
        start, start + len("at dusk"), "at dusk"
    )
    assert trim_selection(sentence, 0, 1) == PhraseSpan(0, 1, "a")
    assert trim_selection(sentence, 1, 3) is None  # only spaces
    assert trim_selection(sentence, 5, 5) is None  # empty
    assert trim_selection(sentence, 10, 99) is None  # past the end
    assert trim_selection(sentence, -1, 3) is None
    span = trim_selection(sentence, 2, 9)
    assert span is not None and span.text == sentence[span.start : span.end] == "knight"


def test_a_clean_span_has_no_problem() -> None:
    assert span_problem(SENTENCE, SPAN) == ""
    assert phrase_blocker(SENTENCE, STATE, SPAN) == ""


@pytest.mark.parametrize(
    ("sentence", "phrase", "needle"),
    [
        ("a knight in a forest, at dusk", "forest, at", "comma"),
        ("a knight [[hero]] in a forest", "[[hero]] in", "protected token"),
        ("a knight <lora:x:0.8> in a forest", "knight <lora:x:0.8>", "protected token"),
        ("a knight __style__ in a forest", "__style__", "protected token"),
        ("a knight in a forest", "knig", "inside a word"),
        ("a knight in a forest", "night", "inside a word"),
        ("a knight in a forest", "knight in a fore", "inside a word"),
        ("a knight in a forest", "ight in a forest", "inside a word"),
    ],
)
def test_a_span_that_cannot_be_a_slot_is_refused_in_words(sentence, phrase, needle) -> None:
    start = sentence.index(phrase)
    span = PhraseSpan(start, start + len(phrase), phrase)
    assert needle in span_problem(sentence, span)
    assert phrase_blocker(sentence, matrix_state([]), span) == span_problem(sentence, span)


def test_a_span_that_no_longer_matches_the_sentence_is_refused() -> None:
    assert "no longer matches" in span_problem(SENTENCE, PhraseSpan(START + 1, START + 8, PHRASE))
    assert "no longer matches" in span_problem(SENTENCE, PhraseSpan(0, 999, PHRASE))
    assert "no longer matches" in span_problem("different", SPAN)


def test_length_line_and_marker_limits() -> None:
    long_phrase = "x" * (MAX_PHRASE_CHARS + 1)
    sentence = f"a {long_phrase} b"
    start = sentence.index(long_phrase)
    assert "longer than" in span_problem(
        sentence, PhraseSpan(start, start + len(long_phrase), long_phrase)
    )
    two_lines = "a\nb"
    assert "one line" in span_problem(two_lines, PhraseSpan(0, 3, two_lines))
    # a reserved marker anywhere in the sentence cannot be framed, so it is refused before any request exists
    marked = "SLOT: forest, at dusk"
    start = marked.index(PHRASE)
    assert "reserved marker" in span_problem(marked, PhraseSpan(start, start + len(PHRASE), PHRASE))


def test_the_blocker_reports_a_missing_selection_and_the_usual_limits() -> None:
    assert phrase_blocker(SENTENCE, STATE, None) == NO_PHRASE_TEXT
    assert "authored positive prompt" in phrase_blocker("  ", STATE, SPAN)
    assert "longer than" in phrase_blocker("x" * 2001, STATE, SPAN)
    many = matrix_state([SimpleNamespace(name=f"s{i}", values=["a"]) for i in range(65)])
    assert "too many matrix slots" in phrase_blocker(SENTENCE, many, SPAN)


def test_the_request_is_the_sentence_the_phrase_and_the_slot_names() -> None:
    request = build_phrase_request(
        "r1", "  different times of day ", SENTENCE, SPAN, STATE, content_class="standard"
    )
    assert request.kind is SuggestionKind.PHRASE_SLOT
    assert (request.positive_text, request.phrase_text) == (SENTENCE, PHRASE)
    assert request.goal_text == "different times of day"  # stripped
    assert request.existing_slot_names == ("location",)
    assert (
        build_phrase_request("r2", "", SENTENCE, SPAN, STATE, content_class="sensitive").goal_text
        == ""
    )
    with pytest.raises(ValueError):
        build_phrase_request(
            "r3", "", SENTENCE, PhraseSpan(0, 5, "a kni"), STATE, content_class="standard"
        )


# -- the span edit ---------------------------------------------------------------------------------------------------------


def test_replace_and_restore_are_byte_exact_inverses() -> None:
    after = replace_span(SENTENCE, SPAN, "time_of_day")
    assert after == "a knight in a forest, wearing armor, [[time_of_day]]"
    assert (
        after[:START] == SENTENCE[:START]
        and after[START + len("[[time_of_day]]") :] == SENTENCE[SPAN.end :]
    )
    assert restore_span(after, SPAN, "time_of_day") == SENTENCE


def test_only_the_selected_occurrence_changes_when_the_phrase_repeats() -> None:
    sentence = "at dusk a knight, at dusk"
    first, second = PhraseSpan(0, 7, "at dusk"), PhraseSpan(18, 25, "at dusk")
    assert replace_span(sentence, first, "t") == "[[t]] a knight, at dusk"
    assert replace_span(sentence, second, "t") == "at dusk a knight, [[t]]"
    assert restore_span(replace_span(sentence, second, "t"), second, "t") == sentence


def test_the_expected_state_after_applying_is_the_sentence_and_one_more_slot() -> None:
    context = build_context(1, 2, 0, SENTENCE, SLOTS, (), "nsfw")
    expected = with_phrase_applied(context, SPAN, "time_of_day", (PHRASE, "at dawn", "at midnight"))
    assert expected.sentence == replace_span(SENTENCE, SPAN, "time_of_day")
    assert [(s.name, s.values) for s in expected.slots] == [
        ("location", ("forest", "harbor")),
        ("time_of_day", (PHRASE, "at dawn", "at midnight")),
    ]
    assert (expected.pack_identity, expected.matrix_identity, expected.slot_index) == (1, 2, 0)
    assert context.sentence == SENTENCE and len(context.slots) == 1  # the original is untouched


# -- the judge -------------------------------------------------------------------------------------------------------------


def test_a_clean_proposal_is_offered_with_the_phrase_as_its_first_value() -> None:
    (row,) = judged(("time_of_day", ("at dawn", "at midnight")))
    assert row.offered and row.reason == ""
    assert row.values == (PHRASE, "at dawn", "at midnight")
    assert row.growth is not None and row.growth[1] > row.growth[0]


@pytest.mark.parametrize(
    ("entry", "reason"),
    [
        (("location", ("at dawn", "at midnight")), "slot_name_exists"),
        (("Location ", ("at dawn", "at midnight")), "slot_name_whitespace"),
        (("", ("at dawn", "at midnight")), "slot_name_empty"),
        (("a,b", ("at dawn", "at midnight")), "slot_name_chars"),
        (("time", ("at dusk", "at dawn")), "value_repeats_phrase"),
        (("time", ("AT  DUSK", "at dawn")), "value_repeats_phrase"),
        (("time", ("at dusks", "at dawn")), "value_repeats_phrase"),
        (("time", ("at dawn", "At Dawn")), "values_invalid"),
        (("time", ("at dawn", "a, b")), "values_invalid"),
        (("time", ("at dawn", "[[x]]")), "values_invalid"),
        (("time", ("at dawn", "")), "values_invalid"),
    ],
)
def test_each_check_rejects_with_its_reason(entry, reason) -> None:
    (row,) = judged(entry)
    assert (row.offered, row.reason) == (False, reason)
    assert detail_text(row)  # every reason has words


def test_a_second_proposal_with_the_same_name_is_rejected_the_second_time() -> None:
    first, second = judged(("time", ("at dawn", "at noon")), ("Time", ("at night", "at sunset")))
    assert first.reason == "" and second.reason == "slot_name_collision"


def test_once_a_proposal_replaced_the_span_no_other_one_can_be_applied() -> None:
    rows = judged(("time", ("at dawn", "at noon")), ("mood", ("calm", "tense")), phrase_taken=True)
    assert [r.reason for r in rows] == ["phrase_taken", "phrase_taken"]
    assert "already replaced" in detail_text(rows[0])


def test_a_hidden_name_value_or_rationale_is_rejected_and_never_shown() -> None:
    rows = judged(("time", ("at dawn", "secret glow")), is_visible=lambda t: "secret" not in t)
    assert [r.reason for r in rows] == ["hidden"]
    review = phrase_review(rows)
    assert "secret" not in phrase_text(review)
    cards = phrase_changes(
        review, build_context(1, 2, 0, SENTENCE, SLOTS, (), "nsfw"), SPAN, is_visible=visible
    )
    assert all("secret" not in repr(c) and "secret" not in c.title for c in cards)


def test_the_review_counts_and_the_text_name_every_rejection() -> None:
    rows = judged(("time", ("at dawn", "at noon")), ("location", ("a", "b")))
    review = phrase_review(rows, trust_label="Remote Preview")
    assert review.status == "1 proposal(s) can be applied, 1 rejected, 0 applied."
    assert review.actions and [r.index for r in review.offered_rows] == [0]
    text = phrase_text(review)
    assert "Values (your phrase first): at dusk, at dawn, at noon" in text
    assert "[can apply]" in text and "[rejected]" in text and "Remote Preview" in text
    applied = phrase_review(rows, added=frozenset({0}))
    assert "[applied]" in phrase_text(applied) and applied.offered_rows == ()
    assert (
        unavailable_phrase_review("nope").rows == ()
        and unavailable_phrase_review("nope").actions == ()
    )


def test_cards_show_the_sentence_before_and_after_and_the_first_compiled_example() -> None:
    rows = judged(("time_of_day", ("at dawn", "at midnight")), ("location", ("a", "b")))
    review = phrase_review(rows)
    context = build_context(1, 2, 0, SENTENCE, SLOTS, (), "nsfw")
    good, bad = phrase_changes(review, context, SPAN, is_visible=visible)
    assert good.kind == KIND_PHRASE_SLOT and good.offered and good.key == "phrase:0"
    assert PHRASE in good.before and "[[time_of_day]]" in good.after and PHRASE not in good.after
    # the slot's first value is the operator's phrase, so the first compiled sentence reads as the original did
    assert good.examples and "at dusk" in good.examples[0]
    assert "limit" in good.effect
    assert bad.rejected and bad.reason == "slot_name_exists" and not bad.before
    applied = phrase_changes(
        phrase_review(rows, added=frozenset({0})), context, SPAN, is_visible=visible
    )
    assert applied[0].applied and not applied[0].offered


# -- structure -------------------------------------------------------------------------------------------------------------


def test_the_phrase_module_imports_nothing_that_could_edit_execute_or_queue() -> None:
    tree = ast.parse(Path(ai_slot_phrase.__file__).read_text(encoding="utf-8"))
    imported = {
        node.module or "" for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)
    } | {
        alias.name
        for node in ast.walk(tree)
        if isinstance(node, ast.Import)
        for alias in node.names
    }
    forbidden = (
        "tkinter",
        "subprocess",
        "socket",
        "urllib",
        "requests",
        "queue",
        "controller",
        "pipeline.job",
        "os",
    )
    assert not [
        name
        for name in imported
        if name.split(".")[0] in forbidden
        or any(f in name for f in ("job_service", "runner", "history"))
    ]


def test_the_review_model_has_no_intent_queue_or_save_field() -> None:
    names = {f.name for f in dataclasses.fields(ai_slot_phrase.PhraseReview)} | {
        f.name for f in dataclasses.fields(ai_slot_phrase.PhraseRow)
    }
    assert not {n for n in names if any(w in n for w in ("intent", "queue", "save", "job", "path"))}
