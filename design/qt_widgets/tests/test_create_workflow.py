"""Pure tests for the mock Create workflow added in QT-DS-01 (sources, origins, stale reasons, results)."""

from __future__ import annotations

import unittest

from stablenew_qt_proto.domain import (
    ADVANCED_SETTINGS,
    BASIC_SETTINGS,
    PACKS,
    PROFILE_LEARNING,
    SETTING_FIELDS,
    SOURCE_FREE,
    CreateSession,
    changed_fields,
)


class PromptSourceTests(unittest.TestCase):
    def setUp(self):
        self.session = CreateSession()

    def test_basic_and_advanced_partition_every_setting_once(self):
        self.assertEqual(sorted((*BASIC_SETTINGS, *ADVANCED_SETTINGS)), sorted(SETTING_FIELDS))
        self.assertEqual(set(BASIC_SETTINGS) & set(ADVANCED_SETTINGS), set())

    def test_selecting_a_pack_loads_prompt_negative_and_slots_in_one_undo_step(self):
        before = self.session.draft.clone()
        revision = self.session.revision
        pack = PACKS[1]
        self.session.select_source(pack.key)
        d = self.session.draft
        self.assertEqual(
            (d.prompt, d.negative, d.slots, d.pack_name),
            (pack.prompt, pack.negative, dict(pack.slots), pack.pack_name),
        )
        self.assertEqual(self.session.revision, revision + 1)
        self.assertFalse(self.session.pack_modified)
        self.assertIn("unmodified", self.session.source_label)
        self.assertTrue(self.session.undo())
        self.assertEqual(
            (self.session.draft.prompt, self.session.draft.slots, self.session.draft.source_key),
            (before.prompt, before.slots, SOURCE_FREE),
        )

    def test_editing_after_loading_a_pack_is_reported_as_modified_and_unsaved(self):
        self.session.select_source(PACKS[0].key)
        self.session.set_slot("subject", "pilot")
        self.assertTrue(self.session.pack_modified)
        self.assertIn("modified, unsaved", self.session.source_label)
        self.session.build_preview()
        self.assertTrue(
            any("differ from the fixture pack" in w for w in self.session.preview.warnings)
        )
        self.assertIn("Source:", self.session.preview.text)

    def test_free_prompt_keeps_working_text_and_unknown_sources_are_refused(self):
        self.session.select_source(PACKS[1].key)
        text = self.session.draft.prompt
        self.session.select_source(SOURCE_FREE)
        self.assertEqual(self.session.draft.prompt, text)
        self.assertFalse(self.session.pack_modified)
        with self.assertRaises(ValueError):
            self.session.select_source("not-a-pack")
        revision = self.session.revision
        self.session.select_source(SOURCE_FREE)  # no-op
        self.assertEqual(self.session.revision, revision)

    def test_pack_load_invalidates_a_current_preview(self):
        self.session.build_preview()
        self.assertTrue(self.session.is_preview_current)
        self.session.select_source(PACKS[0].key)
        self.assertFalse(self.session.is_preview_current)
        self.assertFalse(self.session.can_simulate_admission)

    def test_slot_substitution_in_a_pack_prompt(self):
        from stablenew_qt_proto.domain import expand_prompt

        self.session.select_source(PACKS[1].key)
        resolved, unresolved = expand_prompt(self.session.draft.prompt, self.session.draft.slots)
        self.assertEqual(resolved, "A wide landscape of mountains at dawn, calm atmosphere")
        self.assertEqual(unresolved, ())
        self.session.remove_slot("mood")
        self.assertEqual(
            expand_prompt(self.session.draft.prompt, self.session.draft.slots)[1], ("mood",)
        )


class OverridePrecedenceTests(unittest.TestCase):
    def setUp(self):
        self.session = CreateSession()

    def test_origin_labels(self):
        self.assertEqual({self.session.setting_origin(n) for n in SETTING_FIELDS}, {"recommended"})
        self.session.set_setting("steps", 40)
        self.session.toggle_lock("cfg", True)
        self.assertEqual(self.session.setting_origin("steps"), "manual")
        self.assertEqual(self.session.setting_origin("cfg"), "locked")
        self.session.reset_setting("steps")
        self.assertEqual(self.session.setting_origin("steps"), "recommended")

    def test_lock_beats_manual_beats_recommendation_across_model_and_profile_changes(self):
        self.session.set_setting("steps", 40)  # manual
        self.session.set_setting("cfg", 9.0)
        self.session.toggle_lock("cfg", True)  # locked (also manual)
        self.session.switch_model("fixture-flux")
        self.assertEqual(
            (self.session.draft.settings.steps, self.session.draft.settings.cfg), (40, 9.0)
        )
        self.assertEqual(
            self.session.draft.settings.sampler, "Euler"
        )  # untouched fields follow the new model
        self.session.set_profile_source(PROFILE_LEARNING)
        self.assertEqual(
            self.session.draft.settings.steps, 40
        )  # manual survives the profile change
        self.session.reset_unlocked_settings()
        self.assertEqual(self.session.draft.settings.steps, self.session.recommended.steps)
        self.assertEqual(self.session.draft.settings.cfg, 9.0)  # lock survives reset-unlocked
        self.session.reset_setting("cfg")  # an explicit single reset overrides a lock
        self.assertEqual(self.session.draft.settings.cfg, self.session.recommended.cfg)

    def test_unlocked_unchanged_values_follow_the_recommendation(self):
        self.session.switch_model("fixture-flux")
        self.assertEqual(self.session.draft.settings, self.session.recommended)
        self.assertEqual(self.session.draft.manual_fields, set())

    def test_changes_are_logged_with_explanations(self):
        self.session.set_setting("steps", 40)
        self.session.switch_model("fixture-flux")
        notes = " ".join(note for _rev, note in self.session.change_log)
        self.assertIn("Preserved manually overridden steps", notes)
        self.assertIn("fixture proposes 8", notes)


