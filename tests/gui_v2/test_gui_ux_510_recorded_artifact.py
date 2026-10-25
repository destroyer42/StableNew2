"""GUI-UX-510: recorded media identity and History playback without real FFmpeg/WebUI."""

from __future__ import annotations

import tkinter as tk
from pathlib import Path
from tkinter import ttk

import pytest

from src.gui.app_state_v2 import AppStateV2
from src.gui.job_history_panel_v2 import JobHistoryPanelV2
from src.gui.view_contracts.history_artifact_contract import resolve_recorded_artifact
from src.queue.job_history_store import JobHistoryEntry, JobStatus
from src.utils.os_shell import ShellResult


def _entry(job_id: str, result: dict) -> JobHistoryEntry:
    return JobHistoryEntry(
        job_id=job_id,
        created_at="2026-10-22T00:00:00",
        status=JobStatus.COMPLETED,
        payload_summary="Recorded output",
        result=result,
    )


def test_video_bundle_wins_over_direct_image_and_poster(tmp_path: Path) -> None:
    clip = tmp_path / "clip.mp4"
    image = tmp_path / "frame.png"
    clip.touch()
    image.touch()
    result = {
        "artifact": {"artifact_type": "image", "primary_path": str(image)},
        "video_bundle": {
            "artifact_type": "video",
            "primary_path": str(clip),
            "thumbnail_path": str(image),
            "output_paths": [str(clip)],
        },
    }
    assert resolve_recorded_artifact(result).kind == "video"
    assert resolve_recorded_artifact(result).path == str(clip)


def test_missing_recorded_clip_never_falls_back_to_poster(tmp_path: Path) -> None:
    poster = tmp_path / "frame.png"
    poster.touch()
    result = {
        "video_bundle": {
            "primary_path": str(tmp_path / "missing.mp4"),
            "thumbnail_path": str(poster),
        }
    }
    selected = resolve_recorded_artifact(result)
    assert selected.kind == "video"
    assert selected.path is None
    assert "missing" in selected.message.lower()


@pytest.mark.parametrize(
    "result_key",
    ("video_primary_artifact", "movie_assembly_artifact", "svd_native_artifact"),
)
def test_video_metadata_formats_are_playable(tmp_path: Path, result_key: str) -> None:
    clip = tmp_path / "recorded.mp4"
    clip.touch()
    selected = resolve_recorded_artifact(
        {"metadata": {result_key: {"primary_path": str(clip), "artifact_type": "video"}}}
    )
    assert selected.kind == "video"
    assert selected.path == str(clip)


def test_video_aggregate_and_variant_formats(tmp_path: Path) -> None:
    clip = tmp_path / "clip.webm"
    clip.touch()
    for result in (
        {"metadata": {"video_artifacts": {"wan": {"output_paths": [str(clip)]}}}},
        {"variants": [{"stage": "video_workflow", "artifact": {"primary_path": str(clip)}}]},
        {"artifact": {"artifact_type": "video", "primary_path": str(clip)}},
    ):
        assert resolve_recorded_artifact(result).path == str(clip)


def test_frames_only_are_not_passed_to_video_decoder(tmp_path: Path) -> None:
    frame = tmp_path / "frame_0001.png"
    frame.touch()
    chosen = resolve_recorded_artifact(
        {"video_bundle": {"artifact_type": "video", "frame_paths": [str(frame)]}}
    )
    assert chosen.kind == "frames"
    assert chosen.path is None
    assert "frames" in chosen.message


def test_legacy_image_is_still_shown_and_empty_record_is_explained(tmp_path: Path) -> None:
    image = tmp_path / "image.png"
    image.touch()
    result = {"variants": [{"artifact": {"artifact_type": "image", "output_paths": [str(image)]}}]}
    assert resolve_recorded_artifact(result).path == str(image)
    assert resolve_recorded_artifact(result).kind == "image"
    assert resolve_recorded_artifact({}).kind == "none"


@pytest.mark.gui
def test_history_shows_video_not_poster_and_reuses_player_on_selection(
    tk_root: tk.Misc, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import src.gui.job_history_panel_v2 as history_module

    players: list[object] = []

    class FakeVideoPreview(ttk.Frame):
        def __init__(
            self, parent: tk.Misc, *, edge: int, show_control: bool = True, shown_var=None
        ) -> None:
            super().__init__(parent)
            self.shown: list[str] = []
            self.stop_count = 0
            players.append(self)

        def show(self, path: str) -> None:
            self.shown.append(path)

        def stop(self) -> None:
            self.stop_count += 1

        def set_visibility(self, shown: bool) -> None:
            self.visible = shown

    monkeypatch.setattr(history_module, "VideoPreviewWidget", FakeVideoPreview)
    panel = JobHistoryPanelV2(tk_root, app_state=AppStateV2())
    clip = tmp_path / "motion.mp4"
    poster = tmp_path / "frame.png"
    image = tmp_path / "still.png"
    for path in (clip, poster, image):
        path.touch()

    video = _entry(
        "video", {"video_bundle": {"primary_path": str(clip), "thumbnail_path": str(poster)}}
    )
    still = _entry("image", {"artifact": {"artifact_type": "image", "primary_path": str(image)}})
    seen_images: list[str] = []
    monkeypatch.setattr(
        panel.artifact_thumbnail, "set_image_from_path", lambda path: seen_images.append(str(path))
    )
    panel.show_artifact_var.set(True)
    panel._refresh_selected_artifact(video)
    assert len(players) == 1
    assert players[0].shown == [str(clip)]
    assert seen_images == []
    assert panel._shown_artifact_path == str(clip)
    panel._refresh_selected_artifact(video)
    assert players[0].shown == [str(clip)]  # repeated refresh does not decode twice

    opened: list[str] = []
    revealed: list[str] = []
    monkeypatch.setattr(
        history_module, "open_file", lambda path: opened.append(path) or ShellResult(True)
    )
    monkeypatch.setattr(
        history_module,
        "reveal_in_file_manager",
        lambda path: revealed.append(path) or ShellResult(True),
    )
    panel._on_open_artifact()
    panel._on_reveal_artifact()
    assert opened == [str(clip)]
    assert revealed == [str(clip)]

    panel._refresh_selected_artifact(still)
    assert players[0].stop_count >= 1
    assert seen_images == [str(image)]
    panel.show_artifact_var.set(False)
    panel._refresh_selected_artifact(still)
    assert panel._shown_artifact_path is None
    assert not panel.artifact_frame.winfo_manager()


@pytest.mark.gui
def test_history_reports_missing_video_and_disables_open(
    tk_root: tk.Misc, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    panel = JobHistoryPanelV2(tk_root, app_state=AppStateV2())
    poster = tmp_path / "poster.png"
    poster.touch()
    entry = _entry(
        "missing",
        {
            "video_bundle": {
                "primary_path": str(tmp_path / "missing.mp4"),
                "thumbnail_path": str(poster),
            }
        },
    )
    seen: list[str] = []
    monkeypatch.setattr(
        panel.artifact_thumbnail, "set_image_from_path", lambda path: seen.append(str(path))
    )
    panel.show_artifact_var.set(True)
    panel._refresh_selected_artifact(entry)
    assert seen == []
    assert "missing" in panel.artifact_status_var.get().lower()
    assert panel.artifact_open_btn.instate(["disabled"])
    assert panel.artifact_reveal_btn.instate(["disabled"])
    assert panel.artifact_video_preview is None
