"""Design tokens and primitive helpers for the StableNew V2 GUI."""

from __future__ import annotations

import tkinter as tk
from collections.abc import Callable
from dataclasses import dataclass
from tkinter import ttk

Color = str


@dataclass(frozen=True)
class Spacing:
    NONE: int = 0
    XS: int = 2
    SM: int = 4
    MD: int = 8
    LG: int = 12
    XL: int = 16


@dataclass(frozen=True)
class Radii:
    SM: int = 4
    MD: int = 8
    LG: int = 12


@dataclass(frozen=True)
class Typography:
    FAMILY: str = "Segoe UI"
    XS: int = 9
    SM: int = 10
    MD: int = 11
    LG: int = 12
    XL: int = 14
    BOLD: str = "bold"
    NORMAL: str = "normal"


@dataclass(frozen=True)
class Colors:
    PRIMARY_BG: Color = "#121212"
    ELEVATED_SURFACE: Color = "#1E1E1E"
    CARD_BG: Color = "#1E1E1E"
    BORDER: Color = "#2D2D2D"
    PRIMARY_ACCENT: Color = "#FFC805"
    PRIMARY_ACCENT_HOVER: Color = "#FFD94D"
    TEXT_PRIMARY: Color = "#FFFFFF"
    TEXT_MUTED: Color = "#CCCCCC"
    TEXT_DISABLED: Color = "#777777"
    DANGER_BG: Color = "#FF4D4F"
    DANGER_FG: Color = "#FFFFFF"
    SEPARATOR: Color = "#2A2A2A"


PRIMARY_BUTTON = "Primary.TButton"
SECONDARY_BUTTON = "Secondary.TButton"
GHOST_BUTTON = "Ghost.TButton"
DANGER_BUTTON = "Danger.TButton"
CARD_FRAME = "Card.TFrame"
STAGE_CARD_FRAME = "StageCard.TFrame"
HEADING_LABEL = "Heading.TLabel"
SUBHEADING_LABEL = "Subheading.TLabel"
BODY_LABEL = "Body.TLabel"
MUTED_LABEL = "Muted.TLabel"
SECTION_FRAME = "Section.TFrame"


def _font(size: int, weight: str = Typography.NORMAL) -> tuple[str, int, str]:
    return (Typography.FAMILY, size, weight)


def apply_card_styles(style: ttk.Style) -> None:
    style.configure(
        CARD_FRAME,
        background=Colors.CARD_BG,
        borderwidth=1,
        relief="solid",
        bordercolor=Colors.BORDER,
        padding=(Spacing.MD, Spacing.MD),
    )
    style.configure(
        STAGE_CARD_FRAME,
        background=Colors.CARD_BG,
        borderwidth=0,
        relief="flat",
        padding=(Spacing.MD, Spacing.MD),
    )
    style.configure(
        SECTION_FRAME,
        background=Colors.ELEVATED_SURFACE,
        borderwidth=0,
    )


def apply_label_styles(style: ttk.Style) -> None:
    style.configure(
        HEADING_LABEL,
        background=Colors.PRIMARY_BG,
        foreground=Colors.PRIMARY_ACCENT,
        font=_font(Typography.LG, Typography.BOLD),
    )
    style.configure(
        SUBHEADING_LABEL,
        background=Colors.PRIMARY_BG,
        foreground=Colors.TEXT_PRIMARY,
        font=_font(Typography.MD, Typography.BOLD),
    )
    style.configure(
        BODY_LABEL,
        background=Colors.PRIMARY_BG,
        foreground=Colors.TEXT_PRIMARY,
        font=_font(Typography.SM),
    )
    style.configure(
        MUTED_LABEL,
        background=Colors.PRIMARY_BG,
        foreground=Colors.TEXT_MUTED,
        font=_font(Typography.SM),
    )


def apply_button_styles(style: ttk.Style) -> None:
    style.configure(
        PRIMARY_BUTTON,
        background=Colors.PRIMARY_ACCENT,
        foreground="#000000",
        borderwidth=0,
        focusthickness=1,
        focustcolor=Colors.PRIMARY_ACCENT_HOVER,
        padding=(Spacing.MD, Spacing.SM),
    )
    style.map(
        PRIMARY_BUTTON,
        background=[("active", Colors.PRIMARY_ACCENT_HOVER), ("disabled", Colors.BORDER)],
        foreground=[("disabled", Colors.TEXT_DISABLED)],
    )

    style.configure(
        SECONDARY_BUTTON,
        background=Colors.BORDER,
        foreground=Colors.TEXT_PRIMARY,
        borderwidth=0,
        padding=(Spacing.MD, Spacing.SM),
    )
    style.map(
        SECONDARY_BUTTON,
        background=[("active", Colors.ELEVATED_SURFACE), ("disabled", Colors.BORDER)],
        foreground=[("disabled", Colors.TEXT_DISABLED)],
    )

    style.configure(
        GHOST_BUTTON,
        background=Colors.PRIMARY_BG,
        foreground=Colors.PRIMARY_ACCENT,
        borderwidth=1,
        relief="groove",
        padding=(Spacing.SM, Spacing.SM),
    )
    style.map(
        GHOST_BUTTON,
        background=[("active", Colors.ELEVATED_SURFACE)],
    )

    style.configure(
        DANGER_BUTTON,
        background=Colors.DANGER_BG,
        foreground=Colors.DANGER_FG,
        borderwidth=0,
        padding=(Spacing.MD, Spacing.SM),
    )


def apply_design_system(style: ttk.Style) -> None:
    apply_card_styles(style)
    apply_label_styles(style)
    apply_button_styles(style)


def create_primary_button(
    parent: tk.Misc, text: str, command: Callable[[], None] | None = None, **kwargs: object
) -> ttk.Button:
    return ttk.Button(parent, text=text, command=command, style=PRIMARY_BUTTON, **kwargs)


def create_secondary_button(
    parent: tk.Misc, text: str, command: Callable[[], None] | None = None, **kwargs: object
) -> ttk.Button:
    return ttk.Button(parent, text=text, command=command, style=SECONDARY_BUTTON, **kwargs)


def create_stage_card_frame(parent: tk.Misc, **kwargs: object) -> ttk.Frame:
    return ttk.Frame(parent, style=STAGE_CARD_FRAME, **kwargs)
