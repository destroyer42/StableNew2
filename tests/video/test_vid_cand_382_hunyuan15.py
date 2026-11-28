"""VID-CAND-382: the experimental HunyuanVideo 1.5 480p I2V candidate specs and their eval suites.

Deterministic and GPU-free: a fake Comfy client and fake managed runtime, no model, no process, no generation.  It
proves both specs are registered, gated, pinned and wired as declared, that the 8-step and 12-step ids differ in
exactly the sampler step count, that readiness and the dependency probe refuse before any queue call, and that the
example suites build previews of the planned job counts.  It demonstrates no speed, quality or resource envelope.
"""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from PIL import Image

from src.controller.video_workflow_controller import VideoWorkflowController
from src.video.comfy_dependency_probe import ComfyDependencyProbe
from src.video.video_eval_suite import MAX_EVAL_JOBS, load_eval_suite
from src.video.workflow_catalog_hunyuan15 import (
    HUNYUAN15_12_STEP_ID,
    HUNYUAN15_BYT5_ENCODER,
    HUNYUAN15_CLIP_TYPE,
    HUNYUAN15_FILE_BYTES,
    HUNYUAN15_FRAME_COUNT_POLICY,
    HUNYUAN15_ID,
    HUNYUAN15_IDS,
    HUNYUAN15_MODEL_FILES,
    HUNYUAN15_REQUIRED_LAUNCH_FLAGS,
    HUNYUAN15_REVISION,
    HUNYUAN15_STEPS,
    HUNYUAN15_STOCK_NODES,
    HUNYUAN15_VAE,
    HUNYUAN15_VERSION,
)
from src.video.workflow_catalog_wan_a14b import (
    WAN_A14B_FULL_PICTURE_ID,
    WAN_A14B_ID,
    WAN_A14B_VERSION,
)
from src.video.workflow_compiler import WorkflowCompiler
from src.video.workflow_frame_count import frame_count_projection, legal_frame_counts
from src.video.workflow_picker import recommended_workflow_id
from src.video.workflow_registry import build_default_workflow_registry, latest_spec_per_workflow
from tests.video.test_vid_clip_370_candidate_specs import (
    _a14b_backend,
    _a14b_request,
    _fake_export,
    _FramesFake,
)
from tests.video.test_wan22_experimental_workflow import _stats
from tools.qualification.vid_cand382 import plan as design

ROOT = Path(__file__).resolve().parents[2]
EXAMPLES = ROOT / "docs" / "runbooks" / "examples"
SAVE_NODE = "12"
FRAMES = 17  # the fake run's frame count; the catalog default is 121


def _spec(workflow_id: str):
    return build_default_workflow_registry().get(
        workflow_id, HUNYUAN15_VERSION, allow_experimental=True
    )


def _differences(left: Any, right: Any, path: str = "") -> set[str]:
    if isinstance(left, dict) and isinstance(right, dict):
        found: set[str] = set()
        for key in set(left) | set(right):
            found |= _differences(left.get(key), right.get(key), f"{path}.{key}" if path else key)
        return found
    return set() if left == right else {path}


def _info(*, drop_file: str | None = None, drop_node: str | None = None) -> dict[str, Any]:
    """What a managed ComfyUI 0.38.0 would advertise for this graph (file lists, type recipe, vision input)."""

    info: dict[str, Any] = {node: {"input": {"required": {}}} for node in HUNYUAN15_STOCK_NODES}
    options: dict[tuple[str, str], list[str]] = {}
    for _id, name, hint, _digest, _repo, _rev in HUNYUAN15_MODEL_FILES:
        key = tuple(hint.split("."))
        options.setdefault(key, [])  # type: ignore[arg-type]
        if name != drop_file:
            options[key].append(name)  # type: ignore[index]
    for (loader, input_name), names in options.items():
        info[loader]["input"]["required"][input_name] = [names]
    info["DualCLIPLoader"]["input"]["required"]["type"] = [["sdxl", "flux", HUNYUAN15_CLIP_TYPE]]
    info["HunyuanVideo15ImageToVideo"]["input"]["optional"] = {
        "clip_vision_output": ["CLIP_VISION_OUTPUT"]
    }
    if drop_node:
        del info[drop_node]
    return info


