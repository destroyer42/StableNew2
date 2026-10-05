"""PR-IMG-FORGE-100: the thin canonical-path acceptance driver, proven with mocked HTTP only.

No WebUI, GPU, model or physical generation. The real JobService, SQLite repository, worker bridge,
PipelineRunner.run_njr, backend registry, WebUI-family adapter, executor and runtime admission run; only
the HTTP transport is a fake and host process observations are a deterministic table. The cohort-3
regression lives here: changing where evidence is written must not change application behavior.
"""

from __future__ import annotations

import argparse
import ast
import copy
import json
import os
import shutil
import sys
import time
import uuid
from pathlib import Path

import pytest
import requests

from src.api.client import SDWebUIClient
from src.api.forge_client import ForgeWebUIClient
from src.pipeline.executor import Pipeline
from src.pipeline.global_prompt_policy import has_frozen_global_prompt_policy
from src.pipeline.pipeline_runner import PipelineRunner
from src.queue.job_repository import JobRepository
from src.utils import process_inspector_v2 as inspector
from src.utils.config import ConfigManager
from tests.helpers.fake_webui_transport import FakeWebUITransport
from tools.acceptance import img_forge_100_acceptance as driver

REPO_ROOT = Path(__file__).resolve().parents[2]
DRIVER_SOURCE = REPO_ROOT / "tools" / "acceptance" / "img_forge_100_acceptance.py"
INTENT = json.loads(driver.DEFAULT_INTENT.read_text(encoding="utf-8"))
SETTINGS = INTENT["settings"]
BACKENDS = driver.BACKENDS


def _client(backend: str):
    cls, flavor = (ForgeWebUIClient, "forge") if backend == "forge_webui" else (SDWebUIClient, "a1111")
    transport = FakeWebUITransport(flavor=flavor, checkpoint=SETTINGS["checkpoint"], seed=SETTINGS["seed"])
    client = cls(base_url="http://127.0.0.1:1", options_write_enabled=True)
    client._session.request = transport  # type: ignore[method-assign]
    client._options_min_interval_seconds = 0
    return client, transport


def _process_table(anchor_cwd: str, anchor_cmd: tuple[str, ...]):
    """A harness process plus the manager-owned venv launcher -> serving child, as Windows spawns them."""

    def table():
        now = time.time()
        # Absolute and outside the checkout on every OS (a "C:\..." literal is a repo-relative name on Linux).
        webui_dir = str(Path(anchor_cwd).resolve().parent / "stable-diffusion-webui")
        yield inspector.ProcessInfo(10, 1, "python.exe", anchor_cmd, anchor_cwd, now, 120.0, ())
        yield inspector.ProcessInfo(11, 10, "python.exe", ("python.exe", "launch.py", "--api"), webui_dir, now, 80.0, ())
        yield inspector.ProcessInfo(12, 11, "python.exe", ("python.exe", "launch.py", "--api"), webui_dir, now, 3000.0, ())

    return table


