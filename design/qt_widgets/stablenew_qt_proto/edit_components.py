"""Reusable fixture picker and pixel-space editing/comparison widgets."""

from __future__ import annotations

from PySide6.QtCore import QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QImage, QLinearGradient, QPainter, QPen
from PySide6.QtWidgets import QComboBox, QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget

from .edit_domain import (
    SOURCES,
    Availability,
    Candidate,
    EditRefused,
    Geometry,
    ImageTransform,
    Mode,
    paint_segment,
    require_available,
)
from .output_model import fit_factor, format_zoom, step_zoom
from .tokens import ASSET_DIR, COLORS, SPACE, active_theme


class SourcePicker(QComboBox):
    """List identities and availability without displaying any fixture pixels."""

    def __init__(self):
        super().__init__()
        self.setAccessibleName("Edit source fixture")
        self.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        self.setMinimumContentsLength(12)
        self.addItem("Select a source fixture…")
        for source in SOURCES:
            namespace = source.key.partition(":")[0]
            label = f"{namespace} · {source.title}"
            if source.availability != Availability.AVAILABLE:
                label += f" · {source.availability}"
            self.addItem(label, source.key)
            self.setItemData(
                self.count() - 1,
                f"{source.key} · {source.availability}",
                Qt.ItemDataRole.ToolTipRole,
            )
        self.setToolTip("Sources are isolated fixtures. Availability is shown before selection.")


def fixture_image(key: str) -> QImage:
    """Read one of four prototype-owned assets after the catalog visibility check."""
    source = require_available(key)
    assets = ("ridge", "ridge-revision", "coast", "evening")
    image = QImage(str(ASSET_DIR / f"edit-{assets[source.motif]}.svg"))
    if image.isNull():
        raise EditRefused(f"Fixture pixels could not be read for {key}.")
    return image.scaled(*source.size, mode=Qt.TransformationMode.SmoothTransformation)


def mask_layer(mask: bytes, width: int, height: int, color: QColor, feather: int = 0) -> QImage:
    if not mask:
        return QImage()
    alpha = QImage(mask, width, height, width, QImage.Format.Format_Alpha8).copy()
    if feather > 0:
        # Resampling is an illustration of edge softness, not a processing kernel.
        smooth = Qt.TransformationMode.SmoothTransformation
        alpha = alpha.scaled(
            max(1, width // feather), max(1, height // feather), mode=smooth
        ).scaled(width, height, mode=smooth)
    image = QImage(width, height, QImage.Format.Format_ARGB32_Premultiplied)
    image.fill(color)
    painter = QPainter(image)
    painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_DestinationIn)
    painter.drawImage(0, 0, alpha)
    painter.end()
    return image


