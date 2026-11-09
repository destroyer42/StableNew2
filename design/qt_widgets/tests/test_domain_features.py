"""Deterministic tests for recommendations, undo/redo, change log and placeholders."""

from __future__ import annotations

from dataclasses import replace
import unittest

from stablenew_qt_proto.domain import (
    PROFILE_LEARNING, SAMPLERS, CreateDraft, CreateSession, expand_prompt,
    recommended_settings,
)


class RecommendationTests(unittest.TestCase):
    def setUp(self):
        self.s = CreateSession()

    def test_learning_profile_changes_recommendation_not_just_a_label(self):
        self.s.set_profile_source(PROFILE_LEARNING)
        self.assertEqual(self.s.draft.settings.steps, 32)
        self.assertEqual(self.s.draft.settings.cfg, 6.5)
        self.assertEqual(self.s.recommended, recommended_settings("fixture-sdxl", PROFILE_LEARNING))

    def test_profile_change_respects_locks(self):
        self.s.toggle_lock("steps", True)
        self.s.set_profile_source(PROFILE_LEARNING)
        self.assertEqual(self.s.draft.settings.steps, 28)
        self.assertTrue(self.s.differs_from_recommended("steps"))
        self.assertTrue(any("Preserved locked steps" in n for n in self.s.change_notes))

    def test_manual_edit_matching_recommendation_is_not_manual(self):
        self.s.set_setting("steps", 44)
        self.assertIn("steps", self.s.draft.manual_fields)
        self.s.set_setting("steps", 28)
        self.assertNotIn("steps", self.s.draft.manual_fields)

    def test_reset_setting_returns_to_recommended_and_releases_manual(self):
        self.s.set_setting("cfg", 12.0)
        self.s.reset_setting("cfg")
        self.assertEqual(self.s.draft.settings.cfg, 7.0)
        self.assertNotIn("cfg", self.s.draft.manual_fields)
        self.s.switch_model("fixture-flux")  # now follows the new fixture again
        self.assertEqual(self.s.draft.settings.cfg, 1.0)

    def test_reset_unlocked_keeps_locked_values(self):
        self.s.set_setting("steps", 40)
        self.s.set_setting("cfg", 9.0)
        self.s.toggle_lock("steps", True)
        self.s.reset_unlocked_settings()
        self.assertEqual(self.s.draft.settings.steps, 40)
        self.assertEqual(self.s.draft.settings.cfg, 7.0)

    def test_size_preset_is_one_revision(self):
        before = self.s.revision
        self.s.apply_size(832, 1216)
        self.assertEqual(self.s.revision, before + 1)
        self.assertEqual((self.s.draft.settings.width, self.s.draft.settings.height), (832, 1216))

    def test_seed_and_batch_are_validated(self):
        self.s.draft.settings = replace(self.s.draft.settings, batch=99)
        errors = self.s.build_preview().errors
        self.assertTrue(any("Batch count" in e for e in errors))

    def test_unknown_sampler_blocks_preview(self):
        self.s.set_setting("sampler", "Nonexistent")
        self.assertTrue(any("Sampler" in e for e in self.s.build_preview().errors))
        self.assertNotIn("Nonexistent", SAMPLERS)

    def test_empty_sampler_blocks_preview(self):
        self.s.set_setting("sampler", "")
        self.assertFalse(self.s.build_preview().ready)


class ChangeLogTests(unittest.TestCase):
    def setUp(self):
        self.s = CreateSession()

    def test_model_switch_notes_survive_later_edits(self):
        self.s.switch_model("fixture-flux")
        self.s.set_text("pack_name", "later edit")
        text = " ".join(note for _, note in self.s.change_log)
        self.assertIn("Changed model fixture", text)
        self.assertIn("Suggested steps changed", text)

    def test_log_entries_carry_revisions(self):
        self.s.toggle_lock("cfg", True)
        self.assertEqual(self.s.change_log[-1][0], self.s.revision)

    def test_log_is_bounded(self):
        for i in range(300):
            self.s.toggle_lock("cfg", i % 2 == 0)
        self.assertLessEqual(len(self.s.change_log), 200)


