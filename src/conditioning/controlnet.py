"""Versioned, ordered ControlNet declarations and frozen records (PR-IMG-CNET-220).

The legacy openpose.v1 contract is unchanged. Unit settings and image snapshots use
its existing validation primitives internally; persisted multi-unit records have
their own contract and never masquerade as a legacy OpenPose declaration.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from src.conditioning.openpose import CONTRACT as LEGACY_CONTRACT
from src.conditioning.openpose import OpenPoseDeclarationError, OpenPoseSelection, parse_declaration
from src.conditioning.openpose_snapshot import FrozenOpenPose

CONTRACT = "controlnet.v1"
UNIT_CONTRACT = "controlnet-unit.v1"
SLOT_FIELD = "controlnet_units"
MODALITIES = ("openpose", "canny", "depth")
MAX_UNITS = 2


def legacy_settings(raw: Mapping[str, Any]) -> dict[str, Any]:
    return {
        **{key: value for key, value in raw.items() if key != "modality"},
        "contract": LEGACY_CONTRACT,
    }


@dataclass(frozen=True, slots=True)
class UnitSelection:
    modality: str
    settings: OpenPoseSelection

    def to_dict(self) -> dict[str, Any]:
        return {**self.settings.to_dict(), "contract": UNIT_CONTRACT, "modality": self.modality}


def parse_units(raw: Any) -> tuple[UnitSelection, ...]:
    """Validate even disabled declarations; automatic preprocessing is unqualified."""
    if (
        not isinstance(raw, Mapping)
        or set(raw) != {"contract", "units"}
        or raw.get("contract") != CONTRACT
    ):
        raise OpenPoseDeclarationError(
            (f"ControlNet declaration must contain contract '{CONTRACT}' and units",)
        )
    units = raw.get("units")
    if not isinstance(units, list) or len(units) > MAX_UNITS:
        raise OpenPoseDeclarationError(
            ("ControlNet units must be an ordered list of at most two units",)
        )
    selections = []
    for index, unit in enumerate(units):
        if (
            not isinstance(unit, Mapping)
            or unit.get("contract") != UNIT_CONTRACT
            or unit.get("modality") not in MODALITIES
        ):
            raise OpenPoseDeclarationError(
                (f"ControlNet unit {index + 1}: invalid contract or unsupported modality",)
            )
        if unit.get("preprocessor", "None") != "None":
            raise OpenPoseDeclarationError(
                (
                    f"ControlNet unit {index + 1}: automatic preprocessing is unqualified; supply a pre-rendered map with preprocessor None",
                )
            )
        try:
            settings = parse_declaration(legacy_settings(unit))
        except OpenPoseDeclarationError as exc:
            raise OpenPoseDeclarationError(
                tuple(f"ControlNet unit {index + 1}: {item}" for item in exc.problems)
            ) from exc
        selections.append(UnitSelection(unit["modality"], settings))
    return tuple(selections)


def declaration_problems(raw: Any) -> tuple[str, ...]:
    try:
        parse_units(raw)
    except OpenPoseDeclarationError as exc:
        return exc.problems
    return ()


def enabled(raw: Any) -> bool:
    """Malformed intent remains active so consumers refuse it rather than dropping it."""
    if raw is None:
        return False
    try:
        return any(unit.settings.enabled for unit in parse_units(raw))
    except OpenPoseDeclarationError:
        return True


@dataclass(frozen=True, slots=True)
class FrozenUnit:
    modality: str
    image: FrozenOpenPose

    def to_config(self) -> dict[str, Any]:
        return {**self.image.to_config(), "contract": UNIT_CONTRACT, "modality": self.modality}

    def evidence(self) -> dict[str, Any]:
        return {**self.image.evidence(), "contract": UNIT_CONTRACT, "modality": self.modality}


@dataclass(frozen=True, slots=True)
class FrozenControlNet:
    units: tuple[FrozenUnit, ...]

    def to_config(self) -> dict[str, Any]:
        return {"contract": CONTRACT, "units": [unit.to_config() for unit in self.units]}

    def evidence(self) -> dict[str, Any]:
        return {"contract": CONTRACT, "units": [unit.evidence() for unit in self.units]}

    @classmethod
    def from_config(cls, raw: Any) -> FrozenControlNet:
        if (
            not isinstance(raw, Mapping)
            or set(raw) != {"contract", "units"}
            or raw.get("contract") != CONTRACT
        ):
            raise OpenPoseDeclarationError(("invalid frozen ControlNet envelope",))
        units = raw.get("units")
        if not isinstance(units, (list, tuple)) or not 1 <= len(units) <= MAX_UNITS:
            raise OpenPoseDeclarationError(
                ("frozen ControlNet requires one or two ordered enabled units",)
            )
        result = []
        for unit in units:
            if (
                not isinstance(unit, Mapping)
                or unit.get("contract") != UNIT_CONTRACT
                or unit.get("modality") not in MODALITIES
            ):
                raise OpenPoseDeclarationError(
                    ("invalid frozen ControlNet unit contract or modality",)
                )
            result.append(
                FrozenUnit(unit["modality"], FrozenOpenPose.from_config(legacy_settings(unit)))
            )
        return cls(tuple(result))
