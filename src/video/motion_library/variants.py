"""Related representations of one movement in the Motion Library (PR-VID-MOTION-430).

A converted clip's ``DerivationRecord`` carries the identity of the animation file it was rendered from and, since this package,
a ``movement_key``: the SHA-256 of every conversion choice *except the render profile* (animation bytes, frame window and
rates, camera, root-motion policy, geometry, axis conventions, renderer and tool versions).  Clips whose keys are equal were
rendered from the same movement under identical production parameters, so a character, a silhouette and a skeleton render of it
are related variants.

This module only groups catalog records.  It reads no file and decodes no video, so the browser can use it freely.  A stored key is
the catalog's own claim; ``src/video/motion_conversion/representation.py`` re-verifies it against the conversion record before an
evaluation relies on it.  Each variant keeps its own asset identity and bytes: nothing here merges or deduplicates anything, and a
clip converted before this field existed simply has no key (it is never guessed into a group).
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable, Sequence
from dataclasses import dataclass

from src.video.motion_library.models import MotionAsset
from src.video.workflow_conditioning import PROFILE_REPRESENTATION, REPRESENTATION_LABELS


@dataclass(frozen=True, slots=True)
class VariantRef:
    asset_id: str
    name: str
    sha256: str
    profile: str
    representation: str

    @property
    def label(self) -> str:
        return REPRESENTATION_LABELS.get(
            self.representation, self.profile or "unknown representation"
        )


@dataclass(frozen=True, slots=True)
class VariantGroup:
    """Catalog assets that claim the same movement key (not yet verified against their conversion records)."""

    source_sha256: str
    movement_key: str
    members: tuple[VariantRef, ...]

    @property
    def representations(self) -> tuple[str, ...]:
        return tuple(sorted({m.representation for m in self.members}))

    @property
    def multi_representation(self) -> bool:
        return len(self.representations) >= 2


def variant_ref(asset: MotionAsset) -> VariantRef | None:
    derivation = asset.derivation
    if derivation is None or not derivation.movement_key:
        return None
    return VariantRef(
        asset_id=asset.asset_id,
        name=asset.display_name or asset.asset_id,
        sha256=asset.sha256,
        profile=derivation.profile,
        representation=PROFILE_REPRESENTATION.get(derivation.profile, ""),
    )


def group_variants(assets: Iterable[MotionAsset]) -> dict[tuple[str, str], VariantGroup]:
    """Groups of assets that share an animation file *and* a movement key (one entry per distinct pair)."""

    buckets: dict[tuple[str, str], list[VariantRef]] = defaultdict(list)
    for asset in assets:
        ref = variant_ref(asset)
        if ref is not None and asset.derivation is not None:
            buckets[(asset.derivation.source_sha256, asset.derivation.movement_key)].append(ref)
    return {
        key: VariantGroup(key[0], key[1], tuple(sorted(members, key=lambda m: m.asset_id)))
        for key, members in buckets.items()
    }


def related_variants(assets: Sequence[MotionAsset], asset: MotionAsset) -> tuple[VariantRef, ...]:
    """The other catalog assets rendered from the same movement under the same parameters (never ``asset`` itself)."""

    derivation = asset.derivation
    if derivation is None or not derivation.movement_key:
        return ()
    group = group_variants(assets).get((derivation.source_sha256, derivation.movement_key))
    if group is None:
        return ()
    return tuple(m for m in group.members if m.asset_id != asset.asset_id)


def variant_lines(asset: MotionAsset, related: Sequence[VariantRef]) -> tuple[str, ...]:
    """Detail-pane lines about related variants; honest about clips whose relationship cannot be known."""

    derivation = asset.derivation
    if derivation is None:
        return ()
    if not derivation.movement_key:
        return (
            "Related variants: not tracked for this clip (converted before representation tracking); "
            "it is never grouped by name or by a shared animation file alone.",
        )
    if not related:
        return ("Related variants: no other representation of this movement is in the library.",)
    lines = [
        "Related variants (same animation file, frame window, camera, root-motion policy and geometry; each keeps its "
        "own identity):"
    ]
    lines.extend(f"  {ref.label}: {ref.name} [{ref.asset_id}]" for ref in related)
    lines.append(
        "A shared movement does not make the renders interchangeable: what each shows (body shape, texture, head "
        "orientation) differs by profile."
    )
    return tuple(lines)


__all__ = [
    "VariantGroup",
    "VariantRef",
    "group_variants",
    "related_variants",
    "variant_lines",
    "variant_ref",
]
