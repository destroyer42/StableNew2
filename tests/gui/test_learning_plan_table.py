from __future__ import annotations

from src.gui.learning_state import LearningVariant
from src.gui.views.learning_plan_table import LearningPlanTable
from tests.gui_v2.tk_test_utils import get_shared_tk_root


def test_learning_plan_table_variant_numbering_and_stage() -> None:
    root = get_shared_tk_root()
    if root is None:
        return

    table = LearningPlanTable(root)
    table.update_plan(
        [
            LearningVariant(param_value=7.0, status="pending", planned_images=1, completed_images=0),
            LearningVariant(param_value=8.0, status="queued", planned_images=2, completed_images=1),
        ],
        stage_name="img2img",
    )

    rows = table.tree.get_children()
    assert len(rows) == 2
    first = table.tree.item(rows[0], "values")
    second = table.tree.item(rows[1], "values")
    assert first[0] == "#1"
    assert second[0] == "#2"
    assert first[2] == "img2img"


def test_learning_plan_table_selection_callback_uses_row_index() -> None:
    root = get_shared_tk_root()
    if root is None:
        return

    table = LearningPlanTable(root)
    table.update_plan(
        [
            LearningVariant(param_value=7.0, status="pending", planned_images=1, completed_images=0),
            LearningVariant(param_value=8.0, status="pending", planned_images=1, completed_images=0),
        ],
        stage_name="txt2img",
    )

    selected: list[int] = []
    table.set_on_variant_selected(lambda idx: selected.append(idx))

    row = table.tree.get_children()[1]
    table.tree.selection_set(row)
    table._on_row_selected(None)
    assert selected == [1]

