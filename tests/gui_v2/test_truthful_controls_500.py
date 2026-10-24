"""PR-GUI-UX-500: truthful Pipeline controls (Pack Selector, preview thumbnail, navigation help).

Real Tk widgets with injected fakes. No backend, queue, runner or persisted user data is touched.
"""

from __future__ import annotations

import json
import tkinter as tk
from collections.abc import Iterable
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from src.gui import sidebar_panel_v2
from src.gui.panels_v2.reprocess_panel_v2 import ReprocessPanelV2
from src.gui.preview_panel_v2 import PreviewPanelV2
from src.gui.sidebar_panel_v2 import PromptPackSummary, SidebarPanelV2
from src.gui.view_contracts import config_source_contract as contract
from src.gui.widgets.tab_overview_panel_v2 import get_tab_overview_content

pytestmark = pytest.mark.gui


class FakeConfigManager:
    """The slice of ConfigManager the sidebar reads; pack settings live in a dict."""

    def __init__(
        self,
        presets_dir: Path,
        pack_configs: dict[str, dict[str, Any]] | None = None,
    ) -> None:
        self.presets_dir = presets_dir
        self.pack_configs = dict(pack_configs or {})

    def load_pack_config(self, pack_id: str) -> dict[str, Any] | None:
        return self.pack_configs.get(pack_id)


class FakeController:
    """Records the callbacks the sidebar fires; optionally fails them."""

    def __init__(self, config_manager: FakeConfigManager | None = None) -> None:
        self.config_manager = config_manager
        self.calls: list[tuple[str, tuple[Any, ...]]] = []
        self.fail: set[str] = set()

    def _record(self, name: str, *args: Any) -> None:
        self.calls.append((name, args))
        if name in self.fail:
            raise RuntimeError(name)

    def on_pipeline_pack_load_config(self, pack_id: str) -> None:
        self._record("load_pack", pack_id)

    def on_pipeline_pack_apply_config(self, pack_ids: list[str]) -> None:
        self._record("save_to_packs", tuple(pack_ids))

    def on_override_pack_config_changed(self, enabled: bool) -> None:
        self._record("override", enabled)

    def names(self) -> list[str]:
        return [name for name, _args in self.calls]


class FakePackAdapter:
    def __init__(self, summaries: Iterable[PromptPackSummary], packs_dir: str = "C:/packs") -> None:
        self._summaries = list(summaries)
        self.packs_dir = packs_dir

    def load_summaries(self) -> list[PromptPackSummary]:
        return list(self._summaries)


class FakePackLists:
    def __init__(self, lists: dict[str, list[str]] | None = None) -> None:
        self.lists = dict(lists or {})

    def get_list_names(self) -> list[str]:
        return sorted(self.lists)

    def get_list(self, name: str) -> list[str] | None:
        return self.lists.get(name)

    def refresh(self) -> None:
        return None


def _summaries(tmp_path: Path, *names: str) -> list[PromptPackSummary]:
    return [
        PromptPackSummary(name=name, path=tmp_path / f"{name}.json", description="", prompt_count=1)
        for name in names
    ]


def _build(
    root: tk.Tk,
    tmp_path: Path,
    *,
    packs: Iterable[str] = (),
    pack_lists: dict[str, list[str]] | None = None,
    pack_configs: dict[str, dict[str, Any]] | None = None,
    packs_dir: str = "C:/packs",
) -> tuple[SidebarPanelV2, FakeController, FakeConfigManager]:
    config_manager = FakeConfigManager(tmp_path, pack_configs)
    controller = FakeController(config_manager)
    panel = SidebarPanelV2(
        root,
        controller=controller,
        prompt_pack_adapter=FakePackAdapter(_summaries(tmp_path, *packs), packs_dir),
        config_manager=config_manager,
        pack_list_manager=FakePackLists(pack_lists),
    )
    panel.update_idletasks()
    panel.asked = []  # type: ignore[attr-defined]

    def _answer(title: str, message: str) -> bool:
        panel.asked.append((title, message))  # type: ignore[attr-defined]
        return True

    panel._confirm_override = _answer  # type: ignore[attr-defined]
    return panel, controller, config_manager


def _select_packs(panel: SidebarPanelV2, *indexes: int) -> None:
    assert panel.pack_listbox is not None
    panel.pack_listbox.selection_clear(0, "end")
    for index in indexes:
        panel.pack_listbox.selection_set(index)
    panel._on_pack_selection_changed()


