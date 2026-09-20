"""Deterministic (display-free) coverage for the operator-journey harness."""

from __future__ import annotations

import json
import subprocess
import sys
import threading
import time
import urllib.request
from pathlib import Path
from types import SimpleNamespace

import pytest

from tools.operator_journey import cli
from tools.operator_journey.capture import FaultCapture
from tools.operator_journey.evidence import FAIL, HOLD, PASS, JourneyEvidence
from tools.operator_journey.fake_a1111 import FakeA1111
from tools.operator_journey.journeys import learning_lora_strength as journey
from tools.operator_journey.observe import SubmissionObserver, read_job_rows
from tools.operator_journey.owned import OwnedResources, terminate_owned_process
from tools.operator_journey.tk_driver import ActionTrace, JourneyTimeout, TkDriver
from tools.operator_journey.workspace import OperatorWorkspace, UserDataGuard

REPO_ROOT = Path(__file__).resolve().parents[2]


class _FakeRoot:
    """Minimal Tk stand-in so bounded-wait logic is testable without a display."""

    def __init__(self) -> None:
        self.updates = 0

    def update(self) -> None:
        self.updates += 1

    def update_idletasks(self) -> None:
        pass


def test_wait_until_is_bounded_and_reports_evidence() -> None:
    driver = TkDriver(_FakeRoot(), ActionTrace())  # type: ignore[arg-type]
    started = time.monotonic()
    with pytest.raises(JourneyTimeout) as raised:
        driver.wait_until(
            lambda: False,
            timeout=0.2,
            description="never satisfied",
            evidence=lambda: {"jobs": ["running"]},
            poll=0.01,
        )
    assert time.monotonic() - started < 2.0
    message = str(raised.value)
    assert "never satisfied" in message and "running" in message
    assert driver.trace.entries[-1]["action"] == "wait_timeout"


def test_wait_until_returns_value_and_records_trace() -> None:
    driver = TkDriver(_FakeRoot(), ActionTrace())  # type: ignore[arg-type]
    attempts = iter([0, 0, "ready"])
    assert (
        driver.wait_until(lambda: next(attempts), timeout=2, description="soon", poll=0.001)
        == "ready"
    )
    assert driver.trace.entries[-1]["action"] == "wait_satisfied"


def _evidence(*, fail: bool = False, hold: str = "") -> JourneyEvidence:
    evidence = JourneyEvidence(journey_id="unit", backend_mode="fake")
    evidence.repository_sha = "abc123"
    evidence.started_at = evidence.completed_at = "2026-01-01T00:00:00+00:00"
    evidence.summary = {"model": "m", "lora": "l", "requested_seed": 12345}
    evidence.variants = [{"value": '{"weight": 0.0}', "job_id": "j0", "job_status": "completed"}]
    evidence.check("run", "all_jobs_completed", not fail, "job j0 failed")
    evidence.hold_reason = hold
    return evidence


def test_evidence_serialization_is_deterministic_and_verdicts_are_exact() -> None:
    first, second = _evidence(), _evidence()
    assert first.to_json() == second.to_json()
    assert json.loads(first.to_json())["verdict"] == PASS
    failed = _evidence(fail=True)
    assert failed.verdict == FAIL
    assert failed.failed_assertion == "run/all_jobs_completed: job j0 failed"
    assert _evidence(hold="A1111 down").verdict == HOLD
    captured = _evidence()
    captured.gui_errors.append("Traceback\nTclError: boom")
    assert captured.verdict == FAIL and "boom" in captured.failed_assertion


@pytest.mark.parametrize(
    ("kwargs", "exit_code"), [({}, 0), ({"fail": True}, 1), ({"hold": "no A1111"}, 2)]
)
def test_cli_returns_non_zero_for_fail_and_hold(monkeypatch, capsys, kwargs, exit_code) -> None:
    monkeypatch.setattr(cli, "run_journey", lambda _config: _evidence(**kwargs))
    assert cli.main(["learning-lora-strength", "--backend", "fake"]) == exit_code
    assert "learning-lora-strength" not in capsys.readouterr().err  # verdict goes to stdout


