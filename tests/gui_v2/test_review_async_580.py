"""PR-GUI-UX-580: Review's folder scan, image-context and comparison work runs off Tk and only the latest result lands."""

from __future__ import annotations

from pathlib import Path

import pytest
from PIL import Image

from src.gui.views.review_tab_frame_v2 import ReviewTabFrame
from src.review.workspace_io import (
    MAX_FOLDER_IMAGES,
    CompareImageError,
    prepare_compare,
    scan_image_folder,
)
from src.utils.image_metadata import build_contract_kv, write_image_metadata
from tests.gui_v2.edit_work_helpers import use_held_delivery, use_manual_registry


def _png(path: Path, *, prompt: str | None = None, size=(24, 24), color=(5, 6, 7)) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", size, color).save(path)
    if prompt is not None:
        payload = {
            "generation": {"model": "m.safetensors"},
            "stage_manifest": {"stage": "txt2img", "final_prompt": prompt, "config": {"steps": 10}},
        }
        assert write_image_metadata(
            path, build_contract_kv(payload, job_id="j", run_id="r", stage="txt2img")
        )
    return path


@pytest.fixture
def quiet(monkeypatch):
    monkeypatch.setattr(
        "src.gui.views.review_tab_frame_v2.messagebox.showinfo", lambda *a, **k: None
    )
    monkeypatch.setattr(
        "src.gui.views.review_tab_frame_v2.messagebox.showerror", lambda *a, **k: None
    )


def _pick_folder(monkeypatch, folder: Path) -> None:
    monkeypatch.setattr(
        "src.gui.views.review_tab_frame_v2.filedialog.askdirectory", lambda **_: str(folder)
    )


def _handoff(path: Path, **overrides):
    from src.gui.controllers.history_iterate_service import HISTORY_ITERATE_SOURCE
    from src.gui.controllers.review_workflow_adapter import ReviewWorkspaceHandoff

    fields = {
        "source": HISTORY_ITERATE_SOURCE,
        "workflow_title": "Edit Image from History",
        "target_stage": "",
        "image_paths": [path],
        "base_prompt": "",
        "base_negative_prompt": "",
        "prompt_delta": "",
        "negative_prompt_delta": "",
        "prompt_mode": "append",
        "negative_prompt_mode": "append",
        "stage_img2img": False,
        "stage_adetailer": False,
        "stage_upscale": False,
        "source_metadata_by_path": {
            str(path): {"history_iterate": {"job_id": "j", "choice": "edit_image"}}
        },
    }
    fields.update(overrides)
    return ReviewWorkspaceHandoff(**fields)


# --- folder scan -------------------------------------------------------------------------------------


def test_select_folder_returns_before_the_scan_runs_and_publishes_only_when_it_finishes(
    tk_root, tmp_path, monkeypatch, quiet
):
    registry = use_manual_registry(monkeypatch)
    folder = tmp_path / "shots"
    _png(folder / "b.png")
    _png(folder / "nested" / "a.png")
    _pick_folder(monkeypatch, folder)
    tab = ReviewTabFrame(tk_root)
    try:
        tab._on_select_folder()
        assert (
            registry.queued and tab.selected_images == []
        )  # the worker has not run: Tk was not asked to walk
        assert "Scanning" in tab.selection_label.cget("text")
        registry.run_all()
        assert [p.name for p in tab.selected_images] == ["b.png", "a.png"] or len(
            tab.selected_images
        ) == 2
        assert tab.selection_label.cget("text") == "2 image(s) selected"
    finally:
        tab.destroy()


def test_a_late_folder_scan_cannot_replace_a_history_handoff_accepted_meanwhile(
    tk_root, tmp_path, monkeypatch, quiet
):
    held = use_held_delivery(monkeypatch)
    folder = tmp_path / "shots"
    _png(folder / "x.png")
    recorded = _png(tmp_path / "recorded.png", prompt="a red fox")
    _pick_folder(monkeypatch, folder)
    tab = ReviewTabFrame(tk_root)
    try:
        tab._on_select_folder()  # the scan finished on its worker, its delivery is still pending
        handoff = _handoff(recorded)
        assert tab.load_history_iterate_handoff(handoff)
        held.deliver()
        assert tab.selected_images == [recorded]
        assert tab._active_handoff is handoff
        assert tab.selection_label.cget("text") == "1 image(s) selected"
    finally:
        tab.destroy()


def test_a_newer_folder_request_supersedes_an_older_one(tk_root, tmp_path, monkeypatch, quiet):
    held = use_held_delivery(monkeypatch)
    first, second = tmp_path / "first", tmp_path / "second"
    _png(first / "one.png")
    _png(second / "two.png", color=(9, 9, 9))
    tab = ReviewTabFrame(tk_root)
    try:
        _pick_folder(monkeypatch, first)
        tab._on_select_folder()
        _pick_folder(monkeypatch, second)
        tab._on_select_folder()
        held.pending.reverse()  # the older scan reports last
        held.deliver()
        assert [p.name for p in tab.selected_images] == ["two.png"]
    finally:
        tab.destroy()


def test_an_oversized_folder_is_refused_not_partially_loaded(tmp_path):
    for index in range(4):
        _png(tmp_path / f"{index}.png", color=(index, 0, 0))
    scan = scan_image_folder(tmp_path, limit=3)
    assert scan.too_many and scan.paths == ()
    assert MAX_FOLDER_IMAGES >= 1000


