"""PR-VID-190 (part 2): Wan-Animate-2 experimental exposure on the StableNew-managed ComfyUI.

Fakes only: no GPU, model, network or real process.  The qualified-graph parity test also reads the
real PR-VID-184R/S flat graph when it exists on this machine (skipped elsewhere).
"""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from types import SimpleNamespace

import pytest
from PIL import Image

from src.controller.video_workflow_controller import VideoWorkflowController
from src.pipeline.result_contract_v26 import collect_canonical_artifacts
from src.queue.job_model import JobStatus
from src.video import ComfyWorkflowVideoBackend, VideoExecutionRequest
from src.video.video_backend_types import (
    CONTROL_NEGATIVE_PROMPT,
    CONTROL_POSE_VIDEO,
    CONTROL_PROMPT_TEXT,
    CONTROL_SOURCE_IMAGE,
)
from src.video.video_workflow_intent import form_visibility
from src.video.workflow_catalog_wan_animate2 import (
    WAN_ANIMATE2_BASE_NODES,
    WAN_ANIMATE2_DEFAULT_NEGATIVE,
    WAN_ANIMATE2_DRIVE_ID,
    WAN_ANIMATE2_DRIVE_NODES,
    WAN_ANIMATE2_MODEL_FILES,
    WAN_ANIMATE2_PROMPT_ID,
)
from src.video.workflow_compiler import WorkflowCompiler
from src.video.workflow_frame_count import frame_count_projection, legal_frame_counts
from src.video.workflow_readiness import WorkflowResourceReadiness
from src.video.workflow_registry import build_default_workflow_registry
from tests.integration.test_pr_vid_120_neutral_video_queue import _build_stack
from tests.video.test_pr_vid_190_comfy_lifecycle_frame_count import _FakeManager, _no_transition
from tests.video.test_wan22_experimental_workflow import _driver_probe, _FakeComfy, _stats

# Optional machine-local PR-VID-184 evidence; the parity test skips when it is not provided.
QUALIFIED_GRAPH = Path(os.environ.get("STABLENEW_VID184_QUALIFIED_GRAPH", "__unset__"))
MANAGED_COMMAND = ["python.exe", "main.py", "--port", "8000", "--disable-pinned-memory"]


def _spec(workflow_id: str):
    return build_default_workflow_registry().get(workflow_id, "1.0.0", allow_experimental=True)


def _object_info() -> dict:
    loaders = {
        "UNETLoader": "unet_name",
        "CLIPLoader": "clip_name",
        "VAELoader": "vae_name",
        "CLIPVisionLoader": "clip_name",
    }
    info = {node: {"input": {"required": {}}} for node in WAN_ANIMATE2_BASE_NODES}
    info.update({node: {"input": {"required": {}}} for node in WAN_ANIMATE2_DRIVE_NODES})
    for _id, filename, hint, _digest in WAN_ANIMATE2_MODEL_FILES:
        loader = hint.partition(".")[0]
        info[loader] = {"input": {"required": {loaders[loader]: [[filename]]}}}
    return info


class _AnimateComfy(_FakeComfy):
    def __init__(self, tmp: Path, **kw) -> None:
        super().__init__(tmp, info=_object_info(), stats=_stats(free_mib=11000), **kw)
        self.uploaded: list[Path] = []

    def upload_image(self, path, **_kw):
        self.uploaded.append(Path(path))
        return {"name": f"staged_{Path(path).name}", "subfolder": ""}


class _ManagedFake(_FakeManager):
    def __init__(self, *, command=None, **kw) -> None:
        super().__init__(**kw)
        self._config = SimpleNamespace(base_url="http://x", command=list(command or MANAGED_COMMAND))


def _backend(client, manager, *, ram: float = 24.0) -> ComfyWorkflowVideoBackend:
    return ComfyWorkflowVideoBackend(
        client=client,
        process_manager=manager,
        readiness=WorkflowResourceReadiness(
            ram_probe=lambda: ram, gpu_probe=_driver_probe(client.stats)
        ),
        transition=_no_transition(),
        history_timeout=5.0,
        history_poll_interval=0.1,
    )


