"""PR-VID-EVAL-320: eval suites load strictly and an eval run is admitted once on the canonical path."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from PIL import Image

from src.controller.video_workflow_controller import VideoWorkflowController
from src.video.video_eval_run import (
    RUN_MANIFEST_NAME,
    RUN_SCHEMA,
    BuiltEvalJob,
    EvalRunRefused,
    VideoEvalRunService,
)
from src.video.video_eval_suite import (
    MAX_EVAL_JOBS,
    SUITE_SCHEMA,
    EvalSuiteError,
    file_sha256,
    load_eval_suite,
)

TI2V_ID = "wan22_ti2v_5b_i2v_v1"


class _JobService:
    def __init__(self) -> None:
        self.calls: list[list[Any]] = []

    def submit_njrs(self, njrs, policy):
        self.calls.append(list(njrs))
        return [njr.job_id for njr in njrs]


def _image(path: Path, size=(64, 96), color=(120, 40, 90)) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", size, color).save(path)
    return path


def _suite(tmp_path: Path, *, cases=None, arms=None, **extra) -> Path:
    images = tmp_path / "suite" / "images"
    if cases is None:
        cases = [
            {"case_id": "portrait", "image": "images/portrait.png", "prompt": "turns head slowly"},
            {"case_id": "wide", "image": "images/wide.png", "prompt": "camera drifts right"},
        ]
        _image(images / "portrait.png")
        _image(images / "wide.png", size=(96, 64))
    if arms is None:
        arms = [
            {"arm_id": "svd_base", "label": "SVD XT", "backend": "svd_native", "svd": {}},
            {
                "arm_id": "svd_motion",
                "backend": "svd_native",
                "svd": {"inference": {"motion_bucket_id": 140}},
            },
        ]
    data = {
        "schema": SUITE_SCHEMA,
        "suite_id": "core",
        "seed": 1234,
        "cases": cases,
        "arms": arms,
        **extra,
    }
    path = tmp_path / "suite" / "suite.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data), encoding="utf-8")
    return path


# ------------------------------------------------------------------ suite loading


def test_suite_loads_pins_images_and_defaults_the_baseline(tmp_path) -> None:
    suite = load_eval_suite(_suite(tmp_path))
    assert suite.suite_id == "core" and suite.seed == 1234 and suite.job_count == 4
    assert suite.baseline_arm_id == "svd_base"
    portrait = suite.cases[0]
    assert portrait.image_path.is_file()
    assert portrait.image_sha256 == file_sha256(portrait.image_path)


def test_a_pinned_image_that_changed_is_refused(tmp_path) -> None:
    image = _image(tmp_path / "suite" / "images" / "a.png")
    cases = [{"case_id": "a", "image": "images/a.png", "prompt": "p", "image_sha256": "0" * 64}]
    with pytest.raises(EvalSuiteError, match="changed since the suite pinned it"):
        load_eval_suite(_suite(tmp_path, cases=cases))
    assert image.is_file()


@pytest.mark.parametrize(
    ("arms", "message"),
    [
        ([{"arm_id": "x", "backend": "animatediff"}], "backend must be one of"),
        ([{"arm_id": "Bad Id", "backend": "svd_native"}], "arm_id"),
        ([{"arm_id": "w", "backend": "video_workflow", "form": {}}], "workflow_id is required"),
        (
            [
                {
                    "arm_id": "w",
                    "backend": "video_workflow",
                    "form": {"workflow_id": TI2V_ID, "prompt": "x"},
                }
            ],
            "comes from the case",
        ),
        (
            [{"arm_id": "s", "backend": "svd_native", "svd": {"inference": {"seed": 3}}}],
            "suite seed",
        ),
        (
            [{"arm_id": "s", "backend": "svd_native"}, {"arm_id": "s", "backend": "svd_native"}],
            "duplicate arm_id",
        ),
    ],
)
def test_invalid_arms_are_refused_with_a_reason(tmp_path, arms, message) -> None:
    with pytest.raises(EvalSuiteError, match=message):
        load_eval_suite(_suite(tmp_path, arms=arms))


def test_wrong_schema_unknown_baseline_and_oversized_runs_are_refused(tmp_path) -> None:
    with pytest.raises(EvalSuiteError, match="unsupported eval suite schema"):
        load_eval_suite(_suite(tmp_path, schema="v0"))
    with pytest.raises(EvalSuiteError, match="baseline_arm"):
        load_eval_suite(_suite(tmp_path, baseline_arm="nope"))
    arms = [{"arm_id": f"a{i}", "backend": "svd_native"} for i in range(MAX_EVAL_JOBS // 2 + 1)]
    with pytest.raises(EvalSuiteError, match="one run admits at most"):
        load_eval_suite(_suite(tmp_path, arms=arms))


# ------------------------------------------------------------------ plan and admit (fake builders)


def _fake_builder(fail_case: str | None = None):
    def build(case, arm, seed):
        if case.case_id == fail_case:
            raise ValueError("cannot prepare this source")
        return BuiltEvalJob(njr=SimpleNamespace(job_id=f"{case.case_id}-{arm.arm_id}"), seed=seed)

    return build


def test_admission_submits_every_job_once_and_writes_the_manifest(tmp_path) -> None:
    suite = load_eval_suite(_suite(tmp_path))
    service = VideoEvalRunService(builders={"svd_native": _fake_builder()})
    plan = service.plan(suite)
    assert plan.eligible and len(plan.jobs) == 4
    job_service = _JobService()

    admission = service.admit(plan, job_service, output_root=tmp_path / "output")

    assert len(job_service.calls) == 1 and len(job_service.calls[0]) == 4
    manifest = json.loads(admission.manifest_path.read_text(encoding="utf-8"))
    assert manifest["schema"] == RUN_SCHEMA and manifest["run_id"] == plan.run_id
    assert {(job["case_id"], job["arm_id"]) for job in manifest["jobs"]} == {
        (c, a) for c in ("portrait", "wide") for a in ("svd_base", "svd_motion")
    }
    assert all(job["seed"] == 1234 for job in manifest["jobs"])
    assert manifest["suite"]["baseline_arm"] == "svd_base"
    assert admission.run_dir == tmp_path / "output" / "video_eval" / plan.run_id


def test_one_unbuildable_case_makes_the_whole_run_unqueueable(tmp_path) -> None:
    suite = load_eval_suite(_suite(tmp_path))
    service = VideoEvalRunService(builders={"svd_native": _fake_builder(fail_case="wide")})
    plan = service.plan(suite)
    assert not plan.eligible
    assert "wide x svd_base: cannot prepare this source" in plan.summary()
    job_service = _JobService()
    with pytest.raises(EvalRunRefused, match="nothing was queued"):
        service.admit(plan, job_service, output_root=tmp_path / "output")
    assert job_service.calls == []


def test_an_image_changed_after_the_preview_is_refused_before_admission(tmp_path) -> None:
    suite = load_eval_suite(_suite(tmp_path))
    service = VideoEvalRunService(builders={"svd_native": _fake_builder()})
    plan = service.plan(suite)
    _image(suite.cases[0].image_path, color=(1, 2, 3))
    job_service = _JobService()
    with pytest.raises(EvalRunRefused, match="changed after the preview"):
        service.admit(plan, job_service, output_root=tmp_path / "output")
    assert job_service.calls == []
    assert not (tmp_path / "output").exists()


def test_a_failed_admission_leaves_no_manifest(tmp_path) -> None:
    suite = load_eval_suite(_suite(tmp_path))
    service = VideoEvalRunService(builders={"svd_native": _fake_builder()})
    plan = service.plan(suite)

    class _Broken:
        def submit_njrs(self, njrs, policy):
            raise RuntimeError("database is locked")

    with pytest.raises(EvalRunRefused, match="database is locked"):
        service.admit(plan, _Broken(), output_root=tmp_path / "output")
    assert not (tmp_path / "output" / "video_eval" / plan.run_id / RUN_MANIFEST_NAME).exists()


# ------------------------------------------------------------------ the production controller path


def _controller(tmp_path: Path):
    job_service = _JobService()
    app = SimpleNamespace(
        job_service=job_service,
        output_dir=str(tmp_path / "output"),
        sync_queue_state_after_direct_submission=lambda: None,
    )
    return VideoWorkflowController(app_controller=app), job_service


def test_controller_builds_real_svd_and_workflow_njrs_and_admits_them_once(
    tmp_path, monkeypatch
) -> None:
    monkeypatch.setattr(
        "src.controller.svd_controller.get_svd_preflight",
        lambda *_args, **_kwargs: SimpleNamespace(available=True, blocking_reasons=()),
    )
    arms = [
        {"arm_id": "svd", "backend": "svd_native", "svd": {"inference": {"motion_bucket_id": 127}}},
        {
            "arm_id": "ti2v",
            "backend": "video_workflow",
            "form": {
                "workflow_id": TI2V_ID,
                "workflow_version": "1.1.0",
                "frame_count": 33,
                "experimental_opt_in": True,
            },
        },
    ]
    controller, job_service = _controller(tmp_path)

    plan = controller.preview_eval_run(_suite(tmp_path, arms=arms))

    assert plan.eligible, plan.summary()
    assert plan.experimental_arms == ("ti2v",)
    admission = controller.submit_eval_run(plan)
    assert len(job_service.calls) == 1
    njrs = {job.arm_id + ":" + job.case_id: job.njr for job in plan.jobs}
    svd_config = njrs["svd:portrait"].config["svd_native"]
    assert svd_config["inference"]["seed"] == 1234
    assert svd_config["inference"]["motion_bucket_id"] == 127
    # Portrait source: SVD target follows the source aspect.
    assert svd_config["preprocess"]["target_height"] > svd_config["preprocess"]["target_width"]
    workflow = njrs["ti2v:wide"].config["video_workflow"]
    assert workflow["workflow_id"] == TI2V_ID
    assert workflow["prompt"] == "camera drifts right"
    assert workflow["seed"] == 1234 and workflow["frame_count"] == 33
    assert admission.manifest_path.is_file()


def test_an_experimental_workflow_arm_without_opt_in_is_not_queueable(tmp_path) -> None:
    # TI2V-5B 1.1.0 is still experimental (only 1.2.0 was promoted by PR-VID-GOV-316), so the
    # arm needs its suite-declared opt-in; the form's default version would now be approved.
    arms = [
        {
            "arm_id": "ti2v",
            "backend": "video_workflow",
            "form": {"workflow_id": TI2V_ID, "workflow_version": "1.1.0"},
        }
    ]
    controller, job_service = _controller(tmp_path)

    plan = controller.preview_eval_run(_suite(tmp_path, arms=arms))

    assert not plan.eligible
    assert "ti2v" in plan.summary()
    assert job_service.calls == []


def test_an_approved_workflow_arm_is_queueable_without_an_opt_in(tmp_path) -> None:
    arms = [{"arm_id": "ti2v", "backend": "video_workflow", "form": {"workflow_id": TI2V_ID}}]
    controller, job_service = _controller(tmp_path)

    plan = controller.preview_eval_run(_suite(tmp_path, arms=arms))

    assert plan.eligible, plan.summary()
    assert plan.experimental_arms == ()
    workflow = plan.jobs[0].njr.config["video_workflow"]
    assert workflow["workflow_version"] == "1.3.0"  # the approved frames-out revision (PR-VID-WAN-324)
    assert workflow["video_execution"]["experimental_opt_in"] is False
    assert job_service.calls == []  # a preview admits nothing
