"""PR-VID-EVAL-320: the Video Workflow tab's eval panel captures intent; the controller does the work."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from src.gui.view_contracts.video_experiment_contract import BackgroundWorkRunner
from src.gui.views.video_eval_panel_v2 import VideoEvalPanel
from src.video.video_eval_run import RUN_SCHEMA, EvalJobPlan
from src.video.video_eval_suite import SUITE_SCHEMA

RUN_ID = "20261122_040000_core_12345678"


def _write_run(run_dir):
    run_dir.mkdir(parents=True)
    (run_dir / "run.json").write_text(
        json.dumps(
            {
                "schema": RUN_SCHEMA,
                "run_id": run_dir.name,
                "jobs": [],
                "suite": {"suite_id": "core"},
            }
        ),
        encoding="utf-8",
    )


def _sync_runner() -> BackgroundWorkRunner:
    return BackgroundWorkRunner(spawn=lambda _name, target: target(), dispatch=lambda fn: fn())


class _Controller:
    def __init__(self, *, eligible: bool = True, experimental: tuple[str, ...] = ()) -> None:
        self.submitted: list[Any] = []
        self.reports: list[tuple[str, bool]] = []
        self.plan = SimpleNamespace(
            eligible=eligible,
            suite=SimpleNamespace(arms=()),
            jobs=[
                EvalJobPlan("case", arm, "svd_native", arm, 0, 25, SimpleNamespace(config={}))
                for arm in ("a", "b")
            ],
            experimental_arms=experimental,
            summary=lambda: "Eval suite core: 1 cases x 2 arms = 2 jobs",
        )

    def preview_eval_run(self, path):
        self.previewed = path
        return self.plan

    def submit_eval_run(self, plan):
        self.submitted.append(plan)
        run_dir = self.output / "video_eval" / RUN_ID
        _write_run(run_dir)
        return SimpleNamespace(run_id=RUN_ID, job_ids=("a", "b"), run_dir=run_dir)

    def build_eval_report(self, run_dir, *, show_prompts=True):
        self.reports.append((run_dir, show_prompts))
        (Path(run_dir) / "index.html").touch()
        return SimpleNamespace(
            summary=lambda: "2 of 2 clips measured",
            report_path=Path(run_dir) / "index.html",
        )


def _panel(tk_root, controller, tmp_path, *, populated=True, **kwargs):
    confirmations: list[str] = []
    opened: list[str] = []
    queued: list[list[str]] = []
    output = tmp_path / "output"
    controller.output = output
    folder = output / "eval_plans" / "video"
    suite = folder / "suite.json"
    if populated:
        folder.mkdir(parents=True)
        (folder / "image.png").touch()
        suite.write_text(
            json.dumps(
                {
                    "schema": SUITE_SCHEMA,
                    "suite_id": "core",
                    "cases": [{"case_id": "case", "image": "image.png", "prompt": "walk"}],
                    "arms": [{"arm_id": "base", "backend": "svd_native"}],
                }
            ),
            encoding="utf-8",
        )
    panel = VideoEvalPanel(
        tk_root,
        get_controller=lambda: controller,
        output_dir=lambda: str(output),
        show_prompts=kwargs.pop("show_prompts", lambda: True),
        on_queued=queued.append,
        runner=_sync_runner(),
        ask_open=kwargs.get("ask_open", lambda **_kw: ""),
        confirm_import=kwargs.get("confirm_import", lambda *_args: False),
        confirm=lambda _title, text: confirmations.append(text) or kwargs.get("answer", True),
        open_report=opened.append,
    )
    panel.refresh()
    return panel, confirmations, opened, queued


def test_queue_asks_names_experimental_arms_and_submits_once(tk_root, tmp_path) -> None:
    controller = _Controller(experimental=("ti2v",))
    panel, confirmations, _, queued = _panel(tk_root, controller, tmp_path)
    try:
        panel.on_queue_suite()
        assert Path(controller.previewed) == tmp_path / "output/eval_plans/video/suite.json"
        assert len(confirmations) == 1 and "ti2v" in confirmations[0]
        assert len(controller.submitted) == 1
        assert queued == [["a", "b"]]
        assert f"Queued 2 eval jobs as run {RUN_ID}" in panel.status_var.get()
        assert panel.run_combo.current() == 0
    finally:
        panel.destroy()


def test_declining_the_confirmation_queues_nothing(tk_root, tmp_path) -> None:
    controller = _Controller()
    panel, _, _, queued = _panel(tk_root, controller, tmp_path, answer=False)
    try:
        panel.on_queue_suite()
        assert controller.submitted == [] and queued == []
        assert "nothing was queued" in panel.status_var.get()
    finally:
        panel.destroy()


def test_an_unqueueable_plan_is_explained_without_asking(tk_root, tmp_path) -> None:
    controller = _Controller(eligible=False)
    panel, confirmations, _, _ = _panel(tk_root, controller, tmp_path)
    try:
        panel.on_queue_suite()
        assert confirmations == [] and controller.submitted == []
        assert "not queued" in panel.status_var.get()
    finally:
        panel.destroy()


def test_a_suite_error_is_shown_and_the_buttons_come_back(tk_root, tmp_path) -> None:
    class _Broken(_Controller):
        def preview_eval_run(self, path):
            raise ValueError("case portrait: image not found")

    panel, _, _, _ = _panel(tk_root, _Broken(), tmp_path)
    try:
        panel.on_queue_suite()
        assert "image not found" in panel.status_var.get()
        assert panel.queue_button.instate(["!disabled"])
    finally:
        panel.destroy()


def test_report_reads_visibility_on_tk_and_opens_the_contact_sheet(tk_root, tmp_path) -> None:
    controller = _Controller()
    panel, _, opened, _ = _panel(tk_root, controller, tmp_path, show_prompts=lambda: False)
    run_dir = controller.output / "video_eval" / RUN_ID
    _write_run(run_dir)
    panel.refresh()
    try:
        assert panel.open_report_button.instate(["disabled"])
        panel.on_build_report()
        assert controller.reports == [(str(run_dir), False)]
        assert len(opened) == 1 and opened[0].endswith("index.html")
        assert "2 of 2 clips measured" in panel.status_var.get()
        assert panel.open_report_button.instate(["!disabled"])
        panel.open_report_button.invoke()
        assert len(opened) == 2
    finally:
        panel.destroy()


def test_empty_output_and_cancelled_other_file_are_read_only(tk_root, tmp_path) -> None:
    controller = _Controller()
    calls = []
    panel, _, opened, _ = _panel(
        tk_root,
        controller,
        tmp_path,
        populated=False,
        ask_open=lambda **kw: calls.append(kw) or "",
    )
    try:
        folder = tmp_path / "output/eval_plans/video"
        assert str(folder) in panel.plan_status_var.get()
        assert not controller.output.exists()
        panel.other_file_button.invoke()
        panel.on_build_report()
        assert calls[0]["initialdir"] == str(folder)
        assert not hasattr(controller, "previewed") and controller.reports == [] and opened == []
        assert not controller.output.exists()
    finally:
        panel.destroy()


def test_invalid_plan_shows_reason_and_disables_queue(tk_root, tmp_path) -> None:
    controller = _Controller()
    panel, _, _, _ = _panel(tk_root, controller, tmp_path)
    try:
        folder = controller.output / "eval_plans" / "video"
        (folder / "unavailable.suite.json").write_text("{}", encoding="utf-8")
        panel.refresh()
        invalid = next(
            i
            for i, label in enumerate(panel.plan_combo["values"])
            if label.startswith("Unavailable")
        )
        panel.plan_combo.current(invalid)
        panel.plan_combo.event_generate("<<ComboboxSelected>>")
        assert panel.queue_button.instate(["disabled"])
        assert "unsupported eval suite schema" in panel.plan_status_var.get()
        assert not hasattr(controller, "previewed")
    finally:
        panel.destroy()


def test_other_file_can_import_before_preview(tk_root, tmp_path) -> None:
    controller = _Controller()
    outside = tmp_path / "existing"
    outside.mkdir()
    suite = outside / "existing.suite.json"
    (outside / "image.png").touch()
    suite.write_text(
        json.dumps(
            {
                "schema": SUITE_SCHEMA,
                "suite_id": "existing",
                "cases": [{"case_id": "case", "image": "image.png", "prompt": "walk"}],
                "arms": [{"arm_id": "base", "backend": "svd_native"}],
            }
        ),
        encoding="utf-8",
    )
    panel, _, _, _ = _panel(
        tk_root,
        controller,
        tmp_path,
        populated=False,
        answer=False,
        ask_open=lambda **_kw: str(suite),
        confirm_import=lambda *_args: True,
    )
    try:
        panel.other_file_button.invoke()
        imported = controller.output / "eval_plans" / "video" / suite.name
        assert Path(controller.previewed) == imported
        assert imported.is_file()
        assert not controller.submitted
    finally:
        panel.destroy()
