"""Fun Control contract: offline only, with disposable inputs and fake runtime evidence."""

import copy
import hashlib
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import pytest

from src.controller.job_service import JobService
from src.gui.view_contracts.video_batch_contract import build_preview_view
from src.video.comfy_api_client import ComfyApiClient
from src.video.comfy_dependency_probe import ComfyDependencyProbe
from src.video.comfy_workflow_backend import ComfyWorkflowVideoBackend
from src.video.driving_frame_consumption import driving_frame_consumption
from src.video.motion_source_plan import motion_source_contract
from src.video.motion_source_preparation import MotionSourceRequest, prepare_motion_source
from src.video.motion_source_readiness import assess_motion_source, requested_output_timing
from src.video.video_backend_types import VideoExecutionRequest
from src.video.video_workflow_intent import capability_errors, form_visibility
from src.video.workflow_admission import require_workflow_admission
from src.video.workflow_asset_integrity import model_folders, verify_assets
from src.video.workflow_catalog_fun_control import FUN_ASSETS, FUN_MODEL, FUN_REVISION
from src.video.workflow_compiler import WorkflowCompiler
from src.video.workflow_frame_count import parse_frame_count
from src.video.workflow_input_integrity import verify_exact_dispatch_inputs, verify_exact_motion
from src.video.workflow_motion_guidance import motion_readiness_projection
from src.video.workflow_preflight import PreflightProbes, evaluate_workflow_preflight
from src.video.workflow_readiness import WorkflowResourceReadiness
from src.video.workflow_registry import WorkflowLookupError, build_default_workflow_registry
from tests.video.test_pr_vid_196_readiness_and_guidance import _facts
from tests.video.test_pr_vid_motion_210_admission import _inputs, _record, _stack
from tests.video.test_pr_vid_motion_210_preparation import _clip, _digests, needs_ffmpeg

FUN_ID = "wan22_fun_control_5b_canny_i2v_v1"


def _spec():
    return build_default_workflow_registry().get(FUN_ID, "1.0.0", allow_experimental=True)


def _form(clip, record):
    return {
        "workflow_id": FUN_ID,
        "workflow_version": "1.0.0",
        "prompt": "walk forward",
        "seed": "424242",
        "frame_count": "17",
        "pose_video_path": str(clip),
        "experimental_opt_in": True,
        "prepared_motion_source": record,
    }


def _prepared(tmp_path):
    source, clip = _inputs(tmp_path)
    record = _record(tmp_path, clip, frames=17, version="1.0.0", workflow_id=FUN_ID)
    record["derived"].update(frame_rate="24/1", frames_md5_sha256="a" * 64)
    record["contract"] = motion_source_contract(_spec(), 17).to_record()
    return source, clip, record


def _built(tmp_path):
    source, clip, record = _prepared(tmp_path)
    controller, _service = _stack(tmp_path)
    form = _form(clip, record)
    builder = controller._njr_builder
    frozen = builder.freeze_inputs(source, form)
    return builder.build_job(form, frozen).njr, controller, form


def _request(njr):
    stage = copy.deepcopy(njr.config["video_workflow"])
    return VideoExecutionRequest(
        backend_id="comfy",
        stage_name="video_workflow",
        stage_config=stage,
        output_dir=Path(njr.input_image_paths[0]).parent,
        input_image_path=Path(njr.input_image_paths[0]),
        prompt=stage["prompt"],
        negative_prompt=stage["negative_prompt"],
        workflow_id=FUN_ID,
        workflow_version="1.0.0",
        experimental_opt_in=True,
        job_id=njr.job_id,
    )


def test_fun_is_a_separate_experimental_version():
    registry = build_default_workflow_registry()
    spec = registry.get(FUN_ID, "1.0.0", allow_experimental=True)
    assert spec.is_experimental
    with pytest.raises(WorkflowLookupError, match="experimental"):
        registry.get(FUN_ID, "1.0.0")


