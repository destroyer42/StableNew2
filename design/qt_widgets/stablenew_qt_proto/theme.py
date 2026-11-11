"""Versioned, strictly validated design-theme contract (pure Python, no Qt).

A theme is a JSON document (``schema`` + ``schema_version``) that carries every value the
prototype's stylesheet and layouts read: semantic colours, typography, spacing/density,
borders, radii and component state appearance. This module owns parsing, validation,
serialisation, contrast diagnostics, the draft editor and the stylesheet builder.

It is a *design artifact only*. It never reads or writes StableNew production settings,
and the production Tk design values (``src/gui_v2/design_values.py``) are not imported.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Iterator, Mapping
from dataclasses import dataclass, field, fields, replace
from pathlib import Path
from typing import Any

SCHEMA = "stablenew.qt-design-theme"
SCHEMA_VERSION = 1
MAX_THEME_BYTES = 128 * 1024

COLOR_ROLES: tuple[str, ...] = (
    "background",
    "surface",
    "field",
    "selected",
    "border",
    "strong_border",
    "text",
    "muted",
    "disabled",
    "accent",
    "on_accent",
    "danger",
    "success",
    "danger_fill",
    "on_danger",
)
STATE_DEFAULTS: dict[str, str] = {
    "button_hover_border": "accent",
    "input_hover_border": "strong_border",
    "focus_border": "accent",
    "pressed_background": "surface",
    "primary_hover_border": "text",
    "primary_focus_border": "text",
    "selected_item_border": "accent",
    "hover_fill": "selected",
}
# Status levels shared by notices and chips; the stylesheet styles every one of them.
LEVELS = ("info", "warning", "blocked", "success")
WEIGHTS = ("normal", "bold")
DENSITIES = ("comfortable", "compact")
KINDS = ("reference", "user")
FALLBACK_FONT = "Arial"

_HEX = re.compile(r"^#[0-9A-Fa-f]{6}$")
_FAMILY = re.compile(r"^[A-Za-z0-9][A-Za-z0-9 ._-]{0,63}$")
_ID = re.compile(r"^[a-z0-9][a-z0-9-]{0,47}$")
_NOTE_KEY = re.compile(r"^[a-z_]+(\.[a-z_]+)?$")

# (min, max) inclusive integer ranges for every numeric field.
RANGES: dict[str, dict[str, tuple[int, int]]] = {
    "typography": {
        "body_pt": (8, 16),
        "small_pt": (7, 14),
        "section_pt": (8, 20),
        "heading_pt": (9, 28),
    },
    "spacing": {
        "xs": (0, 16),
        "sm": (0, 24),
        "md": (0, 32),
        "gutter": (0, 48),
        "xl": (0, 64),
        "control_min_height": (24, 64),
    },
    "borders": {"control_width": (1, 4), "card_width": (0, 4)},
    "radius": {"control": (0, 24), "button": (0, 24), "card": (0, 32), "chip": (0, 32)},
}


class ThemeError(ValueError):
    """A theme document failed validation; ``errors`` lists every problem found."""

    def __init__(self, errors: list[str]):
        super().__init__("; ".join(errors))
        self.errors = errors


@dataclass(frozen=True)
class Palette:
    background: str
    surface: str
    field: str
    selected: str
    border: str
    strong_border: str
    text: str
    muted: str
    disabled: str
    accent: str
    on_accent: str
    danger: str
    success: str
    danger_fill: str
    on_danger: str


@dataclass(frozen=True)
class Typography:
    family: str
    body_pt: int
    small_pt: int
    section_pt: int
    heading_pt: int
    emphasis_weight: str


@dataclass(frozen=True)
class Metrics:
    xs: int
    sm: int
    md: int
    gutter: int
    xl: int
    control_min_height: int


@dataclass(frozen=True)
class Borders:
    control_width: int
    card_width: int


@dataclass(frozen=True)
class Radius:
    control: int
    button: int
    card: int
    chip: int


@dataclass(frozen=True)
class States:
    button_hover_border: str
    input_hover_border: str
    focus_border: str
    pressed_background: str
    primary_hover_border: str
    primary_focus_border: str
    selected_item_border: str
    hover_fill: str


@dataclass(frozen=True)
class Theme:
    id: str
    name: str
    description: str
    kind: str
    base_id: str | None
    palette: Palette
    typography: Typography
    spacing: Metrics
    density: str
    borders: Borders
    radius: Radius
    states: States
    provenance: Mapping[str, str] = field(default_factory=dict)
    schema_version: int = SCHEMA_VERSION

    def metrics(self) -> Metrics:
        """Spacing after density is applied (compact scales layout gaps, never the hit target)."""
        if self.density == "comfortable":
            return self.spacing
        scale = 0.75
        s = self.spacing
        return Metrics(
            xs=round(s.xs * scale),
            sm=round(s.sm * scale),
            md=round(s.md * scale),
            gutter=round(s.gutter * scale),
            xl=round(s.xl * scale),
            control_min_height=s.control_min_height,
        )

    def state_color(self, key: str) -> str:
        return getattr(self.palette, getattr(self.states, key))

    def fingerprint(self) -> str:
        return hashlib.sha256(canonical_json(self).encode("utf-8")).hexdigest()


# --------------------------------------------------------------------- parsing
def _reject_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ThemeError([f"duplicate JSON key '{key}'"])
        result[key] = value
    return result


def _reject_constant(name: str) -> Any:
    raise ThemeError([f"non-finite number '{name}' is not allowed"])


def parse_theme_json(text: str) -> Theme:
    """Parse and validate theme JSON text. Raises :class:`ThemeError` listing every problem."""
    if len(text.encode("utf-8")) > MAX_THEME_BYTES:
        raise ThemeError([f"theme file exceeds {MAX_THEME_BYTES // 1024} KiB"])
    try:
        data = json.loads(
            text, object_pairs_hook=_reject_duplicates, parse_constant=_reject_constant
        )
    except ThemeError:
        raise
    except json.JSONDecodeError as exc:
        raise ThemeError(
            [f"not valid JSON: {exc.msg} (line {exc.lineno}, column {exc.colno})"]
        ) from None
    return theme_from_dict(data)


def _check_section(
    data: Mapping[str, Any], name: str, keys: tuple[str, ...], errors: list[str]
) -> dict[str, Any]:
    section = data.get(name)
    if not isinstance(section, dict):
        errors.append(f"'{name}' must be an object")
        return {}
    for key in section:
        if key not in keys:
            errors.append(f"{name}.{key}: unknown key")
    for key in keys:
        if key not in section:
            errors.append(f"{name}.{key}: missing")
    return section


def _is_int(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def theme_from_dict(data: Any) -> Theme:
    errors: list[str] = []
    if not isinstance(data, dict):
        raise ThemeError(["theme must be a JSON object"])
    top = (
        "schema",
        "schema_version",
        "id",
        "name",
        "description",
        "kind",
        "base_id",
        "colors",
        "typography",
        "spacing",
        "density",
        "borders",
        "radius",
        "states",
        "provenance",
    )
    for key in data:
        if key not in top:
            errors.append(f"{key}: unknown top-level key")
    if data.get("schema") != SCHEMA:
        errors.append(f"schema must be '{SCHEMA}'")
    version = data.get("schema_version")
    if not _is_int(version):
        errors.append("schema_version must be an integer")
    elif version != SCHEMA_VERSION:
        errors.append(
            f"schema_version {version} is not supported (this prototype reads version {SCHEMA_VERSION}); "
            + (
                "it was written by a newer prototype"
                if version > SCHEMA_VERSION
                else "no migration exists"
            )
        )
    theme_id, name = data.get("id"), data.get("name")
    if not isinstance(theme_id, str) or not _ID.match(theme_id):
        errors.append("id must be lower-case letters, digits and hyphens (1-48 characters)")
    if not isinstance(name, str) or not 1 <= len(name.strip()) <= 60:
        errors.append("name must be 1-60 characters")
    description = data.get("description")
    if not isinstance(description, str) or len(description) > 600:
        errors.append("description must be text of at most 600 characters")
    kind = data.get("kind")
    if kind not in KINDS:
        errors.append(f"kind must be one of {KINDS}")
    base_id = data.get("base_id")
    if base_id is not None and (not isinstance(base_id, str) or not _ID.match(base_id)):
        errors.append("base_id must be null or a valid theme id")
    density = data.get("density")
    if density not in DENSITIES:
        errors.append(f"density must be one of {DENSITIES}")

    colors = _check_section(data, "colors", COLOR_ROLES, errors)
    for role in COLOR_ROLES:
        value = colors.get(role)
        if role in colors and (not isinstance(value, str) or not _HEX.match(value)):
            errors.append(f"colors.{role}: '{value}' is not a #RRGGBB colour")

    typo = _check_section(
        data,
        "typography",
        ("family", "body_pt", "small_pt", "section_pt", "heading_pt", "emphasis_weight"),
        errors,
    )
    family = typo.get("family")
    if "family" in typo and (not isinstance(family, str) or not _FAMILY.match(family)):
        errors.append(
            "typography.family must be 1-64 letters, digits, spaces, dots, hyphens or underscores"
        )
    if "emphasis_weight" in typo and typo["emphasis_weight"] not in WEIGHTS:
        errors.append(f"typography.emphasis_weight must be one of {WEIGHTS}")
    sections: dict[str, dict[str, Any]] = {"typography": typo}
    for section, keys in (
        ("spacing", tuple(RANGES["spacing"])),
        ("borders", tuple(RANGES["borders"])),
        ("radius", tuple(RANGES["radius"])),
    ):
        sections[section] = _check_section(data, section, keys, errors)
    for section, limits in RANGES.items():
        values = sections[section]
        for key, (low, high) in limits.items():
            if key in values and (not _is_int(values[key]) or not low <= values[key] <= high):
                errors.append(f"{section}.{key}: must be an integer from {low} to {high}")

    states = _check_section(data, "states", tuple(STATE_DEFAULTS), errors)
    for key in STATE_DEFAULTS:
        if key in states and states[key] not in COLOR_ROLES:
            errors.append(f"states.{key}: '{states[key]}' is not a colour role")

    provenance = data.get("provenance", {})
    if not isinstance(provenance, dict) or len(provenance) > 64:
        errors.append("provenance must be an object with at most 64 notes")
        provenance = {}
    else:
        for key, note in provenance.items():
            if not _NOTE_KEY.match(str(key)) or not isinstance(note, str) or len(note) > 240:
                errors.append(f"provenance.{key}: invalid key or note longer than 240 characters")
    if errors:
        raise ThemeError(errors)
    return Theme(
        id=theme_id,
        name=name.strip(),
        description=description,
        kind=kind,
        base_id=base_id,
        palette=Palette(**{role: colors[role].upper() for role in COLOR_ROLES}),
        typography=Typography(
            **{
                key: typo[key]
                for key in (
                    "family",
                    "body_pt",
                    "small_pt",
                    "section_pt",
                    "heading_pt",
                    "emphasis_weight",
                )
            }
        ),
        spacing=Metrics(**{key: sections["spacing"][key] for key in RANGES["spacing"]}),
        density=density,
        borders=Borders(**{key: sections["borders"][key] for key in RANGES["borders"]}),
        radius=Radius(**{key: sections["radius"][key] for key in RANGES["radius"]}),
        states=States(**{key: states[key] for key in STATE_DEFAULTS}),
        provenance=dict(provenance),
    )


def theme_to_dict(theme: Theme) -> dict[str, Any]:
    def section(obj: Any) -> dict[str, Any]:
        return {f.name: getattr(obj, f.name) for f in fields(obj)}

    return {
        "schema": SCHEMA,
        "schema_version": theme.schema_version,
        "id": theme.id,
        "name": theme.name,
        "description": theme.description,
        "kind": theme.kind,
        "base_id": theme.base_id,
        "colors": section(theme.palette),
        "typography": section(theme.typography),
        "spacing": section(theme.spacing),
        "density": theme.density,
        "borders": section(theme.borders),
        "radius": section(theme.radius),
        "states": section(theme.states),
        "provenance": dict(theme.provenance),
    }


def canonical_json(theme: Theme) -> str:
    return json.dumps(theme_to_dict(theme), indent=2, ensure_ascii=True) + "\n"


_WINDOWS_RESERVED = frozenset(
    [
        "con",
        "prn",
        "aux",
        "nul",
        *(f"com{i}" for i in range(1, 10)),
        *(f"lpt{i}" for i in range(1, 10)),
    ]
)


def slugify(name: str) -> str:
    """File-safe theme id. Windows device names (``con``, ``nul`` ...) would address a device, not a file."""
    slug = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")[:48].strip("-") or "theme"
    return f"{slug}-theme" if slug in _WINDOWS_RESERVED else slug


# ------------------------------------------------------------------- contrast
def _channel(value: int) -> float:
    c = value / 255
    return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4


def luminance(hex_color: str) -> float:
    h = hex_color.lstrip("#")
    r, g, b = (int(h[i : i + 2], 16) for i in (0, 2, 4))
    return 0.2126 * _channel(r) + 0.7152 * _channel(g) + 0.0722 * _channel(b)


def contrast_ratio(foreground: str, background: str) -> float:
    """WCAG 2.x contrast ratio between two ``#RRGGBB`` colours."""
    a, b = luminance(foreground), luminance(background)
    hi, lo = max(a, b), min(a, b)
    return (hi + 0.05) / (lo + 0.05)


