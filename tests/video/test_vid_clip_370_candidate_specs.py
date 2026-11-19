"""VID-CLIP-370: two experimental eval-candidate specs and one three-arm eval admission.

Deterministic and GPU-free: a fake Comfy client, no model, no process, no generation. It proves the
specs are registered, gated and wired as declared, that the A14B graph is the PR-VID-WAN-321F frozen
graph apart from its templated inputs, and that one eval suite admits all three engines in one call.
It does not demonstrate any real generation, resource envelope or visual quality.
"""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from PIL import Image

from src.controller.video_workflow_controller import VideoWorkflowController
from src.video import ComfyWorkflowVideoBackend, VideoExecutionRequest
from src.video.comfy_dependency_probe import ComfyDependencyProbe
from src.video.video_backend_types import (
    CONTROL_NEGATIVE_PROMPT,
    CONTROL_PROMPT_TEXT,
    CONTROL_SOURCE_IMAGE,
)
from src.video.workflow_catalog import WAN22_720P_VERSION, WAN22_FRAMES_VERSION
from src.video.workflow_catalog_wan_a14b import (
    WAN_A14B_ID,
    WAN_A14B_MODEL_FILES,
    WAN_A14B_REQUIRED_LAUNCH_FLAGS,
    WAN_A14B_STOCK_NODES,
    WAN_A14B_VERSION,
)
from src.video.workflow_compiler import WorkflowCompiler
from src.video.workflow_picker import recommended_workflow_id, workflow_choices
from src.video.workflow_readiness import WorkflowResourceReadiness
from src.video.workflow_registry import build_default_workflow_registry, latest_spec_per_workflow
from tests.video.test_comfy_process_manager import fake_comfy_command
from tests.video.test_pr_vid_190_comfy_lifecycle_frame_count import _FakeManager, _no_transition
from tests.video.test_wan22_experimental_workflow import (
    WAN_ID,
    _backend,
    _driver_probe,
    _FakeComfy,
    _stats,
)
from tools.qualification.wan321f import plan as frozen_plan

ROOT = Path(__file__).resolve().parents[2]
EXAMPLE_SUITE = ROOT / "docs" / "runbooks" / "examples" / "video_eval_three_engines.suite.json"
FRAMES = 17


def _spec(workflow_id: str, version: str):
    return build_default_workflow_registry().get(workflow_id, version, allow_experimental=True)


def _differences(left: Any, right: Any, path: str = "") -> set[str]:
    if isinstance(left, dict) and isinstance(right, dict):
        found: set[str] = set()
        for key in set(left) | set(right):
            found |= _differences(left.get(key), right.get(key), f"{path}.{key}" if path else key)
        return found
    return set() if left == right else {path}


# --- registration, governance and the picker --------------------------------------------------


@pytest.mark.parametrize(("workflow_id", "version"), [(WAN_ID, WAN22_720P_VERSION)])
def test_the_720p_candidate_is_still_experimental_and_needs_the_per_job_opt_in(
    # VID-CLIP-372 approved A14B 1.0.0 (see test_vid_clip_372_promotion.py); the 720p approval is held.
    workflow_id: str,
    version: str,
) -> None:
    registry = build_default_workflow_registry()
    spec = registry.get(workflow_id, version, allow_experimental=True)

    assert spec.governance_state == "experimental" and spec.is_experimental
    assert spec.pinned_revision == f"catalog:{workflow_id}@{version}"
    assert "xperimental" in spec.display_name
    assert spec.governance_notes.startswith("EXPERIMENTAL")
    assert (
        "NOT QUALIFIED" in spec.governance_notes.upper() or "not qualified" in spec.governance_notes
    )
    with pytest.raises(KeyError, match="explicit experimental opt-in"):
        registry.get(workflow_id, version)
    approved = {
        (s.workflow_id, s.workflow_version)
        for s in registry.list_offerable_specs("comfy")
        if s.governance_state == "approved"
    }
    assert (workflow_id, version) not in approved
    assert spec.backend_defaults["runtime_policy"]["release_owned_runtime_after_job"] is True


def _controller() -> VideoWorkflowController:
    return VideoWorkflowController(
        app_controller=SimpleNamespace(job_service=SimpleNamespace(), output_dir="out")
    )


