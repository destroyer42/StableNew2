"""Pure tests: saving, restoring, importing and exporting user themes without touching shipped presets."""

from __future__ import annotations

import json
import os
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path

from stablenew_qt_proto.theme import MAX_THEME_BYTES, ThemeEditor, ThemeError, canonical_json
from stablenew_qt_proto.theme_store import (
    ENV_THEME_DIR, SUFFIX, ThemeLibrary, ThemeStoreError, default_user_theme_dir,
)
from stablenew_qt_proto.tokens import THEME_DIR, reference_themes

REPO_ROOT = Path(__file__).resolve().parents[3]


class StoreCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.dir = Path(self._tmp.name) / "themes"
        self.lib = ThemeLibrary(self.dir)
        self.blue = reference_themes()["blue-modern"]

    def edited(self, **colors):
        editor = ThemeEditor(self.blue)
        for role, value in colors.items():
            editor.set("colors", role, value)
        return editor.draft


class SaveRestoreTests(StoreCase):
    def test_save_then_restore_in_a_fresh_library(self):
        saved = self.lib.save_as(self.edited(accent="#FFC806"), "Warm Accent")
        self.assertEqual((saved.id, saved.kind, saved.base_id), ("warm-accent", "user", "blue-modern"))
        fresh = ThemeLibrary(self.dir)
        self.assertEqual(fresh.get("warm-accent"), saved)
        self.assertEqual(fresh.get("warm-accent").palette.accent, "#FFC806")

    def test_saved_file_is_canonical_json_in_the_user_dir_only(self):
        self.lib.save_as(self.edited(), "Plain")
        files = sorted(p.name for p in self.dir.iterdir())
        self.assertEqual(files, ["plain" + SUFFIX])
        text = (self.dir / ("plain" + SUFFIX)).read_text(encoding="utf-8")
        self.assertEqual(text, canonical_json(self.lib.get("plain")))

    def test_shipped_presets_cannot_be_overwritten_or_deleted(self):
        before = {p.name: p.read_bytes() for p in THEME_DIR.glob("*.json")}
        for name in ("Blue Modern", "blue-modern", "BLUE  MODERN!", "Concept A"):
            with self.assertRaises(ThemeStoreError):
                self.lib.save_as(self.edited(), name, overwrite=True)
        with self.assertRaises(ThemeStoreError):
            self.lib.delete("blue-modern")
        self.assertEqual({p.name: p.read_bytes() for p in THEME_DIR.glob("*.json")}, before)
        self.assertFalse(self.dir.exists() and any(self.dir.iterdir()))

    def test_overwriting_a_saved_theme_needs_explicit_confirmation(self):
        self.lib.save_as(self.edited(accent="#FFC806"), "Mine")
        with self.assertRaises(ThemeStoreError) as caught:
            self.lib.save_as(self.edited(accent="#FFC807"), "Mine")
        self.assertIn("already exists", str(caught.exception))
        self.assertEqual(self.lib.get("mine").palette.accent, "#FFC806")
        self.lib.save_as(self.edited(accent="#FFC807"), "Mine", overwrite=True)
        self.assertEqual(ThemeLibrary(self.dir).get("mine").palette.accent, "#FFC807")

    def test_names_cannot_escape_the_directory(self):
        for name in ("../escape", "..\\escape-two", "a/b", "C:\\x", "con", "x" * 80):
            if len(name) > 60:
                with self.assertRaises(ThemeStoreError):
                    self.lib.save_as(self.edited(), name)
                continue
            saved = self.lib.save_as(self.edited(), name)
            self.assertEqual(self.lib.path_for(saved.id).parent, self.dir)
        for path in self.dir.iterdir():
            self.assertTrue(path.name.endswith(SUFFIX))
        self.assertEqual(list(self.dir.parent.glob("*")), [self.dir])

    def test_empty_name_is_refused_and_no_temp_files_remain(self):
        with self.assertRaises(ThemeStoreError):
            self.lib.save_as(self.edited(), "   ")
        self.lib.save_as(self.edited(), "ok")
        self.assertEqual([p.name for p in self.dir.iterdir() if p.name.endswith(".tmp")], [])

    def test_delete_removes_file_and_clears_active(self):
        saved = self.lib.save_as(self.edited(), "Gone")
        self.lib.set_active(saved)
        self.lib.delete("gone")
        self.assertNotIn("gone", self.lib.user_themes())
        self.assertEqual(self.lib.active_id(), "blue-modern")
        with self.assertRaises(ThemeStoreError):
            self.lib.delete("gone")


