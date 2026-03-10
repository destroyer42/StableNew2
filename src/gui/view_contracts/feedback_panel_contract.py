"""Feedback panel contract for review/learning flows."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class FeedbackPanelState:
    can_save: bool
    can_batch_save: bool
    can_undo: bool
    message: str


def update_feedback_state(
    *,
    selected_count: int,
    undo_depth: int,
) -> FeedbackPanelState:
    has_selected_image = int(selected_count or 0) > 0
    can_save = bool(has_selected_image)
    can_batch_save = int(selected_count or 0) > 0
    can_undo = int(undo_depth or 0) > 0
    if not can_save:
        message = "Select an image to save feedback."
    elif can_batch_save:
        message = f"{selected_count} image(s) selected."
    else:
        message = "Ready to save feedback."
    return FeedbackPanelState(
        can_save=can_save,
        can_batch_save=can_batch_save,
        can_undo=can_undo,
        message=message,
    )
