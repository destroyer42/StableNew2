"""Persistence helpers for GUI preferences and last-used settings."""

from __future__ import annotations

import copy
import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


class PreferencesManager:
    """Read and write last-used GUI preferences as JSON."""

    _DEFAULT_PIPELINE_CONTROLS: dict[str, Any] = {
        "txt2img_enabled": True,
        "img2img_enabled": True,
        "adetailer_enabled": False,
        "upscale_enabled": True,
        "video_enabled": False,
        "loop_type": "single",
        "loop_count": 1,
        "pack_mode": "selected",
        "images_per_prompt": 1,
        "model_matrix": [],
        "hypernetworks": [],
        "variant_mode": "fanout",
    }

    def __init__(self, path: str | Path | None = None):
        """Initialise manager with optional custom storage path."""

        if path is None:
            path = Path("presets") / "last_settings.json"
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def default_pipeline_controls(self) -> dict[str, Any]:
        """Return a copy of the default pipeline controls payload."""

        return copy.deepcopy(self._DEFAULT_PIPELINE_CONTROLS)

    def default_preferences(self, default_config: dict[str, Any]) -> dict[str, Any]:
        """Return default preferences merged with provided default config."""

        return {
            "preset": "default",
            "selected_packs": [],
            "override_pack": False,
            "pipeline_controls": self.default_pipeline_controls(),
            "config": copy.deepcopy(default_config),
        }

    def load_preferences(self, default_config: dict[str, Any]) -> dict[str, Any]:
        """Load preferences from disk, merging with defaults for missing keys."""

        preferences = self.default_preferences(default_config)

        if not self.path.exists():
            return preferences

        try:
            with self.path.open(encoding="utf-8") as handle:
                data = json.load(handle)
        except Exception as err:  # pragma: no cover - defensive logging path
            logger.warning(
                "Failed to load preferences from %s: %s. Using defaults.", self.path, err
            )
            return preferences

        preferences["preset"] = data.get("preset", preferences["preset"])
        preferences["selected_packs"] = data.get("selected_packs", preferences["selected_packs"])
        preferences["override_pack"] = bool(data.get("override_pack", preferences["override_pack"]))

        pipeline_overrides = data.get("pipeline_controls", {})
        preferences["pipeline_controls"] = self._merge_dicts(
            preferences["pipeline_controls"], pipeline_overrides
        )

        config_overrides = data.get("config", {})
        preferences["config"] = self._merge_dicts(preferences["config"], config_overrides)

        return preferences

    def save_preferences(self, preferences: dict[str, Any]) -> bool:
        """Persist preferences to disk. Returns True when successful."""

        try:
            with self.path.open("w", encoding="utf-8") as handle:
                json.dump(preferences, handle, indent=2, ensure_ascii=False)
            logger.info("Saved preferences to %s", self.path)
            return True
        except Exception as err:  # pragma: no cover - defensive logging path
            logger.error("Failed to save preferences to %s: %s", self.path, err)
            return False

    def backup_corrupt_preferences(self) -> None:
        """Move a corrupt preferences file out of the way (or delete if rename fails)."""

        if not self.path.exists():
            return

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        backup_name = f"{self.path.stem}_corrupt_{timestamp}{self.path.suffix}"
        backup_path = self.path.with_name(backup_name)

        try:
            self.path.rename(backup_path)
            logger.warning("Backed up corrupt preferences to %s", backup_path)
            return
        except Exception as exc:
            logger.error("Failed to move corrupt preferences to %s: %s", backup_path, exc)

        try:
            self.path.unlink()
            logger.warning("Deleted corrupt preferences file at %s", self.path)
        except Exception:
            logger.exception("Failed to delete corrupt preferences file at %s", self.path)

    def _merge_dicts(self, base: dict[str, Any], overrides: dict[str, Any]) -> dict[str, Any]:
        """Deep merge two dictionaries without mutating the inputs."""

        result = copy.deepcopy(base)
        for key, value in overrides.items():
            if isinstance(result.get(key), dict) and isinstance(value, dict):
                result[key] = self._merge_dicts(result[key], value)
            else:
                result[key] = value
        return result