class UndoRedoTests(unittest.TestCase):
    def setUp(self):
        self.s = CreateSession()

    def test_nothing_to_undo_initially(self):
        self.assertFalse(self.s.can_undo)
        self.assertFalse(self.s.undo())

    def test_undo_and_redo_restore_draft(self):
        original = self.s.draft.fingerprint()
        self.s.set_setting("steps", 50)
        self.assertTrue(self.s.undo())
        self.assertEqual(self.s.draft.fingerprint(), original)
        self.assertTrue(self.s.redo())
        self.assertEqual(self.s.draft.settings.steps, 50)

    def test_typing_coalesces_into_one_undo_step(self):
        original = self.s.draft.prompt
        for text in ("a", "ab", "abc", "abcd"):
            self.s.set_text("prompt", text)
        self.assertTrue(self.s.undo())
        self.assertEqual(self.s.draft.prompt, original)
        self.assertFalse(self.s.can_undo)

    def test_different_fields_do_not_coalesce(self):
        self.s.set_text("prompt", "x")
        self.s.set_text("negative", "y")
        self.s.undo()
        self.assertEqual(self.s.draft.prompt, "x")

    def test_new_change_clears_redo(self):
        self.s.set_setting("steps", 50)
        self.s.undo()
        self.assertTrue(self.s.can_redo)
        self.s.set_setting("steps", 60)
        self.assertFalse(self.s.can_redo)

    def test_undo_restores_locks_models_and_manual_flags(self):
        self.s.toggle_lock("steps", True)
        self.s.switch_model("fixture-flux")
        self.s.undo()
        self.assertEqual(self.s.draft.model_key, "fixture-sdxl")
        self.assertIn("steps", self.s.draft.locked_fields)
        self.s.undo()
        self.assertNotIn("steps", self.s.draft.locked_fields)

    def test_undo_returning_to_previewed_state_makes_preview_current(self):
        self.s.build_preview()
        self.s.set_setting("steps", 50)
        self.assertFalse(self.s.is_preview_current)
        self.s.undo()
        self.assertTrue(self.s.is_preview_current)

    def test_undo_clears_receipt(self):
        self.s.set_setting("steps", 50)
        self.s.build_preview()
        self.s.simulate_admission()
        self.assertIsNotNone(self.s.demo_receipt)
        self.assertTrue(self.s.undo())
        self.assertIsNone(self.s.demo_receipt)

    def test_reset_is_undoable(self):
        self.s.set_text("prompt", "custom prompt")
        self.s.reset()
        self.assertNotEqual(self.s.draft.prompt, "custom prompt")
        self.assertTrue(self.s.undo())
        self.assertEqual(self.s.draft.prompt, "custom prompt")

    def test_undo_does_not_alias_live_draft(self):
        self.s.set_slot("extra", "1")
        self.s.undo()
        self.s.set_slot("other", "2")
        self.assertTrue(self.s.undo())
        self.assertNotIn("other", self.s.draft.slots)
        self.s.redo()
        self.assertIn("other", self.s.draft.slots)


class PlaceholderTests(unittest.TestCase):
    def test_expand_resolves_known_slots(self):
        text, unresolved = expand_prompt("a {x} and {y}", {"x": "cat"})
        self.assertEqual(text, "a cat and {y}")
        self.assertEqual(unresolved, ("y",))

    def test_default_prompt_is_fully_resolved(self):
        d = CreateDraft()
        text, unresolved = expand_prompt(d.prompt, d.slots)
        self.assertIn("explorer", text)
        self.assertEqual(unresolved, ())

    def test_preview_shows_resolved_prompt(self):
        s = CreateSession()
        preview = s.build_preview()
        self.assertIn("Prompt resolved: A cinematic portrait of an imaginary explorer", preview.text)

    def test_unresolved_placeholder_warns_not_blocks(self):
        s = CreateSession()
        s.remove_slot("subject")
        preview = s.build_preview()
        self.assertTrue(preview.ready)
        self.assertTrue(any("{subject}" in w for w in preview.warnings))

    def test_unused_slot_warns(self):
        s = CreateSession()
        s.set_slot("spare", "unused")
        self.assertTrue(any("spare" in w for w in s.build_preview().warnings))

    def test_invalid_slot_name_warns(self):
        s = CreateSession()
        s.replace_slots({"bad name": "x", "subject": "a", "lighting": "b"})
        self.assertTrue(any("bad name" in w for w in s.build_preview().warnings))

    def test_prompt_only_placeholders_make_empty_prompt_an_error(self):
        s = CreateSession()
        s.set_text("prompt", "{empty}")
        s.replace_slots({"empty": "   "})
        self.assertTrue(any("Prompt is empty" in e for e in s.build_preview().errors))

    def test_slot_order_does_not_change_fingerprint(self):
        a = CreateDraft(slots={"b": "2", "a": "1"})
        b = CreateDraft(slots={"a": "1", "b": "2"})
        self.assertEqual(a.fingerprint(), b.fingerprint())


if __name__ == "__main__":
    unittest.main()
