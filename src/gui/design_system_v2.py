"""Tk/ttk style registration and primitive helpers for the StableNew V2 GUI.

The raw palette, spacing, type and radii live in the toolkit-neutral ``src/gui_v2/design_values.py`` and are re-exported
here unchanged, so existing callers keep importing them from this module.
"""

from __future__ import annotations

import tkinter as tk
from collections.abc import Callable
from tkinter import ttk
from typing import NamedTuple

from src.gui_v2.design_values import NOTICE_KINDS, Color, Colors, Radii, Spacing, Typography

# The neutral values stay importable from here for existing callers; ``__all__`` marks them as intentional re-exports.
__all__ = ["NOTICE_KINDS", "Color", "Colors", "Radii", "Spacing", "Typography"]

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
