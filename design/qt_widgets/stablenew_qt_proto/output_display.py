"""Output Display: a dockable, collapsible, resizable, zoomable preview window.

The display shows a *placeholder frame* derived from the Create draft (size,
resolved prompt, preview state). It never shows a generated image: this
prototype has no runtime. All state is in memory.

Size modes
----------
* **Free**   – drag the dock edge (or float it and resize the window).
* **Locked** – the width (docked) or size (floating) is frozen until unlocked.
* **Fill**   – docked: takes every pixel the Create workspace does not need and
  follows the window as it resizes; floating: fills the screen's work area.
"""

from __future__ import annotations

import html

from PySide6.QtCore import QPointF, QRectF, QSize, Qt, QTimer, Signal
from PySide6.QtGui import (
    QAction, QBrush, QColor, QKeySequence, QLinearGradient, QPainter, QPainterPath, QPen, QTransform,
)
from PySide6.QtWidgets import (
    QButtonGroup, QDockWidget, QFrame, QGraphicsScene, QGraphicsView, QGraphicsTextItem, QHBoxLayout,
    QLabel, QMainWindow, QPushButton, QSlider, QToolButton, QVBoxLayout, QWidget,
)

from .components import repolish
from .output_model import (
    SIZE_FILL, SIZE_FREE, SIZE_LOCKED, SIZE_MODES, SLIDER_STEPS, ZOOM_CUSTOM, ZOOM_FIT, ZOOM_STEP,
    OutputFrame, clamp_zoom, fit_factor, format_zoom, slider_to_zoom, step_zoom, zoom_to_slider,
)
from .tokens import COLORS, SPACE

QWIDGETSIZE_MAX = 16777215
_MODE_LABELS = {SIZE_FREE: "Free", SIZE_LOCKED: "Lock size", SIZE_FILL: "Fill"}
_MODE_TIPS = {
    SIZE_FREE: "Free: drag the dock edge (or the floating window edge) to resize.",
    SIZE_LOCKED: "Lock size: freeze the current docked width, or the floating window size, until unlocked.",
    SIZE_FILL: "Fill: docked, take all space the Create workspace does not need; floating, fill the screen.",
}
_KIND_COLORS = {"draft": COLORS.muted, "preview": COLORS.success, "stale": COLORS.accent, "receipt": COLORS.success}


