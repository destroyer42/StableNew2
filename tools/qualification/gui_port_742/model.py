"""Toolkit-neutral workspace state and text for the GUI-PORT-742 qualification surfaces.

Both toolkit views render this state; it owns no persistence, queue, runner or history authority. Filter parsing is the
real ``history_browser_model``; navigation is the real ``task_navigation_contract``.
"""

from __future__ import annotations

from dataclasses import dataclass

from src.gui.ui_tokens import NOTICE_KINDS, TOKENS
from src.gui.view_contracts.task_navigation_contract import (
    DEFAULT_TAB_ID,
    TASK_GROUPS,
    all_tab_ids,
    default_tab_for_group,
    get_destination,
    group_for_tab,
)
from src.gui_v2.history_browser_model import (
    ANY_STATUS,
    HistoryFilterError,
    HistoryFilters,
    describe_page,
)
from src.pipeline.job_models_v2 import UnifiedJobSummary
from src.queue.history_query import MAX_PAGE_SIZE, HistoryPage
from src.queue.job_history_store import JobHistoryEntry
from tools.qualification.gui_port_742.fixture import filter_entries

SELECTED_MARKER = "▶ "  # a shape, so selection never relies on color alone
HISTORY_COLUMNS = ("Job", "Status", "Created", "Summary")
QUEUE_COLUMNS = ("Job", "Status", "Pack", "Summary")
READY_NOTICE = ("neutral", "Ready. Read-only qualification data.")


def status_label(value: object) -> str:
    return str(getattr(value, "value", value)).capitalize()


def history_cells(entry: JobHistoryEntry, selected: bool) -> tuple[str, str, str, str]:
    return (
        (SELECTED_MARKER if selected else "") + entry.job_id,
        status_label(entry.status),
        entry.created_at.strftime("%Y-%m-%d %H:%M"),
        entry.payload_summary,
    )


def queue_cells(job: UnifiedJobSummary) -> tuple[str, str, str, str]:
    return (
        job.job_id,
        status_label(job.status),
        job.prompt_pack_id or "manual",
        f"{job.positive_prompt_preview} | {job.base_model}",
    )


def _stamp(value: object) -> str:
    return value.strftime("%Y-%m-%d %H:%M:%S") if hasattr(value, "strftime") else "not recorded"


def details_heading(entry: JobHistoryEntry) -> str:
    return f"Selected {entry.job_id} ({status_label(entry.status)})"


def details_text(entry: JobHistoryEntry) -> str:
    lines = [
        details_heading(entry),
        f"Created: {_stamp(entry.created_at)}",
        f"Started: {_stamp(entry.started_at)}",
        f"Completed: {_stamp(entry.completed_at)}",
        "Duration: "
        + (
            f"{entry.duration_ms / 1000:.1f} s" if entry.duration_ms is not None else "not recorded"
        ),
        f"Pack: {entry.prompt_pack_id or 'manual'}",
        f"Run mode: {entry.run_mode}",
        f"Summary: {entry.payload_summary}",
    ]
    if entry.error_message:
        lines.append(f"Error: {entry.error_message}")
    return "\n".join(lines)


NO_SELECTION_TEXT = "No job selected. Select a history row to inspect it."


@dataclass(frozen=True)
class Notice:
    kind: str
    text: str

    def __post_init__(self) -> None:
        if self.kind not in NOTICE_KINDS:
            raise ValueError(f"unknown notice kind {self.kind!r}")

    @property
    def word(self) -> str:
        """The visible role word; the meaning never depends on color alone."""

        return TOKENS.notices.role(self.kind).label

    @property
    def display(self) -> str:
        return f"{self.word}: {self.text}"


def placeholder_title(tab_id: str) -> str:
    destination, group = get_destination(tab_id), group_for_tab(tab_id)
    if destination is None or group is None:
        raise ValueError(f"unknown tab id {tab_id!r}")
    return f"{group.label} / {destination.display_label}"


