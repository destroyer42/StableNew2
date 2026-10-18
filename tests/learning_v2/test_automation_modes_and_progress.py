"""Default automation mode, how a saved choice is read, and the ratings-needed message."""

from __future__ import annotations

import pytest

from src.learning.automation_modes import (
    AUTOMATION_MODE_LABELS,
    AUTOMATION_MODES,
    DEFAULT_AUTOMATION_MODE,
    mode_for_label,
    normalize_automation_mode,
    resolve_persisted_mode,
)
from src.learning.evidence_progress import evidence_progress


def test_the_default_is_apply_with_confirm_and_every_mode_stays_selectable() -> None:
    assert DEFAULT_AUTOMATION_MODE == "apply_with_confirm"
    assert set(AUTOMATION_MODE_LABELS) == set(AUTOMATION_MODES)
    assert "auto_micro_experiment" in AUTOMATION_MODES


@pytest.mark.parametrize("mode", AUTOMATION_MODES)
def test_labels_round_trip(mode: str) -> None:
    assert mode_for_label(AUTOMATION_MODE_LABELS[mode]) == mode
    assert mode_for_label(mode) == mode


def test_unknown_modes_fall_back_to_the_default() -> None:
    assert normalize_automation_mode("bogus") == DEFAULT_AUTOMATION_MODE
    assert normalize_automation_mode(None) == DEFAULT_AUTOMATION_MODE
    assert normalize_automation_mode(" Suggest_Only ") == "suggest_only"


def test_a_saved_suggest_only_is_the_old_hardcoded_value_not_a_choice() -> None:
    assert resolve_persisted_mode({"automation_mode": "suggest_only"}) == (
        DEFAULT_AUTOMATION_MODE,
        False,
    )
    assert resolve_persisted_mode(None) == (DEFAULT_AUTOMATION_MODE, False)


def test_a_marked_saved_mode_is_kept() -> None:
    payload = {"automation_mode": "suggest_only", "automation_mode_user_set": True}
    assert resolve_persisted_mode(payload) == ("suggest_only", True)
    payload = {"automation_mode": "auto_micro_experiment", "automation_mode_user_set": True}
    assert resolve_persisted_mode(payload) == ("auto_micro_experiment", True)
    assert (
        resolve_persisted_mode(
            {"automation_mode": "suggest_only", "automation_mode_user_set": "yes"}
        )[1]
        is False
    )


def test_progress_counts_ratings_and_tested_values() -> None:
    assert (
        evidence_progress([]).message()
        == "Need 3 more ratings across at least 2 more tested values for recommendations."
    )
    assert (
        evidence_progress([1]).message()
        == "Need 2 more ratings across at least 1 more tested value for recommendations."
    )
    assert (
        evidence_progress([3]).message() == "Need at least 1 more tested value for recommendations."
    )
    assert evidence_progress([1, 1]).message() == "Need 1 more rating for recommendations."
    assert evidence_progress([2, 1]).ready is True
    assert evidence_progress([2, 1]).message() == "Enough ratings for recommendations."
