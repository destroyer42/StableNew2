"""Learning automation modes: names, labels, the default, and how a persisted choice is read back.

Until the selector existed the mode could not be chosen, so every saved ``suggest_only`` was the old hard-coded value,
not a decision. A saved mode therefore counts only when it carries ``automation_mode_user_set``; anything else reads
back as the default.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

SUGGEST_ONLY = "suggest_only"
APPLY_WITH_CONFIRM = "apply_with_confirm"
AUTO_MICRO_EXPERIMENT = "auto_micro_experiment"

DEFAULT_AUTOMATION_MODE = APPLY_WITH_CONFIRM
AUTOMATION_MODES = (SUGGEST_ONLY, APPLY_WITH_CONFIRM, AUTO_MICRO_EXPERIMENT)

AUTOMATION_MODE_LABELS: dict[str, str] = {
    SUGGEST_ONLY: "Suggest only (never apply)",
    APPLY_WITH_CONFIRM: "Apply with confirm",
    AUTO_MICRO_EXPERIMENT: "Auto micro-experiment (apply, then queue 1 preview job)",
}

USER_SET_KEY = "automation_mode_user_set"


def normalize_automation_mode(value: object) -> str:
    """A known mode, lower-cased; anything else is the default."""

    mode = str(value or "").strip().lower()
    return mode if mode in AUTOMATION_MODES else DEFAULT_AUTOMATION_MODE


def mode_for_label(label: object) -> str:
    """The mode a combobox label stands for (a bare mode name is accepted too)."""

    text = str(label or "").strip()
    for mode, known in AUTOMATION_MODE_LABELS.items():
        if text == known:
            return mode
    return normalize_automation_mode(text)


def resolve_persisted_mode(payload: Mapping[str, Any] | None) -> tuple[str, bool]:
    """``(mode, user_set)`` for a saved Learning payload; an unmarked saved mode is not a choice."""

    if isinstance(payload, Mapping) and payload.get(USER_SET_KEY) is True:
        return normalize_automation_mode(payload.get("automation_mode")), True
    return DEFAULT_AUTOMATION_MODE, False


__all__ = [
    "APPLY_WITH_CONFIRM",
    "AUTOMATION_MODES",
    "AUTOMATION_MODE_LABELS",
    "AUTO_MICRO_EXPERIMENT",
    "DEFAULT_AUTOMATION_MODE",
    "SUGGEST_ONLY",
    "USER_SET_KEY",
    "mode_for_label",
    "normalize_automation_mode",
    "resolve_persisted_mode",
]
