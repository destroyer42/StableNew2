"""Authoring tests use local fixtures, the real suite parser and the offline catalog."""

import json
import os
import subprocess
from copy import deepcopy
from datetime import date
from pathlib import Path

import pytest
from PIL import Image

from src.video.video_eval_authoring import (
    EvalSuiteDraft,
    EvalWorkflowCatalog,
    bind_source,
    publish_validated_suite,
    validate_draft,
)
from src.video.video_eval_suite import EvalSuiteError, file_sha256, load_eval_suite

EXAMPLES = Path(__file__).resolve().parents[2] / "docs/runbooks/examples"
DAY = date(2026, 11, 23)


def _image(path, color="red"):
    Image.new("RGB", (32, 48), color=color).save(path)
    return path


def _bound_template(tmp_path, name="three_engines"):
    path = EXAMPLES / f"video_eval_{name}.suite.json"
    draft = EvalSuiteDraft.open(path)
    for i, case in enumerate(draft.cases):
        case.update(bind_source(_image(tmp_path / f"image{i}.png", (i * 16, i * 4, 30))))
    return draft


def test_template_opens_with_all_unresolved_cases_and_validation_keeps_the_draft():
    draft = EvalSuiteDraft.open(EXAMPLES / "video_eval_three_engines.suite.json")
    before = deepcopy(draft.data)
    result = validate_draft(draft, EvalWorkflowCatalog())
    assert draft.data == before
    assert draft.job_count == 9 and result.record is None
    for case in draft.cases:
        assert any(case["case_id"] in error for error in result.errors)


def test_bind_three_sources_and_save_independent_versions_without_overwriting(tmp_path):
    draft = _bound_template(tmp_path)
    original = draft.source.read_bytes()
    for arm in draft.arms:
        arm["form"]["frame_count"] = 49
    draft.data["baseline_arm"] = draft.arms[-1]["arm_id"]
    result = validate_draft(draft, EvalWorkflowCatalog())
    assert not result.errors
    root = tmp_path / "plans"
    folder = root / "video"
    folder.mkdir(parents=True)
    occupied = folder / f"20261123_{draft.data['suite_id']}_v001.suite.json"
    occupied.write_bytes(b"existing bytes")
    first = publish_validated_suite(result, root, day=DAY)
    second = publish_validated_suite(result, root, day=DAY)
    assert first.name.endswith("_v002.suite.json") and second.name.endswith("_v003.suite.json")
    assert occupied.read_bytes() == b"existing bytes" and draft.source.read_bytes() == original
    saved = load_eval_suite(first)
    assert saved.job_count == 9 and saved.baseline_arm_id == draft.arms[-1]["arm_id"]
    assert len({case.image_sha256 for case in saved.cases}) == 3
    for source, case in zip(draft.cases, saved.cases, strict=True):
        assert case.image_path == Path(source["image"])
        assert case.image_sha256 == source["image_sha256"] == file_sha256(case.image_path)
    assert [arm.overrides for arm in saved.arms] == [arm["form"] for arm in draft.arms]


def test_relative_path_is_rebased_and_changed_pin_requires_explicit_rebinding(tmp_path):
    source_folder = tmp_path / "templates"
    source_folder.mkdir()
    image = _image(source_folder / "image.png")
    example = EXAMPLES / "video_eval_three_engines.suite.json"
    source = source_folder / "original.suite.json"
    draft = EvalSuiteDraft.open(example)
    draft.cases[:] = [draft.cases[0]]
    draft.cases[0].update(image="image.png", image_sha256=file_sha256(image))
    source.write_text(json.dumps(draft.data), encoding="utf-8")
    draft = EvalSuiteDraft.open(source)
    catalog = EvalWorkflowCatalog()
    root = tmp_path / "plans"
    validation = validate_draft(draft, catalog)
    assert not validation.errors
    first = publish_validated_suite(validation, root, day=DAY)
    assert load_eval_suite(first).cases[0].image_path == image.resolve()
    old_pin = draft.cases[0]["image_sha256"]
    _image(image, "blue")
    assert "Rebind" in "\n".join(validate_draft(draft, catalog).errors)
    assert draft.cases[0]["image_sha256"] == old_pin
    with pytest.raises(EvalSuiteError, match="changed"):
        publish_validated_suite(validation, root, day=DAY)
    draft.cases[0].update(bind_source(image))
    assert draft.cases[0]["image_sha256"] != old_pin
    assert not validate_draft(draft, catalog).errors


def test_collects_bad_identifiers_baseline_workflow_and_image_errors(tmp_path):
    draft = _bound_template(tmp_path)
    draft.cases[0]["case_id"] = draft.cases[1]["case_id"]
    draft.cases[1]["image"] = str(tmp_path / "bad.png")
    (tmp_path / "bad.png").write_bytes(b"not an image")
    draft.cases[1].pop("image_sha256")
    draft.cases[2]["prompt"] = ""
    draft.arms[0]["form"]["workflow_version"] = "99.0"
    draft.arms[1]["form"]["frame_count"] = 18
    draft.data.update(baseline_arm="missing", seed="-4", suite_id="../other")
    result = validate_draft(draft, EvalWorkflowCatalog())
    reasons = "\n".join(result.errors)
    for reason in (
        "suite_id",
        "Duplicate case ID",
        "baseline",
        "Shared seed",
        "Cannot read image",
        "Enter a motion prompt",
        "99.0",
        "cannot generate 18 frames",
    ):
        assert reason in reasons
    with pytest.raises(EvalSuiteError, match="Resolve validation errors"):
        publish_validated_suite(result, tmp_path / "plans")
    assert not (tmp_path / "plans").exists()


