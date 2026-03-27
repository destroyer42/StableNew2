from __future__ import annotations

"""Keep a unique basename to avoid pytest import-file collisions across suites."""

from src.prompting.contracts import PromptContext, PromptSourceContext
from src.prompting.prompt_intent_analyzer import PromptIntentAnalyzer


def _context(tags: list[str] | None = None) -> PromptContext:
    return PromptContext(
        stage="txt2img",
        pipeline_name="txt2img",
        positive_chunk_count=4,
        negative_chunk_count=2,
        positive_bucket_counts={"subject": 1, "style_medium": 1},
        negative_bucket_counts={"style_blockers": 1},
        loras=[{"name": "detail", "weight": 0.6}],
        embeddings=[{"name": "face_refiner", "weight": 1.0}],
        source=PromptSourceContext(prompt_source="pack", tags=tags or []),
        warnings=[],
    )


def test_prompt_intent_analyzer_builds_people_and_sensitivity_signals() -> None:
    analyzer = PromptIntentAnalyzer()

    bundle = analyzer.infer(
        positive="full body portrait of a naked woman, natural skin texture, looking directly into camera",
        negative="watermark, blurry",
        prompt_context=_context(tags=["nsfw"]),
    )

    assert bundle.intent_band == "portrait"
    assert bundle.shot_type == "full_body"
    assert bundle.requested_pose == "frontal"
    assert bundle.has_people_tokens is True
    assert bundle.wants_face_detail is True
    assert bundle.sensitive is True
    assert "tagged_sensitive" in bundle.sensitivity_reasons
    assert "naked" in bundle.sensitivity_reasons
    assert "prompt_contains_full_body_and_portrait_tokens" in bundle.conflicts


def test_prompt_intent_analyzer_detects_style_and_lora_conflicts() -> None:
    analyzer = PromptIntentAnalyzer()

    bundle = analyzer.infer(
        positive="anime woman, <lora:detail:0.6>, <lora:detail:0.8>",
        negative="anime, watermark",
        prompt_context=_context(),
    )

    assert bundle.style_mode == "stylized"
    assert bundle.has_lora_tokens is True
    assert "positive_negative_style_conflict" in bundle.conflicts
    assert "duplicate_lora_name_with_different_weights" in bundle.conflicts
