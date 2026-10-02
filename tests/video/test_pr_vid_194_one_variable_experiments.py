"""PR-VID-194: one-variable operator experiments over the declared Video Workflow controls.

CPU-only and deterministic: fake JobService, temp files, no Comfy/WebUI/GPU/network.
"""

from __future__ import annotations

import copy
import dataclasses
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from PIL import Image

from src.controller.video_workflow_controller import VideoWorkflowController
from src.pipeline.job_models_v2 import SourceKind, WorkloadKind
from src.video.video_workflow_experiment import (
    ExperimentRefused,
    assert_one_variable,
)
from src.video.workflow_catalog_wan_animate2 import (
    WAN_ANIMATE2_CONTROLS_VERSION,
    WAN_ANIMATE2_DRIVE_ID,
    WAN_ANIMATE2_PROMPT_ID,
)

TI2V_ID = "wan22_ti2v_5b_i2v_v1"
APPEARANCE = "Character appearance description: a woman in a navy top. Background: pale studio."
MOTION = "A person steps left, then raises an arm."


class _JobService:
    def __init__(self) -> None:
        self.calls: list[list[Any]] = []

    def submit_njrs(self, njrs, policy):
        self.calls.append(list(njrs))
        return [f"job-{index}" for index, _njr in enumerate(njrs)]


def _stack(tmp_path: Path):
    service = _JobService()
    synced: list[bool] = []
    app = SimpleNamespace(
        job_service=service,
        output_dir=str(tmp_path / "output"),
        sync_queue_state_after_direct_submission=lambda: synced.append(True),
    )
    return VideoWorkflowController(app_controller=app), service, synced


def _source(tmp_path: Path) -> Path:
    path = tmp_path / "reference.png"
    Image.new("RGB", (48, 80), "navy").save(path)
    return path


def _clip(tmp_path: Path) -> Path:
    path = tmp_path / "driving.mp4"
    path.write_bytes(b"\x00\x00\x00\x18ftypmp42 fake driving clip")
    return path


def _drive_form(tmp_path: Path, **overrides: Any) -> dict[str, Any]:
    form: dict[str, Any] = {
        "workflow_id": WAN_ANIMATE2_DRIVE_ID,
        "workflow_version": WAN_ANIMATE2_CONTROLS_VERSION,
        "prompt": APPEARANCE,
        "negative_prompt": "",
        "pose_video_path": str(_clip(tmp_path)),
        "experimental_opt_in": True,
        "seed": "424242",
        "operator_controls": {"pose_prompt": MOTION, "pose_strength": "1"},
    }
    form.update(overrides)
    return form


def _preview(tmp_path, variable="pose_strength", candidates=("1.5",), **form_overrides):
    controller, service, synced = _stack(tmp_path)
    plan = controller.preview_experiment(
        source_image_path=_source(tmp_path),
        form_data=_drive_form(tmp_path, **form_overrides),
        variable_name=variable,
        candidates=list(candidates),
    )
    return controller, service, synced, plan


def _video_block(arm) -> dict[str, Any]:
    return arm.njr.config["video_workflow"]


# ------------------------------------------------------------------ capability / variable list


def test_selector_offers_exactly_the_declared_controls_and_none_for_other_workflows(tmp_path):
    controller, service, _ = _stack(tmp_path)
    records = {r["workflow_id"]: r for r in controller.list_workflow_specs()}

    drive = [c["name"] for c in records[WAN_ANIMATE2_DRIVE_ID]["operator_controls"]]
    assert drive == [
        "pose_prompt",
        "pose_strength",
        "pose_start_percent",
        "pose_end_percent",
        "reference_image_strength",
    ]
    prompt = [c["name"] for c in records[WAN_ANIMATE2_PROMPT_ID]["operator_controls"]]
    assert prompt == ["reference_image_strength"]
    # A workflow that declares no controls offers no experiment capability...
    assert records[TI2V_ID]["operator_controls"] is None
    # ...and cannot be sent experiment values.
    with pytest.raises(ExperimentRefused, match="does not declare"):
        controller.preview_experiment(
            source_image_path=_source(tmp_path),
            form_data={
                "workflow_id": TI2V_ID,
                "workflow_version": "1.1.0",
                "prompt": "slow turn",
                "experimental_opt_in": True,
            },
            variable_name="pose_strength",
            candidates=["2"],
        )
    assert service.calls == []


