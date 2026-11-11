"""Reusable Asset Library widgets (QT-DS-05). All colours, spacing and type come from the theme tokens.

Pixels are only ever produced through :class:`MediaProvider`, which asks the pure session whether a record
may be decoded. A hidden, missing, unsupported or media-less record is never passed to the decoder.
"""

from __future__ import annotations

from collections import OrderedDict
from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum

from PySide6.QtCore import (
    QAbstractListModel,
    QModelIndex,
    QObject,
    QPoint,
    QRect,
    QRectF,
    QSize,
    Qt,
    QTimer,
    Signal,
)
from PySide6.QtGui import QColor, QFont, QFontMetrics, QImage, QKeyEvent, QPainter, QPen, QPixmap
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListView,
    QListWidget,
    QListWidgetItem,
    QMenu,
    QPlainTextEdit,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QStyle,
    QStyledItemDelegate,
    QStyleOptionViewItem,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from .components import ActionStrip, NoticeBanner, ResponsiveGrid, StatusChip, repolish
from .edit_components import CompareViewer, ImageCanvas, ZoomControls, motif_image
from .library_domain import (
    ACTION_LABELS,
    HANDOFF_ACTIONS,
    AssetKind,
    SCOPE_LABELS,
    SEMANTIC_UNAVAILABLE,
    SCOPE_SHORT,
    SIMILARITY_LABEL,
    ActionEligibility,
    ActionId,
    AssetGroup,
    AssetRecord,
    Availability,
    Catalog,
    LibraryQuery,
    Scope,
    SearchMode,
    SelectionStatus,
    Sort,
    describe,
    groups_of,
    relations,
    scope_count,
)
from .library_session import LibrarySession, LearningProposal, PlacementProposal
from .motion_components import ElidedLabel
from .tokens import COLORS, RADIUS, SPACE

THUMB_SIZE = (320, 200)
TILE_MIN_WIDTH = 148
TILE_HEIGHT = 154
ROW_HEIGHT = 50
KEY_ROLE = Qt.ItemDataRole.UserRole + 1
Decoder = Callable[[AssetRecord, tuple[int, int]], QImage]

AVAILABILITY_TEXT = {
    Availability.AVAILABLE: "Available",
    Availability.MISSING: "Missing file",
    Availability.HIDDEN: "Hidden by policy",
    Availability.UNSUPPORTED: "Unsupported type",
}


def default_decoder(record: AssetRecord, size: tuple[int, int]) -> QImage:
    """Read one of the four packaged fixture illustrations. The only pixel source in the Library."""
    assert record.motif is not None
    return motif_image(record.motif, record.size or (640, 400)).scaled(
        *size,
        Qt.AspectRatioMode.KeepAspectRatio,
        Qt.TransformationMode.SmoothTransformation,
    )


class MediaProvider(QObject):
    """Deferred, bounded, permission-gated thumbnails and inspector images."""

    thumbnailReady = Signal(str)
    BATCH = 4
    LIMIT = 192

    def __init__(self, session: LibrarySession, decoder: Decoder | None = None):
        super().__init__()
        self.session = session
        self.decoder: Decoder = decoder or default_decoder
        self.decode_count = 0
        self.blocked_count = 0
        self._cache: OrderedDict[str, QPixmap] = OrderedDict()
        self._queue: list[str] = []
        self._scheduled = False

    def permitted(self, key: str) -> AssetRecord | None:
        record, _reason = self.session.media_source(key)
        if record is None:
            self.blocked_count += 1
        return record

    def thumbnail(self, key: str) -> QPixmap | None:
        """The cached thumbnail, or ``None`` after queueing a deferred decode. Never decodes in paint."""
        if key in self._cache:
            self._cache.move_to_end(key)
            return self._cache[key]
        if self.permitted(key) is not None and key not in self._queue:
            self._queue.append(key)
            if not self._scheduled:
                self._scheduled = True
                QTimer.singleShot(0, self._drain)
        return None

    def _drain(self) -> None:
        self._scheduled = False
        for key in self._queue[: self.BATCH]:
            record = self.permitted(key)  # availability may have changed while queued
            if record is not None:
                self.decode_count += 1
                self._cache[key] = QPixmap.fromImage(self.decoder(record, THUMB_SIZE))
                self.thumbnailReady.emit(key)
        del self._queue[: self.BATCH]
        while len(self._cache) > self.LIMIT:
            self._cache.popitem(last=False)
        if self._queue:
            self._scheduled = True
            QTimer.singleShot(0, self._drain)

    def forget(self, key: str) -> None:
        self._cache.pop(key, None)

    def full_image(self, key: str) -> QImage | None:
        """A full-size inspector image, only for a permitted record."""
        record = self.permitted(key)
        if record is None:
            return None
        self.decode_count += 1
        return motif_image(record.motif, record.size or (640, 400))


# ------------------------------------------------------------------------------- card painting
@dataclass(frozen=True)
class CardInfo:
    key: str
    label: str
    type_text: str
    source: str
    availability: Availability
    availability_text: str
    facts: str
    favorite: bool
    collections: int
    order: int  # 1-based selection order, 0 when not selected
    media_note: str


def card_info(session: LibrarySession, key: str) -> CardInfo:
    record = session.catalog.get(key)
    availability = session.availability_of(record)
    text = AVAILABILITY_TEXT[availability]
    if key in session.org.archived:
        text += " · Archived (simulated)"
    bits = []
    if record.size:
        bits.append(f"{record.size[0]}×{record.size[1]}")
    if record.duration is not None:
        bits.append(f"{record.duration:g} s")
    if record.model:
        bits.append(record.model)
    _media, reason = session.media_source(key)
    note = {
        Availability.MISSING: "Missing file",
        Availability.HIDDEN: "Hidden by policy",
        Availability.UNSUPPORTED: "Unsupported type",
    }.get(availability, "")
    if not note and reason:
        note = "Metadata only"
    return CardInfo(
        key,
        record.label,
        record.kind.value,
        record.namespace,
        availability,
        text,
        " · ".join(bits) if bits else "dimensions unknown",
        key in session.org.favorites,
        len(session.org.collections_of(key)),
        session.selection.index(key) + 1 if key in session.selection else 0,
        note,
    )


def _font(base: QFont, delta: int = 0, bold: bool = False) -> QFont:
    font = QFont(base)
    if delta:
        font.setPointSizeF(max(7.0, font.pointSizeF() + delta))
    font.setBold(bold)
    return font


