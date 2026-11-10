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


def run(
    sizes: list[str], layouts: list[str], docks: list[str], states: list[str], theme_id: str
) -> list[dict]:
    from PySide6.QtCore import QEvent
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
                for state in states:
                    window = PrototypeWindow()
                    window.output_toggle.setChecked(dock == "expanded")
                    window.resize(width, height)
                    window.show()
                    pump(app)
                    window.create_view.set_layout_design(layout)
                    window.output_dock.set_collapsed(dock == "collapsed")
                    pump(app, 10)  # the minimum width only drops once the dock has collapsed
                    window.resize(width, height)
                    pump(app, 10)
                    row = probe(window, primed=state == "primed")
                    row["requested_size"] = size
                    row["dock_requested"] = dock
                    row["size_clamped"] = [window.width(), window.height()] != [width, height]
                    rows.append(row)
                    window.close()
                    window.deleteLater()
                    QApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
                    pump(app, 2)
    return rows


def markdown(rows: list[dict], meta: dict) -> str:
    lines = [
        f"# Create layout audit ({meta['platform_note']})",
        "",
        f"Theme `{meta['theme']}` · Qt platform `{meta['qpa']}` · scale {meta['scale']} "
        f"({'SIMULATED via QT_SCALE_FACTOR' if meta['scale'] != 1.0 else 'native display scale'}) · {meta['python']}",
        "",
        "| Layout | State | Requested → actual | Output Display | Form viewport | Form height | Required in view | Unreachable | Clipped text / overflow | Task scroll actions | Task scroll px (form/settings/review) | Summary/preview/primary without scrolling | Tab stops · missing · out of view · preview before actions |",
        "|---|---|---|---|---|---|---|---|---|---|---|---|",
    ]
    for r in rows:
        persist = r["persistent_without_scroll"]
        kb = r.get("keyboard", {})
        tp = r["task_path"]
        lines.append(
            f"| {r['layout']} | {r['state']} | {r['requested_size']} → {r['window'][0]}×{r['window'][1]}"
            f"{' (clamped by minimum size)' if r['size_clamped'] else ''} | {r['output_display']} | "
            f"{r['form_viewport'][0]}×{r['form_viewport'][1]} | {r['form_content_height']} | "
            f"{len(r['visible_required_controls'])}/{len(r['controls'])} | "
            f"{', '.join(r['unreachable']) or 'none'} | "
            f"{len(r['clipped_text'])} / {len(r['horizontal_overflow'])} | "
            f"{tp['scroll_actions']} | {tp['form_scroll_px']}/{tp['settings_scroll_px']}/{tp['review_scroll_px']} | "
            f"{'yes' if all(persist.values()) else 'no: ' + ', '.join(k for k, v in persist.items() if not v)} | "
            f"{kb.get('tab_stops', '-')} · {len(kb.get('required_missing_from_chain', []))} · {kb.get('focus_out_of_view', '-')} · "
            f"{'yes' if kb.get('preview_before_actions') else 'no'} |"
        )
    return "\n".join(lines) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", required=True, type=Path)
    parser.add_argument("--sizes", nargs="+", default=list(DEFAULT_SIZES))
    parser.add_argument("--layouts", nargs="+", default=["scroll", "split"])
    parser.add_argument("--docks", nargs="+", default=["expanded", "collapsed"])
    parser.add_argument(
        "--states", nargs="+", default=["fresh", "primed"], choices=["fresh", "primed"]
    )
    parser.add_argument("--theme", default="blue-modern")
    parser.add_argument("--scale", type=float, default=1.0)
    parser.add_argument(
        "--offscreen", action="store_true", help="headless; text metrics are NOT representative"
    )
    parser.add_argument("--name", default="layout_audit")
    args = parser.parse_args()
    if args.offscreen:
        os.environ["QT_QPA_PLATFORM"] = "offscreen"
    if args.scale != 1.0:
        os.environ["QT_SCALE_FACTOR"] = str(args.scale)
    sys.path.insert(0, str(ROOT))
    rows = run(args.sizes, args.layouts, args.docks, args.states, args.theme)
    from PySide6.QtGui import QGuiApplication

    screen = QGuiApplication.primaryScreen()
    meta = {
        "theme": args.theme,
        "qpa": QGuiApplication.platformName(),
        "scale": args.scale,
        "python": platform.python_version(),
        "os": platform.platform(),
        "platform_note": "headless, not representative" if args.offscreen else "native platform",
        "screen": None
        if screen is None
        else {
            "name": screen.name(),
            "geometry": [screen.geometry().width(), screen.geometry().height()],
            "devicePixelRatio": screen.devicePixelRatio(),
            "logicalDpi": screen.logicalDotsPerInch(),
        },
    }
    args.out.mkdir(parents=True, exist_ok=True)
    (args.out / f"{args.name}.json").write_text(
        json.dumps({"meta": meta, "rows": rows}, indent=2), encoding="utf-8"
    )
    (args.out / f"{args.name}.md").write_text(markdown(rows, meta), encoding="utf-8")
    sys.stdout.reconfigure(encoding="utf-8")  # the table contains arrows and multiplication signs
    print(markdown(rows, meta))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
