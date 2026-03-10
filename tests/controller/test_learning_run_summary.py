from __future__ import annotations

from src.gui.controllers.learning_controller import LearningController
from src.gui.learning_state import LearningExperiment, LearningState, LearningVariant


class _PipelineSummaryStub:
    def can_enqueue_learning_jobs(self, requested_jobs: int):
        if requested_jobs > 2:
            return (False, "cap exceeded")
        return (True, "")

    def get_learning_queue_cap(self):
        return 3

    def get_queue_depth(self):
        return 1


def test_learning_run_summary_aggregates_variant_and_queue_info() -> None:
    state = LearningState()
    state.current_experiment = LearningExperiment(name="s", stage="txt2img", images_per_value=2)
    state.plan = [
        LearningVariant(param_value=1, status="pending", planned_images=2, completed_images=0),
        LearningVariant(param_value=2, status="queued", planned_images=2, completed_images=0),
        LearningVariant(param_value=3, status="completed", planned_images=2, completed_images=2),
        LearningVariant(param_value=4, status="failed", planned_images=2, completed_images=0),
    ]
    controller = LearningController(
        learning_state=state,
        pipeline_controller=_PipelineSummaryStub(),
    )

    summary = controller.get_learning_run_summary()
    assert summary["total_variants"] == 4
    assert summary["total_planned_images"] == 8
    assert summary["total_completed_images"] == 2
    assert summary["status_counts"]["pending"] == 1
    assert summary["status_counts"]["queued"] == 1
    assert summary["status_counts"]["completed"] == 1
    assert summary["status_counts"]["failed"] == 1
    assert summary["queue_cap"] == 3
    assert summary["queue_depth"] == 1
    assert summary["queue_ok"] is True


def test_learning_run_summary_reports_blocked_when_pending_would_exceed_cap() -> None:
    state = LearningState()
    state.current_experiment = LearningExperiment(name="s", stage="txt2img", images_per_value=1)
    state.plan = [
        LearningVariant(param_value=1, status="pending", planned_images=1, completed_images=0),
        LearningVariant(param_value=2, status="pending", planned_images=1, completed_images=0),
        LearningVariant(param_value=3, status="pending", planned_images=1, completed_images=0),
    ]
    controller = LearningController(
        learning_state=state,
        pipeline_controller=_PipelineSummaryStub(),
    )
    summary = controller.get_learning_run_summary()
    assert summary["queue_ok"] is False
    assert "cap exceeded" in summary["queue_reason"]

