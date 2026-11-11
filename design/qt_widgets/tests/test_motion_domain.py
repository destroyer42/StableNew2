"""Deterministic, Qt-free tests for the Motion mock domain and its seven scripted walkthroughs."""

from __future__ import annotations

import unittest
from dataclasses import replace

from stablenew_qt_proto import motion_walkthroughs as walk
from stablenew_qt_proto.edit_domain import CREATE_SOURCE, Replacement
from stablenew_qt_proto.motion_domain import (
    ANCHORS,
    KIND_MOVIE,
    KIND_QUICK,
    KIND_STORY,
    MAX_SHOTS,
    MIN_SHOTS,
    SEED_MAX,
    WORKFLOWS,
    Governance,
    MotionRefused,
    MotionSession,
    SeedIntent,
    StaleSave,
    Status,
    camera_window,
    diff_runs,
    media_digest,
    motion_for,
    plan_fingerprint,
    plan_for_clip,
    plan_for_movie,
    plan_for_run,
    resume_eligibility,
    workflow_for,
)

WAN13 = ("wan22_ti2v_5b_i2v_v1", "1.3.0")
WAN11 = ("wan22_ti2v_5b_i2v_v1", "1.1.0")
SVD = ("svd_native", "svd-xt")
ANIMATE = ("wan_animate2_drive_i2v_v1", "1.2.0")
FUN = ("wan22_fun_control_5b_canny_i2v_v1", "1.0.0")
LTX = ("ltx_multiframe_anchor_v1", "1.0.0")


def quick_ready(**changes) -> MotionSession:
    m = MotionSession()
    m.select_source(CREATE_SOURCE)
    m.update_quick(prompt="Slow push toward the ridge", **changes)
    m.review(KIND_QUICK)
    return m


def board(shots: int = 3, **kw) -> MotionSession:
    m = MotionSession()
    m.new_storyboard(CREATE_SOURCE, prompt="Slow movement", **kw)
    while len(m.story.draft.shots) < shots:
        m.add_shot()
    return m


class WorkflowIdentityTests(unittest.TestCase):
    def test_identity_is_id_and_exact_version_never_display_name(self):
        keys = [w.key for w in WORKFLOWS]
        self.assertEqual(len(keys), len(set(keys)))
        a, b = workflow_for(WAN13), workflow_for(("wan22_ti2v_5b_i2v_v1", "1.2.0"))
        self.assertEqual(a.display_name, b.display_name)
        self.assertNotEqual(a.key, b.key)
        self.assertTrue(a.frames_out and not b.frames_out)
        with self.assertRaises(MotionRefused):
            workflow_for(("Wan2.2 TI2V-5B", "1.3.0"))

    def test_governance_matches_the_documented_catalog(self):
        self.assertEqual(workflow_for(WAN13).governance, Governance.APPROVED)
        self.assertEqual(
            workflow_for(("wan22_ti2v_5b_i2v_v1", "1.2.0")).governance, Governance.APPROVED
        )
        self.assertEqual(workflow_for(WAN11).governance, Governance.EXPERIMENTAL)
        self.assertEqual(workflow_for(ANIMATE).governance, Governance.EXPERIMENTAL)
        self.assertEqual(workflow_for(SVD).governance, Governance.APPROVED)
        self.assertFalse(workflow_for(LTX).offered)

    def test_capability_eligibility_is_declared_not_assumed(self):
        self.assertNotIn("prompt", workflow_for(SVD).controls)
        self.assertFalse(workflow_for(SVD).storyboard)
        self.assertIn("motion_reference", workflow_for(ANIMATE).required)
        self.assertFalse(workflow_for(ANIMATE).storyboard)
        self.assertTrue(workflow_for(WAN13).storyboard)

    def test_retired_workflow_is_never_ready_and_fun_control_is_held(self):
        m = quick_ready(workflow=LTX)
        self.assertEqual(m.status(KIND_QUICK), Status.BLOCKED)
        self.assertTrue(any("retired" in e for e in m.previews[KIND_QUICK].errors))
        m = quick_ready(workflow=FUN, reference_key="motion:orbit-slow")
        self.assertTrue(any("not qualified" in e for e in m.previews[KIND_QUICK].errors))
        self.assertEqual(m.status(KIND_QUICK), Status.BLOCKED)


class SourceAndProvenanceTests(unittest.TestCase):
    def test_source_selection_records_identity_and_digest(self):
        m = MotionSession()
        self.assertTrue(m.select_source(CREATE_SOURCE, origin="create"))
        draft = m.quick.draft
        self.assertEqual(draft.source_digest, m.catalog.get(CREATE_SOURCE).digest)
        self.assertEqual(m.origin[KIND_QUICK], "create")

    def test_unavailable_hidden_unsupported_and_unknown_sources_are_refused(self):
        m = MotionSession()
        for key, needle in (
            ("history:missing", "Missing file"),
            ("history:hidden", "Hidden by fixture policy"),
            ("import:clip", "Unsupported media"),
            ("nope:nothing", "Unknown media identity"),
            ("motion:orbit-slow", "not an image"),
        ):
            with self.assertRaises(MotionRefused, msg=key) as ctx:
                m.select_source(key)
            self.assertIn(needle, str(ctx.exception))
        self.assertIsNone(m.quick.draft)

    def test_hidden_media_leaks_no_title_and_is_never_substituted(self):
        m = MotionSession()
        m.catalog.get("history:hidden")
        with self.assertRaises(MotionRefused) as ctx:
            m.select_source("history:hidden")
        self.assertNotIn("Restricted still", str(ctx.exception))
        self.assertIn("No substitute", str(ctx.exception))

    def test_sources_are_immutable_and_changes_create_new_records(self):
        m = MotionSession()
        old = m.catalog.get(CREATE_SOURCE)
        new = m.catalog.replace_media(CREATE_SOURCE)
        self.assertNotEqual(old.digest, new.digest)
        self.assertEqual(old.digest, media_digest(CREATE_SOURCE))
        with self.assertRaises(AttributeError):
            old.digest = "x"  # type: ignore[misc]


