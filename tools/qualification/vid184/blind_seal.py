"""PR-VID-184 best-effort arm blinding for the human verdict gate (owner amendment section 6).

Rob must review all outputs and score the pre-registered rubric before seeing any metric score
or knowing which clip came from which workflow/seed arm. This module relabels a set of output
files with random sealed IDs and commits only the SHA-256 of the mapping before hand-off -- the
mapping itself stays local and unrevealed until Rob's review is recorded, so a mapping committed
before review is provably the same mapping revealed after review (no post-hoc relabeling).

Pure stdlib. No network, no media parsing beyond a file copy.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import secrets
import shutil
import sys
from pathlib import Path
from typing import Any


def _canonical(mapping: dict[str, Any]) -> str:
    return json.dumps(mapping, sort_keys=True, separators=(",", ":"))


def seal(
    entries: list[tuple[str, Path]], *, blind_dir: Path, mapping_path: Path
) -> tuple[dict[str, str], str]:
    """Copy each (run_label, source_path) to a randomly-ID'd file under ``blind_dir``.

    Returns (mapping, mapping_sha256). ``mapping`` (run_label -> sealed_id) is written to
    ``mapping_path`` for the reviewer to use ONLY after recording a verdict; it must not be
    committed to the PR branch until after review, unlike its hash.
    """

    blind_dir.mkdir(parents=True, exist_ok=True)
    used_ids: set[str] = set()
    mapping: dict[str, str] = {}
    for run_label, source in entries:
        while True:
            sealed_id = secrets.token_hex(8)
            if sealed_id not in used_ids:
                used_ids.add(sealed_id)
                break
        target = blind_dir / f"{sealed_id}{source.suffix}"
        shutil.copy2(source, target)
        mapping[run_label] = sealed_id

    mapping_path.parent.mkdir(parents=True, exist_ok=True)
    mapping_path.write_text(_canonical(mapping), encoding="utf-8")
    mapping_sha256 = hashlib.sha256(_canonical(mapping).encode("utf-8")).hexdigest()
    return mapping, mapping_sha256


def verify_mapping_hash(mapping_path: Path, expected_sha256: str) -> dict[str, str]:
    """Load the (previously unrevealed) mapping and confirm it matches the committed hash
    before revealing it -- proves the mapping was not altered between commit and reveal."""

    mapping: dict[str, str] = json.loads(mapping_path.read_text(encoding="utf-8"))
    actual = hashlib.sha256(_canonical(mapping).encode("utf-8")).hexdigest()
    if actual != expected_sha256:
        raise RuntimeError(
            f"sealed mapping hash mismatch: expected {expected_sha256}, got {actual} -- "
            "the mapping file does not match what was committed before review; do not reveal it."
        )
    return mapping


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command", required=True)

    seal_p = sub.add_parser("seal")
    seal_p.add_argument(
        "--entry", action="append", required=True, help="run_label=path/to/file, repeatable"
    )
    seal_p.add_argument("--blind-dir", type=Path, required=True)
    seal_p.add_argument("--mapping-path", type=Path, required=True)

    verify_p = sub.add_parser("verify")
    verify_p.add_argument("--mapping-path", type=Path, required=True)
    verify_p.add_argument("--expected-sha256", required=True)

    args = parser.parse_args(argv)
    if args.command == "seal":
        entries = []
        for raw in args.entry:
            label, _, path = raw.partition("=")
            entries.append((label, Path(path)))
        _, mapping_sha256 = seal(entries, blind_dir=args.blind_dir, mapping_path=args.mapping_path)
        print(mapping_sha256)
    elif args.command == "verify":
        mapping = verify_mapping_hash(args.mapping_path, args.expected_sha256)
        print(json.dumps(mapping, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
