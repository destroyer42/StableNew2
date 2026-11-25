"""PR-VID-MOTION-420 Workstream F/G: alignment as an explicit experimental variable of the existing eval kit.

Structural checks only: the real suite parser, authoring validator, production builders, run service and integrity
vocabulary prove an aligned-versus-unaligned plan is well formed and comparable.  Real FFmpeg builds the aligned
derivative from a disposable clip (skipped without it).  Nothing is generated, no runtime starts, no media is
committed.
"""

from __future__ import annotations

import copy
import json
import shutil
from pathlib import Path
from typing import Any

import pytest
from PIL import Image

from src.video import video_eval_integrity as integrity
from src.video.motion_alignment_preparation import prepare_aligned_for_form
from src.video.video_eval_authoring import EvalSuiteDraft, EvalWorkflowCatalog, validate_draft
from src.video.video_eval_integrity import (
    ComparisonKind,
    IntegrityClass,
    classify_group,
    classify_pair,
)
from src.video.video_eval_motion import (
    MotionBindingError,
    canonical_sha256,
    driving_context_sha256,
    parse_motion,
    record_identity,
)
from src.video.video_eval_run import EvalRunRefused
from src.video.video_eval_suite import MAX_EVAL_JOBS, EvalSuiteError, load_eval_suite
from tests.video.motion_410_support import (
    controller,
    drive_arm,
    make_image,
    motion_block,
    write_suite,
)
from tests.video.motion_420_support import moving_square_clip, needs_ffmpeg

EXAMPLES = Path(__file__).resolve().parents[2] / "docs" / "runbooks" / "examples"
TEMPLATES = {
    "pilot": ("video_eval_motion_alignment_pilot.suite.json", 2),
    "diagnostic": ("video_eval_motion_alignment_diagnostic.suite.json", 8),
    "full": ("video_eval_motion_alignment_full.suite.json", 16),
}
ALIGNMENT = {"scale": 0.9, "translate_x": 14.0, "translate_y": -8.0, "mirror": False}


def _arm(arm_id: str, mode: str, **extra: Any) -> dict[str, Any]:
    arm = drive_arm(arm_id, frame_count=17)
    arm["form"]["motion_alignment"] = mode
    arm["form"].update(extra)
    return arm


def _real_case(
    tmp_path: Path, *, alignment: dict[str, Any] | None = None, mode="workflow_prepared"
) -> list[dict]:
    """One case over a real moving-subject clip and a real 600x900 source image."""

    folder = tmp_path / "suite"
    (folder / "motion").mkdir(parents=True, exist_ok=True)
    (folder / "images").mkdir(parents=True, exist_ok=True)
    clip = moving_square_clip(folder / "motion", "drive.mp4")
    Image.new("RGB", (600, 900), (30, 90, 140)).save(folder / "images" / "s.png")
    block = motion_block(
        clip,
        preparation={"mode": mode, "fps_conversion": "none"},
        window={"start_frame": 0, "end_frame": None},
    )
    if alignment is not None:
        block["alignment"] = dict(alignment)
    return [
        {
            "case_id": "pos_a",
            "image": "images/s.png",
            "prompt": "a woman in a studio",
            "motion": block,
        }
    ]


# ------------------------------------------------------------------------------ the declaration


def test_a_case_declares_an_alignment_that_is_not_part_of_the_motions_identity(tmp_path):
    clip = tmp_path / "suite" / "motion" / "d.mp4"
    clip.parent.mkdir(parents=True)
    clip.write_bytes(b"driver")
    plain = parse_motion(
        motion_block(clip, preparation={"mode": "workflow_prepared"}), "c", tmp_path
    )
    aligned = parse_motion(
        motion_block(clip, preparation={"mode": "workflow_prepared"}, alignment=ALIGNMENT),
        "c",
        tmp_path,
    )
    assert plain.alignment is None and aligned.alignment == ALIGNMENT
    assert aligned.to_record()["alignment"] == ALIGNMENT and "alignment" not in plain.to_record()
    # the same driver, window, preparation, prompt and category are the same motion, aligned or not
    assert aligned.identity == plain.identity == record_identity(aligned.to_record())
    intent = aligned.alignment_intent()
    assert intent is not None and (intent.scale, intent.translate_x, intent.mirror) == (
        0.9,
        14.0,
        False,
    )


