from __future__ import annotations

import tkinter as tk

import pytest

from src.gui.learning_review_dialog_v2 import LearningReviewDialogV2
from src.learning.learning_record import LearningRecord


class StubController:
    def __init__(self):
        self.enabled = None
        self.saved = []

    def set_learning_enabled(self, value):
        self.enabled = value

    def list_recent_records(self, limit=10):
        return []

    def save_feedback(self, record, rating, tags=None):
        self.saved.append((record, rating, tags))


def test_learning_toggle_calls_controller(gui_app_factory):
    stub = StubController()
    app = gui_app_factory(controller=stub)
    app._on_learning_toggle(True)
    assert stub.enabled is True
    app._on_learning_toggle(False)
    assert stub.enabled is False


def test_learning_review_dialog_saves_feedback(tk_root):
    controller = StubController()
    record = LearningRecord(
        run_id="r1",
        timestamp="t1",
        base_config={},
        variant_configs=[],
        randomizer_mode="",
        randomizer_plan_size=0,
        primary_model="m",
        primary_sampler="Euler",
        primary_scheduler="Normal",
        primary_steps=10,
        primary_cfg_scale=7.0,
        metadata={},
    )
    dialog = LearningReviewDialogV2(tk_root, controller, [record])
    for rec, rating_var, tags_var in dialog._rows:
        rating_var.set("5")
        tags_var.set("good,sharp")
    dialog._on_save()
    assert controller.saved
    saved_rec, rating, tags = controller.saved[0]
    assert saved_rec.run_id == "r1"
    assert rating == 5
    assert "good" in tags