def test_undeclared_variable_is_refused_even_on_a_workflow_with_controls(tmp_path):
    controller, service, _ = _stack(tmp_path)
    with pytest.raises(ExperimentRefused, match="does not declare a control named 'seed'"):
        controller.preview_experiment(
            source_image_path=_source(tmp_path),
            form_data=_drive_form(tmp_path),
            variable_name="seed",
            candidates=["1"],
        )
    assert service.calls == []


# ------------------------------------------------------------------ baseline and candidates


def test_baseline_is_the_resolved_current_value_not_an_invented_default(tmp_path):
    controller, _, _ = _stack(tmp_path)
    form = _drive_form(tmp_path, operator_controls={"pose_strength": "2.5", "pose_prompt": ""})
    assert controller.resolve_experiment_baseline(form, "pose_strength") == 2.5
    # blank number -> declared default; blank text -> the declared fallback (the appearance prompt)
    assert controller.resolve_experiment_baseline(form, "pose_end_percent") == 1.0
    assert controller.resolve_experiment_baseline(form, "pose_prompt") == APPEARANCE


def test_numeric_candidates_use_the_existing_control_validation(tmp_path):
    _, _, _, plan = _preview(tmp_path, candidates=["1.5", "2"])
    assert [arm.value for arm in plan.arms] == [1.0, 1.5, 2.0]
    for bad, fragment in (
        ("11", "between 0 and 10"),
        ("abc", "must be a number"),
        ("nan", "between"),
    ):
        controller, service, _ = _stack(tmp_path)
        with pytest.raises(ExperimentRefused, match=fragment):
            controller.preview_experiment(
                source_image_path=_source(tmp_path),
                form_data=_drive_form(tmp_path),
                variable_name="pose_strength",
                candidates=["1.2", bad],
            )
        assert service.calls == []


def test_text_candidates_preserve_exact_text_and_fallback_semantics(tmp_path):
    other = "A person walks forward and waves."
    _, _, _, plan = _preview(tmp_path, variable="pose_prompt", candidates=[other, "  padded  "])
    assert [arm.value for arm in plan.arms] == [MOTION, other, "padded"]
    frozen = [_video_block(arm)["operator_controls"]["pose_prompt"] for arm in plan.arms]
    assert frozen == [MOTION, other, "padded"]

    # An empty candidate means the declared fallback: the PREVIEW shows the resolved text, and it
    # is refused when that equals the baseline.
    controller, service, _ = _stack(tmp_path)
    form = _drive_form(tmp_path, operator_controls={"pose_prompt": "", "pose_strength": "1"})
    with pytest.raises(ExperimentRefused, match="same as the baseline"):
        controller.preview_experiment(
            source_image_path=_source(tmp_path),
            form_data=form,
            variable_name="pose_prompt",
            candidates=[""],
        )
    plan = controller.preview_experiment(
        source_image_path=_source(tmp_path),
        form_data=_drive_form(tmp_path, operator_controls={"pose_prompt": "x"}),
        variable_name="pose_prompt",
        candidates=[""],
    )
    assert plan.arms[1].value == APPEARANCE  # resolved effective text, not an empty box
    assert service.calls == []


def test_candidate_count_and_duplicates_fail_closed(tmp_path):
    controller, service, _ = _stack(tmp_path)

    def attempt(candidates, match):
        with pytest.raises(ExperimentRefused, match=match):
            controller.preview_experiment(
                source_image_path=_source(tmp_path),
                form_data=_drive_form(tmp_path),
                variable_name="pose_strength",
                candidates=candidates,
            )

    attempt([], "1 to 3 candidate")
    attempt(["1.1", "1.2", "1.3", "1.4"], "1 to 3 candidate")  # five total arms
    attempt(["1"], "same as the baseline")
    attempt(["1.0"], "same as the baseline")
    attempt(["1.5", "1.50"], "another candidate")
    assert service.calls == []

    _, _, _, plan = _preview(tmp_path, candidates=["1.1", "1.2", "1.3"])
    assert [arm.label for arm in plan.arms] == ["A", "B", "C", "D"]  # four is the maximum


