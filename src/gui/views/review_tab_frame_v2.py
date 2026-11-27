"""Present image selection, ratings, disposition, and reprocessing actions in Review."""

from __future__ import annotations

import os
import tkinter as tk
from collections.abc import Callable, Sequence
from pathlib import Path
from tkinter import filedialog, messagebox, ttk
from typing import Any

from src.controller.app_controller_services.pack_model_batch_service import batch_identity
from src.controller.batch_operations_service import build_batch_operations_service
from src.controller.content_visibility_resolver import ContentVisibilityResolver
from src.gui.artifact_metadata_inspector_dialog import ArtifactMetadataInspectorDialog
from src.gui.help_text.workflow_guidance_v2 import (
    REVIEW_DEFAULT_WORKFLOW_HINT,
    build_review_action_guidance,
    get_review_handoff_hint,
)
from src.gui.layout_v2 import configure_grid_columns
from src.gui.theme_v2 import (
    apply_toplevel_theme,
    style_canvas_widget,
    style_listbox_widget,
    style_text_widget,
)
from src.gui.tooltip import attach_tooltip
from src.gui.ui_tokens import TOKENS
from src.gui.view_contracts.edit_work_runner import build_edit_work_runner
from src.gui.view_contracts.pipeline_layout_contract import (
    PRIMARY_CONTROL_MIN_WIDTH,
    get_single_pair_form_column_specs,
    get_two_pane_workspace_column_specs,
)
from src.gui.view_contracts.review_selection_contract import (
    ReviewSelectionRevisions,
    SelectionToken,
)
from src.gui.view_contracts.review_workspace_contract import (
    FILTER_LABELS,
    INSPECTION_LABELS,
    LOC_ARCHIVED,
    STATE_LABELS,
    ItemState,
    ReviewWorkspaceSession,
    ViewFilter,
    item_key,
    selection_label_text,
    undo_rating_text,
)
from src.gui.views.review_set_picker import ReviewSetPicker
from src.gui.widgets.action_explainer_panel_v2 import ActionExplainerPanel
from src.gui.widgets.disclosure_section_v2 import DisclosureSection
from src.gui.widgets.flow_row_v2 import FlowRow
from src.gui.widgets.media_inspector import MediaInspector as ThumbnailWidget
from src.gui.widgets.responsive_wrap_v2 import bind_wraplength
from src.gui.widgets.scrollable_frame_v2 import ScrollableFrame
from src.gui.widgets.tab_overview_panel_v2 import TabOverviewPanel, get_tab_overview_content
from src.learning.feedback_save import refresh_saved_feedback
from src.queue.job_history_store import JobHistoryEntry
from src.review.adetailer_outcome import (
    OUTCOME_LABELS,
    AdetailerPair,
    build_review_context,
    resolve_adetailer_pair,
)
from src.review.archive import (
    ARCHIVED_MESSAGE,
    ArchiveOutcome,
    active_input_paths,
    archive_file,
    archive_root,
    archived_reason,
    configured_output_root,
    job_queue_of,
    restore_file,
)
from src.review.effective_prompt import (
    EffectivePromptView,
    format_provenance,
    project_effective_prompts,
    redact_view,
)
from src.review.improvement_evidence import ImprovementPair
from src.review.review_evidence import (
    InspectionDraft,
    clear_inspection,
    save_disposition,
    save_inspection,
)
from src.review.review_lineage import (
    batch_of_job_reader,
    repository_of,
    resolve_result_images,
)
from src.review.workflow_adapter import (
    ReviewWorkflowAdapter,
    ReviewWorkspaceHandoff,
)
from src.review.workspace_io import (
    MAX_FOLDER_IMAGES,
    CompareImageError,
    FolderScan,
    ImageContext,
    PreparedCompare,
    load_image_context,
    prepare_compare,
    scan_image_folder,
)
from src.utils.image_metadata import extract_embedded_metadata

try:
    from PIL import ImageTk

    PIL_AVAILABLE = True
except ImportError:
    PIL_AVAILABLE = False

#: Widgets where a letter is typed text, never a Review key (tk/ttk class names).
TEXT_ENTRY_CLASSES = frozenset(
    {"Entry", "TEntry", "Text", "Spinbox", "TSpinbox", "Combobox", "TCombobox"}
)
_CONTROL_MASK = 0x4
_ALT_MASK = (
    0x20000  # Windows reports Alt here; 0x8 is NumLock there, so it is not treated as a modifier
)


