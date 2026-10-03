"""Tests for the process inspector helpers."""

from __future__ import annotations

import pytest

from src.utils import process_inspector_v2


def _tree_process(pid, parent_pid, kind="webui", rss_mb=100.0, create_time=None):
    commands = {"webui": ("python", "launch.py"), "main": ("python", "-m", "src.main"),
                "bridge": ("python", "helper.py"), "pytest": ("python", "-m", "pytest")}
    return process_inspector_v2.ProcessInfo(
        pid=pid, parent_pid=parent_pid, name="python.exe", cmdline=commands[kind],
        cwd=str(process_inspector_v2.REPO_ROOT), create_time=create_time,
        rss_mb=rss_mb, env_markers=(),
    )


@pytest.mark.parametrize(
    "kind,shape,roots",
    [
        ("webui", [(10, None, "webui")], [10]),
        ("webui", [(10, None, "webui"), (11, 10, "webui")], [10]),
        ("webui", [(10, None, "webui"), (11, 10, "bridge"), (12, 11, "webui")], [10]),
        ("webui", [(10, None, "webui"), (20, None, "webui")], [10, 20]),
        ("webui", [(10, None, "webui"), (11, 10, "webui"),
                   (20, None, "webui"), (21, 20, "webui")], [10, 20]),
        ("main", [(10, None, "main"), (11, 10, "main")], [10]),
        ("main", [(10, None, "main"), (11, 10, "bridge"), (12, 11, "main")], [10]),
        ("main", [(10, None, "main"), (20, None, "main")], [10, 20]),
        ("main", [(10, None, "main"), (11, 10, "main"),
                  (20, None, "main"), (21, 20, "main")], [10, 20]),
        # Shared executable/cwd or an unknown parent cannot establish matching ancestry.
        ("webui", [(10, 99, "webui"), (20, 99, "webui")], [10, 20]),
        ("webui", [(10, 20, "webui"), (20, 10, "webui")], [10, 20]),
        ("webui", [(10, 10, "webui"), (20, None, "webui")], [10, 20]),
    ],
)
def test_process_risk_counts_independent_matching_trees(monkeypatch, kind, shape, roots):
    # Child-first ordering proves grouping does not depend on scan order.
    processes = [_tree_process(*item) for item in reversed(shape)]
    monkeypatch.setattr(process_inspector_v2, "iter_stablenew_like_processes",
                        lambda: iter(processes))
    risk = process_inspector_v2.collect_process_risk_snapshot()
    raw_key = "webui_process_count" if kind == "webui" else "significant_main_process_count"
    prefix = "webui_runtime_tree" if kind == "webui" else "significant_main_tree"
    raw = sum(item[2] == kind for item in shape)
    assert risk[raw_key] == raw
    if kind == "main":
        assert risk["main_process_count"] == raw
    assert risk[prefix + "_count"] == len(roots)
    assert risk[prefix + "_roots"] == roots
    duplicate_reason = "duplicate_webui_process" if kind == "webui" else "duplicate_stablenew_main"
    members = {p["pid"] for p in risk["suspicious_processes"]
               if duplicate_reason in p["reasons"]}
    if len(roots) > 1:
        assert risk["status"] == "critical"
        assert members == {pid for pid, _, candidate_kind in shape if candidate_kind == kind}
    else:
        assert risk["status"] == "normal"
        assert members == set()


def test_tree_grouping_preserves_unrelated_high_rss_and_stale_pytest(monkeypatch):
    processes = [_tree_process(10, None), _tree_process(11, 10),
                 _tree_process(20, None, "pytest", rss_mb=600, create_time=100)]
    monkeypatch.setattr(process_inspector_v2, "iter_stablenew_like_processes",
                        lambda: iter(processes))
    monkeypatch.setattr(process_inspector_v2.time, "time", lambda: 1000)
    risk = process_inspector_v2.collect_process_risk_snapshot()
    assert risk["webui_process_count"] == 2
    assert risk["webui_runtime_tree_count"] == 1
    assert risk["status"] == "warning"
    assert [(p["pid"], p["reasons"]) for p in risk["suspicious_processes"]] == [
        (20, ["high_rss_512mb_plus", "stale_pytest_process"])
    ]