@pytest.fixture
def canonical_context(monkeypatch, tmp_path):
    """The canonical application context: the StableNew checkout is the working directory."""

    monkeypatch.chdir(REPO_ROOT)

    def forbidden(*_a, **_k):
        raise AssertionError("the acceptance driver must never change directory")

    monkeypatch.setattr(os, "chdir", forbidden)
    # Production runtime admission stays real; the host's processes are replaced by a deterministic
    # table in which the harness (cwd = repo) is the StableNew anchor of one launcher/child WebUI tree.
    monkeypatch.setattr(
        inspector, "iter_python_processes",
        _process_table(str(REPO_ROOT), ("python.exe", "-m", "tools.acceptance.img_forge_100_acceptance")),
    )
    # Mutable operator state must never reach frozen intent: hostile runtime globals.
    manager = ConfigManager(
        presets_dir=tmp_path / "presets",
        packs_dir=tmp_path / "packs",
        global_prompt_dir=tmp_path / "global-prompts",
    )
    manager.save_global_positive_state("MUTABLE runtime positive", True)
    manager.save_global_negative_state("MUTABLE runtime negative", True)
    monkeypatch.setattr("src.pipeline.executor.ConfigManager", lambda: manager)
    for target, replacement in (
        (Pipeline, "_apply_webui_defaults_once"),
        (Pipeline, "_maybe_apply_workload_launch_policy"),
        (PipelineRunner, "_start_gpu_survivor_telemetry"),
    ):
        monkeypatch.setattr(target, replacement, lambda *_a, **_k: None)
    monkeypatch.setattr("src.pipeline.executor.collect_gpu_snapshot", lambda: {})
    monkeypatch.setattr("src.api.healthcheck.probe_webui_endpoint", lambda *_a, **_k: "free")
    monkeypatch.setattr("src.video.comfy_healthcheck.probe_comfy_endpoint", lambda *_a, **_k: "free")
    # Readiness/connection probes use their own HTTP path, not the client's session; the canonical queue
    # helper stubs exactly these (tests/helpers/njr_queue_harness.py). Model selection and generation stay real.
    from src.api.webui_api import WebUIAPI

    monkeypatch.setattr(WebUIAPI, "wait_until_true_ready", lambda *_a, **_k: True)
    monkeypatch.setattr("src.api.client.wait_for_webui_ready", lambda *_a, **_k: True)
    monkeypatch.setattr("src.api.client.validate_webui_health", lambda *_a, **_k: True)

    def no_real_http(*_a, **_k):
        raise AssertionError("Real HTTP is forbidden: only the instance fake may answer")

    monkeypatch.setattr(requests.sessions.Session, "request", no_real_http)
    return manager


def _args(backend: str, reports: Path, tag: str, **overrides) -> argparse.Namespace:
    njr = driver.freeze_njr(SETTINGS, backend, job_id="digest-only", output_dir=reports)
    values = {
        "backend": backend, "reports_dir": reports, "intent": driver.DEFAULT_INTENT,
        "approved_intent_sha256": driver.intent_digest(njr), "job_id": f"test-forge100-{backend}-{tag}",
        "timeout_seconds": 60.0, "dry": False, "endpoint": "http://127.0.0.1:1",
    }
    values.update(overrides)
    return argparse.Namespace(**values)


def _drive(backend: str, reports: Path, tag: str):
    client, transport = _client(backend)
    try:
        code = driver.run(_args(backend, reports, tag), driver.InjectedRuntime(), client=client)
    finally:
        client.close()
    return code, transport


def _evidence(reports: Path) -> dict:
    return json.loads((reports / "acceptance.json").read_text(encoding="utf-8"))


def _stored_intent(reports: Path, job_id: str) -> str:
    repository = JobRepository(reports / "state" / "jobs.sqlite3")
    try:
        entry = repository.get_job(job_id)
        from src.pipeline.job_models_v2 import NormalizedJobRecord

        return driver.intent_digest(NormalizedJobRecord.from_dict(entry.snapshot["normalized_job"]))
    finally:
        repository.close()


@pytest.fixture
def repo_local_reports():
    path = REPO_ROOT / "reports" / f"_test_img_forge_100_{uuid.uuid4().hex[:8]}"  # /reports/ is gitignored
    yield path
    shutil.rmtree(path, ignore_errors=True)


# --- The cohort-3 regression: evidence location must not change application behavior -----------------


