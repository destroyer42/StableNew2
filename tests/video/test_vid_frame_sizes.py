"""VID-FRAME: A14B full-picture sizes keep the whole picture, and a crop is never silent."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from PIL import Image

from src.controller.ports.default_runtime_ports import DefaultWorkflowRegistryPort
from src.pipeline.policy_warnings import CODE_VIDEO_SOURCE_CROPPED, accepted_warning_records
from src.video.video_eval_suite import load_eval_suite
from src.video.video_workflow_batch import BatchSource, VideoWorkflowBatchService
from src.video.video_workflow_intent import EXPERIMENTAL_OPT_IN_FIELD
from src.video.video_workflow_njr_builder import VideoWorkflowNjrBuilder
from src.video.workflow_catalog_wan_a14b import (
    WAN_A14B_FULL_PICTURE_ID,
    WAN_A14B_ID,
    WAN_A14B_VERSION,
    a14b_launch_attention,
)
from src.video.workflow_picker import is_offered
from src.video.workflow_registry import build_default_workflow_registry
from src.video.workflow_source_preparation import (
    passthrough_declared_workflow_source,
    resolve_declared_target,
)
from src.video.workflow_warnings import source_crop_warning, source_crop_warning_for_path

REGISTRY = build_default_workflow_registry()


FULL = (
    WAN_A14B_FULL_PICTURE_ID  # its own workflow id; the other argument is the approved A14B version
)


def _ids(choice: str) -> tuple[str, str]:
    return (FULL, WAN_A14B_VERSION) if choice == FULL else (WAN_A14B_ID, choice)


def _spec(choice: str) -> Any:
    return REGISTRY.get(*_ids(choice), allow_experimental=True)


def _policy(version: str) -> dict[str, Any]:
    return dict(_spec(version).backend_defaults["source_preparation"])


def _png(path: Path, size: tuple[int, int]) -> Path:
    Image.new("RGB", size, (12, 120, 200)).save(path, format="PNG")
    return path


def _builder(tmp_path: Path) -> VideoWorkflowNjrBuilder:
    return VideoWorkflowNjrBuilder(
        workflow_registry=DefaultWorkflowRegistryPort(),
        output_dir_provider=lambda: str(tmp_path / "out"),
    )


def _form(choice: str) -> dict[str, Any]:
    workflow_id, version = _ids(choice)
    return {
        "workflow_id": workflow_id,
        "workflow_version": version,
        "prompt": "the person waves",
        "seed": "7",
        EXPERIMENTAL_OPT_IN_FIELD: choice == FULL,
    }


def _target(version: str, width: int, height: int) -> tuple[int, int]:
    target = resolve_declared_target(_policy(version), width, height)[1]
    return target["width"], target["height"]


@pytest.mark.parametrize(
    ("source", "expected"),
    [
        ((768, 1024), (544, 720)),
        ((1024, 768), (720, 544)),
        ((1024, 1024), (624, 624)),
        ((720, 1280), (480, 832)),
        ((1920, 1080), (832, 480)),
        ((832, 1216), (512, 768)),
        ((1216, 832), (768, 512)),
    ],
)
def test_full_picture_version_chooses_the_size_that_crops_least(source, expected) -> None:
    assert _target(WAN_A14B_FULL_PICTURE_ID, *source) == expected


def test_every_declared_size_is_legal_and_no_larger_than_the_baseline() -> None:
    for size in _policy(WAN_A14B_FULL_PICTURE_ID)["aspect_targets"]:
        assert size["width"] % 16 == 0 and size["height"] % 16 == 0
        assert size["width"] * size["height"] <= 480 * 832


def test_the_approved_version_keeps_its_two_sizes() -> None:
    assert _target(WAN_A14B_VERSION, 768, 1024) == (480, 832)
    assert _target(WAN_A14B_VERSION, 1024, 768) == (832, 480)


def test_full_picture_version_is_experimental_with_the_baseline_graph_and_launch() -> None:
    base, full = _spec(WAN_A14B_VERSION), _spec(WAN_A14B_FULL_PICTURE_ID)

    assert full.is_experimental and not full.backend_defaults["make_video_default"]
    assert full.backend_defaults["prompt_template"] == base.backend_defaults["prompt_template"]
    assert full.dependency_specs == base.dependency_specs
    assert a14b_launch_attention(full) == "baseline"
    record = {"workflow_id": FULL, "governance_state": full.governance_state, "experimental": True}
    assert not is_offered(record, show_experimental=False)
    assert is_offered(record, show_experimental=True)


def test_a_handoff_frame_of_any_declared_size_passes_through(tmp_path: Path) -> None:
    frame = _png(tmp_path / "frame.png", (544, 720))

    record = passthrough_declared_workflow_source(
        source_path=frame, policy=_policy(WAN_A14B_FULL_PICTURE_ID)
    )

    assert record.target_dimensions == {"width": 544, "height": 720}


def test_a_large_crop_warns_with_why_and_fix_and_a_small_one_does_not() -> None:
    cropped = source_crop_warning(_spec(WAN_A14B_VERSION), 768, 1024)

    assert cropped is not None and cropped.code == CODE_VIDEO_SOURCE_CROPPED
    assert "23%" in cropped.title and "480x832" in cropped.why and cropped.fix
    assert source_crop_warning(_spec(WAN_A14B_VERSION), 720, 1280) is None
    assert source_crop_warning(_spec(WAN_A14B_FULL_PICTURE_ID), 768, 1024) is None
    assert source_crop_warning(_spec(WAN_A14B_FULL_PICTURE_ID), 832, 1216) is None
    # A very tall source fits no size within 5 %.
    assert source_crop_warning(_spec(WAN_A14B_FULL_PICTURE_ID), 500, 1500) is not None


def test_warning_from_a_path_honours_exif_rotation_and_survives_a_bad_file(tmp_path: Path) -> None:
    policy = _policy(WAN_A14B_VERSION)
    rotated = tmp_path / "rotated.jpg"
    exif = Image.Exif()
    exif[0x0112] = 6  # stored landscape, shown portrait 720x1280
    Image.new("RGB", (1280, 720)).save(rotated, exif=exif)
    broken = tmp_path / "broken.png"
    broken.write_bytes(b"not an image")

    subject = f"{WAN_A14B_ID}@{WAN_A14B_VERSION}"  # the approved two sizes
    tall = _png(tmp_path / "tall.png", (768, 1024))

    assert source_crop_warning_for_path(policy, subject, str(tall)) is not None
    assert source_crop_warning_for_path(policy, subject, str(rotated)) is None
    assert source_crop_warning_for_path(policy, subject, str(broken)) is None
    assert source_crop_warning_for_path(policy, subject, "") is None
    assert source_crop_warning_for_path(None, subject, str(tall)) is None
    assert source_crop_warning_for_path(policy, "another_workflow@1.0.0", str(tall)) is None


def test_job_records_size_crop_fraction_and_the_accepted_warning(tmp_path: Path) -> None:
    builder = _builder(tmp_path)
    source = _png(tmp_path / "portrait.png", (768, 1024))
    form = _form(WAN_A14B_VERSION)

    built = builder.build_job(form, builder.freeze_inputs(source, form))

    assert built.source_preparation["target_dimensions"] == {"width": 480, "height": 832}
    recorded = built.njr.extra_metadata["video_workflow"]["source_crop_fraction"]
    assert recorded == pytest.approx(0.2308, abs=1e-4)
    codes = [item["code"] for item in accepted_warning_records(built.njr.extra_metadata)]
    assert codes == [CODE_VIDEO_SOURCE_CROPPED]


def test_full_picture_job_of_a_3_4_source_records_no_crop_warning(tmp_path: Path) -> None:
    builder = _builder(tmp_path)
    source = _png(tmp_path / "portrait.png", (768, 1024))
    form = _form(WAN_A14B_FULL_PICTURE_ID)

    built = builder.build_job(form, builder.freeze_inputs(source, form))

    assert built.source_preparation["target_dimensions"] == {"width": 544, "height": 720}
    assert built.njr.extra_metadata["video_workflow"]["source_crop_fraction"] < 0.01
    codes = [item["code"] for item in accepted_warning_records(built.njr.extra_metadata)]
    assert CODE_VIDEO_SOURCE_CROPPED not in codes


def test_batch_preview_names_the_cropped_sources_once(tmp_path: Path) -> None:
    service = VideoWorkflowBatchService(_builder(tmp_path))
    sources = [
        BatchSource(str(_png(tmp_path / "a.png", (768, 1024)))),
        BatchSource(str(_png(tmp_path / "b.png", (720, 1280)))),
    ]

    assessment = service.assess(_form(WAN_A14B_VERSION), sources)

    crop = [text for text in assessment.warnings if "cut away" in text]
    assert len(crop) == 1 and "Source 1" in crop[0] and assessment.eligible


def test_the_example_suite_compares_the_two_versions_and_loads(tmp_path: Path) -> None:
    example = Path(__file__).resolve().parents[2] / "docs" / "runbooks" / "examples"
    data = json.loads((example / "video_eval_a14b_full_picture.suite.json").read_text("utf-8"))
    for case in data["cases"]:
        image = tmp_path / case["image"]
        image.parent.mkdir(parents=True, exist_ok=True)
        Image.new("RGB", (96, 128), (90, 60, 30)).save(image)
    path = tmp_path / "suite.json"
    path.write_text(json.dumps(data), encoding="utf-8")

    suite = load_eval_suite(path)

    assert len(suite.arms) == 2 and len(suite.cases) == 5
