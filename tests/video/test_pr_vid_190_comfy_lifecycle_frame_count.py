"""PR-VID-190 (part 1): owned-Comfy release after each job, and a neutral frame-count control.

Fakes only: no GPU, model, network or real process.  The fake manager models the one fact the
production defect depends on: while a StableNew-owned Comfy stays resident after a job, the models
it loaded keep host RAM, so the next job's resource readiness fails.
"""

from __future__ import annotations

import ast
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from PIL import Image

from src.controller.video_workflow_controller import VideoWorkflowController
from src.pipeline.result_contract_v26 import collect_canonical_artifacts
from src.queue.job_model import JobStatus
from src.video import ComfyWorkflowVideoBackend, VideoExecutionRequest
from src.video import comfy_process_manager as cpm
from src.video import comfy_workflow_backend as backend_module
from src.video.video_backend_types import (
    CONTROL_NEGATIVE_PROMPT,
    CONTROL_PROMPT_TEXT,
    CONTROL_SOURCE_IMAGE,
)
from src.video.video_workflow_intent import form_visibility
from src.video.workflow_catalog import build_builtin_workflow_specs
from src.video.workflow_compiler import WorkflowCompiler
from src.video.workflow_frame_count import (
    frame_count_projection,
    legal_frame_counts,
    parse_frame_count,
)
from src.video.workflow_readiness import WorkflowResourceReadiness
from src.video.workflow_registry import build_default_workflow_registry
from tests.integration.test_pr_vid_120_neutral_video_queue import _build_stack
from tests.video.test_wan22_experimental_workflow import (
    WAN_ID,
    _driver_probe,
    _FakeComfy,
    _object_info,
    _stats,
)

V1, V11 = "1.0.0", "1.1.0"
QUALIFIED_V1_FINGERPRINT = "2dd94ae24001fe7d71d83f871b9a50059518255ddfb82cd40b4294cea6dfc70b"


def _spec(version: str):
    return build_default_workflow_registry().get(WAN_ID, version, allow_experimental=True)


def _fingerprint(spec) -> str:
    return hashlib.sha256(json.dumps(spec.to_dict(), sort_keys=True).encode()).hexdigest()


class _FakeManager:
    """ComfyProcessManager stand-in: starts/stops a pretend owned process; counts both."""

    def __init__(self, *, owns: bool = True, running: bool = False) -> None:
        self._owns = owns
        self.running = running
        self.starts = 0
        self.stops = 0
        self.jobs_since_start = 0
        self._next_pid = 4100
        self.pid: int | None = 4000 if running else None
        self._config = SimpleNamespace(base_url="http://x")

    @property
    def owns_process(self) -> bool:
        return self._owns and self.running

    def is_running(self) -> bool:
        return self.running

    def ensure_running(self) -> bool:
        if not self.running:
            self.starts += 1
            self.running = True
            self.jobs_since_start = 0
            self._next_pid += 1
            self.pid = self._next_pid
        return True

    def stop(self, **_kw) -> None:
        self.stops += 1
        self.running = False
        self.pid = None


class _ResidentComfy(_FakeComfy):
    """Fake Comfy whose loaded models stay resident in its (owned) process after a job."""

    def __init__(self, tmp: Path, manager: _FakeManager, **kw) -> None:
        super().__init__(tmp, **kw)
        self.manager = manager

    def queue_prompt(self, payload, **_kw):
        self.manager.jobs_since_start += 1
        return super().queue_prompt(payload)


def _resident_ram_readiness(client, manager: _FakeManager, probes: list[float]):
    """16 GB floor: a fresh runtime sees 24 GB free; one that already served a job sees 5 GB,
    exactly the owner's observed failure."""

    def ram() -> float:
        value = 5.0 if manager.jobs_since_start else 24.0
        probes.append(value)
        return value

    return WorkflowResourceReadiness(ram_probe=ram, gpu_probe=_driver_probe(client.stats))


def _no_transition():
    return SimpleNamespace(prepare_for=lambda _target: SimpleNamespace(ready=True))


def _backend(client, manager, *, readiness=None) -> ComfyWorkflowVideoBackend:
    return ComfyWorkflowVideoBackend(
        client=client,
        process_manager=manager,
        readiness=readiness
        or WorkflowResourceReadiness(
            ram_probe=lambda: 24.0, gpu_probe=_driver_probe(client.stats)
        ),
        transition=_no_transition(),
        history_timeout=5.0,
        history_poll_interval=0.1,
    )