@pytest.mark.parametrize("backend", BACKENDS)
def test_repo_local_and_external_reports_dirs_produce_identical_execution_intent(
    backend, canonical_context, repo_local_reports, tmp_path
):
    external = tmp_path / "external evidence" / "run"
    outcomes = {}
    for label, reports in (("repo-local", repo_local_reports), ("external", external)):
        code, transport = _drive(backend, reports, label)
        assert code == driver.EXIT_COMPLETED, _evidence(reports)
        evidence = _evidence(reports)
        outcomes[label] = {
            "intent": evidence["intent_sha256"],
            "stored_intent": _stored_intent(reports, evidence["job_id"]),
            "non_generation_traffic": [c for c in transport.calls if c[1] not in ("/sdapi/v1/txt2img",)],
            "generation_payloads": transport.payloads["/sdapi/v1/txt2img"],
            "generation_posts": [p for _, p, _ in transport.generation_calls],
            "backend": evidence["job"]["result_metadata"]["image_backend_id"],
            "cwd": evidence["cwd"],
        }

    assert outcomes["repo-local"] == outcomes["external"]  # byte-for-byte the same application behavior
    assert outcomes["external"]["cwd"] == str(REPO_ROOT)  # evidence elsewhere; the context never moved
    assert outcomes["external"]["stored_intent"] == outcomes["external"]["intent"]  # SQLite froze exactly this
    assert outcomes["external"]["generation_posts"] == ["/sdapi/v1/txt2img"]  # one POST: no retry, no replay
    assert outcomes["external"]["backend"] == backend
    assert Path.cwd() == REPO_ROOT


@pytest.mark.parametrize("backend", BACKENDS)
def test_the_frozen_intent_reaches_the_dispatched_request_byte_for_byte(backend, canonical_context, tmp_path):
    code, transport = _drive(backend, tmp_path / "evidence", "intent")
    assert code == driver.EXIT_COMPLETED
    [payload] = transport.payloads["/sdapi/v1/txt2img"]

    for key, frozen in (("prompt", SETTINGS["prompt"]), ("negative_prompt", SETTINGS["negative_prompt"])):
        assert payload[key] == frozen and payload[key].encode("utf-8") == frozen.encode("utf-8")
    assert "MUTABLE" not in json.dumps(payload)  # mutable global files cannot alter frozen intent
    assert payload["seed"] == SETTINGS["seed"] == 424242
    assert (payload["steps"], payload["cfg_scale"]) == (SETTINGS["steps"], SETTINGS["cfg_scale"])
    assert (payload["sampler_name"], payload["scheduler"]) == (SETTINGS["sampler_name"], SETTINGS["scheduler"])
    assert (payload["width"], payload["height"]) == (SETTINGS["width"], SETTINGS["height"])
    evidence = _evidence(tmp_path / "evidence")
    assert evidence["njr"]["workload"]["backend_options"]["image"]["backend_id"] == backend
    assert evidence["job"]["result_metadata"]["image_backend_id"] == backend


@pytest.mark.parametrize("backend", BACKENDS)
def test_frozen_global_prompt_and_optimizer_intent_is_preserved_in_the_immutable_job(backend, tmp_path):
    njr = driver.freeze_njr(SETTINGS, backend, job_id="x", output_dir=tmp_path)

    assert has_frozen_global_prompt_policy(njr.config)
    assert njr.config["global_prompt_policy_source"] == "frozen_njr"
    assert not any(njr.config["pipeline"][flag] for flag in (
        "apply_global_positive_txt2img", "apply_global_negative_txt2img", "apply_global_negative_img2img",
        "apply_global_negative_adetailer", "apply_global_negative_upscale",
    ))
    assert njr.config["prompt_optimizer"] == {"enabled": False}
    assert njr.seed == 424242
    assert njr.positive_prompt == SETTINGS["prompt"] and njr.negative_prompt == SETTINGS["negative_prompt"]
    with pytest.raises(AttributeError):  # the NJR is immutable
        njr.positive_prompt = "changed"  # type: ignore[misc]


