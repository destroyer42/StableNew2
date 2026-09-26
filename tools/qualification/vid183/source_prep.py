"""Freeze the PR-VID-183 natural locomotion source and its fixed, non-tracking crop."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from tools.qualification.vid181 import driving_prep
from tools.qualification.vid183 import provenance as prov


def _probe(path: Path) -> dict[str, object]:
    import cv2

    capture = cv2.VideoCapture(str(path))
    result = {
        "width": int(capture.get(cv2.CAP_PROP_FRAME_WIDTH)),
        "height": int(capture.get(cv2.CAP_PROP_FRAME_HEIGHT)),
        "fps": float(capture.get(cv2.CAP_PROP_FPS)),
        "frames": int(capture.get(cv2.CAP_PROP_FRAME_COUNT)),
    }
    capture.release()
    return result


def prepare(source: Path, target: Path) -> dict[str, object]:
    """Use the fixed PR-VID-183 source window and produce its immutable provenance."""

    crop = driving_prep.prepare(
        source,
        target,
        start_s=prov.SOURCE_START_SECONDS,
        duration_s=prov.SOURCE_DURATION_SECONDS,
        x=450,
        y=30,
        k=13,
    )
    return {
        "source_url": "https://mixkit.co/free-stock-video/girl-listens-to-music-and-dances-happily-4856/",
        "license_basis": "Mixkit Stock Video Free License",
        "natural_real_human": True,
        "selected_window": {
            "start_seconds": prov.SOURCE_START_SECONDS,
            "duration_seconds": prov.SOURCE_DURATION_SECONDS,
        },
        "raw_source": {"path": str(source), "sha256": prov.sha256_of(source), **_probe(source)},
        "processed_source": {
            "path": str(target),
            "sha256": prov.sha256_of(target),
            **_probe(target),
        },
        "fixed_crop": crop,
        "no_tracking_crop": True,
        "command_owner": "ffmpeg via tools.qualification.vid181.driving_prep.prepare",
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--evidence", required=True)
    args = parser.parse_args(argv)
    evidence = prepare(Path(args.source), Path(args.out))
    Path(args.evidence).write_text(json.dumps(evidence, indent=2), encoding="utf-8")
    print(json.dumps(evidence, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
