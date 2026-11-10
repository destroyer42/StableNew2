"""Pure tests for the Output Display model (zoom math, fill width, frame content)."""

from __future__ import annotations

import unittest

from stablenew_qt_proto.domain import CreateSession
from stablenew_qt_proto.output_model import (
    MAX_ZOOM,
    MIN_ZOOM,
    SIZE_FILL,
    SIZE_FREE,
    SIZE_LOCKED,
    SIZE_MODES,
    SLIDER_STEPS,
    clamp_zoom,
    fill_width,
    fit_factor,
    format_zoom,
    frame_from_session,
    slider_to_zoom,
    step_zoom,
    zoom_to_slider,
)


class ZoomMathTests(unittest.TestCase):
    def test_clamp_rejects_nonsense(self):
        self.assertEqual(clamp_zoom(0), 1.0)
        self.assertEqual(clamp_zoom(float("nan")), 1.0)
        self.assertEqual(clamp_zoom(1e9), MAX_ZOOM)
        self.assertEqual(clamp_zoom(1e-9), MIN_ZOOM)

    def test_step_snaps_to_actual_size(self):
        self.assertEqual(step_zoom(0.9, +1), 1.0)
        self.assertEqual(step_zoom(1.1, -1), 1.0)
        self.assertGreater(step_zoom(1.0, +1), 1.0)
        self.assertLess(step_zoom(1.0, -1), 1.0)

    def test_step_stays_in_range(self):
        zoom = 1.0
        for _ in range(100):
            zoom = step_zoom(zoom, +1)
        self.assertEqual(zoom, MAX_ZOOM)
        for _ in range(200):
            zoom = step_zoom(zoom, -1)
        self.assertEqual(zoom, MIN_ZOOM)

    def test_fit_factor_uses_limiting_axis(self):
        self.assertAlmostEqual(fit_factor(500, 500, 1000, 500), 0.5)
        self.assertAlmostEqual(fit_factor(500, 500, 500, 1000), 0.5)
        self.assertAlmostEqual(fit_factor(1000, 1000, 500, 500), 2.0)  # upscaling allowed
        self.assertAlmostEqual(fit_factor(520, 520, 1000, 1000, margin=10), 0.5)

    def test_fit_factor_degenerate_inputs(self):
        self.assertEqual(fit_factor(10, 10, 0, 0), 1.0)
        self.assertEqual(fit_factor(10, 10, 100, 100, margin=20), MIN_ZOOM)

    def test_slider_round_trip_is_monotonic_and_bounded(self):
        self.assertAlmostEqual(slider_to_zoom(0), MIN_ZOOM)
        self.assertAlmostEqual(slider_to_zoom(SLIDER_STEPS), MAX_ZOOM)
        previous = 0.0
        for value in range(0, SLIDER_STEPS + 1, 50):
            zoom = slider_to_zoom(value)
            self.assertGreater(zoom, previous)
            previous = zoom
            self.assertLessEqual(abs(zoom_to_slider(zoom) - value), 1)

    def test_format_zoom(self):
        self.assertEqual(format_zoom(1.0), "100%")
        self.assertEqual(format_zoom(0.625), "62%")
        self.assertEqual(format_zoom(0.05), "5.0%")


class FillWidthTests(unittest.TestCase):
    def test_fill_takes_what_workspace_does_not_need(self):
        self.assertEqual(fill_width(1600, 900, 300), 700)

    def test_fill_never_goes_below_minimum_or_above_maximum(self):
        self.assertEqual(fill_width(1000, 900, 300), 300)
        self.assertEqual(fill_width(3000, 900, 300, maximum=1200), 1200)

    def test_modes_are_distinct(self):
        self.assertEqual(len(set(SIZE_MODES)), 3)
        self.assertEqual({SIZE_FREE, SIZE_LOCKED, SIZE_FILL}, set(SIZE_MODES))


class FrameTests(unittest.TestCase):
    def test_frame_follows_draft_size_and_prompt(self):
        session = CreateSession()
        frame = frame_from_session(session)
        self.assertEqual(frame.kind, "draft")
        self.assertEqual(
            (frame.width, frame.height),
            (session.draft.settings.width, session.draft.settings.height),
        )
        self.assertIn("explorer", frame.lines[0])  # {subject} resolved
        self.assertEqual(frame.lines[-1], "No image generated")

    def test_frame_kind_tracks_preview_and_receipt(self):
        session = CreateSession()
        session.build_preview()
        self.assertEqual(frame_from_session(session).kind, "preview")
        session.set_setting("steps", 40)
        self.assertEqual(frame_from_session(session).kind, "stale")
        session.build_preview()
        session.simulate_admission()
        frame = frame_from_session(session)
        self.assertEqual(frame.kind, "receipt")
        self.assertEqual(frame.lines[-1], "No image generated")

    def test_frame_aspect_and_dimensions(self):
        session = CreateSession()
        session.apply_size(768, 1360)
        frame = frame_from_session(session)
        self.assertEqual(frame.dimensions, "768 × 1360")
        self.assertAlmostEqual(frame.aspect, 768 / 1360)


if __name__ == "__main__":
    unittest.main()