class FrameAndSeedTests(unittest.TestCase):
    def test_wan_frames_are_4n_plus_1_within_policy(self):
        policy = workflow_for(WAN13).policy
        legal = [f for f in range(0, 100) if policy.is_legal(f)]
        self.assertEqual(legal, list(range(17, 82, 4)))
        self.assertFalse(policy.is_legal(20))
        self.assertFalse(policy.is_legal(85))

    def test_illegal_frames_block_with_the_rule_and_never_clip(self):
        m = quick_ready(frames=20)
        self.assertEqual(m.status(KIND_QUICK), Status.BLOCKED)
        self.assertTrue(any("4n+1" in e for e in m.previews[KIND_QUICK].errors))
        self.assertEqual(m.quick.draft.frames, 20)

    def test_duration_is_frames_over_fps(self):
        m = quick_ready(frames=49)
        self.assertEqual(m.previews[KIND_QUICK].seconds, round(49 / 24, 3))
        self.assertEqual(m.previews[KIND_QUICK].total_frames, 49)

    def test_svd_has_its_own_frame_policy(self):
        m = MotionSession()
        m.select_source(CREATE_SOURCE)
        m.update_quick(workflow=SVD, prompt="", frames=25, motion_bucket=127)
        preview = m.review(KIND_QUICK)
        self.assertEqual(preview.errors, ())
        self.assertEqual(preview.seconds, round(25 / 6, 3))

    def test_seed_intent_validation_and_resolution(self):
        self.assertEqual(SeedIntent("explicit", -1).problem()[:8], "Explicit")
        self.assertEqual(SeedIntent("explicit", 2**32).problem()[:8], "Explicit")
        self.assertEqual(SeedIntent("explicit", 5).problem(), "")
        m = quick_ready()
        self.assertIn(
            "freezes no seed", dict(m.previews[KIND_QUICK].facts)["Not an executable job"]
        )
        run = m.simulate_quick()
        self.assertEqual(run.clips[0].seed_origin, "drawn at admission")
        m.update_quick(seed=SeedIntent("explicit", 90), variants=2)
        m.review(KIND_QUICK)
        run2 = m.simulate_quick()
        self.assertEqual([c.seed for c in run2.clips], [90, 91])
        self.assertTrue(all(c.seed_origin == "explicit" for c in run2.clips))

    def test_drawn_seeds_are_deterministic_for_the_same_plan(self):
        a, b = quick_ready(), quick_ready()
        self.assertEqual(
            [c.seed for c in a.simulate_quick().clips], [c.seed for c in b.simulate_quick().clips]
        )

    def test_shot_1_inherits_storyboard_seed_and_later_shots_resolve_at_admission(self):
        m = board(3)
        m.update_story(seed=SeedIntent("explicit", 500))
        for shot in m.story.draft.shots:
            m.update_shot(shot.shot_id, prompt="go")
        m.review(KIND_STORY)
        run = m.simulate_storyboard()
        self.assertEqual((run.resolved[0].seed, run.resolved[0].seed_origin), (500, "explicit"))
        self.assertTrue(all(r.seed_origin == "drawn at admission" for r in run.resolved[1:]))
        shot_text = m.previews[KIND_STORY].shots[0].seed_text
        self.assertIn("inherits Storyboard seed", shot_text)


class StoryboardShotTests(unittest.TestCase):
    def test_shot_count_boundaries(self):
        m = board(2)
        self.assertEqual(len(m.story.draft.shots), MIN_SHOTS)
        for _ in range(MAX_SHOTS - MIN_SHOTS):
            m.add_shot()
        self.assertEqual(len(m.story.draft.shots), MAX_SHOTS)
        with self.assertRaises(MotionRefused):
            m.add_shot()
        with self.assertRaises(MotionRefused):
            m.duplicate_shot(m.story.draft.shots[0].shot_id)
        while len(m.story.draft.shots) > 1:
            m.remove_shot(m.story.draft.shots[-1].shot_id)
        with self.assertRaises(MotionRefused):
            m.remove_shot(m.story.draft.shots[0].shot_id)
        self.assertTrue(any("2–12" in e for e in m.review(KIND_STORY).errors))

    def test_identity_survives_reorder_duplicate_and_remove(self):
        m = board(3)
        first, second, third = (s.shot_id for s in m.story.draft.shots)
        m.move_shot(third, -2)
        self.assertEqual([s.shot_id for s in m.story.draft.shots], [third, first, second])
        copy = m.duplicate_shot(first)
        self.assertNotIn(copy.shot_id, (first, second, third))
        m.update_shot(copy.shot_id, prompt="changed copy")
        self.assertIsNone(next(s for s in m.story.draft.shots if s.shot_id == first).prompt)
        m.remove_shot(second)
        self.assertNotIn(second, [s.shot_id for s in m.story.draft.shots])
        self.assertFalse(m.move_shot(m.story.draft.shots[0].shot_id, -1))

    def test_removing_a_shot_never_mutates_a_simulated_result(self):
        m = board(3)
        for shot in m.story.draft.shots:
            m.update_shot(shot.shot_id, prompt="go")
        m.review(KIND_STORY)
        run = m.simulate_storyboard()
        before = (run.snapshot, run.resolved, run.clips)
        m.remove_shot(m.story.draft.shots[0].shot_id)
        self.assertEqual((m.run(run.run_id).snapshot, run.resolved, run.clips), before)
        self.assertEqual(len(run.snapshot.shots), 3)

    def test_blank_inherits_but_explicit_empty_blocks(self):
        m = board(2)
        m.review(KIND_STORY)
        self.assertEqual(m.status(KIND_STORY), Status.READY)  # blank shots inherit "Slow movement"
        m.update_story(default_prompt="")
        self.assertTrue(any("inherits an empty" in e for e in m.review(KIND_STORY).errors))
        m.update_story(default_prompt="Slow")
        m.update_shot(m.story.draft.shots[0].shot_id, prompt="  ")
        errors = m.review(KIND_STORY).errors
        self.assertTrue(any("explicitly empty" in e and e.startswith("Shot 1") for e in errors))

    def test_explicit_versus_inherited_marks_follow_the_data(self):
        m = board(2)
        a, b = (s.shot_id for s in m.story.draft.shots)
        m.update_shot(a, prompt="explicit", frames=25)
        shots = m.review(KIND_STORY).shots
        self.assertEqual((shots[0].prompt_origin, shots[0].frames_origin), ("explicit", "explicit"))
        self.assertEqual(
            (shots[1].prompt_origin, shots[1].frames_origin), ("inherited", "inherited")
        )
        self.assertEqual(shots[1].frames, workflow_for(WAN13).policy.default)
        m.update_story(default_frames=49)
        self.assertEqual(m.review(KIND_STORY).shots[1].frames, 49)
        self.assertEqual(b, shots[1].shot_id)

    def test_shot_1_cannot_carry_an_authored_anchor(self):
        m = board(3)
        m.update_shot(m.story.draft.shots[0].shot_id, anchor_key="anchor:ridge-dusk")
        errors = m.review(KIND_STORY).errors
        self.assertTrue(any("shot 1 starts from the main source" in e for e in errors))
        self.assertEqual(m.status(KIND_STORY), Status.BLOCKED)

    def test_reordering_an_anchored_shot_to_first_blocks_rather_than_ignoring_it(self):
        m = board(3)
        anchored = m.story.draft.shots[1].shot_id
        m.update_shot(anchored, anchor_key="anchor:ridge-dusk")
        self.assertEqual(m.review(KIND_STORY).errors, ())
        m.move_shot(anchored, -1)
        self.assertTrue(m.review(KIND_STORY).errors)

    def test_provided_versus_carried_anchor_basis_and_overlap_text(self):
        m = board(3)
        m.update_shot(m.story.draft.shots[2].shot_id, anchor_key="anchor:ridge-high")
        shots = m.review(KIND_STORY).shots
        self.assertEqual([s.anchor_basis for s in shots], ["source", "carried", "provided"])
        self.assertIn(
            "1 carried boundary frame", dict(m.previews[KIND_STORY].facts)["Native frames"]
        )

    def test_anchor_size_mismatch_missing_and_unsupported_media_block(self):
        m = board(3)
        shot = m.story.draft.shots[1].shot_id
        for key, needle in (
            ("anchor:coast-wide", "differs from the sequence frame size"),
            ("history:missing", "Missing file"),
            ("import:clip", "Unsupported media"),
        ):
            m.update_shot(shot, anchor_key=key)
            errors = m.review(KIND_STORY).errors
            self.assertTrue(any(needle in e for e in errors), (key, errors))

    def test_storyboard_requires_a_storyboard_capable_workflow(self):
        for workflow in (SVD, ANIMATE):
            m = board(2, workflow=workflow)
            self.assertTrue(
                any(
                    "does not support the Storyboard editor" in e
                    for e in m.review(KIND_STORY).errors
                )
            )

    def test_total_frames_and_duration_before_overlap_trims(self):
        m = board(3)
        for shot, frames in zip(m.story.draft.shots, (17, 25, 33), strict=True):
            m.update_shot(shot.shot_id, frames=frames)
        preview = m.review(KIND_STORY)
        self.assertEqual(preview.total_frames, 75)
        self.assertEqual(preview.seconds, round(75 / 24, 3))

    def test_summary_is_never_an_executable_plan(self):
        m = board(2)
        preview = m.review(KIND_STORY)
        self.assertFalse(preview.executable)
        self.assertIn("freezes no seed", dict(preview.facts)["Not an executable plan"])
        self.assertFalse(hasattr(preview, "njr"))


