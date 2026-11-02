"""Read-only inventory of downloaded motion assets (PR-VID-MOTION-354).

    python tools/motion_asset_inventory.py [--root FOLDER] [--out report.json] [--no-video-probe]

Hashes and classifies every file under the folder (the Motion Library folder when omitted), lists archive members without
extracting them, and prints a concise summary.  Nothing under the folder is written, moved, extracted or imported; the JSON
report is refused if it would be written inside the scanned folder.  Blender is only detected, never started for a scan.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from src.video.driving_video_inspection import inspect_driving_video  # noqa: E402
from src.video.motion_conversion.blender import candidate_executables  # noqa: E402
from src.video.motion_conversion.inventory import format_report, scan_inventory  # noqa: E402
from src.video.motion_library.config import load_library_root  # noqa: E402


def _probe(path: Path) -> dict[str, object] | None:
    inspection = inspect_driving_video(path, frame_count=0)
    facts = inspection.facts
    if facts is None:
        return None
    return {
        "width": facts.display_width,
        "height": facts.display_height,
        "fps": facts.reported_fps,
        "frames": facts.frame_count,
        "duration_seconds": facts.duration_seconds,
        "codec": facts.codec_name,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--root", default="", help="Folder to scan (default: the Motion Library folder)."
    )
    parser.add_argument(
        "--out", default="", help="Write the full JSON report here (outside the scanned folder)."
    )
    parser.add_argument("--no-video-probe", action="store_true", help="Skip FFprobe on videos.")
    args = parser.parse_args(argv)

    root = Path(args.root or load_library_root() or "")
    if not str(root) or not root.is_dir():
        print(
            "No asset folder: pass --root or configure the Motion Library folder.", file=sys.stderr
        )
        return 2
    root = root.resolve()
    out = Path(args.out).resolve() if args.out else None
    if out is not None and (out == root or root in out.parents):
        print("Refusing to write the report inside the scanned folder.", file=sys.stderr)
        return 2

    blender = any(path.is_file() for path in candidate_executables())
    report = scan_inventory(
        root, probe_video=None if args.no_video_probe else _probe, blender_available=blender
    )
    print(format_report(report))
    if out is not None:
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(report.to_record(), indent=2), encoding="utf-8")
        print(f"Report written to {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
