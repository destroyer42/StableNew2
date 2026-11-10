"""Saving, restoring, importing and exporting user themes (pure Python, no Qt).

User themes live in one directory chosen by the caller (default: ``design/qt_widgets/user_themes``,
git-ignored, or ``STABLENEW_QT_PROTO_THEME_DIR``). Nothing here reads or writes StableNew
production settings, ``presets/`` or ``config/``. Shipped reference presets are never written:
every write path refuses a reference id, and overwriting an existing user theme needs an
explicit ``overwrite=True``.
"""

from __future__ import annotations

import json
import os
import tempfile
from dataclasses import replace
from pathlib import Path

from .theme import MAX_THEME_BYTES, Theme, ThemeError, canonical_json, parse_theme_json, slugify
from .tokens import DEFAULT_THEME_ID, reference_themes

ENV_THEME_DIR = "STABLENEW_QT_PROTO_THEME_DIR"
STATE_FILE = "active-theme.json"
SUFFIX = ".theme.json"


def default_user_theme_dir() -> Path:
    override = os.environ.get(ENV_THEME_DIR)
    return Path(override) if override else Path(__file__).resolve().parents[1] / "user_themes"


class ThemeStoreError(RuntimeError):
    """A save/delete/export was refused (reference preset, overwrite, bad name, I/O)."""


def _atomic_write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=path.name + ".", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(text)
        os.replace(tmp, path)
    except OSError:
        Path(tmp).unlink(missing_ok=True)
        raise


