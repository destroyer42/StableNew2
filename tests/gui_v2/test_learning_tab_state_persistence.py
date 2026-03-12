from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from src.gui.app_state_v2 import AppStateV2
from src.gui.learning_state import LearningExperiment, LearningVariant
from src.gui.views.learning_tab_frame_v2 import LearningTabFrame
from src.gui.views.learning_review_panel import LearningReviewPanel
from src.services.ui_state_store import UIStateStore
from tests.gui_v2.tk_test_utils import get_shared_tk_root


class _StubPipelineController:
    def set_learning_enabled(self, _enabled: bool) -> None:
        return


def test_learning_tab_persists_and_restores_resume_session() -> None:
    root = get_shared_tk_root()
    if root is None:
        return

    with TemporaryDirectory() as tmp_dir:
        state_path = Path(tmp_dir) / "ui_state.json"
        experiments_root = Path(tmp_dir) / "experiments"
        store = UIStateStore(state_path)

        with patch("src.gui.views.learning_tab_frame_v2.get_ui_state_store", return_value=store), patch(
            "src.gui.views.learning_tab_frame_v2.get_learning_experiments_root",
            return_value=experiments_root,
        ):
            tab = LearningTabFrame(
                root,
                app_state=AppStateV2(),
                pipeline_controller=_StubPipelineController(),
            )

            experiment = LearningExperiment(
                name="Resume Test",
                description="Resume me",
                prompt_text="portrait",
                stage="txt2img",
                variable_under_test="Steps",
                images_per_value=2,
            )
            variant = LearningVariant(
                experiment_id="Resume Test",
                param_value=20,
                status="completed",
                planned_images=2,
                completed_images=2,
                image_refs=["out/a.png", "out/b.png"],
            )
            tab.learning_controller.learning_state.current_experiment = experiment
            tab.learning_controller.learning_state.plan = [variant]
            tab.learning_controller.learning_state.selected_variant = variant

            tab._persist_learning_session_state()  # noqa: SLF001
            saved = store.load_state()
            assert saved is not None
            experiment_id = saved["learning"]["last_experiment_id"]
            assert experiment_id
            session_path = experiments_root / experiment_id / "session.json"
            assert session_path.exists()

            restored_tab = LearningTabFrame(
                root,
                app_state=AppStateV2(),
                pipeline_controller=_StubPipelineController(),
            )
            assert restored_tab.restore_learning_session_state(saved["learning"]) is True
            assert restored_tab.learning_controller.learning_state.current_experiment is not None
            assert restored_tab.learning_controller.learning_state.current_experiment.name == "Resume Test"
            assert restored_tab.experiment_panel.name_var.get() == "Resume Test"
            assert restored_tab.experiment_panel.variable_var.get() == "Steps"

            restored_tab.destroy()
            tab.destroy()


def test_learning_tab_places_review_panel_below_plan_for_larger_preview() -> None:
    root = get_shared_tk_root()
    if root is None:
        return

    with TemporaryDirectory() as tmp_dir:
        state_path = Path(tmp_dir) / "ui_state.json"
        experiments_root = Path(tmp_dir) / "experiments"
        store = UIStateStore(state_path)

        with patch("src.gui.views.learning_tab_frame_v2.get_ui_state_store", return_value=store), patch(
            "src.gui.views.learning_tab_frame_v2.get_learning_experiments_root",
            return_value=experiments_root,
        ):
            tab = LearningTabFrame(
                root,
                app_state=AppStateV2(),
                pipeline_controller=_StubPipelineController(),
            )

            plan_grid = tab.plan_table.grid_info()
            review_grid = tab.review_panel.grid_info()

            assert int(plan_grid["row"]) == 0
            assert int(plan_grid["column"]) == 1
            assert int(plan_grid["columnspan"]) == 2
            assert int(review_grid["row"]) == 1
            assert int(review_grid["column"]) == 1
            assert int(review_grid["columnspan"]) == 2

            tab.destroy()


def test_learning_review_panel_prioritizes_image_column() -> None:
    root = get_shared_tk_root()
    if root is None:
        return

    panel = LearningReviewPanel(root)
    try:
        preview_grid = panel.preview_column.grid_info()
        side_grid = panel.side_column.grid_info()
        image_grid = panel.image_frame.grid_info()
        rating_grid = panel.rating_frame.grid_info()

        assert int(preview_grid["column"]) == 0
        assert int(side_grid["column"]) == 1
        assert int(image_grid["row"]) == 0
        assert int(rating_grid["row"]) == 3
        assert int(panel.grid_columnconfigure(0)["weight"]) > int(panel.grid_columnconfigure(1)["weight"])
    finally:
        panel.destroy()
