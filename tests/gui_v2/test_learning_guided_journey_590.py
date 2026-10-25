"""PR-LEARN-UX-590 highest-value integration: Design -> Preview -> Run -> Compare -> Rate -> Recommendations.

Real Tk widgets and the real controller / execution controller over a temporary job repository. The only
submission seam is the recording fake JobService; no runner, backend or generation is started.
"""

from __future__ import annotations

from pathlib import Path
from tkinter import messagebox
from unittest.mock import Mock, patch

import pytest
from PIL import Image

from src.learning.guided_workflow import (
    ACTION_BUILD_PREVIEW,
    ACTION_RATE,
    ACTION_REVIEW_RESULTS,
    ACTION_RUN,
    ACTION_VIEW_PROGRESS,
    STEP_COMPARE,
    STEP_DESIGN,
    STEP_PREVIEW,
    STEP_RATE,
    STEP_RUN,
)
from src.queue.job_model import JobStatus
from src.queue.job_repository import JobRepository
from tests.gui_v2.test_learning_guided_workflow_590 import (
    build_tab,
    click_primary,
    design_cfg_sweep,
    primary,
)
from tests.gui_v2.tk_test_utils import get_shared_tk_root
from tests.learning_v2.test_learning_recovery_260 import transition


@pytest.fixture
def root():
    shared = get_shared_tk_root()
    if shared is None:
        pytest.skip("No display available for Tkinter tests")
    return shared


@pytest.fixture
def repo(tmp_path):
    repository = JobRepository(tmp_path / "jobs.sqlite3")
    yield repository
    repository.close()


@pytest.fixture
def tab_and_service(root, tmp_path, repo):
    tab, service = build_tab(root, tmp_path, repo)
    tab.pack(fill="both", expand=True)
    root.update()
    yield tab, service
    tab.destroy()


def _complete(repo, service, tmp_path: Path, plan) -> list[list[str]]:
    images: list[list[str]] = []
    for index, variant in enumerate(plan):
        paths = []
        for sample in range(2):
            path = tmp_path / f"out_{index}_{sample}.png"
            Image.new("RGB", (16, 16), (index * 40, sample * 90, 10)).save(path)
            paths.append(str(path))
        images.append(paths)
        result = {
            "variants": [
                {
                    "output_paths": paths,
                    "final_prompt": "portrait",
                    "all_seeds": [42, 43],
                    "all_subseeds": [700, 701],
                    "runtime_admission": {"launch_profile": "forge-profile-1"},
                }
            ]
        }
        service.finish(transition(repo, variant.job_id, JobStatus.COMPLETED, result))
    return images


def test_guided_journey_from_design_to_rated_evidence(
    tab_and_service, root, repo, tmp_path, monkeypatch
):
    tab, service = tab_and_service
    panel = tab.experiment_panel
    controller = tab.learning_controller
    monkeypatch.setattr(messagebox, "askyesno", Mock(return_value=True))
    monkeypatch.setattr(messagebox, "showinfo", Mock())
    steps: list[str] = []

    with patch(
        "src.pipeline.pipeline_runner.PipelineRunner.run_njr", side_effect=AssertionError("runner")
    ):
        # Design: nothing is queued while designing, and the estimate is truthful before any Preview.
        design_cfg_sweep(panel)
        assert primary(tab)[0] == ACTION_BUILD_PREVIEW
        assert "3 variants x 2 images = 6 images" in panel.estimate_var.get()
        assert service.calls == []
        steps.append(tab._viewed_step)

        # Preview: frozen, non-executing, with the expected image count.
        click_primary(tab, root)
        assert tab._viewed_step == STEP_PREVIEW and primary(tab)[0] == ACTION_RUN
        assert "3 variants x 2 images = 6 expected images" in tab.preview_card.headline_var.get()
        assert service.calls == []
        steps.append(tab._viewed_step)

        # Run: one all-or-none admission through the queue; the plan keeps the submitted job identities.
        click_primary(tab, root)
        assert len(service.calls) == 1 and len(service.calls[0]) == 3
        plan = controller.learning_state.plan
        assert [v.job_id for v in plan] == [r.job_id for r in service.calls[0]]
        assert tab._viewed_step == STEP_RUN and primary(tab)[0] == ACTION_VIEW_PROGRESS
        steps.append(tab._viewed_step)

        # Results arrive from the repository (never from the GUI): the guide offers Compare, then Rate.
        images = _complete(repo, service, tmp_path, plan)
        root.update()
        assert all(v.status == "completed" for v in plan)
        assert primary(tab)[0] in {ACTION_REVIEW_RESULTS, ACTION_RATE}
        tab._goto_step(STEP_COMPARE)
        root.update()
        review = tab.review_panel
        assert len(review.variant_summary_list.get(0, "end")) == 3
        steps.append(tab._viewed_step)

        # Rate: Save & Next walks every image once, in stable order, with no invented ratings.
        tab._goto_step(STEP_RATE)
        root.update()
        assert tab._viewed_step == STEP_RATE
        review.rating_var.set(0)
        visited = []
        scores = [2, 2, 5, 5, 3, 4]
        for score in scores:
            visited.append(review._selected_image_ref())  # noqa: SLF001
            review.rating_var.set(score)
            review.save_and_next()
            root.update()
        flat = [path for variant_paths in images for path in variant_paths]
        assert visited == flat
        assert [controller.get_rating_for_image(path) for path in flat] == scores
        steps.append(tab._viewed_step)

    writer_path = controller._learning_record_writer.records_path  # noqa: SLF001
    assert len(writer_path.read_text(encoding="utf-8").splitlines()) == 6
    assert len(service.calls) == 1  # rating never queued or ran anything
    assert steps == [STEP_DESIGN, STEP_PREVIEW, STEP_RUN, STEP_COMPARE, STEP_RATE]

    # Recommendations are the outcome of the ratings: the summary says what it knows and why Apply is or is
    # not available, without applying or changing anything.
    recommendations = controller.get_recommendations_for_current_prompt()
    review.update_recommendations(recommendations)
    assert review.recommendation_summary_var.get() == "Suggested: cfg_scale: 7.0"
    assert "cfg_scale is already 7.0" in review.apply_note_var.get()
    assert tab.workflow_bar.status_var.get().endswith("Complete")
    assert len(service.calls) == 1  # still nothing queued after recommendations were shown
