"""Toolkit-neutral masked draft edits. Store sidecars remain the only photo draft authority."""

from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from dataclasses import dataclass, field
from typing import Any

from src.gui.controllers.review_workflow_adapter import ReviewWorkflowAdapter

from .models import PhotoOptimizeAsset
from .settings import (
    FIELDS,
    STAGES,
    decoded_geometry,
    normalize_settings,
    resolve_geometry,
    validate_settings,
)


@dataclass(frozen=True)
class PromptEdit:
    mode: str
    text: str


@dataclass(frozen=True)
class SelectionValue:
    value: Any
    mixed: bool


def field_defaults() -> dict[str, Any]:
    return {
        "model": "",
        "vae": "",
        "geometry_policy": "auto",
        **{f"stage.{stage}": False for stage in STAGES},
        **{
            f"config.{stage}.{key}": spec[2]
            for stage, fields in FIELDS.items()
            for key, spec in fields.items()
        },
    }


def asset_values(asset: PhotoOptimizeAsset) -> dict[str, Any]:
    baseline = asset.baseline
    config = normalize_settings(baseline.config)
    return {
        "model": baseline.model,
        "vae": baseline.vae,
        "geometry_policy": baseline.geometry_policy,
        "prompt": baseline.prompt,
        "negative_prompt": baseline.negative_prompt,
        **{f"stage.{s}": bool(baseline.stage_defaults.get(s, False)) for s in STAGES},
        **{f"config.{s}.{key}": value for s in STAGES for key, value in config[s].items()},
    }


def selection_values(assets: list[PhotoOptimizeAsset]) -> dict[str, SelectionValue]:
    if not assets:
        return {}
    rows = [asset_values(asset) for asset in assets]
    keys = sorted(set().union(*(row.keys() for row in rows)))
    return {
        key: SelectionValue(
            deepcopy(rows[0].get(key)), any(row.get(key) != rows[0].get(key) for row in rows[1:])
        )
        for key in keys
    }


def pipeline_mask(snapshot: dict[str, Any], groups: set[str]) -> dict[str, Any]:
    """Explicit field groups; geometry and saved prompts are never implicit stage-copy targets."""
    if not isinstance(snapshot.get("config"), dict) or not snapshot["config"]:
        raise ValueError("Live Pipeline settings are unavailable")
    config = normalize_settings(snapshot["config"])
    captured = snapshot.get("captured_config", snapshot["config"])
    mask = {}
    for key in ("model", "vae"):
        if key in groups:
            mask[key] = snapshot.get(key, "")
    if "stages" in groups:
        mask.update({f"stage.{s}": bool(snapshot["stage_defaults"].get(s, False)) for s in STAGES})
    for stage in STAGES:
        if stage in groups:
            aliases = {alias for spec in FIELDS[stage].values() for alias in spec[0]}
            raw = captured.get(stage, {})
            exported = {
                key
                for key, (legacy, flat, _) in FIELDS[stage].items()
                if any(name in raw for name in (key, *legacy))
                or any(name in captured for name in flat)
            }
            exported.update(set(raw) - aliases - FIELDS[stage].keys())
            for key in config[stage]:
                if key in exported and key not in aliases | {
                    "width",
                    "height",
                    "model",
                    "model_name",
                    "vae",
                    "vae_name",
                    "enabled",
                }:
                    mask[f"config.{stage}.{key}"] = deepcopy(config[stage][key])
    if "geometry" in groups and all(
        captured.get("img2img", {}).get(k) for k in ("width", "height")
    ):
        mask.update(
            {
                "geometry_policy": "custom",
                "config.img2img.width": config["img2img"]["width"],
                "config.img2img.height": config["img2img"]["height"],
            }
        )
    return mask


@dataclass
class EditRow:
    asset_id: str
    before: PhotoOptimizeAsset
    after: PhotoOptimizeAsset
    fingerprint: str
    changes: dict[str, tuple[Any, Any]]


@dataclass
class EditPlan:
    rows: list[EditRow]
    source: str

    def describe(self, render=lambda asset, value: repr(value)) -> str:
        lines = [
            f"{self.source}: {len(self.rows)} photo(s). Only listed fields change.",
            "Preserved: unmasked fields, prompts not targeted, geometry policy unless selected, "
            "notes, tags, archive state, history and snapshots. Writes are per asset, not atomic.",
        ]
        for row in self.rows:
            lines.append(f"\n{row.asset_id}" + (" [Archived]" if row.before.archived else ""))
            lines.extend(
                f"  {key}: {render(row.before, before)} -> {render(row.after, after)}"
                for key, (before, after) in row.changes.items()
            )
            if not row.changes:
                lines.append("  No changes")
        return "\n".join(lines)


@dataclass
class EditResult:
    applied: list[str] = field(default_factory=list)
    failed: dict[str, str] = field(default_factory=dict)
    unconfirmed: dict[str, str] = field(default_factory=dict)

    def describe(self) -> str:
        return (
            f"Successful IDs: {', '.join(self.applied) or '(none)'}\n"
            f"Failed IDs: {self.failed or '(none)'}\n"
            f"Unconfirmed IDs (inspect before retry): {self.unconfirmed or '(none)'}"
        )


