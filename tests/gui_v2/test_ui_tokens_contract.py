from __future__ import annotations

from src.gui.ui_tokens import TOKENS, ColorTokens, SpacingTokens, TypeTokens


def test_ui_tokens_shape_and_values() -> None:
    assert isinstance(TOKENS.colors, ColorTokens)
    assert isinstance(TOKENS.spacing, SpacingTokens)
    assert isinstance(TOKENS.typography, TypeTokens)
    assert TOKENS.colors.surface_primary
    assert TOKENS.colors.text_primary
    assert TOKENS.colors.accent_primary
    assert TOKENS.spacing.sm > 0
    assert TOKENS.spacing.md >= TOKENS.spacing.sm
    assert TOKENS.typography.family
