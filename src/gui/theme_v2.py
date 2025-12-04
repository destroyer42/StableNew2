"""StableNew V2 theme definitions and helpers."""

from __future__ import annotations

import tkinter as tk
from tkinter import ttk

from src.gui import design_system_v2 as design_system

BACKGROUND_DARK = design_system.Colors.PRIMARY_BG
BACKGROUND_ELEVATED = design_system.Colors.ELEVATED_SURFACE
TEXT_PRIMARY = design_system.Colors.TEXT_PRIMARY
TEXT_MUTED = design_system.Colors.TEXT_MUTED
TEXT_DISABLED = design_system.Colors.TEXT_DISABLED
BORDER_SUBTLE = design_system.Colors.BORDER
ACCENT_GOLD = design_system.Colors.PRIMARY_ACCENT
ACCENT_GOLD_HOVER = design_system.Colors.PRIMARY_ACCENT_HOVER
PADDING_SM = design_system.Spacing.SM
PADDING_MD = design_system.Spacing.MD
ASWF_BLACK = BACKGROUND_DARK
ASWF_DARK_GREY = BACKGROUND_ELEVATED
ASWF_MED_GREY = "#3A393D"
ASWF_LIGHT_GREY = "#4A4950"
ASWF_GOLD = ACCENT_GOLD
ASWF_ERROR_RED = "#FF4D4F"
ASWF_OK_GREEN = "#52C41A"

CARD_FRAME_STYLE = design_system.CARD_FRAME
SURFACE_FRAME_STYLE = design_system.SECTION_FRAME
BODY_LABEL_STYLE = design_system.BODY_LABEL
MUTED_LABEL_STYLE = design_system.MUTED_LABEL
HEADING_LABEL_STYLE = design_system.HEADING_LABEL
PRIMARY_BUTTON_STYLE = design_system.PRIMARY_BUTTON
SECONDARY_BUTTON_STYLE = design_system.SECONDARY_BUTTON
GHOST_BUTTON_STYLE = design_system.GHOST_BUTTON


def _configure_global_colors(root: tk.Tk | tk.Toplevel) -> None:
    try:
        root.configure(bg=BACKGROUND_DARK)
    except Exception:
        pass


def _configure_fonts(root: tk.Tk | tk.Toplevel) -> None:
    family = f"{{{design_system.Typography.FAMILY}}}"
    root.option_add("*Font", f"{family} {design_system.Typography.SM}")
    root.option_add("*TEntry.Font", f"{family} {design_system.Typography.SM}")
    root.option_add("*Text.Font", f"{family} {design_system.Typography.SM}")
    root.option_add("*Treeview.Font", f"{family} {design_system.Typography.SM}")
    root.option_add("*Heading.Font", f"{family} {design_system.Typography.LG} bold")


def _configure_entry_styles(style: ttk.Style) -> None:
    style.configure(
        "TEntry",
        fieldbackground=BACKGROUND_ELEVATED,
        foreground=design_system.Colors.TEXT_PRIMARY,
        borderwidth=1,
        relief="solid",
    )
    style.map("TEntry", fieldbackground=[("disabled", BACKGROUND_ELEVATED)])

    style.configure(
        "Dark.TCombobox",
        fieldbackground=BACKGROUND_ELEVATED,
        background=BACKGROUND_ELEVATED,
        foreground=design_system.Colors.TEXT_PRIMARY,
        bordercolor=BORDER_SUBTLE,
        arrowcolor=design_system.Colors.TEXT_PRIMARY,
    )
    style.map(
        "Dark.TCombobox",
        fieldbackground=[("readonly", BACKGROUND_ELEVATED)],
        background=[("readonly", BACKGROUND_ELEVATED)],
        foreground=[("disabled", TEXT_MUTED)],
    )
    style.configure(
        "Dark.TCombobox.Listbox",
        background=BACKGROUND_ELEVATED,
        foreground=design_system.Colors.TEXT_PRIMARY,
        selectbackground=design_system.Colors.PRIMARY_ACCENT,
        selectforeground=design_system.Colors.TEXT_PRIMARY,
    )

    style.configure(
        "Dark.TSpinbox",
        fieldbackground=BACKGROUND_ELEVATED,
        foreground=design_system.Colors.TEXT_PRIMARY,
        bordercolor=BORDER_SUBTLE,
    )
    style.map(
        "Dark.TSpinbox",
        fieldbackground=[("readonly", BACKGROUND_ELEVATED)],
    )

    style.configure(
        "Dark.TCheckbutton",
        background=BACKGROUND_ELEVATED,
        foreground=design_system.Colors.TEXT_PRIMARY,
        bordercolor=BORDER_SUBTLE,
    )
    style.map(
        "Dark.TCheckbutton",
        background=[("active", BACKGROUND_ELEVATED)],
        foreground=[("disabled", TEXT_MUTED)],
        indicatorcolor=[
            ("selected", ACCENT_GOLD),
            ("alternate", ACCENT_GOLD),
            ("!selected", TEXT_MUTED),
        ],
        indicatorbackground=[
            ("selected", BACKGROUND_ELEVATED),
            ("!selected", BACKGROUND_ELEVATED),
        ],
    )

    style.configure(
        "Dark.TLabel",
        background=BACKGROUND_ELEVATED,
        foreground=design_system.Colors.TEXT_PRIMARY,
    )

    style.configure(
        "Dark.Horizontal.TScale",
        troughcolor=BACKGROUND_ELEVATED,
        background=BACKGROUND_DARK,
        bordercolor=BORDER_SUBTLE,
    )
    style.configure(
        "Dark.Vertical.TScale",
        troughcolor=BACKGROUND_ELEVATED,
        background=BACKGROUND_DARK,
        bordercolor=BORDER_SUBTLE,
    )

    style.configure(
        "Dark.TButton",
        background=BACKGROUND_ELEVATED,
        foreground=design_system.Colors.TEXT_PRIMARY,
        bordercolor=BORDER_SUBTLE,
        focusthickness=1,
    )
    style.map(
        "Dark.TButton",
        background=[("active", BACKGROUND_DARK)],
        foreground=[("disabled", TEXT_MUTED)],
    )


