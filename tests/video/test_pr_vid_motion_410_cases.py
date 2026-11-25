"""PR-VID-MOTION-410 Workstreams A-C: motion cases, suite versioning, frozen identity and all-or-none admission."""

from __future__ import annotations

import json
from functools import partial

import pytest

from src.video.video_eval_motion import MotionBindingError, parse_motion
from src.video.video_eval_run import RUN_MANIFEST_NAME, EvalRunRefused
from src.video.video_eval_suite import (
    SUITE_SCHEMA,
    SUITE_SCHEMA_V2,
    EvalSuiteError,
    load_eval_suite,
)
from tests.video.motion_410_support import (
    controller,
    drive_arm,
    fake_prepared_record,
    make_image,
    make_video,
    motion_block,
    sha,
    write_suite,
)


def _cases(tmp_path, *, count=2, driver=None, **motion):
    driver = driver or make_video(tmp_path / "suite" / "motion" / "head.mp4")
    cases = []
    for index in range(count):
        make_image(
            tmp_path / "suite" / "images" / f"subject{index}.png", color=(40 * index, 90, 120)
        )
        cases.append(
            {
                "case_id": f"head_s{index}",
                "image": f"images/subject{index}.png",
                "prompt": "a woman in a red coat stands in a studio",
                "motion": motion_block(driver, **motion),
            }
        )
    return cases, driver


# ------------------------------------------------------------------ suite contract (Workstream A)


def test_a_motion_case_binds_a_verified_driver_and_records_a_local_video_honestly(tmp_path) -> None:
    cases, driver = _cases(tmp_path, count=1)
    suite = load_eval_suite(write_suite(tmp_path, cases, [drive_arm()]))

    motion = suite.cases[0].motion
    assert suite.schema == SUITE_SCHEMA_V2 and suite.has_motion
    assert motion is not None and motion.driving_sha256 == sha(driver)
    # A local video is never presented as a library asset or a generated clip.
    assert motion.library_asset is None
    assert "not verified" in motion.provenance_label


def test_one_driver_is_shared_by_many_source_images_without_duplicating_arms(tmp_path) -> None:
    cases, driver = _cases(tmp_path, count=3)
    suite = load_eval_suite(write_suite(tmp_path, cases, [drive_arm("a"), drive_arm("b")]))

    assert {case.motion.driving_sha256 for case in suite.cases} == {sha(driver)}
    assert len({case.motion.identity for case in suite.cases}) == 1  # one motion, three subjects
    assert len({case.image_sha256 for case in suite.cases}) == 3
    assert suite.job_count == 6  # cases x arms; the driver adds no arm


def test_different_cases_may_bind_different_drivers(tmp_path) -> None:
    first, _ = _cases(tmp_path, count=1)
    wave = make_video(tmp_path / "suite" / "motion" / "wave.mp4", b"driver-b")
    image = make_image(tmp_path / "suite" / "images" / "other.png")
    second = {
        "case_id": "wave_s0",
        "image": str(image),
        "prompt": "a man waves",
        "motion": motion_block(wave, category="hand_wave"),
    }
    suite = load_eval_suite(write_suite(tmp_path, [*first, second], [drive_arm()]))
    assert len({case.motion.driving_sha256 for case in suite.cases}) == 2


def test_v1_suites_load_unchanged_and_cannot_carry_a_driving_reference(tmp_path) -> None:
    cases, _ = _cases(tmp_path, count=1)
    path = write_suite(tmp_path, cases, [drive_arm()], schema=SUITE_SCHEMA)
    with pytest.raises(EvalSuiteError, match="needs schema stablenew.video-eval-suite.v2"):
        load_eval_suite(path)

    plain = [{"case_id": "p", "image": "images/subject0.png", "prompt": "turns"}]
    data = json.loads(write_suite(tmp_path, plain, [drive_arm()], schema=SUITE_SCHEMA).read_text())
    suite = load_eval_suite(write_suite(tmp_path, plain, [drive_arm()], schema=SUITE_SCHEMA))
    assert data["schema"] == SUITE_SCHEMA and suite.schema == SUITE_SCHEMA and not suite.has_motion


