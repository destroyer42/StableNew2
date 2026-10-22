"""PR-VID-SEQ-330-CORE: the typed sequence plan and its admission. Everything illegal is refused before an NJR exists.

Real workflow catalog (the approved Wan TI2V-5B versions); no runtime, GPU or network.
"""

from __future__ import annotations

import hashlib
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from PIL import Image

from src.video.sequence_admission import (
    freeze_sequence_plan,
    verify_provided_anchors,
    workflow_segment_errors,
)
from src.video.sequence_plan import (
    ANCHOR_CARRY,
    ANCHOR_PROVIDED,
    ANCHOR_SOURCE,
    COLOR_ALGORITHM,
    COLOR_REFERENCE,
    MAX_SEQUENCE_SEGMENTS,
    MAX_SEQUENCE_TOTAL_FRAMES,
    SEQUENCE_PLAN_SCHEMA,
    SEQUENCE_POLICY_VERSION,
    STAGE_SVD_NATIVE,
    STAGE_VIDEO_WORKFLOW,
    SegmentSpec,
    SequenceColorMatch,
    SequencePlan,
    SequencePlanError,
)
from src.video.svd_config import SVDConfig
from src.video.svd_sequence_admission import freeze_svd_sequence_plan, svd_sequence_fps
from src.video.workflow_registry import build_default_workflow_registry

WORKFLOW = "wan22_ti2v_5b_i2v_v1"
REGISTRY = build_default_workflow_registry()


def _png(path: Path, size: tuple[int, int] = (480, 832)) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", size, (10, 20, 30)).save(path)
    return path


def _intent(*segments: dict[str, Any], **top: Any) -> dict[str, Any]:
    return {"segments": list(segments or ({"frame_count": 49}, {"frame_count": 49})), **top}


def _freeze(intent: dict[str, Any], **kw: Any) -> SequencePlan:
    options: dict[str, Any] = {
        "stage": STAGE_VIDEO_WORKFLOW,
        "fps": 24,
        "base_prompt": "the person waves",
        "base_workflow": (WORKFLOW, "1.3.0"),
        "registry": REGISTRY,
        "target_size": (480, 832),
    }
    options.update(kw)
    return freeze_sequence_plan(intent, **options)


# ----------------------------------------------------------------------------- a legal plan


def test_a_legal_plan_is_concrete_and_round_trips() -> None:
    plan = _freeze(
        _intent(
            {"frame_count": 49, "seed": 5},
            {"frame_count": 33, "workflow_version": "1.2.0", "prompt": "turns"},
            {"frame_count": 81, "seed": "random", "overlap_frames": 1},
        ),
        segment_zero_seed=7,
    )

    assert [s.index for s in plan.segments] == [0, 1, 2]
    assert plan.segments[0].seed == 5  # an explicit seed wins over the single-clip default
    assert all(
        0 <= s.seed <= 2**31 - 1 for s in plan.segments
    )  # blank and "random" were frozen to concrete seeds
    assert [s.frame_count for s in plan.segments] == [49, 33, 81]
    assert [s.workflow_version for s in plan.segments] == ["1.3.0", "1.2.0", "1.3.0"]
    assert [s.prompt for s in plan.segments] == ["the person waves", "turns", "the person waves"]
    assert [s.anchor_policy for s in plan.segments] == [ANCHOR_SOURCE, ANCHOR_CARRY, ANCHOR_CARRY]
    assert plan.total_frames == 163 and plan.validate() == []
    assert SequencePlan.from_dict(plan.to_dict()) == plan
    assert plan.plan_sha256() == SequencePlan.from_dict(plan.to_dict()).plan_sha256()
    turned_on = replace(plan, color_match=SequenceColorMatch(enabled=True))
    assert plan.plan_sha256() != turned_on.plan_sha256()
    changed = replace(plan, segments=(replace(plan.segments[0], seed=6), *plan.segments[1:]))
    assert plan.plan_sha256() != changed.plan_sha256()


