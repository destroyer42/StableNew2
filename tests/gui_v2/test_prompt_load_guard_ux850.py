"""UX-850 P1: loading a PromptPack must not silently replace unsaved edits.

The Load button and the pack-list double-click share one handler. When the working pack has unsaved edits it asks the
same discard/cancel question as New; declining keeps the working pack, its content and its unsaved flag untouched.
"""

from __future__ import annotations

import json
import tkinter as tk
from pathlib import Path

import pytest

from src.gui.prompt_workspace_state import PromptWorkspaceState
from src.gui.views.prompt_tab_frame_v2 import PromptTabFrame

pytestmark = pytest.mark.gui


def _write_pack(path: Path, *texts: str) -> None:
    slots = [{"index": i, "text": text, "negative": f"neg {i}"} for i, text in enumerate(texts)]
    path.write_text(
        json.dumps({"schema_version": 1, "pack_data": {"slots": slots}, "preset_data": {}}),
        encoding="utf-8",
    )


class Dialogs:
    """Records every message box the Prompt tab raises; ``answer`` is what Yes/No returns."""

    def __init__(self) -> None:
        self.asked: list[tuple[str, str]] = []
        self.info: list[tuple[str, str]] = []
        self.errors: list[tuple[str, str]] = []
        self.answer = False
        self.on_ask = None

    def askyesno(self, title: str, message: str, **_kwargs) -> bool:
        self.asked.append((title, message))
        if self.on_ask is not None:
            self.on_ask()
        return self.answer

    def showinfo(self, title: str, message: str, **_kwargs) -> None:
        self.info.append((title, message))

    def showerror(self, title: str, message: str, **_kwargs) -> None:
        self.errors.append((title, message))


@pytest.fixture
def dialogs(monkeypatch: pytest.MonkeyPatch) -> Dialogs:
    recorder = Dialogs()
    monkeypatch.setattr("tkinter.messagebox.askyesno", recorder.askyesno)
    monkeypatch.setattr("tkinter.messagebox.showinfo", recorder.showinfo)
    monkeypatch.setattr("tkinter.messagebox.showerror", recorder.showerror)
    return recorder


