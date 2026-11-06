"""PR-DEVEX-CENSUS-150: deterministic timing-informed weighted census sharding.

Covers the shard-count-independent algorithm (N = 1..8 and beyond the file count), missing / stale / incomplete timing
data, new test files, timing-manifest integrity (fail closed), complete file coverage (every active file in exactly one
shard) and the manifest refresh gate. Pure functions over temporary trees; no test of the real suite is executed.
"""

from __future__ import annotations

import hashlib
import json
import math
import random
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools" / "ci"))

import census_shards as cs  # noqa: E402
import census_weights as cw  # noqa: E402

SHARD_COUNTS = range(1, 9)


def _timings(files_ms: dict[str, int], source: str = "unit test") -> cw.Timings:
    return cw.parse_manifest(cw.build_manifest(files_ms, source))


def _tree(tmp_path: Path, names: list[str]) -> Path:
    tmp_path.mkdir(parents=True, exist_ok=True)
    (tmp_path / "pyproject.toml").write_text(
        '[tool.pytest.ini_options]\ntestpaths = ["tests"]\n', encoding="utf-8"
    )
    for rel in names:
        path = tmp_path / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("def test_x():\n    assert True\n", encoding="utf-8")
    return tmp_path


def _write_timings(root: Path, files_ms: dict[str, int]) -> Path:
    path = root / cw.TIMINGS_RELATIVE_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(cw.build_manifest(files_ms, "unit test")), encoding="utf-8")
    return path


def _synthetic(count: int = 60, seed: int = 7) -> tuple[list[str], dict[str, int]]:
    rng = random.Random(seed)
    files = [f"tests/area{n % 7}/test_f{n:03d}.py" for n in range(count)]
    return files, {f: int(rng.paretovariate(1.2) * 400) for f in files}


# --- the algorithm: shard-count independence ---------------------------------------------------------------------------


@pytest.mark.parametrize("shard_count", SHARD_COUNTS)
def test_every_shard_count_partitions_the_real_census_completely_and_deterministically(
    shard_count: int,
) -> None:
    active = cs.active_test_files()
    plan = cs.build_plan(shard_count)

    assert len(plan.shards) == shard_count
    assert cs.partition_problems(active, plan.shards) == []  # complete, disjoint, nothing foreign
    assert sorted(f for shard in plan.shards for f in shard) == active
    assert all(shard == sorted(shard) for shard in plan.shards)
    again = cs.build_plan(shard_count)
    assert again.shards == plan.shards and again.digest == plan.digest


@pytest.mark.parametrize("shard_count", SHARD_COUNTS)
def test_real_census_balance_stays_within_the_lpt_guarantee_and_never_loses_to_the_hash_partition(
    shard_count: int,
) -> None:
    active = cs.active_test_files()
    timings = cw.load_timings(cs.timings_path())
    assert timings is not None, "the committed timing manifest is missing"
    report = cw.weigh(active, timings)
    loads = cw.shard_loads(cs.build_plan(shard_count).shards, report.weights)
    total = sum(report.weights.values())
    floor = max(max(report.weights.values()), math.ceil(total / shard_count))

    # Graham's bound for greedy longest-first scheduling: makespan <= (4/3 - 1/(3N)) * optimum >= floor.
    assert max(loads) <= (4 / 3 - 1 / (3 * shard_count)) * floor + 1

    # The previous sha256(path) % N partition is the baseline this algorithm replaces.
    hashed: list[list[str]] = [[] for _ in range(shard_count)]
    for file in active:
        hashed[int(hashlib.sha256(file.encode("utf-8")).hexdigest(), 16) % shard_count].append(file)
    assert max(loads) <= max(cw.shard_loads(hashed, report.weights))


