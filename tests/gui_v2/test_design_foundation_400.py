"""PR-GUI-400: design foundation (tokens, ttk styles, shared component presentation).

Deterministic checks of the canonical token roles, the registered ttk styles and their state maps, and the shared
``TabOverviewPanel`` / ``SubmissionNotice`` / ``DisclosureSection`` presentation. They inspect resolved Tk style
data (not pixels), so they hold on any display scale; the visual comparison lives in the PR evidence.
"""

from __future__ import annotations

import re
import tkinter as tk
from tkinter import ttk

import pytest

from src.gui import design_system_v2 as ds
from src.gui import theme_v2
from src.gui.ui_tokens import NOTICE_KINDS, TOKENS, NoticeRole
from src.gui.widgets.disclosure_section_v2 import DisclosureSection
from src.gui.widgets.submission_notice_v2 import (
    KIND_ERROR,
    KIND_QUEUED,
    SubmissionNotice,
)
from src.gui.widgets.tab_overview_panel_v2 import TabOverviewPanel, get_tab_overview_content

HEX = re.compile(r"^#[0-9a-fA-F]{6}$")


def _luminance(color: str) -> float:
    channels = [int(color[i : i + 2], 16) / 255 for i in (1, 3, 5)]
    linear = [c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4 for c in channels]
    return 0.2126 * linear[0] + 0.7152 * linear[1] + 0.0722 * linear[2]


def contrast(first: str, second: str) -> float:
    high, low = sorted((_luminance(first), _luminance(second)), reverse=True)
    return (high + 0.05) / (low + 0.05)


@pytest.fixture
def style(tk_root: tk.Tk) -> ttk.Style:
    return theme_v2.apply_theme(tk_root)


def _bg(style: ttk.Style, name: str, state: list[str] | None = None) -> str:
    return str(style.lookup(name, "background", state or [])).lower()


def _fg(style: ttk.Style, name: str, state: list[str] | None = None) -> str:
    return str(style.lookup(name, "foreground", state or [])).lower()


def _border(style: ttk.Style, name: str, state: list[str] | None = None) -> str:
    return str(style.lookup(name, "bordercolor", state or [])).lower()


def _embossed_when_disabled(style: ttk.Style, name: str) -> str:
    """'0' only when the style explicitly turns the doubled disabled-text shadow off (unset is '')."""

    return str(style.lookup(name, "embossed", ["disabled"]))


ACTION_BUTTONS = (ds.PRIMARY_BUTTON, ds.SECONDARY_BUTTON, ds.GHOST_BUTTON, ds.DANGER_BUTTON)
BUTTONS = (
    *ACTION_BUTTONS,
    "TButton",
    "Dark.TButton",
    "Disclosure.TButton",
    "DisclosureActive.TButton",
)
SURFACE_LABELS = (
    ds.HEADING_LABEL,
    ds.SUBHEADING_LABEL,
    ds.BODY_LABEL,
    ds.MUTED_LABEL,
)


# --------------------------------------------------------------------------------------------- tokens


def test_notice_roles_cover_every_semantic_kind_with_text_meaning() -> None:
    assert NOTICE_KINDS == ("neutral", "info", "success", "warning", "error")
    labels = set()
    for kind in NOTICE_KINDS:
        role = TOKENS.notices.role(kind)
        assert isinstance(role, NoticeRole) and role.kind == kind
        assert role.label.strip(), "a status must carry words, not only a color"
        assert role.a11y_role in {"alert", "status"}
        for color in (role.foreground, role.label_foreground, role.background, role.accent):
            assert HEX.match(color), (kind, color)
        labels.add(role.label)
    assert len(labels) == len(NOTICE_KINDS), "each kind needs its own word"
    assert TOKENS.notices.role("error").a11y_role == "alert"
    assert TOKENS.notices.role("warning").a11y_role == "alert"
    assert TOKENS.notices.role("unknown-kind").kind == "neutral"


