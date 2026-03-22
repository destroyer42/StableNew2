from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from src.gui.app_state_v2 import AppStateV2
from src.gui.learning_state import LearningExperiment, LearningVariant
from src.gui.views.learning_tab_frame_v2 import LearningTabFrame
from src.gui.views.learning_review_panel import LearningReviewPanel
from src.learning.discovered_review_models import DiscoveredReviewExperiment, DiscoveredReviewItem
from src.learning.discovered_review_store import DiscoveredReviewStore
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


def test_learning_review_panel_viewer_window_size_prefers_image_dimensions() -> None:
    width, height = LearningReviewPanel._compute_viewer_window_size(
        image_width=768,
        image_height=1280,
        screen_width=1920,
        screen_height=1080,
    )

    assert width >= 768
    assert width <= int(1920 * 0.9)
    assert height == int(1080 * 0.9)


def test_learning_review_panel_viewer_window_size_caps_to_screen() -> None:
    width, height = LearningReviewPanel._compute_viewer_window_size(
        image_width=2200,
        image_height=3400,
        screen_width=1600,
        screen_height=900,
    )

    assert width == int(1600 * 0.9)
    assert height == int(900 * 0.9)


def test_learning_tab_includes_staged_curation_mode() -> None:
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

            labels = [
                tab._mode_notebook.tab(tab_id, "text")  # noqa: SLF001
                for tab_id in tab._mode_notebook.tabs()  # noqa: SLF001
            ]
            assert "Staged Curation" in labels
            tab.destroy()


def test_learning_tab_staged_curation_persists_selection_event(tmp_path) -> None:
    root = get_shared_tk_root()
    if root is None:
        return

    state_path = tmp_path / "ui_state.json"
    experiments_root = tmp_path / "experiments"
    discovered_root = tmp_path / "discovered"
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
        try:
            discovered_store = DiscoveredReviewStore(discovered_root)
            tab.learning_controller._discovered_review_store = discovered_store  # noqa: SLF001
            experiment = DiscoveredReviewExperiment(
                group_id="disc-stage",
                display_name="Stage Group",
                stage="txt2img",
                prompt_hash="hash-1",
                items=[
                    DiscoveredReviewItem(
                        item_id="item-1",
                        artifact_path=str(tmp_path / "fake.png"),
                        stage="txt2img",
                        model="juggernautXL",
                        sampler="DPM++ 2M",
                        steps=30,
                        cfg_scale=6.5,
                    )
                ],
                varying_fields=["cfg_scale"],
            )
            discovered_store.save_group(experiment)

            tab._on_staged_open_group("disc-stage")  # noqa: SLF001
            assert len(tab._staged_candidate_tree.get_children()) == 1  # noqa: SLF001

            tab._staged_reason_tag_vars["good_composition"].set(True)  # noqa: SLF001
            tab._staged_notes_text.insert("1.0", "promote this image")  # noqa: SLF001
            tab._apply_staged_decision("advanced_to_refine")  # noqa: SLF001

            events = discovered_store.load_selection_events("disc-stage")
            assert len(events) == 1
            assert events[0].decision == "advanced_to_refine"
            assert events[0].reason_tags == ["good_composition"]
        finally:
            tab.destroy()


def test_learning_tab_staged_curation_face_tier_and_submit_hooks(tmp_path) -> None:
    root = get_shared_tk_root()
    if root is None:
        return

    state_path = tmp_path / "ui_state.json"
    experiments_root = tmp_path / "experiments"
    discovered_root = tmp_path / "discovered"
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
        try:
            discovered_store = DiscoveredReviewStore(discovered_root)
            tab.learning_controller._discovered_review_store = discovered_store  # noqa: SLF001
            image_path = tmp_path / "fake-tier.png"
            image_path.write_text("placeholder", encoding="utf-8")
            experiment = DiscoveredReviewExperiment(
                group_id="disc-stage-tier",
                display_name="Stage Group",
                stage="txt2img",
                prompt_hash="hash-1",
                items=[
                    DiscoveredReviewItem(
                        item_id="item-1",
                        artifact_path=str(image_path),
                        stage="txt2img",
                        model="juggernautXL",
                        sampler="DPM++ 2M",
                        steps=30,
                        cfg_scale=6.5,
                    )
                ],
                varying_fields=["cfg_scale"],
            )
            discovered_store.save_group(experiment)

            tab._on_staged_open_group("disc-stage-tier")  # noqa: SLF001

            tab._staged_face_tier_var.set("heavy")  # noqa: SLF001
            tab._on_staged_face_triage_tier_changed()  # noqa: SLF001
            loaded = discovered_store.load_group("disc-stage-tier")
            assert loaded is not None
            assert loaded.items[0].extra_fields["face_triage_tier"] == "heavy"

            with patch.object(
                tab.learning_controller,
                "submit_staged_curation_advancement",
                return_value=2,
            ) as submit_mock:
                tab._submit_staged_jobs("face_triage")  # noqa: SLF001

            submit_mock.assert_called_once_with("disc-stage-tier", "face_triage")
            assert "Submitted 2 face triage job(s)" in tab._staged_job_status_var.get()  # noqa: SLF001
        finally:
            tab.destroy()