def test_known_weights_produce_the_documented_longest_first_assignment() -> None:
    timings = _timings(
        {
            "tests/a/test_a.py": 7000,
            "tests/a/test_b.py": 5000,
            "tests/a/test_c.py": 4000,
            "tests/a/test_d.py": 3000,
            "tests/a/test_e.py": 2000,
            "tests/a/test_f.py": 1000,
        }
    )

    shards = cw.weighted_partition(list(timings.files), 2, timings)

    # 7 -> s0; 5 -> s1; 4 -> s1 (5 < 7); 3 -> s0 (7 < 9); 2 -> s0 (10 vs 9 -> s1); pinned so the algorithm cannot drift
    assert shards == [
        ["tests/a/test_a.py", "tests/a/test_d.py", "tests/a/test_f.py"],
        ["tests/a/test_b.py", "tests/a/test_c.py", "tests/a/test_e.py"],
    ]


def test_ties_resolve_by_path_then_lowest_shard_and_input_order_never_matters() -> None:
    files, ms = _synthetic()
    timings = _timings(ms)
    baseline = cw.weighted_partition(files, 5, timings)
    shuffled = list(files)
    random.Random(3).shuffle(shuffled)

    assert cw.weighted_partition(shuffled, 5, timings) == baseline
    assert (
        cw.weighted_partition([f.replace("/", "\\") for f in files], 5, timings) == baseline
    )  # Windows spelling
    assert cw.weighted_partition(files + files, 5, timings) == baseline  # duplicates collapse

    equal = cw.weighted_partition(
        ["tests/z/test_3.py", "tests/z/test_1.py", "tests/z/test_2.py"], 2, None
    )
    assert equal == [["tests/z/test_1.py", "tests/z/test_3.py"], ["tests/z/test_2.py"]]


def test_more_shards_than_files_leaves_empty_shards_but_loses_nothing() -> None:
    files = ["tests/a/test_1.py", "tests/a/test_2.py", "tests/a/test_3.py"]

    for count in (4, 8, 50):
        shards = cw.weighted_partition(files, count, None)
        assert len(shards) == count
        assert sum(1 for s in shards if s) == 3 and cs.partition_problems(files, shards) == []


def test_zero_files_and_invalid_shard_counts() -> None:
    assert cw.weighted_partition([], 3, None) == [[], [], []]
    for bad in (0, -1):
        with pytest.raises(ValueError):
            cw.weighted_partition(["tests/a/test_1.py"], bad, None)


@pytest.mark.parametrize("shard_count", SHARD_COUNTS)
def test_synthetic_heavy_tailed_timings_stay_balanced_at_every_shard_count(
    shard_count: int,
) -> None:
    files, ms = _synthetic(count=200)
    timings = _timings(ms)
    shards = cw.weighted_partition(files, shard_count, timings)
    weights = cw.weigh(files, timings).weights
    loads = cw.shard_loads(shards, weights)
    floor = max(max(weights.values()), math.ceil(sum(weights.values()) / shard_count))

    assert cs.partition_problems(files, shards) == []
    assert max(loads) <= (4 / 3 - 1 / (3 * shard_count)) * floor + 1


# --- missing, stale and incomplete timing data ------------------------------------------------------------------------


def test_missing_timing_data_degrades_to_uniform_weights_without_losing_a_file() -> None:
    files = [f"tests/m{n}/test_{n:02d}.py" for n in range(10)]
    shards = cw.weighted_partition(files, 3, None)

    assert sorted(map(len, shards)) == [3, 3, 4]
    assert cs.partition_problems(files, shards) == []
    assert (
        cw.weigh(files, None).unmeasured == ()
    )  # nothing is "unmeasured" when there is no manifest at all


def test_stale_records_are_ignored_and_reported() -> None:
    timings = _timings({"tests/a/test_old.py": 99_000, "tests/a/test_kept.py": 1000})
    active = ["tests/a/test_kept.py", "tests/a/test_new.py"]

    report = cw.weigh(active, timings)

    assert report.stale == ("tests/a/test_old.py",)
    assert "tests/a/test_old.py" not in report.weights
    assert report.unmeasured == ("tests/a/test_new.py",)
    assert cs.partition_problems(active, cw.weighted_partition(active, 2, timings)) == []