class ReviewTabFrame(ttk.Frame):
    """MVP tab for reviewing existing images and reprocessing with prompt edits."""

    def __init__(
        self,
        master: tk.Misc,
        *,
        app_controller: Any = None,
        app_state: Any = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(master, **kwargs)
        self.app_controller = app_controller
        self.app_state = app_state
        self._workflow_adapter = ReviewWorkflowAdapter()
        self._default_workflow_hint = REVIEW_DEFAULT_WORKFLOW_HINT

        self.selected_images: list[Path] = []
        self._image_index_by_row: list[Path] = []

        self.stage_img2img_var = tk.BooleanVar(value=False)
        self.stage_adetailer_var = tk.BooleanVar(value=True)
        self.stage_upscale_var = tk.BooleanVar(value=False)
        self.klein_edit_var = tk.BooleanVar(value=False)
        self._klein_snapshot: dict[str, Any] | None = None
        self.prompt_mode_var = tk.StringVar(value="append")
        self.negative_mode_var = tk.StringVar(value="append")
        self._prompt_prev_mode = "append"
        self._negative_prev_mode = "append"
        self._prompt_mode_edits: dict[str, str] = {
            "append": "",
            "replace": "",
            "modify": "",
        }
        self._negative_mode_edits: dict[str, str] = {
            "append": "",
            "replace": "",
            "modify": "",
        }
        self.batch_size_var = tk.IntVar(value=1)
        self.group_by_model_var = tk.BooleanVar(value=False)
        self.rating_var = tk.IntVar(value=3)
        self.anatomy_rating_var = tk.IntVar(value=3)
        # PR-REFINE-160: optional per-region before/after judgment of an ADetailer output (default: unreviewed).
        self.adetailer_face_outcome_var = tk.StringVar(value=OUTCOME_LABELS["unreviewed"])
        self.adetailer_hands_outcome_var = tk.StringVar(value=OUTCOME_LABELS["unreviewed"])
        self.adetailer_outcome_note_var = tk.StringVar(value="")
        self._adetailer_pair: AdetailerPair | None = None
        self.composition_rating_var = tk.IntVar(value=3)
        self.prompt_adherence_rating_var = tk.IntVar(value=3)
        self.quality_var = tk.StringVar(value="okay")
        self._effective_settings_var = tk.StringVar(value="Effective settings: select an image")
        self._prior_review_summary_var = tk.StringVar(value="Prior Review Summary: none")
        #: Whether the status line holds a rating save/undo message (it ends when another image is shown).
        self._rating_status_shown = False
        #: ``(sequence, funcid)`` of the toplevel key bindings this tab added (removed on destroy).
        self._workspace_keys: list[tuple[str, str]] = []
        self._feedback_undo_stack: list[list[dict[str, str]]] = []
        #: ``(image path, SHA-256)`` of each inspection saved from Inspect & Improve, for Undo (a clearing row).
        self._inspection_undo: list[tuple[str, str]] = []
        self._feedback_status_var = tk.StringVar(value="")
        self._selected_base_prompt = ""
        self._selected_base_negative_prompt = ""
        self._selected_image_path: Path | None = None
        # SHA-256 of the bytes shown for the selected image, read off the Tk thread ("" until known or unreadable).
        self._selected_image_sha256 = ""
        self._applying_saved_rating = False
        self._rating_touched = False
        for rating_var in (
            self.rating_var,
            self.quality_var,
            self.anatomy_rating_var,
            self.composition_rating_var,
            self.prompt_adherence_rating_var,
        ):
            rating_var.trace_add("write", self._mark_rating_touched)
        for outcome_var in (
            self.adetailer_face_outcome_var,
            self.adetailer_hands_outcome_var,
            self.adetailer_outcome_note_var,
        ):
            outcome_var.trace_add("write", self._mark_rating_touched)
        self._compare_window: tk.Toplevel | None = None
        self._compare_canvas: tk.Canvas | None = None
        self._compare_photo: Any = None
        self._compare_mode = "single"
        self._history_import_window: tk.Toplevel | None = None
        self._inspection: tk.Toplevel | None = None
        self._active_handoff: ReviewWorkspaceHandoff | None = None
        self._content_visibility_mode = str(
            getattr(getattr(self, "app_state", None), "content_visibility_mode", "nsfw") or "nsfw"
        )
        self._pending_visibility_refresh = False
        # PR-GUI-UX-580: blocking file work runs on a worker; every result carries the selection revision it was
        # requested under and is dropped when a newer selection, handoff or image request has superseded it.
        self._revisions = ReviewSelectionRevisions()
        self._work = build_edit_work_runner(self)
        self._image_ready = False
        self._pending_overlay: tuple[ReviewWorkspaceHandoff, Path] | None = None
        self._edited_since_selection = False
        self._confirm_replace_hook: Any = None
        #: Replaced by tests: a real modal would hang the run (PR-REVIEW-ARCHIVE-623).
        self._confirm_discard_hook: Any = None
        self._confirm_alternative_hook: Any = None
        self._archive_context: tuple[Path, Any] = (Path("output"), None)
        self._offer_after: str | None = None
        # PR-REVIEW-LIFECYCLE-621: the logical workspace. Only decisions and ratings are stored (Learning evidence);
        # job states are derived from the job repository every time they are read.
        self._session = ReviewWorkspaceSession(
            runner=self._work,
            records_path=self._evidence_records_path,
            repository=self._review_repository,
            write_disposition=self._write_disposition,
            on_change=self._on_session_changed,
            output_root=lambda: self._output_root(),
            archive=lambda path, digest: self._archive_on_worker(path, digest),
            restore=lambda path, digest, alt: self._restore_on_worker(path, digest, alt),
        )
        self._row_texts: list[str] = []
        self._undo_order: list[str] = []
        self._returned_rows: list[Any] = []
        self._set_picker: ReviewSetPicker | None = None
        self.filter_var = tk.StringVar(value=FILTER_LABELS[ViewFilter.ACTIVE])
        self._scope_var = tk.StringVar(value="")
        self._rework_reason_var = tk.StringVar(value="")
        self._single_note_var = tk.StringVar(value="")
        self._baseline_note_var = tk.StringVar(value="")
        self._returned_note_var = tk.StringVar(value="")
        self._adetailer_enabled = False
        self._adetailer_outcome_widgets: list[Any] = []
        self._provenance_view: EffectivePromptView | None = None
        self._writer: Any = None
        self._batch_of_job: Any = None
        self._poll_id: str | None = None
        self._last_session_message = ""
        self._batch_saves = 0

        self.columnconfigure(0, weight=1)
        self.rowconfigure(0, weight=0)
        self.rowconfigure(1, weight=0)
        self.rowconfigure(2, weight=1)
        self.rowconfigure(3, weight=0)

        self.overview_panel = TabOverviewPanel(
            self,
            content=get_tab_overview_content("review"),
            app_state=self.app_state,
        )
        self.overview_panel.grid(row=0, column=0, sticky="ew", padx=6, pady=(6, 0))

        self._build_header()
        self._build_body()
        self._build_controls()
        self._build_returned()

        self.prompt_mode_var.trace_add("write", lambda *_: self._on_prompt_mode_changed())
        self.negative_mode_var.trace_add("write", lambda *_: self._on_negative_mode_changed())
        self.stage_img2img_var.trace_add("write", lambda *_: self._refresh_effective_settings())
        self.stage_adetailer_var.trace_add("write", lambda *_: self._refresh_effective_settings())
        self.stage_upscale_var.trace_add("write", lambda *_: self._refresh_effective_settings())
        self.klein_edit_var.trace_add("write", lambda *_: self._on_klein_edit_toggled())
        self.klein_edit_var.trace_add("write", lambda *_: self._refresh_effective_settings())
        self.prompt_text.bind("<KeyRelease>", lambda _e: self._on_prompt_edited())
        self.negative_text.bind("<KeyRelease>", lambda _e: self._on_prompt_edited())
        self._set_readonly_text(self.current_prompt_text, "")
        self._set_readonly_text(self.current_negative_text, "")
        self._sync_edit_box_to_mode("prompt")
        self._sync_edit_box_to_mode("negative")
        self.bind("<Map>", self._on_map, add="+")
        self._refresh_prompt_diff()
        self._refresh_workspace_view()
        if self.app_state is not None and hasattr(self.app_state, "subscribe"):
            try:
                self.app_state.subscribe(
                    "content_visibility_mode",
                    self._on_content_visibility_mode_changed,
                )
            except Exception:
                pass
        self.on_content_visibility_mode_changed(self._content_visibility_mode)

    def _build_header(self) -> None:
        # The set bar: one Open menu, the state filter with its counts, and where hand-offs and messages land.
        header = ttk.Frame(self, style="Panel.TFrame", padding=8)
        header.grid(row=1, column=0, sticky="ew", padx=6, pady=(6, 4))
        header.columnconfigure(5, weight=1)

        self.open_button = ttk.Menubutton(header, text="Open...")
        self.open_menu = tk.Menu(self.open_button, tearoff=False)
        self.open_menu.add_command(label="Folder...", command=self._on_select_folder)
        self.open_menu.add_command(label="Files...", command=self._on_select_images)
        self.open_menu.add_command(label="Recent job...", command=self._on_open_recent_job)
        self.open_menu.add_command(label="Batch...", command=self._on_open_batch)
        self.open_button.configure(menu=self.open_menu)
        self.open_button.grid(row=0, column=0, sticky="w", padx=(0, 6))
        attach_tooltip(
            self.open_button,
            "Open the images to review: a folder, files, the outputs of a recent job, or the outputs of a "
            "Review or Video batch. Nothing is copied or changed.",
        )

        ttk.Button(
            header,
            text="Clear",
            style="Dark.TButton",
            command=self._on_clear,
        ).grid(row=0, column=1, sticky="w", padx=(0, 6))

        ttk.Label(header, text="Show", style="Dark.TLabel").grid(
            row=0, column=2, sticky="e", padx=(6, 4)
        )
        self.filter_box = ttk.Combobox(
            header,
            textvariable=self.filter_var,
            values=list(FILTER_LABELS.values()),
            state="readonly",
            style="Dark.TCombobox",
            width=10,
        )
        self.filter_box.grid(row=0, column=3, sticky="w")
        self.filter_box.bind("<<ComboboxSelected>>", self._on_filter_changed)
        self.counts_label = ttk.Label(header, text="", style="Dark.TLabel")
        self.counts_label.grid(row=0, column=4, sticky="w", padx=(10, 0))

        self.selection_label = ttk.Label(
            header,
            text="No images selected",
            style="Dark.TLabel",
        )
        self.selection_label.grid(row=0, column=5, sticky="e")
        self.help_button = ttk.Button(
            header, text="Help", style="Dark.TButton", command=self._toggle_help
        )
        self.help_button.grid(row=0, column=6, sticky="e", padx=(8, 0))
        self.visibility_banner = ttk.Label(header, text="", style="Dark.TLabel")

        self.workflow_hint_label = ttk.Label(
            header,
            text=self._default_workflow_hint,
            style="Dark.TLabel",
        )
        self.workflow_hint_label.grid(row=1, column=0, columnspan=7, sticky="ew", pady=(6, 0))
        bind_wraplength(self.workflow_hint_label)
        # One guidance panel, opened on demand (it used to stack under the hint and the overview).
        self.action_help_panel = ActionExplainerPanel(
            header,
            content=build_review_action_guidance(),
            app_state=self.app_state,
            wraplength=980,
        )
        self.action_help_panel.grid(row=2, column=0, columnspan=7, sticky="ew", pady=(8, 0))
        self.action_help_panel.grid_remove()

    def _toggle_help(self) -> None:
        if self.action_help_panel.winfo_manager():
            self.action_help_panel.grid_remove()
        else:
            self.action_help_panel.grid()

    def _build_body(self) -> None:
        # PR-GUI-100: preview/metadata and the decision controls share one scrollable workspace so the
        # ~620 px preview keeps its size and the controls below it stay reachable on short screens.
        self._workspace_scroll = ScrollableFrame(self, style="Panel.TFrame")
        self._workspace_scroll.grid(row=2, column=0, sticky="nsew", padx=6, pady=4)
        self._workspace_scroll.inner.columnconfigure(0, weight=1)
        body = ttk.Frame(self._workspace_scroll.inner, style="Panel.TFrame")
        body.grid(row=0, column=0, sticky="nsew")
        configure_grid_columns(body, get_two_pane_workspace_column_specs())
        body.rowconfigure(0, weight=1)
        self._body_frame = body

        left = ttk.LabelFrame(body, text="Images", style="Dark.TLabelframe", padding=8)
        left.grid(row=0, column=0, sticky="nsew", padx=(0, 6))
        left.columnconfigure(0, weight=1)
        left.rowconfigure(0, weight=1)

        self.images_list = tk.Listbox(
            left,
            bg=TOKENS.colors.surface_secondary,
            fg=TOKENS.colors.text_primary,
            selectbackground=TOKENS.colors.accent_primary,
            selectforeground=TOKENS.colors.text_primary,
            selectmode=tk.EXTENDED,
            borderwidth=0,
            highlightthickness=1,
            highlightbackground=TOKENS.colors.border_subtle,
            exportselection=False,
        )
        style_listbox_widget(self.images_list)
        self.images_list.grid(row=0, column=0, sticky="nsew")
        self.images_list.bind("<<ListboxSelect>>", self._on_image_select)
        # Keyboard triage: R retains, D discards, W marks for Re-work, U undoes; the next undecided image is shown.
        for sequence, disposition in (
            ("r", "retain"),
            ("d", "discard"),
            ("w", "rework"),
            ("u", "undo"),
        ):
            handler = self._decision_key_handler(disposition)
            workspace_handler = self._workspace_key_handler(disposition)
            for key in (sequence, sequence.upper()):
                self.images_list.bind(f"<Key-{key}>", handler)
                # The same keys work anywhere in this tab except where the operator is typing (see the handler).
                self._workspace_keys.append(
                    (
                        f"<Key-{key}>",
                        self.winfo_toplevel().bind(f"<Key-{key}>", workspace_handler, add="+"),
                    )
                )

        list_scroll = ttk.Scrollbar(left, orient="vertical", command=self.images_list.yview)
        list_scroll.grid(row=0, column=1, sticky="ns")
        self.images_list.configure(yscrollcommand=list_scroll.set)

        right = ttk.LabelFrame(body, text="Review", style="Dark.TLabelframe", padding=8)
        right.grid(row=0, column=1, sticky="nsew")
        right.columnconfigure(0, weight=1)

        preview_actions = FlowRow(right, style="Panel.TFrame", gap=6)
        preview_actions.grid(row=0, column=0, sticky="ew", pady=(0, 6))
        for text, command in (("Prev", self._show_previous_image), ("Next", self._show_next_image)):
            preview_actions.add(
                ttk.Button(preview_actions, text=text, style="Dark.TButton", command=command)
            )
        self.compare_button = ttk.Button(
            preview_actions,
            text="Compare",
            style="Dark.TButton",
            command=self._open_contextual_compare,
        )
        preview_actions.add(self.compare_button)
        attach_tooltip(
            self.compare_button,
            "Compare the image with its returned re-work (or its source), the ADetailer before/after when the "
            "source is verified, or a staged-curation derived image; otherwise a large view.",
        )
        preview_actions.add(
            ttk.Button(
                preview_actions,
                text="Inspect Metadata",
                style="Dark.TButton",
                command=self._open_metadata_inspector,
            )
        )
        self.send_video_button = ttk.Button(
            preview_actions,
            text="Make Video",
            style="Dark.TButton",
            command=self._on_send_selected_to_video_workflow,
        )
        preview_actions.add(self.send_video_button)
        self.send_video_tooltip = attach_tooltip(
            self.send_video_button,
            "Make a video from the image highlighted in the Images list: it opens the Video Workflow tab with that "
            "image loaded and the recommended workflow selected. Several highlighted images become batch sources. "
            "This only transfers the selection; nothing is queued until you press Queue there.",
        )
        self.send_to_button = ttk.Menubutton(preview_actions, text="Send to...")
        self.send_to_menu = tk.Menu(self.send_to_button, tearoff=False)
        self.send_to_menu.add_command(
            label="Learning (staged curation)...",
            command=self._on_import_selected_to_staged_curation,
        )
        self.send_to_menu.add_command(
            label="Photo Optimize (Managed Photo Set)...", command=self._on_manage_selected_photos
        )
        self.send_to_button.configure(menu=self.send_to_menu)
        preview_actions.add(self.send_to_button)
        self.send_to_tooltip = attach_tooltip(
            self.send_to_button,
            "Learning: record the highlighted images as evidence candidates (nothing is queued). Photo Optimize: "
            "offer them to the Managed Photo Set (nothing is copied until you confirm there).",
        )
        # Inpaint / outpaint the image shown without first marking it for Re-work (the Re-work region keeps its own
        # buttons for the one marked image).
        self.edit_image_button = ttk.Menubutton(preview_actions, text="Edit image...")
        self.edit_image_menu = tk.Menu(self.edit_image_button, tearoff=False)
        self.edit_image_menu.add_command(
            label="Inpaint (Edit Mask)...", command=lambda: self._open_mask_editor(shown=True)
        )
        self.edit_image_menu.add_command(
            label="Outpaint (Extend Canvas)...",
            command=lambda: self._open_outpaint_editor(shown=True),
        )
        self.edit_image_button.configure(menu=self.edit_image_menu)
        preview_actions.add(self.edit_image_button)
        attach_tooltip(
            self.edit_image_button,
            "Inpaint part of the image shown (paint a mask) or extend its canvas (outpaint). Each opens an editor "
            "with its own frozen preview; nothing is queued until you add the prepared job there.",
        )

        self._build_decision_bar(right, row=1)

        # PR-GUI-110: 620 px is the maximum, not an assumption; the preview fits the pane's real width.
        self.preview = ThumbnailWidget(
            right,
            width=620,
            height=620,
            placeholder_text="Select an image",
            responsive=True,
        )
        self.preview.grid(row=2, column=0, sticky="ew", pady=(0, 8))
        self.preview._canvas.bind(
            "<Double-Button-1>", lambda _event: self._open_contextual_compare()
        )
        self.preview.bind("<<MediaHidden>>", self._hide_compare_media, add="+")
        self.preview.bind("<<MediaHidden>>", lambda _event: self._close_inspection(), add="+")

        self.meta_label = ttk.Label(
            right,
            text="Metadata: n/a",
            style="Dark.TLabel",
            justify="left",
        )
        self.meta_label.grid(row=3, column=0, sticky="ew")
        bind_wraplength(self.meta_label)

        provenance_box = ttk.LabelFrame(
            right,
            text="Prompts and provenance",
            style="Dark.TLabelframe",
            padding=8,
        )
        provenance_box.grid(row=4, column=0, sticky="ew", pady=(8, 0))
        provenance_box.columnconfigure(0, weight=1)
        self.provenance_text = tk.Text(
            provenance_box,
            height=8,
            bg=TOKENS.colors.surface_tertiary,
            fg=TOKENS.colors.text_muted,
            insertbackground=TOKENS.colors.text_muted,
            wrap="word",
            borderwidth=1,
            relief="solid",
        )
        style_text_widget(self.provenance_text, elevated=True)
        self.provenance_text.configure(fg=TOKENS.colors.text_muted)
        self.provenance_text.grid(row=0, column=0, sticky="ew")
        self._set_readonly_text(self.provenance_text, "Select an image to see its prompts.")
        prior_review_label = ttk.Label(
            provenance_box,
            textvariable=self._prior_review_summary_var,
            style="Dark.TLabel",
            justify="left",
        )
        prior_review_label.grid(row=1, column=0, sticky="ew", pady=(6, 0))
        bind_wraplength(prior_review_label)

        self._build_rating_details(right, row=5)
        self._build_feedback_area(right, row=6)

    def _decision_key_handler(self, value: str) -> Callable[[tk.Event], str]:
        def handle(_event: tk.Event) -> str:
            return self._on_decision_key(value)

        return handle

    def _workspace_key_handler(self, value: str) -> Callable[[tk.Event], str | None]:
        def handle(event: tk.Event) -> str | None:
            if not self._owns_decision_key(event):
                return None  # not ours (another tab, a dialog) or the operator is typing: the key goes on unchanged
            return self._on_decision_key(value)

        return handle

    def _owns_decision_key(self, event: tk.Event) -> bool:
        """R/D/W/U act when focus is on a non-text widget inside this tab and no Control/Alt is held."""

        try:
            if not self.winfo_exists():
                return False
            widget = event.widget
            inside = str(widget) == str(self) or str(widget).startswith(f"{self}.")
            typing = widget.winfo_class() in TEXT_ENTRY_CLASSES
        except (tk.TclError, AttributeError, KeyError):
            return False
        state = event.state if isinstance(event.state, int) else 0
        return inside and not typing and not state & (_CONTROL_MASK | _ALT_MASK)

    def _build_decision_bar(self, parent: tk.Misc, *, row: int) -> None:
        """Retain / Discard / Re-work with the rating, right above the preview so triage never scrolls."""

        bar = FlowRow(parent, style="Panel.TFrame", gap=6)
        bar.grid(row=row, column=0, sticky="ew", pady=(0, 6))
        self.retain_button = ttk.Button(
            bar,
            text="Retain (R)",
            style="Dark.TButton",
            command=lambda: self._decide_current("retain"),
        )
        self.discard_button = ttk.Button(
            bar,
            text="Discard (D)",
            style="Dark.TButton",
            command=lambda: self._decide_current("discard"),
        )
        self.mark_rework_button = ttk.Button(
            bar,
            text="Re-work (W)",
            style="Dark.TButton",
            command=lambda: self._decide_current("rework"),
        )
        self.restore_button = ttk.Button(
            bar, text="Restore", style="Dark.TButton", command=self._restore_current
        )
        for button in (self.retain_button, self.discard_button, self.mark_rework_button):
            bar.add(button)
        bar.add(self.restore_button, shown=False)
        self._decision_tooltips = {
            "retain": attach_tooltip(self.retain_button, ""),
            "discard": attach_tooltip(self.discard_button, ""),
            "rework": attach_tooltip(self.mark_rework_button, ""),
        }
        bar.add(ttk.Label(bar, text="Rating", style="Dark.TLabel"))
        bar.add(
            ttk.Spinbox(
                bar,
                from_=1,
                to=5,
                increment=1,
                textvariable=self.rating_var,
                width=4,
                style="Dark.TSpinbox",
            )
        )
        self.save_rating_button = ttk.Button(
            bar, text="Save rating", style="Dark.TButton", command=self._save_feedback
        )
        bar.add(self.save_rating_button)
        attach_tooltip(
            self.save_rating_button,
            "Saves the rating, quality, subscores and notes as Learning evidence for these exact image bytes. The "
            "file is never changed. A decision made after you touched the rating saves it too.",
        )
        self._decision_bar = bar

    def _build_rating_details(self, parent: tk.Misc, *, row: int) -> None:
        """Quality label and subscores, one disclosure below the fold."""

        self.details_section = DisclosureSection(
            parent, title="Details (quality and subscores)", expanded=False
        )
        self.details_section.grid(row=row, column=0, sticky="ew", pady=(8, 0))
        body = self.details_section.body
        configure_grid_columns(body, get_single_pair_form_column_specs())
        ttk.Label(body, text="Quality", style="Dark.TLabel").grid(
            row=0, column=0, sticky="w", padx=(0, 6), pady=(0, 4)
        )
        ttk.Combobox(
            body,
            textvariable=self.quality_var,
            values=["reject", "poor", "okay", "good", "excellent"],
            state="readonly",
            style="Dark.TCombobox",
            width=12,
        ).grid(row=0, column=1, sticky="w", pady=(0, 4))
        ttk.Label(body, text="Subscores", style="Dark.TLabel").grid(
            row=1, column=0, sticky="w", padx=(0, 6), pady=(4, 4)
        )
        subscores = ttk.Frame(body, style="Panel.TFrame")
        subscores.grid(row=1, column=1, sticky="w", pady=(4, 4))
        # PR-GUI-110: two pairs per row (not three) so the row still fits a narrow pane at increased Tk scaling.
        subscores.columnconfigure(1, minsize=PRIMARY_CONTROL_MIN_WIDTH // 3)
        subscores.columnconfigure(3, minsize=PRIMARY_CONTROL_MIN_WIDTH // 3)
        for column, (label, variable) in enumerate(
            (("Anatomy", self.anatomy_rating_var), ("Composition", self.composition_rating_var))
        ):
            ttk.Label(subscores, text=label, style="Dark.TLabel").grid(
                row=0, column=column * 2, sticky="w", padx=(0 if column == 0 else 0, 0)
            )
            ttk.Spinbox(
                subscores,
                from_=1,
                to=5,
                increment=1,
                textvariable=variable,
                width=4,
                style="Dark.TSpinbox",
            ).grid(row=0, column=column * 2 + 1, sticky="w", padx=(6, 12 if column == 0 else 0))
        ttk.Label(subscores, text="Prompt Fit", style="Dark.TLabel").grid(
            row=1, column=0, sticky="w", pady=(4, 0)
        )
        ttk.Spinbox(
            subscores,
            from_=1,
            to=5,
            increment=1,
            textvariable=self.prompt_adherence_rating_var,
            width=4,
            style="Dark.TSpinbox",
        ).grid(row=1, column=1, sticky="w", padx=(6, 12), pady=(4, 0))

    def _build_feedback_area(self, parent: tk.Misc, *, row: int) -> None:
        feedback_box = ttk.LabelFrame(
            parent,
            text="Notes and actions",
            style="Dark.TLabelframe",
            padding=8,
        )
        feedback_box.grid(row=row, column=0, sticky="ew", pady=(8, 0))
        configure_grid_columns(feedback_box, get_single_pair_form_column_specs())
        ttk.Label(feedback_box, text="Notes", style="Dark.TLabel").grid(
            row=0, column=0, sticky="nw", padx=(0, 6)
        )
        self.feedback_notes = tk.Text(
            feedback_box,
            height=3,
            bg=TOKENS.colors.surface_secondary,
            fg=TOKENS.colors.text_primary,
            insertbackground=TOKENS.colors.text_primary,
            wrap="word",
            borderwidth=1,
            relief="solid",
        )
        style_text_widget(self.feedback_notes, elevated=True)
        self.feedback_notes.grid(row=0, column=1, sticky="ew")
        self.apply_selected_button = ttk.Button(
            feedback_box,
            text="Apply rating to selected",
            style="Dark.TButton",
            command=self._save_feedback_batch,
        )
        self.apply_selected_button.grid(row=1, column=0, columnspan=2, sticky="ew", pady=(6, 0))
        attach_tooltip(
            self.apply_selected_button,
            "Saves the rating, quality, subscores and notes shown here for every image highlighted in the list. "
            "It never marks, retains or discards them.",
        )
        # One row (not two) so the Review workspace keeps its scroll height.
        undo_row = ttk.Frame(feedback_box, style="Panel.TFrame")
        undo_row.grid(row=2, column=0, columnspan=2, sticky="ew", pady=(6, 0))
        undo_row.columnconfigure((0, 1), weight=1, uniform="feedback_actions")
        self.undo_button = ttk.Button(
            undo_row,
            text="Undo (U)",
            style="Dark.TButton",
            command=self._undo_last_action,
        )
        self.undo_button.grid(row=0, column=0, sticky="ew", padx=(0, 3))
        attach_tooltip(
            self.undo_button,
            "Undo the last decision (a new row restores the earlier one; nothing is deleted), the last saved "
            "inspection (a clearing row is recorded) or the last saved rating.",
        )
        self.write_rating_button = ttk.Button(
            undo_row,
            text="Write rating to file...",
            style="Dark.TButton",
            command=self._write_rating_into_file,
        )
        self.write_rating_button.grid(row=0, column=1, sticky="ew", padx=(3, 0))
        attach_tooltip(
            self.write_rating_button,
            "Optional export of the saved rating. PNG: embedded in the file, which changes the file's identity. "
            "JPEG and WebP: a sidecar file next to the image; the image is never re-encoded.",
        )
        feedback_status = ttk.Label(
            feedback_box, textvariable=self._feedback_status_var, style="Dark.TLabel"
        )
        feedback_status.grid(row=3, column=0, columnspan=2, sticky="ew", pady=(6, 0))
        bind_wraplength(feedback_status)
        feedback_status.grid_remove()
        self._feedback_status_label = feedback_status

        def show_feedback_outcome(*_args: object) -> None:
            feedback_status.grid()
            feedback_status.update_idletasks()
            self._workspace_scroll.reveal(feedback_status)

        self._feedback_status_var.trace_add("write", show_feedback_outcome)

    def _build_returned(self) -> None:
        """Finished re-work results beside their source; shown only when there is something to show."""

        frame = ttk.LabelFrame(
            self._workspace_scroll.inner,
            text="Returned",
            style="Dark.TLabelframe",
            padding=8,
        )
        frame.grid(row=2, column=0, sticky="ew", pady=(4, 6))
        frame.columnconfigure(0, weight=1)
        self._returned_frame = frame
        self.returned_tree = ttk.Treeview(
            frame,
            columns=("source", "result", "state", "link"),
            show="headings",
            selectmode="browse",
            height=5,
        )
        for name, heading, width in (
            ("source", "Source", 180),
            ("result", "Returned result", 220),
            ("state", "State", 130),
            ("link", "Source link", 130),
        ):
            self.returned_tree.heading(name, text=heading)
            self.returned_tree.column(name, width=width, anchor="w")
        self.returned_tree.grid(row=0, column=0, sticky="ew")
        actions = FlowRow(frame, style="Panel.TFrame", gap=6)
        actions.grid(row=1, column=0, sticky="ew", pady=(6, 0))
        self.returned_compare_button = ttk.Button(
            actions,
            text="Compare with source",
            style="Dark.TButton",
            command=self._compare_returned,
        )
        self.returned_review_button = ttk.Button(
            actions, text="Review result", style="Dark.TButton", command=self._review_returned
        )
        self.returned_rework_button = ttk.Button(
            actions, text="Re-work again", style="Dark.TButton", command=self._rework_returned_again
        )
        self.returned_refresh_button = ttk.Button(
            actions, text="Refresh", style="Dark.TButton", command=self._session.refresh
        )
        self.returned_batches_button = ttk.Button(
            actions, text="Open Batches (retry)", style="Dark.TButton", command=self._open_batches
        )
        for button in (
            self.returned_compare_button,
            self.returned_review_button,
            self.returned_rework_button,
            self.returned_refresh_button,
        ):
            actions.add(button)
        actions.add(self.returned_batches_button, shown=False)
        self._returned_actions = actions
        note = ttk.Label(frame, textvariable=self._returned_note_var, style="Dark.TLabel")
        note.grid(row=2, column=0, sticky="ew", pady=(6, 0))
        bind_wraplength(note)
        frame.grid_remove()

    def _build_controls(self) -> None:
        # PR-REVIEW-LIFECYCLE-621: the Re-work region is shown only while images are marked for Re-work.
        rework = ttk.LabelFrame(
            self._workspace_scroll.inner,
            text="Re-work",
            style="Dark.TLabelframe",
            padding=8,
        )
        rework.grid(row=1, column=0, sticky="ew", pady=(4, 6))
        rework.columnconfigure(0, weight=1)
        self._rework_frame = rework
        scope_label = ttk.Label(rework, textvariable=self._scope_var, style="Dark.TLabel")
        scope_label.grid(row=0, column=0, sticky="ew", pady=(0, 6))
        bind_wraplength(scope_label)
        controls = ttk.Frame(rework, style="Panel.TFrame")
        controls.grid(row=1, column=0, sticky="ew")
        configure_grid_columns(
            controls,
            get_two_pane_workspace_column_specs(
                left_min_width=420,
                right_min_width=360,
            ),
        )
        self._controls_frame = controls

        prompt_box = ttk.LabelFrame(
            controls,
            text="Current Prompts + Edits",
            style="Dark.TLabelframe",
            padding=8,
        )
        prompt_box.grid(row=0, column=0, sticky="nsew", padx=(0, 6))
        configure_grid_columns(prompt_box, get_single_pair_form_column_specs())
        prompt_box.rowconfigure(1, weight=0)
        prompt_box.rowconfigure(3, weight=0)

        self._baseline_label = ttk.Label(
            prompt_box, textvariable=self._baseline_note_var, style="Dark.TLabel"
        )
        self._baseline_label.grid(row=0, column=0, columnspan=2, sticky="w", pady=(0, 4))
        self.current_prompt_text = tk.Text(
            prompt_box,
            height=3,
            bg=TOKENS.colors.surface_tertiary,
            fg=TOKENS.colors.text_muted,
            insertbackground=TOKENS.colors.text_muted,
            wrap="word",
            borderwidth=1,
            relief="solid",
        )
        style_text_widget(self.current_prompt_text, elevated=True)
        self.current_prompt_text.configure(
            fg=TOKENS.colors.text_muted,
            insertbackground=TOKENS.colors.text_muted,
        )
        self.current_prompt_text.grid(row=1, column=0, columnspan=2, sticky="ew", pady=(0, 8))

        ttk.Label(prompt_box, text="Positive mode", style="Dark.TLabel").grid(
            row=2, column=0, sticky="w", padx=(0, 6), pady=(0, 4)
        )
        ttk.Combobox(
            prompt_box,
            textvariable=self.prompt_mode_var,
            values=["append", "replace", "modify"],
            state="readonly",
            style="Dark.TCombobox",
            width=10,
        ).grid(row=2, column=1, sticky="w", pady=(0, 4))

        self.prompt_text = tk.Text(
            prompt_box,
            height=4,
            bg=TOKENS.colors.surface_secondary,
            fg=TOKENS.colors.text_primary,
            insertbackground=TOKENS.colors.text_primary,
            wrap="word",
            borderwidth=1,
            relief="solid",
        )
        style_text_widget(self.prompt_text, elevated=True)
        self.prompt_text.grid(row=3, column=0, columnspan=2, sticky="ew", pady=(0, 8))

        ttk.Label(prompt_box, text="Current - prompt", style="Dark.TLabel").grid(
            row=4, column=0, columnspan=2, sticky="w", pady=(0, 4)
        )
        self.current_negative_text = tk.Text(
            prompt_box,
            height=3,
            bg=TOKENS.colors.surface_tertiary,
            fg=TOKENS.colors.text_muted,
            insertbackground=TOKENS.colors.text_muted,
            wrap="word",
            borderwidth=1,
            relief="solid",
        )
        style_text_widget(self.current_negative_text, elevated=True)
        self.current_negative_text.configure(
            fg=TOKENS.colors.text_muted,
            insertbackground=TOKENS.colors.text_muted,
        )
        self.current_negative_text.grid(row=5, column=0, columnspan=2, sticky="ew", pady=(0, 8))

        ttk.Label(prompt_box, text="Negative mode", style="Dark.TLabel").grid(
            row=6, column=0, sticky="w", padx=(0, 6), pady=(0, 4)
        )
        ttk.Combobox(
            prompt_box,
            textvariable=self.negative_mode_var,
            values=["append", "replace", "modify"],
            state="readonly",
            style="Dark.TCombobox",
            width=10,
        ).grid(row=6, column=1, sticky="w", pady=(0, 4))

        self.negative_text = tk.Text(
            prompt_box,
            height=4,
            bg=TOKENS.colors.surface_secondary,
            fg=TOKENS.colors.text_primary,
            insertbackground=TOKENS.colors.text_primary,
            wrap="word",
            borderwidth=1,
            relief="solid",
        )
        style_text_widget(self.negative_text, elevated=True)
        self.negative_text.grid(row=7, column=0, columnspan=2, sticky="ew")

        diff_box = ttk.LabelFrame(
            prompt_box,
            text="Before / After Diff",
            style="Dark.TLabelframe",
            padding=8,
        )
        diff_box.grid(row=8, column=0, columnspan=2, sticky="ew", pady=(8, 0))
        diff_box.columnconfigure(0, weight=1)

        self.diff_before_label = ttk.Label(
            diff_box,
            text="Before: (select an image)",
            style="Dark.TLabel",
            justify="left",
        )
        self.diff_before_label.grid(row=0, column=0, sticky="ew", pady=(0, 4))
        bind_wraplength(self.diff_before_label)

        self.diff_after_label = ttk.Label(
            diff_box,
            text="After: (no changes)",
            style="Dark.TLabel",
            justify="left",
        )
        self.diff_after_label.grid(row=1, column=0, sticky="ew")
        bind_wraplength(self.diff_after_label)

        run_box = ttk.LabelFrame(
            controls,
            text="Stages and queue",
            style="Dark.TLabelframe",
            padding=8,
        )
        run_box.grid(row=0, column=1, sticky="nsew")
        run_box.columnconfigure(0, weight=1)

        ttk.Checkbutton(
            run_box,
            text="img2img",
            variable=self.stage_img2img_var,
            style="Dark.TCheckbutton",
        ).grid(row=0, column=0, sticky="w", pady=(0, 2))
        ttk.Checkbutton(
            run_box,
            text="adetailer",
            variable=self.stage_adetailer_var,
            style="Dark.TCheckbutton",
        ).grid(row=1, column=0, sticky="w", pady=(0, 2))
        ttk.Checkbutton(
            run_box,
            text="upscale",
            variable=self.stage_upscale_var,
            style="Dark.TCheckbutton",
        ).grid(row=2, column=0, sticky="w", pady=(0, 8))

        effective_box = ttk.LabelFrame(
            run_box,
            text="Effective Reprocess Settings",
            style="Dark.TLabelframe",
            padding=8,
        )
        effective_box.grid(row=3, column=0, sticky="ew", pady=(0, 8))
        effective_box.columnconfigure(0, weight=1)
        effective_label = ttk.Label(
            effective_box,
            textvariable=self._effective_settings_var,
            style="Dark.TLabel",
            justify="left",
        )
        effective_label.grid(row=0, column=0, sticky="ew")
        bind_wraplength(effective_label)

        # GUI-COMPLETE-760: wrapping row, so the group-by-model option and its help stay reachable.
        batch_row = FlowRow(run_box, style="Panel.TFrame", gap=8)
        batch_row.grid(row=4, column=0, sticky="ew", pady=(0, 8))
        self._batch_row = batch_row
        batch_row.add(ttk.Label(batch_row, text="Batch size", style="Dark.TLabel"))
        batch_row.add(
            ttk.Spinbox(
                batch_row,
                from_=1,
                to=64,
                increment=1,
                textvariable=self.batch_size_var,
                width=6,
                style="Dark.TSpinbox",
            )
        )
        batch_row.add(
            ttk.Label(batch_row, text="(groups by compatible settings)", style="Dark.TLabel")
        )
        batch_row.add(
            ttk.Checkbutton(
                batch_row,
                text="Order new batch by checkpoint/profile",
                variable=self.group_by_model_var,
                style="Dark.TCheckbutton",
            )
        )
        batch_help_btn = ttk.Button(
            batch_row,
            text="?",
            width=3,
            style="Dark.TButton",
            command=self._show_batch_logic_help,
        )
        batch_row.add(batch_help_btn)
        attach_tooltip(
            batch_help_btn,
            "Batching only combines images with identical effective prompt/model/config. "
            "Different settings are split into separate jobs.",
        )

        edit_row = ttk.Frame(run_box)
        edit_row.grid(row=5, column=0, sticky="ew", pady=(0, 6))
        edit_row.columnconfigure((0, 1), weight=1, uniform="image_edit")
        self._smart_enablement: Any = None
        self.edit_mask_button = ttk.Button(
            edit_row,
            text="Edit Mask…",
            command=self._open_mask_editor,
        )
        self.edit_mask_button.grid(row=0, column=0, sticky="ew", padx=(0, 3))
        self.extend_canvas_button = ttk.Button(
            edit_row,
            text="Extend Canvas…",
            command=self._open_outpaint_editor,
        )
        self.extend_canvas_button.grid(row=0, column=1, sticky="ew", padx=(3, 0))
        self.smart_review_button = ttk.Button(
            edit_row,
            text="Smart Review…",
            command=self._open_smart_review,
        )
        self.smart_review_button.grid(row=1, column=0, columnspan=2, sticky="ew", pady=(4, 0))
        self.inspect_improve_button = ttk.Button(
            edit_row, text="Inspect & Improve…", command=self._open_guided_review
        )
        self.inspect_improve_button.grid(row=2, column=0, columnspan=2, sticky="ew", pady=(4, 0))
        attach_tooltip(
            self.smart_review_button,
            "Opt-in local helpers: click an object to suggest a mask, or get a caption suggestion. "
            "Suggestions only; nothing is edited or queued until you accept and review it.",
        )
        klein_check = ttk.Checkbutton(
            run_box,
            text="FLUX.2 Klein single-reference edit (Forge)",
            variable=self.klein_edit_var,
            style="Dark.TCheckbutton",
        )
        klein_check.grid(row=6, column=0, sticky="w", pady=(6, 0))
        attach_tooltip(
            klein_check,
            "Edit exactly one selected image with FLUX.2 Klein 4B FP8 (img2img only, fixed Euler/Beta/"
            "4 steps/CFG 1.0; the 768x1024 and 1024x1024 sizes are qualified). Requires the Forge "
            "backend. Describe the desired edit in the prompt box; it replaces the prompt.",
        )
        self.klein_check = klein_check
        single_note = ttk.Label(run_box, textvariable=self._single_note_var, style="Dark.TLabel")
        single_note.grid(row=7, column=0, sticky="ew", pady=(6, 0))
        bind_wraplength(single_note)
        self.rework_button = ttk.Button(
            run_box,
            text="Preview and queue...",
            style="Primary.TButton",
            command=self._start_rework,
        )
        self.rework_button.grid(row=8, column=0, sticky="ew", pady=(8, 0))
        self._rework_tooltip = attach_tooltip(
            self.rework_button,
            "Preview the marked images with the checked stages and prompt edits, then queue them through the "
            "existing Review path. Nothing is queued until you confirm the preview.",
        )
        reason = ttk.Label(run_box, textvariable=self._rework_reason_var, style="Dark.TLabel")
        reason.grid(row=9, column=0, sticky="ew", pady=(4, 0))
        bind_wraplength(reason)
        rework.grid_remove()

    def _selected_stages(self) -> list[str]:
        stages: list[str] = []
        if self.stage_img2img_var.get():
            stages.append("img2img")
        if self.stage_adetailer_var.get():
            stages.append("adetailer")
        if self.stage_upscale_var.get():
            stages.append("upscale")
        return stages

    def _on_select_images(self) -> None:
        files = filedialog.askopenfilenames(
            title="Select images to review/reprocess",
            filetypes=[
                ("Image files", "*.png *.jpg *.jpeg *.webp"),
                ("All files", "*.*"),
            ],
        )
        if not files:
            return
        self._set_selected_images([Path(f) for f in files])

    def _on_select_folder(self) -> None:
        folder = filedialog.askdirectory(title="Select folder with images")
        if not folder:
            return
        # The dialog and this capture stay on the UI thread; the recursive walk runs on a worker, a newer folder
        # request (or any other accepted selection) supersedes it, and nothing is published until it is current.
        root = Path(folder)
        token = self._revisions.begin_folder_scan()
        revisions = self._revisions
        skip = (archive_root(self._output_root()),)
        self.selection_label.config(text=f"Scanning {root.name or root} for images...")
        self._work.submit(
            "review:folder-scan",
            lambda: scan_image_folder(
                root, is_cancelled=lambda: not revisions.is_current_folder_scan(token), skip=skip
            ),
            on_result=lambda scan: self._publish_folder_scan(token, scan),
            on_error=lambda exc: self._folder_scan_failed(token, root, exc),
            name="review-folder-scan",
            purpose="Enumerate a Review folder without blocking Tk",
        )

    def _restore_selection_label(self) -> None:
        self.selection_label.config(
            text=selection_label_text(
                len(self._session.items),
                len(self._session.visible_items()),
                FILTER_LABELS[self._session.filter],
            )
        )

    def _publish_folder_scan(self, token: SelectionToken, scan: FolderScan) -> None:
        if not self._revisions.is_current_folder_scan(token) or scan.cancelled:
            return
        self._restore_selection_label()
        skipped = (
            f" {len(scan.unreadable)} folder(s) could not be read and were skipped."
            if scan.unreadable
            else ""
        )
        if scan.too_many:
            self.workflow_hint_label.config(
                text=(
                    f"{scan.root} holds more than {MAX_FOLDER_IMAGES:,} images, so nothing was loaded. "
                    "Choose a subfolder."
                )
            )
            return
        if not scan.paths:
            self.workflow_hint_label.config(
                text=(
                    f"No PNG, JPEG or WebP images were found under {scan.root}; "
                    f"Review's selection was left as it was.{skipped}"
                )
            )
            return
        self._set_selected_images(list(scan.paths), folder=scan.root)
        if skipped:
            self.workflow_hint_label.config(text=f"Loaded {len(scan.paths)} image(s).{skipped}")

    def _folder_scan_failed(self, token: SelectionToken, root: Path, error: Exception) -> None:
        if not self._revisions.is_current_folder_scan(token):
            return
        self._restore_selection_label()
        reason = getattr(error, "strerror", None) or type(error).__name__
        self.workflow_hint_label.config(text=f"Could not scan {root}: {reason}")

    def _begin_selection_context(self, handoff: ReviewWorkspaceHandoff | None) -> None:
        """An incoming selection was accepted: outstanding work of the old context is stale, its claims are gone."""

        self._close_inspection()
        self._revisions.accept_selection()
        self._active_handoff = handoff
        self._pending_overlay = None
        self._edited_since_selection = False
        # A banner about the previous set ("Editing the recorded image of History job ...") ends with that set;
        # whoever accepted the new one writes its own hint afterwards.
        self.workflow_hint_label.config(text=self._default_workflow_hint)

    def _on_clear(self) -> None:
        self._begin_selection_context(None)
        self._session.clear()
        self._image_ready = False
        self.selected_images = []
        self._image_index_by_row = []
        self._row_texts = []
        self._undo_order = []
        self._inspection_undo = []
        self.images_list.delete(0, tk.END)
        self.selection_label.config(text="No images selected")
        self.meta_label.config(text="Metadata: n/a")
        self._selected_base_prompt = ""
        self._selected_base_negative_prompt = ""
        self._selected_image_path = None
        self._selected_image_sha256 = ""
        self._provenance_view = None
        self._baseline_note_var.set("")
        self._reset_rating_controls()
        self._adetailer_pair = None
        self._set_adetailer_controls(False)
        self._reset_mode_edits_for_current_image()
        self._apply_content_visibility_mode()
        self._refresh_prompt_diff()
        self.preview.clear()
        self._compare_mode = "single"
        self._effective_settings_var.set("Effective settings: select an image")
        self._prior_review_summary_var.set("Prior Review Summary: none")
        self.workflow_hint_label.config(text=self._default_workflow_hint)
        self._refresh_workspace_view()

    def _confirm_replace(self, title: str, message: str) -> bool:
        hook = self._confirm_replace_hook
        if callable(hook):
            return bool(hook(title, message))
        return bool(messagebox.askyesno(title, message, parent=self))

    def _confirm_incoming_replacement(self) -> bool:
        """Replace/Cancel, the History handoff's convention, for an incoming selection over unsent Review work."""

        if not self.has_unsent_edits():
            return True
        return self._confirm_replace(
            "Replace Review selection?",
            "Review already holds a selection or edits that have not been queued. "
            "Replace them with the incoming images?",
        )

    def load_staged_curation_handoff(
        self, handoff: ReviewWorkspaceHandoff, *, confirmed: bool = False
    ) -> bool:
        """Load a handoff as Review's selection; False when the operator declined to replace unsent work."""

        image_paths = [Path(path) for path in list(handoff.image_paths or [])]
        if not image_paths:
            raise ValueError("No staged-curation images were provided for Review handoff")
        if not confirmed and not self._confirm_incoming_replacement():
            return False

        self._begin_selection_context(handoff)
        self._apply_selection(image_paths)
        if self._selected_image_path is not None:
            self._pending_overlay = (handoff, self._selected_image_path)
        self.workflow_hint_label.config(text=get_review_handoff_hint(len(image_paths)))

        self.stage_img2img_var.set(bool(handoff.stage_img2img))
        self.stage_adetailer_var.set(bool(handoff.stage_adetailer))
        self.stage_upscale_var.set(bool(handoff.stage_upscale))
        self._apply_handoff_overlay(handoff)
        return True

    def _apply_handoff_overlay(self, handoff: ReviewWorkspaceHandoff) -> None:
        """The handoff's baseline and prompt edits over the image's own baseline (re-applied once its metadata lands)."""

        self._selected_base_prompt = str(handoff.base_prompt or self._selected_base_prompt or "")
        self._selected_base_negative_prompt = str(
            handoff.base_negative_prompt or self._selected_base_negative_prompt or ""
        )
        self._apply_content_visibility_mode()

        prompt_mode = str(handoff.prompt_mode or "append")
        negative_mode = str(handoff.negative_prompt_mode or "append")
        self.prompt_mode_var.set(prompt_mode)
        self.negative_mode_var.set(negative_mode)
        self._prompt_mode_edits = {
            "append": "",
            "replace": "",
            "modify": self._selected_base_prompt,
        }
        self._negative_mode_edits = {
            "append": "",
            "replace": "",
            "modify": self._selected_base_negative_prompt,
        }
        if prompt_mode in self._prompt_mode_edits:
            self._prompt_mode_edits[prompt_mode] = str(handoff.prompt_delta or "")
        if negative_mode in self._negative_mode_edits:
            self._negative_mode_edits[negative_mode] = str(handoff.negative_prompt_delta or "")
        self._prompt_prev_mode = prompt_mode
        self._negative_prev_mode = negative_mode
        self._set_text(self.prompt_text, self._prompt_mode_edits.get(prompt_mode, ""))
        self._set_text(self.negative_text, self._negative_mode_edits.get(negative_mode, ""))
        self._refresh_prompt_diff()

    def has_unsent_edits(self) -> bool:
        """Whether Review holds a selection or prompt edit that an incoming handoff would replace."""

        if self.selected_images:
            return True
        return bool(
            self._get_text(self.prompt_text).strip() or self._get_text(self.negative_text).strip()
        )

    def load_history_iterate_handoff(self, handoff: ReviewWorkspaceHandoff) -> bool:
        """Load one recorded History image as the input of a new reprocess task (PR-HISTORY-610A).

        Stages start unselected and nothing is queued; the handoff's ``history_iterate`` identity rides along in
        ``source_metadata_by_path`` and is verified against the file again when the batch is prepared. History's
        service has already asked Replace/Cancel, so this entry point does not ask a second time.
        """

        paths = list(handoff.image_paths or [])
        if handoff.source != "history_iterate" or len(paths) != 1:
            raise ValueError("A History hand-off carries exactly one recorded image")
        self.load_staged_curation_handoff(handoff, confirmed=True)
        meta = self._lookup_handoff_source_metadata(Path(paths[0])) or {}
        job_id = str(meta.get("source_job_id") or "")
        self.workflow_hint_label.config(
            text=(
                f"Editing the recorded image of History job {job_id}. "
                if job_id
                else "Editing a recorded History image. "
            )
            + "Choose the stages, then Preview; nothing is queued until you confirm."
        )
        return True

    def load_selected_images(
        self,
        image_paths: Sequence[str | Path],
        *,
        status_message: str | None = None,
        confirmed: bool = False,
    ) -> int:
        """Select existing images in Review, in the given order (the Select Images picker's behavior).

        Used by explicit "Open in Review" hand-offs (for example from Queue/History batches or Photo Optimize).
        It only changes the selection, exactly as the Select Images picker does (the first image is shown with its
        own baseline prompt); stage toggles are untouched, and a previous hand-off's source metadata is dropped so
        it cannot attach to unrelated images. Replacing unsent Review work asks Replace/Cancel first; Cancel
        returns 0 and leaves everything as it was. Nothing is queued.
        """

        paths = [Path(path) for path in image_paths]
        if not paths:
            raise ValueError("No images were provided for Review")
        if not confirmed and not self._confirm_incoming_replacement():
            return 0
        self._set_selected_images(paths)
        if status_message:
            # ``{count}`` is what the set actually holds: the same file named twice is listed once, and says so.
            listed = len(self.selected_images)
            text = status_message.replace("{count}", str(listed))
            if listed != len(paths):
                text += f" {len(paths) - listed} duplicate path(s) of an image already listed were skipped."
            self.workflow_hint_label.config(text=text)
        return len(self.selected_images)

    def _set_selected_images(self, paths: list[Path], *, folder: Path | None = None) -> None:
        """Accept ``paths`` as a new manual selection (its own context: no earlier handoff claim applies)."""

        self._begin_selection_context(None)
        self._apply_selection(paths, folder=folder)

    def _apply_selection(self, paths: list[Path], *, folder: Path | None = None) -> None:
        deduped: list[Path] = []
        seen: set[str] = set()
        for path in paths:
            key = str(path.resolve())
            if key in seen:
                continue
            seen.add(key)
            deduped.append(path)

        self._undo_order = []
        self._inspection_undo = []
        self._session.set_items(deduped, folder=folder)
        self.selected_images = self._session.paths()
        self._restore_selection_label()
        first = self._session.visible_items()
        if first:
            self.images_list.selection_clear(0, tk.END)
            self.images_list.selection_set(0)
            if os.path.lexists(first[0].path):
                self._show_image(first[0].path)

    def _on_image_select(self, _event: tk.Event) -> None:
        idxs = self.images_list.curselection()
        if not idxs:
            self._close_inspection()
            return
        idx = int(idxs[0])
        if idx < 0 or idx >= len(self._image_index_by_row):
            return
        self._show_image(self._image_index_by_row[idx])

    def _set_adetailer_controls(self, enabled: bool) -> None:
        """Enable the before/after judgment only for an ADetailer output whose source image is verified."""

        self._adetailer_enabled = bool(enabled)
        self._applying_saved_rating = True
        try:
            self.adetailer_face_outcome_var.set(OUTCOME_LABELS["unreviewed"])
            self.adetailer_hands_outcome_var.set(OUTCOME_LABELS["unreviewed"])
            self.adetailer_outcome_note_var.set("")
        finally:
            self._applying_saved_rating = False
        self._sync_adetailer_widgets()

    def _sync_adetailer_widgets(self) -> None:
        for widget in self._adetailer_outcome_widgets:
            try:
                widget.configure(
                    state=("readonly" if isinstance(widget, ttk.Combobox) else "normal")
                    if self._adetailer_enabled
                    else "disabled"
                )
            except tk.TclError:
                continue  # the compare viewer that hosted it was closed

    def _build_adetailer_outcome(self, frame: ttk.Frame) -> None:
        """The optional before/after judgment, shown inside the ADetailer compare it describes."""

        outcome = ttk.Frame(frame, style="Panel.TFrame")
        outcome.grid(row=4, column=0, columnspan=2, sticky="ew", pady=(8, 0))
        outcome.columnconfigure(3, weight=1)
        ttk.Label(outcome, text="ADetailer outcome (optional)", style="Dark.TLabel").grid(
            row=0, column=0, columnspan=4, sticky="w"
        )
        for column, (label, variable) in enumerate(
            (
                ("Face", self.adetailer_face_outcome_var),
                ("Hands", self.adetailer_hands_outcome_var),
            )
        ):
            ttk.Label(outcome, text=label, style="Dark.TLabel").grid(
                row=1,
                column=column * 2,
                sticky="w",
                padx=(0 if column == 0 else 12, 6),
                pady=(2, 0),
            )
            combo = ttk.Combobox(
                outcome,
                textvariable=variable,
                values=list(OUTCOME_LABELS.values()),
                state="disabled",
                style="Dark.TCombobox",
                width=14,
            )
            combo.grid(row=1, column=column * 2 + 1, sticky="w", pady=(2, 0))
            self._adetailer_outcome_widgets.append(combo)
        note = ttk.Entry(outcome, textvariable=self.adetailer_outcome_note_var, state="disabled")
        note.grid(row=2, column=0, columnspan=4, sticky="ew", pady=(2, 0))
        self._adetailer_outcome_widgets.append(note)
        reason = ttk.Label(outcome, text="", style="Dark.TLabel")
        reason.grid(row=3, column=0, columnspan=4, sticky="w", pady=(2, 0))
        reason.configure(
            text=""
            if self._adetailer_enabled
            else "The source image of this ADetailer output is not verified, so it cannot be judged."
        )
        attach_tooltip(
            outcome,
            "Available for an ADetailer output whose source image is verified. Judge the before/after by region; this "
            "is a post-ADetailer assessment, not an attribution to one pass, and it does not change the overall "
            "rating. It is saved with the rating (Save rating).",
        )
        self._sync_adetailer_widgets()

    def _open_adetailer_compare(self) -> None:
        pair = self._adetailer_pair
        if pair is None:
            messagebox.showinfo(
                "ADetailer Before/After",
                "No verified ADetailer source image for the selected image.",
            )
            return
        self._compare_mode = "adetailer"
        self._render_compare_viewer(
            pair.source,
            secondary_path=pair.output,
            title_prefix="ADetailer Before / After",
            labels=("Before (sent to ADetailer)", "After (ADetailer output)"),
        )

    def _open_contextual_compare(self) -> None:
        """One Compare: the ADetailer before/after, the returned re-work (or its source), a staged-curation
        derived image, or else the large single view, whichever applies to the image shown."""

        path = self._selected_image_path
        if path is None:
            return
        if not PIL_AVAILABLE:
            messagebox.showinfo("Viewer unavailable", "Large compare viewer requires Pillow.")
            return
        if self._adetailer_pair is not None:
            self._open_adetailer_compare()
            return
        if self._open_partner_compare(path):
            return
        if self._open_latest_derived_compare(show_errors=False):
            return
        self._open_compare_viewer()

    def _open_partner_compare(self, path: Path) -> bool:
        partner = self._session.compare_partner(item_key(path))
        if partner is None:
            return False
        other, relation = partner
        self._compare_mode = "partner"
        if relation == "returned":
            self._render_compare_viewer(
                path,
                secondary_path=other,
                title_prefix="Source vs Returned re-work",
                labels=("Source", "Returned re-work"),
            )
        else:
            self._render_compare_viewer(
                other,
                secondary_path=path,
                title_prefix="Source vs Returned re-work",
                labels=("Source", "Returned re-work"),
            )
        return True

    def _refresh_viewer_after_step(self) -> None:
        path = self._selected_image_path
        if path is None:
            return
        if self._compare_mode == "latest_derived":
            self._open_latest_derived_compare(show_errors=False)
        elif self._compare_mode == "partner" and self._open_partner_compare(path):
            return
        else:
            self._compare_mode = "single"
            self._render_compare_viewer(path)

    def _on_prompt_edited(self) -> None:
        self._edited_since_selection = True
        self._refresh_prompt_diff()

    def _prior_summary_getter(self) -> Any:
        controller = self._resolve_learning_controller()
        getter = (
            getattr(controller, "get_prior_review_summary", None)
            if controller is not None
            else None
        )
        return getter if callable(getter) else None

    def _show_image(self, path: Path) -> None:
        """Show ``path`` now (preview) and fill its metadata when the worker finishes, if it is still the latest."""

        self._close_inspection()
        token = self._revisions.begin_image(str(path))
        overlay = self._pending_overlay
        if overlay is not None and overlay[1] != path:
            self._pending_overlay = None
        if self._show_archived_image(path):
            return
        self._selected_image_path = path
        self._selected_image_sha256 = ""
        self._reset_rating_controls()
        if self._rating_status_shown:
            # "Saved N feedback record(s)..." is about the image that was rated; it must not stay under another one.
            self._rating_status_shown = False
            self._feedback_status_var.set(self._session.archive_line(item_key(path)))
        self._image_ready = False
        self._edited_since_selection = False
        self._adetailer_pair = None
        self._set_adetailer_controls(False)
        self.preview.set_eligibility(self._content_visibility_mode != "sfw")
        self.preview.set_image_from_path(path)
        self.meta_label.config(text="Metadata: loading...")
        self._prior_review_summary_var.set("Prior Review Summary: loading...")
        self._selected_base_prompt = ""
        self._selected_base_negative_prompt = ""
        self._provenance_view = None
        self._baseline_note_var.set("")
        self._reset_mode_edits_for_current_image()
        self._apply_content_visibility_mode()
        self._refresh_decision_controls()
        getter = self._prior_summary_getter()
        self._work.submit(
            "review:image-context",
            lambda: load_image_context(
                path,
                prior_summary_getter=getter,
                extract_metadata=extract_embedded_metadata,
                resolve_pair=resolve_adetailer_pair,
            ),
            on_result=lambda context: self._publish_image_context(token, context),
            on_error=lambda exc: self._image_context_failed(token, exc),
            name="review-image-context",
            purpose="Read embedded metadata and prior review for the selected Review image",
        )

    def _show_archived_image(self, path: Path) -> bool:
        """An archived image has no file at its path: say where it is instead of trying to load it."""

        key = item_key(path)
        facts = self._session.facts_of(key)
        if (
            os.path.lexists(path)
            or facts.location != LOC_ARCHIVED
            or self._session.state_of(key) is not ItemState.ARCHIVED
        ):
            return False
        self._selected_image_path = path
        self._selected_image_sha256 = facts.digest
        self._reset_rating_controls()
        self._image_ready = False
        self._edited_since_selection = False
        self._adetailer_pair = None
        self._set_adetailer_controls(False)
        self.preview.clear()
        self.meta_label.config(text="Metadata: n/a (archived)")
        self._prior_review_summary_var.set("Prior Review Summary: restore this image to review it")
        self._selected_base_prompt = ""
        self._selected_base_negative_prompt = ""
        self._provenance_view = None
        self._baseline_note_var.set("")
        self._reset_mode_edits_for_current_image()
        self._apply_content_visibility_mode()
        self._refresh_decision_controls()
        self._feedback_status_var.set(self._session.archive_line(key))
        return True

    def _publish_image_context(self, token: SelectionToken, context: ImageContext) -> None:
        if not self._revisions.is_current_image(token) or self._selected_image_path != context.path:
            return
        self._image_ready = True
        self._selected_image_sha256 = context.artifact_sha256
        self._adetailer_pair = context.adetailer_pair
        self._set_adetailer_controls(context.adetailer_pair is not None)
        if context.prior_summary_available:
            self._load_saved_rating(context.prior_summary)
            self._prior_review_summary_var.set(
                self._format_prior_review_summary(context.prior_summary)
            )
        else:
            self._prior_review_summary_var.set("Prior Review Summary: unavailable")
        overlay, self._pending_overlay = self._pending_overlay, None
        if context.metadata_ok:
            self._selected_base_prompt = context.prompt
            self._selected_base_negative_prompt = context.negative_prompt
        else:
            self._selected_base_prompt = ""
            self._selected_base_negative_prompt = ""
        if not self._edited_since_selection:
            self._reset_mode_edits_for_current_image()
            if overlay is not None:
                self._apply_handoff_overlay(overlay[0])
        elif overlay is not None:
            self._selected_base_prompt = str(overlay[0].base_prompt or self._selected_base_prompt)
            self._selected_base_negative_prompt = str(
                overlay[0].base_negative_prompt or self._selected_base_negative_prompt
            )
        self._provenance_view = (
            project_effective_prompts(context.payload)
            if context.metadata_ok and isinstance(context.payload, dict)
            else None
        )
        self._baseline_note_var.set(
            self._provenance_view.baseline_label if self._provenance_view is not None else ""
        )
        self._apply_content_visibility_mode()
        self._refresh_prompt_diff()
        if not context.metadata_ok:
            self.meta_label.config(text=f"Metadata: {context.metadata_status}")
            return
        preview_prompt = context.prompt.strip()
        if len(preview_prompt) > 120:
            preview_prompt = f"{preview_prompt[:117]}..."
        resolver = self._visibility_resolver()
        self.meta_label.config(
            text=(
                f"Metadata: ok | model={context.model or 'n/a'} | vae={context.vae or 'n/a'}\n"
                f"Prompt: {resolver.redact_text(preview_prompt, item=self._current_visibility_subject()) or '(empty)'}"
            )
        )

    def _image_context_failed(self, token: SelectionToken, error: Exception) -> None:
        if not self._revisions.is_current_image(token):
            return
        self._image_ready = True
        self._provenance_view = None
        self._prior_review_summary_var.set("Prior Review Summary: unavailable")
        self.meta_label.config(text=f"Metadata: unavailable ({type(error).__name__})")
        self._render_provenance()
        self._refresh_prompt_diff()

    def _mark_rating_touched(self, *_args: object) -> None:
        if not self._applying_saved_rating:
            self._rating_touched = True

    def _reset_rating_controls(self) -> None:
        """Show the unrated state, so one image never displays the previous image's rating."""

        self._applying_saved_rating = True
        try:
            for var in (
                self.rating_var,
                self.anatomy_rating_var,
                self.composition_rating_var,
                self.prompt_adherence_rating_var,
            ):
                var.set(3)
            self.quality_var.set("okay")
            self.feedback_notes.delete("1.0", tk.END)
        finally:
            self._applying_saved_rating = False
        self._rating_touched = False

    def _load_saved_rating(self, summary: Any) -> None:
        """Fill the rating controls from the saved review of the shown bytes (not when it was for other bytes)."""

        if (
            not isinstance(summary, dict)
            or summary.get("identity_status") == "changed"
            or self._rating_touched
            or summary.get("user_rating_raw") is None
        ):
            return
        raw_subscores = summary.get("subscores")
        subscores: dict[str, Any] = raw_subscores if isinstance(raw_subscores, dict) else {}
        self._applying_saved_rating = True
        try:
            values: tuple[tuple[tk.IntVar, Any], ...] = (
                (self.rating_var, summary.get("user_rating_raw")),
                (self.anatomy_rating_var, subscores.get("anatomy")),
                (self.composition_rating_var, subscores.get("composition")),
                (self.prompt_adherence_rating_var, subscores.get("prompt_adherence")),
            )
            for var, value in values:
                try:
                    var.set(max(1, min(5, int(value))))
                except (TypeError, ValueError):
                    continue
            if str(summary.get("quality_label") or "") in (
                "reject",
                "poor",
                "okay",
                "good",
                "excellent",
            ):
                self.quality_var.set(str(summary["quality_label"]))
            if not self.feedback_notes.get("1.0", tk.END).strip():
                self.feedback_notes.insert("1.0", str(summary.get("user_notes") or ""))
        finally:
            self._applying_saved_rating = False

    def _refresh_prior_review_summary(self, image_path: Path) -> None:
        learning_controller = self._resolve_learning_controller()
        getter = (
            getattr(learning_controller, "get_prior_review_summary", None)
            if learning_controller is not None
            else None
        )
        if not callable(getter):
            self._prior_review_summary_var.set("Prior Review Summary: unavailable")
            return
        try:
            summary = getter(str(image_path))
        except Exception:
            self._prior_review_summary_var.set("Prior Review Summary: unavailable")
            return
        self._prior_review_summary_var.set(self._format_prior_review_summary(summary))

    @staticmethod
    def _format_prior_review_summary(summary: Any) -> str:
        if not isinstance(summary, dict):
            return "Prior Review Summary: none"
        source_type = str(summary.get("source_type") or "unknown")
        source_label_map = {
            "internal_learning_record": "internal learning record",
            "embedded_review_metadata": "embedded artifact metadata",
            "sidecar_review_metadata": "sidecar artifact metadata",
        }
        source_label = source_label_map.get(source_type, source_type.replace("_", " "))
        rating = summary.get("user_rating")
        quality = str(summary.get("quality_label") or "")
        timestamp = str(summary.get("review_timestamp") or "")
        notes = str(summary.get("user_notes") or "").strip()
        prompt_mode = str(summary.get("prompt_mode") or "").strip()
        prompt_changed = bool(
            str(summary.get("prompt_delta") or "").strip()
            or str(summary.get("negative_prompt_delta") or "").strip()
            or str(summary.get("prompt_before") or "").strip()
            != str(summary.get("prompt_after") or "").strip()
            or str(summary.get("negative_prompt_before") or "").strip()
            != str(summary.get("negative_prompt_after") or "").strip()
        )
        bits = [f"Source: {source_label}"]
        if summary.get("identity_status") == "changed":
            bits.append(
                "This file changed since it was reviewed; the rating below was for its earlier content."
            )
        if rating is not None:
            rating_text = f"Rating: {rating}"
            if quality:
                rating_text += f" ({quality})"
            bits.append(rating_text)
        elif quality:
            bits.append(f"Quality: {quality}")
        if timestamp:
            bits.append(f"Reviewed: {timestamp}")
        if notes:
            trimmed = notes if len(notes) <= 120 else f"{notes[:117]}..."
            bits.append(f"Notes: {trimmed}")
        bits.append(f"Prompt change: {prompt_mode or ('yes' if prompt_changed else 'no')}")
        return "\n".join(bits)

    def _show_previous_image(self) -> None:
        self._step_selected_image(-1)

    def _show_next_image(self) -> None:
        self._step_selected_image(1)

    def _step_selected_image(self, delta: int) -> None:
        if not self._image_index_by_row:
            return
        current = self.images_list.curselection()
        current_index = int(current[0]) if current else 0
        next_index = max(0, min(len(self._image_index_by_row) - 1, current_index + int(delta)))
        self.images_list.selection_clear(0, tk.END)
        self.images_list.selection_set(next_index)
        self.images_list.activate(next_index)
        self.images_list.see(next_index)
        self._show_image(self._image_index_by_row[next_index])

    def _open_compare_viewer(self) -> None:
        image_path = self._selected_image_path
        if image_path is None:
            return
        if not PIL_AVAILABLE:
            messagebox.showinfo("Viewer unavailable", "Large compare viewer requires Pillow.")
            return
        self._compare_mode = "single"
        self._render_compare_viewer(image_path)

    def _open_metadata_inspector(self) -> None:
        image_path = self._selected_image_path
        if image_path is None:
            messagebox.showinfo("Metadata Inspector", "Select an image first.")
            return
        if not os.path.lexists(image_path) and (
            self._session.facts_of(item_key(image_path)).location == LOC_ARCHIVED
            or archived_reason(image_path)
        ):
            # The file is in the archive folder, not at this path: say so instead of showing an empty summary.
            messagebox.showinfo(
                "Metadata Inspector", f"This image was {ARCHIVED_MESSAGE}.", parent=self
            )
            return
        learning_controller = self._resolve_learning_controller()
        inspector = (
            getattr(learning_controller, "inspect_artifact_metadata", None)
            if learning_controller is not None
            else None
        )
        if not callable(inspector):
            messagebox.showerror("Metadata Inspector", "Metadata inspector is unavailable.")
            return

        def _refresh() -> dict[str, Any] | None:
            refreshed = inspector(str(image_path))
            return dict(refreshed) if isinstance(refreshed, dict) else None

        try:
            payload = inspector(str(image_path))
        except Exception as exc:
            messagebox.showerror("Metadata Inspector", str(exc))
            return
        if not isinstance(payload, dict):
            messagebox.showerror("Metadata Inspector", "Inspector returned an invalid payload.")
            return
        ArtifactMetadataInspectorDialog(self, inspection_payload=payload, on_refresh=_refresh)

    def _lookup_handoff_source_metadata(self, image_path: Path) -> dict[str, Any] | None:
        handoff = self._active_handoff
        if handoff is None:
            return None
        source_map = dict(getattr(handoff, "source_metadata_by_path", {}) or {})
        return source_map.get(str(image_path)) or source_map.get(str(image_path.resolve()))

    def _get_selected_latest_derived_descendant(self) -> dict[str, Any] | None:
        image_path = self._selected_image_path
        if image_path is None:
            return None
        source_metadata = self._lookup_handoff_source_metadata(image_path)
        selection_meta = (
            source_metadata.get("curation_source_selection")
            if isinstance(source_metadata, dict)
            else None
        )
        if not isinstance(selection_meta, dict):
            return None
        candidate_id = str(selection_meta.get("candidate_id") or "").strip()
        if not candidate_id:
            return None
        learning_controller = self._resolve_learning_controller()
        if learning_controller is None:
            return None
        getter = getattr(
            learning_controller, "get_staged_curation_candidate_latest_descendant", None
        )
        if not callable(getter):
            return None
        latest = getter(candidate_id)
        return latest if isinstance(latest, dict) else None

    def _open_latest_derived_compare(self, *, show_errors: bool = True) -> bool:
        image_path = self._selected_image_path
        if image_path is None:
            if show_errors:
                messagebox.showinfo(
                    "Compare unavailable", "Select a staged-curation source image first."
                )
            return False
        if not PIL_AVAILABLE:
            if show_errors:
                messagebox.showinfo("Viewer unavailable", "Large compare viewer requires Pillow.")
            return False
        latest = self._get_selected_latest_derived_descendant()
        latest_path_value = str((latest or {}).get("artifact_path") or "").strip()
        if not latest_path_value:
            if show_errors:
                messagebox.showinfo(
                    "No latest derived",
                    "No derived descendant has been found yet for the selected staged-curation source.",
                )
            return False
        self._compare_mode = "latest_derived"
        target_stage = str((latest or {}).get("target_stage") or "derived").replace("_", " ")
        self._render_compare_viewer(
            image_path,
            secondary_path=Path(latest_path_value),
            title_prefix=f"Source vs Latest Derived ({target_stage})",
        )
        return True

    def open_staged_candidate_latest_derived_compare(
        self,
        *,
        image_path: Path,
        candidate_id: str,
        workflow_title: str = "",
    ) -> bool:
        self.load_staged_curation_handoff(
            ReviewWorkspaceHandoff(
                source="staged_curation",
                workflow_title=workflow_title,
                target_stage="",
                image_paths=[image_path],
                base_prompt="",
                base_negative_prompt="",
                prompt_delta="",
                negative_prompt_delta="",
                prompt_mode="append",
                negative_prompt_mode="append",
                stage_img2img=False,
                stage_adetailer=False,
                stage_upscale=False,
                source_candidate_ids=[candidate_id],
                source_metadata_by_path={
                    str(image_path): {
                        "curation_source_selection": {
                            "candidate_id": candidate_id,
                        }
                    }
                },
            )
        )
        return self._open_latest_derived_compare()

    def _render_compare_viewer(
        self,
        image_path: Path,
        *,
        secondary_path: Path | None = None,
        title_prefix: str = "Large Compare",
        labels: tuple[str, str] = ("Source", "Latest derived"),
    ) -> None:
        """Open or refresh the viewer now and fill it when the worker's bounded decode finishes (latest wins)."""

        token = self._revisions.begin_compare(str(image_path))
        compare_label = f"{labels[0]}: {image_path.name}"
        if secondary_path is not None:
            compare_label += f"    {labels[1]}: {secondary_path.name}"
        status = tk.StringVar(master=self, value=f"{compare_label}    Loading...")
        viewer, canvas = self._build_compare_shell(f"{title_prefix} - {image_path.name}", status)
        self._work.submit(
            "review:compare",
            lambda: prepare_compare(image_path, secondary_path),
            on_result=lambda prepared: self._publish_compare(
                token, viewer, canvas, status, compare_label, prepared
            ),
            on_error=lambda exc: self._compare_failed(token, status, exc),
            name="review-compare",
            purpose="Decode and composite the Review comparison image without blocking Tk",
        )

    def _build_compare_shell(
        self, title: str, status: tk.StringVar
    ) -> tuple[tk.Toplevel, tk.Canvas]:
        if self._compare_window and self._compare_window.winfo_exists():
            viewer = self._compare_window
            for child in viewer.winfo_children():
                child.destroy()
        else:
            viewer = tk.Toplevel(self)
            self._compare_window = viewer
            apply_toplevel_theme(viewer)
            viewer.bind("<Left>", lambda _event: self._show_previous_image_and_refresh_viewer())
            viewer.bind("<Right>", lambda _event: self._show_next_image_and_refresh_viewer())
            viewer.bind("<Escape>", lambda _event: viewer.destroy())

            def on_destroy(event: tk.Event, window: tk.Toplevel = viewer) -> None:
                self._on_compare_closed(event, window)

            viewer.bind("<Destroy>", on_destroy, add="+")

        viewer.title(title)
        viewer.transient(self.winfo_toplevel())
        viewer.resizable(True, True)
        viewer.minsize(720, 520)

        frame = ttk.Frame(viewer, padding=6)
        frame.pack(fill=tk.BOTH, expand=True)
        frame.columnconfigure(0, weight=1)
        frame.rowconfigure(
            2, weight=1
        )  # the canvas row takes the space (row 1 is the one-line status)

        nav = ttk.Frame(frame, style="Panel.TFrame")
        nav.grid(row=0, column=0, sticky="ew", pady=(0, 6))
        ttk.Button(
            nav,
            text="Prev",
            style="Dark.TButton",
            command=self._show_previous_image_and_refresh_viewer,
        ).pack(side="left")
        ttk.Button(
            nav, text="Next", style="Dark.TButton", command=self._show_next_image_and_refresh_viewer
        ).pack(side="left", padx=(6, 0))
        ttk.Label(
            nav,
            text="Left/Right arrows cycle through the loaded review images",
            style="Dark.TLabel",
        ).pack(side="left", padx=(12, 0))

        ttk.Label(
            frame,
            textvariable=status,
            style="Dark.TLabel",
            justify="left",
        ).grid(row=1, column=0, sticky="w", pady=(0, 6))

        canvas = tk.Canvas(frame, bg=TOKENS.colors.surface_secondary, highlightthickness=0)
        style_canvas_widget(canvas, elevated=True)
        canvas.grid(row=2, column=0, sticky="nsew")
        v_scroll = ttk.Scrollbar(frame, orient=tk.VERTICAL, command=canvas.yview)
        h_scroll = ttk.Scrollbar(frame, orient=tk.HORIZONTAL, command=canvas.xview)
        canvas.configure(yscrollcommand=v_scroll.set, xscrollcommand=h_scroll.set)
        v_scroll.grid(row=2, column=1, sticky="ns")
        h_scroll.grid(row=3, column=0, sticky="ew")

        self._adetailer_outcome_widgets = []
        if self._compare_mode == "adetailer":
            self._build_adetailer_outcome(frame)
        self._compare_canvas = canvas
        self._compare_photo = None
        viewer.lift()
        viewer.focus_force()
        return viewer, canvas

    def _on_compare_closed(self, event: tk.Event, window: tk.Toplevel) -> None:
        if event.widget is not window:
            return  # a child widget of the viewer was rebuilt; the viewer itself is still open
        self._revisions.close_compare()
        if self._compare_window is window:
            self._compare_window = None
            self._compare_canvas = None
            self._compare_photo = None

    def _publish_compare(
        self,
        token: SelectionToken,
        viewer: tk.Toplevel,
        canvas: tk.Canvas,
        status: tk.StringVar,
        compare_label: str,
        prepared: PreparedCompare,
    ) -> None:
        if not self._revisions.is_current_compare(token) or self._compare_canvas is not canvas:
            return
        if not viewer.winfo_exists():
            return
        image_width, image_height = prepared.image.size
        photo = ImageTk.PhotoImage(prepared.image)
        self._compare_photo = photo
        canvas.create_image(0, 0, image=photo, anchor="nw")
        canvas.configure(scrollregion=(0, 0, image_width, image_height))
        status.set(
            compare_label
            + ("    (scaled to fit; the files are unchanged)" if prepared.scaled else "")
        )
        width = min(max(image_width + 60, 960), int(viewer.winfo_screenwidth() * 0.92))
        height = min(max(image_height + 120, 720), int(viewer.winfo_screenheight() * 0.92))
        viewer.geometry(f"{width}x{height}")

    def _compare_failed(
        self, token: SelectionToken, status: tk.StringVar, error: Exception
    ) -> None:
        if not self._revisions.is_current_compare(token):
            return
        reason = str(error) if isinstance(error, CompareImageError) else f"{type(error).__name__}"
        status.set(f"Comparison unavailable: {reason}")

    def destroy(self) -> None:
        self._session.close()
        for sequence, funcid in self._workspace_keys:
            try:
                self.winfo_toplevel().unbind(sequence, funcid)
            except tk.TclError:
                pass
        self._workspace_keys.clear()
        if self._poll_id is not None:
            try:
                self.after_cancel(self._poll_id)
            except (tk.TclError, ValueError):
                pass
            self._poll_id = None
        self._work.close()
        self._revisions.close_compare()
        super().destroy()

    def _show_previous_image_and_refresh_viewer(self) -> None:
        self._step_selected_image(-1)
        self._refresh_viewer_after_step()

    def _show_next_image_and_refresh_viewer(self) -> None:
        self._step_selected_image(1)
        self._refresh_viewer_after_step()

    def _on_import_selected_to_staged_curation(self) -> None:
        learning_controller = self._resolve_learning_controller()
        if learning_controller is None:
            messagebox.showerror("Learning unavailable", "Learning controller is not connected.")
            return
        selected = self._get_selected_review_paths()
        if not selected:
            messagebox.showwarning("No selection", "Select one or more images to import.")
            return
        importer = getattr(learning_controller, "import_review_images_to_staged_curation", None)
        if not callable(importer):
            messagebox.showerror(
                "Unsupported",
                "Connected learning controller does not support staged-curation import.",
            )
            return
        group_id = importer(
            [str(path) for path in selected], display_name=self._build_import_display_name(selected)
        )
        if not group_id:
            messagebox.showerror(
                "Import failed", "Unable to build a staged-curation group from the selected images."
            )
            return
        messagebox.showinfo(
            "Imported",
            f"Imported {len(selected)} image(s) into Staged Curation.\nGroup: {group_id}",
        )

    def _find_history_entry(self, job_id: str) -> JobHistoryEntry | None:
        history_items = list(getattr(self.app_state, "history_items", []) or [])
        for entry in history_items:
            if str(getattr(entry, "job_id", "") or "") == str(job_id or ""):
                return entry
        return None

    def _history_entry_summary(self, entry: JobHistoryEntry) -> str:
        prompt_pack_id = str(getattr(entry, "prompt_pack_id", "") or "").strip()
        if prompt_pack_id:
            return prompt_pack_id
        payload_summary = str(getattr(entry, "payload_summary", "") or "").strip()
        return payload_summary[:80] if payload_summary else "History job"

    def _close_inspection(self) -> None:
        inspection = getattr(self, "_inspection", None)
        if inspection is not None and inspection.winfo_exists():
            inspection.destroy()
        self._inspection = None

    def _open_guided_review(self) -> None:
        from src.gui.guided_review_dialog import GuidedReviewDialog

        target = self._single_tool_path("Inspect & Improve")
        if target is None:
            return
        path = self._selected_image_path
        if (
            path is None
            or target != path
            or not self.preview.model.renderable
            or self.app_controller is None
            or not self._image_ready
        ):
            messagebox.showinfo(
                "Inspect & Improve", "Select and show one still image in Review.", parent=self
            )
            return
        if self._inspection is not None and self._inspection.winfo_exists():
            self._inspection.lift()
            return
        token = self._revisions.current_image(str(path))

        def current() -> bool:
            return bool(
                self.winfo_exists()
                and self._revisions.is_current_image(token)
                and self._selected_image_path == path
                and self.preview.model.renderable
                and self._visibility_resolver().is_visible(self._current_visibility_subject())
            )

        self._inspection = GuidedReviewDialog(
            self,
            path=path,
            revision=(token.selection, token.image),
            current=current,
            save=self._save_feedback,
            save_inspection=self._write_inspection if self._bind_writer() is not None else None,
            inspection_saved=self._inspection_saved,
        )

    def _open_mask_editor(self, *, shown: bool = False) -> None:
        from src.controller.masked_edit_service import history_lineage_for
        from src.gui.mask_editor_dialog import MaskEditorDialog

        path = self._shown_tool_path("Edit Mask") if shown else self._single_tool_path("Edit Mask")
        if path is None:
            return
        if self.app_controller is None:
            messagebox.showwarning(
                "Edit Mask", "The application controller is unavailable.", parent=self
            )
            return
        MaskEditorDialog(
            self,
            source_path=path,
            controller=self.app_controller,
            lineage=history_lineage_for(getattr(self, "_active_handoff", None), path),
        )

    def _open_smart_review(self) -> None:
        from src.gui.smart_review_dialog import SmartReviewDialog, TextDraft
        from src.review.assist.session import AssistEnablement

        path = self._single_tool_path("Smart Review")
        if path is None:
            return
        if self.app_controller is None:
            messagebox.showwarning(
                "Smart Review", "The application controller is unavailable.", parent=self
            )
            return
        if self._smart_enablement is None:
            self._smart_enablement = (
                AssistEnablement()
            )  # session-scoped; every capability starts off
        SmartReviewDialog(
            self,
            source_path=path,
            controller=self.app_controller,
            enablement=self._smart_enablement,
            prompt_binding=TextDraft(self.prompt_text, self._refresh_prompt_diff),
            visibility_mode=lambda: self._content_visibility_mode,
            draft_current=lambda: self._single_target_path() == path,
        )

    def _open_outpaint_editor(self, *, shown: bool = False) -> None:
        from src.controller.masked_edit_service import history_lineage_for
        from src.gui.outpaint_dialog import OutpaintDialog

        path = (
            self._shown_tool_path("Extend Canvas")
            if shown
            else self._single_tool_path("Extend Canvas")
        )
        if path is None:
            return
        if self.app_controller is None:
            messagebox.showwarning(
                "Extend Canvas", "The application controller is unavailable.", parent=self
            )
            return
        OutpaintDialog(
            self,
            source_path=path,
            controller=self.app_controller,
            lineage=history_lineage_for(getattr(self, "_active_handoff", None), path),
        )

    def _get_selected_review_paths(self) -> list[Path]:
        idxs = list(self.images_list.curselection())
        if not idxs and self._selected_image_path is not None:
            return [self._selected_image_path]
        paths: list[Path] = []
        for idx in idxs:
            if 0 <= int(idx) < len(self._image_index_by_row):
                paths.append(self._image_index_by_row[int(idx)])
        return paths

    def _highlighted_image_paths(self) -> list[Path]:
        """The Images list's explicit selection in list order (never the merely previewed image)."""

        return [
            self._image_index_by_row[int(idx)]
            for idx in self.images_list.curselection()
            if 0 <= int(idx) < len(self._image_index_by_row)
        ]

    def _on_manage_selected_photos(self) -> None:
        """Offer the Listbox's highlighted rows (in list order) to the Managed Photo Set.

        Distinct from Quick Edit: this is an import into persistent managed assets that Photo Optimize plans and
        the operator confirms. Only file paths travel; Review's selection, edits, History identity and staged
        hand-off stay exactly as they are, and no lineage is attached to the managed photo."""

        paths = self._highlighted_image_paths()
        if not paths:
            messagebox.showinfo(
                "Manage Selected Photos",
                "Select one or more images in the Images list first.",
            )
            return
        main_window = getattr(self.app_controller, "main_window", None)
        if main_window is None:
            messagebox.showerror("Manage Selected Photos", "The main window is not available.")
            return
        from src.gui.controllers.video_workspace_handoff import route_images_to_photo_optimize

        try:
            route_images_to_photo_optimize(
                main_window=main_window,
                image_paths=paths,
                status_message=f"Checking {len(paths)} image(s) from Quick Edit for the Managed Photo Set...",
            )
        except (RuntimeError, ValueError) as exc:
            messagebox.showerror("Manage Selected Photos", str(exc))

    # -- PR-REVIEW-LIFECYCLE-621: the workspace -------------------------------------------------------------------

    def _resolve_evidence_writer(self) -> Any | None:
        """The one Learning evidence writer (owned by the Learning tab); ``None`` when Learning is not connected."""

        controller = self._resolve_learning_controller()
        if controller is None:
            return None
        return getattr(controller, "learning_record_writer", None) or getattr(
            controller, "_learning_record_writer", None
        )

    def _evidence_records_path(self) -> Path | None:
        records = getattr(self._resolve_evidence_writer(), "records_path", None)
        return Path(records) if records else None

    def _review_repository(self) -> Any:
        return repository_of(self.app_controller)

    def _bind_writer(self) -> Any | None:
        """Resolve the writer (and the archive's output root and job queue) on the Tk thread for the worker."""

        self._writer = self._resolve_evidence_writer()
        self._archive_context = (self._output_root(), job_queue_of(self.app_controller))
        repository = self._review_repository()
        self._batch_of_job = (
            batch_of_job_reader(repository, batch_identity) if repository is not None else None
        )
        return self._writer

    def _output_root(self) -> Path:
        return configured_output_root(getattr(self.app_controller, "_config_manager", None))

    def _archive_on_worker(self, path: Path, _digest: str) -> ArchiveOutcome:
        """Discard's file move; runs on the Review worker with the context bound on the Tk thread."""

        root, queue = self._archive_context

        def unreadable() -> set[str]:
            raise RuntimeError("the job queue is not reachable")

        # With a controller but no reachable queue the move is refused (fail closed); with no controller at all
        # (a bare tab) there is no queue that could be using the file.
        active = (
            (lambda: active_input_paths(queue))
            if queue is not None
            else (unreadable if self.app_controller is not None else None)
        )
        return archive_file(path, output_root=root, active_inputs=active)

    def _restore_on_worker(self, path: Path, digest: str, use_alternative: bool) -> ArchiveOutcome:
        root, _queue = self._archive_context
        return restore_file(
            path, output_root=root, digest=digest or None, use_alternative=use_alternative
        )

    def _write_disposition(self, path: Path, digest: str, job_id: str, disposition: str) -> Any:
        writer = self._writer
        if writer is None:
            raise OSError("Learning evidence is not connected, so the decision cannot be recorded.")
        return save_disposition(
            writer,
            image_path=path,
            disposition=disposition,
            artifact_sha256=digest or None,
            source_job_id=job_id,
            batch_of_job=self._batch_of_job,
        )

    def _write_inspection(self, draft: InspectionDraft) -> Any:
        """Blocking (runs on the dialog's worker): append one inspection through the one evidence writer."""

        writer = self._writer
        if writer is None:
            raise OSError(
                "Learning evidence is not connected, so the inspection cannot be recorded."
            )
        return save_inspection(
            writer,
            image_path=draft.image_path,
            verdict=draft.verdict,
            findings=draft.findings,
            subject_count=draft.subject_count,
            artifact_sha256=draft.artifact_sha256,
            image_size=draft.image_size,
        )

    def _inspection_saved(self, draft: InspectionDraft) -> None:
        """Tk thread, after the write was confirmed: show the verdict on the image's row and make it undoable."""

        self._inspection_undo.append((draft.image_path, draft.artifact_sha256))
        self._undo_order.append("inspection")
        self._session.note_inspection(item_key(draft.image_path), draft.verdict)
        self._feedback_status_var.set(
            f"Saved inspection ({INSPECTION_LABELS[draft.verdict]}) for {Path(draft.image_path).name}. "
            "The image file was not changed and no job was queued."
        )

    def _undo_last_inspection(self) -> None:
        """Record a clearing row for the last saved inspection; the earlier rows stay (nothing is deleted)."""

        if not self._inspection_undo:
            self._feedback_status_var.set("Nothing to undo.")
            return
        writer = self._bind_writer()
        if writer is None:
            self._feedback_status_var.set(
                "Learning evidence is not connected, so Undo cannot be recorded."
            )
            return
        entry = self._inspection_undo.pop()
        self._discard_undo_marker("inspection")
        path, digest = entry

        def work() -> None:
            clear_inspection(writer, image_path=path, artifact_sha256=digest)

        def done(_unused: None) -> None:
            if self.winfo_exists():
                self._session.note_inspection(item_key(path), "")
                self._feedback_status_var.set(
                    "Undid the saved inspection (a clearing row was recorded; nothing was deleted)."
                )

        def failed(error: Exception) -> None:
            self._inspection_undo.append(entry)
            self._undo_order.append("inspection")
            if self.winfo_exists():
                self._feedback_status_var.set(f"The inspection was not undone: {error}")

        self._work.submit(
            "review:undo-inspection",
            work,
            on_result=done,
            on_error=failed,
            name="review-undo-inspection",
            purpose="Record a clearing row for the last saved Review inspection",
        )

    def _on_session_changed(self) -> None:
        self._refresh_workspace_view()
        if self._session.restore_offer is not None and self._offer_after is None:
            self._offer_after = self.after(0, self._offer_restore_alternative)

    def _offer_restore_alternative(self) -> None:
        """The original location is taken by a different file: ask once whether to restore under a new name."""

        self._offer_after = None
        offer = self._session.take_restore_offer()
        if offer is None or not self.winfo_exists():
            return
        hook = self._confirm_alternative_hook
        name = offer.alternative.name
        accepted = (
            bool(hook(name))
            if callable(hook)
            else messagebox.askyesno(
                "Restore under a new name?",
                f"A different file now exists at the original location. Restore the archived image as {name}?",
                parent=self,
            )
        )
        if accepted:
            self._bind_writer()
            self._session.restore(offer.key, use_alternative=True)

    def _current_key(self) -> str | None:
        return (
            item_key(self._selected_image_path) if self._selected_image_path is not None else None
        )

    def _discard_undo_marker(self, marker: str) -> None:
        for index in range(len(self._undo_order) - 1, -1, -1):
            if self._undo_order[index] == marker:
                del self._undo_order[index]
                return

    def _refresh_workspace_view(self) -> None:
        if not self.winfo_exists():
            return
        session = self._session
        self.selected_images = session.paths()
        self._refresh_list()
        if not str(self.selection_label.cget("text")).startswith("Scanning"):
            self._restore_selection_label()
        counts = session.counts_text() if session.items else ""
        if session.loading and session.items:
            counts += "  (reading review state...)"
        self.counts_label.config(text=counts)
        label = FILTER_LABELS[session.filter]
        if self.filter_var.get() != label:
            self.filter_var.set(label)
        message = session.message
        if message != self._last_session_message:
            self._last_session_message = message
            if message:
                self._feedback_status_var.set(message)
        self._refresh_rework_region()
        self._refresh_returned()
        self._refresh_decision_controls()
        self._schedule_poll()

    def _refresh_list(self) -> None:
        visible = self._session.visible_items()
        paths = [item.path for item in visible]
        texts = [self._session.row_text(item) for item in visible]
        box = self.images_list
        if paths == self._image_index_by_row:
            for index, (old, new) in enumerate(zip(self._row_texts, texts, strict=False)):
                if old != new:
                    selected = bool(box.selection_includes(index))
                    box.delete(index)
                    box.insert(index, new)
                    if selected:
                        box.selection_set(index)
            self._row_texts = texts
            return
        previously = {
            item_key(self._image_index_by_row[int(index)])
            for index in box.curselection()
            if 0 <= int(index) < len(self._image_index_by_row)
        }
        shown = self._current_key()
        box.delete(0, tk.END)
        for text in texts:
            box.insert(tk.END, text)
        self._image_index_by_row = paths
        self._row_texts = texts
        for index, item in enumerate(visible):
            if item.key in previously or (not previously and item.key == shown):
                box.selection_set(index)

    def _select_key(self, key: str | None) -> bool:
        """Show the image ``key`` (it must be in the visible list); True when it was."""

        if key is None:
            return False
        for index, path in enumerate(self._image_index_by_row):
            if item_key(path) == key:
                self.images_list.selection_clear(0, tk.END)
                self.images_list.selection_set(index)
                self.images_list.activate(index)
                self.images_list.see(index)
                self._show_image(path)
                return True
        return False

    def _on_filter_changed(self, _event: object = None) -> None:
        chosen = self.filter_var.get()
        for view, label in FILTER_LABELS.items():
            if label == chosen:
                self._session.set_filter(view)
                return

    def _refresh_decision_controls(self) -> None:
        session = self._session
        key = self._current_key()
        connected = self._resolve_evidence_writer() is not None
        for disposition, button in (
            ("retain", self.retain_button),
            ("discard", self.discard_button),
            ("rework", self.mark_rework_button),
        ):
            gate = session.decide_state(key, disposition)
            enabled, reason = gate.enabled, gate.reason
            if enabled and not connected:
                enabled = False
                reason = "Learning evidence is not connected, so a decision cannot be recorded."
            button.configure(state="normal" if enabled else "disabled")
            self._decision_tooltips[disposition].text = reason
        archived = key is not None and session.state_of(key) is ItemState.ARCHIVED
        self._decision_bar.set_shown(self.restore_button, archived)
        restorable = archived and connected and session.decide_state(key, "restore").enabled
        self.restore_button.configure(state="normal" if restorable else "disabled")
        self.save_rating_button.configure(
            state="normal" if self._selected_image_path is not None else "disabled"
        )
        highlighted = len(self._highlighted_image_paths())
        self.apply_selected_button.configure(
            text=f"Apply rating to {highlighted} selected"
            if highlighted
            else "Apply rating to selected"
        )

    def _refresh_rework_region(self) -> None:
        session = self._session
        marked = session.marked_items()
        if not marked:
            self._rework_frame.grid_remove()
            return
        self._rework_frame.grid()
        self._scope_var.set(session.scope_line())
        gate = session.rework_state()
        enabled, reason = gate.enabled, ""
        if not gate.enabled:
            reason = gate.reason
        elif self.app_controller is None:
            enabled, reason = False, "The application controller is not connected."
        self.rework_button.configure(state="normal" if enabled else "disabled")
        self._rework_reason_var.set(reason)
        self._rework_tooltip.text = reason or gate.reason
        single = session.single_tool_state(self._current_key())
        for widget in (
            self.edit_mask_button,
            self.extend_canvas_button,
            self.smart_review_button,
            self.inspect_improve_button,
            self.klein_check,
        ):
            widget.configure(state="normal" if single.enabled else "disabled")
        self._single_note_var.set("" if single.enabled else single.reason)

    def _refresh_returned(self) -> None:
        session = self._session
        rows = session.returned_rows()
        failed = [
            item for item in session.items if session.state_of(item.key) is ItemState.REWORK_FAILED
        ]
        if not rows and not failed:
            self._returned_rows = []
            self._returned_frame.grid_remove()
            return
        self._returned_frame.grid()
        values = [
            (
                row.source_name,
                row.path.name,
                STATE_LABELS[row.state],
                "Verified" if row.relation == "verified" else "Unverified (job id only)",
            )
            for row in rows
        ]
        current = [
            self.returned_tree.item(iid, "values") for iid in self.returned_tree.get_children()
        ]
        if [tuple(str(value) for value in row) for row in current] != [
            tuple(row) for row in values
        ] or len(self._returned_rows) != len(rows):
            selected = self.returned_tree.selection()
            self.returned_tree.delete(*self.returned_tree.get_children())
            for index, row_values in enumerate(values):
                self.returned_tree.insert("", "end", iid=str(index), values=row_values)
            if selected and selected[0].isdigit() and int(selected[0]) < len(values):
                self.returned_tree.selection_set(selected[0])
        self._returned_rows = rows
        notes: list[str] = []
        if failed:
            notes.append(
                f"{len(failed)} re-work job(s) failed. Nothing is retried automatically; retry them from "
                "Pipeline > Batches."
            )
        if any(row.relation != "verified" for row in rows):
            notes.append(
                "Unverified: the job recorded this image's job, but not the exact file, so the link may be "
                "to a different version."
            )
        self._returned_note_var.set(" ".join(notes))
        self._returned_actions.set_shown(self.returned_batches_button, bool(failed))

    def _schedule_poll(self) -> None:
        """While a re-work job is queued or running, re-read the repository now and then (never a retry)."""

        active = any(
            self._session.state_of(item.key) is ItemState.REWORK_QUEUED
            for item in self._session.items
        )
        if not active or self._poll_id is not None:
            return
        self._poll_id = self.after(5000, self._poll)

    def _poll(self) -> None:
        self._poll_id = None
        if self.winfo_exists() and self.winfo_ismapped():
            self._session.refresh()

    # -- decisions -------------------------------------------------------------------------------------------

    def _decide_current(self, disposition: str) -> bool:
        key = self._current_key()
        if key is None:
            return False
        self._bind_writer()
        targets = self._discard_targets(key) if disposition == "discard" else [key]
        if len(targets) > 1 and not self._confirm_discard(len(targets)):
            return False
        if self._rating_touched and self._selected_image_path is not None:
            self._save_feedback()  # a rating set before the decision is saved with it
        if len(targets) > 1:
            began = self._session.decide_many(targets, disposition)
            if not began:
                return False
            self._undo_order.extend(["decision"] * began)
        else:
            if not self._session.decide(key, disposition):
                return False
            self._undo_order.append("decision")
        self._advance_after_decision(key)
        return True

    def _discard_targets(self, key: str) -> list[str]:
        """The shown image, or every highlighted image when the shown one is among several highlighted."""

        highlighted = [item_key(path) for path in self._highlighted_image_paths()]
        return highlighted if len(highlighted) > 1 and key in highlighted else [key]

    def _confirm_discard(self, count: int) -> bool:
        hook = self._confirm_discard_hook
        if callable(hook):
            return bool(hook(count))
        return bool(
            messagebox.askyesno(
                "Discard images?",
                f"Move {count} images to the archive folder? Each can be restored (Undo or Restore); "
                "nothing is deleted.",
                parent=self,
            )
        )

    def _restore_current(self) -> bool:
        key = self._current_key()
        self._bind_writer()
        if not self._session.restore(key):
            return False
        self._undo_order.append("decision")
        return True

    def _advance_after_decision(self, key: str) -> None:
        following = self._session.next_undecided(key)
        if following is not None:
            self._select_key(following)
        elif not any(item_key(path) == key for path in self._image_index_by_row):
            self._feedback_status_var.set("Every visible image has a decision.")

    def _on_decision_key(self, value: str) -> str:
        if value == "undo":
            self._undo_last_action()
        else:
            self._decide_current(value)
        return "break"

    def _undo_last_action(self) -> None:
        last = self._undo_order[-1] if self._undo_order else ""
        if last == "inspection":
            self._undo_last_inspection()
            return
        if last == "rating":
            self._undo_last_feedback_save()
            return
        if last == "decision" or self._session.can_undo:
            self._bind_writer()
            if self._session.undo():
                self._discard_undo_marker("decision")
            return
        if self._feedback_undo_stack:
            self._undo_last_feedback_save()
            return
        self._feedback_status_var.set("Nothing to undo.")

    # -- re-work ---------------------------------------------------------------------------------------------

    def _start_rework(self) -> None:
        gate = self._session.rework_state()
        if not gate.enabled:
            messagebox.showwarning("Re-work", gate.reason, parent=self)
            return
        self._reprocess(targets=[item.path for item in self._session.rework_scope()])

    def _submit_rework(self, controller: Any, batch: Any, **callbacks: Any) -> Any:
        """Queue through the controller as before, then re-read the repository so queued jobs show as queued."""

        on_submitted = callbacks.get("on_submitted")

        def submitted(count: int) -> None:
            if self.winfo_exists():
                self._session.refresh()
            if callable(on_submitted):
                on_submitted(count)

        return controller.submit_review_reprocess_batch_async(
            batch, **{**callbacks, "on_submitted": submitted}
        )

    def _single_target_path(self) -> Path | None:
        target = self._session.single_target(self._current_key())
        return target.path if target is not None else None

    def _shown_tool_path(self, title: str) -> Path | None:
        """The image shown in Review, for the always-visible Edit image menu, or ``None`` after saying why not."""

        item = self._session.item(self._current_key())
        if item is None:
            messagebox.showwarning(title, "Select an image first.", parent=self)
            return None
        if item.path.suffix.lower() not in {".png", ".jpg", ".jpeg", ".webp"}:
            messagebox.showwarning(
                title, "Select exactly one PNG, JPEG or WebP still image.", parent=self
            )
            return None
        return item.path

    def _single_tool_path(self, title: str) -> Path | None:
        """The one image a single-image tool edits, or ``None`` after saying why not."""

        gate = self._session.single_tool_state(self._current_key())
        if not gate.enabled:
            messagebox.showwarning(title, gate.reason, parent=self)
            return None
        path = self._single_target_path()
        if path is None or path.suffix.lower() not in {".png", ".jpg", ".jpeg", ".webp"}:
            messagebox.showwarning(
                title, "Select exactly one PNG, JPEG or WebP still image.", parent=self
            )
            return None
        return path

    # -- provenance -----------------------------------------------------------------------------------------

    def _render_provenance(self) -> None:
        view = self._provenance_view
        if view is None:
            text = (
                "No recorded prompts for this image."
                if self._image_ready
                else "Loading prompts..."
                if self._selected_image_path is not None
                else "Select an image to see its prompts."
            )
        else:
            text = format_provenance(
                redact_view(view, self._visibility_resolver(), self._current_visibility_subject())
            )
        self._set_readonly_text(self.provenance_text, text)

    # -- Open menu ------------------------------------------------------------------------------------------

    def _open_picker(
        self, title: str, columns: Sequence[tuple[str, str, int]], on_open: Any
    ) -> ReviewSetPicker:
        if self._set_picker is not None and self._set_picker.winfo_exists():
            self._set_picker.destroy()
        picker = ReviewSetPicker(self, title=title, columns=columns, on_open=on_open)
        self._set_picker = picker
        return picker

    def _on_open_recent_job(self) -> None:
        history_items = list(getattr(self.app_state, "history_items", []) or [])
        if not history_items:
            messagebox.showinfo("No history", "No recent job history is available to open.")
            return
        picker = self._open_picker(
            "Open a recent job in Review",
            (("status", "Status", 120), ("pack", "Pack / Summary", 360), ("job_id", "Job ID", 220)),
            self._open_history_job,
        )
        picker.set_rows(
            [
                (
                    str(getattr(entry, "job_id", "") or ""),
                    (
                        str(getattr(getattr(entry, "status", None), "value", "") or ""),
                        self._history_entry_summary(entry),
                        str(getattr(entry, "job_id", "") or ""),
                    ),
                )
                for entry in history_items[:50]
            ]
        )

    def _open_history_job(self, job_id: str) -> None:
        entry = self._find_history_entry(job_id)
        picker = self._set_picker
        if entry is None:
            if picker is not None:
                picker.set_status("That job is no longer in History.")
            return
        if picker is not None:
            picker.set_status("Finding the job's images...")
        status, created, result = entry.status, entry.created_at, entry.result
        self._work.submit(
            "review:open-job",
            lambda: resolve_result_images(job_id, status, created, result),
            on_result=lambda resolution: self._load_resolved_outputs(
                resolution, f"job {job_id[:8]}"
            ),
            on_error=lambda exc: self._open_failed(exc),
            name="review-open-job",
            purpose="Resolve a recent job's image outputs for Review without blocking Tk",
        )

    def _on_open_batch(self) -> None:
        service = build_batch_operations_service(self.app_controller)
        if service is None:
            messagebox.showinfo(
                "No batches", "The job repository is not connected, so no batch can be opened."
            )
            return
        picker = self._open_picker(
            "Open a batch in Review",
            (
                ("batch", "Batch", 220),
                ("state", "State", 180),
                ("jobs", "Jobs", 60),
                ("activity", "Last activity", 180),
            ),
            lambda token: self._open_batch_outputs(service, token),
        )
        picker.set_status("Reading batches...")
        self._batch_summaries: dict[str, Any] = {}

        def listed(snapshot: Any) -> None:
            if not picker.winfo_exists():
                return
            rows: list[tuple[str, tuple[str, ...]]] = []
            for summary in snapshot.catalog.summaries:
                token = summary.key.to_token()
                self._batch_summaries[token] = summary
                rows.append(
                    (
                        token,
                        (
                            summary.key.label,
                            summary.state.value,
                            str(summary.job_count),
                            summary.last_activity_at.strftime("%Y-%m-%d %H:%M"),
                        ),
                    )
                )
            picker.set_rows(rows)
            picker.set_status("" if rows else "No batches were found in the job repository.")

        self._work.submit(
            "review:list-batches",
            service.refresh,
            on_result=listed,
            on_error=lambda exc: picker.set_status(f"Batches could not be read: {exc}")
            if picker.winfo_exists()
            else None,
            name="review-list-batches",
            purpose="Read the batch catalog for Review's Open menu without blocking Tk",
        )

    def _open_batch_outputs(self, service: Any, token: str) -> None:
        summary = self._batch_summaries.get(token)
        picker = self._set_picker
        if summary is None:
            if picker is not None:
                picker.set_status("Select a batch first.")
            return
        if picker is not None:
            picker.set_status("Finding the batch's images...")
        job_ids = tuple(job.job_id for job in summary.jobs)
        key = summary.key
        self._work.submit(
            "review:open-batch",
            lambda: service.resolve_outputs(key, job_ids),
            on_result=lambda resolution: self._load_resolved_outputs(resolution, key.label),
            on_error=lambda exc: self._open_failed(exc),
            name="review-open-batch",
            purpose="Resolve a batch's image outputs for Review without blocking Tk",
        )

    def _open_failed(self, error: Exception) -> None:
        picker = self._set_picker
        if picker is not None and picker.winfo_exists():
            picker.set_status(f"Could not open the outputs: {error}")

    def _load_resolved_outputs(self, resolution: Any, label: str) -> None:
        picker = self._set_picker
        images = [Path(path) for path in resolution.images]
        # Outputs Review archived are part of the set (listed under Archived, restorable there); nothing reads them.
        archived = [
            Path(path)
            for _job, path, reason in resolution.unavailable
            if reason == ARCHIVED_MESSAGE
        ]
        problems = " ".join(resolution.messages)
        if not images and not archived:
            if picker is not None and picker.winfo_exists():
                picker.set_status(f"No usable image outputs for {label}. {problems}".strip())
            return
        note = f" {len(archived)} archived by Review: see the Archived filter." if archived else ""
        count = self.load_selected_images(
            [*images, *archived],
            status_message=f"Opened {len(images)} image(s) from {label}.{note} {problems}".strip(),
        )
        if count and not images:
            self._session.set_filter(ViewFilter.ARCHIVED)
        if count and picker is not None and picker.winfo_exists():
            picker.destroy()

    # -- Returned -------------------------------------------------------------------------------------------

    def _selected_returned_row(self) -> Any | None:
        selection = self.returned_tree.selection()
        if not selection or not selection[0].isdigit():
            return None
        index = int(selection[0])
        return self._returned_rows[index] if index < len(self._returned_rows) else None

    def _compare_returned(self) -> None:
        row = self._selected_returned_row()
        if row is None:
            self._returned_note_var.set("Select a returned result first.")
            return
        source = next((item for item in self._session.items if item.key == row.source_key), None)
        if source is None:
            return
        if not PIL_AVAILABLE:
            messagebox.showinfo("Viewer unavailable", "Large compare viewer requires Pillow.")
            return
        self._compare_mode = "partner"
        self._render_compare_viewer(
            source.path,
            secondary_path=row.path,
            title_prefix="Source vs Returned re-work",
            labels=("Source", "Returned re-work"),
        )

    def _review_returned(self) -> None:
        row = self._selected_returned_row()
        if row is None:
            self._returned_note_var.set("Select a returned result first.")
            return
        out_key = item_key(row.path)
        self._session.add_items([row.path], after=row.source_key)
        if not self._select_key(out_key):
            self._session.set_filter(ViewFilter.ALL)
            self._select_key(out_key)

    def _rework_returned_again(self) -> None:
        """Mark the returned result itself for Re-work, so the next job names it (not the source) as its parent."""

        row = self._selected_returned_row()
        if row is None:
            self._returned_note_var.set("Select a returned result first.")
            return
        out_key = item_key(row.path)
        self._session.add_items([row.path], after=row.source_key)
        if not self._select_key(out_key):
            self._session.set_filter(ViewFilter.ALL)
            self._select_key(out_key)
        self._decide_current("rework")

    def _open_batches(self) -> None:
        from src.gui.controllers.video_workspace_handoff import show_queue_view

        if not show_queue_view(getattr(self.app_controller, "main_window", None)):
            self._returned_note_var.set("Open Pipeline > Batches to retry failed jobs.")

    def _on_send_selected_to_video_workflow(self) -> None:
        """Hand the Listbox's highlighted rows (in list order) to the Video Workflow tab.

        Uses the explicit selection only: not every imported image and not merely the image
        currently previewed.  Intent transfer only; the Video Workflow tab owns preview/queue."""

        paths = self._highlighted_image_paths()
        if not paths:
            messagebox.showinfo(
                "Send to Video Workflow",
                "Select one or more images in the Images list first.",
            )
            return
        main_window = getattr(self.app_controller, "main_window", None)
        if main_window is None:
            messagebox.showerror("Send to Video Workflow", "The main window is not available.")
            return
        lineage: dict[str, dict[str, str]] = {}
        for path in paths:
            meta = self._lookup_handoff_source_metadata(path)
            if isinstance(meta, dict):
                hint = {
                    key: str(meta[key])
                    for key in ("source_job_id", "source_artifact_id")
                    if meta.get(key)
                }
                if hint:
                    lineage[str(path)] = hint
        from src.gui.controllers.video_workspace_handoff import route_images_to_video_workflow

        try:
            route_images_to_video_workflow(
                main_window=main_window,
                image_paths=[str(path) for path in paths],
                lineage_by_path=lineage,
                status_message=(
                    f"Loaded {len(paths)} Review image(s) into Video Workflow. "
                    "Preview the batch before queueing."
                    if len(paths) > 1
                    else f"Loaded into Video Workflow tab: {paths[0].name}"
                ),
            )
        except Exception as exc:
            messagebox.showerror("Send to Video Workflow", str(exc))

    def _build_import_display_name(self, paths: list[Path]) -> str:
        if len(paths) == 1:
            return f"Review Import - {paths[0].stem}"
        return f"Review Import - {len(paths)} images"

    def _visibility_resolver(self) -> ContentVisibilityResolver:
        return ContentVisibilityResolver(self._content_visibility_mode)

    def _current_visibility_subject(self) -> dict[str, str]:
        return {
            "positive_prompt": self._selected_base_prompt,
            "negative_prompt": self._selected_base_negative_prompt,
            "name": self._selected_image_path.name if self._selected_image_path is not None else "",
        }

    def _apply_content_visibility_mode(self) -> None:
        resolver = self._visibility_resolver()
        self.preview.set_eligibility(
            (self._content_visibility_mode != "sfw" or self._image_ready)
            and resolver.is_visible(self._current_visibility_subject())
        )
        prompt_value = resolver.redact_text(
            self._selected_base_prompt, item=self._current_visibility_subject()
        )
        negative_value = resolver.redact_text(
            self._selected_base_negative_prompt,
            item=self._current_visibility_subject(),
        )
        self._set_readonly_text(self.current_prompt_text, prompt_value)
        self._set_readonly_text(self.current_negative_text, negative_value)
        self.visibility_banner.config(text="")
        self._render_provenance()

    def _hide_compare_media(self, _event: Any = None) -> None:
        window = self._compare_window
        if window is not None and window.winfo_exists():
            window.destroy()

    def on_content_visibility_mode_changed(self, mode: str | None = None) -> None:
        self._content_visibility_mode = str(
            mode
            or getattr(getattr(self, "app_state", None), "content_visibility_mode", "nsfw")
            or "nsfw"
        )
        self._close_inspection()
        self._pending_visibility_refresh = False
        self._apply_content_visibility_mode()
        self._refresh_prompt_diff()

    def _on_content_visibility_mode_changed(self) -> None:
        if not bool(self.winfo_ismapped()):
            self._pending_visibility_refresh = True
            self._content_visibility_mode = str(
                getattr(getattr(self, "app_state", None), "content_visibility_mode", "nsfw")
                or "nsfw"
            )
            return
        self.on_content_visibility_mode_changed()

    def _on_map(self, _event=None) -> None:
        if self._session.items:
            self._session.refresh()
        if not self._pending_visibility_refresh:
            return
        self.after_idle(
            lambda: self.on_content_visibility_mode_changed(self._content_visibility_mode)
        )

    def _set_readonly_text(self, widget: tk.Text, value: str) -> None:
        widget.configure(state="normal")
        widget.delete("1.0", tk.END)
        widget.insert("1.0", (value or "").strip())
        widget.configure(state="disabled")

    def _clip_text(self, text: str, max_len: int = 220) -> str:
        return self._workflow_adapter.clip_text(text, max_len=max_len)

    def _refresh_prompt_diff(self) -> None:
        prompt_delta = self.prompt_text.get("1.0", tk.END).strip()
        negative_delta = self.negative_text.get("1.0", tk.END).strip()
        diff = self._workflow_adapter.build_prompt_diff(
            base_prompt=self._selected_base_prompt,
            base_negative_prompt=self._selected_base_negative_prompt,
            prompt_delta=prompt_delta,
            negative_prompt_delta=negative_delta,
            prompt_mode=self.prompt_mode_var.get(),
            negative_prompt_mode=self.negative_mode_var.get(),
        )
        resolver = self._visibility_resolver()
        self.diff_before_label.config(
            text=resolver.redact_text(diff.before_text, item=self._current_visibility_subject())
        )
        self.diff_after_label.config(
            text=resolver.redact_text(diff.after_text, item=self._current_visibility_subject())
        )
        self._refresh_effective_settings()

    def _refresh_effective_settings(self) -> None:
        image_path = self._selected_image_path
        if image_path is None:
            self._effective_settings_var.set("Effective settings: select an image")
            return
        if not self._image_ready:
            # The image's own metadata is still loading off the Tk thread; the summary is built once it is current.
            self._effective_settings_var.set("Effective settings: loading image details...")
            return

        controller = self.app_controller
        builder = getattr(controller, "get_review_reprocess_effective_settings_preview", None)
        if not callable(builder):
            self._effective_settings_var.set("Effective settings: controller preview unavailable")
            return

        try:
            preview = builder(
                image_path=str(image_path),
                stages=self._selected_stages(),
                prompt_delta=self.prompt_text.get("1.0", tk.END).strip(),
                negative_prompt_delta=self.negative_text.get("1.0", tk.END).strip(),
                prompt_mode=self.prompt_mode_var.get(),
                negative_prompt_mode=self.negative_mode_var.get(),
            )
        except Exception as exc:
            self._effective_settings_var.set(f"Effective settings: unavailable ({exc})")
            return

        direct_queue_preview = None
        if self._active_handoff is not None:
            direct_queue_preview = self._active_handoff.direct_queue_preview
        try:
            readiness = self._workflow_adapter.assess_readiness(
                preview, single_reference_edit=bool(self.klein_edit_var.get())
            )
        except Exception:  # advisory only; the admission boundary still validates
            readiness = None
        self._effective_settings_var.set(
            self._workflow_adapter.format_effective_settings_summary(
                preview,
                direct_queue_preview=direct_queue_preview,
                readiness=readiness,
            )
        )

    def _show_batch_logic_help(self) -> None:
        messagebox.showinfo(
            "Batch Logic",
            "How batching works:\n\n"
            "- Single image run: always 1 job.\n"
            "- Batch run: images are grouped by compatible effective settings.\n"
            "- Compatible means same final + prompt, - prompt, model, and merged config.\n"
            "- If one image needs different model/config/prompt, it is put in a different job.\n"
            "- Batch size limits max images per compatible job.",
        )

    @staticmethod
    def _apply_prompt_delta(base: str, delta: str, mode: str) -> str:
        return ReviewWorkflowAdapter.apply_prompt_delta(base, delta, mode)

    def _get_text(self, widget: tk.Text) -> str:
        return widget.get("1.0", tk.END).strip()

    def _set_text(self, widget: tk.Text, value: str) -> None:
        widget.delete("1.0", tk.END)
        widget.insert("1.0", value or "")

    def _reset_mode_edits_for_current_image(self) -> None:
        self._prompt_mode_edits = {
            "append": "",
            "replace": "",
            "modify": self._selected_base_prompt,
        }
        self._negative_mode_edits = {
            "append": "",
            "replace": "",
            "modify": self._selected_base_negative_prompt,
        }
        self._prompt_prev_mode = self.prompt_mode_var.get() or "append"
        self._negative_prev_mode = self.negative_mode_var.get() or "append"
        self._sync_edit_box_to_mode("prompt")
        self._sync_edit_box_to_mode("negative")

    def _sync_edit_box_to_mode(self, which: str) -> None:
        if which == "prompt":
            mode = self.prompt_mode_var.get() or "append"
            text = self._prompt_mode_edits.get(mode, "")
            if mode == "modify" and not text:
                text = self._selected_base_prompt
                self._prompt_mode_edits["modify"] = text
            self._set_text(self.prompt_text, text)
        else:
            mode = self.negative_mode_var.get() or "append"
            text = self._negative_mode_edits.get(mode, "")
            if mode == "modify" and not text:
                text = self._selected_base_negative_prompt
                self._negative_mode_edits["modify"] = text
            self._set_text(self.negative_text, text)
        self._refresh_prompt_diff()

    def _on_prompt_mode_changed(self) -> None:
        self._prompt_mode_edits[self._prompt_prev_mode] = self._get_text(self.prompt_text)
        self._prompt_prev_mode = self.prompt_mode_var.get() or "append"
        self._sync_edit_box_to_mode("prompt")

    def _on_negative_mode_changed(self) -> None:
        self._negative_mode_edits[self._negative_prev_mode] = self._get_text(self.negative_text)
        self._negative_prev_mode = self.negative_mode_var.get() or "append"
        self._sync_edit_box_to_mode("negative")

    def _on_klein_edit_toggled(self) -> None:
        if self.klein_edit_var.get():
            if self._klein_snapshot is not None:
                return  # a repeated callback while Klein stays checked never overwrites the snapshot
            self._prompt_mode_edits[self._prompt_prev_mode] = self._get_text(self.prompt_text)
            self._negative_mode_edits[self._negative_prev_mode] = self._get_text(self.negative_text)
            self._klein_snapshot = {
                "img2img": self.stage_img2img_var.get(),
                "adetailer": self.stage_adetailer_var.get(),
                "upscale": self.stage_upscale_var.get(),
                "prompt_mode": self.prompt_mode_var.get(),
                "negative_mode": self.negative_mode_var.get(),
                "batch_size": self.batch_size_var.get(),
                "prompt_edits": dict(self._prompt_mode_edits),
                "negative_edits": dict(self._negative_mode_edits),
            }
            self.stage_img2img_var.set(True)
            self.stage_adetailer_var.set(False)
            self.stage_upscale_var.set(False)
            self.prompt_mode_var.set("replace")
            self.negative_mode_var.set("replace")
            self.batch_size_var.set(1)
            return
        snapshot, self._klein_snapshot = (
            self._klein_snapshot,
            None,
        )  # transient: cleared once restored
        if snapshot is None:
            return
        self.stage_img2img_var.set(snapshot["img2img"])
        self.stage_adetailer_var.set(snapshot["adetailer"])
        self.stage_upscale_var.set(snapshot["upscale"])
        self.prompt_mode_var.set(snapshot["prompt_mode"])
        self.negative_mode_var.set(snapshot["negative_mode"])
        self.batch_size_var.set(snapshot["batch_size"])
        # The Klein session's own typing must not leak into the ordinary per-mode edits.
        self._prompt_mode_edits = dict(snapshot["prompt_edits"])
        self._negative_mode_edits = dict(snapshot["negative_edits"])
        self._prompt_prev_mode = snapshot["prompt_mode"] or "append"
        self._negative_prev_mode = snapshot["negative_mode"] or "append"
        self._sync_edit_box_to_mode("prompt")
        self._sync_edit_box_to_mode("negative")

    def _reprocess(self, *, targets: list[Path]) -> None:
        """Preview and queue ``targets`` through the existing Review path (the one Preview dialog and Queue)."""

        klein_edit = bool(self.klein_edit_var.get())
        stages = ["img2img"] if klein_edit else self._selected_stages()
        if not stages:
            messagebox.showwarning("No stages", "Select at least one stage.")
            return
        if not targets:
            messagebox.showwarning("No images", "Mark at least one image for Re-work.")
            return

        controller = self.app_controller
        if controller is None:
            messagebox.showerror("Controller missing", "App controller is not connected.")
            return

        prompt_delta = self.prompt_text.get("1.0", tk.END).strip()
        negative_delta = self.negative_text.get("1.0", tk.END).strip()
        batch_size = max(1, int(self.batch_size_var.get() or 1))
        if klein_edit:
            if len(targets) != 1:
                messagebox.showwarning(
                    "Klein edit",
                    "FLUX.2 Klein single-reference edit needs exactly one selected image "
                    "(multi-reference is not supported).",
                )
                return
            if not prompt_delta:
                messagebox.showwarning("Klein edit", "Describe the desired edit in the prompt box.")
                return
            negative_delta, batch_size = "", 1

        try:
            preview_batch = getattr(controller, "preview_review_reprocess_batch", None)
            if callable(preview_batch):
                from src.gui.review_batch_dialog import ReviewBatchDialog

                source_map = dict(
                    getattr(self._active_handoff, "source_metadata_by_path", {}) or {}
                )
                if klein_edit:
                    source_map = self._workflow_adapter.with_klein_edit_request(source_map, targets)
                request = {
                    "image_paths": [str(p) for p in targets],
                    "stages": stages,
                    "prompt_delta": prompt_delta,
                    "negative_prompt_delta": negative_delta,
                    "prompt_mode": "replace" if klein_edit else self.prompt_mode_var.get(),
                    "negative_prompt_mode": "replace"
                    if klein_edit
                    else self.negative_mode_var.get(),
                    "batch_size": batch_size,
                    "source_metadata_by_image": source_map,
                    "group_by_model": bool(self.group_by_model_var.get()),
                }

                def show(preview: Any) -> None:
                    if not self.winfo_exists():
                        return
                    ReviewBatchDialog(
                        self,
                        preview,
                        submit=lambda batch, **callbacks: self._submit_rework(
                            controller, batch, **callbacks
                        ),
                        repreview=lambda paths: prepare({**request, "image_paths": paths}),
                        visibility=self._visibility_resolver(),
                    )

                def prepare(payload: dict[str, Any]) -> None:
                    preview_batch(
                        **payload,
                        on_preview=show,
                        on_error=lambda exc: messagebox.showerror("Review preview failed", str(exc))
                        if self.winfo_exists()
                        else None,
                    )

                prepare(request)
                return
            handler = getattr(controller, "on_reprocess_images_with_prompt_delta", None)
            if callable(handler):
                source_metadata_by_image = None
                if self._active_handoff is not None:
                    source_map = dict(
                        getattr(self._active_handoff, "source_metadata_by_path", {}) or {}
                    )
                    if source_map:
                        source_metadata_by_image = {}
                        for target in targets:
                            source_metadata = source_map.get(str(target)) or source_map.get(
                                str(target.resolve())
                            )
                            if isinstance(source_metadata, dict):
                                source_metadata_by_image[str(target)] = source_metadata
                if klein_edit:
                    source_metadata_by_image = self._workflow_adapter.with_klein_edit_request(
                        source_metadata_by_image, targets
                    )
                submitted = handler(
                    image_paths=[str(p) for p in targets],
                    stages=stages,
                    prompt_delta=prompt_delta,
                    negative_prompt_delta=negative_delta,
                    prompt_mode="replace" if klein_edit else self.prompt_mode_var.get(),
                    negative_prompt_mode="replace" if klein_edit else self.negative_mode_var.get(),
                    batch_size=batch_size,
                    source_metadata_by_image=source_metadata_by_image,
                )
            else:
                fallback = getattr(controller, "on_reprocess_images", None)
                if not callable(fallback):
                    raise RuntimeError("No reprocess handler is available on controller")
                submitted = fallback(
                    image_paths=[str(p) for p in targets],
                    stages=stages,
                    batch_size=batch_size,
                )
            messagebox.showinfo("Submitted", f"Submitted {submitted} reprocess job(s).")
            self._session.refresh()
        except Exception as exc:
            messagebox.showerror("Reprocess failed", str(exc))

    def _resolve_learning_controller(self) -> Any | None:
        app_ctrl = self.app_controller
        if app_ctrl is None:
            return None
        main_window = getattr(app_ctrl, "main_window", None)
        if main_window is None:
            return None
        learning_tab = getattr(main_window, "learning_tab", None)
        if learning_tab is None:
            return None
        return getattr(learning_tab, "learning_controller", None) or getattr(
            learning_tab, "controller", None
        )

    def _save_feedback(
        self, context: dict[str, Any] | None = None, *, source_proof: ImprovementPair | None = None
    ) -> None:
        if self._selected_image_path is None:
            messagebox.showwarning("No image", "Select an image first.")
            return
        learning_controller = self._resolve_learning_controller()
        if learning_controller is None:
            messagebox.showerror(
                "Learning unavailable",
                "Learning controller is not connected.",
            )
            return
        save = getattr(learning_controller, "save_review_feedback", None)
        if not callable(save):
            messagebox.showerror(
                "Unsupported",
                "Connected learning controller does not support review feedback.",
            )
            return
        payload = self._build_feedback_payload(self._selected_image_path)
        if payload is None:
            messagebox.showerror(
                "Save failed", "Unable to build feedback payload for selected image."
            )
            return
        if context:
            payload["context"] = {**payload.get("context", {}), **context}
        if source_proof is not None:
            payload["guided_source_proof"] = source_proof
        try:
            record = save(payload)
            run_id = str(getattr(record, "run_id", "") or "")
            if not run_id:
                raise OSError("Learning did not confirm a saved record identity.")
        except Exception as exc:
            self._feedback_status_var.set(
                f"Save not confirmed: {exc} Check the log before retrying."
            )
            return
        self._close_inspection()
        self._feedback_undo_stack.append(
            [{"run_id": run_id, "image_path": str(self._selected_image_path)}]
        )
        self._undo_order.append("rating")
        self._rating_touched = False
        self._session.note_rating(item_key(self._selected_image_path), int(self.rating_var.get()))
        status = (
            f"Saved 1 feedback record: {self._selected_image_path}. The image file was not changed. "
            "Review feedback is observational; use controlled Learning evidence for profile publication."
        )
        selected_image = self._selected_image_path
        summary_error = refresh_saved_feedback(
            lambda: self._refresh_prior_review_summary(selected_image)
        )
        if record.metadata.get("recommendation_refresh_error") or summary_error:
            status += " Evidence is saved; refresh Learning recommendations and the Review summary."
        self._feedback_status_var.set(status)
        self._rating_status_shown = True

    def _save_feedback_batch(self) -> None:
        learning_controller = self._resolve_learning_controller()
        if learning_controller is None:
            messagebox.showerror("Learning unavailable", "Learning controller is not connected.")
            return
        save = getattr(learning_controller, "save_review_feedback", None)
        if not callable(save):
            messagebox.showerror(
                "Unsupported",
                "Connected learning controller does not support review feedback.",
            )
            return
        targets = self._highlighted_image_paths()
        if not targets:
            messagebox.showwarning("No selection", "Select one or more images in the list.")
            return
        # Everything the worker needs is read from Tk here; hashing, metadata reads and the saves run off the
        # Tk thread, and the status is published when they finish.
        form = self._rating_form()
        selected_image = self._selected_image_path
        getter = self._prior_summary_getter()
        self._batch_saves += 1
        self._feedback_status_var.set(f"Saving the rating for {len(targets)} image(s)...")
        self.apply_selected_button.configure(state="disabled")

        def work() -> dict[str, Any]:
            tokens: list[dict[str, str]] = []
            failed: list[str] = []
            refresh_failed: list[str] = []
            for target in targets:
                try:
                    payload = self._build_feedback_payload(target, form)
                    if payload is None:
                        raise ValueError("Unable to build feedback payload.")
                    record = save(payload)
                    run_id = str(getattr(record, "run_id", "") or "")
                    if not run_id:
                        raise OSError("Learning did not confirm a saved record identity.")
                    tokens.append({"run_id": run_id, "image_path": str(target)})
                    if record.metadata.get("recommendation_refresh_error"):
                        refresh_failed.append(str(target))
                except Exception:
                    failed.append(str(target))
            summary: Any = None
            summary_ok = False
            if tokens and selected_image is not None and callable(getter):

                def read() -> None:
                    nonlocal summary
                    summary = getter(str(selected_image))

                summary_ok = not refresh_saved_feedback(read)
            return {
                "tokens": tokens,
                "failed": failed,
                "refresh_failed": refresh_failed,
                "summary": summary,
                "summary_ok": summary_ok,
            }

        def done(result: dict[str, Any]) -> None:
            if not self.winfo_exists():
                return
            self.apply_selected_button.configure(state="normal")
            tokens = result["tokens"]
            failed = result["failed"]
            refresh_failed = list(result["refresh_failed"])
            if tokens:
                self._close_inspection()
                self._feedback_undo_stack.append(tokens)
                self._undo_order.append("rating")
                for token in tokens:
                    self._session.note_rating(item_key(token["image_path"]), form["rating"])
                if selected_image is not None and any(
                    item_key(token["image_path"]) == item_key(selected_image) for token in tokens
                ):
                    self._rating_touched = False
            status = f"Saved {len(tokens)} feedback record(s); not confirmed {len(failed)}."
            if tokens:
                status += " Saved: " + "; ".join(token["image_path"] for token in tokens) + "."
            if failed:
                status += (
                    " Not confirmed: " + "; ".join(failed) + ". Check the log before retrying."
                )
            if tokens and selected_image is not None:
                if result["summary_ok"]:
                    self._prior_review_summary_var.set(
                        self._format_prior_review_summary(result["summary"])
                    )
                else:
                    self._prior_review_summary_var.set("Prior Review Summary: unavailable")
            if refresh_failed:
                status += (
                    " Evidence is saved; refresh Learning recommendations and the Review summary."
                )
            self._feedback_status_var.set(status)
            self._rating_status_shown = True

        def failed_run(error: Exception) -> None:
            if not self.winfo_exists():
                return
            self.apply_selected_button.configure(state="normal")
            self._feedback_status_var.set(f"The rating was not saved: {error}")

        self._work.submit(
            f"review:rate-batch:{self._batch_saves}",
            work,
            on_result=done,
            on_error=failed_run,
            name="review-rate-batch",
            purpose="Hash and save one Review rating for each highlighted image without blocking Tk",
        )

    def _write_rating_into_file(self) -> None:
        """Explicit export of the saved rating into the image (or a sidecar); saving a rating never does this."""

        path = self._selected_image_path
        learning_controller = self._resolve_learning_controller()
        export = getattr(learning_controller, "write_review_rating_into_file", None)
        if path is None or not callable(export):
            messagebox.showwarning("Write rating", "Select an image with a saved rating first.")
            return
        if path.suffix.lower() == ".png":
            message = (
                "This embeds the saved rating in the PNG file. The file's bytes will change, so its identity "
                "changes: History lineage, Compare with Parent and Review Preview will treat it as a different "
                "file. Continue?"
            )
        else:
            message = (
                "This writes the saved rating to a sidecar file next to the image. The image itself is not "
                "re-encoded or changed. Continue?"
            )
        if not self._confirm_replace("Write rating into file?", message):
            return
        self._feedback_status_var.set("Writing the rating into the file...")
        self._work.submit(
            "review:write-rating",
            lambda: export(str(path)),
            on_result=lambda result: self._feedback_status_var.set(
                f"Rating written to {result.sidecar_path or result.stamped_path}."
                if result.success
                else f"Rating was not written: {result.error or 'unknown error'}."
            ),
            on_error=lambda exc: self._feedback_status_var.set(f"Rating was not written: {exc}"),
            name="review-write-rating",
            purpose="Write the saved Review rating into the selected image or its sidecar",
        )

    def _undo_last_feedback_save(self) -> None:
        learning_controller = self._resolve_learning_controller()
        if learning_controller is None:
            messagebox.showerror("Learning unavailable", "Learning controller is not connected.")
            return
        undo = getattr(learning_controller, "undo_review_feedback", None)
        if not callable(undo):
            messagebox.showerror(
                "Unsupported", "Connected learning controller does not support undo."
            )
            return
        if not self._feedback_undo_stack:
            messagebox.showinfo("Nothing to undo", "No saved feedback actions to undo.")
            return
        action = self._feedback_undo_stack.pop()
        self._discard_undo_marker("rating")
        undone = 0
        for token in reversed(action):
            if undo(run_id=token.get("run_id"), image_path=token.get("image_path")):
                undone += 1
        if undone <= 0:
            self._feedback_status_var.set("Undo removed no matching feedback records.")
            messagebox.showwarning("Undo", "No matching feedback records were removed.")
            return
        text = undo_rating_text(undone, [token.get("image_path") for token in action])
        self._feedback_status_var.set(text)
        self._rating_status_shown = True
        messagebox.showinfo("Undo complete", text)

    def _rating_form(self) -> dict[str, Any]:
        """Every Tk-held value a rating save needs, read once on the Tk thread so a worker can build payloads."""

        return {
            "rating": int(self.rating_var.get()),
            "quality": self.quality_var.get(),
            "notes": self.feedback_notes.get("1.0", tk.END).strip(),
            "prompt_delta": self.prompt_text.get("1.0", tk.END).strip(),
            "negative_delta": self.negative_text.get("1.0", tk.END).strip(),
            "prompt_mode": self.prompt_mode_var.get(),
            "negative_mode": self.negative_mode_var.get(),
            "stages": self._selected_stages(),
            "anatomy": int(self.anatomy_rating_var.get()),
            "composition": int(self.composition_rating_var.get()),
            "prompt_adherence": int(self.prompt_adherence_rating_var.get()),
            "selected_path": self._selected_image_path,
            "selected_sha": self._selected_image_sha256,
            "adetailer_pair": self._adetailer_pair,
            "adetailer_face": self.adetailer_face_outcome_var.get(),
            "adetailer_hands": self.adetailer_hands_outcome_var.get(),
            "adetailer_note": self.adetailer_outcome_note_var.get(),
        }

    def _build_feedback_payload(
        self, image_path: Path, form: dict[str, Any] | None = None
    ) -> dict[str, Any] | None:
        form = form if form is not None else self._rating_form()
        metadata = extract_embedded_metadata(image_path)
        if metadata.status != "ok" or not isinstance(metadata.payload, dict):
            return None
        payload = self._workflow_adapter.build_feedback_payload(
            image_path=image_path,
            metadata_payload=metadata.payload,
            rating=form["rating"],
            quality_label=form["quality"],
            notes=form["notes"],
            prompt_delta=form["prompt_delta"],
            negative_prompt_delta=form["negative_delta"],
            prompt_mode=form["prompt_mode"],
            negative_prompt_mode=form["negative_mode"],
            stages=list(form["stages"]),
            anatomy_rating=form["anatomy"],
            composition_rating=form["composition"],
            prompt_adherence_rating=form["prompt_adherence"],
        )
        # The identity of the bytes Review showed; any other image is hashed by the controller at save time.
        if image_path == form["selected_path"] and form["selected_sha"]:
            payload["artifact_sha256"] = form["selected_sha"]
        job_id = str(metadata.payload.get("job_id") or "").strip()
        if job_id:
            payload["source_job_id"] = job_id
        # Only the image currently shown (with its verified source) can carry the optional before/after judgment.
        pair = form["adetailer_pair"]
        if pair is not None and image_path == form["selected_path"]:
            context = build_review_context(
                pair,
                face=form["adetailer_face"],
                hands=form["adetailer_hands"],
                note=form["adetailer_note"],
            )
            if context:
                payload["context"] = context
        return payload