def test_the_picker_keeps_offering_the_approved_ti2v_1_3_0_and_recommends_the_promoted_a14b() -> (
    None
):
    controller = _controller()
    records = {r["workflow_id"]: r for r in controller.list_workflow_specs()}

    ti2v = records[WAN_ID]
    assert (ti2v["workflow_version"], ti2v["governance_state"]) == (
        WAN22_FRAMES_VERSION,
        "approved",
    )
    assert ti2v["experimental"] is False
    a14b = records[WAN_A14B_ID]
    assert (a14b["workflow_version"], a14b["governance_state"]) == (
        WAN_A14B_VERSION,
        "approved",
    )
    assert a14b["experimental"] is False and a14b["make_video_default"] is True

    listed = controller.list_workflow_specs()
    assert recommended_workflow_id(listed) == WAN_A14B_ID
    labels = {c.workflow_id: c for c in workflow_choices(listed)}
    assert labels[WAN_A14B_ID].recommended and not labels[WAN_A14B_ID].experimental
    assert not labels[WAN_ID].recommended and not labels[WAN_ID].experimental
    form = controller.build_default_form_state()
    assert (form["workflow_id"], form["workflow_version"]) == (WAN_A14B_ID, WAN_A14B_VERSION)


def test_a_newer_experimental_version_never_displaces_the_newest_approved_one() -> None:
    registry = build_default_workflow_registry()
    ti2v = [s for s in registry.list_offerable_specs("comfy") if s.workflow_id == WAN_ID]
    assert {s.workflow_version for s in ti2v} >= {WAN22_FRAMES_VERSION, WAN22_720P_VERSION}

    assert [s.workflow_version for s in latest_spec_per_workflow(ti2v)] == [WAN22_FRAMES_VERSION]

    def fake(version: str, state: str) -> Any:
        return SimpleNamespace(workflow_id="w", workflow_version=version, governance_state=state)

    only_experimental = [fake("1.0.0", "experimental"), fake("1.1.0", "experimental")]
    assert latest_spec_per_workflow(only_experimental)[0].workflow_version == "1.1.0"
    mixed = [fake("1.2.0", "approved"), fake("1.10.0", "experimental"), fake("1.1.0", "approved")]
    assert latest_spec_per_workflow(mixed)[0].workflow_version == "1.2.0"
    approved = [fake("1.2.0", "approved"), fake("1.10.0", "approved")]
    assert latest_spec_per_workflow(approved)[0].workflow_version == "1.10.0"


# --- TI2V-5B 1.4.0 ----------------------------------------------------------------------------


def test_ti2v_1_4_0_is_the_1_3_0_graph_at_720p_targets_and_nothing_else() -> None:
    base = _spec(WAN_ID, WAN22_FRAMES_VERSION).to_dict()
    candidate = _spec(WAN_ID, WAN22_720P_VERSION)
    changed = _differences(base, candidate.to_dict())

    assert (
        changed
        == {
            "workflow_version",
            "pinned_revision",
            "governance_state",
            "governance_notes",
            "display_name",
            "description",
            "backend_defaults.history_timeout_seconds",  # VID-CLIP-372: 1200 s from the 720p eval timings
            "backend_defaults.source_preparation.portrait_target.width",
            "backend_defaults.source_preparation.portrait_target.height",
            "backend_defaults.source_preparation.landscape_target.width",
            "backend_defaults.source_preparation.landscape_target.height",
            "backend_defaults.provenance.qualification",
            "backend_defaults.operator_projection.fixed_settings.geometry",
            "backend_defaults.operator_projection.fixed_settings.hardware",
        }
    )
    prep = candidate.backend_defaults["source_preparation"]
    assert prep["portrait_target"] == {"width": 704, "height": 1280}
    assert prep["landscape_target"] == {"width": 1280, "height": 704}
    assert (
        prep["resize_policy"] == "cover_resize_center_crop"
        and prep["square_orientation"] == "portrait"
    )
    assert all(
        v % 32 == 0 for t in ("portrait_target", "landscape_target") for v in prep[t].values()
    )
    defaults = candidate.backend_defaults
    assert defaults["output_policy"] == {"mode": "frames", "fps": 24}
    assert (
        defaults["frame_count_policy"]
        == _spec(WAN_ID, "1.3.0").backend_defaults["frame_count_policy"]
    )
    assert (
        defaults["resource_readiness"]
        == _spec(WAN_ID, "1.3.0").backend_defaults["resource_readiness"]
    )


# --- A14B: the 321F frozen graph --------------------------------------------------------------


