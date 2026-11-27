"""VID-A14B-SVI-375: an experimental Wan2.2 I2V-A14B + SVI 2.0 workflow and multi-segment eval-kit cases.

Deterministic and GPU-free: a fake Comfy client and fake managed runtime, no model, process or generation.  It proves
the three SVI versions are registered, gated and pinned as declared, that each differs from the approved A14B graph
only by the SVI recipe (and from each other only by adapter file or CFG), that the reference pad is segment 0's
prepared source in every segment, that readiness and preflight know the ``ref_pad_image`` input, that sequence
admission accepts the workflow, and that an eval suite can run 3-segment cases rated as whole sequences.  It
demonstrates no quality, speed or resource envelope.
"""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from PIL import Image

from src.controller.video_workflow_controller import VideoWorkflowController
from src.pipeline.video_sequence_executor import apply_stage_overrides, segment_overrides
from src.video.comfy_dependency_probe import ComfyDependencyProbe
from src.video.comfy_workflow_backend import _sequence_ref_pad_hash
from src.video.sequence_admission import workflow_segment_errors
from src.video.sequence_plan import SegmentSpec, SequencePlan
from src.video.video_eval_identity import (
    Comparability,
    JobFacts,
    verify_cell_identity,
)
from src.video.video_eval_report import EvalReport, render_html
from src.video.video_eval_rubric import CATEGORY_KEYS
from src.video.video_eval_suite import EvalSuiteError, load_eval_suite
from src.video.workflow_catalog_wan_a14b import (
    WAN_A14B_HIGH_LORA,
    WAN_A14B_ID,
    WAN_A14B_LOW_LORA,
    WAN_A14B_MODEL_FILES,
    WAN_A14B_STOCK_NODES,
    WAN_A14B_VERSION,
)
from src.video.workflow_catalog_wan_a14b_svi import (
    ADAPTER_DERIVED,
    ADAPTER_KIJAI,
    WAN_A14B_SVI_ADAPTER_BYTES,
    WAN_A14B_SVI_ADAPTER_FILES,
    WAN_A14B_SVI_CFG1_VERSION,
    WAN_A14B_SVI_ID,
    WAN_A14B_SVI_KIJAI_VERSION,
    WAN_A14B_SVI_REF_PAD_SOURCE,
    WAN_A14B_SVI_VERSION,
    WAN_A14B_SVI_VERSIONS,
)
from src.video.workflow_compiler import WorkflowCompiler
from src.video.workflow_picker import recommended_workflow_id
from src.video.workflow_preflight import _dependency_gates
from src.video.workflow_registry import build_default_workflow_registry, latest_spec_per_workflow
from tests.video.test_vid_a14b_374_speed_arms import _differences
from tests.video.test_vid_clip_370_candidate_specs import (
    _a14b_backend,
    _a14b_request,
    _fake_export,
    _FramesFake,
)

ROOT = Path(__file__).resolve().parents[2]
SUITE = ROOT / "docs" / "runbooks" / "examples" / "video_eval_a14b_svi_sequence.suite.json"
DERIVED, KIJAI, CFG1 = WAN_A14B_SVI_VERSION, WAN_A14B_SVI_KIJAI_VERSION, WAN_A14B_SVI_CFG1_VERSION
DERIVED_SHA = {
    "SVI_Wan2.2-I2V-A14B_high_noise_lora_v2.0.comfy.safetensors": (
        "0367ad1b466e22e8c5bb44a358af3cd238c5976d90cc784e4b8795c22cd99ef6"
    ),
    "SVI_Wan2.2-I2V-A14B_low_noise_lora_v2.0.comfy.safetensors": (
        "9380636b55e5ca6cf6cd6a155c454d52c5f4f442fc1de3e15da70f7b5e0a17f2"
    ),
}
KIJAI_SHA = {
    "SVI_Wan2.2-I2V-A14B_lora_HIGH_v2.0_rank_128_fp16.safetensors": (
        "dc45a5b33282793c9eadef218167ea046684bef3cf2a593b205f06603375573c"
    ),
    "SVI_Wan2.2-I2V-A14B_lora_LOW_v2.0_rank_128_fp16.safetensors": (
        "403f0ad00fe692eea749c4211ed9db191c17c1059aa759b83557e18f08fe097b"
    ),
}


