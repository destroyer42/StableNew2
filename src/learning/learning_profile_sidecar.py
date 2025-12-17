# Subsystem: Learning
# Role: Associates model/LoRA profiles with learning runs via sidecar metadata.

"""Model & LoRA Profile Sidecar support for learning runs."""

import json
from pathlib import Path
from typing import Any


class ProfileSidecar:
    """Represents a model or LoRA profile sidecar file."""

    def __init__(self, path: Path):
        self.path = path
        self.data: dict[str, Any] | None = None
        self._load()

    def _load(self):
        if self.path.exists() and self.path.suffix in {".json", ".profile"}:
            with open(self.path, encoding="utf-8") as f:
                self.data = json.load(f)
        else:
            self.data = None

    def get_prior(self) -> dict[str, Any] | None:
        """Return the prior config/settings for learning."""
        if self.data:
            return self.data.get("prior", self.data)
        return None

    def get_metadata(self) -> dict[str, Any] | None:
        if self.data:
            return self.data.get("metadata", {})
        return None


# Utility to discover sidecars for a model or LoRA


def find_profile_sidecar(base_path: Path, name: str) -> ProfileSidecar | None:
    """Find a sidecar file for a given model or LoRA name."""
    candidates = [
        base_path / f"{name}.profile",
        base_path / f"{name}.json",
    ]
    for candidate in candidates:
        if candidate.exists():
            return ProfileSidecar(candidate)
    return None


# Example usage in learning run:
# sidecar = find_profile_sidecar(Path('profiles'), 'my_model')
# prior = sidecar.get_prior() if sidecar else None
