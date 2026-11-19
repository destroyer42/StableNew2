"""Deterministic physical-adapter tests: no real runtime, model, network or GPU."""

from __future__ import annotations

import json
import threading
from dataclasses import asdict, dataclass
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from src.api.http_transport import DispatchOutcomeUnknown
from tools.qualification.wan321f import physical as physical
from tools.qualification.wan321f.controls import Sample
from tools.qualification.wan321f.plan import build_graph, frozen_plan


def test_deadline_stops_owned_process_independently_of_polling(tmp_path):
    stopped = threading.Event()
    manager = SimpleNamespace(owns_process=True, stop=lambda **_: stopped.set())
    monitor = physical.Monitor(
        manager, tmp_path, {**frozen_plan()["safety_proposal"], "attempt_seconds": 0.05}
    )
    try:
        monitor.arm()
        assert stopped.wait(2)
        assert monitor.reason == "attempt time limit"
    finally:
        monitor.close()


def test_safety_evidence_disk_failure_cannot_prevent_owned_stop(tmp_path, monkeypatch):
    manager = SimpleNamespace(owns_process=True, stop=Mock())
    monitor = physical.Monitor(manager, tmp_path, frozen_plan()["safety_proposal"])
    monkeypatch.setattr(physical, "write_new_json", Mock(side_effect=OSError("disk full")))
    monitor.abort("safety stop: system commit")
    manager.stop.assert_called_once_with(grace_seconds=0)
    assert "disk full" in monitor.error


def test_freshness_watchdog_stops_while_sampler_is_blocked(tmp_path, monkeypatch):
    stopped, blocked, release = threading.Event(), threading.Event(), threading.Event()
    manager = SimpleNamespace(owns_process=True, stop=lambda **_: stopped.set())
    policy = {
        **frozen_plan()["safety_proposal"],
        "sample_seconds": 0.01,
        "telemetry_gap_seconds": 0.15,
    }
    monitor = physical.Monitor(manager, tmp_path, policy)

    def hung_sample():
        blocked.set()
        release.wait(2)

    monkeypatch.setattr(monitor, "sample_once", hung_sample)
    monitor.thread.start()
    monitor.watchdog.start()
    try:
        assert blocked.wait(1)
        assert stopped.wait(1)
        assert "freshness deadline" in monitor.reason
    finally:
        release.set()
        monitor.close()


def test_external_manager_is_never_stopped_by_watchdog(tmp_path):
    manager = SimpleNamespace(owns_process=False, stop=Mock())
    physical.Monitor(manager, tmp_path, frozen_plan()["safety_proposal"]).abort("missing telemetry")
    manager.stop.assert_not_called()


def test_abort_remains_active_across_child_publication(tmp_path):
    manager = SimpleNamespace(owns_process=False, stop=Mock())
    monitor = physical.Monitor(manager, tmp_path, frozen_plan()["safety_proposal"])
    monitor.abort("missing telemetry")
    manager.stop.assert_not_called()
    manager.owns_process = True
    monitor.abort("missing telemetry")
    manager.stop.assert_called_once_with(grace_seconds=0)


def test_error_history_is_returned_intact_for_evidence():
    history = {
        "status": {
            "status_str": "error",
            "messages": [["execution_error", {"exception_type": "OOM"}]],
        }
    }
    client = SimpleNamespace(get_history=lambda *a, **k: {"p": history})
    assert (
        physical.wait_attempt(client, SimpleNamespace(reason=""), "p", clock=lambda: 0) == history
    )


def test_polling_timeout_is_bounded_without_real_clock():
    clock = iter([0, 1, 301])
    monitor = SimpleNamespace(reason="", abort=Mock())
    client = SimpleNamespace(get_history=lambda *a, **k: {})
    with pytest.raises(RuntimeError, match="time limit"):
        physical.wait_attempt(client, monitor, "p", clock=lambda: next(clock), sleep=lambda _: None)
    monitor.abort.assert_called_once_with("attempt time limit")


def test_schema_mismatch_refuses_before_submission():
    with pytest.raises(RuntimeError, match="Missing stock node"):
        physical.validate_schema({}, build_graph(1))


def test_output_count_and_escape_refusals(tmp_path):
    with pytest.raises(RuntimeError, match="81 PNG"):
        physical.validate_outputs({}, tmp_path)
    images = [{"filename": "../escape.png", "type": "output"}] * 81
    with pytest.raises(RuntimeError, match="Escaped"):
        physical.validate_outputs({"outputs": {"16": {"images": images}}}, tmp_path)