def _request(tmp: Path, *, version: str = V11, frame_count=49, job: str = "job-1"):
    source = tmp / "source.png"
    source.write_bytes(b"png")
    stage = {
        "workflow_id": WAN_ID,
        "workflow_version": version,
        "seed": 7,
        "source_preparation": {"target_dimensions": {"width": 480, "height": 832}},
    }
    if frame_count is not None:
        stage["frame_count"] = frame_count
    return VideoExecutionRequest(
        backend_id="comfy",
        stage_name="video_workflow",
        stage_config=stage,
        output_dir=tmp / f"run-{job}",
        input_image_path=source,
        prompt="the person waves",
        negative_prompt="blurry",
        job_id=job,
        workflow_id=WAN_ID,
        workflow_version=version,
        requested_controls=(CONTROL_SOURCE_IMAGE, CONTROL_PROMPT_TEXT, CONTROL_NEGATIVE_PROMPT),
        experimental_opt_in=True,
    )


# ---------------------------------------------------------------- catalog identity / length


def test_qualified_fixed_length_revision_is_byte_identical() -> None:
    assert _fingerprint(_spec(V1)) == QUALIFIED_V1_FINGERPRINT
    assert _spec(V1).backend_defaults["prompt_template"]["8"]["inputs"]["length"] == 49
    assert "runtime_policy" not in _spec(V1).backend_defaults


def test_variable_length_revision_keeps_the_qualified_graph_files_and_readiness() -> None:
    old, new = _spec(V1), _spec(V11)
    assert new.is_experimental and new.backend_id == "comfy"
    assert new.pinned_revision == "catalog:wan22_ti2v_5b_i2v_v1@1.1.0"
    assert [d.to_dict() for d in new.dependency_specs] == [d.to_dict() for d in old.dependency_specs]
    old_graph = json.loads(json.dumps(old.backend_defaults["prompt_template"]))
    new_graph = json.loads(json.dumps(new.backend_defaults["prompt_template"]))
    assert new_graph["8"]["inputs"].pop("length") == "{{input.frame_count}}"
    assert old_graph["8"]["inputs"].pop("length") == 49
    assert new_graph == old_graph
    # The qualification-derived floor is not weakened for the new revision.
    assert new.backend_defaults["resource_readiness"] == old.backend_defaults["resource_readiness"]
    assert new.backend_defaults["runtime_policy"] == {"release_owned_runtime_after_job": True}
    assert new.accepted_controls == old.accepted_controls


def test_legal_lengths_are_4n_plus_1_within_the_declared_envelope() -> None:
    legal = legal_frame_counts(_spec(V11))
    assert legal[0] == 17 and legal[-1] == 81 and 49 in legal
    assert all((count - 1) % 4 == 0 for count in legal)
    projection = frame_count_projection(_spec(V11))
    assert projection["default"] == 49 and projection["fps"] == 24
    assert {"frames": 81, "seconds": 3.4} in projection["choices"]
    assert {"frames": 49, "seconds": 2.0} in projection["choices"]
    assert legal_frame_counts(_spec(V1)) == [] and frame_count_projection(_spec(V1)) is None


@pytest.mark.parametrize("value, expected", [(None, 49), ("", 49), ("81", 81), (61, 61), (17, 17)])
def test_legal_or_empty_frame_count_is_accepted(value, expected) -> None:
    assert parse_frame_count(_spec(V11), value) == expected


@pytest.mark.parametrize("value", ["50", "13", "85", "0", "-3", "abc", "49.0"])
def test_illegal_frame_count_is_rejected_never_rounded(value) -> None:
    with pytest.raises(ValueError):
        parse_frame_count(_spec(V11), value)


def test_frame_count_is_offered_only_by_declaring_workflows() -> None:
    assert form_visibility(_spec(V11))["frame_count"] is True
    assert form_visibility(_spec(V1))["frame_count"] is False
    for spec in build_builtin_workflow_specs():
        declares = "frame_count_policy" in spec.backend_defaults
        assert form_visibility(spec)["frame_count"] is declares, spec.workflow_id
    with pytest.raises(ValueError, match="does not accept a frame count"):
        parse_frame_count(_spec(V1), 49)


def test_compiled_graph_length_is_the_frozen_frame_count(tmp_path: Path) -> None:
    compiled = WorkflowCompiler().compile(_spec(V11), _request(tmp_path, frame_count=81))
    assert compiled.backend_payload["prompt"]["8"]["inputs"]["length"] == 81
    assert compiled.compiled_inputs["frame_count"] == 81


