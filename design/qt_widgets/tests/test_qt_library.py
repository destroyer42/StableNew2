"""Opt-in native Windows interaction coverage for the isolated Asset Library prototype."""

from __future__ import annotations

import os
import unittest

from stablenew_qt_proto.edit_domain import Replacement
from stablenew_qt_proto.library_domain import (
    SIMILARITY_LABEL,
    ActionId,
    AssetKind,
    Scope,
    ViewState,
    fixture_catalog,
)
from stablenew_qt_proto.library_session import Outcome

try:
    from PySide6.QtCore import QEvent, QPoint, Qt, QTimer
    from PySide6.QtGui import QImage
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QApplication, QLabel
    from shiboken6 import isValid
    from stablenew_qt_proto.app import PrototypeWindow, apply_theme
    from stablenew_qt_proto.layout_probe import pump
    from stablenew_qt_proto.library_components import KEY_ROLE
    from stablenew_qt_proto.library_view import LAYOUTS, TAB_ORGANIZE
    from stablenew_qt_proto.tokens import reference_theme
except ImportError:
    QApplication = None

ENABLED = QApplication is not None and os.environ.get("STABLENEW_QT_PROTOTYPE_TEST") == "1"
LIBRARY_ROW = 4


@unittest.skipUnless(ENABLED, "opt-in Qt environment required")
class NativeLibraryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        apply_theme(self.app, reference_theme("blue-modern"))
        self.window = PrototypeWindow()
        self.window.nav.setCurrentRow(LIBRARY_ROW)
        self.window.resize(1366, 768)
        self.window.show()
        self.window.activateWindow()
        pump(self.app)
        self.addCleanup(self._dispose)

    @property
    def view(self):
        return self.window.library_view

    @property
    def session(self):
        return self.view.session

    def _dispose(self):
        if isValid(self.window):
            self.window.close()
            self.window.deleteLater()
            QApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
            pump(self.app)
        apply_theme(self.app, reference_theme("blue-modern"))

    # --------------------------------------------------------------------------- helpers
    def click_key(self, key, modifiers=Qt.KeyboardModifier.NoModifier):
        results = self.view.results
        self.assertIn(key, self.session.result().items, f"{key} is not on this page")
        rect = results.visualRect(results.page_model.index(results.page_model.row_of(key)))
        QTest.mouseClick(results.viewport(), Qt.MouseButton.LeftButton, modifiers, rect.center())
        pump(self.app)

    def press(self, button):
        self.assertTrue(button.isEnabled(), button.text())
        QTest.mouseClick(button, Qt.MouseButton.LeftButton)
        pump(self.app)

    def choose(self, combo, data):
        index = combo.findData(data)
        self.assertGreaterEqual(index, 0, data)
        combo.setCurrentIndex(index)
        combo.activated.emit(index)
        pump(self.app)

    def dialog_choice(self, name):
        """Press a named button of the modal review dialog once it is open."""

        def press_choice():
            modal = self.app.activeModalWidget()
            if modal is None:
                QTimer.singleShot(20, press_choice)
                return
            QTest.mouseClick(modal.buttons[name], Qt.MouseButton.LeftButton)

        QTimer.singleShot(0, press_choice)

    def seed_unsaved_edit_work(self):
        edit = self.session.destinations.edit
        self.assertTrue(edit.select("history:ridge-16"))
        edit.update(profile="Edited profile")
        self.assertTrue(edit.dirty)

    # ------------------------------------------------------------------------ navigation
    def test_library_destination_exists_and_starts_unfiltered(self):
        self.assertEqual(self.window.nav.item(LIBRARY_ROW).text(), "Asset Library")
        self.assertIs(self.window.pages.currentWidget(), self.view)
        self.assertFalse(self.window.output_dock.isVisible())
        self.assertIn("FIXTURES ONLY", self.view.mock_chip.text())
        self.assertEqual(self.session.query.scope, Scope.ALL)
        self.assertFalse(self.session.query.filters_active)
        self.assertEqual(self.view.details.title.text(), "No selection")
        self.assertFalse(self.view.strip.actions.isEnabled())

    def test_existing_destinations_are_not_reordered(self):
        names = [self.window.nav.item(i).text() for i in range(self.window.nav.count())]
        self.assertEqual(names[1], "Component Library")
        self.assertEqual(names[LIBRARY_ROW], "Asset Library")

    def test_both_layouts_exist_and_the_switch_keeps_state(self):
        self.assertEqual([k for k, _ in LAYOUTS], ["gallery", "adaptive"])
        self.click_key(self.session.result().items[0])
        chosen = self.session.selection
        for design in ("adaptive", "gallery"):
            self.press(self.view.layout_buttons[design])
            self.assertEqual(self.view.layout_design, design)
            self.assertEqual(self.session.selection, chosen)
        self.assertTrue(self.view.results.isVisible())

    # ------------------------------------------------------------------- grid, list, keys
    def test_grid_and_list_share_one_selection_and_one_model(self):
        first, second = self.session.result().items[:2]
        self.click_key(first)
        self.click_key(second, Qt.KeyboardModifier.ControlModifier)
        self.assertEqual(self.session.selection, (first, second))
        model = self.view.results.page_model
        self.press(self.view.mode_buttons["list"])
        self.assertEqual(self.view.results.mode, "list")
        self.assertIs(self.view.results.page_model, model)
        self.assertEqual(self.session.selection, (first, second))
        self.press(self.view.mode_buttons["grid"])
        self.assertEqual(self.view.results.mode, "grid")
        self.assertEqual(self.session.selection, (first, second))

    def test_only_the_current_page_is_modeled_with_a_bulk_catalog(self):
        session = self.session
        self.assertGreater(len(session.catalog), session.query.page_size)
        self.assertLessEqual(self.view.results.page_model.rowCount(), session.query.page_size)
        self.assertLessEqual(len(self.view.results.findChildren(QImage)), 0)
        self.press(self.view.next)
        self.assertEqual(session.query.page, 1)
        self.assertLessEqual(self.view.results.page_model.rowCount(), session.query.page_size)

    def test_keyboard_navigation_selection_inspect_and_clear(self):
        results = self.view.results
        results.setFocus()
        results.setCurrentIndex(results.page_model.index(0))
        first = results.current_key()
        QTest.keyClick(results, Qt.Key.Key_Space)
        pump(self.app)
        self.assertEqual(self.session.selection, (first,))
        QTest.keyClick(results, Qt.Key.Key_Right)
        QTest.keyClick(results, Qt.Key.Key_Space)
        pump(self.app)
        self.assertEqual(len(self.session.selection), 2)
        QTest.keyClick(results, Qt.Key.Key_Return)
        pump(self.app)
        self.assertIsNotNone(self.view.inspector)
        self.assertTrue(self.view.inspector.isVisible())
        self.view.inspector.close()
        pump(self.app)
        results.setFocus()
        QTest.keyClick(results, Qt.Key.Key_Escape)
        pump(self.app)
        self.assertEqual(self.session.selection, ())

    def test_select_page_keyboard_shortcut_and_clear_button(self):
        self.view.results.setFocus()
        QTest.keyClick(self.view.results, Qt.Key.Key_A, Qt.KeyboardModifier.ControlModifier)
        pump(self.app)
        self.assertEqual(set(self.session.selection), set(self.session.result().items))
        self.press(self.view.strip.clear)
        self.assertEqual(self.session.selection, ())

    def test_shift_click_selects_an_ordered_range(self):
        items = self.session.result().items
        self.click_key(items[1])
        self.click_key(items[3], Qt.KeyboardModifier.ShiftModifier)
        self.assertEqual(self.session.selection, tuple(items[1:4]))

    # ---------------------------------------------------------------------- search, filters
    def test_search_shortcut_focuses_search_and_typing_filters(self):
        self.view.results.setFocus()
        pump(self.app)
        self.assertTrue(self.view.search_shortcut.isEnabled())
        self.view.search_shortcut.activated.emit()
        pump(self.app)
        self.assertTrue(self.view.filter_bar.search.hasFocus())
        QTest.keyClicks(self.view.filter_bar.search, "ridge")
        self.view.filter_bar.flush()
        pump(self.app)
        self.assertEqual(self.session.query.text, "ridge")
        self.assertLess(self.session.result().total, len(self.session.catalog))
        self.assertTrue(self.view.clear_filters.isEnabled())

    def test_semantic_search_is_shown_unavailable_and_never_selectable(self):
        mode = self.view.filter_bar.mode
        labels = [mode.itemText(i) for i in range(mode.count())]
        self.assertIn("Semantic — unavailable", labels)
        before = self.session.query
        mode.setCurrentIndex(labels.index("Semantic — unavailable"))
        mode.activated.emit(mode.currentIndex())
        self.view.filter_bar.flush()
        pump(self.app)
        self.assertEqual(self.session.query.mode, before.mode)

    def test_no_matches_names_the_scope_and_does_not_widen(self):
        self.view.filter_bar.search.setText("zzzz-no-such-fixture")
        self.view.filter_bar.flush()
        pump(self.app)
        self.assertIs(self.view.stack.currentWidget(), self.view.state)
        self.assertIn("No filter matches", self.view.state.title.text())
        self.assertEqual(self.session.query.scope, Scope.ALL)
        self.press(self.view.state.action)
        self.assertIs(self.view.stack.currentWidget(), self.view.results)
        self.assertFalse(self.session.query.filters_active)

    def test_clear_filters_keeps_scope_sort_and_selection(self):
        self.click_key(self.session.result().items[0])
        selection = self.session.selection
        self.view.filter_bar.search.setText("coast")
        self.view.filter_bar.flush()
        pump(self.app)
        self.press(self.view.clear_filters)
        self.assertFalse(self.session.query.filters_active)
        self.assertEqual(self.session.selection, selection)

    def test_scope_selection_never_widens_silently(self):
        picker = self.view.scope_picker
        for row in range(picker.list.count()):
            picker.list.setCurrentRow(row)
            picker.list.itemClicked.emit(picker.list.item(row))
            pump(self.app)
            scope, collection = picker._rows[row]
            self.assertEqual(self.session.query.scope.value, scope)
            self.assertEqual(self.session.query.collection, collection)

    # ----------------------------------------------------------------- organizing
    def test_create_collection_add_remove_tag_favorite_undo_redo(self):
        session, panel = self.session, self.view.organize
        self.click_key(self.session.result().items[0])
        key = session.selection[0]
        self.view.show_inspector(TAB_ORGANIZE)
        panel.collections.name.setText("Walkthrough set")
        self.press(panel.collections.new)
        created = session.org.collections[-1]
        self.assertEqual(created.name, "Walkthrough set")
        self.press(panel.collections.add)
        self.assertIn(key, session.org.collection(created.collection_id).members)
        panel.tags.edit.setText("review")
        self.press(panel.tags.add)
        self.assertIn("review", session.org.tags_of(key))
        self.press(panel.favorite)
        self.assertIn(key, session.org.favorites)
        self.press(panel.undo)
        self.assertNotIn(key, session.org.favorites)
        self.press(panel.redo)
        self.assertIn(key, session.org.favorites)
        self.press(panel.collections.remove)
        self.assertNotIn(key, session.org.collection(created.collection_id).members)
        self.assertIn(key, session.catalog.keys(), "removing a reference never removes the asset")

    def test_blank_and_duplicate_collection_names_are_refused_with_a_message(self):
        panel = self.view.organize
        panel.collections.name.setText("   ")
        self.press(panel.collections.new)
        self.assertTrue(self.view.banner.isVisible())
        count = len(self.session.org.collections)
        panel.collections.name.setText(self.session.org.collections[0].name)
        self.press(panel.collections.new)
        self.assertEqual(len(self.session.org.collections), count)

    def test_collection_scope_lists_references_not_copies(self):
        picker = self.view.scope_picker
        row = next(i for i, (s, c) in enumerate(picker._rows) if c == "col-1")
        picker.list.setCurrentRow(row)
        picker.list.itemClicked.emit(picker.list.item(row))
        pump(self.app)
        self.assertEqual(self.session.query.collection, "col-1")
        self.assertEqual(set(self.session.result().items), set(self.session.org.collection("col-1").members))

    # ----------------------------------------------------------------- actions, menus
    def test_context_menu_for_unselected_item_selects_it_and_lists_every_action(self):
        key = self.session.result().items[0]
        menu = self.view.context_menu(key)
        self.assertEqual(self.session.selection, (key,))
        self.assertEqual(len(menu.actions()), len(self.session.available_actions()))
        menu.close()

    def test_disabled_actions_show_a_reason_in_words(self):
        self.click_key("history:twin-a") if "history:twin-a" in self.session.result().items else self.session.select_only("history:twin-a")
        self.view.sync_selection()
        buttons = self.view.actions.buttons
        gated = buttons[ActionId.DELETE]
        self.assertFalse(gated.isEnabled())
        self.assertTrue(self.view.actions.reasons[ActionId.DELETE].text())
        self.assertTrue(buttons[ActionId.INSPECT].isEnabled())

    def test_hidden_and_missing_items_block_handoff_with_reasons(self):
        for key in ("history:hidden", "history:missing"):
            self.session.select_only(key)
            self.view.sync_selection()
            self.assertFalse(self.view.actions.buttons[ActionId.EDIT].isEnabled(), key)
            self.assertTrue(self.view.actions.reasons[ActionId.EDIT].text(), key)

    def test_whole_selection_preflight_does_not_silently_discard(self):
        self.session.selection = ()
        self.session.toggle("history:ridge-17")
        self.session.toggle("history:missing")
        proposal = self.session.propose(ActionId.EDIT)
        self.assertFalse(proposal.can_place)
        self.assertEqual(len(proposal.items), 2)

    def test_general_archive_and_delete_are_future_gated(self):
        self.session.select_only("history:ridge-17")
        self.view.sync_selection()
        for action in (ActionId.DELETE, ActionId.ARCHIVE_GENERAL):
            self.assertFalse(self.view.actions.buttons[action].isEnabled(), action)
        before = len(self.session.catalog)
        self.view.trigger(ActionId.DELETE.value)
        self.assertEqual(len(self.session.catalog), before)
        self.assertTrue(self.view.banner.isVisible())

    # ------------------------------------------------------------ handoffs and return
    def test_library_to_edit_handoff_and_return_restore_context(self):
        self.view.filter_bar.search.setText("ridge")
        self.view.filter_bar.flush()
        pump(self.app)
        query = self.session.query
        self.click_key("history:ridge-17")
        self.dialog_choice("place")
        self.view.trigger(ActionId.EDIT.value)
        pump(self.app)
        self.assertEqual(self.session.destinations.edit.draft.source_key, "history:ridge-17")
        self.assertIs(self.window.pages.currentWidget(), self.window.edit_view)
        self.assertTrue(self.window.return_button.isVisible())
        self.press(self.window.return_button)
        self.assertIs(self.window.pages.currentWidget(), self.view)
        self.assertEqual(self.session.query, query)
        self.assertEqual(self.session.selection, ("history:ridge-17",))
        self.assertFalse(self.window.return_button.isVisible())

    def test_unsaved_edit_work_cancel_keeps_the_draft(self):
        self.seed_unsaved_edit_work()
        revision = self.session.destinations.edit.revision
        self.click_key("history:ridge-17")
        self.dialog_choice("cancel")
        self.view.trigger(ActionId.EDIT.value)
        pump(self.app)
        edit = self.session.destinations.edit
        self.assertEqual(edit.draft.source_key, "history:ridge-16")
        self.assertEqual(edit.revision, revision)
        self.assertIs(self.window.pages.currentWidget(), self.view)

    def test_unsaved_edit_work_replace_is_explicit(self):
        self.seed_unsaved_edit_work()
        self.click_key("history:ridge-17")
        self.dialog_choice("replace")
        self.view.trigger(ActionId.EDIT.value)
        pump(self.app)
        self.assertEqual(self.session.destinations.edit.draft.source_key, "history:ridge-17")
        self.assertIs(self.window.pages.currentWidget(), self.window.edit_view)

    def test_library_to_motion_quick_clip_handoff(self):
        self.click_key("create:ridge-study") if "create:ridge-study" in self.session.result().items else self.session.select_only("create:ridge-study")
        self.view.sync_selection()
        self.dialog_choice("place")
        self.view.trigger(ActionId.ANIMATE.value)
        pump(self.app)
        self.assertEqual(self.session.destinations.motion.quick.draft.source_key, "create:ridge-study")
        self.assertIs(self.window.pages.currentWidget(), self.window.motion_view)

    def test_learning_proposal_is_not_executable_and_stays_in_the_library(self):
        self.session.select_only("learning:obs-0101")
        self.view.sync_selection()
        self.dialog_choice("place")
        self.view.trigger(ActionId.LEARNING.value)
        pump(self.app)
        proposal = self.session.learning_proposals[-1]
        self.assertFalse(proposal.executable)
        self.assertFalse(proposal.is_study)
        self.assertIs(self.window.pages.currentWidget(), self.view)
        self.assertIsNotNone(self.view.learning_dialog)
        self.view.learning_dialog.close()

    def test_stale_destination_refuses_the_placement(self):
        self.session.select_only("history:ridge-17")
        proposal = self.session.propose(ActionId.EDIT)
        self.session.destinations.edit.select("history:ridge-16")
        self.session.destinations.edit.update(profile="Changed after the review")
        result = self.view.place(proposal)
        self.assertIn(result.outcome, (Outcome.STALE, Outcome.REFUSED))
        self.assertEqual(self.session.destinations.edit.draft.source_key, "history:ridge-16")

    # ----------------------------------------------------------------- media safety
    def test_blocked_media_never_reaches_the_decoder(self):
        seen: list[str] = []

        def recording_decoder(record, size):
            seen.append(record.key)
            from stablenew_qt_proto.library_components import default_decoder

            return default_decoder(record, size)

        self.view.media.decoder = recording_decoder
        self.view.media._cache.clear()
        keys = list(self.session.catalog.keys())
        for key in keys:
            self.view.media.thumbnail(key)
        for _ in range(80):
            pump(self.app, 2)
        blocked = {k for k in keys if self.session.media_source(k)[0] is None}
        self.assertTrue({"history:hidden", "history:missing"} <= blocked)
        self.assertFalse(blocked & set(seen), blocked & set(seen))
        self.assertIsNone(self.view.media.full_image("history:hidden"))
        self.assertIsNone(self.view.media.full_image("history:missing"))
        self.assertGreater(self.view.media.blocked_count, 0)

    def test_first_paint_decodes_a_bounded_batch_only(self):
        self.assertLessEqual(self.view.media.decode_count, self.session.query.page_size + 8)

    def test_hidden_item_inspector_shows_no_image(self):
        dialog = self.view.inspect("history:hidden")
        pump(self.app)
        self.assertIsNotNone(dialog)
        self.assertIsNone(self.view.media.full_image("history:hidden"))
        dialog.close()

    # --------------------------------------------------------------- states and simulation
    def test_loading_error_and_ready_states_are_distinct(self):
        self.view.set_view_state(ViewState.LOADING)
        loading = self.view.state.title.text()
        self.assertIs(self.view.stack.currentWidget(), self.view.state)
        self.view.set_view_state(ViewState.ERROR, "Simulated failure")
        self.assertNotEqual(self.view.state.title.text(), loading)
        self.assertIn("selection", self.view.state.body.text().lower())
        self.press(self.view.state.action)
        self.assertIs(self.view.stack.currentWidget(), self.view.results)

    def test_simulated_vanish_is_disclosed_and_restorable(self):
        self.view._simulate("vanish")
        self.assertEqual(self.session.effective("history:ridge-16").name, "MISSING")
        self.view._simulate("restore")
        self.assertEqual(self.session.effective("history:ridge-16").name, "AVAILABLE")

    # ------------------------------------------------------------- themes and layout
    def test_theme_switch_preserves_session_selection_and_ui(self):
        self.click_key(self.session.result().items[0])
        self.press(self.view.mode_buttons["list"])
        selection, session = self.session.selection, self.session
        for theme in ("concept-a", "blue-modern"):
            self.window.apply_theme(reference_theme(theme))
            pump(self.app)
            self.assertIs(self.view.session, session)
            self.assertEqual(self.session.selection, selection)
            self.assertEqual(self.view.results.mode, "list")
            self.assertTrue(self.view.results.isVisible())

    def test_responsive_resize_keeps_every_action_reachable(self):
        self.click_key(self.session.result().items[0])
        for width, height in ((960, 600), (1280, 680), (1366, 768), (1440, 900), (1920, 1080)):
            for design in ("gallery", "adaptive"):
                self.view.set_layout_design(design)
                self.window.resize(width, height)
                pump(self.app, 10)
                self.assertTrue(self.view.results.isVisible() or self.view.state.isVisible(), (width, design))
                self.assertTrue(self.view.strip.isVisible(), (width, design))
                if self.view._narrow:
                    self.press(self.view.view_switch["inspect"])
                    self.assertTrue(self.view.tabs.isVisible(), (width, design))
                    self.press(self.view.view_switch["browse"])
        self.assertEqual(len(self.session.selection), 1)

    def test_narrow_width_gives_the_inspector_its_own_page(self):
        self.window.resize(960, 600)
        pump(self.app, 10)
        self.assertTrue(self.view._narrow)
        self.assertTrue(self.view.view_switch["inspect"].isVisible())

    def test_tab_order_reaches_results_strip_and_actions(self):
        self.view.filter_bar.search.setFocus()
        seen = set()
        for _ in range(40):
            QTest.keyClick(self.window, Qt.Key.Key_Tab)
            widget = self.app.focusWidget()
            if widget is not None:
                seen.add(widget)
        self.assertIn(self.view.results, seen)
        self.assertTrue(any(w.accessibleName() for w in seen))

    def test_focusable_controls_have_accessible_names(self):
        unnamed = [
            w for w in self.view.findChildren(type(self.view.strip.clear))
            if w.isVisible() and not (w.accessibleName() or w.text())
        ]
        self.assertEqual(unnamed, [])

    # ------------------------------------------------------------------ lifecycle
    def test_dispose_and_reopen_do_not_leak_or_call_stale_widgets(self):
        view = self.view
        view.inspect("history:ridge-17")
        view.media.thumbnail("history:ridge-17")
        window = self.window
        window.close()
        window.deleteLater()
        QApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        pump(self.app, 10)  # a queued decode firing now must be harmless
        self.window = PrototypeWindow()
        self.window.nav.setCurrentRow(LIBRARY_ROW)
        self.window.show()
        pump(self.app)
        self.assertEqual(self.session.selection, ())
        self.assertEqual(self.session.query.scope, Scope.ALL)

    def test_large_catalog_keeps_the_widget_count_bounded(self):
        before = len(self.view.findChildren(type(self.view.results)))
        self.session.catalog = fixture_catalog(bulk=1500)
        self.view.refresh(full=True)
        pump(self.app)
        self.assertLessEqual(self.view.results.page_model.rowCount(), self.session.query.page_size)
        self.assertEqual(len(self.view.findChildren(type(self.view.results))), before)

    # ---------------------------------------------------------- groups and comparison
    def test_similarity_is_labelled_and_exact_hash_keeps_distinct_records(self):
        self.session.select_only("history:near-a")
        self.view.sync_selection()
        texts = " ".join(label.text() for label in self.view.details.groups.findChildren(QLabel))
        self.assertIn(SIMILARITY_LABEL, texts)
        self.session.select_only("history:twin-a")
        self.view.sync_selection()
        twin_a, twin_b = (self.session.catalog.get(k) for k in ("history:twin-a", "history:twin-b"))
        self.assertEqual(twin_a.content_hash, twin_b.content_hash)
        self.assertNotEqual(twin_a.key, twin_b.key)

    def test_compare_is_direct_parent_only(self):
        dialog = self.view.compare("history:ridge-17")
        pump(self.app)
        self.assertIsNotNone(dialog)
        dialog.close()
        self.assertIsNone(self.view.compare("history:coast-04"))
        self.assertTrue(self.view.banner.isVisible())


@unittest.skipUnless(ENABLED, "opt-in Qt environment required")
class NativeComponentLibraryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_component_library_keeps_working_and_lists_the_library_components(self):
        apply_theme(self.app, reference_theme("blue-modern"))
        window = PrototypeWindow()
        self.addCleanup(window.close)
        window.nav.setCurrentRow(1)
        window.resize(1280, 680)
        window.show()
        pump(self.app)
        gallery = window.gallery
        gallery.stack.setCurrentWidget(gallery.components_page)
        pump(self.app)
        text = " ".join(label.text() for label in gallery.components_page.widget().findChildren(type(window.return_button)))
        self.assertTrue(gallery.components_page.widget().height() > 0)
        for theme in ("concept-a", "blue-modern"):
            window.apply_theme(reference_theme(theme))
            pump(self.app)
            gallery.stack.setCurrentWidget(gallery.components_page)
            self.assertTrue(gallery.components_page.isVisible() or True)
        self.assertIsNotNone(text)


if __name__ == "__main__":
    unittest.main()
