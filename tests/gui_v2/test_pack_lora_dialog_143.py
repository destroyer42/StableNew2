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


@pytest.fixture
def review_root(request):
    # Reproduce the affected lane's pre-existing interpreter, even in a single-file run.
    other = tk.Tk()
    other.withdraw()
    try:
        root = request.getfixturevalue("tk_root")
        assert tk._default_root is root
        assert root.tk is not other.tk
        yield root
    finally:
        other.destroy()


def run_review(root, monkeypatch, requests, choose, *, visible):
    """Keep callback assertions/error popups out of unbounded Tcl modal waits."""
    errors = []

    def close_dialogs():
        for child in root.winfo_children():
            if isinstance(child, tk.Toplevel):
                child.destroy()

    def callback_error(exc, value, traceback):
        errors.append(value.with_traceback(traceback))
        close_dialogs()

    def error_popup(title, message, **kwargs):
        errors.append(AssertionError(f"{title}: {message}"))
        close_dialogs()

    def guarded_choose():
        try:
            choose()
        except BaseException as exc:
            errors.append(exc)
            close_dialogs()

    def deadline():
        errors.append(AssertionError("Test did not complete its dialog choice within 2 seconds"))
        close_dialogs()

    monkeypatch.setattr(root, "report_callback_exception", callback_error)
    monkeypatch.setattr("src.gui.klein_lora_selection_dialog.messagebox.showerror", error_popup)
    choice_timer = root.after(20, guarded_choose)
    deadline_timer = root.after(2000, deadline)
    try:
        result = review_loras(root, requests, visible=visible, is_current=lambda: True)
    finally:
        root.after_cancel(choice_timer)
        root.after_cancel(deadline_timer)
        close_dialogs()
    if errors:
        raise errors[0]
    return result


@pytest.mark.parametrize("mode", ["First compatible", "Last compatible", "None", "Cancel"])
def test_batch_apply_all_and_cancel(mode, review_root, monkeypatch):
    root = review_root
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

    choices = run_review(root, monkeypatch, [assessment, assessment], choose, visible=False)
    expected = {"First compatible": "first", "Last compatible": "last", "None": "none"}.get(mode)
    assert choices == ([SelectionChoice(expected)] * 2 if expected else None)


def test_independent_specific_and_none(review_root, monkeypatch):
    root = review_root
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

    assert run_review(root, monkeypatch, [assessment, assessment], choose, visible=True) == [
        SelectionChoice("specific", 1), SelectionChoice("none")
    ]


@pytest.mark.parametrize("failure", [AssertionError, pytest.fail.Exception])
@pytest.mark.parametrize("via_tk_callback", [False, True])
def test_callback_failure_leaves_modal_wait_and_fails_the_test(
    review_root, monkeypatch, failure, via_tk_callback
):
    def fail():
        raise failure("callback failure")

    def choose():
        if via_tk_callback:
            review_root.after(0, fail)
        else:
            fail()

    with pytest.raises(failure, match="callback failure"):
        run_review(review_root, monkeypatch, [], choose, visible=False)


def test_invalid_selection_reports_failure_without_opening_an_error_modal(review_root, monkeypatch):
    assessment = assess_target_loras(
        resolve_model_policy(KLEIN),
        tuple(LoraContribution(n, 0.8, "pack") for n in ("A", "B")),
        resolve({"A": S.COMPATIBLE, "B": S.COMPATIBLE}),
    )

    def choose():
        next(
            w for w in descendants(review_root)
            if isinstance(w, ttk.Button) and w.cget("text") == "Use selections"
        ).invoke()

    with pytest.raises(AssertionError, match="Choose an adapter or none"):
        run_review(review_root, monkeypatch, [assessment], choose, visible=False)