@pytest.mark.parametrize(
    ("alignment", "message"),
    [
        ({"scale": 9.0}, "scale must be between"),
        ({"scale": float("nan")}, "finite number"),
        ({"translate_x": "12"}, "finite number"),
        ({"mirror": 1}, "true or false"),
        ({"rotate": 10}, "unknown field"),
        ({"scale": True}, "finite number"),
    ],
)
def test_an_unusable_declaration_is_refused_never_clamped(tmp_path, alignment, message):
    clip = tmp_path / "d.mp4"
    clip.write_bytes(b"driver")
    with pytest.raises(MotionBindingError, match=message):
        parse_motion(
            motion_block(clip, preparation={"mode": "workflow_prepared"}, alignment=alignment),
            "c",
            tmp_path,
        )


def test_an_alignment_needs_a_prepared_driving_context(tmp_path):
    clip = tmp_path / "d.mp4"
    clip.write_bytes(b"driver")
    with pytest.raises(MotionBindingError, match="needs preparation.mode"):
        parse_motion(motion_block(clip, alignment=ALIGNMENT), "c", tmp_path)


def test_an_arm_may_only_choose_none_or_case(tmp_path):
    clip = tmp_path / "suite" / "motion" / "d.mp4"
    clip.parent.mkdir(parents=True)
    clip.write_bytes(b"driver")
    make_image(tmp_path / "suite" / "images" / "a.png")
    block = motion_block(clip, preparation={"mode": "workflow_prepared"}, alignment=ALIGNMENT)
    cases = [{"case_id": "c", "image": "images/a.png", "prompt": "p", "motion": block}]
    with pytest.raises(EvalSuiteError, match="motion_alignment must be one of"):
        load_eval_suite(write_suite(tmp_path, cases, [_arm("x", "sometimes")]))
    suite = load_eval_suite(
        write_suite(tmp_path, cases, [_arm("base", "none"), _arm("al", "case")])
    )
    assert [a.overrides["motion_alignment"] for a in suite.arms] == ["none", "case"]


# ------------------------------------------------------------------------------ comparison integrity


def _settings(**changes: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "workflow_id": "wan_animate2_drive_i2v_v1",
        "workflow_version": "1.2.0",
        "frame_count": 49,
        "fps": 24,
        "seed": 420,
        "driver_original_sha256": "a" * 64,
        "driver_effective_sha256": "b" * 64,
        "ordered_frames_sha256": "c" * 64,
        "preparation_settings": {
            "start_frame": 0,
            "end_frame": None,
            "fps_conversion": "workflow_rate",
        },
        "interpolation": False,
        "controls": {"pose_prompt": "waves", "pose_strength": 1.0},
        "alignment": None,
        "temporal_plan_sha256": "d" * 64,
    }
    base.update(changes)
    return base


def _aligned(**changes: Any) -> dict[str, Any]:
    values: dict[str, Any] = {
        "alignment": "e" * 64,
        "driver_effective_sha256": "f" * 64,
        "ordered_frames_sha256": "0" * 64,
    }
    values.update(changes)
    return _settings(**values)


def test_an_aligned_arm_against_an_unaligned_one_is_the_alignment_comparison():
    pair = classify_pair(_settings(), _aligned())
    assert pair.kind is ComparisonKind.ALIGNMENT
    assert pair.integrity is IntegrityClass.VERIFIED_COMPARABLE
    assert set(pair.varied) == set(integrity.ALIGNMENT_EXPECTED_KEYS)
    assert "only the declared spatial alignment differs" in pair.disclosed[0]
    assert integrity.KIND_LABELS[pair.kind] == "Spatial alignment comparison"
    # two different declared alignments are also an alignment comparison
    assert (
        classify_pair(
            _aligned(),
            _aligned(
                alignment="9" * 64, driver_effective_sha256="8" * 64, ordered_frames_sha256="7" * 64
            ),
        ).kind
        is ComparisonKind.ALIGNMENT
    )


@pytest.mark.parametrize(
    ("change", "expected"),
    [
        ({"seed": 421}, "must stay fixed"),
        ({"driver_original_sha256": "9" * 64}, "must stay fixed"),
        ({"controls": {"pose_prompt": "other", "pose_strength": 1.0}}, "must stay fixed"),
        ({"temporal_plan_sha256": "1" * 64}, "temporal frame selection differs"),
        (
            {
                "preparation_settings": {
                    "start_frame": 4,
                    "end_frame": None,
                    "fps_conversion": "none",
                }
            },
            "temporal frame selection differs",
        ),
    ],
)
def test_an_unrelated_change_is_never_accepted_as_part_of_the_alignment_intervention(
    change, expected
):
    pair = classify_pair(_settings(), _aligned(**change))
    assert pair.integrity is IntegrityClass.INCOMPARABLE
    assert expected in pair.reasons[0]