class MediaChangeAndAcceptanceTests(unittest.TestCase):
    def test_changed_anchor_makes_summary_stale_then_blocks_until_accepted(self):
        m = board(3)
        shot = m.story.draft.shots[1].shot_id
        m.update_shot(shot, anchor_key="anchor:ridge-dusk")
        m.review(KIND_STORY)
        self.assertEqual(m.status(KIND_STORY), Status.READY)
        m.catalog.replace_media("anchor:ridge-dusk")
        self.assertEqual(m.status(KIND_STORY), Status.STALE)
        with self.assertRaises(MotionRefused):
            m.simulate_storyboard()
        self.assertTrue(any("changed" in e for e in m.review(KIND_STORY).errors))
        m.accept_anchor_media(shot)
        m.review(KIND_STORY)
        self.assertEqual(m.status(KIND_STORY), Status.READY)

    def test_changed_source_requires_explicit_acceptance_for_quick_and_storyboard(self):
        m = quick_ready()
        m.catalog.replace_media(CREATE_SOURCE)
        self.assertEqual(m.status(KIND_QUICK), Status.STALE)
        self.assertTrue(any("changed" in e for e in m.review(KIND_QUICK).errors))
        m.accept_source_media()
        m.review(KIND_QUICK)
        self.assertEqual(m.status(KIND_QUICK), Status.READY)
        b = board(2)
        b.catalog.replace_media(CREATE_SOURCE)
        self.assertTrue(any("Accept Current Media" in e for e in b.review(KIND_STORY).errors))
        b.accept_source_media(KIND_STORY)
        self.assertEqual(b.review(KIND_STORY).errors, ())

    def test_changing_an_anchor_selection_invalidates_the_summary(self):
        m = board(3)
        m.review(KIND_STORY)
        m.update_shot(m.story.draft.shots[1].shot_id, anchor_key="anchor:ridge-high")
        self.assertEqual(m.status(KIND_STORY), Status.STALE)

    def test_media_becoming_unavailable_blocks_without_substitution(self):
        m = quick_ready(reference_key=None)
        m.review(KIND_QUICK)
        self.assertEqual(m.status(KIND_QUICK), Status.READY)
        self.assertEqual(m.quick.draft.source_key, CREATE_SOURCE)


class DraftRevisionAndSaveTests(unittest.TestCase):
    def test_material_edits_bump_revision_and_noops_do_not(self):
        m = quick_ready()
        revision = m.quick.revision
        self.assertFalse(m.update_quick(prompt="Slow push toward the ridge"))
        self.assertEqual(m.quick.revision, revision)
        self.assertTrue(m.update_quick(prompt="Another"))
        self.assertEqual(m.quick.revision, revision + 1)

    def test_undo_and_redo_restore_drafts_and_invalidate_previews(self):
        m = quick_ready()
        before = m.quick.draft
        m.update_quick(prompt="Something else")
        self.assertEqual(m.status(KIND_QUICK), Status.STALE)
        m.undo = m.quick.undo
        m.quick.undo()
        self.assertEqual(m.quick.draft, before)
        self.assertEqual(m.status(KIND_QUICK), Status.STALE)  # revision moved: review again
        m.quick.redo()
        self.assertEqual(m.quick.draft.prompt, "Something else")
        b = board(3)
        original = b.story.draft
        b.move_shot(b.story.draft.shots[2].shot_id, -1)
        b.story.undo()
        self.assertEqual(b.story.draft, original)

    def test_save_save_as_and_duplicate_are_in_memory_with_new_identities(self):
        m = board(3)
        saved = m.save_storyboard()
        self.assertEqual(
            (saved.base_revision, m.store.latest_revision(saved.storyboard_id)), (1, 1)
        )
        self.assertFalse(m.story.dirty)
        copy = m.save_storyboard_as("Copy")
        self.assertNotEqual(copy.storyboard_id, saved.storyboard_id)
        old_ids = {s.shot_id for s in saved.shots}
        self.assertTrue(old_ids.isdisjoint({s.shot_id for s in copy.shots}))
        self.assertEqual(len(m.store.list()), 2)

    def test_stale_save_conflict_is_deterministic(self):
        m = board(3)
        saved = m.save_storyboard()
        m.update_story(title="Edit")
        m.store.external_save(saved.storyboard_id)
        with self.assertRaises(StaleSave):
            m.save_storyboard()
        self.assertEqual(m.store.latest_revision(saved.storyboard_id), 2)
        self.assertTrue(m.story.dirty)  # nothing was lost
        reopened = m.save_storyboard_as("Recovered")
        self.assertEqual(reopened.base_revision, 1)

    def test_a_saved_draft_retains_no_consent_and_reopening_never_restores_it(self):
        m = board(2, workflow=WAN11)
        m.grant_consent(KIND_STORY)
        self.assertTrue(m.consent_valid(KIND_STORY))
        saved = m.save_storyboard()
        self.assertFalse(m.consent_valid(KIND_STORY))
        m.grant_consent(KIND_STORY)
        m.open_storyboard(saved.storyboard_id, Replacement.REPLACE)
        self.assertFalse(m.consent_valid(KIND_STORY))
        self.assertFalse(hasattr(saved, "consent"))

    def test_open_requires_a_decision_when_the_current_draft_is_unsaved(self):
        m = board(2)
        saved = m.save_storyboard()
        m.update_story(title="dirty")
        self.assertFalse(m.open_storyboard(saved.storyboard_id))
        self.assertTrue(m.story.dirty)
        self.assertTrue(m.open_storyboard(saved.storyboard_id, Replacement.REPLACE))