def _spec(version: str, workflow_id: str = WAN_A14B_SVI_ID):
    return build_default_workflow_registry().get(workflow_id, version, allow_experimental=True)


def _svi_request(tmp_path: Path, *, version: str = DERIVED, sequence_sha: str | None = None):
    request = _a14b_request(tmp_path, workflow_id=WAN_A14B_SVI_ID, version=version)
    prepared = tmp_path / "prepared_source.png"
    prepared.write_bytes(b"prepared")
    request.stage_config["source_preparation"]["prepared_image_path"] = str(prepared)
    if sequence_sha is not None:
        request.stage_config["sequence_metadata"] = {
            "source": {"path": str(prepared), "sha256": sequence_sha}
        }
    return request


def _compiled(version: str, tmp_path: Path, workflow_id: str = WAN_A14B_SVI_ID) -> dict[str, Any]:
    request = (
        _svi_request(tmp_path, version=version)
        if workflow_id == WAN_A14B_SVI_ID
        else _a14b_request(tmp_path, version=version)
    )
    return (
        WorkflowCompiler().compile(_spec(version, workflow_id), request).backend_payload["prompt"]
    )


def _svi_info(version: str, *, ref_pad: bool = True) -> dict[str, Any]:
    info = _base_info(version)
    inputs: dict[str, Any] = {"start_image": ["IMAGE"]}
    if ref_pad:
        inputs["ref_pad_image"] = ["IMAGE"]
    info["WanImageToVideo"] = {"input": {"required": {"vae": ["VAE"]}, "optional": inputs}}
    return info


def _base_info(version: str) -> dict[str, Any]:
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
    return info


@pytest.fixture
def _no_encode(monkeypatch):
    monkeypatch.setattr("src.video.frames_out.export_image_sequence_video", _fake_export)
    monkeypatch.setattr(
        "src.video.comfy_workflow_backend.write_video_container_metadata", lambda *_a, **_k: True
    )


# --- registration and governance --------------------------------------------------------------


def test_three_experimental_svi_versions_are_registered_and_need_the_opt_in() -> None:
    registry = build_default_workflow_registry()

    assert registry.list_versions(WAN_A14B_SVI_ID) == list(WAN_A14B_SVI_VERSIONS)
    assert WAN_A14B_SVI_VERSIONS == ("1.0.0", "1.1.0", "1.2.0")
    for version in WAN_A14B_SVI_VERSIONS:
        spec = _spec(version)
        assert spec.governance_state == "experimental" and spec.is_experimental
        assert spec.pinned_revision == f"catalog:{WAN_A14B_SVI_ID}@{version}"
        assert "(Experimental)" in spec.display_name
        assert spec.governance_notes.startswith("EXPERIMENTAL")
        assert "NOT QUALIFIED" in spec.governance_notes
        assert spec.backend_defaults["make_video_default"] is False
        with pytest.raises(KeyError, match="explicit experimental opt-in"):
            registry.get(WAN_A14B_SVI_ID, version)
    runnable = {s.workflow_id for s in registry.list_specs_for_backend("comfy")}
    assert WAN_A14B_SVI_ID not in runnable


def test_the_approved_a14b_stays_the_picker_default_and_its_versions_are_unchanged() -> None:
    registry = build_default_workflow_registry()

    assert registry.list_versions(WAN_A14B_ID) == ["1.0.0", "1.1.0", "1.2.0", "1.3.0", "1.4.0"]
    controller = VideoWorkflowController(
        app_controller=SimpleNamespace(job_service=SimpleNamespace(), output_dir="out")
    )
    assert recommended_workflow_id(controller.list_workflow_specs()) == WAN_A14B_ID
    form = controller.build_default_form_state()
    assert (form["workflow_id"], form["workflow_version"]) == (WAN_A14B_ID, WAN_A14B_VERSION)
    svi = [s for s in registry.list_offerable_specs("comfy") if s.workflow_id == WAN_A14B_SVI_ID]
    assert [s.workflow_version for s in latest_spec_per_workflow(svi)] == [CFG1]


