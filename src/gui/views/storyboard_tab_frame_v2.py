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
from tkinter import ttk
from typing import Any

from PIL import Image, ImageTk

from src.controller.storyboard_submission_service import ContinueRequest, ContinueRow
from src.gui.tooltip import attach_tooltip
from src.gui.view_contracts.edit_work_runner import build_edit_work_runner
from src.gui.view_contracts.storyboard_tree_contract import AI_NOT_SET_UP, StoryboardTreeContract
from src.gui.views.storyboard_compare_window_v2 import StoryboardCompareWindowV2
from src.gui.widgets.storyboard_columns_v2 import StoryboardColumnsV2
from src.gui.widgets.storyboard_viewer_v2 import StoryboardViewerV2
from src.utils.os_shell import reveal_in_file_manager
from src.video.review_preview import prepare_review_preview
from src.video.sequence_plan import ROOT_PARENT
from src.video.storyboard_cut import CutManifest
from src.video.storyboard_frame_cache import FrameCache
from src.video.storyboard_projection import TakeView
from src.video.storyboard_tree import MAX_ROWS, StoryboardTree

REFRESH_MS = 6000
_LIVE_STATES = frozenset({"pending", "queued", "running"})


@dataclass(frozen=True, slots=True)
class _State:
    tree: StoryboardTree
    views: dict[str, TakeView]
    root_thumbnail: str | None
    notice: str = ""


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
    def __init__(self, parent: tk.Misc, *, app_controller: Any, app_state: Any) -> None:
        super().__init__(parent, style="Panel.TFrame")
        self.app_controller = app_controller
        self.app_state = app_state
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
        self.rowconfigure(2, weight=1)
        self.columnconfigure(0, weight=1)
        self._build_toolbar()
        self.columns = StoryboardColumnsV2(
            self,
            on_select=self.select_take,
            on_mark=self.set_mark,
            on_compare=self._compare_hook,
            on_resume=self.resume_take,
            on_replay=self.replay_take,
        )
        self.columns.grid(row=1, column=0, sticky="ew", padx=8)
        body = ttk.Frame(self, style="Panel.TFrame")
        body.grid(row=2, column=0, sticky="nsew", padx=8, pady=4)
        body.columnconfigure(0, weight=3)
        body.columnconfigure(1, weight=2)
        body.rowconfigure(0, weight=1)
        self.viewer = StoryboardViewerV2(
            body,
            on_frame=self._request_frame,
            on_continue=self._continue_from_frame,
            readout=self._readout,
        )
        self.viewer.grid(row=0, column=0, sticky="nsew", padx=(0, 8))
        self.continue_host = ttk.Frame(body, style="Panel.TFrame")
        self.continue_host.grid(row=0, column=1, sticky="nsew")
        self._build_continue_panel(self.continue_host)
        ttk.Label(self, textvariable=self.status_var, style="Dark.TLabel", wraplength=900).grid(
            row=3, column=0, sticky="ew", padx=8, pady=(0, 6)
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
        self.render()
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

    def render(self) -> None:
        if self.contract is None:
            return
        self.columns.render(self.contract.columns(self.show_dropped_var.get()))
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
        sources = self._thumbnail_sources()
        if not sources:
            return
        cache = self.cache

        def work() -> dict[str, Image.Image]:
            loaded: dict[str, Image.Image] = {}
            for take_id, path in sources.items():
                try:
                    loaded[take_id] = cache.thumbnail(path)
                except OSError:
                    continue  # a missing frame leaves the placeholder; the status text carries the reason
            return loaded

        self._work("thumbnails", work, self._apply_thumbnails)

    def _apply_thumbnails(self, loaded: dict[str, Image.Image]) -> None:
        for take_id, image in loaded.items():
            photo = ImageTk.PhotoImage(image, master=self)
            self._photos[take_id] = photo
            self.columns.set_thumbnail(take_id, photo)

    # ------------------------------------------------------------------ selection and the cut

    def select_take(self, take_id: str) -> None:
        if self.contract is None:
            return
        self.contract.select(take_id)
        self.render()
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
        smoothing = self.tree.root.smoothing_text if self.tree is not None else ""
        self.viewer.note_var.set(smoothing)
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
        if cut is None or not 0 <= index < len(cut.frames):
            return
        path = cut.frames[index].path
        self._frame_path = path
        cache = self.cache
        self._work("frame", lambda: cache.frame(path), self._apply_frame)

    def _apply_frame(self, image: Image.Image) -> None:
        self.viewer.show_image(ImageTk.PhotoImage(image, master=self))

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
        self._row_widgets: list[_RowWidgets] = []
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
        self.ai_button = ttk.Button(top, text="Write with AI…", state="disabled")
        self.ai_button.pack(side="right")
        ttk.Label(host, textvariable=self.ai_reason_var, style="Dark.TLabel").grid(
            row=2, column=0, sticky="e"
        )
        self.rows_frame = ttk.Frame(host, style="Panel.TFrame")
        self.rows_frame.grid(row=3, column=0, sticky="ew")
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

    def add_row(self, prompt: str = "", negative: str = "", seed: str = "") -> None:
        if len(self._row_widgets) >= MAX_ROWS:
            return
        row = _RowWidgets(
            self.rows_frame, len(self._row_widgets) + 1, prompt, negative, seed, self.remove_row
        )
        self._row_widgets.append(row)
        self._refresh_rows()

    def remove_row(self, row: _RowWidgets) -> None:
        if len(self._row_widgets) <= 1:
            return
        self._row_widgets.remove(row)
        row.destroy()
        for number, remaining in enumerate(self._row_widgets, start=1):
            remaining.renumber(number)
        self._refresh_rows()

    def set_rows(self, prompts: list[str]) -> None:
        while len(self._row_widgets) > 1:
            self.remove_row(self._row_widgets[-1])
        self._row_widgets[0].prompt_var.set(prompts[0] if prompts else "")
        for prompt in prompts[1:]:
            self.add_row(prompt)

    def _refresh_rows(self) -> None:
        full = len(self._row_widgets) >= MAX_ROWS
        self.add_row_button.configure(state="disabled" if full else "normal")
        for row in self._row_widgets:
            row.remove_button.configure(
                state="normal" if len(self._row_widgets) > 1 else "disabled"
            )
        self._refresh_queue_label()

    def _refresh_queue_label(self) -> None:
        self.queue_button.configure(
            text=StoryboardTreeContract.queue_label(self.mode_var.get(), len(self._row_widgets))
        )

    def _continue_rows(self) -> tuple[ContinueRow, ...]:
        return tuple(
            ContinueRow(row.prompt_var.get(), row.negative_var.get(), row.seed_var.get())
            for row in self._row_widgets
        )

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
        allowed = False
        if self.target is None:
            self.continue_title_var.set("Continue")
        else:
            owner, handoff = self.target
            allowed = contract.continue_allowed(owner)[0]
            where = "the still image" if handoff is None else f"its frame {handoff + 1}"
            self.continue_title_var.set(f"Continue {contract.label(owner)} from {where}")
        state = "normal" if allowed and not self._busy else "disabled"
        self.preview_button.configure(state=state)
        self.queue_button.configure(state=state)
        self._sync_experimental()

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
        rows = self._continue_rows()
        errors = self.contract.validate_rows(rows)
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


class _RowWidgets:
    """One Continue row: positive, negative, seed and a remove button."""

    def __init__(
        self,
        parent: ttk.Frame,
        number: int,
        prompt: str,
        negative: str,
        seed: str,
        on_remove: Callable[[_RowWidgets], None],
    ) -> None:
        self.frame = ttk.Frame(parent, style="Panel.TFrame")
        self.frame.pack(fill="x", pady=1)
        self.prompt_var = tk.StringVar(value=prompt)
        self.negative_var = tk.StringVar(value=negative)
        self.seed_var = tk.StringVar(value=seed)
        self.number_label = ttk.Label(self.frame, text=str(number), width=2)
        self.number_label.pack(side="left")
        ttk.Entry(self.frame, textvariable=self.prompt_var, width=26).pack(side="left", padx=1)
        ttk.Entry(self.frame, textvariable=self.negative_var, width=18).pack(side="left", padx=1)
        ttk.Entry(self.frame, textvariable=self.seed_var, width=9).pack(side="left", padx=1)
        self.remove_button = ttk.Button(
            self.frame, text="✕", width=3, command=lambda: on_remove(self)
        )
        self.remove_button.pack(side="left")

    def renumber(self, number: int) -> None:
        self.number_label.configure(text=str(number))

    def destroy(self) -> None:
        self.frame.destroy()


class _NewStoryboardDialog(tk.Toplevel):
    """Start from a finished clip (job id) or a still image plus the workflow to use. Non-modal; the tab does the work."""

    def __init__(self, tab: StoryboardTabFrameV2) -> None:
        super().__init__(tab)
        self.title("New storyboard")
        self.transient(tab.winfo_toplevel())
        self._tab = tab
        self.source_var = tk.StringVar(value="clip")
        self.job_var = tk.StringVar()
        self.image_var = tk.StringVar()
        self.title_var = tk.StringVar(value="New storyboard")
        self.workflow_var = tk.StringVar(value=self._default_workflow())
        self.version_var = tk.StringVar()
        self.frames_var = tk.StringVar()
        body = ttk.Frame(self, padding=10)
        body.pack(fill="both", expand=True)
        ttk.Label(body, text="Title").grid(row=0, column=0, sticky="w")
        ttk.Entry(body, textvariable=self.title_var, width=44).grid(row=0, column=1, sticky="ew")
        ttk.Radiobutton(
            body,
            text="From a finished clip (job id from Recent outputs)",
            variable=self.source_var,
            value="clip",
        ).grid(row=1, column=0, columnspan=2, sticky="w")
        ttk.Entry(body, textvariable=self.job_var).grid(row=2, column=1, sticky="ew")
        ttk.Radiobutton(
            body, text="From a still image", variable=self.source_var, value="image"
        ).grid(row=3, column=0, columnspan=2, sticky="w")
        ttk.Entry(body, textvariable=self.image_var).grid(row=4, column=1, sticky="ew")
        ttk.Button(body, text="Browse…", command=self._browse).grid(row=4, column=0)
        for row, (label, var) in enumerate(
            (
                ("Workflow id", self.workflow_var),
                ("Version (optional)", self.version_var),
                ("Frames (optional)", self.frames_var),
            ),
            start=5,
        ):
            ttk.Label(body, text=label).grid(row=row, column=0, sticky="w")
            ttk.Entry(body, textvariable=var).grid(row=row, column=1, sticky="ew")
        buttons = ttk.Frame(body)
        buttons.grid(row=8, column=0, columnspan=2, sticky="e", pady=(8, 0))
        ttk.Button(buttons, text="Create", command=self.create).pack(side="right")
        ttk.Button(buttons, text="Cancel", command=self.destroy).pack(side="right", padx=4)
        body.columnconfigure(1, weight=1)

    def _default_workflow(self) -> str:
        window = self._tab.winfo_toplevel()
        variable = getattr(getattr(window, "video_workflow_tab", None), "workflow_var", None)
        try:
            return str(variable.get()) if variable is not None else ""
        except tk.TclError:
            return ""

    def _browse(self) -> None:
        from tkinter import filedialog

        chosen = filedialog.askopenfilename(parent=self, title="Choose the still image")
        if chosen:
            self.image_var.set(chosen)

    def create(self) -> None:
        title = self.title_var.get().strip() or "New storyboard"
        if self.source_var.get() == "clip":
            job_id = self.job_var.get().strip()
            if not job_id:
                self._tab._say("Enter the job id of a finished clip.")
                return
            self._tab.start_from_job(job_id)
        else:
            settings: dict[str, Any] = {"workflow_id": self.workflow_var.get().strip()}
            if self.version_var.get().strip():
                settings["workflow_version"] = self.version_var.get().strip()
            if self.frames_var.get().strip():
                settings["frame_count"] = self.frames_var.get().strip()
            image = self.image_var.get().strip()
            if not image:
                self._tab._say("Choose a still image.")
                return
            self._tab.start_from_image(image, settings, title)
        self.destroy()


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
