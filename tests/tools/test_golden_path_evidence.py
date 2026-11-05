"""Permanent evidence, comparison, friction, registries and gate hardening (PR-TEST-DESKTOP-830 amendment).

Deterministic and display-free: temporary directories, injected probes, no model runtime and no GPU.
"""

from __future__ import annotations

import json
import os
import subprocess
import urllib.request
from copy import deepcopy
from pathlib import Path
from typing import Any

import pytest

from tests.tools.test_golden_path_contracts import (
    authorize,
    boom,
    ctx_for,
    frozen,
    run_gate,
)
from tools.operator_journey.evidence import FAIL, HOLD, NO_GO, JourneyEvidence
from tools.operator_journey.golden import baseline, compare, friction, provenance, registry
from tools.operator_journey.golden.physical import confirmation_phrase, default_confirm
from tools.operator_journey.golden.suite import redact, write_run_evidence

HOME = str(Path.home())


# --- helpers -----------------------------------------------------------------------------------------------------


def make_png(path: Path, *, text: str | None = None) -> Path:
    from PIL import Image, PngImagePlugin

    path.parent.mkdir(parents=True, exist_ok=True)
    image = Image.new("RGB", (8, 6), (10, 120, 200))
    info = None
    if text:
        info = PngImagePlugin.PngInfo()
        info.add_text("note", text)
    image.save(path, pnginfo=info)
    return path


def journey(
    jid: str,
    *,
    trace: list[dict[str, Any]] | None = None,
    verdict: str = "PASS",
    seconds: int = 60,
    errors: int = 0,
    media_sha: str | None = "m1",
    checks: int = 4,
) -> JourneyEvidence:
    ev = JourneyEvidence(journey_id=jid, backend_mode="simulated")
    ev.started_at = "2026-11-03T10:00:00+00:00"
    ev.completed_at = f"2026-11-03T10:{seconds // 60:02d}:{seconds % 60:02d}+00:00"
    ev.desktop_driver = "windows"
    for index in range(checks):
        ev.check("p", f"c{index}", True if verdict == "PASS" else index != 0, "d")
    if verdict == "HOLD":
        ev.hold_reason = "prerequisite missing"
    if verdict == "FAIL":
        ev.abort_reason = "failed"
    ev.action_trace = list(trace or [{"t": 1.0, "action": "click", "driver": "windows"}])
    ev.log_errors = [{"msg": "e"}] * errors
    if media_sha:
        ev.observe("image_media", {"path": "x.png", "valid": True, "sha256": media_sha})
    return ev


def run_folder(
    tmp_path: Path,
    name: str,
    results: list[JourneyEvidence],
    *,
    mode: str = "simulated",
    driver: str = "windows",
    display_w: int = 2560,
) -> Path:
    run_dir = tmp_path / name
    run_dir.mkdir(parents=True)
    plan = {"suite": "golden-paths"}
    import tools.operator_journey.desktop as desktop

    original = desktop.display_facts
    desktop.display_facts = lambda: {
        "width": display_w,
        "height": 1440,
        "dpi": 96,
        "scaling_percent": 100,
    }
    try:
        write_run_evidence(run_dir, plan=plan, results=results, mode=mode, driver=driver)
    finally:
        desktop.display_facts = original
    make_png(run_dir / "screenshots" / "IMG-01_1_prompt.png", text=f"secret path {HOME}")
    return run_dir


@pytest.fixture
def model_file(tmp_path: Path) -> Path:
    path = tmp_path / "model.safetensors"
    path.write_bytes(b"model")
    return path


@pytest.fixture
def source_file(tmp_path: Path) -> Path:
    path = tmp_path / "ref.png"
    path.write_bytes(b"png")
    return path


@pytest.fixture
def acceptance_root(tmp_path: Path) -> Path:
    return tmp_path / "StableNewAcceptance"


# --- 1. registries -------------------------------------------------------------------------------------------------


