"""GUI-SEAM-741: the semantic design tokens import without a toolkit and keep their exact values."""

from __future__ import annotations

import ast
import dataclasses
import re
import subprocess
import sys
import textwrap
import tkinter as tk
from pathlib import Path
from tkinter import ttk

from src.gui import design_system_v2 as ds
from src.gui import theme_v2, ui_tokens
from src.gui_v2 import design_values

ROOT = Path(__file__).resolve().parents[2]

_FORBID_TK = textwrap.dedent(
    """
    import importlib.abc
    import sys

    sys.path.insert(0, {root!r})


    class ForbidTk(importlib.abc.MetaPathFinder):
        def find_spec(self, name, path=None, target=None):
            if name in ("tkinter", "_tkinter") or name.startswith("tkinter."):
                raise ImportError("forbidden toolkit import: " + name)
            return None


    sys.meta_path.insert(0, ForbidTk())
    """
)


def _run_isolated(body: str) -> subprocess.CompletedProcess[str]:
    code = _FORBID_TK.format(root=str(ROOT)) + textwrap.dedent(body)
    return subprocess.run(
        [sys.executable, "-c", code],
        capture_output=True,
        text=True,
        timeout=120,
        cwd=ROOT,
        check=False,
    )


def test_ui_tokens_import_in_a_fresh_process_that_forbids_tkinter() -> None:
    result = _run_isolated(
        """
        import src.gui.ui_tokens as ui_tokens
        from src.gui.ui_tokens import TOKENS, ColorTokens, SpacingTokens, TypeTokens, NoticeTokens

        assert isinstance(TOKENS.colors, ColorTokens)
        assert isinstance(TOKENS.spacing, SpacingTokens)
        assert isinstance(TOKENS.typography, TypeTokens)
        assert isinstance(TOKENS.notices, NoticeTokens)
        loaded = sorted(m for m in sys.modules if m in ("tkinter", "_tkinter") or m.startswith("tkinter."))
        assert not loaded, loaded
        print("ok")
        """
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "ok"


def test_the_forbidding_finder_really_blocks_the_legacy_tk_module() -> None:
    """Guards the harness: the Tk-bound renderer module must fail under the same finder, so a pass above means something."""

    result = _run_isolated("import src.gui.design_system_v2\n")
    assert result.returncode != 0
    assert "forbidden toolkit import: tkinter" in result.stderr


def test_design_values_is_a_leaf_with_no_imports_beyond_dataclasses() -> None:
    tree = ast.parse(Path(design_values.__file__).read_text(encoding="utf-8"))
    modules: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            modules.add(node.module or "")
    assert modules <= {"__future__", "dataclasses"}


def test_import_direction_is_one_way_from_the_renderers_to_the_values() -> None:
    tokens_tree = ast.parse(Path(ui_tokens.__file__).read_text(encoding="utf-8"))
    imported = {
        (node.module or "") + "." + alias.name
        for node in ast.walk(tokens_tree)
        if isinstance(node, ast.ImportFrom)
        for alias in node.names
    }
    assert "src.gui.design_system_v2" not in imported
    assert "src.gui_v2.design_values" in imported


def test_the_tk_renderer_holds_no_second_copy_of_the_values() -> None:
    source = Path(ds.__file__).read_text(encoding="utf-8")
    assert not re.search(r"[\"']#[0-9A-Fa-f]{6}[\"']", source)
    for name in ("Colors", "Spacing", "Typography", "Radii"):
        assert getattr(ds, name) is getattr(design_values, name)
    assert ds.NOTICE_KINDS is design_values.NOTICE_KINDS
    assert ds.Color is design_values.Color
    assert ui_tokens.NOTICE_KINDS is design_values.NOTICE_KINDS


def _defaults(cls: type) -> dict[str, object]:
    return {field.name: field.default for field in dataclasses.fields(cls)}


def test_raw_design_values_are_exactly_the_pre_extraction_values() -> None:
    assert _defaults(ds.Colors) == {
        "PRIMARY_BG": "#121212",
        "ELEVATED_SURFACE": "#1E1E1E",
        "CARD_BG": "#1E1E1E",
        "BORDER": "#2D2D2D",
        "PRIMARY_ACCENT": "#FFC805",
        "PRIMARY_ACCENT_HOVER": "#FFD94D",
        "TEXT_PRIMARY": "#FFFFFF",
        "TEXT_MUTED": "#CCCCCC",
        "TEXT_DISABLED": "#777777",
        "DANGER_BG": "#D9363E",
        "DANGER_BG_HOVER": "#C62F36",
        "DANGER_FG": "#FFFFFF",
        "SEPARATOR": "#2A2A2A",
        "SURFACE_HOVER": "#262626",
        "SURFACE_SELECTED": "#2B2B2B",
        "SECONDARY_HOVER": "#3A3A3A",
        "TEXT_ON_ACCENT": "#000000",
        "FOCUS_RING": "#FFC805",
        "FOCUS_RING_ON_FILL": "#FFFFFF",
        "ACCENT_DISABLED_EDGE": "#8C7413",
    }
    assert _defaults(ds.Spacing) == {"NONE": 0, "XS": 2, "SM": 4, "MD": 8, "LG": 12, "XL": 16}
    assert _defaults(ds.Radii) == {"SM": 4, "MD": 8, "LG": 12}
    assert _defaults(ds.Typography) == {
        "FAMILY": "Segoe UI",
        "XS": 9,
        "SM": 10,
        "MD": 11,
        "LG": 12,
        "XL": 14,
        "BOLD": "bold",
        "NORMAL": "normal",
    }
    assert ds.NOTICE_KINDS == ("neutral", "info", "success", "warning", "error")


def test_semantic_tokens_keep_their_exact_values_and_the_intentional_spacing_difference() -> None:
    colors = ui_tokens.TOKENS.colors
    assert colors.surface_primary == "#121212"
    assert colors.surface_tertiary == "#161616"
    assert colors.status_success == "#52C41A"
    assert colors.status_error == "#FF4D4F"
    assert colors.action_danger == "#D9363E"
    assert colors.focus_ring == "#FFC805"
    spacing = ui_tokens.TOKENS.spacing
    assert (spacing.xs, spacing.sm, spacing.md, spacing.lg, spacing.xl) == (4, 4, 8, 12, 24)
    assert ds.Spacing.XS == 2 and spacing.xs == 4
    type_tokens = ui_tokens.TOKENS.typography
    assert (type_tokens.family, type_tokens.size_sm, type_tokens.size_md, type_tokens.size_lg) == (
        "Segoe UI",
        10,
        11,
        12,
    )
    notices = ui_tokens.TOKENS.notices
    assert [(r.kind, r.label, r.a11y_role) for r in map(notices.role, ds.NOTICE_KINDS)] == [
        ("neutral", "Note", "status"),
        ("info", "Info", "status"),
        ("success", "Success", "status"),
        ("warning", "Warning", "alert"),
        ("error", "Error", "alert"),
    ]
    assert notices.role("error").background == "#2E1A1B"
    assert notices.role("not-a-kind") is notices.neutral


def test_helper_signatures_and_style_name_helpers_are_unchanged() -> None:
    assert ds.notice_style_names("warning") == (
        "Notice.Warning.TFrame",
        "Notice.Warning.TLabel",
        "NoticePrefix.Warning.TLabel",
        "NoticeBar.Warning.TFrame",
    )
    assert ds.notice_style_names("bogus") == ds.notice_style_names("neutral")
    for name in (
        "apply_design_system",
        "apply_card_styles",
        "apply_label_styles",
        "apply_button_styles",
    ):
        assert callable(getattr(ds, name))
    assert ds.PRIMARY_BUTTON == "Primary.TButton"
    assert ds.PAGE_RADIOBUTTON == "Page.TRadiobutton"


def test_tk_registration_still_resolves_styles_from_the_shared_values(tk_root: tk.Tk) -> None:
    style: ttk.Style = theme_v2.apply_theme(tk_root)
    colors = design_values.Colors
    assert style.lookup(ds.PRIMARY_BUTTON, "background") == colors.PRIMARY_ACCENT
    assert style.lookup(ds.PRIMARY_BUTTON, "foreground") == colors.TEXT_ON_ACCENT
    assert style.lookup(ds.DANGER_BUTTON, "background") == colors.DANGER_BG
    assert style.lookup(ds.CARD_FRAME, "background") == colors.CARD_BG
    assert style.lookup(ds.HEADING_LABEL, "foreground") == colors.PRIMARY_ACCENT
    assert style.lookup(ds.PAGE_BODY_LABEL, "background") == colors.PRIMARY_BG
    assert style.lookup(ds.PRIMARY_BUTTON, "background", ["disabled"]) == colors.BORDER
    font = style.lookup(ds.HEADING_LABEL, "font")
    assert str(design_values.Typography.LG) in str(font) and "bold" in str(font)
    pad = str(style.lookup(ds.CARD_FRAME, "padding")).split()
    assert pad == [str(design_values.Spacing.MD)] * 2