def test_the_plan_carries_its_versioned_identity_and_digest() -> None:
    plan = _freeze(
        _intent({"frame_count": 49, "seed": 5}, {"frame_count": 33}),
        continuity={"pack_id": "p1"},
        plan_origin={"shot_id": "s1"},
    )
    data = plan.to_dict()

    assert (
        data["schema"] == SEQUENCE_PLAN_SCHEMA and data["policy_version"] == SEQUENCE_POLICY_VERSION
    )
    assert data["backend"] == "comfy" and data["experimental_opt_in"] is False
    assert data["plan_digest"] == plan.plan_sha256() and len(data["plan_digest"]) == 64
    assert data["continuity"] == {"pack_id": "p1"} and data["plan_origin"] == {"shot_id": "s1"}
    assert data["color_match"] == {
        "enabled": False,
        "algorithm": COLOR_ALGORITHM,
        "reference": COLOR_REFERENCE,
    }  # colour matching is off until quality has been evaluated
    # Any edit after freezing - including the digest itself - makes the plan unloadable.
    tampered = {**data, "segments": [{**data["segments"][0], "seed": 6}, *data["segments"][1:]]}
    with pytest.raises(SequencePlanError, match="altered after it was frozen"):
        SequencePlan.from_dict(tampered)
    with pytest.raises(SequencePlanError, match="altered after it was frozen"):
        SequencePlan.from_dict({**data, "plan_digest": "0" * 64})
    assert any(
        "unsupported sequence execution policy" in text
        for text in replace(plan, policy_version="other").validate()
    )


def test_overlap_defaults_are_one_for_a_carried_anchor_and_zero_for_a_provided_one(
    tmp_path: Path,
) -> None:
    anchor = _png(tmp_path / "anchor.png")
    plan = _freeze(
        _intent(
            {"frame_count": 49},
            {"frame_count": 49},
            {"frame_count": 49, "anchor": {"policy": "provided", "path": str(anchor)}},
            {"frame_count": 49, "overlap_frames": 0},
            {"frame_count": 49, "overlap_frames": 3},
        )
    )

    assert [s.overlap_frames for s in plan.segments] == [0, 1, 0, 0, 3]


def test_the_first_segments_frozen_seed_is_used_when_the_intent_leaves_it_blank() -> None:
    plan = _freeze(_intent({"frame_count": 49}, {"frame_count": 49}), segment_zero_seed=1234)

    assert plan.segments[0].seed == 1234


def test_the_defaults_are_the_approved_limits() -> None:
    assert (MAX_SEQUENCE_SEGMENTS, MAX_SEQUENCE_TOTAL_FRAMES) == (12, 972)
    twelve = _freeze(_intent(*({"frame_count": 81},) * 12))
    assert twelve.total_frames == MAX_SEQUENCE_TOTAL_FRAMES and twelve.validate() == []


# ----------------------------------------------------------------------------- refusals


@pytest.mark.parametrize("count", [18, 100, 0, 16])
def test_an_illegal_frame_count_is_refused(count: int) -> None:
    with pytest.raises(SequencePlanError, match="cannot generate|frame_count"):
        _freeze(_intent({"frame_count": 49}, {"frame_count": count}))


def test_too_many_segments_and_too_large_a_budget_are_refused() -> None:
    with pytest.raises(SequencePlanError, match="13 segments is more than the 12"):
        _freeze(_intent(*({"frame_count": 17},) * 13))
    over = SequencePlan(
        sequence_id="x",
        stage=STAGE_VIDEO_WORKFLOW,
        fps=24,
        segments=tuple(
            SegmentSpec(
                index=i,
                seed=1,
                frame_count=82,
                anchor_policy=ANCHOR_SOURCE if i == 0 else ANCHOR_CARRY,
                workflow_id=WORKFLOW,
                workflow_version="1.3.0",
            )
            for i in range(12)
        ),
    )
    assert any("972-frame generation budget" in text for text in over.validate())
    assert (
        _freeze(_intent({"frame_count": 49})).validate() == []
    )  # one segment is a legal (degenerate) sequence
    with pytest.raises(SequencePlanError, match="a list of segments"):
        _freeze({"segments": []})


