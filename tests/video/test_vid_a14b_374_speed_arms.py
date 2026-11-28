"""VID-A14B-SPEED-374: three experimental Wan2.2 I2V-A14B speed arms and longer A14B lengths.

Deterministic and GPU-free: a fake Comfy client and fake managed runtime, no model, process or generation.
It proves the arms are registered, gated and wired as declared, that each changes exactly one thing in the
approved 1.0.0 graph, that readiness knows the attention node and its option, that versions never share a warm
process, that A14B offers 17..121 frames with an advisory above 81, and that the example suite only builds a plan
until the owner queues it.  It demonstrates no speed, quality or resource envelope.
"""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from PIL import Image

from src.controller.video_workflow_controller import VideoWorkflowController
from src.video.comfy_dependency_probe import ComfyDependencyProbe
from src.video.workflow_catalog import WAN22_FRAMES_VERSION
from src.video.workflow_catalog_wan_a14b import (
    WAN_A14B_ATTENTION_NODE,
    WAN_A14B_CK_ATTENTION,
    WAN_A14B_CK_ATTENTION_VERSION,
    WAN_A14B_FULL_PICTURE_ID,
    WAN_A14B_GPU_TEXT_ENCODER_VERSION,
    WAN_A14B_ID,
    WAN_A14B_MERGED_FILE_BYTES,
    WAN_A14B_MERGED_MODEL_FILES,
    WAN_A14B_MERGED_VERSION,
    WAN_A14B_MODEL_FILES,
    WAN_A14B_SPEED_ARM_VERSIONS,
    WAN_A14B_STOCK_NODES,
    WAN_A14B_VERSION,
)
from src.video.workflow_compiler import WorkflowCompiler
from src.video.workflow_frame_count import (
    frame_count_advisory,
    frame_count_projection,
    legal_frame_counts,
    parse_frame_count,
)
from src.video.workflow_picker import recommended_workflow_id
from src.video.workflow_preflight import _dependency_gates
from src.video.workflow_registry import build_default_workflow_registry, latest_spec_per_workflow
from tests.video.test_vid_clip_370_candidate_specs import (
    _a14b_backend,
    _a14b_request,
    _fake_export,
    _FramesFake,
)
from tests.video.test_vid_warm_373_a14b_reuse import _slot
from tests.video.test_wan22_experimental_workflow import WAN_ID, _stats

ROOT = Path(__file__).resolve().parents[2]
SUITE = ROOT / "docs" / "runbooks" / "examples" / "video_eval_a14b_speed_arms.suite.json"
ALL_VERSIONS = (WAN_A14B_VERSION, *WAN_A14B_SPEED_ARM_VERSIONS)
CK, MERGED, GPU_TE = (
    WAN_A14B_CK_ATTENTION_VERSION,
    WAN_A14B_MERGED_VERSION,
    WAN_A14B_GPU_TEXT_ENCODER_VERSION,
)


def _spec(version: str, workflow_id: str = WAN_A14B_ID):
    return build_default_workflow_registry().get(workflow_id, version, allow_experimental=True)


def _differences(left: Any, right: Any, path: str = "") -> set[str]:
    if isinstance(left, dict) and isinstance(right, dict):
        found: set[str] = set()
        for key in set(left) | set(right):
            found |= _differences(left.get(key), right.get(key), f"{path}.{key}" if path else key)
        return found
    return set() if left == right else {path}


@pytest.fixture
def _no_encode(monkeypatch):
    monkeypatch.setattr("src.video.frames_out.export_image_sequence_video", _fake_export)
    monkeypatch.setattr(
        "src.video.comfy_workflow_backend.write_video_container_metadata", lambda *_a, **_k: True
    )


# --- registration and governance --------------------------------------------------------------