class _DummyProcess:
    def __init__(self, info: dict[str, object]) -> None:
        self.info = info

    def cmdline(self) -> list[str]:
        return list(self.info.get("cmdline") or [])

    def memory_info(self):
        class _MemInfo:
            def __init__(self, rss: float) -> None:
                self.rss = rss

        rss = float(self.info.get("rss") or 0.0)
        return _MemInfo(rss)

    def environ(self) -> dict[str, str]:
        return dict(self.info.get("environ") or {})


def _require_psutil() -> None:
    if process_inspector_v2.psutil is None:
        pytest.skip("psutil unavailable in this environment")


def test_iter_python_processes_returns_py_only(monkeypatch) -> None:
    _require_psutil()

    python_info = {
        "pid": 42,
        "name": "python.exe",
        "cmdline": ["python", "some_script.py"],
        "cwd": str(process_inspector_v2.REPO_ROOT),
        "create_time": 1.0,
        "rss": 0.0,
        "environ": {"STABLENEW_RUN_ID": "run-1"},
    }
    other_info = {
        "pid": 99,
        "name": "cmd.exe",
        "cmdline": ["cmd", "/C", "echo"],
        "cwd": "C:/Windows",
        "create_time": 2.0,
        "rss": 0.0,
        "environ": {},
    }

    monkeypatch.setattr(
        process_inspector_v2.psutil,
        "process_iter",
        lambda attrs=None: iter([_DummyProcess(python_info), _DummyProcess(other_info)]),
    )

    results = list(process_inspector_v2.iter_python_processes())

    assert len(results) == 1
    result = results[0]
    assert result.pid == 42
    assert "run-1" in result.env_markers[0]


def test_hold_process_scan_lock_is_reentrant() -> None:
    with process_inspector_v2.hold_process_scan_lock():
        with process_inspector_v2.hold_process_scan_lock():
            assert True


def test_iter_stablenew_like_processes_filters(monkeypatch) -> None:
    python_one = process_inspector_v2.ProcessInfo(
        pid=1,
        parent_pid=None,
        name="python",
        cmdline=("python", "some_script.py"),
        cwd=str(process_inspector_v2.REPO_ROOT),
        create_time=0.0,
        rss_mb=12.0,
        env_markers=(),
    )
    python_two = process_inspector_v2.ProcessInfo(
        pid=2,
        parent_pid=1,
        name="python",
        cmdline=("python", "a1111_upscale_folder.py"),
        cwd="/usr/bin",
        create_time=0.0,
        rss_mb=8.0,
        env_markers=(),
    )

    monkeypatch.setattr(
        process_inspector_v2,
        "iter_python_processes",
        lambda: iter([python_one, python_two]),
    )

    result = list(process_inspector_v2.iter_stablenew_like_processes())

    assert result == [python_one, python_two]


def test_iter_stablenew_like_processes_skips_vscode_extension_workers(monkeypatch) -> None:
    vscode_worker = process_inspector_v2.ProcessInfo(
        pid=10,
        parent_pid=None,
        name="python.exe",
        cmdline=(
            "python",
            "C:/Users/rob/.vscode/extensions/ms-python.mypy-type-checker-2025.2.0/bundled/tool/lsp_server.py",
        ),
        cwd=str(process_inspector_v2.REPO_ROOT),
        create_time=0.0,
        rss_mb=15.0,
        env_markers=("STABLENEW_RIFE_EXE=C:/tools/rife.exe",),
    )

    monkeypatch.setattr(
        process_inspector_v2,
        "iter_python_processes",
        lambda: iter([vscode_worker]),
    )

    result = list(process_inspector_v2.iter_stablenew_like_processes())

    assert result == []


def test_iter_stablenew_like_processes_keeps_debugpy_main_process(monkeypatch) -> None:
    debugpy_main = process_inspector_v2.ProcessInfo(
        pid=20,
        parent_pid=None,
        name="python.exe",
        cmdline=(
            "python",
            "-m",
            "debugpy",
            "--listen",
            "5678",
            "-m",
            "src.main",
        ),
        cwd=str(process_inspector_v2.REPO_ROOT),
        create_time=0.0,
        rss_mb=300.0,
        env_markers=(),
    )

    monkeypatch.setattr(
        process_inspector_v2,
        "iter_python_processes",
        lambda: iter([debugpy_main]),
    )

    result = list(process_inspector_v2.iter_stablenew_like_processes())

    assert result == [debugpy_main]


