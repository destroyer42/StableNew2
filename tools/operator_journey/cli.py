"""Command line entry point: ``python -m tools.operator_journey <journey> ...``."""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence
from pathlib import Path

from tools.operator_journey.evidence import FAIL, HOLD, PASS, JourneyEvidence
from tools.operator_journey.journeys.discovered_outputs_review import (
    JOURNEY_ID as DISCOVERED_JOURNEY_ID,
)
from tools.operator_journey.journeys.discovered_outputs_review import run_discovered_journey
from tools.operator_journey.journeys.learning_lora_strength import (
    DEFAULT_LORA,
    JOURNEY_ID,
    PHASES,
    JourneyConfig,
    run_journey,
)

EXIT_CODES = {PASS: 0, FAIL: 1, HOLD: 2}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m tools.operator_journey",
        description="Drive the real StableNew Tk GUI through a reference operator journey.",
    )
    parser.add_argument(
        "legacy_journey", nargs="?", metavar="journey", choices=[JOURNEY_ID, DISCOVERED_JOURNEY_ID]
    )
    golden = parser.add_argument_group("golden-path suite (PR-TEST-DESKTOP-830)")
    golden.add_argument(
        "--suite",
        choices=["golden-paths"],
        default=None,
        help="run the golden-path journeys instead of a single reference journey",
    )
    golden.add_argument(
        "--journey",
        dest="golden_journey",
        choices=["image", "video", "learning", "all"],
        default="all",
    )
    golden.add_argument(
        "--mode",
        choices=["simulated", "readiness", "physical"],
        default="simulated",
        help="simulated (default, no GPU) | readiness (read-only preflight) | physical (authorized plan only)",
    )
    golden.add_argument(
        "--desktop-driver",
        choices=["tk", "windows"],
        default="tk",
        help="tk = semantic widget calls; windows = real Win32 mouse/keyboard input (local desktop only)",
    )
    golden.add_argument(
        "--plan",
        type=Path,
        default=None,
        help="frozen physical plan (readiness and physical modes)",
    )
    golden.add_argument(
        "--build-plan",
        type=Path,
        default=None,
        metavar="OUT",
        help="freeze a plan from --plan-spec into OUT (read-only observation; never authorizes)",
    )
    golden.add_argument(
        "--plan-spec", type=Path, default=None, help="JSON {targets, limits} used by --build-plan"
    )
    backend = parser.add_mutually_exclusive_group()
    backend.add_argument("--backend", choices=["fake", "real"], default=None)
    backend.add_argument(
        "--real-backend",
        action="store_true",
        help="explicit opt-in to the real A1111 backend (never used by CI)",
    )
    parser.add_argument("--lora-name", default=DEFAULT_LORA)
    parser.add_argument("--seed", type=int, default=12345)
    parser.add_argument("--timeout", type=float, default=None, help="run-phase timeout seconds")
    parser.add_argument("--evidence-dir", type=Path, default=None)
    parser.add_argument("--webui-url", default=None, help="override the A1111 base URL (real mode)")
    parser.add_argument("--hide-window", action="store_true")
    parser.add_argument(
        "--startup-wait",
        type=float,
        default=None,
        help="seconds to wait for StableNew to connect to WebUI (normal startup takes ~15-30s)",
    )
    parser.add_argument(
        "--startup-grace",
        type=float,
        default=None,
        help="override StableNew's startup probe grace seconds (default: production timing)",
    )
    dev = parser.add_argument_group("harness development (fake backend)")
    dev.add_argument(
        "--fixture-sdxl",
        action="store_true",
        help="declare an SDXL loopback test fixture in the isolated AssetRegistry cache",
    )
    dev.add_argument("--stop-after", choices=list(PHASES), default=None)
    dev.add_argument("--discard-workspace", action="store_true")
    dev.add_argument("--fake-startup-delay", type=float, default=0.0)
    dev.add_argument("--fake-drop-seed-readback", action="store_true")
    return parser


def config_from_args(args: argparse.Namespace) -> JourneyConfig:
    config = JourneyConfig(
        backend="real" if args.real_backend else (args.backend or "fake"),
        lora_name=args.lora_name,
        seed=args.seed,
        timeout=args.timeout,
        webui_url=args.webui_url,
        show_window=not args.hide_window,
        startup_wait=args.startup_wait,
        startup_grace_sec=args.startup_grace,
        stop_after=args.stop_after,
        discard_workspace=args.discard_workspace,
        fixture_sdxl=args.fixture_sdxl,
    )
    if config.backend == "fake":
        config.fake_options = {
            "startup_delay": args.fake_startup_delay,
            "drop_seed_readback": args.fake_drop_seed_readback,
        }
    if args.evidence_dir is not None:
        config.evidence_root = args.evidence_dir
    return config


def format_verdict(evidence: JourneyEvidence) -> str:
    line = f"{evidence.journey_id} [{evidence.backend_mode}]: {evidence.verdict}"
    if evidence.failed_assertion:
        line += f" - {evidence.failed_assertion}"
    return f"{line}\nevidence: {evidence.summary.get('evidence_dir', '')}"


def _golden_main(parser: argparse.ArgumentParser, args: argparse.Namespace) -> int:
    from tools.operator_journey.golden.modes import ModeRefusal
    from tools.operator_journey.golden.suite import EXIT_CODES as GOLDEN_EXIT
    from tools.operator_journey.golden.suite import EXIT_REFUSED, build_plan_from_spec, run_suite

    if (
        args.legacy_journey
        or args.real_backend
        or args.backend is not None
        or args.webui_url
        or args.lora_name != DEFAULT_LORA
    ):
        parser.error(
            "--suite golden-paths takes no reference-journey name and no real-backend options; "
            "a physical run is configured only by its frozen --plan"
        )
    root = args.evidence_dir or (
        Path(__file__).resolve().parents[2] / "reports" / "operator_journeys"
    )
    if args.build_plan:
        if not args.plan_spec:
            parser.error("--build-plan needs --plan-spec")
        path = build_plan_from_spec(args.plan_spec, args.build_plan, root)
        print(f"frozen plan written (unauthorized): {path}")
        return 0
    try:
        verdict, run_dir = run_suite(
            journeys_choice=args.golden_journey,
            mode=args.mode,
            driver=args.desktop_driver,
            plan_path=args.plan,
            evidence_root=Path(root),
            hide_window=args.hide_window,
        )
    except ModeRefusal as exc:
        print(f"refused: {exc}", file=sys.stderr)
        return EXIT_REFUSED
    print(f"golden-paths [{args.mode}/{args.desktop_driver}]: {verdict}")
    print(f"evidence: {run_dir}")
    return GOLDEN_EXIT[verdict]


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.suite:
        return _golden_main(parser, args)
    if (
        args.plan
        or args.build_plan
        or args.plan_spec
        or args.mode != "simulated"
        or args.desktop_driver != "tk"
    ):
        parser.error(
            "--plan/--mode/--desktop-driver/--build-plan apply only with --suite golden-paths"
        )
    if args.legacy_journey is None:
        parser.error("choose a journey name or --suite golden-paths")
    args.journey = args.legacy_journey
    if args.journey == DISCOVERED_JOURNEY_ID:
        if args.real_backend or args.backend == "real":
            parser.error("discovered-outputs-review uses no generation backend")
        evidence = run_discovered_journey(config_from_args(args))
    else:
        evidence = run_journey(config_from_args(args))
    print(format_verdict(evidence))
    return EXIT_CODES[evidence.verdict]


if __name__ == "__main__":
    sys.exit(main())
