"""Operator-invoked, offline readiness report of installed assets against the curated catalog (PR-ASSET-130).

A thin orchestrator over ``AssetRegistry`` (the one byte-identity authority) and ``src/assets/resource_readiness``. It
never downloads, loads a model, starts a process, contacts a server or touches the queue. Without ``--refresh`` it reads
only the registry's persisted hash cache (stat-validated) and so cannot prove that anything is absent; ``--refresh``
streams SHA-256 for the ControlNet and auxiliary model folders through the registry's own cache, which is the only file
this tool can write (besides the one ``--json`` names).

    python tools/asset_readiness_report.py                      # compact console summary from the cache
    python tools/asset_readiness_report.py --refresh            # hash the two folders first (cancel with Ctrl+C)
    python tools/asset_readiness_report.py --refresh --json report.json   # sanitized, deterministic JSON ('-' = stdout)

Exit status: 0 complete evidence, 2 no WebUI root or unusable catalog, 3 incomplete evidence.
"""

from __future__ import annotations

import argparse
import signal
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.assets.registry import AssetRegistry  # noqa: E402
from src.assets.resource_catalog import CatalogError, load_catalog  # noqa: E402
from src.assets.resource_readiness import (  # noqa: E402
    build_report,
    collect_installed_evidence,
    render_console,
    render_json,
)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument(
        "--webui-root", type=Path, help="WebUI home (default: the configured StableNew WebUI root)"
    )
    parser.add_argument("--cache-path", type=Path, help="registry hash cache to read and update")
    parser.add_argument(
        "--catalog",
        type=Path,
        help="alternate catalog JSON (default: config/curated_asset_catalog.json)",
    )
    parser.add_argument(
        "--refresh",
        action="store_true",
        help="stream SHA-256 of the ControlNet and auxiliary folders",
    )
    parser.add_argument(
        "--json", dest="json_path", help="write the sanitized JSON report here ('-' for stdout)"
    )
    args = parser.parse_args(argv)

    try:
        catalog = load_catalog(args.catalog)
    except CatalogError as exc:
        print(f"Catalog refused: {exc}", file=sys.stderr)
        return 2
    registry = AssetRegistry(args.webui_root, cache_path=args.cache_path)
    if registry.webui_root is None:
        print("No WebUI root is configured; pass --webui-root.", file=sys.stderr)
        return 2

    cancelled = {"flag": False}

    def _interrupt(_signum: int, _frame: Any) -> None:
        cancelled["flag"] = (
            True  # a cancelled refresh yields an incomplete report, never a partial verdict
        )

    previous = None
    try:
        previous = signal.signal(signal.SIGINT, _interrupt)
    except ValueError:  # not the main thread: cancellation by signal is simply unavailable
        pass
    try:
        evidence = collect_installed_evidence(
            registry, catalog, refresh=args.refresh, cancelled=lambda: cancelled["flag"]
        )
    finally:
        if previous is not None:
            signal.signal(signal.SIGINT, previous)
    report = build_report(catalog, evidence)
    if args.json_path == "-":
        sys.stdout.write(render_json(report))
    else:
        if args.json_path:
            Path(args.json_path).write_text(render_json(report), encoding="utf-8", newline="\n")
        sys.stdout.write(render_console(report))
    return 0 if evidence.complete else 3


if __name__ == "__main__":
    raise SystemExit(main())