class PreviewFreshnessAndRefusalTests(unittest.TestCase):
    def setUp(self):
        self.session = CreateSession()

    def test_stale_reasons_name_exactly_the_changed_fields(self):
        self.assertEqual(self.session.stale_reasons(), ())
        self.session.build_preview()
        self.assertEqual(self.session.stale_reasons(), ())
        self.session.set_setting("steps", 33)
        self.session.set_text("prompt", "new text")
        self.assertEqual(self.session.stale_reasons(), ("prompt", "settings.steps"))
        self.session.undo()
        self.session.undo()
        self.assertEqual(self.session.stale_reasons(), ())
        self.assertTrue(self.session.is_preview_current)

    def test_changed_fields_helper(self):
        self.assertEqual(
            changed_fields({"a": {"b": 1, "c": 2}}, {"a": {"b": 1, "c": 3}, "d": 4}), ("a.c", "d")
        )

    def test_admission_is_refused_without_preview_when_stale_and_when_invalid(self):
        with self.assertRaisesRegex(RuntimeError, "missing, stale, or contains an invalid"):
            self.session.simulate_admission()
        self.session.build_preview()
        self.session.set_setting("steps", 33)
        with self.assertRaises(RuntimeError):
            self.session.simulate_admission()
        self.session.set_text("prompt", "")  # invalid: empty prompt
        self.session.build_preview()
        self.assertFalse(self.session.preview.ready)
        self.assertIn("Prompt is empty", self.session.preview.errors[0])
        with self.assertRaises(RuntimeError):
            self.session.simulate_admission()
        self.assertIsNone(self.session.demo_receipt)

    def test_negative_prompt_on_a_model_without_support_blocks_preview_with_a_reason(self):
        self.session.switch_model("fixture-flux")
        self.session.build_preview()
        self.assertFalse(self.session.can_simulate_admission)
        self.assertTrue(any("negative prompt" in e for e in self.session.preview.errors))

    def test_same_preview_can_only_produce_one_receipt(self):
        session = self.session
        session.build_preview()
        receipt = session.simulate_admission()
        self.assertFalse(session.can_simulate_admission)
        self.assertIs(session.simulate_admission(), receipt)
        session.build_preview()
        self.assertFalse(session.can_simulate_admission)
        self.assertIs(session.simulate_admission(), receipt)
        session.set_setting("batch", 2)
        with self.assertRaises(RuntimeError):
            session.simulate_admission()
        session.build_preview()
        self.assertIsNot(session.simulate_admission(), receipt)

    def test_incompatible_locked_values_require_explicit_correction(self):
        session = self.session
        session.toggle_lock("sampler", True)
        session.toggle_lock("scheduler", True)
        session.switch_model("fixture-flux")
        session.set_text("negative", "")
        blocked = session.build_preview()
        self.assertEqual(len(blocked.errors), 2)
        self.assertTrue(all("locked in this draft" in error for error in blocked.errors))
        self.assertEqual(session.draft.settings.sampler, "DPM++ 2M")
        self.assertEqual(session.draft.settings.scheduler, "Karras")
        with self.assertRaises(RuntimeError):
            session.simulate_admission()
        session.reset_setting("sampler")
        session.reset_setting("scheduler")
        self.assertEqual(session.draft.locked_fields, {"sampler", "scheduler"})
        self.assertTrue(session.build_preview().ready)

    def test_editing_after_admission_clears_the_receipt(self):
        self.session.build_preview()
        self.session.simulate_admission()
        self.assertIsNotNone(self.session.demo_receipt)
        self.session.set_setting("steps", 33)
        self.assertIsNone(self.session.demo_receipt)


class SimulatedResultTests(unittest.TestCase):
    def test_receipt_tiles_match_batch_and_seed_and_carry_no_job_identity(self):
        session = CreateSession()
        session.set_setting("batch", 3)
        session.set_setting("seed", 100)
        session.build_preview()
        receipt = session.simulate_admission()
        self.assertEqual([t.seed for t in receipt.tiles], ["100", "101", "102"])
        self.assertTrue(
            all(t.label.startswith("MOCK IMAGE") and "OF 3" in t.label for t in receipt.tiles)
        )
        self.assertEqual({t.size for t in receipt.tiles}, {"1024 × 1024"})
        text = repr(receipt).lower()
        for word in ("job_id", "queue", "njr", "artifact", "path"):
            self.assertNotIn(word, text)

    def test_random_seed_is_labelled_not_invented(self):
        session = CreateSession()
        session.build_preview()
        (tile,) = session.simulate_admission().tiles
        self.assertEqual(tile.seed, "random at run time")

    def test_session_exposes_no_submission_surface(self):
        public = {name for name in dir(CreateSession) if not name.startswith("_")}
        for forbidden in (
            "submit",
            "enqueue",
            "run",
            "queue",
            "dispatch",
            "save",
            "persist",
            "write",
        ):
            self.assertFalse(
                [n for n in public if forbidden in n.lower() and n != "simulate_admission"],
                forbidden,
            )


if __name__ == "__main__":
    unittest.main()
