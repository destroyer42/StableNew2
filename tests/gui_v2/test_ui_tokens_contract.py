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


def test_ui_tokens_expose_interactive_and_notice_roles() -> None:
    from src.gui.ui_tokens import NOTICE_KINDS, NoticeRole

    for field in (
        "surface_hover",
        "surface_selected",
        "focus_ring",
        "text_on_accent",
        "action_danger",
    ):
        assert getattr(TOKENS.colors, field).startswith("#")
    assert tuple(TOKENS.notices.role(kind).kind for kind in NOTICE_KINDS) == NOTICE_KINDS
    assert all(isinstance(TOKENS.notices.role(kind), NoticeRole) for kind in NOTICE_KINDS)
    # Wave 1 keeps the existing metrics.
    assert (TOKENS.spacing.sm, TOKENS.spacing.md) == (4, 8)
