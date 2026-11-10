"""Pure theme-contract tests: loading, strict validation, serialisation, editor, contrast, stylesheet."""

from __future__ import annotations

import copy
import hashlib
import json
import re
import unittest
from dataclasses import replace
from pathlib import Path

from stablenew_qt_proto.theme import (
    COLOR_ROLES, MAX_THEME_BYTES, SCHEMA_VERSION, STATE_DEFAULTS, ThemeEditor, ThemeError,
    build_stylesheet, canonical_json, contrast_checks, contrast_ratio, failing_checks,
    parse_theme_json, theme_to_dict,
)
from stablenew_qt_proto.tokens import ASSET_DIR, THEME_DIR, reference_themes

# Pinned bytes of the shipped reference presets: a deliberate preset change must update these hashes.
REFERENCE_SHA256 = {
    "blue-modern.theme.json": "bae781b23ba6d5b10d2662f9f161ec678f63ebca0f84d762f3285f9bd1e27217",
    "concept-a.theme.json": "ea290b8d0d0eec4b7d7d187391cd3071a945d95a4f6d836d9c04e036fae86ce9",
}
REPO_ROOT = Path(__file__).resolve().parents[3]
TOKENS_MD = REPO_ROOT / "docs" / "research" / "stablenew-experience" / "ux850-c" / "TOKENS.md"

# Accepted prototype v0.3.0 Blue palette (tokens.py of the verbatim import).
V03_BLUE = {
    "background": "#0E2A55", "surface": "#163F7C", "field": "#0A2147", "selected": "#1E5AA8",
    "border": "#3E70B8", "strong_border": "#8FB4E8", "text": "#FFFFFF", "muted": "#C6D8F2",
    "disabled": "#9DB5D6", "accent": "#FFC805", "on_accent": "#0A1A33", "danger": "#FF8A91", "success": "#7EE0A8",
}


def blue():
    return reference_themes()["blue-modern"]


def concept():
    return reference_themes()["concept-a"]


def raw(theme=None) -> dict:
    return copy.deepcopy(theme_to_dict(theme or blue()))


def errors_for(data) -> list[str]:
    try:
        parse_theme_json(json.dumps(data))
    except ThemeError as exc:
        return exc.errors
    return []


class ReferencePresetTests(unittest.TestCase):
    def test_two_reference_presets_load(self):
        themes = reference_themes()
        self.assertEqual(set(themes), {"blue-modern", "concept-a"})
        for theme in themes.values():
            self.assertEqual(theme.kind, "reference")
            self.assertEqual(theme.schema_version, SCHEMA_VERSION)

    def test_reference_files_are_pinned(self):
        for name, pinned in REFERENCE_SHA256.items():
            content = (THEME_DIR / name).read_bytes().replace(bytes([13, 10]), bytes([10]))  # autocrlf-safe
            digest = hashlib.sha256(content).hexdigest()
            self.assertEqual(digest, pinned, f"{name} changed: update the pin only for a deliberate preset change")

    def test_blue_modern_matches_accepted_prototype_values(self):
        for role, value in V03_BLUE.items():
            self.assertEqual(getattr(blue().palette, role), value, role)
        self.assertEqual((blue().radius.control, blue().radius.button, blue().radius.card, blue().radius.chip), (8, 10, 14, 12))

    def test_presets_meet_every_contrast_requirement(self):
        for theme in reference_themes().values():
            self.assertEqual(failing_checks(theme), (), theme.id)
            self.assertGreaterEqual(len(contrast_checks(theme)), 20)

    def test_concept_a_verified_values_appear_in_research_tokens(self):
        if not TOKENS_MD.is_file():
            self.skipTest("research TOKENS.md not present in this checkout")
        text = TOKENS_MD.read_text(encoding="utf-8").upper()
        p = concept().palette
        for value in (p.background, p.surface, p.selected, p.border, p.text, p.muted, p.disabled, p.accent, p.danger_fill):
            self.assertIn(value, text, value)

    def test_concept_a_declares_what_is_not_verified(self):
        notes = concept().provenance
        for key in ("colors.field", "colors.danger", "colors.success", "radius"):
            self.assertRegex(notes[key], r"(?i)mapped|invented")
        self.assertIn("NOT verified", concept().description)

    def test_round_trip_is_lossless_and_canonical(self):
        for theme in reference_themes().values():
            text = canonical_json(theme)
            self.assertEqual(parse_theme_json(text), theme)
            self.assertEqual(canonical_json(parse_theme_json(text)), text)
            self.assertEqual(theme.fingerprint(), parse_theme_json(text).fingerprint())


