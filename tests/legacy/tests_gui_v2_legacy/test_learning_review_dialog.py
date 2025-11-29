from __future__ import annotations

import tkinter as tk

import pytest

from src.gui.learning_review_dialog_v2 import LearningReviewDialogV2
from src.gui_v2.adapters.learning_adapter_v2 import LearningRecordSummary


class StubLearningController:
    def __init__(self, records):
        self.records = records
        self.saved = []

    def list_recent_records(self, limit=10):
        return self.records

    def save_feedback(self, record, rating, tags=None):
        self.saved.append((record.run_id, rating, tags))


@pytest.fixture
def summaries():
    return [
        LearningRecordSummary(
            run_id="r1",
            timestamp="t1",
            prompt_summary="p1",
            pipeline_summary="m1",
            rating=None,
            tags=[],
        )
    ]


def test_learning_review_dialog_updates_feedback(tk_root, summaries):
    controller = StubLearningController(records=summaries)
    dialog = LearningReviewDialogV2(tk_root, controller, summaries)
    for rec, rating_var, tags_var in dialog._rows:
        rating_var.set("4")
        tags_var.set("nice,sharp")
    dialog._on_save()
    assert controller.saved
    rid, rating, tags = controller.saved[0]
    assert rid == "r1"
    assert rating == 4
    assert "sharp" in tags