@pytest.mark.parametrize("kind", NOTICE_KINDS)
def test_notice_text_stays_readable_on_its_tint(kind: str) -> None:
    role = TOKENS.notices.role(kind)
    assert contrast(role.foreground, role.background) >= 7.0
    assert contrast(role.label_foreground, role.background) >= 4.5
    assert contrast(role.accent, role.background) >= 3.0, (
        "the edge bar must be visible against the tint"
    )


def test_tokens_keep_the_existing_metric_assumptions() -> None:
    # Wave 1 must not invalidate the min-width work: spacing and type sizes are unchanged.
    assert (TOKENS.spacing.sm, TOKENS.spacing.md, TOKENS.spacing.lg) == (4, 8, 12)
    assert (TOKENS.typography.size_sm, TOKENS.typography.size_md, TOKENS.typography.size_lg) == (
        10,
        11,
        12,
    )
    assert TOKENS.typography.family == "Segoe UI"


def test_brand_identity_is_preserved() -> None:
    assert TOKENS.colors.surface_primary.lower() == "#121212"
    assert TOKENS.colors.surface_secondary.lower() == "#1e1e1e"
    assert TOKENS.colors.accent_primary.lower() == "#ffc805"


def test_interactive_role_tokens_are_valid_and_distinct() -> None:
    colors = TOKENS.colors
    for value in (
        colors.surface_selected,
        colors.surface_hover,
        colors.text_on_accent,
        colors.focus_ring,
        colors.focus_ring_on_accent,
        colors.action_danger,
        colors.text_on_danger,
    ):
        assert HEX.match(value)
    assert colors.surface_selected != colors.surface_secondary
    assert contrast(colors.text_on_accent, colors.accent_primary) >= 7.0
    assert contrast(colors.text_on_danger, colors.action_danger) >= 4.5
    assert contrast(colors.focus_ring, colors.surface_secondary) >= 3.0
    assert contrast(colors.focus_ring_on_accent, colors.surface_secondary) >= 3.0
    assert contrast(colors.text_disabled, colors.surface_secondary) >= 3.0


# ---------------------------------------------------------------------------------------- registration


def test_public_style_names_are_unchanged() -> None:
    assert ds.PRIMARY_BUTTON == "Primary.TButton"
    assert ds.SECONDARY_BUTTON == "Secondary.TButton"
    assert ds.GHOST_BUTTON == "Ghost.TButton"
    assert ds.DANGER_BUTTON == "Danger.TButton"
    assert ds.HEADING_LABEL == "Heading.TLabel"
    assert ds.SUBHEADING_LABEL == "Subheading.TLabel"
    assert ds.BODY_LABEL == "Body.TLabel"
    assert ds.MUTED_LABEL == "Muted.TLabel"
    assert ds.CARD_FRAME == "Card.TFrame"
    assert theme_v2.SUBMISSION_ERROR_LABEL_STYLE == "SubmissionError.TLabel"


def test_every_public_style_is_registered_in_ttk_style(style: ttk.Style) -> None:
    names = [
        *BUTTONS,
        *SURFACE_LABELS,
        ds.CARD_FRAME,
        ds.SECTION_FRAME,
        "Panel.TFrame",
        "TRadiobutton",
        "Dark.TRadiobutton",
        theme_v2.SUBMISSION_ERROR_LABEL_STYLE,
    ]
    for kind in NOTICE_KINDS:
        names.extend(ds.notice_style_names(kind))
    for name in names:
        assert _bg(style, name), f"{name} has no background"
    for name in (
        *BUTTONS,
        *SURFACE_LABELS,
        "Dark.TLabel",
        "Dark.TCheckbutton",
        "Dark.TRadiobutton",
    ):
        assert _fg(style, name), f"{name} has no foreground"


def test_applying_the_theme_twice_is_idempotent(tk_root: tk.Tk) -> None:
    first = theme_v2.apply_theme(tk_root)
    snapshot = {name: _bg(first, name) for name in BUTTONS}
    second = theme_v2.apply_theme(tk_root)
    assert snapshot == {name: _bg(second, name) for name in BUTTONS}


