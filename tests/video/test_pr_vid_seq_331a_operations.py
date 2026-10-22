"""PR-VID-SEQ-331A: shots to intent, ledger location, and what Job History shows for a sequence job.

Pure and file-system-only (temporary directories); no runtime, queue or GUI display is touched.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from src.queue.job_model import JobStatus
from src.video.sequence_history import (
    planned_segments,
    read_ledger_progress,
    sequence_history_info,
)
from src.video.sequence_ledger import LEDGER_FILE_NAME
from src.video.sequence_locator import folder_token, locate_ledger
from src.video.sequence_shots import MAX_SHOTS, ShotDraft, build_sequence_intent, shot_problems

# ----------------------------------------------------------------------------- shots -> intent


def test_shots_become_one_intent_with_provided_anchors_only_where_a_keyframe_is_named() -> None:
    shots = [
        ShotDraft(prompt="waves", frame_count=17, seed="5", keyframe_path="ignored.png"),
        ShotDraft(frame_count=21),
        ShotDraft(prompt="turns", frame_count=17, keyframe_path="C:/k/two.PNG"),
    ]

    intent = build_sequence_intent(shots, clip_name=" walk ")

    assert intent == {
        "segments": [
            {"frame_count": 17, "prompt": "waves", "seed": "5"},
            {"frame_count": 21},
            {
                "frame_count": 17,
                "prompt": "turns",
                "anchor": {"policy": "provided", "path": "C:/k/two.PNG"},
            },
        ],
        "assembly": {"clip_name": "walk"},
    }


def test_a_shot_list_that_cannot_be_a_sequence_is_refused_with_operator_text() -> None:
    assert "at least 2" in " ".join(shot_problems([ShotDraft(frame_count=17)]))
    assert "at most" in " ".join(shot_problems([ShotDraft(frame_count=17)] * (MAX_SHOTS + 1)))
    problems = shot_problems(
        [ShotDraft(frame_count=17), ShotDraft(frame_count=None, keyframe_path="clip.mp4")]
    )
    assert any("choose a length" in text for text in problems)
    assert any("must be an image" in text for text in problems)
    with pytest.raises(ValueError, match="at least 2"):
        build_sequence_intent([ShotDraft(frame_count=17)])


def test_a_draft_is_read_from_form_values_without_raising_on_junk() -> None:
    draft = ShotDraft.from_mapping(
        {"prompt": " a ", "frame_count": "x", "keyframe_path": " k.png "}
    )
    assert (draft.prompt, draft.frame_count, draft.keyframe_path) == ("a", None, "k.png")
    assert ShotDraft.from_mapping({"frame_count": " 21 "}).frame_count == 21


# ----------------------------------------------------------------------------- locating a ledger


def _ledger(directory: Path, job_id: str, **extra: Any) -> Path:
    directory.mkdir(parents=True)
    path = directory / LEDGER_FILE_NAME
    path.write_text(json.dumps({"job_id": job_id, "state": "cancelled", **extra}), encoding="utf-8")
    return path


def test_the_ledger_of_a_job_is_found_in_its_named_run_folder_under_a_route(tmp_path: Path) -> None:
    job_id = "abcdef0123456789abcdef"
    wanted = _ledger(
        tmp_path / "Pipeline" / f"20261022_101500_{folder_token(job_id)}-model-none", job_id
    )
    _ledger(tmp_path / "Pipeline" / "20261022_101600_zzzzzzzzzzzz-model-none", "someone-else")

    assert locate_ledger(job_id, [tmp_path]) == str(wanted.resolve())


def test_a_folder_that_matches_by_name_but_belongs_to_another_job_is_not_trusted(
    tmp_path: Path,
) -> None:
    job_id = "abcdef0123456789"
    _ledger(tmp_path / f"20261022_{folder_token(job_id)}-m-none", "a-different-job")

    assert locate_ledger(job_id, [tmp_path]) is None
    assert locate_ledger(job_id, [tmp_path / "missing"]) is None
    assert locate_ledger("", [tmp_path]) is None


def test_an_unreadable_or_oversized_ledger_is_skipped_not_raised(tmp_path: Path) -> None:
    job_id = "feedfacefeedface"
    folder = tmp_path / f"run_{folder_token(job_id)}"
    folder.mkdir()
    (folder / LEDGER_FILE_NAME).write_text("{not json", encoding="utf-8")

    assert locate_ledger(job_id, [tmp_path]) is None


# ----------------------------------------------------------------------------- what History shows


def _snapshot(segments: int) -> dict[str, Any]:
    plan = {"segments": [{"index": i} for i in range(segments)]}
    return {
        "normalized_job": {"workload": {"config": {"video_workflow": {"sequence_metadata": plan}}}}
    }


def test_an_ordinary_job_is_not_a_sequence() -> None:
    assert planned_segments({"normalized_job": {"workload": {"config": {"txt2img": {}}}}}) == 0
    assert planned_segments(None) == 0
    assert sequence_history_info(None, None, JobStatus.COMPLETED) is None


def test_a_cancelled_sequence_offers_resume_and_replay_with_its_progress() -> None:
    result = {
        "metadata": [{"sequence_artifact": {"completed_segments": 2, "ledger_path": "L.json"}}]
    }

    info = sequence_history_info(_snapshot(3), result, JobStatus.CANCELLED)

    assert info is not None
    assert (info.total_segments, info.completed_segments, info.ledger_path) == (3, 2, "L.json")
    assert info.can_resume and info.can_replay
    assert "2 of 3 segments done" in info.label and "Resume" in info.label


def test_a_finished_sequence_can_be_replayed_but_has_nothing_to_resume() -> None:
    result = {"metadata": {"sequence_artifact": {"completed_segments": 3}}}

    info = sequence_history_info(_snapshot(3), result, JobStatus.COMPLETED)

    assert info is not None and info.can_replay and not info.can_resume
    assert info.label == "Sequence: all 3 segments done."


def test_a_running_sequence_offers_nothing_and_a_cancelled_one_without_a_result_still_does() -> (
    None
):
    running = sequence_history_info(_snapshot(2), None, JobStatus.RUNNING)
    assert running is not None and not running.can_resume and not running.can_replay

    cancelled = sequence_history_info(_snapshot(2), None, JobStatus.CANCELLED)
    assert cancelled is not None and cancelled.can_resume and cancelled.ledger_path is None
    assert cancelled.completed_segments == 0


def test_ledger_progress_is_read_from_the_checkpoint_file(tmp_path: Path) -> None:
    path = _ledger(tmp_path / "run", "j", completed_prefix=2, total_segments=4)

    assert read_ledger_progress(path) == (2, 4, "cancelled")
    assert read_ledger_progress(tmp_path / "nope.json") is None