def test_the_arms_are_registered_beside_the_approved_1_0_0_as_experimental_versions() -> None:
    registry = build_default_workflow_registry()

    assert registry.list_versions(WAN_A14B_ID) == ["1.0.0", "1.1.0", "1.2.0", "1.3.0"]
    assert _spec(WAN_A14B_VERSION).governance_state == "approved"
    for version in WAN_A14B_SPEED_ARM_VERSIONS:
        spec = _spec(version)
        assert spec.governance_state == "experimental" and spec.is_experimental
        assert spec.pinned_revision == f"catalog:{WAN_A14B_ID}@{version}"
        assert "(Experimental)" in spec.display_name
        assert (
            spec.governance_notes.startswith("EXPERIMENTAL")
            and "NOT QUALIFIED" in spec.governance_notes
        )
        assert spec.backend_defaults["make_video_default"] is False
        with pytest.raises(KeyError, match="explicit experimental opt-in"):
            registry.get(WAN_A14B_ID, version)
    runnable = {
        (s.workflow_id, s.workflow_version) for s in registry.list_specs_for_backend("comfy")
    }
    assert (WAN_A14B_ID, WAN_A14B_VERSION) in runnable
    assert not runnable & {(WAN_A14B_ID, version) for version in WAN_A14B_SPEED_ARM_VERSIONS}


def test_the_approved_1_0_0_stays_the_picker_entry_for_its_id() -> None:
    registry = build_default_workflow_registry()
    a14b = [s for s in registry.list_offerable_specs("comfy") if s.workflow_id == WAN_A14B_ID]

    assert [s.workflow_version for s in latest_spec_per_workflow(a14b)] == [WAN_A14B_VERSION]
    controller = VideoWorkflowController(
        app_controller=SimpleNamespace(job_service=SimpleNamespace(), output_dir="out")
    )
    records = {r["workflow_id"]: r for r in controller.list_workflow_specs()}
    assert records[WAN_A14B_ID]["workflow_version"] == WAN_A14B_VERSION
    assert recommended_workflow_id(controller.list_workflow_specs()) == WAN_A14B_FULL_PICTURE_ID
    form = controller.build_default_form_state()
    assert (form["workflow_id"], form["workflow_version"]) == (
        WAN_A14B_FULL_PICTURE_ID,
        WAN_A14B_VERSION,
    )


@pytest.mark.parametrize("version", WAN_A14B_SPEED_ARM_VERSIONS)
def test_each_arm_shares_1_0_0s_runtime_frame_readiness_and_input_contract(version: str) -> None:
    base, arm = _spec(WAN_A14B_VERSION), _spec(version)

    for key in (
        "frame_count_policy",
        "output_policy",
        "runtime_policy",
        "resource_readiness",
        "source_preparation",
        "history_timeout_seconds",
        "default_negative_prompt",
        "workflow_family",
    ):
        assert arm.backend_defaults[key] == base.backend_defaults[key], key
    assert arm.backend_defaults["runtime_policy"]["required_launch_flags"] == [
        "--disable-pinned-memory"
    ]
    assert arm.backend_defaults["runtime_policy"]["keep_warm_between_jobs_seconds"] == 120
    assert arm.input_bindings == base.input_bindings
    assert arm.output_bindings == base.output_bindings


# --- one change per arm -----------------------------------------------------------------------


def _compiled(version: str, tmp_path: Path) -> dict[str, Any]:
    request = _a14b_request(tmp_path, version=version)
    return WorkflowCompiler().compile(_spec(version), request).backend_payload["prompt"]


def test_1_1_0_inserts_one_ck_attention_node_per_expert_before_model_sampling(
    tmp_path: Path,
) -> None:
    base, arm = _compiled(WAN_A14B_VERSION, tmp_path), _compiled(CK, tmp_path)

    assert _differences(base, arm) == {"17", "18", "5.inputs.model", "6.inputs.model"}
    assert arm["17"] == {
        "class_type": WAN_A14B_ATTENTION_NODE,
        "inputs": {"model": ["3", 0], "attention": WAN_A14B_CK_ATTENTION},
    }
    assert arm["18"] == {
        "class_type": WAN_A14B_ATTENTION_NODE,
        "inputs": {"model": ["4", 0], "attention": WAN_A14B_CK_ATTENTION},
    }
    assert (arm["5"]["inputs"]["model"], arm["6"]["inputs"]["model"]) == (["17", 0], ["18", 0])
    assert arm["3"]["class_type"] == arm["4"]["class_type"] == "LoraLoaderModelOnly"
    assert WAN_A14B_CK_ATTENTION == "comfy kitchen attention"