def _configure_treeview_styles(style: ttk.Style) -> None:
    style.configure(
        "Treeview",
        background=BACKGROUND_ELEVATED,
        fieldbackground=BACKGROUND_ELEVATED,
        foreground=design_system.Colors.TEXT_PRIMARY,
        borderwidth=0,
    )
    style.configure("Treeview.Heading", background=BACKGROUND_DARK, foreground=design_system.Colors.TEXT_PRIMARY)


def _configure_statusbar_styles(style: ttk.Style) -> None:
    style.configure("StatusBar.TFrame", background=BACKGROUND_ELEVATED, borderwidth=1, relief="solid", bordercolor=BORDER_SUBTLE)
    style.configure("StatusBar.TLabel", background=BACKGROUND_ELEVATED, foreground=design_system.Colors.TEXT_MUTED)
    style.configure("Status.TLabel", background=BACKGROUND_ELEVATED, foreground=design_system.Colors.TEXT_MUTED)
    style.configure("StatusStrong.TLabel", background=BACKGROUND_ELEVATED, foreground=ACCENT_GOLD, font=(design_system.Typography.FAMILY, design_system.Typography.MD, "bold"))


def _configure_progress_styles(style: ttk.Style) -> None:
    style.configure("Horizontal.TProgressbar", troughcolor=BACKGROUND_ELEVATED, background=design_system.Colors.PRIMARY_ACCENT)


def init_theme(root: tk.Tk | tk.Toplevel) -> ttk.Style:
    style = ttk.Style(master=root)
    for candidate in ("alt", "clam"):
        try:
            style.theme_use(candidate)
            break
        except tk.TclError:
            continue
    _configure_global_colors(root)
    _configure_fonts(root)
    design_system.apply_design_system(style)
    style.configure("Panel.TFrame", background=BACKGROUND_ELEVATED)
    _configure_entry_styles(style)
    _configure_treeview_styles(style)
    _configure_statusbar_styles(style)
    _configure_progress_styles(style)
    return style


def apply_theme(root: tk.Tk | tk.Toplevel) -> ttk.Style:
    return init_theme(root)


class Theme:
    def apply_ttk_styles(self, root_or_style: tk.Tk | ttk.Style) -> None:
        try:
            style = root_or_style
            if not isinstance(style, ttk.Style):
                style = ttk.Style(master=root_or_style)
            design_system.apply_design_system(style)
        except Exception:
            pass

    def apply_root(self, root: tk.Tk) -> None:
        try:
            init_theme(root)
        except Exception:
            pass


__all__ = [
    "init_theme",
    "apply_theme",
    "Theme",
    "BACKGROUND_DARK",
    "BACKGROUND_ELEVATED",
    "BORDER_SUBTLE",
    "TEXT_PRIMARY",
    "TEXT_MUTED",
    "TEXT_DISABLED",
    "ACCENT_GOLD",
    "ACCENT_GOLD_HOVER",
    "CARD_FRAME_STYLE",
    "SURFACE_FRAME_STYLE",
    "BODY_LABEL_STYLE",
    "MUTED_LABEL_STYLE",
    "HEADING_LABEL_STYLE",
    "PRIMARY_BUTTON_STYLE",
    "SECONDARY_BUTTON_STYLE",
    "GHOST_BUTTON_STYLE",
    "STATUS_LABEL_STYLE",
    "STATUS_STRONG_LABEL_STYLE",
    "PADDING_MD",
    "PADDING_SM",
    "ASWF_BLACK",
    "ASWF_DARK_GREY",
    "ASWF_MED_GREY",
    "ASWF_LIGHT_GREY",
    "ASWF_GOLD",
    "ASWF_ERROR_RED",
    "ASWF_OK_GREEN",
]
STATUS_LABEL_STYLE = "Status.TLabel"
STATUS_STRONG_LABEL_STYLE = "StatusStrong.TLabel"