def test_shipped_registries_are_valid_and_hold_all_known_findings() -> None:
    findings = registry.load_findings()
    assert registry.finding_problems(findings) == []
    ids = {f["id"] for f in findings["findings"]}
    assert {"GP830-F1", "GP830-F2", "GP830-F3", "GP830-F4", "GP830-F5", "GP830-I1"} <= ids
    # A repair is claimed only with the PR that made it, the tests that pin it and the verification that proved it.
    for finding in findings["findings"]:
        repair = finding["repair"]
        if repair["status"] == "REPAIRED":
            assert repair["repaired_in"], finding["id"]
            assert repair["regression_tests"], finding["id"]
            assert repair["verification"], finding["id"]
        if repair["status"] == "WONTFIX":
            assert repair["classification"] and repair["summary"], finding["id"]
    coverage = registry.load_coverage()
    assert registry.coverage_problems(coverage) == []
    summary = registry.coverage_summary(coverage)
    # The three 830 journeys stay full desktop journeys; the advanced journeys add to, never remove from, that set.
    assert summary["full_desktop_journey"] >= 3 and summary["untested"] >= 1
    full = {row["id"] for row in coverage["workflows"] if row["coverage"] == "full_desktop_journey"}
    assert {
        "image-txt2img-from-promptpack",
        "video-wan22-ti2v-from-reference-image",
        "learning-designed-experiment-rating-persistence",
    } <= full


def test_registry_validators_fail_closed() -> None:
    bad = {
        "schema": "stablenew.golden_findings",
        "version": "1",
        "findings": [
            {"id": "X", "severity": "cosmic", "repair": {"status": "MAYBE"}, "evidence": [{}]}
        ],
    }
    problems = " ".join(registry.finding_problems(bad))
    assert (
        "unknown severity" in problems
        and "unknown repair status" in problems
        and "missing title" in problems
    )
    matrix = {
        "schema": "stablenew.golden_coverage_matrix",
        "version": "1",
        "workflows": [
            {
                "id": "a",
                "coverage": "full_desktop_journey",
                "journeys": ["NOPE-9"],
                "tests": [],
                "limits": "x",
            },
            {
                "id": "b",
                "coverage": "integration_only",
                "journeys": [],
                "tests": ["tests/does_not_exist.py"],
                "limits": "x",
            },
            {"id": "c", "coverage": "untested", "journeys": ["IMG-01"], "tests": [], "limits": "x"},
            {"id": "d", "coverage": "wishful", "limits": "x"},
        ],
    }
    problems = " ".join(registry.coverage_problems(matrix))
    for expected in (
        "unknown journey",
        "does not exist",
        "untested must not list",
        "unknown coverage class",
    ):
        assert expected in problems


# --- 2. friction, reachability and outcomes -------------------------------------------------------------------------


def test_workarounds_are_counted_as_friction_and_linked_to_findings() -> None:
    trace = [
        {"action": "maximize_window"},
        {"action": "drag_sash", "label": "Learning panes"},
        {"action": "pointer_followed_control", "label": "Pack Refresh"},
        {"action": "reclick_after_no_effect", "label": "Model"},
        {"action": "waited_for_state", "label": "Run", "state": "hidden", "seconds": 2.0},
        {"action": "scrolled_into_view", "label": "Steps", "wheel_notches": 3},
        {"action": "click"},
    ]
    report = friction.friction_report(trace)
    assert report["workaround_count"] == 5
    assert report["workarounds"]["window_forced_maximized"]["finding"] == "GP830-F1"
    assert report["workarounds"]["mouse_release_followed_moving_control"]["finding"] == "GP830-F2"
    assert report["informational"] == {"page_scrolled_with_the_wheel": 1}


def test_reachability_is_only_claimed_where_real_pointer_input_was_used() -> None:
    clean = friction.friction_report([{"action": "click"}])
    dirty = friction.friction_report([{"action": "maximize_window"}])
    assert friction.reachability("tk", "PASS", None, dirty) == "NOT_ASSESSED"
    assert friction.reachability("windows", "PASS", None, clean) == "DIRECT"
    assert friction.reachability("windows", "PASS", None, dirty) == "WITH_WORKAROUNDS"
    assert (
        friction.reachability("windows", "FAIL", "ControlUnreachable: Rating", dirty) == "BLOCKED"
    )
    out = friction.outcomes("windows", "PASS", None, dirty)
    assert out["functional"] == "PASS" and out["reachability"] == "WITH_WORKAROUNDS"
    assert out["resource_safety"] == "NOT_ASSESSED" and out["visual_quality"] == "NOT_ASSESSED"
    assert friction.outcomes("windows", "PASS", None, dirty, physical=True)["visual_quality"] == (
        "PENDING_OPERATOR_REVIEW"
    )