def test_1_1_0_needs_no_launch_flag_beyond_1_0_0s() -> None:
    manifest = json.loads(
        (ROOT / "config" / "managed_comfy_runtime.json").read_text(encoding="utf-8")
    )

    flags = _spec(CK).backend_defaults["runtime_policy"]["required_launch_flags"]
    assert "--use-ck-attention" not in flags
    assert "--use-ck-attention" not in json.dumps(manifest)


def test_1_2_0_loads_the_merged_experts_and_drops_the_lora_nodes(tmp_path: Path) -> None:
    base, arm = _compiled(WAN_A14B_VERSION, tmp_path), _compiled(MERGED, tmp_path)

    assert _differences(base, arm) == {
        "1.inputs.unet_name",
        "2.inputs.unet_name",
        "3",
        "4",
        "5.inputs.model",
        "6.inputs.model",
    }
    assert "3" not in arm and "4" not in arm
    assert arm["1"]["inputs"] == {
        "unet_name": "wan2.2_i2v_A14b_high_noise_scaled_fp8_e4m3_lightx2v_4step_comfyui.safetensors",
        "weight_dtype": "default",
    }
    assert arm["2"]["inputs"]["unet_name"] == (
        "wan2.2_i2v_A14b_low_noise_scaled_fp8_e4m3_lightx2v_4step_comfyui.safetensors"
    )
    assert (arm["5"]["inputs"]["model"], arm["6"]["inputs"]["model"]) == (["1", 0], ["2", 0])
    assert {node["class_type"] for node in arm.values()} == set(WAN_A14B_STOCK_NODES) - {
        "LoraLoaderModelOnly"
    }


def test_1_2_0_pins_the_merged_files_by_name_digest_size_and_revision() -> None:
    spec = _spec(MERGED)
    expected = {
        "wan2.2_i2v_A14b_high_noise_scaled_fp8_e4m3_lightx2v_4step_comfyui.safetensors": (
            "10125ab5c86167d3f3d4836e52b5317d611b98a1603d075b9e1f568843968d84"
        ),
        "wan2.2_i2v_A14b_low_noise_scaled_fp8_e4m3_lightx2v_4step_comfyui.safetensors": (
            "90444bc6fb98d693b8afc18a13a7a5c35f751c2b71252d73438ed0649633057b"
        ),
    }
    provenance = spec.backend_defaults["provenance"]
    shared = {name: digest for _i, name, _h, digest, _r, _v in WAN_A14B_MODEL_FILES[2:4]}

    assert provenance["files"] == {**expected, **shared}
    assert provenance["merged_experts_repo"] == "lightx2v/Wan2.2-Distill-Models"
    assert provenance["merged_experts_revision"] == "52699089e1dac804cbedd2400d0d2aea969577de"
    assert provenance["merged_experts_bytes"] == dict.fromkeys(expected, 15003000250)
    assert WAN_A14B_MERGED_FILE_BYTES == provenance["merged_experts_bytes"]
    assert provenance["license"] == "Apache-2.0"
    assert "lora_repo" not in provenance and "lora_revision" not in provenance
    files = {d.locator: d for d in spec.dependency_specs if d.dependency_kind == "model_file"}
    assert set(files) == set(expected) | set(shared)
    for name, digest in expected.items():
        assert files[name].version_hint == "UNETLoader.unet_name"
        assert digest[:16] in files[name].description and "526990" in files[name].description
    nodes = {d.locator for d in spec.dependency_specs if d.dependency_kind == "stock_node"}
    assert nodes == set(WAN_A14B_STOCK_NODES) - {"LoraLoaderModelOnly"}


def test_1_3_0_only_moves_the_text_encoder_to_the_default_device(tmp_path: Path) -> None:
    base, arm = _compiled(WAN_A14B_VERSION, tmp_path), _compiled(GPU_TE, tmp_path)

    assert _differences(base, arm) == {"7.inputs.device"}
    assert (base["7"]["inputs"]["device"], arm["7"]["inputs"]["device"]) == ("cpu", "default")
    spec = _spec(GPU_TE)
    assert "near pixel-identical" in spec.governance_notes
    assert spec.dependency_specs == _spec(WAN_A14B_VERSION).dependency_specs