def test_a_new_file_gets_the_median_recorded_duration_not_zero_and_not_the_maximum() -> None:
    timings = _timings(
        {"tests/a/test_1.py": 100, "tests/a/test_2.py": 200, "tests/a/test_3.py": 90_000}
    )

    report = cw.weigh(
        ["tests/a/test_1.py", "tests/a/test_2.py", "tests/a/test_3.py", "tests/a/test_new.py"],
        timings,
    )

    assert report.default_ms == 200  # median
    assert report.weights["tests/a/test_new.py"] == 200 + cw.FILE_OVERHEAD_MS


def test_an_empty_or_partial_manifest_never_removes_files_from_the_census(tmp_path: Path) -> None:
    root = _tree(tmp_path, [f"tests/p{n}/test_{n}.py" for n in range(12)])
    active = cs.active_test_files(root)
    for recorded in ({}, {"tests/p3/test_3.py": 5000}, dict.fromkeys(active[:6], 10)):
        _write_timings(root, recorded)
        for count in SHARD_COUNTS:
            plan = cs.build_plan(count, root=root)
            assert cs.partition_problems(active, plan.shards) == []


def test_a_new_test_file_lands_in_exactly_one_shard_and_the_old_assignment_stays_valid(
    tmp_path: Path,
) -> None:
    root = _tree(tmp_path, [f"tests/p{n}/test_{n}.py" for n in range(9)])
    _write_timings(root, {f"tests/p{n}/test_{n}.py": 1000 * (n + 1) for n in range(9)})
    before = cs.build_plan(3, root=root)
    (root / "tests/p0/test_brand_new.py").write_text(
        "def test_y():\n    assert True\n", encoding="utf-8"
    )

    after = cs.build_plan(3, root=root)

    assert sum(s.count("tests/p0/test_brand_new.py") for s in after.shards) == 1
    assert after.unmeasured == ("tests/p0/test_brand_new.py",)
    assert sum(map(len, after.shards)) == sum(map(len, before.shards)) + 1
    assert after.timing_digest == before.timing_digest and after.digest != before.digest


# --- manifest integrity: fail closed ---------------------------------------------------------------------------------------


def _good() -> dict:
    return cw.build_manifest({"tests/a/test_1.py": 100, "tests/b/test_2.py": 250}, "unit")


def test_a_valid_manifest_round_trips_with_a_content_digest_that_ignores_the_source_note() -> None:
    manifest = _good()
    parsed = cw.parse_manifest(json.loads(json.dumps(manifest)))

    assert parsed.files == {"tests/a/test_1.py": 100, "tests/b/test_2.py": 250}
    assert parsed.digest == manifest["digest"]
    assert cw.build_manifest(dict(parsed.files), "a different note")["digest"] == manifest["digest"]
    assert list(manifest["files"]) == sorted(manifest["files"])  # type: ignore[arg-type]


@pytest.mark.parametrize(
    "mutate",
    [
        lambda m: m["files"].__setitem__("tests/a/test_1.py", 101),  # value edited, digest stale
        lambda m: m["files"].__setitem__("tests/c/test_3.py", 5),  # record added, digest stale
        lambda m: m.__setitem__("digest", "0" * 64),
        lambda m: m.__setitem__("schema", 2),
        lambda m: m.__setitem__("unit", "seconds"),
        lambda m: m.__setitem__("source", 7),
        lambda m: m.__setitem__("extra", True),
        lambda m: m.pop("digest"),
        lambda m: m.__setitem__("files", ["tests/a/test_1.py"]),
    ],
)
def test_any_tampering_with_the_manifest_is_rejected(mutate) -> None:
    manifest = json.loads(json.dumps(_good()))
    mutate(manifest)

    with pytest.raises(cw.TimingsError):
        cw.parse_manifest(manifest)


