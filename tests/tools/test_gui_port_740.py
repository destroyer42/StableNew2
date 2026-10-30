"""Hermetic proof-package checks: ordinary CI needs neither PySide6 nor a GUI."""

from __future__ import annotations

import ast
import json
import subprocess
import sys

import pytest

from tools.qualification.gui_port_740.common import (
    ROOT,
    rows,
    source_identity,
    summary,
    visible_render_evidence,
)
from tools.qualification.gui_port_740.run import main


def test_synthetic_revision_has_stable_selection_and_actual_membership_change():
    initial, revised = rows(500), rows(500, 1)
    assert len(initial) == len(revised) == 500
    left, right = {r[0]: r for r in initial}, {r[0]: r for r in revised}
    assert len(left.keys() - right.keys()) == len(right.keys() - left.keys()) == 10
    assert left["synthetic-00050"][1] != right["synthetic-00050"][1]


def test_default_entrypoint_is_explicitly_not_run_without_importing_qt(capsys):
    before = {name for name in sys.modules if name.startswith("PySide6")}
    assert main([]) == 2
    assert json.loads(capsys.readouterr().out)["status"] == "NOT RUN"
    assert {name for name in sys.modules if name.startswith("PySide6")} == before


def test_shared_contracts_import_and_state_notifications_without_tk():
    code = """
import json
from tools.qualification.gui_port_740.common import forbid_tk
forbid_tk()
from src.controller.ports.ui_dispatcher import ImmediateUiDispatcher
from src.gui.app_state_v2 import AppStateV2
from src.gui.view_contracts.task_navigation_contract import all_tab_ids, get_destination
s=AppStateV2(); s.set_invoker(ImmediateUiDispatcher()); calls=[]
def listener(): calls.append('ok')
s.subscribe('proof',listener); s._notify('proof'); s.unsubscribe('proof',listener); s._notify('proof')
assert calls==['ok'] and len(all_tab_ids())==9 and get_destination('invalid') is None
print(json.dumps({'status':'PASS'}))
"""
    result = subprocess.run(
        [sys.executable, "-c", code], cwd=ROOT, capture_output=True, text=True, timeout=15
    )
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)["status"] == "PASS"


def test_distribution_lock_is_exact_official_wheels_and_matching_qt_versions():
    entries = json.loads(
        (ROOT / "tools/qualification/gui_port_740/artifacts.json").read_text(encoding="utf8")
    )
    for item in entries:
        assert item["url"].startswith("https://files.pythonhosted.org/") and item["url"].endswith(
            ".whl"
        )
        assert len(item["sha256"]) == 64
    qt = {
        item["name"].lower(): item["version"]
        for item in entries
        if item["name"].lower().startswith(("pyside", "shiboken"))
    }
    assert (
        qt["pyside6"]
        == qt["pyside6_essentials"]
        == qt["pyside6_addons"]
        == qt["shiboken6"]
        == "6.12.0"
    )


def test_optional_qt_module_only_has_the_required_widget_imports():
    folder = ROOT / "tools/qualification/gui_port_740"
    for path in folder.glob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and (node.module or "").startswith("PySide6"):
                assert node.module in {"PySide6", "PySide6.QtCore"}
                if node.module == "PySide6":
                    assert {alias.name for alias in node.names} <= {"QtCore", "QtGui", "QtWidgets"}


def test_evidence_fingerprints_and_latency_summary_are_inspectable():
    identities = source_identity()
    assert set(identities) >= {
        "qt_child.py",
        "qt_dispatcher.py",
        "tk_child.py",
        "run.py",
        "common.py",
    }
    assert all(len(value) == 64 for value in identities.values())
    assert summary([1, 2, 3, 4, 5]) == {"n": 5, "min": 1, "median": 3, "p95": 5, "max": 5}


def test_premap_or_missing_warm_render_is_never_accepted():
    assert not visible_render_evidence(
        {"visible": False}, {"toolkit": "tk", "warm_visible_rendered": True}
    )
    assert not visible_render_evidence({"visible": True}, {"toolkit": "tk"})
    assert visible_render_evidence(
        {"visible": True}, {"toolkit": "tk", "warm_visible_rendered": True}
    )
    assert not visible_render_evidence(
        {"visible": True}, {"toolkit": "qt", "warm_visible_rendered": True}
    )
    assert visible_render_evidence(
        {"visible": True, "exposed": True}, {"toolkit": "qt", "warm_visible_rendered": True}
    )


@pytest.mark.parametrize("samples", ["0", "6"])
def test_invalid_sample_bounds_are_refused_before_gui_start(tmp_path, samples):
    with pytest.raises(SystemExit):
        main(["--allow-gui", "--output", str(tmp_path / "unused"), "--samples", samples])
    assert not (tmp_path / "unused").exists()