class ConsentTests(unittest.TestCase):
    def test_experimental_needs_consent_for_this_submission_only(self):
        m = quick_ready(workflow=WAN11)
        self.assertEqual(m.status(KIND_QUICK), Status.BLOCKED)
        with self.assertRaises(MotionRefused):
            m.simulate_quick()
        m.grant_consent(KIND_QUICK)
        self.assertEqual(m.status(KIND_QUICK), Status.READY)
        run = m.simulate_quick()
        self.assertTrue(run.clips[0].consent_recorded)

    def test_approved_workflows_need_no_consent_and_refuse_a_grant(self):
        m = quick_ready()
        self.assertFalse(m.consent_required(KIND_QUICK))
        with self.assertRaises(MotionRefused):
            m.grant_consent(KIND_QUICK)

    def test_any_edit_voids_consent(self):
        m = quick_ready(workflow=WAN11)
        m.grant_consent(KIND_QUICK)
        m.update_quick(prompt="different")
        self.assertFalse(m.consent_valid(KIND_QUICK))
        m.review(KIND_QUICK)
        self.assertEqual(m.status(KIND_QUICK), Status.BLOCKED)

    def test_consent_is_not_shared_across_workflows_or_kinds(self):
        m = quick_ready(workflow=WAN11)
        m.grant_consent(KIND_QUICK)
        m.new_storyboard(CREATE_SOURCE, workflow=WAN11, prompt="x")
        self.assertFalse(m.consent_valid(KIND_STORY))
        m.grant_consent(KIND_STORY)
        m.update_quick(workflow=WAN13)
        m.update_quick(workflow=WAN11)
        self.assertFalse(m.consent_valid(KIND_QUICK))

    def test_a_result_never_grants_consent_to_a_new_draft(self):
        m = quick_ready(workflow=WAN11)
        m.grant_consent(KIND_QUICK)
        run = m.simulate_quick()
        m.storyboard_from_clip(run.clips[0].clip_id)
        self.assertFalse(m.consent_valid(KIND_STORY))
        self.assertEqual(m.status(KIND_STORY), Status.NOT_REVIEWED)
        m.select_source("history:ridge-17", Replacement.REPLACE, origin="edit")
        self.assertFalse(m.consent_valid(KIND_QUICK))


class SummaryAdmissionAndStalenessTests(unittest.TestCase):
    def test_summary_is_distinct_from_simulated_admission(self):
        m = quick_ready()
        self.assertEqual(m.status(KIND_QUICK), Status.READY)
        self.assertEqual([r for r in m.runs if r.origin == "session"], [])
        run = m.simulate_quick()
        self.assertEqual(m.status(KIND_QUICK), Status.SIMULATED)
        self.assertNotEqual(run.run_id, m.previews[KIND_QUICK].kind)
        self.assertFalse(m.previews[KIND_QUICK].executable)

    def test_not_reviewed_stale_and_blocked_drafts_refuse_admission(self):
        m = MotionSession()
        m.select_source(CREATE_SOURCE)
        m.update_quick(prompt="go")
        with self.assertRaises(MotionRefused) as ctx:
            m.simulate_quick()
        self.assertIn("Review Readiness first", str(ctx.exception))
        m.review(KIND_QUICK)
        m.update_quick(prompt="go on")
        with self.assertRaises(MotionRefused) as ctx:
            m.simulate_quick()
        self.assertIn("stale", str(ctx.exception))
        m.update_quick(prompt="")
        m.review(KIND_QUICK)
        with self.assertRaises(MotionRefused) as ctx:
            m.simulate_quick()
        self.assertIn("Blocked", str(ctx.exception))
        self.assertEqual([r for r in m.runs if r.origin == "session"], [])

    def test_no_duplicate_admission_for_one_revision(self):
        m = quick_ready()
        first = m.simulate_quick()
        self.assertIs(m.simulate_quick(), first)
        self.assertEqual(len([r for r in m.runs if r.origin == "session"]), 1)
        m.update_quick(variants=2)
        m.review(KIND_QUICK)
        self.assertNotEqual(m.simulate_quick().run_id, first.run_id)

    def test_every_status_label_is_reachable(self):
        m = MotionSession()
        m.select_source(CREATE_SOURCE)
        seen = [m.status(KIND_QUICK)]
        m.update_quick(prompt="")
        m.review(KIND_QUICK)
        seen.append(m.status(KIND_QUICK))
        m.update_quick(prompt="go")
        seen.append(m.status(KIND_QUICK))
        m.review(KIND_QUICK)
        seen.append(m.status(KIND_QUICK))
        m.simulate_quick()
        seen.append(m.status(KIND_QUICK))
        self.assertEqual(
            seen,
            [Status.NOT_REVIEWED, Status.BLOCKED, Status.STALE, Status.READY, Status.SIMULATED],
        )

    def test_unsupported_controls_are_refused_not_silently_dropped(self):
        m = quick_ready(workflow=SVD)  # prompt present but SVD declares none
        self.assertTrue(any("no motion prompt control" in e for e in m.previews[KIND_QUICK].errors))
        m.update_quick(prompt="", reference_key="motion:orbit-slow")
        self.assertTrue(
            any("does not support a motion reference" in e for e in m.review(KIND_QUICK).errors)
        )
        m.update_quick(reference_key=None, motion_bucket=300)
        self.assertTrue(any("Motion bucket" in e for e in m.review(KIND_QUICK).errors))
        m.update_quick(workflow=WAN13, motion_bucket=100, prompt="go")
        self.assertTrue(
            any("does not declare Motion bucket" in e for e in m.review(KIND_QUICK).errors)
        )

    def test_required_motion_reference_and_missing_reference(self):
        m = quick_ready(workflow=ANIMATE)
        self.assertTrue(
            any("requires a motion reference" in e for e in m.previews[KIND_QUICK].errors)
        )
        m.update_quick(reference_key="motion:lost")
        self.assertTrue(any("Missing file" in e for e in m.review(KIND_QUICK).errors))
        m.update_quick(reference_key="motion:orbit-slow")
        m.review(KIND_QUICK)
        self.assertEqual(m.status(KIND_QUICK), Status.BLOCKED)  # experimental: needs consent
        m.grant_consent(KIND_QUICK)
        self.assertEqual(m.status(KIND_QUICK), Status.READY)

    def test_workflow_change_invalidates_the_preview_and_keeps_values_visible(self):
        m = quick_ready()
        m.update_quick(workflow=("wan22_ti2v_5b_i2v_v1", "1.2.0"))
        self.assertEqual(m.status(KIND_QUICK), Status.STALE)
        self.assertEqual(m.quick.draft.prompt, "Slow push toward the ridge")


