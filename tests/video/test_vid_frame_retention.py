"""VID-FRAME: PNG frames are removed a day after their clip exists, and nothing that is still needed is."""

from __future__ import annotations

import json
import os
import time
from pathlib import Path

from src.video.frame_retention import MARKER_NAME, frames_were_removed, sweep_retained_frames

NOW = time.time()
OLD = NOW - 2 * 86_400


def _run(root: Path, name: str = "run1", *, count: int = 5, age: float = OLD) -> Path:
    run = root / "movie_clips" / name
    (run / "manifests").mkdir(parents=True)
    frames = []
    for number in range(1, count + 1):
        frame = run / f"clip_{number:05d}_.png"
        frame.write_bytes(b"png")
        frames.append(str(frame))
    clip = run / "clip.mp4"
    clip.write_bytes(b"mp4")
    os.utime(clip, (age, age))
    manifest = {
        "frames_out": {"video_path": str(clip), "frame_paths": frames},
        "frame_paths": frames,
        "output_paths": [str(clip)],
        "video_paths": [str(clip)],
        "artifact": {"primary_path": str(clip), "output_paths": [str(clip)]},
    }
    (run / "manifests" / "clip.json").write_text(json.dumps(manifest), encoding="utf-8")
    return run


def _names(run: Path) -> list[str]:
    return sorted(path.name for path in run.glob("*.png"))


def _sweep(root: Path, tree_root: Path | None = None, **kwargs):
    return sweep_retained_frames(root, now=NOW, tree_root=tree_root or root / "no_trees", **kwargs)


def test_old_frames_go_and_the_clip_first_and_last_frame_stay(tmp_path: Path) -> None:
    run = _run(tmp_path)

    result = _sweep(tmp_path)

    assert _names(run) == ["clip_00001_.png", "clip_00005_.png"]
    assert (run / "clip.mp4").is_file() and (run / "manifests" / "clip.json").is_file()
    assert (result.frames, result.runs, result.refused) == (3, 1, "")
    assert frames_were_removed(run) and (run / MARKER_NAME).is_file()
    assert _sweep(tmp_path).frames == 0  # a second sweep finds nothing


def test_a_dry_run_counts_the_same_frames_and_touches_nothing(tmp_path: Path) -> None:
    run = _run(tmp_path)

    counted = _sweep(tmp_path, dry_run=True)

    assert (counted.frames, counted.bytes, counted.runs) == (3, 9, 1)
    assert len(_names(run)) == 5 and not frames_were_removed(run)


def test_a_young_a_missing_or_an_empty_clip_keeps_every_frame(tmp_path: Path) -> None:
    young = _run(tmp_path, "young", age=NOW - 3600)
    gone = _run(tmp_path, "gone")
    (gone / "clip.mp4").unlink()
    empty = _run(tmp_path, "empty")
    (empty / "clip.mp4").write_bytes(b"")
    os.utime(empty / "clip.mp4", (OLD, OLD))

    assert _sweep(tmp_path).frames == 0
    assert all(len(_names(run)) == 5 for run in (young, gone, empty))


def test_a_png_the_job_names_as_an_output_is_never_deleted(tmp_path: Path) -> None:
    run = _run(tmp_path)
    manifest = run / "manifests" / "clip.json"
    data = json.loads(manifest.read_text(encoding="utf-8"))
    data["artifact"]["output_paths"].append(str(run / "clip_00003_.png"))
    manifest.write_text(json.dumps(data), encoding="utf-8")

    _sweep(tmp_path)

    assert "clip_00003_.png" in _names(run) and "clip_00002_.png" not in _names(run)


def test_unlisted_files_and_paths_outside_the_run_folder_are_left_alone(tmp_path: Path) -> None:
    run = _run(tmp_path)
    mine = run / "keeper.png"
    mine.write_bytes(b"png")
    elsewhere = tmp_path / "images"
    elsewhere.mkdir()
    outside = elsewhere / "clip_00002_.png"
    outside.write_bytes(b"png")
    manifest = run / "manifests" / "clip.json"
    data = json.loads(manifest.read_text(encoding="utf-8"))
    data["frames_out"]["frame_paths"][1] = str(outside)
    manifest.write_text(json.dumps(data), encoding="utf-8")

    _sweep(tmp_path)

    assert mine.is_file() and outside.is_file()


def test_frames_a_cut_manifest_names_are_kept(tmp_path: Path) -> None:
    run = _run(tmp_path)
    cut = tmp_path / "storyboards" / "s1" / "root" / "root_cut.json"
    cut.parent.mkdir(parents=True)
    cut.write_text(
        json.dumps(
            {
                "schema": "stablenew.storyboard_cut.v1",
                "frames": [{"path": str(run / "clip_00003_.png"), "sha256": "0" * 64}],
            }
        ),
        encoding="utf-8",
    )

    _sweep(tmp_path)

    assert _names(run) == ["clip_00001_.png", "clip_00003_.png", "clip_00005_.png"]


def test_a_frame_a_storyboard_starts_from_is_kept(tmp_path: Path) -> None:
    run = _run(tmp_path / "out")
    trees = tmp_path / "trees"
    trees.mkdir()
    tree = {"root": {"image_path": str(run / "clip_00002_.png"), "manifest_path": ""}}
    (trees / "abc.json").write_text(json.dumps(tree), encoding="utf-8")

    _sweep(tmp_path / "out", trees)

    assert "clip_00002_.png" in _names(run) and "clip_00003_.png" not in _names(run)


def test_an_unreadable_cut_manifest_stops_the_whole_sweep(tmp_path: Path) -> None:
    run = _run(tmp_path)
    cut = tmp_path / "storyboards" / "s1" / "root" / "root_cut.json"
    cut.parent.mkdir(parents=True)
    cut.write_text("{broken", encoding="utf-8")

    result = _sweep(tmp_path)

    assert result.frames == 0 and "root_cut.json" in result.refused and len(_names(run)) == 5


def test_an_unreadable_storyboard_file_stops_the_whole_sweep(tmp_path: Path) -> None:
    run = _run(tmp_path / "out")
    trees = tmp_path / "trees"
    trees.mkdir()
    (trees / "abc.json").write_text("{broken", encoding="utf-8")

    result = _sweep(tmp_path / "out", trees)

    assert result.frames == 0 and "abc.json" in result.refused and len(_names(run)) == 5


def test_sequence_runs_evaluations_and_the_archive_are_skipped(tmp_path: Path) -> None:
    sequence = _run(tmp_path, "sequence")
    (sequence / "sequence_state.json").write_text("{}", encoding="utf-8")
    evaluation = _run(tmp_path / "video_eval", "e")
    archived = _run(tmp_path / "_archive", "a")

    assert _sweep(tmp_path).frames == 0
    assert all(len(_names(run)) == 5 for run in (sequence, evaluation, archived))


def test_the_sweep_stops_when_asked(tmp_path: Path) -> None:
    run = _run(tmp_path)

    assert _sweep(tmp_path, should_stop=lambda: True).frames == 0
    assert len(_names(run)) == 5