@pytest.mark.parametrize(
    ("intent", "needle"),
    [
        (
            {"segments": [{"frame_count": 49}, {"frame_count": 49}], "extra": 1},
            "unknown sequence field",
        ),
        (_intent({"frame_count": 49}, {"frame_count": 49, "cfg": 7}), "unknown segment 1 field"),
        (
            _intent(
                {"frame_count": 49},
                {"frame_count": 49, "anchor": {"policy": "carry_last_frame", "x": 1}},
            ),
            "unknown segment 1 anchor field",
        ),
        (
            _intent(
                {"frame_count": 49}, {"frame_count": 49}, assembly={"codec": "libx264", "gpu": True}
            ),
            "unknown assembly",
        ),
    ],
)
def test_unknown_override_keys_are_refused_not_ignored(intent: dict[str, Any], needle: str) -> None:
    with pytest.raises(SequencePlanError, match=needle):
        _freeze(intent)


def test_a_plan_with_a_stray_field_cannot_be_loaded_back() -> None:
    plan = _freeze(_intent())
    data = plan.to_dict()
    data["segments"][1]["pose_video_path"] = "x.mp4"
    with pytest.raises(SequencePlanError, match="pose_video_path"):
        SequencePlan.from_dict(data)
    with pytest.raises(SequencePlanError, match="missing"):
        SequencePlan.from_dict({})


@pytest.mark.parametrize(
    ("segment", "needle"),
    [
        ({"workflow_id": "no_such_workflow", "workflow_version": "1.0.0"}, "not registered"),
        ({"workflow_version": "1.1.0"}, "experimental"),
        ({"workflow_id": "wan_animate2_drive_i2v_v1", "workflow_version": "1.2.0"}, "experimental"),
        ({"workflow_id": "wan_animate2_drive_i2v_v1"}, "name the exact version"),
    ],
)
def test_unsupported_workflows_are_refused(segment: dict[str, Any], needle: str) -> None:
    with pytest.raises(SequencePlanError, match=needle):
        _freeze(_intent({"frame_count": 49}, {"frame_count": 49, **segment}))


def test_a_workflow_the_sequence_layer_cannot_drive_is_refused_with_the_reason() -> None:
    base = REGISTRY.get(WORKFLOW, "1.3.0")

    def spec(**overrides: Any) -> Any:
        values: dict[str, Any] = {
            "workflow_id": "other",
            "workflow_version": "1.0.0",
            "backend_id": "comfy",
            "governance_state": "approved",
            "required_input_names": ("source_image", "prompt"),
            "declared_input_names": ("source_image", "prompt", "seed", "frame_count"),
            "backend_defaults": {
                "frame_count_policy": {
                    "default": 49,
                    "minimum": 17,
                    "maximum": 81,
                    "step": 4,
                    "offset": 1,
                    "fps": 24,
                },
                "source_preparation": base.backend_defaults["source_preparation"],
            },
        }
        values.update(overrides)
        return SimpleNamespace(**values)

    assert workflow_segment_errors(spec(), base, 49, 24) == []
    assert any(
        "requires pose_video" in e
        for e in workflow_segment_errors(
            spec(required_input_names=("source_image", "pose_video")), base, 49, 24
        )
    )
    assert any(
        "operator controls" in e
        for e in workflow_segment_errors(
            spec(backend_defaults={**spec().backend_defaults, "operator_controls": {"x": 1}}),
            base,
            49,
            24,
        )
    )
    assert any(
        "plays at 16 fps" in e
        for e in workflow_segment_errors(
            spec(
                backend_defaults={
                    **spec().backend_defaults,
                    "frame_count_policy": {
                        **spec().backend_defaults["frame_count_policy"],
                        "fps": 16,
                    },
                }
            ),
            base,
            49,
            24,
        )
    )
    assert any(
        "prepares its source differently" in e
        for e in workflow_segment_errors(
            spec(
                backend_defaults={
                    **spec().backend_defaults,
                    "source_preparation": {"policy": "other"},
                }
            ),
            base,
            49,
            24,
        )
    )
    assert any(
        "not a Comfy workflow" in e
        for e in workflow_segment_errors(spec(backend_id="svd"), base, 49, 24)
    )
    assert any(
        "no declared frame-count policy" in e
        for e in workflow_segment_errors(
            spec(
                backend_defaults={"source_preparation": base.backend_defaults["source_preparation"]}
            ),
            base,
            49,
            24,
        )
    )