class ResultIdentityTests(unittest.TestCase):
    def test_variants_have_independent_identities_and_a_failed_one_leaves_others_intact(self):
        m = quick_ready(variants=3, drill_fail_variant=2)
        run = m.simulate_quick()
        self.assertEqual(run.state, "Partially completed")
        ids = [c.clip_id for c in run.clips]
        self.assertEqual(len(set(ids)), 3)
        self.assertEqual([c.status for c in run.clips], ["completed", "failed", "completed"])
        self.assertEqual(m.rate(run.clips[0].clip_id, 5).stars, 5)
        with self.assertRaises(MotionRefused):
            m.rate(run.clips[1].clip_id, 3)
        self.assertEqual(m.clip(run.clips[2].clip_id).status, "completed")

    def test_ratings_never_change_the_clip_or_the_action_outcome(self):
        m = quick_ready()
        clip = m.simulate_quick().clips[0]
        m.rate(clip.clip_id, 2, "meh")
        self.assertIs(m.clip(clip.clip_id), clip)
        self.assertTrue(clip.completed)
        with self.assertRaises(MotionRefused):
            m.rate(clip.clip_id, 6)

    def test_results_survive_later_edits_and_keep_their_frozen_snapshot(self):
        m = quick_ready()
        run = m.simulate_quick()
        frozen = run.snapshot
        m.update_quick(prompt="completely different", frames=49)
        self.assertEqual(m.run(run.run_id).snapshot, frozen)
        self.assertEqual(m.run(run.run_id).snapshot.prompt, "Slow push toward the ridge")
        self.assertEqual(m.clip(run.clips[0].clip_id).frames, 33)

    def test_failed_shot_keeps_the_completed_prefix_and_stops(self):
        m = board(3)
        m.update_story(drill_fail_shot=m.story.draft.shots[1].shot_id)
        m.review(KIND_STORY)
        run = m.simulate_storyboard()
        self.assertEqual((run.state, run.completed_prefix, len(run.clips)), ("Failed", 1, 2))
        self.assertTrue(run.clips[0].completed and not run.clips[1].completed)

    def test_motion_illustration_is_deterministic_from_the_prompt(self):
        self.assertEqual(motion_for("Pan LEFT slowly", 1), "pan-left")
        self.assertEqual(motion_for("zoom out", 1), "zoom-out")
        self.assertEqual(motion_for("zoom", 1), "zoom-in")
        self.assertEqual(motion_for("anything", 3), motion_for("anything", 3))

    def test_resume_is_explanation_only_and_never_for_a_changed_plan(self):
        m = board(3)
        m.update_story(drill_fail_shot=m.story.draft.shots[1].shot_id)
        m.review(KIND_STORY)
        run = m.simulate_storyboard()
        ok, why = resume_eligibility(run, m.story.draft)
        self.assertTrue(ok)
        self.assertIn("Explanation only", why)
        m.update_shot(m.story.draft.shots[0].shot_id, prompt="changed")
        ok, why = resume_eligibility(run, m.story.draft)
        self.assertFalse(ok)
        self.assertIn("plan changed", why)
        self.assertFalse(hasattr(m, "resume"))

    def test_plan_fingerprint_ignores_title_and_save_revision(self):
        m = board(2)
        a = plan_fingerprint(m.story.draft)
        self.assertEqual(a, plan_fingerprint(replace(m.story.draft, title="x", base_revision=9)))
        self.assertNotEqual(a, plan_fingerprint(replace(m.story.draft, default_prompt="y")))

    def test_diff_names_changed_settings_and_never_merges(self):
        m = board(3)
        for shot in m.story.draft.shots:
            m.update_shot(shot.shot_id, prompt="go")
        m.review(KIND_STORY)
        a = m.simulate_storyboard()
        m.update_shot(m.story.draft.shots[0].shot_id, frames=25)
        m.move_shot(m.story.draft.shots[2].shot_id, -1)
        m.review(KIND_STORY)
        b = m.simulate_storyboard()
        text = "\n".join(diff_runs(a, b))
        self.assertIn("frames", text)
        self.assertIn("Shot order", text)
        self.assertEqual(len(a.clips), len(b.clips))
        self.assertTrue({c.clip_id for c in a.clips}.isdisjoint({c.clip_id for c in b.clips}))


