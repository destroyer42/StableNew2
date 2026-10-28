"""Operator selection of offline qualification drafts; no execution controls or admission."""

from __future__ import annotations

import tkinter as tk
from tkinter import ttk
from tkinter.scrolledtext import ScrolledText
from typing import Any

from src.learning.evidence_autopilot import ProposalPlan, describe


def choose_prompt_context(
    parent: tk.Toplevel, selected: dict[str, Any] | None, current: tuple[str, str]
) -> tuple[str, str, dict[str, Any]] | None:
    """One compact source choice, only on Preview or explicit Change; never on discovery/save."""
    window = tk.Toplevel(parent)
    window.title("Qualification prompt context")
    window.columnconfigure(1, weight=1)
    options = (["Selected Learning PromptPack row"] if selected else []) + [
        "Custom qualification prompt"
    ]
    source = tk.StringVar(window, value=options[0])
    ttk.Label(window, text="Use for every selected Preview").grid(row=0, column=0, padx=8, pady=8)
    ttk.Combobox(window, textvariable=source, values=options, state="readonly", width=40).grid(
        row=0, column=1, padx=8, pady=8
    )
    ttk.Label(window, text="Custom positive").grid(row=1, column=0, padx=8)
    positive = tk.Text(window, width=65, height=4)
    positive.grid(row=1, column=1, padx=8, pady=4)
    positive.insert("1.0", current[0])
    ttk.Label(window, text="Custom negative").grid(row=2, column=0, padx=8)
    negative = tk.Text(window, width=65, height=3)
    negative.grid(row=2, column=1, padx=8, pady=4)
    negative.insert("1.0", current[1])
    status = tk.StringVar(
        window, value="Preview freezes the source; this does not admit generation."
    )
    ttk.Label(window, textvariable=status).grid(row=3, column=0, columnspan=2, padx=8, pady=4)
    result = []

    def accept() -> None:
        if source.get() == "Selected Learning PromptPack row" and selected:
            prompt, neg = (
                str(selected.get("prompt_text", "")),
                str(selected.get("negative_prompt_text", "")),
            )
            metadata = {
                "prompt_source": "pack",
                "selected_prompt_pack_path": selected.get("prompt_pack_path", ""),
                "selected_prompt_pack_name": selected.get("prompt_pack_name", ""),
                "selected_prompt_index": selected.get("prompt_index", 0),
                "selected_prompt_label": selected.get("label", ""),
            }
        else:
            prompt, neg = positive.get("1.0", "end").strip(), negative.get("1.0", "end").strip()
            metadata = {"prompt_source": "custom"}
        if not prompt or len(prompt) > 16000 or len(neg) > 16000:
            status.set("Choose a nonempty positive prompt of at most 16,000 characters.")
            return
        result.append((prompt, neg, metadata))
        window.destroy()

    actions = ttk.Frame(window, padding=8)
    actions.grid(row=4, column=0, columnspan=2, sticky="e")
    ttk.Button(actions, text="Cancel", command=window.destroy).pack(side="left", padx=6)
    ttk.Button(actions, text="Use context for Preview", command=accept).pack(side="left")
    window.transient(parent)
    window.grab_set()
    parent.wait_window(window)
    return result[0] if result else None


