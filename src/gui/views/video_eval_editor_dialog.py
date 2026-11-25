"""Graphical authoring of video evaluation suite intent."""

from __future__ import annotations

import tkinter as tk
from collections.abc import Callable
from copy import deepcopy
from functools import partial
from pathlib import Path
from tkinter import filedialog, messagebox, ttk
from tkinter.scrolledtext import ScrolledText
from typing import Any

from src.gui.theme_v2 import (
    DARK_COMBOBOX_STYLE,
    PRIMARY_BUTTON_STYLE,
    style_listbox_widget,
    style_text_widget,
)
from src.gui.view_contracts.video_experiment_contract import BackgroundWorkRunner, WorkOutcome
from src.gui.views.video_eval_editor_motion import MotionEditorMixin
from src.gui.widgets.responsive_wrap_v2 import bind_wraplength
from src.gui.widgets.scrollable_frame_v2 import ScrollableFrame
from src.state.workspace_paths import workspace_paths
from src.video.video_eval_authoring import (
    EvalSuiteDraft,
    EvalWorkflowCatalog,
    bind_source,
    publish_validated_suite,
    validate_draft,
)
from src.video.video_eval_motion import CASE_OWNED_CONTROLS
from src.video.video_eval_suite import ARM_BACKEND_SVD, ARM_BACKEND_WORKFLOW, MAX_EVAL_JOBS
from src.video.video_workflow_intent import form_visibility
from src.video.workflow_controls import operator_controls

EXAMPLES = workspace_paths.root / "docs" / "runbooks" / "examples"
THREE_ENGINES = EXAMPLES / "video_eval_three_engines.suite.json"
IMAGE_FILES = [("Images", "*.png *.jpg *.jpeg *.webp *.bmp *.tif *.tiff"), ("All files", "*.*")]
JSON_FILES = [("Eval suites", "*.json"), ("All files", "*.*")]
_BACKENDS = {"Video Workflow": ARM_BACKEND_WORKFLOW, "Native SVD": ARM_BACKEND_SVD}


def _whole_or_text(value: str) -> int | str:
    try:
        return int(value)
    except ValueError:
        return value


def _row_label(item: dict[str, Any], kind: str, index: int) -> str:
    identifier = item.get(f"{kind}_id") or f"Unnamed {kind} {index + 1}"
    if kind == "case":
        image = str(item.get("image") or "")
        source = Path(image).name if image else "Choose image"
        clip = (
            "sequence"
            if item.get("segments") is not None
            else "driving motion"
            if item.get("motion") is not None
            else "clip"
        )
        return f"{identifier} · {source} · {clip}"
    return f"{identifier} · {item.get('label') or item.get('backend') or 'Choose backend'}"