def test_illegal_frozen_length_fails_before_any_runtime_start(tmp_path: Path) -> None:
    manager = _FakeManager()
    client = _FakeComfy(tmp_path)
    with pytest.raises(ValueError, match="cannot generate 50 frames"):
        _backend(client, manager).execute(None, _request(tmp_path, frame_count=50))
    assert manager.starts == 0 and client.queued == []


# ---------------------------------------------------------------- controller admission


def _capture_controller(tmp_path: Path):
    submitted: list = []
    service = SimpleNamespace(
        submit_njrs=lambda records, _policy: [submitted.extend(records) or "job-x"][0]
    )
    app = SimpleNamespace(job_service=service, output_dir=str(tmp_path / "out"))
    return VideoWorkflowController(app_controller=app), submitted


def _form(**overrides):
    form = {
        "workflow_id": WAN_ID,
        "workflow_version": V11,
        "prompt": "the person turns and waves",
        "negative_prompt": "",
        "experimental_opt_in": True,
    }
    form.update(overrides)
    return form


def _source(tmp_path: Path) -> Path:
    path = tmp_path / "source.png"
    Image.new("RGB", (32, 48), "navy").save(path)
    return path


def test_admission_freezes_the_default_length_and_records_duration(tmp_path: Path) -> None:
    controller, submitted = _capture_controller(tmp_path)
    form = _form()
    controller.submit_video_workflow_job(source_image_path=_source(tmp_path), form_data=form)
    [record] = submitted
    extra = record.stage_chain[0].to_dict()["extra"]
    assert extra["frame_count"] == 49 and extra["fps"] == 24
    assert isinstance(extra["seed"], int)  # seed is still frozen at admission
    assert extra["video_execution"]["experimental_opt_in"] is True
    assert form["_stable_new_submission_projection"]["frame_count"] == 49


def test_admission_freezes_a_selected_legal_length(tmp_path: Path) -> None:
    controller, submitted = _capture_controller(tmp_path)
    controller.submit_video_workflow_job(
        source_image_path=_source(tmp_path), form_data=_form(frame_count=81)
    )
    assert submitted[0].stage_chain[0].to_dict()["extra"]["frame_count"] == 81


def test_illegal_length_is_rejected_before_queue_admission(tmp_path: Path) -> None:
    controller, submitted = _capture_controller(tmp_path)
    ok, reason = controller.validate_form_data(_form(frame_count=50))
    assert not ok and "cannot generate 50 frames" in reason
    with pytest.raises(ValueError):
        controller.submit_video_workflow_job(
            source_image_path=_source(tmp_path), form_data=_form(frame_count=84)
        )
    assert submitted == []


def test_experimental_opt_in_is_still_required_per_job(tmp_path: Path) -> None:
    controller, submitted = _capture_controller(tmp_path)
    ok, reason = controller.validate_form_data(_form(experimental_opt_in=False))
    assert not ok and "experimental" in reason
    assert controller.build_default_form_state()["experimental_opt_in"] is False
    assert submitted == []


def test_only_the_newest_revision_is_offered_and_the_old_one_still_resolves(tmp_path) -> None:
    controller, _ = _capture_controller(tmp_path)
    [offered] = [s for s in controller.list_workflow_specs() if s["workflow_id"] == WAN_ID]
    assert offered["workflow_version"] == V11
    assert offered["frame_count"]["default"] == 49
    ok, reason = controller.validate_form_data(_form(workflow_version=V1))
    assert ok, reason  # existing 1.0.0 jobs can still be validated and replayed exactly


def test_video_workflow_controller_acquires_no_process_lifecycle() -> None:
    source = Path("src/controller/video_workflow_controller.py").read_text(encoding="utf-8")
    names = {
        node.id if isinstance(node, ast.Name) else node.attr
        for node in ast.walk(ast.parse(source))
        if isinstance(node, (ast.Name, ast.Attribute))
    }
    assert not names & {"ComfyProcessManager", "stop", "terminate", "kill", "ensure_running"}


# ---------------------------------------------------------------- lifecycle release


