"""Deterministic ownership tests for the shutdown journey process matcher."""

from __future__ import annotations

from tools.test_helpers import process_inspection


def _process(*, pid: int, parent_pid: int | None, cmdline: tuple[str, ...], **env: str):
    return process_inspection._ProcessSnapshot(
        pid=pid,
        parent_pid=parent_pid,
        name="python.exe",
        cmdline=" ".join(cmdline),
        cwd=str(process_inspection.__file__),
        environ=env,
    )


def test_unrelated_python_or_comfy_process_is_ignored(monkeypatch) -> None:
    unrelated = _process(
        pid=41,
        parent_pid=999,
        cmdline=("python", "ComfyUI", "main.py"),
    )
    monkeypatch.setattr(process_inspection, "_collect_snapshots", lambda: [unrelated])

    assert process_inspection.list_stablenew_processes(owner_pid=123) == []
    assert process_inspection.list_managed_backend_processes(owner_pid=123) == []


def test_test_owned_stablenew_child_is_detected(monkeypatch) -> None:
    owned = _process(pid=42, parent_pid=123, cmdline=("python", "-m", "src.main"))
    monkeypatch.setattr(process_inspection, "_collect_snapshots", lambda: [owned])

    assert process_inspection.list_stablenew_processes(owner_pid=123) == [
        "42:python.exe:python -m src.main"
    ]


def test_test_owned_managed_backend_child_is_detected_separately(monkeypatch) -> None:
    backend = _process(
        pid=43,
        parent_pid=123,
        cmdline=("python", "launch.py"),
        **{process_inspection.MANAGED_BACKEND_ENV: "1"},
    )
    monkeypatch.setattr(process_inspection, "_collect_snapshots", lambda: [backend])

    assert process_inspection.list_stablenew_processes(owner_pid=123) == []
    assert process_inspection.list_managed_backend_processes(owner_pid=123) == [
        "43:python.exe:python launch.py"
    ]


def test_cleanup_does_not_target_preexisting_external_process() -> None:
    class ExternalProcess:
        pid = 44

        def terminate(self) -> None:
            raise AssertionError("external process was targeted")

    process_inspection.request_clean_shutdown(ExternalProcess())  # type: ignore[arg-type]