# --- readiness knows the attention node and its option ----------------------------------------


def _info(
    version: str, *, attention_options: list[str] | None = None, combo: bool = False
) -> dict[str, Any]:
    spec = _spec(version)
    info: dict[str, Any] = {
        d.locator: {"input": {"required": {}}}
        for d in spec.dependency_specs
        if d.dependency_kind == "stock_node"
    }
    options: dict[tuple[str, str], list[str]] = {}
    for d in spec.dependency_specs:
        if d.dependency_kind == "model_file":
            loader, _, input_name = d.version_hint.partition(".")
            options.setdefault((loader, input_name), []).append(d.locator)
    for (loader, input_name), names in options.items():
        info[loader] = {"input": {"required": {input_name: [names]}}}
    if WAN_A14B_ATTENTION_NODE in info:
        listed = ["pytorch attention"] if attention_options is None else attention_options
        spec_value: list[Any] = ["COMBO", {"options": listed}] if combo else [listed]
        info[WAN_A14B_ATTENTION_NODE] = {
            "input": {"required": {"model": ["MODEL"], "attention": spec_value}}
        }
    return info


@pytest.mark.parametrize("combo", [False, True])
def test_1_1_0_is_ready_only_when_comfy_advertises_comfy_kitchen_attention(combo: bool) -> None:
    probe, spec = ComfyDependencyProbe(), _spec(CK)
    ready = _info(CK, attention_options=["pytorch attention", WAN_A14B_CK_ATTENTION], combo=combo)
    pytorch_only = _info(CK, attention_options=["pytorch attention"], combo=combo)
    no_node = _info(CK)
    del no_node[WAN_A14B_ATTENTION_NODE]

    assert probe.probe_workflow(spec, object_info=ready).ready
    refused = probe.probe_workflow(spec, object_info=pytorch_only)
    assert not refused.ready
    assert refused.missing_required == ("option_modelattentionbackend_comfy_kitchen_attention",)
    missing = probe.probe_workflow(spec, object_info=no_node)
    assert set(missing.missing_required) == {
        "node_modelattentionbackend",
        "option_modelattentionbackend_comfy_kitchen_attention",
    }


def test_the_other_versions_never_ask_for_the_attention_node() -> None:
    for version in (WAN_A14B_VERSION, MERGED, GPU_TE):
        spec = _spec(version)
        assert WAN_A14B_ATTENTION_NODE not in {d.locator for d in spec.dependency_specs}
        assert ComfyDependencyProbe().probe_workflow(spec, object_info=_info(version)).ready


def test_1_2_0_without_the_merged_files_refuses_before_any_queue_prompt(tmp_path: Path) -> None:
    info = _info(MERGED)
    info["UNETLoader"] = {"input": {"required": {"unet_name": [[]]}}}

    result = ComfyDependencyProbe().probe_workflow(_spec(MERGED), object_info=info)

    assert set(result.missing_required) == {
        "wan_a14b_merged_high_noise_unet",
        "wan_a14b_merged_low_noise_unet",
    }
    client = _FramesFake(tmp_path, save_node="16", info=info)
    with pytest.raises(RuntimeError, match="wan_a14b_merged_high_noise_unet"):
        _a14b_backend(client, tmp_path).execute(None, _a14b_request(tmp_path, version=MERGED))
    assert client.queued == []


def test_preflight_names_the_missing_attention_option() -> None:
    probes = SimpleNamespace(
        base_url="http://x",
        fetch_object_info=lambda _url: _info(CK, attention_options=["pytorch attention"]),
    )

    node_gate, file_gate, _info_payload = _dependency_gates(_spec(CK), probes, "healthy")

    assert node_gate.state == "blocked"
    assert "ModelAttentionBackend.attention 'comfy kitchen attention'" in node_gate.detail
    assert file_gate.state == "ok"


# --- jobs on a fake runtime -------------------------------------------------------------------


@pytest.mark.parametrize("version", WAN_A14B_SPEED_ARM_VERSIONS)
def test_an_arm_job_needs_the_per_job_opt_in(tmp_path: Path, version: str) -> None:
    info = _info(version, attention_options=["pytorch attention", WAN_A14B_CK_ATTENTION])
    client = _FramesFake(tmp_path, save_node="16", info=info)

    with pytest.raises(KeyError, match="explicit experimental opt-in"):
        _a14b_backend(client, tmp_path).execute(
            None, _a14b_request(tmp_path, version=version, opt_in=False)
        )
    assert client.queued == []


