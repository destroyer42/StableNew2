"""Exercise offline repository indexing, routing, and capsule freshness."""

from __future__ import annotations

import ast
import json
import socket
import stat
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from tools import context_index, context_router, repo_context
from tools.generate_code_map import ROOT, module_files, only_added_docstring


def write(root: Path, path: str, content: str) -> None:
    target = root / path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding="utf-8")


@pytest.fixture
def checkout(tmp_path: Path) -> Path:
    files = {
        "src/__init__.py": '"""Fixture application."""\n',
        "src/queueing/__init__.py": '"""Queue package."""\nfrom .work import QueueRecord as Record\n__all__ = ["Record"]\n',
        "src/queueing/work.py": (
            '"""Persist immutable queue snapshots."""\n'
            "from . import missing\nfrom ..support import stable_hash as fingerprint\n"
            "from ...invalid import external_name\nimport pathlib\nimport importlib as il\n"
            "if False:\n    from . import broken\n"
            'def restore_queue():\n    il.import_module("plugin")\n    from . import broken\n'
            'class QueueRecord: pass\nraise RuntimeError("Never import during inspection")\n'
        ),
        "src/queueing/broken.py": "def invalid(:\n",
        "src/support.py": '"""Shared helpers."""\ndef stable_hash(): pass\n',
        "src/gui/view.py": (
            '"""Show queue snapshots in the GUI."""\n'
            "from src.queueing.work import QueueRecord\nfrom src.support import stable_hash\n"
        ),
        "src/video/view.py": '"""Show video outputs."""\nfrom src.support import stable_hash\n',
        "tests/test_work.py": "from src.queueing.work import QueueRecord\ndef test_restore_queue(): pass\n",
        "tests/test_view.py": "def test_display_video(): pass\n",
        "docs/CODEX_MAP.md": (
            "| Queue snapshots | \x60src/queueing/work.py\x60; \x60docs/Subsystems/Runtime/LIVING.md\x60 |\n"
        ),
        "docs/Subsystems/README.md": "- [Repository](Runtime/LIVING.md)\n",
        "docs/Subsystems/Runtime/LIVING.md": "Queue reading starts at \x60src/queueing/work.py\x60.\n",
        ".gitignore": "src/cache/\noutput/\n",
    }
    for path, source in files.items():
        write(tmp_path, path, source)
    context_index.git(tmp_path, "init", "-q")
    context_index.git(
        tmp_path, "config", "remote.origin.url", "https://github.com/destroyer42/StableNew2.git"
    )
    context_index.git(tmp_path, "add", ".")
    context_index.git(
        tmp_path,
        "-c",
        "user.name=Fixture",
        "-c",
        "user.email=fixture@example.invalid",
        "-c",
        "commit.gpgsign=false",
        "commit",
        "-qm",
        "fixture",
    )
    return tmp_path


def test_static_index_records_resolution_symbols_and_limitations(
    checkout: Path, monkeypatch
) -> None:
    def no_network(*args, **kwargs):
        pytest.fail("The context index tried to use the network")

    monkeypatch.setattr(socket, "socket", no_network)
    imports_before = set(sys.modules)
    index = context_index.build(checkout)
    paths = index["modules"]
    assert index["schema"] == context_index.INDEX_VERSION
    assert list(paths) == sorted(paths)
    entry = paths["src/queueing/work.py"]
    assert entry["module"] == "src.queueing.work"
    assert entry["summary"] == "Persist immutable queue snapshots"
    assert entry["symbols"]["QueueRecord"]["kind"] == "class"
    assert entry["symbols"]["restore_queue"]["kind"] == "function"
    assert entry["symbols"]["fingerprint"]["kind"] == "binding"
    assert {
        ("static", "src.support.stable_hash"),
        ("attribute-unverified", "src.queueing.missing"),
    } <= {(edge["state"], edge["name"]) for edge in entry["imports"]}
    assert {"external", "unresolved", "dynamic-syntax"} <= {
        edge["state"] for edge in entry["imports"]
    }
    assert any(
        edge["guarded"] for edge in entry["imports"] if edge["name"] == "src.queueing.broken"
    )
    assert any(
        edge["deferred"] for edge in entry["imports"] if edge["name"] == "src.queueing.broken"
    )
    assert entry["dependencies"] == [
        "src/queueing/__init__.py",
        "src/queueing/broken.py",
        "src/support.py",
    ]
    assert entry["package_initializers"] == ["src/__init__.py"]
    assert entry["dependents"] == ["src/gui/view.py", "src/queueing/__init__.py"]
    assert entry["docs"] == {"docs/Subsystems/Runtime/LIVING.md": "living record references path"}
    assert entry["tests"] == {"tests/test_work.py": "static import"}
    assert paths["src/queueing/__init__.py"]["symbols"]["Record"]["explicit_export"]
    assert paths["src/gui/view.py"]["tests"] == {"tests/test_view.py": "matching test filename"}
    assert not paths["src/queueing/broken.py"]["parsed"]
    assert not any(name.startswith("src.queueing") for name in set(sys.modules) - imports_before)
    assert context_index.json_text(index) == context_index.json_text(context_index.build(checkout))


