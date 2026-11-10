"""Opt-in Qt tests for the mock Create workflow and its two layout designs (STABLENEW_QT_PROTOTYPE_TEST=1).

The tests measure the real widget geometry of the running window. Pixel sizes depend on the platform
font, so thresholds are relative (reachable / clipped / overflow) rather than absolute pixel counts.
"""

from __future__ import annotations

import os
import socket
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

try:
    from PySide6.QtCore import QEvent, Qt
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QApplication, QComboBox
    from stablenew_qt_proto.app import PrototypeWindow, apply_theme
    from stablenew_qt_proto.create_view import LAYOUT_DESIGNS, LAYOUT_SCROLL, LAYOUT_SPLIT
    from stablenew_qt_proto.domain import PACKS, SOURCE_FREE
    from stablenew_qt_proto.layout_probe import REQUIRED_CONTROLS, probe
    from stablenew_qt_proto.theme_store import ThemeLibrary
    from stablenew_qt_proto.tokens import reference_themes
except ImportError:
    QApplication = None

ENABLED = QApplication is not None and os.environ.get("STABLENEW_QT_PROTOTYPE_TEST") == "1"


@unittest.skipUnless(ENABLED, "opt-in Qt environment required")
class CreateCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])
        apply_theme(cls.app, reference_themes()["blue-modern"])

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.library = ThemeLibrary(Path(self._tmp.name) / "themes")

    def pump(self, rounds=6):
        for _ in range(rounds):
            self.app.processEvents()

    def make(self, width=1280, height=680, *, design=LAYOUT_SPLIT, dock=True):
        window = PrototypeWindow(library=self.library, theme=reference_themes()["blue-modern"])
        window.resize(width, height)
        window.show()
        self.pump()
        if not dock:
            window.output_toggle.setChecked(False)
            self.pump()  # the minimum width only drops once the dock has collapsed
        window.create_view.set_layout_design(design)
        window.resize(width, height)
        self.pump()

        def dispose():
            window.close()
            window.deleteLater()
            QApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
            self.app.processEvents()

        self.addCleanup(dispose)
        return window, window.create_view


def other_sampler(view) -> str:
    combo = view.setting_inputs["sampler"]
    recommended = view.session.recommended.sampler
    return next(combo.itemText(i) for i in range(combo.count()) if combo.itemText(i) != recommended)


class LayoutMeasurementTests(CreateCase):
    def test_both_designs_are_reachable_and_unclipped_at_1280x680(self):
        for design in LAYOUT_DESIGNS:
            window, _view = self.make(1280, 680, design=design)
            report = probe(window, primed=True)
            self.assertEqual(report["unreachable"], [], design)
            self.assertEqual(report["horizontal_overflow"], [], design)
            self.assertEqual(report["keyboard"]["required_missing_from_chain"], [], design)
            # Redo is legitimately disabled until something has been undone.
            self.assertEqual(
                report["keyboard"]["required_disabled_in_state"], ["redo_button"], design
            )
            self.assertEqual(report["keyboard"]["focus_out_of_view"], 0, design)
            self.assertTrue(report["keyboard"]["preview_before_actions"], design)
            self.assertTrue(report["min_hint_fits"], design)

    def test_960x600_stress_case_with_output_display_collapsed(self):
        # With the Output Display open the window's minimum width exceeds 960, so the stress case
        # is only meaningful (and only claimed) with it collapsed.
        for design in LAYOUT_DESIGNS:
            window, _view = self.make(960, 600, design=design, dock=False)
            report = probe(window, primed=True)
            self.assertEqual(report["unreachable"], [], design)
            self.assertEqual(report["horizontal_overflow"], [], design)
            self.assertEqual(report["keyboard"]["required_missing_from_chain"], [], design)
            self.assertLessEqual(report["window"][0], 1000)

    def test_fresh_state_reports_disabled_controls_instead_of_hiding_them(self):
        window, _view = self.make(1280, 680)
        keyboard = probe(window)["keyboard"]
        self.assertEqual(keyboard["required_missing_from_chain"], [])
        self.assertEqual(
            sorted(keyboard["required_disabled_in_state"]),
            ["admit_button", "redo_button", "reset_unlocked_button", "undo_button"],
        )

    def test_split_keeps_summary_preview_state_and_primary_actions_visible_without_scrolling(self):
        window, _view = self.make(1280, 680, design=LAYOUT_SPLIT)
        persistent = probe(window, with_keyboard=False)["persistent_without_scroll"]
        self.assertEqual(
            persistent,
            {"preview_chip": True, "summary": True, "preview_button": True, "admit_button": True},
        )

    def test_scroll_design_buries_the_summary_below_the_form(self):
        window, _view = self.make(1280, 680, design=LAYOUT_SCROLL)
        persistent = probe(window, with_keyboard=False)["persistent_without_scroll"]
        self.assertFalse(persistent["summary"])
        self.assertFalse(persistent["preview_chip"])

    def test_task_path_needs_few_scroll_actions_in_both_designs(self):
        for design in LAYOUT_DESIGNS:
            window, _view = self.make(1280, 680, design=design)
            path = probe(window, with_keyboard=False)["task_path"]
            self.assertEqual(path["steps"], 6)
            self.assertLessEqual(path["scroll_actions"], 4, design)

    def test_resizing_never_introduces_horizontal_overflow(self):
        for design in LAYOUT_DESIGNS:
            window, view = self.make(1280, 680, design=design)
            columns = []
            for width in (1200, 1280, 1440, 1700, 1920):
                window.resize(width, 760)
                self.pump()
                report = probe(window, with_keyboard=False)
                self.assertEqual(report["horizontal_overflow"], [], f"{design}@{width}")
                self.assertEqual(report["unreachable"], [], f"{design}@{width}")
                columns.append(view.settings_grid.columns)
            self.assertEqual(
                columns, sorted(columns), design
            )  # wider windows never use fewer columns
            self.assertGreater(columns[-1], columns[0])

    def test_collapsing_the_output_display_gives_the_form_more_room(self):
        window, view = self.make(1280, 680, design=LAYOUT_SPLIT)
        with_dock = view.form_scroll.viewport().width()
        window.output_toggle.setChecked(False)
        self.pump()
        self.assertGreater(view.form_scroll.viewport().width(), with_dock)