# ------------------------------------------------------------------------------------ states and roles


@pytest.mark.parametrize("name", BUTTONS)
def test_disabled_buttons_are_distinct_readable_and_not_embossed(
    style: ttk.Style, name: str
) -> None:
    enabled_fg = _fg(style, name)
    disabled_fg = _fg(style, name, ["disabled"])
    assert disabled_fg == TOKENS.colors.text_disabled.lower()
    assert disabled_fg != enabled_fg, "disabled must not look like enabled"
    assert contrast(disabled_fg, _bg(style, name, ["disabled"])) >= 3.0
    assert _embossed_when_disabled(style, name) == "0", (
        "disabled text must not get the doubled shadow"
    )


@pytest.mark.parametrize("name", BUTTONS)
def test_every_button_shows_keyboard_focus(style: ttk.Style, name: str) -> None:
    resting = _border(style, name)
    focused = _border(style, name, ["focus"])
    assert focused != resting, f"{name} shows no focus change"
    surface = TOKENS.colors.surface_secondary
    assert contrast(focused, surface) >= 3.0, "the focus edge must be visible against the surface"


@pytest.mark.parametrize("name", [*ACTION_BUTTONS, "TButton", "Dark.TButton", "Disclosure.TButton"])
def test_buttons_have_a_hover_state(style: ttk.Style, name: str) -> None:
    assert _bg(style, name, ["active"]) != _bg(style, name)


def test_primary_is_the_only_gold_filled_action_and_danger_is_distinct(style: ttk.Style) -> None:
    gold = TOKENS.colors.accent_primary.lower()
    filled = [name for name in BUTTONS if _bg(style, name) == gold]
    assert filled == [ds.PRIMARY_BUTTON]
    assert _bg(style, ds.DANGER_BUTTON) == TOKENS.colors.action_danger.lower()
    assert _bg(style, ds.DANGER_BUTTON) != _bg(style, ds.PRIMARY_BUTTON)
    assert contrast(_fg(style, ds.DANGER_BUTTON), _bg(style, ds.DANGER_BUTTON)) >= 4.5
    assert contrast(_fg(style, ds.PRIMARY_BUTTON), _bg(style, ds.PRIMARY_BUTTON)) >= 7.0


def test_a_disabled_primary_still_reads_as_the_primary_action(style: ttk.Style) -> None:
    primary = _border(style, ds.PRIMARY_BUTTON, ["disabled"])
    secondary = _border(style, ds.SECONDARY_BUTTON, ["disabled"])
    assert primary != secondary, "a disabled CTA keeps a distinguishing edge"


def test_gold_is_reserved_for_primary_selected_active_and_focus(style: ttk.Style) -> None:
    gold = TOKENS.colors.accent_primary.lower()
    quiet = (
        ds.SUBHEADING_LABEL,
        ds.BODY_LABEL,
        ds.MUTED_LABEL,
        "Dark.TLabel",
        "Dark.TButton",
        "Disclosure.TButton",
        ds.SECONDARY_BUTTON,
        *[ds.notice_style_names(kind).message for kind in NOTICE_KINDS],
    )
    for name in quiet:
        assert _fg(style, name) != gold, f"{name} should not spend the accent"
    assert _fg(style, "DisclosureActive.TButton") == gold, (
        "non-default hidden content keeps its accent"
    )


@pytest.mark.parametrize("name", SURFACE_LABELS)
def test_semantic_labels_sit_on_the_card_surface_not_a_darker_rectangle(
    style: ttk.Style, name: str
) -> None:
    assert _bg(style, name) == TOKENS.colors.surface_secondary.lower()
    for container in (ds.CARD_FRAME, ds.SECTION_FRAME, "Panel.TFrame", "TLabelframe"):
        assert _bg(style, name) == _bg(style, container), (name, container)


