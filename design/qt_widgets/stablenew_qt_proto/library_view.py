"""The Asset Library workspace (QT-DS-05): browse, inspect, organize, place, return.

A presentation over the pure :class:`LibrarySession`. It owns no assets: every pixel goes through the
session's media gate, every organizing action is in-memory, and a placement only ever creates or selects a
draft in a destination-owned mock session after an explicit review.
"""

from __future__ import annotations

from dataclasses import dataclass, replace

from PySide6.QtCore import QPoint, Qt, Signal
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QAbstractButton,
    QHBoxLayout,
    QLabel,
    QMenu,
    QPushButton,
    QSplitter,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from .components import NoticeBanner, fit_segment, repolish
from .edit_domain import Replacement
from .library_components import (
    AssetActionMenu,
    AssetDetailsPanel,
    AssetFilterBar,
    AssetView,
    CompareDialog,
    CompatibilityReview,
    InspectDialog,
    InspectorTabs,
    LearningProposalDialog,
    MediaProvider,
    MultiSelectionStrip,
    OrganizePanel,
    ReviewChoice,
    SourceScopePicker,
    StatePanel,
    build_action_menu,
)
from .library_domain import (
    HANDOFF_ACTIONS,
    SCOPE_LABELS,
    ActionId,
    EmptyState,
    LibraryRefused,
    Scope,
    ViewState,
)
from .library_session import LibrarySession, PlacementResult
from .motion_components import ElidedLabel
from .tokens import SPACE

NARROW_WIDTH = 940  # below this the inspector becomes a page of its own
LAYOUTS = (("gallery", "A · Gallery-first"), ("adaptive", "B · Adaptive browser"))
TAB_DETAILS, TAB_ACTIONS, TAB_ORGANIZE = 0, 1, 2


@dataclass
class LibraryUi:
    """Presentation-only state that survives a theme rebuild. Not Library data."""

    layout: str = "adaptive"
    mode: str = "grid"
    tab: int = TAB_DETAILS
    page: str = "browse"  # narrow layouts: browse | inspect
    details_open: bool = True  # layout B drawer
    filters_open: bool = False  # layout B filter disclosure


def _button(text: str, name: str = "", *, checkable: bool = False, role: str = "") -> QPushButton:
    button = QPushButton(text)
    button.setAccessibleName(name or text)
    button.setCheckable(checkable)
    if role:
        button.setProperty("role", role)
    button.ensurePolished()
    button.setMinimumWidth(button.sizeHint().width() + 8)
    return button