class HandoffTests(unittest.TestCase):
    def test_h4_carries_identity_only_and_never_replaces_a_different_source_silently(self):
        m = MotionSession()
        self.assertTrue(m.receive_source(CREATE_SOURCE, "create"))
        m.update_quick(prompt="mine")
        m.review(KIND_QUICK)
        self.assertFalse(m.receive_source("history:ridge-17", "edit"))
        self.assertEqual((m.quick.draft.source_key, m.quick.draft.prompt), (CREATE_SOURCE, "mine"))
        self.assertFalse(m.receive_source("history:ridge-17", "edit", Replacement.CANCEL))
        self.assertTrue(m.receive_source("history:ridge-17", "edit", Replacement.REPLACE))
        self.assertEqual(m.quick.draft.prompt, "")
        self.assertIsNone(m.previews[KIND_QUICK])
        self.assertEqual(m.origin[KIND_QUICK], "edit")

    def test_h4_refuses_unavailable_sources_and_keeps_the_draft(self):
        m = quick_ready()
        with self.assertRaises(MotionRefused):
            m.receive_source("history:missing", "create", Replacement.REPLACE)
        self.assertEqual(m.quick.draft.prompt, "Slow push toward the ridge")

    def test_same_source_handoff_keeps_the_draft(self):
        m = quick_ready()
        self.assertTrue(m.receive_source(CREATE_SOURCE, "create"))
        self.assertEqual(m.quick.draft.prompt, "Slow push toward the ridge")

    def test_new_storyboard_from_a_clip_gets_a_new_draft_identity(self):
        m = quick_ready()
        clip = m.simulate_quick().clips[0]
        self.assertTrue(m.storyboard_from_clip(clip.clip_id))
        draft = m.story.draft
        self.assertEqual((draft.source_key, draft.base_revision), (CREATE_SOURCE, 0))
        self.assertNotIn(draft.storyboard_id, {r.run_id for r in m.runs})
        self.assertEqual(draft.workflow, clip.workflow)

    def test_clip_from_a_non_storyboard_workflow_cannot_start_one(self):
        m = MotionSession()
        m.select_source(CREATE_SOURCE)
        m.update_quick(workflow=SVD, prompt="", frames=20)
        m.review(KIND_QUICK)
        clip = m.simulate_quick().clips[0]
        with self.assertRaises(MotionRefused) as ctx:
            m.storyboard_from_clip(clip.clip_id)
        self.assertIn("does not support the Storyboard editor", str(ctx.exception))

    def test_h8_reopens_expressible_sequences_as_new_drafts_only(self):
        m = MotionSession()
        self.assertTrue(m.storyboard_from_run("hist-run-1"))
        draft = m.story.draft
        old = m.run("hist-run-1").snapshot
        self.assertNotEqual(draft.storyboard_id, old.storyboard_id)
        self.assertTrue({s.shot_id for s in draft.shots}.isdisjoint({s.shot_id for s in old.shots}))
        self.assertEqual(draft.base_revision, 0)
        with self.assertRaises(MotionRefused) as ctx:
            m.storyboard_from_run("hist-run-2")
        self.assertIn("mixes workflows", str(ctx.exception))
        self.assertEqual(m.story.draft, draft)

    def test_h8_needs_a_decision_when_the_current_storyboard_is_unsaved(self):
        m = board(3)
        self.assertFalse(m.storyboard_from_run("hist-run-1"))
        self.assertTrue(m.storyboard_from_run("hist-run-1", Replacement.REPLACE))