def test_a_changed_or_missing_driver_is_refused(tmp_path) -> None:
    cases, driver = _cases(tmp_path, count=1)
    cases[0]["motion"]["driving"]["sha256"] = "0" * 64
    with pytest.raises(EvalSuiteError, match="changed since the suite pinned it"):
        load_eval_suite(write_suite(tmp_path, cases, [drive_arm()]))
    driver.unlink()
    cases[0]["motion"]["driving"].pop("sha256")
    with pytest.raises(EvalSuiteError, match="driving video not found"):
        load_eval_suite(write_suite(tmp_path, cases, [drive_arm()]))


def test_a_library_binding_is_accepted_only_for_the_exact_clip(tmp_path) -> None:
    cases, driver = _cases(tmp_path, count=1)
    cases[0]["motion"]["driving"]["library_asset"] = {"asset_id": "ma_1", "sha256": "f" * 64}
    with pytest.raises(EvalSuiteError, match="does not match the bound driving video"):
        load_eval_suite(write_suite(tmp_path, cases, [drive_arm()]))
    cases[0]["motion"]["driving"]["library_asset"] = {
        "asset_id": "ma_1",
        "sha256": sha(driver),
        "derived_from": {
            "original_sha256": "a" * 64,
            "start_frame": 10,
            "end_frame": 59,
            "cadence": "native",
        },
    }
    suite = load_eval_suite(write_suite(tmp_path, cases, [drive_arm()]))
    motion = suite.cases[0].motion
    assert (
        motion.source == "library_asset"
        and motion.library_asset["derived_from"]["start_frame"] == 10
    )


@pytest.mark.parametrize(
    ("change", "message"),
    [
        ({"category": "moonwalk"}, "category must be one of"),
        ({"expected_outcome": ""}, "expected_outcome is required"),
        ({"motion_prompt": ""}, "motion_prompt is required"),
        ({"action": ""}, "action is required"),
        ({"window": {"start_frame": 9, "end_frame": 3}}, "end_frame must be after start_frame"),
        ({"window": {"start_frame": 3}}, "needs preparation.mode"),
        ({"preparation": {"mode": "magic"}}, "preparation.mode must be one of"),
        ({"surprise": 1}, "unknown field"),
        ({"source": "library_asset"}, "is not a library asset without a verified library binding"),
    ],
)
def test_malformed_motion_blocks_are_refused_with_a_reason(tmp_path, change, message) -> None:
    cases, _ = _cases(tmp_path, count=1)
    cases[0]["motion"].update(change)
    with pytest.raises(EvalSuiteError, match=message):
        load_eval_suite(write_suite(tmp_path, cases, [drive_arm()]))


def test_an_arm_may_not_override_the_cases_driver_or_motion_prompt(tmp_path) -> None:
    cases, _ = _cases(tmp_path, count=1)
    arm = drive_arm()
    arm["form"]["pose_video_path"] = "x.mp4"
    with pytest.raises(EvalSuiteError, match="comes from each motion case's driving reference"):
        load_eval_suite(write_suite(tmp_path, cases, [arm]))
    arm = drive_arm()
    arm["form"]["operator_controls"] = {"pose_prompt": "other"}
    with pytest.raises(EvalSuiteError, match="motion prompt"):
        load_eval_suite(write_suite(tmp_path, cases, [arm]))


def test_native_svd_cannot_run_a_motion_case(tmp_path) -> None:
    cases, _ = _cases(tmp_path, count=1)
    svd = {"arm_id": "svd", "backend": "svd_native", "svd": {}}
    with pytest.raises(EvalSuiteError, match="takes no driving video"):
        load_eval_suite(write_suite(tmp_path, cases, [drive_arm(), svd]))


