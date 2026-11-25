"""PR-VID-MOTION-410 Workstream B: authoring driving-motion suites with the existing editor infrastructure."""

from __future__ import annotations

import json
from copy import deepcopy
from datetime import date
from types import SimpleNamespace

import pytest

from src.video.video_eval_authoring import (
    EvalSuiteDraft,
    EvalWorkflowCatalog,
    bind_driving_video,
    bind_library_asset,
    bind_source,
    publish_validated_suite,
    validate_draft,
)
from src.video.video_eval_suite import (
    MAX_EVAL_JOBS,
    SUITE_SCHEMA,
    SUITE_SCHEMA_V2,
    EvalSuiteError,
    file_sha256,
    load_eval_suite,
)
from tests.video.motion_410_support import (
    drive_arm,
    make_image,
    make_video,
    motion_block,
    sha,
)

DAY = date(2026, 11, 24)
CATALOG = EvalWorkflowCatalog()


def _write(tmp_path, data, name="plan.suite.json"):
    path = tmp_path / "plans_in" / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data), encoding="utf-8")
    return path


def _draft(tmp_path, *, schema=SUITE_SCHEMA_V2, subjects=1, arms=None):
    driver = make_video(tmp_path / "media" / "head.mp4")
    cases = []
    for index in range(subjects):
        image = make_image(tmp_path / "media" / f"s{index}.png", color=(30 * index + 5, 60, 90))
        cases.append(
            {
                "case_id": f"c{index}",
                "image": str(image),
                "image_sha256": sha(image),
                "prompt": "a woman in a red coat",
                "motion": motion_block(driver),
            }
        )
    data = {
        "schema": schema,
        "suite_id": "motion-authoring",
        "seed": 410,
        "cases": cases,
        "arms": arms or [drive_arm("baseline"), drive_arm("motion", pose_strength=1.2)],
        "baseline_arm": "baseline",
    }
    return EvalSuiteDraft.open(_write(tmp_path, data)), driver


def test_a_motion_draft_validates_publishes_as_v2_and_round_trips(tmp_path) -> None:
    draft, driver = _draft(tmp_path)
    result = validate_draft(draft, CATALOG)
    assert not result.errors, result.errors
    assert result.record["schema"] == SUITE_SCHEMA_V2
    published = publish_validated_suite(result, tmp_path / "plans", day=DAY)

    saved = load_eval_suite(published)
    assert saved.schema == SUITE_SCHEMA_V2 and saved.cases[0].motion.driving_sha256 == sha(driver)
    # Re-opening the published file and saving again gives an equivalent plan (a new version, not a rewrite).
    again = validate_draft(EvalSuiteDraft.open(published), CATALOG)
    assert not again.errors and again.record["cases"] == result.record["cases"]
    second = publish_validated_suite(again, tmp_path / "plans", day=DAY)
    assert second != published and published.read_bytes() == published.read_bytes()


def test_a_legacy_v1_plan_round_trips_untouched_and_is_not_silently_rewritten(tmp_path) -> None:
    image = make_image(tmp_path / "media" / "p.png")
    data = {
        "schema": SUITE_SCHEMA,
        "suite_id": "legacy",
        "seed": 1,
        "cases": [
            {"case_id": "p", "image": str(image), "image_sha256": sha(image), "prompt": "turns"}
        ],
        "arms": [
            {
                "arm_id": "a",
                "backend": "video_workflow",
                "form": {
                    "workflow_id": "wan22_ti2v_5b_i2v_v1",
                    "workflow_version": "1.2.0",
                    "frame_count": 49,
                },
            }
        ],
        "baseline_arm": "a",
    }
    path = _write(tmp_path, data, "legacy.suite.json")
    before = path.read_bytes()

    draft = EvalSuiteDraft.open(path)
    result = validate_draft(draft, CATALOG)
    assert not result.errors, result.errors
    assert result.record["schema"] == SUITE_SCHEMA  # no motion case: it stays v1
    published = publish_validated_suite(result, tmp_path / "plans", day=DAY)
    assert path.read_bytes() == before  # the original plan is never touched
    assert json.loads(published.read_text())["schema"] == SUITE_SCHEMA
    assert load_eval_suite(published).schema == SUITE_SCHEMA


def test_adding_a_motion_case_to_a_v1_draft_publishes_a_new_v2_version_only(tmp_path) -> None:
    draft, driver = _draft(tmp_path, schema=SUITE_SCHEMA)
    # The v1 draft carries a motion block: validation upgrades the *new* record, never the file it came from.
    source_bytes = draft.source.read_bytes()
    result = validate_draft(draft, CATALOG)
    assert not result.errors and result.record["schema"] == SUITE_SCHEMA_V2
    assert draft.data["schema"] == SUITE_SCHEMA and draft.source.read_bytes() == source_bytes
    # The strict v1 loader refuses a v1 file that carries a driver; it is never ignored.
    with pytest.raises(EvalSuiteError, match="needs schema"):
        load_eval_suite(draft.source)


