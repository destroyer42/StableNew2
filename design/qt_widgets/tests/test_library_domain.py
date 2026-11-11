"""Deterministic, Qt-free tests for the Asset Library mock domain (QT-DS-05)."""

from __future__ import annotations

import ast
import unittest
from dataclasses import replace
from pathlib import Path

from stablenew_qt_proto.domain import CreateSession
from stablenew_qt_proto.edit_domain import EditSession, Mode, Replacement
from stablenew_qt_proto.library_domain import (
    ILLUSTRATIVE_GROUPS,
    SIMILARITY_LABEL,
    UNKNOWN,
    ActionId,
    AssetRef,
    Availability,
    EmptyState,
    LibraryQuery,
    LibraryRefused,
    Scope,
    SearchMode,
    SelectionStatus,
    Sort,
    ViewState,
    describe,
    exact_groups,
    fixture_catalog,
    groups_of,
    run_query,
)
from stablenew_qt_proto.library_session import Destinations, LibrarySession, Outcome
from stablenew_qt_proto.library_walkthroughs import run_all
from stablenew_qt_proto.motion_domain import MotionSession

ROOT = Path(__file__).resolve().parents[1] / "stablenew_qt_proto"


def session(bulk: int = 120) -> LibrarySession:
    return LibrarySession(
        fixture_catalog(bulk),
        Destinations(EditSession(), MotionSession(), CreateSession()),
    )


class IdentityTests(unittest.TestCase):
    def test_source_qualified_ids_are_stable_and_unique(self):
        a, b = fixture_catalog(), fixture_catalog()
        self.assertEqual(a.keys(), b.keys())
        self.assertEqual(len(set(a.keys())), len(a))
        for record in a:
            self.assertEqual(AssetRef.parse(record.key), record.ref)
        with self.assertRaises(LibraryRefused):
            AssetRef.parse("no-namespace")

    def test_duplicate_hashes_keep_distinct_records(self):
        catalog = fixture_catalog()
        group = next(g for g in exact_groups(catalog) if "history:twin-a" in g.members)
        a, b = (catalog.get(k) for k in group.members[:2])
        self.assertEqual(a.content_hash, b.content_hash)
        self.assertNotEqual(a.ref, b.ref)
        self.assertNotEqual(a.job_id, b.job_id)
        self.assertNotEqual(catalog.observations_of(a.key), catalog.observations_of(b.key))
        self.assertTrue(group.exact)

    def test_unknown_source_is_refused_not_substituted(self):
        with self.assertRaises(LibraryRefused):
            fixture_catalog().get("history:does-not-exist")

    def test_unknown_fields_are_shown_as_unknown(self):
        rows = {r.name: r.value for r in describe(fixture_catalog().get("create:ridge-study"))}
        self.assertEqual(rows["Parent"], UNKNOWN)
        self.assertEqual(rows["Job / record lineage"], UNKNOWN)
        self.assertEqual(rows["Duration"], UNKNOWN)

    def test_catalog_covers_required_fixture_categories(self):
        c = fixture_catalog()
        kinds = {r.kind.value for r in c}
        self.assertTrue(
            {
                "Still image",
                "Edited candidate",
                "Video clip",
                "Storyboard sequence",
                "Motion reference",
                "Learning observation",
                "Unsupported type",
            }
            <= kinds
        )
        availabilities = {r.availability for r in c}
        self.assertEqual(availabilities, set(Availability))
        self.assertTrue(any(r.kind.value == "Edited candidate" and r.parent for r in c))
        self.assertTrue(any(r.kind.value == "Still image" and r.parent is None for r in c))
        self.assertGreaterEqual(len(c.observations_of("history:ridge-17")), 2)

    def test_theme_independent_domain(self):
        for name in ("library_domain.py", "library_session.py", "library_walkthroughs.py"):
            code = (ROOT / name).read_text(encoding="utf-8")
            self.assertNotIn("PySide6", code)
            self.assertNotIn("tokens", code)