def test_run_evidence_records_provenance_outcomes_and_timings(tmp_path: Path) -> None:
    run = run_folder(
        tmp_path,
        "r",
        [journey("IMG-01", trace=[{"t": 2.5, "action": "maximize_window", "driver": "windows"}])],
    )
    evidence = json.loads((run / "evidence.json").read_text(encoding="utf-8"))
    assert evidence["evidence_schema"] == "2" and evidence["suite_version"] == "1.1.0"
    prov = evidence["provenance"]
    assert prov["repository_sha"] and prov["python"] and prov["harness_sources"]["combined_sha256"]
    assert "tree_state" in prov and "dirty_tracked_files" in prov
    result = evidence["journeys"]["IMG-01"]
    assert result["outcomes"]["reachability"] == "WITH_WORKAROUNDS"
    assert result["friction"]["workaround_count"] == 1
    assert result["timings"]["duration_s"] == 60 and result["timings"]["trace_span_s"] == 2.5
    assert HOME not in (run / "evidence.json").read_text(encoding="utf-8")


# --- 3. provenance and media retention ---------------------------------------------------------------------------------


def test_media_is_copied_and_its_hash_verified_before_the_workspace_goes(tmp_path: Path) -> None:
    import hashlib

    media = tmp_path / "ws" / "out.png"
    make_png(media)
    sha = hashlib.sha256(media.read_bytes()).hexdigest()
    obs = [
        {
            "name": "image_media",
            "source": "observed",
            "value": {"path": str(media), "valid": True, "sha256": sha},
        }
    ]
    records = provenance.retain_media(obs, tmp_path / "run")
    assert records[0]["retained"] and (tmp_path / "run" / records[0]["file"]).is_file()
    assert records[0]["sha256"] == sha


def test_missing_corrupt_or_changed_media_is_reported_never_reconstructed(tmp_path: Path) -> None:
    gone = {
        "name": "image_media",
        "source": "observed",
        "value": {"path": str(tmp_path / "gone.png"), "valid": True, "sha256": "a"},
    }
    invalid = {
        "name": "video_media",
        "source": "observed",
        "value": {"path": "x", "valid": False, "sha256": "b"},
    }
    changed_file = make_png(tmp_path / "c.png")
    changed = {
        "name": "image_media",
        "source": "observed",
        "value": {"path": str(changed_file), "valid": True, "sha256": "not-the-hash"},
    }
    records = provenance.retain_media([gone, invalid, changed], tmp_path / "run")
    assert [r["retained"] for r in records] == [False, False, False]
    assert "no longer exists" in records[0]["reason"] and "did not validate" in records[1]["reason"]
    assert "differs" in records[2]["reason"]
    assert not list(
        (tmp_path / "run" / "artifacts" / "media").glob("*")
    )  # the bad copy was removed


def test_settings_report_flags_mismatches_and_unobserved_values() -> None:
    report = provenance.settings_report(
        {"steps": 6, "seed": 1, "model": "m"}, {"steps": "6", "seed": 2}
    )
    assert report["keys"]["steps"]["match"] is True and report["keys"]["seed"]["match"] is False
    assert report["keys"]["model"]["match"] is None and report["unobserved"] == ["model"]
    assert report["all_matched"] is False


# --- 4. baseline archive -----------------------------------------------------------------------------------------------


def test_the_acceptance_root_defaults_outside_the_repository_and_refuses_the_repo(
    tmp_path: Path,
) -> None:
    assert baseline.default_root() == Path.home() / "StableNewAcceptance"
    assert baseline.resolve_root(None, {}) == baseline.default_root()
    assert baseline.resolve_root(None, {baseline.ENV_ROOT: str(tmp_path / "x")}) == tmp_path / "x"
    assert (
        baseline.resolve_root(tmp_path / "cli", {baseline.ENV_ROOT: str(tmp_path / "x")})
        == tmp_path / "cli"
    )
    with pytest.raises(baseline.ArchiveRefused, match="inside the repository"):
        baseline.resolve_root(baseline.REPO_ROOT / "reports" / "x", {})


