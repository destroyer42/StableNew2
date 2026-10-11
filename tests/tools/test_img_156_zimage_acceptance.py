"""Real canonical queue, SQLite, runner and Forge client with fake transport; no GPU/process/network."""

from __future__ import annotations

import argparse
import base64
import io
import json
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest
import requests
from PIL import Image

import tools.acceptance.img_156_zimage_acceptance as d
from src.api.forge_client import ForgeWebUIClient
from src.image_backends.forge_klein_readiness import HostMemorySnapshot
from src.image_backends.forge_zimage_profile import SAMPLING_OPTIONS
from tests.helpers.fake_webui_transport import FakeResponse, FakeWebUITransport
from tests.tools.test_img_forge_100_acceptance_driver import canonical_context  # noqa: F401
from tools.qualification.img154.evidence import FAULT_SOURCES, FaultSnapshot, FaultSourceSnapshot


class Runtime:
    endpoint = d.ENDPOINT

    def __init__(self, *, owned=True, discrepancy=False):
        self.starts = self.stops = 0
        self.owned, self.discrepancy = owned, discrepancy

    def start(self):
        self.starts += 1
        return {"owns_process": self.owned, "owned_tree": [{"pid": 123}]}

    def stop(self):
        self.stops += 1
        return {"surviving_pids": [123] if self.discrepancy else [], "listening_pids": []}

    def observe(self):
        return {"owned_tree": [], "listening_pids": []}


class Observer:
    def __init__(self, gap=False):
        self.rows = []
        self.gap = gap
        self.phase = "runtime_startup"

    def sample(self, phase):
        fields = ["ram_available_bytes", "commit_headroom_bytes", "vram_used_bytes", "shared_vram_bytes",
                  "gpu_device_present", "forge_tree_private_bytes", "forge_tree_working_set_bytes", "gpu_temperature_c"]
        row = {"mono": float(len(self.rows)), "phase": phase, "values": dict.fromkeys(fields, 10),
               "status": dict.fromkeys(fields, "ok")}
        if phase == "after_cleanup":
            for field in ("forge_tree_private_bytes", "forge_tree_working_set_bytes"):
                row["status"][field], row["values"][field] = "not_applicable", None
        if self.gap and phase != "preflight":
            row["status"]["shared_vram_bytes"] = "missing"
            row["values"]["shared_vram_bytes"] = None
        self.rows.append(row)
        return row

    def start(self):
        self.sample("loading_or_generation")

    def close(self):
        pass


def faults():
    return FaultSnapshot(datetime.now(UTC).isoformat(), "same-boot",
                         {key: FaultSourceSnapshot(key, "complete") for key in FAULT_SOURCES})


class Transport(FakeWebUITransport):
    def __init__(self, *, image="valid", seed=424254, metadata=True, **kwargs):
        super().__init__(flavor="forge", checkpoint=d.P.transformer.filename, seed=seed,
                         modules=[{"model_name": a.filename, "filename": "/data/" + a.filename} for a in d.P.modules], **kwargs)
        self.options.update(SAMPLING_OPTIONS)
        self.image, self.metadata = image, metadata

    def _post(self, path, body):
        response = super()._post(path, body)
        if path != "/sdapi/v1/txt2img" or response.status_code != 200:
            return response
        image = Image.new("RGB", (1024, 1024), "white")
        if self.image == "valid":
            image.putpixel((0, 0), (0, 0, 0))
        buffer = io.BytesIO()
        image.save(buffer, format="PNG")
        info = json.loads(response.json()["info"])
        if self.metadata:
            info["infotexts"] = [f"{d.FrozenIntent().prompt}\nSteps: 9, Sampler: Euler, Schedule type: Beta, CFG scale: 1.0, Shift: 9.0, Seed: {self.seed}, Size: 1024x1024, Model hash: {d.P.transformer.sha256[:10]}, Module 1: qwen3_4b_2964436, Module 2: flux1AE_v10"]
        return FakeResponse({"images": [base64.b64encode(buffer.getvalue()).decode()], "info": json.dumps(info)})


@pytest.fixture(autouse=True)
def isolated(monkeypatch):
    monkeypatch.setattr(d, "source_revision", lambda: {"sha": "a" * 40, "dirty": ""})
    monkeypatch.setattr("src.image_backends.forge_webui_backend.read_host_memory", lambda: HostMemorySnapshot(34_000_000_000, 1, 0))
    monkeypatch.setattr("src.image_backends.forge_webui_backend.verify_zimage_assets", lambda *a, **kw: {
        "forge": {"revision": d.P.forge_revision}, **{a.role: {"sha256": a.sha256} for a in d.P.assets}})


def args(root, dry=True, **kwargs):
    return argparse.Namespace(reports_dir=root, dry=dry, approved_digest="", owner_authorization=None,
                              model_home=root.parent / "models", timeout_seconds=10, **kwargs)