def _request(tmp_path: Path, workflow_id: str, *, opt_in: bool = True, frames: int = FRAMES):
    return _a14b_request(
        tmp_path,
        workflow_id=workflow_id,
        version=HUNYUAN15_VERSION,
        width=480,
        height=848,
        frames=frames,
        opt_in=opt_in,
    )


def _compiled(workflow_id: str, tmp_path: Path) -> dict[str, Any]:
    return (
        WorkflowCompiler()
        .compile(_spec(workflow_id), _request(tmp_path, workflow_id))
        .backend_payload["prompt"]
    )


@pytest.fixture
def _no_encode(monkeypatch):
    monkeypatch.setattr("src.video.frames_out.export_image_sequence_video", _fake_export)
    monkeypatch.setattr(
        "src.video.comfy_workflow_backend.write_video_container_metadata", lambda *_a, **_k: True
    )


# --- registration, governance and the picker --------------------------------------------------


@pytest.mark.parametrize("workflow_id", HUNYUAN15_IDS)
def test_both_ids_are_registered_as_experimental_and_refused_without_the_opt_in(
    workflow_id: str,
) -> None:
    registry = build_default_workflow_registry()
    spec = _spec(workflow_id)

    assert registry.list_versions(workflow_id) == [HUNYUAN15_VERSION]
    assert spec.governance_state == "experimental" and spec.is_experimental
    assert spec.pinned_revision == f"catalog:{workflow_id}@{HUNYUAN15_VERSION}"
    assert "(Experimental)" in spec.display_name
    assert spec.governance_notes.startswith("EXPERIMENTAL")
    assert "NOT QUALIFIED" in spec.governance_notes
    assert spec.backend_defaults["make_video_default"] is False
    assert f"{HUNYUAN15_STEPS[workflow_id]}-step" in spec.display_name
    with pytest.raises(KeyError, match="explicit experimental opt-in"):
        registry.get(workflow_id, HUNYUAN15_VERSION)
    runnable = {
        (s.workflow_id, s.workflow_version) for s in registry.list_specs_for_backend("comfy")
    }
    assert (workflow_id, HUNYUAN15_VERSION) not in runnable


def test_the_approved_a14b_stays_the_make_video_default_and_the_candidates_are_never_preselected() -> (
    None
):
    controller = VideoWorkflowController(
        app_controller=SimpleNamespace(job_service=SimpleNamespace(), output_dir="out")
    )
    listed = controller.list_workflow_specs()
    records = {r["workflow_id"]: r for r in listed}

    assert recommended_workflow_id(listed) == WAN_A14B_FULL_PICTURE_ID
    form = controller.build_default_form_state()
    assert (form["workflow_id"], form["workflow_version"]) == (
        WAN_A14B_FULL_PICTURE_ID,
        WAN_A14B_VERSION,
    )
    for workflow_id in HUNYUAN15_IDS:
        assert records[workflow_id]["experimental"] is True
        assert records[workflow_id]["make_video_default"] is False
        entries = [
            s
            for s in build_default_workflow_registry().list_offerable_specs("comfy")
            if s.workflow_id == workflow_id
        ]
        assert [s.workflow_version for s in latest_spec_per_workflow(entries)] == [
            HUNYUAN15_VERSION
        ]


