"""PR-VID-EVAL-320: the Video Workflow tab's eval panel captures intent; the controller does the work."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Any

from src.gui.view_contracts.video_experiment_contract import BackgroundWorkRunner
from src.gui.views.video_eval_panel_v2 import VideoEvalPanel


def _sync_runner() -> BackgroundWorkRunner:
    return BackgroundWorkRunner(spawn=lambda _name, target: target(), dispatch=lambda fn: fn())


class _Controller:
    def __init__(self, *, eligible: bool = True, experimental: tuple[str, ...] = ()) -> None:
        self.submitted: list[Any] = []
        self.reports: list[tuple[str, bool]] = []
        self.plan = SimpleNamespace(
            eligible=eligible,
            jobs=[object(), object()],
            experimental_arms=experimental,
            summary=lambda: "Eval suite core: 1 cases x 2 arms = 2 jobs",
        )

    def preview_eval_run(self, path):
        self.previewed = path
        return self.plan

    def submit_eval_run(self, plan):
        self.submitted.append(plan)
        return SimpleNamespace(
            run_id="run1", job_ids=("a", "b"), run_dir=Path("output/video_eval/run1")
        )

    def build_eval_report(self, run_dir, *, show_prompts=True):
        self.reports.append((run_dir, show_prompts))
        return SimpleNamespace(
            summary=lambda: "2 of 2 clips measured",
            report_path=Path(run_dir) / "index.html",
        )


def _panel(tk_root, controller, **kwargs):
    confirmations: list[str] = []
    opened: list[str] = []
    queued: list[list[str]] = []
    panel = VideoEvalPanel(
        tk_root,
        get_controller=lambda: controller,
        output_dir=lambda: "output",
        show_prompts=kwargs.pop("show_prompts", lambda: True),
        on_queued=queued.append,
        runner=_sync_runner(),
        ask_open=lambda **_kw: kwargs.get("suite", "suite.json"),
        ask_directory=lambda **_kw: kwargs.get("run_dir", "output/video_eval/run1"),
        confirm=lambda _title, text: confirmations.append(text) or kwargs.get("answer", True),
        open_report=opened.append,
    )
    return panel, confirmations, opened, queued


def test_queue_asks_names_experimental_arms_and_submits_once(tk_root) -> None:
    controller = _Controller(experimental=("ti2v",))
    panel, confirmations, _, queued = _panel(tk_root, controller)
    try:
        panel.on_queue_suite()
        assert controller.previewed == "suite.json"
        assert len(confirmations) == 1 and "ti2v" in confirmations[0]
        assert len(controller.submitted) == 1
        assert queued == [["a", "b"]]
        assert "Queued 2 eval jobs as run run1" in panel.status_var.get()
    finally:
        panel.destroy()


def test_declining_the_confirmation_queues_nothing(tk_root) -> None:
    controller = _Controller()
    panel, _, _, queued = _panel(tk_root, controller, answer=False)
    try:
        panel.on_queue_suite()
        assert controller.submitted == [] and queued == []
        assert "nothing was queued" in panel.status_var.get()
    finally:
        panel.destroy()


def test_an_unqueueable_plan_is_explained_without_asking(tk_root) -> None:
    controller = _Controller(eligible=False)
    panel, confirmations, _, _ = _panel(tk_root, controller)
    try:
        panel.on_queue_suite()
        assert confirmations == [] and controller.submitted == []
        assert "not queued" in panel.status_var.get()
    finally:
        panel.destroy()


def test_a_suite_error_is_shown_and_the_buttons_come_back(tk_root) -> None:
    class _Broken(_Controller):
        def preview_eval_run(self, path):
            raise ValueError("case portrait: image not found")

    panel, _, _, _ = _panel(tk_root, _Broken())
    try:
        panel.on_queue_suite()
        assert "image not found" in panel.status_var.get()
        assert panel.queue_button.instate(["!disabled"])
    finally:
        panel.destroy()


def test_report_reads_visibility_on_tk_and_opens_the_contact_sheet(tk_root) -> None:
    controller = _Controller()
    panel, _, opened, _ = _panel(tk_root, controller, show_prompts=lambda: False)
    try:
        panel.on_build_report()
        assert controller.reports == [("output/video_eval/run1", False)]
        assert len(opened) == 1 and opened[0].endswith("index.html")
        assert "2 of 2 clips measured" in panel.status_var.get()
    finally:
        panel.destroy()


def test_cancelled_dialogs_do_nothing(tk_root) -> None:
    controller = _Controller()
    panel, _, opened, _ = _panel(tk_root, controller, suite="", run_dir="")
    try:
        panel.on_queue_suite()
        panel.on_build_report()
        assert not hasattr(controller, "previewed") and controller.reports == [] and opened == []
    finally:
        panel.destroy()