def test_a_workflow_without_a_driving_video_refuses_a_motion_case(tmp_path) -> None:
    ti2v = {
        "arm_id": "prompt_only",
        "backend": "video_workflow",
        "form": {
            "workflow_id": "wan22_ti2v_5b_i2v_v1",
            "workflow_version": "1.2.0",
            "frame_count": 49,
        },
    }
    draft, _ = _draft(tmp_path, arms=[drive_arm("baseline"), ti2v])
    result = validate_draft(draft, CATALOG)
    assert result.record is None
    assert any("prompt_only" in e and "takes no driving video" in e for e in result.errors) or any(
        "takes no driving video" in e for e in result.errors
    )
    # No arm was repaired or dropped to make the suite valid.
    assert len(draft.arms) == 2


def test_native_svd_is_refused_for_a_motion_case(tmp_path) -> None:
    svd = {"arm_id": "svd", "backend": "svd_native", "svd": {}}
    draft, _ = _draft(tmp_path, arms=[drive_arm("baseline"), svd])
    result = validate_draft(draft, CATALOG)
    assert any("native SVD takes no driving video" in error for error in result.errors)


def test_an_experimental_driving_workflow_needs_the_arms_explicit_opt_in(tmp_path) -> None:
    arm = drive_arm("baseline")
    arm["form"]["experimental_opt_in"] = False
    draft, _ = _draft(tmp_path, arms=[arm])
    result = validate_draft(draft, CATALOG)
    assert result.errors and any(
        "opt" in error.lower() or "experimental" in error.lower() for error in result.errors
    )


def test_a_driver_that_changed_since_it_was_pinned_needs_an_explicit_rebind(tmp_path) -> None:
    draft, driver = _draft(tmp_path)
    draft.cases[0]["motion"]["driving"]["sha256"] = sha(driver)
    driver.write_bytes(b"re-encoded driver")
    result = validate_draft(draft, CATALOG)
    assert any("changed since the suite pinned it" in error for error in result.errors)
    draft.cases[0]["motion"]["driving"].update(bind_driving_video(driver)["driving"])
    assert not validate_draft(draft, CATALOG).errors


def test_a_missing_driver_and_an_unsupported_file_type_are_refused(tmp_path) -> None:
    with pytest.raises(EvalSuiteError, match="Choose a video file"):
        bind_driving_video(tmp_path / "x.png")
    with pytest.raises(EvalSuiteError, match="not found"):
        bind_driving_video(tmp_path / "missing.mp4")
    draft, driver = _draft(tmp_path)
    driver.unlink()
    assert any(
        "driving video not found" in error for error in validate_draft(draft, CATALOG).errors
    )


def test_a_bound_local_video_is_recorded_as_a_local_video(tmp_path) -> None:
    driver = make_video(tmp_path / "x" / "walk.mp4", b"walk")
    bound = bind_driving_video(driver)
    assert bound["driving"]["sha256"] == sha(driver) and "library_asset" not in bound["driving"]


def _store(tmp_path, *, tamper=False, harvested=True):
    clip = make_video(tmp_path / "library" / "clip.mp4", b"library clip")
    asset = SimpleNamespace(
        asset_id="ma_001",
        display_name="Head turn",
        sha256=sha(clip),
        framing="medium",
        viewpoint="front",
        motion_direction="left to right",
        effective_motion_label="turns head",
        harvest=SimpleNamespace(
            original_sha256="a" * 64, start_frame=10, end_frame=59, cadence="native"
        )
        if harvested
        else None,
    )
    if tamper:
        clip.write_bytes(b"not the catalogued bytes")
    return SimpleNamespace(
        get=lambda asset_id: asset if asset_id == "ma_001" else None, asset_path=lambda _a: clip
    ), clip


def test_a_library_asset_is_bound_only_after_its_bytes_verify(tmp_path) -> None:
    store, clip = _store(tmp_path)
    suggested = bind_library_asset(store, "ma_001")
    assert suggested["driving"]["library_asset"] == {
        "asset_id": "ma_001",
        "sha256": sha(clip),
        "derived_from": {
            "original_sha256": "a" * 64,
            "start_frame": 10,
            "end_frame": 59,
            "cadence": "native",
        },
    }
    assert suggested["annotations"] == {"framing": "medium", "viewpoint": "front"}
    assert suggested["direction"] == "left to right" and suggested["action"] == "turns head"

    changed, _ = _store(tmp_path / "other", tamper=True)
    with pytest.raises(EvalSuiteError, match="no longer matches its recorded SHA-256"):
        bind_library_asset(changed, "ma_001")
    with pytest.raises(EvalSuiteError, match="No Motion Library asset"):
        bind_library_asset(store, "nope")


