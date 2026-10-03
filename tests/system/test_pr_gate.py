from __future__ import annotations

from types import SimpleNamespace

import pytest

from tools.ci import run_collection_gate, run_pr_gate


def _command_name(command: tuple[str, ...]) -> str:
    if command[0] == "ruff":
        return command[0]
    return command[1].replace("\\", "/").split("/")[-1]


def test_pr_gate_runs_each_authority_in_order(monkeypatch) -> None:
    observed: list[str] = []

    def fake_run(command, **_kwargs):
        observed.append(_command_name(command))
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(run_pr_gate.subprocess, "run", fake_run)
    monkeypatch.setattr(run_pr_gate, "missing_required_tools", lambda: [])

    assert run_pr_gate.main() == 0
    assert observed == [_command_name(command) for _, command in run_pr_gate.GATE_STEPS]


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


# --- Shared pytest-gate output contract: quiet on success, diagnostic on failure -------------


def _write_test_file(tmp_path, name: str, body: str) -> str:
    path = tmp_path / name
    path.write_text(body, encoding="utf-8")
    return str(path)


@pytest.fixture
def unchanged_repository(monkeypatch):
    """Skip hashing the real repository; the gate sees an identical snapshot twice."""

    snapshot = run_collection_gate.RepositorySnapshot(files=(), guarded=())
    monkeypatch.setattr(run_collection_gate, "snapshot_repository", lambda: snapshot)


def test_pytest_gate_success_output_is_one_compact_line(
    tmp_path, capsys, unchanged_repository
) -> None:
    target = _write_test_file(
        tmp_path,
        "test_quiet_success.py",
        "def test_a():\n    pass\n\n\ndef test_b():\n    pass\n\n\ndef test_c():\n    pass\n",
    )

    assert run_collection_gate.run_pytest_gate(["-q", target]) == 0

    captured = capsys.readouterr()
    assert captured.err == ""
    assert len(captured.out.strip().splitlines()) == 1
    assert "pytest gate OK" in captured.out
    assert "3 passed" in captured.out
    assert "test_quiet_success" not in captured.out


def test_pytest_gate_failure_keeps_full_diagnostics_and_exit_status(
    tmp_path, capsys, unchanged_repository
) -> None:
    target = _write_test_file(
        tmp_path,
        "test_loud_failure.py",
        "def test_breaks():\n    marker = 'distinctive-failure-evidence'\n    assert marker == 'x'\n",
    )

    assert run_collection_gate.run_pytest_gate(["-q", target]) == 1

    captured = capsys.readouterr()
    assert "test_breaks" in captured.out
    assert "distinctive-failure-evidence" in captured.out
    assert "1 failed" in captured.out
    assert "pytest gate FAILED (exit 1)" in captured.err
    assert "pytest gate OK" not in captured.out


def test_pytest_gate_propagates_non_failure_pytest_exit_codes(
    tmp_path, capsys, unchanged_repository
) -> None:
    empty = _write_test_file(tmp_path, "test_nothing_here.py", "VALUE = 1\n")

    assert run_collection_gate.run_pytest_gate(["-q", empty]) == 5  # no tests collected

    captured = capsys.readouterr()
    assert "no tests ran" in captured.out
    assert "pytest gate FAILED (exit 5)" in captured.err


@pytest.mark.parametrize("pytest_passes", [True, False])
def test_pytest_gate_still_fails_and_reports_repository_pollution(
    tmp_path, monkeypatch, capsys, pytest_passes
) -> None:
    body = "def test_ok():\n    pass\n" if pytest_passes else "def test_ok():\n    assert False\n"
    target = _write_test_file(tmp_path, "test_pollution.py", body)
    before = run_collection_gate.RepositorySnapshot(files=(("src/a.py", "file:1"),), guarded=())
    after = run_collection_gate.RepositorySnapshot(
        files=(("src/a.py", "file:2"),), guarded=(("output", "directory"),)
    )
    snapshots = iter([before, after])
    monkeypatch.setattr(run_collection_gate, "snapshot_repository", lambda: next(snapshots))

    assert run_collection_gate.run_pytest_gate(["-q", target]) == 1

    captured = capsys.readouterr()
    assert "pytest changed repository contents:" in captured.err
    assert "src/a.py" in captured.err and "output" in captured.err
    assert "pytest gate OK" not in captured.out
    assert ("1 passed" in captured.out) is pytest_passes  # pytest evidence is not discarded
