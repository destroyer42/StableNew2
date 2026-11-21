"""PR-VID-STORY-380: admission of a storyboard take (policy v2) and the shared sequence NJR builder.

A take with a lead-in starts from the exact handoff PNG of its parent cut; admission freezes that plan and refuses
anything inconsistent before an NJR exists. Real workflow catalog (Wan2.2 I2V-A14B), real PNG frames and a real cut
manifest; no runtime, GPU or network.
"""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest
from PIL import Image

from src.video.sequence_admission import freeze_sequence_plan, sha256_file
from src.video.sequence_job_build import build_sequence_njr
from src.video.sequence_plan import (
    ANCHOR_CARRY,
    ANCHOR_SOURCE,
    ROOT_PARENT,
    SEQUENCE_POLICY_VERSION,
    SEQUENCE_POLICY_VERSION_V2,
    STAGE_SVD_NATIVE,
    STAGE_VIDEO_WORKFLOW,
    SequencePlan,
    SequencePlanError,
    StoryboardLeadIn,
    StoryboardPlanLink,
)
from src.video.storyboard_cut import (
    BASIS_DECODED,
    CutFrame,
    CutManifest,
    CutManifestError,
    CutRange,
    write_cut_manifest,
)
from src.video.video_workflow_njr_builder import VideoWorkflowNjrBuilder
from src.video.workflow_catalog_wan_a14b import WAN_A14B_ID, WAN_A14B_VERSION
from src.video.workflow_registry import build_default_workflow_registry

SIZE = (832, 480)
FPS = 16
ROOT_FRAMES = 81


@pytest.fixture
def registry() -> Any:
    return build_default_workflow_registry()


@pytest.fixture
def a14b_builder(tmp_path: Path, registry: Any) -> VideoWorkflowNjrBuilder:
    return VideoWorkflowNjrBuilder(
        workflow_registry=registry,
        output_dir_provider=lambda: str(tmp_path / "out"),
    )


def _a14b_form() -> dict[str, Any]:
    return {
        "workflow_id": WAN_A14B_ID,
        "workflow_version": WAN_A14B_VERSION,
        "prompt": "the person waves",
        "seed": "",
    }


def _intent(rows: int, **top: Any) -> dict[str, Any]:
    return {"segments": [{"frame_count": 81} for _ in range(rows)], **top}


def _png(path: Path, color: tuple[int, int, int], size: tuple[int, int] = SIZE) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", size, color).save(path, format="PNG")
    return path


def _still(tmp_path: Path) -> Path:
    return _png(tmp_path / "still.png", (40, 90, 160))


def _overwrite_png(path: Path) -> None:
    """Same size, different pixels: only the hash tells it apart."""

    _png(path, (255, 0, 255))


def _lead_in_from_root(tmp_path: Path, *, k: int) -> tuple[StoryboardLeadIn, Path]:
    """An 81-frame root cut at 832x480 and 16 fps; the lead-in is its first ``k`` frames (handoff = frame ``k``)."""

    folder = tmp_path / "storyboards" / "sb-1" / "root"
    frames = []
    for index in range(ROOT_FRAMES):
        path = _png(folder / f"frame_{index:04d}.png", (index, 120, 200)).resolve()
        frames.append(CutFrame(path=str(path), sha256=sha256_file(path)))
    manifest = CutManifest(
        fps=FPS,
        width=SIZE[0],
        height=SIZE[1],
        frames=tuple(frames),
        ranges=(CutRange(ROOT_PARENT, 0, ROOT_FRAMES - 1, BASIS_DECODED, 0),),
        lead_in_frames=0,
        job_id=None,
    )
    written = write_cut_manifest(folder / "cut.json", manifest)
    handoff = frames[k - 1]
    lead_in = StoryboardLeadIn(
        manifest_path=written.path,
        manifest_sha256=written.sha256,
        frame_count=k,
        handoff_path=handoff.path,
        handoff_sha256=handoff.sha256,
    )
    return lead_in, Path(handoff.path)


def _link(lead_in: StoryboardLeadIn | None, *, take_ids: tuple[str, ...]) -> StoryboardPlanLink:
    return StoryboardPlanLink(
        storyboard_id="sb-1",
        parent_id=ROOT_PARENT,
        take_ids=take_ids,
        handoff_index=None if lead_in is None else lead_in.frame_count - 1,
        lead_in=lead_in,
    )


def _plan_of(njr: Any) -> SequencePlan:
    return SequencePlan.from_dict(dict(njr.stage_chain[0].extra)["sequence_metadata"])