def test_archive_is_sealed_hashed_read_only_and_redacted(
    tmp_path: Path, acceptance_root: Path
) -> None:
    run = run_folder(tmp_path, "r", [journey("IMG-01")])
    sealed = baseline.archive_with_registries(run, acceptance_root, label="unit")
    report = baseline.verify_archive(sealed)
    assert report["status"] == "OK", report["problems"]
    manifest = report["manifest"]
    assert manifest["evidence_class"] == "acceptance" and manifest["mode"] == "simulated"
    assert sealed.parent.parent == acceptance_root and (sealed / baseline.COMPLETE).is_file()
    paths = {row["path"] for row in manifest["files"]}
    assert {
        "evidence.json",
        "summary.md",
        "registries/findings.v1.json",
        "registries/coverage_matrix.v1.json",
    } <= paths
    assert not os.access(sealed / "evidence.json", os.W_OK)
    assert HOME not in (sealed / "evidence.json").read_text(encoding="utf-8")
    assert not list(acceptance_root.rglob(".partial-*"))


def test_screenshot_metadata_is_stripped_and_the_pixel_caveat_is_recorded(
    tmp_path: Path, acceptance_root: Path
) -> None:
    from PIL import Image

    run = run_folder(tmp_path, "r", [journey("IMG-01")])
    source = run / "screenshots" / "IMG-01_1_prompt.png"
    with Image.open(source) as image:
        assert image.text.get("note")  # the original carries metadata
        pixels = list(image.getdata())
    sealed = baseline.archive_run(run, acceptance_root)
    copy = sealed / "screenshots" / "IMG-01_1_prompt.png"
    with Image.open(copy) as image:
        assert not image.text and list(image.getdata()) == pixels
    manifest = baseline.verify_archive(sealed)["manifest"]
    row = next(r for r in manifest["files"] if r["path"] == "screenshots/IMG-01_1_prompt.png")
    assert row["transform"] == "png_metadata_stripped_pixels_unredacted"
    assert row["source_sha256"] != row["sha256"] and "NOT redacted" in manifest["redaction"]


def test_home_paths_are_redacted_in_every_spelling() -> None:
    forms = [HOME, HOME.replace("\\", "/"), HOME.replace("\\", "\\\\")]
    for form in forms:
        assert HOME.lower() not in baseline.redact_paths(f"x {form}\\y").lower().replace(
            "\\\\", "\\"
        )
        assert form not in redact(f"x {form} y")