def prepare(tmp_path):
    a = args(tmp_path / "evidence")
    assert d.run(a) == 0
    packet = json.loads((a.reports_dir / "intent.json").read_text())
    a.dry = False
    a.approved_digest = packet["approval_digest"]
    a.owner_authorization = tmp_path / "owner.json"
    now = datetime.now(UTC)
    a.owner_authorization.write_text(json.dumps({"owner": "Rob", "action": d.ACTION,
        "attempt_id": packet["attempt_id"], "approval_digest": a.approved_digest,
        "source_sha": packet["source"]["sha"], "reports_dir": packet["reports_dir"],
        "issued_at": (now - timedelta(seconds=5)).isoformat(), "expires_at": (now + timedelta(minutes=10)).isoformat()}))
    return a


def execute(a, t=None, runtime=None, observer=None, preflight_fn=None, recycle=False, settle_fn=None):
    t = t or Transport()
    client = ForgeWebUIClient(base_url=d.ENDPOINT, options_write_enabled=True)
    client._session.request = t
    client._build_http_session = lambda: SimpleNamespace(request=t, close=lambda: None)
    client._options_min_interval_seconds = 0
    client._sleep = lambda _: None
    if recycle:
        original = t._get
        failed = False
        def get(path):
            nonlocal failed
            if not failed:
                failed = True
                raise requests.ConnectTimeout("synthetic GET forces production session replacement")
            return original(path)
        t._get = get
    runtime = runtime or Runtime()
    code = d.run(a, runtime=runtime, client=client, observer=observer or Observer(),
                 preflight_fn=preflight_fn or (lambda *a: {"synthetic": True}), faults_fn=faults,
                 settle_fn=settle_fn or (lambda _: None))
    report = json.loads((a.reports_dir / "acceptance.json").read_text())
    return code, report, t, runtime


def test_dry_freezes_full_v1_and_never_starts_runtime(tmp_path):
    a = args(tmp_path / "dry")
    runtime = Runtime()
    assert d.run(a, runtime=runtime) == 0
    packet = json.loads((a.reports_dir / "intent.json").read_text())
    njr = packet["njr"]
    assert njr["workload"]["backend_options"]["image"]["model_profile"] == d.P.reference()
    assert njr["provenance"]["seed"] == 424254
    assert len(njr["stages"]) == 1
    assert (njr["workload"]["config"]["steps"], njr["workload"]["config"]["distilled_cfg_scale"]) == (9, 9)
    assert runtime.starts == runtime.stops == 0
    assert {p.name for p in a.reports_dir.iterdir()} == {"intent.json"}


@pytest.mark.parametrize("bad", ["digest", "missing_owner", "expired_owner", "wrong_case", "wrong_profile", "used_root", "dirty_source"])
def test_refuses_before_launch(tmp_path, bad, monkeypatch):
    a = prepare(tmp_path)
    runtime = Runtime()
    if bad == "digest":
        a.approved_digest = "0" * 64
    elif bad == "missing_owner":
        a.owner_authorization = None
    elif bad in {"expired_owner", "wrong_case"}:
        record = json.loads(a.owner_authorization.read_text())
        record["expires_at" if bad == "expired_owner" else "attempt_id"] = "2020-01-01T00:00:00+00:00" if bad == "expired_owner" else "other"
        a.owner_authorization.write_text(json.dumps(record))
    elif bad == "wrong_profile":
        path = a.reports_dir / "intent.json"
        packet = json.loads(path.read_text())
        packet["njr"]["workload"]["backend_options"]["image"]["model_profile"]["version"] = 2
        path.write_text(json.dumps(packet))
    elif bad == "used_root":
        (a.reports_dir / "attempt.json").write_text("consumed")
    else:
        monkeypatch.setattr(d, "source_revision", lambda: {"sha": "a" * 40, "dirty": "modified"})
    with pytest.raises((PermissionError, ValueError)):
        execute(a, runtime=runtime)
    assert runtime.starts == runtime.stops == 0


@pytest.mark.usefixtures("canonical_context")
def test_real_canonical_path_and_result_pass(tmp_path):
    a = prepare(tmp_path)
    code, report, t, runtime = execute(a)
    assert code == 0, report
    assert report["generation"] == "GENERATION_PASS"
    assert report["integration"] == "CANONICAL_PATH_PASS"
    assert report["cleanup"] == "CLEANUP_VERIFIED"
    assert report["resources"]["verdict"] == "OBSERVED_NO_FAULT"
    assert len(t.generation_calls) == runtime.starts == runtime.stops == 1
    assert len(t.generation_calls[0][2]) == 14
    assert (a.reports_dir / "state" / "jobs.sqlite3").is_file()
    assert report["repository_artifact_references"]
    assert report["artifacts"][0]["bytes"] > 0


@pytest.mark.usefixtures("canonical_context")
@pytest.mark.parametrize("changes", [{"image": "constant"}, {"seed": 1}, {"metadata": False}])
def test_invalid_result_cannot_pass(tmp_path, changes):
    code, report, t, _ = execute(prepare(tmp_path), Transport(**changes))
    assert code == 1 and report["generation"] == "GENERATION_FAIL", report
    assert report["validation_errors"] and len(t.generation_calls) == 1