def test_alignment_together_with_another_control_is_disclosed_as_not_separable():
    pair = classify_pair(
        _settings(), _aligned(controls={"pose_prompt": "waves", "pose_strength": 1.2})
    )
    assert pair.kind is ComparisonKind.MULTI_ARM
    assert pair.integrity is IntegrityClass.VERIFIED_WITH_DISCLOSED_DIFFERENCES
    assert any("alignment differs together with other settings" in line for line in pair.disclosed)
    other = classify_pair(_settings(), _aligned(workflow_version="1.3.0"))
    assert other.kind is ComparisonKind.MULTI_ARM and other.integrity.comparable


def test_existing_comparisons_keep_their_classification_when_nothing_is_aligned():
    assert classify_pair(_settings(), _settings()).integrity is IntegrityClass.VERIFIED_COMPARABLE
    longer = classify_pair(_settings(), _settings(frame_count=81, temporal_plan_sha256="2" * 64))
    assert (
        longer.integrity is IntegrityClass.VERIFIED_WITH_DISCLOSED_DIFFERENCES
    )  # as it was in Phase 2
    one = classify_pair(
        _settings(), _settings(controls={"pose_prompt": "waves", "pose_strength": 1.2})
    )
    assert (
        one.kind is ComparisonKind.ONE_VARIABLE
        and one.integrity is IntegrityClass.VERIFIED_COMPARABLE
    )


def test_cross_subject_groups_disclose_per_subject_alignments_and_never_generalize_them():
    group = classify_group(
        {
            "a": _aligned(),
            "b": _aligned(
                alignment="9" * 64, driver_effective_sha256="8" * 64, ordered_frames_sha256="7" * 64
            ),
        },
        {"a": "subject-a", "b": "subject-b"},
    )
    assert group.integrity is IntegrityClass.VERIFIED_WITH_DISCLOSED_DIFFERENCES
    assert "alignment" in group.disclosed[0]


def test_ratings_are_bound_to_the_frozen_alignment_and_unaligned_digests_are_unchanged():
    kwargs = {
        "source_sha256": "1" * 64,
        "driver_original_sha256": "a" * 64,
        "driver_effective_sha256": "b" * 64,
        "motion_prompt": "waves",
    }
    plain = _settings()
    legacy = canonical_sha256(
        {
            "source": kwargs["source_sha256"],
            "driver_original": kwargs["driver_original_sha256"],
            "driver_effective": kwargs["driver_effective_sha256"],
            "workflow": [plain["workflow_id"], plain["workflow_version"]],
            "length": [plain["frame_count"], plain["fps"]],
            "preparation": plain["preparation_settings"],
            "ordered_frames": plain["ordered_frames_sha256"],
            "motion_prompt": "waves",
        }
    )
    assert (
        driving_context_sha256(facts_settings=plain, **kwargs) == legacy
    )  # an old rating still applies
    aligned = driving_context_sha256(facts_settings=_aligned(), **kwargs)
    other = driving_context_sha256(facts_settings=_aligned(alignment="9" * 64), **kwargs)
    assert (
        len({legacy, aligned, other}) == 3
    )  # a judgment never silently moves to another alignment


# ------------------------------------------------------------------------------ the plan, end to end


def _write(tmp_path: Path, cases: list[dict], arms: list[dict]) -> Path:
    return write_suite(tmp_path, cases, arms)


@needs_ffmpeg
def test_an_aligned_versus_unaligned_plan_is_valid_comparable_and_needs_no_gpu(tmp_path):
    cases = _real_case(tmp_path, alignment=ALIGNMENT)
    path = _write(tmp_path, cases, [_arm("unaligned", "none"), _arm("aligned", "case")])
    ctl, service = controller(tmp_path)
    plan = ctl.preview_eval_run(path)
    assert plan.errors == () and len(plan.jobs) == 2
    base, cand = (next(j for j in plan.jobs if j.arm_id == arm) for arm in ("unaligned", "aligned"))
    assert base.motion.alignment is None and cand.motion.alignment["scale"] == 0.9
    assert base.motion.driver_original_sha256 == cand.motion.driver_original_sha256
    assert base.motion.temporal_plan_sha256 == cand.motion.temporal_plan_sha256
    assert base.motion.driver_effective_sha256 != cand.motion.driver_effective_sha256
    assert (base.seed, base.frame_count) == (cand.seed, cand.frame_count)
    pair = classify_pair(base.motion.settings(), cand.motion.settings())
    assert pair.kind is ComparisonKind.ALIGNMENT and pair.integrity.comparable
    notes = [
        line
        for line in plan.summary().splitlines()
        if "spatial alignment is an intervention" in line
    ]
    assert (
        notes
        and "aligned applies scale 0.9" in notes[0]
        and "unaligned use(s) no alignment" in notes[0]
    )
    assert service.calls == []  # a preview queues nothing
    # the inputs the preview froze include the aligned clip and the one source image
    labels = {label for label, _p, _s in cand.inputs}
    assert {"prepared source image", "driving video", "prepared driving video"} <= labels
    admission = ctl.submit_eval_run(plan)
    assert len(service.calls) == 1 and len(service.calls[0]) == 2
    manifest = json.loads(admission.manifest_path.read_text("utf-8"))
    motion = {job["arm_id"]: job["motion"] for job in manifest["jobs"]}
    assert (
        motion["aligned"]["alignment_detail"]["transform_sha256"]
        == cand.motion.alignment["transform_sha256"]
    )
    assert motion["unaligned"]["alignment_detail"] is None
    assert manifest["cases"][0]["motion"]["alignment"] == ALIGNMENT


