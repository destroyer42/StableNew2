"""PR-VID-192: Animate-2 controls are the ones the pinned runtime actually honors.

Fakes only: no GPU, model, network or real process.  The pinned-runtime parity test additionally
reads the real ComfyUI v0.37.0 node source when ``STABLENEW_VID184_COMFY_SOURCE`` points at it
(skipped elsewhere).
"""

from __future__ import annotations

import hashlib
import json
import os
import re
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from src.controller.video_workflow_controller import VideoWorkflowController
from src.pipeline.replay_engine import ReplayEngine
from src.pipeline.result_contract_v26 import collect_canonical_artifacts
from src.queue.job_model import JobStatus
from src.video.video_workflow_intent import form_visibility
from src.video.workflow_catalog_wan_animate2 import (
    WAN_ANIMATE2_BASELINE_VERSION,
    WAN_ANIMATE2_CONTROLS_VERSION,
    WAN_ANIMATE2_DRIVE_ID,
    WAN_ANIMATE2_PROMPT_ID,
    build_wan_animate2_specs,
)
from src.video.workflow_compiler import WorkflowCompiler
from src.video.workflow_controls import (
    control_defaults,
    operator_controls,
    operator_controls_projection,
    resolve_operator_controls,
)
from src.video.workflow_registry import build_default_workflow_registry
from tests.integration.test_pr_vid_120_neutral_video_queue import _build_stack
from tests.video.test_pr_vid_190_wan_animate2 import (
    _AnimateComfy,
    _backend,
    _capture,
    _driving_clip,
    _ManagedFake,
    _reference,
)

COMFY_SOURCE = os.environ.get("STABLENEW_VID184_COMFY_SOURCE", "")
# sha256 of json.dumps(spec.to_dict(), sort_keys=True, ensure_ascii=False, default=str) at PR-VID-191
# (bc10a66).  The 1.0.0 specs must stay identical so PR-VID-191 jobs replay against the same graph.
BASELINE_SPEC_SHA256 = {
    WAN_ANIMATE2_PROMPT_ID: "fa3eed00ba5ce134f2f7fab4ce9c94abbc60f7de05efecb6bd3fc8b1206fceac",
    WAN_ANIMATE2_DRIVE_ID: "e92757007f29bff27bd0c84c829c68fb8f934b11e6181b705b75d1f03cdf3510",
}
APPEARANCE = "Character appearance description: a young woman in a navy top. Background: pale studio."
MOTION = "A person performs a slow side step, then raises one arm and waves."


def _spec(workflow_id: str, version: str = WAN_ANIMATE2_CONTROLS_VERSION):
    return build_default_workflow_registry().get(workflow_id, version, allow_experimental=True)


def _form(workflow_id: str, **overrides: Any) -> dict[str, Any]:
    form = {
        "workflow_id": workflow_id,
        "workflow_version": WAN_ANIMATE2_CONTROLS_VERSION,
        "prompt": APPEARANCE,
        "negative_prompt": "",
        "experimental_opt_in": True,
    }
    form.update(overrides)
    return form


def _run_jobs(tmp_path: Path, forms: list[dict[str, Any]]):
    manager = _ManagedFake()
    client = _AnimateComfy(tmp_path)
    repository, queue, service, _ = _build_stack(tmp_path, [_backend(client, manager)])
    app = SimpleNamespace(job_service=service, output_dir=str(tmp_path / "output"))
    controller = VideoWorkflowController(app_controller=app)
    try:
        job_ids = [
            controller.submit_video_workflow_job(
                source_image_path=_reference(tmp_path), form_data=form
            )
            for form in forms
        ]
        for job_id in job_ids:
            service.runner.run_once(queue.get_job(job_id))
        done = [repository.get_job(job_id) for job_id in job_ids]
        assert [job.status for job in done] == [JobStatus.COMPLETED] * len(forms)
        return client, done, manager
    finally:
        service.runner.stop()
        repository.close()


def _manifest(job) -> dict[str, Any]:
    [artifact] = collect_canonical_artifacts(job.result)
    manifests = list(Path(artifact["primary_path"]).parent.glob("manifests/*.json"))
    assert len(manifests) == 1
    return json.loads(manifests[0].read_text(encoding="utf-8"))