# ----------------------------------------------------------------------- viewer
class ZoomView(QGraphicsView):
    """Vector placeholder viewer with fit / 100% / custom zoom, Ctrl+wheel and pan."""

    zoomChanged = Signal(float, str)  # factor, ZOOM_FIT | ZOOM_CUSTOM

    FIT_PADDING = 0.03  # fraction of the long edge kept as scene padding

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setProperty("role", "viewer")
        self._scene = QGraphicsScene(self)
        self.setScene(self._scene)
        self.setDragMode(QGraphicsView.DragMode.ScrollHandDrag)
        self.setRenderHints(
            QPainter.RenderHint.Antialiasing | QPainter.RenderHint.TextAntialiasing
            | QPainter.RenderHint.SmoothPixmapTransform
        )
        self.setBackgroundBrush(QBrush(QColor(COLORS.field)))
        self.setTransformationAnchor(QGraphicsView.ViewportAnchor.AnchorViewCenter)
        self.setResizeAnchor(QGraphicsView.ViewportAnchor.AnchorViewCenter)
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setMinimumSize(160, 140)
        self.setAccessibleName("Output display viewer")
        self.setToolTip("Ctrl+wheel zooms at the pointer · drag to pan · double-click toggles Fit / 100%")
        self._frame: OutputFrame | None = None
        self._zoom = 1.0
        self._mode = ZOOM_FIT
        self._set_scrollbars()

    # ---------------------------------------------------------------- properties
    @property
    def zoom(self) -> float:
        return self._zoom

    @property
    def mode(self) -> str:
        return self._mode

    @property
    def frame_content(self) -> OutputFrame | None:
        return self._frame

    # ---------------------------------------------------------------- zoom API
    def fit(self) -> None:
        self._mode = ZOOM_FIT
        self._set_scrollbars()
        self._apply(self._fit_zoom(), ZOOM_FIT)

    def actual_size(self) -> None:
        self.zoom_to(1.0)

    def zoom_to(self, zoom: float) -> None:
        self._mode = ZOOM_CUSTOM
        self._set_scrollbars()
        self._apply(zoom, ZOOM_CUSTOM)

    def zoom_in(self) -> None:
        self.zoom_to(step_zoom(self._zoom, +1))

    def zoom_out(self) -> None:
        self.zoom_to(step_zoom(self._zoom, -1))

    def toggle_fit(self) -> None:
        self.actual_size() if self._mode == ZOOM_FIT else self.fit()

    def _fit_zoom(self) -> float:
        rect = self.sceneRect()
        return fit_factor(self.viewport().width(), self.viewport().height(), rect.width(), rect.height())

    def _apply(self, zoom: float, mode: str) -> None:
        zoom = clamp_zoom(zoom)
        self._zoom = zoom
        self.setTransform(QTransform.fromScale(zoom, zoom))
        self.zoomChanged.emit(zoom, mode)

    def _set_scrollbars(self) -> None:
        policy = Qt.ScrollBarPolicy.ScrollBarAlwaysOff if self._mode == ZOOM_FIT else Qt.ScrollBarPolicy.ScrollBarAsNeeded
        self.setHorizontalScrollBarPolicy(policy)
        self.setVerticalScrollBarPolicy(policy)

    # ------------------------------------------------------------------ events
    def resizeEvent(self, event) -> None:  # noqa: N802 (Qt API)
        super().resizeEvent(event)
        if self._mode == ZOOM_FIT:
            self._apply(self._fit_zoom(), ZOOM_FIT)

    def wheelEvent(self, event) -> None:  # noqa: N802 (Qt API)
        if event.modifiers() & Qt.KeyboardModifier.ControlModifier:
            delta = event.angleDelta().y()
            if delta:
                self._mode = ZOOM_CUSTOM
                self._set_scrollbars()
                self.setTransformationAnchor(QGraphicsView.ViewportAnchor.AnchorUnderMouse)
                self._apply(self._zoom * ZOOM_STEP ** (delta / 120.0), ZOOM_CUSTOM)
                self.setTransformationAnchor(QGraphicsView.ViewportAnchor.AnchorViewCenter)
            event.accept()
            return
        super().wheelEvent(event)  # plain wheel scrolls when zoomed in, else propagates

    def mouseDoubleClickEvent(self, event) -> None:  # noqa: N802 (Qt API)
        self.toggle_fit()
        event.accept()

    # ------------------------------------------------------------------- scene
    def set_frame(self, frame: OutputFrame) -> None:
        if frame == self._frame:
            return
        self._frame = frame
        self._build_scene(frame)
        if self._mode == ZOOM_FIT:
            self._apply(self._fit_zoom(), ZOOM_FIT)
        else:
            self.zoomChanged.emit(self._zoom, self._mode)
        self.setAccessibleDescription(f"{frame.title}, {frame.dimensions}. No image generated.")

    def _build_scene(self, frame: OutputFrame) -> None:
        scene = self._scene
        scene.clear()
        w, h = float(frame.width), float(frame.height)
        pad = max(w, h) * self.FIT_PADDING
        scene.setSceneRect(QRectF(-pad, -pad, w + 2 * pad, h + 2 * pad))
        radius = min(w, h) * 0.02
        outline = QPainterPath()
        outline.addRoundedRect(QRectF(0, 0, w, h), radius, radius)
        gradient = QLinearGradient(0, 0, w, h)
        gradient.setColorAt(0.0, QColor(COLORS.selected))
        gradient.setColorAt(1.0, QColor(COLORS.surface))
        scene.addPath(outline, QPen(Qt.PenStyle.NoPen), QBrush(gradient))

        def cosmetic(color: QColor, width: int = 1, style: Qt.PenStyle = Qt.PenStyle.SolidLine) -> QPen:
            pen = QPen(color, width, style)
            pen.setCosmetic(True)  # constant on-screen thickness at any zoom
            return pen

        grid = cosmetic(QColor(255, 255, 255, 30))
        step = 64.0
        x = step
        while x < w:
            scene.addLine(x, 0, x, h, grid)
            x += step
        y = step
        while y < h:
            scene.addLine(0, y, w, y, grid)
            y += step
        diag = cosmetic(QColor(255, 255, 255, 46))
        scene.addLine(0, 0, w, h, diag)
        scene.addLine(w, 0, 0, h, diag)

        color = QColor(_KIND_COLORS[frame.kind])
        # State is carried by line style and words as well as colour.
        style = Qt.PenStyle.DashLine if frame.kind in ("draft", "stale") else Qt.PenStyle.SolidLine
        scene.addPath(outline, cosmetic(color, 3, style), QBrush(Qt.BrushStyle.NoBrush))

        base = max(12.0, min(w, h) / 26.0)
        prompt = frame.lines[0] if frame.lines else ""
        prompt = (prompt[:200] + "…") if len(prompt) > 200 else prompt
        body = "<br>".join(html.escape(line) for line in ((prompt,) + tuple(frame.lines[1:])))
        text = QGraphicsTextItem()
        text.setHtml(
            f"<div style='text-align:center; color:{COLORS.text};'>"
            f"<div style='font-size:{base * 1.1:.1f}px; font-weight:bold; color:{color.name()};'>{html.escape(frame.title)}</div>"
            f"<div style='font-size:{base * 2.4:.1f}px; font-weight:bold;'>{html.escape(frame.dimensions)}</div>"
            f"<div style='font-size:{base:.1f}px; color:{COLORS.muted};'>{body}</div></div>"
        )
        text.setTextWidth(w * 0.84)
        text.setPos((w - text.boundingRect().width()) / 2, max(0.0, (h - text.boundingRect().height()) / 2))
        scene.addItem(text)


