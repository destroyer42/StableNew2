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