def _driving_clip(tmp: Path) -> Path:
    clip = tmp / "driving.mp4"
    clip.write_bytes(b"\x00\x00\x00\x18ftypmp42 fake driving clip")
    return clip


def _request(tmp: Path, workflow_id: str, *, frame_count: int = 41, driving: Path | None = None):
    source = tmp / "reference.png"
    source.write_bytes(b"png")
    stage = {
        "workflow_id": workflow_id,
        "workflow_version": "1.0.0",
        "seed": 11,
        "frame_count": frame_count,
        "source_preparation": {"target_dimensions": {"width": 480, "height": 832}},
    }
    controls = [CONTROL_SOURCE_IMAGE, CONTROL_PROMPT_TEXT, CONTROL_NEGATIVE_PROMPT]
    if driving is not None:
        stage["pose_video_path"] = str(driving)
        stage["pose_video_sha256"] = hashlib.sha256(driving.read_bytes()).hexdigest()
        controls.append(CONTROL_POSE_VIDEO)
    return VideoExecutionRequest(
        backend_id="comfy",
        stage_name="video_workflow",
        stage_config=stage,
        output_dir=tmp / f"run-{workflow_id}-{frame_count}",
        input_image_path=source,
        prompt="the woman waves and turns",
        negative_prompt="blurry",
        job_id=f"job-{workflow_id}-{frame_count}",
        workflow_id=workflow_id,
        workflow_version="1.0.0",
        requested_controls=tuple(sorted(controls)),
        experimental_opt_in=True,
    )


# ---------------------------------------------------------------- catalog identity


@pytest.mark.parametrize("workflow_id", [WAN_ANIMATE2_PROMPT_ID, WAN_ANIMATE2_DRIVE_ID])
def test_animate2_specs_are_experimental_comfy_with_the_accepted_model_set(workflow_id) -> None:
    spec = _spec(workflow_id)
    assert spec.is_experimental and spec.backend_id == "comfy"
    files = {d.locator for d in spec.dependency_specs if d.dependency_kind == "model_file"}
    assert files == {
        "wan_animate_2_distill_int8_convrot.safetensors",
        "umt5_xxl_fp8_e4m3fn_scaled.safetensors",
        "Wan2_1_VAE_bf16.safetensors",
        "clip_vision_h.safetensors",
    }
    policy = spec.backend_defaults["runtime_policy"]
    assert policy["release_owned_runtime_after_job"] is True
    assert policy["required_launch_flags"] == ["--disable-pinned-memory"]
    assert spec.backend_defaults["resource_readiness"]["min_available_ram_gb"] == 16.0
    with pytest.raises(KeyError, match="explicit experimental opt-in"):
        build_default_workflow_registry().get(workflow_id, "1.0.0")


def test_graph_keeps_the_qualified_sampling_settings() -> None:
    graph = _spec(WAN_ANIMATE2_DRIVE_ID).backend_defaults["prompt_template"]
    by_class = {node["class_type"]: node["inputs"] for node in graph.values()}
    assert by_class["KSamplerSelect"]["sampler_name"] == "lcm"
    assert by_class["BasicScheduler"] == {
        "model": ["1", 0],
        "scheduler": "simple",
        "steps": 10,
        "denoise": 1.0,
    }
    assert by_class["ModelSamplingSD3"]["shift"] == 5.0
    assert by_class["SamplerCustom"]["cfg"] == 1.0
    assert "WanAnimate2Cache" not in by_class and "ContextWindowsManual" not in by_class
    assert graph["6"]["inputs"]["text"] == "{{input.negative_prompt}}"
    assert _spec(WAN_ANIMATE2_DRIVE_ID).backend_defaults["default_negative_prompt"] == (
        WAN_ANIMATE2_DEFAULT_NEGATIVE
    )