def _freeze(intent: dict[str, Any], registry: Any, handoff: Path, **kw: Any) -> SequencePlan:
    options: dict[str, Any] = {
        "stage": STAGE_VIDEO_WORKFLOW,
        "fps": FPS,
        "base_prompt": "the person waves",
        "base_workflow": (WAN_A14B_ID, WAN_A14B_VERSION),
        "registry": registry,
        "target_size": SIZE,
        "source": {"path": str(handoff), "sha256": sha256_file(handoff)},
    }
    options.update(kw)
    return freeze_sequence_plan(intent, **options)


# ----------------------------------------------------------------------------- build_sequence_njr


def test_storyboard_link_freezes_a_v2_plan_starting_from_the_handoff(
    tmp_path: Path, a14b_builder: VideoWorkflowNjrBuilder, registry: Any
) -> None:
    # 81 frames at 832x480, handoff = frame 78
    lead_in, handoff = _lead_in_from_root(tmp_path, k=78)
    built = build_sequence_njr(
        njr_builder=a14b_builder,
        registry=registry,
        source_image_path=str(handoff),
        form_data=_a14b_form(),
        sequence_intent=_intent(rows=1),
        storyboard=_link(lead_in, take_ids=("t1",)),
        exact_source=True,
    )
    plan = _plan_of(built.njr)
    assert plan.policy_version == SEQUENCE_POLICY_VERSION_V2
    assert plan.source == {"path": str(handoff.resolve()), "sha256": sha256_file(handoff)}
    assert plan.segments[0].overlap_frames == 1 and plan.assembly.enabled
    assert plan.storyboard == _link(lead_in, take_ids=("t1",))
    assert not plan.color_match.enabled
    assert (plan.target_width, plan.target_height) == SIZE
    # The NJR runs the handoff PNG itself: no prepared copy was made.
    assert not (tmp_path / "out" / "prepared_video_sources").exists()
    assert built.source_preparation["prepared_image_path"] == str(handoff.resolve())


def test_a_changed_handoff_is_refused_before_an_njr_exists(
    tmp_path: Path, a14b_builder: VideoWorkflowNjrBuilder, registry: Any
) -> None:
    lead_in, handoff = _lead_in_from_root(tmp_path, k=78)
    _overwrite_png(handoff)
    with pytest.raises(SequencePlanError, match="handoff frame changed"):
        build_sequence_njr(
            njr_builder=a14b_builder,
            registry=registry,
            source_image_path=str(handoff),
            form_data=_a14b_form(),
            sequence_intent=_intent(rows=1),
            storyboard=_link(lead_in, take_ids=("t1",)),
            exact_source=True,
        )


def test_storyboard_takes_refuse_smoothing(
    tmp_path: Path, a14b_builder: VideoWorkflowNjrBuilder, registry: Any
) -> None:
    form = {**_a14b_form(), "interpolation": {"enabled": True, "multiplier": 2}}
    with pytest.raises(SequencePlanError, match="RIFE smoothing is not applied inside a sequence"):
        build_sequence_njr(
            njr_builder=a14b_builder,
            registry=registry,
            source_image_path=str(_still(tmp_path)),
            form_data=form,
            sequence_intent=_intent(rows=1),
            storyboard=_link(None, take_ids=("t1",)),
        )


def test_sequential_chain_uses_carry_last_frame(
    tmp_path: Path, a14b_builder: VideoWorkflowNjrBuilder, registry: Any
) -> None:
    lead_in, handoff = _lead_in_from_root(tmp_path, k=81)
    built = build_sequence_njr(
        njr_builder=a14b_builder,
        registry=registry,
        source_image_path=str(handoff),
        form_data=_a14b_form(),
        sequence_intent=_intent(rows=3),
        storyboard=_link(lead_in, take_ids=("t1", "t2", "t3")),
        exact_source=True,
    )
    plan = _plan_of(built.njr)
    assert [s.anchor_policy for s in plan.segments] == [
        "source",
        "carry_last_frame",
        "carry_last_frame",
    ]
    assert [s.overlap_frames for s in plan.segments] == [1, 1, 1]
    assert plan.storyboard is not None and plan.storyboard.take_ids == ("t1", "t2", "t3")


def test_exact_source_refuses_a_source_that_is_not_the_lead_ins_handoff(
    tmp_path: Path, a14b_builder: VideoWorkflowNjrBuilder, registry: Any
) -> None:
    """Refused on the frozen source hash itself, before the cut manifest is even read."""

    lead_in, handoff = _lead_in_from_root(tmp_path, k=78)
    Path(lead_in.manifest_path).unlink()  # verify_lead_in would say "cut manifest is missing"
    with pytest.raises(CutManifestError, match="handoff frame changed"):
        build_sequence_njr(
            njr_builder=a14b_builder,
            registry=registry,
            source_image_path=str(_still(tmp_path)),
            form_data=_a14b_form(),
            sequence_intent=_intent(rows=1),
            storyboard=_link(lead_in, take_ids=("t1",)),
            exact_source=True,
        )
    assert handoff.is_file()