def test_pack_config_buttons_are_named_for_what_they_do(tk_root: tk.Tk, tmp_path: Path) -> None:
    panel, _, _ = _build(tk_root, tmp_path, packs=["p1"])
    try:
        assert panel.load_config_button.cget("text") == "Load Pack Settings"
        assert panel.apply_config_button.cget("text") == "Apply to PromptPack\u2026"
        assert panel.add_to_job_button.cget("text") == "Add to Job"
    finally:
        panel.destroy()


def test_pack_buttons_follow_the_selection(tk_root: tk.Tk, tmp_path: Path) -> None:
    panel, controller, _ = _build(tk_root, tmp_path, packs=["p1", "p2"])
    try:
        for button in (
            panel.load_config_button,
            panel.apply_config_button,
            panel.add_to_job_button,
        ):
            assert str(button.cget("state")) == "disabled"
        panel._on_pack_apply_config()
        assert controller.calls == []

        _select_packs(panel, 0)
        assert str(panel.load_config_button.cget("state")) == "normal"
        assert str(panel.apply_config_button.cget("state")) == "normal"

        _select_packs(panel, 0, 1)
        assert str(panel.load_config_button.cget("state")) == "disabled"
        assert str(panel.apply_config_button.cget("state")) == "normal"
        assert str(panel.add_to_job_button.cget("state")) == "normal"

        panel._on_pack_apply_config()
        assert controller.calls == [("save_to_packs", (("p1", "p2"),))]
    finally:
        panel.destroy()


def test_load_pack_config_names_the_promptpack_as_the_source(
    tk_root: tk.Tk, tmp_path: Path
) -> None:
    panel, controller, _ = _build(
        tk_root, tmp_path, packs=["p1", "p2"], pack_configs={"p1": {"pipeline": {}}}
    )
    try:
        _select_packs(panel, 0)
        panel._on_pack_load_config()

        assert controller.calls == [("load_pack", ("p1",))]
        assert "last loaded from PromptPack Settings of 'p1'" in panel.config_source_label.cget(
            "text"
        )

        # A pack with no saved settings loads nothing, so it must not become the source.
        _select_packs(panel, 1)
        panel._on_pack_load_config()
        assert "PromptPack Settings of 'p1'" in panel.config_source_label.cget("text")
        assert "PromptPack Settings of 'p2'" not in panel.config_source_label.cget("text")
    finally:
        panel.destroy()


def test_no_promptpacks_explains_where_they_come_from(tk_root: tk.Tk, tmp_path: Path) -> None:
    panel, _, _ = _build(tk_root, tmp_path, packs=[], packs_dir="C:/Users/x/PromptPacks")
    try:
        text = panel.pack_status_label.cget("text")

        assert "No PromptPacks found in C:/Users/x/PromptPacks" in text
        assert "Prompt tab" in text
        assert panel.pack_listbox.size() == 0
    finally:
        panel.destroy()


