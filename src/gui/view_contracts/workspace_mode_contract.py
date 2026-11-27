"""N6: the Simple / Advanced workspace mode, a Tk-free presentation contract.

Simple (the default) opens on the Generate workspace and shows a short list of tabs; Advanced shows every tab and
option that exists, as before. The mode only decides what navigation and a few panels *show*: every tab is still
built, registered and selectable (a handoff to a hidden tab still opens it), every study and stored record still
loads, and nothing is refused (warn, don't block; ``AGENTS.md`` section 2).

The mode is persisted in the UI state file as ``{"workspace": {"mode": "simple" | "advanced"}}``. A missing or
unknown value means Simple. No Tk calls live here; ``task_navigation_contract`` reads the tab set from this module.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

WORKSPACE_SIMPLE = "simple"
WORKSPACE_ADVANCED = "advanced"
WORKSPACE_MODES: tuple[str, ...] = (WORKSPACE_SIMPLE, WORKSPACE_ADVANCED)
DEFAULT_WORKSPACE_MODE = WORKSPACE_SIMPLE

#: The UI-state key the mode is stored under.
WORKSPACE_STATE_KEY = "workspace"

#: Tabs the Simple workspace shows, by stable tab id; navigation order comes from the task groups.
SIMPLE_TAB_IDS: frozenset[str] = frozenset(
    {"generate", "review", "video_workflow", "storyboard", "learning"}
)
#: Where Simple opens when the stored tab is not one it shows.
SIMPLE_DEFAULT_TAB_ID = "generate"

#: Learning study types Simple hides from the objective chooser. Each had 0 saved experiments in the owner's
#: workspace on 2026-11-26 (Controlled Variable 23, LoRA Composition 29, Model Comparison 11, Compatibility Probe 3).
#: They stay in ``study_catalog``; a saved or selected experiment of these types still opens, runs and rates.
SIMPLE_HIDDEN_STUDY_SLUGS: tuple[str, ...] = (
    "prompt_slot",
    "embedding_experiment",
    "two_axis_grid",
    "prompt_model_matrix",
)

SWITCH_LABEL = "Advanced"
SWITCH_TOOLTIP = (
    "Off: a simple workspace (Generate, Review, Video, Storyboard, Learning). "
    "On: every tab and option, as before. Nothing is removed either way."
)


def normalize_workspace_mode(value: Any) -> str:
    """``value`` when it is a known mode, else the default (Simple)."""

    return value if isinstance(value, str) and value in WORKSPACE_MODES else DEFAULT_WORKSPACE_MODE


def workspace_mode_from_state(state: Any) -> str:
    """The mode stored in a UI-state payload; corrupt or absent entries mean the default."""

    payload: Mapping[str, Any] = state if isinstance(state, Mapping) else {}
    workspace = payload.get(WORKSPACE_STATE_KEY)
    if not isinstance(workspace, Mapping):
        return DEFAULT_WORKSPACE_MODE
    return normalize_workspace_mode(workspace.get("mode"))


def workspace_state_payload(existing: Any, mode: str) -> dict[str, Any]:
    """The ``workspace`` payload to save, keeping unrelated keys already stored there."""

    merged: dict[str, Any] = dict(existing) if isinstance(existing, Mapping) else {}
    merged["mode"] = normalize_workspace_mode(mode)
    return merged


def is_simple(mode: str) -> bool:
    return normalize_workspace_mode(mode) == WORKSPACE_SIMPLE


def hidden_study_slugs(mode: str) -> tuple[str, ...]:
    """Study types the objective chooser hides in ``mode`` (none in Advanced)."""

    return SIMPLE_HIDDEN_STUDY_SLUGS if is_simple(mode) else ()


def shows_discovered_outputs(mode: str) -> bool:
    """Whether Learning shows its Discovered Outputs view (hidden in Simple: 831 of 834 groups never reviewed)."""

    return not is_simple(mode)


__all__ = [
    "DEFAULT_WORKSPACE_MODE",
    "SIMPLE_DEFAULT_TAB_ID",
    "SIMPLE_HIDDEN_STUDY_SLUGS",
    "SIMPLE_TAB_IDS",
    "SWITCH_LABEL",
    "SWITCH_TOOLTIP",
    "WORKSPACE_ADVANCED",
    "WORKSPACE_MODES",
    "WORKSPACE_SIMPLE",
    "WORKSPACE_STATE_KEY",
    "hidden_study_slugs",
    "is_simple",
    "normalize_workspace_mode",
    "shows_discovered_outputs",
    "workspace_mode_from_state",
    "workspace_state_payload",
]