def test_the_two_ids_share_everything_except_identity_and_the_sampler_step_count(
    tmp_path: Path,
) -> None:
    eight, twelve = (_spec(i) for i in HUNYUAN15_IDS)

    changed = _differences(eight.to_dict(), twelve.to_dict())
    assert changed == {
        "workflow_id",
        "pinned_revision",
        "display_name",
        "description",
        "backend_defaults.prompt_template.10.inputs.steps",
        "backend_defaults.operator_projection.fixed_settings.steps",
    }
    assert _differences(
        _compiled(HUNYUAN15_ID, tmp_path), _compiled(HUNYUAN15_12_STEP_ID, tmp_path)
    ) == {"10.inputs.steps"}
    assert (
        _compiled(HUNYUAN15_ID, tmp_path)["10"]["inputs"]["steps"],
        _compiled(HUNYUAN15_12_STEP_ID, tmp_path)["10"]["inputs"]["steps"],
    ) == (8, 12)


# --- pinned files and provenance --------------------------------------------------------------


def test_every_model_file_is_pinned_by_sha256_revision_size_and_loader_input() -> None:
    names = [entry[1] for entry in HUNYUAN15_MODEL_FILES]
    assert len(set(names)) == len(names) == 5
    assert set(HUNYUAN15_FILE_BYTES) == set(names)
    for dependency_id, name, hint, digest, repo, revision in HUNYUAN15_MODEL_FILES:
        assert re.fullmatch(r"[0-9a-f]{64}", digest), dependency_id
        assert re.fullmatch(r"[0-9a-f]{40}", revision) and revision == HUNYUAN15_REVISION
        assert repo == "Comfy-Org/Hunyuan-Video-1.5"
        assert re.fullmatch(r"[A-Za-z]+\.[a-z_0-9]+", hint)
        assert name.endswith(".safetensors") and HUNYUAN15_FILE_BYTES[name] > 0
    assert len({entry[3] for entry in HUNYUAN15_MODEL_FILES}) == 5

    for workflow_id in HUNYUAN15_IDS:
        provenance = _spec(workflow_id).backend_defaults["provenance"]
        assert provenance["files"] == {entry[1]: entry[3] for entry in HUNYUAN15_MODEL_FILES}
        assert provenance["upstream_revision"] == HUNYUAN15_REVISION
        assert provenance["comfyui_version"] == "0.38.0"
        assert "EU" in provenance["license"] and "UK" in provenance["license"]
        assert "South Korea" in provenance["license"]
        assert provenance["qualification"].startswith("NOT QUALIFIED")


def test_the_model_files_are_the_480p_step_distilled_fp8_build_not_a_larger_one() -> None:
    names = {entry[1] for entry in HUNYUAN15_MODEL_FILES}

    assert "hunyuanvideo1.5_480p_i2v_step_distilled_fp8_scaled.safetensors" in names
    assert HUNYUAN15_BYT5_ENCODER in names and HUNYUAN15_VAE in names
    assert not any("fp16" in n and "unet" in n for n in names)
    assert not any(n.startswith("hunyuanvideo1.5_720p") for n in names)
    # The published fit is 12 GB VRAM / 32 GB RAM: the diffusion model plus its encoder is ~17.8 GB of weights.
    heavy = [
        HUNYUAN15_FILE_BYTES[n]
        for n in names
        if "unet" in n or "step_distilled" in n or "qwen" in n
    ]
    assert sum(heavy) < 18_000_000_000


# The published specs and graphs are immutable once registered: a change is a new version (VIDEO_PIPELINE section 13).
# sha256 of json.dumps(spec.to_dict(), sort_keys=True, ensure_ascii=False, default=str) and of the prompt template alone,
# pinned from the first registration (VID-CAND-382).
PINNED_SPEC_SHA256 = {
    HUNYUAN15_ID: "3e908b5e7f62a68649234e340e1d51d9ebbfe0113cd89019884a97ac2b2c245a",
    HUNYUAN15_12_STEP_ID: "bced62437d8400bf861757c08ccf386073ea2be2e3958f9c9cbf0604d20adc6c",
}
PINNED_TEMPLATE_SHA256 = {
    HUNYUAN15_ID: "625670d12cd9fb052031217ff2b3521bb52fed57c0f22140525e815425afc8d2",
    HUNYUAN15_12_STEP_ID: "4a079db2b5723834a7e42b333692fa36a7830d2033d0ac4865393324024fd41d",
}