def test_ordered_control_constraints_still_fail_closed(tmp_path):
    controller, service, _ = _stack(tmp_path)
    form = _drive_form(
        tmp_path, operator_controls={"pose_prompt": MOTION, "pose_end_percent": "0.5"}
    )
    with pytest.raises(ExperimentRefused, match="must not be greater"):
        controller.preview_experiment(
            source_image_path=_source(tmp_path),
            form_data=form,
            variable_name="pose_start_percent",
            candidates=["0.2", "0.8"],
        )
    assert service.calls == []


def test_one_invalid_arm_means_zero_submitted_jobs(tmp_path):
    controller, service, synced = _stack(tmp_path)
    with pytest.raises(ExperimentRefused):
        controller.preview_experiment(
            source_image_path=_source(tmp_path),
            form_data=_drive_form(tmp_path),
            variable_name="pose_strength",
            candidates=["1.2", "99"],
        )
    assert service.calls == [] and synced == []


# ------------------------------------------------------------------ frozen baseline


def test_blank_seed_is_resolved_once_and_reused_by_every_arm(tmp_path):
    _, _, _, plan = _preview(tmp_path, candidates=["1.2", "1.4", "1.6"], seed="")
    assert isinstance(plan.common_seed, int)
    assert {_video_block(arm)["seed"] for arm in plan.arms} == {plan.common_seed}
    assert {arm.njr.provenance.metadata["video_workflow"]["seed"] for arm in plan.arms} == {
        plan.common_seed
    }
    assert thaw_seed(plan) == plan.common_seed


def thaw_seed(plan) -> int:
    return json.loads(plan.snapshot_json)["seed"]


def test_explicit_seed_is_identical_across_arms(tmp_path):
    _, _, _, plan = _preview(tmp_path, seed="777")
    assert plan.common_seed == 777
    assert {_video_block(arm)["seed"] for arm in plan.arms} == {777}


def test_source_and_driving_hashes_are_identical_across_arms_and_in_the_snapshot(tmp_path):
    _, _, _, plan = _preview(tmp_path, candidates=["1.2", "1.4"])
    source_hash = hashlib.sha256(_source(tmp_path).read_bytes()).hexdigest()
    clip_hash = hashlib.sha256(_clip(tmp_path).read_bytes()).hexdigest()
    snapshot = json.loads(plan.snapshot_json)
    assert snapshot["source"]["sha256"] == source_hash
    assert snapshot["driving_video"]["sha256"] == clip_hash
    assert {_video_block(arm)["pose_video_sha256"] for arm in plan.arms} == {clip_hash}
    assert (
        len({_video_block(arm)["source_preparation"]["prepared_image_path"] for arm in plan.arms})
        == 1
    )
    assert len({arm.njr.input_image_paths for arm in plan.arms}) == 1
    assert (
        hashlib.sha256(Path(plan.arms[0].njr.input_image_paths[0]).read_bytes()).hexdigest()
        == snapshot["source"]["prepared_sha256"]
    )


@pytest.mark.parametrize("target", ["source", "driving", "prepared"])
def test_bytes_changed_between_preview_and_admission_submits_nothing(tmp_path, target):
    controller, service, synced, plan = _preview(tmp_path)
    path = {
        "source": _source(tmp_path),
        "driving": _clip(tmp_path),
        "prepared": Path(plan.frozen.prepared_source_path),
    }[target]
    path.write_bytes(path.read_bytes() + b"changed")
    with pytest.raises(ExperimentRefused, match="changed after it was frozen"):
        controller.submit_experiment(plan)
    assert service.calls == [] and synced == []