@pytest.mark.parametrize("bad", [-1, 1.5, True, "12", None, cw.MAX_FILE_MS + 1, float("nan")])
def test_a_duration_must_be_a_plain_bounded_non_negative_integer(bad) -> None:
    with pytest.raises(cw.TimingsError):
        cw.build_manifest({"tests/a/test_1.py": bad}, "unit")  # type: ignore[dict-item]


@pytest.mark.parametrize(
    "key", ["/abs/test_1.py", "tests/a/readme.md", "../escape/test_1.py".replace("../", "/"), ""]
)
def test_a_key_must_be_a_repo_relative_python_test_path(key: str) -> None:
    with pytest.raises(cw.TimingsError):
        cw.build_manifest({key: 1}, "unit")


def test_manifest_files_on_disk_are_loaded_strictly(tmp_path: Path) -> None:
    path = tmp_path / "census_timings.json"
    assert cw.load_timings(path) is None  # absent: uniform weights, not an error

    path.write_text(json.dumps(_good()), encoding="utf-8")
    assert cw.load_timings(path) is not None

    for broken in ("", "{not json", "[]", json.dumps(_good())[:-20]):
        path.write_text(broken, encoding="utf-8")
        with pytest.raises(cw.TimingsError):
            cw.load_timings(path)


def test_a_corrupt_manifest_fails_the_plan_the_verifier_and_the_cli_closed(
    tmp_path: Path, capsys
) -> None:
    root = _tree(tmp_path, ["tests/a/test_1.py", "tests/a/test_2.py"])
    path = _write_timings(root, {"tests/a/test_1.py": 10})
    corrupt = json.loads(path.read_text(encoding="utf-8"))
    corrupt["files"]["tests/a/test_1.py"] = 11
    path.write_text(json.dumps(corrupt), encoding="utf-8")

    with pytest.raises(cw.TimingsError):
        cs.build_plan(2, root=root)
    problems, evidence = cs.verify_results(2, tmp_path / "none", root=root)
    assert (
        problems
        and "cannot derive the shard plan" in problems[0]
        and evidence["shard_results"] == []
    )
    with pytest.raises(cw.TimingsError):
        cs.run_shard(2, 0, tmp_path / "out", root=root)
    assert not (tmp_path / "out" / "census-shard-0.xml").exists()  # nothing ran


def test_the_committed_manifest_is_intact_and_describes_only_real_paths() -> None:
    timings = cw.load_timings(cs.timings_path())

    assert timings is not None and timings.files
    assert all(path.startswith("tests/") for path in timings.files)
    assert timings.digest == cw.canonical_digest(timings.files)


# --- selection guards and the empty-shard hazard -----------------------------------------------------------------------------


@pytest.mark.parametrize("shards,index", [(3, -1), (3, 3), (0, 0), (-2, 0)])
def test_shard_selection_outside_the_range_is_rejected_not_wrapped(
    shards: int, index: int, tmp_path: Path
) -> None:
    with pytest.raises(ValueError):
        cs.check_index(shards, index)
    with pytest.raises(ValueError):
        cs.run_shard(
            shards, index, tmp_path / "out", root=_tree(tmp_path / "r", ["tests/a/test_1.py"])
        )


def test_cli_reports_bad_input_as_exit_2(tmp_path: Path, capsys) -> None:
    assert cs.main(["plan", "--shards", "3", "--index", "-1"]) == 2
    assert "--index must be in 0..2" in capsys.readouterr().err
    assert cs.main(["plan", "--shards", "0", "--index", "0"]) == 2


