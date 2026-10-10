"""Operator-invoked, read-only model topology report (PR-IMG-MODELS-152).

A thin orchestrator over the application's evidence APIs (``AssetRegistry.observe`` -> ``build_report``). It adds no
classifier, cache or identity store of its own. By default it is fully offline: it stats files and reads bounded
safetensors/GGUF headers and adjacent configs; it never hashes a weight, loads a model, writes the hash cache, starts a
process or contacts a server. ``--forge-url`` additionally makes GET-only reads against an endpoint that is *already*
running (never launched, restarted or discovered by this tool). The only file written is the one ``--json`` names.

    python tools/asset_topology_report.py                       # compact console summary
    python tools/asset_topology_report.py --json report.json    # full redacted JSON (no absolute paths)
    python tools/asset_topology_report.py --json - --include-paths
    python tools/asset_topology_report.py --forge-url http://127.0.0.1:7860   # explicit, GET-only reconciliation
"""

from __future__ import annotations

import argparse
import signal
import sys
from collections.abc import Sequence
from dataclasses import asdict
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.assets.inventory_report import build_report, render_console, render_json  # noqa: E402
from src.assets.observation import ScanLimits  # noqa: E402
from src.assets.registry import AssetRegistry  # noqa: E402

#: The one recorded measured outcome (PR-IMG-MODELS-151). It is attached only to the exact evaluated candidate.
RECORDED_OUTCOMES: tuple[dict[str, Any], ...] = (
    {
        "id": "PR-IMG-MODELS-151",
        "verdict": "NO_GO_RESOURCE_RISK",
        "scope": "exact full-BF16 FLUX.2 Klein Base 9B stack on the evaluated 12 GB GPU / ~34 GB host RAM",
        "applies_to": {
            "architecture": "flux2_dit",
            "hidden_size": 4096,
            "precision_layout": "plain",
            "dominant_dtype_by_bytes": "BF16",
            "file_name": "flux-2-klein-base-9b.safetensors",
            "size_bytes": 18_157_185_200,
            "sha256_prefix": "9105af6c",
            "sha256_suffix": "41ca",
        },
    },
)


def _profile_lookup() -> Any:
    from src.image_backends.forge_klein_profile import is_klein_transformer_name

    return is_klein_transformer_name


def _forge_state(url: str) -> dict[str, Any]:
    from src.api.forge_client import ForgeWebUIClient
    from src.image_backends.model_inventory_reconcile import read_forge_state

    return read_forge_state(ForgeWebUIClient(base_url=url))


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument(
        "--webui-root", type=Path, help="WebUI home (default: the configured StableNew WebUI root)"
    )
    parser.add_argument(
        "--cache-path", type=Path, help="registry hash cache to read identity from (read-only)"
    )
    parser.add_argument(
        "--json", dest="json_path", help="write the full JSON report here ('-' for stdout)"
    )
    parser.add_argument(
        "--include-paths",
        action="store_true",
        help="include absolute local paths (default: labels only)",
    )
    parser.add_argument(
        "--forge-url", help="explicit GET-only reconciliation with an already-running endpoint"
    )
    parser.add_argument("--max-files", type=int, default=ScanLimits.max_files)
    parser.add_argument("--max-dirs", type=int, default=ScanLimits.max_dirs)
    parser.add_argument("--max-depth", type=int, default=ScanLimits.max_depth)
    args = parser.parse_args(argv)

    registry = AssetRegistry(args.webui_root, cache_path=args.cache_path)
    if registry.webui_root is None:
        print("No WebUI root is configured; pass --webui-root.", file=sys.stderr)
        return 2
    limits = ScanLimits(max_files=args.max_files, max_dirs=args.max_dirs, max_depth=args.max_depth)
    cancelled = {"flag": False}

    def _interrupt(_signum: int, _frame: Any) -> None:
        cancelled["flag"] = True  # a cancelled scan yields a partial, clearly incomplete report

    previous = None
    try:
        previous = signal.signal(signal.SIGINT, _interrupt)
    except ValueError:  # not the main thread: cancellation by signal is simply unavailable
        pass
    try:
        scan = registry.observe(limits=limits, cancelled=lambda: cancelled["flag"])
    finally:
        if previous is not None:
            signal.signal(signal.SIGINT, previous)
    state = _forge_state(args.forge_url) if args.forge_url else None
    report = build_report(
        scan,
        include_paths=args.include_paths,
        roots=registry.observation_roots(),
        runtime_state=state,
        recorded_outcomes=RECORDED_OUTCOMES,
        profile_lookup=_profile_lookup(),
        limits=asdict(limits),
    )
    if args.json_path == "-":
        sys.stdout.write(render_json(report))
    else:
        if args.json_path:
            Path(args.json_path).write_text(render_json(report), encoding="utf-8")
        sys.stdout.write(render_console(report))
    return 0 if scan.complete else 3


if __name__ == "__main__":
    raise SystemExit(main())