def _fingerprint(store, identity):
    return hashlib.sha256(store.sidecar_path(identity).read_bytes()).hexdigest()


def prepare_edit(store, ids: list[str], mask: dict[str, Any], *, source="Batch Edit") -> EditPlan:
    """Preflight every selected asset before any write. A missing mask entry always means leave unchanged."""
    if not ids or len(set(ids)) != len(ids):
        raise ValueError("Select unique photo identities")
    allowed = set(field_defaults()) | {"prompt", "negative_prompt"}
    extra_config = {
        k
        for k in mask
        if k.startswith("config.")
        and len(k.split(".", 2)) == 3
        and k.split(".", 2)[1] in STAGES
        and k.split(".", 2)[2]
    }
    if not mask or set(mask) - allowed - extra_config:
        raise ValueError("Select at least one supported field to Apply")
    dimensions = {"config.img2img.width", "config.img2img.height"}
    if dimensions & mask.keys() and mask.get("geometry_policy") != "custom":
        raise ValueError("Dimension overrides require explicitly selecting Custom geometry")
    rows = []
    for identity in ids:
        signature = _fingerprint(store, identity)
        before = store.get_asset(identity)
        if before is None:
            raise ValueError(f"Photo is unavailable: {identity}")
        after = deepcopy(before)
        baseline = after.baseline
        for key, value in mask.items():
            if key in {"prompt", "negative_prompt"}:
                if not isinstance(value, PromptEdit) or value.mode not in {
                    "append",
                    "replace",
                    "modify",
                }:
                    raise ValueError("Prompt transformations require append, replace or modify")
                setattr(
                    baseline,
                    key,
                    ReviewWorkflowAdapter.apply_prompt_delta(
                        getattr(baseline, key), value.text, value.mode
                    ),
                )
            elif key.startswith("stage."):
                if type(value) is not bool:
                    raise ValueError(f"{key} requires True or False")
                baseline.stage_defaults[key.split(".")[1]] = value
            elif key.startswith("config."):
                _, stage, name = key.split(".", 2)
                aliases, flat, fallback = FIELDS[stage].get(name, ((), (), None))
                if isinstance(fallback, bool) and type(value) is not bool:
                    raise ValueError(f"{key} requires True or False")
                if type(fallback) in (int, float) and isinstance(value, bool):
                    raise ValueError(f"{key} requires a number")
                nested = baseline.config.setdefault(stage, {})
                nested[name] = value
                nested.update(dict.fromkeys(aliases, value))
                baseline.config.update(dict.fromkeys(flat, value))
            else:
                if not isinstance(value, str):
                    raise ValueError(f"{key} requires text")
                setattr(baseline, key, value)
        width, height = decoded_geometry(after.current_input_path)
        if baseline.geometry_policy not in {"auto", "custom"}:
            raise ValueError("Geometry must be Auto or Custom")
        if (
            mask.get("geometry_policy") == "custom"
            and before.baseline.geometry_policy == "auto"
            and not dimensions <= mask.keys()
        ):
            raise ValueError("Switching Auto photos to Custom requires explicit width and height")
        if baseline.geometry_policy == "auto" and "geometry_policy" in mask:
            for section in (
                baseline.config,
                baseline.config.setdefault("img2img", {}),
                baseline.config.setdefault("txt2img", {}),
            ):
                section.update(width=width, height=height)
        config = resolve_geometry(baseline, after.current_input_path)
        validate_settings(config)
        json.dumps(
            after.to_dict(), allow_nan=False
        )  # preflight serialization for the entire selection
        old, new = asset_values(before), asset_values(after)
        changes = {
            key: (old.get(key, "(not set)"), new.get(key, "(not set)"))
            for key in sorted(old.keys() | new.keys())
            if old.get(key) != new.get(key)
        }
        if _fingerprint(store, identity) != signature:
            raise ValueError(f"Photo changed while preparing: {identity}; preview again")
        rows.append(EditRow(identity, before, after, signature, changes))
    return EditPlan(rows, source)


def apply_edit(store, plan: EditPlan) -> EditResult:
    """Refuse stale selections before writing; retain exact per-asset outcomes if later writes fail."""
    for row in plan.rows:
        if _fingerprint(store, row.asset_id) != row.fingerprint:
            raise ValueError(
                f"Photo changed since preview: {row.asset_id}; nothing applied, preview again"
            )
    result = EditResult()
    for row in plan.rows:
        try:
            if _fingerprint(store, row.asset_id) != row.fingerprint:
                result.failed[row.asset_id] = "Changed during Apply; preview again"
                continue
            if row.changes:
                store.save_asset(deepcopy(row.after))
            result.applied.append(row.asset_id)
        except (OSError, ValueError, TypeError) as exc:
            try:
                saved = store.get_asset(row.asset_id)
                if saved is not None and saved.to_dict() == row.after.to_dict():
                    result.applied.append(row.asset_id)
                elif _fingerprint(store, row.asset_id) == row.fingerprint:
                    result.failed[row.asset_id] = str(exc)
                else:
                    result.unconfirmed[row.asset_id] = str(exc)
            except OSError:
                result.unconfirmed[row.asset_id] = str(exc)
    return result
