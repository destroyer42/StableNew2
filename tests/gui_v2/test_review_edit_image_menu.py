"""Inpainting and outpainting are reachable from Review without marking an image for Re-work.

Operator report 2026-11-19: after the task-first regroup (PR-REVIEW-LIFECYCLE-621) Edit Mask and Extend Canvas lived
only inside the Re-work region, which stays hidden until an image is marked, so Review appeared to have no inpainting.
"""

# ruff: noqa: F811, F401  (the Review batch fixtures are reused from test_review_batch_200)

from __future__ import annotations

import pytest

from src.gui.view_contracts.review_workspace_contract import ItemState, item_key
from tests.gui_v2.test_review_batch_200 import images, mark_for_rework, workflow


def _labels(menu) -> list[str]:
    return [menu.entrycget(index, "label") for index in range(menu.index("end") + 1)]


def _invoke(menu, label: str) -> None:
    menu.invoke(_labels(menu).index(label))


@pytest.mark.gui
def test_edit_image_menu_is_in_the_always_visible_review_actions(workflow, tmp_path):
    _controller, _repository, tab = workflow
    paths = images(tmp_path, 2)
    tab._set_selected_images(paths)

    # Nothing is marked, so the Re-work region stays hidden.
    assert tab._rework_frame.winfo_manager() == ""
    assert str(tab.edit_image_button.cget("text")) == "Edit image..."
    assert tab.edit_image_button.master is tab.send_to_button.master
    assert _labels(tab.edit_image_menu) == [
        "Inpaint (Edit Mask)...",
        "Outpaint (Extend Canvas)...",
    ]


@pytest.mark.gui
@pytest.mark.parametrize(
    ("label", "dialog"),
    [
        ("Inpaint (Edit Mask)...", "src.gui.mask_editor_dialog.MaskEditorDialog"),
        ("Outpaint (Extend Canvas)...", "src.gui.outpaint_dialog.OutpaintDialog"),
    ],
)
def test_the_menu_edits_the_image_shown_without_a_rework_mark(
    workflow, tmp_path, monkeypatch, label, dialog
):
    _controller, repository, tab = workflow
    paths = images(tmp_path, 3)
    tab._set_selected_images(paths)
    tab._show_next_image()
    shown = tab._selected_image_path
    assert shown is not None and shown != paths[0]
    opened: list[dict] = []
    monkeypatch.setattr(dialog, lambda parent, **kw: opened.append(kw))

    _invoke(tab.edit_image_menu, label)

    assert [kw["source_path"] for kw in opened] == [shown]
    assert not tab._session.rework_scope()  # nothing was marked for Re-work
    assert not repository.list_jobs()


@pytest.mark.gui
def test_the_menu_edits_the_image_shown_even_when_several_are_marked(
    workflow, tmp_path, monkeypatch
):
    _controller, _repository, tab = workflow
    paths = images(tmp_path, 3)
    mark_for_rework(tab, tmp_path, paths)
    # The Re-work region's own button needs exactly one marked image.
    assert str(tab.edit_mask_button.cget("state")) == "disabled"
    shown = tab._selected_image_path
    opened: list[dict] = []
    monkeypatch.setattr(
        "src.gui.mask_editor_dialog.MaskEditorDialog", lambda parent, **kw: opened.append(kw)
    )

    _invoke(tab.edit_image_menu, "Inpaint (Edit Mask)...")

    assert [kw["source_path"] for kw in opened] == [shown]
    assert {tab._session.state_of(item_key(p)) for p in paths} == {ItemState.REWORK_MARKED}


@pytest.mark.gui
def test_the_menu_says_why_when_no_image_is_shown(workflow, monkeypatch):
    _controller, _repository, tab = workflow
    warnings: list[tuple[str, str]] = []
    monkeypatch.setattr(
        "src.gui.views.review_tab_frame_v2.messagebox.showwarning",
        lambda title, text, **kw: warnings.append((title, text)),
    )
    monkeypatch.setattr(
        "src.gui.mask_editor_dialog.MaskEditorDialog",
        lambda parent, **kw: pytest.fail("no image is shown"),
    )

    _invoke(tab.edit_image_menu, "Inpaint (Edit Mask)...")

    assert warnings == [("Edit Mask", "Select an image first.")]
