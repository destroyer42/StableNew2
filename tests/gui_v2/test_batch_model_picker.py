"""DESK-QUICK: search and per-model status in the batch builder's model list."""

from __future__ import annotations

import threading
from typing import Any

import pytest

from src.gui.batch_builder_dialog import BatchBuilderDialog, BatchBuilderPanel, BatchSources
from src.gui.batch_model_picker import ModelStatusReport
from src.pipeline.policy_warnings import PolicyWarning
from src.services.model_file_health import ModelFileHealth, ModelFileProblem

MODELS = [
    ("Juggernaut XL v9", "juggernautXL_v9.safetensors"),
    ("Pony v6", "ponyDiffusion_v6.safetensors"),
    ("Klein 4B", "flux-2-klein-4b-fp8.safetensors"),
]

REPORT = ModelStatusReport(
    run_counts={"juggernautxl_v9": 12},
    health=ModelFileHealth(
        entries=(
            ModelFileProblem("image", "flux-2-klein-4b-fp8.safetensors", ("qwen is missing",)),
        )
    ),
    warnings={
        "ponyDiffusion_v6.safetensors": PolicyWarning(
            code="image_model_unqualified",
            subject="ponyDiffusion_v6.safetensors",
            title="Pony is not qualified.",
            why="Nobody has run it.",
            fix="Queue runs it anyway.",
        )
    },
)


def _dialog(root: Any, **kwargs: Any) -> Any:
    """The dialog's panel; destroy its ``winfo_toplevel()`` when done."""

    window = BatchBuilderDialog(
        root,
        packs=["castles"],
        models=MODELS,
        plan_batch=lambda *_a: None,
        queue_batch=lambda *_a: None,
        selected_model=MODELS[0][1],
        **kwargs,
    )
    return window.panel


@pytest.fixture
def dialog(tk_root: Any):  # type: ignore[no-untyped-def]
    panel = _dialog(tk_root)
    yield panel
    panel.winfo_toplevel().destroy()


def _rows(dialog: Any) -> list[str]:
    return list(dialog.model_list.get(0, "end"))


def test_search_filters_the_list_and_keeps_the_selected_models_visible(dialog) -> None:  # type: ignore[no-untyped-def]
    dialog.model_picker.search_var.set("klein")

    assert _rows(dialog) == ["Juggernaut XL v9", "Klein 4B"]
    assert dialog.selected_models() == [MODELS[0][1]]

    dialog.model_list.selection_set(1)
    assert dialog.selected_models() == [MODELS[0][1], MODELS[2][1]]

    dialog.model_picker.search_var.set("")
    assert len(_rows(dialog)) == 3
    assert dialog.selected_models() == [MODELS[0][1], MODELS[2][1]]


def test_search_matches_every_word_against_the_name_and_file(dialog) -> None:  # type: ignore[no-untyped-def]
    dialog.model_list.selection_clear(0, "end")

    dialog.model_picker.search_var.set("pony diffusion")

    assert _rows(dialog) == ["Pony v6"]


def test_each_row_shows_runs_warnings_and_missing_files(dialog) -> None:  # type: ignore[no-untyped-def]
    dialog.model_picker.apply_status(REPORT)

    rows = _rows(dialog)
    assert "ran 12 times here" in rows[0]
    assert "warning" in rows[1] and "missing files" not in rows[1]
    assert "missing files" in rows[2]
    assert dialog.selected_models() == [MODELS[0][1]]


def test_the_detail_line_gives_the_why_and_fix_of_the_picked_model(dialog) -> None:  # type: ignore[no-untyped-def]
    dialog.model_picker.apply_status(REPORT)

    dialog.model_picker.show_detail(1)
    text = dialog.model_picker.detail_label.cget("text")
    assert "Nobody has run it." in text and "Queue runs it anyway." in text

    dialog.model_picker.show_detail(2)
    assert "qwen is missing" in dialog.model_picker.detail_label.cget("text")


def test_the_missing_files_window_lists_every_model_with_missing_files(dialog) -> None:  # type: ignore[no-untyped-def]
    dialog.model_picker.apply_status(REPORT)

    window = dialog.model_picker.show_missing_files()

    assert "qwen is missing" in window.body.get("1.0", "end")
    window.destroy()


def test_status_is_loaded_off_the_tk_thread(tk_root) -> None:  # type: ignore[no-untyped-def]
    release, ran_on = threading.Event(), []

    def load(_cancelled):  # type: ignore[no-untyped-def]
        ran_on.append(threading.current_thread())
        assert release.wait(5.0)
        return REPORT

    window = _dialog(tk_root, load_model_status=load)
    try:
        picker = window.model_picker
        picker.refresh_status()
        assert "ran 12" not in _rows(window)[0]  # returned at once
        release.set()
        picker.worker.join(5.0)
        picker.poll_status()
        assert "ran 12 times here" in _rows(window)[0]
        assert ran_on[0] is not threading.current_thread()
    finally:
        release.set()
        window.winfo_toplevel().destroy()


def test_the_embedded_panel_takes_a_status_loader_later_and_rereads_when_models_change(
    tk_root,
) -> None:  # type: ignore[no-untyped-def]
    """N6: the Generate panel is built empty, before a controller and the model list exist."""

    panel = BatchBuilderPanel(
        tk_root, packs=(), models=(), plan_batch=lambda *_a: None, queue_batch=lambda *_a: None
    )
    reads: list[int] = []

    def load(_cancelled):  # type: ignore[no-untyped-def]
        reads.append(1)
        return REPORT

    def finish() -> None:
        panel.model_picker.worker.join(5.0)
        panel.model_picker.poll_status()

    try:
        panel.set_sources(BatchSources(packs=("castles",), models=tuple(MODELS)))
        panel.model_picker.set_status_loader(load)
        panel.model_picker.refresh_status()
        finish()
        assert "ran 12 times here" in panel.model_list.get(0)

        assert not panel.model_picker.stale
        panel.set_sources(BatchSources(packs=("castles",), models=tuple(MODELS[:2])))
        assert panel.model_picker.stale
    finally:
        panel.destroy()


def test_the_generate_tab_gives_its_builder_the_status_loader(tk_root) -> None:  # type: ignore[no-untyped-def]
    from types import SimpleNamespace

    from src.gui.views.generate_tab_frame_v2 import GenerateTabFrameV2

    controller = SimpleNamespace(
        _background_tasks=object(),
        app_state=SimpleNamespace(resources={"models": []}),
        resource_service=None,
    )
    sidebar = SimpleNamespace(
        controller=controller,
        _current_pack_names=["castles"],
        pack_listbox=None,
        get_base_generation_panel=lambda: SimpleNamespace(
            model_choices=lambda: list(MODELS), selected_model_name=lambda: ""
        ),
        stage_states={},
    )
    tab = GenerateTabFrameV2(tk_root, sidebar_provider=lambda: sidebar)
    try:
        assert tab.refresh_sources()
        assert tab.batch_panel.model_picker.has_status_loader
        assert tab.batch_panel.model_list.size() == 3
    finally:
        tab.destroy()