def test_paths_are_scoped_and_checkout_freshness_uses_actual_bytes(checkout: Path) -> None:
    old = context_index.build(checkout)
    path = "src/queueing/work.py"
    write(checkout, path, '"""Changed summary."""\n')
    write(checkout, "src/new.py", '"""Untracked source."""\n')
    write(checkout, "src/cache/private.py", "secret = True\n")
    write(checkout, "output/private.py", "secret = True\n")
    changed = context_index.build(checkout)
    assert changed["identity"]["head"] == old["identity"]["head"]
    assert changed["identity"]["dirty"]
    assert changed["identity"]["fingerprint"] != old["identity"]["fingerprint"]
    assert changed["modules"][path]["sha256"] != old["modules"][path]["sha256"]
    assert "src/new.py" in changed["modules"]
    assert not any("private" in path for path in changed["modules"])
    for unsafe in (
        "../private.py",
        "src/queueing/../support.py",
        "C:/private.py",
        "src//support.py",
    ):
        assert context_index.candidate_path(checkout, unsafe) is None


def test_source_symlinks_are_not_followed(checkout: Path, monkeypatch) -> None:
    write(checkout, "src/external.py", "raise RuntimeError('outside')\n")
    original = Path.lstat
    monkeypatch.setattr(
        Path,
        "lstat",
        lambda path: SimpleNamespace(st_mode=stat.S_IFLNK)
        if path.name == "external.py"
        else original(path),
    )
    assert "src/external.py" not in context_index.build(checkout)["modules"]


def test_git_status_disables_configured_filters(checkout: Path, monkeypatch) -> None:
    calls = []

    def inspect(root, *args):
        calls.append(args)
        return ""

    monkeypatch.setattr(context_index, "git", inspect)
    context_index.checkout_status(
        checkout,
        ["core.editor", "filter.sample.clean", "filter.sample.process", "filter.sample.required"],
    )
    assert calls[0][:6] == (
        "-c",
        "filter.sample.clean=",
        "-c",
        "filter.sample.process=",
        "-c",
        "filter.sample.required=false",
    )


def test_navigation_resolves_paths_embedded_in_commands() -> None:
    path = "tools/ci/run_pr_gate.py"
    assert context_index.references(f"Use \x60python {path}\x60", "docs", {path}) == [path]