@dataclass(frozen=True)
class ContrastCheck:
    label: str
    foreground: str
    background: str
    minimum: float
    ratio: float

    @property
    def passed(self) -> bool:
        return self.ratio >= self.minimum


def contrast_checks(theme: Theme) -> tuple[ContrastCheck, ...]:
    """Every readability / visibility pair the prototype relies on (targets from UX-850-C TOKENS)."""
    p = theme.palette
    focus, hover = theme.state_color("focus_border"), theme.state_color("input_hover_border")
    primary_ring = theme.state_color("primary_focus_border")
    selected_ring = theme.state_color("selected_item_border")
    pairs: tuple[tuple[str, str, str, float], ...] = (
        ("Text on background", p.text, p.background, 4.5),
        ("Text on surface", p.text, p.surface, 4.5),
        ("Text on field", p.text, p.field, 4.5),
        ("Text on selected", p.text, p.selected, 4.5),
        ("Muted on surface", p.muted, p.surface, 4.5),
        ("Muted on selected", p.muted, p.selected, 4.5),
        ("Primary action label", p.on_accent, p.accent, 7.0),
        ("Danger action label", p.on_danger, p.danger_fill, 4.5),
        ("Accent on surface", p.accent, p.surface, 3.0),
        ("Accent on field", p.accent, p.field, 3.0),
        ("Strong border on surface", p.strong_border, p.surface, 3.0),
        ("Strong border on field", p.strong_border, p.field, 3.0),
        ("Danger on field", p.danger, p.field, 4.5),
        ("Success on field", p.success, p.field, 4.5),
        ("Disabled text on selected", p.disabled, p.selected, 3.0),
        ("Focus edge on surface", focus, p.surface, 3.0),
        ("Focus edge on field", focus, p.field, 3.0),
        ("Input hover edge on field", hover, p.field, 3.0),
        ("Primary focus edge on background", primary_ring, p.background, 3.0),
        ("Selected-item edge on selected", selected_ring, p.selected, 3.0),
    )
    return tuple(
        ContrastCheck(label, fg, bg, need, contrast_ratio(fg, bg)) for label, fg, bg, need in pairs
    )


