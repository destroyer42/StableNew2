from __future__ import annotations

import tkinter as tk
from tkinter import ttk

# Palette
BACKGROUND_DARK = "#121212"
BACKGROUND_ELEVATED = "#1E1E1E"
BORDER_SUBTLE = "#2A2A2A"

TEXT_PRIMARY = "#FFFFFF"
TEXT_MUTED = "#CCCCCC"
TEXT_DISABLED = "#777777"

ACCENT_GOLD = "#FFC805"
ACCENT_GOLD_HOVER = "#FFD94D"

ERROR_RED = "#FF4D4F"
SUCCESS_GREEN = "#52C41A"
INFO_BLUE = "#40A9FF"

ASWF_BLACK = BACKGROUND_DARK
ASWF_DARK_GREY = BACKGROUND_ELEVATED
ASWF_MED_GREY = "#3A393D"
ASWF_LIGHT_GREY = "#4A4950"
ASWF_GOLD = ACCENT_GOLD
ASWF_ERROR_RED = ERROR_RED
ASWF_OK_GREEN = SUCCESS_GREEN

# Fonts
DEFAULT_FONT_FAMILY = "Segoe UI"
DEFAULT_FONT_SIZE = 10
HEADING_FONT_SIZE = 11
MONO_FONT_FAMILY = "Consolas"

# Padding and style constants for V2 panels
PADDING_XS = 2
PADDING_SM = 4
PADDING_MD = 8
PADDING_LG = 12
SURFACE_FRAME_STYLE = "Surface.TFrame"
STATUS_LABEL_STYLE = "Status.TLabel"
STATUS_STRONG_LABEL_STYLE = "StatusStrong.TLabel"


def apply_theme(root: tk.Tk) -> None:
    """Apply the StableNew V2 dark theme to the given Tk root."""
    style = ttk.Style(master=root)
    try:
        style.theme_use("alt")
    except tk.TclError:
        try:
            style.theme_use("clam")
        except tk.TclError:
            pass

    _configure_global_colors(root)
    _configure_fonts(root)
    _configure_panel_styles(style)
    _configure_button_styles(style)
    _configure_label_styles(style)
    _configure_entry_styles(style)
    _configure_treeview_styles(style)
    _configure_statusbar_styles(style)
    _configure_progress_styles(style)


def _configure_global_colors(root: tk.Tk) -> None:
    try:
        root.configure(bg=BACKGROUND_DARK)
    except Exception:
        pass


def _configure_fonts(root: tk.Tk) -> None:
    family = f"{{{DEFAULT_FONT_FAMILY}}}"
    root.option_add("*Font", f"{family} {DEFAULT_FONT_SIZE}")
    root.option_add("*TEntry.Font", f"{family} {DEFAULT_FONT_SIZE}")
    root.option_add("*Text.Font", f"{family} {DEFAULT_FONT_SIZE}")
    root.option_add("*Treeview.Font", f"{family} {DEFAULT_FONT_SIZE}")
    root.option_add("*TNotebook.Tab.Font", f"{family} {DEFAULT_FONT_SIZE}")
    root.option_add("*Heading.Font", f"{family} {HEADING_FONT_SIZE} bold")


def _configure_panel_styles(style: ttk.Style) -> None:
    style.configure(
        "Panel.TFrame",
        background=BACKGROUND_DARK,
        borderwidth=0,
    )
    style.configure(
        "Card.TFrame",
        background=BACKGROUND_ELEVATED,
        borderwidth=1,
        relief="solid",
        bordercolor=BORDER_SUBTLE,
    )


def _configure_button_styles(style: ttk.Style) -> None:
    style.configure(
        "Primary.TButton",
        background=ACCENT_GOLD,
        foreground="#000000",
        borderwidth=0,
        focusthickness=1,
        focustcolor=ACCENT_GOLD_HOVER,
        padding=(8, 4),
    )
    style.map(
        "Primary.TButton",
        background=[("active", ACCENT_GOLD_HOVER), ("disabled", BORDER_SUBTLE)],
        foreground=[("disabled", TEXT_DISABLED)],
    )

    style.configure(
        "Secondary.TButton",
        background=BORDER_SUBTLE,
        foreground=TEXT_PRIMARY,
        borderwidth=0,
        padding=(8, 4),
    )
    style.map(
        "Secondary.TButton",
        background=[("active", BACKGROUND_ELEVATED), ("disabled", BORDER_SUBTLE)],
        foreground=[("disabled", TEXT_DISABLED)],
    )


def _configure_label_styles(style: ttk.Style) -> None:
    style.configure(
        "TLabel",
        background=BACKGROUND_DARK,
        foreground=TEXT_PRIMARY,
    )
    style.configure(
        "Muted.TLabel",
        background=BACKGROUND_DARK,
        foreground=TEXT_MUTED,
    )
    style.configure(
        "Heading.TLabel",
        background=BACKGROUND_DARK,
        foreground=TEXT_PRIMARY,
        font=f"{{{DEFAULT_FONT_FAMILY}}} {HEADING_FONT_SIZE} bold",
    )


