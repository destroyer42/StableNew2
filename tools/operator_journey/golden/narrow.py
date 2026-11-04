"""Narrow-window reachability: the entry controls of every golden path must stay reachable at the app's minimum size.

The window is resized to the application's own declared minimum (a window-manager request, as dragging the edge is);
each key control is then reached with the physical driver (wheel-scrolling pages when needed).  A control that is
hidden, disabled, off-screen, obscured or unresponsive is an acceptance failure, named with its reason.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from tools.operator_journey.golden.session import GoldenRun
from tools.operator_journey.tk_driver import WidgetNotFound


def _controls(run: GoldenRun) -> list[tuple[str, str, Callable[[], Any]]]:
    """(tab title, control label, resolver) for each golden path's entry controls."""

    w = run.window
    d = run.driver
    return [
        ("Prompt", "Prompt: New pack", lambda: d.find_button(w.prompt_tab, "New")),
        ("Prompt", "Prompt: Save pack", lambda: d.find_button(w.prompt_tab, "Save")),
        (
            "Pipeline",
            "Pipeline: Pack list Refresh",
            lambda: w.sidebar_panel_v2.refresh_packs_button,
        ),
        (
            "Pipeline",
            "Pipeline: Steps",
            lambda: w.sidebar_panel_v2.base_generation_panel._steps_spin,
        ),
        (
            "Video Workflow - Adv",
            "Video: Browse source image",
            lambda: d.find_button(w.video_workflow_tab, "Browse..."),
        ),
        (
            "Video Workflow - Adv",
            "Video: Select Images",
            lambda: d.find_button(w.video_workflow_tab, "Select Images..."),
        ),
        (
            "Learning - Adv",
            "Learning: New Experiment",
            lambda: d.find_button(w.learning_tab.header_frame, "New Experiment"),
        ),
        (
            "Learning - Adv",
            "Learning: Experiment Library",
            lambda: d.find_button(w.learning_tab.header_frame, "Experiment Library"),
        ),
    ]


def run_narrow(run: GoldenRun) -> None:
    run.boot_app()
    d, root = run.driver, run.root
    assert root is not None
    min_w, min_h = root.minsize()
    root.state("normal")
    root.geometry(f"{max(min_w, 1)}x{max(min_h, 1)}+20+20")
    d.pump(1.0)
    size = (root.winfo_width(), root.winfo_height())
    run.ev.observe("narrow_window", {"requested_minimum": [min_w, min_h], "actual": list(size)})
    run.snap("narrow_start")
    run.require(
        "narrow",
        "window_is_narrow",
        size[0] <= max(min_w, 1) + 40,
        f"window {size} is not at the declared minimum {(min_w, min_h)}",
    )
    for tab_title, label, resolve in _controls(run):
        try:
            d.select_tab(run.window.center_notebook, tab_title)
            widget = resolve()
            if widget is None:
                raise WidgetNotFound(f"{label}: control does not exist")
            d.reach(widget, label=label)
            run.check("narrow", f"reachable[{label}]", True, "")
        except Exception as exc:  # noqa: BLE001 - every control is reported, not just the first failure
            run.snap(f"narrow_{label.split(':')[0].lower()}_blocked")
            run.check("narrow", f"reachable[{label}]", False, f"{type(exc).__name__}: {exc}")
    run.shutdown_app()


def main(argv: list[str] | None = None) -> int:
    """``python -m tools.operator_journey.golden.narrow --evidence-dir DIR``: the physical narrow-window check."""

    import argparse
    import json
    import sys
    from pathlib import Path

    from tools.operator_journey.golden.fixtures import make_fake_a1111, seed_declared_sdxl
    from tools.operator_journey.golden.modes import ModeRefusal, validate_combination
    from tools.operator_journey.golden.session import RunConfig, run_journey_body

    parser = argparse.ArgumentParser(prog="python -m tools.operator_journey.golden.narrow")
    parser.add_argument("--evidence-dir", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        validate_combination(mode="simulated", driver="windows", plan=None)
    except ModeRefusal as exc:
        print(f"refused: {exc}", file=sys.stderr)
        return 4
    args.evidence_dir.mkdir(parents=True, exist_ok=True)
    config = RunConfig(driver="windows", evidence_dir=args.evidence_dir, maximize=False)
    evidence = run_journey_body(
        "NARROW",
        run_narrow,
        config,
        mode_label="simulated",
        fake_a1111_factory=make_fake_a1111,
        workspace_hook=seed_declared_sdxl,
    )
    (args.evidence_dir / "narrow_evidence.json").write_text(
        json.dumps(evidence.as_dict(), indent=2, default=str), "utf-8"
    )
    print(f"narrow-window: {evidence.verdict}")
    return 0 if evidence.verdict == "PASS" else 1


if __name__ == "__main__":
    import sys

    sys.exit(main())