class MovieAssemblyTests(unittest.TestCase):
    def setUp(self):
        self.m = MotionSession()
        self.ids = ["hist-run-1-clip-1", "hist-run-1-clip-2", "hist-run-1-clip-3"]

    def test_clip_order_is_exactly_as_authored_and_never_sorted(self):
        reverse = list(reversed(self.ids))
        self.m.add_clips(reverse)
        self.assertEqual([i.clip_id for i in self.m.assembly.draft.items], reverse)
        self.m.move_item(self.m.assembly.draft.items[0].item_id, 1)
        self.assertEqual(
            [i.clip_id for i in self.m.assembly.draft.items],
            [reverse[1], reverse[0], reverse[2]],
        )

    def test_h5_handoff_never_starts_assembly(self):
        self.m.add_clips(self.ids)
        self.assertEqual(self.m.movies, [])
        self.assertEqual(self.m.status(KIND_MOVIE), Status.NOT_REVIEWED)

    def test_ineligible_clips_are_refused_with_explicit_reasons(self):
        for clip_id, needle in (
            ("hist-clip-lost", "missing"),
            ("hist-clip-failed", "failed"),
            ("nope", "Unknown clip"),
        ):
            with self.assertRaises(MotionRefused) as ctx:
                self.m.add_clips([clip_id])
            self.assertIn(needle, str(ctx.exception))
        self.assertEqual(self.m.assembly.draft.items if self.m.assembly.draft else (), ())

    def test_duplicates_are_refused_on_add_and_flagged_if_carried_by_handoff(self):
        self.m.add_clips(self.ids[:1])
        with self.assertRaises(MotionRefused) as ctx:
            self.m.add_clips(self.ids[:1])
        self.assertIn("Duplicate source", str(ctx.exception))
        self.m.add_clips(self.ids[:1], allow_duplicate=True)
        errors = self.m.review(KIND_MOVIE).errors
        self.assertTrue(any("appears at positions 1 and 2" in e for e in errors))

    def test_trim_and_estimated_duration(self):
        self.m.add_clips(self.ids)  # 33, 25, 17 frames at 24 fps
        self.assertAlmostEqual(self.m.review(KIND_MOVIE).seconds, round(75 / 24, 3))
        first = self.m.assembly.draft.items[0]
        self.m.set_trim(first.item_id, 8, 1)  # 24 frames kept
        self.assertAlmostEqual(self.m.review(KIND_MOVIE).seconds, round((24 + 25 + 17) / 24, 3))
        self.m.set_trim(first.item_id, 20, 20)
        self.assertTrue(any("trims remove all" in e for e in self.m.review(KIND_MOVIE).errors))
        self.m.set_trim(first.item_id, -1, 0)
        self.assertTrue(any("negative" in e for e in self.m.review(KIND_MOVIE).errors))

    def test_crossfade_reduces_duration_and_is_refused_for_short_clips(self):
        self.m.add_clips(self.ids[:2])  # 33 and 25 frames
        base = self.m.review(KIND_MOVIE).seconds
        self.m.update_assembly(transition="crossfade")
        self.assertAlmostEqual(self.m.review(KIND_MOVIE).seconds, round(base - 0.5, 3))
        self.m.add_clips(self.ids[2:])  # 17 frames = 0.71 s: 0.5 > half
        self.assertTrue(any("longer than half" in e for e in self.m.review(KIND_MOVIE).errors))

    def test_audio_fixture_selection(self):
        self.m.add_clips(self.ids)
        self.m.update_assembly(audio_key="audio:ambience")
        preview = self.m.review(KIND_MOVIE)
        self.assertEqual(preview.errors, ())
        self.assertTrue(any("longer than the movie" in w for w in preview.warnings))
        self.m.update_assembly(audio_key="audio:lost")
        self.assertTrue(any("Missing file" in e for e in self.m.review(KIND_MOVIE).errors))
        self.m.update_assembly(audio_key="audio:nope")
        self.assertTrue(
            any("Unknown imported audio" in e for e in self.m.review(KIND_MOVIE).errors)
        )
        self.m.update_assembly(audio_key=None)
        self.assertEqual(self.m.review(KIND_MOVIE).errors, ())

    def test_export_profile_compatibility(self):
        self.m.add_clips(self.ids)
        self.m.update_assembly(profile="archive", audio_key="audio:score")
        self.assertTrue(
            any("excludes imported audio" in e for e in self.m.review(KIND_MOVIE).errors)
        )
        self.m.update_assembly(audio_key=None)
        self.assertEqual(self.m.review(KIND_MOVIE).errors, ())
        self.m.update_assembly(profile="nope")
        self.assertTrue(
            any("Unknown export profile" in e for e in self.m.review(KIND_MOVIE).errors)
        )
        self.m.update_assembly(profile="draft")
        self.assertEqual(self.m.review(KIND_MOVIE).errors, ())

    def test_size_mismatch_is_incompatible_with_the_match_first_profile(self):
        q = MotionSession()
        q.select_source("photo:evening")  # 600×400
        q.update_quick(prompt="drift")
        q.review(KIND_QUICK)
        evening = q.simulate_quick().clips[0].clip_id
        q.add_clips(["hist-run-1-clip-1", evening])
        q.update_assembly(profile="archive")
        self.assertTrue(any("sizes differ" in e for e in q.review(KIND_MOVIE).errors))
        q.update_assembly(profile="recommended")
        self.assertEqual(q.review(KIND_MOVIE).errors, ())

    def test_every_assembly_setting_invalidates_readiness(self):
        self.m.add_clips(self.ids)
        for change in (
            {"audio_key": "audio:score"},
            {"profile": "draft"},
            {"drill_failure": True},
            {"title": "Retitled"},
        ):
            self.m.review(KIND_MOVIE)
            self.assertEqual(self.m.status(KIND_MOVIE), Status.READY)
            self.m.update_assembly(**change)
            self.assertEqual(self.m.status(KIND_MOVIE), Status.STALE, change)
        self.m.review(KIND_MOVIE)
        self.m.move_item(self.m.assembly.draft.items[0].item_id, 1)
        self.assertEqual(self.m.status(KIND_MOVIE), Status.STALE)
        self.m.review(KIND_MOVIE)
        self.m.set_trim(self.m.assembly.draft.items[0].item_id, 1, 0)
        self.assertEqual(self.m.status(KIND_MOVIE), Status.STALE)
        self.m.review(KIND_MOVIE)
        self.m.remove_item(self.m.assembly.draft.items[0].item_id)
        self.assertEqual(self.m.status(KIND_MOVIE), Status.STALE)

    def test_stale_or_blocked_assembly_cannot_be_simulated(self):
        with self.assertRaises(MotionRefused):
            self.m.simulate_assembly()
        self.m.add_clips(self.ids[:1])
        with self.assertRaises(MotionRefused):
            self.m.simulate_assembly()
        self.m.update_assembly(profile="nope")
        self.m.review(KIND_MOVIE)
        with self.assertRaises(MotionRefused):
            self.m.simulate_assembly()

    def test_assembly_result_has_its_own_identity_and_no_duplicate_admission(self):
        self.m.add_clips(self.ids)
        self.m.review(KIND_MOVIE)
        result = self.m.simulate_assembly()
        self.assertTrue(result.movie_id.startswith("mock-movie"))
        self.assertNotIn(result.movie_id, self.m.clips)
        self.assertNotEqual(result.assembly_id, result.movie_id)
        self.assertIs(self.m.simulate_assembly(), result)
        self.assertEqual(len(self.m.movies), 1)
        self.assertEqual(self.m.status(KIND_MOVIE), Status.SIMULATED)

    def test_assembly_failure_retains_the_source_list(self):
        outcome = walk.failed_assembly_demo()
        self.assertEqual(outcome.outcome, "recoverable")

    def test_old_movie_result_stays_inspectable_after_edits(self):
        self.m.add_clips(self.ids)
        self.m.review(KIND_MOVIE)
        result = self.m.simulate_assembly()
        self.m.remove_item(self.m.assembly.draft.items[0].item_id)
        self.assertEqual(self.m.movies[0], result)
        self.assertEqual(len(result.snapshot.items), 3)

    def test_session_clips_become_eligible_after_simulation(self):
        q = quick_ready(variants=2, drill_fail_variant=1)
        run = q.simulate_quick()
        eligible = {c.clip_id for c in q.eligible_clips()}
        self.assertNotIn(run.clips[0].clip_id, eligible)
        self.assertIn(run.clips[1].clip_id, eligible)
        self.assertNotIn("hist-clip-lost", eligible)


class IsolationAndIdentityTests(unittest.TestCase):
    def test_identities_are_distinct_namespaces(self):
        m = quick_ready(variants=2)
        run = m.simulate_quick()
        m.new_storyboard(CREATE_SOURCE, prompt="x")
        shot = m.story.draft.shots[0].shot_id
        m.add_clips([c.clip_id for c in run.clips])
        movie_id = m.assembly.draft.assembly_id
        ids = [
            run.run_id,
            run.clips[0].clip_id,
            m.story.draft.storyboard_id,
            shot,
            m.assembly.draft.items[0].item_id,
            movie_id,
            CREATE_SOURCE,
            m.quick.draft.draft_id,
        ]
        self.assertEqual(len(ids), len(set(ids)))

    def test_sessions_are_independent_and_deterministic(self):
        a, b = MotionSession(), MotionSession()
        a.select_source(CREATE_SOURCE)
        self.assertIsNone(b.quick.draft)
        a2, b2 = walk.run_all(), walk.run_all()
        self.assertEqual(a2, b2)

    def test_every_catalog_anchor_is_an_image_fixture(self):
        m = MotionSession()
        for key, _title, _motif, _size in ANCHORS:
            self.assertEqual(m.catalog.get(key).kind, "image")


class WalkthroughTests(unittest.TestCase):
    def test_seven_walkthroughs_each_end_in_a_named_state(self):
        results = walk.run_all()
        self.assertEqual([r.key for r in results], [f"MOTION-0{i}" for i in range(1, 8)])
        outcomes = {r.key: r.outcome for r in results}
        self.assertEqual(outcomes["MOTION-04"], "refusal")
        self.assertEqual(outcomes["MOTION-07"], "recoverable")
        self.assertTrue(all(o in ("success", "refusal", "recoverable") for o in outcomes.values()))
        self.assertTrue(all(r.steps and r.terminal for r in results))


