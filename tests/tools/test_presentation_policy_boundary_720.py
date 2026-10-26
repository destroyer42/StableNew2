"""Shared policies cannot depend on the Tk package, including hidden local imports."""

from __future__ import annotations

import ast
import subprocess
import sys
from collections import deque
from pathlib import Path

import pytest

from tools.ci import check_controller_tk_boundary as boundary

ROOT = Path(__file__).resolve().parents[2]
POLICIES = (
    "src.state.content_visibility",
    "src.review.workflow_adapter",
    "src.gui_v2.adapters.config_adapter_v26",
)


def forbidden(module):
    return module == boundary.TKINTER or module == "src.gui" or module.startswith("src.gui.")


@pytest.mark.parametrize("policy", POLICIES)
def test_policy_import_closure_and_all_local_imports_exclude_tk_host(policy):
    graph, modules = boundary.build_graph(ROOT / "src")
    pending = deque([(policy, [policy])])
    visited = set()
    while pending:
        module, path = pending.popleft()
        if module in visited:
            continue
        visited.add(module)
        assert not forbidden(module), " -> ".join(path)
        pending.extend((target, [*path, target]) for target in graph.get(module, ()))
    # The runtime graph intentionally ignores TYPE_CHECKING and function bodies.
    # Check every import in the new policies as well: no local/type-only GUI escape.
    tree = ast.parse(modules[policy].read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            targets = boundary._targets_for_import(node, policy, False, modules)
            assert not any(forbidden(target) for target in targets)
        if isinstance(node, ast.Call):
            # These policies need neither dynamic imports nor a dependency locator.
            assert not (isinstance(node.func, ast.Name) and node.func.id == "__import__")
            assert not (isinstance(node.func, ast.Attribute) and node.func.attr == "import_module")


def test_policy_imports_and_contract_operations_work_with_tk_and_gui_imports_refused():
    code = r"""
import importlib.abc
import json
import sys
from pathlib import Path

class RefuseTkHost(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname in {"tkinter", "src.gui"} or fullname.startswith(("tkinter.", "src.gui.")):
            raise AssertionError("Forbidden host import: " + fullname)

sys.meta_path.insert(0, RefuseTkHost())
from tests.gui_v2.test_shared_presentation_policy_720 import contract_snapshot
actual = contract_snapshot("src.state.content_visibility", "src.review.workflow_adapter",
                           "src.gui_v2.adapters.config_adapter_v26")
expected = json.loads(Path("tests/fixtures/presentation_policy_720.json").read_text(encoding="utf-8"))
assert actual == expected
assert not any(name in {"tkinter", "src.gui"} or name.startswith(("tkinter.", "src.gui.")) for name in sys.modules)
print("neutral imports and operations passed")
"""
    result = subprocess.run(
        [sys.executable, "-c", code],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "neutral imports and operations passed" in result.stdout