@pytest.mark.skipif(not QUALIFIED_GRAPH.is_file(), reason="set STABLENEW_VID184_QUALIFIED_GRAPH to the PR-VID-184 run5 flat graph")
def test_graph_matches_the_qualified_flat_graph_node_settings() -> None:
    qualified = json.loads(QUALIFIED_GRAPH.read_text(encoding="utf-8"))
    qualified = qualified.get("prompt", qualified)
    assert hashlib.sha256(QUALIFIED_GRAPH.read_bytes()).hexdigest().startswith("9ef8dae4")
    ours = _spec(WAN_ANIMATE2_DRIVE_ID).backend_defaults["prompt_template"]
    q = {node["class_type"]: node["inputs"] for node in qualified.values()}
    o = {node["class_type"]: node["inputs"] for node in ours.values()}
    assert o["UNETLoader"] == q["UNETLoader"]
    assert o["CLIPLoader"] == q["CLIPLoader"]
    assert o["VAELoader"] == q["VAELoader"]
    assert o["CLIPVisionLoader"] == q["CLIPVisionLoader"]
    assert o["KSamplerSelect"] == q["KSamplerSelect"]
    assert qualified["608"]["inputs"]["text"] == WAN_ANIMATE2_DEFAULT_NEGATIVE
    assert o["BasicScheduler"]["scheduler"] == q["BasicScheduler"]["scheduler"]
    for key in ("steps", "denoise"):
        assert float(o["BasicScheduler"][key]) == float(q["BasicScheduler"][key])
    assert float(o["ModelSamplingSD3"]["shift"]) == float(q["ModelSamplingSD3"]["shift"])
    assert float(o["SamplerCustom"]["cfg"]) == float(q["SamplerCustom"]["cfg"])
    for key in ("pose_strength", "pose_start_percent", "pose_end_percent", "reference_image_strength"):
        assert float(o["WanAnimate2ToVideo"][key]) == float(q["WanAnimate2ToVideo"][key])


def test_frame_count_default_is_the_qualified_41_with_a_legal_envelope() -> None:
    for workflow_id in (WAN_ANIMATE2_PROMPT_ID, WAN_ANIMATE2_DRIVE_ID):
        legal = legal_frame_counts(_spec(workflow_id))
        assert legal[0] == 17 and legal[-1] == 81 and all((n - 1) % 4 == 0 for n in legal)
        assert frame_count_projection(_spec(workflow_id))["default"] == 41


# ---------------------------------------------------------------- modes / controls


def test_prompt_mode_takes_no_driving_video_and_hides_the_field() -> None:
    spec = _spec(WAN_ANIMATE2_PROMPT_ID)
    assert CONTROL_POSE_VIDEO not in spec.accepted_controls
    assert "pose_video" not in spec.declared_input_names
    assert form_visibility(spec)["pose_video"] is False


def test_driving_mode_declares_the_neutral_pose_video_control_and_shows_the_field() -> None:
    spec = _spec(WAN_ANIMATE2_DRIVE_ID)
    assert CONTROL_POSE_VIDEO in spec.accepted_controls
    assert "pose_video" in spec.required_input_names
    assert form_visibility(spec)["pose_video"] is True


def test_the_driving_video_field_stays_hidden_for_other_workflows() -> None:
    registry = build_default_workflow_registry()
    ti2v = registry.get("wan22_ti2v_5b_i2v_v1", "1.1.0", allow_experimental=True)
    assert form_visibility(ti2v)["pose_video"] is False


def _capture(tmp_path: Path):
    submitted: list = []
    service = SimpleNamespace(
        submit_njrs=lambda records, _policy: [submitted.extend(records) or "job-x"][0]
    )
    app = SimpleNamespace(job_service=service, output_dir=str(tmp_path / "out"))
    return VideoWorkflowController(app_controller=app), submitted