def _digest(value: Any) -> str:
    text = json.dumps(value, sort_keys=True, ensure_ascii=False, default=str)
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


@pytest.mark.parametrize("workflow_id", HUNYUAN15_IDS)
def test_the_registered_specs_and_graphs_are_pinned_byte_for_byte(workflow_id: str) -> None:
    spec = _spec(workflow_id)

    assert _digest(spec.to_dict()) == PINNED_SPEC_SHA256[workflow_id]
    assert _digest(spec.backend_defaults["prompt_template"]) == PINNED_TEMPLATE_SHA256[workflow_id]


# --- the graph ---------------------------------------------------------------------------------


@pytest.mark.parametrize("workflow_id", HUNYUAN15_IDS)
def test_the_compiled_graph_is_the_declared_stock_node_graph(
    tmp_path: Path, workflow_id: str
) -> None:
    graph = _compiled(workflow_id, tmp_path)

    assert {node["class_type"] for node in graph.values()} == set(HUNYUAN15_STOCK_NODES)
    assert "ModelSamplingSD3" not in {
        n["class_type"] for n in graph.values()
    }  # the model's own shift of 7.0
    assert graph["9"]["class_type"] == "HunyuanVideo15ImageToVideo"
    assert graph["9"]["inputs"]["width"] == 480 and graph["9"]["inputs"]["height"] == 848
    assert graph["9"]["inputs"]["length"] == FRAMES
    assert graph["9"]["inputs"]["clip_vision_output"] == ["6", 0]
    assert graph["2"]["inputs"]["type"] == HUNYUAN15_CLIP_TYPE
    sampler = graph["10"]["inputs"]
    assert sampler["seed"] == 7 and sampler["cfg"] == 1.0 and sampler["denoise"] == 1.0
    assert (sampler["sampler_name"], sampler["scheduler"]) == ("euler", "simple")
    assert sampler["latent_image"] == ["9", 2]
    assert graph["12"]["class_type"] == "SaveImage"
    assert not any(
        "{{" in json.dumps(node) for node in graph.values()
    )  # every template input resolved
    for node in graph.values():
        for value in node["inputs"].values():
            if isinstance(value, list):  # a link must point at a node that exists
                assert value[0] in graph


def test_every_stock_node_is_a_dependency_and_every_loader_file_is_in_the_graph(
    tmp_path: Path,
) -> None:
    spec = _spec(HUNYUAN15_ID)
    declared = {d.locator for d in spec.dependency_specs if d.dependency_kind == "stock_node"}
    graph_text = json.dumps(_compiled(HUNYUAN15_ID, tmp_path))

    assert declared == set(HUNYUAN15_STOCK_NODES)
    for _id, name, _hint, _digest, _repo, _rev in HUNYUAN15_MODEL_FILES:
        assert name in graph_text
    kinds = {d.dependency_kind for d in spec.dependency_specs}
    assert kinds == {"model_file", "stock_node", "node_option", "node_input"}


# --- frame, runtime and readiness policy -------------------------------------------------------