@pytest.mark.parametrize(
    ("segment", "needle"),
    [
        ({"seed": -1}, "seed must be between"),
        ({"seed": 2**31}, "seed must be between"),
        ({"seed": "abc"}, "whole number or 'random'"),
        (
            {"overlap_frames": 1, "anchor": {"policy": "carry_last_frame"}, "frame_count": 1},
            "cannot generate|frame_count",
        ),
    ],
)
def test_seeds_and_overlaps_are_validated(segment: dict[str, Any], needle: str) -> None:
    with pytest.raises(SequencePlanError, match=needle):
        _freeze(_intent({"frame_count": 49}, {"frame_count": 49, **segment}))


def test_overlap_rules() -> None:
    carry = _freeze(_intent({"frame_count": 49}, {"frame_count": 49, "overlap_frames": 3}))
    assert carry.segments[1].overlap_frames == 3
    with pytest.raises(SequencePlanError, match="nothing before it to overlap"):
        _freeze(_intent({"frame_count": 49, "overlap_frames": 1}, {"frame_count": 49}))
    with pytest.raises(SequencePlanError, match="below its frame_count"):
        _freeze(_intent({"frame_count": 49}, {"frame_count": 49, "overlap_frames": 49}))


# ----------------------------------------------------------------------------- authored anchors


def test_a_provided_anchor_is_hashed_and_its_shape_checked(tmp_path: Path) -> None:
    anchor = _png(tmp_path / "authored.png")
    plan = _freeze(
        _intent(
            {"frame_count": 49},
            {"frame_count": 49, "anchor": {"policy": "provided", "path": str(anchor)}},
        )
    )

    segment = plan.segments[1]
    assert segment.anchor_policy == ANCHOR_PROVIDED
    assert segment.anchor_sha256 == hashlib.sha256(anchor.read_bytes()).hexdigest()
    assert Path(segment.anchor_path or "").resolve() == anchor.resolve()
    verify_provided_anchors(plan)  # unchanged: fine

    with pytest.raises(SequencePlanError, match="exactly 480x832"):
        _freeze(
            _intent(
                {"frame_count": 49},
                {
                    "frame_count": 49,
                    "anchor": {
                        "policy": "provided",
                        "path": str(_png(tmp_path / "wide.png", (832, 480))),
                    },
                },
            )
        )


def test_a_missing_or_video_anchor_is_refused_at_admission(tmp_path: Path) -> None:
    for name, needle in (("gone.png", "does not exist or was moved"),):
        with pytest.raises(SequencePlanError, match=needle):
            _freeze(
                _intent(
                    {"frame_count": 49},
                    {
                        "frame_count": 49,
                        "anchor": {"policy": "provided", "path": str(tmp_path / name)},
                    },
                )
            )
    clip = tmp_path / "previous.mp4"
    clip.write_bytes(b"mp4")  # it exists, and it is still never an anchor
    with pytest.raises(SequencePlanError, match="never used as an anchor"):
        _freeze(
            _intent(
                {"frame_count": 49},
                {"frame_count": 49, "anchor": {"policy": "provided", "path": str(clip)}},
            )
        )
    corrupt = tmp_path / "corrupt.png"
    corrupt.write_bytes(b"not a png at all")  # right suffix, not an image
    with pytest.raises(SequencePlanError, match="not a readable image"):
        _freeze(
            _intent(
                {"frame_count": 49},
                {"frame_count": 49, "anchor": {"policy": "provided", "path": str(corrupt)}},
            )
        )
    with pytest.raises(SequencePlanError, match="needs an image path"):
        _freeze(_intent({"frame_count": 49}, {"frame_count": 49, "anchor": {"policy": "provided"}}))
    with pytest.raises(SequencePlanError, match="takes no image path"):
        _freeze(
            _intent(
                {"frame_count": 49},
                {"frame_count": 49, "anchor": {"policy": "carry_last_frame", "path": "x.png"}},
            )
        )


