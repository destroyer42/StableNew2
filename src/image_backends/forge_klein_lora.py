"""FLUX.2 Klein 4B LoRA compatibility interpretation and v2 admission (PR-IMG-117).

``AssetRegistry`` stays the only local asset identity authority: it hashes the bytes (SHA-256), reads the
safetensors header and the CivitAI-style sidecar, and keeps that evidence per location. Its generic
``src.assets.compatibility`` profile deliberately knows only coarse families and (by design) does not
recognize ``flux2_klein_4b``. This module is the one narrow *consumer* that answers the Klein-specific
question for profile v2: "does the metadata the registry already preserved explicitly establish
FLUX.2 Klein 4B?". It never hashes, scans, rewrites or caches anything, and it never infers compatibility
from a filename, from Forge listing the adapter, from generic FLUX evidence, or from the operator's choice.

Evidence rules (exact whole-value matches, no substring matching):

* an exact Klein-4B value in a supported embedded/sidecar base-model field -> compatible;
* an explicit other FLUX variant (a different FLUX.1/FLUX.2 form) -> incompatible;
* a resolved SD1/SD2/SDXL/SD3 family -> incompatible;
* Klein-4B evidence alongside any contradicting evidence -> conflicting;
* generic FLUX, unknown, or no evidence -> unverified (not runnable for Klein v2).
"""

from __future__ import annotations

import math
import re
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from enum import Enum
from typing import Any

from src.assets.compatibility import (
    EMBEDDED_BASE_MODEL_KEYS,
    SIDECAR_BASE_MODEL_KEYS,
    CompatibilityStatus,
    ModelFamily,
)

#: Exact normalized values (lowercase, ``/`` separators) that identify FLUX.2 Klein 4B. The distilled model
#: and the base model share the 4B architecture; adapters are trained on the base and run on the distilled
#: model (Black Forest Labs' documented workflow). Only forms observed in real adapter metadata or published
#: model identifiers belong here; extend it with a proven form, never with a pattern.
KLEIN_4B_BASE_MODEL_VALUES = frozenset(
    {
        "flux2_klein_4b",
        "black-forest-labs/flux.2-klein-4b",
        "black-forest-labs/flux.2-klein-base-4b",
    }
)

#: An anchored FLUX.1 / FLUX.2 identifier that is not Klein 4B (e.g. ``flux2_klein_9b``,
#: ``black-forest-labs/FLUX.2-dev``, ``flux1_dev``). Anchored at both ends: never a substring test.
_OTHER_FLUX_VALUE = re.compile(r"^(?:[a-z0-9_.-]+/)?flux[._-]?[12](?:[._-][a-z0-9._-]*)?$")

_LORA_TAG = re.compile(r"<\s*(lora|lyco)\s*:([^>]*)>", re.IGNORECASE)

#: Weight bounds for the bounded v2 slice. Zero is a no-op adapter and is refused; the upper bound is the
#: conservative limit of this slice (the qualified adapter's published range is 0.5-1.0), not a model claim.
LORA_WEIGHT_MIN_EXCLUSIVE = 0.0
LORA_WEIGHT_MAX = 2.0


class KleinLoraStatus(str, Enum):
    COMPATIBLE = "compatible"
    UNVERIFIED = "unverified"
    INCOMPATIBLE = "incompatible"
    CONFLICTING = "conflicting"


@dataclass(frozen=True, slots=True)
class KleinLoraDecision:
    """The compatibility decision for one named LoRA; free of machine-local paths."""

    name: str
    status: KleinLoraStatus
    reason: str
    #: ``embedded_metadata:<field>`` or ``sidecar_metadata:<field>`` of the admitting evidence ("" otherwise).
    evidence_source: str = ""
    evidence_raw_value: str = ""
    sha256: str = ""

    @property
    def runnable(self) -> bool:
        return self.status is KleinLoraStatus.COMPATIBLE

    def as_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "status": self.status.value,
            "reason": self.reason,
            "evidence_source": self.evidence_source,
            "evidence_raw_value": self.evidence_raw_value,
            "sha256": self.sha256,
        }


LoraResolver = Callable[[str], KleinLoraDecision]


def normalize_evidence_value(raw: Any) -> str:
    return str(raw or "").strip().lower().replace("\\", "/")


