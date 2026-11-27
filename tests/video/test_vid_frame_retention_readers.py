"""VID-FRAME: what read a clip's frames keeps working after retention removed them."""

from __future__ import annotations

import json
from pathlib import Path

from src.gui.view_contracts.movie_clips_contract import extract_source_paths_from_bundle
from src.video.frame_retention import MARKER_NAME
from src.video.storyboard_cut import BASIS_DECODED, read_cut_manifest
from src.video.storyboard_root import prepare_clip_root
from tests.helpers.storyboard_380 import REG, frames_out_job, png, remove


def _sweep_like(frames: list[Path]) -> None:
    remove(frames[1:-1])
    (frames[0].parent / MARKER_NAME).write_text(json.dumps({"frames": []}), encoding="utf-8")


def test_a_storyboard_root_decodes_the_clip_when_its_frames_were_removed(tmp_path: Path) -> None:
    repo, job_id, frames = frames_out_job(tmp_path, count=17, smoothed_fps=32)
    _sweep_like(frames)
    decoded: list[Path] = []

    def decode(clip: Path, folder: Path, cancel_token=None) -> list[Path]:
        decoded.append(clip)
        return [png(folder / f"decoded_{n:05d}.png", (832, 480), (n, n, n)) for n in range(17)]

    root = prepare_clip_root(
        repository=repo,
        job_id=job_id,
        storyboard_id="after_retention",
        output_root=tmp_path,
        registry=REG,
        decode_clip=decode,
    )

    manifest = read_cut_manifest(root.manifest.path)
    assert len(manifest.frames) == 17 and manifest.ranges[0].basis == BASIS_DECODED
    assert decoded and "smooth" not in decoded[0].name


def test_movie_clips_takes_the_clip_once_the_frames_are_removed(tmp_path: Path) -> None:
    frames = [str(png(tmp_path / f"f_{n}.png", (8, 8), (n, n, n))) for n in range(3)]
    bundle = {
        "frame_paths": frames,
        "primary_path": str(tmp_path / "clip_smooth.mp4"),
        "output_paths": [str(tmp_path / "clip_smooth.mp4"), str(tmp_path / "clip.mp4")],
    }
    assert extract_source_paths_from_bundle(bundle) == frames

    (tmp_path / MARKER_NAME).write_text("{}", encoding="utf-8")

    assert extract_source_paths_from_bundle(bundle) == [str(tmp_path / "clip_smooth.mp4")]
