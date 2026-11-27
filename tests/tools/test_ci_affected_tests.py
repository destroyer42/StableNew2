"""CI-LEAN: the affected-test selection behind ``run_pr_gate.py --parity``."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from tools.ci import affected_tests

FILES = {
    "src/__init__.py": "",
    "src/catalog.py": "from src.catalog_animate import SPEC\n",
    "src/catalog_animate.py": "SPEC = 1\n",
    "src/registry.py": "from src.catalog import SPEC\n",
    "src/other.py": "VALUE = 2\n",
    "tools/review_deploy_tool.py": "VALUE = 3\n",
    "services/gateway/review_gateway/__init__.py": "",
    "services/gateway/review_gateway/store.py": "VALUE = 4\n",
    "docs/schemas/sync-contract.v1.json": "{}\n",
    "tests/helpers/fakes.py": "from src.other import VALUE\n",
    "tests/video/test_animate.py": "from src.catalog_animate import SPEC\n",
    "tests/video/test_catalog.py": "from src.catalog import SPEC\n",
    "tests/video/test_registry.py": "from src import registry\n",
    "tests/video/test_uses_a_helper.py": "from tests.helpers.fakes import VALUE\n",
    "tests/tools/test_deploy_by_path.py": "TOOL = 'tools/review_deploy_tool.py'\n",
    "tests/gateway/test_store.py": "from review_gateway.store import VALUE\n",
    "tests/gateway/test_schema.py": "SCHEMA = 'sync-contract.v1.json'\n",
    "tests/gui/conftest.py": "",
    "tests/gui/test_panel.py": "def test_x():\n    pass\n",
}


@pytest.fixture(scope="module")
def tree(tmp_path_factory: pytest.TempPathFactory) -> Path:
    root = tmp_path_factory.mktemp("affected")
    for relative, text in FILES.items():
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    subprocess.run(["git", "init", "-q"], cwd=root, check=True)
    return root


def _select(tree: Path, *changed: str) -> list[str]:
    active = [path for path in FILES if Path(path).name.startswith("test_")]
    return affected_tests.select(changed, root=tree, active=active)


def test_a_split_out_module_selects_its_own_and_its_facades_tests(tree: Path) -> None:
    # The stale version pin of #466 lived in a test that imported only the facade.
    assert _select(tree, "src/catalog_animate.py") == [
        "tests/video/test_animate.py",
        "tests/video/test_catalog.py",
    ]


def test_a_change_reaches_tests_through_a_helper_module(tree: Path) -> None:
    assert _select(tree, "src/other.py") == ["tests/video/test_uses_a_helper.py"]


def test_files_loaded_by_path_and_service_packages_are_found(tree: Path) -> None:
    assert _select(tree, "tools/review_deploy_tool.py") == ["tests/tools/test_deploy_by_path.py"]
    assert _select(tree, "services/gateway/review_gateway/store.py") == [
        "tests/gateway/test_store.py"
    ]
    assert _select(tree, "docs/schemas/sync-contract.v1.json") == ["tests/gateway/test_schema.py"]


def test_changed_tests_folder_conftests_and_unrelated_documents(tree: Path) -> None:
    assert _select(tree, "tests/video/test_registry.py") == ["tests/video/test_registry.py"]
    assert _select(tree, "tests/gui/conftest.py") == ["tests/gui/test_panel.py"]
    assert _select(tree, "docs/notes.md", "src/deleted_module.py") == []


def test_journeys_the_hosted_runner_skips_are_left_out(tree: Path) -> None:
    (skipped,) = affected_tests.HOSTED_RUNNER_SKIPS

    assert affected_tests.select([skipped], root=tree, active=[skipped]) == []
    assert (affected_tests.ROOT / skipped).is_file()


def test_changed_files_include_committed_uncommitted_and_untracked_work(tmp_path: Path) -> None:
    def git(*args: str) -> None:
        subprocess.run(
            ["git", "-c", "user.email=t@example.invalid", "-c", "user.name=t", *args],
            cwd=tmp_path,
            check=True,
            capture_output=True,
        )

    git("init", "-q")
    for name in ("committed.py", "edited.py"):
        (tmp_path / name).write_text("a\n", encoding="utf-8")
    git("add", "-A")
    git("commit", "-qm", "base")
    git("branch", "base")
    (tmp_path / "committed.py").write_text("b\n", encoding="utf-8")
    git("commit", "-qam", "change")
    (tmp_path / "edited.py").write_text("b\n", encoding="utf-8")
    (tmp_path / "new.py").write_text("c\n", encoding="utf-8")

    assert affected_tests.changed_files("base", root=tmp_path) == [
        "committed.py",
        "edited.py",
        "new.py",
    ]


def test_the_selection_runs_with_the_hosted_runners_missing_tools_hidden(monkeypatch) -> None:
    observed: dict[str, object] = {}

    def fake_run(command, **kwargs):
        observed.update(command=command, env=kwargs["env"])
        argsfile = next(item for item in command if item.startswith("@"))[1:]
        observed["selected"] = Path(argsfile).read_text(encoding="utf-8").split()
        return subprocess.CompletedProcess(command, 3)

    monkeypatch.setattr(affected_tests.subprocess, "run", fake_run)

    assert affected_tests.run(["tests/a/test_one.py"]) == 3
    assert observed["selected"] == ["tests/a/test_one.py"]
    assert observed["env"][affected_tests.CI_PARITY_ENV] == "1"
    assert set(affected_tests.census_shards.pytest_args()) <= set(observed["command"])


def test_the_parity_switch_name_matches_the_helper_that_reads_it() -> None:
    from tests.helpers import host_isolation

    assert affected_tests.CI_PARITY_ENV == host_isolation.CI_PARITY_ENV