def test_valid_pngs_are_decoded_and_hashed(tmp_path):
    from PIL import Image

    images = []
    for i in range(81):
        name = f"frame_{i:05d}.png"
        Image.new("RGB", (480, 832), (i, 1, 2)).save(tmp_path / name)
        images.append({"filename": name, "type": "output"})
    history = {"outputs": {"16": {"images": images}}}
    result = physical.validate_outputs(history, tmp_path)
    assert result["valid"] and result["count"] == 81
    assert len({f["sha256"] for f in result["frames"]}) == 81
    (tmp_path / images[-1]["filename"]).write_bytes(b"corrupt")
    with pytest.raises(OSError):
        physical.validate_outputs(history, tmp_path)


@pytest.mark.parametrize("failure", [None, "ambiguous", "oom", "startup", "survivor"])
def test_complete_fake_session_exact_once_and_teardown(tmp_path, monkeypatch, failure):
    import hashlib

    root = tmp_path / "evidence"
    root.mkdir()
    source = tmp_path / "source.png"
    source.write_bytes(b"frozen source fixture")
    monkeypatch.setattr(physical, "EVIDENCE_ROOT", str(root))
    monkeypatch.setattr(physical, "INPUT_PATH", str(source))
    monkeypatch.setattr(physical, "INPUT_SHA", hashlib.sha256(source.read_bytes()).hexdigest())
    monkeypatch.setattr(physical, "asset_refusals", lambda: [])
    monkeypatch.setattr(physical, "source_refusals", lambda: [])
    monkeypatch.setattr(physical, "event_log", lambda _: {"events": []})
    monkeypatch.setattr(physical, "validate_outputs", lambda *a: {"valid": True, "count": 81})
    monkeypatch.setattr("sys.argv", ["physical", "--authorize-plan", physical.PLAN_SHA])

    class Manager:
        def __init__(self, *args):
            self.owns_process, self.contained, self.pid, self.stops = False, True, 424242, 0
            managers.append(self)

        def start(self):
            if failure == "startup":
                monitors[0].reason = "missing telemetry during startup"
            self.owns_process = True

        def stop(self, **kwargs):
            self.owns_process = False
            self.stops += 1

        def is_running(self):
            return self.owns_process

        def check_health(self):
            assert failure != "startup", "Aborted startup reached readiness polling"
            return True

    class Client:
        def __init__(self, **kwargs):
            self.posts = []
            clients.append(self)

        def get_system_stats(self, **kwargs):
            return {
                "system": {
                    "comfyui_version": "0.38.0",
                    "pytorch_version": "2.14.0+cu130",
                    "python_version": "3.13.7",
                }
            }

        def get_object_info(self, **kwargs):
            return {
                n["class_type"]: {"input": {"required": {k: ["ANY"] for k in n["inputs"]}}}
                for n in build_graph(1).values()
            }

        def queue_prompt(self, payload):
            self.posts.append(payload)
            if failure == "ambiguous":
                raise DispatchOutcomeUnknown("response lost")
            return {"prompt_id": str(len(self.posts))}

        def get_history(self, pid, **kwargs):
            if failure == "oom":
                return {
                    pid: {
                        "status": {
                            "status_str": "error",
                            "messages": [
                                [
                                    "execution_error",
                                    {
                                        "exception_type": "OutOfMemoryError",
                                        "exception_message": "Allocation on device",
                                    },
                                ]
                            ],
                        }
                    }
                }
            return {pid: {"status": {"completed": True}}}

        def close(self):
            pass

    class Monitor:
        def __init__(self, manager, path, policy, **kwargs):
            self.reason, self.path = "", path
            monitors.append(self)

        def start(self):
            row = {"sample": asdict(Sample(0, 50, 20, 10, 1, 2, 10000, 12282))}
            (self.path / "telemetry.jsonl").write_text(json.dumps(row) + "\n")

        def arm(self):
            pass

        def disarm(self):
            pass

        def close(self):
            pass

    managers, clients, monitors = [], [], []
    monkeypatch.setattr("src.video.comfy_process_manager.ComfyProcessManager", Manager)
    monkeypatch.setattr("src.video.comfy_api_client.ComfyApiClient", Client)
    monkeypatch.setattr(physical, "Monitor", Monitor)

    class Table:
        """The owned launcher exists while its manager owns it; a ``survivor`` child outlives the stop."""

        def running(self):
            return any(m.owns_process for m in managers)

        def exists(self, pid):
            return (pid == 424242 and self.running()) or (pid == 424243 and failure == "survivor")

        def create_time(self, pid):
            return {424242: 1.0, 424243: 2.0}.get(pid)

        def children(self, pid):
            return [424243] if failure == "survivor" else []

        def listening_pids(self, port):
            assert port == 8197
            return []

    monkeypatch.setattr(physical, "process_table", Table)
    monkeypatch.setattr(
        physical, "TEARDOWN_DEADLINE_SECONDS", 0.0
    )  # a survivor ends the wait at once
    assert physical.main() == (1 if failure else 0)
    result = json.loads((root / "physical-001/result.json").read_text())
    assert result["verdict"] == (
        "NO-GO" if failure == "oom" else "INCONCLUSIVE" if failure else "PASS"
    )
    expected_posts = 0 if failure == "startup" else 1 if failure not in (None, "survivor") else 3
    assert len(clients[0].posts) == expected_posts
    assert managers[0].stops == 1
    teardown = json.loads((root / "physical-001/teardown.json").read_text())
    assert teardown["verified"] is (failure != "survivor")
    assert teardown["bounded_wait"]["deadline_seconds"] == 0.0
    assert teardown["bounded_wait"]["observations"][0]["utc"]
    if failure == "survivor":
        assert teardown["surviving_pids"] == [424243] and teardown["observed_children"] == [424243]
    with pytest.raises(FileExistsError):
        physical.main()
    assert len(clients[0].posts) == expected_posts
    if failure == "oom":
        assert (root / "physical-001/attempt-1/history.json").is_file()


