"""PR-GUI-UX-560 repair: application-owned PromptPack saves invalidate exactly the Preview that used that pack.

Covers every in-app writer that can change a pack the job draft compiles: the Prompt tab save (``PromptPackModel``) and
the saved-settings writes behind "apply settings to packs" (``ConfigManager.update_pack_config``). Identity is the
compiler's own resolution (``pack_json_path``), so a same-named file elsewhere is a different pack.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from src.controller.app_controller import AppController
from src.controller.app_controller_services.pack_settings_apply_service import (
    apply_settings_to_packs,
    bind_preview_invalidation,
)
from src.gui.app_state_v2 import AppStateV2, PackJobEntry
from src.gui.models.prompt_pack_model import PromptPackModel
from src.gui.prompt_workspace_state import PromptWorkspaceState
from src.gui.views.prompt_tab_frame_v2 import PromptTabFrame
from src.promptpacks import storage
from src.utils.config import ConfigManager
from src.utils.prompt_pack_utils import pack_json_path, same_pack_file
from tests.controller.test_matrix_preview_admission_560 import Harness, _matrix
from tests.gui_v2.tk_test_utils import get_shared_tk_root
from tests.helpers.factories import make_run_config
from tests.helpers.job_helpers import make_test_njr
from tests.helpers.job_service_di_test_helpers import make_stubbed_job_service
from tests.pipeline.test_prompt_pack_job_builder import _write_native_pack


def _entry(pack_id: str) -> PackJobEntry:
    return PackJobEntry(
        pack_id=pack_id,
        pack_name=Path(pack_id).stem,
        prompt_text="A [[character]]",
        config_snapshot={},
        stage_flags={"txt2img": True},
    )


def _accepted(state: AppStateV2) -> list[Any]:
    records = [make_test_njr(job_id="accepted-1", prompt_source="manual", prompt_pack_id="")]
    state.set_preview_jobs(records)
    return records


def _packs(tmp_path: Path) -> tuple[Path, Path, Path]:
    primary, other = tmp_path / "packs", tmp_path / "elsewhere"
    primary.mkdir()
    other.mkdir()
    return primary, other, tmp_path / "presets"


# ---- identity ---------------------------------------------------------------------------------------------


def test_pack_identity_is_the_compilers_resolution(tmp_path: Path) -> None:
    packs, other, _ = _packs(tmp_path)

    assert pack_json_path("demo", packs) == packs / "demo.json"
    assert pack_json_path("demo.json", packs) == packs / "demo.json"
    assert (
        pack_json_path("sub/demo.txt", packs) == packs / "demo.json"
    )  # a relative id is a stem inside packs_dir
    assert pack_json_path(other / "demo.json", packs) == other / "demo.json"
    assert pack_json_path(str(other / "demo"), packs) == other / "demo.json"
    assert same_pack_file(packs / "demo.json", packs / "." / "demo.json")
    assert not same_pack_file(packs / "demo.json", other / "demo.json")


def test_the_compiler_resolves_pack_files_with_the_same_rule(tmp_path: Path) -> None:
    harness = Harness(tmp_path, _matrix(limit=2))

    resolved = harness.builder._resolve_pack_json_path(harness.pack.name)  # noqa: SLF001

    assert resolved == pack_json_path(harness.pack.name, harness.config_manager.packs_dir)
    assert harness.builder._resolve_pack_json_path("not-there.json") is None  # noqa: SLF001


@pytest.mark.parametrize(
    ("draft_id", "saved", "expected"),
    [
        ("demo", "packs/demo.json", True),
        ("demo.json", "packs/demo.json", True),
        ("demo", "elsewhere/demo.json", False),  # same file name, different directory
        (
            "elsewhere/demo.json",
            "elsewhere/demo.json",
            False,
        ),  # a relative id is a stem inside packs_dir, as compiled
        ("ABS:elsewhere/demo.json", "elsewhere/demo.json", True),
        ("ABS:elsewhere/demo.json", "packs/demo.json", False),
        ("ABS:packs/demo.json", "packs/demo.json", True),
        ("demo", "packs/other.json", False),
    ],
)
def test_only_the_very_same_file_invalidates(
    tmp_path: Path, draft_id: str, saved: str, expected: bool
) -> None:
    packs, other, _ = _packs(tmp_path)
    if draft_id.startswith("ABS:"):
        draft_id = str(tmp_path / draft_id[4:])
    state = AppStateV2()
    state.add_packs_to_job_draft([_entry(draft_id)])
    records = _accepted(state)
    revision = state.preview_revision

    result = state.pack_file_saved(tmp_path / saved, packs_dir=packs)

    assert result is expected
    if expected:
        assert state.preview_jobs == [] and state.preview_revision == revision + 1
    else:
        assert state.preview_jobs == records and state.preview_revision == revision


def test_a_save_with_nothing_in_the_draft_changes_nothing(tmp_path: Path) -> None:
    packs, _, _ = _packs(tmp_path)
    state = AppStateV2()
    records = _accepted(state)

    assert state.pack_file_saved(packs / "demo.json", packs_dir=packs) is False
    assert state.preview_jobs == records


def test_invalidation_announces_the_draft_so_the_pipeline_tab_rebuilds(tmp_path: Path) -> None:
    packs, _, _ = _packs(tmp_path)
    state = AppStateV2()
    state.add_packs_to_job_draft([_entry("demo")])
    _accepted(state)
    announced: list[str] = []
    state.subscribe("job_draft", lambda: announced.append("job_draft"))

    state.pack_file_saved(packs / "demo.json", packs_dir=packs)

    assert announced == ["job_draft"]


# ---- writer 1: the Prompt tab save ------------------------------------------------------------------------


@pytest.fixture
def tab_env(tmp_path: Path):
    root = get_shared_tk_root()
    if root is None:
        pytest.skip("Tk unavailable")
    packs, other, _ = _packs(tmp_path)
    state = AppStateV2()
    tab = PromptTabFrame(root, app_state=state, packs_dir=packs)
    tab.workspace_state.new_pack("demo")
    tab.workspace_state.current_pack.get_slot(0).text = "A [[character]]"
    yield tab, state, packs, other
    tab.destroy()


def test_the_prompt_tab_save_invalidates_the_preview_of_that_pack(tab_env) -> None:
    tab, state, packs, _ = tab_env
    state.add_packs_to_job_draft([_entry("demo")])
    _accepted(state)

    tab.workspace_state.save_current_pack_as(packs / "demo.json")

    assert state.preview_jobs == []


def test_the_prompt_tab_save_as_to_another_directory_leaves_the_preview_alone(tab_env) -> None:
    tab, state, _, other = tab_env
    state.add_packs_to_job_draft([_entry("demo")])
    records = _accepted(state)

    tab.workspace_state.save_current_pack_as(
        other / "demo.json"
    )  # same file name, a different pack

    assert state.preview_jobs == records


def test_saving_an_unrelated_pack_from_the_prompt_tab_leaves_the_preview_alone(tab_env) -> None:
    tab, state, packs, _ = tab_env
    state.add_packs_to_job_draft([_entry("demo")])
    records = _accepted(state)

    tab.workspace_state.save_current_pack_as(packs / "unrelated.json")

    assert state.preview_jobs == records


def test_a_failed_prompt_tab_save_does_not_invalidate(
    tab_env, monkeypatch: pytest.MonkeyPatch
) -> None:
    tab, state, packs, _ = tab_env
    state.add_packs_to_job_draft([_entry("demo")])
    records = _accepted(state)
    revision = state.preview_revision

    def refuse(*_args: Any, **_kwargs: Any) -> None:
        raise OSError("disk full")

    monkeypatch.setattr("src.gui.models.prompt_pack_model.save_prompt_pack_document", refuse)

    with pytest.raises(OSError, match="disk full"):
        tab.workspace_state.save_current_pack_as(packs / "demo.json")

    assert state.preview_jobs == records and state.preview_revision == revision


def test_a_failing_listener_never_fails_a_completed_save(tmp_path: Path) -> None:
    workspace = PromptWorkspaceState()
    pack = workspace.new_pack("demo")
    pack.get_slot(0).text = "x"

    def boom(_path: Path) -> None:
        raise RuntimeError("observer bug")

    workspace.pack_saved_listener = boom
    saved = workspace.save_current_pack_as(tmp_path / "demo.json")

    assert saved.exists() and PromptPackModel.load_from_file(saved).slots[0].text == "x"


# ---- writer 2: saved-settings writes (apply settings to packs) --------------------------------------------


@pytest.fixture
def settings_env(tmp_path: Path):
    packs, other, presets = _packs(tmp_path)
    manager = ConfigManager(presets_dir=presets, packs_dir=packs)
    _write_native_pack(packs / "demo.json", text="A [[character]]")
    _write_native_pack(packs / "unrelated.json", text="B")
    state = AppStateV2()
    bind_preview_invalidation(manager, lambda: state)
    return manager, state, packs, other


def test_saving_a_packs_settings_invalidates_the_preview_that_used_it(settings_env) -> None:
    manager, state, _packs_dir, _ = settings_env
    state.add_packs_to_job_draft([_entry("demo")])
    _accepted(state)

    manager.update_pack_config("demo", {"txt2img": {"steps": 33}})

    assert state.preview_jobs == []


def test_apply_to_packs_invalidates_each_used_pack_and_reports_failures_without_invalidating(
    settings_env,
) -> None:
    manager, state, packs, _ = settings_env
    state.add_packs_to_job_draft([_entry("demo")])
    records = _accepted(state)

    report = apply_settings_to_packs(
        manager, ["unrelated", "missing"], {"txt2img": {"steps": 9}}, source="test"
    )
    assert report.succeeded == ("unrelated",) and [item.pack_id for item in report.failed] == [
        "missing"
    ]
    assert (
        state.preview_jobs == records
    )  # nothing the draft uses was written; the failure wrote nothing

    report = apply_settings_to_packs(manager, ["demo"], {"txt2img": {"steps": 9}}, source="test")
    assert report.all_ok
    assert state.preview_jobs == []
    assert (
        json.loads((packs / "demo.json").read_text(encoding="utf-8"))["preset_data"]["txt2img"][
            "steps"
        ]
        == 9
    )


def test_a_failed_settings_write_does_not_invalidate(
    settings_env, monkeypatch: pytest.MonkeyPatch
) -> None:
    manager, state, _, _ = settings_env
    state.add_packs_to_job_draft([_entry("demo")])
    records = _accepted(state)
    revision = state.preview_revision

    def refuse(*_args: Any, **_kwargs: Any) -> Path:
        raise OSError("read-only")

    monkeypatch.setattr(manager, "_update_pack_preset_data", refuse)

    assert manager.save_pack_config("demo", {"txt2img": {"steps": 5}}) is False
    assert state.preview_jobs == records and state.preview_revision == revision


def test_a_same_named_pack_in_another_directory_is_not_the_drafts_pack(settings_env) -> None:
    manager, state, packs, other = settings_env
    state.add_packs_to_job_draft(
        [_entry(str(other / "demo.json"))]
    )  # the draft uses elsewhere/demo.json
    records = _accepted(state)

    manager.update_pack_config("demo", {"txt2img": {"steps": 7}})  # writes packs/demo.json

    assert state.preview_jobs == records


def test_a_rebound_or_missing_app_state_is_tolerated(tmp_path: Path) -> None:
    packs, _, presets = _packs(tmp_path)
    manager = ConfigManager(presets_dir=presets, packs_dir=packs)
    _write_native_pack(packs / "demo.json", text="x")
    holder: dict[str, AppStateV2 | None] = {"state": None}
    bind_preview_invalidation(manager, lambda: holder["state"])

    manager.update_pack_config("demo", {"txt2img": {"steps": 2}})  # no state yet: harmless

    holder["state"] = AppStateV2()
    holder["state"].add_packs_to_job_draft([_entry("demo")])
    _accepted(holder["state"])
    manager.update_pack_config("demo", {"txt2img": {"steps": 3}})
    assert holder["state"].preview_jobs == []


class _NoopRunner:
    def run(self, *_a: Any, **_k: Any) -> None:
        return None


class _Window:
    """Just enough window for AppController construction (as the existing config tests do)."""

    def __getattr__(self, name: str) -> Any:
        raise AttributeError(name)


def test_the_app_controller_wires_its_config_manager_to_the_live_app_state(tmp_path: Path) -> None:
    packs, _, presets = _packs(tmp_path)
    manager = ConfigManager(presets_dir=presets, packs_dir=packs)
    _write_native_pack(packs / "demo.json", text="x")
    controller = AppController(
        _Window(),
        threaded=False,
        packs_dir=packs,
        config_manager=manager,
        pipeline_runner=_NoopRunner(),
        job_service=make_stubbed_job_service(),
    )
    controller.app_state.run_config = make_run_config()
    controller.app_state.add_packs_to_job_draft([_entry("demo")])
    records = _accepted(controller.app_state)

    assert manager.save_pack_config("unrelated", {}) is False  # not a pack at all: a failed write
    assert controller.app_state.preview_jobs == records

    manager.update_pack_config("demo", {"txt2img": {"steps": 4}})
    assert controller.app_state.preview_jobs == []


def test_queued_records_cannot_be_changed_by_a_later_pack_save(tmp_path: Path) -> None:
    harness = Harness(tmp_path, _matrix(mode="random", limit=3, sample_seed=5))
    harness.accept_preview()
    harness.controller.submit_preview_jobs_to_queue()
    before = [record.to_dict() for record in harness.queued()]
    manager = ConfigManager(
        presets_dir=tmp_path / "presets", packs_dir=harness.config_manager.packs_dir
    )
    bind_preview_invalidation(manager, lambda: harness.app_state)

    manager.update_pack_config(harness.pack.name, {"txt2img": {"steps": 99}})
    storage.save_prompt_pack_document(harness.pack, storage.load_prompt_pack_document(harness.pack))

    assert [record.to_dict() for record in harness.queued()] == before