def failing_checks(theme: Theme) -> tuple[ContrastCheck, ...]:
    return tuple(check for check in contrast_checks(theme) if not check.passed)


# ---------------------------------------------------------------------- editor
class ThemeEditor:
    """Pure draft editor behind the Theme Studio.

    Holds the loaded ``base`` theme and a validated ``draft``. Edits are applied to a plain
    dict; an invalid edit keeps the last valid draft and reports ``errors`` so the UI can
    show the problem without losing work. Nothing here touches disk.
    """

    SECTIONS = ("colors", "typography", "spacing", "borders", "radius", "states")

    def __init__(self, theme: Theme):
        self.load(theme)

    def load(self, theme: Theme) -> None:
        self.base = theme
        self._data = theme_to_dict(theme)
        if theme.kind == "reference":
            # Editing never silently mutates a shipped preset: the first edit yields a user copy.
            self._data.update(
                kind="user",
                base_id=theme.id,
                id=f"{theme.id}-copy"[:48],
                name=f"{theme.name} (edited copy)"[:60],
            )
        self.draft = theme
        self.errors: list[str] = []

    @property
    def is_dirty(self) -> bool:
        return self.draft != self.base or bool(self.errors)

    @property
    def is_reference(self) -> bool:
        return self.draft.kind == "reference"

    def set(self, section: str, key: str, value: Any) -> bool:
        """Set one value (``density`` uses section ``""``). Returns True if the draft is valid."""
        if section == "":
            if key != "density":
                raise KeyError(key)
            self._data["density"] = value
        else:
            if section not in self.SECTIONS or key not in self._data[section]:
                raise KeyError(f"{section}.{key}")
            self._data[section][key] = value
        return self._revalidate()

    def _revalidate(self) -> bool:
        try:
            self.draft = theme_from_dict(self._data)
        except ThemeError as exc:
            self.errors = exc.errors
            return False
        self.errors = []
        return True

    def revert(self) -> None:
        """Discard unsaved edits and return to the loaded theme."""
        self.load(self.base)

    def rename(self, name: str) -> bool:
        self._data["name"] = name
        self._data["id"] = slugify(name)
        return self._revalidate()