class ActiveThemeTests(StoreCase):
    def test_default_is_blue_modern_without_any_state(self):
        self.assertEqual(self.lib.load_active(), self.blue)
        self.assertFalse(self.dir.exists())

    def test_active_theme_is_restored_in_a_new_session(self):
        saved = self.lib.save_as(self.edited(accent="#FFC806"), "Restore Me")
        self.lib.set_active(saved)
        self.assertEqual(ThemeLibrary(self.dir).load_active(), saved)

    def test_reference_can_be_remembered(self):
        concept = reference_themes()["concept-a"]
        self.lib.set_active(concept)
        self.assertEqual(ThemeLibrary(self.dir).load_active(), concept)

    def test_unsaved_or_modified_themes_cannot_be_remembered(self):
        with self.assertRaises(ThemeStoreError):
            self.lib.set_active(self.edited(accent="#FFC806"))
        saved = self.lib.save_as(self.edited(), "Saved")
        with self.assertRaises(ThemeStoreError):
            self.lib.set_active(replace(saved, description="changed after save"))

    def test_corrupt_or_stale_state_falls_back_to_default(self):
        self.dir.mkdir()
        for content in ("not json", "[]", json.dumps({"active": 5}), json.dumps({"active": "deleted-theme"})):
            (self.dir / "active-theme.json").write_text(content, encoding="utf-8")
            self.assertEqual(self.lib.load_active(), self.blue, content)

    def test_invalid_saved_files_are_skipped_and_reported(self):
        self.dir.mkdir()
        (self.dir / ("broken" + SUFFIX)).write_text("{", encoding="utf-8")
        wrong_kind = json.loads(canonical_json(self.blue))
        (self.dir / ("fake" + SUFFIX)).write_text(json.dumps(wrong_kind), encoding="utf-8")  # kind: reference
        self.assertEqual(self.lib.user_themes(), {})
        self.assertEqual(set(self.lib.invalid_files()), {"broken" + SUFFIX, "fake" + SUFFIX})
        self.assertEqual(self.lib.load_active(), self.blue)


class ExportImportTests(StoreCase):
    def test_export_import_round_trip(self):
        draft = self.edited(accent="#FFC806")
        target = self.dir.parent / "out" / "exported.json"
        self.lib.export_to(draft, target)
        imported = self.lib.import_from(target)
        self.assertEqual(imported.palette, draft.palette)
        self.assertEqual(imported.kind, "user")
        self.assertEqual(self.lib.user_themes(), {})  # import never saves by itself

    def test_export_requires_json_suffix_and_never_writes_into_shipped_themes(self):
        with self.assertRaises(ThemeStoreError):
            self.lib.export_to(self.blue, self.dir.parent / "x.txt")
        with self.assertRaises(ThemeStoreError):
            self.lib.export_to(self.blue, THEME_DIR / "evil.json")
        self.assertFalse((THEME_DIR / "evil.json").exists())

    def test_exported_reference_becomes_a_user_theme_referencing_its_base(self):
        target = self.dir.parent / "ref.json"
        self.lib.export_to(self.blue, target)
        document = json.loads(target.read_text(encoding="utf-8"))
        self.assertEqual((document["kind"], document["base_id"]), ("user", "blue-modern"))

    def test_imported_reference_claim_is_downgraded_and_id_collisions_are_renamed(self):
        source = self.dir.parent / "claims.json"
        source.parent.mkdir(parents=True, exist_ok=True)
        source.write_text(canonical_json(self.blue), encoding="utf-8")  # kind: reference, id: blue-modern
        imported = self.lib.import_from(source)
        self.assertEqual(imported.kind, "user")
        self.assertNotIn(imported.id, self.lib.references)
        self.assertEqual(imported.base_id, "blue-modern")
        self.assertTrue(imported.name.endswith("(imported)"))

    def test_import_errors(self):
        base = self.dir.parent
        base.mkdir(parents=True, exist_ok=True)
        good = json.loads(canonical_json(self.blue))
        cases = {
            "empty.json": "",
            "garbage.json": "{{{",
            "array.json": "[1, 2]",
            "future.json": json.dumps({**good, "schema_version": 9}),
            "badcolour.json": json.dumps({**good, "colors": {**good["colors"], "accent": "#12"}}),
            "extra.json": json.dumps({**good, "evil": "<script>"}),
            "huge.json": " " * (MAX_THEME_BYTES + 1),
        }
        for name, content in cases.items():
            path = base / name
            path.write_text(content, encoding="utf-8")
            with self.assertRaises(ThemeError, msg=name) as caught:
                self.lib.import_from(path)
            self.assertTrue(caught.exception.errors, name)
        with self.assertRaises(ThemeError):
            self.lib.import_from(base / "missing.json")
        self.assertEqual(self.lib.user_themes(), {})

    def test_import_survives_hostile_unicode_and_control_characters(self):
        path = self.dir.parent / "unicode.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        good = json.loads(canonical_json(self.blue))
        good.update(kind="user", id="uni", name="Ünï \u202e rtl", description="x\u0000y")
        path.write_text(json.dumps(good), encoding="utf-8")
        theme = self.lib.import_from(path)
        self.assertEqual(theme.id, "uni")


class ProductionIsolationTests(unittest.TestCase):
    def test_default_directory_is_outside_production_settings(self):
        path = default_user_theme_dir().resolve()
        for protected in ("presets", "config", "src", "data"):
            self.assertNotIn((REPO_ROOT / protected).resolve(), (path, *path.parents), protected)
        self.assertEqual(path.name, "user_themes")

    def test_environment_override(self):
        previous = os.environ.get(ENV_THEME_DIR)
        os.environ[ENV_THEME_DIR] = "C:/somewhere/else"
        try:
            self.assertEqual(default_user_theme_dir(), Path("C:/somewhere/else"))
        finally:
            if previous is None:
                del os.environ[ENV_THEME_DIR]
            else:
                os.environ[ENV_THEME_DIR] = previous

    def test_store_module_never_names_production_settings(self):
        source = (Path(__file__).resolve().parents[1] / "stablenew_qt_proto" / "theme_store.py").read_text(encoding="utf-8")
        code = source.split('"""', 2)[2]  # skip the module docstring, which names what is excluded
        for forbidden in ('"presets"', "presets/", "settings.json", "ui_tokens", "design_values", "config/"):
            self.assertFalse(forbidden in code, forbidden)


if __name__ == "__main__":
    unittest.main()
