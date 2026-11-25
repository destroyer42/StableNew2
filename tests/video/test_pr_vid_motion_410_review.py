"""PR-VID-MOTION-410 Workstream E: the motion review state (source, effective driver, results) on one bounded clock."""

from __future__ import annotations

import json
import threading
from pathlib import Path

import pytest

from src.gui.view_contracts.video_eval_motion_review_contract import (
    SLOT_DRIVER,
    SLOT_LEFT,
    SLOT_RIGHT,
    SLOT_SOURCE,
    MotionReviewSession,
    anchor_text,
)
from src.gui.view_contracts.video_experiment_contract import WorkOutcome
from src.video.review_preview import STATUS_OK, PreviewClip, PreviewResult
from src.video.video_eval_motion_review import (
    MotionReviewError,
    load_motion_review,
)
from tests.video.test_pr_vid_motion_410_evidence import MotionRun


def clip(
    path: str, *, fps: float | None = 24.0, frames: int = 48, reported: int | None = None
) -> PreviewClip:
    return PreviewClip(
        path=path,
        width=2,
        height=2,
        source_width=64,
        source_height=64,
        fps=fps,
        frame_count=frames,
        reported_frame_count=reported,
        duration_seconds=None,
        raw=b"\x00" * (12 * frames),
    )


def ok(path: str, **kwargs) -> PreviewResult:
    return PreviewResult(path=path, status=STATUS_OK, clip=clip(path, **kwargs))


@pytest.fixture
def built(tmp_path):
    run = MotionRun(tmp_path)
    run.build()
    return run


@pytest.fixture
def built_prepared(tmp_path):
    run = MotionRun(tmp_path, prepared=True)
    run.build()
    return run


# ------------------------------------------------------------------ the data: what the model consumed


def test_the_review_binds_source_effective_driver_and_results_for_each_case(built) -> None:
    data = load_motion_review(built.run_dir)
    assert data.baseline_arm == "baseline" and [c.case_id for c in data.cases] == [
        "head_s0",
        "head_s1",
    ]
    case = data.cases[0]
    assert case.source.verified and case.source.path
    assert case.driver.path == str(built.driver) and case.driver.original_path == str(built.driver)
    assert "original file" in case.driver.note and "not prepared" in case.driver.note
    assert [c.arm_id for c in case.cells] == ["baseline", "motion_emphasis", "reference_emphasis"]
    baseline = case.cell("baseline")
    assert (
        baseline.playable and baseline.integrity == "verified_comparable" and baseline.is_baseline
    )
    assert any("pose_strength=1" in line for line in baseline.settings_lines)
    assert any("pose_strength=1.2" in line for line in case.cell("motion_emphasis").settings_lines)


def test_a_prepared_driver_is_shown_as_the_derivative_with_the_original_one_click_away(
    built_prepared,
) -> None:
    case = load_motion_review(built_prepared.run_dir).cases[0]
    assert case.driver.path != str(built_prepared.driver)  # the derivative the model consumed
    assert case.driver.original_path == str(built_prepared.driver)
    assert "prepared derivative" in case.driver.note and case.driver.verified


def test_a_changed_driver_is_not_presented_as_the_admitted_input(built) -> None:
    built.driver.write_bytes(b"swapped driving video")
    built.build()
    case = load_motion_review(built.run_dir).cases[0]
    assert not case.driver.verified and "changed after admission" in case.driver.note
    assert case.cell("baseline").integrity == "changed_input"


def test_a_job_without_a_recorded_effective_driver_is_labelled_original_binding_only(built) -> None:
    manifest_path = built.run_dir / "run.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    for job in manifest["jobs"]:
        job.pop("motion")
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    case = load_motion_review(built.run_dir).cases[0]
    assert not case.driver.verified and "original binding only" in case.driver.label
    assert "not verified as what the model consumed" in case.driver.note


def test_the_review_needs_a_built_report_and_a_motion_run(built, tmp_path) -> None:
    (built.run_dir / "metrics.json").unlink()
    with pytest.raises(MotionReviewError, match="Build the report"):
        load_motion_review(built.run_dir)
    empty = tmp_path / "empty_run"
    empty.mkdir()
    with pytest.raises(MotionReviewError):
        load_motion_review(empty)


# ------------------------------------------------------------------ the session


class Ports:
    def __init__(self, built, *, fps=None, frames=None, mode="nsfw"):
        self.built = built
        self.mode = mode
        self.fps = fps or {}
        self.frames = frames or {}
        self.previews: list[str] = []
        self.images: list[str] = []
        self.loads = 0

    def load(self, run_dir, cancel):
        self.loads += 1
        return load_motion_review(run_dir, cancel)

    def preview(self, path, cancel):
        self.previews.append(path)
        name = Path(path).name
        return ok(path, fps=self.fps.get(name, 24.0), frames=self.frames.get(name, 48))

    def image(self, path, cancel):
        self.images.append(path)
        return f"image:{Path(path).name}"


