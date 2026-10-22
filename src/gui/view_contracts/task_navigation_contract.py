"""Task-first navigation contract (PR-GUI-410).

A pure, toolkit-independent description of how the nine workspace tabs are presented as operator task groups.
A group is a presentation category only: it owns no tab, job, queue or selection state. The single
``MainWindowV2.center_notebook`` stays the selection authority and ``_tab_registry`` the tab-identity authority; the
Tk shell binds this contract to them.

No Tk calls live here. The module also owns the stable-id persistence rules: new sessions store ``selected_tab_id``;
the historic numeric ``selected_index`` is read as a fallback (it indexes the notebook's creation order, which is
:data:`LEGACY_TAB_ORDER`) and never trusted over an id.
"""

from __future__ import annotations

from collections.abc import Collection, Mapping
from dataclasses import dataclass
from typing import Any

# Notebook creation order. Historic saved ``tabs.selected_index`` values index this tuple, so it must not be reordered.
LEGACY_TAB_ORDER: tuple[str, ...] = (
    "prompt",
    "pipeline",
    "learning",
    "review",
    "photo_optimize",
    "movie_clips",
    "character_training",
    "svd",
    "video_workflow",
)

# Today's effective first tab: the Pipeline workspace is raised once the panels are attached.
DEFAULT_TAB_ID = "pipeline"

HOLD_LABEL_SUFFIX = "HOLD"


@dataclass(frozen=True)
class NavDestination:
    """One workspace reachable from navigation; ``tab_id`` is the stable ``_tab_registry`` id."""

    tab_id: str
    label: str
    group_id: str
    hold: bool = False
    hold_reason: str = ""

    @property
    def display_label(self) -> str:
        return f"{self.label} ({HOLD_LABEL_SUFFIX})" if self.hold else self.label


@dataclass(frozen=True)
class NavGroup:
    """A presentation category of destinations, in display order."""

    group_id: str
    label: str
    destinations: tuple[NavDestination, ...]

    @property
    def tab_ids(self) -> tuple[str, ...]:
        return tuple(destination.tab_id for destination in self.destinations)


_CHARACTER_TRAINING_HOLD_REASON = (
    "Character Training is on hold pending a trainer decision; no trainer is bundled."
)

TASK_GROUPS: tuple[NavGroup, ...] = (
    NavGroup(
        "create",
        "Create",
        (
            NavDestination("prompt", "Prompt", "create"),
            NavDestination("pipeline", "Pipeline", "create"),
        ),
    ),
    NavGroup(
        "edit",
        "Edit",
        (
            NavDestination("review", "Review", "edit"),
            NavDestination("photo_optimize", "Photo Optimize", "edit"),
        ),
    ),
    NavGroup(
        "motion",
        "Motion",
        (
            NavDestination("video_workflow", "Video Workflow", "motion"),
            NavDestination("svd", "SVD Img2Vid", "motion"),
            NavDestination("movie_clips", "Movie Clips", "motion"),
        ),
    ),
    NavGroup(
        "learn",
        "Learn",
        (NavDestination("learning", "Learning", "learn"),),
    ),
    NavGroup(
        "advanced",
        "Advanced",
        (
            NavDestination(
                "character_training",
                "Character Training",
                "advanced",
                hold=True,
                hold_reason=_CHARACTER_TRAINING_HOLD_REASON,
            ),
        ),
    ),
)

_DESTINATIONS: dict[str, NavDestination] = {
    destination.tab_id: destination for group in TASK_GROUPS for destination in group.destinations
}
_GROUPS: dict[str, NavGroup] = {group.group_id: group for group in TASK_GROUPS}


def group_ids() -> tuple[str, ...]:
    return tuple(group.group_id for group in TASK_GROUPS)


def all_tab_ids() -> tuple[str, ...]:
    """Every tab id in navigation order (group order, then destination order)."""

    return tuple(destination.tab_id for group in TASK_GROUPS for destination in group.destinations)


def get_group(group_id: str) -> NavGroup | None:
    return _GROUPS.get(str(group_id or ""))


def get_destination(tab_id: str) -> NavDestination | None:
    return _DESTINATIONS.get(str(tab_id or ""))


def group_for_tab(tab_id: str) -> NavGroup | None:
    destination = get_destination(tab_id)
    return None if destination is None else _GROUPS[destination.group_id]


def default_tab_for_group(group_id: str, available: Collection[str] | None = None) -> str | None:
    """First destination of a group that exists (all of them when ``available`` is None)."""

    group = get_group(group_id)
    if group is None:
        return None
    for tab_id in group.tab_ids:
        if available is None or tab_id in available:
            return tab_id
    return None


def legacy_tab_id_for_index(index: Any) -> str | None:
    """Translate a historic notebook index to a tab id; None for anything out of range or non-integer."""

    if isinstance(index, bool) or not isinstance(index, int):
        return None
    if 0 <= index < len(LEGACY_TAB_ORDER):
        return LEGACY_TAB_ORDER[index]
    return None


def resolve_startup_tab_id(tabs_state: Any, available: Collection[str]) -> str:
    """Pick the tab to show at startup from a stored ``tabs`` payload.

    Order: a stored ``selected_tab_id`` that is known and present, then a historic ``selected_index`` translated
    through :data:`LEGACY_TAB_ORDER` (only when no valid id is stored), then :data:`DEFAULT_TAB_ID`, then the first
    present tab in navigation order. Corrupt, unknown or absent entries never raise. Returns ``""`` only when no
    navigation tab is available at all.
    """

    present = set(available)
    payload: Mapping[str, Any] = tabs_state if isinstance(tabs_state, Mapping) else {}
    stored_id = payload.get("selected_tab_id")
    if isinstance(stored_id, str) and stored_id in _DESTINATIONS and stored_id in present:
        return stored_id
    if "selected_tab_id" not in payload or not isinstance(stored_id, str):
        legacy_id = legacy_tab_id_for_index(payload.get("selected_index"))
        if legacy_id is not None and legacy_id in present:
            return legacy_id
    if DEFAULT_TAB_ID in present:
        return DEFAULT_TAB_ID
    for tab_id in all_tab_ids():
        if tab_id in present:
            return tab_id
    return ""


def merge_tabs_state(
    existing: Any, *, selected_tab_id: str | None, selected_index: int | None
) -> dict[str, Any]:
    """Return the ``tabs`` payload to save, keeping unrelated keys already stored there.

    ``selected_index`` is still written so an older build reading the same file keeps working; ``selected_tab_id`` is
    the authority and is written only for a known id (an unresolved selection keeps the previously stored values).
    """

    merged: dict[str, Any] = dict(existing) if isinstance(existing, Mapping) else {}
    if isinstance(selected_tab_id, str) and selected_tab_id in _DESTINATIONS:
        merged["selected_tab_id"] = selected_tab_id
    if isinstance(selected_index, int) and not isinstance(selected_index, bool):
        merged["selected_index"] = selected_index
    return merged


__all__ = [
    "DEFAULT_TAB_ID",
    "HOLD_LABEL_SUFFIX",
    "LEGACY_TAB_ORDER",
    "TASK_GROUPS",
    "NavDestination",
    "NavGroup",
    "all_tab_ids",
    "default_tab_for_group",
    "get_destination",
    "get_group",
    "group_for_tab",
    "group_ids",
    "legacy_tab_id_for_index",
    "merge_tabs_state",
    "resolve_startup_tab_id",
]