def test_every_archive_is_unique_and_an_existing_one_is_never_overwritten(
    tmp_path: Path, acceptance_root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    run = run_folder(tmp_path, "r", [journey("IMG-01")])
    first = baseline.archive_run(run, acceptance_root)
    second = baseline.archive_run(run, acceptance_root)
    assert first != second and baseline.verify_archive(first)["status"] == "OK"
    monkeypatch.setattr(baseline.secrets, "token_hex", lambda _n: "000000")
    monkeypatch.setattr(
        baseline.time, "strftime", lambda fmt, *_a: "20261103T000000Z" if "T" in fmt else "x"
    )
    one = baseline.archive_run(run, acceptance_root)
    before = (one / "evidence.json").read_bytes()
    with pytest.raises(baseline.ArchiveRefused, match="never overwritten"):
        baseline.archive_run(run, acceptance_root)
    assert (one / "evidence.json").read_bytes() == before


def test_tampering_missing_and_extra_files_are_detected(
    tmp_path: Path, acceptance_root: Path
) -> None:
    run = run_folder(tmp_path, "r", [journey("IMG-01")])
    sealed = baseline.archive_run(run, acceptance_root)
    target = sealed / "summary.md"
    target.chmod(0o666)
    target.write_text("edited", encoding="utf-8")
    report = baseline.verify_archive(sealed)
    assert report["status"] == "TAMPERED" and any(
        "hash mismatch: summary.md" in p for p in report["problems"]
    )
    (sealed / "actions.jsonl").chmod(0o666)
    (sealed / "actions.jsonl").unlink()
    (sealed / "stray.txt").write_text("x", encoding="utf-8")
    problems = " ".join(baseline.verify_archive(sealed)["problems"])
    assert "missing: actions.jsonl" in problems and "unexpected file: stray.txt" in problems


def test_an_interrupted_archive_is_never_mistaken_for_a_finished_one(
    tmp_path: Path, acceptance_root: Path
) -> None:
    run = run_folder(tmp_path, "r", [journey("IMG-01")])
    calls = {"n": 0}

    def dying_copier(src: Path, dst: Path) -> tuple[str, bool]:
        calls["n"] += 1
        if calls["n"] == 3:
            raise KeyboardInterrupt("the machine went to sleep")
        return baseline._copy_one(src, dst)

    with pytest.raises(KeyboardInterrupt):
        baseline.archive_run(run, acceptance_root, copier=dying_copier)
    partial = baseline.find_interrupted(acceptance_root)
    assert len(partial) == 1 and partial[0].name.startswith(baseline.PARTIAL_PREFIX)
    assert baseline.verify_archive(partial[0])["status"] == "INCOMPLETE"
    finals = [p for p in (acceptance_root / "golden-paths").iterdir() if not p.name.startswith(".")]
    assert finals == []
    with pytest.raises(compare.Incomparable, match="interrupted"):
        compare.compare(partial[0], run)


def test_acceptance_is_recorded_once_for_a_verified_archive_only(
    tmp_path: Path, acceptance_root: Path
) -> None:
    run = run_folder(tmp_path, "r", [journey("IMG-01")])
    sealed = baseline.archive_run(run, acceptance_root)
    baseline.mark_accepted(sealed, accepted_by="owner", reason="unit")
    assert baseline.verify_archive(sealed)["status"] == "OK"  # ACCEPTED.json is an allowed addition
    with pytest.raises(baseline.ArchiveRefused, match="already accepted"):
        baseline.mark_accepted(sealed, accepted_by="owner", reason="again")
    other = baseline.archive_run(run, acceptance_root)
    (other / "summary.md").chmod(0o666)
    (other / "summary.md").write_text("x", encoding="utf-8")
    with pytest.raises(baseline.ArchiveRefused, match="verified archive"):
        baseline.mark_accepted(other, accepted_by="owner", reason="no")


def test_findings_evidence_is_preserved_with_hashes_and_gaps_are_reported(
    tmp_path: Path, acceptance_root: Path
) -> None:
    source_root = tmp_path / "exploratory"
    shot = source_root / "gp_winl8" / "run" / "screenshots" / "LRN-01_1_failure.png"
    make_png(shot)
    run = run_folder(tmp_path, "r", [journey("IMG-01")])
    sealed = baseline.archive_with_registries(
        run, acceptance_root, findings_source_root=source_root
    )
    index = json.loads(
        (sealed / "registries" / "findings_evidence.json").read_text(encoding="utf-8")
    )
    found = [r for r in index if r["found"]]
    assert [r["finding"] for r in found] == ["GP830-F1"] and found[0]["source_sha256"]
    assert (sealed / found[0]["archive_path"]).is_file()
    assert any(
        not r["found"] for r in index
    )  # evidence that no longer exists is reported, not invented


def test_an_earlier_run_is_preserved_as_exploratory_never_acceptance(
    tmp_path: Path, acceptance_root: Path
) -> None:
    run = run_folder(tmp_path, "r", [journey("IMG-01")])
    sealed = baseline.archive_with_registries(
        run, acceptance_root, evidence_class="exploratory", notes=["pre-commit tree"]
    )
    manifest = baseline.verify_archive(sealed)["manifest"]
    assert manifest["evidence_class"] == "exploratory" and "exploratory" in sealed.name


# --- 5. comparison ---------------------------------------------------------------------------------------------------


def _archive(tmp_path: Path, root: Path, name: str, results, **kw) -> Path:
    return baseline.archive_run(run_folder(tmp_path, name, results, **kw), root)


def test_identical_evidence_is_unchanged_and_regressions_are_degraded(
    tmp_path: Path, acceptance_root: Path
) -> None:
    a = _archive(tmp_path, acceptance_root, "a", [journey("IMG-01")])
    b = _archive(tmp_path, acceptance_root, "b", [journey("IMG-01")])
    result = compare.compare(a, b)
    metrics = result["journeys"]["IMG-01"]["metrics"]
    assert result["regressions"] == 0
    assert (
        metrics["verdict"]["result"] == "unchanged"
        and metrics["workaround_count"]["result"] == "unchanged"
    )
    worse = _archive(
        tmp_path,
        acceptance_root,
        "c",
        [
            journey(
                "IMG-01",
                trace=[{"t": 1, "action": "maximize_window", "driver": "windows"}] * 2,
                errors=2,
            )
        ],
    )
    result = compare.compare(a, worse)
    metrics = result["journeys"]["IMG-01"]["metrics"]
    assert result["regressions"] >= 2
    assert metrics["workaround_count"]["result"] == "degraded"
    assert metrics["error_count"]["result"] == "degraded"
    better = compare.compare(worse, a)["journeys"]["IMG-01"]["metrics"]
    assert better["workaround_count"]["result"] == "improved"
    # a failing run stopped early: its verdict degrades, but its action/workaround counts are truncated, not comparable
    failed = _archive(tmp_path, acceptance_root, "d", [journey("IMG-01", verdict="FAIL")])
    metrics = compare.compare(a, failed)["journeys"]["IMG-01"]["metrics"]
    assert metrics["verdict"]["result"] == "degraded"
    assert metrics["workaround_count"]["result"] == "inconclusive"
    assert metrics["action_count"]["result"] == "inconclusive"
    assert (
        compare.compare(failed, a)["journeys"]["IMG-01"]["metrics"]["verdict"]["result"]
        == "improved"
    )


def test_environment_differences_are_noted_and_make_timings_inconclusive(
    tmp_path: Path, acceptance_root: Path
) -> None:
    a = _archive(tmp_path, acceptance_root, "a", [journey("IMG-01", seconds=60)])
    b = _archive(tmp_path, acceptance_root, "b", [journey("IMG-01", seconds=30)], display_w=1920)
    result = compare.compare(a, b)
    assert any(d["key"] == "display" for d in result["environment"]["differences"])
    timing = result["journeys"]["IMG-01"]["metrics"]["duration_s"]
    assert timing["result"] == "inconclusive" and "display" in timing["note"]
    same_env = compare.compare(
        a, _archive(tmp_path, acceptance_root, "c", [journey("IMG-01", seconds=30)])
    )["journeys"]["IMG-01"]["metrics"]["duration_s"]
    assert same_env["result"] == "improved"


def test_different_media_bytes_are_inconclusive_not_a_quality_verdict(
    tmp_path: Path, acceptance_root: Path
) -> None:
    a = _archive(tmp_path, acceptance_root, "a", [journey("IMG-01", media_sha="m1")])
    b = _archive(tmp_path, acceptance_root, "b", [journey("IMG-01", media_sha="m2")])
    row = compare.compare(a, b)["journeys"]["IMG-01"]["metrics"]["media_sha256"]
    assert row["result"] == "inconclusive" and "operator review" in row["note"]


def test_a_journey_missing_on_one_side_is_inconclusive(
    tmp_path: Path, acceptance_root: Path
) -> None:
    a = _archive(tmp_path, acceptance_root, "a", [journey("IMG-01"), journey("VID-01")])
    b = _archive(tmp_path, acceptance_root, "b", [journey("IMG-01")])
    entry = compare.compare(a, b)["journeys"]["VID-01"]
    assert entry["present"] == {"a": True, "b": False} and entry["metrics"] == {}


def test_tk_evidence_leaves_reachability_inconclusive(
    tmp_path: Path, acceptance_root: Path
) -> None:
    ev_tk = journey("IMG-01")
    ev_tk.desktop_driver = "tk"
    a = _archive(tmp_path, acceptance_root, "a", [ev_tk], driver="tk")
    b = _archive(tmp_path, acceptance_root, "b", [journey("IMG-01")], driver="windows")
    result = compare.compare(a, b)
    assert result["journeys"]["IMG-01"]["metrics"]["reachability"]["result"] == "inconclusive"
    assert any(d["key"] == "desktop_driver" for d in result["environment"]["differences"])


def test_incompatible_missing_unsealed_and_tampered_inputs_are_refused(
    tmp_path: Path, acceptance_root: Path
) -> None:
    a = _archive(tmp_path, acceptance_root, "a", [journey("IMG-01")])
    with pytest.raises(compare.Incomparable, match="not a directory"):
        compare.compare(a, tmp_path / "nowhere")
    empty = tmp_path / "empty"
    empty.mkdir()
    with pytest.raises(compare.Incomparable, match="no evidence.json"):
        compare.compare(a, empty)
    readiness = _archive(tmp_path, acceptance_root, "r", [journey("IMG-01")], mode="readiness")
    with pytest.raises(compare.Incomparable, match="different mode"):
        compare.compare(a, readiness)
    other_version = tmp_path / "v2"
    other_version.mkdir()
    doc = json.loads((a / "evidence.json").read_text(encoding="utf-8"))
    doc["suite_version"] = "2.0.0"
    (other_version / "evidence.json").write_text(json.dumps(doc), encoding="utf-8")
    with pytest.raises(compare.Incomparable, match="incompatible suite versions"):
        compare.compare(a, other_version)
    tampered = baseline.archive_run(run_folder(tmp_path, "t", [journey("IMG-01")]), acceptance_root)
    (tampered / "summary.md").chmod(0o666)
    (tampered / "summary.md").write_text("x", encoding="utf-8")
    with pytest.raises(compare.Incomparable, match="TAMPERED"):
        compare.compare(a, tampered)
    plain = compare.compare(
        run_folder(tmp_path, "p1", [journey("IMG-01")]),
        run_folder(tmp_path, "p2", [journey("IMG-01")]),
    )
    assert plain["a"]["integrity"].startswith("unverified")


def test_comparison_output_is_written_once(tmp_path: Path, acceptance_root: Path) -> None:
    a = _archive(tmp_path, acceptance_root, "a", [journey("IMG-01")])
    b = _archive(tmp_path, acceptance_root, "b", [journey("IMG-01")])
    result = compare.compare(a, b)
    out = compare.write_comparison(result, tmp_path / "cmp")
    assert "Environmental differences" in out.read_text(encoding="utf-8")
    with pytest.raises(baseline.ArchiveRefused, match="never overwritten"):
        compare.write_comparison(result, tmp_path / "cmp")


def test_cli_tools_verify_compare_and_registries(
    tmp_path: Path, acceptance_root: Path, capsys
) -> None:
    from tools.operator_journey import cli

    a = _archive(tmp_path, acceptance_root, "a", [journey("IMG-01")])
    b = _archive(tmp_path, acceptance_root, "b", [journey("IMG-01", verdict="FAIL")])
    assert cli.main(["--suite", "golden-paths", "--check-registries"]) == 0
    assert cli.main(["--suite", "golden-paths", "--verify-archive", str(a)]) == 0
    assert (
        cli.main(["--suite", "golden-paths", "--compare", str(a), str(b)]) == compare.EXIT_DEGRADED
    )
    assert (
        cli.main(["--suite", "golden-paths", "--compare", str(a), str(tmp_path / "nope")])
        == compare.EXIT_INCOMPARABLE
    )
    assert (
        cli.main(["--suite", "golden-paths", "--layout", "minimum"]) == 4
    )  # needs the windows driver
    capsys.readouterr()


# --- 6. physical gate and readiness hardening --------------------------------------------------------------------------


def test_a_non_interactive_session_can_never_launch(monkeypatch: pytest.MonkeyPatch) -> None:
    class NoTty:
        def isatty(self) -> bool:
            return False

    monkeypatch.setattr("sys.stdin", NoTty())
    assert default_confirm("go? ") == ""


def test_an_executor_crash_is_a_no_go_with_evidence_and_no_retry(
    tmp_path: Path, model_file, source_file
) -> None:
    plan, probes = frozen(tmp_path, model_file, source_file)
    calls = {"n": 0}

    def crashing(*_a, **_k):
        calls["n"] += 1
        raise RuntimeError("driver exploded")

    verdict, run_dir = run_gate(
        tmp_path,
        authorize(plan),
        probes,
        ctx_for(probes),
        executor=crashing,
        confirm=lambda _p: confirmation_phrase(plan),
    )
    evidence = json.loads((run_dir / "evidence.json").read_text(encoding="utf-8"))
    assert verdict == NO_GO and calls["n"] == 1
    assert (
        evidence["outcomes"]["physical_execution"] == "RAN"
        and evidence["outcomes"]["functional"] == FAIL
    )
    assert "driver exploded" in evidence["outcomes"]["reason"]


def test_plans_missing_limits_runtime_identity_or_an_unreadable_file_hold_before_any_launch(
    tmp_path: Path, model_file, source_file
) -> None:
    plan, probes = frozen(tmp_path, model_file, source_file)
    approved = authorize(plan)
    no_limits = deepcopy(approved)
    no_limits["limits"].pop("max_vram_used_mib")
    no_identity = deepcopy(approved)
    no_identity["targets"]["image"]["runtime"].pop("identity")
    for broken in (no_limits, no_identity):
        verdict, run_dir = run_gate(
            tmp_path,
            broken,
            probes,
            ctx_for(probes),
            executor=boom,
            confirm=lambda _p: confirmation_phrase(plan),
        )
        assert verdict == HOLD
        assert (
            json.loads((run_dir / "evidence.json").read_text(encoding="utf-8"))["outcomes"][
                "physical_execution"
            ]
            == "NOT RUN"
        )
    from tools.operator_journey.golden import definitions
    from tools.operator_journey.golden.physical import run_physical

    verdict, _ = run_physical(
        tmp_path / "missing.json",
        journeys=definitions.select("image"),
        evidence_root=tmp_path / "ev",
        probes=probes,
    )
    assert verdict == HOLD


def test_readiness_with_real_probes_only_reads(
    tmp_path: Path, model_file, source_file, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Whatever the host answers, readiness may run only nvidia-smi/git/ffprobe, GET requests and a process listing."""

    from tools.operator_journey.golden.suite import run_readiness

    plan, _ = frozen(tmp_path, model_file, source_file)
    plan_path = tmp_path / "plan.json"
    plan_path.write_text(json.dumps(plan, default=str), encoding="utf-8")
    commands: list[str] = []
    requests: list[str] = []
    real_popen = subprocess.Popen

    class SpyPopen(real_popen):  # every subprocess helper funnels through Popen
        def __init__(self, args, *a, **k):
            commands.append(
                Path(str(args[0] if isinstance(args, (list, tuple)) else args)).stem.lower()
            )
            super().__init__(args, *a, **k)

    def forbidden(*_a, **_k):
        raise AssertionError("readiness must not start a process")

    def spy_urlopen(request, *a, **k):
        requests.append("GET" if isinstance(request, str) else request.get_method())
        raise OSError("no network in this test")

    monkeypatch.setattr(subprocess, "Popen", SpyPopen)
    monkeypatch.setattr(os, "startfile", forbidden, raising=False)
    monkeypatch.setattr(os, "system", forbidden)
    monkeypatch.setattr(urllib.request, "urlopen", spy_urlopen)
    verdict, run_dir = run_readiness(plan_path, evidence_root=tmp_path / "ev")
    assert verdict in {"PASS", "HOLD", "NO-GO"} and (run_dir / "evidence.json").is_file()
    assert set(commands) <= {
        "nvidia-smi",
        "git",
        "ffprobe",
        "ffmpeg",
        "tasklist",
        "wmic",
        "powershell",
    }
    assert set(requests) <= {"GET"}
    report = json.loads((run_dir / "evidence.json").read_text(encoding="utf-8"))["readiness"]
    assert report["started_runtime"] is False and report["physical_run_authorized"] is False


def test_the_native_dialog_responder_ignores_windows_of_other_processes() -> None:
    from tools.operator_journey.desktop import NativeDialogResponder

    seen: list[int] = []

    class Win32Double:
        def dialogs_of(self, pid: int) -> list[int]:
            seen.append(pid)
            return []

    responder = NativeDialogResponder(Win32Double(), 4242)
    responder.__enter__()
    try:
        import time

        time.sleep(0.4)
    finally:
        responder.__exit__(None, None, None)
    assert seen and set(seen) == {4242}  # only its own process is ever asked about


def test_the_native_dialog_responder_waits_for_a_dialog_that_is_still_being_built() -> None:
    """A file dialog exists before its controls do; answering it early consumed the answer and hung the app."""

    import time

    from tools.operator_journey.desktop import NativeDialogResponder

    polls = {"n": 0}
    typed: list[str] = []
    clicked: list[int] = []

    class Win32Double:
        def dialogs_of(self, pid: int) -> list[int]:
            return [7]

        def children_of(self, hwnd: int) -> list[tuple[int, str, str]]:
            polls["n"] += 1
            if polls["n"] < 4:  # the window is there, its controls are not
                return []
            return [(11, "Edit", ""), (12, "Button", "&Open"), (13, "Button", "Cancel")]

        def text(self, hwnd: int) -> str:
            return "Open Storyboard"

        def set_text(self, hwnd: int, value: str) -> None:
            typed.append(value)

        def click_button(self, hwnd: int) -> None:
            clicked.append(hwnd)

    responder = NativeDialogResponder(Win32Double(), 4242)
    responder.queue("file", "C:/x/draft.json")
    responder.__enter__()
    try:
        deadline = time.monotonic() + 5
        while not clicked and time.monotonic() < deadline:
            time.sleep(0.05)
    finally:
        responder.__exit__(None, None, None)
    assert typed == ["C:/x/draft.json"] and clicked == [12]
    assert responder.seen[0]["answer"] == "file:C:/x/draft.json" and polls["n"] >= 4