def test_qual927_monitor_samples_the_whole_owned_tree_not_the_launcher_stub(tmp_path, monkeypatch):
    """The 321F session measured only the 4.7 MB launcher; the worker beneath it is now counted."""

    from tools.qualification.vid160c import win_memory

    @dataclass(frozen=True)
    class Mem:
        working_set_gb: float
        private_usage_gb: float

    class Table:
        def exists(self, pid):
            return pid in (10, 11, 12)

        def create_time(self, pid):
            return float(pid)

        def children(self, pid):
            assert pid == 10  # only the owned root is ever walked
            return [11, 12]

        def listening_pids(self, port):
            return []

    memory = {10: Mem(0.0044, 0.0009), 11: Mem(8.0, 12.0), 12: Mem(0.5, 0.25)}
    commit = win_memory.SystemCommit(22.5, 56.0, 30.0, 33.5, 40.2, 31.9, 16.0)
    monkeypatch.setattr(win_memory, "read_system_commit", lambda: commit)
    monkeypatch.setattr(
        physical,
        "gpu_sample",
        lambda: {"name": "NVIDIA GeForce RTX 4070 Ti", "total_mib": 12282, "used_mib": 2000.0},
    )
    manager = SimpleNamespace(
        pid=10, owns_process=True, get_stdout_tail=lambda: [], get_stderr_tail=lambda: []
    )
    monitor = physical.Monitor(
        manager, tmp_path, frozen_plan()["safety_proposal"], table=Table(), memory=memory.get
    )
    monitor.sample_once()

    record = json.loads((tmp_path / "telemetry.jsonl").read_text().splitlines()[-1])
    assert record["sample"]["owned_working_set_gib"] == pytest.approx(8.5044)
    assert record["sample"]["owned_private_gib"] == pytest.approx(12.2509)
    assert record["process_tree"]["pids"] == [10, 11, 12]
    assert record["process_tree"]["processes"]["11"] == {
        "working_set_gib": 8.0,
        "private_gib": 12.0,
    }
    assert record["system"]["physical_available_gb"] == 16.0
    assert monitor.children == {11, 12}
    assert [p.pid for p in monitor.tree.recorded] == [10, 11, 12]
    assert monitor.tree.peaks["tree_private_gib"] == pytest.approx(12.2509)


def test_qual927_monitor_fails_closed_when_no_owned_process_can_be_read(tmp_path, monkeypatch):
    from tools.qualification.vid160c import win_memory

    class Table:
        def exists(self, pid):
            return True

        def create_time(self, pid):
            return 1.0

        def children(self, pid):
            return []

        def listening_pids(self, port):
            return []

    commit = win_memory.SystemCommit(22.5, 56.0, 30.0, 33.5, 40.2, 31.9, 16.0)
    monkeypatch.setattr(win_memory, "read_system_commit", lambda: commit)
    monkeypatch.setattr(
        physical,
        "gpu_sample",
        lambda: {"name": "NVIDIA GeForce RTX 4070 Ti", "total_mib": 12282, "used_mib": 2000.0},
    )
    manager = SimpleNamespace(
        pid=10, owns_process=True, get_stdout_tail=lambda: [], get_stderr_tail=lambda: []
    )
    monitor = physical.Monitor(
        manager, tmp_path, frozen_plan()["safety_proposal"], table=Table(), memory=lambda pid: None
    )
    with pytest.raises(RuntimeError, match="memory telemetry unavailable"):
        monitor.sample_once()
