from __future__ import annotations

from src.gui.models.prompt_pack_model import MatrixConfig, MatrixSlot
from src.gui.prompt_workspace_state import PromptWorkspaceState
from src.gui.widgets.matrix_tab_panel import MatrixTabPanel
from tests.gui_v2.tk_test_utils import get_shared_tk_root


def test_matrix_tab_panel_random_mode_preview_uses_multiple_slots() -> None:
    root = get_shared_tk_root()
    if root is None:
        return

    workspace = PromptWorkspaceState()
    pack = workspace.new_pack("Random Matrix Pack")
    pack.get_slot(0).text = "A [[job]] in a [[environment]] with [[lighting]]"
    pack.matrix = MatrixConfig(
        enabled=True,
        mode="random",
        limit=4,
        slots=[
            MatrixSlot(name="job", values=["wizard", "knight"]),
            MatrixSlot(name="environment", values=["forest", "castle"]),
            MatrixSlot(name="lighting", values=["day", "night"]),
        ],
    )

    panel = MatrixTabPanel(root, workspace, on_matrix_changed=lambda: None)
    panel._update_preview()  # noqa: SLF001

    text = panel.preview_text.get("1.0", "end")
    assert "wizard" in text or "knight" in text
    assert "forest" in text or "castle" in text
    assert "day" in text or "night" in text
    assert "[[" not in text

    panel.destroy()


def test_matrix_tab_panel_random_mode_samples_only_up_to_the_limit_without_a_second_algorithm() -> (
    None
):
    root = get_shared_tk_root()
    if root is None:
        return

    workspace = PromptWorkspaceState()
    pack = workspace.new_pack("Random Matrix Pack")
    pack.get_slot(0).text = "A [[job]] in a [[environment]] with [[lighting]]"
    pack.matrix = MatrixConfig(
        enabled=True,
        mode="random",
        limit=4,
        slots=[
            MatrixSlot(name="job", values=["wizard", "knight"]),
            MatrixSlot(name="environment", values=["forest", "castle"]),
            MatrixSlot(name="lighting", values=["day", "night"]),
        ],
    )

    panel = MatrixTabPanel(root, workspace, on_matrix_changed=lambda: None)

    # The editor keeps no combination algorithm of its own: the counts and examples are the shared plan's.
    assert not hasattr(panel, "_build_combinations")
    assert not hasattr(panel, "_build_random_combinations")

    panel._update_preview()  # noqa: SLF001

    view = panel.last_view
    assert view is not None
    assert view.plan.theoretical_count == 8
    assert view.plan.selected_count == 4
    assert len(view.example_rows) == 4
    text = panel.preview_text.get("1.0", "end")
    assert "Illustrative examples (not frozen)" in panel.preview_heading_var.get()
    assert "[[" not in text

    panel.destroy()
