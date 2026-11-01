"""Render the GUI-SEAM-743 result tables from one or two ``metrics.json`` files (pure; no GUI, nothing is re-measured)."""

from __future__ import annotations

import json
import statistics
import sys
from pathlib import Path
from typing import Any

from tools.qualification.gui_seam_743.evidence import SCALAR_KEYS, verdict

COLUMNS = (
    ("burst_median_ms", "burst med ms"),
    ("burst_p95_ms", "burst p95 ms"),
    ("burst_total_ms", "drain ms"),
    ("burst_max_batch", "max batch"),
    ("sustained_hb_p95_ms", "load hb p95"),
    ("sustained_hb_max_ms", "load hb max"),
    ("sustained_pump_max_ms", "pump max ms"),
    ("refresh_to_visible_ms", "refresh ms"),
    ("idle_period_median_ms", "idle period ms"),
    ("idle_pump_hz", "idle pump Hz"),
    ("idle_cpu_percent", "idle cpu %"),
)


def _fmt(value: float) -> str:
    return f"{value:.1f}" if abs(value) < 1000 else f"{value:.0f}"


def table(conditions: dict[str, Any]) -> str:
    header = "| cond | " + " | ".join(label for _, label in COLUMNS) + " |"
    lines = [header, "|" + "---|" * (len(COLUMNS) + 1)]
    for name, cond in conditions.items():
        runs = [r["scalars"] for r in cond["runs"]]
        cells = []
        for key, _ in COLUMNS:
            values = [r[key] for r in runs]
            cells.append(
                f"{_fmt(statistics.median(values))} ({_fmt(min(values))}-{_fmt(max(values))})"
            )
        lines.append(f"| {name} | " + " | ".join(cells) + " |")
    return "\n".join(lines)


def screens_table(screens: dict[str, Any]) -> str:
    lines = [
        "| cond | burst med cut | burst p95 cut | hb p95 d | hb max d (med/worst) | refresh cut | idle cpu d pp | pump Hz x | gates (burst/resp/refresh/resource) |",
        "|---|---|---|---|---|---|---|---|---|",
    ]
    for name, s in screens.items():
        g = s["gates"]
        gates = "/".join(
            "pass" if g[k] else "FAIL"
            for k in ("burst", "responsiveness", "representative_refresh", "resource")
        )
        lines.append(
            f"| {name} | {s['burst_median_reduction']:+.0%} | {s['burst_p95_reduction']:+.0%} | "
            f"{s['heartbeat_p95_delta_ms']:+.1f} | {s['heartbeat_max_delta_ms_median_of_runs']:+.1f} / {s['heartbeat_worst_gap_delta_ms']:+.1f} | "
            f"{s['refresh_reduction']:+.0%} | {s['idle_cpu_delta_pp']:+.2f} | {s['idle_pump_rate_ratio']:.2f} | {gates} |"
        )
    return "\n".join(lines)


def main(paths: list[str]) -> int:
    screens: dict[str, Any] = {}
    confirm: list[str] = []
    for raw in paths:
        report = json.loads(Path(raw).read_text(encoding="utf8"))
        ident = report["identity"]
        print(
            f"## {ident['phase']}  validity={report['validity']['status']}  sha={ident['source_sha'][:8]}"
        )
        for phase in report["phases"].values():
            print(table(phase["conditions"]))
            print()
            print(screens_table(phase.get("screens", {})))
            print()
            screens.update(phase.get("screens", {}))
            if ident["phase"] == "confirmation":
                confirm.extend(phase.get("screens", {}))
        for failure in report["validity"]["failures"]:
            print("FAILURE:", failure)
    assert set(SCALAR_KEYS)
    if screens:
        print(json.dumps(verdict(screens, confirm), indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
