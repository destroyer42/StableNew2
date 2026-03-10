from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from src.gui.app_state_v2 import AppStateV2
from src.gui.learning_state import LearningExperiment, LearningVariant
from src.gui.views.learning_tab_frame_v2 import LearningTabFrame
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
        store = UIStateStore(state_path)

        with patch("src.gui.views.learning_tab_frame_v2.get_ui_state_store", return_value=store):
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
            assert saved["learning"]["session"]["current_experiment"]["name"] == "Resume Test"

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
