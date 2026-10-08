"""Tk batch choices never expose hidden identities or mutate PromptPacks."""

import tkinter as tk
from tkinter import ttk

import pytest

from src.gui.klein_lora_selection_dialog import review_loras
from src.image_backends.model_policy import resolve_model_policy
from src.prompting.pack_lora_selection import SelectionChoice, assess_target_loras
from src.prompting.prompt_adaptation import LoraContribution
from tests.pipeline.test_klein_pack_selection_143 import KLEIN, S, resolve


def descendants(widget):
    for child in widget.winfo_children():
        yield child
        yield from descendants(child)


@pytest.mark.parametrize("mode", ["First compatible", "Last compatible", "None", "Cancel"])
def test_batch_apply_all_and_cancel(mode):
    root = tk.Tk()
    root.withdraw()
    assessment = assess_target_loras(
        resolve_model_policy(KLEIN),
        tuple(LoraContribution(n, 0.8, "pack") for n in ("SECRET_A", "SECRET_B")),
        resolve({"SECRET_A": S.COMPATIBLE, "SECRET_B": S.COMPATIBLE}),
        label="SECRET_PACK",
    )

    def choose():
        widgets = list(descendants(root))
        texts = [str(w.cget("text")) for w in widgets if isinstance(w, (ttk.Label, ttk.LabelFrame))]
        assert not any("SECRET" in text for text in texts)
        combos = [w for w in widgets if isinstance(w, ttk.Combobox)]
        assert len(combos) == 3
        if mode != "Cancel":
            combos[-1].set(mode)
        button = next(
            w
            for w in widgets
            if isinstance(w, ttk.Button)
            and w.cget("text") == ("Cancel" if mode == "Cancel" else "Use selections")
        )
        button.invoke()

    root.after(20, choose)
    try:
        choices = review_loras(
            root, [assessment, assessment], visible=False, is_current=lambda: True
        )
        expected = {"First compatible": "first", "Last compatible": "last", "None": "none"}.get(
            mode
        )
        assert choices == ([SelectionChoice(expected)] * 2 if expected else None)
    finally:
        root.destroy()


def test_independent_specific_and_none():
    root = tk.Tk()
    root.withdraw()
    assessment = assess_target_loras(
        resolve_model_policy(KLEIN),
        tuple(LoraContribution(n, 0.8, "pack") for n in ("A", "B")),
        resolve({"A": S.COMPATIBLE, "B": S.COMPATIBLE}),
    )

    def choose():
        widgets = list(descendants(root))
        combos = [w for w in widgets if isinstance(w, ttk.Combobox)]
        combos[0].set("Specific: B (0.8)")
        combos[1].set("None")
        next(
            w for w in widgets if isinstance(w, ttk.Button) and w.cget("text") == "Use selections"
        ).invoke()

    root.after(20, choose)
    try:
        assert review_loras(
            root, [assessment, assessment], visible=True, is_current=lambda: True
        ) == [SelectionChoice("specific", 1), SelectionChoice("none")]
    finally:
        root.destroy()