def _a14b_request(
    tmp: Path,
    *,
    workflow_id: str = WAN_A14B_ID,
    version: str = WAN_A14B_VERSION,
    width: int = 832,
    height: int = 480,
    frames: int = FRAMES,
    opt_in: bool = True,
) -> VideoExecutionRequest:
    source = tmp / "source.png"
    source.write_bytes(b"png")
    return VideoExecutionRequest(
        backend_id="comfy",
        stage_name="video_workflow",
        stage_config={
            "workflow_id": workflow_id,
            "workflow_version": version,
            "seed": 7,
            "frame_count": frames,
            "source_preparation": {"target_dimensions": {"width": width, "height": height}},
        },
        output_dir=tmp / "run",
        input_image_path=source,
        prompt="the person waves",
        negative_prompt="blurry",
        job_id="job-1",
        workflow_id=workflow_id,
        workflow_version=version,
        requested_controls=(CONTROL_SOURCE_IMAGE, CONTROL_PROMPT_TEXT, CONTROL_NEGATIVE_PROMPT),
        experimental_opt_in=opt_in,
    )


def test_the_compiled_a14b_graph_is_the_321f_frozen_graph_apart_from_templated_inputs(
    tmp_path: Path,
) -> None:
    spec = _spec(WAN_A14B_ID, WAN_A14B_VERSION)
    compiled = WorkflowCompiler().compile(spec, _a14b_request(tmp_path)).backend_payload["prompt"]
    frozen = frozen_plan.build_graph(1)

    assert set(compiled) == set(frozen)
    assert _differences(frozen, compiled) == {
        "9.inputs.image",  # LoadImage: the staged source image
        "11.inputs.text",  # prompt
        "12.inputs.text",  # negative prompt
        "13.inputs.noise_seed",  # seed, both passes
        "14.inputs.noise_seed",
        "10.inputs.width",  # frozen geometry (832x480 here; the frozen run was 480x832)
        "10.inputs.height",
        "10.inputs.length",  # frozen frame count (17 here; the frozen run was 81)
        "16.inputs.filename_prefix",  # output prefix
    }
    assert compiled["9"]["inputs"]["image"] == str(tmp_path / "source.png")
    assert (compiled["11"]["inputs"]["text"], compiled["12"]["inputs"]["text"]) == (
        "the person waves",
        "blurry",
    )
    assert compiled["13"]["inputs"]["noise_seed"] == compiled["14"]["inputs"]["noise_seed"] == 7
    assert (compiled["10"]["inputs"]["width"], compiled["10"]["inputs"]["height"]) == (832, 480)
    assert compiled["10"]["inputs"]["length"] == FRAMES
    assert compiled["16"]["inputs"]["filename_prefix"] == "stablenew/wan_a14b_job-1"


def test_the_a14b_pins_are_the_321f_asset_names_and_digests() -> None:
    spec = _spec(WAN_A14B_ID, WAN_A14B_VERSION)
    frozen = {Path(a.relative_path).name: a.sha256 for a in frozen_plan.ASSETS}

    assert {name: digest for _id, name, _hint, digest, _r, _v in WAN_A14B_MODEL_FILES} == frozen
    assert spec.backend_defaults["provenance"]["files"] == frozen
    files = {d.locator: d for d in spec.dependency_specs if d.dependency_kind == "model_file"}
    assert set(files) == set(frozen) and len(files) == 6
    assert {f.version_hint for f in files.values()} == {
        "UNETLoader.unet_name",
        "LoraLoaderModelOnly.lora_name",
        "CLIPLoader.clip_name",
        "VAELoader.vae_name",
    }
    for name, digest in frozen.items():
        assert digest[:16] in files[name].description
    nodes = {d.locator for d in spec.dependency_specs if d.dependency_kind == "stock_node"}
    assert (
        nodes
        == set(WAN_A14B_STOCK_NODES)
        == {node["class_type"] for node in frozen_plan.build_graph(1).values()}
    )


def test_the_a14b_policies_are_declared_with_the_existing_fields_only() -> None:
    defaults = _spec(WAN_A14B_ID, WAN_A14B_VERSION).backend_defaults

    assert defaults["output_policy"] == {"mode": "frames", "fps": 16}
    assert defaults["frame_count_policy"] == {
        "default": 81,
        "minimum": 17,
        "maximum": 81,
        "step": 4,
        "offset": 1,
        "fps": 16,
    }
    assert defaults["runtime_policy"] == {
        "release_owned_runtime_after_job": True,
        "required_launch_flags": ["--disable-pinned-memory"],
    }
    assert set(WAN_A14B_REQUIRED_LAUNCH_FLAGS) <= set(
        frozen_plan.frozen_plan()["runtime"]["required_flags"]
    )
    assert set(defaults["resource_readiness"]) == {
        "policy",
        "min_available_to_comfy_vram_mib",
        "min_available_ram_gb",
    }
    assert defaults["source_preparation"] == {
        "resize_policy": "cover_resize_center_crop",
        "portrait_target": {"width": 480, "height": 832},
        "landscape_target": {"width": 832, "height": 480},
        "square_orientation": "portrait",
    }
    assert (
        defaults["source_preparation"]
        == _spec(WAN_ID, "1.3.0").backend_defaults["source_preparation"]
    )
    assert defaults["history_timeout_seconds"] >= 600