def illustration(candidate: Candidate) -> QImage:
    """Make a visual proxy for the frozen intent using only in-memory fixture pixels."""
    draft = candidate.preview.draft
    source = fixture_image(candidate.parent)
    width, height = source.width(), source.height()
    target = candidate.preview.output_size
    assert target is not None
    image = QImage(*target, QImage.Format.Format_RGB32)
    sky = source.pixelColor(width // 2, height // 4)
    image.fill(sky.lighter(140))
    painter = QPainter(image)
    if draft.mode == Mode.EXTEND:
        painter.setBrush(sky.lighter(115))
        painter.setPen(Qt.PenStyle.NoPen)
        for x in range(0, target[0], 28):
            painter.drawRect(x, 0, 10, target[1])
        painter.drawImage(draft.geometry.left, draft.geometry.top, source)
    else:
        painter.drawImage(0, 0, source)
        tint = source.pixelColor(0, height // 2).lighter(150)
        tint.setAlpha(round(255 * draft.region.strength / 100))
        if draft.mode == Mode.MASKED:
            painter.drawImage(
                0, 0, mask_layer(draft.region.mask, width, height, tint, draft.region.feather)
            )
        else:
            split = height // 2
            top = split if draft.active_region == 0 else 0
            gradient = QLinearGradient(0, top, 0, top + split)
            transparent = QColor(tint)
            transparent.setAlpha(0)
            gradient.setColorAt(0, transparent if top else tint)
            gradient.setColorAt(1, tint if top else transparent)
            painter.fillRect(0, top, width, split, gradient)
    painter.end()
    return image


class ImageCanvas(QWidget):
    """Paint one fixture with an optional in-progress, source-pixel mask gesture."""

    maskCommitted = Signal(int, bytes)
    pixelChanged = Signal(str)
    zoomChanged = Signal(str)

    def __init__(self, *, interactive: bool = True):
        super().__init__()
        self.setAccessibleName("Edit image canvas" if interactive else "Comparison image")
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setMouseTracking(True)
        self.setMinimumSize(140, 140)
        self.image = QImage()
        self.geometry_overlay: Geometry | None = None
        self.mask = b""
        self.overlay = QImage()
        self.feather = 0
        self.revision = 0
        self.tool = "Pan"
        self.brush_radius = 12
        self.zoom: float | None = None
        self.pan = QPointF()
        self.interactive = interactive
        self._stroke: bytearray | None = None
        self._previous_pixel: tuple[int, int] | None = None
        self._stroke_revision = 0
        self._stroke_radius = 0
        self._stroke_erase = False
        self._drag: QPointF | None = None
        self._pan_button = Qt.MouseButton.NoButton

    def set_image(self, image: QImage) -> None:
        self.cancel_gesture()
        self.image = image
        self.fit()

    def set_edit_state(
        self, revision: int, mask: bytes, feather: int, geometry: Geometry | None
    ) -> None:
        if revision != self.revision:
            self.cancel_gesture()
        self.revision = revision
        if (mask, feather) != (self.mask, self.feather):
            self.mask, self.feather = mask, feather
            self._refresh_mask(mask, feather)
        if self.geometry_overlay != geometry:
            self.geometry_overlay = geometry
            self._redraw()
        else:
            self.update()

    def _refresh_mask(self, mask: bytes, feather: int) -> None:
        color = QColor(COLORS.accent)
        color.setAlpha(145)
        self.overlay = mask_layer(mask, self.image.width(), self.image.height(), color, feather)

    def restyle(self) -> None:
        if self._stroke is None:
            self._refresh_mask(self.mask, self.feather)
        self.update()

    def transform(self) -> ImageTransform:
        width, height = self.image.width(), self.image.height()
        geometry = self.geometry_overlay
        target = geometry.output_size((width, height)) if geometry else (width, height)
        scale = self.zoom or fit_factor(self.width(), self.height(), *target, SPACE.sm)
        left = (self.width() - target[0] * scale) / 2 + self.pan.x()
        top = (self.height() - target[1] * scale) / 2 + self.pan.y()
        if geometry:
            left += geometry.left * scale
            top += geometry.top * scale
        return ImageTransform(left, top, scale, (width, height))

    def _redraw(self) -> None:
        self.zoomChanged.emit(format_zoom(self.transform().scale))
        self.update()

    def fit(self) -> None:
        self.zoom = None
        self.pan = QPointF()
        self._redraw()

    def actual_size(self) -> None:
        self.zoom = 1.0
        self.pan = QPointF()
        self._redraw()

    def step(self, direction: int) -> None:
        if self._stroke is None and not self.image.isNull():
            self.zoom = step_zoom(self.transform().scale, direction)
            self._redraw()

    def cancel_gesture(self) -> None:
        if self._stroke is not None:
            self._stroke = None
            self._previous_pixel = None
            self._refresh_mask(self.mask, self.feather)
            self.update()
        self._drag = None
        self._pan_button = Qt.MouseButton.NoButton

    def paintEvent(self, _event) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor(COLORS.field))
        if not self.image.isNull():
            tx = self.transform()
            painter.save()
            painter.translate(tx.left, tx.top)
            painter.scale(tx.scale, tx.scale)
            width, height = tx.size
            if geometry := self.geometry_overlay:
                target = geometry.output_size(tx.size)
                painter.fillRect(
                    QRectF(-geometry.left, -geometry.top, *target), QColor(COLORS.selected)
                )
            painter.drawImage(0, 0, self.image)
            if not self.overlay.isNull():
                painter.drawImage(0, 0, self.overlay)
            if self.geometry_overlay:
                pen = QPen(QColor(COLORS.accent))
                pen.setCosmetic(True)
                pen.setStyle(Qt.PenStyle.DashLine)
                painter.setPen(pen)
                painter.drawRect(QRectF(0, 0, width, height))
            painter.restore()
        else:
            painter.setPen(QColor(COLORS.muted))
            painter.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, "No image to display")
        theme = active_theme()
        border = theme.state_color("focus_border") if self.hasFocus() else COLORS.border
        pen = QPen(QColor(border), theme.borders.control_width)
        painter.setPen(pen)
        painter.drawRect(self.rect().adjusted(1, 1, -2, -2))

    def resizeEvent(self, event) -> None:  # noqa: N802
        self.cancel_gesture()
        self._redraw()
        super().resizeEvent(event)

    def focusInEvent(self, event) -> None:  # noqa: N802
        self.update()
        super().focusInEvent(event)

    def focusOutEvent(self, event) -> None:  # noqa: N802
        self.cancel_gesture()
        self.update()
        super().focusOutEvent(event)

    def hideEvent(self, event) -> None:  # noqa: N802
        self.cancel_gesture()
        super().hideEvent(event)

    def _pixel(self, point: QPointF) -> tuple[int, int] | None:
        pixel = self.transform().source_pixel(point.x(), point.y())
        self.pixelChanged.emit(f"x {pixel[0]} · y {pixel[1]}" if pixel else "Outside image")
        return pixel

    def leaveEvent(self, event) -> None:  # noqa: N802
        self.pixelChanged.emit("Outside image")
        super().leaveEvent(event)

    def _paint_to(self, pixel: tuple[int, int] | None) -> None:
        if self._stroke is not None and pixel is not None:
            paint_segment(
                self._stroke,
                (self.image.width(), self.image.height()),
                self._previous_pixel or pixel,
                pixel,
                self._stroke_radius,
                erase=self._stroke_erase,
            )
            self._refresh_mask(bytes(self._stroke), 0)
            self.update()
        self._previous_pixel = pixel

    def mousePressEvent(self, event) -> None:  # noqa: N802
        if self.image.isNull():
            return
        button = event.button()
        if button == Qt.MouseButton.MiddleButton or (
            button == Qt.MouseButton.LeftButton and self.tool == "Pan"
        ):
            if self._stroke is None:
                self._drag = event.position()
                self._pan_button = button
            return
        if button == Qt.MouseButton.LeftButton and self.interactive and self._drag is None:
            pixel = self._pixel(event.position())
            if pixel is not None:
                self._stroke = bytearray(
                    self.mask or bytes(self.image.width() * self.image.height())
                )
                self._stroke_revision = self.revision
                self._stroke_radius = self.brush_radius
                self._stroke_erase = self.tool == "Erase"
                self._paint_to(pixel)

    def mouseMoveEvent(self, event) -> None:  # noqa: N802
        if self._drag is not None:
            self.pan += event.position() - self._drag
            self._drag = event.position()
            self.update()
        self._paint_to(self._pixel(event.position()))

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802
        if event.button() == self._pan_button:
            self._drag = None
            self._pan_button = Qt.MouseButton.NoButton
        if self._stroke is not None and event.button() == Qt.MouseButton.LeftButton:
            self._paint_to(self._pixel(event.position()))
            mask = bytes(self._stroke)
            self.cancel_gesture()
            self.maskCommitted.emit(self._stroke_revision, mask)

    def wheelEvent(self, event) -> None:  # noqa: N802
        if self.interactive and event.modifiers() == Qt.KeyboardModifier.ControlModifier:
            self.step(event.angleDelta().y())
            event.accept()
        else:
            event.ignore()

    def keyPressEvent(self, event) -> None:  # noqa: N802
        if event.key() == Qt.Key.Key_Escape:
            self.cancel_gesture()
            event.accept()
        else:
            super().keyPressEvent(event)