class StrictValidationTests(unittest.TestCase):
    def test_valid_document_has_no_errors(self):
        self.assertEqual(errors_for(raw()), [])

    def test_unknown_and_missing_keys_are_errors(self):
        data = raw()
        data["surprise"] = 1
        data["colors"]["glow"] = "#FFFFFF"
        del data["colors"]["accent"]
        del data["radius"]["chip"]
        errors = errors_for(data)
        self.assertTrue(any("surprise" in e for e in errors))
        self.assertTrue(any("colors.glow" in e for e in errors))
        self.assertTrue(any("colors.accent: missing" in e for e in errors))
        self.assertTrue(any("radius.chip: missing" in e for e in errors))

    def test_all_problems_are_reported_together(self):
        data = raw()
        data["colors"]["accent"] = "red"
        data["spacing"]["md"] = -1
        data["density"] = "tight"
        self.assertGreaterEqual(len(errors_for(data)), 3)

    def test_colour_format(self):
        for bad in ("FFC805", "#FFC80", "#FFC8055", "#GGGGGG", "rgb(1,2,3)", 0xFFC805, None, "#FFC805; x"):
            data = raw()
            data["colors"]["accent"] = bad
            self.assertTrue(errors_for(data), repr(bad))
        data = raw()
        data["colors"]["accent"] = "#ffc806"
        self.assertEqual(parse_theme_json(json.dumps(data)).palette.accent, "#FFC806")

    def test_numeric_ranges_and_types(self):
        cases = (("spacing", "md", 33), ("spacing", "control_min_height", 23), ("borders", "control_width", 0),
                 ("radius", "card", 33), ("typography", "body_pt", 7), ("typography", "body_pt", 10.5),
                 ("spacing", "xs", True), ("spacing", "xs", "4"))
        for section, key, value in cases:
            data = raw()
            data[section][key] = value
            self.assertTrue(errors_for(data), (section, key, value))

    def test_font_family_cannot_inject_stylesheet_syntax(self):
        for bad in ("Segoe UI; } QWidget { color: red", "A{B}", "x'y", 'x"y', "", "a" * 65, "\\ttf", "../x"):
            data = raw()
            data["typography"]["family"] = bad
            self.assertTrue(errors_for(data), repr(bad))

    def test_state_values_must_be_colour_roles(self):
        data = raw()
        data["states"]["focus_border"] = "#FFFFFF"
        self.assertTrue(errors_for(data))
        data["states"]["focus_border"] = "nonexistent"
        self.assertTrue(errors_for(data))

    def test_schema_and_version(self):
        for mutate in (lambda d: d.update(schema="other"), lambda d: d.update(schema_version=0),
                       lambda d: d.update(schema_version=SCHEMA_VERSION + 1), lambda d: d.update(schema_version="1"),
                       lambda d: d.pop("schema")):
            data = raw()
            mutate(data)
            self.assertTrue(errors_for(data))
        data = raw()
        data["schema_version"] = SCHEMA_VERSION + 1
        self.assertTrue(any("newer" in e for e in errors_for(data)))

    def test_bad_json_documents(self):
        for text in ("", "{", "[]", "null", '{"a": NaN}', '{"a": 1, "a": 2}', "\u0000"):
            with self.assertRaises(ThemeError):
                parse_theme_json(text)

    def test_oversized_document_is_rejected_before_parsing(self):
        with self.assertRaises(ThemeError) as caught:
            parse_theme_json(" " * (MAX_THEME_BYTES + 1))
        self.assertIn("exceeds", caught.exception.errors[0])

    def test_identity_fields(self):
        for key, bad in (("id", "Has Space"), ("id", ""), ("id", "x" * 49), ("name", ""), ("name", "n" * 61),
                         ("kind", "admin"), ("base_id", "BAD ID"), ("description", "d" * 601)):
            data = raw()
            data[key] = bad
            self.assertTrue(errors_for(data), (key, bad))


class EditorTests(unittest.TestCase):
    def test_editing_a_reference_makes_a_user_copy_and_never_changes_the_preset(self):
        base = blue()
        editor = ThemeEditor(base)
        self.assertFalse(editor.is_dirty)
        self.assertTrue(editor.set("colors", "accent", "#FFC806"))
        self.assertEqual((editor.draft.kind, editor.draft.base_id), ("user", "blue-modern"))
        self.assertNotEqual(editor.draft.id, "blue-modern")
        self.assertTrue(editor.is_dirty)
        self.assertEqual(reference_themes()["blue-modern"], base)
        self.assertEqual(editor.base, base)

    def test_invalid_edit_keeps_last_valid_draft_and_reports(self):
        editor = ThemeEditor(blue())
        editor.set("colors", "accent", "#FFC806")
        good = editor.draft
        self.assertFalse(editor.set("colors", "accent", "#12"))
        self.assertEqual(editor.draft, good)
        self.assertTrue(editor.errors)
        self.assertTrue(editor.set("colors", "accent", "#FFC807"))
        self.assertEqual(editor.errors, [])

    def test_revert_and_unknown_keys(self):
        editor = ThemeEditor(blue())
        editor.set("radius", "card", 4)
        editor.revert()
        self.assertEqual(editor.draft, blue())
        self.assertFalse(editor.is_dirty)
        with self.assertRaises(KeyError):
            editor.set("colors", "nope", "#FFFFFF")
        with self.assertRaises(KeyError):
            editor.set("bogus", "x", 1)

    def test_every_section_is_editable(self):
        editor = ThemeEditor(blue())
        edits = (("colors", "muted", "#CCDDEE"), ("typography", "family", "Arial"), ("typography", "body_pt", 11),
                 ("typography", "emphasis_weight", "normal"), ("spacing", "gutter", 20), ("borders", "control_width", 3),
                 ("radius", "chip", 6), ("states", "focus_border", "text"), ("", "density", "compact"))
        for section, key, value in edits:
            self.assertTrue(editor.set(section, key, value), (section, key))
        d = editor.draft
        self.assertEqual((d.palette.muted, d.typography.family, d.typography.body_pt, d.typography.emphasis_weight, d.spacing.gutter,
                          d.borders.control_width, d.radius.chip, d.states.focus_border, d.density),
                         ("#CCDDEE", "Arial", 11, "normal", 20, 3, 6, "text", "compact"))

    def test_rename_derives_a_safe_id(self):
        editor = ThemeEditor(blue())
        self.assertTrue(editor.rename("My Theme! v2"))
        self.assertEqual((editor.draft.name, editor.draft.id), ("My Theme! v2", "my-theme-v2"))