def test_everything_except_the_selected_control_is_identical_across_arms(tmp_path):
    _, _, _, plan = _preview(
        tmp_path,
        candidates=["1.2", "1.5"],
        operator_controls={
            "pose_prompt": MOTION,
            "pose_strength": "1",
            "pose_start_percent": "0.1",
            "pose_end_percent": "0.9",
            "reference_image_strength": "1.1",
        },
    )
    first = plan.arms[0].njr
    for arm in plan.arms[1:]:
        njr = arm.njr
        block, base = _video_block(arm), _video_block(plan.arms[0])
        assert (block["workflow_id"], block["workflow_version"], block["backend_id"]) == (
            base["workflow_id"],
            base["workflow_version"],
            base["backend_id"],
        )
        assert njr.positive_prompt == first.positive_prompt
        assert njr.negative_prompt == first.negative_prompt
        assert block["frame_count"] == base["frame_count"] and block["fps"] == base["fps"]
        assert njr.config["pipeline"] == first.config["pipeline"]
        assert block["video_execution"] == base["video_execution"]
        for name in (
            "pose_prompt",
            "pose_start_percent",
            "pose_end_percent",
            "reference_image_strength",
        ):
            assert block["operator_controls"][name] == base["operator_controls"][name]
        assert (
            block["operator_controls"]["pose_strength"]
            != base["operator_controls"]["pose_strength"]
        )
        assert njr.output_plan == first.output_plan
        assert njr.source == first.source
    assert_one_variable(
        plan.arms,
        variable_name=plan.variable_name,
        variable_label=plan.variable_label,
        experiment_id=plan.experiment_id,
        experiment_name=plan.experiment_name,
    )


def _other_frame_count(controller) -> int:
    record = next(
        r for r in controller.list_workflow_specs() if r["workflow_id"] == WAN_ANIMATE2_DRIVE_ID
    )
    default = record["frame_count"]["default"]
    return next(c["frames"] for c in record["frame_count"]["choices"] if c["frames"] != default)


def test_controlled_diff_gate_refuses_any_other_difference(tmp_path):
    controller, service, _, plan = _preview(tmp_path, candidates=["1.2", "1.4"])
    builder = controller._njr_builder
    form = _drive_form(tmp_path)
    form["operator_controls"] = {**form["operator_controls"], "pose_strength": "1.2"}

    def rebuilt(**changes):
        frozen = dataclasses.replace(plan.frozen, **changes.pop("frozen", {}))
        variant = {**form, **changes}
        return builder.build_job(
            variant, frozen, learning_context=plan.arms[1].njr.learning_context
        )

    leaks = {
        "seed": rebuilt(frozen={"seed": 1}),
        "prompt": rebuilt(prompt=APPEARANCE + " extra"),
        "negative": rebuilt(negative_prompt="blurry"),
        "output_route": rebuilt(output_route="Testing"),
        "other control": rebuilt(
            operator_controls={**form["operator_controls"], "pose_end_percent": "0.9"}
        ),
        "frames": rebuilt(frame_count=_other_frame_count(controller)),
    }
    for built in leaks.values():
        tampered = (plan.arms[0], dataclasses.replace(plan.arms[1], njr=built.njr), plan.arms[2])
        with pytest.raises(ExperimentRefused, match="differs from arm A outside"):
            assert_one_variable(
                tampered,
                variable_name=plan.variable_name,
                variable_label=plan.variable_label,
                experiment_id=plan.experiment_id,
                experiment_name=plan.experiment_name,
            )
    assert service.calls == []


def test_a_builder_that_leaks_a_difference_refuses_the_whole_experiment(tmp_path, monkeypatch):
    controller, service, _ = _stack(tmp_path)
    original = controller._njr_builder.build_job

    def leaky(form_data, frozen, **kwargs):
        index = kwargs["learning_context"].variant_index
        if index == 2:
            form_data = {**form_data, "prompt": form_data["prompt"] + " leaked"}
        return original(form_data, frozen, **kwargs)

    monkeypatch.setattr(controller._njr_builder, "build_job", leaky)
    with pytest.raises(ExperimentRefused, match="differs from arm A outside Pose Strength"):
        controller.preview_experiment(
            source_image_path=_source(tmp_path),
            form_data=_drive_form(tmp_path),
            variable_name="pose_strength",
            candidates=["1.2", "1.4"],
        )
    assert service.calls == []


# ------------------------------------------------------------------ NJR contract and admission


