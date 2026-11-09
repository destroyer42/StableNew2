"""Pure-Python theme checks: contrast, geometry tokens, assets and stylesheet hygiene."""

from __future__ import annotations

from pathlib import Path
import re
import unittest

from stablenew_qt_proto.tokens import (
    ASSET_DIR, ASSET_FILES, COLORS, CONTRAST_PAIRS, RADIUS, contrast_ratio, make_stylesheet,
)


class ThemeTests(unittest.TestCase):
    def test_contrast_pairs_meet_their_minimums(self):
        for label, fg, bg, minimum in CONTRAST_PAIRS:
            self.assertGreaterEqual(contrast_ratio(fg, bg), minimum, label)

    def test_contrast_function_known_values(self):
        self.assertAlmostEqual(contrast_ratio("#FFFFFF", "#000000"), 21.0, places=1)
        self.assertAlmostEqual(contrast_ratio("#777777", "#777777"), 1.0, places=3)

    def test_background_is_blue_not_black(self):
        for name in ("background", "surface", "field", "selected"):
            h = getattr(COLORS, name).lstrip("#")
            r, g, b = (int(h[i : i + 2], 16) for i in (0, 2, 4))
            self.assertGreater(b, r + 40, name)
            self.assertGreater(b, g, name)

    def test_geometry_is_rounded(self):
        for value in (RADIUS.control, RADIUS.button, RADIUS.card, RADIUS.chip):
            self.assertGreaterEqual(value, 8)

    def test_assets_exist_and_are_referenced(self):
        css = make_stylesheet()
        for name in ASSET_FILES:
            self.assertTrue((Path(ASSET_DIR) / name).is_file(), name)
            self.assertIn(name, css)

    def test_plain_widgets_are_transparent(self):
        css = make_stylesheet()
        first_rule = re.search(r"QWidget\s*\{([^}]*)\}", css).group(1)
        self.assertIn("background: transparent", first_rule)
        # No selector list may paint a bare QWidget/QLabel/QCheckBox opaque.
        for selectors, body in re.findall(r"([^{}]+)\{([^}]*)\}", css):
            names = [s.strip() for s in selectors.split(",")]
            if any(n in {"QWidget", "QLabel", "QCheckBox", "QFrame"} for n in names):
                self.assertNotRegex(body, r"background:\s*#", selectors)

    def test_controls_keep_constant_border_width(self):
        css = make_stylesheet()
        for selector in ("QLineEdit:focus", "QPushButton:focus", "QComboBox:focus"):
            body = re.search(re.escape(selector) + r"[^{]*\{([^}]*)\}", css).group(1)
            self.assertNotRegex(body, r"border:\s*\d", "focus must only change border-color")

    def test_stylesheet_braces_balance(self):
        css = make_stylesheet()
        self.assertEqual(css.count("{"), css.count("}"))


if __name__ == "__main__":
    unittest.main()