@needs_ffmpeg
def test_an_arm_that_applies_a_missing_or_unsupported_alignment_is_refused_not_degraded(tmp_path):
    no_alignment = _real_case(tmp_path)
    ctl, service = controller(tmp_path)
    plan = ctl.preview_eval_run(_write(tmp_path, no_alignment, [_arm("aligned", "case")]))
    assert any("declares none" in error for error in plan.errors) and not plan.jobs
    with pytest.raises(EvalRunRefused):
        ctl.submit_eval_run(plan)
    shutil.rmtree(tmp_path / "suite")
    cases = _real_case(tmp_path, alignment=ALIGNMENT)
    fun = _arm(
        "fun", "case", workflow_id="wan22_fun_control_5b_canny_i2v_v1", workflow_version="1.1.0"
    )
    plan = ctl.preview_eval_run(_write(tmp_path, cases, [fun]))
    assert plan.errors and "edges" in plan.errors[0] and not plan.jobs
    assert service.calls == []


@needs_ffmpeg
def test_a_dropped_or_altered_alignment_is_caught_against_the_compiled_job(tmp_path):
    cases = _real_case(tmp_path, alignment=ALIGNMENT)
    path = _write(tmp_path, cases, [_arm("unaligned", "none"), _arm("aligned", "case")])
    ctl, _service = controller(tmp_path)

    def plain_instead(spec, form, request, output_root, cancel=None):
        from src.video.motion_source_preparation import prepare_for_form

        return prepare_for_form(
            spec, form, {**request, "start": 0, "end": None, "unit": "frames"}, output_root
        )

    ctl._motion_aligner = plain_instead  # type: ignore[attr-defined]
    plan = ctl.preview_eval_run(path)
    assert any("differs from the arm's request" in error for error in plan.errors)

    def altered(spec, form, request, output_root, cancel=None):
        from src.video.motion_alignment import AlignmentIntent

        return prepare_aligned_for_form(
            spec, form, {**request, "intent": AlignmentIntent(scale=1.2)}, output_root
        )

    ctl2, _ = controller(tmp_path)
    ctl2._motion_aligner = altered  # type: ignore[attr-defined]
    plan = ctl2.preview_eval_run(path)
    assert any("froze a different alignment" in error for error in plan.errors)


# ------------------------------------------------------------------------------ campaign templates


def _materialize(name: str, tmp_path: Path) -> Path:
    file, _jobs = TEMPLATES[name]
    data = json.loads((EXAMPLES / file).read_text("utf-8"))
    folder = tmp_path / name
    folder.mkdir(parents=True)
    for index, case in enumerate(data["cases"]):
        make_image(folder / case["image"], color=(20 * index + 10, 80, 120))
        driver = folder / case["motion"]["driving"]["path"]
        driver.parent.mkdir(parents=True, exist_ok=True)
        driver.write_bytes(case["motion"]["category"].encode())
    target = folder / file
    shutil.copy(EXAMPLES / file, target)
    return target


@pytest.mark.parametrize("name", TEMPLATES)
def test_each_template_loads_validates_and_keeps_to_the_documented_bounds(name, tmp_path):
    path = _materialize(name, tmp_path)
    suite = load_eval_suite(path)
    assert suite.job_count == TEMPLATES[name][1] <= 16 <= MAX_EVAL_JOBS
    result = validate_draft(EvalSuiteDraft.open(path), EvalWorkflowCatalog())
    assert not result.errors, result.errors
    assert all(
        case.motion is not None and case.motion.alignment is not None for case in suite.cases
    )
    assert suite.seed == 420 and len({case.motion.driving_sha256 for case in suite.cases}) <= 4