def _reference(tmp_path: Path) -> Path:
    path = tmp_path / "reference.png"
    Image.new("RGB", (48, 80), "navy").save(path)
    return path


def _form(workflow_id: str, **overrides):
    form = {
        "workflow_id": workflow_id,
        "workflow_version": "1.0.0",
        "prompt": "the woman raises both arms and turns",
        "negative_prompt": "",
        "experimental_opt_in": True,
    }
    form.update(overrides)
    return form


def test_prompt_mode_admits_without_a_driving_video_and_records_none(tmp_path) -> None:
    controller, submitted = _capture(tmp_path)
    controller.submit_video_workflow_job(
        source_image_path=_reference(tmp_path), form_data=_form(WAN_ANIMATE2_PROMPT_ID)
    )
    extra = submitted[0].stage_chain[0].to_dict()["extra"]
    assert "pose_video_path" not in extra and extra["frame_count"] == 41
    assert CONTROL_POSE_VIDEO not in extra["video_execution"]["controls"]
    assert extra["negative_prompt"] == WAN_ANIMATE2_DEFAULT_NEGATIVE


def test_driving_mode_requires_a_driving_video(tmp_path) -> None:
    controller, submitted = _capture(tmp_path)
    ok, reason = controller.validate_form_data(_form(WAN_ANIMATE2_DRIVE_ID))
    assert not ok and "needs a driving video" in reason
    assert submitted == []


def test_supplied_driving_video_is_frozen_with_its_hash_and_never_modified(tmp_path) -> None:
    clip = _driving_clip(tmp_path)
    before = clip.read_bytes()
    controller, submitted = _capture(tmp_path)
    controller.submit_video_workflow_job(
        source_image_path=_reference(tmp_path),
        form_data=_form(WAN_ANIMATE2_DRIVE_ID, pose_video_path=str(clip)),
    )
    extra = submitted[0].stage_chain[0].to_dict()["extra"]
    assert extra["pose_video_path"] == str(clip.resolve())
    assert extra["pose_video_sha256"] == hashlib.sha256(before).hexdigest()
    assert CONTROL_POSE_VIDEO in extra["video_execution"]["controls"]
    assert clip.read_bytes() == before


@pytest.mark.parametrize("name, fragment", [("missing.mp4", "does not exist"), ("clip.txt", "must be a video")])
def test_invalid_driving_video_is_rejected_before_admission(tmp_path, name, fragment) -> None:
    if name.endswith(".txt"):
        (tmp_path / name).write_text("not a video", encoding="utf-8")
    controller, submitted = _capture(tmp_path)
    ok, reason = controller.validate_form_data(
        _form(WAN_ANIMATE2_DRIVE_ID, pose_video_path=str(tmp_path / name))
    )
    assert not ok and fragment in reason and submitted == []


def test_a_driving_video_is_refused_by_the_prompt_only_workflow(tmp_path) -> None:
    controller, _ = _capture(tmp_path)
    ok, reason = controller.validate_form_data(
        _form(WAN_ANIMATE2_PROMPT_ID, pose_video_path=str(_driving_clip(tmp_path)))
    )
    assert not ok and "does not accept the requested pose video" in reason


# ---------------------------------------------------------------- backend: launch policy, staging


def test_missing_pinned_memory_flag_refuses_before_any_runtime_start(tmp_path) -> None:
    manager = _ManagedFake(command=["python.exe", "main.py", "--port", "8000"])
    client = _AnimateComfy(tmp_path)
    with pytest.raises(RuntimeError, match="--disable-pinned-memory"):
        _backend(client, manager).execute(None, _request(tmp_path, WAN_ANIMATE2_PROMPT_ID))
    assert manager.starts == 0 and client.queued == []