class ThemeLibrary:
    def __init__(self, user_dir: Path | None = None):
        self.user_dir = Path(user_dir) if user_dir is not None else default_user_theme_dir()
        self.references = reference_themes()

    # ---------------------------------------------------------------- listing
    def user_themes(self) -> dict[str, Theme]:
        """Valid saved themes by id. Invalid files are skipped and reported by :meth:`invalid_files`."""
        found: dict[str, Theme] = {}
        for path in sorted(self.user_dir.glob(f"*{SUFFIX}")) if self.user_dir.is_dir() else ():
            try:
                theme = self._read(path)
            except (ThemeError, OSError):
                continue
            found[theme.id] = theme
        return found

    def invalid_files(self) -> dict[str, str]:
        problems: dict[str, str] = {}
        for path in sorted(self.user_dir.glob(f"*{SUFFIX}")) if self.user_dir.is_dir() else ():
            try:
                self._read(path)
            except (ThemeError, OSError) as exc:
                problems[path.name] = str(exc)
        return problems

    def all_themes(self) -> dict[str, Theme]:
        return {**self.references, **self.user_themes()}

    def get(self, theme_id: str) -> Theme:
        themes = self.all_themes()
        if theme_id not in themes:
            raise KeyError(theme_id)
        return themes[theme_id]

    @staticmethod
    def _read(path: Path) -> Theme:
        if path.stat().st_size > MAX_THEME_BYTES:
            raise ThemeError([f"{path.name}: file exceeds {MAX_THEME_BYTES // 1024} KiB"])
        theme = parse_theme_json(path.read_text(encoding="utf-8"))
        if theme.kind != "user":
            raise ThemeError([f"{path.name}: only kind 'user' themes may be stored here"])
        return theme

    # ---------------------------------------------------------------- saving
    def path_for(self, theme_id: str) -> Path:
        return self.user_dir / f"{theme_id}{SUFFIX}"

    def save_as(self, theme: Theme, name: str, *, overwrite: bool = False) -> Theme:
        """Save ``theme`` as a new user theme called ``name`` and return the saved theme."""
        name = name.strip()
        if not name or len(name) > 60:
            raise ThemeStoreError("Enter a theme name of 1-60 characters.")
        slug = slugify(name)
        if slug in self.references:
            raise ThemeStoreError(
                f"'{slug}' is a shipped reference preset and cannot be overwritten; choose another name."
            )
        target = self.path_for(slug)
        if target.exists() and not overwrite:
            raise ThemeStoreError(
                f"A saved theme '{slug}' already exists; confirm overwrite to replace it."
            )
        base_id = theme.base_id or (theme.id if theme.kind == "reference" else None)
        saved = replace(theme, id=slug, name=name, kind="user", base_id=base_id)
        try:
            _atomic_write(target, canonical_json(saved))
        except OSError as exc:
            raise ThemeStoreError(f"Could not save: {exc}") from exc
        return saved

    def delete(self, theme_id: str) -> None:
        if theme_id in self.references:
            raise ThemeStoreError("Shipped reference presets cannot be deleted.")
        path = self.path_for(theme_id)
        if not path.is_file():
            raise ThemeStoreError(f"No saved theme '{theme_id}'.")
        path.unlink()
        if self.active_id() == theme_id:
            self.clear_active()

    # ------------------------------------------------------- export / import
    def export_to(self, theme: Theme, path: Path) -> Path:
        """Write ``theme`` as a user-kind JSON file at an explicit, caller-chosen path."""
        path = Path(path)
        if path.suffix.lower() != ".json":
            raise ThemeStoreError("Export files must end in .json.")
        try:
            resolved = path.resolve()
            for reference_dir in (Path(__file__).resolve().parent / "themes",):
                if resolved.parent == reference_dir:
                    raise ThemeStoreError(
                        "Exports cannot be written into the shipped themes folder."
                    )
            exported = replace(
                theme,
                kind="user",
                base_id=theme.base_id or (theme.id if theme.kind == "reference" else None),
            )
            _atomic_write(path, canonical_json(exported))
        except OSError as exc:
            raise ThemeStoreError(f"Could not export: {exc}") from exc
        return path

    def import_from(self, path: Path) -> Theme:
        """Validate a theme file and return it as an unsaved user theme (never auto-saved or applied).

        A document claiming ``kind: reference`` is downgraded to a user copy, and a colliding id
        or name receives an ``-imported`` suffix so shipped and saved themes are never shadowed.
        """
        path = Path(path)
        try:
            if path.stat().st_size > MAX_THEME_BYTES:
                raise ThemeError([f"theme file exceeds {MAX_THEME_BYTES // 1024} KiB"])
            theme = parse_theme_json(path.read_text(encoding="utf-8"))
        except OSError as exc:
            raise ThemeError([f"could not read file: {exc}"]) from exc
        taken = set(self.all_themes())
        theme_id, name = theme.id, theme.name
        if theme_id in taken:
            stem, counter = theme_id[:36], 2
            theme_id = f"{stem}-imported"
            while theme_id in taken:
                theme_id, counter = f"{stem}-imported-{counter}", counter + 1
            name = f"{name[:46]} (imported)"
        base_id = theme.base_id or (theme.id if theme.kind == "reference" else None)
        return replace(theme, id=theme_id, name=name, kind="user", base_id=base_id)

    # ---------------------------------------------------------- active theme
    def _state_path(self) -> Path:
        return self.user_dir / STATE_FILE

    def active_id(self) -> str:
        try:
            data = json.loads(self._state_path().read_text(encoding="utf-8"))
            value = data.get("active") if isinstance(data, dict) else None
        except (OSError, ValueError):
            return DEFAULT_THEME_ID
        return value if isinstance(value, str) else DEFAULT_THEME_ID

    def set_active(self, theme: Theme) -> None:
        """Remember a *saved or reference* theme as the one to restore next launch."""
        if theme.id not in self.all_themes() or self.get(theme.id) != theme:
            raise ThemeStoreError(
                "Only a saved or shipped theme can be restored at launch; use Save As first."
            )
        try:
            _atomic_write(self._state_path(), json.dumps({"active": theme.id}) + "\n")
        except OSError as exc:
            raise ThemeStoreError(f"Could not remember the active theme: {exc}") from exc

    def clear_active(self) -> None:
        self._state_path().unlink(missing_ok=True)

    def load_active(self) -> Theme:
        """The theme to start with: the remembered one if it still exists and is valid, else the default."""
        themes = self.all_themes()
        return themes.get(self.active_id(), themes[DEFAULT_THEME_ID])
