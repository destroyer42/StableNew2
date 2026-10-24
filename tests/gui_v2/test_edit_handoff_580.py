"""PR-GUI-UX-580: Quick Edit (Review) <-> Managed Photo Set hand-offs and PR-HISTORY-610A compatibility.

Real Tk tabs, real ``PhotoOptimizeStore`` and real History hand-offs; nothing here may queue a job or start a runtime.
"""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from src.gui.controllers.video_workspace_handoff import (
    route_images_to_photo_optimize,
    route_images_to_review,
)
from src.gui.views.photo_optimize_tab_frame_v2 import PhotoOptimizeTabFrameV2
from src.photo_optimize.managed_import import IMPORT_COPY, OPEN_EXISTING
from src.photo_optimize.store import PhotoOptimizeStore
from tests.gui_v2 import test_history_iterate_service_610a as service_tests
from tests.gui_v2.test_history_iterate_service_610a import JOB_ID, Env, _png

env = service_tests.env  # the 610A Review + History fixture, reused as-is

SECRET = "super private prompt words"


class _Notebook:
    def __init__(self) -> None:
        self.selected: list[object] = []

    def select(self, tab) -> None:
        self.selected.append(tab)


@pytest.fixture(autouse=True)
def quiet_dialogs(monkeypatch):
    shown: list[tuple[str, str]] = []
    for module in ("src.gui.views.photo_optimize_handoff", "src.gui.views.review_tab_frame_v2"):
        for name in ("showinfo", "showwarning", "showerror"):
            monkeypatch.setattr(
                f"{module}.messagebox.{name}",
                lambda title, message, **_: shown.append((title, message)),
            )
    return shown


class Workspace:
    """The 610A environment plus a real Photo Optimize tab wired into the same fake main window."""

    def __init__(self, env: Env, tk_root, tmp_path: Path) -> None:
        self.env = env
        self.store = PhotoOptimizeStore(tmp_path / "managed")
        self.notebook = _Notebook()
        self.photo = PhotoOptimizeTabFrameV2(tk_root, app_controller=env.app, store=self.store)
        env.app.main_window.photo_optimize_tab = self.photo
        env.app.main_window.center_notebook = self.notebook
        self.confirmations: list[object] = []
        self.answer: str | None = OPEN_EXISTING

        def confirm(plan):
            self.confirmations.append(
                SimpleNamespace(
                    assets_at_prompt=len(self.store.list_assets(include_archived=True)),
                    jobs_at_prompt=len(env.repository.list_jobs()),
                    plan=plan,
                )
            )
            return self.answer

        self.photo._confirm_import_hook = confirm

    @property
    def window(self):
        return self.env.app.main_window

    def asset_count(self) -> int:
        return len(self.store.list_assets(include_archived=True))


@pytest.fixture
def workspace(env, tk_root, tmp_path):
    space = Workspace(env, tk_root, tmp_path)
    yield space
    space.photo.destroy()


def _other(tmp_path: Path, name: str = "other.png", job_id: str | None = "other-job") -> Path:
    shade = (
        sum(name.encode()) % 200
    )  # distinct bytes per name: identity is the content, not the file name
    return Path(_png(tmp_path / name, job_id=job_id, color=(shade, 30, 60)))


def _history_handoff_loaded(env: Env):
    assert env.iterate.edit_in_review(JOB_ID, lambda *_: True).done
    notebook = env.app.main_window.center_notebook
    if isinstance(notebook, _Notebook):
        notebook.selected.clear()  # only navigation caused by the step under test is of interest
    return env.tab._active_handoff


# --- 610A amendment: identity, replacement and cancel semantics --------------------------------------


def test_history_identity_still_refuses_a_source_changed_after_the_handoff(env, tmp_path):
    _history_handoff_loaded(env)
    _png(tmp_path / "recorded.png", color=(200, 0, 0))
    preview = env.prepare()
    assert preview.blocked and "changed since" in preview.blocked[0].error


def test_manual_replacement_drops_the_history_claim_for_every_incoming_route(env, tmp_path):
    other = _other(tmp_path)
    for route in ("select_images", "queue_history_route"):
        _history_handoff_loaded(env)
        assert env.tab._active_handoff is not None
        env.tab._confirm_replace_hook = lambda *_: True
        if route == "select_images":
            env.tab._set_selected_images([other])
        else:
            assert route_images_to_review(main_window=env.app.main_window, image_paths=[other]) == [
                str(other)
            ]
        assert env.tab._active_handoff is None  # the claim no longer attaches to anything
        assert [str(p) for p in env.tab.selected_images] == [str(other)]


