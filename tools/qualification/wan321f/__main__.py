"""Write a new OFFLINE freeze directory. This command cannot launch or dispatch."""

from __future__ import annotations

import argparse
import hashlib
import os
import shutil
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path

from tools.qualification.wan321f.controls import physical_refusals, write_new_json
from tools.qualification.wan321f.plan import (
    ASSETS,
    INPUT_PATH,
    INPUT_SHA,
    asset_refusals,
    digest,
    frozen_plan,
    source_refusals,
)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--out", type=Path, required=True, help="New directory; existing evidence is never replaced"
    )
    args = parser.parse_args()
    plan = frozen_plan()
    refusal = asset_refusals()
    runtime_refusal = source_refusals()
    disks = {}
    for drive in ("C:/", "E:/"):
        usage = shutil.disk_usage(drive)
        disks[drive] = {"free_bytes": usage.free, "total_bytes": usage.total}
    missing_bytes = sum(a.bytes for a in ASSETS if not Path(a.local_path).is_file())
    # Reserve uncompressed RGB frames for all three attempts plus a 1 GiB evidence/log allowance.
    evidence_reserve = 3 * 81 * 480 * 832 * 3 + 1024**3
    args.out.mkdir(parents=True, exist_ok=False)
    write_new_json(args.out / "plan.json", plan)
    input_bytes = Path(INPUT_PATH).read_bytes() if Path(INPUT_PATH).is_file() else None
    if input_bytes is not None and hashlib.sha256(input_bytes).hexdigest() == INPUT_SHA:
        with (args.out / "wan321f-source.png").open("xb") as handle:
            handle.write(input_bytes)
            handle.flush()
            os.fsync(handle.fileno())
    else:
        refusal.append("input changed during freeze; snapshot not published")
    for attempt in plan["attempts"]:
        write_new_json(args.out / f"graph-{attempt['attempt']}.json", attempt["graph"])
    snapshot = {
        "timestamp_utc": datetime.now(UTC).isoformat(),
        "verdict": "INCONCLUSIVE",
        "plan_sha256": digest(plan),
        "asset_refusals": refusal,
        "source_refusals": runtime_refusal,
        "physical_refusals": physical_refusals(),
        "disks": disks,
        "all_asset_bytes": sum(a.bytes for a in ASSETS),
        "missing_asset_bytes": missing_bytes,
        "evidence_reserve_bytes": evidence_reserve,
        "capacity_sufficient": {
            "E:/": disks["E:/"]["free_bytes"] >= missing_bytes,
            "C:/": disks["C:/"]["free_bytes"] >= evidence_reserve,
        },
        "assets": [asdict(a) for a in ASSETS],
        "physical_attempts": 0,
    }
    write_new_json(args.out / "offline-evidence.json", snapshot)
    print(f"INCONCLUSIVE (offline only): {args.out.resolve()}; plan {digest(plan)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
