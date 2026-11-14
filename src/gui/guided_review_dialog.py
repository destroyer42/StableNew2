"""Inspect & Improve in Review, with explicit observation, draft and feedback actions."""

from __future__ import annotations

import threading
import tkinter as tk
from collections.abc import Callable
from dataclasses import replace
from pathlib import Path
from tkinter import ttk
from typing import Any

from src.controller.masked_edit_service import history_lineage_for
from src.generation_profiles.startup import available_model_names
from src.gui.controllers.history_compare_service import resolve_history_repository
from src.gui.guided_reprocess_dialog import GuidedReprocessDialog
from src.gui.mask_editor_dialog import MaskEditorDialog
from src.gui.smart_review_dialog import SmartReviewDialog
from src.gui.theme_v2 import apply_toplevel_theme
from src.gui.view_contracts.edit_work_runner import build_edit_work_runner
from src.gui.view_contracts.media_image_decode import InspectionImage, decode_inspection_image
from src.gui.widgets.media_inspector import MediaInspector
from src.image_backends.image_backend_types import configured_image_backend_id
from src.pipeline.adetailer_effectiveness import VISUAL_OUTCOMES
from src.review.assist.contracts import CaptionProposal, SegmentProposal
from src.review.assist.identity import reverify_source
from src.review.correction_advice import (
    CorrectionTarget,
    GuidedReprocess,
    ReviewResources,
    detectors_for,
    recommend,
    resolve_target,
)
from src.review.findings import (
    MAX_FINDINGS,
    Action,
    Advisory,
    Category,
    Certainty,
    Confirmation,
    Finding,
    Origin,
    Region,
)
from src.review.improvement_evidence import (
    OVERALL_PREFERENCES,
    ImprovementPair,
    build_improvement_context,
    resolve_improvement,
)
from src.review.inspection import GuidedSource, import_suggestion, inspect_source


