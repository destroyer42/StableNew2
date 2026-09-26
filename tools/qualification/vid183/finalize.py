"""Freeze PR-VID-183 A/B controls and reject an invalid basic-retarget pair before GPU work."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from tools.qualification.vid181 import finalize as accepted_finalize
from tools.qualification.vid183 import provenance as prov


def finalize(case_dir: Path, source_meta: dict[str, object]) -> dict[str, object]:
    """Use the accepted finalizer and bind its result to the new controlled A/B contract."""

    record = accepted_finalize.finalize(case_dir, source_meta)
    evidence = json.loads((case_dir / "preprocess_evidence.json").read_text(encoding="utf-8"))
    record["case"] = evidence["case"]
    record["use_flux"] = False
    record["reference_sha256_expected"] = prov.REFERENCE_SHA256
    if record["final_pose"]["sha256"] != prov.sha256_of(Path(record["final_pose"]["path"])):
        raise RuntimeError(
            "BASIC_RETARGET_CONTROL_INVALID: final-pose hash changed during finalization"
        )
    (case_dir / "controls_evidence.json").write_text(json.dumps(record, indent=2), encoding="utf-8")
    return record


def validate_pair(a_dir: Path, b_dir: Path) -> dict[str, float]:
    """Persist the A/B difference and temporal-motion guards before any Animate submission."""

    a, b = a_dir / "final_pose_480x832_13f.mp4", b_dir / "final_pose_480x832_13f.mp4"
    result = prov.validate_control_pair(a, b)
    result["a_sha256"] = prov.sha256_of(a)
    result["b_sha256"] = prov.sha256_of(b)
    destination = b_dir / "pair_validation.json"
    destination.write_text(json.dumps(result, indent=2), encoding="utf-8")
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--case-dir")
    parser.add_argument("--source-meta")
    parser.add_argument("--validate-pair", action="store_true")
    parser.add_argument("--a-dir")
    parser.add_argument("--b-dir")
    args = parser.parse_args(argv)
    if args.validate_pair:
        if not args.a_dir or not args.b_dir:
            parser.error("--validate-pair requires --a-dir and --b-dir")
        print(json.dumps(validate_pair(Path(args.a_dir), Path(args.b_dir)), indent=2))
        return 0
    if not args.case_dir or not args.source_meta:
        parser.error("--case-dir and --source-meta are required unless --validate-pair is used")
    meta = json.loads(Path(args.source_meta).read_text(encoding="utf-8"))
    print(json.dumps(finalize(Path(args.case_dir), meta), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
