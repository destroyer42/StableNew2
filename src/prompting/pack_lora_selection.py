"""Explicit Klein selection over canonical exact-admission evidence; no I/O or rendering."""

from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass
from typing import Any

from src.image_backends.forge_klein_lora import (
    LORA_WEIGHT_MAX,
    KleinLoraDecision,
    KleinLoraStatus,
    LoraResolver,
)
from src.image_backends.model_policy import LORA_POLICY_KLEIN_4B_EXPLICIT, ModelPolicy

CONTRACT = "klein_lora_selection/1"
SELECTION_METADATA_KEY = "klein_lora_selection"


class KleinSelectionError(ValueError):
    """No work may be admitted when preflight or operator selection is incomplete."""


@dataclass(frozen=True)
class SelectionChoice:
    mode: str
    index: int | None = None


def applies(policy: ModelPolicy) -> bool:
    feature = policy.feature("lora")
    return bool(
        policy.qualified
        and feature.supported
        and feature.limit == 1
        and feature.compatibility_policy == LORA_POLICY_KLEIN_4B_EXPLICIT
    )


@dataclass(frozen=True)
class KleinLoraAssessment:
    policy_id: str
    profile_json: str
    source: tuple[Any, ...]
    decisions: tuple[KleinLoraDecision, ...]
    label: str = "Prompt"

    @property
    def compatible_indices(self) -> tuple[int, ...]:
        return tuple(i for i, d in enumerate(self.decisions) if d.runnable)

    @property
    def requires_choice(self) -> bool:
        return len(self.compatible_indices) > 1

    def choose(self, choice: SelectionChoice) -> KleinLoraSelection:
        candidates = self.compatible_indices
        index = choice.index
        if choice.mode == "auto":
            if self.requires_choice:
                raise KleinSelectionError(
                    "Multiple verified Klein LoRAs require an operator choice"
                )
            index = candidates[0] if candidates else None
        elif choice.mode in {"first", "last"} and candidates:
            index = candidates[0 if choice.mode == "first" else -1]
        elif choice.mode == "none":
            index = None
        elif choice.mode != "specific":
            raise KleinSelectionError("Invalid or cancelled Klein LoRA selection")
        elif index is None:
            raise KleinSelectionError(
                "A specific Klein LoRA selection needs a compatible candidate"
            )
        if index is not None and (type(index) is not int or index not in candidates):
            raise KleinSelectionError("Select a verified-compatible Klein LoRA or none")
        if index is not None:
            weight = self.source[index].weight
            if not math.isfinite(weight) or not 0 < weight <= LORA_WEIGHT_MAX:
                raise KleinSelectionError(
                    "Selected Klein LoRA weight is outside the qualified range"
                )
        return KleinLoraSelection(self, choice.mode, index)


@dataclass(frozen=True)
class KleinLoraSelection:
    assessment: KleinLoraAssessment
    choice: str
    index: int | None

    @property
    def selected(self) -> tuple[Any, ...]:
        return (self.assessment.source[self.index],) if self.index is not None else ()

    def validate(self, policy: ModelPolicy, source: tuple[Any, ...]) -> None:
        if (
            not applies(policy)
            or policy.policy_id != self.assessment.policy_id
            or json.dumps(policy.profile_ref, sort_keys=True) != self.assessment.profile_json
            or source != self.assessment.source
        ):
            raise KleinSelectionError(
                "Klein selection does not match frozen source/target; rebuild Preview"
            )
        # Revalidate the choice without accepting injected or corrupted indexes.
        self.assessment.choose(
            SelectionChoice("specific" if self.index is not None else "none", self.index)
        )

    def to_dict(self) -> dict[str, Any]:
        source = [asdict(lora) for lora in self.assessment.source]
        return {
            "contract": CONTRACT,
            "policy_id": self.assessment.policy_id,
            "profile_ref": json.loads(self.assessment.profile_json),
            "choice": self.choice,
            "source_loras": source,
            "source_loras_sha256": lora_source_digest(source),
            "selected": (
                {
                    **source[self.index],
                    **self.assessment.decisions[self.index].as_dict(),
                    "index": self.index,
                }
                if self.index is not None
                else None
            ),
            "excluded": [
                {
                    **source[i],
                    **decision.as_dict(),
                    "index": i,
                    "exclusion_reason": "not_selected"
                    if decision.runnable
                    else "not_positively_verified",
                }
                for i, decision in enumerate(self.assessment.decisions)
                if i != self.index
            ],
        }


