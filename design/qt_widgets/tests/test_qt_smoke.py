"""Opt-in real Qt display tests. Execute on authorized Windows Python 3.14 Qt env.

Set ``STABLENEW_QT_PROTOTYPE_TEST=1``. These tests show windows (they never
submit anything) and measure real layout, so run them on an uncontended desktop
or with ``QT_QPA_PLATFORM=offscreen`` for headless smoke coverage.
"""

from __future__ import annotations

import os
import unittest

# No unconditional Qt import: this module is safe to collect without Qt.
try:
    from PySide6.QtCore import QEvent, QPointF, Qt, qInstallMessageHandler
    from PySide6.QtGui import QPixmap, QWheelEvent
    from PySide6.QtWidgets import QApplication, QComboBox, QScrollArea, QWidget
    from stablenew_qt_proto.app import PrototypeWindow, apply_theme
    from stablenew_qt_proto.tokens import ASSET_DIR, ASSET_FILES
except ImportError:
    QApplication = None

ENABLED = QApplication is not None and os.environ.get("STABLENEW_QT_PROTOTYPE_TEST") == "1"


@unittest.skipUnless(ENABLED, "opt-in Qt environment required")
class QtWidgetSmokeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.stylesheet_warnings: list[str] = []

        def handler(_mode, _context, message):
            if "stylesheet" in message.lower() or "parse" in message.lower():
                cls.stylesheet_warnings.append(message)

        qInstallMessageHandler(handler)
        cls.app = QApplication.instance() or QApplication([])
        apply_theme(cls.app)
        qInstallMessageHandler(None)

    def make(self, width=1280, height=680):
        window = PrototypeWindow()
        window.resize(width, height)
        window.show()
        self.app.processEvents()

        def dispose():
            # Really delete the window: live widgets slow every later application stylesheet change.
            window.close()
            window.deleteLater()
            QApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
            self.app.processEvents()

        self.addCleanup(dispose)
        return window, window.pages.widget(0)

    def test_stylesheet_parses_without_warnings(self):
        self.assertEqual(self.stylesheet_warnings, [])

    def test_svg_assets_load(self):
        for name in ASSET_FILES:
            self.assertFalse(QPixmap(str(ASSET_DIR / name)).isNull(), name)

    def test_window_and_gallery_construct(self):
        window, _ = self.make()
        self.assertEqual(window.pages.count(), 2)
        self.assertEqual(window.nav.count(), 2)
        window.nav.setCurrentRow(1)
        self.app.processEvents()
        self.assertTrue(window.pages.currentWidget().isVisible())

    def test_create_preview_stale_and_receipt(self):
        window, view = self.make()
        view.preview_button.click()
        self.assertTrue(view.admit_button.isEnabled())
        view.prompt_text.setPlainText("different prompt")
        self.assertFalse(view.admit_button.isEnabled())
        self.assertIn("STALE", view.preview_chip.text())
        view.preview_button.click()
        self.assertTrue(view.admit_button.isEnabled())
        view.admit_button.click()
        self.assertIn("No job submitted", view.result_text.text())

    def test_actions_stay_inside_window_at_minimum_target_size(self):
        window, view = self.make(1280, 680)
        bottom = view.actions.mapTo(window, view.actions.rect().bottomLeft()).y()
        self.assertLessEqual(bottom, window.height())
        for button in (view.undo_button, view.reset_button, view.preview_button, view.admit_button):
            self.assertTrue(button.isVisible())
            self.assertLessEqual(
                button.mapTo(window, button.rect().bottomRight()).x(), window.width()
            )

    def test_no_horizontal_clipping_at_target_and_minimum_sizes(self):
        for width, height in ((1280, 680), (1440, 900), (960, 600)):
            window, view = self.make(width, height)
            if (
                width < 1200
            ):  # the expanded Output Display needs >= ~1200 px; collapse it for small windows
                window.output_dock.set_collapsed(True)
                self.app.processEvents()
            for scroll in (pane for pane in view.findChildren(QScrollArea) if pane.isVisible()):
                self.assertLessEqual(
                    scroll.widget().minimumSizeHint().width(),
                    scroll.viewport().width(),
                    f"{width}x{height}",
                )
            self.assertLessEqual(window.minimumSizeHint().width(), window.width())
            self.assertLessEqual(window.minimumSizeHint().height(), window.height())

    def test_settings_grid_reflows_with_width(self):
        _, wide = self.make(1920, 1080)
        narrow_window, narrow = self.make(960, 600)
        narrow_window.output_dock.set_collapsed(True)
        self.app.processEvents()
        self.assertGreater(wide.settings_grid.columns, narrow.settings_grid.columns)
        self.assertGreaterEqual(narrow.settings_grid.columns, 1)

    def test_lock_and_reset_controls(self):
        _, view = self.make()
        view.setting_inputs["steps"].setValue(40)
        field = view.setting_fields["steps"]
        self.assertTrue(field.reset_button.isEnabled())
        self.assertIn("Manual · rec. 28", field.recommendation.text())
        field.reset_button.click()
        self.assertEqual(view.setting_inputs["steps"].value(), 28)
        self.assertFalse(field.reset_button.isEnabled())
        field.lock.setChecked(True)
        self.assertIn("steps", view.session.draft.locked_fields)

    def test_model_switch_updates_size_presets_and_keeps_log(self):
        _, view = self.make()
        view.model_combo.setCurrentIndex(1)
        self.assertEqual(view.size_combo.itemText(1), "768 × 1360")
        view.pack_name.setText("later")
        self.assertIn("Changed model fixture", view.change_log_view.toPlainText())

    def test_undo_redo_buttons_track_session(self):
        _, view = self.make()
        self.assertFalse(view.undo_button.isEnabled())
        view.setting_inputs["steps"].setValue(33)
        self.assertTrue(view.undo_button.isEnabled())
        view.undo_button.click()
        self.assertEqual(view.setting_inputs["steps"].value(), 28)
        self.assertTrue(view.redo_button.isEnabled())
        view.redo_button.click()
        self.assertEqual(view.setting_inputs["steps"].value(), 33)

    def test_reset_is_undoable_without_modal_dialog(self):
        _, view = self.make()
        view.prompt_text.setPlainText("custom")
        view.reset_button.click()
        self.assertNotEqual(view.prompt_text.toPlainText(), "custom")
        view.undo_button.click()
        self.assertEqual(view.prompt_text.toPlainText(), "custom")

    def test_slot_rename_and_duplicate_guard(self):
        _, view = self.make()
        view.slots.item(0, 0).setText("hero")
        self.assertIn("hero", view.session.draft.slots)
        view.slots.item(1, 0).setText("hero")
        self.assertIn("DUPLICATE", view.banner.message.text())
        self.assertIn("hero", view.session.draft.slots)

    def test_unfocused_spinbox_ignores_wheel(self):
        _, view = self.make()
        spin = view.setting_inputs["steps"]
        spin.clearFocus()
        wheel = QWheelEvent(
            QPointF(5, 5),
            QPointF(5, 5),
            QPointF(0, 0).toPoint(),
            QPointF(0, 120).toPoint(),
            Qt.MouseButton.NoButton,
            Qt.KeyboardModifier.NoModifier,
            Qt.ScrollPhase.NoScrollPhase,
            False,
        )
        self.assertTrue(view._wheel_guard.eventFilter(spin, wheel))
        self.assertFalse(wheel.isAccepted())  # parent scroll area gets it
        self.assertEqual(spin.value(), 28)

    def test_combo_boxes_are_not_editable(self):
        _, view = self.make()
        for name in ("sampler", "scheduler"):
            self.assertFalse(view.setting_inputs[name].isEditable())
        self.assertTrue(
            all(isinstance(view.setting_inputs[n], QComboBox) for n in ("sampler", "scheduler"))
        )

    def test_keyboard_shortcut_actions_exist(self):
        _, view = self.make()
        # CreateView.actions is the footer strip, so use the base-class accessor.
        shortcuts = {a.shortcut().toString() for a in QWidget.actions(view)}
        self.assertTrue({"Alt+Z", "Alt+Y", "Ctrl+Return", "Ctrl+Shift+Return"} <= shortcuts)


if __name__ == "__main__":
    unittest.main()
