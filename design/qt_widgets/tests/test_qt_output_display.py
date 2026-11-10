"""Opt-in real Qt tests for the Output Display dock (``STABLENEW_QT_PROTOTYPE_TEST=1``).

They show real windows and measure geometry, so run them on the native Windows
platform; offscreen is only a smoke check (no fonts, widths unrepresentative).
"""

from __future__ import annotations

import os
import unittest

try:
    from PySide6.QtCore import QEvent, QPointF, Qt
    from PySide6.QtGui import QMouseEvent, QWheelEvent
    from PySide6.QtWidgets import QApplication, QScrollArea
    from stablenew_qt_proto.app import PrototypeWindow, apply_theme
    from stablenew_qt_proto.output_model import (
        MAX_ZOOM, MIN_ZOOM, SIZE_FILL, SIZE_FREE, SIZE_LOCKED, ZOOM_CUSTOM, ZOOM_FIT,
    )
except ImportError:
    QApplication = None

ENABLED = QApplication is not None and os.environ.get("STABLENEW_QT_PROTOTYPE_TEST") == "1"


@unittest.skipUnless(ENABLED, "opt-in Qt environment required")
class OutputDisplayTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])
        apply_theme(cls.app)

    def settle(self, rounds: int = 6) -> None:
        for _ in range(rounds):
            self.app.processEvents()

    def make(self, width=1440, height=800):
        window = PrototypeWindow()
        window.resize(width, height)
        window.show()
        self.settle()

        def dispose():
            # Really delete the window: live widgets slow every later application stylesheet change.
            window.close()
            window.deleteLater()
            QApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
            self.app.processEvents()

        self.addCleanup(dispose)
        return window, window.output_dock

    @staticmethod
    def left_edge(window, widget) -> int:
        return widget.mapTo(window, widget.rect().topLeft()).x()

    @staticmethod
    def wheel(delta: int, modifiers=Qt.KeyboardModifier.NoModifier) -> QWheelEvent:
        pos = QPointF(40, 40)
        return QWheelEvent(
            pos, pos, QPointF(0, 0).toPoint(), QPointF(0, delta).toPoint(),
            Qt.MouseButton.NoButton, modifiers, Qt.ScrollPhase.NoScrollPhase, False,
        )

    # ------------------------------------------------------------- placement
    def test_dock_sits_right_of_the_workspace_and_starts_expanded(self):
        window, dock = self.make()
        self.assertTrue(dock.isVisible())
        self.assertFalse(dock.isFloating())
        self.assertEqual(window.dockWidgetArea(dock), Qt.DockWidgetArea.RightDockWidgetArea)
        self.assertGreater(self.left_edge(window, dock), self.left_edge(window, window.create_view))
        self.assertLessEqual(abs(dock.width() - dock.DEFAULT_WIDTH), 4)
        self.assertEqual(dock.size_mode, SIZE_FREE)
        self.assertFalse(dock.collapsed)

    def test_window_minimum_keeps_1280_by_680_usable(self):
        window, _ = self.make(1280, 680)
        self.assertLessEqual(window.minimumSizeHint().width(), 1280)
        self.assertEqual(window.width(), 1280)
        view = window.create_view
        self.assertLessEqual(view.actions.mapTo(window, view.actions.rect().bottomLeft()).y(), window.height())
        for button in (view.undo_button, view.reset_button, view.preview_button, view.admit_button):
            self.assertLessEqual(button.mapTo(window, button.rect().bottomRight()).x(), window.width())
            self.assertGreaterEqual(button.width(), button.minimumWidth())
        for scroll in view.findChildren(QScrollArea):
            self.assertLessEqual(scroll.widget().minimumSizeHint().width(), scroll.viewport().width())

    def test_dock_can_be_moved_to_the_left_but_not_the_bottom(self):
        window, dock = self.make()
        self.assertTrue(dock.allowedAreas() & Qt.DockWidgetArea.LeftDockWidgetArea)
        self.assertFalse(dock.allowedAreas() & Qt.DockWidgetArea.BottomDockWidgetArea)
        window.addDockWidget(Qt.DockWidgetArea.LeftDockWidgetArea, dock)
        self.settle()
        self.assertEqual(window.dockWidgetArea(dock), Qt.DockWidgetArea.LeftDockWidgetArea)
        self.assertLess(self.left_edge(window, dock), self.left_edge(window, window.create_view))

    # ------------------------------------------------------- content/linkage
    def test_frame_follows_the_create_draft(self):
        window, dock = self.make()
        view = window.create_view
        frame = dock.view.frame_content
        self.assertEqual((frame.width, frame.height), (1024, 1024))
        self.assertEqual(frame.kind, "draft")
        self.assertIn("explorer", frame.lines[0])
        view.setting_inputs["width"].setValue(768)
        view.setting_inputs["height"].setValue(1344)
        self.assertEqual((dock.view.frame_content.width, dock.view.frame_content.height), (768, 1344))
        self.assertIn("768 × 1344", dock.panel.status.text())
        view.preview_button.click()
        self.assertEqual(dock.view.frame_content.kind, "preview")
        view.setting_inputs["steps"].setValue(41)
        self.assertEqual(dock.view.frame_content.kind, "stale")
        view.preview_button.click()
        view.admit_button.click()
        self.assertEqual(dock.view.frame_content.kind, "receipt")
        self.assertIn("no image", dock.panel.status.text().lower())

    # ------------------------------------------------------------- collapse
    def test_collapse_to_rail_and_restore_width(self):
        window, dock = self.make()
        width_before = dock.width()
        window_center_before = window.create_view.width()
        dock.set_collapsed(True)
        self.settle()
        self.assertEqual(dock.width(), dock.RAIL_WIDTH)
        self.assertFalse(dock.panel.isVisible())
        self.assertTrue(dock.rail.isVisible())
        self.assertGreater(window.create_view.width(), window_center_before)  # workspace reclaims space
        self.assertFalse(window.output_toggle.isChecked())
        dock.set_collapsed(False)
        self.settle()
        self.assertTrue(dock.panel.isVisible())
        self.assertFalse(dock.rail.isVisible())
        self.assertLessEqual(abs(dock.width() - width_before), 4)
        self.assertTrue(window.output_toggle.isChecked())

    def test_header_toggle_and_shortcut_collapse(self):
        window, dock = self.make()
        window.output_toggle.click()
        self.settle()
        self.assertTrue(dock.collapsed)
        window.output_toggle.click()
        self.settle()
        self.assertFalse(dock.collapsed)
        shortcuts = {a.shortcut().toString() for a in window.actions()}
        self.assertIn("Ctrl+3", shortcuts)

    def test_title_bar_buttons(self):
        _, dock = self.make()
        dock.title_bar.collapse_button.click()
        self.settle()
        self.assertTrue(dock.collapsed)
        dock.title_bar.collapse_button.click()
        self.settle()
        self.assertFalse(dock.collapsed)
        dock.title_bar.float_button.click()
        self.settle()
        self.assertTrue(dock.isFloating())
        self.assertEqual(dock.title_bar.float_button.text(), "Dock")
        dock.title_bar.float_button.click()
        self.settle()
        self.assertFalse(dock.isFloating())
        self.assertEqual(dock.title_bar.float_button.text(), "Undock")

    # ------------------------------------------------------------- dock/undock
    def test_undock_collapse_and_redock(self):
        window, dock = self.make()
        dock.setFloating(True)
        self.settle()
        self.assertTrue(dock.isFloating())
        self.assertTrue(dock.isVisible())
        self.assertGreater(dock.view.viewport().width(), 200)
        dock.set_collapsed(True)
        self.settle()
        self.assertLess(dock.height(), 90)  # title bar only
        self.assertFalse(dock.panel.isVisible())
        dock.set_collapsed(False)
        self.settle()
        self.assertGreater(dock.height(), 300)
        dock.setFloating(False)
        self.settle()
        self.assertFalse(dock.isFloating())
        self.assertEqual(window.dockWidgetArea(dock), Qt.DockWidgetArea.RightDockWidgetArea)

    def test_floating_dock_is_resizable_in_free_mode(self):
        _, dock = self.make()
        dock.setFloating(True)
        self.settle()
        dock.resize(700, 600)
        self.settle()
        self.assertGreaterEqual(dock.width(), 690)
        self.assertGreaterEqual(dock.height(), 590)

    # ------------------------------------------------------------ size modes
    def test_lock_freezes_docked_width_while_the_window_grows(self):
        window, dock = self.make(1300, 760)
        dock.set_size_mode(SIZE_LOCKED)
        self.settle()
        locked = dock.width()
        window.resize(1700, 820)
        self.settle()
        self.assertEqual(dock.width(), locked)
        self.assertEqual(dock.minimumWidth(), dock.maximumWidth())
        self.assertIn("Locked", dock.panel.mode_hint.text())
        window.resizeDocks([dock], [locked + 200], Qt.Orientation.Horizontal)
        self.settle()
        self.assertEqual(dock.width(), locked)  # a drag cannot change a locked dock

    def test_unlock_allows_resize_again(self):
        window, dock = self.make(1500, 760)
        dock.set_size_mode(SIZE_LOCKED)
        self.settle()
        dock.set_size_mode(SIZE_FREE)
        self.settle()
        window.resizeDocks([dock], [520], Qt.Orientation.Horizontal)
        self.settle()
        self.assertLessEqual(abs(dock.width() - 520), 4)

    def test_free_mode_resize_has_a_minimum(self):
        window, dock = self.make(1500, 760)
        window.resizeDocks([dock], [100], Qt.Orientation.Horizontal)
        self.settle()
        self.assertGreaterEqual(dock.width(), dock.MIN_EXPANDED_WIDTH)

    def test_fill_tracks_the_window_and_leaves_the_workspace_its_width(self):
        window, dock = self.make(1500, 760)
        dock.set_size_mode(SIZE_FILL)
        self.settle()
        first = dock.width()
        self.assertGreater(first, dock.DEFAULT_WIDTH)
        window.resize(1900, 800)
        self.settle()
        self.assertGreater(dock.width(), first)
        # Workspace keeps (about) its preferred width.
        self.assertLessEqual(abs(window.centralWidget().width() - 900), 24)
        window.resize(1300, 800)
        self.settle()
        self.assertLess(dock.width(), first)
        self.assertGreaterEqual(dock.width(), dock.MIN_EXPANDED_WIDTH)

    def test_fill_does_nothing_while_collapsed_then_applies_on_expand(self):
        window, dock = self.make(1700, 760)
        dock.set_collapsed(True)
        dock.set_size_mode(SIZE_FILL)
        self.settle()
        self.assertEqual(dock.width(), dock.RAIL_WIDTH)
        dock.set_collapsed(False)
        self.settle()
        self.assertGreater(dock.width(), dock.DEFAULT_WIDTH)

    def test_locked_width_survives_collapse_and_expand(self):
        _, dock = self.make(1400, 760)
        dock.set_size_mode(SIZE_LOCKED)
        self.settle()
        locked = dock.width()
        dock.set_collapsed(True)
        self.settle()
        self.assertEqual(dock.width(), dock.RAIL_WIDTH)
        dock.set_collapsed(False)
        self.settle()
        self.assertEqual(dock.width(), locked)

    def test_floating_lock_freezes_size_and_fill_covers_screen(self):
        _, dock = self.make()
        dock.setFloating(True)
        self.settle()
        dock.resize(640, 620)
        self.settle()
        free_geometry = dock.geometry()
        dock.set_size_mode(SIZE_LOCKED)
        self.settle()
        dock.resize(900, 900)
        self.settle()
        self.assertEqual((dock.width(), dock.height()), (free_geometry.width(), free_geometry.height()))
        dock.set_size_mode(SIZE_FILL)
        self.settle()
        available = dock.screen().availableGeometry()
        self.assertEqual(dock.geometry(), available)
        dock.set_size_mode(SIZE_FREE)
        self.settle()
        self.assertEqual((dock.width(), dock.height()), (free_geometry.width(), free_geometry.height()))

    def test_mode_buttons_reflect_state(self):
        _, dock = self.make()
        for mode in (SIZE_LOCKED, SIZE_FILL, SIZE_FREE):
            dock.panel.mode_buttons[mode].click()
            self.settle()
            self.assertEqual(dock.size_mode, mode)
            self.assertTrue(dock.panel.mode_buttons[mode].isChecked())
        with self.assertRaises(ValueError):
            dock.set_size_mode("sideways")

    # ------------------------------------------------------------------- zoom
    def test_zoom_buttons_slider_and_clamps(self):
        _, dock = self.make()
        view, panel = dock.view, dock.panel
        self.assertEqual(view.mode, ZOOM_FIT)
        self.assertTrue(panel.fit_button.isChecked())
        panel.zoom_in_button.click()
        self.assertEqual(view.mode, ZOOM_CUSTOM)
        self.assertFalse(panel.fit_button.isChecked())
        panel.actual_button.click()
        self.assertEqual(view.zoom, 1.0)
        self.assertIn("100%", panel.status.text())
        panel.zoom_out_button.click()
        self.assertLess(view.zoom, 1.0)
        panel.slider.setValue(panel.slider.maximum())
        self.assertAlmostEqual(view.zoom, MAX_ZOOM)
        self.assertFalse(panel.zoom_in_button.isEnabled())
        panel.slider.setValue(0)
        self.assertAlmostEqual(view.zoom, MIN_ZOOM)
        self.assertFalse(panel.zoom_out_button.isEnabled())
        panel.fit_button.click()
        self.assertEqual(view.mode, ZOOM_FIT)

    def test_fit_follows_resizes_but_custom_zoom_is_kept(self):
        window, dock = self.make(1500, 760)
        view = dock.view
        fit_before = view.zoom
        window.resizeDocks([dock], [640], Qt.Orientation.Horizontal)
        self.settle()
        self.assertGreater(view.zoom, fit_before)
        self.assertEqual(view.mode, ZOOM_FIT)
        view.zoom_to(0.75)
        window.resizeDocks([dock], [420], Qt.Orientation.Horizontal)
        self.settle()
        self.assertEqual(view.zoom, 0.75)
        self.assertEqual(view.mode, ZOOM_CUSTOM)

    def test_fit_shows_the_whole_frame(self):
        _, dock = self.make()
        view = dock.view
        scene_rect = view.sceneRect()
        self.assertLessEqual(scene_rect.width() * view.zoom, view.viewport().width() + 1)
        self.assertLessEqual(scene_rect.height() * view.zoom, view.viewport().height() + 1)
        self.assertEqual(view.horizontalScrollBar().maximum(), 0)

    def test_ctrl_wheel_zooms_plain_wheel_does_not(self):
        _, dock = self.make()
        view = dock.view
        start = view.zoom
        view.wheelEvent(self.wheel(120))
        self.assertEqual(view.zoom, start)  # no modifier: no zoom
        view.wheelEvent(self.wheel(120, Qt.KeyboardModifier.ControlModifier))
        self.assertGreater(view.zoom, start)
        zoomed = view.zoom
        view.wheelEvent(self.wheel(-240, Qt.KeyboardModifier.ControlModifier))
        self.assertLess(view.zoom, zoomed)
        self.assertEqual(view.mode, ZOOM_CUSTOM)

    def test_double_click_toggles_fit_and_actual_size(self):
        _, dock = self.make()
        view = dock.view
        event = QMouseEvent(
            QEvent.Type.MouseButtonDblClick, QPointF(30, 30), QPointF(30, 30),
            Qt.MouseButton.LeftButton, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier,
        )
        view.mouseDoubleClickEvent(event)
        self.assertEqual((view.mode, view.zoom), (ZOOM_CUSTOM, 1.0))
        view.mouseDoubleClickEvent(event)
        self.assertEqual(view.mode, ZOOM_FIT)

    def test_zoomed_in_view_can_pan(self):
        _, dock = self.make()
        view = dock.view
        view.zoom_to(2.0)
        self.settle()
        self.assertGreater(view.horizontalScrollBar().maximum(), 0)
        self.assertEqual(view.dragMode(), view.DragMode.ScrollHandDrag)

    def test_zoom_actions_have_shortcuts(self):
        from PySide6.QtWidgets import QWidget

        _, dock = self.make()
        shortcuts = {s.toString() for a in QWidget.actions(dock) for s in a.shortcuts()}
        self.assertTrue({"Ctrl+=", "Ctrl+-", "Ctrl+0", "Ctrl+9"} <= shortcuts)

    def test_frame_change_keeps_custom_zoom(self):
        window, dock = self.make()
        dock.view.zoom_to(0.5)
        window.create_view.setting_inputs["width"].setValue(512)
        self.assertEqual(dock.view.zoom, 0.5)
        self.assertEqual(dock.view.frame_content.width, 512)

    def test_no_horizontal_clipping_with_dock_collapsed_at_960(self):
        window, dock = self.make(960, 600)
        dock.set_collapsed(True)
        self.settle()
        self.assertLessEqual(window.minimumSizeHint().width(), 960)
        for scroll in window.create_view.findChildren(QScrollArea):
            self.assertLessEqual(scroll.widget().minimumSizeHint().width(), scroll.viewport().width())

    def test_long_prompt_does_not_break_the_frame(self):
        window, dock = self.make()
        window.create_view.prompt_text.setPlainText("word " * 400 + "<b>&</b>")
        self.settle()
        self.assertTrue(dock.view.frame_content.lines[0])
        self.assertGreater(dock.view.zoom, 0)


if __name__ == "__main__":
    unittest.main()
