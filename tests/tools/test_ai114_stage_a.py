"""PR-AI-QUAL-114 Stage A harness additions, driven by the same fake runtime as the AI-111 session tests."""

from __future__ import annotations

import copy
import hashlib
import json
import os
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


def _pin_fake(monkeypatch) -> None:
    """The fake archive's launcher stands in for the pinned member."""

    sha = hashlib.sha256(session.FILES["llama-cli.exe"]).hexdigest()
    monkeypatch.setitem(physical.LAUNCHABLE_MEMBERS, "llama-cli.exe", sha)


def _rows(world, name: str) -> list[dict]:
    path = world["paths"].evidence_root / "physical-A" / name
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


@windows_only
def test_rows_carry_run_identity_timing_and_cold_warm_phase(world, monkeypatch) -> None:
    _pin_fake(monkeypatch)
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


def test_only_pinned_launchable_members_can_be_requested(world) -> None:
    intent = copy.deepcopy(world["plan"]["runtime_intent"])
    with pytest.raises(Exception, match="requested_executable_not_launchable"):
        physical.derive_runtime_build(world["archive"], intent, "ggml.dll")
    with pytest.raises(Exception, match="requested_executable_hash_mismatch"):
        physical.derive_runtime_build(world["archive"], intent, "llama-cli.exe")


@windows_only
def test_an_extra_loadable_file_in_the_runtime_directory_stops_the_arm(world, monkeypatch) -> None:
    real_import = physical.import_runtime

    def import_and_plant(archive, build, root):
        target = real_import(archive, build, root)
        (target / "ggml-cpu-evil.dll").write_bytes(b"x")
        return target

    monkeypatch.setattr(physical, "import_runtime", import_and_plant)
    result = _run(world, [_case(0)])
    assert "unpinned loadable file in runtime" in result["abort_reason"]
    assert not [r for r in _rows(world, "records.jsonl") if r["arm"] == world["entry"].model_id]


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


def test_a_specific_runtime_directory_is_an_acceptable_extra_read_root(
    tmp_path: Path, monkeypatch
) -> None:
    (tmp_path / "vc").mkdir()
    monkeypatch.setattr(physical, "_refused_prefixes", lambda: [])
    assert physical.extra_root_refusal(tmp_path / "vc") == ""
    assert physical.extra_root_refusal(tmp_path / "missing")


@pytest.mark.parametrize("where", ["appdata", "repo"])
def test_extra_read_roots_under_the_profile_or_repository_are_refused(where: str) -> None:
    target = {
        "appdata": Path(os.environ.get("LOCALAPPDATA", str(Path.home()))),
        "repo": physical.plan_module.REPO_ROOT / "tools",
    }[where]
    assert target.is_dir() and physical.extra_root_refusal(target)