def session(built, **kwargs) -> tuple[MotionReviewSession, Ports]:
    ports = Ports(built, **{k: v for k, v in kwargs.items() if k in ("fps", "frames", "mode")})
    changes: list[int] = []
    instance = MotionReviewSession(
        load=ports.load,
        prepare_preview=ports.preview,
        prepare_image=ports.image,
        visibility=lambda: ports.mode,
        on_change=lambda: changes.append(1),
    )
    instance.changes = changes  # type: ignore[attr-defined]
    return instance, ports


def load(instance: MotionReviewSession, built) -> list:
    work = instance.begin_load(str(built.run_dir))
    works = instance.finish_load(work, instance.run_load(work))
    assert works is not None
    for item in works:
        assert instance.finish_media(item, instance.run_media(item))
    return works


def test_loading_a_run_selects_the_baseline_and_the_next_arm_and_decodes_every_role_once(
    built,
) -> None:
    instance, ports = session(built)
    works = load(instance, built)

    assert {w.slot for w in works} == {SLOT_SOURCE, SLOT_DRIVER, SLOT_LEFT, SLOT_RIGHT}
    assert instance.arms == ("baseline", "motion_emphasis")
    assert (
        len(ports.images) == 1 and len(ports.previews) == 3
    )  # driver + two results, all bounded previews
    assert instance.clock.playing is False  # nothing plays until the operator asks
    assert (
        instance.slot(SLOT_SOURCE).state == "ready" and instance.slot(SLOT_DRIVER).state == "ready"
    )


def test_roles_and_case_rows_name_the_expectation_and_the_identity_of_each_medium(built) -> None:
    instance, _ = session(built)
    load(instance, built)
    roles = {role: (label, note) for role, label, note in instance.role_rows() if role != "result"}
    assert "Source image" in roles["source"][0] and "Digest matches" in roles["source"][1]
    assert "Driving reference" in roles["driver"][0]
    rows = dict(instance.case_rows())
    assert rows["Motion category"] == "Head turn" and "60 degrees" in rows["Expected outcome"]
    results = [row for row in instance.role_rows() if row[0] == "result"]
    assert len(results) == 2 and all("Verified and comparable" in note for _r, _l, note in results)


def test_different_frame_rates_and_durations_are_disclosed_and_anchors_use_common_times(
    built,
) -> None:
    instance, ports = session(built)
    # The two results: one 24 fps x 48 frames (2 s), one 12 fps x 24 frames (2 s). Equal duration, different rates.
    work = instance.begin_load(str(built.run_dir))
    works = instance.finish_load(work, instance.run_load(work))
    left_name = Path(instance.cell(SLOT_LEFT).clip_path).name
    right_name = Path(instance.cell(SLOT_RIGHT).clip_path).name
    ports.fps.update({left_name: 24.0, right_name: 12.0})
    ports.frames.update({left_name: 48, right_name: 24})
    for item in works:
        instance.finish_media(item, instance.run_media(item))

    notes = " ".join(instance.notes())
    assert "24 fps" in notes and "12 fps" in notes and "repeats frames" in notes
    left = instance.anchor_frames(SLOT_LEFT)
    right = instance.anchor_frames(SLOT_RIGHT)
    assert len(left) == len(right) == 3
    # The middle anchor is the same moment for both clips, but not the same frame number.
    assert left[1].index != right[1].index
    assert left[1].seconds == pytest.approx(right[1].seconds, abs=1 / 12)
    assert "frame" in anchor_text(left) and "s" in anchor_text(right)
    assert instance.position_text().count("frame") >= 2


def test_a_shorter_clip_is_held_and_labelled_held(built) -> None:
    instance, ports = session(built)
    work = instance.begin_load(str(built.run_dir))
    works = instance.finish_load(work, instance.run_load(work))
    right = Path(instance.cell(SLOT_RIGHT).clip_path).name
    ports.frames[right] = 12  # 0.5 s against the others' 2 s
    for item in works:
        instance.finish_media(item, instance.run_media(item))
    last = instance.anchor_frames(SLOT_RIGHT)[-1]
    assert last.held and last.index == 11
    assert any("is shorter" in note for note in instance.notes())


