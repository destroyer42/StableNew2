"""Canonical NJR-backed derivation helpers for staged-curation workflows."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from src.pipeline.reprocess_builder import (
    ReprocessJobBuilder,
    ReprocessJobPlan,
    ReprocessSourceItem,
)
from src.state.output_routing import OUTPUT_ROUTE_LEARNING

from .curation_manifest import (
    build_candidate_lineage_block,
    build_selection_event_block,
)
from .models import (
    CurationCandidate,
    CurationWorkflow,
    FaceTriageProfile,
    SelectionEvent,
)

DerivedStage = Literal["refine", "face_triage", "upscale"]


@dataclass(slots=True)
class CurationSourceSelection:
    candidate: CurationCandidate
    source_item: Any
    selection_event: SelectionEvent
    reprocess_item: ReprocessSourceItem
    face_triage_tier: str = "medium"


class CurationWorkflowBuilder:
    """Compile staged-curation selections into canonical reprocess NJRs."""

    DEFAULT_FACE_TRIAGE_PROFILES: dict[str, FaceTriageProfile] = {
        "skip": FaceTriageProfile(
            tier="skip",
            confidence=0.69,
            denoise=0.25,
            steps=8,
            mask_padding=32,
        ),
        "light": FaceTriageProfile(
            tier="light",
            confidence=0.74,
            denoise=0.18,
            steps=6,
            mask_padding=24,
        ),
        "medium": FaceTriageProfile(
            tier="medium",
            confidence=0.69,
            denoise=0.25,
            steps=8,
            mask_padding=32,
        ),
        "heavy": FaceTriageProfile(
            tier="heavy",
            confidence=0.62,
            denoise=0.34,
            steps=12,
            mask_padding=48,
        ),
    }

    _TARGET_TO_STAGE: dict[DerivedStage, list[str]] = {
        "refine": ["img2img"],
        "face_triage": ["adetailer"],
        "upscale": ["upscale"],
    }

    _TARGET_TO_LABEL: dict[DerivedStage, str] = {
        "refine": "Refine",
        "face_triage": "Face Triage",
        "upscale": "Upscale",
    }

    def __init__(self, builder: ReprocessJobBuilder | None = None) -> None:
        self._builder = builder or ReprocessJobBuilder()

    @classmethod
    def get_face_triage_tier_options(cls) -> list[str]:
        return list(cls.DEFAULT_FACE_TRIAGE_PROFILES.keys())

    @classmethod
    def resolve_face_triage_profile(cls, tier: str | None) -> FaceTriageProfile:
        normalized = str(tier or "medium").strip().lower()
        return cls.DEFAULT_FACE_TRIAGE_PROFILES.get(normalized, cls.DEFAULT_FACE_TRIAGE_PROFILES["medium"])

    @classmethod
    def apply_learning_output_route(cls, config: dict[str, Any]) -> dict[str, Any]:
        updated = deepcopy(config or {})
        pipeline_cfg = updated.setdefault("pipeline", {})
        if not isinstance(pipeline_cfg, dict):
            pipeline_cfg = {}
            updated["pipeline"] = pipeline_cfg
        pipeline_cfg["output_route"] = OUTPUT_ROUTE_LEARNING
        return updated

    def build_derived_stage_plan(
        self,
        *,
        workflow: CurationWorkflow,
        target_stage: DerivedStage,
        selections: list[CurationSourceSelection],
        fallback_config: dict[str, Any] | None = None,
        output_dir: str = "output",
    ) -> ReprocessJobPlan:
        if not selections:
            return ReprocessJobPlan()

        stages = list(self._TARGET_TO_STAGE[target_stage])
        routed_config = self.apply_learning_output_route(fallback_config or {})
        working_items: list[ReprocessSourceItem] = []
        for selection in selections:
            item = self._build_reprocess_item_for_target(
                target_stage=target_stage,
                selection=selection,
            )
            if item is not None:
                working_items.append(item)

        if not working_items:
            return ReprocessJobPlan()

        return self._builder.build_grouped_reprocess_jobs(
            items=working_items,
            stages=stages,
            fallback_config=routed_config,
            batch_size=1,
            pack_name=f"Curation{self._TARGET_TO_LABEL[target_stage]}",
            source=f"staged_curation_{target_stage}",
            output_dir=output_dir,
            extra_metadata_builder=lambda chunk, _job_output_dir: self._build_chunk_metadata(
                workflow=workflow,
                target_stage=target_stage,
                chunk=chunk,
            ),
        )

    def build_run_request(self, jobs: list[Any], *, target_stage: DerivedStage):
        return self._builder.build_run_request(
            jobs,
            source=f"staged_curation_{target_stage}",
            requested_job_label=f"Staged Curation: {self._TARGET_TO_LABEL[target_stage]}",
        )

    def _build_reprocess_item_for_target(
        self,
        *,
        target_stage: DerivedStage,
        selection: CurationSourceSelection,
    ) -> ReprocessSourceItem | None:
        source = selection.reprocess_item
        metadata = deepcopy(source.metadata or {})
        metadata["curation_source_selection"] = {
            "candidate_id": selection.candidate.candidate_id,
            "decision": selection.selection_event.decision,
            "face_triage_tier": selection.face_triage_tier,
            "target_stage": target_stage,
        }
        config = deepcopy(source.config or {})

        if target_stage == "face_triage":
            tier = str(selection.face_triage_tier or "medium").strip().lower()
            if tier == "skip":
                return None
            profile = self.resolve_face_triage_profile(tier)
            ad_cfg = config.setdefault("adetailer", {})
            if not isinstance(ad_cfg, dict):
                ad_cfg = {}
                config["adetailer"] = ad_cfg
            ad_cfg.update(
                {
                    "adetailer_confidence": profile.confidence,
                    "ad_confidence": profile.confidence,
                    "adetailer_denoise": profile.denoise,
                    "ad_denoising_strength": profile.denoise,
                    "adetailer_steps": profile.steps,
                    "ad_steps": profile.steps,
                    "ad_inpaint_only_masked_padding": profile.mask_padding,
                    "adetailer_padding": profile.mask_padding,
                }
            )
            metadata["face_triage_profile"] = profile.to_dict()

        return ReprocessSourceItem(
            input_image_path=source.input_image_path,
            prompt=source.prompt,
            negative_prompt=source.negative_prompt,
            model=source.model,
            vae=source.vae,
            config=config,
            metadata=metadata,
            output_dir=source.output_dir,
            image_edit=source.image_edit,
        )

    def _build_chunk_metadata(
        self,
        *,
        workflow: CurationWorkflow,
        target_stage: DerivedStage,
        chunk: list[ReprocessSourceItem],
    ) -> dict[str, Any]:
        if not chunk:
            return {}
        item = chunk[0]
        selection_meta = dict((item.metadata or {}).get("curation_source_selection") or {})
        candidate = item.metadata.get("curation_candidate")
        event = item.metadata.get("curation_selection_event")
        payload: dict[str, Any] = {
            "curation_derived_stage": {
                "workflow_id": workflow.workflow_id,
                "target_stage": target_stage,
                "source_candidate_id": str(selection_meta.get("candidate_id") or ""),
                "source_decision": str(selection_meta.get("decision") or ""),
                "face_triage_tier": str(selection_meta.get("face_triage_tier") or ""),
            }
        }
        if isinstance(candidate, CurationCandidate):
            source_decision = str(selection_meta.get("decision") or "").strip() or None
            payload.update(
                build_candidate_lineage_block(
                    candidate,
                    source_decision=source_decision,
                )
            )
        if isinstance(event, SelectionEvent):
            payload["selection_event"] = build_selection_event_block(event)
        return payload
