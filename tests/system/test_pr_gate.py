from __future__ import annotations

from types import SimpleNamespace

from tools.ci import run_pr_gate


def test_pr_gate_runs_each_authority_in_order(monkeypatch) -> None:
    observed: list[str] = []

    def fake_run(command, **_kwargs):
        observed.append(command[1].replace("\\", "/").split("/")[-1])
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(run_pr_gate.subprocess, "run", fake_run)
    monkeypatch.setattr(run_pr_gate, "missing_required_tools", lambda: [])

    assert run_pr_gate.main() == 0
    assert observed == [step.split("/")[-1] for _, step in run_pr_gate.GATE_STEPS]


def test_pr_gate_stops_and_returns_underlying_failure(monkeypatch) -> None:
    observed: list[str] = []

    def fake_run(command, **_kwargs):
        script = command[1].replace("\\", "/").split("/")[-1]
        observed.append(script)
        return SimpleNamespace(returncode=7 if script == "check_controller_surface.py" else 0)

    monkeypatch.setattr(run_pr_gate.subprocess, "run", fake_run)
    monkeypatch.setattr(run_pr_gate, "missing_required_tools", lambda: [])

    assert run_pr_gate.main() == 7
    assert observed == [
        "check_repository_completeness.py",
        "check_controller_surface.py",
    ]


def test_pr_gate_reports_missing_tools_before_running_gates(monkeypatch, capsys) -> None:
    monkeypatch.setattr(run_pr_gate, "missing_required_tools", lambda: ["mypy"])

    assert run_pr_gate.main() == run_pr_gate.TOOLING_BLOCKER_EXIT_CODE
    assert "TOOLING BLOCKER" in capsys.readouterr().err


def test_pr_gate_labels_gate_failure_as_source_or_test_failure(monkeypatch, capsys) -> None:
    monkeypatch.setattr(run_pr_gate, "missing_required_tools", lambda: [])

    def fake_run(_command, **_kwargs):
        return SimpleNamespace(returncode=7)

    monkeypatch.setattr(run_pr_gate.subprocess, "run", fake_run)

    assert run_pr_gate.main() == 7
    assert "SOURCE/TEST FAILURE" in capsys.readouterr().err
