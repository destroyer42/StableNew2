"""Opt-in native Windows interaction coverage for the isolated Edit prototype."""

from __future__ import annotations

import math
import os
import unittest

from stablenew_qt_proto.edit_domain import CREATE_SOURCE, EditRefused, Mode, Replacement

try:
    from PySide6.QtCore import QEvent, QPoint, Qt, QTimer
    from PySide6.QtGui import QWheelEvent
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QApplication
    from shiboken6 import isValid
    from stablenew_qt_proto.app import PrototypeWindow, apply_theme
    from stablenew_qt_proto.edit_components import fixture_image
    from stablenew_qt_proto.layout_probe import pump
    from stablenew_qt_proto.tokens import reference_theme
except ImportError:
    QApplication = None

ENABLED = QApplication is not None and os.environ.get("STABLENEW_QT_PROTOTYPE_TEST") == "1"


@unittest.skipUnless(ENABLED, "opt-in Qt environment required")
class NativeEditTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        apply_theme(self.app, reference_theme("blue-modern"))
        self.window = PrototypeWindow()
        self.view = self.window.edit_view
        self.window.nav.setCurrentRow(2)
        self.window.resize(1280, 680)
        self.window.show()
        self.window.activateWindow()
        pump(self.app)
        self.addCleanup(self._dispose)

    def _dispose(self):
        if isValid(self.window):
            self.window.close()
            self.window.deleteLater()
            QApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
            pump(self.app)
        apply_theme(self.app, reference_theme("blue-modern"))

    def pick(self, key, *, choice=None):
        if choice is not None:

            def press_choice():
                modal = self.app.activeModalWidget()
                button = next(button for button in modal.buttons() if button.text() == choice)
                QTest.mouseClick(button, Qt.MouseButton.LeftButton)

            QTimer.singleShot(0, self.view, press_choice)
        index = self.view.picker.findData(key)
        self.assertGreater(index, 0)
        self.view.picker.setCurrentIndex(index)
        self.view.picker.activated.emit(index)
        pump(self.app)

    def type_prompt(self, text):
        self.view.prompt.setFocus()
        QTest.keyClick(self.view.prompt, Qt.Key.Key_A, Qt.KeyboardModifier.ControlModifier)
        QTest.keyClicks(self.view.prompt, text)

    def pixel(self, x, y):
        tx = self.view.canvas.transform()
        return QPoint(math.ceil(tx.left + x * tx.scale), math.ceil(tx.top + y * tx.scale))

    def stroke(self, start, end=None, *, cancel=False):
        canvas = self.view.canvas
        start = self.pixel(*start)
        end = self.pixel(*end) if end else start
        QTest.mousePress(canvas, Qt.MouseButton.LeftButton, pos=start)
        QTest.mouseMove(canvas, end)
        if cancel:
            QTest.keyClick(canvas, Qt.Key.Key_Escape)
        QTest.mouseRelease(canvas, Qt.MouseButton.LeftButton, pos=end)
        pump(self.app)

    def test_edit_01_create_handoff_and_quick_edit(self):
        self.window.nav.setCurrentRow(0)
        create = self.window.create_view
        create.preview_button.click()
        create.admit_button.click()
        pump(self.app)
        self.assertTrue(create.edit_result.isVisible())
        QTest.mouseClick(create.edit_result, Qt.MouseButton.LeftButton)
        self.assertIs(self.window.pages.currentWidget(), self.view)
        self.assertEqual(self.view.session.draft.source_key, CREATE_SOURCE)
        self.assertEqual(self.view.status.text(), "Not built")
        self.assertFalse(self.view.admit_button.isEnabled())
        self.type_prompt("Warm the valley")
        QTest.keyClick(self.view.prompt, Qt.Key.Key_Return, Qt.KeyboardModifier.ControlModifier)
        self.assertEqual(self.view.status.text(), "Current / ready")
        self.view.admit_button.click()
        self.assertEqual(self.view.status.text(), "Simulated admission recorded")
        self.assertIn(CREATE_SOURCE, self.view.compare.labels[0].text())
        self.assertIn("edit:candidate-1", self.view.compare.labels[1].text())
        self.assertIn("Warm the valley", self.view.candidate_summary.text())
        self.view.admit_button.click()
        self.assertEqual(len(self.view.session.candidates), 1)

    def test_edit_02_paint_erase_cancel_undo_zoom_and_pan(self):
        self.pick("history:ridge-17")
        self.view.mode.setCurrentText(Mode.MASKED)
        self.type_prompt("Bring out the foreground")
        canvas = self.view.canvas
        original = canvas.image.copy()
        self.view.zoom.buttons["100%"].click()
        self.assertEqual(canvas.transform().scale, 1)
        start = self.pixel(290, 170)
        QTest.mousePress(canvas, Qt.MouseButton.MiddleButton, pos=start)
        QTest.mouseMove(canvas, start + QPoint(23, 14))
        QTest.mouseRelease(canvas, Qt.MouseButton.MiddleButton, pos=start + QPoint(23, 14))
        self.assertEqual(canvas.pan.toPoint(), QPoint(23, 14))
        self.stroke((275, 150), (325, 190))
        mask = self.view.session.draft.region.mask
        self.assertEqual(mask[170 * 640 + 300], 255)
        self.assertIn("Mask ·", self.view.coverage.text())
        self.assertIn("x 325 · y 190", self.view.coordinates.text())
        self.assertFalse(canvas.overlay.isNull())
        self.view.tool.setCurrentText("Erase")
        self.view.brush.setValue(5)
        self.stroke((300, 170))
        erased = self.view.session.draft.region.mask
        self.assertLess(erased.count(255), mask.count(255))
        self.stroke((280, 154), cancel=True)
        self.assertEqual(self.view.session.draft.region.mask, erased)
        QTest.keyClick(canvas, Qt.Key.Key_Z, Qt.KeyboardModifier.AltModifier)
        self.assertEqual(self.view.session.draft.region.mask, mask)
        QTest.keyClick(canvas, Qt.Key.Key_Y, Qt.KeyboardModifier.AltModifier)
        self.assertEqual(self.view.session.draft.region.mask, erased)
        self.assertEqual(canvas.image, original)
        self.view.preview_button.click()
        self.view.admit_button.click()
        self.assertIn("history:ridge-17", self.view.compare.labels[0].text())
        self.view.compare.zoom.buttons["100%"].click()
        self.assertEqual(self.view.compare.left.transform().scale, 1)
        self.assertEqual(self.view.compare.right.transform().scale, 1)
        self.view.inspector.setCurrentWidget(self.view.review_scroll)
        self.view.recorded_parent.click()
        self.assertIn(
            "Verified fixture parent · history:ridge-16", self.view.compare.labels[0].text()
        )

    def test_edit_03_geometry_and_mock_output(self):
        picker = self.view.picker
        picker.setFocus()
        for _ in range(picker.findData("photo:evening")):
            QTest.keyClick(picker, Qt.Key.Key_Down)
        self.assertEqual(self.view.session.draft.source_key, "photo:evening")
        self.view.mode.setCurrentText(Mode.EXTEND)
        self.view.margins["top"].setValue(48)
        self.view.margins["left"].setValue(72)
        self.type_prompt("Continue the evening sky")
        self.assertIn("Source at (72, 48)", self.view.image_note.text())
        self.assertIn("704 × 448", self.view.image_note.text())
        self.assertIsNotNone(self.view.canvas.geometry_overlay)
        self.view.preview_button.click()
        self.assertIn("No pixel-preservation result", self.view.preview_summary.text())
        self.view.admit_button.click()
        self.assertEqual(self.view.compare.right.image.size().toTuple(), (704, 448))
        self.assertEqual(
            self.view.compare.right.image.pixel(72, 48), self.view.compare.left.image.pixel(0, 0)
        )

    def test_edit_04_compare_iterate_and_set_baseline(self):
        self.pick(CREATE_SOURCE)
        self.type_prompt("Softer foreground")
        self.view.preview_button.click()
        self.view.admit_button.click()
        first = self.view.session.candidates[0]
        self.view.compare_button.click()
        self.view.advanced.toggle.click()
        self.assertTrue(self.view.advanced.body.isVisible())
        self.view.strength.setValue(72)
        self.assertEqual(self.view.status.text(), "Stale")
        self.assertFalse(self.view.admit_button.isEnabled())
        self.assertIn("40% → 72%", self.view.preview_summary.text())
        self.view.preview_button.click()
        self.view.admit_button.click()
        self.view.peer_picker.setCurrentIndex(self.view.peer_picker.findData(first.key))
        self.assertIn(first.key, self.view.compare.labels[0].text())
        self.assertIn("40% → 72%", self.view.candidate_summary.text())
        self.view.candidate_picker.setCurrentIndex(self.view.candidate_picker.findData(first.key))
        self.view.baseline.click()
        self.assertIn(f"Working Baseline · {first.key}", self.view.baseline_note.text())
        self.assertIn("Preferred / Final · none", self.view.baseline_note.text())
        self.assertEqual(first.preview.draft.region.strength, 40)
        self.assertEqual(len(self.view.session.candidates), 2)

    def test_edit_05_refusals_and_cancelled_replacement(self):
        for key, reason in (
            ("history:missing", "Missing file"),
            ("history:hidden", "Hidden"),
            ("import:clip", "Unsupported media"),
        ):
            with self.subTest(key=key):
                self.pick(key)
                self.assertIn(reason, self.view.banner.message.text())
                self.assertTrue(self.view.canvas.image.isNull())
                self.assertIsNone(self.view.session.draft)
                with self.assertRaises(EditRefused):
                    fixture_image(key)
        self.pick("import:coast")
        self.assertTrue(self.view.negative_field.isHidden())
        self.type_prompt("Tidy the water")
        self.view.mode.setCurrentText(Mode.EXTEND)
        self.view.margins["left"].setValue(0)
        self.view.margins["right"].setValue(0)
        self.view.preview_button.click()
        self.assertEqual(self.view.status.text(), "Blocked")
        self.assertIn("positive extension margin", self.view.preview_summary.text())
        self.assertFalse(self.view.admit_button.isEnabled())
        self.window.resize(960, 600)
        pump(self.app)
        summary = self.view.preview_summary
        self.assertGreaterEqual(summary.height(), summary.heightForWidth(summary.width()))
        old = self.view.session.draft
        self.pick(CREATE_SOURCE, choice=Replacement.CANCEL)
        self.assertIs(self.view.session.draft, old)
        self.view.mode.setCurrentText(Mode.MASKED)
        self.view.inspector.setCurrentWidget(self.view.settings_scroll)
        self.view.advanced.toggle.click()
        self.view.assist.click()
        self.assertIn("Simulated suggestion unavailable", self.view.banner.message.text())
        self.assertTrue(self.view.suggestion_controls.isHidden())
        self.pick(CREATE_SOURCE, choice=Replacement.KEEP)
        self.assertEqual(self.view.session.draft.source_key, "import:coast")
        self.pick(CREATE_SOURCE, choice=Replacement.REPLACE)
        self.assertEqual(self.view.session.draft.source_key, CREATE_SOURCE)

    def test_assisted_mask_accept_reject_and_manual_revision(self):
        self.pick(CREATE_SOURCE)
        self.view.mode.setCurrentText(Mode.MASKED)
        self.view.advanced.toggle.click()
        self.view.assist.click()
        pump(self.app)
        self.assertTrue(self.view.suggestion_controls.isVisible())
        self.assertFalse(self.view.preview_button.isEnabled())
        self.stroke((400, 212))
        self.assertFalse(self.view.session.draft.region.mask)
        self.view.reject_suggestion.click()
        self.assertFalse(self.view.session.draft.region.mask)
        self.view.assist.click()
        pump(self.app)
        self.stroke((400, 212))
        self.view.accept_suggestion.click()
        self.assertEqual(self.view.session.draft.region.mask[212 * 640 + 400], 255)
        self.view.clear_mask.click()
        self.assertFalse(self.view.session.draft.region.mask)
        self.view.undo.click()
        self.assertEqual(self.view.session.draft.region.mask[212 * 640 + 400], 255)

    def test_native_resize_theme_navigation_and_focus_preserve_state(self):
        self.pick(CREATE_SOURCE)
        self.view.mode.setCurrentText(Mode.MASKED)
        self.type_prompt("Preserve my edit")
        self.stroke((300, 200))
        self.view.zoom.buttons["100%"].click()
        self.view.preview_button.click()
        saved = self.view.session.draft, self.view.session.preview, self.view.canvas.zoom
        for theme in ("concept-a", "blue-modern"):
            self.window.nav.setCurrentRow(1)
            self.window.apply_theme(reference_theme(theme))
            self.window.nav.setCurrentRow(2)
            pump(self.app)
            for size in ((960, 600), (1280, 680), (1366, 768), (1440, 900), (1920, 1080)):
                self.window.resize(*size)
                pump(self.app)
                self.assertEqual(self.window.size().toTuple(), size)
                self.assertGreaterEqual(self.view.canvas.height(), 225)
                self.assertFalse(self.window.output_dock.isVisible())
                for widget in (
                    self.view.preview_button,
                    self.view.admit_button,
                    self.view.tool,
                    self.view.clear_mask,
                ):
                    self.assertTrue(widget.isVisible())
                    point = widget.mapTo(self.window, widget.rect().bottomRight())
                    self.assertTrue(self.window.rect().contains(point))
                viewport = self.view.review_scroll.viewport()
                self.assertLessEqual(self.view.review_scroll.widget().width(), viewport.width())
            old_width = self.view.canvas.width()
            self.view.inspector_toggle.click()
            pump(self.app)
            self.assertGreater(self.view.canvas.width(), old_width)
            self.view.inspector_toggle.click()
            self.assertEqual(
                (self.view.session.draft, self.view.session.preview, self.view.canvas.zoom), saved
            )
        self.view.preview_button.setFocus()
        QTest.keyClick(self.view.preview_button, Qt.Key.Key_Tab)
        self.assertIs(self.app.focusWidget(), self.view.admit_button)
        QTest.keyClick(self.view.admit_button, Qt.Key.Key_Tab, Qt.KeyboardModifier.ShiftModifier)
        self.assertIs(self.app.focusWidget(), self.view.preview_button)
        self.assertTrue(self.view.preview_button.hasFocus())

    def test_wheel_requires_control_and_layout_is_stable_during_press(self):
        self.pick(CREATE_SOURCE)
        self.view.mode.setCurrentText(Mode.MASKED)
        canvas = self.view.canvas
        position = self.pixel(320, 200)
        initial = canvas.transform().scale
        for modifier in (Qt.KeyboardModifier.NoModifier, Qt.KeyboardModifier.ControlModifier):
            event = QWheelEvent(
                position,
                canvas.mapToGlobal(position),
                QPoint(),
                QPoint(0, 120),
                Qt.MouseButton.NoButton,
                modifier,
                Qt.ScrollPhase.NoScrollPhase,
                False,
            )
            QApplication.sendEvent(canvas, event)
            if modifier == Qt.KeyboardModifier.NoModifier:
                self.assertEqual(canvas.transform().scale, initial)
                self.assertFalse(event.isAccepted())
        self.assertGreater(canvas.transform().scale, initial)
        before = canvas.geometry(), self.view.preview_button.geometry()
        QTest.mousePress(canvas, Qt.MouseButton.LeftButton, pos=position)
        pump(self.app)
        self.assertEqual(before, (canvas.geometry(), self.view.preview_button.geometry()))
        QTest.mouseRelease(canvas, Qt.MouseButton.LeftButton, pos=position)

    def test_destroy_while_editing_and_reopen(self):
        self.pick(CREATE_SOURCE)
        self.view.mode.setCurrentText(Mode.MASKED)
        canvas = self.view.canvas
        QTest.mousePress(canvas, Qt.MouseButton.LeftButton, pos=self.pixel(300, 200))
        self.window.close()
        self.window.deleteLater()
        QApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        pump(self.app)
        self.assertFalse(isValid(canvas))
        self.window = PrototypeWindow()
        self.view = self.window.edit_view
        self.window.nav.setCurrentRow(2)
        self.window.show()
        pump(self.app)
        self.assertIsNone(self.view.session.draft)
        self.assertFalse(self.view.session.candidates)