def test_njrs_are_immutable_and_carry_shared_learning_identity(tmp_path):
    _, _, _, plan = _preview(tmp_path, candidates=["1.2", "1.4"])
    contexts = [arm.njr.learning_context for arm in plan.arms]
    assert {c.experiment_id for c in contexts} == {plan.experiment_id}
    assert {c.experiment_name for c in contexts} == {plan.experiment_name}
    assert {c.variable_under_test for c in contexts} == {"pose_strength"}
    assert [c.variant_index for c in contexts] == [0, 1, 2]
    assert [c.variant_value for c in contexts] == [1.0, 1.2, 1.4]
    for arm in plan.arms:
        assert arm.njr.source.kind is SourceKind.VIDEO_WORKFLOW
        assert arm.njr.workload_kind is WorkloadKind.VIDEO
        with pytest.raises(dataclasses.FrozenInstanceError):
            arm.njr.job_id = "other"  # type: ignore[misc]
        with pytest.raises(dataclasses.FrozenInstanceError):
            arm.njr.provenance.learning_context = None  # type: ignore[misc]
    assert len({arm.njr.job_id for arm in plan.arms}) == 3


def test_admission_crosses_submit_njrs_exactly_once_with_every_njr(tmp_path):
    controller, service, synced, plan = _preview(tmp_path, candidates=["1.2", "1.4", "1.6"])
    assert service.calls == []  # previewing never queues

    result = controller.submit_experiment(plan)

    assert len(service.calls) == 1
    assert [njr.job_id for njr in service.calls[0]] == [arm.njr.job_id for arm in plan.arms]
    assert result.job_ids == ["job-0", "job-1", "job-2", "job-3"]
    assert [(label, value) for label, value, _ in result.arms] == [
        ("A", 1.0),
        ("B", 1.2),
        ("C", 1.4),
        ("D", 1.6),
    ]
    # Queue-state refresh touches GUI-visible state, so it is the UI thread's job, not admission's.
    assert result.experiment_id == plan.experiment_id and synced == []


def test_experiment_arm_a_equals_the_normal_single_submission(tmp_path):
    controller, service, _ = _stack(tmp_path)
    form = _drive_form(tmp_path)
    controller.submit_video_workflow_job(source_image_path=_source(tmp_path), form_data=dict(form))
    [single] = service.calls[0]
    plan = controller.preview_experiment(
        source_image_path=_source(tmp_path),
        form_data=form,
        variable_name="pose_strength",
        candidates=["1.5"],
    )
    arm_a = plan.arms[0].njr.to_dict()
    expected = single.to_dict()
    for payload in (arm_a, expected):
        payload.pop("job_id")
        payload["provenance"].pop("learning_context")
    assert arm_a == expected
    assert single.learning_context is None  # normal jobs are unchanged


def test_normal_submission_is_unchanged_in_projection_and_default_provenance(tmp_path):
    controller, service, _ = _stack(tmp_path)
    form = _drive_form(tmp_path, seed="")
    job_id = controller.submit_video_workflow_job(
        source_image_path=_source(tmp_path), form_data=form
    )
    projection = form["_stable_new_submission_projection"]
    assert job_id == "job-0" == projection["job_id"]
    assert isinstance(projection["seed"], int)
    assert projection["source_preparation"]["target_dimensions"]
    [njr] = service.calls[0]
    assert njr.config["video_workflow"]["seed"] == projection["seed"]
    assert njr.provenance.learning_context is None


def test_experimental_opt_in_is_default_off_and_required_to_preview_or_queue(tmp_path):
    controller, service, _ = _stack(tmp_path)
    assert controller.build_default_form_state()["experimental_opt_in"] is False
    with pytest.raises(ExperimentRefused, match="experimental"):
        controller.preview_experiment(
            source_image_path=_source(tmp_path),
            form_data=_drive_form(tmp_path, experimental_opt_in=False),
            variable_name="pose_strength",
            candidates=["1.5"],
        )
    assert service.calls == []

    _, _, _, plan = _preview(tmp_path)
    assert plan.requires_opt_in is True
    assert all(
        _video_block(arm)["video_execution"]["experimental_opt_in"] is True for arm in plan.arms
    )


# ------------------------------------------------------------------ source hygiene