def test_an_empty_shard_runs_no_tests_instead_of_falling_back_to_the_whole_suite(
    tmp_path: Path,
) -> None:
    root = _tree(tmp_path / "repo", ["tests/a/test_1.py", "tests/a/test_2.py"])
    out = tmp_path / "out"

    codes = [
        cs.run_shard(4, i, out, root=root, extra_pytest_args=("-p", "no:cacheprovider"))
        for i in range(4)
    ]

    assert codes == [0, 0, 0, 0]
    results = [
        json.loads((out / f"census-shard-{i}.result.json").read_text(encoding="utf-8"))
        for i in range(4)
    ]
    assert sorted(r["files"] for r in results) == [0, 0, 1, 1]
    problems, evidence = cs.verify_results(4, out, root=root)
    assert problems == []
    assert (
        evidence["summary"]["collected"] == 2
    )  # exactly the two real tests; no shard ran anything extra


# --- the aggregate gate against the plan ---------------------------------------------------------------------------------------


def _artifacts(
    directory: Path,
    plan: cs.CensusPlan,
    *,
    plan_digest: str | None = None,
    identity: tuple[int, int] | None = None,
) -> None:
    for index, files in enumerate(plan.shards):
        cases = "".join(
            f'<testcase classname="{f[:-3].replace("/", ".")}" name="test_x" time="1.0"/>'
            for f in files
        )
        (directory / f"census-shard-{index}.xml").write_text(
            f'<testsuites><testsuite name="pytest" tests="{len(files)}" time="{len(files)}">{cases}</testsuite></testsuites>',
            encoding="utf-8",
        )
        shard_index, shard_total = (
            identity if identity and index == 0 else (index, plan.shard_count)
        )
        (directory / f"census-shard-{index}.manifest.json").write_text(
            json.dumps(
                {
                    "index": shard_index,
                    "shards": shard_total,
                    "files": files,
                    "plan_digest": plan_digest or plan.digest,
                }
            ),
            encoding="utf-8",
        )
        (directory / f"census-shard-{index}.result.json").write_text(
            json.dumps(
                {
                    "index": index,
                    "shards": plan.shard_count,
                    "files": len(files),
                    "exit_code": 0,
                    "pytest_wall_seconds": 5.0,
                }
            ),
            encoding="utf-8",
        )


def test_verify_rejects_shards_planned_from_a_different_tree_or_timing_manifest(
    tmp_path: Path,
) -> None:
    root = _tree(tmp_path / "repo", [f"tests/p{n}/test_{n}.py" for n in range(9)])
    _write_timings(root, {f"tests/p{n}/test_{n}.py": 500 * (n + 1) for n in range(9)})
    out = tmp_path / "out"
    out.mkdir()
    plan = cs.build_plan(3, root=root)

    _artifacts(out, plan)
    assert cs.verify_results(3, out, root=root)[0] == []

    _artifacts(out, plan, plan_digest="f" * 64)
    assert any("plan digest differs" in p for p in cs.verify_results(3, out, root=root)[0])

    _artifacts(out, plan, identity=(2, 3))  # shard 0's artifact claims to be shard 2
    assert any(
        "identifies itself as shard 2 of 3" in p for p in cs.verify_results(3, out, root=root)[0]
    )

    _artifacts(out, plan)
    _write_timings(
        root, {f"tests/p{n}/test_{n}.py": 10 for n in range(9)}
    )  # timing manifest changed after the run
    assert any(
        "differs from the partition" in p or "plan digest differs" in p
        for p in cs.verify_results(3, out, root=root)[0]
    )


def test_aggregate_reports_predicted_and_actual_time_and_timing_coverage(tmp_path: Path) -> None:
    root = _tree(tmp_path / "repo", [f"tests/p{n}/test_{n}.py" for n in range(6)])
    _write_timings(root, {f"tests/p{n}/test_{n}.py": 1000 for n in range(4)})
    out = tmp_path / "out"
    out.mkdir()
    _artifacts(out, cs.build_plan(2, root=root))

    problems, evidence = cs.verify_results(2, out, root=root)
    text = cs.render_aggregate(problems, evidence)

    assert problems == []
    assert evidence["weights_source"] == "timings" and len(evidence["unmeasured_files"]) == 2
    assert "predicted s" in text and "2 active files without a recorded duration" in text