@pytest.mark.parametrize("version", WAN_A14B_SPEED_ARM_VERSIONS)
def test_an_opted_in_arm_job_completes_through_the_frames_out_path(
    tmp_path: Path, _no_encode, version: str
) -> None:
    info = _info(version, attention_options=["pytorch attention", WAN_A14B_CK_ATTENTION])
    client = _FramesFake(tmp_path, save_node="16", info=info)

    result = _a14b_backend(client, tmp_path).execute(None, _a14b_request(tmp_path, version=version))

    assert result is not None
    [queued] = client.queued
    expected = _compiled(version, tmp_path)
    # The source image is staged into Comfy's input folder, so only node 9's image name differs.
    assert _differences(expected, queued["prompt"]) == {"9.inputs.image"}
    assert result.to_variant_payload()["frames_out"]["reconciliation"]["status"] == "match"


def test_a_1_1_0_job_after_a_held_1_0_0_releases_the_process_instead_of_reusing_it(
    tmp_path: Path, _no_encode
) -> None:
    slot, _clock, _spawned = _slot()
    info = _info(CK, attention_options=["pytorch attention", WAN_A14B_CK_ATTENTION])
    client = _FramesFake(tmp_path, save_node="16", info=info, stats=_stats(free_mib=11800.0))
    first = _a14b_backend(client, tmp_path, warm_hold=slot)
    first_request = _a14b_request(tmp_path)
    first_request.output_dir = tmp_path / "run-1"
    first.execute(None, first_request)
    manager = first.fake_manager
    held_pid = manager.pid
    assert slot.snapshot()["key"] == [WAN_A14B_ID, WAN_A14B_VERSION]

    second = _a14b_backend(client, tmp_path, warm_hold=slot)
    second._process_manager = manager
    request = _a14b_request(tmp_path, version=CK)
    request.job_id = "job-2"
    request.output_dir = tmp_path / "run-2"
    result = second.execute(None, request)

    assert manager.stops == 1 and manager.starts == 2 and manager.pid != held_pid
    assert result.backend_metadata["runtime_reuse"]["status"] == "released"
    assert slot.snapshot()["key"] == [WAN_A14B_ID, CK]  # the new version holds its own process


# --- frame-count choices ----------------------------------------------------------------------


@pytest.mark.parametrize("version", ALL_VERSIONS)
def test_every_a14b_version_offers_17_to_121_frames_with_81_as_default(version: str) -> None:
    spec = _spec(version)

    assert legal_frame_counts(spec) == list(range(17, 122, 4))
    projection = frame_count_projection(spec)
    assert projection is not None
    assert projection["default"] == 81 and projection["advisory_above"] == 81
    assert projection["choices"][-1] == {"frames": 121, "seconds": 7.6}
    assert parse_frame_count(spec, "121") == 121 and parse_frame_count(spec, "") == 81
    with pytest.raises(ValueError, match="from 17 to 121"):
        parse_frame_count(spec, 125)
    with pytest.raises(ValueError):
        parse_frame_count(spec, 83)


def test_the_advisory_appears_only_above_81_frames() -> None:
    projection = frame_count_projection(_spec(WAN_A14B_VERSION))

    assert frame_count_advisory(projection, 81) == ""
    assert frame_count_advisory(projection, None) == ""
    text = frame_count_advisory(projection, 85)
    assert "longer run" in text and "RAM" in text and "loop back" in text
    assert frame_count_advisory(projection, 121) == text


def test_ti2v_keeps_its_spec_capped_lengths_and_no_advisory() -> None:
    projection = frame_count_projection(_spec(WAN22_FRAMES_VERSION, WAN_ID))

    assert projection is not None and projection["choices"][-1]["frames"] == 81
    assert "advisory_above" not in projection
    assert frame_count_advisory(projection, 81) == ""