@pytest.mark.parametrize("version", WAN_A14B_SVI_VERSIONS)
def test_svi_shares_the_approved_a14b_runtime_frame_and_readiness_policy(version: str) -> None:
    base, svi = _spec(WAN_A14B_VERSION, WAN_A14B_ID), _spec(version)

    for key in (
        "frame_count_policy",
        "output_policy",
        "runtime_policy",
        "resource_readiness",
        "source_preparation",
        "history_timeout_seconds",
        "default_negative_prompt",
        "transport",
    ):
        assert svi.backend_defaults[key] == base.backend_defaults[key], key
    assert svi.input_bindings[:-1] == base.input_bindings
    ref_pad = svi.input_bindings[-1]
    assert (ref_pad.binding_name, ref_pad.source_field, ref_pad.required) == (
        "ref_pad_image",
        WAN_A14B_SVI_REF_PAD_SOURCE,
        True,
    )
    assert WAN_A14B_SVI_REF_PAD_SOURCE == "stage_config.source_preparation.prepared_image_path"


# --- the graph ---------------------------------------------------------------------------------


def test_the_svi_graph_is_the_a14b_graph_plus_the_svi_recipe(tmp_path: Path) -> None:
    base = _compiled(WAN_A14B_VERSION, tmp_path, WAN_A14B_ID)
    svi = _compiled(DERIVED, tmp_path)

    assert _differences(base, svi) == {
        "3.inputs.strength_model",
        "5.inputs.model",
        "6.inputs.model",
        "10.inputs.ref_pad_image",
        "13.inputs.cfg",
        "14.inputs.cfg",
        "16.inputs.filename_prefix",
        "17",
        "20",
        "21",
    }
    assert svi["3"]["inputs"] == {
        "model": ["1", 0],
        "lora_name": WAN_A14B_HIGH_LORA,
        "strength_model": 0.5,
    }
    assert svi["4"]["inputs"]["lora_name"] == WAN_A14B_LOW_LORA
    assert svi["4"]["inputs"]["strength_model"] == 1.0
    assert svi["20"]["inputs"] == {
        "model": ["3", 0],
        "lora_name": "SVI_Wan2.2-I2V-A14B_high_noise_lora_v2.0.comfy.safetensors",
        "strength_model": 1.0,
    }
    assert svi["21"]["inputs"]["model"] == ["4", 0]
    assert svi["21"]["inputs"]["lora_name"] == (
        "SVI_Wan2.2-I2V-A14B_low_noise_lora_v2.0.comfy.safetensors"
    )
    assert (svi["5"]["inputs"]["model"], svi["6"]["inputs"]["model"]) == (["20", 0], ["21", 0])
    assert svi["13"]["inputs"]["cfg"] == svi["14"]["inputs"]["cfg"] == 1.5
    assert svi["10"]["inputs"]["ref_pad_image"] == ["17", 0]
    assert svi["17"] == {
        "class_type": "LoadImage",
        "inputs": {"image": str(tmp_path / "prepared_source.png")},
    }
    assert {node["class_type"] for node in svi.values()} == set(WAN_A14B_STOCK_NODES)


def test_the_kijai_version_changes_only_the_svi_adapter_files(tmp_path: Path) -> None:
    derived, kijai = _compiled(DERIVED, tmp_path), _compiled(KIJAI, tmp_path)

    assert _differences(derived, kijai) == {"20.inputs.lora_name", "21.inputs.lora_name"}
    assert kijai["20"]["inputs"]["lora_name"] == (
        "SVI_Wan2.2-I2V-A14B_lora_HIGH_v2.0_rank_128_fp16.safetensors"
    )
    assert kijai["21"]["inputs"]["lora_name"] == (
        "SVI_Wan2.2-I2V-A14B_lora_LOW_v2.0_rank_128_fp16.safetensors"
    )


def test_the_cfg_1_version_changes_only_the_cfg(tmp_path: Path) -> None:
    derived, cfg1 = _compiled(DERIVED, tmp_path), _compiled(CFG1, tmp_path)

    assert _differences(derived, cfg1) == {"13.inputs.cfg", "14.inputs.cfg"}
    assert cfg1["13"]["inputs"]["cfg"] == cfg1["14"]["inputs"]["cfg"] == 1.0