# --- backend runs on a fake Comfy (frames-out path) -------------------------------------------


def _png(path: Path, shade: int) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", (16, 16), (shade, 0, 0)).save(path)
    return path


def _a14b_info(*, drop: str | None = None) -> dict[str, Any]:
    info: dict[str, Any] = {node: {"input": {"required": {}}} for node in WAN_A14B_STOCK_NODES}
    options: dict[tuple[str, str], list[str]] = {}
    for _id, name, hint, _digest, _repo, _rev in WAN_A14B_MODEL_FILES:
        if name == drop:
            options.setdefault(tuple(hint.split(".")), [])  # type: ignore[arg-type]
            continue
        options.setdefault(tuple(hint.split(".")), []).append(name)  # type: ignore[arg-type]
    for (loader, input_name), names in options.items():
        info[loader] = {"input": {"required": {input_name: [names]}}}
    return info


class _FramesFake(_FakeComfy):
    """Fake Comfy that saves numbered PNG frames from the given SaveImage node."""

    def __init__(
        self,
        tmp: Path,
        *,
        save_node: str,
        info: dict[str, Any],
        frames: int = FRAMES,
        stats: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(tmp, info=info, stats=stats)
        self.save_node = save_node
        self.frame_names = [f"frame_{n:05d}_.png" for n in range(1, frames + 1)]

    def get_history(self, prompt_id=None, **_kw):
        images = [
            {"filename": n, "subfolder": "stablenew", "type": "output"} for n in self.frame_names
        ]
        return {
            prompt_id: {
                "outputs": {self.save_node: {"images": images}},
                "status": {"status_str": "success", "completed": True},
            }
        }

    def download_view(self, filename, destination, *, subfolder="", file_type="output", **_kw):
        return _png(Path(destination), (int(filename.split("_")[1]) * 10) % 256)


def _a14b_backend(client, tmp: Path, *, ram_gb: float = 24.0, supported: bool = True):
    """Backend over a fake managed runtime whose launch command does (or does not) support the flag."""

    manager = _FakeManager()
    switches = ("--disable-pinned-memory",) if supported else ()
    manager.config = SimpleNamespace(
        base_url="http://x", command=list(fake_comfy_command(tmp / "comfy_source", *switches))
    )
    backend = ComfyWorkflowVideoBackend(
        client=client,
        process_manager=manager,
        readiness=WorkflowResourceReadiness(
            ram_probe=lambda: ram_gb, gpu_probe=_driver_probe(client.stats)
        ),
        transition=_no_transition(),
        history_timeout=5.0,
        history_poll_interval=0.1,
    )
    backend.fake_manager = manager  # type: ignore[attr-defined]
    return backend


def _fake_export(**kwargs):
    Path(kwargs["output_path"]).parent.mkdir(parents=True, exist_ok=True)
    Path(kwargs["output_path"]).write_bytes(b"mp4")
    return Path(kwargs["output_path"])


@pytest.fixture
def _no_encode(monkeypatch):
    monkeypatch.setattr("src.video.frames_out.export_image_sequence_video", _fake_export)
    monkeypatch.setattr(
        "src.video.comfy_workflow_backend.write_video_container_metadata", lambda *_a, **_k: True
    )


def test_an_a14b_job_completes_through_the_frames_out_path(tmp_path: Path, _no_encode) -> None:
    client = _FramesFake(tmp_path, save_node="16", info=_a14b_info())

    backend = _a14b_backend(client, tmp_path)

    result = backend.execute(None, _a14b_request(tmp_path))

    assert result is not None
    assert backend.fake_manager.stops == 1  # the owned runtime is released after the job
    [queued] = client.queued
    assert queued["prompt"]["16"]["class_type"] == "SaveImage"
    assert queued["prompt"]["13"]["inputs"]["noise_seed"] == 7
    payload = result.to_variant_payload()
    assert payload["frames_out"]["frame_count"] == FRAMES
    assert payload["frames_out"]["reconciliation"]["status"] == "match"
    clip = tmp_path / "run" / f"{WAN_A14B_ID}_job-1.mp4"
    assert result.primary_path == str(clip) and clip.is_file()
    assert result.diagnostic_payload["resource_readiness"]["ready"] is True
    assert (
        ComfyDependencyProbe()
        .probe_workflow(_spec(WAN_A14B_ID, WAN_A14B_VERSION), object_info=client.info)
        .ready
    )


def test_an_approved_a14b_job_runs_without_the_per_job_opt_in(tmp_path: Path, _no_encode) -> None:
    client = _FramesFake(tmp_path, save_node="16", info=_a14b_info())

    result = _a14b_backend(client, tmp_path).execute(None, _a14b_request(tmp_path, opt_in=False))

    assert result is not None and len(client.queued) == 1


def test_an_a14b_job_needs_a_runtime_that_supports_disable_pinned_memory(tmp_path: Path) -> None:
    client = _FramesFake(tmp_path, save_node="16", info=_a14b_info())

    with pytest.raises(RuntimeError, match="--disable-pinned-memory"):
        _a14b_backend(client, tmp_path, supported=False).execute(None, _a14b_request(tmp_path))
    assert client.queued == []


@pytest.mark.parametrize(
    ("missing", "dependency_id"),
    [
        ("wan2.2_i2v_high_noise_14B_fp8_scaled.safetensors", "wan_a14b_high_noise_unet"),
        ("wan2.2_i2v_low_noise_14B_fp8_scaled.safetensors", "wan_a14b_low_noise_unet"),
        (
            "wan2.2_i2v_A14b_high_noise_lora_rank64_lightx2v_4step_1022.safetensors",
            "wan_a14b_high_noise_lora",
        ),
        (
            "wan2.2_i2v_A14b_low_noise_lora_rank64_lightx2v_4step_1022.safetensors",
            "wan_a14b_low_noise_lora",
        ),
    ],
)
def test_a_missing_expert_or_lora_refuses_before_any_queue_prompt(
    tmp_path: Path, missing: str, dependency_id: str
) -> None:
    client = _FramesFake(tmp_path, save_node="16", info=_a14b_info(drop=missing))

    with pytest.raises(RuntimeError, match=dependency_id):
        _a14b_backend(client, tmp_path).execute(None, _a14b_request(tmp_path))
    assert client.queued == []  # nothing was dispatched


def test_a14b_gpu_readiness_still_gates_execution_and_ram_stays_advisory(
    tmp_path: Path, _no_encode
) -> None:
    low = _FramesFake(tmp_path, save_node="16", info=_a14b_info(), stats=_stats(free_mib=5000))
    with pytest.raises(RuntimeError, match="not resource-ready"):
        _a14b_backend(low, tmp_path).execute(None, _a14b_request(tmp_path))
    assert low.queued == []

    short_ram = _FramesFake(
        tmp_path, save_node="16", info=_a14b_info(), stats=_stats(free_mib=11000)
    )
    result = _a14b_backend(short_ram, tmp_path, ram_gb=4.0).execute(None, _a14b_request(tmp_path))
    assert result is not None and len(short_ram.queued) == 1
    assert result.diagnostic_payload["resource_readiness"]["advisories"]


def test_a_ti2v_720p_job_completes_through_the_frames_out_path(tmp_path: Path, _no_encode) -> None:
    from tests.video.test_wan22_experimental_workflow import _object_info

    info = _object_info()
    info["SaveImage"] = {"input": {"required": {}}}
    client = _FramesFake(tmp_path, save_node="11", info=info)
    request = _a14b_request(
        tmp_path, workflow_id=WAN_ID, version=WAN22_720P_VERSION, width=704, height=1280
    )

    result = _backend(client).execute(None, request)

    assert result is not None
    [queued] = client.queued
    graph = queued["prompt"]
    assert (graph["8"]["inputs"]["width"], graph["8"]["inputs"]["height"]) == (704, 1280)
    assert graph["8"]["inputs"]["length"] == FRAMES
    assert graph["11"]["class_type"] == "SaveImage"
    assert result.to_variant_payload()["frames_out"]["reconciliation"]["status"] == "match"


def test_a_ti2v_720p_job_without_the_opt_in_is_refused_before_queue_prompt(tmp_path: Path) -> None:
    from tests.video.test_wan22_experimental_workflow import _object_info

    client = _FramesFake(tmp_path, save_node="11", info=_object_info())
    request = _a14b_request(
        tmp_path,
        workflow_id=WAN_ID,
        version=WAN22_720P_VERSION,
        width=704,
        height=1280,
        opt_in=False,
    )
    with pytest.raises(KeyError, match="explicit experimental opt-in"):
        _backend(client).execute(None, request)
    assert client.queued == []


# --- the example eval suite admits all three engines once -------------------------------------


class _JobService:
    def __init__(self) -> None:
        self.calls: list[list[Any]] = []

    def submit_njrs(self, njrs, policy):
        self.calls.append(list(njrs))
        return [njr.job_id for njr in njrs]


def _materialize_example(tmp_path: Path) -> Path:
    data = json.loads(EXAMPLE_SUITE.read_text(encoding="utf-8"))
    suite_dir = tmp_path / "suite"
    for case in data["cases"]:
        image = suite_dir / case["image"]
        image.parent.mkdir(parents=True, exist_ok=True)
        size = (96, 64) if "landscape" in case["image"] else (64, 96)
        Image.new("RGB", size, (90, 60, 30)).save(image)
    path = suite_dir / "suite.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    return path


def test_the_example_suite_is_synthetic_and_names_the_three_arms() -> None:
    data = json.loads(EXAMPLE_SUITE.read_text(encoding="utf-8"))
    text = EXAMPLE_SUITE.read_text(encoding="utf-8")

    assert data["schema"] == "stablenew.video-eval-suite.v1"
    assert all(case["image"].startswith("images/synthetic_") for case in data["cases"])
    assert "\\" not in text and ":/" not in text and "C:" not in text  # no machine-local paths
    arms = {arm["arm_id"]: arm["form"] for arm in data["arms"]}
    assert data["baseline_arm"] == "ti2v_480p"
    assert (arms["ti2v_480p"]["workflow_id"], arms["ti2v_480p"]["workflow_version"]) == (
        WAN_ID,
        "1.3.0",
    )
    assert "experimental_opt_in" not in arms["ti2v_480p"]
    assert (arms["ti2v_720p"]["workflow_version"], arms["ti2v_720p"]["experimental_opt_in"]) == (
        "1.4.0",
        True,
    )
    assert (arms["a14b_480p"]["workflow_id"], arms["a14b_480p"]["experimental_opt_in"]) == (
        WAN_A14B_ID,
        True,
    )


def test_the_example_suite_builds_one_njr_per_case_per_arm_and_admits_once(tmp_path: Path) -> None:
    job_service = _JobService()
    app = SimpleNamespace(
        job_service=job_service,
        output_dir=str(tmp_path / "output"),
        sync_queue_state_after_direct_submission=lambda: None,
    )
    controller = VideoWorkflowController(app_controller=app)

    plan = controller.preview_eval_run(_materialize_example(tmp_path))

    assert plan.eligible, plan.summary()
    assert len(plan.jobs) == 9 and job_service.calls == []  # a preview admits nothing
    # The suite still declares the opt-in on the A14B arm; the approved spec ignores it and the NJR records False.
    assert set(plan.experimental_arms) == {"ti2v_720p", "a14b_480p"}
    by_cell = {(job.case_id, job.arm_id): job.njr.config["video_workflow"] for job in plan.jobs}
    assert len(by_cell) == 9
    expected = {
        "ti2v_480p": (WAN_ID, "1.3.0", False, (480, 832)),
        "ti2v_720p": (WAN_ID, "1.4.0", True, (704, 1280)),
        "a14b_480p": (WAN_A14B_ID, "1.0.0", False, (480, 832)),
    }
    for (case_id, arm_id), config in by_cell.items():
        workflow_id, version, opt_in, portrait = expected[arm_id]
        assert (config["workflow_id"], config["workflow_version"]) == (workflow_id, version)
        assert config["video_execution"]["experimental_opt_in"] is opt_in
        assert config["seed"] == 370 and config["frame_count"] == 81
        target = config["source_preparation"]["target_dimensions"]
        width, height = (portrait[1], portrait[0]) if case_id == "harbor_pan" else portrait
        assert (target["width"], target["height"]) == (width, height)
    assert by_cell[("walk_forward", "a14b_480p")]["fps"] == 16
    assert by_cell[("walk_forward", "ti2v_720p")]["fps"] == 24

    admission = controller.submit_eval_run(plan)

    assert len(job_service.calls) == 1 and len(job_service.calls[0]) == 9
    assert admission.manifest_path.is_file()
