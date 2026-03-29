"""Non-render review workflow logic for Review tab."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from src.curation.curation_manifest import build_serialized_curation_source_metadata
from src.pipeline.reprocess_builder import ReprocessEffectiveSettingsPreview, ReprocessJobBuilder
from src.utils.image_metadata import resolve_model_vae_fields, resolve_prompt_fields


@dataclass(frozen=True)
class ReviewPromptDiff:
    before_text: str
    after_text: str
    after_prompt: str
    after_negative_prompt: str


@dataclass(frozen=True)
class ReviewWorkspaceHandoff:
    source: str
    workflow_title: str
    target_stage: str
    image_paths: list[Path]
    base_prompt: str
    base_negative_prompt: str
    prompt_delta: str
    negative_prompt_delta: str
    prompt_mode: str
    negative_prompt_mode: str
    stage_img2img: bool
    stage_adetailer: bool
    stage_upscale: bool
    source_candidate_ids: list[str] = field(default_factory=list)
    source_metadata_by_path: dict[str, dict[str, Any]] = field(default_factory=dict)
    direct_queue_preview: ReprocessEffectiveSettingsPreview | None = None


class ReviewWorkflowAdapter:
    """Pure logic adapter that can be reused across GUI hosts."""

    _STAGED_TARGET_TO_FLAGS: dict[str, tuple[bool, bool, bool]] = {
        "refine": (True, False, False),
        "face_triage": (False, True, False),
        "upscale": (False, False, True),
    }

    @staticmethod
    def apply_prompt_delta(base: str, delta: str, mode: str) -> str:
        base_clean = (base or "").strip()
        delta_clean = (delta or "").strip()
        if not delta_clean:
            return base_clean
        if mode == "replace":
            return delta_clean
        if mode == "modify":
            return ReviewWorkflowAdapter._apply_modify_delta(base_clean, delta_clean)
        if not base_clean:
            return delta_clean
        return f"{base_clean}, {delta_clean}"

    @staticmethod
    def _apply_modify_delta(base: str, delta: str) -> str:
        base_clean = (base or "").strip()
        delta_clean = (delta or "").strip()
        if not delta_clean:
            return base_clean
        if not base_clean:
            return delta_clean
        if not ReviewWorkflowAdapter._has_modify_instructions(delta_clean):
            if ReviewWorkflowAdapter._looks_like_full_prompt_edit(base_clean, delta_clean):
                return delta_clean
            return ReviewWorkflowAdapter._append_prompt_terms(base_clean, delta_clean)

        terms = ReviewWorkflowAdapter._split_prompt_terms(base_clean)
        for instruction in ReviewWorkflowAdapter._split_prompt_terms(delta_clean):
            if not instruction:
                continue
            if instruction.startswith("+"):
                terms = ReviewWorkflowAdapter._add_term(terms, instruction[1:])
                continue
            if instruction.startswith("-"):
                terms = ReviewWorkflowAdapter._remove_term(terms, instruction[1:])
                continue
            if "->" in instruction:
                old_term, new_term = instruction.split("->", 1)
                terms = ReviewWorkflowAdapter._replace_term(terms, old_term, new_term)
                continue
            if "=>" in instruction:
                old_term, new_term = instruction.split("=>", 1)
                terms = ReviewWorkflowAdapter._replace_term(terms, old_term, new_term)
                continue
            terms = ReviewWorkflowAdapter._add_term(terms, instruction)
        return ", ".join(terms)

    @staticmethod
    def _has_modify_instructions(text: str) -> bool:
        for item in ReviewWorkflowAdapter._split_prompt_terms(text):
            if item.startswith(("+", "-")):
                return True
            if "->" in item or "=>" in item:
                return True
        return False

    @staticmethod
    def _looks_like_full_prompt_edit(base: str, delta: str) -> bool:
        if delta == base:
            return True
        base_terms = ReviewWorkflowAdapter._split_prompt_terms(base)
        delta_terms = ReviewWorkflowAdapter._split_prompt_terms(delta)
        if not base_terms or not delta_terms:
            return False
        shared = {
            term.casefold() for term in base_terms
        } & {
            term.casefold() for term in delta_terms
        }
        overlap_ratio = len(shared) / max(len(base_terms), 1)
        if overlap_ratio >= 0.5:
            return True
        return len(delta) >= max(32, int(len(base) * 0.6))

    @staticmethod
    def _append_prompt_terms(base: str, delta: str) -> str:
        terms = ReviewWorkflowAdapter._split_prompt_terms(base)
        for item in ReviewWorkflowAdapter._split_prompt_terms(delta):
            terms = ReviewWorkflowAdapter._add_term(terms, item)
        return ", ".join(terms)

    @staticmethod
    def _split_prompt_terms(text: str) -> list[str]:
        return [part.strip() for part in str(text or "").split(",") if part.strip()]

    @staticmethod
    def _add_term(terms: list[str], term: str) -> list[str]:
        clean = str(term or "").strip()
        if not clean:
            return terms
        if any(existing.casefold() == clean.casefold() for existing in terms):
            return terms
        return [*terms, clean]

    @staticmethod
    def _remove_term(terms: list[str], term: str) -> list[str]:
        clean = str(term or "").strip()
        if not clean:
            return terms
        return [existing for existing in terms if existing.casefold() != clean.casefold()]

    @staticmethod
    def _replace_term(terms: list[str], old_term: str, new_term: str) -> list[str]:
        old_clean = str(old_term or "").strip()
        new_clean = str(new_term or "").strip()
        if not old_clean:
            return ReviewWorkflowAdapter._add_term(terms, new_clean)
        updated: list[str] = []
        replaced = False
        for existing in terms:
            if not replaced and existing.casefold() == old_clean.casefold():
                if new_clean and not any(item.casefold() == new_clean.casefold() for item in updated):
                    updated.append(new_clean)
                replaced = True
                continue
            if new_clean and existing.casefold() == new_clean.casefold():
                continue
            updated.append(existing)
        if not replaced:
            return ReviewWorkflowAdapter._add_term(updated, new_clean)
        return updated

    @staticmethod
    def clip_text(text: str, max_len: int = 220) -> str:
        clean = (text or "").strip()
        if not clean:
            return "(empty)"
        if len(clean) <= max_len:
            return clean
        return f"{clean[:max_len-3]}..."

    def build_staged_curation_handoff(self, *, plan: Any) -> ReviewWorkspaceHandoff | None:
        selections = list(getattr(plan, "selections", []) or [])
        if not selections:
            return None

        image_paths: list[Path] = []
        seen_paths: set[str] = set()
        source_candidate_ids: list[str] = []
        source_metadata_by_path: dict[str, dict[str, Any]] = {}
        base_prompt = ""
        base_negative_prompt = ""

        for selection in selections:
            candidate = getattr(selection, "candidate", None)
            candidate_id = str(getattr(candidate, "candidate_id", "") or "").strip()
            if candidate_id:
                source_candidate_ids.append(candidate_id)

            source_item = getattr(selection, "source_item", None)
            artifact_path = str(getattr(source_item, "artifact_path", "") or "").strip()
            if artifact_path:
                path_obj = Path(artifact_path)
                dedupe_key = str(path_obj)
                if dedupe_key not in seen_paths:
                    seen_paths.add(dedupe_key)
                    image_paths.append(path_obj)

            event = getattr(selection, "selection_event", None)
            if candidate is not None and event is not None and artifact_path:
                source_metadata_by_path[str(Path(artifact_path))] = build_serialized_curation_source_metadata(
                    candidate,
                    event,
                    source_stage=str(getattr(source_item, "stage", "") or getattr(candidate, "stage", "") or ""),
                    face_triage_tier=str(getattr(selection, "face_triage_tier", "") or ""),
                )

            reprocess_item = getattr(selection, "reprocess_item", None)
            if not base_prompt:
                base_prompt = str(getattr(reprocess_item, "prompt", "") or getattr(source_item, "positive_prompt", "") or "")
            if not base_negative_prompt:
                base_negative_prompt = str(
                    getattr(reprocess_item, "negative_prompt", "")
                    or getattr(source_item, "negative_prompt", "")
                    or ""
                )

        if not image_paths:
            return None

        target_stage = str(getattr(plan, "target_stage", "") or "").strip().lower()
        stage_img2img, stage_adetailer, stage_upscale = self._STAGED_TARGET_TO_FLAGS.get(
            target_stage,
            (False, False, False),
        )
        workflow = getattr(plan, "workflow", None)
        direct_queue_preview = None
        jobs = list(getattr(plan, "jobs", []) or [])
        if jobs:
            first_selection = selections[0]
            first_source_item = getattr(first_selection, "source_item", None)
            first_reprocess_item = getattr(first_selection, "reprocess_item", None)
            builder = ReprocessJobBuilder()
            direct_queue_preview = builder.build_effective_settings_preview(
                source_stage=str(
                    getattr(first_source_item, "stage", "")
                    or getattr(getattr(first_selection, "candidate", None), "stage", "")
                    or "unknown"
                ),
                source_model=getattr(first_reprocess_item, "model", None),
                source_vae=getattr(first_reprocess_item, "vae", None),
                stages=list(self._TARGET_TO_STAGE_FLAGS(target_stage)),
                fallback_config=getattr(jobs[0], "config", {}) or {},
                metadata_config={},
                prompt=str(getattr(first_reprocess_item, "prompt", "") or ""),
                negative_prompt=str(getattr(first_reprocess_item, "negative_prompt", "") or ""),
                prompt_mode="append",
                negative_prompt_mode="append",
                prompt_delta="",
                negative_prompt_delta="",
                source_baseline_label="staged curation source baseline",
                fallback_source_label="staged curation queue baseline",
            )
        return ReviewWorkspaceHandoff(
            source="staged_curation",
            workflow_title=str(getattr(workflow, "title", "") or ""),
            target_stage=target_stage,
            image_paths=image_paths,
            base_prompt=base_prompt,
            base_negative_prompt=base_negative_prompt,
            prompt_delta="",
            negative_prompt_delta="",
            prompt_mode="append",
            negative_prompt_mode="append",
            stage_img2img=stage_img2img,
            stage_adetailer=stage_adetailer,
            stage_upscale=stage_upscale,
            source_candidate_ids=source_candidate_ids,
            source_metadata_by_path=source_metadata_by_path,
            direct_queue_preview=direct_queue_preview,
        )

    @classmethod
    def _TARGET_TO_STAGE_FLAGS(cls, target_stage: str) -> list[str]:
        if target_stage == "refine":
            return ["img2img"]
        if target_stage == "face_triage":
            return ["adetailer"]
        if target_stage == "upscale":
            return ["upscale"]
        return []

    @staticmethod
    def _format_stage_preview(stage_preview: Any) -> str:
        def _format_field(name: str, value: Any, source: Any) -> str:
            value_text = "n/a" if value is None else str(value)
            source_text = str(source or "active resolution")
            return f"{name}={value_text} [{source_text}]"

        bits = [str(getattr(stage_preview, "stage", "") or "stage")]
        bits.append(_format_field("sampler", getattr(stage_preview, "sampler", None), getattr(stage_preview, "sampler_source", None)))
        bits.append(_format_field("scheduler", getattr(stage_preview, "scheduler", None), getattr(stage_preview, "scheduler_source", None)))
        bits.append(_format_field("steps", getattr(stage_preview, "steps", None), getattr(stage_preview, "steps_source", None)))
        bits.append(_format_field("cfg", getattr(stage_preview, "cfg_scale", None), getattr(stage_preview, "cfg_scale_source", None)))
        bits.append(_format_field("denoise", getattr(stage_preview, "denoise", None), getattr(stage_preview, "denoise_source", None)))
        return " | ".join(bits)

    def format_effective_settings_summary(
        self,
        preview: ReprocessEffectiveSettingsPreview | None,
        *,
        direct_queue_preview: ReprocessEffectiveSettingsPreview | None = None,
    ) -> str:
        if preview is None:
            return "Effective settings: unavailable"

        lines = [
            f"Source: stage={preview.source_stage} | model={preview.source_model or 'n/a'} | vae={preview.source_vae or 'n/a'}",
            f"Targets: {' -> '.join(preview.target_stages) or 'n/a'}",
            f"Why these values are active: {preview.metadata_source_label} overrides {preview.fallback_source_label}; {preview.default_source_label} fill any remaining gaps.",
            f"Positive prompt: {preview.positive_prompt_behavior} [{'explicit edit' if preview.positive_prompt_behavior != 'inherited' else preview.source_baseline_label}]",
            f"Negative prompt: {preview.negative_prompt_behavior} [{'explicit edit' if preview.negative_prompt_behavior != 'inherited' else preview.source_baseline_label}]",
        ]
        for stage_preview in list(preview.stage_settings or []):
            lines.append(self._format_stage_preview(stage_preview))

        if direct_queue_preview is not None:
            lines.append("")
            lines.append("Direct Queue Now baseline:")
            lines.append(
                f"Source: stage={direct_queue_preview.source_stage} | model={direct_queue_preview.source_model or 'n/a'} | vae={direct_queue_preview.source_vae or 'n/a'}"
            )
            lines.append(f"Targets: {' -> '.join(direct_queue_preview.target_stages) or 'n/a'}")
            for stage_preview in list(direct_queue_preview.stage_settings or []):
                lines.append(self._format_stage_preview(stage_preview))

        return "\n".join(lines)

    def build_prompt_diff(
        self,
        *,
        base_prompt: str,
        base_negative_prompt: str,
        prompt_delta: str,
        negative_prompt_delta: str,
        prompt_mode: str,
        negative_prompt_mode: str,
    ) -> ReviewPromptDiff:
        after_prompt = self.apply_prompt_delta(base_prompt, prompt_delta, prompt_mode)
        after_negative = self.apply_prompt_delta(
            base_negative_prompt,
            negative_prompt_delta,
            negative_prompt_mode,
        )
        before_text = (
            f"Before +: {self.clip_text(base_prompt)}\n"
            f"Before -: {self.clip_text(base_negative_prompt)}"
        )
        after_text = (
            f"After +: {self.clip_text(after_prompt)}\n"
            f"After -: {self.clip_text(after_negative)}"
        )
        return ReviewPromptDiff(
            before_text=before_text,
            after_text=after_text,
            after_prompt=after_prompt,
            after_negative_prompt=after_negative,
        )

    def build_feedback_payload(
        self,
        *,
        image_path: Path,
        metadata_payload: dict[str, Any],
        rating: int,
        quality_label: str,
        notes: str,
        prompt_delta: str,
        negative_prompt_delta: str,
        prompt_mode: str,
        negative_prompt_mode: str,
        stages: list[str],
        anatomy_rating: int,
        composition_rating: int,
        prompt_adherence_rating: int,
    ) -> dict[str, Any]:
        stage_manifest = metadata_payload.get("stage_manifest", {})
        if not isinstance(stage_manifest, dict):
            stage_manifest = {}
        generation = metadata_payload.get("generation", {})
        if not isinstance(generation, dict):
            generation = {}
        base_prompt, base_negative = resolve_prompt_fields(metadata_payload)
        model, _vae = resolve_model_vae_fields(metadata_payload)
        diff = self.build_prompt_diff(
            base_prompt=base_prompt,
            base_negative_prompt=base_negative,
            prompt_delta=prompt_delta,
            negative_prompt_delta=negative_prompt_delta,
            prompt_mode=prompt_mode,
            negative_prompt_mode=negative_prompt_mode,
        )
        return {
            "image_path": str(image_path),
            "rating": int(rating),
            "quality_label": str(quality_label or ""),
            "notes": str(notes or ""),
            "base_prompt": base_prompt,
            "base_negative_prompt": base_negative,
            "after_prompt": diff.after_prompt,
            "after_negative_prompt": diff.after_negative_prompt,
            "prompt_delta": str(prompt_delta or ""),
            "negative_prompt_delta": str(negative_prompt_delta or ""),
            "prompt_mode": str(prompt_mode or "append"),
            "negative_prompt_mode": str(negative_prompt_mode or "append"),
            "stages": list(stages or []),
            "subscores": {
                "anatomy": int(anatomy_rating),
                "composition": int(composition_rating),
                "prompt_adherence": int(prompt_adherence_rating),
            },
            "model": str(model or ""),
            "sampler": str(stage_manifest.get("sampler_name") or generation.get("sampler_name") or ""),
            "scheduler": str(stage_manifest.get("scheduler") or generation.get("scheduler") or ""),
            "steps": stage_manifest.get("steps") or generation.get("steps"),
            "cfg_scale": stage_manifest.get("cfg_scale") or generation.get("cfg_scale"),
        }