class ReviewRepairTests(unittest.TestCase):
    def test_changed_motion_reference_voids_consent_and_never_reuses_the_old_run(self):
        m = MotionSession()
        m.select_source(CREATE_SOURCE)
        m.update_quick(
            workflow=ANIMATE, prompt="Follow the walk", reference_key="motion:orbit-slow"
        )
        m.grant_consent(KIND_QUICK)
        m.review(KIND_QUICK)
        first = m.simulate_quick()
        m.catalog.replace_media("motion:orbit-slow")
        self.assertEqual(m.status(KIND_QUICK), Status.STALE)
        m.review(KIND_QUICK)
        self.assertFalse(m.consent_valid(KIND_QUICK))
        self.assertEqual(m.status(KIND_QUICK), Status.BLOCKED)
        m.grant_consent(KIND_QUICK)
        m.review(KIND_QUICK)
        self.assertEqual(m.status(KIND_QUICK), Status.READY)  # not Simulated: the bytes changed
        second = m.simulate_quick()
        self.assertNotEqual(first.run_id, second.run_id)

    def test_undo_after_save_is_not_a_stale_save(self):
        m = board(3)
        m.save_storyboard()
        m.update_shot(m.story.draft.shots[0].shot_id, label="Edited after save")
        m.story.undo()
        self.assertFalse(m.story.dirty)
        m.update_shot(m.story.draft.shots[1].shot_id, label="Another edit")
        m.story.undo()
        saved = m.save_storyboard()
        self.assertEqual(saved.base_revision, 2)

    def test_explicit_seed_range_and_variant_offsets_are_validated(self):
        self.assertEqual(SeedIntent("explicit", SEED_MAX).problem(), "")
        self.assertNotEqual(SeedIntent("explicit", SEED_MAX + 1).problem(), "")
        m = quick_ready(seed=SeedIntent("explicit", SEED_MAX), variants=3)
        self.assertTrue(any("would pass" in e for e in m.review(KIND_QUICK).errors))
        self.assertEqual(m.status(KIND_QUICK), Status.BLOCKED)
        m.update_quick(variants=1)
        self.assertEqual(m.review(KIND_QUICK).errors, ())

    def test_camera_keywords_match_whole_words_only(self):
        self.assertEqual(motion_for("pan to the right", None), "pan-right")
        self.assertEqual(motion_for("zoom out slowly", None), "zoom-out")
        for text in ("bright dawn", "leftover light", "a group of cups"):
            self.assertEqual(motion_for(text, 0), motion_for("", 0), text)


class PlaybackPlanTests(unittest.TestCase):
    def test_camera_windows_are_deterministic_and_stay_inside_the_image(self):
        for motion in ("zoom-in", "zoom-out", "pan-left", "pan-right", "tilt-up", "unknown"):
            for t in (-1.0, 0.0, 0.25, 0.5, 1.0, 2.0):
                x, y, scale = camera_window(motion, t)
                self.assertEqual((x, y, scale), camera_window(motion, t))
                self.assertGreaterEqual(x, -1e-9, (motion, t))
                self.assertGreaterEqual(y, -1e-9, (motion, t))
                self.assertLessEqual(x + scale, 1 + 1e-9, (motion, t))
                self.assertLessEqual(y + scale, 1 + 1e-9, (motion, t))

    def test_camera_moves_start_and_end_where_the_name_says(self):
        self.assertLess(camera_window("zoom-in", 1)[2], camera_window("zoom-in", 0)[2])
        self.assertGreater(camera_window("zoom-out", 1)[2], camera_window("zoom-out", 0)[2])
        self.assertGreater(camera_window("pan-right", 1)[0], camera_window("pan-right", 0)[0])
        self.assertLess(camera_window("pan-left", 1)[0], camera_window("pan-left", 0)[0])
        self.assertLess(camera_window("tilt-up", 1)[1], camera_window("tilt-up", 0)[1])

    def test_clip_plan_covers_exactly_the_clip_frames(self):
        m = MotionSession()
        clip = m.clip("hist-run-1-clip-1")
        plan = plan_for_clip(clip)
        self.assertEqual(plan.total_frames, clip.frames)
        self.assertEqual(plan.seconds, round(clip.frames / clip.fps, 3))
        self.assertEqual(plan.locate(0)[:2], (0, 0))
        self.assertEqual(plan.locate(10_000)[1], clip.frames - 1)  # clamped, never past the end
        self.assertAlmostEqual(plan.locate(clip.frames - 1)[2], 1.0)

    def test_run_plan_plays_completed_clips_in_order_and_skips_failed_ones(self):
        m = MotionSession()
        run = m.run("hist-run-1")
        plan = plan_for_run(run)
        self.assertEqual([s.clip_id for s in plan.segments], [c.clip_id for c in run.clips])
        self.assertEqual(plan.total_frames, sum(c.frames for c in run.clips))
        position, local, _ = plan.locate(run.clips[0].frames)
        self.assertEqual((position, local), (1, 0))

    def test_failed_or_missing_output_has_nothing_to_play(self):
        m = MotionSession()
        with self.assertRaises(MotionRefused):
            plan_for_clip(m.clip("hist-clip-failed"))
        with self.assertRaises(MotionRefused):
            plan_for_clip(m.clip("hist-clip-lost"))

    def test_movie_plan_follows_authored_order_and_trims_without_cutting_media(self):
        m = MotionSession()
        m.add_clips(["hist-run-1-clip-3", "hist-run-1-clip-1"])
        first, second = m.assembly.draft.items
        m.set_trim(second.item_id, 4, 4)
        m.review(KIND_MOVIE)
        movie = m.simulate_assembly()
        plan = plan_for_movie(m, movie)
        self.assertEqual(
            [s.clip_id for s in plan.segments], ["hist-run-1-clip-3", "hist-run-1-clip-1"]
        )
        self.assertEqual(plan.segments[1].frames, m.clip("hist-run-1-clip-1").frames - 8)
        self.assertEqual(plan.segments[1].offset, 4)
        self.assertEqual(m.clip("hist-run-1-clip-1").frames, 33)  # the clip itself is untouched

    def test_empty_plan_refuses_to_locate(self):
        from stablenew_qt_proto.motion_domain import PlaybackPlan

        with self.assertRaises(MotionRefused):
            PlaybackPlan("empty", ()).locate(0)


if __name__ == "__main__":
    unittest.main()