@pytest.mark.parametrize("backend", BACKENDS)
def test_the_converged_freeze_dispatches_the_same_request_as_the_superseded_qualification_njr(
    backend, canonical_context, tmp_path
):
    """Convergence must not move the owner-approved Pair-A intent: same request, byte for byte."""

    from tests.helpers.njr_queue_harness import run_njr_via_queue
    from tools.qualification.img_forge_100 import run as old_run

    matrix = {"settings": SETTINGS, "assets": {"input": {"path": str(tmp_path / "unused")}}}
    case = next(c for c in INTENT["cases"] if c["case_id"] == f"A-{backend}")
    old_njr = old_run.compile_case(matrix, case, tmp_path / "old")
    old_client, old_transport = _client(backend)
    try:
        entry = run_njr_via_queue(old_njr, old_client, artifact_root=tmp_path / "old-run")
        assert entry.status.value == "completed", entry.error_message
    finally:
        old_client.close()
    code, new_transport = _drive(backend, tmp_path / "new", "converged")

    assert code == driver.EXIT_COMPLETED
    assert new_transport.payloads["/sdapi/v1/txt2img"] == old_transport.payloads["/sdapi/v1/txt2img"]
    assert [c for c in new_transport.calls if c[0] == "POST" and c[1] == "/sdapi/v1/options"] == [
        c for c in old_transport.calls if c[0] == "POST" and c[1] == "/sdapi/v1/options"
    ]  # the same option writes (checkpoint/VAE selection) as well


def test_the_intent_digest_ignores_job_identity_and_evidence_location_only(tmp_path):
    one = driver.freeze_njr(SETTINGS, "forge_webui", job_id="job-one", output_dir=tmp_path / "one")
    two = driver.freeze_njr(SETTINGS, "forge_webui", job_id="job-two", output_dir=tmp_path / "two")
    changed = dict(SETTINGS, seed=SETTINGS["seed"] + 1)

    assert driver.intent_digest(one) == driver.intent_digest(two)
    assert driver.intent_digest(driver.freeze_njr(changed, "forge_webui", job_id="job-one", output_dir=tmp_path)) != (
        driver.intent_digest(one)
    )  # a real change of intent changes the digest (so approval cannot silently drift)


def test_a1111_and_forge_requests_differ_only_by_backend_identity(canonical_context, tmp_path):
    payloads = {}
    for backend in BACKENDS:
        code, transport = _drive(backend, tmp_path / backend, "parity")
        assert code == driver.EXIT_COMPLETED
        payloads[backend] = copy.deepcopy(transport.payloads["/sdapi/v1/txt2img"][0])

    assert payloads["a1111_webui"] == payloads["forge_webui"]  # identical translation for both identities
    assert driver.intent_digest(driver.freeze_njr(SETTINGS, "a1111_webui", job_id="a", output_dir=tmp_path)) != (
        driver.intent_digest(driver.freeze_njr(SETTINGS, "forge_webui", job_id="b", output_dir=tmp_path))
    )  # ...yet the frozen intent records which backend was asked for


# --- The driver stays thin: no second authority ----------------------------------------------------------


def _driver_tree() -> ast.Module:
    return ast.parse(DRIVER_SOURCE.read_text(encoding="utf-8"))


def test_the_driver_defines_no_second_compiler_queue_backend_dispatch_or_ownership_gate():
    source = DRIVER_SOURCE.read_text(encoding="utf-8")
    tree = _driver_tree()
    called = {n.func.attr if isinstance(n.func, ast.Attribute) else getattr(n.func, "id", "") for n in ast.walk(tree) if isinstance(n, ast.Call)}

    for forbidden_call in ("chdir", "Popen", "run", "system", "kill", "terminate", "taskkill", "NormalizedJobRecord",
                           "RuntimeTransitionCoordinator", "ImageBackendRegistry", "ForgeWebUIImageBackend",
                           "A1111WebUIImageBackend", "StageConfig", "ImageWorkloadSpec"):
        assert forbidden_call not in called - {"run"}, forbidden_call
    for forbidden_text in ("os.chdir", "subprocess", "taskkill", "requests.sessions", "Session.request", "_config.",
                           "webui_manager_getter", "_ensure_runtime_admissible", "discover_webui_port"):
        assert forbidden_text not in source, forbidden_text
    imported = {a.name for n in ast.walk(tree) if isinstance(n, ast.ImportFrom) for a in n.names}
    assert "compile_case" not in imported and "execute_matrix" not in imported  # not the old parallel shell
    # The lifecycle authority is used, exactly once, inside the runtime wrapper.
    assert source.count("WebUIProcessManager(") == 1


