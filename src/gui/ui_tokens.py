"""Toolkit-agnostic UI design tokens for StableNew."""

from __future__ import annotations

from dataclasses import dataclass

from src.gui import design_system_v2 as design_system


@dataclass(frozen=True)
class ColorTokens:
    surface_primary: str = design_system.Colors.PRIMARY_BG
    surface_secondary: str = design_system.Colors.ELEVATED_SURFACE
    surface_tertiary: str = "#161616"
    text_primary: str = design_system.Colors.TEXT_PRIMARY
    text_muted: str = design_system.Colors.TEXT_MUTED
    text_disabled: str = design_system.Colors.TEXT_DISABLED
    border_subtle: str = design_system.Colors.BORDER
    accent_primary: str = design_system.Colors.PRIMARY_ACCENT
    accent_primary_hover: str = design_system.Colors.PRIMARY_ACCENT_HOVER
    status_success: str = "#52C41A"
    status_warning: str = "#d9a04a"
    status_error: str = "#FF4D4F"
    status_info: str = "#4a90d9"


@dataclass(frozen=True)
class SpacingTokens:
    xs: int = 4
    sm: int = design_system.Spacing.SM
    md: int = design_system.Spacing.MD
    lg: int = design_system.Spacing.LG
    xl: int = 24


@dataclass(frozen=True)
class TypeTokens:
    family: str = design_system.Typography.FAMILY
    size_sm: int = design_system.Typography.SM
    size_md: int = design_system.Typography.MD
    size_lg: int = design_system.Typography.LG
    weight_regular: str = "normal"
    weight_bold: str = "bold"


@dataclass(frozen=True)
class MotionTokens:
    fast_ms: int = 120
    base_ms: int = 220
    slow_ms: int = 320


@dataclass(frozen=True)
class UITokens:
    colors: ColorTokens = ColorTokens()
    spacing: SpacingTokens = SpacingTokens()
    typography: TypeTokens = TypeTokens()
    motion: MotionTokens = MotionTokens()


TOKENS = UITokens()


__all__ = [
    "ColorTokens",
    "SpacingTokens",
    "TypeTokens",
    "MotionTokens",
    "UITokens",
    "TOKENS",
]