def test_parse_motion_requires_an_absolute_path_without_a_suite_folder(tmp_path) -> None:
    with pytest.raises(MotionBindingError, match="must be absolute"):
        parse_motion(motion_block(tmp_path / "x.mp4") | {"driving": {"path": "x.mp4"}}, "c", None)


# ------------------------------------------------------------------ production builders and admission (Workstream C)


def _plan(tmp_path, *, cases=None, arms=None, preparer=None):
    cases = cases if cases is not None else _cases(tmp_path, count=2)[0]
    arms = arms or [
        drive_arm("baseline", pose_strength=1.0, reference_image_strength=1.0),
        drive_arm("motion", pose_strength=1.2, reference_image_strength=1.0),
    ]
    ctl, service = controller(tmp_path, preparer=preparer)
    return ctl, service, ctl.preview_eval_run(write_suite(tmp_path, cases, arms))


def test_every_motion_job_is_a_production_njr_that_froze_the_driver_and_the_controls(
    tmp_path,
) -> None:
    ctl, service, plan = _plan(tmp_path)

    assert plan.eligible, plan.summary()
    assert len(plan.jobs) == 4
    for job in plan.jobs:
        block = job.njr.config["video_workflow"]
        assert (
            block["workflow_id"] == "wan_animate2_drive_i2v_v1"
            and block["workflow_version"] == "1.2.0"
        )
        assert block["pose_video_sha256"] == job.motion.driver_original_sha256
        assert block["operator_controls"]["pose_prompt"].startswith("the person turns")
        assert block["seed"] == 410 and block["frame_count"] == 49
        assert job.motion.prepared is False and not job.motion.interpolation
    strengths = {(job.arm_id, job.motion.controls["pose_strength"]) for job in plan.jobs}
    assert strengths == {("baseline", 1.0), ("motion", 1.2)}
    # Admission is one all-or-none submit_njrs call and records the driving identity in the manifest.
    admission = ctl.submit_eval_run(plan)
    assert len(service.calls) == 1 and len(service.calls[0]) == 4
    manifest = json.loads(admission.manifest_path.read_text())
    assert manifest["suite"]["schema"] == SUITE_SCHEMA_V2
    assert (
        manifest["cases"][0]["motion"]["driving"]["sha256"]
        == plan.jobs[0].motion.driver_original_sha256
    )
    assert manifest["jobs"][0]["motion"]["controls"]["pose_prompt"]
    assert manifest["jobs"][0]["motion"]["prepared_source_sha256"]


def test_a_workflow_that_takes_no_driving_video_refuses_the_motion_case_and_the_whole_run(
    tmp_path,
) -> None:
    ti2v = {
        "arm_id": "prompt_only",
        "backend": "video_workflow",
        "form": {
            "workflow_id": "wan22_ti2v_5b_i2v_v1",
            "workflow_version": "1.2.0",
            "frame_count": 49,
        },
    }
    ctl, service, plan = _plan(tmp_path, arms=[drive_arm(), ti2v])

    assert not plan.eligible
    assert any(
        "takes no driving video" in error and "prompt_only" in error for error in plan.errors
    )
    with pytest.raises(EvalRunRefused, match="nothing was queued"):
        ctl.submit_eval_run(plan)
    assert service.calls == []
    # Nothing was dropped silently: the refused arm produced no job at all (not a driver-less one).
    assert {job.arm_id for job in plan.jobs} == {"baseline"}


def test_one_invalid_arm_prevents_whole_suite_admission(tmp_path) -> None:
    broken = drive_arm("broken", pose_strength=99)
    ctl, service, plan = _plan(tmp_path, arms=[drive_arm(), broken])

    assert not plan.eligible and any(
        "Pose Strength must be between" in error for error in plan.errors
    )
    with pytest.raises(EvalRunRefused):
        ctl.submit_eval_run(plan)
    assert service.calls == []