def test_a_later_segment_starts_from_the_carry_and_pads_with_segment_0s_source(
    tmp_path: Path,
) -> None:
    request = _svi_request(tmp_path)
    prepared = request.stage_config["source_preparation"]["prepared_image_path"]
    segment = SegmentSpec(
        index=2,
        seed=374,
        frame_count=81,
        workflow_id=WAN_A14B_SVI_ID,
        workflow_version=DERIVED,
        prompt="the person stops",
        negative_prompt="blurry",
        anchor_policy="carry_last_frame",
        overlap_frames=1,
    )
    plan = SequencePlan(
        sequence_id="s", stage="video_workflow", backend="comfy", fps=16, segments=(segment,)
    )
    request.stage_config = apply_stage_overrides(
        request.stage_config, segment_overrides(plan, segment), stage="video_workflow"
    )
    carried = tmp_path / "seg_01_last.png"
    carried.write_bytes(b"carry")
    request.input_image_path = carried

    graph = WorkflowCompiler().compile(_spec(DERIVED), request).backend_payload["prompt"]

    assert graph["9"]["inputs"]["image"] == str(carried)
    assert graph["17"]["inputs"]["image"] == prepared
    assert graph["13"]["inputs"]["noise_seed"] == 374


# --- pins, readiness and preflight --------------------------------------------------------------


@pytest.mark.parametrize(
    ("version", "expected"), [(DERIVED, DERIVED_SHA), (KIJAI, KIJAI_SHA), (CFG1, DERIVED_SHA)]
)
def test_each_version_pins_exactly_the_adapter_files_it_loads(
    version: str, expected: dict[str, str]
) -> None:
    spec = _spec(version)
    provenance = spec.backend_defaults["provenance"]
    shared = {name: digest for _i, name, _h, digest, _r, _v in WAN_A14B_MODEL_FILES}

    assert provenance["files"] == {**shared, **expected}
    assert provenance["svi_adapter_bytes"] == {
        name: WAN_A14B_SVI_ADAPTER_BYTES[name] for name in expected
    }
    files = {d.locator: d for d in spec.dependency_specs if d.dependency_kind == "model_file"}
    assert set(files) == set(shared) | set(expected)
    for name, digest in expected.items():
        assert files[name].version_hint == "LoraLoaderModelOnly.lora_name"
        assert digest[:16] in files[name].description
    if expected is KIJAI_SHA:
        assert provenance["svi_repo"] == "Kijai/WanVideo_comfy"
        assert provenance["svi_revision"] == "8260d429d19fd7a72304cad059160b95d843913f"
        assert "svi_official_originals" not in provenance
    else:
        assert provenance["svi_repo"] == "epfl-vita/svi-model"
        assert set(provenance["svi_official_originals"]) == {
            "SVI_Wan2.2-I2V-A14B_high_noise_lora_v2.0.safetensors",
            "SVI_Wan2.2-I2V-A14B_low_noise_lora_v2.0.safetensors",
        }
    assert {
        name: digest
        for adapter in (ADAPTER_DERIVED, ADAPTER_KIJAI)
        for _i, name, _h, digest, _r, _v in WAN_A14B_SVI_ADAPTER_FILES[adapter]
    } == {**DERIVED_SHA, **KIJAI_SHA}


@pytest.mark.parametrize("version", WAN_A14B_SVI_VERSIONS)
def test_readiness_needs_the_adapters_and_the_ref_pad_input(version: str) -> None:
    probe, spec = ComfyDependencyProbe(), _spec(version)

    assert probe.probe_workflow(spec, object_info=_svi_info(version)).ready
    old_build = probe.probe_workflow(spec, object_info=_svi_info(version, ref_pad=False))
    assert old_build.missing_required == ("input_wanimagetovideo_ref_pad_image",)
    no_adapters = _svi_info(version)
    no_adapters["LoraLoaderModelOnly"] = {
        "input": {"required": {"lora_name": [[WAN_A14B_HIGH_LORA, WAN_A14B_LOW_LORA]]}}
    }
    missing = probe.probe_workflow(spec, object_info=no_adapters)
    assert set(missing.missing_required) == {
        entry[0]
        for entry in WAN_A14B_SVI_ADAPTER_FILES[
            ADAPTER_KIJAI if version == KIJAI else ADAPTER_DERIVED
        ]
    }


def test_the_approved_a14b_never_asks_for_svi_files_or_the_ref_pad_input() -> None:
    spec = _spec(WAN_A14B_VERSION, WAN_A14B_ID)
    locators = {d.locator for d in spec.dependency_specs}

    assert "ref_pad_image" not in locators
    assert not locators & {*DERIVED_SHA, *KIJAI_SHA}


