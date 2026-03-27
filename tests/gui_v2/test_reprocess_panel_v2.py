from __future__ import annotations

import tkinter as tk
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace

import pytest
from tkinter import ttk

from src.pipeline.reprocess_builder import ReprocessEffectiveSettingsPreview, ReprocessStageSettingsPreview
from src.gui.controllers.review_workflow_adapter import ReviewWorkspaceHandoff
from src.gui.artifact_metadata_inspector_dialog import ArtifactMetadataInspectorDialog
from src.gui.theme_v2 import BACKGROUND_DARK
from src.gui.panels_v2.reprocess_panel_v2 import ReprocessPanelV2
from src.gui.views.review_tab_frame_v2 import ReviewTabFrame
from src.queue.job_history_store import JobHistoryEntry
from src.queue.job_model import JobStatus
from src.utils.image_metadata import ReadPayloadResult


@pytest.mark.gui
def test_reprocess_panel_is_launcher_only(tk_root: tk.Tk) -> None:
    panel = ReprocessPanelV2(tk_root)
    panel.pack(fill="both", expand=True)

    assert panel.open_review_button.cget("text") == "Open Review Workspace"
    assert not hasattr(panel, "select_images_button")
    assert not hasattr(panel, "reprocess_button")

    panel.destroy()


@pytest.mark.gui
def test_reprocess_panel_launcher_selects_review_tab_via_notebook(tk_root: tk.Tk) -> None:
    notebook = ttk.Notebook(tk_root)
    notebook.pack(fill="both", expand=True)
    pipeline_frame = ttk.Frame(notebook)
    review_frame = ttk.Frame(notebook)
    notebook.add(pipeline_frame, text="Pipeline")
    notebook.add(review_frame, text="Review")
    notebook.select(pipeline_frame)

    panel = ReprocessPanelV2(pipeline_frame)
    panel.pack(fill="both", expand=True)

    panel.open_review_button.invoke()

    assert notebook.tab(notebook.select(), "text") == "Review"

    panel.destroy()


@pytest.mark.gui
def test_reprocess_panel_prefers_controller_main_window_review_tab(tk_root: tk.Tk) -> None:
    notebook = ttk.Notebook(tk_root)
    notebook.pack(fill="both", expand=True)
    pipeline_frame = ttk.Frame(notebook)
    review_frame = ttk.Frame(notebook)
    notebook.add(pipeline_frame, text="Pipeline")
    notebook.add(review_frame, text="Review")
    notebook.select(pipeline_frame)

    controller = SimpleNamespace(
        main_window=SimpleNamespace(center_notebook=notebook, review_tab=review_frame)
    )
    panel = ReprocessPanelV2(pipeline_frame, controller=controller)
    panel.pack(fill="both", expand=True)

    panel.open_review_button.invoke()

    assert notebook.tab(notebook.select(), "text") == "Review"

    panel.destroy()


@pytest.mark.gui
def test_review_tab_marks_itself_as_canonical_reprocess_workspace(tk_root: tk.Tk) -> None:
    tab = ReviewTabFrame(tk_root)

    assert "canonical advanced reprocess" in tab.workflow_hint_label.cget("text").lower()
    assert "use learning" in tab.workflow_hint_label.cget("text").lower()

    tab.destroy()


@pytest.mark.gui
def test_review_tab_imports_selected_images_to_staged_curation(
    tk_root: tk.Tk, tmp_path: Path
) -> None:
    imported: list[tuple[list[str], str | None]] = []

    class _LearningController:
        def import_review_images_to_staged_curation(self, image_paths, *, display_name=None, source_label="review_tab"):
            imported.append((list(image_paths), display_name))
            return "curation-import-1"

    app_controller = SimpleNamespace(
        main_window=SimpleNamespace(
            learning_tab=SimpleNamespace(learning_controller=_LearningController())
        )
    )
    image_a = tmp_path / "a.png"
    image_b = tmp_path / "b.png"
    image_a.write_text("placeholder", encoding="utf-8")
    image_b.write_text("placeholder", encoding="utf-8")

    tab = ReviewTabFrame(tk_root, app_controller=app_controller)
    try:
        with pytest.MonkeyPatch.context() as mp:
            mp.setattr(tab.preview, "set_image_from_path", lambda path: None)
            mp.setattr(
                "src.gui.views.review_tab_frame_v2.extract_embedded_metadata",
                lambda _path: ReadPayloadResult(payload=None, status="missing"),
            )
            mp.setattr("src.gui.views.review_tab_frame_v2.messagebox.showinfo", lambda *args, **kwargs: None)
            mp.setattr("src.gui.views.review_tab_frame_v2.messagebox.showerror", lambda *args, **kwargs: None)
            mp.setattr("src.gui.views.review_tab_frame_v2.messagebox.showwarning", lambda *args, **kwargs: None)
            tab._set_selected_images([image_a, image_b])  # noqa: SLF001
            tab.images_list.selection_set(0, 1)
            tab._on_import_selected_to_staged_curation()  # noqa: SLF001
    finally:
        tab.destroy()

    assert imported
    assert imported[0][0] == [str(image_a), str(image_b)]
    assert imported[0][1] == "Review Import - 2 images"


