"""Static tests: no hard-coded theme values outside the theme builder, and component styling is complete."""

from __future__ import annotations

import re
import unittest
from pathlib import Path

from stablenew_qt_proto.theme import STATE_DEFAULTS, build_stylesheet
from stablenew_qt_proto.tokens import ASSET_DIR, reference_themes

PACKAGE = Path(__file__).resolve().parents[1] / "stablenew_qt_proto"
SOURCES = sorted(p for p in PACKAGE.glob("*.py"))
# The only module allowed to spell out CSS property names with literal values.
BUILDER = "theme.py"
# Modules that may build a one-off inline stylesheet, but only from theme values (f-string placeholders).
INLINE_FROM_TOKENS = {"gallery.py", "theme_studio.py", "output_display.py"}
CSS_PROPERTIES = (
    "font-size",
    "font-family",
    "font-weight",
    "border-radius",
    "border:",
    "border-color",
    "background:",
    "color:",
    "padding:",
)


def code_lines(path: Path):
    for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        stripped = line.strip()
        if stripped.startswith("#") or stripped.startswith('"""'):
            continue
        yield number, line


class NoHardCodedThemeValues(unittest.TestCase):
    def test_no_hex_colour_literals_in_python_sources(self):
        for path in SOURCES:
            for number, line in code_lines(path):
                self.assertIsNone(
                    re.search(r"#[0-9A-Fa-f]{6}\b", line), f"{path.name}:{number}: {line.strip()}"
                )

    def test_no_rgb_named_colour_or_qcolor_literals(self):
        for path in SOURCES:
            for number, line in code_lines(path):
                self.assertNotRegex(line, r"\b(rgb|rgba|hsl)\(", f"{path.name}:{number}")
                self.assertNotRegex(line, r"QColor\(\s*[\"'0-9]", f"{path.name}:{number}")
                self.assertNotRegex(line, r"Qt\.GlobalColor", f"{path.name}:{number}")

    def test_css_properties_with_literal_values_live_only_in_the_builder(self):
        for path in SOURCES:
            if path.name == BUILDER:
                continue
            for number, line in code_lines(path):
                if (
                    any(prop in line for prop in CSS_PROPERTIES)
                    and "setProperty" not in line
                    and not line.lstrip().startswith("def ")
                    and ('"' in line or "'" in line)
                ):
                    self.assertIn(
                        path.name, INLINE_FROM_TOKENS, f"{path.name}:{number}: {line.strip()}"
                    )
                    self.assertIn(
                        "{",
                        line,
                        f"inline style must interpolate theme values: {path.name}:{number}",
                    )

    def test_no_literal_fonts_or_point_sizes(self):
        for path in SOURCES:
            for number, line in code_lines(path):
                self.assertNotRegex(line, r"\bQFont\(", f"{path.name}:{number}")
                self.assertNotRegex(
                    line, r"setPointSize|setFamily|setPixelSize", f"{path.name}:{number}"
                )

    def test_theme_json_files_are_the_only_colour_sources(self):
        themes = sorted((PACKAGE / "themes").glob("*.theme.json"))
        self.assertEqual(
            {p.name for p in themes}, {"blue-modern.theme.json", "concept-a.theme.json"}
        )


class ComponentStyleConsistency(unittest.TestCase):
    def setUp(self):
        self.css = {
            tid: build_stylesheet(theme, ASSET_DIR) for tid, theme in reference_themes().items()
        }

    def test_every_role_used_by_a_component_has_a_style_rule(self):
        used: set[str] = set()
        for path in SOURCES:
            used.update(
                re.findall(
                    r"""setProperty\(\s*["']role["']\s*,\s*["']([a-z-]+)["']""",
                    path.read_text(encoding="utf-8"),
                )
            )
        self.assertGreaterEqual(len(used), 12)
        for tid, css in self.css.items():
            for role in sorted(used):
                self.assertIn(
                    f"[role='{role}']", css, f"{tid}: role '{role}' has no stylesheet rule"
                )

    def test_every_notice_and_chip_level_is_styled(self):
        from stablenew_qt_proto.components import LEVELS

        for tid, css in self.css.items():
            for level in LEVELS:
                if level == "info":
                    continue  # the default look
                self.assertIn(f"QFrame[role='notice'][level='{level}']", css, tid)
                self.assertIn(f"QLabel[role='chip'][level='{level}']", css, tid)

    def test_every_interactive_control_defines_hover_focus_and_disabled(self):
        required = {
            "QPushButton": ("hover", "focus", "disabled"),
            "QPushButton[role='primary']": ("hover", "focus", "disabled"),
            "QPushButton[role='danger']": ("hover", "focus", "disabled"),
            "QLineEdit": ("hover", "focus", "disabled"),
            "QComboBox": ("hover", "focus", "disabled"),
            "QSpinBox": ("hover", "focus", "disabled"),
            "QPlainTextEdit": ("hover", "focus", "disabled"),
            "QCheckBox": ("focus",),
            "QToolButton": ("hover", "focus", "disabled"),
        }
        for tid, css in self.css.items():
            for selector, states in required.items():
                for state in states:
                    self.assertRegex(
                        css, re.escape(selector) + r"[^{}]*:" + state, f"{tid}: {selector}:{state}"
                    )

    def test_focus_and_hover_never_change_border_width_or_layout(self):
        for tid, css in self.css.items():
            for selectors, body in re.findall(r"([^{}]+)\{([^}]*)\}", css):
                if (
                    re.search(r":(hover|focus|pressed)|\[state=", selectors)
                    and "::" not in selectors
                ):
                    self.assertNotRegex(
                        body,
                        r"border:\s*\d|border-width|padding|margin|min-height",
                        f"{tid}: {selectors.strip()}",
                    )

    def test_state_selectors_are_driven_by_state_roles_not_literals(self):
        for tid, theme in reference_themes().items():
            css = self.css[tid]
            for key, role in STATE_DEFAULTS.items():
                self.assertEqual(getattr(theme.states, key), role)
            self.assertIn(theme.palette.accent, css)

    def test_geometry_is_theme_driven(self):
        for tid, theme in reference_themes().items():
            for radius in {
                theme.radius.control,
                theme.radius.button,
                theme.radius.card,
                theme.radius.chip,
            }:
                self.assertIn(f"border-radius: {radius}px", self.css[tid])
            self.assertIn(f"min-height: {theme.spacing.control_min_height}px", self.css[tid])


if __name__ == "__main__":
    unittest.main()