# ------------------------------------------------------------- identity / versions


def test_baseline_versions_are_byte_identical_to_pr_vid_191() -> None:
    for spec in build_wan_animate2_specs():
        if spec.workflow_version != WAN_ANIMATE2_BASELINE_VERSION:
            continue
        digest = hashlib.sha256(
            json.dumps(spec.to_dict(), sort_keys=True, ensure_ascii=False, default=str).encode(
                "utf-8"
            )
        ).hexdigest()
        assert digest == BASELINE_SPEC_SHA256[spec.workflow_id], spec.workflow_id


def test_both_versions_stay_registered_and_the_ui_offers_only_the_latest() -> None:
    registry = build_default_workflow_registry()
    for workflow_id in (WAN_ANIMATE2_PROMPT_ID, WAN_ANIMATE2_DRIVE_ID):
        assert registry.list_versions(workflow_id) == ["1.0.0", "1.1.0"]
    listed = {
        record["workflow_id"]: record["workflow_version"]
        for record in VideoWorkflowController(app_controller=SimpleNamespace()).list_workflow_specs()
    }
    assert listed[WAN_ANIMATE2_PROMPT_ID] == listed[WAN_ANIMATE2_DRIVE_ID] == "1.1.0"


# ------------------------------------------------------------- `gentle` never affected Animate-2


@pytest.mark.parametrize("workflow_id", [WAN_ANIMATE2_PROMPT_ID, WAN_ANIMATE2_DRIVE_ID])
@pytest.mark.parametrize("version", ["1.0.0", "1.1.0"])
def test_generic_motion_profile_is_never_declared_or_visible_for_animate2(
    workflow_id: str, version: str
) -> None:
    spec = _spec(workflow_id, version)
    assert "motion_profile" not in spec.declared_input_names
    assert form_visibility(spec)["motion_profile"] is False
    assert "motion_profile" not in json.dumps(spec.backend_defaults["prompt_template"])


def test_a_stray_generic_motion_value_never_enters_the_njr_or_the_comfy_graph(tmp_path) -> None:
    clip = _driving_clip(tmp_path)
    forms = [
        _form(WAN_ANIMATE2_PROMPT_ID, motion_profile="gentle"),
        _form(WAN_ANIMATE2_DRIVE_ID, motion_profile="gentle", pose_video_path=str(clip)),
    ]
    controller, submitted = _capture(tmp_path)
    for form in forms:
        controller.submit_video_workflow_job(source_image_path=_reference(tmp_path), form_data=form)
    for record in submitted:
        extra = record.stage_chain[0].to_dict()["extra"]
        assert "motion_profile" not in extra
        assert "gentle" not in json.dumps(record.to_queue_snapshot(), default=str)
    client, _done, _manager = _run_jobs(tmp_path, forms)
    for payload in client.queued:
        assert "motion_profile" not in json.dumps(payload["prompt"])
        assert "gentle" not in json.dumps(payload["prompt"])


# ------------------------------------------------------------- exact graph mapping


def test_drive_controls_map_to_the_exact_pinned_node_inputs(tmp_path) -> None:
    clip = _driving_clip(tmp_path)
    form = _form(
        WAN_ANIMATE2_DRIVE_ID,
        pose_video_path=str(clip),
        operator_controls={
            "pose_prompt": MOTION,
            "pose_strength": "1.7",
            "pose_start_percent": "0.1",
            "pose_end_percent": "0.8",
            "reference_image_strength": "1.2",
        },
    )
    client, _done, _manager = _run_jobs(tmp_path, [form])
    graph = client.queued[0]["prompt"]
    animate = graph["10"]["inputs"]

    # appearance/background and motion prompts are distinct nodes
    assert graph["5"]["inputs"]["text"] == APPEARANCE
    assert graph["23"] == {
        "class_type": "CLIPTextEncode",
        "inputs": {"text": MOTION, "clip": ["2", 0]},
    }
    assert animate["positive"] == ["5", 0] and animate["positive_pose"] == ["23", 0]
    # numeric controls are real, typed node inputs
    assert animate["pose_strength"] == 1.7
    assert animate["pose_start_percent"] == 0.1
    assert animate["pose_end_percent"] == 0.8
    assert animate["reference_image_strength"] == 1.2
    # everything else stays as qualified
    assert animate["video_frame_offset"] == 0 and animate["length"] == 41
    assert graph["13"]["inputs"]["cfg"] == 1.0 and "WanAnimate2Cache" not in json.dumps(graph)