@pytest.mark.gui
def test_review_tab_imports_selected_history_job_to_staged_curation(
    tk_root: tk.Tk, tmp_path: Path
) -> None:
    imported: list[str] = []

    class _LearningController:
        def import_history_entry_to_staged_curation(self, entry):
            imported.append(entry.job_id)
            return "curation-history-1"

    entry = JobHistoryEntry(
        job_id="history-1",
        created_at=datetime.utcnow(),
        status=JobStatus.COMPLETED,
        prompt_pack_id="History Pack",
        result={"output_dir": str(tmp_path)},
    )
    app_controller = SimpleNamespace(
        main_window=SimpleNamespace(
            learning_tab=SimpleNamespace(learning_controller=_LearningController())
        )
    )
    app_state = SimpleNamespace(history_items=[entry])

    tab = ReviewTabFrame(tk_root, app_controller=app_controller, app_state=app_state)
    try:
        with pytest.MonkeyPatch.context() as mp:
            mp.setattr("src.gui.views.review_tab_frame_v2.messagebox.showinfo", lambda *args, **kwargs: None)
            mp.setattr("src.gui.views.review_tab_frame_v2.messagebox.showerror", lambda *args, **kwargs: None)
            mp.setattr("src.gui.views.review_tab_frame_v2.messagebox.showwarning", lambda *args, **kwargs: None)
            picker = ttk.Treeview(tk_root, columns=("status", "pack", "job_id"), show="headings")
            picker.insert("", "end", iid="history-1", values=("completed", "History Pack", "history-1"))
            picker.selection_set("history-1")
            tab._import_selected_history_job(picker)  # noqa: SLF001
    finally:
        picker.destroy()
        tab.destroy()

    assert imported == ["history-1"]


@pytest.mark.gui
def test_review_tab_loads_staged_curation_handoff(tk_root: tk.Tk, tmp_path: Path) -> None:
    image_a = tmp_path / "review-a.png"
    image_b = tmp_path / "review-b.png"
    image_a.write_text("placeholder", encoding="utf-8")
    image_b.write_text("placeholder", encoding="utf-8")

    tab = ReviewTabFrame(tk_root)
    try:
        handoff = ReviewWorkspaceHandoff(
            source="staged_curation",
            workflow_title="Review Group",
            target_stage="face_triage",
            image_paths=[image_a, image_b],
            base_prompt="source prompt",
            base_negative_prompt="source negative",
            prompt_delta="",
            negative_prompt_delta="",
            prompt_mode="append",
            negative_prompt_mode="append",
            stage_img2img=False,
            stage_adetailer=True,
            stage_upscale=False,
            source_candidate_ids=["cand-1", "cand-2"],
        )
        with pytest.MonkeyPatch.context() as mp:
            mp.setattr(tab.preview, "set_image_from_path", lambda path: None)
            mp.setattr(
                "src.gui.views.review_tab_frame_v2.extract_embedded_metadata",
                lambda _path: ReadPayloadResult(payload=None, status="missing"),
            )
            tab.load_staged_curation_handoff(handoff)

        assert [str(path) for path in tab.selected_images] == [str(image_a), str(image_b)]
        assert tab.stage_img2img_var.get() is False
        assert tab.stage_adetailer_var.get() is True
        assert tab.stage_upscale_var.get() is False
        assert tab.current_prompt_text.get("1.0", "end-1c") == "source prompt"
        assert tab.current_negative_text.get("1.0", "end-1c") == "source negative"
        assert tab.prompt_text.get("1.0", "end-1c") == ""
        assert tab.negative_text.get("1.0", "end-1c") == ""
        assert "bulk throughput for the marked set" in tab.workflow_hint_label.cget("text").lower()
    finally:
        tab.destroy()


