"""Progressively disclosed findings review inside Learning's existing Recommendations area."""

from __future__ import annotations

import tkinter as tk
from collections.abc import Callable
from pathlib import Path
from tkinter import messagebox, ttk
from typing import Any

from src.gui.controllers.learning_profile_publication import (
    LearningProfilePublicationCoordinator,
    controller_context,
)
from src.gui.view_contracts.edit_work_runner import build_edit_work_runner
from src.gui.widgets.disclosure_section_v2 import DisclosureSection
from src.learning.profile_publication import (
    LIMITATION,
    ProfilePublicationService,
    PublicationProposal,
)
from src.learning.resource_access import get_projected_resources
from src.learning.variable_selection_contract import normalize_resource_entries


class LearningProfilePublicationPanel(ttk.Frame):
    def __init__(self, parent: tk.Misc, *, controller_getter: Callable[[], Any]) -> None:
        super().__init__(parent)
        self._controller_getter = controller_getter
        self._coordinator: LearningProfilePublicationCoordinator | None = None
        self._last_context: Any = None
        self._proposal: PublicationProposal | None = None
        self._lineages: tuple[Any, ...] = ()
        self._status = tk.StringVar(value="Review saved controlled findings for this exact model.")
        section = DisclosureSection(
            self, title="Save Findings as Generation Profile", expanded=False
        )
        section.pack(fill="x")
        body = section.body
        ttk.Label(body, textvariable=self._status, wraplength=340, justify="left").pack(fill="x")
        self.review_button = ttk.Button(body, text="Review Profile Findings", command=self.review)
        self.review_button.pack(anchor="w", pady=4)
        self._destination = tk.StringVar(value="New Learning profile")
        self.destination = ttk.Combobox(
            body, textvariable=self._destination, state="readonly", values=("New Learning profile",)
        )
        self.destination.pack(fill="x", pady=3)
        self.destination.bind("<<ComboboxSelected>>", lambda _event: self._render_details())
        self._profile_name_var = tk.StringVar(value="Learning findings")
        ttk.Label(body, text="Profile name").pack(anchor="w")
        self.name_entry = ttk.Entry(body, textvariable=self._profile_name_var)
        self.name_entry.pack(fill="x")
        self.details = tk.Text(body, height=9, width=32, wrap="word", state="disabled")
        self.details.pack(fill="x", pady=4)
        self.publish_button = ttk.Button(
            body, text="Publish Learning Profile", state="disabled", command=self.publish
        )
        self.publish_button.pack(anchor="w")
        self.bind("<Destroy>", self._destroyed, add="+")
        self._watch_id = self.after(250, self._watch_context)

    def _get_coordinator(self) -> LearningProfilePublicationCoordinator:
        if self._coordinator is None:
            controller = self._controller_getter()
            profile_controller = controller.app_controller.generation_profiles
            writer = controller._learning_record_writer
            if writer is None:
                raise ValueError("The Learning ratings store is unavailable.")
            self._coordinator = LearningProfilePublicationCoordinator(
                service=ProfilePublicationService(
                    profile_controller.service.store, profile_controller.service
                ),
                records_path=Path(writer.records_path),
                runner=build_edit_work_runner(self),
                context=lambda: controller_context(self._controller_getter()),
                catalogs=self._catalogs,
                show=self._show,
                refresh_catalog=profile_controller.notify_changed,
            )
            self._last_context = self._coordinator.context()
        return self._coordinator

    def _catalogs(self) -> dict[str, Any]:
        resources = get_projected_resources(self._controller_getter())
        return {
            key: list(normalize_resource_entries(list(resources.get(key) or []))[1].values())
            for key in ("samplers", "schedulers", "vaes")
        }

    def _watch_context(self) -> None:
        controller = self._controller_getter()
        if controller is not None:
            context = controller_context(controller)
            if self._last_context is not None and context != self._last_context:
                if self._coordinator is not None:
                    self._coordinator.invalidate()
                self._proposal = None
                self.publish_button.configure(state="disabled")
                self.review_button.configure(state="normal")
                self._status.set(
                    "Selection changed. Review findings for the current experiment and model."
                )
            self._last_context = context
        self._watch_id = self.after(250, self._watch_context)

    def review(self) -> None:
        try:
            self._get_coordinator().review()
        except (AttributeError, ValueError, RuntimeError) as exc:
            self._show("error", str(exc))

    def _show(self, state: str, value: Any) -> None:
        self.review_button.configure(state="disabled" if state == "busy" else "normal")
        self.publish_button.configure(state="disabled")
        if state == "proposal":
            self._proposal = value
            self._lineages = value.lineages
            labels = ("New Learning profile",) + tuple(
                f"{p.name} — revision {p.revision}" for p in self._lineages
            )
            self.destination.configure(values=labels)
            self._destination.set(labels[0])
            self._status.set(
                "Qualified settings found." if value.ready else " ".join(value.blockers)
            )
            self.publish_button.configure(state="normal" if value.ready else "disabled")
            self._render_details()
        else:
            if state == "success":
                self._proposal = None
            self._status.set(str(value))

    def _selected_lineage(self) -> Any:
        index = self.destination.current()
        return self._lineages[index - 1] if 0 < index <= len(self._lineages) else None

    def _render_details(self) -> None:
        proposal = self._proposal
        if proposal is None:
            return
        previous = self._selected_lineage()
        published = proposal.already_published(previous.ref if previous else None)
        self.publish_button.configure(
            state="normal" if proposal.ready and published is None else "disabled"
        )
        if published is not None:
            self._status.set(
                f"These findings are already published as {published.name}, revision {published.revision}."
            )
        elif proposal.ready:
            self._status.set("Qualified settings found.")
        lines = [
            f"Model: {proposal.model.display_name}",
            f"SHA-256: {proposal.model.sha256 or 'exact executable profile'}",
            f"Executable profile: {dict(proposal.model.exact_profile or {})}",
            "Operation: txt2img",
            f"{proposal.experiment_count} eligible experiments; {proposal.sample_count} saved samples.",
        ]
        for finding in proposal.findings:
            lines.extend(
                (
                    finding.rationale,
                    f"Tested values: {finding.tested_values}",
                    f"Evidence: {finding.evidence_digest}",
                )
            )
        lines.extend(("Comparison:", *proposal.differences(previous), "Excluded settings:"))
        lines.extend(f"{key}: {reason}" for key, reason in proposal.excluded)
        lines.append(LIMITATION)
        self.details.configure(state="normal")
        self.details.delete("1.0", tk.END)
        self.details.insert("1.0", "\n".join(lines))
        self.details.configure(state="disabled")

    def publish(self) -> None:
        if self._proposal is None or not self._proposal.ready:
            return
        coordinator = self._get_coordinator()
        previous = self._selected_lineage()
        name = self._profile_name_var.get().strip()
        if not name:
            self._show("error", "Enter a profile name before publication.")
            return
        revision = previous.revision + 1 if previous else 1
        confirmed = messagebox.askyesno(
            "Publish Learning Profile",
            f"Publish {name}, revision {revision}, for {self._proposal.model.display_name}?\n\n"
            + "\n".join(self._proposal.differences(previous)),
            parent=self,
        )
        coordinator.publish(
            name=name, lineage=previous.ref if previous else None, confirmed=confirmed
        )

    def _destroyed(self, event: tk.Event[Any]) -> None:
        if event.widget is self:
            self.after_cancel(self._watch_id)
            if self._coordinator is not None:
                self._coordinator.close()
