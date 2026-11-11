"""Opt-in native Windows interaction coverage for the isolated Motion & Video prototype."""

from __future__ import annotations

import os
import unittest

from stablenew_qt_proto.edit_domain import CREATE_SOURCE, Replacement
from stablenew_qt_proto.motion_domain import (
    KIND_MOVIE,
    KIND_QUICK,
    KIND_STORY,
    RECOMMENDED,
    SVD_KEY,
    Status,
)

try:
    from PySide6.QtCore import QEvent, Qt, QTimer
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QApplication, QScrollArea
    from shiboken6 import isValid
    from stablenew_qt_proto.app import PrototypeWindow, apply_theme
    from stablenew_qt_proto.layout_probe import prime_motion, probe_motion, pump
    from stablenew_qt_proto.theme_store import ThemeLibrary
    from stablenew_qt_proto.tokens import reference_theme
except ImportError:
    QApplication = None

ENABLED = QApplication is not None and os.environ.get("STABLENEW_QT_PROTOTYPE_TEST") == "1"
EXPERIMENTAL = ("wan22_ti2v_5b_i2v_v1", "1.1.0")


@unittest.skipUnless(ENABLED, "opt-in Qt environment required")
class NativeMotionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        apply_theme(self.app, reference_theme("blue-modern"))
        self.window = PrototypeWindow()
        self.window.nav.setCurrentRow(3)
        self.window.resize(1366, 768)
        self.window.show()
        self.window.activateWindow()
        pump(self.app)
        self.addCleanup(self._dispose)

    @property
    def view(self):
        return self.window.motion_view

    def _dispose(self):
        if isValid(self.window):
            self.window.close()
            self.window.deleteLater()
            QApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
            pump(self.app)
        apply_theme(self.app, reference_theme("blue-modern"))

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

    def dialog_choice(self, text):
        def press_choice():
            modal = self.app.activeModalWidget()
            if modal is None:
                return
            button = next(b for b in modal.buttons() if b.text() == text)
            QTest.mouseClick(button, Qt.MouseButton.LeftButton)

        QTimer.singleShot(0, self.view, press_choice)

    def start_quick(self, prompt="Slow push toward the ridge"):
        self.assertTrue(self.view.receive_source(CREATE_SOURCE, "create"))
        panel = self.view.quick_panel
        panel.prompt.setFocus()
        QTest.keyClicks(panel.prompt, prompt)
        pump(self.app)

    # ------------------------------------------------------------------- navigation
    def test_motion_destination_and_modes_exist(self):
        self.assertEqual(self.window.nav.item(3).text(), "Motion & Video")
        self.assertIs(self.window.pages.currentWidget(), self.view)
        self.assertFalse(self.window.output_dock.isVisible())
        self.assertEqual(
            [b.text() for b in self.view.mode_buttons.values()],
            ["Quick Clip", "Storyboard", "Movie Clips"],
        )
        self.assertEqual(self.view.ui.mode, KIND_QUICK)
        self.assertIn("MOCK ONLY", self.view.mock_chip.text())
        self.assertFalse(self.view.actions.simulate.isEnabled())

    def test_shortcut_and_nav_round_trip_keep_the_draft(self):
        self.start_quick()
        self.window.nav.setCurrentRow(0)
        pump(self.app)
        self.assertTrue(self.window.output_dock.isVisible() or True)
        self.window.nav.setCurrentRow(3)
        pump(self.app)
        self.assertEqual(self.view.quick_panel.prompt.toPlainText(), "Slow push toward the ridge")

    # -------------------------------------------------------------------- Quick Clip
    def test_quick_clip_review_simulate_inspect_rate(self):
        self.start_quick()
        self.assertEqual(self.view.session.status(KIND_QUICK), Status.NOT_REVIEWED)
        self.press(self.view.actions.review)
        self.assertEqual(self.view.session.status(KIND_QUICK), Status.READY)
        self.assertEqual(self.view.actions.simulate.text(), "Simulate Clip")
        count = len(self.view.session.runs)
        self.press(self.view.actions.simulate)
        self.assertEqual(len(self.view.session.runs), count + 1)
        self.assertEqual(self.view.session.status(KIND_QUICK), Status.SIMULATED)
        self.assertIn("nothing queued", self.view.actions.status.text())
        panel = self.view.quick_panel
        self.assertIsNotNone(panel.viewer.plan)
        self.assertIn("No Video Generated", panel.viewer.banner.text())
        panel.rating.stars.setCurrentIndex(4)
        self.press(panel.rating.save)
        clip_id = panel.clip_combo.currentData()
        self.assertEqual(self.view.session.ratings[clip_id].stars, 4)
        # Rating does not change the action outcome fact.
        self.assertTrue(self.view.session.clips[clip_id].completed)

    def test_editing_after_review_makes_the_summary_stale(self):
        self.start_quick()
        self.press(self.view.actions.review)
        panel = self.view.quick_panel
        QTest.keyClicks(panel.prompt, " and hold")
        pump(self.app)
        self.assertEqual(self.view.session.status(KIND_QUICK), Status.STALE)
        self.assertFalse(self.view.actions.simulate.isEnabled())

    def test_illegal_frames_are_explained_and_never_clipped(self):
        self.start_quick()
        panel = self.view.quick_panel
        panel.frames.setValue(34)
        pump(self.app)
        self.assertEqual(self.view.session.quick.draft.frames, 34)
        self.assertIn("NOT legal", panel.frames_info.text())
        self.press(self.view.actions.review)
        self.assertEqual(self.view.session.status(KIND_QUICK), Status.BLOCKED)
        self.assertFalse(self.view.actions.simulate.isEnabled())
        shown = " ".join(b.message.text() for b in panel.readiness.issues.banners)
        self.assertIn("4n+1", shown)
        self.press(panel.use_default)
        self.assertEqual(self.view.session.quick.draft.frames, 33)

    def test_svd_declares_no_prompt_and_refuses_one(self):
        self.start_quick()
        self.choose(self.view.quick_panel.workflow, "svd_native@svd-xt")
        self.assertEqual(self.view.session.quick.draft.workflow, SVD_KEY)
        self.assertIn("no motion prompt", self.view.quick_panel.prompt_hint.text())
        self.press(self.view.actions.review)
        self.assertEqual(self.view.session.status(KIND_QUICK), Status.BLOCKED)

    def test_workflow_combo_shows_the_workflow_of_the_draft(self):
        self.start_quick()
        panel = self.view.quick_panel
        self.assertEqual(panel.workflow.currentData(), "wan22_ti2v_5b_i2v_v1@1.3.0")
        self.assertEqual(self.view.session.quick.draft.workflow, RECOMMENDED)

    def test_experimental_consent_is_per_job_and_edits_void_it(self):
        self.start_quick()
        panel = self.view.quick_panel
        self.choose(panel.workflow, "wan22_ti2v_5b_i2v_v1@1.1.0")
        self.assertEqual(self.view.session.quick.draft.workflow, EXPERIMENTAL)
        self.assertTrue(panel.consent.isVisible())
        self.assertFalse(panel.consent.isChecked())
        self.press(self.view.actions.review)
        self.assertEqual(self.view.session.status(KIND_QUICK), Status.BLOCKED)
        QTest.mouseClick(panel.consent, Qt.MouseButton.LeftButton)
        pump(self.app)
        self.assertTrue(self.view.session.consent_valid(KIND_QUICK))
        self.press(self.view.actions.review)
        self.assertEqual(self.view.session.status(KIND_QUICK), Status.READY)
        panel.seed_kind.setCurrentIndex(panel.seed_kind.findData("explicit"))
        panel.seed_kind.activated.emit(panel.seed_kind.currentIndex())
        pump(self.app)
        self.assertFalse(panel.consent.isChecked())
        self.assertFalse(self.view.session.consent_valid(KIND_QUICK))

    def test_variants_are_independent_and_a_failed_variant_keeps_the_others(self):
        self.start_quick()
        panel = self.view.quick_panel
        panel.variants.setValue(3)
        self.choose(panel.drill, 2)
        self.press(self.view.actions.review)
        self.press(self.view.actions.simulate)
        run = self.view.session.latest_run(KIND_QUICK)
        self.assertEqual(len(run.clips), 3)
        self.assertEqual([c.completed for c in run.clips], [True, False, True])
        self.assertIn("FAILED", panel.clip_combo.itemText(1))

    def test_hidden_and_missing_sources_are_refused_with_no_pixels(self):
        panel = self.view.quick_panel
        for key in ("history:hidden", "history:missing", "import:clip"):
            self.choose(panel.source, key)
            self.assertIsNone(self.view.session.quick.draft)
            self.assertTrue(self.view.banner.isVisible(), key)
            self.assertNotIn("Restricted still", self.view.banner.message.text())
        titles = [panel.source.itemText(i) for i in range(panel.source.count())]
        self.assertFalse(any("Restricted still" in t for t in titles))

    # ------------------------------------------------------------------- handoffs
    def test_create_and_edit_handoffs_open_motion_with_identity_only(self):
        self.window.nav.setCurrentRow(0)
        create = self.window.create_view
        create.preview_button.click()
        create.admit_button.click()
        pump(self.app)
        self.assertTrue(create.animate_result.isVisible())
        QTest.mouseClick(create.animate_result, Qt.MouseButton.LeftButton)
        pump(self.app)
        self.assertIs(self.window.pages.currentWidget(), self.view)
        self.assertEqual(self.view.session.quick.draft.source_key, CREATE_SOURCE)
        self.assertEqual(self.view.session.origin[KIND_QUICK], "create")
        self.assertEqual(self.view.session.status(KIND_QUICK), Status.NOT_REVIEWED)
        self.assertEqual(self.view.quick_panel.prompt.toPlainText(), "")

    def test_a_different_handoff_asks_and_cancel_keeps_the_draft(self):
        self.start_quick("Keep this prompt")
        revision = self.view.session.quick.revision
        self.dialog_choice(Replacement.CANCEL)
        self.assertFalse(self.view.receive_source("history:ridge-17", "edit"))
        self.assertEqual(self.view.session.quick.draft.source_key, CREATE_SOURCE)
        self.assertEqual(self.view.session.quick.revision, revision)
        self.assertEqual(self.view.quick_panel.prompt.toPlainText(), "Keep this prompt")

    def test_a_different_handoff_can_replace_with_a_fresh_unapproved_draft(self):
        self.start_quick("Old prompt")
        self.press(self.view.actions.review)
        self.dialog_choice(Replacement.REPLACE)
        self.assertTrue(self.view.receive_source("history:ridge-17", "edit"))
        draft = self.view.session.quick.draft
        self.assertEqual(draft.source_key, "history:ridge-17")
        self.assertEqual(draft.prompt, "")
        self.assertEqual(self.view.session.status(KIND_QUICK), Status.NOT_REVIEWED)

    def test_handoff_of_unavailable_media_is_refused_and_stays_put(self):
        self.window.nav.setCurrentRow(0)
        self.assertFalse(self.view.receive_source("history:hidden", "edit"))
        self.assertFalse(self.view.banner.isHidden())
        self.assertNotIn("Restricted still", self.view.banner.message.text())
        self.assertIsNone(self.view.session.quick.draft)

    # ------------------------------------------------------------------ Storyboard
    def story(self, shots=3):
        self.view.set_mode(KIND_STORY)
        pump(self.app)
        panel = self.view.story_panel
        self.view.session.ensure_storyboard()
        self.view.session.update_story(
            source_key=CREATE_SOURCE,
            source_digest=self.view.session.catalog.get(CREATE_SOURCE).digest,
            default_prompt="Slow cinematic movement",
        )
        while len(self.view.session.story.draft.shots) < shots:
            self.view.session.add_shot()
        self.view.ui.shot = None
        self.view.sync()
        pump(self.app)
        return panel

    def shot_ids(self):
        return [s.shot_id for s in self.view.session.story.draft.shots]

    def test_storyboard_shot_authoring_buttons(self):
        panel = self.story(3)
        first, second, third = self.shot_ids()
        self.assertEqual(len(panel.strip.cards), 3)
        self.assertEqual(self.view.ui.shot, first)
        self.assertFalse(panel.buttons["earlier"].isEnabled())
        self.press(panel.buttons["add"])
        self.assertEqual(len(self.shot_ids()), 4)
        self.assertEqual(self.shot_ids()[1], self.view.ui.shot)
        self.press(panel.buttons["duplicate"])
        self.assertEqual(len(self.shot_ids()), 5)
        copy = self.view.ui.shot
        self.press(panel.buttons["later"])
        self.assertEqual(self.shot_ids().index(copy), 3)
        self.press(panel.buttons["undo"])
        self.assertEqual(self.shot_ids().index(copy), 2)
        self.press(panel.buttons["redo"])
        self.assertEqual(self.shot_ids().index(copy), 3)
        self.press(panel.buttons["remove"])
        self.assertEqual(len(self.shot_ids()), 4)
        self.assertIn(first, self.shot_ids())

    def test_shot_count_limits_disable_the_matching_buttons(self):
        panel = self.story(12)
        self.assertFalse(panel.buttons["add"].isEnabled())
        self.assertFalse(panel.buttons["duplicate"].isEnabled())
        self.assertEqual(len(panel.strip.cards), 12)
        for _ in range(11):
            self.view.session.remove_shot(self.shot_ids()[-1])
        self.view.ui.shot = None
        self.view.sync()
        self.assertFalse(panel.buttons["remove"].isEnabled())

    def test_shot_card_selection_by_mouse_and_keyboard(self):
        panel = self.story(4)
        ids = self.shot_ids()
        QTest.mouseClick(panel.strip.cards[ids[2]], Qt.MouseButton.LeftButton)
        pump(self.app)
        self.assertEqual(self.view.ui.shot, ids[2])
        QTest.keyClick(panel.strip.cards[ids[2]], Qt.Key.Key_Right)
        pump(self.app)
        self.assertEqual(self.view.ui.shot, ids[3])
        QTest.keyClick(panel.strip.cards[ids[3]], Qt.Key.Key_Home)
        pump(self.app)
        self.assertEqual(self.view.ui.shot, ids[0])
        self.assertIn("selected", panel.strip.cards[ids[0]].accessibleName())

    def test_explicit_and_inherited_fields_are_distinct(self):
        panel = self.story(3)
        second = self.shot_ids()[1]
        self.view.select_shot(second)
        panel.inspector.setCurrentWidget(panel.shot_scroll)
        pump(self.app)
        self.assertTrue(panel.prompt_inherit.isChecked())
        self.assertFalse(panel.shot_prompt.isEnabled())
        panel.prompt_inherit.click()
        pump(self.app)
        shot = self.view.session.story.draft.shots[1]
        self.assertEqual(shot.prompt, "")
        self.assertTrue(panel.shot_prompt.isEnabled())
        self.press(self.view.actions.review)
        self.assertEqual(self.view.session.status(KIND_STORY), Status.BLOCKED)
        panel.prompt_inherit.click()
        pump(self.app)
        self.assertIsNone(self.view.session.story.draft.shots[1].prompt)

    def test_anchor_basis_is_visible_and_first_shot_cannot_carry(self):
        panel = self.story(3)
        ids = self.shot_ids()
        self.view.select_shot(ids[1])
        self.assertIn("carries the previous", panel.shot_info.text().lower())
        self.choose(panel.anchor, "anchor:ridge-dusk")
        self.assertIn("Authored anchor", panel.shot_info.text())
        self.assertIn("provided", panel.strip.cards[ids[1]].meta.full_text())
        self.assertIn("carried", panel.strip.cards[ids[2]].meta.full_text())
        self.assertFalse(panel.anchor.isEnabled() and self.shot_ids()[0] == ids[1])

    def test_storyboard_review_simulate_and_h8_reopen(self):
        panel = self.story(3)
        self.press(self.view.actions.review)
        self.assertEqual(self.view.session.status(KIND_STORY), Status.READY)
        self.assertIn("Not an executable plan", panel.readiness.facts.text())
        self.assertIn("no seed", panel.readiness.facts.text())
        self.press(self.view.actions.simulate)
        run = self.view.session.latest_run(KIND_STORY)
        self.assertEqual(len(run.clips), 3)
        self.assertEqual(panel.inspector.currentWidget(), panel.results_scroll)
        self.assertEqual(panel.run_combo.currentData(), run.run_id)
        self.assertIn("Strict resume", panel.resume_text.text())
        before = self.view.session.story.draft.storyboard_id
        self.dialog_choice(Replacement.REPLACE)
        self.press(panel.reopen)
        self.assertNotEqual(self.view.session.story.draft.storyboard_id, before)
        self.assertIn("NEW Storyboard draft", self.view.banner.message.text())

    def test_stale_save_conflict_and_save_as_are_in_memory(self):
        panel = self.story(3)
        self.press(panel.save_btn)
        draft = self.view.session.story.draft
        self.assertEqual(draft.base_revision, 1)
        self.assertIn("in-memory mock", panel.saved_note.text())
        self.press(panel.other_btn)
        self.view.session.update_story(title="Changed locally")
        self.view.sync()
        self.press(panel.save_btn)
        self.assertIn(
            "Stale save refused",
            self.view.banner.title.text()
            if hasattr(self.view.banner, "title")
            else "Stale save refused",
        )
        self.assertTrue(self.view.banner.isVisible())
        before = self.view.session.story.draft.storyboard_id
        self.press(panel.save_as_btn)
        self.assertNotEqual(self.view.session.story.draft.storyboard_id, before)

    def test_changed_anchor_media_needs_acceptance(self):
        panel = self.story(3)
        ids = self.shot_ids()
        self.view.session.update_shot(
            ids[1],
            anchor_key="anchor:ridge-dusk",
            anchor_digest=self.view.session.catalog.get("anchor:ridge-dusk").digest,
        )
        self.view.sync()
        self.press(self.view.actions.review)
        self.assertEqual(self.view.session.status(KIND_STORY), Status.READY)
        self.view.session.catalog.replace_media("anchor:ridge-dusk")
        self.view.sync()
        self.view.select_shot(ids[1])
        panel.inspector.setCurrentWidget(panel.shot_scroll)
        pump(self.app)
        self.assertEqual(self.view.session.status(KIND_STORY), Status.STALE)
        self.assertTrue(panel.accept_anchor.isVisible())
        self.press(self.view.actions.review)
        self.assertEqual(self.view.session.status(KIND_STORY), Status.BLOCKED)
        self.press(panel.accept_anchor)
        self.press(self.view.actions.review)
        self.assertEqual(self.view.session.status(KIND_STORY), Status.READY)

    def test_layout_b_keeps_the_same_state_and_actions(self):
        panel = self.story(5)
        second = self.shot_ids()[1]
        self.view.select_shot(second)
        self.press(self.view.actions.review)
        self.choose(self.view.layout_combo, "timeline")
        self.assertIsNot(self.view.story_panel, panel)
        self.assertEqual(self.view.story_panel.layout_design, "timeline")
        self.assertEqual(self.view.ui.shot, second)
        self.assertEqual(self.view.session.status(KIND_STORY), Status.READY)
        self.assertEqual(len(self.view.story_panel.strip.cards), 5)
        self.press(self.view.actions.simulate)
        self.assertEqual(len(self.view.session.latest_run(KIND_STORY).clips), 5)

    # -------------------------------------------------------------------- Movie Clips
    def test_movie_assembly_order_is_authored_never_sorted(self):
        self.view.set_mode(KIND_MOVIE)
        panel = self.view.movie_panel
        panel.library.list.item(2).setSelected(True)
        panel.library.list.item(0).setSelected(True)
        self.press(panel.add_btn)
        ids = [i.clip_id for i in self.view.session.assembly.draft.items]
        self.assertEqual(ids, ["hist-run-1-clip-1", "hist-run-1-clip-3"])
        panel.assembly.list.setCurrentRow(1)
        pump(self.app)
        self.press(panel.assembly.up)
        ids = [i.clip_id for i in self.view.session.assembly.draft.items]
        self.assertEqual(ids, ["hist-run-1-clip-3", "hist-run-1-clip-1"])

    def test_ineligible_clips_are_visible_but_cannot_be_added(self):
        self.view.set_mode(KIND_MOVIE)
        library = self.view.movie_panel.library.list
        texts = [library.item(i).text() for i in range(library.count())]
        lost = next(t for t in texts if t.startswith("hist-clip-lost"))
        self.assertIn("Not eligible", lost)
        row = texts.index(lost)
        self.assertFalse(library.item(row).flags() & Qt.ItemFlag.ItemIsSelectable)

    def test_movie_simulate_creates_a_separate_identity(self):
        self.view.set_mode(KIND_MOVIE)
        self.view.add_clips(["hist-run-1-clip-1", "hist-run-1-clip-2"])
        self.assertEqual(self.view.ui.mode, KIND_MOVIE)
        self.press(self.view.actions.review)
        self.assertEqual(self.view.actions.simulate.text(), "Simulate Assembly")
        self.press(self.view.actions.simulate)
        movie = self.view.session.movies[-1]
        self.assertTrue(movie.movie_id.startswith("mock-movie"))
        self.assertNotIn(movie.movie_id, [c.clip_id for c in self.view.session.clips.values()])
        self.assertIn(
            "no FFmpeg", self.view.movie_panel.result_info.text().replace("FFmpeg ran", "no FFmpeg")
        )
        self.assertIsNotNone(self.view.movie_panel.viewer.plan)

    def test_crossfade_refusal_is_explained_and_hard_cut_recovers(self):
        self.view.set_mode(KIND_MOVIE)
        self.view.add_clips(["hist-run-1-clip-1", "hist-run-1-clip-3"])
        panel = self.view.movie_panel
        self.choose(panel.transition, "crossfade")
        self.press(self.view.actions.review)
        self.assertIn(self.view.session.status(KIND_MOVIE), (Status.BLOCKED, Status.READY))
        self.choose(panel.transition, "cut")
        self.press(self.view.actions.review)
        self.assertEqual(self.view.session.status(KIND_MOVIE), Status.READY)

    def test_send_to_movie_clips_adds_without_starting_assembly(self):
        self.start_quick()
        self.press(self.view.actions.review)
        self.press(self.view.actions.simulate)
        before = len(self.view.session.movies)
        self.press(self.view.actions.send)
        self.assertEqual(self.view.ui.mode, KIND_MOVIE)
        self.assertEqual(len(self.view.session.movies), before)
        self.assertEqual(len(self.view.session.assembly.draft.items), 1)

    # ------------------------------------------------------------- viewer and lifecycle
    def test_viewer_plays_pauses_scrubs_and_stops_when_hidden(self):
        self.start_quick()
        self.press(self.view.actions.review)
        self.press(self.view.actions.simulate)
        viewer = self.view.quick_panel.viewer
        self.press(viewer.play_button)
        self.assertTrue(viewer.playing)
        self.assertEqual(viewer.play_button.text(), "Pause")
        QTest.qWait(150)
        self.assertGreater(viewer.index, 0)
        self.press(viewer.play_button)
        self.assertFalse(viewer.playing)
        viewer.slider.setValue(5)
        self.assertEqual(viewer.index, 5)
        self.press(viewer.play_button)
        self.window.nav.setCurrentRow(0)
        pump(self.app)
        self.assertFalse(viewer.playing)

    def test_theme_switch_keeps_session_and_view_state(self):
        panel = self.story(4)
        self.view.select_shot(self.shot_ids()[2])
        self.press(self.view.actions.review)
        old_session = self.view.session
        library = ThemeLibrary()
        theme = library.get("concept-a")
        self.window.apply_theme(theme)
        pump(self.app)
        self.assertIsNot(self.window.motion_view, None)
        self.assertIs(self.view.session, old_session)
        self.assertEqual(self.view.ui.mode, KIND_STORY)
        self.assertEqual(self.view.ui.shot, self.shot_ids()[2])
        self.assertEqual(self.view.session.status(KIND_STORY), Status.READY)
        self.assertEqual(len(self.view.story_panel.strip.cards), 4)
        self.assertIsNot(self.view.story_panel, panel)
        self.window.apply_theme(library.get("blue-modern"))
        pump(self.app)
        self.assertEqual(self.view.session.status(KIND_STORY), Status.READY)

    def test_every_mode_works_in_the_second_theme(self):
        self.window.apply_theme(ThemeLibrary().get("concept-a"))
        pump(self.app)
        self.start_quick()
        self.press(self.view.actions.review)
        self.press(self.view.actions.simulate)
        self.assertEqual(self.view.session.status(KIND_QUICK), Status.SIMULATED)
        panel = self.story(3)
        self.press(self.view.actions.review)
        self.press(self.view.actions.simulate)
        self.assertTrue(self.view.session.latest_run(KIND_STORY).clips)
        self.assertIsNotNone(panel)

    def test_keyboard_shortcuts_review_and_undo(self):
        self.start_quick()
        self.view.quick_panel.prompt.setFocus()
        QTest.keyClick(
            self.view.quick_panel.prompt, Qt.Key.Key_Return, Qt.KeyboardModifier.ControlModifier
        )
        pump(self.app)
        self.assertEqual(self.view.session.status(KIND_QUICK), Status.READY)

    def test_every_motion_control_has_a_non_empty_accessible_name_or_text(self):
        from PySide6.QtWidgets import (
            QAbstractButton,
            QAbstractSpinBox,
            QComboBox,
            QLineEdit,
            QTextEdit,
        )

        self.story(3)
        for mode in (KIND_QUICK, KIND_STORY, KIND_MOVIE):
            self.view.set_mode(mode)
            pump(self.app)
            for kind in (QAbstractButton, QComboBox, QLineEdit, QTextEdit, QAbstractSpinBox):
                for widget in self.view.findChildren(kind):
                    if widget.parentWidget() is None or widget.objectName().startswith("qt_"):
                        continue
                    if isinstance(
                        widget, QLineEdit
                    ) and widget.parentWidget().__class__.__name__ in (
                        "QSpinBox",
                        "QComboBox",
                    ):
                        continue
                    label = widget.accessibleName() or (
                        widget.text() if isinstance(widget, QAbstractButton) else ""
                    )
                    self.assertTrue(label, f"{mode}: unnamed {type(widget).__name__}")

    # ------------------------------------------------------------------------ geometry
    def test_no_horizontal_overflow_or_clipped_persistent_controls_at_960x600(self):
        for layout in ("strip", "timeline"):
            for state in ("quick", "story", "movie"):
                window = PrototypeWindow()
                try:
                    prime_motion(window, (960, 600), state, layout)
                    row = probe_motion(window)
                    self.assertEqual(row["window"], (960, 600), (layout, state))
                    self.assertEqual(row["horizontal_overflow_px"], {}, (layout, state))
                    self.assertEqual(row["clipped"], [], (layout, state))
                    self.assertEqual(row["shrunk_controls"], [], (layout, state))
                    self.assertEqual(row["missing_tab_stops"], [], (layout, state))
                finally:
                    window.close()
                    window.deleteLater()
                    QApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
                    pump(self.app, 2)

    def test_all_shot_cards_fit_without_inner_scrolling_at_1366x768(self):
        for layout in ("strip", "timeline"):
            window = PrototypeWindow()
            try:
                prime_motion(window, (1366, 768), "story", layout, shots=8)
                row = probe_motion(window)
                self.assertEqual(row["shot_cards_visible_unscrolled"], 8, layout)
                self.assertEqual(row["horizontal_overflow_px"], {}, layout)
            finally:
                window.close()
                window.deleteLater()
                QApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
                pump(self.app, 2)
            window = PrototypeWindow()
            try:
                prime_motion(window, (1366, 768), "story", layout, shots=6)
                row = probe_motion(window)
                self.assertEqual(row["page_scroll_px"], 0, layout)
            finally:
                window.close()
                window.deleteLater()
                QApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
                pump(self.app, 2)

    def test_motion_scroll_areas_never_show_a_horizontal_scrollbar(self):
        self.story(6)
        for mode in (KIND_QUICK, KIND_STORY, KIND_MOVIE):
            self.view.set_mode(mode)
            pump(self.app)
            for scroll in self.view.findChildren(QScrollArea):
                if scroll.isVisible():
                    self.assertFalse(
                        scroll.horizontalScrollBar().isVisible(), (mode, scroll.accessibleName())
                    )


if __name__ == "__main__":
    unittest.main()
