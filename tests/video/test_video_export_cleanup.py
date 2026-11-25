"""Scratch-frame cleanup must not fail an export that already succeeded (WinError 32)."""

from __future__ import annotations

from PIL import Image

from src.video import video_export


class _LockingCreator:
    ffmpeg_available = True
    handle = None

    def create_video_from_images(self, *, image_paths, output_path, **_kwargs):
        # Hold a frame open the way a scanner/indexer would; on Windows this blocks deletion.
        type(self).handle = open(image_paths[-1], "rb")
        output_path.write_bytes(b"mp4")
        return True


def test_export_video_mp4_survives_locked_scratch_frame(tmp_path, monkeypatch):
    monkeypatch.setattr(video_export, "VideoCreator", _LockingCreator)
    out = tmp_path / "clip.mp4"
    try:
        result = video_export.export_video_mp4(
            frames=[Image.new("RGB", (8, 8)) for _ in range(3)], output_path=out, fps=16
        )
    finally:
        if _LockingCreator.handle is not None:
            _LockingCreator.handle.close()
    assert result == out and out.read_bytes() == b"mp4"