def paint_card(
    painter: QPainter,
    rect: QRect,
    info: CardInfo,
    pixmap: QPixmap | None,
    *,
    grid: bool,
    focus: bool,
    base_font: QFont,
) -> None:
    painter.save()
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    selected = info.order > 0
    card = QRectF(rect).adjusted(2, 2, -2, -2)
    painter.setBrush(QColor(COLORS.selected if selected else COLORS.field))
    painter.setPen(QPen(QColor(COLORS.accent if selected else COLORS.border), 2 if selected else 1))
    painter.drawRoundedRect(card, RADIUS.card, RADIUS.card)
    pad = 8
    if grid:
        preview = QRect(rect.x() + pad + 2, rect.y() + pad + 2, rect.width() - 2 * pad - 4, 76)
    else:
        preview = QRect(rect.x() + 34, rect.y() + 7, 56, rect.height() - 14)
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(QColor(COLORS.background))
    painter.drawRoundedRect(QRectF(preview), 4, 4)
    if pixmap is not None and not pixmap.isNull():
        scaled = pixmap.scaled(
            preview.size(), Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation
        )
        painter.drawPixmap(
            preview.x() + (preview.width() - scaled.width()) // 2,
            preview.y() + (preview.height() - scaled.height()) // 2,
            scaled,
        )
    else:
        painter.setPen(QColor(COLORS.muted))
        painter.setFont(_font(base_font, -1))
        text = info.media_note or "Loading…"
        painter.drawText(preview, Qt.AlignmentFlag.AlignCenter | Qt.TextFlag.TextWordWrap, text)
    # Selection order, favorite and collection membership are three different signals.
    painter.setFont(_font(base_font, -1, True))
    if selected:
        badge = QRect(rect.x() + 6, rect.y() + 6, 22, 20) if grid else QRect(rect.x() + 6, rect.y() + 14, 22, 22)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(COLORS.accent))
        painter.drawRoundedRect(QRectF(badge), 6, 6)
        painter.setPen(QColor(COLORS.on_accent))
        painter.drawText(badge, Qt.AlignmentFlag.AlignCenter, str(info.order))
    painter.setPen(QColor(COLORS.accent))
    if grid:
        marks = ("★ " if info.favorite else "") + (f"▤{info.collections}" if info.collections else "")
        if marks:
            painter.setBrush(QColor(COLORS.background))
            chip = QRect(preview.right() - 46, preview.bottom() - 18, 46, 18)
            painter.drawText(chip, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter, marks.strip())
    fm_font = _font(base_font, 0, True)
    painter.setFont(fm_font)
    fm = QFontMetrics(fm_font)
    painter.setPen(QColor(COLORS.text))
    if grid:
        text_x, width = rect.x() + pad + 2, rect.width() - 2 * pad - 4
        y = preview.bottom() + 4
        painter.drawText(QRect(text_x, y, width, fm.height()), Qt.AlignmentFlag.AlignLeft,
                         fm.elidedText(info.label, Qt.TextElideMode.ElideRight, width))  # fmt: skip
        small = _font(base_font, -1)
        sm = QFontMetrics(small)
        painter.setFont(small)
        painter.setPen(QColor(COLORS.muted))
        y += fm.height()
        line2 = f"{info.type_text} · {info.source}"
        painter.drawText(QRect(text_x, y, width, sm.height()), Qt.AlignmentFlag.AlignLeft,
                         sm.elidedText(line2, Qt.TextElideMode.ElideRight, width))  # fmt: skip
        y += sm.height()
        warn = info.availability != Availability.AVAILABLE or "Archived" in info.availability_text
        painter.setPen(QColor(COLORS.danger if warn else COLORS.muted))
        line3 = info.availability_text if warn else f"{info.availability_text} · {info.facts}"
        painter.drawText(QRect(text_x, y, width, sm.height()), Qt.AlignmentFlag.AlignLeft,
                         sm.elidedText(line3, Qt.TextElideMode.ElideRight, width))  # fmt: skip
    else:
        text_x = preview.right() + 10
        right_w = min(210, max(90, rect.width() // 3))
        width = rect.right() - text_x - right_w - pad
        y = rect.y() + 6
        painter.drawText(QRect(text_x, y, max(20, width), fm.height()), Qt.AlignmentFlag.AlignLeft,
                         fm.elidedText(info.label, Qt.TextElideMode.ElideRight, max(20, width)))  # fmt: skip
        small = _font(base_font, -1)
        sm = QFontMetrics(small)
        painter.setFont(small)
        painter.setPen(QColor(COLORS.muted))
        line2 = f"{info.type_text} · {info.source} · {info.facts}"
        painter.drawText(QRect(text_x, y + fm.height(), max(20, width), sm.height()), Qt.AlignmentFlag.AlignLeft,
                         sm.elidedText(line2, Qt.TextElideMode.ElideRight, max(20, width)))  # fmt: skip
        warn = info.availability != Availability.AVAILABLE
        painter.setPen(QColor(COLORS.danger if warn else COLORS.muted))
        marks = ("★ " if info.favorite else "") + (f"▤{info.collections} " if info.collections else "")
        right = QRect(rect.right() - right_w - pad, y, right_w, rect.height() - 12)
        painter.drawText(right, Qt.AlignmentFlag.AlignRight | Qt.TextFlag.TextWordWrap,
                         sm.elidedText(info.availability_text, Qt.TextElideMode.ElideRight, right_w))  # fmt: skip
        if marks:
            painter.setPen(QColor(COLORS.accent))
            painter.drawText(QRect(rect.right() - right_w - pad, y + sm.height() + 2, right_w, sm.height() + 2),
                             Qt.AlignmentFlag.AlignRight, marks.strip())  # fmt: skip
    if focus:
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.setPen(QPen(QColor(COLORS.text), 2, Qt.PenStyle.DashLine))
        painter.drawRoundedRect(QRectF(rect).adjusted(4, 4, -4, -4), RADIUS.card, RADIUS.card)
    painter.restore()


class AssetTile(QWidget):
    """One asset card as a standalone widget (used in the Component Library). The browser itself uses
    the same painting through :class:`AssetDelegate`, so there is one visual definition."""

    def __init__(self, info: CardInfo, pixmap: QPixmap | None = None, *, grid: bool = True):
        super().__init__()
        self.info, self.pixmap, self.grid = info, pixmap, grid
        if grid:
            self.setFixedSize(TILE_MIN_WIDTH + 12, TILE_HEIGHT)
        else:
            self.setMinimumSize(360, ROW_HEIGHT)
        self.setAccessibleName(f"Asset {info.label}")
        self.setAccessibleDescription(f"{info.type_text}, {info.source}, {info.availability_text}")

    def paintEvent(self, _event) -> None:  # noqa: N802 (Qt API)
        painter = QPainter(self)
        paint_card(painter, self.rect(), self.info, self.pixmap, grid=self.grid, focus=False, base_font=self.font())
        painter.end()


class AssetPageModel(QAbstractListModel):
    """Only the current page's keys: a bounded model, whatever the catalog size."""

    def __init__(self, session: LibrarySession):
        super().__init__()
        self.session = session
        self.keys: list[str] = []

    def rowCount(self, parent=QModelIndex()) -> int:  # noqa: N802 (Qt API)
        return 0 if parent.isValid() else len(self.keys)

    def data(self, index: QModelIndex, role: int = Qt.ItemDataRole.DisplayRole):
        if not index.isValid() or not 0 <= index.row() < len(self.keys):
            return None
        key = self.keys[index.row()]
        if role == KEY_ROLE:
            return key
        if role in (Qt.ItemDataRole.DisplayRole, Qt.ItemDataRole.AccessibleTextRole):
            info = card_info(self.session, key)
            selected = f", selected {info.order}" if info.order else ""
            return f"{info.label}, {info.type_text}, {info.source}, {info.availability_text}{selected}"
        if role == Qt.ItemDataRole.ToolTipRole:
            return f"{key}\n{card_info(self.session, key).availability_text}"
        return None

    def set_keys(self, keys: tuple[str, ...]) -> None:
        self.beginResetModel()
        self.keys = list(keys)
        self.endResetModel()

    def refresh(self) -> None:
        if self.keys:
            self.dataChanged.emit(self.index(0), self.index(len(self.keys) - 1))

    def refresh_key(self, key: str) -> None:
        if key in self.keys:
            row = self.keys.index(key)
            self.dataChanged.emit(self.index(row), self.index(row))

    def row_of(self, key: str) -> int:
        return self.keys.index(key) if key in self.keys else -1


class AssetDelegate(QStyledItemDelegate):
    def __init__(self, view: AssetView):
        super().__init__(view)
        self.view = view

    def sizeHint(self, option, index) -> QSize:  # noqa: N802 (Qt API)
        if self.view.mode == "grid":
            return self.view.tile_size
        return QSize(self.view.viewport().width() - 4, ROW_HEIGHT)

    def paint(self, painter: QPainter, option: QStyleOptionViewItem, index: QModelIndex) -> None:
        key = index.data(KEY_ROLE)
        if key is None:
            return
        focus = bool(option.state & QStyle.StateFlag.State_HasFocus)
        paint_card(
            painter, option.rect, card_info(self.view.session, key), self.view.media.thumbnail(key),
            grid=self.view.mode == "grid", focus=focus, base_font=option.font,
        )  # fmt: skip


class AssetView(QListView):
    """Thumbnail grid and dense list over the same model and the same ordered selection.

    Qt's own selection model is unused: selection is the session's ordered tuple, painted by the
    delegate, so a click never means favorite, rating, parent or Learning evidence.
    """

    selectionRequested = Signal(str, object)  # key, Qt.KeyboardModifier
    activated_key = Signal(str)
    contextRequested = Signal(str, QPoint)
    clearRequested = Signal()
    selectPageRequested = Signal()

    def __init__(self, session: LibrarySession, media: MediaProvider):
        super().__init__()
        self.session, self.media = session, media
        self.mode = "grid"
        self.tile_size = QSize(TILE_MIN_WIDTH + 12, TILE_HEIGHT)
        self.page_model = AssetPageModel(session)
        self.setModel(self.page_model)
        self.setItemDelegate(AssetDelegate(self))
        self.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        self.setVerticalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setUniformItemSizes(True)
        self.setResizeMode(QListView.ResizeMode.Adjust)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setFrameShape(QFrame.Shape.NoFrame)
        self.setMouseTracking(True)
        self.setAccessibleName("Asset results")
        self.setAccessibleDescription(
            "Arrow keys move, Space toggles selection, Enter inspects, Ctrl+A selects the page, "
            "Escape clears the selection, the Menu key opens actions."
        )
        media.thumbnailReady.connect(self.page_model.refresh_key)
        self.set_mode("grid")

    def set_mode(self, mode: str) -> None:
        self.mode = mode
        if mode == "grid":
            self.setViewMode(QListView.ViewMode.IconMode)
            self.setWrapping(True)
            self.setFlow(QListView.Flow.LeftToRight)
            self.setMovement(QListView.Movement.Static)
            self.setSpacing(0)
            self._fit_tiles()
        else:
            self.setViewMode(QListView.ViewMode.ListMode)
            self.setWrapping(False)
            self.setFlow(QListView.Flow.TopToBottom)
            self.setGridSize(QSize())
        self.setAccessibleName("Asset grid" if mode == "grid" else "Asset list")
        self.scheduleDelayedItemsLayout()
        self.viewport().update()

    def _fit_tiles(self) -> None:
        width = max(TILE_MIN_WIDTH, self.viewport().width())
        columns = max(1, width // TILE_MIN_WIDTH)
        self.tile_size = QSize(width // columns - 1, TILE_HEIGHT)
        if self.mode == "grid":
            self.setGridSize(self.tile_size)

    def resizeEvent(self, event) -> None:  # noqa: N802 (Qt API)
        super().resizeEvent(event)
        if self.mode == "grid":
            old = self.tile_size
            self._fit_tiles()
            if old != self.tile_size:
                self.scheduleDelayedItemsLayout()

    # ---------------------------------------------------------------- operator input
    def _key_at(self, pos) -> str | None:
        index = self.indexAt(pos)
        return index.data(KEY_ROLE) if index.isValid() else None

    def mousePressEvent(self, event) -> None:  # noqa: N802 (Qt API)
        key = self._key_at(event.position().toPoint())
        if event.button() == Qt.MouseButton.LeftButton and key:
            self.setCurrentIndex(self.page_model.index(self.page_model.row_of(key)))
            self.selectionRequested.emit(key, event.modifiers())
            event.accept()
            return
        if event.button() == Qt.MouseButton.LeftButton:
            self.setFocus()
        super().mousePressEvent(event)

    def mouseDoubleClickEvent(self, event) -> None:  # noqa: N802 (Qt API)
        key = self._key_at(event.position().toPoint())
        if key:
            self.activated_key.emit(key)

    def contextMenuEvent(self, event) -> None:  # noqa: N802 (Qt API)
        key = self._key_at(event.pos()) if event.reason() == event.Reason.Mouse else self.current_key()
        if key:
            self.contextRequested.emit(key, event.globalPos())

    def current_key(self) -> str | None:
        index = self.currentIndex()
        return index.data(KEY_ROLE) if index.isValid() else None

    def keyPressEvent(self, event: QKeyEvent) -> None:  # noqa: N802 (Qt API)
        key = self.current_key()
        code, mods = event.key(), event.modifiers()
        if code == Qt.Key.Key_Space and key:
            self.selectionRequested.emit(key, Qt.KeyboardModifier.ControlModifier)
            return
        if code in (Qt.Key.Key_Return, Qt.Key.Key_Enter) and key:
            self.activated_key.emit(key)
            return
        if code == Qt.Key.Key_A and mods & Qt.KeyboardModifier.ControlModifier:
            self.selectPageRequested.emit()
            return
        if code == Qt.Key.Key_Escape:
            self.clearRequested.emit()
            return
        if code == Qt.Key.Key_Menu and key:
            rect = self.visualRect(self.currentIndex())
            self.contextRequested.emit(key, self.viewport().mapToGlobal(rect.center()))
            return
        super().keyPressEvent(event)

    def visible_tile_count(self) -> int:
        rect, count = self.viewport().rect(), 0
        for row in range(self.page_model.rowCount()):
            if self.visualRect(self.page_model.index(row)).intersects(rect):
                count += 1
        return count


# ---------------------------------------------------------------------- identity / navigation
class SourceIdentityBadge(ElidedLabel):
    """Namespace and record ID, always visible with the qualified identity as tooltip."""

    def __init__(self, key: str = "", availability: Availability = Availability.AVAILABLE):
        super().__init__()
        self.setProperty("role", "chip")
        self.set_identity(key, availability)

    def set_identity(self, key: str, availability: Availability = Availability.AVAILABLE) -> None:
        namespace, _, record = key.partition(":")
        shown = f"{namespace} · {record}" if key else "no source selected"
        self.set_full_text(f"Source {shown}")
        self.setAccessibleName(f"Source identity: {key or 'none'}, {AVAILABILITY_TEXT[availability]}")
        self.setProperty("level", "info" if availability == Availability.AVAILABLE else "warning")
        repolish(self)


class SourceScopePicker(QWidget):
    """Scopes and collections as presentation filters over fixture records. Not separate repositories."""

    scopeChosen = Signal(str, object)  # Scope value, collection id or None

    def __init__(self):
        super().__init__()
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(SPACE.xs)
        self.heading = QLabel("Source")
        self.heading.setProperty("role", "section")
        outer.addWidget(self.heading)
        self.list = QListWidget()
        self.list.setProperty("role", "nav")
        self.list.setAccessibleName("Source scopes and collections")
        self.list.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.list.setTextElideMode(Qt.TextElideMode.ElideRight)
        outer.addWidget(self.list, 1)
        self.combo = QComboBox()
        self.combo.setAccessibleName("Source scope")
        self.combo.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        self.combo.setMinimumContentsLength(14)
        self.combo.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.combo.hide()
        outer.addWidget(self.combo)
        self.note = QLabel("Scopes filter source-identified fixtures; they are not separate repositories.")
        self.note.setProperty("role", "muted")
        self.note.setWordWrap(True)
        outer.addWidget(self.note)
        self._rows: list[tuple[str, str | None]] = []
        self._building = False
        self.list.currentRowChanged.connect(self._list_changed)
        self.combo.activated.connect(self._combo_changed)

    def set_compact(self, compact: bool) -> None:
        self.list.setVisible(not compact)
        self.heading.setVisible(not compact)
        self.note.setVisible(not compact)
        self.combo.setVisible(compact)

    def refresh(self, session: LibrarySession) -> None:
        self._building = True
        self._rows = []
        self.list.clear()
        self.combo.clear()
        cat, org = session.catalog, session.org

        def add(scope: Scope, collection: str | None, text: str, tip: str = "") -> None:
            self._rows.append((scope.value, collection))
            item = QListWidgetItem(text)
            item.setToolTip(tip or text)
            self.list.addItem(item)
            self.combo.addItem(text.strip())

        for scope in (Scope.ALL, Scope.HISTORY, Scope.EDIT_PHOTO, Scope.VIDEO, Scope.MOTION, Scope.LEARNING, Scope.IMPORTED):
            add(scope, None, f"{SCOPE_SHORT[scope]} ({scope_count(cat, org, scope)})", SCOPE_LABELS[scope])
        add(Scope.COLLECTIONS, None, f"Collections ({scope_count(cat, org, Scope.COLLECTIONS)})", "Every asset that is in at least one collection")
        for collection in org.collections:
            add(Scope.COLLECTIONS, collection.collection_id, f"   ▤ {collection.name} ({len(collection.members)})", f"Collection {collection.name}")
        add(Scope.FAVORITES, None, f"Favorites ({scope_count(cat, org, Scope.FAVORITES)})", SCOPE_LABELS[Scope.FAVORITES])
        want = (session.query.scope.value, session.query.collection)
        row = self._rows.index(want) if want in self._rows else 0
        self.list.setCurrentRow(row)
        self.combo.setCurrentIndex(row)
        self._building = False

    def _list_changed(self, row: int) -> None:
        if self._building or not 0 <= row < len(self._rows):
            return
        self.combo.setCurrentIndex(row)
        self.scopeChosen.emit(*self._rows[row])

    def _combo_changed(self, row: int) -> None:
        if self._building or not 0 <= row < len(self._rows):
            return
        self.list.setCurrentRow(row)


# ------------------------------------------------------------------------------- filter bar
ANY = "Any"
DATE_CHOICES = (("Any time", None), ("Since 2026-10-10", "2026-10-10"), ("Since 2026-10-03", "2026-10-03"), ("Since 2026-10-01", "2026-10-01"))
AVAIL_CHOICES = (("Any state", None), *((AVAILABILITY_TEXT[a], a) for a in Availability))


def _combo(name: str, tip: str = "") -> QComboBox:
    combo = QComboBox()
    combo.setAccessibleName(name)
    combo.setToolTip(tip or name)
    combo.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
    combo.setMinimumContentsLength(6)
    combo.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
    return combo


class AssetFilterBar(QWidget):
    """Search plus explicit filters. Words are ANDed, filter values are ORed, tags need all."""

    changed = Signal()

    def __init__(self):
        super().__init__()
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(SPACE.sm)
        self.search_row = QWidget()
        row = QHBoxLayout(self.search_row)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(SPACE.sm)
        self.search = QLineEdit()
        self.search.setPlaceholderText("Search indexed fixture fields…")
        self.search.setClearButtonEnabled(True)
        self.search.setAccessibleName("Search assets")
        self.mode = _combo("Search mode", "Metadata and bounded prompt-prefix search. Semantic search is not available.")
        self.mode.addItem("Metadata", SearchMode.METADATA)
        self.mode.addItem("Prompt prefix", SearchMode.PROMPT_PREFIX)
        self.mode.addItem("Semantic — unavailable", None)
        self.mode.setItemData(0, "Searches label, ID, model, workflow, kind and tags", Qt.ItemDataRole.ToolTipRole)
        self.mode.setItemData(1, "Matches the start of the first 48 characters of a fixture prompt", Qt.ItemDataRole.ToolTipRole)
        self.mode.setItemData(2, SEMANTIC_UNAVAILABLE, Qt.ItemDataRole.ToolTipRole)
        self.mode.model().item(2).setEnabled(False)
        self.sort = _combo("Sort order")
        for value in Sort:
            self.sort.addItem(value.value, value)
        row.addWidget(self.search, 3)
        row.addWidget(self.mode, 2)
        row.addWidget(self.sort, 1)
        outer.addWidget(self.search_row)
        self.filters = ResponsiveGrid(min_column_width=158, column_gap=SPACE.sm)
        self.kind = _combo("Asset type")
        self.category = _combo("Source category")
        self.model = _combo("Model or workflow")
        self.recency = _combo("Date or recency")
        self.availability = _combo("Availability")
        self.tag = _combo("Tag")
        self.collection = _combo("Collection")
        self.favorites = QCheckBox("Favorites only")
        self.favorites.setAccessibleName("Favorites only")
        for widget in (self.kind, self.category, self.model, self.recency, self.availability, self.tag, self.collection, self.favorites):
            self.filters.add(widget)
        outer.addWidget(self.filters)
        self.semantics = QLabel("")
        self.semantics.setProperty("role", "muted")
        self.semantics.setWordWrap(True)
        self.semantics.hide()
        outer.addWidget(self.semantics)
        self._loading = False
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(120)  # a keystroke never re-queries the catalog immediately
        self._timer.timeout.connect(self.changed.emit)
        self.search.textChanged.connect(lambda _t: self._timer.start())
        for combo in (self.mode, self.sort, self.kind, self.category, self.model, self.recency, self.availability, self.tag, self.collection):
            combo.activated.connect(lambda _i: self._emit())
        self.favorites.toggled.connect(lambda _c: self._emit())

    def _emit(self) -> None:
        if not self._loading:
            self._timer.stop()
            self.changed.emit()

    def flush(self) -> None:
        """Apply a pending debounced search now (used by tests and when leaving the field)."""
        if self._timer.isActive():
            self._timer.stop()
            self.changed.emit()

    def populate(self, catalog: Catalog, session: LibrarySession) -> None:
        """Fill the value lists from fixture metadata and the organizing state, keeping selections."""
        self._loading = True
        keep = self.query_changes()
        for combo, entries in (
            (self.kind, ((ANY, None), *((k, k) for k in sorted({r.kind for r in catalog}, key=str)))),
            (self.category, ((ANY, None), *((c, c) for c in sorted({r.category for r in catalog})))),
            (self.model, ((ANY, None), *((m, m) for m in sorted({r.model for r in catalog if r.model})))),
            (self.recency, DATE_CHOICES),
            (self.availability, AVAIL_CHOICES),
            (self.tag, ((ANY, None), *((t, t) for t in session.org.all_tags()))),
            (self.collection, ((ANY, None), *((c.name, c.collection_id) for c in session.org.collections))),
        ):
            combo.clear()
            for text, data in entries:
                combo.addItem(f"{getattr(data, 'value', text)}" if combo is self.kind and data else text, data)
        self.kind.setItemText(0, "Any type")
        self.category.setItemText(0, "Any source")
        self.model.setItemText(0, "Any model")
        self.tag.setItemText(0, "Any tag")
        self.collection.setItemText(0, "Any collection")
        self._restore(keep)
        self._loading = False

    def _restore(self, changes: dict) -> None:
        for combo, name in ((self.kind, "kinds"), (self.category, "categories"), (self.model, "models"),
                            (self.availability, "availability"), (self.tag, "tags")):  # fmt: skip
            value = next(iter(changes.get(name) or ()), None)
            combo.setCurrentIndex(max(0, combo.findData(value)))
        self.collection.setCurrentIndex(max(0, self.collection.findData(changes.get("collection"))))
        self.recency.setCurrentIndex(max(0, self.recency.findData(changes.get("date_from"))))

    def query_changes(self) -> dict:
        def one(combo: QComboBox) -> frozenset:
            data = combo.currentData()
            return frozenset({data}) if data is not None else frozenset()

        # Qt hands StrEnum item data back as a plain str: restore the enum so the query stays typed.
        mode = SearchMode(self.mode.currentData() or SearchMode.METADATA)
        kinds = one(self.kind) if self.kind.count() else frozenset()
        return {
            "text": self.search.text(),
            "mode": mode,
            "sort": Sort(self.sort.currentData() or Sort.RECENT),
            "kinds": frozenset(AssetKind(k) for k in kinds),
            "categories": one(self.category) if self.category.count() else frozenset(),
            "models": one(self.model) if self.model.count() else frozenset(),
            "availability": frozenset(Availability(a) for a in one(self.availability)) if self.availability.count() else frozenset(),
            "tags": one(self.tag) if self.tag.count() else frozenset(),
            "collection": self.collection.currentData() if self.collection.count() else None,
            "date_from": self.recency.currentData() if self.recency.count() else None,
            "favorites_only": self.favorites.isChecked(),
        }

    def show_query(self, query: LibraryQuery) -> None:
        """Mirror a query that changed elsewhere (restore, clear, scope change) without emitting."""
        self._loading = True
        self.search.setText(query.text)
        self.mode.setCurrentIndex(max(0, self.mode.findData(query.mode)))
        self.sort.setCurrentIndex(max(0, self.sort.findData(query.sort)))
        self.favorites.setChecked(query.favorites_only)
        self._restore({
            "kinds": query.kinds, "categories": query.categories, "models": query.models,
            "availability": query.availability, "tags": query.tags,
            "collection": query.collection, "date_from": query.date_from,
        })  # fmt: skip
        self._loading = False


# --------------------------------------------------------------------------------- details
class SimilarityGroupPanel(QWidget):
    """Exact-content and illustrative-similarity groups. Neither merges records or implies provenance."""

    memberChosen = Signal(str)

    def __init__(self):
        super().__init__()
        self._layout = QVBoxLayout(self)
        self._layout.setContentsMargins(0, 0, 0, 0)
        self._layout.setSpacing(SPACE.sm)

    def set_groups(self, groups: tuple[AssetGroup, ...], current: str) -> None:
        while self._layout.count():
            item = self._layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.hide()
                widget.setParent(None)
                widget.deleteLater()
        for group in groups:
            title = QLabel(group.label)
            title.setProperty("role", "chip")
            title.setProperty("level", "info" if group.exact else "warning")
            title.setWordWrap(True)
            title.setAccessibleName(f"Group: {group.label}")
            self._layout.addWidget(title)
            caveat = QLabel(group.caveat)
            caveat.setProperty("role", "muted")
            caveat.setWordWrap(True)
            self._layout.addWidget(caveat)
            for member in group.members:
                if member == current:
                    continue
                button = QPushButton(f"Select {member}")
                button.setAccessibleName(f"Select group member {member}")
                button.clicked.connect(lambda _c=False, k=member: self.memberChosen.emit(k))
                self._layout.addWidget(button)


def _fact_label(text: str, role: str = "") -> QLabel:
    label = QLabel(text)
    label.setTextFormat(Qt.TextFormat.PlainText)
    label.setWordWrap(True)
    label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
    if role:
        label.setProperty("role", role)
    return label


class AssetDetailsPanel(QWidget):
    """Source identity, lineage, availability, related items, collections and tags for one asset."""

    relationChosen = Signal(str)
    inspectRequested = Signal(str)

    def __init__(self):
        super().__init__()
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.scroll.setAccessibleName("Asset details")
        outer.addWidget(self.scroll)
        self.body = QWidget()
        self.layout_ = QVBoxLayout(self.body)
        self.layout_.setContentsMargins(SPACE.sm, SPACE.sm, SPACE.sm, SPACE.sm)
        self.layout_.setSpacing(SPACE.sm)
        self.scroll.setWidget(self.body)
        self.badge = SourceIdentityBadge()
        self.layout_.addWidget(self.badge)
        self.title = _fact_label("", "section")
        self.layout_.addWidget(self.title)
        self.preview = QLabel()
        self.preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.preview.setMinimumHeight(96)
        self.preview.setProperty("role", "tile")
        self.preview.setWordWrap(True)
        self.preview.setAccessibleName("Asset preview")
        self.layout_.addWidget(self.preview)
        self.status = StatusChip("", "info")
        self.layout_.addWidget(self.status)
        self.inspect = QPushButton("Inspect…")
        self.inspect.setAccessibleName("Inspect selected asset")
        self.inspect.clicked.connect(lambda: self.inspectRequested.emit(self._key))
        self.layout_.addWidget(self.inspect)
        self.facts = QWidget()
        self.facts_layout = QVBoxLayout(self.facts)
        self.facts_layout.setContentsMargins(0, 0, 0, 0)
        self.facts_layout.setSpacing(2)
        self.layout_.addWidget(self.facts)
        self.groups = SimilarityGroupPanel()
        self.layout_.addWidget(self.groups)
        self.related = QWidget()
        self.related_layout = QVBoxLayout(self.related)
        self.related_layout.setContentsMargins(0, 0, 0, 0)
        self.layout_.addWidget(self.related)
        self.layout_.addStretch(1)
        self.groups.memberChosen.connect(self.relationChosen)
        self._key = ""

    @staticmethod
    def _clear(layout: QVBoxLayout) -> None:
        while layout.count():
            item = layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.hide()
                widget.setParent(None)
                widget.deleteLater()

    def show_none(self) -> None:
        self._key = ""
        self.badge.set_identity("")
        self.title.setText("No selection")
        self.preview.setPixmap(QPixmap())
        self.preview.setText("Select an asset to see its source identity, lineage and compatible actions.")
        self.status.set_status("Nothing selected", "info")
        self.inspect.setEnabled(False)
        for layout in (self.facts_layout, self.related_layout):
            self._clear(layout)
        self.groups.set_groups((), "")

    def show_asset(self, session: LibrarySession, key: str, media: MediaProvider, extra: str = "") -> None:
        record = session.catalog.get(key)
        availability = session.availability_of(record)
        self._key = key
        self.badge.set_identity(key, availability)
        self.title.setText(record.label)
        pixmap = media.thumbnail(key)
        if pixmap is not None:
            self.preview.setText("")
            self.preview.setPixmap(pixmap.scaledToWidth(min(240, max(120, self.width() - 40)), Qt.TransformationMode.SmoothTransformation))
        else:
            _source, reason = session.media_source(key)
            self.preview.setPixmap(QPixmap())
            self.preview.setText(reason or "Loading preview…")
        text = AVAILABILITY_TEXT[availability] + (" · Archived (simulated Photo policy)" if key in session.org.archived else "")
        self.status.set_status(text, "success" if availability == Availability.AVAILABLE else "warning")
        self.inspect.setEnabled(True)
        self._clear(self.facts_layout)
        if extra:
            self.facts_layout.addWidget(_fact_label(extra, "muted"))
        for row in describe(record):
            self.facts_layout.addWidget(_fact_label(f"{row.name}: {row.value}"))
        org = session.org
        collections = ", ".join(c.name for c in org.collections_of(key)) or "none"
        tags = ", ".join(org.tags_of(key)) or "none"
        self.facts_layout.addWidget(_fact_label(f"Collections: {collections}"))
        self.facts_layout.addWidget(_fact_label(f"Tags: {tags}"))
        self.facts_layout.addWidget(_fact_label(f"Favorite: {'yes' if key in org.favorites else 'no'}"))
        for line in availability_lines(session, key):
            self.facts_layout.addWidget(_fact_label(line, "muted"))
        self.groups.set_groups(groups_of(session.catalog, key), key)
        self._clear(self.related_layout)
        rels = [r for r in relations(session.catalog, key) if not r.caveat.startswith(("Same content", SIMILARITY_LABEL))]
        if rels:
            head = _fact_label("Related items", "section")
            self.related_layout.addWidget(head)
        for relation in rels:
            button = QPushButton(f"{relation.kind}: {relation.key}")
            button.setToolTip(relation.caveat)
            button.setAccessibleName(f"Select related {relation.kind.lower()} {relation.key}")
            button.clicked.connect(lambda _c=False, k=relation.key: self.relationChosen.emit(k))
            self.related_layout.addWidget(button)


def availability_lines(session: LibrarySession, key: str) -> list[str]:
    record = session.catalog.get(key)
    availability = session.availability_of(record)
    out = []
    if availability != Availability.AVAILABLE:
        from .library_domain import availability_reason

        out.append(availability_reason(availability))
    if key in session.overrides:
        out.append("State changed during this session (fixture simulation); the original record said "
                   f"{record.availability.value}.")  # fmt: skip
    observations = session.catalog.observations_of(key)
    if observations:
        out.append(f"Referenced by {len(observations)} research observation(s): {', '.join(observations)}.")
    return out


# ------------------------------------------------------------------------------ action menu
class AssetActionMenu(QWidget):
    """Every action with an explicit eligibility. Disabled actions say why, in words."""

    actionRequested = Signal(str)

    def __init__(self):
        super().__init__()
        self._layout = QVBoxLayout(self)
        self._layout.setContentsMargins(SPACE.sm, SPACE.sm, SPACE.sm, SPACE.sm)
        self._layout.setSpacing(SPACE.sm)
        self.buttons: dict[ActionId, QPushButton] = {}
        self.reasons: dict[ActionId, QLabel] = {}
        self.summary = _fact_label("", "muted")
        self._layout.addWidget(self.summary)
        for action in ACTION_LABELS:
            box = QWidget()
            col = QVBoxLayout(box)
            col.setContentsMargins(0, 0, 0, 0)
            col.setSpacing(2)
            button = QPushButton(ACTION_LABELS[action])
            button.setAccessibleName(f"Action: {ACTION_LABELS[action]}")
            button.clicked.connect(lambda _c=False, a=action: self.actionRequested.emit(a.value))
            reason = _fact_label("", "muted")
            col.addWidget(button)
            col.addWidget(reason)
            self.buttons[action], self.reasons[action] = button, reason
            self._layout.addWidget(box)
        self._layout.addStretch(1)

    @staticmethod
    def enabled(item: ActionEligibility) -> bool:
        if item.gated or not item.verdicts:
            return False
        if item.action in HANDOFF_ACTIONS:
            return bool(item.eligible)
        return item.placeable

    def set_eligibility(self, items: tuple[ActionEligibility, ...], count: int) -> None:
        self.summary.setText(
            f"Actions for {count} selected asset(s). A button is disabled when the whole selection cannot be "
            "placed; the reason is shown beneath it."
            if count
            else "Select one or more assets to see compatible actions."
        )
        for item in items:
            button, reason = self.buttons[item.action], self.reasons[item.action]
            ok = self.enabled(item)
            suffix = "…" if item.action in HANDOFF_ACTIONS else ""
            button.setText(item.label + suffix)
            button.setEnabled(ok)
            note = item.reason if (not item.placeable and count) else ""
            if ok and item.needs_narrowing:
                note = f"Opens the review: {item.reason}"
            reason.setText(note)
            reason.setVisible(bool(note))
            button.setToolTip(note or ACTION_LABELS[item.action])


def build_action_menu(items: tuple[ActionEligibility, ...], parent: QWidget, trigger: Callable[[str], None]) -> QMenu:
    menu = QMenu(parent)
    menu.setToolTipsVisible(True)
    menu.setAccessibleName("Asset actions")
    for item in items:
        ok = AssetActionMenu.enabled(item)
        suffix = "…" if item.action in HANDOFF_ACTIONS else ""
        action = menu.addAction(item.label + suffix)
        action.setEnabled(ok)
        action.setToolTip(item.reason or item.label)
        action.triggered.connect(lambda _c=False, a=item.action: trigger(a.value))
    return menu


# ----------------------------------------------------------------------------- selection strip
class MultiSelectionStrip(ActionStrip):
    """Anchored, always visible: ordered selection, off-page status and the action entry points.

    Built on the shared ActionStrip, so the summary wraps above the buttons instead of squeezing them."""

    clearRequested = Signal()
    detailsRequested = Signal()
    organizeRequested = Signal()

    CHIPS = 4

    def __init__(self):
        super().__init__()
        self.setAccessibleName("Selection")
        self.status.setAccessibleName("Selection summary")
        self.status.setTextFormat(Qt.TextFormat.PlainText)
        self.clear = self.add_action("Clear selection")
        self.clear.setAccessibleName("Clear selection")
        self.clear.clicked.connect(self.clearRequested)
        self.organize = self.add_action("Organize")
        self.organize.setAccessibleName("Organize selection: collections, tags and favorites")
        self.organize.clicked.connect(self.organizeRequested)
        self.details = self.add_action("Details")
        self.details.setAccessibleName("Show details")
        self.details.clicked.connect(self.detailsRequested)
        self.actions = self.add_action("Actions ▾", primary=True)
        self.actions.setAccessibleName("Actions for the selection")

    def set_selection(self, session: LibrarySession) -> None:
        keys = session.selection
        if not keys:
            self.status.setText("No selection · click an asset; Ctrl+click adds, Shift+click selects a range")
            self.status.setToolTip("")
        else:
            report = session.selection_report()
            off = sum(1 for s in report.values() if s != SelectionStatus.ON_PAGE)
            shown = ", ".join(f"{i}·{k}" for i, k in enumerate(keys[: self.CHIPS], 1))
            more = f" +{len(keys) - self.CHIPS} more" if len(keys) > self.CHIPS else ""
            away = f" · {off} not on this page" if off else ""
            self.status.setText(f"{len(keys)} selected{away}: {shown}{more}")
            self.status.setToolTip("\n".join(f"{i}. {k} — {report[k].value}" for i, k in enumerate(keys, 1)))
        self.clear.setEnabled(bool(keys))
        self.actions.setEnabled(bool(keys))
        self.organize.setEnabled(bool(keys))


# --------------------------------------------------------------------- organize (collections, tags)
class TagEditor(QWidget):
    def __init__(self):
        super().__init__()
        col = QVBoxLayout(self)
        col.setContentsMargins(0, 0, 0, 0)
        col.setSpacing(SPACE.sm)
        self.current = _fact_label("Tags: none", "muted")
        col.addWidget(self.current)
        self.edit = QLineEdit()
        self.edit.setPlaceholderText("Tag name")
        self.edit.setAccessibleName("Tag name")
        col.addWidget(self.edit)
        row = QHBoxLayout()
        self.add = QPushButton("Add tag")
        self.add.setAccessibleName("Add tag to selection")
        self.remove = QPushButton("Remove tag")
        self.remove.setAccessibleName("Remove tag from selection")
        row.addWidget(self.add)
        row.addWidget(self.remove)
        col.addLayout(row)


class CollectionPanel(QWidget):
    def __init__(self):
        super().__init__()
        col = QVBoxLayout(self)
        col.setContentsMargins(0, 0, 0, 0)
        col.setSpacing(SPACE.sm)
        self.target = _combo("Target collection")
        col.addWidget(self.target)
        self.name = QLineEdit()
        self.name.setPlaceholderText("Collection name")
        self.name.setAccessibleName("Collection name")
        col.addWidget(self.name)
        grid = ResponsiveGrid(min_column_width=120, column_gap=SPACE.sm)
        self.new = QPushButton("New collection")
        self.rename = QPushButton("Rename")
        self.rename.setAccessibleName("Rename target collection")
        self.add = QPushButton("Add selected")
        self.add.setAccessibleName("Add selected assets to the target collection")
        self.remove = QPushButton("Remove references")
        self.remove.setAccessibleName("Remove selected references from the target collection")
        for button in (self.new, self.rename, self.add, self.remove):
            grid.add(button)
        col.addWidget(grid)
        note = _fact_label("Removing a reference never deletes, moves or changes the source artifact.", "muted")
        col.addWidget(note)


class OrganizePanel(QWidget):
    def __init__(self):
        super().__init__()
        scroll_body = QWidget()
        col = QVBoxLayout(scroll_body)
        col.setContentsMargins(SPACE.sm, SPACE.sm, SPACE.sm, SPACE.sm)
        col.setSpacing(SPACE.md)
        col.addWidget(_fact_label("Collections", "section"))
        self.collections = CollectionPanel()
        col.addWidget(self.collections)
        col.addWidget(_fact_label("Tags", "section"))
        self.tags = TagEditor()
        col.addWidget(self.tags)
        col.addWidget(_fact_label("Favorites", "section"))
        row = QHBoxLayout()
        self.favorite = QPushButton("Favorite")
        self.unfavorite = QPushButton("Unfavorite")
        row.addWidget(self.favorite)
        row.addWidget(self.unfavorite)
        col.addLayout(row)
        col.addWidget(_fact_label("A favorite is not a rating, a selection, a parent link or Learning evidence.", "muted"))
        col.addWidget(_fact_label("History", "section"))
        row2 = QHBoxLayout()
        self.undo = QPushButton("Undo")
        self.redo = QPushButton("Redo")
        row2.addWidget(self.undo)
        row2.addWidget(self.redo)
        col.addLayout(row2)
        col.addStretch(1)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setWidget(scroll_body)
        scroll.setAccessibleName("Organize")
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(scroll)


class InspectorTabs(QTabWidget):
    """Details / Actions / Organize in one panel (side panel, drawer or inspector tab)."""

    def __init__(self, details: QWidget, actions: QWidget, organize: QWidget):
        super().__init__()
        self.setAccessibleName("Inspector")
        self.setDocumentMode(True)
        for widget, name in ((details, "Details"), (actions, "Actions"), (organize, "Organize")):
            if isinstance(widget, AssetActionMenu):
                scroll = QScrollArea()
                scroll.setWidgetResizable(True)
                scroll.setFrameShape(QFrame.Shape.NoFrame)
                scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
                scroll.setWidget(widget)
                scroll.setAccessibleName("Compatible actions")
                widget = scroll
            self.addTab(widget, name)


# ------------------------------------------------------------------------------- dialogs
class ReviewChoice(StrEnum):
    CANCEL = "cancel"
    PLACE = "place"
    REPLACE = "replace"
    NARROW = "narrow"


class CompatibilityReview(QDialog):
    """Whole-selection preflight: eligible and blocked separately, what is copied, kept, reset, discarded."""

    def __init__(self, proposal: PlacementProposal, parent: QWidget | None = None):
        super().__init__(parent)
        self.proposal = proposal
        self.choice = ReviewChoice.CANCEL
        self.narrowed: tuple[str, ...] = ()
        self.setWindowTitle(f"Place into {proposal.destination}")
        self.setAccessibleName("Placement review")
        self.setModal(True)
        self.resize(600, 560)
        eligibility = proposal.eligibility
        outer = QVBoxLayout(self)
        outer.setSpacing(SPACE.sm)
        head = QLabel(f"{eligibility.label} → {proposal.destination}")
        head.setProperty("role", "section")
        head.setWordWrap(True)
        outer.addWidget(head)
        counts = QLabel(f"{len(proposal.items)} selected · {len(eligibility.eligible)} can be placed · {len(eligibility.blocked)} blocked")
        counts.setProperty("role", "muted")
        outer.addWidget(counts)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setAccessibleName("Placement details")
        body = QWidget()
        col = QVBoxLayout(body)
        col.setSpacing(SPACE.sm)
        col.setContentsMargins(0, 0, SPACE.sm, 0)
        scroll.setWidget(body)
        outer.addWidget(scroll, 1)
        if eligibility.set_reason:
            banner = NoticeBanner()
            banner.set_message("Narrow the selection", eligibility.set_reason, "warning")
            col.addWidget(banner)
        if proposal.needs_replace:
            banner = NoticeBanner()
            banner.set_message("Unsaved work", f"{proposal.replace_detail} Replace or Cancel; Cancel changes nothing.", "warning")
            banner.setAccessibleName("Replacement warning")
            col.addWidget(banner)
        col.addWidget(_fact_label("Can be placed (selected order)", "section"))
        self.eligible = QListWidget()
        self.eligible.setAccessibleName("Items that can be placed")
        self.eligible.setMinimumHeight(60)
        self.eligible.setMaximumHeight(120)
        narrowing = proposal.needs_narrowing
        for n, key in enumerate(proposal.items, 1):
            if key in eligibility.eligible:
                item = QListWidgetItem(f"{n}. {key}")
                item.setData(KEY_ROLE, key)
                if narrowing:
                    item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
                    item.setCheckState(Qt.CheckState.Checked)
                self.eligible.addItem(item)
        col.addWidget(self.eligible)
        if eligibility.blocked:
            col.addWidget(_fact_label("Blocked, with reasons", "section"))
            self.blocked = QListWidget()
            self.blocked.setAccessibleName("Items that are blocked")
            self.blocked.setWordWrap(True)
            self.blocked.setMaximumHeight(150)
            for verdict in eligibility.blocked:
                self.blocked.addItem(f"{verdict.key} — {verdict.reason}")
            col.addWidget(self.blocked)
        for title, lines in (
            ("Copied to the destination draft", [f"{k}: {v}" for k, v in proposal.copied]),
            ("Preserved", list(proposal.preserved)),
            ("Reset or not applicable", list(proposal.reset)),
            ("Discarded", list(proposal.discarded) or ["Nothing is discarded."]),
            ("Notes", list(proposal.notes)),
        ):
            if lines:
                col.addWidget(_fact_label(title, "section"))
                col.addWidget(_fact_label("\n".join(f"• {x}" for x in lines)))
        col.addStretch(1)
        row = QHBoxLayout()
        row.addStretch(1)
        self.buttons: dict[str, QPushButton] = {}
        self.buttons["cancel"] = QPushButton("Cancel")
        self.buttons["cancel"].setAccessibleName("Cancel placement")
        row.addWidget(self.buttons["cancel"])
        if narrowing:
            self.buttons["narrow"] = QPushButton("Narrow selection to checked")
            self.buttons["narrow"].setProperty("role", "primary")
            row.addWidget(self.buttons["narrow"])
            self.eligible.itemChanged.connect(self._enforce_capacity)
            self.buttons["narrow"].clicked.connect(self._narrow)
        elif proposal.needs_replace and proposal.can_place:
            self.buttons["replace"] = QPushButton("Replace draft and place")
            self.buttons["replace"].setProperty("role", "primary")
            row.addWidget(self.buttons["replace"])
            self.buttons["replace"].clicked.connect(lambda: self._finish(ReviewChoice.REPLACE))
        elif proposal.can_place:
            self.buttons["place"] = QPushButton("Place")
            self.buttons["place"].setProperty("role", "primary")
            row.addWidget(self.buttons["place"])
            self.buttons["place"].clicked.connect(lambda: self._finish(ReviewChoice.PLACE))
        for button in self.buttons.values():
            button.ensurePolished()
            button.setMinimumWidth(button.sizeHint().width() + 8)
        self.buttons["cancel"].setDefault(True)
        self.buttons["cancel"].clicked.connect(lambda: self._finish(ReviewChoice.CANCEL))
        outer.addLayout(row)

    def _checked(self) -> tuple[str, ...]:
        return tuple(
            self.eligible.item(i).data(KEY_ROLE)
            for i in range(self.eligible.count())
            if self.eligible.item(i).checkState() == Qt.CheckState.Checked
        )

    def _enforce_capacity(self, changed: QListWidgetItem) -> None:
        from .library_domain import CAPACITY

        cap = CAPACITY.get(self.proposal.action)
        checked = self._checked()
        if cap is not None and len(checked) > cap and changed.checkState() == Qt.CheckState.Checked:
            self.eligible.blockSignals(True)
            for i in range(self.eligible.count()):
                item = self.eligible.item(i)
                if item is not changed and item.checkState() == Qt.CheckState.Checked and len(self._checked()) > cap:
                    item.setCheckState(Qt.CheckState.Unchecked)
            self.eligible.blockSignals(False)
        self.buttons["narrow"].setEnabled(bool(self._checked()))

    def _narrow(self) -> None:
        self.narrowed = self._checked()
        self._finish(ReviewChoice.NARROW)

    def _finish(self, choice: ReviewChoice) -> None:
        self.choice = choice
        self.accept() if choice != ReviewChoice.CANCEL else self.reject()


def proposal_text(proposal: LearningProposal) -> str:
    lines = [f"{proposal.proposal_id} · {proposal.status}", "", f"Intended research context: {proposal.context}", "", "Sources (selected order)"]
    for n, s in enumerate(proposal.sources, 1):
        lines += [
            f"{n}. {s.key}  [{s.kind}]  namespace {s.namespace}",
            f"   label: {s.label}",
            f"   observation ID: {s.observation_id} · job lineage: {s.job_id}",
            f"   content hash: {s.content_hash} · model: {s.model}",
            f"   rating: {s.rating} · experiment: {s.experiment}",
        ]
    lines += ["", "Evidence limitations"] + [f"• {x}" for x in proposal.limitations]
    lines += ["", f"executable: {proposal.executable} · is a study: {proposal.is_study}"]
    return "\n".join(lines)


class LearningProposalDialog(QDialog):
    """Read-only. This is the QT-DS-06 handoff contract, not a Learning screen."""

    def __init__(self, proposal: LearningProposal, parent: QWidget | None = None):
        super().__init__(parent)
        self.setWindowTitle("Mock Learning source proposal")
        self.setAccessibleName("Learning proposal")
        self.resize(620, 520)
        col = QVBoxLayout(self)
        banner = NoticeBanner()
        banner.set_message("Not a study", "A non-executable, inspectable placement summary. Nothing was submitted.", "warning")
        col.addWidget(banner)
        self.text = QPlainTextEdit(proposal_text(proposal))
        self.text.setReadOnly(True)
        self.text.setAccessibleName("Proposal summary")
        col.addWidget(self.text, 1)
        self.close_button = QPushButton("Close")
        self.close_button.clicked.connect(self.accept)
        col.addWidget(self.close_button, 0, Qt.AlignmentFlag.AlignRight)


class InspectDialog(QDialog):
    """Image inspection with Fit/100%, zoom and pan for permitted stills, metadata for everything else.

    Non-modal: closing it returns to the results with the Library context untouched."""

    compareRequested = Signal(str)

    def __init__(self, session: LibrarySession, media: MediaProvider, key: str, parent: QWidget | None = None):
        super().__init__(parent)
        self.key = key
        record = session.catalog.get(key)
        self.setWindowTitle(f"Inspect {key}")
        self.setAccessibleName("Asset inspector")
        self.setModal(False)
        self.resize(720, 560)
        col = QVBoxLayout(self)
        col.addWidget(SourceIdentityBadge(key, session.availability_of(record)))
        self.canvas = ImageCanvas(interactive=False)
        self.canvas.setAccessibleName("Inspected image")
        self.zoom = ZoomControls(self.canvas)
        image = media.full_image(key)
        _src, reason = session.media_source(key)
        if image is not None:
            self.canvas.set_image(image)
            col.addWidget(self.zoom)
            col.addWidget(self.canvas, 1)
        else:
            self.canvas.hide()
            self.zoom.hide()
            info = _fact_label(reason or "No image is available.")
            info.setAccessibleName("Why there is no image")
            col.addWidget(info)
        self.info = QPlainTextEdit("\n".join(f"{r.name}: {r.value}" for r in describe(record)))
        self.info.setReadOnly(True)
        self.info.setMaximumHeight(170)
        self.info.setAccessibleName("Source and provenance details")
        col.addWidget(self.info)
        row = QHBoxLayout()
        self.compare = QPushButton("Compare with parent")
        self.compare.setEnabled(session.evaluate(ActionId.COMPARE, (key,)).placeable)
        if not self.compare.isEnabled():
            self.compare.setToolTip(session.evaluate(ActionId.COMPARE, (key,)).reason)
        self.compare.clicked.connect(lambda: self.compareRequested.emit(key))
        self.close_button = QPushButton("Close and return to results")
        self.close_button.clicked.connect(self.close)
        row.addWidget(self.compare)
        row.addStretch(1)
        row.addWidget(self.close_button)
        col.addLayout(row)


class CompareDialog(QDialog):
    """Direct-parent comparison of two permitted stills. Arbitrary or video pairs are never offered."""

    def __init__(self, session: LibrarySession, media: MediaProvider, key: str, parent: QWidget | None = None):
        super().__init__(parent)
        self.setWindowTitle("Compare with parent")
        self.setAccessibleName("Parent comparison")
        self.setModal(False)
        self.resize(820, 520)
        col = QVBoxLayout(self)
        parent_record, child = session.compare_pair(key)
        left, right = media.full_image(parent_record.key), media.full_image(child.key)
        self.viewer = CompareViewer()
        if left is None or right is None:
            raise ValueError("A comparison image is not permitted.")
        self.viewer.set_pair(left, right, f"Parent {parent_record.key}", f"Derived {child.key}")
        col.addWidget(self.viewer, 1)
        col.addWidget(_fact_label("Direct parent only, established by the recorded lineage. This is not an arbitrary comparison.", "muted"))
        self.close_button = QPushButton("Close")
        self.close_button.clicked.connect(self.close)
        col.addWidget(self.close_button, 0, Qt.AlignmentFlag.AlignRight)


class StatePanel(QFrame):
    """Empty source, no matches, loading and read errors are different pages, never one blank list."""

    def __init__(self):
        super().__init__()
        self.setProperty("role", "card")
        col = QVBoxLayout(self)
        col.setContentsMargins(SPACE.gutter, SPACE.gutter, SPACE.gutter, SPACE.gutter)
        col.setSpacing(SPACE.md)
        col.addStretch(1)
        self.title = QLabel("")
        self.title.setProperty("role", "section")
        self.title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.title.setWordWrap(True)
        self.body = QLabel("")
        self.body.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.body.setWordWrap(True)
        self.body.setProperty("role", "muted")
        self.action = QPushButton("")
        col.addWidget(self.title)
        col.addWidget(self.body)
        col.addWidget(self.action, 0, Qt.AlignmentFlag.AlignCenter)
        col.addStretch(1)

    def show_state(self, title: str, body: str, action: str = "") -> None:
        self.setAccessibleName(title)
        self.title.setText(title)
        self.body.setText(body)
        self.action.setText(action)
        self.action.setAccessibleName(action)
        self.action.setVisible(bool(action))


__all__ = [
    "AssetActionMenu", "AssetDelegate", "AssetDetailsPanel", "AssetFilterBar", "AssetPageModel", "AssetTile",
    "AssetView", "CardInfo", "CollectionPanel", "CompareDialog", "CompatibilityReview", "InspectDialog",
    "InspectorTabs", "LearningProposalDialog", "MediaProvider", "MultiSelectionStrip", "OrganizePanel",
    "ReviewChoice", "SimilarityGroupPanel", "SourceIdentityBadge", "SourceScopePicker", "StatePanel",
    "TagEditor", "build_action_menu", "card_info", "paint_card",
]  # fmt: skip