class DensityAndContrastTests(unittest.TestCase):
    def test_compact_density_scales_gaps_but_not_the_hit_target(self):
        comfortable = blue()
        compact = replace(comfortable, density="compact")
        self.assertEqual(comfortable.metrics(), comfortable.spacing)
        for key in ("sm", "md", "gutter", "xl"):
            self.assertLess(getattr(compact.metrics(), key), getattr(comfortable.spacing, key), key)
        self.assertEqual(compact.metrics().control_min_height, comfortable.spacing.control_min_height)

    def test_contrast_function_known_values(self):
        self.assertAlmostEqual(contrast_ratio("#FFFFFF", "#000000"), 21.0, places=1)
        self.assertAlmostEqual(contrast_ratio("#777777", "#777777"), 1.0, places=3)

    def test_failing_contrast_is_detected(self):
        editor = ThemeEditor(blue())
        editor.set("colors", "text", editor.draft.palette.background)  # text == background
        labels = {c.label for c in failing_checks(editor.draft)}
        self.assertIn("Text on background", labels)
        editor.revert()
        editor.set("states", "focus_border", "background")  # invisible focus edge
        self.assertIn("Focus edge on surface", {c.label for c in failing_checks(editor.draft)})

    def test_every_state_role_has_a_contrast_or_text_check(self):
        labels = " ".join(c.label for c in contrast_checks(blue()))
        for fragment in ("Focus edge", "Input hover edge", "Primary focus edge", "Selected-item edge", "Danger action label"):
            self.assertIn(fragment, labels)


class StylesheetTests(unittest.TestCase):
    def test_both_presets_build_balanced_stylesheets_without_placeholders(self):
        for theme in reference_themes().values():
            css = build_stylesheet(theme, ASSET_DIR)
            self.assertEqual(css.count("{"), css.count("}"), theme.id)
            self.assertNotRegex(css, r"\{[a-z_.]+\}", theme.id)
            self.assertNotIn("None", css)

    def test_theme_values_reach_the_stylesheet(self):
        css = build_stylesheet(replace(blue(), radius=replace(blue().radius, card=21)), ASSET_DIR)
        self.assertIn("border-radius: 21px", css)
        accent = "#FFC806"
        editor = ThemeEditor(blue())
        editor.set("colors", "accent", accent)
        self.assertIn(accent, build_stylesheet(editor.draft, ASSET_DIR))
        self.assertNotIn(accent, build_stylesheet(blue(), ASSET_DIR))

    def test_state_roles_drive_state_selectors(self):
        editor = ThemeEditor(blue())
        editor.set("states", "button_hover_border", "success")
        css = build_stylesheet(editor.draft, ASSET_DIR)
        rule = re.search(r"QPushButton:hover, QPushButton\[state='hover'\] \{([^}]*)\}", css).group(1)
        self.assertIn(editor.draft.palette.success, rule)

    def test_forced_state_selectors_exist_for_the_state_matrix(self):
        css = build_stylesheet(blue(), ASSET_DIR)
        for selector in ("QPushButton[state='hover']", "QPushButton[state='focus']", "QPushButton[state='pressed']",
                         "QPushButton[role='primary'][state='hover']", "QPushButton[role='danger'][state='focus']",
                         "QLineEdit[state='hover']", "QLineEdit[state='focus']", "QCheckBox[state='focus']",
                         "QCheckBox[state='hover']::indicator"):
            self.assertIn(selector, css)

    def test_density_changes_padding_and_family_is_quoted(self):
        compact = build_stylesheet(replace(blue(), density="compact"), ASSET_DIR)
        self.assertIn("padding: 0px 10px", compact)
        self.assertIn("font-family: 'Segoe UI', Arial", compact)

    def test_every_colour_role_is_a_known_stylesheet_input(self):
        self.assertEqual(set(STATE_DEFAULTS.values()) - set(COLOR_ROLES), set())


if __name__ == "__main__":
    unittest.main()