def test_preflight_names_the_missing_ref_pad_input() -> None:
    probes = SimpleNamespace(
        base_url="http://x", fetch_object_info=lambda _url: _svi_info(DERIVED, ref_pad=False)
    )

    node_gate, file_gate, _payload = _dependency_gates(_spec(DERIVED), probes, "healthy")

    assert node_gate.state == "blocked"
    assert "WanImageToVideo input 'ref_pad_image'" in node_gate.detail
    assert file_gate.state == "ok"


# --- the sequence path --------------------------------------------------------------------------


@pytest.mark.parametrize("version", WAN_A14B_SVI_VERSIONS)
def test_sequence_admission_accepts_svi_only_with_the_jobs_opt_in(version: str) -> None:
    spec = _spec(version)

    assert workflow_segment_errors(spec, spec, 81, 16, experimental_opt_in=True) == []
    refused = workflow_segment_errors(spec, spec, 81, 16, experimental_opt_in=False)
    assert any("has not opted in" in problem for problem in refused)


def test_the_backend_checks_the_ref_pad_against_the_sequence_source_hash(tmp_path: Path) -> None:
    request = _svi_request(tmp_path, sequence_sha="a" * 64)
    prepared = request.stage_config["source_preparation"]["prepared_image_path"]

    assert _sequence_ref_pad_hash(_spec(DERIVED), request.stage_config) == (prepared, "a" * 64)
    assert _sequence_ref_pad_hash(_spec(DERIVED), _svi_request(tmp_path).stage_config) is None
    assert (
        _sequence_ref_pad_hash(_spec(WAN_A14B_VERSION, WAN_A14B_ID), request.stage_config) is None
    )


class _UploadRecorder(_FramesFake):
    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.uploads: list[tuple[str, str | None]] = []

    def upload_image(self, path, **kwargs):
        self.uploads.append((Path(path).name, kwargs.get("expected_sha256")))
        return super().upload_image(path, **kwargs)


def test_an_opted_in_svi_segment_uploads_the_carry_and_the_hash_checked_ref_pad(
    tmp_path: Path, _no_encode
) -> None:
    client = _UploadRecorder(tmp_path, save_node="16", info=_svi_info(DERIVED))
    request = _svi_request(tmp_path, sequence_sha="b" * 64)

    result = _a14b_backend(client, tmp_path).execute(None, request)

    assert result is not None
    [queued] = client.queued
    assert queued["prompt"]["17"]["inputs"]["image"] == "prepared_source.png"
    assert queued["prompt"]["9"]["inputs"]["image"] == "source.png"
    assert ("prepared_source.png", "b" * 64) in client.uploads


def test_an_svi_job_without_the_opt_in_queues_nothing(tmp_path: Path) -> None:
    client = _FramesFake(tmp_path, save_node="16", info=_svi_info(DERIVED))
    request = _svi_request(tmp_path)
    request.experimental_opt_in = False

    with pytest.raises(KeyError, match="explicit experimental opt-in"):
        _a14b_backend(client, tmp_path).execute(None, request)
    assert client.queued == []


# --- the eval kit: sequence cases ---------------------------------------------------------------


class _JobService:
    def __init__(self) -> None:
        self.calls: list[list[Any]] = []

    def submit_njrs(self, njrs, policy):
        self.calls.append(list(njrs))
        return [njr.job_id for njr in njrs]


def _materialize(tmp_path: Path, data: dict[str, Any] | None = None) -> Path:
    data = data if data is not None else json.loads(SUITE.read_text(encoding="utf-8"))
    suite_dir = tmp_path / "suite"
    for case in data["cases"]:
        image = suite_dir / case["image"]
        image.parent.mkdir(parents=True, exist_ok=True)
        size = (96, 64) if "landscape" in case["image"] else (64, 96)
        Image.new("RGB", size, (90, 60, 30)).save(image)
    path = suite_dir / "suite.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    return path


def _controller(tmp_path: Path, job_service: _JobService) -> VideoWorkflowController:
    app = SimpleNamespace(
        job_service=job_service,
        output_dir=str(tmp_path / "output"),
        sync_queue_state_after_direct_submission=lambda: None,
    )
    return VideoWorkflowController(app_controller=app)


