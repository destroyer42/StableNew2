"""Temporary, default-off PR-VID-193 AD0 Review submission bridge."""

from __future__ import annotations

import hashlib
import json
import os
import uuid
from pathlib import Path
from typing import Any

from src.controller.submission_policy_v26 import SubmissionPolicy
from src.pipeline.reprocess_builder import ReprocessJobBuilder
from src.state.output_routing import classify_njr_output_route, get_output_route_root
from src.video.video_backend_registry import build_default_video_backend_registry
from src.video.video_execution_resolver import VideoExecutionResolver

_DESCRIPTOR_PATH = (
    Path(__file__).resolve().parents[3]
    / "docs/Subsystems/Video/PR-VID-193_AD0_qualification.json"
)
_DESCRIPTOR_SHA256 = "e6bf26a45390ec85e9919298d1cd4b58b834722aa5965ef2b599b00c19c3a70b"


def qualification_enabled() -> bool:
    return os.environ.get("STABLENEW_VID193_QUALIFICATION") == "1"


class Vid193Ad0QualificationAdapter:
    def __init__(self, *, descriptor_path: Path = _DESCRIPTOR_PATH) -> None:
        self._descriptor_path = descriptor_path
        self._submitted = False
        self._prepared_job_id: str | None = None

    @staticmethod
    def _hash_descriptor(data: dict[str, Any]) -> str:
        canonical = json.dumps(data, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()

    def prepare(self, selected_paths: list[Path]) -> tuple[Any, str]:
        if not qualification_enabled():
            raise RuntimeError("PR-VID-193 qualification mode is disabled")
        if self._submitted:
            raise RuntimeError("AD0 was already submitted from this Review session")
        if len(selected_paths) != 1:
            raise ValueError("Select exactly one AD0 source image")

        descriptor = json.loads(self._descriptor_path.read_text(encoding="utf-8"))
        digest = self._hash_descriptor(descriptor)
        if digest != _DESCRIPTOR_SHA256:
            raise ValueError("Frozen AD0 descriptor hash does not match")
        source = Path(descriptor["source_image_path"])
        selected = selected_paths[0]
        if selected.resolve() != source.resolve():
            raise ValueError("Selected image is not the frozen AD0 source")
        if hashlib.sha256(source.read_bytes()).hexdigest() != descriptor["source_sha256"]:
            raise ValueError("Frozen AD0 source hash does not match")

        config = descriptor["config"]
        stage_config = config["animatediff"]
        output = config["pipeline"]
        job_id = uuid.uuid5(uuid.NAMESPACE_URL, f"PR-VID-193-AD0:{digest}").hex
        njr = ReprocessJobBuilder(id_fn=lambda: job_id).build_reprocess_job(
            input_image_paths=[source],
            stages=["animatediff"],
            config=config,
            output_dir=output["output_dir"],
            prompt=descriptor["prompt"],
            negative_prompt=descriptor["negative_prompt"],
            model=descriptor["checkpoint"],
            pack_name="PR-VID-193 AD0 qualification",
            source="video",
            extra_metadata={"qualification": {"id": descriptor["qualification_id"], "sha256": digest}},
        )
        if njr.start_stage != "animatediff" or njr.stage_chain_labels != ["animatediff"]:
            raise ValueError("AD0 builder produced an unexpected stage chain")
        if tuple(njr.input_image_paths) != (str(source),):
            raise ValueError("AD0 builder produced unexpected source inputs")
        if classify_njr_output_route(njr) != output["output_route"]:
            raise ValueError("AD0 output route did not resolve as frozen")

        stage = njr.stage_chain[0].to_dict()
        stage.update(stage.pop("extra"))
        registry = build_default_video_backend_registry()
        resolver = VideoExecutionResolver(registry)
        intent = resolver.build_intent("animatediff", stage, has_source_image=True)
        backend = resolver.resolve("animatediff", intent)
        if backend.backend_id != "animatediff":
            raise ValueError("AD0 did not resolve to AnimateDiffVideoBackend")
        preview = {
            "qualification": descriptor["qualification_id"],
            "descriptor_sha256": digest,
            "job_id": njr.job_id,
            "job_count": 1,
            "source_image_path": str(source),
            "source_sha256": descriptor["source_sha256"],
            "start_stage": njr.start_stage,
            "stage_chain": njr.stage_chain_labels,
            "resolved_backend": backend.backend_id,
            "prompt": njr.positive_prompt,
            "negative_prompt": njr.negative_prompt,
            "checkpoint": njr.base_model,
            "required_a1111_options": descriptor["required_a1111_options"],
            "stage_config": stage,
            "output_dir": njr.path_output_dir,
            "output_route": classify_njr_output_route(njr),
            "effective_routed_root": str(
                get_output_route_root(njr.path_output_dir, output["output_route"], create=False)
            ),
        }
        if any(stage.get(key) != value for key, value in stage_config.items()):
            raise ValueError("Frozen AD0 stage settings changed during preparation")
        self._prepared_job_id = njr.job_id
        return njr, json.dumps(preview, indent=2, ensure_ascii=False)

    def submit(self, njr: Any, job_service: Any) -> str:
        if not qualification_enabled() or self._submitted:
            raise RuntimeError("AD0 submission is disabled or already attempted")
        if njr.job_id != self._prepared_job_id:
            raise RuntimeError("AD0 NJR was not prepared by this Review session")
        self._submitted = True  # An ambiguous submission must never be retried from this session.
        job_ids = job_service.submit_njrs([njr], SubmissionPolicy())
        if job_ids != [njr.job_id]:
            raise RuntimeError("JobService did not return the single frozen AD0 Job ID")
        return job_ids[0]
