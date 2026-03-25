from __future__ import annotations

import pytest

from src.gui.views.movie_clips_tab_frame_v2 import MovieClipsTabFrameV2
from src.gui.views.svd_tab_frame_v2 import SVDTabFrameV2
from src.gui.views.video_workflow_tab_frame_v2 import VideoWorkflowTabFrameV2


@pytest.mark.gui
def test_pipeline_stage_surfaces_expose_setting_help(gui_app_factory) -> None:
    app = gui_app_factory()

    base_generation = app.pipeline_tab.sidebar.base_generation_panel
    txt2img = app.pipeline_tab.stage_cards_panel.txt2img_card
    img2img = app.pipeline_tab.stage_cards_panel.img2img_card
    upscale = app.pipeline_tab.stage_cards_panel.upscale_card
    adetailer = app.pipeline_tab.stage_cards_panel.adetailer_card

    assert "denoising algorithm" in base_generation._setting_tooltips["sampler"].text.lower()
    assert "classifier-free guidance" in base_generation._setting_tooltips["cfg"].text.lower()
    assert "text-encoder layers" in txt2img._setting_tooltips["clip_skip"].text.lower()
    assert "move away from the source image" in img2img._setting_tooltips["denoise"].text.lower()
    assert "overall upscale multiplier" in upscale._setting_tooltips["scale"].text.lower()
    assert "minimum detection confidence" in adetailer._setting_tooltips["confidence"].text.lower()


@pytest.mark.gui
def test_video_surfaces_expose_setting_help(tk_root) -> None:
    svd_tab = SVDTabFrameV2(tk_root)
    workflow_tab = VideoWorkflowTabFrameV2(tk_root)
    movie_clips_tab = MovieClipsTabFrameV2(tk_root)
    try:
        assert "tested group of svd settings" in svd_tab._setting_tooltips["preset"].text.lower()
        assert "encouraged to add" in svd_tab._setting_tooltips["motion_bucket"].text.lower()
        assert "authored workflow recipe" in workflow_tab._setting_tooltips["workflow"].text.lower()
        assert "motion intensity profile" in workflow_tab._setting_tooltips["motion"].text.lower()
        assert "frames per second" in movie_clips_tab._setting_tooltips["fps"].text.lower()
        assert "assembled into the output clip" in movie_clips_tab._setting_tooltips["mode"].text.lower()
    finally:
        movie_clips_tab.destroy()
        workflow_tab.destroy()
        svd_tab.destroy()