def test_an_empty_motion_prompt_is_frozen_explicitly_as_the_appearance_prompt(tmp_path) -> None:
    clip = _driving_clip(tmp_path)
    form = _form(WAN_ANIMATE2_DRIVE_ID, pose_video_path=str(clip), operator_controls={})
    controller, submitted = _capture(tmp_path)
    controller.submit_video_workflow_job(source_image_path=_reference(tmp_path), form_data=form)
    frozen = submitted[0].stage_chain[0].to_dict()["extra"]["operator_controls"]
    assert frozen["pose_prompt"] == APPEARANCE  # the node's own default, now explicit
    assert frozen["pose_strength"] == 1.0 and frozen["reference_image_strength"] == 1.0
    assert (frozen["pose_start_percent"], frozen["pose_end_percent"]) == (0.0, 1.0)


def test_prompt_mode_exposes_only_the_control_that_is_real_without_a_pose_video(tmp_path) -> None:
    spec = _spec(WAN_ANIMATE2_PROMPT_ID)
    assert [c["name"] for c in operator_controls(spec)] == ["reference_image_strength"]
    client, _done, _manager = _run_jobs(
        tmp_path,
        [_form(WAN_ANIMATE2_PROMPT_ID, operator_controls={"reference_image_strength": "0.8"})],
    )
    graph = client.queued[0]["prompt"]
    animate = graph["10"]["inputs"]
    assert animate["reference_image_strength"] == 0.8
    assert "positive_pose" not in animate and "pose_video" not in animate and "23" not in graph
    # the pose knobs stay literal defaults: the pinned node skips the pose branch without a video
    assert (animate["pose_strength"], animate["pose_start_percent"]) == (1.0, 0.0)
    controller, _submitted = _capture(tmp_path)
    ok, reason = controller.validate_form_data(
        _form(WAN_ANIMATE2_PROMPT_ID, operator_controls={"pose_strength": "2"})
    )
    assert not ok and "does not accept the control" in reason


def test_prompt_mode_is_described_honestly_and_drive_mode_relabels_the_prompt() -> None:
    prompt_spec, drive_spec = _spec(WAN_ANIMATE2_PROMPT_ID), _spec(WAN_ANIMATE2_DRIVE_ID)
    assert "subtle" in prompt_spec.display_name.lower()
    assert "no driving video" in prompt_spec.description
    assert "exploratory" in prompt_spec.description
    assert prompt_spec.backend_defaults["operator_projection"]["prompt_label"] == "Prompt"
    label = drive_spec.backend_defaults["operator_projection"]["prompt_label"]
    assert label == "Appearance / Background Prompt"
    fixed = drive_spec.backend_defaults["operator_projection"]["fixed_settings"]
    assert "cfg 1.0" in fixed["negative_prompt_effect"]


# ------------------------------------------------------------- defaults equal the pinned node's


def test_control_defaults_and_ranges_equal_the_declared_pinned_node_values() -> None:
    assert control_defaults(_spec(WAN_ANIMATE2_DRIVE_ID)) == {
        "pose_strength": 1.0,
        "pose_start_percent": 0.0,
        "pose_end_percent": 1.0,
        "reference_image_strength": 1.0,
    }
    ranges = {c["name"]: (c["minimum"], c["maximum"]) for c in operator_controls(_spec(WAN_ANIMATE2_DRIVE_ID)) if c["kind"] == "number"}
    assert ranges == {
        "pose_strength": (0.0, 10.0),
        "pose_start_percent": (0.0, 1.0),
        "pose_end_percent": (0.0, 1.0),
        "reference_image_strength": (0.0, 10.0),
    }