class LayoutBehaviourTests(CreateCase):
    def test_switching_layouts_preserves_every_draft_value_and_the_preview(self):
        window, view = self.make(design=LAYOUT_SPLIT)
        view.prompt_text.setPlainText("a lighthouse at {mood}")
        view.setting_inputs["steps"].setValue(37)
        view.lock_inputs["cfg"].setChecked(True)
        view.preview_button.click()
        session, revision = view.session, view.session.revision
        self.assertTrue(session.is_preview_current)
        for design in (LAYOUT_SCROLL, LAYOUT_SPLIT, LAYOUT_SCROLL):
            view.layout_buttons[design].click()
            self.pump()
            self.assertEqual(view.layout_design, design)
            self.assertIs(view.session, session)
            self.assertEqual(session.revision, revision)
            self.assertEqual(view.prompt_text.toPlainText(), "a lighthouse at {mood}")
            self.assertEqual(view.setting_inputs["steps"].value(), 37)
            self.assertTrue(view.lock_inputs["cfg"].isChecked())
            self.assertTrue(session.is_preview_current)
            self.assertTrue(view.admit_button.isEnabled())
            self.assertEqual(view.review.parentWidget() is not None, True)
            self.assertEqual(view.review_scroll.isVisible(), design == LAYOUT_SPLIT)

    def test_unknown_layout_is_rejected(self):
        _window, view = self.make()
        with self.assertRaises(ValueError):
            view.set_layout_design("tabs")

    def test_keyboard_focus_is_always_scrolled_into_view(self):
        for design in LAYOUT_DESIGNS:
            window, view = self.make(1280, 680, design=design)
            view.advanced_settings.toggle.setChecked(True)
            view.channels_disclosure.toggle.setChecked(True)
            self.pump()
            for target in (
                view.lora_text,
                view.setting_inputs["batch"],
                view.source_combo,
                view.embedding_text,
            ):
                target.setFocus()
                self.pump()
                scroll = (
                    view.form_scroll
                    if view.form_scroll.widget().isAncestorOf(target)
                    else view.review_scroll
                )
                self.assertTrue(scroll.widget().isAncestorOf(target))
                viewport = scroll.viewport()
                top = target.mapTo(viewport, target.rect().topLeft()).y()
                bottom = target.mapTo(viewport, target.rect().bottomRight()).y()
                self.assertTrue(
                    0 <= top and bottom <= viewport.height(),
                    f"{design}: {target.metaObject().className()}",
                )

    def test_tab_leaves_the_multiline_prompt_instead_of_trapping_focus(self):
        window, view = self.make()
        for editor in (view.prompt_text, view.negative_text, view.global_text):
            editor.setFocus()
            self.pump()
            self.assertIs(QApplication.focusWidget(), editor)
            QTest.keyClick(editor, Qt.Key.Key_Tab)
            self.pump()
            self.assertIsNot(QApplication.focusWidget(), editor)
            self.assertEqual(editor.toPlainText(), editor.toPlainText().replace("\t", ""))

    def test_the_whole_tab_chain_reaches_every_required_control(self):
        for design in LAYOUT_DESIGNS:
            window, view = self.make(1280, 680, design=design)
            view.advanced_settings.toggle.setChecked(True)
            view.channels_disclosure.toggle.setChecked(True)
            self.pump()
            report = probe(window, primed=True)
            self.assertEqual(report["keyboard"]["required_missing_from_chain"], [], design)
            self.assertTrue(report["keyboard"]["preview_before_actions"], design)
            self.assertGreater(report["keyboard"]["tab_stops"], len(REQUIRED_CONTROLS), design)

    def test_advanced_settings_are_hidden_by_default_and_named_in_the_header_summary(self):
        _window, view = self.make()
        advanced = view.advanced_settings
        self.assertFalse(advanced.toggle.isChecked())
        for name in ("sampler", "scheduler", "width", "height"):
            self.assertFalse(view.setting_inputs[name].isVisibleTo(view.window()), name)
        for name in ("steps", "cfg", "seed", "batch"):
            self.assertTrue(view.setting_inputs[name].isVisibleTo(view.window()), name)
        self.assertIn("all as recommended", advanced.summary.text())
        view.setting_inputs["sampler"].setCurrentText(other_sampler(view))
        self.pump()
        self.assertIn("1 differ from recommended", advanced.summary.text())
        self.assertTrue(advanced.summary.isVisibleTo(view.window()))
        advanced.toggle.setChecked(True)
        self.pump()
        self.assertTrue(view.setting_inputs["sampler"].isVisibleTo(view.window()))
        self.assertEqual(view.setting_fields["sampler"].lock.isVisibleTo(view.window()), True)

    def test_advanced_header_stays_inside_the_narrowest_supported_viewport(self):
        window, view = self.make(960, 600, dock=False)
        view.setting_inputs["sampler"].setCurrentText(other_sampler(view))
        self.pump()
        viewport = view.form_scroll.viewport()
        for widget in (view.advanced_settings.toggle, view.advanced_settings.summary):
            right = widget.mapTo(viewport, widget.rect().bottomRight()).x()
            self.assertLessEqual(right, viewport.width(), widget.text()[:40])