def placeholder_body(tab_id: str) -> str:
    destination = get_destination(tab_id)
    if destination is None:
        raise ValueError(f"unknown tab id {tab_id!r}")
    if destination.hold:
        return f"HOLD: {destination.hold_reason}"
    return "Qualification placeholder: this workspace is not part of the proof."


def nav_entries() -> tuple[tuple[str, str], ...]:
    """(tab_id, display label) in navigation order, exactly what the production contract defines."""

    return tuple((tab_id, get_destination(tab_id).display_label) for tab_id in all_tab_ids())  # type: ignore[union-attr]


def nav_group_labels() -> tuple[str, ...]:
    return tuple(group.label for group in TASK_GROUPS)


class WorkspaceModel:
    """Navigation, filter, selection, notice and projection state; UI-thread use only."""

    def __init__(self) -> None:
        self.tab_id = DEFAULT_TAB_ID
        self.filters = HistoryFilters()
        self.history: tuple[JobHistoryEntry, ...] = ()
        self.queue: tuple[UnifiedJobSummary, ...] = ()
        self.visible: tuple[JobHistoryEntry, ...] = ()
        self.selected_id: str | None = None
        self.notice = Notice(*READY_NOTICE)
        self.result_line = ""

    # navigation -------------------------------------------------------------------------------------------------
    def navigate(self, tab_id: str) -> bool:
        if get_destination(tab_id) is None:
            return False  # an unknown id leaves the current workspace untouched
        self.tab_id = tab_id
        return True

    def navigate_group(self, group_id: str) -> bool:
        target = default_tab_for_group(group_id)
        return False if target is None else self.navigate(target)

    # projection -------------------------------------------------------------------------------------------------
    def set_projection(
        self, history: tuple[JobHistoryEntry, ...], queue: tuple[UnifiedJobSummary, ...]
    ) -> None:
        self.history, self.queue = tuple(history), tuple(queue)
        self._refilter()
        ids = {entry.job_id for entry in self.visible}
        if self.selected_id is not None and self.selected_id not in ids:
            gone = self.selected_id
            self.selected_id = None
            self.notice = Notice(
                "warning", f"Selected job {gone} is no longer in the history projection."
            )

    def _refilter(self) -> None:
        query = self.filters.to_query(limit=MAX_PAGE_SIZE)
        self.visible = filter_entries(query, self.history)
        page = HistoryPage(
            entries=self.visible, next_cursor=None, exhausted=True, examined=len(self.history)
        )
        self.result_line = describe_page(len(self.visible), page)

    # filters ----------------------------------------------------------------------------------------------------
    def apply_filters(self, filters: HistoryFilters) -> bool:
        try:
            filters.to_query(limit=MAX_PAGE_SIZE)
        except HistoryFilterError as error:
            self.notice = Notice("error", str(error))
            return False
        self.filters = filters
        self._refilter()
        if self.selected_id is not None and self.selected_id not in {
            e.job_id for e in self.visible
        }:
            self.notice = Notice(
                "info", f"Selection cleared: {self.selected_id} is outside the current filter."
            )
            self.selected_id = None
        else:
            self.notice = Notice(
                "neutral", "Filter applied." if _is_filtered(filters) else READY_NOTICE[1]
            )
        return True

    # selection --------------------------------------------------------------------------------------------------
    def select(self, job_id: str | None) -> bool:
        if job_id is None:
            self.selected_id = None
            return True
        if job_id not in {entry.job_id for entry in self.visible}:
            return False
        self.selected_id = job_id
        return True

    def selected_entry(self) -> JobHistoryEntry | None:
        return next((e for e in self.visible if e.job_id == self.selected_id), None)

    def details(self) -> str:
        entry = self.selected_entry()
        return NO_SELECTION_TEXT if entry is None else details_text(entry)


def _is_filtered(filters: HistoryFilters) -> bool:
    return bool(
        filters.text.strip()
        or filters.status_label != ANY_STATUS
        or filters.pack.strip()
        or filters.date_from.strip()
        or filters.date_to.strip()
    )