# ------------------------------------------------------------------ stylesheet
@dataclass(frozen=True)
class _Pad:
    btn_y: int
    btn_x: int
    inp_y: int
    inp_x: int
    disc_y: int
    disc_x: int
    nav_y: int
    nav_x: int


_PAD = {"comfortable": _Pad(2, 14, 3, 8, 4, 12, 10, 12), "compact": _Pad(0, 10, 1, 6, 2, 10, 6, 10)}


def _forced(selector: str, pseudo: str) -> str:
    """``selector:pseudo`` plus an equivalent ``[state='pseudo']`` form so the Theme Studio can
    show hover/focus/pressed appearance statically (real pseudo-states cannot be forced)."""
    base, sep, sub = selector.partition("::")
    forced = f"{base}[state='{pseudo}']" + (f"::{sub}" if sep else "")
    return f"{selector}:{pseudo}, {forced}"


def build_stylesheet(theme: Theme, asset_dir: Path) -> str:
    """Complete widget stylesheet for ``theme`` (no GUI access).

    Plain widgets are transparent so labels never paint opaque rectangles over cards. Every
    interactive control keeps a constant border width and only changes colour on hover/focus,
    so focus never shifts layout.
    """
    c, r, t, b = theme.palette, theme.radius, theme.typography, theme.borders
    s, pad = theme.spacing, _PAD[theme.density]
    bw, cw, emph, h = (
        b.control_width,
        b.card_width,
        t.emphasis_weight,
        theme.spacing.control_min_height,
    )
    hover_b, in_hover = (
        theme.state_color("button_hover_border"),
        theme.state_color("input_hover_border"),
    )
    focus_b, pressed = theme.state_color("focus_border"), theme.state_color("pressed_background")
    p_hover, p_focus = (
        theme.state_color("primary_hover_border"),
        theme.state_color("primary_focus_border"),
    )
    sel_b, hover_fill = theme.state_color("selected_item_border"), theme.state_color("hover_fill")
    asset = lambda name: 'url("' + (asset_dir / name).as_posix() + '")'  # noqa: E731
    up, down, chevron, check = (
        asset("arrow_up.svg"),
        asset("arrow_down.svg"),
        asset("chevron_down.svg"),
        asset("check.svg"),
    )
    seg_h = max(24, h - 4)
    inputs = "QLineEdit, QPlainTextEdit, QSpinBox, QDoubleSpinBox, QComboBox"
    return f"""
    QWidget {{ color: {c.text}; background: transparent; font-family: '{t.family}', {FALLBACK_FONT}; font-size: {t.body_pt}pt; }}
    QMainWindow, QDialog, QMessageBox {{ background: {c.background}; }}
    QFrame[role='preview-surface'] {{ background: {c.background}; border: {cw}px solid {c.border}; border-radius: {r.card}px; }}
    QToolTip {{ color: {c.text}; background: {c.field}; border: {bw}px solid {c.strong_border}; border-radius: {r.control}px; padding: 4px 6px; }}

    QFrame[role='card'] {{ background: {c.surface}; border: {cw}px solid {c.border}; border-radius: {r.card}px; }}
    QFrame[role='notice'] {{ background: {c.field}; border: {bw}px solid {c.strong_border}; border-radius: {max(0, r.card - 2)}px; }}
    QFrame[role='notice'][level='warning'] {{ border-color: {c.accent}; }}
    QFrame[role='notice'][level='blocked'] {{ border-color: {c.danger}; }}
    QFrame[role='notice'][level='success'] {{ border-color: {c.success}; }}
    QLabel[role='tile'] {{ background: {c.field}; border: {bw}px dashed {c.strong_border}; border-radius: {r.control}px; padding: 8px; }}
    QLabel[role='tile'][selected='true'] {{ border: {bw}px solid {sel_b}; }}

    QFrame[role='shot'] {{ background: {c.field}; border: {bw}px solid {c.border}; border-radius: {r.card}px; }}
    QFrame[role='shot']:hover {{ border-color: {hover_b}; }}
    QFrame[role='shot']:focus {{ border-color: {focus_b}; }}
    QFrame[role='shot'][invalid='true'] {{ border-color: {c.danger}; }}
    QFrame[role='shot'][selected='true'] {{ background: {c.selected}; border-color: {sel_b}; }}

    QLabel[role='muted'] {{ color: {c.muted}; }}
    QLabel[role='muted'][level='warning'] {{ color: {c.accent}; }}
    QLabel[role='heading'] {{ font-size: {t.heading_pt}pt; font-weight: {emph}; }}
    QLabel[role='section'] {{ font-size: {t.section_pt}pt; font-weight: {emph}; }}
    QLabel[role='capsule'] {{ font-size: {t.small_pt}pt; font-weight: {emph}; color: {c.accent}; border: 1px solid {c.accent}; border-radius: {r.chip}px; padding: 3px 12px; }}
    QLabel[role='chip'] {{ font-weight: {emph}; background: {c.field}; border: {bw}px solid {c.strong_border}; border-radius: {r.chip}px; padding: 2px 12px; }}
    QLabel[role='chip'][level='warning'] {{ border-color: {c.accent}; color: {c.accent}; }}
    QLabel[role='chip'][level='blocked'] {{ border-color: {c.danger}; color: {c.danger}; }}
    QLabel[role='chip'][level='success'] {{ border-color: {c.success}; color: {c.success}; }}

    QPushButton {{ min-height: {h}px; background: {c.selected}; border: {bw}px solid {c.strong_border}; border-radius: {r.button}px; padding: {pad.btn_y}px {pad.btn_x}px; }}
    {_forced("QPushButton", "hover")} {{ border-color: {hover_b}; }}
    {_forced("QPushButton", "pressed")} {{ background: {pressed}; }}
    {_forced("QPushButton", "focus")} {{ border-color: {focus_b}; }}
    QPushButton:disabled {{ color: {c.disabled}; background: {c.surface}; border-color: {c.border}; }}
    QPushButton[role='primary'] {{ background: {c.accent}; color: {c.on_accent}; border-color: {c.accent}; font-weight: {emph}; }}
    {_forced("QPushButton[role='primary']", "hover")} {{ border-color: {p_hover}; }}
    {_forced("QPushButton[role='primary']", "focus")} {{ border-color: {p_focus}; }}
    QPushButton[role='primary']:disabled {{ color: {c.disabled}; background: {c.surface}; border-color: {c.border}; }}
    QPushButton[role='danger'] {{ background: {c.danger_fill}; color: {c.on_danger}; border-color: {c.danger_fill}; font-weight: {emph}; }}
    {_forced("QPushButton[role='danger']", "hover")} {{ border-color: {p_hover}; }}
    {_forced("QPushButton[role='danger']", "focus")} {{ border-color: {p_focus}; }}
    QPushButton[role='danger']:disabled {{ color: {c.disabled}; background: {c.surface}; border-color: {c.border}; }}

    QToolButton {{ background: transparent; border: {bw}px solid transparent; border-radius: {r.control}px; padding: 2px 8px; }}
    QToolButton:hover, QToolButton:focus {{ border-color: {focus_b}; }}
    QToolButton:disabled {{ color: {c.disabled}; }}
    QToolButton[role='reset'] {{ font-size: {t.body_pt + 3}pt; padding: 0 6px; }}
    QPushButton[role='disclosure'] {{ background: {c.field}; border-color: {c.border}; padding: {pad.disc_y}px {pad.disc_x}px; font-weight: {emph}; text-align: left; }}
    QPushButton[role='disclosure']:hover, QPushButton[role='disclosure']:focus {{ border-color: {focus_b}; }}
    QPushButton[role='disclosure']:checked {{ border-color: {c.strong_border}; }}

    {inputs}, QTableWidget {{
        background: {c.field}; border: {bw}px solid {c.border}; border-radius: {r.control}px; padding: {pad.inp_y}px {pad.inp_x}px;
        selection-background-color: {c.accent}; selection-color: {c.on_accent}; }}
    QLineEdit, QSpinBox, QDoubleSpinBox, QComboBox {{ min-height: {h}px; }}
    {", ".join(_forced(sel, "hover") for sel in inputs.split(", "))} {{ border-color: {in_hover}; }}
    {", ".join(_forced(sel, "focus") for sel in (*inputs.split(", "), "QTableWidget"))} {{ border-color: {focus_b}; }}
    QLineEdit:disabled, QPlainTextEdit:disabled, QSpinBox:disabled, QDoubleSpinBox:disabled, QComboBox:disabled {{ color: {c.disabled}; border-color: {c.border}; }}
    QLineEdit[invalid='true'], QSpinBox[invalid='true'] {{ border-color: {c.danger}; }}
    QPlainTextEdit[readOnly='true'] {{ background: {c.field}; border-color: {c.border}; }}

    QSpinBox, QDoubleSpinBox {{ padding-right: 26px; }}
    QSpinBox::up-button, QDoubleSpinBox::up-button {{ subcontrol-origin: border; subcontrol-position: top right; width: 22px; margin: 2px 2px 0 0; border: none; border-top-right-radius: {max(0, r.control - 2)}px; background: {c.selected}; }}
    QSpinBox::down-button, QDoubleSpinBox::down-button {{ subcontrol-origin: border; subcontrol-position: bottom right; width: 22px; margin: 0 2px 2px 0; border: none; border-bottom-right-radius: {max(0, r.control - 2)}px; background: {c.selected}; }}
    QSpinBox::up-button:hover, QDoubleSpinBox::up-button:hover, QSpinBox::down-button:hover, QDoubleSpinBox::down-button:hover {{ background: {c.border}; }}
    QSpinBox::up-arrow, QDoubleSpinBox::up-arrow {{ image: {up}; width: 10px; height: 10px; }}
    QSpinBox::down-arrow, QDoubleSpinBox::down-arrow {{ image: {down}; width: 10px; height: 10px; }}

    QComboBox {{ padding-right: 30px; }}
    QComboBox::drop-down {{ subcontrol-origin: border; subcontrol-position: center right; width: 28px; border: none; }}
    QComboBox::down-arrow {{ image: {chevron}; width: 12px; height: 12px; }}
    QComboBox QAbstractItemView {{ background: {c.surface}; border: {bw}px solid {c.strong_border}; border-radius: {r.control}px; padding: 4px; outline: 0; selection-background-color: {c.selected}; selection-color: {c.text}; }}

    QCheckBox {{ spacing: 8px; }}
    QCheckBox::indicator {{ width: 16px; height: 16px; border: {bw}px solid {c.strong_border}; border-radius: {max(0, r.control - 2)}px; background: {c.field}; }}
    {_forced("QCheckBox::indicator", "hover")} {{ border-color: {focus_b}; }}
    QCheckBox::indicator:checked {{ background: {c.accent}; border-color: {c.accent}; image: {check}; }}
    QCheckBox::indicator:disabled {{ border-color: {c.border}; }}
    {_forced("QCheckBox", "focus")} {{ color: {focus_b}; }}

    QTableWidget {{ gridline-color: {c.border}; padding: 2px; }}
    QTableWidget::item {{ padding: 4px; }}
    QTableWidget::item:selected {{ background: {c.selected}; color: {c.text}; }}
    QTableCornerButton::section {{ background: {c.surface}; border: none; }}
    QHeaderView {{ background: transparent; }}
    QHeaderView::section {{ background: {c.surface}; color: {c.text}; border: none; border-bottom: 1px solid {c.border}; padding: 6px; font-weight: {emph}; }}

    QListWidget[role='nav'] {{ background: {c.surface}; border: {cw}px solid {c.border}; border-radius: {r.card}px; padding: 6px; outline: 0; }}
    QListWidget[role='nav']:focus {{ border-color: {focus_b}; }}
    QListWidget[role='nav']::item {{ padding: {pad.nav_y}px {pad.nav_x}px; margin: 2px 0; border: {bw}px solid transparent; border-radius: {r.control}px; }}
    QListWidget[role='nav']::item:hover {{ background: {hover_fill}; }}
    QListWidget[role='nav']::item:selected {{ background: {c.selected}; color: {c.text}; border-color: {sel_b}; font-weight: {emph}; }}

    QScrollBar:vertical {{ background: transparent; width: 12px; margin: 2px; }}
    QScrollBar:horizontal {{ background: transparent; height: 12px; margin: 2px; }}
    QScrollBar::handle:vertical {{ background: {c.strong_border}; border-radius: 4px; min-height: 28px; }}
    QScrollBar::handle:horizontal {{ background: {c.strong_border}; border-radius: 4px; min-width: 28px; }}
    QScrollBar::handle:hover {{ background: {c.accent}; }}
    QScrollBar::add-line, QScrollBar::sub-line {{ width: 0px; height: 0px; }}
    QScrollBar::add-page, QScrollBar::sub-page {{ background: transparent; }}

    QPushButton[role='segment'] {{ min-height: {seg_h}px; background: {c.field}; border-color: {c.border}; padding: 2px 10px; }}
    QPushButton[role='segment']:hover {{ border-color: {hover_b}; }}
    QPushButton[role='segment']:checked {{ background: {c.selected}; border-color: {sel_b}; font-weight: {emph}; }}
    QToolButton[role='zoom'] {{ background: {c.selected}; border: {bw}px solid {c.strong_border}; border-radius: {r.button}px; min-width: 28px; min-height: 24px; padding: 2px 8px; font-weight: {emph}; }}
    QToolButton[role='zoom']:hover, QToolButton[role='zoom']:focus {{ border-color: {focus_b}; }}
    QToolButton[role='zoom']:checked {{ border-color: {sel_b}; background: {c.surface}; }}
    QToolButton[glyph='true'] {{ font-size: {t.body_pt + 3}pt; padding: 0 8px; }}
    QToolButton[role='zoom']:disabled {{ color: {c.disabled}; background: {c.surface}; border-color: {c.border}; }}
    QSlider::groove:horizontal {{ height: 6px; background: {c.field}; border: 1px solid {c.border}; border-radius: 4px; }}
    QSlider::sub-page:horizontal {{ background: {c.selected}; border-radius: 4px; }}
    QSlider::handle:horizontal {{ width: 14px; height: 14px; margin: -6px 0; background: {c.accent}; border: {bw}px solid {c.on_accent}; border-radius: 9px; }}
    QSlider::handle:horizontal:hover, QSlider::handle:horizontal:focus {{ border-color: {c.text}; }}
    QFrame[role='dockbar'] {{ background: {c.surface}; border: {cw}px solid {c.border}; border-radius: {r.card}px; }}
    QGraphicsView[role='viewer'] {{ background: {c.field}; border: {bw}px solid {c.border}; border-radius: {r.control}px; }}
    QGraphicsView[role='viewer']:focus {{ border-color: {focus_b}; }}
    QDockWidget {{ background: {c.background}; }}
    QMainWindow::separator {{ background: transparent; width: {max(4, s.sm)}px; height: {max(4, s.sm)}px; }}
    QMainWindow::separator:hover {{ background: {c.accent}; border-radius: 3px; }}
    QSplitter::handle {{ background: {c.border}; border-radius: 2px; margin: 4px 2px; }}
    QSplitter::handle:hover {{ background: {c.accent}; }}
    QStatusBar {{ color: {c.muted}; }}
    QStatusBar::item {{ border: none; }}
    QSizeGrip {{ background: transparent; }}
    """


def iter_hex_literals(text: str) -> Iterator[str]:
    yield from re.findall(r"#[0-9A-Fa-f]{6}\b", text)


def with_density(theme: Theme, density: str) -> Theme:
    return replace(theme, density=density)