@pytest.mark.parametrize("workflow_id", HUNYUAN15_IDS)
def test_the_policies_give_an_equal_duration_clip_at_the_native_24_fps(workflow_id: str) -> None:
    spec = _spec(workflow_id)
    defaults = spec.backend_defaults

    assert defaults["frame_count_policy"] == HUNYUAN15_FRAME_COUNT_POLICY
    assert defaults["output_policy"] == {"mode": "frames", "fps": 24}
    legal = legal_frame_counts(spec)
    assert (
        legal[0] == 17
        and legal[-1] == 121
        and 121 in legal
        and all((n - 1) % 4 == 0 for n in legal)
    )
    projection = frame_count_projection(spec)
    assert projection["default"] == 121 and projection["fps"] == 24
    a14b = build_default_workflow_registry().get(WAN_A14B_ID, WAN_A14B_VERSION)
    a14b_seconds = a14b.backend_defaults["frame_count_policy"]["default"] / 16
    assert abs(121 / 24 - a14b_seconds) < 0.05  # 5.04 s against 5.06 s
    assert defaults["runtime_policy"]["required_launch_flags"] == list(
        HUNYUAN15_REQUIRED_LAUNCH_FLAGS
    )
    assert defaults["runtime_policy"]["release_owned_runtime_after_job"] is True
    assert set(defaults["resource_readiness"]) == {
        "policy",
        "min_available_to_comfy_vram_mib",
        "min_available_ram_gb",
    }
    assert (
        defaults["resource_readiness"]["min_available_to_comfy_vram_mib"] <= 12282
    )  # fits the 12 GB card
    assert defaults["history_timeout_seconds"] == 1200


def test_the_target_sizes_are_multiples_of_the_16_pixel_latent_grid_and_cover_both_orientations() -> (
    None
):
    prep = _spec(HUNYUAN15_ID).backend_defaults["source_preparation"]

    assert prep["portrait_target"] == {"width": 480, "height": 848}
    assert prep["landscape_target"] == {"width": 848, "height": 480}
    assert all(
        v % 16 == 0 for t in ("portrait_target", "landscape_target") for v in prep[t].values()
    )
    assert (
        prep["resize_policy"] == "cover_resize_center_crop"
        and prep["square_orientation"] == "portrait"
    )


# --- dependency probe and backend runs on a fake Comfy ----------------------------------------


@pytest.mark.parametrize("workflow_id", HUNYUAN15_IDS)
def test_the_probe_accepts_a_runtime_that_advertises_everything(workflow_id: str) -> None:
    assert ComfyDependencyProbe().probe_workflow(_spec(workflow_id), object_info=_info()).ready


@pytest.mark.parametrize(
    ("kwargs", "missing"),
    [
        ({"drop_file": HUNYUAN15_BYT5_ENCODER}, "hunyuan15_byt5_glyph_text_encoder"),
        ({"drop_node": "HunyuanVideo15ImageToVideo"}, "node_hunyuanvideo15imagetovideo"),
        ({"drop_node": "CLIPVisionEncode"}, "node_clipvisionencode"),
    ],
)
def test_a_missing_file_or_node_is_named_by_the_probe(kwargs: dict[str, str], missing: str) -> None:
    result = ComfyDependencyProbe().probe_workflow(_spec(HUNYUAN15_ID), object_info=_info(**kwargs))

    assert not result.ready and missing in result.missing_required


def test_a_runtime_without_the_text_encoder_recipe_or_the_vision_input_is_refused() -> None:
    no_recipe = _info()
    no_recipe["DualCLIPLoader"]["input"]["required"]["type"] = [["sdxl", "flux"]]
    no_vision = _info()
    no_vision["HunyuanVideo15ImageToVideo"]["input"].pop("optional")

    spec = _spec(HUNYUAN15_ID)
    recipe = ComfyDependencyProbe().probe_workflow(spec, object_info=no_recipe)
    vision = ComfyDependencyProbe().probe_workflow(spec, object_info=no_vision)

    assert "option_dualcliploader_hunyuan_video_15" in recipe.missing_required
    assert "input_hunyuanvideo15imagetovideo_clip_vision_output" in vision.missing_required