def test_pinned_assets_reuse_existing_encoder_and_vae_bytes():
    spec = _spec()
    base = build_default_workflow_registry().get("wan22_ti2v_5b_i2v_v1", "1.3.0")
    assert spec.backend_defaults["asset_integrity"]["revision"] == FUN_REVISION
    assert FUN_ASSETS[FUN_MODEL] == {
        "folder": "diffusion_models",
        "size": 10003303280,
        "sha256": "ace4718a7c87ee3e5606a68ab79142c4395e81aece76b8120bc886f0fbbe1d16",
    }
    for name in set(FUN_ASSETS) - {FUN_MODEL}:
        assert FUN_ASSETS[name]["sha256"] == base.backend_defaults["provenance"]["files"][name]


@pytest.mark.parametrize("length", [17, 21, 25, 29, 33, 37, 41, 45, 49])
def test_product_frame_envelope(length):
    assert parse_frame_count(_spec(), length) == length


@pytest.mark.parametrize("length", [0, 16, 18, 48, 50, 53, 81, True])
def test_illegal_frame_count_is_not_rounded(length):
    with pytest.raises(ValueError):
        parse_frame_count(_spec(), length)


def test_real_compiler_binds_appearance_canny_motion_and_frames_out(tmp_path):
    njr, _controller, _form_data = _built(tmp_path)
    request = _request(njr)
    compiled = WorkflowCompiler().compile(_spec(), request)
    graph = compiled.backend_payload["prompt"]
    assert graph["1"]["inputs"]["unet_name"] == FUN_MODEL
    assert graph["7"]["inputs"]["image"] == str(request.input_image_path)
    assert graph["12"] == {
        "class_type": "LoadVideo",
        "inputs": {"file": request.stage_config["pose_video_path"]},
    }
    assert graph["13"]["inputs"]["video"] == ["12", 0]
    assert graph["14"]["inputs"] == {
        "image": ["13", 0],
        "low_threshold": 0.1,
        "high_threshold": 0.6,
    }
    assert graph["8"]["inputs"] == {
        "positive": ["5", 0],
        "negative": ["6", 0],
        "vae": ["3", 0],
        "width": 480,
        "height": 832,
        "length": 17,
        "batch_size": 1,
        "ref_image": ["7", 0],
        "control_video": ["14", 0],
    }
    assert graph["9"]["inputs"] == {
        "model": ["4", 0],
        "seed": 424242,
        "steps": 20,
        "cfg": 5.0,
        "sampler_name": "uni_pc",
        "scheduler": "simple",
        "positive": ["8", 0],
        "negative": ["8", 1],
        "latent_image": ["8", 2],
        "denoise": 1.0,
    }
    assert graph["5"]["inputs"]["text"] == "walk forward"
    assert graph["6"]["inputs"]["text"] == request.negative_prompt
    assert graph["11"]["class_type"] == "SaveImage"
    assert _spec().backend_defaults["output_policy"] == {"mode": "frames", "fps": 24}
    verify_exact_dispatch_inputs(_spec(), request)


@pytest.mark.parametrize(
    "missing", ["Canny", "LoadVideo", "GetVideoComponents", "Wan22FunControlToVideo", "SaveImage"]
)
def test_missing_stock_node_is_reported(missing):
    spec = _spec()
    info = {
        d.locator: {}
        for d in spec.dependency_specs
        if d.dependency_kind == "stock_node" and d.locator != missing
    }
    result = ComfyDependencyProbe().probe_workflow(spec, object_info=info)
    assert not result.ready
    assert any(result.details[key]["locator"] == missing for key in result.missing_required)


@pytest.mark.parametrize("mutation", ["slot", "threshold", "binding", "runtime", "node"])
def test_frame_consumption_recognition_fails_closed(mutation):
    spec = _spec()
    assert driving_frame_consumption(spec).verified
    defaults = copy.deepcopy(spec.backend_defaults)
    graph = defaults["prompt_template"]
    if mutation == "slot":
        graph["14"]["inputs"]["image"][1] = 1
    elif mutation == "threshold":
        graph["14"]["inputs"]["low_threshold"] = 0.4
    elif mutation == "binding":
        graph["12"]["inputs"]["file"] = "other.mp4"
    elif mutation == "runtime":
        defaults["provenance"]["comfyui_revision"] = "unknown"
    else:
        graph["13"]["class_type"] = "CustomVideoLoader"
    assert not driving_frame_consumption(replace(spec, backend_defaults=defaults)).verified