@pytest.mark.usefixtures("canonical_context")
def test_ambiguous_post_never_replayed(tmp_path):
    _, report, t, _ = execute(prepare(tmp_path), Transport(generation_error=requests.ReadTimeout("ambiguous")))
    assert report["generation"] == "GENERATION_AMBIGUOUS", report
    assert len(t.generation_calls) == 1


@pytest.mark.usefixtures("canonical_context")
def test_get_session_replacement_preserves_actual_dispatch_and_fence(tmp_path):
    code, report, t, _ = execute(prepare(tmp_path), recycle=True)
    assert code == 0, report
    assert report["dispatch"]["sent"] and len(t.generation_calls) == 1


@pytest.mark.usefixtures("canonical_context")
def test_connect_timeout_cannot_send_another_post_on_replacement_session(tmp_path):
    _, report, t, _ = execute(prepare(tmp_path), Transport(generation_error=requests.ConnectTimeout("no retry")))
    assert report["generation"] == "GENERATION_AMBIGUOUS", report
    assert report["dispatch"]["blocked_additional"] >= 1
    assert len(t.generation_calls) == 1


@pytest.mark.usefixtures("canonical_context")
def test_post_cleanup_background_samples_are_applicable_to_host_but_not_owned_tree(tmp_path):
    observer = Observer()
    def settled(seconds):
        for _ in range(int(seconds)):
            observer.sample(observer.phase)
    code, report, _, _ = execute(prepare(tmp_path), observer=observer, settle_fn=settled)
    assert code == 0, report
    assert report["resources"]["samples"] >= 120
    assert report["resources"]["verdict"] == "OBSERVED_NO_FAULT"


def test_missing_owned_tree_during_generation_is_still_a_gap():
    observer = Observer()
    row = observer.sample("loading_or_generation")
    row["status"]["forge_tree_private_bytes"] = "not_applicable"
    assert d.resource_result(observer.rows, {"complete": True})["verdict"] == "COVERAGE_INCOMPLETE"


@pytest.mark.usefixtures("canonical_context")
def test_timeout_preserves_uncertainty_and_consumed_root(tmp_path, monkeypatch):
    def timeout(*a):
        raise d.AmbiguousDispatch("bounded wait elapsed")
    monkeypatch.setattr(d, "_await_terminal", timeout)
    a = prepare(tmp_path)
    _, report, t, _ = execute(a)
    assert report["generation"] == "GENERATION_AMBIGUOUS"
    assert len(t.generation_calls) <= 1
    with pytest.raises(PermissionError, match="previously used"):
        execute(a)


@pytest.mark.usefixtures("canonical_context")
def test_generation_pass_is_separate_from_gap_and_immediate_shutdown_failure(tmp_path):
    _, report, _, runtime = execute(prepare(tmp_path), runtime=Runtime(discrepancy=True), observer=Observer(gap=True))
    assert report["generation"] == "GENERATION_PASS", report
    assert report["resources"]["verdict"] == "COVERAGE_INCOMPLETE"
    assert report["cleanup"] == "CLEANUP_FAILED"
    assert report["shutdown_immediate"]["surviving_pids"] == [123]
    assert report["shutdown_settled"]["owned_tree"] == [] and runtime.stops == 1


def test_untrusted_runtime_and_external_ownership_never_used(tmp_path, monkeypatch):
    monkeypatch.setattr(d, "launch_profile", lambda *a: {})
    runtime = Runtime()
    _, report, t, _ = execute(prepare(tmp_path), runtime=runtime, preflight_fn=d.preflight)
    assert "untrusted runtime" in report["error"] and runtime.starts == 0
    assert not t.generation_calls
    a = prepare(tmp_path / "second")
    runtime = Runtime(owned=False)
    _, report, t, _ = execute(a, runtime=runtime)
    assert not t.generation_calls and runtime.stops == 0
    assert report["cleanup"] == "CLEANUP_NOT_VERIFIED"


@pytest.mark.usefixtures("canonical_context")
@pytest.mark.parametrize("cause", ["missing asset", "wrong served hash", "wrong Forge pin"])
def test_production_identity_refusal_before_generation(tmp_path, monkeypatch, cause):
    def refuse(*a, **kw):
        raise ValueError(cause)
    monkeypatch.setattr("src.image_backends.forge_webui_backend.verify_zimage_assets", refuse)
    _, report, t, _ = execute(prepare(tmp_path))
    assert not t.generation_calls and report["generation"] != "GENERATION_PASS"


def test_request_fence_refuses_second_dispatch(tmp_path):
    t = Transport()
    client = ForgeWebUIClient(base_url=d.ENDPOINT, options_write_enabled=True)
    client._session.request = t
    wire = d.RequestEvidence(client, tmp_path)
    wire.request("POST", d.ENDPOINT + "/sdapi/v1/txt2img", json={})
    with pytest.raises(PermissionError, match="second"):
        wire.request("POST", d.ENDPOINT + "/sdapi/v1/txt2img", json={})
    assert len(t.generation_calls) == 1 and wire.blocked == 1


def test_empty_or_incomplete_roots_refuse(tmp_path):
    with pytest.raises(FileExistsError):
        d.run(args(tmp_path))
    with pytest.raises(PermissionError, match="incomplete"):
        d.run(args(tmp_path, dry=False))
