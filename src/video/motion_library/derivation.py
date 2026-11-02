"""Operator-facing text for a converted clip's derivation (PR-VID-MOTION-354).

Original and derivative are kept apart on purpose: the clip's SHA-256 is its own identity, the animation file's SHA-256 is the
identity of what it was rendered from.  When the original is no longer where it was recorded the text says so; the derived
clip stays fully usable because its provenance record carries the rest.
"""

from __future__ import annotations

from src.video.motion_library.models import DerivationRecord

PROFILE_TEXT = {
    "character_reference": "character render",
    "high_contrast_silhouette": "silhouette render",
    "skeleton_reference": "skeleton render (not an OpenPose map)",
}
CAMERA_MODE_TEXT = {"static": "static camera", "tracking": "camera follows the subject"}
ROOT_TEXT = {
    "preserve": "original root motion kept",
    "in_place": "root translation removed (in place)",
}


def derivation_lines(
    derivation: DerivationRecord, *, source_present: bool | None
) -> tuple[str, ...]:
    """Lines for the detail pane.  ``source_present`` is ``None`` when it was not checked."""

    if source_present is None:
        presence = ""
    elif source_present:
        presence = " (original file present)"
    else:
        presence = " (original file NOT found at the recorded path; this clip and its record are unaffected)"
    lines = [
        "DERIVED clip: rendered from an animation file, not recorded footage.",
        f"Original: {derivation.source_name or 'unnamed'} [{derivation.source_type.upper() or '?'}]{presence}",
        f"Original SHA-256: {derivation.source_sha256}",
        "Render: "
        + ", ".join(
            filter(
                None,
                (
                    PROFILE_TEXT.get(derivation.profile, derivation.profile),
                    f"{derivation.camera.replace('_', '-')} view" if derivation.camera else "",
                    CAMERA_MODE_TEXT.get(derivation.camera_mode, derivation.camera_mode),
                    ROOT_TEXT.get(derivation.root_motion, derivation.root_motion),
                ),
            )
        ),
    ]
    if derivation.blender_version:
        lines.append(
            f"Blender {derivation.blender_version}, conversion script v{derivation.script_version or '?'}"
        )
    if derivation.provenance_path:
        lines.append(f"Conversion record: {derivation.provenance_path}")
    return tuple(lines)