@pytest.mark.parametrize(
    ("page_style", "card_style"),
    [(ds.PAGE_BODY_LABEL, ds.BODY_LABEL), (ds.PAGE_MUTED_LABEL, ds.MUTED_LABEL)],
)
def test_page_surface_variants_change_only_the_surface(
    style: ttk.Style, page_style: str, card_style: str
) -> None:
    assert _bg(style, page_style) == TOKENS.colors.surface_primary.lower()
    assert _fg(style, page_style) == _fg(style, card_style)
    assert style.lookup(page_style, "font") == style.lookup(card_style, "font")


def test_page_radiobutton_sits_on_the_page_surface(style: ttk.Style) -> None:
    assert _bg(style, ds.PAGE_RADIOBUTTON) == TOKENS.colors.surface_primary.lower()
    assert _fg(style, ds.PAGE_RADIOBUTTON, ["disabled"]) == TOKENS.colors.text_disabled.lower()
    assert _embossed_when_disabled(style, ds.PAGE_RADIOBUTTON) == "0"


@pytest.mark.parametrize("name", ["TRadiobutton", "Dark.TRadiobutton"])
def test_radiobuttons_are_themed_not_toolkit_default_gray(style: ttk.Style, name: str) -> None:
    assert _bg(style, name) == TOKENS.colors.surface_secondary.lower()
    assert _fg(style, name) == TOKENS.colors.text_primary.lower()
    assert _fg(style, name, ["disabled"]) == TOKENS.colors.text_disabled.lower()
    assert _embossed_when_disabled(style, name) == "0"


@pytest.mark.parametrize("name", ["Dark.TEntry", "Dark.TCombobox", "Dark.TSpinbox", "TEntry"])
def test_text_fields_distinguish_disabled_and_focus(style: ttk.Style, name: str) -> None:
    field = lambda state: str(style.lookup(name, "fieldbackground", state)).lower()  # noqa: E731
    assert field(["disabled"]) != field([]), "a disabled field must look different"
    assert _fg(style, name, ["disabled"]) == TOKENS.colors.text_disabled.lower()
    assert _border(style, name, ["focus"]) == TOKENS.colors.focus_ring.lower()


@pytest.mark.parametrize("name", ["TCheckbutton", "Dark.TCheckbutton"])
def test_checkbuttons_distinguish_disabled_and_selected(style: ttk.Style, name: str) -> None:
    assert _fg(style, name, ["disabled"]) == TOKENS.colors.text_disabled.lower()
    assert _embossed_when_disabled(style, name) == "0"
    on = str(style.lookup(name, "indicatorcolor", ["selected"])).lower()
    off = str(style.lookup(name, "indicatorcolor", ["!selected"])).lower()
    assert on != off


def test_notebook_tabs_make_selected_obvious(style: ttk.Style) -> None:
    selected_bg, resting_bg = _bg(style, "TNotebook.Tab", ["selected"]), _bg(style, "TNotebook.Tab")
    assert selected_bg != resting_bg
    assert contrast(selected_bg, resting_bg) >= 1.2
    assert _fg(style, "TNotebook.Tab", ["selected"]) != _fg(style, "TNotebook.Tab")
    assert _border(style, "TNotebook.Tab", ["selected"]) != _border(style, "TNotebook.Tab")
    assert _fg(style, "TNotebook.Tab", ["disabled"]) == TOKENS.colors.text_disabled.lower()
    for state in ([], ["selected"]):
        assert (
            contrast(_fg(style, "TNotebook.Tab", state), _bg(style, "TNotebook.Tab", state)) >= 4.5
        )


def test_action_button_outer_size_is_unchanged_by_the_focus_edge(style: ttk.Style) -> None:
    # A 1px edge was added so focus can show on filled buttons; padding gave it back, so the outer
    # size (and every min-width decision downstream) matches the previous (MD, SM) padding with no edge.
    for name in (ds.PRIMARY_BUTTON, ds.SECONDARY_BUTTON, ds.DANGER_BUTTON):
        border = int(str(style.lookup(name, "borderwidth")) or 0)
        padding = [int(float(part)) for part in str(style.lookup(name, "padding")).split()]
        horizontal, vertical = padding[0], padding[1]
        assert 2 * border + 2 * horizontal == 2 * ds.Spacing.MD, name
        assert 2 * border + 2 * vertical == 2 * ds.Spacing.SM, name


