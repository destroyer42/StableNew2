"""PR-VID-MOTION-LIB-353 test harness: temporary libraries, scripted inspection and disposable clips.

A library lives under ``tmp_path``.  ``fake_inspector`` answers the way the bounded FFprobe helper would
without starting any process; ``make_clip`` generates a tiny real clip with CPU-only FFmpeg ``testsrc``.
Nothing here starts a runtime, a model or a GPU.
"""

from __future__ import annotations

import io
import subprocess
import threading
from pathlib import Path

import pytest
from PIL import Image

from src.pipeline.video import resolve_ffmpeg_executable
from src.video.container_metadata import resolve_ffprobe_executable
from src.video.driving_video_inspection import (
    STATUS_FAILED,
    STATUS_OK,
    DrivingVideoFacts,
    DrivingVideoInspection,
    InspectionIssue,
    PreviewFrame,
)
from src.video.motion_library.store import MotionLibraryStore

FFMPEG = resolve_ffmpeg_executable()
FFPROBE = resolve_ffprobe_executable()
needs_ffmpeg = pytest.mark.skipif(
    FFMPEG is None or FFPROBE is None, reason="FFmpeg/FFprobe are not installed"
)


def png_bytes(color: str = "navy", size: tuple[int, int] = (16, 12)) -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", size, color).save(buffer, format="PNG")
    return buffer.getvalue()


def facts(
    *,
    width: int = 64,
    height: int = 48,
    fps: float = 24.0,
    frames: int = 24,
    seconds: float = 1.0,
) -> DrivingVideoFacts:
    return DrivingVideoFacts(
        container_format="mov,mp4",
        codec_name="h264",
        pixel_format="yuv420p",
        coded_width=width,
        coded_height=height,
        rotation_quadrants=0,
        display_width=width,
        display_height=height,
        sample_aspect_ratio="",
        reported_fps=fps,
        fps_basis="average",
        fps_is_variable_suspected=False,
        reported_frame_count=frames,
        estimated_frame_count=None,
        frame_count_basis="reported",
        duration_seconds=seconds,
        duration_basis="stream",
        fps_rational=f"{int(fps)}/1",
    )


class FakeInspector:
    """Scripted ``inspect(path, cancel)``; counts calls so a test can prove nothing was decoded."""

    def __init__(
        self,
        result: DrivingVideoFacts | None = None,
        *,
        failure: str = "",
        frames: int = 3,
    ) -> None:
        self.facts = result if result is not None else facts()
        self.failure = failure
        self.frame_total = frames
        self.calls: list[str] = []

    def __call__(self, path: Path, cancel: threading.Event | None = None) -> DrivingVideoInspection:
        self.calls.append(str(path))
        if self.failure:
            return DrivingVideoInspection(
                path=str(path),
                status=STATUS_FAILED,
                issues=(InspectionIssue("probe_failed", self.failure),),
            )
        colors = ("red", "green", "blue")
        frames = tuple(
            PreviewFrame(
                position_seconds=float(i), width=16, height=12, png_bytes=png_bytes(colors[i % 3])
            )
            for i in range(self.frame_total)
        )
        return DrivingVideoInspection(
            path=str(path), status=STATUS_OK, facts=self.facts, frames=frames
        )


def new_store(tmp_path: Path, name: str = "library", **kwargs) -> MotionLibraryStore:
    return MotionLibraryStore(tmp_path / name, **kwargs)


def write_clip(path: Path, payload: bytes = b"clip-bytes-A") -> Path:
    """A placeholder ``.mp4`` for tests that script the inspector (never decoded)."""

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"\x00\x00\x00\x18ftypmp42" + payload)
    return path


def make_clip(
    tmp_path: Path,
    name: str = "walk.mp4",
    *,
    frames: int = 24,
    rate: int = 24,
    size: str = "64x48",
) -> Path:
    """A real, tiny H.264 clip generated on the CPU."""

    assert FFMPEG is not None
    path = tmp_path / name
    path.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        [str(FFMPEG), "-v", "error", "-y", "-f", "lavfi", "-i", f"testsrc=size={size}:rate={rate}",
         "-frames:v", str(frames), "-pix_fmt", "yuv420p", "-c:v", "libx264", str(path)],
        check=True, capture_output=True, timeout=120,
    )  # fmt: skip
    return path


def make_ports(
    store: MotionLibraryStore, inspector: FakeInspector | None = None, workflows: dict | None = None
):
    """``MotionLibraryPorts`` over a real store and a scripted inspector -- what the controller supplies in the app."""

    from src.gui.view_contracts.motion_library_contract import MotionLibraryPorts
    from src.video.motion_library.handoff import plan_driving_handoff
    from src.video.motion_library.importer import import_folder, import_video
    from src.video.motion_library.relink import relink_asset
    from src.video.motion_library.snapshot import build_snapshot

    scripted = inspector or FakeInspector()
    catalog = workflows or {}

    def snapshot():
        store.reload()
        return build_snapshot(store)

    return MotionLibraryPorts(
        snapshot=snapshot,
        inspect=lambda asset_id, cancel: scripted(
            store.asset_path(store.require(asset_id)), cancel
        ),
        import_file=lambda path, mode, notes, cancel: import_video(
            store, path, mode=mode, annotations=notes, inspect=scripted, cancel=cancel
        ),
        import_folder=lambda folder, mode, notes, cancel: import_folder(
            store, folder, mode=mode, annotations=notes, inspect=scripted, cancel=cancel
        ),
        annotate=lambda asset_id, changes: store.annotate(asset_id, changes),
        relink=lambda asset_id, path, cancel: relink_asset(store, asset_id, path, cancel=cancel),
        configure=lambda root: None,
        plan_handoff=lambda asset_id, workflow_id, version, cancel: plan_driving_handoff(
            store, asset_id, catalog.get(workflow_id), cancel=cancel
        ),
    )


DRIVING_WORKFLOW = {
    "workflow_id": "driving_wf",
    "workflow_version": "1.0.0",
    "display_name": "Driving Workflow",
    "motion_readiness": {
        "accepts_driving_video": True,
        "driving_frame_consumption": {"verified": False},
    },
}
STILL_WORKFLOW = {
    "workflow_id": "still_wf",
    "workflow_version": "1.0.0",
    "display_name": "Still Workflow",
    "motion_readiness": {"accepts_driving_video": False},
}
