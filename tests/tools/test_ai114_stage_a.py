"""PR-AI-QUAL-114 Stage A harness additions, driven by the same fake runtime as the AI-111 session tests."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from tests.tools import test_ai111_session as session  # noqa: E402
from tools.qualification.ai111 import physical  # noqa: E402

_case, _run, windows_only = session._case, session._run, session.windows_only
# The session fixtures (fake archive, fake model, hermetic ownership monitor) are shared, not copied.
world = session.world


def _rows(world, name: str) -> list[dict]:
    path = world["paths"].evidence_root / "physical-A" / name
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


@windows_only
def test_rows_carry_run_identity_timing_and_cold_warm_phase(world) -> None:
    result = _run(
        world, [_case(i) for i in range(3)], run_id="ai114-test", executable="llama-cli.exe"
    )
    manifest = json.loads(
        (world["paths"].evidence_root / "physical-A" / "execution-manifest.json").read_text(
            encoding="utf-8"
        )
    )
    assert manifest["run_id"] == "ai114-test" and manifest["executable"] == "llama-cli.exe"
    assert manifest["source_dirty"] in (True, False, None) and manifest["etw_sha256"]
    model_rows = [r for r in _rows(world, "records.jsonl") if r["arm"] == world["entry"].model_id]
    assert [r["phase"] for r in model_rows] == ["cold", "warm", "warm"]
    assert all(r["started_utc"] < r["ended_utc"] and r["input_chars"] > 0 for r in model_rows)
    integrity = _rows(world, "arm-integrity.jsonl")
    assert [(r["phase"], r["problems"]) for r in integrity] == [("before", []), ("after", [])]
    assert result["verdict"] != "PASS"  # a hermetic monitor can never certify a pass


@windows_only
def test_a_failed_arm_precondition_stops_before_any_request(world) -> None:
    result = _run(
        world, [_case(0)], gpu_probe=lambda: ["gpu: utilization 90% (another workload is running)"]
    )
    assert "arm precondition failed" in result["abort_reason"]
    assert not [r for r in _rows(world, "records.jsonl") if r["arm"] == world["entry"].model_id]
    assert _rows(world, "arm-integrity.jsonl")[0]["problems"]


@windows_only
def test_an_unknown_requested_executable_refuses_to_run(world) -> None:
    with pytest.raises(Exception, match="requested_executable_not_in_archive"):
        _run(world, [_case(0)], executable="llama-completion.exe")


@windows_only
def test_lifecycle_probes_prove_real_timeout_and_cancellation_with_teardown(world) -> None:
    slow = _case(9, behavior="", mode="sleep")
    result = _run(world, [_case(0)], lifecycle_probes=True, probe_case=slow)
    probes = _rows(world, "lifecycle-probes.jsonl")
    assert [p["probe"] for p in probes] == ["timeout", "cancel"]
    assert all(
        p["stopped_as_intended"] and p["teardown_verified"] and not p["ownership_violations"]
        for p in probes
    ), probes
    assert probes[0]["outcome"] == "timeout" and probes[1]["outcome"] == "cancelled"
    assert not result["abort_reason"]


@pytest.mark.parametrize(
    "name",
    ["", "documents", "home"],
)
def test_extra_read_roots_never_widen_to_user_profile_or_drive_root(
    tmp_path: Path, name: str
) -> None:
    home = Path.home()
    target = {"": Path(tmp_path.anchor), "documents": home / "Documents", "home": home}[name]
    if not target.is_dir():
        pytest.skip("directory missing on this host")
    assert physical.extra_root_refusal(target)


def test_a_specific_runtime_directory_is_an_acceptable_extra_read_root(tmp_path: Path) -> None:
    (tmp_path / "vc").mkdir()
    assert physical.extra_root_refusal(tmp_path / "vc") == ""
    assert physical.extra_root_refusal(tmp_path / "missing")