class LibraryView(QWidget):
    """Gallery-first (A) and adaptive-browser (B) arrangements of one set of Library widgets."""

    placed = Signal(object)  # PlacementResult
    feedback = Signal(str)

    def __init__(
        self,
        session: LibrarySession | None = None,
        layout_design: str = "adaptive",
        ui: LibraryUi | None = None,
    ):
        super().__init__()
        self.session = session or LibrarySession()
        self.ui = ui or LibraryUi(layout=layout_design)
        self.media = MediaProvider(self.session)
        self._narrow: bool | None = None
        self._org_seen: object = None
        self._shown_keys: tuple[str, ...] | None = None
        self._menu: QMenu | None = None
        self.inspector: InspectDialog | None = None
        self.compare_dialog: CompareDialog | None = None
        self.learning_dialog: LearningProposalDialog | None = None
        self.setAccessibleName("Asset Library")

        root = QVBoxLayout(self)
        root.setContentsMargins(SPACE.sm, 0, 0, 0)
        root.setSpacing(SPACE.sm)
        head = QHBoxLayout()
        title = QLabel("Asset Library")
        title.setProperty("role", "heading")
        head.addWidget(title)
        head.addStretch(1)
        self.layout_buttons: dict[str, QPushButton] = {}
        for key, text in LAYOUTS:
            button = _button(text, f"Library layout: {text}", checkable=True, role="segment")
            fit_segment(button)
            button.clicked.connect(lambda _c=False, k=key: self.set_layout_design(k))
            self.layout_buttons[key] = button
            head.addWidget(button)
        self.mock_chip = QLabel("FIXTURES ONLY · NO SCAN")
        self.mock_chip.setProperty("role", "capsule")
        self.mock_chip.setToolTip(
            "Fixture records only. Nothing is scanned, imported, moved, renamed or deleted."
        )
        head.addWidget(self.mock_chip)
        root.addLayout(head)
        self.banner = NoticeBanner()
        self.banner.hide()
        root.addWidget(self.banner)

        # --- the components, built once and arranged by the layout design ------------------
        self.scope_picker = SourceScopePicker()
        self.filter_bar = AssetFilterBar()
        self.notices = QLabel("")
        self.notices.setProperty("role", "muted")
        self.notices.setWordWrap(True)
        self.notices.hide()
        self.header = self._build_header()
        head.addWidget(self.states_button)
        self.results = AssetView(self.session, self.media)
        self.state = StatePanel()
        self.stack = QStackedWidget()
        self.stack.addWidget(self.results)
        self.stack.addWidget(self.state)
        self.strip = MultiSelectionStrip()
        self.details = AssetDetailsPanel()
        self.actions = AssetActionMenu()
        self.organize = OrganizePanel()
        self.tabs = InspectorTabs(self.details, self.actions, self.organize)
        self.body = QWidget()
        self.body_layout = QVBoxLayout(self.body)
        self.body_layout.setContentsMargins(0, 0, 0, 0)
        root.addWidget(self.body, 1)
        self._managed = (
            self.scope_picker,
            self.filter_bar,
            self.notices,
            self.header,
            self.stack,
            self.strip,
            self.tabs,
        )

        self._wire()
        self.search_shortcut = QShortcut(QKeySequence("Ctrl+F"), self)
        self.search_shortcut.setContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
        self.search_shortcut.activated.connect(lambda: self.filter_bar.search.setFocus())
        self._arrange()
        self.refresh(full=True)

    # ------------------------------------------------------------------------------ building
    def _build_header(self) -> QWidget:
        header = QWidget()
        header.setAccessibleName("Results header")
        outer = QVBoxLayout(header)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(SPACE.xs)
        self.summary = ElidedLabel("")
        self.summary.setAccessibleName("Result count and page")
        outer.addWidget(self.summary)
        row = QHBoxLayout()
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(SPACE.sm)
        outer.addLayout(row)
        self.view_switch = {}
        for key, text in (("browse", "Browse"), ("inspect", "Inspector")):
            button = _button(text, f"Show {text.lower()}", checkable=True, role="segment")
            fit_segment(button)
            button.clicked.connect(lambda _c=False, k=key: self.show_page(k))
            self.view_switch[key] = button
            row.addWidget(button)
        self.clear_filters = _button("Clear filters", "Clear filters")
        self.prev = _button("‹ Prev", "Previous page")
        self.next = _button("Next ›", "Next page")
        self.mode_buttons = {}
        for key, text in (("grid", "Grid"), ("list", "List")):
            button = _button(text, f"{text} view", checkable=True, role="segment")
            fit_segment(button)
            button.clicked.connect(lambda _c=False, k=key: self.set_mode(k))
            self.mode_buttons[key] = button
        self.details_toggle = _button(
            "Details ▸", "Show or hide the details drawer", checkable=True
        )
        self.states_button = _button("Fixture states", "Simulate fixture states")
        self.states_menu = QMenu(self.states_button)
        for text, callback in (
            ("Simulate loading", lambda: self.set_view_state(ViewState.LOADING)),
            (
                "Simulate read error",
                lambda: self.set_view_state(
                    ViewState.ERROR, "Simulated read failure in the fixture reader."
                ),
            ),
            ("Back to ready", lambda: self.set_view_state(ViewState.READY)),
            ("Make 'Ridge revision 16' go missing", lambda: self._simulate("vanish")),
            ("Restore 'Ridge revision 16'", lambda: self._simulate("restore")),
        ):
            self.states_menu.addAction(text).triggered.connect(lambda _c=False, f=callback: f())
        self.states_button.setMenu(self.states_menu)
        self.filters_toggle = _button("Filters ▾", "Show or hide filters", checkable=True)
        row.addStretch(1)
        for widget in (
            self.filters_toggle,
            self.clear_filters,
            self.prev,
            self.next,
            *self.mode_buttons.values(),
            self.details_toggle,
        ):
            row.addWidget(widget)
        return header

    def _wire(self) -> None:
        self.scope_picker.scopeChosen.connect(self._on_scope)
        self.filter_bar.changed.connect(self._on_filters)
        self.clear_filters.clicked.connect(self._clear_filters)
        self.prev.clicked.connect(lambda: self._page(-1))
        self.next.clicked.connect(lambda: self._page(1))
        self.results.selectionRequested.connect(self._on_select)
        self.results.activated_key.connect(self.inspect)
        self.results.contextRequested.connect(self._on_context)
        self.results.clearRequested.connect(self._clear_selection)
        self.results.selectPageRequested.connect(self._select_page)
        self.strip.clearRequested.connect(self._clear_selection)
        self.strip.detailsRequested.connect(lambda: self.show_inspector(TAB_DETAILS))
        self.strip.organizeRequested.connect(lambda: self.show_inspector(TAB_ORGANIZE))
        self.strip.actions.clicked.connect(self._strip_menu)
        self.actions.actionRequested.connect(self.trigger)
        self.details.relationChosen.connect(self._choose_related)
        self.details.inspectRequested.connect(self.inspect)
        self.state.action.clicked.connect(self._state_action)
        self.details_toggle.toggled.connect(self._toggle_details)
        self.filters_toggle.toggled.connect(self._toggle_filters)
        self.tabs.currentChanged.connect(lambda i: setattr(self.ui, "tab", i))
        panel = self.organize
        panel.collections.new.clicked.connect(self._new_collection)
        panel.collections.rename.clicked.connect(self._rename_collection)
        panel.collections.add.clicked.connect(self._add_to_collection)
        panel.collections.remove.clicked.connect(self._remove_from_collection)
        panel.tags.add.clicked.connect(lambda: self._tag(True))
        panel.tags.remove.clicked.connect(lambda: self._tag(False))
        panel.favorite.clicked.connect(lambda: self._favorite(True))
        panel.unfavorite.clicked.connect(lambda: self._favorite(False))
        panel.undo.clicked.connect(lambda: self._history(True))
        panel.redo.clicked.connect(lambda: self._history(False))

    # ------------------------------------------------------------------------------- layout
    @property
    def layout_design(self) -> str:
        return self.ui.layout

    def set_layout_design(self, design: str) -> None:
        if design not in dict(LAYOUTS):
            raise ValueError(f"Unknown Library layout: {design}")
        self.ui.layout = design
        self._arrange()
        self.refresh()

    def _arrange(self) -> None:
        """Place the same widgets for layout A or B and for wide or narrow windows."""
        narrow = self.width() < NARROW_WIDTH if self.isVisible() or self.width() > 100 else False
        self._narrow = narrow
        for widget in self._managed:
            widget.setParent(self)
            widget.hide()
        while self.body_layout.count():
            item = self.body_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        design = self.ui.layout
        for key, button in self.layout_buttons.items():
            button.setChecked(key == design)
        container = QWidget()
        col = QVBoxLayout(container)
        col.setContentsMargins(0, 0, 0, 0)
        col.setSpacing(SPACE.sm)
        compact_scope = narrow or design == "adaptive"
        self.scope_picker.set_compact(compact_scope)
        for widget in (self.view_switch["browse"], self.view_switch["inspect"]):
            widget.setVisible(narrow)
        self.details_toggle.setVisible(design == "adaptive" and not narrow)
        self.strip.details.setVisible(narrow or design == "adaptive")
        self.filters_toggle.setVisible(design == "adaptive")
        self.filter_bar.filters.setVisible(design == "gallery" or self.ui.filters_open)
        self.filters_toggle.blockSignals(True)
        self.filters_toggle.setChecked(self.ui.filters_open)
        self.filters_toggle.blockSignals(False)
        self.details_toggle.blockSignals(True)
        self.details_toggle.setChecked(self.ui.details_open)
        self.details_toggle.setText("Details ◂" if self.ui.details_open else "Details ▸")
        self.details_toggle.blockSignals(False)

        browse = QWidget()
        bcol = QVBoxLayout(browse)
        bcol.setContentsMargins(0, 0, 0, 0)
        bcol.setSpacing(SPACE.sm)
        if design == "adaptive" or narrow:
            bar = QWidget()
            bar_row = QHBoxLayout(bar)
            bar_row.setContentsMargins(0, 0, 0, 0)
            bar_row.setSpacing(SPACE.sm)
            bar_row.addWidget(self.scope_picker, 2)
            bcol.addWidget(bar)
        for widget in (self.filter_bar, self.notices, self.header, self.stack):
            widget.show()
        self.scope_picker.show()
        bcol.addWidget(self.filter_bar)
        bcol.addWidget(self.notices)
        bcol.addWidget(self.header)
        bcol.addWidget(self.stack, 1)
        self.strip.show()
        self.tabs.show()

        if narrow:
            self.page_stack = QStackedWidget()
            self.page_stack.addWidget(browse)
            self.page_stack.addWidget(self.tabs)
            col.addWidget(self.page_stack, 1)
            col.addWidget(self.strip)
            self.page_stack.setCurrentIndex(0 if self.ui.page == "browse" else 1)
            for key, button in self.view_switch.items():
                button.setChecked(key == self.ui.page)
            self.splitter = None
        elif design == "gallery":
            self.page_stack = None
            self.splitter = QSplitter(Qt.Orientation.Horizontal)
            self.splitter.setChildrenCollapsible(False)
            left = self.scope_picker
            left.setMinimumWidth(170)
            left.setMaximumWidth(260)
            browse_with_strip = QWidget()
            wcol = QVBoxLayout(browse_with_strip)
            wcol.setContentsMargins(0, 0, 0, 0)
            wcol.setSpacing(SPACE.sm)
            wcol.addWidget(browse, 1)
            wcol.addWidget(self.strip)
            self.splitter.addWidget(left)
            self.splitter.addWidget(browse_with_strip)
            self.tabs.setMinimumWidth(290)
            self.splitter.addWidget(self.tabs)
            self.splitter.setStretchFactor(1, 1)
            self.splitter.setSizes([215, 600, 320])
            col.addWidget(self.splitter, 1)
        else:
            self.page_stack = None
            self.splitter = QSplitter(Qt.Orientation.Horizontal)
            self.splitter.setChildrenCollapsible(True)
            self.splitter.addWidget(browse)
            self.splitter.addWidget(self.tabs)
            self.tabs.setMinimumWidth(280)
            self.tabs.setVisible(self.ui.details_open)
            self.splitter.setStretchFactor(0, 1)
            self.splitter.setSizes([700, 320])
            col.addWidget(self.splitter, 1)
            col.addWidget(self.strip)
        self.scope_picker.setVisible(True)
        self.body_layout.addWidget(container)
        self._fix_tab_order()
        self.results.set_mode(self.ui.mode)
        for key, button in self.mode_buttons.items():
            button.setChecked(key == self.ui.mode)

    def _fix_tab_order(self) -> None:
        chain = [
            self.scope_picker.list if not self.scope_picker.list.isHidden() else self.scope_picker.combo,
            self.filter_bar.search, self.filter_bar.mode, self.filter_bar.sort,
            self.filter_bar.kind, self.filter_bar.category, self.filter_bar.model, self.filter_bar.recency,
            self.filter_bar.availability, self.filter_bar.tag, self.filter_bar.collection, self.filter_bar.favorites,
            self.filters_toggle, self.clear_filters, self.prev, self.next,
            *self.mode_buttons.values(), self.details_toggle, self.states_button, self.results,
            self.strip.clear, self.strip.organize, self.strip.details, self.strip.actions, self.tabs,
        ]  # fmt: skip
        previous = None
        for widget in chain:
            if previous is not None:
                QWidget.setTabOrder(previous, widget)
            previous = widget

    def resizeEvent(self, event) -> None:  # noqa: N802 (Qt API)
        super().resizeEvent(event)
        narrow = self.width() < NARROW_WIDTH
        if self._narrow is not None and narrow != self._narrow and self.width() > 100:
            self._arrange()
            self.refresh()

    def show_page(self, page: str) -> None:
        self.ui.page = page
        if getattr(self, "page_stack", None) is not None:
            self.page_stack.setCurrentIndex(0 if page == "browse" else 1)
            for key, button in self.view_switch.items():
                button.setChecked(key == page)

    def show_inspector(self, tab: int = TAB_DETAILS) -> None:
        """Bring the inspector forward: a page when narrow, a drawer in B, the side panel in A."""
        if self.ui.layout == "adaptive" and not self.ui.details_open and not self._narrow:
            self.details_toggle.setChecked(True)
        self.show_page("inspect")
        self.tabs.setCurrentIndex(tab)

    def _toggle_details(self, shown: bool) -> None:
        self.ui.details_open = shown
        self.details_toggle.setText("Details ◂" if shown else "Details ▸")
        self.tabs.setVisible(shown)

    def _toggle_filters(self, shown: bool) -> None:
        self.ui.filters_open = shown
        self.filter_bar.filters.setVisible(shown)

    # ------------------------------------------------------------------------------ feedback
    def note(self, message: str, level: str = "success", status: str = "") -> None:
        word = (
            status
            or {"success": "Done", "warning": "Note", "blocked": "Blocked", "info": "Info"}[level]
        )
        self.banner.set_message(word, message, level)
        self.banner.show()
        self.feedback.emit(message)

    def _guard(self, action) -> bool:
        try:
            action()
        except LibraryRefused as exc:
            self.note(str(exc), "blocked")
            return False
        self.note(self.session.last_feedback)
        return True

    # -------------------------------------------------------------------------- refresh/sync
    def refresh(self, *, full: bool = False) -> None:
        """Bring every widget in line with the session. Only the current page is ever modeled."""
        session = self.session
        result = session.result()
        if full or self._org_seen != (session.org, len(session.catalog)):
            self._org_seen = (session.org, len(session.catalog))
            self.scope_picker.refresh(session)
            self.filter_bar.populate(session.catalog, session)
        else:
            self.scope_picker.refresh(session) if self.scope_picker.list.currentRow() < 0 else None
        if (
            full and not self.filter_bar.pending()
        ):  # never overwrite keystrokes still in the debounce
            self.filter_bar.show_query(session.query)
        if session.view_state == ViewState.LOADING:
            self.state.show_state(
                "Loading…",
                "Reading fixture records. Results appear when the read finishes.",
                "Finish loading",
            )
            self.stack.setCurrentWidget(self.state)
        elif session.view_state == ViewState.ERROR:
            self.state.show_state(
                "Read error",
                f"{session.view_error} Your selection, filters and collections are intact.",
                "Retry",
            )
            self.stack.setCurrentWidget(self.state)
        elif result.empty == EmptyState.EMPTY_SOURCE:
            self.state.show_state(*self._empty_text())
            self.stack.setCurrentWidget(self.state)
        elif result.empty == EmptyState.NO_MATCHES:
            label = self._scope_text()
            self.state.show_state(
                "No filter matches",
                f"Nothing in {label} matches these filters. The search did not widen to other sources "
                f"({result.scope_total} record(s) are in this scope).",
                "Clear filters",
            )
            self.stack.setCurrentWidget(self.state)
        else:
            if self._shown_keys != result.items:
                bar = self.results.verticalScrollBar()
                keep = bar.value()
                self.results.page_model.set_keys(result.items)
                bar.setValue(
                    keep
                    if self._shown_keys is not None and set(self._shown_keys) == set(result.items)
                    else 0
                )
                self._shown_keys = result.items
            else:
                self.results.page_model.refresh()
            self.stack.setCurrentWidget(self.results)
        if self.stack.currentWidget() is self.state:
            self._shown_keys = None
        self.summary.set_full_text(
            result.summary()
            + (f" · {session.query.mode.value} search" if session.query.text else "")
        )
        self.prev.setEnabled(result.page > 0)
        self.next.setEnabled(result.page + 1 < result.page_count)
        self.clear_filters.setEnabled(session.query.filters_active)
        notes = list(result.notices)
        self.notices.setText(" ".join(notes))
        self.notices.setVisible(bool(notes))
        prompt_mode = session.query.mode.value != "Metadata"
        self.filter_bar.semantics.setText(
            "Prompt search matches the start of the first 48 characters of a fixture prompt. "
            "It is not full-text and not semantic search."
        )
        self.filter_bar.semantics.setVisible(prompt_mode)
        self.sync_selection()

    def sync_selection(self) -> None:
        session = self.session
        self.results.page_model.refresh()
        self.strip.set_selection(session)
        keys = session.selection
        if not keys:
            self.details.show_none()
        else:
            key = session.focus if session.focus in keys else keys[-1]
            extra = ""
            if len(keys) > 1:
                extra = (
                    f"{len(keys)} assets are selected, in this order: "
                    + ", ".join(keys[:6])
                    + (" …" if len(keys) > 6 else "")
                    + f". Showing details for {key}."
                )
            self.details.show_asset(session, key, self.media, extra)
        self.actions.set_eligibility(session.available_actions(), len(keys))
        self._sync_organize()

    def _sync_organize(self) -> None:
        session, panel = self.session, self.organize
        combo = panel.collections.target
        want = combo.currentData() or session.query.collection
        combo.blockSignals(True)
        combo.clear()
        for collection in session.org.collections:
            combo.addItem(
                f"{collection.name} ({len(collection.members)})", collection.collection_id
            )
        combo.setCurrentIndex(max(0, combo.findData(want)))
        combo.blockSignals(False)
        has_sel, has_target = bool(session.selection), combo.count() > 0
        panel.collections.add.setEnabled(has_sel and has_target)
        panel.collections.remove.setEnabled(has_sel and has_target)
        panel.collections.rename.setEnabled(has_target)
        panel.tags.add.setEnabled(has_sel)
        panel.tags.remove.setEnabled(has_sel)
        panel.favorite.setEnabled(has_sel)
        panel.unfavorite.setEnabled(has_sel)
        panel.undo.setEnabled(session.can_undo)
        panel.redo.setEnabled(session.can_redo)
        focus = (
            session.focus
            if session.focus in session.selection
            else (session.selection[-1] if session.selection else None)
        )
        tags = ", ".join(session.org.tags_of(focus)) if focus else ""
        panel.tags.current.setText(
            f"Tags on {focus}: {tags or 'none'}" if focus else "Tags: select an asset"
        )

    def _scope_text(self) -> str:
        query = self.session.query
        if query.collection is not None:
            return f"collection '{self.session.org.collection(query.collection).name}'"
        return f"“{SCOPE_LABELS[query.scope]}”"

    def _empty_text(self) -> tuple[str, str, str]:
        query = self.session.query
        if query.collection is not None:
            return (
                "This collection is empty",
                "It holds no references yet. Select assets in another source and use Add selected in Organize.",
                "Show all collections",
            )
        if query.scope == Scope.FAVORITES:
            return (
                "No favorites yet",
                "Select an asset and use Favorite in Organize. A favorite is only a mark; it is not a rating.",
                "Show all supported assets",
            )
        if query.scope == Scope.COLLECTIONS:
            return (
                "No collections hold anything yet",
                "Create a collection in Organize and add selected assets to it.",
                "Show all supported assets",
            )
        return (
            "This source is empty",
            f"{self._scope_text()} has no fixture records. Choose another source.",
            "Show all supported assets",
        )

    def _state_action(self) -> None:
        session = self.session
        if session.view_state != ViewState.READY:
            self.set_view_state(ViewState.READY)
            return
        result = session.result()
        if result.empty == EmptyState.NO_MATCHES:
            self._clear_filters()
        else:
            session.set_scope(Scope.ALL if session.query.collection is None else Scope.COLLECTIONS)
            self.filter_bar.show_query(session.query)
            self.refresh(full=True)

    def set_view_state(self, state: ViewState, error: str = "") -> None:
        self.session.set_view_state(state, error)
        self.refresh()

    def _simulate(self, what: str) -> None:
        key = "history:ridge-16"
        self.note(
            self.session.simulate_vanish(key)
            if what == "vanish"
            else self.session.simulate_restore(key),
            "warning",
        )
        self.media.forget(key)
        self.refresh()

    # ----------------------------------------------------------------- query / selection input
    def _on_scope(self, scope_value: str, collection) -> None:
        self.session.set_scope(Scope(scope_value), collection)
        self.filter_bar.show_query(self.session.query)
        self.refresh()

    def _on_filters(self) -> None:
        changes = self.filter_bar.query_changes()
        if not self._guard_quiet(lambda: self.session.set_query(**changes)):
            return
        self.refresh(full=False)
        self.scope_picker.refresh(self.session)

    def _guard_quiet(self, action) -> bool:
        try:
            action()
        except LibraryRefused as exc:
            self.note(str(exc), "blocked")
            return False
        return True

    def _clear_filters(self) -> None:
        self.session.clear_filters()
        self.filter_bar.show_query(self.session.query)
        self.refresh(full=True)
        self.note(
            "Filters cleared. The source scope, sort order and selection are unchanged.", "info"
        )

    def _page(self, delta: int) -> None:
        self.session.go_page(self.session.query.page + delta)
        self.results.verticalScrollBar().setValue(0)
        self.refresh()

    def _on_select(self, key: str, modifiers) -> None:
        session = self.session
        if (
            modifiers & Qt.KeyboardModifier.ShiftModifier
            and session.focus in self.session.result().items
        ):
            session.select_range(session.focus, key)
        elif modifiers & Qt.KeyboardModifier.ControlModifier:
            session.toggle(key)
        else:
            session.select_only(key)
        self.sync_selection()

    def _select_page(self) -> None:
        for key in self.session.result().items:
            if key not in self.session.selection:
                self.session.toggle(key)
        self.sync_selection()

    def _clear_selection(self) -> None:
        self.session.clear_selection()
        self.sync_selection()

    def _choose_related(self, key: str) -> None:
        self.session.select_only(key)
        status = self.session.selection_report()[key]
        self.sync_selection()
        self.note(f"Selected {key}. {status.value}.", "info")

    # ---------------------------------------------------------------------------- display mode
    def set_mode(self, mode: str) -> None:
        self.ui.mode = mode
        self.results.set_mode(mode)
        for key, button in self.mode_buttons.items():
            button.setChecked(key == mode)

    # ----------------------------------------------------------------------------- actions
    def context_menu(self, key: str | None = None) -> QMenu:
        """The actions for the current selection (selecting ``key`` first if it is not selected)."""
        if key is not None and key not in self.session.selection:
            self.session.select_only(key)
            self.sync_selection()
        self._menu = build_action_menu(self.session.available_actions(), self, self.trigger)
        return self._menu

    def _on_context(self, key: str, pos: QPoint) -> None:
        self.context_menu(key).popup(pos)

    def _strip_menu(self) -> None:
        menu = self.context_menu()
        menu.popup(self.strip.actions.mapToGlobal(QPoint(0, -menu.sizeHint().height())))

    def trigger(self, action_value: str) -> None:
        action = ActionId(action_value)
        session = self.session
        if action == ActionId.INSPECT:
            if session.selection:
                self.inspect(
                    session.focus if session.focus in session.selection else session.selection[-1]
                )
        elif action == ActionId.COMPARE:
            self.compare(
                session.focus
                if session.focus in session.selection
                else (session.selection[0] if session.selection else "")
            )
        elif action in HANDOFF_ACTIONS:
            self.begin_placement(action)
        elif action in (ActionId.ADD_COLLECTION, ActionId.REMOVE_COLLECTION):
            self.show_inspector(TAB_ORGANIZE)
            self.organize.collections.target.setFocus()
        elif action == ActionId.FAVORITE:
            self._favorite(True)
        elif action == ActionId.ARCHIVE_PHOTO:
            self._guard(lambda: session.archive_photo(session.selection))
            self._after_org()
        elif action == ActionId.RESTORE_PHOTO:
            self._guard(lambda: session.restore_photo(session.selection))
            self._after_org()
        else:  # general archive and delete are future-gated: say why, change nothing
            self.note(session.evaluate(action).reason, "blocked", "Unavailable")

    # -------------------------------------------------------------------------- inspection
    def inspect(self, key: str) -> InspectDialog | None:
        if self.inspector is not None:
            self.inspector.close()
            self.inspector.deleteLater()
        self.inspector = InspectDialog(self.session, self.media, key, self)
        self.inspector.compareRequested.connect(self.compare)
        self.inspector.show()
        return self.inspector

    def compare(self, key: str) -> CompareDialog | None:
        try:
            self.compare_dialog = CompareDialog(self.session, self.media, key, self)
        except (LibraryRefused, ValueError) as exc:
            self.note(str(exc), "blocked")
            return None
        self.compare_dialog.show()
        return self.compare_dialog

    # ---------------------------------------------------------------------------- placement
    def begin_placement(self, action: ActionId) -> PlacementResult | None:
        """Review the whole selection, optionally narrow it, then place or cancel. Cancel mutates nothing."""
        session = self.session
        proposal = session.propose(action)
        if not proposal.eligibility.eligible:
            self.note(
                proposal.eligibility.reason or "Select at least one asset.",
                "blocked",
                "Cannot place",
            )
            return None
        while True:
            dialog = CompatibilityReview(proposal, self)
            dialog.exec()
            if dialog.choice == ReviewChoice.NARROW:
                session.narrow(dialog.narrowed)
                self.sync_selection()
                proposal = session.propose(action)
                if not proposal.eligibility.eligible:
                    return None
                continue
            break
        if dialog.choice == ReviewChoice.CANCEL:
            self.note(
                "Placement cancelled. The Library and the destination are unchanged.",
                "info",
                "Cancelled",
            )
            return None
        choice = Replacement.REPLACE if dialog.choice == ReviewChoice.REPLACE else None
        return self.place(proposal, choice)

    def place(self, proposal, choice: Replacement | None = None) -> PlacementResult:
        result = self.session.commit(proposal, choice)
        level = {"Placed": "success", "Cancelled": "info"}.get(result.outcome.value, "blocked")
        self.note(result.message, level, result.outcome.value)
        if result.ok:
            if self.session.pending_return is not None:
                self.session.pending_return = replace(
                    self.session.pending_return,
                    ui=(("mode", self.ui.mode), ("tab", self.tabs.currentIndex()),
                        ("scroll", self.results.verticalScrollBar().value()), ("layout", self.ui.layout)),
                )  # fmt: skip
            if proposal.action == ActionId.LEARNING:
                self.learning_dialog = LearningProposalDialog(
                    self.session.learning_proposals[-1], self
                )
                self.learning_dialog.show()
            self.placed.emit(result)
        self.refresh()
        return result

    def return_to_library(self) -> tuple[str, ...]:
        """Restore the in-session browse context. Changed items stay selected and are disclosed."""
        context = self.session.pending_return
        notes = self.session.restore_context()
        ui = dict(context.ui) if context else {}
        if "mode" in ui:
            self.set_mode(ui["mode"])
        self.filter_bar.show_query(self.session.query)
        self.refresh(full=True)
        if "tab" in ui:
            self.tabs.setCurrentIndex(ui["tab"])
        self.show_page("browse")
        if "scroll" in ui:
            self.results.verticalScrollBar().setValue(ui["scroll"])
        self.note(self.session.last_feedback, "warning" if notes else "success", "Context restored")
        return notes

    # ---------------------------------------------------------------------------- organizing
    def _after_org(self) -> None:
        self.refresh(full=True)

    def _target(self) -> str | None:
        return self.organize.collections.target.currentData()

    def _new_collection(self) -> None:
        name = self.organize.collections.name.text()
        if self._guard(lambda: self.session.create_collection(name)):
            self.organize.collections.name.clear()
            self.organize.collections.target.setCurrentIndex(
                self.organize.collections.target.count()
            )
        self.refresh(full=True)
        newest = (
            self.session.org.collections[-1].collection_id if self.session.org.collections else None
        )
        self.organize.collections.target.setCurrentIndex(
            max(0, self.organize.collections.target.findData(newest))
        )

    def _rename_collection(self) -> None:
        target, name = self._target(), self.organize.collections.name.text()
        if target and self._guard(lambda: self.session.rename_collection(target, name)):
            self.organize.collections.name.clear()
        self._after_org()

    def _add_to_collection(self) -> None:
        target = self._target()
        if target:
            self._guard(lambda: self.session.add_to_collection(target, self.session.selection))
        self._after_org()

    def _remove_from_collection(self) -> None:
        target = self._target()
        if target:
            self._guard(lambda: self.session.remove_from_collection(target, self.session.selection))
        self._after_org()

    def _tag(self, add: bool) -> None:
        tag = self.organize.tags.edit.text()
        call = self.session.add_tag if add else self.session.remove_tag
        if self._guard(lambda: call(self.session.selection, tag)):
            self.organize.tags.edit.clear()
        self._after_org()

    def _favorite(self, value: bool) -> None:
        self._guard(lambda: self.session.set_favorite(self.session.selection, value))
        self._after_org()

    def _history(self, undo: bool) -> None:
        self._guard(self.session.undo if undo else self.session.redo)
        self._after_org()

    # ------------------------------------------------------------------------------- theme
    def restyle(self) -> None:
        for widget in (self, *self.findChildren(QAbstractButton)):
            repolish(widget)
        self.results.page_model.refresh()

    def shutdown(self) -> None:
        for dialog in (self.inspector, self.compare_dialog, self.learning_dialog):
            if dialog is not None:
                dialog.close()
        if self._menu is not None:
            self._menu.close()
        self.media.deleteLater()