# -------------------------------------------------------------------- chrome
class _RailLabel(QWidget):
    """Vertical text shown while the dock is collapsed to a rail."""

    def __init__(self, text: str, parent: QWidget | None = None):
        super().__init__(parent)
        self._text = text

    def sizeHint(self) -> QSize:  # noqa: N802 (Qt API)
        return QSize(28, 160)

    def paintEvent(self, _event) -> None:  # noqa: N802 (Qt API)
        painter = QPainter(self)
        painter.setPen(QColor(COLORS.muted))
        font = painter.font()
        font.setBold(True)
        painter.setFont(font)
        painter.translate(self.width() / 2.0, 8)
        painter.rotate(90)
        painter.drawText(QPointF(0, font.pointSizeF() / 2.0 + 2), self._text)


class DockTitleBar(QFrame):
    """Custom title bar: draggable (empty space falls through to the dock)."""

    def __init__(self, dock: "OutputDock"):
        super().__init__(dock)
        self.setProperty("role", "dockbar")
        row = QHBoxLayout(self)
        row.setContentsMargins(SPACE.md, SPACE.xs, SPACE.sm, SPACE.xs)
        row.setSpacing(SPACE.xs)
        self.title = QLabel("Output Display")
        self.title.setProperty("role", "section")
        row.addWidget(self.title)
        row.addStretch(1)
        self.float_button = QToolButton()
        self.float_button.setProperty("role", "zoom")
        self.float_button.setText("Undock")
        self.float_button.setAccessibleName("Undock or dock the Output Display")
        self.collapse_button = QToolButton()
        self.collapse_button.setProperty("role", "zoom")
        self.collapse_button.setProperty("glyph", "true")
        self.collapse_button.setAccessibleName("Collapse or expand the Output Display")
        row.addWidget(self.float_button)
        row.addWidget(self.collapse_button)
        self.float_button.clicked.connect(lambda: dock.setFloating(not dock.isFloating()))
        self.collapse_button.clicked.connect(lambda: dock.set_collapsed(not dock.collapsed))
        self.setMinimumHeight(40)