def test_playback_is_explicit_and_stops_at_the_end(built) -> None:
    instance, _ = session(built)
    load(instance, built)
    assert instance.tick(1.0) is False and instance.clock.position == 0
    instance.play(10.0)
    assert instance.tick(10.0 + 1.0) is True and instance.clock.position > 0
    instance.tick(10.0 + 60.0)
    assert (
        instance.clock.position == instance.clock.last_position and instance.clock.playing is False
    )


def test_a_superseded_selection_discards_its_late_decode_and_cancels_it(built) -> None:
    instance, _ = session(built)
    work = instance.begin_load(str(built.run_dir))
    works = instance.finish_load(work, instance.run_load(work))
    left = next(w for w in works if w.slot == SLOT_LEFT)
    instance.select_arms(
        "reference_emphasis", "motion_emphasis"
    )  # the left slot now shows another clip

    assert left.cancel.is_set()
    assert (
        instance.finish_media(left, instance.run_media(left)) is False
    )  # stale: dropped, never rendered
    assert instance.slot(SLOT_LEFT).state == "loading" and instance.slot(SLOT_LEFT).clip is None


def test_closing_cancels_everything_and_ignores_late_results(built) -> None:
    instance, _ = session(built)
    work = instance.begin_load(str(built.run_dir))
    works = instance.finish_load(work, instance.run_load(work))
    instance.close()
    assert all(w.cancel.is_set() for w in works)
    assert instance.finish_media(works[0], WorkOutcome(value=ok("x"))) is False
    assert instance.begin_load(str(built.run_dir)) is None
    assert instance.slot(SLOT_LEFT) is None


def test_a_newer_load_supersedes_an_older_one(built) -> None:
    instance, _ = session(built)
    first = instance.begin_load(str(built.run_dir))
    second = instance.begin_load(str(built.run_dir))
    assert first.cancel.is_set() and not second.cancel.is_set()
    assert instance.finish_load(first, instance.run_load(first)) is None  # stale
    assert instance.finish_load(second, instance.run_load(second)) is not None


def test_a_failed_load_is_reported_not_raised(built, tmp_path) -> None:
    instance, _ = session(built)
    work = instance.begin_load(str(tmp_path / "nowhere"))
    assert instance.finish_load(work, instance.run_load(work)) is None
    assert instance.status.startswith("Cannot review") and instance.case is None


def test_sfw_mode_does_not_decode_the_source_or_the_driver_and_redacts_text(built) -> None:
    instance, ports = session(built, mode="sfw")
    work = instance.begin_load(str(built.run_dir))
    works = instance.finish_load(work, instance.run_load(work))
    assert {w.slot for w in works} == {SLOT_LEFT, SLOT_RIGHT}
    assert (
        ports.images == []
        and instance.slot(SLOT_DRIVER) is None
        and instance.slot(SLOT_SOURCE) is None
    )
    assert any("hidden in SFW mode" in note for note in instance.notes())


def test_a_missing_driver_file_is_not_decoded_and_the_reason_is_shown(built) -> None:
    built.driver.unlink()
    built.build()
    instance, ports = session(built)
    work = instance.begin_load(str(built.run_dir))
    works = instance.finish_load(work, instance.run_load(work))
    assert SLOT_DRIVER not in {w.slot for w in works}  # a missing file is never decoded
    notes = instance.notes()
    assert any("missing or unreadable" in note for note in notes)
    assert any("not verified as the file the model consumed" in note for note in notes)


def test_open_original_offers_only_recorded_files_that_still_exist(built_prepared) -> None:
    instance, _ = session(built_prepared)
    load(instance, built_prepared)
    assert instance.original_path(SLOT_DRIVER) == str(
        built_prepared.driver
    )  # the original, not the derivative
    assert instance.effective_driver_path() != instance.original_path(SLOT_DRIVER)
    assert instance.original_path(SLOT_LEFT).endswith(".mp4")
    built_prepared.driver.unlink()
    assert instance.original_path(SLOT_DRIVER) is None


def test_decode_failures_become_a_visible_state_not_an_exception(built) -> None:
    instance, ports = session(built)
    ports.preview = lambda path, cancel: (_ for _ in ()).throw(OSError("decoder crashed"))  # type: ignore[assignment]
    instance._prepare_preview = ports.preview  # the injected port raises
    work = instance.begin_load(str(built.run_dir))
    works = instance.finish_load(work, instance.run_load(work))
    media = next(w for w in works if w.slot == SLOT_LEFT)
    assert instance.finish_media(media, instance.run_media(media)) is True
    assert (
        instance.slot(SLOT_LEFT).state == "failed"
        and "decoder crashed" in instance.slot(SLOT_LEFT).message
    )


def test_the_event_type_is_a_real_threading_event(built) -> None:
    instance, _ = session(built)
    assert isinstance(instance.begin_load(str(built.run_dir)).cancel, threading.Event)