def test_cli_real_backend_requires_explicit_flag() -> None:
    parser = cli.build_parser()
    assert cli.config_from_args(parser.parse_args(["learning-lora-strength"])).backend == "fake"
    real = cli.config_from_args(parser.parse_args(["learning-lora-strength", "--real-backend"]))
    assert real.backend == "real" and real.lora_name == "add-detail-xl" and real.seed == 12345
    with pytest.raises(SystemExit):
        parser.parse_args(["learning-lora-strength", "--real-backend", "--backend", "fake"])


def test_workspace_redirects_and_restores_every_mutable_authority(tmp_path: Path) -> None:
    from src.state.workspace_paths import workspace_paths
    from src.utils.config import ConfigManager

    real_root, real_cwd = workspace_paths.root, Path.cwd()
    saved_env = dict(__import__("os").environ)
    workspace = OperatorWorkspace(root=tmp_path / "ws", webui_base_url="http://127.0.0.1:1")
    with workspace.activate():
        assert (
            workspace_paths.job_repository()
            == (tmp_path / "ws" / "state" / "jobs.sqlite3").resolve()
        )
        assert (
            workspace_paths.learning_records(create_parent=False)
            == workspace.records_path.resolve()
        )
        assert Path(ConfigManager().presets_dir).resolve() == workspace.presets_dir.resolve()
        assert Path.cwd().resolve() == (tmp_path / "ws").resolve()
        settings = json.loads((workspace.presets_dir / "settings.json").read_text("utf-8"))
        assert settings["webui_autostart_enabled"] is False
    assert workspace_paths.root == real_root and Path.cwd() == real_cwd
    assert ConfigManager.__init__.__defaults__[0] == "presets"
    assert dict(__import__("os").environ) == saved_env


def test_user_data_guard_detects_protected_data_changes(tmp_path: Path) -> None:
    protected = tmp_path / "state"
    protected.mkdir()
    (protected / "jobs.sqlite3").write_text("original")
    guard = UserDataGuard(repo_root=tmp_path)
    guard.capture()
    assert guard.violations() == []
    (protected / "jobs.sqlite3").write_text("mutated by a journey")
    assert any("state/" in problem for problem in guard.violations())


def test_fault_capture_records_thread_errors_and_restores_hooks() -> None:
    before = (sys.excepthook, threading.excepthook)
    with FaultCapture(None) as faults:
        thread = threading.Thread(target=lambda: 1 / 0, name="journey-bg")
        thread.start()
        thread.join()
    assert any(
        "journey-bg" in error and "ZeroDivisionError" in error for error in faults.thread_errors
    )
    assert (sys.excepthook, threading.excepthook) == before


def test_shutdown_noise_after_close_is_separated_from_run_errors() -> None:
    faults = FaultCapture(None)
    faults._record_tk("real callback failure")
    faults.begin_shutdown()
    faults._record_tk('tcl-bgerror: invalid command name "123_pump"')
    faults._record_tk("another genuine failure during close")
    assert faults.shutdown_noise == ['tcl-bgerror: invalid command name "123_pump"']
    assert faults.tk_errors == ["real callback failure", "another genuine failure during close"]


def test_cleanup_only_stops_journey_owned_resources() -> None:
    stopped: list[str] = []
    owned = OwnedResources()
    owned.register("fake-backend", lambda: stopped.append("fake-backend"))
    unrelated = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"])
    try:
        assert terminate_owned_process(unrelated, owned.owned_pids) is False
        assert owned.cleanup() == ["fake-backend"] and stopped == ["fake-backend"]
        assert unrelated.poll() is None  # never adopted, never killed
        child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"])
        owned.register_process(child)
        assert owned.cleanup() == [f"process:{child.pid}"]
        assert child.poll() is not None
    finally:
        unrelated.kill()
        unrelated.wait(timeout=5)