def test_packs_hidden_by_content_visibility_are_not_reported_missing(
    tk_root: tk.Tk, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    panel, _, _ = _build(tk_root, tmp_path, packs=["p1", "p2"])
    try:
        monkeypatch.setattr(panel, "_filter_visible_prompt_summaries", lambda summaries: [])
        panel.refresh_prompt_packs()

        text = panel.pack_status_label.cget("text")
        assert "2 PromptPacks hidden by the content-visibility setting" in text
        assert "No PromptPacks found" not in text
    finally:
        panel.destroy()


def test_empty_saved_pack_list_dropdown_is_disabled_and_explained(
    tk_root: tk.Tk, tmp_path: Path
) -> None:
    panel, _, _ = _build(tk_root, tmp_path, packs=["p1"])
    try:
        assert str(panel.pack_list_combo.cget("state")) == "disabled"
        caption = panel.pack_list_caption_label.cget("text")
        assert "No Saved Pack Lists" in caption
        assert "custom_pack_lists.json" in caption
        assert panel.pack_listbox.size() == 1
        assert panel.pack_status_label.cget("text") == "Showing 1 PromptPack."
    finally:
        panel.destroy()


def test_saved_pack_list_filters_and_reports_the_filter(tk_root: tk.Tk, tmp_path: Path) -> None:
    panel, _, _ = _build(
        tk_root,
        tmp_path,
        packs=["p1", "p2", "p3"],
        pack_lists={"Favourites": ["p2"], "Old": ["gone"]},
    )
    try:
        assert str(panel.pack_list_combo.cget("state")) == "readonly"
        assert panel.pack_list_caption_label.cget("text") == contract.PACK_LIST_CAPTION

        panel.pack_list_var.set("Favourites")
        panel._on_pack_list_selected()
        assert list(panel.pack_listbox.get(0, "end")) == ["p2"]
        assert "from Saved Pack List 'Favourites'" in panel.pack_status_label.cget("text")

        panel.pack_list_var.set("Old")
        panel._on_pack_list_selected()
        assert list(panel.pack_listbox.get(0, "end")) == ["p1", "p2", "p3"]
        assert "'Old' matches none of them, so all are shown" in panel.pack_status_label.cget(
            "text"
        )
    finally:
        panel.destroy()


def test_pack_selection_and_state_survive_refresh_and_restore(
    tk_root: tk.Tk, tmp_path: Path
) -> None:
    panel, _, _ = _build(tk_root, tmp_path, packs=["p1", "p2", "p3"])
    try:
        _select_packs(panel, 1)
        panel.refresh_prompt_packs()
        assert [panel._current_pack_names[i] for i in panel.pack_listbox.curselection()] == ["p2"]

        panel.save_state()
        saved = json.loads(Path(sidebar_panel_v2.SIDEBAR_STATE_PATH).read_text())
        assert saved["selected_packs"] == ["p2"]
        assert saved["schema_version"] == "2.6"
    finally:
        panel.destroy()


def test_override_checkbox_states_what_it_decides(tk_root: tk.Tk, tmp_path: Path) -> None:
    panel, controller, _ = _build(tk_root, tmp_path, packs=["p1"])
    try:
        assert panel.override_description_label.cget("text") == contract.OVERRIDE_OFF_TEXT

        panel.override_pack_config_var.set(True)
        panel._on_override_changed()

        assert panel.override_description_label.cget("text") == contract.OVERRIDE_ON_TEXT
        assert controller.calls == [("override", (True,))]
    finally:
        panel.destroy()


# ---- Preview thumbnail --------------------------------------------------------------------------------------


def _preview(root: tk.Tk, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> PreviewPanelV2:
    monkeypatch.setattr(
        "src.gui.preview_panel_v2.PREVIEW_STATE_PATH", tmp_path / "preview_state.json"
    )
    panel = PreviewPanelV2(root, controller=SimpleNamespace(), app_state=None)
    panel.update_idletasks()
    return panel


def _job(job_id: str, **extra: Any) -> SimpleNamespace:
    return SimpleNamespace(
        job_id=job_id,
        label="model",
        positive_preview="p",
        negative_preview="n",
        stages_display="txt2img",
        sampler_name="Euler",
        steps=20,
        cfg_scale=7.0,
        seed=1,
        **extra,
    )


def _image(tmp_path: Path, name: str) -> Path:
    path = tmp_path / name
    path.write_bytes(b"\x89PNG\r\n\x1a\n")
    return path


def _shown_text(panel: PreviewPanelV2) -> str | None:
    return panel.thumbnail._placeholder_shown


def test_thumbnail_checkbox_is_named_for_a_saved_output_not_for_generation(
    tk_root: tk.Tk, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    panel = _preview(tk_root, tmp_path, monkeypatch)
    try:
        label = panel.preview_checkbox.cget("text")

        assert label == "Show output thumbnail"
        assert "generate" not in label.lower()
        assert "ticking this does not generate one" in PreviewPanelV2.PREVIEW_CHECKBOX_TIP
    finally:
        panel.destroy()


def test_enabling_the_checkbox_without_a_job_says_there_is_no_job(
    tk_root: tk.Tk, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    controller = SimpleNamespace(calls=0)
    monkeypatch.setattr(
        "src.gui.preview_panel_v2.PREVIEW_STATE_PATH", tmp_path / "preview_state.json"
    )
    panel = PreviewPanelV2(tk_root, controller=controller, app_state=None)
    try:
        panel._show_preview_var.set(True)
        panel._on_preview_checkbox_changed()

        assert _shown_text(panel) == PreviewPanelV2.NO_JOB_PLACEHOLDER
        assert panel.thumbnail.current_path() is None
        assert controller.calls == 0
    finally:
        panel.destroy()


def test_a_draft_job_without_an_artifact_explains_the_missing_image(
    tk_root: tk.Tk, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    panel = _preview(tk_root, tmp_path, monkeypatch)
    try:
        panel._show_preview_var.set(True)
        panel.set_job_summaries([_job("draft-1")])

        text = _shown_text(panel)
        assert text == PreviewPanelV2.NO_ARTIFACT_PLACEHOLDER
        assert "only after this job has saved an image" in text
        assert "checkbox" not in text.lower() and "enable" not in text.lower()
        assert panel.thumbnail.current_path() is None
        assert str(panel.make_video_button.cget("state")) == "disabled"
    finally:
        panel.destroy()


def test_thumbnail_comes_only_from_the_previewed_job(
    tk_root: tk.Tk, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    other = _image(tmp_path, "other_job.png")
    mine = _image(tmp_path, "my_job.png")
    panel = _preview(tk_root, tmp_path, monkeypatch)
    try:
        panel._show_preview_var.set(True)

        # The panel previews the last job; an earlier job's image must not stand in for it.
        panel.set_job_summaries([_job("a", output_paths=[str(other)]), _job("b", output_paths=[])])
        assert panel.thumbnail.current_path() is None
        assert _shown_text(panel) == PreviewPanelV2.NO_ARTIFACT_PLACEHOLDER

        panel.set_job_summaries(
            [_job("a", output_paths=[str(other)]), _job("b", output_paths=[str(mine)])]
        )
        assert panel._find_immediate_output_image(panel._current_preview_job) == mine
        assert panel.thumbnail.current_path() == str(mine)
    finally:
        panel.destroy()


def test_unticking_hides_the_thumbnail_without_losing_the_previewed_job(
    tk_root: tk.Tk, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    panel = _preview(tk_root, tmp_path, monkeypatch)
    try:
        job = _job("draft-1")
        panel._show_preview_var.set(True)
        panel.set_job_summaries([job])
        panel._show_preview_var.set(False)
        panel._on_preview_checkbox_changed()

        assert panel._current_preview_job is job
        assert not panel.thumbnail_frame.winfo_ismapped()

        panel._show_preview_var.set(True)
        panel._on_preview_checkbox_changed()
        assert _shown_text(panel) == PreviewPanelV2.NO_ARTIFACT_PLACEHOLDER
    finally:
        panel.destroy()


# ---- Navigation and help ------------------------------------------------------------------------------------


def test_pipeline_help_points_existing_images_to_review_and_photo_optimize() -> None:
    content = get_tab_overview_content("pipeline")
    text = " ".join(
        [content.compact_summary, *content.inputs, *content.actions, *content.connections]
    )

    assert "Review or Photo Optimize" in content.compact_summary
    assert "Photo Optimize (enhance photos)" in text
    assert "Make Video (it opens Video Workflow)" in text
    assert "only for a job that has saved an image" in text
    assert "PromptPacks (authored in the Prompt tab)" in text
    assert "generation profiles" in text and "startup defaults" in text


def test_video_workflow_help_mentions_the_make_video_handoff() -> None:
    connections = " ".join(get_tab_overview_content("video_workflow").connections)

    assert "Make Video on the Pipeline preview, Review or Job History" in connections


def test_reprocess_card_directs_to_review_photo_optimize_and_make_video(tk_root: tk.Tk) -> None:
    panel = ReprocessPanelV2(tk_root)
    try:
        labels = " ".join(
            str(child.cget("text")) for child in panel.winfo_children() if "text" in child.keys()
        )

        assert "Review" in labels and "Photo Optimize" in labels
        assert "Make Video" in labels and "Video Workflow" in labels
        assert "Advanced reprocess now lives in Review" not in labels
    finally:
        panel.destroy()


def test_a_thumbnail_hidden_by_visibility_is_not_reported_as_missing(
    tk_root: tk.Tk, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    saved = _image(tmp_path, "saved.png")
    panel = _preview(tk_root, tmp_path, monkeypatch)
    try:
        panel._content_visibility_mode = "sfw"
        panel._show_preview_var.set(True)
        panel.set_job_summaries(
            [_job("job", positive_prompt="explicit", output_paths=[str(saved)])]
        )

        assert _shown_text(panel) == PreviewPanelV2.HIDDEN_PLACEHOLDER
        assert panel.thumbnail.current_path() is None
    finally:
        panel.destroy()