class VideoEvalEditorDialog(MotionEditorMixin, tk.Toplevel):
    def __init__(
        self,
        parent: tk.Misc,
        *,
        plan_root: Path,
        initial_path: Path | None,
        runner: BackgroundWorkRunner,
        on_saved: Callable[[Path, bool], None],
        on_close: Callable[[], None],
        catalog: EvalWorkflowCatalog | None = None,
        ask_open: Callable[..., str] = filedialog.askopenfilename,
        confirm_discard: Callable[..., bool] = messagebox.askyesno,
    ) -> None:
        super().__init__(parent)
        self.title("Create / Edit Evaluation Suite")
        self.transient(parent.winfo_toplevel())
        self.geometry(
            f"{min(900, self.winfo_screenwidth() - 90)}x{min(760, self.winfo_screenheight() - 120)}"
        )
        self.minsize(570, 410)
        self.plan_root = plan_root
        self.draft = EvalSuiteDraft.new()
        self._catalog = catalog
        self._runner = runner
        self._on_saved = on_saved
        self._on_close = on_close
        self._ask_open = ask_open
        self._confirm_discard = confirm_discard
        self._closed = False
        self._busy = False
        self._saving = False
        self._dirty = False
        self.indices = {"case": 0, "arm": 0}
        self.status = tk.StringVar(self)
        self.count = tk.StringVar(self)

        self.columnconfigure(0, weight=1)
        self.rowconfigure(2, weight=1)
        top = ttk.Frame(self, padding=(12, 10, 12, 4))
        top.grid(row=0, column=0, sticky="ew")
        self._button(top, "New", lambda: self._load(None))
        self._button(top, "Three-engine template", lambda: self._load(THREE_ENGINES))
        self._button(top, "Open JSON / template…", self._open)
        self.source_label = ttk.Label(self, padding=(12, 0))
        self.source_label.grid(row=1, column=0, sticky="ew")
        bind_wraplength(self.source_label)
        self.tabs = ttk.Notebook(self)
        self.tabs.grid(row=2, column=0, sticky="nsew", padx=12, pady=(6, 0))
        suite = ScrollableFrame(self.tabs)
        suite.inner.columnconfigure(1, weight=1)
        self.suite_form = suite.inner
        self.tabs.add(suite, text="Suite")
        self.lists: dict[str, tk.Listbox] = {}
        self.details: dict[str, ttk.Frame] = {}
        for kind in ("case", "arm"):
            self._build_list_tab(kind)

        footer = ttk.Frame(self, padding=(12, 8))
        footer.grid(row=3, column=0, sticky="ew")
        self.results = ScrolledText(footer, height=6, wrap="word", state="disabled", takefocus=True)
        style_text_widget(self.results)
        self.status_label = ttk.Label(footer, textvariable=self.status)
        self.status_label.pack(fill="x")
        ttk.Label(footer, textvariable=self.count).pack(fill="x", pady=(0, 4))
        actions = ttk.Frame(footer)
        actions.pack(fill="x")
        self._button(actions, "Validate", lambda: self._validate(save=False))
        self.save_button = self._button(
            actions, "Save as New Version", lambda: self._validate(save=True)
        )
        self.preview_button = self._button(
            actions, "Save & Preview…", lambda: self._validate(save=True, preview=True)
        )
        self.preview_button.configure(style=PRIMARY_BUTTON_STYLE)
        self.close_button = ttk.Button(actions, text="Close", command=self._request_close)
        self.close_button.pack(side="right")
        self.protocol("WM_DELETE_WINDOW", self._request_close)
        self.bind("<Escape>", lambda _event: self._request_close())
        self.bind("<Destroy>", self._destroyed, add="+")
        self._render()
        if initial_path is not None or catalog is None:
            self._load(initial_path)

    def _button(self, parent: ttk.Frame, label: str, command: Callable[[], None]) -> ttk.Button:
        button = ttk.Button(parent, text=label, command=lambda: self._when_idle(command))
        button.pack(side="left", padx=(0, 5))
        return button

    def _when_idle(self, command: Callable[[], None]) -> None:
        if not self._busy and not self._closed:
            command()

    def _build_list_tab(self, kind: str) -> None:
        tab = ttk.Frame(self.tabs, padding=6)
        tab.columnconfigure(1, weight=1)
        tab.rowconfigure(0, weight=1)
        listing = ttk.Frame(tab)
        listing.grid(row=0, column=0, sticky="nsew", padx=(0, 8))
        listing.columnconfigure(0, weight=1)
        listing.rowconfigure(0, weight=1)
        entries = tk.Listbox(listing, width=27, exportselection=False)
        style_listbox_widget(entries)
        scroll = ttk.Scrollbar(listing, command=entries.yview)
        entries.configure(yscrollcommand=scroll.set)
        entries.grid(row=0, column=0, sticky="nsew")
        scroll.grid(row=0, column=1, sticky="ns")
        entries.bind("<<ListboxSelect>>", lambda _event: self._select(kind))
        buttons = ttk.Frame(listing)
        buttons.grid(row=1, column=0, columnspan=2, sticky="ew", pady=(4, 0))
        self._button(buttons, "Add", lambda: self._add(kind))
        if kind == "arm":
            self._button(buttons, "Duplicate", lambda: self._add(kind, duplicate=True))
        self._button(buttons, "Remove", lambda: self._remove(kind))
        detail = ScrollableFrame(tab)
        detail.grid(row=0, column=1, sticky="nsew")
        detail.inner.columnconfigure(1, weight=1)
        self.tabs.add(tab, text=f"{kind.title()}s")
        self.lists[kind] = entries
        self.details[kind] = detail.inner

    def _items(self, kind: str) -> list[dict[str, Any]]:
        return self.draft.cases if kind == "case" else self.draft.arms

    def _selected(self, kind: str) -> dict[str, Any] | None:
        items = self._items(kind)
        idx = self.indices[kind]
        return items[idx] if 0 <= idx < len(items) else None

    def _select(self, kind: str) -> None:
        indices = self.lists[kind].curselection()  # type: ignore[no-untyped-call]
        if indices and not self._busy and self.indices[kind] != indices[0]:
            self.indices[kind] = indices[0]
            self._render_detail(kind)

    def _render_list(self, kind: str) -> None:
        widget = self.lists[kind]
        widget.delete(0, "end")
        for index, record in enumerate(self._items(kind)):
            widget.insert("end", _row_label(record, kind, index))
        if self._selected(kind) is not None:
            widget.selection_set(self.indices[kind])
            widget.see(self.indices[kind])

    def _render(self) -> None:
        self.source_label.configure(
            text=f"Opened from {self.draft.source}" if self.draft.source else "New suite"
        )
        self._render_suite()
        for kind in ("case", "arm"):
            self._render_list(kind)
            self._render_detail(kind)
        self._update_count()

    @staticmethod
    def _clear(frame: ttk.Frame) -> None:
        for child in frame.winfo_children():
            child.destroy()

    def _field(
        self,
        frame: ttk.Frame | ttk.LabelFrame,
        label: str,
        data: dict[str, Any],
        key: str,
        *,
        choices: tuple[str, ...] = (),
        read: Callable[[Any], str] = lambda value: str(value if value is not None else ""),
        parse: Callable[[str], Any] = str,
        changed: Callable[[], None] | None = None,
        browse: Callable[[], None] | None = None,
    ) -> None:
        row = frame.grid_size()[1]
        ttk.Label(frame, text=label).grid(row=row, column=0, sticky="nw", padx=(0, 10), pady=4)
        var = tk.StringVar(self, value=read(data.get(key)))
        widget: ttk.Entry | ttk.Combobox
        if choices:
            widget = ttk.Combobox(
                frame, textvariable=var, values=choices, state="readonly", style=DARK_COMBOBOX_STYLE
            )
        else:
            widget = ttk.Entry(frame, textvariable=var)
        widget.grid(row=row, column=1, sticky="ew", pady=4)
        if browse is not None:
            ttk.Button(frame, text="Browse…", command=lambda: self._when_idle(browse)).grid(
                row=row, column=2, padx=(4, 0)
            )

        def update(*_args: str) -> None:
            if not self._busy:
                data[key] = parse(var.get())
                self._changed()
                if changed is not None:
                    changed()

        var.trace_add("write", update)

    def _prompt(
        self, parent: ttk.Frame | ttk.LabelFrame, label: str, data: dict[str, Any], key: str
    ) -> None:
        row = parent.grid_size()[1]
        ttk.Label(parent, text=label).grid(row=row, column=0, sticky="nw", padx=(0, 10), pady=4)
        box = tk.Text(parent, height=3, width=24, undo=True, wrap="word")
        style_text_widget(box)
        box.grid(row=row, column=1, sticky="ew", pady=4)
        box.insert("1.0", str(data.get(key) or ""))
        box.edit_modified(False)

        def update(_event: tk.Event) -> None:
            if box.edit_modified():
                box.edit_modified(False)
                if not self._busy:
                    data[key] = box.get("1.0", "end-1c")
                    self._changed()

        box.bind("<<Modified>>", update)

    def _notice(self, parent: ttk.Frame, text: str) -> None:
        row = parent.grid_size()[1]
        notice = ttk.Label(parent, text=text, justify="left")
        notice.grid(row=row, column=0, columnspan=2, sticky="ew", pady=4)
        bind_wraplength(notice)

    def _render_suite(self) -> None:
        frame = self.suite_form
        self._clear(frame)
        record = self.draft.data
        self._field(frame, "Suite ID", record, "suite_id")
        self._prompt(frame, "Description", record, "description")
        self._field(frame, "Shared seed", record, "seed")
        ids = tuple(str(arm.get("arm_id") or "").strip() for arm in self.draft.arms)
        # The v1 loader uses the first arm for suites that omit their baseline.
        view = {"baseline_arm": record.get("baseline_arm") or (ids[0] if ids else "")}

        def baseline_changed() -> None:
            record["baseline_arm"] = view["baseline_arm"]

        if ids:
            self._field(
                frame, "Baseline arm", view, "baseline_arm", choices=ids, changed=baseline_changed
            )
        else:
            self._notice(frame, "Add an arm before choosing a baseline.")

    def _render_detail(self, kind: str) -> None:
        frame = self.details[kind]
        self._clear(frame)
        record = self._selected(kind)
        if record is None:
            self._notice(frame, f"Add a {kind} to begin.")
            return

        def rename() -> None:
            self._render_list(kind)
            if kind == "arm":
                self._render_suite()

        self._field(frame, f"{kind.title()} ID", record, f"{kind}_id", changed=rename)
        if kind == "case":
            self._case_fields(frame, record)
        else:
            self._arm_fields(frame, record)

    def _case_fields(self, frame: ttk.Frame, record: dict[str, Any]) -> None:
        image = str(record.get("image") or "")
        self._notice(frame, f"Source image: {image or 'Choose a file'}")
        if record.get("image_sha256"):
            self._notice(frame, f"SHA-256: {record['image_sha256']}")
        self._form_buttons(frame, [("Bind Image…", lambda: self._bind_image(record))])
        self._prompt(frame, "Negative prompt", record, "negative_prompt")
        self._field(
            frame,
            "Tags (comma separated)",
            record,
            "tags",
            read=lambda items: ", ".join(map(str, items))
            if isinstance(items, list)
            else str(items or ""),
            parse=lambda value: [tag.strip() for tag in value.split(",") if tag.strip()],
        )
        segments = record.get("segments")
        if segments is None:
            has_motion = record.get("motion") is not None
            self._prompt(
                frame,
                "Appearance and scene prompt" if has_motion else "Motion prompt",
                record,
                "prompt",
            )
            self._motion_section(frame, record)
            if not has_motion:  # a driving-motion case is a single clip
                self._form_buttons(
                    frame, [("Use Ordered Segments", lambda: self._convert_case(record, True))]
                )
            return
        if record.get("prompt"):
            self._prompt(frame, "Single-clip prompt (clear for sequence)", record, "prompt")
        if not isinstance(segments, list) or any(not isinstance(shot, dict) for shot in segments):
            self._notice(
                frame, "This sequence has invalid segment data. Choose Single Clip to replace it."
            )
            self._form_buttons(
                frame, [("Use Single Clip", lambda: self._convert_case(record, False))]
            )
            return
        for index, segment in enumerate(segments):
            shot = ttk.LabelFrame(frame, text=f"Segment {index + 1}", padding=6)
            shot.columnconfigure(1, weight=1)
            shot.grid(row=frame.grid_size()[1], column=0, columnspan=2, sticky="ew", pady=4)
            self._prompt(shot, "Motion prompt", segment, "prompt")
            self._field(
                shot,
                "Frames (blank uses arm)",
                segment,
                "frame_count",
                parse=lambda value: _whole_or_text(value) if value.strip() else None,
            )
            buttons: list[tuple[str, Callable[[], None]]] = []
            if index:
                buttons.append(("Move Up", partial(self._move_segment, segments, index, -1)))
            if index < len(segments) - 1:
                buttons.append(("Move Down", partial(self._move_segment, segments, index, 1)))
            buttons.append(("Remove Segment", partial(self._remove_segment, segments, index)))
            self._form_buttons(shot, buttons)
        self._form_buttons(
            frame,
            [
                ("Add Segment", lambda: self._add_segment(segments)),
                ("Use Single Clip", lambda: self._convert_case(record, False)),
            ],
        )

    def _form_buttons(
        self, frame: ttk.Frame | ttk.LabelFrame, buttons: list[tuple[str, Callable[[], None]]]
    ) -> None:
        actions = ttk.Frame(frame)
        actions.grid(row=frame.grid_size()[1], column=0, columnspan=2, sticky="w", pady=4)
        for text, command in buttons:
            self._button(actions, text, command)

    def _convert_case(self, record: dict[str, Any], sequence: bool) -> None:
        if sequence:
            record["segments"] = [{"prompt": record.pop("prompt", "")}, {"prompt": ""}]
        else:
            segments = record.get("segments")
            if not self._confirm_discard(
                "Use single clip",
                "Replace the ordered segments with one motion prompt?",
                parent=self,
            ):
                return
            if isinstance(segments, list) and segments and isinstance(segments[0], dict):
                record.setdefault("prompt", segments[0].get("prompt", ""))
            record.pop("segments", None)
        self._case_changed()

    def _move_segment(self, segments: list[Any], index: int, delta: int) -> None:
        segments[index], segments[index + delta] = segments[index + delta], segments[index]
        self._case_changed()

    def _remove_segment(self, segments: list[Any], index: int) -> None:
        segments.pop(index)
        self._case_changed()

    def _add_segment(self, segments: list[Any]) -> None:
        segments.append({"prompt": ""})
        self._case_changed()

    def _case_changed(self) -> None:
        self._changed()
        self._render_list("case")
        self._render_detail("case")

    def _arm_fields(self, frame: ttk.Frame, arm: dict[str, Any]) -> None:
        self._field(frame, "Label", arm, "label", changed=lambda: self._render_list("arm"))
        backend = arm.get("backend")
        view = {
            "backend": next(
                (label for label, key in _BACKENDS.items() if key == backend), str(backend or "")
            )
        }

        def select_backend() -> None:
            arm["backend"] = _BACKENDS[view["backend"]]
            self._render_list("arm")
            self._render_detail("arm")

        self._field(
            frame, "Backend", view, "backend", choices=tuple(_BACKENDS), changed=select_backend
        )
        if backend == ARM_BACKEND_SVD:
            self._svd_fields(frame, arm)
        elif backend == ARM_BACKEND_WORKFLOW:
            self._workflow_fields(frame, arm)

    def _svd_fields(self, frame: ttk.Frame, arm: dict[str, Any]) -> None:
        config = arm.get("svd", {})
        if not isinstance(config, dict):
            self._notice(frame, "This arm's SVD settings are invalid. Reset them to edit the arm.")
        else:
            fields = (
                ("inference", "num_frames", "Frames", ()),
                ("inference", "fps", "Frames per second", ()),
                ("inference", "num_inference_steps", "Inference steps", ()),
                ("inference", "motion_bucket_id", "Motion bucket", ()),
                ("inference", "noise_aug_strength", "Noise augmentation", ()),
                ("inference", "decode_chunk_size", "Decode chunk size", ()),
                ("output", "output_format", "Output format", ("mp4", "gif", "frames")),
            )
            for section, key, label, choices in fields:
                group = config.get(section, {})
                if not isinstance(group, dict):
                    continue

                def store(
                    group: dict[str, Any] = group, section: str = section, key: str = key
                ) -> None:
                    if not group.get(key):
                        group.pop(key, None)
                    if group or section in config:
                        config[section] = group
                        arm["svd"] = config

                self._field(
                    frame, label, group, key, choices=choices, parse=str.strip, changed=store
                )
            self._notice(frame, "Blank numeric settings inherit native SVD defaults.")

        self._form_buttons(
            frame, [("Reset SVD Settings…", lambda: self._reset_arm(arm, "svd", {}))]
        )

    def _workflow_fields(self, frame: ttk.Frame, arm: dict[str, Any]) -> None:
        form = arm.get("form", {})
        catalog = self._catalog
        if catalog is None:
            return
        specs = {
            f"{spec.display_name} · {spec.workflow_id} {spec.workflow_version}"
            + (" · experimental" if spec.is_experimental else ""): spec
            for spec in catalog.specs
        }
        identity = (
            (str(form.get("workflow_id") or ""), str(form.get("workflow_version") or ""))
            if isinstance(form, dict)
            else ("", "")
        )
        selected = None
        if identity[0]:
            try:
                version = identity[1] or None
                if "workflow_version" not in form:
                    version = catalog.inherited_version(identity[0])
                selected = catalog.get(identity[0], version)
            except KeyError:
                pass
        selected_label = next((name for name, spec in specs.items() if spec == selected), "")
        if not selected_label:
            selected_label = " ".join(identity).strip() or "Choose a workflow"
        elif "workflow_version" not in form:
            selected_label += " (inherited version)"
        view = {"engine": selected_label}

        def select_workflow() -> None:
            spec = specs[view["engine"]]
            target = arm.get("form")
            if not isinstance(target, dict):
                target = {}
                arm["form"] = target
            target.update(
                workflow_id=spec.workflow_id,
                workflow_version=spec.workflow_version,
                experimental_opt_in=False,
            )
            self._render_detail("arm")

        self._field(
            frame, "Workflow", view, "engine", choices=tuple(specs), changed=select_workflow
        )
        if not isinstance(form, dict):
            self._notice(frame, "Invalid workflow settings. Choose an engine to replace them.")
            return
        if selected is None:
            return
        settings = arm.setdefault("form", form)
        visible = form_visibility(selected)
        if visible["frame_count"]:
            self._field(
                frame, "Frames (blank uses default)", settings, "frame_count", parse=_whole_or_text
            )
        if visible["motion_profile"]:
            self._field(frame, "Motion profile", settings, "motion_profile")
        if visible["end_anchor"]:
            self._path_field(frame, "End anchor", settings, "end_anchor_path", IMAGE_FILES)
        motion_suite = self.draft.has_motion
        if visible["pose_video"] and motion_suite:
            self._notice(
                frame,
                "This suite's cases bind their own driving-motion references, so no driving clip or motion "
                "prompt is set on the arm.",
            )
        elif visible["pose_video"]:
            self._path_field(
                frame,
                "Driving clip",
                settings,
                "pose_video_path",
                [("Video", "*.mp4 *.mov *.mkv *.webm *.avi"), ("All files", "*.*")],
            )
        elif motion_suite:
            self._notice(
                frame,
                "This workflow takes no driving video, so the suite's driving-motion cases cannot run under "
                "it. Validation refuses the combination; the reference is never dropped.",
            )
        overrides = settings.get("operator_controls", {})
        if isinstance(overrides, dict):
            for control in operator_controls(selected):
                if motion_suite and control["name"] in CASE_OWNED_CONTROLS:
                    continue
                self._field(
                    frame,
                    control["label"],
                    overrides,
                    control["name"],
                    changed=partial(settings.update, operator_controls=overrides),
                )
        if selected.is_experimental:
            opt_in = tk.BooleanVar(self, value=settings.get("experimental_opt_in") is True)

            def opt_in_changed() -> None:
                settings["experimental_opt_in"] = opt_in.get()
                self._changed()

            ttk.Checkbutton(
                frame,
                text="Opt this arm in to the experimental workflow",
                variable=opt_in,
                command=lambda: self._when_idle(opt_in_changed),
            ).grid(row=frame.grid_size()[1], column=0, columnspan=2, sticky="w", pady=4)
        self._form_buttons(
            frame,
            [
                (
                    "Reset Workflow Settings…",
                    lambda: self._reset_arm(
                        arm,
                        "form",
                        {
                            key: settings[key]
                            for key in ("workflow_id", "workflow_version")
                            if key in settings
                        },
                    ),
                )
            ],
        )

    def _path_field(
        self,
        frame: ttk.Frame,
        label: str,
        settings: dict[str, Any],
        key: str,
        filetypes: list[tuple[str, str]],
    ) -> None:
        def choose() -> None:
            path = self._ask_open(parent=self, title=f"Choose {label.lower()}", filetypes=filetypes)
            if path:
                settings[key] = path
                self._changed()
                self._render_detail("arm")

        self._field(frame, label, settings, key, browse=choose)

    def _reset_arm(self, arm: dict[str, Any], key: str, settings: dict[str, Any]) -> None:
        if self._confirm_discard(
            "Reset arm settings", "Reset the selected arm's overrides?", parent=self
        ):
            arm[key] = settings
            self._changed()
            self._render_detail("arm")

    def _add(self, kind: str, *, duplicate: bool = False) -> None:
        if kind == "case":
            self.draft.add_case()
        else:
            original = self._selected(kind) if duplicate else None
            if duplicate and original is None:
                return
            self.draft.add_arm(original)
        self.indices[kind] = len(self._items(kind)) - 1
        self._changed()
        self._render()

    def _remove(self, kind: str) -> None:
        selected = self._selected(kind)
        if selected is None:
            return
        items = self._items(kind)
        items.pop(self.indices[kind])
        self.indices[kind] = min(self.indices[kind], len(items) - 1)
        self._changed()
        self._render()

    def _changed(self) -> None:
        self._dirty = True
        self._show_results("Draft changed.")
        self._update_count()

    def _update_count(self) -> None:
        cases = len(self.draft.cases)
        arms = len(self.draft.arms)
        self.count.set(f"{cases} cases × {arms} arms = {cases * arms} jobs (limit {MAX_EVAL_JOBS})")
        disabled = self._busy or not 0 < self.draft.job_count <= MAX_EVAL_JOBS
        for button in (self.save_button, self.preview_button):
            button.state(["disabled"] if disabled else ["!disabled"])

    def _show_results(self, status: str, messages: tuple[str, ...] = ()) -> None:
        self.status.set(status)
        self.results.configure(state="normal")
        self.results.delete("1.0", "end")
        self.results.insert("1.0", "\n".join(messages))
        self.results.configure(state="disabled")
        if messages:
            self.results.pack(fill="x", before=self.status_label)
        else:
            self.results.pack_forget()

    def _open(self) -> None:
        path = self._ask_open(
            parent=self,
            title="Open evaluation suite or template",
            filetypes=JSON_FILES,
            initialdir=str(self.plan_root / "templates"),
        )
        if path:
            self._load(Path(path))

    def _load(self, path: Path | None) -> None:
        if not self._may_discard():
            return
        catalog = self._catalog

        def work() -> WorkOutcome:
            return WorkOutcome(
                value=(
                    catalog or EvalWorkflowCatalog(),
                    EvalSuiteDraft.open(path) if path else EvalSuiteDraft.new(),
                )
            )

        def done(outcome: WorkOutcome) -> None:
            self._catalog, self.draft = outcome.value
            self.indices = {"case": 0, "arm": 0}
            self._dirty = False
            self._render()
            tab = 1 if path and self.draft.cases else 0
            self.tabs.select(tab)  # type: ignore[no-untyped-call]
            self._show_results(
                "Suite opened. Review each case and bind any missing source images."
                if path
                else "New suite."
            )

        self._start("Open", work, done, "Opening suite…" if path else "Preparing a new suite…")

    def _bind_image(self, record: dict[str, Any]) -> None:
        path = self._ask_open(parent=self, title="Bind case source image", filetypes=IMAGE_FILES)
        if not path:
            return

        def done(outcome: WorkOutcome) -> None:
            record.update(outcome.value)
            self._case_changed()
            self._show_results(f"Bound {Path(path).name}.")

        self._start(
            "Bind",
            lambda: WorkOutcome(value=bind_source(Path(path))),
            done,
            "Checking source image…",
        )

    def _validate(self, *, save: bool, preview: bool = False) -> None:
        snapshot = deepcopy(self.draft)
        catalog = self._catalog
        root = self.plan_root

        def work() -> WorkOutcome:
            validation = validate_draft(snapshot, catalog or EvalWorkflowCatalog())
            path = (
                publish_validated_suite(validation, root)
                if save and not validation.errors
                else None
            )
            return WorkOutcome(value=(validation.errors, path))

        def done(outcome: WorkOutcome) -> None:
            errors, path = outcome.value
            if errors:
                self._show_results("Resolve these issues before saving.", errors)
            elif path is None:
                self._show_results(
                    "Validation passed. Save a new version to preview the compiled jobs."
                )
            else:
                self._dirty = False
                self.destroy()
                self._on_saved(path, preview)

        self._start("Save" if save else "Validate", work, done, "Validating suite…", saving=save)

    def _start(
        self,
        name: str,
        work: Callable[[], WorkOutcome],
        finish: Callable[[WorkOutcome], None],
        status: str,
        *,
        saving: bool = False,
    ) -> None:
        if self._busy or self._closed:
            return
        self._busy = True
        self._saving = saving
        self.close_button.state(["disabled"] if saving else ["!disabled"])
        self._show_results(status)
        self._update_count()
        disabled = self._disable_edits()

        def done(outcome: WorkOutcome) -> None:
            if self._closed:
                return
            self._busy = False
            self._saving = False
            self.close_button.state(["!disabled"])
            for widget in disabled:
                if isinstance(widget, (tk.Text, tk.Listbox)):
                    widget.configure(state="normal")
                else:
                    widget.state(["!disabled"])
            self._update_count()
            if outcome.error:
                self._show_results(f"{name} failed.", (outcome.error,))
            else:
                finish(outcome)

        self._runner.start(f"VideoEval-Editor-{name}", work, done)

    def _disable_edits(self) -> list[Any]:
        disabled: list[Any] = []
        pending: list[tk.Misc] = [self.suite_form, *self.details.values(), *self.lists.values()]
        while pending:
            widget = pending.pop()
            pending.extend(widget.winfo_children())
            if isinstance(widget, (tk.Text, tk.Listbox)) and widget["state"] == "normal":
                widget.configure(state="disabled")
                disabled.append(widget)
            elif isinstance(widget, (ttk.Entry, ttk.Button, ttk.Checkbutton)) and widget.instate(
                ["!disabled"]
            ):
                widget.state(["disabled"])
                disabled.append(widget)
        return disabled

    def _may_discard(self) -> bool:
        return not self._dirty or self._confirm_discard(
            "Discard draft changes", "Discard the unsaved changes to this suite?", parent=self
        )

    def _request_close(self) -> None:
        if not self._saving and self._may_discard():
            self.destroy()

    def _destroyed(self, event: tk.Event) -> None:
        if event.widget is self and not self._closed:
            self._closed = True
            self._on_close()
