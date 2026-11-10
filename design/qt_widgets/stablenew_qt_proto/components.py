"""Reusable Qt Widgets components for a Figma-independent design assessment.

No StableNew production modules, backend clients or job services are imported.
"""

from __future__ import annotations

from PySide6.QtCore import QEvent, QObject, Qt, Signal
from PySide6.QtGui import QFontMetrics
from PySide6.QtWidgets import (
    QCheckBox, QFrame, QPlainTextEdit, QHBoxLayout, QLabel, QPushButton, QScrollArea, QSizePolicy,
    QToolButton, QVBoxLayout, QWidget, QGridLayout,
)

from .tokens import SPACE

LEVELS = ("info", "warning", "blocked", "success")


class FormTextEdit(QPlainTextEdit):
    """Multi-line editor where Tab moves focus (it would otherwise insert a tab and trap the keyboard)."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.setTabChangesFocus(True)


def fit_segment(button: QPushButton) -> None:
    """Segmented buttons turn bold when checked; reserve the bold width so the label never clips."""
    font = button.font()
    font.setBold(True)
    button.setMinimumWidth(QFontMetrics(font).horizontalAdvance(button.text()) + 44)


def reveal(scroll: QScrollArea, widget: QWidget, margin: int = 8) -> None:
    """Scroll so the *whole* widget is inside the viewport (QScrollArea.ensureWidgetVisible only
    guarantees the cursor rectangle of input widgets). Widgets taller than the viewport align their top."""
    body = scroll.widget()
    if body is None or not body.isAncestorOf(widget):
        return
    top = widget.mapTo(body, widget.rect().topLeft()).y()
    bottom = top + widget.height()
    bar, view_h = scroll.verticalScrollBar(), scroll.viewport().height()
    if widget.height() + 2 * margin >= view_h or top - margin < bar.value():
        bar.setValue(max(0, top - margin))
    elif bottom + margin > bar.value() + view_h:
        bar.setValue(bottom + margin - view_h)


def repolish(widget: QWidget) -> None:
    """Re-apply the stylesheet after a dynamic property (role/level) changed."""
    widget.style().unpolish(widget)
    widget.style().polish(widget)
    widget.update()


def set_level(widget: QWidget, level: str) -> None:
    if level not in LEVELS:
        raise ValueError(f"Unknown level: {level}")
    widget.setProperty("level", level)
    repolish(widget)


def stacked_label(label: str, editor: QWidget, *, help_text: str = "") -> QWidget:
    item = QWidget()
    lay = QVBoxLayout(item)
    lay.setContentsMargins(0, 0, 0, 0)
    lay.setSpacing(SPACE.xs)
    label_widget = QLabel(label)
    label_widget.setBuddy(editor)
    lay.addWidget(label_widget)
    lay.addWidget(editor)
    if help_text:
        help_label = QLabel(help_text)
        help_label.setProperty("role", "muted")
        help_label.setWordWrap(True)
        lay.addWidget(help_label)
    return item


class NoWheelUnlessFocused(QObject):
    """Event filter: an unfocused spin box/combo ignores the wheel so the
    surrounding scroll area scrolls instead of silently changing a value."""

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:  # noqa: N802 (Qt API)
        if event.type() == QEvent.Type.Wheel and isinstance(watched, QWidget) and not watched.hasFocus():
            event.ignore()  # propagate to the parent scroll area
            return True
        return False


def guard_wheel(editor: QWidget, guard: NoWheelUnlessFocused) -> None:
    editor.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
    editor.installEventFilter(guard)


class StatusChip(QLabel):
    """Compact status pill. State is carried by words as well as colour."""

    def __init__(self, text: str = "", level: str = "info", parent: QWidget | None = None):
        super().__init__(text, parent)
        self.setProperty("role", "chip")
        self.setSizePolicy(QSizePolicy.Policy.Maximum, QSizePolicy.Policy.Fixed)
        set_level(self, level)

    def set_status(self, text: str, level: str) -> None:
        self.setText(text)
        set_level(self, level)


class SectionCard(QFrame):
    """Reusable labeled section with a vertical content layout."""

    def __init__(self, title: str, subtitle: str = "", parent: QWidget | None = None):
        super().__init__(parent)
        self.setProperty("role", "card")
        self.content = QVBoxLayout(self)
        self.content.setSpacing(SPACE.md)
        self.content.setContentsMargins(SPACE.gutter, SPACE.gutter, SPACE.gutter, SPACE.gutter)
        name = QLabel(title)
        name.setProperty("role", "section")
        self.content.addWidget(name)
        if subtitle:
            desc = QLabel(subtitle)
            desc.setProperty("role", "muted")
            desc.setWordWrap(True)
            self.content.addWidget(desc)

    def add(self, widget: QWidget) -> None:
        self.content.addWidget(widget)


class NoticeBanner(QFrame):
    """Visible state plus text; not dependent on color alone."""

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setProperty("role", "notice")
        lay = QHBoxLayout(self)
        lay.setContentsMargins(SPACE.md, SPACE.sm, SPACE.md, SPACE.sm)
        self.message = QLabel("No current warning")
        self.message.setWordWrap(True)
        lay.addWidget(self.message)
        self.setAccessibleName("Workflow notices")
        set_level(self, "info")

    def set_message(self, status: str, description: str, level: str = "info") -> None:
        self.message.setText(f"{status}: {description}")
        self.setToolTip(description)
        set_level(self, level)


class IssueList(QWidget):
    """Stack of banners for validation errors (blocked) and warnings."""

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self._layout = QVBoxLayout(self)
        self._layout.setContentsMargins(0, 0, 0, 0)
        self._layout.setSpacing(SPACE.sm)
        self.banners: list[NoticeBanner] = []

    def set_issues(self, errors: tuple[str, ...], warnings: tuple[str, ...], *, empty: str = "No issues found") -> None:
        for banner in self.banners:
            self._layout.removeWidget(banner)
            banner.deleteLater()
        self.banners = []
        entries = [("BLOCKED", text, "blocked") for text in errors] + [("WARNING", text, "warning") for text in warnings]
        if not entries:
            entries = [("OK", empty, "success")]
        for status, text, level in entries:
            banner = NoticeBanner(self)
            banner.set_message(status, text, level)
            self._layout.addWidget(banner)
            self.banners.append(banner)


class Disclosure(QWidget):
    """Accessible expandable section with no persisted hidden state."""

    def __init__(self, title: str, subtitle: str = "", parent: QWidget | None = None):
        super().__init__(parent)
        self._title = title
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(SPACE.sm)
        self.toggle = QPushButton(self)  # QPushButton honours text-align: left
        self.toggle.setProperty("role", "disclosure")
        self.toggle.setCheckable(True)
        self.toggle.setChecked(False)
        self.toggle.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        outer.addWidget(self.toggle)
        # Wrapping summary of enabled/non-default hidden content (never ellipsized, never hover-only).
        self.summary = QLabel("")
        self.summary.setProperty("role", "muted")
        self.summary.setWordWrap(True)
        self.summary.hide()
        outer.addWidget(self.summary)
        if subtitle:
            note = QLabel(subtitle)
            note.setProperty("role", "muted")
            note.setWordWrap(True)
            outer.addWidget(note)
        self.body = QWidget(self)
        self.body_layout = QVBoxLayout(self.body)
        self.body_layout.setContentsMargins(SPACE.sm, 0, SPACE.sm, 0)
        self.body_layout.setSpacing(SPACE.md)
        self.body.hide()
        outer.addWidget(self.body)
        self.toggle.toggled.connect(self._on_toggled)
        self._on_toggled(False)

    def set_summary(self, text: str) -> None:
        self.summary.setText(text)
        self.summary.setVisible(bool(text))

    def set_title(self, title: str) -> None:
        """Update the header text (it names enabled hidden content, see DESIGN_SYSTEM_CANDIDATE section 3)."""
        self._title = title
        self._on_toggled(self.toggle.isChecked())

    def _on_toggled(self, open_: bool) -> None:
        self.body.setVisible(open_)
        self.toggle.setText(f"{'▾' if open_ else '▸'}  {self._title}")
        self.toggle.setAccessibleName(f"{'Collapse' if open_ else 'Expand'} {self._title}")

    def add(self, widget: QWidget) -> None:
        self.body_layout.addWidget(widget)


class ActionStrip(QFrame):
    """Actions stay visible outside the scrolling form.

    The status text sits beside the buttons when there is room and on its own
    line above them when there is not, so buttons are never squeezed or clipped.
    """

    STATUS_MIN_WIDTH = 170

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setProperty("role", "card")
        self._grid = QGridLayout(self)
        self._grid.setSpacing(SPACE.sm)
        self._grid.setContentsMargins(SPACE.md, SPACE.sm, SPACE.md, SPACE.sm)
        self.status = QLabel("Draft only · nothing submitted")
        self.status.setProperty("role", "muted")
        self.status.setWordWrap(True)
        self._buttons = QWidget()
        self.row = QHBoxLayout(self._buttons)
        self.row.setContentsMargins(0, 0, 0, 0)
        self.row.setSpacing(SPACE.sm)
        self.row.addStretch(1)
        self._stacked: bool | None = None
        self._place(stacked=False)

    def _place(self, *, stacked: bool) -> None:
        if stacked == self._stacked:
            return
        self._stacked = stacked
        self._grid.removeWidget(self.status)
        self._grid.removeWidget(self._buttons)
        if stacked:
            self._grid.addWidget(self.status, 0, 0)
            self._grid.addWidget(self._buttons, 1, 0)
            self._grid.setColumnStretch(0, 1)
            self._grid.setColumnStretch(1, 0)
        else:
            self._grid.addWidget(self.status, 0, 0)
            self._grid.addWidget(self._buttons, 0, 1)
            self._grid.setColumnStretch(0, 1)
            self._grid.setColumnStretch(1, 0)

    def resizeEvent(self, event) -> None:  # noqa: N802 (Qt API)
        super().resizeEvent(event)
        margins = self._grid.contentsMargins()
        needed = self._buttons.sizeHint().width() + self.STATUS_MIN_WIDTH + self._grid.spacing() + margins.left() + margins.right()
        # Hysteresis avoids flip-flopping while the layout settles.
        stacked = self.width() < needed if self._stacked is None else (
            self.width() < needed + (24 if self._stacked else 0)
        )
        self._place(stacked=stacked)

    def add_action(self, title: str, *, primary: bool = False) -> QPushButton:
        btn = QPushButton(title, self._buttons)
        if primary:
            btn.setProperty("role", "primary")
        btn.ensurePolished()
        btn.setMinimumWidth(btn.sizeHint().width() + 8)  # bold primary labels must never clip
        self.row.addWidget(btn)
        return btn


class ResponsiveGrid(QWidget):
    """Reflows its items into as many equal columns as fit ``min_column_width``.

    Keeps dense forms compact on wide windows and single-column (never clipped)
    on narrow ones, without a horizontal scroll bar.
    """

    def __init__(self, min_column_width: int = 190, parent: QWidget | None = None, *, column_gap: int = SPACE.md):
        super().__init__(parent)
        self.min_column_width = min_column_width
        self._items: list[QWidget] = []
        self._columns = 0
        self._grid = QGridLayout(self)
        self._grid.setContentsMargins(0, 0, 0, 0)
        self._grid.setHorizontalSpacing(column_gap)
        self._grid.setVerticalSpacing(SPACE.md)

    @property
    def columns(self) -> int:
        return self._columns

    def add(self, widget: QWidget) -> None:
        self._items.append(widget)
        self._reflow(force=True)

    def clear(self) -> None:
        for item in self._items:
            self._grid.removeWidget(item)
            item.deleteLater()
        self._items = []
        self._columns = 0

    def _wanted_columns(self) -> int:
        usable = max(self.width(), self.min_column_width)
        return max(1, min(len(self._items) or 1, usable // self.min_column_width))

    def _reflow(self, force: bool = False) -> None:
        cols = self._wanted_columns()
        if cols == self._columns and not force:
            return
        self._columns = cols
        for item in self._items:
            self._grid.removeWidget(item)
        for index, item in enumerate(self._items):
            self._grid.addWidget(item, index // cols, index % cols)
        for col in range(cols):
            self._grid.setColumnStretch(col, 1)
        for col in range(cols, len(self._items) + 1):
            self._grid.setColumnStretch(col, 0)

    def resizeEvent(self, event) -> None:  # noqa: N802 (Qt API)
        super().resizeEvent(event)
        self._reflow()

    def minimumSizeHint(self):  # noqa: N802 (Qt API)
        hint = super().minimumSizeHint()
        hint.setWidth(self.min_column_width)  # one column always fits
        return hint


class SettingField(QWidget):
    """One effective setting: label, draft lock, reset-to-recommended, editor
    and a visible recommendation line (text, not colour alone)."""

    lockToggled = Signal(bool)
    resetRequested = Signal()

    def __init__(self, key: str, title: str, editor: QWidget, parent: QWidget | None = None):
        super().__init__(parent)
        self.key = key
        self.editor = editor
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(SPACE.xs)
        head = QHBoxLayout()
        head.setSpacing(SPACE.xs)
        self.title = QLabel(title)
        self.title.setBuddy(editor)
        head.addWidget(self.title, 1)
        self.reset_button = QToolButton()
        self.reset_button.setProperty("role", "reset")
        self.reset_button.setText("↺")
        self.reset_button.setToolTip(f"Reset {title} to the recommended value")
        self.reset_button.setAccessibleName(f"Reset {title} to recommended")
        self.reset_button.clicked.connect(self.resetRequested)
        head.addWidget(self.reset_button)
        self.lock = QCheckBox("Lock")
        self.lock.setToolTip(f"Keep {title} unchanged when the model or settings source changes (this draft only)")
        self.lock.setAccessibleName(f"Lock {title} in draft")
        self.lock.toggled.connect(self.lockToggled)
        head.addWidget(self.lock)
        lay.addLayout(head)
        lay.addWidget(editor)
        self.recommendation = QLabel("")
        self.recommendation.setProperty("role", "muted")
        lay.addWidget(self.recommendation)

    def set_state(self, *, locked: bool, differs: bool, recommended: str, origin: str = "") -> None:
        self.lock.blockSignals(True)
        self.lock.setChecked(locked)
        self.lock.blockSignals(False)
        self.reset_button.setEnabled(differs)
        origin_text = {"locked": " · locked", "manual": " · manual override"}.get(origin, "")
        self.recommendation.setText(f"Recommended: {recommended}" + (" · differs" if differs else "") + origin_text)
        self.recommendation.setProperty("level", "warning" if differs else "info")
        repolish(self.recommendation)


class ResultGallery(QFrame):
    """Mock result tiles for a simulated admission. Tiles are labelled placeholders, never images."""

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self._layout = QVBoxLayout(self)
        self._layout.setContentsMargins(0, 0, 0, 0)
        self._layout.setSpacing(SPACE.sm)
        self.caption = QLabel("No simulated result.")
        self.caption.setProperty("role", "muted")
        self.caption.setWordWrap(True)
        self._layout.addWidget(self.caption)
        self.grid = ResponsiveGrid(min_column_width=140)
        self._layout.addWidget(self.grid)
        self.tiles: list[QLabel] = []

    def set_tiles(self, tiles: tuple) -> None:
        self.grid.clear()
        self.tiles = []
        self.caption.setText(
            f"{len(tiles)} placeholder tile(s) from a simulated admission. No image exists." if tiles
            else "No simulated result."
        )
        for tile in tiles:
            label = QLabel("\n".join((tile.label, tile.size, f"seed: {tile.seed}")))
            label.setProperty("role", "tile")
            label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            label.setAccessibleName(f"{tile.label}, {tile.size}, seed {tile.seed} (placeholder)")
            self.grid.add(label)
            self.tiles.append(label)