@pytest.mark.parametrize(
    "mutation,reason",
    [
        ("frames", "inconsistent"),
        ("fps", "24 FPS"),
        ("frame_digest", "ordered-frame identity"),
        ("runtime", "runtime identity"),
        ("lossless", "lossless"),
        ("derived_bytes", "changed since"),
        ("original_bytes", "changed since"),
    ],
)
def test_prepared_source_must_match_accepted_record(tmp_path, mutation, reason):
    _source, clip, record = _prepared(tmp_path)
    if mutation == "frames":
        record["derived"]["frames"] = 16
    elif mutation == "fps":
        record["derived"]["frame_rate"] = "30/1"
    elif mutation == "frame_digest":
        record["derived"].pop("frames_md5_sha256")
    elif mutation == "runtime":
        record["contract"]["runtime_revision"] = "other"
    elif mutation == "lossless":
        record["processing"]["lossless"] = False
    elif mutation == "derived_bytes":
        Path(record["derived"]["path"]).write_bytes(b"replaced")
    else:
        clip.write_bytes(b"replaced")
    with pytest.raises(ValueError, match=reason):
        verify_exact_motion(_spec(), record, frame_count=17, original_path=str(clip))


def test_preparation_and_concrete_seed_are_required_before_preview(tmp_path):
    source, clip, record = _prepared(tmp_path)
    controller, _ = _stack(tmp_path)
    form = _form(clip, None)
    with pytest.raises(ValueError, match="Prepare Motion Source"):
        controller._njr_builder.freeze_inputs(source, form)
    form = _form(clip, record)
    form["seed"] = "Random"
    assert controller.validate_form_data(form) == (
        False,
        "Choose a concrete seed before Preview for this controlled-motion workflow.",
    )


@pytest.mark.parametrize(
    "changed", ["prepared_reference", "original_reference", "driving", "graph", "fps", "geometry"]
)
def test_frozen_inputs_are_reverified_before_dispatch(tmp_path, changed):
    njr, _controller, _form_data = _built(tmp_path)
    request = _request(njr)
    stage = request.stage_config
    if changed == "prepared_reference":
        request.input_image_path.write_bytes(b"replaced")
    elif changed == "original_reference":
        Path(stage["reference_identity"]["original_path"]).write_bytes(b"replaced")
    elif changed == "driving":
        Path(stage["pose_video_path"]).write_bytes(b"replaced")
    elif changed == "graph":
        stage["workflow_identity"]["graph_sha256"] = "bad"
    elif changed == "fps":
        stage["fps"] = 30
    else:
        stage["source_preparation"]["target_dimensions"]["width"] = 704
    with pytest.raises(ValueError):
        verify_exact_dispatch_inputs(_spec(), request)


def test_unqualified_hardware_never_passes_even_with_abundant_memory():
    readiness = WorkflowResourceReadiness(
        ram_probe=lambda: 1000, gpu_probe=lambda _: (100000, 100000)
    )
    result = readiness.evaluate(_spec(), system_stats={})
    assert not result.ready and "NOT QUALIFIED" in result.message


def test_canonical_admission_refuses_before_any_queue_mutation(tmp_path):
    njr, _controller, _form_data = _built(tmp_path)
    with pytest.raises(ValueError, match="NOT QUALIFIED"):
        JobService.__new__(JobService).submit_njrs([njr])
    with pytest.raises(ValueError, match="NOT QUALIFIED"):
        require_workflow_admission(njr)