def test_iter_stablenew_like_processes_includes_descendant_runtime_children(monkeypatch) -> None:
    main_process = process_inspector_v2.ProcessInfo(
        pid=30,
        parent_pid=None,
        name="python.exe",
        cmdline=("python", "-m", "src.main"),
        cwd=str(process_inspector_v2.REPO_ROOT),
        create_time=0.0,
        rss_mb=500.0,
        env_markers=(),
    )
    webui_child = process_inspector_v2.ProcessInfo(
        pid=31,
        parent_pid=30,
        name="python.exe",
        cmdline=("python", "launch.py"),
        cwd="C:/tools/stable-diffusion-webui",
        create_time=0.0,
        rss_mb=700.0,
        env_markers=(),
    )
    vscode_worker = process_inspector_v2.ProcessInfo(
        pid=32,
        parent_pid=None,
        name="python.exe",
        cmdline=(
            "python",
            "C:/Users/rob/.vscode/extensions/ms-python.mypy-type-checker-2025.2.0/bundled/tool/lsp_server.py",
        ),
        cwd=str(process_inspector_v2.REPO_ROOT),
        create_time=0.0,
        rss_mb=20.0,
        env_markers=(),
    )

    monkeypatch.setattr(
        process_inspector_v2,
        "iter_python_processes",
        lambda: iter([main_process, webui_child, vscode_worker]),
    )

    result = list(process_inspector_v2.iter_stablenew_like_processes())

    assert result == [main_process, webui_child]


def test_collect_process_risk_snapshot_ignores_single_main_process_high_rss(monkeypatch) -> None:
    main_process = process_inspector_v2.ProcessInfo(
        pid=1,
        parent_pid=None,
        name="python.exe",
        cmdline=("python", "-m", "src.main"),
        cwd=str(process_inspector_v2.REPO_ROOT),
        create_time=0.0,
        rss_mb=1200.0,
        env_markers=(),
    )

    monkeypatch.setattr(
        process_inspector_v2,
        "iter_stablenew_like_processes",
        lambda: iter([main_process]),
    )

    result = process_inspector_v2.collect_process_risk_snapshot()

    assert result["status"] == "normal"
    assert result["main_process_count"] == 1
    assert result["suspicious_processes"] == []


def test_collect_process_risk_snapshot_marks_duplicate_main_processes_critical(monkeypatch) -> None:
    main_a = process_inspector_v2.ProcessInfo(
        pid=1,
        parent_pid=None,
        name="python.exe",
        cmdline=("python", "-m", "src.main"),
        cwd=str(process_inspector_v2.REPO_ROOT),
        create_time=0.0,
        rss_mb=950.0,
        env_markers=(),
    )
    main_b = process_inspector_v2.ProcessInfo(
        pid=2,
        parent_pid=None,
        name="python.exe",
        cmdline=("python", "-m", "src.main"),
        cwd=str(process_inspector_v2.REPO_ROOT),
        create_time=0.0,
        rss_mb=940.0,
        env_markers=(),
    )

    monkeypatch.setattr(
        process_inspector_v2,
        "iter_stablenew_like_processes",
        lambda: iter([main_a, main_b]),
    )

    result = process_inspector_v2.collect_process_risk_snapshot()

    assert result["status"] == "critical"
    assert result["main_process_count"] == 2
    assert result["significant_main_tree_count"] == 2
    assert len(result["suspicious_processes"]) == 2