def test_an_unverifiable_external_runtime_is_refused(tmp_path, monkeypatch) -> None:
    from src.video import comfy_workflow_backend as backend_module

    monkeypatch.setattr(backend_module, "get_global_comfy_process_manager", lambda: None)
    monkeypatch.setattr(backend_module, "build_default_comfy_process_config", lambda: None)
    client = _AnimateComfy(tmp_path)
    backend = ComfyWorkflowVideoBackend(
        client=client,
        readiness=WorkflowResourceReadiness(ram_probe=lambda: 24.0, gpu_probe=_driver_probe(client.stats)),
        transition=_no_transition(),
    )
    with pytest.raises(RuntimeError, match="cannot be verified"):
        backend.execute(None, _request(tmp_path, WAN_ANIMATE2_PROMPT_ID))
    assert client.queued == [] and client.uploaded == []


def test_prompt_job_runs_releases_the_runtime_and_records_no_driving_video(tmp_path) -> None:
    manager = _ManagedFake()
    client = _AnimateComfy(tmp_path)
    result = _backend(client, manager).execute(None, _request(tmp_path, WAN_ANIMATE2_PROMPT_ID, frame_count=81))
    prompt = client.queued[0]["prompt"]
    assert prompt["10"]["class_type"] == "WanAnimate2ToVideo"
    assert prompt["10"]["inputs"]["length"] == 81
    assert (prompt["10"]["inputs"]["width"], prompt["10"]["inputs"]["height"]) == (480, 832)
    assert "pose_video" not in prompt["10"]["inputs"] and "18" not in prompt
    assert manager.stops == 1 and not manager.running
    manifest = json.loads(Path(result.manifest_path).read_text(encoding="utf-8"))
    assert "pose_video" not in manifest and manifest["frame_count"] == 81


def test_driving_video_is_staged_as_a_copy_and_recorded_in_provenance(tmp_path) -> None:
    clip = _driving_clip(tmp_path)
    before = clip.read_bytes()
    manager = _ManagedFake()
    client = _AnimateComfy(tmp_path)
    result = _backend(client, manager).execute(
        None, _request(tmp_path, WAN_ANIMATE2_DRIVE_ID, driving=clip)
    )
    prompt = client.queued[0]["prompt"]
    assert prompt["18"] == {"class_type": "LoadVideo", "inputs": {"file": "staged_driving.mp4"}}
    assert prompt["10"]["inputs"]["pose_video"] == ["20", 0]
    assert clip in client.uploaded and clip.read_bytes() == before
    manifest = json.loads(Path(result.manifest_path).read_text(encoding="utf-8"))
    assert manifest["pose_video"] == {
        "path": str(clip),
        "sha256": hashlib.sha256(before).hexdigest(),
    }
    assert manager.stops == 1


def test_changed_driving_video_is_refused_before_upload_or_queue(tmp_path) -> None:
    clip = _driving_clip(tmp_path)
    request = _request(tmp_path, WAN_ANIMATE2_DRIVE_ID, driving=clip)
    clip.write_bytes(b"different driving clip")
    manager = _ManagedFake()
    client = _AnimateComfy(tmp_path)

    with pytest.raises(ValueError, match="changed since queue admission"):
        _backend(client, manager).execute(None, request)

    assert client.uploaded == [] and client.queued == []
    assert manager.stops == 1


def test_compiled_driving_graph_binds_the_frozen_length_and_geometry(tmp_path) -> None:
    compiled = WorkflowCompiler().compile(
        _spec(WAN_ANIMATE2_DRIVE_ID),
        _request(tmp_path, WAN_ANIMATE2_DRIVE_ID, frame_count=61, driving=_driving_clip(tmp_path)),
    )
    prompt = compiled.backend_payload["prompt"]
    assert prompt["10"]["inputs"]["length"] == 61
    assert prompt["20"]["inputs"]["resize_type.width"] == 480
    assert prompt["20"]["inputs"]["resize_type.height"] == 832


# ---------------------------------------------------------------- canonical queue, serial jobs