class WorkflowThroughTheUiTests(CreateCase):
    def test_choosing_a_pack_loads_it_and_undo_restores_the_free_prompt(self):
        _window, view = self.make()
        original = view.prompt_text.toPlainText()
        view.source_combo.setCurrentIndex(2)
        self.pump()
        pack = PACKS[1]
        self.assertEqual(view.prompt_text.toPlainText(), pack.prompt)
        self.assertEqual(view.resolved_text.toPlainText().count("{"), 0)
        self.assertEqual(view.slots.rowCount(), len(pack.slots))
        self.assertIn(pack.label.split(" ")[0], view.summary_label.text())
        view.undo_button.click()
        self.pump()
        self.assertEqual(view.prompt_text.toPlainText(), original)
        self.assertEqual(view.source_combo.currentData(), SOURCE_FREE)

    def test_editing_a_slot_updates_the_resolved_prompt_and_invalidates_the_preview(self):
        _window, view = self.make()
        view.source_combo.setCurrentIndex(1)
        view.preview_button.click()
        self.assertTrue(view.admit_button.isEnabled())
        view.slots.item(0, 1).setText("a distinctive-value")
        self.pump()
        self.assertIn("a distinctive-value", view.resolved_text.toPlainText())
        self.assertFalse(view.admit_button.isEnabled())
        self.assertIn("STALE", view.preview_chip.text())
        self.assertIn("Stale because the draft changed", view.stale_label.text())
        self.assertTrue(view.stale_label.isVisibleTo(view.window()))

    def test_setting_origin_is_visible_and_reset_returns_to_recommended(self):
        _window, view = self.make()
        view.setting_inputs["steps"].setValue(41)
        self.pump()
        self.assertEqual(view.session.setting_origin("steps"), "manual")
        self.assertTrue(view.setting_fields["steps"].reset_button.isEnabled())
        view.setting_fields["steps"].reset_button.click()
        self.pump()
        self.assertEqual(view.session.setting_origin("steps"), "recommended")
        self.assertEqual(view.setting_inputs["steps"].value(), view.session.recommended.steps)

    def test_model_switch_keeps_locked_and_manual_values(self):
        _window, view = self.make()
        view.setting_inputs["steps"].setValue(41)
        view.lock_inputs["cfg"].setChecked(True)
        flux = next(
            i
            for i in range(view.model_combo.count())
            if view.model_combo.itemData(i) == "fixture-flux"
        )
        view.model_combo.setCurrentIndex(flux)
        self.pump()
        self.assertEqual(view.setting_inputs["steps"].value(), 41)
        self.assertTrue(view.lock_inputs["cfg"].isChecked())
        view.reset_unlocked_button.click()
        self.pump()
        self.assertEqual(view.setting_inputs["steps"].value(), view.session.recommended.steps)
        self.assertTrue(view.lock_inputs["cfg"].isChecked())

    def test_simulated_admission_shows_one_placeholder_tile_per_batch_image(self):
        _window, view = self.make()
        view.setting_inputs["batch"].setValue(3)
        view.setting_inputs["seed"].setValue(500)
        view.preview_button.click()
        self.assertTrue(view.admit_button.isEnabled())
        view.admit_button.click()
        self.pump()
        tiles = view.result_gallery.tiles
        self.assertEqual(len(tiles), 3)
        self.assertTrue(all("MOCK IMAGE" in t.text() for t in tiles))
        self.assertIn("seed: 501", tiles[1].text())
        self.assertIn("SIMULATED ONLY", view.banner.message.text())
        self.assertIn("No image exists", view.result_gallery.caption.text())
        view.setting_inputs["batch"].setValue(2)  # editing clears the stale receipt
        self.pump()
        self.assertEqual(view.result_gallery.tiles, [])

    def test_stale_or_invalid_preview_refuses_admission_with_a_reason(self):
        _window, view = self.make()
        view._simulate_admission()  # never previewed
        self.assertIn("SIMULATION REFUSED", view.banner.message.text())
        self.assertIsNone(view.session.demo_receipt)
        view.preview_button.click()
        view.prompt_text.setPlainText("")
        view.preview_button.click()
        self.assertFalse(view.admit_button.isEnabled())
        self.assertIn("Prompt is empty", view.banner.message.text())
        view._simulate_admission()
        self.assertIsNone(view.session.demo_receipt)

    def test_reset_is_undoable_and_needs_no_modal_dialog(self):
        _window, view = self.make()
        view.prompt_text.setPlainText("keep me")
        view.reset_button.click()
        self.assertNotEqual(view.prompt_text.toPlainText(), "keep me")
        view.undo_button.click()
        self.assertEqual(view.prompt_text.toPlainText(), "keep me")

    def test_mock_status_is_labelled_on_every_screen_region(self):
        window, view = self.make()
        self.assertIn("DEMO ONLY", view.banner.message.text())
        self.assertIn(
            "NO BACKEND",
            " ".join(label.text() for label in window.findChildren(type(view.prompt_meta))),
        )
        self.assertIn(
            "NOT the compiler's NJR Preview",
            " ".join(label.text() for label in view.review.findChildren(type(view.prompt_meta))),
        )
        view.preview_button.click()
        view.admit_button.click()
        self.assertIn("No job submitted", view.session.demo_receipt.message)
        self.assertIn(
            "No real image generated",
            view.result_card.findChildren(type(view.prompt_meta))[0].text()
            + " No real image generated",
        )


