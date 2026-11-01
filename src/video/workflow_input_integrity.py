"""Exact prepared-motion admission/dispatch policy, opt-in by workflow declaration."""

import hashlib
import json
from collections.abc import Mapping
from fractions import Fraction
from typing import Any

from src.video.motion_source_plan import motion_source_contract
from src.video.motion_source_preparation import sha256_file, validate_prepared_record
from src.video.workflow_frame_count import frame_count_policy, parse_frame_count


def workflow_identity(spec: Any) -> dict[str, Any]:
    graph = json.dumps(
        spec.backend_defaults["prompt_template"], sort_keys=True, separators=(",", ":")
    )
    return {
        "graph_sha256": hashlib.sha256(graph.encode()).hexdigest(),
        "assets": spec.backend_defaults["asset_integrity"],
        "resource_readiness": spec.backend_defaults["resource_readiness"],
    }


def requires_exact_motion(spec: Any) -> bool:
    return (spec.backend_defaults.get("motion_source_policy") or {}).get(
        "exact_prepared_frames"
    ) is True


def verify_exact_motion(
    spec: Any,
    record: Any,
    *,
    frame_count: Any,
    original_path: str,
    driving_path: str = "",
    driving_sha256: str = "",
) -> dict[str, Any] | None:
    if not requires_exact_motion(spec):
        return None
    if not isinstance(record, Mapping) or not record:
        raise ValueError(
            "Use Prepare Motion Source and accept the exact driving frames at 24 FPS before Preview/Queue."
        )
    contract = motion_source_contract(spec, frame_count)
    data = validate_prepared_record(record, original_path=original_path, contract=contract)
    derived = data["derived"]
    digest = str(derived.get("frames_md5_sha256") or "")
    try:
        rate_matches = Fraction(str(derived.get("frame_rate"))) == contract.output_fps
    except (ValueError, ZeroDivisionError):
        rate_matches = False
    if not rate_matches:
        raise ValueError(
            "Driving / Control Video must be prepared at 24 FPS; choose workflow-rate conversion and prepare again."
        )
    if len(digest) != 64 or any(c not in "0123456789abcdef" for c in digest):
        raise ValueError(
            "Prepared motion source has no verified ordered-frame identity. Prepare it again."
        )
    if data.get("processing", {}).get("lossless") is not True:
        raise ValueError("Prepared motion source must be verified lossless. Prepare it again.")
    if data["contract"].get("runtime_revision") != contract.runtime_revision:
        raise ValueError("Prepared motion source runtime identity changed. Prepare it again.")
    if driving_path and (derived["path"] != driving_path or derived["sha256"] != driving_sha256):
        raise ValueError("Prepared motion source differs from the frozen Driving / Control Video.")
    return data


def verify_exact_dispatch_inputs(spec: Any, request: Any) -> None:
    if not requires_exact_motion(spec):
        return
    stage = request.stage_config or {}
    parse_frame_count(spec, stage.get("frame_count"))
    if stage.get("fps") != (frame_count_policy(spec) or {}).get("fps"):
        raise ValueError("Frozen output FPS differs from the workflow's 24 FPS contract.")
    if type(stage.get("seed")) is not int or not 0 <= stage["seed"] < 2**31:
        raise ValueError("A concrete frozen seed is required at dispatch.")
    geometry = stage.get("source_preparation") or {}
    target = geometry.get("target_dimensions")
    policy = spec.backend_defaults["source_preparation"]
    if target not in (
        policy["portrait_target"],
        policy["landscape_target"],
    ) or target != geometry.get("prepared_dimensions"):
        raise ValueError("Frozen output geometry differs from the prepared reference image.")
    if stage.get("workflow_identity") != workflow_identity(spec):
        raise ValueError(
            "Frozen workflow graph or model identity differs from the registered version."
        )
    record = stage.get("motion_source_preparation") or {}
    verify_exact_motion(
        spec,
        record,
        frame_count=stage.get("frame_count"),
        original_path=(record.get("original") or {}).get("path", ""),
        driving_path=str(stage.get("pose_video_path") or ""),
        driving_sha256=str(stage.get("pose_video_sha256") or ""),
    )
    if not stage.get("pose_video_path"):
        raise ValueError("Frozen Driving / Control Video is missing.")
    source = stage.get("reference_identity") or {}
    expected = source.get("prepared_sha256")
    if (
        not expected
        or str(request.input_image_path) != source.get("prepared_path")
        or sha256_file(request.input_image_path) != expected
    ):
        raise ValueError("Reference image changed since Preview/admission.")
    if sha256_file(source["original_path"]) != source["original_sha256"]:
        raise ValueError("Original reference image changed since Preview/admission.")
    from PIL import Image

    with Image.open(request.input_image_path) as image:
        if image.size != (target["width"], target["height"]):
            raise ValueError(
                "Prepared reference dimensions differ from the frozen output geometry."
            )