@pytest.fixture
def load_calls(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    calls: list[str] = []
    original = PromptWorkspaceState.load_pack

    def spy(self, path):
        calls.append(str(path))
        return original(self, path)

    monkeypatch.setattr(PromptWorkspaceState, "load_pack", spy)
    return calls


@pytest.fixture
def packs_dir(tmp_path: Path) -> Path:
    directory = tmp_path / "packs"
    directory.mkdir()
    _write_pack(directory / "alpha.json", "alpha one", "alpha two")
    _write_pack(directory / "beta.json", "beta one", "beta two")
    return directory


@pytest.fixture
def tab(tk_root: tk.Tk, packs_dir: Path):
    frame = PromptTabFrame(tk_root, packs_dir=packs_dir)
    picker = frame.lora_picker
    if picker._initial_scan is not None:  # never let the real discovery timer run in these tests
        picker.after_cancel(picker._initial_scan)
        picker._initial_scan = None
    yield frame
    frame.destroy()


def _select(frame: PromptTabFrame, name: str) -> None:
    names = list(frame.pack_listbox.get(0, tk.END))
    frame.pack_listbox.selection_clear(0, tk.END)
    frame.pack_listbox.selection_set(names.index(name))


def _open(frame: PromptTabFrame, name: str, load_calls: list[str]) -> None:
    """Load ``name`` as the working pack (clean) and forget that setup call."""
    _select(frame, name)
    frame._on_load_selected_pack()
    load_calls.clear()


def _type_in_editor(frame: PromptTabFrame, root: tk.Tk, text: str) -> None:
    """Edit through the real editor widget, the way an operator does, and let Tk deliver <<Modified>>."""
    frame.editor.insert("end", text)
    root.update()


def _load_button(frame: PromptTabFrame):
    def walk(widget):
        for child in widget.winfo_children():
            if child.winfo_class() == "TButton" and child.cget("text") == "Load":
                return child
            found = walk(child)
            if found is not None:
                return found
        return None

    button = walk(frame)
    assert button is not None, "Load button not found"
    return button


def _snapshot(frame: PromptTabFrame) -> tuple:
    state = frame.workspace_state
    return (
        id(state.current_pack),
        state.current_pack.name,
        [slot.text for slot in state.current_pack.slots],
        state.dirty,
        state.get_current_slot_index(),
        frame.editor.get("1.0", "end"),
        frame.pack_name_label.cget("text"),
    )


# --- The guard ---------------------------------------------------------------------------------------------------------


def test_the_editor_edit_marks_the_working_pack_unsaved(
    tab: PromptTabFrame, tk_root: tk.Tk, dialogs: Dialogs, load_calls: list[str]
) -> None:
    """Precondition for the guard: a real editor keystroke reaches the dirty flag the guard reads."""
    _open(tab, "alpha", load_calls)
    assert tab.workspace_state.dirty is False

    _type_in_editor(tab, tk_root, " edited")

    assert tab.workspace_state.dirty is True
    assert tab.workspace_state.get_slot(0).text == "alpha one edited"


def test_declining_the_load_button_keeps_the_unsaved_pack_untouched(
    tab: PromptTabFrame, tk_root: tk.Tk, dialogs: Dialogs, load_calls: list[str]
) -> None:
    _open(tab, "alpha", load_calls)
    _type_in_editor(tab, tk_root, " edited")
    before = _snapshot(tab)
    _select(tab, "beta")
    dialogs.answer = False

    _load_button(tab).invoke()

    assert len(dialogs.asked) == 1
    title, message = dialogs.asked[0]
    assert title == "Unsaved Changes"
    assert "discard" in message.lower() and "beta" in message
    assert load_calls == []  # nothing was read from disk
    assert _snapshot(tab) == before
    assert tab.workspace_state.dirty is True
    assert dialogs.errors == [] and dialogs.info == []
    assert tab.pack_listbox.curselection() == (list(tab.pack_listbox.get(0, tk.END)).index("beta"),)


def test_accepting_the_load_button_replaces_the_pack_exactly_once(
    tab: PromptTabFrame, tk_root: tk.Tk, dialogs: Dialogs, load_calls: list[str]
) -> None:
    _open(tab, "alpha", load_calls)
    _type_in_editor(tab, tk_root, " edited")
    _select(tab, "beta")
    dialogs.answer = True

    _load_button(tab).invoke()

    assert len(dialogs.asked) == 1
    assert len(load_calls) == 1 and load_calls[0].endswith("beta.json")
    assert [slot.text for slot in tab.workspace_state.current_pack.slots][:2] == ["beta one", "beta two"]
    assert tab.workspace_state.dirty is False
    assert tab.editor.get("1.0", "end").strip() == "beta one"
    assert tab.pack_name_label.cget("text") == "Editor - beta"


def _double_click(frame: PromptTabFrame, root: tk.Tk, name: str) -> None:
    """Select ``name`` and deliver two quick presses; Tk itself recognises them as <Double-Button-1>.

    Tk only synthesises the double-click for a mapped window, so map the tab invisibly (alpha 0) for the gesture.
    """
    _select(frame, name)
    try:
        root.attributes("-alpha", 0.0)
    except tk.TclError:
        pass
    frame.pack(fill="both", expand=True)
    root.deiconify()
    root.update()
    index = list(frame.pack_listbox.get(0, tk.END)).index(name)
    x, y, _w, h = frame.pack_listbox.bbox(index)
    y += h // 2  # click on the row itself: a real click re-selects whatever is under the pointer
    try:
        for _ in range(2):
            frame.pack_listbox.event_generate("<ButtonPress-1>", x=x + 4, y=y, time=1000)
            frame.pack_listbox.event_generate("<ButtonRelease-1>", x=x + 4, y=y, time=1001)
        root.update()
    finally:
        root.withdraw()


def test_declining_a_double_click_keeps_the_unsaved_pack_untouched(
    tab: PromptTabFrame, tk_root: tk.Tk, dialogs: Dialogs, load_calls: list[str]
) -> None:
    _open(tab, "alpha", load_calls)
    _type_in_editor(tab, tk_root, " edited")
    before = _snapshot(tab)
    dialogs.answer = False
    # The double-click binding itself (not a direct handler call) must reach the guard.
    _double_click(tab, tk_root, "beta")

    assert len(dialogs.asked) == 1, "double-click did not reach the guarded handler"
    assert load_calls == []
    assert tab.workspace_state.dirty is True
    assert _snapshot(tab)[:5] == before[:5]


def test_accepting_a_double_click_loads_exactly_once(
    tab: PromptTabFrame, tk_root: tk.Tk, dialogs: Dialogs, load_calls: list[str]
) -> None:
    _open(tab, "alpha", load_calls)
    _type_in_editor(tab, tk_root, " edited")
    dialogs.answer = True
    _double_click(tab, tk_root, "beta")

    assert len(dialogs.asked) == 1
    assert len(load_calls) == 1 and load_calls[0].endswith("beta.json")
    assert tab.workspace_state.get_slot(0).text == "beta one"
    assert tab.workspace_state.dirty is False


def test_a_clean_pack_loads_without_any_prompt(
    tab: PromptTabFrame, tk_root: tk.Tk, dialogs: Dialogs, load_calls: list[str]
) -> None:
    _open(tab, "alpha", load_calls)
    _select(tab, "beta")

    tab._on_load_selected_pack()

    assert dialogs.asked == []
    assert len(load_calls) == 1
    assert tab.workspace_state.get_slot(0).text == "beta one"


def test_the_initial_untouched_workspace_loads_without_a_prompt(
    tab: PromptTabFrame, dialogs: Dialogs, load_calls: list[str]
) -> None:
    _select(tab, "alpha")

    tab._on_load_selected_pack()

    assert dialogs.asked == []
    assert len(load_calls) == 1


# --- Same-pack reload --------------------------------------------------------------------------------------------------


def test_reloading_the_same_pack_is_guarded_and_decline_keeps_the_edit(
    tab: PromptTabFrame, tk_root: tk.Tk, dialogs: Dialogs, load_calls: list[str]
) -> None:
    _open(tab, "alpha", load_calls)
    _type_in_editor(tab, tk_root, " edited")
    before = _snapshot(tab)
    _select(tab, "alpha")
    dialogs.answer = False

    tab._on_load_selected_pack()

    assert len(dialogs.asked) == 1
    assert load_calls == []
    assert _snapshot(tab) == before
    assert tab.workspace_state.get_slot(0).text == "alpha one edited"


def test_reloading_the_same_pack_after_accepting_discards_the_edit_once(
    tab: PromptTabFrame, tk_root: tk.Tk, dialogs: Dialogs, load_calls: list[str]
) -> None:
    _open(tab, "alpha", load_calls)
    _type_in_editor(tab, tk_root, " edited")
    _select(tab, "alpha")
    dialogs.answer = True

    tab._on_load_selected_pack()

    assert len(dialogs.asked) == 1 and len(load_calls) == 1
    assert tab.workspace_state.get_slot(0).text == "alpha one"
    assert tab.workspace_state.dirty is False


# --- Refusals and failures never cost the draft ------------------------------------------------------------------------


def test_no_selection_refuses_without_prompting_or_replacing(
    tab: PromptTabFrame, tk_root: tk.Tk, dialogs: Dialogs, load_calls: list[str]
) -> None:
    _open(tab, "alpha", load_calls)
    _type_in_editor(tab, tk_root, " edited")
    before = _snapshot(tab)
    tab.pack_listbox.selection_clear(0, tk.END)

    tab._on_load_selected_pack()

    assert dialogs.asked == [] and load_calls == []
    assert [title for title, _ in dialogs.info] == ["Load Pack"]
    assert _snapshot(tab) == before


def test_an_unresolvable_selection_refuses_without_prompting_or_replacing(
    tab: PromptTabFrame, tk_root: tk.Tk, dialogs: Dialogs, load_calls: list[str]
) -> None:
    _open(tab, "alpha", load_calls)
    _type_in_editor(tab, tk_root, " edited")
    before = _snapshot(tab)
    _select(tab, "beta")
    tab._visible_pack_infos = []  # the visible list no longer matches the widget

    tab._on_load_selected_pack()

    assert dialogs.asked == [] and load_calls == []
    assert [title for title, _ in dialogs.errors] == ["Load Pack"]
    assert _snapshot(tab) == before


@pytest.mark.parametrize("contents", ["{not json", json.dumps({"schema_version": 1, "pack_data": "bad"})])
def test_a_malformed_pack_accepted_over_a_draft_fails_without_dropping_the_draft(
    tab: PromptTabFrame,
    tk_root: tk.Tk,
    dialogs: Dialogs,
    load_calls: list[str],
    packs_dir: Path,
    contents: str,
) -> None:
    _open(tab, "alpha", load_calls)
    _type_in_editor(tab, tk_root, " edited")
    before = _snapshot(tab)
    _select(tab, "beta")
    (packs_dir / "beta.json").write_text(contents, encoding="utf-8")  # listed, then corrupted on disk
    dialogs.answer = True

    tab._on_load_selected_pack()

    assert len(dialogs.asked) == 1
    assert len(load_calls) == 1  # the attempt happened, and failed before assignment
    assert [title for title, _ in dialogs.errors] == ["Load Pack"]
    assert _snapshot(tab) == before
    assert tab.workspace_state.dirty is True
    assert tab.workspace_state.get_slot(0).text == "alpha one edited"


def test_a_missing_pack_file_fails_without_dropping_the_draft(
    tab: PromptTabFrame,
    tk_root: tk.Tk,
    dialogs: Dialogs,
    load_calls: list[str],
    packs_dir: Path,
) -> None:
    _open(tab, "alpha", load_calls)
    _type_in_editor(tab, tk_root, " edited")
    before = _snapshot(tab)
    _select(tab, "beta")
    (packs_dir / "beta.json").unlink()  # listed, then removed from disk
    dialogs.answer = True

    tab._on_load_selected_pack()

    assert [title for title, _ in dialogs.errors] == ["Load Pack"]
    assert _snapshot(tab) == before
    assert tab.workspace_state.dirty is True


# --- Repeated activation cannot bypass the guard -----------------------------------------------------------------------


def test_activating_load_again_while_the_prompt_is_open_does_not_bypass_it(
    tab: PromptTabFrame, tk_root: tk.Tk, dialogs: Dialogs, load_calls: list[str]
) -> None:
    _open(tab, "alpha", load_calls)
    _type_in_editor(tab, tk_root, " edited")
    _select(tab, "beta")
    dialogs.answer = False
    dialogs.on_ask = tab._on_load_selected_pack  # a second activation arrives while the first prompt is open

    tab._on_load_selected_pack()

    assert len(dialogs.asked) == 1  # not re-prompted, not loaded
    assert load_calls == []
    assert tab.workspace_state.dirty is True
    assert tab.workspace_state.get_slot(0).text == "alpha one edited"


def test_the_guard_is_released_after_a_decline_so_a_later_load_is_asked_again(
    tab: PromptTabFrame, tk_root: tk.Tk, dialogs: Dialogs, load_calls: list[str]
) -> None:
    _open(tab, "alpha", load_calls)
    _type_in_editor(tab, tk_root, " edited")
    _select(tab, "beta")
    dialogs.answer = False
    tab._on_load_selected_pack()
    dialogs.answer = True

    tab._on_load_selected_pack()

    assert len(dialogs.asked) == 2
    assert len(load_calls) == 1
    assert tab.workspace_state.get_slot(0).text == "beta one"


# --- New is unchanged --------------------------------------------------------------------------------------------------


def test_new_pack_keeps_its_own_discard_prompt(
    tab: PromptTabFrame, tk_root: tk.Tk, dialogs: Dialogs, load_calls: list[str]
) -> None:
    _open(tab, "alpha", load_calls)
    _type_in_editor(tab, tk_root, " edited")
    dialogs.answer = False

    tab._on_new_pack()

    assert dialogs.asked == [("Unsaved Changes", "Discard unsaved changes and create a new pack?")]
    assert tab.workspace_state.get_slot(0).text == "alpha one edited"