class OutputPanel(QFrame):
    """Dock body: size-mode selector, viewer, zoom controls, status line."""

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setProperty("role", "card")
        col = QVBoxLayout(self)
        col.setContentsMargins(SPACE.md, SPACE.md, SPACE.md, SPACE.md)
        col.setSpacing(SPACE.sm)

        mode_row = QHBoxLayout()
        mode_row.setSpacing(SPACE.xs)
        self.mode_group = QButtonGroup(self)
        self.mode_group.setExclusive(True)
        self.mode_buttons: dict[str, QPushButton] = {}
        for mode in SIZE_MODES:
            button = QPushButton(_MODE_LABELS[mode])
            button.setProperty("role", "segment")
            button.setCheckable(True)
            button.setToolTip(_MODE_TIPS[mode])
            button.setAccessibleName(f"Output size mode: {_MODE_LABELS[mode]}")
            self.mode_group.addButton(button)
            self.mode_buttons[mode] = button
            mode_row.addWidget(button)
        mode_row.addStretch(1)
        col.addLayout(mode_row)
        self.mode_hint = QLabel("")
        self.mode_hint.setProperty("role", "muted")
        self.mode_hint.setWordWrap(True)
        col.addWidget(self.mode_hint)

        self.view = ZoomView()
        col.addWidget(self.view, 1)

        zoom_row = QHBoxLayout()
        zoom_row.setSpacing(SPACE.xs)
        self.zoom_out_button = self._zoom_button("−", "Zoom out (Ctrl+−)")
        self.zoom_in_button = self._zoom_button("+", "Zoom in (Ctrl+=)")
        self.slider = QSlider(Qt.Orientation.Horizontal)
        self.slider.setRange(0, SLIDER_STEPS)
        self.slider.setAccessibleName("Zoom level")
        self.slider.setMinimumWidth(70)
        self.actual_button = self._zoom_button("100%", "Actual size (Ctrl+0)")
        self.fit_button = self._zoom_button("Fit", "Fit the whole frame (Ctrl+9)")
        self.fit_button.setCheckable(True)
        for widget in (self.zoom_out_button, self.slider, self.zoom_in_button, self.actual_button, self.fit_button):
            zoom_row.addWidget(widget, 1 if widget is self.slider else 0)
        col.addLayout(zoom_row)

        self.status = QLabel("")
        self.status.setProperty("role", "muted")
        self.status.setWordWrap(True)
        col.addWidget(self.status)

        self.zoom_out_button.clicked.connect(self.view.zoom_out)
        self.zoom_in_button.clicked.connect(self.view.zoom_in)
        self.actual_button.clicked.connect(self.view.actual_size)
        self.fit_button.clicked.connect(self.view.fit)
        self.slider.valueChanged.connect(self._slider_moved)
        self.view.zoomChanged.connect(self._zoom_changed)
        self._zoom_changed(self.view.zoom, self.view.mode)

    @staticmethod
    def _zoom_button(text: str, tip: str) -> QToolButton:
        button = QToolButton()
        button.setProperty("role", "zoom")
        if text in ("−", "+"):
            button.setProperty("glyph", "true")
        button.setText(text)
        button.setToolTip(tip)
        button.setAccessibleName(tip.split(" (")[0])
        return button

    def _slider_moved(self, value: int) -> None:
        if self.slider.signalsBlocked():
            return
        self.view.zoom_to(slider_to_zoom(value))

    def _zoom_changed(self, zoom: float, mode: str) -> None:
        self.slider.blockSignals(True)
        self.slider.setValue(zoom_to_slider(zoom))
        self.slider.blockSignals(False)
        self.fit_button.setChecked(mode == ZOOM_FIT)
        self.zoom_in_button.setEnabled(zoom < 16.0 - 1e-9)
        self.zoom_out_button.setEnabled(zoom > 0.05 + 1e-9)
        self.refresh_status()

    def refresh_status(self) -> None:
        frame = self.view.frame_content
        suffix = " (Fit)" if self.view.mode == ZOOM_FIT else ""
        zoom = f"{format_zoom(self.view.zoom)}{suffix}"
        if frame is None:
            self.status.setText(f"Zoom {zoom}")
        else:
            self.status.setText(f"{frame.title.title()} · {frame.dimensions} · zoom {zoom} · placeholder, no image")