# ------------------------------------------------------------------------------------ SubmissionNotice


def _notice(root: tk.Tk) -> SubmissionNotice:
    root.columnconfigure(0, weight=1)
    notice = SubmissionNotice(root)
    notice.grid(row=0, column=0, sticky="ew")  # the tabs grid it; show/clear re-map and un-map it
    return notice


def test_notice_error_exposes_role_text_and_keeps_the_message_untouched(
    tk_root: tk.Tk, style: ttk.Style
) -> None:
    notice = _notice(tk_root)
    try:
        notice.show_error("Source image is missing")
        assert notice.kind == KIND_ERROR
        assert notice.message_var.get() == "Source image is missing"
        assert notice.role == "alert"
        assert notice.prefix_label.cget("text") == "Error"
        assert notice.accessible_text() == "Error: Source image is missing"
        assert str(notice.label.cget("style")) == ds.notice_style_names("error").message
        assert str(notice.prefix_label.cget("style")) == ds.notice_style_names("error").prefix
        assert notice.winfo_manager() == "grid"
    finally:
        notice.destroy()


@pytest.mark.parametrize(
    ("method", "kind", "word", "role"),
    [
        ("show_info", "info", "Info", "status"),
        ("show_warning", "warning", "Warning", "alert"),
        ("show_success", "success", "Success", "status"),
    ],
)
def test_notice_inline_kinds_each_carry_a_word_and_role(
    tk_root: tk.Tk, style: ttk.Style, method: str, kind: str, word: str, role: str
) -> None:
    notice = _notice(tk_root)
    try:
        getattr(notice, method)("The selected workflow is experimental.")
        assert notice.kind == kind
        assert notice.role == role
        assert notice.prefix_label.cget("text") == word
        assert notice.accessible_text() == f"{word}: The selected workflow is experimental."
        assert notice.winfo_manager() == "grid"
    finally:
        notice.destroy()


def test_notice_queued_keeps_its_kind_and_gets_a_word(tk_root: tk.Tk, style: ttk.Style) -> None:
    notice = _notice(tk_root)
    try:
        notice.show_queued("Queued 1 job.", on_view_queue=lambda: None)
        assert notice.kind == KIND_QUEUED
        assert notice.role == "status"
        assert notice.prefix_label.cget("text") == "Queued"
        assert notice.accessible_text() == "Queued: Queued 1 job."
        assert notice.view_button.winfo_manager() == "grid"
    finally:
        notice.destroy()


def test_notice_replace_and_clear_update_role_and_text(tk_root: tk.Tk, style: ttk.Style) -> None:
    notice = _notice(tk_root)
    try:
        notice.show_error("First failure")
        notice.show_queued("Queued now")
        assert notice.role == "status" and notice.accessible_text() == "Queued: Queued now"
        assert str(notice.label.cget("style")) == ds.notice_style_names("success").message
        notice.show_warning("Heads up")
        assert notice.role == "alert" and notice.prefix_label.cget("text") == "Warning"
        assert notice._dismiss_id is None, "a warning stays until dismissed"  # noqa: SLF001
        notice.clear()
        assert notice.kind == "" and notice.role == ""
        assert notice.accessible_text() == ""
        assert notice.message_var.get() == ""
        assert notice.winfo_manager() == ""
    finally:
        notice.destroy()


def test_notice_errors_persist_but_success_dismisses_itself(
    tk_root: tk.Tk, style: ttk.Style
) -> None:
    notice = _notice(tk_root)
    try:
        notice.show_error("Stays")
        assert notice._dismiss_id is None  # noqa: SLF001
        notice.show_success("Done")
        assert notice._dismiss_id is not None  # noqa: SLF001
        notice.show_info("Stays too")
        assert notice._dismiss_id is None, "replacing a notice cancels the pending dismissal"  # noqa: SLF001
    finally:
        notice.destroy()


