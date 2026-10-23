"""Offline AI Assist inside an operator journey: its data is disposable, only the committed manifests are readable.

The journey's ``AccessSpy`` treats ``config/`` as operator-owned. Offline AI Assist's readiness record reads two immutable,
checked-in manifests, so exactly those two files are readable (never writable); every other read, write and listing under a
protected directory stays a violation.
"""

from __future__ import annotations

import builtins
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from tools.operator_journey.workspace import AccessSpy, OperatorWorkspace  # noqa: E402

MANIFESTS = ("managed_ai_runtime.json", "ai_model_registry.json")


def _fake_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    (repo / "config").mkdir(parents=True)
    for name in (
        *MANIFESTS,
        "managed_comfy_runtime.json",
        "forge_klein_assets.json",
        "secret_local.json",
    ):
        (repo / "config" / name).write_text("{}", encoding="utf-8")
    (repo / "presets").mkdir()
    (repo / "presets" / "settings.json").write_text("{}", encoding="utf-8")
    (repo / "state").mkdir()
    return repo


@pytest.mark.parametrize("name", MANIFESTS)
def test_the_two_committed_manifests_may_be_read(tmp_path: Path, name: str) -> None:
    repo = _fake_repo(tmp_path)
    with AccessSpy(repo_root=repo) as spy:
        (repo / "config" / name).read_text(encoding="utf-8")
        with open(repo / "config" / name, encoding="utf-8") as handle:
            handle.read()
    assert spy.read_protected == [] and spy.written == []


@pytest.mark.parametrize(
    "name", ["managed_comfy_runtime.json", "forge_klein_assets.json", "secret_local.json"]
)
def test_every_other_config_file_stays_guarded_for_reading(tmp_path: Path, name: str) -> None:
    repo = _fake_repo(tmp_path)
    with AccessSpy(repo_root=repo) as spy:
        (repo / "config" / name).read_text(encoding="utf-8")
    assert [Path(p).name for p in spy.read_protected] == [name]


def test_lookalike_paths_are_not_exempt(tmp_path: Path) -> None:
    repo = _fake_repo(tmp_path)
    (repo / "config" / "ai_model_registry.json.bak").write_text("{}", encoding="utf-8")
    (repo / "config" / "nested").mkdir()
    (repo / "config" / "nested" / "ai_model_registry.json").write_text("{}", encoding="utf-8")
    (repo / "presets" / "ai_model_registry.json").write_text("{}", encoding="utf-8")
    with AccessSpy(repo_root=repo) as spy:
        (repo / "config" / "ai_model_registry.json.bak").read_text(encoding="utf-8")
        (repo / "config" / "nested" / "ai_model_registry.json").read_text(encoding="utf-8")
        (repo / "presets" / "ai_model_registry.json").read_text(encoding="utf-8")
    assert len(spy.read_protected) == 3


@pytest.mark.parametrize("name", MANIFESTS)
@pytest.mark.parametrize("mode", ["w", "a", "r+", "x"])
def test_the_manifests_are_never_writable(tmp_path: Path, name: str, mode: str) -> None:
    repo = _fake_repo(tmp_path)
    target = repo / "config" / name
    with AccessSpy(repo_root=repo) as spy:
        try:
            if mode == "x":
                target.unlink()
            with open(target, mode, encoding="utf-8"):
                pass
        except OSError:
            pass
    assert [Path(p).name for p in spy.written] == [name]


def test_protected_directories_are_still_not_enumerable_and_presets_not_readable(
    tmp_path: Path,
) -> None:
    import os

    repo = _fake_repo(tmp_path)
    with AccessSpy(repo_root=repo) as spy:
        list(os.scandir(repo / "config"))
        os.listdir(repo / "state")
        (repo / "presets" / "settings.json").read_text(encoding="utf-8")
    assert len(spy.enumerated) == 2
    assert [Path(p).name for p in spy.read_protected] == ["settings.json"]


def test_the_spy_restores_open_after_it_exits(tmp_path: Path) -> None:
    real_open = builtins.open
    with AccessSpy(repo_root=_fake_repo(tmp_path)):
        assert builtins.open is not real_open
    assert builtins.open is real_open


def test_a_journey_workspace_gives_ai_assist_a_disposable_directory_and_restores_the_environment(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import os

    workspace = OperatorWorkspace(root=tmp_path / "ws", webui_base_url="http://127.0.0.1:1")
    monkeypatch.setenv("STABLENEW_AI_DIR", "D:/operators-real-ai-directory")
    with workspace.activate():
        assert Path(os.environ["STABLENEW_AI_DIR"]) == workspace.ai_assist_dir
        assert workspace.ai_assist_dir.is_dir() and workspace.ai_assist_dir.is_relative_to(tmp_path)
    assert os.environ["STABLENEW_AI_DIR"] == "D:/operators-real-ai-directory"

    monkeypatch.delenv("STABLENEW_AI_DIR")
    with workspace.activate():
        assert os.environ["STABLENEW_AI_DIR"] == str(workspace.ai_assist_dir)
    assert "STABLENEW_AI_DIR" not in os.environ


def test_readiness_inside_a_journey_workspace_reads_only_the_committed_manifests(
    tmp_path: Path,
) -> None:
    """The exact path that failed on hosted CI: Operator Readiness collected under the real repository root."""

    from src.services.operator_readiness_service import (
        OperatorReadinessService,
        OperatorReadinessState,
    )

    workspace = OperatorWorkspace(root=tmp_path / "ws", webui_base_url="http://127.0.0.1:1")
    with workspace.activate(), AccessSpy(repo_root=ROOT, allowed=(workspace.root,)) as spy:
        record = (
            OperatorReadinessService(
                python_version_provider=lambda: (3, 14, 0),
                free_threaded_provider=lambda: False,
                jit_enabled_provider=lambda: False,
                comfy_command_provider=lambda: (),
            )
            .collect()
            .record_for("ai_assist")
        )
    assert record is not None and record.state is OperatorReadinessState.OPTIONAL
    assert [p for p in spy.read_protected if Path(p).name in MANIFESTS] == []
    assert not [p for p in spy.written if "ai_" in Path(p).name]
    assert not list(workspace.ai_assist_dir.iterdir()), (
        "reading the status must not create anything"
    )
