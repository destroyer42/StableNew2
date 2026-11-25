"""Verified relationships between representations of one movement (PR-VID-MOTION-430).

``movement_key`` is the identity of *what movement was rendered and how it was filmed*, independent of the render profile.  A
controlled representation comparison (character vs silhouette vs skeleton) is only offered when every variant's own conversion
record proves the same key and its published video still hashes to the catalog asset.  Otherwise the relationship is reported as
unverified and the comparison stays exploratory.

Nothing here converts, imports or renders: it reads ``provenance.json`` records that already exist and compares plain values.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from src.video.motion_conversion.conversion_service import read_provenance
from src.video.motion_library.models import MotionAsset
from src.video.workflow_conditioning import PROFILE_REPRESENTATION, REPRESENTATION_LABELS

KEY_VERSION = 1
_MESH_REPRESENTATIONS = ("rendered_character", "rendered_silhouette")

Reader = Callable[[str], "dict[str, Any] | None"]


def _mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _canonical(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode(
        "utf-8"
    )


MAX_RECORD_BYTES = (
    4 * 1024 * 1024
)  # a conversion record is a few kilobytes; never read an unbounded file named by a catalog


def _bounded_reader(path: str) -> dict[str, Any] | None:
    try:
        if Path(path).stat().st_size > MAX_RECORD_BYTES:
            return None
    except OSError:
        return None
    return read_provenance(path)


def movement_key(plan_record: Mapping[str, Any]) -> str:
    """Digest of a conversion plan record with the render profile, character binding and workflow target removed.

    Included: the animation bytes and route, exact source-frame sampling (rates, window, every sampled frame), camera and its
    mode, root-motion policy, output geometry, axis conventions, renderer and the Blender / script versions.  Excluded because
    they differ by design between profiles (or do not change the movement): ``profile``, ``character``, ``binding``,
    ``binding_mapping``, ``workflow``."""

    source = _mapping(plan_record.get("source"))
    payload = {
        "version": KEY_VERSION,
        "source": {k: source.get(k) for k in ("sha256", "type", "route")},
        "rig_fingerprint": plan_record.get("rig_fingerprint"),
        "camera": plan_record.get("camera"),
        "camera_mode": plan_record.get("camera_mode"),
        "root_motion": plan_record.get("root_motion"),
        "timing": plan_record.get("timing"),
        "geometry": plan_record.get("geometry"),
        "transform": plan_record.get("transform"),
        "renderer": plan_record.get("renderer"),
        "blender_version": plan_record.get("blender_version"),
        "script_version": plan_record.get("script_version"),
    }
    return hashlib.sha256(_canonical(payload)).hexdigest()


def movement_key_of_record(record: Mapping[str, Any]) -> str:
    """The key of a whole ``provenance.json`` record, or ``""`` when it carries no plan."""

    plan = record.get("plan")
    return movement_key(plan) if isinstance(plan, Mapping) else ""


@dataclass(frozen=True, slots=True)
class VariantEvidence:
    asset_id: str
    sha256: str
    profile: str
    representation: str
    movement_key: str
    verified: bool
    problem: str = ""
    plan_digest: str = ""
    character_mode: str = ""
    character_sha256: str = ""
    rig_fingerprint: str = ""

    @property
    def label(self) -> str:
        return REPRESENTATION_LABELS.get(self.representation, self.profile or "unknown")


@dataclass(frozen=True, slots=True)
class RepresentationEvidence:
    variants: tuple[VariantEvidence, ...]
    #: Every variant's own record proves the same movement key and its bytes match the catalog.
    common_movement_verified: bool
    #: Verified common movement *and* at least two distinct representations: a controlled representation comparison.
    controlled: bool
    movement_key: str = ""
    disclosures: tuple[str, ...] = ()
    problems: tuple[str, ...] = ()

    @property
    def representations(self) -> tuple[str, ...]:
        return tuple(sorted({v.representation for v in self.variants if v.representation}))

    def kind_label(self) -> str:
        if self.controlled:
            return "Controlled representation comparison (verified common movement)"
        return "Exploratory (relationship between the representations is not verified)"

    def binding_for(self, asset_id: str) -> dict[str, Any] | None:
        """The additive suite binding fields for one verified variant, or ``None`` when it is not verified."""

        for v in self.variants:
            if v.asset_id == asset_id and v.verified and self.common_movement_verified:
                return {
                    "representation": v.representation,
                    "movement_key": v.movement_key,
                    "profile": v.profile,
                    "plan_digest": v.plan_digest,
                }
        return None


def verify_variant(asset: MotionAsset, read: Reader | None = None) -> VariantEvidence:
    """Re-verify one converted asset against its own conversion record."""

    reader: Reader = read or _bounded_reader
    derivation = asset.derivation
    profile = derivation.profile if derivation is not None else ""
    representation = PROFILE_REPRESENTATION.get(profile, "")

    def bad(problem: str) -> VariantEvidence:
        return VariantEvidence(
            asset.asset_id, asset.sha256, profile, representation, "", False, problem
        )

    if derivation is None:
        return bad("not a converted clip")
    if not derivation.provenance_path:
        return bad("no conversion record is linked to this clip")
    record = reader(derivation.provenance_path)
    if record is None:
        return bad("the conversion record is missing, unreadable or of another schema")
    output = _mapping(record.get("output"))
    if str(output.get("sha256") or "") != asset.sha256:
        return bad("the conversion record describes different video bytes than the catalog asset")
    source = _mapping(record.get("source"))
    if str(source.get("sha256") or "") != derivation.source_sha256:
        return bad("the conversion record names a different animation file than the catalog")
    key = movement_key_of_record(record)
    if not key:
        return bad("the conversion record carries no plan")
    if derivation.movement_key and derivation.movement_key != key:
        return bad("the catalog's stored movement key disagrees with the conversion record")
    character = _mapping(record.get("character"))
    rig = _mapping(record.get("rig"))
    return VariantEvidence(
        asset_id=asset.asset_id,
        sha256=asset.sha256,
        profile=str(_mapping(record.get("conversion")).get("profile") or profile),
        representation=representation,
        movement_key=key,
        verified=True,
        plan_digest=str(record.get("plan_digest") or ""),
        character_mode=str(character.get("mode") or ""),
        character_sha256=str(character.get("sha256") or ""),
        rig_fingerprint=str(rig.get("fingerprint") or ""),
    )


def verify_variants(
    assets: Iterable[MotionAsset], read: Reader | None = None
) -> RepresentationEvidence:
    """Whether ``assets`` are verifiably representations of one movement, and what differs between them."""

    variants = tuple(verify_variant(a, read) for a in assets)
    problems = tuple(f"{v.asset_id}: {v.problem}" for v in variants if not v.verified)
    verified = [v for v in variants if v.verified]
    keys = {v.movement_key for v in verified}
    common = bool(verified) and len(verified) == len(variants) and len(keys) == 1
    if verified and len(keys) > 1:
        problems += (
            "the clips were not rendered from the same movement under identical parameters",
        )
    representations = {v.representation for v in verified if v.representation}
    controlled = common and len(representations) >= 2 and len(verified) >= 2
    disclosures: list[str] = []
    if common and len(variants) >= 2:
        disclosures.append(
            "Same animation file, frame window, camera, root-motion policy, geometry, rates and tool versions "
            "(identical movement key); each clip keeps its own bytes and identity."
        )
        if len({v.profile for v in verified}) > 1:
            disclosures.append(
                "Render profile differs by design: the pixels depict a character, a silhouette or a skeleton."
            )
        if representations & set(_MESH_REPRESENTATIONS) and "rendered_skeleton" in representations:
            disclosures.append(
                "A skeleton render has no body shape, clothing or face; head orientation and secondary motion are "
                "only as present as the drawn bones."
            )
        if (
            len(
                {
                    (v.character_mode, v.character_sha256)
                    for v in verified
                    if v.representation != "rendered_skeleton"
                }
            )
            > 1
        ):
            disclosures.append(
                "The rendered characters differ between mesh variants; body proportions may differ."
            )
        if len({v.rig_fingerprint for v in verified}) > 1:
            disclosures.append("The rig fingerprints differ between variants.")
        disclosures.append(
            "A shared movement key does not prove the renders are visually equivalent motion; it removes the camera, "
            "timing and root-motion differences from the comparison."
        )
    return RepresentationEvidence(
        variants=variants,
        common_movement_verified=common,
        controlled=controlled,
        movement_key=next(iter(keys)) if common else "",
        disclosures=tuple(disclosures),
        problems=problems,
    )


def verify_bindings(
    bindings: Sequence[Mapping[str, Any]],
    assets_by_id: Mapping[str, MotionAsset],
    read: Reader | None = None,
) -> RepresentationEvidence:
    """Verify the library assets a set of suite case bindings names (an unknown asset is a reported problem)."""

    found = [
        assets_by_id[str(b.get("asset_id"))]
        for b in bindings
        if str(b.get("asset_id")) in assets_by_id
    ]
    result = verify_variants(found, read)
    missing = [
        str(b.get("asset_id")) for b in bindings if str(b.get("asset_id")) not in assets_by_id
    ]
    if missing:
        return RepresentationEvidence(
            result.variants,
            False,
            False,
            "",
            result.disclosures,
            (*result.problems, *(f"{m}: not in the Motion Library" for m in missing)),
        )
    return result


__all__ = [
    "KEY_VERSION",
    "RepresentationEvidence",
    "VariantEvidence",
    "movement_key",
    "movement_key_of_record",
    "verify_bindings",
    "verify_variant",
    "verify_variants",
]