# ----------------------------------------------------------------------- dock
class OutputDock(QDockWidget):
    """The Output Display dock. Constraints are derived from three pieces of state:
    ``collapsed``, ``size_mode`` and docked/floating, in ``refresh_constraints``."""

    sizeModeChanged = Signal(str)
    collapsedChanged = Signal(bool)

    RAIL_WIDTH = 56
    MIN_EXPANDED_WIDTH = 300
    DEFAULT_WIDTH = 380

    def __init__(self, parent: QWidget | None = None):
        super().__init__("Output Display", parent)
        self.setObjectName("OutputDock")
        self.setAllowedAreas(Qt.DockWidgetArea.LeftDockWidgetArea | Qt.DockWidgetArea.RightDockWidgetArea)
        self.setFeatures(QDockWidget.DockWidgetFeature.DockWidgetMovable | QDockWidget.DockWidgetFeature.DockWidgetFloatable)
        self.setAccessibleName("Output Display")
        self._size_mode = SIZE_FREE
        self._collapsed = False
        self._restore_width = self.DEFAULT_WIDTH     # docked width to return to
        self._locked_width = self.DEFAULT_WIDTH
        self._locked_size = QSize(520, 560)           # floating size when locked
        self._float_geometry = None                   # saved before Fill takes the screen
        self._fill_callback = None

        self.title_bar = DockTitleBar(self)
        self.setTitleBarWidget(self.title_bar)
        self.panel = OutputPanel()
        self.rail = _RailLabel("OUTPUT DISPLAY")
        self.rail.hide()
        body = QWidget()
        col = QVBoxLayout(body)
        col.setContentsMargins(0, SPACE.sm, 0, 0)
        col.setSpacing(0)
        col.addWidget(self.panel, 1)
        col.addWidget(self.rail, 1, Qt.AlignmentFlag.AlignHCenter)
        self.setWidget(body)

        for mode, button in self.panel.mode_buttons.items():
            button.clicked.connect(lambda _checked=False, m=mode: self.set_size_mode(m))
        self.panel.mode_buttons[SIZE_FREE].setChecked(True)
        self.topLevelChanged.connect(self._on_top_level_changed)
        self.dockLocationChanged.connect(lambda _area: self._sync_chrome())
        self._add_zoom_actions()
        self._sync_chrome()
        self.refresh_constraints()

    # ---------------------------------------------------------------- properties
    @property
    def size_mode(self) -> str:
        return self._size_mode

    @property
    def collapsed(self) -> bool:
        return self._collapsed

    @property
    def view(self) -> ZoomView:
        return self.panel.view

    def set_fill_callback(self, callback) -> None:
        """Window-level fill logic (needs the window width); called after state changes."""
        self._fill_callback = callback

    def set_frame(self, frame: OutputFrame) -> None:
        self.panel.view.set_frame(frame)
        self.panel.refresh_status()

    # ------------------------------------------------------------------ actions
    def _add_zoom_actions(self) -> None:
        for label, keys, slot in (
            ("Output: zoom in", ("Ctrl+=", "Ctrl++"), self.panel.view.zoom_in),
            ("Output: zoom out", ("Ctrl+-",), self.panel.view.zoom_out),
            ("Output: actual size", ("Ctrl+0",), self.panel.view.actual_size),
            ("Output: fit", ("Ctrl+9",), self.panel.view.fit),
        ):
            action = QAction(label, self)
            action.setShortcuts([QKeySequence(k) for k in keys])
            action.setShortcutContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
            action.triggered.connect(slot)
            self.addAction(action)

    # -------------------------------------------------------------------- state
    def set_size_mode(self, mode: str) -> None:
        if mode not in SIZE_MODES:
            raise ValueError(f"Unknown size mode: {mode}")
        previous = self._size_mode
        if mode == SIZE_LOCKED and previous != SIZE_LOCKED:
            if self._collapsed:
                self._locked_width = self._restore_width
            else:
                self._locked_width = max(self.MIN_EXPANDED_WIDTH, self.width())
                self._locked_size = self.size()
        if previous == SIZE_FILL and mode != SIZE_FILL and self.isFloating() and self._float_geometry is not None:
            self.setGeometry(self._float_geometry)
            self._float_geometry = None
        self._size_mode = mode
        self.panel.mode_buttons[mode].setChecked(True)
        self.refresh_constraints()
        if previous != mode:
            self.sizeModeChanged.emit(mode)
        self._run_fill()

    def set_collapsed(self, collapsed: bool) -> None:
        if collapsed == self._collapsed:
            return
        if collapsed and not self.isFloating():
            self._restore_width = max(self.MIN_EXPANDED_WIDTH, self.width())
        elif collapsed:
            self._locked_size = self.size() if self._size_mode != SIZE_LOCKED else self._locked_size
        self._collapsed = collapsed
        self._sync_chrome()
        self.refresh_constraints()
        self.collapsedChanged.emit(collapsed)
        if not collapsed:
            QTimer.singleShot(0, self._restore_expanded_size)
        self._run_fill()

    def fill_floating(self, rect) -> None:
        """Floating Fill: remember the free geometry once, then cover ``rect``."""
        if self._float_geometry is None:
            self._float_geometry = self.geometry()
        if self.geometry() != rect:
            self.setGeometry(rect)

    def _restore_expanded_size(self) -> None:
        if self._collapsed:
            return
        window = self.parentWidget()
        if self.isFloating():
            size = self._locked_size
            self.resize(size)
        elif isinstance(window, QMainWindow):
            width = self._locked_width if self._size_mode == SIZE_LOCKED else self._restore_width
            window.resizeDocks([self], [width], Qt.Orientation.Horizontal)
        self._run_fill()

    def _on_top_level_changed(self, _floating: bool) -> None:
        self._sync_chrome()
        self.refresh_constraints()
        self._run_fill()

    def _run_fill(self) -> None:
        if self._fill_callback is not None:
            self._fill_callback()

    def refresh_constraints(self) -> None:
        """Apply collapse / lock / fill state as concrete size limits."""
        self.setMinimumSize(0, 0)
        self.setMaximumSize(QWIDGETSIZE_MAX, QWIDGETSIZE_MAX)
        floating = self.isFloating()
        if self._collapsed:
            if floating:
                self.setMinimumWidth(self.MIN_EXPANDED_WIDTH)
                height = self.title_bar.sizeHint().height() + SPACE.sm
                self.setMaximumHeight(height)
                self.resize(self.width(), height)
            else:
                self.setMinimumWidth(self.RAIL_WIDTH)
                self.setMaximumWidth(self.RAIL_WIDTH)
        elif self._size_mode == SIZE_LOCKED:
            if floating:
                self.setFixedSize(self._locked_size)
            else:
                self.setMinimumWidth(self._locked_width)
                self.setMaximumWidth(self._locked_width)
        else:
            self.setMinimumWidth(self.MIN_EXPANDED_WIDTH)
        self.panel.mode_hint.setText(self._hint_text())
        window = self.parentWidget()
        if window is not None and window.layout() is not None:
            window.layout().invalidate()
        self.updateGeometry()

    def _hint_text(self) -> str:
        if self._size_mode == SIZE_LOCKED:
            if self.isFloating():
                return f"Locked at {self._locked_size.width()} × {self._locked_size.height()} px. Choose Free to resize."
            return f"Locked at {self._locked_width} px wide. Choose Free to resize."
        if self._size_mode == SIZE_FILL:
            return "Fill: floating, uses the whole screen; docked, uses all remaining width."
        return "Free: drag the dock edge to resize."

    def _sync_chrome(self) -> None:
        """Title-bar text and rail visibility follow collapsed / docked state."""
        floating = self.isFloating()
        rail = self._collapsed and not floating
        self.panel.setVisible(not self._collapsed)
        self.rail.setVisible(rail)
        self.title_bar.title.setVisible(not rail)
        self.title_bar.float_button.setVisible(not rail)
        self.title_bar.float_button.setText("Dock" if floating else "Undock")
        right = self.parentWidget() is not None and isinstance(self.parentWidget(), QMainWindow) and \
            self.parentWidget().dockWidgetArea(self) == Qt.DockWidgetArea.RightDockWidgetArea
        if floating:
            arrow = "▾" if self._collapsed else "▴"
        elif right:
            arrow = "◂" if self._collapsed else "▸"
        else:
            arrow = "▸" if self._collapsed else "◂"
        self.title_bar.collapse_button.setText(arrow)
        verb = "Expand" if self._collapsed else "Collapse"
        self.title_bar.collapse_button.setToolTip(f"{verb} the Output Display (Ctrl+3)")
        layout = self.title_bar.layout()
        layout.setContentsMargins(SPACE.xs if rail else SPACE.md, SPACE.xs, SPACE.xs if rail else SPACE.sm, SPACE.xs)
        repolish(self.title_bar)

    def sizeHint(self) -> QSize:  # noqa: N802 (Qt API)
        return QSize(self.DEFAULT_WIDTH, 560)