def test_the_svi_suite_is_synthetic_and_names_the_baseline_and_three_svi_arms() -> None:
    data = json.loads(SUITE.read_text(encoding="utf-8"))
    text = SUITE.read_text(encoding="utf-8")

    assert data["schema"] == "stablenew.video-eval-suite.v1"
    assert all(case["image"].startswith("images/synthetic_") for case in data["cases"])
    assert "\\" not in text and ":/" not in text and "C:" not in text
    assert 6 <= len(data["cases"]) <= 8
    assert all(len(case["segments"]) == 3 and "prompt" not in case for case in data["cases"])
    assert isinstance(data["seed"], int)
    arms = {arm["arm_id"]: arm["form"] for arm in data["arms"]}
    assert data["baseline_arm"] == "plain_carry"
    assert (arms["plain_carry"]["workflow_id"], arms["plain_carry"]["workflow_version"]) == (
        WAN_A14B_ID,
        WAN_A14B_VERSION,
    )
    assert "experimental_opt_in" not in arms["plain_carry"]
    assert {
        arm_id: (form["workflow_id"], form["workflow_version"])
        for arm_id, form in arms.items()
        if arm_id != "plain_carry"
    } == {
        "svi_derived": (WAN_A14B_SVI_ID, DERIVED),
        "svi_kijai": (WAN_A14B_SVI_ID, KIJAI),
        "svi_derived_cfg1": (WAN_A14B_SVI_ID, CFG1),
    }
    assert all(
        form.get("experimental_opt_in") is True for a, form in arms.items() if a != "plain_carry"
    )
    assert {form["frame_count"] for form in arms.values()} == {81}


def test_the_svi_suite_previews_one_sequence_job_per_case_and_arm(tmp_path: Path) -> None:
    job_service = _JobService()
    controller = _controller(tmp_path, job_service)
    data = json.loads(SUITE.read_text(encoding="utf-8"))
    seed = data["seed"]

    plan = controller.preview_eval_run(_materialize(tmp_path))

    assert plan.eligible, plan.summary()
    assert len(plan.jobs) == len(data["cases"]) * 4 and job_service.calls == []
    assert set(plan.experimental_arms) == {"svi_derived", "svi_kijai", "svi_derived_cfg1"}
    assert "multi-segment sequences" in plan.summary()
    for job in plan.jobs:
        config = job.njr.config["video_workflow"]
        segments = config["sequence_metadata"]["segments"]
        assert [item["seed"] for item in segments] == [seed, seed + 1, seed + 2]
        assert job.segment_seeds == (seed, seed + 1, seed + 2) and job.seed == seed
        assert job.frame_count == 243
        assert config["video_execution"]["experimental_opt_in"] is (job.arm_id != "plain_carry")
        case = next(c for c in data["cases"] if c["case_id"] == job.case_id)
        assert [item["prompt"] for item in segments] == [s["prompt"] for s in case["segments"]]
        assert config["prompt"] == case["segments"][0]["prompt"]

    admission = controller.submit_eval_run(plan)

    assert len(job_service.calls) == 1 and len(job_service.calls[0]) == len(plan.jobs)
    manifest = json.loads(admission.manifest_path.read_text(encoding="utf-8"))
    assert all(len(case["segments"]) == 3 for case in manifest["cases"])
    assert all(job["segment_seeds"] == [seed, seed + 1, seed + 2] for job in manifest["jobs"])
    assert all(job["frame_count"] == 243 for job in manifest["jobs"])


def _one_case_suite(
    case: dict[str, Any], arms: list[dict[str, Any]] | None = None
) -> dict[str, Any]:
    return {
        "schema": "stablenew.video-eval-suite.v1",
        "suite_id": "seq-test",
        "seed": 5,
        "cases": [{"case_id": "c1", "image": "images/a.png", **case}],
        "arms": arms
        or [
            {
                "arm_id": "a",
                "backend": "video_workflow",
                "form": {"workflow_id": WAN_A14B_ID, "frame_count": 81},
            }
        ],
    }


