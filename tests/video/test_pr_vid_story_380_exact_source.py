"""PR-VID-STORY-380: a handoff frame reaches the video job untouched.

A storyboard take starts from the exact PNG of an earlier clip.  The A14B workflow still reads its
output size from ``stage_config.source_preparation.target_dimensions``, so the take needs a
preparation record, but the record must point at the original file: no resize, no re-save.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from PIL import Image

from src.video.video_workflow_njr_builder import VideoWorkflowNjrBuilder
from src.video.workflow_catalog_wan_a14b import WAN_A14B_ID, WAN_A14B_VERSION
from src.video.workflow_registry import build_default_workflow_registry
from src.video.workflow_source_preparation import (
    PASSTHROUGH_POLICY,
    passthrough_declared_workflow_source,
)

A14B_POLICY: dict[str, Any] = dict(
    build_default_workflow_registry()
    .get(WAN_A14B_ID, WAN_A14B_VERSION)
    .backend_defaults["source_preparation"]
)


def _png(path: Path, size: tuple[int, int]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", size, (12, 120, 200)).save(path, format="PNG")
    return path


def _a14b_form() -> dict[str, Any]:
    return {
        "workflow_id": WAN_A14B_ID,
        "workflow_version": WAN_A14B_VERSION,
        "prompt": "the person waves",
        "seed": "",
    }


@pytest.fixture
def a14b_builder(tmp_path: Path) -> VideoWorkflowNjrBuilder:
    return VideoWorkflowNjrBuilder(
        workflow_registry=build_default_workflow_registry(),
        output_dir_provider=lambda: str(tmp_path / "out"),
    )


def test_passthrough_writes_nothing_and_keeps_the_file(tmp_path: Path) -> None:
    png = _png(tmp_path / "f.png", (832, 480))
    before = png.read_bytes()

    record = passthrough_declared_workflow_source(source_path=png, policy=A14B_POLICY)

    assert record.prepared_image_path == str(png.resolve())
    assert record.original_source_path == str(png.resolve())
    assert record.target_dimensions == {"width": 832, "height": 480}
    assert record.source_dimensions == record.prepared_dimensions == record.target_dimensions
    assert record.policy == PASSTHROUGH_POLICY
    assert not (tmp_path / "prepared_video_sources").exists()
    assert png.read_bytes() == before
    assert sorted(p.name for p in tmp_path.iterdir()) == ["f.png"]


def test_passthrough_accepts_the_portrait_target_too(tmp_path: Path) -> None:
    png = _png(tmp_path / "p.png", (480, 832))

    record = passthrough_declared_workflow_source(source_path=png, policy=A14B_POLICY)

    assert record.target_dimensions == {"width": 480, "height": 832}
    assert record.orientation == "portrait"


def test_passthrough_refuses_a_wrong_size(tmp_path: Path) -> None:
    png = _png(tmp_path / "f.png", (830, 480))

    with pytest.raises(ValueError, match="not the workflow's target size 832x480"):
        passthrough_declared_workflow_source(source_path=png, policy=A14B_POLICY)
    assert sorted(p.name for p in tmp_path.iterdir()) == ["f.png"]


def test_passthrough_message_names_both_sizes(tmp_path: Path) -> None:
    png = _png(tmp_path / "f.png", (830, 480))

    with pytest.raises(ValueError) as excinfo:
        passthrough_declared_workflow_source(source_path=png, policy=A14B_POLICY)

    assert str(excinfo.value) == (
        "The handoff frame is 830x480, not the workflow's target size 832x480; "
        "it is used exactly as generated, never resized."
    )


def test_passthrough_refuses_a_missing_file(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="does not exist"):
        passthrough_declared_workflow_source(source_path=tmp_path / "nope.png", policy=A14B_POLICY)


def test_freeze_inputs_exact_source_keeps_the_hash(
    tmp_path: Path, a14b_builder: VideoWorkflowNjrBuilder
) -> None:
    png = _png(tmp_path / "f.png", (832, 480))

    frozen = a14b_builder.freeze_inputs(
        png, _a14b_form(), prompt_per_segment=True, exact_source=True
    )

    assert frozen.prepared_source_path == str(png.resolve())
    assert frozen.prepared_source_sha256 == frozen.source_sha256
    assert frozen.source_preparation is not None
    assert frozen.source_preparation["target_dimensions"] == {"width": 832, "height": 480}
    assert frozen.source_preparation["policy"] == PASSTHROUGH_POLICY
    assert not (tmp_path / "out").exists()


def test_freeze_inputs_without_exact_source_still_prepares(
    tmp_path: Path, a14b_builder: VideoWorkflowNjrBuilder
) -> None:
    png = _png(tmp_path / "f.png", (1000, 600))

    frozen = a14b_builder.freeze_inputs(png, _a14b_form(), prompt_per_segment=True)

    assert frozen.source_preparation is not None
    assert frozen.source_preparation["policy"] == "cover_resize_center_crop"
    assert frozen.prepared_source_path != str(png.resolve())
    assert (tmp_path / "out" / "prepared_video_sources").is_dir()


def test_freeze_inputs_exact_source_refuses_a_wrong_size(
    tmp_path: Path, a14b_builder: VideoWorkflowNjrBuilder
) -> None:
    png = _png(tmp_path / "f.png", (1000, 600))

    with pytest.raises(ValueError, match="not the workflow's target size 832x480"):
        a14b_builder.freeze_inputs(png, _a14b_form(), prompt_per_segment=True, exact_source=True)
    assert not (tmp_path / "out").exists()


def test_the_pass_through_record_is_accepted_by_the_dispatch_geometry_check(
    tmp_path: Path, a14b_builder: VideoWorkflowNjrBuilder
) -> None:
    """Readers compare dimensions, never the policy string; the pass-through must satisfy them."""

    png = _png(tmp_path / "f.png", (832, 480))
    frozen = a14b_builder.freeze_inputs(
        png, _a14b_form(), prompt_per_segment=True, exact_source=True
    )
    record = frozen.source_preparation
    assert record is not None
    assert record["target_dimensions"] in (
        A14B_POLICY["portrait_target"],
        A14B_POLICY["landscape_target"],
    )
    assert record["target_dimensions"] == record["prepared_dimensions"]