def test_the_arms_differ_only_in_whether_the_cases_alignment_is_applied():
    for file, _jobs in TEMPLATES.values():
        data = json.loads((EXAMPLES / file).read_text("utf-8"))
        unaligned, aligned = (copy.deepcopy(arm["form"]) for arm in data["arms"])
        assert (unaligned.pop("motion_alignment"), aligned.pop("motion_alignment")) == (
            "none",
            "case",
        )
        assert (
            unaligned == aligned
        )  # same workflow, version, length, controls, opt-in: one intervention
        assert data["baseline_arm"] == "unaligned"


def test_the_templates_hold_no_machine_specific_paths_and_no_operator_media():
    for file, _jobs in TEMPLATES.values():
        text = (EXAMPLES / file).read_text("utf-8")
        assert not any(marker in text for marker in ("C:\\", "C:/", "/Users/", "/home/", "E:\\"))
        data = json.loads(text)
        for case in data["cases"]:
            assert not Path(case["image"]).is_absolute()
            assert not Path(case["motion"]["driving"]["path"]).is_absolute()
            assert "sha256" not in case["motion"]["driving"]  # bound by the operator's own files
    assert not list(EXAMPLES.glob("*.mp4")) and not list(EXAMPLES.glob("*.png"))


def test_the_designs_nest_the_pilot_in_the_diagnostic_sample_in_the_full_design(tmp_path):
    cells = {}
    for name, (file, _jobs) in TEMPLATES.items():
        data = json.loads((EXAMPLES / file).read_text("utf-8"))
        cells[name] = {(c["case_id"], a["arm_id"]) for c in data["cases"] for a in data["arms"]}
    assert cells["pilot"] < cells["diagnostic"] < cells["full"] and len(cells["full"]) == 16
    full = json.loads((EXAMPLES / TEMPLATES["full"][0]).read_text("utf-8"))
    scenarios = {case["case_id"].rsplit("_subject_", 1)[0] for case in full["cases"]}
    assert scenarios == {"position", "scale", "locomotion", "start_pose"}
    for scenario in scenarios:
        pair = [c for c in full["cases"] if c["case_id"].startswith(scenario + "_")]
        assert len(pair) == 2 and len({c["image"] for c in pair}) == 2
        # an alignment belongs to one source image: the two subjects do not share numbers
        assert pair[0]["motion"]["alignment"] != pair[1]["motion"]["alignment"]


def test_the_suite_editor_keeps_an_alignment_and_never_copies_it_to_another_subject(tmp_path):
    path = _materialize("pilot", tmp_path)
    draft = EvalSuiteDraft.open(path)
    assert draft.cases[0]["motion"]["alignment"]["scale"] == 1.0  # opened and kept as written
    assert draft.arms[1]["form"]["motion_alignment"] == "case"
    copy_for_other_subject = draft.duplicate_case_for_source(0, {"image": "images/subject_b.png"})
    assert "alignment" not in copy_for_other_subject["motion"]  # it must be aligned for itself
    assert copy_for_other_subject["motion"]["driving"] == draft.cases[0]["motion"]["driving"]
    assert "alignment" in draft.cases[0]["motion"]  # the original keeps its own


def test_the_review_and_report_state_the_frozen_alignment_and_never_call_it_success():
    from src.video.video_eval_motion_html import _alignment_html
    from src.video.video_eval_motion_review import _driver_role

    detail = {
        "scale": 0.9,
        "translate_x": 14.0,
        "translate_y": -8.0,
        "mirror": True,
        "transform_sha256": "ab" * 32,
    }
    job = {
        "prepared": True,
        "driver_effective_path": "aligned.mp4",
        "driver_effective_sha256": "c" * 64,
        "driver_original_sha256": "d" * 64,
        "driver_original_path": "orig.mp4",
        "alignment_detail": detail,
    }
    case = {"motion": {"driving": {"path": "orig.mp4"}}}
    role = _driver_role(case, job, changed=False)
    assert role.label == "Driving reference (aligned effective input)"
    assert "scale 0.9" in role.note and "mirrored" in role.note and "abababababab" in role.note
    assert "not evidence that the generated motion succeeded" in role.note
    plain = _driver_role(case, {**job, "alignment_detail": None}, changed=False)
    assert plain.label == "Driving reference (effective input)" and "aligned" not in plain.note
    html = _alignment_html(detail)
    assert (
        "spatially aligned: scale 0.9" in html
        and "mirrored" in html
        and _alignment_html(None) == ""
    )