def test_the_driver_stays_a_small_observer_not_an_application_shell():
    # It replaces tools/qualification/img_forge_100/run.py's execute path (231 lines) and the ~420-line
    # external session wrapper; the structural tests above are the real guard, this only stops regrowth.
    # Pair B/C/D freezing (production builders only) and asset verification added ~80 lines.
    assert len(DRIVER_SOURCE.read_text(encoding="utf-8").splitlines()) <= 470


def test_a_physical_run_requires_the_owners_exact_intent_digest(canonical_context, tmp_path):
    client, transport = _client("a1111_webui")
    args = _args("a1111_webui", tmp_path / "ev", "approval", approved_intent_sha256="0" * 64)

    with pytest.raises(PermissionError):
        driver.run(args, driver.InjectedRuntime(), client=client)

    assert transport.calls == []  # nothing was sent, nothing was submitted
    assert not (tmp_path / "ev" / "acceptance.json").exists()


def test_dry_mode_freezes_and_reports_but_starts_and_submits_nothing(canonical_context, tmp_path, capsys):
    code = driver.main(["--backend", "forge_webui", "--dry", "--reports-dir", str(tmp_path / "dry")])

    assert code == driver.EXIT_DRY
    summary = json.loads(capsys.readouterr().out.strip().splitlines()[-1])
    assert summary["dry"] and len(summary["intent_sha256"]) == 64
    assert (tmp_path / "dry" / "intent.json").is_file() and not (tmp_path / "dry" / "state").exists()


def test_evidence_is_never_overwritten(canonical_context, tmp_path):
    reports = tmp_path / "ev"
    assert _drive("a1111_webui", reports, "first")[0] == driver.EXIT_COMPLETED

    with pytest.raises(FileExistsError):
        _drive("a1111_webui", reports, "second")  # a new run needs a new reports dir


def test_a_failed_job_is_reported_failed_without_retry(canonical_context, tmp_path):
    client, transport = _client("forge_webui")
    transport.generation_error = requests.ConnectionError("simulated pre-response failure")
    args = _args("forge_webui", tmp_path / "ev", "failed")
    try:
        code = driver.run(args, driver.InjectedRuntime(), client=client)
    finally:
        client.close()

    assert code == driver.EXIT_FAILED
    assert len(transport.generation_calls) <= 1  # one dispatch at most: the product never replays it
    assert _evidence(tmp_path / "ev")["job"]["status"] == "failed"


def test_the_sources_cwd_assumption_matches_the_inspector():
    # The anchor rule the driver relies on (and the old external shell broke by chdir-ing away).
    assert inspector.REPO_ROOT == REPO_ROOT
    assert sys.version_info >= (3, 11)


# --- Process observation: the cohort-3 cause, proven hermetically and with a real manager-owned tree ------


@pytest.fixture
def live_context(monkeypatch, tmp_path):
    """The canonical context with the REAL process inspector, so a live manager-owned tree is observed."""

    monkeypatch.chdir(REPO_ROOT)
    manager = ConfigManager(
        presets_dir=tmp_path / "presets",
        packs_dir=tmp_path / "packs",
        global_prompt_dir=tmp_path / "global-prompts",
    )
    monkeypatch.setattr("src.pipeline.executor.ConfigManager", lambda: manager)
    for target, replacement in (
        (Pipeline, "_apply_webui_defaults_once"),
        (Pipeline, "_maybe_apply_workload_launch_policy"),
        (PipelineRunner, "_start_gpu_survivor_telemetry"),
    ):
        monkeypatch.setattr(target, replacement, lambda *_a, **_k: None)
    monkeypatch.setattr("src.pipeline.executor.collect_gpu_snapshot", lambda: {})
    monkeypatch.setattr("src.video.comfy_healthcheck.probe_comfy_endpoint", lambda *_a, **_k: "free")
    from src.api.webui_api import WebUIAPI

    monkeypatch.setattr(WebUIAPI, "wait_until_true_ready", lambda *_a, **_k: True)
    monkeypatch.setattr("src.api.client.wait_for_webui_ready", lambda *_a, **_k: True)
    monkeypatch.setattr("src.api.client.validate_webui_health", lambda *_a, **_k: True)