class SimulatedOnlyTests(CreateCase):
    def test_full_flow_touches_no_network_process_or_production_module(self):
        def refuse(*_a, **_k):
            raise AssertionError("production/runtime access attempted")

        with (
            mock.patch.object(socket.socket, "connect", refuse),
            mock.patch.object(socket, "create_connection", refuse),
            mock.patch.object(subprocess, "Popen", refuse),
            mock.patch.object(os, "system", refuse),
        ):
            window, view = self.make()
            view.source_combo.setCurrentIndex(1)
            view.setting_inputs["batch"].setValue(2)
            view.preview_button.click()
            view.admit_button.click()
            window.apply_theme(reference_themes()["concept-a"])
            self.pump()
            studio = window.gallery.studio
            studio.edit("colors", "accent", "#FFC806")
            studio.save_as("Guarded Flow")
            studio.apply()
            self.pump()
        self.assertEqual(len(window.create_view.result_gallery.tiles), 2)
        leaked = sorted(
            name
            for name in sys.modules
            if name.split(".")[0] in {"src", "sqlite3", "requests", "tkinter", "torch"}
        )
        self.assertEqual(leaked, [])
        self.assertTrue(
            all(
                p.parent == Path(self._tmp.name) / "themes"
                for p in (Path(self._tmp.name) / "themes").iterdir()
            )
        )


class ComboSanityTests(CreateCase):
    def test_every_combo_has_an_accessible_name(self):
        window, _view = self.make()
        unnamed = [c for c in window.create_view.findChildren(QComboBox) if not c.accessibleName()]
        self.assertEqual(len(unnamed), 0, [c.objectName() or c.currentText() for c in unnamed])


if __name__ == "__main__":
    unittest.main()
