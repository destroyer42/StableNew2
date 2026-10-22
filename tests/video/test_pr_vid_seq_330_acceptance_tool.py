"""PR-VID-SEQ-330-CORE: the evidence verifier a later physical sequence run is judged by (CPU-only, fake probe)."""

from __future__ import annotations

import json
from pathlib import Path

from src.video.sequence_ledger import LEDGER_FILE_NAME
from tests.video.test_pr_vid_seq_330_executor import (
    Segments,
    _executor,
    _plan,
    _source,
)
from tools.acceptance.seq330_sequence_verification import main, verify_sequence_evidence


def _finished(tmp_path: Path, count: int = 3) -> Path:
    from tests.video.test_pr_vid_seq_330_executor import Release

    _executor(tmp_path, _plan(count), Segments(tmp_path), release_runtime=Release()).execute(
        source_image_path=_source(tmp_path)
    )
    return tmp_path / LEDGER_FILE_NAME


def _probe_of(ledger_path: Path):
    data = json.loads(ledger_path.read_text(encoding="utf-8"))
    return lambda _path: (data["assembly"]["total_frames"], float(data["assembly"]["fps"]))


def test_a_clean_finished_sequence_passes_every_check(tmp_path: Path) -> None:
    ledger = _finished(tmp_path)

    verdict = verify_sequence_evidence(ledger, probe=_probe_of(ledger))

    assert verdict["passed"] is True, [c for c in verdict["checks"] if not c["ok"]]
    names = [c["check"] for c in verdict["checks"]]
    assert "segment 1 was conditioned on segment 0's exact final frame" in names
    assert verdict["facts"]["assembled_frames"] == 5 + 5 + 5


def test_a_tampered_artifact_a_wrong_decode_or_a_partial_run_fails(tmp_path: Path) -> None:
    ledger = _finished(tmp_path)
    data = json.loads(ledger.read_text(encoding="utf-8"))

    wrong_decode = verify_sequence_evidence(
        ledger, probe=lambda _p: (data["assembly"]["total_frames"] - 1, 24.0)
    )
    assert wrong_decode["passed"] is False
    assert any(
        c["check"] == "assembled movie decodes to the recorded frame count" and not c["ok"]
        for c in wrong_decode["checks"]
    )

    Path(data["segments"][1]["frames"][0]["path"]).write_bytes(b"swapped")
    tampered = verify_sequence_evidence(ledger, probe=_probe_of(ledger))
    assert tampered["passed"] is False
    assert any("hash and size" in c["check"] and not c["ok"] for c in tampered["checks"])


def test_a_failed_checkpoint_is_not_an_acceptance(tmp_path: Path) -> None:
    from tests.video.test_pr_vid_seq_330_executor import _failed_parent

    ledger, _sha = _failed_parent(tmp_path, _plan(4), fail_on=2)

    verdict = verify_sequence_evidence(ledger, probe=None)

    assert verdict["passed"] is False
    assert {c["check"] for c in verdict["checks"] if not c["ok"]} >= {
        "sequence completed",
        "every planned segment is recorded",
    }


def test_the_command_line_reports_and_sets_the_exit_code(tmp_path: Path, capsys) -> None:
    ledger = _finished(tmp_path, count=2)
    report = tmp_path / "out" / "verdict.json"

    assert main([str(ledger), "--no-probe", "--report", str(report)]) == 0
    assert json.loads(report.read_text(encoding="utf-8"))["passed"] is True
    assert main([str(tmp_path / "missing.json"), "--no-probe"]) == 1
    capsys.readouterr()
