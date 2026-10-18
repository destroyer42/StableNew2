"""Toolkit-neutral model for the history browser: turn the filter-bar text into a ``HistoryQuery`` and describe a page."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta

from src.queue.history_query import (
    DEFAULT_PAGE_SIZE,
    HistoryCursor,
    HistoryPage,
    HistoryQuery,
)
from src.queue.job_model import JobStatus

ANY_STATUS = "Any"
STATUS_CHOICES: dict[str, frozenset[JobStatus]] = {
    ANY_STATUS: frozenset(),
    "Completed": frozenset({JobStatus.COMPLETED}),
    "Failed": frozenset({JobStatus.FAILED}),
    "Cancelled": frozenset({JobStatus.CANCELLED}),
    "Queued": frozenset({JobStatus.QUEUED}),
    "Running": frozenset({JobStatus.RUNNING}),
}


class HistoryFilterError(ValueError):
    """A filter-bar value the user can correct; the message is shown as is."""


def _parse_day(label: str, value: str) -> datetime | None:
    text = value.strip()
    if not text:
        return None
    try:
        return datetime.strptime(text, "%Y-%m-%d")
    except ValueError as exc:
        raise HistoryFilterError(f"{label} must be a date like 2026-10-18.") from exc


def build_history_query(
    *,
    text: str = "",
    status_label: str = ANY_STATUS,
    pack: str = "",
    date_from: str = "",
    date_to: str = "",
    cursor: HistoryCursor | None = None,
    limit: int = DEFAULT_PAGE_SIZE,
) -> HistoryQuery:
    """``date_to`` is a whole day: the query ends before the next midnight, so the day itself is included."""

    statuses = STATUS_CHOICES.get(status_label)
    if statuses is None:
        raise HistoryFilterError(f"Unknown status {status_label!r}.")
    created_from = _parse_day("From", date_from)
    last_day = _parse_day("To", date_to)
    created_before = last_day + timedelta(days=1) if last_day is not None else None
    if created_from is not None and created_before is not None and created_from >= created_before:
        raise HistoryFilterError("From must not be after To.")
    return HistoryQuery(
        statuses=statuses,
        created_from=created_from,
        created_before=created_before,
        pack_id=pack.strip() or None,
        text=text,
        limit=limit,
        cursor=cursor,
    )


@dataclass(frozen=True)
class HistoryFilters:
    """The filter bar as typed; ``to_query`` validates it and may raise ``HistoryFilterError``."""

    text: str = ""
    status_label: str = ANY_STATUS
    pack: str = ""
    date_from: str = ""
    date_to: str = ""

    def to_query(
        self, *, cursor: HistoryCursor | None = None, limit: int = DEFAULT_PAGE_SIZE
    ) -> HistoryQuery:
        return build_history_query(
            text=self.text,
            status_label=self.status_label,
            pack=self.pack,
            date_from=self.date_from,
            date_to=self.date_to,
            cursor=cursor,
            limit=limit,
        )


def describe_page(shown: int, page: HistoryPage) -> str:
    """One line under the results: how many are listed and whether older jobs remain unsearched."""

    noun = "job" if shown == 1 else "jobs"
    if page.exhausted:
        return f"{shown} {noun} shown. End of history."
    if len(page.entries) == 0:
        return f"{shown} {noun} shown. Searched {page.examined:,} more, none matched; older jobs remain."
    return f"{shown} {noun} shown. Older jobs remain; load more to continue."


__all__ = [
    "ANY_STATUS",
    "HistoryFilterError",
    "HistoryFilters",
    "STATUS_CHOICES",
    "build_history_query",
    "describe_page",
]
