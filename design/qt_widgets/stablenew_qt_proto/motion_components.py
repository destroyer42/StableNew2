"""Reusable Motion & Video components (QT-DS-04). Presentation only: state lives in MotionSession.

No video is decoded or generated. The viewer animates camera moves over packaged fixture illustrations
and always says so. Hidden or unavailable media is never drawn.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from PySide6.QtCore import QEvent, QPointF, QRectF, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QPainter, QPen, QPixmap
from PySide6.QtWidgets import (
    QComboBox,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QSizePolicy,
    QSlider,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from .components import (
    ActionStrip,
    IssueList,
    ResponsiveGrid,
    StatusChip,
    repolish,
    stacked_label,
)
from .edit_components import motif_image
from .edit_domain import Availability
from .motion_domain import (
    MOCK_NOTICE,
    Governance,
    MediaCatalog,
    MockClip,
    MotionPreview,
    PlaybackPlan,
    Rating,
    Status,
    WorkflowCapabilityFixture,
    camera_window,
    usable_image,
)
from .tokens import COLORS, SPACE, active_theme

GOVERNANCE_LEVEL = {
    Governance.APPROVED: "success",
    Governance.EXPERIMENTAL: "warning",
    Governance.RETIRED: "blocked",
}
STATUS_LEVEL = {
    Status.NOT_REVIEWED: "info",
    Status.STALE: "warning",
    Status.BLOCKED: "blocked",
    Status.READY: "success",
    Status.SIMULATED: "success",
}
MAX_VISIBLE_ISSUES = 5


def _label(text: str = "", role: str = "muted") -> QLabel:
    label = QLabel(text)
    label.setTextFormat(Qt.TextFormat.PlainText)
    if role != "body":
        label.setProperty("role", role)
    label.setWordWrap(True)
    return label


def source_pixmap(
    catalog: MediaCatalog, key: str | None, size: tuple[int, int] | None = None
) -> QPixmap:
    """Pixels for ``key`` only when the catalog allows it (hidden/missing/unsupported yield a null pixmap)."""
    if usable_image(catalog, key):
        return QPixmap()
    source = catalog.get(key)
    image = motif_image(source.motif, source.size)
    pixmap = QPixmap.fromImage(image)
    if size:
        pixmap = pixmap.scaled(
            *size, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation
        )
    return pixmap


# --------------------------------------------------------------------------------- selectors
class MotionSourceSelector(QComboBox):
    """Lists explicit media identities with their availability before selection; shows no pixels."""

    def __init__(self, catalog: MediaCatalog, *, anchors: bool = False, kind: str = "image"):
        super().__init__()
        self.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        self.setMinimumContentsLength(12)
        if kind == "motion-reference":
            self.setAccessibleName("Motion reference")
            self.addItem("No motion reference", None)
            sources = catalog.references()
        else:
            self.setAccessibleName("Authored anchor" if anchors else "Source image fixture")
            self.addItem(
                "No authored anchor (carry last frame)" if anchors else "Select a source image…",
                None,
            )
            sources = tuple(
                s for s in catalog.images() if anchors or not s.key.startswith("anchor:")
            )
        for source in sources:
            title = (
                "restricted media" if source.availability == Availability.HIDDEN else source.title
            )
            label = f"{source.key.partition(':')[0]} · {title}"
            if source.availability != Availability.AVAILABLE:
                label += f" · {source.availability}"
            self.addItem(label, source.key)
            self.setItemData(
                self.count() - 1,
                f"{source.key} · {source.availability}",
                Qt.ItemDataRole.ToolTipRole,
            )
        self.setToolTip("Media are isolated fixtures. Availability is shown before selection.")

    def key(self) -> str | None:
        return self.currentData()

    def select_key(self, key: str | None) -> None:
        index = self.findData(key)
        self.setCurrentIndex(max(0, index))


class WorkflowCapabilityBadge(QWidget):
    """Governance chip plus route, controls and the fixture note. Governance is words, not colour alone."""

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(SPACE.xs)
        row = QHBoxLayout()
        row.setSpacing(SPACE.sm)
        self.chip = StatusChip("Governance", "info")
        self.route = _label()
        row.addWidget(self.chip)
        row.addWidget(self.route, 1)
        lay.addLayout(row)
        self.detail = _label()
        lay.addWidget(self.detail)

    def set_workflow(self, wf: WorkflowCapabilityFixture | None) -> None:
        if wf is None:
            self.chip.set_status("No workflow", "info")
            self.route.setText("")
            self.detail.setText("")
            return
        self.chip.set_status(wf.governance.value.upper(), GOVERNANCE_LEVEL[wf.governance])
        self.route.setText(f"{wf.route.value} · {wf.workflow_id} {wf.version}")
        controls = ", ".join(sorted(wf.controls))
        self.detail.setText(f"Declared controls: {controls}\n{wf.policy.describe()}\n{wf.note}")
        self.setAccessibleName(f"{wf.label}, {wf.governance.value}")


# ---------------------------------------------------------------------------------- shot cards
@dataclass(frozen=True)
class ShotCardData:
    shot_id: str
    position: int
    label: str
    frames_text: str
    basis: str
    issues: int
    source_key: str | None


class StoryboardShotCard(QFrame):
    selectRequested = Signal(str)
    navigate = Signal(object, int)  # (card, delta)

    def __init__(self, shot_id: str, parent: QWidget | None = None):
        super().__init__(parent)
        self.shot_id = shot_id
        self.setProperty("role", "shot")
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(SPACE.sm, SPACE.sm, SPACE.sm, SPACE.sm)
        lay.setSpacing(SPACE.xs)
        self.thumb = QLabel()
        self.thumb.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.thumb.setMinimumHeight(48)
        self.thumb.setProperty("role", "muted")
        self.title = ElidedLabel()
        self.meta = ElidedLabel()
        self.meta.setProperty("role", "muted")
        self.badge = ElidedLabel()
        self.badge.setProperty("role", "muted")
        for widget in (self.thumb, self.title, self.meta, self.badge):
            lay.addWidget(widget)
        self.thumb.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)

    def set_data(
        self, data: ShotCardData, pixmap: QPixmap, *, selected: bool, compact: bool
    ) -> None:
        self.thumb.setVisible(not compact)
        if pixmap.isNull():
            self.thumb.setPixmap(QPixmap())
            self.thumb.setText("media unavailable")
        else:
            self.thumb.setText("")
            self.thumb.setPixmap(pixmap)
        self.title.set_full_text(f"{data.position} · {data.label}")
        self.meta.set_full_text(f"{data.frames_text} · {data.basis}")
        self.badge.set_full_text(
            "Not reviewed"
            if data.issues < 0
            else (f"{data.issues} issue(s)" if data.issues else "Ready")
        )
        self.badge.setProperty("level", "warning" if data.issues > 0 else "info")
        repolish(self.badge)
        self.setProperty("selected", selected)
        self.setProperty("invalid", data.issues > 0)
        repolish(self)
        self.setAccessibleName(
            f"Shot {data.position} {data.label}, {data.frames_text}, {data.basis}, "
            f"{'selected, ' if selected else ''}"
            f"{'not reviewed' if data.issues < 0 else str(data.issues) + ' issues'}"
        )

    def mousePressEvent(self, event) -> None:  # noqa: N802 (Qt API)
        self.setFocus()
        self.selectRequested.emit(self.shot_id)
        event.accept()

    def keyPressEvent(self, event) -> None:  # noqa: N802 (Qt API)
        key = event.key()
        if key in (Qt.Key.Key_Return, Qt.Key.Key_Enter, Qt.Key.Key_Space):
            self.selectRequested.emit(self.shot_id)
        elif key in (Qt.Key.Key_Left, Qt.Key.Key_Up):
            self.navigate.emit(self, -1)
        elif key in (Qt.Key.Key_Right, Qt.Key.Key_Down):
            self.navigate.emit(self, 1)
        elif key in (Qt.Key.Key_Home, Qt.Key.Key_End):
            self.navigate.emit(self, -999 if key == Qt.Key.Key_Home else 999)
        else:
            super().keyPressEvent(event)
            return
        event.accept()


class ShotStrip(QWidget):
    """Ordered shot cards that wrap to new rows instead of scrolling horizontally."""

    shotSelected = Signal(str)
    CARD_WIDTH = 140
    COMPACT_CARD_WIDTH = 112

    def __init__(self, catalog: MediaCatalog, parent: QWidget | None = None):
        super().__init__(parent)
        self.catalog = catalog
        self.cards: dict[str, StoryboardShotCard] = {}
        self.order: list[str] = []
        self.compact = False
        self._selected: str | None = None
        self._thumbs: dict[tuple, QPixmap] = {}
        self._columns = 0
        self._grid = QGridLayout(self)
        self._grid.setContentsMargins(0, 0, 0, 0)
        self._grid.setSpacing(SPACE.sm)
        self.setAccessibleName("Storyboard shot strip")
        self.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Minimum)

    def set_compact(self, compact: bool) -> None:
        self.compact = compact

    @property
    def card_width(self) -> int:
        return self.COMPACT_CARD_WIDTH if self.compact else self.CARD_WIDTH

    def _thumb(self, key: str | None) -> QPixmap:
        if not key:
            return QPixmap()
        digest = ""
        try:
            digest = self.catalog.get(key).digest
        except ValueError:
            return QPixmap()
        cache_key = (key, digest, self.catalog.get(key).availability.value)
        if cache_key not in self._thumbs:
            if len(self._thumbs) > 24:
                self._thumbs.clear()
            self._thumbs[cache_key] = source_pixmap(self.catalog, key, (112, 56))
        return self._thumbs[cache_key]

    def set_shots(self, rows: Sequence[ShotCardData], selected: str | None) -> None:
        self._selected = selected
        wanted = {r.shot_id for r in rows}
        for shot_id in [s for s in self.cards if s not in wanted]:
            card = self.cards.pop(shot_id)
            self._grid.removeWidget(card)
            card.hide()
            card.deleteLater()
        for row in rows:
            card = self.cards.get(row.shot_id)
            if card is None:
                card = StoryboardShotCard(row.shot_id, self)
                card.selectRequested.connect(self._select)
                card.navigate.connect(self._navigate)
                self.cards[row.shot_id] = card
            card.set_data(
                row,
                self._thumb(row.source_key),
                selected=row.shot_id == selected,
                compact=self.compact,
            )
        self.order = [r.shot_id for r in rows]
        self._reflow(force=True)

    def _select(self, shot_id: str) -> None:
        self.shotSelected.emit(shot_id)

    def _navigate(self, card: StoryboardShotCard, delta: int) -> None:
        index = self.order.index(card.shot_id)
        target = max(0, min(len(self.order) - 1, index + delta))
        new = self.cards[self.order[target]]
        new.setFocus()
        self.shotSelected.emit(new.shot_id)

    def focus_card(self, shot_id: str) -> None:
        if card := self.cards.get(shot_id):
            card.setFocus()

    def _wanted_columns(self) -> int:
        gap = self._grid.spacing()
        return max(1, min(len(self.order) or 1, (self.width() + gap) // (self.card_width + gap)))

    def _reflow(self, force: bool = False) -> None:
        cols = self._wanted_columns()
        if cols == self._columns and not force:
            return
        self._columns = cols
        for shot_id in self.order:
            self._grid.removeWidget(self.cards[shot_id])
        for index, shot_id in enumerate(self.order):
            self._grid.addWidget(self.cards[shot_id], index // cols, index % cols)
        for col in range(max(cols, 13)):
            self._grid.setColumnStretch(col, 1 if col < cols else 0)

    def resizeEvent(self, event) -> None:  # noqa: N802 (Qt API)
        super().resizeEvent(event)
        self._reflow()

    def needed_height(self) -> int:
        """Height needed to show every card at the current width (rows wrap, none scroll away).

        Card labels elide rather than wrap, so the grid's own size hint is exact."""
        if not self.order:
            return 0
        for card in self.cards.values():
            card.ensurePolished()
            card.layout().invalidate()
        self._grid.invalidate()
        self._grid.activate()
        return self._grid.sizeHint().height()

    def row_height(self) -> int:
        """Height of one row of cards at the current width."""
        if not self.order:
            return 0
        rows = -(-len(self.order) // self._wanted_columns())
        return (self.needed_height() - self._grid.spacing() * (rows - 1)) // rows

    def minimumSizeHint(self):  # noqa: N802 (Qt API)
        hint = super().minimumSizeHint()
        hint.setWidth(self.card_width)
        return hint


@dataclass(frozen=True)
class TimelineRow:
    shot_id: str
    position: int
    label: str
    frames: int
    basis: str
    blocked: bool


class ShotTimeline(QWidget):
    """Lightweight order / approximate-duration / dependency illustration. Not a precision editor."""

    shotSelected = Signal(str)

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.rows: tuple[TimelineRow, ...] = ()
        self.selected: str | None = None
        self.detailed = True
        self.setMinimumHeight(40)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.setAccessibleName("Storyboard timeline illustration")

    def set_detailed(self, detailed: bool) -> None:
        self.detailed = detailed
        self.setFixedHeight(76 if detailed else 40)

    def set_rows(self, rows: Sequence[TimelineRow], selected: str | None) -> None:
        self.rows, self.selected = tuple(rows), selected
        total = sum(r.frames for r in rows)
        self.setAccessibleDescription(
            f"{len(rows)} shots, about {total} native frames. Dependencies: "
            + ", ".join(f"{r.position} {r.basis}" for r in rows)
        )
        self.update()

    def _blocks(self) -> list[tuple[TimelineRow, QRectF]]:
        if not self.rows:
            return []
        gap = 6.0
        avail = max(40.0, self.width() - 2 * gap) - gap * (len(self.rows) - 1)
        weights = [max(1, r.frames) for r in self.rows]
        total = sum(weights)
        floor = min(26.0, avail / len(self.rows))
        widths = [max(floor, avail * w / total) for w in weights]
        scale = avail / sum(widths)
        out, x = [], gap
        top = 6.0
        height = 26.0
        for row, width in zip(self.rows, widths, strict=True):
            out.append((row, QRectF(x, top, width * scale, height)))
            x += width * scale + gap
        return out

    def paintEvent(self, _event) -> None:  # noqa: N802 (Qt API)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        theme = active_theme()
        for row, rect in self._blocks():
            chosen = row.shot_id == self.selected
            fill = QColor(COLORS.selected if chosen else COLORS.field)
            edge = (
                COLORS.danger
                if row.blocked
                else (COLORS.accent if chosen else COLORS.strong_border)
            )
            painter.setBrush(fill)
            painter.setPen(QPen(QColor(edge), theme.borders.control_width))
            painter.drawRoundedRect(rect, 4, 4)
            painter.setPen(QColor(COLORS.text))
            painter.drawText(rect, Qt.AlignmentFlag.AlignCenter, f"{row.position}")
            if self.detailed:
                painter.setPen(QColor(COLORS.muted))
                note = {
                    "source": "source",
                    "carried": "carries last frame",
                    "provided": "authored anchor",
                }
                text = f"{row.frames} f · {note.get(row.basis, row.basis)}"
                painter.drawText(
                    QRectF(rect.left(), rect.bottom() + 4, max(rect.width(), 70), 16),
                    Qt.AlignmentFlag.AlignLeft,
                    painter.fontMetrics().elidedText(
                        text, Qt.TextElideMode.ElideRight, int(max(rect.width(), 70))
                    ),
                )
                if row.basis == "provided":
                    painter.setPen(QPen(QColor(COLORS.accent), 2))
                    painter.drawLine(
                        QPointF(rect.left(), rect.top() - 4),
                        QPointF(rect.left() + 10, rect.top() - 4),
                    )
                elif row.basis == "carried":
                    painter.setPen(QPen(QColor(COLORS.muted), 1, Qt.PenStyle.DashLine))
                    painter.drawLine(
                        QPointF(rect.left() - 6, rect.center().y()),
                        QPointF(rect.left(), rect.center().y()),
                    )
        painter.end()

    def mousePressEvent(self, event) -> None:  # noqa: N802 (Qt API)
        point = event.position()
        for row, rect in self._blocks():
            if rect.adjusted(-3, -3, 3, 40).contains(point):
                self.shotSelected.emit(row.shot_id)
                break


# ------------------------------------------------------------------------------- readiness
class SequenceReadinessPanel(QWidget):
    """Status, blocking reasons, facts and per-shot readiness. A summary, never an executable job."""

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(SPACE.sm)
        self.chip = StatusChip(Status.NOT_REVIEWED.value, "info")
        self.revision = _label()
        self.issues = IssueList()
        self.facts = _label("", "body")
        self.shots = _label("", "body")
        for widget in (self.chip, self.revision, self.issues, self.facts, self.shots):
            lay.addWidget(widget)
        self.setAccessibleName("Readiness summary")

    def set_state(
        self,
        status: Status,
        preview: MotionPreview | None,
        issues: Sequence[str],
        revision: int,
    ) -> None:
        self.chip.set_status(status.value, STATUS_LEVEL[status])
        warnings = preview.warnings if preview else ()
        shown, hidden = list(issues[:MAX_VISIBLE_ISSUES]), max(0, len(issues) - MAX_VISIBLE_ISSUES)
        if hidden:
            shown.append(f"… and {hidden} more blocking reason(s).")
        empty = {
            Status.NOT_REVIEWED: "Review Readiness to build a summary.",
            Status.STALE: "The draft or its media changed. Review Readiness again.",
        }.get(status, "No blocking reasons.")
        self.issues.set_issues(
            tuple(shown),
            () if status in (Status.NOT_REVIEWED, Status.STALE) else tuple(warnings[:3]),
            empty=empty,
            empty_status={Status.STALE: "STALE", Status.NOT_REVIEWED: "NOT REVIEWED"}.get(
                status, "OK"
            ),
            empty_level={Status.STALE: "warning", Status.NOT_REVIEWED: "info"}.get(
                status, "success"
            ),
        )
        if preview is None:
            self.revision.setText(f"Draft revision {revision} · no summary yet")
            self.facts.setText("")
            self.shots.setText("")
            return
        self.revision.setText(
            f"Last preview revision {preview.revision} · draft revision {revision}"
            + ("" if preview.revision == revision else " · preview is stale")
        )
        self.facts.setText("\n".join(f"{k} · {v}" for k, v in preview.facts))
        lines = []
        for shot in preview.shots:
            frames = f"{shot.frames} f" if shot.frames else "illegal frames"
            lines.append(
                f"{shot.position}. {shot.label} · {frames} · {shot.anchor_basis} · prompt {shot.prompt_origin}"
                f" · frames {shot.frames_origin} · seed {shot.seed_text}"
                + (f" · {len(shot.errors)} issue(s)" if shot.errors else "")
            )
        self.shots.setText("\n".join(lines))


class ElidedLabel(QLabel):
    """Single-line label that elides in the middle instead of forcing the layout wider.

    The full text stays available as the tooltip and accessible description."""

    def __init__(self, text: str = "", parent: QWidget | None = None):
        super().__init__(parent)
        self.setTextFormat(Qt.TextFormat.PlainText)
        self.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        self._full = ""
        self.set_full_text(text)

    def full_text(self) -> str:
        return self._full

    def set_full_text(self, text: str) -> None:
        self._full = text
        self.setToolTip(text)
        self.setAccessibleDescription(text)
        self._elide()

    def _elide(self) -> None:
        shown = self.fontMetrics().elidedText(
            self._full, Qt.TextElideMode.ElideMiddle, max(0, self.width() - 2)
        )
        super().setText(shown)

    def resizeEvent(self, event) -> None:  # noqa: N802 (Qt API)
        super().resizeEvent(event)
        self._elide()

    def minimumSizeHint(self):  # noqa: N802 (Qt API)
        hint = super().minimumSizeHint()
        hint.setWidth(0)
        return hint


# ------------------------------------------------------------------------------------ viewer
class _FrameCanvas(QWidget):
    def __init__(self, catalog: MediaCatalog):
        super().__init__()
        self.catalog = catalog
        self.pixmap = QPixmap()
        self.motion = "pan-right"
        self.progress = 0.0
        self.message = "No simulated clip selected."
        self.setMinimumSize(160, 90)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.setAccessibleName("Simulated clip frame (illustration)")

    def set_frame(self, pixmap: QPixmap, motion: str, progress: float, message: str) -> None:
        self.pixmap, self.motion, self.progress, self.message = pixmap, motion, progress, message
        self.update()

    def paintEvent(self, _event) -> None:  # noqa: N802 (Qt API)
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor(COLORS.field))
        if self.pixmap.isNull():
            painter.setPen(QColor(COLORS.muted))
            painter.drawText(
                self.rect().adjusted(8, 8, -8, -8),
                Qt.AlignmentFlag.AlignCenter | Qt.TextFlag.TextWordWrap,
                self.message,
            )
        else:
            x, y, scale = camera_window(self.motion, self.progress)
            width, height = self.pixmap.width(), self.pixmap.height()
            window = QRectF(x * width, y * height, scale * width, scale * height)
            fit = min(self.width() / window.width(), self.height() / window.height())
            target = QRectF(0, 0, window.width() * fit, window.height() * fit)
            target.moveCenter(QPointF(self.width() / 2, self.height() / 2))
            painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
            painter.drawPixmap(target, self.pixmap, window)
        theme = active_theme()
        border = theme.state_color("focus_border") if self.hasFocus() else COLORS.border
        painter.setPen(QPen(QColor(border), theme.borders.control_width))
        painter.drawRect(self.rect().adjusted(1, 1, -2, -2))


