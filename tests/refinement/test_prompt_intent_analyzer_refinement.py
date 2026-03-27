from __future__ import annotations

"""Keep a unique basename to avoid pytest import-file collisions across suites."""

from src.refinement.prompt_intent_analyzer import PromptIntentAnalyzer


def test_prompt_intent_analyzer_reuses_prompt_signals() -> None:
    analyzer = PromptIntentAnalyzer()

    result = analyzer.infer(
        positive="full body portrait, profile, woman, detailed face, <lora:eyes:0.6>, <embedding:face_refiner>",
        negative="bad anatomy, watermark",
    )

    assert result["intent_band"] == "portrait"
    assert result["requested_pose"] == "profile"
    assert result["wants_full_body"] is True
    assert result["wants_face_detail"] is True
    assert result["has_people_tokens"] is True
    assert result["has_lora_tokens"] is True
    assert "prompt_contains_full_body_and_portrait_tokens" in result["conflicts"]
    assert result["positive_embedding_count"] == 1


def test_prompt_intent_analyzer_handles_non_people_prompt() -> None:
    analyzer = PromptIntentAnalyzer()

    result = analyzer.infer(
        positive="cinematic forest landscape, dramatic lighting",
        negative="text, watermark",
    )

    assert result["intent_band"] == "non_people"
    assert result["has_people_tokens"] is False
    assert result["requested_pose"] == "unknown"
