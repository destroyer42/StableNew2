"""Non-render review workflow logic for Review tab."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from src.utils.image_metadata import resolve_model_vae_fields, resolve_prompt_fields


@dataclass(frozen=True)
class ReviewPromptDiff:
    before_text: str
    after_text: str
    after_prompt: str
    after_negative_prompt: str


class ReviewWorkflowAdapter:
    """Pure logic adapter that can be reused across GUI hosts."""

    @staticmethod
    def apply_prompt_delta(base: str, delta: str, mode: str) -> str:
        base_clean = (base or "").strip()
        delta_clean = (delta or "").strip()
        if not delta_clean:
            return base_clean
        if mode in {"replace", "modify"}:
            return delta_clean
        if not base_clean:
            return delta_clean
        return f"{base_clean}, {delta_clean}"

    @staticmethod
    def clip_text(text: str, max_len: int = 220) -> str:
        clean = (text or "").strip()
        if not clean:
            return "(empty)"
        if len(clean) <= max_len:
            return clean
        return f"{clean[:max_len-3]}..."

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
