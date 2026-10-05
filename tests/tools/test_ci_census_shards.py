"""PR-DEVEX-CENSUS-140: deterministic file-level census sharding and its fail-closed completeness guard."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools" / "ci"))

import census_shards as cs  # noqa: E402
import run_collection_gate as gate  # noqa: E402
import run_sharded_census as local  # noqa: E402


def _touch(root: Path, rel: str) -> None:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("def test_x():\n    pass\n", encoding="utf-8")


def _tree(tmp_path: Path) -> Path:
    (tmp_path / "pyproject.toml").write_text(
        '[tool.pytest.ini_options]\ntestpaths = ["tests"]\nnorecursedirs = ["archive"]\n', encoding="utf-8"
    )
    for rel in (
        "tests/test_a.py", "tests/api/test_b.py", "tests/api/sub/test_c.py", "tests/gui_v2/test_d.py",
        "tests/api/helpers.py",  # not test_*.py
        "tests/legacy/test_old.py", "tests/quarantine/test_q.py", "tests/scripts/test_s.py",
        "tests/gui_v1_legacy/test_g.py", "tests/gui_v2/archive/test_arch.py",
    ):
        _touch(tmp_path, rel)
    return tmp_path


def test_active_surface_excludes_ignored_directories_and_non_test_files(tmp_path: Path) -> None:
    files = cs.active_test_files(_tree(tmp_path))

    assert files == ["tests/api/sub/test_c.py", "tests/api/test_b.py", "tests/gui_v2/test_d.py", "tests/test_a.py"]


def test_active_surface_matches_what_pytest_actually_collects() -> None:
    """The planner must not define a second test universe: every collected module is an active file."""

    result = subprocess.run(
        [sys.executable, "-m", "pytest", "--collect-only", "-q", "-p", "no:cacheprovider"],
        cwd=ROOT, capture_output=True, text=True, check=False,
    )
    collected = {line.split("::")[0].replace("\\", "/") for line in result.stdout.splitlines() if "::" in line}
    active = set(cs.active_test_files())

    assert collected, result.stdout[-500:]
    assert collected <= active, sorted(collected - active)[:5]
    # files that collect nothing (collection-time skips / zero tests) are the only allowed extras
    assert len(active - collected) <= 10


def test_exclusions_come_from_the_collection_gate_authority() -> None:
    for excluded in gate.DEFAULT_COLLECTION_EXCLUDES:
        assert not any(f.startswith(excluded + "/") for f in cs.active_test_files())


@pytest.mark.parametrize("raw", ["tests/api/test_b.py", "./tests/api/test_b.py", "tests\\api\\test_b.py", Path("tests/api/test_b.py")])
def test_path_normalization_is_cross_platform_stable(raw) -> None:
    assert cs.normalize_path(raw) == "tests/api/test_b.py"
    assert cs.shard_of(raw, 3) == cs.shard_of("tests/api/test_b.py", 3)


def test_assignment_is_the_documented_sha256_function_and_stable() -> None:
    import hashlib

    for path in ("tests/test_a.py", "tests/queue/test_job_repository_sqlite.py"):
        assert cs.shard_of(path, 3) == int(hashlib.sha256(path.encode()).hexdigest(), 16) % 3
    # pinned values protect against an accidental change of the hash/partition (that would reshuffle every shard)
    assert cs.shard_of("tests/test_a.py", 3) == 1
    assert cs.shard_of("tests/queue/test_job_repository_sqlite.py", 3) == 0
    assert cs.shard_of("tests/gui_v2/test_image_thumbnail_v2.py", 3) == 1
    assert cs.shard_of("tests/gui_v2/test_image_thumbnail_v2.py", 2) == 0


def test_real_repository_partition_is_complete_disjoint_and_roughly_balanced() -> None:
    active = cs.active_test_files()
    shards = cs.partition(active, 3)

    assert cs.partition_problems(active, shards) == []
    assert sorted(f for shard in shards for f in shard) == active
    assert len({f for shard in shards for f in shard}) == len(active)
    assert all(len(shard) > 0.25 * len(active) for shard in shards)


def test_a_new_test_file_is_assigned_automatically_without_a_manifest(tmp_path: Path) -> None:
    root = _tree(tmp_path)
    before = cs.partition(cs.active_test_files(root), 3)
    _touch(root, "tests/pipeline/test_brand_new.py")
    after = cs.partition(cs.active_test_files(root), 3)

    assert "tests/pipeline/test_brand_new.py" in after[cs.shard_of("tests/pipeline/test_brand_new.py", 3)]
    assert sum(map(len, after)) == sum(map(len, before)) + 1
    assert cs.partition_problems(cs.active_test_files(root), after) == []


def test_zero_test_files_stay_assigned(tmp_path: Path) -> None:
    root = _tree(tmp_path)
    (root / "tests" / "test_nothing.py").write_text("# no tests here\n", encoding="utf-8")
    (root / "tests" / "test_skipped.py").write_text("import pytest\npytest.skip('x', allow_module_level=True)\n", encoding="utf-8")

    files = cs.active_test_files(root)

    assert "tests/test_nothing.py" in files and "tests/test_skipped.py" in files
    assert cs.partition_problems(files, cs.partition(files, 3)) == []


def test_the_guard_detects_missing_duplicated_and_foreign_files() -> None:
    active = ["tests/a/test_1.py", "tests/b/test_2.py", "tests/c/test_3.py"]

    assert any("assigned to no shard" in p for p in cs.partition_problems(active, [["tests/a/test_1.py"], ["tests/b/test_2.py"]]))
    assert any("assigned to shards" in p for p in cs.partition_problems(active, [active, ["tests/a/test_1.py"]]))
    assert any("outside the active census" in p for p in cs.partition_problems(active, [active, ["tests/z/test_9.py"]]))


# --- aggregate -----------------------------------------------------------------------------------------------------

JUNIT = (
    '<?xml version="1.0" encoding="utf-8"?><testsuites><testsuite name="pytest" tests="{n}" time="{t}">{cases}</testsuite></testsuites>'
)


def _shard_artifacts(directory: Path, shards: list[list[str]], *, exit_codes=None, wall=None, drop=None) -> None:
    for index, files in enumerate(shards):
        if drop == index:
            continue
        cases = "".join(
            f'<testcase classname="{f[:-3].replace("/", ".")}" name="test_x" time="1.0"/>' for f in files
        )
        (directory / f"census-shard-{index}.xml").write_text(JUNIT.format(n=len(files), t=len(files), cases=cases), encoding="utf-8")
        (directory / f"census-shard-{index}.manifest.json").write_text(json.dumps({"index": index, "shards": len(shards), "files": files}), encoding="utf-8")
        (directory / f"census-shard-{index}.result.json").write_text(json.dumps({
            "index": index, "shards": len(shards), "files": len(files),
            "exit_code": (exit_codes or {}).get(index, 0), "pytest_wall_seconds": (wall or {}).get(index, 10.0 + index),
        }), encoding="utf-8")


def test_aggregate_passes_for_a_complete_consistent_census(tmp_path: Path) -> None:
    active = ["tests/a/test_1.py", "tests/b/test_2.py", "tests/c/test_3.py", "tests/d/test_4.py", "tests/e/test_5.py"]
    shards = cs.partition(active, 3)
    _shard_artifacts(tmp_path, shards, wall={0: 100.0, 1: 150.0, 2: 120.0})

    problems, evidence = cs.verify_results(3, tmp_path, active=active)

    assert problems == []
    assert evidence["parallel_wall_seconds"] == 150.0  # slowest shard, not the sum
    assert evidence["sum_shard_wall_seconds"] == 370.0
    assert evidence["summary"]["collected"] == 5 and evidence["summary"]["passed"] == 5
    assert "PASS" in cs.render_aggregate(problems, evidence)


def test_aggregate_fails_closed_on_a_missing_shard_artifact(tmp_path: Path) -> None:
    active = [f"tests/m{n}/test_{n}.py" for n in range(9)]
    shards = cs.partition(active, 3)
    _shard_artifacts(tmp_path, shards, drop=1)

    problems, _ = cs.verify_results(3, tmp_path, active=active)

    assert any("shard 1" in p and "missing" in p for p in problems)


def test_aggregate_fails_on_a_shard_pytest_failure(tmp_path: Path) -> None:
    active = [f"tests/m{n}/test_{n}.py" for n in range(9)]
    _shard_artifacts(tmp_path, cs.partition(active, 3), exit_codes={2: 1})

    problems, _ = cs.verify_results(3, tmp_path, active=active)

    assert any("shard 2" in p and "exited with 1" in p for p in problems)


def test_aggregate_fails_when_a_new_active_file_was_not_in_the_shard_manifests(tmp_path: Path) -> None:
    active = [f"tests/m{n}/test_{n}.py" for n in range(9)]
    _shard_artifacts(tmp_path, cs.partition(active, 3))

    problems, _ = cs.verify_results(3, tmp_path, active=[*active, "tests/new/test_new.py"])

    assert any("differs from the partition" in p or "assigned to no shard" in p for p in problems)


def test_aggregate_fails_on_junit_records_outside_the_manifest(tmp_path: Path) -> None:
    active = [f"tests/m{n}/test_{n}.py" for n in range(9)]
    shards = cs.partition(active, 3)
    _shard_artifacts(tmp_path, shards)
    xml = tmp_path / "census-shard-0.xml"
    xml.write_text(xml.read_text(encoding="utf-8").replace("</testsuite>", '<testcase classname="tests.zz.test_stray" name="test_x" time="1"/></testsuite>'), encoding="utf-8")

    problems, _ = cs.verify_results(3, tmp_path, active=active)

    assert any("outside its manifest" in p for p in problems)


def test_merged_junit_keeps_the_single_census_summarizer_authoritative(tmp_path: Path) -> None:
    import census_summary

    a, b, out = tmp_path / "a.xml", tmp_path / "b.xml", tmp_path / "m.xml"
    a.write_text(JUNIT.format(n=1, t=2, cases='<testcase classname="tests.x.test_a" name="t" time="2"/>'), encoding="utf-8")
    b.write_text(JUNIT.format(n=2, t=3, cases='<testcase classname="tests.y.test_b" name="t" time="1"><failure message="boom"/></testcase><testcase classname="tests.y.test_b" name="u" time="2"><skipped message="why"/></testcase>'), encoding="utf-8")

    cs.merge_junit([a, b], out)
    summary = census_summary.summarize(out)

    assert (summary["collected"], summary["passed"], summary["failed"], summary["skipped"]) == (3, 1, 1, 1)


# --- the local runner ------------------------------------------------------------------------------------------------


def test_local_workers_share_the_partition_but_never_share_temp_or_cache_directories(tmp_path: Path) -> None:
    c0 = local.worker_command(2, 0, tmp_path)
    c1 = local.worker_command(2, 1, tmp_path)

    assert local.DEFAULT_WORKERS == 2
    assert (tmp_path / "worker-0").is_dir() and (tmp_path / "worker-1").is_dir()  # parents of --basetemp exist
    assert "--shards" in c0 and c0[c0.index("--shards") + 1] == "2" and c1[c1.index("--shards") + 1] == "2"
    assert c0[c0.index("--index") + 1] == "0" and c1[c1.index("--index") + 1] == "1"
    base0 = next(a for a in c0 if a.startswith("--basetemp="))
    base1 = next(a for a in c1 if a.startswith("--basetemp="))
    assert base0 != base1
    assert next(a for a in c0 if a.startswith("cache_dir=")) != next(a for a in c1 if a.startswith("cache_dir="))


def test_run_shard_executes_ordinary_pytest_on_whole_files_and_records_the_result(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    (root / "tests").mkdir(parents=True)
    (root / "pyproject.toml").write_text('[tool.pytest.ini_options]\ntestpaths = ["tests"]\npython_files = ["test_*.py"]\n', encoding="utf-8")
    names = [f"tests/test_n{n}.py" for n in range(4)]
    for rel in names:
        (root / rel).write_text("def test_ok():\n    assert True\n", encoding="utf-8")
    out = tmp_path / "out"

    codes = [cs.run_shard(2, index, out, root=root, extra_pytest_args=("-p", "no:cacheprovider")) for index in (0, 1)]

    assert codes == [0, 0]
    problems, evidence = cs.verify_results(2, out, root=root)
    assert problems == []
    assert evidence["summary"]["collected"] == 4 and evidence["summary"]["passed"] == 4


def test_isolated_worker_checkout_matches_the_developers_working_tree(tmp_path: Path, monkeypatch) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()

    def git(*args: str) -> None:
        subprocess.run(["git", "-c", "user.email=t@t", "-c", "user.name=t", *args], cwd=repo, check=True, capture_output=True)

    git("init", "-q")
    (repo / "kept.txt").write_text("v1", encoding="utf-8")
    (repo / "changed.txt").write_text("v1", encoding="utf-8")
    (repo / "removed.txt").write_text("v1", encoding="utf-8")
    git("add", "-A")
    git("commit", "-q", "-m", "base")
    (repo / "changed.txt").write_text("v2", encoding="utf-8")  # uncommitted edit
    (repo / "removed.txt").unlink()  # uncommitted delete
    (repo / "new").mkdir()
    (repo / "new" / "untracked.txt").write_text("u", encoding="utf-8")  # untracked file
    monkeypatch.setattr(local, "ROOT", repo)

    checkout = local.make_isolated_checkout(tmp_path / "worker-repo")
    try:
        assert (checkout / "kept.txt").read_text(encoding="utf-8") == "v1"
        assert (checkout / "changed.txt").read_text(encoding="utf-8") == "v2"
        assert not (checkout / "removed.txt").exists()
        assert (checkout / "new" / "untracked.txt").read_text(encoding="utf-8") == "u"
        assert checkout != repo
    finally:
        local.remove_isolated_checkout(checkout)
    assert not (tmp_path / "worker-repo").exists()


def test_collection_skip_records_are_attributed_to_their_module(tmp_path: Path) -> None:
    import census_summary

    xml = tmp_path / "c.xml"
    xml.write_text(JUNIT.format(n=1, t=0, cases='<testcase classname="" name="tests.video.test_x" time="0"><skipped message="collection skipped"/></testcase>'), encoding="utf-8")

    assert census_summary.summarize(xml)["by_file"][0]["file"] == "tests/video/test_x.py"
    assert cs.junit_files(xml) == {"tests/video/test_x.py"}