def lora_source_digest(source: Sequence[Mapping[str, Any]]) -> str:
    """Canonical JSON fingerprint of ordered structured contributions, never asset bytes."""
    payload = json.dumps([dict(item) for item in source], sort_keys=True, allow_nan=False)
    return hashlib.sha256(payload.encode()).hexdigest()


def selection_manifest_is_consistent(manifest: Mapping[str, Any]) -> bool:
    """Validate frozen source/choice/exclusion consistency without reassessing compatibility."""
    try:
        source = manifest["source_loras"]
        if not isinstance(source, (list, tuple)):
            return False
        for item in source:
            if (
                not isinstance(item, Mapping)
                or set(item) != {"name", "weight", "kind"}
                or not isinstance(item["name"], str)
                or not item["name"]
                or item["kind"] not in {"actor", "pack", "style"}
                or type(item["weight"]) not in (int, float)
                or not math.isfinite(item["weight"])
            ):
                return False
        if lora_source_digest(source) != manifest["source_loras_sha256"]:
            return False
        selected, excluded = manifest["selected"], manifest["excluded"]
        if not isinstance(excluded, (list, tuple)):
            return False
        if selected is not None and not isinstance(selected, Mapping):
            return False
        entries = [*excluded, *([selected] if selected is not None else [])]
        indices = []
        compatible = []
        for item in entries:
            if not isinstance(item, Mapping):
                return False
            index = item["index"]
            if type(index) is not int or not 0 <= index < len(source):
                return False
            if any(item[key] != source[index][key] for key in ("name", "weight", "kind")):
                return False
            if item["status"] not in {status.value for status in KleinLoraStatus}:
                return False
            if not all(
                isinstance(item[key], str)
                for key in ("reason", "evidence_source", "evidence_raw_value", "sha256")
            ):
                return False
            if item["status"] == KleinLoraStatus.COMPATIBLE.value:
                digest = item["sha256"]
                if len(digest) != 64 or any(c not in "0123456789abcdef" for c in digest):
                    return False
                compatible.append(index)
            if item is not selected and item["exclusion_reason"] != (
                "not_selected" if item["status"] == "compatible" else "not_positively_verified"
            ):
                return False
            indices.append(index)
        if sorted(indices) != list(range(len(source))):
            return False
        compatible.sort()
        chosen = selected["index"] if selected is not None else None
        if chosen is not None and chosen not in compatible:
            return False
        choice = manifest["choice"]
        if choice == "none":
            return chosen is None
        if choice == "auto":
            return len(compatible) <= 1 and chosen == (compatible[0] if compatible else None)
        if choice in {"first", "last"}:
            return bool(compatible) and chosen == compatible[0 if choice == "first" else -1]
        return choice == "specific" and chosen is not None
    except (KeyError, TypeError, ValueError, OverflowError):
        return False


def assess_target_loras(
    policy: ModelPolicy, loras: tuple[Any, ...], resolver: LoraResolver, *, label: str = "Prompt"
) -> KleinLoraAssessment:
    if not applies(policy):
        raise KleinSelectionError(
            "Explicit selection requires the exact qualified Klein LoRA policy"
        )
    decisions = []
    try:
        for lora in loras:
            decision = resolver(lora.name)
            if not isinstance(decision, KleinLoraDecision) or decision.name != lora.name:
                raise ValueError("invalid assessment")
            if not isinstance(decision.status, KleinLoraStatus):
                raise ValueError("unknown assessment status")
            if decision.runnable and (
                len(decision.sha256) != 64
                or any(c not in "0123456789abcdef" for c in decision.sha256)
            ):
                raise ValueError("compatible adapter has no byte identity")
            decisions.append(decision)
    except Exception as exc:
        raise KleinSelectionError(
            "Klein LoRA evidence assessment failed; refresh assets and rebuild Preview"
        ) from exc
    return KleinLoraAssessment(
        policy.policy_id,
        json.dumps(policy.profile_ref, sort_keys=True),
        loras,
        tuple(decisions),
        label,
    )
