from src.pipeline.resolution_layer import UnifiedPromptResolver


def test_prompt_merges_gui_pack_and_prepend() -> None:
    resolver = UnifiedPromptResolver(max_preview_length=200)
    resolved = resolver.resolve(
        gui_prompt="epic sunrise",
        pack_prompt="gleaming towers",
        prepend_text="wide ",
        apply_global_negative=False,
    )
    assert resolved.positive == "wide epic sunrise gleaming towers"
    assert resolved.positive_preview.startswith("wide epic")
    assert resolved.global_negative_applied is False


def test_negative_builds_with_global_and_pack_terms() -> None:
    resolver = UnifiedPromptResolver(max_preview_length=200)
    resolved = resolver.resolve(
        gui_prompt="scene",
        negative_override="bad lighting",
        pack_negative="pack noise",
        global_negative="global hush",
        apply_global_negative=True,
    )
    assert "global hush" in resolved.negative
    assert "pack noise" in resolved.negative
    assert resolved.global_negative_applied is True


def test_preview_truncates_when_limit_reached() -> None:
    resolver = UnifiedPromptResolver(max_preview_length=10)
    long_prompt = "a" * 100
    resolved = resolver.resolve(gui_prompt=long_prompt, apply_global_negative=False)
    assert len(resolved.positive_preview) <= 13
