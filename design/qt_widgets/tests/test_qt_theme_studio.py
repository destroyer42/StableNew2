"""Opt-in Qt tests for the Theme Studio and live theme application (STABLENEW_QT_PROTOTYPE_TEST=1).

Every test uses a temporary theme library and restores the blue-modern theme afterwards, so the
user's real ``user_themes`` directory is never read or written.
"""

from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path

try:
    from PySide6.QtCore import QEvent
    from PySide6.QtWidgets import QApplication
    from stablenew_qt_proto.app import PrototypeWindow, apply_theme
    from stablenew_qt_proto.domain import PACKS
    from stablenew_qt_proto.theme import canonical_json, failing_checks
    from stablenew_qt_proto.theme_store import ThemeLibrary
    from stablenew_qt_proto.theme_studio import ThemeStudio
    from stablenew_qt_proto.tokens import (
        COLORS,
        SPACE,
        THEME_DIR,
        reference_themes,
    )
except ImportError:
    QApplication = None

ENABLED = QApplication is not None and os.environ.get("STABLENEW_QT_PROTOTYPE_TEST") == "1"


def edge_colour(widget) -> str:
    """Colour of the middle of the widget's top edge (its border on a plain rounded rectangle)."""
    image = widget.grab().toImage()
    return image.pixelColor(image.width() // 2, 0).name().upper()


@unittest.skipUnless(ENABLED, "opt-in Qt environment required")
class StudioCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.dir = Path(self._tmp.name) / "themes"
        self.lib = ThemeLibrary(self.dir)
        self.refs = reference_themes()
        self.addCleanup(self._restore_blue)
        apply_theme(self.app, self.refs["blue-modern"])
        self.applied: list = []
        self.studio = ThemeStudio(self.lib, self.refs["blue-modern"], self.applied.append)
        self.studio.resize(1180, 760)
        self.studio.show()
        self.dispose(self.studio)
        self.pump()

    def _restore_blue(self):
        apply_theme(self.app, self.refs["blue-modern"])

    def dispose(self, widget):
        """Close and really delete a widget: every live widget makes the next stylesheet change slower."""

        def _dispose():
            widget.close()
            widget.deleteLater()
            QApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
            self.app.processEvents()

        self.addCleanup(_dispose)

    def pump(self):
        for _ in range(4):
            self.app.processEvents()

    def notice(self) -> str:
        return self.studio.notice.message.text()


class EditingTests(StudioCase):
    def test_editing_a_reference_makes_an_unsaved_user_copy_and_updates_the_preview(self):
        before = self.refs["blue-modern"]
        self.assertTrue(self.studio.edit("colors", "accent", "#FFC806"))
        self.pump()
        draft = self.studio.draft
        self.assertEqual(
            (draft.kind, draft.base_id, draft.palette.accent), ("user", "blue-modern", "#FFC806")
        )
        self.assertEqual(
            reference_themes()["blue-modern"], before
        )  # the shipped preset is immutable
        self.assertIn("UNSAVED EDITS", self.notice())
        self.assertEqual(self.lib.user_themes(), {})
        primary = self.studio.preview.matrix_widgets[("Primary", "Default")]
        self.assertEqual(edge_colour(primary), "#FFC806")

    def test_invalid_hex_is_flagged_and_keeps_the_last_valid_draft(self):
        original = self.studio.draft.palette.accent
        self.assertFalse(self.studio.edit("colors", "accent", "#12"))
        self.pump()
        self.assertEqual(self.studio.draft.palette.accent, original)
        self.assertEqual(self.studio.fields[("colors", "accent")].property("invalid"), "true")
        self.assertIn("INVALID EDIT", self.notice())
        self.assertFalse(self.studio.apply_button.isEnabled())
        self.assertFalse(self.studio.apply())
        self.assertTrue(self.studio.edit("colors", "accent", "#112233"))
        self.assertEqual(self.studio.fields[("colors", "accent")].property("invalid"), "false")

    def test_out_of_range_numbers_are_rejected(self):
        before = self.studio.draft.spacing.md
        self.assertFalse(self.studio.edit("spacing", "md", 9999))
        self.assertEqual(self.studio.draft.spacing.md, before)

    def test_forced_state_matrix_follows_state_roles(self):
        hover = self.studio.preview.matrix_widgets[("Primary", "Hover")]
        default = self.studio.preview.matrix_widgets[("Primary", "Default")]
        draft = self.studio.draft
        self.assertEqual(edge_colour(hover), draft.palette.text.upper())
        self.assertEqual(edge_colour(default), draft.palette.accent.upper())
        self.studio.edit("states", "primary_hover_border", "danger_fill")
        self.pump()
        hover = self.studio.preview.matrix_widgets[("Primary", "Hover")]
        self.assertEqual(edge_colour(hover), self.studio.draft.palette.danger_fill.upper())
        self.assertEqual(
            {t for t, _s in self.studio.preview.matrix_widgets},
            {"Button", "Primary", "Danger", "Input", "Checkbox"},
        )

    def test_density_and_spacing_reach_the_preview_but_not_the_hit_target(self):
        spacing_before = self.studio.preview._layout.spacing()
        self.studio.edit("", "density", "compact")
        self.pump()
        self.assertLess(self.studio.preview._layout.spacing(), spacing_before)
        draft = self.studio.draft
        self.assertEqual(draft.metrics().control_min_height, draft.spacing.control_min_height)
        button = self.studio.preview.matrix_widgets[("Button", "Default")]
        self.assertGreaterEqual(button.sizeHint().height(), draft.spacing.control_min_height)
        self.studio.edit("spacing", "control_min_height", 44)
        self.pump()
        button = self.studio.preview.matrix_widgets[("Button", "Default")]
        self.assertGreaterEqual(button.sizeHint().height(), 44)

    def test_typography_and_shape_reach_the_stylesheet(self):
        self.studio.edit("typography", "body_pt", 13)
        self.studio.edit("typography", "emphasis_weight", "normal")
        self.studio.edit("radius", "button", 14)
        css = self.studio.preview.styleSheet()
        self.assertIn("font-size: 13pt", css)
        self.assertIn("border-radius: 14px", css)
        self.assertIn("font-weight: normal", css)

    def test_contrast_diagnostics_list_every_check(self):
        text = self.studio.diagnostics.toPlainText()
        self.assertEqual(len(text.splitlines()), 20)
        self.assertTrue(all(line.startswith(("PASS", "FAIL")) for line in text.splitlines()))
        self.assertIn("ALL 20 PASS", self.studio.contrast_chip.text())


class GuardTests(StudioCase):
    def _break_contrast(self):
        self.studio.edit("colors", "text", self.studio.draft.palette.background)
        self.pump()
        self.assertTrue(failing_checks(self.studio.draft))

    def test_failing_contrast_blocks_apply_save_and_export(self):
        self._break_contrast()
        self.assertFalse(self.studio.apply_button.isEnabled())
        self.assertFalse(self.studio.save_button.isEnabled())
        self.assertFalse(self.studio.export_button.isEnabled())
        self.assertIn("FAIL", self.studio.contrast_chip.text())
        target = Path(self._tmp.name) / "blocked.json"
        self.assertFalse(self.studio.apply())
        self.assertIsNone(self.studio.save_as("Blocked"))
        self.assertFalse(self.studio.export_to(target))
        self.assertEqual((self.applied, self.lib.user_themes(), target.exists()), ([], {}, False))
        self.assertIn("EXPORT REFUSED", self.notice())

    def test_revert_discards_edits_and_resyncs_fields(self):
        original = self.studio.draft
        self.studio.edit("colors", "accent", "#FFC806")
        self.studio.edit("spacing", "md", 20)
        self.assertTrue(self.studio.revert_button.isEnabled())
        self.studio.revert()
        self.pump()
        self.assertEqual(self.studio.draft.palette, original.palette)
        self.assertEqual(self.studio.draft.spacing, original.spacing)
        self.assertEqual(self.studio.fields[("colors", "accent")].text(), original.palette.accent)
        self.assertEqual(self.studio.fields[("spacing", "md")].value(), original.spacing.md)
        self.assertFalse(self.studio.revert_button.isEnabled())

    def test_reset_to_preset_returns_to_the_shipped_values(self):
        self.studio.select_preset("concept-a")
        self.studio.edit("colors", "accent", "#112233")
        self.studio.reset_to_preset()
        self.assertEqual(self.studio.draft, self.refs["concept-a"])

    def test_switching_presets_with_unsaved_edits_needs_discard(self):
        self.studio.edit("colors", "accent", "#FFC806")
        self.assertFalse(self.studio.select_preset("concept-a"))
        self.assertEqual(self.studio.draft.palette.accent, "#FFC806")
        self.assertTrue(self.studio.select_preset("concept-a", discard=True))
        self.assertEqual(self.studio.draft, self.refs["concept-a"])

    def test_reference_presets_are_selectable_and_labelled_read_only(self):
        labels = [
            self.studio.preset_combo.itemText(i) for i in range(self.studio.preset_combo.count())
        ]
        self.assertEqual(sum("reference (read-only)" in label for label in labels), 2)
        self.assertIn("REFERENCE", self.notice())
        self.assertFalse(self.studio.delete_button.isEnabled())
        self.assertFalse(self.studio.delete_selected())
        self.assertTrue((THEME_DIR / "blue-modern.theme.json").exists())


class PersistenceTests(StudioCase):
    def test_save_restore_and_apply_across_library_instances(self):
        self.studio.edit("colors", "accent", "#FFC806")
        saved = self.studio.save_as("Warm Accent")
        self.assertIsNotNone(saved)
        self.assertIn("SAVED", self.notice())
        self.assertFalse(self.studio.revert_button.isEnabled())
        self.assertTrue((self.dir / "warm-accent.theme.json").exists())
        self.assertEqual(self.applied, [])  # saving never applies
        self.assertTrue(self.studio.apply())
        self.assertEqual(self.applied[-1], saved)
        fresh = ThemeLibrary(self.dir)
        self.assertEqual(fresh.get("warm-accent"), saved)
        self.assertEqual(fresh.load_active(), saved)
        reopened = ThemeStudio(fresh, fresh.load_active())
        self.dispose(reopened)
        self.assertEqual(reopened.draft, saved)
        self.assertEqual(reopened.fields[("colors", "accent")].text(), "#FFC806")

    def test_overwrite_requires_a_second_deliberate_press(self):
        self.studio.edit("colors", "accent", "#FFC806")
        self.studio.save_as("Mine")
        self.studio.edit("colors", "accent", "#FFC807")
        self.assertIsNone(self.studio.save_as("Mine"))
        self.assertIn("CONFIRM OVERWRITE", self.notice())
        self.assertEqual(ThemeLibrary(self.dir).get("mine").palette.accent, "#FFC806")
        self.assertIsNotNone(self.studio.save_as("Mine"))
        self.assertEqual(ThemeLibrary(self.dir).get("mine").palette.accent, "#FFC807")

    def test_any_edit_cancels_a_pending_overwrite(self):
        self.studio.edit("colors", "accent", "#FFC806")
        self.studio.save_as("Mine")
        self.studio.edit("colors", "accent", "#FFC807")
        self.studio.save_as("Mine")
        self.studio.edit("colors", "accent", "#FFC808")
        self.assertIsNone(self.studio.save_as("Mine"))
        self.assertEqual(ThemeLibrary(self.dir).get("mine").palette.accent, "#FFC806")

    def test_reference_names_are_refused(self):
        before = (THEME_DIR / "blue-modern.theme.json").read_bytes()
        self.studio.edit("colors", "accent", "#FFC806")
        for name in ("Blue Modern", "concept-a", "  CONCEPT A  "):
            self.assertIsNone(self.studio.save_as(name), name)
            self.assertIn("SAVE REFUSED", self.notice())
        self.assertEqual((THEME_DIR / "blue-modern.theme.json").read_bytes(), before)
        self.assertEqual(self.lib.user_themes(), {})

    def test_export_then_import_round_trip_never_auto_saves_or_applies(self):
        self.studio.edit("colors", "accent", "#FFC806")
        target = Path(self._tmp.name) / "out" / "mine.json"
        self.assertTrue(self.studio.export_to(target))
        self.assertIn("EXPORTED", self.notice())
        self.studio.revert()
        self.assertTrue(self.studio.import_from(target))
        self.assertIn("IMPORTED", self.notice())
        self.assertEqual(self.studio.draft.palette.accent, "#FFC806")
        self.assertEqual((self.lib.user_themes(), self.applied), ({}, []))

    def test_import_errors_are_surfaced_and_leave_the_draft_alone(self):
        good = json.loads(canonical_json(self.refs["blue-modern"]))
        cases = {
            "garbage.json": "{{{",
            "colour.json": json.dumps({**good, "colors": {**good["colors"], "accent": "blue"}}),
            "future.json": json.dumps({**good, "schema_version": 99}),
            "extra.json": json.dumps({**good, "evil": 1}),
        }
        before = self.studio.draft
        for name, content in cases.items():
            path = Path(self._tmp.name) / name
            path.write_text(content, encoding="utf-8")
            self.assertFalse(self.studio.import_from(path), name)
            self.assertIn("IMPORT REFUSED", self.notice(), name)
            self.assertEqual(self.studio.draft, before, name)
        self.assertFalse(self.studio.import_from(Path(self._tmp.name) / "missing.json"))

    def test_import_is_refused_over_unsaved_edits(self):
        path = Path(self._tmp.name) / "ok.json"
        self.lib.export_to(self.refs["concept-a"], path)
        self.studio.edit("colors", "accent", "#FFC806")
        self.assertFalse(self.studio.import_from(path))
        self.assertEqual(self.studio.draft.palette.accent, "#FFC806")

    def test_delete_removes_the_saved_file(self):
        self.studio.edit("colors", "accent", "#FFC806")
        self.studio.save_as("Temp")
        self.assertTrue(self.studio.delete_button.isEnabled())
        self.assertTrue(self.studio.delete_selected())
        self.assertFalse((self.dir / "temp.theme.json").exists())
        self.assertEqual(self.studio.draft, self.refs["blue-modern"])

    def test_nothing_outside_the_temporary_directory_is_written(self):
        default = Path(__file__).resolve().parents[1] / "user_themes"
        existed = default.exists()
        self.studio.edit("colors", "accent", "#FFC806")
        self.studio.save_as("Isolated")
        self.studio.apply()
        self.assertEqual(default.exists(), existed)


class ResponsiveStudioTests(StudioCase):
    def test_wide_shows_both_columns_and_narrow_shows_one_at_a_time(self):
        self.assertFalse(self.studio.compact)
        self.assertTrue(
            self.studio.editor_column.isVisible() and self.studio.preview_column.isVisible()
        )
        self.studio.resize(640, 700)
        self.pump()
        self.assertTrue(self.studio.compact)
        self.assertTrue(self.studio.mode_bar.isVisible())
        self.assertTrue(self.studio.editor_column.isVisible())
        self.assertFalse(self.studio.preview_column.isVisible())
        self.studio.mode_buttons["preview"].click()
        self.pump()
        self.assertTrue(self.studio.preview_column.isVisible())
        self.assertFalse(self.studio.editor_column.isVisible())
        self.studio.resize(1180, 760)
        self.pump()
        self.assertFalse(self.studio.compact)
        self.assertTrue(
            self.studio.editor_column.isVisible() and self.studio.preview_column.isVisible()
        )


class UntrustedTextTests(StudioCase):
    def test_imported_theme_names_are_never_rendered_as_rich_text(self):
        good = json.loads(canonical_json(self.refs["blue-modern"]))
        good.update(kind="user", id="hostile", name="<img src='file:///C:/x.png'><b>Boo</b>")
        path = Path(self._tmp.name) / "hostile.json"
        path.write_text(json.dumps(good), encoding="utf-8")
        self.assertTrue(self.studio.import_from(path))
        self.pump()
        from PySide6.QtCore import Qt as QtNamespace

        self.assertEqual(self.studio.notice.message.textFormat(), QtNamespace.TextFormat.PlainText)
        self.assertIn("<img", self.studio.notice.message.text())
        headings = [
            w
            for w in self.studio.preview.findChildren(type(self.studio.notice.message))
            if "live preview" in w.text()
        ]
        self.assertTrue(headings)
        self.assertEqual(headings[0].textFormat(), QtNamespace.TextFormat.PlainText)


class CompactVerdictTests(StudioCase):
    def test_contrast_verdict_stays_visible_on_the_preview_page_of_a_narrow_studio(self):
        self.studio.resize(640, 700)
        self.pump()
        self.studio.mode_buttons["preview"].click()
        self.studio.edit("colors", "text", self.studio.draft.palette.background)
        self.pump()
        self.assertTrue(self.studio.mode_chip.isVisible())
        self.assertFalse(self.studio.contrast_chip.isVisible())  # it lives on the Edit page
        self.assertIn("FAIL", self.studio.mode_chip.text())
        self.assertEqual(self.studio.mode_chip.property("level"), "blocked")
        self.studio.revert()
        self.pump()
        self.assertIn("ALL 20 PASS", self.studio.mode_chip.text())


class WindowThemeTests(StudioCase):
    def make_window(self):
        window = PrototypeWindow(library=self.lib, theme=self.refs["blue-modern"])
        window.resize(1280, 760)
        window.show()
        self.dispose(window)
        self.pump()
        return window

    def test_applying_a_theme_restyles_the_app_and_preserves_the_session(self):
        window = self.make_window()
        session = window.create_view.session
        window.create_view.source_combo.setCurrentIndex(1)  # load a fixture pack
        window.create_view.preview_button.click()
        revision = session.revision
        old_view = window.create_view
        window.apply_theme(self.refs["concept-a"])
        self.pump()
        self.assertIsNot(window.create_view, old_view)
        self.assertIs(window.create_view.session, session)
        self.assertEqual(session.revision, revision)
        self.assertEqual(window.create_view.layout_design, old_view.layout_design)
        self.assertEqual(COLORS.accent, self.refs["concept-a"].palette.accent)
        self.assertIn(self.refs["concept-a"].palette.accent, self.app.styleSheet())
        self.assertEqual(window.create_view.prompt_text.toPlainText(), PACKS[0].prompt)
        self.assertTrue(session.undo())  # undo history survives the rebuild
        self.pump()
        self.assertEqual(window.create_view.prompt_text.toPlainText(), session.draft.prompt)

    def test_spacing_changes_reach_the_rebuilt_create_view(self):
        window = self.make_window()
        editor_theme = self.refs["blue-modern"]
        from stablenew_qt_proto.theme import ThemeEditor

        editor = ThemeEditor(editor_theme)
        editor.set("spacing", "md", 24)
        window.apply_theme(editor.draft)
        self.pump()
        self.assertEqual(SPACE.md, 24)
        self.assertEqual(window.create_view.form_layout.spacing(), 24)

    def test_studio_apply_drives_the_window_and_is_remembered(self):
        window = self.make_window()
        studio = window.gallery.studio
        window.nav.setCurrentRow(1)
        window.gallery.show_page("studio")
        self.pump()
        studio.select_preset("concept-a")
        self.assertTrue(studio.apply())
        self.pump()
        self.assertEqual(COLORS.accent, self.refs["concept-a"].palette.accent)
        self.assertEqual(self.lib.active_id(), "concept-a")
        self.assertIn("APPLIED", studio.notice.message.text())

    def test_every_page_survives_both_themes_without_stylesheet_warnings(self):
        from PySide6.QtCore import qInstallMessageHandler

        warnings: list[str] = []
        qInstallMessageHandler(
            lambda _m, _c, text: warnings.append(text)
            if "tylesheet" in text or "parse" in text.lower()
            else None
        )
        try:
            window = self.make_window()
            for theme_id in ("concept-a", "blue-modern"):
                window.apply_theme(self.refs[theme_id])
                for row in (0, 1):
                    window.nav.setCurrentRow(row)
                    for page in ("components", "studio"):
                        window.gallery.show_page(page)
                        self.pump()
        finally:
            qInstallMessageHandler(None)
        self.assertEqual(warnings, [])


if __name__ == "__main__":
    unittest.main()