def test_routing_uses_index_only_with_narrow_and_ambiguous_matches(
    checkout: Path, monkeypatch
) -> None:
    index = context_index.build(checkout)
    index["modules"]["src/support.py"]["dependents"] += [f"src/shared{n}.py" for n in range(22)]

    def no_reads(*args, **kwargs):
        pytest.fail("Routing should use only the generated index")

    monkeypatch.setattr(Path, "read_bytes", no_reads)
    exact = context_router.route(index, "Check src/queueing/work.py")
    assert [item["path"] for item in exact["sources"]] == ["src/queueing/work.py"]
    assert exact["sources"][0]["evidence"] == "direct"
    assert not any(item["path"] == "src/support.py" for item in exact["dependencies"])
    symbol = context_router.route(index, "Investigate QueueRecord")
    assert symbol["sources"][0]["why"].startswith("Exact symbol QueueRecord at line")
    natural = context_router.route(index, "Persist immutable queue snapshots")
    assert natural["sources"][0]["path"] == "src/queueing/work.py"
    assert any(
        item["path"] == "src/gui/view.py" for item in natural["sources"] + natural["dependencies"]
    )
    assert natural["tests"][0]["evidence"] == "static"
    assert context_router.route(index, "Fix view.py")["confidence"] == "ambiguous"
    assert (
        context_router.route(index, "Calculate exoplanet orbital velocity")["confidence"]
        == "no-match"
    )
    assert context_router.route(index, "Persist immutable queue snapshots") == natural
    assert (
        len(context_router.route(index, "queue snapshots", limit=1, broader=True)["sources"]) == 1
    )


def test_capsule_budget_order_provenance_and_verified_identity(checkout: Path) -> None:
    index = context_index.build(checkout)
    result = context_router.route(index, "Repair QueueRecord persistence")
    result["tests"].append(result["sources"][0])
    output = repo_context.capsule(index, result, 650, repo_context.json_line)
    assert output == repo_context.capsule(index, result, 650, repo_context.json_line)
    assert repo_context.size_units(output) <= 650
    data = json.loads(output)
    assert data["authority"] == ["AGENTS.md", "STATUS.md", "docs/CODEX_MAP.md"]
    assert data["reading_order"][:2] == ["docs", "sources"]
    paths = [row["path"] for group in repo_context.GROUPS for row in data[group]]
    assert len(set(paths)) == len(paths)
    assert data["sources"][0]["evidence"] == "direct"
    assert data["sources"][0]["import_uncertainty"]["dynamic-syntax"] == 1
    assert "reflection" in data["limitations"]
    markup = repo_context.capsule(index, result, 650, repo_context.markdown)
    assert repo_context.size_units(markup) <= 650
    assert markup.index("AGENTS.md") < markup.index("Implementation surfaces")
    repo_context.verify(data, index["identity"])
    write(checkout, "src/support.py", '"""A changed dependency."""\n')
    with pytest.raises(ValueError, match="Stale or mismatched"):
        repo_context.verify(data, context_index.snapshot(checkout)[0])


def test_cli_builds_index_without_saved_state_and_reports_invalid_checkout(checkout: Path) -> None:
    args = [sys.executable, "-m", "tools.repo_context", "--root"]
    captured = subprocess.run(
        [*args, str(checkout), "capsule", "QueueRecord", "--format", "json"],
        cwd=ROOT,
        check=True,
        capture_output=True,
    ).stdout
    verification = subprocess.run(
        [*args, str(checkout), "verify"],
        input=captured,
        cwd=ROOT,
        check=True,
        capture_output=True,
    )
    assert json.loads(verification.stdout)["status"] == "current"
    invalid = subprocess.run(
        [*args, str(checkout.parent), "route", "QueueRecord"],
        cwd=ROOT,
        capture_output=True,
    )
    assert invalid.returncode == 1
    assert b"Repository context unavailable" in invalid.stderr
    context_index.git(
        checkout, "config", "remote.origin.url", "https://example.invalid/other/project"
    )
    with pytest.raises(ValueError, match="origin destroyer42/StableNew2"):
        context_index.build(checkout)


def test_every_source_module_has_a_module_docstring() -> None:
    paths = module_files(ROOT)
    assert paths
    assert [path for path in paths if not ast.get_docstring(ast.parse(path.read_bytes()))] == []


def test_docstring_ast_comparison_preserves_executable_structure() -> None:
    before = b"# encoding: utf-8\nfrom __future__ import annotations\nVALUE = 1\n"
    after = (
        b'# encoding: utf-8\n"""Describe the configuration value."""\n' + before.split(b"\n", 1)[1]
    )
    assert only_added_docstring(before, after)
    assert not only_added_docstring(before, after.replace(b"VALUE = 1", b"VALUE = 2"))
    assert not only_added_docstring(after, after.replace(b"configuration", b"default"))
