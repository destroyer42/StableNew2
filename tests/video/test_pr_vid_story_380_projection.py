"""PR-VID-STORY-380 B1: the read-only projection of takes from the repository."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Any

from src.queue.job_model import JobStatus
from src.video.sequence_ledger import BASIS_NATIVE, FileRecord
from src.video.sequence_plan import ROOT_PARENT
from src.video.storyboard_cut import take_manifest, write_cut_manifest
from src.video.storyboard_projection import (
    PROBLEM_PREFIX,
    first_missing_frame,
    project_storyboard,
)
from src.video.storyboard_tree import StoryboardTree, Take, TreeRoot

NOW = "2026-11-21T10:00:00+00:00"
STATUS = {
    "queued": JobStatus.QUEUED,
    "running": JobStatus.RUNNING,
    "completed": JobStatus.COMPLETED,
    "failed": JobStatus.FAILED,
    "cancelled": JobStatus.CANCELLED,
}


class _Repo:
    def __init__(self, entries: dict[str, Any]) -> None:
        self.entries = entries
        self.reads: list[list[str]] = []

    def get_job_entries(self, job_ids: Any) -> dict[str, Any]:
        self.reads.append(list(job_ids))
        return {job: self.entries[job] for job in job_ids if job in self.entries}


def _root() -> TreeRoot:
    return TreeRoot(
        kind="clip", job_id="j0", image_path="", image_sha256="", manifest_path="", manifest_sha256="",
        settings=(), fps=16, width=8, height=8, smoothing_text="",
    )


def _take(take_id: str, attempts: tuple[str, ...] = (), segment_index: int = 0) -> Take:
    return Take(
        take_id=take_id, parent_id=ROOT_PARENT, handoff_index=1, mode="parallel", batch_id="b",
        chain_position=0, segment_index=segment_index, prompt="p", negative_prompt="", seed_intent="",
        attempts=attempts, replay_of=None, mark="none", created_at=NOW,
    )


def _tree(*takes: Take) -> StoryboardTree:
    tree = StoryboardTree.new("t", _root())
    for take in takes:
        tree = tree.with_take(take)
    return tree


def _frames(tmp_path: Path, count: int = 3) -> list[FileRecord]:
    records = []
    for index in range(count):
        path = tmp_path / f"frame_{index:04d}.png"
        path.write_bytes(bytes([index]) * 4)
        records.append(FileRecord.of(path))
    return records


def _result(
    tmp_path: Path, take_id: str, *, mp4: bool, frames: list[FileRecord] | None = None, job_id: str = "j1"
) -> dict[str, Any]:
    records = frames if frames is not None else _frames(tmp_path)
    manifest = take_manifest(
        lead_in=None, segments=[(take_id, records, 0, BASIS_NATIVE)], fps=16, width=8, height=8, job_id=job_id
    )
    reference = write_cut_manifest(tmp_path / f"{take_id}_cut.json", manifest)
    video = tmp_path / f"{take_id}.mp4"
    if mp4:
        video.write_bytes(b"mp4")
    clip = tmp_path / f"{take_id}_clip.mp4"
    return {
        "metadata": {
            "sequence_artifact": {
                "cut_manifest": {"path": reference.path, "sha256": reference.sha256},
                "assembled_video": {"output_path": str(video)},
                "segment_provenance": [{"segment_index": 0, "primary_output_path": str(clip)}],
            }
        }
    }


def _entry(state: str, result: Any = None) -> Any:
    return SimpleNamespace(status=STATUS[state], result=result)


def test_states_and_progress_text(tmp_path):
    entries = {
        "j1": _entry("queued"),
        "j2": _entry("running"),
        "j3": _entry("completed"),
        "j4": _entry("failed"),
        "j5": _entry("cancelled"),
    }
    takes = [_take(f"t{n}", (f"j{n}",)) for n in range(1, 6)]
    views = project_storyboard(
        _tree(*takes), _Repo(entries), output_roots=[str(tmp_path)], check_frames=lambda m: None
    )
    assert [v.state for v in views.values()] == ["queued", "running", "completed", "failed", "cancelled"]
    assert views["t1"].status_text == "queued" and views["t3"].status_text == "completed"


def test_running_progress_reads_the_ledger(tmp_path, monkeypatch):
    from src.video import storyboard_projection as module

    fake = SimpleNamespace(job_id="j2", total_segments=4, completed_prefix=1, cut_manifest=None, assembly=None, segments=[])
    monkeypatch.setattr(module, "read_ledger", lambda path: fake)
    monkeypatch.setattr(module, "locate_ledger", lambda job_id, roots: str(tmp_path / "x.json"))
    views = project_storyboard(
        _tree(_take("t1", ("j2",))), _Repo({"j2": _entry("running")}),
        output_roots=[str(tmp_path)], check_frames=lambda m: None,
    )
    assert views["t1"].status_text == "running segment 2 of 4"


def test_projection_reports_not_encoded_with_manifest(tmp_path):
    result = _result(tmp_path, "t1", mp4=False)
    views = project_storyboard(
        _tree(_take("t1", ("j1",))), _Repo({"j1": _entry("cancelled", result)}),
        output_roots=[str(tmp_path)], check_frames=lambda m: None,
    )
    view = views["t1"]
    assert view.manifest is not None and not view.encoded and view.can_resume and view.frames_ok
    assert view.clip_path is not None and view.clip_path.endswith("t1_clip.mp4")


def test_projection_flags_missing_parent_frames_but_keeps_the_mp4(tmp_path):
    result = _result(tmp_path, "t1", mp4=True)
    (tmp_path / "frame_0001.png").unlink()
    views = project_storyboard(
        _tree(_take("t1", ("j1",))), _Repo({"j1": _entry("completed", result)}),
        output_roots=[str(tmp_path)], check_frames=first_missing_frame,
    )
    view = views["t1"]
    assert not view.frames_ok and view.problem.startswith(PROBLEM_PREFIX)
    assert "frame_0001.png" in view.problem
    assert view.stitched_path is not None and view.encoded


def test_changed_manifest_is_reported_not_raised(tmp_path):
    result = _result(tmp_path, "t1", mp4=True)
    manifest_path = Path(result["metadata"]["sequence_artifact"]["cut_manifest"]["path"])
    manifest_path.write_text(manifest_path.read_text(encoding="utf-8") + " ", encoding="utf-8")
    view = project_storyboard(
        _tree(_take("t1", ("j1",))), _Repo({"j1": _entry("completed", result)}),
        output_roots=[], check_frames=first_missing_frame,
    )["t1"]
    assert not view.frames_ok and view.problem.startswith(PROBLEM_PREFIX) and view.manifest is None


def test_pending_take_has_no_job(tmp_path):
    repo = _Repo({})
    view = project_storyboard(
        _tree(_take("t1", ())), repo, output_roots=[], check_frames=lambda m: None
    )["t1"]
    assert view.state == "pending" and view.shown_job_id is None and repo.reads == []


def test_newest_completed_attempt_is_shown(tmp_path):
    entries = {
        "old": _entry("completed", _result(tmp_path, "t1", mp4=True, job_id="old")),
        "new": _entry("failed"),
    }
    view = project_storyboard(
        _tree(_take("t1", ("old", "new"))), _Repo(entries),
        output_roots=[], check_frames=lambda m: None,
    )["t1"]
    assert view.shown_job_id == "old" and view.state == "completed"
    # with no completed attempt the newest one shows
    view = project_storyboard(
        _tree(_take("t1", ("old", "new"))), _Repo({"old": _entry("failed"), "new": _entry("queued")}),
        output_roots=[], check_frames=lambda m: None,
    )["t1"]
    assert view.shown_job_id == "new" and view.state == "queued"


def test_chain_middle_take_shares_the_chain_file(tmp_path):
    records = _frames(tmp_path, 4)
    manifest = take_manifest(
        lead_in=None,
        segments=[("c1", records[:2], 0, BASIS_NATIVE), ("c2", records[2:], 0, BASIS_NATIVE)],
        fps=16, width=8, height=8, job_id="j1",
    )
    reference = write_cut_manifest(tmp_path / "chain.json", manifest)
    video = tmp_path / "chain.mp4"
    video.write_bytes(b"x")
    result = {
        "metadata": {
            "sequence_artifact": {
                "cut_manifest": {"path": reference.path, "sha256": reference.sha256},
                "assembled_video": {"output_path": str(video)},
            }
        }
    }
    tree = _tree(_take("c1", ("j1",), 0), _take("c2", ("j1",), 1))
    views = project_storyboard(
        tree, _Repo({"j1": _entry("completed", result)}), output_roots=[], check_frames=first_missing_frame
    )
    assert views["c1"].stitched_path == views["c2"].stitched_path == str(video)
