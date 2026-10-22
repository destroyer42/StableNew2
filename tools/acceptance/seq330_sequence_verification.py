"""PR-VID-SEQ-330-CORE evidence verifier: re-read what a finished sequence job left and check it against itself.

This is the CPU-only half of a physical sequence acceptance run (``docs/Subsystems/Video/PR-VID-SEQ-330_Acceptance.md``).
It starts no runtime, makes no request and generates nothing: it takes a job's ``sequence_state.json`` and checks that

* the ledger is a valid, contiguous, completed prefix covering every segment of its plan;
* every recorded clip, frame, manifest and final frame exists and still has its recorded SHA-256 and size;
* every final frame is a decodable PNG, and every carried anchor is exactly the previous segment's final frame;
* a frames-out or native-SVD segment generated exactly the frame count it was admitted with;
* the assembled movie exists, has its recorded hash and manifest, and decodes to the recorded frame count and rate;
* exactly one runtime-release record exists (what it did is reported; whether anything was stopped is not judged here).

A failed check fails the run; the checks land in the printed (and optional ``--report``) JSON.

    python -m tools.acceptance.seq330_sequence_verification <sequence_state.json> [--report FILE] [--no-probe]
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any

from src.video.sequence_ledger import (
    STATE_COMPLETED,
    SequenceLedger,
    SequenceLedgerError,
    read_ledger,
    sha256_of,
    verify_segment_files,
)

# (decoded frame count, frame rate) of an encoded movie
VideoProbe = Callable[[Path], tuple[int, float]]


def _default_probe(path: Path) -> tuple[int, float]:
    from tools.acceptance.vid324_frames_out_acceptance import probe_encoded_video

    return probe_encoded_video(path)


def verify_sequence_evidence(
    ledger_path: str | Path,
    *,
    probe: VideoProbe | None = _default_probe,
) -> dict[str, Any]:
    """Check the completed sequence behind ``ledger_path``; ``passed`` only when every check holds.

    ``probe=None`` skips decoding the assembled movie (the hash and manifest are still checked)."""

    checks: list[dict[str, Any]] = []
    facts: dict[str, Any] = {"ledger_path": str(ledger_path)}

    def check(name: str, ok: bool, detail: Any = None) -> bool:
        checks.append({"check": name, "ok": bool(ok), "detail": detail})
        return bool(ok)

    def verdict() -> dict[str, Any]:
        return {
            "passed": bool(checks) and all(item["ok"] for item in checks),
            "checks": checks,
            "facts": facts,
        }

    path = Path(ledger_path)
    try:
        ledger = read_ledger(path)
    except SequenceLedgerError as exc:
        check("ledger is a valid StableNew sequence ledger", False, str(exc))
        return verdict()
    check("ledger is a valid StableNew sequence ledger", True)
    facts.update(
        job_id=ledger.job_id,
        sequence_id=ledger.sequence_id,
        plan_sha256=ledger.plan_sha256,
        ledger_sha256=sha256_of(path),
        state=ledger.state,
    )
    check("sequence completed", ledger.state == STATE_COMPLETED, ledger.state)
    check(
        "every planned segment is recorded",
        ledger.completed_prefix == ledger.total_segments and ledger.next_segment is None,
        {"completed": ledger.completed_prefix, "planned": ledger.total_segments},
    )
    problems = verify_segment_files(ledger.segments)
    check("every recorded file still has its recorded hash and size", not problems, problems[:10])
    _check_frames(ledger, check)
    _check_assembly(ledger, check, probe, facts)
    check(
        "one runtime-release record",
        ledger.runtime_release is not None,
        None if ledger.runtime_release is None else dict(ledger.runtime_release),
    )
    reused = [s.index for s in ledger.segments if s.origin == "reused"]
    facts["reused_segments"] = reused
    if ledger.parent is not None:
        check(
            "resumed segments are exactly the parent's prefix",
            reused == list(ledger.parent.get("reused_segments") or []),
            {"reused": reused, "parent": dict(ledger.parent)},
        )
    return verdict()


def _check_frames(ledger: SequenceLedger, check: Callable[..., bool]) -> None:
    from src.video.sequence_frames import SequenceFrameError, require_png

    for segment in ledger.segments:
        label = f"segment {segment.index}"
        try:
            require_png(Path(segment.final_frame.file.path), label=f"{label} final frame")
            png_ok, png_detail = True, segment.final_frame.basis
        except SequenceFrameError as exc:
            png_ok, png_detail = False, str(exc)
        check(f"{label} final frame is a PNG", png_ok, png_detail)
        anchor = segment.input_anchor
        if segment.index > 0 and anchor is not None and anchor.from_segment is not None:
            previous = ledger.segments[anchor.from_segment].final_frame
            check(
                f"{label} was conditioned on segment {anchor.from_segment}'s exact final frame",
                anchor.file.sha256 == previous.file.sha256 and anchor.basis == previous.basis,
                {"anchor": anchor.file.sha256, "previous_final": previous.file.sha256},
            )
        if segment.processing.get("backend") == "comfy" and not segment.processing.get("decoded"):
            check(
                f"{label} generated exactly its admitted frame count",
                segment.frame_count == segment.expected_frame_count,
                [segment.frame_count, segment.expected_frame_count],
            )


def _check_assembly(
    ledger: SequenceLedger,
    check: Callable[..., bool],
    probe: VideoProbe | None,
    facts: dict[str, Any],
) -> None:
    assembly: Mapping[str, Any] | None = ledger.assembly
    if assembly is None:
        check("assembled movie recorded", False, "the ledger has no assembly record")
        return
    movie = Path(str(assembly.get("output_path") or ""))
    manifest = Path(str(assembly.get("manifest_path") or ""))
    if not check("assembled movie exists", movie.is_file(), str(movie)):
        return
    check(
        "assembled movie has its recorded hash",
        sha256_of(movie) == assembly.get("output_sha256"),
        assembly.get("output_sha256"),
    )
    check("assembly manifest exists", manifest.is_file(), str(manifest))
    kept = sum(int(item["frames_used"]) for item in assembly.get("segments") or [])
    check(
        "recorded timeline equals the frames used after overlap",
        kept == int(assembly.get("total_frames") or -1),
        {"frames_used": kept, "timeline": assembly.get("total_frames")},
    )
    facts["assembled_frames"] = assembly.get("total_frames")
    if probe is None:
        return
    decoded, fps = probe(movie)
    check(
        "assembled movie decodes to the recorded frame count",
        decoded == assembly.get("total_frames"),
        {"decoded": decoded, "recorded": assembly.get("total_frames")},
    )
    check(
        "assembled movie plays at the recorded rate",
        abs(fps - float(assembly.get("fps") or 0)) < 0.01,
        {"decoded": fps, "recorded": assembly.get("fps")},
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("ledger", type=Path, help="the job's sequence_state.json")
    parser.add_argument("--report", type=Path, help="also write the verdict here")
    parser.add_argument("--no-probe", action="store_true", help="do not decode the assembled movie")
    args = parser.parse_args(argv)
    verdict = verify_sequence_evidence(args.ledger, probe=None if args.no_probe else _default_probe)
    text = json.dumps(verdict, indent=2, default=str)
    if args.report is not None:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(text, encoding="utf-8")
    print(text)
    return 0 if verdict["passed"] else 1


if __name__ == "__main__":
    sys.exit(main())
