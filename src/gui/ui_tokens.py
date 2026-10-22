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
    # PR-GUI-400 interactive roles. Gold is reserved for the primary action, selection/active hints and focus.
    surface_hover: str = design_system.Colors.SURFACE_HOVER
    surface_selected: str = design_system.Colors.SURFACE_SELECTED
    text_on_accent: str = design_system.Colors.TEXT_ON_ACCENT
    focus_ring: str = design_system.Colors.FOCUS_RING
    focus_ring_on_accent: str = design_system.Colors.FOCUS_RING_ON_FILL
    action_danger: str = design_system.Colors.DANGER_BG
    text_on_danger: str = design_system.Colors.DANGER_FG


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


NOTICE_KINDS = design_system.NOTICE_KINDS


@dataclass(frozen=True)
class NoticeRole:
    """One inline-notice kind. ``label`` is the word that carries the meaning; color only reinforces it."""

    kind: str
    label: str
    a11y_role: str  # semantic role ("alert" or "status") for tests and a future UI Automation bridge; Tk announces nothing
    foreground: str  # message text
    label_foreground: str  # the bold role word
    background: str  # tint behind the notice
    accent: str  # the edge bar


@dataclass(frozen=True)
class NoticeTokens:
    neutral: NoticeRole = NoticeRole(
        "neutral",
        "Note",
        "status",
        design_system.Colors.TEXT_PRIMARY,
        design_system.Colors.TEXT_MUTED,
        design_system.Colors.ELEVATED_SURFACE,
        "#8A8A8A",
    )
    info: NoticeRole = NoticeRole(
        "info",
        "Info",
        "status",
        design_system.Colors.TEXT_PRIMARY,
        "#7DB4F0",
        "#16222E",
        ColorTokens.status_info,
    )
    success: NoticeRole = NoticeRole(
        "success",
        "Success",
        "status",
        design_system.Colors.TEXT_PRIMARY,
        "#7FDB4F",
        "#17261A",
        ColorTokens.status_success,
    )
    warning: NoticeRole = NoticeRole(
        "warning",
        "Warning",
        "alert",
        design_system.Colors.TEXT_PRIMARY,
        "#F0B964",
        "#2B2416",
        ColorTokens.status_warning,
    )
    error: NoticeRole = NoticeRole(
        "error",
        "Error",
        "alert",
        design_system.Colors.TEXT_PRIMARY,
        "#FF7875",
        "#2E1A1B",
        ColorTokens.status_error,
    )

    def role(self, kind: str) -> NoticeRole:
        """The role for ``kind``; an unknown kind is neutral rather than an error."""

        return getattr(self, kind, self.neutral) if kind in NOTICE_KINDS else self.neutral


@dataclass(frozen=True)
class UITokens:
    colors: ColorTokens = ColorTokens()
    spacing: SpacingTokens = SpacingTokens()
    typography: TypeTokens = TypeTokens()
    motion: MotionTokens = MotionTokens()
    notices: NoticeTokens = NoticeTokens()


TOKENS = UITokens()


__all__ = [
    "ColorTokens",
    "SpacingTokens",
    "TypeTokens",
    "MotionTokens",
    "NOTICE_KINDS",
    "NoticeRole",
    "NoticeTokens",
    "UITokens",
    "TOKENS",
]