@pytest.mark.skipif(
    not COMFY_SOURCE or not (Path(COMFY_SOURCE) / "comfy_extras" / "nodes_wan.py").is_file(),
    reason="set STABLENEW_VID184_COMFY_SOURCE to the pinned ComfyUI v0.37.0 source",
)
def test_controls_match_the_pinned_comfyui_node_schema() -> None:
    source = (Path(COMFY_SOURCE) / "comfy_extras" / "nodes_wan.py").read_text(encoding="utf-8")
    block = source[source.index("class WanAnimate2ToVideo") : source.index("class WanAnimate2Cache")]
    for optional in ("positive_pose", "continue_motion", "video_frame_offset"):
        assert f'"{optional}"' in block
    for control in operator_controls(_spec(WAN_ANIMATE2_DRIVE_ID)):
        if control["kind"] != "number":
            continue
        match = re.search(
            rf'io\.Float\.Input\("{control["name"]}", default=([\d.]+), min=([\d.]+), max=([\d.]+)',
            block,
        )
        assert match, control["name"]
        assert tuple(float(v) for v in match.groups()) == (
            control["default"],
            control["minimum"],
            control["maximum"],
        )


# ------------------------------------------------------------- validation / boundaries


@pytest.mark.parametrize(
    "controls, fragment",
    [
        ({"pose_strength": "abc"}, "must be a number"),
        ({"pose_strength": "11"}, "between 0 and 10"),
        ({"pose_strength": "-0.5"}, "between 0 and 10"),
        ({"reference_image_strength": "nan"}, "between 0 and 10"),
        ({"pose_start_percent": "1.5"}, "between 0 and 1"),
        ({"pose_start_percent": "0.9", "pose_end_percent": "0.2"}, "must not be greater"),
        ({"unknown_knob": "1"}, "does not accept the control"),
    ],
)
def test_invalid_controls_are_rejected_before_admission(tmp_path, controls, fragment) -> None:
    clip = _driving_clip(tmp_path)
    controller, submitted = _capture(tmp_path)
    ok, reason = controller.validate_form_data(
        _form(WAN_ANIMATE2_DRIVE_ID, pose_video_path=str(clip), operator_controls=controls)
    )
    assert not ok and fragment in reason
    assert submitted == []


def test_other_video_workflows_do_not_gain_animate2_controls() -> None:
    registry = build_default_workflow_registry()
    ti2v = registry.get("wan22_ti2v_5b_i2v_v1", "1.1.0", allow_experimental=True)
    assert operator_controls_projection(ti2v) is None
    assert resolve_operator_controls(ti2v, {}) is None
    with pytest.raises(ValueError, match="does not accept workflow controls"):
        resolve_operator_controls(ti2v, {"operator_controls": {"pose_strength": "2"}})
    assert all(
        record["operator_controls"] is None
        for record in VideoWorkflowController(app_controller=SimpleNamespace()).list_workflow_specs()
        if not record["workflow_id"].startswith("wan_animate2")
    )


def test_the_controller_builds_no_backend_payload_for_these_controls() -> None:
    source = Path("src/controller/video_workflow_controller.py").read_text(encoding="utf-8")
    for forbidden in ("positive_pose", "prompt_template", "CLIPTextEncode", "WanAnimate2"):
        assert forbidden not in source


# ------------------------------------------------------------- provenance / replay