@pytest.fixture
def stand_in_application_lock(monkeypatch):
    """The real singleton lock belongs to a running StableNew; tests substitute an always-held one."""

    class HeldLock:
        def __init__(self, *_a, **_k):
            pass

        def acquire(self):
            return True

        def release(self):
            pass

        @staticmethod
        def is_gui_running(*_a, **_k):
            return True

    monkeypatch.setattr("src.utils.single_instance.SingleInstanceLock", HeldLock)


def test_the_manager_owned_tree_is_observed_when_the_harness_runs_from_the_application_context(monkeypatch):
    anchor = ("python.exe", "-m", "tools.acceptance.img_forge_100_acceptance")
    monkeypatch.setattr(inspector, "iter_python_processes", _process_table(str(REPO_ROOT), anchor))

    risk = inspector.collect_process_risk_snapshot()

    assert (risk["webui_process_count"], risk["webui_runtime_tree_count"], risk["webui_runtime_tree_roots"]) == (2, 1, [11])
    assert risk["status"] == "normal" and risk["stablenew_like_count"] == 3


def test_an_external_evidence_cwd_hides_the_owned_tree_which_is_why_the_driver_never_changes_directory(
    monkeypatch, tmp_path
):
    external = str(tmp_path / "physical-pass-3")  # the old shell's os.chdir(<evidence dir>) running session.py
    monkeypatch.setattr(inspector, "iter_python_processes", _process_table(external, ("python.exe", "session.py", "execute")))

    risk = inspector.collect_process_risk_snapshot()

    assert (risk["stablenew_like_count"], risk["webui_runtime_tree_count"]) == (0, 0)  # an empty observation
    assert risk["status"] == "normal"  # not a duplicate finding: the tree was never anchored to StableNew


def _fake_webui(directory: Path, port: int) -> dict:
    """A throwaway `launch.py` HTTP server that satisfies the production readiness probes."""

    (directory / "launch.py").write_text(
        "import json\n"
        "from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer\n"
        "class H(BaseHTTPRequestHandler):\n"
        "    def do_GET(self):\n"
        "        data = {'progress': 0.0, 'state': {}} if 'progress' in self.path else ([] if 'models' in self.path else {})\n"
        "        body = json.dumps(data).encode()\n"
        "        self.send_response(200)\n"
        "        self.send_header('Content-Type', 'application/json')\n"
        "        self.send_header('Content-Length', str(len(body)))\n"
        "        self.end_headers()\n"
        "        self.wfile.write(body)\n"
        "    def log_message(self, *args):\n"
        "        pass\n"
        f"ThreadingHTTPServer(('127.0.0.1', {port}), H).serve_forever()\n",
        encoding="utf-8",
    )
    return {"command": [sys.executable, "launch.py", "--api"], "working_dir": str(directory),
            "endpoint": f"http://127.0.0.1:{port}", "startup_timeout_seconds": 30}


def _free_port() -> int:
    import socket

    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


windows_only = pytest.mark.skipif(os.name != "nt", reason="the Windows venv launcher -> serving child tree")