@pytest.mark.parametrize("workflow_id", HUNYUAN15_IDS)
def test_an_opted_in_job_completes_through_the_frames_out_path(
    tmp_path: Path, _no_encode, workflow_id: str
) -> None:
    client = _FramesFake(tmp_path, save_node=SAVE_NODE, info=_info(), frames=FRAMES)

    result = _a14b_backend(client, tmp_path).execute(None, _request(tmp_path, workflow_id))

    assert result is not None
    [queued] = client.queued
    assert _differences(_compiled(workflow_id, tmp_path), queued["prompt"]) == {"5.inputs.image"}
    assert queued["prompt"][SAVE_NODE]["class_type"] == "SaveImage"
    payload = result.to_variant_payload()
    assert payload["frames_out"]["frame_count"] == FRAMES
    assert payload["frames_out"]["reconciliation"]["status"] == "match"
    assert result.diagnostic_payload["resource_readiness"]["ready"] is True


@pytest.mark.parametrize("workflow_id", HUNYUAN15_IDS)
def test_a_job_without_the_per_job_opt_in_is_refused_before_any_queue_prompt(
    tmp_path: Path, workflow_id: str
) -> None:
    client = _FramesFake(tmp_path, save_node=SAVE_NODE, info=_info())

    with pytest.raises(KeyError, match="explicit experimental opt-in"):
        _a14b_backend(client, tmp_path).execute(None, _request(tmp_path, workflow_id, opt_in=False))
    assert client.queued == []


def test_a_missing_file_refuses_before_any_queue_prompt(tmp_path: Path) -> None:
    client = _FramesFake(
        tmp_path, save_node=SAVE_NODE, info=_info(drop_file=HUNYUAN15_BYT5_ENCODER)
    )

    with pytest.raises(RuntimeError, match="hunyuan15_byt5_glyph_text_encoder"):
        _a14b_backend(client, tmp_path).execute(None, _request(tmp_path, HUNYUAN15_ID))
    assert client.queued == []


def test_a_runtime_launched_without_the_required_flag_refuses_before_any_queue_prompt(
    tmp_path: Path,
) -> None:
    client = _FramesFake(tmp_path, save_node=SAVE_NODE, info=_info())

    with pytest.raises(RuntimeError, match="disable-pinned-memory"):
        _a14b_backend(client, tmp_path, supported=False).execute(
            None, _request(tmp_path, HUNYUAN15_ID)
        )
    assert client.queued == []


def test_gpu_readiness_gates_execution_and_ram_stays_advisory(tmp_path: Path, _no_encode) -> None:
    low = _FramesFake(tmp_path, save_node=SAVE_NODE, info=_info(), stats=_stats(free_mib=5000))
    with pytest.raises(RuntimeError, match="not resource-ready"):
        _a14b_backend(low, tmp_path).execute(None, _request(tmp_path, HUNYUAN15_ID))
    assert low.queued == []

    short_ram = _FramesFake(
        tmp_path, save_node=SAVE_NODE, info=_info(), stats=_stats(free_mib=11000), frames=FRAMES
    )
    result = _a14b_backend(short_ram, tmp_path, ram_gb=4.0).execute(
        None, _request(tmp_path, HUNYUAN15_ID)
    )
    assert result is not None and len(short_ram.queued) == 1
    assert result.diagnostic_payload["resource_readiness"]["advisories"]


# --- the example eval suites --------------------------------------------------------------------


class _JobService:
    def __init__(self) -> None:
        self.calls: list[list[Any]] = []

    def submit_njrs(self, njrs, policy):
        self.calls.append(list(njrs))
        return [njr.job_id for njr in njrs]


def _materialize(tmp_path: Path, name: str) -> Path:
    data = json.loads((EXAMPLES / name).read_text(encoding="utf-8"))
    suite_dir = tmp_path / "suite"
    for case in data["cases"]:
        image = suite_dir / case["image"]
        image.parent.mkdir(parents=True, exist_ok=True)
        size = (96, 64) if "landscape" in case["image"] else (64, 96)
        Image.new("RGB", size, (90, 60, 30)).save(image)
    path = suite_dir / "suite.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    return path


