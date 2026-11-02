"""Tk rendering of the Video Workflow "Motion Library" browser (PR-VID-MOTION-LIB-353). Presentation only.

Every rule -- filtering, staleness, content visibility, what Use as Driving Video verifies -- lives in
``MotionLibrarySession``.  Hashing, FFprobe and frame decoding run on workers owned by the existing
``ThreadRegistry``; their results come back through ``TkUiDispatcher`` and are dropped when stale or after
the panel is destroyed.  Playback reuses the shared ``MediaInspector`` (its decoder and content-visibility
policy).  The panel builds no job, calls no backend and never queues anything: Use as Driving Video only
asks the tab to fill its own driving-video field.
"""

from __future__ import annotations

import base64
import tkinter as tk
from collections.abc import Callable, Mapping
from tkinter import filedialog, ttk
from typing import Any

from PIL import Image, ImageTk

from src.gui.theme_v2 import style_text_widget
from src.gui.ui_dispatcher import tk_dispatcher_for
from src.gui.view_contracts.motion_library_contract import (
    LibraryView,
    MotionLibraryPorts,
    MotionLibrarySession,
    visibility_subject,
)
from src.gui.view_contracts.video_experiment_contract import BackgroundWorkRunner
from src.gui.widgets.disclosure_section_v2 import DisclosureSection
from src.gui.widgets.flow_row_v2 import FlowRow
from src.gui.widgets.media_inspector import MediaInspector
from src.gui.widgets.responsive_wrap_v2 import bind_wraplength
from src.utils.os_shell import open_file, reveal_in_file_manager
from src.utils.thread_registry import get_thread_registry
from src.video.motion_library.handoff import HandoffPlan
from src.video.motion_library.models import (
    CAMERA_MOVEMENTS,
    FRAMINGS,
    INTENSITIES,
    LOCATOR_LINKED,
    LOCATOR_MANAGED,
    LOOP_SUITABILITIES,
    REVIEW_STATUSES,
    SOURCE_CATEGORIES,
    SOURCE_CATEGORY_LABELS,
    SUBJECT_KINDS,
    VIEWPOINTS,
    MotionAsset,
)
from src.video.motion_library.search import SearchQuery

_VIDEO_FILETYPES = [("Video files", "*.mp4 *.webm *.mov *.mkv"), ("All files", "*.*")]
_ANY = "Any"
_THUMB_EDGE = (56, 40)
_FULL_COLUMNS = ("name", "length", "source", "review", "file")
_COMPACT_COLUMNS = ("name", "length", "file")
_WIDE_PANEL_PX = 700
_MAX_CACHED_THUMBS = 400
_FILTER_DEBOUNCE_MS = 150
_INTRO = (
    "Keep motion-reference videos you own or have the right to use. Importing, searching and previewing "
    "never queue a job. Use as Driving Video fills the driving-video field; Prepare Motion Source and "
    "Preview still decide what is submitted."
)

# (key, label, choices) for the always-available filter row; choices are raw model values.
_FILTER_CHOICES: tuple[tuple[str, str, tuple[str, ...]], ...] = (
    ("source", "Source", SOURCE_CATEGORIES),
    ("subject_kind", "Subject", SUBJECT_KINDS),
    ("framing", "Framing", FRAMINGS),
    ("viewpoint", "Viewpoint", VIEWPOINTS),
    ("camera_movement", "Camera", CAMERA_MOVEMENTS),
    ("motion_intensity", "Intensity", INTENSITIES),
    ("loop", "Loop", ("loopable", "one_shot")),
    ("review", "Review", REVIEW_STATUSES),
)
# (field, label, kind, choices) for the annotation editor; kind: entry | combo | text | check.
_EDIT_FIELDS: tuple[tuple[str, str, str, tuple[str, ...]], ...] = (
    ("display_name", "Name", "entry", ()),
    ("tags", "Motion tags", "entry", ()),
    ("source_category", "Source", "combo", SOURCE_CATEGORIES),
    ("source_reference", "Source reference", "entry", ()),
    ("source_url", "Source URL (text only)", "entry", ()),
    ("subject_kind", "Subject", "combo", SUBJECT_KINDS),
    ("subject_count", "Subject count", "entry", ()),
    ("framing", "Framing", "combo", FRAMINGS),
    ("camera_movement", "Camera movement", "combo", CAMERA_MOVEMENTS),
    ("viewpoint", "Viewpoint", "combo", VIEWPOINTS),
    ("motion_intensity", "Intensity", "combo", INTENSITIES),
    ("motion_direction", "Direction", "entry", ()),
    ("start_pose", "Start pose", "entry", ()),
    ("end_pose", "End pose", "entry", ()),
    ("loop_suitability", "Loop", "combo", LOOP_SUITABILITIES),
    ("review_status", "Review", "combo", REVIEW_STATUSES),
    ("good_for_motion", "Good for motion driving", "check", ()),
    ("quality_notes", "Quality notes", "text", ()),
    ("provenance_notes", "Provenance notes", "text", ()),
    ("usage_terms", "Usage terms", "text", ()),
)