def test_a_lead_in_without_exact_source_is_refused_because_a_prepared_copy_is_not_the_handoff(
    tmp_path: Path, a14b_builder: VideoWorkflowNjrBuilder, registry: Any
) -> None:
    lead_in, handoff = _lead_in_from_root(tmp_path, k=78)
    with pytest.raises(SequencePlanError, match="segment 0 starts from the handoff frame"):
        build_sequence_njr(
            njr_builder=a14b_builder,
            registry=registry,
            source_image_path=str(handoff),
            form_data=_a14b_form(),
            sequence_intent=_intent(rows=1),
            storyboard=_link(lead_in, take_ids=("t1",)),
        )


def test_a_take_from_a_still_root_is_v2_with_its_source_prepared_as_today(
    tmp_path: Path, a14b_builder: VideoWorkflowNjrBuilder, registry: Any
) -> None:
    still = _png(tmp_path / "still.png", (40, 90, 160), size=(1000, 600))
    built = build_sequence_njr(
        njr_builder=a14b_builder,
        registry=registry,
        source_image_path=str(still),
        form_data=_a14b_form(),
        sequence_intent=_intent(rows=2),
        storyboard=_link(None, take_ids=("t1", "t2")),
    )
    plan = _plan_of(built.njr)
    assert plan.policy_version == SEQUENCE_POLICY_VERSION_V2
    assert plan.storyboard is not None and plan.storyboard.handoff_index is None
    assert [s.overlap_frames for s in plan.segments] == [0, 1]
    assert plan.source is not None and plan.source["path"] != str(still.resolve())
    assert (tmp_path / "out" / "prepared_video_sources").is_dir()


def test_without_a_storyboard_link_the_plan_stays_v1(
    tmp_path: Path, a14b_builder: VideoWorkflowNjrBuilder, registry: Any
) -> None:
    built = build_sequence_njr(
        njr_builder=a14b_builder,
        registry=registry,
        source_image_path=str(_still(tmp_path)),
        form_data=_a14b_form(),
        sequence_intent=_intent(rows=2),
    )
    raw = dict(built.njr.stage_chain[0].extra)["sequence_metadata"]
    assert raw["policy_version"] == SEQUENCE_POLICY_VERSION
    assert "storyboard" not in raw


def test_a_take_id_per_segment_is_enforced_through_the_plan(
    tmp_path: Path, a14b_builder: VideoWorkflowNjrBuilder, registry: Any
) -> None:
    lead_in, handoff = _lead_in_from_root(tmp_path, k=81)
    with pytest.raises(SequencePlanError, match="one take id per segment"):
        build_sequence_njr(
            njr_builder=a14b_builder,
            registry=registry,
            source_image_path=str(handoff),
            form_data=_a14b_form(),
            sequence_intent=_intent(rows=2),
            storyboard=_link(lead_in, take_ids=("t1",)),
            exact_source=True,
        )


def test_a_moved_lead_in_frame_propagates_as_a_cut_manifest_error(
    tmp_path: Path, a14b_builder: VideoWorkflowNjrBuilder, registry: Any
) -> None:
    lead_in, handoff = _lead_in_from_root(tmp_path, k=78)
    (handoff.parent / "frame_0010.png").unlink()
    with pytest.raises(CutManifestError, match="lead-in frame is missing") as caught:
        build_sequence_njr(
            njr_builder=a14b_builder,
            registry=registry,
            source_image_path=str(handoff),
            form_data=_a14b_form(),
            sequence_intent=_intent(rows=1),
            storyboard=_link(lead_in, take_ids=("t1",)),
            exact_source=True,
        )
    assert type(caught.value) is CutManifestError  # not re-wrapped into a plain SequencePlanError


# ----------------------------------------------------------------------------- freeze_sequence_plan


@pytest.mark.parametrize(
    "top",
    [
        {"color_match": True},
        {"color_match": {"enabled": True}},
        {"assembly": {"enabled": False}},
    ],
)
def test_a_take_is_always_assembled_without_colour_matching(
    tmp_path: Path, registry: Any, top: dict[str, Any]
) -> None:
    lead_in, handoff = _lead_in_from_root(tmp_path, k=78)
    with pytest.raises(
        SequencePlanError, match="a storyboard take is always assembled without colour matching"
    ):
        _freeze(_intent(1, **top), registry, handoff, storyboard=_link(lead_in, take_ids=("t1",)))


def test_explicit_assembly_settings_are_kept_and_forced_on(tmp_path: Path, registry: Any) -> None:
    lead_in, handoff = _lead_in_from_root(tmp_path, k=78)
    plan = _freeze(
        _intent(1, assembly={"clip_name": "take one"}, color_match=False),
        registry,
        handoff,
        storyboard=_link(lead_in, take_ids=("t1",)),
    )
    assert plan.assembly.enabled and plan.assembly.clip_name == "take_one"
    assert not plan.color_match.enabled