def test_owned_runtime_is_released_after_a_successful_job(tmp_path: Path) -> None:
    manager = _FakeManager()
    client = _FakeComfy(tmp_path)
    result = _backend(client, manager).execute(None, _request(tmp_path))
    assert manager.starts == 1 and manager.stops == 1 and not manager.running
    release = result.diagnostic_payload["runtime_release"]
    assert release["ownership"] == "owned" and release["released"] is True
    assert release["pid"] == 4101
    assert result.backend_metadata["frame_count"] == 49 and result.backend_metadata["fps"] == 24
    manifest = json.loads(Path(result.manifest_path).read_text(encoding="utf-8"))
    assert manifest["frame_count"] == 49 and manifest["fps"] == 24
    assert manifest["approximate_seconds"] == 2.0
    assert manifest["runtime_policy"] == {"release_owned_runtime_after_job": True}


def _missing_node_client(tmp):
    return _FakeComfy(tmp, info=_object_info(missing_node="Wan22ImageToVideoLatent"))


def _low_vram_client(tmp):
    return _FakeComfy(tmp, stats=_stats(free_mib=4000))


class _NoOutputComfy(_FakeComfy):
    def get_history(self, prompt_id=None, **_kw):
        return {prompt_id: {"outputs": {"12": {"images": []}}, "status": {"completed": True}}}


@pytest.mark.parametrize(
    "make_client, error",
    [
        (_missing_node_client, "missing required Comfy dependencies"),
        (_low_vram_client, "not resource-ready"),
        (lambda tmp: _NoOutputComfy(tmp), "without discoverable output artifacts"),
    ],
    ids=["dependency_after_start", "readiness_after_start", "output_failure"],
)
def test_owned_runtime_is_released_after_a_failure_once_started(
    tmp_path: Path, make_client, error
) -> None:
    manager = _FakeManager()
    with pytest.raises(RuntimeError, match=error):
        _backend(make_client(tmp_path), manager).execute(None, _request(tmp_path))
    assert manager.starts == 1 and manager.stops == 1 and not manager.running


def test_interruption_releases_the_owned_runtime_and_propagates(tmp_path: Path) -> None:
    class _Interrupted(_FakeComfy):
        def queue_prompt(self, payload, **_kw):
            raise KeyboardInterrupt

    manager = _FakeManager()
    with pytest.raises(KeyboardInterrupt):
        _backend(_Interrupted(tmp_path), manager).execute(None, _request(tmp_path))
    assert manager.stops == 1 and not manager.running


def test_an_unowned_running_runtime_is_never_stopped(tmp_path: Path) -> None:
    manager = _FakeManager(owns=False, running=True)
    result = _backend(_FakeComfy(tmp_path), manager).execute(None, _request(tmp_path))
    assert manager.stops == 0 and manager.running
    assert result.diagnostic_payload["runtime_release"]["ownership"] == "not_owned"


