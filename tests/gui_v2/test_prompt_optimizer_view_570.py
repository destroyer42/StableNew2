"""Authority and privacy of read-only optimizer comparisons."""

from types import SimpleNamespace

import pytest

from src.gui_v2.prompt_optimizer_view import compiled_prompt_lines, editor_comparison_lines


@pytest.mark.parametrize(
    "settings, status",
    [
        ({}, "Not confirmed"),
        ({"enabled": False}, "Disabled by user"),
        ({"opt_out_pipeline_names": ["txt2img"]}, "Not applicable to stage"),
    ],
)
def test_editor_illustration_labels_settings_and_authority(settings, status):
    text = "\n".join(
        editor_comparison_lines("masterpiece, beautiful woman, masterpiece", "blurry", settings)
    )
    assert status in text
    assert "EDITOR ILLUSTRATION" in text
    assert "Before (Positive authored text)" in text and "After (Positive illustration)" in text
    assert "Execution-time projection unavailable" in text
    if settings.get("enabled") is False or settings.get("opt_out_pipeline_names"):
        assert "Positive: Unchanged" in text
    else:
        assert "Duplicate chunks removed (Positive): 1" in text
        assert "Removed: masterpiece" in text


def test_hidden_mode_excludes_all_prompt_diagnostics_before_optimization(monkeypatch):
    monkeypatch.setattr(
        "src.gui_v2.prompt_optimizer_view.PromptOptimizerService",
        lambda *_: pytest.fail("hidden text must not be optimized"),
    )
    text = "\n".join(
        editor_comparison_lines(
            "secret <lora:identity:0.7>", "secret-negative", {}, visible=False, diagnostics=True
        )
    )
    for hidden in ("secret", "identity", "secret-negative", "Removed:", "bucket diagnostics:"):
        assert hidden not in text


def test_editor_reports_lora_movement_and_buckets_only_when_requested():
    args = (
        "<lora:detail:0.70>, beautiful woman, masterpiece",
        "",
        {"preserve_lora_relative_order": False, "preserve_unknown_order": False},
    )
    text = "\n".join(editor_comparison_lines(*args))
    assert "1 → 1; 1 changed parsed chunk position" in text
    assert "bucket diagnostics:" not in text
    assert "bucket diagnostics:" in "\n".join(editor_comparison_lines(*args, diagnostics=True))


def test_exact_profile_disables_editor_transform_without_readding_tokens():
    target = SimpleNamespace(
        optimizer_available=False, optimizer_note="Exact profile disables optimization."
    )
    text = "\n".join(editor_comparison_lines("secret <lora:dropped:1>", "", {}, target=target))
    assert "Unavailable for model" in text
    assert "After (Positive" not in text and "dropped" not in text


def test_compiled_evidence_uses_frozen_inputs_and_profile_then_redacts():
    from src.image_backends.forge_klein_profile import KLEIN_PROFILE_V1

    job = SimpleNamespace(
        config={"prompt_optimizer": {"enabled": False}},
        backend_options={
            "image": {"backend_id": "forge", "model_profile": KLEIN_PROFILE_V1.reference()}
        },
        positive_prompt="compiled-secret <lora:identity:0.7>",
        negative_prompt="negative-secret",
    )
    text = "\n".join(compiled_prompt_lines([job], visible=True))
    assert "Compiled Positive:" in text and "compiled-secret" in text
    assert "Unavailable for model (frozen exact profile)" in text
    assert "observed outbound prompt requires execution evidence" in text
    hidden = "\n".join(compiled_prompt_lines([job], visible=False))
    assert "secret" not in hidden and "identity" not in hidden


def test_empty_and_invalid_inputs_do_not_fabricate_backend_prompts():
    assert "No compiled Preview" in "\n".join(compiled_prompt_lines([], visible=True))
    text = "\n".join(editor_comparison_lines("", "", {}))
    assert "Positive: Unchanged" in text and "Negative: Unchanged" in text
    invalid = "\n".join(
        editor_comparison_lines("sensitive", "", {"large_chunk_warning_threshold": 0})
    )
    assert "invalid settings" in invalid and "sensitive" not in invalid
