"""Design tokens and primitive helpers for the StableNew V2 GUI."""

from __future__ import annotations

import tkinter as tk
from collections.abc import Callable
from dataclasses import dataclass
from tkinter import ttk
from typing import NamedTuple

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
    # PR-GUI-400: white on the former #FF4D4F fill was 3.3:1; this deeper red keeps the identity at 4.6:1.
    DANGER_BG: Color = "#D9363E"
    DANGER_BG_HOVER: Color = "#E5484F"
    DANGER_FG: Color = "#FFFFFF"
    SEPARATOR: Color = "#2A2A2A"
    # PR-GUI-400: interactive-state surfaces and the focus edge (gold on dark surfaces, white on gold/red fills).
    SURFACE_HOVER: Color = "#262626"
    SURFACE_SELECTED: Color = "#2B2B2B"
    SECONDARY_HOVER: Color = "#3A3A3A"
    TEXT_ON_ACCENT: Color = "#000000"
    FOCUS_RING: Color = PRIMARY_ACCENT
    FOCUS_RING_ON_FILL: Color = "#FFFFFF"
    ACCENT_DISABLED_EDGE: Color = "#8C7413"


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
# The semantic labels sit on cards/sections/panels (ELEVATED_SURFACE). These variants are for the few widgets that
# sit directly on the page-dark background; they inherit font and color from the card-surface style.
PAGE_BODY_LABEL = "Page.Body.TLabel"
PAGE_MUTED_LABEL = "Page.Muted.TLabel"
PAGE_RADIOBUTTON = "Page.TRadiobutton"

NOTICE_KINDS = ("neutral", "info", "success", "warning", "error")


class NoticeStyleNames(NamedTuple):
    frame: str
    message: str
    prefix: str
    bar: str


def notice_style_names(kind: str) -> NoticeStyleNames:
    """ttk style names of one inline-notice kind (an unknown kind falls back to ``neutral``)."""

    name = (kind if kind in NOTICE_KINDS else "neutral").capitalize()
    return NoticeStyleNames(
        frame=f"Notice.{name}.TFrame",
        message=f"Notice.{name}.TLabel",
        prefix=f"NoticePrefix.{name}.TLabel",
        bar=f"NoticeBar.{name}.TFrame",
    )


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
    # PR-GUI-400: these roles live on cards, sections and panels (all ELEVATED_SURFACE); on the page-dark
    # background they drew a darker rectangle behind every label. Use plain TLabel directly on the page.
    style.configure(
        HEADING_LABEL,
        background=Colors.CARD_BG,
        foreground=Colors.PRIMARY_ACCENT,
        font=_font(Typography.LG, Typography.BOLD),
    )
    style.configure(
        SUBHEADING_LABEL,
        background=Colors.CARD_BG,
        foreground=Colors.TEXT_PRIMARY,
        font=_font(Typography.MD, Typography.BOLD),
    )
    style.configure(
        BODY_LABEL,
        background=Colors.CARD_BG,
        foreground=Colors.TEXT_PRIMARY,
        font=_font(Typography.SM),
    )
    style.configure(
        MUTED_LABEL,
        background=Colors.CARD_BG,
        foreground=Colors.TEXT_MUTED,
        font=_font(Typography.SM),
    )
    style.configure(PAGE_BODY_LABEL, background=Colors.PRIMARY_BG)
    style.configure(PAGE_MUTED_LABEL, background=Colors.PRIMARY_BG)


def _no_emboss_when_disabled(style: ttk.Style, name: str) -> None:
    """Drop Tk's doubled shadow on disabled text; the disabled foreground carries the state instead."""

    style.map(name, embossed=[("disabled", 0)])


def _action_button(
    style: ttk.Style,
    name: str,
    *,
    background: str,
    foreground: str,
    hover: str,
    disabled_background: str,
    edge: str,
    disabled_edge: str,
    focus_edge: str,
    focus_dots: str | None = None,
) -> None:
    """One action role. The 1px edge exists so keyboard focus can show on a filled button; the padding gives it back
    (2 * edge + 2 * padding equals the previous 2 * (MD, SM)), so button sizes and min-width layouts are unchanged."""

    style.configure(
        name,
        background=background,
        foreground=foreground,
        bordercolor=edge,
        lightcolor=background,
        darkcolor=background,
        borderwidth=1,
        focusthickness=1,
        focuscolor=focus_dots or focus_edge,
        padding=(Spacing.MD - 1, Spacing.SM - 1),
    )
    style.map(
        name,
        background=[("disabled", disabled_background), ("pressed", hover), ("active", hover)],
        foreground=[("disabled", Colors.TEXT_DISABLED)],
        bordercolor=[("disabled", disabled_edge), ("focus", focus_edge)],
        lightcolor=[("disabled", disabled_background), ("pressed", hover), ("active", hover)],
        darkcolor=[("disabled", disabled_background), ("pressed", hover), ("active", hover)],
    )
    _no_emboss_when_disabled(style, name)


def apply_button_styles(style: ttk.Style) -> None:
    _action_button(
        style,
        PRIMARY_BUTTON,
        background=Colors.PRIMARY_ACCENT,
        foreground=Colors.TEXT_ON_ACCENT,
        hover=Colors.PRIMARY_ACCENT_HOVER,
        disabled_background=Colors.BORDER,
        edge=Colors.PRIMARY_ACCENT,
        disabled_edge=Colors.ACCENT_DISABLED_EDGE,  # a disabled CTA still reads as the primary action
        focus_edge=Colors.FOCUS_RING_ON_FILL,
        focus_dots=Colors.TEXT_ON_ACCENT,  # the inner focus line must contrast with the gold fill it sits on
    )
    _action_button(
        style,
        SECONDARY_BUTTON,
        background=Colors.BORDER,
        foreground=Colors.TEXT_PRIMARY,
        hover=Colors.SECONDARY_HOVER,
        disabled_background=Colors.ELEVATED_SURFACE,
        edge=Colors.BORDER,
        disabled_edge=Colors.BORDER,
        focus_edge=Colors.FOCUS_RING,
    )
    _action_button(
        style,
        DANGER_BUTTON,
        background=Colors.DANGER_BG,
        foreground=Colors.DANGER_FG,
        hover=Colors.DANGER_BG_HOVER,
        disabled_background=Colors.BORDER,
        edge=Colors.DANGER_BG,
        disabled_edge=Colors.BORDER,
        focus_edge=Colors.FOCUS_RING_ON_FILL,
    )

    style.configure(
        GHOST_BUTTON,
        background=Colors.PRIMARY_BG,
        foreground=Colors.PRIMARY_ACCENT,
        bordercolor=Colors.BORDER,
        borderwidth=1,
        focusthickness=1,
        focuscolor=Colors.FOCUS_RING,
        relief="groove",
        padding=(Spacing.SM, Spacing.SM),
    )
    style.map(
        GHOST_BUTTON,
        background=[("disabled", Colors.PRIMARY_BG), ("active", Colors.ELEVATED_SURFACE)],
        foreground=[("disabled", Colors.TEXT_DISABLED)],
        bordercolor=[("disabled", Colors.BORDER), ("focus", Colors.FOCUS_RING)],
    )
    _no_emboss_when_disabled(style, GHOST_BUTTON)


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