class ZoomControls(QWidget):
    """Apply the same fit, actual size and incremental zoom actions to each viewer."""

    def __init__(self, *canvases: ImageCanvas):
        super().__init__()
        row = QHBoxLayout(self)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(SPACE.sm)
        self.buttons = {}
        for title, method, args in (
            ("Fit to Window", "fit", ()),
            ("100%", "actual_size", ()),
            ("Zoom in", "step", (1,)),
            ("Zoom out", "step", (-1,)),
        ):
            button = QPushButton(title)
            self.buttons[title] = button
            row.addWidget(button)
            for canvas in canvases:
                callback = getattr(canvas, method)
                button.clicked.connect(lambda _checked=False, fn=callback, a=args: fn(*a))
        row.addStretch(1)


class CompareViewer(QWidget):
    """Side-by-side images with shared zoom actions and explicit role/identity labels."""

    def __init__(self):
        super().__init__()
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        self.left = ImageCanvas(interactive=False)
        self.right = ImageCanvas(interactive=False)
        self.zoom = ZoomControls(self.left, self.right)
        outer.addWidget(self.zoom)
        row = QHBoxLayout()
        self.labels = []
        for label, canvas in (("Source", self.left), ("Derived", self.right)):
            column = QVBoxLayout()
            text = QLabel(label)
            text.setWordWrap(True)
            self.labels.append(text)
            column.addWidget(text)
            column.addWidget(canvas, 1)
            row.addLayout(column, 1)
        outer.addLayout(row, 1)

    def set_pair(self, left: QImage, right: QImage, left_label: str, right_label: str) -> None:
        for canvas, text, label, image in zip(
            (self.left, self.right),
            self.labels,
            (left_label, right_label),
            (left, right),
            strict=True,
        ):
            text.setText(label)
            canvas.setAccessibleName(label)
            canvas.set_image(image)