def is_klein_4b_value(raw: Any) -> bool:
    return normalize_evidence_value(raw) in KLEIN_4B_BASE_MODEL_VALUES


def is_other_flux_value(raw: Any) -> bool:
    """An explicit FLUX identifier that is not Klein 4B (never true for the Klein 4B values)."""

    value = normalize_evidence_value(raw)
    return value not in KLEIN_4B_BASE_MODEL_VALUES and _OTHER_FLUX_VALUE.match(value) is not None


def _evidence_items(record: Any) -> list[tuple[str, str]]:
    """Every supported base-model field the registry preserved: ``(source, raw value)``, embedded first."""

    items: list[tuple[str, str]] = []
    embedded = getattr(record, "embedded_metadata", None)
    if isinstance(embedded, Mapping):
        for key in EMBEDDED_BASE_MODEL_KEYS:
            value = embedded.get(key)
            if value is not None and str(value).strip():
                items.append((f"embedded_metadata:{key}", str(value).strip()))
    for location in getattr(record, "locations", ()) or ():
        sidecar = getattr(location, "sidecar_metadata", None)
        if isinstance(sidecar, Mapping):
            for key in SIDECAR_BASE_MODEL_KEYS:
                value = sidecar.get(key)
                if value is not None and str(value).strip():
                    items.append((f"sidecar_metadata:{key}", str(value).strip()))
    return items


def classify_klein_lora(name: str, record: Any) -> KleinLoraDecision:
    """Decide Klein-4B compatibility from an ``AssetRecord`` (SHA-256 and metadata already preserved there)."""

    sha256 = str(getattr(record, "sha256", "") or "")
    items = _evidence_items(record)
    klein = [(src, raw) for src, raw in items if is_klein_4b_value(raw)]
    other_flux = [(src, raw) for src, raw in items if is_other_flux_value(raw)]
    profile = getattr(record, "compatibility", None)
    status = getattr(profile, "status", None)
    family = getattr(profile, "family", None)
    resolved_other = (
        status is CompatibilityStatus.RESOLVED
        and family is not None
        and family not in (ModelFamily.FLUX,)
    )
    registry_conflict = status is CompatibilityStatus.CONFLICTING

    def decision(kind: KleinLoraStatus, reason: str, source: str = "", raw: str = "") -> KleinLoraDecision:
        return KleinLoraDecision(name, kind, reason, source, raw, sha256)

    if klein and (other_flux or resolved_other or registry_conflict):
        contradicting = (
            other_flux[0][1] if other_flux else (family.value if resolved_other else "conflicting registry evidence")
        )
        return decision(
            KleinLoraStatus.CONFLICTING,
            f"its metadata names FLUX.2 Klein 4B ('{klein[0][1]}') but other evidence contradicts it "
            f"('{contradicting}')",
            *klein[0],
        )
    if registry_conflict:
        return decision(
            KleinLoraStatus.CONFLICTING, "its metadata names more than one model family"
        )
    if resolved_other and not klein:
        return decision(
            KleinLoraStatus.INCOMPATIBLE,
            f"its metadata resolves to the {family.value} family, not FLUX.2 Klein 4B",
        )
    if other_flux:
        return decision(
            KleinLoraStatus.INCOMPATIBLE,
            f"its metadata names a different FLUX variant ('{other_flux[0][1]}'), not FLUX.2 Klein 4B",
            *other_flux[0],
        )
    if klein:
        return decision(KleinLoraStatus.COMPATIBLE, "explicit FLUX.2 Klein 4B metadata", *klein[0])
    return decision(
        KleinLoraStatus.UNVERIFIED,
        "its local metadata does not establish FLUX.2 Klein 4B (generic FLUX, unknown or absent evidence); "
        "the adapter may still be valid, but StableNew cannot verify it for this model",
    )


def unavailable_decision(name: str, reason: str) -> KleinLoraDecision:
    return KleinLoraDecision(name, KleinLoraStatus.UNVERIFIED, reason)


def _name_keys(location: Any) -> set[str]:
    keys = {str(getattr(location, "display_name", "") or "").strip().lower()}
    try:
        relative = location.path.relative_to(location.root).with_suffix("")
        keys.add(relative.as_posix().lower())
    except (AttributeError, ValueError):
        pass
    keys.discard("")
    return keys