def _live_run(tmp_path: Path, reports: Path):
    profile = _fake_webui(tmp_path, _free_port())
    client, transport = _client("a1111_webui")
    runtime = driver.ManagedWebUIRuntime(profile, "a1111_webui")
    try:
        code = driver.run(_args("a1111_webui", reports, "live", endpoint=runtime.endpoint), runtime, client=client)
    finally:
        client.close()
    return code, transport


@windows_only
def test_a_real_manager_owned_tree_is_owned_observed_by_the_inspector_and_released(
    live_context, stand_in_application_lock, tmp_path
):
    from src.api.webui_process_manager import get_global_webui_process_manager

    reports = tmp_path / "evidence"
    code, transport = _live_run(tmp_path, reports)
    evidence = _evidence(reports)

    assert code == driver.EXIT_COMPLETED, evidence
    start = evidence["runtime_start"]
    pids = {p["pid"] for p in start["owned_tree"]}
    assert start["owns_process"] and start["manager"]["runtime_identity"] == "a1111_webui"
    assert start["root_pid"] in pids and start["listening_pids"] and set(start["listening_pids"]) <= pids
    # The production inspector, from the application context, sees exactly one runtime tree rooted at the manager's PID.
    assert start["process_risk"]["webui_runtime_tree_count"] == 1
    assert start["process_risk"]["webui_runtime_tree_roots"] == [start["root_pid"]]
    # Never critical and never a duplicate finding ("warning" can only be this large test process's own RSS).
    assert start["process_risk"]["status"] in {"normal", "warning"}
    assert not [r for s in start["process_risk"]["suspicious_processes"] for r in s["reasons"] if "duplicate" in r]
    assert evidence["cwd"] == str(REPO_ROOT)
    assert [p for _, p, _ in transport.generation_calls] == ["/sdapi/v1/txt2img"]
    assert evidence["job"]["status"] == "completed"
    assert evidence["runtime_stop"] == {"surviving_pids": [], "listening_pids": []}  # the owned tree was released
    assert get_global_webui_process_manager() is None


class _BlindObserverRuntime(driver.InjectedRuntime):
    """A runtime whose manager owns a tree that the production inspector reports as empty."""

    stopped = False

    def start(self):
        return {"owns_process": True, "root_pid": 4242, "process_risk": {"webui_runtime_tree_count": 0, "status": "normal"}}

    def stop(self):
        self.stopped = True
        return super().stop()


def test_a_manager_owned_tree_the_inspector_cannot_see_is_a_production_defect_and_nothing_is_submitted(
    canonical_context, tmp_path
):
    client, transport = _client("a1111_webui")
    runtime = _BlindObserverRuntime()
    try:
        code = driver.run(_args("a1111_webui", tmp_path / "ev", "blind"), runtime, client=client)
    finally:
        client.close()
    evidence = _evidence(tmp_path / "ev")

    assert code == driver.EXIT_NOT_SUBMITTED
    assert evidence["classification"] == "PRODUCTION_PROCESS_OBSERVATION_DEFECT"
    assert transport.calls == [] and "job" not in evidence and not (tmp_path / "ev" / "state").exists()
    assert runtime.stopped  # the runtime is still released through its owner


def test_an_occupied_endpoint_is_refused_and_the_external_listener_is_left_running(
    live_context, stand_in_application_lock, tmp_path
):
    import socket

    with socket.socket() as occupant:
        occupant.bind(("127.0.0.1", 0))
        occupant.listen(16)  # the manager's own occupancy probe must not exhaust the backlog
        port = occupant.getsockname()[1]
        profile = {"command": [sys.executable, "-c", "raise SystemExit(0)"], "working_dir": str(tmp_path),
                   "endpoint": f"http://127.0.0.1:{port}", "startup_timeout_seconds": 5}
        runtime = driver.ManagedWebUIRuntime(profile, "a1111_webui")

        with pytest.raises(Exception, match="already occupied"):
            runtime.start()

        assert runtime.manager is not None and not runtime.manager.owns_process  # never adopted
        with socket.create_connection(("127.0.0.1", port), timeout=1):  # the external listener is untouched
            pass
    runtime.stop()