def test_fake_backend_speaks_the_webui_seam_and_records_generations() -> None:
    with FakeA1111() as fake:
        request = urllib.request.Request(
            f"{fake.base_url}/sdapi/v1/txt2img",
            data=json.dumps({"prompt": "p <lora:x:1.0>", "seed": 12345, "batch_size": 2}).encode(),
            headers={"Content-Type": "application/json"},
        )
        body = json.loads(urllib.request.urlopen(request, timeout=10).read())  # noqa: S310
        info = json.loads(body["info"])
        assert info["all_seeds"] == [12345, 12346] and len(body["images"]) == 2
        assert fake.txt2img_payloads[0]["prompt"] == "p <lora:x:1.0>"
        urllib.request.urlopen(f"{fake.base_url}/sdapi/v1/sd-models", timeout=10).read()  # noqa: S310
        assert fake.unhandled == []


def test_submission_observer_counts_calls_without_changing_them() -> None:
    class Service:
        def submit_njrs(self, records, policy=None):
            return [r.job_id for r in records]

    service = Service()
    observer = SubmissionObserver()
    observer.install(service)
    assert service.submit_njrs([SimpleNamespace(job_id="a"), SimpleNamespace(job_id="b")]) == [
        "a",
        "b",
    ]
    assert observer.calls == [["a", "b"]]
    observer.uninstall()
    assert "submit_njrs" not in service.__dict__


def test_repository_observer_reads_production_lifecycle_read_only(tmp_path: Path) -> None:
    from src.queue.job_queue import JobQueue
    from src.queue.job_repository import JobRepository
    from tests.queue.test_job_repository_sqlite import _job

    path = tmp_path / "jobs.sqlite3"
    repository = JobRepository(path)
    JobQueue(repository=repository).submit(_job("observed"))
    rows = read_job_rows(path, tmp_path)
    repository.close()
    assert [(row["job_id"], row["status"]) for row in rows] == [("observed", "queued")]
    assert rows[0]["retry_attempts"] == 0 and "prompt observed" in rows[0]["njr_positive_prompt"]


def test_journey_only_observes_it_never_initiates_execution() -> None:
    """The driver and journey must not call submission, runner or backend entry points."""

    forbidden = (
        ".run_plan(",
        ".submit_njrs(",
        "run_njr(",
        ".build_plan(",
        "submit_variant",
        "requests.post",
        "urlopen(",
    )
    root = REPO_ROOT / "tools" / "operator_journey"
    for name in ("tk_driver.py", "journeys/learning_lora_strength.py"):
        source = (root / name).read_text(encoding="utf-8")
        code = "\n".join(line for line in source.splitlines() if not line.strip().startswith("#"))
        for token in forbidden:
            assert token not in code, f"{name} must not call {token}"


def test_learning_journey_defaults_match_the_reference_scenario() -> None:
    config = journey.JourneyConfig()
    assert (config.backend, config.lora_name, config.seed) == ("fake", "add-detail-xl", 12345)
    assert journey._STRENGTHS == (0.0, 1.0, 2.0) and journey._RATINGS == (3, 4, 5)
    assert config.run_timeout < JourneyConfigReal().run_timeout


def JourneyConfigReal() -> journey.JourneyConfig:  # noqa: N802 - tiny factory used above
    return journey.JourneyConfig(backend="real")


def test_real_mode_holds_when_a1111_is_unreachable(tmp_path: Path) -> None:
    """No A1111 means HOLD with the exact precondition - never a bypass or a fake result."""

    evidence = journey.run_journey(
        journey.JourneyConfig(
            backend="real", webui_url="http://127.0.0.1:9", evidence_root=tmp_path
        )
    )
    assert evidence.verdict == HOLD
    assert "not reachable at http://127.0.0.1:9" in evidence.hold_reason
    assert not evidence.checks and evidence.failed_assertion.startswith("prerequisite:")
    assert (next(tmp_path.iterdir()) / "evidence.json").is_file()


