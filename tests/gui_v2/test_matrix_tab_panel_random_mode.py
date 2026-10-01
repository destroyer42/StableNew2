from __future__ import annotations

from unittest.mock import patch

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


def test_matrix_tab_panel_random_mode_does_not_materialize_cartesian_product() -> None:
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

    # The Cartesian product of this matrix has 8 combinations. Random mode must
    # sample only up to ``limit`` of them via the dedicated random builder
    # instead of enumerating the full product and truncating.
    with patch.object(
        panel,
        "_build_random_combinations",
        wraps=panel._build_random_combinations,  # noqa: SLF001
    ) as random_builder:
        panel._update_preview()  # noqa: SLF001

    random_builder.assert_called_once()
    assert random_builder.call_args.args[2] == 4
    text = panel.preview_text.get("1.0", "end")
    assert "Preview (4 of 4 combinations)" in text
    assert "[[" not in text

    panel.destroy()