class ModelEvidenceProposalsDialog(tk.Toplevel):
    def __init__(self, owner: Any, plan: ProposalPlan) -> None:
        super().__init__(owner)
        self.owner, self.plan = owner, plan
        self.title("Proposed Experiments — qualification drafts")
        self.geometry(
            f"{min(1080, self.winfo_screenwidth() - 24)}x{min(700, self.winfo_screenheight() - 96)}"
        )
        self.columnconfigure(0, weight=1)
        self.rowconfigure(2, weight=1)
        self.rowconfigure(4, weight=1)
        self.proposals = {p.proposal_id: p for p in plan.proposals}
        self.checked = {p.proposal_id for p in plan.proposals if p.document["default_selected"]}
        self.status = tk.StringVar()
        ttk.Label(
            self,
            text="Choose supported experiments. Queue to Learning saves drafts only; Run remains in Learning.",
            padding=6,
        ).grid(row=0, column=0, sticky="ew")
        ttk.Label(self, textvariable=self.status, padding=6).grid(row=1, column=0, sticky="ew")
        table = ttk.Frame(self)
        table.grid(row=2, column=0, sticky="nsew", padx=6)
        table.rowconfigure(0, weight=1)
        table.columnconfigure(0, weight=1)
        self.tree = ttk.Treeview(
            table, columns=("selected", "variable", "images", "tier"), selectmode="browse"
        )
        self.tree.heading("#0", text="Experiment / explanation")
        self.tree.column("#0", width=580)
        for key, label in (
            ("selected", "Select"),
            ("variable", "Setting"),
            ("images", "Images"),
            ("tier", "Evidence"),
        ):
            self.tree.heading(key, text=label)
            self.tree.column(key, width=85)
        self.tree.grid(row=0, column=0, sticky="nsew")
        vertical = ttk.Scrollbar(table, orient="vertical", command=self.tree.yview)
        horizontal = ttk.Scrollbar(table, orient="horizontal", command=self.tree.xview)
        vertical.grid(row=0, column=1, sticky="ns")
        horizontal.grid(row=1, column=0, sticky="ew")
        self.tree.configure(yscrollcommand=vertical.set, xscrollcommand=horizontal.set)
        self.tree.tag_configure("blocked", foreground="#888888")
        for group, label in (
            ("ready", "Runnable P1 qualification pilots"),
            ("optional", "Optional / descriptive"),
            ("blocked", "Blocked / research / metadata only"),
        ):
            self.tree.insert("", "end", iid=group, text=label, open=True)
        for proposal in plan.proposals:
            doc = proposal.document
            group = (
                "ready"
                if proposal.runnable and doc["priority"] == "P1"
                else "optional"
                if proposal.runnable
                else "blocked"
            )
            tier = (
                ", ".join(dict.fromkeys(r["classification"] for r in doc.get("evidence_refs", [])))
                or "No alternate"
            )
            self.tree.insert(
                group,
                "end",
                iid=proposal.proposal_id,
                text=doc["name"],
                values=(
                    "Checked"
                    if proposal.proposal_id in self.checked
                    else "Unchecked"
                    if proposal.runnable
                    else "Unavailable",
                    doc["variable"],
                    doc["expected_images"] or "—",
                    tier,
                ),
                tags=() if proposal.runnable else ("blocked",),
            )
        self.tree.bind("<Button-1>", self._click)
        self.tree.bind("<space>", lambda _event: self._toggle())
        self.tree.bind("<<TreeviewSelect>>", lambda _event: self._describe())
        prompt = ttk.Frame(self, padding=6)
        prompt.grid(row=3, column=0, sticky="ew")
        ttk.Label(
            prompt, text="One prompt context is resolved only when Preview is requested."
        ).pack(side="left")
        ttk.Button(
            prompt,
            text="Change prompt context…",
            command=lambda: owner._choose_qualification_prompt(change=True),
        ).pack(side="right")
        self.details = ScrolledText(self, height=12, wrap="word", state="disabled")
        self.details.grid(row=4, column=0, sticky="nsew", padx=6)
        actions = ttk.Frame(self, padding=6)
        actions.grid(row=5, column=0, sticky="ew")
        self.save_button = ttk.Button(
            actions,
            text="Save Drafts",
            command=lambda: owner._save_selected(self, queue_to_learning=False),
        )
        self.save_button.pack(side="left")
        self.preview_button = ttk.Button(
            actions, text="Preview Selected", command=lambda: owner._preview_selected(self)
        )
        self.preview_button.pack(side="left", padx=6)
        self.queue_button = ttk.Button(
            actions,
            text="Queue to Learning (drafts)",
            command=lambda: owner._save_selected(self, queue_to_learning=True),
        )
        self.queue_button.pack(side="left")
        ttk.Button(
            actions, text="Open highlighted draft", command=lambda: owner._open_draft(self)
        ).pack(side="right")
        self._update_count()

    def selection_ids(self) -> tuple[str, ...]:
        return tuple(p.proposal_id for p in self.plan.proposals if p.proposal_id in self.checked)

    def _click(self, event: Any) -> None:
        if self.tree.identify_column(event.x) == "#1":
            row = self.tree.identify_row(event.y)
            if row in self.proposals:
                self.tree.selection_set(row)
                self._toggle()

    def _toggle(self) -> str:
        selected = self.tree.selection()
        proposal = self.proposals.get(selected[0]) if selected else None
        if proposal and proposal.runnable:
            if proposal.proposal_id in self.checked:
                self.checked.remove(proposal.proposal_id)
            else:
                self.checked.add(proposal.proposal_id)
            self.tree.set(
                proposal.proposal_id,
                "selected",
                "Checked" if proposal.proposal_id in self.checked else "Unchecked",
            )
            self._update_count()
        return "break"

    def _update_count(self) -> None:
        docs = [self.proposals[p].document for p in self.selection_ids()]
        images = sum(d["expected_images"] for d in docs)
        work = sum(d.get("estimated_work", {}).get("denoising_steps", 0) for d in docs)
        self.status.set(
            f"Selected: {len(docs)} experiments / {images} images / {work:g} estimated denoising steps. Nothing has been admitted."
        )
        for button in (self.save_button, self.preview_button, self.queue_button):
            button.configure(state="normal" if docs else "disabled")

    def show(self, text: str) -> None:
        self.details.configure(state="normal")
        self.details.delete("1.0", "end")
        self.details.insert("1.0", text)
        self.details.configure(state="disabled")

    def _describe(self) -> None:
        selected = self.tree.selection()
        proposal = self.proposals.get(selected[0]) if selected else None
        if proposal:
            self.show(describe(proposal))

    def refuse_stale(self) -> None:
        self.status.set("Findings changed. Close this list and replan before saving or previewing.")
        self.checked.clear()
        for proposal_id, proposal in self.proposals.items():
            if proposal.runnable:
                self.tree.set(proposal_id, "selected", "Unchecked (stale)")
        for button in (self.save_button, self.preview_button, self.queue_button):
            button.configure(state="disabled")