def test_a_driver_changed_after_the_preview_is_not_accepted_as_the_validated_input(
    tmp_path,
) -> None:
    cases, driver = _cases(tmp_path, count=1)
    ctl, service, plan = _plan(tmp_path, cases=cases)
    assert plan.eligible
    driver.write_bytes(b"driver-edited")

    with pytest.raises(EvalRunRefused, match="driving video changed after the preview"):
        ctl.submit_eval_run(plan)
    assert service.calls == []


def test_a_source_image_changed_after_the_preview_is_not_accepted(tmp_path) -> None:
    cases, _ = _cases(tmp_path, count=1)
    ctl, service, plan = _plan(tmp_path, cases=cases)
    plan.suite.cases[0].image_path.write_bytes(b"not the same image")
    with pytest.raises(EvalRunRefused, match="changed after the preview"):
        ctl.submit_eval_run(plan)
    assert service.calls == []


def test_prepared_derivatives_are_shared_only_where_the_contract_is_identical(tmp_path) -> None:
    calls: list[dict] = []

    def preparer(spec, form, request, output_root):
        calls.append({"version": spec.workflow_version, "frames": form.get("frame_count")})
        return fake_prepared_record(spec, form, request, output_root)

    cases, _ = _cases(
        tmp_path,
        count=2,
        preparation={"mode": "workflow_prepared", "fps_conversion": "workflow_rate"},
    )
    arms = [drive_arm("short", frame_count=49), drive_arm("long", frame_count=81)]
    ctl, service, plan = _plan(tmp_path, cases=cases, arms=arms, preparer=preparer)

    assert plan.eligible, plan.summary()
    # Two subjects share the derivative within each length; the two lengths are two contracts.
    assert sorted(call["frames"] for call in calls) == [49, 81]
    short = {job.motion.driver_effective_sha256 for job in plan.jobs if job.arm_id == "short"}
    long = {job.motion.driver_effective_sha256 for job in plan.jobs if job.arm_id == "long"}
    assert len(short) == 1 and len(long) == 1 and short != long
    assert all(job.motion.prepared and job.motion.ordered_frames_sha256 for job in plan.jobs)
    # The difference is disclosed, not hidden.
    assert "different driving contracts" in plan.summary()
    ctl.submit_eval_run(plan)
    assert len(service.calls) == 1


def test_a_failed_preparation_makes_the_run_unqueueable(tmp_path) -> None:
    class Failed:
        prepared = False
        record = None
        message = "ffmpeg is unavailable"

    cases, _ = _cases(tmp_path, count=1, preparation={"mode": "workflow_prepared"})
    ctl, service, plan = _plan(tmp_path, cases=cases, preparer=lambda *_a: Failed())
    assert not plan.eligible and any("ffmpeg is unavailable" in error for error in plan.errors)


def test_a_prepared_derivative_changed_after_the_preview_is_refused(tmp_path) -> None:
    cases, _ = _cases(tmp_path, count=1, preparation={"mode": "workflow_prepared"})
    ctl, service, plan = _plan(tmp_path, cases=cases, preparer=partial(fake_prepared_record))
    assert plan.eligible, plan.summary()
    from pathlib import Path

    Path(plan.jobs[0].motion.driver_effective_path).write_bytes(b"tampered derivative")
    with pytest.raises(EvalRunRefused, match="prepared driving video changed after the preview"):
        ctl.submit_eval_run(plan)
    assert service.calls == []


def test_a_manifest_is_not_left_behind_when_a_motion_run_is_refused(tmp_path) -> None:
    cases, driver = _cases(tmp_path, count=1)
    ctl, service, plan = _plan(tmp_path, cases=cases)
    driver.write_bytes(b"x")
    with pytest.raises(EvalRunRefused):
        ctl.submit_eval_run(plan)
    assert not list((tmp_path / "output").rglob(RUN_MANIFEST_NAME))
