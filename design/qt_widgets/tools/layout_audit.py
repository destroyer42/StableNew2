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


def run_edit(sizes: list[str], layouts: list[str], theme_id: str) -> list[dict]:
    from PySide6.QtCore import QEvent
    from PySide6.QtWidgets import QApplication
    from stablenew_qt_proto.app import PrototypeWindow, apply_theme
    from stablenew_qt_proto.layout_probe import prime_edit, probe_edit, pump
    from stablenew_qt_proto.tokens import reference_theme

    app = QApplication.instance() or QApplication([])
    apply_theme(app, reference_theme(theme_id))
    rows = []
    for size in sizes:
        width, height = map(int, size.split("x"))
        for layout in layouts:
            window = PrototypeWindow(edit_layout=layout)
            prime_edit(window, (width, height))
            row = probe_edit(window)
            row["requested_size"] = size
            rows.append(row)
            window.close()
            window.deleteLater()
            QApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
            pump(app, 2)
    return rows


def run_motion(
    sizes: list[str], layouts: list[str], states: list[str], theme_id: str
) -> list[dict]:
    from PySide6.QtCore import QEvent
    from PySide6.QtWidgets import QApplication
    from stablenew_qt_proto.app import PrototypeWindow, apply_theme
    from stablenew_qt_proto.layout_probe import prime_motion, probe_motion, pump
    from stablenew_qt_proto.tokens import reference_theme

    app = QApplication.instance() or QApplication([])
    apply_theme(app, reference_theme(theme_id))
    rows = []
    for size in sizes:
        width, height = map(int, size.split("x"))
        for state in states:
            for layout in layouts if state == "story" else ["strip"]:
                window = PrototypeWindow()
                prime_motion(window, (width, height), state, layout)
                row = probe_motion(window)
                row["requested_size"] = size
                row["theme"] = theme_id
                row["size_clamped"] = [window.width(), window.height()] != [width, height]
                rows.append(row)
                window.close()
                window.deleteLater()
                QApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
                pump(app, 2)
    return rows


def motion_markdown(rows: list[dict], meta: dict) -> str:
    lines = [
        f"# Motion layout audit ({meta['platform_note']})",
        "",
        f"Theme `{meta['theme']}` · Qt platform `{meta['qpa']}` · requested scale {meta['scale']} · "
        f"screen DPR {meta['screen']['devicePixelRatio']} · Python {meta['python']}",
        "",
        "| Mode | Layout | Requested → actual | Viewer | Inspector | Cards unscrolled | Clipped | Page scroll | Overflow | Shrunk | Tab stops · missing |",
        "|---|---|---|---|---|---|---|---|---|---|---|",
    ]
    for r in rows:
        width, height = r["window"]
        cards = f"{r['shot_cards_visible_unscrolled']}/{r['shots']}" if "shots" in r else "-"
        viewer = "x".join(map(str, r["viewer"])) if "viewer" in r else "-"
        inspector = "x".join(map(str, r["inspector"])) if "inspector" in r else "-"
        over = ", ".join(f"{k} {v}px" for k, v in r["horizontal_overflow_px"].items()) or "none"
        lines.append(
            f"| {r['mode']} | {r['layout']} | {r['requested_size']} → {width}×{height}"
            f"{' (clamped)' if r['size_clamped'] else ''} | {viewer} | {inspector} | {cards} | "
            f"{', '.join(r['clipped']) or 'none'} | {r['page_scroll_px']} px | {over} | {len(r['shrunk_controls'])} | "
            f"{r['tab_stops']} · {', '.join(r['missing_tab_stops']) or 'none'} |"
        )
    return "\n".join(lines) + "\n"


def edit_markdown(rows: list[dict], meta: dict) -> str:
    lines = [
        f"# Edit layout audit ({meta['platform_note']})",
        "",
        f"Theme `{meta['theme']}` · Qt platform `{meta['qpa']}` · requested scale {meta['scale']} · "
        f"screen DPR {meta['screen']['devicePixelRatio']} · Python {meta['python']}",
        "",
        "| Layout | Requested → actual client | Canvas | Inspector | Scroll to advanced | Clipped | Horizontal overflow | Tab stops · missing | Preview |",
        "|---|---|---|---|---|---|---|---|---|",
    ]
    for r in rows:
        width, height = r["window"]
        lines.append(
            f"| {r['layout']} | {r['requested_size']} → {width}×{height} | "
            f"{r['canvas'][0]}×{r['canvas'][1]} | {r['inspector_viewport'][0]}×{r['inspector_viewport'][1]} | "
            f"{r['settings_scroll_px']['advanced']} px | "
            f"{', '.join(r['clipped']) or 'none'} | {r['horizontal_overflow_px']} px | "
            f"{r['tab_stops']} · {', '.join(r['missing_tab_stops']) or 'none'} | {r['preview']} |"
        )
    return "\n".join(lines) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", required=True, type=Path)
    parser.add_argument("--sizes", nargs="+", default=list(DEFAULT_SIZES))
    parser.add_argument("--layouts", nargs="+", default=["scroll", "split"])
    parser.add_argument("--edit-layouts", nargs="+", choices=["editor", "inspector"])
    parser.add_argument("--motion-layouts", nargs="+", choices=["strip", "timeline"])
    parser.add_argument(
        "--motion-states", nargs="+", default=["story"], choices=["quick", "story", "movie"]
    )
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
    if args.motion_layouts:
        rows = run_motion(args.sizes, args.motion_layouts, args.motion_states, args.theme)
    elif args.edit_layouts:
        rows = run_edit(args.sizes, args.edit_layouts, args.theme)
    else:
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
    if args.scale != 1.0:
        meta["platform_note"] += ", simulated scaling"
    if args.motion_layouts:
        report = motion_markdown(rows, meta)
    else:
        report = edit_markdown(rows, meta) if args.edit_layouts else markdown(rows, meta)
    args.out.mkdir(parents=True, exist_ok=True)
    (args.out / f"{args.name}.json").write_text(
        json.dumps({"meta": meta, "rows": rows}, indent=2), encoding="utf-8"
    )
    (args.out / f"{args.name}.md").write_text(report, encoding="utf-8")
    sys.stdout.reconfigure(encoding="utf-8")  # the table contains arrows and multiplication signs
    print(report)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