def _label_for(value: str) -> str:
    return SOURCE_CATEGORY_LABELS.get(value) or value.replace("_", " ").capitalize()


class WorkflowMotionLibraryPanel(ttk.LabelFrame):
    def __init__(
        self,
        master: tk.Misc,
        *,
        ports: MotionLibraryPorts,
        mode_provider: Callable[[], str] = lambda: "nsfw",
        selected_workflow: Callable[[], tuple[str, str]] = lambda: ("", ""),
        on_handoff: Callable[[HandoffPlan], None] | None = None,
        on_convert: Callable[[], None] | None = None,
        on_preview_conditioning: Callable[[Any], None] | None = None,
        decode: Any = None,
        runner: BackgroundWorkRunner | None = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(
            master, text="Motion Library", style="Dark.TLabelframe", padding=8, **kwargs
        )
        self._closed = False
        self._on_convert = on_convert
        self._on_preview_conditioning = on_preview_conditioning
        self._runner = runner
        self._media_decode = decode
        self._photos: list[tk.PhotoImage] = []
        self._thumb_cache: dict[str, ImageTk.PhotoImage] = {}
        self._row_ids: tuple[str, ...] = ()
        self._columns: tuple[str, ...] = _COMPACT_COLUMNS
        self._previewed = ""
        self._editing = ""
        self._filter_job: str | None = None
        self.status_var = tk.StringVar(self, value="")
        self.search_var = tk.StringVar(self)
        self.copy_var = tk.BooleanVar(self, value=False)
        self.import_category_var = tk.StringVar(self, value=_label_for(SOURCE_CATEGORIES[-1]))
        self.import_tags_var = tk.StringVar(self)
        self.filter_vars: dict[str, tk.StringVar] = {
            k: tk.StringVar(self, value=_ANY) for k, _l, _c in _FILTER_CHOICES
        }
        self.min_frames_var = tk.StringVar(self)
        self.max_frames_var = tk.StringVar(self)
        self.min_seconds_var = tk.StringVar(self)
        self.max_seconds_var = tk.StringVar(self)
        self.reviewed_only_var = tk.BooleanVar(self, value=False)
        self.edit_vars: dict[str, tk.StringVar | tk.BooleanVar] = {}
        self.edit_texts: dict[str, tk.Text] = {}
        self.columnconfigure(0, weight=1)

        self._build_header()
        self._build_filters()
        self._build_list()
        self._build_detail()
        self._build_editor()

        self.session = MotionLibrarySession(
            ports=ports,
            runner=self._work_runner(),
            mode_provider=mode_provider,
            selected_workflow=selected_workflow,
            on_change=self._render,
            on_handoff=on_handoff,
        )
        self.bind("<Destroy>", self._on_destroy, add="+")
        self.bind("<Configure>", self._on_resize, add="+")
        self._render()

    # ------------------------------------------------------------------ build

    def _build_header(self) -> None:
        intro = ttk.Label(self, text=_INTRO, style="Muted.TLabel", justify="left")
        intro.grid(row=0, column=0, sticky="ew", pady=(0, 6))
        bind_wraplength(intro)
        bar = FlowRow(self, style="Panel.TFrame")
        bar.grid(row=1, column=0, sticky="ew", pady=(0, 6))
        self.choose_button = ttk.Button(
            bar, text="Choose library folder...", style="Dark.TButton", command=self._on_choose_root
        )
        self.import_file_button = ttk.Button(
            bar, text="Import video...", style="Dark.TButton", command=self._on_import_file
        )
        self.import_folder_button = ttk.Button(
            bar, text="Import folder...", style="Dark.TButton", command=self._on_import_folder
        )
        self.convert_button = ttk.Button(
            bar, text="Convert Motion...", style="Dark.TButton", command=self._on_convert_motion
        )
        self.refresh_button = ttk.Button(
            bar, text="Refresh", style="Dark.TButton", command=self.request_refresh
        )
        self.copy_check = ttk.Checkbutton(
            bar, text="Copy into library", variable=self.copy_var, style="Dark.TCheckbutton"
        )
        buttons = (
            self.choose_button,
            self.import_file_button,
            self.import_folder_button,
            self.convert_button,
            self.refresh_button,
            self.copy_check,
        )
        for widget in buttons:
            bar.add(widget)
        import_options = FlowRow(self, style="Panel.TFrame")
        import_options.grid(row=2, column=0, sticky="ew", pady=(0, 6))
        import_options.add(ttk.Label(import_options, text="Import as", style="Dark.TLabel"))
        self.import_category_combo = ttk.Combobox(
            import_options, state="readonly", width=18, textvariable=self.import_category_var,
            values=[_label_for(c) for c in SOURCE_CATEGORIES if c != "stablenew_generated"],
        )  # fmt: skip
        import_options.add(self.import_category_combo)
        import_options.add(ttk.Label(import_options, text="Tags", style="Dark.TLabel"))
        import_options.add(
            ttk.Entry(
                import_options, textvariable=self.import_tags_var, width=24, style="Dark.TEntry"
            )
        )
        self.status_label = ttk.Label(
            self, textvariable=self.status_var, style="Muted.TLabel", justify="left"
        )
        self.status_label.grid(row=3, column=0, sticky="ew", pady=(0, 6))
        bind_wraplength(self.status_label)

    def _build_filters(self) -> None:
        search_row = ttk.Frame(self, style="Panel.TFrame")
        search_row.grid(row=4, column=0, sticky="ew", pady=(0, 4))
        search_row.columnconfigure(1, weight=1)
        ttk.Label(search_row, text="Search", style="Dark.TLabel").grid(row=0, column=0, padx=(0, 6))
        self.search_entry = ttk.Entry(search_row, textvariable=self.search_var, style="Dark.TEntry")
        self.search_entry.grid(row=0, column=1, sticky="ew")
        self.filters = DisclosureSection(self, title="Filters")
        self.filters.grid(row=5, column=0, sticky="ew", pady=(0, 6))
        body = self.filters.body
        body.columnconfigure(0, weight=1)
        self.filter_combos: dict[str, ttk.Combobox] = {}
        choice_row = FlowRow(body, style="Panel.TFrame")
        choice_row.grid(row=0, column=0, sticky="ew", pady=(0, 4))
        for key, label, choices in _FILTER_CHOICES:
            cell = ttk.Frame(choice_row, style="Panel.TFrame")
            ttk.Label(cell, text=label, style="Dark.TLabel", width=10).grid(
                row=0, column=0, sticky="w"
            )
            combo = ttk.Combobox(
                cell, state="readonly", width=16, textvariable=self.filter_vars[key],
                values=[_ANY, *[_label_for(c) for c in choices]],
            )  # fmt: skip
            combo.grid(row=0, column=1, sticky="w")
            self.filter_combos[key] = combo
            choice_row.add(cell)
        ranges = FlowRow(body, style="Panel.TFrame")
        ranges.grid(row=1, column=0, sticky="ew", pady=(0, 4))
        for label, var in (
            ("Min s", self.min_seconds_var),
            ("Max s", self.max_seconds_var),
            ("Min frames", self.min_frames_var),
            ("Max frames", self.max_frames_var),
        ):
            pair = ttk.Frame(ranges, style="Panel.TFrame")
            ttk.Label(pair, text=label, style="Dark.TLabel").grid(row=0, column=0, padx=(0, 4))
            ttk.Entry(pair, textvariable=var, width=7, style="Dark.TEntry").grid(row=0, column=1)
            ranges.add(pair)
        ttk.Checkbutton(
            body, text="Marked good for motion driving only", variable=self.reviewed_only_var, style="Dark.TCheckbutton"
        ).grid(row=2, column=0, sticky="w")  # fmt: skip
        watched = [
            self.search_var,
            self.min_frames_var,
            self.max_frames_var,
            self.min_seconds_var,
            self.max_seconds_var,
            self.reviewed_only_var,
        ]
        for variable in (*watched, *self.filter_vars.values()):
            variable.trace_add("write", lambda *_a: self._schedule_filter())

    def _build_list(self) -> None:
        style = ttk.Style(self)
        style.configure("MotionLib.Treeview", rowheight=_THUMB_EDGE[1] + 6)
        frame = ttk.Frame(self, style="Panel.TFrame")
        frame.grid(row=6, column=0, sticky="nsew", pady=(0, 6))
        frame.columnconfigure(0, weight=1)
        self.tree = ttk.Treeview(
            frame, columns=("name", "length", "source", "review", "file"), show="tree headings",
            height=5, selectmode="browse", style="MotionLib.Treeview",
        )  # fmt: skip
        self.tree.heading("#0", text="")
        self.tree.column("#0", width=_THUMB_EDGE[0] + 12, stretch=False)
        for column, heading, width, stretch in (
            ("name", "Motion", 130, True), ("length", "Length", 96, False), ("source", "Source", 120, False),
            ("review", "Review", 80, False), ("file", "File", 70, False),
        ):  # fmt: skip
            self.tree.heading(column, text=heading)
            self.tree.column(column, width=width, stretch=stretch)
        self.tree.configure(displaycolumns=_COMPACT_COLUMNS)
        scroll = ttk.Scrollbar(frame, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=scroll.set)
        self.tree.grid(row=0, column=0, sticky="nsew")
        scroll.grid(row=0, column=1, sticky="ns")
        self.tree.bind("<<TreeviewSelect>>", self._on_select)
        self.tree.bind("<Return>", self._on_use_key)
        self.tree.bind("<Double-Button-1>", lambda _e: self._on_use())

    def _build_detail(self) -> None:
        detail = ttk.Frame(self, style="Panel.TFrame")
        detail.grid(row=7, column=0, sticky="ew")
        detail.columnconfigure(0, weight=1)
        self.preview = MediaInspector(
            detail, decode=self._media_decode_arg(), edge=256, scale=1, allow_original=False
        )
        self.preview.grid(row=0, column=0, sticky="w", pady=(0, 6))
        self.frames_frame = ttk.Frame(detail, style="Panel.TFrame")
        self.frames_frame.grid(row=1, column=0, sticky="w", pady=(0, 6))
        self.detail_text = tk.Text(detail, height=9, wrap="word", state="disabled", takefocus=True)
        style_text_widget(self.detail_text, elevated=True)
        self.detail_text.grid(row=2, column=0, sticky="ew", pady=(0, 6))
        actions = FlowRow(detail, style="Panel.TFrame")
        actions.grid(row=3, column=0, sticky="ew")
        self.use_button = ttk.Button(
            actions,
            text="Use as Driving Video",
            style="Dark.TButton",
            command=self._on_use,
            state="disabled",
        )
        self.relink_button = ttk.Button(
            actions,
            text="Relink file...",
            style="Dark.TButton",
            command=self._on_relink,
            state="disabled",
        )
        self.condition_button = ttk.Button(
            actions,
            text="Preview Conditioning...",
            style="Dark.TButton",
            command=self._on_preview_condition,
            state="disabled",
        )
        self.open_button = ttk.Button(
            actions, text="Open", style="Dark.TButton", command=self._on_open, state="disabled"
        )
        self.reveal_button = ttk.Button(
            actions, text="Reveal", style="Dark.TButton", command=self._on_reveal, state="disabled"
        )
        for button in (
            self.use_button,
            self.condition_button,
            self.relink_button,
            self.open_button,
            self.reveal_button,
        ):
            actions.add(button)

    def _media_decode_arg(self) -> Any:
        return getattr(self, "_media_decode", None)

    def _build_editor(self) -> None:
        self.editor = DisclosureSection(self, title="Edit details")
        self.editor.grid(row=8, column=0, sticky="ew", pady=(6, 0))
        body = self.editor.body
        body.columnconfigure(1, weight=1)
        for row, (key, label, kind, choices) in enumerate(_EDIT_FIELDS):
            ttk.Label(body, text=label, style="Dark.TLabel").grid(
                row=row, column=0, sticky="nw", padx=(0, 6), pady=(0, 4)
            )
            if kind == "check":
                var: tk.StringVar | tk.BooleanVar = tk.BooleanVar(self, value=False)
                ttk.Checkbutton(body, variable=var, style="Dark.TCheckbutton").grid(
                    row=row, column=1, sticky="w"
                )
            elif kind == "combo":
                var = tk.StringVar(self)
                ttk.Combobox(
                    body, state="readonly", textvariable=var, values=list(choices), width=22
                ).grid(row=row, column=1, sticky="w", pady=(0, 4))
            elif kind == "text":
                var = tk.StringVar(self)
                text = tk.Text(body, height=3, wrap="word")
                style_text_widget(text, elevated=True)
                text.grid(row=row, column=1, sticky="ew", pady=(0, 4))
                self.edit_texts[key] = text
            else:
                var = tk.StringVar(self)
                ttk.Entry(body, textvariable=var, style="Dark.TEntry").grid(
                    row=row, column=1, sticky="ew", pady=(0, 4)
                )
            self.edit_vars[key] = var
        self.save_button = ttk.Button(
            body, text="Save details", style="Dark.TButton", command=self._on_save, state="disabled"
        )
        self.save_button.grid(row=len(_EDIT_FIELDS), column=1, sticky="w")

    # ------------------------------------------------------------------ background work

    def _work_runner(self) -> BackgroundWorkRunner:
        if self._runner is None:
            dispatcher = tk_dispatcher_for(self)
            self._runner = BackgroundWorkRunner(
                spawn=lambda name, target: get_thread_registry().spawn(
                    target=target,
                    name=name,
                    daemon=False,
                    purpose="Read or verify Motion Library files without blocking Tk",
                ),
                dispatch=lambda fn: dispatcher.invoke(lambda: self._deliver(fn)),
            )
        return self._runner

    def _deliver(self, finish: Callable[[], None]) -> None:
        if self._closed:
            return
        try:
            if self.winfo_exists():
                finish()
        except tk.TclError:
            pass  # the widget tree is going away

    # ------------------------------------------------------------------ public

    def request_refresh(self) -> None:
        if not self._closed:
            self.session.refresh()

    def on_content_visibility_mode_changed(self, mode: str | None = None) -> None:
        if not self._closed:
            self._previewed = ""  # re-evaluate the preview under the new policy
            self._render()

    # ------------------------------------------------------------------ filters

    def _schedule_filter(self) -> None:
        if self._closed:
            return
        if self._filter_job is not None:
            try:
                self.after_cancel(self._filter_job)
            except tk.TclError:
                pass
        self._filter_job = self.after(_FILTER_DEBOUNCE_MS, self._apply_filter)

    def _filter_value(self, key: str, choices: tuple[str, ...]) -> str:
        shown = self.filter_vars[key].get()
        for choice in choices:
            if _label_for(choice) == shown:
                return choice
        return ""

    @staticmethod
    def _number(text: str, cast: Callable[[str], Any]) -> Any:
        try:
            value = cast(text.strip())
        except (TypeError, ValueError):
            return None
        return value if value >= 0 else None

    def build_query(self) -> SearchQuery:
        picks: dict[str, Any] = {
            key: self._filter_value(key, choices) for key, _label, choices in _FILTER_CHOICES
        }
        source = picks.pop("source")
        return SearchQuery(
            text=self.search_var.get(),
            source_categories=(source,) if source else (),
            min_seconds=self._number(self.min_seconds_var.get(), float),
            max_seconds=self._number(self.max_seconds_var.get(), float),
            min_frames=self._number(self.min_frames_var.get(), int),
            max_frames=self._number(self.max_frames_var.get(), int),
            good_for_motion_only=bool(self.reviewed_only_var.get()),
            **picks,
        )

    def _apply_filter(self) -> None:
        self._filter_job = None
        if not self._closed:
            self.session.set_query(self.build_query())

    # ------------------------------------------------------------------ rendering

    def _thumb(self, path: str) -> ImageTk.PhotoImage | None:
        if not path:
            return None
        cached = self._thumb_cache.get(path)
        if cached is not None:
            return cached
        try:
            with Image.open(path) as image:
                image.thumbnail(_THUMB_EDGE)
                photo = ImageTk.PhotoImage(image.copy())
        except (OSError, ValueError):
            return None
        if len(self._thumb_cache) >= _MAX_CACHED_THUMBS:
            self._thumb_cache.clear()
        self._thumb_cache[path] = photo
        return photo

    def _render(self) -> None:
        if self._closed:
            return
        try:
            view = self.session.view()
            self.status_var.set(view.status)
            self._render_buttons(view)
            self._render_rows(view)
            self._render_detail(view)
        except tk.TclError:
            pass

    def _render_buttons(self, view: LibraryView) -> None:
        can = "normal" if view.can_import else "disabled"
        for button in (self.import_file_button, self.import_folder_button, self.convert_button):
            button.configure(state=can)
        self.refresh_button.configure(state="disabled" if view.busy else "normal")
        self.choose_button.configure(state="disabled" if view.busy else "normal")

    def _render_rows(self, view: LibraryView) -> None:
        wanted = tuple(row.asset_id for row in view.rows)
        if wanted != self._row_ids:
            self._row_ids = wanted
            self.tree.delete(*self.tree.get_children())
            for row in view.rows:
                photo = self._thumb(row.thumbnail_path)
                self.tree.insert(
                    "", "end", iid=row.asset_id, image=photo or "",
                    values=(row.name, row.length_text, row.source_label, row.review_label, row.file_label),
                )  # fmt: skip
        if (
            view.selected_id
            and self.tree.exists(view.selected_id)
            and self.tree.selection() != (view.selected_id,)
        ):
            self.tree.selection_set(view.selected_id)
        extra = (
            f" ({view.hidden_by_visibility} hidden by the content filter)"
            if view.hidden_by_visibility
            else ""
        )
        if view.configured:
            self.status_var.set(f"{view.status}  Showing {len(view.rows)} of {view.total}.{extra}")
        if view.issues:
            self.status_var.set(self.status_var.get() + "\n" + "\n".join(view.issues[:3]))

    def _render_detail(self, view: LibraryView) -> None:
        detail = view.detail
        for child in self.frames_frame.winfo_children():
            child.destroy()
        self._photos.clear()
        self.detail_text.configure(state="normal")
        self.detail_text.delete("1.0", "end")
        if detail is None:
            self.preview.stop()
            self._previewed = ""
            self.detail_text.insert("1.0", "Select a clip to preview it.")
            self.detail_text.configure(state="disabled")
            for button in (
                self.use_button,
                self.condition_button,
                self.relink_button,
                self.open_button,
                self.reveal_button,
                self.save_button,
            ):
                button.configure(state="disabled")
            self._editing = ""
            return
        if detail.media_path != self._previewed:
            self._previewed = detail.media_path
            if detail.media_path:
                self.preview.set_media(
                    detail.media_path, "video", subject=visibility_subject(detail.asset)
                )
            else:
                self.preview.stop()
        for index, frame in enumerate(detail.frames):
            cell = ttk.Frame(self.frames_frame, style="Panel.TFrame")
            cell.grid(row=0, column=index, padx=(0, 6))
            photo = tk.PhotoImage(data=base64.b64encode(frame.png_bytes).decode("ascii"))
            self._photos.append(photo)
            ttk.Label(cell, image=photo).grid(row=0, column=0)
            ttk.Label(cell, text=frame.caption, style="Muted.TLabel").grid(row=1, column=0)
        lines: list[str] = []
        if detail.file_state in {"missing", "changed", "unreadable"}:
            lines.append(f"!! {detail.file_message}")
        if detail.preview_loading:
            lines.append("Reading the clip...")
        lines.extend(detail.fact_lines)
        lines.append("")
        lines.extend(detail.provenance_lines)
        if detail.origin_lines:
            lines.append("")
            lines.extend(detail.origin_lines)
        lines.extend(f"Preview: {issue}" for issue in detail.preview_issues)
        self.detail_text.insert("1.0", "\n".join(lines))
        self.detail_text.configure(state="disabled")
        self.use_button.configure(state="normal" if detail.can_use else "disabled")
        self.condition_button.configure(
            state="normal" if detail.can_use and self._on_preview_conditioning else "disabled"
        )
        self.relink_button.configure(state="normal" if detail.can_relink else "disabled")
        playable = "normal" if detail.media_path else "disabled"
        self.open_button.configure(state=playable)
        self.reveal_button.configure(state=playable)
        self.save_button.configure(state="normal")
        if detail.asset.asset_id != self._editing:
            self._editing = detail.asset.asset_id
            self._load_editor(detail.asset)

    # ------------------------------------------------------------------ editor

    def _load_editor(self, asset: MotionAsset) -> None:
        data = asset.to_dict()
        for key, var in self.edit_vars.items():
            value = data.get(key)
            if isinstance(var, tk.BooleanVar):
                var.set(bool(value))
            elif key == "tags":
                var.set(", ".join(asset.tags))
            else:
                var.set("" if value is None else str(value))
        for key, text in self.edit_texts.items():
            text.delete("1.0", "end")
            text.insert("1.0", str(data.get(key) or ""))

    def _collect_edits(self) -> dict[str, Any]:
        changes: dict[str, Any] = {}
        for key, var in self.edit_vars.items():
            if key in self.edit_texts:
                changes[key] = self.edit_texts[key].get("1.0", "end").strip()
            elif isinstance(var, tk.BooleanVar):
                changes[key] = bool(var.get())
            elif key == "subject_count":
                text = str(var.get()).strip()
                changes[key] = int(text) if text.isdigit() else None
            else:
                changes[key] = str(var.get())
        return changes

    def _on_save(self) -> None:
        if self._editing:
            self.session.annotate(self._editing, self._collect_edits())

    # ------------------------------------------------------------------ actions

    def _import_annotations(self) -> dict[str, Any]:
        category = next(
            (c for c in SOURCE_CATEGORIES if _label_for(c) == self.import_category_var.get()),
            "other",
        )
        return {"source_category": category, "tags": self.import_tags_var.get()}

    def _mode(self) -> str:
        return LOCATOR_MANAGED if self.copy_var.get() else LOCATOR_LINKED

    def _on_choose_root(self) -> None:
        view = self.session.view()
        folder = filedialog.askdirectory(
            title="Choose the Motion Library folder (outside the repository)",
            initialdir=view.root or view.suggested_root or None,
            mustexist=False,
        )
        if folder:
            self.session.configure_root(folder)

    def _on_import_file(self) -> None:
        path = filedialog.askopenfilename(title="Import a motion video", filetypes=_VIDEO_FILETYPES)
        if path:
            self.session.import_file(path, self._mode(), self._import_annotations())

    def _on_convert_motion(self) -> None:
        if self._on_convert is not None:
            self._on_convert()

    def focus_asset(self, asset_id: str) -> None:
        """Refresh, then select a clip that was just added elsewhere (for example by Convert Motion)."""

        if not self._closed:
            self.session.refresh_and_select(asset_id)

    def _on_import_folder(self) -> None:
        folder = filedialog.askdirectory(
            title="Import the videos in a folder (sub-folders are not entered)"
        )
        if folder:
            self.session.import_folder(folder, self._mode(), self._import_annotations())

    def _on_use_key(self, _event: Any = None) -> str:
        self._on_use()
        return "break"

    def _on_resize(self, event: Any) -> None:
        if event.widget is not self or self._closed:
            return
        wanted = _FULL_COLUMNS if event.width >= _WIDE_PANEL_PX else _COMPACT_COLUMNS
        if wanted != self._columns:
            self._columns = wanted
            self.tree.configure(displaycolumns=wanted)

    def _on_select(self, _event: Any = None) -> None:
        chosen = self.tree.selection()
        if chosen and chosen[0] != self.session.selected_id:
            self.session.select(chosen[0])

    def _on_use(self) -> None:
        self.session.use_as_driving()

    def _on_preview_condition(self) -> None:
        """Hand the verified, selected clip to the owner of the preview window; nothing is queued or changed."""

        detail = self.session.view().detail
        if detail is not None and detail.can_use and self._on_preview_conditioning is not None:
            self._on_preview_conditioning(detail)

    def _on_relink(self) -> None:
        detail = self.session.view().detail
        if detail is None:
            return
        path = filedialog.askopenfilename(
            title="Choose the file that has the same bytes as the original clip",
            filetypes=_VIDEO_FILETYPES,
        )
        if path:
            self.session.relink(detail.asset.asset_id, path)

    def _on_open(self) -> None:
        detail = self.session.view().detail
        if detail is not None and detail.media_path:
            result = open_file(detail.media_path)
            if not result.ok:
                self.status_var.set(result.message)

    def _on_reveal(self) -> None:
        detail = self.session.view().detail
        if detail is not None and detail.media_path:
            result = reveal_in_file_manager(detail.media_path)
            if not result.ok:
                self.status_var.set(result.message)

    def _on_destroy(self, event: Any = None) -> None:
        if event is None or event.widget is self:
            self._closed = True
            if self._filter_job is not None:
                try:
                    self.after_cancel(self._filter_job)
                except tk.TclError:
                    pass
            self.session.close()


def prompt_add_details(parent: tk.Misc, default_label: str) -> Mapping[str, Any] | None:
    """Ask for the operator-judged facts about a generated clip; ``None`` when cancelled."""

    dialog = tk.Toplevel(parent)
    dialog.title("Add to Motion Library")
    dialog.transient(parent.winfo_toplevel())
    label_var = tk.StringVar(dialog, value=default_label)
    achieved_var = tk.StringVar(dialog, value="Not judged")
    good_var = tk.BooleanVar(dialog, value=True)
    copy_var = tk.BooleanVar(dialog, value=False)
    result: dict[str, Any] = {}
    body = ttk.Frame(dialog, padding=10)
    body.grid(row=0, column=0, sticky="nsew")
    body.columnconfigure(1, weight=1)
    ttk.Label(body, text="Motion label").grid(row=0, column=0, sticky="w", padx=(0, 6), pady=(0, 6))
    ttk.Entry(body, textvariable=label_var, width=36).grid(
        row=0, column=1, sticky="ew", pady=(0, 6)
    )
    ttk.Label(body, text="Requested motion achieved").grid(
        row=1, column=0, sticky="w", padx=(0, 6), pady=(0, 6)
    )
    ttk.Combobox(
        body,
        state="readonly",
        textvariable=achieved_var,
        values=["Not judged", "Yes", "No"],
        width=14,
    ).grid(row=1, column=1, sticky="w", pady=(0, 6))
    ttk.Checkbutton(body, text="Good for motion driving", variable=good_var).grid(
        row=2, column=0, columnspan=2, sticky="w"
    )
    ttk.Checkbutton(body, text="Copy the clip into the library folder", variable=copy_var).grid(
        row=3, column=0, columnspan=2, sticky="w", pady=(0, 6)
    )
    ttk.Label(body, text="Known artifacts").grid(row=4, column=0, sticky="nw", padx=(0, 6))
    artifacts = tk.Text(body, height=2, width=36, wrap="word")
    artifacts.grid(row=4, column=1, sticky="ew", pady=(0, 6))
    ttk.Label(body, text="Reuse conditions").grid(row=5, column=0, sticky="nw", padx=(0, 6))
    reuse = tk.Text(body, height=2, width=36, wrap="word")
    reuse.grid(row=5, column=1, sticky="ew", pady=(0, 6))

    def accept() -> None:
        judged = achieved_var.get()
        result.update(
            motion_label=label_var.get().strip(),
            motion_achieved=True if judged == "Yes" else False if judged == "No" else None,
            good_for_motion=bool(good_var.get()),
            mode=LOCATOR_MANAGED if copy_var.get() else LOCATOR_LINKED,
            known_artifacts=artifacts.get("1.0", "end").strip(),
            reuse_conditions=reuse.get("1.0", "end").strip(),
        )
        dialog.destroy()

    buttons = ttk.Frame(body)
    buttons.grid(row=6, column=0, columnspan=2, sticky="e")
    ttk.Button(buttons, text="Add", command=accept).grid(row=0, column=0, padx=(0, 6))
    ttk.Button(buttons, text="Cancel", command=dialog.destroy).grid(row=0, column=1)
    dialog.bind("<Escape>", lambda _e: dialog.destroy())
    dialog.grab_set()
    dialog.wait_window()
    return dict(result) if result else None


__all__ = ["WorkflowMotionLibraryPanel", "prompt_add_details"]