class SimulatedClipViewer(QWidget):
    """Play/pause, restart and scrub over fixture illustrations. The timer runs only while playing and
    visible, steps in real time, and is parented so it can never call into a deleted widget."""

    frameChanged = Signal(int)
    TARGET_FPS = 12

    def __init__(self, catalog: MediaCatalog, parent: QWidget | None = None):
        super().__init__(parent)
        self.catalog = catalog
        self.plan: PlaybackPlan | None = None
        self.index = 0
        self._segment = -1
        self._pixmap = QPixmap()
        self._pixmap_key: tuple | None = None
        self._step = 1
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(SPACE.sm)
        self.banner = QLabel("Simulated Clip — No Video Generated")
        self.banner.setProperty("role", "capsule")
        self.banner.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.banner.setToolTip(MOCK_NOTICE)
        lay.addWidget(self.banner)
        self.canvas = _FrameCanvas(catalog)
        lay.addWidget(self.canvas, 1)
        self.title = _label()
        lay.addWidget(self.title)
        controls = QHBoxLayout()
        controls.setSpacing(SPACE.sm)
        self.play_button = QPushButton("Play")
        self.play_button.setAccessibleName("Play or pause simulated clip")
        self.restart_button = QPushButton("Restart")
        self.slider = QSlider(Qt.Orientation.Horizontal)
        self.slider.setAccessibleName("Scrub simulated frames")
        self.slider.setEnabled(False)
        self.readout = QLabel("")
        self.readout.setMinimumWidth(
            self.readout.fontMetrics().horizontalAdvance("frame 000 / 000")
        )
        controls.addWidget(self.play_button)
        controls.addWidget(self.restart_button)
        controls.addWidget(self.slider, 1)
        controls.addWidget(self.readout)
        lay.addLayout(controls)
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._tick)
        self.play_button.clicked.connect(self.toggle)
        self.restart_button.clicked.connect(self.restart)
        self.slider.valueChanged.connect(self._scrubbed)
        self.set_plan(None)

    # ------------------------------------------------------------------------- state
    @property
    def playing(self) -> bool:
        return self._timer.isActive()

    def set_plan(self, plan: PlaybackPlan | None) -> None:
        self.pause()
        self.plan = plan
        self.index = 0
        self._segment = -1
        self.slider.blockSignals(True)
        self.slider.setRange(0, max(0, plan.total_frames - 1) if plan else 0)
        self.slider.setValue(0)
        self.slider.blockSignals(False)
        self.slider.setEnabled(plan is not None)
        self.play_button.setEnabled(plan is not None)
        self.restart_button.setEnabled(plan is not None)
        self.title.setText(
            f"{plan.title} · {plan.total_frames} frames · {plan.seconds:.2f} s illustrated"
            if plan
            else "No simulated clip selected. Simulate a clip, sequence or assembly to inspect it."
        )
        self._show(0)

    def _load_segment(self, position: int) -> None:
        seg = self.plan.segments[position]
        key = (
            seg.source_key,
            self.catalog.get(seg.source_key).digest,
            self.catalog.get(seg.source_key).availability,
        )
        if key != self._pixmap_key:
            self._pixmap = source_pixmap(self.catalog, seg.source_key)  # at most one pixmap is held
            self._pixmap_key = key
        self._segment = position
        self._step = max(1, seg.fps // self.TARGET_FPS)
        self._timer.setInterval(max(16, round(1000 * self._step / seg.fps)))

    def _show(self, index: int) -> None:
        if self.plan is None or not self.plan.segments:
            self.canvas.set_frame(QPixmap(), "pan-right", 0.0, "No simulated clip selected.")
            self.readout.setText("")
            return
        self.index = max(0, min(index, self.plan.total_frames - 1))
        position, local, progress = self.plan.locate(self.index)
        if position != self._segment:
            self._load_segment(position)
        seg = self.plan.segments[position]
        self.canvas.set_frame(
            self._pixmap,
            seg.motion,
            progress,
            f"Source unavailable: {seg.source_key}. Nothing is drawn.",
        )
        self.readout.setText(f"frame {self.index + 1} / {self.plan.total_frames}")
        self.title.setText(
            f"{self.plan.title} · segment {position + 1}/{len(self.plan.segments)} {seg.label} · "
            f"{seg.motion} illustration"
        )
        if self.slider.value() != self.index:
            self.slider.blockSignals(True)
            self.slider.setValue(self.index)
            self.slider.blockSignals(False)
        self.frameChanged.emit(self.index)

    # ---------------------------------------------------------------------- controls
    def toggle(self) -> None:
        self.pause() if self.playing else self.play()

    def play(self) -> None:
        if self.plan is None or not self.isVisible():
            return
        if self.index >= self.plan.total_frames - 1:
            self._show(0)
        self._load_segment(self.plan.locate(self.index)[0])
        self._timer.start()
        self.play_button.setText("Pause")

    def pause(self) -> None:
        was_playing = self._timer.isActive()
        self._timer.stop()
        if was_playing:
            self.play_button.setText("Play")

    def restart(self) -> None:
        self._show(0)
        if self.plan is not None:
            self.play()

    def seek(self, index: int) -> None:
        self._show(index)

    def _scrubbed(self, value: int) -> None:
        self._show(value)

    def _tick(self) -> None:
        if self.plan is None:
            self.pause()
            return
        nxt = self.index + self._step
        if nxt >= self.plan.total_frames:
            self._show(self.plan.total_frames - 1)
            self.pause()
            return
        self._show(nxt)

    def hideEvent(self, event) -> None:  # noqa: N802 (Qt API)
        self.pause()
        super().hideEvent(event)

    def changeEvent(self, event) -> None:  # noqa: N802 (Qt API)
        if event.type() == QEvent.Type.EnabledChange and not self.isEnabled():
            self.pause()
        super().changeEvent(event)


# ---------------------------------------------------------------------------------- assembly
@dataclass(frozen=True)
class AssemblyRow:
    item_id: str
    text: str
    clip_frames: int
    trim_start: int
    trim_end: int
    problem: str


class ClipAssemblyList(QWidget):
    """Ordered assembly with reorder, remove and start/end trim intent. Order is never re-sorted."""

    moveRequested = Signal(str, int)
    removeRequested = Signal(str)
    trimChanged = Signal(str, int, int)
    itemSelected = Signal(str)

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(SPACE.sm)
        self.list = QListWidget()
        self.list.setProperty("role", "nav")
        self.list.setAccessibleName("Assembly clip order")
        self.list.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.list.setWordWrap(True)
        self.list.setMinimumHeight(110)
        lay.addWidget(self.list, 1)
        row = ResponsiveGrid(min_column_width=104)
        self.up = QPushButton("Move Up")
        self.down = QPushButton("Move Down")
        self.remove = QPushButton("Remove")
        self.remove.setToolTip(
            "Remove the selected clip from this assembly (the clip itself stays)"
        )
        for button in (self.up, self.down, self.remove):
            row.add(button)
        lay.addWidget(row)
        trims = QHBoxLayout()
        self.trim_start = QSpinBox()
        self.trim_start.setAccessibleName("Trim start frames")
        self.trim_start.setSuffix(" f")
        self.trim_end = QSpinBox()
        self.trim_end.setAccessibleName("Trim end frames")
        self.trim_end.setSuffix(" f")
        for spin in (self.trim_start, self.trim_end):
            spin.setKeyboardTracking(False)
            spin.setRange(0, 200)
        trims.addWidget(stacked_label("Trim start", self.trim_start))
        trims.addWidget(stacked_label("Trim end", self.trim_end))
        lay.addLayout(trims)
        self.note = _label("Trim is intent only: nothing is cut or encoded.")
        lay.addWidget(self.note)
        self.rows: tuple[AssemblyRow, ...] = ()
        self.list.currentRowChanged.connect(self._row_changed)
        self.up.clicked.connect(lambda: self._emit_move(-1))
        self.down.clicked.connect(lambda: self._emit_move(1))
        self.remove.clicked.connect(self._emit_remove)
        self.trim_start.valueChanged.connect(self._emit_trim)
        self.trim_end.valueChanged.connect(self._emit_trim)

    def current_id(self) -> str | None:
        row = self.list.currentRow()
        return self.rows[row].item_id if 0 <= row < len(self.rows) else None

    def set_items(self, rows: Sequence[AssemblyRow], selected: str | None) -> None:
        self.rows = tuple(rows)
        self.list.blockSignals(True)
        self.list.clear()
        current = 0
        for index, row in enumerate(self.rows):
            text = f"{index + 1} · {row.text}" + (f"\n⚠ {row.problem}" if row.problem else "")
            self.list.addItem(QListWidgetItem(text))
            if row.item_id == selected:
                current = index
        if self.rows:
            self.list.setCurrentRow(current)
        self.list.blockSignals(False)
        self._load_trim()

    def _load_trim(self) -> None:
        row = self.list.currentRow()
        has = 0 <= row < len(self.rows)
        for spin in (self.trim_start, self.trim_end):
            spin.blockSignals(True)
        if has:
            item = self.rows[row]
            self.trim_start.setValue(item.trim_start)
            self.trim_end.setValue(item.trim_end)
        for spin in (self.trim_start, self.trim_end):
            spin.blockSignals(False)
        last = len(self.rows) - 1
        self.up.setEnabled(has and row > 0)
        self.down.setEnabled(has and row < last)
        self.remove.setEnabled(has)
        self.trim_start.setEnabled(has)
        self.trim_end.setEnabled(has)

    def _row_changed(self, _row: int) -> None:
        self._load_trim()
        if item_id := self.current_id():
            self.itemSelected.emit(item_id)

    def _emit_move(self, delta: int) -> None:
        if item_id := self.current_id():
            self.moveRequested.emit(item_id, delta)

    def _emit_remove(self) -> None:
        if item_id := self.current_id():
            self.removeRequested.emit(item_id)

    def _emit_trim(self) -> None:
        if item_id := self.current_id():
            self.trimChanged.emit(item_id, self.trim_start.value(), self.trim_end.value())


# -------------------------------------------------------------------------------- rating
class QualityRatingPanel(QWidget):
    """Action outcome (a fact) and operator quality impression (optional) are separate. Neither enters Learning."""

    rated = Signal(int, str)

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(SPACE.xs)
        lay.addWidget(_label("1 · Action outcome (mock workflow)", "section"))
        self.outcome = _label("No clip selected.")
        lay.addWidget(self.outcome)
        lay.addWidget(_label("2 · Operator quality impression (optional)", "section"))
        self.stars = QComboBox()
        self.stars.setAccessibleName("Quality impression of the illustration")
        self.stars.addItem("Not rated", 0)
        for n in range(1, 6):
            self.stars.addItem(f"{n} of 5", n)
        self.note = QLineEdit()
        self.note.setAccessibleName("Impression note")
        self.note.setPlaceholderText("Optional note")
        self.save = QPushButton("Record impression")
        row = QHBoxLayout()
        row.addWidget(self.stars)
        row.addWidget(self.save)
        lay.addLayout(row)
        lay.addWidget(self.note)
        self.disclaimer = _label(
            "Rates the illustration only. Not sent to Learning, not a model qualification, "
            "never changes recommendations."
        )
        lay.addWidget(self.disclaimer)
        self.save.clicked.connect(
            lambda: self.rated.emit(self.stars.currentData(), self.note.text())
        )
        self.set_clip(None, None)

    def set_clip(self, clip: MockClip | None, rating: Rating | None) -> None:
        for widget in (self.stars, self.note, self.save):
            widget.setEnabled(clip is not None and clip.completed)
        if clip is None:
            self.outcome.setText("No clip selected.")
            return
        self.outcome.setText(
            f"{clip.clip_id}: mock action {'completed' if clip.completed else 'FAILED'}"
            + ("" if clip.completed else f" ({clip.failure})")
            + f"\n{MOCK_NOTICE}"
        )
        self.stars.blockSignals(True)
        self.stars.setCurrentIndex(rating.stars if rating else 0)
        self.stars.blockSignals(False)
        self.note.setText(rating.note if rating else "")


class MotionActionStrip(ActionStrip):
    """Persistent actions: Review Readiness, Simulate, Inspect Results, Send to Movie Clips."""

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.status.setText("Draft only · mock simulation · nothing queued")
        self.review = self.add_action("Review Readiness")
        self.inspect = self.add_action("Inspect Results")
        self.send = self.add_action("Send to Movie Clips")
        self.simulate = self.add_action("Simulate Clip", primary=True)
        self.setAccessibleName("Motion actions")
