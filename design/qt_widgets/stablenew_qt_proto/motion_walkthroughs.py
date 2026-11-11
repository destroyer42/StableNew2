"""Seven scripted, executable Motion walkthroughs (MOTION-01 … MOTION-07) over the pure mock domain.

Each script drives a fresh :class:`MotionSession` exactly as an operator would through the UI, checks every
step with :func:`expect` and ends in a named success, refusal or recoverable state. The native Qt tests
replay the same journeys through real widgets; these scripts prove the rules without Qt.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, replace

from .edit_domain import CREATE_SOURCE, Replacement
from .motion_domain import (
    KIND_MOVIE,
    KIND_QUICK,
    KIND_STORY,
    MotionRefused,
    MotionSession,
    SeedIntent,
    StaleSave,
    Status,
    describe_run,
    diff_runs,
    resume_eligibility,
)

EDIT_SOURCE = "history:ridge-17"
EXPERIMENTAL = ("wan22_ti2v_5b_i2v_v1", "1.1.0")
SVD = ("svd_native", "svd-xt")


class WalkthroughError(AssertionError):
    """A scripted step did not behave as the operator contract requires."""


def expect(condition: object, message: str) -> None:
    if not condition:
        raise WalkthroughError(message)


def refused(action: Callable[[], object], needle: str) -> str:
    try:
        action()
    except MotionRefused as exc:
        expect(needle.lower() in str(exc).lower(), f"expected '{needle}' in refusal, got: {exc}")
        return str(exc)
    raise WalkthroughError(f"expected a refusal mentioning '{needle}'")


@dataclass(frozen=True)
class WalkthroughResult:
    key: str
    title: str
    outcome: str  # success | refusal | recoverable
    terminal: str
    steps: tuple[str, ...]


@dataclass
class Script:
    key: str
    title: str
    session: MotionSession
    log: list[str]

    def step(self, text: str) -> None:
        self.log.append(text)

    def done(self, outcome: str, terminal: str) -> WalkthroughResult:
        return WalkthroughResult(self.key, self.title, outcome, terminal, tuple(self.log))


def _script(key: str, title: str, session: MotionSession | None = None) -> Script:
    return Script(key, title, session or MotionSession(), [])


def _ready_quick(session: MotionSession, prompt: str = "Slow push toward the ridge") -> None:
    session.update_quick(prompt=prompt)
    session.review(KIND_QUICK)


def motion_01_quick_clip(session: MotionSession | None = None) -> WalkthroughResult:
    s = _script("MOTION-01", "Quick Clip", session)
    m = s.session
    s.step("Select source fixture create:ridge-study")
    expect(m.select_source(CREATE_SOURCE), "source selection")
    draft = m.quick.draft
    s.step(f"Default workflow is the recommended approved {draft.workflow[0]} {draft.workflow[1]}")
    expect(draft.workflow == ("wan22_ti2v_5b_i2v_v1", "1.3.0"), "recommended workflow")
    expect(m.status(KIND_QUICK) == Status.NOT_REVIEWED, "fresh draft is not reviewed")
    s.step("Author motion intent; Review Readiness")
    _ready_quick(m)
    expect(m.status(KIND_QUICK) == Status.READY, f"ready, got {m.status(KIND_QUICK)}")
    s.step("Simulate Clip: two independent variants")
    m.update_quick(variants=2)
    expect(m.status(KIND_QUICK) == Status.STALE, "editing variants makes the summary stale")
    m.review(KIND_QUICK)
    run = m.simulate_quick()
    expect(run.state == "Completed" and len(run.clips) == 2, "two completed variants")
    expect(run.clips[0].clip_id != run.clips[1].clip_id, "variant identities differ")
    s.step("Inspect clip: identity, frames, lineage")
    clip = run.clips[0]
    expect(clip.frames == 33 and abs(clip.seconds - 1.375) < 1e-9, "33 frames at 24 fps")
    expect(
        clip.source_key == CREATE_SOURCE and clip.source_digest == draft.source_digest, "lineage"
    )
    s.step("Rate: action outcome is separate from the quality impression")
    expect(m.rate(clip.clip_id, 4, "Nice push").stars == 4 and clip.completed, "rating is separate")
    return s.done("success", f"{run.run_id} completed with {len(run.clips)} simulated clips")


def motion_02_handoff(session: MotionSession | None = None) -> WalkthroughResult:
    s = _script("MOTION-02", "Create/Edit handoff", session)
    m = s.session
    s.step("Create result sends its linked source to Motion (nothing selected yet)")
    expect(m.receive_source(CREATE_SOURCE, "create"), "first handoff has nothing to replace")
    expect(m.quick.draft.source_key == CREATE_SOURCE, "identity retained")
    expect(m.status(KIND_QUICK) == Status.NOT_REVIEWED, "no preview approval is carried")
    s.step("Author unsaved Motion intent")
    m.update_quick(prompt="Drift the camera left")
    s.step("Edit sends a different source: a Cancel/Replace decision is required")
    expect(not m.receive_source(EDIT_SOURCE, "edit"), "different source is never replaced silently")
    expect(m.quick.draft.prompt == "Drift the camera left", "declining preserves the draft")
    s.step("Replace: new source, identity retained, intent and consent not carried")
    expect(m.receive_source(EDIT_SOURCE, "edit", Replacement.REPLACE), "replace")
    expect(m.quick.draft.source_key == EDIT_SOURCE and m.quick.draft.prompt == "", "fresh draft")
    expect(m.previews[KIND_QUICK] is None and not m.consent_valid(KIND_QUICK), "no old approvals")
    s.step("Build a fresh Motion preview")
    m.update_quick(prompt="Rise over the ridge")
    m.review(KIND_QUICK)
    expect(m.status(KIND_QUICK) == Status.READY, "fresh preview")
    return s.done("success", "source identity kept; unsaved draft protected; fresh preview ready")


def _three_shot_board(m: MotionSession) -> None:
    m.new_storyboard(CREATE_SOURCE, title="Ridge sequence", prompt="Slow cinematic movement")
    m.update_story(default_frames=33)
    m.add_shot()
    prompts = ("Push toward the ridge", "Tilt up to the dusk sky", "Pan right across the grass")
    for shot, text in zip(m.story.draft.shots, prompts, strict=True):
        m.update_shot(shot.shot_id, prompt=text)


def motion_03_storyboard(session: MotionSession | None = None) -> WalkthroughResult:
    s = _script("MOTION-03", "Storyboard", session)
    m = s.session
    s.step("Build a three-shot Storyboard from create:ridge-study")
    _three_shot_board(m)
    ids = [x.shot_id for x in m.story.draft.shots]
    expect(len(ids) == 3 and len(set(ids)) == 3, "three unique shot identities")
    s.step("Reorder: move shot 3 earlier; identity follows the shot")
    third = ids[2]
    m.move_shot(third, -1)
    order = [x.shot_id for x in m.story.draft.shots]
    expect(order == [ids[0], third, ids[1]], "reorder changes position, not identity")
    s.step("Duplicate shot 2: new identity, independent record")
    copy = m.duplicate_shot(third)
    expect(copy.shot_id not in ids and len(m.story.draft.shots) == 4, "duplicate has its own id")
    s.step("Revise the duplicate with explicit frames and an explicit seed")
    m.update_shot(copy.shot_id, frames=25, seed=SeedIntent("explicit", 77), label="Grass pan 2")
    expect(m.story.draft.shots[1].frames is None, "the original shot stays inherited")
    s.step("Review the summary: it is not an executable plan")
    preview = m.review(KIND_STORY)
    expect(not preview.executable and preview.errors == (), f"clean summary: {preview.errors}")
    expect(preview.total_frames == 33 * 3 + 25, "native frame total")
    s.step("Simulate Sequence")
    run = m.simulate_storyboard()
    expect(run.state == "Completed" and len(run.clips) == 4, "four segment clips")
    expect([r.shot_id for r in run.resolved] == [x.shot_id for x in m.story.draft.shots], "order")
    return s.done("success", f"{run.run_id}: four segments in authored order")


def motion_04_consent_and_compatibility(session: MotionSession | None = None) -> WalkthroughResult:
    s = _script("MOTION-04", "Consent and compatibility", session)
    m = s.session
    m.select_source(CREATE_SOURCE)
    s.step("Choose an experimental workflow version")
    m.update_quick(workflow=EXPERIMENTAL, prompt="Wind moves the grass")
    m.review(KIND_QUICK)
    expect(m.status(KIND_QUICK) == Status.BLOCKED, "experimental needs consent")
    refused(m.simulate_quick, "consent")
    s.step("Grant consent for exactly this proposed submission")
    m.grant_consent(KIND_QUICK)
    expect(m.status(KIND_QUICK) == Status.READY, "consent unblocks")
    s.step("An edit voids that consent: it is never inherited")
    m.update_quick(prompt="Wind moves the grass slowly")
    expect(not m.consent_valid(KIND_QUICK), "consent is bound to the exact draft")
    m.review(KIND_QUICK)
    expect(m.status(KIND_QUICK) == Status.BLOCKED, "blocked again")
    s.step("Consent for Quick Clip does not authorize a Storyboard, saved or not")
    m.grant_consent(KIND_QUICK)
    m.new_storyboard(CREATE_SOURCE, workflow=EXPERIMENTAL, prompt="Slow movement")
    expect(not m.consent_valid(KIND_STORY), "no cross-workflow consent")
    m.grant_consent(KIND_STORY)
    m.save_storyboard()
    expect(not m.consent_valid(KIND_STORY), "a saved draft retains no consent")
    s.step("Unsupported control: native SVD does not take a motion prompt")
    m.update_quick(workflow=SVD, prompt="Pan left")
    preview = m.review(KIND_QUICK)
    expect(any("no motion prompt" in e for e in preview.errors), "refused, not silently dropped")
    expect(m.status(KIND_QUICK) == Status.BLOCKED, "blocked by the unsupported control")
    return s.done("refusal", "unsupported SVD prompt refused; consent never inherited")


def motion_05_sequence_iteration(session: MotionSession | None = None) -> WalkthroughResult:
    s = _script("MOTION-05", "Sequence review and iteration", session)
    m = s.session
    _three_shot_board(m)
    m.review(KIND_STORY)
    first = m.simulate_storyboard()
    s.step(f"Inspect completed simulated sequence {first.run_id}")
    expect(first.state == "Completed", "first candidate completed")
    s.step("Change a shot: the old summary is stale")
    shot = m.story.draft.shots[1]
    m.update_shot(shot.shot_id, prompt="Tilt up much faster")
    expect(m.status(KIND_STORY) == Status.STALE, "old summary is stale")
    refused(m.simulate_storyboard, "stale")
    s.step("Review again and simulate a NEW independent candidate")
    m.review(KIND_STORY)
    second = m.simulate_storyboard()
    expect(second.run_id != first.run_id, "new identity")
    expect(first in m.runs and second in m.runs, "history is never overwritten")
    expect(first.resolved[1].prompt == "Tilt up to the dusk sky", "old snapshot is frozen")
    diff = diff_runs(first, second)
    expect(any("prompt" in line for line in diff), f"diff names the change: {diff}")
    s.step("A completed sequence has nothing to resume; an edited plan is a new candidate")
    ok, why = resume_eligibility(first, m.story.draft)
    expect(not ok and "nothing to resume" in why.lower(), why)
    return s.done("success", f"candidates {first.run_id} and {second.run_id} coexist")


def motion_06_movie_clips(session: MotionSession | None = None) -> WalkthroughResult:
    s = _script("MOTION-06", "Movie Clips", session)
    m = s.session
    s.step("Pick simulated clips from fixture history (explicit order, not filename order)")
    wanted = ["hist-run-1-clip-3", "hist-run-1-clip-1", "hist-run-1-clip-2"]
    added = m.add_clips(wanted)
    expect([i.clip_id for i in added] == wanted, "order preserved exactly as authored")
    s.step("Reorder: move the last clip to the front")
    m.move_item(m.assembly.draft.items[2].item_id, -2)
    order = [i.clip_id for i in m.assembly.draft.items]
    expect(order == ["hist-run-1-clip-2", "hist-run-1-clip-3", "hist-run-1-clip-1"], order)
    s.step("Trim intent, imported audio fixture and export profile")
    m.set_trim(m.assembly.draft.items[0].item_id, 2, 1)
    m.update_assembly(audio_key="audio:score", profile="recommended", transition="crossfade")
    s.step("A crossfade longer than half the shortest clip is refused; use a hard cut")
    expect(any("Crossfade" in e for e in m.review(KIND_MOVIE).errors), "crossfade refusal")
    m.update_assembly(transition="cut")
    s.step("Review the final order and estimated duration")
    preview = m.review(KIND_MOVIE)
    expect(preview.errors == (), f"assembly ready: {preview.errors}")
    expect(m.status(KIND_MOVIE) == Status.READY, "ready for mock assembly")
    s.step("Simulate assembly: a separate identity from the clips")
    result = m.simulate_assembly()
    expect(result.movie_id.startswith("mock-movie") and result.movie_id not in m.clips, "identity")
    expect(result.clip_ids == tuple(order), "result preserves clip order")
    return s.done("success", f"{result.movie_id}: {result.seconds:.2f} s illustrated, not encoded")


def motion_07_failure_and_recovery(session: MotionSession | None = None) -> WalkthroughResult:
    s = _script("MOTION-07", "Failure and recovery", session)
    m = s.session
    s.step("Missing source media is refused and nothing is substituted")
    refused(lambda: m.select_source("history:missing"), "Missing file")
    expect(m.quick.draft is None, "no substitute selected")
    s.step("Changed anchor blocks until its current media is explicitly accepted")
    _three_shot_board(m)
    anchored = m.story.draft.shots[1]
    m.update_shot(anchored.shot_id, anchor_key="anchor:ridge-dusk")
    m.review(KIND_STORY)
    expect(m.status(KIND_STORY) == Status.READY, "anchor is fine at first")
    m.catalog.replace_media("anchor:ridge-dusk")
    expect(m.status(KIND_STORY) == Status.STALE, "changed media makes the summary stale")
    preview = m.review(KIND_STORY)
    expect(any("changed" in e for e in preview.errors), "changed anchor blocks")
    m.accept_anchor_media(anchored.shot_id)
    m.review(KIND_STORY)
    expect(m.status(KIND_STORY) == Status.READY, "explicit acceptance recovers")
    s.step("An explicitly empty shot prompt blocks readiness")
    m.update_shot(m.story.draft.shots[2].shot_id, prompt="")
    preview = m.review(KIND_STORY)
    expect(any("explicitly empty" in e for e in preview.errors), "explicit empty is invalid")
    m.update_shot(m.story.draft.shots[2].shot_id, prompt=None)
    s.step("Stale version: another session saved first")
    saved = m.save_storyboard()
    m.update_story(title="Edited locally")
    m.store.external_save(saved.storyboard_id)
    try:
        m.save_storyboard()
        raise WalkthroughError("stale save must be refused")
    except StaleSave:
        s.step("Recover with Save As (a new Storyboard identity)")
    copy = m.save_storyboard_as("Edited locally copy")
    expect(copy.storyboard_id != saved.storyboard_id and copy.base_revision == 1, "Save As")
    s.step("Declining an unsaved-draft replacement keeps the draft")
    m.select_source(CREATE_SOURCE)
    m.update_quick(prompt="Keep me")
    expect(not m.receive_source(EDIT_SOURCE, "edit", Replacement.CANCEL), "declined")
    expect(m.quick.draft.prompt == "Keep me", "draft preserved")
    s.step("Unsupported resume is explained, not offered")
    m.update_story(drill_fail_shot=m.story.draft.shots[1].shot_id)
    m.review(KIND_STORY)
    failed = m.simulate_storyboard()
    expect(failed.state == "Failed" and failed.completed_prefix == 1, "failed with a prefix")
    m.update_shot(m.story.draft.shots[0].shot_id, prompt="A changed first shot")
    ok, why = resume_eligibility(failed, m.story.draft)
    expect(not ok and "plan changed" in why, why)
    return s.done("recoverable", "every failure explained with a way forward; no state lost")


ALL: tuple[Callable[..., WalkthroughResult], ...] = (
    motion_01_quick_clip,
    motion_02_handoff,
    motion_03_storyboard,
    motion_04_consent_and_compatibility,
    motion_05_sequence_iteration,
    motion_06_movie_clips,
    motion_07_failure_and_recovery,
)


def run_all() -> list[WalkthroughResult]:
    return [walk() for walk in ALL]


def failed_assembly_demo() -> WalkthroughResult:
    """Assembly failure keeps the source list (used by the walkthrough document and tests)."""
    s = _script("MOTION-06b", "Assembly failure")
    m = s.session
    m.add_clips(["hist-run-1-clip-1", "hist-run-1-clip-2"])
    m.update_assembly(drill_failure=True)
    m.review(KIND_MOVIE)
    result = m.simulate_assembly()
    expect(result.status == "failed" and len(m.assembly.draft.items) == 2, "list retained")
    return s.done("recoverable", result.failure)


__all__ = [
    "ALL",
    "WalkthroughError",
    "WalkthroughResult",
    "describe_run",
    "failed_assembly_demo",
    "replace",
    "run_all",
]
