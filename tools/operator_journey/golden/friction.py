"""Operator friction and the four-way outcome of a journey.

A journey that PASSes functionally may still have needed things an ordinary operator should not need: a forced
maximize, a dragged pane, a mouse release that had to follow a moving control, a retried click or a wait for a hidden
widget.  Those are recorded here as friction (never silently counted as defect-free) and linked to the structured
finding that explains them.  Reachability is assessed only where real pointer input was used; the semantic Tk driver
fires widget callbacks, so it can say nothing about whether a person could reach a control.
"""

from __future__ import annotations

from collections import defaultdict
from typing import Any

#: trace action -> (friction kind, finding id, kind-of-friction)
FRICTION_ACTIONS: dict[str, tuple[str, str | None, str]] = {
    "maximize_window": ("window_forced_maximized", "GP830-F1", "workaround"),
    "drag_sash": ("pane_dragged_to_reveal_controls", "GP830-F1", "workaround"),
    "pointer_followed_control": ("mouse_release_followed_moving_control", "GP830-F2", "workaround"),
    "reclick_after_no_effect": ("click_retried_after_no_effect", "GP830-F2", "workaround"),
    "typing_retried": ("typing_retried_with_another_strategy", None, "workaround"),
    "waited_for_state": ("waited_for_hidden_or_disabled_control", None, "workaround"),
    "dialog_never_appeared": ("expected_dialog_never_appeared", None, "workaround"),
}
#: Ordinary operator behaviour that is worth counting but is not a workaround.
INFORMATIONAL_ACTIONS = {
    "scrolled_into_view": "page_scrolled_with_the_wheel",
    "scrolled_with_scrollbar": "page_scrolled_with_the_scrollbar",
}

REACHABILITY_DIRECT = "DIRECT"
REACHABILITY_WORKAROUNDS = "WITH_WORKAROUNDS"
REACHABILITY_BLOCKED = "BLOCKED"
REACHABILITY_NOT_ASSESSED = "NOT_ASSESSED"
NOT_ASSESSED = "NOT_ASSESSED"


def friction_report(trace: list[dict[str, Any]]) -> dict[str, Any]:
    grouped: dict[str, dict[str, Any]] = defaultdict(
        lambda: {"count": 0, "labels": [], "finding": None, "class": "workaround"}
    )
    info: dict[str, int] = defaultdict(int)
    for entry in trace:
        action = entry.get("action")
        if action in FRICTION_ACTIONS:
            kind, finding, cls = FRICTION_ACTIONS[action]
            row = grouped[kind]
            row["count"] += 1
            row["finding"], row["class"] = finding, cls
            label = entry.get("label")
            if label and label not in row["labels"] and len(row["labels"]) < 8:
                row["labels"].append(str(label))
        elif action in INFORMATIONAL_ACTIONS:
            info[INFORMATIONAL_ACTIONS[action]] += 1
    return {
        "workarounds": dict(sorted(grouped.items())),
        "workaround_count": sum(r["count"] for r in grouped.values()),
        "informational": dict(sorted(info.items())),
    }


def reachability(driver: str, verdict: str, failed: str | None, report: dict[str, Any]) -> str:
    if driver != "windows":
        return REACHABILITY_NOT_ASSESSED
    text = (failed or "").lower()
    if verdict != "PASS" and ("unreachable" in text or "controlunreachable" in text):
        return REACHABILITY_BLOCKED
    return REACHABILITY_WORKAROUNDS if report["workaround_count"] else REACHABILITY_DIRECT


def outcomes(
    driver: str, verdict: str, failed: str | None, report: dict[str, Any], *, physical: bool = False
) -> dict[str, Any]:
    """Functional / reachability / resource / visual-quality, each honest about what was and was not assessed."""

    return {
        "functional": verdict,
        "reachability": reachability(driver, verdict, failed, report),
        "resource_safety": NOT_ASSESSED if not physical else "SEE_PHYSICAL_OUTCOMES",
        "visual_quality": "PENDING_OPERATOR_REVIEW" if physical else NOT_ASSESSED,
    }


__all__ = [
    "FRICTION_ACTIONS",
    "REACHABILITY_BLOCKED",
    "REACHABILITY_DIRECT",
    "REACHABILITY_NOT_ASSESSED",
    "REACHABILITY_WORKAROUNDS",
    "friction_report",
    "outcomes",
    "reachability",
]