class GuidedReviewDialog(tk.Toplevel):
    def __init__(
        self,
        parent: Any,
        *,
        path: Path,
        revision: tuple[int, int],
        current: Callable[[], bool],
        save: Callable[..., None],
    ) -> None:
        super().__init__(parent)
        apply_toplevel_theme(self)
        self.title("Inspect & Improve")
        self.geometry("1160x830")
        self.minsize(820, 640)
        self.transient(parent.winfo_toplevel())
        self._review = parent
        self._controller = parent.app_controller
        self._path, self._current, self._save_feedback = path, current, save
        self._work = build_edit_work_runner(self)
        self._loaded: GuidedSource | None = None
        self._targets: dict[str, CorrectionTarget] = {}
        self._findings: list[tuple[Finding, bytes | None]] = []
        self._judgments: list[tuple[Category, Region | None, str]] = []
        self._region: Region | None = None
        self._selected: int | None = None
        self._pair: ImprovementPair | None = None
        self._child: tk.Toplevel | None = None
        self._busy = False
        self._feedback_saved = False
        self._status = tk.StringVar(master=self, value="Reading selected image…")
        self._evidence = tk.StringVar(master=self)
        self._visible_comparison = False
        self._region_label = tk.StringVar(master=self, value="Whole image")
        self._category = tk.StringVar(master=self, value=Category.GENERAL)
        self._certainty = tk.StringVar(master=self, value=Certainty.UNKNOWN)
        self._confirmation = tk.StringVar(master=self, value=Confirmation.CONFIRMED)
        self._action = tk.StringVar(master=self)
        self._outcome = tk.StringVar(master=self, value="unreviewed")
        self._preference = tk.StringVar(master=self, value="unreviewed")
        self._build()
        self.bind("<Destroy>", self._destroyed, add="+")
        self._work.submit(
            "inspect",
            lambda: inspect_source(path, revision),
            on_result=self._loaded_source,
            on_error=lambda _exc: self._status.set(
                "Select a readable PNG, JPEG or WebP within the inspection limits."
            ),
            name="guided-review-source",
        )

    def _build(self) -> None:
        body = ttk.Frame(self, padding=10)
        body.pack(fill="both", expand=True)
        body.columnconfigure(0, weight=1)
        body.rowconfigure(0, weight=1)
        media = ttk.Frame(body)
        media.grid(row=0, column=0, sticky="nsew", padx=(0, 10))
        media.columnconfigure(0, weight=1)
        media.rowconfigure((0, 1), weight=1)
        self.after_view = MediaInspector(
            media,
            width=520,
            height=320,
            allow_original=False,
            on_region=self._select_region,
            image_decoder=self._decode_after,
        )
        self.after_view.grid(row=0, column=0, rowspan=2, sticky="nsew")
        self.after_view.bind("<<MediaHidden>>", self._hide_evidence, add="+")
        self.before_view = MediaInspector(
            media,
            width=520,
            height=280,
            allow_original=False,
            image_decoder=self._decode_before,
        )
        from src.gui.widgets.scrollable_frame_v2 import ScrollableFrame

        scroll = ScrollableFrame(body)
        scroll.grid(row=0, column=1, sticky="nsew")
        panel = scroll.inner
        ttk.Label(panel, text="Findings").pack(anchor="w")
        self._rows = tk.Listbox(panel, height=5, width=48, exportselection=False)
        self._rows.pack(fill="x")
        self._rows.bind("<<ListboxSelect>>", self._show_finding)
        row = ttk.Frame(panel)
        row.pack(fill="x", pady=4)
        ttk.Button(row, text="New finding", command=self._new_finding).pack(side="left")
        ttk.Button(row, text="Smart Review…", command=self._open_smart).pack(side="left", padx=4)
        ttk.Button(row, text="Refresh actions", command=self._refresh_targets).pack(side="left")
        row = ttk.Frame(panel)
        row.pack(fill="x")
        ttk.Button(row, text="Draw region", command=self._draw_region).pack(side="left")
        ttk.Button(row, text="Whole image", command=lambda: self._select_region(None)).pack(
            side="left", padx=4
        )
        ttk.Label(panel, textvariable=self._region_label).pack(anchor="w")
        for label, variable, choices in (
            ("Issue category", self._category, tuple(Category)),
            ("Certainty", self._certainty, tuple(Certainty)),
            ("Confirmation", self._confirmation, tuple(Confirmation)),
        ):
            ttk.Label(panel, text=label).pack(anchor="w")
            ttk.Combobox(panel, values=choices, textvariable=variable, state="readonly").pack(
                fill="x"
            )
        self._origin = ttk.Label(panel, text=Origin.OPERATOR, wraplength=340)
        self._origin.pack(anchor="w", pady=(4, 0))
        ttk.Label(panel, text="Visible issue").pack(anchor="w")
        self._observation = tk.Text(panel, height=3, width=40, wrap="word")
        self._observation.pack(fill="x")
        ttk.Button(panel, text="Record finding", command=self._record).pack(anchor="w", pady=4)
        self._actions = ttk.Combobox(panel, textvariable=self._action, state="readonly", values=())
        self._actions.pack(fill="x")
        self._actions.bind("<<ComboboxSelected>>", lambda _event: self._show_advice())
        self._advice = ttk.Label(panel, wraplength=340, justify="left")
        self._advice.pack(anchor="w")
        self._draft_button = ttk.Button(
            panel, text="Open correction draft", command=self._open_draft
        )
        self._draft_button.pack(anchor="w", pady=4)
        self._draft_button.state(["disabled"])
        ttk.Separator(panel).pack(fill="x", pady=4)
        ttk.Button(panel, text="Compare completed result", command=self._compare).pack(anchor="w")
        ttk.Label(panel, textvariable=self._evidence, wraplength=340, justify="left").pack(
            anchor="w"
        )
        self._rating_row = ttk.Frame(panel)
        ttk.Label(self._rating_row, text="Selected region").pack(side="left")
        ttk.Combobox(
            self._rating_row,
            textvariable=self._outcome,
            values=VISUAL_OUTCOMES,
            state="readonly",
            width=11,
        ).pack(side="left")
        ttk.Button(self._rating_row, text="Record judgment", command=self._judge).pack(side="left")
        self._preference_row = ttk.Frame(panel)
        ttk.Label(self._preference_row, text="Overall preference").pack(side="left")
        ttk.Combobox(
            self._preference_row,
            textvariable=self._preference,
            values=OVERALL_PREFERENCES,
            state="readonly",
            width=15,
        ).pack(side="left", padx=4)
        self._save_button = ttk.Button(panel, text="Save with Review ratings", command=self._save)
        ttk.Label(body, textvariable=self._status, wraplength=850).grid(
            row=1, column=0, columnspan=2, sticky="w"
        )

    def _destroyed(self, event: tk.Event) -> None:
        if event.widget is self:
            self._work.close()

    def _decode_after(self, path: str, cancel: threading.Event) -> InspectionImage:
        loaded = self._loaded
        if loaded is None:
            raise ValueError("The source image is unavailable.")
        return decode_inspection_image(path, cancel, source_bytes=loaded.data)

    def _decode_before(self, path: str, cancel: threading.Event) -> InspectionImage:
        pair = self._pair
        if pair is None:
            raise ValueError("The before image is unavailable.")
        loaded = inspect_source(Path(path), pair.after.revision)
        if loaded.source.identity.file_sha256 != pair.before_sha256:
            raise ValueError("The before image changed. Reopen inspection.")
        return decode_inspection_image(path, cancel, source_bytes=loaded.data)

    def _loaded_source(self, loaded: GuidedSource) -> None:
        if not self._current():
            return
        self._loaded = loaded
        if not self._review._visibility_resolver().is_visible(loaded.subject):
            self._status.set("This image is hidden by content visibility.")
            return
        self.after_view.set_image_reference(str(self._path), subject=loaded.subject)
        self._status.set("Draw a region or choose Whole image. Record only visible issues.")
        self._refresh_targets()

    def _resources(self) -> ReviewResources:
        state = self._review.app_state
        catalog = getattr(state, "resources", None)
        names = available_model_names(catalog) or set()
        detectors = tuple(getattr(state, "adetailer_detectors", ()))
        return ReviewResources(frozenset(names), detectors, getattr(self, "_backend", ""))

    def _refresh_targets(self) -> None:
        if self._loaded is None or not self._current():
            return
        self._targets.clear()
        self._refresh_advice()
        try:
            fallbacks = {
                stage: self._controller._build_reprocess_config([stage])
                for stage in ("img2img", "adetailer")
            }
        except (AttributeError, ValueError, OSError):
            self._status.set(
                "Correction settings are unavailable. You can still inspect this image."
            )
            return

        def prepare() -> tuple[str, dict[str, CorrectionTarget]]:
            backend = configured_image_backend_id()
            baseline = self._controller._extract_reprocess_baseline_from_image(self._path)
            return backend, {
                stage: resolve_target(baseline, config, stage)
                for stage, config in fallbacks.items()
            }

        def ready(result: tuple[str, dict[str, CorrectionTarget]]) -> None:
            if self._current():
                self._backend, self._targets = result
                self._refresh_advice()

        self._work.submit(
            "targets",
            prepare,
            on_result=ready,
            on_error=lambda _exc: self._status.set(
                "Correction target is unavailable. Manual inspection is available."
            ),
        )

    def _draw_region(self) -> None:
        if self._loaded and self._current():
            self.after_view.set_region(self._region.box if self._region else None, selecting=True)
            self._status.set("Drag between two points within the image.")

    def _select_region(self, box: tuple[int, int, int, int] | None) -> None:
        if not self._loaded or not self._current():
            return
        region = Region(*box) if box else None
        if region:
            region.validate(self._loaded.source.identity.size)
        self._region = region
        self._region_label.set(f"Stored pixels {box}" if box else "Whole image")
        self.after_view.set_region(box)

    def _reset_finding(self) -> None:
        self._selected = None
        self._category.set(Category.GENERAL)
        self._certainty.set(Certainty.UNKNOWN)
        self._confirmation.set(Confirmation.CONFIRMED)
        self._origin.configure(text=Origin.OPERATOR)
        self._observation.delete("1.0", "end")
        self._select_region(None)
        self._refresh_advice()

    def _new_finding(self) -> None:
        self._rows.selection_clear(0, "end")
        self._reset_finding()

    def _record(self) -> None:
        if (
            not self._current()
            or not self._loaded
            or self._busy
            or not self.after_view.model.renderable
        ):
            return
        original, mask = (
            self._findings[self._selected] if self._selected is not None else (None, None)
        )
        text = self._observation.get("1.0", "1.0+501c")
        try:
            confirmation = Confirmation(self._confirmation.get())
            if (
                original
                and original.origin is not Origin.OPERATOR
                and original.confirmation is not Confirmation.CONFIRMED
                and confirmation is Confirmation.CONFIRMED
                and text.strip()
                in (
                    original.observation,
                    self._review._visibility_resolver().redact_text(original.observation),
                )
            ):
                raise ValueError(
                    "Describe the issue you see in your own words before confirming the suggestion."
                )
            finding = Finding(
                self._loaded.source,
                self._region,
                Category(self._category.get()),
                original.origin if original else Origin.OPERATOR,
                text,
                Certainty(self._certainty.get()),
                confirmation,
                suggestion_label=original.suggestion_label if original else "",
                effectiveness_job_id=self._pair.job_id
                if self._pair and self._pair.verified
                else None,
            )
            self._store_finding(
                finding, mask if original and original.region == finding.region else None
            )
        except ValueError as exc:
            self._status.set(str(exc))

    def _store_finding(self, finding: Finding, mask: bytes | None) -> None:
        if self._selected is None:
            if len(self._findings) >= MAX_FINDINGS:
                raise ValueError(f"Use at most {MAX_FINDINGS} findings per session.")
            self._selected = len(self._findings)
            self._findings.append((finding, mask))
        else:
            self._findings[self._selected] = finding, mask
        self._rows.delete(0, "end")
        for item, _ in self._findings:
            self._rows.insert(
                "end",
                f"{item.category} · {item.confirmation} · {item.region.box if item.region else 'Whole image'}",
            )
        self._rows.selection_set(self._selected)
        self._status.set("Finding recorded for this inspection.")
        self._show_finding()

    def _show_finding(self, _event: Any = None) -> None:
        selected = self._rows.curselection()  # type: ignore[no-untyped-call]
        if not selected or not self._current():
            return
        self._selected = int(selected[0])
        finding, _ = self._findings[self._selected]
        self._category.set(finding.category)
        self._certainty.set(finding.certainty)
        self._confirmation.set(finding.confirmation)
        self._origin.configure(
            text=f"{finding.origin} · {finding.suggestion_label}"
            if finding.suggestion_label
            else finding.origin
        )
        self._observation.delete("1.0", "end")
        self._observation.insert(
            "1.0", self._review._visibility_resolver().redact_text(finding.observation)
        )
        self._select_region(finding.region.box if finding.region else None)
        self._refresh_advice()

    def _refresh_advice(self) -> None:
        options: tuple[Advisory, ...] = ()
        if self._selected is not None and self._targets:
            finding, mask = self._findings[self._selected]
            options = recommend(finding, self._targets, self._resources())
            self._findings[self._selected] = replace(finding, advice=options), mask
        self._actions.configure(values=tuple(option.action for option in options))
        self._action.set(options[0].action if options else "")
        self._show_advice()

    def _show_advice(self) -> None:
        options = self._findings[self._selected][0].advice if self._selected is not None else ()
        option = next((item for item in options if item.action == self._action.get()), None)
        self._advice.configure(
            text=f"{'Available' if option.eligible else 'Unavailable'} · {option.reason}"
            if option
            else ""
        )
        self._draft_button.state(["!disabled"] if option and option.eligible else ["disabled"])

    def _can_open(self) -> bool:
        return bool(
            self._loaded
            and self._current()
            and not self._busy
            and self.after_view.model.renderable
            and (self._child is None or not self._child.winfo_exists())
        )

    def _open_smart(self) -> None:
        if not self._can_open():
            return
        from src.review.assist.session import AssistEnablement

        if self._review._smart_enablement is None:
            self._review._smart_enablement = AssistEnablement()
        self._child = SmartReviewDialog(
            self,
            source_path=self._path,
            controller=self._controller,
            enablement=self._review._smart_enablement,
            draft_current=self._current,
            visibility_mode=lambda: self._review._content_visibility_mode,
            on_suggestion=self._import,
            expected_source_sha256=self._loaded.source.identity.file_sha256
            if self._loaded
            else None,
        )

    def _import(self, proposal: CaptionProposal | SegmentProposal) -> None:
        if not self._current() or self._loaded is None:
            return
        source = self._loaded.source

        def prepare() -> tuple[Finding, bytes | None]:
            reverify_source(source.path, source.identity)
            return import_suggestion(source, proposal)

        def ready(value: tuple[Finding, bytes | None]) -> None:
            if self._current() and self.after_view.model.renderable:
                self._new_finding()
                try:
                    self._store_finding(*value)
                except ValueError as exc:
                    self._status.set(str(exc))

        self._work.submit(
            "suggestion",
            prepare,
            on_result=ready,
            on_error=lambda _exc: self._status.set(
                "Suggestion unavailable for the current source."
            ),
        )

    def _open_draft(self) -> None:
        if self._selected is None or not self._can_open():
            return
        finding, mask = self._findings[self._selected]
        selection = self._selected
        if not self._targets:
            self._status.set("Correction targets are unavailable.")
            return
        option = next(
            (
                item
                for item in recommend(finding, self._targets, self._resources())
                if item.action == self._action.get()
            ),
            None,
        )
        if option is None or not option.eligible:
            self._status.set(option.reason if option else "Choose an available action.")
            return
        action = option.action
        stage = "adetailer" if action in (Action.FACE, Action.HANDS) else "img2img"
        target = self._targets[stage]
        resources = self._resources()
        detectors = detectors_for(action, resources)
        draft = GuidedReprocess(
            finding.source,
            action,
            finding.category,
            finding.region,
            target.model,
            target.backend,
            detectors[0] if detectors else "",
            resources,
        )

        def current() -> bool:
            return bool(
                self._current()
                and self.after_view.model.renderable
                and resources == self._resources()
            )

        def ready(_unused: None) -> None:
            self._busy = False
            if (
                not current()
                or self._selected != selection
                or self._findings[selection][0] != finding
                or self._action.get() != action
            ):
                self._status.set("Source finding or target changed. Open the draft again.")
                return
            handoff = self._review._active_handoff
            if action is Action.MASK:
                self._child = MaskEditorDialog(
                    self,
                    source_path=self._path,
                    controller=self._controller,
                    lineage=history_lineage_for(handoff, self._path),
                    suggested_mask=mask,
                    suggested_source_sha256=finding.source.identity.file_sha256,
                    guided=draft,
                    guided_current=current,
                )
                self._status.set(
                    "Paint the indicated region in Edit Mask, or refine the accepted suggestion."
                )
            else:
                self._child = GuidedReprocessDialog(
                    self,
                    draft=draft,
                    controller=self._controller,
                    sources=dict(getattr(handoff, "source_metadata_by_path", None) or {}),
                    detectors=detectors,
                    current=current,
                    visibility=self._review._visibility_resolver,
                )

        def failed(_exc: Exception) -> None:
            self._busy = False
            self._status.set("The source image changed. Reopen Inspect & Improve.")

        self._busy = True
        self._work.submit(
            "handoff",
            lambda: reverify_source(self._path, finding.source.identity),
            on_result=ready,
            on_error=failed,
        )

    def _compare(self) -> None:
        if not self._can_open() or self._loaded is None:
            return
        source = self._loaded.source
        repository = resolve_history_repository(self._controller)
        self._work.submit(
            "compare",
            lambda: resolve_improvement(repository, source),
            on_result=self._show_comparison,
            on_error=lambda _exc: self._evidence.set(
                "Verified before/after evidence unavailable. You can still inspect the selected image."
            ),
        )

    def _show_comparison(self, pair: ImprovementPair) -> None:
        if not self._current() or not self.after_view.model.renderable:
            return
        resolver = self._review._visibility_resolver()
        if self._loaded is None or pair.after != self._loaded.source:
            return
        if not all(
            resolver.is_visible(subject)
            for subject in (
                pair.before_subject,
                pair.after_subject,
                pair.before_bytes_subject,
                self._loaded.subject,
            )
        ):
            self._evidence.set("Comparison hidden by content visibility.")
            return
        self._pair = pair
        self._visible_comparison = True
        self.after_view.grid_configure(row=1, rowspan=1)
        self.before_view.grid(row=0, column=0, sticky="nsew")
        self.before_view.set_image_reference(str(pair.before), subject=pair.before_subject)
        self.after_view.set_image_reference(str(pair.after.path), subject=self._loaded.subject)
        self._render_evidence()

    def _hide_evidence(self, _event: tk.Event) -> None:
        if self._visible_comparison and not self.after_view.model.renderable:
            self._visible_comparison = False
            self.before_view.grid_remove()
            self.after_view.grid_configure(row=0, rowspan=2)
            self._evidence.set("")
            self._rating_row.pack_forget()
            self._preference_row.pack_forget()
            self._save_button.pack_forget()

    def _render_evidence(self) -> None:
        pair = self._pair
        if pair is None:
            return
        if pair.verified:
            lines = ["Verified before (top) and completed result (bottom).", *pair.summary]
            lines.extend(
                f"{category} {region.box if region else '(whole image)'} · operator: {outcome}"
                for category, region, outcome in self._judgments[-3:]
            )
            lines.append("Overall image rating uses the existing Review Feedback settings.")
            self._rating_row.pack(anchor="w")
            self._preference_row.pack(anchor="w")
            self._save_button.pack(anchor="w")
        else:
            lines = [
                "Recorded before (top) and result (bottom). Source lineage remains unverified."
            ]
        self._evidence.set("\n".join(lines))

    def _comparison_ready(self) -> bool:
        return self._visible_comparison and all(
            view.model.renderable and view.model.status == "ready"
            for view in (self.before_view, self.after_view)
        )

    def _judge(self) -> None:
        if (
            not self._current()
            or not self._comparison_ready()
            or not self._pair
            or not self._pair.verified
            or self._busy
            or self._feedback_saved
        ):
            return
        value = self._outcome.get()
        if value == "unreviewed":
            self._status.set("Select a judgment for the selected region.")
            return
        category = Category(self._category.get())
        remaining = [row for row in self._judgments if row[:2] != (category, self._region)]
        if len(remaining) >= MAX_FINDINGS:
            self._status.set(f"Use at most {MAX_FINDINGS} region judgments.")
            return
        self._judgments = remaining
        self._judgments.append((category, self._region, value))
        self._render_evidence()

    def _save(self) -> None:
        pair = self._pair
        if (
            not self._current()
            or not self._comparison_ready()
            or pair is None
            or self._busy
            or self._feedback_saved
        ):
            return
        try:
            context = build_improvement_context(
                pair, tuple(self._judgments), self._preference.get()
            )
        except ValueError as exc:
            self._status.set(str(exc))
            return
        self._busy = True

        def ready(_unused: None) -> None:
            self._busy = False
            if self._current() and self._comparison_ready() and self._pair is pair:
                self._feedback_saved = True
                self._save_feedback(context, source_proof=pair)
                if self.winfo_exists():
                    self._status.set(
                        "Save was not confirmed. See the Review Feedback status before retrying."
                    )

        def failed(_exc: Exception) -> None:
            self._busy = False
            self._status.set("The comparison images changed. Reopen inspection before saving.")

        self._work.submit("feedback", pair.require_current, on_result=ready, on_error=failed)
