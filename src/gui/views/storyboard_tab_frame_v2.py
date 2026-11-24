"""The Storyboard tab: a tree of takes as shot columns, a cut viewer and a Continue panel (PR-VID-STORY-380).

Presentation only. State lives in ``StoryboardTreeContract``; every service call, projection and frame load runs on
``build_edit_work_runner`` and marshals back through the UI dispatcher. The tab builds no job, touches no repository and
never calls the runner: Continue goes through ``app_controller.get_video_workflow_controller().storyboards``.
"""

from __future__ import annotations

import tkinter as tk
from collections.abc import Callable
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from tkinter import filedialog, ttk
from typing import Any

from PIL import Image, ImageTk

from src.controller.storyboard_submission_service import ContinueRequest, ContinueRow
from src.gui import theme_v2
from src.gui.design_system_v2 import Colors, Typography
from src.gui.tooltip import attach_tooltip
from src.gui.view_contracts.edit_work_runner import build_edit_work_runner
from src.gui.view_contracts.storyboard_import_contract import (
    MediaPrefs,
    clip_dialog_options,
    image_dialog_options,
    import_actions,
    load_media_prefs,
    save_media_prefs,
)
from src.gui.view_contracts.storyboard_tree_contract import (
    AI_NOT_SET_UP,
    MODE_TIPS,
    SEED_FIXED,
    SEED_RANDOM,
    StoryboardTreeContract,
)
from src.gui.views.storyboard_compare_window_v2 import StoryboardCompareWindowV2
from src.gui.widgets.storyboard_columns_v2 import StoryboardColumnsV2
from src.gui.widgets.storyboard_continue_rows_v2 import ContinueRowFields, ContinueRowsV2
from src.gui.widgets.storyboard_viewer_v2 import StoryboardViewerV2
from src.services.ui_state_store import get_ui_state_store
from src.utils.os_shell import reveal_in_file_manager
from src.video.review_preview import prepare_review_preview
from src.video.sequence_plan import ROOT_PARENT
from src.video.storyboard_cut import CutManifest
from src.video.storyboard_frame_cache import FrameCache
from src.video.storyboard_import import ClipImportPlan, source_text
from src.video.storyboard_projection import TakeView
from src.video.storyboard_tree import StoryboardTree

REFRESH_MS = 6000
COLUMNS_MIN_HEIGHT = 90  # the tree strip can be dragged this small, never to nothing
BODY_MIN_HEIGHT = 160
NO_TARGET_TEXT = "Nothing selected to continue from"
BANNER_FONT = (Typography.FAMILY, 11, "bold")
_LIVE_STATES = frozenset({"pending", "queued", "running"})


@dataclass(frozen=True, slots=True)
class _State:
    tree: StoryboardTree
    views: dict[str, TakeView]
    root_thumbnail: str | None
    notice: str = ""


def _application_ui_store() -> Any:
    """The application's UI state store, or ``None`` when it cannot be opened (preferences then last one session)."""

    try:
        return get_ui_state_store()
    except OSError:
        return None


def _timecode(frames: int, fps: int) -> str:
    """``mm:ss.ff``: whole seconds, then the frames left over at the cut's own fps."""

    seconds, rest = divmod(frames, max(1, fps))
    return f"{seconds // 60:02d}:{seconds % 60:02d}.{rest:02d}"


