"""Frozen ADetailer checkpoint selection and the legacy compatibility rule."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Literal

from src.pipeline.model_synchronizer import (
    checkpoint_names_match,
    normalize_model_name,
    operator_model_title,
)
from src.utils.config import ADETAILER_CHECKPOINT_SELECTION_KEY

CHECKPOINT_SELECTION_KEY = ADETAILER_CHECKPOINT_SELECTION_KEY
CHECKPOINT_ALIASES = ("adetailer_checkpoint_model", "model", "sd_model_checkpoint")


def _checkpoint(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    name = value.strip()
    if not normalize_model_name(name) or name in {"Inherit Base Generation", "inherit"}:
        return None
    if name.lower().endswith(".pt") and name.lower().startswith(
        ("face_", "hand_", "person_", "mediapipe")
    ):
        return None
    return name


@dataclass(frozen=True, slots=True)
class ADetailerCheckpointSelection:
    mode: Literal["inherit", "explicit"]
    checkpoint: str | None = None

    @classmethod
    def from_operator_choice(cls, value: str) -> ADetailerCheckpointSelection:
        if value:
            return cls("explicit", value)
        return cls("inherit")

    @classmethod
    def from_config(cls, config: Mapping[str, Any]) -> ADetailerCheckpointSelection | None:
        if CHECKPOINT_SELECTION_KEY not in config:
            return None
        raw = config[CHECKPOINT_SELECTION_KEY]
        if isinstance(raw, Mapping):
            mode, name = raw.get("mode"), raw.get("checkpoint")
            if mode == "inherit" and name is None:
                return cls("inherit")
            if mode == "explicit" and (checkpoint := _checkpoint(name)):
                return cls("explicit", checkpoint)
        raise ValueError(
            "ADetailer checkpoint selection is invalid. Create a fresh job and select "
            "Inherit Base Generation or an available checkpoint."
        )

    def to_dict(self) -> dict[str, str | None]:
        return {"mode": self.mode, "checkpoint": self.checkpoint}


def _legacy_checkpoints(config: Mapping[str, Any]) -> list[str]:
    return [name for key in CHECKPOINT_ALIASES if (name := _checkpoint(config.get(key)))]


def stamp_fresh_checkpoint_selection(config: dict[str, Any]) -> None:
    """A blank authoring scope inherits. Older nonblank settings retain their uncertainty."""
    if ADetailerCheckpointSelection.from_config(config) is None and not _legacy_checkpoints(config):
        config[CHECKPOINT_SELECTION_KEY] = ADetailerCheckpointSelection("inherit").to_dict()


def resolve_adetailer_checkpoint(stage: Mapping[str, Any], base: str | None) -> str | None:
    """Resolve using frozen intent, or refuse a legacy conflict before runtime is touched."""
    config = dict(stage)
    extra = stage.get("extra")
    if isinstance(extra, Mapping):
        config.update(extra)
    selection = ADetailerCheckpointSelection.from_config(config)
    if selection is not None:
        return selection.checkpoint if selection.mode == "explicit" else base

    candidates = _legacy_checkpoints(stage)
    if isinstance(extra, Mapping):
        candidates.extend(_legacy_checkpoints(extra))
    effective = base or next(iter(candidates), None)
    for candidate in candidates:
        if not checkpoint_names_match(candidate, effective):
            raise ValueError(
                f"ADetailer checkpoint conflict between '{operator_model_title(effective)}' and "
                f"'{operator_model_title(candidate)}' without recorded selection. "
                "Create a fresh job and explicitly choose the ADetailer checkpoint "
                "or Inherit Base Generation."
            )
    return effective