def test_a_library_bound_case_validates_publishes_and_loads_as_a_library_asset(tmp_path) -> None:
    store, clip = _store(tmp_path)
    draft, _ = _draft(tmp_path)
    motion = draft.cases[0]["motion"]
    motion.update(bind_library_asset(store, "ma_001"))
    motion["annotations"] = {"framing": "medium"}
    result = validate_draft(draft, CATALOG)
    assert not result.errors, result.errors
    saved = load_eval_suite(publish_validated_suite(result, tmp_path / "plans", day=DAY))
    case_motion = saved.cases[0].motion
    assert (
        case_motion.source == "library_asset"
        and case_motion.library_asset["derived_from"]["start_frame"] == 10
    )


def test_duplicating_a_motion_case_for_another_source_keeps_the_driver_and_adds_no_arm(
    tmp_path,
) -> None:
    draft, driver = _draft(tmp_path)
    arms_before = deepcopy(draft.arms)
    other = make_image(tmp_path / "media" / "other.png", color=(200, 10, 10))
    copy = draft.duplicate_case_for_source(0)

    assert copy["case_id"] == "case_1" and copy["image"] == "" and "image_sha256" not in copy
    assert copy["motion"] == draft.cases[0]["motion"] and draft.arms == arms_before
    result = validate_draft(draft, CATALOG)
    assert any(
        "Choose a source image" in error for error in result.errors
    )  # refused until the new image is bound
    copy.update(bind_source(other))
    result = validate_draft(draft, CATALOG)
    assert not result.errors, result.errors
    assert draft.job_count == 4
    suite = load_eval_suite(publish_validated_suite(result, tmp_path / "plans", day=DAY))
    assert {case.motion.driving_sha256 for case in suite.cases} == {sha(driver)}
    assert len({case.image_sha256 for case in suite.cases}) == 2


def test_the_per_run_job_limit_is_unchanged_and_applies_to_motion_suites(tmp_path) -> None:
    draft, _ = _draft(
        tmp_path, arms=[drive_arm(f"a{i}", pose_strength=1.0 + i / 100) for i in range(3)]
    )
    while len(draft.cases) * len(draft.arms) <= MAX_EVAL_JOBS:
        draft.duplicate_case_for_source(0)
    result = validate_draft(draft, CATALOG)
    assert any(f"exceeds the limit of {MAX_EVAL_JOBS}" in error for error in result.errors)
    assert MAX_EVAL_JOBS == 64


def test_a_malformed_motion_block_is_reported_per_case(tmp_path) -> None:
    draft, _ = _draft(tmp_path)
    draft.cases[0]["motion"]["category"] = "moonwalk"
    errors = validate_draft(draft, CATALOG).errors
    assert any("case c0" in e and "category must be one of" in e for e in errors)
    draft.cases[0]["motion"]["category"] = "head_turn"
    draft.cases[0]["motion"]["expected_outcome"] = ""
    assert any("expected_outcome is required" in e for e in validate_draft(draft, CATALOG).errors)


def test_the_new_motion_case_helper_starts_empty_and_is_refused_until_completed(tmp_path) -> None:
    draft, _ = _draft(tmp_path)
    case = draft.add_motion_case()
    assert case["motion"] == {} and draft.has_motion
    result = validate_draft(draft, CATALOG)
    assert any("driving is required" in error for error in result.errors)
    assert file_sha256(draft.source) == sha(draft.source)


def test_a_remote_or_device_driver_path_is_refused_before_it_is_opened(tmp_path) -> None:
    draft, _ = _draft(tmp_path)
    draft.cases[0]["motion"]["driving"] = {"path": "\\\\server\\share\\wave.mp4"}
    errors = validate_draft(draft, CATALOG).errors
    assert any("Choose a local file" in error for error in errors)


def test_an_exact_motion_workflow_needs_case_preparation_or_a_recorded_one(tmp_path) -> None:
    fun = {
        "arm_id": "fun",
        "backend": "video_workflow",
        "form": {
            "workflow_id": "wan22_fun_control_5b_canny_i2v_v1",
            "frame_count": 33,
            "experimental_opt_in": True,
        },
    }
    draft, _ = _draft(tmp_path, arms=[fun])
    unprepared = validate_draft(draft, CATALOG).errors
    assert any("requires an accepted Prepare Motion Source record" in error for error in unprepared)
    draft.cases[0]["motion"]["preparation"] = {
        "mode": "workflow_prepared",
        "fps_conversion": "workflow_rate",
    }
    prepared = validate_draft(draft, CATALOG).errors
    assert not any(
        "requires an accepted Prepare Motion Source record" in error for error in prepared
    )