def test_declined_replacement_preserves_identity_selection_and_navigation(env, workspace, tmp_path):
    handoff = _history_handoff_loaded(env)
    before = list(env.tab.selected_images)
    asked = []
    env.tab._confirm_replace_hook = lambda title, message: asked.append(title) or False

    routed = route_images_to_review(main_window=env.app.main_window, image_paths=[_other(tmp_path)])

    assert routed == [] and asked == ["Replace Review selection?"]
    assert env.tab._active_handoff is handoff
    assert env.tab.selected_images == before
    assert workspace.notebook.selected == []  # a declined hand-off navigates nowhere
    assert env.prepare().jobs  # the claim still verifies and still compiles
    assert env.repository.list_jobs() == []


def test_nothing_is_managed_or_queued_before_the_operator_confirms(env, workspace, tmp_path):
    _history_handoff_loaded(env)
    env.tab.images_list.selection_set(0)
    workspace.answer = None  # Cancel

    env.tab._on_manage_selected_photos()

    assert len(workspace.confirmations) == 1
    seen = workspace.confirmations[0]
    assert (
        seen.assets_at_prompt == 0 and seen.jobs_at_prompt == 0
    )  # nothing existed while the question was open
    assert workspace.asset_count() == 0 and env.repository.list_jobs() == []
    assert workspace.notebook.selected == [
        workspace.photo
    ]  # the operator did go to the Managed Photo Set


def test_a_history_origin_image_is_imported_with_no_parent_claim_and_review_keeps_its_own(
    env, workspace
):
    handoff = _history_handoff_loaded(env)
    env.tab.images_list.selection_set(0)

    env.tab._on_manage_selected_photos()

    assert workspace.asset_count() == 1
    asset = workspace.store.list_assets()[0]
    stored = json.dumps(
        json.loads(workspace.store.sidecar_path(asset.asset_id).read_text(encoding="utf-8"))
    ).lower()
    for forbidden in (
        "history_iterate",
        JOB_ID,
        "parent_job",
        "parent_artifact",
        "source_artifact_id",
    ):
        assert forbidden.lower() not in stored
    # The import is a distinct operation: Review still holds its handoff and the claim still verifies.
    assert env.tab._active_handoff is handoff
    assert env.prepare().jobs[0].source.parent_job_id == JOB_ID
    assert env.repository.list_jobs() == []


def test_returning_from_the_managed_set_keeps_review_edits(env, workspace, tmp_path):
    _history_handoff_loaded(env)
    env.tab._set_text(env.tab.prompt_text, "my unsent edit")
    env.tab._on_prompt_edited()
    env.tab.images_list.selection_set(0)
    workspace.answer = None

    env.tab._on_manage_selected_photos()
    workspace.window.center_notebook.select(env.tab)

    assert env.tab._get_text(env.tab.prompt_text) == "my unsent edit"
    assert env.tab._active_handoff is not None and env.tab.has_unsent_edits()


def test_matrix_sourced_history_job_still_offers_edit_image_after_this_change(
    tk_root, tmp_path, monkeypatch
):
    from tests.gui_v2.test_history_iterate_model_610a import _entry, _result
    from tests.pipeline.test_history_variation_compiler_610a import _source

    environment = Env(tk_root, tmp_path, monkeypatch)
    try:
        environment.entry = _entry(
            _source(job_id=JOB_ID, matrix_slot_values={"hair": "red"}),
            result=_result(environment.image),
        )
        assessment = environment.iterate.assess(JOB_ID)
        assert assessment.review.supported and not assessment.pipeline.supported
        assert environment.iterate.edit_in_review(JOB_ID).done
        assert environment.tab._active_handoff.source == "history_iterate"
    finally:
        environment.tab.destroy()


# --- Review -> Managed Photo Set ---------------------------------------------------------------------


def test_review_offers_exactly_the_highlighted_images_in_list_order(env, workspace, tmp_path):
    files = [_other(tmp_path, f"p{i}.png", job_id=None) for i in range(3)]
    env.tab._set_selected_images(files)
    env.tab.images_list.selection_clear(0, "end")
    for index in (2, 0):
        env.tab.images_list.selection_set(index)

    env.tab._on_manage_selected_photos()

    plan = workspace.confirmations[0].plan
    assert [Path(row.path) for row in plan.rows] == [files[0], files[2]]
    assert workspace.asset_count() == 2
    assert [str(p) for p in env.tab.selected_images] == [
        str(p) for p in files
    ]  # Review's selection is untouched