def find_lora_record(snapshot: Any, name: str) -> tuple[Any | None, str]:
    """The one LoRA ``AssetRecord`` a prompt tag names, or ``(None, reason)`` (missing or ambiguous)."""

    from src.assets import AssetKind

    wanted = str(name or "").strip().lower().replace("\\", "/")
    matches = [
        record
        for record in snapshot.records_for(AssetKind.LORA)
        if any(
            location.kind is AssetKind.LORA and wanted in _name_keys(location)
            for location in record.locations
        )
    ]
    if not matches:
        return None, f"LoRA '{name}' was not found in StableNew's local asset registry"
    if len(matches) > 1:
        return None, f"LoRA name '{name}' matches more than one distinct file in the local asset registry"
    return matches[0], ""


class RegistryLoraResolver:
    """Resolve a prompt LoRA name through ``AssetRegistry`` (the single local identity authority)."""

    def __init__(self, registry: Any | None = None, *, cache_only: bool = False) -> None:
        self._registry = registry
        #: UI projection mode: read the persisted registry snapshot only (no scan, no hashing). Admission
        #: (the backend) always refreshes, so a stale cache can only make the UI more cautious, never admit.
        self._cache_only = cache_only

    def _get_registry(self) -> Any:
        if self._registry is None:
            from src.assets import AssetRegistry

            self._registry = AssetRegistry()
        return self._registry

    def record_for(self, name: str) -> tuple[Any | None, str]:
        from src.assets import AssetKind

        registry = self._get_registry()
        if registry.webui_root is None:
            return None, "no local WebUI root is configured, so LoRA assets cannot be identified"
        if self._cache_only:
            return find_lora_record(registry.cached_snapshot(), name)
        result = registry.refresh(kinds={AssetKind.LORA})
        return find_lora_record(result.snapshot, name)

    def __call__(self, name: str) -> KleinLoraDecision:
        record, reason = self.record_for(name)
        if record is None:
            return unavailable_decision(name, reason)
        return classify_klein_lora(name, record)

    def locations_for(self, name: str) -> tuple[str, ...]:
        """Local file paths of the named LoRA (used only to bind Forge's served file; never persisted)."""

        record, _ = self.record_for(name)
        return tuple(str(location.path) for location in getattr(record, "locations", ()) or ())


@dataclass(frozen=True, slots=True)
class LoraTag:
    name: str
    weight: float


def extract_lora_tags(prompt: str) -> tuple[tuple[LoraTag, ...], tuple[str, ...]]:
    """``<lora:name:weight>`` / ``<lyco:...>`` tags in a prompt, and the malformed ones (never dropped)."""

    tags: list[LoraTag] = []
    malformed: list[str] = []
    for match in _LORA_TAG.finditer(str(prompt or "")):
        body = match.group(2).strip()
        name, sep, weight_text = body.rpartition(":")
        name = name.strip()
        try:
            weight = float(weight_text)
        except ValueError:
            weight = math.nan
        if not sep or not name or not math.isfinite(weight):
            malformed.append(match.group(0))
            continue
        tags.append(LoraTag(name, weight))
    return tuple(tags), tuple(malformed)


