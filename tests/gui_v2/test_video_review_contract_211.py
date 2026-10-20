"""PR-VID-QUALITY-211: the Tk-free review session and comparison clock.

No Tk, no FFmpeg, no repository: the session is driven through its begin/run/finish steps with plain
callables, exactly as the window drives it.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

from src.gui.view_contracts.video_experiment_contract import WorkOutcome
from src.gui.view_contracts.video_review_contract import (
    ClipTiming,
    ComparisonClock,
    VideoReviewSession,
)
from src.learning.video_quality_review import (
    ClipReviewDraft,
    ReviewSaveError,
    SavedClipReview,
    SavedPreference,
    SaveOutcome,
    StoredReviews,
)
from src.learning.video_review_service import LoadedReview
from src.video.review_preview import PreviewClip, PreviewResult
from src.video.video_review_group import (
    ArmState,
    ReviewArm,
    ReviewGroup,
    ReviewOverview,
)

SHA = {label: label.lower() * 64 for label in "ABCD"}


def _arm(index: int, state: ArmState = ArmState.PLAYABLE) -> ReviewArm:
    label = "ABCD"[index]
    playable = state is ArmState.PLAYABLE
    return ReviewArm(
        label=label,
        index=index,
        value=float(index + 1),
        job_id=f"job-{label}",
        state=state,
        state_text="Ready to review." if playable else state.value,
        njr_fingerprint="f" * 64,
        artifact_path=f"C:/out/{label}.mp4" if playable else None,
        artifact_sha256=SHA[label] if playable else "",
    )


def _group(*states: ArmState, prompt: str = "a calm walk") -> ReviewGroup:
    arms = tuple(_arm(i, state) for i, state in enumerate(states))
    overview = ReviewOverview(
        workflow_id="wf",
        workflow_version="1.0.0",
        backend_id="comfy",
        seed=7,
        frame_count=12,
        fps=12.0,
        prompt=prompt,
        negative_prompt="",
        source_image_path="C:/src.png",
        prepared_source_path="C:/prep.png",
        driving_video_path="C:/drive.mp4",
        driving_video_sha256="d" * 64,
        fixed_controls={"pose_prompt": "steps left"},
    )
    return ReviewGroup(
        "exp-1", "Video experiment: Pose Strength", "pose_strength", arms, overview, arms[0].job_id
    )


def _clip(frames: int, fps: float | None = 12.0, *, reported: int | None = None) -> PreviewClip:
    return PreviewClip(
        path="p",
        width=4,
        height=2,
        source_width=64,
        source_height=48,
        fps=fps,
        frame_count=frames,
        reported_frame_count=frames if reported is None else reported,
        duration_seconds=None,
        raw=b"".join(bytes([n % 256]) * 24 for n in range(frames)),
    )


class _Harness:
    """A session plus the recorded calls its injected callables received."""

    def __init__(self, group: ReviewGroup, stored: StoredReviews | None = None) -> None:
        self.group = group
        self.stored = stored or StoredReviews()
        self.changes = 0
        self.saved: list[tuple[str, ClipReviewDraft]] = []
        self.preferences: list[tuple[str | None, str]] = []
        self.save_result: Any = SaveOutcome("saved", 1, "id")
        self.preview_results: dict[str, PreviewResult] = {}
        self.session = VideoReviewSession(
            load=lambda job_id, cancel: LoadedReview(self.group, self.stored),
            prepare_preview=lambda path, cancel: self.preview_results[path],
            save_clip=self._save_clip,
            save_preference=self._save_preference,
            file_exists=lambda path: path.endswith("A.mp4"),
            on_change=self._changed,
        )

    def _changed(self) -> None:
        self.changes += 1

    def _save_clip(self, group, job_id, draft):
        self.saved.append((job_id, draft))
        if isinstance(self.save_result, Exception):
            raise self.save_result
        return self.save_result

    def _save_preference(self, group, job_id, reason):
        self.preferences.append((job_id, reason))
        if isinstance(self.save_result, Exception):
            raise self.save_result
        return self.save_result

    def load(self, job_id: str = "job-A") -> bool:
        work = self.session.begin_load(job_id)
        assert work is not None
        return self.session.finish_load(work, self.session.run_load(work))

    def ready(self, work, frames: int = 12, fps: float | None = 12.0) -> bool:
        clip = _clip(frames, fps)
        self.preview_results[work.path] = PreviewResult(work.path, "ok", clip)
        return self.session.finish_preview(work, self.session.run_preview(work))


# ------------------------------------------------------------------ the comparison clock


def test_equal_clips_share_one_exact_timeline():
    clock = ComparisonClock()
    timing = ClipTiming("A", 12, 12.0)
    clock.configure([timing, ClipTiming("B", 12, 12.0)])

    assert clock.steps == 12 and clock.last_position == 11
    assert [clock.frame_index(timing, p) for p in range(12)] == list(range(12))
    assert clock.notes() == []


def test_a_shorter_clip_is_held_on_its_final_frame_without_changing_speed():
    clock = ComparisonClock()
    long_clip, short_clip = ClipTiming("A", 12, 12.0), ClipTiming("B", 6, 12.0)
    clock.configure([long_clip, short_clip])

    assert clock.steps == 12
    assert [clock.frame_index(short_clip, p) for p in range(12)] == [
        0,
        1,
        2,
        3,
        4,
        5,
        5,
        5,
        5,
        5,
        5,
        5,
    ]
    assert [clock.frame_index(long_clip, p) for p in range(12)] == list(
        range(12)
    )  # speed untouched
    clock.seek(3)
    assert not clock.is_held(short_clip)
    clock.seek(9)
    assert clock.is_held(short_clip) and not clock.is_held(long_clip)
    assert any(
        "B is shorter" in note and "held on its final frame" in note for note in clock.notes()
    )


def test_different_frame_rates_step_on_the_finer_grid_and_repeat_frames_of_the_slower_clip():
    clock = ComparisonClock()
    fast, slow = ClipTiming("A", 24, 24.0), ClipTiming("B", 12, 12.0)  # both exactly 1 s long
    clock.configure([fast, slow])

    assert clock.steps == 24 and abs(clock.seconds) < 1e-9
    assert [clock.frame_index(slow, p) for p in range(6)] == [0, 0, 1, 1, 2, 2]
    clock.seek(23)
    assert (clock.frame_index(fast), clock.frame_index(slow)) == (23, 11)
    assert abs(clock.seconds - 23 / 24) < 1e-9
    notes = " ".join(clock.notes())
    assert "24 fps" in notes and "12 fps" in notes and "no speed is changed" in notes


def test_a_longer_slower_clip_still_reaches_its_final_frame():
    clock = ComparisonClock()
    quick, slow = ClipTiming("A", 24, 24.0), ClipTiming("B", 18, 12.0)  # 1.0 s vs 1.5 s
    clock.configure([quick, slow])

    assert clock.steps == 36
    clock.seek(clock.last_position)
    assert clock.frame_index(slow) == 17 and clock.frame_index(quick) == 23 and clock.is_held(quick)


def test_seek_and_step_clamp_and_stepping_pauses_playback():
    clock = ComparisonClock()
    clock.configure([ClipTiming("A", 5, 10.0)])
    clock.play(0.0)
    clock.step(1)
    assert clock.playing is False and clock.position == 1
    clock.step(-5)
    assert clock.position == 0
    clock.seek(999)
    assert clock.position == 4
    clock.restart()
    assert clock.position == 0 and not clock.playing


def test_playback_follows_real_time_stops_at_the_end_and_replays_from_the_start():
    clock = ComparisonClock()
    clock.configure([ClipTiming("A", 10, 10.0)])
    clock.play(100.0)

    assert clock.tick(100.05) is False and clock.position == 0
    assert clock.tick(100.35) is True and clock.position == 3
    assert clock.tick(105.0) is True and clock.position == 9
    assert clock.playing is False  # reached the end
    clock.play(200.0)
    assert clock.position == 0 and clock.playing  # Play at the end restarts
    clock.pause()
    assert clock.tick(250.0) is False


def test_timing_disclosures_cover_assumed_rates_and_truncated_previews():
    clock = ComparisonClock()
    clock.configure([ClipTiming("A", 5, 24.0, fps_assumed=True, reported_frame_count=81)])
    notes = " ".join(clock.notes())
    assert "assumed" in notes and "first 5 of 81" in notes


def test_an_empty_clock_is_safe():
    clock = ComparisonClock()
    clock.configure([])
    clock.step(1)
    clock.play(0.0)
    assert clock.steps == 1 and clock.position == 0 and clock.notes() == []
    assert clock.position_text().startswith("t = 0.000 s")


# ------------------------------------------------------------------ opening a review


def test_a_load_selects_the_first_two_playable_arms_keeping_their_identities():
    h = _Harness(_group(ArmState.FAILED, ArmState.PLAYABLE, ArmState.PENDING, ArmState.PLAYABLE))

    assert h.load()

    assert h.session.pair == ("job-B", "job-D")
    assert [text for _job, text in h.session.available_choices()] == ["B  (2)", "D  (4)"]
    assert h.session.arm("job-D").label == "D" and h.session.arm("job-D").value == 4.0
    assert "2 ready to review" in h.session.status


def test_a_load_failure_is_reported_and_clears_the_previous_review():
    h = _Harness(_group(ArmState.PLAYABLE, ArmState.PLAYABLE))
    assert h.load()
    h.session._load = lambda job_id, cancel: (_ for _ in ()).throw(ValueError("No job 'x' exists"))

    assert h.load("x") is False

    assert h.session.group is None and h.session.pair == (None, None)
    assert h.session.status == "Cannot review: No job 'x' exists"


def test_a_single_playable_arm_or_none_degrades_cleanly():
    one = _Harness(_group(ArmState.PLAYABLE, ArmState.PENDING))
    one.load()
    assert one.session.pair == ("job-A", None)
    none = _Harness(_group(ArmState.PENDING, ArmState.FAILED))
    none.load()
    assert none.session.pair == (None, None) and none.session.available_choices() == []
    assert none.session.select_pair(None, None) == []
    assert "Only one arm" not in none.session.status


# ------------------------------------------------------------------ pair selection and previews


def test_pair_selection_preserves_arm_identity_and_starts_one_decode_per_clip():
    h = _Harness(_group(*[ArmState.PLAYABLE] * 4))
    h.load()

    works = h.session.select_pair("job-B", "job-D")

    assert [(w.job_id, w.path) for w in works] == [
        ("job-B", "C:/out/B.mp4"),
        ("job-D", "C:/out/D.mp4"),
    ]
    assert h.session.pair == ("job-B", "job-D")
    h.session.select_pair("job-B", "job-B")  # the same clip cannot be both sides
    assert h.session.pair == ("job-B", None)


def test_unplayable_or_unknown_jobs_cannot_be_put_on_screen():
    h = _Harness(_group(ArmState.PLAYABLE, ArmState.FAILED, ArmState.PLAYABLE))
    h.load()

    h.session.select_pair("job-B", "nonsense")

    assert h.session.pair == (None, None)


def test_ready_previews_configure_one_clock_and_report_differences():
    h = _Harness(_group(ArmState.PLAYABLE, ArmState.PLAYABLE))
    h.load()
    left, right = h.session.select_pair("job-A", "job-B")
    assert h.ready(left, frames=12) and h.ready(right, frames=6)

    clock = h.session.clock
    assert clock.steps == 12
    assert h.session.timing_for("job-B").frame_count == 6
    assert any("B is shorter" in note for note in clock.notes())
    assert "frame 12/12" not in clock.position_text()  # position 0 -> first frames
    assert h.session.slot("job-A").state == "ready"
    assert "Review preview 4x2 of the original 64x48" in h.session.slot("job-A").message


def test_a_decode_failure_keeps_the_review_open_with_a_message():
    h = _Harness(_group(ArmState.PLAYABLE, ArmState.PLAYABLE))
    h.load()
    left, right = h.session.select_pair("job-A", "job-B")
    h.preview_results[left.path] = PreviewResult(
        left.path, "failed", None, "ffmpeg_unavailable", "FFmpeg was not found."
    )
    assert h.session.finish_preview(left, h.session.run_preview(left))
    assert h.ready(right)

    slot = h.session.slot("job-A")
    assert slot.state == "failed" and slot.message == "FFmpeg was not found."
    assert h.session.can_review("job-A")  # ratings stay available without a preview
    assert h.session.original_path("job-A") == "C:/out/A.mp4"


def test_an_exception_in_the_decoder_is_contained():
    h = _Harness(_group(ArmState.PLAYABLE, ArmState.PLAYABLE))
    h.load()
    work = h.session.select_pair("job-A", "job-B")[0]
    h.session._prepare_preview = lambda path, cancel: (_ for _ in ()).throw(
        RuntimeError("decoder blew up")
    )

    assert h.session.finish_preview(work, h.session.run_preview(work))

    assert (
        h.session.slot("job-A").state == "failed"
        and "decoder blew up" in h.session.slot("job-A").message
    )


def test_changing_the_selection_cancels_and_discards_stale_preview_work():
    h = _Harness(_group(*[ArmState.PLAYABLE] * 3))
    h.load()
    first = h.session.select_pair("job-A", "job-B")
    stale_b = first[1]

    second = h.session.select_pair("job-A", "job-C")  # B is dropped while its decode is in flight

    assert stale_b.cancel.is_set() and not first[0].cancel.is_set()
    assert [w.job_id for w in second] == ["job-C"]  # A is still decoding; no duplicate request
    assert h.session.slot("job-B") is None
    assert h.ready(stale_b) is False  # the late result is discarded, not rendered
    assert h.session.slot("job-B") is None and h.session.timing_for("job-B") is None


def test_reselecting_a_clip_issues_a_fresh_request_so_an_older_result_cannot_land():
    h = _Harness(_group(*[ArmState.PLAYABLE] * 3))
    h.load()
    old_b = h.session.select_pair("job-A", "job-B")[1]
    h.session.select_pair("job-A", "job-C")
    new_b = h.session.select_pair("job-A", "job-B")[0]

    assert new_b.token != old_b.token
    assert h.ready(old_b) is False
    assert h.ready(new_b) is True


def test_reloading_the_review_discards_every_outstanding_preview():
    h = _Harness(_group(ArmState.PLAYABLE, ArmState.PLAYABLE))
    h.load()
    left = h.session.select_pair("job-A", "job-B")[0]

    h.load()  # the operator pressed Load again

    assert left.cancel.is_set()
    assert h.ready(left) is False


def test_a_superseded_load_cannot_overwrite_the_newer_one():
    h = _Harness(_group(ArmState.PLAYABLE, ArmState.PLAYABLE))
    old = h.session.begin_load("job-A")
    new = h.session.begin_load("job-B")

    assert old.cancel.is_set()
    assert h.session.finish_load(old, h.session.run_load(old)) is False
    assert h.session.group is None and h.session.busy_loading
    assert h.session.finish_load(new, h.session.run_load(new)) is True


def test_closing_cancels_everything_frees_frames_and_ignores_late_results():
    h = _Harness(_group(ArmState.PLAYABLE, ArmState.PLAYABLE))
    h.load()
    left, right = h.session.select_pair("job-A", "job-B")
    assert h.ready(left)

    h.session.close()

    assert right.cancel.is_set() and left.cancel.is_set()
    assert h.session.slot("job-A") is None  # frame memory released
    assert h.ready(right) is False
    assert h.session.begin_load("job-A") is None and h.session.begin_save("job-A") is None
    changes = h.changes
    h.session.set_field("job-A", "overall", "3")
    assert h.changes == changes  # a closed session notifies nobody


def test_repeated_open_close_cycles_leave_no_live_work():
    events = []
    for _ in range(25):
        h = _Harness(_group(ArmState.PLAYABLE, ArmState.PLAYABLE))
        h.load()
        events.extend(w.cancel for w in h.session.select_pair("job-A", "job-B"))
        h.session.close()
    assert all(event.is_set() for event in events)


# ------------------------------------------------------------------ forms and saving


def test_saved_reviews_prefill_only_the_matching_artifact_bytes():
    saved = SavedClipReview(
        draft=ClipReviewDraft(4, "partially_achieved", {"scene_stability": 3}, "slides").validate(),
        revision=2,
        reviewed_at="t",
        review_id="r",
        job_id="job-A",
        artifact_sha256=SHA["A"],
        artifact_path="C:/out/A.mp4",
    )
    stale = SavedClipReview(
        draft=ClipReviewDraft(5, "achieved").validate(),
        revision=1,
        reviewed_at="t",
        review_id="r2",
        job_id="job-B",
        artifact_sha256="9" * 64,  # a different file than the one on disk now
        artifact_path="C:/out/B.mp4",
    )
    stored = StoredReviews(clips={("job-A", SHA["A"]): saved, ("job-B", "9" * 64): stale})
    h = _Harness(_group(ArmState.PLAYABLE, ArmState.PLAYABLE), stored)

    h.load()

    form_a, form_b = h.session.forms["job-A"], h.session.forms["job-B"]
    assert (form_a.overall, form_a.outcome, form_a.notes) == ("4", "partially_achieved", "slides")
    assert form_a.dimensions["scene_stability"] == "3"
    assert (form_b.overall, form_b.outcome) == ("", "")
    assert h.session.messages["job-A"] == "Saved review, revision 2."
    assert not h.session.is_dirty("job-A") and "job-B" not in h.session.messages


def test_an_invalid_form_is_not_saved_and_says_why():
    h = _Harness(_group(ArmState.PLAYABLE, ArmState.PLAYABLE))
    h.load()

    assert h.session.begin_save("job-A") is None
    assert h.session.messages["job-A"].startswith("Not saved: Overall rating is required")
    h.session.set_field("job-A", "overall", "9")
    h.session.set_field("job-A", "outcome", "achieved")
    assert (
        h.session.begin_save("job-A") is None
        and "whole number from 1 to 5" in h.session.messages["job-A"]
    )
    assert h.saved == []


def test_a_successful_save_marks_the_form_clean_and_a_repeat_says_nothing_changed():
    h = _Harness(_group(ArmState.PLAYABLE, ArmState.PLAYABLE))
    h.load()
    h.session.set_field("job-A", "overall", "5")
    h.session.set_field("job-A", "outcome", "not_achieved")
    h.session.set_field("job-A", "notes", "never raised the arm")
    assert h.session.is_dirty("job-A")

    work = h.session.begin_save("job-A")
    assert h.session.messages["job-A"] == "Saving..." and "job-A" in h.session.saving
    assert h.session.begin_save("job-A") is None  # no double submit while one is outstanding
    assert h.session.finish_save(work, h.session.run_save(work)) is True

    assert h.session.messages["job-A"] == "Saved (revision 1)."
    assert not h.session.is_dirty("job-A") and not h.session.saving
    job, draft = h.saved[0]
    assert job == "job-A" and (draft.overall_rating, draft.action_outcome) == (5, "not_achieved")
    h.save_result = SaveOutcome("unchanged", 1, "id")
    again = h.session.begin_save("job-A")
    h.session.finish_save(again, h.session.run_save(again))
    assert h.session.messages["job-A"] == "No changes to save."


def test_a_failed_save_never_says_saved_and_keeps_the_edits_dirty():
    h = _Harness(_group(ArmState.PLAYABLE, ArmState.PLAYABLE))
    h.load()
    h.session.set_field("job-B", "overall", "3")
    h.session.set_field("job-B", "outcome", "cannot_assess")
    h.save_result = ReviewSaveError("The review could not be written. Your edits are kept.")

    work = h.session.begin_save("job-B")
    assert h.session.finish_save(work, h.session.run_save(work)) is False

    message = h.session.messages["job-B"]
    assert message.startswith(
        "Save FAILED, your edits are kept"
    ) and "Saved" not in message.replace("Save FAILED", "")
    assert h.session.is_dirty("job-B") and h.session.forms["job-B"].overall == "3"
    assert not h.session.saving
    h.save_result = SaveOutcome("saved", 1, "id")  # retrying needs no retyping
    retry = h.session.begin_save("job-B")
    assert h.session.finish_save(retry, h.session.run_save(retry))
    assert not h.session.is_dirty("job-B")


def test_an_unexpected_save_status_is_not_treated_as_success():
    h = _Harness(_group(ArmState.PLAYABLE, ArmState.PLAYABLE))
    h.load()
    h.session.set_field("job-A", "overall", "3")
    h.session.set_field("job-A", "outcome", "achieved")
    h.save_result = SimpleNamespace(status="queued", revision=0)
    work = h.session.begin_save("job-A")

    assert h.session.finish_save(work, h.session.run_save(work)) is True
    assert "FAILED" in h.session.messages["job-A"] and h.session.is_dirty("job-A")


def test_an_arm_without_an_identified_clip_cannot_be_saved():
    h = _Harness(_group(ArmState.PLAYABLE, ArmState.FAILED))
    h.load()

    assert h.session.begin_save("job-B") is None
    assert "no completed, identified video" in h.session.messages["job-B"]


def test_a_save_that_lands_after_a_reload_is_ignored():
    h = _Harness(_group(ArmState.PLAYABLE, ArmState.PLAYABLE))
    h.load()
    h.session.set_field("job-A", "overall", "3")
    h.session.set_field("job-A", "outcome", "achieved")
    work = h.session.begin_save("job-A")
    h.load()  # the review reloaded before the save finished

    assert h.session.finish_save(work, WorkOutcome(value=SaveOutcome("saved", 1))) is False
    assert h.session.messages.get("job-A") != "Saved (revision 1)."


# ------------------------------------------------------------------ manual preference


def test_a_saved_preference_applies_only_while_it_names_the_same_bytes():
    stored = StoredReviews(
        preference=SavedPreference("job-B", "B", SHA["B"], "cleanest motion", 3, "t", "p")
    )
    h = _Harness(_group(ArmState.PLAYABLE, ArmState.PLAYABLE), stored)
    h.load()
    assert h.session.preference_job == "job-B" and h.session.preference_reason == "cleanest motion"
    assert not h.session.preference_dirty()

    replaced = StoredReviews(
        preference=SavedPreference("job-B", "B", "0" * 64, "cleanest motion", 3, "t", "p")
    )
    h2 = _Harness(_group(ArmState.PLAYABLE, ArmState.PLAYABLE), replaced)
    h2.load()
    assert (
        h2.session.preference_job is None
        and "no longer the same file" in h2.session.preference_message
    )


def test_preference_edits_save_through_the_service_and_report_failure_honestly():
    h = _Harness(_group(ArmState.PLAYABLE, ArmState.PLAYABLE))
    h.load()
    h.session.set_preference("job-A", "less foot sliding")
    assert h.session.preference_dirty()

    work = h.session.begin_save_preference()
    h.save_result = ReviewSaveError("disk full")
    assert h.session.finish_save(work, h.session.run_save(work)) is False
    assert h.session.preference_message == "Save FAILED, your edits are kept: disk full"
    assert h.session.preference_dirty()

    h.save_result = SaveOutcome("saved", 1, "id")
    work = h.session.begin_save_preference()
    assert h.session.finish_save(work, h.session.run_save(work)) is True
    assert h.preferences[-1] == ("job-A", "less foot sliding")
    assert (
        not h.session.preference_dirty()
        and "Saved manual preference" in h.session.preference_message
    )
    h.session.set_preference("job-B-unknown")
    assert h.session.preference_job is None  # only a reviewable arm can be preferred


# ------------------------------------------------------------------ visibility


def test_prompts_and_text_values_honour_the_content_visibility_mode():
    h = _Harness(_group(ArmState.PLAYABLE, ArmState.PLAYABLE, prompt="a nude woman walks"))
    h.load()

    shown = dict(h.session.overview_rows("nsfw"))
    hidden = dict(h.session.overview_rows("sfw"))

    assert shown["Prompt"] == "a nude woman walks"
    assert hidden["Prompt"] == "[Hidden in SFW mode]"
    assert "nude" not in " ".join(value for _label, value in hidden.items())
    assert dict(h.session.overview_rows("sfw"))["pose_prompt"] == "steps left"  # benign text stays
    assert h.session.arm_rows("sfw")[0]["value"] == "1"


def test_unplayable_arms_stay_listed_with_their_own_state():
    h = _Harness(_group(ArmState.PLAYABLE, ArmState.RUNNING, ArmState.FAILED, ArmState.MISSING))
    h.load()

    rows = h.session.arm_rows()

    assert [(r["label"], r["state"]) for r in rows] == [
        ("A (baseline)", "playable"),
        ("B", "running"),
        ("C", "failed"),
        ("D", "missing"),
    ]
    assert h.session.original_path("job-B") is None


def test_original_path_is_offered_only_while_the_recorded_file_exists():
    h = _Harness(_group(ArmState.PLAYABLE, ArmState.PLAYABLE))
    h.load()

    assert h.session.original_path("job-A") == "C:/out/A.mp4"
    assert h.session.original_path("job-B") is None  # the injected existence check says it is gone
    assert h.session.original_path("unknown") is None


def test_long_text_values_are_shortened_in_pair_labels_and_the_original_needs_a_video_suffix():
    long_value = "a very long motion prompt " * 20
    group = _group(ArmState.PLAYABLE, ArmState.PLAYABLE)
    arms = list(group.arms)
    arms[1] = ReviewArm(**{**arms[1].__dict__, "value": long_value})
    h = _Harness(ReviewGroup(**{**group.__dict__, "arms": tuple(arms)}))
    h.load()

    labels = [text for _job, text in h.session.available_choices()]
    assert len(labels[1]) < 60 and labels[1].endswith("...)")
    assert h.session.arm_rows()[1]["value"] == long_value  # the table keeps the full recorded value

    odd = _arm(0)
    h2 = _Harness(
        ReviewGroup(
            **{
                **group.__dict__,
                "arms": (ReviewArm(**{**odd.__dict__, "artifact_path": "C:/out/A.exe"}), arms[1]),
            }
        )
    )
    h2.session._file_exists = lambda path: True
    h2.load()
    assert h2.session.original_path("job-A") is None  # never hand a non-video path to the OS opener
