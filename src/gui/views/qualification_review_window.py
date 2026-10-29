"""Guided Compare & Rate over verified qualification pairs and existing image ratings."""

from __future__ import annotations

import copy
import json
import tkinter as tk
from tkinter import messagebox, simpledialog, ttk
from typing import Any

from src.gui.view_contracts.edit_work_runner import build_edit_work_runner
from src.gui.views.qualification_rating_card import RatingCard
from src.gui.widgets.disclosure_section_v2 import DisclosureSection
from src.gui.widgets.scrollable_frame_v2 import ScrollableFrame
from src.gui_v2.qualification_review_session import QualificationReviewSession
from src.learning.experiment_execution import snapshot_digest, thaw_snapshot
from src.learning.qualification_review import project_qualification


class QualificationReviewWindow(tk.Toplevel):
    def __init__(self, panel: Any) -> None:
        super().__init__(panel)
        self.panel = panel
        self.learning_controller = panel._get_learning_controller()
        self.session = QualificationReviewSession(self.learning_controller)
        self.app_state = getattr(self.learning_controller, "app_state", None)
        self.runner = build_edit_work_runner(self)
        self.findings = None
        self.entries: list[Any] = []
        self.index = 0
        self.title("Compare & Rate — Qualification")
        self.geometry(
            f"{min(1100, self.winfo_screenwidth() - 24)}x{min(760, self.winfo_screenheight() - 80)}"
        )
        self.minsize(520, 360)
        self.scroll = ScrollableFrame(self)
        self.scroll.pack(fill="both", expand=True)
        host = self.scroll.inner
        host.columnconfigure(0, weight=1)
        self.heading = tk.StringVar(self, value="Checking saved execution evidence…")
        ttk.Label(host, textvariable=self.heading, wraplength=850, justify="left").pack(
            fill="x", padx=8, pady=6
        )
        options = ttk.Frame(host)
        options.pack(fill="x", padx=8)
        self.alternative = tk.StringVar(self)
        self.alternatives = ttk.Combobox(
            options, textvariable=self.alternative, state="readonly", width=32
        )
        self.alternatives.pack(side="left")
        self.alternatives.bind("<<ComboboxSelected>>", lambda _e: self._select_entries())
        self.individual = tk.BooleanVar(
            self,
            value=bool(self.session.experiment.metadata.get("qualification_review_individual")),
        )
        ttk.Checkbutton(
            options,
            text="Individual images (including exclusions)",
            variable=self.individual,
            command=self._select_entries,
        ).pack(side="left", padx=5)
        self.position = tk.StringVar(self)
        ttk.Label(host, textvariable=self.position).pack(fill="x", padx=8)
        images = ttk.Frame(host)
        images.pack(fill="both", expand=True, padx=6, pady=6)
        images.columnconfigure((0, 1), weight=1, uniform="pair")
        self.cards = (
            RatingCard(images, self, "Control / baseline"),
            RatingCard(images, self, "Candidate"),
        )
        for column, card in enumerate(self.cards):
            card.grid(row=0, column=column, sticky="nsew", padx=3)
        nav = ttk.Frame(host, padding=6)
        nav.pack(fill="x")
        for text, action in (
            ("Previous Pair", lambda: self._move(-1)),
            ("Save & Next Pair", self._save_next),
            ("Next Unrated Pair", self._next_unrated),
            ("Back to Experiment", self.destroy),
        ):
            ttk.Button(nav, text=text, command=action).pack(side="left", padx=3)
        self.message = tk.StringVar(self)
        ttk.Label(host, textvariable=self.message, wraplength=850).pack(fill="x", padx=8)
        self.details = DisclosureSection(host, title="Evidence Details", expanded=False)
        self.details.pack(fill="x", padx=8, pady=5)
        self.evidence = tk.Text(self.details.body, height=10, wrap="word", state="disabled")
        self.evidence.pack(fill="x")
        self.next_button = ttk.Button(host, text="Suggested Next Step", command=self._next_step)
        self.next_button.pack(anchor="w", padx=8, pady=4)
        self.followup = ttk.Button(
            host,
            text="Prepare Follow-Up Experiment",
            command=self._prepare_followup,
            state="disabled",
        )
        self.followup.pack(anchor="w", padx=8, pady=4)
        self.bind("<Destroy>", self._closed, add="+")
        self.refresh()

    def _closed(self, event: Any) -> None:
        if event.widget is self:
            self.session.closed = True
            self.runner.close()

    def destroy(self) -> None:
        if self.session.live:
            self._stage()
        self.session.closed = True
        self.runner.close()
        super().destroy()

    def _stage(self) -> None:
        for card in self.cards:
            card.stage()

    def refresh(self, *, advance: bool = False) -> None:
        if not self.session.live:
            self.message.set("Experiment changed; close this view and reopen its review.")
            return
        experiment = copy.deepcopy(self.session.experiment)
        plan = copy.deepcopy(self.learning_controller.learning_state.plan)
        ratings = copy.deepcopy(self.learning_controller._rating_details_cache)
        self.runner.submit(
            "findings",
            lambda: project_qualification(experiment, plan, ratings),
            on_result=lambda result: self._render(result, advance),
            on_error=lambda exc: self.message.set(str(exc)),
        )

    def _render(self, result: Any, advance: bool) -> None:
        if not self.session.live:
            return
        self.findings = result
        lines = [
            f"{self.session.experiment.name} — Experiment Outcome: {result.outcome}",
            f"{result.setting}: {' vs '.join(map(str, result.values))}. Controlled rated pairs: {result.rated_pairs}/{result.expected_pairs}.",
            result.reason,
        ]
        for row in result.comparisons:
            mean = (
                f"{row.mean_difference:+.2f}" if row.mean_difference is not None else "unavailable"
            )
            lines.append(
                f"Candidate {row.value}: {row.wins} wins / {row.ties} ties / {row.losses} losses ({row.rated}/{row.pairs} rated pairs); mean difference {mean}."
            )
        self.heading.set("\n".join(lines))
        alternatives = tuple(str(value) for value in result.values[1:])
        self.alternatives.configure(values=alternatives)
        restored_index = self.session.position(result.pairs)
        if result.pairs and not self.alternative.get():
            self.alternative.set(str(result.pairs[restored_index].candidate.value))
        elif self.alternative.get() not in alternatives and alternatives:
            self.alternative.set(alternatives[0])
        self.next_button.configure(text="Suggested Next Step: " + result.next_action)
        self.followup.configure(
            state="normal"
            if result.outcome in {"Follow-up supported", "Inconclusive"}
            else "disabled"
        )
        snapshot = (
            thaw_snapshot(self.session.experiment.execution_snapshot_json)
            if self.session.experiment.execution_snapshot_json
            else {}
        )
        details = {
            "frozen_model": snapshot.get("model_identity"),
            "source_proposal": (snapshot.get("evidence_proposal") or {}).get("proposal_id"),
            "catalog_revision": (snapshot.get("evidence_proposal") or {}).get("catalog_revision"),
            "per_value_valid_rated_mean": result.per_value,
            "exclusions": result.exclusions,
            "samples": [vars(s) for s in result.samples],
            "comparisons": [vars(r) for r in result.comparisons],
            "settings": [
                (v.param_value, v.execution_metadata.get("qualification_setting_evidence"))
                for v in self.learning_controller.learning_state.plan
            ],
        }
        self.evidence.configure(state="normal")
        self.evidence.delete("1.0", "end")
        self.evidence.insert("1.0", json.dumps(details, indent=2, default=str))
        self.evidence.configure(state="disabled")
        self._select_entries(stage=False, restore=True)
        if advance:
            self._move(1)

    def _select_entries(self, *, stage: bool = True, restore: bool = True) -> None:
        if not self.findings or not self.session.live:
            return
        if stage:
            self._stage()
        self.entries = (
            [p for p in self.findings.pairs if str(p.candidate.value) == self.alternative.get()]
            if not self.individual.get()
            else []
        )
        if not self.entries:
            self.entries = list(self.findings.samples)
        identity = tuple(
            self.session.experiment.metadata.get("qualification_review_position") or ()
        )
        if self.individual.get() or not self.findings.pairs:
            identity = tuple(
                self.session.experiment.metadata.get("qualification_individual_position") or ()
            )
        self.index = (
            next(
                (
                    i
                    for i, entry in enumerate(self.entries)
                    if getattr(
                        entry,
                        "identity",
                        (getattr(entry, "variant_id", ""), getattr(entry, "image_ref", "")),
                    )
                    == identity
                ),
                0,
            )
            if restore
            else 0
        )
        self._show()

    def _show(self) -> None:
        if not self.entries or not self.session.live:
            self.position.set("No output images available; inspect execution evidence.")
            return
        entry = self.entries[self.index]
        paired = hasattr(entry, "control")
        self.position.set(
            f"{'Comparison' if paired else 'Individual image'} {self.index + 1}/{len(self.entries)}"
        )
        self.cards[0].show(entry.control if paired else entry)
        self.cards[1].show(entry.candidate if paired else None)
        if paired:
            self.session.remember(entry)
        else:
            self.session.experiment.metadata["qualification_individual_position"] = [
                entry.variant_id,
                entry.image_ref,
            ]
        self.session.experiment.metadata["qualification_review_individual"] = self.individual.get()
        self.learning_controller._notify_resume_state_changed()

    def _move(self, delta: int) -> None:
        if self.entries and self.session.live:
            self._stage()
            self.index = (self.index + delta) % len(self.entries)
            self._show()

    def _save_next(self) -> None:
        if not self.session.live:
            return
        outcomes: list[bool] = []
        for card in self.cards:
            if card.sample:
                ok, text = self.session.save(
                    card.sample.image_ref,
                    card.payload(),
                    lambda _ref: messagebox.askyesno(
                        "Override Rating", "Replace this image's saved rating?", parent=self
                    ),
                )
                card.status.set(text)
                outcomes.append(ok)
        if outcomes and all(outcomes):
            self.message.set(
                "Both image ratings saved." if len(outcomes) == 2 else "Image rating saved."
            )
            self.refresh(advance=True)
        else:
            self.message.set(
                "Not fully saved. Each image shows its own state; drafts retained. Navigation has not advanced."
            )

    def _next_unrated(self) -> None:
        if not self.session.live:
            return
        self._stage()
        for offset in range(1, len(self.entries) + 1):
            index = (self.index + offset) % len(self.entries)
            entry = self.entries[index]
            samples = (entry.control, entry.candidate) if hasattr(entry, "control") else (entry,)
            if any(
                self.learning_controller.get_rating_for_image(s.image_ref) is None for s in samples
            ):
                self.index = index
                self._show()
                return
        self.message.set("All reviewable images in this comparison have saved ratings.")

    def _owner(self) -> Any:
        owner = self.panel
        while owner is not None and not hasattr(owner, "experiment_store"):
            owner = getattr(owner, "master", None)
        return owner

    def _next_step(self) -> None:
        if not self.session.live or not self.findings:
            return
        if self.findings.next_action == "Finish Rating":
            self._next_unrated()
        elif self.findings.next_action == "Inspect Execution Evidence":
            self.details.set_expanded(True)
        elif self.findings.next_action == "Investigate Further":
            self._prepare_followup()
        else:
            owner = self._owner()
            if owner is not None:
                from src.gui.views.model_evidence_window import open_model_evidence

                window = open_model_evidence(owner)
                snapshot = thaw_snapshot(self.session.experiment.execution_snapshot_json)
                window.request_next_test(snapshot["model_identity"]["display_name"])

    def _prepare_followup(self) -> None:
        if (
            not self.session.live
            or not self.findings
            or self.findings.outcome not in {"Follow-up supported", "Inconclusive"}
        ):
            return
        from src.gui.controllers.model_evidence_proposals import capture_resources
        from src.gui.views.model_evidence_proposals_dialog import choose_prompt_context

        chosen = choose_prompt_context(self, None, ("", ""))
        if chosen is None or not self.session.live:
            return
        seed = simpledialog.askinteger(
            "Follow-up seed cohort",
            "Explicit base seed (0–4294967295). Choose a separate cohort or a new prompt.",
            parent=self,
            minvalue=0,
            maxvalue=2**32 - 1,
        )
        if seed is None or not self.session.live:
            return
        owner = self._owner()
        if owner is None:
            self.message.set("Experiment Library is unavailable.")
            return
        experiment = copy.deepcopy(self.session.experiment)
        plan = copy.deepcopy(self.learning_controller.learning_state.plan)
        ratings = copy.deepcopy(self.learning_controller._rating_details_cache)
        resources = capture_resources(self.learning_controller)
        from src.learning.evidence_autopilot import digest

        evidence_revision = digest({"plan": [v.to_dict() for v in plan], "ratings": ratings})
        candidate = next(v for v in self.findings.values[1:] if str(v) == self.alternative.get())
        self.followup.configure(state="disabled")

        def work() -> Any:
            from src.gui.controllers.qualification_review import prepare_validated_followup

            return prepare_validated_followup(
                experiment,
                plan,
                ratings,
                resources,
                candidate=candidate,
                prompt=chosen[0],
                negative=chosen[1],
                seed=seed,
            )

        def prepared(draft: Any) -> None:
            from src.gui.controllers.qualification_review import revalidate_followup_sources
            from src.learning.qualification_followup import save_followup

            if (
                not self.session.live
                or snapshot_digest(self.session.experiment.execution_snapshot_json)
                != draft.parent_revision
            ):
                return
            if capture_resources(self.learning_controller) != resources:
                self.message.set("Resources changed; prepare again. No draft saved.")
                return
            if (
                digest(
                    {
                        "plan": [v.to_dict() for v in self.learning_controller.learning_state.plan],
                        "ratings": self.learning_controller._rating_details_cache,
                    }
                )
                != evidence_revision
            ):
                self.message.set(
                    "Parent execution evidence or ratings changed; prepare again. No draft saved."
                )
                return
            try:
                revalidate_followup_sources(draft)
                experiment_id = save_followup(draft, owner.experiment_store)
            except (OSError, ValueError, KeyError, TypeError) as exc:
                self.message.set(f"Follow-up not saved: {exc}")
                return
            self.message.set(draft.explanation)
            messagebox.showinfo("Follow-up draft prepared", draft.explanation, parent=self)
            if owner._restore_from_store_payload(
                owner.experiment_store.load_session(experiment_id), experiment_id=experiment_id
            ):
                self.destroy()

        self.runner.submit(
            "followup",
            work,
            on_result=prepared,
            on_error=lambda exc: self.message.set(f"Follow-up refused: {exc}"),
            on_complete=lambda _latest, _error: self.followup.configure(state="normal")
            if self.session.live
            else None,
        )
