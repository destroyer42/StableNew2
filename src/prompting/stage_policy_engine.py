from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from src.prompting.contracts import (
    PromptContext,
    PromptIntentBundle,
    StagePolicyBundle,
    StagePolicyDecision,
)


@dataclass(frozen=True, slots=True)
class StagePolicyApplicationResult:
    config: dict[str, Any]
    bundle: StagePolicyBundle


@dataclass(frozen=True, slots=True)
class _PolicyCandidate:
    key: str
    value: Any
    rationale: str


class StagePolicyEngine:
    _AUTO_SENTINELS = {"auto", "automatic"}

    def apply(
        self,
        *,
        stage_name: str,
        current_config: dict[str, Any] | None,
        prompt_context: PromptContext,
        intent: PromptIntentBundle,
        source_config: dict[str, Any] | None = None,
    ) -> StagePolicyApplicationResult:
        effective = dict(current_config or {})
        source = dict(source_config or {})
        applied_settings: dict[str, Any] = {}
        applied_decisions: list[StagePolicyDecision] = []
        preserved_decisions: list[StagePolicyDecision] = []
        recommended_decisions: list[StagePolicyDecision] = []
        warnings = self._build_warnings(prompt_context, intent)

        for candidate in self._build_candidates(stage_name, prompt_context, intent):
            source_state = self._source_state(source, candidate.key)
            current_value = effective.get(candidate.key)
            if source_state in {"missing", "auto"}:
                effective[candidate.key] = candidate.value
                applied_settings[candidate.key] = candidate.value
                applied_decisions.append(
                    StagePolicyDecision(
                        key=candidate.key,
                        value=candidate.value,
                        action="applied",
                        rationale=candidate.rationale,
                        source_state=source_state,
                    )
                )
                continue
            preserved_decisions.append(
                StagePolicyDecision(
                    key=candidate.key,
                    value=current_value,
                    action="preserved",
                    rationale=f"Explicit user value preserved; {candidate.rationale}",
                    source_state=source_state,
                )
            )

        if stage_name == "adetailer" and intent.wants_full_body and not intent.wants_portrait:
            recommended_decisions.append(
                StagePolicyDecision(
                    key="enable_face_pass",
                    value=False,
                    action="recommended",
                    rationale="Full-body prompts often produce tiny faces; consider disabling face pass if detections become unstable.",
                    source_state="heuristic",
                )
            )
        if stage_name == "upscale" and str(effective.get("upscale_mode") or "single") != "img2img" and (
            "large_chunk_count" in prompt_context.warnings or bool(intent.conflicts)
        ):
            recommended_decisions.append(
                StagePolicyDecision(
                    key="upscale_mode",
                    value="img2img",
                    action="recommended",
                    rationale="Complex prompts benefit from conservative img2img upscale controls when operator review is acceptable.",
                    source_state="heuristic",
                )
            )

        return StagePolicyApplicationResult(
            config=effective,
            bundle=StagePolicyBundle(
                stage=stage_name,
                mode="auto_safe_fill_v1",
                applied_settings=applied_settings,
                applied_decisions=applied_decisions,
                preserved_decisions=preserved_decisions,
                recommended_decisions=recommended_decisions,
                warnings=warnings,
            ),
        )

    def _build_candidates(
        self,
        stage_name: str,
        prompt_context: PromptContext,
        intent: PromptIntentBundle,
    ) -> list[_PolicyCandidate]:
        dense_prompt = "large_chunk_count" in prompt_context.warnings or prompt_context.positive_chunk_count >= 18
        conflict_heavy = bool(intent.conflicts)
        portrait_like = intent.intent_band == "portrait" or intent.wants_portrait or intent.wants_face_detail
        full_body = intent.intent_band == "full_body" or intent.wants_full_body

        if stage_name == "txt2img":
            cfg = 6.0 if (dense_prompt or conflict_heavy) else (6.5 if portrait_like else 7.0)
            steps = 24 if (dense_prompt or conflict_heavy) else (28 if portrait_like else 22)
            sampler = "DPM++ 2M" if (portrait_like or dense_prompt or conflict_heavy) else "Euler a"
            scheduler = "Karras" if sampler == "DPM++ 2M" else ""
            return self._base_generation_candidates(cfg, steps, sampler, scheduler)

        if stage_name == "img2img":
            cfg = 5.5 if (dense_prompt or conflict_heavy) else 6.0
            steps = 20 if portrait_like else 18
            denoise = 0.2 if (dense_prompt or conflict_heavy) else (0.22 if portrait_like else 0.28)
            return [
                *_generation_candidates(cfg, steps, "DPM++ 2M", "Karras"),
                _PolicyCandidate(
                    key="denoising_strength",
                    value=denoise,
                    rationale="img2img auto-safe fill uses conservative denoise to reduce drift on prompt-led refinements.",
                ),
            ]

        if stage_name == "adetailer":
            confidence = 0.28 if portrait_like else (0.38 if full_body else 0.32)
            padding = 40 if portrait_like else 24
            steps = 12 if portrait_like else 10
            cfg = 4.5 if portrait_like else 4.0
            denoise = 0.18 if portrait_like else 0.16
            return [
                _PolicyCandidate(
                    key="enable_face_pass",
                    value=True,
                    rationale="Portrait or face-detail prompts benefit from a face pass when the key is unset.",
                ),
                _PolicyCandidate(
                    key="adetailer_confidence",
                    value=confidence,
                    rationale="ADetailer confidence auto-fill follows prompt distance and face-detail signals.",
                ),
                _PolicyCandidate(
                    key="adetailer_padding",
                    value=padding,
                    rationale="ADetailer padding auto-fill increases room around portrait faces without overriding explicit values.",
                ),
                _PolicyCandidate(
                    key="adetailer_steps",
                    value=steps,
                    rationale="ADetailer steps auto-fill keeps the pass short and identity-safe by default.",
                ),
                _PolicyCandidate(
                    key="adetailer_cfg",
                    value=cfg,
                    rationale="ADetailer CFG auto-fill stays conservative to avoid face redesign drift.",
                ),
                _PolicyCandidate(
                    key="adetailer_denoise",
                    value=denoise,
                    rationale="ADetailer denoise auto-fill stays low for identity preservation.",
                ),
                _PolicyCandidate(
                    key="adetailer_sampler",
                    value="DPM++ 2M",
                    rationale="ADetailer sampler auto-fill defaults to a stable portrait-friendly sampler when unset.",
                ),
                _PolicyCandidate(
                    key="adetailer_scheduler",
                    value="inherit",
                    rationale="ADetailer scheduler auto-fill inherits the parent sampler schedule when unset.",
                ),
            ]

        if stage_name == "upscale":
            if str(prompt_context.stage or "") != "upscale":
                return []
            upscale_mode = "img2img"
            if portrait_like or dense_prompt or conflict_heavy:
                cfg = 5.0 if (dense_prompt or conflict_heavy) else 5.5
                steps = 18 if (dense_prompt or conflict_heavy) else 16
                denoise = 0.18 if portrait_like else 0.2
                return [
                    _PolicyCandidate(
                        key="sampler_name",
                        value="DPM++ 2M",
                        rationale="Upscale img2img auto-fill uses a stable sampler for texture recovery.",
                    ),
                    _PolicyCandidate(
                        key="scheduler",
                        value="Karras",
                        rationale="Upscale img2img auto-fill uses Karras scheduling for conservative refinement.",
                    ),
                    _PolicyCandidate(
                        key="steps",
                        value=steps,
                        rationale="Upscale img2img step auto-fill limits texture work to a conservative range.",
                    ),
                    _PolicyCandidate(
                        key="cfg_scale",
                        value=cfg,
                        rationale="Upscale img2img CFG auto-fill avoids over-asserting dense or conflicting prompts.",
                    ),
                    _PolicyCandidate(
                        key="denoising_strength",
                        value=denoise,
                        rationale="Upscale img2img denoise auto-fill stays conservative for anatomy and identity stability.",
                    ),
                ]
            return []

        return []

    @staticmethod
    def _build_warnings(prompt_context: PromptContext, intent: PromptIntentBundle) -> list[str]:
        warnings: list[str] = []
        if "large_chunk_count" in prompt_context.warnings:
            warnings.append("stage_policy_dense_prompt")
        if intent.conflicts:
            warnings.append("stage_policy_prompt_conflicts_present")
        return warnings

    def _source_state(self, source_config: dict[str, Any], key: str) -> str:
        if key not in source_config:
            return "missing"
        value = source_config.get(key)
        if value is None:
            return "missing"
        if isinstance(value, str):
            stripped = value.strip()
            if not stripped:
                return "missing"
            if stripped.lower() in self._AUTO_SENTINELS:
                return "auto"
        return "explicit"

    @staticmethod
    def _base_generation_candidates(
        cfg: float,
        steps: int,
        sampler: str,
        scheduler: str,
    ) -> list[_PolicyCandidate]:
        return _generation_candidates(cfg, steps, sampler, scheduler)


def _generation_candidates(
    cfg: float,
    steps: int,
    sampler: str,
    scheduler: str,
) -> list[_PolicyCandidate]:
    candidates = [
        _PolicyCandidate(
            key="cfg_scale",
            value=cfg,
            rationale="Prompt-aware CFG auto-fill stays conservative when prompts are dense or portrait-focused.",
        ),
        _PolicyCandidate(
            key="steps",
            value=steps,
            rationale="Prompt-aware step auto-fill uses a bounded range based on prompt density and intent.",
        ),
        _PolicyCandidate(
            key="sampler_name",
            value=sampler,
            rationale="Prompt-aware sampler auto-fill chooses a safe default when the key is missing or AUTO.",
        ),
    ]
    if scheduler:
        candidates.append(
            _PolicyCandidate(
                key="scheduler",
                value=scheduler,
                rationale="Prompt-aware scheduler auto-fill only applies when the user did not choose a scheduler explicitly.",
            )
        )
    return candidates