@pytest.mark.parametrize("case", ["whitespace_unknown", "neutral_precedence", "missing_opt_in"])
def test_admission_uses_the_same_effective_identity_as_execution(tmp_path, case):
    njr, _controller, _form_data = _built(tmp_path)
    stage = copy.deepcopy(njr.config["video_workflow"])
    if case == "whitespace_unknown":
        stage["workflow_id"] = FUN_ID + " "
        stage["workflow_version"] = "9.9.9"
        stage.pop("video_execution")
        reason = "Unknown version"
    elif case == "neutral_precedence":
        stage["workflow_id"] = "wan22_ti2v_5b_i2v_v1"
        stage["workflow_version"] = "1.3.0"
        reason = "NOT QUALIFIED"
    else:
        stage["video_execution"]["experimental_opt_in"] = False
        reason = "experimental opt-in"
    inconsistent = SimpleNamespace(
        config={"video_workflow": stage},
        stage_chain_labels=["video_workflow"],
        input_image_paths=njr.input_image_paths,
    )
    with pytest.raises(ValueError, match=reason):
        require_workflow_admission(inconsistent)


@pytest.mark.parametrize("frames", [9, 25])
def test_original_clip_facts_never_predict_fun_trimming_padding_or_playback_speed(frames):
    result = assess_motion_source(
        geometry=None,
        driving=_facts(fps=30.0, frames=frames),
        output=requested_output_timing(_spec(), 17),
        consumption=driving_frame_consumption(_spec()),
    )
    timing = result.timing
    assert timing.consumption_known
    assert timing.driving_frames_used is None and timing.last_frame_held_for is None
    assert timing.driving_frames_unused is None and timing.playback_speed_vs_original is None
    assert not {a.code for a in result.advisories} & {
        "driving_shorter_than_output",
        "driving_longer_than_output",
        "driving_fps_differs",
    }
    assert "exact prepared" in timing.consumption_note
    assert motion_readiness_projection(_spec())["driving_frame_consumption"][
        "requires_prepared_source"
    ]


def test_preview_reports_frozen_input_and_graph_identities(tmp_path):
    _njr, controller, form = _built(tmp_path)
    source = form["prepared_motion_source"]["original"]["path"]
    # The reference is separate from the original driving clip.
    reference = str(Path(source).parent / "portrait.png")
    sources = controller.select_batch_sources([reference]).sources
    plan = controller.preview_batch(form_data=form, sources=sources)
    view = build_preview_view(plan)
    summary = dict(view.summary)
    assert view.frozen and len(plan.njrs) == 1
    assert len(summary["Graph SHA-256"]) == 64
    assert len(summary["Reference SHA-256"]) == 64
    assert "NOT QUALIFIED" in summary["Hardware"]
    assert "Queue is off" in view.headline


def test_backend_refuses_unqualified_work_before_starting_runtime(tmp_path, monkeypatch):
    njr, _controller, _form_data = _built(tmp_path)
    backend = ComfyWorkflowVideoBackend(
        process_manager=SimpleNamespace(
            config=SimpleNamespace(command=[], working_dir=None),
            ensure_running=lambda: pytest.fail("runtime start forbidden"),
        )
    )
    monkeypatch.setattr("src.video.comfy_workflow_backend.configured_asset_issues", lambda *_: ())
    with pytest.raises(ValueError, match="NOT QUALIFIED"):
        backend.execute(None, _request(njr))


def test_uploaded_source_is_the_verified_snapshot_even_when_path_changes(tmp_path):
    path = tmp_path / "control.mp4"
    path.write_bytes(b"accepted bytes")
    calls = []

    def post(_method, _url, **kwargs):
        path.write_bytes(b"replaced during upload")
        calls.append(kwargs["files"]["image"][1].read())
        return {"name": path.name}

    client = ComfyApiClient()
    client._transport = SimpleNamespace(request_json=post)
    client.upload_image(path, expected_sha256=hashlib.sha256(b"accepted bytes").hexdigest())
    assert calls == [b"accepted bytes"]
    with pytest.raises(ValueError, match="SHA-256"):
        client.upload_image(path, expected_sha256=hashlib.sha256(b"accepted bytes").hexdigest())
    assert len(calls) == 1