def test_the_forge_profile_must_use_the_frozen_loopback_port():
    with pytest.raises(ValueError):
        driver.ManagedWebUIRuntime({"endpoint": "http://127.0.0.1:7860", "command": ["x"]}, "forge_webui")
    with pytest.raises(ValueError):
        driver.ManagedWebUIRuntime({"endpoint": "http://example.com:7871", "command": ["x"]}, "forge_webui")
    assert driver.ManagedWebUIRuntime({"endpoint": "http://127.0.0.1:7871", "command": ["x"]}, "forge_webui").endpoint


# --- PR-IMG-FORGE-120: the default-path acceptance driver injects NO backend selection ------------------------------


def _default_driver():
    from tools.acceptance import img_forge_120_default_acceptance as default_driver

    return default_driver


def test_the_default_acceptance_driver_stamps_forge_from_the_default_and_supplies_no_backend_options(monkeypatch):
    import src.utils.config as config_module

    class _Config:
        def load_settings(self):
            return {}

    monkeypatch.setattr(config_module, "ConfigManager", lambda *a, **k: _Config())
    monkeypatch.delenv("STABLENEW_WEBUI_RUNTIME_IDENTITY", raising=False)
    default_driver = _default_driver()
    settings = driver.load_pair_a(driver.DEFAULT_INTENT, "forge_webui")

    njr = default_driver.freeze_default_njr(settings, job_id="default-1", output_dir=Path("out"))

    assert njr.backend_options["image"]["backend_id"] == "forge_webui"  # produced by the production default alone
    source = Path(default_driver.__file__).read_text(encoding="utf-8")
    tree = ast.parse(source)
    keys = {n.value for n in ast.walk(tree) if isinstance(n, ast.Constant) and isinstance(n.value, str)}
    kwargs = {k.arg for n in ast.walk(tree) if isinstance(n, ast.Call) for k in n.keywords}
    assert "runtime_identity" not in kwargs and "backend_options" not in kwargs  # nothing injected into any call
    assert "--backend" not in keys and "--runtime-profile" not in keys  # no selection arguments exist


def test_the_default_acceptance_driver_refuses_an_explicit_identity_or_profile(monkeypatch, tmp_path):
    import src.utils.config as config_module

    default_driver = _default_driver()
    real_manager = config_module.ConfigManager  # the genuine class, captured before it is patched

    def with_settings(stored: dict) -> None:
        presets = tmp_path / f"p{len(list(tmp_path.iterdir()))}"
        presets.mkdir()
        (presets / "settings.json").write_text(json.dumps(stored), encoding="utf-8")
        monkeypatch.setattr(config_module, "ConfigManager", lambda *a, **k: real_manager(presets_dir=presets))

    monkeypatch.delenv("STABLENEW_WEBUI_RUNTIME_IDENTITY", raising=False)
    monkeypatch.delenv("STABLENEW_WEBUI_BASE_URL", raising=False)

    with_settings({"webui_base_url": "http://127.0.0.1:7860"})  # a normal persisted configuration
    evidence = default_driver.effective_configuration()
    assert evidence["effective_identity"] == "forge_webui" and evidence["effective_base_url"] == "http://127.0.0.1:7871"
    assert evidence["stored_has_webui_runtime_identity"] is False

    with_settings({"webui_runtime_identity": "forge_webui"})  # even an explicit Forge would not prove the DEFAULT
    with pytest.raises(PermissionError, match="explicit webui_runtime_identity"):
        default_driver.effective_configuration()
    with_settings({"forge_runtime_profile_path": "C:/x/profile.json"})
    with pytest.raises(PermissionError, match="forge_runtime_profile_path"):
        default_driver.effective_configuration()
    with_settings({"webui_runtime_identity": "a1111_webui"})
    with pytest.raises(PermissionError):
        default_driver.effective_configuration()
