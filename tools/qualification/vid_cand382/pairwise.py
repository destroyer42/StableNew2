"""Blind pairwise preference for VID-CAND-382 stage 2 (a separate ``pairwise.csv``; ``ratings.csv`` is untouched).

A14B saturated the 1-5 ratings at 5/5 in VID-CLIP-371, so stage 2 also asks the owner which of two unlabeled clips is
better on three dimensions.  ``build_pairing`` shuffles the arm order per case from a recorded seed, copies each clip to a
neutral file name in a new folder (the run's own files are only read) and writes the owner's sheet plus a key that maps
A/B back to arms.  ``score_pairing`` reads the filled sheet and the key.  An agent never fills the sheet.
"""

from __future__ import annotations

import csv
import hashlib
import json
import shutil
from collections.abc import Mapping
from pathlib import Path
from typing import Any

DIMENSIONS = ("fidelity", "stability", "motion")
CHOICES = ("A", "B", "tie")
SHEET_NAME = "pairwise.csv"
KEY_NAME = "pairwise_key.json"
BLIND_FOLDER = "pairwise_blind"


def arm_order_is_swapped(seed: int, case_id: str) -> bool:
    """Deterministic per-case coin: independent of case order, so a rebuilt sheet shuffles identically."""

    return bool(hashlib.sha256(f"{seed}:{case_id}".encode()).digest()[0] & 1)


def build_pairing(
    clips: Mapping[str, Mapping[str, Path]],
    *,
    baseline_arm: str,
    candidate_arm: str,
    seed: int,
    out_dir: Path,
) -> dict[str, Any]:
    """Write the blind folder, the owner's sheet and the key; refuse to overwrite any of them.

    ``clips`` maps ``case_id -> {arm_id: clip path}``; a case missing either arm is listed as skipped, never guessed.
    """

    sheet, key_path, blind = out_dir / SHEET_NAME, out_dir / KEY_NAME, out_dir / BLIND_FOLDER
    for existing in (sheet, key_path, blind):
        if existing.exists():
            raise FileExistsError(f"{existing} exists; pairing evidence is never replaced")
    rows: list[dict[str, str]] = []
    key: dict[str, dict[str, str]] = {}
    skipped: list[str] = []
    blind.mkdir(parents=True)
    for index, case_id in enumerate(sorted(clips), start=1):
        pair = clips[case_id]
        if baseline_arm not in pair or candidate_arm not in pair:
            skipped.append(case_id)
            continue
        first, second = (
            (candidate_arm, baseline_arm)
            if arm_order_is_swapped(seed, case_id)
            else (baseline_arm, candidate_arm)
        )
        names = {}
        for label, arm_id in (("A", first), ("B", second)):
            source = Path(pair[arm_id])
            name = f"p{index:02d}_{label}{source.suffix or '.mp4'}"
            shutil.copy2(source, blind / name)
            names[label] = name
        key[case_id] = {"A": first, "B": second}
        rows.append(
            {
                "pair": f"p{index:02d}",
                "case_id": case_id,
                "clip_a": f"{BLIND_FOLDER}/{names['A']}",
                "clip_b": f"{BLIND_FOLDER}/{names['B']}",
                **{f"{dimension}_better": "" for dimension in DIMENSIONS},
                "notes": "",
            }
        )
    with sheet.open("x", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(
            stream,
            fieldnames=[
                "pair",
                "case_id",
                "clip_a",
                "clip_b",
                *(f"{d}_better" for d in DIMENSIONS),
                "notes",
            ],
        )
        writer.writeheader()
        writer.writerows(rows)
    key_path.write_text(
        json.dumps(
            {
                "seed": seed,
                "baseline_arm": baseline_arm,
                "candidate_arm": candidate_arm,
                "key": key,
            },
            indent=1,
            sort_keys=True,
        ),
        encoding="utf-8",
    )
    return {"pairs": len(rows), "skipped": skipped, "sheet": str(sheet), "key": str(key_path)}


def score_pairing(sheet: Path, key_file: Path) -> dict[str, Any]:
    """Candidate preference per dimension: (wins + 0.5 * ties) / answered pairs, plus the unanswered count."""

    meta = json.loads(key_file.read_text(encoding="utf-8"))
    key, candidate = meta["key"], meta["candidate_arm"]
    tally = {d: {"candidate": 0, "baseline": 0, "tie": 0, "unanswered": 0} for d in DIMENSIONS}
    with sheet.open(newline="", encoding="utf-8") as stream:
        for row in csv.DictReader(stream):
            mapping = key.get(row.get("case_id", ""))
            if mapping is None:
                raise ValueError(f"pairwise row {row.get('pair')!r} has no key entry")
            for dimension in DIMENSIONS:
                choice = (row.get(f"{dimension}_better") or "").strip()
                bucket = tally[dimension]
                if choice.lower() == "tie":
                    bucket["tie"] += 1
                elif choice.upper() in ("A", "B"):
                    bucket["candidate" if mapping[choice.upper()] == candidate else "baseline"] += 1
                elif choice:
                    raise ValueError(
                        f"{row.get('pair')} {dimension}: {choice!r} is not A, B or tie"
                    )
                else:
                    bucket["unanswered"] += 1
    for bucket in tally.values():
        answered = bucket["candidate"] + bucket["baseline"] + bucket["tie"]
        bucket["answered"] = answered
        bucket["candidate_preference"] = (
            round((bucket["candidate"] + 0.5 * bucket["tie"]) / answered, 4) if answered else None
        )
    answered_all = [
        b["candidate_preference"] for b in tally.values() if b["candidate_preference"] is not None
    ]
    return {
        "per_dimension": tally,
        "overall_candidate_preference": (
            round(sum(answered_all) / len(answered_all), 4) if answered_all else None
        ),
        "complete": all(b["unanswered"] == 0 and b["answered"] for b in tally.values()),
    }


__all__ = ["DIMENSIONS", "arm_order_is_swapped", "build_pairing", "score_pairing"]