def evaluate_klein_loras(
    *,
    max_loras: int,
    prompt: str,
    declared: Sequence[tuple[str, float]] = (),
    lora_strength_overrides: bool = False,
    resolver: LoraResolver | None,
) -> tuple[list[str], tuple[KleinLoraDecision, ...], tuple[LoraTag, ...]]:
    """Problems, per-LoRA decisions and the effective tags for a Klein profile that allows LoRA.

    ``declared`` are the NJR's ``LoRATag`` intents: each must appear in the rendered prompt (a declared LoRA
    that Forge would never receive is rejected, never silently dropped). Nothing here rewrites the prompt.
    """

    problems: list[str] = []
    tags, malformed = extract_lora_tags(prompt)
    problems.extend(f"malformed LoRA tag {tag!r}" for tag in malformed)
    if lora_strength_overrides:
        problems.append("per-LoRA strength overrides (lora_strengths) are not applied by this profile")
    if len(tags) > max_loras:
        listed = ", ".join(f"{tag.name}:{tag.weight:g}" for tag in tags)
        problems.append(
            f"{len(tags)} LoRAs are requested ({listed}) but this profile admits at most {max_loras}"
        )
    rendered = {(tag.name.lower(), round(tag.weight, 9)) for tag in tags}
    for declared_name, declared_weight in declared:
        if (str(declared_name).lower(), round(float(declared_weight), 9)) not in rendered:
            problems.append(
                f"LoRA '{declared_name}' ({declared_weight:g}) is declared by the job but is not in the prompt Forge will receive"
            )
    decisions: list[KleinLoraDecision] = []
    for tag in tags:
        if not (LORA_WEIGHT_MIN_EXCLUSIVE < tag.weight <= LORA_WEIGHT_MAX):
            problems.append(
                f"LoRA '{tag.name}' weight {tag.weight:g} is outside the supported range "
                f"(>{LORA_WEIGHT_MIN_EXCLUSIVE:g} to {LORA_WEIGHT_MAX:g})"
            )
        decision = (
            resolver(tag.name)
            if resolver is not None
            else unavailable_decision(tag.name, "no LoRA compatibility resolver is available")
        )
        decisions.append(decision)
        if not decision.runnable:
            problems.append(
                f"LoRA '{tag.name}' is not verified for FLUX.2 Klein 4B ({decision.status.value}): {decision.reason}"
            )
    return problems, tuple(decisions), tags


# Forge's console handler wraps and right-pads each record (``[LORA] Loaded <file>  networks.py :: INFO`` then
# ``for KModel-UNet with 80 keys at weight 0.8 (skipped 0`` then ``keys) with on_the_fly = False``), so the log is
# normalized to one line per ``[LORA]`` record before it is read.
_LOG_SOURCE_TAG = re.compile(r"\b\w+\.py :: (?:INFO|WARNING|ERROR|DEBUG)\b")
_LOADED = re.compile(
    r"^\[LORA\] Loaded (?P<file>\S+) for (?P<model>\S+) with (?P<keys>\d+) keys at weight "
    r"(?P<weight>[-+0-9.eE]+) \(skipped (?P<skipped>\d+)"
)
_MISMATCH = re.compile(r"^\[LORA\] (?:LoRA mismatch|Mismatch)\b")


def observe_lora_consumption(log_lines: Sequence[str], filename_stem: str) -> dict[str, Any]:
    """What Forge's own log says about applying ``filename_stem`` (read-only; never raises).

    ``consumed`` is True only on a ``[LORA] Loaded <file> for <model> with N keys at weight W`` record for that
    file, ``False`` on a mismatch record that names it, and ``None`` when the log says nothing (Forge caches an
    identical adapter set, so a repeated job may legitimately log nothing). The last record decides.
    """

    stem = str(filename_stem or "").lower()
    result: dict[str, Any] = {"consumed": None, "source": "forge_stdout"}
    text = re.sub(r"\s+", " ", _LOG_SOURCE_TAG.sub(" ", " ".join(str(line) for line in log_lines or ())))
    for record in re.split(r"(?=\[LORA\])", text):
        record = record.strip()
        if not record.startswith("[LORA]") or (stem and stem not in record[:400].lower()):
            continue
        loaded = _LOADED.match(record)
        if loaded is not None and stem in loaded.group("file").lower():
            result.update(
                consumed=True,
                keys=int(loaded.group("keys")),
                skipped=int(loaded.group("skipped")),
                weight=float(loaded.group("weight")),
                model=loaded.group("model"),
            )
            result.pop("line", None)
        elif _MISMATCH.match(record) is not None:
            result.update(consumed=False, line=record[:300])
    return result


__all__ = [
    "KLEIN_4B_BASE_MODEL_VALUES",
    "LORA_WEIGHT_MAX",
    "LORA_WEIGHT_MIN_EXCLUSIVE",
    "KleinLoraDecision",
    "KleinLoraStatus",
    "LoraTag",
    "RegistryLoraResolver",
    "classify_klein_lora",
    "evaluate_klein_loras",
    "extract_lora_tags",
    "find_lora_record",
    "is_klein_4b_value",
    "is_other_flux_value",
    "observe_lora_consumption",
    "unavailable_decision",
]
