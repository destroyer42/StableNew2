"""Deterministic tests requiring no Qt, backend, network, or production checkout."""

from __future__ import annotations

import unittest
from dataclasses import replace

from stablenew_qt_proto.domain import MODEL_BY_KEY, CreateDraft, CreateSession


class CreateSessionTests(unittest.TestCase):
    def setUp(self):
        self.session = CreateSession()

    def test_default_is_fixture_not_real_model(self):
        self.assertTrue(MODEL_BY_KEY[self.session.draft.model_key].label.endswith("fixture)"))

    def test_initial_no_preview(self):
        self.assertIsNone(self.session.preview)
        self.assertFalse(self.session.can_simulate_admission)

    def test_preview_is_display_only_and_current(self):
        p = self.session.build_preview()
        self.assertIn("NOT AN NJR", p.text)
        self.assertTrue(p.ready)
        self.assertTrue(self.session.is_preview_current)

    def test_simulation_requires_preview(self):
        with self.assertRaises(RuntimeError):
            self.session.simulate_admission()

    def test_ready_preview_can_simulate_in_memory_receipt(self):
        self.session.build_preview()
        receipt = self.session.simulate_admission()
        self.assertIn("No job submitted", receipt.message)
        self.assertNotIn("job_id", receipt.__dict__)

    def test_draft_edit_invalidates_preview(self):
        self.session.build_preview()
        self.session.set_text("prompt", "New prompt")
        self.assertFalse(self.session.is_preview_current)
        self.assertFalse(self.session.can_simulate_admission)

    def test_old_preview_preserved_but_stale(self):
        previous = self.session.build_preview()
        self.session.set_text("pack_name", "Changed")
        self.assertIs(self.session.preview, previous)
        self.assertFalse(self.session.is_preview_current)

    def test_unmodified_field_has_stable_revision(self):
        rev = self.session.revision
        self.session.set_text("prompt", self.session.draft.prompt)
        self.assertEqual(rev, self.session.revision)

    def test_empty_prompt_is_not_ready(self):
        self.session.set_text("prompt", "   ")
        p = self.session.build_preview()
        self.assertFalse(p.ready)
        self.assertIn("Prompt is empty", p.errors[0])

    def test_invalid_mock_negative_blocks(self):
        self.session.switch_model("fixture-flux")
        p = self.session.build_preview()
        self.assertFalse(p.ready)
        self.assertTrue(any("negative prompt" in x.lower() for x in p.errors))

    def test_negative_is_not_silently_dropped(self):
        negative = self.session.draft.negative
        self.session.switch_model("fixture-flux")
        self.assertEqual(self.session.draft.negative, negative)

    def test_clearing_negative_allows_mock_preview(self):
        self.session.switch_model("fixture-flux")
        self.session.set_text("negative", "")
        self.assertTrue(self.session.build_preview().ready)

    def test_unlocked_values_follow_new_model_fixture(self):
        self.session.switch_model("fixture-flux")
        self.assertEqual(self.session.draft.settings.steps, 8)
        self.assertEqual(self.session.draft.settings.cfg, 1.0)

    def test_locked_value_preserved_across_model_change(self):
        self.session.toggle_lock("steps", True)
        self.session.switch_model("fixture-flux")
        self.assertEqual(self.session.draft.settings.steps, 28)
        self.assertIn("steps", self.session.draft.locked_fields)

    def test_locked_value_explained_in_review_notes(self):
        self.session.toggle_lock("cfg", True)
        self.session.switch_model("fixture-flux")
        self.assertTrue(any("Preserved locked cfg" in n for n in self.session.change_notes))

    def test_manual_override_preserved_across_model_change(self):
        self.session.set_setting("steps", 44)
        self.session.switch_model("fixture-flux")
        self.assertEqual(self.session.draft.settings.steps, 44)
        self.assertIn("steps", self.session.draft.manual_fields)

    def test_unlocked_unmodified_sampler_updates(self):
        self.session.switch_model("fixture-flux")
        self.assertEqual(self.session.draft.settings.sampler, "Euler")

    def test_unsupported_size_warns_not_blocks(self):
        self.session.set_setting("width", 896)
        preview = self.session.build_preview()
        self.assertTrue(preview.ready)
        self.assertTrue(any("unverified" in w for w in preview.warnings))

    def test_learning_source_is_labeled_unqualified(self):
        self.session.set_profile_source("Learning-informed (fixture)")
        self.assertTrue(
            any("not evidence" in w.lower() for w in self.session.build_preview().warnings)
        )

    def test_text_field_rejects_unknown_name(self):
        with self.assertRaises(ValueError):
            self.session.set_text("backend_url", "abc")

    def test_unknown_model_rejected_without_mutation(self):
        before = self.session.draft.fingerprint()
        with self.assertRaises(ValueError):
            self.session.switch_model("nonexistent")
        self.assertEqual(before, self.session.draft.fingerprint())

    def test_add_slot_updates_digest(self):
        before = self.session.draft.fingerprint()
        self.session.set_slot("environment", "mountains")
        self.assertNotEqual(before, self.session.draft.fingerprint())

    def test_remove_slot(self):
        self.session.remove_slot("subject")
        self.assertNotIn("subject", self.session.draft.slots)

    def test_replace_slots(self):
        self.session.replace_slots({"one": "1", "two": "2"})
        self.assertEqual(self.session.draft.slots, {"one": "1", "two": "2"})

    def test_adetailer_toggle_is_snapshot_freshness(self):
        self.session.build_preview()
        self.session.set_adetailer_enabled(True)
        self.assertFalse(self.session.is_preview_current)

    def test_receipt_invalidated_after_change(self):
        self.session.build_preview()
        self.session.simulate_admission()
        self.session.set_text("prompt", "Changed")
        self.assertIsNone(self.session.demo_receipt)

    def test_reset_is_in_memory_only(self):
        self.session.set_text("prompt", "Changed")
        self.session.reset()
        self.assertEqual(self.session.draft.prompt, CreateDraft().prompt)
        self.assertIsNone(self.session.preview)

    def test_fingerprint_order_independent_for_slots(self):
        a = CreateDraft(slots={"b": "2", "a": "1"})
        b = CreateDraft(slots={"a": "1", "b": "2"})
        self.assertEqual(a.fingerprint(), b.fingerprint())

    def test_invalid_steps_refused(self):
        self.session.draft.settings = replace(self.session.draft.settings, steps=0)
        self.assertFalse(self.session.build_preview().ready)

    def test_invalid_dimensions_refused(self):
        self.session.draft.settings = replace(self.session.draft.settings, width=200)
        self.assertFalse(self.session.build_preview().ready)

    def test_lock_toggle_changes_snapshot_identity(self):
        before = self.session.draft.fingerprint()
        self.session.toggle_lock("height", True)
        self.assertNotEqual(before, self.session.draft.fingerprint())

    def test_switch_to_same_model_is_noop(self):
        before = self.session.revision
        self.session.switch_model("fixture-sdxl")
        self.assertEqual(before, self.session.revision)

    def test_mock_receipt_is_not_actual_queue_or_history(self):
        self.session.build_preview()
        r = self.session.simulate_admission()
        # QT-DS-01 added placeholder ``tiles`` for the mock result gallery; no job/queue identity may appear.
        self.assertEqual(
            sorted(r.__dict__), ["message", "preview_fingerprint", "revision", "tiles"]
        )
        for tile in r.tiles:
            self.assertEqual(sorted(tile.__dict__), ["index", "label", "seed", "size"])
            self.assertTrue(tile.label.startswith("MOCK IMAGE"))


if __name__ == "__main__":
    unittest.main()