def _configure_entry_styles(style: ttk.Style) -> None:
    style.configure(
        "TEntry",
        fieldbackground=BACKGROUND_ELEVATED,
        foreground=TEXT_PRIMARY,
        borderwidth=1,
        relief="solid",
    )
    style.map(
        "TEntry",
        fieldbackground=[("disabled", BACKGROUND_ELEVATED), ("readonly", BACKGROUND_ELEVATED)],
        foreground=[("disabled", TEXT_DISABLED)],
    )


def _configure_treeview_styles(style: ttk.Style) -> None:
    style.configure(
        "Treeview",
        background=BACKGROUND_ELEVATED,
        fieldbackground=BACKGROUND_ELEVATED,
        foreground=TEXT_PRIMARY,
        borderwidth=0,
    )
    style.configure(
        "Treeview.Heading",
        background=BACKGROUND_DARK,
        foreground=TEXT_PRIMARY,
    )


def _configure_statusbar_styles(style: ttk.Style) -> None:
    style.configure(
        "StatusBar.TFrame",
        background=BACKGROUND_ELEVATED,
        borderwidth=1,
        relief="solid",
        bordercolor=BORDER_SUBTLE,
    )
    style.configure(
        "StatusBar.TLabel",
        background=BACKGROUND_ELEVATED,
        foreground=TEXT_MUTED,
    )


def _configure_progress_styles(style: ttk.Style) -> None:
    style.configure(
        "Horizontal.TProgressbar",
        troughcolor=BACKGROUND_ELEVATED,
        background=ACCENT_GOLD,
        bordercolor=BORDER_SUBTLE,
        lightcolor=ACCENT_GOLD,
        darkcolor=ACCENT_GOLD,
    )


class Theme:
    """
    Minimal V2 Theme contract for GUI tests and runtime.
    """
    def apply_ttk_styles(self, root_or_style) -> None:
        """
        Apply ttk styles required by GUI V2 components and tests.
        Safe to call multiple times; must not raise.
        """
        try:
            style = root_or_style
            if not isinstance(style, ttk.Style):
                style = ttk.Style(master=root_or_style)
            # Ensure key styles exist for tests
            style.configure("Primary.TButton", background=ACCENT_GOLD, foreground=TEXT_PRIMARY)
            style.configure("Panel.TFrame", background=BACKGROUND_ELEVATED)
            style.configure("StatusBar.TFrame", background=BACKGROUND_DARK)
            style.configure("Surface.TFrame", background=BACKGROUND_ELEVATED)
            style.configure("Pipeline.TFrame", background=BACKGROUND_ELEVATED)
            style.configure("PipelineHeading.TLabel", foreground=ACCENT_GOLD, font=(DEFAULT_FONT_FAMILY, HEADING_FONT_SIZE, "bold"))
            style.configure("StatusStrong.TLabel", foreground=ACCENT_GOLD, font=(DEFAULT_FONT_FAMILY, HEADING_FONT_SIZE, "bold"))
            style.configure("Status.TLabel", foreground=TEXT_MUTED, background=BACKGROUND_ELEVATED)
            style.configure("Dark.TLabel", foreground=TEXT_PRIMARY, background=BACKGROUND_DARK)
            style.configure("Dark.TEntry", fieldbackground=BACKGROUND_ELEVATED, foreground=TEXT_PRIMARY)
            style.configure("Dark.TCombobox", fieldbackground=BACKGROUND_ELEVATED, foreground=TEXT_PRIMARY)
        except Exception:
            pass

    def apply_root(self, root) -> None:
        """
        Apply global styles to the given Tk root widget.
        Safe to call multiple times; must not raise.
        """
        try:
            apply_theme(root)
        except Exception:
            pass

__all__ = [
    "Theme",
    "BACKGROUND_DARK",
    "BACKGROUND_ELEVATED",
    "BORDER_SUBTLE",
    "TEXT_PRIMARY",
    "TEXT_MUTED",
    "TEXT_DISABLED",
    "ACCENT_GOLD",
    "ACCENT_GOLD_HOVER",
    "ERROR_RED",
    "SUCCESS_GREEN",
    "INFO_BLUE",
    "ASWF_BLACK",
    "ASWF_DARK_GREY",
    "ASWF_MED_GREY",
    "ASWF_LIGHT_GREY",
    "ASWF_GOLD",
    "ASWF_ERROR_RED",
    "ASWF_OK_GREEN",
    "PADDING_XS",
    "PADDING_SM",
    "PADDING_MD",
    "PADDING_LG",
    "SURFACE_FRAME_STYLE",
    "STATUS_LABEL_STYLE",
    "STATUS_STRONG_LABEL_STYLE",
]