def _saved_text(tree: StoryboardTree) -> str:
    try:
        stamp = datetime.fromisoformat(tree.updated_at)
    except ValueError:
        return "saved"
    minutes = int((datetime.now(UTC) - stamp).total_seconds() // 60)
    return "saved just now" if minutes < 1 else f"saved {minutes} min ago"


class StoryboardTabFrameV2(ttk.Frame):
    def __init__(
        self,
        parent: tk.Misc,
        *,
        app_controller: Any,
        app_state: Any,
        ui_state_store: Any = None,
    ) -> None:
        super().__init__(parent, style="Panel.TFrame")
        self.app_controller = app_controller
        self.app_state = app_state
        #: Presentation preferences (thumbnails and viewer on/off) live in the application's UI state file.
        self._ui_store = ui_state_store if ui_state_store is not None else _application_ui_store()
        self.media: MediaPrefs = load_media_prefs(self._ui_store)
        #: Bumped whenever thumbnails are switched, so a load started before the switch is ignored when it lands.
        self._thumb_generation = 0
        #: The native file browser; tests replace it.
        self.ask_open_file: Callable[..., str] = filedialog.askopenfilename
        self.runner = build_edit_work_runner(self)
        self.cache = FrameCache()
        self.tree: StoryboardTree | None = None
        self.views: dict[str, TakeView] = {}
        self.contract: StoryboardTreeContract | None = None
        self.cut: CutManifest | None = None
        self._root_thumbnail: str | None = None
        self._photos: dict[str, Any] = {}
        self._refresh_after: str | None = None
        self._frame_path = ""
        self._ai_tooltip_text = ""
        self.target: tuple[str, int | None] | None = None
        self.compare_preview_fn: Any = prepare_review_preview
        self.compare_windows: list[StoryboardCompareWindowV2] = []
        self.status_var = tk.StringVar(
            value="Open a storyboard, or start one from a finished clip or image."
        )
        self.title_var = tk.StringVar(value="Storyboard")
        self.show_dropped_var = tk.BooleanVar(value=False)
        self.dropped_text_var = tk.StringVar(value="Show dropped (0)")
        self.show_thumbnails_var = tk.BooleanVar(value=self.media.thumbnails)
        self.show_viewer_var = tk.BooleanVar(value=self.media.viewer)
        self.banner_var = tk.StringVar(value=NO_TARGET_TEXT)
        self.rowconfigure(1, weight=1)
        self.columnconfigure(0, weight=1)
        self._build_toolbar()
        #: The take tree above and the viewer + Continue panel below, with a sash Rob can drag.
        self.pane = tk.PanedWindow(
            self,
            orient="vertical",
            sashwidth=6,
            sashrelief="raised",
            bd=0,
            bg=theme_v2.BACKGROUND_DARK,
        )
        self.pane.grid(row=1, column=0, sticky="nsew", padx=8, pady=4)
        self.columns = StoryboardColumnsV2(
            self.pane,
            on_select=self.select_take,
            on_mark=self.set_mark,
            on_compare=self._compare_hook,
            on_resume=self.resume_take,
            on_replay=self.replay_take,
        )
        self.columns.set_thumbnails_visible(self.media.thumbnails)
        body = ttk.Frame(self.pane, style="Panel.TFrame")
        self._body = body
        self.pane.add(self.columns, stretch="always", minsize=COLUMNS_MIN_HEIGHT)
        self.pane.add(body, stretch="always", minsize=BODY_MIN_HEIGHT)
        body.rowconfigure(1, weight=1)
        self.banner_label = ttk.Label(
            body,
            textvariable=self.banner_var,
            style="Dark.TLabel",
            font=BANNER_FONT,
            foreground=Colors.PRIMARY_ACCENT,
        )
        self.banner_label.grid(row=0, column=0, columnspan=2, sticky="w", pady=(0, 4))
        self.viewer = StoryboardViewerV2(
            body,
            on_frame=self._request_frame,
            on_continue=self._continue_from_frame,
            readout=self._readout,
        )
        self.viewer.set_media_visible(self.media.viewer)
        self.viewer.grid(row=1, column=0, sticky="nsew", padx=(0, 8))
        self._apply_body_weights()
        self.continue_host = ttk.Frame(body, style="Panel.TFrame")
        self.continue_host.grid(row=1, column=1, sticky="nsew")
        self._build_continue_panel(self.continue_host)
        ttk.Label(self, textvariable=self.status_var, style="Dark.TLabel", wraplength=900).grid(
            row=2, column=0, sticky="ew", padx=8, pady=(0, 6)
        )

    # ------------------------------------------------------------------ construction

    def _build_toolbar(self) -> None:
        bar = ttk.Frame(self, style="Panel.TFrame")
        bar.grid(row=0, column=0, sticky="ew", padx=8, pady=6)
        ttk.Label(bar, textvariable=self.title_var, style="Dark.TLabel").pack(side="left")
        self.new_button = ttk.Button(
            bar, text="New from clip or image…", style="Dark.TButton", command=self._ask_new
        )
        self.open_button = ttk.Button(
            bar, text="Open…", style="Dark.TButton", command=self._ask_open
        )
        self.dropped_check = ttk.Checkbutton(
            bar,
            textvariable=self.dropped_text_var,
            variable=self.show_dropped_var,
            command=self.render,
        )
        self.thumbnails_check = ttk.Checkbutton(
            bar,
            text="Thumbnails",
            variable=self.show_thumbnails_var,
            command=self._toggle_thumbnails,
        )
        self.viewer_check = ttk.Checkbutton(
            bar, text="Viewer", variable=self.show_viewer_var, command=self._toggle_viewer
        )
        attach_tooltip(
            self.thumbnails_check,
            "Show a thumbnail on each take card. Off: the cards are text only and no thumbnail is loaded.",
        )
        attach_tooltip(
            self.viewer_check,
            "Show the frame viewer. Off: no frame is drawn or played; the slider, readout and Continue still work.",
        )
        self.export_button = ttk.Button(
            bar, text="Export cut…", style="Dark.TButton", command=self._ask_export
        )
        self.rename_button = ttk.Button(
            bar, text="Rename…", style="Dark.TButton", command=self._ask_rename
        )
        self.save_as_button = ttk.Button(
            bar, text="Save As…", style="Dark.TButton", command=self._ask_save_as
        )
        self.refresh_button = ttk.Button(
            bar, text="Refresh", style="Dark.TButton", command=self.refresh
        )
        for widget in (
            self.refresh_button,
            self.save_as_button,
            self.rename_button,
            self.export_button,
            self.dropped_check,
            self.viewer_check,
            self.thumbnails_check,
            self.open_button,
            self.new_button,
        ):
            widget.pack(side="right", padx=2)

    # ------------------------------------------------------------------ service and workers

    def _service(self) -> Any:
        getter = getattr(self.app_controller, "get_video_workflow_controller", None)
        if not callable(getter):
            raise RuntimeError("The video workflow controller is not available.")
        return getter().storyboards

    def _say(self, text: str) -> None:
        self.status_var.set(text)

    def _fail(self, error: Exception) -> None:
        self._say(str(error) or type(error).__name__)

    def _work(
        self, key: str, work: Callable[[], Any], on_result: Callable[[Any], None] | None = None
    ) -> None:
        self.runner.submit(key, work, on_result=on_result, on_error=self._fail)

    # ------------------------------------------------------------------ open, refresh, start

    def _load_state(self, storyboard_id: str, *, reconcile: bool = True) -> _State:
        service = self._service()
        tree = service.reconcile(storyboard_id) if reconcile else service.store.load(storyboard_id)
        views = service.project(tree)
        return _State(tree, views, self._root_thumbnail_path(service, tree))

    @staticmethod
    def _root_thumbnail_path(service: Any, tree: StoryboardTree) -> str | None:
        if tree.root.kind == "image":
            return tree.root.image_path or None
        cut = service.parent_cut(tree, ROOT_PARENT)
        return None if cut is None else str(cut.frames[0].path)

    def open_storyboard(self, storyboard_id: str) -> None:
        self._say("Opening the storyboard…")
        self._work("open", lambda: self._load_state(storyboard_id), self._apply_state)

    def refresh(self) -> None:
        if self.tree is None:
            return
        storyboard_id = self.tree.storyboard_id
        self._work(
            "refresh",
            lambda: self._load_state(storyboard_id, reconcile=True),
            lambda state: self._apply_state(state, keep_selection=True),
        )

    def start_from_job(self, job_id: str, *, status_message: str | None = None) -> None:
        self._say(status_message or "Preparing the storyboard from the clip…")
        title = f"Storyboard {job_id[:8]}"

        def work() -> _State:
            tree = self._service().create_from_clip(job_id, title)
            return self._load_state(tree.storyboard_id, reconcile=False)

        self._work("create", work, self._apply_state)

    def start_from_image(self, image_path: str, settings: dict[str, Any], title: str) -> None:
        self._say("Preparing the storyboard from the image…")

        def work() -> _State:
            tree = self._service().create_from_image(image_path, settings, title)
            return self._load_state(tree.storyboard_id, reconcile=False)

        self._work("create", work, self._apply_state)

    def inspect_clip_file(
        self,
        path: str,
        settings: dict[str, Any],
        on_plan: Callable[[ClipImportPlan], None],
        on_error: Callable[[Exception], None],
    ) -> None:
        """Probe and identify a picked MP4 on a worker (read only; nothing is created, queued or changed)."""

        service = self._service()
        self._say("Inspecting the clip…")

        def failed(error: Exception) -> None:
            self._fail(error)
            on_error(error)

        def shown(plan: ClipImportPlan) -> None:
            self._say(f"Inspected {plan.facts.filename}.")
            on_plan(plan)

        self.runner.submit(
            "inspect",
            lambda: service.inspect_clip(path, settings),
            on_result=shown,
            on_error=failed,
        )

    def start_from_clip_file(
        self,
        path: str,
        title: str,
        settings: dict[str, Any],
        *,
        expected_sha256: str | None = None,
        accept_conversion: bool = False,
        import_as_media: bool = False,
        on_done: Callable[[], None] | None = None,
        on_error: Callable[[Exception], None] | None = None,
    ) -> None:
        """Make a storyboard from a picked MP4 on a worker; success opens it, a refusal stays inline."""

        service = self._service()
        self._say("Preparing the storyboard from the clip…")

        def work() -> _State:
            tree = service.create_from_clip_file(
                path,
                title,
                settings,
                expected_sha256=expected_sha256,
                accept_conversion=accept_conversion,
                import_as_media=import_as_media,
            )
            state = self._load_state(tree.storyboard_id, reconcile=False)
            return replace(state, notice=source_text(tree.root))

        def done(state: _State) -> None:
            self._apply_state(state)
            if on_done is not None:
                on_done()

        def failed(error: Exception) -> None:
            self._fail(error)
            if on_error is not None:
                on_error(error)

        self.runner.submit("create", work, on_result=done, on_error=failed)

    def _apply_state(self, state: _State, *, keep_selection: bool = False) -> None:
        previous = self.contract.selected_id if (keep_selection and self.contract) else ROOT_PARENT
        same_tree = self.tree is not None and self.tree.storyboard_id == state.tree.storyboard_id
        if not same_tree:  # thumbnails are keyed by take id, and every root is ``root``
            self._photos.clear()
            self.cut = None
            self.target = None
        self.tree, self.views, self._root_thumbnail = state.tree, state.views, state.root_thumbnail
        self.contract = StoryboardTreeContract(self.tree, self.views, ai_reason=self._ai_reason)
        selected = (
            previous
            if previous == ROOT_PARENT or any(take.take_id == previous for take in self.tree.takes)
            else ROOT_PARENT
        )
        self.contract.select(selected)
        self.title_var.set(f"{self.tree.title} · {_saved_text(self.tree)}")
        self.dropped_text_var.set(f"Show dropped ({self.contract.dropped_count()})")
        self.render(reveal_selected=not keep_selection)
        if not (same_tree and keep_selection and self.cut is not None):
            self._load_cut(selected)
        else:
            self._after_views_changed()
        self._schedule_refresh()
        if state.notice:
            self._say(state.notice)
        elif not keep_selection:
            self._say("Ready.")

    def _after_views_changed(self) -> None:
        self._reapply_cut()
        self._update_continue_panel()

    def _reapply_cut(self) -> None:
        """A rebuilt contract has no slider ownership yet: give it the cut that is already on screen."""

        if self.contract is not None and self.cut is not None:
            self.contract.apply_cut(
                [(item.start, item.end, item.trimmed) for item in self.cut.ranges],
                len(self.cut.frames),
            )

    def _schedule_refresh(self) -> None:
        if self._refresh_after is not None:
            self.after_cancel(self._refresh_after)
            self._refresh_after = None
        if any(view.state in _LIVE_STATES for view in self.views.values()):
            self._refresh_after = self.after(REFRESH_MS, self._auto_refresh)

    def _auto_refresh(self) -> None:
        self._refresh_after = None
        self.refresh()

    def _ai_reason(self) -> str:
        ai = getattr(self.app_controller, "ai_assist", None)
        availability = getattr(ai, "availability", None)
        if not callable(availability):
            return ""
        try:
            code, reason = availability()
        except (RuntimeError, OSError, ValueError):
            return ""
        return str(reason) if code is not None else ""

    # ------------------------------------------------------------------ rendering

    def render(self, *, reveal_selected: bool = False) -> None:
        """Rebuild the tree. Only a selection or an open scrolls the selected card into view (``reveal_selected``):
        the periodic refresh and mark changes leave wherever Rob has scrolled to."""

        if self.contract is None:
            return
        self.columns.render(self.contract.columns(self.show_dropped_var.get()))
        if reveal_selected:
            self.columns.see(self.contract.selected_id)
        self._load_thumbnails()

    def _thumbnail_sources(self) -> dict[str, str]:
        sources: dict[str, str] = {}
        for take_id in self.columns.card_take_ids():
            if take_id in self._photos:
                continue
            if take_id == ROOT_PARENT:
                path = self._root_thumbnail
            else:
                view = self.views.get(take_id)
                path = None if view is None else view.thumbnail_path
            if path:
                sources[take_id] = path
        return sources

    def _load_thumbnails(self) -> None:
        if not self.media.thumbnails:
            return  # hidden: nothing is read, decoded or kept for a thumbnail nobody can see
        sources = self._thumbnail_sources()
        if not sources:
            return
        cache = self.cache
        generation = self._thumb_generation

        def work() -> dict[str, Image.Image]:
            loaded: dict[str, Image.Image] = {}
            for take_id, path in sources.items():
                try:
                    loaded[take_id] = cache.thumbnail(path)
                except OSError:
                    continue  # a missing frame leaves the placeholder; the status text carries the reason
            return loaded

        self._work("thumbnails", work, lambda loaded: self._apply_thumbnails(loaded, generation))

    def _apply_thumbnails(
        self, loaded: dict[str, Image.Image], generation: int | None = None
    ) -> None:
        if not self.media.thumbnails or (
            generation is not None and generation != self._thumb_generation
        ):
            return  # a result from before the switch must not bring hidden thumbnails back
        for take_id, image in loaded.items():
            photo = ImageTk.PhotoImage(image, master=self)
            self._photos[take_id] = photo
            self.columns.set_thumbnail(take_id, photo)

    # ------------------------------------------------------------------ selection and the cut

    def select_take(self, take_id: str) -> None:
        if self.contract is None:
            return
        if take_id != self.contract.selected_id:
            # A different take is a different clip to extend: aim Continue at its last frame (where the viewer starts)
            # instead of keeping an ancestor's frame that merely sits on the path.
            self.target = None
        self.contract.select(take_id)
        self.render(reveal_selected=True)
        self._load_cut(take_id)

    def _load_cut(self, node_id: str) -> None:
        tree, contract = self.tree, self.contract
        if tree is None or contract is None:
            return
        self.cut = None
        self._say("")
        allowed, reason = contract.continue_allowed(node_id)
        if not allowed:
            self.viewer.clear()
            self._update_continue_panel()
            self._say(reason)
            return
        service = self._service()
        self._work(
            "cut",
            lambda: service.parent_cut(tree, node_id),
            lambda cut: self._apply_cut(node_id, cut),
        )

    def _apply_cut(self, node_id: str, cut: CutManifest | None) -> None:
        contract = self.contract
        if contract is None or contract.selected_id != node_id:
            return
        self.cut = cut
        if cut is None:
            self.viewer.clear()
            self._say(
                "The still image has no frames; the first takes start from the image."
                if node_id == ROOT_PARENT
                else "This take has no frames yet."
            )
            self._update_continue_panel()
            return
        try:
            contract.apply_cut(
                [(item.start, item.end, item.trimmed) for item in cut.ranges], len(cut.frames)
            )
        except ValueError as exc:
            self.viewer.clear()
            self._say(str(exc))
            return
        self.viewer.set_cut(
            len(cut.frames),
            contract.joins(),
            cut.fps,
            title=f"{contract.label(node_id)} · cut · {len(cut.frames) / cut.fps:.1f} s",
        )
        root = self.tree.root if self.tree is not None else None
        note = "" if root is None else (root.smoothing_text or source_text(root))
        self.viewer.note_var.set(note)
        self._update_continue_panel()

    def _readout(self, index: int) -> str:
        contract = self.contract
        if contract is None or self.cut is None:
            return ""
        try:
            return contract.readout(index)
        except (IndexError, KeyError):
            return f"frame {index + 1}"

    def _request_frame(self, index: int) -> None:
        cut = self.cut
        if not self.media.viewer or cut is None or not 0 <= index < len(cut.frames):
            return
        path = cut.frames[index].path
        self._frame_path = path
        cache = self.cache
        self._work("frame", lambda: cache.frame(path), self._apply_frame)

    def _apply_frame(self, image: Image.Image) -> None:
        if not self.media.viewer:
            return  # the viewer was hidden while this frame was loading
        self.viewer.show_image(image)

    # ------------------------------------------------------------------ media visibility

    def _apply_body_weights(self) -> None:
        """With the picture gone the Continue panel takes the space the viewer was holding."""

        self._body.columnconfigure(0, weight=3 if self.media.viewer else 1)
        self._body.columnconfigure(1, weight=2 if self.media.viewer else 3)

    def _toggle_thumbnails(self) -> None:
        self.media = replace(self.media, thumbnails=bool(self.show_thumbnails_var.get()))
        self._thumb_generation += 1
        if not self.media.thumbnails:
            self._photos.clear()
        self.columns.set_thumbnails_visible(self.media.thumbnails)
        if self.media.thumbnails:
            self._load_thumbnails()
        self._save_media()

    def _toggle_viewer(self) -> None:
        """Hide or restore the picture only: the selected take, frame and Continue target are never touched."""

        self.media = replace(self.media, viewer=bool(self.show_viewer_var.get()))
        self.viewer.set_media_visible(self.media.viewer)
        self._apply_body_weights()
        self._save_media()

    def _save_media(self) -> None:
        store, prefs = self._ui_store, self.media
        self._work("media_prefs", lambda: save_media_prefs(store, prefs))

    # ------------------------------------------------------------------ marks and titles

    def set_mark(self, take_id: str, mark: str) -> None:
        tree = self.tree
        if tree is None:
            return
        service = self._service()

        def work() -> StoryboardTree:
            saved: StoryboardTree = service.store.save(tree.with_mark(take_id, mark))
            return saved

        self._work(f"mark:{take_id}", work, self._apply_saved_tree)

    def _apply_saved_tree(self, tree: StoryboardTree) -> None:
        if self.tree is None or tree.storyboard_id != self.tree.storyboard_id:
            return
        selected = self.contract.selected_id if self.contract else ROOT_PARENT
        self.tree = tree
        self.contract = StoryboardTreeContract(tree, self.views, ai_reason=self._ai_reason)
        self.contract.select(selected)
        self._reapply_cut()
        self.title_var.set(f"{tree.title} · {_saved_text(tree)}")
        self.dropped_text_var.set(f"Show dropped ({self.contract.dropped_count()})")
        self.render()

    def rename(self, title: str) -> None:
        tree = self.tree
        if tree is None:
            return
        service = self._service()
        self._work(
            "rename", lambda: service.store.save(tree.renamed(title)), self._apply_saved_tree
        )

    def save_as(self, title: str) -> None:
        tree = self.tree
        if tree is None:
            return
        service = self._service()

        def work() -> _State:
            copy = service.store.save(tree.duplicate(title))
            return self._load_state(copy.storyboard_id, reconcile=False)

        self._work("save_as", work, self._apply_state)

    # ------------------------------------------------------------------ dialogs (thin; the work is above)

    def _ask_new(self) -> None:
        _NewStoryboardDialog(self)

    def default_browse_root(self) -> str | None:
        try:
            return str(self._service().output_root())
        except (RuntimeError, AttributeError, OSError):
            return None

    def _ask_open(self) -> None:
        service = self._service()
        self._work("list", lambda: service.store.list_trees(), self._show_open_dialog)

    def _show_open_dialog(self, rows: list[tuple[str, str, str]]) -> None:
        _OpenStoryboardDialog(self, rows)

    def _ask_rename(self) -> None:
        if self.tree is None:
            return
        from tkinter import simpledialog

        title = simpledialog.askstring(
            "Rename storyboard", "Title:", initialvalue=self.tree.title, parent=self
        )
        if title and title.strip():
            self.rename(title.strip())

    def _ask_save_as(self) -> None:
        if self.tree is None:
            return
        from tkinter import simpledialog

        title = simpledialog.askstring(
            "Save storyboard as",
            "Title of the copy:",
            initialvalue=f"{self.tree.title} copy",
            parent=self,
        )
        if title and title.strip():
            self.save_as(title.strip())

    # ------------------------------------------------------------------ the Continue panel (B4)

    def _build_continue_panel(self, host: ttk.Frame) -> None:
        self.target = None
        self._busy = False
        self.continue_title_var = tk.StringVar(value="Continue")
        self.mode_var = tk.StringVar(value="parallel")
        self.engine_var = tk.StringVar(value="")
        self.ai_reason_var = tk.StringVar(value="")
        self.experimental_var = tk.BooleanVar(value=False)  # never restored from the file
        host.columnconfigure(0, weight=1)
        ttk.Label(host, textvariable=self.continue_title_var, style="Dark.TLabel").grid(
            row=0, column=0, sticky="w"
        )
        top = ttk.Frame(host, style="Panel.TFrame")
        top.grid(row=1, column=0, sticky="ew")
        self.parallel_radio = ttk.Radiobutton(
            top,
            text="Parallel",
            variable=self.mode_var,
            value="parallel",
            command=self._refresh_queue_label,
        )
        self.sequential_radio = ttk.Radiobutton(
            top,
            text="Sequential",
            variable=self.mode_var,
            value="sequential",
            command=self._refresh_queue_label,
        )
        self.parallel_radio.pack(side="left")
        self.sequential_radio.pack(side="left", padx=6)
        attach_tooltip(self.parallel_radio, MODE_TIPS["parallel"])
        attach_tooltip(self.sequential_radio, MODE_TIPS["sequential"])
        self.ai_button = ttk.Button(top, text="Write with AI…", state="disabled")
        self.ai_button.pack(side="right")
        ttk.Label(host, textvariable=self.ai_reason_var, style="Dark.TLabel").grid(
            row=2, column=0, sticky="e"
        )
        self.rows_widget = ContinueRowsV2(host, on_change=self._rows_changed)
        self.rows_frame = self.rows_widget
        self.rows_widget.grid(row=3, column=0, sticky="ew")
        self.add_row_button = ttk.Button(
            host, text="+ Add row (up to 6)", style="Dark.TButton", command=self.add_row
        )
        self.add_row_button.grid(row=4, column=0, sticky="w", pady=2)
        ttk.Label(host, textvariable=self.engine_var, style="Dark.TLabel", wraplength=480).grid(
            row=5, column=0, sticky="w"
        )
        self.experimental_check = ttk.Checkbutton(
            host,
            text="This workflow is experimental: allow it for this Continue only",
            variable=self.experimental_var,
        )
        actions = ttk.Frame(host, style="Panel.TFrame")
        actions.grid(row=7, column=0, sticky="e", pady=4)
        self.preview_button = ttk.Button(
            actions, text="Preview", style="Dark.TButton", command=self.preview
        )
        self.queue_button = ttk.Button(
            actions, text="Queue 1 takes", style="Dark.TButton", command=self.queue
        )
        self.preview_button.pack(side="left", padx=2)
        self.queue_button.pack(side="left", padx=2)
        self.add_row()
        self._refresh_ai_button()

    def _refresh_ai_button(self) -> None:
        """Write with AI… is always disabled in this package; the reason is the readiness record's when reachable."""

        text = self._ai_reason().strip() or AI_NOT_SET_UP
        self.ai_button.configure(state="disabled")
        self.ai_reason_var.set(text)
        if text != self._ai_tooltip_text:
            self._ai_tooltip_text = text
            attach_tooltip(self.ai_button, text)

    @property
    def _row_widgets(self) -> list[ContinueRowFields]:
        return self.rows_widget.rows

    def add_row(self, prompt: str = "", negative: str = "", seed: str = "") -> None:
        """Add a row; ``seed`` is blank/``random`` (Random) or a number (Fixed), as the service reads it."""

        text = seed.strip()
        random_seed = text.lower() in ("", "random")
        self.rows_widget.add_row(
            prompt,
            negative,
            SEED_RANDOM if random_seed else SEED_FIXED,
            "" if random_seed else text,
        )

    def remove_row(self, row: ContinueRowFields) -> None:
        self.rows_widget.remove_row(row)

    def set_rows(self, prompts: list[str]) -> None:
        while len(self._row_widgets) > 1:
            self.remove_row(self._row_widgets[-1])
        self._row_widgets[0].prompt_var.set(prompts[0] if prompts else "")
        for prompt in prompts[1:]:
            self.add_row(prompt)

    def _rows_changed(self) -> None:
        self.add_row_button.configure(state="disabled" if self.rows_widget.full else "normal")
        self._refresh_queue_label()

    def _refresh_queue_label(self) -> None:
        self.queue_button.configure(
            text=StoryboardTreeContract.queue_label(self.mode_var.get(), len(self._row_widgets))
        )

    def _continue_rows(self) -> tuple[tuple[ContinueRow, ...], list[str]]:
        """The rows as the service reads them, and the seed problems found (Random never has one)."""

        rows: list[ContinueRow] = []
        problems: list[str] = []
        for number, row in enumerate(self._row_widgets, start=1):
            seed, problem = StoryboardTreeContract.seed_text(
                row.seed_mode, row.seed_var.get(), number
            )
            if problem:
                problems.append(problem)
                seed = SEED_RANDOM.lower()  # judged once, above
            rows.append(ContinueRow(row.prompt_var.get(), row.negative_var.get(), seed))
        return tuple(rows), problems

    def _set_target(self, node_id: str, handoff_index: int | None) -> None:
        self.target = (node_id, handoff_index)
        self._update_continue_panel()

    def _continue_from_frame(self, index: int) -> None:
        if self.contract is None or self.cut is None:
            return
        try:
            owner, handoff = self.contract.continue_target(index)
        except IndexError:
            return
        self._set_target(owner, handoff)

    def _update_continue_panel(self) -> None:
        contract, tree = self.contract, self.tree
        if contract is None or tree is None:
            return
        self._refresh_ai_button()
        selected = contract.selected_id
        if self.cut is not None:
            if self.target is None or self.target[0] not in contract.path_to(selected):
                self._set_target(selected, len(self.cut.frames) - 1)
                return
        elif selected == ROOT_PARENT and tree.root.kind == "image":
            self.target = (ROOT_PARENT, None)
        else:
            self.target = None
        self.engine_var.set(contract.engine_line())
        self.rows_widget.hint_var.set(contract.negative_hint())
        allowed = False
        if self.target is None:
            self.continue_title_var.set("Continue")
            self.banner_var.set(NO_TARGET_TEXT)
        else:
            owner, handoff = self.target
            allowed = contract.continue_allowed(owner)[0]
            where = "the still image" if handoff is None else f"its frame {handoff + 1}"
            self.continue_title_var.set(f"Continue {contract.label(owner)} from {where}")
        self.banner_var.set(self._banner_text())
        state = "normal" if allowed and not self._busy else "disabled"
        self.preview_button.configure(state=state)
        self.queue_button.configure(state=state)
        self._sync_experimental()

    def _banner_text(self) -> str:
        """Which take and frame the next Continue extends: the Continue target, said where Rob is looking."""

        if self.target is None or self.contract is None:
            return NO_TARGET_TEXT
        owner, handoff = self.target
        where = "the still image" if handoff is None else f"frame {handoff + 1}"
        return f"Continuing from: {self.contract.label(owner)} · {where}"

    def _sync_experimental(self) -> None:
        tree = self.tree
        if tree is None:
            return
        needs = bool(
            getattr(self._service(), "needs_experimental_opt_in", lambda _tree: False)(tree)
        )
        if needs:
            self.experimental_check.grid(row=6, column=0, sticky="w")
        else:
            self.experimental_check.grid_remove()
            self.experimental_var.set(False)

    def _build_request(self) -> ContinueRequest | None:
        tree, target = self.tree, self.target
        if tree is None or target is None or self.contract is None:
            self._say("Choose a take and a frame to continue from.")
            return None
        rows, problems = self._continue_rows()
        errors = [*self.contract.validate_rows(rows), *problems]
        if errors:
            self._say(" ".join(errors))
            return None
        owner, handoff = target
        return ContinueRequest(
            storyboard_id=tree.storyboard_id,
            expected_revision=tree.revision,
            parent_id=owner,
            handoff_index=handoff,
            mode="sequential" if self.mode_var.get() == "sequential" else "parallel",
            rows=rows,
            experimental_opt_in=bool(self.experimental_var.get()),
        )

    def preview(self) -> None:
        request = self._build_request()
        if request is None:
            return
        service = self._service()
        self._work("preview", lambda: service.preview(request), self._show_preview)

    def _show_preview(self, preview: Any) -> None:
        jobs = (
            "one chained job"
            if preview.jobs == 1 and preview.segments > 1
            else f"{preview.jobs} job(s)"
        )
        self._say(
            f"Preview: {jobs}, {preview.segments} segment(s) · lead-in {preview.lead_in_frames} frames · "
            f"cut {preview.total_cut_frames} frames at {preview.fps} fps · "
            f"{preview.workflow_id} {preview.workflow_version} · seeds {', '.join(preview.seeds)}. "
            "Nothing was queued."
        )

    def queue(self) -> None:
        if self._busy:
            return
        request = self._build_request()
        if request is None:
            return
        service = self._service()
        self._busy = True
        self._update_continue_panel()
        self._say("Queueing…")
        self.runner.submit(
            "submit",
            lambda: service.submit(request),
            on_result=self._after_submit,
            on_error=self._submit_failed,
        )

    def _submit_failed(self, error: Exception) -> None:
        self._busy = False
        self._update_continue_panel()
        self._fail(error)

    def _after_submit(self, result: Any) -> None:
        self._busy = False
        self._say(f"Queued {len(result.take_ids)} take(s) as {len(result.job_ids)} job(s).")
        self.refresh()
        self._update_continue_panel()

    # ------------------------------------------------------------------ compare, export, resume, replay (B5)

    def open_compare(self, column_title: str) -> StoryboardCompareWindowV2 | None:
        """Play the completed, non-dropped takes of one column side by side (their own clips, no ratings)."""

        contract = self.contract
        if contract is None:
            return None
        clips: list[tuple[str, str]] = []
        for column in contract.columns(show_dropped=False):
            if column.title != column_title:
                continue
            for card in column.cards:
                view = self.views.get(card.take_id)
                if view is not None and view.state == "completed" and view.clip_path:
                    clips.append((card.label, view.clip_path))
        if len(clips) < 2:
            self._say("Compare needs two or more finished takes in the column.")
            return None
        window = StoryboardCompareWindowV2(self, clips=clips, preview_fn=self.compare_preview_fn)
        self.compare_windows.append(window)
        return window

    def _compare_hook(self, column_title: str) -> None:
        self.open_compare(column_title)

    def _chain_info(self, take_id: str) -> bool:
        """True when later takes of the same chain follow this one (so the stitched file runs past it)."""

        tree = self.tree
        if tree is None or take_id == ROOT_PARENT:
            return False
        take = next(item for item in tree.takes if item.take_id == take_id)
        return take.mode == "sequential" and any(
            other.batch_id == take.batch_id and other.chain_position > take.chain_position
            for other in tree.takes
        )

    def export_text(self, take_id: str, cut_length: int | None) -> str:
        """What Export cut… offers for one take. Nothing is re-encoded: the stitched file already exists."""

        view = self.views.get(take_id)
        label = self.contract.label(take_id) if self.contract else take_id
        if take_id == ROOT_PARENT:
            return "The root clip is not a stitched cut. Export a take instead."
        if view is None or not view.encoded or not view.stitched_path:
            return (
                f"{label}: not encoded. Its frames can still be viewed and continued; "
                "Resume re-encodes the stitched video."
            )
        lines = [f"{label}: {view.stitched_path}"]
        if self._chain_info(take_id):
            fps = (
                self.cut.fps
                if self.cut is not None
                else int(self.tree.root.fps if self.tree else 16)
            )
            end = "" if cut_length is None else f" and ends at {_timecode(cut_length, fps)}"
            lines.append(
                f"This take is part of a chain. The stitched file is the whole chain's cut{end}; "
                "there is no file that stops at this take."
            )
        return "\n".join(lines)

    def _ask_export(self) -> None:
        contract, tree = self.contract, self.tree
        if contract is None or tree is None:
            return
        take_id = contract.selected_id
        view = self.views.get(take_id)
        service = self._service()

        def work() -> tuple[str, int | None]:
            cut = service.parent_cut(tree, take_id) if take_id != ROOT_PARENT else None
            return take_id, None if cut is None else len(cut.frames)

        def show(result: tuple[str, int | None]) -> None:
            _ExportDialog(self, take_id, self.export_text(result[0], result[1]), view)

        self._work("export", work, show)

    def reveal_stitched(self, take_id: str) -> None:
        view = self.views.get(take_id)
        if view is None or not view.stitched_path:
            self._say("Nothing to reveal: this take has no stitched video.")
            return
        path = view.stitched_path

        def work() -> Any:
            return reveal_in_file_manager(path)

        def done(result: Any) -> None:
            self._say("" if result.ok else str(result.message))

        self._work("reveal", work, done)

    def send_to_movie_clips(self, take_id: str) -> None:
        view = self.views.get(take_id)
        if view is None or not view.encoded or not view.stitched_path:
            self._say("This take is not encoded; there is no stitched video to send.")
            return
        from src.gui.controllers.video_workspace_handoff import route_bundle_to_movie_clips

        main_window = getattr(self.app_controller, "main_window", None)
        if main_window is None:
            self._say("The main window is not available.")
            return
        bundle = {
            "stage": "assembled_video",
            "primary_path": view.stitched_path,
            "output_paths": [view.stitched_path],
        }
        try:
            route_bundle_to_movie_clips(
                main_window=main_window,
                bundle=bundle,
                status_message="Loaded the storyboard cut into Movie Clips.",
            )
        except RuntimeError as exc:
            self._say(str(exc))

    def resume_take(self, take_id: str) -> None:
        self._sequence_action(take_id, "resume_sequence")

    def replay_take(self, take_id: str) -> None:
        self._sequence_action(take_id, "replay_sequence")

    def _sequence_action(self, take_id: str, method: str) -> None:
        view = self.views.get(take_id)
        allowed = view is not None and (
            view.can_resume if method == "resume_sequence" else view.can_replay
        )
        if view is None or not allowed or not view.shown_job_id:
            self._say("That take cannot be resumed or replayed right now.")
            return
        job_id, ledger = view.shown_job_id, view.ledger_path
        controller = self.app_controller.get_video_workflow_controller()
        action = getattr(controller, method)
        storyboard_id = self.tree.storyboard_id if self.tree else ""

        def work() -> _State:
            new_job = action(job_id, ledger_path=ledger)
            state = self._load_state(
                storyboard_id
            )  # reconcile adopts the new job (a resume joins the take)
            return replace(state, notice=f"Queued {method.split('_')[0]} as job {new_job}.")

        self._work("sequence", work, lambda state: self._apply_state(state, keep_selection=True))

    # ------------------------------------------------------------------ lifetime

    def destroy(self) -> None:
        if self._refresh_after is not None:
            self.after_cancel(self._refresh_after)
            self._refresh_after = None
        self.runner.close()
        super().destroy()


class _ExportDialog(tk.Toplevel):
    """Export cut…: reveal the stitched video, send it to Movie Clips, or resume when it is not encoded."""

    def __init__(
        self, tab: StoryboardTabFrameV2, take_id: str, text: str, view: TakeView | None
    ) -> None:
        super().__init__(tab)
        self.title("Export cut")
        self.transient(tab.winfo_toplevel())
        self.summary = text
        body = ttk.Frame(self, padding=10)
        body.pack(fill="both", expand=True)
        ttk.Label(body, text=text, wraplength=520, justify="left").pack(anchor="w")
        buttons = ttk.Frame(body)
        buttons.pack(anchor="e", pady=(8, 0))
        self.buttons: dict[str, ttk.Button] = {}
        if view is not None and view.encoded:
            self._add(buttons, "Reveal stitched video", lambda: tab.reveal_stitched(take_id))
            self._add(buttons, "Send to Movie Clips", lambda: tab.send_to_movie_clips(take_id))
        elif view is not None and view.can_resume:
            self._add(buttons, "Resume", lambda: tab.resume_take(take_id))
        self._add(buttons, "Close", self.destroy)

    def _add(self, parent: ttk.Frame, text: str, command: Callable[[], None]) -> None:
        button = ttk.Button(parent, text=text, command=command)
        button.pack(side="left", padx=2)
        self.buttons[text] = button


class _NewStoryboardDialog(tk.Toplevel):
    """Start from a video clip (MP4) or a still image, picked with the native file browser. Non-modal; the tab works.

    The clip is inspected on a worker as soon as it is chosen; Create stays unavailable (with the reason beside it)
    until the clip can be used, any conversion it needs has been accepted, and, for a clip StableNew cannot continue
    from its own job, importing the encoded MP4 as media has been chosen."""

    def __init__(self, tab: StoryboardTabFrameV2) -> None:
        super().__init__(tab)
        self.title("New storyboard")
        self.transient(tab.winfo_toplevel())
        self._tab = tab
        self.plan: ClipImportPlan | None = None
        self._known_refused = False
        self._title_edited = False
        self._checked: tuple[str, str, str, str] | None = None
        self._inspection = 0  # the latest inspection request; an older answer is ignored
        self.title_var = tk.StringVar(value="New storyboard")
        self.clip_var = tk.StringVar()
        self.image_var = tk.StringVar()
        self.summary_var = tk.StringVar(value="No clip chosen.")
        self.hint_var = tk.StringVar()
        self.convert_var = tk.BooleanVar(value=False)
        self.media_var = tk.BooleanVar(value=False)
        self.workflow_var = tk.StringVar(value=self._default_workflow())
        self.version_var = tk.StringVar()
        self.frames_var = tk.StringVar()
        body = ttk.Frame(self, padding=10)
        body.pack(fill="both", expand=True)
        body.columnconfigure(1, weight=1)
        ttk.Label(body, text="Title").grid(row=0, column=0, sticky="w")
        title_entry = ttk.Entry(body, textvariable=self.title_var, width=52)
        title_entry.grid(row=0, column=1, sticky="ew")
        title_entry.bind("<Key>", lambda _e: setattr(self, "_title_edited", True), add="+")

        clip = ttk.LabelFrame(body, text="Video clip (MP4)", padding=6)
        clip.grid(row=1, column=0, columnspan=2, sticky="ew", pady=(8, 0))
        clip.columnconfigure(1, weight=1)
        self.browse_clip_button = ttk.Button(
            clip, text="Browse for video clip…", command=self.browse_clip
        )
        self.browse_clip_button.grid(row=0, column=0, sticky="w")
        self.clip_entry = ttk.Entry(clip, textvariable=self.clip_var, state="readonly")
        self.clip_entry.grid(row=0, column=1, sticky="ew", padx=(6, 0))
        attach_tooltip(self.clip_entry, "The full path of the chosen clip.")
        ttk.Label(clip, textvariable=self.summary_var, justify="left", wraplength=520).grid(
            row=1, column=0, columnspan=2, sticky="w", pady=(4, 0)
        )
        self.convert_check = ttk.Checkbutton(
            clip,
            text="Apply this conversion (the original file is not changed)",
            variable=self.convert_var,
            command=self._refresh,
        )
        self.media_check = ttk.Checkbutton(
            clip,
            text="Import the encoded MP4 as media instead (no StableNew job provenance)",
            variable=self.media_var,
            command=self._refresh,
        )

        still = ttk.LabelFrame(body, text="Still image", padding=6)
        still.grid(row=2, column=0, columnspan=2, sticky="ew", pady=(8, 0))
        still.columnconfigure(1, weight=1)
        self.browse_image_button = ttk.Button(
            still, text="Browse for still image…", command=self.browse_image
        )
        self.browse_image_button.grid(row=0, column=0, sticky="w")
        self.image_entry = ttk.Entry(still, textvariable=self.image_var, state="readonly")
        self.image_entry.grid(row=0, column=1, sticky="ew", padx=(6, 0))

        flow = ttk.LabelFrame(body, text="Workflow for the new takes", padding=6)
        flow.grid(row=3, column=0, columnspan=2, sticky="ew", pady=(8, 0))
        flow.columnconfigure(1, weight=1)
        ttk.Label(
            flow,
            text="Used for a still image, or an MP4 StableNew did not make. A StableNew clip keeps its own job's workflow.",
            wraplength=520,
        ).grid(row=0, column=0, columnspan=2, sticky="w")
        self._workflow_entries: list[ttk.Entry] = []
        for row, (label, var) in enumerate(
            (
                ("Workflow id", self.workflow_var),
                ("Version (optional)", self.version_var),
                ("Frames (optional)", self.frames_var),
            ),
            start=1,
        ):
            ttk.Label(flow, text=label).grid(row=row, column=0, sticky="w")
            entry = ttk.Entry(flow, textvariable=var)
            entry.grid(row=row, column=1, sticky="ew")
            entry.bind("<FocusOut>", lambda _e: self._recheck(), add="+")
            self._workflow_entries.append(entry)

        ttk.Label(body, textvariable=self.hint_var, wraplength=560, justify="left").grid(
            row=4, column=0, columnspan=2, sticky="w", pady=(8, 0)
        )
        buttons = ttk.Frame(body)
        buttons.grid(row=5, column=0, columnspan=2, sticky="e", pady=(8, 0))
        self.create_button = ttk.Button(buttons, text="Create", command=self.create)
        self.create_button.pack(side="right")
        ttk.Button(buttons, text="Cancel", command=self.destroy).pack(side="right", padx=4)
        self._refresh()

    # ------------------------------------------------------------------ inputs

    def _default_workflow(self) -> str:
        window = self._tab.winfo_toplevel()
        variable = getattr(getattr(window, "video_workflow_tab", None), "workflow_var", None)
        try:
            return str(variable.get()) if variable is not None else ""
        except tk.TclError:
            return ""

    def settings(self) -> dict[str, Any]:
        settings: dict[str, Any] = {"workflow_id": self.workflow_var.get().strip()}
        if self.version_var.get().strip():
            settings["workflow_version"] = self.version_var.get().strip()
        if self.frames_var.get().strip():
            settings["frame_count"] = self.frames_var.get().strip()
        return settings

    def _signature(self) -> tuple[str, str, str, str]:
        return (
            self.clip_var.get(),
            self.workflow_var.get().strip(),
            self.version_var.get().strip(),
            self.frames_var.get().strip(),
        )

    # ------------------------------------------------------------------ browsing (the picker never changes anything)

    def browse_clip(self) -> None:
        chosen = self._tab.ask_open_file(
            parent=self, **clip_dialog_options(self._tab.default_browse_root())
        )
        if not chosen:
            return  # cancelled: nothing changes, here or in the open storyboard
        self._known_refused = False
        self.convert_var.set(False)
        self.media_var.set(False)
        self.clip_var.set(str(chosen))
        self.image_var.set("")
        self._inspect()

    def browse_image(self) -> None:
        chosen = self._tab.ask_open_file(
            parent=self, **image_dialog_options(self._tab.default_browse_root())
        )
        if not chosen:
            return
        self.image_var.set(str(chosen))
        self.clip_var.set("")
        self._inspection += (
            1  # an inspection still running belongs to a clip that is no longer chosen
        )
        self.plan = None
        self.summary_var.set("No clip chosen.")
        self._checked = None
        self._refresh()

    def _inspect(self) -> None:
        path = self.clip_var.get()
        if not path:
            return
        self._checked = self._signature()
        self._inspection += 1
        ticket = self._inspection
        self.summary_var.set("Inspecting…")
        self._tab.inspect_clip_file(
            path,
            self.settings(),
            lambda plan: self._show_plan(plan, ticket),
            lambda error: self._show_problem(error, ticket),
        )

    def _recheck(self) -> None:
        if self.clip_var.get() and self._checked is not None and self._signature() != self._checked:
            self._inspect()

    def _alive(self) -> bool:
        try:
            return bool(self.winfo_exists())
        except tk.TclError:
            return False

    def _show_plan(self, plan: ClipImportPlan, ticket: int) -> None:
        if not self._alive() or ticket != self._inspection:
            return
        self.plan = plan
        if not self._title_edited:
            self.title_var.set(plan.title)
        self.summary_var.set("\n".join(plan.lines()))
        self._refresh()

    def _show_problem(self, error: Exception, ticket: int) -> None:
        if not self._alive() or ticket != self._inspection:
            return
        self.plan = None
        self.summary_var.set(str(error))
        self._refresh()

    # ------------------------------------------------------------------ actions

    def _actions(self) -> Any:
        return import_actions(
            self.plan,
            conversion_accepted=bool(self.convert_var.get()),
            media_chosen=bool(self.media_var.get()),
            known_refused=self._known_refused,
        )

    def _refresh(self) -> None:
        if not self.clip_var.get():
            self.convert_check.grid_remove()
            self.media_check.grid_remove()
            self.hint_var.set("")
            self.create_button.configure(state="normal" if self.image_var.get() else "disabled")
            return
        actions = self._actions()
        for check, shown, row in (
            (self.convert_check, actions.show_conversion, 2),
            (self.media_check, actions.show_media_choice, 3),
        ):
            if shown:
                check.grid(row=row, column=0, columnspan=2, sticky="w")
            else:
                check.grid_remove()
        self.hint_var.set(actions.hint)
        self.create_button.configure(state="normal" if actions.can_create else "disabled")

    def create(self) -> None:
        title = self.title_var.get().strip() or "New storyboard"
        if not self.clip_var.get():
            image = self.image_var.get().strip()
            if not image:
                self._tab._say("Choose a video clip or a still image.")
                return
            self._tab.start_from_image(image, self.settings(), title)
            self.destroy()
            return
        actions = self._actions()
        if not actions.can_create or self.plan is None:
            self._tab._say(actions.hint)
            return
        self._tab.start_from_clip_file(
            self.clip_var.get(),
            title,
            self.settings(),
            expected_sha256=self.plan.facts.sha256,
            accept_conversion=bool(self.convert_var.get()),
            import_as_media=bool(self.media_var.get()),
            on_done=self._finished,
            on_error=self._refused,
        )

    def _finished(self) -> None:
        if self._alive():
            self.destroy()

    def _refused(self, error: Exception) -> None:
        """A refusal stays here, inline; StableNew's own refusal of a known clip offers the media import."""

        if not self._alive():
            return
        from src.video.storyboard_import import KnownClipRefused

        if isinstance(error, KnownClipRefused):
            self._known_refused = True
        self.hint_var.set(str(error))
        self._refresh()
        self.hint_var.set(str(error))


class _OpenStoryboardDialog(tk.Toplevel):
    def __init__(self, tab: StoryboardTabFrameV2, rows: list[tuple[str, str, str]]) -> None:
        super().__init__(tab)
        self.title("Open storyboard")
        self.transient(tab.winfo_toplevel())
        self._tab = tab
        self._rows = rows
        self.listbox = tk.Listbox(self, width=60, height=12)
        for _id, title, updated in rows:
            self.listbox.insert("end", f"{title}   {updated[:16].replace('T', ' ')}")
        self.listbox.pack(fill="both", expand=True, padx=8, pady=8)
        self.listbox.bind("<Double-Button-1>", lambda _e: self.choose())
        ttk.Button(self, text="Open", command=self.choose).pack(pady=(0, 8))

    def choose(self) -> None:
        selection: tuple[int, ...] = tuple(self.listbox.curselection())  # type: ignore[no-untyped-call]
        if selection:
            self._tab.open_storyboard(self._rows[selection[0]][0])
            self.destroy()


__all__ = ["StoryboardTabFrameV2"]