def test_sequence_round_trip_checks_governance_segment_frames_and_svd_compatibility(tmp_path):
    draft = _bound_template(tmp_path, "a14b_svi_sequence")
    catalog = EvalWorkflowCatalog()
    original = load_eval_suite(publish_validated_suite(validate_draft(draft, catalog), tmp_path))
    assert [s.prompt for s in original.cases[0].segments] == [
        s["prompt"] for s in draft.cases[0]["segments"]
    ]
    assert [arm.overrides for arm in original.arms] == [arm["form"] for arm in draft.arms]
    draft.arms[1]["form"].pop("experimental_opt_in")
    draft.cases[0]["segments"][1]["frame_count"] = 5
    draft.data["seed"] = 2**31 - 1
    draft.add_arm()["backend"] = "svd_native"
    result = validate_draft(draft, catalog)
    reasons = "\n".join(result.errors)
    assert "experimental" in reasons and "Segment 2" in reasons
    assert "cannot generate 5 frames" in reasons and "seed plus the segment offset" in reasons
    assert "native SVD cannot run sequence cases" in reasons


def test_cap_and_copy_are_independent(tmp_path):
    draft = _bound_template(tmp_path)
    old = draft.arms[0]
    extra = draft.add_arm(old)
    extra["form"]["frame_count"] = 49
    assert old["form"]["frame_count"] == 81
    for _ in range(14):
        draft.add_case()
    assert draft.job_count == 68
    assert "68 jobs exceeds the limit of 64." in validate_draft(draft, EvalWorkflowCatalog()).errors


def test_rejects_ambiguous_json_and_private_sidecar(tmp_path):
    path = tmp_path / "case.suite.json"
    path.write_text('{"schema": "test", "schema": "duplicate"}', encoding="utf-8")
    with pytest.raises(EvalSuiteError, match="Duplicate JSON field"):
        EvalSuiteDraft.open(path)
    with pytest.raises(EvalSuiteError, match="Private suite"):
        EvalSuiteDraft.open(tmp_path / "data.private.json")


def test_save_refuses_a_video_folder_link_outside_the_plan_root(tmp_path):
    draft = _bound_template(tmp_path)
    result = validate_draft(draft, EvalWorkflowCatalog())
    root = tmp_path / "plans"
    root.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    try:
        (root / "video").symlink_to(outside, target_is_directory=True)
    except OSError as exc:
        if os.name != "nt":
            pytest.skip(f"Directory symlinks unavailable: {exc}")
        junction = subprocess.run(
            ["cmd", "/c", "mklink", "/J", str(root / "video"), str(outside)],
            capture_output=True,
            check=False,
        )
        if junction.returncode != 0:
            pytest.skip("Directory symlinks and junctions are unavailable.")
    with pytest.raises(EvalSuiteError, match="inside the configured root"):
        publish_validated_suite(result, root)
    assert list(outside.iterdir()) == []


@pytest.mark.parametrize(
    "arm",
    [
        {
            "arm_id": "remote",
            "backend": "video_workflow",
            "form": {
                "workflow_id": "wan22_i2v_a14b_4step_v1",
                "workflow_version": "1.0.0",
                "end_anchor_path": "//host/share/anchor.png",
            },
        },
        {
            "arm_id": "remote",
            "backend": "svd_native",
            "svd": {
                "postprocess": {
                    "face_restore": {"facelib_model_root": "//host/share/model"},
                }
            },
        },
        {
            "arm_id": "remote",
            "backend": "svd_native",
            "svd": {
                "postprocess": {
                    "upscale": {"model_path_x2": "//host/share/model.bin"},
                }
            },
        },
    ],
)
def test_remote_arm_paths_are_refused_before_backend_file_validation(tmp_path, monkeypatch, arm):
    draft = _bound_template(tmp_path)
    draft.arms[:] = [arm]
    draft.data["baseline_arm"] = "remote"

    def no_probe(*_args, **_kwargs):
        pytest.fail("Authoring passed an untrusted path to a backend validator.")

    monkeypatch.setattr("src.video.video_eval_authoring.validate_svd_postprocess_config", no_probe)
    monkeypatch.setattr(
        "src.video.video_eval_authoring.VideoWorkflowNjrBuilder.validate_form_data", no_probe
    )
    assert "Choose a local file" in "\n".join(validate_draft(draft, EvalWorkflowCatalog()).errors)


def test_legacy_omitted_version_round_trips_but_blank_multiversion_identity_is_refused(tmp_path):
    draft = _bound_template(tmp_path)
    form = draft.arms[0]["form"]
    form.pop("workflow_version")
    catalog = EvalWorkflowCatalog()
    result = validate_draft(draft, catalog)
    saved = load_eval_suite(publish_validated_suite(result, tmp_path))
    assert "workflow_version" not in saved.arms[0].overrides
    form["workflow_version"] = ""
    assert "version is required" in "\n".join(validate_draft(draft, catalog).errors)