def test_idle_notice_paints_nothing_and_keeps_the_reserved_height(
    tk_root: tk.Tk, style: ttk.Style
) -> None:
    notice = _notice(tk_root)
    try:
        tk_root.update_idletasks()
        assert notice.bar.winfo_manager() == "" and notice.prefix_label.winfo_manager() == ""
        assert str(notice.cget("style")) == "Panel.TFrame", (
            "an empty notice must not tint or draw an edge bar"
        )
        reference = ttk.Label(
            tk_root, textvariable=tk.StringVar(master=tk_root, value=""), style="Dark.TLabel"
        )
        assert notice.winfo_reqheight() == reference.winfo_reqheight(), (
            "idle height is one empty label, as before"
        )
        reference.destroy()
        notice.show_error("Visible now")
        assert (
            notice.bar.winfo_manager() == "grid" and notice.prefix_label.winfo_manager() == "grid"
        )
        notice.clear()
        assert notice.bar.winfo_manager() == "" and notice.prefix_label.winfo_manager() == ""
        assert str(notice.cget("style")) == "Panel.TFrame"
    finally:
        notice.destroy()


def test_notice_blank_message_still_names_the_kind(tk_root: tk.Tk, style: ttk.Style) -> None:
    notice = _notice(tk_root)
    try:
        notice.show_error("   ")
        assert notice.message_var.get() == ""
        assert notice.accessible_text() == "Error"
    finally:
        notice.destroy()


def test_notice_children_share_the_notice_surface(tk_root: tk.Tk, style: ttk.Style) -> None:
    notice = _notice(tk_root)
    try:
        for kind in NOTICE_KINDS:
            names = ds.notice_style_names(kind)
            tint = TOKENS.notices.role(kind).background.lower()
            assert _bg(style, names.frame) == tint
            assert _bg(style, names.message) == tint
            assert _bg(style, names.prefix) == tint
            assert _bg(style, names.bar) == TOKENS.notices.role(kind).accent.lower()
    finally:
        notice.destroy()


# ---------------------------------------------------------------------------------- TabOverviewPanel


def test_overview_panel_uses_token_spacing_and_demotes_its_title(
    tk_root: tk.Tk, style: ttk.Style
) -> None:
    panel = TabOverviewPanel(tk_root, content=get_tab_overview_content("pipeline"))
    panel.pack(fill="x")
    try:
        padding = tuple(int(float(str(part))) for part in panel.cget("padding"))
        assert padding == (TOKENS.spacing.md, TOKENS.spacing.sm)
        assert str(panel.title_label.cget("style")) == ds.SUBHEADING_LABEL
        assert _fg(style, ds.SUBHEADING_LABEL) == TOKENS.colors.text_primary.lower()
        assert str(panel.summary_label.cget("style")) == ds.BODY_LABEL
        assert str(panel.details_label.cget("style")) == ds.MUTED_LABEL
    finally:
        panel.destroy()


def test_overview_panel_text_sits_on_the_panel_surface(tk_root: tk.Tk, style: ttk.Style) -> None:
    panel = TabOverviewPanel(tk_root, content=get_tab_overview_content("review"), expanded=True)
    panel.pack(fill="x")
    try:
        surface = _bg(style, "Panel.TFrame")
        for label in (panel.title_label, panel.summary_label, panel.details_label):
            assert _bg(style, str(label.cget("style"))) == surface
    finally:
        panel.destroy()