def test_an_empty_folder_leaves_the_selection_alone_and_says_so(
    tk_root, tmp_path, monkeypatch, quiet
):
    keep = _png(tmp_path / "keep.png")
    empty = tmp_path / "empty"
    empty.mkdir()
    tab = ReviewTabFrame(tk_root)
    try:
        tab._set_selected_images([keep])
        _pick_folder(monkeypatch, empty)
        tab._on_select_folder()
        assert tab.selected_images == [keep]
        assert "No PNG, JPEG or WebP images" in tab.workflow_hint_label.cget("text")
    finally:
        tab.destroy()


# --- image context -----------------------------------------------------------------------------------


def test_metadata_of_a_superseded_image_never_overwrites_the_current_one(
    tk_root, tmp_path, monkeypatch, quiet
):
    held = use_held_delivery(monkeypatch)
    a = _png(tmp_path / "a.png", prompt="prompt for image A")
    b = _png(tmp_path / "b.png", prompt="prompt for image B", color=(80, 80, 80))
    tab = ReviewTabFrame(tk_root)
    try:
        tab._set_selected_images([a, b])  # A is shown first
        tab._show_image(b)  # the operator moves on before A's worker result is delivered
        held.pending.reverse()  # A's result arrives after B's
        held.deliver()
        assert tab._selected_image_path == b
        assert tab._selected_base_prompt == "prompt for image B"
        assert "prompt for image A" not in tab.meta_label.cget("text")
    finally:
        tab.destroy()


def test_a_prompt_edit_made_while_metadata_loads_survives_the_late_result(
    tk_root, tmp_path, monkeypatch, quiet
):
    held = use_held_delivery(monkeypatch)
    a = _png(tmp_path / "a.png", prompt="stored prompt")
    tab = ReviewTabFrame(tk_root)
    try:
        tab._set_selected_images([a])
        tab._set_text(tab.prompt_text, "operator typed this")
        tab._on_prompt_edited()
        held.deliver()
        assert tab._get_text(tab.prompt_text) == "operator typed this"
        assert tab._selected_base_prompt == "stored prompt"
    finally:
        tab.destroy()


def test_effective_settings_wait_for_the_metadata_instead_of_guessing(
    tk_root, tmp_path, monkeypatch, quiet
):
    held = use_held_delivery(monkeypatch)
    a = _png(tmp_path / "a.png", prompt="p")
    tab = ReviewTabFrame(tk_root)
    try:
        tab._set_selected_images([a])
        assert tab._image_ready is False
        held.deliver()
        assert tab._image_ready is True
    finally:
        tab.destroy()


def test_a_destroyed_tab_drops_every_late_callback(tk_root, tmp_path, monkeypatch, quiet):
    registry = use_manual_registry(monkeypatch)
    folder = tmp_path / "shots"
    _png(folder / "x.png")
    _pick_folder(monkeypatch, folder)
    tab = ReviewTabFrame(tk_root)
    tab._on_select_folder()
    tab._set_selected_images([_png(tmp_path / "solo.png", prompt="p")])
    tab.destroy()
    registry.run_all()  # workers finish after the widget is gone: nothing may touch it


# --- comparison viewer -------------------------------------------------------------------------------


def test_closing_the_viewer_discards_a_decode_still_in_flight(
    tk_root, tmp_path, monkeypatch, quiet
):
    held = use_held_delivery(monkeypatch)
    big = _png(tmp_path / "big.png", size=(64, 48))
    tab = ReviewTabFrame(tk_root)
    try:
        tab._render_compare_viewer(big, title_prefix="t")
        window = tab._compare_window
        assert window is not None and window.winfo_exists()
        window.destroy()  # the operator closes the viewer while the decode is out
        tk_root.update()
        held.deliver()
        assert tab._compare_window is None or not tab._compare_window.winfo_exists()
        assert getattr(tab, "_compare_photo", None) is None
    finally:
        tab.destroy()


def test_a_second_comparison_supersedes_the_first_one(tk_root, tmp_path, monkeypatch, quiet):
    held = use_held_delivery(monkeypatch)
    one = _png(tmp_path / "one.png", size=(40, 30))
    two = _png(tmp_path / "two.png", size=(80, 60), color=(1, 2, 3))
    tab = ReviewTabFrame(tk_root)
    try:
        tab._render_compare_viewer(one, title_prefix="t")
        tab._render_compare_viewer(two, title_prefix="t")
        held.pending.reverse()
        held.deliver()
        assert tab._compare_photo is not None and tab._compare_photo.width() == 80
    finally:
        tab.destroy()


def test_comparison_decode_is_bounded_and_refuses_unbounded_sources(tmp_path):
    wide = _png(tmp_path / "wide.png", size=(6000, 40))
    prepared = prepare_compare(wide, max_edge=512)
    assert max(prepared.image.size) <= 512 and prepared.scaled
    pair = prepare_compare(wide, _png(tmp_path / "s.png", size=(30, 30)), max_edge=512)
    assert pair.image.size[0] <= 512 + 512 + 24
    with pytest.raises(CompareImageError, match="too large"):
        prepare_compare(wide, max_pixels=1000)
    with pytest.raises(CompareImageError, match="no longer available"):
        prepare_compare(tmp_path / "gone.png")
    broken = tmp_path / "broken.png"
    broken.write_bytes(b"not an image")
    with pytest.raises(CompareImageError, match="could not be opened"):
        prepare_compare(broken)