def test_an_external_endpoint_without_a_manager_is_never_stopped(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(backend_module, "get_global_comfy_process_manager", lambda: None)
    monkeypatch.setattr(backend_module, "wait_for_comfy_ready", lambda *_a, **_k: True)
    client = _FakeComfy(tmp_path)
    backend = ComfyWorkflowVideoBackend(
        client=client,
        readiness=WorkflowResourceReadiness(
            ram_probe=lambda: 24.0, gpu_probe=_driver_probe(client.stats)
        ),
        transition=_no_transition(),
    )
    result = backend.execute(None, _request(tmp_path))
    assert result.diagnostic_payload["runtime_release"] == {
        "policy": "release_owned_runtime_after_job",
        "ownership": "none",
        "released": False,
    }


def test_a_workflow_without_the_policy_keeps_its_runtime_resident(tmp_path: Path) -> None:
    manager = _FakeManager()
    result = _backend(_FakeComfy(tmp_path), manager).execute(
        None, _request(tmp_path, version=V1, frame_count=None)
    )
    assert manager.starts == 1 and manager.stops == 0 and manager.running
    assert "runtime_release" not in result.diagnostic_payload


def test_the_next_job_relaunches_a_fresh_managed_runtime(tmp_path: Path) -> None:
    manager = _FakeManager()
    backend = _backend(_FakeComfy(tmp_path), manager)
    pids = []
    for job in ("a", "b"):
        result = backend.execute(None, _request(tmp_path, job=job))
        pids.append(result.diagnostic_payload["runtime_release"]["pid"])
    assert manager.starts == 2 and manager.stops == 2 and pids == [4101, 4102]


def test_the_backend_reuses_one_owner_object_after_the_global_is_cleared(
    tmp_path: Path, monkeypatch
) -> None:
    manager = _FakeManager()
    handed_out = iter([manager])  # the global owner is visible once, then cleared by stop()
    monkeypatch.setattr(
        backend_module, "get_global_comfy_process_manager", lambda: next(handed_out, None)
    )
    client = _FakeComfy(tmp_path)
    backend = ComfyWorkflowVideoBackend(
        client=client,
        readiness=WorkflowResourceReadiness(
            ram_probe=lambda: 24.0, gpu_probe=_driver_probe(client.stats)
        ),
        transition=_no_transition(),
    )
    backend.execute(None, _request(tmp_path, job="a"))
    backend.execute(None, _request(tmp_path, job="b"))
    # Same object relaunched: app-exit cleanup and runtime transitions keep tracking it.
    assert manager.starts == 2 and manager.stops == 2


def test_relaunch_after_stop_reregisters_the_global_owner(monkeypatch) -> None:
    class _Proc:
        pid = 55

        def __init__(self, *_a, **_k) -> None:
            self.stdout = self.stderr = None
            self.alive = True

        def poll(self):
            return None if self.alive else 0

        def terminate(self) -> None:
            self.alive = False

        def wait(self, timeout=None) -> int:
            return 0

    monkeypatch.setattr(cpm.subprocess, "Popen", _Proc)
    monkeypatch.setattr(cpm, "probe_comfy_endpoint", lambda *_a, **_k: "free")
    manager = cpm.ComfyProcessManager(
        cpm.ComfyProcessConfig(command=["comfy"], base_url="http://127.0.0.1:1")
    )
    try:
        manager.start()
        manager.stop()
        assert cpm.get_global_comfy_process_manager() is None
        manager.start()
        assert cpm.get_global_comfy_process_manager() is manager and manager.owns_process
    finally:
        manager.stop()
        cpm.clear_global_comfy_process_manager()


# ---------------------------------------------------------------- canonical queue, serial jobs


def _queue_three_jobs(tmp_path: Path, version: str):
    manager = _FakeManager()
    probes: list[float] = []
    client = _ResidentComfy(tmp_path, manager)
    backend = _backend(client, manager, readiness=_resident_ram_readiness(client, manager, probes))
    repository, queue, service, _controller = _build_stack(tmp_path, [backend])
    app = SimpleNamespace(job_service=service, output_dir=str(tmp_path / "output"))
    controller = VideoWorkflowController(app_controller=app)
    job_ids = []
    for index, frames in enumerate((49, 81, 49)):
        form = _form(workflow_version=version, seed=str(100 + index))
        if version == V11:
            form["frame_count"] = frames
        job_ids.append(
            controller.submit_video_workflow_job(
                source_image_path=_source(tmp_path), form_data=form
            )
        )
    for job_id in job_ids:
        service.runner.run_once(queue.get_job(job_id))
    return repository, service, manager, client, probes, job_ids


def test_three_queued_jobs_complete_serially_without_manual_teardown(tmp_path: Path) -> None:
    repository, service, manager, client, probes, job_ids = _queue_three_jobs(tmp_path, V11)
    try:
        done = [repository.get_job(job_id) for job_id in job_ids]
        assert [job.status for job in done] == [JobStatus.COMPLETED] * 3
        assert manager.starts == 3 and manager.stops == 3 and not manager.running
        assert probes == [24.0, 24.0, 24.0]  # readiness evaluated per job, on a fresh runtime
        assert [p["prompt"]["8"]["inputs"]["length"] for p in client.queued] == [49, 81, 49]
        for job in done:
            [artifact] = collect_canonical_artifacts(job.result)
            assert Path(artifact["primary_path"]).is_file()
        assert len(set(job_ids)) == 3
    finally:
        service.runner.stop()
        repository.close()


def test_without_the_policy_the_second_job_fails_readiness_against_a_resident_runtime(
    tmp_path: Path,
) -> None:
    """The owner's observed defect, reproduced with the unchanged 1.0.0 revision."""

    repository, service, manager, client, probes, job_ids = _queue_three_jobs(tmp_path, V1)
    try:
        statuses = [repository.get_job(job_id).status for job_id in job_ids]
        assert statuses == [JobStatus.COMPLETED, JobStatus.FAILED, JobStatus.FAILED]
        assert "5.0 GB of system RAM" in str(repository.get_job(job_ids[1]).error_message)
        assert manager.stops == 0 and len(client.queued) == 1
    finally:
        service.runner.stop()
        repository.close()