def test_overview_panel_expanded_state_is_visible_textual_and_reversible(
    tk_root: tk.Tk, style: ttk.Style
) -> None:
    panel = TabOverviewPanel(tk_root, content=get_tab_overview_content("pipeline"))
    panel.pack(fill="x")
    try:
        tk_root.update_idletasks()
        collapsed_height = panel.winfo_reqheight()
        assert panel.toggle_button.cget("text") == "Show Guidance"
        assert not panel.toggle_button.instate(["selected"])

        panel.toggle_button.invoke()
        tk_root.update_idletasks()
        expanded_height = panel.winfo_reqheight()
        assert panel.toggle_button.cget("text") == "Hide Guidance"
        assert panel.toggle_button.instate(["selected"])
        assert expanded_height > collapsed_height

        panel.toggle_button.invoke()
        tk_root.update_idletasks()
        assert panel.winfo_reqheight() == collapsed_height, "no stuck fixed height after collapsing"
        assert not panel.toggle_button.instate(["selected"])
    finally:
        panel.destroy()


def test_overview_panel_help_mode_is_labelled_not_color_only(
    tk_root: tk.Tk, style: ttk.Style
) -> None:
    from src.gui.app_state_v2 import AppStateV2

    app_state = AppStateV2()
    panel = TabOverviewPanel(
        tk_root, content=get_tab_overview_content("pipeline"), app_state=app_state
    )
    panel.pack(fill="x")
    try:
        app_state.set_help_mode_enabled(True)
        assert panel.toggle_button.cget("text") == "Help Mode On"
        assert panel.toggle_button.instate(["disabled"])
        assert panel.toggle_button.instate(["selected"])
    finally:
        panel.destroy()


# --------------------------------------------------------------------------------- DisclosureSection


def test_disclosure_expanded_state_is_a_visible_style_state(
    tk_root: tk.Tk, style: ttk.Style
) -> None:
    section = DisclosureSection(tk_root, title="Advanced options")
    section.pack(fill="x")
    try:
        header = section.toggle_button
        assert not header.instate(["selected"])
        assert section.header_text() == f"{theme_v2.EXPANDER_ICON_COLLAPSED} Advanced options"
        section.set_expanded(True)
        assert header.instate(["selected"])
        assert section.header_text() == f"{theme_v2.EXPANDER_ICON_EXPANDED} Advanced options"
        section.toggle()
        assert not header.instate(["selected"])

        for name in ("Disclosure.TButton", "DisclosureActive.TButton"):
            assert _bg(style, name, ["selected"]) != _bg(style, name)
            assert _bg(style, name, ["selected"]) == TOKENS.colors.surface_selected.lower()
            assert contrast(_fg(style, name, ["selected"]), _bg(style, name, ["selected"])) >= 4.5
    finally:
        section.destroy()


def test_disclosure_collapsed_and_expanded_keep_natural_height(
    tk_root: tk.Tk, style: ttk.Style
) -> None:
    section = DisclosureSection(tk_root, title="Advanced options")
    section.pack(fill="x")
    ttk.Label(section.body, text="Body content", style=ds.BODY_LABEL).grid()
    try:
        tk_root.update_idletasks()
        collapsed = section.winfo_reqheight()
        section.set_expanded(True)
        tk_root.update_idletasks()
        assert section.winfo_reqheight() > collapsed
        section.set_expanded(False)
        tk_root.update_idletasks()
        assert section.winfo_reqheight() == collapsed
        assert str(section.body.cget("height")) in {"0", ""}, (
            "the body is never given a fixed height"
        )
    finally:
        section.destroy()


def test_disclosure_state_changes_keep_the_active_accent_orthogonal(
    tk_root: tk.Tk, style: ttk.Style
) -> None:
    section = DisclosureSection(tk_root, title="Advanced options")
    section.pack(fill="x")
    try:
        section.set_status("2 changed", active=True)
        section.set_expanded(True)
        header = section.toggle_button
        assert header.instate(["selected"])
        assert str(header.cget("style")) == "DisclosureActive.TButton"
        assert "2 changed" not in section.header_text(), "the status hint is a collapsed-only cue"
        section.set_expanded(False)
        assert not header.instate(["selected"])
        assert str(header.cget("style")) == "DisclosureActive.TButton"
        assert "2 changed" in section.header_text()
    finally:
        section.destroy()
