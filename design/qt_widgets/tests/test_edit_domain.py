from __future__ import annotations

import unittest
from dataclasses import replace

from stablenew_qt_proto.edit_domain import (
    CREATE_SOURCE,
    EditRefused,
    EditSession,
    Geometry,
    ImageTransform,
    Mode,
    Replacement,
    evaluate,
    paint_segment,
    require_available,
    source_for,
    suggest_mask,
)


class EditDomainTests(unittest.TestCase):
    def setUp(self):
        self.edit = EditSession()
        self.edit.select(CREATE_SOURCE)

    def ready(self):
        self.edit.update_region(prompt="Warm the ridgeline")
        preview = self.edit.build_preview()
        self.assertEqual(preview.errors, ())
        return preview

    def test_identity_and_direct_parent_are_catalog_values(self):
        self.assertEqual(source_for("history:ridge-17").parent, "history:ridge-16")
        self.assertIsNone(source_for("import:coast").parent)
        self.assertNotEqual(source_for("history:ridge-16").key, source_for(CREATE_SOURCE).key)

    def test_transform_respects_zoom_pan_resize_and_half_open_bounds(self):
        for scale, left, top in ((1, 0, 0), (2.25, -60.5, 47), (0.75, 260, 112)):
            transform = ImageTransform(left, top, scale, (640, 400))
            self.assertEqual(transform.source_pixel(left, top), (0, 0))
            self.assertEqual(
                transform.source_pixel(left + 639.9 * scale, top + 399.5 * scale), (639, 399)
            )
            self.assertIsNone(transform.source_pixel(left - 0.01, top))
            self.assertIsNone(transform.source_pixel(left + 640 * scale, top))

    def test_brush_sweep_is_continuous_and_clipped_and_erase_is_local(self):
        pixels = bytearray(120)
        paint_segment(pixels, (12, 10), (0, 0), (11, 0), 2)
        self.assertEqual(pixels[:36], bytes([255]) * 36)
        self.assertEqual(pixels[36:], bytes(84))
        paint_segment(pixels, (12, 10), (6, 0), (6, 0), 1, erase=True)
        self.assertEqual(pixels[5:8], b"\0\0\0")
        self.assertEqual(pixels[12 + 6], 0)
        self.assertEqual(pixels[12 + 5], 255)

    def test_mask_undo_redo_and_stale_callback(self):
        edit = self.edit
        edit.update(mode=Mode.MASKED)
        edit.update_region(prompt="Revise the foreground")
        first = edit.revision
        mask = suggest_mask(CREATE_SOURCE)
        self.assertTrue(edit.commit_mask(first, mask))
        preview = edit.build_preview()
        self.assertEqual(edit.status, "Current / ready")
        edit.undo()
        self.assertEqual(edit.draft.region.mask, b"")
        self.assertEqual(edit.status, "Stale")
        self.assertFalse(edit.install_preview(preview))
        self.assertFalse(edit.commit_mask(first, mask))
        edit.redo()
        self.assertEqual(edit.draft.region.mask, mask)
        self.assertEqual(edit.status, "Stale")
        self.assertGreater(edit.revision, preview.revision)

    def test_region_independence_and_scope(self):
        edit = self.edit
        self.ready()
        edit.update(active_region=1)
        self.assertEqual(edit.status, "Stale")
        self.assertEqual(edit.draft.region.prompt, "")
        edit.update_region(prompt="Cool the sky", strength=21)
        edit.update(active_region=0)
        self.assertEqual(edit.draft.region.prompt, "Warm the ridgeline")
        self.assertEqual(edit.draft.regions[1].strength, 21)

    def test_feather_geometry_and_profile_validation(self):
        edit = self.edit
        self.ready()
        edit.update(mode=Mode.MASKED)
        edit.commit_mask(edit.revision, suggest_mask(CREATE_SOURCE))
        edit.update_region(feather=33)
        self.assertIn("Feather", edit.build_preview().errors[0])
        edit.update(mode=Mode.EXTEND, geometry=Geometry(0, 0, 0, 0))
        self.assertIn("positive extension", edit.build_preview().errors[0])
        edit.update(geometry=Geometry(-1, 1, 3, 4))
        self.assertIn("whole pixels", edit.build_preview().errors[0])
        edit.update(geometry=Geometry(7, 11, 13, 17), profile="Prompt-only fixture")
        self.assertIn("profile", edit.build_preview().errors[0])
        edit.update(profile="Still image fixture")
        self.assertEqual(edit.build_preview().output_size, (660, 428))

    def test_unavailable_or_unknown_source_never_replaces_a_draft(self):
        self.ready()
        before = self.edit.draft, self.edit.revision, self.edit.preview
        for key in ("history:missing", "history:hidden", "import:clip", "history:typo"):
            with self.subTest(key=key), self.assertRaises(EditRefused):
                self.edit.select(key, Replacement.REPLACE)
            self.assertEqual((self.edit.draft, self.edit.revision, self.edit.preview), before)
        self.assertTrue(evaluate(replace(self.edit.draft, source_key="history:hidden"), 1).errors)

    def test_replacement_choices_preserve_dirty_draft_until_replace(self):
        self.ready()
        old = self.edit.draft
        for choice in (None, Replacement.CANCEL, Replacement.KEEP):
            self.assertFalse(self.edit.select("import:coast", choice))
            self.assertIs(self.edit.draft, old)
        self.assertTrue(self.edit.select("import:coast", Replacement.REPLACE))
        self.assertFalse(self.edit.dirty)
        self.assertEqual(self.edit.status, "Not built")
        self.assertFalse(self.edit.can_undo)
        self.edit.update_region(prompt="Coast", negative="Blur")
        self.assertIn("Negative prompt", self.edit.build_preview().errors[0])

    def test_admission_is_fresh_idempotent_and_keeps_immutable_branch_snapshots(self):
        edit = self.edit
        with self.assertRaises(EditRefused):
            edit.admit()
        self.ready()
        one = edit.admit()
        self.assertIs(one, edit.admit())
        edit.build_preview()
        self.assertIs(one, edit.admit())
        edit.update_region(prompt="")
        self.assertEqual(edit.status, "Stale")
        with self.assertRaises(EditRefused):
            edit.admit()
        edit.build_preview()
        with self.assertRaises(EditRefused):
            edit.admit()
        edit.update_region(prompt="Cool the ridgeline")
        edit.build_preview()
        two = edit.admit()
        self.assertEqual(len(edit.candidates), 2)
        self.assertEqual(one.parent, two.parent)
        self.assertEqual(one.preview.draft.region.prompt, "Warm the ridgeline")
        self.assertNotEqual(one.key, two.key)
        edit.set_baseline(one)
        self.assertEqual(edit.baselines, {CREATE_SOURCE: one.key})
        self.assertEqual(edit.candidates, [one, two])
        self.assertEqual(require_available(CREATE_SOURCE).size, (640, 400))
        self.assertIsNone(require_available(CREATE_SOURCE).parent)
        edit.select("photo:evening", Replacement.REPLACE)
        self.assertEqual(one.parent, CREATE_SOURCE)
        self.assertEqual(edit.candidates, [one, two])

    def test_assistance_is_deterministic_and_unavailable_for_some_fixtures(self):
        self.assertEqual(suggest_mask(CREATE_SOURCE), suggest_mask(CREATE_SOURCE))
        self.assertGreater(suggest_mask(CREATE_SOURCE).count(255), 0)
        with self.assertRaisesRegex(EditRefused, "suggestion unavailable"):
            suggest_mask("import:coast")