def test_gui_experiment_code_builds_no_payload_and_branches_on_no_workflow():
    forbidden = (
        "wan_animate",
        "animate2",
        "animate-2",
        "wan22",
        "comfy",
        "workflow_id ==",
        "workflow_id in",
        "jobrepository",
        "pipelinerunner",
        "submit_njrs",
        "requests.",
        "urllib",
        "subprocess",
        "positive_pose",
        "prompt_id",
    )
    for relative in (
        "src/gui/views/video_workflow_experiment_panel_v2.py",
        "src/gui/view_contracts/video_experiment_contract.py",
    ):
        text = Path(relative).read_text(encoding="utf-8").lower()
        for token in forbidden:
            assert token not in text, f"{relative} must not contain {token!r}"
    tab = Path("src/gui/views/video_workflow_tab_frame_v2.py").read_text(encoding="utf-8").lower()
    for token in ("submit_njrs", "jobrepository", "pipelinerunner", "positive_pose", "prompt_id"):
        assert token not in tab


def test_experiment_service_names_no_workflow_or_model():
    text = Path("src/video/video_workflow_experiment.py").read_text(encoding="utf-8").lower()
    for token in ("wan_animate", "animate2", "wan22", "comfy", "pose_strength", "pose_prompt"):
        assert token not in text


def test_controller_stays_small_and_owns_no_njr_construction():
    text = Path("src/controller/video_workflow_controller.py").read_text(encoding="utf-8")
    assert len(text.splitlines()) < 260
    assert "ReprocessJobBuilder" not in text and "build_reprocess_job" not in text


def test_plan_is_a_transient_frozen_value_with_an_honest_fixed_summary(tmp_path):
    _, _, _, plan = _preview(tmp_path)
    assert dataclasses.is_dataclass(plan) and plan.__dataclass_params__.frozen
    assert plan.statement == "Only Pose Strength changes across these jobs."
    labels = [row[0] for row in plan.fixed_inputs()]
    assert {"Workflow", "Source", "Driving video", "Seed", "Prompt", "Negative"} <= set(labels)
    assert "pose_prompt" in labels and "pose_strength" not in labels  # the variable is not "fixed"


# ------------------------------------------------------------------ real queue, fake Comfy


def test_experiment_jobs_run_through_the_real_queue_with_distinct_controls(tmp_path):
    from src.queue.job_model import JobStatus
    from tests.integration.test_pr_vid_120_neutral_video_queue import _build_stack
    from tests.video.test_pr_vid_190_wan_animate2 import (
        _AnimateComfy,
        _backend,
        _ManagedFake,
    )

    client = _AnimateComfy(tmp_path)
    repository, queue, service, _ = _build_stack(tmp_path, [_backend(client, _ManagedFake())])
    app = SimpleNamespace(job_service=service, output_dir=str(tmp_path / "output"))
    controller = VideoWorkflowController(app_controller=app)
    try:
        plan = controller.preview_experiment(
            source_image_path=_source(tmp_path),
            form_data=_drive_form(tmp_path),
            variable_name="pose_strength",
            candidates=["1.5", "2"],
        )
        result = controller.submit_experiment(plan)
        assert len(result.job_ids) == 3
        for job_id in result.job_ids:
            service.runner.run_once(queue.get_job(job_id))
        jobs = [repository.get_job(job_id) for job_id in result.job_ids]
        assert [job.status for job in jobs] == [JobStatus.COMPLETED] * 3
        # The queue snapshot keeps each arm's shared experiment identity and its own value.
        contexts = [
            job.snapshot["normalized_job"]["provenance"]["learning_context"] for job in jobs
        ]
        assert {c["experiment_id"] for c in contexts} == {plan.experiment_id}
        assert [c["variant_value"] for c in contexts] == [1.0, 1.5, 2.0]
        assert {c["variable_under_test"] for c in contexts} == {"pose_strength"}
        # Every arm submitted one Comfy graph; the graphs differ ONLY in the pose strength input.
        graphs = [payload["prompt"] for payload in client.queued]
        assert len(graphs) == 3
        assert [g["10"]["inputs"]["pose_strength"] for g in graphs] == [1.0, 1.5, 2.0]

        def neutral(graph):  # mask the variable and the job-identity-derived filename prefix
            graph = copy.deepcopy(graph)
            graph["10"]["inputs"]["pose_strength"] = None
            graph["17"]["inputs"]["filename_prefix"] = None
            return graph

        assert all(neutral(graph) == neutral(graphs[0]) for graph in graphs[1:])
    finally:
        service.runner.stop()
        repository.close()


# ------------------------------------------------------------------ streaming hash


