"""Capture layout evidence (PNG + measurements) from the isolated prototype.

Usage (from the package root, with the Qt interpreter):

    python tools/capture.py --out captures --sizes 1280x680 1440x900
    python tools/capture.py --out captures --sizes 1280x680 --scale 1.5

Writes PNGs only into ``--out``. Use the default (native) platform for real
fonts; ``--offscreen`` is for headless runs and renders text as boxes on
machines without fonts. Nothing else is written; no StableNew code is imported.
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", required=True, type=Path, help="directory for PNG output (created)")
    parser.add_argument("--sizes", nargs="+", default=["1280x680", "1440x900"])
    parser.add_argument("--scale", type=float, default=1.0, help="QT_SCALE_FACTOR to emulate display scaling")
    parser.add_argument("--offscreen", action="store_true")
    args = parser.parse_args()

    if args.offscreen:
        os.environ["QT_QPA_PLATFORM"] = "offscreen"
    if args.scale != 1.0:
        os.environ["QT_SCALE_FACTOR"] = str(args.scale)
    sys.path.insert(0, str(ROOT))

    from PySide6.QtWidgets import QApplication

    from stablenew_qt_proto.app import PrototypeWindow, apply_theme

    args.out.mkdir(parents=True, exist_ok=True)
    app = QApplication([])
    apply_theme(app)
    suffix = f"@{args.scale:g}x" if args.scale != 1.0 else ""
    for size in args.sizes:
        width, height = (int(part) for part in size.split("x"))
        window = PrototypeWindow()
        window.resize(width, height)
        window.show()
        app.processEvents()
        if width < 1200:  # an expanded Output Display needs ~1192 px; small windows use the collapsed rail
            window.output_dock.set_collapsed(True)
            for _ in range(6):
                app.processEvents()
        view = window.pages.widget(0)
        bar = view.form_scroll.verticalScrollBar()
        tag = f"{size}{suffix}"
        print(
            f"{tag}: form viewport {view.form_scroll.viewport().width()}x{view.form_scroll.viewport().height()}, "
            f"content {view.form_scroll.widget().width()}x{view.form_scroll.widget().height()}, "
            f"settings columns {view.settings_grid.columns}, "
            f"footer bottom {view.actions.mapTo(window, view.actions.rect().bottomLeft()).y()} / window {window.height()}"
        )
        window.grab().save(str(args.out / f"create_{tag}_top.png"))
        bar.setValue(bar.maximum() // 2)
        app.processEvents()
        window.grab().save(str(args.out / f"create_{tag}_middle.png"))
        bar.setValue(bar.maximum())
        app.processEvents()
        window.grab().save(str(args.out / f"create_{tag}_bottom.png"))
        bar.setValue(0)
        view.session.switch_model("fixture-flux")  # demonstrate a blocked, explained state
        view._sync_view()
        view._build_preview()
        app.processEvents()
        window.grab().save(str(args.out / f"create_{tag}_blocked.png"))
        window.nav.setCurrentRow(1)
        app.processEvents()
        window.grab().save(str(args.out / f"library_{tag}.png"))
        window.close()
        capture_dock(app, args.out, width, height, tag)
    return 0


def capture_dock(app, out: Path, width: int, height: int, tag: str) -> None:
    """Output Display states: docked, zoomed, Fill, collapsed rail, floating (and floating-collapsed)."""
    from PySide6.QtCore import Qt

    from stablenew_qt_proto.app import PrototypeWindow
    from stablenew_qt_proto.output_model import SIZE_FILL, SIZE_FREE

    def pump() -> None:
        for _ in range(6):
            app.processEvents()

    window = PrototypeWindow()
    window.resize(width, height)
    window.show()
    pump()
    dock = window.output_dock
    view = window.pages.widget(0)
    print(
        f"{tag} dock: width {dock.width()}, viewer {dock.view.viewport().width()}x{dock.view.viewport().height()}, "
        f"fit zoom {dock.view.zoom:.2f}, window min width {window.minimumSizeHint().width()}"
    )
    window.grab().save(str(out / f"dock_{tag}_expanded.png"))
    view.preview_button.click()
    dock.view.zoom_to(1.0)
    pump()
    window.grab().save(str(out / f"dock_{tag}_zoom100_preview.png"))
    dock.view.fit()
    dock.set_size_mode(SIZE_FILL)
    window.resize(max(width, 1700), height)
    pump()
    window.grab().save(str(out / f"dock_{tag}_fill.png"))
    dock.set_size_mode(SIZE_FREE)
    dock.set_collapsed(True)
    pump()
    window.grab().save(str(out / f"dock_{tag}_collapsed.png"))
    dock.set_collapsed(False)
    dock.setFloating(True)
    pump()
    dock.grab().save(str(out / f"dock_{tag}_floating.png"))
    dock.set_collapsed(True)
    pump()
    dock.grab().save(str(out / f"dock_{tag}_floating_collapsed.png"))
    dock.set_collapsed(False)
    dock.setFloating(False)
    pump()
    assert window.dockWidgetArea(dock) == Qt.DockWidgetArea.RightDockWidgetArea
    window.close()


if __name__ == "__main__":
    raise SystemExit(main())
