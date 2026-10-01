"""PR-VID-192 motion-source qualification corpus (qualification-only; NOT a product library).

Records what a driving clip is, where it came from and what it shows, so Animate-2 drive behavior can
be characterised against a small, honest set of motion sources.  It deliberately does not extend
``src.assets.AssetRegistry`` (the local model/resource registry) and stores no media in Git:

* ``annotations.json`` (tracked) holds the human judgments and provenance per candidate; a clip's
  location is a repo-relative path or ``$QUAL/<path>`` under the machine-local qualification root.
* ``build`` probes every file (ffprobe), hashes it and writes an inventory with **no absolute local
  paths**; a machine-local manifest may add resolved paths outside Git.

    python -m tools.qualification.vid192.motion_corpus build \
        --annotations tools/qualification/vid192/corpus_annotations.json \
        --qual-root <machine-local qualification root> \
        --out tools/qualification/vid192/corpus_inventory.json
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
import subprocess
import sys
from collections.abc import Mapping
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[3]
QUAL_PREFIX = "$QUAL/"

# Media that may live inside the working tree (never committed: reports/ and output/ are untracked).
REPO_SAFE_LICENSES = frozenset({"owner_created", "stablenew_generated", "public_domain_cc0"})
LICENSE_STATUSES = REPO_SAFE_LICENSES | {"third_party_internal_only", "unknown"}
FLAGGED_LICENSES = frozenset({"third_party_internal_only", "unknown"})

SUBJECT_COUNTS = ("single", "multiple")
BODY_VISIBILITY = ("full_body", "upper_body", "partial")
CAMERA_MOVEMENT = ("static", "pan_or_tilt", "tracking", "handheld")
OCCLUSION = ("none", "low", "moderate", "high")
MOTION_INTENSITY = ("low", "moderate", "high")

# The recorded properties every entry must carry (the PR-VID-192 corpus contract).
ANNOTATION_FIELDS = (
    "asset_id",
    "local_path",
    "source",
    "license_status",
    "subjects",
    "body_visibility",
    "camera_movement",
    "occlusion",
    "motion_tags",
    "motion_intensity",
    "start_pose_notes",
    "end_pose_notes",
)
PROBED_FIELDS = ("sha256", "width", "height", "fps", "frame_count", "duration_s")
_ABSOLUTE_PATH = re.compile(r"^(?:[A-Za-z]:[\\/]|/(?:Users|home)/|\\\\)")


class CorpusError(ValueError):
    """An annotation or media file breaks the corpus contract."""


def is_absolute_local(text: str) -> bool:
    return bool(_ABSOLUTE_PATH.match(text))


def parse_ffprobe(stdout: str) -> dict[str, Any]:
    """Width/height/fps/frame count/duration from ``ffprobe -count_frames -show_streams`` JSON."""

    streams = json.loads(stdout).get("streams") or []
    stream = next((s for s in streams if s.get("codec_type", "video") == "video"), None)
    if stream is None:
        raise CorpusError("no video stream found")
    numerator, _, denominator = str(stream.get("r_frame_rate") or "0/1").partition("/")
    fps = float(numerator) / float(denominator or 1) if float(denominator or 1) else 0.0
    frames = stream.get("nb_read_frames") or stream.get("nb_frames")
    if frames in (None, "N/A"):
        raise CorpusError("frame count unavailable (probe with -count_frames)")
    frame_count = int(frames)
    return {
        "width": int(stream["width"]),
        "height": int(stream["height"]),
        "fps": round(fps, 3),
        "frame_count": frame_count,
        "duration_s": round(frame_count / fps, 3) if fps else 0.0,
    }


def probe_video(path: Path, *, ffprobe: str | None = None) -> dict[str, Any]:
    binary = ffprobe or shutil.which("ffprobe")
    if not binary:
        raise CorpusError("ffprobe is not available")
    completed = subprocess.run(
        [binary, "-v", "error", "-count_frames", "-select_streams", "v:0", "-show_streams",
         "-of", "json", str(path)],
        capture_output=True, text=True, check=False,
    )  # fmt: skip
    if completed.returncode:
        raise CorpusError(f"ffprobe failed for {path.name}: {completed.stderr.strip()[:200]}")
    return parse_ffprobe(completed.stdout)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def resolve_local_path(locator: str, *, qual_root: Path | None, repo_root: Path = REPO_ROOT) -> Path:
    """A repo-relative locator, or ``$QUAL/<path>`` under the machine-local qualification root."""

    if is_absolute_local(locator):
        raise CorpusError(f"annotation paths must not be absolute local paths: {locator!r}")
    if locator.startswith(QUAL_PREFIX):
        if qual_root is None:
            raise CorpusError(f"{locator!r} needs --qual-root (or STABLENEW_QUAL_ROOT)")
        return qual_root / locator[len(QUAL_PREFIX) :]
    return repo_root / locator


def validate_annotation(entry: Mapping[str, Any]) -> list[str]:
    """Readable problems with one human annotation (empty when the entry is complete)."""

    problems = [f"missing '{field}'" for field in ANNOTATION_FIELDS if entry.get(field) in (None, "", [])]
    choices = {
        "license_status": LICENSE_STATUSES,
        "subjects": SUBJECT_COUNTS,
        "body_visibility": BODY_VISIBILITY,
        "camera_movement": CAMERA_MOVEMENT,
        "occlusion": OCCLUSION,
        "motion_intensity": MOTION_INTENSITY,
    }
    for field, allowed in choices.items():
        if entry.get(field) and entry[field] not in allowed:
            problems.append(f"'{field}' must be one of {sorted(allowed)}, got {entry[field]!r}")
    if entry.get("motion_tags") is not None and not isinstance(entry.get("motion_tags"), list):
        problems.append("'motion_tags' must be a list")
    locator = str(entry.get("local_path") or "")
    if locator and is_absolute_local(locator):
        problems.append("'local_path' must be repo-relative or $QUAL/... (no absolute local path)")
    if entry.get("license_status") == "third_party_internal_only" and not entry.get("license_note"):
        problems.append("third_party_internal_only entries need a 'license_note' (scope of use)")
    return problems


def build_entry(
    annotation: Mapping[str, Any],
    *,
    qual_root: Path | None,
    repo_root: Path = REPO_ROOT,
    ffprobe: str | None = None,
) -> dict[str, Any]:
    """Merge probed facts into an annotation; refuses media that cannot be kept out of Git."""

    problems = validate_annotation(annotation)
    if problems:
        raise CorpusError(f"{annotation.get('asset_id', '?')}: " + "; ".join(problems))
    path = resolve_local_path(str(annotation["local_path"]), qual_root=qual_root, repo_root=repo_root)
    if not path.is_file():
        raise CorpusError(f"{annotation['asset_id']}: media file not found ({annotation['local_path']})")
    inside_repo = repo_root.resolve() in path.resolve().parents
    if inside_repo and annotation["license_status"] not in REPO_SAFE_LICENSES:
        raise CorpusError(
            f"{annotation['asset_id']}: {annotation['license_status']} media must live outside the "
            "repository (never commit third-party or unknown-license video)"
        )
    entry = {key: value for key, value in annotation.items() if key != "local_path"}
    entry["locator"] = str(annotation["local_path"])
    entry["sha256"] = sha256_file(path)
    entry.update(probe_video(path, ffprobe=ffprobe))
    return entry


def build_inventory(
    annotations: list[Mapping[str, Any]],
    *,
    qual_root: Path | None,
    repo_root: Path = REPO_ROOT,
    ffprobe: str | None = None,
) -> dict[str, Any]:
    ids = [str(item.get("asset_id")) for item in annotations]
    duplicates = sorted({asset_id for asset_id in ids if ids.count(asset_id) > 1})
    if duplicates:
        raise CorpusError(f"duplicate asset ids: {duplicates}")
    entries = [
        build_entry(item, qual_root=qual_root, repo_root=repo_root, ffprobe=ffprobe)
        for item in sorted(annotations, key=lambda item: str(item.get("asset_id")))
    ]
    return {
        "schema_version": "1.0",
        "purpose": "PR-VID-192 Animate-2 drive qualification corpus (not a product library)",
        "entries": entries,
        "flagged_licenses": sorted(
            {entry["asset_id"] for entry in entries if entry["license_status"] in FLAGGED_LICENSES}
        ),
    }


def contact_sheet(video: Path, out: Path, *, frames: int = 9, ffmpeg: str | None = None) -> Path:
    """A one-row contact sheet of evenly spaced frames, for visual annotation and review."""

    binary = ffmpeg or shutil.which("ffmpeg")
    if not binary:
        raise CorpusError("ffmpeg is not available")
    count = probe_video(video)["frame_count"]
    step = max(count // frames, 1)
    out.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        [binary, "-y", "-loglevel", "error", "-i", str(video), "-vf",
         f"select='not(mod(n,{step}))',scale=120:-1,tile={frames}x1", "-frames:v", "1", str(out)],
        check=True,
    )  # fmt: skip
    return out


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    build = sub.add_parser("build", help="probe and hash annotated clips into an inventory")
    build.add_argument("--annotations", required=True, type=Path)
    build.add_argument("--qual-root", type=Path, default=None)
    build.add_argument("--out", required=True, type=Path)
    args = parser.parse_args(argv)
    annotations = json.loads(args.annotations.read_text(encoding="utf-8"))["entries"]
    inventory = build_inventory(annotations, qual_root=args.qual_root)
    args.out.write_text(json.dumps(inventory, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"wrote {args.out} ({len(inventory['entries'])} entries)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