@pytest.mark.parametrize(
    ("stage", "jobs", "cases", "arms"),
    [("stage0", 2, 2, 1), ("stage1", 24, 8, 3), ("stage2", 16, 8, 2)],
)
def test_each_example_suite_loads_within_the_job_cap(
    tmp_path: Path, stage: str, jobs: int, cases: int, arms: int
) -> None:
    suite = load_eval_suite(_materialize(tmp_path, design.EXAMPLE_FILES[stage]))

    assert (len(suite.cases), len(suite.arms), suite.job_count) == (cases, arms, jobs)
    assert suite.job_count <= MAX_EVAL_JOBS
    assert suite.seed == design.SEEDS[stage]


def test_the_example_files_are_exactly_what_the_frozen_design_builds() -> None:
    for stage, document in design.example_suites().items():
        text = (EXAMPLES / design.EXAMPLE_FILES[stage]).read_text(encoding="utf-8")
        assert json.loads(text) == document
        assert "\\" not in text and ":/" not in text and "C:" not in text  # no machine-local path
        assert all(c["image"].startswith("images/synthetic_") for c in document["cases"])


def test_the_example_arms_follow_the_fairness_rules() -> None:
    suites = design.example_suites()
    stage1 = suites["stage1"]
    arms = {arm["arm_id"]: arm["form"] for arm in stage1["arms"]}

    assert stage1["baseline_arm"] == design.A14B_ARM
    assert arms[design.A14B_ARM] == {
        "workflow_id": WAN_A14B_ID,
        "workflow_version": WAN_A14B_VERSION,
        "frame_count": 81,
    }  # approved: no opt-in
    for arm_id, workflow_id in (
        (design.HUNYUAN_8_ARM, HUNYUAN15_ID),
        (design.HUNYUAN_12_ARM, HUNYUAN15_12_STEP_ID),
    ):
        assert arms[arm_id] == {
            "workflow_id": workflow_id,
            "workflow_version": HUNYUAN15_VERSION,
            "frame_count": 121,
            "experimental_opt_in": True,
        }
    for suite in suites.values():
        for arm in suite["arms"]:  # no RIFE or other resampling knob in any arm
            assert set(arm["form"]) <= {
                "workflow_id",
                "workflow_version",
                "frame_count",
                "experimental_opt_in",
            }
    assert {a["form"]["workflow_id"] for a in suites["stage2"]["arms"]} == {
        WAN_A14B_ID,
        HUNYUAN15_ID,
    }


def test_the_stage1_example_previews_24_jobs_and_admits_only_on_submit(tmp_path: Path) -> None:
    job_service = _JobService()
    app = SimpleNamespace(
        job_service=job_service,
        output_dir=str(tmp_path / "output"),
        sync_queue_state_after_direct_submission=lambda: None,
    )
    controller = VideoWorkflowController(app_controller=app)

    plan = controller.preview_eval_run(_materialize(tmp_path, design.EXAMPLE_FILES["stage1"]))

    assert plan.eligible, plan.summary()
    assert len(plan.jobs) == 24 and job_service.calls == []  # a preview admits nothing
    assert set(plan.experimental_arms) == {design.HUNYUAN_8_ARM, design.HUNYUAN_12_ARM}
    for job in plan.jobs:
        config = job.njr.config["video_workflow"]
        hunyuan = job.arm_id != design.A14B_ARM
        assert config["video_execution"]["experimental_opt_in"] is hunyuan
        assert config["seed"] == 371
        assert (config["frame_count"], config["fps"]) == ((121, 24) if hunyuan else (81, 16))
        assert config["workflow_id"] == (
            {design.HUNYUAN_8_ARM: HUNYUAN15_ID, design.HUNYUAN_12_ARM: HUNYUAN15_12_STEP_ID}.get(
                job.arm_id, WAN_A14B_ID
            )
        )

    admission = controller.submit_eval_run(plan)

    assert len(job_service.calls) == 1 and len(job_service.calls[0]) == 24
    assert admission.manifest_path.is_file()