def test_sha256_file_streams_in_bounded_chunks_with_the_standard_digest(tmp_path, monkeypatch):
    from src.video.video_workflow_njr_builder import HASH_CHUNK_BYTES, sha256_file

    payload = bytes(range(256)) * (HASH_CHUNK_BYTES // 256 * 2 + 3)  # > 2 chunks, uneven tail
    path = tmp_path / "big.bin"
    path.write_bytes(payload)
    empty = tmp_path / "empty.bin"
    empty.write_bytes(b"")

    def forbidden(self):
        raise AssertionError("whole-file read_bytes() is not allowed for hashing")

    monkeypatch.setattr(Path, "read_bytes", forbidden)
    assert sha256_file(path) == hashlib.sha256(payload).hexdigest()
    assert sha256_file(empty) == hashlib.sha256(b"").hexdigest()

    sizes: list[int] = []
    real_open = Path.open

    def spying_open(self, *args, **kwargs):
        handle = real_open(self, *args, **kwargs)

        class _Spy:
            def read(self_inner, size=-1):
                sizes.append(size)
                return handle.read(size)

            def __enter__(self_inner):
                return self_inner

            def __exit__(self_inner, *exc):
                handle.close()

        return _Spy()

    monkeypatch.setattr(Path, "open", spying_open)
    assert sha256_file(path) == hashlib.sha256(payload).hexdigest()
    assert sizes and all(0 < size <= HASH_CHUNK_BYTES for size in sizes)


# ------------------------------------------------------------------ all-or-none canonical admission


def test_a_repository_failure_on_a_later_arm_leaves_zero_arms_admitted_or_runnable(
    tmp_path, monkeypatch
):
    import sqlite3

    from src.gui.view_contracts.video_experiment_contract import VideoExperimentSession
    from tests.integration.test_pr_vid_120_neutral_video_queue import _build_stack
    from tests.video.test_pr_vid_190_wan_animate2 import _AnimateComfy, _backend, _ManagedFake

    repository, queue, service, _ = _build_stack(
        tmp_path, [_backend(_AnimateComfy(tmp_path), _ManagedFake())]
    )
    app = SimpleNamespace(job_service=service, output_dir=str(tmp_path / "output"))
    controller = VideoWorkflowController(app_controller=app)
    try:
        service.auto_run_enabled = True  # a failed admission must not start anything either
        plan = controller.preview_experiment(
            source_image_path=_source(tmp_path),
            form_data=_drive_form(tmp_path),
            variable_name="pose_strength",
            candidates=["1.5", "2", "2.5"],
        )
        original = repository._insert_job_submission
        calls = {"n": 0}

        def fail_on_third(connection, prepared, queue_order):
            calls["n"] += 1
            if calls["n"] == 3:
                raise sqlite3.OperationalError("injected write failure")
            return original(connection, prepared, queue_order)

        monkeypatch.setattr(repository, "_insert_job_submission", fail_on_third)
        started: list[bool] = []
        monkeypatch.setattr(service, "_ensure_runner_started", lambda: started.append(True))

        with pytest.raises(sqlite3.OperationalError):
            controller.submit_experiment(plan)

        assert calls["n"] == 3  # arms A and B were inserted inside the transaction, then undone
        assert repository.list_recent_jobs() == []
        assert queue.list_jobs() == [] and queue.get_next_job() is None
        assert started == []

        # The operator-facing "nothing was queued" is now literally true.
        session = VideoExperimentSession(
            resolve_baseline=controller.resolve_experiment_baseline,
            build_preview=controller.preview_experiment,
            submit_plan=controller.submit_experiment,
        )
        session.apply_controls(
            next(
                r
                for r in controller.list_workflow_specs()
                if r["workflow_id"] == WAN_ANIMATE2_DRIVE_ID
            )["operator_controls"]
        )
        session.set_enabled(True)
        session.select_variable("pose_strength")
        session.set_candidate(0, "1.5")
        form = _drive_form(tmp_path)
        assert session.build_preview(str(_source(tmp_path)), form)
        calls["n"] = 1  # a two-arm plan: arm A inserts (n=2), arm B fails (n=3)
        assert session.queue(str(_source(tmp_path)), form) == []
        assert "nothing was queued" in session.message
        assert repository.list_recent_jobs() == [] and queue.list_jobs() == []
    finally:
        service.runner.stop()
        repository.close()