@pytest.mark.gui
def test_review_tab_shows_effective_reprocess_settings_summary(tk_root: tk.Tk, tmp_path: Path) -> None:
    image_path = tmp_path / "effective-summary.png"
    image_path.write_text("placeholder", encoding="utf-8")

    controller = SimpleNamespace(
        get_review_reprocess_effective_settings_preview=lambda **_kwargs: ReprocessEffectiveSettingsPreview(
            source_stage="txt2img",
            source_model="juggernautXL",
            source_vae="Automatic",
            target_stages=["adetailer"],
            positive_prompt_behavior="append",
            negative_prompt_behavior="inherited",
            stage_settings=[
                ReprocessStageSettingsPreview(
                    stage="adetailer",
                    sampler="DPM++ 2M Karras",
                    scheduler="Karras",
                    steps=12,
                    cfg_scale=5.7,
                    denoise=0.25,
                )
            ],
        )
    )

    tab = ReviewTabFrame(tk_root, app_controller=controller)
    try:
        handoff = ReviewWorkspaceHandoff(
            source="staged_curation",
            workflow_title="Review Group",
            target_stage="face_triage",
            image_paths=[image_path],
            base_prompt="source prompt",
            base_negative_prompt="source negative",
            prompt_delta="",
            negative_prompt_delta="",
            prompt_mode="append",
            negative_prompt_mode="append",
            stage_img2img=False,
            stage_adetailer=True,
            stage_upscale=False,
            source_candidate_ids=["cand-1"],
            direct_queue_preview=ReprocessEffectiveSettingsPreview(
                source_stage="txt2img",
                source_model="juggernautXL",
                source_vae="Automatic",
                target_stages=["adetailer"],
                positive_prompt_behavior="inherited",
                negative_prompt_behavior="inherited",
                stage_settings=[
                    ReprocessStageSettingsPreview(
                        stage="adetailer",
                        sampler="DPM++ 2M Karras",
                        scheduler="Karras",
                        steps=8,
                        cfg_scale=5.7,
                        denoise=0.34,
                    )
                ],
            ),
        )
        with pytest.MonkeyPatch.context() as mp:
            mp.setattr(tab.preview, "set_image_from_path", lambda path: None)
            mp.setattr(
                "src.gui.views.review_tab_frame_v2.extract_embedded_metadata",
                lambda _path: ReadPayloadResult(payload=None, status="missing"),
            )
            tab.load_staged_curation_handoff(handoff)

        summary = tab._effective_settings_var.get()  # noqa: SLF001
        assert "Source: stage=txt2img | model=juggernautXL | vae=Automatic" in summary
        assert "Targets: adetailer" in summary
        assert "Why these values are active:" in summary
        assert "Positive prompt: append [explicit edit]" in summary
        assert "Negative prompt: inherited [source artifact baseline]" in summary
        assert "adetailer | sampler=DPM++ 2M Karras [active resolution] | scheduler=Karras [active resolution] | steps=12 [active resolution] | cfg=5.7 [active resolution] | denoise=0.25 [active resolution]" in summary
        assert "Direct Queue Now baseline:" in summary
        assert "adetailer | sampler=DPM++ 2M Karras [active resolution] | scheduler=Karras [active resolution] | steps=8 [active resolution] | cfg=5.7 [active resolution] | denoise=0.34 [active resolution]" in summary
    finally:
        tab.destroy()


@pytest.mark.gui
def test_review_tab_surfaces_prior_review_summary_from_learning_controller(tk_root: tk.Tk, tmp_path: Path) -> None:
    image_path = tmp_path / "prior-review.png"
    image_path.write_text("placeholder", encoding="utf-8")

    learning_controller = SimpleNamespace(
        get_prior_review_summary=lambda _image_path: {
            "source_type": "embedded_review_metadata",
            "review_timestamp": "2026-03-23T12:00:00",
            "user_rating": 4,
            "quality_label": "good",
            "user_notes": "hands improved",
            "prompt_mode": "append",
        }
    )
    app_controller = SimpleNamespace(
        main_window=SimpleNamespace(
            learning_tab=SimpleNamespace(learning_controller=learning_controller)
        )
    )

    tab = ReviewTabFrame(tk_root, app_controller=app_controller)
    try:
        with pytest.MonkeyPatch.context() as mp:
            mp.setattr(tab.preview, "set_image_from_path", lambda path: None)
            mp.setattr(
                "src.gui.views.review_tab_frame_v2.extract_embedded_metadata",
                lambda _path: ReadPayloadResult(payload=None, status="missing"),
            )
            tab._set_selected_images([image_path])  # noqa: SLF001

        summary = tab._prior_review_summary_var.get()  # noqa: SLF001
        assert "embedded artifact metadata" in summary
        assert "Rating: 4 (good)" in summary
        assert "hands improved" in summary
        assert "Prompt change: append" in summary
    finally:
        tab.destroy()