@pytest.mark.parametrize("overlap", [0, 2])
def test_an_explicit_segment_zero_overlap_other_than_one_is_refused(
    tmp_path: Path, registry: Any, overlap: int
) -> None:
    lead_in, handoff = _lead_in_from_root(tmp_path, k=78)
    intent = {"segments": [{"frame_count": 81, "overlap_frames": overlap}]}
    with pytest.raises(SequencePlanError, match="overlaps the handoff frame by 1 frame"):
        _freeze(intent, registry, handoff, storyboard=_link(lead_in, take_ids=("t1",)))


def test_an_explicit_segment_zero_overlap_of_one_is_accepted(tmp_path: Path, registry: Any) -> None:
    lead_in, handoff = _lead_in_from_root(tmp_path, k=78)
    intent = {"segments": [{"frame_count": 81, "overlap_frames": 1}]}
    plan = _freeze(intent, registry, handoff, storyboard=_link(lead_in, take_ids=("t1",)))
    assert plan.segments[0].overlap_frames == 1


def test_a_lead_in_needs_the_frozen_target_size(tmp_path: Path, registry: Any) -> None:
    lead_in, handoff = _lead_in_from_root(tmp_path, k=78)
    Path(lead_in.manifest_path).unlink()  # refused before the lead-in is even read
    with pytest.raises(SequencePlanError) as caught:
        _freeze(
            _intent(1),
            registry,
            handoff,
            target_size=None,
            storyboard=_link(lead_in, take_ids=("t1",)),
        )
    assert str(caught.value) == (
        "a storyboard take with a lead-in needs the workflow's frozen target size"
    )


@pytest.mark.parametrize(
    ("change", "message"),
    [
        ("size", "not the target size 480x832"),
        ("fps", "plays at 16 fps, not 24 fps"),
        ("manifest", "cut manifest changed"),
    ],
)
def test_lead_in_checks_run_before_the_plan_is_built(
    tmp_path: Path, registry: Any, change: str, message: str
) -> None:
    lead_in, handoff = _lead_in_from_root(tmp_path, k=78)
    options: dict[str, Any] = {"storyboard": _link(lead_in, take_ids=("t1",))}
    if change == "size":
        options["target_size"] = (480, 832)
    elif change == "fps":
        options["fps"] = 24
    else:
        Path(lead_in.manifest_path).write_text("{}", encoding="utf-8")
    with pytest.raises(CutManifestError, match=message):
        _freeze(_intent(1), registry, handoff, **options)


def test_the_source_must_be_the_handoff_frame(tmp_path: Path, registry: Any) -> None:
    lead_in, _handoff = _lead_in_from_root(tmp_path, k=78)
    other = _still(tmp_path)
    with pytest.raises(SequencePlanError, match="segment 0 starts from the handoff frame"):
        _freeze(_intent(1), registry, other, storyboard=_link(lead_in, take_ids=("t1",)))


def test_a_handoff_index_that_is_not_the_last_lead_in_frame_is_refused(
    tmp_path: Path, registry: Any
) -> None:
    lead_in, handoff = _lead_in_from_root(tmp_path, k=78)
    link = replace(_link(lead_in, take_ids=("t1",)), handoff_index=10)
    with pytest.raises(SequencePlanError, match="handoff_index must be 77"):
        _freeze(_intent(1), registry, handoff, storyboard=link)


def test_freeze_without_a_link_is_unchanged_v1(tmp_path: Path, registry: Any) -> None:
    plan = _freeze(_intent(2), registry, _still(tmp_path))
    assert plan.policy_version == SEQUENCE_POLICY_VERSION and plan.storyboard is None
    assert "storyboard" not in plan.to_dict()
    assert [s.anchor_policy for s in plan.segments] == [ANCHOR_SOURCE, ANCHOR_CARRY]
    assert [s.overlap_frames for s in plan.segments] == [0, 1]


def test_a_storyboard_link_on_native_svd_is_refused_before_anything_else() -> None:
    # The segment would otherwise be refused for its prompt; the storyboard refusal comes first.
    intent = {"segments": [{"frame_count": 17, "prompt": "waves"}]}
    with pytest.raises(SequencePlanError) as caught:
        freeze_sequence_plan(
            intent,
            stage=STAGE_SVD_NATIVE,
            fps=6,
            svd_max_frames=25,
            model_id="svd_xt",
            storyboard=_link(None, take_ids=("t1",)),
        )
    assert str(caught.value) == (
        "storyboard takes run on Comfy video workflows only; native SVD has no prompt to vary"
    )