def test_collect_process_risk_snapshot_ignores_tiny_duplicate_main_process(monkeypatch) -> None:
    main_a = process_inspector_v2.ProcessInfo(
        pid=1,
        parent_pid=None,
        name="python.exe",
        cmdline=("python", "-m", "src.main"),
        cwd=str(process_inspector_v2.REPO_ROOT),
        create_time=0.0,
        rss_mb=900.0,
        env_markers=(),
    )
    main_b = process_inspector_v2.ProcessInfo(
        pid=2,
        parent_pid=1,
        name="python.exe",
        cmdline=("python", "-m", "src.main"),
        cwd=str(process_inspector_v2.REPO_ROOT),
        create_time=0.0,
        rss_mb=8.0,
        env_markers=(),
    )

    monkeypatch.setattr(
        process_inspector_v2,
        "iter_stablenew_like_processes",
        lambda: iter([main_a, main_b]),
    )

    result = process_inspector_v2.collect_process_risk_snapshot()

    assert result["status"] == "normal"
    assert result["main_process_count"] == 2
    assert result["significant_main_process_count"] == 1
    assert result["suspicious_processes"] == []


def test_collect_process_risk_snapshot_ignores_comfyui_runtime_high_rss(monkeypatch) -> None:
    main_process = process_inspector_v2.ProcessInfo(
        pid=1,
        parent_pid=None,
        name="python.exe",
        cmdline=("python", "-m", "src.main"),
        cwd=str(process_inspector_v2.REPO_ROOT),
        create_time=0.0,
        rss_mb=900.0,
        env_markers=(),
    )
    comfy_process = process_inspector_v2.ProcessInfo(
        pid=2,
        parent_pid=1,
        name="python.exe",
        cmdline=(
            "python",
            "E:/Users/rober/AppData/Local/Programs/ComfyUI/resources/ComfyUI/main.py",
            "--listen",
            "127.0.0.1",
            "--port",
            "8000",
        ),
        cwd="E:/Users/rober/AppData/Local/Programs/ComfyUI/resources/ComfyUI",
        create_time=0.0,
        rss_mb=756.5,
        env_markers=(),
    )

    monkeypatch.setattr(
        process_inspector_v2,
        "iter_stablenew_like_processes",
        lambda: iter([main_process, comfy_process]),
    )

    result = process_inspector_v2.collect_process_risk_snapshot()

    assert result["status"] == "normal"
    assert result["webui_process_count"] == 0
    assert result["comfy_process_count"] == 1
    assert result["suspicious_processes"] == []


def test_collect_process_risk_snapshot_does_not_treat_duplicate_comfyui_as_duplicate_webui(
    monkeypatch,
) -> None:
    main_process = process_inspector_v2.ProcessInfo(
        pid=1,
        parent_pid=None,
        name="python.exe",
        cmdline=("python", "-m", "src.main"),
        cwd=str(process_inspector_v2.REPO_ROOT),
        create_time=0.0,
        rss_mb=900.0,
        env_markers=(),
    )
    comfy_launcher = process_inspector_v2.ProcessInfo(
        pid=2,
        parent_pid=1,
        name="python.exe",
        cmdline=(
            "E:/Users/rober/ComfyUI/.venv-explicit/Scripts/python.exe",
            "E:/Users/rober/AppData/Local/Programs/ComfyUI/resources/ComfyUI/main.py",
            "--listen",
        ),
        cwd="E:/Users/rober/AppData/Local/Programs/ComfyUI/resources/ComfyUI",
        create_time=0.0,
        rss_mb=4.5,
        env_markers=(),
    )
    comfy_worker = process_inspector_v2.ProcessInfo(
        pid=3,
        parent_pid=2,
        name="python.exe",
        cmdline=(
            "C:/Users/rob/AppData/Local/Programs/Python/Python310/python.exe",
            "E:/Users/rober/AppData/Local/Programs/ComfyUI/resources/ComfyUI/main.py",
            "--listen",
        ),
        cwd="E:/Users/rober/AppData/Local/Programs/ComfyUI/resources/ComfyUI",
        create_time=0.0,
        rss_mb=756.8,
        env_markers=(),
    )

    monkeypatch.setattr(
        process_inspector_v2,
        "iter_stablenew_like_processes",
        lambda: iter([main_process, comfy_launcher, comfy_worker]),
    )

    result = process_inspector_v2.collect_process_risk_snapshot()

    assert result["status"] == "normal"
    assert result["webui_process_count"] == 0
    assert result["comfy_process_count"] == 2
    assert result["suspicious_processes"] == []