def test_every_effective_control_reaches_the_manifest_and_a_replayed_njr(tmp_path) -> None:
    clip = _driving_clip(tmp_path)
    form = _form(
        WAN_ANIMATE2_DRIVE_ID,
        pose_video_path=str(clip),
        seed="424242",
        operator_controls={
            "pose_prompt": MOTION,
            "pose_strength": "1.3",
            "pose_start_percent": "0.05",
            "pose_end_percent": "0.9",
            "reference_image_strength": "1.1",
        },
    )
    controller, submitted = _capture(tmp_path)
    controller.submit_video_workflow_job(source_image_path=_reference(tmp_path), form_data=form)
    record = submitted[0]
    expected = {
        "pose_prompt": MOTION,
        "pose_strength": 1.3,
        "pose_start_percent": 0.05,
        "pose_end_percent": 0.9,
        "reference_image_strength": 1.1,
    }
    assert record.stage_chain[0].to_dict()["extra"]["operator_controls"] == expected
    assert record.extra_metadata["video_workflow"]["operator_controls"] == expected

    client, done, _manager = _run_jobs(tmp_path, [form])
    manifest = _manifest(done[0])
    assert manifest["operator_controls"] == expected
    control_record = manifest["control_record"]
    assert control_record["operator_controls"] == expected
    assert control_record["seed"] == 424242 and control_record["prompt"] == APPEARANCE
    assert control_record["pose_video"]["sha256"] == hashlib.sha256(clip.read_bytes()).hexdigest()
    reference_sha = control_record["source_image"]["sha256"]
    assert isinstance(reference_sha, str) and len(reference_sha) == 64
    workflow = control_record["workflow"]
    assert workflow["workflow_id"] == WAN_ANIMATE2_DRIVE_ID
    assert workflow["workflow_version"] == WAN_ANIMATE2_CONTROLS_VERSION
    assert workflow["comfyui_version"] == "0.37.0" and workflow["qualified_graph_sha256"]

    # replay: snapshot -> hydrate keeps every control, and compiles to the identical graph
    hydrated = ReplayEngine(SimpleNamespace(run_njr=lambda *a, **k: None))._hydrate_njr(
        record.to_queue_snapshot()
    )
    assert hydrated is not None
    assert hydrated.stage_chain[0].to_dict()["extra"]["operator_controls"] == expected
    graph = client.queued[0]["prompt"]["10"]["inputs"]
    assert (graph["pose_strength"], graph["pose_end_percent"]) == (1.3, 0.9)


def test_prompt_jobs_without_controls_or_driving_video_add_no_control_record(tmp_path) -> None:
    _client, done, _manager = _run_jobs(
        tmp_path, [{**_form(WAN_ANIMATE2_PROMPT_ID), "workflow_version": "1.0.0"}]
    )
    manifest = _manifest(done[0])
    assert "control_record" not in manifest and "operator_controls" not in manifest


def test_the_baseline_1_0_0_drive_job_still_runs_with_the_unconnected_pose_prompt(tmp_path) -> None:
    clip = _driving_clip(tmp_path)
    form = {
        **_form(WAN_ANIMATE2_DRIVE_ID, pose_video_path=str(clip)),
        "workflow_version": WAN_ANIMATE2_BASELINE_VERSION,
    }
    client, _done, _manager = _run_jobs(tmp_path, [form])
    animate = client.queued[0]["prompt"]["10"]["inputs"]
    assert "positive_pose" not in animate and "23" not in client.queued[0]["prompt"]


def test_driving_video_hash_stays_admission_frozen_for_the_controlled_workflow(tmp_path) -> None:
    clip = _driving_clip(tmp_path)
    controller, submitted = _capture(tmp_path)
    controller.submit_video_workflow_job(
        source_image_path=_reference(tmp_path),
        form_data=_form(WAN_ANIMATE2_DRIVE_ID, pose_video_path=str(clip)),
    )
    extra = submitted[0].stage_chain[0].to_dict()["extra"]
    assert extra["pose_video_sha256"] == hashlib.sha256(clip.read_bytes()).hexdigest()
    clip.write_bytes(b"changed after admission")
    assert extra["pose_video_sha256"] != hashlib.sha256(clip.read_bytes()).hexdigest()


def test_compiling_without_the_frozen_controls_fails_closed(tmp_path) -> None:
    from src.video.video_backend_types import VideoExecutionRequest

    request = VideoExecutionRequest(
        backend_id="comfy",
        stage_name="video_workflow",
        stage_config={
            "seed": 1,
            "frame_count": 41,
            "pose_video_path": str(_driving_clip(tmp_path)),
            "source_preparation": {"target_dimensions": {"width": 480, "height": 832}},
        },
        output_dir=tmp_path / "run",
        input_image_path=_reference(tmp_path),
        prompt=APPEARANCE,
        job_id="job-x",
        workflow_id=WAN_ANIMATE2_DRIVE_ID,
        workflow_version=WAN_ANIMATE2_CONTROLS_VERSION,
        experimental_opt_in=True,
    )
    with pytest.raises(ValueError, match="requires input 'pose_prompt'"):
        WorkflowCompiler().compile(_spec(WAN_ANIMATE2_DRIVE_ID), request)