def test_three_queued_animate_jobs_complete_serially_without_manual_teardown(tmp_path) -> None:
    manager = _ManagedFake()
    client = _AnimateComfy(tmp_path)
    repository, queue, service, _ = _build_stack(tmp_path, [_backend(client, manager)])
    app = SimpleNamespace(job_service=service, output_dir=str(tmp_path / "output"))
    controller = VideoWorkflowController(app_controller=app)
    clip = _driving_clip(tmp_path)
    forms = [
        _form(WAN_ANIMATE2_PROMPT_ID, frame_count=41, seed="1"),
        _form(WAN_ANIMATE2_PROMPT_ID, frame_count=81, seed="2"),
        _form(WAN_ANIMATE2_DRIVE_ID, frame_count=41, seed="3", pose_video_path=str(clip)),
    ]
    job_ids = [
        controller.submit_video_workflow_job(source_image_path=_reference(tmp_path), form_data=form)
        for form in forms
    ]
    try:
        for job_id in job_ids:
            service.runner.run_once(queue.get_job(job_id))
        done = [repository.get_job(job_id) for job_id in job_ids]
        assert [job.status for job in done] == [JobStatus.COMPLETED] * 3
        assert manager.starts == 3 and manager.stops == 3 and not manager.running
        assert [p["prompt"]["10"]["inputs"]["length"] for p in client.queued] == [41, 81, 41]
        assert ["18" in p["prompt"] for p in client.queued] == [False, False, True]
        for job in done:
            [artifact] = collect_canonical_artifacts(job.result)
            assert Path(artifact["primary_path"]).is_file()
    finally:
        service.runner.stop()
        repository.close()


def test_long_generations_get_a_declared_history_wait_longer_than_the_default() -> None:
    backend = ComfyWorkflowVideoBackend(history_timeout=120.0)
    registry = build_default_workflow_registry()
    ti2v_v11 = registry.get("wan22_ti2v_5b_i2v_v1", "1.1.0", allow_experimental=True)
    ti2v_v1 = registry.get("wan22_ti2v_5b_i2v_v1", "1.0.0", allow_experimental=True)
    assert backend._history_timeout_for(_spec(WAN_ANIMATE2_PROMPT_ID)) == 1200.0
    assert backend._history_timeout_for(ti2v_v11) == 600.0
    assert backend._history_timeout_for(ti2v_v1) == 120.0  # the qualified revision is unchanged


class _EchoingLoadVideoComfy(_AnimateComfy):
    """Comfy v0.37 reports LoadVideo's source clip as a ``type: input`` preview output."""

    def __init__(self, tmp: Path) -> None:
        super().__init__(tmp)
        self.downloaded: list[str] = []

    def get_history(self, prompt_id=None, **_kw):
        entry = {
            "outputs": {
                "18": {"images": [{"filename": "staged_driving.mp4", "subfolder": "", "type": "input"}]},
                "17": {
                    "images": [
                        {"filename": "wan_animate2_job_00001_.mp4", "subfolder": "stablenew", "type": "output"}
                    ]
                },
            },
            "status": {"status_str": "success", "completed": True},
        }
        return {prompt_id: entry}

    def download_view(self, filename, destination, **kw):
        self.downloaded.append(filename)
        return super().download_view(filename, destination, **kw)


def test_input_previews_are_never_downloaded_or_treated_as_the_artifact(tmp_path) -> None:
    client = _EchoingLoadVideoComfy(tmp_path)
    result = _backend(client, _ManagedFake()).execute(
        None, _request(tmp_path, WAN_ANIMATE2_DRIVE_ID, driving=_driving_clip(tmp_path))
    )
    assert client.downloaded == ["wan_animate2_job_00001_.mp4"]
    assert Path(result.primary_path).name == "wan_animate2_job_00001_.mp4"
    assert [Path(p).name for p in result.raw_result["video_paths"]] == ["wan_animate2_job_00001_.mp4"]
