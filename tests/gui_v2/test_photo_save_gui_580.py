"""PR-GUI-UX-580: the Photo Optimize tab saves the active photo's baseline off Tk, in order, and never lies about it."""

from __future__ import annotations

import time
import tkinter as tk
from pathlib import Path
from types import SimpleNamespace

import pytest
from PIL import Image

from src.gui.views.photo_optimize_tab_frame_v2 import (
    BASELINE_SAVE_DEBOUNCE_MS,
    PhotoOptimizeTabFrameV2,
)
from src.photo_optimize.store import PhotoOptimizeStore
from tests.gui_v2.edit_work_helpers import ManualRegistry, use_manual_registry


def _store(tmp_path: Path, count: int = 2) -> tuple[PhotoOptimizeStore, list[str]]:
    store = PhotoOptimizeStore(tmp_path / "photo_optimize")
    ids = []
    for index in range(count):
        source = tmp_path / "source" / f"p{index}.png"
        source.parent.mkdir(parents=True, exist_ok=True)
        Image.new("RGB", (64, 48), (40 * index, 80, 120)).save(source)
        ids.append(store.import_photo(source).asset_id)
    return store, ids


def _pump(root, predicate, timeout: float = 5.0) -> None:
    deadline = time.monotonic() + timeout
    while not predicate() and time.monotonic() < deadline:
        root.update()
        time.sleep(0.01)
    assert predicate(), "condition was not met in time"


class Env:
    def __init__(self, tk_root, tmp_path, monkeypatch) -> None:
        self.registry: ManualRegistry = use_manual_registry(monkeypatch)
        self.store, imported = _store(tmp_path)
        self.errors: list[tuple[str, str]] = []
        for module in (
            "src.gui.views.photo_optimize_tab_frame_v2",
            "src.gui.views.photo_optimize_scope",
        ):
            monkeypatch.setattr(
                f"{module}.messagebox.showerror",
                lambda title, message, **_: self.errors.append((title, message)),
            )
            monkeypatch.setattr(f"{module}.messagebox.showwarning", lambda *a, **k: None)
        self.prepared_with: list[str] = []
        controller = SimpleNamespace(
            build_photo_optimize_defaults=lambda: {},
            prepare_photo_optimize_plan=self._prepare,
        )
        monkeypatch.setattr(
            "src.gui.views.photo_optimize_scope.review_dialog", lambda *a, **k: False
        )
        self.tab = PhotoOptimizeTabFrameV2(tk_root, app_controller=controller, store=self.store)
        self.root = tk_root
        self.drain()
        self.ids = list(
            self.tab._asset_index_by_row
        )  # the list's own order (asset ids are not time-ordered)
        assert sorted(self.ids) == sorted(imported) and self.tab._current_asset_id == self.ids[0]

    def _prepare(self, **arguments):
        # Called on the operation worker: record the *persisted* prompt the plan is about to be built from.
        self.prepared_with.extend(row["baseline"]["prompt"] for row in arguments["assets"])
        raise RuntimeError("stop after recording")

    def drain(self) -> None:
        self.registry.run_all()
        self.root.update()

    def type_prompt(self, text: str) -> None:
        self.tab._set_text(self.tab.baseline_prompt_text, text)
        self.tab._on_baseline_form_changed()

    def stored_prompt(self, asset_id: str) -> str:
        return self.store.get_asset(asset_id).baseline.prompt


@pytest.fixture
def env(tk_root, tmp_path, monkeypatch):
    environment = Env(tk_root, tmp_path, monkeypatch)
    yield environment
    try:
        environment.tab.destroy()
    except tk.TclError:
        pass  # a test that closed the tab itself


def test_typing_is_debounced_into_one_write_of_the_latest_text(env, monkeypatch):
    writes: list[str] = []
    real = env.store.update_asset_fields

    def spy(asset_id, **kwargs):
        writes.append(kwargs["baseline"].prompt)
        return real(asset_id, **kwargs)

    monkeypatch.setattr(env.store, "update_asset_fields", spy)
    for text in ("a", "ab", "abc", "abcd"):
        env.type_prompt(text)
    assert BASELINE_SAVE_DEBOUNCE_MS > 0
    assert (
        "photo-baseline-save" not in [name for name, _t, _a in env.registry.queued] and writes == []
    )
    # keystrokes only schedule the debounce; Tk does no file work and no write is submitted yet
    assert env.tab.baseline_save_status_var.get() == "Unsaved changes"
    env.tab._flush_baseline_timer()  # the quiet period elapsed
    env.drain()
    assert writes == ["abcd"] and env.stored_prompt(env.ids[0]) == "abcd"
    assert env.tab.baseline_save_status_var.get() == "Saved"


def test_leaving_a_photo_saves_its_edit_on_that_photo_only(env):
    first, second = env.ids
    before_second = env.stored_prompt(second)
    env.type_prompt("edited on the first photo")
    env.tab.assets_list.selection_clear(0, "end")
    env.tab.assets_list.selection_set(1)
    env.tab._show_asset(second)
    env.drain()
    assert env.stored_prompt(first) == "edited on the first photo"
    assert env.stored_prompt(second) == before_second
    assert env.tab._current_asset_id == second
    assert env.tab._get_text(env.tab.baseline_prompt_text) == before_second


def test_a_plan_is_prepared_only_after_the_visible_edit_is_persisted(env):
    env.type_prompt("must be in the plan")
    env.tab._optimize(batch_all=False)
    assert env.prepared_with == []  # the save has not run, so the plan has not been prepared
    assert env.errors == []
    env.registry.run_all()
    _pump(env.root, lambda: bool(env.prepared_with))
    assert env.prepared_with == ["must be in the plan"]


def test_a_failed_save_blocks_the_dependent_action_and_says_why(env, monkeypatch):
    monkeypatch.setattr(
        env.store,
        "update_asset_fields",
        lambda *a, **k: (_ for _ in ()).throw(OSError("disk full")),
    )
    env.type_prompt("never reaches disk")
    ran = []
    env.tab._with_saved_baseline(lambda: ran.append(True), action="Promoting a result")
    env.drain()
    assert ran == []
    assert (
        env.errors
        and "disk full" in env.errors[-1][1]
        and "Promoting a result" in env.errors[-1][1]
    )
    assert env.tab.baseline_save_status_var.get().startswith("Not saved")
    assert env.stored_prompt(env.ids[0]) != "never reaches disk"


def test_closing_with_an_unsaved_edit_still_writes_it(env):
    env.type_prompt("typed just before closing")
    env.tab.destroy()
    env.registry.run_all()  # the write finishes on its worker after the view is gone
    assert env.stored_prompt(env.ids[0]) == "typed just before closing"


def test_late_worker_results_after_close_touch_nothing(env):
    env.tab._refresh_assets()
    env.tab.destroy()
    env.registry.run_all()  # must not raise on the destroyed widget