def test_relevant_controls_only_and_no_implicit_opt_in():
    visible = form_visibility(_spec())
    assert visible["pose_video"] and visible["frozen_preview"]
    assert not any(
        visible[k] for k in ("end_anchor", "mid_anchors", "camera_intent", "depth_conditioning")
    )
    assert "experimental" in capability_errors(_spec(), {})[0]
    assert any(
        "end anchor" in e for e in capability_errors(_spec(), {"end_anchor_path": "image.png"})
    )


def _small_asset_spec(payload=b"verified model bytes"):
    digest = hashlib.sha256(payload).hexdigest()
    asset = {"folder": "diffusion_models", "size": len(payload), "sha256": digest}
    defaults = {
        "asset_integrity": {
            "repository": "test/repo",
            "revision": "a" * 40,
            "files": {"model.safetensors": asset},
        },
        "provenance": {
            "upstream_repo": "test/repo",
            "upstream_revision": "a" * 40,
            "files": {"model.safetensors": digest},
        },
    }
    return SimpleNamespace(backend_defaults=defaults)


@pytest.mark.parametrize(
    "state", ["missing", "truncated", "digest", "unknown_revision", "valid", "ambiguous"]
)
def test_asset_verification_reads_bytes_without_loading_or_downloading(
    tmp_path, state, monkeypatch
):
    import socket

    monkeypatch.setattr(
        socket, "create_connection", lambda *_a, **_kw: pytest.fail("network forbidden")
    )
    spec = _small_asset_spec()
    file = tmp_path / "model.safetensors"
    if state != "missing":
        file.write_bytes(b"verified model bytes")
    if state == "truncated":
        file.write_bytes(b"short")
    elif state == "digest":
        file.write_bytes(b"x" * len(file.read_bytes()))
    elif state == "unknown_revision":
        spec.backend_defaults["asset_integrity"]["revision"] = "main"
    roots = [tmp_path]
    if state == "ambiguous":
        other = tmp_path / "other"
        other.mkdir()
        (other / file.name).write_bytes(b"wrong")
        roots.append(other)
    issues = verify_assets(spec, {"diffusion_models": roots})
    assert bool(issues) is (state != "valid")
    if state == "digest":
        assert "SHA-256 mismatch" in issues[0]


def test_local_model_search_paths_reuse_existing_folders(tmp_path):
    config = tmp_path / "extra.yaml"
    config.write_text(
        "shared:\n  base_path: assets\n  diffusion_models: diffusion_models\n  text_encoders: text_encoders\n  vae: vae\n"
    )
    roots = model_folders(
        ["python", "main.py", "--extra-model-paths-config", str(config)], str(tmp_path)
    )
    assert tmp_path / "assets" / "diffusion_models" in roots["diffusion_models"]
    assert tmp_path / "assets" / "vae" in roots["vae"]


def test_preflight_separates_missing_assets_and_unqualified_hardware():
    probes = PreflightProbes(
        command=(),
        base_url="http://127.0.0.1:8188",
        autostart=False,
        endpoint_state=lambda _: "free",
        fetch_object_info=lambda _: pytest.fail("no runtime"),
        fetch_system_stats=lambda _: pytest.fail("no runtime"),
        ram_probe=lambda: 1000,
        gpu_probe=lambda _: pytest.fail("no physical GPU probe"),
    )
    result = evaluate_workflow_preflight(_spec(), probes)
    assert not result.queueable
    assert {g.id for g in result.blocking} >= {"asset_integrity", "resource_qualification"}


@needs_ffmpeg
def test_disposable_real_preparation_proves_exact_order_before_binding(tmp_path):
    clip = _clip(tmp_path, rate="24", frames=25)
    original = _digests(clip)
    contract = motion_source_contract(_spec(), 17)
    outcome = prepare_motion_source(
        MotionSourceRequest(str(clip), contract, start=3, end=20, unit="frames"),
        output_root=tmp_path / "out",
    )
    assert outcome.record is not None
    record = verify_exact_motion(_spec(), outcome.record, frame_count=17, original_path=str(clip))
    assert _digests(Path(record["derived"]["path"])) == original[3:20]