def test_nothing_highlighted_offers_nothing(env, workspace, quiet_dialogs, tmp_path):
    env.tab._set_selected_images([_other(tmp_path)])
    env.tab.images_list.selection_clear(0, "end")
    env.tab._on_manage_selected_photos()
    assert (
        workspace.confirmations == []
        and quiet_dialogs
        and "Select one or more" in quiet_dialogs[-1][1]
    )
    assert workspace.notebook.selected == []


def test_duplicate_content_opens_the_existing_asset_or_copies_when_the_operator_says_so(
    env, workspace, tmp_path
):
    source = _other(tmp_path, "dup.png", job_id=None)
    existing = workspace.store.import_photo(source)
    env.tab._set_selected_images([source])
    env.tab.images_list.selection_set(0)

    workspace.answer = OPEN_EXISTING
    env.tab._on_manage_selected_photos()
    assert workspace.asset_count() == 1
    assert (
        workspace.photo._current_asset_id == existing.asset_id
    )  # the existing managed photo was opened

    workspace.answer = IMPORT_COPY
    env.tab._on_manage_selected_photos()
    assert workspace.asset_count() == 2


def test_partial_failure_reports_per_file_outcomes_and_imports_the_rest(
    env, workspace, quiet_dialogs, tmp_path
):
    good = _other(tmp_path, "good.png", job_id=None)
    gone = _other(tmp_path, "gone.png", job_id=None)
    env.tab._set_selected_images([good, gone])
    gone.unlink()
    env.tab.images_list.selection_set(0, "end")

    env.tab._on_manage_selected_photos()

    assert workspace.asset_count() == 1
    assert "FAILED gone.png" in workspace.photo.submission_summary_var.get()
    assert SECRET not in workspace.photo.submission_summary_var.get()


def test_the_handoff_routes_validate_their_targets(tmp_path):
    with pytest.raises(ValueError):
        route_images_to_photo_optimize(main_window=SimpleNamespace(), image_paths=[])
    with pytest.raises(RuntimeError, match="Photo Optimize tab is not available"):
        route_images_to_photo_optimize(main_window=SimpleNamespace(), image_paths=["a.png"])
    with pytest.raises(RuntimeError, match="does not support"):
        route_images_to_photo_optimize(
            main_window=SimpleNamespace(photo_optimize_tab=object()), image_paths=["a.png"]
        )


def test_the_managed_set_never_receives_review_state_only_paths(workspace, tmp_path):
    received = []
    window = SimpleNamespace(
        photo_optimize_tab=SimpleNamespace(
            receive_review_handoff=lambda paths, status_message=None: received.append(
                (paths, status_message)
            )
        ),
        center_notebook=_Notebook(),
    )
    route_images_to_photo_optimize(
        main_window=window, image_paths=[tmp_path / "x.png"], status_message="hello"
    )
    assert received == [([str(tmp_path / "x.png")], "hello")]


# --- Managed Photo Set -> Quick Edit -----------------------------------------------------------------


def test_open_selected_in_quick_edit_hands_the_working_image_to_review(env, workspace, tmp_path):
    source = _other(tmp_path, "managed.png", job_id=None)
    asset = workspace.store.import_photo(source)
    workspace.photo._refresh_assets(select_asset_id=asset.asset_id)
    workspace.photo.assets_list.selection_set(0)

    workspace.photo._open_selected_in_quick_edit()

    assert [str(p) for p in env.tab.selected_images] == [str(asset.current_input_path)]
    assert workspace.notebook.selected == [env.tab]
    assert env.tab._active_handoff is None  # a managed photo carries no History lineage into Review


def test_open_selected_in_quick_edit_respects_a_declined_replacement(env, workspace, tmp_path):
    handoff = _history_handoff_loaded(env)
    asset = workspace.store.import_photo(_other(tmp_path, "managed.png", job_id=None))
    workspace.photo._refresh_assets(select_asset_id=asset.asset_id)
    workspace.photo.assets_list.selection_set(0)
    env.tab._confirm_replace_hook = lambda *_: False

    workspace.photo._open_selected_in_quick_edit()

    assert env.tab._active_handoff is handoff
    assert workspace.notebook.selected == []
    assert "kept its current work" in workspace.photo.submission_summary_var.get()
