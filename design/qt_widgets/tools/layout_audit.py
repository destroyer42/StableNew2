"""Measure Create layout designs across window sizes (native Windows platform recommended).

    python tools/layout_audit.py --out docs/evidence/layout --sizes 1280x680 960x600

For each layout design (scrolling form, split workspace), size and Output Display state this
records reachability, clipping, scroll distance, task path length, persistent visibility and Tab
coverage as JSON plus a Markdown table. Nothing is submitted; only ``--out`` is written.
``--scale`` sets QT_SCALE_FACTOR and is SIMULATED scaling, recorded as such (not a real display).
"""

from __future__ import annotations

import argparse
import json
import os
import platform
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

DEFAULT_SIZES = ("1280x680", "960x600", "1440x900", "1920x1080")


def run(sizes: list[str], layouts: list[str], docks: list[str], theme_id: str) -> list[dict]:
    from PySide6.QtWidgets import QApplication

    from stablenew_qt_proto.app import PrototypeWindow, apply_theme
    from stablenew_qt_proto.layout_probe import probe, pump
    from stablenew_qt_proto.tokens import reference_theme

    app = QApplication.instance() or QApplication([])
    apply_theme(app, reference_theme(theme_id))
    rows: list[dict] = []
    for size in sizes:
        width, height = (int(part) for part in size.split("x"))
        for dock in docks:
            for layout in layouts:
                window = PrototypeWindow()
                window.resize(width, height)
                window.show()
                pump(app)
                window.create_view.set_layout_design(layout)
                window.output_dock.set_collapsed(dock == "collapsed")
                pump(app, 10)
                row = probe(window)
                row["requested_size"] = size
                row["dock_requested"] = dock
                rows.append(row)
                window.close()
    return rows


def markdown(rows: list[dict], meta: dict) -> str:
    lines = [
        f"# Create layout audit ({meta['platform_note']})", "",
        f"Theme `{meta['theme']}` · Qt platform `{meta['qpa']}` · scale {meta['scale']} "
        f"({'SIMULATED via QT_SCALE_FACTOR' if meta['scale'] != 1.0 else 'native display scale'}) · {meta['python']}", "",
        "| Layout | Window | Output Display | Form viewport | Form screens | Unreachable | Clipped/overflow | Task scroll actions | Form scroll (viewports) | Summary/preview/primary without scrolling | Tab stops · missing · out of view |",
        "|---|---|---|---|---|---|---|---|---|---|---|",
    ]
    for r in rows:
        persist = r["persistent_without_scroll"]
        kb = r.get("keyboard", {})
        tp = r["task_path"]
        lines.append(
            f"| {r['layout']} | {r['window'][0]}×{r['window'][1]} | {r['output_display']} | "
            f"{r['form_viewport'][0]}×{r['form_viewport'][1]} | {r['form_screens']} | "
            f"{', '.join(r['unreachable']) or 'none'} | {', '.join(r['horizontal_overflow']) or 'none'} | "
            f"{tp['scroll_actions']} | {tp['form_scroll_viewports']} | "
            f"{'yes' if all(persist.values()) else 'no: ' + ', '.join(k for k, v in persist.items() if not v)} | "
            f"{kb.get('tab_stops', '-')} · {len(kb.get('required_missing_from_chain', []))} · {kb.get('focus_out_of_view', '-')} |"
        )
    return "\n".join(lines) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", required=True, type=Path)
    parser.add_argument("--sizes", nargs="+", default=list(DEFAULT_SIZES))
    parser.add_argument("--layouts", nargs="+", default=["scroll", "split"])
    parser.add_argument("--docks", nargs="+", default=["expanded", "collapsed"])
    parser.add_argument("--theme", default="blue-modern")
    parser.add_argument("--scale", type=float, default=1.0)
    parser.add_argument("--offscreen", action="store_true", help="headless; text metrics are NOT representative")
    parser.add_argument("--name", default="layout_audit")
    args = parser.parse_args()
    if args.offscreen:
        os.environ["QT_QPA_PLATFORM"] = "offscreen"
    if args.scale != 1.0:
        os.environ["QT_SCALE_FACTOR"] = str(args.scale)
    sys.path.insert(0, str(ROOT))
    rows = run(args.sizes, args.layouts, args.docks, args.theme)
    from PySide6.QtGui import QGuiApplication

    screen = QGuiApplication.primaryScreen()
    meta = {
        "theme": args.theme, "qpa": QGuiApplication.platformName(), "scale": args.scale,
        "python": platform.python_version(), "os": platform.platform(),
        "platform_note": "headless, not representative" if args.offscreen else "native platform",
        "screen": None if screen is None else {
            "name": screen.name(), "geometry": [screen.geometry().width(), screen.geometry().height()],
            "devicePixelRatio": screen.devicePixelRatio(), "logicalDpi": screen.logicalDotsPerInch(),
        },
    }
    args.out.mkdir(parents=True, exist_ok=True)
    (args.out / f"{args.name}.json").write_text(json.dumps({"meta": meta, "rows": rows}, indent=2), encoding="utf-8")
    (args.out / f"{args.name}.md").write_text(markdown(rows, meta), encoding="utf-8")
    print(markdown(rows, meta))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
