"""How long the phone takes to open an image, per day: the PHONE-FAST gate (read only).

    python -m tools.gate_report [--json]

It reads the open times the review gateway holds (30 days, at most 100,000 views) with the gateway address, pinned
certificate and sync secret that StableNew's Phone review gateway dialog stored for this Windows user (DPAPI). It
changes nothing: not the gateway, the live checkout, the sync ledger or the running app.

A view is timed from the item becoming current on the phone to its image having loaded. Days are this PC's local days.
A cache hit is a view whose bytes were not asked for when it was viewed: they were in the phone's cache or had been
fetched ahead. Its share is of the views whose source the phone could tell. p90 is the time nine views in ten met.

Exit codes: 0 reported (also when there is nothing yet); 1 the gateway refused or does not offer open times yet; 2 usage
or no gateway settings; 4 the gateway is unreachable.
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
from collections.abc import Mapping, Sequence
from datetime import datetime, tzinfo
from typing import Any

from src.app.review_gateway_client import (
    OPEN_SOURCES,
    GatewayClient,
    GatewayError,
    GatewayUnauthorized,
    GatewayUnavailable,
    PinnedHttpsTransport,
)
from src.app.review_gateway_store import GatewaySettingsStore

EXIT_OK = 0
EXIT_REFUSED = 1
EXIT_USAGE = 2
EXIT_UNREACHABLE = 4
_COLUMNS = (
    "day",
    "views",
    "median ms",
    "p90 ms",
    "cache hits",
    "network",
    "cache",
    "prefetch",
    "unknown",
    "median KB",
)
_WIDTHS = (10, 7, 9, 7, 10, 7, 5, 8, 7, 9)


def _figures(day: str, rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    times = sorted(row["ms"] for row in rows)
    sizes = [row["bytes"] for row in rows if row["bytes"] is not None]
    count = {source: sum(row["source"] == source for row in rows) for source in OPEN_SOURCES}
    known = len(rows) - count["unknown"]
    return {
        "day": day,
        "views": len(times),
        "median_ms": round(statistics.median(times)),
        "p90_ms": times[(9 * len(times) + 9) // 10 - 1],  # nearest rank: a measured time
        **count,
        "cache_hit_share": (count["cache"] + count["prefetch"]) / known if known else None,
        "median_bytes": round(statistics.median(sizes)) if sizes else None,
    }


def summarize(
    rows: Sequence[Mapping[str, Any]], zone: tzinfo | None = None
) -> list[dict[str, Any]]:
    """One set of figures per day in ``zone`` (this PC's local time when ``None``), then one for ``all``."""

    days: dict[str, list[Mapping[str, Any]]] = {}
    for row in rows:
        day = datetime.fromisoformat(row["at"]).astimezone(zone).date().isoformat()
        days.setdefault(day, []).append(row)
    found = [_figures(day, days[day]) for day in sorted(days)]
    return [*found, _figures("all", rows)] if rows else []


def _line(values: Sequence[object]) -> str:
    first, *rest = (str(value) for value in values)
    cells = [first.ljust(_WIDTHS[0])]
    cells += [value.rjust(width) for value, width in zip(rest, _WIDTHS[1:], strict=True)]
    return "  ".join(cells)


def _table(days: Sequence[Mapping[str, Any]]) -> list[str]:
    lines = [_line(_COLUMNS)]
    for day in days:
        share, size = day["cache_hit_share"], day["median_bytes"]
        lines.append(
            _line(
                (
                    day["day"],
                    day["views"],
                    day["median_ms"],
                    day["p90_ms"],
                    "-" if share is None else f"{share:.0%}",
                    *(day[source] for source in OPEN_SOURCES),
                    "-" if size is None else round(size / 1000),
                )
            )
        )
    return lines


def main(argv: Sequence[str] | None = None, *, client: GatewayClient | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m tools.gate_report", description=(__doc__ or "").split("\n\n")[0]
    )
    parser.add_argument("--json", action="store_true", help="print the figures as JSON")
    try:
        args = parser.parse_args(argv)
    except SystemExit as exit_:
        return EXIT_USAGE if exit_.code else EXIT_OK
    if client is None:
        try:
            settings = GatewaySettingsStore().load()
        except (OSError, ValueError) as error:
            print(f"The gateway settings cannot be read: {error}", file=sys.stderr)
            return EXIT_USAGE
        if settings is None:
            print(
                "No gateway settings for this Windows user: enter them in StableNew's Phone review gateway dialog.",
                file=sys.stderr,
            )
            return EXIT_USAGE
        client = GatewayClient(PinnedHttpsTransport(settings), settings.secret)
    try:
        rows = client.open_timings()
    except GatewayUnauthorized:
        print("The gateway refused the sync secret: check the Phone review gateway settings.")
        return EXIT_REFUSED
    except GatewayUnavailable:
        print("The gateway is unreachable from this PC.")
        return EXIT_UNREACHABLE
    except GatewayError as error:
        print(f"The gateway answered unexpectedly: {error}")
        return EXIT_REFUSED
    if rows is None:
        print("The gateway does not offer open times yet: deploy a release that records them.")
        return EXIT_REFUSED
    days = summarize(rows)
    if args.json:
        print(json.dumps(days, indent=2))
    elif not days:
        print("No open times yet. They arrive while images are reviewed on the phone.")
    else:
        print("\n".join(_table(days)))
    return EXIT_OK


if __name__ == "__main__":
    raise SystemExit(main())