def test_real_mode_holds_when_the_requested_lora_is_missing(tmp_path: Path) -> None:
    with FakeA1111(loras=("some-other-lora",)) as backend:
        evidence = journey.run_journey(
            journey.JourneyConfig(
                backend="real",
                webui_url=backend.base_url,
                evidence_root=tmp_path,
                lora_name="add-detail-xl",
            )
        )
    assert evidence.verdict == HOLD
    assert "'add-detail-xl' is not installed" in evidence.hold_reason
    assert backend.txt2img_payloads == []  # nothing was generated


def test_backend_probe_reports_models_loras_and_active_checkpoint() -> None:
    from tools.operator_journey.preflight import fetch_progress, probe_backend

    with FakeA1111(model="m1", loras=("a", "b")) as backend:
        info = probe_backend(backend.base_url)
        assert info.reachable and info.models == ["m1"] and info.loras == ["a", "b"]
        assert info.active_checkpoint == backend.title("m1") and info.version
        assert fetch_progress(backend.base_url)["progress"] == 0.0
    assert not probe_backend("http://127.0.0.1:9").reachable


def test_access_spy_flags_production_data_but_allows_the_workspace(tmp_path: Path) -> None:
    import builtins
    import io
    import sqlite3

    from tools.operator_journey.workspace import AccessSpy

    repo, work = tmp_path / "repo", tmp_path / "ws"
    for directory in (repo / "state", repo / "presets", repo / "output", work):
        directory.mkdir(parents=True)
    real = (sqlite3.connect, builtins.open, io.open)
    spy = AccessSpy(repo_root=repo, allowed=(work,))
    with spy:
        sqlite3.connect(str(work / "jobs.sqlite3")).close()  # isolated: fine
        sqlite3.connect(":memory:").close()
        (work / "ok.txt").write_text("workspace write")
        (repo / "output" / "old.png").write_bytes(b"png")  # noqa: SIM115 - writes via open
        sqlite3.connect(str(repo / "state" / "jobs.sqlite3")).close()
        (repo / "presets" / "settings.json").write_text("mutated")
        (repo / "presets" / "settings.json").read_text()
    assert (sqlite3.connect, builtins.open, io.open) == real  # patches restored
    problems = spy.violations()
    assert any("production SQLite database" in p and "jobs.sqlite3" in p for p in problems)
    assert any("wrote production file" in p and "settings.json" in p for p in problems)
    assert any("wrote production file" in p and "old.png" in p for p in problems)
    assert not any(str(work) in p for p in problems)


def test_isolation_is_installed_before_production_authorities_open_paths(tmp_path: Path) -> None:
    """Default-constructed production authorities must resolve inside the workspace."""

    from src.queue.job_repository import JobRepository
    from src.state.workspace_paths import workspace_paths
    from src.utils.config import ConfigManager
    from tools.operator_journey.workspace import REPO_ROOT, AccessSpy

    workspace = OperatorWorkspace(root=tmp_path / "ws", webui_base_url="http://127.0.0.1:1")
    spy = AccessSpy(repo_root=REPO_ROOT, allowed=(workspace.root,))
    with workspace.activate(), spy:
        manager = ConfigManager()  # the constructor every GUI/controller call site uses
        manager.get_global_positive_prompt()
        manager.save_settings({"webui_base_url": "http://127.0.0.1:1"})
        repository = JobRepository(workspace_paths.job_repository())
        repository.close()
        workspace_paths.learning_records().write_text("{}\n", encoding="utf-8")
        workspace_paths.ui_state().parent.mkdir(parents=True, exist_ok=True)
        workspace_paths.ui_state().write_text("{}", encoding="utf-8")
    assert spy.violations() == []
    assert (workspace.root / "state" / "jobs.sqlite3").is_file()
    assert (workspace.presets_dir / "global_positive.txt").is_file()