@pytest.mark.gui
def test_review_tab_opens_metadata_inspector_for_selected_image(tk_root: tk.Tk, tmp_path: Path) -> None:
    image_path = tmp_path / "inspect.png"
    image_path.write_text("placeholder", encoding="utf-8")
    opened: list[dict[str, object]] = []

    learning_controller = SimpleNamespace(
        get_prior_review_summary=lambda _image_path: None,
        inspect_artifact_metadata=lambda _image_path: {
            "artifact_path": str(image_path),
            "normalized_generation_summary": {"stage": "txt2img"},
            "normalized_review_summary": {"user_rating": 4},
            "source_diagnostics": {"active_review_precedence": "embedded_review_metadata"},
            "raw_embedded_payload": {"stage": "txt2img"},
            "raw_embedded_review_payload": {"user_rating": 4},
            "raw_sidecar_review_payload": None,
            "raw_internal_review_summary": None,
        },
    )
    app_controller = SimpleNamespace(
        main_window=SimpleNamespace(learning_tab=SimpleNamespace(learning_controller=learning_controller))
    )

    tab = ReviewTabFrame(tk_root, app_controller=app_controller)
    try:
        with pytest.MonkeyPatch.context() as mp:
            mp.setattr(tab.preview, "set_image_from_path", lambda path: None)
            mp.setattr(
                "src.gui.views.review_tab_frame_v2.extract_embedded_metadata",
                lambda _path: ReadPayloadResult(payload=None, status="missing"),
            )
            mp.setattr(
                "src.gui.views.review_tab_frame_v2.ArtifactMetadataInspectorDialog",
                lambda parent, *, inspection_payload, on_refresh=None: opened.append(inspection_payload),
            )
            tab._set_selected_images([image_path])  # noqa: SLF001
            tab._open_metadata_inspector()  # noqa: SLF001

        assert len(opened) == 1
        assert opened[0]["artifact_path"] == str(image_path)
    finally:
        tab.destroy()


@pytest.mark.gui
def test_review_tab_can_open_latest_derived_compare_from_staged_candidate(
    tk_root: tk.Tk, tmp_path: Path
) -> None:
    source_image = tmp_path / "source.png"
    derived_image = tmp_path / "derived.png"
    source_image.write_text("placeholder", encoding="utf-8")
    derived_image.write_text("placeholder", encoding="utf-8")

    learning_controller = SimpleNamespace(
        get_staged_curation_candidate_latest_descendant=lambda candidate_id: {
            "artifact_path": str(derived_image),
            "target_stage": "face_triage",
            "candidate_id": candidate_id,
        }
    )
    app_controller = SimpleNamespace(
        main_window=SimpleNamespace(
            learning_tab=SimpleNamespace(learning_controller=learning_controller)
        )
    )
    tab = ReviewTabFrame(tk_root, app_controller=app_controller)
    rendered: list[tuple[str, str | None, str]] = []
    try:
        with pytest.MonkeyPatch.context() as mp:
            mp.setattr(tab.preview, "set_image_from_path", lambda path: None)
            mp.setattr(
                "src.gui.views.review_tab_frame_v2.extract_embedded_metadata",
                lambda _path: ReadPayloadResult(payload=None, status="missing"),
            )
            mp.setattr(
                tab,
                "_render_compare_viewer",
                lambda image_path, *, secondary_path=None, title_prefix="Large Compare": rendered.append(
                    (str(image_path), str(secondary_path) if secondary_path is not None else None, title_prefix)
                ),
            )

            opened = tab.open_staged_candidate_latest_derived_compare(
                image_path=source_image,
                candidate_id="cand-1",
                workflow_title="Group A",
            )
    finally:
        tab.destroy()

    assert opened is True
    assert rendered == [
        (str(source_image), str(derived_image), "Source vs Latest Derived (face triage)")
    ]


@pytest.mark.gui
def test_review_tab_history_import_picker_uses_themed_popup(tk_root: tk.Tk) -> None:
    entry = SimpleNamespace(
        job_id="job-1",
        status=SimpleNamespace(value="completed"),
        prompt_pack_id="Pack A",
        payload_summary="",
    )
    tab = ReviewTabFrame(tk_root, app_state=SimpleNamespace(history_items=[entry]))
    try:
        tab._on_open_history_import_picker()  # noqa: SLF001
        assert tab._history_import_window is not None  # noqa: SLF001
        assert tab._history_import_window.cget("bg") == BACKGROUND_DARK  # noqa: SLF001
    finally:
        if tab._history_import_window is not None and tab._history_import_window.winfo_exists():  # noqa: SLF001
            tab._history_import_window.destroy()  # noqa: SLF001
        tab.destroy()
