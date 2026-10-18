"""Filter-bar text to ``HistoryQuery``, and the one-line page summary."""

from __future__ import annotations

from datetime import datetime

import pytest

from src.gui_v2.history_browser_model import HistoryFilterError, build_history_query, describe_page
from src.queue.history_query import HistoryCursor, HistoryPage
from src.queue.job_model import JobStatus


def test_blank_filters_find_everything() -> None:
    query = build_history_query()

    assert query.statuses == frozenset()
    assert query.created_from is None
    assert query.created_before is None
    assert query.pack_id is None
    assert query.terms == ()


def test_status_pack_and_text_are_carried_over() -> None:
    query = build_history_query(text="  Red Dragon ", status_label="Failed", pack=" pack-a ")

    assert query.statuses == frozenset({JobStatus.FAILED})
    assert query.pack_id == "pack-a"
    assert query.terms == ("red", "dragon")


def test_the_to_date_includes_that_whole_day() -> None:
    query = build_history_query(date_from="2026-10-02", date_to="2026-10-04")

    assert query.created_from == datetime(2026, 10, 2)
    assert query.created_before == datetime(2026, 10, 5)


@pytest.mark.parametrize(
    ("kwargs", "message"),
    [
        ({"date_from": "10/02/2026"}, "From must be a date"),
        ({"date_to": "yesterday"}, "To must be a date"),
        ({"date_from": "2026-10-05", "date_to": "2026-10-01"}, "From must not be after To"),
        ({"status_label": "Weird"}, "Unknown status"),
    ],
)
def test_bad_filters_raise_a_message_the_user_can_act_on(
    kwargs: dict[str, str], message: str
) -> None:
    with pytest.raises(HistoryFilterError, match=message):
        build_history_query(**kwargs)


def test_cursor_and_limit_pass_through() -> None:
    cursor = HistoryCursor(created_at="2026-10-01T10:00:00", rowid=7)

    query = build_history_query(cursor=cursor, limit=25)

    assert query.cursor == cursor
    assert query.limit == 25


def test_describe_page_states() -> None:
    cursor = HistoryCursor(created_at="x", rowid=1)

    assert describe_page(1, HistoryPage((), None, True, 1)) == "1 job shown. End of history."
    assert "load more" in describe_page(50, HistoryPage((object(),), cursor, False, 50))  # type: ignore[arg-type]
    assert "none matched" in describe_page(0, HistoryPage((), cursor, False, 2000))
