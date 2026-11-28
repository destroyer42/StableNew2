"""VID-FRAME: the line beside Queue says when the selected workflow would crop the source."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from src.gui.views.video_workflow_tab_frame_v2 import VideoWorkflowTabFrameV2
from src.video.workflow_catalog_wan_a14b import WAN_A14B_ID
from tests.helpers.make_video_313 import RECOMMENDED_ID, make_app, make_image

pytestmark = pytest.mark.gui


def test_a_cropped_source_warns_beside_queue_without_blocking(tk_root, tmp_path: Path) -> None:
    app, _controller, _service = make_app(tmp_path)
    tab = VideoWorkflowTabFrameV2(tk_root, app_controller=app, app_state=SimpleNamespace())
    try:
        portrait = make_image(tmp_path / "portrait.png", (768, 1024))
        tab.workflow_var.set(RECOMMENDED_ID)  # the full-picture default keeps a 3:4 source whole
        tab.set_source_image_path(portrait)
        assert "cut away" not in tab.queue_block_reason_var.get()

        tab.workflow_var.set(WAN_A14B_ID)  # 480x832 cuts it
        tab.set_source_image_path(portrait)
        assert "23% of the source picture is cut away" in tab.queue_block_reason_var.get()
        assert str(tab.queue_workflow_button.cget("state")) == "normal"

        tab.set_source_image_path(make_image(tmp_path / "tall.png", (720, 1280)))
        assert "cut away" not in tab.queue_block_reason_var.get()
    finally:
        tab.destroy()