def test_the_1_0_0_graph_is_unchanged_by_the_longer_lengths(tmp_path: Path) -> None:
    request = _a14b_request(tmp_path, frames=121)

    graph = WorkflowCompiler().compile(_spec(WAN_A14B_VERSION), request).backend_payload["prompt"]

    assert graph["10"]["inputs"]["length"] == 121


# --- the example eval suite -------------------------------------------------------------------


class _JobService:
    def __init__(self) -> None:
        self.calls: list[list[Any]] = []

    def submit_njrs(self, njrs, policy):
        self.calls.append(list(njrs))
        return [njr.job_id for njr in njrs]


def _materialize(tmp_path: Path) -> Path:
    data = json.loads(SUITE.read_text(encoding="utf-8"))
    suite_dir = tmp_path / "suite"
    for case in data["cases"]:
        image = suite_dir / case["image"]
        image.parent.mkdir(parents=True, exist_ok=True)
        size = (96, 64) if "landscape" in case["image"] else (64, 96)
        Image.new("RGB", size, (90, 60, 30)).save(image)
    path = suite_dir / "suite.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    return path


def test_the_speed_arm_suite_is_synthetic_and_names_the_baseline_and_three_arms() -> None:
    data = json.loads(SUITE.read_text(encoding="utf-8"))
    text = SUITE.read_text(encoding="utf-8")

    assert data["schema"] == "stablenew.video-eval-suite.v1"
    assert all(case["image"].startswith("images/synthetic_") for case in data["cases"])
    assert "\\" not in text and ":/" not in text and "C:" not in text
    assert len(data["cases"]) == 8
    tags = {tag for case in data["cases"] for tag in case["tags"]}
    assert {"rotation", "locomotion", "face", "gesture"} <= tags
    arms = {arm["arm_id"]: arm["form"] for arm in data["arms"]}
    assert data["baseline_arm"] == "a14b_base"
    assert arms["a14b_base"]["workflow_version"] == WAN_A14B_VERSION
    assert "experimental_opt_in" not in arms["a14b_base"]
    candidates = {
        arm_id: form["workflow_version"] for arm_id, form in arms.items() if arm_id != "a14b_base"
    }
    assert sorted(candidates.values()) == sorted(WAN_A14B_SPEED_ARM_VERSIONS)
    assert all(arms[arm_id]["experimental_opt_in"] is True for arm_id in candidates)
    assert {form["workflow_id"] for form in arms.values()} == {WAN_A14B_ID}
    assert {form["frame_count"] for form in arms.values()} == {81}


def test_the_speed_arm_suite_previews_32_jobs_and_admits_only_on_submit(tmp_path: Path) -> None:
    job_service = _JobService()
    app = SimpleNamespace(
        job_service=job_service,
        output_dir=str(tmp_path / "output"),
        sync_queue_state_after_direct_submission=lambda: None,
    )
    controller = VideoWorkflowController(app_controller=app)

    plan = controller.preview_eval_run(_materialize(tmp_path))

    assert plan.eligible, plan.summary()
    assert len(plan.jobs) == 32 and job_service.calls == []  # a preview admits nothing
    assert set(plan.experimental_arms) == {"a14b_ck_attention", "a14b_merged", "a14b_gpu_te"}
    by_cell = {(job.case_id, job.arm_id): job.njr.config["video_workflow"] for job in plan.jobs}
    for (_case_id, arm_id), config in by_cell.items():
        assert config["workflow_id"] == WAN_A14B_ID
        assert config["video_execution"]["experimental_opt_in"] is (arm_id != "a14b_base")
        assert config["seed"] == 374 and config["frame_count"] == 81 and config["fps"] == 16
    assert not (tmp_path / "output" / "video_eval").exists() or not any(
        (tmp_path / "output" / "video_eval").iterdir()
    )

    admission = controller.submit_eval_run(plan)

    assert len(job_service.calls) == 1 and len(job_service.calls[0]) == 32
    assert admission.manifest_path.is_file()


def test_the_merged_model_file_tuple_matches_the_catalog_constants() -> None:
    assert [entry[0] for entry in WAN_A14B_MERGED_MODEL_FILES] == [
        "wan_a14b_merged_high_noise_unet",
        "wan_a14b_merged_low_noise_unet",
        "wan_a14b_text_encoder",
        "wan_a14b_vae",
    ]