@pytest.mark.parametrize(
    ("case", "arms", "message"),
    [
        ({"segments": [{"prompt": "one"}]}, None, "2-12 segments"),
        (
            {"prompt": "p", "segments": [{"prompt": "a"}, {"prompt": "b"}]},
            None,
            "not a case 'prompt'",
        ),
        ({"segments": [{"prompt": "a"}, {"prompt": ""}]}, None, "segment 2: 'prompt' is required"),
        ({"segments": [{"prompt": "a"}, {"prompt": "b", "seed": 3}]}, None, "unknown field"),
        (
            {"segments": [{"prompt": "a"}, {"prompt": "b"}]},
            [{"arm_id": "s", "backend": "svd_native", "svd": {}}],
            "sequence cases run as Video Workflow sequences",
        ),
    ],
)
def test_the_suite_loader_refuses_malformed_sequence_cases(
    tmp_path: Path, case: dict[str, Any], arms: list[dict[str, Any]] | None, message: str
) -> None:
    with pytest.raises(EvalSuiteError, match=message):
        load_eval_suite(_materialize(tmp_path, _one_case_suite(case, arms)))


def test_a_sequence_case_can_set_per_segment_lengths(tmp_path: Path) -> None:
    case = {"segments": [{"prompt": "a", "frame_count": 49}, {"prompt": "b"}]}
    controller = _controller(tmp_path, _JobService())

    plan = controller.preview_eval_run(_materialize(tmp_path, _one_case_suite(case)))

    assert plan.eligible, plan.summary()
    [job] = plan.jobs
    assert [
        s["frame_count"] for s in job.njr.config["video_workflow"]["sequence_metadata"]["segments"]
    ] == [49, 81]
    assert job.frame_count == 130 and job.segment_seeds == (5, 6)


def _identity(facts: JobFacts, *, seeds: list[int] | None = None, case_segments: Any = "default"):
    segments = [{"prompt": "a"}, {"prompt": "b"}] if case_segments == "default" else case_segments
    case = {"case_id": "c1", "image": "/x/a.png", "prompt": "a"}
    if segments is not None:
        case["segments"] = segments
    job = {"job_id": "j1", "seed": 5, **({"segment_seeds": seeds} if seeds is not None else {})}
    return verify_cell_identity(
        facts=facts,
        job=job,
        case=case,
        arm={"backend": "video_workflow"},
        suite_seed=5,
        source=None,
    )


def _facts(segments: Any) -> JobFacts:
    return JobFacts("j1", "video_workflow", 5, "/x/a.png", "a", segments=segments)


def test_a_sequence_pair_is_verified_only_when_every_segment_matches() -> None:
    assert _identity(_facts((("a", 5), ("b", 6))), seeds=[5, 6]).status is Comparability.VERIFIED
    wrong_seed = _identity(_facts((("a", 5), ("b", 9))), seeds=[5, 6])
    assert wrong_seed.status is Comparability.INCOMPARABLE
    assert "seed 9 for segment 2" in " ".join(wrong_seed.findings)
    wrong_prompt = _identity(_facts((("a", 5), ("c", 6))), seeds=[5, 6])
    assert "different prompt for segment 2" in " ".join(wrong_prompt.findings)
    assert _identity(_facts((("a", 5),)), seeds=[5, 6]).status is Comparability.INCOMPARABLE
    assert _identity(_facts(None), seeds=[5, 6]).status is Comparability.INCOMPARABLE
    single_case = _identity(_facts((("a", 5), ("b", 6))), case_segments=None)
    assert "case is a single clip" in " ".join(single_case.findings)
    unpinned = _identity(_facts((("a", 5), ("b", 6))))
    assert unpinned.status is Comparability.NOT_FULLY_VERIFIED


def test_the_report_marks_a_sequence_case_and_the_rubric_has_a_seam_category() -> None:
    report = EvalReport(
        run_dir=Path("run"),
        manifest={
            "run_id": "r",
            "suite": {"seed": 5, "baseline_arm": "a"},
            "arms": [{"arm_id": "a", "label": "A", "backend": "video_workflow"}],
            "cases": [
                {"case_id": "c1", "prompt": "a", "segments": [{"prompt": "a"}, {"prompt": "b <b>"}]}
            ],
        },
    )

    page = render_html(report, show_prompts=True)
    hidden = render_html(report, show_prompts=False)

    assert "2-segment sequence: rate the whole assembled clip" in page
    assert "b &lt;b&gt;" in page and "b &lt;b&gt;" not in hidden
    assert "segment_seam" in CATEGORY_KEYS
