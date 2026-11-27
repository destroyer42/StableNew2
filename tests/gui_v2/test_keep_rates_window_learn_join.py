"""LEARN-JOIN: the read-only "What You Keep" window."""

from __future__ import annotations

import time

from src.gui.views.keep_rates_window import KeepRatesWindow
from src.learning.decision_rates import FACTOR_STEPS, Decision, JobFacts, build_report


def _report():
    facts = {"j": JobFacts(model="alpha", model_name="Alpha", factors={FACTOR_STEPS: ("20",)})}
    return build_report([Decision("a", "retain", favorite=True, job_id="j")], facts)


def _wait(window, done) -> None:
    deadline = time.monotonic() + 10
    while not done():
        assert time.monotonic() < deadline, window.summary_var.get()
        window.update()
        time.sleep(0.01)


def test_window_loads_on_a_worker_and_switches_factor(tk_root) -> None:
    window = KeepRatesWindow(tk_root, _report)
    _wait(window, lambda: "images decided" in window.summary_var.get())

    rows = [window.tree.item(item) for item in window.tree.get_children()]
    assert [row["text"] for row in rows] == ["Alpha"]
    assert rows[0]["values"][-1] == "not enough yet"

    window.factor_var.set(FACTOR_STEPS)
    window._factor_chosen()
    assert window.model_var.get() == "Alpha"
    assert window.tree.item(window.tree.get_children()[0])["text"] == "20"

    window.factor_var.set("Batch")
    window._factor_chosen()
    assert "No decided images" in window.tree.item(window.tree.get_children()[0])["text"]
    window.destroy()


def test_window_says_when_the_report_cannot_be_read(tk_root) -> None:
    def fail():
        raise OSError("locked")

    window = KeepRatesWindow(tk_root, fail)
    _wait(window, lambda: "could not be read" in window.summary_var.get())
    window.destroy()
