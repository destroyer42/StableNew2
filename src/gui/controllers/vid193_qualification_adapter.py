"""Temporary, default-off PR-VID-193 frozen-arm Review submission bridge."""

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

_DESCRIPTOR_ROOT = Path(__file__).resolve().parents[3] / "docs/Subsystems/Video"
_DESCRIPTOR_SHA256 = {
    "AD0": "e6bf26a45390ec85e9919298d1cd4b58b834722aa5965ef2b599b00c19c3a70b",
    "AD1": "4240e65e1322cda58fe718aaab6c53aa3ee6943a04484f32c9d1a67fec1cedae",
}


def qualification_mode() -> str | None:
    return {"1": "AD0", "AD0": "AD0", "AD1": "AD1"}.get(
        os.environ.get("STABLENEW_VID193_QUALIFICATION", "")
    )


def qualification_enabled() -> bool:
    return qualification_mode() is not None


class Vid193QualificationAdapter:
    def __init__(self, *, descriptor_path: Path | None = None) -> None:
        self.arm = qualification_mode() or "AD0"
        self._descriptor_path = descriptor_path or (
            _DESCRIPTOR_ROOT / f"PR-VID-193_{self.arm}_qualification.json"
        )
        self._submitted = False
        self._prepared_job_id: str | None = None

    @staticmethod
    def _hash_descriptor(data: dict[str, Any]) -> str:
        canonical = json.dumps(data, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()

    def prepare(self, selected_paths: list[Path]) -> tuple[Any, str]:
        if qualification_mode() != self.arm:
            raise RuntimeError("PR-VID-193 qualification mode is disabled or changed")
        if self._submitted:
            raise RuntimeError(f"{self.arm} was already submitted from this Review session")
        if len(selected_paths) != 1:
            raise ValueError(f"Select exactly one {self.arm} source image")

        descriptor = json.loads(self._descriptor_path.read_text(encoding="utf-8"))
        digest = self._hash_descriptor(descriptor)
        if digest != _DESCRIPTOR_SHA256[self.arm]:
            raise ValueError(f"Frozen {self.arm} descriptor hash does not match")
        source = Path(descriptor["source_image_path"])
        selected = selected_paths[0]
        if selected.resolve() != source.resolve():
            raise ValueError(f"Selected image is not the frozen {self.arm} source")
        if hashlib.sha256(source.read_bytes()).hexdigest() != descriptor["source_sha256"]:
            raise ValueError(f"Frozen {self.arm} source hash does not match")

        config = descriptor["config"]
        stage_config = config["animatediff"]
        output = config["pipeline"]
        job_id = uuid.uuid5(uuid.NAMESPACE_URL, f"PR-VID-193-{self.arm}:{digest}").hex
        njr = ReprocessJobBuilder(id_fn=lambda: job_id).build_reprocess_job(
            input_image_paths=[source],
            stages=["animatediff"],
            config=config,
            output_dir=output["output_dir"],
            prompt=descriptor["prompt"],
            negative_prompt=descriptor["negative_prompt"],
            model=descriptor["checkpoint"],
            pack_name=f"PR-VID-193 {self.arm} qualification",
            source="video",
            extra_metadata={"qualification": {"id": descriptor["qualification_id"], "sha256": digest}},
        )
        if njr.start_stage != "animatediff" or njr.stage_chain_labels != ["animatediff"]:
            raise ValueError(f"{self.arm} builder produced an unexpected stage chain")
        if tuple(njr.input_image_paths) != (str(source),):
            raise ValueError(f"{self.arm} builder produced unexpected source inputs")
        if classify_njr_output_route(njr) != output["output_route"]:
            raise ValueError(f"{self.arm} output route did not resolve as frozen")

        stage = njr.stage_chain[0].to_dict()
        stage.update(stage.pop("extra"))
        registry = build_default_video_backend_registry()
        resolver = VideoExecutionResolver(registry)
        intent = resolver.build_intent("animatediff", stage, has_source_image=True)
        backend = resolver.resolve("animatediff", intent)
        if backend.backend_id != "animatediff":
            raise ValueError(f"{self.arm} did not resolve to AnimateDiffVideoBackend")
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
            raise ValueError(f"Frozen {self.arm} stage settings changed during preparation")
        self._prepared_job_id = njr.job_id
        return njr, json.dumps(preview, indent=2, ensure_ascii=False)

    def submit(self, njr: Any, job_service: Any) -> str:
        if qualification_mode() != self.arm or self._submitted:
            raise RuntimeError(f"{self.arm} submission is disabled, changed, or already attempted")
        if njr.job_id != self._prepared_job_id:
            raise RuntimeError(f"{self.arm} NJR was not prepared by this Review session")
        self._submitted = True  # An ambiguous submission must never be retried from this session.
        job_ids = job_service.submit_njrs([njr], SubmissionPolicy())
        if job_ids != [njr.job_id]:
            raise RuntimeError(f"JobService did not return the single frozen {self.arm} Job ID")
        return job_ids[0]
