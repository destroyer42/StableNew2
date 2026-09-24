"""Turn one case's full upstream ``src_pose.mp4`` into the frozen 480x832 / 13f / 8fps pose control
and write its provenance record. Runs in the StableNew ``.venv`` (OpenCV/numpy only, CPU):

    python -m tools.qualification.vid181.finalize --case-dir <out/case> --source-meta <json>

``--source-meta`` is a JSON file describing the raw driving clip (source page, license basis,
download date, original hash/dimensions/fps/frames, trim). Nothing here touches a GPU.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from tools.qualification.vid110.metrics import contact_sheet
from tools.qualification.vid181 import provenance as prov


def _probe(path: Path) -> dict[str, object]:
    import cv2

    capture = cv2.VideoCapture(str(path))
    info = {
        "width": int(capture.get(cv2.CAP_PROP_FRAME_WIDTH)),
        "height": int(capture.get(cv2.CAP_PROP_FRAME_HEIGHT)),
        "fps": round(float(capture.get(cv2.CAP_PROP_FPS)), 4),
        "frames": int(capture.get(cv2.CAP_PROP_FRAME_COUNT)),
    }
    capture.release()
    return info


def finalize(case_dir: Path, source_meta: dict[str, object]) -> dict[str, object]:
    evidence = json.loads((case_dir / "preprocess_evidence.json").read_text(encoding="utf-8"))
    full_pose = Path(evidence["src_pose"]["path"])
    if prov.sha256_of(full_pose) != evidence["src_pose"]["sha256"]:
        raise RuntimeError("full src_pose.mp4 hash changed since preprocessing")
    final, indices, operation = prov.adapt_pose_to_frozen(
        full_pose, case_dir / "final_pose_480x832_13f.mp4"
    )
    contact_sheet(full_pose, case_dir / "full_pose_sheet.png", columns=6, count=12)
    contact_sheet(final, case_dir / "final_pose_sheet.png", columns=7, count=13)
    record = {
        "upstream_sha": evidence["upstream_sha"],
        "retarget_flag": evidence["retarget_flag"],
        "source": source_meta,
        "raw_video_processed": evidence["raw_video"],
        "full_pose": {**evidence["src_pose"], **_probe(full_pose)},
        "src_face_generated_not_consumed": {
            **evidence["src_face"],
            "consumed_by_graph": False,
        },
        "final_pose": {
            "path": str(final),
            "sha256": prov.sha256_of(final),
            **_probe(final),
        },
        "selected_source_frame_indices": indices,
        "adaptation": operation,
        "detector_providers": evidence["detector_providers"],
        "pose_providers": evidence["pose_providers"],
    }
    (case_dir / "controls_evidence.json").write_text(json.dumps(record, indent=2), encoding="utf-8")
    return record


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--case-dir", required=True)
    parser.add_argument("--source-meta", required=True)
    args = parser.parse_args(argv)
    meta = json.loads(Path(args.source_meta).read_text(encoding="utf-8"))
    print(json.dumps(finalize(Path(args.case_dir), meta), indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