def test_a_changed_or_removed_anchor_is_caught_before_dispatch(tmp_path: Path) -> None:
    anchor = _png(tmp_path / "authored.png")
    plan = _freeze(
        _intent(
            {"frame_count": 49},
            {"frame_count": 49, "anchor": {"policy": "provided", "path": str(anchor)}},
        )
    )

    anchor.write_bytes(anchor.read_bytes() + b"!")
    with pytest.raises(SequencePlanError, match="changed since it was queued"):
        verify_provided_anchors(plan)
    anchor.unlink()
    with pytest.raises(SequencePlanError, match="anchor is missing"):
        verify_provided_anchors(plan)


def test_the_structural_plan_rules_catch_what_admission_would_never_build() -> None:
    segments = (
        SegmentSpec(
            index=0,
            seed=1,
            frame_count=5,
            anchor_policy=ANCHOR_CARRY,
            workflow_id="w",
            workflow_version="1",
        ),
        SegmentSpec(
            index=2,
            seed=1,
            frame_count=5,
            anchor_policy=ANCHOR_SOURCE,
            workflow_id="w",
            workflow_version="1",
            anchor_path="x.png",
        ),
    )
    plan = SequencePlan(sequence_id="s", stage=STAGE_VIDEO_WORKFLOW, fps=24, segments=segments)

    errors = " | ".join(plan.validate())

    assert "segment 0 starts from the job's source image" in errors
    assert "numbered 2" in errors and "cannot use the 'source' anchor" in errors
    assert "carries an anchor path or hash" in errors


# ----------------------------------------------------------------------------- native SVD


def test_an_svd_plan_takes_only_seeds_and_frame_counts() -> None:
    config = SVDConfig()
    plan = freeze_svd_sequence_plan(
        {"segments": [{"frame_count": 14}, {"frame_count": 14, "seed": 3}]}, config=config
    )

    assert plan.stage == STAGE_SVD_NATIVE and plan.fps == svd_sequence_fps(config)
    assert [s.workflow_id for s in plan.segments] == [None, None]
    assert plan.segments[1].seed == 3
    for forbidden in ("workflow_id", "prompt", "negative_prompt", "workflow_version"):
        with pytest.raises(SequencePlanError, match="takes no"):
            freeze_svd_sequence_plan(
                {"segments": [{"frame_count": 14}, {"frame_count": 14, forbidden: "x"}]},
                config=config,
            )
    with pytest.raises(SequencePlanError, match="at most"):
        freeze_svd_sequence_plan(
            {"segments": [{"frame_count": 14}, {"frame_count": 99}]}, config=config
        )


def test_an_svd_sequence_refuses_a_loop_export_and_scales_fps_by_rife() -> None:
    from src.video.svd_config import SVDInterpolationConfig, SVDOutputConfig, SVDPostprocessConfig

    with pytest.raises(SequencePlanError, match="loop or ping-pong"):
        freeze_svd_sequence_plan(
            {"segments": [{"frame_count": 14}, {"frame_count": 14}]},
            config=SVDConfig(output=SVDOutputConfig(loop_mode="ping_pong")),
        )
    config = SVDConfig(
        postprocess=SVDPostprocessConfig(
            interpolation=SVDInterpolationConfig(enabled=True, multiplier=2)
        )
    )
    assert svd_sequence_fps(config) == config.inference.fps * 2
