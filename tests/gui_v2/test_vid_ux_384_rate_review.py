"""VID-UX-384 follow-up: the Evaluate view's Rate & review section (intent capture only)."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from src.gui.views.video_workflow_layout_v2 import VIEW_EVALUATE
from src.gui.views.video_workflow_rate_review_v2 import (
    NO_RUN_TEXT,
    OPEN_OPERATOR_SITE_EVENT,
    RateReviewSection,
    rating_status_text,
)
from src.gui.views.video_workflow_tab_frame_v2 import VideoWorkflowTabFrameV2
from src.video.video_eval_catalog import RunEntry
from tests.helpers.make_video_313 import make_app, make_window

pytestmark = pytest.mark.gui


def _run(*, jobs=4, rated=1, built=True, report=True, motion=False, suite="suite_a"):
    path = Path("video_eval") / "20261101_120000_suite_a"
    return RunEntry(
        path=path,
        created_at="2026-11-01 12:00",
        suite_id=suite,
        jobs=jobs,
        built=built,
        report_path=path / "index.html" if report else None,
        rated=rated,
        motion=motion,
    )


def test_status_text_covers_every_rating_state():
    assert rating_status_text(None) == NO_RUN_TEXT
    assert "rated 1 of 4 clips" in rating_status_text(_run())
    assert "all 4 clips rated" in rating_status_text(_run(rated=4))
    assert "ratings file unreadable" in rating_status_text(_run(rated=None))
    assert "report pending" in rating_status_text(_run(built=False, report=False))


def test_buttons_follow_what_the_run_can_do(tk_root):
    calls: list[str] = []
    section = RateReviewSection(
        tk_root,
        open_report=lambda: calls.append("report"),
        open_motion_review=lambda: calls.append("motion"),
        open_site=lambda: calls.append("site"),
        site_available=True,
    )

    def enabled(button) -> bool:
        return not button.instate(["disabled"])

    section.set_run(None)
    assert not any(
        enabled(b) for b in (section.report_button, section.motion_button, section.site_button)
    )

    section.set_run(_run(built=False, report=False))
    assert not any(
        enabled(b) for b in (section.report_button, section.motion_button, section.site_button)
    )

    section.set_run(_run())
    assert enabled(section.report_button) and enabled(section.site_button)
    assert not enabled(section.motion_button)
    assert (
        float(section.progress.cget("maximum")) == 4 and float(section.progress.cget("value")) == 1
    )

    section.set_run(_run(motion=True))
    assert enabled(section.motion_button)
    for button in (section.report_button, section.motion_button, section.site_button):
        button.invoke()
    assert calls == ["report", "motion", "site"]


def test_site_review_is_disabled_when_the_site_is_unavailable(tk_root):
    section = RateReviewSection(
        tk_root,
        open_report=lambda: None,
        open_motion_review=lambda: None,
        open_site=lambda: None,
        site_available=False,
    )
    section.set_run(_run())
    assert section.site_button.instate(["disabled"])
    assert "Windows only" in str(section.hint_label.cget("text"))


@pytest.fixture
def env(tk_root, tmp_path):
    app, controller, service = make_app(tmp_path)
    tab = VideoWorkflowTabFrameV2(tk_root, app_controller=app, app_state=SimpleNamespace())
    app.main_window = make_window(tab)
    yield SimpleNamespace(tab=tab, root=tk_root)


def test_section_lives_in_the_evaluate_view_and_tracks_the_selected_run(env):
    tab = env.tab
    tab.select_view(VIEW_EVALUATE)
    assert tab.rate_review.master is tab.evaluate_view.rate_host
    assert str(tab.evaluate_view.rate_heading.cget("text")) == "Rate & review"
    assert tab.rate_review.status_var.get() == NO_RUN_TEXT
    run = _run()
    tab.eval_panel._runs = [run]
    tab.eval_panel.run_combo["values"] = [run.label]
    tab.eval_panel.run_combo.current(0)
    tab.eval_panel._on_selection()
    assert tab.eval_panel.selected_run() is run
    assert "rated 1 of 4 clips" in tab.rate_review.status_var.get()


def test_site_button_raises_the_virtual_event_and_never_touches_the_controller(env):
    tab = env.tab
    seen: list[str] = []
    env.root.bind(OPEN_OPERATOR_SITE_EVENT, lambda _e: seen.append("open"))
    tab.rate_review._site_available = True
    tab.rate_review.set_run(_run())
    tab.rate_review.site_button.invoke()
    env.root.update()
    assert seen == ["open"]


def test_readiness_chip_does_not_repeat_the_source_prefix_and_is_packed_before_the_status_label(
    env,
):
    from src.gui.views.video_workflow_media_pane_v2 import readiness_chip_text

    view = SimpleNamespace(
        source_state="ready",
        source_lines=("Source: 832x480 landscape",),
        advisory_lines=(),
        accepts_driving_video=False,
    )
    assert readiness_chip_text(view, has_source=True) == "Source ready · 832x480 landscape"
    tab = env.tab
    order = tab._action_bar.pack_slaves()
    assert order.index(tab.readiness_chip) < order.index(tab.status_label)