class QueryTests(unittest.TestCase):
    def setUp(self):
        self.s = session()

    def test_metadata_filter_and_semantics(self):
        r = self.s.set_query(scope=Scope.HISTORY, models=frozenset({"fixture-flux"}), text="coast")
        self.assertEqual(r.matched, ("history:coast-04",))
        r = self.s.set_query(models=frozenset({"fixture-flux", "fixture-sdxl"}), text="coast study")
        self.assertEqual(r.matched, ("history:coast-04",))  # every word must match

    def test_filters_are_and_across_and_or_within(self):
        base = LibraryQuery(
            scope=Scope.ALL, kinds=frozenset({"Still image"}), models=frozenset({"fixture-flux"})
        )
        base = replace(
            base,
            kinds=frozenset(
                k
                for k in __import__(
                    "stablenew_qt_proto.library_domain", fromlist=["AssetKind"]
                ).AssetKind
                if k.value == "Still image"
            ),
        )
        r = run_query(self.s.catalog, self.s.org, base)
        self.assertTrue(all(self.s.catalog.get(k).model == "fixture-flux" for k in r.matched))

    def test_tags_require_all(self):
        self.s.add_tag(("history:ridge-16",), "keeper")
        r = self.s.set_query(tags=frozenset({"keeper", "ridge"}))
        self.assertEqual(r.matched, ("history:ridge-17",))
        r = self.s.set_query(tags=frozenset({"keeper"}))
        self.assertEqual(set(r.matched), {"history:ridge-16", "history:ridge-17"})

    def test_date_filter_reports_unknown_dates(self):
        r = self.s.set_query(date_from="2026-10-10", scope=Scope.ALL)
        self.assertTrue(
            all((self.s.catalog.get(k).created or "") >= "2026-10-10" for k in r.matched)
        )

    def test_model_filter_notice_for_unknown_model(self):
        r = self.s.set_query(scope=Scope.IMPORTED, models=frozenset({"fixture-sdxl"}))
        self.assertTrue(any("no model metadata" in n for n in r.notices))

    def test_prompt_prefix_is_bounded_and_distinct_from_metadata(self):
        r = self.s.set_query(
            scope=Scope.HISTORY, text="Harbor at first", mode=SearchMode.PROMPT_PREFIX
        )
        self.assertEqual(set(r.matched), {"history:twin-a", "history:twin-b"})
        r = self.s.set_query(text="first light", mode=SearchMode.PROMPT_PREFIX)
        self.assertEqual(r.matched, ())  # a prefix search is not a substring search
        r = self.s.set_query(text="x" * 80, mode=SearchMode.PROMPT_PREFIX)
        self.assertTrue(any("first 48" in n for n in r.notices))

    def test_sort_orders_are_deterministic_with_unknown_dates_last(self):
        recent = self.s.set_query(scope=Scope.IMPORTED, sort=Sort.RECENT).matched
        oldest = self.s.set_query(scope=Scope.IMPORTED, sort=Sort.OLDEST).matched
        self.assertEqual(
            recent,
            tuple(
                sorted(recent, key=lambda k: (self.s.catalog.get(k).created or ""), reverse=True)
            ),
        )
        self.assertEqual(set(recent), set(oldest))
        self.assertEqual(
            self.s.set_query(sort=Sort.LABEL).matched, self.s.set_query(sort=Sort.LABEL).matched
        )

    def test_pagination_and_continuation(self):
        r = self.s.set_query(page_size=10)
        self.assertEqual(len(r.items), 10)
        self.assertEqual(r.page_count, -(-r.total // 10))
        seen = []
        for page in range(r.page_count):
            seen += self.s.go_page(page).items
        self.assertEqual(tuple(seen), r.matched)
        last = self.s.go_page(999)
        self.assertEqual(last.page, r.page_count - 1)
        self.assertEqual(self.s.query.page, r.page_count - 1)

    def test_empty_source_versus_no_match(self):
        self.assertEqual(self.s.set_scope(Scope.FAVORITES).empty, EmptyState.EMPTY_SOURCE)
        r = self.s.set_scope(Scope.LEARNING)
        self.assertIsNone(r.empty)
        r = self.s.set_query(text="zzzz")
        self.assertEqual(r.empty, EmptyState.NO_MATCHES)
        self.assertEqual(r.scope_total, 4)  # never silently widened to other scopes
        self.assertEqual(self.s.clear_filters().total, 4)

    def test_invalid_page_size_and_collection_are_refused(self):
        with self.assertRaises(LibraryRefused):
            run_query(self.s.catalog, self.s.org, LibraryQuery(page_size=0))
        with self.assertRaises(LibraryRefused):
            self.s.set_query(collection="col-404")

    def test_query_is_independent_of_theme_and_repeatable(self):
        a = self.s.result()
        self.assertEqual(a, session().result())


class SelectionTests(unittest.TestCase):
    def setUp(self):
        self.s = session()

    def test_ordered_selection_survives_page_and_filter_changes(self):
        self.s.set_query(page_size=5)
        first = self.s.result().items[0]
        self.s.toggle(first)
        self.s.toggle("history:ridge-17")
        self.s.go_page(2)
        self.assertEqual(self.s.selection, (first, "history:ridge-17"))
        report = self.s.selection_report()
        self.assertEqual(report[first], SelectionStatus.OTHER_PAGE)
        self.s.set_scope(Scope.FAVORITES)
        self.assertEqual(set(self.s.selection_report().values()), {SelectionStatus.FILTERED_OUT})
        self.assertEqual(self.s.selection, (first, "history:ridge-17"))  # not silently replaced

    def test_narrow_moves_focus_off_a_dropped_item(self):
        items = self.s.result().items
        self.s.select_only(items[0])
        self.s.toggle(items[1])
        self.assertEqual(self.s.focus, items[1])
        self.s.narrow([items[0]])
        self.assertEqual(self.s.focus, items[0])

    def test_range_toggle_clear_and_narrow(self):
        items = self.s.result().items
        self.s.select_only(items[0])
        self.s.select_range(items[0], items[3])
        self.assertEqual(self.s.selection, items[:4])
        self.s.narrow([items[2], items[0]])
        self.assertEqual(self.s.selection, (items[0], items[2]))  # selected order kept
        with self.assertRaises(LibraryRefused):
            self.s.narrow([items[9]])
        self.s.clear_selection()
        self.assertEqual(self.s.selection, ())
        with self.assertRaises(LibraryRefused):
            self.s.toggle("nope:nothing")


class OrganizationTests(unittest.TestCase):
    def setUp(self):
        self.s = session()

    def test_collection_membership_references_originals(self):
        c = self.s.create_collection("Harbor", ("history:twin-a", "history:twin-b"))
        self.assertEqual(c.members, ("history:twin-a", "history:twin-b"))
        self.s.add_to_collection("col-1", ("history:twin-a",))
        self.assertEqual(
            {x.name for x in self.s.org.collections_of("history:twin-a")},
            {"Harbor", "Ridge project"},
        )
        self.assertIn("history:twin-a", self.s.catalog)

    def test_removal_is_non_destructive_and_rename_leaves_assets_alone(self):
        record = self.s.catalog.get("history:ridge-17")
        before_tags = self.s.org.tags_of("history:ridge-17")
        msg = self.s.remove_from_collection("col-1", ("history:ridge-17",))
        self.assertIn("not deleted", msg)
        self.assertIn("history:ridge-17", self.s.org.collection("col-2").members)
        self.assertIs(self.s.catalog.get("history:ridge-17"), record)
        self.assertEqual(self.s.org.tags_of("history:ridge-17"), before_tags)
        self.s.rename_collection("col-1", "Ridge work")
        self.assertIs(
            self.s.catalog.get("history:ridge-16"), self.s.catalog.get("history:ridge-16")
        )
        with self.assertRaises(LibraryRefused):
            self.s.rename_collection("col-1", "client review")  # case-insensitive duplicate
        with self.assertRaises(LibraryRefused):
            self.s.remove_from_collection("col-1", ("history:coast-04",))

    def test_unavailable_asset_stays_in_collection(self):
        self.s.add_to_collection("col-1", ("history:missing", "history:hidden"))
        self.s.simulate_vanish("history:ridge-16")
        self.assertIn("history:ridge-16", self.s.org.collection("col-1").members)
        self.assertEqual(self.s.effective("history:ridge-16"), Availability.MISSING)

    def test_tags_and_favorites_do_not_change_identity_and_undo_redo(self):
        record = self.s.catalog.get("history:coast-04")
        self.s.add_tag(("history:coast-04",), "  Sea  Side ")
        self.assertIn("sea side", self.s.org.tags_of("history:coast-04"))
        self.s.set_favorite(("history:coast-04",), True)
        self.assertEqual(self.s.set_scope(Scope.FAVORITES).matched, ("history:coast-04",))
        self.s.remove_tag(("history:coast-04",), "sea side")
        self.assertIs(self.s.catalog.get("history:coast-04"), record)
        self.s.undo()
        self.assertIn("sea side", self.s.org.tags_of("history:coast-04"))
        self.s.redo()
        self.assertNotIn("sea side", self.s.org.tags_of("history:coast-04"))
        with self.assertRaises(LibraryRefused):
            self.s.add_tag(("history:coast-04",), "a,b")

    def test_undo_of_creation_clears_a_dangling_collection_filter(self):
        c = self.s.create_collection("Temp")
        self.s.set_scope(Scope.COLLECTIONS, c.collection_id)
        self.s.undo()
        self.assertIsNone(self.s.query.collection)

    def test_simulated_photo_archive_and_restore(self):
        self.assertTrue(self.s.evaluate(ActionId.ARCHIVE_PHOTO, ("photo:evening",)).placeable)
        self.assertFalse(self.s.evaluate(ActionId.ARCHIVE_PHOTO, ("history:ridge-17",)).placeable)
        self.s.archive_photo(("photo:evening",))
        self.assertFalse(self.s.evaluate(ActionId.EDIT, ("photo:evening",)).placeable)
        self.assertIn("photo:evening", self.s.catalog)
        self.s.restore_photo(("photo:evening",))
        self.assertTrue(self.s.evaluate(ActionId.EDIT, ("photo:evening",)).placeable)
        with self.assertRaises(LibraryRefused):
            self.s.restore_photo(("photo:evening",))

    def test_general_archive_and_delete_are_future_gated(self):
        for action in (ActionId.ARCHIVE_GENERAL, ActionId.DELETE):
            e = self.s.evaluate(action, ("history:ridge-17",))
            self.assertTrue(e.gated and not e.placeable)
            self.assertIn("Future-gated", e.reason)
        self.assertFalse(hasattr(self.s, "delete"))


class GroupTests(unittest.TestCase):
    def test_similarity_is_labelled_illustrative_and_exact_is_not_ai(self):
        c = fixture_catalog()
        for g in ILLUSTRATIVE_GROUPS:
            self.assertEqual(g.label, SIMILARITY_LABEL)
            self.assertIn("No AI Analysis", g.label)
            self.assertIn("does not establish", g.caveat)
        groups = groups_of(c, "history:twin-a")
        self.assertTrue(any(g.exact for g in groups) and any(not g.exact for g in groups))

    def test_group_membership_never_merges_records(self):
        c = fixture_catalog()
        before = len(c)
        exact_groups(c)
        self.assertEqual(len(c), before)
        self.assertEqual(
            len({c.get(k).ref for g in exact_groups(c) for k in g.members}),
            sum(len(g.members) for g in exact_groups(c)),
        )


class EligibilityTests(unittest.TestCase):
    def setUp(self):
        self.s = session()

    def ok(self, action, *keys):
        return self.s.evaluate(action, keys)

    def test_matrix_by_type_and_destination(self):
        self.assertTrue(self.ok(ActionId.EDIT, "history:ridge-17").placeable)
        self.assertFalse(self.ok(ActionId.EDIT, "video:hist-run-1-clip-1").placeable)
        self.assertFalse(self.ok(ActionId.EDIT, "import:clip").placeable)
        self.assertTrue(self.ok(ActionId.ANIMATE, "create:ridge-study").placeable)
        self.assertTrue(self.ok(ActionId.ANIMATE, "motion:orbit-slow").placeable)
        self.assertFalse(self.ok(ActionId.ANIMATE, "video:hist-run-1-clip-1").placeable)
        self.assertFalse(self.ok(ActionId.STORYBOARD, "motion:orbit-slow").placeable)
        self.assertTrue(self.ok(ActionId.MOVIE, "video:hist-run-1-clip-1").placeable)
        self.assertFalse(self.ok(ActionId.MOVIE, "video:hist-board-1").placeable)
        self.assertFalse(self.ok(ActionId.MOVIE, "video:hist-clip-retired").placeable)
        self.assertTrue(self.ok(ActionId.COMPARE, "history:ridge-17").placeable)
        self.assertTrue(self.ok(ActionId.COMPARE, "edit:fixture-candidate-1").placeable)
        self.assertFalse(self.ok(ActionId.COMPARE, "create:ridge-study").placeable)
        self.assertFalse(self.ok(ActionId.COMPARE, "video:hist-run-1-clip-1").placeable)
        self.assertTrue(self.ok(ActionId.REGENERATE, "history:ridge-17").placeable)
        self.assertFalse(self.ok(ActionId.REGENERATE, "create:ridge-study").placeable)
        self.assertTrue(self.ok(ActionId.LEARNING, "learning:obs-0101").placeable)
        self.assertFalse(self.ok(ActionId.LEARNING, "create:ridge-study").placeable)  # no lineage
        self.assertTrue(self.ok(ActionId.INSPECT, "history:hidden").placeable)

    def test_organizing_works_for_unavailable_assets(self):
        for key in ("history:missing", "history:hidden", "import:clip"):
            self.assertTrue(self.ok(ActionId.FAVORITE, key).placeable)
            self.assertTrue(self.ok(ActionId.ADD_COLLECTION, key).placeable)

    def test_invalid_source_and_unsupported_type(self):
        with self.assertRaises(LibraryRefused):
            self.ok(ActionId.EDIT, "bogus:1")
        self.assertIn("Unsupported", self.ok(ActionId.EDIT, "import:clip").reason)

    def test_missing_and_hidden_reasons(self):
        self.assertIn("Missing file", self.ok(ActionId.EDIT, "history:missing").reason)
        self.assertIn("Hidden by fixture policy", self.ok(ActionId.EDIT, "history:hidden").reason)

    def test_video_clip_parity_with_motion_session(self):
        motion = MotionSession()
        for record in self.s.catalog:
            if (
                record.key.startswith("video:hist-")
                and record.native_key
                and record.native_key in motion.clips
            ):
                ok, _ = MotionSession.clip_eligibility(motion.clip(record.native_key))
                self.assertEqual(self.ok(ActionId.MOVIE, record.key).placeable, ok, record.key)

    def test_edit_lineage_matches_the_edit_fixture(self):
        from stablenew_qt_proto.edit_domain import SOURCES

        for source in SOURCES:
            record = self.s.catalog.get(source.key)
            self.assertEqual(
                record.parent.key if record.parent else None, source.parent, source.key
            )
            self.assertEqual(record.availability, source.availability, source.key)

    def test_multi_selection_preflight_lists_eligible_and_blocked(self):
        e = self.ok(
            ActionId.MOVIE, "video:hist-run-1-clip-1", "history:ridge-17", "video:hist-clip-lost"
        )
        self.assertEqual(e.eligible, ("video:hist-run-1-clip-1",))
        self.assertEqual({v.key for v in e.blocked}, {"history:ridge-17", "video:hist-clip-lost"})
        self.assertTrue(e.needs_narrowing and not e.placeable)
        single = self.ok(ActionId.EDIT, "history:ridge-17", "photo:evening")
        self.assertIn("one asset", single.set_reason)
        self.assertTrue(single.needs_narrowing)
        self.assertIn(
            "different placements",
            self.ok(ActionId.ANIMATE, "motion:orbit-slow", "create:ridge-study").set_reason,
        )
        self.assertFalse(self.ok(ActionId.EDIT).placeable)  # empty selection


class HandoffTests(unittest.TestCase):
    def setUp(self):
        self.s = session()
        self.edit, self.motion, self.create = (
            self.s.destinations.edit,
            self.s.destinations.motion,
            self.s.destinations.create,
        )

    def test_edit_handoff_fields_and_return_state(self):
        self.s.set_scope(Scope.HISTORY)
        self.s.set_query(text="ridge", page_size=7)
        self.s.select_only("history:ridge-17")
        p = self.s.propose(ActionId.EDIT)
        self.assertEqual(dict(p.copied)["Source identity"], "history:ridge-17")
        self.assertTrue(p.reset and p.preserved and not p.needs_replace)
        result = self.s.commit(p)
        self.assertEqual(result.outcome, Outcome.PLACED)
        self.assertEqual(self.edit.draft.source_key, "history:ridge-17")
        self.assertIsNone(self.edit.preview)
        self.s.set_scope(Scope.LEARNING)  # the operator wandered off
        self.s.restore_context()
        self.assertEqual(
            (self.s.query.scope, self.s.query.text, self.s.query.page_size, self.s.selection),
            (Scope.HISTORY, "ridge", 7, ("history:ridge-17",)),
        )

    def test_preview_approval_is_discarded_on_new_source(self):
        self.edit.select("history:ridge-16")
        self.edit.update(mode=Mode.QUICK)
        self.edit.update_region(prompt="warmer")
        self.edit.build_preview()
        self.s.select_only("history:ridge-17")
        p = self.s.propose(ActionId.EDIT)
        self.assertTrue(p.needs_replace)
        self.assertTrue(any("Preview" in d for d in p.discarded))

    def test_cancel_produces_zero_destination_and_library_mutation(self):
        self.edit.select("history:ridge-16")
        self.edit.update(mode=Mode.MASKED)
        self.s.set_query(text="ridge")
        self.s.select_only("history:ridge-17")
        p = self.s.propose(ActionId.EDIT)
        snap = (
            self.edit.draft,
            self.edit.revision,
            self.s.query,
            self.s.selection,
            self.s.org,
            self.s.pending_return,
        )
        for choice in (None, Replacement.CANCEL, Replacement.KEEP):
            r = self.s.commit(p, choice)
            self.assertEqual(r.outcome, Outcome.CANCELLED)
        self.assertEqual(
            snap,
            (
                self.edit.draft,
                self.edit.revision,
                self.s.query,
                self.s.selection,
                self.s.org,
                self.s.pending_return,
            ),
        )
        self.assertEqual(self.s.commit(p, Replacement.REPLACE).outcome, Outcome.PLACED)
        self.assertEqual(self.edit.draft.source_key, "history:ridge-17")

    def test_destination_revision_mismatch_is_stale_and_mutates_nothing(self):
        self.edit.select("history:ridge-16")
        self.s.select_only("history:ridge-17")
        p = self.s.propose(ActionId.EDIT)
        self.edit.update(mode=Mode.EXTEND)  # destination moved on after the review
        before = (self.edit.draft, self.edit.revision)
        self.assertEqual(self.s.commit(p, Replacement.REPLACE).outcome, Outcome.STALE)
        self.assertEqual((self.edit.draft, self.edit.revision), before)

    def test_selection_change_after_review_is_stale(self):
        self.s.select_only("history:ridge-17")
        p = self.s.propose(ActionId.EDIT)
        self.s.select_only("photo:evening")
        self.assertEqual(self.s.commit(p).outcome, Outcome.STALE)
        self.assertIsNone(self.edit.draft)

    def test_missing_file_refusal_and_vanish_between_review_and_commit(self):
        self.s.select_only("history:missing")
        self.assertFalse(self.s.propose(ActionId.EDIT).can_place)
        self.assertEqual(self.s.commit(self.s.propose(ActionId.EDIT)).outcome, Outcome.REFUSED)
        self.s.select_only("history:ridge-16")
        p = self.s.propose(ActionId.EDIT)
        self.s.simulate_vanish("history:ridge-16")
        self.assertEqual(self.s.commit(p).outcome, Outcome.REFUSED)
        self.assertIsNone(self.edit.draft)

    def test_motion_handoff_does_not_inherit_approval(self):
        self.s.select_only("create:ridge-study")
        p = self.s.propose(ActionId.ANIMATE)
        self.assertTrue(any("never inherited" in n for n in p.notes))
        self.assertEqual(self.s.commit(p).outcome, Outcome.PLACED)
        self.assertEqual(self.motion.origin["quick"], "library")
        self.assertIsNone(self.motion.previews["quick"])
        self.motion.update_quick(prompt="push in")
        self.motion.review("quick")
        self.s.select_only("history:ridge-17")
        p2 = self.s.propose(ActionId.ANIMATE)
        self.assertTrue(p2.needs_replace)
        self.assertEqual(self.s.commit(p2, Replacement.CANCEL).outcome, Outcome.CANCELLED)
        self.assertEqual(self.motion.quick.draft.source_key, "create:ridge-study")

    def test_motion_reference_needs_a_source_first(self):
        self.s.select_only("motion:orbit-slow")
        self.assertFalse(self.s.propose(ActionId.ANIMATE).can_place)
        self.motion.select_source("create:ridge-study")
        p = self.s.propose(ActionId.ANIMATE)
        self.assertTrue(p.can_place and any("motion reference" in n for n in p.notes))
        self.assertTrue(self.s.commit(p).ok)
        self.assertEqual(self.motion.quick.draft.reference_key, "motion:orbit-slow")

    def test_movie_clips_keep_selected_order_and_refuse_whole_set_atomically(self):
        order = ("video:hist-run-1-clip-3", "video:hist-run-1-clip-1", "video:hist-run-1-clip-2")
        self.s.selection = order
        self.assertTrue(self.s.commit(self.s.propose(ActionId.MOVIE)).ok)
        self.assertEqual(
            [i.clip_id for i in self.motion.assembly.draft.items],
            ["hist-run-1-clip-3", "hist-run-1-clip-1", "hist-run-1-clip-2"],
        )
        self.assertIsNone(self.motion.assembly_preview)
        self.assertFalse(self.motion.movies)
        before = self.motion.assembly.revision
        self.s.selection = ("video:hist-run-1-clip-1",)  # already in the assembly
        self.assertFalse(self.s.propose(ActionId.MOVIE).can_place)
        self.s.selection = ("video:hist-clip-retired", "video:hist-clip-lost")
        self.assertEqual(self.s.commit(self.s.propose(ActionId.MOVIE)).outcome, Outcome.REFUSED)
        self.assertEqual(self.motion.assembly.revision, before)

    def test_movie_clips_into_a_fresh_session_creates_no_draft_on_refusal(self):
        self.s.selection = ("video:hist-clip-lost",)
        self.assertEqual(self.s.commit(self.s.propose(ActionId.MOVIE)).outcome, Outcome.REFUSED)
        self.assertIsNone(self.motion.assembly.draft)

    def test_storyboard_source_handoff(self):
        self.s.select_only("create:ridge-study")
        self.assertTrue(self.s.commit(self.s.propose(ActionId.STORYBOARD)).ok)
        self.assertEqual(self.motion.story.draft.source_key, "create:ridge-study")
        self.s.select_only("history:ridge-17")
        self.assertTrue(self.s.commit(self.s.propose(ActionId.STORYBOARD)).ok)
        self.assertEqual(self.motion.story.draft.source_key, "history:ridge-17")

    def test_create_handoff_requires_known_recipe_and_replace_consent(self):
        self.s.select_only("create:ridge-study")
        self.assertFalse(self.s.propose(ActionId.REGENERATE).can_place)
        self.create.set_text("prompt", "my own unsent words")
        self.s.select_only("history:ridge-17")
        p = self.s.propose(ActionId.REGENERATE)
        self.assertTrue(p.needs_replace)
        self.assertEqual(self.s.commit(p).outcome, Outcome.CANCELLED)
        self.assertEqual(self.create.draft.prompt, "my own unsent words")
        self.assertTrue(self.s.commit(p, Replacement.REPLACE).ok)
        self.assertEqual(self.create.draft.source_key, "pack-landscapes")
        self.assertIsNone(self.create.demo_receipt)

    def test_learning_proposal_is_not_a_study_and_touches_no_destination(self):
        revisions = (self.edit.revision, self.motion.quick.revision, self.create.revision)
        self.s.select_only("learning:obs-0102")
        self.assertTrue(self.s.commit(self.s.propose(ActionId.LEARNING)).ok)
        proposal = self.s.learning_proposals[-1]
        self.assertFalse(proposal.executable or proposal.is_study)
        self.assertEqual(proposal.sources[0].observation_id, "mock-obs-0102")
        self.assertTrue(any("not independent samples" in x for x in proposal.limitations))
        self.assertEqual(
            revisions, (self.edit.revision, self.motion.quick.revision, self.create.revision)
        )
        self.assertFalse(hasattr(proposal, "submit") or hasattr(proposal, "run"))

    def test_identical_hash_records_stay_separate_sources_in_a_proposal(self):
        self.s.selection = ("learning:obs-0103", "learning:obs-0104")
        proposal = self.s.build_learning_proposal(self.s.selection)
        self.assertEqual([x.key for x in proposal.sources], list(self.s.selection))
        self.assertEqual(len({x.observation_id for x in proposal.sources}), 2)
        self.assertTrue(any("Equal bytes are not independent" in x for x in proposal.limitations))

    def test_missing_destination_workspace_blocks_placement(self):
        lonely = LibrarySession(fixture_catalog(0))
        lonely.select_only("history:ridge-17")
        p = lonely.propose(ActionId.EDIT)
        self.assertFalse(p.can_place)
        self.assertIn("not open", p.eligibility.reason)

    def test_return_context_discloses_changed_availability(self):
        self.s.select_only("history:ridge-16")
        self.assertTrue(self.s.commit(self.s.propose(ActionId.EDIT)).ok)
        self.s.simulate_vanish("history:ridge-16")
        notes = self.s.restore_context()
        self.assertEqual(self.s.selection, ("history:ridge-16",))
        self.assertTrue(notes and "Missing" in notes[0])
        with self.assertRaises(LibraryRefused):
            self.s.restore_context()

    def test_compare_supports_only_direct_parent_images(self):
        parent, child = self.s.compare_pair("edit:fixture-candidate-1")
        self.assertEqual((parent.key, child.key), ("history:ridge-17", "edit:fixture-candidate-1"))
        with self.assertRaises(LibraryRefused):
            self.s.compare_pair("video:hist-run-1-clip-1")
        self.s.simulate_vanish("history:ridge-17")
        with self.assertRaises(LibraryRefused):
            self.s.compare_pair("edit:fixture-candidate-1")


class ViewStateAndScaleTests(unittest.TestCase):
    def test_view_states_are_distinct(self):
        s = session()
        s.set_view_state(ViewState.LOADING)
        self.assertEqual(s.view_state, ViewState.LOADING)
        s.set_view_state(ViewState.ERROR, "simulated read failure")
        self.assertEqual(s.view_error, "simulated read failure")
        s.set_view_state(ViewState.READY)
        self.assertEqual(s.view_error, "")

    def test_large_catalog_pages_are_bounded(self):
        s = session(5000)
        r = s.result()
        self.assertLessEqual(len(r.items), s.query.page_size)
        self.assertGreater(r.page_count, 100)


class WalkthroughTests(unittest.TestCase):
    def test_all_eight_walkthroughs_reach_a_terminal_state(self):
        results = run_all()
        self.assertEqual([r.key for r in results], [f"LIB-0{i}" for i in range(1, 9)])
        self.assertTrue(all(r.terminal and r.steps for r in results))
        self.assertEqual(
            {r.outcome for r in results} - {"success", "refusal", "recoverable"}, set()
        )


class IsolationTests(unittest.TestCase):
    def test_library_modules_import_only_prototype_and_stdlib(self):
        forbidden = {
            "src",
            "controller",
            "pipeline",
            "queue",
            "history",
            "tkinter",
            "sqlite3",
            "subprocess",
            "socket",
            "requests",
            "ctypes",
            "shutil",
            "os",
            "pathlib",
            "glob",
            "webbrowser",
        }
        for name in ("library_domain.py", "library_session.py", "library_walkthroughs.py"):
            tree = ast.parse((ROOT / name).read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                names = (
                    [a.name for a in node.names]
                    if isinstance(node, ast.Import)
                    else [node.module or ""]
                    if isinstance(node, ast.ImportFrom) and node.level == 0
                    else []
                )
                for n in names:
                    self.assertNotIn(n.split(".")[0], forbidden, f"{name}: {n}")

    def test_no_file_operations_in_library_domain(self):
        for name in ("library_domain.py", "library_session.py"):
            code = (ROOT / name).read_text(encoding="utf-8")
            for token in (
                "open(",
                "unlink",
                "rmtree",
                "rename(",
                "os.remove",
                "write_text",
                "write_bytes",
            ):
                self.assertNotIn(token, code, f"{name}: {token}")


if __name__ == "__main__":
    unittest.main()
