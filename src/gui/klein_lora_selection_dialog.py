"""One batch review of ordered verified candidates, on the Tk thread only."""

from __future__ import annotations

import tkinter as tk
from tkinter import messagebox, ttk
from typing import Any

from src.prompting.pack_lora_selection import KleinSelectionError, SelectionChoice


def review_loras(parent: Any, requests: Any, *, visible: bool, is_current: Any) -> Any:
    dialog = tk.Toplevel(parent)
    dialog.title("Klein PromptPack LoRA Selection")
    dialog.transient(parent)
    frame = ttk.Frame(dialog, padding=12)
    frame.pack(fill="both", expand=True)
    ttk.Label(
        frame,
        text="Klein admits one verified adapter per prompt. Authored PromptPacks stay unchanged.",
    ).pack(anchor="w")
    dialog.geometry("820x620")
    canvas = tk.Canvas(frame, highlightthickness=0)
    scrollbar = ttk.Scrollbar(frame, orient="vertical", command=canvas.yview)
    scrollbar.pack(side="right", fill="y")
    canvas.pack(fill="both", expand=True)
    body = ttk.Frame(canvas)
    window = canvas.create_window((0, 0), window=body, anchor="nw")
    canvas.configure(yscrollcommand=scrollbar.set)
    body.bind("<Configure>", lambda _: canvas.configure(scrollregion=canvas.bbox("all")))
    canvas.bind("<Configure>", lambda event: canvas.itemconfigure(window, width=event.width))
    rows = []
    result = None
    for number, request in enumerate(requests):
        group = ttk.LabelFrame(
            body, text=request.label if visible else f"Prompt {number + 1}", padding=6
        )
        group.pack(fill="x", pady=4)
        choices = {
            "First compatible": SelectionChoice("first"),
            "Last compatible": SelectionChoice("last"),
            "None": SelectionChoice("none"),
        }
        for index in request.compatible_indices:
            lora = request.source[index]
            label = (
                f"{lora.name} ({lora.weight:g})" if visible else f"Compatible adapter {index + 1}"
            )
            choices[f"Specific: {label}"] = SelectionChoice("specific", index)
        for index, decision in enumerate(request.decisions):
            label = request.source[index].name if visible else f"Adapter {index + 1}"
            detail = decision.reason if visible else "Exact policy assessment"
            ttk.Label(
                group, text=f"{label}: {decision.status.value} — {detail}", wraplength=720
            ).pack(anchor="w")
        variable = tk.StringVar(value="Choose..." if request.requires_choice else "Automatic")
        if request.requires_choice:
            ttk.Combobox(
                group, textvariable=variable, values=list(choices), state="readonly", width=65
            ).pack(fill="x")
        else:
            ttk.Label(
                group,
                text=f"Automatic: {len(request.compatible_indices)} verified-compatible adapter(s)",
            ).pack(anchor="w")
        rows.append((request, variable, choices))
    shared = tk.StringVar(value="Independent choices")
    ttk.Label(frame, text="Optional apply to all prompts requiring a decision:").pack(
        anchor="w", pady=(8, 0)
    )
    ttk.Combobox(
        frame,
        textvariable=shared,
        values=["Independent choices", "First compatible", "Last compatible", "None"],
        state="readonly",
    ).pack(fill="x")

    def accept() -> None:
        nonlocal result
        decisions = []
        try:
            if not is_current():
                raise KleinSelectionError("Source changed; cancel and rebuild Preview")
            for request, variable, choices in rows:
                if request.requires_choice:
                    choice = choices.get(
                        shared.get() if shared.get() != "Independent choices" else variable.get()
                    )
                    if choice is None:
                        raise KleinSelectionError("Choose an adapter or none for every prompt")
                else:
                    choice = SelectionChoice("auto")
                request.choose(choice)
                decisions.append(choice)
        except KleinSelectionError as exc:
            messagebox.showerror("Selection incomplete", str(exc), parent=dialog)
            return
        result = decisions
        dialog.destroy()

    actions = ttk.Frame(frame)
    actions.pack(fill="x", pady=(8, 0))
    ttk.Button(actions, text="Cancel", command=dialog.destroy).pack(side="right")
    ttk.Button(actions, text="Use selections", command=accept).pack(side="right", padx=5)

    def poll() -> None:
        if not is_current():
            dialog.destroy()
        elif dialog.winfo_exists():
            dialog.after(100, poll)

    dialog.protocol("WM_DELETE_WINDOW", dialog.destroy)
    dialog.after(100, poll)
    dialog.grab_set()
    dialog.wait_window()
    return result
