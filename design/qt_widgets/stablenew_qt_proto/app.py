"""Run: python -m stablenew_qt_proto.app

Standalone demonstration. No StableNew production imports or side effects.
"""

from __future__ import annotations

import sys
from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QAction
from PySide6.QtWidgets import (
    QApplication, QHBoxLayout, QLabel, QListWidget, QMainWindow, QPushButton,
    QSplitter, QStackedWidget, QVBoxLayout, QWidget,
)

from .create_view import CreateView
from .gallery import ComponentGallery
from .output_display import OutputDock
from .output_model import SIZE_FILL, fill_width, frame_from_session
from .tokens import SPACE, make_stylesheet

WORKSPACE_MIN_WIDTH = 880   # Create workspace (nav + form + review) never gets narrower than this
WORKSPACE_FILL_WIDTH = 900  # width the workspace keeps while the Output Display is in Fill mode


class PrototypeWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("StableNew · Independent Qt Widgets Assessment")
        self.resize(1440, 900)
        # Height is explicit; the minimum width comes from the layout (workspace + Output Display).
        self.setMinimumHeight(600)
        shell = QWidget()
        shell.setMinimumWidth(WORKSPACE_MIN_WIDTH)
        self.setCentralWidget(shell)
        root = QVBoxLayout(shell)
        root.setContentsMargins(SPACE.sm, SPACE.sm, SPACE.sm, SPACE.sm)
        root.setSpacing(SPACE.sm)
        header = QHBoxLayout()
        product = QLabel("StableNew  /  Qt Widgets Assessment")
        product.setProperty("role", "heading")
        header.addWidget(product)
        header.addStretch(1)
        self.output_toggle = QPushButton("Output Display")
        self.output_toggle.setCheckable(True)
        self.output_toggle.setChecked(True)
        self.output_toggle.setProperty("role", "segment")
        self.output_toggle.setMinimumWidth(150)
        self.output_toggle.setToolTip("Show or collapse the Output Display (Ctrl+3)")
        self.output_toggle.setAccessibleName("Output Display visible")
        header.addWidget(self.output_toggle)
        capsule = QLabel("ISOLATED DEMO · NO GPU · NO BACKEND · NO WRITES")
        capsule.setProperty("role", "capsule")
        header.addWidget(capsule)
        root.addLayout(header)
        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.setChildrenCollapsible(False)
        root.addWidget(splitter, 1)
        self.nav = QListWidget()
        self.nav.setProperty("role", "nav")
        self.nav.addItems(["Create Image", "Component Library"])
        self.nav.setMaximumWidth(240)
        self.nav.setMinimumWidth(184)
        self.nav.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.nav.setAccessibleName("Prototype navigation")
        splitter.addWidget(self.nav)
        self.pages = QStackedWidget()
        self.create_view = CreateView()
        self.pages.addWidget(self.create_view)
        self.pages.addWidget(ComponentGallery())
        splitter.addWidget(self.pages)
        splitter.setSizes([185, 1200])
        self.nav.currentRowChanged.connect(self.pages.setCurrentIndex)
        self.nav.setCurrentRow(0)
        self.statusBar().showMessage("Prototype uses demonstration fixtures only; all settings and receipts are in memory.")
        self.statusBar().setSizeGripEnabled(True)
        shortcut = QAction("Switch to Create", self)
        shortcut.setShortcut("Ctrl+1")
        shortcut.triggered.connect(lambda: self.nav.setCurrentRow(0))
        self.addAction(shortcut)
        gallery = QAction("Switch to Library", self)
        gallery.setShortcut("Ctrl+2")
        gallery.triggered.connect(lambda: self.nav.setCurrentRow(1))
        self.addAction(gallery)
        self._build_output_display()

    # ---------------------------------------------------------- Output Display
    def _build_output_display(self) -> None:
        self.output_dock = OutputDock(self)
        self.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, self.output_dock)
        self.output_dock.set_fill_callback(self.apply_output_fill)
        self.create_view.stateSynced.connect(self._refresh_output)
        self._refresh_output()
        self.output_toggle.toggled.connect(lambda shown: self.output_dock.set_collapsed(not shown))
        self.output_dock.collapsedChanged.connect(self._sync_output_toggle)
        toggle = QAction("Toggle Output Display", self)
        toggle.setShortcut("Ctrl+3")
        toggle.setShortcutContext(Qt.ShortcutContext.ApplicationShortcut)
        toggle.triggered.connect(self.output_toggle.toggle)
        self.addAction(toggle)
        self._initial_dock_sized = False

    def _refresh_output(self) -> None:
        self.output_dock.set_frame(frame_from_session(self.create_view.session))

    def _sync_output_toggle(self, collapsed: bool) -> None:
        self.output_toggle.blockSignals(True)
        self.output_toggle.setChecked(not collapsed)
        self.output_toggle.blockSignals(False)

    def apply_output_fill(self) -> None:
        """Fill mode: docked, give the display all width the workspace does not need;
        floating, cover the screen's work area. Re-run on every window resize."""
        dock = self.output_dock
        if dock.size_mode != SIZE_FILL or dock.collapsed:
            return
        if dock.isFloating():
            screen = dock.screen() or self.screen()
            if screen is not None:
                dock.fill_floating(screen.availableGeometry())
        else:
            width = fill_width(self.width(), WORKSPACE_FILL_WIDTH, dock.MIN_EXPANDED_WIDTH)
            self.resizeDocks([dock], [width], Qt.Orientation.Horizontal)

    def showEvent(self, event) -> None:  # noqa: N802 (Qt API)
        super().showEvent(event)
        if not self._initial_dock_sized:
            self._initial_dock_sized = True
            QTimer.singleShot(0, self._size_dock_initially)

    def _size_dock_initially(self) -> None:
        if not self.output_dock.isFloating() and not self.output_dock.collapsed:
            self.resizeDocks([self.output_dock], [self.output_dock.DEFAULT_WIDTH], Qt.Orientation.Horizontal)
        self.apply_output_fill()

    def resizeEvent(self, event) -> None:  # noqa: N802 (Qt API)
        super().resizeEvent(event)
        if hasattr(self, "output_dock"):
            self.apply_output_fill()


def apply_theme(app: QApplication) -> None:
    app.setStyle("Fusion")
    app.setStyleSheet(make_stylesheet())


def main(argv: list[str] | None = None) -> int:
    app = QApplication(list(sys.argv if argv is None else argv))
    app.setApplicationName("StableNew Qt Design Assessment (isolated)")
    apply_theme(app)
    window = PrototypeWindow()
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