# --- refreshing the manifest ---------------------------------------------------------------------------------------------------


def _green_run(tmp_path: Path, names: list[str], shards: int = 2) -> tuple[Path, Path]:
    root = _tree(tmp_path / "repo", names)
    out = tmp_path / "run"
    out.mkdir()
    plan = cs.build_plan(shards, root=root, timings=None)
    _artifacts(out, plan)
    return root, out


def test_refresh_builds_a_deterministic_manifest_from_a_complete_green_run(tmp_path: Path) -> None:
    root, out = _green_run(
        tmp_path, ["tests/a/test_1.py", "tests/a/test_2.py", "tests/b/test_3.py"]
    )
    (out / "census-shard-0.xml").write_text(
        '<testsuites><testsuite name="p" tests="3" time="9"><testcase classname="tests.a.test_1" name="x" time="1.2346"/>'
        '<testcase classname="tests.a.test_1" name="y" time="2"/><testcase classname="tests.gone.test_9" name="z" time="50"/>'
        "</testsuite></testsuites>",
        encoding="utf-8",
    )

    manifest, problems = cs.refresh_timings(2, out, "run 1", root=root)
    again, _ = cs.refresh_timings(2, out, "run 1", root=root)

    assert problems == [] and manifest == again
    assert (
        manifest["files"]["tests/a/test_1.py"] == 3235
    )  # summed and rounded to whole milliseconds
    assert (
        "tests/gone/test_9.py" not in manifest["files"]
    )  # records for files that are no longer active are dropped
    assert cw.parse_manifest(json.loads(json.dumps(manifest))).files == manifest["files"]


def test_refresh_refuses_partial_failed_or_mis_sized_runs(tmp_path: Path) -> None:
    root, out = _green_run(tmp_path, [f"tests/a/test_{n}.py" for n in range(4)])

    (out / "census-shard-1.result.json").write_text(json.dumps({"exit_code": 1}), encoding="utf-8")
    manifest, problems = cs.refresh_timings(2, out, "x", root=root)
    assert manifest is None and any("green runs" in p for p in problems)

    (out / "census-shard-1.xml").unlink()
    assert any("missing" in p for p in cs.refresh_timings(2, out, "x", root=root)[1])

    assert (
        cs.refresh_timings(3, out, "x", root=root)[0] is None
    )  # asked for three shards, only two were run


def test_the_refresh_cli_writes_the_manifest_and_refuses_otherwise(tmp_path: Path, capsys) -> None:
    root, out = _green_run(tmp_path, ["tests/a/test_1.py", "tests/a/test_2.py"])
    target = tmp_path / "timings.json"

    assert (
        cs.main(
            [
                "refresh-timings",
                "--shards",
                "2",
                "--results-dir",
                str(tmp_path / "nowhere"),
                "--source",
                "x",
                "--out",
                str(target),
            ]
        )
        == 1
    )
    assert not target.exists()
    assert "refresh refused" in capsys.readouterr().err


def test_simulation_covers_every_requested_count_and_flags_the_single_file_floor(
    tmp_path: Path,
) -> None:
    root = _tree(tmp_path, [f"tests/s{n}/test_{n}.py" for n in range(6)])
    _write_timings(
        root,
        {"tests/s0/test_0.py": 100_000, **{f"tests/s{n}/test_{n}.py": 1000 for n in range(1, 6)}},
    )

    rows = cs.simulate(8, root=root)

    assert [r["shards"] for r in rows] == list(range(1, 9))
    big = [r for r in rows if r["shards"] >= 3]
    assert all(r["slowest_s"] >= 100.0 for r in big)  # one file bounds the makespan whatever N is
    assert all(r["vs_bound"] == 1.0 for r in big)
    assert rows[-1]["empty_shards"] == 8 - 6
    assert "| shards |" in cs.render_simulation(rows)
